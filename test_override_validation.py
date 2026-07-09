"""Override validation: 5 properties, with/without overrides.

Categories:
1. Ruttle Close — Rightmove hides house number (known: #6)
2. Chestnut Close — Rightmove hides house number (known: #24)
3. Ingestre Road — flat needing building name + flat number
4. Chestnut Close wrong postcode — simulates Rightmove/EPC postcode mismatch
5. Thorney Leys — normal property, no override needed (control)
"""

import sys, os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.valuation_engine_v2 import run_v2_valuation
from src.epc import lookup_subject_floor_area


def run_pair(label, category, listing_no, listing_yes):
    """Run one property with and without overrides, report comparison."""
    print(f"\n{'=' * 85}")
    print(f"  {label}")
    print(f"  Category: {category}")
    print(f"{'=' * 85}")

    results = {}
    for tag, listing in [("WITHOUT", listing_no), ("WITH", listing_yes)]:
        addr = listing.effective_address_first_line
        pc = listing.effective_postcode
        street = listing.effective_street

        # EPC
        sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
        epc_ok = sqm > 0

        # Apply EPC to listing copy
        l = PropertyListing(**listing.to_dict())
        if sqm > 0 and not l.floor_area_sqm:
            l.floor_area_sqm = sqm
            l.floor_area_source = "EPC"

        fa_source = l.floor_area_source or "None"
        fa_val = l.floor_area_sqm or 0

        # Fetch comps
        ev = fetch_and_score_comparables(
            postcode=pc,
            property_type=l.property_type or "",
            bedrooms=l.bedrooms or 0,
            floor_area_sqm=l.floor_area_sqm or 0,
            tenure=l.tenure or "",
            street=addr,
        )

        # V2
        v2 = run_v2_valuation(ev, l)

        results[tag] = {
            "epc_sqm": sqm,
            "epc_rating": rating,
            "epc_detail": detail,
            "fa_source": fa_source,
            "fa_val": fa_val,
            "direct": v2.direct.comp_count,
            "direct_val": v2.direct.valuation,
            "direct_conf": f"{v2.direct.confidence_label} ({v2.direct.confidence_score})",
            "dev": v2.development.comp_count,
            "dev_val": v2.development.valuation,
            "local": v2.local_market.comp_count,
            "blended": v2.final.fair_value_balanced,
            "conf": f"{v2.final.confidence_label} ({v2.final.confidence_score})",
            "status": v2.final.valuation_status,
        }

        print(f"\n  {tag} overrides:")
        print(f"    EPC lookup addr: '{addr}' @ {pc}")
        print(f"    EPC result: {sqm:.0f} sqm, {rating}, {detail[:60]}")
        print(f"    Floor area: {fa_val:.0f} sqm ({fa_source})")
        print(f"    Direct: {v2.direct.comp_count} comps, {v2.direct.valuation:,.0f}")
        print(f"    Dev:    {v2.development.comp_count} comps, {v2.development.valuation:,.0f}")
        print(f"    Local:  {v2.local_market.comp_count} comps")
        print(f"    V2:     {v2.final.fair_value_balanced:,.0f} ({v2.final.confidence_label}, {v2.final.confidence_score})")

    wo = results["WITHOUT"]
    wi = results["WITH"]

    # Improvement assessment
    improvements = []
    if wi["epc_sqm"] > 0 and wo["epc_sqm"] == 0:
        improvements.append("EPC match gained")
    if wi["direct"] > wo["direct"]:
        improvements.append(f"Direct comps {wo['direct']}->{wi['direct']}")
    if wi["dev"] > wo["dev"]:
        improvements.append(f"Dev comps {wo['dev']}->{wi['dev']}")
    conf_wo = int(wo["conf"].split("(")[1].rstrip(")"))
    conf_wi = int(wi["conf"].split("(")[1].rstrip(")"))
    if conf_wi > conf_wo:
        improvements.append(f"Confidence {conf_wo}->{conf_wi}")
    if wi["blended"] > 0 and wo["blended"] == 0:
        improvements.append("Valuation now possible")

    verdict = "IMPROVED" if improvements else "NO CHANGE"
    print(f"\n  VERDICT: {verdict}")
    if improvements:
        for imp in improvements:
            print(f"    + {imp}")
    else:
        print(f"    (override had no measurable effect)")

    return {
        "label": label,
        "category": category,
        "verdict": verdict,
        "improvements": improvements,
        "wo": wo,
        "wi": wi,
    }


# ===== TEST CASES =====

all_results = []

