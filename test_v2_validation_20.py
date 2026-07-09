"""20-property V2 validation — diverse types, locations, price points."""

import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.valuation_engine_v2 import run_v2_valuation
from src.explanation_engine import explain_valuation
from src.epc import lookup_subject_floor_area
from src.utils import format_currency


PROPERTIES = [
    # === EXISTING 4 TEST PROPERTIES ===
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

    # === WIRRAL / MERSEYSIDE ===
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

    # === OXFORDSHIRE ===
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

    # === OTHER REGIONS (diversity) ===
    {"label": "15. Bostock Road, Abingdon (det, 4bed, OX14)",
     "listing": PropertyListing(
         address="Bostock Road, Abingdon", postcode="OX14 1DL",
         asking_price=475000, property_type="Detached House", bedrooms=4, tenure="Freehold",
         override_street_name="Bostock Road",
         overrides_applied=["Street: Bostock Road"])},

    {"label": "16. Mill Street, Eynsham (cottage, 2bed, OX29)",
     "listing": PropertyListing(
         address="Mill Street, Eynsham", postcode="OX29 4JS",
         asking_price=350000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Mill Street",
         overrides_applied=["Street: Mill Street"])},

    {"label": "17. Monks Close, Carterton (semi, 3bed, OX18)",
     "listing": PropertyListing(
         address="Monks Close, Carterton", postcode="OX18 3RF",
         asking_price=265000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Monks Close",
         overrides_applied=["Street: Monks Close"])},

    {"label": "18. Bracken Close, Didcot (det, 3bed, OX11)",
     "listing": PropertyListing(
         address="Bracken Close, Didcot", postcode="OX11 7TG",
         asking_price=340000, property_type="Detached House", bedrooms=3, tenure="Freehold",
         override_street_name="Bracken Close",
         overrides_applied=["Street: Bracken Close"])},

    {"label": "19. Yewdale Park, Prenton (flat, 2bed, CH43)",
     "listing": PropertyListing(
         address="Yewdale Park, Prenton", postcode="CH43 5YQ",
         asking_price=130000, property_type="Flat", bedrooms=2, tenure="Leasehold",
         override_street_name="Yewdale Park",
         overrides_applied=["Street: Yewdale Park"])},

    {"label": "20. Ladygrove, Didcot (terr, 3bed, OX11)",
     "listing": PropertyListing(
         address="Ladygrove, Didcot", postcode="OX11 7UG",
         asking_price=295000, property_type="Terraced", bedrooms=3, tenure="Freehold",
         override_street_name="Ladygrove",
         overrides_applied=["Street: Ladygrove"])},
]


results = []

for t in PROPERTIES:
    label = t["label"]
    listing = t["listing"]
    print(f"\n{'=' * 80}", flush=True)
    print(f"  {label}", flush=True)
    print(f"{'=' * 80}", flush=True)

    try:
        # EPC lookup
        addr = listing.effective_address_first_line
        pc = listing.effective_postcode
        street = listing.effective_street

        sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
        if sqm > 0 and not listing.floor_area_sqm:
            listing.floor_area_sqm = sqm
            listing.floor_area_source = "EPC"

        # Comparables
        ev = fetch_and_score_comparables(
            postcode=pc, property_type=listing.property_type or "",
            bedrooms=listing.bedrooms or 0, floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "", street=addr,
        )

        # V1
        signals = interpret_listing(description="", key_features=[], property_type=listing.property_type or "")
        v1 = calculate_valuation(
            asking_price=listing.asking_price, evidence=ev, signals=signals,
            floor_area_sqm=listing.floor_area_sqm or 0, tenure=listing.tenure or "", region="England",
        )

        # V2 + explanation
        v2 = run_v2_valuation(ev, listing)
        expl = explain_valuation(v2, listing)

        # Evidence group dominance
        active = [g for g in v2.groups if g.comp_count > 0]
        dominant = max(active, key=lambda g: g.weight_in_final) if active else None
        dominant_str = f"{dominant.name} ({dominant.weight_in_final:.0%})" if dominant else "None"

        # Group details
        group_detail = []
        for g in v2.groups:
            if g.comp_count > 0:
                type_str = ""
                if g.type_exact_count or g.type_compatible_count or g.type_incompatible_fallback_count or g.type_excluded_count:
                    type_str = f", types:{g.type_exact_count}e/{g.type_compatible_count}c/{g.type_incompatible_fallback_count}fb/{g.type_excluded_count}x"
                group_detail.append(f"{g.name}: {g.comp_count}c, {format_currency(g.valuation)}, {g.confidence_label}({g.confidence_score}), wt={g.weight_in_final:.0%}{type_str}")
            else:
                group_detail.append(f"{g.name}: empty")

        # V1 vs V2 difference
        v1_val = v1.fair_value_balanced or 0
        v2_val = v2.final.fair_value_balanced or 0
        if v1_val > 0 and v2_val > 0:
            diff_pct = ((v2_val - v1_val) / v1_val) * 100
            diff_str = f"{diff_pct:+.1f}%"
            material_diff = abs(diff_pct) > 10
        else:
            diff_str = "N/A"
            material_diff = False

        # Explanation quality
        expl_sections = sum([
            1 if expl.executive_summary else 0,
            1 if expl.key_drivers else 0,
            1 if expl.evidence_hierarchy else 0,
            1 if expl.confidence_explanation else 0,
            1 if expl.offer_rationale else 0,
            1 if expl.overall_verdict else 0,
            1 if expl.why_not_highest else 0,
            1 if expl.evidence_conflicts else 0,
            1 if expl.risks else 0,
            1 if expl.strengths else 0,
        ])

        # Asking price vs V2 fair value
        if v2_val > 0:
            ask_gap = ((listing.asking_price - v2_val) / v2_val) * 100
            ask_gap_str = f"{ask_gap:+.1f}%"
        else:
            ask_gap_str = "N/A"

        rec = {
            "label": label,
            "asking": listing.asking_price,
            "v2_fair": v2_val,
            "v2_conf_score": v2.final.confidence_score,
            "v2_conf_label": v2.final.confidence_label,
            "v1_fair": v1_val,
            "v1_conf": f"{v1.confidence_label} ({v1.confidence_score})",
            "diff_pct": diff_str,
            "material_diff": material_diff,
            "dominant_group": dominant_str,
            "groups": group_detail,
            "active_groups": len(active),
            "expl_sections": expl_sections,
            "expl_drivers": len(expl.key_drivers),
            "expl_risks": len(expl.risks),
            "expl_strengths": len(expl.strengths),
            "ask_vs_v2": ask_gap_str,
            "floor_area": f"{listing.floor_area_sqm or 0:.0f} sqm ({listing.floor_area_source or 'Unknown'})",
            "exec_summary_start": (expl.executive_summary or "")[:100],
            "verdict_start": (expl.overall_verdict or "")[:100],
            "error": None,
        }
        results.append(rec)

        print(f"  Asking: {format_currency(listing.asking_price)}", flush=True)
        print(f"  V2: {format_currency(v2_val)} | {v2.final.confidence_label} ({v2.final.confidence_score})", flush=True)
        print(f"  V1: {format_currency(v1_val)} | {v1.confidence_label} ({v1.confidence_score})", flush=True)
        print(f"  V2-V1 diff: {diff_str} {'*** MATERIAL ***' if material_diff else ''}", flush=True)
        print(f"  Dominant: {dominant_str}", flush=True)
        print(f"  Active groups: {len(active)}/4", flush=True)
        print(f"  Floor area: {listing.floor_area_sqm or 0:.0f} sqm ({listing.floor_area_source or 'Unknown'})", flush=True)
        print(f"  Explanation: {expl_sections}/10 sections, {len(expl.key_drivers)} drivers", flush=True)
        print(f"  Ask vs V2: {ask_gap_str}", flush=True)
        for gd in group_detail:
            print(f"    {gd}", flush=True)

    except Exception as e:
        rec = {"label": label, "error": str(e)}
        results.append(rec)
        print(f"  *** ERROR: {e} ***", flush=True)
        import traceback
        traceback.print_exc()


