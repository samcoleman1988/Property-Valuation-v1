"""Diagnose Vyner Road's Direct Evidence comp-count drift (7 -> 3)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables, _is_same_street_or_building
from src.valuation_engine_v2 import (
    _extract_subject_street, MAX_DIRECT_AGE_DAYS, is_property_type_compatible,
    _subject_type_code,
)
from src.epc import lookup_subject_floor_area
from src.utils import format_currency

listing = PropertyListing(
    address="Vyner Road South, Prenton", postcode="CH43 7PN",
    asking_price=230000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
    override_street_name="Vyner Road South",
    overrides_applied=["Street: Vyner Road South"])

addr = listing.effective_address_first_line
pc = listing.effective_postcode
street = listing.effective_street
sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
if sqm > 0 and not listing.floor_area_sqm:
    listing.floor_area_sqm = sqm

ev = fetch_and_score_comparables(
    postcode=pc, property_type=listing.property_type or "",
    bedrooms=listing.bedrooms or 0, floor_area_sqm=listing.floor_area_sqm or 0,
    tenure=listing.tenure or "", street=addr)

subject_street = _extract_subject_street(listing)
subject_addr_first = listing.address.split(",")[0].strip()
subject_code = _subject_type_code(listing)

print(f"Total scored: {len(ev.scored_comparables)}, context-only: {len(ev.context_only_comparables)}")
print()

all_comps = ev.scored_comparables + ev.context_only_comparables
candidates = []
for c in all_comps:
    is_same, reason = _is_same_street_or_building(c, subject_street, subject_addr_first)
    prox_level = c.score_breakdown.get("proximity_level", 0)
    if is_same or prox_level >= 4:
        candidates.append((c, is_same, reason, prox_level))

print(f"Comps matching same-street/building or proximity>=4: {len(candidates)}")
for c, is_same, reason, prox_level in candidates:
    rel = is_property_type_compatible(subject_code, c.property_type_code)
    age_ok = c.age_days <= MAX_DIRECT_AGE_DAYS
    print(f"  {c.address[:50]:50s} | type={c.property_type_code or '?'} ({rel}) | "
          f"age={c.age_days}d ({c.age_days/365.25:.1f}y) | within 3yr: {age_ok} | "
          f"price={format_currency(c.price)} | same_street={is_same} prox={prox_level}")
