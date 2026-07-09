"""Valuation Engine V2 — four-group evidence architecture.

Replaces the single weighted-average approach with four distinct evidence
groups, each producing an independent valuation with its own confidence
assessment. The final valuation reconciles across groups.

Evidence groups:
  1. Direct Evidence     — same street/building, same type, recent
  2. Development Evidence — same estate/development, similar properties
  3. Local Market Evidence — same postcode sector, similar type & size
  4. Area Market Evidence  — wider area, broader type matching
"""

import math
import re
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

from .comparable_engine import (
    ScoredComparable, ComparableEvidence,
    COMPATIBLE_TYPES, PROPERTY_TYPE_REVERSE,
    _normalise_street, _extract_building_name, _extract_street_name,
    _is_same_street_or_building,
)
from .rightmove_parser import PropertyListing
from .valuation_engine import _size_similarity_weight
from .hpi import adjust_price_to_current
from .utils import postcode_sector, postcode_outcode


# Bump this (and add an entry under baselines/) whenever valuation logic in
# this module changes materially, so validation runs can be tied back to a
# specific, reproducible version of the engine.
MODEL_VERSION = "v2-evidence-status-fallback-guard"
MODEL_VERSION_DATE = "2026-07-09"

MAX_DIRECT_AGE_DAYS = 1095   # 3 years
MAX_DEV_AGE_DAYS = 1825      # 5 years


@dataclass
class EvidenceGroup:
    """One of the four comparable evidence groups.

    Each group independently assesses a subset of comparables that share
    a proximity/similarity profile. Every field is populated by the
    calculation step — construction leaves them at defaults.
    """

    name: str = ""
    description: str = ""

    # --- Comparables assigned to this group ---
    comparables: List[ScoredComparable] = field(default_factory=list)

    # --- Group-level statistics (populated by calculation step) ---
    median_value: float = 0.0
    weighted_mean: float = 0.0

    # --- Group valuation ---
    valuation: float = 0.0
    valuation_low: float = 0.0
    valuation_high: float = 0.0

    # --- Confidence in this group's output ---
    confidence_score: int = 0
    confidence_label: str = ""
    confidence_drivers: List[str] = field(default_factory=list)

    # --- Representative comparable (best single data point) ---
    representative: Optional[ScoredComparable] = None
    representative_reason: str = ""

    # --- Qualitative assessment ---
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

    # --- Per-sqm metrics (when floor area is available) ---
    median_price_per_sqm: float = 0.0
    weighted_mean_price_per_sqm: float = 0.0

    # --- Property type diagnostics ---
    type_exact_count: int = 0
    type_compatible_count: int = 0
    unknown_type_count: int = 0
    type_incompatible_fallback_count: int = 0
    type_excluded_count: int = 0

    # --- Evidence quality (trustworthiness of composition, 0-100) ---
    evidence_quality: int = 100

    # --- Evidence status (authority classification) ---
    evidence_status: str = "EMPTY"  # STRONG, WEAK, FALLBACK_ONLY, EMPTY
    evidence_status_reason: str = ""

    # --- Metadata ---
    comp_count: int = 0
    weight_in_final: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.representative:
            d["representative"] = self.representative.to_dict()
        return d


@dataclass
class Reconciliation:
    """How the final valuation was derived from the four evidence groups."""

    method: str = ""
    group_weights: dict = field(default_factory=dict)
    dominant_group: str = ""
    conflicts: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FinalValuation:
    """The reconciled valuation output — what the user sees."""

    asking_price: float = 0.0

    # --- Core valuations ---
    fair_value_balanced: float = 0.0
    fair_value_conservative: float = 0.0
    fair_value_aggressive: float = 0.0

    # --- Gap analysis ---
    asking_vs_fair_gap: float = 0.0
    asking_vs_fair_gap_pct: float = 0.0

    # --- Per-sqm ---
    price_per_sqm_asking: float = 0.0
    price_per_sqm_fair: float = 0.0

    # --- Offer strategy ---
    suggested_initial_offer: float = 0.0
    max_sensible_offer: float = 0.0
    walk_away_price: float = 0.0
    negotiation_reasoning: str = ""

    # --- Confidence ---
    confidence_score: int = 0
    confidence_label: str = ""
    confidence_drivers: List[str] = field(default_factory=list)

    # --- Status ---
    valuation_status: str = ""
    sufficient_evidence: bool = True

    # --- Methodology ---
    valuation_method: str = ""
    warnings: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)

    # --- Verdict ---
    investment_tagline: str = ""

    # --- Reconciliation trace ---
    reconciliation: Reconciliation = field(default_factory=Reconciliation)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValuationEvidence:
    """Top-level container: four evidence groups + final valuation.

    This is the single object returned by the V2 valuation pipeline.
    """

    # --- The four evidence groups ---
    direct: EvidenceGroup = field(default_factory=lambda: EvidenceGroup(
        name="Direct Evidence",
        description="Same street or building, same property type, sold within 24 months",
    ))
    development: EvidenceGroup = field(default_factory=lambda: EvidenceGroup(
        name="Development Evidence",
        description="Same estate or development, similar property type and size",
    ))
    local_market: EvidenceGroup = field(default_factory=lambda: EvidenceGroup(
        name="Local Market Evidence",
        description="Same postcode sector, similar type and size, floor-area adjusted",
    ))
    area_market: EvidenceGroup = field(default_factory=lambda: EvidenceGroup(
        name="Area Market Evidence",
        description="Wider postcode area, broader type matching, floor-area adjusted",
    ))

    # --- Final reconciled valuation ---
    final: FinalValuation = field(default_factory=FinalValuation)

    # --- Input context ---
    subject_postcode: str = ""
    subject_property_type: str = ""
    subject_bedrooms: int = 0
    subject_floor_area_sqm: float = 0.0
    subject_floor_area_source: str = ""
    subject_tenure: str = ""

    # --- Evidence totals ---
    total_comparables: int = 0
    total_with_floor_area: int = 0
    epc_matched_count: int = 0
    epc_attempted_count: int = 0

    @property
    def groups(self) -> List[EvidenceGroup]:
        return [self.direct, self.development, self.local_market, self.area_market]

    @property
    def active_groups(self) -> List[EvidenceGroup]:
        return [g for g in self.groups if g.comp_count > 0]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Direct Evidence group builder
# ---------------------------------------------------------------------------

@dataclass
class CompAssessment:
    """Why a comparable was included in or rejected from Direct Evidence."""
    comp: ScoredComparable = field(default_factory=ScoredComparable)
    included: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "address": self.comp.address,
            "included": self.included,
            "reasons": self.reasons,
        }


def _subject_type_code(listing: PropertyListing) -> str:
    """Derive the single-letter type code from a listing's property_type."""
    ptype = (listing.property_type or "").lower().strip()
    return PROPERTY_TYPE_REVERSE.get(ptype, "")


def _is_type_compatible(comp_code: str, subject_code: str) -> Tuple[bool, str]:
    """Check if a comp's property type is compatible with the subject.

    Used by Local Market (broad gate — unchanged from V1 COMPATIBLE_TYPES).
    """
    if not subject_code or not comp_code:
        return True, "type comparison: data incomplete — accepted"
    if comp_code == subject_code:
        return True, "same property type"
    compatible = COMPATIBLE_TYPES.get(subject_code, set())
    if comp_code in compatible:
        return True, f"compatible type ({comp_code})"
    return False, f"different type ({comp_code} vs {subject_code})"


# ---------------------------------------------------------------------------
# V2 strict property-type compatibility (Direct & Development only)
# ---------------------------------------------------------------------------
# Land Registry codes: D=Detached, S=Semi-Detached, T=Terraced, F=Flat/Maisonette
#
# Exact:      same code
# Compatible: S↔T only (semi ↔ end-terrace, which Land Registry records as T)
# All other cross-type combinations: incompatible (excluded, with fallback)

_V2_COMPATIBLE_PAIRS = {
    frozenset({"S", "T"}),
}


def is_property_type_compatible(
    subject_code: str, comp_code: str,
) -> str:
    """Classify comp type relationship for V2 evidence groups.

    Returns "exact", "compatible", "incompatible", or "unknown".
    """
    if not subject_code or not comp_code:
        return "unknown"
    if comp_code == subject_code:
        return "exact"
    if frozenset({subject_code, comp_code}) in _V2_COMPATIBLE_PAIRS:
        return "compatible"
    return "incompatible"


def property_type_weight(subject_code: str, comp_code: str) -> float:
    """Weight multiplier based on type compatibility for V2 evidence groups.

    exact:        1.0
    compatible:   0.70 (downgraded)
    incompatible: 0.25 (fallback only — used when <3 comps otherwise)
    unknown:      0.50
    """
    rel = is_property_type_compatible(subject_code, comp_code)
    if rel == "exact":
        return 1.0
    if rel == "compatible":
        return 0.70
    if rel == "incompatible":
        return 0.25
    return 0.50


_FALLBACK_OUTLIER_BAND = 0.50  # +/-50% of the genuine median


