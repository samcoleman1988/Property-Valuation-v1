# Validation Dataset Coverage Matrix — 70 Properties (2026-07-30)

**Status: read-only analysis. No dataset expansion or valuation logic changed as part of this report.**

Source data: `validate_baseline.py`'s `PROPERTIES` list (70 entries) cross-referenced with the latest full run (`validation_baselines/20260730_104639_baseline_..._lm-type-weighting.json`) for comparable counts and evidence status. Classification rules are stated explicitly below — this is a derived, rule-based matrix, not a hand-guessed one.

## 1. Coverage Matrix

### Property Type

| Type | Count | % |
|---|---|---|
| Terraced | 21 | 30.0% |
| Flat | 18 | 25.7% |
| Semi-Detached | 14 | 20.0% |
| Bungalow | 9 | 12.9% |
| Detached | 6 | 8.6% |
| Retirement | 2 | 2.9% |
| Maisonette | **0** | **0.0%** |
| Other | 0 | 0.0% |

*Classification: "Retirement" pulled out of "Flat" by scanning the property label for "retirement"/"Richmond Villages" — the underlying `type` field is still `"Flat"` (Land Registry has no separate retirement category), so this is a market-segment tag, not a code-path distinction.*

### Tenure

| Tenure | Count | % |
|---|---|---|
| Unknown (unconfirmed on listing) | 41 | 58.6% |
| Freehold | 20 | 28.6% |
| Leasehold | 8 | 11.4% |
| Share of Freehold | 1 | 1.4% |

### Region

| Region | Count | % |
|---|---|---|
| Oxfordshire | 24 | 34.3% |
| North West | 13 | 18.6% |
| West Midlands | 12 | 17.1% |
| South West | 10 | 14.3% |
| East Midlands | 5 | 7.1% |
| Yorkshire | 4 | 5.7% |
| South East | 1 | 1.4% |
| London | 1 | 1.4% |
| East of England | 0 | 0.0% |
| North East | 0 | 0.0% |
| Wales | 0 | 0.0% |
| Scotland | N/A — see note below |

*Note on Scotland: Scotland uses Registers of Scotland, not HM Land Registry Price Paid Data — the comparable engine's data source (`landregistry.data.gov.uk`) does not cover Scotland at all. A Scottish property cannot be validated by this engine without a separate data integration, which is out of scope for dataset expansion. This is a structural limitation, not a sourcing gap.*

### Evidence Profile (rule-based tags, a property can carry more than one)

| Tag | Count | % | Rule |
|---|---|---|---|
| Dense comparables | 46 | 65.7% | `local_market_evidence_comp_count` or `direct_evidence_comp_count` ≥ 100 |
| Urban | 31 | 44.3% | Label/description matches known urban/city-centre keywords |
| Edge case | 18 | 25.7% | Label/why_selected matches unusual/HMO/outlier/collision keywords |
| Premium | 11 | 15.7% | Asking price in the top 15% of the dataset |
| Sparse comparables | 10 | 14.3% | `credibility_judgement == INSUFFICIENT_EVIDENCE` or comp_count == 0 |
| Rural | 8 | 11.4% | Label/why_selected matches village/rural keywords |
| Standard (no tag applied) | 4 | 5.7% | — |

### Type × Region Cross-Tab

| Type | Oxon | NW | SW | WMid | EMid | Yorks | SE | Lon |
|---|---|---|---|---|---|---|---|---|
| Detached | 3 | 1 | 0 | 0 | 0 | 0 | 1 | 1 |
| Semi-Detached | 9 | 2 | 0 | 3 | 0 | 0 | 0 | 0 |
| Terraced | 8 | 3 | 1 | 5 | 4 | 0 | 0 | 0 |
| Flat | 2 | 5 | 2 | 4 | 1 | 4 | 0 | 0 |
| Maisonette | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bungalow | 0 | 2 | 7 | 0 | 0 | 0 | 0 | 0 |
| Retirement | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**Reading this cross-tab is more informative than the marginal totals alone**: Yorkshire is 100% Flat (4/4). East Midlands is 100% Terraced+Flat, no houses at all. London and South East are single Detached data points each. South West is dominated by Bungalow (7/10). Several regions are effectively single-type samples, not balanced cross-sections — raw regional counts understate how thin genuine type-diversity-per-region actually is.

## 2. The Single Most Concrete Finding

