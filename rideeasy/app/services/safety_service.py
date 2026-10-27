"""Rider and driver safety: trip PIN, trip sharing, SOS alerts and emergency contacts."""
import hmac
import re
import secrets
import threading
import time
import uuid

from flask import current_app, url_for

from app.repositories.database import get_db
from app.services.driver_location_service import DriverLocationService
from app.services.geo import valid_point
from app.services.notification_service import NotificationService
from app.services.sms_service import SmsService

ACTIVE_STATUSES = ("DRIVER_ASSIGNED", "DRIVER_ARRIVING", "DRIVER_ARRIVED", "TRIP_STARTED")
SHAREABLE_STATUSES = ACTIVE_STATUSES
MAX_EMERGENCY_CONTACTS = 5
PHONE_PATTERN = re.compile(r"\+?[0-9][0-9 \-]{6,18}")
PIN_PATTERN = re.compile(r"[0-9]{4}")


class SafetyError(Exception):
    """A safety request that cannot be completed; the message is safe to show."""


def _first_name(full_name) -> str:
    parts = str(full_name or "").split()
    return parts[0] if parts else "Rider"


class SafetyService:
    # ------------------------------------------------------------------ trip PIN
    PIN_MAX_FAILURES = 5
    PIN_LOCK_SECONDS = 300
    _pin_lock = threading.Lock()
    _pin_failures: dict = {}

    @classmethod
    def reset_pin_state(cls) -> None:
        with cls._pin_lock:
            cls._pin_failures.clear()

    @staticmethod
    def pin_required() -> bool:
        return bool(current_app.config.get("REQUIRE_TRIP_PIN", True))

    @staticmethod
    def ensure_pin(ride_id: str) -> str | None:
        """Create the 4-digit start PIN once and return it."""
        db = get_db()
        db.execute(
            "UPDATE rides SET start_pin = ? WHERE id = ? AND (start_pin IS NULL OR start_pin = '')",
            (f"{secrets.randbelow(10000):04d}", ride_id),
        )
        row = db.fetchone("SELECT start_pin FROM rides WHERE id = ?", (ride_id,))
        return row["start_pin"] if row else None

    @classmethod
    def verify_pin(cls, ride: dict, submitted: str) -> tuple[bool, str]:
        """Check the PIN the passenger gave the driver. Rides without a PIN are allowed
        (rides created before this feature existed)."""
        if not cls.pin_required() or not ride.get("start_pin"):
            return True, ""
        ride_id = ride["id"]
        now = time.monotonic()
        with cls._pin_lock:
            failures, locked_until = cls._pin_failures.get(ride_id, (0, 0.0))
            if locked_until > now:
                return False, "Too many incorrect PIN attempts. Ask the passenger to confirm, then try again in a few minutes."
        submitted = (submitted or "").strip()
        if PIN_PATTERN.fullmatch(submitted) and hmac.compare_digest(submitted, str(ride["start_pin"])):
            with cls._pin_lock:
                cls._pin_failures.pop(ride_id, None)
            return True, ""
        with cls._pin_lock:
            failures += 1
            locked_until = now + cls.PIN_LOCK_SECONDS if failures >= cls.PIN_MAX_FAILURES else 0.0
            cls._pin_failures[ride_id] = (failures, locked_until)
        if failures == cls.PIN_MAX_FAILURES:
            NotificationService.create_notification(
                user_id=ride["passenger_id"],
                title="Wrong trip PIN entered several times",
                message="Your driver entered an incorrect trip PIN 5 times. Only share your PIN with the driver you are riding with.",
                notif_type="SYSTEM",
                related_entity_id=ride_id,
            )
        return False, "That PIN is not correct. Ask the passenger for the 4-digit trip PIN."

    # --------------------------------------------------------------- trip sharing
    @staticmethod
    def active_share(ride_id: str):
        return get_db().fetchone(
            """SELECT id, token, expires_at FROM trip_shares
               WHERE ride_id = ? AND revoked = 0 AND expires_at > CURRENT_TIMESTAMP
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (ride_id,),
        )

    @classmethod
    def create_share(cls, ride_id: str, passenger_id: str) -> dict:
        db = get_db()
        ride = db.fetchone("SELECT status FROM rides WHERE id = ? AND passenger_id = ?", (ride_id, passenger_id))
        if not ride:
            raise SafetyError("Ride not found.")
        if ride["status"] not in SHAREABLE_STATUSES:
            raise SafetyError("You can share a trip once a driver has accepted it and until it ends.")
        existing = cls.active_share(ride_id)
        if existing:
            return existing
        hours = max(1, int(current_app.config.get("TRIP_SHARE_HOURS", 12)))
        token = secrets.token_urlsafe(24)
        db.execute(
            """INSERT INTO trip_shares (id, ride_id, token, created_by, expires_at)
               VALUES (?, ?, ?, ?, datetime(CURRENT_TIMESTAMP, ?))""",
            (f"shr_{uuid.uuid4().hex[:10]}", ride_id, token, passenger_id, f"+{hours} hours"),
        )
        return cls.active_share(ride_id)

    @staticmethod
    def revoke_shares(ride_id: str, passenger_id: str) -> int:
        return get_db().execute(
            """UPDATE trip_shares SET revoked = 1
               WHERE ride_id = ? AND revoked = 0
                 AND EXISTS (SELECT 1 FROM rides r WHERE r.id = trip_shares.ride_id AND r.passenger_id = ?)""",
            (ride_id, passenger_id),
        )

    @staticmethod
    def share_url(token: str) -> str:
        return url_for("share.track", token=token, _external=True)

    @staticmethod
    def get_shared_trip(token: str):
        """Read-only view for the public share page. First names only, no phone numbers."""
        db = get_db()
        share = db.fetchone(
            """SELECT ride_id, expires_at FROM trip_shares
               WHERE token = ? AND revoked = 0 AND expires_at > CURRENT_TIMESTAMP""",
            (token,),
        )
        if not share:
            return None
        ride = db.fetchone(
            """SELECT r.id, r.status, r.pickup_address, r.pickup_lat, r.pickup_lng,
                      r.destination_address, r.destination_lat, r.destination_lng,
                      r.driver_id, pu.full_name AS passenger_name, du.full_name AS driver_name,
                      v.make, v.model, v.color, v.plate_number
               FROM rides r
               JOIN users pu ON pu.id = r.passenger_id
               LEFT JOIN users du ON du.id = r.driver_id
               LEFT JOIN vehicles v ON v.driver_id = r.driver_id
               WHERE r.id = ?""",
            (share["ride_id"],),
        )
        if not ride:
            return None
        trip = {
            "ride_id": ride["id"],
            "status": ride["status"],
            "active": ride["status"] in ACTIVE_STATUSES,
            "passenger_first_name": _first_name(ride["passenger_name"]),
            "driver_first_name": _first_name(ride["driver_name"]) if ride["driver_id"] else None,
            "vehicle": " ".join(filter(None, (ride["color"], ride["make"], ride["model"]))) or None,
            "plate_number": ride["plate_number"],
            "pickup_address": ride["pickup_address"],
            "destination_address": ride["destination_address"],
            "pickup": {"lat": ride["pickup_lat"], "lng": ride["pickup_lng"]} if valid_point(ride["pickup_lat"], ride["pickup_lng"]) else None,
            "destination": {"lat": ride["destination_lat"], "lng": ride["destination_lng"]} if valid_point(ride["destination_lat"], ride["destination_lng"]) else None,
            "expires_at": share["expires_at"],
            "driver_location": None,
        }
        if trip["active"] and ride["driver_id"]:
            position = DriverLocationService.location_for_driver(
                ride["driver_id"], int(current_app.config.get("DISPATCH_LOCATION_MAX_AGE_SECONDS", 180)) * 2
            )
            if position:
                info = DriverLocationService.progress(ride, position["lat"], position["lng"]) or {}
                trip["driver_location"] = {
                    "lat": position["lat"], "lng": position["lng"], "heading": position["heading"],
                    "age_seconds": position["age_seconds"], **info,
                }
        return trip

    # -------------------------------------------------------- emergency contacts
    @staticmethod
    def list_contacts(user_id: str):
        return get_db().fetchall(
            "SELECT id, name, phone FROM emergency_contacts WHERE user_id = ? ORDER BY created_at ASC, rowid ASC",
            (user_id,),
        )

    @classmethod
    def add_contact(cls, user_id: str, name: str, phone: str) -> None:
        name = (name or "").strip()
        phone = (phone or "").strip()
        if not name or len(name) > 80:
            raise SafetyError("Enter the contact's name (up to 80 characters).")
        if not PHONE_PATTERN.fullmatch(phone):
            raise SafetyError("Enter a valid phone number, for example +256 700 000000.")
        db = get_db()
        count = db.fetchone("SELECT COUNT(*) AS count FROM emergency_contacts WHERE user_id = ?", (user_id,))["count"]
        if count >= MAX_EMERGENCY_CONTACTS:
            raise SafetyError(f"You can save up to {MAX_EMERGENCY_CONTACTS} emergency contacts.")
        db.execute(
            "INSERT INTO emergency_contacts (id, user_id, name, phone) VALUES (?, ?, ?, ?)",
            (f"ec_{uuid.uuid4().hex[:10]}", user_id, name, phone),
        )

    @staticmethod
    def delete_contact(user_id: str, contact_id: str) -> int:
        return get_db().execute(
            "DELETE FROM emergency_contacts WHERE id = ? AND user_id = ?", (contact_id, user_id)
        )

    # ----------------------------------------------------------------------- SOS
    @classmethod
    def trigger_sos(cls, ride_id: str, user: dict, lat=None, lng=None, message: str | None = None) -> dict:
        db = get_db()
        ride = db.fetchone(
            """SELECT id, passenger_id, driver_id, status, pickup_address, destination_address
               FROM rides WHERE id = ?""",
            (ride_id,),
        )
        if not ride or user["id"] not in (ride["passenger_id"], ride["driver_id"]):
            raise SafetyError("Ride not found.")
        if ride["status"] not in ACTIVE_STATUSES:
            raise SafetyError("Emergency alerts are available while a trip is active. If you are in danger, call "
                              f"{current_app.config.get('EMERGENCY_NUMBER', '999')} now.")

        duplicate = db.fetchone(
            """SELECT id FROM safety_incidents
               WHERE ride_id = ? AND reporter_id = ? AND status = 'OPEN'
                 AND created_at >= datetime(CURRENT_TIMESTAMP, '-2 minutes')""",
            (ride_id, user["id"]),
        )
        if duplicate:
            return {"incident_id": duplicate["id"], "duplicate": True, "contacts_notified": 0, "share_url": None}

        if not valid_point(lat, lng):
            lat = lng = None
            if user["id"] == ride["driver_id"]:
                position = DriverLocationService.location_for_driver(user["id"], 3600)
                if position:
                    lat, lng = position["lat"], position["lng"]
        else:
            lat, lng = float(lat), float(lng)
        message = (message or "").strip()[:300] or None

        incident_id = f"sos_{uuid.uuid4().hex[:10]}"
        db.execute(
            """INSERT INTO safety_incidents (id, ride_id, reporter_id, reporter_role, kind, message, lat, lng)
               VALUES (?, ?, ?, ?, 'SOS', ?, ?, ?)""",
            (incident_id, ride_id, user["id"], user["role"], message, lat, lng),
        )
        db.execute(
            """INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
               VALUES (?, ?, 'SOS_TRIGGERED', 'RIDE', ?, ?)""",
            (f"aud_{uuid.uuid4().hex[:8]}", user["id"], ride_id, f"Incident {incident_id}"),
        )

        # A tracking link lets contacts follow the trip; only the passenger's trip can be shared.
        share_link = None
        if user["id"] == ride["passenger_id"]:
            try:
                share_link = cls.share_url(cls.create_share(ride_id, user["id"])["token"])
            except SafetyError:
                share_link = None

        place = f" Last location: https://maps.google.com/?q={lat:.5f},{lng:.5f}." if lat is not None else ""
        track = f" Follow the trip: {share_link}" if share_link else ""
        sms_text = (
            f"RideEasy EMERGENCY: {_first_name(user['full_name'])} pressed the SOS button during a trip "
            f"from {ride['pickup_address']} to {ride['destination_address']}.{place}{track} "
            "Please call them now."
        )
        notified = 0
        for contact in cls.list_contacts(user["id"]):
            if SmsService.send_safety_sms(contact["phone"], sms_text) == "SENT":
                notified += 1

        admins = db.fetchall("SELECT id FROM users WHERE role = 'ADMIN' AND is_active = 1")
        for admin in admins:
            NotificationService.create_notification(
                user_id=admin["id"],
                title="SOS alert from an active trip",
                message=(
                    f"{user['full_name']} ({user['role'].title()}) pressed SOS on ride #{ride_id[:8].upper()}. "
                    f"{place.strip() or 'Location unavailable.'} Open Safety alerts to respond."
                ),
                notif_type="SYSTEM",
                related_entity_id=ride_id,
            )
        return {"incident_id": incident_id, "duplicate": False, "contacts_notified": notified, "share_url": share_link}

    # --------------------------------------------------------------- admin review
    @staticmethod
    def list_incidents(status: str | None = None, limit: int = 100):
        query = """SELECT i.id, i.ride_id, i.kind, i.message, i.lat, i.lng, i.status, i.created_at,
                          i.resolved_at, i.resolution_note, i.reporter_role,
                          u.full_name AS reporter_name, u.phone AS reporter_phone,
                          r.pickup_address, r.destination_address, r.status AS ride_status,
                          du.full_name AS driver_name, du.phone AS driver_phone, v.plate_number
                   FROM safety_incidents i
                   JOIN users u ON u.id = i.reporter_id
                   JOIN rides r ON r.id = i.ride_id
                   LEFT JOIN users du ON du.id = r.driver_id
                   LEFT JOIN vehicles v ON v.driver_id = r.driver_id"""
        params = ()
        if status:
            query += " WHERE i.status = ?"
            params = (status,)
        query += " ORDER BY CASE i.status WHEN 'OPEN' THEN 0 ELSE 1 END, i.created_at DESC LIMIT ?"
        return get_db().fetchall(query, (*params, int(limit)))

    @staticmethod
    def resolve_incident(incident_id: str, admin_id: str, note: str | None) -> bool:
        db = get_db()
        updated = db.execute(
            """UPDATE safety_incidents
               SET status = 'RESOLVED', resolved_at = CURRENT_TIMESTAMP, resolved_by = ?, resolution_note = ?
               WHERE id = ? AND status = 'OPEN'""",
            (admin_id, (note or "").strip()[:500] or None, incident_id),
        )
        if updated:
            db.execute(
                """INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
                   VALUES (?, ?, 'SOS_RESOLVED', 'SAFETY_INCIDENT', ?, ?)""",
                (f"aud_{uuid.uuid4().hex[:8]}", admin_id, incident_id, (note or "")[:200]),
            )
        return bool(updated)
