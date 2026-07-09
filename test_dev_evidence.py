"""Test Development Evidence group alongside Direct Evidence for 4 properties.

Uses manually constructed PropertyListing objects with known data from
previous validation runs (Rightmove listings have expired/404).
"""

import sys, os, json

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.valuation_engine_v2 import build_direct_evidence_group, build_development_evidence_group

TESTS = [
    {
        "label": "1. Ruttle Close, Cholsey",
        "asking": 425000,
        "listing": PropertyListing(
            address="6 Ruttle Close, Cholsey",
            postcode="OX10 9QQ",
            asking_price=425000,
            property_type="Semi-Detached",
            bedrooms=3,
            floor_area_sqm=95.0,
            floor_area_source="Rightmove",
            tenure="Freehold",
        ),
    },
    {
        "label": "2. Thorney Leys, Witney",
        "asking": 275000,
        "listing": PropertyListing(
            address="26 Thorney Leys, Witney",
            postcode="OX28 5NR",
            asking_price=275000,
            property_type="Terraced",
            bedrooms=3,
            floor_area_sqm=64.0,
            floor_area_source="Rightmove",
            tenure="Freehold",
        ),
    },
    {
        "label": "3. Ingestre Road, Prenton",
        "asking": 160000,
        "listing": PropertyListing(
            address="Ingestre Court, 6 Ingestre Road, Prenton",
            postcode="CH43 2HY",
            asking_price=160000,
            property_type="Flat",
            bedrooms=2,
            floor_area_sqm=68.0,
            floor_area_source="Rightmove",
            tenure="Leasehold",
        ),
    },
    {
        "label": "4. Chestnut Close, Witney",
        "asking": 425000,
        "listing": PropertyListing(
            address="24 Chestnut Close, Witney",
            postcode="OX28 1GH",
            asking_price=425000,
            property_type="Semi-Detached",
            bedrooms=3,
            floor_area_sqm=77.0,
            floor_area_source="Rightmove",
            tenure="Freehold",
        ),
    },
]


def run_test(t):
    listing = t["listing"]
    print(f"\nProcessing {t['label']} ({listing.postcode})...")

    street = ""
    if listing.address:
        parts = listing.address.split(",")
        if parts:
            street = parts[0].strip()

    evidence = fetch_and_score_comparables(
        postcode=listing.postcode,
        property_type=listing.property_type,
        bedrooms=listing.bedrooms,
        floor_area_sqm=listing.floor_area_sqm,
        tenure=listing.tenure,
        street=street,
    )

    print(f"  Fetched {evidence.total_fetched} raw, {evidence.total_scored} scored, {len(evidence.context_only_comparables)} context-only")

    direct = build_direct_evidence_group(evidence, listing)
    dev = build_development_evidence_group(evidence, listing, direct_group=direct)

    result = {
        "label": t["label"],
        "asking": t["asking"],
        "subject_sqm": listing.floor_area_sqm,
        "postcode": listing.postcode,
        "direct": {
            "comp_count": direct.comp_count,
            "valuation": direct.valuation,
            "range": f"{direct.valuation_low:,.0f} - {direct.valuation_high:,.0f}" if direct.valuation > 0 else "N/A",
            "confidence": f"{direct.confidence_label} ({direct.confidence_score})",
            "representative": f"{direct.representative.address[:50]}, {direct.representative.adjusted_price:,.0f}" if direct.representative else "None",
        },
        "development": {
            "comp_count": dev.comp_count,
            "median": dev.median_value,
            "weighted_mean": dev.weighted_mean,
            "valuation": dev.valuation,
            "range": f"{dev.valuation_low:,.0f} - {dev.valuation_high:,.0f}" if dev.valuation > 0 else "N/A",
            "confidence": f"{dev.confidence_label} ({dev.confidence_score})",
            "representative": f"{dev.representative.address[:50]}, {dev.representative.adjusted_price:,.0f}" if dev.representative else "None",
            "representative_reason": dev.representative_reason if dev.representative else "",
            "strengths": dev.strengths,
            "weaknesses": dev.weaknesses,
            "confidence_drivers": dev.confidence_drivers,
            "psm_median": dev.median_price_per_sqm,
            "psm_wmean": dev.weighted_mean_price_per_sqm,
        },
    }

    # Agreement analysis
    if direct.valuation > 0 and dev.valuation > 0:
        gap = abs(direct.valuation - dev.valuation) / direct.valuation * 100
        if gap < 10:
            result["agreement"] = f"AGREE ({gap:.1f}% gap)"
        elif gap < 20:
            result["agreement"] = f"MILD TENSION ({gap:.1f}% gap)"
        else:
            result["agreement"] = f"CONFLICT ({gap:.1f}% gap)"
    elif direct.valuation > 0:
        result["agreement"] = "Development Evidence empty - Direct only"
    elif dev.valuation > 0:
        result["agreement"] = "Direct Evidence empty - Development only"
    else:
        result["agreement"] = "Neither group has evidence"

    return result


results = []
for t in TESTS:
    results.append(run_test(t))

print("\n" + "=" * 80)
print("DEVELOPMENT EVIDENCE TEST RESULTS")
print("=" * 80)

for r in results:
    print(f"\n--- {r['label']} (asking {r['asking']:,}, {r['subject_sqm']} sqm, {r['postcode']}) ---")
    d = r['direct']
    print(f"  Direct:      {d['comp_count']} comps, val {d['valuation']:,.0f}, {d['confidence']}")
    print(f"               rep: {d['representative']}")
    v = r['development']
    print(f"  Development: {v['comp_count']} comps, val {v['valuation']:,.0f}, {v['confidence']}")
    print(f"               rep: {v['representative']}")
    if v['representative_reason']:
        print(f"               reason: {v['representative_reason']}")
    print(f"  Agreement:   {r['agreement']}")
    if v['strengths']:
        print(f"  Dev strengths: {'; '.join(v['strengths'])}")
    if v['weaknesses']:
        print(f"  Dev weaknesses: {'; '.join(v['weaknesses'])}")
    if v['confidence_drivers']:
        print(f"  Dev confidence: {'; '.join(v['confidence_drivers'])}")

print("\n" + json.dumps(results, indent=2, default=str))
