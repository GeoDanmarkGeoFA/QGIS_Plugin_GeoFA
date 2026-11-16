"""Fetch and cache the inputs for the layer generator (read-only, public endpoints).

  - Confluence spec page tree: groups -> datasets, with the Database page each dataset embeds
  - Webmap (GC2) layer metadata: styles (class rules) per table
  - Production WFS capabilities: which feature types exist (anonymous, read-only)

Writes JSON files to dev/spec/. Run with OSGeo4W python (python-qgis-ltr.bat tools/fetch_sources.py).
"""
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parents[1] / "dev" / "spec"  # a local cache, not committed
CONFLUENCE = "https://confluence.kds.dk"
SPEC_PAGE_ID = "191398874"  # GeoFA-specifikation
# The same request the webmap makes for the fkg schema (the tag filter also returned other schemas' copies)
WEBMAP_META = "https://geofa-kort.geodanmark.dk/api/meta/fkg/fkg"
PROD_CAPS = "https://geofa.geodanmark.dk/ows/fkg/fkg?SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0"
NOT_DATASET_GROUPS = {"Opslagsliste"}  # code-list pages, not datasets


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "geofa-layer-generator"})
    with urllib.request.urlopen(req, timeout=90, context=ssl.create_default_context()) as r:
        return r.read()


def get_json(url):
    return json.loads(get(url).decode("utf-8"))


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


def sql(query):
    data = get_json(f"{PROD_SQL}?q={urllib.parse.quote(query)}")
    return [f["properties"] for f in data.get("features", [])]


def fetch_production_details():
    """Field lists, object counts and the pending datasets' code lists (production, anonymous, read-only)."""
    import geofa_spec
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
            except Exception as error:  # noqa: BLE001 - log and continue; reported by the generator
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


def main():
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    if "--production-details" in sys.argv:
        fetch_production_details()
        return
    if "--webmap" in sys.argv:
        fetch_webmap()
        return
    if "--authorities" in sys.argv:
        fetch_authorities()
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
