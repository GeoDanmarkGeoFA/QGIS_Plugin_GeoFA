"""Generate the plugin's layer catalogue, QML styles and symbols from the GeoFA spec and the webmap's styling.

Run with QGIS 3.44 LTR, the oldest QGIS the tests run on, so the QMLs load in QGIS 3.34+ and QGIS 4:
    python-qgis-ltr.bat tools/generate_layers.py [--only t_5800_fac_pkt,t_5710_born_skole_dis]

Inputs live in dev/spec/: clones of GeoFA's Database and Grafik repositories, and the files
tools/fetch_sources.py writes (see the readme). Outputs:
    geofa_plugin/layers/catalogue.json        groups and datasets, in spec order, with where each
                                              field's code list is in GeoFA and a form version
    geofa_plugin/layers/styles/<table>.qml     symbology, labels, edit form, constraints (no code
                                              lists: the plugin reads them from GeoFA)
    geofa_plugin/layers/symbols/...            the SVG symbols the styles use (from the Grafik repo)
    dev/reports/difference_report.md           spec vs webmap vs production WFS
"""
import argparse
import functools
import json
import os
import re
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Own throwaway QGIS profile, so the generator never touches the user's QGIS settings
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = str(Path(__file__).resolve().parents[1] / "dev" / "qgis-profile" / "generator")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import geofa_spec as spec  # noqa: E402

sys.path.insert(0, str(spec.REPO))
from geofa_plugin.catalogue import form_fingerprint  # noqa: E402  (the same fingerprint the plugin checks)
from geofa_plugin.htmlfields import HTML_FIELDS  # noqa: E402

from qgis.core import (  # noqa: E402
    Qgis, QgsApplication, QgsAttributeEditorContainer, QgsAttributeEditorField, QgsCategorizedSymbolRenderer,
    QgsEditorWidgetSetup, QgsField, QgsFieldConstraints, QgsFillSymbol, QgsLinePatternFillSymbolLayer,
    QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsRendererCategory, QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer, QgsSimpleMarkerSymbolLayer, QgsSingleSymbolRenderer, QgsSvgMarkerSymbolLayer,
    QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsCentroidFillSymbolLayer,
    QgsSettings, QgsFontMarkerSymbolLayer, QgsPointPatternFillSymbolLayer, QgsDefaultValue, QgsExpression,
    QgsOptionalExpression,
)
from qgis.PyQt.QtCore import QMetaType, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont  # noqa: E402

PIXELS = Qgis.RenderUnit.Pixels
NULL_VALUE = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"  # how QGIS's ValueMap stores "no value"
GENERAL_FIELDS_THEME = "t_5800_fac_pkt"  # any published theme has the general fields and their code lists
# QGIS's attachment widget as a link only: the file name, opened in the browser on a click
PHOTO_LINK = {"DocumentViewer": 0, "DocumentViewerHeight": 0, "DocumentViewerWidth": 0, "FileWidget": True,
              "FileWidgetButton": False, "FullUrl": False, "RelativeStorage": 0, "StorageMode": 0, "UseLink": True}
DERIVED_GENERAL = {"cvr_navn", "kommunekode", "oprindelse", "status", "offentlig"}
GEOMETRY = {"MULTIPOINT": "MultiPoint", "POINT": "MultiPoint", "MULTILINESTRING": "MultiLineString",
            "LINESTRING": "MultiLineString", "MULTIPOLYGON": "MultiPolygon", "POLYGON": "MultiPolygon"}
SPEC_TYPES = {"integer": QMetaType.Type.Int, "bigint": QMetaType.Type.LongLong, "smallint": QMetaType.Type.Int,
              "double precision": QMetaType.Type.Double, "numeric": QMetaType.Type.Double, "real": QMetaType.Type.Double,
              "date": QMetaType.Type.QDate, "timestamp with time zone": QMetaType.Type.QDateTime,
              "timestamp without time zone": QMetaType.Type.QDateTime, "time without time zone": QMetaType.Type.QTime,
              "boolean": QMetaType.Type.Bool}
XSD_TYPES = {"integer": QMetaType.Type.Int, "int": QMetaType.Type.Int, "long": QMetaType.Type.LongLong,
             "double": QMetaType.Type.Double, "decimal": QMetaType.Type.Double, "float": QMetaType.Type.Double,
             "date": QMetaType.Type.QDate, "dateTime": QMetaType.Type.QDateTime, "time": QMetaType.Type.QTime,
             "boolean": QMetaType.Type.Bool}
GRAFIK_URL = re.compile(r"github(?:usercontent)?\.com/GeoDanmarkGeoFA/Grafik/(?:refs/heads/|raw/|blob/)?main/(.+)$")


# ---------------------------------------------------------------- fields

def spec_fields(dataset):
    """(fields, spec meta or None) for a dataset. Each field has name, qtype, kind
    (system/general/theme/derived/free), required, codes and source."""
    table = dataset["table"]
    meta = spec.spec_meta(table) if dataset["status"] == "published" else None
    describe = spec.read_json(spec.SPEC / "prod_describe" / f"{table}.json")
    fields = []
    if meta:
        schema = spec.table_schema(table) or {"columns": []}
        theme_columns = {c["name"]: c for c in schema["columns"]}
        general = {c["name"]: c for c in spec.generel_schema()["columns"]}
        ordered = sorted(meta["fields"].items(), key=lambda kv: (int(kv[1].get("sort_id") or 999), list(meta["fields"]).index(kv[0])))
        for name, f in ordered:
            if f.get("_type") == "geometry":
                continue
            column = theme_columns.get(name) or general.get(name)
            nullable = str((column or {}).get("is_nullable")) != "False"
            restriction = f.get("_restriction") if isinstance(f.get("_restriction"), list) else None
            fields.append({
                "name": name, "qtype": SPEC_TYPES.get(f.get("_type"), QMetaType.Type.QString),
                "kind": classify(name, in_theme=name in theme_columns),
                "required": column is not None and not nullable,
                "codes": [(str(r.get("value")), str(r.get("alias"))) for r in restriction] if restriction else None,
                "source": code_source(f.get("properties")),
            })
        return fields, meta
    # Pending: production WFS fields, code relations from the webmap, general code lists from a published theme
    webmap = spec.webmap_layers().get(table, {})
    fieldconf = spec.parse_loose(webmap.get("fieldconf")) or {}
    derived = {(spec.parse_loose(c.get("properties")) or {}).get("_text") for c in fieldconf.values() if c} - {None}
    general_codes, general_sources = general_code_lists(), general_code_sources()
    for d in describe:
        name = d["name"]
        if d["type"].startswith("gml:"):
            continue
        codes = general_codes.get(name)
        props = spec.parse_loose((fieldconf.get(name) or {}).get("properties")) or {}
        source = code_source(props) or general_sources.get(name)
        rel = props.get("_rel") if isinstance(props, dict) else None
        if rel and codes is None:
            cached = spec.SPEC / "codelists" / f"{rel}.json"
            if cached.exists():
                codes = [(str(r["value"]), str(r["alias"])) for r in spec.read_json(cached)]
        kind = "derived" if name in derived else classify(name, in_theme=True)
        fields.append({"name": name, "qtype": XSD_TYPES.get(d["type"].split(":")[-1], QMetaType.Type.QString),
                       "kind": kind, "required": False, "codes": codes, "source": source})
    return fields, None


