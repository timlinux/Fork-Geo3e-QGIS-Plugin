# -*- coding: utf-8 -*-
"""Tests for SubnationalAggregationProcessingTask's factor/dimension/
total average columns - computed via spatial selection + SQL average
over study_area_grid, not raster zonal statistics (see
aggregate_factor_dimension_totals()'s docstring for why).
"""
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from osgeo import ogr
from qgis.core import QgsVectorLayer

from geest.core.algorithms.subnational_aggregation_processor import (
    SubnationalAggregationProcessingTask,
)
from geest.core.json_tree_item import JsonTreeItem


def make_item(role, item_id="", name="", attributes=None):
    attrs = dict(attributes or {})
    attrs.setdefault("id", item_id)
    attrs.setdefault("name", name)
    item = JsonTreeItem([name, "", 0, attrs], role=role)
    return item


class TestRunSkipsAveragesWhenDisabled(unittest.TestCase):
    """run() only computes the factor/dimension/total averages when the
    Subnational Score Matrix is actually going to be shown (Settings >
    GeoE3 > Analysis Options) - no point paying for a spatial join plus
    a SQL AVG() pass per zone that no report will ever read.
    """

    def _make_task(self):
        task = MagicMock()
        task.geoe3_score_folder = "/fake/geoe3_score"
        task.geoe3_by_population_folder = None
        task.geoe3_score_ghsl_masked_folder = None
        task.geoe3_score_by_population_ghsl_masked_folder = None
        return task

    @patch("geest.core.algorithms.subnational_aggregation_processor.setting")
    def test_skipped_when_setting_is_off(self, mock_setting):
        mock_setting.side_effect = lambda key, default=None: default
        task = self._make_task()

        SubnationalAggregationProcessingTask.run(task)

        task.aggregate_factor_dimension_totals.assert_not_called()

    @patch("geest.core.algorithms.subnational_aggregation_processor.setting")
    def test_computed_when_setting_is_on(self, mock_setting):
        mock_setting.side_effect = lambda key, default=None: True
        task = self._make_task()

        SubnationalAggregationProcessingTask.run(task)

        task.aggregate_factor_dimension_totals.assert_called_once()


