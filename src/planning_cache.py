"""Read-through cache for the Planning Data API.

Wraps every planning constraint lookup (_check_constraints in planning.py)
so repeated runs against the same location do not re-issue the same six
HTTP requests every time. Reuses the pattern established by geocode/HPI/
Land Registry caching (src/utils.py) but with its own storage layout,
since planning responses need richer validity tracking — a failed or
rate-limited response must never silently overwrite a good cached one —
and a distinct per-source directory structure for readability:

    data/cache/planning/<source>/<cache_key>.json

Each cache file records the source dataset, the exact query parameters,
when it was generated, the request URL, the response status, the response
payload, and a parser_version — enough to audit or reproduce any cached
decision without re-querying the API.

Query identity: the Planning Data API's /point endpoint used here takes
only latitude/longitude (no radius or date-range parameter exists in the
current planning.py call pattern). The cache key is therefore derived from
whatever query_params dict is passed in — lat/lng today, but the key
function is generic, so a future caller adding radius/date/endpoint
variants only needs to include them in query_params to get a distinct key.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Configuration ----------------------------------------------------
# Module-level, matching this codebase's existing convention for cache
# settings (see CACHE_DIR in utils.py, _GEOCODE_BATCH_MAX_WORKERS in
# transport.py) rather than the dataclass-based domain config in
# config.py, which covers valuation weights/thresholds, not I/O plumbing.
PLANNING_CACHE_ENABLED = True
PLANNING_CACHE_REFRESH = False
PLANNING_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "planning"

# 90 days: statutory planning designations (conservation areas, listed
# buildings, green belt, Article 4 directions, flood zones) move at the
# pace of local plan reviews and periodic Environment Agency remapping —
# annual at the fastest. See ROADMAP.md item 3 for the full TTL rationale;
# this mirrors that decision.
PLANNING_CACHE_MAX_AGE_HOURS = 24 * 90

PARSER_VERSION = "planning-cache-v1"

# HTTP statuses that must never be cached, and must never overwrite an
# existing valid cache entry.
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
_AUTH_STATUSES = {401, 403}


@dataclass
class CachedPlanningResponse:
    """Result of a single cached (or cache-attempted) planning lookup."""
    hit: bool                  # served from cache (fresh hit OR failure fallback)
    stale_fallback: bool       # True only when served from cache BECAUSE the live call failed
    status: str                 # "cache_hit" | "fetched" | "refreshed" | "fallback_to_cache" | "no_data"
    payload: Optional[dict]     # the API response body, or None if genuinely unavailable
    is_zero_result: bool = False


def _cache_key(query_params: dict) -> str:
    """Deterministic key: same params -> same key, different params (any
    field) -> different key. Not tied to a specific parameter set, so
    query_params can carry lat/lng today and radius/date/source variants
    later without changing this function.
    """
    raw = json.dumps(query_params, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _cache_path(source: str, key: str) -> Path:
    return PLANNING_CACHE_DIR / source / f"{key}.json"


def _read_cache(source: str, key: str) -> Optional[dict]:
    path = _cache_path(source, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _is_cache_fresh(entry: dict) -> bool:
    try:
        generated_at = datetime.fromisoformat(entry["generated_at"])
    except (KeyError, ValueError, TypeError):
        return False
    age_hours = (datetime.now() - generated_at).total_seconds() / 3600
    return age_hours <= PLANNING_CACHE_MAX_AGE_HOURS


def _write_cache(source: str, key: str, entry: dict) -> None:
    path = _cache_path(source, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")


def _is_valid_response(status_code: Optional[int], payload) -> bool:
    """A response is cacheable if it's a genuine, well-formed API answer —
    including a legitimate zero-result answer (status 200, well-formed
    dict body, count/results simply empty). Timeouts/exceptions (signalled
    by status_code=None), retryable failures (429/5xx), auth errors
    (401/403), non-200 statuses, and malformed (non-dict) bodies are never
    cacheable, so they can never overwrite a good cached entry.
    """
    if status_code is None:
        return False
    if status_code in _RETRYABLE_STATUSES or status_code in _AUTH_STATUSES:
        return False
    if status_code != 200:
        return False
    if not isinstance(payload, dict):
        return False
    return True


def fetch_with_cache(
    source: str,
    request_url: str,
    query_params: dict,
    fetch_fn: Callable[[], Tuple[Optional[int], Optional[dict]]],
) -> CachedPlanningResponse:
    """Read-through cache around a single planning dataset lookup.

    fetch_fn() is called only on a cache miss, or unconditionally when
    PLANNING_CACHE_REFRESH is True. It must return (status_code, payload):
    status_code=None signals an exception/timeout occurred during the call.

    Behaviour:
    - PLANNING_CACHE_ENABLED=False: caching is bypassed entirely, fetch_fn
      is always called, and its result is never written to disk.
    - Fresh cache hit (and not in refresh mode): returned without calling
      fetch_fn at all.
    - Cache miss, or refresh mode: fetch_fn is called. A valid response is
      written to cache (refresh mode included — this is exactly how a
      forced refresh overwrites a stale entry with a fresh one).
    - Invalid/failed response: never written to cache. If a prior valid
      cache entry exists (even a stale one, by age), it is used as a
      fallback with a warning logged. If no cache exists at all, a
      controlled no-data result (payload=None) is returned rather than
      raising — matching the existing caller's tolerance for missing
      planning data.
    """
    key = _cache_key(query_params)

    if PLANNING_CACHE_ENABLED and not PLANNING_CACHE_REFRESH:
        cached = _read_cache(source, key)
        if cached is not None and _is_cache_fresh(cached):
            logger.info("planning_cache HIT source=%s key=%s", source, key)
            return CachedPlanningResponse(
                hit=True, stale_fallback=False, status="cache_hit",
                payload=cached.get("response_payload"),
                is_zero_result=cached.get("is_zero_result", False),
            )
        logger.info("planning_cache MISS source=%s key=%s", source, key)
    elif PLANNING_CACHE_REFRESH:
        logger.info("planning_cache REFRESH forced source=%s key=%s", source, key)

    status_code, payload = fetch_fn()

    if _is_valid_response(status_code, payload):
        is_zero = payload.get("count") == 0
        entry = {
            "source": source,
            "query_params": query_params,
            "generated_at": datetime.now().isoformat(),
            "cache_key": key,
            "request_url": request_url,
            "response_status": status_code,
            "response_payload": payload,
            "parser_version": PARSER_VERSION,
            "is_zero_result": is_zero,
        }
        result_status = "refreshed" if PLANNING_CACHE_REFRESH else "fetched"
        if PLANNING_CACHE_ENABLED:
            _write_cache(source, key, entry)
            logger.info(
                "planning_cache %s source=%s key=%s status=%s zero_result=%s",
                result_status.upper(), source, key, status_code, is_zero,
            )
        return CachedPlanningResponse(
            hit=False, stale_fallback=False, status=result_status,
            payload=payload, is_zero_result=is_zero,
        )

    # Live call failed, or returned something unsafe to cache. Fall back
    # to any existing cache — even a stale one is better than silently
    # treating "the API had a bad moment" as "there is no constraint".
    fallback = _read_cache(source, key)
    if fallback is not None:
        logger.warning(
            "planning_cache API_FAILURE source=%s key=%s status=%s -- "
            "falling back to cached response from %s",
            source, key, status_code, fallback.get("generated_at", "unknown"),
        )
        return CachedPlanningResponse(
            hit=True, stale_fallback=True, status="fallback_to_cache",
            payload=fallback.get("response_payload"),
            is_zero_result=fallback.get("is_zero_result", False),
        )

    logger.warning(
        "planning_cache API_FAILURE source=%s key=%s status=%s -- "
        "no cache available, returning no-data",
        source, key, status_code,
    )
    return CachedPlanningResponse(
        hit=False, stale_fallback=False, status="no_data", payload=None,
    )
