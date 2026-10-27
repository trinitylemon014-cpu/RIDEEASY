import threading
import time
from collections import OrderedDict

import requests
from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from app.services.auth_service import login_required, AuthService

maps_bp = Blueprint("maps", __name__)

# LocationIQ raster tile endpoint. The API key is added server-side only, so it
# is never exposed in browser HTML, JavaScript, or tile URLs.
LOCATIONIQ_TILE_URL = "https://a-tiles.locationiq.com/v3/streets/r/{z}/{x}/{y}.png"
TILE_MAX_ZOOM = 18
TILE_CACHE_MAX_ITEMS = 1000
TILE_CACHE_TTL_SECONDS = 24 * 60 * 60

_tile_cache = OrderedDict()
_tile_cache_lock = threading.Lock()


def _cache_get(key):
    now = time.time()
    with _tile_cache_lock:
        item = _tile_cache.get(key)
        if item is None:
            return None
        expires_at, content = item
        if expires_at < now:
            _tile_cache.pop(key, None)
            return None
        _tile_cache.move_to_end(key)
        return content


def _cache_set(key, content):
    with _tile_cache_lock:
        _tile_cache[key] = (time.time() + TILE_CACHE_TTL_SECONDS, content)
        _tile_cache.move_to_end(key)
        while len(_tile_cache) > TILE_CACHE_MAX_ITEMS:
            _tile_cache.popitem(last=False)


def _tile_response(content):
    response = Response(content, mimetype="image/png")
    # Tiles sit behind login, so keep them out of shared caches.
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


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


@maps_bp.route("/map/tiles/<int:z>/<int:x>/<int:y>.png")
def map_tile(z, x, y):
    return serve_tile(z, x, y)


def serve_tile(z, x, y):
    """Serve map tiles through the server so the LocationIQ key stays private
    and the browser never hits OpenStreetMap's restricted tile servers.
    (Also used by the public trip-share page after it checks its share token.)"""
    api_key = (current_app.config.get("LOCATIONIQ_API_KEY") or "").strip()
    if not api_key:
        abort(404)

    if z < 0 or z > TILE_MAX_ZOOM:
        abort(404)
    max_index = 2 ** z
    if x < 0 or y < 0 or x >= max_index or y >= max_index:
        abort(404)

    cache_key = (z, x, y)
    cached = _cache_get(cache_key)
    if cached is not None:
        return _tile_response(cached)

    url = LOCATIONIQ_TILE_URL.format(z=z, x=x, y=y)
    try:
        upstream = requests.get(
            url,
            params={"key": api_key},
            headers={"User-Agent": "RideEasy/1.0 (route-map tile proxy)"},
            timeout=(3.05, 10),
        )
    except requests.RequestException as error:
        # Log only the exception type; the message can contain the request URL with the key.
        current_app.logger.warning("Map tile request failed (%s).", type(error).__name__)
        abort(502)

    content_type = upstream.headers.get("Content-Type", "")
    if upstream.status_code != 200 or not content_type.startswith("image/"):
        current_app.logger.warning("Map tile provider returned status %s.", upstream.status_code)
        abort(502 if upstream.status_code >= 500 or upstream.status_code in (401, 403, 429) else 404)

    _cache_set(cache_key, upstream.content)
    return _tile_response(upstream.content)
