# -*- coding: utf-8 -*-
"""Regression test for TreePanel's per-item workflow spinner.

TreePanel is a heavy QWidget that needs a loaded .ui file to construct,
so this calls the unbound on_workflow_started()/_stop_item_spinner()
methods directly against a lightweight MagicMock stand-in carrying a
REAL JsonTreeModel (needed since these methods call real model APIs:
model.itemIndex(), model.dataChanged), matching the pattern in
test_tree_panel_download_all_resources.py.

The spinner animates in place of the item's own role icon (column 0,
JsonTreeItem.getIcon()/set_spinner_pixmap()) rather than a separate
tree column/widget - a second column was a source of unwanted panel
resizing (worldbank/GeoE3 field report, 2026-10-24).

Guards against a real production bug: self.child_movie/self.parent_movie
were a single shared pair of attributes, not tracked per item. With two
items' start/stop events overlapping (concurrent_tasks > 1, or just two
sequential items racing), stopping one item's spinner could silently stop
a DIFFERENT, still-running item's spinner instead, freezing it on its
last rendered frame (worldbank/GeoE3 field report, 2026-10-24).
"""
import unittest
from unittest.mock import MagicMock

from geest.core.json_tree_item import JsonTreeItem
from geest.gui.panels.tree_panel import TreePanel
from geest.gui.views import JsonTreeModel


class TestWorkflowSpinnerPerItemIsolation(unittest.TestCase):
    def setUp(self):
        self.model = JsonTreeModel({"dimensions": []})
        self.dimension_a = JsonTreeItem(
            ["Dimension A", "Status", 1.0, {"id": "dim_a"}], role="dimension", parent=self.model.rootItem
        )
        self.model.rootItem.appendChild(self.dimension_a)
        self.dimension_b = JsonTreeItem(
            ["Dimension B", "Status", 1.0, {"id": "dim_b"}], role="dimension", parent=self.model.rootItem
        )
        self.model.rootItem.appendChild(self.dimension_b)

        self.panel = MagicMock()
        self.panel.model = self.model
        self.panel._item_spinners = {}

    def test_two_items_get_independent_movie_objects(self):
        TreePanel.on_workflow_started(self.panel, self.dimension_a)
        TreePanel.on_workflow_started(self.panel, self.dimension_b)

        self.assertEqual(set(self.panel._item_spinners.keys()), {self.dimension_a.guid, self.dimension_b.guid})
        (movie_a,) = self.panel._item_spinners[self.dimension_a.guid]
        (movie_b,) = self.panel._item_spinners[self.dimension_b.guid]
        self.assertIsNot(movie_a, movie_b)

    def test_each_item_shows_its_own_spinner_frame_as_its_icon(self):
        TreePanel.on_workflow_started(self.panel, self.dimension_a)
        TreePanel.on_workflow_started(self.panel, self.dimension_b)

        self.assertIsNotNone(self.dimension_a._spinner_pixmap)
        self.assertIsNotNone(self.dimension_b._spinner_pixmap)

    def test_stopping_one_items_spinner_does_not_stop_a_different_items_spinner(self):
        TreePanel.on_workflow_started(self.panel, self.dimension_a)
        TreePanel.on_workflow_started(self.panel, self.dimension_b)

        (movie_b,) = self.panel._item_spinners[self.dimension_b.guid]
        state_before = movie_b.state()

        TreePanel._stop_item_spinner(self.panel, self.dimension_a)

        # dimension_a's spinner is gone and its normal icon restored.
        self.assertNotIn(self.dimension_a.guid, self.panel._item_spinners)
        self.assertIsNone(self.dimension_a._spinner_pixmap)

        # dimension_b's spinner must be completely untouched.
        self.assertIn(self.dimension_b.guid, self.panel._item_spinners)
        (still_movie_b,) = self.panel._item_spinners[self.dimension_b.guid]
        self.assertIs(still_movie_b, movie_b)
        self.assertEqual(still_movie_b.state(), state_before)
        self.assertIsNotNone(self.dimension_b._spinner_pixmap)

    def test_stopping_an_item_twice_is_a_safe_no_op(self):
        TreePanel.on_workflow_started(self.panel, self.dimension_a)

        TreePanel._stop_item_spinner(self.panel, self.dimension_a)
        TreePanel._stop_item_spinner(self.panel, self.dimension_a)

        self.assertNotIn(self.dimension_a.guid, self.panel._item_spinners)


