# -*- coding: utf-8 -*-
"""Tests for the analysis report's "insights" pages - patterns in
study_area_grid beyond the final score (limiting dimension, settlement
coverage, opportunity overlap, hazard exposure, factor correlation).

AnalysisReport is a heavy class (full QgsLayout/template construction),
so these call the unbound methods directly against a lightweight
MagicMock stand-in, matching the pattern in
test_analysis_report_sparkline.py.
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


class GridFixtureTestCase(unittest.TestCase):
    """Shared helper for building a study_area_grid GeoPackage with
    arbitrary columns, used by several test classes below.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_insights_")
        self.gpkg_path = os.path.join(self.temp_dir, "study_area.gpkg")
        self.report = MagicMock()
        self.report.grid_gpkg_path = self.gpkg_path
        # self.report is a MagicMock, so without this the insights
        # methods' internal self._read_grid_columns(...)/
        # self._read_grid_columns_with_gaps(...) calls would hit an
        # auto-mocked attribute instead of the real method under test.
        self.report._read_grid_columns.side_effect = lambda columns: AnalysisReport._read_grid_columns(
            self.report, columns
        )
        self.report._read_grid_columns_with_gaps.side_effect = (
            lambda columns: AnalysisReport._read_grid_columns_with_gaps(self.report, columns)
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_grid(self, columns: dict):
        """columns: {column_name: [values, ...]} - all lists the same
        length. A value of None writes a NULL cell.
        """
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("study_area_grid", geom_type=ogr.wkbPolygon)
        for column_name in columns:
            layer.CreateField(ogr.FieldDefn(column_name, ogr.OFTReal))
        layer_defn = layer.GetLayerDefn()
        n_rows = len(next(iter(columns.values())))
        for i in range(n_rows):
            feature = ogr.Feature(layer_defn)
            for column_name, values in columns.items():
                if values[i] is not None:
                    feature.SetField(column_name, values[i])
            layer.CreateFeature(feature)
        dataset = None


class TestReadGridColumns(GridFixtureTestCase):
    """_read_grid_columns() requires EVERY requested column to be
    non-null and > 0 for a row to be returned - used where a single
    cell's values across columns must be compared against each other.
    """

    def test_returns_rows_where_all_columns_are_valid(self):
        self._make_grid({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})

        rows = AnalysisReport._read_grid_columns(self.report, ["a", "b"])

        self.assertEqual(sorted(rows), [(1.0, 4.0), (2.0, 5.0), (3.0, 6.0)])

    def test_excludes_a_row_if_any_column_is_null_or_zero(self):
        self._make_grid({"a": [1.0, None, 3.0], "b": [4.0, 5.0, 0.0]})

        rows = AnalysisReport._read_grid_columns(self.report, ["a", "b"])

        self.assertEqual(rows, [(1.0, 4.0)])

    def test_unsafe_column_name_is_refused(self):
        self._make_grid({"a": [1.0]})

        rows = AnalysisReport._read_grid_columns(self.report, ["a; DROP TABLE study_area_grid"])

        self.assertEqual(rows, [])

    def test_missing_gpkg_returns_empty_list(self):
        self.report.grid_gpkg_path = os.path.join(self.temp_dir, "does_not_exist.gpkg")

        self.assertEqual(AnalysisReport._read_grid_columns(self.report, ["a"]), [])


class TestReadGridColumnsWithGaps(GridFixtureTestCase):
    """_read_grid_columns_with_gaps() keeps every row, turning 0/NULL
    into NaN rather than dropping it - needed for pairwise correlation,
    where dropping any row missing ANY column can discard every row.
    """

    def test_null_and_zero_become_nan_without_dropping_the_row(self):
        self._make_grid({"a": [1.0, None, 0.0], "b": [4.0, 5.0, 6.0]})

        data = AnalysisReport._read_grid_columns_with_gaps(self.report, ["a", "b"])

        self.assertEqual(data.shape, (3, 2))
        numpy.testing.assert_array_equal(numpy.isnan(data[:, 0]), [False, True, True])
        numpy.testing.assert_array_equal(numpy.isnan(data[:, 1]), [False, False, False])

    def test_missing_gpkg_returns_empty_array_with_right_width(self):
        self.report.grid_gpkg_path = os.path.join(self.temp_dir, "does_not_exist.gpkg")

        data = AnalysisReport._read_grid_columns_with_gaps(self.report, ["a", "b"])

        self.assertEqual(data.shape, (0, 2))


class TestLimitingDimensionCounts(GridFixtureTestCase):
    """_limiting_dimension_counts() finds, for every cell scoring 2 or
    below, which dimension has the lowest value - the actionable
    "fix this first" breakdown.
    """

    def setUp(self):
        super().setUp()
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report.model_path = self.model_path
        self.report._has_used_factors.side_effect = lambda dimension: AnalysisReport._has_used_factors(
            self.report, dimension
        )

    def _write_model(self, dimensions):
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump({"dimensions": dimensions}, f)

    def _two_dimension_model(self):
        self._write_model(
            [
                {
                    "id": "alpha",
                    "name": "Alpha",
                    "factors": [{"indicators": [{"analysis_mode": "Use"}]}],
                },
                {
                    "id": "beta",
                    "name": "Beta",
                    "factors": [{"indicators": [{"analysis_mode": "Use"}]}],
                },
            ]
        )

    def test_counts_the_dimension_with_the_lowest_value_among_low_scoring_cells(self):
        self._two_dimension_model()
        # Row 1: geoe3=1 (low), alpha=1 (lowest) -> Alpha
        # Row 2: geoe3=2 (low), beta=1 (lowest) -> Beta
        # Row 3: geoe3=2 (low), alpha=1 (lowest) -> Alpha
        self._make_grid(
            {
                "geoe3": [1.0, 2.0, 2.0],
                "dim_alpha": [1.0, 3.0, 1.0],
                "dim_beta": [2.0, 1.0, 4.0],
            }
        )

        counts = AnalysisReport._limiting_dimension_counts(self.report)

        self.assertEqual(dict(counts), {"Alpha": 2, "Beta": 1})

    def test_high_scoring_cells_are_excluded(self):
        self._two_dimension_model()
        self._make_grid(
            {
                "geoe3": [4.0],  # above the <= 2 threshold
                "dim_alpha": [1.0],
                "dim_beta": [2.0],
            }
        )

        counts = AnalysisReport._limiting_dimension_counts(self.report)

        self.assertEqual(dict(counts), {"Alpha": 0, "Beta": 0})

    def test_fewer_than_two_usable_dimensions_returns_empty_list(self):
        self._write_model([{"id": "alpha", "name": "Alpha", "factors": []}])
        self._make_grid({"geoe3": [1.0], "dim_alpha": [1.0]})

        self.assertEqual(AnalysisReport._limiting_dimension_counts(self.report), [])


class TestGhslSettlementGapStats(GridFixtureTestCase):
    """_ghsl_settlement_gap_stats() compares the average score across
    the whole study area to the average within GHSL settlements only.
    """

    def test_computes_averages_and_settlement_share(self):
        self._make_grid(
            {
                "geoe3": [1.0, 2.0, 3.0, 4.0],
                "geoe3_masked": [None, None, 3.0, 4.0],
            }
        )

        stats = AnalysisReport._ghsl_settlement_gap_stats(self.report)

        self.assertAlmostEqual(stats["avg_all"], 2.5)
        self.assertAlmostEqual(stats["avg_settlement"], 3.5)
        self.assertAlmostEqual(stats["settlement_share"], 0.5)

    def test_no_settlement_cells_leaves_avg_settlement_none(self):
        self._make_grid({"geoe3": [1.0, 2.0], "geoe3_masked": [None, None]})

        stats = AnalysisReport._ghsl_settlement_gap_stats(self.report)

        self.assertIsNone(stats["avg_settlement"])
        self.assertEqual(stats["settlement_share"], 0.0)

    def test_missing_grid_returns_none(self):
        self.report.grid_gpkg_path = os.path.join(self.temp_dir, "does_not_exist.gpkg")

        self.assertIsNone(AnalysisReport._ghsl_settlement_gap_stats(self.report))


class TestOpportunitiesMaskScoreHistogram(GridFixtureTestCase):
    """_opportunities_mask_score_histogram() only counts cells flagged
    as an economic opportunity, bucketed into the five enablement
    classes.
    """

    def test_counts_only_opportunity_flagged_cells(self):
        self._make_grid(
            {
                "geoe3": [1.0, 1.0, 4.0, 2.0],
                "opportunities_mask": [1.0, 1.0, 1.0, 0.0],
            }
        )

        counts = AnalysisReport._opportunities_mask_score_histogram(self.report)

        self.assertEqual(counts, [2, 0, 0, 1, 0])

    def test_missing_grid_returns_five_zero_counts(self):
        self.report.grid_gpkg_path = os.path.join(self.temp_dir, "does_not_exist.gpkg")

        self.assertEqual(AnalysisReport._opportunities_mask_score_histogram(self.report), [0, 0, 0, 0, 0])


class TestFactorCorrelationMatrix(GridFixtureTestCase):
    """_factor_correlation_matrix() computes PAIRWISE correlation -
    factors with very different spatial coverage (the real case that
    motivated this: one factor covering every cell, another covering a
    few hundred) must not make the whole matrix come back empty.
    """

    def setUp(self):
        super().setUp()
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report.model_path = self.model_path
        self.report._has_used_indicators.side_effect = lambda factor: AnalysisReport._has_used_indicators(
            self.report, factor
        )

    def _write_model(self, factor_ids):
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dimensions": [
                        {
                            "factors": [
                                {
                                    "id": factor_id,
                                    "name": factor_id.title(),
                                    "indicators": [{"analysis_mode": "Use"}],
                                }
                                for factor_id in factor_ids
                            ]
                        }
                    ]
                },
                f,
            )

    def test_perfectly_correlated_factors_score_close_to_one(self):
        self._write_model(["a", "b"])
        self._make_grid({"fac_a": [1.0, 2.0, 3.0, 4.0, 5.0], "fac_b": [1.0, 2.0, 3.0, 4.0, 5.0]})
        AnalysisReport.MIN_CORRELATION_OVERLAP_CELLS = 3
        try:
            names, matrix = AnalysisReport._factor_correlation_matrix(self.report)
        finally:
            AnalysisReport.MIN_CORRELATION_OVERLAP_CELLS = 30

        self.assertEqual(names, ["A", "B"])
        self.assertAlmostEqual(matrix[0][1], 1.0, places=5)

    def test_a_factor_with_zero_valid_cells_is_dropped_not_left_blank(self):
        self._write_model(["a", "b", "empty"])
        self._make_grid(
            {
                "fac_a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "fac_b": [1.0, 2.0, 3.0, 4.0, 5.0],
                "fac_empty": [None, None, None, None, None],
            }
        )
        AnalysisReport.MIN_CORRELATION_OVERLAP_CELLS = 3
        try:
            result = AnalysisReport._factor_correlation_matrix(self.report)
        finally:
            AnalysisReport.MIN_CORRELATION_OVERLAP_CELLS = 30

        self.assertIsNotNone(result)
        names, _matrix = result
        self.assertEqual(names, ["A", "B"])

    def test_uneven_coverage_still_yields_a_pairwise_result(self):
        """The exact scenario that broke the all-columns-at-once
        approach: factor A covers every cell, factor B only a handful,
        and they never overlap with factor C at all - but A and B still
        overlap enough to correlate.
        """
        self._write_model(["a", "b", "c"])
        self._make_grid(
            {
                "fac_a": [1.0, 2.0, 3.0, 4.0, 5.0, 1.0, 2.0],
                "fac_b": [1.0, 2.0, 3.0, None, None, None, None],
                "fac_c": [None, None, None, None, None, 5.0, 4.0],
            }
        )
        AnalysisReport.MIN_CORRELATION_OVERLAP_CELLS = 3
        try:
            names, matrix = AnalysisReport._factor_correlation_matrix(self.report)
        finally:
            AnalysisReport.MIN_CORRELATION_OVERLAP_CELLS = 30

        a_index, b_index, c_index = names.index("A"), names.index("B"), names.index("C")
        self.assertFalse(numpy.isnan(matrix[a_index][b_index]))
        # A and C only overlap on 2 cells - below the 3-cell minimum.
        self.assertTrue(numpy.isnan(matrix[a_index][c_index]))

    def test_fewer_than_two_factors_returns_none(self):
        self._write_model(["a"])
        self._make_grid({"fac_a": [1.0, 2.0, 3.0]})

        self.assertIsNone(AnalysisReport._factor_correlation_matrix(self.report))


