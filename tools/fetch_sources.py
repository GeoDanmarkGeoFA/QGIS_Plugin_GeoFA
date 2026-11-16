"""Fetch and cache the inputs for the layer generator (read-only, public endpoints, anonymous).

Run with OSGeo4W's Python: python-qgis-ltr.bat tools/fetch_sources.py [option]. Without an
option it fetches the basics; each option fetches one more input:

  (none)                 the Confluence spec page tree (groups -> datasets, with the Database page
                         each dataset embeds) -> confluence_tree.json; the webmap's layer metadata
                         (styles per table) -> webmap_meta.json; the production WFS's feature
                         types -> prod_feature_types.json
  --webmap               the webmap's layer metadata only -> webmap_meta.json
  --production-details   field lists, object counts and the pending datasets' code lists
                         -> prod_describe/, prod_counts.json, codelists/
  --authorities          municipality code -> CVR, for the cvr_kode default -> authorities.json
  --photo-layers         the photo-link versions of layers (fkg_foto_gpx_link) -> photo_layers.json
  --municipalities       municipality outlines for the municipality filter, written into the plugin
                         -> geofa_plugin/layers/municipalities.json

Files without a path go to dev/spec/ (a local cache, not committed).
"""
import argparse
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import geofa_spec

SPEC_DIR = geofa_spec.SPEC  # a local cache, not committed
CONFLUENCE = "https://confluence.kds.dk"
SPEC_PAGE_ID = "191398874"  # GeoFA-specifikation
WEBMAP_META = geofa_spec.WEBMAP_META
PROD_CAPS = "https://geofa.geodanmark.dk/ows/fkg/fkg?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0"
NOT_DATASET_GROUPS = {"Opslagsliste"}  # code-list pages, not datasets


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "geofa-layer-generator"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read()


def get_json(url, timeout=90):
    return json.loads(get(url, timeout).decode("utf-8"))


def children(page_id):
    out, start = [], 0
    while True:
        data = get_json(f"{CONFLUENCE}/rest/api/content/{page_id}/child/page?limit=200&start={start}")
        out += data.get("results", [])
        if not data.get("_links", {}).get("next"):
            return out
        start += 200


def embedded_page(page_id):
    """The Database page a spec page embeds, e.g. '5800_fac_pkt' (None if it embeds none)."""
    data = get_json(f"{CONFLUENCE}/rest/api/content/{page_id}?expand=body.storage")
    m = re.search(r"geodanmarkgeofa\.github\.io/Database/pages/([A-Za-z0-9_]+)", data["body"]["storage"]["value"])
    return m.group(1) if m else None


def confluence_tree():
    groups = []
    for group in children(SPEC_PAGE_ID):
        if group["title"] in NOT_DATASET_GROUPS:
            continue
        datasets = []
        for page in children(group["id"]):
            datasets.append({"page_id": page["id"], "page_title": page["title"],
                             "database_page": embedded_page(page["id"])})
        groups.append({"group": group["title"], "page_id": group["id"], "datasets": datasets})
    return groups


def prod_feature_types():
    root = ET.fromstring(get(PROD_CAPS))
    ns = {"wfs": "http://www.opengis.net/wfs"}
    return {ft.findtext("wfs:Name", namespaces=ns).split(".", 1)[-1]: (ft.findtext("wfs:Title", namespaces=ns) or "").strip()
            for ft in root.iter("{http://www.opengis.net/wfs}FeatureType")}


PROD_OWS = "https://geofa.geodanmark.dk/ows/fkg/fkg"
PROD_SQL = "https://geofa.geodanmark.dk/api/v2/sql/fkg"
XSD = "{http://www.w3.org/2001/XMLSchema}"


def describe(table):
    """Field names and XSD types of a production feature type, in WFS order."""
    url = f"{PROD_OWS}?SERVICE=WFS&VERSION=1.1.0&REQUEST=DescribeFeatureType&TYPENAME=fkg:fkg.{table}"
    root = ET.fromstring(get(url))
    return [{"name": e.get("name"), "type": e.get("type")} for e in root.iter(f"{XSD}element")
            if e.get("name") and e.get("type") and not e.get("substitutionGroup")]


def sql(query, timeout=90):
    data = get_json(f"{PROD_SQL}?q={urllib.parse.quote(query)}", timeout)
    return [f["properties"] for f in data.get("features", [])]


