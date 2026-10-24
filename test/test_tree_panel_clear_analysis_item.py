# -*- coding: utf-8 -*-
"""Regression tests for TreePanel._clear_single_item_outputs() on the
Analysis item specifically.

TreePanel is a heavy QWidget that needs a loaded .ui file to construct,
so these tests call the unbound method against a lightweight MagicMock
stand-in, matching the pattern in test_tree_panel_clear_item.py.

Guards against a real production bug: "Clear Item" on the Analysis node
silently deleted nothing. item.getPaths() only knows how to build a path
for indicator/factor/dimension hierarchies and returns [] for the
analysis item itself, so item_directory resolved to the whole
working_directory instead of any of the analysis item's real output
directories (geoe3_score/, geoe3_by_population_score/, ...).
item.gridColumnName() had the same gap - the analysis item has no "id"
attribute, so it fell through to "" and reached clear_grid_column() with
a blank column name, failing with a SQLite "no such column" error
instead of clearing anything (worldbank/GeoE3 field report, 2026-10-24).
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from geest.core.json_tree_item import JsonTreeItem
from geest.gui.panels.tree_panel import TreePanel


class TestClearSingleItemOutputsForAnalysisRole(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_clear_analysis_item_")

        # One stale leftover file in each of the analysis item's real
        # output directories, matching a plausible interrupted/earlier run.
        for name in TreePanel.ANALYSIS_OUTPUT_DIRECTORIES:
            directory = os.path.join(self.temp_dir, name)
            os.makedirs(directory)
            with open(os.path.join(directory, "stale.tif"), "w") as f:
                f.write("stale")

        # study_area_grid.gpkg just needs to exist - clear_grid_column()
        # itself is mocked in the relevant tests below, so its contents
        # are never actually read.
        study_area_dir = os.path.join(self.temp_dir, "study_area")
        os.makedirs(study_area_dir)
        open(os.path.join(study_area_dir, "study_area.gpkg"), "w").close()

        self.analysis_item = JsonTreeItem(
            ["GeoE3 Score", "Configured", 1.0, {"result": "Completed successfully"}],
            role="analysis",
        )

        self.panel = MagicMock()
        self.panel.working_directory = self.temp_dir

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("geest.core.grid_column_utils.clear_grid_column")
    def test_clearing_the_analysis_item_deletes_files_in_every_output_directory(self, mock_clear_grid_column):
        # Grid-column clearing is exercised separately below - mocked out
        # here since the placeholder study_area.gpkg isn't a real
        # GeoPackage and this test only cares about file deletion.
        TreePanel._clear_single_item_outputs(self.panel, self.analysis_item)

        for name in TreePanel.ANALYSIS_OUTPUT_DIRECTORIES:
            directory = os.path.join(self.temp_dir, name)
            self.assertEqual(os.listdir(directory), [], f"{name} still has a stale file")

    @patch("geest.core.grid_column_utils.clear_grid_column")
    def test_clearing_the_analysis_item_clears_every_one_of_its_own_grid_columns(self, mock_clear_grid_column):
        TreePanel._clear_single_item_outputs(self.panel, self.analysis_item)

        cleared_columns = {call.args[1] for call in mock_clear_grid_column.call_args_list}
        self.assertEqual(cleared_columns, set(TreePanel.ANALYSIS_GRID_COLUMNS))
        self.assertNotIn("", cleared_columns)


class TestClearGridColumnRefusesBlankName(unittest.TestCase):
    """Defense in depth: even if some future caller reaches
    clear_grid_column() with a blank name again, it must refuse cleanly
    rather than reach the raw SQL UPDATE that SQLite rejects.
    """

    def test_blank_column_name_is_refused_without_crashing(self):
        from geest.core.grid_column_utils import clear_grid_column

        temp_dir = tempfile.mkdtemp(prefix="test_clear_blank_column_")
        try:
            gpkg_path = os.path.join(temp_dir, "study_area.gpkg")
            open(gpkg_path, "w").close()

            result = clear_grid_column(gpkg_path, "")

            self.assertFalse(result)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
