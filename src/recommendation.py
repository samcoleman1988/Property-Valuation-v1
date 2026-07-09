"""Single source of truth for pricing recommendations.

This module owns the ONLY logic in the application that decides:
- pricing classification (overpriced / undervalued / fairly priced / etc.)
- investment tagline
- negotiation stance
- suggested initial offer / max sensible offer / walk-away price
- offer reasoning

It is deliberately engine-agnostic: build_recommendation() takes primitive
values (fair value, gap %, valuation status), never a ValuationResult or
FinalValuation object directly. Both V1 (valuation_engine.py) and V2
(valuation_engine_v2.py) call this same function with their own numbers at
the end of their own pipeline — never with each other's numbers. Nothing
else in the application should independently decide these concepts; every
consumer (banner, scorecard, risk assessor, PDF) reads the Recommendation
object that was already built.
"""

from dataclasses import dataclass, field, asdict
from typing import List

from .config import get_config
from .utils import format_currency


@dataclass
class Recommendation:
    """The one and only pricing/offer recommendation for a valuation.

    Built once per valuation run, from exactly one engine's own numbers
    (source_engine records which). Every UI surface, PDF section, and
    scorecard/risk-assessor consumer should read this object rather than
    recompute any of its fields.
    """

    source_engine: str = ""  # "V1" or "V2" — always explicit, never ambiguous

    # --- Core inputs, carried through for traceability ---
    fair_value_used: float = 0.0
    asking_price: float = 0.0
    gap_pct: float = 0.0
    valuation_status: str = ""

    # --- The single pricing classification, used everywhere ---
    # One of: "Insufficient evidence", "Weak evidence", "Undervalued",
    # "Slightly undervalued", "Fairly priced", "Slightly above fair value",
    # "Overpriced"
    pricing_classification: str = ""

    # --- User-facing text ---
    investment_tagline: str = ""
    negotiation_stance: str = ""
    offer_reasoning: str = ""

    # --- Offer strategy numbers ---
    suggested_initial_offer: float = 0.0
    max_sensible_offer: float = 0.0
    walk_away_price: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# Thresholds are the exact boundaries previously used by V1's
# _generate_tagline() / _calculate_offer_strategy() — moved here verbatim,
# not re-derived, so V1's existing behaviour is unchanged after the move.
_UNDERVALUED_THRESHOLD = -10
_SLIGHTLY_UNDERVALUED_THRESHOLD = -5
_SLIGHTLY_ABOVE_THRESHOLD = 5
_OVERPRICED_THRESHOLD = 15

# Offer strategy is only computed when the valuation is trustworthy enough
# to act on — same condition V1 used to gate _calculate_offer_strategy().
_OFFER_ELIGIBLE_STATUSES = ("Reliable", "Usable with caution")


def _classify_gap(gap_pct: float) -> str:
    if gap_pct <= _UNDERVALUED_THRESHOLD:
        return "Undervalued"
    if gap_pct < _SLIGHTLY_UNDERVALUED_THRESHOLD:
        return "Slightly undervalued"
    if gap_pct <= _SLIGHTLY_ABOVE_THRESHOLD:
        return "Fairly priced"
    if gap_pct <= _OVERPRICED_THRESHOLD:
        return "Slightly above fair value"
    return "Overpriced"


_NEGOTIATION_STANCE = {
    "Insufficient evidence": "Insufficient evidence to advise on negotiation.",
    "Weak evidence": "Evidence is limited; confirm value independently before negotiating.",
    "Undervalued": "Little room to negotiate further below the asking price.",
    "Slightly undervalued": "Some room to negotiate below the asking price.",
    "Fairly priced": "Standard negotiation applies.",
    "Slightly above fair value": "Room to negotiate below the asking price.",
    "Overpriced": "Significant room to negotiate below the asking price.",
}


_TAGLINES = {
    "Undervalued": "Priced below the evidence-supported range",
    "Slightly undervalued": "Priced modestly below the evidence-supported range",
    "Fairly priced": "Priced in line with the evidence-supported range",
    "Slightly above fair value": "Priced modestly above the evidence-supported range",
    "Overpriced": "Priced above the evidence-supported range",
}


def _tagline_for(pricing_classification: str) -> str:
    return _TAGLINES.get(pricing_classification, "Valuation inconclusive")


def _weak_evidence_tagline(gap_pct: float) -> str:
    """Weak-evidence taglines use their own distinct wording and their own
    threshold ladder (note the -10 boundary here is strict '<', unlike the
    <=-10 used by _classify_gap — this exact asymmetry existed in the
    original V1 _generate_tagline() and is preserved as-is, not smoothed
    over, since collapsing it would silently change behaviour at gap==-10).
    """
    if gap_pct > _OVERPRICED_THRESHOLD:
        return "Evidence is limited; asking price appears above the indicative range"
    if gap_pct < _UNDERVALUED_THRESHOLD:
        return "Evidence is limited; asking price appears below the indicative range"
    return "Evidence is limited; treat this valuation as indicative only"