def fetch_production_details():
    """Field lists, object counts and the pending datasets' code lists (production, anonymous, read-only)."""
    tables = [d for d in geofa_spec.datasets() if d["table"]]

    describe_dir = SPEC_DIR / "prod_describe"
    describe_dir.mkdir(exist_ok=True)
    for d in tables:
        (describe_dir / f"{d['table']}.json").write_text(json.dumps(describe(d["table"]), indent=1), encoding="utf-8")
    print(f"described {len(tables)} production feature types")

    counts = {}
    for i in range(0, len(tables), 20):
        chunk = tables[i:i + 20]
        query = " UNION ALL ".join(f"SELECT '{d['table']}' AS t, count(*) AS n FROM fkg.{d['table']}" for d in chunk)
        counts.update({r["t"]: r["n"] for r in sql(query)})
    (SPEC_DIR / "prod_counts.json").write_text(json.dumps(counts, indent=1), encoding="utf-8")
    print(f"counted objects in {len(counts)} tables; empty: {sorted(t for t, n in counts.items() if not n)}")

    # Code lists for the pending datasets come from the webmap's field configuration
    webmap = geofa_spec.webmap_layers()
    code_dir = SPEC_DIR / "codelists"
    code_dir.mkdir(exist_ok=True)
    fetched, failed = 0, []
    for d in tables:
        if d["status"] != "pending" or d["table"] not in webmap:
            continue
        fieldconf = geofa_spec.parse_loose(webmap[d["table"]].get("fieldconf")) or {}
        for conf in fieldconf.values():
            rel = geofa_spec.parse_loose((conf or {}).get("properties")) or {}
            if not rel.get("_rel"):
                continue
            target = code_dir / f"{rel['_rel']}.json"
            if target.exists():
                continue
            where = f" WHERE {rel['_where']}" if rel.get("_where") else ""
            query = f"SELECT {rel['_value']} AS value, {rel['_text']} AS alias FROM {rel['_rel']}{where} ORDER BY 2"
            try:
                rows = sql(query)
            except Exception as error:  # noqa: BLE001 - listed in the summary below
                failed.append(f"{d['table']}: {rel['_rel']} ({error})")
                continue
            target.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            fetched += 1
    print(f"fetched {fetched} code lists for pending datasets; failed: {failed}", flush=True)


