"""Investment scorecard with 8 explained dimensions.

Replaces scoring.py. Each dimension has a numeric score, label,
explanation, and key drivers. No opaque numbers.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .config import get_config
from .valuation_engine import ValuationResult
from .recommendation import Recommendation
from .utils import format_currency


@dataclass
class DimensionScore:
    """A single scorecard dimension."""
    name: str = ""
    score: int = 0          # 0-10
    weight: float = 0.0     # from config
    weighted_score: float = 0.0
    label: str = ""          # e.g. "Strong", "Weak"
    explanation: str = ""
    key_drivers: List[str] = field(default_factory=list)


@dataclass
class InvestmentScorecard:
    """Full investment scorecard with 8 dimensions."""
    # Dimensions
    fair_value: DimensionScore = field(default_factory=lambda: DimensionScore(name="Fair Value"))
    negotiation_opportunity: DimensionScore = field(default_factory=lambda: DimensionScore(name="Negotiation Opportunity"))
    development_opportunity: DimensionScore = field(default_factory=lambda: DimensionScore(name="Development Opportunity"))
    planning_confidence: DimensionScore = field(default_factory=lambda: DimensionScore(name="Planning Confidence"))
    rental_potential: DimensionScore = field(default_factory=lambda: DimensionScore(name="Rental Potential"))
    resale_potential: DimensionScore = field(default_factory=lambda: DimensionScore(name="Resale Potential"))
    location_quality: DimensionScore = field(default_factory=lambda: DimensionScore(name="Location Quality"))
    investment_risk: DimensionScore = field(default_factory=lambda: DimensionScore(name="Investment Risk"))

    # Aggregate
    overall_score: float = 0.0  # 0-100
    overall_label: str = ""
    verdict: str = ""
    recommendation: str = ""
    investment_tagline: str = ""

    # Lists
    key_risks: List[str] = field(default_factory=list)
    key_opportunities: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def dimensions(self) -> List[DimensionScore]:
        return [
            self.fair_value,
            self.negotiation_opportunity,
            self.development_opportunity,
            self.planning_confidence,
            self.rental_potential,
            self.resale_potential,
            self.location_quality,
            self.investment_risk,
        ]

    def to_dict(self) -> dict:
        return asdict(self)


def _label(score: int) -> str:
    if score >= 8:
        return "Strong"
    if score >= 6:
        return "Good"
    if score >= 4:
        return "Fair"
    if score >= 2:
        return "Weak"
    return "Very Weak"


def calculate_scorecard(
    valuation: ValuationResult,
    recommendation: Recommendation,
    planning_result: Optional[dict] = None,
    btl_result: Optional[dict] = None,
    location_result: Optional[dict] = None,
    mode: str = "personal",
) -> InvestmentScorecard:
    """Calculate the full investment scorecard.

    `recommendation` is the single source of truth for pricing/negotiation
    judgements (see recommendation.py) — it must be built from whichever
    engine (V1 or V2) is primary for this run. `valuation` still supplies
    the non-pricing inputs used by the other six dimensions (development,
    planning, rental, resale, location, and the confidence/data-gap
    portions of risk) — those are unaffected by the V1/V2 pricing
    inconsistency this parameter was added to fix.

    mode: "personal" | "btl" | "both"
    """
    cfg = get_config()
    sc = InvestmentScorecard()
    planning = planning_result or {}
    btl = btl_result or {}
    location = location_result or {}

    # 1. Fair Value
    _score_fair_value(sc.fair_value, recommendation)

    # 2. Negotiation Opportunity
    _score_negotiation(sc.negotiation_opportunity, recommendation)

    # 3. Development Opportunity
    _score_development(sc.development_opportunity, planning)

    # 4. Planning Confidence
    _score_planning(sc.planning_confidence, planning)

    # 5. Rental Potential
    _score_rental(sc.rental_potential, btl, mode)

    # 6. Resale Potential
    _score_resale(sc.resale_potential, valuation, location)

    # 7. Location Quality
    _score_location(sc.location_quality, location, mode)

    # 8. Investment Risk
    _score_risk(sc.investment_risk, recommendation, valuation, planning, btl)

    # Apply weights and calculate overall
    weights = cfg.scorecard_weights
    weight_map = {
        "Fair Value": weights.fair_value,
        "Negotiation Opportunity": weights.negotiation_opportunity,
        "Development Opportunity": weights.development_opportunity,
        "Planning Confidence": weights.planning_confidence,
        "Rental Potential": weights.rental_potential,
        "Resale Potential": weights.resale_potential,
        "Location Quality": weights.location_quality,
        "Investment Risk": weights.investment_risk,
    }

    total_weighted = 0.0
    total_weight = 0.0
    for dim in sc.dimensions:
        w = weight_map.get(dim.name, 10.0)
        dim.weight = w
        dim.weighted_score = dim.score * w
        dim.label = _label(dim.score)
        total_weighted += dim.weighted_score
        total_weight += w

    sc.overall_score = round(total_weighted / total_weight * 10, 1) if total_weight > 0 else 0

    if sc.overall_score >= 75:
        sc.overall_label = "Strong"
    elif sc.overall_score >= 55:
        sc.overall_label = "Reasonable"
    elif sc.overall_score >= 40:
        sc.overall_label = "Marginal"
    else:
        sc.overall_label = "Weak"

    # Collect risks and opportunities
    _collect_risks_and_opportunities(sc, recommendation, valuation, planning, btl, location)

    # Verdict and recommendation
    sc.verdict = _generate_verdict(sc, mode)
    sc.recommendation = _generate_recommendation(sc, recommendation)
    sc.investment_tagline = recommendation.investment_tagline

    return sc


def _score_fair_value(dim: DimensionScore, recommendation: Recommendation):
    """How well-priced is the property relative to evidence?

    Thin consumer of Recommendation — the gap%, pricing classification,
    and "is there even a valuation" question are all decided once in
    recommendation.py. This function only maps that single gap value onto
    a 0-10 score band; it must not re-derive the pricing judgement itself.
    """
    if recommendation.pricing_classification == "Insufficient evidence":
        dim.score = 3
        dim.explanation = "Insufficient comparable evidence to assess fair value reliably."
        dim.key_drivers.append("Limited comparable data")
        return

    gap = recommendation.gap_pct

    if gap < -10:
        dim.score = 10
        dim.explanation = f"Asking price is {abs(gap):.0f}% below estimated fair value. Potential bargain if evidence is reliable."
    elif gap < -5:
        dim.score = 8
        dim.explanation = f"Asking price is {abs(gap):.0f}% below fair value. Looks well-priced."
    elif gap < 0:
        dim.score = 7
        dim.explanation = f"Asking price is {abs(gap):.0f}% below fair value. Slightly favourable."
    elif gap < 5:
        dim.score = 6
        dim.explanation = f"Asking price is within {gap:.0f}% of fair value. Fairly priced."
    elif gap < 10:
        dim.score = 4
        dim.explanation = f"Asking price is {gap:.0f}% above fair value. Overpriced unless negotiated."
    elif gap < 20:
        dim.score = 2
        dim.explanation = f"Asking price is {gap:.0f}% above fair value. Significantly overpriced."
    else:
        dim.score = 1
        dim.explanation = f"Asking price is {gap:.0f}% above fair value. Avoid at this price."

    dim.key_drivers.append(f"Asking/fair gap: {gap:+.1f}%")
    dim.key_drivers.append(f"Pricing classification: {recommendation.pricing_classification} ({recommendation.source_engine})")


def _score_negotiation(dim: DimensionScore, recommendation: Recommendation):
    """How much room is there to negotiate? Thin consumer of Recommendation
    — see _score_fair_value for why this must not re-derive the gap itself.
    """
    if recommendation.pricing_classification == "Insufficient evidence":
        dim.score = 5
        dim.explanation = "Cannot assess negotiation room without reliable valuation."
        return

    gap = recommendation.gap_pct

    if gap > 20:
        dim.score = 9
        dim.explanation = (
            f"Asking price is {gap:.0f}% above fair value. "
            f"Significant negotiation room. Vendor may be testing the market."
        )
        dim.key_drivers.append("Large overpricing suggests negotiability")
    elif gap > 10:
        dim.score = 7
        dim.explanation = (
            f"Asking price is {gap:.0f}% above fair value. "
            f"Good negotiation room if vendor is motivated."
        )
    elif gap > 5:
        dim.score = 6
        dim.explanation = f"Moderate room to negotiate down from asking price."
    elif gap > 0:
        dim.score = 5
        dim.explanation = f"Some room to negotiate but property is close to fair value."
    elif gap > -5:
        dim.score = 4
        dim.explanation = f"Priced at or below fair value. Less leverage for negotiation."
    else:
        dim.score = 3
        dim.explanation = f"Priced well below fair value. Little negotiation leverage - act fast."

    if recommendation.suggested_initial_offer > 0:
        dim.key_drivers.append(f"Suggested opening: {format_currency(recommendation.suggested_initial_offer)}")
    if recommendation.walk_away_price > 0:
        dim.key_drivers.append(f"Walk-away price: {format_currency(recommendation.walk_away_price)}")


def _score_development(dim: DimensionScore, planning: dict):
    """Is there value-add development potential?"""
    if not planning:
        dim.score = 5
        dim.explanation = "No planning assessment available."
        dim.key_drivers.append("Planning data not assessed")
        return

    scores = [
        planning.get("rear_extension_score", 0),
        planning.get("side_extension_score", 0),
        planning.get("loft_conversion_score", 0),
        planning.get("garage_conversion_score", 0),
        planning.get("outbuilding_score", 0),
    ]
    best = max(scores) if scores else 0
    net_high = planning.get("net_opportunity_high", 0)
    net_low = planning.get("net_opportunity_low", 0)

    dim.score = min(10, best)

    if best >= 7:
        dim.explanation = "Strong extension/development potential with likely positive return."
    elif best >= 5:
        dim.explanation = "Moderate development potential. Returns depend on build costs."
    elif best >= 3:
        dim.explanation = "Limited development potential. Constraints may apply."
    else:
        dim.explanation = "Little or no development opportunity."

    if net_high > 0:
        dim.key_drivers.append(f"Potential uplift: {format_currency(net_low)} - {format_currency(net_high)}")

    constraints = []
    if planning.get("listed_building"):
        constraints.append("Listed building")
    if planning.get("conservation_area"):
        constraints.append("Conservation area")
    if planning.get("green_belt"):
        constraints.append("Green Belt")
    if constraints:
        dim.key_drivers.append(f"Constraints: {', '.join(constraints)}")


def _score_planning(dim: DimensionScore, planning: dict):
    """How confident are we in planning/regulatory status?"""
    if not planning:
        dim.score = 5
        dim.explanation = "Planning constraints not assessed."
        return

    penalties = 0
    cfg = get_config()
    rp = cfg.risk_penalties
    issues = []

    if planning.get("listed_building"):
        penalties += abs(rp.listed_building)
        issues.append("Listed building")
    if planning.get("conservation_area"):
        penalties += abs(rp.conservation_area)
        issues.append("Conservation area")
    if planning.get("green_belt"):
        penalties += abs(rp.green_belt)
        issues.append("Green Belt")
    if planning.get("article_4"):
        penalties += abs(rp.article_4)
        issues.append("Article 4 direction")

    flood = planning.get("flood_zone", "")
    if "3" in str(flood):
        penalties += abs(rp.flood_zone_3)
        issues.append("Flood Zone 3")
    elif "2" in str(flood):
        penalties += abs(rp.flood_zone_2)
        issues.append("Flood Zone 2")

    if penalties == 0:
        dim.score = 9
        dim.explanation = "No planning constraints identified. Clear for permitted development."
    elif penalties <= 15:
        dim.score = 7
        dim.explanation = "Minor planning considerations but no showstoppers."
    elif penalties <= 30:
        dim.score = 5
        dim.explanation = "Moderate planning constraints that may limit development."
    elif penalties <= 50:
        dim.score = 3
        dim.explanation = "Significant planning constraints. Development will be restricted."
    else:
        dim.score = 1
        dim.explanation = "Severe planning constraints. Very limited scope for alteration."

    for issue in issues:
        dim.key_drivers.append(issue)


def _score_rental(dim: DimensionScore, btl: dict, mode: str):
    """Rental income potential."""
    if mode == "personal":
        dim.score = 5
        dim.explanation = "Rental potential not primary concern for personal purchase."
        dim.key_drivers.append("Personal use mode")
        return

    if not btl:
        dim.score = 5
        dim.explanation = "No BTL assessment available."
        return

    gross_yield = btl.get("gross_yield", 0)
    btl_score = btl.get("btl_score", 5)

    dim.score = min(10, btl_score)

    if gross_yield >= 8:
        dim.explanation = f"Excellent gross yield of {gross_yield:.1f}%. Strong rental investment."
    elif gross_yield >= 6:
        dim.explanation = f"Good gross yield of {gross_yield:.1f}%. Solid rental returns."
    elif gross_yield >= 4.5:
        dim.explanation = f"Moderate gross yield of {gross_yield:.1f}%. Acceptable for stable areas."
    elif gross_yield > 0:
        dim.explanation = f"Low gross yield of {gross_yield:.1f}%. Rental case is weak."
    else:
        dim.explanation = "No yield data available."

    if gross_yield > 0:
        dim.key_drivers.append(f"Gross yield: {gross_yield:.1f}%")

    for risk in btl.get("risk_factors", []):
        dim.key_drivers.append(risk)


def _score_resale(dim: DimensionScore, val: ValuationResult, location: dict):
    """How easy will this be to resell?"""
    score = 5

    if val.confidence_label == "High":
        score += 2
    elif val.confidence_label == "Low":
        score -= 1

    if val.hpi_annual_growth > 4:
        score += 1
    elif val.hpi_annual_growth < 1:
        score -= 1

    if location.get("location_score", 5) >= 7:
        score += 1
    elif location.get("location_score", 5) <= 3:
        score -= 1

    dim.score = max(1, min(10, score))

    if dim.score >= 7:
        dim.explanation = "Good resale prospects. Active market with healthy demand."
    elif dim.score >= 5:
        dim.explanation = "Average resale prospects."
    else:
        dim.explanation = "Resale may be challenging. Limited market or poor fundamentals."

    if val.hpi_annual_growth:
        dim.key_drivers.append(f"Annual HPI growth: {val.hpi_annual_growth:.1f}%")
    dim.key_drivers.append(f"Valuation confidence: {val.confidence_label}")


def _score_location(dim: DimensionScore, location: dict, mode: str):
    """Location quality relative to user's needs."""
    if not location:
        dim.score = 5
        dim.explanation = "Location not assessed."
        return

    loc_score = location.get("location_score", 5)
    dim.score = min(10, loc_score)

    home_dist = location.get("home_distance_miles")
    work_dist = location.get("work_distance_miles")

    if dim.score >= 8:
        dim.explanation = "Excellent location for stated needs."
    elif dim.score >= 6:
        dim.explanation = "Good location with reasonable access."
    elif dim.score >= 4:
        dim.explanation = "Acceptable location with trade-offs."
    else:
        dim.explanation = "Poor location relative to requirements."

    if home_dist is not None:
        dim.key_drivers.append(f"Distance from home: {home_dist:.1f} miles")
    if work_dist is not None:
        dim.key_drivers.append(f"Distance from work: {work_dist:.1f} miles")


