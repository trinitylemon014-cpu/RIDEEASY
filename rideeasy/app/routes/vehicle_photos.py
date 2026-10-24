import secrets

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from app.repositories.database import get_db
from app.services.auth_service import AuthService, login_required, role_required
from app.services.cloudinary_service import CloudinaryError
from app.services.vehicle_photo_service import (
    MAX_UPLOAD_BYTES,
    SLOT_INFO,
    SLOTS,
    PhotoError,
    VehiclePhotoService,
)

vehicle_photos_bp = Blueprint("vehicle_photos", __name__)

# A passenger may see a driver's car photos once that driver has been matched to one of
# their rides (any ride that is not just a request still waiting for a driver, or cancelled).
_VISIBLE_RIDE_STATUSES = (
    "DRIVER_ASSIGNED", "DRIVER_ARRIVING", "DRIVER_ARRIVED",
    "TRIP_STARTED", "TRIP_COMPLETED", "PAYMENT_PENDING", "COMPLETED",
)


def _csrf_ok():
    token = request.form.get("csrf_token", "")
    expected = session.get("payment_csrf_token", "")
    return bool(token and expected and secrets.compare_digest(token, expected))


def _wants_json():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _driver_vehicle(user_id):
    return get_db().fetchone("SELECT * FROM vehicles WHERE driver_id = ?", (user_id,))


def _reply(success, message, status=200, category=None, flash_it=True):
    """JSON for the upload script, otherwise flash + redirect back to the photo page."""
    if _wants_json():
        if flash_it and message:
            flash(message, category or ("success" if success else "error"))
        return jsonify({"success": success, "message": message}), status
    if message:
        flash(message, category or ("success" if success else "error"))
    return redirect(url_for("vehicle_photos.manage"))


@vehicle_photos_bp.route("/driver/vehicle-photos", methods=["GET", "POST"])
@login_required
@role_required("DRIVER")
def manage():
    user = AuthService.get_current_user()
    vehicle = _driver_vehicle(user["id"])

    if request.method == "GET":
        photos = VehiclePhotoService.photo_status(vehicle["id"]) if vehicle else []
        return render_template(
            "driver/vehicle_photos.html",
            user=user,
            vehicle=vehicle,
            photos=photos,
            photo_count=sum(1 for p in photos if p["has_photo"]),
            max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
        )

    try:
        csrf_ok = _csrf_ok()
        uploads = {slot: request.files.get(f"photo_{slot}") for slot in SLOTS}
    except RequestEntityTooLarge:
        return _reply(False, "Those photos are too large. Each photo must be under 8 MB.", 413, flash_it=False)

    if not csrf_ok:
        return _reply(False, "Your session expired. Reload the page and try again.", 400, flash_it=False)
    if not vehicle:
        return _reply(False, "No vehicle is registered to your account yet.", 400, flash_it=False)

    saved, errors = [], []
    for slot in SLOTS:
        upload = uploads[slot]
        if upload is None or not upload.filename:
            continue
        label = SLOT_INFO[slot]["label"]
        try:
            raw = upload.stream.read(MAX_UPLOAD_BYTES + 1)
            VehiclePhotoService.save_photo(vehicle["id"], slot, VehiclePhotoService.process_image(raw))
            saved.append(label)
        except PhotoError as error:
            errors.append(f"{label} photo: {error}")
        except CloudinaryError as error:
            current_app.logger.warning("Vehicle photo upload failed for vehicle %s: %s", vehicle["id"], error)
            errors.append(f"{label} photo could not be saved to cloud storage. Please try again.")

    if not saved and not errors:
        return _reply(False, "Choose at least one photo to upload.", 400, flash_it=False)
    if not saved:
        return _reply(False, " ".join(errors), 400, flash_it=False)

    message = f"Saved your {', '.join(saved).lower()} photo{'s' if len(saved) > 1 else ''}."
    if errors:
        flash(" ".join(errors), "warning")
    remaining = 3 - VehiclePhotoService.count_photos(vehicle["id"])
    if remaining > 0:
        message += f" {remaining} more to go so passengers can spot your car."
    else:
        message += " All three photos are in. Passengers can now spot your car easily."
    return _reply(True, message)


@vehicle_photos_bp.route("/driver/vehicle-photos/<slot>/delete", methods=["POST"])
@login_required
@role_required("DRIVER")
def delete(slot):
    slot = slot.upper()
    if slot not in SLOTS:
        abort(404)
    try:
        csrf_ok = _csrf_ok()
    except RequestEntityTooLarge:
        csrf_ok = False
    if not csrf_ok:
        flash("Your session expired. Reload the page and try again.", "error")
        return redirect(url_for("vehicle_photos.manage"))
    user = AuthService.get_current_user()
    vehicle = _driver_vehicle(user["id"])
    if not vehicle:
        abort(404)
    try:
        VehiclePhotoService.delete_photo(vehicle["id"], slot)
    except CloudinaryError as error:
        current_app.logger.warning("Vehicle photo cleanup failed for vehicle %s: %s", vehicle["id"], error)
        flash("The photo was removed from your profile, but cloud cleanup could not be confirmed.", "warning")
        return redirect(url_for("vehicle_photos.manage"))
    flash(f"Removed your {SLOT_INFO[slot]['label'].lower()} photo.", "info")
    return redirect(url_for("vehicle_photos.manage"))


def _can_view(vehicle):
    role = session.get("user_role")
    user_id = session.get("user_id")
    if role == "ADMIN":
        return True
    if role == "DRIVER":
        return vehicle["driver_id"] == user_id
    if role == "PASSENGER" and vehicle["driver_id"]:
        placeholders = ", ".join("?" for _ in _VISIBLE_RIDE_STATUSES)
        ride = get_db().fetchone(
            f"""SELECT id FROM rides
                WHERE passenger_id = ? AND driver_id = ? AND status IN ({placeholders})
                LIMIT 1""",
            (user_id, vehicle["driver_id"], *_VISIBLE_RIDE_STATUSES),
        )
        return ride is not None
    return False


@vehicle_photos_bp.route("/vehicle-photos/<vehicle_id>/<slot>.jpg")
@login_required
def serve(vehicle_id, slot):
    slot = slot.upper()
    if slot not in SLOTS:
        abort(404)
    vehicle = get_db().fetchone("SELECT id, driver_id FROM vehicles WHERE id = ?", (vehicle_id,))
    # 404 (not 403) so the URL does not reveal whether a vehicle exists.
    if not vehicle or not _can_view(vehicle):
        abort(404)
    try:
        photo = VehiclePhotoService.get_photo(vehicle_id, slot)
    except CloudinaryError as error:
        current_app.logger.warning("Vehicle photo retrieval failed for vehicle %s: %s", vehicle_id, error)
        abort(502)
    if not photo:
        abort(404)
    response = Response(photo["data"], mimetype=photo["mime_type"])
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = "inline"
    return response
