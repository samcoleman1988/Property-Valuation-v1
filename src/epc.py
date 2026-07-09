"""EPC (Energy Performance Certificate) data access.

Uses the GOV.UK EPC API at https://api.get-energy-performance-data.communities.gov.uk
Requires a free Bearer token (register via GOV.UK One Login). If no key is configured,
the module returns empty results and flags a warning.
"""

import os
import re
import requests
import pandas as pd
from typing import Optional, List, Tuple

from .utils import cache_key, get_cached, set_cache

EPC_API_BASE = "https://api.get-energy-performance-data.communities.gov.uk/api"


def get_epc_key() -> str:
    """Read the EPC API key from Streamlit Cloud secrets (if running there)
    or the local environment / .env file (local dev). Checking st.secrets
    first means the key never needs to exist as an OS env var in a hosted
    deployment — it's entered once in the Streamlit Cloud dashboard and
    never touches the git repo.
    """
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "EPC_API_KEY" in st.secrets:
            return st.secrets["EPC_API_KEY"]
    except Exception:
        pass
    return os.environ.get("EPC_API_KEY", "")


def _auth_headers() -> dict:
    key = get_epc_key()
    if not key:
        return {}
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def search_epc_by_postcode(postcode: str, limit: int = 25) -> pd.DataFrame:
    """Search EPC register by postcode. Returns DataFrame with full certificate data."""
    headers = _auth_headers()
    if not headers:
        return _empty_frame()

    ck = cache_key("epc_v2", {"pc": postcode})
    cached = get_cached(ck, max_age_hours=720)
    if cached and "records" in cached:
        return pd.DataFrame(cached["records"])

    try:
        resp = requests.get(
            f"{EPC_API_BASE}/domestic/search",
            params={"postcode": postcode, "page_size": limit},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return _empty_frame()

    summaries = data.get("data", [])
    if not summaries:
        return _empty_frame()

    records = []
    for s in summaries:
        cert_num = s.get("certificateNumber", "")
        if not cert_num:
            continue
        detail = _fetch_certificate(cert_num, headers)
        if detail:
            records.append(detail)

    if not records:
        return _empty_frame()

    set_cache(ck, {"records": records})
    return pd.DataFrame(records)


def _fetch_certificate(cert_number: str, headers: dict) -> Optional[dict]:
    """Fetch full certificate details and normalise to the field names used downstream."""
    try:
        resp = requests.get(
            f"{EPC_API_BASE}/certificate",
            params={"certificate_number": cert_number},
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json().get("data", {})
    except (requests.RequestException, ValueError):
        return None

    if not raw:
        return None

    addr_parts = [
        raw.get("address_line_1", ""),
        raw.get("address_line_2", ""),
        raw.get("address_line_3", ""),
        raw.get("address_line_4", ""),
    ]
    address = ", ".join(p for p in addr_parts if p)

    return {
        "address": address,
        "postcode": raw.get("postcode", ""),
        "current-energy-rating": raw.get("current_energy_efficiency_band", ""),
        "current-energy-efficiency": raw.get("energy_rating_current", ""),
        "floor-area": raw.get("total_floor_area", 0),
        "lodgement-date": raw.get("registration_date", ""),
        "property-type": raw.get("dwelling_type", ""),
        "built-form": raw.get("built_form", ""),
        "certificate-number": raw.get("certificateNumber", cert_number),
    }


def get_epc_for_address(postcode: str, address: str) -> Optional[dict]:
    """Try to find the best-matching EPC for a specific address."""
    df = search_epc_by_postcode(postcode)
    if df.empty:
        return None

    addr_lower = address.lower()
    best_match = None
    best_score = 0

    for _, row in df.iterrows():
        epc_addr = str(row.get("address", "")).lower()
        words = set(addr_lower.split())
        epc_words = set(epc_addr.split())
        overlap = len(words & epc_words)
        if overlap > best_score:
            best_score = overlap
            best_match = row.to_dict()

    return best_match


def estimate_epc_impact(current_rating: str) -> dict:
    """Estimate the financial impact of EPC rating on value and costs."""
    ratings = {"A": 7, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1}
    score = ratings.get(current_rating.upper(), 4) if current_rating else 4

    return {
        "current_rating": current_rating or "Unknown",
        "rating_score": score,
        "estimated_annual_energy_cost": _energy_cost_estimate(score),
        "upgrade_potential": score < 5,
        "upgrade_cost_estimate_low": max(0, (5 - score)) * 2000,
        "upgrade_cost_estimate_high": max(0, (5 - score)) * 6000,
        "value_impact_pct": (score - 4) * 1.5,
        "notes": _epc_notes(current_rating),
    }


def _energy_cost_estimate(score: int) -> float:
    estimates = {7: 800, 6: 1100, 5: 1500, 4: 2000, 3: 2800, 2: 3500, 1: 4500}
    return estimates.get(score, 2000)


def _epc_notes(rating: str) -> str:
    if not rating:
        return "EPC rating unknown — request certificate from agent."
    r = rating.upper()
    if r in ("A", "B"):
        return "Good energy rating. Minimal upgrade needed."
    if r == "C":
        return "Acceptable rating. Minor improvements possible."
    if r == "D":
        return "Average rating. Typical for older properties. Upgrade would add value."
    if r in ("E", "F", "G"):
        return f"Poor rating ({r}). Significant upgrade costs likely. Landlords must reach E by law for lettings."
    return "EPC rating not recognised."


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "address", "postcode", "current-energy-rating",
        "current-energy-efficiency", "property-type",
        "built-form", "floor-area", "lodgement-date",
    ])


