# Investment Decision Engine - Architecture Redesign

## Mission Statement

This is not a house valuation tool. It is an **investment decision engine** designed to help avoid overpaying for UK residential property while identifying opportunities with the greatest risk-adjusted upside.

Every output should read like advice from an experienced buying agent who is spending your money as carefully as their own.

---

## 1. Critical Review of Existing Modules

### rightmove_parser.py - KEEP, EXPAND

**Does it contribute?** Yes - this is the entry point. Without listing extraction, nothing works.

**Current weaknesses:**
- Extracts data but does not interpret it. A listing description saying "in need of modernisation" is investment-critical information that is currently ignored.
- No extraction of time-on-market, price reduction history, or listing activity signals.
- No extraction of property age, construction type, or condition indicators from description text.
- Photos and floorplan URLs are captured but never analysed (future: room count validation, condition assessment).
- No structured extraction of garden size, parking, garage presence - all of which affect value and extension potential.

**Redesign:** Split into two concerns:
1. `listing_scraper.py` - raw HTML/JSON extraction (keep current logic, fix edge cases)
2. `listing_interpreter.py` - extract investment-relevant signals from description text, key features, and metadata (condition keywords, modernisation indicators, garden/parking mentions, construction period, number of receptions, garage presence)

### land_registry.py - KEEP, MAJOR REWRITE

**Does it contribute?** Yes - comparable evidence is the foundation of any valuation.

**Current weaknesses - this is the most critical failure in v1:**
- Treats all comparables equally. A sale of an identical semi next door last month is weighted the same as a detached house half a mile away three years ago.
- No comparable quality scoring. The API returns raw data; the module passes it through with only property-type filtering and a crude outlier removal.
- No per-sqft normalisation. Without this, comparing a 600sqft flat with an 1100sqft house is meaningless.
- No extraction of street name for same-road matching (the most powerful comparable signal).
- The API returns PAON, SAON, street separately but the module concatenates them and loses the structure.
- No date filtering built into the API query (the `min-date` param was never correctly wired).
- Deduplication is by address+date string which is fragile.
- The progressive search (exact -> sector -> outcode) is correct in principle but stops at 5 results, which may include poor comparables when better ones exist at the next search level.

**Redesign:** This module becomes `comparable_engine.py` - the most important module in the system. Each comparable gets a similarity score (0-100) based on: same street > same postcode > same sector > same outcode, same property type, similar bedrooms, similar floor area, similar age, same tenure, recency of sale. Poor comparables (score < 20) should be shown but clearly flagged as weak. The report must explain WHY each comparable was selected or excluded.

### hpi.py - KEEP, MINOR FIX

**Does it contribute?** Yes - adjusting historic prices to current values is essential.

**Current weaknesses:**
- The UK HPI CSV download URL may not be reliable long-term.
- Falls back to a flat 3% annual growth which is a crude national average.
- Does not use regional or local authority level HPI data even when available from the same API.
- No awareness of market cycle position (are we in a rising or falling market?).

**Redesign:** Keep the core logic. Add local authority level HPI lookup. Add a "market direction" indicator (rising/flat/falling based on recent HPI trend). The flat-rate fallback is acceptable as a last resort but should be flagged prominently.

### epc.py - KEEP, EXPAND ROLE

**Does it contribute?** Partially. Currently just fetches certificates.

**Current weaknesses:**
- Requires an API key that most users won't have registered.
- The EPC impact assessment uses arbitrary energy cost estimates.
- Does not cross-reference EPC floor area with listing floor area (a powerful validation check).
- EPC data includes property age band, construction type, and floor area which are valuable for comparable matching but are not exposed.

**Redesign:** EPC becomes a primary data enrichment source, not just an energy rating lookup. Even without the API, the module should structure what we know from the listing's stated EPC rating. With the API, it becomes a floor area validator and property age indicator.

### planning.py - KEEP, MAJOR REWRITE

**Does it contribute?** The constraint checks are valuable. The extension scoring is too simplistic.

