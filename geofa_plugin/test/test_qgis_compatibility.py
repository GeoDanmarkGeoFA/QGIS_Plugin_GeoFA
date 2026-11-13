"""Offline compatibility checks; run with python-qgis(-ltr) and an isolated profile."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QgsApplication away from the user's real QGIS profile
os.environ.setdefault("QGIS_CUSTOM_CONFIG_PATH", tempfile.mkdtemp(prefix="geofa_qgis_profile_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt.QtWidgets import QMainWindow, QMenu

APP = QgsApplication.instance() or QgsApplication([], True)
APP.initQgis()
QCoreApplication.setOrganizationName("GeoFACompatibilityTests")
QCoreApplication.setApplicationName("offline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.gettempdir())
QSettings().setValue("locale/userLocale", "da_DK")

import geofa_plugin.geofa as geofa_module
from geofa_plugin.geofa import GeoFA
from geofa_plugin.config.settings_dialog import ConfigOptionsPage
import geofa_plugin.import_geofa as loader


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.anchor = QMenu("Help", self.window)
        self.window.menuBar().addMenu(self.anchor)
        self.options_factories = []
        self.locator_filters = []

    def registerOptionsWidgetFactory(self, factory):
        self.options_factories.append(factory)

    def unregisterOptionsWidgetFactory(self, factory):
        self.options_factories.remove(factory)

    def registerLocatorFilter(self, filter_):
        self.locator_filters.append(filter_)

    def deregisterLocatorFilter(self, filter_):
        self.locator_filters.remove(filter_)

    def mainWindow(self):
        return self.window

    def firstRightStandardMenu(self):
        return self.anchor


class CompatibilityTests(unittest.TestCase):
    def test_plugin_settings_and_locator_action(self):
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        plugin.settings.set_value("testmiljo", True)
        plugin.settings.emit_updated()
        self.assertEqual(plugin.menu.title(), "&GeoFA — TESTMILJØ")
        plugin.settings.set_value("testmiljo", False)
        plugin.settings.emit_updated()
        self.assertEqual(plugin.menu.title(), "&GeoFA")
        opened = []
        fake_services = types.SimpleNamespace(openUrl=lambda url: opened.append(url.toString()))
        with patch.object(geofa_module, "QDesktopServices", fake_services):
            plugin.manual_menu.trigger()
        self.assertEqual(opened, [geofa_module.VEJLEDNING_URL])
        page = ConfigOptionsPage(None, plugin.settings)
        page.show_password()
        page.hide_password()
        calls = []
        plugin.run_action = lambda name, path: calls.append(name)
        plugin.layer_locator_filter.triggerResult(types.SimpleNamespace(userData=0))
        self.assertEqual(calls, ["Skoledistrikter"])
        plugin.unload()
        self.assertEqual(iface.options_factories, [])
        self.assertEqual(iface.locator_filters, [])
        # After unload, a settings change must not touch the deleted menu
        plugin.settings.emit_updated()

    def test_compiled_resource_and_color_dialog_enum(self):
        from qgis.PyQt.QtGui import QIcon
        from qgis.PyQt.QtWidgets import QColorDialog
        import geofa_plugin.resources
        self.assertFalse(QIcon(":/plugins/geofa/icon_about.png").isNull())
        self.assertIsNotNone(QColorDialog.ColorDialogOption.ShowAlphaChannel)
    def test_domain_progress_when_first_table_fails(self):
        created_dialogs = []
        class Dialog:
            def __init__(self):
                self.closed = False
                created_dialogs.append(self)
            def __getattr__(self, name):
                return lambda *args: None
            def close(self):
                self.closed = True
        class Bar:
            def __init__(self, *args):
                pass
            def __getattr__(self, name):
                return lambda *args: None
        class Layer:
            def __init__(self, url, name, provider):
                assert "geofa-test.geodanmark.dk" in url
                self.layer_name = name
            def name(self):
                return self.layer_name
            def setFlags(self, flags):
                pass
            def isValid(self):
                return self.layer_name != "d_5607_ladefacilitet_type"
        class Project:
            def __init__(self):
                self.layers = {}
            def mapLayers(self):
                return self.layers
            def addMapLayer(self, layer):
                self.layers[layer.name()] = layer
        project = Project()
        messages = types.SimpleNamespace(pushMessage=lambda *args, **kwargs: None)
        iface = types.SimpleNamespace(messageBar=lambda: messages)
        with patch.object(loader, "QgsProject", types.SimpleNamespace(instance=lambda: project)), \
             patch.object(loader, "QgsVectorLayer", Layer), \
             patch.object(loader, "QProgressDialog", Dialog), \
             patch.object(loader, "QProgressBar", Bar), \
             patch.object(loader, "iface", iface):
            loader.import_geofa.d_tables(types.SimpleNamespace(testmiljo=True))
        self.assertEqual(len(project.layers), 25)
        self.assertEqual(len(created_dialogs), 1)
        self.assertTrue(created_dialogs[0].closed)


if __name__ == "__main__":
    unittest.main()
