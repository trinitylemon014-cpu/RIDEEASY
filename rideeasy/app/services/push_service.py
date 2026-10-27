"""Web Push (phone / desktop notifications) using VAPID.

Optional: if VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY are not set, or pywebpush is not
installed, every method quietly does nothing and the in-app notifications keep working.
"""
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import current_app, has_app_context

from app.repositories.database import get_db

logger = logging.getLogger("rideeasy.push")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webpush")
MAX_SUBSCRIPTIONS_PER_USER = 5


class PushService:
    @staticmethod
    def enabled() -> bool:
        if not has_app_context():
            return False
        config = current_app.config
        if not (config.get("VAPID_PUBLIC_KEY") and config.get("VAPID_PRIVATE_KEY")):
            return False
        import importlib.util
        return importlib.util.find_spec("pywebpush") is not None

    @staticmethod
    def public_key() -> str:
        return current_app.config.get("VAPID_PUBLIC_KEY", "") if has_app_context() else ""

    # ------------------------------------------------------------- subscriptions
    @staticmethod
    def save_subscription(user_id: str, subscription: dict) -> bool:
        endpoint = str(subscription.get("endpoint") or "").strip()
        keys = subscription.get("keys") or {}
        p256dh = str(keys.get("p256dh") or "").strip()
        auth = str(keys.get("auth") or "").strip()
        if not (endpoint.startswith("https://") and p256dh and auth) or len(endpoint) > 1000:
            return False
        db = get_db()
        existing = db.fetchall(
            "SELECT id, endpoint FROM push_subscriptions WHERE user_id = ? ORDER BY created_at ASC, rowid ASC",
            (user_id,),
        )
        known = {row["endpoint"] for row in existing}
        if endpoint not in known and len(existing) >= MAX_SUBSCRIPTIONS_PER_USER:
            db.execute("DELETE FROM push_subscriptions WHERE id = ?", (existing[0]["id"],))
        db.execute(
            """INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id,
                   p256dh = excluded.p256dh, auth = excluded.auth""",
            (f"push_{uuid.uuid4().hex[:12]}", user_id, endpoint, p256dh, auth),
        )
        return True

    @staticmethod
    def remove_subscription(user_id: str, endpoint: str) -> int:
        return get_db().execute(
            "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user_id, endpoint),
        )

    # ------------------------------------------------------------------- sending
    @classmethod
    def send_to_user(cls, user_id: str, title: str, body: str, url: str | None = None,
                     tag: str | None = None, ride_id: str | None = None) -> None:
        """Queue a push to every device the user enabled. Never raises.

        When url is None the link is chosen from the person's role: drivers open their
        trip requests, passengers open the ride (or the home page)."""
        try:
            if not cls.enabled():
                return
            subscriptions = get_db().fetchall(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
                (user_id,),
            )
            if not subscriptions:
                return
            if url is None:
                person = get_db().fetchone("SELECT role FROM users WHERE id = ?", (user_id,))
                role = person["role"] if person else ""
                if role == "DRIVER":
                    url = "/driver/requests"
                elif role == "PASSENGER" and ride_id:
                    url = f"/passenger/rides/{ride_id}"
                else:
                    url = "/"
            payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or ride_id or "rideeasy"})
            app = current_app._get_current_object()
            if app.testing:
                cls._deliver(app, subscriptions, payload)
            else:
                _executor.submit(cls._deliver, app, subscriptions, payload)
        except Exception:
            logger.exception("Could not queue web push for user %s", user_id)

    @staticmethod
    def _deliver(app, subscriptions, payload: str) -> None:
        from pywebpush import WebPushException, webpush

        with app.app_context():
            dead = []
            for sub in subscriptions:
                try:
                    webpush(
                        subscription_info={
                            "endpoint": sub["endpoint"],
                            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                        },
                        data=payload,
                        vapid_private_key=app.config["VAPID_PRIVATE_KEY"],
                        vapid_claims={"sub": app.config.get("VAPID_SUBJECT", "mailto:support@rideeasy.ug")},
                        ttl=120,
                        timeout=4,
                    )
                except WebPushException as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status in (404, 410):          # subscription expired or was revoked
                        dead.append(sub["endpoint"])
                    else:
                        logger.warning("Web push failed (%s).", status or type(exc).__name__)
                except Exception as exc:
                    logger.warning("Web push failed (%s).", type(exc).__name__)
            for endpoint in dead:
                try:
                    get_db().execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
                except Exception:
                    logger.exception("Could not remove expired push subscription.")
