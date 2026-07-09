"""Extension potential wrapper — delegates to planning module.

This module provides a simplified interface for the extension/planning
assessment, combining planning constraints with build-cost estimates.
"""

from .planning import assess_planning, PlanningAssessment


BUILD_COSTS_PER_SQM = {
    "single_storey_rear": {"low": 1400, "mid": 1800, "high": 2400},
    "two_storey_rear": {"low": 1200, "mid": 1600, "high": 2200},
    "side_extension": {"low": 1300, "mid": 1700, "high": 2300},
    "loft_conversion": {"low": 1200, "mid": 1600, "high": 2200},
    "dormer": {"low": 1500, "mid": 2000, "high": 2800},
    "garage_conversion": {"low": 800, "mid": 1200, "high": 1600},
    "outbuilding": {"low": 800, "mid": 1200, "high": 1800},
}

PROFESSIONAL_FEES_PCT = 0.12
CONTINGENCY_PCT = 0.10


def assess_extension_potential(
    postcode: str,
    property_type: str = "",
    bedrooms: int = 0,
    current_value: float = 0.0,
    latitude: float = 0.0,
    longitude: float = 0.0,
) -> dict:
    """Assess extension potential and return a summary dict for the report."""
    pa = assess_planning(
        postcode=postcode,
        property_type=property_type,
        bedrooms=bedrooms,
        current_value=current_value,
        latitude=latitude,
        longitude=longitude,
    )

    summary = pa.to_dict()

    # Add detailed build cost breakdown
    summary["build_cost_breakdown"] = _build_cost_breakdown(pa, property_type)

    # Add extension recommendations
    summary["recommendations"] = _recommendations(pa, property_type)

    return summary


def _build_cost_breakdown(pa: PlanningAssessment, property_type: str) -> list:
    """Generate itemised build cost estimates for viable extensions."""
    items = []
    pt = property_type.lower() if property_type else ""

    if pa.rear_extension_score >= 4:
        sqm = 15 if "terrace" in pt else 25 if "semi" in pt else 30
        costs = BUILD_COSTS_PER_SQM["single_storey_rear"]
        items.append({
            "type": "Single-storey rear extension",
            "estimated_sqm": sqm,
            "cost_low": _total_cost(sqm, costs["low"]),
            "cost_high": _total_cost(sqm, costs["high"]),
            "score": pa.rear_extension_score,
        })

    if pa.side_extension_score >= 4:
        sqm = 15 if "semi" in pt else 20
        costs = BUILD_COSTS_PER_SQM["side_extension"]
        items.append({
            "type": "Side extension",
            "estimated_sqm": sqm,
            "cost_low": _total_cost(sqm, costs["low"]),
            "cost_high": _total_cost(sqm, costs["high"]),
            "score": pa.side_extension_score,
        })

    if pa.loft_conversion_score >= 4:
        sqm = 20 if "bungalow" in pt else 15
        costs = BUILD_COSTS_PER_SQM["loft_conversion"]
        items.append({
            "type": "Loft conversion",
            "estimated_sqm": sqm,
            "cost_low": _total_cost(sqm, costs["low"]),
            "cost_high": _total_cost(sqm, costs["high"]),
            "score": pa.loft_conversion_score,
        })

    if pa.garage_conversion_score >= 4:
        sqm = 15
        costs = BUILD_COSTS_PER_SQM["garage_conversion"]
        items.append({
            "type": "Garage conversion",
            "estimated_sqm": sqm,
            "cost_low": _total_cost(sqm, costs["low"]),
            "cost_high": _total_cost(sqm, costs["high"]),
            "score": pa.garage_conversion_score,
        })

    if pa.outbuilding_score >= 4:
        sqm = 12
        costs = BUILD_COSTS_PER_SQM["outbuilding"]
        items.append({
            "type": "Garden room / outbuilding",
            "estimated_sqm": sqm,
            "cost_low": _total_cost(sqm, costs["low"]),
            "cost_high": _total_cost(sqm, costs["high"]),
            "score": pa.outbuilding_score,
        })

    return items


def _total_cost(sqm: int, cost_per_sqm: int) -> float:
    base = sqm * cost_per_sqm
    return round(base * (1 + PROFESSIONAL_FEES_PCT + CONTINGENCY_PCT), -2)


def _recommendations(pa: PlanningAssessment, property_type: str) -> list:
    recs = []

    if pa.listed_building:
        recs.append("Listed building — all external and most internal works require Listed Building Consent. Budget for specialist architect.")
    if pa.conservation_area:
        recs.append("Conservation area — permitted development rights restricted. Pre-application advice recommended.")
    if pa.article_4:
        recs.append("Article 4 direction in effect — additional planning permissions may be required for normally permitted works.")
    if pa.green_belt:
        recs.append("Green Belt — extensions must not result in disproportionate additions. Very limited scope.")

    best_score = max(
        pa.rear_extension_score,
        pa.side_extension_score,
        pa.loft_conversion_score,
        pa.garage_conversion_score,
        pa.outbuilding_score,
    )

    if best_score >= 6:
        recs.append("Good extension potential — consider pre-application advice to de-risk.")
    elif best_score >= 4:
        recs.append("Moderate extension potential — worth investigating but not guaranteed.")
    elif best_score > 0:
        recs.append("Limited extension potential due to property type or constraints.")
    else:
        recs.append("No extension potential identified.")

    return recs
