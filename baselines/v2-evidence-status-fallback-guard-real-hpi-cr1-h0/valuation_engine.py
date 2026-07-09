"""Investment valuation engine.

Uses tier-filtered comparable evidence with explicit, traceable adjustments.
Replaces the old valuation.py. Every number is explainable.

Key safety features:
- Only uses Tier A-C comparables (hard-gated and type-matched)
- Checks comparable spread before producing a valuation
- Returns explicit valuation status (Reliable / Usable with caution / Weak / Insufficient)
- Conservative value is evidence-based, not a random low percentile
- Never defaults to asking price
"""

import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from .comparable_engine import ComparableEvidence, ScoredComparable
from .listing_interpreter import ListingSignals
from .hpi import adjust_price_to_current, get_annual_growth
from .config import get_config
from .utils import format_currency
from .recommendation import build_recommendation, Recommendation


@dataclass
class Adjustment:
    """A single traceable valuation adjustment."""
    name: str = ""
    amount: float = 0.0
    percentage: float = 0.0
    reason: str = ""
    direction: str = ""
    confidence: str = ""


@dataclass
class ValuationResult:
    asking_price: float = 0.0

    # Core valuations (0 = not produced)
    fair_value_balanced: float = 0.0
    fair_value_conservative: float = 0.0
    fair_value_aggressive: float = 0.0

    # Base comparable value (before adjustments)
    base_comparable_value: float = 0.0

    # Adjustments applied
    adjustments: List[Adjustment] = field(default_factory=list)
    total_adjustment: float = 0.0
    total_adjustment_pct: float = 0.0

    # Offer strategy
    suggested_initial_offer: float = 0.0
    max_sensible_offer: float = 0.0
    walk_away_price: float = 0.0
    negotiation_reasoning: str = ""

    # Gap analysis
    asking_vs_fair_gap: float = 0.0
    asking_vs_fair_gap_pct: float = 0.0

    # Per-sqm analysis
    price_per_sqm_asking: float = 0.0
    price_per_sqm_comparable: float = 0.0

    # Confidence
    confidence_score: int = 0
    confidence_label: str = ""
    confidence_drivers: List[str] = field(default_factory=list)

    # Valuation status
    valuation_status: str = ""  # "Reliable", "Usable with caution", "Weak evidence", "Insufficient evidence"
    sufficient_evidence: bool = True

    # Evidence summary
    comparables_used: int = 0
    excellent_comps: int = 0
    good_comps: int = 0
    evidence_summary: str = ""
    comparable_details: List[dict] = field(default_factory=list)

    # Spread metrics
    comparable_spread_iqr: float = 0.0
    comparable_spread_cv: float = 0.0
    comparable_max_min_ratio: float = 0.0
    spread_acceptable: bool = True

    # HPI
    hpi_annual_growth: float = 0.0
    hpi_region: str = ""

    # Methodology
    valuation_method: str = ""
    assumptions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)

    # Verdict — mirrors recommendation.investment_tagline; kept as a flat
    # field for existing consumers (PDF, property_db, saved-property UI).
    investment_tagline: str = ""

    # The single, authoritative pricing recommendation for this valuation.
    # Built once by build_recommendation() — see recommendation.py.
    recommendation: Optional[Recommendation] = None

    # Safeguard reporting
    strongest_direct_value: float = 0.0
    floor_area_implied_value: float = 0.0
    safeguard_cap_applied: bool = False
    safeguard_detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --- Minimum evidence thresholds ---
MIN_ELIGIBLE_FOR_VALUATION = 3
MIN_AB_FOR_HIGH_CONFIDENCE = 5
MIN_AB_FOR_MEDIUM_CONFIDENCE = 3
MIN_BC_FOR_MEDIUM_CONFIDENCE = 6

# --- Spread limits ---
MAX_CV_ACCEPTABLE = 0.40       # coefficient of variation
MAX_IQR_RATIO_ACCEPTABLE = 0.60  # IQR / median
MAX_MIN_RATIO_LIMIT = 3.0     # max price / min price


