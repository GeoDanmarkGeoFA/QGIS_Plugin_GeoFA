"""Open QGIS with the plugin, its panel and a GeoFA layer, then close it as a user would.

Started by run_e2e.ps1 (QGIS runs it via --code), which checks that QGIS exits without a crash
within 90 s of being started. Logs to exit_check_<QGIS version>.log in the folder in GEOFA_E2E_OUT.
"""
import os
from pathlib import Path

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import QTimer
from qgis.utils import iface, plugins

OUT = Path(os.environ.get("GEOFA_E2E_OUT") or Path.cwd())
LOG = OUT / f"exit_check_{Qgis.QGIS_VERSION.split('-')[0]}.log"


def log(text):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def close():
    log("closing")
    QgsProject.instance().setDirty(False)  # no "save project?" question
    iface.mainWindow().close()
    log("close returned")


def start():
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    plugin = plugins.get("geofa")
    log(f"plugin loaded: {plugin is not None}")
    plugin.panel.show()
    plugin.add_tables(["t_5800_fac_pkt"])  # a WFS layer, and code lists being read, while QGIS closes
    log("layer added")
    QTimer.singleShot(8000, close)


QTimer.singleShot(3000, start)
