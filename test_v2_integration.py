"""Test V2 integration: V1 + V2 diagnostic + explanation engine + PDF generation."""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.valuation_engine_v2 import run_v2_valuation
from src.explanation_engine import explain_valuation
from src.investment_scorecard import calculate_scorecard
from src.risk_assessor import assess_risks
from src.planning import assess_planning
from src.btl_analysis import assess_btl
from src.transport import assess_location
from src.report_generator import generate_report
from src.epc import lookup_subject_floor_area
from src.utils import format_currency


TESTS = [
    {
        "label": "Ruttle Close",
        "listing": PropertyListing(
            address="Ruttle Close, Cholsey", postcode="OX10 9FP",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
            override_house_number="6", override_street_name="Ruttle Close",
            overrides_applied=["House: 6", "Street: Ruttle Close"],
        ),
    },
    {
        "label": "Chestnut Close",
        "listing": PropertyListing(
            address="Chestnut Close, Witney", postcode="OX28 1PD",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
            override_house_number="24", override_street_name="Chestnut Close",
            overrides_applied=["House: 24", "Street: Chestnut Close"],
        ),
    },
    {
        "label": "Thorney Leys",
        "listing": PropertyListing(
            address="26 Thorney Leys, Witney", postcode="OX28 5NR",
            asking_price=275000, property_type="Terraced", bedrooms=3,
            floor_area_sqm=64.0, floor_area_source="Rightmove", tenure="Freehold",
        ),
    },
    {
        "label": "Ingestre Road",
        "listing": PropertyListing(
            address="Ingestre Road, Prenton", postcode="CH43 5UY",
            asking_price=160000, property_type="Flat", bedrooms=2, tenure="Leasehold",
            override_house_number="6", override_building_name="Ingestre Court",
            override_street_name="Ingestre Road",
            overrides_applied=["Number: 6", "Building: Ingestre Court"],
        ),
    },
]


for t in TESTS:
    label = t["label"]
    listing = t["listing"]
    print(f"\n{'#' * 85}", flush=True)
    print(f"  {label}", flush=True)
    print(f"{'#' * 85}", flush=True)

    # EPC lookup
    addr = listing.effective_address_first_line
    pc = listing.effective_postcode
    street = listing.effective_street
    print(f"  Fetching EPC + comps...", flush=True)

    sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
    if sqm > 0 and not listing.floor_area_sqm:
        listing.floor_area_sqm = sqm
        listing.floor_area_source = "EPC"

    # Comparables
    ev = fetch_and_score_comparables(
        postcode=pc,
        property_type=listing.property_type or "",
        bedrooms=listing.bedrooms or 0,
        floor_area_sqm=listing.floor_area_sqm or 0,
        tenure=listing.tenure or "",
        street=addr,
    )

    # V1 valuation
    signals = interpret_listing(description="", key_features=[], property_type=listing.property_type or "")
    v1 = calculate_valuation(
        asking_price=listing.asking_price,
        evidence=ev,
        signals=signals,
        floor_area_sqm=listing.floor_area_sqm or 0,
        tenure=listing.tenure or "",
        region="England",
    )
    print(f"  V1: {format_currency(v1.fair_value_balanced)} | {v1.confidence_label} ({v1.confidence_score})", flush=True)

    # V2 valuation + explanation
    v2 = run_v2_valuation(ev, listing)
    expl = explain_valuation(v2, listing)
    print(f"  V2: {format_currency(v2.final.fair_value_balanced)} | {v2.final.confidence_label} ({v2.final.confidence_score})", flush=True)

    # Explanation sections (abbreviated)
    print(f"  Explanation sections: {len(expl.key_drivers)} drivers, {len(expl.risks)} risks, {len(expl.strengths)} strengths", flush=True)
    print(f"  Executive summary: {expl.executive_summary[:80]}...", flush=True)
    print(f"  Verdict: {expl.overall_verdict[:80]}...", flush=True)

    # PDF generation with V2
    try:
        scorecard = calculate_scorecard(valuation=v1, recommendation=v1.recommendation, planning_result={}, btl_result={}, location_result={}, mode="personal")
        risk = assess_risks(valuation=v1, recommendation=v1.recommendation, signals=signals, planning_result={}, btl_result={}, tenure=listing.tenure or "")
        score_dict = scorecard.to_dict()
        risk_dict = risk.to_dict()
        score_dict["flags"] = risk_dict.get("flags", [])
        score_dict["summary"] = risk_dict.get("summary", "")

        report_path = generate_report(
            listing=listing.to_dict(),
            valuation=v1.to_dict(),
            planning={},
            btl={},
            location={"location_score": 0, "distances": [], "warnings": []},
            investment_score=score_dict,
            mode="personal",
            v2_result=v2,
            v2_explanation=expl,
        )
        print(f"  PDF: OK -> {report_path}", flush=True)
    except Exception as e:
        print(f"  PDF: FAILED -> {e}", flush=True)

    # Also test PDF without V2 (V1-only mode)
    try:
        report_path_v1 = generate_report(
            listing=listing.to_dict(),
            valuation=v1.to_dict(),
            planning={},
            btl={},
            location={"location_score": 0, "distances": [], "warnings": []},
            investment_score=score_dict,
            mode="personal",
        )
        print(f"  PDF (V1-only): OK -> {report_path_v1}", flush=True)
    except Exception as e:
        print(f"  PDF (V1-only): FAILED -> {e}", flush=True)


print(f"\n\n{'=' * 85}", flush=True)
print("COMPLETE", flush=True)
print(f"{'=' * 85}", flush=True)
