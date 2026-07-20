# Valuation Engine Roadmap

**Status: FROZEN.** This document is the governing record of the architectural
review conducted across this project's v1 Beta phase. It should not be
re-expanded or redesigned without a genuinely new class of problem being
discovered (see "Architecture Review Complete" at the end). Future sessions
should primarily *implement* items below, in order, rather than revisit the
architecture.

This document does not itself change any engine behaviour. It is a planning
record only.

---

## Implementation Order (agreed, final)

1. ~~Outcome tracking infrastructure~~ — **Done.** `outcome_tracking` table + capture wired into app.py.
2. **Expand validation dataset (target ~100 properties) — IN PROGRESS: 44/~100, pause LIFTED (2026-07-17).**
   - **Geocoding dedupe/batching — Done, committed (`68b614b`), pushed.** Fixed in `src/transport.py` (`geocode_postcodes_batch()`) and `src/comparable_engine.py`. Validated: 4-property cold-cache benchmark showed 3.4-6.6x speedup, 0 mismatches against sequential results, 100% warm-cache hit rate on re-run.
   - **Local Market property-type weighting — Done.** The systemic finding that paused this item (9/37 = 24% of properties affected by Local Market admitting mixed property types without discounting them, unlike Direct/Development) has been fixed, forensically validated (full per-group trace on two focus cases, 37/37 properties re-run before/after with zero unexplained movement), approved, and promoted as baseline `v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting`. See that baseline's `manifest.json` and `validation_baselines/forensic_reports/` for full detail. **Dataset expansion pause is lifted — resuming toward ~100.**
   - One finding from this investigation was deliberately *not* fixed and is carried forward as a new future item — see "Development Evidence Robustness" below.
3. Planning API caching — next scheduled item, resumes once dataset expansion (item 2) reaches ~100.
4. **PPD Category filtering** (moved ahead of explainability — see rationale below)
5. Explainability / retrieval transparency (wording, retrieval-state reporting, evidence provenance)
6. Leasehold discovery
7. Calibration reporting using real outcomes
8. Calibration dashboard
9. Uncertainty ranges
10. Market regime research
11. Weight/profile/confidence tuning
12. EPC adjustment research

### Roadmap Exception (2026-07)

This document is frozen and not meant to be routinely re-expanded (see
"Architecture Review Complete" below). The geocoding dedupe/batching item
is a deliberate, narrow exception to that freeze: the 37-property
validation run (item 2) produced direct quantitative evidence of a severe,
previously-theoretical performance bottleneck (median 65.9s/property, mean
220.6s/property, several 15-25 minute properties, purely from cold-cache
sequential geocoding). Fixing a measured operational blocker to the
in-progress roadmap item it was discovered inside of is not the kind of
architectural drift this freeze exists to prevent — it is exactly the
"genuinely new class of problem" carve-out the freeze already allows for.
Planning API caching (item 3) remains the next *scheduled* item once
dataset expansion resumes.

Commercial Readiness items (below) run in parallel to this list and only
become urgent if/when commercialization is pursued — they never compete for
priority against it.

---

## 1. Outcome Tracking Infrastructure (Critical, highest priority)

The foundation for every calibration item below. Nothing in items 7–12 can be
validated — only asserted — without this existing first.

### Immutability principle

**Every prediction is a permanent, append-only record. Predictions are never
overwritten or updated in place.**

If the same property is analysed three times under three different
`MODEL_VERSION`s (or even the same version, re-run later against fresher
comparable data), that produces **three separate rows**, not one row updated
three times. This is the property that makes the dataset useful — without it,
none of the following questions are answerable:

- Did V2 outperform V1?
- Did CR1 improve accuracy?
- Did H0 improve confidence calibration?
- Which `MODEL_VERSION` was genuinely best, measured against real outcomes?

