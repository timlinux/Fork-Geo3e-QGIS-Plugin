#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for settings module."""

__copyright__ = "Copyright 2022, Tim Sutton"
__license__ = "GPL version 3"
__email__ = "tim@kartoza.com"
__revision__ = "$Format:%H$"

# -----------------------------------------------------------
# Copyright (C) 2022 Tim Sutton
# -----------------------------------------------------------
# Licensed under the terms of GNU GPL 3
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# ---------------------------------------------------------------------

import os
import shutil
import tempfile
import unittest
from collections import OrderedDict
from unittest.mock import MagicMock, patch

from qgis.PyQt.QtCore import QSettings

from geest.core.settings import (
    deep_convert_dict,
    delete_general_setting,
    general_setting,
    set_general_setting,
    set_setting,
    setting,
)


class TestSettings(unittest.TestCase):
    """Test suite for settings module."""

    def test_deep_convert_dict_simple(self):
        """Test deep_convert_dict with simple dict."""
        input_dict = {"key1": "value1", "key2": "value2"}
        result = deep_convert_dict(input_dict)
        self.assertEqual(result, input_dict)
        self.assertIsInstance(result, dict)

    def test_deep_convert_dict_ordered(self):
        """Test deep_convert_dict with OrderedDict."""
        input_dict = OrderedDict([("key1", "value1"), ("key2", "value2")])
        result = deep_convert_dict(input_dict)
        self.assertEqual(result, {"key1": "value1", "key2": "value2"})
        self.assertIsInstance(result, dict)
        self.assertNotIsInstance(result, OrderedDict)

    def test_deep_convert_dict_nested(self):
        """Test deep_convert_dict with nested OrderedDict."""
        input_dict = OrderedDict(
            [
                ("key1", "value1"),
                ("key2", OrderedDict([("nested1", "nestedvalue1")])),
            ]
        )
        result = deep_convert_dict(input_dict)
        self.assertEqual(result, {"key1": "value1", "key2": {"nested1": "nestedvalue1"}})
        self.assertIsInstance(result, dict)
        self.assertIsInstance(result["key2"], dict)
        self.assertNotIsInstance(result["key2"], OrderedDict)

    def test_deep_convert_dict_non_dict(self):
        """Test deep_convert_dict with non-dict value."""
        input_value = "simple string"
        result = deep_convert_dict(input_value)
        self.assertEqual(result, input_value)

    @patch("geest.core.settings.QSettings")
    def test_setting_with_default(self, mock_qsettings):
        """Test setting function with default value."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.value.side_effect = lambda key, default=None, type=None: default
        mock_qsettings.return_value = mock_settings_instance

        result = setting("test_key", default="default_value")

        self.assertEqual(result, "default_value")

    @patch("geest.core.settings.QSettings")
    @patch("geest.core.settings.QgsProject")
    def test_set_setting(self, mock_project, mock_qsettings):
        """Test set_setting function."""
        mock_settings_instance = MagicMock()
        mock_qsettings.return_value = mock_settings_instance

        mock_project_instance = MagicMock()
        mock_project.instance.return_value = mock_project_instance

        set_setting("test_key", "test_value")

        mock_settings_instance.setValue.assert_called()

    @patch("geest.core.settings.QSettings")
    @patch("geest.core.settings.QgsProject")
    def test_set_setting_syncs_to_disk(self, _mock_project, mock_qsettings):
        # A value set right before QGIS closes must not depend on the
        # QSettings object's destructor (garbage-collection timing) to
        # actually reach disk - without an explicit sync(), it can be
        # silently lost (worldbank/GeoE3 field report, 2026-10-25:
        # "Include Subnational Score Matrix" reverting to checked after
        # every restart despite being unchecked and OK'd every time).
        mock_settings_instance = MagicMock()
        mock_qsettings.return_value = mock_settings_instance

        set_setting("test_key", "test_value")

        mock_settings_instance.sync.assert_called_once()

    @patch("geest.core.settings.QSettings")
    def test_delete_setting_syncs_to_disk(self, mock_qsettings):
        mock_settings_instance = MagicMock()
        mock_qsettings.return_value = mock_settings_instance

        delete_general_setting("test_key")

        mock_settings_instance.remove.assert_called_once()
        mock_settings_instance.sync.assert_called_once()

    def test_bool_default_is_coerced_even_when_the_backend_returns_the_raw_ini_string(self):
        # general_setting()'s own PyQt/Qt binding round-trips a bool fine
        # in this environment - but a real QGIS 4 install was observed
        # returning the literal string "false" from value() when no
        # type= was passed, and every call site in geoe3_settings.py
        # (e.g. `bool(setting(key="include_subnational_score_matrix",
        # default=False))`) relies on exactly that implicit coercion.
        # bool("false") is True in Python, so an unchecked/saved
        # checkbox showed checked again on every reopen (worldbank/GeoE3
        # field report, 2026-10-25). This fake backend reproduces that
        # binding's behaviour deterministically, regardless of which Qt
        # binding actually runs this test.
        class _RawStringBackedQSettings:
            def __init__(self, stored):
                self._stored = stored

            def value(self, key, default=None, type=None):
                if key not in self._stored:
                    return default
                raw = self._stored[key]
                if type is None:
                    return raw
                if type is bool:
                    return raw.lower() == "true"
                return type(raw)

        backend = _RawStringBackedQSettings({"GeoE3/include_subnational_score_matrix": "false"})

        result = general_setting("GeoE3/include_subnational_score_matrix", default=False, qsettings=backend)

        self.assertIs(result, False)

    def test_int_default_is_also_coerced_on_a_raw_string_backed_backend(self):
        class _RawStringBackedQSettings:
            def __init__(self, stored):
                self._stored = stored

            def value(self, key, default=None, type=None):
                if key not in self._stored:
                    return default
                raw = self._stored[key]
                return raw if type is None else type(raw)

        backend = _RawStringBackedQSettings({"GeoE3/chunk_size": "25"})

        result = general_setting("GeoE3/chunk_size", default=50, qsettings=backend)

        self.assertEqual(result, 25)
        self.assertIsInstance(result, int)

    def test_explicit_expected_type_still_wins_over_the_inferred_one(self):
        mock_settings_instance = MagicMock()
        mock_settings_instance.value.side_effect = lambda key, default=None, type=None: type

        result = general_setting("test_key", default=False, expected_type=str, qsettings=mock_settings_instance)

        self.assertIs(result, str)

    def test_a_boolean_setting_survives_a_simulated_restart(self):
        # Two independent QSettings instances pointed at the same file,
        # never open at the same time - exactly how a setting toggled in
        # one QGIS session needs to be readable by the next one. Without
        # set_general_setting()'s explicit sync(), this round trip is the
        # one that silently loses the write.
        temp_dir = tempfile.mkdtemp(prefix="test_settings_restart_")
        try:
            ini_path = os.path.join(temp_dir, "settings.ini")

            session_one = QSettings(ini_path, QSettings.Format.IniFormat)
            set_general_setting("geoe3/include_subnational_score_matrix", False, qsettings=session_one)
            del session_one  # the QGIS process exiting, not a clean close

            session_two = QSettings(ini_path, QSettings.Format.IniFormat)
            result = general_setting(
                "geoe3/include_subnational_score_matrix", default=True, expected_type=bool, qsettings=session_two
            )

            self.assertFalse(result)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