class TestDetectNameField(unittest.TestCase):
    """_detect_name_field() picks the first String-type field - there is
    no explicit "pick the name column" step for the aggregation
    boundary, unlike the admin0 dissolve field chosen during project
    setup.

    Uses a real OGR-backed GeoPackage, not a QGIS "memory" layer -
    self.aggregation_layer is always loaded via the "ogr" provider in
    production, and the memory provider reports field type names with
    different capitalisation ("string" vs OGR's "String"), which would
    make this test pass or fail for the wrong reason.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_detect_name_field_")
        self.gpkg_path = os.path.join(self.temp_dir, "zones.gpkg")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_gpkg(self, fields):
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("zones", geom_type=ogr.wkbPolygon)
        for field_name, field_type in fields:
            layer.CreateField(ogr.FieldDefn(field_name, field_type))
        layer.CreateFeature(ogr.Feature(layer.GetLayerDefn()))
        dataset = None

    def test_picks_the_first_string_field(self):
        self._make_gpkg([("pop", ogr.OFTInteger), ("name", ogr.OFTString)])
        layer = QgsVectorLayer(f"{self.gpkg_path}|layername=zones", "zones", "ogr")

        self.assertEqual(SubnationalAggregationProcessingTask._detect_name_field(layer), "name")

    def test_no_string_field_returns_none(self):
        self._make_gpkg([("pop", ogr.OFTInteger)])
        layer = QgsVectorLayer(f"{self.gpkg_path}|layername=zones", "zones", "ogr")

        self.assertIsNone(SubnationalAggregationProcessingTask._detect_name_field(layer))


class TestFactorDimensionTotalColumns(unittest.TestCase):
    """_factor_dimension_total_columns() walks the live in-memory item
    tree (not model.json, which may lag behind this run's results) for
    every used dimension, every used factor, and the overall total.
    """

    def setUp(self):
        self.task = MagicMock()

    def _attach(self, analysis, dimension, factors_and_indicators):
        for factor_id, indicator_modes in factors_and_indicators:
            factor = make_item("factor", factor_id, factor_id.title())
            for mode in indicator_modes:
                factor.childItems.append(make_item("indicator", attributes={"analysis_mode": mode}))
            dimension.childItems.append(factor)
        analysis.childItems.append(dimension)

    def test_includes_used_dimensions_factors_and_the_total(self):
        analysis = make_item("analysis")
        dimension = make_item("dimension", "alpha", "Alpha")
        self._attach(analysis, dimension, [("fac_a", ["Use"]), ("fac_b", ["Do Not Use", "Use"])])
        self.task.item = analysis

        columns = SubnationalAggregationProcessingTask._factor_dimension_total_columns(self.task)

        self.assertEqual(
            columns,
            [
                ("Alpha", "dim_alpha"),
                ("Fac_A", "fac_fac_a"),
                ("Fac_B", "fac_fac_b"),
                ("GeoE3 Score", "geoe3"),
            ],
        )

    def test_dimension_with_no_used_factors_is_skipped(self):
        analysis = make_item("analysis")
        dimension = make_item("dimension", "alpha", "Alpha")
        self._attach(analysis, dimension, [("fac_a", ["Do Not Use"])])
        self.task.item = analysis

        columns = SubnationalAggregationProcessingTask._factor_dimension_total_columns(self.task)

        self.assertEqual(columns, [("GeoE3 Score", "geoe3")])


class TestExistingSqliteColumns(unittest.TestCase):
    """_existing_sqlite_columns() is the idempotency/legacy-backfill
    check: only columns not already present get computed. Reads via
    OGR, not a bare sqlite3 connection - see _write_zone_results()'s
    docstring for why - so the fixture here must be a real GeoPackage,
    not a plain sqlite file: OGR's GeoPackage driver won't open a
    sqlite file lacking the GPKG spec's own metadata tables.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_existing_columns_")
        self.db_path = os.path.join(self.temp_dir, "test.gpkg")
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.db_path)
        layer = dataset.CreateLayer("zones", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("zone_name", ogr.OFTString))
        dataset = None

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_returns_existing_column_names(self):
        columns = SubnationalAggregationProcessingTask._existing_sqlite_columns(self.db_path, "zones")

        self.assertEqual(columns, {"zone_name"})

    def test_missing_table_returns_empty_set(self):
        columns = SubnationalAggregationProcessingTask._existing_sqlite_columns(self.db_path, "does_not_exist")

        self.assertEqual(columns, set())


