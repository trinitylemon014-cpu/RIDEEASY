import os

from flask import Blueprint, current_app, make_response, render_template, send_from_directory
from app.repositories.database import get_db
from app.services.auth_service import AuthService

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    user = AuthService.get_current_user()
    return render_template("index.html", user=user)

@main_bp.route("/about")
def about():
    user = AuthService.get_current_user()
    return render_template("about.html", user=user)

@main_bp.route("/safety")
def safety():
    user = AuthService.get_current_user()
    return render_template("safety.html", user=user)

@main_bp.route("/pricing")
def pricing():
    user = AuthService.get_current_user()
    db = get_db()
    pricing = db.fetchall("SELECT * FROM pricing_configs")
    return render_template("pricing.html", user=user, pricing=pricing)

@main_bp.route("/contact")
def contact():
    user = AuthService.get_current_user()
    return render_template("contact.html", user=user)


@main_bp.route("/sw.js")
def service_worker():
    """Served from the site root so the worker can control every page (needed for push)."""
    response = make_response(send_from_directory(os.path.join(current_app.root_path, "static"), "sw.js"))
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response
