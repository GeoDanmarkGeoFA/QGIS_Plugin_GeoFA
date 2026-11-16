# -*- coding: utf-8 -*-
"""GeoFA's settings in a small window: GeoFA › Indstillinger … and ⚙ in the panel.

The only place for the plugin's settings (as in Geodata Connect): there is no GeoFA page in
QGIS's own Options dialog. The password is never a setting: it goes into QGIS's password
store (credentials.py), and the field never shows a stored password again.
"""
from qgis.core import Qgis
from qgis.gui import QgsPasswordLineEdit
from qgis.PyQt.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
                                 QWidget)
from qgis.utils import iface

from . import credentials
from .config.qgissettingmanager.setting_dialog import SettingDialog, UpdateMode
from .panel import Banner

PASSWORD_PLACEHOLDER = "Adgangskode"
PASSWORD_SAVED_PLACEHOLDER = "Gemt – skriv en ny for at ændre den"


class LoginForm(QWidget, SettingDialog):
    """Username and password (QGIS's password field, with the eye), editing and the test environment.

    The widgets are named after the settings (username, wfst, testmiljo), which binds them to
    the plugin's settings; apply() stores them.
    """

    def __init__(self, settings, parent=None):
        QWidget.__init__(self, parent)
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>GeoFA-login</b>"))
        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setObjectName("username")
        self.username_edit.setPlaceholderText("fx kom101")
        self.password_edit = QgsPasswordLineEdit()
        form.addRow("Brugernavn", self.username_edit)
        form.addRow("Adgangskode", self.password_edit)
        layout.addLayout(form)
        self.check_box_wfst = QCheckBox("Redigering (WFS-T)")
        self.check_box_wfst.setObjectName("wfst")
        self.check_box_wfst.setToolTip("Kræver et GeoFA-login. Uden login kan lagene kun vises.")
        layout.addWidget(self.check_box_wfst)
        self.check_box_test = QCheckBox("Testmiljø")
        self.check_box_test.setObjectName("testmiljo")
        self.check_box_test.setToolTip("Nye lag hentes fra GeoFA's testmiljø og får »[TEST]« i navnet.")
        layout.addWidget(self.check_box_test)
        note = QLabel("Adgangskoden gemmes i QGIS' adgangskodelager, ikke i projekter eller indstillinger.")
        note.setWordWrap(True)
        note.setEnabled(False)  # shown greyed, as a hint
        layout.addWidget(note)

        # Fills the widgets from the settings; apply() writes them back
        SettingDialog.__init__(self, settings, UpdateMode.NoUpdate)
        self.reset_password_field()
        self.on_text_changed()
        self.username_edit.textChanged.connect(self.on_text_changed)
        self.password_edit.textChanged.connect(self.on_text_changed)

    def reset_password_field(self):
        self.password_edit.clear()
        self.password_edit.setPlaceholderText(PASSWORD_SAVED_PLACEHOLDER if credentials.has_password()
                                              else PASSWORD_PLACEHOLDER)

    def on_text_changed(self):
        # Editing needs a username and a password (typed now, or stored earlier)
        ready = bool(self.username_edit.text().strip()) and bool(
            self.password_edit.text().strip() or credentials.has_password())
        self.check_box_wfst.setEnabled(ready)
        if not ready:
            self.check_box_wfst.setChecked(False)

    def save_login(self, old_username):
        """Store, update or forget the login in QGIS's password store."""
        username = (self.settings.value("username") or "").strip()
        new_password = self.password_edit.text()
        if not username:
            credentials.remove_login()
            return
        if not new_password and not credentials.has_password():
            return  # nothing to store yet
        username_changed = username != (old_username or "").strip()
        legacy_pending = credentials.legacy_password() != "" and not credentials.has_login()
        if not (new_password or username_changed or legacy_pending):
            return  # stored and unchanged: no needless master password prompt
        if not credentials.save_login(username, new_password or None):
            # Without a stored login, editing can't work
            self.settings.set_value("wfst", False)
            self.check_box_wfst.setChecked(False)
            iface.messageBar().pushMessage(
                "GeoFA", "Login blev ikke gemt. QGIS skal have en master-adgangskode for at gemme koden sikkert.",
                level=Qgis.MessageLevel.Warning, duration=15)

    def apply(self):
        old_username = self.settings.value("username")
        self.set_values_from_widgets()
        self.save_login(old_username)
        self.reset_password_field()
        self.on_text_changed()
        # The plugin applies the new mode (see GeoFA.apply_settings)
        self.settings.emit_updated()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GeoFA – indstillinger")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(Banner("Login, redigering og testmiljø"))
        body = QVBoxLayout()
        body.setContentsMargins(10, 8, 10, 0)
        body.setSpacing(8)
        layout.addLayout(body)
        self.form = LoginForm(settings)
        body.addWidget(self.form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)

    def accept(self):
        # Stores the login and emits the settings' update; the plugin then applies the new mode
        self.form.apply()
        super().accept()
