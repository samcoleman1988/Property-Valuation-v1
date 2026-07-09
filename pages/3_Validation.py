"""Validation Test Harness — paste Rightmove URLs to test real-world accuracy."""

import json
import traceback
import streamlit as st
import pandas as pd

from src.rightmove_parser import parse_listing
from src.comparable_engine import fetch_and_score_comparables
from src.listing_interpreter import interpret_listing
from src.valuation_engine import calculate_valuation
from src.investment_scorecard import calculate_scorecard
from src.risk_assessor import assess_risks
from src.planning import assess_planning
from src.transport import assess_location
from src.property_db import save_property, get_all_properties
from src.utils import format_currency

st.set_page_config(page_title="Validation", page_icon="🧪", layout="wide")
st.title("Validation Test Harness")
st.caption(
    "Paste Rightmove URLs one at a time. Each analysis is saved to the database "
    "so you can review and calibrate results on the Calibration page."
)

# --- Settings ---
with st.sidebar:
    st.header("Test Settings")
    mode = st.selectbox(
        "Analysis Mode",
        ["Personal Purchase", "Buy-to-Let", "Both"],
        index=0,
        key="val_mode",
    )
    mode_key = {"Personal Purchase": "personal", "Buy-to-Let": "btl", "Both": "both"}[mode]
    region = st.selectbox(
        "HPI Region",
        ["England", "North West", "South East", "Oxfordshire", "Wirral", "London",
         "East Midlands", "West Midlands", "South West", "East of England", "Wales"],
        index=0,
        key="val_region",
    )

    st.divider()
    st.subheader("Test Categories")
    st.caption("Tag the property for the validation summary.")
    category = st.selectbox(
        "Property category",
        ["oxfordshire_family", "wirral_btl", "obviously_overpriced",
         "development_potential", "other"],
        format_func=lambda x: x.replace("_", " ").title(),
        key="val_category",
    )

# --- URL Input ---
url = st.text_input(
    "Rightmove URL",
    placeholder="https://www.rightmove.co.uk/properties/...",
    key="val_url",
)

