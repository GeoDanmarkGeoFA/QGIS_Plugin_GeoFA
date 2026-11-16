"""Offline compatibility checks; run with python-qgis(-ltr) and an isolated profile."""
import json
import os
import sys
import tempfile
import time
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Always a fresh, throwaway QGIS profile (settings and password store), never the user's own
TEMP_ROOT = tempfile.mkdtemp(prefix="geofa_qgis_test_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = os.path.join(TEMP_ROOT, "profile")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import (QgsApplication, QgsAuthMethodConfig, QgsDataSourceUri, QgsEditorWidgetSetup, QgsSettings,
                       QgsVectorLayer)
from qgis.gui import QgsMessageBar, QgsPasswordLineEdit
from qgis.PyQt.QtCore import QCoreApplication, QFile, QSettings, QUrl
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QGuiApplication, QIcon
from qgis.PyQt.QtWidgets import QApplication, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton
from qgis.PyQt.QtXml import QDomDocument

APP = QgsApplication.instance() or QgsApplication([], True)
APP.initQgis()
QCoreApplication.setOrganizationName("GeoFACompatibilityTests")
QCoreApplication.setApplicationName("offline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, os.path.join(TEMP_ROOT, "settings"))
QSettings().setValue("locale/userLocale", "da_DK")

import geofa_plugin.geofa as geofa_module
import geofa_plugin.settings_window as settings_window_module
from geofa_plugin.geofa import GeoFA
from geofa_plugin import credentials
from geofa_plugin.config import Settings
from geofa_plugin.settings_window import PASSWORD_SAVED_PLACEHOLDER, OptionsFactory, SettingsForm
from geofa_plugin import about, codelists, htmlfields, loader, municipalities
from geofa_plugin.catalogue import Catalogue, catalogue
from geofa_plugin.panel import LOGIN_ICON, ROLE_GROUP, ROLE_TABLE, GeoFAPanel
from geofa_plugin.settings_window import SettingsDialog


def _messages():
    pushed = []
    return pushed, types.SimpleNamespace(pushMessage=lambda *args, **kwargs: pushed.append(args))


class FakeSettingsDialog:
    """GeoFA's settings window: records that it opened, and does what the test's user does in it."""
    iface = None

    def __init__(self, settings, parent=None):
        self.settings = settings

    def exec(self):
        FakeSettingsDialog.iface.options_opened.append("settings")
        if FakeSettingsDialog.iface.on_options:
            FakeSettingsDialog.iface.on_options()
        return 1


geofa_module.SettingsDialog = FakeSettingsDialog  # the real one is tested on its own


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.anchor = QMenu("Help", self.window)
        self.window.menuBar().addMenu(self.anchor)
        self.options_factories = []
        self.locator_filters = []
        self.pushed, self.message_bar = _messages()
        self.options_opened = []
        self.on_options = None  # what the user does in the settings window
        FakeSettingsDialog.iface = self

    def messageBar(self):
        return self.message_bar

    def mapCanvas(self):
        return types.SimpleNamespace(refresh=lambda: None, stopRendering=lambda: None)

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

    def addDockWidget(self, area, widget):
        self.window.addDockWidget(area, widget)

    def removeDockWidget(self, widget):
        self.window.removeDockWidget(widget)


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
        form = SettingsForm(plugin.settings)
        self.assertIsInstance(form.password_edit, QgsPasswordLineEdit)  # QGIS's own field, with the eye
        # The GeoFA page in QGIS's Options, with the same form
        self.assertEqual(len(iface.options_factories), 1)
        page = iface.options_factories[0].createWidget(None)
        self.assertEqual(page.objectName(), "geofaOptions")
        self.assertFalse(iface.options_factories[0].icon().isNull())  # the GeoFA "G"
        self.assertEqual(page.form.municipality_box.count(), 1 + 99)  # "Hele landet" and the municipalities
        # Both places name Geopartner, with a link that opens in the browser
        for window in (page, SettingsDialog(plugin.settings)):
            credit = window.findChild(QLabel, "developer_credit")
            self.assertIn("href='https://geopartner.dk'", credit.text())
            self.assertTrue(credit.openExternalLinks())
        calls = []
        plugin.add_tables = lambda tables: calls.append(tables)
        plugin.layer_locator_filter.triggerResult(types.SimpleNamespace(userData=0))
        self.assertEqual(calls, [[catalogue().groups[0][1][0].table]])
        # The locator bar finds layers by theme code too
        self.assertEqual([l["title"] for l in plugin.layer_locator_filter.data.get_matching_layers("5800")],
                         ["Friluftsliv faciliteter, punkter (5800) (Sport, fritid og friluftsliv, GeoFA)"])
        plugin.unload()
        self.assertEqual(iface.options_factories, [])
        self.assertEqual(iface.locator_filters, [])
        # After unload, a settings change must not touch the deleted menu
        plugin.settings.emit_updated()

    def test_color_dialog_enum(self):
        from qgis.PyQt.QtWidgets import QColorDialog
        self.assertIsNotNone(QColorDialog.ColorDialogOption.ShowAlphaChannel)


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

    def test_settings_window_stores_the_login_and_applies_it(self):
        settings = Settings()
        updates = []
        settings.settings_updated.connect(lambda: updates.append(True))
        dialog = SettingsDialog(settings)
        self.assertEqual(dialog.windowTitle(), "GeoFA – indstillinger")
        self.assertIsInstance(dialog.form.password_edit, QgsPasswordLineEdit)
        dialog.form.username_edit.setText("kom997")
        dialog.form.password_edit.setText("hemmelig")
        dialog.form.check_box_wfst.setChecked(True)
        dialog.accept()
        self.assertEqual(self.stored(), ("Basic", "kom997@fkg", "hemmelig"))
        self.assertTrue(settings.value("wfst"))
        self.assertEqual(updates, [True])
        # Cancel changes nothing
        dialog = SettingsDialog(settings)
        dialog.form.username_edit.setText("kom996")
        dialog.reject()
        self.assertEqual(settings.value("username"), "kom997")
        # The municipality filter
        dialog = SettingsDialog(settings)
        box = dialog.form.municipality_box
        box.setCurrentIndex(box.findData("0751"))
        dialog.accept()
        try:
            self.assertEqual(settings.value("kommune"), "0751")
            self.assertEqual(loader.Mode.from_settings(settings).kommune, "0751")
            reopened = SettingsDialog(settings)
            self.assertEqual(reopened.form.municipality_box.currentData(), "0751")
        finally:
            settings.set_value("kommune", "")

    def test_without_a_login_the_plugin_is_a_viewer(self):
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        plugin.settings.set_value("wfst", True)  # left over: without a login it can't apply
        plugin.settings.emit_updated()
        try:
            # The panel's menu item has the GeoFA "G", as the Options page
            g = QIcon(settings_window_module.ICON).pixmap(16, 16).toImage()
            self.assertEqual(plugin.panel_action.icon().pixmap(16, 16).toImage(), g)
            self.assertFalse(plugin.mode.edit)
            self.assertFalse(plugin.edit_action.isVisible())
            self.assertTrue(plugin.panel.edit_button.isHidden())
            credentials.save_login("kom999", "hemmelig")
            plugin.settings.emit_updated()
            self.assertTrue(plugin.mode.edit)
            self.assertTrue(plugin.edit_action.isVisible())
            self.assertFalse(plugin.panel.edit_button.isHidden())
        finally:
            plugin.settings.set_value("wfst", False)
            credentials.remove_login()
            plugin.settings.emit_updated()
            plugin.unload()

    def test_removing_the_login_in_qgis_makes_the_plugin_read_only_at_once(self):
        credentials.save_login("kom999", "hemmelig")
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        plugin.settings.set_value("wfst", True)
        plugin.settings.emit_updated()
        try:
            self.assertTrue(plugin.mode.edit)
            # As the user does under Indstillinger › Godkendelse (no settings change in the plugin),
            # then closes the dialog: QGIS's main window gets focus back
            QgsApplication.authManager().removeAuthenticationConfig(credentials.AUTHCFG_ID)
            QGuiApplication.instance().focusWindowChanged.emit(None)
            self.assertFalse(plugin.mode.edit)
            self.assertFalse(plugin.edit_action.isVisible())
            self.assertTrue(plugin.panel.edit_button.isHidden())
            self.assertIn("fjernet", iface.pushed[-1][1])
            # And a login stored again brings editing back
            credentials.save_login("kom999", "hemmelig")
            QGuiApplication.instance().focusWindowChanged.emit(None)
            self.assertTrue(plugin.mode.edit)
            self.assertTrue(plugin.edit_action.isVisible())
        finally:
            plugin.settings.set_value("wfst", False)
            credentials.remove_login()
            plugin.settings.emit_updated()
            plugin.unload()

    def test_settings_applied_while_layers_are_swapped_wait_for_them(self):
        # Closing QGIS's Options after removing the login: the GeoFA page applies the settings, and
        # while the layers load (Qt's event loop) the main window gets focus and the login check follows
        credentials.save_login("kom999", "hemmelig")
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        plugin.settings.set_value("wfst", True)
        plugin.settings.emit_updated()
        depth, swaps = [0], []

        def repoint(mode, project=None):
            depth[0] += 1
            swaps.append((mode.edit, depth[0]))
            if len(swaps) == 1:
                QgsApplication.authManager().removeAuthenticationConfig(credentials.AUTHCFG_ID)
                QGuiApplication.instance().focusWindowChanged.emit(None)
            depth[0] -= 1
            return 0, [], []

        try:
            with patch.object(loader, "repoint", repoint):
                plugin.settings.set_value("kommune", "0751")
                plugin.settings.emit_updated()
            # The second swap (read-only, as the login is gone) came after the first, not inside it
            self.assertEqual(swaps, [(True, 1), (False, 1)])
            self.assertFalse(plugin.mode.edit)
            self.assertEqual(plugin.mode.kommune, "0751")
        finally:
            plugin.settings.set_value("kommune", "")
            plugin.settings.set_value("wfst", False)
            credentials.remove_login()
            plugin.settings.emit_updated()
            plugin.unload()

    def test_login_form_keeps_password_out_of_settings(self):
        settings = Settings()
        page = SettingsForm(settings)
        page.username_edit.setText("kom999")
        page.password_edit.setText("hemmelig")
        page.check_box_wfst.setChecked(True)
        page.apply()
        self.assertEqual(self.stored(), ("Basic", "kom999@fkg", "hemmelig"))
        self.assertEqual(QSettings().value(credentials.LEGACY_PASSWORD_KEY, ""), "")
        self.assertTrue(settings.value("wfst"))
        # The saved password is never shown again, but WFS-T stays available
        reopened = SettingsForm(settings)
        self.assertEqual(reopened.password_edit.text(), "")
        self.assertEqual(reopened.password_edit.placeholderText(), PASSWORD_SAVED_PLACEHOLDER)
        self.assertTrue(reopened.check_box_wfst.isEnabled())

    def _create_wfst_layer(self):
        captured = []

        class Layer:
            def __init__(self, uri, name, provider):
                captured.append(uri)

            def isValid(self):
                return False

        pushed, message_bar = _messages()
        project = types.SimpleNamespace(mapLayers=lambda: {}, customVariables=lambda: {})
        mode = loader.Mode(edit=True, test=True, username="kom999")
        with patch.object(loader, "QgsVectorLayer", Layer):
            loader.add_dataset(catalogue().get("t_5710_born_skole_dis"), mode, message_bar, project)
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
        self.assertEqual(iface.options_opened, ["settings"])
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
        self.assertEqual(iface.options_opened, ["settings"])
        self.assertEqual(layers["placeholder"].reloads, [])
        self.assertEqual(layers["anonymous"].reloads, [])
        self.assertEqual(len(iface.pushed), 1)
        self.assertIn("Åbn projektet igen", iface.pushed[0][1])


class FakeLayer:
    """A GeoFA layer in a project, as the loader sees it."""

    def __init__(self, source, name="Skoledistrikter (5710)", table=None, editing=False):
        self.src, self.layer_name, self.editing = source, name, editing
        self.properties = {loader.TABLE_PROPERTY: table} if table else {}

    def customProperty(self, key):
        return self.properties.get(key)

    def setCustomProperty(self, key, value):
        self.properties[key] = value

    def providerType(self):
        return "WFS"

    def source(self):
        return self.src

    def name(self):
        return self.layer_name

    def isEditable(self):
        return self.editing

    def setDataSource(self, source, name, provider):
        self.src, self.layer_name = source, name

    def setName(self, name):
        self.layer_name = name

    def id(self):
        return getattr(self, "layer_id", self.layer_name)


class FakeProject(QObject):
    """A project with layers, and the signals the panel follows."""
    layersAdded = pyqtSignal(list)
    layersRemoved = pyqtSignal(list)

    def __init__(self, layers):
        super().__init__()
        self.layers, self.removed = layers, []
        for layer_id, layer in layers.items():
            layer.layer_id = layer_id

    def mapLayers(self):
        return self.layers

    def customVariables(self):
        return {}

    def removeMapLayers(self, ids):
        self.removed.append(list(ids))


def _replace_in_place(project, layer, source, name):
    """Stands in for loader.replace_layer, which needs a real WFS layer."""
    layer.setDataSource(source, name, "WFS")
    return layer


READ = loader.Mode(edit=False, test=False, username="kom999")
EDIT = loader.Mode(edit=True, test=False, username="kom999")
TEST_READ = loader.Mode(edit=False, test=True, username="kom999")
EDIT_TEST = loader.Mode(edit=True, test=True, username="kom999")


class CatalogueTests(unittest.TestCase):
    def test_catalogue_has_every_spec_dataset_and_its_style(self):
        cat = Catalogue()
        self.assertEqual(len(cat.groups), 13)
        self.assertEqual(len(cat.datasets()), 80)
        for dataset in cat.datasets():
            self.assertTrue(os.path.exists(dataset.style_path), dataset.style_path)
        # Old table names (from earlier plugin versions) find the renamed tables
        self.assertEqual(cat.get("t_5609_cykelknudepunktsstraekninger").table, "t_5609_cykelkrydspunktsstraekninger")

    def test_sources_hold_no_password(self):
        read = loader.layer_source("t_5710_born_skole_dis", READ)
        self.assertIn("url='https://geofa.geodanmark.dk/ows/fkg/fkg'", read)
        self.assertIn("typename='fkg:fkg.t_5710_born_skole_dis'", read)
        self.assertNotIn("authcfg", read)
        edit = loader.layer_source("t_5800_fac_pkt", EDIT_TEST)
        self.assertIn("url='https://geofa-test.geodanmark.dk/wfs/kom999@fkg/fkg/25832'", edit)
        self.assertIn("typename='fkg:t_5800_fac_pkt'", edit)
        self.assertIn("authcfg=geofa01", edit)
        self.assertNotIn("password", edit)

    def test_read_only_layers_with_photos_come_from_the_photo_link_version(self):
        def parts(table, mode):
            uri = QgsDataSourceUri(loader.layer_source(table, mode))
            return uri.param("url"), uri.param("typename")

        self.assertEqual(parts("t_5800_fac_pkt", READ), ("https://geofa.geodanmark.dk/ows/fkg/fkg_foto_gpx_link",
                                                          "fkg:fkg_foto_gpx_link.t_5800_fac_pkt"))
        # Editing uses the normal, editable table
        self.assertEqual(parts("t_5800_fac_pkt", EDIT)[1], "fkg:t_5800_fac_pkt")
        # Only where GeoFA has a photo-link version: 5607 has none in the test environment
        self.assertEqual(parts("t_5607_ladefacilitet", READ)[1], "fkg:fkg_foto_gpx_link.t_5607_ladefacilitet")
        self.assertEqual(parts("t_5607_ladefacilitet", TEST_READ)[1], "fkg:fkg.t_5607_ladefacilitet")
        layer = FakeLayer(loader.layer_source("t_5800_fac_pkt", READ))
        self.assertEqual(loader.table_of(layer), "t_5800_fac_pkt")

    def test_municipality_filter_is_sent_with_every_source_and_fits_a_request(self):
        aarhus = loader.Mode(edit=False, test=False, username="kom999", kommune="0751")
        source = QgsDataSourceUri(loader.layer_source("t_5710_born_skole_dis", aarhus))
        self.assertIn("<ogc:Intersects><ogc:PropertyName>geometri</ogc:PropertyName>", source.param("filter"))
        # Whole metres: "6.2227e+06" would lose precision, and its "+" becomes a space in the request
        self.assertNotIn("e+", source.param("filter"))
        # QGIS would combine the filter with the map view box at more than twice its length
        self.assertFalse(source.hasParam("restrictToRequestBBOX"))
        self.assertEqual(QgsDataSourceUri(loader.layer_source("t_5710_born_skole_dis", READ)).param("filter"), "")
        self.assertEqual(municipalities.display_name("0751"), "Aarhus Kommune")
        self.assertEqual(municipalities.display_name("0411"), "Christiansø")
        choices = municipalities.choices()
        self.assertEqual(len(choices), 99)
        self.assertEqual([name for _, name in choices], sorted(name for _, name in choices))
        self.assertIsNone(municipalities.intersects_filter("9999"))
        # Swapping a layer keeps the user's own filter, but not this one (it comes with the new source)
        self.assertTrue(municipalities.is_municipality_filter(municipalities.intersects_filter("0101")))
        self.assertFalse(municipalities.is_municipality_filter('"statuskode" = 3'))
        self.assertFalse(municipalities.is_municipality_filter(""))
        # GeoFA's server turns down request lines over ~8,190 characters, and QGIS adds to the filter
        longest = max(len(urllib.parse.quote(municipalities.intersects_filter(code), safe=""))
                      for code, _ in choices)
        self.assertLessEqual(longest, 5500)

    def test_changing_the_municipality_filters_the_layers_already_added(self):
        layer = FakeLayer(loader.layer_source("t_5710_born_skole_dis", READ), table="t_5710_born_skole_dis")
        project = types.SimpleNamespace(mapLayers=lambda: {"layer": layer})
        aarhus = loader.Mode(edit=False, test=False, username="kom999", kommune="0751")
        with patch.object(loader, "replace_layer", _replace_in_place):
            self.assertEqual(loader.repoint(aarhus, project)[0], 1)
            self.assertIn("Intersects", QgsDataSourceUri(layer.src).param("filter"))
            self.assertEqual(loader.repoint(aarhus, project)[0], 0)  # already filtered
            self.assertEqual(loader.repoint(READ, project)[0], 1)
        self.assertEqual(QgsDataSourceUri(layer.src).param("filter"), "")

    def test_a_swap_leaves_alone_layers_swapped_while_another_loaded(self):
        # Loading a WFS layer runs Qt's event loop, where the plugin may swap the layers itself
        layers = {name: FakeLayer(loader.layer_source(table, EDIT), name=name, table=table)
                  for name, table in (("a", "t_5710_born_skole_dis"), ("b", "t_5800_fac_pkt"))}
        project = types.SimpleNamespace(mapLayers=lambda: layers)
        nested = []

        def replace(project, layer, source, name):
            if not nested:  # "a" loads; meanwhile the same swap runs again and swaps both
                nested.append("started")
                nested.append(loader.repoint(READ, project))
                return None  # as replace_layer does when the old layer left the project meanwhile
            new = FakeLayer(source, name=name, table=layer.customProperty(loader.TABLE_PROPERTY))
            layers[name] = new  # the new layer takes the old one's place
            return new

        with patch.object(loader, "replace_layer", replace):
            self.assertEqual(loader.repoint(READ, project), (0, [], []))  # nothing failed, nothing swapped twice
        self.assertEqual(nested[1], (2, [], []))
        for name, table in (("a", "t_5710_born_skole_dis"), ("b", "t_5800_fac_pkt")):
            self.assertEqual(layers[name].src, loader.layer_source(table, READ))

    def test_a_layer_gone_while_its_replacement_loaded_is_not_touched(self):
        old = FakeLayer(loader.layer_source("t_5710_born_skole_dis", EDIT), table="t_5710_born_skole_dis")
        layers = {"old": old}
        project = types.SimpleNamespace(mapLayers=lambda: layers)

        class Loading:
            def __init__(self, source, name, provider):
                layers.pop("old")  # swapped or removed in Qt's event loop while this one loaded

            def isValid(self):
                return True

        with patch.object(loader, "QgsVectorLayer", Loading):
            # The fake old layer has no style to copy: touching it would raise
            self.assertIsNone(loader.replace_layer(project, old, loader.layer_source("t_5710_born_skole_dis", READ),
                                                   old.name()))

    def test_layers_stay_in_their_environment_and_only_the_chosen_one_is_editable(self):
        prod = FakeLayer(loader.layer_source("t_5710_born_skole_dis", READ), table="t_5710_born_skole_dis")
        # A layer from an older plugin version, recognised by its source
        old = FakeLayer("pagingEnabled='false' typename='fkg:fkg.t_5800_fac_pkt' "
                        "url='https://geofa.geodanmark.dk/ows/fkg/fkg'", name="Friluftsliv faciliteter, punkter")
        test = FakeLayer(loader.layer_source("t_5802_fac_li", TEST_READ), name="Faciliteter, linjer (5802) [TEST]",
                         table="t_5802_fac_li")
        busy = FakeLayer(loader.layer_source("t_5801_fac_fl", TEST_READ), name="Faciliteter, flader (5801) [TEST]",
                         table="t_5801_fac_fl", editing=True)
        other = FakeLayer("url='https://example.com/wfs' typename='x:y'", name="Andet lag")
        layers = {"prod": prod, "old": old, "test": test, "busy": busy, "other": other}
        project = types.SimpleNamespace(mapLayers=lambda: layers)
        names = {key: layer.name() for key, layer in layers.items()}

        def repoint(mode):
            with patch.object(loader, "replace_layer", _replace_in_place):
                return loader.repoint(mode, project)

        # Switching to test, read-only: production layers stay on production
        repoint(TEST_READ)
        self.assertEqual(prod.src, loader.layer_source("t_5710_born_skole_dis", READ))
        self.assertIn("url='https://geofa.geodanmark.dk/", old.src)  # production (its photo-link version)
        self.assertEqual(test.src, loader.layer_source("t_5802_fac_li", TEST_READ))
        # Editing in test: only the test layers become editable (not the one being edited)
        changed, editing, failed = repoint(EDIT_TEST)
        self.assertEqual((changed, editing, failed), (1, [busy.name()], []))
        self.assertEqual(test.src, loader.layer_source("t_5802_fac_li", EDIT_TEST))
        self.assertEqual(prod.src, loader.layer_source("t_5710_born_skole_dis", READ))
        # Editing in production: the production layers become editable, the test layers read-only
        repoint(EDIT)
        self.assertEqual(prod.src, loader.layer_source("t_5710_born_skole_dis", EDIT))
        self.assertEqual(old.src, loader.layer_source("t_5800_fac_pkt", EDIT))
        self.assertEqual(old.customProperty(loader.TABLE_PROPERTY), "t_5800_fac_pkt")
        self.assertEqual(test.src, loader.layer_source("t_5802_fac_li", TEST_READ))
        self.assertEqual(other.src, "url='https://example.com/wfs' typename='x:y'")
        self.assertEqual({key: layer.name() for key, layer in layers.items()}, names)
        self.assertEqual(loader.layers_outside(EDIT, project), [test, busy])

    def test_test_layer_is_added_beside_the_production_layer(self):
        prod = FakeLayer(loader.layer_source("t_5710_born_skole_dis", READ), table="t_5710_born_skole_dis")
        project = types.SimpleNamespace(mapLayers=lambda: {"prod": prod}, customVariables=lambda: {})
        created = []

        class Layer:
            def __init__(self, uri, name, provider):
                created.append((uri, name))

            def isValid(self):
                return False

        pushed, message_bar = _messages()
        dataset = catalogue().get("t_5710_born_skole_dis")
        with patch.object(loader, "QgsVectorLayer", Layer):
            self.assertIs(loader.add_dataset(dataset, READ, message_bar, project), prod)
            loader.add_dataset(dataset, TEST_READ, message_bar, project)
        self.assertEqual(created, [(loader.layer_source(dataset.table, TEST_READ), dataset.title + " [TEST]")])

    def test_test_layers_from_older_versions_get_the_test_suffix(self):
        old_test = FakeLayer("pagingEnabled='false' typename='fkg:fkg.t_5800_fac_pkt' "
                             "url='https://geofa-test.geodanmark.dk/ows/fkg/fkg'", name="Faciliteter, punkter")
        marked = FakeLayer(loader.layer_source("t_5802_fac_li", TEST_READ), name="Linjer [TEST]",
                           table="t_5802_fac_li")
        prod = FakeLayer(loader.layer_source("t_5710_born_skole_dis", READ), table="t_5710_born_skole_dis")
        project = types.SimpleNamespace(mapLayers=lambda: {"old": old_test, "marked": marked, "prod": prod})
        self.assertEqual(loader.mark_test_layers(project), 1)
        self.assertEqual([old_test.name(), marked.name(), prod.name()],
                         ["Faciliteter, punkter [TEST]", "Linjer [TEST]", "Skoledistrikter (5710)"])

    def test_old_5609_layer_points_at_the_renamed_table(self):
        layer = FakeLayer("pagingEnabled='false' typename='fkg:fkg.t_5609_cykelknudepunktsstraekninger' "
                          "url='https://geofa.geodanmark.dk/ows/fkg/fkg'")
        project = types.SimpleNamespace(mapLayers=lambda: {"old": layer})
        with patch.object(loader, "replace_layer", _replace_in_place):
            self.assertEqual(loader.fix_renamed_tables(project), 1)
        self.assertIn("typename='fkg:fkg.t_5609_cykelkrydspunktsstraekninger'", layer.src)

    def test_panel_searches_title_and_theme_code(self):
        panel = GeoFAPanel(catalogue(), project=FakeProject({}))

        def shown():
            return [item.text(0) for group in panel.groups() if not group.isHidden()
                    for item in panel.children(group) if not item.isHidden()]

        self.assertEqual(len(shown()), 80)
        panel.search.setText("5800")
        self.assertEqual(shown(), ["Friluftsliv faciliteter, punkter (5800)"])
        panel.search.setText("skole 5710")
        self.assertEqual(shown(), ["Børne- og skoledistrikter (5710)"])
        panel.search.setText("forsyning")  # a group's name shows all its layers
        self.assertEqual(len(shown()), len(dict(catalogue().groups)["Forsyning"]))
        panel.set_mode(EDIT_TEST)
        self.assertFalse(panel.test_banner.isHidden())
        self.assertTrue(panel.edit_button.isChecked())
        # The login button: the login shows the non-public objects too, not only editing
        self.assertIn("Logget ind som kom999 i testmiljøet", panel.edit_button.toolTip())
        self.assertIn("ikke er offentlige", panel.edit_button.toolTip())
        self.assertTrue(QFile.exists(":/images/themes/default" + LOGIN_ICON))  # QGIS's own icon
        panel.set_mode(READ)
        self.assertTrue(panel.test_banner.isHidden())
        self.assertFalse(panel.edit_button.isChecked())
        self.assertIn("kun de objekter, der er offentlige", panel.edit_button.toolTip())
        self.assertFalse(panel.edit_button.autoRaise())  # a framed button, as in Geodata Connect
        # Natural size or more, and centred exactly on the search field: an even difference in height
        field = panel.search.sizeHint().height()
        for button in (panel.edit_button, panel.settings_button):
            width, height = button.maximumWidth(), button.maximumHeight()
            self.assertGreaterEqual(height, max(field, button.sizeHint().height()))
            self.assertGreaterEqual(width, max(height, button.sizeHint().width()))
            self.assertEqual((height - field) % 2, 0)
        self.assertTrue(panel.area_filter.isHidden())
        panel.set_mode(loader.Mode(edit=False, test=False, username="kom999", kommune="0751"))
        self.assertFalse(panel.area_filter.isHidden())
        self.assertEqual(panel.area_filter.text(), "Kun objekter i Aarhus Kommune")

    def test_panel_ticks_mirror_the_project(self):
        prod = FakeLayer(loader.layer_source("t_5800_fac_pkt", READ), table="t_5800_fac_pkt")
        project = FakeProject({"prod": prod})
        panel = GeoFAPanel(catalogue(), project=project)
        panel.set_mode(READ)
        added, removed = [], []
        panel.add_requested.connect(added.append)
        panel.remove_requested.connect(removed.append)
        group = next(g for g in panel.groups() if g.data(0, ROLE_GROUP) == "Sport, fritid og friluftsliv")
        items = {item.data(0, ROLE_TABLE): item for item in panel.children(group)}
        self.assertEqual(items["t_5800_fac_pkt"].checkState(0), Qt.CheckState.Checked)
        self.assertEqual(items["t_5801_fac_fl"].checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(group.checkState(0), Qt.CheckState.PartiallyChecked)
        self.assertTrue(group.text(0).endswith("· 1 indlæst"))
        self.assertFalse(items["t_5800_fac_pkt"].icon(0).isNull())  # the geometry type's icon
        # Ticking adds, unticking removes
        items["t_5801_fac_fl"].setCheckState(0, Qt.CheckState.Checked)
        items["t_5800_fac_pkt"].setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual((added, removed), ([["t_5801_fac_fl"]], [["t_5800_fac_pkt"]]))
        # The ticks show the project, not the click: nothing was really added or removed here
        self.assertEqual(items["t_5801_fac_fl"].checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(items["t_5800_fac_pkt"].checkState(0), Qt.CheckState.Checked)
        # Ticking the group adds the layers shown that aren't in the project, after asking when there are many
        panel.search.setText("fac")
        with patch.object(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes):
            group.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(added[-1], ["t_5801_fac_fl", "t_5802_fac_li"])
        # In test, the production layer doesn't count
        panel.set_mode(TEST_READ)
        self.assertEqual(items["t_5800_fac_pkt"].checkState(0), Qt.CheckState.Unchecked)
        # Removing a layer in QGIS clears its tick
        panel.set_mode(READ)
        project.layers.clear()
        project.layersRemoved.emit(["prod"])
        self.assertEqual(items["t_5800_fac_pkt"].checkState(0), Qt.CheckState.Unchecked)
        panel.cleanup()

    def test_unticking_removes_layers_but_not_ones_being_edited(self):
        prod = FakeLayer(loader.layer_source("t_5800_fac_pkt", READ), table="t_5800_fac_pkt")
        busy = FakeLayer(loader.layer_source("t_5801_fac_fl", READ), table="t_5801_fac_fl", editing=True)
        test = FakeLayer(loader.layer_source("t_5800_fac_pkt", TEST_READ), table="t_5800_fac_pkt")
        layers = {"prod": prod, "busy": busy, "test": test}
        project = FakeProject(layers)
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.mode = READ
        instance = types.SimpleNamespace(instance=lambda: project)
        with patch.object(loader, "QgsProject", instance), patch.object(geofa_module, "QgsProject", instance):
            plugin.remove_tables(["t_5800_fac_pkt", "t_5801_fac_fl"])
        self.assertEqual(project.removed, [["prod"]])  # not the test layer, nor the one being edited
        self.assertIn("redigering", iface.pushed[0][1])

    def test_about_names_the_version_and_links(self):
        text = about.about_text(80)
        self.assertIn(about.plugin_version(), text)
        for url in (about.GUIDE_URL, about.SPEC_URL, about.ISSUES_URL):
            self.assertIn(url, text)

    def test_switching_to_test_keeps_production_layers_and_says_so(self):
        prod = FakeLayer(loader.layer_source("t_5710_born_skole_dis", READ), table="t_5710_born_skole_dis")
        project = types.SimpleNamespace(mapLayers=lambda: {"prod": prod}, customVariables=lambda: {})
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        for key, value in (("wfst", False), ("testmiljo", False), ("username", "kom999")):
            plugin.settings.set_value(key, value)
        plugin.settings.emit_updated()
        try:
            with patch.object(loader, "QgsProject", types.SimpleNamespace(instance=lambda: project)):
                plugin.settings.set_value("testmiljo", True)
                plugin.settings.emit_updated()
            self.assertEqual(prod.src, loader.layer_source("t_5710_born_skole_dis", READ))
            self.assertEqual(prod.name(), "Skoledistrikter (5710)")
            self.assertEqual([message[1] for message in iface.pushed],
                             ["Nye GeoFA-lag hentes nu fra testmiljøet og får »[TEST]« i navnet. "
                              "1 lag fra produktion bliver i projektet."])
        finally:
            plugin.settings.set_value("testmiljo", False)
            plugin.settings.emit_updated()
            plugin.unload()

    def test_html_descriptions_are_formatted_until_the_layer_is_edited(self):
        layer = QgsVectorLayer("Point?crs=EPSG:25832&field=navn:string&field=lang_beskr:string&field=d_l_beskr:string",
                               "5800", "memory")
        layer.setEditorWidgetSetup(2, QgsEditorWidgetSetup("Hidden", {}))  # the user's own choice stays

        def widget(index):
            setup = layer.editorWidgetSetup(index)
            return setup.type(), setup.config().get("UseHtml")

        self.assertTrue(htmlfields.follow(layer))
        self.assertEqual(widget(1), ("TextEdit", True))
        layer.startEditing()
        self.assertEqual(widget(1), ("TextEdit", False))  # the HTML itself, to edit
        layer.rollBack()
        self.assertEqual(widget(1), ("TextEdit", True))
        self.assertEqual(widget(2), ("Hidden", None))
        self.assertEqual(widget(0), ("", None))  # not a description: untouched
        self.assertFalse(htmlfields.follow(QgsVectorLayer("Point?field=navn:string", "x", "memory")))

    def test_edit_switch_without_login_opens_settings(self):
        credentials.remove_login()
        iface = FakeIface()
        plugin = GeoFA(iface)
        plugin.initGui()
        plugin.settings.set_value("wfst", False)
        plugin.settings.set_value("username", "")
        plugin.settings.emit_updated()
        try:
            plugin.edit_action.trigger()
            self.assertFalse(plugin.settings.value("wfst"))
            self.assertFalse(plugin.edit_action.isChecked())
            self.assertEqual(iface.options_opened, ["settings"])
        finally:
            plugin.unload()


FACILITET = codelists.Source("fkg.d_5800_facilitet", "facil_ty_k", "facil_ty", "aktiv=1")
KVALITET = codelists.Source("fkg.d_5800_kvalitetstjekket", "kvalitetstjekket_k", "kvalitetstjekket", "aktiv=1")


def _answer(rows):
    return json.dumps({"success": True, "features": [{"properties": {"v": v, "t": t}} for v, t in rows]}).encode()


NOT_REGISTERED = json.dumps({"success": False, "message": "fkg.d_5800_kvalitetstjekket is a relation, but "
                                                          "authentication is not set.\nmore"}).encode()


class FakeGeoFA:
    """GeoFA's SQL API: answers per code list table; records what was asked."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def __call__(self, url, done):
        self.asked.append(url)
        table = next(t for t in self.answers if urllib.parse.quote(t) in url)
        done(self.answers[table], None if b'"success": true' in self.answers[table] else "Internal Server Error")


def _facility_layer():
    return QgsVectorLayer("Point?crs=EPSG:25832&field=facil_ty_k:integer&field=kvalitetstjekket_k:integer"
                          "&field=navn:string", "Friluftsliv faciliteter, punkter (5800)", "memory")


class CodeListTests(unittest.TestCase):
    def setUp(self):
        QgsSettings().remove(codelists.REPORTED_KEY)
        self.dataset = types.SimpleNamespace(code_lists=(("facil_ty_k", FACILITET, True),
                                                         ("kvalitetstjekket_k", KVALITET, False)))

    def widget(self, layer, field):
        setup = layer.editorWidgetSetup(layer.fields().indexOf(field))
        return setup.type(), setup.config()

    def test_answer_is_read_in_code_order(self):
        self.assertEqual(codelists.parse(_answer([("8", "Andet"), ("1", "Helårsåbent"), ("2", "Sæsonåbent")])),
                         [("1", "Helårsåbent"), ("2", "Sæsonåbent"), ("8", "Andet")])
        for data, reason in ((NOT_REGISTERED, "authentication is not set."), (b"<html>", "svarede ikke"),
                             (_answer([]), "tom"), (_answer([("1", "a"), ("1", "b")]), "samme kode")):
            with self.assertRaises(codelists.CodeListError) as raised:
                codelists.parse(data)
            self.assertIn(reason, str(raised.exception))
        self.assertIn("SELECT%20%28facil_ty_k%29%3A%3Atext", FACILITET.url(loader.PRODUCTION_HOST))
        self.assertTrue(FACILITET.url(loader.TEST_HOST).startswith("https://geofa-test.geodanmark.dk/api/v2/sql/fkg?q="))

    def test_dropdowns_come_from_geofa_and_a_broken_list_shows_codes_and_is_reported_once(self):
        geofa = FakeGeoFA({FACILITET.table: _answer([("2012", "Svømmehal"), ("1012", "Toilet")]),
                           KVALITET.table: NOT_REGISTERED})
        reports = []
        lists = codelists.CodeLists(fetch=geofa)
        lists.problems.connect(reports.append)
        layer = _facility_layer()
        lists.fill([(layer, self.dataset, loader.PRODUCTION_HOST)])
        # A required field too starts with "<ingen værdi>"; its not-null constraint marks it while empty
        self.assertEqual(self.widget(layer, "facil_ty_k"),
                         ("ValueMap", {"map": [{codelists.NO_VALUE: codelists.NULL_VALUE}, {"Toilet": "1012"},
                                               {"Svømmehal": "2012"}]}))
        self.assertEqual(self.widget(layer, "kvalitetstjekket_k")[0], "TextEdit")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0][0]["table"], KVALITET.table)
        self.assertIn("authentication is not set", reports[0][0]["reason"])
        self.assertEqual(reports[0][0]["fields"], ["Friluftsliv faciliteter, punkter (5800): kvalitetstjekket_k"])
        # Read once per session: a second layer uses what was read
        lists.fill([(_facility_layer(), self.dataset, loader.PRODUCTION_HOST)])
        self.assertEqual(len(geofa.asked), 2)
        # Next session: the same broken list isn't reported again
        later = codelists.CodeLists(fetch=geofa)
        later.problems.connect(reports.append)
        later.fill([(_facility_layer(), self.dataset, loader.PRODUCTION_HOST)])
        self.assertEqual(len(reports), 1)
        # Once it works again, the dropdown is back
        geofa.answers[KVALITET.table] = _answer([("1", "Ja"), ("2", "Nej")])
        later.forget()
        later.fill([(layer, self.dataset, loader.PRODUCTION_HOST)])
        self.assertEqual(self.widget(layer, "kvalitetstjekket_k"),
                         ("ValueMap", {"map": [{codelists.NO_VALUE: codelists.NULL_VALUE}, {"Ja": "1"}, {"Nej": "2"}]}))
        # ...and breaking again is reported again
        geofa.answers[KVALITET.table] = NOT_REGISTERED
        third = codelists.CodeLists(fetch=geofa)
        third.problems.connect(reports.append)
        third.fill([(layer, self.dataset, loader.PRODUCTION_HOST)])
        self.assertEqual(len(reports), 2)
        self.assertEqual(self.widget(layer, "kvalitetstjekket_k")[0], "TextEdit")

    def test_lists_are_read_in_a_background_task(self):
        folder = tempfile.mkdtemp(prefix="geofa_codes_")
        path = os.path.join(folder, "answer.json")
        with open(path, "wb") as f:
            f.write(_answer([("2", "Nej"), ("1", "Ja")]))
        answers = []
        codelists.network_fetch(QUrl.fromLocalFile(path).toString(), lambda data, error: answers.append((data, error)))
        for _ in range(200):
            if answers:
                break
            QCoreApplication.processEvents()
            time.sleep(0.02)
        self.assertEqual(len(answers), 1)
        self.assertEqual(codelists.parse(answers[0][0]), [("1", "Ja"), ("2", "Nej")])
        self.assertIsNone(answers[0][1])
        self.assertEqual(codelists._RUNNING, set())

    def test_the_users_own_widgets_are_left_alone(self):
        layer = _facility_layer()
        relation = QgsEditorWidgetSetup("ValueRelation", {"Layer": "d_5800_facilitet", "Key": "facil_ty_k"})
        layer.setEditorWidgetSetup(0, relation)
        codelists.apply(layer, self.dataset.code_lists, {FACILITET: [("1012", "Toilet")]})
        self.assertEqual(self.widget(layer, "facil_ty_k")[0], "ValueRelation")

    def test_styles_hold_no_code_lists_and_the_catalogue_says_where_they_are(self):
        dataset = catalogue().get("t_5800_fac_pkt")
        self.assertIn(("facil_ty_k", FACILITET, True), dataset.code_lists)
        self.assertEqual(len(dataset.form_version), 12)
        layer = _facility_layer()
        layer.loadNamedStyle(dataset.style_path)
        self.assertEqual(self.widget(layer, "facil_ty_k")[0], "TextEdit")
        with open(dataset.style_path, encoding="utf-8") as f:
            self.assertNotIn('type="ValueMap"', f.read())
        # Ratings 0-9 from a database check are a number range, not a code list
        rating = QgsVectorLayer("MultiPolygon?crs=EPSG:25832&field=arkitektonisk_vaerdi:integer", "6205", "memory")
        _, ok = rating.loadNamedStyle(catalogue().get("t_6205_bygningsvurdering").style_path)
        self.assertTrue(ok)
        setup = rating.editorWidgetSetup(0)
        self.assertEqual((setup.type(), setup.config()["Min"], setup.config()["Max"]), ("Range", 0, 9))

    def test_form_update_keeps_symbology_and_stamps_the_layer(self):
        dataset = catalogue().get("t_5800_fac_pkt")
        layer = _facility_layer()
        renderer = layer.renderer().clone()
        layer.setCustomProperty(loader.TABLE_PROPERTY, dataset.table)
        layer.setMapTipsEnabled(True)  # as in projects from before map tips were switched off
        project = types.SimpleNamespace(mapLayers=lambda: {"layer": layer})
        self.assertEqual(loader.outdated_layers(project), [(layer, dataset)])
        self.assertTrue(loader.update_form(layer, dataset))
        self.assertEqual(layer.renderer().type(), renderer.type())
        self.assertEqual(layer.fields().field("facil_ty_k").alias(), "Facilitettype (facil_ty_k)")
        self.assertFalse(layer.mapTipsEnabled())
        self.assertEqual(loader.outdated_layers(project), [])
        self.assertEqual(loader.code_list_layers(project), [(layer, dataset, loader.PRODUCTION_HOST)])

    def test_unused_domain_tables_from_0_36_are_found(self):
        def old_table(name):
            return types.SimpleNamespace(providerType=lambda: "ogr", name=lambda: name, id=lambda: name + "_id",
                                         source=lambda: "https://geofa.geodanmark.dk/api/v2/sql/fkg?"
                                                        f"q=SELECT%20*%20FROM%20fkg.{name}")
        used, unused = old_table("d_5800_facilitet"), old_table("d_5800_saeson")
        layer = _facility_layer()
        layer.setEditorWidgetSetup(0, QgsEditorWidgetSetup("ValueRelation", {"Layer": used.id(), "Key": "facil_ty_k"}))
        project = types.SimpleNamespace(mapLayers=lambda: {"a": used, "b": unused, "c": layer})
        self.assertEqual(loader.old_domain_layers(project), [unused])

    def test_opening_a_project_with_older_forms_offers_an_update(self):
        dataset = catalogue().get("t_5800_fac_pkt")
        layer = _facility_layer()
        # A layer from 0.36: no form version, and a hidden domain table in the project
        layer.setCustomProperty(loader.TABLE_PROPERTY, dataset.table)
        old_table = types.SimpleNamespace(providerType=lambda: "ogr", name=lambda: "d_5800_saeson",
                                          id=lambda: "d_id", customProperty=lambda key: None,
                                          source=lambda: "https://geofa.geodanmark.dk/api/v2/"
                                                         "sql/fkg?q=SELECT%20*%20FROM%20fkg.d_5800_saeson")
        layers = {"layer": layer, "old": old_table}
        project = types.SimpleNamespace(mapLayers=lambda: layers, customVariables=lambda: {},
                                        layerTreeRoot=lambda: None, setDirty=lambda dirty: None,
                                        removeMapLayers=lambda ids: [layers.pop(k) for k in list(layers)
                                                                     if layers[k].id() in ids])
        iface = FakeIface()
        offered = []
        iface.message_bar.createMessage = QgsMessageBar.createMessage
        iface.message_bar.pushWidget = lambda widget, level, duration: offered.append(widget)
        iface.message_bar.popWidget = lambda widget: True
        plugin = GeoFA(iface)
        plugin.initGui()
        geofa = FakeGeoFA({FACILITET.table: _answer([("1012", "Toilet")]), KVALITET.table: NOT_REGISTERED,
                           "fkg.d_": _answer([("1", "x")])})
        plugin.code_lists.fetch = geofa
        reports = []
        plugin.code_lists.problems.connect(reports.append)
        instance = types.SimpleNamespace(instance=lambda: project)
        try:
            with patch.object(loader, "QgsProject", instance), patch.object(geofa_module, "QgsProject", instance):
                plugin.project_opened()
                self.assertEqual(len(offered), 1)
                self.assertIn("1 GeoFA-lag", offered[0].text())
                self.assertEqual(geofa.asked, [])  # until its form is updated, a 0.36 layer keeps its own lists
                offered[0].findChild(QPushButton).click()
            self.assertEqual(layer.customProperty(loader.FORM_PROPERTY), dataset.form_version)
            self.assertEqual(self.widget(layer, "facil_ty_k"),
                             ("ValueMap", {"map": [{codelists.NO_VALUE: codelists.NULL_VALUE}, {"Toilet": "1012"}]}))
            self.assertEqual(self.widget(layer, "kvalitetstjekket_k")[0], "TextEdit")
            self.assertEqual(len(reports), 1)
            self.assertNotIn("old", layers)
            self.assertIn("1 gamle domænetabeller", iface.pushed[-1][1])
        finally:
            for box in QApplication.topLevelWidgets():
                if box.windowTitle() == "GeoFA – kodelister":
                    box.close()
            plugin.unload()


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
