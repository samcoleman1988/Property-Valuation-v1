"""Planning data access and extension potential assessment.

Uses the Planning Data API (https://www.planning.data.gov.uk/) where available,
with fallback constraint checks.
"""

import requests
from typing import Optional
from dataclasses import dataclass, field, asdict

from .utils import cache_key, get_cached, set_cache

PLANNING_API_BASE = "https://www.planning.data.gov.uk/api/v1"


@dataclass
class PlanningAssessment:
    """Planning and extension potential assessment for a property."""
    # Constraints
    conservation_area: bool = False
    listed_building: bool = False
    listed_grade: str = ""
    article_4: bool = False
    green_belt: bool = False
    aonb: bool = False
    flood_zone: str = ""
    tree_preservation_orders: bool = False
    constraints_summary: list = field(default_factory=list)

    # Extension potential scores (0-10)
    rear_extension_score: int = 0
    side_extension_score: int = 0
    loft_conversion_score: int = 0
    garage_conversion_score: int = 0
    outbuilding_score: int = 0

    # Planning evidence
    nearby_approvals: list = field(default_factory=list)
    nearby_refusals: list = field(default_factory=list)

    # Summary
    overall_planning_confidence: str = "Unknown"  # Low / Medium / High
    extension_upside_estimate: float = 0.0
    build_cost_low: float = 0.0
    build_cost_high: float = 0.0
    post_works_value_low: float = 0.0
    post_works_value_high: float = 0.0
    net_opportunity_low: float = 0.0
    net_opportunity_high: float = 0.0
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def assess_planning(
    postcode: str,
    property_type: str = "",
    bedrooms: int = 0,
    current_value: float = 0.0,
    latitude: float = 0.0,
    longitude: float = 0.0,
) -> PlanningAssessment:
    """Run planning and extension potential assessment."""
    assessment = PlanningAssessment()

    # Check constraints
    _check_constraints(assessment, postcode, latitude, longitude)

    # Score extension potential based on property type and constraints
    _score_extensions(assessment, property_type, bedrooms)

    # Search nearby planning applications
    _search_nearby_planning(assessment, postcode, latitude, longitude)

    # Calculate financial upside
    if current_value > 0:
        _calculate_extension_financials(assessment, property_type, bedrooms, current_value)

    # Determine confidence
    _set_confidence(assessment)

    return assessment


