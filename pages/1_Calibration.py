"""Calibration & Feedback — review past analyses and record human judgement."""

import json
import streamlit as st

from src.property_db import (
    get_all_properties, get_property, get_calibration,
    save_calibration, get_error_tag_summary,
)
from src.utils import format_currency

st.set_page_config(page_title="Calibration", page_icon="🎯", layout="wide")
st.title("Calibration & Feedback")
st.caption(
    "Review past analyses, record whether the tool got it right, "
    "and track what it missed. This builds the feedback loop that "
    "makes the model better over time."
)

# --- Property selector ---
properties = get_all_properties()
if not properties:
    st.info("No properties analysed yet. Run an analysis from the main page first.")
    st.stop()

options = {
    p["id"]: f"{p['address'][:50]} | {p['postcode']} | {format_currency(p['asking_price'])} | {p.get('analysis_date', '')}"
    for p in properties
}

selected_id = st.selectbox(
    "Select a property to review",
    list(options.keys()),
    format_func=lambda x: options[x],
)

prop = get_property(selected_id)
if not prop:
    st.error("Property not found.")
    st.stop()

cal = get_calibration(selected_id) or {}

# --- Property summary ---
st.divider()
col1, col2, col3 = st.columns(3)
with col1:
    st.subheader(prop["address"] or "Unknown")
    st.write(f"**{prop['property_type']}** | {prop['bedrooms']} bed | {prop['tenure']}")
    st.write(f"Postcode: **{prop['postcode']}**")
    if prop.get("url"):
        st.markdown(f"[Open on Rightmove]({prop['url']})")

with col2:
    st.metric("Asking Price", format_currency(prop["asking_price"]))
    balanced = prop.get("fair_value_balanced", 0)
    if balanced:
        st.metric("Balanced Value", format_currency(balanced))
    else:
        st.metric("Balanced Value", "Not produced")

with col3:
    st.metric("Overall Score", f"{prop.get('overall_score', 0):.0f}/100")
    st.metric("Confidence", prop.get("confidence_label", "N/A"))

# Valuation status and tagline
val_json = {}
if prop.get("valuation_json"):
    try:
        val_json = json.loads(prop["valuation_json"])
    except (json.JSONDecodeError, TypeError):
        pass

v_status = val_json.get("valuation_status", "Unknown")
tagline = val_json.get("investment_tagline", prop.get("investment_tagline", ""))
gap_pct = prop.get("asking_vs_fair_gap_pct", 0)

st.write(f"**Status:** {v_status}")
st.write(f"**Tagline:** {tagline}")
if gap_pct:
    st.write(f"**Gap vs asking:** {gap_pct:+.1f}%")
st.write(f"**Verdict:** {prop.get('verdict', 'N/A')}")
st.write(f"**Risk level:** {prop.get('risk_level', 'N/A')} ({prop.get('risk_count', 0)} flags)")

# Show recommendation
if prop.get("recommendation"):
    with st.expander("Tool Recommendation", expanded=False):
        st.write(prop["recommendation"])

# Show comparables summary
if prop.get("comparable_json"):
    try:
        comp_data = json.loads(prop["comparable_json"])
        with st.expander("Comparable Summary", expanded=False):
            st.write(f"Total comparables: {comp_data.get('total', 'N/A')}")
            if comp_data.get("summary"):
                st.write(comp_data["summary"])
    except (json.JSONDecodeError, TypeError):
        pass

# --- Calibration feedback form ---
st.divider()
st.subheader("Your Feedback")

