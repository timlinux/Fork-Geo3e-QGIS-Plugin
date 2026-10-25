# -*- coding: utf-8 -*-
"""Tests for the analysis report's "Methodology" and "Scoring Weights"
pages: which real-world technique produced each indicator's score, and
how much weight each dimension/factor carries, both read straight from
model.json and shown for transparency.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from geest.core.reports import methodology
from geest.core.reports.analysis_report import AnalysisReport
from geest.core.reports.methodology import (
    ANALYSIS_MODE_TECHNIQUE,
    TECHNIQUES,
    nuance_for_analysis_mode,
    technique_for_analysis_mode,
)


class TestMethodologyReferenceData(unittest.TestCase):
    """Integrity checks on the static reference data itself - a typo
    here would silently break at report-generation time rather than
    raising anywhere obvious.
    """

    def test_every_analysis_mode_maps_to_a_real_technique(self):
        for analysis_mode, technique_key in ANALYSIS_MODE_TECHNIQUE.items():
            self.assertIn(technique_key, TECHNIQUES, f"{analysis_mode!r} maps to an unknown technique")

    def test_every_technique_has_an_svg_file_on_disk(self):
        methodology_dir = os.path.join(os.path.dirname(methodology.__file__), "..", "..", "resources", "methodology")
        for technique_key, technique in TECHNIQUES.items():
            svg_path = os.path.join(methodology_dir, technique["svg"])
            self.assertTrue(os.path.exists(svg_path), f"{technique_key!r}'s svg {technique['svg']!r} is missing")

    def test_technique_for_unknown_analysis_mode_returns_none(self):
        self.assertIsNone(technique_for_analysis_mode("Do Not Use"))
        self.assertIsNone(technique_for_analysis_mode("factor_aggregation"))
        self.assertIsNone(technique_for_analysis_mode("something_added_later"))

    def test_nuance_defaults_to_empty_string(self):
        self.assertEqual(nuance_for_analysis_mode("use_point_per_cell"), "")


class TestMethodologyEntries(unittest.TestCase):
    """_methodology_entries() groups used indicators by technique,
    skipping "Do Not Use" and aggregation-role indicators, in the same
    order every other report section walks the model.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_methodology_entries_")
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report = MagicMock()
        self.report.model_path = self.model_path

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_model(self, indicators):
        model = {
            "dimensions": [
                {
                    "name": "Dim",
                    "factors": [{"name": "Fac", "indicators": indicators}],
                }
            ]
        }
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump(model, f)

    def test_groups_indicators_by_technique_and_excludes_unused(self):
        self._write_model(
            [
                {"indicator": "Clinics nearby", "analysis_mode": "use_point_per_cell"},
                {"indicator": "Cycle paths", "analysis_mode": "use_polyline_per_cell"},
                {"indicator": "Legal index", "analysis_mode": "use_index_score"},
                {"indicator": "Unused", "analysis_mode": "Do Not Use"},
            ]
        )

        entries = dict(AnalysisReport._methodology_entries(self.report))

        self.assertEqual(
            sorted(entries["feature_count"]),
            sorted([("Clinics nearby", ""), ("Cycle paths", "")]),
        )
        self.assertEqual(entries["index_score"], [("Legal index", "")])
        self.assertNotIn("Unused", [name for names in entries.values() for name, _ in names])

    def test_includes_the_nuance_for_modes_that_have_one(self):
        self._write_model([{"indicator": "Internet users", "analysis_mode": "use_index_score_with_ookla"}])

        entries = dict(AnalysisReport._methodology_entries(self.report))

        self.assertEqual(
            entries["index_score"], [("Internet users", nuance_for_analysis_mode("use_index_score_with_ookla"))]
        )
        self.assertNotEqual(entries["index_score"][0][1], "")

    def test_no_used_indicators_returns_no_techniques(self):
        self._write_model([{"indicator": "Unused", "analysis_mode": "Do Not Use"}])

        entries = AnalysisReport._methodology_entries(self.report)

        self.assertEqual(entries, [])