**Every Detached property in the dataset (6/6) has abundant local market evidence — comp counts of 55, 357, 444, 398, 176, and 154.** There is currently **zero** genuinely sparse-evidence Detached test case. Detached is simultaneously the thinnest type by raw count (8.6%) and has never been tested under the evidence conditions (thin comparables, reliance on Development/Local Market fallback weighting) that produced the most interesting findings elsewhere in this project (Ladygrove, Pipers Close — both flagged for the still-open "Development Evidence Robustness" future item).

**Second finding**: every Leasehold subject (7/8) lands in a `STRONG` local market — no genuine tenure-conflict scenario (a leasehold subject whose local comparables are mostly freehold, or vice versa) has been tested. `_assess_tenure_match()`'s "different" branch is essentially unexercised by this dataset.

**Third finding**: only 2/70 properties have `local_market_evidence_comp_count` ≤ 2 outside the already-known 10 true-failure (zero-evidence) properties — the dataset has almost no middle ground between "abundant evidence" and "no evidence at all." That middle ground (thin-but-not-empty) is exactly the condition that produces FALLBACK_ONLY-authority weighting decisions, the part of the reconciliation logic most recently under scrutiny.

## 3. Gaps Ranked by Expected Validation Value

| Rank | Gap | Importance | Acquisition difficulty | Expected engine insight |
|---|---|---|---|---|
| 1 | **Sparse-evidence Detached property** (any region) | High | Medium — needs a genuinely rural/low-density Detached listing, not just "expensive" | High — untested combination of type + thin evidence; directly relevant to the open Development Evidence Robustness item |
| 2 | **Genuine tenure-conflict case** (leasehold subject in a freehold-dominated area, or vice versa) | High | Medium-High — requires checking actual local comparable tenure mix, not just the subject's own tenure | High — exercises `_assess_tenure_match()`'s unexercised "different" branch |
| 3 | **More thin-but-not-empty local market cases generally** (comp_count roughly 3-20) | Medium-High | Medium | Medium-High — this band drives the reconciliation weight-profile selection logic most directly |
| 4 | **Detached/Semi-Detached in a new region** (Yorkshire, East Midlands both currently have zero) | Medium | Medium | Medium — mostly tests external data density in a new area, not new engine logic (region is not a branch in the code) |
| 5 | **Maisonette** | **Low** | High (confirmed this session — persistent postcode-visibility problem) | **Low** — `normalise_property_type()` maps flat/apartment/maisonette to the identical Land Registry code "F"; a maisonette would exercise exactly the same code path as the 18 flats already tested |
| 6 | **More London/South East properties for raw regional balance** | Low | High (confirmed postcode-visibility problem, especially London) | Low — the engine has no region-specific branching logic at all (HPI region defaults uniformly, Land Registry queries are region-agnostic); more London properties mostly test data density, already reasonably covered by existing premium/sparse cases elsewhere |
| 7 | **More Freehold Semi/Terraced in Oxfordshire** | Very Low | Low | Very Low — already the most saturated type/region/tenure combination in the dataset (9 Semi + 8 Terraced, both Oxfordshire, mostly Freehold) |

This directly confirms your own framing: a missing maisonette genuinely is lower-value than a sparse rural Detached property, because the code path evidence (not intuition) shows flats and maisonettes are computationally identical, while Detached-under-thin-evidence is a real, untested combination.

## 4. Expected Value of Further Expansion

- **70 → 80**: Meaningful, *if* targeted at ranks 1-3 above (sparse Detached, tenure-conflict, thin-evidence middle ground). A blind continuation of the current city-by-city search strategy would mostly add rank 4-7 value at this stage, given how saturated the "find any full-postcode listing in a new city" approach has become.
- **80 → 90**: Low-to-medium marginal value under any sourcing strategy. By 80 properties, assuming ranks 1-3 are addressed, most remaining code paths (property type × broad evidence-status × broad tenure combinations) will have already been exercised at least once. Additional properties mostly add statistical density within categories already represented, not new categories.
- **90 → 100**: Low marginal value. This is very unlikely to reveal new systematic behaviour — it would function as broader statistical replication of already-tested conditions, valuable for eventual calibration work (ROADMAP item 7, which explicitly needs volume) but not for continued *structural* validation of the engine's decision logic.

**The acquisition cost curve and the value curve are moving in opposite directions**: acquisition cost per property has risen sharply (confirmed empirically — the last 6 properties required searching 6 separate cities), while the expected new-insight value per property is falling as the type/tenure/evidence-profile space fills in. These two trends together are the actual evidence for a stopping-point recommendation, not an assumption.

## 5. Recommended Stopping Point

