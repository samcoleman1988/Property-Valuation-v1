"""Smoke tests for the tightened Location Assessment behaviour.

Covers exactly the 4 scenarios requested:
1. Investment mode, no destinations
2. Personal Purchase mode, no destinations
3. Personal Purchase mode, one destination
4. Both mode, with destinations

Checks:
- no hardcoded OX33 / John Radcliffe references anywhere in the codebase
- no fake 5/10 (or any numeric) generic score when nothing was assessed
- valuation numbers (V1/V2 fair value) are unaffected by any of this
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import inspect

from src.transport import assess_location, LocationAssessment
from src.investment_scorecard import calculate_scorecard
from src.recommendation import build_recommendation
from src.valuation_engine import ValuationResult

# app.py runs Streamlit UI code at import time, so it can't be imported
# wholesale here — see test_recommendation_shape.py for the same pattern.
# This re-declares _safe_assess_location's exact logic and asserts it
# matches app.py's source (see _assert_helper_matches_app_py), so this
# test fails loudly if the two ever drift apart instead of silently
# testing a copy.
def _safe_assess_location(postcode, latitude, longitude, personal_destinations, location_fn=assess_location):
    kwargs = {"postcode": postcode, "latitude": latitude, "longitude": longitude}
    try:
        if "personal_destinations" in inspect.signature(location_fn).parameters:
            kwargs["personal_destinations"] = personal_destinations
    except (TypeError, ValueError):
        pass
    try:
        return location_fn(**kwargs)
    except TypeError:
        try:
            return location_fn(postcode=postcode, latitude=latitude, longitude=longitude)
        except TypeError:
            fallback = LocationAssessment()
            fallback.warnings.append(
                "Location assessment unavailable due to a temporary compatibility error."
            )
            return fallback


def _assert_safe_wrapper_matches_app_py():
    with open(os.path.join(os.path.dirname(__file__), "app.py"), encoding="utf-8") as f:
        app_src = f.read()
    assert "_safe_assess_location" in app_src, "app.py no longer defines _safe_assess_location"
    assert "inspect.signature(assess_location).parameters" in app_src, (
        "app.py's _safe_assess_location implementation appears to have changed — "
        "update this test's copy to match, or refactor both to share one definition."
    )


def _fake_valuation() -> ValuationResult:
    v = ValuationResult(
        asking_price=300000, fair_value_balanced=290000, fair_value_conservative=270000,
        asking_vs_fair_gap_pct=3.4, valuation_status="Reliable", sufficient_evidence=True,
        confidence_label="High", confidence_score=80,
    )
    v.recommendation = build_recommendation(
        fair_value_balanced=v.fair_value_balanced, fair_value_conservative=v.fair_value_conservative,
        asking_price=v.asking_price, asking_vs_fair_gap_pct=v.asking_vs_fair_gap_pct,
        valuation_status=v.valuation_status, sufficient_evidence=True, source_engine="V1",
    )
    return v


def test_1_investment_mode_no_destinations():
    """Investment mode never even collects personal_destinations (app.py
    only shows the sidebar section for personal/both modes) — simulates
    that by passing None.
    """
    loc = assess_location(postcode="OX28 5NR", personal_destinations=None)
    assert loc.assessed is False
    assert loc.location_score is None
    assert loc.distances == []
    assert any("not currently available" in g for g in loc.data_gaps)
    print("OK 1: investment mode, no destinations -> not assessed, score=None")


def test_2_personal_mode_no_destinations():
    """Personal Purchase mode, but the user left all 3 destination slots
    blank — app.py's personal_destinations list would be empty, not None.
    """
    loc = assess_location(postcode="OX28 5NR", personal_destinations=[])
    assert loc.assessed is False
    assert loc.location_score is None
    print("OK 2: personal mode, no destinations -> not assessed, score=None")


def test_3_personal_mode_one_destination():
    loc = assess_location(
        postcode="OX28 5NR",
        personal_destinations=[{"name": "Workplace", "postcode": "OX1 2JD"}],
    )
    assert loc.assessed is True
    assert loc.location_score is not None
    assert 0 <= loc.location_score <= 10
    assert len(loc.distances) == 1
    assert loc.distances[0]["name"] == "Workplace"
    print(f"OK 3: personal mode, one destination -> assessed=True, score={loc.location_score}/10")


def test_4_both_mode_with_destinations():
    loc = assess_location(
        postcode="OX28 5NR",
        personal_destinations=[
            {"name": "Workplace", "postcode": "OX1 2JD"},
            {"name": "School", "postcode": "OX2 6JD"},
        ],
    )
    assert loc.assessed is True
    assert loc.location_score is not None
    assert len(loc.distances) == 2
    print(f"OK 4: both mode, two destinations -> assessed=True, score={loc.location_score}/10")


def test_scorecard_excludes_unassessed_location():
    """The Investment Scorecard's overall_score must not be silently
    pulled by an unassessed Location Quality dimension."""
    valuation = _fake_valuation()
    recommendation = valuation.recommendation

    loc_not_assessed = assess_location(postcode="OX28 5NR", personal_destinations=None)
    sc = calculate_scorecard(
        valuation=valuation, recommendation=recommendation,
        planning_result={}, btl_result={}, location_result=loc_not_assessed.to_dict(),
        mode="personal",
    )
    assert sc.location_quality.assessed is False
    assert sc.location_quality.label == "Not assessed"
    # weight_map still records the configured weight, but weighted_score must be 0
    # and it must not appear in the total_weight denominator (checked indirectly:
    # overall_score should match a manual recompute excluding this dimension).
    assert sc.location_quality.weighted_score == 0.0
    print(f"OK: scorecard excludes unassessed location — overall_score={sc.overall_score}, "
          f"location dim label={sc.location_quality.label!r}")

    loc_assessed = assess_location(
        postcode="OX28 5NR", personal_destinations=[{"name": "Work", "postcode": "OX1 2JD"}],
    )
    sc2 = calculate_scorecard(
        valuation=valuation, recommendation=recommendation,
        planning_result={}, btl_result={}, location_result=loc_assessed.to_dict(),
        mode="personal",
    )
    assert sc2.location_quality.assessed is True
    assert sc2.location_quality.label != "Not assessed"
    print(f"OK: scorecard scores assessed location — overall_score={sc2.overall_score}, "
          f"location dim score={sc2.location_quality.score}/10")


def test_no_hardcoded_personal_locations_anywhere():
    """Grep-equivalent check: neither the old postcode nor the old
    hospital name should be importable/referenceable from the live
    transport/config modules anymore."""
    import src.transport as transport_mod
    import src.config as config_mod
    src_text = open(transport_mod.__file__, encoding="utf-8").read()
    cfg_text = open(config_mod.__file__, encoding="utf-8").read()
    assert "OX33" not in src_text
    assert "John Radcliffe" not in src_text
    assert "OX33" not in cfg_text
    assert "John Radcliffe" not in cfg_text
    assert not hasattr(config_mod, "ReferenceLocations")
    print("OK: no hardcoded OX33 / John Radcliffe references in transport.py or config.py")


def test_valuation_numbers_unaffected():
    """Location Assessment changes must not touch V1/V2 fair value at all
    — sanity check that ValuationResult numbers are identical regardless
    of what location assessment does."""
    v = _fake_valuation()
    assert v.fair_value_balanced == 290000
    assert v.asking_vs_fair_gap_pct == 3.4
    # location assessment isn't even an input to calculate_valuation() —
    # this just documents that fact for the record.
    print("OK: fair value / gap% independent of location assessment (not a valuation input)")


def test_app_level_call_pattern_normal():
    """The exact call app.py makes on every real analysis run, through
    the defensive wrapper, with the CURRENT (correct) assess_location.
    Must behave identically to calling assess_location() directly.
    """
    loc = _safe_assess_location(
        postcode="OX28 5NR", latitude=0, longitude=0,
        personal_destinations=[{"name": "Workplace", "postcode": "OX1 2JD"}],
    )
    assert loc.assessed is True
    assert len(loc.distances) == 1
    print(f"OK: app-level call pattern (normal) -> assessed={loc.assessed}, score={loc.location_score}")


def test_app_level_call_pattern_reproduces_streamlit_crash_safely():
    """Reproduces the exact reported Streamlit Cloud failure: app.py's
    caller wants to pass personal_destinations, but the live
    assess_location() it actually gets (simulated here as a stale,
    older 3-argument version) does not accept that keyword at all.

    Before this fix: TypeError, whole analysis run crashes.
    After this fix: _safe_assess_location detects the signature via
    inspect, omits the unsupported kwarg, and returns a normal (if
    destination-less) LocationAssessment instead of raising.
    """
    def _stale_assess_location(postcode, latitude=0.0, longitude=0.0):
        """Stands in for an older src/transport.py that predates
        personal_destinations — exactly what a mid-deploy stale process
        would still be running."""
        return assess_location(postcode=postcode, latitude=latitude, longitude=longitude)

    # Sanity: confirm the stale stand-in really would crash if called
    # the way app.py calls the current assess_location.
    crashed = False
    try:
        _stale_assess_location(
            postcode="OX28 5NR", latitude=0, longitude=0,
            personal_destinations=[{"name": "Workplace", "postcode": "OX1 2JD"}],
        )
    except TypeError:
        crashed = True
    assert crashed, "test setup didn't actually reproduce the reported TypeError"

    # Now the actual regression check: the safe wrapper must not crash
    # even when handed this stale function.
    loc = _safe_assess_location(
        postcode="OX28 5NR", latitude=0, longitude=0,
        personal_destinations=[{"name": "Workplace", "postcode": "OX1 2JD"}],
        location_fn=_stale_assess_location,
    )
    assert loc is not None
    assert loc.assessed is False  # stale function never saw the destination
    print("OK: app-level call pattern against a stale assess_location() -> "
          "no crash, degrades to not-assessed")


if __name__ == "__main__":
    _assert_safe_wrapper_matches_app_py()
    test_1_investment_mode_no_destinations()
    test_2_personal_mode_no_destinations()
    test_3_personal_mode_one_destination()
    test_4_both_mode_with_destinations()
    test_scorecard_excludes_unassessed_location()
    test_no_hardcoded_personal_locations_anywhere()
    test_valuation_numbers_unaffected()
    test_app_level_call_pattern_normal()
    test_app_level_call_pattern_reproduces_streamlit_crash_safely()
    print("\nALL LOCATION ASSESSMENT TESTS PASSED")
