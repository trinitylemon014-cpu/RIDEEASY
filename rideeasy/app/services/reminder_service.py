import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.repositories.database import get_db

class ReminderService:
    """Manages scheduled travel reminders for confirmed flight journeys."""

    @staticmethod
    def schedule_journey_reminders(journey_id: str, departure_datetime_str: str, origin: str, destination: str):
        """
        Schedules automated 5-tier travel reminders relative to flight departure:
        - 7 days before
        - 3 days before
        - 2 days before
        - 1 day before
        - Travel day (4 hours prior)
        """
        db = get_db()
        try:
            dep_dt = datetime.fromisoformat(departure_datetime_str.replace("Z", "").replace(" ", "T"))
        except Exception:
            dep_dt = datetime.now() + timedelta(days=7)

        intervals = [
            ("7_DAYS", dep_dt - timedelta(days=7), "Passport & Visa Verification",
             f"7 days until your flight to {destination}. Verify your passport validity has at least 6 months remaining and check foreign entry requirements."),
            ("3_DAYS", dep_dt - timedelta(days=3), "Arrange Airport Transportation",
             f"3 days until departure. Don't leave your airport trip to chance. Book a confirmed RideEasy airport ride from your pickup location to {origin}."),
            ("2_DAYS", dep_dt - timedelta(days=2), "Baggage Allowance & Packing",
             "2 days to go. Check your airline luggage allowance, prepare carry-on items, and ensure all electronics are safely packed."),
            ("1_DAY", dep_dt - timedelta(days=1), "Online Check-in Open",
             "24 hours until departure. Online check-in is now open. Confirm your seat selection and download your boarding pass."),
            ("TRAVEL_DAY", dep_dt - timedelta(hours=4), "Flight Departure Today",
             f"Travel day! Your flight departs today at {dep_dt.strftime('%H:%M')}. Allow at least 3 hours for airport check-in and security.")
        ]

        # Clear any existing non-delivered reminders for this journey to prevent duplicates
        db.execute("DELETE FROM journey_reminders WHERE journey_id = ? AND is_delivered = 0", (journey_id,))

        for rtype, sched_dt, title, msg in intervals:
            rem_id = f"rem_{uuid.uuid4().hex[:10]}"
            sched_str = sched_dt.strftime("%Y-%m-%d %H:%M:%S")
            # If scheduled date is in the past, mark as delivered for demo purposes
            is_deliv = 1 if sched_dt < datetime.now() else 0
            deliv_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_deliv else None

            db.execute(
                """INSERT INTO journey_reminders 
                (id, journey_id, reminder_type, scheduled_for, title, message, is_delivered, delivered_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (rem_id, journey_id, rtype, sched_str, title, msg, is_deliv, deliv_at)
            )

    @staticmethod
    def get_journey_reminders(journey_id: str) -> List[Dict[str, Any]]:
        db = get_db()
        return db.fetchall(
            "SELECT * FROM journey_reminders WHERE journey_id = ? ORDER BY scheduled_for ASC",
            (journey_id,)
        )

    @staticmethod
    def get_user_pending_reminders(user_id: str) -> List[Dict[str, Any]]:
        db = get_db()
        return db.fetchall(
            """SELECT r.*, j.origin, j.destination, j.departure_datetime 
            FROM journey_reminders r
            JOIN confirmed_journeys j ON r.journey_id = j.id
            WHERE j.passenger_id = ?
            ORDER BY r.scheduled_for ASC""",
            (user_id,)
        )
