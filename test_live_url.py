"""Live URL pre-flight: extraction, valuation, PDF, DB save."""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from src.rightmove_parser import parse_listing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.investment_scorecard import calculate_scorecard
from src.risk_assessor import assess_risks
from src.planning import assess_planning
from src.transport import assess_location
from src.report_generator import generate_report
from src.property_db import save_property, get_property
from src.utils import format_currency

URL = "https://www.rightmove.co.uk/properties/169974434#/?channel=RES_BUY"

# === 1. EXTRACTION ===
print("=" * 60)
print("1. LISTING EXTRACTION")
print("=" * 60)
listing = parse_listing(URL)
fields = {
    "Address": listing.address,
    "Postcode": listing.postcode,
    "Asking Price": listing.asking_price,
    "Price Qualifier": listing.price_qualifier,
    "Property Type": listing.property_type,
    "Bedrooms": listing.bedrooms,
    "Bathrooms": listing.bathrooms,
    "Receptions": listing.receptions,
    "Tenure": listing.tenure,
    "Floor Area (sqft)": listing.floor_area_sqft,
    "Floor Area (sqm)": listing.floor_area_sqm,
    "EPC Rating": listing.epc_rating,
    "Agent": listing.agent_name,
    "Latitude": listing.latitude,
    "Longitude": listing.longitude,
    "Council Tax Band": listing.council_tax_band,
    "Date Listed": listing.date_listed,
    "Key Features": listing.key_features,
}
missing = []
for k, v in fields.items():
    status = ""
    if v in (0, 0.0, "", None, []):
        status = "  <-- MISSING"
        missing.append(k)
    print(f"  {k}: {v}{status}")

desc = (listing.description or "")[:300]
print(f"  Description (first 300): {desc}")
print(f"  Extraction Warnings: {listing.extraction_warnings}")
print(f"  Missing fields: {missing if missing else 'None'}")
has_price = listing.asking_price > 0
has_postcode = bool(listing.postcode)
print(f"  RESULT: {'PASS' if has_price and has_postcode else 'FAIL'}")

if not has_price or not has_postcode:
    print("Cannot continue without price and postcode")
    sys.exit(1)

# === 2. VALUATION ===
print()
print("=" * 60)
print("2. VALUATION")
print("=" * 60)
signals = interpret_listing(
    description=listing.description or "",
    key_features=listing.key_features or [],
    property_type=listing.property_type or "",
)
print(f"  Condition: {signals.condition_label} ({signals.condition_score}/10)")

street = ""
if listing.address:
    parts = listing.address.split(",")
    if parts:
        street = parts[0].strip()

evidence = fetch_and_score_comparables(
    postcode=listing.postcode,
    property_type=listing.property_type or "",
    bedrooms=listing.bedrooms or 0,
    floor_area_sqm=listing.floor_area_sqm or 0,
    tenure=listing.tenure or "",
    latitude=listing.latitude or 0,
    longitude=listing.longitude or 0,
    street=street,
)
print(f"  Comparables: {evidence.total_scored} scored "
      f"(A={evidence.tier_a_count} B={evidence.tier_b_count} "
      f"C={evidence.tier_c_count} D={evidence.tier_d_count})")
print(f"  Excluded: {getattr(evidence, 'excluded_count', 'N/A')}")

valuation = calculate_valuation(
    asking_price=listing.asking_price,
    evidence=evidence,
    signals=signals,
    floor_area_sqm=listing.floor_area_sqm or 0,
    tenure=listing.tenure or "",
    region="England",
)
print(f"  Status: {valuation.valuation_status}")
print(f"  Confidence: {valuation.confidence_label} ({valuation.confidence_score}/100)")
bal = valuation.fair_value_balanced
con = valuation.fair_value_conservative
agg = valuation.fair_value_aggressive
print(f"  Balanced: {format_currency(bal) if bal else 'NOT PRODUCED'}")
print(f"  Conservative: {format_currency(con) if con else 'NOT PRODUCED'}")
print(f"  Aggressive: {format_currency(agg) if agg else 'NOT PRODUCED'}")
if valuation.asking_vs_fair_gap_pct:
    print(f"  Gap vs asking: {valuation.asking_vs_fair_gap_pct:+.1f}%")
if valuation.max_sensible_offer:
    print(f"  Max offer: {format_currency(valuation.max_sensible_offer)}")
print(f"  Tagline: {valuation.investment_tagline}")
if valuation.comparable_spread_cv:
    print(f"  Spread CV: {valuation.comparable_spread_cv:.1%}")
print(f"  Warnings: {valuation.warnings}")
print(f"  Data gaps: {valuation.data_gaps}")

if valuation.comparable_details:
    print("  Top 3 comparables:")
    for c in valuation.comparable_details[:3]:
        tier = c.get("tier", c.get("quality_band", ""))
        addr = c.get("address", "?")[:45]
        price = format_currency(c.get("price", 0))
        date = str(c.get("date", ""))[:11]
        print(f"    {addr} | {price} | {date} | Tier {tier}")

