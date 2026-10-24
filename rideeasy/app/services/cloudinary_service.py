"""Small signed Cloudinary REST client for private server-side image workflows."""
import hashlib
import logging
import time
from urllib.parse import urlparse

import requests
from flask import current_app

logger = logging.getLogger("rideeasy.cloudinary")


class CloudinaryError(RuntimeError):
    """Raised when an image cannot be uploaded, fetched, or deleted."""


class CloudinaryService:
    TIMEOUT = (5, 20)
    MAX_FETCH_BYTES = 8 * 1024 * 1024

    @classmethod
    def _credentials(cls):
        cloud_name = current_app.config.get("CLOUDINARY_CLOUD_NAME", "").strip()
        api_key = current_app.config.get("CLOUDINARY_API_KEY", "").strip()
        api_secret = current_app.config.get("CLOUDINARY_API_SECRET", "").strip()
        if not all((cloud_name, api_key, api_secret)):
            raise CloudinaryError(
                "Image storage is not configured. Set CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET."
            )
        return cloud_name, api_key, api_secret

    @staticmethod
    def _signature(params, api_secret):
        signed_values = "&".join(
            f"{key}={params[key]}" for key in sorted(params)
            if params[key] is not None
        )
        return hashlib.sha1(f"{signed_values}{api_secret}".encode("utf-8")).hexdigest()

    @classmethod
    def upload(cls, image_bytes, folder, public_id):
        cloud_name, api_key, api_secret = cls._credentials()
        params = {
            "folder": folder,
            "overwrite": "true",
            "public_id": public_id,
            "timestamp": int(time.time()),
        }
        payload = {**params, "api_key": api_key}
        payload["signature"] = cls._signature(params, api_secret)
        try:
            response = requests.post(
                f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
                data=payload,
                files={"file": ("image.jpg", image_bytes, "image/jpeg")},
                timeout=cls.TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            logger.warning("Cloudinary image upload failed: %s", error)
            raise CloudinaryError("The image could not be saved to cloud storage. Please try again.") from error
        if not result.get("public_id") or not result.get("secure_url"):
            raise CloudinaryError("Cloud image storage returned an incomplete upload response.")
        return {"public_id": result["public_id"], "secure_url": result["secure_url"]}

    @classmethod
    def delete(cls, public_id):
        if not public_id:
            return
        cloud_name, api_key, api_secret = cls._credentials()
        params = {
            "public_id": public_id,
            "timestamp": int(time.time()),
        }
        payload = {**params, "api_key": api_key}
        payload["signature"] = cls._signature(params, api_secret)
        try:
            response = requests.post(
                f"https://api.cloudinary.com/v1_1/{cloud_name}/image/destroy",
                data=payload,
                timeout=cls.TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as error:
            logger.warning("Cloudinary asset cleanup failed for %s: %s", public_id, error)
            raise CloudinaryError("The old cloud image could not be removed.") from error
        if result.get("result") not in {"ok", "not found"}:
            raise CloudinaryError("Cloud image storage did not confirm asset removal.")

    @classmethod
    def fetch(cls, image_url):
        cloud_name, _, _ = cls._credentials()
        parsed = urlparse(image_url or "")
        if parsed.scheme != "https" or parsed.hostname != f"{cloud_name}.res.cloudinary.com":
            raise CloudinaryError("Stored image URL is not a trusted Cloudinary image.")
        try:
            with requests.get(image_url, stream=True, timeout=cls.TIMEOUT) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                    raise CloudinaryError("Cloud storage returned an unsupported image type.")
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > cls.MAX_FETCH_BYTES:
                        raise CloudinaryError("Cloud image exceeds the maximum allowed size.")
                    chunks.append(chunk)
                return {"mime_type": content_type, "data": b"".join(chunks)}
        except requests.RequestException as error:
            logger.warning("Cloudinary image fetch failed: %s", error)
            raise CloudinaryError("The vehicle photo is temporarily unavailable.") from error
