# Release Notes

## Baseline update — 2026-07-17: Local Market property-type weighting

**Baseline:** `v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting` — see `baselines/v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting/manifest.json` for the full change record and validation methodology.

Local Market Evidence now applies `property_type_weight()` consistently with Direct and Development Evidence. This changes Local Market valuations, Evidence Status and reconciliation weights for properties containing mixed property types. Comparable retrieval, HPI, geocoding, recommendation logic and V1 behaviour are unchanged.

**Why this baseline exists**: expanding the validation dataset from 20 to 37 real properties surfaced a systemic pattern — Local Market Evidence was the only evidence group that admitted a broad mix of property types (e.g. Detached comparables for a Semi-Detached subject) without discounting them, unlike Direct and Development Evidence, which already used `property_type_weight()` for exactly this. A forensic investigation (see `validation_baselines/forensic_reports/`) traced this to a real valuation defect affecting 9 of 37 properties (24%) in the current dataset, most visibly a Didcot property whose V2 fair value reached £1.4M against a £450,000 asking price. The fix reuses the same shared weighting mechanism already validated elsewhere in the engine — no new compatibility matrix, no property-specific tuning.

**Validation**: 37/37 properties succeeded before and after, byte-diffed field-by-field. 7 properties moved >5% in final V2 value — all a subset of the 9 properties independently flagged by the pre-fix forensic scan, confirming no unexpected movement occurred elsewhere. Two focus cases were traced at full per-evidence-group detail to confirm Direct and Development Evidence were byte-identical before and after (i.e. this fix touched only what it was scoped to touch). Full detail in the baseline manifest linked above.

## v1 Beta — 2026-07-09

First release intended for real-use testing (not just synthetic validation properties). Deployed for mobile access via Streamlit Community Cloud — see the README's "Deploying (v1 Beta)" section.

### What's in this release

- **Valuation engine baseline:** `v2-evidence-status-fallback-guard-real-hpi` — see `baselines/v2-evidence-status-fallback-guard-real-hpi/manifest.json` for the exact source-file snapshot this release is built from.
- **Four-group evidence architecture** (Direct, Development, Local Market, Area Market) with explicit Evidence Status classification (STRONG / WEAK / FALLBACK_ONLY / EMPTY) driving how much weight each group gets in the final blend.
- **Real regional HPI adjustment** — comparable sale prices are adjusted to current-equivalent values using actual UK House Price Index data (not a flat growth-rate approximation).
- **Fallback-admission guard** — when a group has fewer than 3 genuinely-typed comparables, a wrong-type comp can only stand in if its price is within ±50% of the genuine median; otherwise it's excluded and kept as context only.
- Investment scorecard, risk assessment, buy-to-let analysis, planning/extension flags, and PDF report generation — unchanged from earlier development, not touched in this release.

### Validation status at release

- 20-property fixed validation set: 20/20 succeeded, 0 failures
- Evidence status totals: 26 STRONG, 13 WEAK, 8 FALLBACK_ONLY, 33 EMPTY
- Real HPI confirmed active (source: `real_hpi`, region: England, latest month: 2026-04)
- No credibility judgement worsened versus the prior (flat-rate HPI) baseline

Full validation run: `validation_baselines/20260709_121816_baseline_v2-evidence-status-fallback-guard-real-hpi.csv` / `.json`.

### What "Beta" means here

This is real-use testing, not a finished product:

- Treat every valuation as a starting point for judgement, not a final answer — see the README's "Recommended Operating Workflow."
- Known limitations (floor area coverage, generic street names, cold-fetch latency, basic extension appraisal) are listed in the README's "Known Limitations" section and haven't changed for this release.
- No user accounts, no data backup beyond your own device/browser, no SLA. It's a personal decision-support tool being used for real, not a hosted product.

### Deployment secrets

The EPC API key is read from Streamlit Cloud's secrets manager when deployed there, falling back to a local `.env` file for local development (`src/epc.py get_epc_key()`). It is never committed to the repository — see `.streamlit/secrets.toml.example` for the format and the README's deployment section for exact setup steps.
