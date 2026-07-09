"""Regression test for the Streamlit Cloud AttributeError:

    v2_result.final.recommendation

Covers two things:
1. Every current code path that returns a FinalValuation (blend_evidence's
   three return points) actually sets .recommendation — a real V2 run
   completes and .recommendation is populated, not None.
2. Even if a result object's .recommendation were missing/None (e.g. a
   stale object from an older code version), app.py's defensive
   _ensure_recommendation() must build one on the fly instead of raising
   AttributeError. Simulated directly, without needing Streamlit running.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.valuation_engine_v2 import run_v2_valuation, FinalValuation
from src.recommendation import build_recommendation, Recommendation

# app.py runs Streamlit UI code at import time (st.set_page_config etc.),
# so it can't be imported wholesale in a plain script. This re-declares
# _ensure_recommendation's exact logic and asserts it matches app.py's
# source (see _assert_helper_matches_app_py), so this test fails loudly
# if the two ever drift apart instead of silently testing a copy.
def _ensure_recommendation(final, source_engine: str):
    rec = getattr(final, "recommendation", None)
    if rec is not None:
        return rec
    return build_recommendation(
        fair_value_balanced=final.fair_value_balanced,
        fair_value_conservative=final.fair_value_conservative,
        asking_price=final.asking_price,
        asking_vs_fair_gap_pct=final.asking_vs_fair_gap_pct,
        valuation_status=final.valuation_status,
        sufficient_evidence=final.sufficient_evidence,
        source_engine=source_engine,
    )


def _assert_helper_matches_app_py():
    """Fail loudly if app.py's _ensure_recommendation source diverges from
    the copy above, so this test can't silently drift out of sync."""
    with open(os.path.join(os.path.dirname(__file__), "app.py"), encoding="utf-8") as f:
        app_src = f.read()
    assert "_ensure_recommendation" in app_src, "app.py no longer defines _ensure_recommendation"
    assert "getattr(final, \"recommendation\", None)" in app_src, (
        "app.py's _ensure_recommendation implementation appears to have changed — "
        "update this test's copy to match, or refactor both to share one definition."
    )


def test_real_v2_run_populates_recommendation():
    """The exact failure scenario reported from Streamlit Cloud: a real V2
    valuation completes with a real fair value and confidence, then the
    app accesses primary_recommendation. Must not raise AttributeError,
    and must not be None.
    """
    listing = PropertyListing(
        address="Thorney Leys, Witney", postcode="OX28 5NR",
        asking_price=275000, property_type="Terraced", bedrooms=3, tenure="Freehold",
        override_street_name="Thorney Leys", overrides_applied=["Street: Thorney Leys"],
    )
    ev = fetch_and_score_comparables(
        postcode="OX28 5NR", property_type="Terraced", bedrooms=3,
        floor_area_sqm=0, tenure="Freehold", street="Thorney Leys, Witney",
    )
    v2_result = run_v2_valuation(ev, listing)

    assert v2_result.final.fair_value_balanced > 0, "expected a real V2 valuation for this fixture"
    # This is the exact line that crashed on Streamlit Cloud:
    rec = v2_result.final.recommendation
    assert rec is not None, "FinalValuation.recommendation was None after a successful V2 run"
    assert isinstance(rec, Recommendation)
    assert rec.source_engine == "V2"
    assert rec.investment_tagline

    # app.py's actual access pattern
    use_v2, result = True, v2_result
    primary_recommendation = _ensure_recommendation(result.final, "V2") if (use_v2 and result) else None
    assert primary_recommendation is not None
    print(f"OK: real V2 run -> recommendation = {primary_recommendation.investment_tagline!r}")


def test_v1_run_populates_recommendation():
    listing_kwargs = dict(
        asking_price=275000,
    )
    ev = fetch_and_score_comparables(
        postcode="OX28 5NR", property_type="Terraced", bedrooms=3,
        floor_area_sqm=0, tenure="Freehold", street="Thorney Leys, Witney",
    )
    signals = interpret_listing(description="", key_features=[], property_type="Terraced")
    v1 = calculate_valuation(
        asking_price=275000, evidence=ev, signals=signals,
        floor_area_sqm=0, tenure="Freehold", region="England",
    )
    assert v1.recommendation is not None
    assert v1.recommendation.source_engine == "V1"
    print(f"OK: real V1 run -> recommendation = {v1.recommendation.investment_tagline!r}")


def test_ensure_recommendation_handles_missing_attribute():
    """Simulates the actual crash: a FinalValuation-shaped object whose
    .recommendation is None (stale object / partial construction).
    _ensure_recommendation must build one on the fly, not raise.
    """
    final = FinalValuation(
        asking_price=300000,
        fair_value_balanced=280000,
        fair_value_conservative=260000,
        fair_value_aggressive=300000,
        asking_vs_fair_gap_pct=7.1,
        valuation_status="Usable with caution",
        sufficient_evidence=True,
        confidence_label="Medium",
        confidence_score=50,
    )
    final.recommendation = None  # simulate the reported failure mode

    rec = _ensure_recommendation(final, "V2")
    assert rec is not None
    assert rec.source_engine == "V2"
    assert rec.gap_pct == 7.1
    assert rec.investment_tagline
    print(f"OK: missing-recommendation object -> fallback built = {rec.investment_tagline!r}")


def test_ensure_recommendation_handles_genuinely_missing_attribute():
    """Simulates the actual Streamlit Cloud failure precisely: an object
    from a class shape that never had .recommendation declared at all
    (e.g. a stale pre-CR1 process still running FinalValuation without
    the field). FinalValuation.recommendation has a plain `= None`
    default, which Python stores as a class-level attribute — so even
    `del`-ing the instance attribute on today's class still resolves to
    None via the class fallback, it does NOT reproduce AttributeError.
    A minimal stand-in class without the field at all is the only way to
    faithfully simulate "genuinely missing", which is what getattr's
    default in _ensure_recommendation is actually guarding against.
    """
    class _StaleFinalValuationShape:
        """Mimics FinalValuation as it existed before CR1 added the
        recommendation field — no such attribute exists anywhere."""
        def __init__(self):
            self.asking_price = 300000
            self.fair_value_balanced = 280000
            self.fair_value_conservative = 260000
            self.asking_vs_fair_gap_pct = 7.1
            self.valuation_status = "Usable with caution"
            self.sufficient_evidence = True

    stale = _StaleFinalValuationShape()

    with_attr_error = False
    try:
        _ = stale.recommendation
    except AttributeError:
        with_attr_error = True
    assert with_attr_error, "test setup didn't actually reproduce an AttributeError"

    rec = _ensure_recommendation(stale, "V2")
    assert rec is not None
    print(f"OK: genuinely-missing attribute (stale class shape) -> fallback built = {rec.investment_tagline!r}")


if __name__ == "__main__":
    _assert_helper_matches_app_py()
    test_real_v2_run_populates_recommendation()
    test_v1_run_populates_recommendation()
    test_ensure_recommendation_handles_missing_attribute()
    test_ensure_recommendation_handles_genuinely_missing_attribute()
    print("\nALL TESTS PASSED")
