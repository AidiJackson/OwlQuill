"""Image storage — put and get image bytes, in R2 or on local disk.

TWO PUBLIC WAYS TO PERSIST BYTES, AND THEY MEAN DIFFERENT THINGS
----------------------------------------------------------------
:func:`put_object` writes bytes at a server-minted key and returns a
:class:`StoredObject` carrying BOTH identities — the storage key and the
legacy-compatible ``file_path``. It is used by
``app.services.asset_persistence.persist_image_asset``, which is the only
supported way to create a durable image asset (Phase 4D1).

:func:`put_transient_object` writes bytes that are deliberately NOT an asset:
job scratch, pod I/O, anything whose lifetime is a single operation. It demands
a ``purpose`` so that rowlessness is a stated intention at the call site rather
than an omission nobody notices.

:func:`save_image` is the LEGACY entry point. It predates both and is retained
unchanged for the writers that have not been migrated yet. It returns a bare
string, which is exactly the property that let durable bytes be persisted with
no owner, no safety state and no lifecycle — see
``tests/test_legacy_save_image_inventory.py``, which pins its call sites so the
number cannot quietly grow.

FILE_PATH IS OVERLOADED, AND THAT IS WHY STORAGE_KEY EXISTS
-----------------------------------------------------------
``file_path`` is simultaneously a storage identity and a delivery URL: in R2
mode it holds a public https:// URL, on local disk a relative
``static/generated/<uuid>.<ext>`` path. Every reader inverts that ambiguity
(see ``character_home_media._candidate_file_paths``). ``StoredObject`` keeps the
two apart at the point of writing without changing a single reader.
"""
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Key prefix for durable image assets. Unchanged from the original
#: ``save_image`` behaviour, so nothing about delivery moves.
DURABLE_KEY_PREFIX = "generated"

#: Key prefix for bytes that are deliberately not assets. Distinct so that an
#: object's key states what it is; no existing writer uses this yet.
TRANSIENT_KEY_PREFIX = "transient"

#: Shape of a key this module mints. :func:`delete_object` refuses anything
#: else — capability by structure, not by remembering what was minted.
_MINTED_KEY_RE = re.compile(
    rf"^(?:{DURABLE_KEY_PREFIX}|{TRANSIENT_KEY_PREFIX})/[0-9a-f]{{32}}\.[a-z0-9]{{2,5}}$"
)


@dataclass(frozen=True)
class StoredObject:
    """One stored object, named both ways.

    ``storage_key`` is the object's true identity in the bucket
    (``generated/<uuid>.<ext>``) and is stable across delivery changes.
    ``file_path`` is what the database has always held and what every reader
    still resolves — a public URL in R2 mode, a relative path locally.
    """

    storage_key: str
    file_path: str

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "generated"

# Magic-byte signatures, checked in order. Providers do not all return PNG —
# Gemini image models (gemini-3.1-flash-image and friends) answer with
# ``inlineData.mimeType = image/jpeg`` — so the extension and Content-Type are
# derived from the bytes themselves rather than assumed. Sniffing here instead
# of threading a mime argument through the ~33 call sites keeps every caller
# correct without touching any of them.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")


def detect_image_format(data: bytes) -> tuple[str, str]:
    """Return ``(extension, content_type)`` for image bytes.

    Unrecognised bytes fall back to PNG, preserving the behaviour every caller
    relied on before formats were sniffed — an unknown blob is stored exactly as
    it always was rather than being rejected.
    """
    if data.startswith(_PNG_SIGNATURE):
        return "png", "image/png"
    if data.startswith(_JPEG_SIGNATURE):
        return "jpg", "image/jpeg"
    if data.startswith(_GIF_SIGNATURES):
        return "gif", "image/gif"
    # WEBP is "RIFF" + 4 size bytes + "WEBP".
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "png", "image/png"


def mint_object_key(image_bytes: bytes, *, prefix: str = DURABLE_KEY_PREFIX) -> str:
    """Mint a fresh, server-controlled object key for *image_bytes*.

    Server-controlled is the point: no caller supplies, influences or reuses a
    key, so an asset can never be written over another asset's bytes and a key
    never carries user-supplied text.

    The extension follows the ACTUAL format of the bytes
    (:func:`detect_image_format`) rather than an assumed PNG.
    """
    extension, _content_type = detect_image_format(image_bytes)
    return f"{prefix}/{uuid.uuid4().hex}.{extension}"


