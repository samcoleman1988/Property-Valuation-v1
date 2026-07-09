"""Comparable evidence engine.

Fetches Land Registry sold prices, applies hard gates to exclude
irrelevant sales, then assigns each comparable to a quality tier
(A/B/C/D/Excluded). Only tiers A-C feed the valuation.

Every comparable carries a tier, quality score, and human-readable
explanation of why it was included or excluded.
"""

import re
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

from geopy.distance import geodesic

from .config import get_config, ComparableWeights, ComparableThresholds
from .utils import (
    postcode_outcode, postcode_sector, cache_key, get_cached, set_cache,
    safe_float, safe_int,
)

API_BASE = "https://landregistry.data.gov.uk/data/ppi"

PROPERTY_TYPE_MAP = {
    "D": "Detached",
    "S": "Semi-Detached",
    "T": "Terraced",
    "F": "Flat/Maisonette",
    "O": "Other",
}

PROPERTY_TYPE_REVERSE = {}
for _code, _name in PROPERTY_TYPE_MAP.items():
    PROPERTY_TYPE_REVERSE[_name.lower()] = _code
PROPERTY_TYPE_REVERSE.update({
    "detached house": "D", "detached bungalow": "D",
    "semi-detached house": "S", "semi-detached bungalow": "S",
    "terraced house": "T", "end of terrace": "T", "mid terrace": "T",
    "flat": "F", "apartment": "F", "maisonette": "F",
    "bungalow": "D", "cottage": "T", "town house": "T", "townhouse": "T",
    "link-detached": "S", "link detached": "S",
})

PROPERTY_TYPE_URIS = {
    "D": "http://landregistry.data.gov.uk/def/common/detached",
    "S": "http://landregistry.data.gov.uk/def/common/semi-detached",
    "T": "http://landregistry.data.gov.uk/def/common/terraced",
    "F": "http://landregistry.data.gov.uk/def/common/flat-maisonette",
}

HOUSE_CODES = {"D", "S", "T"}
FLAT_CODES = {"F"}

# Types considered compatible for hard-gate purposes
COMPATIBLE_TYPES = {
    "D": {"D", "S"},       # detached: accept semi as fallback
    "S": {"S", "D", "T"},  # semi: accept detached and terraced
    "T": {"T", "S"},       # terraced: accept semi as fallback
    "F": {"F"},            # flat: only other flats
}


def normalise_property_type(ptype: str) -> str:
    if not ptype:
        return ""
    return PROPERTY_TYPE_REVERSE.get(ptype.lower().strip(), "")


