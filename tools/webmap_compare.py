"""Side-by-side contact sheets: our QML on production WFS (left) vs the production WMS, which the webmap uses (right).

    python-qgis-ltr.bat tools/webmap_compare.py            (all datasets with objects)
    python-qgis-ltr.bat tools/webmap_compare.py t_5609_cykelkrydspunktsstraekninger,t_5800_fac_pkt

Writes dev/reports/compare/sheet_NN.png (all datasets) or pick_NN.png (the datasets named), 8 layers
per sheet, and extents.json (cached view per table).
Read-only, anonymous production requests.
"""
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")  # Windows: the offscreen platform finds no fonts otherwise
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = str(REPO / "dev" / "qgis-profile" / "check")

import geofa_spec as spec  # noqa: E402
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsMapRendererParallelJob,  # noqa: E402
                       QgsMapSettings, QgsRectangle, QgsSettings, QgsVectorLayer)
from qgis.PyQt.QtCore import QRect, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402

OUT = REPO / "dev" / "reports" / "compare"
SQL = "https://geofa.geodanmark.dk/api/v2/sql/fkg"
OWS = "https://geofa.geodanmark.dk/ows/fkg/fkg"
WEBMAP_WMS = "https://geofa-kort.geodanmark.dk/api/wms/fkg/fkg"  # what the webmap itself requests
SIZE = 360
PER_SHEET = 8


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "geofa-layer-check"})
    with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
        return r.read()


def extent_for(table):
    """A view around one object: 1.5 km for points/lines, the object plus a margin for areas."""
    q = (f"SELECT ST_XMin(b) AS x0, ST_YMin(b) AS y0, ST_XMax(b) AS x1, ST_YMax(b) AS y1, "
         f"GeometryType(g) AS t FROM (SELECT geometri AS g, ST_Envelope(geometri) AS b FROM fkg.{table} "
         f"WHERE geometri IS NOT NULL LIMIT 1) s")
    rows = json.loads(get(f"{SQL}?q={urllib.parse.quote(q)}"))["features"]
    if not rows:
        return None
    p = rows[0]["properties"]
    cx, cy = (p["x0"] + p["x1"]) / 2, (p["y0"] + p["y1"]) / 2
    half = max(750.0, (p["x1"] - p["x0"]) * 0.75, (p["y1"] - p["y0"]) * 0.75) if "POLYGON" in p["t"] else 750.0
    return [cx - half, cy - half, cx + half, cy + half]


def ours(table, ext):
    uri = (f"pagingEnabled='true' restrictToRequestBBOX='1' srsname='EPSG:25832' typename='fkg:fkg.{table}' "
           f"url='{OWS}' version='1.1.0'")
    layer = QgsVectorLayer(uri, table, "WFS")
    if not layer.isValid():
        return None
    layer.loadNamedStyle(str(REPO / "geofa_plugin" / "layers" / "styles" / f"{table}.qml"))
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    settings.setExtent(QgsRectangle(*ext))
    settings.setOutputSize(QSize(SIZE, SIZE))
    settings.setBackgroundColor(QColor("white"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def webmap(table, ext):
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": f"fkg.{table}", "STYLES": "",
              "SRS": "EPSG:25832", "BBOX": ",".join(f"{v:.2f}" for v in ext), "WIDTH": SIZE, "HEIGHT": SIZE,
              "FORMAT": "image/png", "TRANSPARENT": "FALSE", "BGCOLOR": "0xFFFFFF"}
    image = QImage()
    try:
        image.loadFromData(get(f"{WEBMAP_WMS}?{urllib.parse.urlencode(params)}"))
    except Exception as error:  # noqa: BLE001 - shown on the sheet
        print(f"{table}: WMS failed: {error}")
    return image


def main():
    app = QgsApplication([], False)
    app.initQgis()
    QgsSettings().setValue("svg/searchPathsForSVG", [str(REPO / "geofa_plugin" / "layers" / "symbols")])
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "extents.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    counts = spec.read_json(spec.SPEC / "prod_counts.json")
    datasets = [d for d in spec.datasets() if d["table"] and counts.get(d["table"])]
    views = {}
    if len(sys.argv) > 1:
        # "table" or "table@label@x0:y0:x1:y1" for a chosen view
        wanted = []
        for item in sys.argv[1].split(","):
            table, *view = item.split("@")
            wanted.append(table)
            if view:
                views.setdefault(table, []).append((view[0], [float(v) for v in view[1].split(":")]))
        datasets = [dict(d, title=f"{d['title']} – {label}" if label else d["title"], view=ext)
                    for d in datasets if d["table"] in wanted for label, ext in views.get(d["table"], [(None, None)])]
    panels = []
    for d in datasets:
        table = d["table"]
        if d.get("view"):
            panels.append((d["title"], ours(table, d["view"]), webmap(table, d["view"])))
            continue
        if table not in cache:
            try:
                cache[table] = extent_for(table)
            except Exception as error:  # noqa: BLE001
                print(f"{table}: no extent ({error})")
                cache[table] = None
            cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        ext = cache[table]
        if not ext:
            continue
        panels.append((d["title"], ours(table, ext), webmap(table, ext)))
        print("done", table, flush=True)
    tag = "sheet" if len(sys.argv) == 1 else "pick"
    for n in range(0, len(panels), PER_SHEET):
        chunk = panels[n:n + PER_SHEET]
        title_h, gap = 22, 12
        sheet = QImage(2 * (2 * SIZE + gap) + gap, ((len(chunk) + 1) // 2) * (SIZE + title_h + gap) + gap,
                       QImage.Format.Format_ARGB32)
        sheet.fill(QColor("#dddddd"))
        p = QPainter(sheet)
        p.setFont(QFont("Arial", 10))
        for i, (title, a, b) in enumerate(chunk):
            x = gap + (i % 2) * (2 * SIZE + gap)
            y = gap + (i // 2) * (SIZE + title_h + gap)
            p.setPen(QColor("black"))
            p.drawText(QRect(x, y, 2 * SIZE, title_h), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"{title}   (QGIS | webmap)")
            for k, img in enumerate((a, b)):
                if img is not None and not img.isNull():
                    p.drawImage(x + k * SIZE, y + title_h, img)
            p.setPen(QColor("#888888"))
            p.drawLine(x + SIZE, y + title_h, x + SIZE, y + title_h + SIZE)
        p.end()
        target = OUT / f"{tag}_{n // PER_SHEET + 1:02d}.png"
        sheet.save(str(target))
        print("wrote", target.name)
    app.exitQgis()


if __name__ == "__main__":
    main()
