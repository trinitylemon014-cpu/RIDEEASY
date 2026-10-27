import uuid
from urllib.parse import urlparse

import requests
from flask import current_app

from app.repositories.database import get_db


class SmsService:
    """Sends transactional texts through a configured EgoSMS-compatible endpoint."""

    @staticmethod
    def send_payment_sms(payment_id: str, phone: str, message: str) -> str:
        endpoint = current_app.config.get("EGOSMS_API_URL", "")
        api_key = current_app.config.get("EGOSMS_API_KEY", "")
        status = "NOT_CONFIGURED"
        provider_message_id = None
        error_message = None

        parsed_endpoint = urlparse(endpoint)
        if endpoint and api_key and parsed_endpoint.scheme == "https" and parsed_endpoint.hostname:
            try:
                response = requests.post(
                    endpoint,
                    json={"to": phone, "message": message},
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=(1, 2)
                )
                response.raise_for_status()
                status = "SENT"
                try:
                    provider_message_id = response.json().get("message_id")
                except (ValueError, AttributeError):
                    provider_message_id = None
            except requests.RequestException as exc:
                status = "FAILED"
                error_message = f"Provider request failed ({type(exc).__name__})."
                current_app.logger.error(
                    "EgoSMS delivery failed for payment %s (%s).",
                    payment_id, type(exc).__name__
                )
        else:
            error_message = "EgoSMS HTTPS endpoint or API key is missing or invalid."
            current_app.logger.warning("EgoSMS is not configured with a valid HTTPS endpoint; SMS was not sent.")

        message_id = f"sms_{uuid.uuid4().hex}"
        get_db().execute(
            """INSERT INTO sms_messages
               (id, payment_id, recipient_phone, message, status, provider_message_id, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, payment_id, phone, message, status, provider_message_id, error_message)
        )
        return status

    @staticmethod
    def send_safety_sms(phone: str, message: str) -> str:
        """Send an emergency text. Returns SENT, FAILED or NOT_CONFIGURED; never raises."""
        endpoint = current_app.config.get("EGOSMS_API_URL", "")
        api_key = current_app.config.get("EGOSMS_API_KEY", "")
        parsed_endpoint = urlparse(endpoint)
        if not (endpoint and api_key and parsed_endpoint.scheme == "https" and parsed_endpoint.hostname):
            current_app.logger.warning("EgoSMS is not configured; safety SMS was not sent.")
            return "NOT_CONFIGURED"
        try:
            response = requests.post(
                endpoint,
                json={"to": phone, "message": message},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=(1, 3)
            )
            response.raise_for_status()
            return "SENT"
        except requests.RequestException as exc:
            current_app.logger.error("Safety SMS delivery failed (%s).", type(exc).__name__)
            return "FAILED"
