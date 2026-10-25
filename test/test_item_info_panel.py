# -*- coding: utf-8 -*-
"""Tests for ItemInfoPanel - the collapsible "what is this tree item"
panel shown above the tree panel's button row, with a slide-over to
the methodology behind an indicator's score. Replaces the old
map-canvas overlay (LayerDescriptionItem, removed).
"""
import unittest
from unittest.mock import MagicMock

from qgis.PyQt.QtGui import QIcon

from geest.gui.widgets.item_info_panel import ItemInfoPanel, _truncate


class TestTruncate(unittest.TestCase):
    """_truncate() - a word-boundary character budget, not a sentence
    split: a technique's own first sentence can itself run well past
    any reasonable card-sized budget (e.g. "feature_count"'s, which
    runs to an em-dash clause before its first period).
    """

    def test_short_text_is_returned_unchanged_but_gets_a_full_stop(self):
        self.assertEqual(_truncate("Short text"), "Short text.")

    def test_text_already_ending_in_a_full_stop_is_untouched(self):
        self.assertEqual(_truncate("Already punctuated."), "Already punctuated.")

    def test_long_text_is_cut_at_a_word_boundary_with_an_ellipsis(self):
        text = "word " * 50

        result = _truncate(text, limit=20)

        self.assertLessEqual(len(result), 21)
        self.assertTrue(result.endswith("…"))
        self.assertNotIn(" …", result)

    def test_trailing_punctuation_before_the_cut_point_is_stripped(self):
        result = _truncate("One, two, three, four, five, six, seven", limit=15)

        self.assertFalse(result.endswith(",…"))


def make_fake_item(role, name, description="", analysis_mode="", tooltip=""):
    """A duck-typed stand-in for JsonTreeItem carrying only what
    ItemInfoPanel.show_item() actually reads.
    """
    item = MagicMock()
    item.role = role
    item.data.return_value = name
    item.getIcon.return_value = QIcon()
    item.getItemTooltip.return_value = tooltip
    attrs = {"description": description, "analysis_mode": analysis_mode}
    item.attribute.side_effect = lambda key, default="": attrs.get(key, default)
    return item


class TestItemInfoPanelShowItem(unittest.TestCase):
    def setUp(self):
        self.panel = ItemInfoPanel()
        # isVisible() reflects the whole ancestor chain, not just this
        # widget's own setVisible() flag - without an actual show(), every
        # child reports isVisible() == False regardless of its own state.
        self.panel.show()

    def test_clear_shows_placeholder(self):
        self.panel.clear()

        self.assertEqual(self.panel.item_heading_label.text(), "No item selected")
        self.assertFalse(self.panel.more_link.isVisible())
        self.assertEqual(self.panel.stack.currentIndex(), 0)

    def test_show_item_sets_heading_and_combined_meta_line(self):
        item = make_fake_item("dimension", "Accessibility", description="How easy it is to reach services.")

        self.panel.show_item(item)

        self.assertEqual(self.panel.item_heading_label.text(), "Accessibility")
        self.assertEqual(self.panel.item_meta_label.text(), "Dimension · How easy it is to reach services.")

    def test_falls_back_to_tooltip_when_it_adds_real_information(self):
        item = make_fake_item("factor", "Active Transport", description="", tooltip="Walking and cycling access.")

        self.panel.show_item(item)

        self.assertEqual(self.panel.item_meta_label.text(), "Factor · Walking and cycling access.")

    def test_bare_role_name_tooltip_is_not_shown_as_a_fake_description(self):
        # getItemTooltip() falls back to the literal role name ("Factor")
        # when there's nothing more specific to say - showing that next to
        # the role label too would just repeat the same word twice.
        item = make_fake_item("factor", "Active Transport", description="", tooltip="Factor")

        self.panel.show_item(item)

        self.assertEqual(self.panel.item_meta_label.text(), "Factor")

    def test_methodology_link_hidden_for_items_without_a_technique(self):
        item = make_fake_item("dimension", "Accessibility")

        self.panel.show_item(item)

        self.assertFalse(self.panel.more_link.isVisible())

    def test_methodology_link_shown_for_indicator_with_a_known_technique(self):
        item = make_fake_item("indicator", "Clinics nearby", analysis_mode="use_point_per_cell")

        self.panel.show_item(item)

        self.assertTrue(self.panel.more_link.isVisible())

    def test_methodology_link_hidden_for_unmapped_analysis_mode(self):
        item = make_fake_item("indicator", "Total score", analysis_mode="factor_aggregation")

        self.panel.show_item(item)

        self.assertFalse(self.panel.more_link.isVisible())

    def test_showing_a_new_item_resets_to_the_item_page(self):
        item = make_fake_item("indicator", "Clinics nearby", analysis_mode="use_point_per_cell")
        self.panel.show_item(item)
        self.panel._show_methodology_page()
        self.assertEqual(self.panel.stack.currentIndex(), 1)

        self.panel.show_item(item)

        self.assertEqual(self.panel.stack.currentIndex(), 0)


class TestItemInfoPanelMethodologySlideOver(unittest.TestCase):
    def setUp(self):
        self.panel = ItemInfoPanel()
        # isVisible() reflects the whole ancestor chain, not just this
        # widget's own setVisible() flag - without an actual show(), every
        # child reports isVisible() == False regardless of its own state.
        self.panel.show()
        self.item = make_fake_item("indicator", "Clinics nearby", analysis_mode="use_point_per_cell")
        self.panel.show_item(self.item)

    def test_more_link_switches_to_methodology_page(self):
        self.panel.more_link.click()

        self.assertEqual(self.panel.stack.currentIndex(), 1)
        self.assertEqual(self.panel.methodology_heading_label.text(), "Counting What's Nearby")

    def test_back_link_returns_to_item_page(self):
        self.panel.more_link.click()

        self.panel.back_link.click()

        self.assertEqual(self.panel.stack.currentIndex(), 0)

    def test_methodology_body_is_a_short_glanceable_summary(self):
        self.panel.more_link.click()

        body = self.panel.methodology_body_label.text()
        self.assertLessEqual(len(body), 135)
        self.assertTrue(body.endswith(".") or body.endswith("…"))


class TestItemInfoPanelCollapse(unittest.TestCase):
    def setUp(self):
        self.panel = ItemInfoPanel()
        # isVisible() reflects the whole ancestor chain, not just this
        # widget's own setVisible() flag - without an actual show(), every
        # child reports isVisible() == False regardless of its own state.
        self.panel.show()

    def test_starts_expanded(self):
        self.assertTrue(self.panel.card.isVisible())

    def test_toggle_collapses_the_card(self):
        self.panel.toggle_expanded()

        self.assertFalse(self.panel.card.isVisible())

    def test_toggle_twice_re_expands(self):
        self.panel.toggle_expanded()
        self.panel.toggle_expanded()

        self.assertTrue(self.panel.card.isVisible())

    def test_toggled_signal_emits_current_state(self):
        received = []
        self.panel.toggled.connect(received.append)

        self.panel.toggle_expanded()

        self.assertEqual(received, [False])


if __name__ == "__main__":
    unittest.main()
