# -*- coding: utf-8 -*-
import os
import unittest

from geest.core.country_pack import (
    all_sources,
    build_country_pack,
    indicator_source,
    project_level_sources,
)

TEST_DATA = os.path.join(os.path.dirname(__file__), "test_data")


class TestIndicatorSource(unittest.TestCase):
    def test_vector_widget_mode_prefers_layer_source_over_shapefile(self):
        indicator = {
            "id": "Kindergartens_Location",
            "analysis_mode": "use_multi_buffer_point",
            "multi_buffer_point_layer_source": "/path/live.gpkg|layername=points",
            "multi_buffer_point_shapefile": "/path/browsed.shp",
        }
        source = indicator_source(indicator)
        self.assertEqual(source.path, "/path/live.gpkg|layername=points")
        self.assertEqual(source.kind, "vector")
        self.assertEqual(source.layer_name, "Kindergartens_Location")

    def test_vector_widget_mode_falls_back_to_shapefile(self):
        indicator = {
            "id": "Water_Sanitation",
            "analysis_mode": "use_single_buffer_point",
            "single_buffer_point_layer_source": "",
            "single_buffer_point_shapefile": "/path/water.shp",
        }
        source = indicator_source(indicator)
        self.assertEqual(source.path, "/path/water.shp")
        self.assertEqual(source.kind, "vector")

    def test_environmental_hazards_raster_field(self):
        indicator = {
            "id": "Fire",
            "analysis_mode": "use_environmental_hazards",
            "environmental_hazards_raster": "/path/fire.tif",
        }
        source = indicator_source(indicator)
        self.assertEqual(source.path, "/path/fire.tif")
        self.assertEqual(source.kind, "raster")

    def test_csv_mode_captures_xy_fields(self):
        indicator = {
            "id": "FCV",
            "analysis_mode": "use_csv_to_point_layer",
            "csv_to_point_layer_csv_file": "/path/acled.csv",
        }
        source = indicator_source(indicator)
        self.assertEqual(source.kind, "csv")
        self.assertEqual(source.x_field, "longitude")
        self.assertEqual(source.y_field, "latitude")

    def test_manual_number_mode_has_no_source(self):
        indicator = {"id": "Workplace_Index", "analysis_mode": "use_contextual_index_score", "index_score": 95}
        self.assertIsNone(indicator_source(indicator))

    def test_unconfigured_indicator_has_no_source(self):
        indicator = {
            "id": "Active_Transport_Network",
            "analysis_mode": "use_polyline_per_cell",
            "polyline_per_cell_layer_source": "",
            "polyline_per_cell_shapefile": "",
        }
        self.assertIsNone(indicator_source(indicator))

    def test_missing_mode_or_id_has_no_source(self):
        self.assertIsNone(indicator_source({"id": "X"}))
        self.assertIsNone(indicator_source({"analysis_mode": "use_point_per_cell"}))


class TestProjectLevelSources(unittest.TestCase):
    def test_reads_road_network_population_and_masks(self):
        model = {
            "road_network_layer_path": "/path/roads.shp|layername=roads",
            "population_layer_source": "/path/pop.tif",
            "population_source": "raster",
            "point_mask_shapefile": "/path/point_mask.shp",
        }
        sources = project_level_sources(model)
        by_name = {s.layer_name: s for s in sources}
        self.assertEqual(by_name["road_network"].kind, "vector")
        self.assertEqual(by_name["population"].kind, "raster")
        self.assertEqual(by_name["point_mask"].kind, "vector")
        self.assertNotIn("polygon_mask", by_name)
        self.assertNotIn("raster_mask", by_name)
        self.assertNotIn("aggregation_boundary", by_name)

    def test_population_kind_follows_population_source_vector_case(self):
        model = {"population_shapefile": "/path/pop.shp", "population_source": "vector"}
        sources = project_level_sources(model)
        self.assertEqual(sources[0].kind, "vector")

    def test_empty_model_has_no_project_level_sources(self):
        self.assertEqual(project_level_sources({}), [])


