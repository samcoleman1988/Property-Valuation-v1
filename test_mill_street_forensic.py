"""Forensic analysis of Mill Street Eynsham — Development Evidence group."""
import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables, PROPERTY_TYPE_REVERSE
from src.epc import lookup_subject_floor_area
from src.valuation_engine_v2 import (
    run_v2_valuation, is_property_type_compatible, _subject_type_code,
    _development_affinity, _extract_subject_street, _is_direct_comp,
    MAX_DIRECT_AGE_DAYS, MAX_DEV_AGE_DAYS,
)
from src.comparable_engine import _is_same_street_or_building, _normalise_street
from src.utils import postcode_sector, postcode_outcode, format_currency
import numpy as np

listing = PropertyListing(
    address="Mill Street, Eynsham", postcode="OX29 4JX",
    asking_price=350000, property_type="Terraced", bedrooms=2, tenure="Freehold",
    override_street_name="Mill Street",
    overrides_applied=["Street: Mill Street"])

# Fetch evidence (uses cache if available)
print("Fetching evidence for Mill Street, Eynsham...", flush=True)
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

print(f"Subject: {listing.address}, {listing.postcode}", flush=True)
print(f"Type: {listing.property_type} (code: {PROPERTY_TYPE_REVERSE.get(listing.property_type.lower().strip(), '?')})", flush=True)
print(f"Floor area: {listing.floor_area_sqm} sqm ({getattr(listing, 'floor_area_source', 'unknown')})", flush=True)
print(f"Total scored comps: {ev.total_scored}", flush=True)
print(f"Total context-only: {len(ev.context_only_comparables)}", flush=True)

# Run V2 to get the groups
v2 = run_v2_valuation(ev, listing)
dev = v2.development

print(f"\n{'=' * 80}")
print(f"DEVELOPMENT EVIDENCE GROUP — FORENSIC ANALYSIS")
print(f"{'=' * 80}")
print(f"Comp count: {dev.comp_count}")
print(f"Valuation: {format_currency(dev.valuation)}")
print(f"Median: {format_currency(dev.median_value)}")
print(f"Weighted mean: {format_currency(dev.weighted_mean)}")
print(f"Evidence Quality: {dev.evidence_quality}")
print(f"Evidence Status: {dev.evidence_status}")
print(f"Status reason: {dev.evidence_status_reason}")
print(f"Type counts: {dev.type_exact_count}e / {dev.type_compatible_count}c / {dev.type_incompatible_fallback_count}fb / {dev.type_excluded_count}x")

subject_code = _subject_type_code(listing)

# Now dump every comparable in the Dev group
print(f"\n{'=' * 80}")
print(f"INDIVIDUAL COMPARABLES IN DEVELOPMENT GROUP")
print(f"{'=' * 80}")

adj_prices = []
for i, c in enumerate(dev.comparables):
    rel = is_property_type_compatible(subject_code, c.property_type_code)
    type_names = {"D": "Detached", "S": "Semi-Detached", "T": "Terraced", "F": "Flat"}

    sqm_str = f"{c.floor_area_sqm:.0f} sqm" if c.floor_area_sqm and c.floor_area_sqm > 0 else "unknown"
    ppsqm = f"£{c.adjusted_price / c.floor_area_sqm:,.0f}/sqm" if c.floor_area_sqm and c.floor_area_sqm > 0 and c.adjusted_price > 0 else "n/a"

    # Re-compute affinity for this comp
    subject_street_norm = _extract_subject_street(listing)
    subject_postcode = listing.postcode or ""
    subject_sector_val = postcode_sector(subject_postcode) if subject_postcode else ""
    subject_outcode_val = postcode_outcode(subject_postcode) if subject_postcode else ""
    affinity, aff_reason = _development_affinity(
        c, subject_postcode, subject_street_norm, subject_sector_val, subject_outcode_val)

    years_ago = c.age_days / 365.25

    print(f"\n--- Comp {i+1} of {dev.comp_count} ---")
    print(f"  Address:          {c.address}")
    print(f"  Street:           {c.street}")
    print(f"  Postcode:         {c.postcode}")
    print(f"  Property type:    {type_names.get(c.property_type_code, c.property_type_code)} ({c.property_type_code})")
    print(f"  Type relation:    {rel} (subject={subject_code})")
    print(f"  Floor area:       {sqm_str}")
    print(f"  Sale price:       {format_currency(c.price)}")
    print(f"  Adjusted price:   {format_currency(c.adjusted_price)}")
    print(f"  £/sqm:            {ppsqm}")
    print(f"  Sale date:        {c.date}")
    print(f"  Age:              {c.age_days} days ({years_ago:.1f} years)")
    print(f"  Affinity score:   {affinity:.2f} — {aff_reason}")
    print(f"  Evidence tier:    {c.tier}")
    print(f"  New build:        {c.new_build}")
    print(f"  Tenure:           {c.tenure}")

    if c.adjusted_price > 0:
        adj_prices.append(c.adjusted_price)

# Statistical analysis
print(f"\n{'=' * 80}")
print(f"STATISTICAL ANALYSIS")
print(f"{'=' * 80}")

