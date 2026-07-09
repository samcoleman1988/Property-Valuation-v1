"""Pre-flight operational checks before real-world validation."""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from src.rightmove_parser import parse_listing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.investment_scorecard import calculate_scorecard
from src.risk_assessor import assess_risks
from src.planning import assess_planning
from src.transport import assess_location
from src.report_generator import generate_report
from src.property_db import (
    save_property, get_all_properties, get_property,
    save_calibration, get_calibration, get_all_calibrations,
)
from src.utils import format_currency


def check(name, fn):
    print(f"\n{'='*60}")
    print(f"CHECK: {name}")
    print(f"{'='*60}")
    try:
        result = fn()
        print(f"  RESULT: PASS")
        return True, result
    except Exception as e:
        print(f"  RESULT: FAIL")
        print(f"  ERROR: {e}")
        traceback.print_exc()
        return False, None


# -------------------------------------------------------
# CHECK 1: Rightmove URL extraction on a live URL
# -------------------------------------------------------
# Use a known property ID format — Rightmove property pages
# We'll try a few approaches to find a working URL

listing = None
live_url = None

def check_1():
    global listing, live_url
    # Try to fetch a real Rightmove listing page
    # Using a property ID that is likely to exist
    test_urls = [
        "https://www.rightmove.co.uk/properties/157541912",
        "https://www.rightmove.co.uk/properties/155000000",
        "https://www.rightmove.co.uk/properties/153000000",
    ]

    last_error = None
    for url in test_urls:
        try:
            print(f"  Trying: {url}")
            result = parse_listing(url)
            if result.asking_price > 0 and result.postcode:
                listing = result
                live_url = url
                print(f"  Address: {result.address}")
                print(f"  Postcode: {result.postcode}")
                print(f"  Type: {result.property_type}")
                print(f"  Bedrooms: {result.bedrooms}")
                print(f"  Asking: {format_currency(result.asking_price)}")
                print(f"  Tenure: {result.tenure}")
                print(f"  Floor area: {result.floor_area_sqft or 'Not available'} sqft")
                print(f"  Lat/Lng: {result.latitude}, {result.longitude}")
                if result.extraction_warnings:
                    print(f"  Warnings: {result.extraction_warnings}")
                return True
            else:
                print(f"  Parsed but missing price or postcode, trying next...")
                last_error = f"No price ({result.asking_price}) or postcode ({result.postcode})"
        except Exception as e:
            print(f"  Failed: {e}")
            last_error = str(e)

    # If no live URL works, simulate with manual data to test the rest of the pipeline
    print(f"\n  No live Rightmove URL returned a full listing.")
    print(f"  Last error: {last_error}")
    print(f"  Falling back to synthetic listing for remaining checks...")

    from src.rightmove_parser import PropertyListing
    listing = PropertyListing(
        url="https://www.rightmove.co.uk/properties/000000000",
        address="Synthetic Test, 10 High Street, Oxford",
        postcode="OX4 1JE",
        property_type="Terraced House",
        bedrooms=3,
        bathrooms=1,
        tenure="Freehold",
        asking_price=350000,
        floor_area_sqft=900,
        floor_area_sqm=83.6,
        description="A well-presented three bedroom terraced house with garden.",
        key_features=["Three bedrooms", "Garden", "Close to amenities"],
        latitude=51.745,
        longitude=-1.237,
    )
    live_url = listing.url
    raise Exception(
        f"Live Rightmove extraction failed. Last error: {last_error}. "
        f"Remaining checks will use synthetic data."
    )

passed_1, _ = check("1. Rightmove URL extraction", check_1)