def code_source(props):
    """Where GeoFA keeps a field's code list: [table, value column, text column, filter], or None.

    The same relation GeoFA's own webmap uses for its dropdowns (fkg.d_* tables); the plugin
    reads the list from GeoFA's SQL API when it adds the layer.
    """
    if not isinstance(props, dict) or not all(props.get(k) for k in ("_rel", "_value", "_text")):
        return None
    return [props["_rel"], props["_value"], props["_text"], props.get("_where") or ""]


@functools.cache
def general_code_sources():
    """Code list sources of the general fields (cvr_kode, statuskode, …), from a published theme."""
    meta = spec.spec_meta(GENERAL_FIELDS_THEME)
    return {name: code_source(meta["fields"][name].get("properties")) for name in spec.GENERAL_CODE_FIELDS
            if code_source(meta["fields"][name].get("properties"))}


def classify(name, in_theme):
    if name in spec.SYSTEM_FIELDS:
        return "system"
    if name in spec.GENERAL_CODE_FIELDS:
        return "general"
    if name in spec.FREE_GENERAL_FIELDS:
        return "free"
    if name in DERIVED_GENERAL:
        return "derived"
    return "theme" if in_theme else "derived"


@functools.cache
def general_code_lists():
    """cvr_kode/oprindkode/statuskode/off_kode code lists, taken from a published theme."""
    meta = spec.spec_meta(GENERAL_FIELDS_THEME)
    return {name: [(str(r["value"]), str(r["alias"])) for r in meta["fields"][name]["_restriction"]]
            for name in spec.GENERAL_CODE_FIELDS if isinstance(meta["fields"][name].get("_restriction"), list)}


# ---------------------------------------------------------------- styling

def color(value, default="#808080", opacity=None):
    c = QColor(str(value).strip()) if value else QColor(default)
    if not c.isValid():
        c = QColor(default)
    if opacity not in (None, ""):
        c.setAlphaF(max(0.0, min(1.0, float(opacity) / 100.0)))
    return c


def number(value, default):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def local_svg(url, symbols_dir, used):
    """Copy a Grafik SVG into the plugin and return its local path (None if it isn't a Grafik SVG)."""
    m = GRAFIK_URL.search(url or "")
    if not m:
        return None
    source = spec.GRAFIK / m.group(1)
    if not source.exists():
        used.setdefault("missing_svgs", set()).add(url)
        return None
    target = symbols_dir / Path(m.group(1)).name
    if not target.exists():
        shutil.copyfile(source, target)
    used.setdefault("svgs", set()).add(target.name)
    return str(target)


MARKER_SHAPES = {"square": Qgis.MarkerShape.Square, "triangle": Qgis.MarkerShape.Triangle,
                 "circle": Qgis.MarkerShape.Circle, "arrow": Qgis.MarkerShape.ArrowHead,
                 "arrow2": Qgis.MarkerShape.ArrowHeadFilled}


def marker_layer(kind, fill, stroke, size, symbols_dir, used, angle=0, stroke_width=None):
    """A point symbol. stroke=None draws no outline (MapServer draws none without an outline colour)."""
    svg = local_svg(kind, symbols_dir, used) if kind and kind.lower().endswith(".svg") else None
    if svg:
        layer = QgsSvgMarkerSymbolLayer(svg, size, angle)
        layer.setFillColor(fill)
        layer.setStrokeColor(stroke if stroke is not None else fill)
    else:
        layer = QgsSimpleMarkerSymbolLayer(MARKER_SHAPES.get(kind, Qgis.MarkerShape.Circle), size, angle)
        layer.setColor(fill)
        if stroke is None:
            layer.setStrokeStyle(Qt.PenStyle.NoPen)
        else:
            layer.setStrokeColor(stroke)
            if stroke_width is not None:
                layer.setStrokeWidth(stroke_width)
                layer.setStrokeWidthUnit(PIXELS)
    layer.setSizeUnit(PIXELS)
    return layer