def calculate_valuation(
    asking_price: float,
    evidence: ComparableEvidence,
    signals: ListingSignals,
    floor_area_sqm: float = 0.0,
    tenure: str = "",
    region: str = "England",
) -> ValuationResult:
    """Run the full valuation using tier-filtered comparable evidence."""
    cfg = get_config()
    result = ValuationResult(asking_price=asking_price)
    result.hpi_region = region

    eligible = evidence.scored_comparables  # Tiers A-C only
    result.comparables_used = len(eligible)
    result.excellent_comps = evidence.tier_a_count
    result.good_comps = evidence.tier_b_count
    result.evidence_summary = evidence.evidence_summary

    # Step 1: Check minimum evidence thresholds
    _assess_evidence_sufficiency(result, evidence)

    if result.valuation_status == "Insufficient evidence":
        result.comparable_details = _format_comparables(eligible, evidence.context_only_comparables)
        _identify_data_gaps(result, evidence, floor_area_sqm, signals)
        return result

    # Step 2: HPI-adjust all eligible comparables
    _apply_hpi_adjustment(eligible, region, result)

    # Step 2b: Remove price outliers (IQR method)
    eligible = _trim_outliers(eligible, result)
    result.comparables_used = len(eligible)

    if len(eligible) < MIN_ELIGIBLE_FOR_VALUATION:
        result.valuation_status = "Insufficient evidence"
        result.sufficient_evidence = False
        result.warnings.append("Too few comparables remained after outlier removal.")
        result.recommendation = build_recommendation(
            fair_value_balanced=0, fair_value_conservative=0, asking_price=asking_price,
            asking_vs_fair_gap_pct=0, valuation_status=result.valuation_status,
            sufficient_evidence=False, source_engine="V1",
        )
        result.investment_tagline = result.recommendation.investment_tagline
        result.comparable_details = _format_comparables(eligible, evidence.context_only_comparables)
        _identify_data_gaps(result, evidence, floor_area_sqm, signals)
        return result

    # Step 3: Check comparable spread
    _check_spread(result, eligible)

    # Step 4: Calculate quality-weighted base value (per-sqm if possible)
    base_value = _calculate_weighted_base(eligible, result, floor_area_sqm)

    if base_value <= 0:
        result.warnings.append("Could not calculate base value from comparables")
        result.valuation_status = "Insufficient evidence"
        result.sufficient_evidence = False
        result.recommendation = build_recommendation(
            fair_value_balanced=0, fair_value_conservative=0, asking_price=asking_price,
            asking_vs_fair_gap_pct=0, valuation_status=result.valuation_status,
            sufficient_evidence=False, source_engine="V1",
        )
        # Distinct from the generic "insufficient evidence" tagline — this
        # specific failure mode (no usable comparable prices at all) is a
        # process failure, not a pricing judgement, so it keeps its own
        # message rather than being folded into build_recommendation().
        result.recommendation.investment_tagline = "Valuation failed - no usable comparable prices"
        result.investment_tagline = result.recommendation.investment_tagline
        return result

    result.base_comparable_value = round(base_value, -2)

    # Step 5: Apply explicit adjustments from listing signals
    adjusted_value = _apply_adjustments(base_value, signals, result)

    # Step 6: Calculate three cases
    _calculate_three_cases(adjusted_value, eligible, result)

    # Step 6b: Direct-evidence safeguard — only when floor-area method was used
    if result.floor_area_implied_value > 0:
        sqm_comps = [
            c for c in eligible
            if c.adjusted_price > 0 and getattr(c, "floor_area_sqm", 0) > 0
        ]
        _apply_direct_evidence_safeguard(result, eligible, sqm_comps, floor_area_sqm)
    else:
        direct = _find_strongest_direct_evidence(eligible)
        if direct:
            result.strongest_direct_value = round(direct.adjusted_price, -2)
            result.safeguard_detail = "Whole-property method — direct evidence included in weighting"

    # Step 7: Per-sqm metrics
    if floor_area_sqm > 0:
        result.price_per_sqm_asking = round(asking_price / floor_area_sqm, 0)
        if result.fair_value_balanced > 0:
            result.price_per_sqm_comparable = round(result.fair_value_balanced / floor_area_sqm, 0)

    # Step 8: Gap analysis
    if result.fair_value_balanced > 0:
        result.asking_vs_fair_gap = asking_price - result.fair_value_balanced
        result.asking_vs_fair_gap_pct = round(
            (asking_price - result.fair_value_balanced) / result.fair_value_balanced * 100, 1
        )

    # Step 9: Confidence scoring
    _score_confidence(result, evidence, floor_area_sqm)

    # Step 10: HPI growth
    result.hpi_annual_growth = get_annual_growth(region) or cfg.hpi.national_annual_growth_pct

    # Step 11: Recommendation — the single place tagline, offer strategy,
    # and pricing classification are decided (see recommendation.py).
    result.recommendation = build_recommendation(
        fair_value_balanced=result.fair_value_balanced,
        fair_value_conservative=result.fair_value_conservative,
        asking_price=asking_price,
        asking_vs_fair_gap_pct=result.asking_vs_fair_gap_pct,
        valuation_status=result.valuation_status,
        sufficient_evidence=result.sufficient_evidence,
        source_engine="V1",
    )
    result.investment_tagline = result.recommendation.investment_tagline
    result.suggested_initial_offer = result.recommendation.suggested_initial_offer
    result.max_sensible_offer = result.recommendation.max_sensible_offer
    result.walk_away_price = result.recommendation.walk_away_price
    result.negotiation_reasoning = result.recommendation.offer_reasoning

    # Step 13: Format comparable details for report (eligible + context)
    result.comparable_details = _format_comparables(eligible, evidence.context_only_comparables)

    # Step 14: Note data gaps
    _identify_data_gaps(result, evidence, floor_area_sqm, signals)

    return result


