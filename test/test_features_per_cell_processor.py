# -*- coding: utf-8 -*-
import os
import unittest

from qgis.core import (
    QgsFeature,
    QgsFeedback,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from utilities_for_testing import prepare_fixtures

from geest.core.algorithms.features_per_cell_processor import (
    assign_values_to_grid,
    select_grid_cells_and_assign_transport_score,
    select_grid_cells_and_assign_weighted_transport_score,
    select_grid_cells_and_count_features,
)
from geest.core.osm_downloaders import OSMDownloadType


class TestSpatialProcessing(unittest.TestCase):
    def setUp(self):
        """
        Set up mock data for the tests.
        """
        # Define working directories
        self.test_data_directory = prepare_fixtures()
        self.output_directory = os.path.join(self.test_data_directory, "output")

        # Create the output directory if it doesn't exist
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)

        self.output_path = os.path.join(self.output_directory, "test_grid.gpkg")

        # Create an in-memory grid layer
        self.grid_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Grid Layer", "memory")
        grid_provider = self.grid_layer.dataProvider()
        grid_fields = QgsFields()
        grid_fields.append(QgsField("id", QVariant.Int))
        grid_provider.addAttributes(grid_fields)
        self.grid_layer.updateFields()

        # Add grid cells (2x2 grid with simple square polygons)
        grid_features = [
            QgsFeature(),
            QgsFeature(),
            QgsFeature(),
            QgsFeature(),
        ]
        geometries = [
            QgsGeometry.fromWkt("POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"),  # Cell 1
            QgsGeometry.fromWkt("POLYGON((1 0, 1 1, 2 1, 2 0, 1 0))"),  # Cell 2
            QgsGeometry.fromWkt("POLYGON((0 1, 0 2, 1 2, 1 1, 0 1))"),  # Cell 3
            QgsGeometry.fromWkt("POLYGON((1 1, 1 2, 2 2, 2 1, 1 1))"),  # Cell 4
        ]
        for i, feature in enumerate(grid_features):
            feature.setGeometry(geometries[i])
            feature.setAttributes([i + 1])  # Set 'id' attribute
        grid_provider.addFeatures(grid_features)

        # Create an in-memory features layer
        self.features_layer = QgsVectorLayer("Point?crs=EPSG:4326", "Features Layer", "memory")
        features_provider = self.features_layer.dataProvider()
        features_provider.addAttributes([QgsField("name", QVariant.String)])
        self.features_layer.updateFields()

        # Add points that intersect the grid cells
        feature_points = [
            QgsGeometry.fromWkt("POINT(0.5 0.5)"),  # Intersects Cell 1
            QgsGeometry.fromWkt("POINT(1.5 0.5)"),  # Intersects Cell 2
            QgsGeometry.fromWkt("POINT(1.5 1.5)"),  # Intersects Cell 4
            QgsGeometry.fromWkt("POINT(0.5 1.5)"),  # Intersects Cell 3
        ]
        features = [QgsFeature() for _ in feature_points]
        for i, feature in enumerate(features):
            feature.setGeometry(feature_points[i])
            feature.setAttributes([f"Feature {i + 1}"])
        features_provider.addFeatures(features)

    def test_select_grid_cells(self):
        """
        Test the select_grid_cells function.
        """
        feedback = QgsFeedback()
        output_layer = select_grid_cells_and_count_features(
            grid_layer=self.grid_layer,
            features_layer=self.features_layer,
            output_path=self.output_path,
            feedback=feedback,
        )

        self.assertTrue(output_layer.isValid(), "Output layer is not valid.")
        self.assertEqual(
            output_layer.featureCount(),
            4,
            "Output layer should have 4 grid cells.",
        )

        # Verify that the 'intersecting_features' field is populated correctly
        output_features = {f["id"]: f["intersecting_features"] for f in output_layer.getFeatures()}
        self.assertEqual(output_features[1], 1, "Cell 1 should have 1 intersecting feature.")
        self.assertEqual(output_features[2], 1, "Cell 2 should have 1 intersecting feature.")
        self.assertEqual(output_features[3], 1, "Cell 3 should have 1 intersecting feature.")
        self.assertEqual(output_features[4], 1, "Cell 4 should have 1 intersecting feature.")

    def test_assign_values_to_grid(self):
        """
        Test the assign_values_to_grid function.
        """
        feedback = QgsFeedback()
        # First, generate the intersecting feature counts
        output_layer = select_grid_cells_and_count_features(
            grid_layer=self.grid_layer,
            features_layer=self.features_layer,
            output_path=self.output_path,
            feedback=feedback,
        )
        updated_layer = assign_values_to_grid(output_layer, feedback=feedback)

        # Verify the 'value' field
        value_map = {f["id"]: f["value"] for f in updated_layer.getFeatures()}
        self.assertEqual(value_map[1], 3, "Cell 1 should have a value of 3.")
        self.assertEqual(value_map[2], 3, "Cell 2 should have a value of 3.")
        self.assertEqual(value_map[3], 3, "Cell 3 should have a value of 3.")
        self.assertEqual(value_map[4], 3, "Cell 4 should have a value of 3.")

    def tearDown(self):
        """
        Clean up test output files.
        """
        if os.path.exists(self.output_path):
            os.remove(self.output_path)


