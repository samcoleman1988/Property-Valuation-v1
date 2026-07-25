"""Tests for validate_baseline.py's run-quality classifier.

Read-only harness improvement — does not touch valuation logic, comparable
retrieval, or evidence calculations. All cases below are drawn from real
observed rows (two confirmed environmental-corruption incidents: Pipers
Close in the first expansion batch, properties #47-52 in the third), not
invented thresholds. Run directly: python test_run_quality_classifier.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# validate_baseline.py runs main() only under __main__, so a plain module
# exec (without setting __name__) is safe here — mirrors the pattern
# test_location_assessment.py/test_recommendation_shape.py already use
# for scripts that aren't proper importable packages.
_src = open(os.path.join(os.path.dirname(__file__), "validate_baseline.py"), encoding="utf-8").read()
_ns = {"__file__": "validate_baseline.py"}
exec(compile(_src, "validate_baseline.py", "exec"), _ns)
_classify_run_quality = _ns["_classify_run_quality"]
ENV_INVALID_ELAPSED_THRESHOLD_SECONDS = _ns["ENV_INVALID_ELAPSED_THRESHOLD_SECONDS"]


def test_confirmed_corruption_signature_flagged():
    """Exact field values from Property #37's original (corrupted) row."""
    row = {"elapsed_seconds": 0.0, "v1_value": 0, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "environmental_invalid"
    print("OK: confirmed real corruption signature (0.0s, v1=v2=0, no error) -> environmental_invalid")


def test_confirmed_corruption_batch_signature_flagged():
    """Exact field values from properties #47-52's original (corrupted) rows."""
    for row in [
        {"elapsed_seconds": 0.0, "v1_value": 0, "v2_value": 0, "error": None},
    ] * 6:
        assert _classify_run_quality(row) == "environmental_invalid"
    print("OK: all 6 confirmed batch-corruption rows (#47-52 signature) -> environmental_invalid")


def test_genuine_slow_empty_evidence_not_flagged():
    """Real observed genuine zero-evidence result (Valley Park, 4.8s) must
    NOT be flagged — it took real, measurable time to determine there was
    no evidence, unlike the corruption cases."""
    row = {"elapsed_seconds": 4.8, "v1_value": 0, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "genuine_failure"
    print("OK: genuine slow empty-evidence result -> genuine_failure, not flagged")


def test_fast_genuine_success_not_flagged():
    """Real observed fast cache-hit success (Coral Springs Way, 0.5s, real
    non-zero values) must NOT be flagged just for being fast."""
    row = {"elapsed_seconds": 0.5, "v1_value": 357000, "v2_value": 378700, "error": None}
    assert _classify_run_quality(row) == "success"
    print("OK: fast but genuine cache-hit success -> success, not flagged")


def test_exception_is_genuine_failure():
    row = {"elapsed_seconds": 12.3, "v1_value": None, "v2_value": None, "error": "ConnectionError"}
    assert _classify_run_quality(row) == "genuine_failure"
    print("OK: exception-carrying row -> genuine_failure")


def test_threshold_boundary_is_strict():
    """Elapsed exactly at the threshold must NOT be flagged (strict <, not
    <=) -- avoids flagging a plausible-if-fast genuine result sitting
    exactly on the boundary."""
    row = {"elapsed_seconds": ENV_INVALID_ELAPSED_THRESHOLD_SECONDS, "v1_value": 0, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "genuine_failure"
    print(f"OK: elapsed exactly at threshold ({ENV_INVALID_ELAPSED_THRESHOLD_SECONDS}s) -> genuine_failure, not flagged")


def test_only_v2_zero_is_not_environmental():
    """If only v2 is zero (v1 nonzero), this doesn't match the confirmed
    both-engines-zero corruption signature -- treated as a genuine
    (if incomplete) result, not auto-rerun."""
    row = {"elapsed_seconds": 0.3, "v1_value": 250000, "v2_value": 0, "error": None}
    assert _classify_run_quality(row) == "genuine_failure"
    print("OK: only V2 zero (V1 nonzero) -> genuine_failure, not environmental_invalid")


if __name__ == "__main__":
    test_confirmed_corruption_signature_flagged()
    test_confirmed_corruption_batch_signature_flagged()
    test_genuine_slow_empty_evidence_not_flagged()
    test_fast_genuine_success_not_flagged()
    test_exception_is_genuine_failure()
    test_threshold_boundary_is_strict()
    test_only_v2_zero_is_not_environmental()
    print("\nALL RUN-QUALITY CLASSIFIER TESTS PASSED")
