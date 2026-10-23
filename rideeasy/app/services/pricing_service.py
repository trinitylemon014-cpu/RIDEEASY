import math
from typing import Dict, List, Optional
from app.repositories.database import get_db

class MapService:
    """Provides geographic distance estimation, landmark lookup, and coordinates in Uganda."""

    # Curated Ugandan transportation hubs and landmarks
    LANDMARKS = [
        {"name": "Entebbe International Airport (EBB)", "lat": 0.0424, "lng": 32.4435, "district": "Entebbe"},
        {"name": "Acacia Mall, Kisementi, Kololo", "lat": 0.3340, "lng": 32.5890, "district": "Kampala"},
        {"name": "Kampala City Centre (Posta Uganda)", "lat": 0.3136, "lng": 32.5811, "district": "Kampala"},
        {"name": "Victoria Towers, Nakasero Road", "lat": 0.3200, "lng": 32.5780, "district": "Kampala"},
        {"name": "Makerere University Main Gate", "lat": 0.3312, "lng": 32.5702, "district": "Kampala"},
        {"name": "Garden City Mall, Yusuf Lule Road", "lat": 0.3195, "lng": 32.5912, "district": "Kampala"},
        {"name": "Lugogo Mall / Shoprite / Game", "lat": 0.3275, "lng": 32.6105, "district": "Kampala"},
        {"name": "Greenhill Academy Kibuli", "lat": 0.3060, "lng": 32.5985, "district": "Kampala"},
        {"name": "Ntinda Complex / Capital Shoppers", "lat": 0.3542, "lng": 32.6120, "district": "Kampala"},
        {"name": "Bunga / Ggaba Beach Landing Site", "lat": 0.2580, "lng": 32.6280, "district": "Kampala"},
        {"name": "Namanve Industrial Park", "lat": 0.3500, "lng": 32.7000, "district": "Mukono"},
        {"name": "Jinja Source of the Nile", "lat": 0.4300, "lng": 33.2000, "district": "Jinja"},
        {"name": "Uganda Wildlife Education Centre (UWEC)", "lat": 0.0570, "lng": 32.4750, "district": "Entebbe"},
    ]

    @staticmethod
    def calculate_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Haversine formula to compute great-circle distance between two GPS coordinates."""
        R = 6371.0  # Earth's radius in kilometers
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c
        # Add road curvature multiplier (avg 1.3x in Ugandan urban road networks)
        return round(distance * 1.3, 1)

    @staticmethod
    def find_coordinates(place_name: str) -> Dict[str, float]:
        """Looks up coordinates for recognized Ugandan landmarks or provides central Kampala fallback."""
        cleaned = place_name.lower().strip()
        for item in MapService.LANDMARKS:
            if item["name"].lower() in cleaned or cleaned in item["name"].lower():
                return {"lat": item["lat"], "lng": item["lng"], "matched_name": item["name"]}
        # Default fallback to Kampala Center
        return {"lat": 0.3136, "lng": 32.5811, "matched_name": place_name}


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
