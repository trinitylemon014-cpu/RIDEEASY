"""Validation and completeness rules for a driver's work profile.

Pure functions only (no Flask, no database) so the rules are easy to test and
reuse. The route in app/routes/driver.py does the reading and writing.
"""
import re
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

# Placeholder written at registration time, before the driver fills in the real value.
PLACEHOLDER = "PENDING"

MIN_DRIVER_AGE = 18
MAX_DRIVER_AGE = 80
MAX_EXPERIENCE_YEARS = 60
# A driver could not have been driving before this age, so experience is capped by it.
EARLIEST_DRIVING_AGE = 16

# Vehicle categories allowed by the vehicles table, with a label and a seat limit.
VEHICLE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "BODA": {"label": "Boda boda (motorcycle)", "max_capacity": 2},
    "ECONOMY": {"label": "Economy car", "max_capacity": 6},
    "COMFORT": {"label": "Comfort car", "max_capacity": 7},
    "PREMIUM": {"label": "Premium car", "max_capacity": 7},
    "COASTER": {"label": "Coaster / minibus", "max_capacity": 33},
    "BUS": {"label": "Bus", "max_capacity": 80},
}

# Uganda national ID number: 14 characters, "CM" (male) or "CF" (female), then 12 letters/digits.
_NIN_RE = re.compile(r"^C[MF][A-Z0-9]{12}$")
_PERMIT_RE = re.compile(r"^[A-Z0-9][A-Z0-9 /\-]{3,18}[A-Z0-9]$")
_PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 ]{3,8}[A-Z0-9]$")
_TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,'/&()\-]*$")


def _clean(value: Any) -> str:
    """Trim, collapse inner whitespace and drop control characters."""
    text = "" if value is None else str(value)
    text = "".join(ch for ch in text if ch == " " or ch.isprintable())
    return re.sub(r"\s+", " ", text).strip()


def is_placeholder(value: Optional[str]) -> bool:
    return value is None or _clean(value) == "" or _clean(value).upper() == PLACEHOLDER


def display_value(value: Optional[str]) -> str:
    """What to show in a form field: nothing for registration placeholders."""
    return "" if is_placeholder(value) else str(value)


def mask_identifier(value: Optional[str], keep_start: int = 2, keep_end: int = 2) -> str:
    """Hide the middle of an ID so it can be shown on screen without exposing it fully."""
    if is_placeholder(value):
        return "Not provided"
    text = str(value)
    if len(text) <= keep_start + keep_end:
        return "•" * len(text)
    return text[:keep_start] + "•" * (len(text) - keep_start - keep_end) + text[-keep_end:]