def _score_risk(dim: DimensionScore, recommendation: Recommendation, val: ValuationResult, planning: dict, btl: dict):
    """Overall investment risk assessment. Higher score = lower risk.

    Pricing risk (the asking-vs-fair-value gap) comes from Recommendation,
    the single source of truth. Confidence/data-gap risk still comes from
    `val` — those aren't pricing judgements, so aren't part of this fix.
    """
    risk_score = 10  # Start at best, deduct for risks

    if val.confidence_label == "Very Low":
        risk_score -= 4
    elif val.confidence_label == "Low":
        risk_score -= 2
    elif val.confidence_label == "Medium":
        risk_score -= 1

    if not val.sufficient_evidence:
        risk_score -= 3
        dim.key_drivers.append("Insufficient comparable evidence")

    if recommendation.gap_pct > 15:
        risk_score -= 2
        dim.key_drivers.append(f"Asking price {recommendation.gap_pct:.0f}% above fair value")
    elif recommendation.gap_pct > 10:
        risk_score -= 1

    if planning.get("flood_zone") and "3" in str(planning.get("flood_zone", "")):
        risk_score -= 2
        dim.key_drivers.append("Flood Zone 3")
    elif planning.get("flood_zone") and "2" in str(planning.get("flood_zone", "")):
        risk_score -= 1

    if planning.get("listed_building"):
        risk_score -= 2
        dim.key_drivers.append("Listed building")

    if val.data_gaps:
        risk_score -= 1
        dim.key_drivers.append(f"{len(val.data_gaps)} data gap(s) identified")

    dim.score = max(1, min(10, risk_score))

    if dim.score >= 8:
        dim.explanation = "Low investment risk. Strong evidence base and few constraints."
    elif dim.score >= 6:
        dim.explanation = "Moderate risk. Some data gaps or constraints but manageable."
    elif dim.score >= 4:
        dim.explanation = "Elevated risk. Multiple concerns require careful due diligence."
    else:
        dim.explanation = "High risk. Significant unknowns or constraints. Proceed with extreme caution."


