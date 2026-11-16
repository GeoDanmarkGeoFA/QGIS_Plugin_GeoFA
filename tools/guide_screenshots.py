"""Screenshots for the Danish guide (geofa_plugin/GeoFA_plugin_vejledning.md), taken in a real
QGIS window. Started by tools/guide_screenshots.ps1 (QGIS runs it via --code).

Reads GeoFA's production environment anonymously, as any user without a login would. Saves the
images to the folder in GEOFA_GUIDE_OUT (geofa_plugin/Vejledning), logs each step to
guide_screenshots.log there, and closes QGIS.
"""
import os
import traceback
from pathlib import Path

from qgis.core import QgsCoordinateReferenceSystem, QgsFeatureRequest, QgsProject, QgsRectangle
from qgis.gui import QgsAttributeDialog, QgsAttributeEditorContext
from qgis.PyQt.QtCore import QPoint, QRect, Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication, QDockWidget, QTabWidget, QWidget
from qgis.utils import iface, plugins

OUT = Path(os.environ.get("GEOFA_GUIDE_OUT") or Path.cwd())
LOG = OUT / "guide_screenshots.log"
AARHUS = QgsRectangle(569000, 6214500, 581000, 6227500)  # EPSG:25832, the city and its harbour
TABLES = ["t_5802_fac_li", "t_5800_fac_pkt", "t_5607_ladefacilitet"]  # two groups, lines and points
KEEP_DOCKS = {"Layers", "GeoFAPanel"}  # the Browser panel would show this computer's drives
STATE = {}


def log(text):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def plugin():
    return plugins.get("geofa")


def save(widget, name, rect=None):
    QApplication.processEvents()
    image = widget.grab(rect) if rect is not None else widget.grab()
    image.save(str(OUT / name))
    log(f"saved {name} ({image.width()}x{image.height()})")


def layer(code):
    return next(l for l in QgsProject.instance().mapLayers().values() if f"({code})" in l.name())


def expand_groups(*tables):
    panel = plugin().panel
    for group in panel.groups():
        group.setExpanded(any(panel.children(group)[i].data(0, Qt.ItemDataRole.UserRole + 1) in tables
                              for i in range(len(panel.children(group)))))


def part_setup():
    settings = plugin().settings
    settings.set_value("testmiljo", False)
    settings.set_value("kommune", "")
    settings.emit_updated()
    window = iface.mainWindow()
    window.showNormal()
    window.resize(1360, 820)
    window.move(40, 40)
    window.raise_()
    for dock in window.findChildren(QDockWidget):
        if dock.objectName() not in KEEP_DOCKS:
            dock.hide()
    plugin().panel.show()
    plugin().add_tables(TABLES)
    canvas = iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    canvas.setExtent(AARHUS)
    canvas.refresh()
    expand_groups(*TABLES)
    iface.setActiveLayer(layer("5800"))


def part_window_and_panel():
    iface.messageBar().clearWidgets()  # e.g. QGIS's own notice about an installed font
    save(iface.mainWindow(), "qgis.png")
    panel = plugin().panel
    save(panel, "panel.png")


def part_form():
    facilities = layer("5800")
    request = QgsFeatureRequest().setFilterRect(AARHUS).setLimit(400)
    feature = next((f for f in facilities.getFeatures(request) if str(f["geofafoto"] or "").startswith("https://")),
                   None) or next(facilities.getFeatures(request))
    dialog = QgsAttributeDialog(facilities, feature, False, iface.mainWindow(), True, QgsAttributeEditorContext())
    dialog.resize(620, 560)
    dialog.show()
    QApplication.processEvents()
    tabs = dialog.findChild(QTabWidget)
    names = [tabs.tabText(i) for i in range(tabs.count())]
    log(f"form tabs: {names}")
    tabs.setCurrentIndex(1)  # the dataset's own fields, with its dropdowns
    save(dialog, "formular.png")
    photo_tab = next((i for i, name in enumerate(names) if name.startswith("Fotos") and tabs.isTabVisible(i)), None)
    if photo_tab is not None:
        tabs.setCurrentIndex(photo_tab)
        dialog.resize(560, 330)  # a few links: no need for the tall form
        save(dialog, "fotos.png")
    dialog.close()


def part_settings_and_menu():
    from geofa.settings_window import SettingsDialog
    dialog = SettingsDialog(plugin().settings, iface.mainWindow())
    dialog.show()
    QApplication.processEvents()
    # An example login as a user would type it; the dialog is cancelled, so nothing is stored
    dialog.form.username_edit.setText("kom101")
    dialog.form.password_edit.setText("eksempel")
    dialog.form.check_box_wfst.setChecked(True)
    save(dialog, "indstillinger.png")
    dialog.reject()
    menu = plugin().menu
    menu.popup(iface.mainWindow().mapToGlobal(QPoint(300, 60)))
    QApplication.processEvents()
    save(menu, "menu.png")
    menu.close()


def part_municipality():
    plugin().settings.set_value("kommune", "0751")
    plugin().settings.emit_updated()
    expand_groups()
    panel = plugin().panel
    top = panel.area_filter.mapTo(panel, QPoint(0, 0)).y() + panel.area_filter.height() + 8
    STATE["municipality_rect"] = QRect(0, 0, panel.width(), top)


def part_municipality_shot():
    save(plugin().panel, "kommune.png", STATE["municipality_rect"])
    plugin().settings.set_value("kommune", "")
    plugin().settings.emit_updated()


