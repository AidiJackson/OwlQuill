"""Image storage — save image bytes to R2 or local disk.

Returns a full https:// URL when settings.USE_OBJECT_STORAGE is True (R2),
or a relative ``static/generated/<uuid>.<ext>`` path otherwise.
"""
import os
import uuid
from pathlib import Path

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


def save_image(image_bytes: bytes) -> str:
    """Persist image bytes and return a storable file_path string.

    The stored extension and Content-Type follow the actual format of
    ``image_bytes`` (see :func:`detect_image_format`); bytes are never
    transcoded.

    R2 mode (USE_OBJECT_STORAGE=true in .env):
        Uploads to Cloudflare R2 under generated/<uuid>.<ext>.
        Returns the full public https:// URL.

    Local mode (default):
        Writes to static/generated/<uuid>.<ext> on disk.
        Returns the relative path, e.g. ``static/generated/<uuid>.jpg``.
    """
    from app.core.config import settings  # lazy to avoid circular at module load

    extension, content_type = detect_image_format(image_bytes)
    filename = f"{uuid.uuid4().hex}.{extension}"

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
            Body=image_bytes,
            ContentType=content_type,
        )
        return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"

    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (_GENERATED_DIR / filename).write_bytes(image_bytes)
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