def _admit_fallback_comps(
    genuine_comps: List[ScoredComparable],
    incompatible_comps: List[ScoredComparable],
    assessments: List["CompAssessment"],
    region: str,
) -> Tuple[List[ScoredComparable], List[ScoredComparable]]:
    """Decide which incompatible-type comps may enter as fallback evidence.

    Fallback is only reached when genuine (exact/compatible/unknown) evidence
    is thin (<3 comps) — see callers. Even then, a fallback comp should only
    stand in for missing genuine evidence if it's a plausible proxy for the
    subject's value. A same-street mansion or converted farmhouse (wrong
    type, wildly different price) is not a proxy — it's an outlier that
    happens to share a postcode. Such comps are excluded from valuation and
    kept as contextual-only, with the reason recorded.

    If fewer than 2 genuine comps have priced data, there's no median to
    compare against, so fallback comps are admitted without the price check
    (there's nothing to judge them against) — but the resulting group still
    can't reach STRONG, since good_comps (exact+compatible) will be <3.

    Returns (admitted, excluded_as_outliers).
    """
    for c in genuine_comps + incompatible_comps:
        if c.adjusted_price <= 0 and c.price > 0 and c.date:
            c.adjusted_price = adjust_price_to_current(c.price, c.date, region)

    genuine_priced = [c for c in genuine_comps if c.adjusted_price > 0]
    genuine_median = None
    if len(genuine_priced) >= 2:
        genuine_median = float(np.median([c.adjusted_price for c in genuine_priced]))

    admitted: List[ScoredComparable] = []
    excluded: List[ScoredComparable] = []

    for c in incompatible_comps:
        assessment = next((a for a in assessments if a.comp is c), None)
        if genuine_median is not None and c.adjusted_price > 0:
            lo = genuine_median * (1 - _FALLBACK_OUTLIER_BAND)
            hi = genuine_median * (1 + _FALLBACK_OUTLIER_BAND)
            if not (lo <= c.adjusted_price <= hi):
                excluded.append(c)
                if assessment:
                    assessment.reasons.append(
                        f"rejected: incompatible-type fallback excluded as outlier "
                        f"(adj_price={c.adjusted_price:,.0f} outside +/-50% of genuine "
                        f"median {genuine_median:,.0f}) — kept as contextual only"
                    )
                continue
        admitted.append(c)
        if assessment:
            assessment.reasons.append(
                "type: incompatible — admitted as fallback (fewer than 3 genuine typed comps)"
            )

    return admitted, excluded


def _calculate_evidence_quality(group: EvidenceGroup) -> int:
    """Calculate evidence quality score (0-100) for an evidence group.

    This is NOT confidence. Confidence = how certain we are about the value.
    Evidence quality = how trustworthy the composition of the evidence is.

    A group with 5 exact-type matches scores near 100.
    A group with 7 incompatible fallbacks scores near 10-20.
    """
    if group.comp_count == 0:
        return 0

    score = 100.0
    n = group.comp_count

    # --- Type composition penalty (dominant factor) ---
    exact = group.type_exact_count
    compat = group.type_compatible_count
    fallback = group.type_incompatible_fallback_count
    typed_total = exact + compat + fallback
    if typed_total > 0:
        fallback_ratio = fallback / typed_total
        if exact == 0 and compat == 0 and fallback > 0:
            # Pure fallback — no same-type evidence at all: EQ should be ~10-15
            score -= 85
        else:
            # Mixed: penalise proportionally, 100% fallback → -80
            score -= fallback_ratio * 80

        compat_ratio = compat / typed_total
        if exact == 0 and compat > 0 and fallback == 0:
            score -= 10
        elif compat_ratio > 0.5:
            score -= compat_ratio * 8

    # --- Comp count penalty ---
    if n == 1:
        score -= 15
    elif n == 2:
        score -= 8
    # 3+ comps: no penalty

    # --- Recency penalty ---
    if group.comparables:
        old_comps = sum(1 for c in group.comparables if c.age_days > 1095)
        old_ratio = old_comps / n
        score -= old_ratio * 15  # all old → -15

    # --- Price spread penalty ---
    if n >= 2 and group.comparables:
        prices = [c.adjusted_price for c in group.comparables if c.adjusted_price > 0]
        if len(prices) >= 2:
            mean_p = sum(prices) / len(prices)
            if mean_p > 0:
                variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
                cv = (variance ** 0.5) / mean_p
                if cv > 0.40:
                    score -= 15
                elif cv > 0.25:
                    score -= 8
                elif cv > 0.15:
                    score -= 3

    return max(min(round(score), 100), 0)


def _calculate_evidence_status(group: EvidenceGroup) -> tuple:
    """Classify an evidence group as STRONG, WEAK, FALLBACK_ONLY, or EMPTY.

    Returns (status, reason) tuple.
    """
    if group.comp_count == 0:
        return "EMPTY", "No comparables found"

    exact = group.type_exact_count
    compat = group.type_compatible_count
    fallback = group.type_incompatible_fallback_count
    good_comps = exact + compat
    typed_total = exact + compat + fallback

    if good_comps == 0 and fallback > 0:
        return "FALLBACK_ONLY", f"No compatible property types available ({fallback} fallback)"

    # Check STRONG thresholds
    fallback_ratio = fallback / typed_total if typed_total > 0 else 0
    strong_reasons = []
    weak_reasons = []

    if good_comps >= 3:
        strong_reasons.append(f"{good_comps} exact/compatible")
    else:
        weak_reasons.append(f"only {good_comps} exact/compatible")

    if fallback_ratio <= 0.25:
        strong_reasons.append(f"{fallback_ratio:.0%} fallback" if fallback > 0 else "no fallback")
    else:
        weak_reasons.append(f"{fallback_ratio:.0%} fallback")

    # Recency: not all old
    if group.comparables:
        old_comps = sum(1 for c in group.comparables if c.age_days > 1095)
        if old_comps == len(group.comparables):
            weak_reasons.append("all comps older than 3 years")

    # Price spread
    if group.comp_count >= 2 and group.comparables:
        prices = [c.adjusted_price for c in group.comparables if c.adjusted_price > 0]
        if len(prices) >= 2:
            mean_p = sum(prices) / len(prices)
            if mean_p > 0:
                variance = sum((p - mean_p) ** 2 for p in prices) / len(prices)
                cv = (variance ** 0.5) / mean_p
                if cv > 0.40:
                    weak_reasons.append(f"wide spread (CV {cv:.0%})")

    if not weak_reasons:
        reason_parts = []
        if exact > 0:
            reason_parts.append(f"{exact} exact match{'es' if exact != 1 else ''}")
        if compat > 0:
            reason_parts.append(f"{compat} compatible")
        return "STRONG", "; ".join(reason_parts) if reason_parts else "good evidence"

    return "WEAK", "; ".join(weak_reasons)


def _extract_subject_street(listing: PropertyListing) -> str:
    """Extract and normalise the subject's street from its address.

    Uses manual override if provided, otherwise parses the Rightmove address.
    """
    if getattr(listing, "override_street_name", ""):
        return _normalise_street(listing.override_street_name)
    if not listing.address:
        return ""
    parts = listing.address.split(",")
    if parts:
        raw = parts[0].strip()
        raw = re.sub(r"^\d+[a-zA-Z]?\s*", "", raw).strip()
        return _normalise_street(raw)
    return ""


