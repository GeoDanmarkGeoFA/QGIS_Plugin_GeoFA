# -*- coding: utf-8 -*-
"""The plugin's own "Om pluginet" dialog: version, what it does, and where to read more."""
import configparser
import os

from qgis.PyQt.QtWidgets import QMessageBox

PLUGIN_DIR = os.path.dirname(__file__)
GUIDE_URL = "https://github.com/GeoDanmarkGeoFA/QGIS_Plugin_GeoFA/blob/main/geofa_plugin/GeoFA_plugin_vejledning.md"
REPOSITORY_URL = "https://github.com/GeoDanmarkGeoFA/QGIS_Plugin_GeoFA"
ISSUES_URL = "https://github.com/GeoDanmarkGeoFA/QGIS_Plugin_GeoFA/issues"
SPEC_URL = "https://confluence.kds.dk/display/GS/GeoFA-specifikation"
GEOFA_URL = "https://www.geodanmark.dk/home/vejledninger/geofa/"
SUPPORT_EMAIL = "support@geopartner.dk"


def plugin_version():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
    return parser.get("general", "version", fallback="")


def about_text(dataset_count):
    return (
        f"<h3>GeoFA-plugin {plugin_version()}</h3>"
        f"<p>Pluginet henter GeoFA's {dataset_count} datasæt ind i QGIS med samme grupper, navne, felter og "
        "kodelister som GeoFA-specifikationen, og med symboler som i GeoFA's webkort. Alle kan se lagenes "
        "offentlige objekter; med et GeoFA-login ser man også dem, der ikke er offentlige, og kan redigere "
        "sine egne data.</p>"
        "<p>Pluginet er udviklet af Geopartner for GeoDanmark.</p>"
        "<p>"
        f"<a href='{GUIDE_URL}'>Vejledning</a><br>"
        f"<a href='{SPEC_URL}'>GeoFA-specifikationen</a><br>"
        f"<a href='{GEOFA_URL}'>GeoFA hos GeoDanmark</a><br>"
        f"<a href='{REPOSITORY_URL}'>Kildekode</a> og <a href='{ISSUES_URL}'>fejlrapporter</a> på GitHub"
        "</p>"
        f"<p>Mangler du et GeoFA-login, så skriv til <a href='mailto:{SUPPORT_EMAIL}'>{SUPPORT_EMAIL}</a> "
        "med emnet »GeoFA brugeroplysninger«.</p>"
    )


def show_about(parent, dataset_count):
    QMessageBox.about(parent, "Om GeoFA-pluginet", about_text(dataset_count))
