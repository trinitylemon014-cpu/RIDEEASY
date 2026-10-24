"""Car photos that drivers upload so passengers can recognise the exact car arriving.

Images are validated and re-encoded with Pillow (removing EXIF data such as GPS
coordinates), resized, and stored in Cloudinary. Existing database-stored photos remain
readable during migration.
"""
import base64
import io
import re

from PIL import Image, ImageOps, UnidentifiedImageError

from app.repositories.database import get_db
from app.services.cloudinary_service import CloudinaryService

SLOTS = ("FRONT", "SIDE", "BACK")

SLOT_INFO = {
    "FRONT": {
        "label": "Front",
        "tip": "Stand a few steps back so the whole front and the number plate are clear.",
    },
    "SIDE": {
        "label": "Side",
        "tip": "Show the full side of the car so the colour and shape are easy to see.",
    },
    "BACK": {
        "label": "Back",
        "tip": "Show the whole back of the car with the number plate readable.",
    },
}

MAX_UPLOAD_BYTES = 8 * 1024 * 1024      # raw upload, per photo
MAX_PIXELS = 40_000_000                 # guards against decompression bombs
MIN_EDGE_PX = 400                       # smaller photos are too blurry to help
MAX_EDGE_PX = 1280                      # stored size
JPEG_QUALITY = 82
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

# Used for the colour dot next to the car description on the passenger page.
COLOR_SWATCHES = (
    ("white", "#f8fafc"), ("pearl", "#f1f5f9"), ("silver", "#c0c6cf"), ("grey", "#8b95a1"),
    ("gray", "#8b95a1"), ("black", "#111827"), ("red", "#dc2626"), ("maroon", "#7f1d1d"),
    ("blue", "#2563eb"), ("navy", "#1e3a8a"), ("green", "#16a34a"), ("yellow", "#facc15"),
    ("gold", "#d4a017"), ("champagne", "#e7d3a7"), ("beige", "#d6c7a1"), ("brown", "#7c4a21"),
    ("orange", "#f97316"), ("purple", "#7c3aed"), ("pink", "#ec4899"),
)


class PhotoError(ValueError):
    """A photo could not be accepted; the message is safe to show to the driver."""


class VehiclePhotoService:
    # ------------------------------------------------------------------ images
    @staticmethod
    def process_image(raw, max_upload_bytes=MAX_UPLOAD_BYTES, min_edge_px=MIN_EDGE_PX):
        """Validate an uploaded image and return clean, resized JPEG bytes."""
        if not raw:
            raise PhotoError("The file is empty.")
        if len(raw) > max_upload_bytes:
            raise PhotoError(f"The photo is larger than {max_upload_bytes // (1024 * 1024)} MB.")
        try:
            image = Image.open(io.BytesIO(raw))
            detected_format = image.format
            width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise PhotoError("That file is not a photo we can read. Use a JPG, PNG or WebP image.")
        if detected_format not in ALLOWED_FORMATS:
            raise PhotoError("Use a JPG, PNG or WebP photo.")
        if width * height > MAX_PIXELS:
            raise PhotoError("The photo has too many pixels. Take it again at a lower resolution.")
        if min(width, height) < min_edge_px:
            raise PhotoError(f"The photo is too small. Use one at least {min_edge_px} pixels on each side.")
        try:
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
            output = io.BytesIO()
            # No exif= argument: location and device metadata are dropped.
            image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        except (OSError, ValueError, Image.DecompressionBombError):
            raise PhotoError("That photo could not be processed. Try a different one.")
        return output.getvalue()

    # ----------------------------------------------------------------- storage
    @staticmethod
    def save_photo(vehicle_id, slot, jpeg_bytes):
        if slot not in SLOTS:
            raise PhotoError("Unknown photo position.")
        cloud_image = CloudinaryService.upload(
            jpeg_bytes,
            folder=f"rideeasy/vehicles/{vehicle_id}",
            public_id=slot.lower(),
        )
        get_db().execute(
            """INSERT INTO vehicle_photos
               (vehicle_id, slot, mime_type, image_data, byte_size,
                cloudinary_public_id, cloudinary_url, updated_at)
               VALUES (?, ?, 'image/jpeg', '', ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(vehicle_id, slot) DO UPDATE SET
                   mime_type = excluded.mime_type,
                   image_data = '',
                   byte_size = excluded.byte_size,
                   cloudinary_public_id = excluded.cloudinary_public_id,
                   cloudinary_url = excluded.cloudinary_url,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                vehicle_id, slot, len(jpeg_bytes),
                cloud_image["public_id"], cloud_image["secure_url"],
            ),
        )

    @staticmethod
    def get_photo(vehicle_id, slot):
        if slot not in SLOTS:
            return None
        row = get_db().fetchone(
            """SELECT mime_type, image_data, cloudinary_url
               FROM vehicle_photos WHERE vehicle_id = ? AND slot = ?""",
            (vehicle_id, slot),
        )
        if not row:
            return None
        if row.get("cloudinary_url"):
            return CloudinaryService.fetch(row["cloudinary_url"])
        try:
            return {"mime_type": row["mime_type"], "data": base64.b64decode(row["image_data"])}
        except (ValueError, TypeError):
            return None

    @staticmethod
    def delete_photo(vehicle_id, slot):
        if slot not in SLOTS:
            return 0
        row = get_db().fetchone(
            "SELECT cloudinary_public_id FROM vehicle_photos WHERE vehicle_id = ? AND slot = ?",
            (vehicle_id, slot),
        )
        deleted = get_db().execute(
            "DELETE FROM vehicle_photos WHERE vehicle_id = ? AND slot = ?", (vehicle_id, slot)
        )
        if deleted and row and row.get("cloudinary_public_id"):
            CloudinaryService.delete(row["cloudinary_public_id"])
        return deleted

    @staticmethod
    def photo_status(vehicle_id):
        """One entry per slot, in display order, with a cache-busting version for the URL."""
        rows = get_db().fetchall(
            "SELECT slot, updated_at FROM vehicle_photos WHERE vehicle_id = ?", (vehicle_id,)
        )
        by_slot = {row["slot"]: row["updated_at"] for row in rows}
        status = []
        for slot in SLOTS:
            updated_at = by_slot.get(slot)
            status.append({
                "slot": slot,
                "label": SLOT_INFO[slot]["label"],
                "tip": SLOT_INFO[slot]["tip"],
                "has_photo": updated_at is not None,
                "version": re.sub(r"\D", "", str(updated_at)) if updated_at else "",
            })
        return status

    @classmethod
    def count_photos(cls, vehicle_id):
        return sum(1 for item in cls.photo_status(vehicle_id) if item["has_photo"])

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def color_hex(color_name):
        name = (color_name or "").lower()
        for keyword, hex_value in COLOR_SWATCHES:
            if keyword in name:
                return hex_value
        return "#9ca3af"