class TestHazardExposureTercileScores(GridFixtureTestCase):
    """_hazard_exposure_tercile_scores() bins cells by
    fac_environmental_hazards (HIGH value = LOW exposure, like every
    other factor) into terciles, and reports the average GeoE3 score
    for each.
    """

    def test_bins_into_low_medium_high_with_correct_direction(self):
        # 9 cells: hazard values spread 1..9, geoe3 deliberately
        # anti-correlated so each bin's average is distinct and checkable.
        self._make_grid(
            {
                "fac_environmental_hazards": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                "geoe3": [1, 1, 1, 2, 2, 2, 3, 3, 3],
            }
        )

        bins = dict(AnalysisReport._hazard_exposure_tercile_scores(self.report))

        # Low fac_environmental_hazards (1,2,3) = HIGH exposure, paired
        # with the lowest geoe3 values (1,1,1).
        self.assertAlmostEqual(bins["High hazard exposure"], 1.0)
        self.assertAlmostEqual(bins["Medium hazard exposure"], 2.0)
        self.assertAlmostEqual(bins["Low hazard exposure"], 3.0)

    def test_too_few_rows_returns_empty_list(self):
        self._make_grid({"fac_environmental_hazards": [1.0, 2.0], "geoe3": [1.0, 2.0]})

        self.assertEqual(AnalysisReport._hazard_exposure_tercile_scores(self.report), [])