def build_recommendation(
    fair_value_balanced: float,
    fair_value_conservative: float,
    asking_price: float,
    asking_vs_fair_gap_pct: float,
    valuation_status: str,
    sufficient_evidence: bool,
    source_engine: str,
) -> Recommendation:
    """Build the one Recommendation for a valuation.

    Called once by V1's calculate_valuation() (with V1's own numbers) and
    once by V2's run_v2_valuation() (with V2's own numbers). Never called
    with a mix of the two. This is the entire implementation of "is this
    overpriced" / "what should I offer" for the whole application.
    """
    rec = Recommendation(
        source_engine=source_engine,
        fair_value_used=fair_value_balanced,
        asking_price=asking_price,
        gap_pct=asking_vs_fair_gap_pct,
        valuation_status=valuation_status,
    )

    # --- No usable fair value at all ---
    if fair_value_balanced <= 0 or valuation_status == "Insufficient evidence":
        rec.pricing_classification = "Insufficient evidence"
        rec.investment_tagline = "Insufficient comparable evidence for a reliable opinion of value"
        rec.negotiation_stance = _NEGOTIATION_STANCE["Insufficient evidence"]
        rec.offer_reasoning = (
            "The available evidence is insufficient to recommend an offer strategy. "
            "Further comparable research is required."
        )
        return rec

    weak_evidence = valuation_status == "Weak evidence"
    gap = asking_vs_fair_gap_pct

    # pricing_classification is always the plain gap-based category — one
    # mapping, used everywhere (scorecard, risk assessor, banner). The
    # tagline is what changes tone when evidence is weak: it uses its own
    # wording and threshold ladder (see _weak_evidence_tagline), matching
    # V1's original behaviour exactly rather than just prefixing "Tentative:"
    # onto the normal-confidence tagline.
    rec.pricing_classification = _classify_gap(gap)
    rec.investment_tagline = (
        _weak_evidence_tagline(gap) if weak_evidence else _tagline_for(rec.pricing_classification)
    )
    rec.negotiation_stance = (
        _NEGOTIATION_STANCE["Weak evidence"] if weak_evidence
        else _NEGOTIATION_STANCE.get(rec.pricing_classification, "")
    )

    # --- Offer strategy: only for valuations trustworthy enough to act on,
    # exactly matching V1's prior gating condition. ---
    if valuation_status not in _OFFER_ELIGIBLE_STATUSES:
        rec.offer_reasoning = (
            f"Evidence quality ({valuation_status}) does not support a numeric offer "
            f"strategy; treat this assessment as directional only."
        )
        return rec

    cfg = get_config()
    balanced = fair_value_balanced
    conservative = fair_value_conservative if fair_value_conservative > 0 else balanced * 0.90

    buffer_pct = cfg.offer_strategy.negotiation_buffer_pct
    initial_base = conservative if cfg.offer_strategy.initial_offer_basis == "conservative" else balanced
    rec.suggested_initial_offer = round(initial_base * (1 - buffer_pct), -3)
    rec.max_sensible_offer = round(balanced, -3)
    rec.walk_away_price = round(balanced * (1 + cfg.offer_strategy.walk_away_ceiling_pct), -3)

    parts: List[str] = []
    if gap > _OVERPRICED_THRESHOLD:
        parts.append(
            f"The asking price is {gap:+.0f}% above the assessed fair value, "
            f"materially outside the evidence-supported range. "
            f"An offer above {format_currency(balanced)} would not be supported "
            f"by the evidence without additional justification."
        )
    elif gap > _SLIGHTLY_ABOVE_THRESHOLD:
        parts.append(
            f"The asking price is {gap:+.0f}% above the assessed fair value. "
            f"An opening offer of {format_currency(rec.suggested_initial_offer)} is suggested, "
            f"with {format_currency(rec.walk_away_price)} as the upper limit supported by the evidence."
        )
    elif gap > _SLIGHTLY_UNDERVALUED_THRESHOLD:
        parts.append(
            f"The asking price is within {abs(gap):.0f}% of the assessed fair value. "
            f"An opening offer of {format_currency(rec.suggested_initial_offer)} is suggested "
            f"to establish negotiating room."
        )
    else:
        parts.append(
            f"The asking price is {abs(gap):.0f}% below the assessed fair value. "
            f"An opening offer of {format_currency(rec.suggested_initial_offer)} is suggested; "
            f"the reason for the discount to comparable evidence should be confirmed before proceeding."
        )
    rec.offer_reasoning = " ".join(parts)

    return rec
