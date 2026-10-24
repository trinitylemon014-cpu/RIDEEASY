import os
import secrets
from flask import Flask, render_template, session
from app.config import Config
from app.repositories.database import get_db
from app.services.auth_service import AuthService

def create_app(config_class=Config):
    """Application factory for RideEasy platform."""
    app = Flask(__name__, 
                static_folder="static", 
                template_folder="templates")
    app.config.from_object(config_class)
    if not app.config.get("SECRET_KEY") and not app.config.get("TESTING"):
        raise RuntimeError("SECRET_KEY must be set to a strong deployment secret.")

    # Initialize database & seed demo data if needed
    with app.app_context():
        from database.migrations.seed_data import seed_database
        seed_database()

    # Register Jinja custom filters & context processors
    @app.template_filter("ugx")
    def format_ugx(val):
        if val is None:
            return "UGX 0"
        try:
            return f"UGX {int(val):,}"
        except Exception:
            return f"UGX {val}"

    @app.context_processor
    def inject_globals():
        user = AuthService.get_current_user()
        unread_count = 0
        recent_notifs = []
        csrf_token = ""
        if user:
            csrf_token = session.setdefault("payment_csrf_token", secrets.token_urlsafe(32))
            from app.services.notification_service import NotificationService
            unread_count = NotificationService.get_unread_count(user["id"])
            recent_notifs = NotificationService.get_user_notifications(user["id"], unread_only=True, limit=5)

        return {
            "app_name": Config.APP_NAME,
            "app_tagline": Config.APP_TAGLINE,
            "company_name": Config.COMPANY_NAME,
            "current_user": user,
            "unread_notifications_count": unread_count,
            "recent_notifications": recent_notifs,
            "payment_csrf_token": csrf_token,
            "support_phone": Config.SUPPORT_PHONE,
            "support_email": Config.SUPPORT_EMAIL
        }

    # Register Blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.profile import profile_bp
    from app.routes.passenger import passenger_bp
    from app.routes.driver import driver_bp
    from app.routes.school import school_bp
    from app.routes.travel_partner import travel_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.payments import payments_bp
    from app.routes.maps import maps_bp
    from app.routes.vehicle_photos import vehicle_photos_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(profile_bp)
    app.register_blueprint(passenger_bp)
    app.register_blueprint(driver_bp)
    app.register_blueprint(school_bp)
    app.register_blueprint(travel_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(maps_bp)
    app.register_blueprint(vehicle_photos_bp)

    # Error Handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("errors/500.html"), 500

    return app
