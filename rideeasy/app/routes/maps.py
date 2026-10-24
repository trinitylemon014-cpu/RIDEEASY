from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from app.services.auth_service import login_required, AuthService

maps_bp = Blueprint("maps", __name__)


@maps_bp.before_request
@login_required
def before_request():
    pass


@maps_bp.route("/maps")
@maps_bp.route("/map")
def route_planner():
    user = AuthService.get_current_user()
    if user is None:
        AuthService.logout_user()
        flash("Your session has expired. Please sign in again.", "warning")
        return redirect(url_for("auth.login", next=request.full_path))

    role_by_user_type = {
        "SCHOOL": "school",
        "DRIVER": "driver",
        "PASSENGER": "passenger",
        "TRAVEL_COMPANY": "travel",
        "ADMIN": "admin",
    }
    role = role_by_user_type.get((user["role"] or "").strip().upper())
    if role is None:
        abort(403)

    pickup = request.args.get("pickup", "").strip()[:300]
    destination = request.args.get("destination", "").strip()[:300]
    return render_template(
        "map.html",
        user=user,
        role=role,
        pickup=pickup,
        destination=destination,
        locationiq_configured=bool(current_app.config.get("LOCATIONIQ_API_KEY")),
    )
