"""Stores driver GPS positions and streams them to the passenger on an active trip."""
import threading
import time

from flask import current_app

from app.repositories.database import get_db
from app.services.geo import eta_minutes, haversine_km, valid_point
from app.services.realtime_service import RealtimeService

ACTIVE_TRIP_STATUSES = ("DRIVER_ASSIGNED", "DRIVER_ARRIVING", "DRIVER_ARRIVED", "TRIP_STARTED")
MAX_ACCURACY_M = 1000.0


class DriverLocationService:
    MIN_INTERVAL_SECONDS = 2.0        # ignore updates arriving faster than this
    TRIP_POINT_INTERVAL_SECONDS = 10.0  # route history resolution while a trip is running

    _lock = threading.Lock()
    _last_write: dict = {}
    _last_point: dict = {}

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._last_write.clear()
            cls._last_point.clear()

    @staticmethod
    def active_ride_for_driver(driver_id: str):
        return get_db().fetchone(
            """SELECT id, passenger_id, status, pickup_lat, pickup_lng,
                      destination_lat, destination_lng
               FROM rides
               WHERE driver_id = ? AND driver_response_status = 'ACCEPTED'
                 AND status IN ('DRIVER_ASSIGNED', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'TRIP_STARTED')
               ORDER BY updated_at DESC LIMIT 1""",
            (driver_id,),
        )

    @staticmethod
    def progress(ride: dict, lat: float, lng: float) -> dict | None:
        """Distance and ETA from a position to the next stop of the trip."""
        if ride["status"] == "TRIP_STARTED":
            target, label = (ride.get("destination_lat"), ride.get("destination_lng")), "destination"
        else:
            target, label = (ride.get("pickup_lat"), ride.get("pickup_lng")), "pickup"
        if not valid_point(*target):
            return None
        distance = haversine_km(lat, lng, target[0], target[1])
        speed = current_app.config.get("ETA_AVERAGE_SPEED_KMH", 25.0)
        return {
            "target": label,
            "distance_km": round(distance, 2),
            "eta_minutes": round(eta_minutes(distance, speed), 1),
        }

    @classmethod
    def update(cls, driver_id: str, lat, lng, heading=None, accuracy=None) -> dict:
        """Validate and store a position. Raises ValueError for unusable input."""
        if not valid_point(lat, lng):
            raise ValueError("Invalid coordinates.")
        lat, lng = float(lat), float(lng)
        try:
            accuracy = float(accuracy) if accuracy is not None else None
        except (TypeError, ValueError):
            accuracy = None
        if accuracy is not None and accuracy > MAX_ACCURACY_M:
            return {"ok": True, "ignored": "low_accuracy"}
        try:
            heading = float(heading) if heading is not None else None
            if heading is not None and not 0 <= heading <= 360:
                heading = None
        except (TypeError, ValueError):
            heading = None

        now = time.monotonic()
        with cls._lock:
            previous = cls._last_write.get(driver_id)
            if previous is not None and now - previous < cls.MIN_INTERVAL_SECONDS:
                return {"ok": True, "throttled": True}
            cls._last_write[driver_id] = now

        db = get_db()
        updated = db.execute(
            """UPDATE driver_profiles
               SET current_lat = ?, current_lng = ?, location_heading = ?,
                   location_accuracy_m = ?, location_updated_at = CURRENT_TIMESTAMP
               WHERE user_id = ?""",
            (lat, lng, heading, accuracy, driver_id),
        )
        if not updated:
            raise LookupError("Driver profile not found.")

        result = {"ok": True, "ride_id": None}
        ride = cls.active_ride_for_driver(driver_id)
        if not ride:
            return result
        result["ride_id"] = ride["id"]

        info = cls.progress(ride, lat, lng) or {}
        RealtimeService.publish_user(ride["passenger_id"], "location", {
            "ride_id": ride["id"], "status": ride["status"],
            "lat": lat, "lng": lng, "heading": heading, **info,
        })

        if ride["status"] == "TRIP_STARTED":
            with cls._lock:
                last = cls._last_point.get(ride["id"])
                due = last is None or now - last >= cls.TRIP_POINT_INTERVAL_SECONDS
                if due:
                    cls._last_point[ride["id"]] = now
            if due:
                db.execute(
                    "INSERT INTO ride_location_points (ride_id, driver_id, lat, lng, heading) VALUES (?, ?, ?, ?, ?)",
                    (ride["id"], driver_id, lat, lng, heading),
                )
        result.update(info)
        return result

    @staticmethod
    def location_for_driver(driver_id: str, max_age_seconds: int):
        """Latest stored position, or None if missing or older than max_age_seconds."""
        row = get_db().fetchone(
            """SELECT current_lat AS lat, current_lng AS lng, location_heading AS heading,
                      CAST((julianday('now') - julianday(location_updated_at)) * 86400 AS INTEGER) AS age_seconds
               FROM driver_profiles WHERE user_id = ? AND location_updated_at IS NOT NULL""",
            (driver_id,),
        )
        if not row or not valid_point(row["lat"], row["lng"]):
            return None
        if row["age_seconds"] is None or row["age_seconds"] > max_age_seconds:
            return None
        return row