def _assess_evidence_sufficiency(result: ValuationResult, evidence: ComparableEvidence):
    """Determine valuation status based on tier counts and evidence quality."""
    tier_a = evidence.tier_a_count
    tier_b = evidence.tier_b_count
    tier_c = evidence.tier_c_count
    eligible = tier_a + tier_b + tier_c

    if eligible < MIN_ELIGIBLE_FOR_VALUATION:
        result.valuation_status = "Insufficient evidence"
        result.sufficient_evidence = False
        result.confidence_score = max(5, eligible * 5)
        result.confidence_label = "Insufficient"
        result.confidence_drivers.append(
            f"Only {eligible} eligible comparable(s) (Tiers A-C). Minimum {MIN_ELIGIBLE_FOR_VALUATION} required."
        )
        if evidence.tier_d_count > 0:
            result.confidence_drivers.append(
                f"{evidence.tier_d_count} Tier D (context-only) comparables exist but are too weak for valuation."
            )
        if evidence.total_excluded > 0:
            result.confidence_drivers.append(
                f"{evidence.total_excluded} comparables excluded by hard gates (wrong type, new build, etc)."
            )
        result.recommendation = build_recommendation(
            fair_value_balanced=0, fair_value_conservative=0, asking_price=result.asking_price,
            asking_vs_fair_gap_pct=0, valuation_status=result.valuation_status,
            sufficient_evidence=False, source_engine="V1",
        )
        result.investment_tagline = result.recommendation.investment_tagline
        result.valuation_method = "No valuation produced - insufficient eligible comparable evidence"
        result.warnings.append(
            f"Only {eligible} eligible comparable(s) found. "
            "The tool cannot produce a reliable valuation. "
            "Manual research via agent appraisals, Rightmove sold prices, or RICS valuation needed."
        )
        return

    ab_count = tier_a + tier_b

    if ab_count >= MIN_AB_FOR_HIGH_CONFIDENCE:
        result.valuation_status = "Reliable"
        result.sufficient_evidence = True
    elif ab_count >= MIN_AB_FOR_MEDIUM_CONFIDENCE:
        result.valuation_status = "Usable with caution"
        result.sufficient_evidence = True
    elif (tier_b + tier_c) >= MIN_BC_FOR_MEDIUM_CONFIDENCE:
        result.valuation_status = "Usable with caution"
        result.sufficient_evidence = True
    elif eligible >= MIN_ELIGIBLE_FOR_VALUATION:
        result.valuation_status = "Weak evidence"
        result.sufficient_evidence = True
        result.warnings.append(
            f"Valuation relies on {eligible} eligible comparables "
            f"({tier_a} Tier A, {tier_b} Tier B, {tier_c} Tier C). "
            "Treat as indicative only."
        )
    else:
        result.valuation_status = "Insufficient evidence"
        result.sufficient_evidence = False


def _apply_hpi_adjustment(
    eligible: List[ScoredComparable], region: str, result: ValuationResult
):
    for comp in eligible:
        comp.adjusted_price = adjust_price_to_current(comp.price, comp.date, region)
    result.assumptions.append("Historic prices adjusted to current values using UK House Price Index")


def _trim_outliers(
    eligible: List[ScoredComparable], result: ValuationResult
) -> List[ScoredComparable]:
    """Remove price outliers using 1.5x IQR method.

    This is the standard statistical approach: anything below Q1 - 1.5*IQR
    or above Q3 + 1.5*IQR is considered an outlier.
    """
    if len(eligible) < 5:
        return eligible

    prices = np.array([c.adjusted_price for c in eligible if c.adjusted_price > 0])
    if len(prices) < 5:
        return eligible

    q1 = np.percentile(prices, 25)
    q3 = np.percentile(prices, 75)
    iqr = q3 - q1

    if iqr == 0:
        return eligible

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    kept = []
    removed = 0
    for c in eligible:
        if c.adjusted_price > 0 and lower <= c.adjusted_price <= upper:
            kept.append(c)
        else:
            removed += 1

    if removed > 0:
        result.assumptions.append(
            f"{removed} price outlier(s) removed (outside Q1-1.5*IQR to Q3+1.5*IQR range: "
            f"{format_currency(lower)} to {format_currency(upper)})"
        )

    return kept if len(kept) >= MIN_ELIGIBLE_FOR_VALUATION else eligible


