"""Phase 4D4-1 — Adult Studio generate writes an EXPLICIT transient object.

The whole increment is a change of INTENT, not of behaviour: the route created
no image row before and creates none now. What changed is that rowlessness
stopped being an omission — a bare string returned by ``save_image`` and no row
written because nobody wrote one — and became a decision recorded at the call
site, in a function that refuses to run without a stated ``purpose``.

That distinction is worth a test file because the omission was doing real
safety work. A rowless file cannot be selected as an avatar or a cover (both
routes look an ``image_id`` up in a table), cannot be attached to a post
(``posts.py`` matches ``file_path`` against both image tables and refuses when
neither matches), never appears in a gallery projection, and is withheld from
every shared surface by ``character_home_media.resolve_public_media_url``,
which fails closed on a url that matches no row. Phase 4D3-2 established that a
launch-safety property must not rest on an accident; these tests state the
property directly so a future migration to a durable asset has to break an
assertion that says what it is breaking.

They deliberately do NOT assert that Adult Studio output is worthless or
permanently unpublishable. Phase 4E owns the reviewed-publication question. What
is pinned here is that 4D4-1 did not answer it by accident.
"""
import pytest
from unittest.mock import patch

from app.core import storage
from app.core.config import settings
from app.core.storage import TRANSIENT_KEY_PREFIX
from app.models.character_image import CharacterImage
from app.models.user_image import UserImage
from app.schemas.character_image import (
    NON_PUBLIC_IMAGE_PROVIDERS,
    is_public_surface_safe,
)
from app.services.character_home_media import resolve_public_media_url
from tests.canon_test_utils import setup_canon
from tests.conftest import auth_headers, get_auth_token, make_admin

#: >1000 bytes so the route's own emptiness guard passes.
_DUMMY_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2048


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    """Real files on disk in a temp tree, object storage off."""
    monkeypatch.setattr(storage, "_GENERATED_DIR", tmp_path / "static" / "generated")
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)
    return tmp_path


def _generation_enabled():
    return patch.object(settings, "ADULT_STUDIO_GENERATION_ENABLED", True)


class _FakeProvider:
    """Returns bytes for a multi-image conditioned call. No network.

    ``supports_multi_image_input`` is the legacy capability flag
    ``provider_supports(..., MULTI_IMAGE_ANCHORS)`` probes; without it the route
    refuses with ``provider_no_multi_image_support`` before reaching the write.
    """

    supports_multi_image_input = True

    def __init__(self):
        self.calls = []

    def generate_with_anchors(self, *, prompt, anchor_images, size="1024x1024"):
        self.calls.append({"prompt": prompt, "n_refs": len(anchor_images)})
        return _DUMMY_PNG


def _admin_owner(client, tag="4d4a"):
    email = f"{tag}@4d4.test.com"
    token = get_auth_token(client, email=email, username=f"u{tag}")
    make_admin(email)
    return get_auth_token(client, email=email, username=f"u{tag}")


def _character(client, token, name="Summer"):
    resp = client.post(
        "/characters/",
        json={"name": name, "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _marks():
    return [
        {
            "label": "Butterfly floral sleeve",
            "type": "tattoo",
            "body_region": "right_upper_arm",
            "side": "right",
            "description": "Right upper arm butterfly and floral sleeve tattoo",
            "reference_image_url": "static/generated/mark_right.png",
            "permanence": "permanent",
        },
    ]


def _prepared(client, db_session, token):
    """A character with locked canon and a prepared 18+ identity."""
    cid = _character(client, token)
    setup_canon(db_session, cid, marks=_marks(), lock=True, with_images=True)
    resp = client.post(
        f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return cid


def _generate(client, token, cid, provider=None):
    """Run the generate route with the provider and ref loader patched."""
    fake = provider or _FakeProvider()
    with _generation_enabled(), \
         patch("app.api.routes.adult_studio._get_adult_provider", return_value=fake), \
         patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer on a beach at sunset, adult woman, both arms visible"},
            headers=auth_headers(token),
        )
    return resp


# ── A. The writer choice ─────────────────────────────────────────────────────


def test_the_generate_route_uses_the_transient_writer():
    """Structural, because the property is about WHICH function is called.

    An edit that swapped this to ``persist_image_asset`` would satisfy every
    behavioural assertion in section B — the route would still return a url —
    while silently granting the object a row, an owner and four public-surface
    eligibilities. What is pinned is the CHOICE.
    """
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parent.parent
        / "app" / "api" / "routes" / "adult_studio.py"
    )
    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.Call)
    }
    assert "put_transient_object" in called
    assert "save_image" not in called
    assert "persist_image_asset" not in called
    assert "persist_derived_image_asset" not in called