def symbol_for(rule, geometry, symbols_dir, used):
    """A QGIS symbol for one GC2 class (legacy flat properties, or the newer 'styles' list)."""
    if rule.get("styles"):
        st = rule["styles"][0]
        rule = dict(rule, color=st.get("color"), outlinecolor=st.get("outlinecolor"),
                    style_opacity=st.get("opacity"), width=st.get("width"), size=st.get("size"), symbol=st.get("symbol"))
    opacity = rule.get("style_opacity")
    fill = color(rule.get("color"), opacity=opacity)
    # The webmap (MapServer) applies a style's opacity to its outline as well
    stroke = color(rule.get("outlinecolor"), default=rule.get("color") or "#404040", opacity=opacity)
    width = number(rule.get("width"), 1.0)
    size = number(rule.get("size"), 10.0)
    has_outline = bool(str(rule.get("outlinecolor") or "").strip())
    if geometry == "MultiPoint":
        sym = QgsMarkerSymbol()
        sym.changeSymbolLayer(0, marker_layer(rule.get("symbol") or "circle", fill, stroke if has_outline else None, size,
                                              symbols_dir, used, stroke_width=width if has_outline else None))
    elif geometry == "MultiLineString":
        sym = QgsLineSymbol()
        line = QgsSimpleLineSymbolLayer(fill, width)
        line.setWidthUnit(PIXELS)
        dashes = [number(x, 0) for x in str(rule.get("pattern") or "").split()]
        if dashes:
            line.setUseCustomDashPattern(True)
            line.setCustomDashVector(dashes)
            line.setCustomDashPatternUnit(PIXELS)
        if rule.get("linecap") == "butt":
            line.setPenCapStyle(Qt.PenCapStyle.FlatCap)
        sym.changeSymbolLayer(0, line)
    else:
        sym = QgsFillSymbol()
        # Without an outline colour the webmap draws no outline
        pen = Qt.PenStyle.SolidLine if has_outline else Qt.PenStyle.NoPen
        fill_layer = QgsSimpleFillSymbolLayer(fill, Qt.BrushStyle.SolidPattern, stroke, pen, width)
        fill_layer.setStrokeWidthUnit(PIXELS)
        sym.changeSymbolLayer(0, fill_layer)
        if rule.get("symbol") and str(rule["symbol"]).lower().endswith(".svg"):
            centroid = QgsCentroidFillSymbolLayer()
            marker = QgsMarkerSymbol()
            marker.changeSymbolLayer(0, marker_layer(rule["symbol"], fill, stroke, size, symbols_dir, used))
            centroid.setSubSymbol(marker)
            sym.appendSymbolLayer(centroid)
    overlay = str(rule.get("overlaysymbol") or "").strip()
    if geometry == "MultiLineString" and not overlay and str(rule.get("overlaycolor") or "").strip():
        # A line's second style without a symbol is a plain line drawn on top (e.g. 5609: purple on white)
        top = QgsSimpleLineSymbolLayer(color(rule["overlaycolor"], opacity=opacity), number(rule.get("overlaywidth"), 1.0))
        top.setWidthUnit(PIXELS)
        if rule.get("linecap") == "butt":
            top.setPenCapStyle(Qt.PenCapStyle.FlatCap)
        sym.appendSymbolLayer(top)
    elif geometry == "MultiPolygon" and not overlay and str(rule.get("overlayoutlinecolor") or "").strip():
        # An area's second style without a symbol is an outline on top, at its own opacity (e.g. 5700: 3 px magenta)
        edge = QgsSimpleLineSymbolLayer(color(rule["overlayoutlinecolor"], opacity=rule.get("overlaystyle_opacity")),
                                        number(rule.get("overlaywidth"), 1.0))
        edge.setWidthUnit(PIXELS)
        sym.appendSymbolLayer(edge)
    elif overlay and geometry == "MultiPolygon":
        overlay_layer = overlay_for(rule, overlay, symbols_dir, used)
        if overlay_layer:
            sym.appendSymbolLayer(overlay_layer)
        else:
            used.setdefault("unhandled_overlays", set()).add(overlay)
    elif overlay:
        used.setdefault("unhandled_overlays", set()).add(overlay)
    return sym


def overlay_for(rule, overlay, symbols_dir, used):
    """The webmap's second style on an area: hatching, a tiled point pattern, or an SVG on the centroid."""
    size = number(rule.get("overlaysize"), 5)
    # The overlay has its own opacity (style_opacity is the first style's only)
    colour = color(rule.get("overlaycolor"), "#000000", opacity=rule.get("overlaystyle_opacity"))
    angle = number(rule.get("overlayangle"), 0)
    width = number(rule.get("overlaywidth"), 1)
    if overlay.startswith("hatch") or overlay == "dashed-line-short":
        # QGIS's line angle is the webmap's hatch angle + 45° (mod 180): webmap 135 is horizontal, 45 vertical
        hatch = QgsLinePatternFillSymbolLayer()
        hatch.setLineAngle((angle + 45) % 180)
        # "dashed-line-short" comes out as solid stripes, much further apart than its size (Nationalpark: 20 px)
        hatch.setDistance(size if overlay.startswith("hatch") else max(size, 5) * 4)
        hatch.setDistanceUnit(PIXELS)
        line = QgsSimpleLineSymbolLayer(colour, width)
        line.setWidthUnit(PIXELS)
        sub = QgsLineSymbol()
        sub.changeSymbolLayer(0, line)
        hatch.setSubSymbol(sub)
        return hatch
    # The webmap tiles these point symbols edge to edge at their size, turned counter-clockwise by the angle;
    # "dashed-line-long" and "dot-dot" come out as a grid of circles
    shape = {"dashed-line-long": "circle", "dot-dot": "circle"}.get(overlay, overlay)
    if shape in MARKER_SHAPES:
        pattern = QgsPointPatternFillSymbolLayer()
        pattern.setDistanceX(size)
        pattern.setDistanceY(size)
        pattern.setDistanceXUnit(PIXELS)
        pattern.setDistanceYUnit(PIXELS)
        outline = str(rule.get("overlayoutlinecolor") or "").strip()
        stroke = color(outline, opacity=rule.get("overlaystyle_opacity")) if outline else None
        marker_size = max(2.0, width * 2) if overlay == "dot-dot" else max(size, 5.0) if shape == "arrow" else size * 0.8
        turn = -angle
        if shape == "arrow" and stroke is None:
            # QGIS's open arrowhead is drawn with its outline only
            stroke = colour
        if shape == "arrow2":
            # The webmap's arrow2 is a narrow filled arrowhead pointing right at angle 0: QGIS's triangle points up
            shape, turn = "triangle", 90 - angle
        sub = QgsMarkerSymbol()
        sub.changeSymbolLayer(0, marker_layer(shape, colour, stroke, marker_size, symbols_dir, used,
                                              angle=turn, stroke_width=width if stroke is not None else None))
        pattern.setSubSymbol(sub)
        return pattern
    if overlay.lower().endswith(".svg"):
        centroid = QgsCentroidFillSymbolLayer()
        sub = QgsMarkerSymbol()
        sub.changeSymbolLayer(0, marker_layer(overlay, colour, colour, size, symbols_dir, used))
        centroid.setSubSymbol(sub)
        return centroid
    return None


