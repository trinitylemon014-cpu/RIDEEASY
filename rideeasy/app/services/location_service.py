import math
from urllib.parse import quote

import requests
from flask import current_app


class LocationIQConfigurationError(Exception):
    pass


class LocationIQRequestError(Exception):
    pass


class LocationIQNoResultsError(Exception):
    pass


class LocationService:
    BASE_URL = "https://us1.locationiq.com/v1"

    @staticmethod
    def _api_key():
        api_key = current_app.config.get("LOCATIONIQ_API_KEY", "").strip()
        if not api_key:
            raise LocationIQConfigurationError("LocationIQ is not configured.")
        return api_key

    @staticmethod
    def _get_json(url, params):
        try:
            response = requests.get(url, params=params, timeout=(3.05, 10))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            current_app.logger.warning("LocationIQ request failed (%s).", type(error).__name__)
            raise LocationIQRequestError("The location service is temporarily unavailable.") from error

    @classmethod
    def geocode(cls, address):
        results = cls._get_json(
            f"{cls.BASE_URL}/search",
            {
                "key": cls._api_key(),
                "q": address,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "en",
            },
        )
        if not isinstance(results, list) or not results:
            raise LocationIQNoResultsError(f"No location found for “{address}”.")

        result = results[0]
        try:
            lat = float(result["lat"])
            lng = float(result["lon"])
        except (KeyError, TypeError, ValueError) as error:
            current_app.logger.warning("LocationIQ returned an invalid geocoding result.")
            raise LocationIQRequestError("The location service returned an invalid result.") from error
        if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise LocationIQRequestError("The location service returned invalid coordinates.")

        return {
            "label": result.get("display_name") or address,
            "lat": lat,
            "lng": lng,
        }

    @classmethod
    def get_route(cls, start, destination):
        api_key = cls._api_key()
        origin = cls.geocode(start)
        target = cls.geocode(destination)
        coordinates = f"{origin['lng']},{origin['lat']};{target['lng']},{target['lat']}"
        encoded_coordinates = quote(coordinates, safe=";,.-")
        result = cls._get_json(
            f"{cls.BASE_URL}/directions/driving/{encoded_coordinates}",
            {
                "key": api_key,
                "overview": "full",
                "geometries": "geojson",
                "alternatives": "false",
            },
        )
        try:
            route = result["routes"][0]
            geometry = route["geometry"]
            distance_km = float(route["distance"]) / 1000
            duration_minutes = float(route["duration"]) / 60
            route_coords = geometry["coordinates"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            current_app.logger.warning("LocationIQ returned an invalid driving route.")
            raise LocationIQRequestError("A driving route could not be calculated.") from error

        valid_geometry = (
            isinstance(route_coords, list)
            and 2 <= len(route_coords) <= 20000
            and all(
                isinstance(point, list)
                and len(point) >= 2
                and isinstance(point[0], (int, float))
                and isinstance(point[1], (int, float))
                and math.isfinite(point[0])
                and math.isfinite(point[1])
                and -180 <= point[0] <= 180
                and -90 <= point[1] <= 90
                for point in route_coords
            )
        )
        if (
            not math.isfinite(distance_km)
            or distance_km <= 0
            or not math.isfinite(duration_minutes)
            or duration_minutes < 0
            or not valid_geometry
            or geometry.get("type") != "LineString"
        ):
            raise LocationIQRequestError("The location service returned an invalid driving route.")

        return {
            "start": origin,
            "destination": target,
            "distance_km": round(distance_km, 1),
            "duration_minutes": round(duration_minutes),
            "geometry": geometry,
        }