**Recommend stopping structural coverage expansion at approximately 78-82 properties, not 100** — specifically: the current 70, plus a small, *targeted* batch of 8-12 properties addressing ranks 1-3 in the gap table above (sparse Detached, tenure-conflict, thin-evidence middle ground), sourced deliberately rather than through further blind regional search.

Beyond that point, the success criterion as you framed it — *"reach sufficient coverage that additional properties are unlikely to reveal new systematic valuation behaviour"* — is very plausibly already satisfied for this engine's current decision logic (property type classification, evidence-group construction, reconciliation weighting, tenure matching). Continuing to 100 via broad regional sourcing would primarily serve a *different* goal — building statistical volume for future calibration work (ROADMAP item 7, confidence-vs-accuracy calibration) — which is a legitimate future need, but a different one from "does the engine have any more structural surprises left to find," and should be pursued via the outcome-tracking/calibration path (already a separate, scheduled ROADMAP item) rather than by continuing to force this specific city-by-city sourcing approach past its point of diminishing returns.

## 6. Alternative Sourcing Strategies — Comparison

| Strategy | Postcode availability | Metadata quality | Repeatability | Acquisition effort |
|---|---|---|---|---|
| **Land Registry direct (PPD)** | Excellent — postcode is the dataset's primary key | Good for price/date/type/tenure-duration/new-build; **no** asking price, bedrooms, or description | Excellent — deterministic, scriptable, the same API the engine already queries | **Low** — fully scriptable, no manual browsing |
| **Zoopla** | Untested this session; plausibly similar to Rightmove | Good when present (bedrooms, type, tenure, sometimes lease length) | Medium — another manual-browsing workflow, doesn't solve the underlying postcode-visibility problem, just moves it to a different site | Medium |
| **OnTheMarket** | Smaller inventory, likely similar visibility issues to Rightmove/Zoopla | Similar to Zoopla | Medium | Medium |
| **Individual estate agent websites** | Variable, agent-dependent — can be excellent for a specific targeted search (e.g. a rural specialist agent) | Variable | Low — per-agent research, not a repeatable process | High per property, but can be *precisely targeted* at a specific gap |
| **User-supplied validation cases** | **Perfect** — exact address/postcode supplied directly | As good as what's supplied, likely excellent given local knowledge | Not applicable (one-off) | **Low** for the assistant; requires the user's time |
| **Synthetic edge cases** | N/A — still needs a real postcode anchor; "synthetic" means constructing an unusual subject (e.g. deliberately malformed type string) against a real, already-used postcode | N/A — by design, not a real listing | Perfect — fully deterministic, scriptable | **Very low** — no web sourcing at all |

### Recommendation

1. **Primary, for the targeted ranks-1-3 gaps**: ask you directly for a small number of known properties matching the specific profiles needed (a rural/low-density Detached listing, a leasehold property in an obviously freehold-dominated street) — this is the most efficient path precisely *because* it's targeted, not broad, and sidesteps the confirmed postcode-visibility problem entirely.
2. **Primary, for future volume/calibration work (ROADMAP item 7)**: Land Registry direct sourcing — fully scriptable, deterministic, and dual-purpose: a recently-sold property used as a validation subject also comes with a genuine known outcome, which is exactly what the outcome-tracking/calibration item needs. This should probably be built as its own small tool rather than continued ad-hoc Rightmove browsing.
3. **Explicitly deprioritise**: continuing the current Rightmove-search-by-city approach, and Zoopla/OnTheMarket as like-for-like substitutes — all three share the same fundamental manual-browsing-with-postcode-visibility-risk problem already confirmed this session.
4. **Future, clearly separated from the validation benchmark**: synthetic edge cases for pipeline robustness testing (malformed inputs, boundary conditions) — valuable, but a different kind of test than market-representativeness validation, and must never be mixed into `PROPERTIES` without an explicit, visible marker distinguishing it from genuine market data.

## 7. Summary Answer to Each Deliverable Point

1. Coverage matrix: see Section 1.
2. Remaining high-value gaps: sparse-evidence Detached, genuine tenure-conflict, thin-but-not-empty local market cases (Section 3, ranks 1-3).
3. Expected value of another 30 properties (70→100): front-loaded — most of the remaining value is captured in the next ~10, with steep diminishing returns after that (Section 4).
4. Recommended stopping point: **~78-82 properties**, reached via a small targeted batch, not continued broad regional sourcing to 100 (Section 5).
5. Recommended sourcing strategy for the remainder: user-supplied targeted cases for the specific structural gaps; Land Registry direct sourcing for future calibration volume; deprioritise further blind Rightmove/Zoopla/OnTheMarket city-by-city search (Section 6).
