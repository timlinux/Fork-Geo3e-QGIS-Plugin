# -*- coding: utf-8 -*-
"""Topic-relevant icon lookup for the tree's dimensions, factors and indicators.

Maps each dimension/factor/indicator ``id`` (as found in model.json) to an
SVG filename under ``geest/resources/icons/topics/``. Most factors have a
single indicator covering the same real-world topic, so that factor and its
one indicator intentionally share an icon file - only the two multi-child
factors (women's travel patterns, environmental hazards) have distinct
per-indicator icons.

Lookups are case-insensitive since ``id`` casing is inconsistent across
model.json (mostly snake_case, some CamelCase/PascalCase).
"""

from typing import Optional

#: analysis-level icon, used for the single top-level "analysis" tree item.
ANALYSIS_ICON = "geoe3_score.svg"

#: dimension id -> icon filename
_DIMENSION_ICONS = {
    "contextual": "contextual.svg",
    "accessibility": "accessibility.svg",
    "place_characterization": "place_characterization.svg",
}

#: factor id -> icon filename
_FACTOR_ICONS = {
    "eplex": "eplex.svg",
    "workplace_discrimination": "workplace_discrimination.svg",
    "regulatory_frameworks": "regulatory_frameworks.svg",
    "financial_inclusion": "financial_inclusion.svg",
    "women_s_travel_patterns": "women_s_travel_patterns.svg",
    "access_to_public_transport": "access_to_public_transport.svg",
    "access_to_health_facilities": "access_to_health_facilities.svg",
    "access_to_education_and_training_facilities": "access_to_education_and_training_facilities.svg",
    "access_to_financial_facilities": "access_to_financial_facilities.svg",
    "active_transport": "active_transport.svg",
    "safety_perception": "safety_perception.svg",
    "fcv": "fcv.svg",
    "education": "education.svg",
    "digital_inclusion": "digital_inclusion.svg",
    "environmental_hazards": "environmental_hazards.svg",
    "water_sanitation": "water_sanitation.svg",
}

#: indicator id -> icon filename. Single-indicator factors fall back to
#: their parent factor's icon (see _FACTOR_ICONS) rather than being repeated
#: here; only indicators belonging to a multi-child factor are listed.
_INDICATOR_ICONS = {
    "eplex_score_indicator": "eplex.svg",
    "workplace_index": "workplace_discrimination.svg",
    "pay_parenthood_index": "regulatory_frameworks.svg",
    "entrepreneurship_index": "financial_inclusion.svg",
    "kindergartens_location": "kindergartens_location.svg",
    "primary_school_location": "primary_school_location.svg",
    "groceries_location": "groceries_location.svg",
    "pharmacies_location": "pharmacies_location.svg",
    "green_space_location": "green_space_location.svg",
    "public_transport_location": "access_to_public_transport.svg",
    "hospital_location": "access_to_health_facilities.svg",
    "universities_location": "access_to_education_and_training_facilities.svg",
    "banks_location": "access_to_financial_facilities.svg",
    "active_transport_network": "active_transport.svg",
    "street_lights": "safety_perception.svg",
    "fcv": "fcv.svg",
    "education": "education.svg",
    "digital_inclusion": "digital_inclusion.svg",
    "fire": "fire.svg",
    "flood": "flood.svg",
    "landslide": "landslide.svg",
    "cyclone": "cyclone.svg",
    "drought": "drought.svg",
    "water_sanitation": "water_sanitation.svg",
}


def topic_icon_filename(role: str, item_id: Optional[str]) -> Optional[str]:
    """Return the topic icon filename for a tree item, or None if unmapped.

    Args:
        role: one of "analysis", "dimension", "factor", "indicator".
        item_id: the item's ``id`` attribute (case-insensitive).

    Returns:
        A filename under ``geest/resources/icons/topics/``, or None.
    """
    if role == "analysis":
        return ANALYSIS_ICON
    if not item_id:
        return None
    key = item_id.lower()
    if role == "dimension":
        return _DIMENSION_ICONS.get(key)
    if role == "factor":
        return _FACTOR_ICONS.get(key)
    if role == "indicator":
        return _INDICATOR_ICONS.get(key)
    return None
