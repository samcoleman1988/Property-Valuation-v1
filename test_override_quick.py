"""Quick override validation — 5 properties, flushed output."""

import sys, os

sys.path.insert(0, os.path.dirname(__file__))
# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.valuation_engine_v2 import run_v2_valuation
from src.epc import lookup_subject_floor_area


def run_one(label, category, listing, overrides_desc=""):
    """Run a single listing and return key metrics."""
    addr = listing.effective_address_first_line
    pc = listing.effective_postcode
    street = listing.effective_street

    print(f"  EPC lookup: '{addr}' @ {pc}...", flush=True)
    sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)

    l = PropertyListing(**listing.to_dict())
    if sqm > 0 and not l.floor_area_sqm:
        l.floor_area_sqm = sqm
        l.floor_area_source = "EPC"

    print(f"  Fetching comps...", flush=True)
    ev = fetch_and_score_comparables(
        postcode=pc,
        property_type=l.property_type or "",
        bedrooms=l.bedrooms or 0,
        floor_area_sqm=l.floor_area_sqm or 0,
        tenure=l.tenure or "",
        street=addr,
    )

    print(f"  Running V2...", flush=True)
    v2 = run_v2_valuation(ev, l)

    return {
        "epc_sqm": sqm, "epc_rating": rating,
        "fa_source": l.floor_area_source or "None", "fa_val": l.floor_area_sqm or 0,
        "direct": v2.direct.comp_count, "direct_val": v2.direct.valuation,
        "dev": v2.development.comp_count, "dev_val": v2.development.valuation,
        "local": v2.local_market.comp_count,
        "blended": v2.final.fair_value_balanced,
        "conf_score": v2.final.confidence_score,
        "conf_label": v2.final.confidence_label,
        "status": v2.final.valuation_status,
    }


TESTS = [
    {
        "label": "1. Ruttle Close",
        "category": "Hidden house number",
        "without": PropertyListing(
            address="Ruttle Close, Cholsey", postcode="OX10 9FP",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
        ),
        "with": PropertyListing(
            address="Ruttle Close, Cholsey", postcode="OX10 9FP",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
            override_house_number="6", override_street_name="Ruttle Close",
            overrides_applied=["House: 6", "Street: Ruttle Close"],
        ),
    },
    {
        "label": "2. Chestnut Close",
        "category": "Hidden house number",
        "without": PropertyListing(
            address="Chestnut Close, Witney", postcode="OX28 1PD",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
        ),
        "with": PropertyListing(
            address="Chestnut Close, Witney", postcode="OX28 1PD",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
            override_house_number="24", override_street_name="Chestnut Close",
            overrides_applied=["House: 24", "Street: Chestnut Close"],
        ),
    },
    {
        "label": "3. Ingestre Road",
        "category": "Flat/block identity",
        "without": PropertyListing(
            address="Ingestre Road, Prenton", postcode="CH43 5UY",
            asking_price=160000, property_type="Flat", bedrooms=2, tenure="Leasehold",
        ),
        "with": PropertyListing(
            address="Ingestre Road, Prenton", postcode="CH43 5UY",
            asking_price=160000, property_type="Flat", bedrooms=2, tenure="Leasehold",
            override_house_number="6", override_building_name="Ingestre Court",
            override_street_name="Ingestre Road",
            overrides_applied=["Number: 6", "Building: Ingestre Court"],
        ),
    },
    {
        "label": "4. Chestnut Close (wrong PC)",
        "category": "Postcode mismatch",
        "without": PropertyListing(
            address="24 Chestnut Close, Witney", postcode="OX28 1GH",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
        ),
        "with": PropertyListing(
            address="24 Chestnut Close, Witney", postcode="OX28 1GH",
            asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
            override_postcode="OX28 1PD",
            overrides_applied=["Postcode: OX28 1PD (was OX28 1GH)"],
        ),
    },
    {
        "label": "5. Thorney Leys (control)",
        "category": "No override needed",
        "without": PropertyListing(
            address="26 Thorney Leys, Witney", postcode="OX28 5NR",
            asking_price=275000, property_type="Terraced", bedrooms=3,
            floor_area_sqm=64.0, floor_area_source="Rightmove", tenure="Freehold",
        ),
        "with": PropertyListing(
            address="26 Thorney Leys, Witney", postcode="OX28 5NR",
            asking_price=275000, property_type="Terraced", bedrooms=3,
            floor_area_sqm=64.0, floor_area_source="Rightmove", tenure="Freehold",
        ),
    },
]


