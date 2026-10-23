import os
import re
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from werkzeug.utils import secure_filename
from app.repositories.database import get_db
from app.services.auth_service import login_required, AuthService
from app.services.notification_service import NotificationService

profile_bp = Blueprint("profile", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_FILE_SIZE = 4 * 1024 * 1024  # 4 MB

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def view_profile():
    user = AuthService.get_current_user()
    db = get_db()
    
    passenger_profile = None
    driver_profile = None
    school_profile = None
    
    if user["role"] == "PASSENGER":
        passenger_profile = db.fetchone("SELECT * FROM passenger_profiles WHERE user_id = ?", (user["id"],))
    elif user["role"] == "DRIVER":
        driver_profile = db.fetchone(
            """SELECT d.*, v.plate_number, v.make, v.model, v.category as vehicle_category
            FROM driver_profiles d
            LEFT JOIN vehicles v ON v.driver_id = d.user_id
            WHERE d.user_id = ?""",
            (user["id"],)
        )
    elif user["role"] == "SCHOOL":
        school_profile = db.fetchone("SELECT * FROM schools WHERE user_id = ?", (user["id"],))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        
        # Server-side validation
        errors = []
        if not full_name or len(full_name) < 2:
            errors.append("Full name must be at least 2 characters.")
        if len(full_name) > 100:
            errors.append("Full name must not exceed 100 characters.")
            
        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not email or not re.match(email_regex, email):
            errors.append("Please enter a valid email address.")
        else:
            # Check email uniqueness against other users
            existing = db.fetchone("SELECT id FROM users WHERE email = ? AND id != ?", (email, user["id"]))
            if existing:
                errors.append("This email address is already in use by another account.")

        phone_clean = re.sub(r"[^\d+]", "", phone)
        if not phone_clean or len(phone_clean) < 9:
            errors.append("Please provide a valid Ugandan phone number (at least 9 digits).")

        # Handle Profile Picture Upload
        avatar_url = user.get("avatar_url") or "/static/images/default-avatar.svg"
        if "avatar" in request.files:
            file = request.files["avatar"]
            if file and file.filename != "":
                if not allowed_file(file.filename):
                    errors.append("Avatar must be a valid image file (.png, .jpg, .jpeg, or .webp).")
                else:
                    # Check file size by seeking
                    file.seek(0, os.SEEK_END)
                    size = file.tell()
                    file.seek(0)
                    if size > MAX_FILE_SIZE:
                        errors.append("Profile picture must be under 4MB in size.")
                    else:
                        filename = f"avatar_{user['id']}_{uuid.uuid4().hex[:6]}_{secure_filename(file.filename)}"
                        upload_dir = os.path.join(current_app.static_folder, "uploads", "avatars")
                        os.makedirs(upload_dir, exist_ok=True)
                        file_path = os.path.join(upload_dir, filename)
                        file.save(file_path)
                        avatar_url = f"/static/uploads/avatars/{filename}"

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "profile.html",
                user={**user, "full_name": full_name, "email": email, "phone": phone, "avatar_url": avatar_url},
                passenger_profile=passenger_profile,
                driver_profile=driver_profile,
                school_profile=school_profile
            )

        # Update Users table
        db.execute(
            """UPDATE users 
            SET full_name = ?, email = ?, phone = ?, avatar_url = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?""",
            (full_name, email, phone, avatar_url, user["id"])
        )

        # Update role-specific fields
        if user["role"] == "PASSENGER":
            em_name = request.form.get("emergency_contact_name", "").strip()
            em_phone = request.form.get("emergency_contact_phone", "").strip()
            home_addr = request.form.get("home_address", "").strip()
            work_addr = request.form.get("work_address", "").strip()
            pay_method = request.form.get("preferred_payment_method", "MTN_MOMO")
            
            db.execute(
                """INSERT OR REPLACE INTO passenger_profiles 
                (user_id, emergency_contact_name, emergency_contact_phone, home_address, work_address, preferred_payment_method) 
                VALUES (?, ?, ?, ?, ?, ?)""",
                (user["id"], em_name, em_phone, home_addr, work_addr, pay_method)
            )

        # Refresh Session data
        session["user_name"] = full_name
        session["user_email"] = email

        # Audit Log
        db.execute(
            "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
            (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "UPDATE_PROFILE", "USER", user["id"], f"Updated name: {full_name}, email: {email}")
        )

        flash("Your profile information has been successfully updated.", "success")
        return redirect(url_for("profile.view_profile"))

    return render_template(
        "profile.html",
        user=user,
        passenger_profile=passenger_profile,
        driver_profile=driver_profile,
        school_profile=school_profile
    )

@profile_bp.route("/notifications/<notif_id>/dismiss", methods=["POST"])
@login_required
def dismiss_notification(notif_id):
    user = AuthService.get_current_user()
    NotificationService.mark_as_read(notif_id, user["id"])
    
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "notification_id": notif_id})
    
    flash("Notification dismissed.", "info")
    next_url = request.referrer or url_for("main.index")
    return redirect(next_url)

@profile_bp.route("/notifications/dismiss-all", methods=["POST"])
@login_required
def dismiss_all_notifications():
    user = AuthService.get_current_user()
    NotificationService.mark_all_as_read(user["id"])
    
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
        
    flash("All notifications marked as read.", "info")
    return redirect(request.referrer or url_for("main.index"))