# 1. Ruttle Close — hidden house number
all_results.append(run_pair(
    "1. Ruttle Close, Cholsey", "Hidden house number",
    PropertyListing(
        address="Ruttle Close, Cholsey",
        postcode="OX10 9FP",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
    ),
    PropertyListing(
        address="Ruttle Close, Cholsey",
        postcode="OX10 9FP",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
        override_house_number="6",
        override_street_name="Ruttle Close",
        overrides_applied=["House number: 6", "Street: Ruttle Close"],
    ),
))

# 2. Chestnut Close — hidden house number
all_results.append(run_pair(
    "2. Chestnut Close, Witney", "Hidden house number",
    PropertyListing(
        address="Chestnut Close, Witney",
        postcode="OX28 1PD",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
    ),
    PropertyListing(
        address="Chestnut Close, Witney",
        postcode="OX28 1PD",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
        override_house_number="24",
        override_street_name="Chestnut Close",
        overrides_applied=["House number: 24", "Street: Chestnut Close"],
    ),
))

# 3. Ingestre Road — flat needing building + flat number
all_results.append(run_pair(
    "3. Ingestre Road, Prenton", "Flat/block identity",
    PropertyListing(
        address="Ingestre Road, Prenton",
        postcode="CH43 5UY",
        asking_price=160000,
        property_type="Flat",
        bedrooms=2,
        tenure="Leasehold",
    ),
    PropertyListing(
        address="Ingestre Road, Prenton",
        postcode="CH43 5UY",
        asking_price=160000,
        property_type="Flat",
        bedrooms=2,
        tenure="Leasehold",
        override_house_number="6",
        override_building_name="Ingestre Court",
        override_street_name="Ingestre Road",
        overrides_applied=["Number: 6", "Building: Ingestre Court", "Street: Ingestre Road"],
    ),
))

# 4. Chestnut Close with wrong postcode — simulates EPC/Rightmove mismatch
# In earlier sessions the wrong postcode OX28 1GH was discovered for this property
all_results.append(run_pair(
    "4. Chestnut Close (wrong postcode)", "Postcode mismatch",
    PropertyListing(
        address="24 Chestnut Close, Witney",
        postcode="OX28 1GH",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
    ),
    PropertyListing(
        address="24 Chestnut Close, Witney",
        postcode="OX28 1GH",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
        override_postcode="OX28 1PD",
        overrides_applied=["Postcode: OX28 1PD (original: OX28 1GH)"],
    ),
))

# 5. Thorney Leys — control, no override needed
all_results.append(run_pair(
    "5. Thorney Leys, Witney (control)", "No override needed",
    PropertyListing(
        address="26 Thorney Leys, Witney",
        postcode="OX28 5NR",
        asking_price=275000,
        property_type="Terraced",
        bedrooms=3,
        floor_area_sqm=64.0,
        floor_area_source="Rightmove",
        tenure="Freehold",
    ),
    PropertyListing(
        address="26 Thorney Leys, Witney",
        postcode="OX28 5NR",
        asking_price=275000,
        property_type="Terraced",
        bedrooms=3,
        floor_area_sqm=64.0,
        floor_area_source="Rightmove",
        tenure="Freehold",
    ),
))

# ===== SUMMARY =====

print(f"\n\n{'=' * 85}")
print("VALIDATION SUMMARY")
print(f"{'=' * 85}")
print(f"{'Property':<40} {'Category':<25} {'Verdict':<12} {'Key change'}")
print(f"{'-'*40} {'-'*25} {'-'*12} {'-'*30}")
for r in all_results:
    key = r["improvements"][0] if r["improvements"] else "none"
    print(f"{r['label']:<40} {r['category']:<25} {r['verdict']:<12} {key}")

improved = sum(1 for r in all_results if r["verdict"] == "IMPROVED")
total = len(all_results)
print(f"\nOverrides improved accuracy in {improved}/{total} cases.")

# EPC match summary
print(f"\nEPC match detail:")
for r in all_results:
    wo_epc = r["wo"]["epc_sqm"]
    wi_epc = r["wi"]["epc_sqm"]
    if wo_epc == 0 and wi_epc > 0:
        print(f"  {r['label']}: GAINED {wi_epc:.0f} sqm ({r['wi']['epc_rating']})")
    elif wo_epc > 0 and wi_epc > 0 and wo_epc != wi_epc:
        print(f"  {r['label']}: CHANGED {wo_epc:.0f} -> {wi_epc:.0f} sqm")
    elif wo_epc > 0:
        print(f"  {r['label']}: already matched ({wo_epc:.0f} sqm)")
    else:
        print(f"  {r['label']}: no match either way")

print(f"\n{'=' * 85}")
