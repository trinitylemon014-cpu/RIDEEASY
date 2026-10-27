import time
import uuid
from flask import Blueprint, abort, current_app, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash
from app.repositories.database import get_db
from app.repositories.turso_http import DatabaseUnavailableError
from app.services.auth_service import AuthService

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect_to_dashboard(session.get("user_role"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            user, err = AuthService.authenticate(email, password)
        except DatabaseUnavailableError:
            current_app.logger.exception("Login failed: database unavailable")
            flash("We can't reach the service right now. Please try again in a moment.", "error")
            return render_template("auth/login.html", email=email), 503
        if err:
            flash(err, "error")
            return render_template("auth/login.html", email=email)

        AuthService.login_user(user)
        flash(f"Welcome back, {user['full_name']}.", "success")
        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect_to_dashboard(user["role"])

    return render_template("auth/login.html")

@auth_bp.route("/demo/<role>")
def demo_login(role):
    """Test-only convenience login for the seeded test fixtures."""
    if not current_app.testing:
        abort(404)
    role_map = {
        "admin": current_app.config["ADMIN_EMAIL"],
        "passenger": "passenger@rideeasy.ug",
        "driver": "driver@rideeasy.ug",
        "school": "school@rideeasy.ug",
        "travel": "travel@rideeasy.ug"
    }
    email = role_map.get(role.lower())
    if not email:
        flash("Invalid demo role selected.", "error")
        return redirect(url_for("auth.login"))

    db = get_db()
    user = db.fetchone("SELECT * FROM users WHERE email = ?", (email,))
    if user:
        AuthService.login_user(user)
        flash(f"Logged in as {user['full_name']} ({user['role']}).", "success")
        return redirect_to_dashboard(user["role"])
    else:
        flash("Demo account not initialized. Please run database seeding.", "error")
        return redirect(url_for("auth.login"))

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect_to_dashboard(session.get("user_role"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form.get("role", "PASSENGER").upper()

        if role not in ("PASSENGER", "DRIVER", "SCHOOL"):
            flash("Invalid registration role specified.", "error")
            return render_template("auth/register.html")

        if not email or not password or not full_name or not phone:
            flash("All fields are required for registration.", "error")
            return render_template("auth/register.html")

        t_start = time.perf_counter()
        db = get_db()
        existing = db.fetchone("SELECT id FROM users WHERE email = ?", (email,))
        t_lookup = time.perf_counter()
        if existing:
            flash("An account with this email address already exists.", "error")
            return render_template("auth/register.html")

        user_id = f"usr_{uuid.uuid4().hex[:10]}"
        pw_hash = generate_password_hash(
            password, method=current_app.config.get("PASSWORD_HASH_METHOD", "scrypt")
        )
        t_hash = time.perf_counter()
        is_verified = 1 if role == "PASSENGER" else 0

        # Create the user and the role-specific profile in ONE atomic round trip.
        operations = [(
            "INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (user_id, email, pw_hash, role, full_name, phone, is_verified)
        )]
        if role == "PASSENGER":
            operations.append(("INSERT INTO passenger_profiles (user_id) VALUES (?)", (user_id,)))
        elif role == "DRIVER":
            operations.append((
                "INSERT INTO driver_profiles (user_id, license_number, national_id_nin, verification_status) VALUES (?, 'PENDING', 'PENDING', 'PENDING')",
                (user_id,)
            ))
        elif role == "SCHOOL":
            operations.append((
                "INSERT INTO schools (user_id, school_name, registration_number, contact_person, phone, email, address, district, verification_status) VALUES (?, ?, 'PENDING', ?, ?, ?, 'Kampala', 'Kampala', 'PENDING')",
                (user_id, full_name, full_name, phone, email)
            ))

        try:
            db.execute_transaction(operations)
        except Exception:
            current_app.logger.exception("Registration failed for %s", email)
            flash("We could not create your account. Please try again.", "error")
            return render_template("auth/register.html")

        t_write = time.perf_counter()
        # Diagnostic: logged at WARNING so it shows in Render's logs. Safe to remove later.
        current_app.logger.warning(
            "register timing: lookup=%.0fms hash=%.0fms write=%.0fms",
            (t_lookup - t_start) * 1000, (t_hash - t_lookup) * 1000, (t_write - t_hash) * 1000
        )

        # login_user() only needs these fields, so there is no need to re-read the row.
        new_user = {"id": user_id, "email": email, "role": role, "full_name": full_name}
        AuthService.login_user(new_user)
        flash(f"Account registered successfully as {role.capitalize()}.", "success")
        return redirect_to_dashboard(role)

    return render_template("auth/register.html")

@auth_bp.route("/logout")
def logout():
    AuthService.logout_user()
    flash("You have been signed out safely.", "info")
    return redirect(url_for("main.index"))

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        flash(f"If an account is associated with {email}, a secure password reset link has been dispatched via SMS and email.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html")

def redirect_to_dashboard(role):
    if role == "PASSENGER":
        return redirect(url_for("passenger.dashboard"))
    elif role == "DRIVER":
        return redirect(url_for("driver.dashboard"))
    elif role == "SCHOOL":
        return redirect(url_for("school.dashboard"))
    elif role == "TRAVEL_COMPANY":
        return redirect(url_for("travel.dashboard"))
    elif role == "ADMIN":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("main.index"))
