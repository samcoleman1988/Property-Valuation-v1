"""Overall scoring and investment verdict.

Combines valuation, planning, BTL, and location scores into
a single investment assessment.
"""

from dataclasses import dataclass, field, asdict


@dataclass
class InvestmentScore:
    # Component scores (0-10)
    value_score: int = 0
    planning_score: int = 0
    btl_score: int = 0
    location_score: int = 0
    condition_score: int = 5  # default mid-point, hard to assess from listing

    # Overall
    overall_score: int = 0  # 0-100
    verdict: str = ""
    tagline: str = ""
    key_risks: list = field(default_factory=list)
    key_opportunities: list = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_investment_score(
    valuation_result: dict,
    planning_result: dict,
    btl_result: dict,
    location_result: dict,
    mode: str = "personal",
) -> InvestmentScore:
    """Calculate overall investment score from component assessments."""
    score = InvestmentScore()

    # Value score from asking price gap
    gap_pct = valuation_result.get("asking_vs_fair_gap_pct", 0)
    if gap_pct < -10:
        score.value_score = 9
    elif gap_pct < -5:
        score.value_score = 8
    elif gap_pct < 0:
        score.value_score = 7
    elif gap_pct < 5:
        score.value_score = 6
    elif gap_pct < 10:
        score.value_score = 4
    elif gap_pct < 20:
        score.value_score = 3
    else:
        score.value_score = 1

    # Planning score
    best_ext = max(
        planning_result.get("rear_extension_score", 0),
        planning_result.get("side_extension_score", 0),
        planning_result.get("loft_conversion_score", 0),
        planning_result.get("garage_conversion_score", 0),
        planning_result.get("outbuilding_score", 0),
    )
    score.planning_score = best_ext

    # BTL score
    score.btl_score = btl_result.get("btl_score", 5)

    # Location score
    score.location_score = location_result.get("location_score", 5)

    # Weighted overall score
    if mode == "btl":
        weights = {"value": 3, "planning": 1.5, "btl": 3.5, "location": 2}
    elif mode == "both":
        weights = {"value": 3, "planning": 2, "btl": 2, "location": 3}
    else:
        weights = {"value": 3.5, "planning": 2, "btl": 0.5, "location": 4}

    weighted = (
        score.value_score * weights["value"]
        + score.planning_score * weights["planning"]
        + score.btl_score * weights["btl"]
        + score.location_score * weights["location"]
    )
    total_weight = sum(weights.values())
    score.overall_score = round(weighted / total_weight * 10)

    # Risks
    if gap_pct > 10:
        score.key_risks.append(f"Asking price {gap_pct:+.0f}% above estimated fair value")
    conf = valuation_result.get("confidence_score", 0)
    if conf < 40:
        score.key_risks.append("Low valuation confidence — limited comparable evidence")
    if planning_result.get("listed_building"):
        score.key_risks.append("Listed building — significant constraints on alterations")
    if planning_result.get("flood_zone"):
        score.key_risks.append(f"Flood risk: {planning_result['flood_zone']}")
    for risk in btl_result.get("risk_factors", []):
        score.key_risks.append(risk)

    # Opportunities
    if gap_pct < -5:
        score.key_opportunities.append(f"Priced {abs(gap_pct):.0f}% below fair value")
    if best_ext >= 6:
        net_opp = planning_result.get("net_opportunity_high", 0)
        if net_opp > 0:
            score.key_opportunities.append(f"Extension upside potential: £{net_opp:,.0f}")
    if btl_result.get("gross_yield", 0) >= 6:
        score.key_opportunities.append(f"Strong rental yield: {btl_result['gross_yield']:.1f}%")

    # Verdict and tagline
    score.tagline = valuation_result.get("investment_tagline", "")
    score.verdict = _generate_verdict(score, mode)
    score.recommendation = _generate_recommendation(score, valuation_result, mode)

    return score


def _generate_verdict(score: InvestmentScore, mode: str) -> str:
    overall = score.overall_score
    if overall >= 75:
        return "Strong investment opportunity"
    if overall >= 60:
        return "Reasonable opportunity with caveats"
    if overall >= 45:
        return "Marginal — proceed with caution"
    if overall >= 30:
        return "Weak investment case"
    return "Avoid — poor value proposition"


def _generate_recommendation(
    score: InvestmentScore,
    valuation: dict,
    mode: str,
) -> str:
    parts = []

    gap_pct = valuation.get("asking_vs_fair_gap_pct", 0)
    fair = valuation.get("fair_value_balanced", 0)
    initial = valuation.get("suggested_initial_offer", 0)
    walk = valuation.get("walk_away_price", 0)

    if gap_pct > 15:
        parts.append(
            f"The asking price appears significantly above fair value. "
            f"Do not offer more than £{fair:,.0f} without strong justification."
        )
    elif gap_pct > 5:
        parts.append(
            f"The asking price is above estimated fair value. "
            f"Open at £{initial:,.0f} and do not exceed £{walk:,.0f}."
        )
    elif gap_pct > -5:
        parts.append(
            f"Fairly priced. Open negotiations at £{initial:,.0f}."
        )
    else:
        parts.append(
            f"Priced below fair value — move quickly but still negotiate. "
            f"Open at £{initial:,.0f}."
        )

    if score.key_risks:
        parts.append(f"Key risk: {score.key_risks[0]}")

    if score.key_opportunities:
        parts.append(f"Key opportunity: {score.key_opportunities[0]}")

    return " ".join(parts)
