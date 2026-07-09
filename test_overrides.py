"""Test manual identity overrides: EPC matching and evidence impact.

Tests:
1. Church Green, Witney — Rightmove address lacks house number
2. Ingestre Road — with manual building name override
3. Ruttle Close — with and without house number for EPC matching
"""

import sys, os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.valuation_engine_v2 import run_v2_valuation
from src.epc import lookup_subject_floor_area


def test_epc_match(label, postcode, address, street=""):
    """Test EPC matching with given address info."""
    sqm, rating, detail = lookup_subject_floor_area(
        postcode=postcode,
        address=address,
        street=street,
    )
    print(f"  EPC: {sqm:.0f} sqm, rating={rating}, detail={detail}")
    return sqm, rating


def test_property(label, listing_without, listing_with, skip_api=False):
    """Compare analysis with and without overrides."""
    print(f"\n{'=' * 80}")
    print(f"  {label}")
    print(f"{'=' * 80}")

    # EPC matching: without overrides
    print(f"\n  WITHOUT overrides:")
    print(f"    address for EPC: '{listing_without.effective_address_first_line}'")
    print(f"    postcode for EPC: '{listing_without.effective_postcode}'")
    sqm_before, rating_before = test_epc_match(
        label,
        listing_without.effective_postcode,
        listing_without.effective_address_first_line,
        listing_without.effective_street,
    )

    # EPC matching: with overrides
    print(f"\n  WITH overrides:")
    print(f"    address for EPC: '{listing_with.effective_address_first_line}'")
    print(f"    postcode for EPC: '{listing_with.effective_postcode}'")
    print(f"    overrides: {listing_with.overrides_applied}")
    sqm_after, rating_after = test_epc_match(
        label,
        listing_with.effective_postcode,
        listing_with.effective_address_first_line,
        listing_with.effective_street,
    )

    epc_improved = (sqm_after > 0 and sqm_before == 0) or (sqm_after > 0 and sqm_before > 0)

    if skip_api:
        print(f"\n  EPC match: {'IMPROVED' if sqm_after > 0 and sqm_before == 0 else 'same' if sqm_after == sqm_before else 'changed'}")
        print(f"    floor area: {sqm_before:.0f} -> {sqm_after:.0f} sqm")
        return

    # Full V2 valuation: without overrides
    print(f"\n  Fetching comparables (without overrides)...")
    street_wo = listing_without.effective_address_first_line
    ev_wo = fetch_and_score_comparables(
        postcode=listing_without.effective_postcode,
        property_type=listing_without.property_type or "",
        bedrooms=listing_without.bedrooms or 0,
        floor_area_sqm=sqm_before if sqm_before > 0 else listing_without.floor_area_sqm or 0,
        tenure=listing_without.tenure or "",
        street=street_wo,
    )

    # Apply EPC floor area to listing for V2
    listing_without_copy = PropertyListing(**listing_without.to_dict())
    if sqm_before > 0 and not listing_without_copy.floor_area_sqm:
        listing_without_copy.floor_area_sqm = sqm_before
        listing_without_copy.floor_area_source = "EPC"

    v2_wo = run_v2_valuation(ev_wo, listing_without_copy)

    # Full V2 valuation: with overrides
    print(f"  Fetching comparables (with overrides)...")
    street_w = listing_with.effective_address_first_line
    ev_w = fetch_and_score_comparables(
        postcode=listing_with.effective_postcode,
        property_type=listing_with.property_type or "",
        bedrooms=listing_with.bedrooms or 0,
        floor_area_sqm=sqm_after if sqm_after > 0 else listing_with.floor_area_sqm or 0,
        tenure=listing_with.tenure or "",
        street=street_w,
    )

    listing_with_copy = PropertyListing(**listing_with.to_dict())
    if sqm_after > 0 and not listing_with_copy.floor_area_sqm:
        listing_with_copy.floor_area_sqm = sqm_after
        listing_with_copy.floor_area_source = "EPC"

    v2_w = run_v2_valuation(ev_w, listing_with_copy)

    # Report
    print(f"\n  COMPARISON:")
    print(f"    EPC floor area:  {sqm_before:.0f} -> {sqm_after:.0f} sqm  ({'IMPROVED' if sqm_after > 0 and sqm_before == 0 else 'same' if sqm_after == sqm_before else 'changed'})")
    print(f"    Direct comps:    {v2_wo.direct.comp_count} -> {v2_w.direct.comp_count}")
    if v2_wo.direct.valuation or v2_w.direct.valuation:
        print(f"    Direct val:      {v2_wo.direct.valuation:,.0f} -> {v2_w.direct.valuation:,.0f}")
    print(f"    Dev comps:       {v2_wo.development.comp_count} -> {v2_w.development.comp_count}")
    if v2_wo.development.valuation or v2_w.development.valuation:
        print(f"    Dev val:         {v2_wo.development.valuation:,.0f} -> {v2_w.development.valuation:,.0f}")
    print(f"    Local comps:     {v2_wo.local_market.comp_count} -> {v2_w.local_market.comp_count}")
    print(f"    V2 blended:      {v2_wo.final.fair_value_balanced:,.0f} -> {v2_w.final.fair_value_balanced:,.0f}")
    print(f"    V2 confidence:   {v2_wo.final.confidence_label} ({v2_wo.final.confidence_score}) -> {v2_w.final.confidence_label} ({v2_w.final.confidence_score})")


