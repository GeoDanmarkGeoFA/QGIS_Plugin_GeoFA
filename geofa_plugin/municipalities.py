# -*- coding: utf-8 -*-
"""The municipality filter: GeoFA layers show only objects inside a chosen municipality.

As in Danmarks Miljøportal's catalogue plugin, each WFS request carries an OGC Intersects filter
with the municipality's outline, so GeoFA's server sends only those objects. The outlines come
from GeoFA's own boundaries (tools/fetch_sources.py --municipalities): widened by a small margin
(50-400 m) and simplified by the same margin, so nothing inside is cut off and the filter fits in
a request URL (GeoFA's server turns down URLs over ~8 KB).
"""
import json
import os

from .catalogue import LAYERS_DIR

GEOMETRY_COLUMN = "geometri"  # the geometry column of every GeoFA dataset
NOT_A_MUNICIPALITY = {"0411": "Christiansø"}  # in the boundaries, but not a municipality
_outlines = None


def outlines():
    """{komkode: {"navn", "margin", "polygons"}}, read once."""
    global _outlines
    if _outlines is None:
        path = os.path.join(LAYERS_DIR, "municipalities.json")
        _outlines = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _outlines = json.load(f)
    return _outlines


def display_name(komkode):
    """'Aarhus Kommune' for '0751'; empty for no municipality."""
    if not komkode:
        return ""
    if komkode in NOT_A_MUNICIPALITY:
        return NOT_A_MUNICIPALITY[komkode]
    outline = outlines().get(komkode)
    return f"{outline['navn']} Kommune" if outline else komkode


def choices():
    """[(komkode, name)] sorted by name, for the settings."""
    return sorted(((code, display_name(code)) for code in outlines()), key=lambda pair: pair[1])


def _polygon(polygon):
    def pos_list(ring):
        # Whole metres: a short number format (6.2227e+06) loses precision, and QGIS leaves the
        # "+" unencoded in the request URL, where GeoFA's server reads it as a space
        return " ".join(f"{round(x)} {round(y)}" for x, y in ring)

    interiors = "".join(f"<gml:interior><gml:LinearRing><gml:posList>{pos_list(ring)}</gml:posList></gml:LinearRing>"
                        "</gml:interior>" for ring in polygon[1:])
    return (f"<gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>{pos_list(polygon[0])}"
            f"</gml:posList></gml:LinearRing></gml:exterior>{interiors}</gml:Polygon></gml:surfaceMember>")


def filter_xml(polygons):
    """The OGC filter (Filter Encoding 1.1, GML 3.1.1, for WFS 1.1.0) for objects intersecting the
    polygons. On one line: newlines and indentation would be mangled when QGIS puts the filter
    into the request URL. tools/fetch_sources.py uses it to keep each outline's filter short."""
    members = "".join(_polygon(polygon) for polygon in polygons)
    return ('<ogc:Filter xmlns:ogc="http://www.opengis.net/ogc" xmlns:gml="http://www.opengis.net/gml">'
            f"<ogc:Intersects><ogc:PropertyName>{GEOMETRY_COLUMN}</ogc:PropertyName>"
            f'<gml:MultiSurface srsName="EPSG:25832">{members}</gml:MultiSurface>'
            "</ogc:Intersects></ogc:Filter>")


def is_municipality_filter(text):
    """Whether a layer's filter is one this module made (rather than the user's own)."""
    return bool(text) and text.startswith("<ogc:Filter") and (
        f"<ogc:Intersects><ogc:PropertyName>{GEOMETRY_COLUMN}</ogc:PropertyName><gml:MultiSurface" in text)


def intersects_filter(komkode):
    """The filter for objects inside the municipality, or None for no filter or an unknown one."""
    outline = outlines().get(komkode or "")
    return filter_xml(outline["polygons"]) if outline else None
