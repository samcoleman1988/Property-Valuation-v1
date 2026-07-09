"""Listing interpreter - extracts investment-relevant signals from text.

Rule-based extraction of condition, features, and risk indicators
from Rightmove listing descriptions and key features. No AI/ML.
"""

import re
from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class ListingSignals:
    """Investment-relevant signals extracted from listing text."""
    # Condition
    condition_score: int = 5  # 1 (derelict) to 10 (pristine)
    condition_label: str = "Unknown"
    condition_keywords_found: List[str] = field(default_factory=list)
    condition_confidence: str = "none"  # "high", "medium", "low", "none"

    # Features
    has_garage: bool = False
    has_driveway: bool = False
    has_parking: bool = False
    has_garden: bool = False
    garden_description: str = ""
    has_extension_already: bool = False
    has_conservatory: bool = False
    has_loft_conversion: bool = False
    has_basement: bool = False
    has_outbuilding: bool = False

    # Tenure / chain signals
    chain_free: bool = False
    investment_property: bool = False
    rental_mentioned: bool = False
    tenant_in_situ: bool = False

    # Construction / age signals
    period_property: bool = False
    new_build: bool = False
    estimated_era: str = ""

    # Risk signals
    needs_modernisation: bool = False
    project_property: bool = False
    structural_concerns: bool = False
    non_standard_construction: bool = False

    # Adjustment recommendations
    adjustments: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# Keyword patterns grouped by signal
_NEEDS_WORK_PATTERNS = [
    r"\b(need(?:s|ing)?\s+(?:of\s+)?(?:modernis|updat|refurbish|renovat))",
    r"\b(require(?:s|ing)?\s+(?:modernis|updat|refurbish|renovat))",
    r"\b(in\s+need\s+of\s+(?:modernisation|updating|renovation|refurbishment))",
    r"\b(scope\s+for\s+(?:improvement|modernisation|renovation|updating))",
    r"\b(huge\s+scope\s+for\s+(?:improvement|modernisation))",
    r"\b(would\s+benefit\s+from\s+(?:modernisation|updating|renovation|improvement))",
    r"\b((?:renovation|refurbishment|modernisation)\s+(?:required|needed|opportunity|project))",
    r"\b(project|doer.upper|fixer.upper|renovation\s+project)",
    r"\b(cosmetic\s+(?:work|updating|improvement))",
    r"\b(original\s+(?:condition|features?\s+throughout|kitchen|bathroom))",
    r"\b(dated\s+(?:kitchen|bathroom|decor|interior))",
    r"\b(dated\b)",
    r"\b(tired\s+(?:decor|interior|condition))",
    r"\b(tired\b)",
    r"\b(blank\s+canvas)",
    r"\b(improvement\s+(?:opportunity|potential))",
    r"\b(requires?\s+improvement)",
]

_EXCELLENT_PATTERNS = [
    r"\b(immaculately?\s+presented)",
    r"\b(beautifully\s+(?:presented|appointed|finished|decorated))",
    r"\b(newly\s+refurbished)",
    r"\b(recently\s+refurbished)",
    r"\b(fully\s+(?:renovated|refurbished|modernised))",
    r"\b(recently\s+renovated)",
    r"\b(modern\s+throughout)",
    r"\b(finished\s+to\s+a\s+high\s+standard)",
    r"\b(turnkey)",
    r"\b(move.in\s+(?:condition|ready))",
    r"\b(no\s+(?:onward\s+)?work\s+required)",
    r"\b(immaculate\s+(?:condition|order|throughout))",
    r"\b(immaculate\b)",
    r"\b(pristine)",
    r"\b(show\s+home)",
    r"\b(high\s+(?:spec(?:ification)?|standard|quality)\s+(?:finish|throughout))",
    r"\b(newly\s+(?:fitted|installed|decorated|refurbished))",
    r"\b(new\s+(?:kitchen|bathroom|boiler|roof|windows|central\s+heating))",
    r"\b((?:kitchen|bathroom)\s+(?:recently\s+)?(?:fitted|installed|replaced))",
    r"\b(fully\s+(?:refurbished|renovated|modernised|updated|redecorated))",
    r"\b(recently\s+(?:refurbished|renovated|modernised|updated|redecorated))",
    r"\b(stylish\s+(?:decor|interior)\s+throughout)",
]

