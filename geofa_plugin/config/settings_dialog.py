# -*- coding: utf-8 -*-
import os
from qgis.PyQt import QtGui, uic
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.gui import (QgsOptionsPageWidget)
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QVBoxLayout, QLineEdit, QCheckBox, QPushButton
from .qgissettingmanager import *
from ..import_geofa import import_geofa
from .. import credentials
from qgis.core import QgsProject, QgsExpressionContextUtils, Qgis
from qgis.utils import iface

OPTIONS_PAGE_NAME = "geofaOptions"  # used to open QGIS's Options dialog on this page
PASSWORD_PLACEHOLDER = "Kode"
PASSWORD_SAVED_PLACEHOLDER = "Kode gemt – skriv ny for at ændre"

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
        self.setObjectName(OPTIONS_PAGE_NAME)

        # set config variables
        self.username = self.settings.value('username')
        self.wfst = self.settings.value('wfst')
        self.testmiljo = self.settings.value('testmiljo')

        # Find the widgets by their object names
        self.username_edit = self.findChild(QLineEdit, "username")
        self.password_edit = self.findChild(QLineEdit, "password")
        self.check_box_wfst = self.findChild(QCheckBox, "wfst")
        self.vispw_button = self.findChild(QPushButton, "vispw")

        # The saved password is never loaded back into the field; it only takes a new one
        self.reset_password_field()

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

    def reset_password_field(self):
        self.password_edit.clear()
        if credentials.has_password():
            self.password_edit.setPlaceholderText(PASSWORD_SAVED_PLACEHOLDER)
        else:
            self.password_edit.setPlaceholderText(PASSWORD_PLACEHOLDER)

    def on_text_changed(self):
        # WFS-T needs a username and a password (typed now, or saved earlier)
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip() or credentials.has_password()

        if username and password:
            self.check_box_wfst.setEnabled(True)
        else:
            self.check_box_wfst.setEnabled(False)
            self.check_box_wfst.setChecked(False)

    def save_login(self, old_username):
        """Store, update or forget the login in QGIS's password store."""
        username = (self.settings.value('username') or '').strip()
        new_password = self.password_edit.text()
        if not username:
            credentials.remove_login()
            return
        if not new_password and not credentials.has_password():
            return  # nothing to store yet
        username_changed = username != (old_username or '').strip()
        # (no bool() here: "from .qgissettingmanager import *" shadows it with the types.bool module)
        legacy_pending = credentials.legacy_password() != "" and not credentials.has_login()
        if not (new_password or username_changed or legacy_pending):
            return  # already stored and unchanged: skip a needless master password prompt
        if not credentials.save_login(username, new_password or None):
            # Without a stored login, editing cannot work
            self.settings.set_value('wfst', False)
            self.check_box_wfst.setChecked(False)
            iface.messageBar().pushMessage(
                "GeoFA",
                "Login blev ikke gemt. QGIS skal have en master-adgangskode for at gemme koden sikkert.",
                level=Qgis.MessageLevel.Warning, duration=15)

    def apply(self):
        old_username = self.settings.value('username')
        self.config_widget.accept_dialog()
        self.save_login(old_username)
        self.reset_password_field()
        self.on_text_changed()
        self.settings.emit_updated()

        # Update config variables
        self.username = self.settings.value('username')
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

        





