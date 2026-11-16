"""Build dev/preview/preview.qgz: generated layers (production WFS, anonymous, read-only) with their QMLs.

    python-qgis.bat tools/make_preview.py t_5800_fac_pkt,t_5710_born_skole_dis,t_5026_regnbed
    python-qgis.bat tools/make_preview.py all t_5800_fac_pkt,t_5710_born_skole_dis   (all layers, two switched on)
Then open it in the preview profile:
    qgis.bat --profiles-path dev/qgis-profile --profile preview --project dev/preview/preview.qgz
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "dev" / "qgis-profile" / "profiles" / "preview"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = str(PROFILE)

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer,  # noqa: E402
                       QgsRectangle, QgsReferencedRectangle, QgsSettings, QgsVectorLayer)

LAYERS = REPO / "geofa_plugin" / "layers"
app = QgsApplication([], False)
app.initQgis()
# The preview profile finds the plugin's symbols the same way the plugin will
QgsSettings().setValue("svg/searchPathsForSVG", [str(LAYERS / "symbols")])

catalogue = json.loads((LAYERS / "catalogue.json").read_text(encoding="utf-8"))
# "all" adds every dataset; the second argument names the ones switched on
tables = [d["table"] for g in catalogue["groups"] for d in g["datasets"]] if sys.argv[1] == "all" else sys.argv[1].split(",")
visible = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set(tables)
project = QgsProject.instance()
project.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
root = project.layerTreeRoot()
for group in catalogue["groups"]:
    wanted = [d for d in group["datasets"] if d["table"] in tables]
    if not wanted:
        continue
    node = root.addGroup(group["name"])
    for d in wanted:
        uri = (f"pagingEnabled='true' restrictToRequestBBOX='1' srsname='EPSG:25832' typename='fkg:fkg.{d['table']}' "
               f"url='https://geofa.geodanmark.dk/ows/fkg/fkg' version='1.1.0'")
        layer = QgsVectorLayer(uri, d["title"], "WFS")
        layer.loadNamedStyle(str(LAYERS / d["style"]))
        project.addMapLayer(layer, False)
        node.addLayer(layer).setItemVisibilityChecked(d["table"] in visible)
    node.setExpanded(any(d["table"] in visible for d in wanted))
osm = QgsRasterLayer("type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0", "OpenStreetMap", "wms")
project.addMapLayer(osm, False)
root.addLayer(osm)
project.viewSettings().setDefaultViewExtent(
    QgsReferencedRectangle(QgsRectangle(570000, 6218000, 582000, 6228000), QgsCoordinateReferenceSystem("EPSG:25832")))
target = REPO / "dev" / "preview" / ("preview_all.qgz" if sys.argv[1] == "all" else "preview.qgz")
target.parent.mkdir(parents=True, exist_ok=True)
print("written:", project.write(str(target)), target)
app.exitQgis()