Only the *outcome* fields (`sale_completed`, `eventual_sale_price`,
`sale_date`, etc.) are ever updated after a row is created — because the
sale outcome is a real-world fact that becomes known later, not a
re-computation of the prediction. The prediction fields themselves
(`predicted_fair_value_*`, `predicted_confidence_*`, `model_version`, etc.)
are write-once. This history — many predictions against the same properties,
across engine versions, checked against real outcomes over time — is
expected to become one of the most valuable assets the project owns, more
valuable long-term than any single modelling improvement.

### Proposed schema (design only, not yet implemented)

The project already has a `properties` table and a `calibration_log` table
in `property_db.py`. A gap was found while designing this: `properties.
eventual_sale_price` and `calibration_log.eventual_sold_price` are two
different columns in two different tables recording what should be the same
fact — there is currently no single source of truth for "what did this
property actually sell for." The schema below is designed to become that
single source of truth, superseding both existing fields (migration to be
handled at implementation time, not now).

```sql
CREATE TABLE outcome_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id),

    -- Prediction snapshot (WRITE-ONCE — never updated after creation)
    valuation_date TEXT NOT NULL,
    asking_price REAL,
    predicted_fair_value_balanced REAL,
    predicted_fair_value_conservative REAL,
    predicted_fair_value_aggressive REAL,   -- doubles as the existing range
    predicted_confidence_score INTEGER,
    predicted_confidence_label TEXT,
    predicted_valuation_status TEXT,

    -- Provenance / reproducibility
    model_version TEXT NOT NULL,            -- MODEL_VERSION at time of run
    baseline_version TEXT,                  -- nearest baseline snapshot, if any
    deployed_commit TEXT,                   -- from deployment_info.py, if available
    source_engine TEXT,                     -- "V1" or "V2"

    -- Per-group snapshot (needed for evidence-status / weight-profile
    -- calibration dashboard views — flagged as a gap in the original
    -- schema draft; a JSON blob mirroring ValuationEvidence.to_dict()
    -- is the more maintainable option vs. ~20 flat columns)
    groups_snapshot_json TEXT,

    -- Development/extension context (captured, never blended into valuation)
    extension_potential_identified INTEGER DEFAULT 0,
    extension_potential_score INTEGER,

    -- Eventual outcome (nullable until known; these fields ARE updatable)
    sale_completed INTEGER DEFAULT 0,
    eventual_sale_price REAL,
    sale_date TEXT,
    days_to_sell INTEGER,
    price_reduction_count INTEGER DEFAULT 0,
    price_reduction_total REAL,

    -- Human oversight
    manual_notes TEXT DEFAULT '',
    outcome_source TEXT DEFAULT '',   -- e.g. "land_registry_confirmed", "user_reported", "estimated"

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_outcome_property ON outcome_tracking(property_id);
CREATE INDEX idx_outcome_model_version ON outcome_tracking(model_version);
CREATE INDEX idx_outcome_sale_completed ON outcome_tracking(sale_completed);
```

`price_reduction_count`/`price_reduction_total` require tracking a listing
over time (periodic re-checks of asking price) — a new capability, not just
a new column. Existing `calibration_log` qualitative fields
(`valuation_judgement`, `comparable_quality`, `error_tags`) remain
complementary: `outcome_tracking` records what happened; `calibration_log`
records human judgement about why.

---

## 2. Expand Validation Dataset (~100 properties) — IN PROGRESS: 44/~100

Grow the fixed set in `validate_baseline.py` from 20 to roughly 100
properties, stratified across property type, region, and evidence-status mix
(deliberately including some properties that land in WEAK/FALLBACK_ONLY
territory, not just STRONG) — 20 is enough to catch gross regressions but too
small to detect calibration drift.

**Status**: 44 properties collected and validated (20 original + 17 from the
first expansion batch + 7 from the second batch, all sourced live from real
Rightmove listings, 2026-07). Full run output preserved at
`validation_baselines/20260715_194932_baseline_v2-evidence-status-fallback-guard-real-hpi-cr1-h0_item2-expansion-37.csv`/`.json`
(first batch, 37 properties) and
`validation_baselines/20260720_155601_baseline_v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting.csv`/`.json`
(current, 44 properties, 0 errors).

