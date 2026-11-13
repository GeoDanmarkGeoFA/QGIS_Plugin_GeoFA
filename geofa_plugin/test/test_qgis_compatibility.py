"""Offline compatibility checks; run with python-qgis(-ltr) and an isolated profile."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Always a fresh, throwaway QGIS profile (settings and password store), never the user's own
TEMP_ROOT = tempfile.mkdtemp(prefix="geofa_qgis_test_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = os.path.join(TEMP_ROOT, "profile")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt.QtWidgets import QMainWindow, QMenu
from qgis.PyQt.QtXml import QDomDocument

APP = QgsApplication.instance() or QgsApplication([], True)
APP.initQgis()
QCoreApplication.setOrganizationName("GeoFACompatibilityTests")
QCoreApplication.setApplicationName("offline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.path.join(TEMP_ROOT, "settings"))
QSettings().setValue("locale/userLocale", "da_DK")

import geofa_plugin.geofa as geofa_module
from geofa_plugin.geofa import GeoFA
from geofa_plugin import credentials
from geofa_plugin.config import Settings
from geofa_plugin.config.settings_dialog import ConfigOptionsPage, PASSWORD_SAVED_PLACEHOLDER
import geofa_plugin.import_geofa as loader


def _messages():
    pushed = []
    return pushed, types.SimpleNamespace(pushMessage=lambda *args, **kwargs: pushed.append(args))


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.anchor = QMenu("Help", self.window)
        self.window.menuBar().addMenu(self.anchor)
        self.options_factories = []
        self.locator_filters = []
        self.pushed, self.message_bar = _messages()
        self.options_opened = []
        self.on_options = None  # what the user does in the Options dialog

    def messageBar(self):
        return self.message_bar

    def mapCanvas(self):
        return types.SimpleNamespace(refresh=lambda: None)

    def showOptionsDialog(self, parent=None, currentPage=""):
        self.options_opened.append(currentPage)
        if self.on_options:
            self.on_options()

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

    def test_color_dialog_enum(self):
        from qgis.PyQt.QtWidgets import QColorDialog
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


def _in_temp_root(location):
    normalise = lambda p: os.path.normcase(str(p)).replace("\\", "/")
    return bool(location) and normalise(TEMP_ROOT) in normalise(location)


def _auth_db_location():
    # qgisAuthDatabaseUri() since QGIS 3.30 (may carry a driver prefix); file path before that
    getter = getattr(QgsApplication, "qgisAuthDatabaseUri", None) or QgsApplication.qgisAuthDatabaseFilePath
    return getter()


SHARED_SOURCE = ("authcfg=geofa01 pagingEnabled='true' typename='fkg:t_5710_born_skole_dis' "
                 "url='https://geofa-test.geodanmark.dk/wfs/kom123@fkg/fkg/25832' version='auto'")
ANONYMOUS_SOURCE = ("pagingEnabled='false' typename='fkg:fkg.t_5710_born_skole_dis' "
                    "url='https://geofa-test.geodanmark.dk/ows/fkg/fkg'")


class CredentialTests(unittest.TestCase):
    """The GeoFA login lives in QGIS's password store, never in settings or layer sources."""

    @classmethod
    def setUpClass(cls):
        manager = QgsApplication.authManager()
        # Never let a test read or write the Windows password manager
        manager.setPasswordHelperEnabled(False)
        if manager.passwordHelperEnabled():
            raise unittest.SkipTest("could not switch off QGIS's OS password manager helper")
        location = _auth_db_location()
        if not _in_temp_root(location):
            raise unittest.SkipTest(f"password store is not in the throwaway profile: {location}")
        if not manager.setMasterPassword("geofa-test-master", True):
            raise unittest.SkipTest("could not set a master password on the throwaway password store")

    def setUp(self):
        credentials.remove_login()

    def stored(self):
        loaded, config = QgsApplication.authManager().loadAuthenticationConfig(
            credentials.AUTHCFG_ID, QgsAuthMethodConfig(), True)
        self.assertTrue(loaded)
        return config.method(), config.config("username"), config.config("password")

    def test_save_update_and_remove_login(self):
        self.assertTrue(credentials.save_login("kom999", "hemmelig"))
        self.assertEqual(self.stored(), ("Basic", "kom999@fkg", "hemmelig"))
        # A new username without a new password keeps the stored password
        self.assertTrue(credentials.save_login("kom998"))
        self.assertEqual(self.stored(), ("Basic", "kom998@fkg", "hemmelig"))
        credentials.remove_login()
        self.assertFalse(credentials.has_login())

    def test_old_plain_text_password_is_moved_into_store(self):
        QSettings().setValue(credentials.LEGACY_PASSWORD_KEY, "gammel")
        self.assertTrue(credentials.ensure_login("kom999"))
        self.assertEqual(QSettings().value(credentials.LEGACY_PASSWORD_KEY, ""), "")
        self.assertEqual(self.stored(), ("Basic", "kom999@fkg", "gammel"))

    def test_settings_page_keeps_password_out_of_settings(self):
        settings = Settings()
        page = ConfigOptionsPage(None, settings)
        page.username_edit.setText("kom999")
        page.password_edit.setText("hemmelig")
        page.check_box_wfst.setChecked(True)
        with patch.object(loader.import_geofa, "d_tables", lambda *args, **kwargs: None), \
             patch.object(loader.import_geofa, "run_action", lambda *args, **kwargs: None):
            page.apply()
        self.assertEqual(self.stored(), ("Basic", "kom999@fkg", "hemmelig"))
        self.assertEqual(QSettings().value(credentials.LEGACY_PASSWORD_KEY, ""), "")
        self.assertTrue(settings.value("wfst"))
        # The saved password is never shown again, but WFS-T stays available
        reopened = ConfigOptionsPage(None, settings)
        self.assertEqual(reopened.password_edit.text(), "")
        self.assertEqual(reopened.password_edit.placeholderText(), PASSWORD_SAVED_PLACEHOLDER)
        self.assertTrue(reopened.check_box_wfst.isEnabled())

    def _create_wfst_layer(self):
        captured = []

        class Layer:
            def __init__(self, uri, name, provider):
                captured.append(uri)

            def loadNamedStyle(self, *args):
                return "", True

            def isValid(self):
                return False

        pushed, message_bar = _messages()
        fake_iface = types.SimpleNamespace(messageBar=lambda: message_bar,
                                           mapCanvas=lambda: types.SimpleNamespace(refresh=lambda: None))
        fake_project = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(mapLayers=lambda: {}))
        plugin = types.SimpleNamespace(wfst=True, testmiljo=True, username="kom999")
        with patch.object(loader, "QgsVectorLayer", Layer), \
             patch.object(loader, "QgsProject", fake_project), \
             patch.object(loader, "iface", fake_iface), \
             patch.object(loader.import_geofa, "d_tables", lambda *args, **kwargs: None):
            loader.import_geofa.create_geofa_layer(plugin, "Skoledistrikter", "fkg:t_5710_born_skole_dis", TEMP_ROOT)
        return captured, pushed

    def test_wfst_layer_uses_stored_login(self):
        credentials.save_login("kom999", "hemmelig")
        captured, _ = self._create_wfst_layer()
        self.assertEqual(len(captured), 1)
        self.assertIn("authcfg=geofa01", captured[0])
        self.assertNotIn("hemmelig", captured[0])
        self.assertNotIn("password", captured[0])

    def test_wfst_layer_without_login_is_not_created(self):
        captured, pushed = self._create_wfst_layer()
        self.assertEqual(captured, [])
        self.assertEqual(len(pushed), 1)

    def test_old_project_layers_are_secured(self):
        credentials.save_login("kom999", "hemmelig")
        old = ("user='kom999@fkg' password='hemmelig' pagingEnabled='true' typename='fkg:t_5710_born_skole_dis' "
               "url='https://geofa-test.geodanmark.dk/wfs/kom999@fkg/fkg/25832' version='auto'")

        class Layer:
            def __init__(self, source):
                self.src = source

            def providerType(self):
                return "WFS"

            def source(self):
                return self.src

            def name(self):
                return "Skoledistrikter"

            def setDataSource(self, source, name, provider):
                self.src = source

        anonymous = ("pagingEnabled='false' typename='fkg:fkg.t_5710_born_skole_dis' "
                     "url='https://geofa-test.geodanmark.dk/ows/fkg/fkg'")
        layers = {"old": Layer(old), "anonymous": Layer(anonymous)}
        project = types.SimpleNamespace(mapLayers=lambda: layers, dirty=False)
        project.setDirty = lambda value: setattr(project, "dirty", value)
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.readconfig = lambda: setattr(plugin, "username", "kom999")
        with patch.object(geofa_module, "QgsProject", types.SimpleNamespace(instance=lambda: project)):
            plugin.secure_project_layers()
        self.assertIn("authcfg=geofa01", layers["old"].src)
        self.assertNotIn("hemmelig", layers["old"].src)
        self.assertEqual(layers["anonymous"].src, anonymous)
        self.assertTrue(project.dirty)
        self.assertEqual(len(iface.pushed), 1)

    def _open_shared_project(self, enter_login, document=None, shared_id="shared", shared_source=SHARED_SOURCE):
        """Open a project with a colleague's editable GeoFA layer; the user answers the login question."""
        layers = {shared_id: LoginLayer(shared_source), "anonymous": LoginLayer(ANONYMOUS_SOURCE, valid=True)}
        project = types.SimpleNamespace(mapLayers=lambda: layers, mapLayer=layers.get)
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        asked = []
        plugin.confirm_enter_login = lambda count: asked.append(count) or enter_login
        # In the Options dialog the user types a login and clicks OK
        iface.on_options = lambda: (credentials.save_login("kom999", "hemmelig"), plugin.settings.emit_updated())
        try:
            with patch.object(geofa_module, "QgsProject", types.SimpleNamespace(instance=lambda: project)):
                plugin.check_project_login(document)
                QCoreApplication.processEvents()
        finally:
            plugin.unload()
        return layers, iface, asked

    def test_shared_project_without_login_opens_settings_and_loads_layers(self):
        layers, iface, asked = self._open_shared_project(enter_login=True)
        self.assertEqual(asked, [1])
        self.assertEqual(iface.options_opened, [geofa_module.OPTIONS_PAGE_NAME])
        self.assertEqual(layers["shared"].reloads, [SHARED_SOURCE])
        self.assertTrue(layers["shared"].isValid())
        self.assertEqual(layers["anonymous"].reloads, [])
        self.assertEqual(len(iface.pushed), 1)  # "loaded with your login"

    def test_shared_project_login_declined_leaves_a_message(self):
        layers, iface, asked = self._open_shared_project(enter_login=False)
        self.assertEqual(asked, [1])
        self.assertEqual(iface.options_opened, [])
        self.assertEqual(layers["shared"].reloads, [])
        self.assertEqual(len(iface.pushed), 1)
        self.assertIn("1 GeoFA-lag", iface.pushed[0][1])

    def test_shared_project_with_stored_login_does_not_ask(self):
        credentials.save_login("kom999", "hemmelig")
        layers, iface, asked = self._open_shared_project(enter_login=True)
        self.assertEqual(asked, [])
        self.assertEqual(iface.options_opened, [])

    def test_shared_project_found_in_file_when_qgis_drops_the_layer(self):
        # When QGIS's master password prompt is cancelled, QGIS puts an empty placeholder layer
        # (new id, no source) in the project; the plugin finds the layer in the project file
        document = QDomDocument()
        document.setContent(
            "<qgis><projectlayers>"
            f"<maplayer><id>shared</id><datasource>{escape(SHARED_SOURCE)}</datasource></maplayer>"
            f"<maplayer><id>anonymous</id><datasource>{escape(ANONYMOUS_SOURCE)}</datasource></maplayer>"
            "</projectlayers></qgis>")
        layers, iface, asked = self._open_shared_project(
            enter_login=True, document=document, shared_id="placeholder", shared_source="")
        self.assertEqual(asked, [1])
        self.assertEqual(iface.options_opened, [geofa_module.OPTIONS_PAGE_NAME])
        self.assertEqual(layers["placeholder"].reloads, [])
        self.assertEqual(layers["anonymous"].reloads, [])
        self.assertEqual(len(iface.pushed), 1)
        self.assertIn("Åbn projektet igen", iface.pushed[0][1])


class LoginLayer:
    """A project layer that only loads when its login is in the password store."""

    def __init__(self, source, valid=False):
        self.src, self.valid, self.reloads = source, valid, []

    def source(self):
        return self.src

    def name(self):
        return "Skoledistrikter"

    def providerType(self):
        return "WFS"

    def isValid(self):
        return self.valid

    def setDataSource(self, source, name, provider):
        self.reloads.append(source)
        self.valid = credentials.has_login()


if __name__ == "__main__":
    unittest.main()
