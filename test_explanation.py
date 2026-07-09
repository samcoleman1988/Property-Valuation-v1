"""Test the Explainable Valuation Engine on 4 properties."""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.valuation_engine_v2 import run_v2_valuation
from src.epc import lookup_subject_floor_area
from src.explanation_engine import explain_valuation


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

    # EPC
    addr = listing.effective_address_first_line
    pc = listing.effective_postcode
    street = listing.effective_street
    print(f"  Fetching EPC + comps...", flush=True)

    sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
    if sqm > 0 and not listing.floor_area_sqm:
        listing.floor_area_sqm = sqm
        listing.floor_area_source = "EPC"

    ev = fetch_and_score_comparables(
        postcode=pc,
        property_type=listing.property_type or "",
        bedrooms=listing.bedrooms or 0,
        floor_area_sqm=listing.floor_area_sqm or 0,
        tenure=listing.tenure or "",
        street=addr,
    )

    v2 = run_v2_valuation(ev, listing)
    expl = explain_valuation(v2, listing)

    print(f"\n  V2: {v2.final.fair_value_balanced:,.0f} | Conf: {v2.final.confidence_label} ({v2.final.confidence_score})", flush=True)

    print(f"\n--- 1. Executive Summary ---\n", flush=True)
    print(expl.executive_summary, flush=True)

    print(f"\n--- 2. Key Value Drivers ---\n", flush=True)
    for d in expl.key_drivers:
        arrow = {"raises value": "^", "lowers value": "v", "neutral": "-"}.get(d.direction, "?")
        print(f"  [{arrow}] {d.title} ({d.impact})", flush=True)
        print(f"      {d.explanation}", flush=True)

    print(f"\n--- 3. Why Not Highest ---\n", flush=True)
    print(expl.why_not_highest, flush=True)

    print(f"\n--- 4. Evidence Hierarchy ---\n", flush=True)
    for h in expl.evidence_hierarchy:
        weight_str = f"{h.weighting:.0%}" if h.weighting > 0 else "n/a"
        val_str = f"{h.valuation:,.0f}" if h.valuation > 0 else "n/a"
        print(f"  {h.group_name}", flush=True)
        print(f"    Confidence: {h.confidence}  |  Valuation: {val_str}  |  Weight: {weight_str}", flush=True)
        if h.representative:
            print(f"    Representative: {h.representative}", flush=True)
        print(f"    {h.summary}", flush=True)

    print(f"\n--- 5. Evidence Conflicts ---\n", flush=True)
    print(expl.evidence_conflicts or "(none)", flush=True)

    print(f"\n--- 6. Confidence Explanation ---\n", flush=True)
    print(expl.confidence_explanation, flush=True)

    print(f"\n--- 7. Offer Rationale ---\n", flush=True)
    print(expl.offer_rationale, flush=True)

    print(f"\n--- 8. Risks ---\n", flush=True)
    if expl.risks:
        for r in expl.risks:
            print(f"  - {r}", flush=True)
    else:
        print("  No material valuation risks identified.", flush=True)

    print(f"\n--- 9. Strengths ---\n", flush=True)
    for s in expl.strengths:
        print(f"  - {s}", flush=True)

    print(f"\n--- 10. Overall Verdict ---\n", flush=True)
    print(expl.overall_verdict, flush=True)

print(f"\n\n{'=' * 85}", flush=True)
print("COMPLETE", flush=True)
print(f"{'=' * 85}", flush=True)