@dataclass
class ScoredComparable:
    """A single comparable with its quality tier and explanation."""
    address: str = ""
    street: str = ""
    paon: str = ""
    town: str = ""
    postcode: str = ""
    price: float = 0.0
    date: str = ""
    property_type_code: str = ""
    property_type: str = ""
    new_build: bool = False
    tenure: str = ""

    # Derived
    adjusted_price: float = 0.0
    price_per_sqm: float = 0.0
    age_days: int = 0
    distance_miles: float = -1.0

    # EPC enrichment
    floor_area_sqm: float = 0.0
    epc_rating: str = ""
    epc_match_reason: str = ""

    # Tiering and scoring
    tier: str = ""           # "A", "B", "C", "D", "Excluded"
    quality_score: int = 0
    quality_band: str = ""   # kept for backward compat — mirrors tier
    score_breakdown: dict = field(default_factory=dict)
    selection_reason: str = ""
    exclusion_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ComparableEvidence:
    """Complete comparable evidence package for a property."""
    subject_postcode: str = ""
    subject_property_type: str = ""
    subject_bedrooms: int = 0
    subject_floor_area_sqm: float = 0.0

    all_comparables: List[ScoredComparable] = field(default_factory=list)
    scored_comparables: List[ScoredComparable] = field(default_factory=list)
    excluded_comparables: List[ScoredComparable] = field(default_factory=list)
    context_only_comparables: List[ScoredComparable] = field(default_factory=list)

    # Tier counts
    tier_a_count: int = 0
    tier_b_count: int = 0
    tier_c_count: int = 0
    tier_d_count: int = 0

    # Legacy band counts (mapped from tiers)
    total_fetched: int = 0
    total_scored: int = 0     # tiers A+B+C (eligible for valuation)
    total_excluded: int = 0
    excellent_count: int = 0  # = tier_a_count
    good_count: int = 0       # = tier_b_count
    fair_count: int = 0       # = tier_c_count
    weak_count: int = 0       # = tier_d_count (context only)
    evidence_summary: str = ""
    search_strategy: str = ""
    warnings: List[str] = field(default_factory=list)

    # EPC enrichment stats
    epc_matched_count: int = 0
    epc_attempted_count: int = 0

    # Retrieval diagnostics
    retrieval_raw_records: int = 0
    retrieval_pages_fetched: int = 0
    retrieval_strategy_used: str = ""
    retrieval_may_be_truncated: bool = False
    retrieval_strategies_detail: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_and_score_comparables(
    postcode: str,
    property_type: str = "",
    bedrooms: int = 0,
    floor_area_sqm: float = 0.0,
    tenure: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    street: str = "",
    max_age_years: int = 5,
) -> ComparableEvidence:
    """Fetch comparables from Land Registry, apply hard gates, assign tiers.

    Returns a ComparableEvidence package. Only tiers A-C feed the valuation.
    Tier D is context-only. Excluded comparables are kept for transparency.
    """
    cfg = get_config()
    evidence = ComparableEvidence(
        subject_postcode=postcode,
        subject_property_type=property_type,
        subject_bedrooms=bedrooms,
        subject_floor_area_sqm=floor_area_sqm,
    )

    subject_street = _normalise_street(street)
    pt_code = normalise_property_type(property_type)
    subject_is_new_build = False  # default; caller can override if known
    now = datetime.now()

    # Fetch raw comparables with progressive search
    raw_records, diag = _fetch_progressive(postcode, property_type, max_age_years)
    evidence.total_fetched = len(raw_records)
    evidence.retrieval_raw_records = diag.total_raw
    evidence.retrieval_pages_fetched = diag.total_pages
    evidence.retrieval_strategy_used = diag.strategy_used
    evidence.retrieval_may_be_truncated = diag.may_be_truncated
    evidence.retrieval_strategies_detail = diag.strategy_details

    if not raw_records:
        evidence.warnings.append("No comparable sales found in Land Registry data")
        evidence.evidence_summary = "No evidence available"
        return evidence

    # Build comparable objects and calculate distance/age
    all_comps = []
    for rec in raw_records:
        comp = ScoredComparable(
            address=rec.get("address", ""),
            street=rec.get("street", ""),
            paon=rec.get("paon", ""),
            town=rec.get("town", ""),
            postcode=rec.get("postcode", ""),
            price=rec.get("price", 0),
            date=rec.get("date", ""),
            property_type_code=rec.get("property_type_code", ""),
            property_type=rec.get("property_type", ""),
            new_build=rec.get("new_build", False),
            tenure=rec.get("tenure", ""),
        )

        try:
            sale_date = pd.to_datetime(comp.date, dayfirst=True)
            comp.age_days = (now - sale_date).days
        except (ValueError, TypeError):
            comp.age_days = max_age_years * 365

        if latitude and longitude and comp.postcode:
            comp.distance_miles = _estimate_distance_from_postcode(
                latitude, longitude, comp.postcode
            )

        all_comps.append(comp)

    # === HARD GATES ===
    for comp in all_comps:
        excluded, reason = _apply_hard_gates(
            comp, pt_code, tenure, subject_is_new_build, max_age_years
        )
        if excluded:
            comp.tier = "Excluded"
            comp.quality_band = "Excluded"
            comp.exclusion_reason = reason
            comp.selection_reason = f"Excluded: {reason}"
            evidence.excluded_comparables.append(comp)
            continue

        # === TIER ASSIGNMENT ===
        tier, score, breakdown, reason = _assign_tier(
            comp, subject_postcode=postcode, subject_street=subject_street,
            subject_pt_code=pt_code, subject_tenure=tenure,
            max_age_years=max_age_years,
            subject_address_first=street,
        )
        comp.tier = tier
        comp.quality_band = _tier_to_band(tier)
        comp.quality_score = score
        comp.score_breakdown = breakdown
        comp.selection_reason = reason
        evidence.all_comparables.append(comp)

    # Separate tiers A-C (eligible) from D (context only)
    for comp in evidence.all_comparables:
        if comp.tier in ("A", "B", "C"):
            evidence.scored_comparables.append(comp)
        else:
            evidence.context_only_comparables.append(comp)

    # Sort eligible by score descending
    evidence.scored_comparables.sort(key=lambda c: c.quality_score, reverse=True)

    # EPC enrichment — add floor area to scored comparables where possible
    from .epc import enrich_comparables_with_epc
    epc_matched, epc_attempted, epc_warnings = enrich_comparables_with_epc(
        evidence.scored_comparables
    )
    evidence.epc_matched_count = epc_matched
    evidence.epc_attempted_count = epc_attempted
    evidence.warnings.extend(epc_warnings)

    # Count tiers
    evidence.tier_a_count = sum(1 for c in evidence.all_comparables if c.tier == "A")
    evidence.tier_b_count = sum(1 for c in evidence.all_comparables if c.tier == "B")
    evidence.tier_c_count = sum(1 for c in evidence.all_comparables if c.tier == "C")
    evidence.tier_d_count = sum(1 for c in evidence.all_comparables if c.tier == "D")

    # Legacy mappings
    evidence.excellent_count = evidence.tier_a_count
    evidence.good_count = evidence.tier_b_count
    evidence.fair_count = evidence.tier_c_count
    evidence.weak_count = evidence.tier_d_count
    evidence.total_scored = len(evidence.scored_comparables)
    evidence.total_excluded = len(evidence.excluded_comparables)

    evidence.evidence_summary = _summarise_evidence(evidence)

    return evidence