def build_direct_evidence_group(
    evidence: ComparableEvidence,
    subject_listing: PropertyListing,
    region: str = "England",
) -> EvidenceGroup:
    """Build the Direct Evidence group from scored comparables.

    A comparable qualifies as Direct Evidence if:
    - same street, same building, or same cul-de-sac
    - compatible property type
    - sold within 3 years
    - not excluded

    Returns an EvidenceGroup with all statistics populated.
    """
    group = EvidenceGroup(
        name="Direct Evidence",
        description="Same street or building, compatible type, sold within 3 years",
    )

    subject_code = _subject_type_code(subject_listing)
    subject_sqm = subject_listing.floor_area_sqm or 0.0
    subject_street = _extract_subject_street(subject_listing)
    subject_addr_first = ""
    if subject_listing.address:
        parts = subject_listing.address.split(",")
        if parts:
            subject_addr_first = parts[0].strip()

    all_comps = evidence.scored_comparables + evidence.context_only_comparables
    assessments: List[CompAssessment] = []

    # Two-pass approach: first collect candidates that pass proximity/recency/price,
    # then apply strict type filtering with fallback for <3 comps.
    proximity_candidates: List[ScoredComparable] = []
    proximity_assessments: List[CompAssessment] = []

    for c in all_comps:
        assessment = CompAssessment(comp=c)
        reasons = []

        # --- Gate 1: proximity ---
        is_same, prox_reason = _is_same_street_or_building(
            c, subject_street, subject_addr_first
        )
        if not is_same:
            prox_level = c.score_breakdown.get("proximity_level", 0)
            if prox_level >= 4:
                is_same = True
                prox_reason = f"V1 proximity_level={prox_level} (same street/building)"
            else:
                reasons.append(f"rejected: not same street/building ({c.street or c.address[:30]})")
                assessment.reasons = reasons
                assessments.append(assessment)
                continue
        reasons.append(f"proximity: {prox_reason}")

        # --- Gate 2: recency ---
        if c.age_days > MAX_DIRECT_AGE_DAYS:
            reasons.append(f"rejected: too old ({c.age_days} days, max {MAX_DIRECT_AGE_DAYS})")
            assessment.reasons = reasons
            assessments.append(assessment)
            continue
        if c.age_days <= 365:
            reasons.append(f"recency: {c.age_days} days (within 1 year)")
        elif c.age_days <= 730:
            reasons.append(f"recency: {c.age_days} days (within 2 years)")
        else:
            reasons.append(f"recency: {c.age_days} days (within 3 years)")

        # --- Gate 3: must have a price ---
        if c.price <= 0 and c.adjusted_price <= 0:
            reasons.append("rejected: no price data")
            assessment.reasons = reasons
            assessments.append(assessment)
            continue

        # Passed proximity, recency, price — type filtering happens below
        assessment.reasons = reasons
        proximity_candidates.append(c)
        proximity_assessments.append(assessment)

    # --- Strict type filtering with fallback ---
    exact_comps = []
    compatible_comps = []
    unknown_comps = []
    incompatible_comps = []
    type_diag = {"exact": 0, "compatible": 0, "unknown": 0, "incompatible": 0, "excluded": 0}

    for c, assessment in zip(proximity_candidates, proximity_assessments):
        rel = is_property_type_compatible(subject_code, c.property_type_code)
        if rel == "exact":
            type_diag["exact"] += 1
            assessment.reasons.append(f"type: exact match ({c.property_type_code})")
            exact_comps.append(c)
        elif rel == "compatible":
            type_diag["compatible"] += 1
            assessment.reasons.append(f"type: compatible but downgraded ({c.property_type_code} vs {subject_code})")
            compatible_comps.append(c)
        elif rel == "unknown":
            # Type unrecorded — included at reduced weight (see
            # property_type_weight) but must NOT inflate the exact-match
            # count or make the group appear more type-verified than it is.
            type_diag["unknown"] += 1
            assessment.reasons.append("type: data incomplete — included at reduced weight, not counted as exact")
            unknown_comps.append(c)
        else:
            type_diag["incompatible"] += 1
            incompatible_comps.append(c)

    # Build the genuine evidence set: exact + compatible + unknown (unknown
    # is already downweighted via property_type_weight, so it's safe to
    # treat as genuine for fallback-admission purposes).
    genuine_comps: List[ScoredComparable] = exact_comps + compatible_comps + unknown_comps
    direct_comps: List[ScoredComparable] = list(genuine_comps)
    fallback_used = False
    fallback_admitted: List[ScoredComparable] = []
    fallback_excluded_outliers: List[ScoredComparable] = []

    # Fallback: if <3 genuine comps, incompatible-type comps may stand in —
    # but only if they're not extreme relative to the genuine median price.
    if len(direct_comps) < 3 and incompatible_comps:
        fallback_admitted, fallback_excluded_outliers = _admit_fallback_comps(
            genuine_comps, incompatible_comps, proximity_assessments, region,
        )
        direct_comps.extend(fallback_admitted)
        fallback_used = len(fallback_admitted) > 0
        type_diag["excluded"] = len(fallback_excluded_outliers)
    else:
        type_diag["excluded"] = len(incompatible_comps)
        for c in incompatible_comps:
            # Find the matching assessment and mark rejected
            for assessment in proximity_assessments:
                if assessment.comp is c:
                    assessment.reasons.append(
                        f"rejected: incompatible type ({c.property_type_code} vs {subject_code})"
                    )
                    break

    # Finalise assessments
    for c, assessment in zip(proximity_candidates, proximity_assessments):
        if c in direct_comps:
            assessment.included = True
            assessment.reasons.append(f"included: adj_price={c.adjusted_price:,.0f}, tier={c.tier}")
        assessments.append(assessment)

    # Record diagnostics
    group.type_exact_count = type_diag["exact"]
    group.type_compatible_count = type_diag["compatible"]
    group.unknown_type_count = type_diag["unknown"]
    group.type_incompatible_fallback_count = len(fallback_admitted) if fallback_used else 0
    group.type_excluded_count = type_diag["excluded"]

    if fallback_used:
        fb_count = group.type_incompatible_fallback_count
        group.weaknesses.append(
            f"{fb_count} incompatible type(s) included at reduced weight "
            f"(fallback — fewer than 3 same-type comps available)"
        )

    if fallback_excluded_outliers:
        group.weaknesses.append(
            f"{len(fallback_excluded_outliers)} incompatible-type comp(s) excluded as outliers "
            f"(more than 50% from the genuine median price) — kept as contextual only, "
            f"not used in valuation"
        )

    if not direct_comps:
        group.weaknesses.append("No same-street/building comparables found within 3 years")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- HPI-adjust prices to current values ---
    for c in direct_comps:
        if c.adjusted_price <= 0 and c.price > 0 and c.date:
            c.adjusted_price = adjust_price_to_current(c.price, c.date, region)

    # Remove any that still have no adjusted price after HPI
    direct_comps = [c for c in direct_comps if c.adjusted_price > 0]
    if not direct_comps:
        group.weaknesses.append("Direct comparables found but HPI adjustment failed for all")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- Populate the group ---
    group.comparables = direct_comps
    group.comp_count = len(direct_comps)

    prices = np.array([c.adjusted_price for c in direct_comps])

    # Median
    group.median_value = round(float(np.median(prices)), -2)

    # Weighted mean: weight by recency, tier quality, and type compatibility
    weights = np.array([
        _direct_comp_weight(c) * property_type_weight(subject_code, c.property_type_code)
        for c in direct_comps
    ], dtype=float)
    w_sum = weights.sum()
    if w_sum > 0:
        group.weighted_mean = round(float(np.sum(prices * weights / w_sum)), -2)
    else:
        group.weighted_mean = group.median_value

    # Valuation: use weighted mean as primary, bounded by range
    group.valuation = group.weighted_mean
    if len(direct_comps) >= 3:
        p25 = float(np.percentile(prices, 25))
        p75 = float(np.percentile(prices, 75))
        group.valuation_low = round(p25, -2)
        group.valuation_high = round(p75, -2)
    elif len(direct_comps) == 2:
        group.valuation_low = round(float(prices.min()), -2)
        group.valuation_high = round(float(prices.max()), -2)
    else:
        group.valuation_low = round(float(prices[0] * 0.95), -2)
        group.valuation_high = round(float(prices[0] * 1.05), -2)

    # Per-sqm diagnostics (informational only — does not override direct values)
    if subject_sqm > 0:
        sqm_comps = [c for c in direct_comps if c.floor_area_sqm > 0]
        if sqm_comps:
            psm_values = [c.adjusted_price / c.floor_area_sqm for c in sqm_comps]
            group.median_price_per_sqm = round(float(np.median(psm_values)), 0)
            sqm_weights = np.array([
                _direct_comp_weight(c) * _size_similarity_weight(c.floor_area_sqm, subject_sqm)
                for c in sqm_comps
            ], dtype=float)
            sqm_w_sum = sqm_weights.sum()
            if sqm_w_sum > 0:
                psm_arr = np.array(psm_values)
                group.weighted_mean_price_per_sqm = round(
                    float(np.sum(psm_arr * sqm_weights / sqm_w_sum)), 0
                )

    # Representative comparable: highest quality score, most recent on ties
    best = max(direct_comps, key=lambda c: (c.quality_score, -c.age_days))
    group.representative = best
    group.representative_reason = (
        f"Tier {best.tier}, {best.age_days} days old, "
        f"{best.adjusted_price:,.0f} adj. price"
    )

    # Confidence
    _assess_direct_confidence(group, direct_comps, subject_code, subject_sqm)

    # Strengths and weaknesses
    _assess_direct_quality(group, direct_comps, assessments, subject_sqm)

    # Evidence quality and status
    group.evidence_quality = _calculate_evidence_quality(group)
    group.evidence_status, group.evidence_status_reason = _calculate_evidence_status(group)

    return group


def _direct_comp_weight(c: ScoredComparable) -> float:
    """Weight for a direct comparable: combines tier quality and recency."""
    tier_w = {"A": 5, "B": 4, "C": 3, "D": 2}.get(c.tier, 1)
    if c.age_days <= 180:
        recency_w = 4.0
    elif c.age_days <= 365:
        recency_w = 3.0
    elif c.age_days <= 730:
        recency_w = 2.0
    else:
        recency_w = 1.0
    return tier_w * recency_w


def _assess_direct_confidence(
    group: EvidenceGroup,
    comps: List[ScoredComparable],
    subject_code: str,
    subject_sqm: float,
) -> None:
    """Set confidence score (0-100) and label for the direct evidence group."""
    score = 0
    drivers = []

    n = len(comps)
    if n >= 4:
        score += 35
        drivers.append(f"{n} direct comps (strong)")
    elif n >= 2:
        score += 25
        drivers.append(f"{n} direct comps (moderate)")
    elif n == 1:
        score += 15
        drivers.append("1 direct comp only")

    # Recency
    recent = sum(1 for c in comps if c.age_days <= 365)
    if recent >= 2:
        score += 20
        drivers.append(f"{recent} sold within 1 year")
    elif recent == 1:
        score += 10
        drivers.append("1 sold within 1 year")
    else:
        oldest_recent = min(c.age_days for c in comps)
        drivers.append(f"most recent sale {oldest_recent} days ago")

    # Type match
    exact_type = sum(1 for c in comps if c.property_type_code == subject_code)
    if exact_type == n and n > 0:
        score += 15
        drivers.append("all exact type match")
    elif exact_type > 0:
        score += 10
        drivers.append(f"{exact_type}/{n} exact type match")
    else:
        score += 5
        drivers.append("compatible types only — no exact match")

    # Price consistency
    if n >= 2:
        prices = [c.adjusted_price for c in comps]
        cv = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 1.0
        if cv < 0.10:
            score += 20
            drivers.append(f"very tight spread (CV {cv:.0%})")
        elif cv < 0.20:
            score += 15
            drivers.append(f"good spread (CV {cv:.0%})")
        elif cv < 0.35:
            score += 10
            drivers.append(f"moderate spread (CV {cv:.0%})")
        else:
            score += 5
            drivers.append(f"wide spread (CV {cv:.0%})")

    # Floor area data
    if subject_sqm > 0:
        sqm_comps = sum(1 for c in comps if c.floor_area_sqm > 0)
        if sqm_comps == n and n > 0:
            score += 10
            drivers.append("all comps have floor area data")
        elif sqm_comps > 0:
            score += 5
            drivers.append(f"{sqm_comps}/{n} comps have floor area data")

    group.confidence_score = min(score, 100)
    if score >= 70:
        group.confidence_label = "High"
    elif score >= 45:
        group.confidence_label = "Medium"
    elif score >= 20:
        group.confidence_label = "Low"
    else:
        group.confidence_label = "Very Low"
    group.confidence_drivers = drivers


def _assess_direct_quality(
    group: EvidenceGroup,
    comps: List[ScoredComparable],
    assessments: List[CompAssessment],
    subject_sqm: float,
) -> None:
    """Populate strengths and weaknesses for the direct evidence group."""
    n = len(comps)
    rejected = [a for a in assessments if not a.included]

    # Strengths
    if n >= 3:
        group.strengths.append(f"{n} same-street/building sales — strong local anchor")
    elif n >= 1:
        group.strengths.append(f"{n} same-street/building sale(s) — direct anchor available")

    recent = [c for c in comps if c.age_days <= 365]
    if recent:
        group.strengths.append(
            f"{len(recent)} sale(s) within 1 year — current market conditions"
        )

    tier_a = [c for c in comps if c.tier == "A"]
    if tier_a:
        group.strengths.append(f"{len(tier_a)} Tier A comparable(s)")

    if subject_sqm > 0:
        similar_size = [
            c for c in comps
            if c.floor_area_sqm > 0
            and _size_similarity_weight(c.floor_area_sqm, subject_sqm) >= 0.80
        ]
        if similar_size:
            group.strengths.append(
                f"{len(similar_size)} comp(s) with similar floor area to subject"
            )

    # Weaknesses
    if n == 1:
        group.weaknesses.append("Only 1 direct comparable — limited triangulation")

    old_comps = [c for c in comps if c.age_days > 730]
    if old_comps:
        group.weaknesses.append(
            f"{len(old_comps)} comp(s) older than 2 years — may not reflect current market"
        )

    if subject_sqm > 0:
        no_sqm = [c for c in comps if c.floor_area_sqm <= 0]
        if no_sqm:
            group.weaknesses.append(
                f"{len(no_sqm)} comp(s) missing floor area — can't verify size similarity"
            )

        diff_size = [
            c for c in comps
            if c.floor_area_sqm > 0
            and _size_similarity_weight(c.floor_area_sqm, subject_sqm) < 0.50
        ]
        if diff_size:
            group.weaknesses.append(
                f"{len(diff_size)} comp(s) with very different floor area from subject"
            )

    if len(rejected) > 3:
        type_rejected = sum(1 for a in rejected if any("type" in r for r in a.reasons))
        if type_rejected:
            group.weaknesses.append(
                f"{type_rejected} same-street sale(s) rejected for incompatible type"
            )


