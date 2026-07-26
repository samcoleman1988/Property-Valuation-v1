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

# --- Validation set --------------------------------------------------------
# Properties 1-20: the original fixed set used throughout this session's EQ
# and Evidence Status validation runs, kept identical here for cross-run
# comparability. See baselines/v2-evidence-status-fallback-guard/manifest.json
# for a known postcode discrepancy against project memory that has NOT been
# applied here.
#
# Properties 21-37: added under ROADMAP.md item 2 (validation dataset
# expansion). Every one of these was sourced from a live Rightmove listing
# fetched directly (WebSearch + WebFetch) during that session — postcode,
# price, type, and bedroom count are as shown on the listing at the time it
# was captured, not invented. "url", "why_selected", and "expected_challenge"
# are populated only for 21-37; the original 20 predate this metadata and are
# left blank rather than backfilled with speculative reasoning.
#
# This is a REGRESSION/EVALUATION set, not a training set — once added,
# entries should stay stable across runs rather than be swapped out, per
# ROADMAP.md item 2's validation philosophy.

PROPERTIES = [
    {"n": 1, "label": "Ruttle Close, Cholsey", "postcode": "OX10 9QT",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 425000, "street": "Ruttle Close",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 2, "label": "Chestnut Close, Witney", "postcode": "OX28 1GH",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 425000, "street": "Chestnut Close",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 3, "label": "Thorney Leys, Witney", "postcode": "OX28 5NR",
     "type": "Terraced", "beds": 3, "tenure": "Freehold", "asking": 275000, "street": "Thorney Leys",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 4, "label": "Ingestre Road, Prenton", "postcode": "CH43 5UX",
     "type": "Flat", "beds": 2, "tenure": "Leasehold", "asking": 160000, "street": "Ingestre Road",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 5, "label": "Vyner Road South, Prenton", "postcode": "CH43 7PN",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 230000, "street": "Vyner Road South",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 6, "label": "Willowbank Road, Birkenhead", "postcode": "CH42 7JZ",
     "type": "Terraced", "beds": 2, "tenure": "Freehold", "asking": 120000, "street": "Willowbank Road",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 7, "label": "Magazine Lane, New Brighton", "postcode": "CH45 1HW",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 185000, "street": "Magazine Lane",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 8, "label": "Dee Park Road, Heswall", "postcode": "CH60 0BL",
     "type": "Detached House", "beds": 4, "tenure": "Freehold", "asking": 550000, "street": "Dee Park Road",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 9, "label": "Acacia Grove, Bebington", "postcode": "CH63 2HR",
     "type": "Bungalow", "beds": 2, "tenure": "Freehold", "asking": 295000, "street": "Acacia Grove",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 10, "label": "Headley Way, Oxford", "postcode": "OX3 7SU",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 550000, "street": "Headley Way",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 11, "label": "Saxton Road, Abingdon", "postcode": "OX14 5LN",
     "type": "Terraced", "beds": 2, "tenure": "Freehold", "asking": 275000, "street": "Saxton Road",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 12, "label": "Mereland Road, Didcot", "postcode": "OX11 8AZ",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 310000, "street": "Mereland Road",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 13, "label": "Witan Way, Witney", "postcode": "OX28 6FH",
     "type": "Flat", "beds": 1, "tenure": "Leasehold", "asking": 160000, "street": "Witan Way",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 14, "label": "High Street, Wallingford", "postcode": "OX10 0BX",
     "type": "Terraced", "beds": 3, "tenure": "Freehold", "asking": 375000, "street": "High Street",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 15, "label": "Bostock Road, Abingdon", "postcode": "OX14 1DT",
     "type": "Detached House", "beds": 4, "tenure": "Freehold", "asking": 475000, "street": "Bostock Road",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 16, "label": "Mill Street, Eynsham", "postcode": "OX29 4JX",
     "type": "Terraced", "beds": 2, "tenure": "Freehold", "asking": 350000, "street": "Mill Street",
     "url": "", "why_selected": "", "expected_challenge": "Known false-affinity risk (Mill Street / THE MILL HOUSE) — see ROADMAP/session history."},
    {"n": 17, "label": "Monks Close, Carterton", "postcode": "OX18 3RF",
     "type": "Semi-Detached", "beds": 3, "tenure": "Freehold", "asking": 265000, "street": "Monks Close",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 18, "label": "Bracken Close, Didcot", "postcode": "OX11 7TG",
     "type": "Detached House", "beds": 3, "tenure": "Freehold", "asking": 340000, "street": "Bracken Close",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 19, "label": "Yewdale Park, Prenton", "postcode": "CH43 5YQ",
     "type": "Flat", "beds": 2, "tenure": "Leasehold", "asking": 130000, "street": "Yewdale Park",
     "url": "", "why_selected": "", "expected_challenge": ""},
    {"n": 20, "label": "Ladygrove, Didcot", "postcode": "OX11 7UG",
     "type": "Terraced", "beds": 3, "tenure": "Freehold", "asking": 295000, "street": "Ladygrove",
     "url": "", "why_selected": "", "expected_challenge": ""},

    # --- Expansion batch (ROADMAP.md item 2), sourced live 2026-07 ---
    {"n": 21, "label": "Tuckers Court, Richmond Villages, Witney", "postcode": "OX28 5DG",
     "type": "Flat", "beds": 2, "tenure": "Leasehold", "asking": 470000, "street": "Coral Springs Way",
     "url": "https://www.rightmove.co.uk/properties/168396455",
     "why_selected": "Age-restricted retirement development — very distinct market segment from ordinary flats.",
     "expected_challenge": "Retirement/age-restricted leasehold flat; comparables likely confined to the same development (sparse, high-affinity Estate Evidence test)."},
    {"n": 22, "label": "Coral Springs Way, Richmond Villages, Witney", "postcode": "OX28 5DG",
     "type": "Flat", "beds": 1, "tenure": "Leasehold", "asking": 325000, "street": "Coral Springs Way",
     "url": "https://www.rightmove.co.uk/properties/167852555",
     "why_selected": "Smallest/cheapest unit in the same retirement development as #21 — tests within-development price spread.",
     "expected_challenge": "1-bed retirement leasehold flat; sparse comparables outside the development itself."},
    {"n": 23, "label": "Woodford Mill, Mill Street, Witney", "postcode": "OX28 6DE",
     "type": "Flat", "beds": 2, "tenure": "", "asking": 270000, "street": "Mill Street",
     "url": "https://www.rightmove.co.uk/properties/169495439",
     "why_selected": "Converted mill building flat; tenure not stated on the listing — realistic data-gap case.",
     "expected_challenge": "Tenure unknown/unconfirmed at capture time; converted-building flat, floor area may be atypical."},
    {"n": 24, "label": "Lady Grove Road, Didcot", "postcode": "OX11 9BP",
     "type": "Semi-Detached", "beds": 4, "tenure": "", "asking": 499995, "street": "Lady Grove Road",
     "url": "https://www.rightmove.co.uk/properties/174812675",
     "why_selected": "Established estate with multiple concurrent listings on the same road (see #26 too) — good same-estate density test.",
     "expected_challenge": "Estate/development affinity — several same-road listings should mutually reinforce Estate Evidence once sold."},
    {"n": 25, "label": "Willington Down, Lady Grove, Didcot", "postcode": "OX11 9GG",
     "type": "Semi-Detached", "beds": 3, "tenure": "", "asking": 490000, "street": "Willington Down",
     "url": "https://www.rightmove.co.uk/properties/89462538",
     "why_selected": "Adjacent close within the same wider Lady Grove estate as #24.",
     "expected_challenge": "Tests whether Estate Evidence correctly links closely-related but differently-named streets within one development."},
    {"n": 26, "label": "Valley Park, Didcot", "postcode": "OX11 6LB",
     "type": "Semi-Detached", "beds": 4, "tenure": "", "asking": 459995, "street": "Valley Park",
     "url": "https://www.rightmove.co.uk/properties/88652370",
     "why_selected": "Newer-build estate, different part of Didcot from the Ladygrove/Lady Grove cluster.",
     "expected_challenge": "New-build-adjacent estate; existing hard gate excludes genuine new-build comparables, so evidence may be thinner than expected for a large estate."},
    {"n": 27, "label": "Ladygrove, Didcot", "postcode": "OX11 9BS",
     "type": "Semi-Detached", "beds": 4, "tenure": "", "asking": 450000, "street": "Ladygrove",
     "url": "https://www.rightmove.co.uk/properties/88952205",
     "why_selected": "Shares a street name with existing property #20 (Ladygrove, Didcot) but is a distinct address/price point — tests whether the two are correctly NOT conflated.",
     "expected_challenge": "Same street name as an existing validation entry — false-duplication / affinity risk analogous to the Mill Street case (#16)."},
    {"n": 28, "label": "Arundel Avenue, Aigburth, Liverpool", "postcode": "L17 2AU",
     "type": "Terraced", "beds": 7, "tenure": "", "asking": 330000, "street": "Arundel Avenue",
     "url": "https://www.rightmove.co.uk/properties/90724686",
     "why_selected": "Unusually high bedroom count for a terraced house — likely a converted/extended property.",
     "expected_challenge": "Unusual layout — 7-bed terrace may be an HMO-style conversion; floor area and £/bedroom will be atypical vs standard 3-bed terrace comparables."},
    {"n": 29, "label": "Alwyn Street, Aigburth, Liverpool", "postcode": "L17 7DY",
     "type": "Terraced", "beds": 4, "tenure": "Freehold", "asking": 270000, "street": "Alwyn Street",
     "url": "https://www.rightmove.co.uk/properties/90653370",
     "why_selected": "Dense inner-urban terraced street — expected to have plentiful genuine comparables, a useful contrast to the sparse-evidence cases in this set.",
     "expected_challenge": "Low expected challenge — control case for a well-evidenced urban terrace."},
    {"n": 30, "label": "Egerton Park, Birkenhead", "postcode": "CH42 4RB",
     "type": "Flat", "beds": 0, "tenure": "", "asking": 250000, "street": "Egerton Park",
     "url": "https://www.rightmove.co.uk/properties/87857151",
     "why_selected": "Part of a block of apartments; bedroom count and tenure were not stated on the listing at capture time.",
     "expected_challenge": "Missing bedroom count and tenure — tests engine behaviour with incomplete subject-property data."},
    {"n": 31, "label": "Woodchurch Lane, Birkenhead", "postcode": "CH42 9PD",
     "type": "Flat", "beds": 0, "tenure": "", "asking": 215000, "street": "Woodchurch Lane",
     "url": "https://www.rightmove.co.uk/properties/90088653",
     "why_selected": "Entry-level flat, block-of-apartments listing with no bedroom count stated.",
     "expected_challenge": "Missing bedroom count; entry-level price band for the North West portfolio area."},
    {"n": 32, "label": "Grove Road, Birkenhead", "postcode": "CH42 3XT",
     "type": "Flat", "beds": 5, "tenure": "", "asking": 165000, "street": "Grove Road",
     "url": "https://www.rightmove.co.uk/properties/89971422",
     "why_selected": "Very low asking price for a 5-bed listing — plausible multi-unit/investment-block sale, not a typical owner-occupier flat.",
     "expected_challenge": "Price/bedroom mismatch suggests a non-standard transaction type; good stress test for whether the engine (or the not-yet-implemented PPD Category filter, ROADMAP item 4) would flag this as atypical."},
    {"n": 33, "label": "Market Place, Faringdon", "postcode": "SN7 7HU",
     "type": "Detached House", "beds": 6, "tenure": "Freehold", "asking": 3000000, "street": "Market Place",
     "url": "https://www.rightmove.co.uk/properties/88645374",
     "why_selected": "Extreme premium price point in a small market town centre — deliberately stresses the top end of the price range.",
     "expected_challenge": "Sparse comparables expected at this price point; town-centre premium road; genuinely obvious high-price outlier vs local market."},
    {"n": 34, "label": "Arbor Park, Bodicote, Banbury", "postcode": "OX15 4BN",
     "type": "Terraced", "beds": 4, "tenure": "", "asking": 565000, "street": "Arbor Park",
     "url": "https://www.rightmove.co.uk/properties/90802227",
     "why_selected": "Village-edge new-ish estate near Banbury, multiple concurrent listings on the same close (see #35).",
     "expected_challenge": "Village location; estate/development affinity test alongside #35."},
    {"n": 35, "label": "Arbor Park, Bodicote, Banbury (End of Terrace)", "postcode": "OX15 4BN",
     "type": "Terraced", "beds": 3, "tenure": "", "asking": 520000, "street": "Arbor Park",
     "url": "https://www.rightmove.co.uk/properties/90808311",
     "why_selected": "Same close as #34 but smaller/cheaper — tests within-estate price differentiation.",
     "expected_challenge": "Same street as #34 — must NOT simply average the two together; genuinely different size/price point."},
    {"n": 36, "label": "Wykham Lane, Banbury", "postcode": "OX16 9UN",
     "type": "Terraced", "beds": 4, "tenure": "", "asking": 540000, "street": "Wykham Lane",
     "url": "https://www.rightmove.co.uk/properties/89842665",
     "why_selected": "Town-edge estate development, Banbury — geographic diversity away from the existing Didcot/Witney/Oxford cluster.",
     "expected_challenge": "Newer estate; genuine same-street comparables may be limited if the development is recent."},
    {"n": 37, "label": "Pipers Close, Heswall, Wirral", "postcode": "CH60 7RE",
     "type": "Bungalow", "beds": 5, "tenure": "Freehold", "asking": 850000, "street": "Pipers Close",
     "url": "https://www.rightmove.co.uk/properties/89508468",
     "why_selected": "Agent's own listing explicitly flags 'extension potential' — direct test case for the extension-potential/planning module.",
     "expected_challenge": "Premium detached bungalow with agent-claimed extension potential; tests whether planning.py's scoring is directionally consistent with a real agent's own assessment. "
                            "NOTE: original run (n=37 in the 2026-07-15 baseline CSV/JSON) produced an untrustworthy 0.0s/£0 result — see "
                            "validation_baselines/property_37_reruns/README.md for the corrected isolated re-run (£199,700 V2, Medium confidence)."},

    # --- Second expansion batch (ROADMAP.md item 2, resumed 2026-07-17),
    # sourced live from Rightmove — targets the coverage gaps identified in
    # the first batch: confirmed leasehold, genuinely new UK regions.
    {"n": 38, "label": "The Vincent, Redland Hill, Bristol", "postcode": "BS6 6BJ",
     "type": "Flat", "beds": 3, "tenure": "Leasehold", "asking": 895000, "street": "Redland Hill",
     "url": "https://www.rightmove.co.uk/properties/90573426",
     "why_selected": "Genuinely new UK region (South West, first Bristol entry in the dataset) and a CONFIRMED-tenure retirement leasehold flat — closes the confirmed-leasehold coverage gap flagged after the first batch.",
     "expected_challenge": "Retirement/age-restricted leasehold development; premium South West market with no existing comparable-region coverage in this dataset."},
    {"n": 39, "label": "Clifton, Bristol", "postcode": "BS8 3HX",
     "type": "Flat", "beds": 3, "tenure": "", "asking": 950000, "street": "Clifton",
     "url": "https://www.rightmove.co.uk/properties/90211176",
     "why_selected": "Premium Bristol (Clifton) flat — new region, high price band, tenure unconfirmed at capture (realistic data-gap case).",
     "expected_challenge": "Premium South West urban flat; tenure not stated on listing."},
    {"n": 40, "label": "29 Victoria, Hudson Quarter, York", "postcode": "YO1 6AB",
     "type": "Flat", "beds": 2, "tenure": "", "asking": 500000, "street": "Hudson Quarter",
     "url": "https://www.rightmove.co.uk/properties/159972281",
     "why_selected": "Genuinely new UK region (Yorkshire, first York entry) — new-build city-centre development, multiple concurrent listings on the same development (see #41, #43).",
     "expected_challenge": "New-build-adjacent development; Yorkshire region with no existing comparable-region coverage."},
    {"n": 41, "label": "15 Kings, Hudson Quarter, York", "postcode": "YO1 6AE",
     "type": "Flat", "beds": 2, "tenure": "", "asking": 495000, "street": "Hudson Quarter",
     "url": "https://www.rightmove.co.uk/properties/134214602",
     "why_selected": "Same development as #40 but a different block (Kings, not Victoria) — tests within-development block-level differentiation.",
     "expected_challenge": "Same development as #40 — must not simply average the two blocks together."},
    {"n": 42, "label": "The Residence, Bishopthorpe Road, York", "postcode": "YO23 1DQ",
     "type": "Flat", "beds": 2, "tenure": "", "asking": 400000, "street": "Bishopthorpe Road",
     "url": "https://www.rightmove.co.uk/properties/90313569",
     "why_selected": "Geographically distinct from the Hudson Quarter cluster (#40/#41/#43) within the same city — tests whether the engine correctly keeps genuinely separate York developments apart.",
     "expected_challenge": "Same city, different development — a within-region differentiation test rather than a cross-region one."},
    {"n": 43, "label": "18 Victoria, Hudson Quarter, York", "postcode": "YO1 6HP",
     "type": "Flat", "beds": 2, "tenure": "", "asking": 375000, "street": "Hudson Quarter",
     "url": "https://www.rightmove.co.uk/properties/89434272",
     "why_selected": "Third Hudson Quarter listing (Victoria block again, different unit/price than #40) — deepens the same-development comparable density for a York new-build case.",
     "expected_challenge": "Same development/block as #40 at a different price point — within-block price differentiation test."},
    {"n": 44, "label": "Ethelbert Road, Canterbury", "postcode": "CT1 3ND",
     "type": "Detached House", "beds": 6, "tenure": "", "asking": 1375000, "street": "Ethelbert Road",
     "url": "https://www.rightmove.co.uk/properties/173317916",
     "why_selected": "Genuinely new UK region (South East/Kent, first Canterbury entry) — premium detached property, large bedroom count.",
     "expected_challenge": "Premium South East market with no existing comparable-region coverage in this dataset; large 6-bed detached, sparse comparables plausible."},

    # --- Third expansion batch (ROADMAP.md item 2, resumed again 2026-07),
    # sourced live from Rightmove — deepens the Bristol/South West cluster
    # (previously only 2 properties, #38/#39) rather than scattering across
    # more single-property regions, per the explicit instruction to use one
    # meaningful regional cluster. Prioritises bungalows (was 2/44).
    {"n": 45, "label": "Bridgeleap Road, Downend, Bristol", "postcode": "BS16 6TE",
     "type": "Bungalow", "beds": 4, "tenure": "", "asking": 875000, "street": "Bridgeleap Road",
     "url": "https://www.rightmove.co.uk/properties/89806158",
     "why_selected": "Bristol cluster densification + bungalow coverage (was thin at 2/44).",
     "expected_challenge": "Detached bungalow — bungalow-to-Detached Land Registry code mapping test case, in a new region (South West)."},
    {"n": 46, "label": "Wells Road, Bristol", "postcode": "BS14 9HT",
     "type": "Semi-Detached Bungalow", "beds": 5, "tenure": "", "asking": 700000, "street": "Wells Road",
     "url": "https://www.rightmove.co.uk/properties/88223910",
     "why_selected": "Semi-Detached bungalow — a rarer sub-type than the usual detached bungalow, tests type-code mapping for a less common combination.",
     "expected_challenge": "Semi-Detached bungalow; unusual bedroom count (5) for the type."},
    {"n": 47, "label": "Russell Grove, Bristol", "postcode": "BS6 7UE",
     "type": "Bungalow", "beds": 3, "tenure": "", "asking": 650000, "street": "Russell Grove",
     "url": "https://www.rightmove.co.uk/properties/90455340",
     "why_selected": "Bristol cluster densification, bungalow coverage, inner-urban (BS6) rather than suburban location.",
     "expected_challenge": "Urban bungalow — less common than suburban/rural bungalows, may have sparser same-type comparables nearby."},
    {"n": 48, "label": "Penn Drive, Frenchay, Bristol", "postcode": "BS16 1NN",
     "type": "Detached Bungalow", "beds": 3, "tenure": "", "asking": 630000, "street": "Penn Drive",
     "url": "https://www.rightmove.co.uk/properties/166258400",
     "why_selected": "Bristol cluster densification, bungalow coverage — same road (Penn Drive) as a higher-priced bungalow listing found but not added, for potential future same-street comparable density.",
     "expected_challenge": "Standard detached bungalow control case within the cluster."},
    {"n": 49, "label": "Queensholm Close, Downend, Bristol", "postcode": "BS16 6LD",
     "type": "Detached Bungalow", "beds": 5, "tenure": "", "asking": 600000, "street": "Queensholm Close",
     "url": "https://www.rightmove.co.uk/properties/88084755",
     "why_selected": "Bristol cluster densification, bungalow coverage, same Downend area as #45/#50 — tests estate/development-level comparable density within the cluster.",
     "expected_challenge": "5-bed bungalow — larger than typical, tests whether size drives an atypical valuation."},
    {"n": 50, "label": "Sandringham Avenue, Downend, Bristol", "postcode": "BS16 6NL",
     "type": "Detached Bungalow", "beds": 3, "tenure": "", "asking": 550000, "street": "Sandringham Avenue",
     "url": "https://www.rightmove.co.uk/properties/91186215",
     "why_selected": "Same Downend area as #45/#49 — third property in this micro-cluster, strong test of same-development/estate evidence density.",
     "expected_challenge": "Standard detached bungalow control case; part of the Downend micro-cluster with #45 and #49."},
    {"n": 51, "label": "Old Gloucester Road, Hambrook, Bristol", "postcode": "BS16 1QH",
     "type": "Semi-Detached Bungalow", "beds": 3, "tenure": "", "asking": 500000, "street": "Old Gloucester Road",
     "url": "https://www.rightmove.co.uk/properties/174093176",
     "why_selected": "Village-edge (Hambrook) location within the wider Bristol cluster, semi-detached bungalow sub-type.",
     "expected_challenge": "Village-edge location; semi-detached bungalow type-code mapping test."},
    {"n": 52, "label": "Clifton Mews, Bristol", "postcode": "BS8 3HX",
     "type": "Terraced", "beds": 4, "tenure": "", "asking": 1575000, "street": "Clifton",
     "url": "https://www.rightmove.co.uk/properties/89461521",
     "why_selected": "Same postcode as existing property #39 (Clifton flat) but a different property type (Mews terraced house) — tests type differentiation at a single postcode, and extends premium-market coverage within the cluster.",
     "expected_challenge": "Premium Clifton mews house; same postcode as an existing flat entry (#39) — must not be conflated with it despite sharing a postcode."},

    # --- Fourth expansion batch (ROADMAP.md item 2, resumed 2026-07-26),
    # sourced live from Rightmove — new regional cluster (West Midlands,
    # first Birmingham entries), targeting confirmed leasehold flats
    # (still thin) and unusual bedroom-count edge cases.
    {"n": 53, "label": "Norfolk Road, Edgbaston, Birmingham", "postcode": "B15 3QD",
     "type": "Flat", "beds": 2, "tenure": "", "asking": 900000, "street": "Norfolk Road",
     "url": "https://www.rightmove.co.uk/properties/173828363",
     "why_selected": "Genuinely new UK region (West Midlands, first Birmingham entry) — premium Edgbaston flat.",
     "expected_challenge": "New region with no existing comparable-region coverage; tenure unconfirmed on listing."},
    {"n": 54, "label": "Penthouse, St Pauls Square, Birmingham", "postcode": "B3 1QZ",
     "type": "Flat", "beds": 2, "tenure": "Leasehold", "asking": 725000, "street": "St Pauls Square",
     "url": "https://www.rightmove.co.uk/properties/90246105",
     "why_selected": "CONFIRMED leasehold penthouse (verified on listing page) — closes part of the confirmed-leasehold coverage gap. City-centre Jewellery Quarter conversion.",
     "expected_challenge": "Confirmed leasehold flat; premium city-centre conversion, comparables may be limited to similar conversions."},
    {"n": 55, "label": "Harborne Road, Edgbaston, Birmingham", "postcode": "B15 3JJ",
     "type": "Flat", "beds": 3, "tenure": "", "asking": 700000, "street": "Harborne Road",
     "url": "https://www.rightmove.co.uk/properties/88583226",
     "why_selected": "Birmingham cluster densification, Edgbaston flat.",
     "expected_challenge": "Tenure unconfirmed; premium Edgbaston apartment market."},
    {"n": 56, "label": "Queensway House, Livery Street, Birmingham", "postcode": "B3 1HA",
     "type": "Flat", "beds": 3, "tenure": "Share of Freehold", "asking": 600000, "street": "Livery Street",
     "url": "https://www.rightmove.co.uk/properties/89729943",
     "why_selected": "CONFIRMED 'Share of Freehold' tenure (verified on listing page) — a distinct tenure type not previously represented anywhere in this dataset (neither pure Freehold nor Leasehold).",
     "expected_challenge": "Unusual/unrepresented tenure string ('Share of Freehold') — tests how the engine's tenure-matching logic (which expects Freehold/Leasehold) handles a real third category."},
    {"n": 57, "label": "High Brow, Harborne, Birmingham", "postcode": "B17 9EN",
     "type": "Terraced", "beds": 4, "tenure": "", "asking": 775000, "street": "High Brow",
     "url": "https://www.rightmove.co.uk/properties/171477611",
     "why_selected": "Birmingham cluster densification, Harborne suburb (a distinct sub-area within the cluster).",
     "expected_challenge": "Standard control case within the new regional cluster."},
    {"n": 58, "label": "Lonsdale Road, Harborne, Birmingham", "postcode": "B17 9QX",
     "type": "Terraced", "beds": 4, "tenure": "", "asking": 700000, "street": "Lonsdale Road",
     "url": "https://www.rightmove.co.uk/properties/172946039",
     "why_selected": "Birmingham cluster densification, Harborne.",
     "expected_challenge": "Standard control case within the new regional cluster."},
    {"n": 59, "label": "Bull Street, Harborne, Birmingham", "postcode": "B17 0HH",
     "type": "Terraced", "beds": 3, "tenure": "", "asking": 675000, "street": "Bull Street",
     "url": "https://www.rightmove.co.uk/properties/90642327",
     "why_selected": "Birmingham cluster densification, Harborne — good same-suburb comparable density with #57/#58.",
     "expected_challenge": "Estate/suburb-level evidence density test alongside #57 and #58."},
    {"n": 60, "label": "Ravenhurst Road, Harborne, Birmingham", "postcode": "B17 9TB",
     "type": "Terraced", "beds": 4, "tenure": "", "asking": 675000, "street": "Ravenhurst Road",
     "url": "https://www.rightmove.co.uk/properties/88035654",
     "why_selected": "Listed as 'Town House' on Rightmove but recorded here as Terraced (nearest Land Registry-compatible category) — tests property-type normalisation for a non-standard listing label.",
     "expected_challenge": "Rightmove 'Town House' label; property-type normalisation edge case."},
    {"n": 61, "label": "Heeley Road, Selly Oak, Birmingham", "postcode": "B29 6EZ",
     "type": "Terraced", "beds": 7, "tenure": "", "asking": 600000, "street": "Heeley Road",
     "url": "https://www.rightmove.co.uk/properties/132826907",
     "why_selected": "Unusually high bedroom count (7) for a terraced house — likely a large student-let/HMO-style conversion near a university area (Selly Oak).",
     "expected_challenge": "Unusual layout — large converted terrace, atypical £/bedroom versus standard terraced comparables."},
    {"n": 62, "label": "Carless Avenue, Harborne, Birmingham", "postcode": "B17 9BW",
     "type": "Semi-Detached", "beds": 5, "tenure": "", "asking": 975000, "street": "Carless Avenue",
     "url": "https://www.rightmove.co.uk/properties/89030040",
     "why_selected": "Premium Harborne semi-detached, Birmingham cluster densification.",
     "expected_challenge": "Premium end of the Birmingham cluster's price range."},
    {"n": 63, "label": "Lea End Lane, Hopwood, Alvechurch", "postcode": "B48 7AY",
     "type": "Semi-Detached", "beds": 3, "tenure": "", "asking": 950000, "street": "Lea End Lane",
     "url": "https://www.rightmove.co.uk/properties/91041447",
     "why_selected": "Village-edge location (Hopwood/Alvechurch, outside central Birmingham) within the wider West Midlands cluster — geographic diversity within the region.",
     "expected_challenge": "Village-edge/rural-adjacent location; sparse comparables plausible given the semi-rural setting despite the high asking price."},
    {"n": 64, "label": "Rotton Park Road, Edgbaston, Birmingham", "postcode": "B16 9JL",
     "type": "Semi-Detached", "beds": 8, "tenure": "", "asking": 945000, "street": "Rotton Park Road",
     "url": "https://www.rightmove.co.uk/properties/174295046",
     "why_selected": "Unusually high bedroom count (8) for a semi-detached house — likely a large converted/HMO-style property.",
     "expected_challenge": "Unusual layout — 8-bed semi is atypical, likely a converted or multi-unit property; tests engine behaviour on an outlier bedroom count."},
]

