# Stage 3 — Bungalow Forensic Audit: Property #37, Pipers Close, Heswall (CH60 7RE)

**Status: read-only investigation. No valuation logic was changed.**

Subject: Bungalow, 5 bed, asking £850,000. Corrected V1 = £300,000. Corrected V2 = £199,700 (Medium confidence, 47). 216 raw / 49 scored comparables.

## Type Normalisation

- Rightmove type string: `"Bungalow"`
- `normalise_property_type()` -> Land Registry code: **`"D"` (Detached)**
- This is not a bug in the mapping function itself — Land Registry's Price Paid Data has no separate "Bungalow" category; single-storey detached properties are legitimately recorded under the same "D" code as multi-storey detached houses. The mapping is doing the only thing it can do with the data available. The consequence, not the mapping choice itself, is the problem: a bungalow and a two-storey detached house of similar footprint are not equivalent value propositions (a bungalow typically needs more land for the same floor area, commands a different buyer pool, and is valued differently), and nothing downstream distinguishes them.

## Subject Floor Area

- EPC lookup result: **`sqm=0.0`, rating='', detail="no confident match"**
- No manual override was supplied (`overrides_applied: []` — empty)
- **The subject has zero floor area information from any source.** Every size-based sanity check in the pipeline (`_size_similarity_weight`) is inert for this property, because it only ever engages `if subject_sqm > 0`.

## Comparable Evidence Overview

- total_fetched=216, total_scored=49, total_excluded=80
- Tier A=0, B=35, C=14, D=87
- EPC matched 43/49 scored comparables (subject itself excluded from this — see above)

## Evidence Group Breakdown

| Group | Comps | Status | Confidence | Valuation | Weight | Type mix |
|---|---|---|---|---|---|---|
| Direct | 0 | EMPTY | None (0) | £0 | 0.000 | — |
| **Development** | **2** | WEAK ("only 0 exact/compatible; wide spread CV 55%") | Medium (46) | **£123,100** | **0.627** | both blank type |
| Local Market | 85 | STRONG (17 exact, 68 compatible) | Medium (50) | £328,500 | 0.373 | D=17, S=62, blank=6 |
| Area Market | 0 | EMPTY | None (0) | £0 | 0.000 | — |

**The Development Evidence group is the dominant driver (62.7% of the final weight) and consists of only 2 comparables, both of unrecorded type, with a 55% price spread.** Its representative comparable is:

> 74A, PENSBY ROAD, WIRRAL — type unrecorded, adjusted price **£67,897**, floor area unrecorded

A £67,897 transaction being treated as representative evidence for an £850,000 5-bed detached bungalow is not a plausible like-for-like comparable. A price this low, combined with an unrecorded property type and unrecorded floor area, is far more consistent with a garage, parking space, ground-rent/leasehold-interest transaction, or another non-standard Land Registry entry than a genuine residential sale of a comparable dwelling. This single comparable (or its pair) is doing outsized damage to the final figure precisely because the group has so few members that one implausible entry can dominate the weighted mean, and because — unlike the type-fallback mechanism in Direct/Development Evidence — **there is no price-plausibility guard protecting a thin, unknown-type Development group from an extreme low-price outlier the way `_admit_fallback_comps()`'s ±50%-of-median band protects type-fallback admissions.** The two comps here were never subject to that guard because they entered as "unknown type" (folded into the genuine bucket), not as type-fallback comps.

## Local Market Group

STRONG status, 85 comps, but the same broad-type-gate pattern documented in Stage 2 is present here too: only 17 of 85 (20%) are exact Detached matches; 62 are Semi-Detached admitted as "compatible" under the broad V1 gate, with no `property_type_weight()` discount. Representative comparable is a Semi-Detached property at £275,000 — again, not a strong like-for-like peer for a premium detached/bungalow subject. This group's £328,500 valuation is itself likely understated for the same systemic reason documented in Stage 2, though it is not the dominant driver of this property's headline result.

## Was the Asking Price Itself Checked for Plausibility?

Per instruction, the asking price was not assumed correct by default. Two observations: (1) the property is a genuinely premium bungalow in Heswall (CH60), an area that produced other high-value listings elsewhere in this dataset (e.g. property #8, Dee Park Road, Heswall) — an £850,000 asking price is not inherently implausible for this specific location and bedroom count; (2) the listing explicitly advertises "extension potential" (see ROADMAP.md item 2's original property selection notes) — none of that context reaches the valuation engine, which has no mechanism to account for development upside (correctly, per ROADMAP.md item 2's earlier finding that extension potential is deliberately excluded from fair value). Neither observation proves the asking price is fair, but neither supports dismissing it as unrealistic either — there is no evidence-based reason to prefer "the asking price is wrong" over "the valuation is wrong" here; both are plausible, and the specific defects found (outlier-dominated thin evidence group, zero floor area) are sufficient on their own to explain a large, unreliable gap regardless of which side is closer to true value.

## Dominant Cause

**(7) Another cause: an extreme low-price outlier admitted into a thin (2-comparable), unknown-type Development Evidence group, which then dominates the final blend (62.7% weight) purely because Direct Evidence is EMPTY and the reconciliation weighting rules favour Development when Direct is absent.**

Compounding factors, ranked by contribution:
- **(2) Missing floor area** (subject sqm=0, no EPC match, no manual override) — removes the one sanity check that could have discounted comparables like the £67,897 outlier or the undersized Local Market matches.
- **(1) Bungalow-to-Detached mapping is too broad**, but this is a secondary, not primary, cause here — Local Market (where the type mapping matters most) is not the dominant group for this property; even a perfect bungalow-specific type policy would not by itself fix the Development Evidence outlier problem, which is the larger driver of the implausible result.

Ruled out: (3) development/plot value ignored — correctly and deliberately excluded from fair value per existing design, not a defect. (4) incorrect listing extraction — postcode, price, type, and bedroom count all traced correctly to source. (5) unsuitable geographic comparables — Development Evidence's affinity gate behaved as designed; the problem is what happened *after* two comps passed it, not the gate itself. (6) asking price unrealistic — no evidence either way, see above.

## Relationship to Stage 4 Option B

The evidence here does **not** straightforwardly support "introduce a distinct bungalow compatibility policy" (Option B) as the primary fix for this specific property, because the acute defect — a 2-comp Development group dominated by an implausible outlier — is a general thin-evidence/outlier-admission gap, not a bungalow-type-classification gap. A bungalow-specific policy might improve the Local Market group's quality (a secondary contributor here, and directly relevant to Stage 2's broader finding), but would not address the Development Evidence outlier problem, which is the larger driver of this specific property's result. See Stage 4 recommendation in the main report for how this is reflected in the final recommendation.
