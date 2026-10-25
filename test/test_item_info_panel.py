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
from geest.utilities import resources_path


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


def make_fake_item(role, name, description="", analysis_mode="", tooltip="", item_id="", parent=None):
    """A duck-typed stand-in for JsonTreeItem carrying only what
    ItemInfoPanel.show_item() actually reads.
    """
    item = MagicMock()
    item.role = role
    item.data.return_value = name
    item.getIcon.return_value = QIcon()
    item.getItemTooltip.return_value = tooltip
    item.parentItem = parent
    attrs = {"description": description, "analysis_mode": analysis_mode, "id": item_id}
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

    def test_indicator_with_no_description_borrows_its_parent_factors(self):
        # model.json leaves almost every indicator's own "description"
        # blank, while the parent factor's is always populated with real
        # prose - that's a far more useful fallback than the bare word
        # "Indicator" or a transient run warning/error.
        factor = make_fake_item("factor", "Women's Travel Patterns", description="Multi-stop caregiving trips.")
        item = make_fake_item("indicator", "Location of Kindergartens/Childcare", description="", parent=factor)

        self.panel.show_item(item)

        self.assertEqual(self.panel.item_meta_label.text(), "Indicator · Multi-stop caregiving trips.")

    def test_long_borrowed_description_is_truncated_not_hard_clipped(self):
        # A factor description can run well past what the card's fixed
        # height has room for - it should be cut with an ellipsis at a
        # word boundary, the same way the methodology summary is, rather
        # than silently overflowing/being hard-clipped by Qt mid-word.
        long_description = (
            "Women's Travel Patterns (WTP) refer to the unique travel behaviors of "
            "women, often involving multiple stops for household or caregiving "
            "tasks, making proximity to essential services like markets, "
            "supermarkets, childcare centers, primary schools, pharmacies, and "
            "green spaces crucial."
        )
        factor = make_fake_item("factor", "Women's Travel Patterns", description=long_description)
        item = make_fake_item("indicator", "Location of Groceries", description="", parent=factor)

        self.panel.show_item(item)

        text = self.panel.item_meta_label.text()
        self.assertLess(len(text), len("Indicator · ") + len(long_description))
        self.assertLessEqual(len(text), 210)
        self.assertTrue(text.endswith("…"))

    def test_item_with_no_description_and_no_parent_description_shows_bare_role(self):
        item = make_fake_item("dimension", "Accessibility", description="", parent=None)

        self.panel.show_item(item)

        self.assertEqual(self.panel.item_meta_label.text(), "Dimension")

    def test_run_warning_text_is_never_shown_as_the_description(self):
        # getItemTooltip() can surface a transient run warning/error (e.g.
        # "No service areas could be computed...") - that belongs on the
        # tree row's own hover tooltip (treeview.py), not in this panel,
        # where it would be mistaken for a description of the indicator.
        item = make_fake_item(
            "indicator",
            "Location of Pharmacies",
            description="",
            tooltip="Warning: No service areas could be computed for this indicator.",
        )

        self.panel.show_item(item)

        self.assertNotIn("Warning", self.panel.item_meta_label.text())
        self.assertEqual(self.panel.item_meta_label.text(), "Indicator")

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

    def test_icon_label_is_a_square_tile(self):
        self.assertEqual(self.panel.item_icon_label.objectName(), "iconTile")
        self.assertEqual(self.panel.item_icon_label.size().width(), 36)
        self.assertEqual(self.panel.item_icon_label.size().height(), 36)

    def test_mapped_id_uses_the_topic_icon_not_the_generic_role_glyph(self):
        item = make_fake_item("factor", "EPLEX Score", item_id="eplex")

        self.panel.show_item(item)

        self.assertFalse(self.panel.item_icon_label.pixmap().isNull())

    def test_unmapped_id_falls_back_to_the_generic_role_icon(self):
        generic_icon = QIcon(resources_path("resources", "icons", "factor.svg"))
        item = make_fake_item("factor", "Mystery Factor", item_id="not_a_real_id")
        item.getIcon.return_value = generic_icon

        self.panel.show_item(item)

        item.getIcon.assert_called()

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

    def test_more_link_lives_in_the_header_not_the_card(self):
        # Moved out of the card's text column so the card's fixed height
        # is spent entirely on the description, not shared with a link.
        self.assertIsNot(self.panel.more_link.parentWidget(), self.panel.card)
        self.assertFalse(self.panel.card.isAncestorOf(self.panel.more_link))

    def test_more_link_hides_while_on_the_methodology_page(self):
        self.assertTrue(self.panel.more_link.isVisible())

        self.panel.more_link.click()

        self.assertFalse(self.panel.more_link.isVisible())

    def test_more_link_reappears_after_returning_to_the_item_page(self):
        self.panel.more_link.click()

        self.panel.back_link.click()

        self.assertTrue(self.panel.more_link.isVisible())

    def test_methodology_icon_label_is_also_a_square_tile(self):
        self.assertEqual(self.panel.methodology_icon_label.objectName(), "iconTile")
        self.assertEqual(self.panel.methodology_icon_label.size().width(), 36)

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

    def test_card_has_room_for_more_than_a_couple_lines_of_description(self):
        # Grown from the original 112px cap so a borrowed factor
        # description has somewhere to go instead of being truncated
        # down to almost nothing.
        self.assertGreaterEqual(self.panel.card.maximumHeight(), 130)

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
