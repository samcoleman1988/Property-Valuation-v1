"""EQ validation batch A — properties 1-7."""
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
from src.epc import lookup_subject_floor_area
from src.utils import format_currency

PROPERTIES = [
    {"label": "1. Ruttle Close, Cholsey (semi, 3bed, OX10)",
     "listing": PropertyListing(
         address="Ruttle Close, Cholsey", postcode="OX10 9FP",
         asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_house_number="6", override_street_name="Ruttle Close",
         overrides_applied=["House: 6"])},

    {"label": "2. Chestnut Close, Witney (semi, 3bed, OX28)",
     "listing": PropertyListing(
         address="Chestnut Close, Witney", postcode="OX28 1PD",
         asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_house_number="24", override_street_name="Chestnut Close",
         overrides_applied=["House: 24"])},

    {"label": "3. Thorney Leys, Witney (terr, 3bed, OX28)",
     "listing": PropertyListing(
         address="26 Thorney Leys, Witney", postcode="OX28 5NR",
         asking_price=275000, property_type="Terraced", bedrooms=3,
         floor_area_sqm=64.0, floor_area_source="Rightmove", tenure="Freehold")},

    {"label": "4. Ingestre Road, Prenton (flat, 2bed, CH43)",
     "listing": PropertyListing(
         address="Ingestre Road, Prenton", postcode="CH43 5UY",
         asking_price=160000, property_type="Flat", bedrooms=2, tenure="Leasehold",
         override_building_name="Ingestre Court", override_street_name="Ingestre Road",
         overrides_applied=["Building: Ingestre Court"])},

    {"label": "5. Vyner Road South, Prenton (semi, 3bed, CH43)",
     "listing": PropertyListing(
         address="Vyner Road South, Prenton", postcode="CH43 7PN",
         asking_price=230000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Vyner Road South",
         overrides_applied=["Street: Vyner Road South"])},

    {"label": "6. Willowbank Road, Birkenhead (terr, 2bed, CH42)",
     "listing": PropertyListing(
         address="Willowbank Road, Birkenhead", postcode="CH42 7JZ",
         asking_price=120000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Willowbank Road",
         overrides_applied=["Street: Willowbank Road"])},

    {"label": "7. Magazine Lane, Wallasey (semi, 3bed, CH45)",
     "listing": PropertyListing(
         address="Magazine Lane, New Brighton", postcode="CH45 1HW",
         asking_price=185000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Magazine Lane",
         overrides_applied=["Street: Magazine Lane"])},
]


def run_property(t):
    label = t["label"]
    listing = t["listing"]
    print(f"\n{'=' * 80}", flush=True)
    print(f"  {label}", flush=True)
    print(f"{'=' * 80}", flush=True)

    try:
        addr = listing.effective_address_first_line
        pc = listing.effective_postcode
        street = listing.effective_street

        sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
        if sqm > 0 and not listing.floor_area_sqm:
            listing.floor_area_sqm = sqm
            listing.floor_area_source = "EPC"

        ev = fetch_and_score_comparables(
            postcode=pc, property_type=listing.property_type or "",
            bedrooms=listing.bedrooms or 0, floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "", street=addr,
        )

        signals = interpret_listing(description="", key_features=[], property_type=listing.property_type or "")
        v1 = calculate_valuation(
            asking_price=listing.asking_price, evidence=ev, signals=signals,
            floor_area_sqm=listing.floor_area_sqm or 0, tenure=listing.tenure or "", region="England",
        )

        v2 = run_v2_valuation(ev, listing)

        v1_val = v1.fair_value_balanced or 0
        v2_val = v2.final.fair_value_balanced or 0

        print(f"  Asking: {format_currency(listing.asking_price)}", flush=True)
        print(f"  V2: {format_currency(v2_val)} | {v2.final.confidence_label} ({v2.final.confidence_score})", flush=True)
        print(f"  V1: {format_currency(v1_val)}", flush=True)

        recon = v2.final.reconciliation
        print(f"  Method: {recon.method}", flush=True)
        if recon.assumptions:
            for a in recon.assumptions:
                print(f"  Assumption: {a}", flush=True)

        for g in v2.groups:
            if g.comp_count > 0:
                ts = ""
                if g.type_exact_count or g.type_compatible_count or g.type_incompatible_fallback_count or g.type_excluded_count:
                    ts = f", types:{g.type_exact_count}e/{g.type_compatible_count}c/{g.type_incompatible_fallback_count}fb/{g.type_excluded_count}x"
                print(f"    {g.name}: {g.comp_count}c, {format_currency(g.valuation)}, conf={g.confidence_label}({g.confidence_score}), EQ={g.evidence_quality}, wt={g.weight_in_final:.0%}{ts}", flush=True)
            else:
                print(f"    {g.name}: empty", flush=True)

    except Exception as e:
        print(f"  *** ERROR: {e} ***", flush=True)
        import traceback
        traceback.print_exc()


for t in PROPERTIES:
    run_property(t)

print(f"\n{'#' * 80}", flush=True)
print("  BATCH A COMPLETE (1-7)", flush=True)
print(f"{'#' * 80}", flush=True)