# === SUMMARY ===
print(f"\n\n{'#' * 80}", flush=True)
print("  VALIDATION SUMMARY", flush=True)
print(f"{'#' * 80}", flush=True)

ok = [r for r in results if not r.get("error")]
err = [r for r in results if r.get("error")]
print(f"\n  Completed: {len(ok)}/20", flush=True)
if err:
    print(f"  Errors: {len(err)}", flush=True)
    for e in err:
        print(f"    {e['label']}: {e['error']}", flush=True)

# Confidence distribution
high = [r for r in ok if r["v2_conf_label"] == "High"]
med = [r for r in ok if r["v2_conf_label"] == "Medium"]
low = [r for r in ok if r["v2_conf_label"] == "Low"]
none_ = [r for r in ok if r["v2_conf_label"] not in ("High", "Medium", "Low")]
print(f"\n  Confidence: High={len(high)}, Medium={len(med)}, Low={len(low)}, Other={len(none_)}", flush=True)

# Material V1 differences
mat = [r for r in ok if r.get("material_diff")]
print(f"\n  Material V1/V2 differences (>10%): {len(mat)}", flush=True)
for m in mat:
    print(f"    {m['label']}: V2={format_currency(m['v2_fair'])}, V1={format_currency(m['v1_fair'])}, diff={m['diff_pct']}", flush=True)

# Asking price vs V2
print(f"\n  Asking vs V2 fair value:", flush=True)
for r in ok:
    print(f"    {r['label'][:45]:45s}  Ask={format_currency(r['asking']):>10s}  V2={format_currency(r['v2_fair']):>10s}  Gap={r['ask_vs_v2']:>7s}  Conf={r['v2_conf_label']:>6s}({r['v2_conf_score']})", flush=True)

# Active group counts
print(f"\n  Active evidence groups:", flush=True)
for n in [1, 2, 3, 4]:
    ct = len([r for r in ok if r.get("active_groups") == n])
    if ct:
        print(f"    {n} groups: {ct} properties", flush=True)

# Explanation quality
print(f"\n  Explanation quality:", flush=True)
avg_sec = sum(r["expl_sections"] for r in ok) / len(ok) if ok else 0
avg_drv = sum(r["expl_drivers"] for r in ok) / len(ok) if ok else 0
print(f"    Avg sections populated: {avg_sec:.1f}/10", flush=True)
print(f"    Avg key drivers: {avg_drv:.1f}", flush=True)

# Floor area coverage
with_fa = [r for r in ok if "0 sqm" not in r.get("floor_area", "0 sqm")]
print(f"\n  Floor area known: {len(with_fa)}/{len(ok)}", flush=True)

print(f"\n{'#' * 80}", flush=True)
print("  VALIDATION COMPLETE", flush=True)
print(f"{'#' * 80}", flush=True)
