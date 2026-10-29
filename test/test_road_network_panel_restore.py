# -*- coding: utf-8 -*-
"""Regression test for RoadNetworkPanel.restore_layer_from_path().

Reproduces a reported cross-project bug: switching from one GeoE3 project
to another (within the same live QGIS session) left the newly-opened
project's stored road network path overwritten with the previous
project's one. Root cause - restore_layer_from_path() called
road_layer_combo.setLayer() without blocking signals, so the resulting
currentIndexChanged fired emit_road_layer_change(), which is connected
straight through to writing the model.json - turning a pure "sync the UI
to what's already stored" call into an unwanted write-back. If that fires
while the combo's filtered layer list is still settling after a project
switch, whichever layer is "current" at that instant (possibly still the
previous project's) gets written into the newly-opened project's model.
"""
import os
import tempfile
import unittest

from qgis.core import QgsProject, QgsVectorLayer

from geest.gui.panels.road_network_panel import RoadNetworkPanel


class TestRestoreLayerFromPathDoesNotWriteBack(unittest.TestCase):
    def setUp(self):
        QgsProject.instance().clear()
        self.tmpdir = tempfile.mkdtemp()
        self.line_path = os.path.join(self.tmpdir, "road.shp")
        layer = QgsVectorLayer("LineString?crs=EPSG:4326", "road", "memory")
        self.assertTrue(layer.isValid())
        QgsProject.instance().addMapLayer(layer)
        self.layer = layer

        self.panel = RoadNetworkPanel()
        self.emitted = []
        self.panel.road_network_layer_path_changed.connect(self.emitted.append)

    def tearDown(self):
        self.panel.deleteLater()
        QgsProject.instance().clear()

    def test_restoring_an_already_loaded_layer_does_not_emit(self):
        self.panel.restore_layer_from_path(self.layer.source())

        self.assertEqual(self.emitted, [])
        self.assertEqual(self.panel.road_layer_combo.currentLayer(), self.layer)

    def test_restore_still_updates_the_combo_selection(self):
        other_layer = QgsVectorLayer("LineString?crs=EPSG:4326", "other_road", "memory")
        QgsProject.instance().addMapLayer(other_layer)
        self.panel.road_layer_combo.setLayer(other_layer)
        self.emitted.clear()

        self.panel.restore_layer_from_path(self.layer.source())

        self.assertEqual(self.panel.road_layer_combo.currentLayer(), self.layer)
        self.assertEqual(self.emitted, [])


if __name__ == "__main__":
    unittest.main()
