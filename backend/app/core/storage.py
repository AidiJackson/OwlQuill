"""Image storage — save PNG bytes to R2 or local disk.

Returns a full https:// URL when settings.USE_OBJECT_STORAGE is True (R2),
or a relative ``static/generated/<uuid>.png`` path otherwise.
"""
import os
import uuid
from pathlib import Path

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "generated"


def save_image(png_bytes: bytes) -> str:
    """Persist PNG bytes and return a storable file_path string.

    R2 mode (USE_OBJECT_STORAGE=true in .env):
        Uploads to Cloudflare R2 under generated/<uuid>.png.
        Returns the full public https:// URL.

    Local mode (default):
        Writes to static/generated/<uuid>.png on disk.
        Returns the relative path, e.g. ``static/generated/<uuid>.png``.
    """
    from app.core.config import settings  # lazy to avoid circular at module load

    filename = f"{uuid.uuid4().hex}.png"

    if settings.USE_OBJECT_STORAGE:
        import boto3  # lazy import — only needed in R2 mode
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        key = f"generated/{filename}"
        s3.put_object(
            Bucket=os.environ["R2_BUCKET_NAME"],
            Key=key,
            Body=png_bytes,
            ContentType="image/png",
        )
        return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"

    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (_GENERATED_DIR / filename).write_bytes(png_bytes)
    return f"static/generated/{filename}"


def file_path_to_url(file_path: str) -> str:
    """Convert a stored file_path to a servable URL.

    Absolute http(s) URLs are returned unchanged.
    Relative local paths are prefixed with /static/ as needed.
    """
    if file_path.startswith(("http://", "https://")):
        return file_path
    path = file_path.lstrip("/")
    return f"/{path}" if path.startswith("static/") else f"/static/{path}"


def load_image_bytes(file_path: str) -> bytes:
    """Load image bytes from a stored file_path — works for R2 URLs and local paths.

    R2 mode  — file_path is https://...: fetches via HTTP GET (30 s timeout).
    Local mode — file_path is static/generated/... or a bare filename:
                 resolves the filename and reads from _GENERATED_DIR.

    Raises urllib.error.URLError on network failure or OSError on missing
    local file.  Callers are responsible for catching and logging.
    """
    if file_path.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(file_path, timeout=30) as resp:  # noqa: S310
            return resp.read()
    filename = Path(file_path.lstrip("/")).name
    return (_GENERATED_DIR / filename).read_bytes()