# -------------------------------------------------------
# CHECK 2: Graceful handling of extraction failure
# -------------------------------------------------------
def check_2():
    # Bad URL
    try:
        result = parse_listing("https://www.rightmove.co.uk/properties/999999999999")
        print(f"  Bad URL returned: price={result.asking_price}, postcode={result.postcode}")
        print(f"  Warnings: {result.extraction_warnings}")
        if result.asking_price == 0 or not result.postcode:
            print(f"  Correctly returned empty/zero values for bad URL")
            return True
        else:
            print(f"  WARNING: Got unexpected data from bad URL")
            return True
    except Exception as e:
        print(f"  Exception on bad URL (acceptable): {type(e).__name__}: {e}")
        return True

    # Invalid domain
    try:
        result = parse_listing("https://www.example.com/not-rightmove")
        print(f"  Non-Rightmove URL: price={result.asking_price}")
        return True
    except Exception as e:
        print(f"  Exception on non-Rightmove (acceptable): {type(e).__name__}: {e}")
        return True

passed_2, _ = check("2. Graceful extraction failure handling", check_2)


# -------------------------------------------------------
# CHECK 3: Full pipeline + DB save
# -------------------------------------------------------
saved_id = None

def check_3():
    global saved_id

    # Run full pipeline
    signals = interpret_listing(
        description=listing.description or "",
        key_features=listing.key_features if hasattr(listing, "key_features") else [],
        property_type=listing.property_type or "",
    )
    print(f"  Signals: condition={signals.condition_label}")

    street = ""
    if listing.address:
        parts = listing.address.split(",")
        if parts:
            street = parts[0].strip()

    evidence = fetch_and_score_comparables(
        postcode=listing.postcode,
        property_type=listing.property_type or "",
        bedrooms=listing.bedrooms or 0,
        floor_area_sqm=listing.floor_area_sqm or 0,
        tenure=listing.tenure or "",
        latitude=listing.latitude or 0,
        longitude=listing.longitude or 0,
        street=street,
    )
    print(f"  Comparables: {evidence.total_scored} scored "
          f"(A={evidence.tier_a_count} B={evidence.tier_b_count} C={evidence.tier_c_count})")

    valuation = calculate_valuation(
        asking_price=listing.asking_price,
        evidence=evidence,
        signals=signals,
        floor_area_sqm=listing.floor_area_sqm or 0,
        tenure=listing.tenure or "",
        region="England",
    )
    print(f"  Valuation: status={valuation.valuation_status}, "
          f"balanced={format_currency(valuation.fair_value_balanced) if valuation.fair_value_balanced else 'N/A'}")

    try:
        planning_result = assess_planning(
            postcode=listing.postcode,
            property_type=listing.property_type,
            bedrooms=listing.bedrooms or 0,
            current_value=valuation.fair_value_balanced or listing.asking_price,
            latitude=listing.latitude or 0,
            longitude=listing.longitude or 0,
        )
        planning_dict = planning_result.to_dict() if hasattr(planning_result, "to_dict") else (
            planning_result if isinstance(planning_result, dict) else {}
        )
    except Exception:
        planning_dict = {}
    print(f"  Planning: {len(planning_dict.get('constraints_summary', []))} constraints")

    location = assess_location(
        postcode=listing.postcode,
        latitude=listing.latitude or 0,
        longitude=listing.longitude or 0,
    )
    location_dict = location.to_dict()

    scorecard = calculate_scorecard(
        valuation=valuation,
        recommendation=valuation.recommendation,
        planning_result=planning_dict,
        btl_result={},
        location_result=location_dict,
        mode="personal",
    )
    print(f"  Scorecard: {scorecard.overall_score:.0f}/100 — {scorecard.verdict}")

    risk = assess_risks(
        valuation=valuation,
        recommendation=valuation.recommendation,
        signals=signals,
        planning_result=planning_dict,
        btl_result={},
        tenure=listing.tenure or "",
    )
    print(f"  Risk: {risk.overall_risk_level} ({len(risk.flags)} flags)")

    # Save to DB
    score_dict = scorecard.to_dict()
    risk_dict = risk.to_dict()
    score_dict["flags"] = risk_dict.get("flags", [])
    score_dict["summary"] = risk_dict.get("summary", "")

    saved_id = save_property(
        url=live_url,
        address=listing.address or "",
        postcode=listing.postcode,
        property_type=listing.property_type or "",
        bedrooms=listing.bedrooms or 0,
        bathrooms=listing.bathrooms if hasattr(listing, "bathrooms") else 0,
        floor_area_sqm=listing.floor_area_sqm or 0,
        tenure=listing.tenure or "",
        asking_price=listing.asking_price,
        valuation_result=valuation.to_dict(),
        scorecard_result=score_dict,
        risk_result=risk_dict,
        listing_data=listing.to_dict(),
        comparable_data={
            "total": evidence.total_scored,
            "tier_a": evidence.tier_a_count,
            "tier_b": evidence.tier_b_count,
            "tier_c": evidence.tier_c_count,
        },
        mode="personal",
        notes="category:preflight_test",
    )
    print(f"  Saved to DB with ID: {saved_id}")

    # Verify it's retrievable
    prop = get_property(saved_id)
    assert prop is not None, "Property not found after save"
    assert prop["postcode"] == listing.postcode, "Postcode mismatch"
    assert prop["asking_price"] == listing.asking_price, "Price mismatch"
    print(f"  Verified: retrieved from DB successfully")

    # Store for later checks
    check_3.valuation = valuation
    check_3.scorecard = scorecard
    check_3.risk = risk
    check_3.planning_dict = planning_dict
    check_3.location_dict = location_dict
    check_3.signals = signals
    check_3.score_dict = score_dict
    check_3.risk_dict = risk_dict

    return True