CATEGORY_EXPR = re.compile(r"^'\[(\w+)\]'\s*=\s*'(.*)'$")
# Codes a GeoFA code list holds by mistake, which the styles leave out (the dropdowns show GeoFA's list as it is).
# 22429 repeats 2242's text and definition ("SPOR Fortællinger fra Sporet"), is the only five-digit facility
# code, and no public object uses it; 2242 has the objects
CODE_LIST_MISTAKES = {"fkg.d_5800_facilitet": {"22429"}}


def renderer_for(webmap_layer, geometry, fields, symbols_dir, used):
    rules = spec.parse_loose((webmap_layer or {}).get("class")) or []
    if not rules:
        sym = default_symbol(geometry)
        return QgsSingleSymbolRenderer(sym), "default (no webmap style)"
    parsed = [(CATEGORY_EXPR.match((r.get("expression") or "").strip()), r) for r in rules]
    # A webmap class without an expression draws everything the other classes don't
    otherwise = [r for m, r in parsed if not m and not (r.get("expression") or "").strip()]
    parsed = [(m, r) for m, r in parsed if m]
    if len(parsed) > 1 and len(parsed) + len(otherwise) == len(rules) and len(otherwise) <= 1 \
            and len({m.group(1) for m, _ in parsed}) == 1:
        text_field = parsed[0][0].group(1)
        # Categorise on the code field when the spec maps the text field to codes, so new objects style at once.
        # The webmap styles by text, so a text with more than one code gets the symbol for all of them
        # (the report lists them), except for codes in a list by mistake
        code_field, text_to_codes = None, {}
        for f in fields:
            if f["codes"] and text_field_for(f, fields) == text_field:
                code_field, text_to_codes = f["name"], {}
                mistakes = CODE_LIST_MISTAKES.get((f["source"] or [None])[0], set())
                for value, alias in f["codes"]:
                    if value not in mistakes:
                        text_to_codes.setdefault(alias, []).append(value)
        table = webmap_layer["f_table_name"]
        by_key = {normalise(text): text for text in text_to_codes}
        attribute = code_field or text_field
        entries, styled = [], set()  # (label, [values], webmap rule)
        for m, r in parsed:
            webmap_text = m.group(2)
            spec_text = by_key.get(normalise(webmap_text)) if code_field else webmap_text
            if code_field and not spec_text:
                # the spec is the source of truth: skip webmap categories it doesn't define
                used.setdefault("webmap_categories_not_in_spec", set()).add(f"{table}: {webmap_text}")
                continue
            if spec_text != webmap_text:
                used.setdefault("webmap_spelling_differs", set()).add(f"{table}: '{webmap_text}' = spec '{spec_text}'")
            styled.add(spec_text)
            entries.append((spec_text, text_to_codes[spec_text] if code_field else [spec_text], r))
        if code_field:
            template = next((r for _, r in parsed if r.get("symbol")), parsed[0][1])
            for spec_text in sorted(set(text_to_codes) - styled):
                # Grafik's per-code SVGs are point symbols; other codes without a webmap style use the fallback
                codes = text_to_codes[spec_text]
                svg = next((s for s in (grafik_svg_for_code(dataset_code(table), code, template.get("symbol")) for code in codes)
                            if s), None) if geometry == "MultiPoint" and template.get("symbol") else None
                if svg:
                    entries.append((spec_text, codes, dict(template, symbol=svg)))
                    used.setdefault("spec_codes_styled_from_grafik", set()).add(f"{table}: {spec_text}")
                else:
                    used.setdefault("spec_codes_without_style", set()).add(f"{table}: {spec_text}")
        for label, values, _ in entries:
            if len(values) > 1:
                used.setdefault("texts_with_several_codes", set()).add(f"{table}: '{label}' = {', '.join(values)}")
        # Alphabetical like the webmap, with "Andet", "Ved ikke", "Ukendt" etc. last
        entries.sort(key=lambda e: legend_order(e[0]))
        # One legend entry per text: a category holds all of the text's codes
        categories = [QgsRendererCategory(values if len(values) > 1 else values[0], symbol_for(r, geometry, symbols_dir, used),
                                          label) for label, values, r in entries]
        # Objects without a type, or with a type that has no symbol (e.g. a code added to the spec later),
        # would otherwise be invisible: they get the webmap's own "everything else" style, or one in the layer's colour
        fallback = symbol_for(otherwise[0], geometry, symbols_dir, used) if otherwise \
            else fallback_symbol(geometry, [r for _, _, r in entries], symbols_dir, used)
        categories.append(QgsRendererCategory("", fallback, "Alle andre værdier"))
        return QgsCategorizedSymbolRenderer(attribute, categories), f"categorised on {attribute} ({len(categories) - 1})"
    if len(rules) == 1 and not (rules[0].get("expression") or "").strip():
        return QgsSingleSymbolRenderer(symbol_for(rules[0], geometry, symbols_dir, used)), "single symbol"
    used.setdefault("unhandled_rules", set()).add(webmap_layer["f_table_name"])
    return QgsSingleSymbolRenderer(symbol_for(rules[0], geometry, symbols_dir, used)), "first rule only (unhandled rules)"


def normalise(text):
    return re.sub(r"[^0-9a-zæøå]", "", (text or "").lower())


# Catch-all values go last in the legend, in this order
CATCH_ALL = [re.compile(r"^(andet|anden|andre)(?![a-zæøå])"), re.compile(r"^ved ikke"), re.compile(r"^ukendt")]
DANISH_ORDER = str.maketrans({"æ": "{", "ø": "|", "å": "}"})  # æ, ø, å after z