# ---------------------------------------------------------------------------
# Development Evidence group builder
# ---------------------------------------------------------------------------

# Generic geographic/landmark words that appear in many unrelated street and
# building names across the country. A shared word from this list, on its
# own, is not evidence of a genuine estate/development relationship — e.g.
# "THE MILL HOUSE" on Eynsham Road is not part of the "Mill Street" estate
# just because both names contain "MILL".
_DEV_AFFINITY_STOPWORDS = {
    "MILL", "CHURCH", "MANOR", "PARK", "HOUSE", "COURT", "LODGE", "HALL",
    "FARM", "FARMHOUSE", "LANE", "ROAD", "STREET", "CLOSE", "DRIVE", "WAY",
    "AVENUE", "GROVE", "HILL", "VIEW", "GREEN", "GARDENS", "MEWS", "PLACE",
    "COTTAGE", "COTTAGES", "OLD", "NEW", "THE", "AND", "OF",
}

# Affinity reason substrings that indicate a genuinely strong development
# signal (same named development, same building/block, or exact road
# cluster/postcode match) — these are allowed to qualify a comp at the
# threshold boundary; weaker combinations must exceed it.
_DEV_STRONG_SIGNAL_MARKERS = ("same postcode", "estate name match", "building name overlap")


def _has_strong_dev_signal(affinity_reason: str) -> bool:
    return any(marker in affinity_reason for marker in _DEV_STRONG_SIGNAL_MARKERS)


def _is_direct_comp(
    c: ScoredComparable, subject_street: str, subject_addr_first: str,
) -> bool:
    """Check if a comp would qualify as Direct Evidence (same street/building)."""
    is_same, _ = _is_same_street_or_building(c, subject_street, subject_addr_first)
    if is_same:
        return True
    if c.score_breakdown.get("proximity_level", 0) >= 4:
        return True
    return False


def _development_affinity(
    c: ScoredComparable,
    subject_postcode: str,
    subject_street: str,
    subject_sector: str,
    subject_outcode: str,
    subject_estate_name: str = "",
) -> Tuple[float, str]:
    """Score how likely a comp is from the same estate/development as the subject.

    Returns (affinity 0.0–1.0, reason string).
    A comp on the same street is handled by Direct Evidence and excluded
    upstream, so this focuses on nearby-but-different-street signals.

    Same postcode is the strongest development signal. Same sector alone
    is NOT sufficient — that's local market territory. Sector-level comps
    only qualify if they also share a street/building name fragment.
    """
    reasons = []
    score = 0.0

    comp_pc = (c.postcode or "").upper().replace(" ", "")
    subj_pc = subject_postcode.upper().replace(" ", "")

    postcode_tier = "none"
    if comp_pc and subj_pc and comp_pc == subj_pc:
        score += 0.50
        reasons.append("same postcode")
        postcode_tier = "exact"
    elif comp_pc and subject_sector:
        comp_sector = postcode_sector(c.postcode).replace(" ", "").upper()
        subj_sector = subject_sector.replace(" ", "").upper()
        if comp_sector == subj_sector:
            score += 0.10
            reasons.append("same sector")
            postcode_tier = "sector"
        elif subject_outcode and postcode_outcode(c.postcode).upper() == subject_outcode.upper():
            postcode_tier = "outcode"
        else:
            return 0.0, "different postcode area"

    if postcode_tier == "none":
        return 0.0, "no postcode data"

    # Street name similarity — estates often have themed street names.
    # Generic geographic words (MILL, CHURCH, PARK, etc.) don't count on
    # their own — a shared word must include something distinguishing.
    name_signal = False
    comp_street_norm = _normalise_street(c.street)
    if comp_street_norm and subject_street:
        comp_words = set(re.findall(r"[A-Z]{3,}", comp_street_norm))
        subj_words = set(re.findall(r"[A-Z]{3,}", subject_street))
        shared = (comp_words & subj_words) - _DEV_AFFINITY_STOPWORDS
        if shared:
            score += 0.20
            reasons.append(f"street name overlap: {', '.join(sorted(shared))}")
            name_signal = True

    # Building/block name similarity — same stopword rule applies. A comp
    # named "The Mill House" does not share a development with "Mill
    # Street" just because both contain "MILL"; a comp named "Ingestre
    # Court" does share a genuine signal with "Ingestre Road" via "INGESTRE".
    comp_building = _extract_building_name(c.address)
    if comp_building:
        comp_bn = re.sub(r"[^A-Z0-9 ]", "", comp_building.upper()).strip()
        subj_bn = re.sub(r"[^A-Z0-9 ]", "", subject_street).strip()
        if comp_bn and subj_bn:
            comp_bw = set(comp_bn.split())
            subj_bw = set(subj_bn.split())
            shared_bw = (comp_bw & subj_bw) - _DEV_AFFINITY_STOPWORDS
            if shared_bw:
                score += 0.20
                reasons.append(f"building name overlap: {', '.join(sorted(shared_bw))}")
                name_signal = True

    # Estate/development name matching (manual override)
    if subject_estate_name:
        estate_norm = re.sub(r"[^A-Z0-9 ]", "", subject_estate_name.upper()).strip()
        estate_words = set(w for w in estate_norm.split() if len(w) >= 3)
        if estate_words:
            comp_full = _normalise_street(c.address or "") + " " + _normalise_street(c.street or "")
            comp_words_full = set(re.findall(r"[A-Z]{3,}", comp_full))
            shared_estate = estate_words & comp_words_full
            if shared_estate:
                score += 0.25
                reasons.append(f"estate name match: {', '.join(shared_estate)}")
                name_signal = True

    # Outcode-only comps require a name signal to qualify at all
    if postcode_tier == "outcode":
        if not name_signal:
            return 0.0, "same outcode only — no name signal"
        score += 0.05
        reasons.append("same outcode with name match")

    if not reasons:
        return 0.0, "no development affinity signals"

    return min(score, 1.0), "; ".join(reasons)


def _dev_comp_weight(c: ScoredComparable, affinity: float) -> float:
    """Weight for a development comparable: tier * recency * affinity."""
    tier_w = {"A": 5, "B": 4, "C": 3, "D": 2}.get(c.tier, 1)
    if c.age_days <= 365:
        recency_w = 4.0
    elif c.age_days <= 730:
        recency_w = 3.0
    elif c.age_days <= 1095:
        recency_w = 2.0
    else:
        recency_w = 1.0
    return tier_w * recency_w * affinity


