import uuid

from flask import current_app, has_app_context
from app.repositories.database import get_db
from app.services.geo import eta_minutes, haversine_km, valid_point
from app.services.notification_service import NotificationService


def _config(key, default=None):
    """App config when a Flask app is active, otherwise the module-level Config."""
    if has_app_context():
        return current_app.config.get(key, default)
    from app.config import Config
    return getattr(Config, key, default)


class RideDispatchService:
    """Assign eligible online drivers to rides awaiting dispatch."""

    @staticmethod
    def dispatch_ride(ride_id: str, excluded_driver_ids=None) -> str | None:
        RideDispatchService.expire_stale_offers(ride_id)
        return RideDispatchService._dispatch_ride(ride_id, excluded_driver_ids)

    @staticmethod
    def _dispatch_ride(ride_id: str, excluded_driver_ids=None) -> str | None:
        db = get_db()
        existing_ride = db.fetchone(
            "SELECT driver_id, status, pickup_lat, pickup_lng FROM rides WHERE id = ?",
            (ride_id,)
        )
        if not existing_ride or existing_ride["status"] not in ("REQUESTED", "SEARCHING_FOR_DRIVER"):
            return (
                existing_ride["driver_id"]
                if existing_ride and existing_ride["status"] == "DRIVER_ASSIGNED"
                else None
            )

        excluded = set(excluded_driver_ids or ())
        required_documents = tuple(_config("DISPATCH_REQUIRED_DOC_TYPES") or ())
        document_checks = "".join(
            """ AND EXISTS (
                   SELECT 1 FROM driver_documents dd
                   WHERE dd.driver_id = d.user_id AND dd.doc_type = ? AND dd.status = 'APPROVED'
                     AND (dd.expires_at IS NULL OR dd.expires_at >= date('now'))
                 )"""
            for _ in required_documents
        )
        raw_candidates = db.fetchall(
            """SELECT d.user_id, u.full_name, v.plate_number, v.make, v.model,
                      d.current_lat, d.current_lng, d.rating_avg, d.total_trips,
                      CAST((julianday('now') - julianday(d.location_updated_at)) * 86400 AS INTEGER)
                          AS location_age_seconds
               FROM driver_profiles d
               JOIN users u ON u.id = d.user_id
               JOIN vehicles v ON v.driver_id = d.user_id
               WHERE d.is_online = 1 AND d.verification_status = 'APPROVED'
                 AND u.is_active = 1 AND v.is_active = 1 AND v.is_verified = 1
                 AND NOT EXISTS (
                   SELECT 1 FROM ride_driver_offers previous
                   WHERE previous.ride_id = ? AND previous.driver_id = d.user_id
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM rides active
                   WHERE active.driver_id = d.user_id
                     AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                 )"""
            + document_checks,
            (ride_id, *required_documents)
        )
        candidates = RideDispatchService.rank_candidates(
            raw_candidates, existing_ride.get("pickup_lat"), existing_ride.get("pickup_lng")
        )

        for candidate in candidates:
            driver_id = candidate["user_id"]
            if driver_id in excluded:
                continue
            timeout_seconds = min(
                300,
                max(1, int(current_app.config["DRIVER_RIDE_OFFER_TIMEOUT_SECONDS"]))
            )
            timeout_modifier = f"+{timeout_seconds} seconds"
            try:
                assigned = db.execute_transaction([
                    (
                        """UPDATE rides
                           SET driver_id = ?, status = 'DRIVER_ASSIGNED',
                               driver_response_status = 'PENDING', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND status IN ('REQUESTED', 'SEARCHING_FOR_DRIVER')
                             AND driver_id IS NULL
                             AND EXISTS (
                               SELECT 1 FROM driver_profiles d
                               WHERE d.user_id = ? AND d.is_online = 1
                                 AND d.verification_status = 'APPROVED'
                             )
                             AND EXISTS (
                               SELECT 1 FROM users u
                               WHERE u.id = ? AND u.is_active = 1
                             )
                             AND EXISTS (
                               SELECT 1 FROM vehicles v
                               WHERE v.driver_id = ? AND v.is_active = 1 AND v.is_verified = 1
                             )
                             AND NOT EXISTS (
                               SELECT 1 FROM rides active
                               WHERE active.driver_id = ?
                                 AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                             )
                             AND NOT EXISTS (
                               SELECT 1 FROM ride_driver_offers previous
                               WHERE previous.ride_id = ? AND previous.driver_id = ?
                             )""",
                        (driver_id, ride_id, driver_id, driver_id, driver_id, driver_id, ride_id, driver_id),
                        1
                    ),
                    (
                        """INSERT INTO ride_driver_offers (ride_id, driver_id, status, expires_at)
                           SELECT ?, ?, 'PENDING', datetime(CURRENT_TIMESTAMP, ?)
                           WHERE EXISTS (
                             SELECT 1 FROM rides
                             WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED'
                               AND driver_response_status = 'PENDING'
                           )""",
                        (ride_id, driver_id, timeout_modifier, ride_id, driver_id),
                        1
                    ),
                ])[0]
            except RuntimeError:
                current_ride = db.fetchone(
                    "SELECT driver_id, status FROM rides WHERE id = ?",
                    (ride_id,)
                )
                if current_ride and current_ride["status"] == "DRIVER_ASSIGNED":
                    return current_ride["driver_id"]
                if not current_ride or current_ride["status"] not in ("REQUESTED", "SEARCHING_FOR_DRIVER"):
                    return None
                candidate_available = db.fetchone(
                    """SELECT d.user_id
                       FROM driver_profiles d
                       JOIN users u ON u.id = d.user_id
                       JOIN vehicles v ON v.driver_id = d.user_id
                       WHERE d.user_id = ? AND d.is_online = 1
                         AND d.verification_status = 'APPROVED' AND u.is_active = 1
                         AND v.is_active = 1 AND v.is_verified = 1
                         AND NOT EXISTS (
                           SELECT 1 FROM rides active
                           WHERE active.driver_id = d.user_id
                             AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                         )""",
                    (driver_id,)
                )
                if not candidate_available:
                    continue
                raise
            if assigned != 1:
                continue

            ride = db.fetchone(
                """SELECT r.passenger_id, r.id, r.pickup_address, u.full_name AS passenger_name
                   FROM rides r JOIN users u ON u.id = r.passenger_id
                   WHERE r.id = ?""",
                (ride_id,)
            )
            if not ride:
                return None
            vehicle = " ".join(filter(None, (
                candidate.get("plate_number"), candidate.get("make"), candidate.get("model")
            )))
            distance_km = candidate.get("pickup_distance_km")
            distance_note = ""
            if distance_km is not None:
                pickup_eta = round(eta_minutes(distance_km, _config("ETA_AVERAGE_SPEED_KMH", 25.0)), 1)
                db.execute("UPDATE rides SET pickup_eta_minutes = ? WHERE id = ?", (pickup_eta, ride_id))
                distance_note = f" You are about {distance_km:.1f} km from the pickup (~{round(pickup_eta)} min)."
            NotificationService.create_notification(
                user_id=driver_id,
                title="New trip awaiting your response",
                message=(
                    f"{ride['passenger_name']} requested a ride. Review the trip and accept or "
                    f"decline it. Pickup: {ride['pickup_address']}.{distance_note}"
                ),
                notif_type="SYSTEM",
                related_entity_id=ride_id
            )
            NotificationService.create_notification(
                user_id=ride["passenger_id"],
                title="Driver requested to take your ride",
                message=f"{candidate['full_name']} ({vehicle}) has been asked to take your trip. Tracking starts after the driver accepts.",
                notif_type="DRIVER_ASSIGNED",
                related_entity_id=ride_id
            )
            return driver_id

        return None

    @staticmethod
    def rank_candidates(candidates, pickup_lat, pickup_lng):
        """Order eligible drivers nearest-first.

        Drivers are grouped by how far they are from the pickup in 0.5 km steps, and
        ties inside a step go to the better-rated driver with fewer trips. Drivers who
        are beyond DISPATCH_MAX_RADIUS_KM, or whose location is missing or stale, are
        skipped (or placed last when DISPATCH_REQUIRE_DRIVER_LOCATION is off).
        Without usable pickup coordinates the previous rating-based order is kept.
        """
        max_age = int(_config("DISPATCH_LOCATION_MAX_AGE_SECONDS", 180))
        radius_km = float(_config("DISPATCH_MAX_RADIUS_KM", 15))
        require_location = bool(_config("DISPATCH_REQUIRE_DRIVER_LOCATION", True))
        has_pickup = valid_point(pickup_lat, pickup_lng)

        ranked = []
        for candidate in candidates:
            candidate = dict(candidate)
            distance = None
            if (
                has_pickup
                and valid_point(candidate.get("current_lat"), candidate.get("current_lng"))
                and candidate.get("location_age_seconds") is not None
                and candidate["location_age_seconds"] <= max_age
            ):
                distance = haversine_km(
                    candidate["current_lat"], candidate["current_lng"], pickup_lat, pickup_lng
                )
            group, bucket = 0, 0
            if has_pickup:
                if distance is None:
                    if require_location:
                        continue
                    group = 1
                else:
                    if distance > radius_km:
                        continue
                    bucket = round(distance / 0.5)
            candidate["pickup_distance_km"] = round(distance, 2) if distance is not None else None
            sort_key = (
                group, bucket,
                -(candidate.get("rating_avg") or 0), candidate.get("total_trips") or 0,
                candidate["pickup_distance_km"] if candidate["pickup_distance_km"] is not None else 0,
            )
            ranked.append((sort_key, candidate))
        ranked.sort(key=lambda item: item[0])
        return [candidate for _, candidate in ranked]

    @staticmethod
    def expire_unmatched_rides(ride_id: str | None = None) -> int:
        """Cancel rides that have searched for RIDE_SEARCH_TIMEOUT_MINUTES without a driver.

        Mirrors a passenger cancellation: pending offers are closed and any reward
        voucher used on the ride is released.
        """
        minutes = int(_config("RIDE_SEARCH_TIMEOUT_MINUTES", 10))
        if minutes <= 0:
            return 0
        db = get_db()
        query = """SELECT id, passenger_id FROM rides
                   WHERE driver_id IS NULL AND status = 'SEARCHING_FOR_DRIVER'
                     AND created_at <= datetime(CURRENT_TIMESTAMP, ?)"""
        params = (f"-{minutes} minutes",)
        if ride_id is not None:
            query += " AND id = ?"
            params += (ride_id,)
        cancelled = 0
        reason = f"No driver was available within {minutes} minutes"
        for ride in db.fetchall(query, params):
            try:
                db.execute_transaction([
                    (
                        """UPDATE rides SET status = 'CANCELLED', cancellation_reason = ?,
                                  cancelled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND driver_id IS NULL AND status = 'SEARCHING_FOR_DRIVER'""",
                        (reason, ride["id"]),
                        1
                    ),
                    (
                        """UPDATE ride_driver_offers SET status = 'CANCELLED', responded_at = CURRENT_TIMESTAMP
                           WHERE ride_id = ? AND status = 'PENDING'""",
                        (ride["id"],)
                    ),
                    (
                        """UPDATE rewards_redemptions SET status = 'ACTIVE', ride_id = NULL
                           WHERE ride_id = ? AND status = 'USED'""",
                        (ride["id"],)
                    ),
                    (
                        """INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
                           VALUES (?, NULL, 'RIDE_AUTO_CANCELLED_NO_DRIVER', 'RIDE', ?, ?)""",
                        (f"aud_{uuid.uuid4().hex[:8]}", ride["id"], reason)
                    ),
                ])
            except RuntimeError:
                continue       # a driver was assigned or the ride changed in the meantime
            cancelled += 1
            NotificationService.create_notification(
                user_id=ride["passenger_id"],
                title="No driver available",
                message=(
                    f"We could not find a driver for ride #{ride['id'][:8].upper()} within {minutes} "
                    "minutes, so the request was cancelled. Please try again shortly."
                ),
                notif_type="CANCELLATION",
                related_entity_id=ride["id"]
            )
        return cancelled

    @staticmethod
    def expire_stale_offers(ride_id: str | None = None) -> int:
        """Expire pending offers once, release their rides, and dispatch to an untried driver."""
        db = get_db()
        query = """SELECT ride_id, driver_id FROM ride_driver_offers
                   WHERE status = 'PENDING' AND expires_at <= CURRENT_TIMESTAMP"""
        params = ()
        if ride_id is not None:
            query += " AND ride_id = ?"
            params = (ride_id,)
        expired = db.fetchall(query, params)
        processed = 0
        for offer in expired:
            ride_id = offer["ride_id"]
            driver_id = offer["driver_id"]
            try:
                updated = db.execute_transaction([
                    (
                        """UPDATE ride_driver_offers
                           SET status = 'EXPIRED', responded_at = CURRENT_TIMESTAMP
                           WHERE ride_id = ? AND driver_id = ? AND status = 'PENDING'
                             AND expires_at <= CURRENT_TIMESTAMP""",
                        (ride_id, driver_id),
                        1
                    ),
                    (
                        """UPDATE rides
                           SET driver_id = NULL, status = 'SEARCHING_FOR_DRIVER',
                               driver_response_status = 'DECLINED', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED'
                             AND driver_response_status = 'PENDING'""",
                        (ride_id, driver_id)
                    ),
                ])
            except RuntimeError:
                current_offer = db.fetchone(
                    "SELECT status FROM ride_driver_offers WHERE ride_id = ? AND driver_id = ?",
                    (ride_id, driver_id)
                )
                if not current_offer or current_offer["status"] != "PENDING":
                    continue
                raise
            if updated[0] != 1 or updated[1] != 1:
                continue

            ride = db.fetchone(
                "SELECT passenger_id FROM rides WHERE id = ? AND status = 'SEARCHING_FOR_DRIVER'",
                (ride_id,)
            )
            driver = db.fetchone("SELECT full_name FROM users WHERE id = ?", (driver_id,))
            if ride and driver:
                RideDispatchService.notify_passenger_driver_declined(
                    ride_id, ride["passenger_id"], driver["full_name"]
                )
            next_driver_id = RideDispatchService._dispatch_ride(ride_id)
            if not next_driver_id:
                RideDispatchService.notify_passenger_no_driver(ride_id)
            processed += 1
        return processed

    @staticmethod
    def decline_offer(ride_id: str, driver_id: str) -> bool:
        """Atomically decline an active offer before trying another eligible driver."""
        db = get_db()
        updated = db.execute_transaction([
            (
                """UPDATE ride_driver_offers
                   SET status = 'DECLINED', responded_at = CURRENT_TIMESTAMP
                   WHERE ride_id = ? AND driver_id = ? AND status = 'PENDING'
                     AND expires_at > CURRENT_TIMESTAMP""",
                (ride_id, driver_id),
                1
            ),
            (
                """UPDATE rides
                   SET driver_id = NULL, status = 'SEARCHING_FOR_DRIVER',
                       driver_response_status = 'DECLINED', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED'
                     AND driver_response_status = 'PENDING'""",
                (ride_id, driver_id),
                1
            ),
        ])
        return updated == [1, 1]

    @staticmethod
    def notify_passenger_driver_declined(ride_id: str, passenger_id: str, driver_name: str) -> None:
        NotificationService.create_notification(
            user_id=passenger_id,
            title="Driver unavailable",
            message=f"{driver_name} is no longer available for your ride. RideEasy is continuing to search; your request remains active.",
            notif_type="SYSTEM",
            related_entity_id=ride_id
        )

    @staticmethod
    def notify_passenger_no_driver(ride_id: str) -> None:
        ride = get_db().fetchone(
            "SELECT passenger_id FROM rides WHERE id = ? AND status = 'SEARCHING_FOR_DRIVER'",
            (ride_id,)
        )
        if ride:
            NotificationService.create_notification(
                user_id=ride["passenger_id"],
                title="Still searching for a driver",
                message="No available driver has accepted yet. Your request remains active, and RideEasy will offer it when another eligible driver is available.",
                notif_type="SYSTEM",
                related_entity_id=ride_id
            )