def _file_path_for_key(key: str) -> str:
    """The legacy ``file_path`` spelling for *key*, per storage mode.

    Byte-identical to what :func:`save_image` has always returned, which is why
    no reader had to change: R2 mode yields the public URL, local mode the
    ``static/generated/<filename>`` relative path.

    LOCAL MODE IGNORES THE KEY PREFIX ON PURPOSE. Locally there is no object
    store, only ``_GENERATED_DIR`` — one flat directory that the test fixture
    redirects wholesale and whose stored paths every reader already resolves by
    basename. Deriving a directory from the prefix would put files somewhere
    ``load_image_bytes`` does not look and somewhere the fixture does not
    redirect. The prefix is a production (R2) identity; ``storage_key`` still
    carries it, and durable and transient objects simply share a directory in
    development.
    """
    from app.core.config import settings  # lazy to avoid circular at module load

    if settings.USE_OBJECT_STORAGE:
        return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"
    return f"static/{DURABLE_KEY_PREFIX}/{Path(key).name}"


def put_object(image_bytes: bytes, *, key: str) -> StoredObject:
    """Write *image_bytes* at *key* and return both of its identities.

    The durable half of the storage API. Callers do not use this directly —
    ``asset_persistence.persist_image_asset`` does, because writing bytes and
    creating the asset row is one decision and splitting it is what produced
    every rowless object in the bucket.

    Raises whatever the underlying store raises. Nothing is caught here: a
    caller that cannot write bytes must not proceed to claim it did.
    """
    from app.core.config import settings  # lazy to avoid circular at module load

    _extension, content_type = detect_image_format(image_bytes)

    if settings.USE_OBJECT_STORAGE:
        _r2_client().put_object(
            Bucket=os.environ["R2_BUCKET_NAME"],
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
        )
    else:
        _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        (_GENERATED_DIR / Path(key).name).write_bytes(image_bytes)

    return StoredObject(storage_key=key, file_path=_file_path_for_key(key))


def delete_object(storage_key: str) -> None:
    """Delete one object this module minted. Compensation only.

    NOT a retention feature and not a way to remove an asset: the owner's delete
    is ``status = ARCHIVED``, which keeps the row, the safety decision and the
    bytes. This exists for exactly one situation — bytes were written, the
    database write then failed, and the object must not survive a row that does
    not exist.

    Refuses any key that does not match :data:`_MINTED_KEY_RE`. That is a
    structural guard, not a claim to know what was minted: a legacy
    ``file_path``, a user-supplied string or a bucket path from anywhere else is
    the wrong shape and is rejected before anything is deleted. The real
    narrowing is at the call site — ``persist_image_asset`` holds the key it
    just minted in a local variable and passes only that.

    Raises on failure. The caller decides what a failed cleanup means; it must
    never replace the error that caused the cleanup.
    """
    from app.core.config import settings  # lazy to avoid circular at module load

    if not _MINTED_KEY_RE.match(storage_key or ""):
        raise ValueError(
            f"Refusing to delete {storage_key!r}: not a key this module minted. "
            "delete_object compensates a failed write; it does not remove assets."
        )

    if settings.USE_OBJECT_STORAGE:
        _r2_client().delete_object(
            Bucket=os.environ["R2_BUCKET_NAME"], Key=storage_key
        )
        return

    (_GENERATED_DIR / Path(storage_key).name).unlink(missing_ok=True)


def put_transient_object(data: bytes, *, purpose: str) -> str:
    """Persist bytes that are deliberately NOT an asset, and say why.

    Returns a ``file_path`` string and creates no row, on purpose. Use it for
    job scratch, pod input snapshots, proof artifacts — anything whose lifetime
    is one operation and which must never appear in somebody's library.

    ``purpose`` is required and is recorded in the log line. It is the whole
    design: the difference between this function and
    :func:`persist_image_asset` must be a decision somebody made and can be
    seen to have made, not a function that happened to be shorter to call.

    NOT the legacy escape hatch. Bytes a user will see, keep, publish or be
    accountable for are durable assets and belong in
    ``asset_persistence.persist_image_asset``.
    """
    if not purpose or not purpose.strip():
        raise ValueError(
            "put_transient_object requires a purpose. If the bytes are durable "
            "user-facing material, persist them as an asset instead."
        )

    key = mint_object_key(data, prefix=TRANSIENT_KEY_PREFIX)
    stored = put_object(data, key=key)
    logger.info(
        "TRANSIENT_OBJECT purpose=%s key=%s bytes=%d", purpose, key, len(data)
    )
    return stored.file_path


