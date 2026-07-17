# Forensic Report — Property #27, Ladygrove, Didcot (OX11 9BS)

**Status: read-only investigation. No valuation logic was changed as part of
this report.** Findings below are diagnostic only; any fix belongs to a
future implementation pass (see Recommendation at the end).

## Observed Anomaly

- Asking price: £450,000 (Semi-Detached, 4 bed)
- V2 fair value (balanced): **£1,415,700**
- Gap vs asking: **+214.6%**
- Direct Evidence: EMPTY (0 comps)
- Development Evidence: WEAK, weight 0.6667 (dominant, "Development Evidence (weak)")
- Local Market Evidence: WEAK, weight 0.3333, **380 comparables**
- Area Market Evidence: EMPTY (not implemented)
- Final confidence: Very Low (21)
- Final status: driven by `dominant_group = "Development Evidence (weak)"` — Direct absent, Development non-High/Medium confidence

## Local Market Evidence Group — Full Breakdown

| Metric | Value |
|---|---|
| comp_count | 380 |
| evidence_status | WEAK — "wide spread (CV 54%)" |
| evidence_quality | 72 |
| confidence | Medium (45) |
| median_value | £492,500 |
| weighted_mean (= group valuation) | £560,300 |
| valuation range | £351,400 – £732,900 |
| type_exact_count | 99 (Semi-Detached, matches subject) |
| type_compatible_count | 281 (Detached + Terraced, admitted under V1's broad `COMPATIBLE_TYPES` gate) |
| weight_in_final | 0.3333 |

### Price statistics (n=380 priced comparables)

- min: £50,807 | max: £1,642,482 | median: £492,513 | mean: £579,140
- IQR: Q1=£351,363, Q3=£732,920, IQR=£381,557
- **CV: 54.0%** (this is what triggered the WEAK evidence-status classification)

### Property type breakdown (Local Market group)

| Type code | Count |
|---|---|
| D (Detached) | 177 |
| S (Semi-Detached, exact match) | 99 |
| T (Terraced) | 81 |
| (blank/unknown) | 23 |

**177 of 380 comparables (46.6%) are Detached properties** — nearly half the
group — despite the subject being a Semi-Detached house.

### Top 10 highest-priced comparables in the group

| Address (truncated) | Type | Tier | Adj. price | Floor area | Date |
|---|---|---|---|---|---|
| SADDLERS ORCHARD, CHURCH CLOSE, DIDCOT | D | D | £1,642,482 | 0 sqm (missing) | 2023-01-18 |
| THE OLD MALT HOUSE, SOUTH STREET, DIDCOT | D | B | £1,589,045 | 0 sqm (missing) | 2024-11-22 |
| 6, GREAT MEAD, DIDCOT | D | C | £1,557,555 | 361 sqm | 2024-05-17 |
| PURPLE HEATHER, HIGH STREET, DIDCOT | D | B | £1,548,139 | 0 sqm (missing) | 2025-03-27 |
| MEADOW COTTAGE, ASTON STREET, DIDCOT | (blank) | C | £1,510,030 | 0 sqm (missing) | 2024-07-12 |
| ST ANDREWS LODGE, HIGH STREET, DIDCOT | D | B | £1,486,324 | 0 sqm (missing) | 2025-05-30 |
| ROSE BARN, SPRING LANE, DIDCOT | D | D | £1,484,063 | 0 sqm (missing) | 2023-05-02 |
| GRANARY BARN, THORPE STREET, DIDCOT | (blank) | D | £1,478,552 | 0 sqm (missing) | 2023-01-11 |
| LAINE, HIGH STREET, DIDCOT | D | B | £1,448,494 | 0 sqm (missing) | 2025-02-25 |
| LOWER CROSS FARM, THE MANEGE, BLEWBURY ROAD | D | D | £1,398,606 | 0 sqm (missing) | 2022-07-04 |

Every single one of the ten highest-priced comparables is Detached (or
unrecorded type), named as a barn/farmhouse/lodge/cottage conversion, on a
road name (Church Close, South Street, High Street, Spring Lane, Thorpe
Street, Blewbury Road) that reads as a surrounding South Oxfordshire village
centre, not the Ladygrove/Lady Grove residential estate the subject sits in.
**None of the top 10 have recorded floor area.**

### Bottom 10 lowest-priced comparables (for contrast)

The lowest-priced entries are Terraced properties on "DIBLEYS" and similar
estate roads, £50,807–£169,836, mostly with recorded floor area (45-89 sqm)
and Tier B/C/D — a plausible, tighter cluster more representative of typical
Ladygrove-area stock.

### Distance data

Not available in this diagnostic run (subject latitude/longitude were not
supplied — this matches how `validate_baseline.py`'s harness itself calls
`fetch_and_score_comparables()`, which also never passes coordinates). This
means distance was never a usable signal for this property in the actual
validation run either — Local Market Evidence's only geographic filter is
"same postcode sector," with no distance-based sanity check available
regardless.

## Root Cause Determination

**Primary cause: (3) Incompatible property types entering Local Market
Evidence at effectively undiscounted weight.**

`build_local_market_evidence_group()` (`valuation_engine_v2.py`) uses V1's
broad `_is_type_compatible()` gate, which for a Semi-Detached subject accepts
Detached and Terraced as "compatible" (`COMPATIBLE_TYPES["S"] = {"S", "D",
"T"}`). Unlike Direct Evidence and Development Evidence — which both apply
`property_type_weight()` to downgrade compatible-but-not-exact matches to
0.70x and incompatible fallbacks to 0.25x — **`_local_comp_weight()` applies
no type-compatibility discount at all.** A £1.6M detached barn conversion
and an exact-match £150k terraced house receive identical type-based
weighting; only tier and recency differ. The size-similarity weight
(`_size_similarity_weight`) that could have discounted these large
properties never engages either, because 9 of the top 10 highest-priced
comparables have **no recorded floor area** (`sqm=0.0`), so the
`if subject_sqm > 0 and c.floor_area_sqm > 0` guard never fires for them.

The combined effect: 177 Detached comparables (46.6% of the group), many of
them large rural properties with unverifiable size, enter at full
tier/recency weight alongside 99 genuine Semi-Detached matches, dragging both
the median (£492,500) and especially the weighted mean (£560,300 — used as
the group's `valuation`) well above what a Ladygrove-estate semi should be
worth. This is what the group's own WEAK evidence-status correctly flagged
(CV 54%) — but WEAK still carries non-trivial reconciliation weight (0.60
authority factor, not near-zero), so the contaminated valuation still fed
into the £1,415,700 final figure via the 0.3333 Local Market weight
(compounded by Development Evidence's own weak, dominant 0.6667 weight —
this Development group was not examined in this pass but is worth the same
scrutiny in a follow-up).

**Secondary contributing factor: (5) postcode search area too broad, in a
specific sense.** The OX11 9 postcode sector spans both the dense
Ladygrove/Lady Grove estate itself and outlying South Oxfordshire villages
(street names in the top-10 — Church Close, South Street, High Street,
Spring Lane, Thorpe Street, Blewbury Road — read as village centres, not
estate roads). "Same postcode sector" is Local Market's only geographic
gate; for a sector this heterogeneous, sector-level matching alone is not a
tight enough geographic proxy to keep an urban/suburban estate semi's
comparables separate from a surrounding rural village's large detached
properties.

Ruled out: (1) wrong subject identity/postcode — the postcode OX11 9BS
correctly resolved and the sector-level query behaved as designed for that
gate. (2) same-name location collision — this was the deliberate test
hypothesis for adding this property (against existing property #20,
"Ladygrove, Didcot," OX11 7UG), but the two are in different postcode
sectors entirely (9BS vs 7UG) and there is no evidence in this diagnostic
that the two were conflated with each other. (7) floor-area error — floor
area is *missing*, not wrong, for the anomalous comparables; this is better
classified under (3)/(4) as a consequence of the type-weighting gap than an
independent floor-area bug.

## Recommendation (not implemented in this pass)

A future fix should apply `property_type_weight()` (already used correctly
by Direct and Development Evidence) to Local Market Evidence's weighting as
well, so a "compatible" Detached/Terraced comparable is discounted the same
way it already is everywhere else in the engine. This is a plausible,
narrowly-scoped candidate for Roadmap item 11 (weight/profile/confidence
tuning) — flagged here for that future pass, not implemented now, per this
task's explicit read-only-forensics scope.