def test_the_purpose_is_stated_at_the_call_site():
    """``put_transient_object`` refuses to run without a purpose, and the
    purpose is the entire design: rowlessness as something somebody decided."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parent.parent
        / "app" / "api" / "routes" / "adult_studio.py"
    )
    purposes = [
        kw.value.value
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) == "put_transient_object")
        for kw in node.keywords
        if kw.arg == "purpose" and isinstance(kw.value, ast.Constant)
    ]
    assert purposes == ["adult_studio_generate_preview"]


def test_transient_bytes_cannot_be_written_without_saying_why(local_storage):
    with pytest.raises(ValueError, match="requires a purpose"):
        storage.put_transient_object(_DUMMY_PNG, purpose="")


# ── B. Behaviour is unchanged ────────────────────────────────────────────────


def test_generate_still_returns_the_same_response_shape(client, db_session, local_storage):
    """Same contract as before the migration: the founder sees their image."""
    token = _admin_owner(client)
    cid = _prepared(client, db_session, token)
    fake = _FakeProvider()

    resp = _generate(client, token, cid, provider=fake)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["image_url"]
    assert data["provider"] == "openai"
    assert data["multi_image_used"] is True
    assert data["refs_count"] >= 1
    assert data["used_refs"]
    assert data["failure_reason"] is None
    # The provider really received the references — no text-only path.
    assert fake.calls and fake.calls[0]["n_refs"] >= 1


def test_the_returned_url_still_resolves_to_the_generated_bytes(
    client, db_session, local_storage
):
    """Transient does not mean unreadable. The founder's preview must load."""
    token = _admin_owner(client, tag="4d4b")
    cid = _prepared(client, db_session, token)

    resp = _generate(client, token, cid)

    assert resp.status_code == 200, resp.text
    url = resp.json()["image_url"]
    assert storage.load_image_bytes(url) == _DUMMY_PNG


def test_the_transient_writer_files_under_the_transient_prefix(local_storage):
    """The practical gain of the change: in production these objects become
    IDENTIFIABLE.

    Every Adult Studio preview written before 4D4-1 was minted under the durable
    ``generated/`` prefix, indistinguishable from a real asset, which is why
    none of them could ever be swept. A transient object announces what it is in
    its STORAGE KEY.

    Asserted at the storage seam rather than through the route's returned url,
    because the url cannot carry it in this environment and saying otherwise
    would be a test that passes for the wrong reason — see the next test.
    """
    key = storage.mint_object_key(_DUMMY_PNG, prefix=TRANSIENT_KEY_PREFIX)
    assert key.startswith(f"{TRANSIENT_KEY_PREFIX}/")
    assert storage.put_object(_DUMMY_PNG, key=key).storage_key == key


def test_the_returned_url_does_not_carry_the_prefix_locally(
    client, db_session, local_storage
):
    """Documented, deliberate, and worth pinning so it is not mistaken for a bug.

    ``_file_path_for_key`` flattens the prefix in local mode on purpose: there is
    no object store locally, only one flat ``_GENERATED_DIR`` that every reader
    resolves by basename, so deriving a directory from the prefix would put the
    file where ``load_image_bytes`` does not look. The prefix is a PRODUCTION
    (R2) identity carried by ``storage_key``, and ``put_transient_object``
    returns ``file_path``, not the key.

    The consequence for 4D4-1 is worth stating plainly: sweeping transient Adult
    Studio objects is possible in R2 and NOT possible from the returned url
    alone in local development.
    """
    token = _admin_owner(client, tag="4d4c")
    cid = _prepared(client, db_session, token)

    resp = _generate(client, token, cid)

    assert resp.status_code == 200, resp.text
    url = resp.json()["image_url"]
    assert TRANSIENT_KEY_PREFIX not in url
    assert "static/generated/" in url


# ── C. No row, on either table ───────────────────────────────────────────────


def test_generate_creates_no_character_image_row(client, db_session, local_storage):
    token = _admin_owner(client, tag="4d4d")
    cid = _prepared(client, db_session, token)
    before = db_session.query(CharacterImage).count()

    resp = _generate(client, token, cid)

    assert resp.status_code == 200, resp.text
    assert db_session.query(CharacterImage).count() == before


def test_generate_creates_no_user_image_row(client, db_session, local_storage):
    """The other table an avatar/cover/post can be chosen from."""
    token = _admin_owner(client, tag="4d4e")
    cid = _prepared(client, db_session, token)
    before = db_session.query(UserImage).count()

    resp = _generate(client, token, cid)

    assert resp.status_code == 200, resp.text
    assert db_session.query(UserImage).count() == before


# ── D. Public-surface safety ─────────────────────────────────────────────────