**Current weaknesses:**
- Extension scores are pure property-type lookups with constraint penalties. They do not consider the actual property (garden size, existing footprint, roof type).
- No nearby planning application search is implemented - the most valuable evidence for planning confidence.
- Build cost estimates use flat per-sqm rates that ignore regional variation, specification level, or access complexity.
- The "uplift percentage" approach (8-25% of current value) is not how developers think. Developers think in GDV (Gross Development Value) and work backwards.
- No concept of permitted development rights vs full planning permission.
- Financial calculations don't include professional fees itemised (architect, structural engineer, building regs, planning application fee, party wall surveyor).

**Redesign:** Split into:
1. `constraints.py` - planning constraint lookups (conservation, listed, Green Belt, AONB, Article 4, flood, TPO)
2. `development_appraisal.py` - thinks like a developer: what can be built (permitted development rules + constraint check), what will it cost (itemised), what will the finished property be worth (GDV from comparables of extended properties), what is the developer profit/ROI/payback.

The development appraisal should use the **residual valuation method**: GDV minus build costs minus fees minus contingency minus profit margin = what the opportunity is worth.

### extension_potential.py - REMOVE, MERGE INTO development_appraisal.py

**Does it contribute?** Duplicates planning.py with a thin wrapper. Adds itemised build costs but they are simplistic.

**Redesign:** Absorbed into the new `development_appraisal.py`.

### btl_analysis.py - KEEP, REWRITE

**Does it contribute?** Yes, but the rental estimates are circular - it estimates rent FROM yield benchmarks applied to the purchase price, then calculates yield from those estimates. This is mathematically guaranteed to return the benchmark yield regardless of the property.

**Current weaknesses:**
- Circular rental estimation makes the entire BTL module unreliable.
- No actual rental comparable data. This is the module's fundamental problem.
- Mortgage assumptions are hardcoded (75% LTV, 5% rate) with no user configurability.
- Does not account for stamp duty, legal fees, or refurbishment costs in the total investment calculation.
- Does not calculate return on capital employed (ROCE), which is what matters for leveraged BTL.
- No Section 24 tax impact modelling.

**Redesign:** Honest about what it can and cannot do. Without free rental data, it should present user-input rental figures or clearly flagged estimates based on the VOA (Valuation Office Agency) data if accessible. Calculate proper ROCE, not just gross yield. Include stamp duty (including the additional 5% surcharge), legal fees, and refurbishment as part of the total capital deployed.

### schools.py - KEEP AS STUB, LOW PRIORITY

**Does it contribute?** Barely. It's a placeholder that tells users to check manually.

**Redesign:** Keep the stub. School catchment affects value significantly but there is no free API that provides quality + catchment data together. This is a future module. The design should reserve a clear interface for it.

### transport.py - KEEP, EXPAND

**Does it contribute?** Yes. Distance calculations work correctly.

**Current weaknesses:**
- Only calculates straight-line distance, not drive time or public transport time.
- Station search is unimplemented.
- No rail journey time estimation.
- Location scoring is a crude distance-based formula.

**Redesign:** Keep geocoding and distance calculations. Add station proximity using the NaPTAN dataset (free, open). Separate "value" (what the market pays for this location) from "desirability" (does this location work for your life). Add crime data from police.uk API (free). Add flood risk from Environment Agency (free).

### valuation.py - MAJOR REWRITE (this is the heart of the system)

**Does it contribute?** Yes, but the methodology is too simplistic for investment decisions.