if st.button("Analyse & Record", type="primary", disabled=not url):
    if "rightmove.co.uk" not in url:
        st.error("Please enter a valid Rightmove URL.")
        st.stop()

    results = {}
    errors = []

    # Step 1: Parse
    with st.status("Parsing listing...", expanded=True) as status:
        try:
            listing = parse_listing(url)
            results["url"] = url
            results["address"] = listing.address or "Unknown"
            results["postcode"] = listing.postcode or "Unknown"
            results["asking_price"] = listing.asking_price
            results["property_type"] = listing.property_type or "Unknown"
            results["bedrooms"] = listing.bedrooms or 0
            results["floor_area_sqft"] = listing.floor_area_sqft or 0
            results["floor_area_sqm"] = listing.floor_area_sqm or 0
            results["tenure"] = listing.tenure or "Unknown"

            if listing.extraction_warnings:
                for w in listing.extraction_warnings:
                    st.warning(w)
                    errors.append(f"Extraction: {w}")

            if not listing.asking_price:
                st.error("Could not extract asking price.")
                errors.append("No asking price extracted")

            st.write(f"**{listing.address}**")
            st.write(f"{listing.property_type} | {listing.bedrooms} bed | {listing.tenure}")
            st.write(f"Asking: **{format_currency(listing.asking_price)}**")
            if listing.floor_area_sqft:
                st.write(f"Floor area: {listing.floor_area_sqft:,.0f} sq ft")
            else:
                st.write("Floor area: **Not available**")
                errors.append("No floor area")
            status.update(label="Listing parsed", state="complete")
        except Exception as e:
            st.error(f"Failed to parse listing: {e}")
            traceback.print_exc()
            st.stop()

    if not listing.asking_price or not listing.postcode:
        st.error("Cannot proceed without asking price and postcode.")
        st.stop()

    # Step 2: Interpret listing text
    with st.status("Interpreting listing...", expanded=False) as status:
        signals = interpret_listing(
            description=listing.description or "",
            key_features=listing.key_features if hasattr(listing, "key_features") else [],
            property_type=listing.property_type or "",
        )
        results["condition"] = f"{signals.condition_label} ({signals.condition_score}/10)"
        status.update(label=f"Condition: {signals.condition_label}", state="complete")

    # Step 3: Comparables
    with st.status("Fetching comparables...", expanded=True) as status:
        street = ""
        if listing.address:
            parts = listing.address.split(",")
            if parts:
                street = parts[0].strip()

        evidence = fetch_and_score_comparables(
            postcode=listing.postcode,
            property_type=listing.property_type or "",
            bedrooms=listing.bedrooms or 0,
            floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "",
            latitude=listing.latitude or 0,
            longitude=listing.longitude or 0,
            street=street,
        )
        results["total_comps"] = evidence.total_scored
        results["tier_a"] = evidence.tier_a_count
        results["tier_b"] = evidence.tier_b_count
        results["tier_c"] = evidence.tier_c_count
        status.update(
            label=f"Comparables: {evidence.total_scored} scored "
                  f"(A={evidence.tier_a_count} B={evidence.tier_b_count} C={evidence.tier_c_count})",
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
        results["valuation_status"] = valuation.valuation_status
        results["balanced"] = valuation.fair_value_balanced
        results["conservative"] = valuation.fair_value_conservative
        results["aggressive"] = valuation.fair_value_aggressive
        results["gap_pct"] = valuation.asking_vs_fair_gap_pct
        results["confidence"] = f"{valuation.confidence_label} ({valuation.confidence_score}/100)"
        results["max_offer"] = valuation.max_sensible_offer
        results["tagline"] = valuation.investment_tagline
        status.update(
            label=f"Status: {valuation.valuation_status} | Balanced: {format_currency(valuation.fair_value_balanced) if valuation.fair_value_balanced else 'N/A'}",
            state="complete",
        )

    # Step 5: Planning
    with st.status("Planning assessment...", expanded=False) as status:
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
        results["planning_summary"] = "; ".join(planning_dict.get("constraints_summary", [])[:3]) or "None found"
        status.update(label="Planning done", state="complete")

    # Step 6: BTL
    btl_dict = {}
    if mode_key in ("btl", "both"):
        with st.status("BTL analysis...", expanded=False) as status:
            try:
                from src.btl_analysis import assess_btl
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
            status.update(label="BTL done", state="complete")

    # Step 7: Location
    with st.status("Location...", expanded=False) as status:
        location = assess_location(
            postcode=listing.postcode,
            latitude=listing.latitude or 0,
            longitude=listing.longitude or 0,
        )
        location_dict = location.to_dict()
        status.update(label="Location done", state="complete")

    # Step 8: Scorecard + Risk
    scorecard = calculate_scorecard(
        valuation=valuation,
        planning_result=planning_dict,
        btl_result=btl_dict,
        location_result=location_dict,
        mode=mode_key,
    )
    risk = assess_risks(
        valuation=valuation,
        signals=signals,
        planning_result=planning_dict,
        btl_result=btl_dict,
        tenure=listing.tenure or "",
    )

    results["investment_score"] = scorecard.overall_score
    results["verdict"] = scorecard.verdict
    results["risk_level"] = risk.overall_risk_level
    results["risk_count"] = len(risk.flags)

    # ===== DISPLAY RESULTS =====
    st.divider()

    # Status banner
    vstatus = valuation.valuation_status
    if vstatus == "Insufficient evidence":
        st.error(f"VALUATION STATUS: {vstatus}")
    elif vstatus == "Weak evidence":
        st.warning(f"VALUATION STATUS: {vstatus}")
    elif vstatus == "Usable with caution":
        st.info(f"VALUATION STATUS: {vstatus}")
    else:
        st.success(f"VALUATION STATUS: {vstatus}")

    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Asking", format_currency(listing.asking_price))
    with col2:
        st.metric("Balanced",
                   format_currency(valuation.fair_value_balanced) if valuation.fair_value_balanced else "N/A")
    with col3:
        if valuation.asking_vs_fair_gap_pct:
            st.metric("Gap", f"{valuation.asking_vs_fair_gap_pct:+.1f}%")
        else:
            st.metric("Gap", "-")
    with col4:
        st.metric("Score", f"{scorecard.overall_score:.0f}/100")

    col5, col6 = st.columns(2)
    with col5:
        st.metric("Max Offer", format_currency(valuation.max_sensible_offer) if valuation.max_sensible_offer else "N/A")
    with col6:
        st.metric("Confidence", f"{valuation.confidence_score}/100 ({valuation.confidence_label})")

    st.write(f"**Tagline:** {valuation.investment_tagline}")
    st.write(f"**Verdict:** {scorecard.verdict}")

    # Top 3 comparables
    st.subheader("Top 3 Comparables")
    comp_details = valuation.comparable_details[:3] if valuation.comparable_details else []
    if comp_details:
        for i, c in enumerate(comp_details, 1):
            tier = c.get("tier", c.get("quality_band", ""))
            st.write(
                f"{i}. **{c.get('address', '?')[:50]}** | "
                f"{format_currency(c.get('price', 0))} | "
                f"{c.get('date', '')[:11]} | "
                f"Tier {tier} (score {c.get('quality_score', '')})"
            )
    else:
        st.write("No comparables available.")

    # Top 3 risks
    st.subheader("Top 3 Risks")
    top_risks = sorted(risk.flags, key=lambda f: {"High": 0, "Medium": 1, "Low": 2}.get(f.severity, 3))[:3]
    for f in top_risks:
        if f.severity == "High":
            st.error(f"**[{f.severity}] {f.title}**: {f.explanation}")
        elif f.severity == "Medium":
            st.warning(f"**[{f.severity}] {f.title}**: {f.explanation}")
        else:
            st.info(f"**[{f.severity}] {f.title}**: {f.explanation}")

    # Planning summary
    st.subheader("Planning / Development")
    st.write(results["planning_summary"])

    # Data gaps
    if valuation.data_gaps:
        st.subheader("Data Gaps")
        for g in valuation.data_gaps:
            st.warning(g)

    # Warnings
    if valuation.warnings:
        st.subheader("Warnings")
        for w in valuation.warnings:
            st.warning(w)

    # Save to DB
    try:
        score_dict = scorecard.to_dict()
        risk_dict = risk.to_dict()
        score_dict["flags"] = risk_dict.get("flags", [])
        score_dict["summary"] = risk_dict.get("summary", "")

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
            scorecard_result=score_dict,
            risk_result=risk_dict,
            listing_data=listing.to_dict(),
            comparable_data={
                "total": evidence.total_scored,
                "tier_a": evidence.tier_a_count,
                "tier_b": evidence.tier_b_count,
                "tier_c": evidence.tier_c_count,
                "summary": evidence.evidence_summary,
            },
            mode=mode_key,
            notes=f"category:{category}",
        )
        st.success(f"Saved to database (ID: {prop_id}). Go to Calibration page to record your judgement.")
    except Exception as e:
        st.error(f"Could not save: {e}")