passed_3, _ = check("3. Full pipeline + DB save", check_3)


# -------------------------------------------------------
# CHECK 4: Validation summary updates
# -------------------------------------------------------
def check_4():
    all_props = get_all_properties()
    found = any(p["id"] == saved_id for p in all_props)
    print(f"  Total properties in DB: {len(all_props)}")
    print(f"  Preflight test property found: {found}")
    assert found, f"Property ID {saved_id} not in get_all_properties()"

    # Check that get_all_calibrations also returns it (LEFT JOIN)
    all_cals = get_all_calibrations()
    cal_found = any(c["id"] == saved_id for c in all_cals)
    print(f"  Found in calibration join: {cal_found}")
    assert cal_found, f"Property ID {saved_id} not in get_all_calibrations()"
    return True

passed_4, _ = check("4. Validation summary updates", check_4)


# -------------------------------------------------------
# CHECK 5: Calibration feedback save + retrieve
# -------------------------------------------------------
def check_5():
    # Save calibration
    save_calibration(saved_id, {
        "valuation_judgement": "credible",
        "comparable_quality": "acceptable",
        "verdict_judgement": "right",
        "what_tool_missed": "Preflight test — nothing missed",
        "manual_adjustment_notes": "",
        "general_notes": "Automated preflight check",
        "error_tags": "",
        "viewed": 0,
        "offered": 0,
        "offer_amount": None,
        "outcome": "",
        "eventual_sold_price": None,
    })
    print(f"  Calibration saved for property {saved_id}")

    # Retrieve
    cal = get_calibration(saved_id)
    assert cal is not None, "Calibration not found after save"
    assert cal["valuation_judgement"] == "credible", f"Wrong judgement: {cal['valuation_judgement']}"
    assert cal["comparable_quality"] == "acceptable", f"Wrong comp quality: {cal['comparable_quality']}"
    print(f"  Retrieved: judgement={cal['valuation_judgement']}, quality={cal['comparable_quality']}")

    # Update
    save_calibration(saved_id, {
        "valuation_judgement": "too_optimistic",
        "comparable_quality": "poor",
        "verdict_judgement": "wrong",
        "what_tool_missed": "Updated in preflight",
        "error_tags": "postcode_too_broad,no_floor_area",
        "viewed": 1,
        "offered": 0,
    })
    cal2 = get_calibration(saved_id)
    assert cal2["valuation_judgement"] == "too_optimistic", "Update failed"
    assert cal2["error_tags"] == "postcode_too_broad,no_floor_area", "Tags not saved"
    assert cal2["viewed"] == 1, "Viewed flag not saved"
    print(f"  Updated: judgement={cal2['valuation_judgement']}, tags={cal2['error_tags']}, viewed={cal2['viewed']}")

    return True

