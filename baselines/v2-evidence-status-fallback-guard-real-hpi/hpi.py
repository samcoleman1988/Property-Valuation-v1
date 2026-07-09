"""UK House Price Index adjustment.

Uses ONS/Land Registry UK HPI data to adjust historic sold prices
to current-equivalent values.

The UK HPI is published monthly and available as open data.
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Optional

from .utils import cache_key, get_cached, set_cache

UK_HPI_CSV_URL = (
    "https://raw.githubusercontent.com/epogrebnyak/uk-house-price-index/main/data/UK-HPI-full-file.csv"
)

# Fallback: use national average annual growth if API unavailable
NATIONAL_ANNUAL_GROWTH_PCT = 3.0  # long-run UK average approx


_hpi_memory_cache: dict = {}  # region -> DataFrame, populated once per process

# Diagnostic record per region: whether real regional HPI data was used or
# the flat-rate fallback, and the latest HPI month available. Read-only —
# populated as a side effect of get_hpi_data(), never consulted by any
# valuation calculation.
_hpi_diagnostics: dict = {}


def get_hpi_diagnostics(region: str = "England") -> dict:
    """Diagnostic info about HPI data availability for a region.

    Returns a dict with:
        region:       the region queried
        source:       "real_hpi" | "fallback_flat_rate" | "not_yet_queried"
        latest_month: "YYYY-MM" string, or None if source is not real_hpi

    Populated the first time get_hpi_data() (directly or via
    adjust_price_to_current()) is called for that region in this process.
    Purely informational — never read by valuation logic.
    """
    return _hpi_diagnostics.get(region, {
        "region": region, "source": "not_yet_queried", "latest_month": None,
    })


def get_hpi_data(region: str = "England") -> Optional[pd.DataFrame]:
    """Fetch UK HPI data. Returns DataFrame with 'date' and 'average_price' columns.

    adjust_price_to_current() calls this once per comparable, and a single
    property valuation can touch several hundred comparables across the
    four evidence groups. The on-disk cache (30-day TTL) avoids repeat
    network calls, but was still re-reading and re-parsing the same JSON
    file from disk on every call (~400ms each) — this in-process cache
    avoids that: same data, read from disk once per run instead of once
    per comparable. Purely a performance change; returned values are
    identical to before.
    """
    if region in _hpi_memory_cache:
        return _hpi_memory_cache[region]

    ck = cache_key("hpi", {"region": region})
    cached = get_cached(ck, max_age_hours=720)  # cache for 30 days
    if cached and "records" in cached:
        df = pd.DataFrame(cached["records"])
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        _hpi_memory_cache[region] = df
        _record_hpi_diagnostics(region, df)
        return df

    df = _fetch_hpi_csv(region)
    if df is not None and not df.empty:
        set_cache(ck, {"records": df.to_dict("records")})
    # Memoize the result even when the fetch failed (df is None) — without
    # this, a broken/unreachable HPI source gets retried on every single
    # comparable (hundreds per property) instead of once per process, each
    # retry paying a full network round-trip. The fallback behaviour in
    # adjust_price_to_current() (flat-rate growth when hpi is None) is
    # unchanged either way — this only avoids repeating a failed call.
    _hpi_memory_cache[region] = df
    _record_hpi_diagnostics(region, df)
    return df


def _record_hpi_diagnostics(region: str, df: Optional[pd.DataFrame]) -> None:
    if df is not None and not df.empty:
        _hpi_diagnostics[region] = {
            "region": region,
            "source": "real_hpi",
            "latest_month": df["date"].max().strftime("%Y-%m"),
        }
    else:
        _hpi_diagnostics[region] = {
            "region": region,
            "source": "fallback_flat_rate",
            "latest_month": None,
        }


def _fetch_hpi_csv(region: str) -> Optional[pd.DataFrame]:
    """Try to fetch the UK HPI CSV.

    The Land Registry linked-data download does NOT have a "Date" column
    (the previous version of this function checked for one, which meant
    this always returned None and every price adjustment silently used
    the flat 3%/year fallback instead of real regional HPI data). The
    actual columns are "Period" (YYYY-MM) and "Pivotable date"
    (YYYY-MM-01, directly parseable) — this uses "Pivotable date".
    """
    try:
        url = f"https://landregistry.data.gov.uk/app/ukhpi/download/new.csv?from=2015-01-01&location=http%3A%2F%2Flandregistry.data.gov.uk%2Fid%2Fregion%2F{_region_slug(region)}"
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200 and len(resp.text) > 100:
            from io import StringIO
            df = pd.read_csv(StringIO(resp.text))
            date_col = "Pivotable date" if "Pivotable date" in df.columns else (
                "Period" if "Period" in df.columns else None
            )
            if date_col and "Average price All property types" in df.columns:
                df = df[[date_col, "Average price All property types"]].copy()
                df.columns = ["date", "average_price"]
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df["average_price"] = pd.to_numeric(df["average_price"], errors="coerce")
                df = df.dropna(subset=["date", "average_price"])
                df = df.sort_values("date")
                if not df.empty:
                    return df
    except Exception:
        pass

    return None


def _region_slug(region: str) -> str:
    """Convert a region name to the Land Registry URL slug."""
    mapping = {
        "england": "england",
        "wales": "wales",
        "england and wales": "england-and-wales",
        "north west": "north-west",
        "south east": "south-east",
        "east midlands": "east-midlands",
        "west midlands": "west-midlands",
        "yorkshire": "yorkshire-and-the-humber",
        "north east": "north-east",
        "south west": "south-west",
        "east of england": "east-of-england",
        "london": "london",
        "wirral": "wirral",
        "oxfordshire": "oxfordshire",
    }
    return mapping.get(region.lower(), "england")


def adjust_price_to_current(
    price: float,
    sale_date: str,
    region: str = "England",
) -> float:
    """Adjust a historic sale price to current-equivalent using HPI or fallback growth."""
    if not price or not sale_date:
        return price

    try:
        sale_dt = pd.to_datetime(sale_date)
    except (ValueError, TypeError):
        return price

    hpi = get_hpi_data(region)

    if hpi is not None and not hpi.empty:
        return _adjust_with_hpi(price, sale_dt, hpi)

    return _adjust_with_flat_rate(price, sale_dt)


def _adjust_with_hpi(price: float, sale_dt, hpi: pd.DataFrame) -> float:
    """Adjust using actual HPI data."""
    hpi = hpi.sort_values("date")

    # Find closest HPI row to sale date
    diffs = (hpi["date"] - sale_dt).abs()
    sale_idx = diffs.idxmin()
    sale_hpi = hpi.loc[sale_idx, "average_price"]

    # Latest HPI value
    current_hpi = hpi.iloc[-1]["average_price"]

    if sale_hpi and sale_hpi > 0:
        return price * (current_hpi / sale_hpi)
    return price


def _adjust_with_flat_rate(price: float, sale_dt) -> float:
    """Fallback: adjust using flat annual growth rate."""
    now = datetime.now()
    years = (now - sale_dt).days / 365.25
    if years <= 0:
        return price
    return price * ((1 + NATIONAL_ANNUAL_GROWTH_PCT / 100) ** years)


def get_annual_growth(region: str = "England", years: int = 5) -> Optional[float]:
    """Calculate average annual growth rate over the given period."""
    hpi = get_hpi_data(region)
    if hpi is None or hpi.empty:
        return NATIONAL_ANNUAL_GROWTH_PCT

    hpi = hpi.sort_values("date")
    current = hpi.iloc[-1]["average_price"]

    target_date = hpi.iloc[-1]["date"] - pd.DateOffset(years=years)
    diffs = (hpi["date"] - target_date).abs()
    past_idx = diffs.idxmin()
    past_val = hpi.loc[past_idx, "average_price"]

    if past_val and past_val > 0:
        total_growth = current / past_val
        annual = (total_growth ** (1 / years)) - 1
        return round(annual * 100, 2)

    return NATIONAL_ANNUAL_GROWTH_PCT