**Current weaknesses - these are fundamental:**
1. **Treats all comparables equally within their time-weight.** A semi on the same street should dominate; a detached house two postcodes away should barely register.
2. **Uses percentiles of raw prices as the three valuation cases.** This means the "conservative" value is just the 25th percentile of whatever comparables happened to be found. If the comparables include a mix of 2-bed terraces and 4-bed detacheds, the 25th percentile is meaningless.
3. **No per-sqft normalisation.** Without floor area adjustment, the valuation cannot account for size differences between comparables and the subject property.
4. **The offer strategy is mechanical.** Initial offer = conservative value, max = balanced, walk-away = balanced + 5%. A real buying agent considers market conditions, vendor motivation, time on market, competing interest, and property condition.
5. **Confidence scoring counts inputs rather than measuring evidence quality.** Having 10 poor comparables scores higher than having 3 excellent ones.
6. **No adjustment for condition, specification, or features.** A recently renovated house and a house "in need of modernisation" at the same postcode with the same bedrooms are treated identically.
7. **The "balanced" valuation defaults to the asking price when no comparables are found.** This makes the tool agree with the vendor when it has no evidence - exactly the wrong default for an overpayment-avoidance tool.

**Redesign: The Layered Evidence Model**

The new valuation engine should work like an experienced surveyor:

**Step 1: Gather evidence** - fetch all comparables, score each one for quality.

**Step 2: Normalise** - adjust each comparable to a per-sqft (or per-sqm) basis where floor area is known. Where floor area is unknown, use bedroom count as a crude proxy.

**Step 3: Apply HPI adjustment** - bring historic prices to current-date equivalent.

**Step 4: Weight by quality** - excellent comparables (same street, same type, recent, similar size) dominate. Poor comparables contribute little. Each weight is explainable.

**Step 5: Calculate base fair value** - weighted average of normalised, adjusted comparables, then scale back to the subject property's floor area.

**Step 6: Apply adjustments** - explicit, traceable adjustments for:
- Condition (needs modernisation: -10 to -20%, recently refurbished: +5 to +10%)
- Tenure (leasehold discount based on remaining lease length)
- EPC (below-average rating: energy cost capitalisation discount)
- Parking (no off-street parking in suburban area: -3 to -5%)
- Garden (no garden in family-home area: -5 to -10%)
- Specific positives/negatives extracted from listing description

Each adjustment must be shown in the report with its reasoning and £ impact.

**Step 7: Three cases** - Conservative uses lower-quality-adjusted comparables and applies larger condition/risk discounts. Balanced uses the central estimate. Aggressive uses the most favourable evidence.

**Step 8: Offer strategy** - considers the asking price gap, time on market, market direction, vendor motivation signals, and competing stock to produce negotiation-aware offer recommendations.

### scoring.py - REWRITE

**Does it contribute?** The concept is right but the implementation is too shallow.

**Current weaknesses:**
- Value score is derived solely from asking-vs-fair gap percentage.
- Planning score is just the max extension score passed through.
- Weights are hardcoded with no transparency about why.
- The verdict and recommendation are template strings with no real reasoning.

**Redesign:** Becomes the **Investment Scorecard** - eight scored dimensions, each with an explanation of WHY that score was given:
1. Fair value (is the price right?)
2. Negotiation opportunity (how much room to negotiate?)
3. Development opportunity (can value be added through works?)
4. Planning confidence (how certain is the development opportunity?)
5. Rental potential (does it work as BTL?)
6. Resale potential (will it sell easily in future?)
7. Location quality (schools, transport, amenities, safety)
8. Investment risk (what could go wrong?)

### report_generator.py - KEEP, EXPAND

**Does it contribute?** Yes. PDF generation works.

**Current weaknesses:**
- The report structure follows the modules rather than telling an investment story.
- No comparable evidence table showing WHY each comparable was selected.
- No visual price positioning (where does this property sit relative to evidence?).
- The recommendation section is a single paragraph rather than structured buying advice.

**Redesign:** The report should be structured as an investment decision document:
1. One-line verdict
2. Executive summary (3-5 sentences a buying agent would say)
3. The Numbers (asking vs fair value, three cases, offer strategy)
4. The Evidence (comparable table with quality scores and selection reasoning)
5. The Opportunity (development appraisal with GDV/cost/profit)
6. The Risks (dedicated risk register)
7. The Location
8. BTL Assessment (if applicable)
9. Investment Scorecard (the eight dimensions)
10. What I Would Do (structured buying recommendation)

