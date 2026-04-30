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
        # Log the full S3 error code and message so operators can act on it.
        http_status = getattr(getattr(exc, "response", None), "get", lambda *_: None)("Error", {}).get("Code", "?")
        _log.error(
            "r2_load_failed key=%s error=%r http_code=%s",
            key, str(exc), http_status,
        )
        raise RuntimeError(f"R2 download failed for key={key!r}: {exc}") from exc


def _load_from_http(url: str) -> bytes:
    """HTTP GET with a browser-compatible User-Agent (non-R2 fallback only)."""
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Ficshon/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return resp.read()
