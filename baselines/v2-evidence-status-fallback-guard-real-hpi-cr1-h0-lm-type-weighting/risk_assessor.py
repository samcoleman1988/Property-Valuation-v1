"""Structured risk assessment for investment properties.

Produces categorised risk flags with severity, explanation,
and mitigation advice. No opaque risk scores.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .valuation_engine import ValuationResult
from .listing_interpreter import ListingSignals
from .recommendation import Recommendation


@dataclass
class RiskFlag:
    """A single identified risk."""
    category: str = ""       # e.g. "Valuation", "Planning", "Condition"
    severity: str = ""       # "High", "Medium", "Low"
    title: str = ""
    explanation: str = ""
    mitigation: str = ""


@dataclass
class RiskAssessment:
    """Full risk assessment for a property."""
    flags: List[RiskFlag] = field(default_factory=list)
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    overall_risk_level: str = ""  # "High", "Medium", "Low"
    summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def assess_risks(
    valuation: ValuationResult,
    recommendation: Recommendation,
    signals: ListingSignals,
    planning_result: Optional[dict] = None,
    btl_result: Optional[dict] = None,
    tenure: str = "",
    lease_years: Optional[int] = None,
) -> RiskAssessment:
    """Run structured risk assessment across all dimensions.

    `recommendation` is the single source of truth for the pricing risk
    flag (see recommendation.py) — build it from whichever engine (V1 or
    V2) is primary for this run. The other risk categories are unaffected
    and still read `valuation` directly.
    """
    ra = RiskAssessment()
    planning = planning_result or {}
    btl = btl_result or {}

    _assess_valuation_risks(ra, valuation)
    _assess_planning_risks(ra, planning)
    _assess_condition_risks(ra, signals)
    _assess_tenure_risks(ra, tenure, lease_years)
    _assess_btl_risks(ra, btl)
    _assess_overpricing_risk(ra, recommendation)
    _assess_liquidity_risks(ra, valuation, planning)

    ra.high_count = sum(1 for f in ra.flags if f.severity == "High")
    ra.medium_count = sum(1 for f in ra.flags if f.severity == "Medium")
    ra.low_count = sum(1 for f in ra.flags if f.severity == "Low")

    if ra.high_count >= 2:
        ra.overall_risk_level = "High"
    elif ra.high_count == 1 or ra.medium_count >= 3:
        ra.overall_risk_level = "Medium-High"
    elif ra.medium_count >= 1:
        ra.overall_risk_level = "Medium"
    else:
        ra.overall_risk_level = "Low"

    total = len(ra.flags)
    ra.summary = (
        f"{total} risk(s) identified: "
        f"{ra.high_count} high, {ra.medium_count} medium, {ra.low_count} low. "
        f"Overall risk level: {ra.overall_risk_level}."
    )

    return ra


def _assess_valuation_risks(ra: RiskAssessment, val: ValuationResult):
    if not val.sufficient_evidence:
        ra.flags.append(RiskFlag(
            category="Valuation",
            severity="High",
            title="Insufficient comparable evidence",
            explanation=(
                f"Only {val.comparables_used} comparable(s) found. "
                "The valuation cannot be relied upon."
            ),
            mitigation="Research sold prices manually via Land Registry. Get RICS valuation.",
        ))

    if val.confidence_label in ("Low", "Very Low"):
        ra.flags.append(RiskFlag(
            category="Valuation",
            severity="Medium",
            title=f"Low valuation confidence ({val.confidence_label})",
            explanation=(
                f"Confidence score: {val.confidence_score}/100. "
                f"Drivers: {'; '.join(val.confidence_drivers[:3])}"
            ),
            mitigation="Cross-reference with local agent appraisals and recent sold prices.",
        ))

    if val.data_gaps:
        for gap in val.data_gaps:
            ra.flags.append(RiskFlag(
                category="Valuation",
                severity="Low",
                title="Data gap",
                explanation=gap,
                mitigation="Request missing information from selling agent.",
            ))


def _assess_planning_risks(ra: RiskAssessment, planning: dict):
    if planning.get("listed_building"):
        ra.flags.append(RiskFlag(
            category="Planning",
            severity="High",
            title="Listed building",
            explanation=(
                "Listed buildings require Listed Building Consent for most alterations. "
                "Internal and external changes are heavily restricted."
            ),
            mitigation="Consult conservation officer before purchase. Budget for specialist materials.",
        ))

    if planning.get("conservation_area"):
        ra.flags.append(RiskFlag(
            category="Planning",
            severity="Medium",
            title="Conservation area",
            explanation="Permitted development rights may be restricted. Demolition requires consent.",
            mitigation="Check Article 4 directions. Pre-app with local planning authority.",
        ))

    if planning.get("green_belt"):
        ra.flags.append(RiskFlag(
            category="Planning",
            severity="High",
            title="Green Belt",
            explanation="Very limited scope for extension or new development in Green Belt.",
            mitigation="Only minor extensions likely to be approved. Factor into development appraisal.",
        ))

    flood = str(planning.get("flood_zone", ""))
    if "3" in flood:
        ra.flags.append(RiskFlag(
            category="Environmental",
            severity="High",
            title="Flood Zone 3",
            explanation="High probability of flooding. Insurance may be expensive or unavailable.",
            mitigation="Check Flood Re eligibility. Get flood survey. Review EA flood map.",
        ))
    elif "2" in flood:
        ra.flags.append(RiskFlag(
            category="Environmental",
            severity="Medium",
            title="Flood Zone 2",
            explanation="Medium probability of flooding. May affect insurance and resale.",
            mitigation="Check insurance costs. Review flood defences and property history.",
        ))

    if planning.get("article_4"):
        ra.flags.append(RiskFlag(
            category="Planning",
            severity="Low",
            title="Article 4 direction",
            explanation="Some permitted development rights removed. Planning permission required for certain changes.",
            mitigation="Check which PD rights are withdrawn before planning any works.",
        ))


def _assess_condition_risks(ra: RiskAssessment, signals: ListingSignals):
    if signals.structural_concerns:
        ra.flags.append(RiskFlag(
            category="Condition",
            severity="High",
            title="Structural concerns flagged",
            explanation=(
                f"Listing text mentions potential structural issues. "
                f"Keywords: {', '.join(signals.condition_keywords_found[:3])}"
            ),
            mitigation="Full structural survey essential before exchange. Budget for remedial works.",
        ))

    if signals.non_standard_construction:
        ra.flags.append(RiskFlag(
            category="Condition",
            severity="Medium",
            title="Non-standard construction",
            explanation="Non-standard construction may limit mortgage availability and increase insurance costs.",
            mitigation="Check mortgage lender criteria. Specialist survey recommended.",
        ))

    if signals.project_property:
        ra.flags.append(RiskFlag(
            category="Condition",
            severity="Medium",
            title="Project property requiring significant works",
            explanation=f"Condition score: {signals.condition_score}/10 ({signals.condition_label}). Significant investment needed.",
            mitigation="Get detailed quotes before purchase. Add 20% contingency to all estimates.",
        ))


def _assess_tenure_risks(ra: RiskAssessment, tenure: str, lease_years: Optional[int]):
    if lease_years is not None:
        if lease_years < 80:
            ra.flags.append(RiskFlag(
                category="Tenure",
                severity="High",
                title=f"Short lease ({lease_years} years)",
                explanation=(
                    f"Lease under 80 years. Mortgage availability severely restricted. "
                    f"Significant lease extension premium required."
                ),
                mitigation=(
                    "Get lease extension quote from specialist solicitor. "
                    "Factor into offer. May add 10-30% to purchase cost."
                ),
            ))
        elif lease_years < 120:
            ra.flags.append(RiskFlag(
                category="Tenure",
                severity="Medium",
                title=f"Moderate lease ({lease_years} years)",
                explanation="Lease between 80-120 years. Extension advisable within first 2 years of ownership.",
                mitigation="Budget for statutory lease extension (typically 1-3% of property value).",
            ))

    if tenure.lower() == "leasehold":
        ra.flags.append(RiskFlag(
            category="Tenure",
            severity="Low",
            title="Leasehold tenure",
            explanation="Ground rent, service charges, and management company rules apply.",
            mitigation="Review lease terms, ground rent escalation clauses, and management pack before exchange.",
        ))


def _assess_btl_risks(ra: RiskAssessment, btl: dict):
    for risk in btl.get("risk_factors", []):
        ra.flags.append(RiskFlag(
            category="BTL",
            severity="Medium",
            title="BTL risk factor",
            explanation=risk,
            mitigation="Factor into rental yield calculation.",
        ))


def _assess_overpricing_risk(ra: RiskAssessment, recommendation: Recommendation):
    """Thin consumer of Recommendation — gap% and pricing classification
    are decided once in recommendation.py, never re-derived here.
    """
    gap = recommendation.gap_pct
    if gap > 20:
        ra.flags.append(RiskFlag(
            category="Pricing",
            severity="High",
            title=f"Asking price materially above assessed value ({gap:+.0f}%)",
            explanation=(
                f"The asking price exceeds the assessed fair value by {gap:.0f}%, "
                f"which may leave the purchase price above realisable value shortly after completion."
            ),
            mitigation="An offer materially below asking price, supported by the comparable evidence, is recommended.",
        ))
    elif gap > 10:
        ra.flags.append(RiskFlag(
            category="Pricing",
            severity="Medium",
            title=f"Asking price above assessed value ({gap:+.0f}%)",
            explanation=f"The asking price is {gap:.0f}% above the assessed fair value.",
            mitigation="An offer below asking price, supported by the comparable evidence, is recommended.",
        ))


def _assess_liquidity_risks(ra: RiskAssessment, val: ValuationResult, planning: dict):
    if val.comparables_used <= 3:
        ra.flags.append(RiskFlag(
            category="Liquidity",
            severity="Low",
            title="Thin market",
            explanation=(
                f"Only {val.comparables_used} recent sale(s) found in this area. "
                "May indicate low demand or limited stock."
            ),
            mitigation="Research time-on-market for similar properties. Consider resale timing.",
        ))