def legend_order(label):
    text = (label or "").strip().lower()
    rank = next((i for i, pattern in enumerate(CATCH_ALL) if pattern.match(text)), None)
    return (0 if rank is None else 1, rank or 0, text.translate(DANISH_ORDER))


def main_colour(rule, symbols_dir, used):
    """The colour a symbol reads as: an SVG's first non-white colour, else the style's colour."""
    svg = local_svg(rule.get("symbol"), symbols_dir, used) if str(rule.get("symbol") or "").lower().endswith(".svg") else None
    if svg:
        for hex_value in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", Path(svg).read_text(encoding="utf-8", errors="replace")):
            c = QColor(hex_value)
            if min(c.red(), c.green(), c.blue()) < 230:
                return c.name()
    return color(rule.get("color")).name()


def lighten(c, share):
    """Mix a colour with white."""
    return QColor.fromRgbF(c.redF() + (1 - c.redF()) * share, c.greenF() + (1 - c.greenF()) * share,
                           c.blueF() + (1 - c.blueF()) * share, c.alphaF())


def fallback_symbol(geometry, rules, symbols_dir, used):
    """Symbol for 'all other values': the layer's most used colour, so it looks like part of the layer."""
    colours = [main_colour(r, symbols_dir, used) for r in rules]
    dominant = QColor(max(set(colours), key=colours.count)) if colours else QColor("#808080")
    template = rules[0] if rules else {}
    if geometry == "MultiPoint":
        # A circle like the round Grafik symbols, with a question mark instead of an icon
        size = number(template.get("size"), 10)
        sym = QgsMarkerSymbol()
        circle = QgsSimpleMarkerSymbolLayer(Qgis.MarkerShape.Circle, size)
        circle.setColor(dominant)
        circle.setStrokeStyle(Qt.PenStyle.NoPen)
        circle.setSizeUnit(PIXELS)
        sym.changeSymbolLayer(0, circle)
        mark = QgsFontMarkerSymbolLayer("Arial", "?", size * 0.7, QColor("white"))
        mark.setFontStyle("Bold")
        mark.setSizeUnit(PIXELS)
        sym.appendSymbolLayer(mark)
        return sym
    # Lines and areas: the template's width/opacity/outline, solid, in a lighter shade of the layer's colour
    rule = dict(template, color=lighten(dominant, 0.45).name(), pattern="", linecap="", symbol="", overlaysymbol="")
    return symbol_for(rule, geometry, symbols_dir, used)


def dataset_code(table):
    return table.split("_")[1]


def grafik_svg_for_code(theme_code, code, sibling_url):
    """Grafik names symbols <Name>_<theme>_<code>.svg; look next to the layer's other symbols first."""
    m = GRAFIK_URL.search(sibling_url or "")
    folders = [spec.GRAFIK / Path(m.group(1)).parent] if m else []
    folders.append(spec.GRAFIK)
    for folder in folders:
        hits = sorted(folder.rglob(f"*_{theme_code}_{code}.svg")) if folder.exists() else []
        if hits:
            rel = hits[0].relative_to(spec.GRAFIK).as_posix()
            return f"https://raw.githubusercontent.com/GeoDanmarkGeoFA/Grafik/refs/heads/main/{rel}"
    return None


def default_symbol(geometry):
    if geometry == "MultiPoint":
        return QgsMarkerSymbol.createSimple({"name": "circle", "color": "#808080", "size": "2"})
    if geometry == "MultiLineString":
        return QgsLineSymbol.createSimple({"color": "#808080", "width": "0.5"})
    return QgsFillSymbol.createSimple({"color": "128,128,128,80", "outline_color": "#404040"})


def text_field_for(code_field, fields):
    """The derived text field the spec pairs with a code field (e.g. facil_ty_k -> facil_ty)."""
    meta_props = code_field.get("properties") or {}
    if meta_props.get("_text"):
        return meta_props["_text"]
    base = code_field["name"][:-2] if code_field["name"].endswith("_k") else None
    return base if base and any(f["name"] == base for f in fields) else None


def labeling_for(webmap_layer):
    rules = spec.parse_loose((webmap_layer or {}).get("class")) or []
    # A class has two label slots, "label" and "label2", each with its own settings (e.g. 5608 uses label2)
    found = next(((r, p) for r in rules for p in ("label", "label2") if r.get(p) and r.get(f"{p}_text")), None)
    if not found:
        return None
    rule, prefix = found
    get = lambda key: rule.get(f"{prefix}_{key}")  # noqa: E731
    settings = QgsPalLayerSettings()
    text = get("text").strip()
    plain = re.fullmatch(r"\[(\w+)\]", text)
    settings.fieldName = plain.group(1) if plain else re.sub(r"\[(\w+)\]", r'" || "\1" || "', f'"{text}"')
    settings.isExpression = not plain
    fmt = QgsTextFormat()
    font = QFont(str(get("font") or "Arial").capitalize())
    if get("fontweight") == "bold":
        font.setBold(True)
    fmt.setFont(font)
    # MapServer label sizes are points, so 10 is 13 px on screen
    fmt.setSize(number(get("size"), 10))
    fmt.setSizeUnit(Qgis.RenderUnit.Points)
    fmt.setColor(color(get("color"), "#000000"))
    if get("outlinecolor"):
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(color(get("outlinecolor")))
        buffer.setSize(1)
        buffer.setSizeUnit(PIXELS)
        fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    if get("force"):
        # The webmap forces every label; QGIS shows them all but moves them apart where it can
        settings.placementSettings().setOverlapHandling(Qgis.LabelOverlapHandling.AllowOverlapIfRequired)
    if get("maxscaledenom"):
        settings.scaleVisibility = True
        settings.minimumScale = number(get("maxscaledenom"), 0)
    return QgsVectorLayerSimpleLabeling(settings)


# ---------------------------------------------------------------- aliases

ALIASES = spec.read_json(Path(__file__).with_name("field_aliases.json"))
ROOM = re.compile(r"^_(\d)_(.+)$")  # 6122: the same questions for rooms 1-4
# Text fields whose code field isn't found by name or by the spec's code relation
COMPANION = {"oprindelse": "oprindkode", "status": "statuskode", "offentlig": "off_kode",
             "handikap": "handicap_k", "slutttrin": "sluttrin_kode"}


