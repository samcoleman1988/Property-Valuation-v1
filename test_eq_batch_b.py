"""EQ validation batch B — properties 8-14."""
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
    {"label": "8. Dee Park Road, Heswall (det, 4bed, CH60)",
     "listing": PropertyListing(
         address="Dee Park Road, Heswall", postcode="CH60 0DE",
         asking_price=550000, property_type="Detached House", bedrooms=4, tenure="Freehold",
         override_street_name="Dee Park Road",
         overrides_applied=["Street: Dee Park Road"])},

    {"label": "9. Acacia Grove, West Kirby (bungalow, 2bed, CH48)",
     "listing": PropertyListing(
         address="Acacia Grove, West Kirby", postcode="CH48 4DY",
         asking_price=295000, property_type="Bungalow", bedrooms=2, tenure="Freehold",
         override_street_name="Acacia Grove",
         overrides_applied=["Street: Acacia Grove"])},

    {"label": "10. Headley Way, Headington (semi, 3bed, OX3)",
     "listing": PropertyListing(
         address="Headley Way, Headington", postcode="OX3 7SW",
         asking_price=550000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Headley Way",
         overrides_applied=["Street: Headley Way"])},

    {"label": "11. Saxton Road, Abingdon (terr, 2bed, OX14)",
     "listing": PropertyListing(
         address="Saxton Road, Abingdon", postcode="OX14 5LN",
         asking_price=275000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Saxton Road",
         overrides_applied=["Street: Saxton Road"])},

    {"label": "12. Mereland Road, Didcot (semi, 3bed, OX11)",
     "listing": PropertyListing(
         address="Mereland Road, Didcot", postcode="OX11 8AZ",
         asking_price=310000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Mereland Road",
         overrides_applied=["Street: Mereland Road"])},

    {"label": "13. Witan Way, Witney (flat, 1bed, OX28)",
     "listing": PropertyListing(
         address="Witan Way, Witney", postcode="OX28 6FH",
         asking_price=160000, property_type="Flat", bedrooms=1, tenure="Leasehold",
         override_street_name="Witan Way",
         overrides_applied=["Street: Witan Way"])},

    {"label": "14. High Street, Wallingford (terr, 3bed, OX10)",
     "listing": PropertyListing(
         address="High Street, Wallingford", postcode="OX10 0BX",
         asking_price=375000, property_type="Terraced", bedrooms=3, tenure="Freehold",
         override_street_name="High Street",
         overrides_applied=["Street: High Street"])},
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
print("  BATCH B COMPLETE (8-14)", flush=True)
print(f"{'#' * 80}", flush=True)
