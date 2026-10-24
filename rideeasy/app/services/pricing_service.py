from typing import Optional
from app.repositories.database import get_db

class PricingService:
    """Calculates official RideEasy fares in Ugandan Shillings (UGX)."""

    @staticmethod
    def calculate_fare(category: str, distance_km: float, duration_minutes: Optional[int] = None) -> int:
        db = get_db()
        config = db.fetchone("SELECT * FROM pricing_configs WHERE category = ?", (category.upper(),))
        if not config:
            # Fallback standard pricing
            defaults = {
                "BODA": {"base": 1500, "km": 700, "min": 100, "min_fare": 2500},
                "ECONOMY": {"base": 3500, "km": 1500, "min": 200, "min_fare": 6000},
                "COMFORT": {"base": 5000, "km": 2200, "min": 300, "min_fare": 9000},
                "PREMIUM": {"base": 8000, "km": 3200, "min": 450, "min_fare": 15000},
                "COASTER": {"base": 80000, "km": 4500, "min": 500, "min_fare": 250000},
                "BUS": {"base": 150000, "km": 7500, "min": 800, "min_fare": 450000},
            }
            c = defaults.get(category.upper(), defaults["ECONOMY"])
            base = c["base"]
            per_km = c["km"]
            per_min = c["min"]
            min_fare = c["min_fare"]
        else:
            base = config["base_fare_ugx"]
            per_km = config["per_km_ugx"]
            per_min = config["per_min_ugx"]
            min_fare = config["min_fare_ugx"]

        if duration_minutes is None:
            # Average urban speed in Kampala: 25 km/h
            duration_minutes = max(5, int((distance_km / 25.0) * 60))

        raw_fare = base + (distance_km * per_km) + (duration_minutes * per_min)
        # Round to nearest 500 UGX
        rounded_fare = int(round(raw_fare / 500.0) * 500)
        return max(min_fare, rounded_fare)
