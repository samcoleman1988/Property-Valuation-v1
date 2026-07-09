"""PDF report generator — investment decision report.

Produces a focused decision-support report using fpdf2.
Adapts content based on valuation status: insufficient evidence
gets a different report than a reliable valuation.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fpdf import FPDF

from .utils import format_currency, format_pct

REPORTS_DIR = Path(__file__).parent.parent / "outputs" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _s(text) -> str:
    """Sanitise text for Helvetica (latin-1 only)."""
    if not isinstance(text, str):
        text = str(text)
    replacements = {
        "—": " - ", "–": " - ",
        "‘": "'", "’": "'",
        "“": '"', "”": '"',
        "…": "...", "•": "- ",
        "²": "2", "³": "3",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class PropertyReport(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Property Investment Decision Report", align="L")
        self.cell(0, 8, datetime.now().strftime("%d %B %Y"), align="R",
                  new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str):
        self.ln(4)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, _s(title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(41, 128, 185)
        self.line(10, self.get_y(), 80, self.get_y())
        self.ln(3)

    def subsection(self, title: str):
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(50, 50, 50)
        self.cell(0, 8, _s(title), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, text: str):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.set_x(self.l_margin)
        self.multi_cell(0, 6, _s(text))
        self.ln(1)

    def kv(self, key: str, value, bold_value: bool = False):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(80, 80, 80)
        self.cell(70, 7, _s(key))
        self.set_text_color(30, 30, 30)
        self.set_font("Helvetica", "B" if bold_value else "", 10)
        self.cell(0, 7, _s(str(value)), new_x="LMARGIN", new_y="NEXT")

    def status_box(self, tagline: str, status: str, score: float):
        self.ln(3)
        if status == "Reliable":
            r, g, b = 230, 255, 230
            dr, dg, db = 34, 139, 34
        elif status == "Usable with caution":
            r, g, b = 240, 248, 255
            dr, dg, db = 41, 128, 185
        elif status == "Weak evidence":
            r, g, b = 255, 248, 230
            dr, dg, db = 200, 150, 0
        else:
            r, g, b = 255, 235, 235
            dr, dg, db = 200, 50, 50

        self.set_fill_color(r, g, b)
        self.set_draw_color(dr, dg, db)
        y = self.get_y()
        self.rect(10, y, 190, 28, style="DF")
        self.set_xy(15, y + 2)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(dr, dg, db)
        self.cell(0, 8, _s(tagline))
        self.set_xy(15, y + 12)
        self.set_font("Helvetica", "B", 10)
        self.cell(95, 8, _s(f"Valuation Status: {status}"))
        self.set_font("Helvetica", "", 10)
        self.set_text_color(80, 80, 80)
        self.cell(0, 8, f"Overall Score: {score:.0f}/100")
        self.set_y(y + 32)

    def warn(self, text: str):
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(180, 80, 0)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5, _s(f"! {text}"))
        self.set_text_color(40, 40, 40)
        self.ln(1)

    def risk_row(self, severity: str, title: str, explanation: str, mitigation: str):
        if severity == "High":
            self.set_text_color(200, 30, 30)
        elif severity == "Medium":
            self.set_text_color(200, 130, 0)
        else:
            self.set_text_color(60, 60, 60)
        self.set_font("Helvetica", "B", 10)
        self.set_x(self.l_margin)
        self.multi_cell(0, 6, _s(f"[{severity}] {title}"))
        self.set_font("Helvetica", "", 9)
        self.set_text_color(60, 60, 60)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5, _s(explanation))
        if mitigation:
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(80, 80, 80)
            self.set_x(self.l_margin)
            self.multi_cell(0, 5, _s(f"Mitigation: {mitigation}"))
        self.ln(2)

    def add_table(self, headers: list, rows: list,
                  col_widths: Optional[list] = None):
        if not rows:
            self.body("No data available.")
            return
        n_cols = len(headers)
        if col_widths is None:
            col_widths = [190 / n_cols] * n_cols

        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(41, 128, 185)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, _s(h), border=1, fill=True)
        self.ln()

        self.set_font("Helvetica", "", 8)
        self.set_text_color(40, 40, 40)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(245, 245, 245)
            else:
                self.set_fill_color(255, 255, 255)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6, _s(str(cell)[:45]),
                          border=1, fill=True)
            self.ln()
            fill = not fill
        self.ln(2)


def generate_report(
    listing: dict,
    valuation: dict,
    planning: dict,
    btl: dict,
    location: dict,
    investment_score: dict,
    mode: str = "personal",
    v2_result=None,
    v2_explanation=None,
) -> str:
    """Generate the full investment decision PDF report."""
    pdf = PropertyReport()
    pdf.alias_nb_pages()
    pdf.add_page()

    address = listing.get("address", "Unknown Address")
    v_status = valuation.get("valuation_status", "Unknown")
    tagline = valuation.get("investment_tagline", "")
    overall = investment_score.get("overall_score", 0)
    insufficient = v_status == "Insufficient evidence"
    weak = v_status == "Weak evidence"
    sec = [0]

    def next_sec():
        sec[0] += 1
        return sec[0]

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 10, _s(address))
    pdf.ln(1)

    # Status box
    pdf.status_box(tagline, v_status, overall)

    # === 1. Executive Summary ===
    pdf.section_title(f"{next_sec()}. Executive Summary")

    if insufficient:
        pdf.body(
            "A reliable valuation could not be produced for this property. "
            "The comparable evidence available is insufficient to estimate fair value."
        )
        # Why
        pdf.subsection("Why evidence is insufficient")
        for w in valuation.get("warnings", []):
            pdf.body(f"- {w}")
        for d in valuation.get("confidence_drivers", []):
            pdf.body(f"- {d}")

        # What's missing
        pdf.subsection("Data gaps")
        for g in valuation.get("data_gaps", []):
            pdf.body(f"- {g}")

        # Is it still worth investigating?
        pdf.subsection("Is this property worth further investigation?")
        pdf.body(
            "Insufficient comparable evidence does not mean the property is a bad investment. "
            "It means the tool cannot assess it automatically. "
            "Consider commissioning a RICS valuation, requesting agent comparable evidence, "
            "or searching Rightmove/Zoopla sold prices for the specific street."
        )
    else:
        rec = investment_score.get("recommendation", "")
        if rec:
            pdf.body(rec)
        verdict = investment_score.get("verdict", "")
        if verdict:
            pdf.body(f"Verdict: {verdict}")
        if weak:
            pdf.warn(
                "This valuation is based on weak evidence. "
                "Treat all figures as a rough guide only. "
                "Manual research is strongly recommended before making an offer."
            )

    # === 2. Property Details ===
    pdf.section_title(f"{next_sec()}. Property Details")
    pdf.kv("Address", address)
    pdf.kv("Postcode", listing.get("postcode", "N/A"))
    pdf.kv("Type", listing.get("property_type", "N/A"))
    pdf.kv("Bedrooms", str(listing.get("bedrooms", "N/A")))
    pdf.kv("Bathrooms", str(listing.get("bathrooms", "N/A")))
    pdf.kv("Tenure", listing.get("tenure", "N/A"))
    sqft = listing.get("floor_area_sqft", 0)
    sqm = listing.get("floor_area_sqm", 0)
    fa_source = listing.get("floor_area_source", "Unknown")
    if sqft:
        pdf.kv("Floor Area", f"{sqft:,.0f} sq ft ({sqm:,.0f} sq m) — source: {fa_source}")
    else:
        pdf.kv("Floor Area", f"Unknown — {fa_source}")
    pdf.kv("EPC Rating", listing.get("epc_rating", "N/A"))
    pdf.kv("Agent", listing.get("agent_name", "N/A"))
    for w in listing.get("extraction_warnings", []):
        pdf.warn(w)

    # === 3. Valuation ===
    pdf.section_title(f"{next_sec()}. Valuation")
    pdf.kv("Valuation Status", v_status, bold_value=True)
    asking = valuation.get("asking_price", 0)
    pdf.kv("Asking Price", format_currency(asking), bold_value=True)

    if insufficient:
        pdf.body(
            "Fair value could not be estimated reliably. "
            "See Executive Summary for details and recommended next steps."
        )
    else:
        balanced = valuation.get("fair_value_balanced", 0)
        conservative = valuation.get("fair_value_conservative", 0)
        aggressive = valuation.get("fair_value_aggressive", 0)

        if balanced:
            label = "Fair Value (Balanced)"
            if weak:
                label += " [TENTATIVE]"
            pdf.kv(label, format_currency(balanced), bold_value=True)
        if conservative:
            pdf.kv("Fair Value (Conservative)", format_currency(conservative))
        else:
            pdf.kv("Fair Value (Conservative)", "Not produced (evidence too weak)")
        if aggressive:
            pdf.kv("Fair Value (Aggressive)", format_currency(aggressive))
        else:
            pdf.kv("Fair Value (Aggressive)", "Not produced (evidence too weak)")
        pdf.ln(2)

        gap_pct = valuation.get("asking_vs_fair_gap_pct", 0)
        gap = valuation.get("asking_vs_fair_gap", 0)
        if gap_pct:
            pdf.kv("Asking vs Fair Value",
                    f"{format_currency(gap)} ({gap_pct:+.1f}%)", bold_value=True)

        sqm_asking = valuation.get("price_per_sqm_asking", 0)
        sqm_comp = valuation.get("price_per_sqm_comparable", 0)
        if sqm_asking:
            pdf.kv("Asking Price / sqm", format_currency(sqm_asking))
        if sqm_comp:
            pdf.kv("Comparable / sqm", format_currency(sqm_comp))

        pdf.ln(1)
        pdf.kv("Confidence",
               f"{valuation.get('confidence_score', 0)}/100 - {valuation.get('confidence_label', 'N/A')}")
        pdf.kv("Method", valuation.get("valuation_method", "N/A"))

        spread_cv = valuation.get("comparable_spread_cv", 0)
        if spread_cv:
            pdf.kv("Comparable Spread (CV)", f"{spread_cv:.0%}")
            if not valuation.get("spread_acceptable", True):
                pdf.warn("Comparable price spread exceeds acceptable limits. "
                         "Valuation precision is reduced.")

    # === 4. Offer Strategy ===
    if not insufficient:
        initial = valuation.get("suggested_initial_offer", 0)
        max_offer = valuation.get("max_sensible_offer", 0)
        walkaway = valuation.get("walk_away_price", 0)
        if initial or max_offer:
            pdf.section_title(f"{next_sec()}. Offer Strategy")
            if weak:
                pdf.warn("Offer figures below are based on weak evidence. "
                         "Do not rely on them without additional research.")
            if initial:
                pdf.kv("Suggested Opening Offer", format_currency(initial), bold_value=True)
            if max_offer:
                pdf.kv("Maximum Sensible Offer", format_currency(max_offer), bold_value=True)
            if walkaway:
                pdf.kv("Walk-Away Price", format_currency(walkaway))
            reasoning = valuation.get("negotiation_reasoning", "")
            if reasoning:
                pdf.ln(1)
                pdf.body(reasoning)

    # === 5. Comparable Evidence ===
    pdf.add_page()
    pdf.section_title(f"{next_sec()}. Comparable Evidence")

    # Evidence quality summary
    pdf.subsection("Evidence Quality")
    pdf.kv("Raw comparables fetched", str(valuation.get("comparables_used", 0)))
    evidence_summary = valuation.get("evidence_summary", "")
    if evidence_summary:
        pdf.body(evidence_summary)

    for d in valuation.get("confidence_drivers", []):
        pdf.body(f"- {d}")

    # Comparable table
    comps = valuation.get("comparable_details", [])
    if comps:
        pdf.subsection("Comparable Sales")
        headers = ["Address", "Price", "Adj Price", "Date", "Type", "Tier", "Score"]
        col_widths = [52, 22, 22, 22, 28, 20, 24]
        rows = []
        for c in comps[:15]:
            tier = c.get("tier", c.get("quality_band", ""))
            rows.append([
                c.get("address", "")[:28],
                format_currency(c.get("price", 0)),
                format_currency(c.get("adjusted_price", 0)) if c.get("adjusted_price") else "-",
                str(c.get("date", ""))[:11],
                c.get("property_type", "")[:14],
                tier,
                str(c.get("quality_score", "")),
            ])
        pdf.add_table(headers, rows, col_widths=col_widths)
    else:
        pdf.body("No comparable evidence available.")

    # Warnings
    for w in valuation.get("warnings", []):
        pdf.warn(w)

    # === 6. Investment Scorecard ===
    pdf.section_title(f"{next_sec()}. Investment Scorecard")
    dim_list = investment_score.get("dimensions", [])
    if not dim_list:
        for dim_name in ["fair_value", "negotiation_opportunity",
                         "development_opportunity", "planning_confidence",
                         "rental_potential", "resale_potential",
                         "location_quality", "investment_risk"]:
            d = investment_score.get(dim_name, {})
            if isinstance(d, dict) and "score" in d:
                dim_list.append(d)

    for dim in dim_list:
        if not isinstance(dim, dict) or "score" not in dim:
            continue
        name = dim.get("name", "")
        score = dim.get("score", 0)
        label = dim.get("label", "")
        weight = dim.get("weight", 0)
        explanation = dim.get("explanation", "")
        pdf.kv(f"{name} ({weight:.0f}%)", f"{score}/10 ({label})")
        if explanation:
            pdf.body(f"  {explanation}")

    pdf.ln(2)
    pdf.kv("Overall Score", f"{overall:.0f}/100", bold_value=True)
    pdf.kv("Overall Label", investment_score.get("overall_label", ""))

    # Key risks and opportunities
    risks = investment_score.get("key_risks", [])
    opps = investment_score.get("key_opportunities", [])
    if risks:
        pdf.subsection("Key Risks")
        for r in risks:
            pdf.warn(r)
    if opps:
        pdf.subsection("Key Opportunities")
        for o in opps:
            pdf.body(f"+ {o}")

    # === 7. Risk Assessment ===
    risk_data = investment_score.get("risk_json", None)
    # risk data may be passed as a separate key or embedded
    # Try to find risk flags in the investment_score or via a separate param
    risk_flags = []
    # The caller may pass risk data in the investment_score dict
    if "flags" in investment_score:
        risk_flags = investment_score.get("flags", [])

    # If not in investment_score, the caller should have put it somewhere accessible
    # For now, we handle what we have
    if risk_flags:
        pdf.add_page()
        pdf.section_title(f"{next_sec()}. Risk Assessment")
        risk_summary = investment_score.get("summary", "")
        if risk_summary:
            pdf.body(risk_summary)
        for flag in risk_flags:
            if isinstance(flag, dict):
                pdf.risk_row(
                    flag.get("severity", ""),
                    flag.get("title", ""),
                    flag.get("explanation", ""),
                    flag.get("mitigation", ""),
                )

    # === Planning ===
    if planning:
        pdf.section_title(f"{next_sec()}. Planning & Development")
        constraints = planning.get("constraints_summary", [])
        if constraints:
            pdf.subsection("Constraints")
            for c in constraints:
                pdf.body(f"- {c}")
        else:
            pdf.body("No planning constraints identified.")

        # Extension scores if available
        ext_fields = [
            ("Rear Extension", "rear_extension_score"),
            ("Side Extension", "side_extension_score"),
            ("Loft Conversion", "loft_conversion_score"),
            ("Garage Conversion", "garage_conversion_score"),
            ("Outbuilding", "outbuilding_score"),
        ]
        has_ext = any(planning.get(f, 0) for _, f in ext_fields)
        if has_ext:
            pdf.subsection("Extension Potential (0-10)")
            for label, field in ext_fields:
                score = planning.get(field, 0)
                if score:
                    pdf.kv(label, f"{score}/10")

        build_items = planning.get("build_cost_breakdown", [])
        if build_items:
            pdf.subsection("Estimated Build Costs")
            for item in build_items:
                pdf.kv(item.get("type", ""),
                       f"{format_currency(item.get('cost_low', 0))} - "
                       f"{format_currency(item.get('cost_high', 0))}")

        for w in planning.get("warnings", []):
            pdf.warn(w)

    # === BTL ===
    if mode in ("btl", "both") and btl:
        pdf.section_title(f"{next_sec()}. Buy-to-Let Assessment")
        pdf.kv("Estimated Monthly Rent",
               format_currency(btl.get("estimated_monthly_rent", 0)))
        pdf.kv("Gross Yield", f"{btl.get('gross_yield', 0):.1f}%")
        pdf.kv("Net Yield (est.)", f"{btl.get('net_yield_estimate', 0):.1f}%")
        pdf.kv("BTL Score", f"{btl.get('btl_score', 0)}/10")
        pdf.kv("BTL Verdict", btl.get("btl_verdict", "N/A"), bold_value=True)

        for r in btl.get("risk_factors", []):
            pdf.warn(r)
        for w in btl.get("warnings", []):
            pdf.warn(w)

    # === Location ===
    pdf.section_title(f"{next_sec()}. Location & Commute")
    pdf.kv("Location Score", f"{location.get('location_score', 0)}/10")
    for d in location.get("distances", []):
        pdf.kv(d.get("name", ""),
               f"{d.get('distance_miles', 0)} miles ({d.get('drive_time_estimate', '')})")
    for w in location.get("warnings", []):
        pdf.warn(w)

    # === Data Gaps ===
    data_gaps = valuation.get("data_gaps", [])
    if data_gaps:
        pdf.section_title(f"{next_sec()}. Data Gaps")
        for g in data_gaps:
            pdf.body(f"- {g}")

    # === Assumptions ===
    assumptions = valuation.get("assumptions", [])
    if assumptions:
        pdf.section_title(f"{next_sec()}. Assumptions")
        for a in assumptions:
            pdf.body(f"- {a}")

    # === Final Recommendation ===
    pdf.section_title(f"{next_sec()}. Final Recommendation")
    if insufficient:
        pdf.body(
            "A reliable valuation could not be produced. "
            "Do not make an offer based solely on this report. "
            "Commission manual research before proceeding."
        )
        pdf.body(
            "Recommended next steps: "
            "(1) Search Rightmove/Zoopla sold prices for the specific street. "
            "(2) Request agent comparable evidence. "
            "(3) Check Land Registry for nearby sales of the same property type. "
            "(4) Consider a RICS valuation."
        )
    else:
        pdf.body(investment_score.get("recommendation",
                                      "No recommendation available."))

    # === V2 Diagnostic Sections ===
    if v2_result is not None and v2_explanation is not None:
        pdf.add_page()
        pdf.section_title(f"{next_sec()}. Evidence-Based Valuation (V2)")
        pdf.body(
            "This section presents the V2 four-group evidence engine analysis, "
            "which is the primary valuation methodology for this report."
        )

        # V2 summary
        v2f = v2_result.final
        pdf.subsection("Valuation Summary")
        pdf.kv("Fair Value (Balanced)", format_currency(v2f.fair_value_balanced) if v2f.fair_value_balanced else "Insufficient data", bold_value=True)
        pdf.kv("Fair Value (Conservative)", format_currency(v2f.fair_value_conservative) if v2f.fair_value_conservative else "-")
        pdf.kv("Fair Value (Aggressive)", format_currency(v2f.fair_value_aggressive) if v2f.fair_value_aggressive else "-")
        pdf.kv("Confidence", f"{v2f.confidence_score}/100 - {v2f.confidence_label}")

        # Evidence groups
        pdf.subsection("Evidence Groups")
        for g in v2_result.groups:
            if g.comp_count > 0:
                weight_str = f"{g.weight_in_final:.0%}" if g.weight_in_final > 0 else "n/a"
                val_str = format_currency(g.valuation) if g.valuation > 0 else "n/a"
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
                status_str = f" | {g.evidence_status}"
                pdf.kv(g.name, f"{g.comp_count} comps | {val_str} | {g.confidence_label} ({g.confidence_score}) | Wt: {weight_str}{status_str}{eq_str}{type_str}")
            else:
                pdf.kv(g.name, "No qualifying comparables")

        # Executive Summary
        pdf.subsection("Why Is This Worth What It Is?")
        pdf.body(v2_explanation.executive_summary)

        # Key Value Drivers
        pdf.subsection("Key Value Drivers")
        for d in v2_explanation.key_drivers:
            arrow = {"raises value": "[+]", "lowers value": "[-]", "neutral": "[=]"}.get(d.direction, "[?]")
            pdf.body(f"{arrow} {d.title} ({d.impact}): {d.explanation}")

        # Evidence Hierarchy
        pdf.subsection("Evidence Hierarchy")
        for h in v2_explanation.evidence_hierarchy:
            weight_str = f"{h.weighting:.0%}" if h.weighting > 0 else "n/a"
            val_str = format_currency(h.valuation) if h.valuation > 0 else "n/a"
            pdf.body(f"{h.group_name}: Confidence {h.confidence} | Valuation {val_str} | Weight {weight_str}")
            if h.representative:
                pdf.body(f"  Representative: {h.representative}")

        # Confidence
        pdf.subsection("Confidence Explanation")
        pdf.body(v2_explanation.confidence_explanation)

        # Offer Rationale
        pdf.subsection("Offer Rationale")
        pdf.body(v2_explanation.offer_rationale)

        # Why Not Highest
        if v2_explanation.why_not_highest:
            pdf.subsection("Why Not the Highest Sale?")
            pdf.body(v2_explanation.why_not_highest)

        # Conflicts
        if v2_explanation.evidence_conflicts:
            pdf.subsection("Evidence Conflicts")
            pdf.body(v2_explanation.evidence_conflicts)

        # Risks
        pdf.subsection("Risks")
        if v2_explanation.risks:
            for r in v2_explanation.risks:
                pdf.warn(r)
        else:
            pdf.body("No material valuation risks identified.")

        # Strengths
        pdf.subsection("Strengths")
        for s in v2_explanation.strengths:
            pdf.body(f"+ {s}")

        # Overall Verdict
        pdf.subsection("Overall Verdict")
        pdf.body(v2_explanation.overall_verdict)

    # Disclaimer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(140, 140, 140)
    pdf.multi_cell(0, 4, _s(
        "DISCLAIMER: This report is generated automatically using publicly available data "
        "and rule-based estimates. It is not a formal valuation and should not be relied upon "
        "as the sole basis for purchasing decisions. Always commission a professional survey "
        "and valuation. Data may be incomplete, outdated, or inaccurate. All estimates and "
        "projections are indicative only."
    ))

    # Save
    safe_addr = "".join(c for c in address[:40]
                        if c.isalnum() or c in " -_").strip().replace(" ", "_")
    filename = f"report_{safe_addr}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = REPORTS_DIR / filename
    pdf.output(str(filepath))
    return str(filepath)