def part_login_button():
    """The person button as a user with a stored login sees it (shown only, no login is used)."""
    from geofa.loader import Mode
    panel = plugin().panel
    panel.set_mode(Mode(edit=False, test=False, username="kom101"), can_edit=True)
    QApplication.processEvents()
    bottom = panel.search.mapTo(panel, QPoint(0, 0)).y() + panel.search.height() + 10
    save(panel, "login.png", QRect(0, 0, panel.width(), bottom))
    plugin().update_environment_label()


def widgets_of_class(class_name):
    """The main window's widgets of a Qt class (found by name: the Python classes don't always match)."""
    return [w for w in iface.mainWindow().findChildren(QWidget) if w.metaObject().className() == class_name]


def part_locator():
    """QGIS's search bar with GeoFA layers as results."""
    window = iface.mainWindow()
    window.activateWindow()  # the result list closes when QGIS loses focus
    window.raise_()
    iface.locatorSearch("geofa distrikt")


def part_locator_shot():
    """The result list (sized to its results) stacked on the search box, without the rest of the status bar."""
    from qgis.PyQt.QtCore import QPointF
    from qgis.PyQt.QtGui import QColor, QPainter, QPixmap
    from qgis.PyQt.QtWidgets import QTreeView
    window = iface.mainWindow()
    locator = widgets_of_class("QgsLocatorWidget")[0]
    popup = widgets_of_class("QgsFloatingWidget")[0]
    if not popup.isVisible():
        popup.show()  # it closes when QGIS isn't the active window
    results = popup.findChild(QTreeView)
    rows = results.model().rowCount()
    log(f"results: {rows} rows")
    last = results.visualRect(results.model().index(rows - 1, 0))
    popup.resize(popup.width(), last.bottom() + 2 * results.frameWidth() + 6)
    QApplication.processEvents()
    results.resizeColumnToContents(0)  # QGIS sets a narrower column, which cuts the results with "…"
    QApplication.processEvents()
    top = popup.grab()
    bottom = locator.grab()
    ratio = top.devicePixelRatio()
    sheet = QPixmap(top.width(), top.height() + bottom.height() + int(4 * ratio))
    sheet.setDevicePixelRatio(ratio)
    sheet.fill(QColor("white"))
    painter = QPainter(sheet)
    painter.drawPixmap(QPointF(0, 0), top)
    painter.drawPixmap(QPointF(0, top.height() / ratio + 4), bottom)
    painter.end()
    sheet.save(str(OUT / "soegefelt.png"))
    log(f"saved soegefelt.png ({sheet.width()}x{sheet.height()})")
    locator.search("")
    window.setFocus()


def part_test_environment():
    """The test environment: the panel's strip, and a [TEST] layer beside the production one."""
    plugin().settings.set_value("testmiljo", True)
    plugin().settings.emit_updated()
    plugin().add_tables(["t_5800_fac_pkt"])
    expand_groups("t_5800_fac_pkt")


def part_test_environment_shot():
    window = iface.mainWindow()
    layers = next(d for d in window.findChildren(QDockWidget) if d.objectName() == "Layers")
    window.resizeDocks([layers], [430], Qt.Orientation.Horizontal)  # room for "… (5800) [TEST]"
    # Only groups and layers in the layer panel (no legends), so the [TEST] layer shows beside the others
    view = iface.layerTreeView()
    view.collapseAllNodes()
    for group in QgsProject.instance().layerTreeRoot().findGroups():
        view.setExpanded(view.node2index(group), True)
    QApplication.processEvents()
    tree_bottom = view.mapTo(layers, QPoint(0, 0)).y() + view.sizeHintForRow(0) * 7 + 8
    panel = plugin().panel
    strip_bottom = panel.search.mapTo(panel, QPoint(0, 0)).y() + panel.search.height() + 10
    left = layers.grab(QRect(0, 0, layers.width(), tree_bottom))
    right = panel.grab(QRect(0, 0, panel.width(), strip_bottom))
    from qgis.PyQt.QtCore import QPointF
    from qgis.PyQt.QtGui import QColor, QPainter, QPixmap
    ratio = left.devicePixelRatio()
    gap = 12  # between the two panels, in screen points
    width = left.width() / ratio + gap + right.width() / ratio
    sheet = QPixmap(int(width * ratio), max(left.height(), right.height()))
    sheet.setDevicePixelRatio(ratio)
    sheet.fill(QColor("white"))
    painter = QPainter(sheet)
    painter.drawPixmap(QPointF(0, 0), left)
    painter.drawPixmap(QPointF(left.width() / ratio + gap, 0), right)
    painter.end()
    sheet.save(str(OUT / "testmiljoe.png"))
    log(f"saved testmiljoe.png ({sheet.width()}x{sheet.height()})")
    plugin().settings.set_value("testmiljo", False)
    plugin().settings.emit_updated()


def finish():
    log("clear and exit")
    QgsProject.instance().setDirty(False)
    QgsProject.instance().clear()
    iface.actionExit().trigger()


# Each part runs from QGIS's own event loop, with time between parts for GeoFA to answer and the map to draw
PLAN = [(3000, part_setup), (15000, part_window_and_panel), (2000, part_form), (2000, part_settings_and_menu),
        (2000, part_municipality), (6000, part_municipality_shot), (2000, part_login_button),
        (2000, part_locator), (2500, part_locator_shot), (2000, part_test_environment),
        (8000, part_test_environment_shot)]


def run_part(index):
    log(f"part {index + 1}: {PLAN[index][1].__name__}")
    try:
        PLAN[index][1]()
    except Exception:  # noqa: BLE001 - written to the log
        log(traceback.format_exc())
        finish()
        return
    if index + 1 < len(PLAN):
        QTimer.singleShot(PLAN[index + 1][0], lambda: run_part(index + 1))
    else:
        finish()


def start():
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    run_part(0)


QTimer.singleShot(PLAN[0][0], start)