class TestDivergingColor(unittest.TestCase):
    """_diverging_color() is white at 0, deepening to NAVY for +1 and
    off-red for -1 - the correlation heatmap's colour scale.
    """

    def test_zero_is_white(self):
        self.assertEqual(AnalysisReport._diverging_color(0.0), QColor(255, 255, 255))

    def test_positive_one_is_navy(self):
        self.assertEqual(AnalysisReport._diverging_color(1.0), QColor(0, 34, 68))

    def test_negative_one_is_off_red(self):
        self.assertEqual(AnalysisReport._diverging_color(-1.0), QColor(204, 68, 68))


class TestMakeFactorDistributionsPage(unittest.TestCase):
    """make_factor_distributions_page() only adds a page when the model
    has at least one used factor.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}
        self.report._has_used_indicators.side_effect = lambda factor: AnalysisReport._has_used_indicators(
            self.report, factor
        )

    def _write_model(self, path, factors):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"dimensions": [{"factors": factors}]}, f)

    def test_no_used_factors_skips_the_page(self):
        temp_dir = tempfile.mkdtemp(prefix="test_factor_dist_")
        try:
            model_path = os.path.join(temp_dir, "model.json")
            self._write_model(model_path, [])
            self.report.model_path = model_path

            added = AnalysisReport.make_factor_distributions_page(self.report, current_page=5)

            self.assertFalse(added)
            self.report.make_page.assert_not_called()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_used_factors_adds_the_page(self):
        temp_dir = tempfile.mkdtemp(prefix="test_factor_dist_")
        try:
            model_path = os.path.join(temp_dir, "model.json")
            self._write_model(
                model_path,
                [{"id": "a", "name": "Factor A", "indicators": [{"analysis_mode": "Use"}]}],
            )
            self.report.model_path = model_path

            added = AnalysisReport.make_factor_distributions_page(self.report, current_page=5)

            self.assertTrue(added)
            self.report.make_page.assert_called_once()
            self.assertEqual(self.report.make_page.call_args.kwargs["title"], "Factor Score Patterns")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestMakeLowScoreDriversPage(unittest.TestCase):
    """make_low_score_drivers_page() skips entirely only when BOTH its
    charts have nothing to show.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_both_empty_skips_the_page(self):
        self.report._limiting_dimension_counts.return_value = []
        self.report._opportunities_mask_score_histogram.return_value = [0, 0, 0, 0, 0]

        added = AnalysisReport.make_low_score_drivers_page(self.report, current_page=5)

        self.assertFalse(added)
        self.report.make_page.assert_not_called()

    def test_only_limiting_dimensions_still_adds_the_page(self):
        self.report._limiting_dimension_counts.return_value = [("Alpha", 3)]
        self.report._opportunities_mask_score_histogram.return_value = [0, 0, 0, 0, 0]

        added = AnalysisReport.make_low_score_drivers_page(self.report, current_page=5)

        self.assertTrue(added)
        self.report._draw_limiting_dimension_chart.assert_called_once()
        self.report._draw_opportunities_overlap_chart.assert_not_called()


