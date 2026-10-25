# -*- coding: utf-8 -*-
"""WorkflowFactory routes Active Transport to a different workflow class
depending on the project's analysis_scale, not just analysis_mode -
model.json's analysis_mode is shared across national/regional/local, so
the factory is the one place that can tell them apart at dispatch time.
worldbank/GeoE3#397.
"""
import unittest
from unittest.mock import MagicMock, patch

from geest.core.workflow_factory import WorkflowFactory


def _make_item(analysis_mode):
    item = MagicMock()
    item.attributes.return_value = {"analysis_mode": analysis_mode}
    item.attributesAsMarkdown.return_value = ""
    return item


class TestActiveTransportWorkflowDispatch(unittest.TestCase):
    def setUp(self):
        self.factory = WorkflowFactory()
        self.item = _make_item("use_osm_transport_polyline_per_cell")
        self.feedback = MagicMock()
        self.context = MagicMock()

    @patch("geest.core.workflow_factory.OsmTransportPolylineWeightedPerCellWorkflow")
    @patch("geest.core.workflow_factory.OsmTransportPolylinePerCellWorkflow")
    def test_national_scale_uses_the_weighted_workflow(self, mock_max_based, mock_weighted):
        self.factory.create_workflow(self.item, 100.0, "national", self.feedback, self.context)

        mock_weighted.assert_called_once()
        mock_max_based.assert_not_called()

    @patch("geest.core.workflow_factory.OsmTransportPolylineWeightedPerCellWorkflow")
    @patch("geest.core.workflow_factory.OsmTransportPolylinePerCellWorkflow")
    def test_regional_scale_keeps_the_existing_highest_score_wins_workflow(self, mock_max_based, mock_weighted):
        self.factory.create_workflow(self.item, 100.0, "regional", self.feedback, self.context)

        mock_max_based.assert_called_once()
        mock_weighted.assert_not_called()

    @patch("geest.core.workflow_factory.OsmTransportPolylineWeightedPerCellWorkflow")
    @patch("geest.core.workflow_factory.OsmTransportPolylinePerCellWorkflow")
    def test_local_scale_keeps_the_existing_highest_score_wins_workflow(self, mock_max_based, mock_weighted):
        self.factory.create_workflow(self.item, 100.0, "local", self.feedback, self.context)

        mock_max_based.assert_called_once()
        mock_weighted.assert_not_called()


if __name__ == "__main__":
    unittest.main()