print("OVERRIDE VALIDATION - 5 PROPERTIES", flush=True)
print("=" * 85, flush=True)

summary_rows = []

for t in TESTS:
    print(f"\n--- {t['label']} ({t['category']}) ---", flush=True)

    print(f" WITHOUT:", flush=True)
    wo = run_one(t["label"], t["category"], t["without"])

    print(f" WITH:", flush=True)
    wi = run_one(t["label"], t["category"], t["with"])

    # Compare
    improvements = []
    if wi["epc_sqm"] > 0 and wo["epc_sqm"] == 0:
        improvements.append(f"EPC: 0->{wi['epc_sqm']:.0f}sqm")
    if wi["direct"] > wo["direct"]:
        improvements.append(f"Direct: {wo['direct']}->{wi['direct']}")
    if wi["dev"] > wo["dev"]:
        improvements.append(f"Dev: {wo['dev']}->{wi['dev']}")
    if wi["conf_score"] > wo["conf_score"]:
        improvements.append(f"Conf: {wo['conf_score']}->{wi['conf_score']}")
    if wi["blended"] > 0 and wo["blended"] == 0:
        improvements.append("Valuation now possible")

    verdict = "IMPROVED" if improvements else "NO CHANGE"

    print(f"\n  RESULT: {verdict}", flush=True)
    print(f"    EPC:     {wo['epc_sqm']:.0f} -> {wi['epc_sqm']:.0f} sqm", flush=True)
    print(f"    FA src:  {wo['fa_source']} -> {wi['fa_source']}", flush=True)
    print(f"    Direct:  {wo['direct']} -> {wi['direct']} comps | {wo['direct_val']:,.0f} -> {wi['direct_val']:,.0f}", flush=True)
    print(f"    Dev:     {wo['dev']} -> {wi['dev']} comps | {wo['dev_val']:,.0f} -> {wi['dev_val']:,.0f}", flush=True)
    print(f"    Local:   {wo['local']} -> {wi['local']} comps", flush=True)
    print(f"    V2:      {wo['blended']:,.0f} -> {wi['blended']:,.0f}", flush=True)
    print(f"    Conf:    {wo['conf_label']}({wo['conf_score']}) -> {wi['conf_label']}({wi['conf_score']})", flush=True)
    if improvements:
        print(f"    Changes: {', '.join(improvements)}", flush=True)

    summary_rows.append({
        "label": t["label"], "category": t["category"], "verdict": verdict,
        "key": improvements[0] if improvements else "none",
        "wo": wo, "wi": wi,
    })

print(f"\n\n{'=' * 85}", flush=True)
print("SUMMARY TABLE", flush=True)
print(f"{'=' * 85}", flush=True)
print(f"{'Property':<30} {'Category':<22} {'EPC':<15} {'V2 value':<25} {'Conf':<20} {'Verdict'}", flush=True)
print(f"{'-'*30} {'-'*22} {'-'*15} {'-'*25} {'-'*20} {'-'*10}", flush=True)
for r in summary_rows:
    wo, wi = r["wo"], r["wi"]
    epc_str = f"{wo['epc_sqm']:.0f}->{wi['epc_sqm']:.0f}"
    val_str = f"{wo['blended']:,.0f}->{wi['blended']:,.0f}"
    conf_str = f"{wo['conf_score']}->{wi['conf_score']}"
    print(f"{r['label']:<30} {r['category']:<22} {epc_str:<15} {val_str:<25} {conf_str:<20} {r['verdict']}", flush=True)

improved = sum(1 for r in summary_rows if r["verdict"] == "IMPROVED")
print(f"\nOverrides improved {improved}/{len(summary_rows)} properties.", flush=True)
print(f"{'=' * 85}", flush=True)
