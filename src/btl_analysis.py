"""Buy-to-let investment analysis.

Estimates rental yield and BTL viability using free data where available,
with fallback to rule-of-thumb estimates when rental data is unavailable.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class BTLAssessment:
    # Rental estimates
    estimated_monthly_rent: float = 0.0
    rent_source: str = ""
    rental_confidence: str = ""

    # Yields
    gross_yield: float = 0.0
    net_yield_estimate: float = 0.0

    # Costs
    management_cost_annual: float = 0.0
    maintenance_annual: float = 0.0
    insurance_annual: float = 0.0
    void_allowance_annual: float = 0.0

    # Finance
    mortgage_interest_annual: float = 0.0
    cash_flow_monthly: float = 0.0

    # Assessment
    btl_score: int = 0  # 0-10
    btl_verdict: str = ""
    demand_factors: list = field(default_factory=list)
    risk_factors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Rough rental yield benchmarks by area type
YIELD_BENCHMARKS = {
    "wirral": {"gross_low": 5.0, "gross_mid": 6.5, "gross_high": 8.0},
    "oxford": {"gross_low": 3.5, "gross_mid": 4.5, "gross_high": 5.5},
    "national": {"gross_low": 4.0, "gross_mid": 5.5, "gross_high": 7.0},
}


def assess_btl(
    asking_price: float,
    fair_value: float,
    postcode: str,
    property_type: str = "",
    bedrooms: int = 0,
    epc_rating: str = "",
    tenure: str = "",
) -> BTLAssessment:
    """Run buy-to-let assessment."""
    assessment = BTLAssessment()
    purchase_price = fair_value if fair_value > 0 else asking_price

    if purchase_price <= 0:
        assessment.warnings.append("No purchase price available for BTL analysis")
        return assessment

    # Estimate rent
    _estimate_rent(assessment, purchase_price, postcode, property_type, bedrooms)

    # Calculate yields
    _calculate_yields(assessment, purchase_price)

    # Estimate costs
    _estimate_costs(assessment, purchase_price)

    # Assess demand
    _assess_demand(assessment, postcode, property_type, bedrooms)

    # Check risks
    _check_risks(assessment, epc_rating, tenure, property_type)

    # Score and verdict
    _score_btl(assessment)

    return assessment


def _estimate_rent(
    assessment: BTLAssessment,
    purchase_price: float,
    postcode: str,
    property_type: str,
    bedrooms: int,
):
    """Estimate monthly rent using postcode-based benchmarks.

    v1: Uses rule-of-thumb based on postcode area and property type.
    Full version would integrate free rental data sources.
    """
    outcode = postcode.split()[0] if postcode else ""

    # Determine area benchmark
    if outcode.startswith("CH"):
        area = "wirral"
    elif outcode.startswith("OX"):
        area = "oxford"
    else:
        area = "national"

    benchmark = YIELD_BENCHMARKS.get(area, YIELD_BENCHMARKS["national"])

    # Use mid-range yield to estimate rent
    mid_yield = benchmark["gross_mid"]
    assessment.estimated_monthly_rent = round((purchase_price * mid_yield / 100) / 12, 0)

    # Adjust for bedrooms
    if bedrooms >= 4:
        assessment.estimated_monthly_rent *= 1.1
    elif bedrooms <= 1:
        assessment.estimated_monthly_rent *= 0.85

    assessment.estimated_monthly_rent = round(assessment.estimated_monthly_rent, -1)

    assessment.rent_source = f"Estimated from {area} area yield benchmarks ({mid_yield}% gross)"
    assessment.rental_confidence = "Low — based on area averages, not actual rental comparables"
    assessment.warnings.append(
        "Rental estimate is rule-of-thumb only. Check Rightmove/OpenRent lettings "
        "for actual comparable rents in the area."
    )


def _calculate_yields(assessment: BTLAssessment, purchase_price: float):
    """Calculate gross and estimated net yields."""
    annual_rent = assessment.estimated_monthly_rent * 12

    if purchase_price > 0:
        assessment.gross_yield = round(annual_rent / purchase_price * 100, 2)

    # Conservative net yield: assume 30% costs
    assessment.net_yield_estimate = round(assessment.gross_yield * 0.7, 2)


def _estimate_costs(assessment: BTLAssessment, purchase_price: float):
    """Estimate annual BTL running costs."""
    annual_rent = assessment.estimated_monthly_rent * 12

    assessment.management_cost_annual = round(annual_rent * 0.10, 0)  # 10% management
    assessment.maintenance_annual = round(purchase_price * 0.01, 0)   # 1% of value
    assessment.insurance_annual = round(max(300, purchase_price * 0.003), 0)
    assessment.void_allowance_annual = round(annual_rent * 0.08, 0)   # 1 month void

    # Mortgage cost estimate (75% LTV, 5% rate)
    loan = purchase_price * 0.75
    assessment.mortgage_interest_annual = round(loan * 0.05, 0)

    total_costs = (
        assessment.management_cost_annual
        + assessment.maintenance_annual
        + assessment.insurance_annual
        + assessment.void_allowance_annual
        + assessment.mortgage_interest_annual
    )

    assessment.cash_flow_monthly = round((annual_rent - total_costs) / 12, 0)


def _assess_demand(
    assessment: BTLAssessment,
    postcode: str,
    property_type: str,
    bedrooms: int,
):
    """Flag likely rental demand factors."""
    outcode = postcode.split()[0] if postcode else ""
    pt = property_type.lower() if property_type else ""

    if outcode.startswith("OX"):
        assessment.demand_factors.append("Oxford area — strong rental demand from university and hospitals")
    if outcode.startswith("CH"):
        assessment.demand_factors.append("Wirral area — moderate rental demand, good yields available")

    if bedrooms == 2 or bedrooms == 3:
        assessment.demand_factors.append(f"{bedrooms}-bed properties typically have strong rental demand")
    elif bedrooms >= 5:
        assessment.demand_factors.append("Large properties: HMO potential but requires licensing")

    if "flat" in pt or "apartment" in pt:
        assessment.demand_factors.append("Flats: lower maintenance but check service charge and ground rent")
    if "terrace" in pt:
        assessment.demand_factors.append("Terraced houses: popular rental stock in many areas")


def _check_risks(
    assessment: BTLAssessment,
    epc_rating: str,
    tenure: str,
    property_type: str,
):
    """Flag BTL-specific risks."""
    if epc_rating and epc_rating.upper() in ("F", "G"):
        assessment.risk_factors.append(
            f"EPC rating {epc_rating.upper()} — illegal to let without upgrading to E minimum. "
            "Budget for EPC improvements before letting."
        )
    elif epc_rating and epc_rating.upper() == "E":
        assessment.risk_factors.append(
            "EPC rating E — meets minimum legal requirement but tightening expected. "
            "Budget for future upgrade to C."
        )

    if tenure and "leasehold" in tenure.lower():
        assessment.risk_factors.append(
            "Leasehold — check lease length, ground rent, service charge, and "
            "any restrictions on letting. Short leases reduce value and mortgageability."
        )

    pt = property_type.lower() if property_type else ""
    if "flat" in pt or "apartment" in pt:
        assessment.risk_factors.append("Check service charge trend and sinking fund adequacy")

    if not assessment.risk_factors:
        assessment.risk_factors.append("No specific BTL risk factors identified from available data")


def _score_btl(assessment: BTLAssessment):
    """Score BTL attractiveness 0-10."""
    score = 5

    if assessment.gross_yield >= 7:
        score += 2
    elif assessment.gross_yield >= 5.5:
        score += 1
    elif assessment.gross_yield < 4:
        score -= 2
    elif assessment.gross_yield < 5:
        score -= 1

    if assessment.cash_flow_monthly > 200:
        score += 1
    elif assessment.cash_flow_monthly < 0:
        score -= 2
    elif assessment.cash_flow_monthly < 100:
        score -= 1

    if len(assessment.risk_factors) > 2:
        score -= 1

    assessment.btl_score = max(0, min(10, score))

    if assessment.btl_score >= 7:
        assessment.btl_verdict = "Strong BTL candidate"
    elif assessment.btl_score >= 5:
        assessment.btl_verdict = "Acceptable BTL investment with caveats"
    elif assessment.btl_score >= 3:
        assessment.btl_verdict = "Weak BTL return — only if strong personal reasons"
    else:
        assessment.btl_verdict = "Poor BTL investment — avoid for pure yield play"
