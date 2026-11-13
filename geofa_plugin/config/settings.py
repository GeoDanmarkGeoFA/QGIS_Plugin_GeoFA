# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtCore import QFileInfo, QObject
from qgis.PyQt import QtCore

from .qgissettingmanager import *
class Settings(SettingManager):
    settings_updated = QtCore.pyqtSignal()

    def __init__(self):
        SettingManager.__init__(self, 'GeoFA')

        # The order here is the order results are displayed in
        self.add_setting(String('username', Scope.Global, ''))
        # The password is not a setting: it lives in QGIS's password store (see credentials.py)
        self.add_setting(Bool('wfst', Scope.Global, False))
        self.add_setting(Bool('testmiljo', Scope.Global, False))


    def emit_updated(self):
        self.settings_updated.emit()

    

