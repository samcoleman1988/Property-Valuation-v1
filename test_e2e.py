"""End-to-end tests for the full analysis + PDF pipeline.

Tests run without Streamlit — they call the same functions app.py uses
and verify the PDF is generated correctly.
"""

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.investment_scorecard import calculate_scorecard
from src.risk_assessor import assess_risks
from src.report_generator import generate_report


def run_test(name, postcode, property_type, bedrooms, asking_price,
             tenure, floor_area_sqm=0, description="", region="England"):
    """Run one full pipeline test and return results."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")

    try:
        # 1. Comparables
        evidence = fetch_and_score_comparables(
            postcode=postcode,
            property_type=property_type,
            bedrooms=bedrooms,
            floor_area_sqm=floor_area_sqm,
            tenure=tenure,
            latitude=0, longitude=0, street="",
        )
        print(f"  Comparables: {evidence.total_scored} scored, "
              f"A={evidence.tier_a_count} B={evidence.tier_b_count} "
              f"C={evidence.tier_c_count} D={evidence.tier_d_count}")

        # 2. Listing interpretation
        signals = interpret_listing(
            description=description,
            key_features=[],
            property_type=property_type,
        )
        print(f"  Condition: {signals.condition_label} ({signals.condition_score}/10)")

        # 3. Valuation
        valuation = calculate_valuation(
            asking_price=asking_price,
            evidence=evidence,
            signals=signals,
            floor_area_sqm=floor_area_sqm,
            tenure=tenure,
            region=region,
        )
        print(f"  Status: {valuation.valuation_status}")
        print(f"  Sufficient: {valuation.sufficient_evidence}")
        print(f"  Confidence: {valuation.confidence_label} ({valuation.confidence_score}/100)")
        if valuation.fair_value_balanced:
            print(f"  Balanced: {valuation.fair_value_balanced:,.0f}")
        else:
            print(f"  Balanced: NOT PRODUCED")
        if valuation.fair_value_conservative:
            print(f"  Conservative: {valuation.fair_value_conservative:,.0f}")
        if valuation.fair_value_aggressive:
            print(f"  Aggressive: {valuation.fair_value_aggressive:,.0f}")
        print(f"  Tagline: {valuation.investment_tagline}")

        # 4. Scorecard
        scorecard = calculate_scorecard(
            valuation=valuation,
            planning_result={},
            btl_result={},
            location_result={"location_score": 5, "distances": [], "warnings": []},
            mode="personal",
        )
        print(f"  Score: {scorecard.overall_score:.0f}/100")
        print(f"  Verdict: {scorecard.verdict}")

        # 5. Risks
        risk = assess_risks(
            valuation=valuation,
            signals=signals,
            planning_result={},
            btl_result={},
            tenure=tenure,
        )
        print(f"  Risks: {risk.overall_risk_level} ({len(risk.flags)} flags)")

        # 6. PDF
        listing_dict = {
            "address": f"Test Property, {postcode}",
            "postcode": postcode,
            "property_type": property_type,
            "bedrooms": bedrooms,
            "bathrooms": 1,
            "tenure": tenure,
            "floor_area_sqft": round(floor_area_sqm * 10.764) if floor_area_sqm else 0,
            "floor_area_sqm": floor_area_sqm,
            "epc_rating": "",
            "agent_name": "Test Agent",
            "asking_price": asking_price,
            "extraction_warnings": [],
        }

        score_dict = scorecard.to_dict()
        risk_dict = risk.to_dict()
        score_dict["flags"] = risk_dict.get("flags", [])
        score_dict["summary"] = risk_dict.get("summary", "")

        report_path = generate_report(
            listing=listing_dict,
            valuation=valuation.to_dict(),
            planning={},
            btl={},
            location={"location_score": 5, "distances": [], "warnings": []},
            investment_score=score_dict,
            mode="personal",
        )

        file_size = os.path.getsize(report_path) / 1024
        print(f"  PDF: {report_path}")
        print(f"  PDF size: {file_size:.1f} KB")

        if file_size < 1:
            print(f"  FAIL: PDF too small ({file_size:.1f} KB)")
            return False

        print(f"  PASS")
        return True

    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []

    # Test 1: Oxfordshire — good evidence
    results.append(run_test(
        name="Oxfordshire OX4 - 3 bed terraced (good evidence)",
        postcode="OX4 1JE",
        property_type="Terraced House",
        bedrooms=3,
        asking_price=350000,
        tenure="Freehold",
        floor_area_sqm=85,
        description="A well-presented three bedroom terraced house with garden and parking.",
    ))

    # Test 2: Wirral CH43 — insufficient evidence (mostly flats)
    results.append(run_test(
        name="Wirral CH43 - 3 bed semi (insufficient evidence expected)",
        postcode="CH43 7PA",
        property_type="Semi-Detached House",
        bedrooms=3,
        asking_price=195000,
        tenure="Freehold",
    ))

    # Test 3: Rural Wales SY25 — weak evidence, wide spread
    results.append(run_test(
        name="Rural Wales SY25 - 4 bed detached (wide spread)",
        postcode="SY25 6AA",
        property_type="Detached House",
        bedrooms=4,
        asking_price=300000,
        tenure="Freehold",
    ))

    # Test 4: Missing floor area
    results.append(run_test(
        name="Manchester M1 - 2 bed flat (no floor area)",
        postcode="M1 3HZ",
        property_type="Flat",
        bedrooms=2,
        asking_price=220000,
        tenure="Leasehold",
        floor_area_sqm=0,
    ))

    # Test 5: BTL mode
    results.append(run_test(
        name="Liverpool L8 - 3 bed terraced (BTL context)",
        postcode="L8 0SY",
        property_type="Terraced House",
        bedrooms=3,
        asking_price=120000,
        tenure="Freehold",
        description="Terraced house, currently tenanted, generating good rental income.",
    ))

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print(f"{'='*60}")
    for i, passed in enumerate(results, 1):
        status = "PASS" if passed else "FAIL"
        print(f"  Test {i}: {status}")
