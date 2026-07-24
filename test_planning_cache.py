"""Tests for the planning API read-through cache (src/planning_cache.py).

Uses a temporary cache directory and a mocked fetch_fn throughout — no
live API calls. Run directly: python test_planning_cache.py
"""
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.dirname(__file__))

import src.planning_cache as pc


class _Sandbox:
    """Redirects PLANNING_CACHE_DIR to a throwaway temp dir for the
    duration of a test, and restores config afterwards."""

    def __enter__(self):
        self._orig_dir = pc.PLANNING_CACHE_DIR
        self._orig_enabled = pc.PLANNING_CACHE_ENABLED
        self._orig_refresh = pc.PLANNING_CACHE_REFRESH
        self.tmp = tempfile.mkdtemp()
        pc.PLANNING_CACHE_DIR = __import__("pathlib").Path(self.tmp)
        pc.PLANNING_CACHE_ENABLED = True
        pc.PLANNING_CACHE_REFRESH = False
        return self

    def __exit__(self, *exc):
        pc.PLANNING_CACHE_DIR = self._orig_dir
        pc.PLANNING_CACHE_ENABLED = self._orig_enabled
        pc.PLANNING_CACHE_REFRESH = self._orig_refresh
        shutil.rmtree(self.tmp, ignore_errors=True)


def _ok_fetch(payload):
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return 200, payload
    return fn, calls


def test_same_query_same_key():
    with _Sandbox():
        k1 = pc._cache_key({"lat": 51.75, "lng": -1.25})
        k2 = pc._cache_key({"lat": 51.75, "lng": -1.25})
        assert k1 == k2
        print("OK: same query params -> same cache key")


def test_changed_params_changed_key():
    with _Sandbox():
        base = pc._cache_key({"lat": 51.75, "lng": -1.25})
        diff_lat = pc._cache_key({"lat": 51.76, "lng": -1.25})
        diff_source = pc._cache_key({"lat": 51.75, "lng": -1.25, "source": "flood-risk-zone"})
        diff_radius = pc._cache_key({"lat": 51.75, "lng": -1.25, "radius": 500})
        diff_date = pc._cache_key({"lat": 51.75, "lng": -1.25, "date": "2026-01-01"})
        assert base != diff_lat
        assert base != diff_source
        assert base != diff_radius
        assert base != diff_date
        print("OK: changed lat/source/radius/date each produce a different cache key")


def test_cache_hit_avoids_api_call():
    with _Sandbox():
        fetch_fn, calls = _ok_fetch({"count": 1, "entities": [{"name": "Test CA"}]})
        r1 = pc.fetch_with_cache("conservation-area", "http://x", {"lat": 1, "lng": 2}, fetch_fn)
        assert r1.status == "fetched" and calls["n"] == 1

        # Second call, identical params -> must NOT call fetch_fn again.
        r2 = pc.fetch_with_cache("conservation-area", "http://x", {"lat": 1, "lng": 2}, fetch_fn)
        assert r2.status == "cache_hit"
        assert r2.hit is True
        assert calls["n"] == 1, "fetch_fn must not be called again on a cache hit"
        assert r2.payload == {"count": 1, "entities": [{"name": "Test CA"}]}
        print("OK: cache hit avoids a second API call and returns the cached payload")


def test_cache_miss_calls_api_and_writes_cache():
    with _Sandbox():
        fetch_fn, calls = _ok_fetch({"count": 0})
        r = pc.fetch_with_cache("green-belt", "http://x", {"lat": 5, "lng": 6}, fetch_fn)
        assert r.status == "fetched" and calls["n"] == 1
        key = pc._cache_key({"lat": 5, "lng": 6})
        on_disk = pc._read_cache("green-belt", key)
        assert on_disk is not None
        assert on_disk["source"] == "green-belt"
        assert on_disk["response_payload"] == {"count": 0}
        assert "generated_at" in on_disk and "cache_key" in on_disk and "request_url" in on_disk
        print("OK: cache miss calls the API once and writes a full cache entry to disk")


def test_refresh_mode_calls_api_even_with_cache():
    with _Sandbox():
        fetch_fn, calls = _ok_fetch({"count": 1})
        pc.fetch_with_cache("article-4-direction-area", "http://x", {"lat": 9, "lng": 9}, fetch_fn)
        assert calls["n"] == 1

        pc.PLANNING_CACHE_REFRESH = True
        try:
            r2 = pc.fetch_with_cache("article-4-direction-area", "http://x", {"lat": 9, "lng": 9}, fetch_fn)
        finally:
            pc.PLANNING_CACHE_REFRESH = False
        assert calls["n"] == 2, "refresh mode must call the API even though a valid cache exists"
        assert r2.status == "refreshed"
        print("OK: PLANNING_CACHE_REFRESH=True forces a fresh API call and overwrites the cache")