def _apply_hard_gates(
    comp: ScoredComparable,
    subject_pt_code: str,
    subject_tenure: str,
    subject_is_new_build: bool,
    max_age_years: int,
) -> Tuple[bool, str]:
    """Apply hard gates. Returns (excluded, reason)."""

    # Gate 1: No mixing flats into house valuations or vice versa (hard rule)
    if subject_pt_code in HOUSE_CODES and comp.property_type_code in FLAT_CODES:
        return True, "Flat excluded from house valuation"
    if subject_pt_code in FLAT_CODES and comp.property_type_code in HOUSE_CODES:
        return True, "House excluded from flat valuation"

    # Gate 3: Exclude new builds when target is resale (unless target is new build)
    if comp.new_build and not subject_is_new_build:
        return True, "New build excluded from resale valuation (new build premium distorts)"

    # Gate 4: Sale too old (beyond max_age_years + 1 year buffer)
    max_days = (max_age_years + 1) * 365
    if comp.age_days > max_days:
        return True, f"Sale too old ({comp.age_days // 365} years)"

    # Gate 5: Price outlier (below £30k or above £5m — likely not comparable residential)
    if comp.price < 30000:
        return True, f"Price too low ({comp.price}) — likely not a standard sale"
    if comp.price > 5000000:
        return True, f"Price too high ({comp.price}) — likely not comparable"

    return False, ""