### utils.py - KEEP, MINOR EXPANSION

**Does it contribute?** Yes. Caching and utilities are essential infrastructure.

**Redesign:** Add a property database layer (SQLite) for tracking analysed properties, offers, outcomes.

### app.py - KEEP, RESTRUCTURE

**Does it contribute?** Yes. Streamlit is the right choice for rapid prototyping.

**Redesign:** Add multi-page navigation, property database browser, comparison view. But do not over-invest in UI until the analytical engine is solid.

---

## 2. Revised System Architecture

```
                    +------------------+
                    |    Streamlit     |
                    |    Frontend      |
                    +--------+---------+
                             |
                    +--------+---------+
                    |   Orchestrator   |  (coordinates the analysis pipeline)
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
+---------+------+  +--------+-------+  +-------+--------+
| Data Gathering |  | Analysis Engine|  | Output Layer   |
+----------------+  +----------------+  +----------------+
| listing_scraper|  | valuation_engine|  | report_gen     |
| listing_interp |  | dev_appraisal  |  | scorecard      |
| land_registry  |  | btl_analysis   |  | database       |
| hpi            |  | risk_assessor  |  +----------------+
| epc            |  | market_context |
| constraints    |  +----------------+
| location       |
| market_data    |
+----------------+

         +------------------+
         | Infrastructure   |
         +------------------+
         | utils / cache    |
         | property_db      |
         | config           |
         +------------------+
```

### Key architectural principles:
1. **Each module produces a typed result dataclass** with both values and confidence/source metadata.
2. **Every number carries provenance** - where did it come from, how was it derived, what assumptions were made.
3. **Modules communicate through the orchestrator**, not directly. This allows future modules to be added without rewiring.
4. **The property database is append-only** - every analysis is saved, building a proprietary dataset over time.
5. **Configuration is externalised** - build costs, yield benchmarks, adjustment factors live in config files, not hardcoded in logic.

---

## 3. Improved Valuation Methodology

### Evidence Hierarchy (weighted contribution to final value)

| Layer | Weight | Source | Current Status |
|-------|--------|--------|----------------|
| Comparable sold evidence | 40% | Land Registry PPD | Working but unscored |
| Current market evidence | 25% | Active listings, reductions | NOT IMPLEMENTED |
| Development opportunity | 15% | Planning + build costs | Simplistic |
| Location quality | 10% | Distance, schools, crime | Partial |
| Risk adjustment | 10% | Constraints, market, property | NOT IMPLEMENTED |

### Comparable Scoring Model

Each comparable receives a quality score (0-100):

| Factor | Max Points | Scoring |
|--------|-----------|---------|
| Proximity | 25 | Same street: 25, Same postcode: 20, Same sector: 12, Same outcode: 5 |
| Property type match | 20 | Exact match: 20, Same category: 12, Different: 3 |
| Size similarity | 15 | Within 10%: 15, Within 20%: 10, Within 30%: 5, Beyond: 2 |
| Recency | 15 | Under 6 months: 15, Under 1 year: 12, Under 2 years: 8, Under 3 years: 5, Older: 2 |
| Bedroom match | 10 | Exact: 10, +/-1: 6, +/-2: 2 |
| Tenure match | 10 | Same: 10, Different: 3 |
| Condition match | 5 | Similar: 5, Different: 2, Unknown: 3 |

**Comparable classification:**
- 70-100: Excellent (dominates valuation)
- 50-69: Good (significant weight)
- 30-49: Fair (moderate weight)
- 10-29: Weak (minimal weight, shown for context)
- 0-9: Irrelevant (excluded, or shown as "excluded because...")

### Adjustment Schedule

Explicit, traceable adjustments applied after comparable-based value:

