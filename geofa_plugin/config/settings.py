# -*- coding: utf-8 -*-
"""The plugin's settings (under plugins/GeoFA in QGIS's settings)."""
from qgis.PyQt.QtCore import pyqtSignal

from .qgissettingmanager import Bool, Scope, SettingManager, String


class Settings(SettingManager):
    # Emitted by emit_updated() after the settings window or the panel changes a setting;
    # GeoFA.apply_settings follows it
    settings_updated = pyqtSignal()

    def __init__(self):
        SettingManager.__init__(self, 'GeoFA')
        self.add_setting(String('username', Scope.Global, ''))
        # The password is not a setting: it lives in QGIS's password store (see credentials.py)
        self.add_setting(Bool('wfst', Scope.Global, False))  # use the stored login
        self.add_setting(Bool('testmiljo', Scope.Global, False))
        # komkode of the municipality filter (see municipalities.py); empty: the whole country
        self.add_setting(String('kommune', Scope.Global, ''))

    def emit_updated(self):
        self.settings_updated.emit()