class TestAllSources(unittest.TestCase):
    def test_combines_project_level_and_every_indicator(self):
        model = {
            "road_network_layer_path": "/path/roads.shp|layername=roads",
            "dimensions": [
                {
                    "factors": [
                        {
                            "indicators": [
                                {
                                    "id": "Fire",
                                    "analysis_mode": "use_environmental_hazards",
                                    "environmental_hazards_raster": "/path/fire.tif",
                                },
                                {
                                    "id": "Workplace_Index",
                                    "analysis_mode": "use_contextual_index_score",
                                    "index_score": 95,
                                },
                            ]
                        }
                    ]
                }
            ],
        }
        sources = all_sources(model)
        names = {s.layer_name for s in sources}
        # road_network (project-level) + Fire (indicator), Workplace_Index skipped (no file).
        self.assertEqual(names, {"road_network", "Fire"})

    def test_two_indicators_sharing_one_source_each_get_their_own_layer(self):
        shared_path = "/path/osm_points.gpkg|layername=points"
        model = {
            "dimensions": [
                {
                    "factors": [
                        {
                            "indicators": [
                                {
                                    "id": "Kindergartens_Location",
                                    "analysis_mode": "use_multi_buffer_point",
                                    "multi_buffer_point_layer_source": shared_path,
                                },
                                {
                                    "id": "Primary_School_Location",
                                    "analysis_mode": "use_multi_buffer_point",
                                    "multi_buffer_point_layer_source": shared_path,
                                },
                            ]
                        }
                    ]
                }
            ]
        }
        sources = all_sources(model)
        self.assertEqual(len(sources), 2)
        self.assertEqual({s.layer_name for s in sources}, {"Kindergartens_Location", "Primary_School_Location"})
        self.assertTrue(all(s.path == shared_path for s in sources))


class TestBuildCountryPack(unittest.TestCase):
    """End-to-end against real committed fixture data (not the user's own
    working directory data, which isn't available in CI)."""

    def setUp(self):
        self.out_path = os.path.join(TEST_DATA, "_country_pack_test_output.gpkg")
        if os.path.exists(self.out_path):
            os.remove(self.out_path)

    def tearDown(self):
        if os.path.exists(self.out_path):
            os.remove(self.out_path)

    def _model(self):
        return {
            "dimensions": [
                {
                    "factors": [
                        {
                            "indicators": [
                                {
                                    "id": "Childcare_Location",
                                    "analysis_mode": "use_point_per_cell",
                                    "point_per_cell_layer_source": os.path.join(
                                        TEST_DATA, "points", "fake_childcare.gpkg|layername=fake_childcare"
                                    ),
                                },
                                # A Float32 raster (no downcast needed).
                                {
                                    "id": "Generic_Raster",
                                    "analysis_mode": "use_nighttime_lights",
                                    "nighttime_lights_raster": os.path.join(TEST_DATA, "rasters", "raster.tif"),
                                },
                                # A Float64 raster (needs downcast to Float32 for GPKG).
                                {
                                    "id": "Fire",
                                    "analysis_mode": "use_environmental_hazards",
                                    "environmental_hazards_raster": os.path.join(
                                        TEST_DATA, "rasters", "env_fire_hazard.tif"
                                    ),
                                },
                                # No file configured - should be skipped silently, not fail the pack.
                                {
                                    "id": "Workplace_Index",
                                    "analysis_mode": "use_contextual_index_score",
                                    "index_score": 95,
                                },
                            ]
                        }
                    ]
                }
            ],
        }

    def test_writes_vector_and_raster_sources_into_one_gpkg(self):
        summary = build_country_pack(
            working_directory=TEST_DATA,
            model=self._model(),
            output_path=self.out_path,
        )
        self.assertEqual(set(summary["written"]), {"Childcare_Location", "Generic_Raster", "Fire"})
        self.assertEqual(summary["skipped"], [])
        self.assertTrue(os.path.exists(self.out_path))

    def test_a_missing_source_file_is_skipped_not_fatal(self):
        model = self._model()
        model["dimensions"][0]["factors"][0]["indicators"][0]["point_per_cell_layer_source"] = os.path.join(
            TEST_DATA, "points", "does_not_exist.gpkg|layername=x"
        )
        summary = build_country_pack(
            working_directory=TEST_DATA,
            model=model,
            output_path=self.out_path,
        )
        self.assertIn("Childcare_Location", summary["skipped"])
        self.assertIn("Generic_Raster", summary["written"])
        self.assertIn("Fire", summary["written"])

    def test_vector_then_raster_order_does_not_lose_the_vector_layer(self):
        """Regression test: GDAL's GPKG driver recreates the whole file
        unless told to append, which once silently wiped out an
        already-written vector layer the moment the next write was a
        raster (caught via a real end-to-end run against a real project)."""
        from osgeo import ogr

        summary = build_country_pack(
            working_directory=TEST_DATA,
            model=self._model(),
            output_path=self.out_path,
        )
        self.assertIn("Childcare_Location", summary["written"])

        ds = ogr.Open(self.out_path)
        layer_names = [ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())]
        ds = None
        self.assertIn("Childcare_Location", layer_names)


if __name__ == "__main__":
    unittest.main()