_GOOD_PATTERNS = [
    r"\b(well\s*[-\s]?presented)",
    r"\b(well\s*[-\s]?maintained)",
    r"\b(tastefully\s+decorated)",
    r"\b(neutral\s+decor)",
    r"\b(recently\s+redecorated)",
    r"\b(upgraded\b)",
    r"\b(improved\s+by\s+(?:the\s+)?(?:current|present)\s+owners?)",
    r"\b(ready\s+to\s+move\s+into)",
]

_AVERAGE_PATTERNS = [
    r"\b(presented\s+in\s+good\s+order)",
    r"\b(good\s+condition\s+throughout)",
    r"\b(spacious\s+accommodation)",
    r"\b(established\s+property)",
]

_SCOPE_TO_EXTEND_PATTERNS = [
    r"\b(scope\s+to\s+(?:extend|add|convert|develop))",
    r"\b(scope\s+for\s+(?:extension|enlargement|conversion|development|loft))",
    r"\b(potential\s+to\s+(?:extend|add|convert))",
    r"\b((?:stpp|subject\s+to\s+(?:relevant\s+)?planning))",
]

_EXTENSION_PATTERNS = [
    r"\b(extended|extension|rear\s+extension|side\s+extension|single.storey|two.storey)",
    r"\b((?:has|with)\s+(?:been\s+)?extended)",
]

_GARAGE_PATTERNS = [
    r"\b(garage|integral\s+garage|detached\s+garage|double\s+garage|single\s+garage)",
]

_PARKING_PATTERNS = [
    r"\b(driveway|off.road\s+parking|off.street\s+parking|parking\s+space|allocated\s+parking|private\s+parking|block.paved\s+drive)",
]

_GARDEN_PATTERNS = [
    r"\b((?:rear|front|side|private|enclosed|south.facing|landscaped|large|generous|good.sized|wrap.around)\s+garden)",
    r"\b(garden\s+(?:to\s+(?:the\s+)?(?:rear|front|side)))",
    r"\b(gardens?\b)",
    r"\b(courtyard\s+garden|patio\s+area|outside\s+space)",
]

_PERIOD_PATTERNS = [
    r"\b(victorian|edwardian|georgian|regency|art\s+deco|1930s|inter.war|period\s+(?:property|home|house|features?))",
    r"\b(character\s+(?:property|home|house|features?))",
    r"\b(original\s+(?:features?|fireplaces?|cornicing|ceiling\s+roses?))",
]

_CHAIN_FREE_PATTERNS = [
    r"\b(no\s+(?:onward\s+)?chain|chain\s+free|no\s+chain)",
    r"\b(vacant\s+possession)",
]

_INVESTMENT_PATTERNS = [
    r"\b(invest(?:ment|or)\s+(?:opportunity|property|only))",
    r"\b((?:buy.to.let|btl|rental)\s+(?:opportunity|property|investment|potential))",
    r"\b(tenant\s+in\s+situ|currently\s+(?:let|rented|tenanted))",
    r"\b(rental\s+(?:income|yield|return|potential))",
    r"\b((?:strong|good|excellent)\s+(?:rental|letting)\s+(?:demand|history|potential))",
]

_NEW_BUILD_PATTERNS = [
    r"\b(new\s+build|newly\s+built|brand\s+new|newly\s+constructed)",
    r"\b(help\s+to\s+buy|first\s+homes?|shared\s+ownership)",
]

_STRUCTURAL_PATTERNS = [
    r"\b(subsidence|underpinning|structural\s+(?:issues?|work|concerns?|movement))",
    r"\b(japanese\s+knotweed|damp\s+(?:issues?|problems?)|woodworm)",
    r"\b(non.standard\s+(?:construction|build))",
    r"\b(prefab(?:ricated)?|timber\s+frame|steel\s+frame|concrete\s+(?:frame|construction))",
]

_ERA_PATTERNS = [
    (r"\b(pre.war|pre.1914|victorian|19th\s+century)", "Pre-1914"),
    (r"\b(edwardian|1900s|1910s)", "1900-1918"),
    (r"\b(inter.war|1920s|1930s|art\s+deco)", "1919-1939"),
    (r"\b(post.war|1940s|1950s|1960s)", "1945-1969"),
    (r"\b(197[0-9]s?|1970s)", "1970s"),
    (r"\b(198[0-9]s?|1980s)", "1980s"),
    (r"\b(199[0-9]s?|1990s)", "1990s"),
    (r"\b(200[0-9]s?|2000s)", "2000s"),
    (r"\b(201[0-9]s?|2010s)", "2010s"),
    (r"\b(202[0-9]s?|2020s|new\s+build|newly\s+built)", "2020s"),
]