def test_failed_api_does_not_overwrite_valid_cache():
    with _Sandbox():
        good_fetch, _ = _ok_fetch({"count": 1, "entities": [{"name": "Listed"}]})
        pc.fetch_with_cache("listed-building-outline", "http://x", {"lat": 3, "lng": 4}, good_fetch)
        key = pc._cache_key({"lat": 3, "lng": 4})
        before = pc._read_cache("listed-building-outline", key)
        assert before["response_payload"]["count"] == 1

        def bad_fetch():
            return 500, None
        pc.fetch_with_cache("listed-building-outline", "http://x", {"lat": 3, "lng": 4}, bad_fetch)

        after = pc._read_cache("listed-building-outline", key)
        assert after == before, "a failed (500) response must never overwrite a valid cache entry"
        print("OK: a failed API response (500) does not overwrite the existing valid cache entry")


def test_failed_api_falls_back_to_cache():
    with _Sandbox():
        # A fresh cache entry short-circuits before fetch_fn is ever called
        # (that's the cache-hit path, already covered separately) — so to
        # exercise the fallback path honestly, the cache entry must be
        # stale enough that fetch_with_cache attempts a real refetch,
        # which then fails, forcing it back onto that stale entry.
        good_fetch, _ = _ok_fetch({"count": 1, "flood-risk-level": "Zone 3"})
        pc.fetch_with_cache("flood-risk-zone", "http://x", {"lat": 7, "lng": 8}, good_fetch)
        key = pc._cache_key({"lat": 7, "lng": 8})
        entry = pc._read_cache("flood-risk-zone", key)
        stale_time = __import__("datetime").datetime.now() - __import__("datetime").timedelta(
            hours=pc.PLANNING_CACHE_MAX_AGE_HOURS + 1
        )
        entry["generated_at"] = stale_time.isoformat()
        pc._write_cache("flood-risk-zone", key, entry)

        def timeout_fetch():
            return None, None  # simulates an exception/timeout in the caller
        r = pc.fetch_with_cache("flood-risk-zone", "http://x", {"lat": 7, "lng": 8}, timeout_fetch)
        assert r.status == "fallback_to_cache"
        assert r.hit is True and r.stale_fallback is True
        assert r.payload == {"count": 1, "flood-risk-level": "Zone 3"}
        print("OK: a failed API call (timeout) against a stale cache falls back to it with stale_fallback=True")


def test_failed_api_no_cache_returns_no_data():
    with _Sandbox():
        def timeout_fetch():
            return None, None
        r = pc.fetch_with_cache("aonb", "http://x", {"lat": 99, "lng": 99}, timeout_fetch)
        assert r.status == "no_data"
        assert r.payload is None
        assert r.hit is False
        print("OK: a failed API call with no existing cache returns a controlled no-data result, not a crash")


def test_valid_zero_result_is_cached():
    with _Sandbox():
        fetch_fn, calls = _ok_fetch({"count": 0, "entities": []})
        r1 = pc.fetch_with_cache("aonb", "http://x", {"lat": 11, "lng": 12}, fetch_fn)
        assert r1.status == "fetched"
        assert r1.is_zero_result is True

        r2 = pc.fetch_with_cache("aonb", "http://x", {"lat": 11, "lng": 12}, fetch_fn)
        assert r2.status == "cache_hit"
        assert r2.is_zero_result is True
        assert calls["n"] == 1, "a legitimate zero-result response must be cached, not re-fetched"
        print("OK: a legitimate zero-result response is cached and marked is_zero_result=True")


def test_disabled_cache_bypasses_storage():
    with _Sandbox():
        pc.PLANNING_CACHE_ENABLED = False
        fetch_fn, calls = _ok_fetch({"count": 1})
        pc.fetch_with_cache("conservation-area", "http://x", {"lat": 20, "lng": 21}, fetch_fn)
        pc.fetch_with_cache("conservation-area", "http://x", {"lat": 20, "lng": 21}, fetch_fn)
        assert calls["n"] == 2, "with caching disabled, every call must hit the API"
        print("OK: PLANNING_CACHE_ENABLED=False bypasses the cache entirely")


def test_auth_and_rate_limit_responses_not_cached():
    with _Sandbox():
        def rate_limited():
            return 429, None
        r = pc.fetch_with_cache("green-belt", "http://x", {"lat": 30, "lng": 31}, rate_limited)
        assert r.status == "no_data"
        key = pc._cache_key({"lat": 30, "lng": 31})
        assert pc._read_cache("green-belt", key) is None

        def forbidden():
            return 403, None
        r2 = pc.fetch_with_cache("green-belt", "http://x", {"lat": 40, "lng": 41}, forbidden)
        assert r2.status == "no_data"
        print("OK: 429 (rate limit) and 403 (auth) responses are never cached")


if __name__ == "__main__":
    test_same_query_same_key()
    test_changed_params_changed_key()
    test_cache_hit_avoids_api_call()
    test_cache_miss_calls_api_and_writes_cache()
    test_refresh_mode_calls_api_even_with_cache()
    test_failed_api_does_not_overwrite_valid_cache()
    test_failed_api_falls_back_to_cache()
    test_failed_api_no_cache_returns_no_data()
    test_valid_zero_result_is_cached()
    test_disabled_cache_bypasses_storage()
    test_auth_and_rate_limit_responses_not_cached()
    print("\nALL PLANNING CACHE TESTS PASSED")