| Adjustment | Range | Trigger |
|-----------|-------|---------|
| Modernisation needed | -8% to -20% | Description keywords: "updating", "modernisation", "project", "potential" |
| Recently refurbished | +3% to +8% | Description keywords: "refurbished", "renovated", "new kitchen/bathroom" |
| No off-street parking | -2% to -5% | Suburban/rural property with no parking mentioned |
| No garden | -3% to -8% | House with no garden or "courtyard only" |
| Short lease (<80 years) | -5% to -30% | Leasehold with stated or estimated short lease |
| Poor EPC (E/F/G) | -2% to -8% | EPC rating below D, capitalised energy cost differential |
| Period features premium | +2% to +5% | Listed/period property with original features |
| New build premium erosion | -5% to -15% | Resale of recent new build (loses new-build premium) |

Each adjustment shown in report as: "Adjustment: -£15,000 (-5%) for modernisation needed. Reason: listing describes property as 'in need of updating throughout'. Range: £9,000-£24,000."

### Offer Strategy Model

The offer should account for:

```
Initial Offer = Conservative Value - Negotiation Buffer
  where Negotiation Buffer considers:
    - Time on market (longer = more room)
    - Recent reductions (signals vendor flexibility)
    - Market direction (falling = more room)
    - Competing stock (more competition = more room)
    - Chain position (no chain = less pressure to overpay)

Max Sensible Offer = Balanced Value
  (never pay more than evidence-based fair value)

Walk-Away Price = Balanced Value + 3%
  (absolute ceiling, only if strong personal/strategic reason)
```

---

## 4. Data Source Map

| Data Source | URL/API | Cost | Current Status | Data Provided |
|-------------|---------|------|----------------|---------------|
| Land Registry PPD | landregistry.data.gov.uk | Free | WORKING | Sold prices, dates, addresses, property types |
| UK House Price Index | landregistry.data.gov.uk | Free | WORKING | Regional price indices for time adjustment |
| postcodes.io | api.postcodes.io | Free | WORKING | Geocoding, lat/lon for distance calculations |
| Planning Data API | planning.data.gov.uk | Free | PARTIAL | Conservation, listed, Green Belt, AONB, Article 4 |
| EPC Register | epc.opendatacommunities.org | Free (key required) | OPTIONAL | Energy ratings, floor areas, property age, construction type |
| Police.uk API | data.police.uk | Free | NOT IMPLEMENTED | Local crime rates by category |
| Environment Agency Flood | environment.data.gov.uk | Free | NOT IMPLEMENTED | Flood risk zones |
| NaPTAN | data.gov.uk | Free | NOT IMPLEMENTED | Railway stations, bus stops with coordinates |
| Ofsted/DfE | gov.uk | Free (scrape) | NOT IMPLEMENTED | School ratings and locations |
| VOA Council Tax | voa.gov.uk | Free (limited) | NOT IMPLEMENTED | Council tax bands (proxy for relative values) |
| Rightmove listing | rightmove.co.uk | Free (single page) | WORKING | Property details from pasted URL |

### Data sources that cannot be freely automated (design placeholder only):
- Rental comparables (Rightmove/OpenRent lettings - no free API)
- Active competing listings (Rightmove search - no free API, user could paste)
- Price reduction history (not freely available programmatically)
- Time on market (partially available from listing page)

---

## 5. Risk Register

### Investment Risks the Tool Should Assess

