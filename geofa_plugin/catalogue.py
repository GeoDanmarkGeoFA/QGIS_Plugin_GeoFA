# -*- coding: utf-8 -*-
"""The GeoFA datasets the plugin offers, read from layers/catalogue.json.

catalogue.json and the styles next to it are generated from the GeoFA specification
(groups, titles, fields, where each field's code list is) and the GeoFA webmap (symbols),
so the plugin itself holds no list of layers. The code lists themselves are read from
GeoFA when a layer is added (see codelists.py).
"""
import hashlib
import json
import os
from dataclasses import dataclass, field
from xml.etree import ElementTree

from .codelists import Source

# The parts of a QML that make up the fields and the form (QGIS's Fields and Forms style categories)
FORM_ELEMENTS = ("fieldConfiguration", "aliases", "defaults", "constraints", "constraintExpressions",
                 "expressionfields", "attributeEditorForm", "editable", "labelOnTop", "reuseLastValue",
                 "editorlayout", "editform", "editforminit", "featformsuppress")


def form_fingerprint(style_path):
    """A short fingerprint of a style's fields and form (aliases, widgets, defaults, tabs).

    The generator stores it in the catalogue (Dataset.form_version) and the plugin on every
    layer it adds, so it can tell when a project's layers have an older form than the plugin's.
    The XML attributes are put in a fixed order first (QGIS writes them in a varying order),
    so the fingerprint only changes when the form does."""
    root = ElementTree.parse(style_path).getroot()
    parts = [ElementTree.canonicalize(ElementTree.tostring(element, encoding="unicode"), strip_text=True)
             for name in FORM_ELEMENTS for element in root.findall(name)]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:12]

LAYERS_DIR = os.path.join(os.path.dirname(__file__), "layers")
SYMBOLS_DIR = os.path.join(LAYERS_DIR, "symbols")

# Tables renamed in GeoFA; layers from older versions of the plugin still point at the old names
RENAMED_TABLES = {
    "t_5608_cykelknudepunkter": "t_5608_cykelkrydspunkter",
    "t_5609_cykelknudepunktsstraekninger": "t_5609_cykelkrydspunktsstraekninger",
}


@dataclass(frozen=True)
class Dataset:
    table: str
    code: str
    title: str
    group: str
    style: str
    status: str  # "published", or "pending" when the spec page says "Kommer snart"
    spec_page: str
    purpose: str
    form_version: str = ""  # fingerprint of the style's fields and form, stored on the layers
    code_lists: tuple = field(default=())  # ((field, Source, required), ...)
    geometry: str = ""  # "MultiPoint", "MultiLineString" or "MultiPolygon" (empty when unknown)
    # Environments ("production", "test") where GeoFA has a photo-link version of the table
    photo_environments: tuple = field(default=())

    @property
    def style_path(self):
        return os.path.join(LAYERS_DIR, self.style)

    @property
    def pending(self):
        return self.status == "pending"

    def icon(self):
        """QGIS's icon for the layer's geometry type (point, line, polygon), as in the layer panel."""
        from qgis.core import QgsApplication, QgsIconUtils, QgsWkbTypes
        if not self.geometry:
            return QgsApplication.getThemeIcon("/mIconWfs.svg")
        return QgsIconUtils.iconForWkbType(QgsWkbTypes.parseType(self.geometry))

    def search_text(self):
        """What the search in the panel and QGIS's locator bar matches: title, theme code and table."""
        return f"{self.title} {self.code} {self.table}".lower()


class Catalogue:
    def __init__(self, path=None):
        with open(path or os.path.join(LAYERS_DIR, "catalogue.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.source = data.get("source", {})
        # [(group name, [Dataset, ...]), ...] in the spec's order
        self.groups = [
            (group["name"], [Dataset(table=d["table"], code=d.get("code") or "", title=d["title"],
                                     group=group["name"], style=d["style"], status=d.get("spec") or "published",
                                     spec_page=d.get("spec_page") or "", purpose=d.get("purpose") or "",
                                     form_version=d.get("form_version") or "",
                                     code_lists=self._code_lists(d.get("code_lists") or {}),
                                     geometry=d.get("geometry") or "",
                                     photo_environments=tuple(d.get("photo_environments") or ()))
                             for d in group["datasets"] if d.get("table")])
            for group in data["groups"]
        ]
        self._by_table = {d.table: d for _, datasets in self.groups for d in datasets}

    @staticmethod
    def _code_lists(entries):
        """{field: [table, code column, text column, filter, required]} -> ((field, Source, required), ...)"""
        return tuple((name, Source(table, value, text, where or ""), bool(required))
                     for name, (table, value, text, where, required) in entries.items())

    def datasets(self):
        return [d for _, datasets in self.groups for d in datasets]

    def get(self, table):
        return self._by_table.get(RENAMED_TABLES.get(table, table))


_catalogue = None


def catalogue():
    """The plugin's catalogue, read once."""
    global _catalogue
    if _catalogue is None:
        _catalogue = Catalogue()
    return _catalogue
