"""Sprint 34 — regression protection for test/production isolation.

These tests prove the suite cannot touch production infrastructure:
object storage is off, R2 credentials are stripped, generated media lands in
a pytest temp dir, and no database lives inside the repository. If any of
these fail, an isolation guarantee has been silently reintroduced — fix the
leak, never the assertion.
"""
import os
from pathlib import Path

# Repo root = parent of backend/ (this file lives in backend/tests/)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_REPO_STATIC_GENERATED = _BACKEND_DIR / "static" / "generated"

_R2_VARS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
)


def _is_inside(path: Path, ancestor: Path) -> bool:
    try:
        path.resolve().relative_to(ancestor.resolve())
        return True
    except ValueError:
        return False


def test_object_storage_disabled():
    """settings.USE_OBJECT_STORAGE must be False for the entire suite."""
    from app.core.config import settings

    assert settings.USE_OBJECT_STORAGE is False
    assert os.environ.get("USE_OBJECT_STORAGE") == "false"


def test_production_r2_credentials_unavailable():
    """R2 credentials must be absent so an accidental upload raises KeyError."""
    for var in _R2_VARS:
        assert var not in os.environ, (
            f"{var} is present in the test environment — an accidental R2 "
            "upload would silently reach the production bucket"
        )


def test_live_image_provider_keys_unavailable():
    """Live provider keys must be absent so generation degrades to the stub.

    With GOOGLE_AI_API_KEY present, every character-locking test silently
    called the real Gemini image API (and, pre-Sprint-34, uploaded the
    results to the production R2 bucket).
    """
    for var in (
        "OPENAI_API_KEY",
        "FAL_KEY",
        "GOOGLE_AI_API_KEY",
        "TOGETHER_API_KEY",
        "REPLICATE_API_TOKEN",
        "RUNPOD_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        assert var not in os.environ, (
            f"{var} is present in the test environment — tests would call "
            "the live provider API"
        )


def test_save_image_writes_to_temp_dir_not_repo(generated_media_dir):
    """save_image must write under the pytest temp dir, never backend/static/."""
    from app.core import storage

    before = set(p.name for p in _REPO_STATIC_GENERATED.glob("*.png")) \
        if _REPO_STATIC_GENERATED.exists() else set()

    stored = storage.save_image(b"\x89PNG-sprint34-isolation-probe")

    # Return value keeps its historical shape...
    assert stored.startswith("static/generated/")
    filename = stored.rsplit("/", 1)[-1]

    # ...but the bytes land in the temp dir, not the repository.
    assert (generated_media_dir / filename).exists()
    assert _is_inside(generated_media_dir / filename, generated_media_dir)
    assert not (_REPO_STATIC_GENERATED / filename).exists()
    if _REPO_STATIC_GENERATED.exists():
        after = set(p.name for p in _REPO_STATIC_GENERATED.glob("*.png"))
        assert after == before, "test run added files to backend/static/generated/"


def test_generated_dir_constants_all_redirected(generated_media_dir):
    """Every module-level _GENERATED_DIR must point at the temp dir."""
    import app.core.storage as storage
    from app.api.routes import (
        character_visual, characters, image_generator, scene_images, users,
    )

    for mod in (storage, character_visual, characters, image_generator,
                scene_images, users):
        assert mod._GENERATED_DIR == generated_media_dir, (
            f"{mod.__name__}._GENERATED_DIR still points at "
            f"{mod._GENERATED_DIR} — writes could reach the repository"
        )


def test_fixture_database_outside_repository():
    """The test-fixture SQLite file must not live inside the repository."""
    from tests.conftest import engine

    db_path = Path(engine.url.database)
    assert not _is_inside(db_path, _REPO_ROOT), (
        f"test database {db_path} is inside the repository"
    )


def test_app_engine_database_outside_repository_and_not_postgres():
    """The app's own engine must use a throwaway SQLite file, never Postgres.

    Startup seeds (admin/starter/invite) run against this engine at every
    TestClient startup — if it pointed at the Replit DATABASE_URL, tests
    would write to the live database.
    """
    from app.core.database import engine as app_engine

    assert app_engine.url.get_backend_name() == "sqlite", (
        f"app engine is {app_engine.url.get_backend_name()} — tests would "
        "touch the live database via startup seeds/SessionLocal"
    )
    db_path = Path(app_engine.url.database)
    assert not _is_inside(db_path, _REPO_ROOT), (
        f"app-engine database {db_path} is inside the repository"
    )