def _check_constraints(
    assessment: PlanningAssessment,
    postcode: str,
    lat: float,
    lon: float,
):
    """Check planning constraints using Planning Data API."""
    if not lat or not lon:
        assessment.warnings.append("No coordinates available — constraint check limited")
        return

    try:
        # Check conservation areas
        resp = requests.get(
            f"{PLANNING_API_BASE}/dataset/conservation-area/point",
            params={"lat": lat, "lng": lon},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0:
                assessment.conservation_area = True
                assessment.constraints_summary.append("Conservation Area")
    except Exception:
        pass

    try:
        resp = requests.get(
            f"{PLANNING_API_BASE}/dataset/listed-building-outline/point",
            params={"lat": lat, "lng": lon},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0:
                assessment.listed_building = True
                assessment.constraints_summary.append("Listed Building")
    except Exception:
        pass

    try:
        resp = requests.get(
            f"{PLANNING_API_BASE}/dataset/green-belt/point",
            params={"lat": lat, "lng": lon},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0:
                assessment.green_belt = True
                assessment.constraints_summary.append("Green Belt")
    except Exception:
        pass

    try:
        resp = requests.get(
            f"{PLANNING_API_BASE}/dataset/area-of-outstanding-natural-beauty/point",
            params={"lat": lat, "lng": lon},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0:
                assessment.aonb = True
                assessment.constraints_summary.append("AONB")
    except Exception:
        pass

    try:
        resp = requests.get(
            f"{PLANNING_API_BASE}/dataset/article-4-direction-area/point",
            params={"lat": lat, "lng": lon},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0:
                assessment.article_4 = True
                assessment.constraints_summary.append("Article 4 Direction")
    except Exception:
        pass

    try:
        resp = requests.get(
            f"{PLANNING_API_BASE}/dataset/flood-risk-zone/point",
            params={"lat": lat, "lng": lon},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("count", 0) > 0:
                items = data.get("entities", data.get("results", []))
                if items:
                    zone = str(items[0].get("flood-risk-level", items[0].get("name", "")))
                    assessment.flood_zone = zone
                    assessment.constraints_summary.append(f"Flood Zone: {zone}")
    except Exception:
        pass

    if not assessment.constraints_summary:
        assessment.constraints_summary.append("No major constraints identified (data may be incomplete)")


def _score_extensions(
    assessment: PlanningAssessment,
    property_type: str,
    bedrooms: int,
):
    """Score extension potential based on property type and constraints."""
    pt = property_type.lower() if property_type else ""

    is_house = any(t in pt for t in ("detached", "semi", "terrace", "bungalow", "cottage", "house"))
    is_flat = any(t in pt for t in ("flat", "apartment", "maisonette"))
    is_detached = "detached" in pt and "semi" not in pt
    is_semi = "semi" in pt
    is_terrace = any(t in pt for t in ("terrace", "mid terrace", "end of terrace"))
    is_bungalow = "bungalow" in pt

    constraint_penalty = 0
    if assessment.listed_building:
        constraint_penalty = 8
    elif assessment.conservation_area:
        constraint_penalty = 3
    elif assessment.article_4:
        constraint_penalty = 2

    # Rear extension
    if is_house:
        base = 7 if is_detached else 6 if is_semi else 5
        assessment.rear_extension_score = max(0, base - constraint_penalty)
    elif is_flat:
        assessment.rear_extension_score = 0

    # Side extension
    if is_detached:
        assessment.side_extension_score = max(0, 7 - constraint_penalty)
    elif is_semi:
        assessment.side_extension_score = max(0, 5 - constraint_penalty)
    else:
        assessment.side_extension_score = 0

    # Loft conversion
    if is_house and not is_bungalow:
        assessment.loft_conversion_score = max(0, 6 - constraint_penalty)
    elif is_bungalow:
        assessment.loft_conversion_score = max(0, 7 - constraint_penalty)
    else:
        assessment.loft_conversion_score = 0

    # Garage conversion
    if is_house:
        assessment.garage_conversion_score = max(0, 5 - constraint_penalty)

    # Outbuilding / garden office
    if is_house:
        assessment.outbuilding_score = max(0, 5 - constraint_penalty)


def _search_nearby_planning(
    assessment: PlanningAssessment,
    postcode: str,
    lat: float,
    lon: float,
):
    """Search for nearby planning applications — stub for v1.

    Full implementation would query local authority planning portals or
    the national planning API when it becomes fully queryable by location.
    """
    assessment.warnings.append(
        "Nearby planning application search is limited in v1. "
        "Check local authority planning portal manually for best evidence."
    )


def _calculate_extension_financials(
    assessment: PlanningAssessment,
    property_type: str,
    bedrooms: int,
    current_value: float,
):
    """Estimate build costs and post-works value uplift."""
    pt = property_type.lower() if property_type else ""

    # Build cost per sqm ranges (2024 UK averages)
    cost_per_sqm_low = 1500   # basic spec
    cost_per_sqm_high = 2500  # good spec

    best_score = max(
        assessment.rear_extension_score,
        assessment.side_extension_score,
        assessment.loft_conversion_score,
    )

    if best_score == 0:
        return

    # Estimate extension size based on property type
    if "detached" in pt and "semi" not in pt:
        est_sqm_low, est_sqm_high = 20, 40
    elif "semi" in pt:
        est_sqm_low, est_sqm_high = 15, 30
    elif "terrace" in pt:
        est_sqm_low, est_sqm_high = 10, 20
    elif "bungalow" in pt:
        est_sqm_low, est_sqm_high = 15, 35
    else:
        est_sqm_low, est_sqm_high = 10, 25

    assessment.build_cost_low = est_sqm_low * cost_per_sqm_low
    assessment.build_cost_high = est_sqm_high * cost_per_sqm_high

    # Post-works uplift: typically 10-25% of current value for a good extension
    uplift_pct_low = 0.08 * (best_score / 7)
    uplift_pct_high = 0.25 * (best_score / 7)

    assessment.post_works_value_low = current_value * (1 + uplift_pct_low)
    assessment.post_works_value_high = current_value * (1 + uplift_pct_high)

    assessment.extension_upside_estimate = (
        assessment.post_works_value_high - current_value - assessment.build_cost_high
    )

    # Net opportunity (upside minus costs and risk buffer)
    fees_and_contingency = 0.15  # 15% for professional fees, contingency
    assessment.net_opportunity_low = (
        assessment.post_works_value_low - current_value
        - assessment.build_cost_high * (1 + fees_and_contingency)
    )
    assessment.net_opportunity_high = (
        assessment.post_works_value_high - current_value
        - assessment.build_cost_low * (1 + fees_and_contingency)
    )


def _set_confidence(assessment: PlanningAssessment):
    """Set overall planning confidence level."""
    if assessment.listed_building:
        assessment.overall_planning_confidence = "Low"
    elif assessment.conservation_area or assessment.article_4:
        assessment.overall_planning_confidence = "Medium"
    elif assessment.green_belt:
        assessment.overall_planning_confidence = "Low"
    elif len(assessment.nearby_approvals) >= 3:
        assessment.overall_planning_confidence = "High"
    elif assessment.constraints_summary == ["No major constraints identified (data may be incomplete)"]:
        assessment.overall_planning_confidence = "Medium"
    else:
        assessment.overall_planning_confidence = "Medium"
