"""Can every layer in the catalogue be read from GeoFA, the way the plugin reads it without a login?

    python-qgis.bat tools/layers_live.py [production|test|both]

Loads each dataset with QGIS's WFS provider, from the source the plugin gives it, and checks that
the layer is valid, has the geometry type and the fields the plugin's form expects, and that its
objects can be read. Writes dev/reports/layers_live.json, with the number of public objects per
layer (without a login GeoFA shows only those, so many layers are empty). Exits with 1 when a
production layer fails; GeoFA's test environment isn't always available, so its failures are only
reported.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

os.environ["QGIS_CUSTOM_CONFIG_PATH"] = tempfile.mkdtemp(prefix="geofa_layers_live_")  # a throwaway profile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsFeatureRequest, QgsVectorLayer, QgsWkbTypes  # noqa: E402

from geofa_plugin import loader  # noqa: E402
from geofa_plugin.catalogue import Catalogue  # noqa: E402
from tools.geofa_spec import PHOTO_FIELD  # noqa: E402

ENVIRONMENTS = {"production": False, "test": True}


def form_fields(dataset):
    """The fields the dataset's form is made for."""
    configuration = ElementTree.parse(dataset.style_path).getroot().find("fieldConfiguration")
    return [field.get("name") for field in configuration.findall("field")]


def check(dataset, test, log):
    """(number of public objects or None, problem or None) for one dataset in one environment."""
    log.clear()
    mode = loader.Mode(edit=False, test=test, username="")
    layer = QgsVectorLayer(loader.layer_source(dataset.table, mode), dataset.title, "WFS")
    if not layer.isValid():
        return None, "QGIS can't read the layer: " + (" | ".join(log) or "no message")
    problems = []
    if dataset.geometry and layer.geometryType() != QgsWkbTypes.geometryType(QgsWkbTypes.parseType(dataset.geometry)):
        problems.append(f"geometry is {QgsWkbTypes.displayString(layer.wkbType())}, the form is for {dataset.geometry}")
    missing = [name for name in form_fields(dataset) if layer.fields().indexOf(name) < 0
               # the photo links come only with GeoFA's photo-link version of the table
               and not (PHOTO_FIELD.match(name) and loader.environment(mode) not in dataset.photo_environments)]
    if missing:
        problems.append(f"fields in the form but not in GeoFA: {', '.join(missing)}")
    list(layer.getFeatures(QgsFeatureRequest().setLimit(1)))
    if layer.dataProvider().hasErrors():
        problems.append("reading objects failed: " + " | ".join(layer.dataProvider().errors()))
    return layer.featureCount(), "; ".join(problems) or None


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    environments = ENVIRONMENTS if which == "both" else {which: ENVIRONMENTS[which]}
    app = QgsApplication([], False)
    app.initQgis()
    log = []
    QgsApplication.messageLog().messageReceived.connect(
        lambda message, tag, level: log.append(message) if tag == "WFS" else None)
    datasets = Catalogue().datasets()
    report, failed = [], []
    for environment, test in environments.items():
        for number, dataset in enumerate(datasets, 1):
            objects, problem = check(dataset, test, log)
            entry = {"environment": environment, "table": dataset.table, "title": dataset.title,
                     "group": dataset.group, "objects": objects, "problem": problem}
            report.append(entry)
            print(f"{environment} {number:2}/{len(datasets)} {dataset.table}: "
                  f"{problem or f'ok, {objects} public objects'}", flush=True)
            if problem:
                failed.append(entry)
    out = ROOT / "dev" / "reports" / "layers_live.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(report)} layers read, {len(failed)} failed -> {out}")
    for entry in failed:
        print(f"  {entry['environment']}: {entry['title']} ({entry['group']}): {entry['problem']}")
    app.exitQgis()
    return 1 if any(entry["environment"] == "production" for entry in failed) else 0


if __name__ == "__main__":
    sys.exit(main())