def interpret_listing(
    description: str = "",
    key_features: list = None,
    property_type: str = "",
) -> ListingSignals:
    """Extract investment signals from listing text. Rule-based, no AI."""
    signals = ListingSignals()

    # Combine all text for searching
    features_text = " ".join(key_features) if key_features else ""
    full_text = f"{description} {features_text}".lower()

    if not full_text.strip():
        return signals

    # Condition assessment
    _assess_condition(signals, full_text)

    # Feature extraction
    _extract_features(signals, full_text)

    # Construction / age
    _assess_age(signals, full_text)

    # Chain / investment
    _assess_investment_signals(signals, full_text)

    # Structural concerns
    _assess_structural(signals, full_text)

    # Generate adjustment recommendations
    _generate_adjustments(signals, property_type)

    return signals


def _find_patterns(text: str, patterns: list) -> List[str]:
    """Find all matching patterns in text."""
    found = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found.extend(matches)
    return found


def _assess_condition(signals: ListingSignals, text: str):
    needs_work = _find_patterns(text, _NEEDS_WORK_PATTERNS)
    excellent = _find_patterns(text, _EXCELLENT_PATTERNS)
    good = _find_patterns(text, _GOOD_PATTERNS)
    average = _find_patterns(text, _AVERAGE_PATTERNS)
    scope_extend = _find_patterns(text, _SCOPE_TO_EXTEND_PATTERNS)

    # Filter: "scope to extend" is NOT a negative condition signal
    needs_work_filtered = []
    for m in needs_work:
        m_lower = m.lower() if isinstance(m, str) else str(m).lower()
        if any(re.search(pat, m_lower) for pat in [
            r"scope\s+to\s+(?:extend|add|convert|develop)",
            r"scope\s+for\s+(?:extension|enlargement|conversion|development|loft)",
        ]):
            continue
        needs_work_filtered.append(m)
    needs_work = needs_work_filtered

    if needs_work:
        signals.needs_modernisation = True
        signals.condition_keywords_found.extend(needs_work[:5])
    if excellent:
        signals.condition_keywords_found.extend(excellent[:5])
    if good:
        signals.condition_keywords_found.extend(good[:5])

    # Priority: negative condition overrides generic positive agent language
    if needs_work and not excellent and not good:
        if any(w in text for w in ["derelict", "uninhabitable", "extensive work", "major renovation"]):
            signals.condition_score = 2
            signals.condition_label = "Poor - major works required"
            signals.condition_confidence = "high"
            signals.project_property = True
        elif any(w in text for w in ["project", "blank canvas", "fixer", "huge scope for improvement"]):
            signals.condition_score = 3
            signals.condition_label = "Below average - significant updating needed"
            signals.condition_confidence = "high"
            signals.project_property = True
        else:
            signals.condition_score = 4
            signals.condition_label = "Below average - modernisation needed"
            signals.condition_confidence = "medium"
    elif needs_work and (excellent or good):
        signals.condition_score = 6
        signals.condition_label = "Mixed - partially updated"
        signals.condition_confidence = "medium"
    elif excellent:
        signals.condition_score = 9
        signals.condition_label = "Excellent - recently refurbished to high standard"
        signals.condition_confidence = "high"
    elif good:
        signals.condition_score = 7
        signals.condition_label = "Good - well maintained"
        signals.condition_confidence = "medium"
    elif average:
        signals.condition_score = 6
        signals.condition_label = "Average - reasonable condition"
        signals.condition_confidence = "low"
        signals.condition_keywords_found.extend(average[:3])
    else:
        signals.condition_score = 5
        signals.condition_label = "Unknown - no strong condition indicators"
        signals.condition_confidence = "none"


def _extract_features(signals: ListingSignals, text: str):
    signals.has_garage = bool(_find_patterns(text, _GARAGE_PATTERNS))
    signals.has_parking = bool(_find_patterns(text, _PARKING_PATTERNS)) or signals.has_garage
    signals.has_driveway = "driveway" in text or "drive" in text.split()

    garden_matches = _find_patterns(text, _GARDEN_PATTERNS)
    if garden_matches:
        signals.has_garden = True
        signals.garden_description = garden_matches[0] if garden_matches else ""

    signals.has_extension_already = bool(_find_patterns(text, _EXTENSION_PATTERNS))
    signals.has_conservatory = "conservatory" in text
    signals.has_loft_conversion = "loft conversion" in text or "loft room" in text
    signals.has_basement = "basement" in text or "cellar" in text
    signals.has_outbuilding = any(w in text for w in ["outbuilding", "workshop", "garden room", "summer house", "garden office", "studio"])


