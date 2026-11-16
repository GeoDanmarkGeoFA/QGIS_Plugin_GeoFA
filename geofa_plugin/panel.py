# -*- coding: utf-8 -*-
"""The GeoFA panel: every GeoFA dataset in the spec's groups, with search and layer info."""
import html
import os

from qgis.core import QgsApplication
from qgis.gui import QgsDockWidget, QgsFilterLineEdit
from qgis.PyQt.QtCore import QSortFilterProxyModel, Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QFont, QPixmap, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QSizePolicy,
                                 QToolButton, QTreeView, QVBoxLayout, QWidget)

TABLE_ROLE = Qt.ItemDataRole.UserRole + 1
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 2
ASK_BEFORE_ADDING = 4  # adding layers takes about a second each

# GeoFA's colours: the green of the GeoFA icon, and GeoDanmark's dark green and orange (geodanmark.dk)
GEOFA_GREEN = "#93c257"
GEODANMARK_GREEN = "#4c5f35"
GEODANMARK_ORANGE = "#fc8833"
FONT = "font-family:'Segoe UI',Arial,sans-serif"
ICON = os.path.join(os.path.dirname(__file__), "icon.png")


class Banner(QFrame):
    """The panel's header: the GeoFA icon and name on GeoDanmark green, with a GeoFA-green line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("geofaBanner")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"#geofaBanner {{ background:{GEODANMARK_GREEN}; border-bottom:3px solid {GEOFA_GREEN}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        logo = QLabel()
        pixmap = QPixmap(ICON)
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToHeight(30, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo)
        title = QLabel(f"<span style=\"{FONT};font-size:15px;font-weight:600;color:#ffffff\">GeoFA</span><br>"
                       f"<span style=\"{FONT};font-size:10px;color:#dcebc8\">Geografiske Fagdata i GeoDanmark</span>")
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


def dataset_tooltip(dataset):
    lines = [f"<b>{html.escape(dataset.title)}</b>"]
    if dataset.purpose:
        lines.append(html.escape(dataset.purpose))
    if dataset.pending:
        lines.append("<i>Specifikationen for dette lag kommer snart.</i>")
    lines.append("Dobbeltklik for at tilføje laget. Højreklik for specifikationen.")
    return "<p>" + "<br><br>".join(lines) + "</p>"


class _SearchFilter(QSortFilterProxyModel):
    """Shows datasets whose title, theme code or table holds every word typed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.words = []
        self.setRecursiveFilteringEnabled(True)  # a group shows when one of its datasets matches

    def set_text(self, text):
        self.words = text.lower().split()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        if not self.words:
            return True
        text = self.sourceModel().index(row, 0, parent).data(SEARCH_ROLE) or ""
        return all(word in text for word in self.words)


class GeoFAPanel(QgsDockWidget):
    add_requested = pyqtSignal(list)  # tables
    edit_toggled = pyqtSignal(bool)
    settings_requested = pyqtSignal()

    def __init__(self, catalogue, parent=None):
        super().__init__("GeoFA", parent)
        self.setObjectName("GeoFAPanel")
        self.catalogue = catalogue
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
        layout.setContentsMargins(4, 4, 4, 4)
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

        self.model = QStandardItemModel(self)
        for group, datasets in catalogue.groups:
            group_item = QStandardItem(group)
            font = QFont(group_item.font())
            font.setBold(True)
            group_item.setFont(font)
            group_item.setData("", SEARCH_ROLE)  # groups show only through their datasets
            for dataset in datasets:
                item = QStandardItem(dataset.title)
                item.setData(dataset.table, TABLE_ROLE)
                item.setData(dataset.search_text(), SEARCH_ROLE)
                item.setToolTip(dataset_tooltip(dataset))
                group_item.appendRow(item)
            self.model.appendRow(group_item)
        self.proxy = _SearchFilter(self)
        self.proxy.setSourceModel(self.model)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.doubleClicked.connect(self.double_clicked)
        layout.addWidget(self.tree)
        self.setWidget(contents)

    def filter(self, text):
        self.proxy.set_text(text)
        if text.strip():
            self.tree.expandAll()
        else:
            self.tree.collapseAll()

    def set_mode(self, mode):
        self.test_banner.setVisible(mode.test)
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

    def _table(self, index):
        return index.data(TABLE_ROLE) if index.isValid() else None

    def _group_tables(self, index):
        """The tables shown under a group (respecting the search)."""
        return [self._table(self.proxy.index(row, 0, index)) for row in range(self.proxy.rowCount(index))]

    def double_clicked(self, index):
        table = self._table(index)
        if table:
            self.add_requested.emit([table])

    def context_menu(self, point):
        index = self.tree.indexAt(point)
        if not index.isValid():
            return
        menu = QMenu(self)
        table = self._table(index)
        selected = [t for t in (self._table(i) for i in self.tree.selectionModel().selectedRows()) if t]
        if table:
            dataset = self.catalogue.get(table)
            if len(selected) > 1 and table in selected:
                self._action(menu, f"Tilføj {len(selected)} valgte lag til kortet", lambda: self.add_tables(selected))
            else:
                self._action(menu, "Tilføj til kortet", lambda: self.add_requested.emit([table]))
            if dataset.spec_page:
                self._action(menu, "Åbn specifikationen", lambda: QDesktopServices.openUrl(QUrl(dataset.spec_page)))
        else:
            tables = self._group_tables(index)
            self._action(menu, f"Tilføj alle {len(tables)} lag i gruppen", lambda: self.add_tables(tables))
        menu.exec(self.tree.viewport().mapToGlobal(point))

    @staticmethod
    def _action(menu, text, slot):
        menu.addAction(text).triggered.connect(lambda checked=False: slot())

    def add_tables(self, tables):
        if len(tables) >= ASK_BEFORE_ADDING:
            answer = QMessageBox.question(
                self, "GeoFA", f"Tilføj {len(tables)} lag? Det tager omkring et sekund pr. lag.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.add_requested.emit(tables)
