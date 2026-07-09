"""Core valuation engine.

Calculates fair value from Land Registry comparables, adjusted by HPI.
Produces conservative / balanced / aggressive valuations with offer strategy.
"""

import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

from .land_registry import search_comparables, normalise_property_type, PROPERTY_TYPE_MAP
from .hpi import adjust_price_to_current, get_annual_growth
from .utils import format_currency, postcode_outcode, postcode_sector


@dataclass
class ValuationResult:
    asking_price: float = 0.0

    # Core valuations
    fair_value_balanced: float = 0.0
    fair_value_conservative: float = 0.0
    fair_value_aggressive: float = 0.0

    # Offer strategy
    suggested_initial_offer: float = 0.0
    max_sensible_offer: float = 0.0
    walk_away_price: float = 0.0

    # Gap analysis
    asking_vs_fair_gap: float = 0.0
    asking_vs_fair_gap_pct: float = 0.0

    # Confidence
    confidence_score: int = 0  # 0-100
    confidence_label: str = ""
    evidence_quality: str = ""

    # Per-sqft analysis
    price_per_sqft: float = 0.0
    comparable_avg_per_sqft: float = 0.0

    # Comparable evidence
    comparables_used: int = 0
    comparables_same_type: int = 0
    comparables_date_range: str = ""
    comparable_details: list = field(default_factory=list)

    # Supporting data
    hpi_annual_growth: float = 0.0
    valuation_method: str = ""
    assumptions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    # Investment verdict
    investment_tagline: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_valuation(
    asking_price: float,
    postcode: str,
    property_type: str = "",
    bedrooms: int = 0,
    floor_area_sqft: float = 0.0,
    tenure: str = "",
    region: str = "England",
) -> ValuationResult:
    """Run the full valuation calculation."""
    result = ValuationResult(asking_price=asking_price)

    # 1. Fetch comparables
    comps = _fetch_and_filter_comparables(
        postcode, property_type, bedrooms, result
    )

    if comps.empty:
        result.warnings.append("No comparable sales found — valuation is indicative only")
        result.confidence_score = 5
        result.confidence_label = "Very Low"
        result.evidence_quality = "No comparable evidence available"
        result.fair_value_balanced = asking_price
        result.fair_value_conservative = asking_price * 0.85
        result.fair_value_aggressive = asking_price * 1.05
        _calculate_offers(result)
        result.investment_tagline = "Insufficient evidence — manual research required"
        return result

    # 2. Adjust comparables to current value using HPI
    comps = _adjust_comparables(comps, region)

    # 3. Calculate fair value
    _calculate_fair_value(comps, result, floor_area_sqft)

    # 4. Calculate per-sqft metrics
    if floor_area_sqft > 0:
        result.price_per_sqft = round(asking_price / floor_area_sqft, 0)
        if result.fair_value_balanced > 0:
            result.comparable_avg_per_sqft = round(result.fair_value_balanced / floor_area_sqft, 0)

    # 5. Calculate offer strategy
    _calculate_offers(result)

    # 6. Score confidence
    _score_confidence(result, comps, property_type)

    # 7. Get HPI growth
    result.hpi_annual_growth = get_annual_growth(region) or 3.0

    # 8. Generate investment tagline
    result.investment_tagline = _generate_tagline(result)

    # 9. Store comparable details for report
    result.comparable_details = _format_comparables(comps)

    return result


def _fetch_and_filter_comparables(
    postcode: str,
    property_type: str,
    bedrooms: int,
    result: ValuationResult,
) -> pd.DataFrame:
    """Fetch comparables and apply filters with progressive relaxation."""
    pt_code = normalise_property_type(property_type)

    # Try exact postcode first, then sector, then outcode
    for search_pc in [postcode, postcode_sector(postcode), postcode_outcode(postcode)]:
        comps = search_comparables(search_pc, property_type, max_age_years=5, limit=100)
        if not comps.empty:
            result.assumptions.append(f"Comparables searched using postcode filter: {search_pc}")
            break
    else:
        return pd.DataFrame()

    original_count = len(comps)

    # Filter by property type if we have enough
    if pt_code and len(comps) >= 5:
        type_match = comps[comps["property_type_code"] == pt_code]
        if len(type_match) >= 3:
            comps = type_match
            result.comparables_same_type = len(comps)
            result.assumptions.append(f"Filtered to same property type: {PROPERTY_TYPE_MAP.get(pt_code, property_type)}")

    # Remove obvious outliers (beyond 3 standard deviations)
    if len(comps) >= 5:
        prices = comps["price"]
        mean, std = prices.mean(), prices.std()
        if std > 0:
            comps = comps[(prices > mean - 3 * std) & (prices < mean + 3 * std)]

    result.comparables_used = len(comps)

    if not comps.empty and "date" in comps.columns:
        dates = pd.to_datetime(comps["date"], errors="coerce").dropna()
        if not dates.empty:
            result.comparables_date_range = f"{dates.min().strftime('%b %Y')} to {dates.max().strftime('%b %Y')}"

    return comps


def _adjust_comparables(comps: pd.DataFrame, region: str) -> pd.DataFrame:
    """Adjust each comparable price to current value using HPI."""
    adjusted_prices = []
    for _, row in comps.iterrows():
        adj = adjust_price_to_current(row["price"], row.get("date", ""), region)
        adjusted_prices.append(adj)

    comps = comps.copy()
    comps["adjusted_price"] = adjusted_prices
    return comps