# --- Test 1: Church Green, Witney ---
# Rightmove often shows "Church Green, Witney" without house number
test_property(
    "Church Green, Witney - house number override",
    listing_without=PropertyListing(
        address="Church Green, Witney",
        postcode="OX28 6AZ",
        asking_price=500000,
        property_type="Terraced",
        bedrooms=3,
        tenure="Freehold",
    ),
    listing_with=PropertyListing(
        address="Church Green, Witney",
        postcode="OX28 6AZ",
        asking_price=500000,
        property_type="Terraced",
        bedrooms=3,
        tenure="Freehold",
        override_house_number="22",
        override_street_name="Church Green",
        overrides_applied=["House/flat number: 22", "Street name: Church Green"],
    ),
)

# --- Test 2: Ingestre Road with building name ---
test_property(
    "Ingestre Road - building name override",
    listing_without=PropertyListing(
        address="Ingestre Road, Prenton",
        postcode="CH43 5UY",
        asking_price=160000,
        property_type="Flat",
        bedrooms=2,
        floor_area_sqm=68.0,
        floor_area_source="Rightmove",
        tenure="Leasehold",
    ),
    listing_with=PropertyListing(
        address="Ingestre Road, Prenton",
        postcode="CH43 5UY",
        asking_price=160000,
        property_type="Flat",
        bedrooms=2,
        floor_area_sqm=68.0,
        floor_area_source="Rightmove",
        tenure="Leasehold",
        override_house_number="6",
        override_building_name="Ingestre Court",
        override_street_name="Ingestre Road",
        overrides_applied=["House/flat number: 6", "Building: Ingestre Court", "Street: Ingestre Road"],
    ),
)

# --- Test 3: Ruttle Close - house number for EPC ---
test_property(
    "Ruttle Close - house number for EPC",
    listing_without=PropertyListing(
        address="Ruttle Close, Cholsey",
        postcode="OX10 9FP",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
    ),
    listing_with=PropertyListing(
        address="Ruttle Close, Cholsey",
        postcode="OX10 9FP",
        asking_price=425000,
        property_type="Semi-Detached",
        bedrooms=3,
        tenure="Freehold",
        override_house_number="6",
        override_street_name="Ruttle Close",
        overrides_applied=["House/flat number: 6", "Street: Ruttle Close"],
    ),
)

print(f"\n{'=' * 80}")
print("OVERRIDE TESTS COMPLETE")
print(f"{'=' * 80}")
