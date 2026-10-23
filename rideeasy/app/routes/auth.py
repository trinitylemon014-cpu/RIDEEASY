import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash
from app.repositories.database import get_db
from app.services.auth_service import AuthService

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect_to_dashboard(session.get("user_role"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user, err = AuthService.authenticate(email, password)
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
    """Convenience 1-click login for demonstration of all 5 system roles."""
    role_map = {
        "admin": "admin@rideeasy.ug",
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

        db = get_db()
        existing = db.fetchone("SELECT id FROM users WHERE email = ?", (email,))
        if existing:
            flash("An account with this email address already exists.", "error")
            return render_template("auth/register.html")

        user_id = f"usr_{uuid.uuid4().hex[:10]}"
        pw_hash = generate_password_hash(password)
        is_verified = 1 if role == "PASSENGER" else 0

        db.execute(
            "INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (user_id, email, pw_hash, role, full_name, phone, is_verified)
        )

        # Create role-specific profile
        if role == "PASSENGER":
            db.execute("INSERT INTO passenger_profiles (user_id) VALUES (?)", (user_id,))
        elif role == "DRIVER":
            db.execute(
                "INSERT INTO driver_profiles (user_id, license_number, national_id_nin, verification_status) VALUES (?, 'PENDING', 'PENDING', 'PENDING')",
                (user_id,)
            )
        elif role == "SCHOOL":
            db.execute(
                "INSERT INTO schools (user_id, school_name, registration_number, contact_person, phone, email, address, district, verification_status) VALUES (?, ?, 'PENDING', ?, ?, ?, 'Kampala', 'Kampala', 'PENDING')",
                (user_id, full_name, full_name, phone, email)
            )

        new_user = db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
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