GROUP_KEYS = ["Direct Evidence", "Development Evidence", "Local Market Evidence", "Area Market Evidence"]


# --- Run-quality detection -------------------------------------------------
#
# Derived from direct observation of two confirmed environmental-corruption
# incidents (Pipers Close, first expansion batch; properties #47-52, third
# expansion batch — see validation_baselines/property_37_reruns/ and
# validation_baselines/second_expansion_batch_reruns/). In EVERY confirmed
# case, elapsed_seconds was exactly 0.0 — never any other value — with
# v1_value/v2_value both 0 and no exception raised. Per-group
# evidence_status fields were populated identically to a genuine "no
# evidence found" result (e.g. "EMPTY", comp_count=0), so they do NOT
# distinguish corruption from a genuine empty result; only elapsed time
# does, and specifically the value 0.0, not a range around it.
#
# Every confirmed GENUINE zero-evidence result observed so far took at
# least several seconds (minimum observed: 4.8s, property #26 "Valley
# Park" in the 44-property run).
#
# A live run (2026-07-25) exposed a genuine gap in an earlier version of
# this classifier: property #43 (18 Victoria, Hudson Quarter, York) showed
# elapsed=0.5s with v1=v2=0 and was flagged using a "< 1.0s" buffer band
# that was never itself observed in a confirmed corruption case — that
# buffer was an engineering safety margin, not evidence. On rerun, #43
# reproduced the identical result (0.5s, £0, twice) — reproducibility is
# evidence AGAINST random environmental corruption, which would not be
# expected to recur identically. The classifier below no longer conflates
# "matches the confirmed signature exactly" with "falls in an unverified
# buffer near it" — those are now two distinct, honestly-labelled tiers.
CONFIRMED_CORRUPTION_ELAPSED_SECONDS = 0.0  # exact value seen in every confirmed incident
GENUINE_FAILURE_MIN_OBSERVED_SECONDS = 4.8  # fastest confirmed-genuine empty result seen so far