def build_development_evidence_group(
    evidence: ComparableEvidence,
    subject_listing: PropertyListing,
    direct_group: EvidenceGroup = None,
    region: str = "England",
    estate_name: str = "",
) -> EvidenceGroup:
    """Build the Development Evidence group from scored comparables.

    A comparable qualifies as Development Evidence if:
    - NOT already in Direct Evidence (same street/building)
    - same estate, development, block, or closely related road cluster
    - compatible property type
    - sold within 5 years
    - has price data
    - has meaningful development affinity (score >= 0.20)
    """
    group = EvidenceGroup(
        name="Development Evidence",
        description="Same estate or development, compatible type, sold within 5 years",
    )

    subject_code = _subject_type_code(subject_listing)
    subject_sqm = subject_listing.floor_area_sqm or 0.0
    subject_street = _extract_subject_street(subject_listing)
    subject_addr_first = ""
    if subject_listing.address:
        parts = subject_listing.address.split(",")
        if parts:
            subject_addr_first = parts[0].strip()

    subject_postcode = subject_listing.postcode or ""
    subject_sector = postcode_sector(subject_postcode) if subject_postcode else ""
    subject_outcode = postcode_outcode(subject_postcode) if subject_postcode else ""

    # Collect IDs of direct evidence comps to exclude
    direct_ids = set()
    if direct_group and direct_group.comparables:
        for dc in direct_group.comparables:
            direct_ids.add(id(dc))

    all_comps = evidence.scored_comparables + evidence.context_only_comparables
    assessments: List[CompAssessment] = []
    dev_affinities: dict = {}  # comp id -> affinity score

    # Two-pass: first collect candidates passing non-type gates, then strict type filter
    affinity_candidates: List[ScoredComparable] = []
    affinity_assessments: List[CompAssessment] = []

    for c in all_comps:
        assessment = CompAssessment(comp=c)
        reasons = []

        # --- Gate 0: skip if already Direct Evidence ---
        if id(c) in direct_ids:
            reasons.append("rejected: already in Direct Evidence")
            assessment.reasons = reasons
            assessments.append(assessment)
            continue

        if _is_direct_comp(c, subject_street, subject_addr_first):
            if c.age_days <= MAX_DIRECT_AGE_DAYS:
                reasons.append("rejected: qualifies as Direct Evidence")
                assessment.reasons = reasons
                assessments.append(assessment)
                continue

        # --- Gate 1: recency (5 years) ---
        if c.age_days > MAX_DEV_AGE_DAYS:
            reasons.append(f"rejected: too old ({c.age_days} days, max {MAX_DEV_AGE_DAYS})")
            assessment.reasons = reasons
            assessments.append(assessment)
            continue

        # --- Gate 2: must have price ---
        if c.price <= 0:
            reasons.append("rejected: no price data")
            assessment.reasons = reasons
            assessments.append(assessment)
            continue

        # --- Gate 3: development affinity ---
        # A comp qualifies if its affinity score strictly exceeds 0.30, OR
        # it sits at the boundary but carries a genuinely strong signal
        # (same postcode, named estate match, or building/block match).
        # This stops weak combinations (e.g. sector + a single generic
        # word overlap) from sneaking in exactly at the threshold while
        # still admitting real same-block/same-development comps.
        subject_estate = estate_name or getattr(subject_listing, "override_estate_name", "") or ""
        affinity, affinity_reason = _development_affinity(
            c, subject_postcode, subject_street, subject_sector, subject_outcode,
            subject_estate_name=subject_estate,
        )
        qualifies = affinity > 0.30 or (affinity >= 0.30 and _has_strong_dev_signal(affinity_reason))
        if not qualifies:
            reasons.append(f"rejected: insufficient development affinity ({affinity:.2f}) — {affinity_reason}")
            assessment.reasons = reasons
            assessments.append(assessment)
            continue

        reasons.append(f"affinity: {affinity:.2f} — {affinity_reason}")
        if c.age_days <= 365:
            reasons.append(f"recency: {c.age_days} days (within 1 year)")
        elif c.age_days <= 730:
            reasons.append(f"recency: {c.age_days} days (within 2 years)")
        elif c.age_days <= 1095:
            reasons.append(f"recency: {c.age_days} days (within 3 years)")
        else:
            reasons.append(f"recency: {c.age_days} days (within 5 years)")

        # Passed affinity/recency/price — type filtering happens below
        assessment.reasons = reasons
        affinity_candidates.append(c)
        affinity_assessments.append(assessment)
        dev_affinities[id(c)] = affinity

    # --- Strict type filtering with fallback ---
    exact_comps = []
    compatible_comps = []
    unknown_comps = []
    incompatible_comps = []
    type_diag = {"exact": 0, "compatible": 0, "unknown": 0, "incompatible": 0, "excluded": 0}

    for c, assessment in zip(affinity_candidates, affinity_assessments):
        rel = is_property_type_compatible(subject_code, c.property_type_code)
        if rel == "exact":
            type_diag["exact"] += 1
            assessment.reasons.append(f"type: exact match ({c.property_type_code})")
            exact_comps.append(c)
        elif rel == "compatible":
            type_diag["compatible"] += 1
            assessment.reasons.append(f"type: compatible but downgraded ({c.property_type_code} vs {subject_code})")
            compatible_comps.append(c)
        elif rel == "unknown":
            # Type unrecorded — included at reduced weight (see
            # property_type_weight) but must NOT inflate the exact-match
            # count or make the group appear more type-verified than it is.
            type_diag["unknown"] += 1
            assessment.reasons.append("type: data incomplete — included at reduced weight, not counted as exact")
            unknown_comps.append(c)
        else:
            type_diag["incompatible"] += 1
            incompatible_comps.append(c)

    # Genuine evidence set: exact + compatible + unknown (unknown is
    # already downweighted via property_type_weight, so it's safe to treat
    # as genuine for fallback-admission purposes).
    genuine_comps: List[ScoredComparable] = exact_comps + compatible_comps + unknown_comps
    dev_comps: List[ScoredComparable] = list(genuine_comps)
    fallback_used = False
    fallback_admitted: List[ScoredComparable] = []
    fallback_excluded_outliers: List[ScoredComparable] = []

    if len(dev_comps) < 3 and incompatible_comps:
        fallback_admitted, fallback_excluded_outliers = _admit_fallback_comps(
            genuine_comps, incompatible_comps, affinity_assessments, region,
        )
        dev_comps.extend(fallback_admitted)
        fallback_used = len(fallback_admitted) > 0
        type_diag["excluded"] = len(fallback_excluded_outliers)
    else:
        type_diag["excluded"] = len(incompatible_comps)
        for c in incompatible_comps:
            for assessment in affinity_assessments:
                if assessment.comp is c:
                    assessment.reasons.append(
                        f"rejected: incompatible type ({c.property_type_code} vs {subject_code})"
                    )
                    break

    for c, assessment in zip(affinity_candidates, affinity_assessments):
        if c in dev_comps:
            assessment.included = True
            assessment.reasons.append(f"included: adj_price={c.adjusted_price:,.0f}, tier={c.tier}")
        assessments.append(assessment)

    group.type_exact_count = type_diag["exact"]
    group.type_compatible_count = type_diag["compatible"]
    group.unknown_type_count = type_diag["unknown"]
    group.type_incompatible_fallback_count = len(fallback_admitted) if fallback_used else 0
    group.type_excluded_count = type_diag["excluded"]

    if fallback_used:
        fb_count = group.type_incompatible_fallback_count
        group.weaknesses.append(
            f"{fb_count} incompatible type(s) included at reduced weight "
            f"(fallback — fewer than 3 same-type comps available)"
        )

    if fallback_excluded_outliers:
        group.weaknesses.append(
            f"{len(fallback_excluded_outliers)} incompatible-type comp(s) excluded as outliers "
            f"(more than 50% from the genuine median price) — kept as contextual only, "
            f"not used in valuation"
        )

    if not dev_comps:
        group.weaknesses.append("No development-level comparables found within 5 years")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- HPI-adjust prices ---
    for c in dev_comps:
        if c.adjusted_price <= 0 and c.price > 0 and c.date:
            c.adjusted_price = adjust_price_to_current(c.price, c.date, region)

    dev_comps = [c for c in dev_comps if c.adjusted_price > 0]
    if not dev_comps:
        group.weaknesses.append("Development comparables found but HPI adjustment failed for all")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- Populate the group ---
    group.comparables = dev_comps
    group.comp_count = len(dev_comps)

    prices = np.array([c.adjusted_price for c in dev_comps])

    # Median
    group.median_value = round(float(np.median(prices)), -2)

    # Weighted mean: tier * recency * affinity * size_similarity * type_compatibility
    weights = []
    for c in dev_comps:
        aff = dev_affinities.get(id(c), 0.20)
        w = _dev_comp_weight(c, aff)
        w *= property_type_weight(subject_code, c.property_type_code)
        if subject_sqm > 0 and c.floor_area_sqm > 0:
            w *= _size_similarity_weight(c.floor_area_sqm, subject_sqm)
        weights.append(w)
    weights = np.array(weights, dtype=float)
    w_sum = weights.sum()
    if w_sum > 0:
        group.weighted_mean = round(float(np.sum(prices * weights / w_sum)), -2)
    else:
        group.weighted_mean = group.median_value

    # Valuation: weighted mean as primary
    group.valuation = group.weighted_mean
    if len(dev_comps) >= 5:
        group.valuation_low = round(float(np.percentile(prices, 25)), -2)
        group.valuation_high = round(float(np.percentile(prices, 75)), -2)
    elif len(dev_comps) >= 3:
        group.valuation_low = round(float(np.percentile(prices, 20)), -2)
        group.valuation_high = round(float(np.percentile(prices, 80)), -2)
    elif len(dev_comps) == 2:
        group.valuation_low = round(float(prices.min()), -2)
        group.valuation_high = round(float(prices.max()), -2)
    else:
        group.valuation_low = round(float(prices[0] * 0.92), -2)
        group.valuation_high = round(float(prices[0] * 1.08), -2)

    # Per-sqm diagnostics
    if subject_sqm > 0:
        sqm_comps = [c for c in dev_comps if c.floor_area_sqm > 0]
        if sqm_comps:
            psm_values = [c.adjusted_price / c.floor_area_sqm for c in sqm_comps]
            group.median_price_per_sqm = round(float(np.median(psm_values)), 0)
            sqm_weights = np.array([
                _dev_comp_weight(c, dev_affinities.get(id(c), 0.20))
                * _size_similarity_weight(c.floor_area_sqm, subject_sqm)
                for c in sqm_comps
            ], dtype=float)
            sqm_w_sum = sqm_weights.sum()
            if sqm_w_sum > 0:
                psm_arr = np.array(psm_values)
                group.weighted_mean_price_per_sqm = round(
                    float(np.sum(psm_arr * sqm_weights / sqm_w_sum)), 0
                )

    # Representative: highest affinity * quality, most recent on ties
    best = max(dev_comps, key=lambda c: (
        dev_affinities.get(id(c), 0) * c.quality_score, -c.age_days
    ))
    group.representative = best
    best_aff = dev_affinities.get(id(best), 0)
    group.representative_reason = (
        f"Tier {best.tier}, {best.age_days}d old, "
        f"affinity {best_aff:.2f}, {best.adjusted_price:,.0f} adj."
    )

    # Confidence
    _assess_dev_confidence(group, dev_comps, dev_affinities, subject_code, subject_sqm)

    # Strengths and weaknesses
    _assess_dev_quality(group, dev_comps, dev_affinities, assessments, subject_sqm)

    # Evidence quality and status
    group.evidence_quality = _calculate_evidence_quality(group)
    group.evidence_status, group.evidence_status_reason = _calculate_evidence_status(group)

    return group