def fetch_authorities():
    """Municipality code -> CVR of the municipality, for the cvr_kode default (production, anonymous, read-only)."""
    rows = sql("SELECT kommunekode, cvr_kode FROM fkg.d_basis_ansvarlig_myndighed "
               "WHERE kommunekode IS NOT NULL AND aktiv = 1 ORDER BY 1")
    mapping = {str(r["kommunekode"]): str(r["cvr_kode"]) for r in rows}
    (SPEC_DIR / "authorities.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    print(f"authorities: {len(mapping)} municipalities")


def fetch_webmap():
    webmap = get_json(WEBMAP_META)
    (SPEC_DIR / "webmap_meta.json").write_text(json.dumps(webmap, ensure_ascii=False), encoding="utf-8")
    print(f"webmap: {len(webmap.get('data', []))} layers")


PHOTO_HOSTS = {"production": "https://geofa.geodanmark.dk", "test": "https://geofa-test.geodanmark.dk"}


def fetch_photo_layers():
    """GeoFA's photo-link versions of some layers (schema fkg_foto_gpx_link), per environment, and their photo fields.

    In these versions the photo fields (geofafoto, geofafoto1, ...) and gpx_link hold links to
    GeoFA's photo store; in the normal layers they are empty or missing."""
    out = {"environments": {}, "fields": {}}
    for environment, host in PHOTO_HOSTS.items():
        caps = get(f"{host}/ows/fkg/fkg_foto_gpx_link?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0").decode("utf-8")
        out["environments"][environment] = sorted(set(re.findall(r"<Name>fkg:fkg_foto_gpx_link\.(t_\w+)</Name>", caps)))
    for table in out["environments"]["production"]:
        describe = get(f"{PHOTO_HOSTS['production']}/ows/fkg/fkg_foto_gpx_link?SERVICE=WFS&VERSION=1.1.0"
                       f"&REQUEST=DescribeFeatureType&TYPENAME=fkg:fkg_foto_gpx_link.{table}").decode("utf-8")
        names = re.findall(r'<(?:xsd:)?element name="([^"]+)"', describe)
        out["fields"][table] = [name for name in names if geofa_spec.PHOTO_FIELD.match(name)]
    (SPEC_DIR / "photo_layers.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"photo layers: {out['environments']}")


MUNICIPALITY_MARGINS = (50, 100, 200, 400, 800, 1600)  # metres, tried in turn
# GeoFA's server turns down request lines over ~8,190 characters. The rest of a GetFeature URL
# (host, typename, paging and the parameters QGIS adds) must fit beside the encoded filter, so the
# filter itself is kept to this
MUNICIPALITY_FILTER_CHARS = 5500


def fetch_municipalities():
    """Municipality outlines for the plugin's municipality filter -> geofa_plugin/layers/municipalities.json.

    From GeoFA's own boundaries (dagi.kommune). Each outline is widened by a margin and then
    simplified by the same margin, so nothing inside the municipality is cut off, and nearby
    islets join the outline; the smallest margin whose filter, as sent in a request URL, stays
    under MUNICIPALITY_FILTER_CHARS is used. The plugin sends the outline in each WFS request's
    filter (geofa_plugin/municipalities.py builds it; the same code measures it here)."""
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from qgis.core import Qgis, QgsGeometry  # noqa: E402
    from geofa_plugin.municipalities import filter_xml  # noqa: E402

    def polygons_of(geometry):
        """Polygons as rings of whole-metre [x, y] points; rings too small to be rings are dropped."""
        geometry = geometry.makeValid()
        geometry.convertGeometryCollectionToSubclass(Qgis.GeometryType.Polygon)
        parts = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
        polygons = []
        for part in parts:
            rings = [[[round(p.x()), round(p.y())] for p in ring] for ring in part]
            rings = [ring for ring in rings if len(ring) >= 4]
            if rings:
                polygons.append(rings)
        return polygons

    # One light query: each municipality's parts joined and lightly simplified. The widening and
    # simplifying per margin is done here: on GeoFA's SQL API it times out (HTTP 500)
    rows = sql("SELECT komkode, max(komnavn) AS navn, ST_AsText(ST_SimplifyPreserveTopology(ST_Union(the_geom), 5)) "
               "AS wkt FROM dagi.kommune GROUP BY komkode ORDER BY komkode", timeout=900)
    out, margins = {}, {}
    for row in rows:
        boundary = QgsGeometry.fromWkt(row["wkt"])
        for margin in MUNICIPALITY_MARGINS:
            polygons = polygons_of(boundary.buffer(margin, 2).simplify(margin))
            length = len(urllib.parse.quote(filter_xml(polygons), safe=""))
            if length <= MUNICIPALITY_FILTER_CHARS or margin == MUNICIPALITY_MARGINS[-1]:
                out[row["komkode"]] = {"navn": row["navn"], "margin": margin, "polygons": polygons}
                margins[margin] = margins.get(margin, 0) + 1
                break
    target = repo / "geofa_plugin" / "layers" / "municipalities.json"
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"municipalities: {len(out)} outlines, margins {dict(sorted(margins.items()))} -> {target} "
          f"({target.stat().st_size // 1024} KB)")


def main():
    parser = argparse.ArgumentParser(description="Fetch the layer generator's inputs (see the module docstring).")
    options = parser.add_mutually_exclusive_group()
    for option in ("--webmap", "--production-details", "--authorities", "--photo-layers", "--municipalities"):
        options.add_argument(option, action="store_true")
    args = parser.parse_args()
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    for option, fetch in (("photo_layers", fetch_photo_layers), ("municipalities", fetch_municipalities),
                          ("production_details", fetch_production_details), ("webmap", fetch_webmap),
                          ("authorities", fetch_authorities)):
        if getattr(args, option):
            fetch()
            return
    tree = confluence_tree()
    (SPEC_DIR / "confluence_tree.json").write_text(json.dumps(tree, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(g["datasets"]) for g in tree)
    missing = [d["page_title"] for g in tree for d in g["datasets"] if not d["database_page"]]
    print(f"confluence: {len(tree)} groups, {n} datasets; without embedded Database page: {missing}")

    fetch_webmap()

    prod = prod_feature_types()
    (SPEC_DIR / "prod_feature_types.json").write_text(json.dumps(prod, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"production WFS: {len(prod)} feature types")


if __name__ == "__main__":
    main()
