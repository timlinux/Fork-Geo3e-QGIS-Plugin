# -*- coding: utf-8 -*-
"""Country Pack Import Task.

This module contains the QgsTask for reconstructing a full GeoE3
project from a country pack GeoPackage in the background.
"""

from typing import Dict, List

from qgis.core import Qgis, QgsTask

from geest.core.country_pack_import import import_country_pack
from geest.utilities import log_message


class ImportCountryPackTask(QgsTask):
    """Background task for reconstructing a project from a country pack."""

    def __init__(self, pack_path: str, working_directory: str):
        """Initialize the task.

        Args:
            pack_path: Path to the country pack GeoPackage to import.
            working_directory: An empty directory to reconstruct the
                project into.
        """
        super().__init__("Importing Country Pack", QgsTask.CanCancel)
        self.pack_path = pack_path
        self.working_directory = working_directory
        self.exception = None
        self.summary: Dict[str, List[str]] = {"imported": [], "skipped": []}

    def run(self) -> bool:
        """Reconstruct the project in the background thread.

        Returns:
            True if the project was reconstructed (even if some tables
            were skipped - see self.summary["skipped"]), False on a
            hard failure (e.g. the working directory already has a
            project, or the pack isn't a country pack).
        """
        try:
            log_message(f"Starting country pack import from '{self.pack_path}'...", tag="GeoE3", level=Qgis.Info)

            def _report_progress(done: int, total: int, table_name: str) -> None:
                if total:
                    self.setProgress(int(100 * done / total))
                if table_name:
                    log_message(f"Country pack import: extracting '{table_name}'...", tag="GeoE3")

            self.summary = import_country_pack(
                pack_path=self.pack_path,
                working_directory=self.working_directory,
                progress_callback=_report_progress,
            )

            log_message(
                f"Country pack imported: {len(self.summary['imported'])} tables reconstructed, "
                f"{len(self.summary['skipped'])} skipped -> {self.working_directory}",
                tag="GeoE3",
                level=Qgis.Info,
            )
            return True

        except Exception as e:
            self.exception = e
            log_message(f"Error importing country pack: {e}", tag="GeoE3", level=Qgis.Critical)
            return False

    def finished(self, result: bool) -> None:
        """Called when the task finishes (main thread).

        Args:
            result: True if the task succeeded, False otherwise.
        """
        if result:
            log_message(
                f"Country pack import ready: {self.working_directory} "
                f"({len(self.summary['imported'])} tables, {len(self.summary['skipped'])} skipped)",
                tag="GeoE3",
                level=Qgis.Info,
            )
        else:
            log_message("Country pack import failed.", tag="GeoE3", level=Qgis.Critical)

    def cancel(self) -> None:
        """Called when the task is cancelled."""
        log_message("Country pack import cancelled.", tag="GeoE3", level=Qgis.Warning)
        super().cancel()