def _check_spread(result: ValuationResult, eligible: List[ScoredComparable]):
    """Check if the comparable spread is acceptable for a precise valuation."""
    prices = np.array([c.adjusted_price for c in eligible if c.adjusted_price > 0])
    if len(prices) < 3:
        return

    mean_p = np.mean(prices)
    std_p = np.std(prices)
    q1 = np.percentile(prices, 25)
    q3 = np.percentile(prices, 75)
    iqr = q3 - q1
    median_p = np.median(prices)
    min_p = np.min(prices)
    max_p = np.max(prices)

    cv = std_p / mean_p if mean_p > 0 else 999
    iqr_ratio = iqr / median_p if median_p > 0 else 999
    max_min_ratio = max_p / min_p if min_p > 0 else 999

    result.comparable_spread_cv = round(cv, 3)
    result.comparable_spread_iqr = round(iqr, 0)
    result.comparable_max_min_ratio = round(max_min_ratio, 2)

    problems = []
    if cv > MAX_CV_ACCEPTABLE:
        problems.append(f"Price coefficient of variation {cv:.0%} exceeds {MAX_CV_ACCEPTABLE:.0%} limit")
    if iqr_ratio > MAX_IQR_RATIO_ACCEPTABLE:
        problems.append(f"IQR/median ratio {iqr_ratio:.0%} exceeds {MAX_IQR_RATIO_ACCEPTABLE:.0%} limit")
    if max_min_ratio > MAX_MIN_RATIO_LIMIT:
        problems.append(f"Max/min price ratio {max_min_ratio:.1f}x exceeds {MAX_MIN_RATIO_LIMIT:.1f}x limit")

    if problems:
        result.spread_acceptable = False
        for p in problems:
            result.warnings.append(p)

        if result.valuation_status == "Reliable":
            result.valuation_status = "Usable with caution"
        elif result.valuation_status == "Usable with caution":
            result.valuation_status = "Weak evidence"

        result.assumptions.append(
            f"Comparable spread warning: prices range from {format_currency(min_p)} "
            f"to {format_currency(max_p)} (IQR: {format_currency(iqr)}). "
            "Wide spread reduces valuation precision."
        )
    else:
        result.spread_acceptable = True


MIN_SQMETRE_COMPS = 3
DIRECT_EVIDENCE_CAP_PCT = 0.10
MIN_AB_SQM_TO_OVERRIDE_DIRECT = 3
SAME_STREET_MAX_AGE_DAYS = 730


def _find_strongest_direct_evidence(
    eligible: List[ScoredComparable],
) -> Optional[ScoredComparable]:
    """Find the strongest same-street/building Tier A comparable within 24 months."""
    candidates = []
    for c in eligible:
        if c.tier != "A":
            continue
        prox = c.score_breakdown.get("proximity_level", 0)
        if prox < 4:
            continue
        if c.age_days > SAME_STREET_MAX_AGE_DAYS:
            continue
        if c.adjusted_price <= 0:
            continue
        candidates.append(c)

    if not candidates:
        return None

    candidates.sort(key=lambda c: c.quality_score, reverse=True)
    return candidates[0]


MIN_SIZE_RATIO = 0.50
MAX_SIZE_RATIO = 2.00


def _size_similarity_weight(comp_sqm: float, subject_sqm: float) -> float:
    """Return a 0-1 multiplier based on how similar two floor areas are.

    1.0 when identical, tapering via a Gaussian-style curve:
      weight = exp(-((ln(ratio))^2) / (2 * sigma^2))

    sigma=0.35 gives:  ratio 1.0 → 1.00,  0.8/1.25 → 0.88,
                        0.6/1.67 → 0.58,  0.5/2.0 → 0.37,
                        0.3/3.3 → 0.05
    """
    if comp_sqm <= 0 or subject_sqm <= 0:
        return 0.0
    import math
    ratio = comp_sqm / subject_sqm
    log_ratio = math.log(ratio)
    sigma = 0.35
    return math.exp(-(log_ratio ** 2) / (2 * sigma ** 2))


def _count_supporting_ab_sqm(
    sqm_comps: List[ScoredComparable],
    direct_comp: ScoredComparable,
    balanced_value: float,
    subject_sqm: float,
) -> float:
    """Size-weighted count of Tier A/B floor-area comps whose implied values
    also exceed the ±10% cap line around the direct comparable.

    Each supporting comp contributes its size_similarity_weight (0-1) rather
    than a flat 1, so a 95 sqm comp supporting a 100 sqm subject counts ~0.98
    while a 40 sqm comp counts ~0.14.
    """
    if subject_sqm <= 0:
        return 0.0
    direct_val = direct_comp.adjusted_price
    cap_line = direct_val * (1 + DIRECT_EVIDENCE_CAP_PCT) if balanced_value > direct_val else direct_val * (1 - DIRECT_EVIDENCE_CAP_PCT)
    weighted_count = 0.0
    for c in sqm_comps:
        if c is direct_comp:
            continue
        if c.tier not in ("A", "B"):
            continue
        if c.floor_area_sqm <= 0 or c.adjusted_price <= 0:
            continue
        comp_implied = (c.adjusted_price / c.floor_area_sqm) * subject_sqm
        supports = False
        if balanced_value > direct_val and comp_implied > cap_line:
            supports = True
        elif balanced_value < direct_val and comp_implied < cap_line:
            supports = True
        if supports:
            weighted_count += _size_similarity_weight(c.floor_area_sqm, subject_sqm)
    return weighted_count


