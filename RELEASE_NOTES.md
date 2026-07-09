# Release Notes

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
