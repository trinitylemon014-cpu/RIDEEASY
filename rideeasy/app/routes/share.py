"""Public, read-only trip tracking page that a passenger can send to family or friends."""
import re
import time
from collections import defaultdict, deque

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from app.repositories.database import get_db
from app.routes.maps import serve_tile
from app.services.safety_service import SafetyService

share_bp = Blueprint("share", __name__, url_prefix="/track")

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{20,64}")
STATUS_MAX_PER_MINUTE = 40
_status_hits = defaultdict(deque)
_token_ok_until: dict = {}
TOKEN_CACHE_SECONDS = 60


def _limited():
    who = request.headers.get("X-Forwarded-For", request.remote_addr or "anon").split(",")[0].strip()
    now = time.monotonic()
    hits = _status_hits[who]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= STATUS_MAX_PER_MINUTE:
        return True
    hits.append(now)
    return False


def _private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _token_is_valid(token: str) -> bool:
    """Cheap token check for tile requests (cached briefly: a map loads many tiles)."""
    if not TOKEN_PATTERN.fullmatch(token or ""):
        return False
    now = time.monotonic()
    if _token_ok_until.get(token, 0) > now:
        return True
    row = get_db().fetchone(
        "SELECT 1 AS ok FROM trip_shares WHERE token = ? AND revoked = 0 AND expires_at > CURRENT_TIMESTAMP",
        (token,),
    )
    if row:
        if len(_token_ok_until) > 500:
            _token_ok_until.clear()
        _token_ok_until[token] = now + TOKEN_CACHE_SECONDS
        return True
    return False


@share_bp.route("/<token>")
def track(token):
    trip = SafetyService.get_shared_trip(token) if TOKEN_PATTERN.fullmatch(token) else None
    if not trip:
        return _private(current_app.make_response((render_template("share/expired.html"), 404)))
    return _private(current_app.make_response(render_template(
        "share/track.html",
        trip=trip,
        token=token,
        locationiq_configured=bool((current_app.config.get("LOCATIONIQ_API_KEY") or "").strip()),
        emergency_number=current_app.config.get("EMERGENCY_NUMBER", "999"),
    )))


@share_bp.route("/<token>/status.json")
def status(token):
    if _limited():
        return _private(jsonify({"error": "Too many requests."})), 429
    trip = SafetyService.get_shared_trip(token) if TOKEN_PATTERN.fullmatch(token) else None
    if not trip:
        return _private(jsonify({"error": "This link has expired."})), 404
    return _private(jsonify({"success": True, "trip": trip}))


@share_bp.route("/<token>/tiles/<int:z>/<int:x>/<int:y>.png")
def tile(token, z, x, y):
    if not _token_is_valid(token):
        abort(404)
    return serve_tile(z, x, y)
