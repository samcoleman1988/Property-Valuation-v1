"""Model validation baseline runner.

Runs the fixed 20-property validation set against the current V1 and V2
engines and writes timestamped CSV + JSON outputs to validation_baselines/.

This script does not alter valuation logic. It is a read-only harness
around run_v2_valuation() / calculate_valuation().

Usage:
    python validate_baseline.py
    python validate_baseline.py --label my-run-note

See README.md "Model Validation Baseline" section for details on what
gets logged and why, in particular the valuation-date / recency-drift
caveat: the underlying engine computes comparable age against
datetime.now() at fetch time, not a single frozen date passed through
the pipeline. This script logs a per-property fetch timestamp for
exactly that reason — so drift across a long run is visible, not silent.
"""
import sys, os, time, json, csv, argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.valuation_engine_v2 import run_v2_valuation, MODEL_VERSION, MODEL_VERSION_DATE
from src.epc import lookup_subject_floor_area
from src.hpi import get_hpi_diagnostics
from src.utils import format_currency

# --- Fixed 20-property validation set -------------------------------------
# Same properties/postcodes used throughout this session's EQ and Evidence
# Status validation runs, kept identical here for cross-run comparability.
# See baselines/v2-evidence-status-fallback-guard/manifest.json for a known
# postcode discrepancy against project memory that has NOT been applied here.

PROPERTIES = [
    {"n": 1, "label": "Ruttle Close, Cholsey", "postcode": "OX10 9QT",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 425000, "street": "Ruttle Close"},
    {"n": 2, "label": "Chestnut Close, Witney", "postcode": "OX28 1GH",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 425000, "street": "Chestnut Close"},
    {"n": 3, "label": "Thorney Leys, Witney", "postcode": "OX28 5NR",
     "type": "Terraced", "beds": 3, "tenure": "Freehold", "asking": 275000, "street": "Thorney Leys"},
    {"n": 4, "label": "Ingestre Road, Prenton", "postcode": "CH43 5UX",
     "type": "Flat", "beds": 2, "tenure": "Leasehold", "asking": 160000, "street": "Ingestre Road"},
    {"n": 5, "label": "Vyner Road South, Prenton", "postcode": "CH43 7PN",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 230000, "street": "Vyner Road South"},
    {"n": 6, "label": "Willowbank Road, Birkenhead", "postcode": "CH42 7JZ",
     "type": "Terraced", "beds": 2, "tenure": "Freehold", "asking": 120000, "street": "Willowbank Road"},
    {"n": 7, "label": "Magazine Lane, New Brighton", "postcode": "CH45 1HW",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 185000, "street": "Magazine Lane"},
    {"n": 8, "label": "Dee Park Road, Heswall", "postcode": "CH60 0BL",
     "type": "Detached House", "beds": 4, "tenure": "Freehold", "asking": 550000, "street": "Dee Park Road"},
    {"n": 9, "label": "Acacia Grove, Bebington", "postcode": "CH63 2HR",
     "type": "Bungalow", "beds": 2, "tenure": "Freehold", "asking": 295000, "street": "Acacia Grove"},
    {"n": 10, "label": "Headley Way, Oxford", "postcode": "OX3 7SU",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 550000, "street": "Headley Way"},
    {"n": 11, "label": "Saxton Road, Abingdon", "postcode": "OX14 5LN",
     "type": "Terraced", "beds": 2, "tenure": "Freehold", "asking": 275000, "street": "Saxton Road"},
    {"n": 12, "label": "Mereland Road, Didcot", "postcode": "OX11 8AZ",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 310000, "street": "Mereland Road"},
    {"n": 13, "label": "Witan Way, Witney", "postcode": "OX28 6FH",
     "type": "Flat", "beds": 1, "tenure": "Leasehold", "asking": 160000, "street": "Witan Way"},
    {"n": 14, "label": "High Street, Wallingford", "postcode": "OX10 0BX",
     "type": "Terraced", "beds": 3, "tenure": "Freehold", "asking": 375000, "street": "High Street"},
    {"n": 15, "label": "Bostock Road, Abingdon", "postcode": "OX14 1DT",
     "type": "Detached House", "beds": 4, "tenure": "Freehold", "asking": 475000, "street": "Bostock Road"},
    {"n": 16, "label": "Mill Street, Eynsham", "postcode": "OX29 4JX",
     "type": "Terraced", "beds": 2, "tenure": "Freehold", "asking": 350000, "street": "Mill Street"},
    {"n": 17, "label": "Monks Close, Carterton", "postcode": "OX18 3RF",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 265000, "street": "Monks Close"},
    {"n": 18, "label": "Bracken Close, Didcot", "postcode": "OX11 7TG",
     "type": "Detached House", "beds": 3, "tenure": "Freehold", "asking": 340000, "street": "Bracken Close"},
    {"n": 19, "label": "Yewdale Park, Prenton", "postcode": "CH43 5YQ",
     "type": "Flat", "beds": 2, "tenure": "Leasehold", "asking": 130000, "street": "Yewdale Park"},
    {"n": 20, "label": "Ladygrove, Didcot", "postcode": "OX11 7UG",
     "type": "Terraced", "beds": 3, "tenure": "Freehold", "asking": 295000, "street": "Ladygrove"},
]

