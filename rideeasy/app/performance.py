"""
Response-level speedups: gzip compression and sensible browser caching.

* Text responses (HTML, CSS, JS, JSON, SVG) are gzip-compressed when the browser accepts it.
  Compressed static files are memoised so they are only compressed once per deploy.
* /static/ files requested with ?v=<version> are cached for a year (immutable); images, icons
  and fonts for 30 days; other unversioned static files are revalidated (cheap 304).
* ``asset_v`` is exposed to templates so stylesheet/script URLs change on every deploy.
"""
import gzip
import os
import time

from flask import request

COMPRESSIBLE = {
    "text/html", "text/css", "text/plain", "text/javascript", "application/javascript",
    "application/json", "application/manifest+json", "image/svg+xml", "image/x-icon",
}
MIN_SIZE = 500
GZIP_LEVEL = 6
LONG_CACHE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".svg", ".woff", ".woff2")
_static_cache = {}  # (etag, path) -> gzipped bytes


def asset_version() -> str:
    """Changes on every deploy (Render exposes the git commit); falls back to process start."""
    for key in ("RENDER_GIT_COMMIT", "SOURCE_VERSION", "GIT_COMMIT"):
        value = os.getenv(key)
        if value:
            return value[:10]
    return str(int(time.time()))


def init_performance(app):
    version = asset_version()

    @app.context_processor
    def _asset_version():
        return {"asset_v": version}

    @app.after_request
    def _optimize(response):
        path = request.path
        if path.startswith("/static/") and response.status_code in (200, 304):
            if request.args.get("v"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif path.lower().endswith(LONG_CACHE_EXTENSIONS):
                response.headers["Cache-Control"] = "public, max-age=2592000"
            else:
                response.headers["Cache-Control"] = "no-cache"
        return _maybe_gzip(response)


def _maybe_gzip(response):
    if response.status_code != 200 or "Content-Encoding" in response.headers:
        return response
    if response.mimetype not in COMPRESSIBLE:
        return response
    if "no-transform" in response.headers.get("Cache-Control", ""):
        return response
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        response.vary.add("Accept-Encoding")
        return response
    if request.headers.get("Range"):
        return response
    if response.is_streamed and not response.direct_passthrough:
        return response  # generators (e.g. server-sent events) must not be buffered

    etag = response.get_etag()[0]
    key = (etag, request.path) if etag and request.path.startswith("/static/") else None
    if key and key in _static_cache:
        body = _static_cache[key]
    else:
        response.direct_passthrough = False
        raw = response.get_data()
        if len(raw) < MIN_SIZE:
            return response
        body = gzip.compress(raw, compresslevel=GZIP_LEVEL, mtime=0)
        if key:
            _static_cache[key] = body

    response.set_data(body)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(body))
    response.vary.add("Accept-Encoding")
    if etag:
        response.set_etag(etag, weak=True)
    return response
