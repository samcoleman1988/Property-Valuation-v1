"""Property Rankings — compare all analysed properties side by side."""

import json
import pandas as pd
import streamlit as st

from src.property_db import get_all_calibrations
from src.utils import format_currency

st.set_page_config(page_title="Rankings", page_icon="📊", layout="wide")
st.title("Property Rankings")
st.caption(
    "Compare all analysed properties. Sort by investment score, discount, "
    "risk, or your own judgement to spot the best opportunities."
)

rows = get_all_calibrations()
if not rows:
    st.info("No properties analysed yet.")
    st.stop()

# Build dataframe
records = []
for r in rows:
    val_json = {}
    if r.get("valuation_json"):
        try:
            val_json = json.loads(r["valuation_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    dev_score = 0
    # Try to extract development score from valuation JSON scorecard
    # (stored separately but we can get it from the property record)

    records.append({
        "ID": r["id"],
        "Date": r.get("analysis_date", ""),
        "Address": (r.get("address") or "")[:40],
        "Postcode": r.get("postcode", ""),
        "Type": r.get("property_type", ""),
        "Beds": r.get("bedrooms", 0),
        "Asking": r.get("asking_price", 0),
        "Val Status": val_json.get("valuation_status", "Unknown"),
        "Balanced": r.get("fair_value_balanced", 0),
        "Gap %": r.get("asking_vs_fair_gap_pct", 0),
        "Score": r.get("overall_score", 0),
        "Verdict": r.get("verdict", ""),
        "Risk Count": r.get("risk_count", 0),
        "Confidence": r.get("confidence_label", ""),
        "Judgement": (r.get("valuation_judgement") or "").replace("_", " "),
        "Comp Quality": (r.get("comparable_quality") or "").replace("_", " "),
        "Viewed": "Yes" if r.get("viewed") else "",
        "Offered": "Yes" if r.get("offered") else "",
        "Offer": r.get("offer_amount") or "",
        "Outcome": (r.get("outcome") or "").replace("_", " "),
        "Sold Price": r.get("eventual_sold_price") or "",
        "URL": r.get("url", ""),
    })

df = pd.DataFrame(records)

# Sort controls
sort_col1, sort_col2 = st.columns([1, 1])
with sort_col1:
    sort_by = st.selectbox(
        "Sort by",
        ["Score", "Gap %", "Asking", "Risk Count", "Date", "Balanced"],
        index=0,
    )
with sort_col2:
    sort_asc = st.checkbox("Ascending", value=False)

df_sorted = df.sort_values(by=sort_by, ascending=sort_asc, na_position="last")

# Format currency columns for display
df_display = df_sorted.copy()
for col in ["Asking", "Balanced"]:
    df_display[col] = df_display[col].apply(
        lambda x: format_currency(x) if x else "-"
    )
if "Offer" in df_display.columns:
    df_display["Offer"] = df_display["Offer"].apply(
        lambda x: format_currency(x) if x else ""
    )
if "Sold Price" in df_display.columns:
    df_display["Sold Price"] = df_display["Sold Price"].apply(
        lambda x: format_currency(x) if x else ""
    )
if "Gap %" in df_display.columns:
    df_display["Gap %"] = df_display["Gap %"].apply(
        lambda x: f"{x:+.1f}%" if x else "-"
    )
if "Score" in df_display.columns:
    df_display["Score"] = df_display["Score"].apply(
        lambda x: f"{x:.0f}" if x else "-"
    )

# Display columns (exclude URL from table, show as link separately)
table_cols = [
    "Date", "Address", "Postcode", "Type", "Beds",
    "Asking", "Val Status", "Balanced", "Gap %",
    "Score", "Verdict", "Risk Count", "Confidence",
    "Judgement", "Viewed", "Offered",
]
available = [c for c in table_cols if c in df_display.columns]

st.dataframe(
    df_display[available],
    use_container_width=True,
    hide_index=True,
    height=min(len(df_display) * 40 + 40, 600),
)

st.caption(f"{len(df_display)} properties analysed")

# --- Quick stats ---
st.divider()
st.subheader("Quick Stats")

stat_cols = st.columns(4)
with stat_cols[0]:
    total = len(df)
    calibrated = len(df[df["Judgement"] != ""])
    st.metric("Total Analysed", total)
    st.metric("Calibrated", calibrated)

with stat_cols[1]:
    viewed = len(df[df["Viewed"] == "Yes"])
    offered = len(df[df["Offered"] == "Yes"])
    st.metric("Viewed", viewed)
    st.metric("Offered", offered)

with stat_cols[2]:
    credible = len(df[df["Judgement"] == "credible"])
    wrong = len(df[df["Judgement"].isin(["too optimistic", "too conservative",
                                          "wrong comparables"])])
    if calibrated > 0:
        st.metric("Credible", f"{credible}/{calibrated}")
        st.metric("Wrong", f"{wrong}/{calibrated}")
    else:
        st.metric("Credible", "-")
        st.metric("Wrong", "-")

with stat_cols[3]:
    insufficient = len(df[df["Val Status"] == "Insufficient evidence"])
    weak = len(df[df["Val Status"] == "Weak evidence"])
    st.metric("Insufficient Evidence", insufficient)
    st.metric("Weak Evidence", weak)

# --- Filter helpers ---
st.divider()
st.subheader("Filtered Views")

filter_choice = st.selectbox(
    "Quick filter",
    ["All", "Undervalued (negative gap)", "Overpriced (positive gap)",
     "Insufficient evidence", "Weak evidence",
     "Viewed but not offered", "Not yet calibrated"],
)

if filter_choice == "Undervalued (negative gap)":
    filtered = df_sorted[df_sorted["Gap %"].apply(
        lambda x: isinstance(x, (int, float)) and x < -5
    )] if "Gap %" in df_sorted.columns else df_sorted.head(0)
elif filter_choice == "Overpriced (positive gap)":
    filtered = df_sorted[df_sorted["Gap %"].apply(
        lambda x: isinstance(x, (int, float)) and x > 5
    )]
elif filter_choice == "Insufficient evidence":
    filtered = df_sorted[df_sorted["Val Status"] == "Insufficient evidence"]
elif filter_choice == "Weak evidence":
    filtered = df_sorted[df_sorted["Val Status"] == "Weak evidence"]
elif filter_choice == "Viewed but not offered":
    filtered = df_sorted[(df_sorted["Viewed"] == "Yes") & (df_sorted["Offered"] != "Yes")]
elif filter_choice == "Not yet calibrated":
    filtered = df_sorted[df_sorted["Judgement"] == ""]
else:
    filtered = df_sorted

if filter_choice != "All":
    # Re-format for display
    filt_display = filtered.copy()
    for col in ["Asking", "Balanced"]:
        if col in filt_display.columns:
            filt_display[col] = filt_display[col].apply(
                lambda x: format_currency(x) if isinstance(x, (int, float)) and x else "-"
            )

    st.dataframe(
        filt_display[available] if len(filt_display) > 0 else pd.DataFrame(),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"{len(filtered)} properties match filter")