class TestWeightedTransportScore(unittest.TestCase):
    """select_grid_cells_and_assign_weighted_transport_score() - every
    intersecting road/cycleway contributes its own score, weighted by
    that same score, instead of the single highest-scoring feature
    winning outright (select_grid_cells_and_assign_transport_score(),
    which stays unchanged). worldbank/GeoE3#397.
    """

    def setUp(self):
        self.test_data_directory = prepare_fixtures()
        self.output_directory = os.path.join(self.test_data_directory, "output")
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.output_path = os.path.join(self.output_directory, "test_weighted_grid.gpkg")

        # A single grid cell that both lines below fully cross.
        self.grid_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Grid Layer", "memory")
        grid_provider = self.grid_layer.dataProvider()
        grid_fields = QgsFields()
        grid_fields.append(QgsField("id", QVariant.Int))
        grid_provider.addAttributes(grid_fields)
        self.grid_layer.updateFields()

        cell = QgsFeature()
        cell.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"))
        cell.setAttributes([1])
        grid_provider.addFeatures([cell])

    def tearDown(self):
        if os.path.exists(self.output_path):
            os.remove(self.output_path)

    def _build_highway_lines(self, highway_types):
        """A line layer with one feature per highway type, all crossing the single cell."""
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "Roads", "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("highway", QVariant.String)])
        layer.updateFields()

        features = []
        for i, highway_type in enumerate(highway_types):
            feature = QgsFeature()
            # Slightly offset each line so they don't exactly overlap, but
            # every one still crosses the full cell.
            y = 0.1 + i * 0.05
            feature.setGeometry(QgsGeometry.fromWkt(f"LINESTRING(-0.1 {y}, 1.1 {y})"))
            feature.setAttributes([highway_type])
            features.append(feature)
        provider.addFeatures(features)
        return layer

    def test_weighted_average_favours_the_higher_scoring_feature(self):
        # "residential" scores 5, "motorway" scores 1 (HIGHWAY_CLASSIFICATION).
        # Plain average would be 3; score-weighted average is
        # (5*5 + 1*1) / (5 + 1) = 26/6 ≈ 4.33, rounding to 4 - the
        # higher-scoring feature dominates without the lower one being
        # ignored outright the way "highest score wins" (score 5) would.
        features_layer = self._build_highway_lines(["residential", "motorway"])

        output_layer = select_grid_cells_and_assign_weighted_transport_score(
            OSMDownloadType.ACTIVE_TRANSPORT,
            self.grid_layer,
            features_layer,
            self.output_path,
            analysis_scale="national",
        )

        values = {f["id"]: f["value"] for f in output_layer.getFeatures()}
        self.assertEqual(values[1], 4)

    def test_differs_from_the_highest_score_wins_result_on_the_same_data(self):
        features_layer = self._build_highway_lines(["residential", "motorway"])

        weighted_layer = select_grid_cells_and_assign_weighted_transport_score(
            OSMDownloadType.ACTIVE_TRANSPORT,
            self.grid_layer,
            features_layer,
            self.output_path,
            analysis_scale="national",
        )
        max_based_layer = select_grid_cells_and_assign_transport_score(
            OSMDownloadType.ACTIVE_TRANSPORT,
            self.grid_layer,
            features_layer,
            os.path.join(self.output_directory, "test_max_grid.gpkg"),
            analysis_scale="national",
        )

        weighted_value = {f["id"]: f["value"] for f in weighted_layer.getFeatures()}[1]
        max_value = {f["id"]: f["value"] for f in max_based_layer.getFeatures()}[1]
        self.assertEqual(max_value, 5)
        self.assertLess(weighted_value, max_value)

    def test_uniform_scores_average_to_that_same_score(self):
        features_layer = self._build_highway_lines(["residential", "residential", "residential"])

        output_layer = select_grid_cells_and_assign_weighted_transport_score(
            OSMDownloadType.ACTIVE_TRANSPORT,
            self.grid_layer,
            features_layer,
            self.output_path,
            analysis_scale="national",
        )

        values = {f["id"]: f["value"] for f in output_layer.getFeatures()}
        self.assertEqual(values[1], 5)


if __name__ == "__main__":
    unittest.main()