def _assess_dev_confidence(
    group: EvidenceGroup,
    comps: List[ScoredComparable],
    affinities: dict,
    subject_code: str,
    subject_sqm: float,
) -> None:
    """Set confidence score (0-100) and label for the development evidence group."""
    score = 0
    drivers = []

    n = len(comps)
    if n >= 8:
        score += 25
        drivers.append(f"{n} development comps (strong)")
    elif n >= 4:
        score += 20
        drivers.append(f"{n} development comps (moderate)")
    elif n >= 2:
        score += 15
        drivers.append(f"{n} development comps (limited)")
    elif n == 1:
        score += 8
        drivers.append("1 development comp only")

    # Affinity quality
    aff_values = [affinities.get(id(c), 0) for c in comps]
    mean_aff = sum(aff_values) / len(aff_values) if aff_values else 0
    if mean_aff >= 0.50:
        score += 20
        drivers.append(f"strong avg affinity ({mean_aff:.2f})")
    elif mean_aff >= 0.35:
        score += 15
        drivers.append(f"moderate avg affinity ({mean_aff:.2f})")
    elif mean_aff >= 0.20:
        score += 10
        drivers.append(f"weak avg affinity ({mean_aff:.2f})")

    # Recency
    recent = sum(1 for c in comps if c.age_days <= 730)
    if recent >= 3:
        score += 15
        drivers.append(f"{recent} sold within 2 years")
    elif recent >= 1:
        score += 8
        drivers.append(f"{recent} sold within 2 years")
    else:
        drivers.append("no sales within 2 years")

    # Type match
    exact_type = sum(1 for c in comps if c.property_type_code == subject_code)
    if exact_type == n and n > 0:
        score += 10
        drivers.append("all exact type match")
    elif exact_type > 0:
        score += 7
        drivers.append(f"{exact_type}/{n} exact type match")
    else:
        score += 3
        drivers.append("compatible types only")

    # Price consistency
    if n >= 2:
        prices = [c.adjusted_price for c in comps]
        cv = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 1.0
        if cv < 0.15:
            score += 15
            drivers.append(f"tight spread (CV {cv:.0%})")
        elif cv < 0.25:
            score += 10
            drivers.append(f"moderate spread (CV {cv:.0%})")
        elif cv < 0.40:
            score += 5
            drivers.append(f"wide spread (CV {cv:.0%})")
        else:
            drivers.append(f"very wide spread (CV {cv:.0%})")

    # Floor area data
    if subject_sqm > 0:
        sqm_comps = sum(1 for c in comps if c.floor_area_sqm > 0)
        if sqm_comps == n and n > 0:
            score += 10
            drivers.append("all comps have floor area data")
        elif sqm_comps > 0:
            score += 5
            drivers.append(f"{sqm_comps}/{n} comps have floor area data")

    # Size similarity bonus (when floor area available)
    if subject_sqm > 0:
        similar = sum(
            1 for c in comps
            if c.floor_area_sqm > 0 and _size_similarity_weight(c.floor_area_sqm, subject_sqm) >= 0.70
        )
        if similar >= 3:
            score += 5
            drivers.append(f"{similar} comps with similar floor area")

    group.confidence_score = min(score, 100)
    if score >= 65:
        group.confidence_label = "High"
    elif score >= 40:
        group.confidence_label = "Medium"
    elif score >= 20:
        group.confidence_label = "Low"
    else:
        group.confidence_label = "Very Low"
    group.confidence_drivers = drivers


def _assess_dev_quality(
    group: EvidenceGroup,
    comps: List[ScoredComparable],
    affinities: dict,
    assessments: List[CompAssessment],
    subject_sqm: float,
) -> None:
    """Populate strengths and weaknesses for the development evidence group."""
    n = len(comps)

    # Strengths
    same_pc = sum(1 for c in comps if affinities.get(id(c), 0) >= 0.50)
    if same_pc >= 2:
        group.strengths.append(f"{same_pc} comps share same postcode — likely same development")
    elif same_pc == 1:
        group.strengths.append("1 comp shares same postcode")

    if n >= 5:
        group.strengths.append(f"{n} development-level comparables — good sample size")
    elif n >= 3:
        group.strengths.append(f"{n} development-level comparables")

    recent = [c for c in comps if c.age_days <= 365]
    if recent:
        group.strengths.append(f"{len(recent)} sale(s) within 1 year")

    tier_ab = [c for c in comps if c.tier in ("A", "B")]
    if tier_ab:
        group.strengths.append(f"{len(tier_ab)} Tier A/B comparable(s)")

    if subject_sqm > 0:
        similar = [
            c for c in comps
            if c.floor_area_sqm > 0
            and _size_similarity_weight(c.floor_area_sqm, subject_sqm) >= 0.70
        ]
        if similar:
            group.strengths.append(f"{len(similar)} comp(s) with similar floor area")

    # Weaknesses
    if n <= 2:
        group.weaknesses.append(f"Only {n} development comp(s) — limited triangulation")

    old_comps = [c for c in comps if c.age_days > 1095]
    if old_comps:
        group.weaknesses.append(
            f"{len(old_comps)} comp(s) older than 3 years — market may have shifted"
        )

    low_aff = [c for c in comps if affinities.get(id(c), 0) < 0.35]
    if low_aff:
        group.weaknesses.append(
            f"{len(low_aff)} comp(s) with weak development affinity — may not be same estate"
        )

    if subject_sqm > 0:
        no_sqm = [c for c in comps if c.floor_area_sqm <= 0]
        if no_sqm:
            group.weaknesses.append(
                f"{len(no_sqm)} comp(s) missing floor area data"
            )

        diff_size = [
            c for c in comps
            if c.floor_area_sqm > 0
            and _size_similarity_weight(c.floor_area_sqm, subject_sqm) < 0.40
        ]
        if diff_size:
            group.weaknesses.append(
                f"{len(diff_size)} comp(s) with very different floor area"
            )

    # Price spread
    if n >= 2:
        prices = [c.adjusted_price for c in comps]
        cv = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 1.0
        if cv > 0.35:
            group.weaknesses.append(
                f"High price variation (CV {cv:.0%}) — development may have mixed property sizes"
            )


# ---------------------------------------------------------------------------
# Placeholder group builders (Local Market, Area Market)
# ---------------------------------------------------------------------------

MAX_LOCAL_AGE_DAYS = 1825  # 5 years

# IQR multiplier for outlier detection
_OUTLIER_IQR_MULT = 2.0


def build_local_market_evidence_group(
    evidence: ComparableEvidence,
    subject_listing: PropertyListing,
    direct_group: EvidenceGroup = None,
    development_group: EvidenceGroup = None,
    region: str = "England",
) -> EvidenceGroup:
    """Build Local Market Evidence from same-sector, compatible-type comps.

    A comparable qualifies if:
    - NOT already in Direct or Development Evidence
    - same postcode sector as subject
    - compatible property type
    - sold within 5 years
    - has price data
    - not an extreme price outlier (IQR fence)
    """
    group = EvidenceGroup(
        name="Local Market Evidence",
        description="Same postcode sector, compatible type, sold within 5 years",
    )

    subject_code = _subject_type_code(subject_listing)
    subject_sqm = subject_listing.floor_area_sqm or 0.0
    subject_postcode = subject_listing.postcode or ""
    subject_sector = postcode_sector(subject_postcode) if subject_postcode else ""

    if not subject_sector:
        group.weaknesses.append("No postcode sector available")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    subj_sector_norm = subject_sector.replace(" ", "").upper()

    # Collect IDs of comps already in Direct or Development
    exclude_ids = set()
    if direct_group and direct_group.comparables:
        for c in direct_group.comparables:
            exclude_ids.add(id(c))
    if development_group and development_group.comparables:
        for c in development_group.comparables:
            exclude_ids.add(id(c))

    all_comps = evidence.scored_comparables + evidence.context_only_comparables
    candidates: List[ScoredComparable] = []

    for c in all_comps:
        # Gate 0: not already used
        if id(c) in exclude_ids:
            continue

        # Gate 1: same sector
        comp_sector = postcode_sector(c.postcode).replace(" ", "").upper() if c.postcode else ""
        if comp_sector != subj_sector_norm:
            continue

        # Gate 2: recency
        if c.age_days > MAX_LOCAL_AGE_DAYS:
            continue

        # Gate 3: type compatibility
        type_ok, _ = _is_type_compatible(c.property_type_code, subject_code)
        if not type_ok:
            continue

        # Gate 4: must have price
        if c.price <= 0:
            continue

        candidates.append(c)

    if not candidates:
        group.weaknesses.append("No same-sector comparables found after excluding Direct/Development")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- HPI-adjust ---
    for c in candidates:
        if c.adjusted_price <= 0 and c.price > 0 and c.date:
            c.adjusted_price = adjust_price_to_current(c.price, c.date, region)

    candidates = [c for c in candidates if c.adjusted_price > 0]
    if not candidates:
        group.weaknesses.append("Local comps found but HPI adjustment failed for all")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- Outlier removal (IQR fence) ---
    prices_arr = np.array([c.adjusted_price for c in candidates])
    q1 = float(np.percentile(prices_arr, 25))
    q3 = float(np.percentile(prices_arr, 75))
    iqr = q3 - q1
    if iqr > 0:
        lo_fence = q1 - _OUTLIER_IQR_MULT * iqr
        hi_fence = q3 + _OUTLIER_IQR_MULT * iqr
        pre_outlier = len(candidates)
        candidates = [c for c in candidates if lo_fence <= c.adjusted_price <= hi_fence]
        outliers_removed = pre_outlier - len(candidates)
    else:
        outliers_removed = 0

    if not candidates:
        group.weaknesses.append("All local comps removed as outliers")
        group.confidence_label = "None"
        group.confidence_score = 0
        return group

    # --- Populate group ---
    group.comparables = candidates
    group.comp_count = len(candidates)

    # Type diagnostics (Local Market uses broad gate — no fallback admitted)
    for c in candidates:
        if c.property_type_code == subject_code:
            group.type_exact_count += 1
        else:
            group.type_compatible_count += 1

    prices = np.array([c.adjusted_price for c in candidates])
    group.median_value = round(float(np.median(prices)), -2)

    # Weighted mean: tier * recency * size_similarity
    weights = []
    for c in candidates:
        w = _local_comp_weight(c)
        if subject_sqm > 0 and c.floor_area_sqm > 0:
            w *= _size_similarity_weight(c.floor_area_sqm, subject_sqm)
        weights.append(w)
    weights = np.array(weights, dtype=float)
    w_sum = weights.sum()
    if w_sum > 0:
        group.weighted_mean = round(float(np.sum(prices * weights / w_sum)), -2)
    else:
        group.weighted_mean = group.median_value

    group.valuation = group.weighted_mean

    # Range
    if len(candidates) >= 5:
        group.valuation_low = round(float(np.percentile(prices, 25)), -2)
        group.valuation_high = round(float(np.percentile(prices, 75)), -2)
    elif len(candidates) >= 3:
        group.valuation_low = round(float(np.percentile(prices, 20)), -2)
        group.valuation_high = round(float(np.percentile(prices, 80)), -2)
    elif len(candidates) == 2:
        group.valuation_low = round(float(prices.min()), -2)
        group.valuation_high = round(float(prices.max()), -2)
    else:
        group.valuation_low = round(float(prices[0] * 0.90), -2)
        group.valuation_high = round(float(prices[0] * 1.10), -2)

    # Per-sqm diagnostics
    if subject_sqm > 0:
        sqm_comps = [c for c in candidates if c.floor_area_sqm > 0]
        if sqm_comps:
            psm_values = [c.adjusted_price / c.floor_area_sqm for c in sqm_comps]
            group.median_price_per_sqm = round(float(np.median(psm_values)), 0)
            sqm_weights = np.array([
                _local_comp_weight(c) * _size_similarity_weight(c.floor_area_sqm, subject_sqm)
                for c in sqm_comps
            ], dtype=float)
            sqm_w_sum = sqm_weights.sum()
            if sqm_w_sum > 0:
                psm_arr = np.array(psm_values)
                group.weighted_mean_price_per_sqm = round(
                    float(np.sum(psm_arr * sqm_weights / sqm_w_sum)), 0
                )

    # Representative: best tier, most recent, closest size
    def _rep_key(c):
        tier_rank = {"A": 4, "B": 3, "C": 2, "D": 1}.get(c.tier, 0)
        size_sim = _size_similarity_weight(c.floor_area_sqm, subject_sqm) if (subject_sqm > 0 and c.floor_area_sqm > 0) else 0.5
        return (tier_rank, size_sim, -c.age_days)

    best = max(candidates, key=_rep_key)
    group.representative = best
    group.representative_reason = (
        f"Tier {best.tier}, {best.age_days}d old, {best.adjusted_price:,.0f} adj."
    )

    # Confidence
    _assess_local_confidence(group, candidates, subject_code, subject_sqm, outliers_removed)

    # Quality
    _assess_local_quality(group, candidates, subject_sqm, outliers_removed)

    # Evidence quality and status
    group.evidence_quality = _calculate_evidence_quality(group)
    group.evidence_status, group.evidence_status_reason = _calculate_evidence_status(group)

    return group


