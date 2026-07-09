"""Shared utilities for the property valuation tool."""

import re
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def extract_postcode(text: str) -> Optional[str]:
    """Extract a UK postcode from text."""
    pattern = r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}"
    match = re.search(pattern, text.upper())
    if match:
        pc = match.group().strip()
        # Normalise spacing
        return pc[:-3].strip() + " " + pc[-3:]
    return None


def postcode_outcode(postcode: str) -> str:
    """Return the outward code (first half) of a postcode."""
    parts = postcode.strip().split()
    return parts[0] if parts else postcode


def postcode_sector(postcode: str) -> str:
    """Return the postcode sector, e.g. OX3 9."""
    parts = postcode.strip().split()
    if len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}"
    return postcode


def cache_key(prefix: str, params: dict) -> str:
    raw = json.dumps(params, sort_keys=True)
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


def get_cached(key: str, max_age_hours: int = 24) -> Optional[dict]:
    """Load cached JSON data if fresh enough."""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
        if datetime.now() - cached_at > timedelta(hours=max_age_hours):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def set_cache(key: str, data: dict):
    """Write data to cache with timestamp."""
    data["_cached_at"] = datetime.now().isoformat()
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data, default=str), encoding="utf-8")


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert to float."""
    if value is None:
        return default
    try:
        cleaned = str(value).replace(",", "").replace("£", "").strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def safe_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(safe_float(value))
    except (ValueError, TypeError):
        return default


def format_currency(value: float) -> str:
    """Format as GBP currency string."""
    if value >= 1_000_000:
        return f"£{value:,.0f}"
    return f"£{value:,.0f}"


def format_pct(value: float) -> str:
    return f"{value:+.1f}%"