def save_image(image_bytes: bytes) -> str:
    """LEGACY. Persist image bytes and return a bare file_path string.

    Behaviour is unchanged and deliberately so — it is still the writer for the
    call sites Phases 4D2/4D3/4D4 have yet to migrate, and re-implementing it on
    :func:`put_object` keeps the two from drifting while both exist.

    DO NOT CALL IT FROM NEW CODE. Returning a bare string is precisely how
    durable bytes came to be persisted with no owner, no safety state and no
    lifecycle. New durable writes go through
    ``asset_persistence.persist_image_asset``; new transient writes through
    :func:`put_transient_object`. ``tests/test_legacy_save_image_inventory.py``
    pins the current call sites and fails if another appears.

    R2 mode (USE_OBJECT_STORAGE=true): uploads to generated/<uuid>.<ext>,
    returns the full public https:// URL.
    Local mode: writes static/generated/<uuid>.<ext>, returns the relative path.
    """
    key = mint_object_key(image_bytes)
    return put_object(image_bytes, key=key).file_path


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

    R2 mode (USE_OBJECT_STORAGE=true) — file_path is https://...:
        Downloads via authenticated boto3 S3 GetObject so Cloudflare/R2
        access-control never produces a 403.  Anonymous HTTP GET is NOT used
        because R2 public-URL access is blocked for server-side requests.

    Local mode — file_path is static/generated/... or a bare filename:
        Resolves the filename and reads from _GENERATED_DIR on disk.

    Raises RuntimeError (R2 failure) or OSError (local missing file).
    Callers are responsible for catching and logging.
    """
    if file_path.startswith(("http://", "https://")):
        from app.core.config import settings  # lazy to avoid circular
        if settings.USE_OBJECT_STORAGE:
            return _load_from_r2(file_path)
        # Non-R2 public URL (e.g. legacy CDN) — plain HTTP with browser UA
        return _load_from_http(file_path)
    filename = Path(file_path.lstrip("/")).name
    return (_GENERATED_DIR / filename).read_bytes()


def _r2_client():
    """Return a boto3 S3 client configured for Cloudflare R2."""
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _load_from_r2(url: str) -> bytes:
    """Download an object from R2 using authenticated S3 GetObject.

    Derives the object key from the URL by stripping the R2_PUBLIC_URL
    prefix.  Falls back to extracting just the filename under generated/
    if the URL prefix doesn't match (e.g. after a bucket migration).

    Raises RuntimeError with HTTP status detail on failure.
    """
    import logging
    _log = logging.getLogger(__name__)

    r2_public_url = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    if r2_public_url and url.startswith(r2_public_url + "/"):
        key = url[len(r2_public_url) + 1:]
    else:
        # Fallback: assume the object lives under generated/<filename>
        key = "generated/" + Path(url).name

    _log.info("r2_load_attempt key=%s", key)
    try:
        s3 = _r2_client()
        resp = s3.get_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=key)
        data: bytes = resp["Body"].read()
        _log.info("r2_load_success key=%s bytes=%d", key, len(data))
        return data
    except Exception as exc:
        # Log the S3 error code so operators can act on it. Extracted defensively
        # on purpose: only botocore's ClientError carries a ``response`` dict, and
        # the previous one-liner
        #     getattr(getattr(exc, "response", None), "get", lambda *_: None)("Error", {}).get("Code", "?")
        # returned None for every other exception type and then called .get on it.
        # That made the *handler* raise AttributeError("'NoneType' object has no
        # attribute 'get'"), which replaced the real exception — a
        # ModuleNotFoundError for boto3 — with a meaningless one at all six
        # reference loads. Diagnostics must never outrank the error they describe.
        error_code = "?"
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            error = response.get("Error")
            if isinstance(error, dict):
                error_code = error.get("Code", "?")
        _log.error(
            "r2_load_failed key=%s exc_type=%s error=%r error_code=%s",
            key, type(exc).__name__, str(exc), error_code,
        )
        raise RuntimeError(
            f"R2 download failed for key={key!r}: {type(exc).__name__}: {exc}"
        ) from exc


def _load_from_http(url: str) -> bytes:
    """HTTP GET with a browser-compatible User-Agent (non-R2 fallback only)."""
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Ficshon/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return resp.read()
