import math
import time
from urllib.parse import quote

import requests
from flask import current_app


class LocationIQConfigurationError(Exception):
    pass


class LocationIQRequestError(Exception):
    def __init__(self, message, provider_code=None):
        super().__init__(message)
        self.provider_code = provider_code


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
    def _get_json(url, params, label="request"):
        # LocationIQ's free plan allows ~2 requests/second. A route needs three calls
        # (geocode, geocode, directions), so retry briefly when rate limited (HTTP 429).
        last_error = None
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=(3.05, 10))
                if response.status_code == 429 and attempt < 2:
                    time.sleep(1.1)
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as error:
                last_error = error
                status = getattr(getattr(error, "response", None), "status_code", None)
                # Log the step, status and provider error text; never log the URL or key.
                body = ""
                if getattr(error, "response", None) is not None:
                    body = (error.response.text or "")[:200].replace(params.get("key", "\0"), "***")
                current_app.logger.warning(
                    "LocationIQ %s failed (%s, HTTP status %s): %s",
                    label, type(error).__name__, status, body,
                )
                provider_code = None
                if getattr(error, "response", None) is not None:
                    try:
                        payload = error.response.json()
                        provider_code = payload.get("code") or payload.get("error")
                    except (ValueError, AttributeError):
                        provider_code = None
                raise LocationIQRequestError(
                    "The location service is temporarily unavailable.", provider_code=provider_code
                ) from error
        raise LocationIQRequestError("The location service is temporarily unavailable.") from last_error

    @classmethod
    def _search(cls, address, country_codes=None):
        params = {
            "key": cls._api_key(),
            "q": address,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "accept-language": "en",
        }
        if country_codes:
            params["countrycodes"] = country_codes
        try:
            results = cls._get_json(f"{cls.BASE_URL}/search", params, label=f"geocode '{address[:40]}'")
        except LocationIQRequestError as error:
            # LocationIQ answers 404 "Unable to geocode" when nothing matches.
            if error.provider_code and "unable to geocode" in str(error.provider_code).lower():
                return []
            raise
        return results

    @classmethod
    def geocode(cls, address):
        # Prefer results inside the countries RideEasy serves (default: Uganda) so a
        # place name is not matched to a same-named place on another continent.
        country_codes = (current_app.config.get("LOCATIONIQ_COUNTRY_CODES") or "ug").strip()
        results = cls._search(address, country_codes)
        if (not isinstance(results, list) or not results) and country_codes:
            results = cls._search(address)
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
        result = None
        for overview in ("full", "simplified"):
            try:
                result = cls._get_json(
                    f"{cls.BASE_URL}/directions/driving/{encoded_coordinates}",
                    {
                        "key": api_key,
                        "overview": overview,
                        "geometries": "geojson",
                        "alternatives": "false",
                    },
                    label=f"directions ({overview})",
                )
                break
            except LocationIQRequestError as error:
                if error.provider_code == "TooBig" and overview == "full":
                    continue
                if error.provider_code in ("TooBig", "NoRoute", "NoSegment"):
                    raise LocationIQNoResultsError(
                        "No driving route could be found between these places. They may be too far apart "
                        "or in different countries. Add the town or country to each place name and try again."
                    ) from error
                raise
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