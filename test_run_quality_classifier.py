"""Tests for validate_baseline.py's run-quality classifier.

Read-only harness improvement -- does not touch valuation logic, comparable
retrieval, or evidence calculations. All cases below are drawn from real
observed rows: two confirmed environmental-corruption incidents (Pipers
Close in the first expansion batch, properties #47-52 in the third, both
showing elapsed_seconds == 0.0 exactly) plus a genuine ambiguous live case
(property #43, 18 Victoria Hudson Quarter York, elapsed=0.5s, reproduced
identically on rerun) that exposed an earlier version of this classifier
using an unverified "< 1.0s" buffer instead of the exact observed value.
Run directly: python test_run_quality_classifier.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# validate_baseline.py runs main() only under __main__, so a plain module
# exec (without setting __name__) is safe here -- mirrors the pattern
# test_location_assessment.py/test_recommendation_shape.py already use
# for scripts that aren't proper importable packages.
_src = open(os.path.join(os.path.dirname(__file__), "validate_baseline.py"), encoding="utf-8").read()
_ns = {"__file__": "validate_baseline.py"}
exec(compile(_src, "validate_baseline.py", "exec"), _ns)
_classify_run_quality = _ns["_classify_run_quality"]
CONFIRMED_CORRUPTION_ELAPSED_SECONDS = _ns["CONFIRMED_CORRUPTION_ELAPSED_SECONDS"]
GENUINE_FAILURE_MIN_OBSERVED_SECONDS = _ns["GENUINE_FAILURE_MIN_OBSERVED_SECONDS"]


def test_confirmed_corruption_signature():
    """Exact field values from Property #37's and properties #47-52's
    original (corrupted) rows -- elapsed_seconds == 0.0 exactly."""
    row = {"elapsed_seconds": 0.0, "v1_value": 0, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "CONFIRMED_ENVIRONMENTAL_INVALID"
    print("OK: exact confirmed corruption signature (0.0s, v1=v2=0, no error) -> CONFIRMED_ENVIRONMENTAL_INVALID")


def test_ambiguous_fast_empty_result_is_suspect_not_confirmed():
    """Property #43's real first-pass values (0.5s, v1=v2=0, no error) --
    the case that exposed the old classifier's unverified '< 1.0s' buffer.
    Must be SUSPECT, not CONFIRMED -- 0.5s was never itself observed in a
    confirmed corruption incident."""
    row = {"elapsed_seconds": 0.5, "v1_value": 0, "v2_value": 0, "error": None}
    result = _classify_run_quality(row)
    assert result == "SUSPECT_ENVIRONMENTAL", result
    print("OK: property #43's real values (0.5s, v1=v2=0) -> SUSPECT_ENVIRONMENTAL, not CONFIRMED")


def test_genuine_slow_empty_evidence_is_genuine_failure():
    """Real observed genuine zero-evidence result (Valley Park, 4.8s) --
    the fastest confirmed-genuine case, defining the lower bound of the
    confirmed-genuine range."""
    row = {"elapsed_seconds": 4.8, "v1_value": 0, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "GENUINE_FAILURE"
    print("OK: genuine slow empty-evidence result (4.8s) -> GENUINE_FAILURE, not flagged for rerun")


def test_fast_genuine_success_not_flagged():
    """Real observed fast cache-hit success (Coral Springs Way, 0.5s, real
    non-zero values) must NOT be flagged just for being fast -- v2 > 0
    always wins regardless of timing."""
    row = {"elapsed_seconds": 0.5, "v1_value": 357000, "v2_value": 378700, "error": None}
    assert _classify_run_quality(row) == "SUCCESS"
    print("OK: fast but genuine cache-hit success -> SUCCESS, not flagged")


def test_exception_is_genuine_failure():
    row = {"elapsed_seconds": 12.3, "v1_value": None, "v2_value": None, "error": "ConnectionError"}
    assert _classify_run_quality(row) == "GENUINE_FAILURE"
    print("OK: exception-carrying row -> GENUINE_FAILURE regardless of timing")


def test_ambiguous_band_boundaries():
    """Values strictly between the confirmed-corrupt point (0.0s) and the
    confirmed-genuine floor (4.8s) are SUSPECT, not silently rounded into
    either confirmed tier."""
    for elapsed in [0.1, 1.0, 2.5, 4.7]:
        row = {"elapsed_seconds": elapsed, "v1_value": 0, "v2_value": 0, "error": None}
        result = _classify_run_quality(row)
        assert result == "SUSPECT_ENVIRONMENTAL", f"elapsed={elapsed} -> {result}"
    print("OK: entire ambiguous band (0.1s-4.7s, empty output) -> SUSPECT_ENVIRONMENTAL")


def test_genuine_failure_floor_is_inclusive():
    row = {"elapsed_seconds": GENUINE_FAILURE_MIN_OBSERVED_SECONDS, "v1_value": 0, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "GENUINE_FAILURE"
    print(f"OK: elapsed exactly at the genuine-failure floor ({GENUINE_FAILURE_MIN_OBSERVED_SECONDS}s) -> GENUINE_FAILURE")


def test_only_v2_zero_treated_as_empty_output():
    """If only v2 is zero (v1 nonzero), the result is still 'empty' from
    V2's perspective (the primary engine) -- classified by the same
    elapsed-time rules as any other empty V2 result, not silently treated
    as a success just because V1 found something."""
    row = {"elapsed_seconds": 0.3, "v1_value": 250000, "v2_value": 0, "error": None}
    result = _classify_run_quality(row)
    assert result == "SUSPECT_ENVIRONMENTAL", result
    print("OK: only V2 zero (V1 nonzero, ambiguous timing) -> SUSPECT_ENVIRONMENTAL (V2-empty rules apply)")


def test_repeatability_promotes_suspect_to_genuine_failure():
    """Simulates the real property #43 outcome: first pass SUSPECT, rerun
    reproduces the identical pattern. The harness's main() loop (not the
    classifier itself) is responsible for promoting a reproduced
    SUSPECT/CONFIRMED tier to GENUINE_FAILURE -- this test documents and
    locks in that expected behaviour at the classifier level, confirming
    both passes independently classify the same way (a precondition for
    main()'s repeatability check to fire correctly)."""
    first_pass = {"elapsed_seconds": 0.5, "v1_value": 0, "v2_value": 0, "error": None}
    rerun = {"elapsed_seconds": 0.5, "v1_value": 0, "v2_value": 0, "error": None}
    t1 = _classify_run_quality(first_pass)
    t2 = _classify_run_quality(rerun)
    assert t1 == t2 == "SUSPECT_ENVIRONMENTAL"
    print("OK: reproduced SUSPECT_ENVIRONMENTAL result classifies identically on both passes "
          "(main()'s loop promotes this to GENUINE_FAILURE on reproduction)")


if __name__ == "__main__":
    test_confirmed_corruption_signature()
    test_ambiguous_fast_empty_result_is_suspect_not_confirmed()
    test_genuine_slow_empty_evidence_is_genuine_failure()
    test_fast_genuine_success_not_flagged()
    test_exception_is_genuine_failure()
    test_ambiguous_band_boundaries()
    test_genuine_failure_floor_is_inclusive()
    test_only_v2_zero_treated_as_empty_output()
    test_repeatability_promotes_suspect_to_genuine_failure()
    print("\nALL RUN-QUALITY CLASSIFIER TESTS PASSED")
