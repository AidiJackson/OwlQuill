"""Stored images keep the format their provider actually returned.

Gemini image models answer with ``inlineData.mimeType = image/jpeg``, but
storage used to hardcode ``<uuid>.png`` / ``ContentType: image/png``, so those
images were JPEG bytes labelled PNG. These tests pin the sniffing behaviour and
the two properties that matter downstream: bytes are never transcoded, and an
unrecognised blob still stores exactly as it did before.
"""
import uuid

import pytest

from app.core import storage
from app.core.storage import detect_image_format, save_image

# Minimal valid-enough headers — sniffing only reads the leading magic bytes.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


class TestDetectImageFormat:
    def test_png_detected(self):
        assert detect_image_format(PNG_BYTES) == ("png", "image/png")

    def test_jpeg_detected(self):
        assert detect_image_format(JPEG_BYTES) == ("jpg", "image/jpeg")

    def test_gif_detected(self):
        assert detect_image_format(GIF_BYTES) == ("gif", "image/gif")

    def test_webp_detected(self):
        assert detect_image_format(WEBP_BYTES) == ("webp", "image/webp")

    def test_unknown_falls_back_to_png(self):
        """Unrecognised bytes must store as they always did, not raise."""
        assert detect_image_format(b"not an image at all") == ("png", "image/png")

    def test_empty_falls_back_to_png(self):
        assert detect_image_format(b"") == ("png", "image/png")

    def test_riff_that_is_not_webp_is_not_claimed(self):
        """A RIFF container that is not WEBP (e.g. WAV) must not be typed webp."""
        riff_wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 32
        assert detect_image_format(riff_wav) == ("png", "image/png")


class TestSaveImageLocal:
    """Local-disk mode (USE_OBJECT_STORAGE=False) — the default everywhere."""

    @pytest.fixture(autouse=True)
    def _local_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "_GENERATED_DIR", tmp_path)
        yield tmp_path

    def test_jpeg_saves_with_jpg_extension(self, _local_dir):
        path = save_image(JPEG_BYTES)
        assert path.endswith(".jpg"), f"expected .jpg, got {path}"

    def test_png_still_saves_with_png_extension(self, _local_dir):
        path = save_image(PNG_BYTES)
        assert path.endswith(".png"), f"expected .png, got {path}"

    def test_bytes_are_written_verbatim(self, _local_dir):
        """No transcoding — what the provider returned is what is stored."""
        path = save_image(JPEG_BYTES)
        written = (_local_dir / path.rsplit("/", 1)[-1]).read_bytes()
        assert written == JPEG_BYTES

    def test_returned_path_keeps_static_generated_prefix(self, _local_dir):
        """Path shape is unchanged — only the extension varies."""
        path = save_image(JPEG_BYTES)
        assert path.startswith("static/generated/")


class TestSaveImageObjectStorage:
    """R2 mode — the Content-Type sent to the bucket must match the bytes."""

    @pytest.fixture
    def captured_put(self, monkeypatch):
        calls: list[dict] = []

        class _FakeS3:
            def put_object(self, **kwargs):
                calls.append(kwargs)

        def _fake_client(*_args, **_kwargs):
            return _FakeS3()

        fake_boto3 = type("_Boto3", (), {"client": staticmethod(_fake_client)})
        monkeypatch.setitem(__import__("sys").modules, "boto3", fake_boto3)

        from app.core.config import settings
        monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", True)
        for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                    "R2_BUCKET_NAME"):
            monkeypatch.setenv(var, f"test-{var.lower()}")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://cdn.example.test/")
        return calls

    def test_jpeg_uploads_as_image_jpeg(self, captured_put):
        url = save_image(JPEG_BYTES)
        assert captured_put[0]["ContentType"] == "image/jpeg"
        assert captured_put[0]["Key"].endswith(".jpg")
        assert url.endswith(".jpg")

    def test_png_uploads_as_image_png(self, captured_put):
        url = save_image(PNG_BYTES)
        assert captured_put[0]["ContentType"] == "image/png"
        assert captured_put[0]["Key"].endswith(".png")
        assert url.endswith(".png")

    def test_body_is_not_transcoded(self, captured_put):
        save_image(JPEG_BYTES)
        assert captured_put[0]["Body"] == JPEG_BYTES
