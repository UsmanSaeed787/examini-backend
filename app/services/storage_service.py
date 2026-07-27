import cloudinary
import cloudinary.uploader
import httpx
from app.config import settings

_configured = False


def _ensure_config():
    """Configure the Cloudinary SDK lazily so the app can start without credentials."""
    global _configured
    if not _configured:
        if not settings.cloudinary_cloud_name:
            raise ValueError("Cloudinary is not configured (CLOUDINARY_CLOUD_NAME missing)")
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )
        _configured = True


class StorageService:
    """File storage backed by Cloudinary (resource_type='raw' supports any file type)."""

    @staticmethod
    def upload_file(content: bytes, public_id: str) -> str:
        """Upload raw bytes and return the permanent https URL."""
        _ensure_config()
        result = cloudinary.uploader.upload(
            content,
            resource_type="raw",
            public_id=f"examini/materials/{public_id}",
            overwrite=False,
        )
        return result["secure_url"]

    @staticmethod
    def fetch_file(url: str) -> bytes:
        """Fetch file bytes back from storage (endpoints proxy these so auth stays enforced)."""
        response = httpx.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        return response.content
