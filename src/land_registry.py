"""HM Land Registry Price Paid Data access.

Uses the Land Registry Linked Data API (free, no key required) to find
comparable sold prices near a target property.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from .utils import postcode_outcode, postcode_sector, cache_key, get_cached, set_cache, safe_float

API_BASE = "https://landregistry.data.gov.uk/data/ppi"
SPARQL_ENDPOINT = "https://landregistry.data.gov.uk/app/root/qonsole"

PROPERTY_TYPE_MAP = {
    "D": "Detached",
    "S": "Semi-Detached",
    "T": "Terraced",
    "F": "Flat/Maisonette",
    "O": "Other",
}

PROPERTY_TYPE_REVERSE = {v.lower(): k for k, v in PROPERTY_TYPE_MAP.items()}
PROPERTY_TYPE_REVERSE.update({
    "detached house": "D",
    "detached bungalow": "D",
    "semi-detached house": "S",
    "semi-detached bungalow": "S",
    "terraced house": "T",
    "end of terrace": "T",
    "mid terrace": "T",
    "flat": "F",
    "apartment": "F",
    "maisonette": "F",
    "bungalow": "D",
    "cottage": "T",
    "town house": "T",
    "townhouse": "T",
    "link-detached": "S",
    "link detached": "S",
})


def normalise_property_type(ptype: str) -> str:
    if not ptype:
        return ""
    return PROPERTY_TYPE_REVERSE.get(ptype.lower().strip(), "")


def search_comparables(
    postcode: str,
    property_type: str = "",
    max_age_years: int = 5,
    limit: int = 100,
) -> pd.DataFrame:
    """Search Land Registry Price Paid Data for comparable sales.

    Uses the free REST API with postcode filtering.
    Returns a DataFrame of sold prices with columns:
        price, date, address, property_type_code, property_type, new_build, tenure, postcode
    """
    ck = cache_key("lr", {"pc": postcode, "pt": property_type, "years": max_age_years})
    cached = get_cached(ck, max_age_hours=168)  # cache for 1 week
    if cached and "records" in cached:
        return pd.DataFrame(cached["records"])

    records = []

    # Try exact postcode first, then range-based sector/outcode search
    search_strategies = [
        {"type": "exact", "postcode": postcode},
        {"type": "range", "outcode": postcode_outcode(postcode), "sector": postcode_sector(postcode).split()[-1] if " " in postcode_sector(postcode) else ""},
        {"type": "range", "outcode": postcode_outcode(postcode), "sector": ""},
    ]

    all_records = []
    for strategy in search_strategies:
        try:
            df = _query_ppd_api(strategy, property_type, max_age_years, limit)
            if not df.empty:
                new_records = df.to_dict("records")
                # Merge, deduplicating by address+date
                seen = {(r.get("address", ""), r.get("date", "")) for r in all_records}
                for r in new_records:
                    key = (r.get("address", ""), r.get("date", ""))
                    if key not in seen:
                        all_records.append(r)
                        seen.add(key)
                if len(all_records) >= 5:
                    break
        except Exception:
            continue
    records = all_records

    if records:
        set_cache(ck, {"records": records})
    return pd.DataFrame(records) if records else _empty_frame()


def _query_ppd_api(
    strategy: dict,
    property_type: str,
    max_age_years: int,
    limit: int,
) -> pd.DataFrame:
    """Query the Land Registry Price Paid Data linked data API."""
    min_date = (datetime.now() - timedelta(days=max_age_years * 365)).strftime("%Y-%m-%d")
    pt_code = normalise_property_type(property_type)

    PROPERTY_TYPE_URIS = {
        "D": "http://landregistry.data.gov.uk/def/common/detached",
        "S": "http://landregistry.data.gov.uk/def/common/semi-detached",
        "T": "http://landregistry.data.gov.uk/def/common/terraced",
        "F": "http://landregistry.data.gov.uk/def/common/flat-maisonette",
    }

    params = {
        "min-pricePaid": "1",
        "_pageSize": str(limit),
        "_page": "0",
    }

    if strategy.get("type") == "exact":
        params["propertyAddress.postcode"] = strategy["postcode"]
    elif strategy.get("type") == "range":
        outcode = strategy["outcode"]
        sector = strategy.get("sector", "")
        if sector:
            params["min-propertyAddress.postcode"] = f"{outcode} {sector}AA"
            params["max-propertyAddress.postcode"] = f"{outcode} {sector}ZZ"
        else:
            params["min-propertyAddress.postcode"] = f"{outcode} 0AA"
            params["max-propertyAddress.postcode"] = f"{outcode} 9ZZ"

    if pt_code and pt_code in PROPERTY_TYPE_URIS:
        params["propertyType"] = PROPERTY_TYPE_URIS[pt_code]

    url = f"{API_BASE}/transaction-record.json"

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return _empty_frame()

    items = data.get("result", {}).get("items", [])
    if not items:
        return _empty_frame()

    rows = []
    for item in items:
        price = safe_float(item.get("pricePaid"))
        date = _extract_date(item.get("transactionDate"))
        address_parts = []
        addr = item.get("propertyAddress", {})
        for key in ("paon", "saon", "street", "town", "district", "county"):
            val = addr.get(key) if isinstance(addr, dict) else ""
            if val:
                address_parts.append(str(val))
        pc = addr.get("postcode", "") if isinstance(addr, dict) else ""
        pt = _extract_property_type(item)
        new_build = item.get("newBuild", False)
        tenure_val = _extract_tenure(item)

        rows.append({
            "price": price,
            "date": date,
            "address": ", ".join(address_parts),
            "property_type_code": pt,
            "property_type": PROPERTY_TYPE_MAP.get(pt, "Unknown"),
            "new_build": bool(new_build),
            "tenure": tenure_val,
            "postcode": pc,
        })

    return pd.DataFrame(rows)


def _extract_date(val) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        return val[:10]
    if isinstance(val, dict):
        return str(val.get("@value", ""))[:10]
    return str(val)[:10]


def _extract_property_type(item: dict) -> str:
    pt = item.get("propertyType", "")
    if isinstance(pt, dict):
        label = pt.get("label", "") or pt.get("@id", "")
        if isinstance(label, list):
            label = " ".join(
                str(l.get("_value", l) if isinstance(l, dict) else l)
                for l in label
            )
        label = str(label)
        for code, name in PROPERTY_TYPE_MAP.items():
            if name.lower() in label.lower():
                return code
        return ""
    if isinstance(pt, list) and pt:
        return _extract_property_type({"propertyType": pt[0]})
    for code in PROPERTY_TYPE_MAP:
        if str(pt).upper() == code:
            return code
    return ""


def _extract_tenure(item: dict) -> str:
    tenure = item.get("estateType", "")
    if isinstance(tenure, dict):
        label = tenure.get("label", "") or tenure.get("@id", "")
        if isinstance(label, list):
            label = " ".join(
                str(l.get("_value", l) if isinstance(l, dict) else l)
                for l in label
            )
        label = str(label)
        if "freehold" in label.lower():
            return "Freehold"
        if "leasehold" in label.lower():
            return "Leasehold"
        return label
    tenure_str = str(tenure).lower()
    if "freehold" in tenure_str:
        return "Freehold"
    if "leasehold" in tenure_str:
        return "Leasehold"
    return str(tenure)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "price", "date", "address", "property_type_code",
        "property_type", "new_build", "tenure", "postcode",
    ])