def text_fields(fields, webmap):
    """Text field -> its code field, from the spec's code relations (published) or the webmap's (pending)."""
    fieldconf = spec.parse_loose((webmap or {}).get("fieldconf")) or {}
    out = {}
    for f in fields:
        props = f.get("properties") or spec.parse_loose((fieldconf.get(f["name"]) or {}).get("properties")) or {}
        text = props.get("_text") if isinstance(props, dict) else None
        if text and text != f["name"]:
            out[text] = f["name"]
    return out


def alias_for(table, name, names, text_of):
    """'Alias' for a field (without the field name), or None if there is none."""
    room = ROOM.match(name)
    if room:
        inner = alias_for(table, room.group(2), {ROOM.sub(r"\2", n) for n in names}, text_of)
        return f"Rum {room.group(1)}: {inner}" if inner else None
    alias = ALIASES["tables"].get(table, {}).get(name) or ALIASES["fields"].get(name)
    if alias:
        return alias
    candidates = (text_of.get(name), COMPANION.get(name), f"{name}_kode", f"{name}_k", f"{name.removesuffix('_label')}_kode")
    code = next((c for c in candidates if c and c != name and c in names), None)
    if code:
        code_alias = alias_for(table, code, names, text_of)
        if code_alias:
            return f"{code_alias} – {'etiket' if name.endswith('_label') else 'tekst'}"
    return None


# ---------------------------------------------------------------- forms

def required_input(name, option):
    """A file fetch_sources.py writes in dev/spec/; the run stops if it's missing, rather than quietly
    leaving something out of every style."""
    path = spec.SPEC / name
    if not path.exists():
        raise SystemExit(f"{path} is missing: run tools/fetch_sources.py {option} first")
    return spec.read_json(path)


def authority_default():
    """cvr_kode default: the municipality's own CVR when the login is kom###, e.g. kom101 -> Københavns Kommune.

    A default expression rather than a filtered dropdown, so the form needs no code table at runtime.
    """
    pairs = ", ".join(f"'{k}', '{v}'" for k, v in sorted(required_input("authorities.json", "--authorities").items()))
    return f"map_get(map({pairs}), regexp_substr(@geofa_bruger_id, '^kom(\\\\d{{3}})'))"


@functools.cache
def defaults():
    """Field -> (expression, also on update). The plugin sets @geofa_bruger_id to the GeoFA username."""
    return {"bruger_id": ("@geofa_bruger_id", True), "cvr_kode": (authority_default(), False)}


def has_link(field):
    """Whether a photo field holds a link. The field is read by name: some editable tables (e.g. 5607's)
    don't have the photo fields at all, and a rule naming a missing field can't be evaluated, so QGIS
    would show what it hides, empty."""
    return f"coalesce(attribute(@feature, '{field}'), '') <> ''"


def theme_defaults(table):
    """temakode and temanavn for a new object, as GeoFA's view fills them in once it's saved:
    the number in the table name and the dataset's own table (e.g. 5800 and 't_5800_fac_pkt_t').
    This matches what GeoFA stores for every dataset with public objects in production. A new
    object would otherwise show 0 and NULL until saved. Not on update: they never change for an object."""
    return {"temakode": (dataset_code(table), False), "temanavn": (f"'{table}_t'", False)}


def number_range(codes):
    """(min, max) when a "code list" is just the numbers min..max labelled as themselves."""
    if not codes or any(value != alias or not value.lstrip("-").isdigit() for value, alias in codes):
        return None
    values = sorted(int(value) for value, _ in codes)
    return (values[0], values[-1]) if values == list(range(values[0], values[-1] + 1)) else None



