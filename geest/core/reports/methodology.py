# -*- coding: utf-8 -*-
"""📦 Methodology reference module.

Static, hand-written reference data for the analysis report's
"Methodology" pages: which real-world computation TECHNIQUE sits behind
each `analysis_mode` an indicator can be configured with, a plain-
language explanation of each technique for a non-GIS reader, and the
SVG illustration that goes with it (geest/resources/methodology/).

Several `analysis_mode` values are mechanically different ways of
doing the SAME underlying technique (e.g. counting points vs counting
line length vs counting polygons are all "tally what's inside the
cell") - they're grouped together here so the report explains the
technique once, then lists which indicators in THIS project use it,
rather than repeating near-identical paragraphs per indicator.
"""

from typing import Optional

#: technique_key -> {"name", "svg", "description"}. Keep descriptions
#: concrete and specific - this is read by policy makers with no GIS
#: background, not by developers.
TECHNIQUES = {
    "index_score": {
        "name": "A Single Published Number",
        "svg": "index_score.svg",
        "description": (
            "Some of what this analysis measures doesn't change from one part of the "
            "country to another. Whether the law formally protects women from workplace "
            "discrimination, for instance, is set in national legislation — it's true "
            "(or not) everywhere at once, down to the last village. For indicators like "
            "this, every grid cell is given the same score, taken directly from a "
            "published index. A couple of the indicators that work this way are narrowed "
            "further, scored only where the underlying data actually applies — only "
            "where broadband coverage exists, say, or only inside built-up settlements. "
            "Everywhere else is left blank, rather than attaching a labour-force "
            "statistic to land where nobody lives, or an internet-use figure to a place "
            "the coverage data never reached."
        ),
    },
    "feature_count": {
        "name": "Counting What's Nearby",
        "svg": "feature_count.svg",
        "description": (
            "For some indicators, what matters is simply how much of something sits "
            "inside each cell of the grid — the number of clinics, say, or the total "
            "length of footpaths and cycle lanes running through it. This technique "
            "overlays the grid on the real-world data and tallies how many points, "
            "lines or polygons fall inside each cell. The score isn't a smooth slide "
            "from that count — a cell with nothing nearby scores 0, a cell with "
            "exactly one feature scores a middle mark, and a cell with two or more "
            "already scores the maximum. A single clinic is enough to lift a cell "
            "out of the bottom of the scale; a second one maxes it out."
        ),
    },
    "distance_buffer": {
        "name": "How Close the Nearest One Is",
        "svg": "distance_buffer.svg",
        "description": (
            "Other indicators care less about density and more about proximity — can "
            "a woman reach a water point without travelling far, or has a violent "
            "incident happened nearby? This technique draws a fixed-radius circle around "
            "every relevant point and scores a grid cell by whether it falls inside that "
            "circle or outside it. Being inside the circle is good news for a water point "
            "or a bank branch, and bad news for a reported violent event — whether "
            "“inside” means a high score or a low one depends on what's being "
            "measured, not on the technique itself."
        ),
    },
    "network_isochrone": {
        "name": "How Far By Road, Not By Air",
        "svg": "network_isochrone.svg",
        "description": (
            "For indicators about reaching a service — a school, a hospital, a bus "
            "stop — a straight-line circle overstates how accessible a place really "
            "is: rivers, dead-end streets and missing roads all make a destination "
            "further away in practice than it looks on a map. This technique instead "
            "traces the actual road network outward from each facility in several steps "
            "(for example a 5-, 10- and 15-minute walk) and scores a grid cell by which "
            "travel-time ring it falls inside. The resulting shape hugs the street layout "
            "rather than forming a tidy circle — a facility beside the only bridge "
            "over a river reaches much further along the road than it does across the "
            "water."
        ),
    },
    "raster_lookup": {
        "name": "Reading a Ready-Made Map",
        "svg": "raster_lookup.svg",
        "description": (
            "Some of the data this analysis draws on arrives as a finished map rather "
            "than a set of points or lines — a satellite-derived picture of "
            "night-time brightness, say, or a hazard model showing flood risk across the "
            "whole country. For indicators like these, there's no counting or buffering "
            "to do: each grid cell simply reads off the value already present at that "
            "location, the same way you'd read a figure off a weather map by pointing at "
            "a city. A brightly lit area scores well on the night-time-lights indicator "
            "(used here as a rough proxy for how safe a place feels after dark); a "
            "high-risk zone scores poorly on a hazard indicator."
        ),
    },
    "zone_classification": {
        "name": "Which Zone You're Standing In",
        "svg": "zone_classification.svg",
        "description": (
            "A small number of indicators come from boundary data rather than points, "
            "lines or a continuous map — a layer of named zones, each carrying its "
            "own attribute, such as a safety rating reported by residents. This technique "
            "works out which zone a grid cell falls inside, looks up that zone's "
            "attribute value in a conversion table, and assigns the matching 0–5 "
            "score to every cell inside it. Two cells a street apart can end up with very "
            "different scores if they happen to sit on opposite sides of a zone boundary "
            "— the result is only ever as fine-grained as the zones it was collected "
            "in."
        ),
    },
    "population_share": {
        "name": "A Ready-Made Demographic Split",
        "svg": "population_share.svg",
        "description": (
            "Occasionally the figure an indicator needs has already been calculated by "
            "somebody else and handed over pre-matched to this analysis's own grid — "
            "the share of a cell's population living in an urban versus a rural "
            "settlement, say, taken from aggregated census-style data. There's no "
            "spatial join or buffering left to do: the value is simply attached to the "
            "matching grid cell by a shared location key, then rescaled onto the 0–5 "
            "scale."
        ),
    },
}