def _assign_tier(
    comp: ScoredComparable,
    subject_postcode: str,
    subject_street: str,
    subject_pt_code: str,
    subject_tenure: str,
    max_age_years: int,
    subject_address_first: str = "",
) -> Tuple[str, int, dict, str]:
    """Assign a comparable to a tier based on proximity, type match, and recency.

    Tier A: Same road / very close, same type, recent (2 years)
    Tier B: Nearby (same postcode/sector), same type, recent-ish (3 years)
    Tier C: Wider area (same outcode), same broad type, acceptable fallback
    Tier D: Weak contextual evidence only — not used for valuation
    """
    breakdown = {}
    reasons = []

    # Proximity assessment
    prox_level, prox_detail = _assess_proximity(
        comp, subject_postcode, subject_street, subject_address_first
    )
    breakdown["proximity_level"] = prox_level
    reasons.append(prox_detail)

    # Type match assessment
    type_match, type_detail = _assess_type_match(comp.property_type_code, subject_pt_code)
    breakdown["type_match"] = type_match
    reasons.append(type_detail)

    # Recency assessment
    recency_level, recency_detail = _assess_recency(comp.age_days)
    breakdown["recency"] = recency_level
    reasons.append(recency_detail)

    # Tenure match
    tenure_match, tenure_detail = _assess_tenure_match(comp.tenure, subject_tenure)
    breakdown["tenure_match"] = tenure_match
    reasons.append(tenure_detail)

    # === Tier determination ===
    # "unknown" type match: API didn't return type — allow but at reduced confidence
    type_ok_exact = type_match == "exact"
    type_ok_broad = type_match in ("exact", "compatible", "unknown")
    type_is_different = type_match == "different"

    # Tier A: same street/building (prox 4) with compatible type + reasonably recent
    # OR same postcode (prox 3) with exact type + recent + same tenure
    if (prox_level == 4 and type_ok_broad and not type_is_different and
            recency_level >= 2 and tenure_match in ("exact", "unknown")):
        tier = "A"
        score = 90 + (5 if type_ok_exact else 0)
    elif (prox_level >= 3 and type_ok_exact and
            recency_level >= 3 and tenure_match in ("exact", "unknown")):
        tier = "A"
        score = 90

    # Tier B: nearby + same/compatible/unknown type + reasonably recent
    elif (prox_level >= 2 and type_ok_broad and not type_is_different and
            recency_level >= 2):
        tier = "B"
        base = 65
        if prox_level >= 3:
            base += 5
        if type_ok_exact:
            base += 5
        if recency_level >= 3:
            base += 5
        if tenure_match == "exact":
            base += 3
        if type_match == "unknown":
            base -= 5  # penalise unknown type
        score = min(89, max(65, base))

    # Tier C: wider area + same broad type or unknown + within date limit
    elif (prox_level >= 1 and type_ok_broad and not type_is_different and
            recency_level >= 1):
        tier = "C"
        base = 40
        if prox_level >= 2:
            base += 5
        if type_ok_exact:
            base += 5
        if recency_level >= 2:
            base += 5
        if type_match == "unknown":
            base -= 3
        score = min(64, max(40, base))

    # Tier D: everything else that passed hard gates but is too weak for valuation
    else:
        tier = "D"
        score = max(5, 10 + (5 if prox_level >= 1 else 0) +
                    (5 if not type_is_different else 0) +
                    (5 if recency_level >= 1 else 0))
        score = min(39, score)

    reason = f"Tier {tier}: " + "; ".join(reasons)
    return tier, score, breakdown, reason


def _extract_street_name(street: str) -> str:
    """Extract the core street/building name for matching purposes."""
    if not street:
        return ""
    s = street.upper().strip()
    s = re.sub(r"^\d+[\s,]*", "", s)
    s = s.strip(", ")
    return s


def _extract_building_name(address: str) -> str:
    """Extract a building/development name from an address if present.

    Looks for named buildings like 'YEWDALE PARK', 'INGESTRE COURT' etc.
    """
    if not address:
        return ""
    upper = address.upper()
    parts = [p.strip() for p in upper.split(",")]
    if len(parts) >= 2:
        first = re.sub(r"^\d+[\s,]*", "", parts[0]).strip()
        if first and not first.isdigit() and len(first) > 3:
            return first
    return ""


def _is_same_street_or_building(
    comp: ScoredComparable, subject_street: str, subject_address_first: str
) -> Tuple[bool, str]:
    """Check if comp is on the same street or in the same building/development.

    Returns (match, reason).
    """
    comp_street_norm = _normalise_street(comp.street)
    if subject_street and comp_street_norm and subject_street == comp_street_norm:
        return True, f"Same street ({comp.street})"

    comp_building = _extract_building_name(comp.address)
    subject_building = subject_address_first.upper().strip() if subject_address_first else ""

    if comp_building and subject_building:
        comp_bn = re.sub(r"[^A-Z0-9 ]", "", comp_building).strip()
        subj_bn = re.sub(r"[^A-Z0-9 ]", "", subject_building).strip()
        if comp_bn and subj_bn and (comp_bn in subj_bn or subj_bn in comp_bn):
            return True, f"Same building/development ({comp_building})"

    comp_street_name = _extract_street_name(comp.street)
    if comp_street_name and subject_building:
        subj_clean = re.sub(r"[^A-Z0-9 ]", "", subject_building).strip()
        comp_clean = re.sub(r"[^A-Z0-9 ]", "", comp_street_name).strip()
        if comp_clean and subj_clean and (comp_clean in subj_clean or subj_clean in comp_clean):
            return True, f"Same street/development ({comp.street})"

    return False, ""


