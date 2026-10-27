import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Base application configuration for RideEasy platform."""
    SECRET_KEY = os.getenv("SECRET_KEY")
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("FLASK_PORT", 5000))
    HOST = os.getenv("HOST", "0.0.0.0")

    # Turso Database Configuration
    # Example: libsql://your-db-org.turso.io
    TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    LOCAL_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rideeasy.db")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@rideeasy.com").strip().lower()
    ADMIN_NAME = os.getenv("ADMIN_NAME", "katongole kylee").strip()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").strip()

    # Password hashing cost for NEW accounts. "scrypt" is Werkzeug's default and the safest.
    # On very small CPUs (e.g. Render free plan) it can take over a second per hash;
    # "scrypt:16384:8:1" is about 4x faster. Existing hashes keep verifying either way.
    PASSWORD_HASH_METHOD = os.getenv("PASSWORD_HASH_METHOD", "scrypt").strip() or "scrypt"

    # Largest request body Flask will accept (3 car photos of up to 8 MB each, plus form fields)
    MAX_CONTENT_LENGTH = 26 * 1024 * 1024

    # Session & Security Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = FLASK_ENV == "production"
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days

    # Application Branding
    APP_NAME = "RideEasy"
    APP_TAGLINE = "MOVE. TRAVEL. ARRIVE."
    COMPANY_NAME = "Emtrixz Technology Company"
    SUPPORT_PHONE = "+256 700 123 456"
    SUPPORT_EMAIL = "support@rideeasy.ug"
    DEFAULT_CURRENCY = "UGX"

    # Payment and notification integrations
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
    PAYSTACK_CURRENCY = os.getenv("PAYSTACK_CURRENCY", "UGX").strip().upper()
    PAYSTACK_AMOUNT_MULTIPLIER = int(os.getenv("PAYSTACK_AMOUNT_MULTIPLIER", "1"))
    PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL", "").strip()
    PAYSTACK_COLLECTION_PHONE = os.getenv("PAYSTACK_COLLECTION_PHONE", "0774339277").strip()
    PAYSTACK_ADMIN_PAYOUT_PHONE = os.getenv("PAYSTACK_ADMIN_PAYOUT_PHONE", "0708329503").strip()
    EGOSMS_API_URL = os.getenv("EGOSMS_API_URL", "").strip()
    EGOSMS_API_KEY = os.getenv("EGOSMS_API_KEY", "").strip()
    LOCATIONIQ_API_KEY = os.getenv("LOCATIONIQ_API_KEY", "").strip()
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    DRIVER_RIDE_OFFER_TIMEOUT_SECONDS = int(os.getenv("DRIVER_RIDE_OFFER_TIMEOUT_SECONDS", "45"))

    # Dispatch: distance-based matching
    # Drivers must have shared their location within this many seconds to be matched by distance.
    DISPATCH_LOCATION_MAX_AGE_SECONDS = int(os.getenv("DISPATCH_LOCATION_MAX_AGE_SECONDS", "180"))
    # Only drivers within this radius of the pickup are offered the trip.
    DISPATCH_MAX_RADIUS_KM = float(os.getenv("DISPATCH_MAX_RADIUS_KM", "15"))
    # "1": drivers with no recent location are never offered a trip that has pickup coordinates.
    # "0": they are still eligible, but ranked after every driver whose location is known.
    DISPATCH_REQUIRE_DRIVER_LOCATION = os.getenv("DISPATCH_REQUIRE_DRIVER_LOCATION", "1") == "1"
    # Average speed used for pickup / trip ETAs (km/h) when no routing provider answers.
    ETA_AVERAGE_SPEED_KMH = float(os.getenv("ETA_AVERAGE_SPEED_KMH", "25"))
    # Drivers need these APPROVED documents to receive trips ("" disables the check).
    DISPATCH_REQUIRED_DOC_TYPES = tuple(
        item.strip().upper()
        for item in os.getenv("DISPATCH_REQUIRED_DOC_TYPES", "").split(",")
        if item.strip()
    )
    # A ride left searching this long with no driver is cancelled and the passenger told.
    RIDE_SEARCH_TIMEOUT_MINUTES = int(os.getenv("RIDE_SEARCH_TIMEOUT_MINUTES", "10"))

    # Real-time streams (server-sent events). Each open stream holds one server thread,
    # so keep this below the gunicorn --threads value.
    REALTIME_MAX_STREAMS = int(os.getenv("REALTIME_MAX_STREAMS", "20"))
    REALTIME_STREAM_SECONDS = int(os.getenv("REALTIME_STREAM_SECONDS", "55"))

    # Safety
    EMERGENCY_NUMBER = os.getenv("EMERGENCY_NUMBER", "999").strip()
    TRIP_SHARE_HOURS = int(os.getenv("TRIP_SHARE_HOURS", "12"))
    REQUIRE_TRIP_PIN = os.getenv("REQUIRE_TRIP_PIN", "1") == "1"

    # Web Push (optional). Generate keys with: python scripts/generate_vapid_keys.py
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:support@rideeasy.ug").strip()

    # Airport Settings (Uganda Entry Hub)
    PRIMARY_AIRPORT = {
        "name": "Entebbe International Airport",
        "code": "EBB",
        "city": "Entebbe / Kampala",
        "lat": 0.0424,
        "lng": 32.4435
    }
