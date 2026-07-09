"""Property Investment Decision Engine — Streamlit App.

Paste a Rightmove URL to get a detailed investment analysis and PDF report.
"""

import os
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from pathlib import Path

from src.rightmove_parser import parse_listing, PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.valuation_engine_v2 import run_v2_valuation
from src.explanation_engine import explain_valuation
from src.investment_scorecard import calculate_scorecard
from src.risk_assessor import assess_risks
from src.planning import assess_planning
from src.btl_analysis import assess_btl
from src.transport import assess_location
from src.report_generator import generate_report
from src.epc import estimate_epc_impact, lookup_subject_floor_area, get_epc_key
from src.property_db import save_property, get_all_properties
from src.utils import format_currency, format_pct

st.set_page_config(
    page_title="Property Investment Decision Engine",
    page_icon="🏠",
    layout="wide",
)

st.title("Property Investment Decision Engine")
st.caption(
    "Paste a Rightmove listing URL. Get a scored valuation, investment scorecard, "
    "risk assessment, and offer strategy — all from free/open data."
)

# --- Sidebar: Settings ---
with st.sidebar:
    st.header("Settings")
    mode = st.selectbox(
        "Analysis Mode",
        ["Personal Purchase", "Buy-to-Let", "Both"],
        index=0,
    )
    mode_key = {"Personal Purchase": "personal", "Buy-to-Let": "btl", "Both": "both"}[mode]

    region = st.selectbox(
        "HPI Region",
        ["England", "North West", "South East", "Oxfordshire", "Wirral", "London",
         "East Midlands", "West Midlands", "South West", "East of England", "Wales"],
        index=0,
    )

    valuation_engine = st.selectbox(
        "Valuation Engine",
        ["V2 Evidence-Based Valuation", "Legacy V1 Comparison"],
        index=0,
        help="V2 is the recommended engine using four-group evidence analysis. Legacy V1 runs the original weighted-average engine for comparison.",
    )
    use_v2 = valuation_engine == "V2 Evidence-Based Valuation"

    st.divider()
    st.subheader("Property Identity")
    st.caption(
        "If Rightmove hides the house number or you can identify it from "
        "photos/Google Maps, enter it here to improve EPC matching and comparables."
    )
    override_house_number = st.text_input(
        "House/Flat Number",
        help="e.g. '22', 'Flat 4', '14A'. Improves EPC match when Rightmove omits it.",
    )
    override_building_name = st.text_input(
        "Building/Block Name",
        help="e.g. 'Ingestre Court', 'Maple House'. For flats/apartments.",
    )
    override_street = st.text_input(
        "Street Name Override",
        help="Override the street extracted from Rightmove address.",
    )
    override_property_name = st.text_input(
        "Property Name",
        help="e.g. 'Rose Cottage'. For named properties without a number.",
    )
    override_estate = st.text_input(
        "Development/Estate Name",
        help="e.g. 'Thorney Leys', 'Yewdale Park'. Helps Development Evidence matching.",
    )

    st.divider()
    st.subheader("Pre-Analysis Checklist")
    st.markdown(
        "1. Confirm the visible address/street.\n"
        "2. Add house number if Rightmove hides it.\n"
        "3. Add flat/building/block name if relevant.\n"
        "4. Confirm postcode, especially if EPC or comparables look wrong.\n"
        "5. Add floor area manually if listed in floorplan but not extracted."
    )

    st.divider()
    st.subheader("Manual Overrides")
    st.caption("Use these if automatic extraction fails or to correct values.")
    override_price = st.number_input("Override Asking Price (GBP)", min_value=0, value=0, step=5000)
    override_postcode = st.text_input("Override Postcode")
    override_type = st.selectbox(
        "Override Property Type",
        ["", "Detached House", "Semi-Detached House", "Terraced House",
         "End of Terrace", "Flat", "Bungalow", "Cottage", "Maisonette"],
        index=0,
    )
    override_beds = st.number_input("Override Bedrooms", min_value=0, max_value=10, value=0)
    override_sqft = st.number_input("Override Floor Area (sq ft)", min_value=0, value=0, step=50)
    override_tenure = st.selectbox("Override Tenure", ["", "Freehold", "Leasehold", "Share of Freehold"], index=0)

    st.divider()
    st.subheader("Data Sources")
    _epc_key = bool(get_epc_key())
    st.caption(f"EPC API key: **{'configured' if _epc_key else 'not configured'}**")
    st.caption(f"EPC enrichment: **{'enabled' if _epc_key else 'skipped'}**")

    st.divider()
    st.subheader("Saved Properties")
    saved = get_all_properties()
    if saved:
        st.caption(f"{len(saved)} properties saved")
        for prop in saved[:10]:
            label = f"{prop['address'][:40]}... | {format_currency(prop['asking_price'])}"
            st.caption(label)
    else:
        st.caption("No saved properties yet.")