# --- Validation Summary ---
st.divider()
st.subheader("Validation Summary")
st.caption("Shows all properties analysed in this database, with key metrics for review.")

all_props = get_all_properties()
if not all_props:
    st.info("No properties analysed yet. Paste a URL above to start.")
    st.stop()

summary_rows = []
for p in all_props:
    val_json = {}
    if p.get("valuation_json"):
        try:
            val_json = json.loads(p["valuation_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    comp_json = {}
    if p.get("comparable_json"):
        try:
            comp_json = json.loads(p["comparable_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    category_tag = ""
    notes = p.get("notes", "")
    if notes and notes.startswith("category:"):
        category_tag = notes.split(":", 1)[1]

    summary_rows.append({
        "ID": p["id"],
        "Address": (p.get("address") or "")[:35],
        "Postcode": p.get("postcode", ""),
        "Category": category_tag,
        "Asking": p.get("asking_price", 0),
        "Balanced": p.get("fair_value_balanced", 0),
        "Gap %": p.get("asking_vs_fair_gap_pct", 0),
        "Status": val_json.get("valuation_status", "?"),
        "Score": p.get("overall_score", 0),
        "Confidence": p.get("confidence_label", ""),
        "Risks": p.get("risk_count", 0),
        "Floor Area": "Yes" if (p.get("floor_area_sqm") or 0) > 0 else "No",
        "Comps": comp_json.get("total", "?"),
        "Tier A+B": (comp_json.get("tier_a", 0) or 0) + (comp_json.get("tier_b", 0) or 0),
    })

df = pd.DataFrame(summary_rows)

# Format for display
df_display = df.copy()
df_display["Asking"] = df_display["Asking"].apply(lambda x: format_currency(x) if x else "-")
df_display["Balanced"] = df_display["Balanced"].apply(lambda x: format_currency(x) if x else "-")
df_display["Gap %"] = df_display["Gap %"].apply(lambda x: f"{x:+.1f}%" if x else "-")
df_display["Score"] = df_display["Score"].apply(lambda x: f"{x:.0f}" if x else "-")

st.dataframe(df_display, use_container_width=True, hide_index=True)

# Quick pattern analysis
st.subheader("Pattern Analysis")

n_total = len(df)
n_insufficient = len(df[df["Status"] == "Insufficient evidence"])
n_weak = len(df[df["Status"] == "Weak evidence"])
n_no_area = len(df[df["Floor Area"] == "No"])
n_low_comps = len(df[df["Tier A+B"] < 5])

p_col1, p_col2, p_col3 = st.columns(3)
with p_col1:
    st.metric("Total analysed", n_total)
    st.metric("Insufficient evidence", n_insufficient)
with p_col2:
    st.metric("Weak evidence", n_weak)
    st.metric("No floor area", n_no_area)
with p_col3:
    st.metric("Low quality comps (<5 A+B)", n_low_comps)

st.caption(
    "After analysing 10 properties, review each on the Calibration page "
    "to record whether the output was credible. Then check the Rankings page "
    "for a side-by-side comparison."
)