#: analysis_mode -> technique_key. Several modes share a technique -
#: see the module docstring. Aggregation-role modes ("factor_aggregation"
#: etc.) and "Do Not Use" deliberately have no entry: they aren't a
#: data-collection technique, they're how already-scored indicators get
#: blended together (covered on the "Scoring Weights" page instead).
ANALYSIS_MODE_TECHNIQUE = {
    "use_index_score": "index_score",
    "use_contextual_index_score": "index_score",
    "use_eplex_score": "index_score",
    "use_index_score_with_ookla": "index_score",
    "use_index_score_with_ghsl": "index_score",
    "use_point_per_cell": "feature_count",
    "use_polyline_per_cell": "feature_count",
    "use_polygon_per_cell": "feature_count",
    "use_osm_transport_polyline_per_cell": "feature_count",
    "use_single_buffer_point": "distance_buffer",
    "use_street_lights": "distance_buffer",
    "use_csv_to_point_layer": "distance_buffer",
    "use_multi_buffer_point": "network_isochrone",
    "use_nighttime_lights": "raster_lookup",
    "use_environmental_hazards": "raster_lookup",
    "use_classify_polygon_into_classes": "zone_classification",
    "use_classify_safety_polygon_into_classes": "zone_classification",
    "use_s2s_urban_rural_share": "population_share",
}

#: analysis_mode -> a one-sentence note on what makes THIS mode's data
#: or scoring differ from its technique siblings - shown alongside the
#: indicator's name on the Methodology page, not repeated in the
#: technique description itself.
ANALYSIS_MODE_NUANCE = {
    "use_index_score_with_ookla": "Only scored where broadband coverage data exists.",
    "use_index_score_with_ghsl": "Only scored inside built-up settlements.",
    "use_osm_transport_polyline_per_cell": ("Combines road and cycle-path data, keeping whichever scores higher."),
    "use_csv_to_point_layer": (
        "Each event type gets its own buffer distance; where buffers overlap, "
        "the higher-impact (closest) value wins."
    ),
    "use_nighttime_lights": (
        "Night-time brightness is used as a proxy for how safe an area feels "
        "after dark, not a direct safety measurement."
    ),
}


def technique_for_analysis_mode(analysis_mode: str) -> Optional[str]:
    """The technique key for an indicator's analysis_mode, or None if
    it isn't a data-collection technique (aggregation roles, "Do Not
    Use", or an analysis_mode added since this reference was written).
    """
    return ANALYSIS_MODE_TECHNIQUE.get(analysis_mode)


def nuance_for_analysis_mode(analysis_mode: str) -> str:
    """One-sentence note on how this specific analysis_mode's data or
    scoring differs from its technique siblings, or "" if there's
    nothing beyond the technique's own general description.
    """
    return ANALYSIS_MODE_NUANCE.get(analysis_mode, "")
