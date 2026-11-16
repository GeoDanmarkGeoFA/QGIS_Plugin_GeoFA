# -*- coding: utf-8 -*-
"""The GeoFA datasets the plugin offers, read from layers/catalogue.json.

catalogue.json and the styles next to it are generated from the GeoFA specification
(groups, titles, fields, where each field's code list is) and the GeoFA webmap (symbols),
so the plugin itself holds no list of layers. The code lists themselves are read from
GeoFA when a layer is added (see codelists.py).
"""
import json
import os
from dataclasses import dataclass, field

from .codelists import Source

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

    @property
    def style_path(self):
        return os.path.join(LAYERS_DIR, self.style)

    @property
    def pending(self):
        return self.status == "pending"

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
                                     code_lists=self._code_lists(d.get("code_lists") or {}))
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
