from app.repositories.database import get_db
from app.services.notification_service import NotificationService


class RideDispatchService:
    """Assign eligible online drivers to rides awaiting dispatch."""

    @staticmethod
    def dispatch_ride(ride_id: str, excluded_driver_ids=None) -> str | None:
        db = get_db()
        excluded = set(excluded_driver_ids or ())
        candidates = db.fetchall(
            """SELECT d.user_id, u.full_name, v.plate_number, v.make, v.model
               FROM driver_profiles d
               JOIN users u ON u.id = d.user_id
               JOIN vehicles v ON v.driver_id = d.user_id
               WHERE d.is_online = 1 AND d.verification_status = 'APPROVED'
                 AND u.is_active = 1 AND v.is_active = 1 AND v.is_verified = 1
                 AND NOT EXISTS (
                   SELECT 1 FROM rides active
                   WHERE active.driver_id = d.user_id
                     AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                 )
               ORDER BY d.rating_avg DESC, d.total_trips ASC""",
        )

        for candidate in candidates:
            driver_id = candidate["user_id"]
            if driver_id in excluded:
                continue
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
                         AND NOT EXISTS (
                           SELECT 1 FROM rides active
                           WHERE active.driver_id = ?
                             AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                         )""",
                    (driver_id, ride_id, driver_id, driver_id, driver_id)
                )
            ])[0]
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
            NotificationService.create_notification(
                user_id=driver_id,
                title="New trip awaiting your response",
                message=(
                    f"{ride['passenger_name']} requested a ride. Review the trip and accept or "
                    f"decline it. Pickup: {ride['pickup_address']}."
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
    def notify_passenger_driver_declined(ride_id: str, passenger_id: str, driver_name: str) -> None:
        NotificationService.create_notification(
            user_id=passenger_id,
            title="Driver unavailable",
            message=f"{driver_name} is no longer available for your ride. RideEasy is looking for another available driver.",
            notif_type="SYSTEM",
            related_entity_id=ride_id
        )