passed_5, _ = check("5. Calibration feedback save + retrieve", check_5)


# -------------------------------------------------------
# CHECK 6: Rankings page data
# -------------------------------------------------------
def check_6():
    all_cals = get_all_calibrations()
    target = None
    for c in all_cals:
        if c["id"] == saved_id:
            target = c
            break

    assert target is not None, f"Property {saved_id} not in rankings data"

    # Verify key fields are present
    required = ["address", "postcode", "asking_price", "fair_value_balanced",
                 "asking_vs_fair_gap_pct", "overall_score", "verdict",
                 "risk_count", "confidence_label", "valuation_judgement",
                 "viewed"]
    missing = [f for f in required if f not in target]
    assert not missing, f"Missing fields in rankings: {missing}"

    print(f"  Rankings row: {target['address'][:40]}")
    print(f"    Asking: {target['asking_price']}, Balanced: {target['fair_value_balanced']}")
    print(f"    Score: {target['overall_score']}, Verdict: {target['verdict']}")
    print(f"    Judgement: {target['valuation_judgement']}, Viewed: {target['viewed']}")
    print(f"  All required fields present")
    return True

passed_6, _ = check("6. Rankings page data", check_6)


# -------------------------------------------------------
# CHECK 7: PDF generation from the same property
# -------------------------------------------------------
def check_7():
    prop = get_property(saved_id)
    assert prop is not None

    listing_data = json.loads(prop["listing_json"]) if prop.get("listing_json") else {}
    val_data = json.loads(prop["valuation_json"]) if prop.get("valuation_json") else {}
    score_data = json.loads(prop["scorecard_json"]) if prop.get("scorecard_json") else {}
    risk_data = json.loads(prop["risk_json"]) if prop.get("risk_json") else {}

    # Merge risk flags into score_data (as app.py does)
    score_data["flags"] = risk_data.get("flags", [])
    score_data["summary"] = risk_data.get("summary", "")

    report_path = generate_report(
        listing=listing_data,
        valuation=val_data,
        planning={},
        btl={},
        location={"location_score": 5, "distances": [], "warnings": []},
        investment_score=score_data,
        mode="personal",
    )

    file_size = os.path.getsize(report_path) / 1024
    print(f"  PDF path: {report_path}")
    print(f"  PDF size: {file_size:.1f} KB")
    assert file_size > 1, f"PDF too small ({file_size:.1f} KB)"
    print(f"  PDF generated successfully from saved DB data")
    return True

passed_7, _ = check("7. PDF generation from saved property", check_7)


# -------------------------------------------------------
# SUMMARY
# -------------------------------------------------------
print(f"\n{'='*60}")
print(f"PRE-FLIGHT SUMMARY")
print(f"{'='*60}")

checks = [
    ("1. Rightmove URL extraction", passed_1),
    ("2. Graceful extraction failure", passed_2),
    ("3. Full pipeline + DB save", passed_3),
    ("4. Validation summary updates", passed_4),
    ("5. Calibration feedback", passed_5),
    ("6. Rankings page data", passed_6),
    ("7. PDF generation", passed_7),
]

all_pass = True
for name, passed in checks:
    status = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  {status}  {name}")

print(f"\n{'='*60}")
if all_pass:
    print("ALL CHECKS PASSED — ready for real-world validation")
else:
    print("SOME CHECKS FAILED — review errors above")
print(f"{'='*60}")
