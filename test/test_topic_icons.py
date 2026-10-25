# -*- coding: utf-8 -*-
"""Tests for the dimension/factor/indicator -> topic icon lookup.

Mirrors the model.json taxonomy test pattern used elsewhere: every
dimension, factor and indicator id in the shipped model.json must
resolve to an icon file that actually exists on disk under
geest/resources/icons/topics/ - a silently-missing mapping would just
fall back to the generic tree glyph with no test failure to catch it.
"""
import json
import os
import unittest

from geest.core.topic_icons import topic_icon_filename
from geest.utilities import resources_path


def _load_model():
    model_path = resources_path("resources", "model.json")
    with open(model_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class TestTopicIconsCoverModelJson(unittest.TestCase):
    def setUp(self):
        self.model = _load_model()

    def test_analysis_level_has_an_icon(self):
        self.assertIsNotNone(topic_icon_filename("analysis", "geoe3"))

    def test_every_dimension_has_a_mapped_icon_that_exists(self):
        for dimension in self.model.get("dimensions", []):
            dimension_id = dimension.get("id")
            filename = topic_icon_filename("dimension", dimension_id)
            self.assertIsNotNone(filename, f"No icon mapped for dimension '{dimension_id}'")
            self._assert_icon_file_exists(filename)

    def test_every_factor_has_a_mapped_icon_that_exists(self):
        for dimension in self.model.get("dimensions", []):
            for factor in dimension.get("factors", []):
                factor_id = factor.get("id")
                filename = topic_icon_filename("factor", factor_id)
                self.assertIsNotNone(filename, f"No icon mapped for factor '{factor_id}'")
                self._assert_icon_file_exists(filename)

    def test_every_indicator_has_a_mapped_icon_that_exists(self):
        for dimension in self.model.get("dimensions", []):
            for factor in dimension.get("factors", []):
                for indicator in factor.get("indicators", []):
                    indicator_id = indicator.get("id")
                    filename = topic_icon_filename("indicator", indicator_id)
                    self.assertIsNotNone(filename, f"No icon mapped for indicator '{indicator_id}'")
                    self._assert_icon_file_exists(filename)

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(
            topic_icon_filename("factor", "EPLEX"),
            topic_icon_filename("factor", "eplex"),
        )

    def test_unknown_id_returns_none_rather_than_raising(self):
        self.assertIsNone(topic_icon_filename("factor", "not_a_real_factor"))
        self.assertIsNone(topic_icon_filename("indicator", None))

    def _assert_icon_file_exists(self, filename):
        path = resources_path("resources", "icons", "topics", filename)
        self.assertTrue(os.path.isfile(path), f"Missing icon file: {path}")


if __name__ == "__main__":
    unittest.main()