# --- Main: URL Input ---
url = st.text_input(
    "Rightmove Listing URL",
    placeholder="https://www.rightmove.co.uk/properties/...",
)

if st.button("Analyse Property", type="primary", disabled=not url):
    if "rightmove.co.uk" not in url:
        st.error("Please enter a valid Rightmove URL.")
        st.stop()

    # Step 1: Parse listing
    with st.status("Extracting listing details...", expanded=True) as status:
        listing = parse_listing(url)

        # Apply identity overrides (keep original Rightmove data intact)
        if override_house_number:
            listing.override_house_number = override_house_number.strip()
            listing.overrides_applied.append(f"House/flat number: {listing.override_house_number}")
        if override_building_name:
            listing.override_building_name = override_building_name.strip()
            listing.overrides_applied.append(f"Building name: {listing.override_building_name}")
        if override_street:
            listing.override_street_name = override_street.strip()
            listing.overrides_applied.append(f"Street name: {listing.override_street_name}")
        if override_property_name:
            listing.override_property_name = override_property_name.strip()
            listing.overrides_applied.append(f"Property name: {listing.override_property_name}")
        if override_estate:
            listing.override_estate_name = override_estate.strip()
            listing.overrides_applied.append(f"Estate/development: {listing.override_estate_name}")

        # Apply value overrides
        if override_price > 0:
            listing.asking_price = override_price
        if override_postcode:
            listing.override_postcode = override_postcode.strip()
            listing.overrides_applied.append(f"Postcode: {listing.override_postcode} (original: {listing.postcode})")
            listing.postcode = override_postcode
        if override_type:
            listing.property_type = override_type
        if override_beds > 0:
            listing.bedrooms = override_beds
        if override_sqft > 0:
            listing.floor_area_sqft = override_sqft
            listing.floor_area_sqm = round(override_sqft * 0.092903, 1)
            listing.floor_area_source = "Manual"
        if override_tenure:
            listing.tenure = override_tenure

        if listing.extraction_warnings:
            for w in listing.extraction_warnings:
                st.warning(w)

        if not listing.asking_price:
            st.error("Could not determine asking price. Please set it in the sidebar overrides.")
            st.stop()
        if not listing.postcode:
            st.error("Could not determine postcode. Please set it in the sidebar overrides.")
            st.stop()

        # Subject floor area: EPC lookup if not already known
        if not listing.floor_area_sqm and listing.postcode:
            # Build the best possible address hint for EPC matching
            epc_address = listing.effective_address_first_line
            epc_street = listing.effective_street
            epc_postcode = listing.effective_postcode

            epc_sqm, epc_rating, epc_detail = lookup_subject_floor_area(
                postcode=epc_postcode,
                address=epc_address,
                street=epc_street,
            )
            if epc_sqm > 0:
                listing.floor_area_sqm = epc_sqm
                listing.floor_area_sqft = round(epc_sqm * 10.7639, 1)
                listing.floor_area_source = "EPC"
                if epc_rating and not listing.epc_rating:
                    listing.epc_rating = epc_rating

        if not listing.floor_area_source:
            listing.floor_area_source = "Unknown" if not listing.floor_area_sqm else "Rightmove"

        floor_label = ""
        if listing.floor_area_sqm:
            floor_label = f" | {listing.floor_area_sqm:,.0f} sqm ({listing.floor_area_source})"

        st.write(f"**{listing.address or 'Address unknown'}**")
        st.write(f"{listing.property_type} | {listing.bedrooms} bed | {listing.tenure}{floor_label}")
        st.write(f"Asking: **{format_currency(listing.asking_price)}** | Postcode: **{listing.postcode}**")
        if listing.overrides_applied:
            st.info("**Manual identity overrides:** " + " | ".join(listing.overrides_applied))
        status.update(label="Listing extracted", state="complete")

    # Step 2: Interpret listing text
    with st.status("Interpreting listing text...", expanded=False) as status:
        signals = interpret_listing(
            description=listing.description or "",
            key_features=listing.key_features if hasattr(listing, "key_features") else [],
            property_type=listing.property_type or "",
        )
        n_adj = len(signals.adjustments)
        status.update(
            label=f"Listing interpreted — condition: {signals.condition_label}, {n_adj} adjustment(s)",
            state="complete",
        )

    # Step 3: Fetch and score comparables
    with st.status("Fetching comparable evidence from Land Registry...", expanded=True) as status:
        street = listing.effective_address_first_line

        evidence = fetch_and_score_comparables(
            postcode=listing.effective_postcode,
            property_type=listing.property_type or "",
            bedrooms=listing.bedrooms or 0,
            floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "",
            latitude=listing.latitude or 0,
            longitude=listing.longitude or 0,
            street=street,
        )
        status.update(
            label=f"Comparables: {evidence.total_scored} scored ({evidence.excellent_count} excellent, {evidence.good_count} good)",
            state="complete",
        )

    # Step 4: Valuation
    with st.status("Calculating valuation...", expanded=True) as status:
        valuation = calculate_valuation(
            asking_price=listing.asking_price,
            evidence=evidence,
            signals=signals,
            floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "",
            region=region,
        )
        status.update(
            label=f"Valuation complete — {valuation.confidence_label} confidence",
            state="complete",
        )

    # Step 4b: V2 Diagnostic (if selected)
    v2_result = None
    v2_explanation = None
    if use_v2:
        with st.status("Running V2 evidence-based valuation...", expanded=True) as status:
            try:
                v2_result = run_v2_valuation(evidence, listing)
                v2_explanation = explain_valuation(v2_result, listing)
                status.update(
                    label=f"V2 valuation: {format_currency(v2_result.final.fair_value_balanced)} | {v2_result.final.confidence_label} confidence",
                    state="complete",
                )
            except Exception as e:
                v2_result = None
                v2_explanation = None
                status.update(label=f"V2 valuation failed: {e}", state="error")

    # Step 5: Planning / Extension
    with st.status("Assessing planning constraints...", expanded=False) as status:
        try:
            planning_result = assess_planning(
                postcode=listing.postcode,
                property_type=listing.property_type,
                bedrooms=listing.bedrooms or 0,
                current_value=valuation.fair_value_balanced or listing.asking_price,
                latitude=listing.latitude or 0,
                longitude=listing.longitude or 0,
            )
            if hasattr(planning_result, "to_dict"):
                planning_dict = planning_result.to_dict()
            elif isinstance(planning_result, dict):
                planning_dict = planning_result
            else:
                planning_dict = {}
        except Exception:
            planning_dict = {}
        status.update(label="Planning assessment complete", state="complete")

    # Step 6: BTL (if relevant)
    btl_dict = {}
    if mode_key in ("btl", "both"):
        with st.status("Running BTL analysis...", expanded=False) as status:
            try:
                btl = assess_btl(
                    asking_price=listing.asking_price,
                    fair_value=valuation.fair_value_balanced,
                    postcode=listing.postcode,
                    property_type=listing.property_type,
                    bedrooms=listing.bedrooms,
                    epc_rating=listing.epc_rating if hasattr(listing, "epc_rating") else "",
                    tenure=listing.tenure,
                )
                btl_dict = btl.to_dict() if hasattr(btl, "to_dict") else {}
            except Exception:
                btl_dict = {}
            status.update(label="BTL analysis complete", state="complete")

    # Step 7: Location
    with st.status("Assessing location...", expanded=False) as status:
        location = assess_location(
            postcode=listing.postcode,
            latitude=listing.latitude or 0,
            longitude=listing.longitude or 0,
        )
        location_dict = location.to_dict()
        status.update(label="Location assessment complete", state="complete")

    # Step 8: Investment Scorecard
    scorecard = calculate_scorecard(
        valuation=valuation,
        planning_result=planning_dict,
        btl_result=btl_dict,
        location_result=location_dict,
        mode=mode_key,
    )

    # Step 9: Risk Assessment
    risk = assess_risks(
        valuation=valuation,
        signals=signals,
        planning_result=planning_dict,
        btl_result=btl_dict,
        tenure=listing.tenure or "",
    )

    # ===== DISPLAY RESULTS =====
    st.divider()

    # High-value decision warning
    if not listing.overrides_applied:
        st.warning(
            "If this is a high-value decision, manually confirming the house number "
            "and postcode is recommended before relying on the valuation."
        )

    # === V2 PRIMARY OUTPUT (when V2 selected) ===
    if use_v2 and v2_result and v2_explanation:
        v2f = v2_result.final

        # V2 Verdict Banner
        verdict_col1, verdict_col2, verdict_col3 = st.columns([2, 1, 1])
        with verdict_col1:
            st.subheader(valuation.investment_tagline)
            st.caption(scorecard.verdict)
        with verdict_col2:
            st.metric("Overall Score", f"{scorecard.overall_score:.0f}/100")
        with verdict_col3:
            st.metric(
                "V2 Confidence",
                f"{v2f.confidence_score}/100",
                help=v2f.confidence_label,
            )

        st.divider()

        # V2 Fair Value Range
        st.subheader("Fair Value Estimate")
        val_cols = st.columns(4)
        with val_cols[0]:
            st.metric("Asking Price", format_currency(listing.asking_price))
        with val_cols[1]:
            v2_gap = None
            if v2f.fair_value_balanced and listing.asking_price:
                v2_gap_pct = ((listing.asking_price - v2f.fair_value_balanced) / v2f.fair_value_balanced) * 100
                v2_gap = f"{v2_gap_pct:+.1f}% vs asking"
            st.metric(
                "Fair Value (Balanced)",
                format_currency(v2f.fair_value_balanced) if v2f.fair_value_balanced else "Insufficient data",
                delta=v2_gap,
                delta_color="inverse",
            )
        with val_cols[2]:
            st.metric(
                "Conservative",
                format_currency(v2f.fair_value_conservative) if v2f.fair_value_conservative else "-",
            )
        with val_cols[3]:
            st.metric(
                "Aggressive",
                format_currency(v2f.fair_value_aggressive) if v2f.fair_value_aggressive else "-",
            )

        # Evidence Groups
        with st.expander("Evidence Groups", expanded=True):
            for g in v2_result.groups:
                if g.comp_count > 0:
                    weight_str = f"{g.weight_in_final:.0%}" if g.weight_in_final > 0 else "n/a"
                    type_parts = []
                    if g.type_exact_count:
                        type_parts.append(f"{g.type_exact_count} exact")
                    if g.type_compatible_count:
                        type_parts.append(f"{g.type_compatible_count} compat")
                    if g.type_incompatible_fallback_count:
                        type_parts.append(f"{g.type_incompatible_fallback_count} fallback")
                    if g.type_excluded_count:
                        type_parts.append(f"{g.type_excluded_count} excl")
                    type_str = f" | Types: {', '.join(type_parts)}" if type_parts else ""
                    eq_str = f" | EQ: {g.evidence_quality}" if g.evidence_quality < 100 else ""
                    status_str = f" | Status: {g.evidence_status}"
                    if g.evidence_status == "FALLBACK_ONLY":
                        status_str += " ⚠"
                    st.markdown(
                        f"**{g.name}** — {g.comp_count} comp(s) | "
                        f"Valuation: {format_currency(g.valuation) if g.valuation > 0 else 'n/a'} | "
                        f"Confidence: {g.confidence_label} ({g.confidence_score}) | "
                        f"Weight: {weight_str}{status_str}{eq_str}{type_str}"
                    )
                    if g.representative:
                        r = g.representative
                        st.caption(
                            f"  Representative: {r.address}, "
                            f"sold for {format_currency(r.adjusted_price)}"
                        )
                else:
                    st.markdown(f"**{g.name}** — No qualifying comparables")

        # Why Is This Worth What It Is?
        st.subheader("Why Is This Worth What It Is?")

        with st.expander("Executive Summary", expanded=True):
            st.write(v2_explanation.executive_summary)

        with st.expander("Key Value Drivers", expanded=True):
            for d in v2_explanation.key_drivers:
                arrow = {"raises value": ":arrow_up:", "lowers value": ":arrow_down:", "neutral": ":left_right_arrow:"}.get(d.direction, "")
                st.markdown(f"{arrow} **{d.title}** ({d.impact})")
                st.caption(f"  {d.explanation}")

        with st.expander("Evidence Hierarchy", expanded=False):
            for h in v2_explanation.evidence_hierarchy:
                weight_str = f"{h.weighting:.0%}" if h.weighting > 0 else "n/a"
                val_str = format_currency(h.valuation) if h.valuation > 0 else "n/a"
                st.markdown(f"**{h.group_name}** — Confidence: {h.confidence} | Valuation: {val_str} | Weight: {weight_str}")
                if h.representative:
                    st.caption(f"  {h.representative}")
                st.caption(f"  {h.summary}")

        with st.expander("Confidence Explanation", expanded=False):
            st.write(v2_explanation.confidence_explanation)

        with st.expander("Offer Rationale", expanded=False):
            st.write(v2_explanation.offer_rationale)

        if v2_explanation.evidence_conflicts:
            with st.expander("Evidence Conflicts", expanded=False):
                st.write(v2_explanation.evidence_conflicts)

        if v2_explanation.why_not_highest:
            with st.expander("Why Not the Highest Sale?", expanded=False):
                st.write(v2_explanation.why_not_highest)

        if v2_explanation.risks or v2_explanation.strengths:
            with st.expander("Risks & Strengths", expanded=False):
                if v2_explanation.risks:
                    st.markdown("**Risks:**")
                    for r in v2_explanation.risks:
                        st.warning(r)
                else:
                    st.caption("No material valuation risks identified.")
                if v2_explanation.strengths:
                    st.markdown("**Strengths:**")
                    for s in v2_explanation.strengths:
                        st.success(s)

        with st.expander("Overall Verdict", expanded=True):
            st.write(v2_explanation.overall_verdict)

    # === V1 OUTPUT (primary when V1, collapsed comparison when V2) ===
    if use_v2 and v2_result and v2_explanation:
        # V1 in collapsed comparison expander
        st.divider()
        with st.expander("Legacy V1 Comparison", expanded=False):
            st.caption("Original weighted-average valuation engine. Retained for comparison and regression testing.")

            # V1 status
            vstatus = getattr(valuation, 'valuation_status', 'Unknown')
            if vstatus == "Insufficient evidence":
                st.error(f"V1 Status: {vstatus}")
            elif vstatus == "Weak evidence":
                st.warning(f"V1 Status: {vstatus}")
            elif vstatus == "Usable with caution":
                st.info(f"V1 Status: {vstatus}")
            elif vstatus == "Reliable":
                st.success(f"V1 Status: {vstatus}")

            v1_cols = st.columns(4)
            with v1_cols[0]:
                st.metric("V1 Fair Value", format_currency(valuation.fair_value_balanced) if valuation.fair_value_balanced else "Insufficient data")
            with v1_cols[1]:
                st.metric("V1 Conservative", format_currency(valuation.fair_value_conservative) if valuation.fair_value_conservative else "-")
            with v1_cols[2]:
                st.metric("V1 Aggressive", format_currency(valuation.fair_value_aggressive) if valuation.fair_value_aggressive else "-")
            with v1_cols[3]:
                st.metric("V1 Confidence", f"{valuation.confidence_score}/100", help=valuation.confidence_label)

            if valuation.suggested_initial_offer > 0:
                st.markdown("**V1 Offer Strategy**")
                off_cols = st.columns(3)
                with off_cols[0]:
                    st.metric("Initial Offer", format_currency(valuation.suggested_initial_offer))
                with off_cols[1]:
                    st.metric("Max Sensible Offer", format_currency(valuation.max_sensible_offer))
                with off_cols[2]:
                    st.metric("Walk-Away Price", format_currency(valuation.walk_away_price))
                st.caption(valuation.negotiation_reasoning)

            if valuation.comparable_details:
                import pandas as pd
                comp_df = pd.DataFrame(valuation.comparable_details)
                display_cols = ["address", "price", "adjusted_price", "date", "property_type",
                                "tenure", "tier", "quality_score", "quality_band"]
                available_cols = [c for c in display_cols if c in comp_df.columns]
                comp_df = comp_df[available_cols]
                if "price" in comp_df.columns:
                    comp_df["price"] = comp_df["price"].apply(lambda x: format_currency(x))
                if "adjusted_price" in comp_df.columns:
                    comp_df["adjusted_price"] = comp_df["adjusted_price"].apply(lambda x: format_currency(x))
                st.dataframe(comp_df, use_container_width=True, hide_index=True)

            st.caption(f"Method: {valuation.valuation_method}")
    else:
        # V1 as primary output (Legacy V1 Comparison mode)
        vstatus = getattr(valuation, 'valuation_status', 'Unknown')
        if vstatus == "Insufficient evidence":
            st.error(f"VALUATION STATUS: {vstatus}. No reliable valuation could be produced.")
        elif vstatus == "Weak evidence":
            st.warning(f"VALUATION STATUS: {vstatus}. Treat all values below as rough guidance only.")
        elif vstatus == "Usable with caution":
            st.info(f"VALUATION STATUS: {vstatus}. Evidence base has limitations - see details below.")
        elif vstatus == "Reliable":
            st.success(f"VALUATION STATUS: {vstatus}. Good evidence base supports this valuation.")

        verdict_col1, verdict_col2, verdict_col3 = st.columns([2, 1, 1])
        with verdict_col1:
            st.subheader(valuation.investment_tagline)
            st.caption(scorecard.verdict)
        with verdict_col2:
            st.metric("Overall Score", f"{scorecard.overall_score:.0f}/100")
        with verdict_col3:
            st.metric(
                "Confidence",
                f"{valuation.confidence_score}/100",
                help=valuation.confidence_label,
            )

        st.divider()

        st.subheader("Fair Value Estimate")
        val_cols = st.columns(4)
        with val_cols[0]:
            st.metric("Asking Price", format_currency(listing.asking_price))
        with val_cols[1]:
            delta_str = None
            if valuation.asking_vs_fair_gap_pct:
                delta_str = f"{valuation.asking_vs_fair_gap_pct:+.1f}% vs asking"
            st.metric(
                "Fair Value (Balanced)",
                format_currency(valuation.fair_value_balanced) if valuation.fair_value_balanced else "Insufficient data",
                delta=delta_str,
                delta_color="inverse",
            )
        with val_cols[2]:
            st.metric(
                "Conservative",
                format_currency(valuation.fair_value_conservative) if valuation.fair_value_conservative else "-",
            )
        with val_cols[3]:
            st.metric(
                "Aggressive",
                format_currency(valuation.fair_value_aggressive) if valuation.fair_value_aggressive else "-",
            )

        if not valuation.sufficient_evidence:
            st.warning(
                "Insufficient comparable evidence for a reliable valuation. "
                "The values above should not be relied upon. Manual research is essential."
            )

        if valuation.suggested_initial_offer > 0:
            st.subheader("Offer Strategy")
            offer_cols = st.columns(3)
            with offer_cols[0]:
                st.metric("Initial Offer", format_currency(valuation.suggested_initial_offer))
            with offer_cols[1]:
                st.metric("Max Sensible Offer", format_currency(valuation.max_sensible_offer))
            with offer_cols[2]:
                st.metric("Walk-Away Price", format_currency(valuation.walk_away_price))
            st.caption(valuation.negotiation_reasoning)

        with st.expander(f"Comparable Evidence ({valuation.comparables_used} sales)", expanded=False):
            if valuation.comparable_details:
                import pandas as pd
                comp_df = pd.DataFrame(valuation.comparable_details)
                display_cols = ["address", "price", "adjusted_price", "date", "property_type",
                                "tenure", "tier", "quality_score", "quality_band"]
                available_cols = [c for c in display_cols if c in comp_df.columns]
                comp_df = comp_df[available_cols]
                if "price" in comp_df.columns:
                    comp_df["price"] = comp_df["price"].apply(lambda x: format_currency(x))
                if "adjusted_price" in comp_df.columns:
                    comp_df["adjusted_price"] = comp_df["adjusted_price"].apply(lambda x: format_currency(x))
                st.dataframe(comp_df, use_container_width=True, hide_index=True)
            else:
                st.info("No comparable evidence available.")

            st.caption(f"Method: {valuation.valuation_method}")
            for a in valuation.assumptions:
                st.caption(f"  - {a}")

            if valuation.warnings:
                for w in valuation.warnings:
                    st.warning(w)

    # === SHARED SECTIONS (both modes) ===

    # Investment Scorecard
    st.subheader("Investment Scorecard")
    dims = scorecard.dimensions
    dim_cols = st.columns(4)
    for i, dim in enumerate(dims):
        with dim_cols[i % 4]:
            colour = "normal"
            if dim.score >= 7:
                colour = "off"
            elif dim.score <= 3:
                colour = "inverse"
            st.metric(
                dim.name,
                f"{dim.score}/10 ({dim.label})",
                delta=f"wt: {dim.weight:.0f}%",
                delta_color=colour,
            )
            st.caption(dim.explanation)

    # Adjustments Applied
    if valuation.adjustments:
        with st.expander(f"Property Adjustments ({len(valuation.adjustments)} applied)", expanded=False):
            for adj in valuation.adjustments:
                direction = "+" if adj.direction == "positive" else ""
                st.write(f"**{adj.name}**: {direction}{adj.percentage:.1f}% ({format_currency(adj.amount)})")
                st.caption(f"  {adj.reason}")
            st.write(f"**Total adjustment: {valuation.total_adjustment_pct:+.1f}%** ({format_currency(valuation.total_adjustment)})")

    # Listing Signals
    with st.expander("Listing Interpretation", expanded=False):
        st.write(f"**Condition:** {signals.condition_label} ({signals.condition_score}/10)")
        if signals.condition_keywords_found:
            st.caption(f"Keywords: {', '.join(signals.condition_keywords_found[:5])}")

        features = []
        if signals.has_garage:
            features.append("Garage")
        if signals.has_driveway:
            features.append("Driveway")
        if signals.has_parking:
            features.append("Parking")
        if signals.has_garden:
            features.append("Garden")
        if signals.has_extension_already:
            features.append("Extension")
        if signals.has_conservatory:
            features.append("Conservatory")
        if signals.has_loft_conversion:
            features.append("Loft conversion")
        if features:
            st.write(f"**Features:** {', '.join(features)}")

        flags = []
        if signals.chain_free:
            flags.append("Chain free")
        if signals.period_property:
            flags.append("Period property")
        if signals.new_build:
            flags.append("New build")
        if signals.investment_property:
            flags.append("Investment property")
        if signals.tenant_in_situ:
            flags.append("Tenant in situ")
        if signals.structural_concerns:
            flags.append("Structural concerns")
        if signals.non_standard_construction:
            flags.append("Non-standard construction")
        if flags:
            st.write(f"**Flags:** {', '.join(flags)}")

        if signals.estimated_era:
            st.write(f"**Estimated era:** {signals.estimated_era}")

    # Risk Assessment
    with st.expander(f"Risk Assessment ({risk.overall_risk_level})", expanded=True):
        st.write(risk.summary)
        for flag in risk.flags:
            if flag.severity == "High":
                st.error(f"**{flag.title}** ({flag.category}): {flag.explanation}")
                st.caption(f"  Mitigation: {flag.mitigation}")
            elif flag.severity == "Medium":
                st.warning(f"**{flag.title}** ({flag.category}): {flag.explanation}")
                st.caption(f"  Mitigation: {flag.mitigation}")
            else:
                st.info(f"**{flag.title}** ({flag.category}): {flag.explanation}")
                if flag.mitigation:
                    st.caption(f"  Mitigation: {flag.mitigation}")

    # Planning
    if planning_dict:
        with st.expander("Planning Constraints", expanded=False):
            constraints = planning_dict.get("constraints_summary", [])
            if constraints:
                for c in constraints:
                    st.write(f"  - {c}")
            else:
                st.write("No planning constraints identified.")

            for w in planning_dict.get("warnings", []):
                st.warning(w)

    # BTL
    if mode_key in ("btl", "both") and btl_dict:
        with st.expander("Buy-to-Let Assessment", expanded=False):
            btl_cols = st.columns(4)
            with btl_cols[0]:
                st.metric("Monthly Rent (est.)", format_currency(btl_dict.get("estimated_monthly_rent", 0)))
            with btl_cols[1]:
                st.metric("Gross Yield", f"{btl_dict.get('gross_yield', 0):.1f}%")
            with btl_cols[2]:
                st.metric("Net Yield (est.)", f"{btl_dict.get('net_yield_estimate', 0):.1f}%")
            with btl_cols[3]:
                st.metric("BTL Score", f"{btl_dict.get('btl_score', 0)}/10")

            st.write(f"**Verdict:** {btl_dict.get('btl_verdict', 'N/A')}")

    # Location
    with st.expander("Location Assessment", expanded=False):
        st.metric("Location Score", f"{location_dict.get('location_score', 0)}/10")
        for d in location_dict.get("distances", []):
            st.write(f"  - **{d['name']}:** {d['distance_miles']} miles ({d['drive_time_estimate']})")
        for w in location_dict.get("warnings", []):
            st.caption(w)

    # EPC
    if hasattr(listing, "epc_rating") and listing.epc_rating:
        with st.expander("EPC Assessment", expanded=False):
            epc_impact = estimate_epc_impact(listing.epc_rating)
            st.write(f"**Current Rating:** {epc_impact['current_rating']}")
            st.write(f"**Estimated Annual Energy Cost:** {format_currency(epc_impact['estimated_annual_energy_cost'])}")
            if epc_impact.get("upgrade_potential"):
                st.write(
                    f"**Upgrade Cost:** {format_currency(epc_impact['upgrade_cost_estimate_low'])} "
                    f"- {format_currency(epc_impact['upgrade_cost_estimate_high'])}"
                )

    # Key Risks & Opportunities
    with st.expander("Key Risks & Opportunities Summary", expanded=False):
        if scorecard.key_risks:
            st.write("**Risks:**")
            for r in scorecard.key_risks:
                st.error(r)
        if scorecard.key_opportunities:
            st.write("**Opportunities:**")
            for o in scorecard.key_opportunities:
                st.success(o)

    # Data Gaps
    if valuation.data_gaps:
        with st.expander(f"Data Gaps ({len(valuation.data_gaps)})", expanded=False):
            for gap in valuation.data_gaps:
                st.warning(gap)

    # Recommendation
    st.subheader("Recommendation")
    st.info(scorecard.recommendation)

    # Manual Identity Overrides (if any)
    if listing.overrides_applied:
        with st.expander("Manual Identity Overrides Used", expanded=False):
            for ov in listing.overrides_applied:
                st.write(f"- {ov}")
            if listing.floor_area_source == "EPC" and listing.floor_area_sqm:
                st.success(
                    f"EPC match successful with overrides: {listing.floor_area_sqm:.0f} sqm"
                )
            elif any("House" in o or "number" in o.lower() for o in listing.overrides_applied):
                if not listing.floor_area_sqm or listing.floor_area_source != "EPC":
                    st.warning("House number provided but EPC match still failed")

    # PDF Report
    st.divider()
    with st.status("Generating PDF report...", expanded=False) as status:
        score_dict = scorecard.to_dict()
        risk_dict = risk.to_dict()
        score_dict["flags"] = risk_dict.get("flags", [])
        score_dict["summary"] = risk_dict.get("summary", "")
        report_path = generate_report(
            listing=listing.to_dict(),
            valuation=valuation.to_dict(),
            planning=planning_dict,
            btl=btl_dict,
            location=location_dict,
            investment_score=score_dict,
            mode=mode_key,
            v2_result=v2_result,
            v2_explanation=v2_explanation,
        )
        status.update(label="PDF report generated", state="complete")

    with open(report_path, "rb") as f:
        st.download_button(
            label="Download PDF Report",
            data=f,
            file_name=Path(report_path).name,
            mime="application/pdf",
            type="primary",
        )

    # Save to database
    try:
        prop_id = save_property(
            url=url,
            address=listing.address or "",
            postcode=listing.postcode,
            property_type=listing.property_type or "",
            bedrooms=listing.bedrooms or 0,
            bathrooms=listing.bathrooms if hasattr(listing, "bathrooms") else 0,
            floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "",
            asking_price=listing.asking_price,
            valuation_result=valuation.to_dict(),
            scorecard_result=scorecard.to_dict(),
            risk_result=risk.to_dict(),
            listing_data=listing.to_dict(),
            comparable_data={"total": evidence.total_scored, "summary": evidence.evidence_summary},
            mode=mode_key,
        )
        st.caption(f"Analysis saved to database (ID: {prop_id})")
    except Exception as e:
        st.caption(f"Could not save to database: {e}")

# --- Footer ---
st.divider()
st.caption(
    "Data sources: HM Land Registry Price Paid Data, UK House Price Index, "
    "Planning Data API, postcodes.io. This tool uses free/open data only. "
    "Not a formal valuation - always commission professional advice."
)
