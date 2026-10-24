# -*- coding: utf-8 -*-
"""Tests for the analysis report's score-distribution sparkline.

AnalysisReport/BaseReport are heavy classes (full QgsLayout/template
construction), so these call the unbound methods directly against a
lightweight MagicMock stand-in, matching the pattern in
test_tree_panel_download_all_resources.py.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy
from osgeo import ogr
from qgis.PyQt.QtGui import QColor

from geest.core.reports.analysis_report import AnalysisReport
from geest.core.reports.base_report import BaseReport


class TestGridColumnScoreHistogram(unittest.TestCase):
    """Reads the study_area_grid column directly - the same values every
    result raster was rasterised from - rather than re-deriving the
    distribution from the rasterised output, which (a) is a resampled
    render of those same values, and (b) for some products (e.g. the
    1-15 bivariate "by population" score) uses an entirely different
    colour scheme than the plain 0-5 scale this sparkline shows.

    Score 0 must never leak into the 1-5 distribution the sparkline shows.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_score_histogram_")
        self.gpkg_path = os.path.join(self.temp_dir, "study_area.gpkg")
        self.report = MagicMock()
        self.report.grid_gpkg_path = self.gpkg_path
        # self.report is a MagicMock, so without this the histogram methods'
        # internal call to self._read_grid_column_values(...) would hit an
        # auto-mocked attribute instead of the real method under test.
        self.report._read_grid_column_values.side_effect = lambda column_name: (
            AnalysisReport._read_grid_column_values(self.report, column_name)
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_grid(self, column_name, values):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("study_area_grid", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn(column_name, ogr.OFTReal))
        layer_defn = layer.GetLayerDefn()
        for value in values:
            feature = ogr.Feature(layer_defn)
            if value is not None:
                feature.SetField(column_name, value)
            layer.CreateFeature(feature)
        dataset = None

    def test_excludes_score_zero_from_the_returned_counts(self):
        self._make_grid("geoe3", [0, 0, 0, 1, 2, 2, 3, 4, 5, 5])

        counts = AnalysisReport._grid_column_score_histogram(self.report, "geoe3")

        self.assertEqual(counts, [1, 2, 1, 1, 2])

    def test_null_cells_are_not_counted_as_score_zero(self):
        self._make_grid("geoe3", [None, None, 1, 1, 1])

        counts = AnalysisReport._grid_column_score_histogram(self.report, "geoe3")

        self.assertEqual(counts, [3, 0, 0, 0, 0])

    def test_fractional_values_match_the_qml_discrete_boundaries(self):
        """Regression: a prior raster-based scheme centred bins on each
        integer (e.g. [2.5, 3.5) for score "3"), disagreeing with the
        map's own right-inclusive QML boundaries (0,1],(1,2],(2,3],(3,4],
        (4,5] - a column of mostly 3.3-3.99 values painted entirely green
        on the map but showed up as a yellow "3" bar on the sparkline.
        """
        self._make_grid("geoe3", [3.3, 3.5, 3.8, 3.99])

        counts = AnalysisReport._grid_column_score_histogram(self.report, "geoe3")

        self.assertEqual(counts, [0, 0, 0, 4, 0])

    def test_value_exactly_at_a_boundary_belongs_to_the_lower_class(self):
        """QGIS's DISCRETE shader is right-inclusive: value == 3.0 belongs
        to the (2,3] "yellow" class, not (3,4] "green"."""
        self._make_grid("geoe3", [3.0])

        counts = AnalysisReport._grid_column_score_histogram(self.report, "geoe3")

        self.assertEqual(counts, [0, 0, 1, 0, 0])

    def test_missing_gpkg_returns_five_zero_counts(self):
        self.report.grid_gpkg_path = os.path.join(self.temp_dir, "does_not_exist.gpkg")

        counts = AnalysisReport._grid_column_score_histogram(self.report, "geoe3")

        self.assertEqual(counts, [0, 0, 0, 0, 0])

    def test_unsafe_column_name_is_refused(self):
        self._make_grid("geoe3", [1, 2, 3])

        counts = AnalysisReport._grid_column_score_histogram(self.report, "geoe3; DROP TABLE study_area_grid")

        self.assertEqual(counts, [0, 0, 0, 0, 0])


class TestGridColumnPaletteHistogram(unittest.TestCase):
    """The "by population" bivariate product (1-15, PalettedRasterRenderer
    in geoe3_by_population_score.qml) needs EXACT-value counting, not the
    (lower, upper] range bucketing _grid_column_score_histogram() uses.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_palette_histogram_")
        self.gpkg_path = os.path.join(self.temp_dir, "study_area.gpkg")
        self.report = MagicMock()
        self.report.grid_gpkg_path = self.gpkg_path
        self.report._read_grid_column_values.side_effect = lambda column_name: (
            AnalysisReport._read_grid_column_values(self.report, column_name)
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_grid(self, column_name, values):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("study_area_grid", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn(column_name, ogr.OFTReal))
        layer_defn = layer.GetLayerDefn()
        for value in values:
            feature = ogr.Feature(layer_defn)
            if value is not None:
                feature.SetField(column_name, value)
            layer.CreateFeature(feature)
        dataset = None

    def test_counts_each_exact_value_separately(self):
        self._make_grid("geoe3_by_population", [1, 1, 7, 15, 15, 15])

        counts = AnalysisReport._grid_column_palette_histogram(self.report, "geoe3_by_population", 15)

        expected = [0] * 15
        expected[0] = 2  # value 1
        expected[6] = 1  # value 7
        expected[14] = 3  # value 15
        self.assertEqual(counts, expected)

    def test_excludes_score_zero_from_the_returned_counts(self):
        self._make_grid("geoe3_by_population", [0, 0, 5])

        counts = AnalysisReport._grid_column_palette_histogram(self.report, "geoe3_by_population", 15)

        self.assertEqual(counts[4], 1)  # value 5
        self.assertEqual(sum(counts), 1)


class TestDrawSparkline(unittest.TestCase):
    """_draw_sparkline() scales bar heights relative to the tallest bar.

    show_percentages=False throughout this class - it's about the bar
    geometry specifically; the percentage-label feature (which eats into
    the same height budget) has its own TestDrawSparklinePercentages below.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report._rect = MagicMock()

    def test_bar_heights_are_proportional_to_the_peak_value(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[1, 2, 4],
            colors=["red", "orange", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
            show_percentages=False,
        )

        self.assertEqual(self.report._rect.call_count, 3)
        heights = [call_args.args[3] for call_args in self.report._rect.call_args_list]
        self.assertAlmostEqual(heights[0], 2.0)  # 1/4 of peak * h=8
        self.assertAlmostEqual(heights[1], 4.0)  # 2/4 of peak * h=8
        self.assertAlmostEqual(heights[2], 8.0)  # 4/4 of peak * h=8

    def test_zero_value_bars_are_skipped(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[0, 3],
            colors=["red", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
            show_percentages=False,
        )

        self.assertEqual(self.report._rect.call_count, 1)
        self.assertEqual(self.report._rect.call_args.args[-1], 1)

    def test_all_zero_values_draws_nothing(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[0, 0, 0],
            colors=["red", "orange", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
            show_percentages=False,
        )

        self.report._rect.assert_not_called()

    def test_empty_values_draws_nothing(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[],
            colors=[],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
            show_percentages=False,
        )

        self.report._rect.assert_not_called()


class TestDrawSparklinePercentages(unittest.TestCase):
    """show_percentages=True (the default) labels each bar with its share
    of the total, e.g. "25%" - skipping bars that round to 0%.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report._rect = MagicMock()
        self.report._label = MagicMock()

    def test_each_bar_is_labelled_with_its_rounded_percentage_of_the_total(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[1, 3],  # 25% / 75% of a total of 4
            colors=["red", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
        )

        texts = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertEqual(texts, ["25%", "75%"])

    def test_a_bar_rounding_to_zero_percent_is_not_labelled(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[1, 999],  # 1/1000 rounds to 0%
            colors=["red", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
        )

        texts = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertEqual(texts, ["100%"])

    def test_show_percentages_false_draws_no_labels(self):
        BaseReport._draw_sparkline(
            self.report,
            values=[1, 2, 4],
            colors=["red", "orange", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
            show_percentages=False,
        )

        self.report._label.assert_not_called()

    def test_percentages_still_reserve_height_budget_even_for_a_skipped_zero_value_bar(self):
        # A 0-value bar draws no rect, but still occupies a column and (if
        # its share rounds above 0%, which it can't here) could be
        # labelled - mainly guards that passing a 0 doesn't raise.
        BaseReport._draw_sparkline(
            self.report,
            values=[0, 4],
            colors=["red", "blue"],
            x=0.0,
            y=0.0,
            w=10.0,
            h=8.0,
            page=1,
        )

        self.assertEqual(self.report._rect.call_count, 1)
        texts = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertEqual(texts, ["100%"])


class TestGridColumnName(unittest.TestCase):
    """Mirrors JsonTreeItem.gridColumnName()'s sanitisation exactly, since
    report code only has the model dict (not a JsonTreeItem) to work from.
    """

    def test_dimension_gets_dim_prefix(self):
        self.assertEqual(AnalysisReport._grid_column_name("dimension", "Contextual"), "dim_contextual")

    def test_factor_gets_fac_prefix(self):
        self.assertEqual(AnalysisReport._grid_column_name("factor", "EPLEX"), "fac_eplex")

    def test_indicator_has_no_prefix(self):
        self.assertEqual(
            AnalysisReport._grid_column_name("indicator", "eplex_score_indicator"), "eplex_score_indicator"
        )

    def test_spaces_and_hyphens_become_underscores(self):
        self.assertEqual(
            AnalysisReport._grid_column_name("factor", "Travel Patterns-2"),
            "fac_travel_patterns_2",
        )


class TestAdmin0Name(unittest.TestCase):
    """_admin0_name() reads study_area/boundaries_dissolved.gpkg, picking
    out the dissolve field by TYPE (first String field) rather than by
    name or position - GeoPackage's own integer "fid" primary key shows
    up as QGIS field 0, ahead of whatever name column the user picked
    during project setup.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_admin0_name_")
        self.study_area_dir = os.path.join(self.temp_dir, "study_area")
        os.makedirs(self.study_area_dir)
        self.gpkg_path = os.path.join(self.study_area_dir, "boundaries_dissolved.gpkg")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_dissolved_boundary(self, field_name, values):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("boundaries_dissolved", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn(field_name, ogr.OFTString))
        layer_defn = layer.GetLayerDefn()
        for value in values:
            feature = ogr.Feature(layer_defn)
            feature.SetField(field_name, value)
            layer.CreateFeature(feature)
        dataset = None

    def test_reads_the_name_field_regardless_of_its_name(self):
        self._make_dissolved_boundary("ADM0_EN", ["Tunisia"])
        self.assertEqual(AnalysisReport._admin0_name(self.temp_dir), "Tunisia")

    def test_skips_the_geopackage_fid_field(self):
        # GeoPackage always prepends an integer "fid" primary key field,
        # ahead of the String name field the user actually chose.
        self._make_dissolved_boundary("country_name", ["Kenya"])
        self.assertEqual(AnalysisReport._admin0_name(self.temp_dir), "Kenya")

    def test_joins_multiple_distinct_values_with_a_comma(self):
        self._make_dissolved_boundary("ADM0_EN", ["Kenya", "Uganda"])
        self.assertEqual(AnalysisReport._admin0_name(self.temp_dir), "Kenya, Uganda")

    def test_missing_working_directory_returns_empty_string(self):
        self.assertEqual(AnalysisReport._admin0_name(None), "")

    def test_missing_dissolved_boundary_file_returns_empty_string(self):
        self.assertEqual(AnalysisReport._admin0_name(self.temp_dir), "")


class TestAddMinimapGridSparklineEligibility(unittest.TestCase):
    """Only minimaps with a grid_column on the plain 0-5 scale get a
    sparkline - e.g. the "by population" bivariate product must not, since
    it uses a completely different 1-15 colour scheme.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report._map_layers.side_effect = lambda layer: [layer]

    def test_sparkline_drawn_only_for_entries_with_a_grid_column(self):
        layer_a = MagicMock()
        layer_b = MagicMock()
        minimaps = [
            ("Dimension A", layer_a, "dim_a", "likert"),
            ("By population", layer_b, None, None),
        ]

        AnalysisReport._add_minimap_grid(self.report, minimaps, current_page=1, top=50.0)

        self.assertEqual(self.report.make_minimap.call_count, 2)
        self.report._draw_sparkline_for_column.assert_called_once()
        called_kwargs = self.report._draw_sparkline_for_column.call_args.kwargs
        self.assertEqual(called_kwargs["column_name"], "dim_a")
        self.assertEqual(called_kwargs["palette"], "likert")


class TestReadVectorFieldValues(unittest.TestCase):
    """_read_vector_field_values() reads a subnational aggregation
    vector layer's own per-zone score field directly - these products
    have no study_area_grid column backing them (one administrative
    zone per feature, not one grid cell), so they can't go through
    _read_grid_column_values() like every other product.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_vector_field_values_")
        self.gpkg_path = os.path.join(self.temp_dir, "subnational.gpkg")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_zones(self, values):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("zones", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("_majority", ogr.OFTReal))
        layer_defn = layer.GetLayerDefn()
        for value in values:
            feature = ogr.Feature(layer_defn)
            if value is not None:
                feature.SetField("_majority", value)
            layer.CreateFeature(feature)
        dataset = None

    def _load_layer(self):
        from qgis.core import QgsVectorLayer

        return QgsVectorLayer(f"{self.gpkg_path}|layername=zones", "zones", "ogr")

    def test_excludes_null_and_zero_values(self):
        self._make_zones([1.0, 0.0, None, 3.5])
        values = AnalysisReport._read_vector_field_values(self._load_layer(), "_majority")
        self.assertEqual(sorted(values.tolist()), [1.0, 3.5])

    def test_missing_field_returns_empty_array(self):
        self._make_zones([1.0])
        values = AnalysisReport._read_vector_field_values(self._load_layer(), "nonexistent_field")
        self.assertEqual(values.size, 0)


class TestAddVectorMapPage(unittest.TestCase):
    """_add_vector_map_page() builds a subnational aggregation page:
    one map (no study area outline - see its own docstring for why
    mixing CRSes there silently breaks the extent) plus an inset
    sparkline read from the layer's own score field, not a grid column.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_missing_layer_skips_the_page_and_returns_false(self):
        self.report._load_vector.return_value = None

        added = AnalysisReport._add_vector_map_page(self.report, "Title", "Title", "bad_uri", current_page=5)

        self.assertFalse(added)
        self.report.make_page.assert_not_called()

    def test_valid_layer_draws_the_map_without_the_study_area_outline(self):
        layer = MagicMock()
        self.report._load_vector.return_value = layer
        self.report._read_vector_field_values.return_value = numpy.array([1.0, 2.0])

        added = AnalysisReport._add_vector_map_page(self.report, "Title", "Title", "good_uri", current_page=5)

        self.assertTrue(added)
        self.report.make_map.assert_called_once()
        self.assertEqual(self.report.make_map.call_args.kwargs["layers"], [layer])
        self.report._draw_main_map_sparkline_for_values.assert_called_once()

    def test_no_score_values_skips_the_sparkline(self):
        layer = MagicMock()
        self.report._load_vector.return_value = layer
        self.report._read_vector_field_values.return_value = numpy.array([])

        AnalysisReport._add_vector_map_page(self.report, "Title", "Title", "good_uri", current_page=5)

        self.report._draw_main_map_sparkline_for_values.assert_not_called()


class TestTotalAnalysisDurationMinutes(unittest.TestCase):
    """_total_analysis_duration_minutes() spans the earliest to the
    latest timestamp found anywhere in the model (dimensions, factors,
    indicators) - not a sum of each step's own duration, which would
    overstate the real elapsed time for anything that ran concurrently.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_total_duration_")
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report = MagicMock()
        self.report.model_path = self.model_path
        self.report.parse_iso_datetime.side_effect = lambda value: AnalysisReport.parse_iso_datetime(self.report, value)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_model(self, model):
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump(model, f)

    def test_spans_the_earliest_start_to_the_latest_end_across_all_levels(self):
        self._write_model(
            {
                "dimensions": [
                    {
                        "execution_start_time": "2026-01-01T09:00:00",
                        "execution_end_time": "2026-01-01T09:05:00",
                        "factors": [
                            {
                                "execution_start_time": "2026-01-01T09:01:00",
                                "execution_end_time": "2026-01-01T11:30:00",
                                "indicators": [
                                    {
                                        "execution_start_time": "2026-01-01T09:02:00",
                                        "execution_end_time": "2026-01-01T09:03:00",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )

        minutes = AnalysisReport._total_analysis_duration_minutes(self.report)

        self.assertEqual(minutes, 150.0)  # 09:00 -> 11:30

    def test_no_timestamps_anywhere_returns_none(self):
        self._write_model({"dimensions": [{"factors": [{"indicators": [{}]}]}]})

        minutes = AnalysisReport._total_analysis_duration_minutes(self.report)

        self.assertIsNone(minutes)


class TestDrawTotalDurationBlock(unittest.TestCase):
    """_draw_total_duration_block() renders a highlighted note, but only
    when there's room left on the page - it's drawn after a
    variable-length chart, so the page could already be nearly full.
    """

    def setUp(self):
        self.report = MagicMock()

    def test_draws_the_note_when_there_is_room(self):
        AnalysisReport._draw_total_duration_block(self.report, total_minutes=125.0, y=100.0, page=3)

        self.assertGreaterEqual(self.report._rect.call_count, 2)
        self.assertGreaterEqual(self.report._label.call_count, 2)

    def test_skips_drawing_when_it_would_overflow_the_page(self):
        AnalysisReport._draw_total_duration_block(self.report, total_minutes=125.0, y=275.0, page=3)

        self.report._rect.assert_not_called()
        self.report._label.assert_not_called()

    def test_duration_over_an_hour_is_formatted_as_hours_and_minutes(self):
        AnalysisReport._draw_total_duration_block(self.report, total_minutes=125.0, y=100.0, page=3)

        texts = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertIn("2 h 5 min", texts)

    def test_duration_under_an_hour_is_formatted_as_minutes_only(self):
        AnalysisReport._draw_total_duration_block(self.report, total_minutes=45.0, y=100.0, page=3)

        texts = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertIn("45 min", texts)


class TestStudyAreaStats(unittest.TestCase):
    """_study_area_stats() reads the analysis grid cell count directly
    from the GeoPackage and combines it with model.json's own recorded
    cell size/scale - the authoritative sources for each, respectively.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_study_area_stats_")
        self.gpkg_path = os.path.join(self.temp_dir, "study_area.gpkg")
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report = MagicMock()
        self.report.grid_gpkg_path = self.gpkg_path
        self.report.model_path = self.model_path
        self.report.working_directory = self.temp_dir
        self.report._admin0_name.return_value = ""

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_grid(self, n_cells):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("study_area_grid", geom_type=ogr.wkbPolygon)
        layer_defn = layer.GetLayerDefn()
        for _ in range(n_cells):
            layer.CreateFeature(ogr.Feature(layer_defn))
        dataset = None

    def _write_model(self, model):
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump(model, f)

    def test_includes_cell_count_size_and_area(self):
        self._make_grid(4)
        self._write_model({"analysis_cell_size_m": 1000, "analysis_scale": "national"})

        stats = dict(AnalysisReport._study_area_stats(self.report))

        self.assertEqual(stats["Number of grid cells"], "4")
        self.assertEqual(stats["Grid cell size"], "1000 m × 1000 m")
        self.assertEqual(stats["Total analysis area"], "4 km²")
        self.assertEqual(stats["Analysis scale"], "National")

    def test_missing_gpkg_returns_no_stats(self):
        self.report.grid_gpkg_path = os.path.join(self.temp_dir, "does_not_exist.gpkg")

        self.assertEqual(AnalysisReport._study_area_stats(self.report), [])

    def test_admin0_name_included_when_available(self):
        self._make_grid(1)
        self._write_model({})
        self.report._admin0_name.return_value = "Tunisia"

        stats = dict(AnalysisReport._study_area_stats(self.report))

        self.assertEqual(stats["Study area"], "Tunisia")


class TestMakeStudyAreaSummaryPage(unittest.TestCase):
    """make_study_area_summary_page() only adds a page when there's
    something to show - a project with no grid GeoPackage yet
    shouldn't get a blank closing page.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_no_stats_skips_the_page(self):
        self.report._study_area_stats.return_value = []

        AnalysisReport.make_study_area_summary_page(self.report, current_page=9)

        self.report.make_page.assert_not_called()

    def test_stats_available_adds_the_page(self):
        self.report._study_area_stats.return_value = [("Number of grid cells", "4")]

        AnalysisReport.make_study_area_summary_page(self.report, current_page=9)

        self.report.make_page.assert_called_once()
        self.assertEqual(self.report.make_page.call_args.kwargs["title"], "Study Area")


class TestMakeByPopulationLegendPage(unittest.TestCase):
    """make_by_population_legend_page() draws a 5x3 bivariate matrix -
    one swatch per enablement-x-population class - plus an explanatory
    note, mirroring make_legend_page()'s plain 0-5 legend.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_adds_the_page_with_the_right_title(self):
        AnalysisReport.make_by_population_legend_page(self.report, current_page=3)

        self.report.make_page.assert_called_once()
        self.assertEqual(self.report.make_page.call_args.kwargs["title"], "Reading the By-Population Maps")

    def test_draws_one_swatch_per_bivariate_class(self):
        AnalysisReport.make_by_population_legend_page(self.report, current_page=3)

        # 15 class swatches + 2 note-box rects (background + accent stripe).
        self.assertEqual(self.report._rect.call_count, 17)

    def test_bottom_left_swatch_is_the_lowest_class_colour(self):
        from geest.core.constants import GEOE3_BY_POPULATION_COLORS

        AnalysisReport.make_by_population_legend_page(self.report, current_page=3)

        colours_drawn = [call_args.args[4] for call_args in self.report._rect.call_args_list[:15]]
        self.assertEqual(colours_drawn[0], QColor(GEOE3_BY_POPULATION_COLORS[1]))


class TestThinVectorOutlines(unittest.TestCase):
    """_thin_vector_outlines() thins a subnational aggregation layer's
    outline for report rendering only - the style's normal 0.26mm
    outline (sized for the interactive canvas, where far fewer zones
    are ever on screen at once) eats into a large share of each tiny
    zone's visible area once hundreds are packed onto a report page.
    """

    def test_every_symbol_layer_with_a_stroke_is_thinned(self):
        from qgis.core import QgsFillSymbol, QgsSingleSymbolRenderer, QgsVectorLayer

        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "zones", "memory")
        symbol = QgsFillSymbol.createSimple({"outline_width": "0.26", "outline_width_unit": "MM"})
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        AnalysisReport._thin_vector_outlines(layer, width_mm=0.08)

        renderer_symbol = layer.renderer().symbol()
        self.assertAlmostEqual(renderer_symbol.symbolLayer(0).strokeWidth(), 0.08)

    def test_a_layer_with_no_renderer_is_a_no_op(self):
        layer = MagicMock()
        layer.renderer.return_value = None

        AnalysisReport._thin_vector_outlines(layer, width_mm=0.08)  # must not raise


if __name__ == "__main__":
    unittest.main()
