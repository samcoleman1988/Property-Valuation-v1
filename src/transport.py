"""Transport and location assessment.

Calculates distances and commute indicators using free geocoding.

The report is generic by default — it does not embed any individual's
personal locations. Distance-to-destination checks only run if the
caller explicitly supplies `personal_destinations` (see app.py's
"Personal Destinations" sidebar setting, off by default).

There is no generic amenity data source wired up (no free API for
schools/supermarkets/transport-links is integrated), and none is
fabricated to fill the gap. Without personal destinations, this module
does not produce a location_score at all — `assessed` stays False and
`location_score` stays None, so a caller can never mistake "nothing was
assessed" for "assessed as average" (a numeric placeholder like 5/10
would look exactly like a real, if mediocre, score).
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from geopy.distance import geodesic

from .utils import cache_key, get_cached, set_cache


@dataclass
class LocationAssessment:
    # Distance to any personally-configured destinations (opt-in only —
    # empty unless the user has added destinations in Settings). This is
    # personal-convenience scoring, not a generic investment metric.
    distances: list = field(default_factory=list)  # [{name, distance_miles, drive_time_est}]

    # Station access
    nearest_stations: list = field(default_factory=list)
    station_distance_miles: float = 0.0

    # General — assessed is True only when personal destinations were
    # actually scored. location_score is None (never a fabricated
    # number) whenever assessed is False.
    assessed: bool = False
    location_score: Optional[int] = None  # 0-10, only meaningful when assessed
    resale_demand: str = ""
    notes: str = ""
    warnings: list = field(default_factory=list)
    data_gaps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def assess_location(
    postcode: str,
    latitude: float = 0.0,
    longitude: float = 0.0,
    personal_destinations: Optional[list] = None,
) -> LocationAssessment:
    """Assess location — distances to any user-configured destinations,
    plus a neutral placeholder score when none are configured.

    personal_destinations: optional list of {"name": str, "postcode": str}
    dicts. None/empty by default — the report stays generic unless the
    user has explicitly added destinations (Settings sidebar, Personal
    Purchase / Both modes only).
    """
    assessment = LocationAssessment()

    if not latitude or not longitude:
        coords = geocode_postcode(postcode)
        if coords:
            latitude, longitude = coords
        else:
            assessment.warnings.append("Could not geocode property — distance checks unavailable")
            return assessment

    # Calculate distances to any personally-configured destinations
    property_coords = (latitude, longitude)
    for dest in (personal_destinations or []):
        dest_coords = None
        if dest.get("lat") and dest.get("lon"):
            dest_coords = (dest["lat"], dest["lon"])
        elif dest.get("postcode"):
            dest_coords = geocode_postcode(dest["postcode"])
        if not dest_coords:
            assessment.warnings.append(f"Could not geocode destination '{dest.get('name', '?')}'")
            continue
        dist = geodesic(property_coords, dest_coords).miles
        drive_est = _estimate_drive_time(dist)
        assessment.distances.append({
            "name": dest.get("name") or dest.get("postcode", "Destination"),
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


_GEOCODE_BATCH_MAX_WORKERS = 5


def geocode_postcodes_batch(
    postcodes, max_workers: int = _GEOCODE_BATCH_MAX_WORKERS
) -> dict:
    """Geocode many postcodes efficiently: dedupe, read the disk cache for
    every postcode first (cheap, synchronous, no network), then fetch only
    genuine cache misses concurrently via a conservative thread pool.

    Each postcode still resolves through geocode_postcode() unchanged —
    same cache key, same 1-year TTL, same timeout and error handling — so
    every returned coordinate is identical to what a sequential call to
    geocode_postcode() would have produced. This function only changes how
    many network round-trips a cold cache costs, not what gets geocoded or
    what the result is. See ROADMAP.md (geocoding dedupe/batching,
    identified as a measured operational bottleneck, not a theoretical one).

    Returns {postcode: (lat, lon) | None}. Postcodes that are falsy/empty
    are skipped entirely (never appear in the result).
    """
    unique = sorted({pc for pc in postcodes if pc})
    results: dict = {}
    misses = []

    for pc in unique:
        ck = cache_key("geo", {"pc": pc})
        cached = get_cached(ck, max_age_hours=8760)
        if cached and "lat" in cached:
            results[pc] = (cached["lat"], cached["lon"])
        else:
            misses.append(pc)

    if misses:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pc = {executor.submit(geocode_postcode, pc): pc for pc in misses}
            for future in future_to_pc:
                pc = future_to_pc[future]
                try:
                    results[pc] = future.result()
                except Exception:
                    results[pc] = None

    return results


def _estimate_drive_time(distance_miles: float) -> str:
    """Rough drive time estimate assuming 30mph average."""
    minutes = distance_miles / 30 * 60
    if minutes < 60:
        return f"~{int(minutes)} mins"
    hours = minutes / 60
    return f"~{hours:.1f} hours"


def _find_nearest_stations(assessment: LocationAssessment, lat: float, lon: float):
    """Nearest-station lookup is not yet implemented — no free station
    dataset is wired up. Flagged as a data gap rather than a fabricated
    estimate; see README Known Limitations.
    """
    assessment.data_gaps.append(
        "Nearest railway station distance is not calculated automatically — "
        "check National Rail or a map service directly."
    )


def _score_location(assessment: LocationAssessment):
    """Score location quality against personally-configured destinations.

    Without them, there is no generic amenity data source wired up (no
    free API for schools, supermarkets, or transport links is
    integrated) — assessed stays False and location_score stays None.
    No placeholder number is produced; see the module docstring for why.
    """
    if not assessment.distances:
        assessment.assessed = False
        assessment.location_score = None
        assessment.data_gaps.append(
            "Generic location scoring is not currently available. Add personal "
            "destinations in Personal Purchase mode if commute/access scoring "
            "is required."
        )
        return

    assessment.assessed = True
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
