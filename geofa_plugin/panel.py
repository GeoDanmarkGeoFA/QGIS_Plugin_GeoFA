# -*- coding: utf-8 -*-
"""The GeoFA panel: every GeoFA dataset in the spec's groups, as a list of tick boxes.

Like the Geodata Connect panel, the ticks mirror the project: ticking a layer adds it,
unticking removes it, and removing it in QGIS's layer panel clears the tick. A group's
tick shows how many of its layers are in the project (none, some, all), and ticking it
adds the rest. The ticks follow the chosen environment: in test, a layer is ticked when
its [TEST] layer is in the project.
"""
import html

from qgis.core import QgsApplication, QgsProject
from qgis.gui import QgsDockWidget, QgsFilterLineEdit
from qgis.PyQt.QtCore import QSize, Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QSizePolicy, QStyledItemDelegate,
                                 QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import loader

ROLE_TABLE = Qt.ItemDataRole.UserRole + 1
ROLE_SEARCH = Qt.ItemDataRole.UserRole + 2
ROLE_STATE = Qt.ItemDataRole.UserRole + 3  # the tick the panel itself set last
ROLE_GROUP = Qt.ItemDataRole.UserRole + 4  # the group's name (group rows only)
BASE = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
CHECKABLE = BASE | Qt.ItemFlag.ItemIsUserCheckable
ASK_FROM = 4  # adding or removing this many layers at once asks first (adding takes about a second each)
ROW_HEIGHT = 18  # like a QGIS tree with 16 px icons

# GeoFA's colours: the green of the GeoFA icon, and GeoDanmark's dark green and orange (geodanmark.dk)
GEOFA_GREEN = "#93c257"
GEODANMARK_GREEN = "#4c5f35"
GEODANMARK_ORANGE = "#fc8833"
FONT = "font-family:'Segoe UI',Arial,sans-serif"


class Banner(QFrame):
    """The header of the panel and the settings window: GeoFA on GeoDanmark green, with a GeoFA-green line."""

    def __init__(self, subtitle="Geografiske Fagdata i GeoDanmark", parent=None):
        super().__init__(parent)
        self.setObjectName("geofaBanner")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"#geofaBanner {{ background:{GEODANMARK_GREEN}; border-bottom:3px solid {GEOFA_GREEN}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        title = QLabel(f"<span style=\"{FONT};font-size:15px;font-weight:600;color:#ffffff\">GeoFA</span><br>"
                       f"<span style=\"{FONT};font-size:10px;color:#dcebc8\">{html.escape(subtitle)}</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title, 1)


def _test_strip():
    """Shown under the banner only in the test environment."""
    strip = QLabel("TESTMILJØ – nye lag hentes fra GeoFA's testmiljø")
    strip.setObjectName("geofaTest")
    strip.setWordWrap(True)
    strip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    strip.setStyleSheet(f"#geofaTest {{ background:{GEODANMARK_ORANGE}; color:#222222; font-weight:bold; "
                        "padding:4px; }")
    strip.setToolTip("Lag fra testmiljøet får »[TEST]« i navnet.\n"
                     "Lag fra produktion bliver i projektet, men kan kun vises.")
    strip.hide()
    return strip


def _value(state):
    return int(state.value) if hasattr(state, "value") else int(state)