def _apply_direct_evidence_safeguard(
    result: ValuationResult,
    eligible: List[ScoredComparable],
    sqm_comps: List[ScoredComparable],
    subject_sqm: float,
) -> None:
    """Cap final balanced value within ±10% of strongest same-street/building
    Tier A evidence unless ≥3 other Tier A/B floor-area comps also imply
    values beyond the cap line.

    Only called when floor-area normalisation was used.
    Operates on result.fair_value_balanced in place.
    """
    direct_comp = _find_strongest_direct_evidence(eligible)

    if direct_comp is None:
        result.safeguard_detail = "No same-street Tier A comparable within 24 months — no cap applied"
        return

    direct_val = direct_comp.adjusted_price
    result.strongest_direct_value = round(direct_val, -2)

    balanced = result.fair_value_balanced
    if balanced <= 0 or direct_val <= 0:
        return

    gap_pct = (balanced - direct_val) / direct_val

    if abs(gap_pct) <= DIRECT_EVIDENCE_CAP_PCT:
        result.safeguard_detail = (
            f"Balanced value within {DIRECT_EVIDENCE_CAP_PCT:.0%} of "
            f"same-street evidence ({format_currency(direct_val)}) — no cap needed"
        )
        return

    supporting = _count_supporting_ab_sqm(sqm_comps, direct_comp, balanced, subject_sqm)

    if supporting >= MIN_AB_SQM_TO_OVERRIDE_DIRECT:
        result.safeguard_detail = (
            f"Balanced value {gap_pct:+.1%} from same-street evidence "
            f"({format_currency(direct_val)}), but {supporting:.1f} size-weighted "
            f"Tier A/B comps also imply values beyond the cap — cap not applied"
        )
        return

    direction = 1 if gap_pct > 0 else -1
    capped = round(direct_val * (1 + direction * DIRECT_EVIDENCE_CAP_PCT), -3)

    old_balanced = result.fair_value_balanced
    result.fair_value_balanced = capped
    result.fair_value_aggressive = min(result.fair_value_aggressive, capped * 1.10) if result.fair_value_aggressive else 0
    result.fair_value_aggressive = round(max(result.fair_value_aggressive, capped), -3)
    result.fair_value_conservative = min(result.fair_value_conservative, capped) if result.fair_value_conservative else 0

    result.safeguard_cap_applied = True
    result.safeguard_detail = (
        f"Balanced value {format_currency(old_balanced)} was {gap_pct:+.1%} from "
        f"same-street evidence ({format_currency(direct_val)}). "
        f"Capped to {format_currency(capped)} (±{DIRECT_EVIDENCE_CAP_PCT:.0%}). "
        f"Only {supporting:.1f} size-weighted supporting Tier A/B comp(s) "
        f"(need {MIN_AB_SQM_TO_OVERRIDE_DIRECT} to override)"
    )
    result.valuation_method = (
        f"Direct comparable-led: same-street evidence anchored at "
        f"{format_currency(direct_val)}, floor-area adjustment capped at "
        f"±{DIRECT_EVIDENCE_CAP_PCT:.0%}"
    )


def _calculate_weighted_base(
    eligible: List[ScoredComparable],
    result: ValuationResult,
    subject_floor_area_sqm: float = 0.0,
) -> float:
    """Calculate quality-weighted base value from eligible comparables.

    If subject floor area is known and enough comparables have EPC floor area,
    uses per-sqm normalisation. Otherwise falls back to whole-property prices.
    The direct-evidence safeguard runs separately after three-case calculation.
    """
    if not eligible:
        return 0.0

    if subject_floor_area_sqm > 0:
        sqm_comps = [
            c for c in eligible
            if c.adjusted_price > 0 and getattr(c, "floor_area_sqm", 0) > 0
        ]
        if len(sqm_comps) >= MIN_SQMETRE_COMPS:
            raw = _weighted_base_per_sqm(
                sqm_comps, eligible, subject_floor_area_sqm, result
            )
            result.floor_area_implied_value = round(raw, -2)
            return raw
        elif sqm_comps:
            raw = _weighted_base_mixed(
                sqm_comps, eligible, subject_floor_area_sqm, result
            )
            result.floor_area_implied_value = round(raw, -2)
            return raw

    return _weighted_base_whole_property(eligible, result)