class TestMakeMethodologyPages(unittest.TestCase):
    """make_methodology_pages() adds one intro page plus one page per
    technique actually used - and only embeds the illustration via
    _place_picture(), never one layout item per indicator (there's no
    cell-count blowup risk here, but the pattern should stay
    consistent with the rest of this report).
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_no_used_techniques_adds_no_pages(self):
        self.report._methodology_entries.return_value = []

        result = AnalysisReport.make_methodology_pages(self.report, current_page=5)

        self.assertEqual(result, 5)
        self.report.make_page.assert_not_called()

    def test_one_page_per_technique_plus_an_intro_page(self):
        self.report._methodology_entries.return_value = [
            ("feature_count", [("Clinics nearby", "")]),
            ("index_score", [("Legal index", "")]),
        ]

        result = AnalysisReport.make_methodology_pages(self.report, current_page=5)

        self.assertEqual(result, 8)  # intro + 2 techniques
        self.assertEqual(self.report.make_page.call_count, 3)
        self.assertEqual(self.report._place_picture.call_count, 2)

    def test_indicator_nuance_is_appended_to_its_list_entry(self):
        self.report._methodology_entries.return_value = [
            ("index_score", [("Internet users", "Only scored where broadband coverage data exists.")]),
        ]

        AnalysisReport.make_methodology_pages(self.report, current_page=5)

        label_calls = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertTrue(any("Internet users" in text and "broadband" in text for text in label_calls))


class TestDimensionFactorWeightings(unittest.TestCase):
    """_dimension_factor_weightings() reads the same
    analysis_weighting/dimension_weighting attributes
    *AggregationWorkflow blends scores with, including a factor with a
    zero weight (deliberately shown, not hidden - transparency is the
    whole point of this page).
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_weightings_")
        self.model_path = os.path.join(self.temp_dir, "model.json")
        self.report = MagicMock()
        self.report.model_path = self.model_path
        self.report._has_used_factors.side_effect = lambda d: AnalysisReport._has_used_factors(self.report, d)
        self.report._has_used_indicators.side_effect = lambda f: AnalysisReport._has_used_indicators(self.report, f)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_model(self, dimensions):
        with open(self.model_path, "w", encoding="utf-8") as f:
            json.dump({"dimensions": dimensions}, f)

    def test_reads_dimension_and_factor_weights(self):
        self._write_model(
            [
                {
                    "name": "Alpha",
                    "analysis_weighting": 0.6,
                    "factors": [
                        {
                            "name": "Fac A",
                            "dimension_weighting": 1.0,
                            "indicators": [{"analysis_mode": "Use"}],
                        },
                        {
                            "name": "Fac B (unused)",
                            "dimension_weighting": 0.0,
                            "indicators": [{"analysis_mode": "Do Not Use"}],
                        },
                    ],
                }
            ]
        )

        weightings = AnalysisReport._dimension_factor_weightings(self.report)

        self.assertEqual(weightings, [("Alpha", 0.6, [("Fac A", 1.0)])])

    def test_skips_dimensions_with_no_used_factors(self):
        self._write_model(
            [
                {
                    "name": "Empty",
                    "analysis_weighting": 0.5,
                    "factors": [{"indicators": [{"analysis_mode": "Do Not Use"}]}],
                }
            ]
        )

        weightings = AnalysisReport._dimension_factor_weightings(self.report)

        self.assertEqual(weightings, [])

    def test_a_zero_weight_factor_is_still_included(self):
        self._write_model(
            [
                {
                    "name": "Alpha",
                    "analysis_weighting": 1.0,
                    "factors": [
                        {"name": "Zero", "dimension_weighting": 0.0, "indicators": [{"analysis_mode": "Use"}]},
                    ],
                }
            ]
        )

        weightings = AnalysisReport._dimension_factor_weightings(self.report)

        self.assertEqual(weightings, [("Alpha", 1.0, [("Zero", 0.0)])])


class TestMakeScoringWeightsPage(unittest.TestCase):
    """make_scoring_weights_page() shows a bare percentage on factor
    rows, not "x% of <dimension name>" - a long dimension name made
    that phrasing wrap onto a second line and crowd the row below it.
    """

    def setUp(self):
        self.report = MagicMock()
        self.report.page_descriptions = {}

    def test_no_weightings_adds_no_pages(self):
        self.report._dimension_factor_weightings.return_value = []

        result = AnalysisReport.make_scoring_weights_page(self.report, current_page=5)

        self.assertEqual(result, 5)
        self.report.make_page.assert_not_called()

    def test_factor_row_text_does_not_repeat_the_dimension_name(self):
        self.report._dimension_factor_weightings.return_value = [
            ("Place Characterization", 0.45, [("Active Transport", 0.142857)]),
        ]

        AnalysisReport.make_scoring_weights_page(self.report, current_page=5)

        label_texts = [call_args.args[0] for call_args in self.report._label.call_args_list]
        self.assertFalse(any("14% of Place Characterization" in text for text in label_texts))
        self.assertTrue(any("14% of this dimension" in text for text in label_texts))

    def test_adds_exactly_one_page_when_everything_fits(self):
        self.report._dimension_factor_weightings.return_value = [
            ("Alpha", 1.0, [("Fac A", 0.5), ("Fac B", 0.5)]),
        ]

        result = AnalysisReport.make_scoring_weights_page(self.report, current_page=5)

        self.assertEqual(result, 6)
        self.report.make_page.assert_called_once()


if __name__ == "__main__":
    unittest.main()