def apply_fields_and_form(layer, dataset, fields, text_of, used):
    layer.dataProvider().addAttributes([QgsField(f["name"], f["qtype"]) for f in fields])
    layer.updateFields()
    config = layer.editFormConfig()
    config.setLayout(Qgis.AttributeFormLayout.DragAndDrop)
    root = config.invisibleRootContainer()
    root.clear()
    theme_tab_name = re.sub(r"\s*\(\d{4}\)\s*$", "", dataset["title"])
    photo_tab_name = "Fotos og GPX" if any(f["name"] == "gpx_link" for f in fields) else "Fotos"
    tabs = {"Generelt": [], theme_tab_name: [], photo_tab_name: [], "Øvrige felter": []}
    names = {f["name"] for f in fields}
    for f in fields:
        idx = layer.fields().indexOf(f["name"])
        alias = alias_for(dataset["table"], f["name"], names, text_of)
        if alias:
            # As in the old plugin layers: "Facilitettype (facil_ty_k)"
            layer.setFieldAlias(idx, f"{alias} ({f['name']})")
        else:
            used.setdefault("fields_without_alias", set()).add(f"{dataset['code']}:{f['name']}")
        editable = f["kind"] in ("general", "theme", "free")
        numbers = number_range(f["codes"])
        if f.get("source"):
            # No list in the style: the plugin fills the dropdown from GeoFA's code list when it
            # adds the layer. Until then, or if GeoFA's list can't be read, the field shows the codes.
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("TextEdit", {"IsMultiline": False, "UseHtml": False}))
        elif numbers:
            # A plain number range from a database check (e.g. 0-9), not a code list
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Range", {
                "Min": numbers[0], "Max": numbers[1], "Step": 1, "Style": "SpinBox", "AllowNull": True}))
        elif f["codes"]:
            options = [{"<ingen værdi>": NULL_VALUE}] + [{alias: value} for value, alias in f["codes"]]
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ValueMap", {"map": options}))
            used.setdefault("lists_without_source", set()).add(f"{dataset['code']}:{f['name']}")
        elif f["kind"] == "photo":
            # Links to GeoFA's photos (and GPX files): a link that opens in the browser
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ExternalResource", PHOTO_LINK))
        elif f["name"] in HTML_FIELDS:
            # Long descriptions in HTML: formatted in the form; the plugin shows the HTML text
            # while the layer is being edited (geofa_plugin/htmlfields.py)
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("TextEdit", {"IsMultiline": True, "UseHtml": True}))
        elif f["qtype"] == QMetaType.Type.QDate:
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("DateTime", {
                "display_format": "yyyy-MM-dd", "field_format": "yyyy-MM-dd", "calendar_popup": True, "allow_null": True}))
        elif f["qtype"] == QMetaType.Type.QDateTime:
            # GeoFA's editing endpoint sends date-times as text in PostgreSQL's format
            # (2025-10-07 00:00:29.814198+00), which only the ISO reading understands; the read-only
            # endpoint sends real date-times, for which the format doesn't matter
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("DateTime", {
                "display_format": "yyyy-MM-dd HH:mm:ss", "field_format": "yyyy-MM-ddTHH:mm:ss", "field_iso_format": True,
                "calendar_popup": True, "allow_null": True}))
        elif f["qtype"] == QMetaType.Type.Bool:
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("CheckBox", {}))
        if f["required"] and editable:
            layer.setFieldConstraint(idx, QgsFieldConstraints.Constraint.ConstraintNotNull,
                                     QgsFieldConstraints.ConstraintStrength.ConstraintStrengthSoft)
        config.setReadOnly(idx, not editable)
        default = defaults().get(f["name"]) or theme_defaults(dataset["table"]).get(f["name"])
        if default:
            layer.setDefaultValueDefinition(idx, QgsDefaultValue(*default))
        if f["kind"] == "photo":
            tab = photo_tab_name
        elif f["kind"] == "general":
            tab = "Generelt"
        elif f["kind"] == "theme" or f["name"] == "note":
            tab = theme_tab_name
        else:
            tab = "Øvrige felter"
        tabs[tab].append((f["name"], idx))
    order = {"Generelt": 0, theme_tab_name: 1, photo_tab_name: 2}
    for tab_name in sorted(tabs, key=lambda t: order.get(t, 3)):
        if not tabs[tab_name] and tab_name == photo_tab_name:
            continue
        container = QgsAttributeEditorContainer(tab_name, root)
        container.setType(Qgis.AttributeEditorContainerType.Tab)
        for name, idx in tabs[tab_name]:
            if tab_name == photo_tab_name:
                # Each photo or GPX link only when there is one: QGIS can hide a container but not a
                # field, so each is in a frameless row of its own. Its label goes above the link,
                # as rows don't share a label column
                row = QgsAttributeEditorContainer(name, container)
                row.setType(Qgis.AttributeEditorContainerType.Row)
                row.setShowLabel(False)
                row.setVisibilityExpression(QgsOptionalExpression(QgsExpression(has_link(name)), True))
                row.addChildElement(QgsAttributeEditorField(name, idx, row))
                container.addChildElement(row)
                config.setLabelOnTop(idx, True)
            else:
                container.addChildElement(QgsAttributeEditorField(name, idx, container))
        if tab_name == photo_tab_name:
            # Only when the object has a photo or GPX link: so never while editing, as the
            # editable (normal) layers have no photo links, and not for objects without photos
            shown = " OR ".join(has_link(name) for name, _ in tabs[tab_name])
            container.setVisibilityExpression(QgsOptionalExpression(QgsExpression(shown), True))
        root.addChildElement(container)
    layer.setEditFormConfig(config)
    return {k: len(v) for k, v in tabs.items() if v}


# ---------------------------------------------------------------- main

@functools.cache
def photo_layers():
    """{"environments": {environment: [table, ...]}, "fields": {table: [photo field, ...]}} (fetch_sources.py --photo-layers)."""
    return required_input("photo_layers.json", "--photo-layers")


def add_photo_fields(table, fields):
    """Mark the photo fields (geofafoto*, gpx_link), and add those only GeoFA's photo-link version has."""
    names = {f["name"] for f in fields}
    for name in photo_layers()["fields"].get(table, []):
        if name not in names:
            fields.append({"name": name, "qtype": QMetaType.Type.QString, "kind": "photo", "required": False,
                           "codes": None, "source": None})
    for f in fields:
        if spec.PHOTO_FIELD.match(f["name"]):
            f["kind"], f["source"], f["codes"] = "photo", None, None


def generate(dataset, webmap, symbols_dir, styles_dir, used):
    geometry = GEOMETRY.get(str((webmap or {}).get("type") or "").upper(), "MultiPolygon")
    fields, meta = spec_fields(dataset)
    if meta:
        for f in fields:
            f["properties"] = (meta["fields"].get(f["name"]) or {}).get("properties") or {}
    add_photo_fields(dataset["table"], fields)
    layer = QgsVectorLayer(f"{geometry}?crs=EPSG:25832", dataset["title"], "memory")
    tabs = apply_fields_and_form(layer, dataset, fields, text_fields(fields, webmap), used)
    renderer, style_note = renderer_for(webmap, geometry, fields, symbols_dir, used)
    layer.setRenderer(renderer)
    labeling = labeling_for(webmap)
    if labeling:
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
    # No map tips: without a template QGIS shows its guess at a name field (often gpx_link or temanavn)
    layer.setMapTipsEnabled(False)
    path = styles_dir / f"{dataset['table']}.qml"
    message, ok = layer.saveNamedStyle(str(path))
    if not ok:
        raise RuntimeError(f"{dataset['table']}: {message}")
    return {"geometry": geometry, "fields": len(fields), "tabs": tabs, "style": style_note,
            "dropdowns": sum(1 for f in fields if f.get("source")),
            # field: [code list table, value column, text column, filter, required]
            "code_lists": {f["name"]: f["source"] + [f["required"]] for f in fields if f.get("source")}}


