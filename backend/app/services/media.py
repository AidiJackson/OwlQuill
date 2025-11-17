"""Media storage service for handling file uploads."""
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.media import MediaAsset, MediaKind
from app.models.user import User


class MediaService:
    """Service for handling media file uploads and storage."""

    def __init__(self):
        self.media_root = Path(settings.MEDIA_ROOT)
        self.media_base_url = settings.MEDIA_BASE_URL
        self.max_size = settings.MAX_IMAGE_SIZE_BYTES
        self.allowed_types = settings.ALLOWED_IMAGE_CONTENT_TYPES

    def _ensure_directory(self, path: Path) -> None:
        """Ensure directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    def _get_file_extension(self, filename: str, content_type: str) -> str:
        """Get file extension from filename or content type."""
        # Try to get from filename first
        if "." in filename:
            return filename.rsplit(".", 1)[1].lower()

        # Fallback to content type
        type_map = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }
        return type_map.get(content_type, "jpg")

    def _validate_file(self, file: UploadFile) -> None:
        """Validate file size and content type."""
        # Check content type
        if file.content_type not in self.allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not allowed. Allowed types: {', '.join(self.allowed_types)}"
            )

        # Check file size by reading in chunks
        file.file.seek(0, 2)  # Seek to end
        size = file.file.tell()
        file.file.seek(0)  # Reset to beginning

        if size > self.max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File size {size} bytes exceeds maximum {self.max_size} bytes ({self.max_size / 1024 / 1024:.1f} MB)"
            )

    def _generate_storage_path(self, kind: MediaKind, extension: str) -> tuple[Path, str]:
        """Generate storage path for a file.

        Returns:
            Tuple of (absolute_path, relative_path)
        """
        now = datetime.utcnow()
        year = now.strftime("%Y")
        month = now.strftime("%m")

        # Generate unique filename
        unique_id = uuid.uuid4().hex
        filename = f"{unique_id}.{extension}"

        # Build path: kind/YYYY/MM/filename.ext
        relative_path = Path(kind.value) / year / month / filename
        absolute_path = self.media_root / relative_path

        return absolute_path, str(relative_path).replace("\\", "/")

    def _save_file(self, file: UploadFile, path: Path) -> None:
        """Save uploaded file to disk."""
        self._ensure_directory(path.parent)

        with open(path, "wb") as f:
            # Read and write in chunks
            chunk_size = 1024 * 1024  # 1 MB chunks
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)

    async def upload_media(
        self,
        file: UploadFile,
        owner: User,
        kind: MediaKind,
        db: Session
    ) -> MediaAsset:
        """Upload and store a media file.

        Args:
            file: The uploaded file
            owner: The user uploading the file
            kind: The type of media being uploaded
            db: Database session

        Returns:
            MediaAsset instance with file information

        Raises:
            HTTPException: If validation fails or storage errors occur
        """
        # Validate file
        self._validate_file(file)

        # Get file extension
        extension = self._get_file_extension(file.filename or "file", file.content_type or "image/jpeg")

        # Generate storage path
        absolute_path, relative_path = self._generate_storage_path(kind, extension)

        # Save file to disk
        try:
            self._save_file(file, absolute_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

        # Get file size
        file_size = absolute_path.stat().st_size

        # Generate URL
        url = f"{self.media_base_url}/{relative_path}"

        # Create database record
        media = MediaAsset(
            owner_id=owner.id,
            kind=kind,
            filename=file.filename or "upload",
            path=relative_path,
            url=url,
            content_type=file.content_type or "image/jpeg",
            size_bytes=file_size,
        )

        db.add(media)
        db.commit()
        db.refresh(media)

        return media

    def delete_media(self, media: MediaAsset, db: Session) -> None:
        """Delete a media file and its database record.

        Args:
            media: The media asset to delete
            db: Database session
        """
        # Delete file from disk
        file_path = self.media_root / media.path
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                # Log error but continue with DB deletion
                print(f"Warning: Failed to delete file {file_path}: {e}")

        # Delete from database
        db.delete(media)
        db.commit()


# Singleton instance
media_service = MediaService()