class TestMakeSettlementHazardPage(unittest.TestCase):
    """make_settlement_hazard_page() skips entirely only when BOTH the
    GHSL gap stats and the hazard bins have nothing to show.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_both_empty_skips_the_page(self):
        self.report._ghsl_settlement_gap_stats.return_value = None
        self.report._hazard_exposure_tercile_scores.return_value = []

        added = AnalysisReport.make_settlement_hazard_page(self.report, current_page=5)

        self.assertFalse(added)
        self.report.make_page.assert_not_called()

    def test_only_hazard_bins_still_adds_the_page(self):
        self.report._ghsl_settlement_gap_stats.return_value = None
        self.report._hazard_exposure_tercile_scores.return_value = [("Low hazard exposure", 3.0)]

        added = AnalysisReport.make_settlement_hazard_page(self.report, current_page=5)

        self.assertTrue(added)
        self.report._draw_hazard_exposure_chart.assert_called_once()
        self.report._draw_ghsl_gap_block.assert_not_called()


class TestMakeFactorCorrelationPage(unittest.TestCase):
    """make_factor_correlation_page() only adds a page when there's a
    usable correlation matrix.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_no_matrix_skips_the_page(self):
        self.report._factor_correlation_matrix.return_value = None

        added = AnalysisReport.make_factor_correlation_page(self.report, current_page=5)

        self.assertFalse(added)
        self.report.make_page.assert_not_called()

    def test_matrix_available_adds_the_page(self):
        self.report._factor_correlation_matrix.return_value = (["A", "B"], numpy.array([[1.0, 0.5], [0.5, 1.0]]))

        added = AnalysisReport.make_factor_correlation_page(self.report, current_page=5)

        self.assertTrue(added)
        self.report._draw_correlation_heatmap.assert_called_once()


class TestCreateInsightsPages(unittest.TestCase):
    """create_insights_pages() only advances current_page for pages
    that were actually added, mirroring create_detail_pages()'s pattern.
    """

    def setUp(self):
        self.report = MagicMock()

    def test_current_page_only_advances_for_pages_actually_added(self):
        self.report.make_factor_distributions_page.return_value = True
        self.report.make_low_score_drivers_page.return_value = False
        self.report.make_settlement_hazard_page.return_value = True
        self.report.make_factor_correlation_page.return_value = False

        result = AnalysisReport.create_insights_pages(self.report, current_page=10)

        self.assertEqual(result, 12)


if __name__ == "__main__":
    unittest.main()