GROUP_KEYS = ["Direct Evidence", "Development Evidence", "Local Market Evidence", "Area Market Evidence"]


def credibility_judgement(v2_value: float, asking: float, confidence_label: str) -> str:
    """Heuristic diagnostic computed by THIS SCRIPT for reporting only.

    Not part of the valuation engine, not used anywhere in valuation
    logic. Purely a coarse label to make the CSV/JSON scannable.
    """
    if v2_value <= 0 or confidence_label in ("None", ""):
        return "INSUFFICIENT_EVIDENCE"
    gap_pct = (v2_value - asking) / asking
    if abs(gap_pct) <= 0.15:
        return "CREDIBLE"
    if abs(gap_pct) <= 0.35:
        return "REVIEW"
    return "QUESTIONABLE"


def run_one(p: dict) -> dict:
    fetch_ts = datetime.now().isoformat()
    listing = PropertyListing(
        address=f"{p['street']}, {p['label'].split(',')[-1].strip()}",
        postcode=p["postcode"],
        asking_price=p["asking"],
        property_type=p["type"],
        bedrooms=p["beds"],
        tenure=p["tenure"],
        override_street_name=p["street"],
        overrides_applied=[f"Street: {p['street']}"],
    )

    row = {
        "n": p["n"],
        "property": p["label"],
        "postcode": p["postcode"],
        "property_type": p["type"],
        "bedrooms": p["beds"],
        "asking_price": p["asking"],
        "fetch_timestamp": fetch_ts,
        "elapsed_seconds": None,
        "v1_value": None,
        "v2_value": None,
        "v2_confidence_label": None,
        "v2_confidence_score": None,
        "v1_recommendation_tagline": None,
        "v2_recommendation_tagline": None,
        "credibility_judgement": None,
        "gap_pct_vs_asking": None,
        "hpi_source": None,
        "hpi_region": None,
        "hpi_latest_month": None,
        "error": None,
    }
    for gname in GROUP_KEYS:
        key = gname.lower().replace(" ", "_")
        row[f"{key}_status"] = None
        row[f"{key}_weight"] = None
        row[f"{key}_comp_count"] = None
        row[f"{key}_confidence_label"] = None
        row[f"{key}_confidence_score"] = None

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

        row["v1_value"] = v1_val
        row["v2_value"] = v2_val
        row["v2_confidence_label"] = v2.final.confidence_label
        row["v2_confidence_score"] = v2.final.confidence_score
        row["v1_recommendation_tagline"] = v1.recommendation.investment_tagline if v1.recommendation else None
        row["v2_recommendation_tagline"] = v2.final.recommendation.investment_tagline if v2.final.recommendation else None
        row["credibility_judgement"] = credibility_judgement(v2_val, p["asking"], v2.final.confidence_label)
        row["gap_pct_vs_asking"] = round((v2_val - p["asking"]) / p["asking"] * 100, 1) if v2_val > 0 else None

        hpi_diag = get_hpi_diagnostics("England")
        row["hpi_source"] = hpi_diag["source"]
        row["hpi_region"] = hpi_diag["region"]
        row["hpi_latest_month"] = hpi_diag["latest_month"]

        for g in v2.groups:
            key = g.name.lower().replace(" ", "_")
            row[f"{key}_status"] = g.evidence_status
            row[f"{key}_weight"] = round(g.weight_in_final, 4)
            row[f"{key}_comp_count"] = g.comp_count
            row[f"{key}_confidence_label"] = g.confidence_label
            row[f"{key}_confidence_score"] = g.confidence_score

    except Exception as e:
        row["error"] = str(e)

    row["elapsed_seconds"] = round(time.time() - start, 1)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="", help="Optional free-text note appended to the output filename")
    args = parser.parse_args()

    run_started_at = datetime.now()
    timestamp = run_started_at.strftime("%Y%m%d_%H%M%S")
    label_suffix = f"_{args.label}" if args.label else ""
    out_dir = os.path.join(os.path.dirname(__file__), "validation_baselines")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"{timestamp}_baseline_{MODEL_VERSION}{label_suffix}.csv")
    json_path = os.path.join(out_dir, f"{timestamp}_baseline_{MODEL_VERSION}{label_suffix}.json")

    print(f"Model version: {MODEL_VERSION} ({MODEL_VERSION_DATE})", flush=True)
    print(f"Run started at: {run_started_at.isoformat()}", flush=True)
    print(f"Properties: {len(PROPERTIES)}", flush=True)
    print(f"Output: {csv_path}", flush=True)
    print(flush=True)

    rows = []
    for p in PROPERTIES:
        print(f"[{p['n']}/20] {p['label']} ({p['postcode']})...", flush=True)
        row = run_one(p)
        rows.append(row)
        if row["error"]:
            print(f"  *** ERROR: {row['error']} *** [{row['elapsed_seconds']}s]", flush=True)
        else:
            print(f"  V1={format_currency(row['v1_value'])} V2={format_currency(row['v2_value'])} "
                  f"({row['v2_confidence_label']}) {row['credibility_judgement']} "
                  f"[{row['elapsed_seconds']}s]", flush=True)

    run_finished_at = datetime.now()

    # --- Summary counts ---
    status_totals = {"STRONG": 0, "WEAK": 0, "FALLBACK_ONLY": 0, "EMPTY": 0, None: 0}
    for row in rows:
        for gname in GROUP_KEYS:
            key = gname.lower().replace(" ", "_")
            status_totals[row.get(f"{key}_status")] = status_totals.get(row.get(f"{key}_status"), 0) + 1
    n_errors = sum(1 for r in rows if r["error"])
    n_ok = len(rows) - n_errors
    credibility_totals = {}
    for row in rows:
        cj = row.get("credibility_judgement")
        if cj:
            credibility_totals[cj] = credibility_totals.get(cj, 0) + 1

    meta = {
        "model_version": MODEL_VERSION,
        "model_version_date": MODEL_VERSION_DATE,
        "hpi_diagnostics": get_hpi_diagnostics("England"),
        "run_started_at": run_started_at.isoformat(),
        "run_finished_at": run_finished_at.isoformat(),
        "run_duration_seconds": round((run_finished_at - run_started_at).total_seconds(), 1),
        "properties_total": len(PROPERTIES),
        "properties_succeeded": n_ok,
        "properties_failed": n_errors,
        "evidence_status_totals": {str(k): v for k, v in status_totals.items() if k is not None},
        "credibility_judgement_totals": credibility_totals,
        "note_on_valuation_date": (
            "Each property's comparable age (age_days) and HPI-adjusted prices "
            "are computed against datetime.now() inside comparable_engine.py at "
            "the moment that property is fetched, NOT against a single frozen "
            "date for the whole run. See per-property 'fetch_timestamp' below. "
            "On a run this long, comparables can cross the 3-year (Direct) or "
            "5-year (Development) recency cutoff between the first and last "
            "property tested — this is expected engine behaviour, not a bug in "
            "this validation script."
        ),
    }

    # --- Write JSON ---
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "results": rows}, f, indent=2, default=str)

    # --- Write CSV ---
    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(flush=True)
    print("=" * 80, flush=True)
    print("BASELINE VALIDATION COMPLETE", flush=True)
    print("=" * 80, flush=True)
    print(f"Model version: {MODEL_VERSION}", flush=True)
    print(f"HPI source:    {meta['hpi_diagnostics']}", flush=True)
    print(f"Run started:   {run_started_at.isoformat()}", flush=True)
    print(f"Run finished:  {run_finished_at.isoformat()}", flush=True)
    print(f"Duration:      {meta['run_duration_seconds']}s", flush=True)
    print(f"Properties:    {n_ok} succeeded, {n_errors} failed (of {len(PROPERTIES)})", flush=True)
    print(f"Evidence status totals: {meta['evidence_status_totals']}", flush=True)
    print(f"Credibility totals:     {credibility_totals}", flush=True)
    print(f"CSV:  {csv_path}", flush=True)
    print(f"JSON: {json_path}", flush=True)


if __name__ == "__main__":
    main()
