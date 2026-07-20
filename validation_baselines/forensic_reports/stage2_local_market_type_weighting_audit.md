# Stage 2 — Local Market Property-Type Weighting Audit

**Status: read-only investigation. No valuation logic was changed.**

## Cross-Group Comparison

| | Direct Evidence | Estate (Development) Evidence | Local Market Evidence | Area Market Evidence |
|---|---|---|---|---|
| Exact match | Same Land Registry type code | Same type code | Same type code | Not implemented |
| Compatible match | Strict: S↔T only (`_V2_COMPATIBLE_PAIRS`) | Same strict S↔T only | Broad: `COMPATIBLE_TYPES` — a Semi subject admits both Detached *and* Terraced as "compatible" | — |
| Unknown-type treatment | Included, `property_type_weight()`=0.50, excluded from exact-count | Same | Included; no distinct unknown tier, folded into `type_compatible_count` | — |
| Incompatible fallback | Only admitted if <3 genuine comps, gated by `_admit_fallback_comps()`'s ±50%-of-median price-band guard | Same mechanism | **No fallback tier exists** — the broad gate is binary (admitted or excluded); nothing is ever classified "incompatible fallback" | — |
| `property_type_weight()` applied? | **Yes** (1.0 / 0.70 / 0.25 / 0.50) | **Yes** | **No — confirmed by direct code inspection. `_local_comp_weight()` multiplies only tier x recency (x size-similarity if floor area known). No type-based discount exists anywhere in the weighting.** | — |
| Affects evidence_status? | Yes, via `type_incompatible_fallback_count` feeding `_calculate_evidence_status`'s fallback-ratio check | Yes, same mechanism | Only indirectly, with a blind spot: `type_incompatible_fallback_count` is always 0 for Local Market (no fallback tier to populate), so the fallback-ratio safeguard trivially passes regardless of how loosely-compatible the mix actually is. Local Market's STRONG/WEAK classification is driven by price-spread CV and comp count, not by type composition — even though type composition is the actual contamination source. | — |
| Affects confidence? | Yes, direct type-match scoring | Yes | Yes, modestly — partial bonus only if `exact_type > n*0.5`; one component among several, capped at 75 total | — |
| Affects valuation weight (£)? | Yes, directly, via the weight multiplier in the weighted mean | Yes, same | **No direct effect on the £ figure.** Only an indirect, partial effect via the group's confidence label influencing `_WEIGHT_PROFILES` selection, and via the STRONG/WEAK/FALLBACK_ONLY authority multiplier scaling the *group's* contribution to the final blend — the contaminated £ figure inside the group is never itself discounted for type mismatch. | — |

**Confirmed**: Local Market admits exact, broadly-compatible, and (by extension) what would be strictly-incompatible types under one undifferentiated gate, with no `property_type_weight()` or equivalent discount applied anywhere in its weighting math.

## Case A — Ladygrove, Didcot, OX11 9BS

Subject: Semi-Detached, asking £450,000. V2 = £1,415,900. Direct Evidence EMPTY. Local Market: 380 comps, WEAK.

### Reproducibility

Ran twice, independently, from a warm cache. **Identical result both times** (comp_count=380, Local Market valuation=£560,800, V2 final=£1,415,900). Not a non-deterministic fluke.

### Counts and £ contribution by type (Local Market group)

| Type | n | Median | Mean | Sum |
|---|---|---|---|---|
| Detached (D) | 177 | £721,157 | £771,385 | £136,535,078 |
| Semi (S, exact) | 99 | £420,886 | £438,621 | £43,423,477 |
| Terraced (T) | 81 | £278,926 | £297,809 | £24,122,525 |
| (blank/unknown) | 23 | £642,691 | £695,304 | £15,991,983 |

### Counterfactual valuations (Local Market group's own weighted mean)

| Scenario | Weighted mean | vs. current |
|---|---|---|
| **A. Current** (all 380, tier x recency only) | £560,762 | — (engine reports £560,800) |
| **B. Exact type only** (n=99) | £430,638 | -23.2% |
| **C. `property_type_weight()` applied to all 380** (strict V2 classification: 99 exact / 81 compatible / 177 incompatible / 23 unknown) | £470,763 | -16.1% |
| **D. Exclude unknown-floor-area Detached** (removes 140 of 380) | £439,529 | -21.6% |

