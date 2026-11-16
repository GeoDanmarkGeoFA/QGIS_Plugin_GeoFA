"""End-to-end check of the plugin in a real QGIS window. Started by run_e2e.ps1 (QGIS runs it via --code).

Uses GeoFA's production and test environments, reading only, without a login (so the plugin is a
viewer). Writes gui_smoke_<QGIS version>.json with a pass/fail per check to the folder in
GEOFA_E2E_OUT, and closes QGIS.

Steps, with time in between for GeoFA to answer:
 1. add Cykelkrydspunktsstrækninger (5609) and Friluftsliv faciliteter, punkter (5800); check aliases,
    styling and photo links
 2. check ticks, viewer mode, HTML description, live code lists; make 5800's form "older" and run Opdater
 3. re-add 5800 (no duplicate); switch to test; add 5800 from test beside the production one
 4. back to production; untick 5609 in the panel; turn the Aarhus municipality filter on and off
"""
import json
import os
import traceback
from pathlib import Path

from qgis.core import Qgis, QgsDataSourceUri, QgsEditorWidgetSetup, QgsFeatureRequest, QgsProject, QgsSettings
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication
from qgis.utils import iface, plugins

OUT = Path(os.environ.get("GEOFA_E2E_OUT") or Path.cwd())
VERSION = Qgis.QGIS_VERSION.split("-")[0]
STEPS = OUT / f"gui_smoke_steps_{VERSION}.log"
DATA = {"qgis": Qgis.QGIS_VERSION}
CHECKS = {}  # name -> (passed, what was seen); names ending in "(testmiljø)" are warnings only
STATE = {}


def step(text):
    """Log each step as it starts, so a crash shows where it happened."""
    with STEPS.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def check(name, passed, seen=""):
    CHECKS[name] = (bool(passed), str(seen)[:300])


def plugin():
    return plugins.get("geofa")


def project_layers():
    return list(QgsProject.instance().mapLayers().values())


def facility_layer(test=False):
    return next(layer for layer in project_layers()
                if "5800" in layer.name() and layer.name().endswith("[TEST]") == test)


def widget(layer, field):
    setup = layer.editorWidgetSetup(layer.fields().indexOf(field))
    return setup.type(), setup.config()


def dropdown_size(layer, field):
    kind, config = widget(layer, field)
    return len(config.get("map") or []) if kind == "ValueMap" else 0


def code_list_popups():
    """The code list pop-ups shown (then closed)."""
    shown = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w.windowTitle() == "GeoFA – kodelister"]
    texts = [w.text() for w in shown]
    for w in shown:
        w.close()
    return texts


def ticked():
    panel = plugin().panel
    return [item.text(0) for group in panel.groups() for item in panel.children(group)
            if item.checkState(0) == Qt.CheckState.Checked]


def part_add():
    QgsSettings().remove("GeoFA/code_list_problems")  # so a broken list is reported in this run
    plugin().settings.set_value("testmiljo", False)  # start in production, whatever a stopped run left
    plugin().settings.set_value("kommune", "")
    plugin().settings.emit_updated()
    check("plugin loaded", plugin() is not None)
    menu = [action.text() for action in plugin().menu.actions()]
    check("menu: 13 groups and the plugin's items", menu.count("") == 2 and len(menu) == 13 + 2 + 6, menu)
    plugin().panel.show()
    step("add 5609 and 5800")
    plugin().add_tables(["t_5609_cykelkrydspunktsstraekninger"])
    plugin().add_tables(["t_5800_fac_pkt"])
    layers = project_layers()
    check("2 layers added and readable", len(layers) == 2 and all(l.isValid() and l.featureCount() > 0 for l in layers),
          [(l.name(), l.isValid(), l.featureCount()) for l in layers])
    groups = [g.name() for g in QgsProject.instance().layerTreeRoot().children()]
    check("layers placed in their spec groups", set(groups) == {"Vej og trafik", "Sport, fritid og friluftsliv"}, groups)
    alias = facility_layer().fields().field("facil_ty_k").alias()
    check("aliases with the field name", alias == "Facilitettype (facil_ty_k)", alias)
    check("webmap styling (categorised)", facility_layer().renderer().type() == "categorizedSymbol",
          facility_layer().renderer().type())
    source = QgsDataSourceUri(facility_layer().source())
    check("read from the photo-link version", "fkg_foto_gpx_link" in source.param("typename"), source.param("typename"))
    sample = list(facility_layer().getFeatures(QgsFeatureRequest().setLimit(300)))
    photos = sum(1 for feature in sample if str(feature["geofafoto"] or "").startswith("https://"))
    check("photo links in the objects", photos > 0, f"{photos} of {len(sample)}")


