"""Explainable Valuation Engine — RICS-style narrative explanations.

Consumes the completed V2 ValuationEvidence and generates structured,
plain-English explanations of how the valuation was reached.

Never invents evidence. Never exposes calculations. Never says "AI thinks".
"""

from dataclasses import dataclass, field
from typing import List

from .valuation_engine_v2 import ValuationEvidence, EvidenceGroup, FinalValuation
from .rightmove_parser import PropertyListing


@dataclass
class KeyDriver:
    title: str = ""
    direction: str = ""  # "raises value" / "lowers value" / "neutral"
    impact: str = ""     # "High" / "Medium" / "Low"
    explanation: str = ""


@dataclass
class EvidenceHierarchyItem:
    group_name: str = ""
    confidence: str = ""
    valuation: float = 0.0
    weighting: float = 0.0
    representative: str = ""
    summary: str = ""


@dataclass
class ValuationExplanation:
    executive_summary: str = ""
    key_drivers: List[KeyDriver] = field(default_factory=list)
    why_not_highest: str = ""
    evidence_hierarchy: List[EvidenceHierarchyItem] = field(default_factory=list)
    evidence_conflicts: str = ""
    confidence_explanation: str = ""
    offer_rationale: str = ""
    risks: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    overall_verdict: str = ""


def _fmt(v: float) -> str:
    if v >= 1_000_000:
        return f"£{v / 1_000_000:,.2f}m"
    return f"£{v:,.0f}"


def _street_from_comp(c) -> str:
    if c.street:
        return c.street
    if c.address:
        return c.address.split(",")[0].strip()
    return "the comparable address"


def _short_address(c) -> str:
    parts = []
    if c.paon:
        parts.append(c.paon)
    if c.street:
        parts.append(c.street)
    if parts:
        return " ".join(parts)
    if c.address:
        return c.address.split(",")[0].strip()
    return "comparable property"


