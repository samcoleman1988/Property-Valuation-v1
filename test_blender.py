"""Test V2 evidence blender with Local Market Evidence.

Reports Direct, Development, Local, V2 blended, and V1 values side-by-side.
"""

import sys, os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.valuation_engine_v2 import run_v2_valuation
from src.valuation_engine import calculate_valuation
from src.listing_interpreter import ListingSignals

TESTS = [
    {
        "label": "1. Ruttle Close, Cholsey",
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

# Previous V2 blended values (before Local Market) for comparison
PREV_V2 = {
    "1. Ruttle Close, Cholsey": 441600,
    "2. Thorney Leys, Witney": 302600,
    "3. Ingestre Road, Prenton": 130600,
    "4. Chestnut Close, Witney": 448900,
}


def run_test(t):
    listing = t["listing"]
    print(f"\nFetching {t['label']} ({listing.postcode})...")

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

    v2 = run_v2_valuation(evidence, listing)

    signals = ListingSignals()
    v1 = calculate_valuation(
        asking_price=listing.asking_price,
        evidence=evidence,
        signals=signals,
        floor_area_sqm=listing.floor_area_sqm or 0.0,
        tenure=listing.tenure or "",
        region="England",
    )

    return {"label": t["label"], "listing": listing, "v2": v2, "v1": v1}


results = []
for t in TESTS:
    results.append(run_test(t))

print("\n" + "=" * 95)
print("V2 BLENDER TEST RESULTS (with Local Market)")
print("=" * 95)

for r in results:
    v2 = r["v2"]
    v1 = r["v1"]
    d = v2.direct
    dev = v2.development
    loc = v2.local_market
    f = v2.final
    listing = r["listing"]
    label = r["label"]
    prev = PREV_V2.get(label, 0)

    print(f"\n{'-' * 95}")
    print(f"  {label} ({listing.postcode})  |  Asking: {listing.asking_price:,.0f}")
    print(f"{'-' * 95}")

    # Direct
    if d.comp_count > 0:
        print(f"  Direct:      {d.valuation:,.0f}  ({d.confidence_label}, {d.confidence_score}, {d.comp_count} comps)")
    else:
        print(f"  Direct:      -- no comps --")

    # Development
    if dev.comp_count > 0:
        print(f"  Development: {dev.valuation:,.0f}  ({dev.confidence_label}, {dev.confidence_score}, {dev.comp_count} comps)")
    else:
        print(f"  Development: -- no comps --")

    # Local Market
    if loc.comp_count > 0:
        print(f"  Local Mkt:   {loc.valuation:,.0f}  ({loc.confidence_label}, {loc.confidence_score}, {loc.comp_count} comps)")
        print(f"               range {loc.valuation_low:,.0f} - {loc.valuation_high:,.0f}")
    else:
        print(f"  Local Mkt:   -- no comps --")

    # V2 blended
    print(f"  V2 blended:  {f.fair_value_balanced:,.0f}  ({f.confidence_label}, {f.confidence_score})")
    print(f"               range {f.fair_value_conservative:,.0f} - {f.fair_value_aggressive:,.0f}")
    print(f"               status: {f.valuation_status}")

    # Weights
    weights = f.reconciliation.group_weights
    if weights:
        w_str = ", ".join(f"{k.replace(' Evidence', '')}={v:.0%}" for k, v in weights.items())
        print(f"               weights: {w_str}")

    # Conflicts
    if f.reconciliation.conflicts:
        for c in f.reconciliation.conflicts:
            print(f"               !! {c}")

    # Before/after Local
    if prev > 0:
        delta = f.fair_value_balanced - prev
        if abs(delta) > 0:
            direction = "up" if delta > 0 else "down"
            mid = (f.fair_value_balanced + prev) / 2
            print(f"               vs pre-Local: {prev:,.0f} -> {f.fair_value_balanced:,.0f} ({direction} {abs(delta):,.0f}, {abs(delta)/mid:.1%})")
        else:
            print(f"               vs pre-Local: unchanged")

    # Gap
    if f.asking_vs_fair_gap != 0:
        direction = "above" if f.asking_vs_fair_gap > 0 else "below"
        print(f"               asking is {abs(f.asking_vs_fair_gap):,.0f} ({abs(f.asking_vs_fair_gap_pct):.1f}%) {direction} V2 fair value")

    # V1
    if v1.fair_value_balanced > 0:
        print(f"  V1 value:    {v1.fair_value_balanced:,.0f}  ({v1.confidence_label}, {v1.confidence_score})")
        v1_v2_diff = abs(v1.fair_value_balanced - f.fair_value_balanced)
        mid = (v1.fair_value_balanced + f.fair_value_balanced) / 2
        if mid > 0:
            print(f"               V1 vs V2 differ by {v1_v2_diff:,.0f} ({v1_v2_diff/mid:.1%})")
    else:
        print(f"  V1 value:    -- insufficient evidence --  (status: {v1.valuation_status})")

    # Local Market detail
    if loc.comp_count > 0:
        print(f"  Local detail:")
        for s in loc.strengths[:3]:
            print(f"    + {s}")
        for w in loc.weaknesses[:3]:
            print(f"    - {w}")

print(f"\n{'=' * 95}")