def _weighted_base_per_sqm(
    sqm_comps: List[ScoredComparable],
    all_eligible: List[ScoredComparable],
    subject_sqm: float,
    result: ValuationResult,
) -> float:
    """Per-sqm normalised valuation using comps with known floor area.

    Each comp's weight = quality_score × size_similarity_weight, so
    similarly-sized properties dominate the weighted average.
    """
    implied_values = []
    weights = []
    for c in sqm_comps:
        psm = c.adjusted_price / c.floor_area_sqm
        c.price_per_sqm = round(psm, 0)
        implied = psm * subject_sqm
        implied_values.append(implied)
        size_w = _size_similarity_weight(c.floor_area_sqm, subject_sqm)
        weights.append(c.quality_score * size_w)

    implied_arr = np.array(implied_values)
    weight_arr = np.array(weights, dtype=float)
    weight_sum = weight_arr.sum()
    if weight_sum == 0:
        weight_arr = np.ones_like(weight_arr)
        weight_sum = len(weight_arr)
    norm = weight_arr / weight_sum

    weighted_avg = float(np.sum(implied_arr * norm))

    psm_values = [c.adjusted_price / c.floor_area_sqm for c in sqm_comps]
    median_psm = float(np.median(psm_values))

    result.valuation_method = (
        f"Floor-area adjusted: {len(sqm_comps)} comparables with EPC floor area, "
        f"size+quality-weighted £/sqm × {subject_sqm:.0f} sqm subject area"
    )
    result.price_per_sqm_comparable = round(median_psm, 0)
    result.assumptions.append(
        f"Per-sqm method: {len(sqm_comps)} comps with floor area "
        f"(median £{median_psm:,.0f}/sqm, range £{min(psm_values):,.0f}-£{max(psm_values):,.0f}/sqm), "
        f"weighted by size similarity to {subject_sqm:.0f} sqm subject"
    )

    return weighted_avg


def _weighted_base_mixed(
    sqm_comps: List[ScoredComparable],
    all_eligible: List[ScoredComparable],
    subject_sqm: float,
    result: ValuationResult,
) -> float:
    """Mixed method: per-sqm for comps that have floor area, whole-property for the rest."""
    values = []
    weights = []

    for c in sqm_comps:
        psm = c.adjusted_price / c.floor_area_sqm
        c.price_per_sqm = round(psm, 0)
        implied = psm * subject_sqm
        values.append(implied)
        size_w = _size_similarity_weight(c.floor_area_sqm, subject_sqm)
        weights.append(c.quality_score * 1.2 * size_w)

    for c in all_eligible:
        if c.adjusted_price > 0 and getattr(c, "floor_area_sqm", 0) <= 0:
            values.append(c.adjusted_price)
            weights.append(c.quality_score)

    if not values:
        return 0.0

    val_arr = np.array(values)
    weight_arr = np.array(weights, dtype=float)
    weight_sum = weight_arr.sum()
    if weight_sum == 0:
        weight_arr = np.ones_like(weight_arr)
        weight_sum = len(weight_arr)
    norm = weight_arr / weight_sum

    weighted_avg = float(np.sum(val_arr * norm))

    result.valuation_method = (
        f"Mixed evidence: {len(sqm_comps)} comps normalised per-sqm + "
        f"{len(values) - len(sqm_comps)} whole-property (Tiers A-C)"
    )
    result.assumptions.append(
        f"Mixed method: {len(sqm_comps)} comps had EPC floor area (weighted 1.2×), "
        f"{len(values) - len(sqm_comps)} used whole-property price"
    )

    return weighted_avg


def _weighted_base_whole_property(
    eligible: List[ScoredComparable],
    result: ValuationResult,
) -> float:
    """Original whole-property price method."""
    prices = np.array([c.adjusted_price for c in eligible if c.adjusted_price > 0])
    weights = np.array([c.quality_score for c in eligible if c.adjusted_price > 0])

    if len(prices) == 0:
        return 0.0

    weight_sum = weights.sum()
    if weight_sum == 0:
        weights = np.ones_like(weights)
        weight_sum = len(weights)
    norm_weights = weights / weight_sum

    weighted_avg = float(np.sum(prices * norm_weights))

    result.valuation_method = (
        f"Whole-property fallback: quality-weighted average of {len(prices)} "
        f"HPI-adjusted Land Registry comparables (Tiers A-C only)"
    )
    result.assumptions.append(
        f"Comparable weights based on tier scores (range {int(weights.min())}-{int(weights.max())})"
    )

    return weighted_avg


def _apply_adjustments(
    base_value: float,
    signals: ListingSignals,
    result: ValuationResult,
) -> float:
    adjusted = base_value
    total_adj_pct = 0.0

    for adj_rec in signals.adjustments:
        mid_pct = adj_rec["mid_pct"]
        amount = round(base_value * mid_pct, -2)

        adjustment = Adjustment(
            name=adj_rec["name"],
            amount=amount,
            percentage=round(mid_pct * 100, 1),
            reason=adj_rec["reason"],
            direction=adj_rec["direction"],
            confidence="medium",
        )
        result.adjustments.append(adjustment)
        adjusted += amount
        total_adj_pct += mid_pct

    result.total_adjustment = round(adjusted - base_value, -2)
    result.total_adjustment_pct = round(total_adj_pct * 100, 1)

    if result.adjustments:
        result.assumptions.append(
            f"{len(result.adjustments)} property-specific adjustments applied "
            f"(total: {result.total_adjustment_pct:+.1f}%)"
        )

    return adjusted


