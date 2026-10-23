from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.repositories.database import get_db
from app.services.auth_service import AuthService
from app.services.pricing_service import MapService, PricingService

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    user = AuthService.get_current_user()
    db = get_db()
    pricing = db.fetchall("SELECT * FROM pricing_configs")
    landmarks = MapService.LANDMARKS
    return render_template("index.html", user=user, pricing=pricing, landmarks=landmarks)

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