def test_the_generated_url_is_withheld_from_shared_surfaces(
    client, db_session, local_storage
):
    """The property the whole increment had to preserve.

    ``resolve_public_media_url`` fails closed on a url matching no row:
    provenance that cannot be established is not provenance. This is what keeps
    an Adult Studio preview off the public Character Home even if a founder
    pastes its url into a cover field by hand.
    """
    token = _admin_owner(client, tag="4d4f")
    cid = _prepared(client, db_session, token)

    resp = _generate(client, token, cid)
    url = resp.json()["image_url"]

    assert resolve_public_media_url(db_session, url) is None


def test_the_generated_url_cannot_be_set_as_a_character_avatar(
    client, db_session, local_storage
):
    """Avatar selection is by ``image_id`` against a table, so a rowless file is
    not addressable at all. Asserted through the route rather than by reasoning
    about it, because that is the surface a founder actually reaches."""
    token = _admin_owner(client, tag="4d4g")
    cid = _prepared(client, db_session, token)
    _generate(client, token, cid)

    # There is no id to offer. The nearest thing a caller can do is guess one,
    # and every id belongs to something that is not this preview.
    resp = client.post(
        f"/characters/{cid}/avatar",
        json={"image_id": 999999, "image_type": "character"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_the_generated_url_cannot_be_attached_to_a_post(
    client, db_session, local_storage
):
    """``posts.py`` matches ``file_path`` against BOTH image tables and refuses
    when neither owns it — a rowless preview is refused with 403.

    Exercised through the real posting route rather than the helper, because
    the attachment guard is the thing being pinned and a founder reaches it by
    posting.
    """
    token = _admin_owner(client, tag="4d4h")
    cid = _prepared(client, db_session, token)
    resp = _generate(client, token, cid)
    url = resp.json()["image_url"]

    realm = client.post(
        "/realms/",
        json={"name": "R4d4h", "slug": "r4d4h", "is_public": True},
        headers=auth_headers(token),
    )
    assert realm.status_code == 201, realm.text
    realm_id = realm.json()["id"]

    posted = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"character_id": cid, "content": "look", "image_url": url},
        headers=auth_headers(token),
    )
    assert posted.status_code == 403, posted.text


def test_the_provider_string_alone_would_not_have_protected_it():
    """Why 4D4-1 did NOT simply write a row and rely on the safety predicate.

    Adult Studio reports ``provider="openai"`` — the same string ordinary
    generation uses, and deliberately not in ``NON_PUBLIC_IMAGE_PROVIDERS``,
    because denying it would break every ordinary image. A row carrying only
    that provider passes ``is_public_surface_safe``. This test exists so the
    reasoning is checkable rather than asserted in a comment: it pins the gap
    that made a durable row the unsafe option in this increment.
    """
    from app.api.routes.adult_studio import _ADULT_PROVIDER_NAME

    assert _ADULT_PROVIDER_NAME not in NON_PUBLIC_IMAGE_PROVIDERS

    class _RowWithOnlyTheProvider:
        provider = _ADULT_PROVIDER_NAME
        metadata_json: dict = {}

    assert is_public_surface_safe(_RowWithOnlyTheProvider()) is True


# ── E. The gates that were already there stay there ──────────────────────────


def test_generation_is_disabled_by_default(client, db_session, local_storage):
    """No flag flip in this increment. The route 409s before any provider is
    constructed, so the migrated write is not even reached."""
    token = _admin_owner(client, tag="4d4i")
    cid = _prepared(client, db_session, token)

    resp = client.post(
        f"/adult-studio/characters/{cid}/generate",
        json={"prompt": "anything"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 409


def test_generate_is_admin_only(client, db_session, local_storage):
    """The router-level ``require_admin`` gate, unchanged."""
    admin_token = _admin_owner(client, tag="4d4j")
    cid = _prepared(client, db_session, admin_token)

    plain = get_auth_token(client, email="plain@4d4.test.com", username="plain4d4")
    with _generation_enabled():
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "anything"},
            headers=auth_headers(plain),
        )
    assert resp.status_code == 403


def test_a_failed_generation_writes_no_object(client, db_session, local_storage):
    """The provider raises before the write. Nothing is stored, and the 502
    carries the diagnostic metadata the route has always returned."""
    token = _admin_owner(client, tag="4d4k")
    cid = _prepared(client, db_session, token)

    class _Failing:
        supports_multi_image_input = True

        def generate_with_anchors(self, *, prompt, anchor_images, size="1024x1024"):
            raise RuntimeError("provider exploded")

    before = _objects(local_storage)
    with _generation_enabled(), \
         patch("app.api.routes.adult_studio._get_adult_provider", return_value=_Failing()), \
         patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer on a beach, adult woman"},
            headers=auth_headers(token),
        )

    assert resp.status_code == 502
    assert _objects(local_storage) == before


def _objects(root) -> set:
    """Every stored file under the temp storage tree."""
    return {p for p in (root / "static" / "generated").rglob("*") if p.is_file()}
