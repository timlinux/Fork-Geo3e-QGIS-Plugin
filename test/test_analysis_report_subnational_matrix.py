# -*- coding: utf-8 -*-
"""Tests for the analysis report's subnational score matrix page: one
row per administrative zone, one colour-coded cell per used
dimension/factor/the overall total, reading the avg_<column>/zone_name
fields SubnationalAggregationProcessingTask.aggregate_factor_dimension_totals()
writes.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from osgeo import ogr
from qgis.PyQt.QtGui import QColor

from geest.core.reports.analysis_report import AnalysisReport


class TestSubnationalScoreMatrixEnabled(unittest.TestCase):
    """_subnational_score_matrix_enabled() gates the whole section
    behind a Settings > GeoE3 opt-in, off by default - a project with
    many zones can otherwise add a very large number of pages.
    """

    @patch("geest.core.reports.analysis_report.setting")
    def test_disabled_by_default(self, mock_setting):
        mock_setting.side_effect = lambda key, default=None: default

        self.assertFalse(AnalysisReport._subnational_score_matrix_enabled())

    @patch("geest.core.reports.analysis_report.setting")
    def test_enabled_when_setting_is_true(self, mock_setting):
        mock_setting.side_effect = lambda key, default=None: True

        self.assertTrue(AnalysisReport._subnational_score_matrix_enabled())


class TestScoreClassColor(unittest.TestCase):
    """_score_class_color() matches the same 5-class DISCRETE boundary
    every map in this report uses (resources/qml/analysis.qml).
    """

    def test_none_is_white(self):
        from geest.core.reports.base_report import WHITE

        self.assertEqual(AnalysisReport._score_class_color(None), WHITE)

    def test_zero_is_white(self):
        from geest.core.reports.base_report import WHITE

        self.assertEqual(AnalysisReport._score_class_color(0.0), WHITE)

    def test_value_in_the_lowest_class(self):
        from geest.core.constants import SCORE_LEGEND_COLORS

        self.assertEqual(AnalysisReport._score_class_color(0.5), QColor(SCORE_LEGEND_COLORS[1]))

    def test_value_at_the_top_of_scale(self):
        from geest.core.constants import SCORE_LEGEND_COLORS

        self.assertEqual(AnalysisReport._score_class_color(5.0), QColor(SCORE_LEGEND_COLORS[5]))


class TestSubnationalScoreMatrixColumns(unittest.TestCase):
    """_subnational_score_matrix_columns() mirrors
    SubnationalAggregationProcessingTask._factor_dimension_total_columns()'s
    column set/order exactly, from model.json.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_matrix_columns_")
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report = MagicMock()
        self.report.model_path = self.model_path
        self.report._has_used_factors.side_effect = lambda d: AnalysisReport._has_used_factors(self.report, d)
        self.report._has_used_indicators.side_effect = lambda f: AnalysisReport._has_used_indicators(self.report, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_model(self, dimensions):
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump({"dimensions": dimensions}, f)

    def test_includes_used_dimensions_factors_and_the_total(self):
        self._write_model(
            [
                {
                    "id": "alpha",
                    "name": "Alpha",
                    "factors": [
                        {"id": "a", "name": "Factor A", "indicators": [{"analysis_mode": "Use"}]},
                        {"id": "b", "name": "Factor B", "indicators": [{"analysis_mode": "Do Not Use"}]},
                    ],
                }
            ]
        )

        columns = AnalysisReport._subnational_score_matrix_columns(self.report)

        self.assertEqual(
            columns,
            [("Alpha", "dim_alpha"), ("Factor A", "fac_a"), ("GeoE3 Score", "geoe3")],
        )

    def test_dimension_with_no_used_factors_is_skipped(self):
        self._write_model(
            [
                {
                    "id": "alpha",
                    "name": "Alpha",
                    "factors": [{"id": "a", "indicators": [{"analysis_mode": "Do Not Use"}]}],
                }
            ]
        )

        columns = AnalysisReport._subnational_score_matrix_columns(self.report)

        self.assertEqual(columns, [("GeoE3 Score", "geoe3")])


class TestSubnationalScoreMatrixRows(unittest.TestCase):
    """_subnational_score_matrix_rows() only returns data once the
    aggregates GeoPackage actually has the avg_<column>/zone_name
    fields - an analysis that hasn't been re-run since this feature
    was added must be skipped, not crash.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_matrix_rows_")
        self.report = MagicMock()
        self.report.working_directory = self.temp_dir
        self.report._subnational_score_matrix_columns.return_value = [
            ("Alpha", "dim_alpha"),
            ("GeoE3 Score", "geoe3"),
        ]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _gpkg_path(self):
        agg_dir = os.path.join(self.temp_dir, "subnational_aggregation")
        os.makedirs(agg_dir, exist_ok=True)
        return os.path.join(agg_dir, "geoe3_score_subnational_aggregation.gpkg")

    def _make_aggregates(self, with_new_columns):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self._gpkg_path())
        layer = dataset.CreateLayer("geoe3_score_subnational_aggregation", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("_majority", ogr.OFTReal))
        if with_new_columns:
            layer.CreateField(ogr.FieldDefn("zone_name", ogr.OFTString))
            layer.CreateField(ogr.FieldDefn("avg_dim_alpha", ogr.OFTReal))
            layer.CreateField(ogr.FieldDefn("avg_geoe3", ogr.OFTReal))
        layer_defn = layer.GetLayerDefn()
        rows = [("Zone One", 3.5, 4.0), ("Zone Two", 1.5, 2.0)] if with_new_columns else [(None, None, None)]
        for row in rows:
            feature = ogr.Feature(layer_defn)
            if with_new_columns:
                feature.SetField("zone_name", row[0])
                feature.SetField("avg_dim_alpha", row[1])
                feature.SetField("avg_geoe3", row[2])
            layer.CreateFeature(feature)
        dataset = None

    def test_missing_gpkg_returns_none(self):
        self.assertIsNone(AnalysisReport._subnational_score_matrix_rows(self.report))

    def test_legacy_gpkg_without_new_columns_returns_none(self):
        self._make_aggregates(with_new_columns=False)

        self.assertIsNone(AnalysisReport._subnational_score_matrix_rows(self.report))

    def test_reads_zone_names_and_averages_in_column_order(self):
        self._make_aggregates(with_new_columns=True)

        columns, rows = AnalysisReport._subnational_score_matrix_rows(self.report)

        self.assertEqual(columns, [("Alpha", "dim_alpha"), ("GeoE3 Score", "geoe3")])
        self.assertEqual(rows, [("Zone One", [3.5, 4.0]), ("Zone Two", [1.5, 2.0])])

    def test_no_working_directory_returns_none(self):
        self.report.working_directory = None

        self.assertIsNone(AnalysisReport._subnational_score_matrix_rows(self.report))


class TestMakeSubnationalScoreMatrixPages(unittest.TestCase):
    """make_subnational_score_matrix_pages() only adds pages when
    there's a subnational boundary with real data, and rasterises each
    page as a single image rather than one QgsLayoutItem per cell -
    confirmed against real data that the per-cell approach brings
    QGIS's layout engine to a crawl for a few thousand cells.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}
        self.report._render_score_matrix_page_image.return_value = os.path.join(tempfile.gettempdir(), "fake.png")

    def test_no_subnational_boundary_adds_no_pages(self):
        self.report._subnational_score_matrix_rows.return_value = None

        result = AnalysisReport.make_subnational_score_matrix_pages(self.report, current_page=5)

        self.assertEqual(result, 5)
        self.report.make_page.assert_not_called()

    def test_empty_rows_adds_no_pages(self):
        self.report._subnational_score_matrix_rows.return_value = ([("GeoE3 Score", "geoe3")], [])

        result = AnalysisReport.make_subnational_score_matrix_pages(self.report, current_page=5)

        self.assertEqual(result, 5)

    def test_renders_one_image_per_page_not_one_item_per_cell(self):
        columns = [("GeoE3 Score", "geoe3")]
        rows = [(f"Zone {i}", [float(i % 5)]) for i in range(100)]
        self.report._subnational_score_matrix_rows.return_value = (columns, rows)

        result = AnalysisReport.make_subnational_score_matrix_pages(self.report, current_page=5)

        # One make_page()/one _render_score_matrix_page_image()/one
        # _place_picture() call per row-page, plus one extra make_page()
        # for the key page - NOT one _label()/_rect() per cell (100
        # rows x 1 column = 100 cells).
        self.assertGreater(self.report.make_page.call_count, 0)
        self.assertEqual(self.report.make_page.call_count, self.report._render_score_matrix_page_image.call_count + 1)
        self.assertEqual(self.report._place_picture.call_count, self.report._render_score_matrix_page_image.call_count)
        self.assertGreater(result, 5)
        self.report._rect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
