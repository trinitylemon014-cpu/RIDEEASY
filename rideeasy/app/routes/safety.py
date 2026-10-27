"""Trip safety actions for passengers and drivers: SOS, trip sharing, emergency contacts."""
import secrets
import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.services.auth_service import AuthService, login_required, role_required
from app.services.safety_service import SafetyError, SafetyService

safety_bp = Blueprint("trip_safety", __name__, url_prefix="/trip-safety")

_sos_hits = defaultdict(deque)
SOS_MAX_PER_MINUTE = 4


def _rate_limited(hits_by_user, limit):
    who = session.get("user_id") or request.remote_addr or "anonymous"
    now = time.monotonic()
    hits = hits_by_user[who]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def _xhr_ok():
    return request.headers.get("X-Requested-With") == "RideEasy"


def _csrf_ok():
    token = request.form.get("csrf_token", "")
    expected = session.get("payment_csrf_token", "")
    return bool(token and expected and secrets.compare_digest(token, expected))


@safety_bp.before_request
@login_required
@role_required("PASSENGER", "DRIVER")
def before_request():
    pass


@safety_bp.route("/rides/<ride_id>/sos", methods=["POST"])
def sos(ride_id):
    if not _xhr_ok():
        return jsonify({"error": "Invalid request."}), 400
    if _rate_limited(_sos_hits, SOS_MAX_PER_MINUTE):
        return jsonify({"error": "Alert already sent. Call emergency services if you are in danger."}), 429
    user = AuthService.get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        result = SafetyService.trigger_sos(ride_id, user, data.get("lat"), data.get("lng"), data.get("message"))
    except SafetyError as error:
        return jsonify({"error": str(error), "emergency_number": current_app.config.get("EMERGENCY_NUMBER", "999")}), 400
    return jsonify({"success": True, "emergency_number": current_app.config.get("EMERGENCY_NUMBER", "999"), **result})


@safety_bp.route("/rides/<ride_id>/share", methods=["POST"])
@role_required("PASSENGER")
def share(ride_id):
    if not _xhr_ok():
        return jsonify({"error": "Invalid request."}), 400
    try:
        link = SafetyService.create_share(ride_id, session["user_id"])
    except SafetyError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"success": True, "url": SafetyService.share_url(link["token"]), "expires_at": link["expires_at"]})


@safety_bp.route("/rides/<ride_id>/share/revoke", methods=["POST"])
@role_required("PASSENGER")
def revoke_share(ride_id):
    if not _xhr_ok():
        return jsonify({"error": "Invalid request."}), 400
    SafetyService.revoke_shares(ride_id, session["user_id"])
    return jsonify({"success": True})


@safety_bp.route("/contacts", methods=["GET", "POST"])
def contacts():
    user = AuthService.get_current_user()
    if request.method == "POST":
        if not _csrf_ok():
            flash("Your session expired. Please try again.", "error")
            return redirect(url_for("trip_safety.contacts"))
        try:
            SafetyService.add_contact(user["id"], request.form.get("name"), request.form.get("phone"))
            flash("Emergency contact saved.", "success")
        except SafetyError as error:
            flash(str(error), "error")
        return redirect(url_for("trip_safety.contacts"))
    return render_template(
        "safety/contacts.html",
        user=user,
        contacts=SafetyService.list_contacts(user["id"]),
        emergency_number=current_app.config.get("EMERGENCY_NUMBER", "999"),
    )


@safety_bp.route("/contacts/<contact_id>/delete", methods=["POST"])
def delete_contact(contact_id):
    if not _csrf_ok():
        flash("Your session expired. Please try again.", "error")
    elif SafetyService.delete_contact(session["user_id"], contact_id):
        flash("Emergency contact removed.", "info")
    return redirect(url_for("trip_safety.contacts"))
