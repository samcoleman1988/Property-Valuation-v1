# Property Investment Analyser

**Status: v1 Beta** — real-use testing, not a finished product. See [RELEASE_NOTES.md](RELEASE_NOTES.md) for what's included and what "Beta" means here.

A Streamlit web app for UK residential property analysis. Paste a Rightmove listing URL to get a valuation, investment score, and downloadable PDF report.

## Valuation Engine

The app uses the **V2 Evidence-Based Valuation** engine by default. This analyses comparable evidence across four independent groups (Direct, Development, Local Market, Area Market), blends them by confidence, and produces a traceable, RICS-surveyor-style explanation of the valuation.

The original V1 weighted-average engine is retained as **Legacy V1 Comparison** and can be selected in the sidebar for regression testing.

**Current production baseline: `v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting`** — see [Validation Status](#validation-status) below and `baselines/MANIFEST.json` for the full version history.

## Validation Status

**Baseline:** `v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting` (2026-07-17)

- ✅ 37-property validation set: 37/37 succeeded, 0 failures
- ✅ Real regional HPI active — comparable prices are adjusted using actual UK House Price Index data, not the flat-rate fallback
- ✅ **CR1 — Single Source of Truth for Recommendations** complete (see prior baseline history)
- ✅ **H0 — displayed confidence matches Evidence Status** complete (see prior baseline history)
- ✅ **Local Market Evidence property-type weighting** complete: Local Market now applies `property_type_weight()` consistently with Direct and Development Evidence, closing a gap where mixed-type comparables (e.g. Detached properties diluting a Semi-Detached subject's local market) contributed at full weight and were invisible to the Evidence Status classifier. Full forensic investigation and validation in `validation_baselines/forensic_reports/` and `baselines/v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting/manifest.json`. Direct Evidence, Development Evidence, comparable retrieval, HPI, geocoding, and V1 are confirmed unchanged.
- **Latest HPI month available:** 2026-04
- **Local Market Evidence Status totals** across the 37-property set: **19 STRONG, 17 WEAK, 1 EMPTY** (post-fix) — 7 properties correctly reclassified STRONG→WEAK by this fix, reflecting real type contamination the classifier was previously blind to
- 7 of 37 properties moved >5% in final V2 fair value as a direct, traced consequence of this fix; 0 final confidence label changes; 2 Recommendation classification changes, both toward the more moderate "Fairly priced"

Full run data: `validation_baselines/lm_type_weighting_fix/before_37properties_2026-07-17.json` / `after_37properties_2026-07-17.json`. See `baselines/v2-evidence-status-fallback-guard-real-hpi-cr1-h0-lm-type-weighting/manifest.json` for what this baseline includes and the full validation methodology.

## Recommended Operating Workflow

For a real purchase decision, follow this sequence rather than trusting the first output:

1. **Paste the Rightmove URL** and let the app do its first-pass extraction.
2. **Manually confirm the house number and postcode** before relying on the valuation for a serious decision — Rightmove sometimes hides the house number, and a wrong postcode can shift the valuation by £100k+.
3. **Add a floor area override** if it's visible on the listing's floorplan but wasn't auto-extracted — this unlocks per-sqm normalisation, which is materially more accurate than whole-property comparison.
4. **Review the Evidence Status and explanation** (Direct / Development / Local Market / Area Market — STRONG / WEAK / FALLBACK_ONLY / EMPTY) before trusting the headline value. A confident-looking number built on FALLBACK_ONLY or EMPTY evidence is not the same as one built on STRONG comparables.
5. **Use calibration feedback after viewing the property or checking the listing in person** — feed back anything that contradicts the tool's assumptions (condition, extensions, boundary issues) so the next analysis on that property reflects reality.

## Deploying (v1 Beta — mobile access)

The app is hosted on **Streamlit Community Cloud** so it's reachable from a phone browser without running Python locally. This was chosen over Render, Railway, Hugging Face Spaces, and a local ngrok tunnel because: it's purpose-built for Streamlit apps (zero Dockerfile/Procfile/port-binding config needed), its free tier is genuinely always-on (unlike Render/Railway free tiers, which sleep), it supports private GitHub repos on the free tier, and — critically — its secrets manager keeps API keys completely out of the git repo (secrets are entered in the Cloud dashboard, not committed as a file). An ngrok tunnel would be simpler to start but requires your own machine to stay on and running, which defeats "check it from my phone while out."

**Local development is unaffected** — `streamlit run app.py` still works exactly as before, reading `EPC_API_KEY` from your local `.env` file.

### One-time setup

These steps need your own GitHub and Streamlit Cloud accounts — they can't be done for you, since they require your own login/OAuth:

1. **Push this repo to GitHub** (private repo is fine — Streamlit Community Cloud supports private repos on the free tier):
   ```bash
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git branch -M main
   git push -u origin main
   ```
2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
3. Click **"New app"**, select this repo, branch `main`, and set the main file path to `app.py`.
4. Before (or after) deploying, open the app's **Settings → Secrets** and paste:
   ```toml
   EPC_API_KEY = "your_base64_encoded_key_here"
   ```
   (same format as `.streamlit/secrets.toml.example` in this repo — that file is a template only, never a real key).
5. Click **Deploy**. You'll get a URL like `https://<your-app>.streamlit.app` — open that on your phone and bookmark it or add it to your home screen.
6. **Optional but recommended:** after each push, add the new commit hash (`git rev-parse HEAD`) to the same Secrets box:
   ```toml
   EPC_API_KEY = "your_base64_encoded_key_here"
   DEPLOYED_COMMIT = "abc1234..."
   ```
   The sidebar's Deployment section reads this to confirm the running instance matches what you just pushed — see "Deployment reliability" below for why this exists.

### Keeping it updated

Any `git push` to the connected branch triggers an automatic redeploy on Streamlit Cloud. In practice, though, a request has landed on a running instance mid-redeploy at least once (see "Deployment reliability" below) — follow the full workflow below for anything beyond a docs/wording-only change:

1. **Push changes.**
2. **Wait for Community Cloud to redeploy** (usually under a minute — the app briefly shows a "rebooting" indicator).
3. **Reboot the app manually** after any change that touches a cross-module function signature or dataclass shape (not needed for pure wording/UI tweaks) — Streamlit Cloud's app menu (⋮) → "Reboot app". This forces a clean process restart rather than relying on the automatic redeploy alone.
4. **Confirm the displayed version/commit** — sidebar → Deployment shows the app version, valuation baseline version, and (if you've set the `DEPLOYED_COMMIT` environment variable after this push) the commit hash. If it doesn't match what you just pushed, the redeploy hasn't landed yet — wait and recheck rather than assuming the code is live.
5. **Run one smoke-test property** through the full flow (paste a URL, let it reach the PDF download button) before treating the deployment as live for real use.

### Deployment reliability

Streamlit Community Cloud redeploys by pulling the new commit into the running container and restarting the process — not an atomic swap. On 2026-07-09, a push that changed `app.py` and `src/transport.py` together in one commit was followed by a live `TypeError` consistent with `app.py`'s new code calling an older version of `assess_location()`. A full repo audit ruled out every structural cause available to check — no duplicate modules, no circular imports, no stale committed bytecode, no inconsistent commits (`app.py` and `transport.py` changed atomically, together, in the same commit). **The most likely explanation is a stale or partially refreshed cloud runtime at the moment of the request — the exact platform-side mechanism is unconfirmed, since the unredacted deployment logs weren't captured.**

Two defensive wrappers in `app.py` (`_ensure_recommendation()`, `_safe_assess_location()`) guard the two integration points this has actually affected — they check the live function's real shape/signature before relying on it, and degrade gracefully instead of crashing the page if it's ever stale. These are kept permanently (the underlying platform behaviour isn't specific to one commit), but this pattern is deliberately **not** applied elsewhere in the codebase without an observed failure — see each function's docstring for the reasoning.

The sidebar's **Deployment** section (app version, baseline version, and an optional `DEPLOYED_COMMIT` environment variable you can set after each push) exists so a mismatch like this is visible at a glance instead of only showing up as a crash.

### Data/cache handling on the hosted deployment

- `data/cache/` (API response cache) and `data/properties.db` (saved-property history) live inside the Cloud container's ephemeral filesystem — they persist between requests while the app is running but are **not backed up** and can be wiped on a redeploy or container restart. This is fine for cache (it just refetches), but don't treat "Saved Properties" on the hosted deployment as permanent storage — if you want a durable record, export/save the PDF report instead.
- `.env`, `data/cache/`, `outputs/`, `*.db`, and `.streamlit/secrets.toml` are all gitignored (see `.gitignore`) — none of them are ever pushed to GitHub or visible in the deployed app's source.

## What it does

1. **Extracts listing details** from a single Rightmove property page (price, address, type, bedrooms, floor area, EPC, etc.)
2. **Finds comparable sold prices** from HM Land Registry Price Paid Data
3. **Adjusts historic prices** using the UK House Price Index
4. **Calculates fair value** using four-group evidence analysis with conservative, balanced, and aggressive cases
5. **Explains why the property is worth what it is** — key drivers, evidence hierarchy, confidence, offer rationale
6. **Generates an offer strategy** (initial offer, max sensible, walk-away)
7. **Assesses extension/planning potential** using the Planning Data API
8. **Runs buy-to-let analysis** with yield and cash flow estimates
9. **Checks location** — generic by default (no personal locations embedded); optionally add your own destinations (home, workplace, a school) in Settings to see distances
10. **Produces a PDF report** with all findings

## Setup

```bash
cd property_value_tool
pip install -r requirements.txt
streamlit run app.py
```

## Data Sources (all free/open)

| Source | Used for |
|--------|----------|
| HM Land Registry Price Paid Data | Comparable sold prices |
| UK House Price Index | Adjusting historic prices to current values |
| Planning Data API | Conservation areas, listed buildings, Green Belt, AONB, Article 4, flood zones |
| postcodes.io | Geocoding postcodes for distance calculations |
| EPC Register (optional) | Energy performance data (requires free API key) |

## Optional: EPC API Key

The EPC register provides floor area data for comparables, enabling per-sqm price
normalisation (more accurate than whole-property comparison alone). It requires a
free API key — the tool works without one, but EPC enrichment will be skipped.

### 1. Get the key

1. Go to https://epc.opendatacommunities.org/
2. Click **"Register"** (top right)
3. Enter your email and accept the terms
4. You will receive an email with your API key (a Base64-encoded string)

### 2. Set the key

**Option A — `.env` file (recommended):**

Create a file called `.env` in the `property_value_tool/` directory:

```
EPC_API_KEY=your_base64_encoded_key
```

The app loads this automatically on startup via `python-dotenv`.

**Option B — Windows environment variable (persistent):**

```powershell
[System.Environment]::SetEnvironmentVariable("EPC_API_KEY", "your_base64_encoded_key", "User")
```

Then restart your terminal and run `streamlit run app.py`.

**Option C — current terminal session only:**

```powershell
$env:EPC_API_KEY = "your_base64_encoded_key"
streamlit run app.py
```

### 3. Confirm the app sees the key

- Open the app in your browser
- Check the **sidebar** — it shows `EPC API key: configured` or `not configured`
- Run an analysis — the Comparable Evidence expander shows the valuation method
  (e.g. "Floor-area normalised: 5 comparables with EPC floor area")

### 4. What happens if the key is missing

- The sidebar shows `EPC API key: not configured` and `EPC enrichment: skipped`
- Valuation falls back to the whole-property method (no per-sqm normalisation)
- A data gap is reported: "EPC enrichment unavailable (no API key)"
- All other analysis (Land Registry comparables, HPI adjustment, planning, BTL,
  scorecard, risk assessment, PDF report) works normally

## Pre-Analysis Checklist

Before running an analysis, especially for high-value decisions:

1. **Confirm the visible address/street.** Check it matches the listing.
2. **Add house number if Rightmove hides it.** Use photos, Google Maps, or Street View to identify it. This unlocks EPC matching and improves confidence by 10-30%.
3. **Add flat/building/block name if relevant.** Flats need a building name for accurate EPC lookup.
4. **Confirm postcode, especially if EPC or comparables look wrong.** A wrong postcode can produce a valuation error of £100k+.
5. **Add floor area manually if listed in floorplan but not extracted.** Floor area enables size-adjusted comparisons.

Enter these in the **Property Identity** and **Manual Overrides** sections of the sidebar.

## Analysis Modes

- **Personal Purchase** — weights location and value highest
- **Buy-to-Let** — weights yield and value highest
- **Both** — balanced weighting across all factors

## Project Structure

```
property_value_tool/
  app.py                        # Streamlit web app
  requirements.txt
  data/
    cache/                      # API response cache
  outputs/
    reports/                    # Generated PDF reports
  src/
    rightmove_parser.py         # Single-listing page parser
    land_registry.py            # Land Registry Price Paid Data
    hpi.py                      # UK House Price Index adjustment
    epc.py                      # EPC register (optional API key)
    planning.py                 # Planning constraints & extension scoring
    extension_potential.py      # Extension cost/upside wrapper
    btl_analysis.py             # Buy-to-let yield & cash flow
    schools.py                  # School data (stub in v1)
    transport.py                # Location & distance assessment
    valuation_engine.py         # V1 valuation engine (legacy)
    valuation_engine_v2.py      # V2 four-group evidence engine (default)
    explanation_engine.py       # RICS-style valuation explanation
    investment_scorecard.py     # Overall investment scoring
    risk_assessor.py            # Risk assessment
    report_generator.py         # PDF report generation
    utils.py                    # Shared utilities & caching
```

## Known Limitations

- Rightmove page structure may change — parser may need updating
- Rental estimates are rule-of-thumb (no free rental comparable API)
- School data is a stub — check manually
- Nearby planning application search is limited
- No machine learning — intentionally rule-based for transparency
- EPC data requires optional API key registration
- **Floor area is still missing for many listings** unless manual identity overrides (house number, building name) are used to unlock EPC matching
- **Generic street names** (e.g. "High Street", "Church Road") can still produce heterogeneous comparables spanning very different property values and ages
- **Cold Land Registry fetches are slow** — the first time a postcode/property-type combination is queried it can take several minutes; cached lookups are near-instant
- **Development/extension appraisal is still basic** — uses Planning Data API constraint flags only, not a full cost/upside model
- **Location scoring is not currently a generic investment metric.** There's no free/no-API-key data source wired up for schools, supermarkets, transport links, flood risk overlays, or deprivation indices, so the tool does not produce a generic Location Quality score — earlier versions embedded the developer's own home postcode and a specific hospital as fixed reference points, which has been removed entirely. Location Assessment shows **"Not assessed"** by default and is excluded from the Investment Scorecard's overall score (not scored as neutral/average — genuinely left out of the weighting) until you add your own destinations.
- **Personal destinations are optional, off by default, and personal-only.** In Personal Purchase or Both mode, Settings → Optional Personal Destinations lets you add up to 3 places (e.g. workplace, a school) to see distance/drive-time figures. This is explicitly labelled "Personal destination scoring" wherever it appears (sidebar, report, PDF) and is never used in the generic investment valuation, fair value, or Investment Scorecard weighting beyond the Location Quality dimension itself.
- **Nearest railway station distance is not calculated** — check National Rail or a map service directly.
- **Future generic location scoring** (schools, rail links, amenities, flood risk, deprivation indices) is a planned enhancement, not yet built — it would need a real free data source per metric, in line with this project's no-invented-data, no-paid-API principles.

## Model Validation Baseline

The V2 engine's behaviour on a fixed 20-property set is snapshotted as a **named baseline**, so future engine changes can be compared against a known-good reference rather than "it feels different now."

### Versioning (no git in this project)

This project isn't a git repository, so versioning is done with a plain file snapshot instead of tags:

- `src/valuation_engine_v2.py` has a `MODEL_VERSION` / `MODEL_VERSION_DATE` constant near the top.
- `baselines/<version>/` holds a snapshot copy of the source files that version depends on (`valuation_engine_v2.py`, `comparable_engine.py`), plus a `manifest.json` describing what changed and any known limitations.
- `baselines/MANIFEST.json` indexes all baselines and marks the current one.

**When you change valuation logic:** bump `MODEL_VERSION` in `valuation_engine_v2.py`, then copy the changed source files into a new `baselines/<new-version>/` folder with an updated `manifest.json`, and re-run the validation baseline below so the new version has its own reference run.

### Rerunning the validation baseline

```bash
cd property_value_tool
python validate_baseline.py
python validate_baseline.py --label some-note   # optional filename suffix
```

This runs the same fixed 20-property set through V1 and V2 and writes two timestamped files to `validation_baselines/`:

- `<timestamp>_baseline_<version>.csv` — one row per property: asking price, V1 value, V2 value, confidence, per-group evidence status/weight/comp count, a coarse `credibility_judgement` heuristic, and a per-property `fetch_timestamp`.
- `<timestamp>_baseline_<version>.json` — the same data plus a `meta` block with run start/end time, success/failure counts, and evidence-status totals across all 24 group-slots (4 groups × 20 properties minus failures).

With warm caches (all 20 postcodes already fetched at least once), a full run takes well under a minute. A cold run — any postcode/property-type combination queried for the first time — can take several minutes per property, since the Land Registry API paginates through matching sales; expect 20–80 minutes if most of the set is cold.

**Note on the valuation date:** comparable age (`age_days`) and HPI-adjusted prices are computed against `datetime.now()` inside `comparable_engine.py` at the moment each property is fetched — not against one frozen date for the whole run. On a run that takes an hour or more, a comparable can silently cross the 3-year (Direct Evidence) or 5-year (Development Evidence) recency cutoff between the first and last property tested. This has already been observed directly in this session (Vyner Road South and Willowbank Road both lost same-street comparables to recency drift between two runs on the same day). `validate_baseline.py` does not change this behaviour — that would be a valuation-logic change — but it logs a `fetch_timestamp` per property and a `note_on_valuation_date` in the JSON `meta` block so drift is visible and explainable rather than silent.

### Interpreting `credibility_judgement`

This column is a coarse label computed **by the validation script only** — it is not part of the valuation engine and does not feed back into any calculation:

- `CREDIBLE` — V2 within ±15% of asking price
- `REVIEW` — V2 within ±35% of asking price
- `QUESTIONABLE` — V2 more than 35% from asking price
- `INSUFFICIENT_EVIDENCE` — V2 returned £0 or confidence label is "None"

## Accuracy

- Never invents missing data — flags it instead
- Shows all assumptions and evidence
- Labels estimates clearly
- Prioritises avoiding overpayment over optimistic upside
- Conservative mode is the default basis for max sensible offer