def _local_comp_weight(c: ScoredComparable) -> float:
    """Weight for a local market comparable: tier * recency."""
    tier_w = {"A": 4, "B": 3, "C": 2, "D": 1.5}.get(c.tier, 1)
    if c.age_days <= 365:
        recency_w = 3.0
    elif c.age_days <= 730:
        recency_w = 2.0
    elif c.age_days <= 1095:
        recency_w = 1.5
    else:
        recency_w = 1.0
    return tier_w * recency_w


def _assess_local_confidence(
    group: EvidenceGroup,
    comps: List[ScoredComparable],
    subject_code: str,
    subject_sqm: float,
    outliers_removed: int,
) -> None:
    """Set confidence score (0-100) for local market evidence."""
    score = 0
    drivers = []
    n = len(comps)

    # Count
    if n >= 15:
        score += 25
        drivers.append(f"{n} local comps (strong sample)")
    elif n >= 8:
        score += 20
        drivers.append(f"{n} local comps (good sample)")
    elif n >= 4:
        score += 15
        drivers.append(f"{n} local comps (moderate)")
    elif n >= 2:
        score += 10
        drivers.append(f"{n} local comps (limited)")
    else:
        score += 5
        drivers.append("1 local comp only")

    # Recency
    recent = sum(1 for c in comps if c.age_days <= 730)
    if recent >= 5:
        score += 15
        drivers.append(f"{recent} sold within 2 years")
    elif recent >= 2:
        score += 10
        drivers.append(f"{recent} sold within 2 years")
    elif recent >= 1:
        score += 5
        drivers.append(f"{recent} sold within 2 years")
    else:
        drivers.append("no sales within 2 years")

    # Type match
    exact_type = sum(1 for c in comps if c.property_type_code == subject_code)
    if exact_type == n and n > 0:
        score += 10
        drivers.append("all exact type match")
    elif exact_type > n * 0.5:
        score += 7
        drivers.append(f"{exact_type}/{n} exact type match")
    elif exact_type > 0:
        score += 5
        drivers.append(f"{exact_type}/{n} exact type match")
    else:
        score += 2
        drivers.append("compatible types only")

    # Price consistency
    if n >= 3:
        prices = [c.adjusted_price for c in comps]
        cv = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 1.0
        if cv < 0.15:
            score += 15
            drivers.append(f"tight spread (CV {cv:.0%})")
        elif cv < 0.25:
            score += 10
            drivers.append(f"moderate spread (CV {cv:.0%})")
        elif cv < 0.40:
            score += 5
            drivers.append(f"wide spread (CV {cv:.0%})")
        else:
            drivers.append(f"very wide spread (CV {cv:.0%})")

    # Floor area data
    if subject_sqm > 0:
        sqm_comps = sum(1 for c in comps if c.floor_area_sqm > 0)
        if sqm_comps >= n * 0.7 and n > 0:
            score += 10
            drivers.append(f"{sqm_comps}/{n} have floor area — size-adjusted weighting")
        elif sqm_comps > 0:
            score += 5
            drivers.append(f"{sqm_comps}/{n} have floor area data")
        else:
            drivers.append("no floor area data — weighting by tier/recency only")

    # Size similarity bonus
    if subject_sqm > 0:
        similar = sum(
            1 for c in comps
            if c.floor_area_sqm > 0 and _size_similarity_weight(c.floor_area_sqm, subject_sqm) >= 0.70
        )
        if similar >= 3:
            score += 5
            drivers.append(f"{similar} comps with similar floor area")

    # Outlier penalty
    if outliers_removed > 0:
        drivers.append(f"{outliers_removed} outlier(s) removed")

    # Local market is inherently weaker — cap at 75
    group.confidence_score = min(score, 75)
    if group.confidence_score >= 55:
        group.confidence_label = "High"
    elif group.confidence_score >= 35:
        group.confidence_label = "Medium"
    elif group.confidence_score >= 15:
        group.confidence_label = "Low"
    else:
        group.confidence_label = "Very Low"
    group.confidence_drivers = drivers


def _assess_local_quality(
    group: EvidenceGroup,
    comps: List[ScoredComparable],
    subject_sqm: float,
    outliers_removed: int,
) -> None:
    """Populate strengths and weaknesses for local market evidence."""
    n = len(comps)

    # Strengths
    if n >= 10:
        group.strengths.append(f"{n} local comps — strong market sample")
    elif n >= 5:
        group.strengths.append(f"{n} local comps — reasonable market sample")
    elif n >= 2:
        group.strengths.append(f"{n} local comps available")

    recent = [c for c in comps if c.age_days <= 365]
    if len(recent) >= 3:
        group.strengths.append(f"{len(recent)} sold within 1 year — current market data")
    elif recent:
        group.strengths.append(f"{len(recent)} sale(s) within 1 year")

    if subject_sqm > 0:
        similar = [
            c for c in comps
            if c.floor_area_sqm > 0
            and _size_similarity_weight(c.floor_area_sqm, subject_sqm) >= 0.70
        ]
        if similar:
            group.strengths.append(f"{len(similar)} comp(s) with similar floor area")

    tier_ab = [c for c in comps if c.tier in ("A", "B")]
    if tier_ab:
        group.strengths.append(f"{len(tier_ab)} Tier A/B comparable(s)")

    # Weaknesses
    group.weaknesses.append("Local market — not same street or development")

    if n < 5:
        group.weaknesses.append(f"Only {n} local comp(s) — thin market data")

    old_comps = [c for c in comps if c.age_days > 1095]
    if old_comps:
        group.weaknesses.append(
            f"{len(old_comps)} comp(s) older than 3 years"
        )

    if subject_sqm > 0:
        no_sqm = [c for c in comps if c.floor_area_sqm <= 0]
        if no_sqm and len(no_sqm) > n * 0.5:
            group.weaknesses.append(
                f"{len(no_sqm)}/{n} comps missing floor area — size adjustment limited"
            )

    if outliers_removed > 0:
        group.weaknesses.append(f"{outliers_removed} extreme outlier(s) excluded")

    if n >= 3:
        prices = [c.adjusted_price for c in comps]
        cv = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 1.0
        if cv > 0.35:
            group.weaknesses.append(
                f"High price variation (CV {cv:.0%}) — mixed property characteristics"
            )


def build_area_market_evidence_group(
    evidence: ComparableEvidence,
    subject_listing: PropertyListing,
    region: str = "England",
) -> EvidenceGroup:
    """Placeholder — Area Market Evidence not yet implemented."""
    return EvidenceGroup(
        name="Area Market Evidence",
        description="Wider postcode area, broader type matching (not yet implemented)",
        confidence_label="None",
        confidence_score=0,
    )


# ---------------------------------------------------------------------------
# Evidence blender
# ---------------------------------------------------------------------------

_WEIGHT_PROFILES = {
    "High":   {"Direct Evidence": 0.75, "Development Evidence": 0.20, "Local Market Evidence": 0.05, "Area Market Evidence": 0.00},
    "Medium": {"Direct Evidence": 0.55, "Development Evidence": 0.30, "Local Market Evidence": 0.15, "Area Market Evidence": 0.00},
    "Low":    {"Direct Evidence": 0.35, "Development Evidence": 0.40, "Local Market Evidence": 0.20, "Area Market Evidence": 0.05},
}