def _classify_run_quality(row: dict) -> str:
    """Classify a single run_one() result as one of:

      "SUCCESS"
          A real, usable valuation was produced (v2_value > 0).

      "CONFIRMED_ENVIRONMENTAL_INVALID"
          Matches the exact signature observed in both confirmed
          corruption incidents: elapsed_seconds == 0.0, v1_value ==
          v2_value == 0, no exception. Not a range — the literal value
          every confirmed incident showed.

      "SUSPECT_ENVIRONMENTAL"
          v2_value is empty and elapsed_seconds is neither the confirmed
          corruption value (0.0) nor within the confirmed-genuine range
          (>= GENUINE_FAILURE_MIN_OBSERVED_SECONDS) — an unusual pattern
          worth a single rerun, but NOT yet proven to be corruption. This
          is the honest "we don't have evidence either way yet" bucket.

      "GENUINE_FAILURE"
          v2_value is empty, but either an exception was caught, or the
          elapsed time is consistent with every confirmed-genuine empty
          result observed so far (>= GENUINE_FAILURE_MIN_OBSERVED_SECONDS).

    Does not change or reinterpret any valuation field — read-only
    classification of the harness's own output. Callers should rerun once
    on CONFIRMED_ENVIRONMENTAL_INVALID or SUSPECT_ENVIRONMENTAL; if the
    rerun reproduces the same non-success tier, the property should be
    recorded as GENUINE_FAILURE (repeatable after rerun), not left
    ambiguously "still invalid" — reproducibility argues for a real,
    reproducible outcome rather than random corruption.
    """
    elapsed = row.get("elapsed_seconds")
    v1 = row.get("v1_value") or 0
    v2 = row.get("v2_value") or 0
    has_error = bool(row.get("error"))

    # V2 is the primary engine's output — a usable result means v2 > 0,
    # matching credibility_judgement()'s own existing v2-keyed logic.
    v2_empty = v2 in (0, None)

    if not v2_empty and not has_error:
        return "SUCCESS"

    if has_error:
        return "GENUINE_FAILURE"

    both_empty = v2_empty and (v1 in (0, None))
    if both_empty and elapsed == CONFIRMED_CORRUPTION_ELAPSED_SECONDS:
        return "CONFIRMED_ENVIRONMENTAL_INVALID"

    if elapsed is not None and elapsed >= GENUINE_FAILURE_MIN_OBSERVED_SECONDS:
        return "GENUINE_FAILURE"

    # v2 empty, no error, elapsed neither the confirmed-corrupt value nor
    # within the confirmed-genuine range — genuinely ambiguous.
    return "SUSPECT_ENVIRONMENTAL"


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
        "url": p.get("url", ""),
        "why_selected": p.get("why_selected", ""),
        "expected_challenge": p.get("expected_challenge", ""),
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

    rows = []                # accepted rows — what downstream consumers read
    original_results_for_reruns = []  # preserved originals, never overwritten
    rerun_manifest = []
    successful_first_pass_n = []
    recovered_after_rerun_n = []
    true_failures_n = []

    RERUN_TRIGGER_TIERS = ("CONFIRMED_ENVIRONMENTAL_INVALID", "SUSPECT_ENVIRONMENTAL")

    for p in PROPERTIES:
        print(f"[{p['n']}/{len(PROPERTIES)}] {p['label']} ({p['postcode']})...", flush=True)
        row = run_one(p)
        quality = _classify_run_quality(row)

        if quality not in RERUN_TRIGGER_TIERS:
            rows.append(row)
            if quality == "SUCCESS":
                successful_first_pass_n.append(p["n"])
            else:
                true_failures_n.append(p["n"])
            if row["error"]:
                print(f"  *** ERROR: {row['error']} *** [{row['elapsed_seconds']}s]", flush=True)
            else:
                print(f"  V1={format_currency(row['v1_value'])} V2={format_currency(row['v2_value'])} "
                      f"({row['v2_confidence_label']}) {row['credibility_judgement']} "
                      f"[{row['elapsed_seconds']}s]", flush=True)
            continue

        # --- CONFIRMED_ENVIRONMENTAL_INVALID or SUSPECT_ENVIRONMENTAL: rerun once ---
        if quality == "CONFIRMED_ENVIRONMENTAL_INVALID":
            reason = (
                f"elapsed_seconds={row['elapsed_seconds']} matches the exact confirmed "
                f"corruption signature ({CONFIRMED_CORRUPTION_ELAPSED_SECONDS}s, v1=v2=0, no error)"
            )
        else:
            reason = (
                f"elapsed_seconds={row['elapsed_seconds']} with v1_value={row['v1_value']}, "
                f"v2_value={row['v2_value']}, error=None — unusual pattern (neither the confirmed "
                f"corrupt value {CONFIRMED_CORRUPTION_ELAPSED_SECONDS}s nor the confirmed-genuine "
                f"range >= {GENUINE_FAILURE_MIN_OBSERVED_SECONDS}s), not yet proven corruption"
            )
        print(f"  *** FLAGGED {quality}: {reason} — rerunning once ***", flush=True)
        original_results_for_reruns.append(row)
        rerun_row = run_one(p)
        rerun_quality = _classify_run_quality(rerun_row)

        outputs_changed = (
            row.get("v1_value") != rerun_row.get("v1_value")
            or row.get("v2_value") != rerun_row.get("v2_value")
            or row.get("v2_confidence_label") != rerun_row.get("v2_confidence_label")
        )

        if rerun_quality == "SUCCESS":
            accepted = "rerun (SUCCESS)"
            rows.append(rerun_row)
            recovered_after_rerun_n.append(p["n"])
            print(f"  RECOVERED on rerun: V1={format_currency(rerun_row['v1_value'])} "
                  f"V2={format_currency(rerun_row['v2_value'])} "
                  f"({rerun_row['v2_confidence_label']}) [{rerun_row['elapsed_seconds']}s]", flush=True)
        elif rerun_quality in RERUN_TRIGGER_TIERS:
            # Reproduced the same ambiguous/corrupt pattern on rerun.
            # Reproducibility is evidence AGAINST random environmental
            # corruption (which would not be expected to recur identically)
            # — per the evidence-first principle, this is now classified
            # GENUINE_FAILURE ("repeatable after rerun"), not left as an
            # unresolved corruption suspicion.
            accepted = f"rerun (reproduced {rerun_quality} — treated as GENUINE_FAILURE per repeatability)"
            rows.append(rerun_row)
            true_failures_n.append(p["n"])
            print(f"  *** REPRODUCED on rerun [{rerun_row['elapsed_seconds']}s] — "
                  f"repeatable, classified GENUINE_FAILURE, needs manual investigation ***", flush=True)
        else:
            # rerun_quality == "GENUINE_FAILURE" directly (e.g. errored, or
            # took confirmed-genuine-length time and still found nothing).
            accepted = "rerun (GENUINE_FAILURE confirmed)"
            rows.append(rerun_row)
            true_failures_n.append(p["n"])
            print(f"  *** CONFIRMED GENUINE FAILURE on rerun [{rerun_row['elapsed_seconds']}s] ***", flush=True)

        rerun_manifest.append({
            "n": p["n"], "property": p["label"],
            "first_pass_tier": quality,
            "rerun_tier": rerun_quality,
            "reason_triggered": reason,
            "timestamp": datetime.now().isoformat(),
            "original_runtime_seconds": row["elapsed_seconds"],
            "rerun_runtime_seconds": rerun_row["elapsed_seconds"],
            "accepted_result": accepted,
            "outputs_changed": outputs_changed,
        })

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

    confidence_totals = {}
    for row in rows:
        cl = row.get("v2_confidence_label")
        if cl:
            confidence_totals[cl] = confidence_totals.get(cl, 0) + 1

    elapsed_values = [r["elapsed_seconds"] for r in rows if r.get("elapsed_seconds") is not None]
    avg_runtime = round(sum(elapsed_values) / len(elapsed_values), 1) if elapsed_values else 0

    # --- Run-quality statistics ---
    total_properties = len(PROPERTIES)
    n_first_pass_success = len(successful_first_pass_n)
    n_flagged_invalid = len(rerun_manifest)
    n_recovered = len(recovered_after_rerun_n)
    n_true_failures = len(true_failures_n)
    run_quality_stats = {
        "first_pass_success_count": n_first_pass_success,
        "first_pass_success_rate": round(n_first_pass_success / total_properties, 4) if total_properties else 0,
        "flagged_for_rerun_count": n_flagged_invalid,  # CONFIRMED_ENVIRONMENTAL_INVALID + SUSPECT_ENVIRONMENTAL
        "rerun_recovered_count": n_recovered,
        "rerun_recovery_rate": round(n_recovered / n_flagged_invalid, 4) if n_flagged_invalid else None,
        "true_failure_count": n_true_failures,
        "true_failure_rate": round(n_true_failures / total_properties, 4) if total_properties else 0,
    }

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
        "confidence_label_totals": confidence_totals,
        "average_runtime_seconds_per_property": avg_runtime,
        "run_quality_stats": run_quality_stats,
        "successful_first_pass_n": successful_first_pass_n,
        "recovered_after_rerun_n": recovered_after_rerun_n,
        "true_failures_n": true_failures_n,
        "rerun_manifest": rerun_manifest,
        "note_on_run_quality_detection": (
            "Every result is classified SUCCESS / CONFIRMED_ENVIRONMENTAL_INVALID / "
            "SUSPECT_ENVIRONMENTAL / GENUINE_FAILURE (see _classify_run_quality() "
            f"docstring). CONFIRMED_ENVIRONMENTAL_INVALID means elapsed_seconds == "
            f"{CONFIRMED_CORRUPTION_ELAPSED_SECONDS}s exactly with v1=v2=0 and no "
            "exception — the literal signature observed in every confirmed corruption "
            f"incident. SUSPECT_ENVIRONMENTAL means v2 is empty with elapsed neither "
            f"that exact value nor within the confirmed-genuine range (>= "
            f"{GENUINE_FAILURE_MIN_OBSERVED_SECONDS}s) — an unusual pattern worth a "
            "rerun but not yet proven corruption. Both tiers trigger one automatic "
            "rerun; if the rerun reproduces the same tier, the property is recorded "
            "as GENUINE_FAILURE (repeatable after rerun), since reproducibility "
            "argues against random environmental corruption. The original flagged "
            "row is never overwritten — see 'original_results_for_reruns' in this "
            "JSON's top level for every preserved original. 'results' below contains "
            "only the accepted row for every property — see 'rerun_manifest' for the "
            "full per-property audit trail (first_pass_tier, rerun_tier, reason, "
            "timestamps, runtimes, accepted result, whether outputs changed)."
        ),
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
    # "results" holds only accepted rows (one per property). Every original,
    # flagged (CONFIRMED_ENVIRONMENTAL_INVALID/SUSPECT_ENVIRONMENTAL) row is
    # preserved separately in "original_results_for_reruns" — never
    # overwritten, never discarded.
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": meta,
            "results": rows,
            "original_results_for_reruns": original_results_for_reruns,
        }, f, indent=2, default=str)

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
    print(f"Duration:      {meta['run_duration_seconds']}s  (avg {avg_runtime}s/property)", flush=True)
    print(f"Properties:    {n_ok} succeeded, {n_errors} failed (of {len(PROPERTIES)})", flush=True)
    print(f"Evidence status totals: {meta['evidence_status_totals']}", flush=True)
    print(f"Confidence totals:      {confidence_totals}", flush=True)
    print(f"Credibility totals:     {credibility_totals}", flush=True)
    print(flush=True)
    print("-" * 80, flush=True)
    print("RUN QUALITY", flush=True)
    print("-" * 80, flush=True)
    print(f"Successful first-pass results ({n_first_pass_success}/{total_properties}): {successful_first_pass_n}", flush=True)
    print(f"Recovered after automatic rerun ({n_recovered}/{n_flagged_invalid} flagged): {recovered_after_rerun_n}", flush=True)
    print(f"True failures ({n_true_failures}/{total_properties}): {true_failures_n}", flush=True)
    print(flush=True)
    print(f"First-pass success rate: {run_quality_stats['first_pass_success_rate']:.1%}", flush=True)
    if n_flagged_invalid:
        print(f"Rerun recovery rate:     {run_quality_stats['rerun_recovery_rate']:.1%} "
              f"({n_recovered} of {n_flagged_invalid} flagged runs recovered)", flush=True)
    else:
        print("Rerun recovery rate:     n/a (no runs flagged CONFIRMED_ENVIRONMENTAL_INVALID/SUSPECT_ENVIRONMENTAL)", flush=True)
    print(f"True failure rate:       {run_quality_stats['true_failure_rate']:.1%}", flush=True)
    if rerun_manifest:
        print(flush=True)
        print("Rerun manifest:", flush=True)
        for entry in rerun_manifest:
            print(f"  [{entry['n']}] {entry['property']}: {entry['first_pass_tier']} "
                  f"({entry['original_runtime_seconds']}s) -> {entry['rerun_tier']} "
                  f"({entry['rerun_runtime_seconds']}s), accepted={entry['accepted_result']}, "
                  f"outputs_changed={entry['outputs_changed']}", flush=True)
    print(flush=True)
    print(f"CSV:  {csv_path}", flush=True)
    print(f"JSON: {json_path}", flush=True)


if __name__ == "__main__":
    main()
