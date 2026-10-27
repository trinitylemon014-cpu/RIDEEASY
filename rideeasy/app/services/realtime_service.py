"""In-process publish/subscribe used for server-sent events (SSE).

Events are small "something changed" hints (plus live driver positions). The pages
still read the truth from the database, so a missed event only means the normal
polling fallback picks the change up a few seconds later.

This is process-local: it works with one gunicorn worker (the Render default for
this app). Running several workers or instances needs a shared broker such as Redis.
"""
import json
import queue
import threading
import time


class RealtimeService:
    MAX_STREAMS_PER_USER = 3
    QUEUE_SIZE = 50

    _lock = threading.Lock()
    _subscribers: dict = {}
    _total = 0

    # ------------------------------------------------------------------ subscribe
    @classmethod
    def subscribe(cls, user_id: str, max_total: int = 20):
        """Register a stream. Returns a Queue, or None when the server is at capacity."""
        with cls._lock:
            if cls._total >= max_total:
                return None
            streams = cls._subscribers.setdefault(user_id, [])
            while len(streams) >= cls.MAX_STREAMS_PER_USER:
                oldest = streams.pop(0)          # a new tab replaces the oldest one
                cls._total -= 1
                try:
                    oldest.put_nowait(None)      # tells that stream to finish
                except queue.Full:
                    pass
            channel = queue.Queue(maxsize=cls.QUEUE_SIZE)
            streams.append(channel)
            cls._total += 1
            return channel

    @classmethod
    def unsubscribe(cls, user_id: str, channel) -> None:
        with cls._lock:
            streams = cls._subscribers.get(user_id)
            if streams and channel in streams:
                streams.remove(channel)
                cls._total -= 1
                if not streams:
                    cls._subscribers.pop(user_id, None)

    @classmethod
    def stream_count(cls) -> int:
        with cls._lock:
            return cls._total

    @classmethod
    def has_subscribers(cls) -> bool:
        return cls._total > 0

    @classmethod
    def reset(cls) -> None:
        """Test helper."""
        with cls._lock:
            cls._subscribers.clear()
            cls._total = 0

    # -------------------------------------------------------------------- publish
    @classmethod
    def publish_user(cls, user_id: str, event_type: str, data: dict | None = None) -> int:
        """Send an event to every open stream of one user. Returns how many got it."""
        if not user_id or not cls._total:
            return 0
        payload = {"type": event_type, "ts": int(time.time()), **(data or {})}
        delivered = 0
        with cls._lock:
            for channel in list(cls._subscribers.get(user_id, ())):
                try:
                    channel.put_nowait(payload)
                except queue.Full:
                    try:                          # drop the oldest hint, keep the newest
                        channel.get_nowait()
                        channel.put_nowait(payload)
                    except (queue.Empty, queue.Full):
                        continue
                delivered += 1
        return delivered

    @classmethod
    def publish_ride(cls, ride_id: str, data: dict | None = None, event_type: str = "ride") -> int:
        """Tell both people on a ride that it changed (skips the lookup if nobody listens)."""
        if not ride_id or not cls._total:
            return 0
        from app.repositories.database import get_db
        ride = get_db().fetchone("SELECT passenger_id, driver_id, status FROM rides WHERE id = ?", (ride_id,))
        if not ride:
            return 0
        body = {"ride_id": ride_id, "status": ride["status"], **(data or {})}
        delivered = 0
        for user_id in {ride["passenger_id"], ride["driver_id"]} - {None}:
            delivered += cls.publish_user(user_id, event_type, body)
        return delivered

    # ------------------------------------------------------------------ streaming
    @staticmethod
    def format_event(payload: dict) -> str:
        event_type = payload.get("type", "message")
        return f"event: {event_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

    @classmethod
    def event_stream(cls, user_id: str, channel, max_seconds: int = 55, heartbeat: int = 15):
        """Generator for a text/event-stream response. Ends after max_seconds so the
        browser reconnects and the server thread is released."""
        deadline = time.monotonic() + max(1, max_seconds)
        try:
            yield "retry: 3000\n\n"
            yield cls.format_event({"type": "ready", "ts": int(time.time())})
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield cls.format_event({"type": "reconnect", "ts": int(time.time())})
                    return
                try:
                    payload = channel.get(timeout=min(heartbeat, remaining))
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if payload is None:
                    return
                yield cls.format_event(payload)
        finally:
            cls.unsubscribe(user_id, channel)
