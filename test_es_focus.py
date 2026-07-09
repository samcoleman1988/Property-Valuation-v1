"""Evidence Status validation — 5 focus cases only."""
import sys, os, time
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
    {"label": "5. Vyner Rd South, Prenton (semi, 3bed, CH43)",
     "listing": PropertyListing(
         address="Vyner Road South, Prenton", postcode="CH43 7PN",
         asking_price=230000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Vyner Road South",
         overrides_applied=["Street: Vyner Road South"])},

    {"label": "6. Willowbank Rd, Birkenhead (terr, 2bed, CH42)",
     "listing": PropertyListing(
         address="Willowbank Road, Birkenhead", postcode="CH42 7JZ",
         asking_price=120000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Willowbank Road",
         overrides_applied=["Street: Willowbank Road"])},

    {"label": "10. Headley Way, Oxford (semi, 3bed, OX3)",
     "listing": PropertyListing(
         address="Headley Way, Oxford", postcode="OX3 7SU",
         asking_price=550000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Headley Way",
         overrides_applied=["Street: Headley Way"])},

    {"label": "14. High Street, Wallingford (terr, 3bed, OX10)",
     "listing": PropertyListing(
         address="High Street, Wallingford", postcode="OX10 0BX",
         asking_price=375000, property_type="Terraced", bedrooms=3, tenure="Freehold",
         override_street_name="High Street",
         overrides_applied=["Street: High Street"])},

    {"label": "16. Mill Street, Eynsham (terr, 2bed, OX29)",
     "listing": PropertyListing(
         address="Mill Street, Eynsham", postcode="OX29 4JX",
         asking_price=350000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Mill Street",
         overrides_applied=["Street: Mill Street"])},
]

totals = {"STRONG": 0, "WEAK": 0, "FALLBACK_ONLY": 0, "EMPTY": 0}

for t in PROPERTIES:
    label = t["label"]
    listing = t["listing"]
    print(f"\n{'=' * 80}", flush=True)
    print(f"  {label}", flush=True)
    print(f"{'=' * 80}", flush=True)
    start = time.time()
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
            tenure=listing.tenure or "", street=addr)
        signals = interpret_listing(description="", key_features=[], property_type=listing.property_type or "")
        v1 = calculate_valuation(
            asking_price=listing.asking_price, evidence=ev, signals=signals,
            floor_area_sqm=listing.floor_area_sqm or 0, tenure=listing.tenure or "", region="England")
        v2 = run_v2_valuation(ev, listing)
        v1_val = v1.fair_value_balanced or 0
        v2_val = v2.final.fair_value_balanced or 0
        elapsed = time.time() - start
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
                print(f"    {g.name}: {g.comp_count}c, {format_currency(g.valuation)}, conf={g.confidence_label}({g.confidence_score}), EQ={g.evidence_quality}, ES={g.evidence_status}, wt={g.weight_in_final:.0%}{ts}", flush=True)
                print(f"      Status reason: {g.evidence_status_reason}", flush=True)
                totals[g.evidence_status] += 1
            else:
                print(f"    {g.name}: empty", flush=True)
                totals["EMPTY"] += 1
        print(f"  [{elapsed:.0f}s]", flush=True)
    except Exception as e:
        print(f"  *** ERROR: {e} ***", flush=True)
        import traceback
        traceback.print_exc()

print(f"\n{'#' * 80}", flush=True)
print(f"  FOCUS CASES COMPLETE", flush=True)
print(f"  STRONG: {totals['STRONG']} | WEAK: {totals['WEAK']} | FALLBACK_ONLY: {totals['FALLBACK_ONLY']} | EMPTY: {totals['EMPTY']}", flush=True)
print(f"{'#' * 80}", flush=True)