def _collect_risks_and_opportunities(
    sc: InvestmentScorecard,
    recommendation: Recommendation,
    val: ValuationResult,
    planning: dict,
    btl: dict,
    location: dict,
):
    """Collect the most important risks and opportunities.

    Pricing-derived items use `recommendation.gap_pct` (single source of
    truth); confidence/data-gap items still come from `val` — see
    _score_risk for why that split is intentional.
    """
    gap = recommendation.gap_pct

    # Risks
    if gap > 10:
        sc.key_risks.append(f"Asking price {gap:+.0f}% above estimated fair value")
    if val.confidence_label in ("Low", "Very Low"):
        sc.key_risks.append(f"Valuation confidence: {val.confidence_label}")
    if not val.sufficient_evidence:
        sc.key_risks.append("Insufficient comparable evidence")
    if planning.get("listed_building"):
        sc.key_risks.append("Listed building - constraints on alterations")
    if planning.get("flood_zone"):
        sc.key_risks.append(f"Flood risk: {planning['flood_zone']}")
    for gap_item in val.data_gaps[:2]:
        sc.key_risks.append(gap_item)
    for risk in btl.get("risk_factors", [])[:2]:
        sc.key_risks.append(risk)

    # Opportunities
    if gap < -5:
        sc.key_opportunities.append(f"Priced {abs(gap):.0f}% below fair value")
    if sc.development_opportunity.score >= 6:
        sc.key_opportunities.append("Good development/extension potential")
    if btl.get("gross_yield", 0) >= 6:
        sc.key_opportunities.append(f"Strong rental yield: {btl['gross_yield']:.1f}%")
    if gap > 10:
        sc.key_opportunities.append("Large negotiation margin if vendor is motivated")
    if sc.location_quality.score >= 8:
        sc.key_opportunities.append("Excellent location")


