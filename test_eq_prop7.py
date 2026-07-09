"""EQ validation — property 7 only."""
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

listing = PropertyListing(
    address="Magazine Lane, New Brighton", postcode="CH45 1HW",
    asking_price=185000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
    override_street_name="Magazine Lane",
    overrides_applied=["Street: Magazine Lane"])

print("7. Magazine Lane, Wallasey (semi, 3bed, CH45)", flush=True)
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
print("DONE", flush=True)
