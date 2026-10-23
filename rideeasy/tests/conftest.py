import os
import sys
import pytest

# Ensure app is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.config import Config
from app.repositories.database import get_db

class TestConfig(Config):
    SECRET_KEY = "test-only-rideeasy-secret"
    TESTING = True
    DEBUG = False
    FLASK_ENV = "testing"
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
    # Use in-memory SQLite or test DB for tests
    LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "test_rideeasy.db")
    TURSO_DATABASE_URL = ""
    TURSO_AUTH_TOKEN = ""

@pytest.fixture(scope="session")
def app():
    app = create_app(TestConfig)
    yield app
    # Cleanup test db
    if os.path.exists(TestConfig.LOCAL_DB_PATH):
        try:
            os.remove(TestConfig.LOCAL_DB_PATH)
        except Exception:
            pass

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def db(app):
    with app.app_context():
        return get_db()