def part_update_forms():
    layer = facility_layer()
    check("panel ticks the added layers", sorted(ticked()) == sorted(l.name() for l in project_layers()), ticked())
    check("viewer without a login: no editing shown",
          not plugin().login_action.isVisible() and plugin().panel.login_button.isHidden())
    kind, config = widget(layer, "lang_beskr")
    check("lang_beskr shown as HTML", kind == "TextEdit" and config.get("UseHtml"), config)
    size = dropdown_size(layer, "facil_ty_k")
    check("facility types read live from GeoFA", size > 100, size)
    check("authorities read live from GeoFA", dropdown_size(layer, "cvr_kode") > 90, dropdown_size(layer, "cvr_kode"))
    DATA["code_list_popups"] = code_list_popups()  # GeoFA's unreadable lists (information, not a check)
    step("make the form older and run Opdater")
    from geofa import loader  # the installed plugin's package
    STATE["loader"] = loader
    layer.setCustomProperty(loader.FORM_PROPERTY, "older")
    layer.setEditorWidgetSetup(layer.fields().indexOf("facil_ty_k"), QgsEditorWidgetSetup("TextEdit", {}))
    check("older form found", len(loader.outdated_layers()) == 1, len(loader.outdated_layers()))
    plugin().update_forms()


def part_switch_to_test():
    loader = STATE["loader"]
    check("Opdater brings the form up to date", not loader.outdated_layers(), len(loader.outdated_layers()))
    check("Opdater fills the dropdowns again", dropdown_size(facility_layer(), "facil_ty_k") > 100,
          dropdown_size(facility_layer(), "facil_ty_k"))
    DATA["code_list_popups_after_update"] = code_list_popups()
    plugin().add_tables(["t_5800_fac_pkt"])
    check("adding a layer twice doesn't duplicate it", len(project_layers()) == 2, len(project_layers()))
    step("switch to test")
    plugin().settings.set_value("testmiljo", True)
    plugin().settings.emit_updated()
    check("test: menu says TESTMILJØ", "TESTMILJØ" in plugin().menu.title(), plugin().menu.title())
    check("test: TEST strip in the panel", not plugin().panel.test_banner.isHidden())
    check("test: production layers stay", all("geofa.geodanmark.dk" in l.source() for l in project_layers()),
          [l.name() for l in project_layers()])
    step("add 5800 from test")
    plugin().add_tables(["t_5800_fac_pkt"])
    test_layers = [l for l in project_layers() if l.name().endswith("[TEST]")]
    check("test layer added beside the production one (testmiljø)",
          len(test_layers) == 1 and test_layers[0].isValid() and "geofa-test" in test_layers[0].source(),
          [(l.name(), l.isValid()) for l in project_layers()])


def part_back_to_production():
    test_layers = [l for l in project_layers() if l.name().endswith("[TEST]")]
    if test_layers:
        size = dropdown_size(test_layers[0], "facil_ty_k")
        check("test layer's code lists from the test environment (testmiljø)", size > 100, size)
    DATA["code_list_popups_test"] = code_list_popups()
    step("back to production")
    plugin().settings.set_value("testmiljo", False)
    plugin().settings.emit_updated()
    check("production: no TEST strip", plugin().panel.test_banner.isHidden())
    check("layers stay in their environment",
          sum(1 for l in project_layers() if l.name().endswith("[TEST]")) == len(test_layers),
          [l.name() for l in project_layers()])
    step("untick 5609 in the panel")
    panel = plugin().panel
    item = next(i for g in panel.groups() for i in panel.children(g) if "5609" in i.text(0))
    item.setCheckState(0, Qt.CheckState.Unchecked)
    names = [l.name() for l in project_layers()]
    check("unticking removes the layer", not any("5609" in name for name in names), names)
    check("…and only that layer", any("5800" in name for name in names), names)
    step("municipality filter: Aarhus")
    everywhere = facility_layer().featureCount()
    plugin().settings.set_value("kommune", "0751")
    plugin().settings.emit_updated()
    filtered = facility_layer().featureCount()
    check("municipality filter reaches the layers already added",
          "Intersects" in QgsDataSourceUri(facility_layer().source()).param("filter"))
    check("only objects in Aarhus Kommune", 0 < filtered < everywhere, f"{filtered} of {everywhere}")
    check("panel shows the filter", not plugin().panel.area_filter.isHidden(), plugin().panel.area_filter.text())
    plugin().settings.set_value("kommune", "")
    plugin().settings.emit_updated()
    check("filter off again", facility_layer().featureCount() == everywhere, facility_layer().featureCount())


def finish():
    step("write result")
    DATA["checks"] = {name: {"passed": passed, "seen": seen} for name, (passed, seen) in CHECKS.items()}
    (OUT / f"gui_smoke_{VERSION}.json").write_text(json.dumps(DATA, indent=1, ensure_ascii=False), encoding="utf-8")
    step("clear and exit")
    QgsProject.instance().setDirty(False)
    QgsProject.instance().clear()
    iface.actionExit().trigger()


# Each part runs from QGIS's own event loop, with time between parts for GeoFA to answer
PLAN = [(3000, part_add), (8000, part_update_forms), (8000, part_switch_to_test), (8000, part_back_to_production)]


def run_part(index):
    step(f"part {index + 1}: {PLAN[index][1].__name__}")
    try:
        PLAN[index][1]()
    except Exception:  # noqa: BLE001 - reported in the result
        DATA["error"] = traceback.format_exc()
        finish()
        return
    if index + 1 < len(PLAN):
        QTimer.singleShot(PLAN[index + 1][0], lambda: run_part(index + 1))
    else:
        finish()


def start():
    OUT.mkdir(parents=True, exist_ok=True)
    STEPS.write_text("", encoding="utf-8")
    run_part(0)


QTimer.singleShot(PLAN[0][0], start)