def _assess_proximity(
    comp: ScoredComparable, subject_postcode: str, subject_street: str,
    subject_address_first: str = "",
) -> Tuple[int, str]:
    """Return proximity level (0-4) and description.

    4 = same street or same building/development
    3 = same postcode
    2 = same sector
    1 = same outcode
    0 = different area
    """
    is_same, reason = _is_same_street_or_building(comp, subject_street, subject_address_first)
    if is_same:
        return 4, reason

    if comp.postcode and subject_postcode:
        subj_norm = subject_postcode.upper().replace(" ", "")
        comp_norm = comp.postcode.upper().replace(" ", "")
        if subj_norm == comp_norm:
            return 3, f"Same postcode ({comp.postcode})"

        if (postcode_sector(subject_postcode).replace(" ", "") ==
                postcode_sector(comp.postcode).replace(" ", "")):
            return 2, f"Same postcode sector"

        if postcode_outcode(subject_postcode) == postcode_outcode(comp.postcode):
            return 1, f"Same outcode ({postcode_outcode(comp.postcode)})"

    return 0, "Different postcode area"


def _assess_type_match(comp_code: str, subject_code: str) -> Tuple[str, str]:
    """Return type match level and description."""
    if not subject_code or not comp_code:
        return "unknown", "Property type comparison: data incomplete"
    if comp_code == subject_code:
        return "exact", f"Same property type ({PROPERTY_TYPE_MAP.get(comp_code, comp_code)})"
    compatible = COMPATIBLE_TYPES.get(subject_code, set())
    if comp_code in compatible:
        comp_name = PROPERTY_TYPE_MAP.get(comp_code, comp_code)
        return "compatible", f"Compatible type ({comp_name})"
    comp_name = PROPERTY_TYPE_MAP.get(comp_code, comp_code)
    return "different", f"Different property type ({comp_name})"


def _assess_recency(age_days: int) -> Tuple[int, str]:
    """Return recency level (0-4) and description.

    4 = within 6 months
    3 = within 1 year
    2 = within 2 years
    1 = within 3 years
    0 = older
    """
    if age_days <= 180:
        return 4, "Sold within 6 months"
    if age_days <= 365:
        return 3, "Sold within 1 year"
    if age_days <= 730:
        return 2, "Sold within 2 years"
    if age_days <= 1095:
        return 1, "Sold within 3 years"
    years = age_days / 365.25
    return 0, f"Sold {years:.1f} years ago"


def _assess_tenure_match(comp_tenure: str, subject_tenure: str) -> Tuple[str, str]:
    """Return tenure match level and description."""
    if not subject_tenure or not comp_tenure:
        return "unknown", "Tenure comparison: data incomplete"
    ct = comp_tenure.lower()
    st = subject_tenure.lower()
    if ("freehold" in ct and "freehold" in st) or ("leasehold" in ct and "leasehold" in st):
        return "exact", f"Same tenure ({comp_tenure})"
    return "different", f"Different tenure ({comp_tenure} vs {subject_tenure})"


def _tier_to_band(tier: str) -> str:
    return {"A": "Excellent", "B": "Good", "C": "Fair", "D": "Weak"}.get(tier, "Excluded")


def _normalise_street(street: str) -> str:
    if not street:
        return ""
    s = street.upper().strip()
    s = re.sub(r"\b(ROAD|RD|STREET|ST|LANE|LN|AVENUE|AVE|DRIVE|DR|CLOSE|CL|COURT|CT|WAY|CRESCENT|CRES|PLACE|PL|GARDENS|GDNS|TERRACE|TER|GROVE|GR)\b", "", s)
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


def _estimate_distance_from_postcode(
    subject_lat: float, subject_lon: float, comp_postcode: str
) -> float:
    """Rough distance estimate using postcode centroid."""
    from .transport import geocode_postcode
    coords = geocode_postcode(comp_postcode)
    if coords:
        return round(geodesic((subject_lat, subject_lon), coords).miles, 2)
    return -1.0