def _age_desc(days: int) -> str:
    if days <= 90:
        return "very recently"
    if days <= 365:
        months = max(1, days // 30)
        return f"approximately {months} months ago"
    years = days / 365.25
    if years < 1.5:
        return "just over a year ago"
    return f"approximately {years:.0f} years ago"


def _type_label(code: str) -> str:
    labels = {
        "D": "detached house", "S": "semi-detached house",
        "T": "terraced house", "F": "flat", "O": "other",
    }
    return labels.get(code, "property")


def explain_valuation(
    v2: ValuationEvidence,
    listing: PropertyListing,
) -> ValuationExplanation:
    """Generate a full RICS-style explanation from completed V2 output."""
    expl = ValuationExplanation()

    expl.executive_summary = _build_executive_summary(v2, listing)
    expl.key_drivers = _build_key_drivers(v2, listing)
    expl.why_not_highest = _build_why_not_highest(v2, listing)
    expl.evidence_hierarchy = _build_evidence_hierarchy(v2)
    expl.evidence_conflicts = _build_conflict_narrative(v2)
    expl.confidence_explanation = _build_confidence_explanation(v2, listing)
    expl.offer_rationale = _build_offer_rationale(v2, listing)
    expl.risks = _build_risks(v2, listing)
    expl.strengths = _build_strengths(v2, listing)
    expl.overall_verdict = _build_overall_verdict(v2, listing)

    return expl


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_executive_summary(v2: ValuationEvidence, listing: PropertyListing) -> str:
    final = v2.final
    sentences = []

    active = v2.active_groups
    if not active:
        return "Insufficient comparable evidence is available to produce a reliable valuation."

    dominant = v2.final.reconciliation.dominant_group or ""
    direct = v2.direct
    dev = v2.development
    local = v2.local_market

    # Lead with the strongest evidence, distinguishing trustworthy from fallback
    if direct.comp_count > 0 and direct.valuation > 0:
        street = _street_from_comp(direct.comparables[0]) if direct.comparables else "the same street"
        if direct.evidence_status == "FALLBACK_ONLY":
            sentences.append(
                f"Same-street sales were found on {street}, but none involve "
                f"a comparable property type. This evidence was treated as "
                f"contextual information only, not as a reliable valuation anchor."
            )
        elif direct.comp_count == 1:
            sentences.append(
                f"The strongest evidence comes from a recent sale on {street}."
            )
        else:
            sentences.append(
                f"The strongest evidence comes from {direct.comp_count} "
                f"recent sales on {street}."
            )
            sentences.append(
                f"Those sales suggest a value in the region of {_fmt(direct.valuation)}."
            )
    elif dev.comp_count > 0 and dev.valuation > 0:
        if dev.evidence_status == "FALLBACK_ONLY":
            sentences.append(
                f"Development-level sales were identified, but none involve "
                f"a compatible property type. This evidence was treated as "
                f"contextual information only."
            )
        else:
            sentences.append(
                f"In the absence of same-street sales, the primary evidence comes from "
                f"{dev.comp_count} sales within the wider development."
            )
            sentences.append(
                f"Development-level evidence suggests a value around {_fmt(dev.valuation)}."
            )

    # Mention supporting or contrasting evidence
    if local.comp_count > 0 and local.valuation > 0:
        if direct.comp_count > 0 and direct.valuation > 0:
            diff_pct = abs(local.valuation - direct.valuation) / direct.valuation
            if diff_pct < 0.08:
                sentences.append(
                    f"Broader local market evidence from {local.comp_count} sales "
                    f"in the same postcode sector supports a similar level."
                )
            elif local.valuation < direct.valuation:
                sentences.append(
                    f"Broader local market evidence from {local.comp_count} sales "
                    f"indicates slightly lower prices around {_fmt(local.valuation)}."
                )
            else:
                sentences.append(
                    f"Broader local market evidence from {local.comp_count} sales "
                    f"suggests slightly higher prices around {_fmt(local.valuation)}."
                )
        elif dev.comp_count > 0 and dev.valuation > 0:
            sentences.append(
                f"This is supported by {local.comp_count} wider local market sales."
            )

    # Explain weighting rationale
    n_active = len(active)
    if n_active >= 2:
        if direct.comp_count > 0 and direct.comp_count <= 3:
            sentences.append(
                "Because direct evidence is limited but relevant, the valuation "
                "is weighted towards those nearby sales while allowing wider "
                "market evidence to moderate the result."
            )
        elif direct.comp_count > 3:
            sentences.append(
                "With strong direct evidence available, the valuation relies "
                "primarily on same-street sales, with wider evidence providing "
                "a cross-check."
            )
        elif dev.comp_count > 0:
            sentences.append(
                "Without same-street comparables, the valuation draws primarily "
                "on development-level evidence, moderated by the local market."
            )
    elif n_active == 1:
        g = active[0]
        sentences.append(
            f"The valuation rests on a single evidence source ({g.name}), "
            f"which limits the reliability of the estimate."
        )

    return "\n\n".join(sentences)


def _build_key_drivers(v2: ValuationEvidence, listing: PropertyListing) -> List[KeyDriver]:
    drivers = []
    final = v2.final
    direct = v2.direct
    dev = v2.development
    local = v2.local_market

    # Direct evidence strength
    if direct.comp_count > 0:
        if direct.evidence_status == "FALLBACK_ONLY":
            drivers.append(KeyDriver(
                title="Direct evidence is fallback only",
                direction="lowers value",
                impact="High",
                explanation=(
                    f"{direct.comp_count} same-street sale(s) exist, but none are a compatible "
                    f"property type. This evidence was treated as contextual only, "
                    f"not as a reliable valuation anchor."
                ),
            ))
        elif direct.comp_count >= 3:
            drivers.append(KeyDriver(
                title="Strong same-street evidence",
                direction="raises value" if direct.valuation >= (final.fair_value_balanced or 1) else "neutral",
                impact="High",
                explanation=f"{direct.comp_count} comparable sales on the same street provide a strong local anchor.",
            ))
        elif direct.comp_count >= 1:
            drivers.append(KeyDriver(
                title="Same-street comparable available",
                direction="neutral",
                impact="High",
                explanation=(
                    f"{direct.comp_count} sale(s) on the same street. "
                    f"While not extensive, same-street evidence carries significant weight."
                ),
            ))
            drivers.append(KeyDriver(
                title="Limited direct evidence",
                direction="lowers value",
                impact="Medium",
                explanation=(
                    f"Only {direct.comp_count} same-street sale(s) available, "
                    f"limiting the ability to triangulate the valuation."
                ),
            ))
    else:
        drivers.append(KeyDriver(
            title="No same-street comparables",
            direction="lowers value",
            impact="Medium",
            explanation="No recent sales on the same street were found, reducing confidence in the valuation.",
        ))

    # Recency
    if direct.comparables:
        most_recent = min(c.age_days for c in direct.comparables)
        if most_recent <= 180:
            drivers.append(KeyDriver(
                title="Very recent comparable sale",
                direction="neutral",
                impact="High",
                explanation=f"The most recent same-street sale occurred {_age_desc(most_recent)}, reflecting current market conditions.",
            ))
        elif most_recent <= 365:
            drivers.append(KeyDriver(
                title="Reasonably recent comparable",
                direction="neutral",
                impact="Medium",
                explanation=f"The most recent same-street sale occurred {_age_desc(most_recent)}.",
            ))
        elif most_recent <= 730:
            drivers.append(KeyDriver(
                title="Recent comparable available",
                direction="neutral",
                impact="Medium",
                explanation=f"The most recent same-street sale occurred {_age_desc(most_recent)}.",
            ))
        else:
            drivers.append(KeyDriver(
                title="Dated comparable evidence",
                direction="lowers value",
                impact="Medium",
                explanation=f"The most recent same-street sale was {_age_desc(most_recent)}. Market conditions may have shifted.",
            ))

    # Floor area
    sqm = listing.floor_area_sqm or 0
    source = listing.floor_area_source or ""
    if sqm > 0 and source:
        if direct.comparables:
            comp_sqms = [c.floor_area_sqm for c in direct.comparables if c.floor_area_sqm > 0]
            if comp_sqms:
                avg_comp_sqm = sum(comp_sqms) / len(comp_sqms)
                ratio = sqm / avg_comp_sqm if avg_comp_sqm > 0 else 1.0
                if ratio < 0.85:
                    drivers.append(KeyDriver(
                        title="Smaller floor area than comparables",
                        direction="lowers value",
                        impact="Medium",
                        explanation=f"At {sqm:.0f} sqm, the subject is smaller than several nearby comparables, which tends to reduce the achievable price.",
                    ))
                elif ratio > 1.15:
                    drivers.append(KeyDriver(
                        title="Larger floor area than comparables",
                        direction="raises value",
                        impact="Medium",
                        explanation=f"At {sqm:.0f} sqm, the subject is larger than several nearby comparables, which may support a higher price.",
                    ))
                else:
                    drivers.append(KeyDriver(
                        title="Floor area confirmed",
                        direction="neutral",
                        impact="Low",
                        explanation=f"Floor area of {sqm:.0f} sqm ({source}) is broadly similar to nearby comparables.",
                    ))
    elif sqm == 0:
        drivers.append(KeyDriver(
            title="No confirmed floor area",
            direction="lowers value",
            impact="Low",
            explanation="Floor area is not confirmed, preventing size-adjusted comparison with nearby sales.",
        ))

    # Evidence breadth
    n_active = len(v2.active_groups)
    if n_active >= 3:
        drivers.append(KeyDriver(
            title="Multiple evidence sources",
            direction="neutral",
            impact="Medium",
            explanation=f"{n_active} independent evidence groups contribute to the valuation, providing cross-checks.",
        ))
    elif n_active == 1:
        drivers.append(KeyDriver(
            title="Single evidence source",
            direction="lowers value",
            impact="Medium",
            explanation="The valuation relies on a single evidence group, which limits the ability to cross-check.",
        ))

    # Asking price vs fair value
    if final.fair_value_balanced > 0 and listing.asking_price > 0:
        gap_pct = final.asking_vs_fair_gap_pct
        if gap_pct > 10:
            drivers.append(KeyDriver(
                title="Asking price above evidence",
                direction="lowers value",
                impact="High",
                explanation=f"The asking price is {gap_pct:.0f}% above the evidence-based fair value, suggesting the property may be overpriced.",
            ))
        elif gap_pct < -10:
            drivers.append(KeyDriver(
                title="Asking price below evidence",
                direction="raises value",
                impact="High",
                explanation=f"The asking price is {abs(gap_pct):.0f}% below the evidence-based fair value, which may represent good value.",
            ))

    # Conflict between groups
    if v2.final.reconciliation.conflicts:
        for conflict in v2.final.reconciliation.conflicts:
            severity = "High" if "Major" in conflict else "Medium"
            drivers.append(KeyDriver(
                title="Conflicting evidence",
                direction="lowers value",
                impact=severity,
                explanation="Different evidence groups produce materially different valuations, increasing uncertainty.",
            ))

    # Sort: High first, then Medium, then Low
    rank = {"High": 0, "Medium": 1, "Low": 2}
    drivers.sort(key=lambda d: rank.get(d.impact, 3))

    return drivers


def _build_why_not_highest(v2: ValuationEvidence, listing: PropertyListing) -> str:
    all_comps = []
    for g in v2.active_groups:
        all_comps.extend(g.comparables)

    if not all_comps:
        return "Insufficient evidence to identify comparable sale prices."

    highest = max(all_comps, key=lambda c: c.adjusted_price)
    fair = v2.final.fair_value_balanced

    if fair <= 0:
        return ""

    if highest.adjusted_price <= fair * 1.02:
        return (
            f"The highest comparable sale achieved {_fmt(highest.adjusted_price)} "
            f"at {_short_address(highest)}, which is broadly in line with the "
            f"assessed fair value."
        )

    reasons = []

    # Size difference
    subj_sqm = listing.floor_area_sqm or 0
    if subj_sqm > 0 and highest.floor_area_sqm > 0:
        if highest.floor_area_sqm > subj_sqm * 1.10:
            reasons.append(
                f"that property is larger ({highest.floor_area_sqm:.0f} sqm "
                f"versus {subj_sqm:.0f} sqm for the subject)"
            )
        elif highest.floor_area_sqm < subj_sqm * 0.90:
            reasons.append(
                f"although smaller in floor area, it may reflect different "
                f"property characteristics or condition"
            )

    # Type difference (skip if types are essentially the same)
    subj_type = listing.property_type or ""
    comp_type = highest.property_type or _type_label(highest.property_type_code)
    if subj_type and comp_type:
        s_norm = subj_type.lower().replace("/maisonette", "").replace("house", "").strip()
        c_norm = comp_type.lower().replace("/maisonette", "").replace("house", "").strip()
        if s_norm != c_norm:
            reasons.append(f"it is a {comp_type.lower()} rather than a {subj_type.lower()}")

    # Age of sale
    if highest.age_days > 730:
        reasons.append(
            f"that sale took place {_age_desc(highest.age_days)} and "
            f"may not reflect current conditions"
        )

    if reasons:
        reason_str = "; ".join(reasons)
        return (
            f"The highest nearby sale achieved {_fmt(highest.adjusted_price)} "
            f"at {_short_address(highest)}. However, {reason_str}. "
            f"The valuation therefore does not adopt this figure."
        )

    return (
        f"The highest nearby sale achieved {_fmt(highest.adjusted_price)} "
        f"at {_short_address(highest)}. The fair value is assessed below "
        f"this level as it represents a weighted assessment across all "
        f"available evidence rather than a single data point."
    )


def _build_evidence_hierarchy(v2: ValuationEvidence) -> List[EvidenceHierarchyItem]:
    items = []
    for g in v2.groups:
        rep_str = ""
        if g.representative:
            r = g.representative
            rep_str = (
                f"{_short_address(r)}, sold for {_fmt(r.adjusted_price)} "
                f"{_age_desc(r.age_days)}"
            )

        if g.comp_count > 0 and g.valuation > 0:
            if g.evidence_status == "FALLBACK_ONLY":
                summary = (
                    f"{g.comp_count} comparable(s) found, but no compatible property types "
                    f"available. Treated as contextual information only ({g.evidence_status_reason})."
                )
            elif g.evidence_status == "WEAK":
                summary = (
                    f"{g.comp_count} comparable(s) producing a group valuation "
                    f"of {_fmt(g.valuation)} (weak evidence: {g.evidence_status_reason})."
                )
            else:
                summary = (
                    f"{g.comp_count} comparable(s) producing a group valuation "
                    f"of {_fmt(g.valuation)}."
                )
        elif g.comp_count > 0:
            summary = f"{g.comp_count} comparable(s) identified but no valuation produced."
        else:
            summary = "No qualifying comparables found for this evidence group."

        items.append(EvidenceHierarchyItem(
            group_name=g.name,
            confidence=f"{g.confidence_label} ({g.confidence_score})" if g.confidence_score > 0 else g.confidence_label or "None",
            valuation=g.valuation,
            weighting=g.weight_in_final,
            representative=rep_str,
            summary=summary,
        ))

    return items


def _build_conflict_narrative(v2: ValuationEvidence) -> str:
    conflicts = v2.final.reconciliation.conflicts
    if not conflicts:
        active = v2.active_groups
        if len(active) >= 2:
            vals = [g.valuation for g in active if g.valuation > 0]
            if vals and len(vals) >= 2:
                spread = (max(vals) - min(vals)) / min(vals)
                if spread < 0.10:
                    return (
                        "The available evidence groups are broadly consistent, "
                        "which strengthens confidence in the valuation."
                    )
                return (
                    "There is some variation between evidence groups, "
                    "but no material conflict requiring special treatment."
                )
        return ""

    direct = v2.direct
    dev = v2.development
    local = v2.local_market

    parts = []

    if direct.valuation > 0 and dev.valuation > 0:
        if direct.valuation > dev.valuation:
            parts.append(
                f"Recent sales on the same street support a value around "
                f"{_fmt(direct.valuation)}."
            )
            parts.append(
                f"However, the wider development contains sales at lower "
                f"levels, with a group valuation of {_fmt(dev.valuation)}."
            )
        else:
            parts.append(
                f"Same-street sales suggest a value around {_fmt(direct.valuation)}."
            )
            parts.append(
                f"The wider development evidence indicates higher values, "
                f"with a group valuation of {_fmt(dev.valuation)}."
            )

    if local.valuation > 0 and direct.valuation > 0:
        if abs(local.valuation - direct.valuation) / direct.valuation > 0.15:
            if local.valuation < direct.valuation:
                parts.append(
                    f"The broader local market ({local.comp_count} sales) suggests "
                    f"lower prevailing values around {_fmt(local.valuation)}."
                )
            else:
                parts.append(
                    f"The broader local market ({local.comp_count} sales) suggests "
                    f"higher prevailing values around {_fmt(local.valuation)}."
                )

    parts.append(
        "The final valuation balances these competing pieces of evidence, "
        "weighting more heavily towards the most proximate and relevant sales."
    )

    return "\n\n".join(parts)


def _build_confidence_explanation(v2: ValuationEvidence, listing: PropertyListing) -> str:
    final = v2.final
    parts = [
        f"Confidence is {final.confidence_label} ({final.confidence_score}/100) because:"
    ]

    bullets = []

    # Direct evidence
    direct = v2.direct
    if direct.comp_count > 0:
        if direct.comp_count >= 3:
            bullets.append(f"{direct.comp_count} direct comparables provide a solid evidence base")
        elif direct.comp_count == 2:
            bullets.append("two direct comparables exist, providing limited but useful evidence")
        else:
            bullets.append("only one direct comparable exists")
    else:
        bullets.append("no same-street comparables were found")

    # Recency
    if direct.comparables:
        recent = [c for c in direct.comparables if c.age_days <= 365]
        if recent:
            bullets.append(f"{len(recent)} of these sold within the past year")
        else:
            oldest = min(c.age_days for c in direct.comparables)
            bullets.append(f"the most recent sale was {_age_desc(oldest)}")

    # Development
    dev = v2.development
    if dev.comp_count > 0:
        bullets.append(
            f"{dev.comp_count} development-level comparable(s) provide supporting evidence"
        )

    # Agreement between groups
    active = v2.active_groups
    if len(active) >= 2:
        vals = [g.valuation for g in active if g.valuation > 0]
        if len(vals) >= 2:
            spread = (max(vals) - min(vals)) / min(vals) if min(vals) > 0 else 0
            if spread < 0.10:
                bullets.append("the evidence groups agree closely")
            elif spread < 0.20:
                bullets.append("the evidence groups agree reasonably well")
            else:
                bullets.append("there is material divergence between evidence groups")

    # Floor area
    sqm = listing.floor_area_sqm or 0
    source = listing.floor_area_source or ""
    if sqm > 0 and source:
        bullets.append(f"floor area confirmed at {sqm:.0f} sqm ({source})")
    else:
        bullets.append("floor area is not confirmed")

    # Conflicts
    if v2.final.reconciliation.conflicts:
        for c in v2.final.reconciliation.conflicts:
            if "Major" in c:
                bullets.append("a major conflict between evidence groups reduces confidence")
            elif "Moderate" in c:
                bullets.append("a moderate conflict between evidence groups tempers confidence")

    bullet_str = "\n".join(f"  - {b}" for b in bullets)
    return parts[0] + "\n\n" + bullet_str


def _build_offer_rationale(v2: ValuationEvidence, listing: PropertyListing) -> str:
    final = v2.final
    if final.fair_value_balanced <= 0:
        return "Insufficient evidence to recommend an offer strategy."

    fair = final.fair_value_balanced
    conservative = final.fair_value_conservative
    asking = listing.asking_price or 0

    parts = []

    if conservative > 0:
        parts.append(
            f"The conservative valuation of {_fmt(conservative)} represents "
            f"the lower bound of the evidence-supported range."
        )

    parts.append(
        f"The balanced fair value of {_fmt(fair)} reflects the most likely "
        f"market value based on the available evidence."
    )

    if asking > 0:
        gap_pct = final.asking_vs_fair_gap_pct
        if gap_pct > 5:
            parts.append(
                f"The asking price of {_fmt(asking)} is {gap_pct:.0f}% above this level. "
                f"A material discount would be required to achieve fair value."
            )
        elif gap_pct < -5:
            parts.append(
                f"The asking price of {_fmt(asking)} is {abs(gap_pct):.0f}% below fair value, "
                f"which may indicate good value or reflect specific circumstances."
            )
        else:
            parts.append(
                f"The asking price of {_fmt(asking)} is broadly in line with the assessed fair value."
            )

    parts.append(
        f"Paying materially above {_fmt(fair)} would require believing "
        f"this property is superior to the strongest comparable sales."
    )

    return "\n\n".join(parts)


def _build_risks(v2: ValuationEvidence, listing: PropertyListing) -> List[str]:
    risks = []

    direct = v2.direct
    if direct.comp_count == 0:
        risks.append("No same-street comparable sales available.")
    elif direct.comp_count == 1:
        risks.append("Only one direct comparable, limiting triangulation.")

    if direct.comparables:
        oldest_recent = min(c.age_days for c in direct.comparables)
        if oldest_recent > 730:
            risks.append("Most recent comparable sale is over two years old.")

    if v2.final.reconciliation.conflicts:
        for c in v2.final.reconciliation.conflicts:
            if "Major" in c:
                risks.append("Major disagreement between evidence groups.")
            elif "Moderate" in c:
                risks.append("Moderate disagreement between evidence groups.")

    sqm = listing.floor_area_sqm or 0
    if sqm == 0:
        risks.append("No confirmed floor area, preventing size-adjusted analysis.")

    # Price spread in direct
    if direct.comp_count >= 2:
        prices = [c.adjusted_price for c in direct.comparables]
        import numpy as np
        cv = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 0
        if cv > 0.25:
            risks.append("Wide price spread among direct comparables.")

    # Mixed types
    if direct.comparables:
        types = set(c.property_type_code for c in direct.comparables if c.property_type_code)
        if len(types) > 1:
            risks.append("Mixed property types in comparable set.")

    local = v2.local_market
    if local.comp_count > 0 and local.comp_count < 5:
        risks.append("Thin local market data.")

    if v2.final.confidence_score < 40:
        risks.append("Overall confidence is below the threshold for reliable valuation.")

    return risks


def _build_strengths(v2: ValuationEvidence, listing: PropertyListing) -> List[str]:
    strengths = []

    direct = v2.direct
    if direct.comp_count >= 3:
        strengths.append(f"{direct.comp_count} same-street comparable sales.")
    elif direct.comp_count >= 1:
        strengths.append("Same-street comparable evidence available.")

    if direct.comparables:
        recent = [c for c in direct.comparables if c.age_days <= 365]
        if recent:
            strengths.append(f"{len(recent)} sale(s) within the past year.")

    active = v2.active_groups
    if len(active) >= 3:
        strengths.append("Three or more independent evidence groups contribute.")
    elif len(active) >= 2:
        strengths.append("Multiple evidence groups provide cross-checks.")

    # Agreement
    if len(active) >= 2:
        vals = [g.valuation for g in active if g.valuation > 0]
        if len(vals) >= 2:
            spread = (max(vals) - min(vals)) / min(vals) if min(vals) > 0 else 0
            if spread < 0.10:
                strengths.append("Strong agreement between evidence groups.")
            elif spread < 0.15:
                strengths.append("Reasonable agreement between evidence groups.")

    sqm = listing.floor_area_sqm or 0
    source = listing.floor_area_source or ""
    if sqm > 0 and source in ("EPC", "Rightmove"):
        strengths.append(f"Floor area confirmed from {source} ({sqm:.0f} sqm).")

    local = v2.local_market
    if local.comp_count >= 10:
        strengths.append(f"Strong local market sample ({local.comp_count} sales).")

    if v2.final.confidence_score >= 65:
        strengths.append("Overall confidence is high.")

    return strengths


def _build_overall_verdict(v2: ValuationEvidence, listing: PropertyListing) -> str:
    final = v2.final

    if final.fair_value_balanced <= 0:
        return (
            "The available evidence is insufficient to produce a reliable "
            "opinion of value. Additional comparable data would be required "
            "before making a purchase decision."
        )

    fair = final.fair_value_balanced
    asking = listing.asking_price or 0
    parts = []

    parts.append(
        f"Overall, the available evidence supports a fair value of "
        f"approximately {_fmt(fair)}."
    )

    # Evidence basis
    direct = v2.direct
    dev = v2.development
    local = v2.local_market

    if direct.comp_count > 0 and direct.valuation > 0:
        if direct.comp_count >= 3:
            parts.append(
                f"Same-street sales provide strong anchoring evidence and are "
                f"the primary basis for this assessment."
            )
        else:
            qualifier = "is" if direct.comp_count == 1 else "are"
            parts.append(
                f"Although the direct evidence base is not extensive, the "
                f"available same-street comparable{'' if direct.comp_count == 1 else 's'} "
                f"{qualifier} sufficiently similar to provide reasonable confidence."
            )
    elif dev.comp_count > 0:
        parts.append(
            f"Without same-street sales, the valuation draws on "
            f"{dev.comp_count} development-level comparable(s)."
        )

    if local.comp_count > 0 and direct.comp_count > 0:
        vals = [g.valuation for g in v2.active_groups if g.valuation > 0]
        if len(vals) >= 2:
            spread = (max(vals) - min(vals)) / min(vals) if min(vals) > 0 else 0
            if spread < 0.15:
                parts.append(
                    "This is broadly supported by wider local market activity."
                )
            else:
                parts.append(
                    "The wider local market shows some variation from "
                    "same-street values, which has been reflected in the "
                    "blended assessment."
                )

    # Asking price verdict
    if asking > 0:
        gap_pct = final.asking_vs_fair_gap_pct
        if gap_pct > 15:
            parts.append(
                f"At {_fmt(asking)}, the property appears significantly overpriced "
                f"relative to comparable evidence. Substantial negotiation would "
                f"be needed to achieve fair value."
            )
        elif gap_pct > 5:
            parts.append(
                f"The asking price is moderately above the assessed fair value. "
                f"Negotiation below the asking price would improve value for money."
            )
        elif gap_pct > -5:
            parts.append(
                "The property appears fairly priced relative to comparable evidence."
            )
        elif gap_pct > -15:
            parts.append(
                "The asking price is below the assessed fair value, which "
                "may represent an opportunity if the property is in good condition."
            )
        else:
            parts.append(
                "The asking price is substantially below the assessed fair value. "
                "This warrants investigation into whether there are factors "
                "not captured by the comparable evidence."
            )

    return "\n\n".join(parts)
