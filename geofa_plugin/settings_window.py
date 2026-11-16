# -*- coding: utf-8 -*-
"""GeoFA's settings: login, editing, test environment and the municipality filter.

The same form is shown in two places: a small window (GeoFA › Indstillinger … and ⚙ in the
panel) and a GeoFA page in QGIS's Options (Indstillinger › Indstillinger). The password is
never a setting: it goes into QGIS's password store (credentials.py), and the field never
shows a stored password again.
"""
import os

from qgis.core import Qgis
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory, QgsPasswordLineEdit
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                                 QVBoxLayout, QWidget)
from qgis.utils import iface

from . import credentials, municipalities
from .config.qgissettingmanager.setting_dialog import SettingDialog, UpdateMode
from .panel import Banner

PASSWORD_PLACEHOLDER = "Adgangskode"
PASSWORD_SAVED_PLACEHOLDER = "Gemt – skriv en ny for at ændre den"
WHOLE_COUNTRY = "Hele landet"
ICON = os.path.join(os.path.dirname(__file__), "icon.png")  # the GeoFA "G"
GEOPARTNER_URL = "https://geopartner.dk"


def developer_credit():
    """Who made the plugin, with a link that opens in the browser."""
    label = QLabel(f"GeoFA-pluginet er udviklet af <a href='{GEOPARTNER_URL}'>Geopartner</a>.")
    label.setObjectName("developer_credit")
    label.setOpenExternalLinks(True)
    return label


class SettingsForm(QWidget, SettingDialog):
    """Username and password (QGIS's password field, with the eye), use of the login, the test
    environment and the municipality filter.

    The username, wfst and testmiljo widgets are named after their settings, which binds them
    through SettingDialog. apply() stores those, the municipality (its box is deliberately not
    bound) and the password (in QGIS's password store).
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
        self.check_box_wfst = QCheckBox("Brug mit login")
        self.check_box_wfst.setObjectName("wfst")
        self.check_box_wfst.setToolTip(
            "<p>Med dit login viser lagene også de objekter, der ikke er offentlige (fx beskyttelsesrum), "
            "og de kan redigeres (WFS-T).<br>Uden login viser lagene kun offentlige objekter og kan ikke "
            "redigeres.</p>")
        layout.addWidget(self.check_box_wfst)
        self.check_box_test = QCheckBox("Testmiljø")
        self.check_box_test.setObjectName("testmiljo")
        self.check_box_test.setToolTip("Nye lag hentes fra GeoFA's testmiljø og får »[TEST]« i navnet.")
        layout.addWidget(self.check_box_test)
        note = QLabel("Adgangskoden gemmes i QGIS' adgangskodelager, ikke i projekter eller indstillinger.")
        note.setWordWrap(True)
        note.setEnabled(False)  # shown greyed, as a hint
        layout.addWidget(note)

        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>Område</b>"))
        area = QFormLayout()
        self.municipality_box = QComboBox()
        self.municipality_box.setObjectName("kommune_box")  # not "kommune": stored by apply(), not the binding
        self.municipality_box.addItem(WHOLE_COUNTRY, "")
        for code, name in municipalities.choices():
            self.municipality_box.addItem(name, code)
        self.municipality_box.setToolTip("Vis kun objekter i én kommune. Gælder alle GeoFA-lag i projektet.")
        chosen = self.municipality_box.findData(settings.value("kommune") or "")
        self.municipality_box.setCurrentIndex(max(chosen, 0))
        area.addRow("Kun objekter i", self.municipality_box)
        layout.addLayout(area)

        # Fills the bound widgets from the settings; apply() writes them back
        SettingDialog.__init__(self, settings, UpdateMode.NoUpdate)
        self.reset_password_field()
        self.update_login_checkbox()
        self.username_edit.textChanged.connect(self.update_login_checkbox)
        self.password_edit.textChanged.connect(self.update_login_checkbox)

    def reset_password_field(self):
        self.password_edit.clear()
        self.password_edit.setPlaceholderText(PASSWORD_SAVED_PLACEHOLDER if credentials.has_password()
                                              else PASSWORD_PLACEHOLDER)

    def update_login_checkbox(self):
        """»Brug mit login« needs a username and a password (typed now, or stored earlier)."""
        ready = bool(self.username_edit.text().strip()) and bool(
            self.password_edit.text().strip() or credentials.has_password())
        self.check_box_wfst.setEnabled(ready)
        if not ready:
            self.check_box_wfst.setChecked(False)

    def store_login(self, old_username):
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
            # Without a stored login the layers can't use it
            self.settings.set_value("wfst", False)
            self.check_box_wfst.setChecked(False)
            iface.messageBar().pushMessage(
                "GeoFA", "Login blev ikke gemt. QGIS skal have en master-adgangskode for at gemme koden sikkert.",
                level=Qgis.MessageLevel.Warning, duration=15)

    def apply(self):
        old_username = self.settings.value("username")
        self.set_values_from_widgets()
        self.settings.set_value("kommune", self.municipality_box.currentData() or "")
        self.store_login(old_username)
        self.reset_password_field()
        self.update_login_checkbox()
        # The plugin applies the new mode (see GeoFA.apply_settings)
        self.settings.emit_updated()


class SettingsDialog(QDialog):
    """The small settings window."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GeoFA – indstillinger")
        self.setWindowIcon(QIcon(ICON))
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(Banner("Login, redigering, testmiljø og område"))
        body = QVBoxLayout()
        body.setContentsMargins(10, 8, 10, 0)
        body.setSpacing(8)
        layout.addLayout(body)
        self.form = SettingsForm(settings)
        body.addWidget(self.form)
        body.addWidget(developer_credit())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)

    def accept(self):
        # Stores the settings and emits their update; the plugin then applies the new mode
        self.form.apply()
        super().accept()


class OptionsPage(QgsOptionsPageWidget):
    """The GeoFA page in QGIS's Options: the same form; QGIS calls apply() on OK."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("geofaOptions")
        layout = QVBoxLayout(self)
        self.form = SettingsForm(settings)
        layout.addWidget(self.form)
        layout.addStretch(1)
        layout.addWidget(developer_credit())  # at the bottom of the page

    def apply(self):
        self.form.apply()


class OptionsFactory(QgsOptionsWidgetFactory):
    """Adds the GeoFA page, with the GeoFA "G", to QGIS's Options."""

    def __init__(self, settings):
        super().__init__("GeoFA", QIcon(ICON))
        self.settings = settings

    def icon(self):
        return QIcon(ICON)

    def createWidget(self, parent):
        return OptionsPage(self.settings, parent)