def _summarise_evidence(evidence: ComparableEvidence) -> str:
    parts = []
    parts.append(
        f"{evidence.total_fetched} sales fetched. "
        f"{evidence.total_excluded} excluded by hard gates."
    )
    parts.append(
        f"Tier A: {evidence.tier_a_count}, "
        f"Tier B: {evidence.tier_b_count}, "
        f"Tier C: {evidence.tier_c_count}, "
        f"Tier D: {evidence.tier_d_count} (context only)."
    )
    eligible = evidence.total_scored
    parts.append(f"{eligible} eligible for valuation (Tiers A-C).")

    if evidence.tier_a_count >= 3:
        parts.append("Strong evidence base.")
    elif evidence.tier_a_count + evidence.tier_b_count >= 3:
        parts.append("Reasonable evidence base.")
    elif eligible >= 3:
        parts.append("Limited quality evidence - treat valuation as indicative.")
    elif eligible > 0:
        parts.append("Very weak evidence - valuation has low reliability.")
    else:
        parts.append("No eligible comparables for valuation.")

    return " ".join(parts)


# ---- Land Registry API access ----

_PAGE_SIZE = 100
_MAX_PAGES_PER_QUERY = 10
_MAX_RECORDS_HARD_CAP = 1000


@dataclass
class _FetchDiagnostics:
    """Internal diagnostics from the progressive fetch."""
    total_raw: int = 0
    total_pages: int = 0
    strategy_used: str = ""
    may_be_truncated: bool = False
    strategy_details: List[str] = field(default_factory=list)


def _fetch_progressive(
    postcode: str, property_type: str, max_age_years: int
) -> Tuple[List[dict], _FetchDiagnostics]:
    """Fetch comparables with progressive postcode widening and full pagination.

    Strategy:
      1. Exact postcode — fetch all pages
      2. Postcode sector — fetch all pages (this is the primary evidence range)
      3. Full outcode — fetch all pages (fallback for sparse areas)

    Always completes the sector-level search (strategy 2) regardless of
    how many records strategy 1 returned. Only skips the outcode-wide
    search (strategy 3) if sector already has sufficient records.
    """
    diag = _FetchDiagnostics()

    ck = cache_key("comp2", {"pc": postcode, "pt": property_type, "y": max_age_years})
    cached = get_cached(ck, max_age_hours=168)
    if cached and "records" in cached:
        diag.total_raw = len(cached["records"])
        diag.strategy_used = cached.get("strategy", "cached")
        diag.may_be_truncated = cached.get("truncated", False)
        diag.strategy_details = cached.get("strategy_details", ["loaded from cache"])
        diag.total_pages = cached.get("pages_fetched", 0)
        return cached["records"], diag

    sector_code = postcode_sector(postcode).split()[-1] if " " in postcode_sector(postcode) else ""
    strategies = [
        {"type": "exact", "postcode": postcode, "label": "exact postcode"},
        {"type": "range", "outcode": postcode_outcode(postcode),
         "sector": sector_code, "label": f"sector {postcode_outcode(postcode)} {sector_code}"},
        {"type": "range", "outcode": postcode_outcode(postcode),
         "sector": "", "label": f"outcode {postcode_outcode(postcode)}"},
    ]

    all_records = []
    seen = set()
    total_pages = 0
    final_strategy = ""
    truncated = False

    for i, strategy in enumerate(strategies):
        try:
            records, pages, was_truncated = _query_ppd_paginated(strategy, max_age_years)
            new_count = 0
            for r in records:
                key = (r.get("address", ""), r.get("date", ""), r.get("price", 0))
                if key not in seen:
                    all_records.append(r)
                    seen.add(key)
                    new_count += 1
            total_pages += pages
            if was_truncated:
                truncated = True
            detail = f"{strategy['label']}: {len(records)} raw, {new_count} new, {pages} pages"
            if was_truncated:
                detail += " (truncated at cap)"
            diag.strategy_details.append(detail)
            final_strategy = strategy["label"]
        except Exception as e:
            diag.strategy_details.append(f"{strategy['label']}: error ({e})")
            continue

        # Always run strategy 0 (exact) and strategy 1 (sector).
        # Only skip strategy 2 (outcode) if sector gave enough records.
        if i >= 1 and len(all_records) >= 30:
            break

    diag.total_raw = len(all_records)
    diag.total_pages = total_pages
    diag.strategy_used = final_strategy
    diag.may_be_truncated = truncated

    if all_records:
        set_cache(ck, {
            "records": all_records,
            "strategy": final_strategy,
            "truncated": truncated,
            "pages_fetched": total_pages,
            "strategy_details": diag.strategy_details,
        })

    return all_records, diag


