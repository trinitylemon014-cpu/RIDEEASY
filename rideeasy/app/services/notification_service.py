import uuid
from typing import List, Dict, Any, Optional
from app.repositories.database import get_db

class NotificationService:
    """Manages in-app notifications for users, driver assignments, and trip alerts."""

    @staticmethod
    def create_notification(user_id: str, title: str, message: str, notif_type: str = "SYSTEM", related_entity_id: Optional[str] = None) -> str:
        db = get_db()
        notif_id = f"notif_{uuid.uuid4().hex[:10]}"
        db.execute(
            """INSERT INTO notifications (id, user_id, title, message, type, is_read, related_entity_id)
            VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (notif_id, user_id, title, message, notif_type, related_entity_id)
        )
        return notif_id

    @staticmethod
    def get_user_notifications(user_id: str, unread_only: bool = False, limit: int = 20) -> List[Dict[str, Any]]:
        db = get_db()
        if unread_only:
            return db.fetchall(
                "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
        return db.fetchall(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )

    @staticmethod
    def get_unread_count(user_id: str) -> int:
        db = get_db()
        row = db.fetchone("SELECT COUNT(*) as c FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,))
        return row["c"] if row else 0

    @staticmethod
    def mark_as_read(notif_id: str, user_id: str) -> bool:
        db = get_db()
        return db.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notif_id, user_id)) > 0

    @staticmethod
    def mark_all_as_read(user_id: str) -> int:
        db = get_db()
        return db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