class _AiryRows(QStyledItemDelegate):
    """Rows as tall as in QGIS's own trees, also for the groups (which have no icon)."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height() + 3, ROW_HEIGHT))


def dataset_tooltip(dataset):
    lines = [f"<b>{html.escape(dataset.title)}</b>"]
    if dataset.purpose:
        lines.append(html.escape(dataset.purpose))
    if dataset.pending:
        lines.append("<i>Specifikationen for dette lag kommer snart.</i>")
    lines.append("Sæt hak for at tilføje laget, fjern hakket for at fjerne det. Højreklik for specifikationen.")
    return "<p>" + "<br><br>".join(lines) + "</p>"


class GeoFAPanel(QgsDockWidget):
    add_requested = pyqtSignal(list)  # tables
    remove_requested = pyqtSignal(list)  # tables
    edit_toggled = pyqtSignal(bool)
    settings_requested = pyqtSignal()

    def __init__(self, catalogue, parent=None, project=None):
        super().__init__("GeoFA", parent)
        self.setObjectName("GeoFAPanel")
        self.catalogue = catalogue
        self.project = project or QgsProject.instance()
        self.test = False

        contents = QWidget()
        outer = QVBoxLayout(contents)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(Banner())
        # Only the test environment gets a strip; production is the normal case
        self.test_banner = _test_strip()
        outer.addWidget(self.test_banner)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(6)
        outer.addWidget(body, 1)

        row = QHBoxLayout()
        self.search = QgsFilterLineEdit()
        self.search.setShowSearchIcon(True)
        self.search.setPlaceholderText("Søg lag eller temakode …")
        self.search.textChanged.connect(self.filter)
        row.addWidget(self.search)
        # Read-only or editing, shown as the button's state rather than a banner
        self.edit_button = QToolButton()
        self.edit_button.setCheckable(True)
        self.edit_button.setAutoRaise(True)
        self.edit_button.setIcon(QgsApplication.getThemeIcon("/mActionToggleEditing.svg"))
        # Editing on: a soft GeoFA-green background (readable in light and dark QGIS themes)
        self.edit_button.setStyleSheet("QToolButton:checked { background: rgba(147, 194, 87, 90); "
                                       f"border: 1px solid {GEOFA_GREEN}; border-radius: 3px; }}")
        self.edit_button.toggled.connect(self.edit_toggled)
        row.addWidget(self.edit_button)
        settings_button = QToolButton()
        settings_button.setAutoRaise(True)
        settings_button.setIcon(QgsApplication.getThemeIcon("/mActionOptions.svg"))
        settings_button.setToolTip("Indstillinger for GeoFA (login og testmiljø)")
        settings_button.clicked.connect(lambda: self.settings_requested.emit())
        row.addWidget(settings_button)
        layout.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegate(_AiryRows(self.tree))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)
        self.setWidget(contents)

        self.populate()
        self.project.layersAdded.connect(self.sync)
        self.project.layersRemoved.connect(self.sync)

    # ------------------------------------------------------------------ tree

    def populate(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for group, datasets in self.catalogue.groups:
            group_item = QTreeWidgetItem([group])
            group_item.setFlags(CHECKABLE)  # no auto tristate: sync() sets it from the project
            group_item.setCheckState(0, Qt.CheckState.Unchecked)
            group_item.setData(0, ROLE_GROUP, group)
            group_item.setData(0, ROLE_SEARCH, group.lower())
            for dataset in datasets:
                item = QTreeWidgetItem([dataset.title])
                item.setFlags(CHECKABLE | Qt.ItemFlag.ItemNeverHasChildren)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setIcon(0, dataset.icon())
                item.setData(0, ROLE_TABLE, dataset.table)
                item.setData(0, ROLE_SEARCH, dataset.search_text())
                item.setToolTip(0, dataset_tooltip(dataset))
                group_item.addChild(item)
            self.tree.addTopLevelItem(group_item)
        self.tree.blockSignals(False)
        self.sync()

    def groups(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    @staticmethod
    def children(group_item):
        return [group_item.child(j) for j in range(group_item.childCount())]

    def loaded(self):
        """Tables with a layer in the project from the chosen environment."""
        return {table for layer, table in loader.geofa_layers(self.project) if loader.in_test(layer) == self.test}

    def sync(self, *args):
        """Ticks and group counts from the project (never adds or removes anything)."""
        loaded = self.loaded()
        self.tree.blockSignals(True)
        try:
            for group_item in self.groups():
                children = self.children(group_item)
                count = 0
                for item in children:
                    state = Qt.CheckState.Checked if item.data(0, ROLE_TABLE) in loaded else Qt.CheckState.Unchecked
                    count += state == Qt.CheckState.Checked
                    item.setCheckState(0, state)
                    item.setData(0, ROLE_STATE, _value(state))
                state = (Qt.CheckState.Checked if count == len(children) else
                         Qt.CheckState.PartiallyChecked if count else Qt.CheckState.Unchecked)
                group_item.setCheckState(0, state)
                group_item.setData(0, ROLE_STATE, _value(state))
                name = group_item.data(0, ROLE_GROUP)
                group_item.setText(0, f"{name} ({len(children)})" + (f" · {count} indlæst" if count else ""))
        finally:
            self.tree.blockSignals(False)

    def _item_changed(self, item, column):
        """A tick the user set: add or remove at once, then show what the project really holds."""
        state = item.checkState(0)
        if item.data(0, ROLE_STATE) == _value(state):
            return  # the text changed, not the tick
        table = item.data(0, ROLE_TABLE)
        try:
            if table:
                (self.add_requested if state == Qt.CheckState.Checked else self.remove_requested).emit([table])
            else:
                self._group_changed(item, state != Qt.CheckState.Unchecked)
        finally:
            self.sync()

    def _group_changed(self, group_item, add):
        """Tick a group: add its layers (those shown, when searching). Untick: remove them."""
        loaded = self.loaded()
        tables = [item.data(0, ROLE_TABLE) for item in self.children(group_item) if not item.isHidden()]
        group = group_item.data(0, ROLE_GROUP)
        if add:
            tables = [table for table in tables if table not in loaded]
            question = f"Tilføj {len(tables)} lag fra {group}? Det tager omkring et sekund pr. lag."
        else:
            tables = [table for table in tables if table in loaded]
            question = f"Fjern {len(tables)} lag fra {group} fra projektet?"
        if len(tables) >= ASK_FROM:
            if QMessageBox.question(self, "GeoFA", question) != QMessageBox.StandardButton.Yes:
                return
        if tables:
            (self.add_requested if add else self.remove_requested).emit(tables)

    def filter(self, text):
        """Show layers whose title, theme code or table holds every word typed (or whose group does)."""
        words = text.lower().split()
        for group_item in self.groups():
            group_hit = bool(words) and all(word in group_item.data(0, ROLE_SEARCH) for word in words)
            shown = 0
            for item in self.children(group_item):
                hit = not words or group_hit or all(word in item.data(0, ROLE_SEARCH) for word in words)
                item.setHidden(not hit)
                shown += hit
            group_item.setHidden(shown == 0)
            group_item.setExpanded(bool(words) and shown > 0)

    def context_menu(self, point):
        item = self.tree.itemAt(point)
        table = item.data(0, ROLE_TABLE) if item is not None else None
        dataset = self.catalogue.get(table) if table else None
        if dataset is None or not dataset.spec_page:
            return
        menu = QMenu(self)
        action = menu.addAction(QgsApplication.getThemeIcon("/mActionHelpContents.svg"), "Åbn specifikationen")
        action.triggered.connect(lambda checked=False: QDesktopServices.openUrl(QUrl(dataset.spec_page)))
        menu.exec(self.tree.viewport().mapToGlobal(point))

    # ------------------------------------------------------------------ mode

    def set_mode(self, mode, can_edit=True):
        """can_edit: a GeoFA login is stored. Without one the panel is a viewer, with no edit button."""
        self.test = mode.test
        self.test_banner.setVisible(mode.test)
        self.edit_button.setVisible(can_edit)
        self.edit_button.blockSignals(True)
        self.edit_button.setChecked(mode.edit)
        self.edit_button.blockSignals(False)
        if mode.edit:
            where = " i testmiljøet" if mode.test else ""
            only = "\nKun lag med »[TEST]« kan redigeres." if mode.test else ""
            self.edit_button.setToolTip(f"Redigering (WFS-T){where} som {mode.username}.{only}\n"
                                        "Klik for kun at vise lagene.")
        else:
            self.edit_button.setToolTip("Lagene kan kun vises.\nKlik for at redigere med dit GeoFA-login (WFS-T).")
        self.sync()

    def cleanup(self):
        """Stop following the project (the plugin is being unloaded)."""
        for signal in (self.project.layersAdded, self.project.layersRemoved):
            try:
                signal.disconnect(self.sync)
            except (TypeError, RuntimeError):
                pass