| Risk Category | Risk | Data Source | Implementation |
|--------------|------|-------------|----------------|
| Planning | Listed building | Planning Data API | v1 WORKING |
| Planning | Conservation area | Planning Data API | v1 WORKING |
| Planning | Green Belt | Planning Data API | v1 WORKING |
| Planning | AONB | Planning Data API | v1 WORKING |
| Planning | Article 4 | Planning Data API | v1 WORKING |
| Planning | Tree Preservation Orders | Planning Data API | v2 |
| Environmental | Flood risk (Zone 2/3) | Environment Agency | v2 |
| Environmental | Japanese knotweed | Not freely available | Placeholder |
| Environmental | Contaminated land | Not freely available | Placeholder |
| Structural | Subsidence risk | British Geological Survey | v3 |
| Market | Price falling market | HPI trend | v2 |
| Market | Low liquidity (long time to sell) | Not freely available | Placeholder |
| Market | Oversupply in area | Not freely available | Placeholder |
| Legal | Short lease (< 80 years) | Listing/EPC | v2 |
| Legal | Restrictive covenants | Not freely available | Placeholder |
| Legal | Flying freehold | Not freely available | Placeholder |
| Location | Busy road frontage | Not freely available | Placeholder - user flag |
| Location | Commercial/industrial neighbours | Not freely available | Placeholder - user flag |
| Location | Future nearby development | Planning applications | v3 |
| Property | Non-standard construction | EPC/listing description | v2 |
| Property | Single skin/timber frame | EPC data | v2 |
| Property | Flat roof | Listing description | v2 |
| BTL | EPC below E (illegal to let) | EPC | v1 WORKING |
| BTL | Leasehold restrictions on letting | Listing | v1 PARTIAL |
| Valuation | Low comparable count | Self-assessed | v1 WORKING |
| Valuation | High comparable variance | Self-assessed | v1 WORKING |
| Valuation | Unique property (low confidence) | Self-assessed | v2 |

### Tool Risks (things that could make the tool give bad advice)

| Risk | Mitigation |
|------|-----------|
| Land Registry data lag (2-3 months) | Flag data currency in report |
| Rightmove page structure changes | Robust parser with fallback; warn on extraction failure |
| HPI data unavailable | Fallback to national average; flag prominently |
| Comparable pool too small | Progressive search widening; explicit confidence reduction |
| Comparable pool contaminated (wrong property types) | Quality scoring; show selection reasoning |
| User enters wrong overrides | Validation ranges; sanity checks |
| Market moves between analysis and offer | Date-stamp all evidence; advise on currency |

---

## 6. Development Roadmap

### Phase 1: Foundation Rewrite (Core Engine)
Priority: CRITICAL. Do this before adding any new features.

1. **Rewrite `land_registry.py` as `comparable_engine.py`**
   - Preserve structured address fields (PAON, street, town) separately
   - Implement comparable quality scoring (0-100)
   - Add same-street detection
   - Add bedroom-count matching
   - Each comparable carries its quality score and selection reasoning

2. **Rewrite `valuation.py` as `valuation_engine.py`**
   - Implement quality-weighted valuation
   - Add per-sqft normalisation (where floor area known)
   - Add explicit adjustment schedule (condition, tenure, parking, garden, EPC)
   - Three-case model uses evidence quality bands, not raw percentiles
   - Offer strategy considers time on market and market direction
   - Every number traceable: "£X because [reason]"

3. **Add `property_db.py`**
   - SQLite database for storing every analysed property
   - Schema: property details, valuation results, comparables used, scores, timestamps
   - Comparison queries: "show me all properties I've analysed in CH42"

4. **Add `config.py`**
   - Externalise all assumptions: build costs, adjustment ranges, yield benchmarks
   - YAML or JSON config file users can review and override
   - Reference locations (OX33 1RT, JR Hospital) in config, not hardcoded

### Phase 2: Evidence Expansion
5. **Add `listing_interpreter.py`**
   - Parse listing description for condition keywords
   - Extract garden/parking/garage signals
   - Estimate property age from description and key features
   - Flag "project" properties vs "move-in ready"

6. **Rewrite `planning.py` as `constraints.py` + `development_appraisal.py`**
   - Constraints: clean separation of constraint lookups
   - Development appraisal: residual valuation method
   - GDV from comparables of similar-but-extended properties
   - Itemised cost schedule (build, architect, structural, building regs, party wall, contingency)
   - Developer ROI and payback calculation

7. **Expand `transport.py` as `location.py`**
   - Add police.uk crime API
   - Add Environment Agency flood risk
   - Add NaPTAN station data
   - Separate value-impact score from personal-desirability score