class TestWorkflowSpinnerAnimatesTheParentToo(unittest.TestCase):
    """An indicator with a genuinely visible parent factor: starting the
    indicator's spinner must also animate the parent's own icon, so an
    ancestor visibly shows progress while a descendant indicator runs -
    and stopping it must restore both.
    """

    def setUp(self):
        self.model = JsonTreeModel({"dimensions": []})
        self.dimension = JsonTreeItem(
            ["Accessibility", "Status", 1.0, {"id": "accessibility"}], role="dimension", parent=self.model.rootItem
        )
        self.model.rootItem.appendChild(self.dimension)
        self.factor = JsonTreeItem(
            ["Women's Travel Patterns", "Status", 1.0, {"id": "womens_travel_patterns"}],
            role="factor",
            parent=self.dimension,
        )
        self.dimension.appendChild(self.factor)
        # Two indicators - factor is NOT a hidden single-child fused row.
        self.indicator = JsonTreeItem(
            ["Location of Groceries", "Status", 1.0, {"id": "groceries_location"}],
            role="indicator",
            parent=self.factor,
        )
        self.factor.appendChild(self.indicator)
        self.sibling_indicator = JsonTreeItem(
            ["Location of Pharmacies", "Status", 1.0, {"id": "pharmacies_location"}],
            role="indicator",
            parent=self.factor,
        )
        self.factor.appendChild(self.sibling_indicator)

        self.panel = MagicMock()
        self.panel.model = self.model
        self.panel._item_spinners = {}

    def test_starting_the_indicator_also_animates_the_visible_parent_factor(self):
        TreePanel.on_workflow_started(self.panel, self.indicator)

        self.assertIsNotNone(self.indicator._spinner_pixmap)
        self.assertIsNotNone(self.factor._spinner_pixmap)
        self.assertEqual(len(self.panel._item_spinners[self.indicator.guid]), 2)

    def test_stopping_the_indicator_restores_both_its_own_and_the_parents_icon(self):
        TreePanel.on_workflow_started(self.panel, self.indicator)

        TreePanel._stop_item_spinner(self.panel, self.indicator)

        self.assertIsNone(self.indicator._spinner_pixmap)
        self.assertIsNone(self.factor._spinner_pixmap)