def _calculate_fair_value(
    comps: pd.DataFrame,
    result: ValuationResult,
    floor_area_sqft: float,
):
    """Calculate three-case valuation from comparables."""
    prices = comps["adjusted_price"]

    # Weighted median (prefer more recent sales)
    if "date" in comps.columns:
        dates = pd.to_datetime(comps["date"], errors="coerce")
        now = pd.Timestamp.now()
        age_days = (now - dates).dt.days.fillna(1825)
        # Weight: newer sales get higher weight (inverse of age, floored)
        weights = 1.0 / (1 + age_days / 365.0)
        weights = weights / weights.sum()

        # Weighted percentiles
        sorted_idx = prices.argsort()
        sorted_prices = prices.iloc[sorted_idx].values
        sorted_weights = weights.iloc[sorted_idx].values
        cum_weights = np.cumsum(sorted_weights)

        p25 = sorted_prices[np.searchsorted(cum_weights, 0.25)]
        p50 = sorted_prices[np.searchsorted(cum_weights, 0.50)]
        p75 = sorted_prices[np.searchsorted(cum_weights, 0.75)]
    else:
        p25 = prices.quantile(0.25)
        p50 = prices.quantile(0.50)
        p75 = prices.quantile(0.75)

    # Conservative: 25th percentile with 5% risk discount
    result.fair_value_conservative = round(p25 * 0.95, -3)

    # Balanced: weighted median
    result.fair_value_balanced = round(p50, -3)

    # Aggressive: 75th percentile
    result.fair_value_aggressive = round(p75, -3)

    # Gap analysis
    if result.fair_value_balanced > 0:
        result.asking_vs_fair_gap = result.asking_price - result.fair_value_balanced
        result.asking_vs_fair_gap_pct = (
            (result.asking_price - result.fair_value_balanced)
            / result.fair_value_balanced * 100
        )

    result.valuation_method = "Weighted median of HPI-adjusted Land Registry comparables"
    result.assumptions.append("Older sales weighted lower; newest sales weighted highest")
    result.assumptions.append("Conservative adds 5% risk discount below 25th percentile")


def _calculate_offers(result: ValuationResult):
    """Calculate offer strategy from valuations."""
    fair = result.fair_value_balanced
    conservative = result.fair_value_conservative

    if fair <= 0:
        return

    # Initial offer: start at conservative value
    result.suggested_initial_offer = round(conservative, -3)

    # Max sensible offer: balanced value (don't pay more than fair)
    result.max_sensible_offer = round(fair, -3)

    # Walk-away: 5% above balanced (absolute ceiling)
    result.walk_away_price = round(fair * 1.05, -3)


def _score_confidence(result: ValuationResult, comps: pd.DataFrame, property_type: str):
    """Score confidence 0-100 based on evidence quality."""
    score = 0

    # Number of comparables (max 30 points)
    n = result.comparables_used
    if n >= 10:
        score += 30
    elif n >= 5:
        score += 20
    elif n >= 3:
        score += 10
    elif n >= 1:
        score += 5

    # Same property type match (max 20 points)
    if result.comparables_same_type >= 5:
        score += 20
    elif result.comparables_same_type >= 3:
        score += 15
    elif result.comparables_same_type >= 1:
        score += 10

    # Recency (max 20 points)
    if "date" in comps.columns:
        dates = pd.to_datetime(comps["date"], errors="coerce").dropna()
        if not dates.empty:
            newest = dates.max()
            months_old = (pd.Timestamp.now() - newest).days / 30
            if months_old < 6:
                score += 20
            elif months_old < 12:
                score += 15
            elif months_old < 24:
                score += 10
            else:
                score += 5

    # Price consistency — lower std/mean = higher confidence (max 20 points)
    prices = comps["adjusted_price"]
    if len(prices) >= 3:
        cv = prices.std() / prices.mean() if prices.mean() > 0 else 1
        if cv < 0.1:
            score += 20
        elif cv < 0.2:
            score += 15
        elif cv < 0.3:
            score += 10
        else:
            score += 5

    # Floor area available (max 10 points)
    if result.price_per_sqft > 0:
        score += 10

    result.confidence_score = min(100, score)

    if score >= 70:
        result.confidence_label = "High"
        result.evidence_quality = "Strong comparable evidence with good recency and consistency"
    elif score >= 45:
        result.confidence_label = "Medium"
        result.evidence_quality = "Reasonable evidence but some limitations in comparables"
    elif score >= 20:
        result.confidence_label = "Low"
        result.evidence_quality = "Limited comparable evidence — treat valuation as indicative"
    else:
        result.confidence_label = "Very Low"
        result.evidence_quality = "Very weak evidence — manual research strongly recommended"


def _generate_tagline(result: ValuationResult) -> str:
    """Generate an investment verdict tagline."""
    gap_pct = result.asking_vs_fair_gap_pct

    if gap_pct < -10:
        return "Potentially undervalued — investigate why"
    if gap_pct < -5:
        return "Priced below fair value — possible opportunity"
    if -5 <= gap_pct <= 5:
        return "Fairly priced — negotiate for margin"
    if 5 < gap_pct <= 15:
        return "Overpriced — negotiate hard or walk away"
    if gap_pct > 15:
        return "Significantly overpriced — avoid unless heavily negotiated"

    return "Valuation inconclusive — more research needed"


def _format_comparables(comps: pd.DataFrame) -> list:
    """Format comparables for the report."""
    rows = []
    for _, row in comps.iterrows():
        rows.append({
            "address": row.get("address", ""),
            "price": row.get("price", 0),
            "adjusted_price": round(row.get("adjusted_price", 0), 0),
            "date": str(row.get("date", "")),
            "property_type": row.get("property_type", ""),
            "tenure": row.get("tenure", ""),
            "new_build": row.get("new_build", False),
        })
    return sorted(rows, key=lambda x: x.get("date", ""), reverse=True)[:20]