if adj_prices:
    arr = np.array(adj_prices)
    mean_p = np.mean(arr)
    median_p = np.median(arr)
    std_p = np.std(arr)
    cv = std_p / mean_p if mean_p > 0 else 0
    q1 = np.percentile(arr, 25)
    q3 = np.percentile(arr, 75)
    iqr = q3 - q1

    print(f"  Count:            {len(adj_prices)}")
    print(f"  Mean:             {format_currency(mean_p)}")
    print(f"  Median:           {format_currency(median_p)}")
    print(f"  Std deviation:    {format_currency(std_p)}")
    print(f"  CV:               {cv:.2%}")
    print(f"  Min:              {format_currency(np.min(arr))}")
    print(f"  Max:              {format_currency(np.max(arr))}")
    print(f"  Range:            {format_currency(np.max(arr) - np.min(arr))}")
    print(f"  Q1 (25th):        {format_currency(q1)}")
    print(f"  Q3 (75th):        {format_currency(q3)}")
    print(f"  IQR:              {format_currency(iqr)}")
    print(f"  Max/Min ratio:    {np.max(arr)/np.min(arr):.1f}x")

    # Type composition
    exact = dev.type_exact_count
    compat = dev.type_compatible_count
    fb = dev.type_incompatible_fallback_count
    total = exact + compat + fb
    print(f"\n  Type composition:")
    print(f"    Exact:          {exact} ({exact/total*100:.0f}%)")
    print(f"    Compatible:     {compat} ({compat/total*100:.0f}%)")
    print(f"    Fallback:       {fb} ({fb/total*100:.0f}%)")

    # By type breakdown
    print(f"\n  Price by property type:")
    type_prices = {}
    for c in dev.comparables:
        key = c.property_type_code or "?"
        if key not in type_prices:
            type_prices[key] = []
        if c.adjusted_price > 0:
            type_prices[key].append(c.adjusted_price)

    for tcode, prices in sorted(type_prices.items()):
        type_names_map = {"D": "Detached", "S": "Semi-Detached", "T": "Terraced", "F": "Flat"}
        tname = type_names_map.get(tcode, tcode)
        rel = is_property_type_compatible(subject_code, tcode)
        parr = np.array(prices)
        print(f"    {tname} ({tcode}, {rel}): n={len(prices)}, "
              f"mean={format_currency(np.mean(parr))}, "
              f"range={format_currency(np.min(parr))}–{format_currency(np.max(parr))}")

    # Floor area breakdown
    print(f"\n  Floor area analysis:")
    for c in dev.comparables:
        sqm_str = f"{c.floor_area_sqm:.0f}" if c.floor_area_sqm and c.floor_area_sqm > 0 else "?"
        ppsqm_str = f"£{c.adjusted_price / c.floor_area_sqm:,.0f}" if c.floor_area_sqm and c.floor_area_sqm > 0 and c.adjusted_price > 0 else "?"
        print(f"    {c.property_type_code} | {sqm_str:>4s} sqm | {format_currency(c.adjusted_price):>10s} | {ppsqm_str:>7s}/sqm | {c.street}")

print(f"\n{'=' * 80}")
print(f"EVIDENCE STATUS CLASSIFICATION WALKTHROUGH")
print(f"{'=' * 80}")
exact = dev.type_exact_count
compat = dev.type_compatible_count
fb = dev.type_incompatible_fallback_count
good = exact + compat
total = exact + compat + fb

print(f"  good_comps (exact + compat) = {exact} + {compat} = {good}")
print(f"  fallback = {fb}")
print(f"  FALLBACK_ONLY check: good_comps == 0 and fallback > 0? {good == 0 and fb > 0} -- {'YES' if good == 0 and fb > 0 else 'NO, passes this gate'}")
print(f"  good_comps >= 3? {good >= 3} -- {'STRONG candidate' if good >= 3 else 'WEAK: only ' + str(good) + ' exact/compatible'}")

fallback_ratio = fb / total if total > 0 else 0
print(f"  fallback_ratio = {fb}/{total} = {fallback_ratio:.0%}")
print(f"  fallback_ratio <= 0.25? {fallback_ratio <= 0.25}")

if dev.comparables:
    old_comps = sum(1 for c in dev.comparables if c.age_days > 1095)
    print(f"  old comps (>3yr): {old_comps}/{len(dev.comparables)}")
    print(f"  all old? {old_comps == len(dev.comparables)}")

    prices = [c.adjusted_price for c in dev.comparables if c.adjusted_price > 0]
    if len(prices) >= 2:
        mean_val = sum(prices) / len(prices)
        variance = sum((p - mean_val) ** 2 for p in prices) / len(prices)
        cv_val = (variance ** 0.5) / mean_val
        print(f"  CV = {cv_val:.2%} (threshold: 40%)")
        print(f"  CV > 0.40? {cv_val > 0.40}")

print(f"\n  → Classification: {dev.evidence_status}")
print(f"  → Reason: {dev.evidence_status_reason}")

# Final answer
print(f"\n{'=' * 80}")
print(f"DONE")
print(f"{'=' * 80}")