def _assess_age(signals: ListingSignals, text: str):
    signals.period_property = bool(_find_patterns(text, _PERIOD_PATTERNS))
    signals.new_build = bool(_find_patterns(text, _NEW_BUILD_PATTERNS))

    for pattern, era in _ERA_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            signals.estimated_era = era
            break


def _assess_investment_signals(signals: ListingSignals, text: str):
    signals.chain_free = bool(_find_patterns(text, _CHAIN_FREE_PATTERNS))

    inv_matches = _find_patterns(text, _INVESTMENT_PATTERNS)
    if inv_matches:
        signals.investment_property = True
        signals.rental_mentioned = True

    if "tenant in situ" in text or "currently let" in text or "currently rented" in text or "currently tenanted" in text:
        signals.tenant_in_situ = True
        signals.rental_mentioned = True


def _assess_structural(signals: ListingSignals, text: str):
    struct_matches = _find_patterns(text, _STRUCTURAL_PATTERNS)
    if struct_matches:
        signals.structural_concerns = True
        signals.condition_keywords_found.extend(struct_matches[:3])

    if any(w in text for w in ["non-standard", "non standard", "prefab", "timber frame", "steel frame"]):
        signals.non_standard_construction = True


def _generate_adjustments(signals: ListingSignals, property_type: str):
    """Generate recommended valuation adjustments based on signals."""
    from .config import get_config
    cfg = get_config()
    adj = cfg.adjustments
    pt = property_type.lower() if property_type else ""
    is_house = any(t in pt for t in ("detached", "semi", "terrace", "bungalow", "house", "cottage"))

    if signals.needs_modernisation:
        lo, hi = adj.modernisation_needed
        signals.adjustments.append({
            "name": "Modernisation required",
            "range_pct": (lo, hi),
            "mid_pct": (lo + hi) / 2,
            "reason": f"Listing indicates property needs updating. Keywords: {', '.join(signals.condition_keywords_found[:3])}",
            "direction": "negative",
        })

    if signals.condition_score >= 9:
        lo, hi = adj.recently_refurbished
        signals.adjustments.append({
            "name": "Excellent condition / recently refurbished",
            "range_pct": (lo, hi),
            "mid_pct": (lo + hi) / 2,
            "reason": f"Listing indicates excellent condition. Keywords: {', '.join(signals.condition_keywords_found[:3])}",
            "direction": "positive",
        })
    elif signals.condition_score >= 7:
        lo, hi = adj.recently_refurbished
        half_lo, half_hi = lo * 0.5, hi * 0.5
        signals.adjustments.append({
            "name": "Good condition / well maintained",
            "range_pct": (half_lo, half_hi),
            "mid_pct": (half_lo + half_hi) / 2,
            "reason": f"Listing indicates good condition. Keywords: {', '.join(signals.condition_keywords_found[:3])}",
            "direction": "positive",
        })

    if is_house and not signals.has_parking and not signals.has_garage:
        lo, hi = adj.no_parking_suburban
        signals.adjustments.append({
            "name": "No off-street parking",
            "range_pct": (lo, hi),
            "mid_pct": (lo + hi) / 2,
            "reason": "No parking, garage, or driveway mentioned in listing",
            "direction": "negative",
        })

    if is_house and not signals.has_garden:
        lo, hi = adj.no_garden_house
        signals.adjustments.append({
            "name": "No garden",
            "range_pct": (lo, hi),
            "mid_pct": (lo + hi) / 2,
            "reason": "No garden mentioned in listing for a house-type property",
            "direction": "negative",
        })

    if signals.period_property:
        lo, hi = adj.period_premium
        signals.adjustments.append({
            "name": "Period property premium",
            "range_pct": (lo, hi),
            "mid_pct": (lo + hi) / 2,
            "reason": "Period/character property with potential premium",
            "direction": "positive",
        })

    if signals.structural_concerns:
        signals.adjustments.append({
            "name": "Structural concerns flagged",
            "range_pct": (-0.10, -0.25),
            "mid_pct": -0.175,
            "reason": f"Listing mentions: {', '.join(signals.condition_keywords_found[:3])}. Professional survey essential.",
            "direction": "negative",
        })

    if signals.non_standard_construction:
        signals.adjustments.append({
            "name": "Non-standard construction",
            "range_pct": (-0.05, -0.15),
            "mid_pct": -0.10,
            "reason": "Non-standard construction may limit mortgage availability and resale",
            "direction": "negative",
        })
