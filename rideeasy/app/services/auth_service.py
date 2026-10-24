from functools import wraps
from flask import session, redirect, url_for, flash, abort, request
from werkzeug.security import generate_password_hash, check_password_hash
from app.repositories.database import get_db

class AuthService:
    """Manages authentication, session tracking, password security, and RBAC."""

    @staticmethod
    def get_current_user():
        user_id = session.get("user_id")
        if not user_id:
            return None
        db = get_db()
        return db.fetchone(
            """SELECT id, email, role, full_name, phone, is_active, is_verified,
                      avatar_url, avatar_cloudinary_public_id, created_at
               FROM users WHERE id = ?""",
            (user_id,)
        )

    @staticmethod
    def authenticate(email: str, password: str):
        db = get_db()
        user = db.fetchone(
            "SELECT id, email, password_hash, role, full_name, phone, is_active, is_verified FROM users WHERE email = ?",
            (email.strip().lower(),)
        )
        if not user:
            return None, "Invalid email or password."
        if not user["is_active"]:
            return None, "Account is disabled. Contact support@rideeasy.ug."
        if not check_password_hash(user["password_hash"], password):
            return None, "Invalid email or password."
        return user, None

    @staticmethod
    def login_user(user: dict):
        session.clear()
        session["user_id"] = user["id"]
        session["user_role"] = user["role"]
        session["user_name"] = user["full_name"]
        session["user_email"] = user["email"]
        session.permanent = True

    @staticmethod
    def logout_user():
        session.clear()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                flash("Please sign in to access this page.", "warning")
                return redirect(url_for("auth.login", next=request.url))
            role = session.get("user_role")
            if role not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