def _query_ppd_paginated(
    strategy: dict, max_age_years: int,
) -> Tuple[List[dict], int, bool]:
    """Query the Land Registry PPD API with full pagination.

    Returns (records, pages_fetched, was_truncated).
    was_truncated is True if we hit _MAX_RECORDS_HARD_CAP before
    exhausting pages.
    """
    from datetime import datetime, timedelta
    min_date = (datetime.now() - timedelta(days=max_age_years * 365 + 365)).strftime("%Y-%m-%d")

    base_params = {
        "min-pricePaid": "1",
        "min-transactionDate": min_date,
        "_pageSize": str(_PAGE_SIZE),
    }

    if strategy.get("type") == "exact":
        base_params["propertyAddress.postcode"] = strategy["postcode"]
    elif strategy.get("type") == "range":
        outcode = strategy["outcode"]
        sector = strategy.get("sector", "")
        if sector:
            base_params["min-propertyAddress.postcode"] = f"{outcode} {sector}AA"
            base_params["max-propertyAddress.postcode"] = f"{outcode} {sector}ZZ"
        else:
            base_params["min-propertyAddress.postcode"] = f"{outcode} 0AA"
            base_params["max-propertyAddress.postcode"] = f"{outcode} 9ZZ"

    api_url = f"{API_BASE}/transaction-record.json"
    all_records = []
    pages_fetched = 0
    was_truncated = False

    for page in range(_MAX_PAGES_PER_QUERY):
        params = dict(base_params)
        params["_page"] = str(page)

        resp = requests.get(url=api_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("result", {})
        items = result.get("items", [])
        pages_fetched += 1

        if not items:
            break

        for item in items:
            all_records.append(_parse_ppd_item(item))

        if len(all_records) >= _MAX_RECORDS_HARD_CAP:
            was_truncated = True
            break

        if "next" not in result:
            break

    return all_records, pages_fetched, was_truncated


def _parse_ppd_item(item: dict) -> dict:
    """Parse a single PPD API item into a comparable record dict."""
    addr = item.get("propertyAddress", {})
    if not isinstance(addr, dict):
        addr = {}

    paon = str(addr.get("paon", ""))
    saon = str(addr.get("saon", "") or "")
    street = str(addr.get("street", ""))
    town = str(addr.get("town", ""))
    district = str(addr.get("district", ""))
    county = str(addr.get("county", ""))
    pc = str(addr.get("postcode", ""))

    address_parts = [p for p in [paon, saon, street, town, district, county] if p]

    return {
        "price": safe_float(item.get("pricePaid")),
        "date": _extract_date(item.get("transactionDate")),
        "address": ", ".join(address_parts),
        "paon": paon,
        "street": street,
        "town": town,
        "postcode": pc,
        "property_type_code": _extract_property_type(item),
        "property_type": PROPERTY_TYPE_MAP.get(_extract_property_type(item), "Unknown"),
        "new_build": bool(item.get("newBuild", False)),
        "tenure": _extract_tenure(item),
    }


def _extract_date(val) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return str(val.get("@value", ""))
    return str(val)


def _extract_label(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        label = obj.get("label", "") or obj.get("@id", "")
        if isinstance(label, list):
            return " ".join(
                str(l.get("_value", l) if isinstance(l, dict) else l)
                for l in label
            )
        return str(label)
    if isinstance(obj, list) and obj:
        return _extract_label(obj[0])
    return str(obj)


def _extract_property_type(item: dict) -> str:
    pt = item.get("propertyType", "")
    if isinstance(pt, dict):
        uri = pt.get("_about", "")
        if "detached" in uri and "semi" not in uri:
            return "D"
        if "semi-detached" in uri:
            return "S"
        if "terraced" in uri:
            return "T"
        if "flat" in uri or "maisonette" in uri:
            return "F"
    label = _extract_label(pt).lower()
    if "semi" in label:
        return "S"
    if "detach" in label and "semi" not in label:
        return "D"
    if "terrace" in label:
        return "T"
    if "flat" in label or "maisonette" in label:
        return "F"
    return ""


def _extract_tenure(item: dict) -> str:
    tenure = item.get("estateType", "")
    label = _extract_label(tenure).lower()
    if "freehold" in label:
        return "Freehold"
    if "leasehold" in label:
        return "Leasehold"
    return label.title() if label else ""