def spec_commit():
    """The checked-out commit of the Database clone, read from its .git folder: git itself isn't
    on the PATH in OSGeo4W's shell."""
    git = spec.SPEC / "Database" / ".git"
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head[:7]  # a detached HEAD holds the commit itself
    ref = head[5:]
    if (git / ref).exists():
        return (git / ref).read_text(encoding="utf-8").strip()[:7]
    packed = (git / "packed-refs").read_text(encoding="utf-8") if (git / "packed-refs").exists() else ""
    return next((line.split()[0][:7] for line in packed.splitlines() if line.endswith(" " + ref)), "unknown")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated tables to generate (default: all)")
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    for clone in (spec.SPEC / "Database", spec.GRAFIK):
        if not clone.exists():  # without Grafik every symbol would quietly become a plain circle
            raise SystemExit(f"{clone} is missing: clone it as the readme describes")
    app = QgsApplication([], False)
    app.initQgis()
    styles_dir, symbols_dir = spec.OUT / "styles", spec.OUT / "symbols"
    if not only:
        # A full run rebuilds both folders, so styles and symbols no longer used don't linger
        for folder in (styles_dir, symbols_dir):
            shutil.rmtree(folder, ignore_errors=True)
    styles_dir.mkdir(parents=True, exist_ok=True)
    symbols_dir.mkdir(parents=True, exist_ok=True)
    # With the symbols folder as an SVG search path, QGIS stores just the file name in the QML;
    # the plugin adds the same folder to the search paths when it loads layers
    QgsSettings().setValue("svg/searchPathsForSVG", [str(symbols_dir)])

    datasets = spec.datasets()
    webmap = spec.webmap_layers()
    prod = spec.prod_tables()
    counts = spec.read_json(spec.SPEC / "prod_counts.json")
    used, results = {}, {}
    for d in datasets:
        if only and d["table"] not in only:
            continue
        results[d["table"]] = generate(d, webmap.get(d["table"]), symbols_dir, styles_dir, used)
        print(f"{d['table']}: {results[d['table']]['style']}, {results[d['table']]['fields']} fields, "
              f"{results[d['table']]['dropdowns']} dropdowns, tabs {results[d['table']]['tabs']}")

    # With --only, the other datasets keep what the last full run wrote
    previous_path = spec.OUT / "catalogue.json"
    previous = {d["table"]: d for g in (spec.read_json(previous_path)["groups"] if previous_path.exists() else [])
                for d in g["datasets"]}
    groups = []
    for d in datasets:
        if not groups or groups[-1]["name"] != d["group"]:
            groups.append({"name": d["group"], "datasets": []})
        meta = spec.spec_meta(d["table"]) if d["status"] == "published" else None
        props = (meta or {}).get("properties") or {}
        result = results.get(d["table"]) or previous.get(d["table"]) or {}
        groups[-1]["datasets"].append({
            "table": d["table"], "code": d["code"], "title": d["title"],
            "geometry": GEOMETRY.get(str((webmap.get(d["table"]) or {}).get("type") or "").upper()),
            "style": f"styles/{d['table']}.qml", "status": d["status"],
            "spec_page": f"https://confluence.kds.dk/pages/viewpage.action?pageId={d['spec_page_id']}",
            "purpose": (props.get("formaal") or "").strip(),
            "form_version": form_fingerprint(spec.OUT / "styles" / f"{d['table']}.qml"),
            "code_lists": result.get("code_lists") or {},
            "photo_environments": [environment for environment, tables in photo_layers()["environments"].items()
                                   if d["table"] in tables],
        })
    catalogue = {"source": {"spec_commit": spec_commit(), "webmap": spec.WEBMAP_META}, "groups": groups}
    (spec.OUT / "catalogue.json").write_text(json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(datasets, webmap, prod, counts, results, used)
    app.exitQgis()


def write_report(datasets, webmap, prod, counts, results, used):
    spec.REPORTS.mkdir(parents=True, exist_ok=True)
    lines = ["# GeoFA plugin – spec vs webmap vs production WFS", "",
             "Generated by tools/generate_layers.py. The spec is the source of truth; differences are flagged here.", "",
             "| Code | Spec title | Group (spec) | Spec | Webmap title | Webmap group | Prod WFS | Objects (anonymous) | Fields not in prod WFS | Prod fields not in spec |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for d in datasets:
        w = webmap.get(d["table"]) or {}
        wt, wg = spec.clean_title(w.get("f_table_title")), spec.clean_title(w.get("layergroup"))
        prod_fields = {f["name"] for f in spec.read_json(spec.SPEC / "prod_describe" / f"{d['table']}.json") if not f["type"].startswith("gml:")}
        meta = spec.spec_meta(d["table"]) if d["status"] == "published" else None
        spec_names = {n for n, f in (meta or {}).get("fields", {}).items() if f.get("_type") != "geometry"} if meta else prod_fields
        n = counts.get(d["table"])
        lines.append("| {code} | {title} | {group} | {status} | {wt} | {wg} | {prod} | {n} | {missing} | {extra} |".format(
            code=d["code"], title=d["title"], group=d["group"], status=d["status"],
            wt="=" if wt == d["title"] else wt or "–", wg="=" if wg.lower() == d["group"].lower() else wg or "–",
            prod="yes" if d["table"] in prod else "**missing**", n=f"**{n}**" if not n else n,
            missing=", ".join(sorted(spec_names - prod_fields)) or "", extra=", ".join(sorted(prod_fields - spec_names)) or ""))
    lines += ["", "## Other findings", "",
              "- Datasets with 0 objects may only lack *public* objects: counts are what an anonymous user sees.",
              "- Pending datasets (spec page says 'Kommer snart'): fields come from the production WFS, and their code "
              "lists from the webmap's field configuration (the plugin reads them from GeoFA when it adds a layer)."]
    for key in ("fields_without_alias", "missing_svgs", "unhandled_overlays", "unhandled_rules", "webmap_categories_not_in_spec",
                "webmap_spelling_differs", "spec_codes_styled_from_grafik", "spec_codes_without_style", "texts_with_several_codes"):
        if used.get(key):
            lines.append(f"- {key}: {', '.join(sorted(used[key]))}")
    (spec.REPORTS / "difference_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {spec.REPORTS / 'difference_report.md'}; svgs bundled: {len(used.get('svgs', []))}")


if __name__ == "__main__":
    main()