def _extract_number(text: str) -> str:
    """Extract the primary building/flat number from an address string."""
    if not text:
        return ""
    m = re.match(r"^\s*(?:flat\s+)?(\d+[a-zA-Z]?)\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return ""


def _extract_flat_id(text: str) -> str:
    """Extract flat/apartment identifier from an address."""
    if not text:
        return ""
    upper = text.upper()
    m = re.search(r"\bFLAT\s+(\d+[A-Z]?)\b", upper)
    if m:
        return m.group(1)
    m = re.search(r"\bAPARTMENT\s+(\d+[A-Z]?)\b", upper)
    if m:
        return m.group(1)
    return ""


def _normalise_for_match(text: str) -> str:
    """Strip punctuation and normalise whitespace for comparison."""
    if not text:
        return ""
    s = text.upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def match_epc_to_comparable(
    comp_postcode: str,
    comp_paon: str,
    comp_saon: str,
    comp_street: str,
    comp_address: str,
    epc_df: pd.DataFrame,
) -> Tuple[Optional[dict], str]:
    """Try to find a confident EPC match for a Land Registry comparable.

    Returns (epc_record_dict, match_reason) or (None, reason_skipped).
    Conservative: only returns a match when confident.
    """
    if epc_df.empty:
        return None, "no EPC data"

    comp_num = _extract_number(comp_paon) or _extract_number(comp_address)
    comp_flat = _extract_flat_id(comp_address) or _extract_flat_id(comp_paon)
    if not comp_flat and comp_saon:
        comp_flat = _extract_flat_id(comp_saon) or _extract_number(comp_saon)
    comp_street_norm = _normalise_for_match(comp_street)

    candidates = []
    for _, row in epc_df.iterrows():
        epc_addr = str(row.get("address", ""))
        epc_pc = str(row.get("postcode", "")).upper().replace(" ", "")
        comp_pc = comp_postcode.upper().replace(" ", "")

        if epc_pc != comp_pc:
            continue

        epc_num = _extract_number(epc_addr)
        epc_flat = _extract_flat_id(epc_addr)
        epc_addr_norm = _normalise_for_match(epc_addr)

        score = 0
        reasons = []

        if comp_num and epc_num:
            if comp_num == epc_num:
                score += 3
                reasons.append(f"number match ({comp_num})")
            else:
                continue
        elif not comp_num and not epc_num:
            pass
        else:
            continue

        if comp_flat or epc_flat:
            if comp_flat and epc_flat and comp_flat == epc_flat:
                score += 2
                reasons.append(f"flat match ({comp_flat})")
            elif comp_flat and epc_flat:
                continue
            else:
                score -= 1

        if comp_street_norm:
            street_words = set(comp_street_norm.split())
            epc_words = set(epc_addr_norm.split())
            overlap = street_words & epc_words
            if len(overlap) >= 1 and len(street_words) > 0:
                score += 1
                reasons.append("street overlap")

        floor_area = row.get("floor-area")
        try:
            floor_area = float(floor_area)
        except (ValueError, TypeError):
            floor_area = 0.0

        if floor_area <= 0:
            continue

        if score >= 3:
            candidates.append((score, row.to_dict(), "; ".join(reasons)))

    if not candidates:
        return None, "no confident match"

    candidates.sort(key=lambda x: x[0], reverse=True)

    if len(candidates) >= 2 and candidates[0][0] == candidates[1][0]:
        top = candidates[0][1]
        second = candidates[1][1]
        top_date = str(top.get("lodgement-date", ""))
        second_date = str(second.get("lodgement-date", ""))
        if top_date >= second_date:
            return top, f"best of {len(candidates)} candidates (most recent): {candidates[0][2]}"
        else:
            return second, f"best of {len(candidates)} candidates (most recent): {candidates[1][2]}"

    best = candidates[0]
    return best[1], best[2]


def lookup_subject_floor_area(
    postcode: str,
    address: str,
    street: str = "",
) -> Tuple[float, str, str]:
    """Look up the subject property's floor area from the EPC register.

    Args:
        postcode: Subject property postcode.
        address: Full address string (e.g. "14 Ruttle Close, Wallingford").
        street: Street name if known separately.

    Returns:
        (floor_area_sqm, epc_rating, match_detail) or (0.0, "", reason).
    """
    if not get_epc_key():
        return 0.0, "", "EPC API key not configured"

    epc_df = search_epc_by_postcode(postcode, limit=50)
    if epc_df.empty:
        return 0.0, "", "no EPC data for postcode"

    building_num = _extract_number(address)
    flat_id = _extract_flat_id(address)
    street_norm = _normalise_for_match(street) if street else ""

    if not street_norm and address:
        parts = address.split(",")
        if parts:
            street_norm = _normalise_for_match(parts[0])

    epc_record, reason = match_epc_to_comparable(
        comp_postcode=postcode,
        comp_paon=building_num,
        comp_saon=flat_id,
        comp_street=street if street else (address.split(",")[0] if address else ""),
        comp_address=address,
        epc_df=epc_df,
    )

    if not epc_record:
        return 0.0, "", reason

    try:
        fa = float(epc_record.get("floor-area", 0))
    except (ValueError, TypeError):
        fa = 0.0

    if fa <= 0:
        return 0.0, "", "EPC matched but no floor area recorded"

    rating = str(epc_record.get("current-energy-rating", ""))
    epc_addr = epc_record.get("address", "")
    return fa, rating, f"EPC match: {epc_addr} ({reason})"


def enrich_comparables_with_epc(
    comparables: list,
    postcodes: Optional[set] = None,
) -> Tuple[int, int, List[str]]:
    """Enrich a list of ScoredComparable objects with EPC floor area data.

    Args:
        comparables: list of ScoredComparable (modified in place)
        postcodes: set of postcodes to fetch EPC data for (if None, derived from comps)

    Returns:
        (epc_matched_count, epc_attempted_count, warnings)
    """
    if not get_epc_key():
        return 0, 0, ["EPC enrichment unavailable - EPC_API_KEY not configured"]

    if postcodes is None:
        postcodes = {c.postcode for c in comparables if c.postcode}

    epc_cache = {}
    for pc in postcodes:
        if pc:
            epc_cache[pc.upper().replace(" ", "")] = search_epc_by_postcode(pc, limit=50)

    matched = 0
    attempted = 0
    warnings = []

    for comp in comparables:
        if not comp.postcode:
            continue
        attempted += 1
        pc_key = comp.postcode.upper().replace(" ", "")
        epc_df = epc_cache.get(pc_key, _empty_frame())

        saon = ""
        if hasattr(comp, "address"):
            parts = comp.address.split(",")
            if len(parts) >= 2:
                saon = parts[0].strip()

        epc_record, reason = match_epc_to_comparable(
            comp_postcode=comp.postcode,
            comp_paon=getattr(comp, "paon", ""),
            comp_saon=saon,
            comp_street=getattr(comp, "street", ""),
            comp_address=getattr(comp, "address", ""),
            epc_df=epc_df,
        )

        if epc_record:
            try:
                fa = float(epc_record.get("floor-area", 0))
            except (ValueError, TypeError):
                fa = 0.0
            if fa > 0:
                comp.floor_area_sqm = fa
                comp.epc_rating = str(epc_record.get("current-energy-rating", ""))
                comp.epc_match_reason = reason
                matched += 1

    if attempted > 0 and matched == 0:
        warnings.append("EPC data fetched but no confident matches found for comparables")
    elif matched > 0:
        warnings.append(f"EPC floor area matched for {matched}/{attempted} comparables")

    return matched, attempted, warnings
