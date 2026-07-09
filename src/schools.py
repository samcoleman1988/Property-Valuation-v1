"""School and education data — stub module.

In v1, this provides basic distance-based checks using postcodes.
Full implementation would use Ofsted/DfE open data for ratings.
"""

from typing import Optional
from dataclasses import dataclass, field, asdict

from geopy.distance import geodesic


@dataclass
class SchoolAssessment:
    nearby_schools: list = field(default_factory=list)
    school_quality_score: int = 0  # 0-10
    notes: str = ""
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def assess_schools(
    postcode: str,
    latitude: float = 0.0,
    longitude: float = 0.0,
) -> SchoolAssessment:
    """Assess school provision near the property.

    v1: Returns a stub with guidance to check manually.
    """
    assessment = SchoolAssessment()
    assessment.warnings.append(
        "School data integration is a stub in v1. "
        "Check school catchment areas and Ofsted ratings manually at "
        "https://www.compare-school-performance.service.gov.uk/ and "
        "https://www.gov.uk/school-performance-tables"
    )
    assessment.notes = (
        "School quality significantly affects property values, "
        "especially for family homes. Good catchment can add 5-15% to value."
    )
    return assessment
