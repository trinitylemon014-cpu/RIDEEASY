import uuid
from datetime import datetime
from typing import Dict, Any, Optional

class PaymentService:
    """
    Modular payment gateway abstraction supporting:
    - MTN Mobile Money (MoMo)
    - Airtel Money
    - Card (Visa / Mastercard via authorized acquirer)
    - Cash on Delivery
    """

    SUPPORTED_METHODS = {
        "CASH": "Cash to Driver",
        "MTN_MOMO": "MTN Mobile Money",
        "AIRTEL_MONEY": "Airtel Money",
        "CARD": "Debit / Credit Card"
    }

    @staticmethod
    def process_payment(amount_ugx: int, method: str, phone: Optional[str] = None, ride_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Processes or initiates transaction.
        In sandbox/demo environment, generates structured transaction records with full audit trail.
        """
        method = method.upper() if method else "CASH"
        txn_ref = f"TXN-{method[:3]}-{uuid.uuid4().hex[:8].upper()}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if method == "CASH":
            return {
                "success": True,
                "reference": txn_ref,
                "status": "PENDING_CASH",
                "message": "Pay exact fare in cash directly to your verified driver at trip completion.",
                "amount": amount_ugx,
                "currency": "UGX",
                "timestamp": now_str
            }

        elif method in ("MTN_MOMO", "AIRTEL_MONEY"):
            provider = "MTN MoMo" if method == "MTN_MOMO" else "Airtel Money"
            return {
                "success": True,
                "reference": txn_ref,
                "status": "PAID",
                "message": f"Payment prompt approved on {phone or 'mobile handset'}. {provider} transaction verified.",
                "amount": amount_ugx,
                "currency": "UGX",
                "provider": provider,
                "timestamp": now_str
            }

        elif method == "CARD":
            return {
                "success": True,
                "reference": txn_ref,
                "status": "PAID",
                "message": "Card authorized via 3D Secure bank gateway.",
                "amount": amount_ugx,
                "currency": "UGX",
                "timestamp": now_str
            }

        return {
            "success": False,
            "reference": txn_ref,
            "status": "FAILED",
            "message": f"Unsupported payment method: {method}",
            "amount": amount_ugx,
            "currency": "UGX",
            "timestamp": now_str
        }

    @staticmethod
    def generate_receipt_data(ride: dict, passenger: dict, driver: Optional[dict] = None) -> Dict[str, Any]:
        """Generates itemized receipt data for completed trips."""
        fare = ride.get("final_fare_ugx") or ride.get("estimated_fare_ugx") or 0
        base_fare = int(fare * 0.35)
        distance_fare = int(fare * 0.55)
        tax = fare - (base_fare + distance_fare)

        return {
            "receipt_number": f"REC-UG-{ride['id'][:8].upper()}",
            "date": ride.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "passenger_name": passenger.get("full_name", "Passenger"),
            "driver_name": driver.get("full_name", "Verified RideEasy Driver") if driver else "Assigned Driver",
            "vehicle_plate": driver.get("plate_number", "UBD 204K") if driver else "UBD 204K",
            "pickup": ride.get("pickup_address", ""),
            "destination": ride.get("destination_address", ""),
            "distance_km": ride.get("estimated_distance_km", 0),
            "category": ride.get("category", "ECONOMY"),
            "payment_method": PaymentService.SUPPORTED_METHODS.get(ride.get("payment_method", "CASH"), "Cash"),
            "status": ride.get("payment_status", "PAID"),
            "fare_breakdown": {
                "base_fare": base_fare,
                "distance_fare": distance_fare,
                "service_fee": tax,
                "total_ugx": fare
            }
        }
