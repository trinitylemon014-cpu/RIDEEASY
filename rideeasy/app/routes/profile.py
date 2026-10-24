import re
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from app.repositories.database import get_db
from app.services.auth_service import login_required, AuthService
from app.services.cloudinary_service import CloudinaryError, CloudinaryService
from app.services.notification_service import NotificationService
from app.services.vehicle_photo_service import PhotoError, VehiclePhotoService

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

        # Validate and sanitize a new profile picture before uploading it.
        avatar_url = user.get("avatar_url") or "/static/images/default-avatar.svg"
        avatar_public_id = user.get("avatar_cloudinary_public_id")
        avatar_bytes = None
        if "avatar" in request.files:
            file = request.files["avatar"]
            if file and file.filename != "":
                if not allowed_file(file.filename):
                    errors.append("Avatar must be a valid image file (.png, .jpg, .jpeg, or .webp).")
                else:
                    try:
                        raw_avatar = file.stream.read(MAX_FILE_SIZE + 1)
                        avatar_bytes = VehiclePhotoService.process_image(
                            raw_avatar, max_upload_bytes=MAX_FILE_SIZE, min_edge_px=100
                        )
                    except PhotoError as error:
                        errors.append(f"Profile picture: {error}")

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

        if avatar_bytes:
            try:
                cloud_image = CloudinaryService.upload(
                    avatar_bytes,
                    folder="rideeasy/avatars",
                    public_id=f"{user['id']}_{uuid.uuid4().hex}",
                )
            except CloudinaryError as error:
                flash(str(error), "error")
                return render_template(
                    "profile.html",
                    user={**user, "full_name": full_name, "email": email, "phone": phone},
                    passenger_profile=passenger_profile,
                    driver_profile=driver_profile,
                    school_profile=school_profile
                )
            avatar_url = cloud_image["secure_url"]
            avatar_public_id = cloud_image["public_id"]

        # Update Users table
        db.execute(
            """UPDATE users 
            SET full_name = ?, email = ?, phone = ?, avatar_url = ?,
                avatar_cloudinary_public_id = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?""",
            (full_name, email, phone, avatar_url, avatar_public_id, user["id"])
        )
        previous_avatar_public_id = user.get("avatar_cloudinary_public_id")
        if avatar_bytes and previous_avatar_public_id:
            try:
                CloudinaryService.delete(previous_avatar_public_id)
            except CloudinaryError as error:
                current_app.logger.warning(
                    "Old profile photo cleanup failed for user %s: %s", user["id"], error
                )
                flash("Your new profile picture was saved, but the previous cloud image could not be cleaned up.", "warning")

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