### Phase 3: Investment Intelligence
8. **Add `market_context.py`** (placeholder with manual input)
   - Structure for: competing listings count, recent reductions, average time on market
   - User can paste this data manually until automated sources are available
   - Feeds into offer strategy

9. **Rewrite `scoring.py` as `investment_scorecard.py`**
   - Eight scored dimensions with explanations
   - Overall investment score
   - Structured recommendation engine

10. **Rewrite `btl_analysis.py`**
    - Break the circular yield calculation
    - Add stamp duty calculator (including 5% surcharge)
    - Add ROCE calculation
    - User-input rental figure with benchmark comparison
    - Section 24 tax impact note

11. **Expand `report_generator.py`**
    - Restructure as investment decision document
    - Add comparable evidence table with quality scores
    - Add adjustment waterfall (base value + adjustments = fair value)
    - Add "What I Would Do" section

### Phase 4: Database and Comparison
12. **Property database UI**
    - Browse previously analysed properties
    - Compare two or more properties side by side
    - Record offers made and outcomes
    - Track price reductions over time

### Phase 5: Future Modules (design interfaces now, implement later)
- Zoopla integration
- Auction property analysis
- HMO analysis
- Holiday let analysis
- Mortgage affordability calculator
- Portfolio analysis
- Refurbishment cost estimator
- AI photo analysis (condition assessment from listing photos)

---

## 7. Code That Must Be Rewritten Before Proceeding

### MUST rewrite (blocking further development):

1. **`land_registry.py`** - The comparable engine is the foundation. Without quality-scored comparables, every downstream calculation is unreliable. The current module passes through raw data with no intelligence. Rewrite as `comparable_engine.py`.

2. **`valuation.py`** - The valuation methodology is too simplistic for investment decisions. Weighted percentiles of undifferentiated comparables is not how surveyors or developers value property. Rewrite as `valuation_engine.py` with the layered evidence model.

3. **`scoring.py`** - The scoring system is shallow and the recommendations are template strings. Rewrite as `investment_scorecard.py` with eight explained dimensions.

### SHOULD rewrite (important but not blocking):

4. **`planning.py`** - The extension scoring is pure lookup tables. Split into `constraints.py` + `development_appraisal.py` and implement the residual valuation method for development opportunity.

5. **`btl_analysis.py`** - The circular yield calculation actively produces misleading results. Fix the methodology even if rental data sources remain limited.

### CAN keep (functional, improve incrementally):

6. **`rightmove_parser.py`** - Works for its current purpose. Add `listing_interpreter.py` alongside it.
7. **`hpi.py`** - Core logic is sound. Add regional granularity.
8. **`transport.py`** - Distance calculations work. Expand data sources.
9. **`report_generator.py`** - PDF generation works. Restructure report sections after engine rewrite.
10. **`utils.py`** - Solid infrastructure. Add property database support.
11. **`app.py`** - Functional UI. Restructure after engine rewrite.

### REMOVE:

12. **`extension_potential.py`** - Thin wrapper that duplicates `planning.py`. Merge into `development_appraisal.py`.
13. **`schools.py`** - Empty stub adding no value. Reserve the interface in `location.py`.

---

## Summary

The current codebase is a working prototype that fetches real data and produces a report. But it makes investment decisions based on undifferentiated comparable averages with no quality assessment, no condition adjustment, no market context, and circular BTL calculations. The confidence scoring counts inputs rather than measuring evidence quality.

The redesign centres on three principles:

1. **Every comparable is scored for quality.** The best evidence dominates. Poor evidence is shown but contributes little.

2. **Every adjustment is explicit and traceable.** No hidden factors. The report shows: "Base value £X, adjusted -£Y for modernisation, -£Z for short lease = Fair value £W."

3. **The output is investment advice, not a valuation certificate.** The tool should say: "This property is overpriced by approximately £30,000 based on 8 comparable sales. The strongest evidence is 4 Acacia Avenue which sold for £X six months ago - same street, same type, similar size. I would open at £Y and walk away above £Z. The main risk is [specific risk]. The main opportunity is [specific opportunity]."