def age_from_dob(dob: Optional[str], today: Optional[date] = None) -> Optional[int]:
    """Whole years between an ISO date (YYYY-MM-DD) and today, or None if unusable."""
    if not dob:
        return None
    try:
        born = datetime.strptime(str(dob)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def normalise_plate(value: str) -> str:
    return _clean(value).upper()


def validate_profile(
    form: Dict[str, Any], today: Optional[date] = None
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Check the submitted work-profile form.

    Returns (clean_values, errors). errors maps a field name to one message, and
    clean_values is only safe to save when errors is empty.
    """
    today = today or date.today()
    errors: Dict[str, str] = {}
    clean: Dict[str, Any] = {}

    # --- Date of birth / age ---------------------------------------------------
    dob_raw = _clean(form.get("date_of_birth"))
    age = None
    if not dob_raw:
        errors["date_of_birth"] = "Enter your date of birth."
    else:
        try:
            datetime.strptime(dob_raw, "%Y-%m-%d")
            age = age_from_dob(dob_raw, today)
        except ValueError:
            errors["date_of_birth"] = "Enter a valid date of birth."
        else:
            if age is None or age < MIN_DRIVER_AGE:
                errors["date_of_birth"] = f"Drivers must be at least {MIN_DRIVER_AGE} years old."
            elif age > MAX_DRIVER_AGE:
                errors["date_of_birth"] = f"Please check your date of birth (age {age})."
    clean["date_of_birth"] = dob_raw

    # --- Years of experience ---------------------------------------------------
    years_raw = _clean(form.get("years_experience"))
    years = None
    if years_raw == "":
        errors["years_experience"] = "Enter your years of driving experience (0 if new)."
    elif not years_raw.isdigit():
        errors["years_experience"] = "Use a whole number, for example 3."
    else:
        years = int(years_raw)
        if years > MAX_EXPERIENCE_YEARS:
            errors["years_experience"] = f"Experience cannot be more than {MAX_EXPERIENCE_YEARS} years."
        elif age is not None and years > max(0, age - EARLIEST_DRIVING_AGE):
            errors["years_experience"] = "Experience is more than your age allows. Please check it."
    clean["years_experience"] = years

    # --- Driving permit --------------------------------------------------------
    permit = _clean(form.get("license_number")).upper()
    if not permit or permit == PLACEHOLDER:
        errors["license_number"] = "Enter your driving permit number."
    elif not _PERMIT_RE.match(permit):
        errors["license_number"] = "Permit number should be 5 to 20 letters or digits."
    clean["license_number"] = permit

    # --- National ID number (NIN) ---------------------------------------------
    nin = re.sub(r"\s+", "", _clean(form.get("national_id_nin"))).upper()
    if not nin or nin == PLACEHOLDER:
        errors["national_id_nin"] = "Enter your National ID number (NIN)."
    elif not _NIN_RE.match(nin):
        errors["national_id_nin"] = "A NIN has 14 characters and starts with CM or CF."
    clean["national_id_nin"] = nin

    # --- Vehicle ---------------------------------------------------------------
    category = _clean(form.get("category")).upper()
    if category not in VEHICLE_CATEGORIES:
        errors["category"] = "Choose your vehicle type."
    clean["category"] = category

    for field, label, low, high in (
        ("make", "make", 2, 40),
        ("model", "model", 1, 40),
        ("color", "colour", 3, 30),
    ):
        text = _clean(form.get(field))
        if len(text) < low:
            errors[field] = f"Enter the vehicle {label}."
        elif len(text) > high or not _TEXT_RE.match(text):
            errors[field] = f"The vehicle {label} contains characters we cannot accept."
        clean[field] = text

    year_raw = _clean(form.get("year"))
    year = None
    if not year_raw.isdigit():
        errors["year"] = "Enter the year the vehicle was made, for example 2016."
    else:
        year = int(year_raw)
        if year < 1980 or year > today.year + 1:
            errors["year"] = f"Enter a year between 1980 and {today.year + 1}."
    clean["year"] = year

    plate = normalise_plate(form.get("plate_number", ""))
    if not plate:
        errors["plate_number"] = "Enter your number plate."
    elif not _PLATE_RE.match(plate) or not re.search(r"\d", plate) or not re.search(r"[A-Z]", plate):
        errors["plate_number"] = "Enter a valid number plate, for example UBA 123X."
    clean["plate_number"] = plate

    capacity_raw = _clean(form.get("capacity"))
    capacity = None
    if not capacity_raw.isdigit() or int(capacity_raw) < 1:
        errors["capacity"] = "Enter how many passengers the vehicle carries."
    else:
        capacity = int(capacity_raw)
        info = VEHICLE_CATEGORIES.get(category)
        limit = info["max_capacity"] if info else 80
        if capacity > limit:
            errors["capacity"] = (
                f"A {info['label'].lower()} carries at most {limit} passengers."
                if info else "Enter a realistic number of seats."
            )
    clean["capacity"] = capacity

    return clean, errors


# Fields that identify the driver or the vehicle. Changing one of these on an approved
# profile sends it back for admin review.
SENSITIVE_FIELDS = ("license_number", "national_id_nin", "plate_number", "date_of_birth")


def sensitive_fields_changed(profile: Optional[Dict[str, Any]], vehicle: Optional[Dict[str, Any]],
                             clean: Dict[str, Any]) -> bool:
    old = {
        "license_number": (profile or {}).get("license_number"),
        "national_id_nin": (profile or {}).get("national_id_nin"),
        "date_of_birth": (profile or {}).get("date_of_birth"),
        "plate_number": (vehicle or {}).get("plate_number"),
    }
    for field in SENSITIVE_FIELDS:
        before = "" if is_placeholder(old[field]) else str(old[field]).strip().upper()
        after = str(clean.get(field) or "").strip().upper()
        # Filling in something that was missing is not a change; replacing a value is.
        if before and before != after:
            return True
    return False


def completeness(profile: Optional[Dict[str, Any]], vehicle: Optional[Dict[str, Any]],
                 photo_count: int = 0) -> Dict[str, Any]:
    """Which parts of the work profile are done, for the dashboard prompt and progress bar."""
    profile = profile or {}
    vehicle = vehicle or {}
    steps = [
        ("Date of birth", bool(profile.get("date_of_birth"))),
        ("Driving permit number", not is_placeholder(profile.get("license_number"))),
        ("National ID number (NIN)", not is_placeholder(profile.get("national_id_nin"))),
        ("Years of experience", profile.get("years_experience") is not None and bool(profile.get("date_of_birth"))),
        ("Vehicle details", bool(vehicle.get("plate_number"))),
        ("Front car photo", photo_count >= 1),
        ("Side and back car photos", photo_count >= 3),
    ]
    done = sum(1 for _, ok in steps if ok)
    return {
        "steps": [{"label": label, "done": ok} for label, ok in steps],
        "done": done,
        "total": len(steps),
        "percent": round(done * 100 / len(steps)),
        "complete": done == len(steps),
        "missing": [label for label, ok in steps if not ok],
    }
