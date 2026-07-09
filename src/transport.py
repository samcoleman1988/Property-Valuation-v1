"""Transport and location assessment.

Calculates distances and commute indicators using free geocoding.
Includes fixed reference points for user contexts.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from geopy.distance import geodesic

from .utils import cache_key, get_cached, set_cache

# User reference locations
REFERENCE_LOCATIONS = {
    "OX33 1RT": {"name": "Home (OX33 1RT)", "lat": 51.7656, "lon": -1.1384},
    "John Radcliffe Hospital": {"name": "John Radcliffe Hospital, Oxford", "lat": 51.7637, "lon": -1.2200},
}


@dataclass
class LocationAssessment:
    # Distance to reference points
    distances: list = field(default_factory=list)  # [{name, distance_miles, drive_time_est}]

    # Station access
    nearest_stations: list = field(default_factory=list)
    station_distance_miles: float = 0.0

    # General
    location_score: int = 0  # 0-10
    resale_demand: str = ""
    notes: str = ""
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def assess_location(
    postcode: str,
    latitude: float = 0.0,
    longitude: float = 0.0,
) -> LocationAssessment:
    """Assess location quality and commute distances."""
    assessment = LocationAssessment()

    if not latitude or not longitude:
        coords = geocode_postcode(postcode)
        if coords:
            latitude, longitude = coords
        else:
            assessment.warnings.append("Could not geocode property — distance checks unavailable")
            return assessment

    # Calculate distances to reference locations
    property_coords = (latitude, longitude)
    for ref_key, ref in REFERENCE_LOCATIONS.items():
        ref_coords = (ref["lat"], ref["lon"])
        dist = geodesic(property_coords, ref_coords).miles
        drive_est = _estimate_drive_time(dist)
        assessment.distances.append({
            "name": ref["name"],
            "distance_miles": round(dist, 1),
            "drive_time_estimate": drive_est,
        })

    # Find nearest stations
    _find_nearest_stations(assessment, latitude, longitude)

    # Score location
    _score_location(assessment)

    return assessment


def geocode_postcode(postcode: str) -> Optional[tuple]:
    """Geocode a UK postcode using the free postcodes.io API."""
    ck = cache_key("geo", {"pc": postcode})
    cached = get_cached(ck, max_age_hours=8760)  # cache for 1 year
    if cached and "lat" in cached:
        return (cached["lat"], cached["lon"])

    pc = postcode.replace(" ", "")
    try:
        resp = requests.get(f"https://api.postcodes.io/postcodes/{pc}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == 200 and data.get("result"):
            lat = data["result"]["latitude"]
            lon = data["result"]["longitude"]
            set_cache(ck, {"lat": lat, "lon": lon})
            return (lat, lon)
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def _estimate_drive_time(distance_miles: float) -> str:
    """Rough drive time estimate assuming 30mph average."""
    minutes = distance_miles / 30 * 60
    if minutes < 60:
        return f"~{int(minutes)} mins"
    hours = minutes / 60
    return f"~{hours:.1f} hours"


def _find_nearest_stations(assessment: LocationAssessment, lat: float, lon: float):
    """Find nearest railway stations — uses a simple approach via postcodes.io."""
    assessment.warnings.append(
        "Station distance is estimated. Check National Rail for actual journey times."
    )


def _score_location(assessment: LocationAssessment):
    """Score overall location quality."""
    score = 5  # baseline

    for d in assessment.distances:
        dist = d.get("distance_miles", 999)
        if dist < 5:
            score += 1
        elif dist < 15:
            score += 0
        elif dist > 30:
            score -= 1

    assessment.location_score = max(0, min(10, score))