class TestWorkflowSpinnerHiddenSingleChildFactor(unittest.TestCase):
    """Regression test for the "Access to Public Transport" case: a factor
    with exactly one indicator is hidden from the tree (its indicator is
    promoted to appear in its place - see JsonTreeItem.get_effective_visible_children()).

    JsonTreeModel._findIndexByGuid() can locate a hidden item's own
    CHILDREN but never the hidden item's own identity, so
    self.model.itemIndex(hidden_factor) is always invalid - there's no
    separate row to animate there, only the promoted indicator's own.
    """

    def setUp(self):
        self.model = JsonTreeModel({"dimensions": []})
        self.dimension = JsonTreeItem(
            ["Accessibility", "Status", 1.0, {"id": "accessibility"}], role="dimension", parent=self.model.rootItem
        )
        self.model.rootItem.appendChild(self.dimension)
        self.factor = JsonTreeItem(
            ["Access to Public Transport", "Status", 1.0, {"id": "access_to_public_transport"}],
            role="factor",
            parent=self.dimension,
        )
        self.dimension.appendChild(self.factor)
        self.factor.set_visibility(False)  # single-child factor: hidden, its indicator is promoted
        self.indicator = JsonTreeItem(
            ["Public Transport Location", "Status", 1.0, {"id": "public_transport_location"}],
            role="indicator",
            parent=self.factor,
        )
        self.factor.appendChild(self.indicator)

        self.panel = MagicMock()
        self.panel.model = self.model
        self.panel._item_spinners = {}

    def test_hidden_factors_own_index_is_unresolvable(self):
        # Documents the underlying model behaviour on_workflow_started()
        # must tolerate, so this test fails loudly (not silently) if
        # JsonTreeModel's promotion logic ever changes.
        self.assertFalse(self.model.itemIndex(self.factor).isValid())
        self.assertTrue(self.model.itemIndex(self.indicator).isValid())

    def test_only_the_promoted_indicators_own_icon_animates(self):
        TreePanel.on_workflow_started(self.panel, self.indicator)

        self.assertIsNotNone(self.indicator._spinner_pixmap)
        # No separate row exists for the hidden factor, so there is
        # nothing meaningful to show a parent spinner on.
        self.assertIsNone(self.factor._spinner_pixmap)
        self.assertEqual(len(self.panel._item_spinners[self.indicator.guid]), 1)


class TestWorkflowSpinnerHiddenFactorIsTheWorkflowItemItself(unittest.TestCase):
    """Regression test for a factor-level aggregation job: the WorkflowJob's
    own item is the hidden single-child factor itself, not its indicator.

    TestWorkflowSpinnerHiddenSingleChildFactor above covers an indicator
    whose PARENT factor is hidden. This covers the opposite direction: a
    factor_aggregation job's item IS the hidden factor. Before this fix,
    on_workflow_started(hidden_factor) hit self.model.itemIndex(item)
    invalid at the very top and bailed out with "animation not started"
    before ever reaching any promoted-child handling - no spinner showed
    at all for a single-indicator factor's own aggregation step
    (worldbank/GeoE3 field report, 2026-10-24).
    """

    def setUp(self):
        self.model = JsonTreeModel({"dimensions": []})
        self.dimension = JsonTreeItem(
            ["Place Characterization", "Status", 1.0, {"id": "place_characterization"}],
            role="dimension",
            parent=self.model.rootItem,
        )
        self.model.rootItem.appendChild(self.dimension)
        self.factor = JsonTreeItem(
            ["Education", "Status", 1.0, {"id": "fac_education"}], role="factor", parent=self.dimension
        )
        self.dimension.appendChild(self.factor)
        self.factor.set_visibility(False)  # single-child factor: hidden, its indicator is promoted
        self.indicator = JsonTreeItem(
            ["Education", "Status", 1.0, {"id": "education"}], role="indicator", parent=self.factor
        )
        self.factor.appendChild(self.indicator)

        self.panel = MagicMock()
        self.panel.model = self.model
        self.panel._item_spinners = {}

    def test_factors_own_index_is_unresolvable(self):
        self.assertFalse(self.model.itemIndex(self.factor).isValid())

    def test_starting_a_workflow_on_the_hidden_factor_itself_animates_its_promoted_child(self):
        TreePanel.on_workflow_started(self.panel, self.factor)

        self.assertIn(self.indicator.guid, self.panel._item_spinners)
        self.assertNotIn(self.factor.guid, self.panel._item_spinners)
        self.assertIsNotNone(self.indicator._spinner_pixmap)

    def test_stopping_a_workflow_on_the_hidden_factor_itself_clears_its_promoted_childs_spinner(self):
        TreePanel.on_workflow_started(self.panel, self.factor)

        TreePanel._stop_item_spinner(self.panel, self.factor)

        self.assertNotIn(self.indicator.guid, self.panel._item_spinners)
        self.assertIsNone(self.indicator._spinner_pixmap)


if __name__ == "__main__":
    unittest.main()
