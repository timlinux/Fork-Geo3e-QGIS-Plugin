# -*- coding: utf-8 -*-
"""📦 Analysis Report module.

This module contains functionality for analysis report.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy
from qgis.core import (
    QgsFillSymbol,
    QgsLayout,
    QgsLayoutItemShape,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from geest.core.constants import GEOE3_BY_POPULATION_COLORS, SCORE_LEGEND_COLORS
from geest.utilities import log_message, resources_path

from .base_report import (
    CHARCOAL,
    CONTENT_W,
    CYAN,
    FOOTER_Y,
    GREY,
    HEADER_H,
    MARGIN,
    MIST,
    NAVY,
    RULE,
    WHITE,
    BaseReport,
    _flat_fill,
)

# The five score classes used by every result map in this report
# (see resources/qml/analysis.qml): range, name, colour, significance.
SCORE_CLASSES = [
    (
        "0 – 1",
        "Very Low Enablement",
        "#d7191c",
        "Conditions offer little or no support for employment and " "entrepreneurship; major barriers dominate.",
    ),
    (
        "1 – 2",
        "Low Enablement",
        "#fdae61",
        "Support is limited and significant barriers remain across most " "measured factors.",
    ),
    (
        "2 – 3",
        "Moderately Enabling",
        "#ffffbf",
        "Some supportive conditions exist, but their coverage or quality " "is uneven.",
    ),
    (
        "3 – 4",
        "Enabling",
        "#bce1b8",
        "Conditions generally support access to employment and business " "opportunities.",
    ),
    (
        "4 – 5",
        "Highly Enabling",
        "#2c7bb6",
        "Strong, well-developed enabling conditions across the measured " "factors.",
    ),
]


class AnalysisReport(BaseReport):
    """
    A class to generate a PDF report from the analysis results.

    """

    def __init__(self, model_path: str, working_directory: Optional[str] = None, report_name="GeoE3 Analysis Report"):
        """
        Initialize the report.

        Args:
            model_path: Path to the model JSON file.
            working_directory: Path to the working directory containing the study area GeoPackage.
            report_name: The title to use for the report.
        """
        template_path = resources_path("resources", "qpt", "analysis_summary_report_template.qpt")
        admin0_name = self._admin0_name(working_directory)
        if admin0_name:
            report_name = f"{report_name} — {admin0_name}"
        super().__init__(template_path, report_name)

        self.report_name = report_name
        self.model_path = model_path
        self.working_directory = working_directory
        # Source of truth for _grid_column_score_histogram()'s sparklines -
        # the same GeoPackage every result raster was rasterised FROM.
        self.grid_gpkg_path = (
            os.path.join(working_directory, "study_area", "study_area.gpkg") if working_directory else None
        )
        self.temp_layers = []  # Track layers added to project for cleanup
        self.study_area_layer = None  # Will hold the study area outline layer

        # Load the study area outline layer if working_directory is provided
        if working_directory:
            self._load_study_area_layer()

        self.page_descriptions[
            "analysis_summary"
        ] = """
        This shows the relative elapsed time for each analysis step. The time is in minutes.
        """
        self.page_descriptions[
            "legend"
        ] = """
        Every map in this report uses the same five-class colour scheme, applied to
        scores from 0 to 5. This page explains what the colours mean and how the
        values are derived.
        """

    @staticmethod
    def _admin0_name(working_directory: Optional[str]) -> str:
        """Read the admin0 (country) name chosen during project setup.

        Project creation lets the user pick which field of their study
        area boundary layer holds the area's name (e.g. an "ADM0_EN"
        column); study_area_processing_task.py dissolves the input
        boundary by that field into
        study_area/boundaries_dissolved.gpkg, one feature (and that one
        field, plus GeoPackage's own integer "fid") per distinct value.
        Reads it by field TYPE (the first String field) rather than by
        name or position - the user could have picked any column name,
        and QGIS's own field list (unlike raw OGR's) includes "fid" as
        field 0, so position 0 is the row id, not the name.

        Args:
            working_directory: The project's working directory, or None.

        Returns:
            The admin0 name(s) found (joined with ", " if more than one
            distinct value was dissolved), or "" if the file, layer, or a
            usable field isn't there - callers should fall back to
            whatever title they already have.
        """
        if not working_directory:
            return ""
        gpkg_path = os.path.join(working_directory, "study_area", "boundaries_dissolved.gpkg")
        if not os.path.exists(gpkg_path):
            return ""
        layer = QgsVectorLayer(gpkg_path, "boundaries_dissolved", "ogr")
        if not layer.isValid():
            return ""
        name_field_index = next(
            (i for i, field in enumerate(layer.fields()) if field.typeName() == "String"),
            None,
        )
        if name_field_index is None:
            return ""
        names = []
        for feature in layer.getFeatures():
            value = feature.attribute(name_field_index)
            if value and str(value) not in names:
                names.append(str(value))
        return ", ".join(names)

    def cleanup(self):
        """
        Explicitly clean up temporary layers. Call this when done with the report,
        or use the context manager pattern.
        """
        if self._cleanup_done:
            return
        # Remove temporary layers added for rendering
        for layer in self.temp_layers:
            if layer:
                try:
                    QgsProject.instance().removeMapLayer(layer.id())
                    log_message(f"Removed temporary layer '{layer.name()}' from project.")
                except Exception as e:
                    log_message(f"Could not remove temporary layer: {e}")
        self.temp_layers = []
        super().cleanup()

    def _load_study_area_layer(self):
        """
        Load the study area outline layer from the GeoPackage.
        """
        gpkg_path = self.grid_gpkg_path
        if not gpkg_path or not os.path.exists(gpkg_path):
            log_message(f"Study area GeoPackage not found at {gpkg_path}")
            return

        # Try to load study_area_clip_polygons first, fall back to study_area_polygons
        for layer_name in ["study_area_clip_polygons", "study_area_polygons"]:
            uri = f"{gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, f"Study Area ({layer_name})", "ogr")
            if layer.isValid():
                self.study_area_layer = layer
                # Outline only: the default study-area style has a solid fill
                # which, drawn over the result raster, blanks out the map
                # ("white interior with a black outline"). The report must
                # show the same styled raster the model tree shows, with just
                # a thin boundary on top.
                symbol = QgsFillSymbol.createSimple(
                    {
                        "color": "0,0,0,0",
                        "outline_color": "51,51,51,255",
                        "outline_width": "0.4",
                        "outline_style": "solid",
                    }
                )
                layer.setRenderer(QgsSingleSymbolRenderer(symbol))
                # Add to project temporarily for rendering
                QgsProject.instance().addMapLayer(layer, False)
                self.temp_layers.append(layer)
                log_message(f"Loaded study area outline from {layer_name}")
                break
            else:
                log_message(f"Could not load study area layer: {layer_name}")

    def create_layout(self):
        """
        Create a QGIS layout (report) that includes a title, summary statistics,
        and individual pages for each indicator.
        """
        project = QgsProject.instance()
        self.title = "Analysis Report"
        self.layout = QgsLayout(project)
        self.layout.initializeDefaults()
        self.load_template()
        self.style_cover_page()

        # Credits sit directly behind the cover so funders and developers
        # get a designed, prominent home.
        self.make_credits_page(current_page=1)

        # Explain the colour scheme before showing any maps.
        self.make_legend_page(current_page=2)

        # Then the analysis overview and the dimension/factor pages.
        current_page = self.create_detail_pages(current_page=3)

        # Processing times live at the back of the report — they are
        # technical bookkeeping, not analysis content.
        self.make_page(
            title="Processing Times",
            description_key="analysis_summary",
            current_page=current_page,
            show_header_and_footer=True,
        )
        bottom_y = self.create_execution_time_layout(
            entries=self.extract_execution_times_with_colors(),
            page=current_page,
        )
        total_minutes = self._total_analysis_duration_minutes()
        if total_minutes is not None:
            self._draw_total_duration_block(total_minutes, bottom_y + 6, current_page)
        current_page += 1

        # The study area summary closes the report - readers who want to
        # judge the analysis's resolution and scope land here last.
        self.make_study_area_summary_page(current_page=current_page)
        current_page += 1

    def make_legend_page(self, current_page: int) -> None:
        """Add the legend page: the score colour scheme and what it means.

        A segmented 0-5 colour bar mirrors the ramp used on every result
        map (resources/qml/analysis.qml), followed by one row per class
        explaining its significance, and a note on how scores are derived.
        """
        self.make_page(
            title="Reading the Maps",
            description_key="legend",
            current_page=current_page,
            show_header_and_footer=True,
        )
        # Segmented colour bar with 0-5 tick labels.
        bar_y = HEADER_H + 26
        bar_h = 10
        segment_w = CONTENT_W / len(SCORE_CLASSES)
        # Hairline backing keeps the palest class visible against the page.
        self._rect(MARGIN - 0.3, bar_y - 0.3, CONTENT_W + 0.6, bar_h + 0.6, RULE, current_page)
        for i, (_, _, colour, _) in enumerate(SCORE_CLASSES):
            self._rect(MARGIN + i * segment_w, bar_y, segment_w, bar_h, QColor(colour), current_page)
        for i in range(len(SCORE_CLASSES) + 1):
            self._label(
                str(i),
                MARGIN + i * segment_w - 10,
                bar_y + bar_h + 1.5,
                20,
                5,
                current_page,
                size=8.5,
                color=GREY,
                halign=Qt.AlignmentFlag.AlignHCenter,
            )

        # One row per class: swatch, range and name, significance.
        row_top = bar_y + bar_h + 14
        row_pitch = 23
        for i, (score_range, name, colour, meaning) in enumerate(SCORE_CLASSES):
            y = row_top + i * row_pitch
            self._rect(MARGIN - 0.3, y - 0.3, 22.6, 14.6, RULE, current_page)
            self._rect(MARGIN, y, 22, 14, QColor(colour), current_page)
            self._label(
                f"{score_range}   {name}",
                MARGIN + 28,
                y,
                CONTENT_W - 28,
                7,
                current_page,
                size=11.5,
                color=NAVY,
                bold=True,
            )
            self._label(
                meaning,
                MARGIN + 28,
                y + 7,
                CONTENT_W - 28,
                7,
                current_page,
                size=9.5,
                color=GREY,
            )

        # How the values are derived.
        note_y = row_top + len(SCORE_CLASSES) * row_pitch + 6
        note_h = 42
        self._rect(MARGIN, note_y, CONTENT_W, note_h, MIST, current_page)
        self._rect(MARGIN, note_y, 2.2, note_h, CYAN, current_page)
        self._label(
            "How the scores are calculated",
            MARGIN + 8,
            note_y + 4.5,
            CONTENT_W - 16,
            7,
            current_page,
            size=12,
            color=NAVY,
            bold=True,
        )
        note_body = self._label(
            "<p>Each indicator scores every analysis grid cell from 0 to 5. Indicator "
            "scores combine into factor scores, factor scores into dimension scores, "
            "and dimension scores into the overall GeoE3 score, using the weights "
            "configured in the model. Blank cells fall outside the study area or have "
            "no data; a score of 0 can also mean the measured service is out of reach "
            "— for example, locations with no road-network access.</p>",
            MARGIN + 8,
            note_y + 13,
            CONTENT_W - 16,
            note_h - 17,
            current_page,
            size=9.5,
            color=CHARCOAL,
            html=True,
        )
        note_body.setHAlign(Qt.AlignmentFlag.AlignJustify)

    def _load_raster(self, layer_uri: str, title: str) -> Optional[QgsRasterLayer]:
        """Load (and cache) a raster result layer, or None when unavailable.

        Validity is checked BEFORE any page is created, so an unreadable
        result can never produce a blank page.
        """
        if not layer_uri:
            return None
        if not hasattr(self, "_raster_cache"):
            self._raster_cache = {}
        if layer_uri in self._raster_cache:
            return self._raster_cache[layer_uri]
        layer = QgsRasterLayer(layer_uri, title)
        if not layer.isValid():
            log_message(f"Layer {layer_uri} is invalid — omitted from report.", tag="GeoE3")
            self._raster_cache[layer_uri] = None
            return None
        QgsProject.instance().addMapLayer(layer, False)
        self.temp_layers.append(layer)
        self._raster_cache[layer_uri] = layer
        return layer

    def _load_vector(self, layer_uri: str, title: str) -> Optional[QgsVectorLayer]:
        """Load (and cache) a vector result layer with its sibling .qml
        style, or None when unavailable. Mirrors _load_raster() for the
        subnational aggregation products: plain polygons with no
        embedded symbology, whose categorized/graduated colour scheme
        (matching every other product's score ramp) lives in a .qml file
        sitting next to the GeoPackage (see
        subnational_aggregation_processor.py).
        """
        if not layer_uri:
            return None
        if not hasattr(self, "_vector_cache"):
            self._vector_cache = {}
        if layer_uri in self._vector_cache:
            return self._vector_cache[layer_uri]
        layer = QgsVectorLayer(layer_uri, title, "ogr")
        if not layer.isValid():
            log_message(f"Layer {layer_uri} is invalid — omitted from report.", tag="GeoE3")
            self._vector_cache[layer_uri] = None
            return None
        gpkg_path = layer_uri.split("|", 1)[0]
        qml_path = os.path.splitext(gpkg_path)[0] + ".qml"
        if os.path.exists(qml_path):
            layer.loadNamedStyle(qml_path)
        QgsProject.instance().addMapLayer(layer, False)
        self.temp_layers.append(layer)
        self._vector_cache[layer_uri] = layer
        return layer

    @staticmethod
    def _read_vector_field_values(layer: QgsVectorLayer, field_name: str):
        """Read a vector layer's own attribute values directly - the
        subnational aggregation products' authoritative per-zone score
        (one administrative zone per feature), with no study_area_grid
        column backing them the way per-cell products have.

        Args:
            layer: The vector layer to read.
            field_name: Attribute holding the per-zone score (e.g.
                "_majority").

        Returns:
            A 1-D numpy array of the field's non-null, non-zero values.
        """
        field_index = layer.fields().indexFromName(field_name)
        if field_index < 0:
            return numpy.array([])
        values = [
            value
            for value in (feature.attribute(field_index) for feature in layer.getFeatures())
            if value is not None and value > 0
        ]
        return numpy.array(values, dtype=float)

    def _map_layers(self, layer: QgsRasterLayer) -> list:
        """Raster plus the study area outline when available."""
        layers = [layer]
        if self.study_area_layer:
            layers.append(self.study_area_layer)
        return layers

    def _add_map_page(
        self,
        title: str,
        description_key: str,
        layer_uri: str,
        current_page: int,
        minimaps: Optional[list] = None,
        grid_column: Optional[str] = None,
        palette: str = "likert",
    ) -> bool:
        """Add a page with a large map and an optional grid of minimaps.

        Args:
            title: The title for the page.
            description_key: Key for the page description in self.page_descriptions.
            layer_uri: Path to the raster layer file.
            current_page: The current page number.
            minimaps: Optional list of (caption, QgsRasterLayer, grid_column,
                palette) tuples laid out as a grid beneath the main map.
                grid_column is the study_area_grid column backing that
                layer, or None if it isn't on a scale a sparkline can
                usefully show.
            grid_column: study_area_grid column backing the main map
                itself, or None to skip its own corner sparkline.
            palette: "likert" (plain 0-5 scale) or "by_population" (the
                1-15 enablement x population bivariate scale) - which
                colour scheme grid_column's sparkline (both the main map's
                and every minimap's) should use.

        Returns:
            bool: True if the page was added, False otherwise.
        """
        layer = self._load_raster(layer_uri, title)
        if layer is None:
            log_message(f"No usable layer for '{title}', skipping page", tag="GeoE3")
            return False

        self.make_page(
            title=title,
            description_key=description_key,
            current_page=current_page,
            show_header_and_footer=True,
        )

        minimaps = [m for m in (minimaps or []) if m[1] is not None]
        main_h = 105.0 if minimaps else 200.0
        main_x, main_y, main_w = 15, 52, 180
        self.make_map(
            layers=self._map_layers(layer),
            current_page=current_page,
            crs=layer.crs(),
            x=main_x,
            y=main_y,
            map_width_mm=main_w,
            map_height_mm=main_h,
        )
        if grid_column:
            self._draw_main_map_sparkline(
                column_name=grid_column,
                palette=palette,
                map_x=main_x,
                map_y=main_y,
                map_w=main_w,
                map_h=main_h,
                page=current_page,
            )
        if minimaps:
            # 12 mm clearance leaves room for the main map's outside-frame
            # coordinate annotations.
            self._add_minimap_grid(minimaps, current_page, top=main_y + main_h + 12)
        return True

    def _add_vector_map_page(
        self,
        title: str,
        description_key: str,
        layer_uri: str,
        current_page: int,
        score_field: str = "_majority",
        palette: str = "likert",
    ) -> bool:
        """Add a page for a subnational-aggregation vector product: one
        polygon per administrative zone (the boundary the user chose
        during project setup), coloured by its majority score, with the
        same inset sparkline treatment _add_map_page() gives raster
        products.

        Args:
            title: The title for the page.
            description_key: Key for the page description in self.page_descriptions.
            layer_uri: Path to the vector GeoPackage layer, e.g.
                "<path>.gpkg|layername=<name>".
            current_page: The current page number.
            score_field: Attribute holding the per-zone majority score.
            palette: "likert" (plain 0-5 scale) or "by_population" (the
                1-15 enablement x population bivariate scale) - which
                colour scheme the inset sparkline should use.

        Returns:
            bool: True if the page was added, False otherwise.
        """
        layer = self._load_vector(layer_uri, title)
        if layer is None:
            log_message(f"No usable layer for '{title}', skipping page", tag="GeoE3")
            return False

        self.make_page(
            title=title,
            description_key=description_key,
            current_page=current_page,
            show_header_and_footer=True,
        )

        # Unlike the raster pages, the study area outline isn't overlaid
        # here: the zone polygons already tile the whole study area, so
        # it would be redundant, and it often sits in a different CRS
        # than the aggregation layer (zones come from a user-chosen
        # boundary layer, not the analysis grid) - make_map() combines
        # layer extents without reprojecting, so mixing CRSes there
        # silently produces a near-empty page.
        main_x, main_y, main_w, main_h = 15, 52, 180, 200.0
        self.make_map(
            layers=[layer],
            current_page=current_page,
            crs=layer.crs(),
            x=main_x,
            y=main_y,
            map_width_mm=main_w,
            map_height_mm=main_h,
        )
        values = self._read_vector_field_values(layer, score_field)
        if values.size:
            self._draw_main_map_sparkline_for_values(
                values=values,
                palette=palette,
                map_x=main_x,
                map_y=main_y,
                map_w=main_w,
                map_h=main_h,
                page=current_page,
            )
        return True

    @staticmethod
    def _grid_column_name(role: str, item_id: str) -> str:
        """Mirror JsonTreeItem.gridColumnName()'s sanitisation for report
        code that only has the model dict (not a JsonTreeItem) to work
        from: lower-case, space/hyphen -> underscore, 63-char GeoPackage
        field name limit, with the dim_/fac_ role prefix workflows use.
        """
        raw_id = (item_id or "").lower().replace(" ", "_").replace("-", "_")
        if role == "dimension":
            return f"dim_{raw_id}"[:63]
        if role == "factor":
            return f"fac_{raw_id}"[:63]
        return raw_id[:63]

    def _read_grid_column_values(self, column_name: str):
        """Read study_area_grid's own column values directly from the
        GeoPackage - the same values every result raster was rasterised
        from, and the authoritative source for them (the raster is a
        resampled render, not the data itself).

        Exact 0/NULL is dropped: a large share of cells carry a literal 0
        (outside the populated/opportunity area, not a genuine "very low"
        score), and counting it would flatten the distribution any
        sparkline built from this exists to show.

        Args:
            column_name: study_area_grid column to read.

        Returns:
            A 1-D numpy array of the column's non-null, non-zero values.
        """
        import sqlite3

        from geest.core.grid_column_utils import _quote_sql_identifier

        if not self.grid_gpkg_path or not os.path.exists(self.grid_gpkg_path):
            return numpy.array([])
        try:
            quoted_column = _quote_sql_identifier(column_name)
        except ValueError as error:
            log_message(f"Refusing to read grid column for sparkline: {error}", tag="GeoE3")
            return numpy.array([])

        try:
            connection = sqlite3.connect(self.grid_gpkg_path)
            try:
                rows = connection.execute(
                    f"SELECT {quoted_column} FROM study_area_grid "  # nosec B608
                    f"WHERE {quoted_column} IS NOT NULL AND {quoted_column} > 0"
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as error:
            log_message(f"Could not read grid column '{column_name}' for sparkline: {error}", tag="GeoE3")
            return numpy.array([])

        return numpy.array([row[0] for row in rows], dtype=float)

    def _grid_column_score_histogram(self, column_name: str) -> list:
        """Count study_area_grid's own column values per QGIS's 5-class
        DISCRETE colour-ramp boundaries (see resources/qml/analysis.qml):
        (0,1], (1,2], (2,3], (3,4], (4,5] - matching the colours actually
        painted on the map exactly. Only valid for columns confirmed to
        be on the plain 0-5 scale (see _add_minimap_grid()'s palette
        parameter) - a bivariate product like "by population" uses a
        completely different scheme (see _grid_column_palette_histogram).

        Args:
            column_name: study_area_grid column to read.

        Returns:
            list: Five counts, one per QML class, in (0,1] .. (4,5] order.
        """
        return AnalysisReport._score_histogram_from_values(self._read_grid_column_values(column_name))

    def _grid_column_palette_histogram(self, column_name: str, n_classes: int) -> list:
        """Count study_area_grid's own column values per EXACT integer
        class 1..n_classes, matching a PalettedRasterRenderer's
        unique-value scheme (e.g. geoe3_by_population_score.qml's 15-class
        enablement x population bivariate palette) - unlike
        _grid_column_score_histogram()'s DISCRETE range bucketing, each
        class here is a single exact value, not a (lower, upper] interval.

        Args:
            column_name: study_area_grid column to read.
            n_classes: Number of palette classes (e.g. 15).

        Returns:
            list: n_classes counts, for values 1..n_classes in order.
        """
        return AnalysisReport._palette_histogram_from_values(self._read_grid_column_values(column_name), n_classes)

    @staticmethod
    def _score_histogram_from_values(values) -> list:
        """Count values per QGIS's 5-class DISCRETE colour-ramp boundaries
        (see resources/qml/analysis.qml): (0,1], (1,2], (2,3], (3,4], (4,5]
        - matching the colours actually painted on the map exactly. Only
        valid for values confirmed to be on the plain 0-5 scale - a
        bivariate product like "by population" uses a completely
        different scheme (see _palette_histogram_from_values()). Shared by
        both study_area_grid columns (per-cell) and subnational
        aggregation vector fields (per-zone), which carry the same 0-5
        score but from different sources.

        Returns:
            list: Five counts, one per QML class, in (0,1] .. (4,5] order.
        """
        # right=True => bins[i-1] < value <= bins[i], matching the QML's
        # own right-inclusive class boundaries; index 5 (value > 5) is
        # out of range and dropped by only counting indices 0-4.
        class_index = numpy.digitize(values, bins=[1, 2, 3, 4, 5], right=True)
        return [int(numpy.count_nonzero(class_index == i)) for i in range(5)]

    @staticmethod
    def _palette_histogram_from_values(values, n_classes: int) -> list:
        """Count values per EXACT integer class 1..n_classes, matching a
        PalettedRasterRenderer's unique-value scheme (e.g.
        geoe3_by_population_score.qml's 15-class enablement x population
        bivariate palette) - unlike _score_histogram_from_values()'s
        DISCRETE range bucketing, each class here is a single exact
        value, not a (lower, upper] interval.

        Returns:
            list: n_classes counts, for values 1..n_classes in order.
        """
        rounded = numpy.round(values).astype(int)
        return [int(numpy.count_nonzero(rounded == v)) for v in range(1, n_classes + 1)]

    def _draw_sparkline_for_values(self, values, palette: str, x: float, y: float, w: float, h: float, page: int):
        """Draw a score-distribution sparkline for an already-read array
        of values, coloured with the same ramp the result map itself uses
        for that product, so the bars read as "more of this colour"
        rather than needing a separate legend.

        Args:
            palette: "likert" (plain 0-5 scale) or "by_population" (the
                1-15 enablement x population bivariate scale).
        """
        if palette == "by_population":
            counts = AnalysisReport._palette_histogram_from_values(values, len(GEOE3_BY_POPULATION_COLORS))
            colors = [QColor(color) for color in GEOE3_BY_POPULATION_COLORS.values()]
        else:
            counts = AnalysisReport._score_histogram_from_values(values)
            colors = [QColor(SCORE_LEGEND_COLORS[score]) for score in range(1, 6)]
        self._draw_sparkline(counts, colors, x, y, w, h, page)

    def _draw_sparkline_for_column(
        self, column_name: str, palette: str, x: float, y: float, w: float, h: float, page: int
    ):
        """Draw a score-distribution sparkline for one study_area_grid
        column - see _draw_sparkline_for_values().

        Args:
            column_name: study_area_grid column to read.
            palette: "likert" (plain 0-5 scale) or "by_population" (the
                1-15 enablement x population bivariate scale).
        """
        self._draw_sparkline_for_values(self._read_grid_column_values(column_name), palette, x, y, w, h, page)

    @staticmethod
    def _sparkline_inset_geometry(map_x: float, map_y: float, map_w: float, map_h: float) -> tuple:
        """Position and size for a sparkline inset into a map's own
        bottom-right corner, shared by both the grid-column and the
        vector-field sparkline insets.
        """
        margin = 4.0
        w, h = 36.0, 10.0
        x = map_x + map_w - w - margin
        y = map_y + map_h - h - margin
        return x, y, w, h

    def _draw_main_map_sparkline(
        self,
        column_name: str,
        palette: str,
        map_x: float,
        map_y: float,
        map_w: float,
        map_h: float,
        page: int,
    ) -> None:
        """Inset a small sparkline into the main map's own bottom-right
        corner, backed by a translucent white panel so the bars stay
        legible over whatever colours the map itself shows underneath.
        """
        x, y, w, h = self._sparkline_inset_geometry(map_x, map_y, map_w, map_h)
        pad = 1.5
        self._rect(x - pad, y - pad, w + 2 * pad, h + 2 * pad, WHITE, page, opacity=0.78)
        self._draw_sparkline_for_column(column_name, palette, x, y, w, h, page)

    def _draw_main_map_sparkline_for_values(
        self,
        values,
        palette: str,
        map_x: float,
        map_y: float,
        map_w: float,
        map_h: float,
        page: int,
    ) -> None:
        """Inset a small sparkline into the main map's own bottom-right
        corner for an already-read array of values - see
        _draw_main_map_sparkline(), used for the subnational aggregation
        vector products, which have no study_area_grid column backing
        them.
        """
        x, y, w, h = self._sparkline_inset_geometry(map_x, map_y, map_w, map_h)
        pad = 1.5
        self._rect(x - pad, y - pad, w + 2 * pad, h + 2 * pad, WHITE, page, opacity=0.78)
        self._draw_sparkline_for_values(values, palette, x, y, w, h, page)

    def _add_minimap_grid(
        self,
        minimaps: list,
        current_page: int,
        top: float,
        columns: int = 4,
        bottom: float = 280.0,
    ) -> None:
        """Lay out (caption, layer, grid_column, palette) tuples as a
        captioned minimap grid. Each is followed by a small sparkline of
        its score distribution (excluding 0 - see
        _grid_column_score_histogram()/_grid_column_palette_histogram())
        when grid_column is set - some products (e.g. the binary
        opportunities mask) aren't on any scale a sparkline can usefully
        show, and pass grid_column=None to skip it rather than render a
        meaningless chart.
        """
        gap = 5.0
        cell_w = (180.0 - (columns - 1) * gap) / columns
        caption_h = cell_w + 7  # square map face + caption strip
        sparkline_h = 8.0
        has_any_sparkline = any(grid_column for _caption, _layer, grid_column, _palette in minimaps)
        cell_h = caption_h + sparkline_h if has_any_sparkline else caption_h
        max_rows = max(1, int((bottom - top + gap) // (cell_h + gap)))
        capacity = max_rows * columns
        if len(minimaps) > capacity:
            log_message(
                f"Minimap grid clipped to {capacity} of {len(minimaps)} entries on page {current_page}",
                tag="GeoE3",
            )
            minimaps = minimaps[:capacity]
        for index, (caption, layer, grid_column, palette) in enumerate(minimaps):
            row, col = divmod(index, columns)
            x = 15 + col * (cell_w + gap)
            y = top + row * (cell_h + gap)
            self.make_minimap(
                caption=caption,
                layers=self._map_layers(layer),
                crs=layer.crs(),
                current_page=current_page,
                x=x,
                y=y,
                w=cell_w,
                h=caption_h,
            )
            if grid_column:
                self._draw_sparkline_for_column(
                    column_name=grid_column,
                    palette=palette,
                    x=x,
                    y=y + caption_h,
                    w=cell_w,
                    h=sparkline_h,
                    page=current_page,
                )

    def _has_used_indicators(self, factor: dict) -> bool:
        """Check if a factor has any indicators that are not 'Do Not Use'.

        Args:
            factor: Factor dictionary from the model.

        Returns:
            bool: True if at least one indicator is used.
        """
        for indicator in factor.get("indicators", []):
            if indicator.get("analysis_mode", "") != "Do Not Use":
                return True
        return False

    def _has_used_factors(self, dimension: dict) -> bool:
        """Check if a dimension has any factors with used indicators.

        Args:
            dimension: Dimension dictionary from the model.

        Returns:
            bool: True if at least one factor has used indicators.
        """
        for factor in dimension.get("factors", []):
            if self._has_used_indicators(factor):
                return True
        return False

    def create_detail_pages(self, current_page: int = 1):
        """Iterate over dimensions, factors, and indicators to create detail pages.

        Args:
            current_page: The current page number to start from. Incremented for each new page.
        """

        with open(self.model_path, "r", encoding="utf-8") as f:
            model = json.load(f)

        # --- Analysis overview: the main GeoE3 score map on top, then the
        # dimension aggregates as minimaps, then any additional analysis
        # products (population/mask variants) as further minimaps.
        self.page_descriptions["analysis_overview"] = (
            "The overall GeoE3 score, with the aggregated score for each "
            "dimension and any derived analysis products shown below."
        )
        main_uri = model.get("geoe3_score_ghsl_masked_result_file") or model.get("result_file")
        main_grid_column = "geoe3_masked" if model.get("geoe3_score_ghsl_masked_result_file") else "geoe3"
        # grid_column is None for products not on any scale a sparkline can
        # usefully show: the "x opportunities" products are a combination
        # of two columns with no single grid column of their own, and the
        # opportunities mask itself is binary, not a 1-5 or 1-15 score.
        product_keys = [
            ("result_file", "GeoE3 score", "geoe3", "likert"),
            ("geoe3_score_ghsl_masked_result_file", "GHSL masked", "geoe3_masked", "likert"),
            ("geoe3_by_population", "By population", "geoe3_by_population", "by_population"),
            (
                "geoe3_score_by_population_ghsl_masked_result_file",
                "By population (GHSL)",
                "geoe3_by_population_masked",
                "by_population",
            ),
            ("opportunities_mask_result_file", "Opportunities mask", None, None),
        ]
        dimension_minimaps = [
            (
                dimension.get("name", ""),
                self._load_raster(dimension.get("result_file"), dimension.get("name", "")),
                self._grid_column_name("dimension", dimension.get("id", "")),
                "likert",
            )
            for dimension in model.get("dimensions", [])
            if self._has_used_factors(dimension)
        ]
        product_minimaps = [
            (label, self._load_raster(model.get(key), label), grid_column, palette)
            for key, label, grid_column, palette in product_keys
            if model.get(key) and model.get(key) != main_uri
        ]
        if self._add_map_page(
            "Analysis Overview",
            "analysis_overview",
            main_uri,
            current_page,
            minimaps=dimension_minimaps + product_minimaps,
            grid_column=main_grid_column,
            palette="likert",
        ):
            current_page += 1

        # --- One page per dimension: its map + a grid of factor minimaps
        for dimension in model.get("dimensions", []):
            dim_name = dimension.get("name", "")

            if not self._has_used_factors(dimension):
                log_message(f"Skipping dimension '{dim_name}' - no used indicators", tag="GeoE3")
                continue

            used_factors = [factor for factor in dimension.get("factors", []) if self._has_used_indicators(factor)]

            self.page_descriptions[dim_name] = dimension.get(
                "description", f"Aggregated analysis for dimension: {dim_name}"
            )
            # A dimension with a single factor aggregates to the same surface
            # as that factor — a one-cell minimap grid would just repeat the
            # main map, so skip it.
            factor_minimaps = (
                [
                    (
                        factor.get("name", ""),
                        self._load_raster(factor.get("result_file"), factor.get("name", "")),
                        self._grid_column_name("factor", factor.get("id", "")),
                        "likert",
                    )
                    for factor in used_factors
                ]
                if len(used_factors) > 1
                else []
            )
            if self._add_map_page(
                f"{dim_name} Dimension",
                dim_name,
                dimension.get("result_file"),
                current_page,
                minimaps=factor_minimaps,
                grid_column=self._grid_column_name("dimension", dimension.get("id", "")),
                palette="likert",
            ):
                current_page += 1

            # --- One page per factor: its map + a grid of indicator minimaps
            for factor in used_factors:
                factor_name = factor.get("name", "")
                self.page_descriptions[factor_name] = factor.get(
                    "description", f"Aggregated analysis for factor: {factor_name}"
                )
                used_indicators = [
                    indicator
                    for indicator in factor.get("indicators", [])
                    if indicator.get("analysis_mode", "") != "Do Not Use"
                ]
                # A factor with a single indicator produces the same surface
                # as that indicator — skip the redundant one-cell grid.
                indicator_minimaps = (
                    [
                        (
                            indicator.get("indicator", ""),
                            self._load_raster(indicator.get("result_file"), indicator.get("indicator", "")),
                            self._grid_column_name("indicator", indicator.get("id", "")),
                            "likert",
                        )
                        for indicator in used_indicators
                    ]
                    if len(used_indicators) > 1
                    else []
                )
                if self._add_map_page(
                    f"{factor_name}",
                    factor_name,
                    factor.get("result_file"),
                    current_page,
                    minimaps=indicator_minimaps,
                    grid_column=self._grid_column_name("factor", factor.get("id", "")),
                    palette="likert",
                ):
                    current_page += 1

        # --- Subnational aggregation: one page per product, each a
        # vector GeoPackage (one polygon per administrative zone the
        # user chose during project setup) carrying the majority score
        # within that zone - a different source (per-zone, not
        # per-cell), so _add_map_page()'s raster loader can't show them.
        subnational_product_keys = [
            (
                "geoe3_score_subnational_aggregation",
                "GeoE3 Score — Subnational Aggregation",
                "likert",
            ),
            (
                "geoe3_score_ghsl_masked_subnational_aggregation",
                "GHSL Masked — Subnational Aggregation",
                "likert",
            ),
            (
                "geoe3_by_population_subnational_aggregation",
                "By Population — Subnational Aggregation",
                "by_population",
            ),
            (
                "geoe3_score_by_population_ghsl_masked_subnational_aggregation",
                "By Population (GHSL Masked) — Subnational Aggregation",
                "by_population",
            ),
        ]
        for key, label, palette in subnational_product_keys:
            layer_uri = model.get(key)
            if not layer_uri:
                continue
            score_kind = "enablement x population" if palette == "by_population" else "GeoE3"
            self.page_descriptions[label] = (
                f"The majority {score_kind} score within each administrative zone, "
                "aggregated from the analysis grid."
            )
            if self._add_vector_map_page(label, label, layer_uri, current_page, palette=palette):
                current_page += 1

        return current_page

    def parse_iso_datetime(self, iso_str: str) -> Optional[datetime]:
        """Parse ISO 8601 datetime string safely.

        Args:
            iso_str: ISO 8601 formatted datetime string.

        Returns:
            datetime: Parsed datetime object, or None if parsing fails.
        """
        try:
            return datetime.fromisoformat(iso_str)
        except Exception:
            return None

    def interpolate_color(self, rel: float) -> str:
        """Linearly interpolate between forest green and off-red.

        rel = 0.0 => forest green (#228B22), rel = 1.0 => off-red (#CC4444)

        Args:
            rel: Relative value from 0.0 to 1.0.

        Returns:
            str: Hex color string (e.g., "#228B22").
        """
        fg = (34, 139, 34)  # Forest Green
        or_ = (204, 68, 68)  # Off Red
        r = int(fg[0] + (or_[0] - fg[0]) * rel)
        g = int(fg[1] + (or_[1] - fg[1]) * rel)
        b = int(fg[2] + (or_[2] - fg[2]) * rel)
        return f"#{r:02x}{g:02x}{b:02x}"  # noqa E231

    def extract_execution_times_with_colors(self) -> List[Dict[str, Optional[str]]]:
        """Extract execution times for indicators with relative time and color gradient.

        Returns:
            List[Dict]: A sorted list of dictionaries with indicator, factor, dimension,
                execution_time_minutes, relative_time (0.0-1.0), and color (hex string).
        """

        with open(self.model_path, "r", encoding="utf-8") as f:
            model = json.load(f)

        results = []

        for dimension in model.get("dimensions", []):
            dim_name = dimension.get("name", "")
            for factor in dimension.get("factors", []):
                factor_name = factor.get("name", "")
                for indicator in factor.get("indicators", []):
                    # Skip indicators that are not used
                    analysis_mode = indicator.get("analysis_mode", "")
                    if analysis_mode == "Do Not Use":
                        continue

                    ind_name = indicator.get("indicator", "")
                    start_str = indicator.get("execution_start_time", "")
                    end_str = indicator.get("execution_end_time", "")

                    start_dt = self.parse_iso_datetime(start_str)
                    end_dt = self.parse_iso_datetime(end_str)

                    if start_dt and end_dt:
                        duration = round((end_dt - start_dt).total_seconds() / 60, 2)
                    else:
                        duration = None

                    results.append(
                        {
                            "indicator": ind_name,
                            "factor": factor_name,
                            "dimension": dim_name,
                            "execution_time_minutes": duration,
                        }
                    )

        # Compute relative times
        valid_times = [r["execution_time_minutes"] for r in results if r["execution_time_minutes"] is not None]

        if valid_times:
            min_time = min(valid_times)
            max_time = max(valid_times)
            range_time = max_time - min_time if max_time > min_time else 1.0  # avoid division by zero

            for r in results:
                exec_time = r["execution_time_minutes"]
                if exec_time is not None:
                    rel = (exec_time - min_time) / range_time
                    r["relative_time"] = round(rel, 2)
                    r["color"] = self.interpolate_color(rel)
                else:
                    r["relative_time"] = None
                    r["color"] = None

        # Sort by execution time descending, placing None last
        results.sort(
            key=lambda r: (
                r["execution_time_minutes"] is None,
                -(r["execution_time_minutes"] or 0),
            )
        )

        return results

    def create_execution_time_layout(self, entries: list, max_bar_width_mm: float = 78.0, page: int = 1) -> float:
        """Add a clean horizontal bar chart of indicator execution times.

        Layout per row: indicator name right-aligned in a left column, a
        length-encoded bar, and the duration at the bar's end. Rows carry a
        subtle alternating tint. Indicators that were not run render as a
        greyed label with no bar.

        Args:
            entries: Output from `extract_execution_times_with_colors()`.
            max_bar_width_mm: Bar width for the slowest indicator, in mm.
            page: Page number to draw the chart on.

        Returns:
            float: Y position (mm) just below the last thing drawn, so a
            caller can place more content on the same page without
            overlapping it.
        """
        top = 44.0
        row_pitch = 7.0
        bar_h = 3.6
        label_x = 15.0
        label_w = 72.0
        bar_x = label_x + label_w + 3.0
        max_rows = 32

        clipped = len(entries) > max_rows
        for i, entry in enumerate(entries[:max_rows]):
            y = top + i * row_pitch
            indicator = entry["indicator"]
            duration = entry["execution_time_minutes"]

            if i % 2 == 0:
                self._rect(label_x - 1, y - 1.4, 181.0, row_pitch - 0.6, MIST, page)

            name = indicator if len(indicator) <= 52 else indicator[:49] + "…"
            self._label(
                name,
                label_x,
                y - 0.6,
                label_w,
                row_pitch,
                page,
                size=8,
                color=CHARCOAL if duration is not None else GREY,
                halign=Qt.AlignmentFlag.AlignRight,
            )

            if duration is None:
                self._label("not run", bar_x, y - 0.6, 30, row_pitch, page, size=8, color=GREY)
                continue

            bar_width = max(0.6, max_bar_width_mm * (entry.get("relative_time") or 0.0))
            bar = QgsLayoutItemShape(self.layout)
            bar.attemptMove(QgsLayoutPoint(bar_x, y, QgsUnitTypes.LayoutUnit.LayoutMillimeters), page=page)
            bar.setFixedSize(QgsLayoutSize(bar_width, bar_h, QgsUnitTypes.LayoutUnit.LayoutMillimeters))
            _flat_fill(bar, CYAN)
            self.layout.addLayoutItem(bar)

            self._label(
                f"{duration:g} min",
                bar_x + bar_width + 2,
                y - 0.6,
                28,
                row_pitch,
                page,
                size=8,
                color=GREY,
            )
        rows_shown = min(len(entries), max_rows)
        bottom_y = top + rows_shown * row_pitch
        if clipped:
            self._label(
                f"Showing the {max_rows} slowest steps of {len(entries)}.",
                label_x,
                bottom_y + 2,
                180,
                6,
                page,
                size=8,
                color=GREY,
            )
            bottom_y += 8
        return bottom_y

    def _total_analysis_duration_minutes(self) -> Optional[float]:
        """Wall-clock span of the whole analysis run: the earliest
        execution_start_time to the latest execution_end_time found
        anywhere in the model (dimensions, factors and indicators each
        carry their own pair) - not a sum of every step's own duration,
        which would overstate the real elapsed time for anything that
        ran concurrently.

        Returns:
            Minutes elapsed, or None if the model has no usable
            timestamps (e.g. nothing has been run yet).
        """
        with open(self.model_path, "r", encoding="utf-8") as f:
            model = json.load(f)

        timestamps = []

        def collect(entry: dict) -> None:
            for key in ("execution_start_time", "execution_end_time"):
                parsed = self.parse_iso_datetime(entry.get(key, ""))
                if parsed:
                    timestamps.append(parsed)

        for dimension in model.get("dimensions", []):
            collect(dimension)
            for factor in dimension.get("factors", []):
                collect(factor)
                for indicator in factor.get("indicators", []):
                    collect(indicator)

        if not timestamps:
            return None
        return round((max(timestamps) - min(timestamps)).total_seconds() / 60, 2)

    def _draw_total_duration_block(self, total_minutes: float, y: float, page: int) -> None:
        """A highlighted block stating the whole analysis run's
        wall-clock duration, styled like make_legend_page()'s "How the
        scores are calculated" note.
        """
        note_h = 24.0
        if y + note_h > FOOTER_Y:
            log_message("Not enough room for the total analysis time block - omitted", tag="GeoE3")
            return
        self._rect(MARGIN, y, CONTENT_W, note_h, MIST, page)
        self._rect(MARGIN, y, 2.2, note_h, CYAN, page)
        self._label(
            "Total analysis time",
            MARGIN + 8,
            y + 4.5,
            CONTENT_W - 16,
            7,
            page,
            size=12,
            color=NAVY,
            bold=True,
        )
        hours, minutes = divmod(round(total_minutes), 60)
        duration_text = f"{hours} h {minutes} min" if hours else f"{minutes} min"
        self._label(
            duration_text,
            MARGIN + 8,
            y + 13,
            CONTENT_W - 16,
            note_h - 17,
            page,
            size=11,
            color=CHARCOAL,
            bold=True,
        )

    def _study_area_stats(self) -> list:
        """Key facts about the study area and analysis grid, for the
        closing summary page.

        Returns:
            A list of (label, value) pairs, or [] if the grid
            GeoPackage isn't available.
        """
        if not self.grid_gpkg_path or not os.path.exists(self.grid_gpkg_path):
            return []

        import sqlite3

        try:
            connection = sqlite3.connect(self.grid_gpkg_path)
            try:
                cell_count = connection.execute("SELECT COUNT(*) FROM study_area_grid").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.Error as error:
            log_message(f"Could not read study_area_grid for the study area summary: {error}", tag="GeoE3")
            return []

        with open(self.model_path, "r", encoding="utf-8") as f:
            model = json.load(f)
        cell_size_m = model.get("analysis_cell_size_m")
        analysis_scale = model.get("analysis_scale")

        crs_label = ""
        grid_layer = QgsVectorLayer(f"{self.grid_gpkg_path}|layername=study_area_grid", "study_area_grid", "ogr")
        if grid_layer.isValid():
            crs = grid_layer.crs()
            crs_label = f"{crs.authid()} — {crs.description()}" if crs.authid() else crs.description()

        stats = []
        admin0_name = self._admin0_name(self.working_directory)
        if admin0_name:
            stats.append(("Study area", admin0_name))
        if analysis_scale:
            stats.append(("Analysis scale", str(analysis_scale).title()))
        stats.append(("Number of grid cells", f"{cell_count:,}"))
        if cell_size_m:
            stats.append(("Grid cell size", f"{cell_size_m:g} m × {cell_size_m:g} m"))
            total_area_km2 = cell_count * (float(cell_size_m) ** 2) / 1_000_000
            stats.append(("Total analysis area", f"{total_area_km2:,.0f} km²"))
        if crs_label:
            stats.append(("Coordinate reference system", crs_label))
        return stats

    def make_study_area_summary_page(self, current_page: int) -> None:
        """Add the closing page: key facts about the study area and the
        analysis grid, so a reader can judge the analysis's resolution
        and scope without opening the GeoPackage themselves.
        """
        stats = self._study_area_stats()
        if not stats:
            log_message("No study area stats available - summary page skipped", tag="GeoE3")
            return

        self.page_descriptions["study_area_summary"] = (
            "Key facts about the study area and the analysis grid these results were computed on."
        )
        self.make_page(
            title="Study Area",
            description_key="study_area_summary",
            current_page=current_page,
            show_header_and_footer=True,
        )

        row_top = HEADER_H + 30
        row_pitch = 14
        for i, (label, value) in enumerate(stats):
            y = row_top + i * row_pitch
            if i % 2 == 0:
                self._rect(MARGIN, y - 2, CONTENT_W, row_pitch - 2, MIST, current_page)
            self._label(label, MARGIN + 6, y, 85, 8, current_page, size=10.5, color=GREY)
            self._label(
                value,
                MARGIN + 95,
                y,
                CONTENT_W - 95 - 6,
                8,
                current_page,
                size=11.5,
                color=NAVY,
                bold=True,
            )