with st.form("calibration_form"):
    f_col1, f_col2 = st.columns(2)

    with f_col1:
        JUDGEMENT_OPTIONS = [
            "", "credible", "too_optimistic", "too_conservative",
            "wrong_comparables", "missing_dev_upside",
            "missing_risk", "insufficient_data",
        ]
        current_judgement = cal.get("valuation_judgement", "")
        judgement_idx = JUDGEMENT_OPTIONS.index(current_judgement) if current_judgement in JUDGEMENT_OPTIONS else 0

        valuation_judgement = st.selectbox(
            "Valuation accuracy",
            JUDGEMENT_OPTIONS,
            index=judgement_idx,
            format_func=lambda x: x.replace("_", " ").title() if x else "-- Select --",
        )

        COMP_OPTIONS = ["", "good", "acceptable", "poor", "wrong_type", "too_broad"]
        current_comp = cal.get("comparable_quality", "")
        comp_idx = COMP_OPTIONS.index(current_comp) if current_comp in COMP_OPTIONS else 0

        comparable_quality = st.selectbox(
            "Comparable selection quality",
            COMP_OPTIONS,
            index=comp_idx,
            format_func=lambda x: x.replace("_", " ").title() if x else "-- Select --",
        )

        VERDICT_OPTIONS = ["", "right", "partially_right", "wrong"]
        current_verdict = cal.get("verdict_judgement", "")
        verdict_idx = VERDICT_OPTIONS.index(current_verdict) if current_verdict in VERDICT_OPTIONS else 0

        verdict_judgement = st.selectbox(
            "Was the investment verdict right?",
            VERDICT_OPTIONS,
            index=verdict_idx,
            format_func=lambda x: x.replace("_", " ").title() if x else "-- Select --",
        )

    with f_col2:
        viewed = st.checkbox("I viewed this property", value=bool(cal.get("viewed", 0)))
        offered = st.checkbox("I made an offer", value=bool(cal.get("offered", 0)))
        offer_amount = st.number_input(
            "Offer amount (GBP)",
            min_value=0, value=int(cal.get("offer_amount") or 0), step=5000,
        )

        OUTCOME_OPTIONS = [
            "", "not_pursued", "offered_rejected", "offered_accepted",
            "purchased", "sold_to_other",
        ]
        current_outcome = cal.get("outcome", "")
        outcome_idx = OUTCOME_OPTIONS.index(current_outcome) if current_outcome in OUTCOME_OPTIONS else 0

        outcome = st.selectbox(
            "Outcome",
            OUTCOME_OPTIONS,
            index=outcome_idx,
            format_func=lambda x: x.replace("_", " ").title() if x else "-- Select --",
        )

        eventual_sold_price = st.number_input(
            "Eventual sold price (if known, GBP)",
            min_value=0, value=int(cal.get("eventual_sold_price") or 0), step=5000,
        )

    what_tool_missed = st.text_area(
        "What did the tool miss?",
        value=cal.get("what_tool_missed", ""),
        placeholder="e.g. Large rear garden not reflected in value, "
                    "nearby development not flagged...",
    )

    manual_adjustment_notes = st.text_area(
        "What adjustment would you have made manually?",
        value=cal.get("manual_adjustment_notes", ""),
        placeholder="e.g. I would value this at ~230k based on 3 similar sales "
                    "on the same street...",
    )

    general_notes = st.text_area(
        "General notes",
        value=cal.get("general_notes", ""),
    )

    # Error tags
    st.write("**Model error categories** (select all that apply)")
    ERROR_TAGS = [
        "postcode_too_broad",
        "wrong_property_type",
        "no_floor_area",
        "rural_comps_diverse",
        "flats_misweighted",
        "extension_underestimated",
        "btl_assumptions_weak",
        "condition_misjudged",
        "tenure_issue",
        "new_build_mixed_in",
        "date_range_too_wide",
        "outlier_not_removed",
    ]
    existing_tags = set((cal.get("error_tags", "") or "").split(","))
    existing_tags.discard("")
    selected_tags = []
    tag_cols = st.columns(4)
    for i, tag in enumerate(ERROR_TAGS):
        with tag_cols[i % 4]:
            if st.checkbox(
                tag.replace("_", " "),
                value=tag in existing_tags,
                key=f"tag_{tag}",
            ):
                selected_tags.append(tag)

    submitted = st.form_submit_button("Save Feedback", type="primary")

if submitted:
    save_calibration(selected_id, {
        "valuation_judgement": valuation_judgement,
        "comparable_quality": comparable_quality,
        "verdict_judgement": verdict_judgement,
        "what_tool_missed": what_tool_missed,
        "manual_adjustment_notes": manual_adjustment_notes,
        "general_notes": general_notes,
        "error_tags": ",".join(selected_tags),
        "viewed": 1 if viewed else 0,
        "offered": 1 if offered else 0,
        "offer_amount": offer_amount if offer_amount > 0 else None,
        "outcome": outcome,
        "eventual_sold_price": eventual_sold_price if eventual_sold_price > 0 else None,
    })
    st.success("Feedback saved.")
    st.rerun()

# --- Model error summary ---
st.divider()
st.subheader("Model Error Patterns")
st.caption("Across all calibrated properties — shows which problems recur.")

error_summary = get_error_tag_summary()
if error_summary:
    for item in error_summary:
        tag_label = item["tag"].replace("_", " ")
        st.write(f"**{tag_label}**: {item['count']} occurrence(s)")
else:
    st.info("No error tags recorded yet. Start reviewing properties above.")