def blend_evidence(
    direct: EvidenceGroup,
    development: EvidenceGroup,
    local_market: EvidenceGroup,
    area_market: EvidenceGroup,
    subject_listing: PropertyListing,
) -> FinalValuation:
    """Blend the four evidence groups into a final valuation.

    Weight profile is selected by Direct Evidence confidence. Groups with
    no valuation have their weight redistributed proportionally to the
    remaining groups.
    """
    asking = subject_listing.asking_price or 0.0
    sqm = subject_listing.floor_area_sqm or 0.0

    final = FinalValuation(asking_price=asking)
    recon = Reconciliation()

    groups = {
        "Direct Evidence": direct,
        "Development Evidence": development,
        "Local Market Evidence": local_market,
        "Area Market Evidence": area_market,
    }

    active = {name: g for name, g in groups.items() if g.comp_count > 0 and g.valuation > 0}

    # --- No evidence at all ---
    if not active:
        final.valuation_status = "Insufficient evidence"
        final.sufficient_evidence = False
        final.confidence_score = 0
        final.confidence_label = "None"
        final.warnings.append("No evidence groups produced a valuation")
        recon.method = "none — no evidence"
        final.reconciliation = recon
        return final

    # --- Select weight profile ---
    profile_key = "no-direct"
    if direct.comp_count > 0 and direct.valuation > 0:
        profile_key = direct.confidence_label
        if profile_key not in _WEIGHT_PROFILES:
            profile_key = "Low"
        raw_weights = dict(_WEIGHT_PROFILES[profile_key])
        recon.dominant_group = "Direct Evidence"
    else:
        # Direct absent — development dominates if viable
        if development.comp_count > 0 and development.valuation > 0:
            if development.confidence_label in ("High", "Medium"):
                raw_weights = {
                    "Direct Evidence": 0.00,
                    "Development Evidence": 0.70,
                    "Local Market Evidence": 0.25,
                    "Area Market Evidence": 0.05,
                }
                recon.dominant_group = "Development Evidence"
            else:
                final.valuation_status = "Weak evidence"
                final.sufficient_evidence = False
                final.confidence_score = max(development.confidence_score - 10, 0)
                final.confidence_label = "Very Low"
                final.warnings.append(
                    "No Direct Evidence and Development confidence is low"
                )
                # Still produce a value but flag it heavily
                raw_weights = {
                    "Direct Evidence": 0.00,
                    "Development Evidence": 0.60,
                    "Local Market Evidence": 0.30,
                    "Area Market Evidence": 0.10,
                }
                recon.dominant_group = "Development Evidence (weak)"
        else:
            final.valuation_status = "Insufficient evidence"
            final.sufficient_evidence = False
            final.confidence_score = 0
            final.confidence_label = "None"
            final.warnings.append(
                "No Direct or Development Evidence — cannot produce reliable valuation"
            )
            recon.method = "none — insufficient evidence"
            final.reconciliation = recon
            return final

    # --- Redistribute weights from empty groups ---
    effective_weights = {}
    dead_weight = 0.0
    live_weight = 0.0
    for name, w in raw_weights.items():
        if name in active:
            effective_weights[name] = w
            live_weight += w
        else:
            dead_weight += w

    if live_weight > 0 and dead_weight > 0:
        for name in effective_weights:
            effective_weights[name] += dead_weight * (effective_weights[name] / live_weight)

    # --- Apply evidence status authority ---
    # STRONG: full profile weight (1.0)
    # WEAK: reduced authority (0.60)
    # FALLBACK_ONLY: near-zero authority (0.05)
    # EMPTY: already excluded from active
    _STATUS_AUTHORITY = {"STRONG": 1.0, "WEAK": 0.60, "FALLBACK_ONLY": 0.05, "EMPTY": 0.0}
    status_factors = {}
    for name in effective_weights:
        g = active[name]
        authority = _STATUS_AUTHORITY.get(g.evidence_status, 0.60)
        status_factors[name] = authority
        effective_weights[name] *= authority

    # Normalise (after status adjustment)
    total_w = sum(effective_weights.values())
    if total_w > 0:
        for name in effective_weights:
            effective_weights[name] /= total_w

    recon.group_weights = {name: round(w, 4) for name, w in effective_weights.items()}
    recon.assumptions.append(
        "Evidence status: " + ", ".join(
            f"{n}={active[n].evidence_status}(×{status_factors[n]:.2f})" for n in status_factors
        )
    )
    recon.method = f"weighted blend — profile '{profile_key if direct.comp_count > 0 else 'no-direct'}' + evidence status"

    # --- Assign weights back to groups ---
    for name, g in groups.items():
        g.weight_in_final = effective_weights.get(name, 0.0)

    # --- Blended value ---
    blended = sum(
        active[name].valuation * effective_weights[name]
        for name in effective_weights if name in active
    )
    final.fair_value_balanced = round(blended, -2)

    # --- Conservative: weighted blend of low ends ---
    conservative = sum(
        active[name].valuation_low * effective_weights[name]
        for name in effective_weights if name in active
    )
    final.fair_value_conservative = round(conservative, -2)

    # --- Aggressive: weighted blend of high ends ---
    aggressive = sum(
        active[name].valuation_high * effective_weights[name]
        for name in effective_weights if name in active
    )
    final.fair_value_aggressive = round(aggressive, -2)

    # --- Evidence conflict detection ---
    conflicts = []
    if direct.comp_count > 0 and direct.valuation > 0 and development.comp_count > 0 and development.valuation > 0:
        mid = (direct.valuation + development.valuation) / 2
        if mid > 0:
            diff_pct = abs(direct.valuation - development.valuation) / mid
            if diff_pct > 0.25:
                conflicts.append(
                    f"Major conflict: Direct ({direct.valuation:,.0f}) vs Development "
                    f"({development.valuation:,.0f}) differ by {diff_pct:.0%}"
                )
            elif diff_pct > 0.15:
                conflicts.append(
                    f"Moderate conflict: Direct ({direct.valuation:,.0f}) vs Development "
                    f"({development.valuation:,.0f}) differ by {diff_pct:.0%}"
                )
    recon.conflicts = conflicts

    # --- Final confidence ---
    if not final.confidence_label:
        _assess_blended_confidence(final, groups, active, effective_weights, conflicts)

    # --- Valuation status ---
    if not final.valuation_status:
        if final.confidence_score >= 65:
            final.valuation_status = "Reliable"
        elif final.confidence_score >= 40:
            final.valuation_status = "Usable with caution"
        elif final.confidence_score >= 20:
            final.valuation_status = "Weak evidence"
        else:
            final.valuation_status = "Insufficient evidence"
            final.sufficient_evidence = False

    # --- Gap analysis ---
    if asking > 0 and final.fair_value_balanced > 0:
        final.asking_vs_fair_gap = round(asking - final.fair_value_balanced, -2)
        final.asking_vs_fair_gap_pct = round(
            (asking - final.fair_value_balanced) / final.fair_value_balanced * 100, 1
        )

    # --- Per-sqm ---
    if sqm > 0:
        if asking > 0:
            final.price_per_sqm_asking = round(asking / sqm, 0)
        if final.fair_value_balanced > 0:
            final.price_per_sqm_fair = round(final.fair_value_balanced / sqm, 0)

    # --- Explanation ---
    explanation_parts = []
    for name in ["Direct Evidence", "Development Evidence", "Local Market Evidence", "Area Market Evidence"]:
        g = groups[name]
        w = effective_weights.get(name, 0)
        if w > 0 and g.comp_count > 0:
            explanation_parts.append(
                f"{name}: {g.valuation:,.0f} ({g.confidence_label}, {w:.0%} weight, {g.comp_count} comps)"
            )
    if conflicts:
        explanation_parts.extend(conflicts)
    explanation_parts.append(
        f"Blended fair value: {final.fair_value_balanced:,.0f} "
        f"(range {final.fair_value_conservative:,.0f}–{final.fair_value_aggressive:,.0f})"
    )
    final.valuation_method = " | ".join(explanation_parts)

    final.reconciliation = recon
    return final


def _assess_blended_confidence(
    final: FinalValuation,
    groups: dict,
    active: dict,
    weights: dict,
    conflicts: list,
) -> None:
    """Set overall confidence for the blended valuation."""
    score = 0.0
    drivers = []

    for name, w in weights.items():
        if name in active:
            g = active[name]
            score += g.confidence_score * w
            drivers.append(f"{name}: {g.confidence_label} ({g.confidence_score})")

    # Penalty for major conflicts
    for c in conflicts:
        if "Major" in c:
            score *= 0.75
            drivers.append("major conflict penalty (-25%)")
        elif "Moderate" in c:
            score *= 0.90
            drivers.append("moderate conflict penalty (-10%)")

    # Bonus for multiple active groups
    n_active = len(active)
    if n_active >= 3:
        score = min(score + 10, 100)
        drivers.append("3+ active evidence groups (+10)")
    elif n_active == 1:
        score *= 0.85
        drivers.append("single evidence group penalty (-15%)")

    final.confidence_score = min(round(score), 100)
    if final.confidence_score >= 65:
        final.confidence_label = "High"
    elif final.confidence_score >= 40:
        final.confidence_label = "Medium"
    elif final.confidence_score >= 20:
        final.confidence_label = "Low"
    else:
        final.confidence_label = "Very Low"
    final.confidence_drivers = drivers


def run_v2_valuation(
    evidence: ComparableEvidence,
    subject_listing: PropertyListing,
    region: str = "England",
) -> ValuationEvidence:
    """Run the full V2 valuation pipeline: build groups, then blend."""
    result = ValuationEvidence(
        subject_postcode=subject_listing.postcode or "",
        subject_property_type=subject_listing.property_type or "",
        subject_bedrooms=subject_listing.bedrooms or 0,
        subject_floor_area_sqm=subject_listing.floor_area_sqm or 0.0,
        subject_floor_area_source=subject_listing.floor_area_source or "",
        subject_tenure=subject_listing.tenure or "",
        total_comparables=len(evidence.scored_comparables) + len(evidence.context_only_comparables),
    )

    # Build evidence groups
    result.direct = build_direct_evidence_group(evidence, subject_listing, region)
    result.development = build_development_evidence_group(
        evidence, subject_listing, direct_group=result.direct, region=region,
        estate_name=getattr(subject_listing, "override_estate_name", ""),
    )
    result.local_market = build_local_market_evidence_group(
        evidence, subject_listing,
        direct_group=result.direct, development_group=result.development,
        region=region,
    )
    result.area_market = build_area_market_evidence_group(evidence, subject_listing, region)

    # Blend
    result.final = blend_evidence(
        result.direct, result.development, result.local_market, result.area_market,
        subject_listing,
    )

    return result