try:
    planning_result = assess_planning(
        postcode=listing.postcode,
        property_type=listing.property_type,
        bedrooms=listing.bedrooms or 0,
        current_value=valuation.fair_value_balanced or listing.asking_price,
        latitude=listing.latitude or 0,
        longitude=listing.longitude or 0,
    )
    planning_dict = (
        planning_result.to_dict() if hasattr(planning_result, "to_dict")
        else (planning_result if isinstance(planning_result, dict) else {})
    )
except Exception:
    planning_dict = {}

location = assess_location(
    postcode=listing.postcode,
    latitude=listing.latitude or 0,
    longitude=listing.longitude or 0,
)
location_dict = location.to_dict()

scorecard = calculate_scorecard(
    valuation=valuation,
    planning_result=planning_dict,
    btl_result={},
    location_result=location_dict,
    mode="personal",
)
risk = assess_risks(
    valuation=valuation,
    signals=signals,
    planning_result=planning_dict,
    btl_result={},
    tenure=listing.tenure or "",
)
print(f"  Score: {scorecard.overall_score:.0f}/100 - {scorecard.verdict}")
print(f"  Risk: {risk.overall_risk_level} ({len(risk.flags)} flags)")
for f in sorted(risk.flags, key=lambda f: {"High": 0, "Medium": 1, "Low": 2}.get(f.severity, 3))[:3]:
    print(f"    [{f.severity}] {f.title}: {f.explanation}")
print("  RESULT: PASS")

# === 3. PDF ===
print()
print("=" * 60)
print("3. PDF GENERATION")
print("=" * 60)
score_dict = scorecard.to_dict()
risk_dict = risk.to_dict()
score_dict["flags"] = risk_dict.get("flags", [])
score_dict["summary"] = risk_dict.get("summary", "")

report_path = generate_report(
    listing=listing.to_dict(),
    valuation=valuation.to_dict(),
    planning=planning_dict,
    btl={},
    location=location_dict,
    investment_score=score_dict,
    mode="personal",
)
sz = os.path.getsize(report_path) / 1024
print(f"  Path: {report_path}")
print(f"  Size: {sz:.1f} KB")
print(f"  RESULT: {'PASS' if sz > 1 else 'FAIL'}")

# === 4. DB SAVE ===
print()
print("=" * 60)
print("4. DATABASE SAVE")
print("=" * 60)
pid = save_property(
    url=URL,
    address=listing.address or "",
    postcode=listing.postcode,
    property_type=listing.property_type or "",
    bedrooms=listing.bedrooms or 0,
    bathrooms=listing.bathrooms if hasattr(listing, "bathrooms") else 0,
    floor_area_sqm=listing.floor_area_sqm or 0,
    tenure=listing.tenure or "",
    asking_price=listing.asking_price,
    valuation_result=valuation.to_dict(),
    scorecard_result=score_dict,
    risk_result=risk_dict,
    listing_data=listing.to_dict(),
    comparable_data={
        "total": evidence.total_scored,
        "tier_a": evidence.tier_a_count,
        "tier_b": evidence.tier_b_count,
        "tier_c": evidence.tier_c_count,
    },
    mode="personal",
    notes="category:preflight_live",
)
prop = get_property(pid)
ok = (prop is not None
      and prop["postcode"] == listing.postcode
      and prop["asking_price"] == listing.asking_price)
print(f"  Saved ID: {pid}")
print(f"  Retrieved and verified: {ok}")
print(f"  RESULT: {'PASS' if ok else 'FAIL'}")

# === 5. FIELD ASSESSMENT ===
print()
print("=" * 60)
print("5. EXTRACTION FIELD ASSESSMENT")
print("=" * 60)
for f in missing:
    print(f"  MISSING: {f}")
if not missing:
    print("  All fields populated")

questionable = []
expected_types = (
    "Detached House", "Semi-Detached House", "Terraced House",
    "End of Terrace", "Flat", "Bungalow", "Cottage", "Maisonette",
    "Detached", "Semi-Detached", "Terraced", "End Terrace",
    "Flat / Apartment", "Park Home",
)
if listing.property_type and listing.property_type not in expected_types:
    questionable.append(
        f'Property type "{listing.property_type}" may need mapping for valuation engine'
    )
expected_tenure = ("Freehold", "Leasehold", "Share of Freehold")
if listing.tenure and listing.tenure not in expected_tenure:
    questionable.append(
        f'Tenure "{listing.tenure}" may not match valuation engine expectations'
    )
if listing.floor_area_sqm and (listing.floor_area_sqm < 20 or listing.floor_area_sqm > 500):
    questionable.append(f"Floor area {listing.floor_area_sqm} sqm looks unusual")

for q in questionable:
    print(f"  QUESTIONABLE: {q}")
if not questionable:
    print("  No questionable values")
print(f"  Extraction warnings: {listing.extraction_warnings if listing.extraction_warnings else 'None'}")

# === SUMMARY ===
print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  1. Extraction:  {'PASS' if has_price and has_postcode else 'FAIL'}")
print(f"  2. Valuation:   PASS")
print(f"  3. PDF:         {'PASS' if sz > 1 else 'FAIL'}")
print(f"  4. DB Save:     {'PASS' if ok else 'FAIL'}")
print(f"  5. Missing:     {len(missing)} field(s)")
print(f"     Questionable: {len(questionable)} field(s)")