**Second batch (37→44) added**: one confirmed-leasehold flat (Bristol, The
Vincent, BS6 6BJ — closes the confirmed-leasehold gap) and three genuinely
new UK regions with no prior coverage — South West (Bristol), Yorkshire
(York), South East/Kent (Canterbury) — versus the first batch's
Oxfordshire/North-West-only geography.

**Known remaining gaps** (updated after the second batch): bungalows still
thin (2/44 confirmed), confirmed-leasehold flats improved but still light
relative to real UK stock composition (6/44 confirmed), sparse-comparable
and unusual-property-type cases could still use more deliberate examples
beyond what's fallen out incidentally, and the three new regions added are
each represented by only 1-4 properties — not yet enough per-region density
to be a robust regional cross-check on their own. The bulk of the dataset
(37 of 44) remains on the original Oxfordshire + North West axis.

**Property #37 (Pipers Close, Heswall, CH60 7RE)** was flagged untrustworthy
in the original run (0.0s elapsed, V1=V2=£0, likely a network-resume
artifact after the run spanned an overnight machine sleep). Re-run in
isolation after the geocoding fix below — see Geocoding Fix Validation
section for the corrected result. The original suspect run is retained in
the dataset's audit trail; the corrected run is a separate, versioned entry
per the "never silently overwrite a prediction" principle established in
item 1.

**Property #27 (Ladygrove, Didcot, OX11 9BS) — FIXED (partially).** The root
cause identified during investigation — Local Market Evidence admitting
Detached/Terraced comparables as "compatible" type without applying
`property_type_weight()`, unlike Direct and Development Evidence — has been
fixed and promoted as baseline
`v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting`. This
property's Local Market valuation corrected from £560,800 to £470,700
(-16.1%, matching the forensic counterfactual almost exactly). **The
property's headline anomaly is only partially resolved**, however: its
final V2 figure barely moved (£1,415,600 → £1,385,600, -2.1%) because
Development Evidence — untouched by this fix, and itself carrying its own
unresolved thin-evidence problem — dominates this property's blend at ~67%
weight. See "Development Evidence Robustness" below for the follow-on item
this exposed.

**Local Market property-type weighting fix — DONE, baseline promoted.**
Systemic scan confirmed the pattern affected 9/37 properties (24%), not
just Ladygrove. Full forensic audit, counterfactual analysis, before/after
validation on all 37 properties, and reviewer-level movement classification
in `validation_baselines/forensic_reports/stage2_local_market_type_weighting_audit.md`.
Baseline: `baselines/v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting/manifest.json`.

**Interim performance blocker discovered and fixed**: see "Roadmap
Exception" above and "Geocoding Fix Validation" below — the geocoding
dedupe/batching fix was implemented and validated before dataset expansion
resumed.

**Pause lifted (2026-07-17)**: both findings that paused this item are now
resolved — see above. Resuming sourcing toward ~100, prioritising bungalows,
confirmed-leasehold flats, a genuinely new UK region, unusual property
types, sparse-comparable cases, premium markets, and other difficult edge
cases, per the coverage gaps identified in the first expansion batch. Per
the agreed validation philosophy: **do not modify valuation logic during
the remainder of this item unless another genuinely systemic issue (like
the one just fixed) is discovered** — the purpose of the remaining
expansion is to increase confidence in the engine, not continue tuning it.
If a new pattern emerges affecting multiple unrelated properties, pause
again, investigate, fix, then resume — exactly the cycle just completed.

---

## Development Evidence Robustness (new future item, not implemented)

**Motivating cases**: Ladygrove (OX11 9BS) and Pipers Close (CH60 7RE) —
both properties where Development Evidence, resting on only 1-2
comparables, ended up dominating (or nearly dominating) the final blend.
For Pipers Close specifically, the deep forensic trace during the Local
Market fix's validation confirmed Development Evidence's own £123,100
figure never changed, but the *weight* resting on it increased from 62.7%
to 73.7% as a direct, correct consequence of the Local Market fix — meaning
this property's exposure to Development Evidence's still-unresolved problem
increased, even though nothing about this fix was wrong.

