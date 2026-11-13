# -*- coding: utf-8 -*-
import os
from qgis.PyQt import QtGui, uic
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.gui import (QgsOptionsPageWidget)
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QVBoxLayout, QLineEdit, QCheckBox, QPushButton
from .qgissettingmanager import *
from ..import_geofa import import_geofa
from qgis.core import QgsProject, QgsExpressionContextUtils

WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'settings.ui')
)


class ConfigOptionsPage(QgsOptionsPageWidget):

    def __init__(self, parent, settings):
        super(ConfigOptionsPage, self).__init__(parent)
        self.settings = settings
        self.config_widget = ConfigDialog(self.settings)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        layout.addWidget(self.config_widget)
        self.setObjectName('geofaOptions')

        # set config variables
        self.username = self.settings.value('username')
        self.password = self.settings.value('password')
        self.wfst = self.settings.value('wfst')
        self.testmiljo = self.settings.value('testmiljo')

        # Find the widgets by their object names
        self.username_edit = self.findChild(QLineEdit, "username")
        self.password_edit = self.findChild(QLineEdit, "password")
        self.check_box_wfst = self.findChild(QCheckBox, "wfst")
        self.vispw_button = self.findChild(QPushButton, "vispw")

        # Check if there is initially something written in the QLineEdit widgets
        # and enable/disable the QCheckBox accordingly
        self.on_text_changed()

        # Connect the textChanged signals of the QLineEdits to the on_text_changed slot
        self.username_edit.textChanged.connect(self.on_text_changed)
        self.password_edit.textChanged.connect(self.on_text_changed)

        # Connect the clicked signals of the QCheckBox to the on_check_box_clicked slot
        self.vispw_button.pressed.connect(self.show_password)
        self.vispw_button.released.connect(self.hide_password)

    def show_password(self):
        # Temporarily set the echo mode of the password edit to "Normal" (plain text)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Normal)

    def hide_password(self):
        # Reset the echo mode of the password edit to "Password" (masked input)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def on_text_changed(self):
        # Enable or disable the checkbox based on the content of the QLineEdits
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()

        if username and password:
            self.check_box_wfst.setEnabled(True)
        else:
            self.check_box_wfst.setEnabled(False)
            self.check_box_wfst.setChecked(False)

    def apply(self):
        self.config_widget.accept_dialog()
        self.settings.emit_updated()

        # Update config variables
        self.username = self.settings.value('username')
        self.password = self.settings.value('password')
        self.wfst = self.settings.value('wfst')
        self.testmiljo = self.settings.value('testmiljo')

        # Set project variables
        QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), 'geofa_bruger_id', self.username)

        # Update the d_tables
        import_geofa.d_tables(self, update=True)

        # Get the menu items
        menu_items = import_geofa.generate_menu_items()

        # get the layers
        layers = [layer.name() for layer in QgsProject.instance().mapLayers().values()]

        # Update the menu items
        for main_menu, submenus in menu_items.items():
            for submenu in submenus:
                if submenu in layers:
                    import_geofa.run_action(self, submenu, "", update=True)


class ConfigDialog(WIDGET, BASE, SettingDialog):
    def __init__(self, settings):
        super(ConfigDialog, self).__init__(None)
        self.setupUi(self)
        SettingDialog.__init__(self, settings)
        self.settings = settings

        