class GridFixtureTestCase(unittest.TestCase):
    """Shared helper for a real study_area_grid-like GeoPackage."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_subnational_avg_")
        self.gpkg_path = os.path.join(self.temp_dir, "study_area.gpkg")
        self.task = MagicMock()
        self.task.study_area_gpkg_path = self.gpkg_path

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_grid(self, geoe3_values):
        """One row per value, fid 1..N (matching GeoPackage's own
        1-indexed integer PK, as study_area_grid always has).
        """
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer("study_area_grid", geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("geoe3", ogr.OFTReal))
        layer_defn = layer.GetLayerDefn()
        for value in geoe3_values:
            feature = ogr.Feature(layer_defn)
            if value is not None:
                feature.SetField("geoe3", value)
            layer.CreateFeature(feature)
        dataset = None


class TestAverageGridColumnsPerZone(GridFixtureTestCase):
    """_average_grid_columns_per_zone() - regression coverage for the
    real bug found against Tunisia data: a cell shared by more than one
    zone (routine against small administrative boundaries, regardless
    of the grid's configured cell size) must contribute to EVERY zone
    it intersects, not just
    whichever zone happened to be inserted last into the mapping table.
    """

    def test_excludes_null_and_zero_before_averaging(self):
        self._make_grid([1.0, 0.0, None, 3.0])

        result = SubnationalAggregationProcessingTask._average_grid_columns_per_zone(
            self.task, {10: [1, 2, 3, 4]}, ["geoe3"]
        )

        self.assertAlmostEqual(result[10]["geoe3"], 2.0)  # (1.0 + 3.0) / 2, excluding 0 and NULL

    def test_a_cell_shared_by_two_zones_contributes_to_both(self):
        self._make_grid([1.0, 3.0, 9.0])  # fid 1, 2, 3

        # fid 2 (value 3.0) intersects both zones - a routine case, not
        # an edge case, whenever zones are smaller than a grid cell.
        result = SubnationalAggregationProcessingTask._average_grid_columns_per_zone(
            self.task, {100: [1, 2], 200: [2, 3]}, ["geoe3"]
        )

        self.assertAlmostEqual(result[100]["geoe3"], 2.0)  # (1.0 + 3.0) / 2
        self.assertAlmostEqual(result[200]["geoe3"], 6.0)  # (3.0 + 9.0) / 2

    def test_unsafe_column_name_is_refused(self):
        self._make_grid([1.0])

        result = SubnationalAggregationProcessingTask._average_grid_columns_per_zone(
            self.task, {1: [1]}, ["geoe3; DROP TABLE study_area_grid"]
        )

        self.assertEqual(result, {})


class TestWriteZoneResults(unittest.TestCase):
    """_write_zone_results() - regression coverage for the real bug
    found against Tunisia data: the aggregates GeoPackage carries RTree
    spatial-index triggers that fire on ANY UPDATE (not just the geom
    column) and reference SpatiaLite functions in their WHEN clause - a
    bare sqlite3 connection must load mod_spatialite first, or even an
    UPDATE of an unrelated column fails with "no such function:
    ST_IsEmpty".
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_write_zone_results_")
        self.gpkg_path = os.path.join(self.temp_dir, "aggregates.gpkg")
        self.table_name = "zones"
        self._make_polygon_gpkg_with_rtree()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_polygon_gpkg_with_rtree(self):
        """A real polygon GeoPackage layer - GDAL creates the same kind
        of RTree triggers on this as native:zonalstatisticsfb's own
        output, which is what reproduces the ST_IsEmpty failure mode.
        """
        driver = ogr.GetDriverByName("GPKG")
        dataset = driver.CreateDataSource(self.gpkg_path)
        layer = dataset.CreateLayer(self.table_name, geom_type=ogr.wkbPolygon, options=["SPATIAL_INDEX=YES"])
        layer_defn = layer.GetLayerDefn()
        for _ in range(3):
            layer.CreateFeature(ogr.Feature(layer_defn))
        dataset = None

    def test_adds_and_populates_zone_name_and_average_columns(self):
        SubnationalAggregationProcessingTask._write_zone_results(
            self.gpkg_path,
            self.table_name,
            missing_columns=[("Alpha", "dim_alpha")],
            averages_by_zone={1: {"dim_alpha": 3.5}, 2: {"dim_alpha": 4.0}},
            zone_names={1: "Zone One", 2: "Zone Two"},
        )

        connection = sqlite3.connect(self.gpkg_path)
        try:
            rows = connection.execute(
                f"SELECT fid, zone_name, avg_dim_alpha FROM {self.table_name} ORDER BY fid"  # nosec B608
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(rows, [(1, "Zone One", 3.5), (2, "Zone Two", 4.0), (3, None, None)])

    def test_rerunning_does_not_duplicate_or_fail_on_existing_columns(self):
        write = lambda: SubnationalAggregationProcessingTask._write_zone_results(  # noqa: E731
            self.gpkg_path,
            self.table_name,
            missing_columns=[("Alpha", "dim_alpha")],
            averages_by_zone={1: {"dim_alpha": 3.5}},
            zone_names=None,
        )

        write()
        write()  # must not raise (duplicate ALTER TABLE ADD COLUMN)

        connection = sqlite3.connect(self.gpkg_path)
        try:
            value = connection.execute(
                f"SELECT avg_dim_alpha FROM {self.table_name} WHERE fid = 1"  # nosec B608
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(value, 3.5)


if __name__ == "__main__":
    unittest.main()
