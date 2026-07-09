"""Test Land Registry retrieval with pagination fix.

Verifies that same-street/building comparables are found after
implementing full API pagination.
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
        "target_street": "RUTTLE",
        "listing": PropertyListing(
            address="6 Ruttle Close, Cholsey",
            postcode="OX10 9FP",
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
        "target_street": "THORNEY",
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
        "target_street": "INGESTRE",
        "listing": PropertyListing(
            address="Ingestre Court, 6 Ingestre Road, Prenton",
            postcode="CH43 5UY",
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
        "target_street": "CHESTNUT",
        "listing": PropertyListing(
            address="24 Chestnut Close, Witney",
            postcode="OX28 1PD",
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
    target = t["target_street"]
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

    # Count same-street records in raw data
    all_comps = evidence.scored_comparables + evidence.context_only_comparables + evidence.excluded_comparables
    same_street_raw = [c for c in all_comps if target in (c.street or "").upper() or target in (c.address or "").upper()]

    direct = build_direct_evidence_group(evidence, listing)
    dev = build_development_evidence_group(evidence, listing, direct_group=direct)

    result = {
        "label": t["label"],
        "postcode": listing.postcode,
        "asking": t["asking"],
        # Retrieval diagnostics
        "retrieval": {
            "raw_records": evidence.retrieval_raw_records,
            "pages_fetched": evidence.retrieval_pages_fetched,
            "strategy": evidence.retrieval_strategy_used,
            "truncated": evidence.retrieval_may_be_truncated,
            "details": evidence.retrieval_strategies_detail,
            "total_fetched": evidence.total_fetched,
            "total_scored": evidence.total_scored,
            "same_street_found": len(same_street_raw),
        },
        # Evidence results
        "direct": {
            "comp_count": direct.comp_count,
            "valuation": direct.valuation,
            "confidence": f"{direct.confidence_label} ({direct.confidence_score})",
            "representative": f"{direct.representative.address[:55]}, {direct.representative.adjusted_price:,.0f}" if direct.representative else "None",
        },
        "development": {
            "comp_count": dev.comp_count,
            "valuation": dev.valuation,
            "confidence": f"{dev.confidence_label} ({dev.confidence_score})",
            "representative": f"{dev.representative.address[:55]}, {dev.representative.adjusted_price:,.0f}" if dev.representative else "None",
        },
    }
    return result


results = []
for t in TESTS:
    results.append(run_test(t))

print("\n" + "=" * 80)
print("RETRIEVAL FIX — TEST RESULTS")
print("=" * 80)

for r in results:
    ret = r["retrieval"]
    print(f"\n--- {r['label']} ({r['postcode']}, asking {r['asking']:,}) ---")
    print(f"  Retrieval: {ret['raw_records']} raw records, {ret['pages_fetched']} pages, strategy: {ret['strategy']}")
    print(f"  Truncated: {ret['truncated']}")
    for d in ret["details"]:
        print(f"    {d}")
    print(f"  Scored: {ret['total_scored']} | Same-street in raw: {ret['same_street_found']}")
    d = r["direct"]
    print(f"  Direct:      {d['comp_count']} comps, val {d['valuation']:,.0f}, {d['confidence']}")
    print(f"               rep: {d['representative']}")
    v = r["development"]
    print(f"  Development: {v['comp_count']} comps, val {v['valuation']:,.0f}, {v['confidence']}")
    print(f"               rep: {v['representative']}")

print("\n" + json.dumps(results, indent=2, default=str))
