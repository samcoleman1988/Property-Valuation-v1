"""Externalised configuration for all assumptions, weights, and thresholds.

Every magic number in the system lives here. Users can review and override.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class ComparableWeights:
    """Max points for each comparable scoring dimension. Must sum to 100."""
    proximity: int = 25
    property_type: int = 20
    size_similarity: int = 15
    recency: int = 15
    bedroom_match: int = 10
    tenure_match: int = 10
    condition_match: int = 5


@dataclass(frozen=True)
class ComparableThresholds:
    """Quality bands for comparable classification."""
    excellent_min: int = 70
    good_min: int = 50
    fair_min: int = 30
    weak_min: int = 10
    # Below weak_min = excluded


@dataclass(frozen=True)
class ValuationAssumptions:
    """Parameters for the three valuation cases."""
    # Conservative
    conservative_percentile: float = 0.30
    conservative_risk_discount: float = 0.05
    conservative_condition_penalty_multiplier: float = 1.3

    # Balanced
    balanced_percentile: float = 0.50

    # Aggressive
    aggressive_percentile: float = 0.70
    aggressive_uplift: float = 0.0

    # Minimum comparables for each confidence tier
    high_confidence_min_comps: int = 8
    medium_confidence_min_comps: int = 4
    low_confidence_min_comps: int = 2

    # When we have no evidence, do NOT default to asking price
    no_evidence_fallback: str = "insufficient"  # "insufficient" | "asking_discounted"
    no_evidence_discount: float = 0.15  # only used if fallback = "asking_discounted"


@dataclass(frozen=True)
class AdjustmentRanges:
    """Percentage adjustment ranges for property characteristics.
    Each is (min_pct, max_pct) where negative = discount.
    """
    modernisation_needed: tuple = (-0.08, -0.20)
    recently_refurbished: tuple = (0.03, 0.08)
    no_parking_suburban: tuple = (-0.02, -0.05)
    no_garden_house: tuple = (-0.03, -0.08)
    short_lease_80_years: tuple = (-0.05, -0.10)
    short_lease_60_years: tuple = (-0.10, -0.20)
    short_lease_40_years: tuple = (-0.20, -0.35)
    poor_epc_e: tuple = (-0.02, -0.04)
    poor_epc_fg: tuple = (-0.04, -0.08)
    period_premium: tuple = (0.02, 0.05)
    new_build_resale_fade: tuple = (-0.05, -0.15)


@dataclass(frozen=True)
class OfferStrategy:
    """Rules for generating offer recommendations."""
    initial_offer_basis: str = "conservative"  # base value for opening offer
    negotiation_buffer_pct: float = 0.05  # subtract from initial basis
    max_offer_basis: str = "balanced"  # never pay more than this
    walk_away_ceiling_pct: float = 0.03  # above balanced = absolute ceiling

    # Market condition adjustments to negotiation buffer
    long_on_market_days: int = 90  # if listed > this, widen buffer
    long_on_market_extra_buffer: float = 0.03
    recent_reduction_extra_buffer: float = 0.02


@dataclass(frozen=True)
class ScorecardWeights:
    """Weights for the investment scorecard dimensions."""
    fair_value: float = 20.0
    negotiation_opportunity: float = 15.0
    development_opportunity: float = 12.0
    planning_confidence: float = 8.0
    rental_potential: float = 10.0
    resale_potential: float = 10.0
    location_quality: float = 10.0
    investment_risk: float = 15.0


@dataclass(frozen=True)
class BuildCosts:
    """Build cost assumptions per sqm (GBP, 2024/25 UK averages)."""
    single_storey_rear_low: int = 1400
    single_storey_rear_high: int = 2400
    two_storey_low: int = 1200
    two_storey_high: int = 2200
    loft_conversion_low: int = 1200
    loft_conversion_high: int = 2200
    garage_conversion_low: int = 800
    garage_conversion_high: int = 1600
    outbuilding_low: int = 800
    outbuilding_high: int = 1800
    professional_fees_pct: float = 0.12
    contingency_pct: float = 0.10


@dataclass(frozen=True)
class RiskPenalties:
    """Score penalties for identified risks."""
    listed_building: int = -30
    conservation_area: int = -15
    green_belt: int = -25
    flood_zone_2: int = -10
    flood_zone_3: int = -25
    article_4: int = -10
    short_lease: int = -15
    poor_epc_letting: int = -10
    low_comparable_count: int = -20
    high_comparable_variance: int = -10
    overpriced_20pct: int = -15


@dataclass(frozen=True)
class HPIDefaults:
    """House Price Index fallback assumptions."""
    national_annual_growth_pct: float = 3.0
    default_region: str = "England"


@dataclass
class Config:
    """Master configuration container."""
    comparable_weights: ComparableWeights = field(default_factory=ComparableWeights)
    comparable_thresholds: ComparableThresholds = field(default_factory=ComparableThresholds)
    valuation: ValuationAssumptions = field(default_factory=ValuationAssumptions)
    adjustments: AdjustmentRanges = field(default_factory=AdjustmentRanges)
    offer_strategy: OfferStrategy = field(default_factory=OfferStrategy)
    scorecard_weights: ScorecardWeights = field(default_factory=ScorecardWeights)
    build_costs: BuildCosts = field(default_factory=BuildCosts)
    risk_penalties: RiskPenalties = field(default_factory=RiskPenalties)
    hpi: HPIDefaults = field(default_factory=HPIDefaults)


# Singleton default config
DEFAULT_CONFIG = Config()


def get_config() -> Config:
    return DEFAULT_CONFIG