def _calculate_three_cases(
    adjusted_value: float,
    eligible: List[ScoredComparable],
    result: ValuationResult,
):
    """Calculate conservative, balanced, and aggressive valuations.

    Conservative: IQR-based lower bound, not a random percentile of noisy data.
    Balanced: quality-weighted average with adjustments.
    Aggressive: IQR-based upper bound.

    If evidence is weak, conservative and aggressive are suppressed.
    """
    prices = np.array([c.adjusted_price for c in eligible if c.adjusted_price > 0])
    if len(prices) == 0:
        return

    # Balanced: the adjusted weighted value (best estimate)
    result.fair_value_balanced = round(adjusted_value, -3)

    if len(prices) < 3 or result.valuation_status == "Weak evidence":
        # With weak evidence, don't pretend we can estimate a range
        result.fair_value_conservative = 0.0
        result.fair_value_aggressive = 0.0
        result.assumptions.append(
            "Conservative and aggressive values not produced due to limited evidence. "
            "Balanced value is indicative only."
        )
        return

    # Use IQR for the range — this is robust to outliers
    q1 = float(np.percentile(prices, 25))
    q3 = float(np.percentile(prices, 75))
    median_p = float(np.median(prices))

    # Apply adjustment ratio to Q1 and Q3
    adj_ratio = adjusted_value / result.base_comparable_value if result.base_comparable_value > 0 else 1.0

    conservative_raw = q1 * adj_ratio
    aggressive_raw = q3 * adj_ratio

    # Conservative gets a small risk discount (5%)
    cfg = get_config()
    conservative_with_discount = conservative_raw * (1.0 - cfg.valuation.conservative_risk_discount)

    result.fair_value_conservative = round(conservative_with_discount, -3)
    result.fair_value_aggressive = round(aggressive_raw, -3)

    # Sanity checks
    result.fair_value_conservative = min(result.fair_value_conservative, result.fair_value_balanced)
    result.fair_value_aggressive = max(result.fair_value_aggressive, result.fair_value_balanced)

    # Don't let conservative be absurdly far from balanced
    max_conservative_gap = 0.30  # conservative should be within 30% of balanced
    min_conservative = result.fair_value_balanced * (1 - max_conservative_gap)
    if result.fair_value_conservative < min_conservative:
        result.fair_value_conservative = round(min_conservative, -3)
        result.warnings.append(
            "Conservative value capped — comparable price spread was very wide. "
            "The conservative figure is a floor based on 30% below balanced, not raw comparable data."
        )

    result.assumptions.append(
        f"Conservative: Q1 of eligible comparables with {int(cfg.valuation.conservative_risk_discount*100)}% risk discount"
    )
    result.assumptions.append(
        f"Aggressive: Q3 of eligible comparables"
    )


# NOTE: offer-strategy generation (initial offer / max sensible / walk-away
# / negotiation reasoning) used to live here as _calculate_offer_strategy().
# It has moved to recommendation.py's build_recommendation() — the single
# implementation shared by V1 and V2 — and is called from calculate_valuation().


def _score_confidence(
    result: ValuationResult,
    evidence: ComparableEvidence,
    floor_area_sqm: float,
):
    """Score valuation confidence based on tier quality, spread, and data completeness."""
    score = 0
    drivers = []

    # Quality of evidence (max 40)
    tier_a = evidence.tier_a_count
    tier_b = evidence.tier_b_count
    ab = tier_a + tier_b

    if tier_a >= 5:
        score += 40
        drivers.append(f"{tier_a} Tier A comparables (same street/postcode, same type, recent)")
    elif tier_a >= 3:
        score += 32
        drivers.append(f"{tier_a} Tier A comparables")
    elif ab >= 5:
        score += 28
        drivers.append(f"{tier_a} Tier A + {tier_b} Tier B comparables")
    elif ab >= 3:
        score += 20
        drivers.append(f"{ab} Tier A/B comparables")
    elif evidence.total_scored >= 3:
        score += 10
        drivers.append(f"No strong comparables - relying on {evidence.total_scored} Tier B/C evidence")
    else:
        score += 3
        drivers.append("Very limited comparable evidence")

    # Quantity of eligible evidence (max 15)
    n = evidence.total_scored
    if n >= 10:
        score += 15
    elif n >= 6:
        score += 12
    elif n >= 4:
        score += 8
        drivers.append(f"Only {n} eligible comparables")
    elif n >= 3:
        score += 5
        drivers.append(f"Only {n} eligible comparables")
    else:
        score += 2

    # Price consistency / spread (max 25)
    if result.spread_acceptable:
        cv = result.comparable_spread_cv
        if cv > 0:
            if cv < 0.15:
                score += 25
                drivers.append(f"Tight price consistency (CV: {cv:.0%})")
            elif cv < 0.25:
                score += 18
                drivers.append(f"Good price consistency (CV: {cv:.0%})")
            elif cv < 0.35:
                score += 12
                drivers.append(f"Moderate price variation (CV: {cv:.0%})")
            else:
                score += 6
                drivers.append(f"Wide price variation (CV: {cv:.0%})")
        else:
            score += 10
    else:
        score += 3
        drivers.append("Comparable spread exceeds acceptable limits")

    # Floor area available (max 10)
    if floor_area_sqm > 0:
        score += 10
    else:
        score += 3
        drivers.append("No floor area data - cannot normalise per sqm")

    # Adjustments uncertainty (max 10)
    n_adj = len(result.adjustments)
    if n_adj == 0:
        score += 8
    elif n_adj <= 2:
        score += 6
    elif n_adj <= 4:
        score += 4
    else:
        score += 2
        drivers.append(f"{n_adj} adjustments applied - each adds uncertainty")

    result.confidence_score = min(100, score)

    if score >= 70:
        result.confidence_label = "High"
    elif score >= 45:
        result.confidence_label = "Medium"
    elif score >= 25:
        result.confidence_label = "Low"
    else:
        result.confidence_label = "Very Low"

    result.confidence_drivers = drivers