Applying the existing `property_type_weight()` mechanism (Option C) closes roughly 84% of the gap between the current contaminated figure (£560,800) and the exact-type-only figure (£430,638), without needing any new logic — it reuses a function that already exists and is already applied identically in Direct and Estate Evidence.

### Top 10 individual weighting contributions

All ten are Detached properties, each contributing only 1.0-1.4% of the total weighted sum individually — **this is not one or two extreme outliers distorting the average, it is a broad, structural over-representation of Detached properties** (177 of 380, 46.6% of the group) at full weight.

## Case B — Systemic Scan (all 37 properties)

Searched for properties where Local Market Evidence holds >=30% of final reconciliation weight AND more than 25% of its comparables are non-exact-type matches.

**9 of 37 properties (24%) flagged:**

| # | Property | LM comps | Non-exact % | Current LM valuation | Counterfactual (type-weighted) | Change |
|---|---|---|---|---|---|---|
| 2 | Chestnut Close, Witney | 103 | 62.1% | £434,900 | £394,767 | -9.2% |
| 5 | Vyner Road South, Prenton | 281 | 68.0% | £251,400 | £211,307 | -16.0% |
| 8 | Dee Park Road, Heswall | 56 | 42.9% | £503,700 | £548,169 | **+8.8%** |
| 9 | Acacia Grove, Bebington | 219 | 88.1% | £267,900 | £282,731 | **+5.5%** |
| 15 | Bostock Road, Abingdon | 358 | 60.3% | £466,100 | £507,248 | **+8.8%** |
| 18 | Bracken Close, Didcot | 445 | 67.0% | £400,200 | £442,642 | **+10.6%** |
| 27 | Ladygrove, Didcot | 380 | 73.9% | £560,800 | £470,763 | -16.1% |
| 33 | Market Place, Faringdon | 395 | 47.1% | £449,600 | £503,637 | **+12.0%** |
| 37 | Pipers Close, Heswall | 85 | 80.0% | £328,500 | £351,534 | **+7.0%** |

**Critical finding for regression-risk assessment: this is not a one-directional fix.** 6 of the 9 flagged properties would see their Local Market valuation *increase* under type-weighting, not decrease — the "compatible" broad-type pool happens to skew cheaper than exact-type comparables in those cases (e.g. cheaper Terraced comparables currently dragging a Semi valuation down, or a mixed-type pool that's actually more expensive on average once genuinely weighted toward exact matches). Only Ladygrove and Vyner Road South show the "large Detached properties inflating a smaller-type subject" pattern seen in the primary case study. This symmetry is reassuring evidence that the fix is a general correctness improvement, not a tuning hack calibrated to look good on the one anomaly that triggered this investigation.

**Caveat on the counterfactual figures above**: these recompute only the Local Market group's own weighted-mean valuation with `property_type_weight()` applied, holding evidence_status, evidence_quality, and reconciliation weight constant. They do not model second-order effects — if type-weighting also changes a group's evidence_status classification (plausible, since the contamination is currently invisible to that classifier — see the blind-spot finding above), the final blended V2 figure could move by more or less than the Local Market group's own figure suggests. A full implementation would need to re-run `_calculate_evidence_status`/`_calculate_evidence_quality` on the corrected weighting, not just the weighted mean.

## Smallest General Fix

Apply `property_type_weight()` inside `_local_comp_weight()` (or as an additional multiplier at the call site in `build_local_market_evidence_group()`), exactly as Direct and Development Evidence already do. This requires no new classification logic — `is_property_type_compatible()` and `property_type_weight()` already exist and are already proven correct elsewhere in the same file. The same fix, applied identically, would also close the equivalent gap in Area Market Evidence once that group is implemented.

This is not Ladygrove-specific: it reuses an existing, already-validated mechanism, and the 9-property scan shows it moves values in both directions depending on the actual price relationship between exact and compatible-type stock in each local market — the definition of a general correctness fix rather than a targeted patch.
