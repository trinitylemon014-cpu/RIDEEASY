import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Base application configuration for RideEasy platform."""
    SECRET_KEY = os.getenv("SECRET_KEY", "rideeasy-emtrixz-super-secret-key-2026-uganda-production")
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    PORT = int(os.getenv("FLASK_PORT", 5000))
    HOST = os.getenv("HOST", "0.0.0.0")

    # Turso Database Configuration
    # Example: libsql://your-db-org.turso.io
    TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
    TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    LOCAL_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rideeasy.db")

    # Session & Security Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days

    # Application Branding
    APP_NAME = "RideEasy"
    APP_TAGLINE = "MOVE. TRAVEL. ARRIVE."
    COMPANY_NAME = "Emtrixz Technology Company"
    SUPPORT_PHONE = "+256 700 123 456"
    SUPPORT_EMAIL = "support@rideeasy.ug"
    DEFAULT_CURRENCY = "UGX"

    # Airport Settings (Uganda Entry Hub)
    PRIMARY_AIRPORT = {
        "name": "Entebbe International Airport",
        "code": "EBB",
        "city": "Entebbe / Kampala",
        "lat": 0.0424,
        "lng": 32.4435
    }