def _generate_verdict(sc: InvestmentScorecard, mode: str) -> str:
    overall = sc.overall_score
    if overall >= 75:
        return "Strong investment opportunity"
    if overall >= 55:
        return "Reasonable opportunity with caveats"
    if overall >= 40:
        return "Marginal - proceed with caution"
    if overall >= 25:
        return "Weak investment case"
    return "Avoid - poor value proposition"


def _generate_recommendation(
    sc: InvestmentScorecard,
    recommendation: Recommendation,
) -> str:
    """Thin consumer of Recommendation.offer_reasoning — this function used
    to independently re-derive the same gap-threshold offer logic that
    lives in recommendation.py (a sixth duplicate implementation found
    during the CR1 consistency audit). It now only adds scorecard-specific
    context (top risk/opportunity) around the single canonical offer text.
    """
    if recommendation.pricing_classification == "Insufficient evidence":
        return (
            "Insufficient evidence for a reliable valuation. "
            "Do not rely on this assessment alone. "
            "Manual comparable research is essential."
        )

    parts = [recommendation.offer_reasoning]

    if sc.key_risks:
        parts.append(f"Key risk: {sc.key_risks[0]}")

    if sc.key_opportunities:
        parts.append(f"Key opportunity: {sc.key_opportunities[0]}")

    return " ".join(p for p in parts if p)