# NOTE: tagline generation used to live here as _generate_tagline(). It has
# moved to recommendation.py's build_recommendation() — the single
# implementation shared by V1 and V2.


def _format_comparables(
    eligible: List[ScoredComparable],
    context_only: Optional[List[ScoredComparable]] = None,
) -> List[dict]:
    """Format comparables for report. Eligible first, then context-only."""
    rows = []
    for comp in eligible[:15]:
        row = {
            "address": comp.address,
            "price": comp.price,
            "adjusted_price": round(comp.adjusted_price, 0) if comp.adjusted_price else 0,
            "date": comp.date,
            "property_type": comp.property_type,
            "tenure": comp.tenure,
            "tier": comp.tier,
            "quality_score": comp.quality_score,
            "quality_band": comp.quality_band,
            "selection_reason": comp.selection_reason,
        }
        fa = getattr(comp, "floor_area_sqm", 0)
        if fa and fa > 0:
            row["floor_area_sqm"] = fa
            row["price_per_sqm"] = round(comp.price / fa, 0) if fa else 0
            adj = comp.adjusted_price if comp.adjusted_price else comp.price
            row["adjusted_price_per_sqm"] = round(adj / fa, 0) if fa else 0
        rows.append(row)
    if context_only:
        for comp in context_only[:5]:
            rows.append({
                "address": comp.address,
                "price": comp.price,
                "adjusted_price": 0,
                "date": comp.date,
                "property_type": comp.property_type,
                "tenure": comp.tenure,
                "tier": "D (context)",
                "quality_score": comp.quality_score,
                "quality_band": "Context only",
                "selection_reason": comp.selection_reason,
            })
    return rows


def _identify_data_gaps(
    result: ValuationResult,
    evidence: ComparableEvidence,
    floor_area_sqm: float,
    signals: ListingSignals,
):
    if floor_area_sqm == 0:
        result.data_gaps.append(
            "No floor area available. Per-sqm normalisation not possible. "
            "Comparables are weighted by whole-property price which is less precise."
        )
    elif evidence.epc_matched_count == 0 and floor_area_sqm > 0:
        if evidence.epc_attempted_count == 0:
            result.data_gaps.append(
                "EPC enrichment unavailable (no API key). "
                "Per-sqm normalisation not applied — using whole-property prices."
            )
        else:
            result.data_gaps.append(
                "No EPC floor area matches found for comparables. "
                "Per-sqm normalisation not applied — using whole-property prices."
            )
    if evidence.tier_a_count == 0:
        result.data_gaps.append(
            "No Tier A comparables found (same street/postcode, same type, recent). "
            "Evidence relies on broader area matches."
        )
    if signals.condition_score == 5:
        result.data_gaps.append(
            "Property condition could not be determined from listing text. "
            "No condition adjustment applied - actual condition may differ from average."
        )
    if evidence.total_scored == 0:
        result.data_gaps.append(
            "No eligible comparable evidence available. Valuation cannot be produced."
        )
    if evidence.total_excluded > 5:
        result.data_gaps.append(
            f"{evidence.total_excluded} comparables were excluded by hard gates "
            f"(incompatible type, new build, etc). This may indicate the area has "
            f"mixed housing stock."
        )
    if not result.spread_acceptable:
        result.data_gaps.append(
            "Eligible comparable prices have a wide spread. The valuation range "
            "should be treated as approximate."
        )
    # Suggest manual checks when evidence is weak
    if result.valuation_status in ("Weak evidence", "Insufficient evidence"):
        result.data_gaps.append(
            "Suggested manual checks: (1) Search Rightmove/Zoopla sold prices for the street, "
            "(2) Request agent comparable evidence, "
            "(3) Check Land Registry for specific nearby sales, "
            "(4) Consider RICS valuation."
        )
