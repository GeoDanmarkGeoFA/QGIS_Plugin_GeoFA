"""Shared helpers for the layer generator: where the inputs live and how spec datasets map to tables.

Sources, in order of authority:
  - which datasets, their groups and order: the Confluence spec page tree (dev/spec/confluence_tree.json)
  - title, fields, required fields, code lists: the spec's Database repo (dev/spec/Database)
  - datasets whose spec page says "Kommer snart" (no Database page yet) are "pending":
    their fields come from the production WFS and the webmap's field configuration
  - styling: the webmap (dev/spec/webmap_meta.json)
"""
import ast
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "dev" / "spec"
DB = SPEC / "Database" / "_data"
GRAFIK = SPEC / "Grafik"
PLUGIN = REPO / "geofa_plugin"
OUT = PLUGIN / "layers"
REPORTS = REPO / "dev" / "reports"
WEBMAP_META = "https://geofa-kort.geodanmark.dk/api/meta/fkg/fkg"  # the webmap's own metadata for the fkg schema
PHOTO_FIELD = re.compile(r"^(geofafoto\d*|gpx_link)$")  # links to GeoFA's photos and GPX files

# Fields every GeoFA theme has (from the spec's generel table) and how the spec page classifies them
SYSTEM_FIELDS = {"versions_id", "objekt_id", "systid_fra", "systid_til", "oprettet", "temakode", "temanavn", "bruger_id"}
GENERAL_CODE_FIELDS = ["cvr_kode", "oprindkode", "statuskode", "off_kode"]  # "Generelt" tab
FREE_GENERAL_FIELDS = {"noegle", "note"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_loose(value):
    """Spec/webmap values are JSON, Python-literal strings or already parsed."""
    if value is None or isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if text in ("", "None", "null"):
        return None
    for parse in (json.loads, ast.literal_eval):
        try:
            return parse(text)
        except (ValueError, SyntaxError):
            continue
    return None


def clean_title(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def webmap_layers():
    # Guard: WEBMAP_META already asks for the fkg schema only; other schemas hold old copies of some tables
    return {l["f_table_name"]: l for l in read_json(SPEC / "webmap_meta.json")["data"] if l.get("f_table_schema") == "fkg"}


def prod_tables():
    return read_json(SPEC / "prod_feature_types.json")


def spec_meta(table):
    path = DB / "meta" / f"fkg.{table}.json"
    return read_json(path) if path.exists() else None


def table_schema(table):
    path = DB / "fkg" / "tables" / f"{table}_t.json"
    return read_json(path) if path.exists() else None


def generel_schema():
    return read_json(DB / "fkg" / "tables" / "generel.json")


def datasets():
    """The spec's datasets in spec order, each resolved to its table name."""
    tree = read_json(SPEC / "confluence_tree.json")
    prod = prod_tables()
    result = []
    for group in tree:
        for d in group["datasets"]:
            page = d["database_page"]
            if page:
                table, status = f"t_{page}", "published"
                code = page.split("_")[0]
            else:
                m = re.search(r"\((\d{4})\)\s*$", d["page_title"])
                code = m.group(1) if m else None
                matches = [t for t in prod if code and t.startswith(f"t_{code}_")]
                table, status = (matches[0] if len(matches) == 1 else None), "pending"
            meta = spec_meta(table) if table and status == "published" else None
            title = clean_title(meta.get("title")) if meta and meta.get("title") else clean_title(d["page_title"])
            result.append({
                "group": clean_title(group["group"]), "table": table, "code": code, "title": title, "page_title": clean_title(d["page_title"]),
                "spec_page_id": d["page_id"], "status": status,
            })
    return result
