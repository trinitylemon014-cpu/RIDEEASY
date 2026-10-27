"""Small geographic helpers shared by dispatch, ETA and live tracking."""
import math

EARTH_RADIUS_KM = 6371.0088


def valid_point(lat, lng) -> bool:
    """True for finite, in-range coordinates (and not the meaningless 0,0 default)."""
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return False
    return not (lat == 0.0 and lng == 0.0)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in kilometres."""
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def eta_minutes(distance_km: float, speed_kmh: float = 25.0, road_factor: float = 1.3) -> float:
    """
    Rough travel time. Straight-line distance understates real roads, so it is
    multiplied by a road factor (default 1.3) before dividing by the average speed.
    """
    speed = max(5.0, float(speed_kmh))
    return max(1.0, (float(distance_km) * road_factor) / speed * 60.0)