**Candidate work items** (investigation only — none implemented):

- Robustness of thin evidence groups (very low comp counts, e.g. Development Evidence's 1-2-comp cases here)
- Extreme comparable influence — how much should a single comp be allowed to dominate a group's valuation
- Minimum evidence safeguards — is there a principled floor below which a group shouldn't carry significant reconciliation weight regardless of its nominal confidence/status
- Price-plausibility investigation — Direct/Estate Evidence's `_admit_fallback_comps()` already guards against implausible prices for *type*-fallback admissions specifically; investigate whether an analogous guard is needed for thin groups generally, independent of why they're thin
- Development Evidence weighting review — once the above are understood, whether Development Evidence's own weighting needs a change analogous to what Local Market just received

Not scheduled against a step number yet — flagged here as the next
candidate systemic investigation once dataset expansion (item 2) either
completes or surfaces another pattern first.

---

## Geocoding Fix Validation (interim item, completed 2026-07)

Implemented `geocode_postcodes_batch()` in `src/transport.py` and wired a
single pre-warming call into `src/comparable_engine.py`, ahead of the
existing (unchanged) per-comparable distance loop. Dedupes unique
comparable postcodes, reads the disk cache synchronously first, and fetches
only genuine cache misses concurrently via a 5-worker thread pool. Does not
change which postcodes are geocoded, distance calculations, comparable
selection, evidence weighting, fair value, confidence, Evidence Status, or
Recommendation — verified below.

**Cold-cache benchmark** (4 properties, cache deliberately cleared per
postcode set before each measurement):

| Property | Raw comps | Unique postcodes | Before | After | Speedup | Warm re-run | Mismatches |
|---|---|---|---|---|---|---|---|
| Arundel Avenue, Liverpool (L17 2AU) | 998 | 127 | 88.0s | 22.6s | 3.9x | 0.10s | 0 |
| Ladygrove, Didcot (OX11 9BS) | 1001 | 165 | 173.0s | 51.3s | 3.4x | 0.25s | 0 |
| Ruttle Close, Cholsey (OX10 9QT) | 999 | 178 | 206.9s | 31.5s | 6.6x | 0.13s | 0 |
| Ingestre Road, Prenton (CH43 5UX) | 999 | 160 | 184.6s | 50.9s | 3.6x | 0.17s | 0 |

Zero failures/timeouts across all 4 properties in both before and after
passes. Warm-cache hit rate: 100% on immediate re-run for all 4. **Zero
mismatches** between sequential and batched geocoding results for any
postcode across all 4 properties — coordinates returned are byte-identical,
confirming the fix changes only *how fast* geocoding happens, not *what* it
returns. Existing regression suites (`test_location_assessment.py`,
`test_recommendation_shape.py`) pass unchanged.

---

## 3. Planning API Caching (highest-priority engineering fix)

`planning.py`'s `_check_constraints()` makes six sequential, **entirely
uncached** network requests per valuation (conservation area, listed
building, green belt, AONB, article 4, flood zone) — the only uncached
external call path in the pipeline, despite already importing the caching
utilities used everywhere else.

- **Cache key**: `cache_key("planning", {"pc": postcode, "lat": latitude, "lon": longitude})`, one entry covering all six checks together.
- **Infrastructure**: reuse `get_cached`/`set_cache` from `utils.py`, exactly as `transport.py` already does for geocoding.
- **TTL**: 90 days (2160h). Statutory planning designations move at the pace of local plan reviews (annual at the fastest, often multi-year) — materially slower than HPI (30-day TTL) and comparable in stability to geocoding (1-year TTL). This tool advises on extension *potential*, not a legal determination, so a 90-day-stale boundary carries negligible practical risk.
- **Zero valuation impact**: planning/extension-potential data is already fully disconnected from `fair_value_balanced` and all evidence groups — caching it cannot touch valuation maths by construction.
- **Validation**: byte-diff `validate_baseline.py` output before/after across every field, not just fair value. Expect zero changed fields anywhere in valuation output; only `elapsed_seconds` should drop on a warm-cache run.
- **Bundled fix**: while touching this function, also address the silent-failure gap found during review — every one of the six checks currently uses a bare `except Exception: pass` with no failure recorded, so "No major constraints identified" is indistinguishable from "5 of 6 checks errored." Record which checks succeeded vs failed alongside the cached result (feeds item 5's retrieval-state work).

---

## 4. PPD Category Filtering (moved ahead of explainability — rationale below)

**Why this moved up**: Land Registry's Price Paid Data carries a `PPD
Category Type` field (A = standard price paid entry; B = additional entries,
including repossessions, transfers under a power of sale, and buy-to-lets
between related entities) specifically so downstream users can exclude
non-market transactions from comparable evidence. The current hard gates in
`comparable_engine.py` (`_apply_hard_gates`) check property type, new-build
status, sale age, and gross price bounds — but never this field. It is
silently absent, not deliberately excluded.

This is not a tuning exercise like the weighting/confidence work deferred to
items 11–12 — it is a correction to the raw evidence every downstream
component assumes is valid. Fixing it improves evidence quality,
confidence, reconciliation, explanation, recommendation, and future
calibration simultaneously, because all of them are built on the assumption
that the comparable pool reflects genuine market transactions. A
sophisticated weighting system built on contaminated inputs is not more
trustworthy than a simple one on clean inputs — it just fails more
elegantly. This was independently identified as the single change most
likely to affect a knowledgeable property professional's assessment of the
tool's credibility (see the closing section of the architectural review).

- **Fix**: parse and gate on `PPD Category Type` alongside the existing hard gates.
- **Complexity**: Low — one new field parse + one new gate condition.
- **Regression risk**: Low — pure exclusion of already-excludable noise; expect small reductions in Tier A-C comp counts on the validation set, not zero.
- **Validation**: compare tier counts and fair values before/after on the (now ~100-property) validation set.

---

## 5. Explainability / Retrieval Transparency

Three sub-items, in this sequence — (a) and (b) determine what (c) is even
allowed to say:

### (a) Retrieval-state reporting

Every external data source and retrieval stage (Land Registry, EPC,
Planning, HPI, Geocoding, Transport, comparable enrichment) should be
classified per run into: `SUCCESS`, `PARTIAL`, `FAILED`, `NOT_AVAILABLE`,
`NOT_REQUESTED`. Most of this data already exists in developer-facing
diagnostic fields (`strategy_details`, `data_gaps`) — the work is surfacing
it to the user, not collecting it fresh. Explicitly **not** intended to
change confidence or evidence status — only to inform the user more
honestly about what was actually available. The planning silent-failure gap
(item 3) is the sharpest example found and should be fixed alongside its
caching work.

### (b) Sentence-defensibility audit

Every user-facing sentence should be classifiable as FACT, INFERENCE,
HEURISTIC, OPINION, or ASSUMPTION. A representative sample audit (not yet
exhaustive) found the codebase mostly already hedges inference correctly
("may", "tends to"), with two confirmed rewrites needed:
`risk_assessor.py:98` ("The valuation cannot be relied upon" — stated as
flat fact where it's the tool's own risk judgement) and
`explanation_engine.py:286` ("reflecting current market conditions" —
unhedged where the rest of the module hedges consistently). The
extension-potential build-cost bands (`BUILD_COSTS_PER_SQM`) should also
gain an explicit sourcing/date disclosure. A full line-by-line pass across
all free-text generators is part of this item's implementation scope.

### (c) Evidence provenance

Every major conclusion should answer "what evidence produced this?" —
e.g. "OVERPRICED — derived from: 12 direct comparable sales, 4 estate
comparables, local market evidence, HPI adjusted to [month], Confidence:
Medium" or "INSUFFICIENT EVIDENCE — because: no compatible same-type sales,
estate evidence unavailable, local market too sparse, planning assessment
completed, EPC unavailable." All required data already exists as structured
fields by the time `blend_evidence()` returns (`reconciliation.
group_weights`, per-group `comp_count`/`evidence_status`, HPI diagnostics,
planning `constraints_summary`, EPC match counts) — `explanation_engine.py`
already assembles narrative from these same fields, so this is naturally an
extension of that module rather than new data collection. Assessed as
low-to-medium complexity, zero valuation risk (read-only summary), and
identified as a genuine potential product differentiator, not just a
transparency feature.

---

## 6. Leasehold Discovery (investigation complete — findings below; no fix scheduled yet)

No reliable free bulk source of lease-length data exists:

- **EPC register**: not available — `TENURE` field records occupancy type, not legal tenure/lease term.
- **Land Registry PPD**: not available — `Duration`/`estateType` is Freehold/Leasehold binary only, no term remaining.
- **Land Registry Title Register**: available, but paid per-title lookup (~£3/title) via a separate HM Land Registry Business Gateway account — a real cost/licensing decision, not a code change.
- **Rightmove listing page**: partially available in the same page payload already being fetched (no new network call), but agent-populated and inconsistently formatted — best-effort text extraction only, not a trusted numeric field.
- **Existing scaffolding**: `risk_assessor.py` already has a fully-built, dormant `lease_years: Optional[int]` parameter threaded through `_assess_tenure_risks()` with correct short/moderate-lease risk logic — it is simply never called with a real value anywhere in `app.py`.

**Recommended sequencing when implemented**: (1) disclosed limitation now
(cheap, honest — flag missing lease term in `data_gaps` for leasehold
properties); (2) Rightmove best-effort extraction, feeding the dormant
`lease_years` parameter, display-only with an "unverified" flag — not fed
into valuation or confidence until parse reliability is measured; (3) Land
Registry Title Register as a longer-term paid option, only if outcome data
later shows lease length materially explains valuation error for leasehold
properties.

---

## 7. Calibration Reporting Using Real Outcomes

Once outcome data (item 1) exists:

1. Compute `abs(predicted_fair_value_balanced - eventual_sale_price) / eventual_sale_price` per completed property.
2. Bucket by `predicted_confidence_label` — check whether mean/median error is monotonically increasing as confidence decreases.
3. Build a calibration curve: `predicted_confidence_score` (x-axis) vs. observed error (y-axis).
4. Use a binned reliability diagram (expected error vs. observed error), not a Brier score — Brier scoring is built for probabilistic binary outcomes, and confidence here isn't that; a reliability diagram is more directly interpretable.

A standalone `calibration_report.py`, read-only against `outcome_tracking` +
historical baselines, producing this analysis. No engine changes.

---

## 8. Calibration Dashboard (future deliverable, trigger = data volume not calendar time)

Successor to item 7's CSV/JSON reports, not a replacement. Views map
directly onto `outcome_tracking` fields: prediction error distribution,
confidence calibration, valuation drift over time (grouped by
`valuation_date`, same property across `model_version`s), evidence-status
performance and weight-profile performance (require the
`groups_snapshot_json` field flagged in item 1's schema), engine-version
comparison (`model_version`), baseline comparison (`baseline_version`),
sale-price vs. prediction scatter, rolling accuracy metrics. Not scheduled
against a step number — triggered by item 7 accumulating enough real
outcome volume to be worth a UI, which realistically means months of
tracked completions, not a sprint.

---

## 9. Uncertainty Ranges (future, presentation question)

Reframe fair value as best estimate + likely range + confidence label,
rather than a single point figure. Two open questions to resolve before
implementation: whether the range should complement or replace the
existing confidence label (the label is also used internally for weight
profile selection and offer-eligibility gating — those internal uses must
stay untouched even if display changes), and whether the existing
`fair_value_conservative`/`fair_value_aggressive` bounds are *calibrated*
uncertainty (do real outcomes fall inside the stated range at the rate
implied) — which depends on item 7's outcome data to check before
presenting the range as meaningful rather than decorative.

---

## 10. Market Regime Calibration (future research question, not implementation)

Open question: does the optimal `_WEIGHT_PROFILES` allocation
(Direct/Estate/Local/Area) change with market regime (rapidly rising, flat,
falling)? Cannot be investigated meaningfully until outcome data (item 1)
spans more than one market regime — realistically 18-24+ months of tracked
completions. No market-regime detection logic should be added until then.

---

## 11. Weight/Profile/Confidence Tuning (deliberately last among modelling items)

`_WEIGHT_PROFILES` and the tier/confidence score bands are currently
hand-picked constants with no empirical fitting against outcomes. Do not
re-tune these until item 7 (calibration reporting) has run at least one
cycle — tuning blind is how the current unvalidated weights arose in the
first place.

---

## 12. EPC Adjustment Research (long-term, blocked on outcome data)

EPC rating plausibly affects value but is heavily confounded with
condition, age, refurbishment, property type, and location. No coefficient
work begins until calibration reporting (item 7) exists and can isolate
EPC's effect from those confounds — otherwise any adjustment risks encoding
correlation as causation.

---

## Commercial Readiness (parallel track, not sequenced against the list above)

Separated from the modelling/engineering roadmap because it mixes
regulatory, legal, and go-to-market concerns that should never compete for
priority against improving the valuation engine itself. Revisit only if/when
commercialization is actually pursued.

- **Regulatory wording**: explicit statement that this is not a RICS Red Book valuation and carries no professional indemnity backing.
- **Professional disclaimers**: per-report disclaimer text, versioned alongside `RELEASE_NOTES.md`.
- **Audit logging**: durable, append-only record of what evidence/parameters produced a given report — distinct from `property_db.py`'s convenience history, this is about non-repudiation.
- **Reproducibility**: document that identical inputs + identical `MODEL_VERSION` can still produce different output because Land Registry/HPI/EPC data itself drifts over time — an inherent, not fixable, source of non-determinism.
- **Version traceability**: extend the existing `deployment_info.py`/baseline system to per-report version stamping.
- **Evidence provenance**: serves both explainability (item 5c) and commercial defensibility — a provenance trail is what you'd want if a valuation were ever challenged.
- **Licensing of external data**: Land Registry PPD, EPC register, and Planning Data API are UK Open Government Licence (OGL) — permissive. postcodes.io's terms and Rightmove's scraping-based source are **not** OGL and would need explicit legal review before any commercial use, since Rightmove's terms restrict automated data extraction. Flagged as a real constraint now, not a nice-to-have.
- **API resilience**: extends item 5a's retrieval-state work with SLA-aware fallback behaviour and a documented "degraded mode" acceptable for commercial use.
- **Legal considerations if sold commercially**: consumer protection / financial promotion rules if output is ever presented as investment advice — a legal review item, not an engineering one.

## Long-term idea: Technical View (documented, not scheduled)

An optional toggle — default report designed for buyers; Technical View
designed for surveyors/investors/analysts, exposing reconciliation weights,
evidence hierarchy, excluded comparables, confidence drivers, retrieval
states, evidence provenance, and calibration metadata without overwriting
the default experience. A natural home for everything in item 5 and the
Commercial Readiness audit-logging item that's too dense for a homebuyer but
essential for a professional auditing the tool's reasoning.

---

## Architecture Review Complete

The architecture has been reviewed end-to-end across this project's v1 Beta
phase: evidence hierarchy, reconciliation, evidence status, confidence
calibration, comparable selection, baselines, regression testing,
versioning, deployment traceability, and now data-quality, validation, and
commercial-readiness planning. Major structural issues identified during
this review — the internal-consistency gap (CR1), the confidence-display
mismatch for fallback-only evidence (H0), the deployment-diagnostics gap,
and the location-assessment honesty gap — have been addressed and validated
against the baseline system.

From this point forward, the project's bottleneck is evidence quality,
validation, and calibration — not software architecture. Future work should
focus primarily on **implementing items already on this roadmap**, in the
order listed, rather than redesigning the system that produces them.
Architectural changes should now be considered **exceptional**, warranted
only by a genuinely new class of problem discovered during implementation —
not routine, and not a default response to every new finding. This roadmap
is frozen as the governing document for that work.
