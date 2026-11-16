"""Checks of what the plugin ships: the 80 styles against the catalogue, and the plugin as packed
for plugins.qgis.org. Offline; run with the other tests:

    python-qgis.bat -m unittest discover -s geofa_plugin/test -t .
"""
import configparser
import importlib
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

# QGIS, offline and in a throwaway profile, as for the other tests
from geofa_plugin.test.test_qgis_compatibility import FakeIface  # noqa: F401 (sets up QGIS first)

from qgis.core import QgsExpression, QgsExpressionContext, QgsFeature, QgsField, QgsFields, QgsVectorLayer
from qgis.PyQt.QtCore import QMetaType

from geofa_plugin import htmlfields
from geofa_plugin.catalogue import SYMBOLS_DIR, Catalogue, form_fingerprint
# What the release ZIP leaves out, and the secret check, as tools/build_zip.py does it
from tools.build_zip import RELEASE_EXCLUDES, SECRET

PLUGIN = Path(__file__).resolve().parents[1]


def _qgs_fields(names):
    fields = QgsFields()
    for name in names:
        fields.append(QgsField(name, QMetaType.Type.QString))
    return fields


def _fields(root):
    """{field: (widget type, {option: value})} from a QML's field configuration."""
    out = {}
    for field in root.iter("field"):
        widget = field.find("editWidget")
        if widget is None:
            continue
        options = {option.get("name"): option.get("value") for option in widget.iter("Option") if option.get("name")}
        out[field.get("name")] = (widget.get("type"), options)
    return out


class StyleTests(unittest.TestCase):
    """The generated styles and catalogue agree, and hold what the plugin expects."""

    @classmethod
    def setUpClass(cls):
        cls.datasets = Catalogue().datasets()
        cls.styles = {d.table: ElementTree.parse(d.style_path).getroot() for d in cls.datasets}

    def test_every_style_loads_in_qgis(self):
        for dataset in self.datasets:
            layer = QgsVectorLayer(f"{dataset.geometry or 'MultiPolygon'}?crs=EPSG:25832", dataset.title, "memory")
            message, ok = layer.loadNamedStyle(dataset.style_path)
            self.assertTrue(ok, f"{dataset.table}: {message}")
            self.assertIsNotNone(layer.renderer(), dataset.table)

    def test_catalogue_was_generated_from_these_styles(self):
        # A style changed by hand without running tools/generate_layers.py would leave an old form version
        for dataset in self.datasets:
            self.assertEqual(dataset.form_version, form_fingerprint(dataset.style_path), dataset.table)

    def test_every_field_has_an_alias_with_its_name(self):
        for table, root in self.styles.items():
            aliases = {alias.get("field"): alias.get("name") for alias in root.iter("alias")}
            for field in _fields(root):
                self.assertTrue((aliases.get(field) or "").endswith(f"({field})"), f"{table}.{field}: {aliases.get(field)}")

    def test_code_list_fields_get_their_lists_from_geofa(self):
        for dataset in self.datasets:
            fields = _fields(self.styles[dataset.table])
            for field, source, _ in dataset.code_lists:
                self.assertIn(field, fields, f"{dataset.table}.{field}")
                self.assertEqual(fields[field][0], "TextEdit", f"{dataset.table}.{field}: no list in the style")
                self.assertTrue(source.table.startswith("fkg.d_"), f"{dataset.table}.{field}: {source.table}")
            baked = [field for field, (kind, _) in fields.items() if kind == "ValueMap"]
            self.assertEqual(baked, [], f"{dataset.table}: lists baked into the style")

    def test_required_code_list_fields_are_marked_while_empty(self):
        # Every dropdown starts with "<ingen værdi>"; for a field GeoFA requires, a not-null constraint
        # marks it until a value is chosen. Soft (2): QGIS warns but doesn't block, so an older object
        # with the field empty can still be saved; GeoFA's database doesn't accept a new empty value
        required = 0
        for dataset in self.datasets:
            constraints = {c.get("field"): c for c in self.styles[dataset.table].iter("constraint")
                           if c.get("notnull_strength") is not None}
            for field, _, is_required in dataset.code_lists:
                if is_required:
                    required += 1
                    self.assertEqual(constraints[field].get("notnull_strength"), "2", f"{dataset.table}.{field}")
        self.assertGreater(required, 50)

    def test_new_objects_get_temakode_and_temanavn_as_geofa_fills_them(self):
        # GeoFA's view fills them on saving: the number in the table name, and the dataset's own table
        for table, root in self.styles.items():
            defaults = {d.get("field"): (d.get("expression"), d.get("applyOnUpdate")) for d in root.iter("default")}
            self.assertEqual(defaults["temakode"], (re.match(r"t_(\d+)_", table).group(1), "0"), table)
            self.assertEqual(defaults["temanavn"], (f"'{table}_t'", "0"), table)

    def test_html_descriptions_are_formatted(self):
        found = 0
        for table, root in self.styles.items():
            fields = _fields(root)
            for name in htmlfields.HTML_FIELDS:
                if name in fields:
                    found += 1
                    self.assertEqual(fields[name][0], "TextEdit", f"{table}.{name}")
                    self.assertEqual(fields[name][1].get("UseHtml"), "true", f"{table}.{name}")
        self.assertGreaterEqual(found, 9)  # 5800, 5801 and 5802 have all three

    def test_photo_links_open_in_the_browser_on_their_own_tab(self):
        photo_field = re.compile(r"^(geofafoto\d*|gpx_link)$")
        found = set()
        for dataset in self.datasets:
            root = self.styles[dataset.table]
            photos = [name for name in _fields(root) if photo_field.match(name)]
            if not photos:
                continue
            found.add(dataset.table)
            for name in photos:
                kind, options = _fields(root)[name]
                self.assertEqual((kind, options.get("UseLink")), ("ExternalResource", "true"), f"{dataset.table}.{name}")
            tab = next(c for c in root.iter("attributeEditorContainer") if c.get("name", "").startswith("Fotos"))
            self.assertEqual(sorted(f.get("name") for f in tab.iter("attributeEditorField")), sorted(photos))
            # Shown only for objects with a photo (never while editing: the editable layers have no links).
            # The fields are read by name: some editable tables (e.g. 5607's) don't have them, and a rule
            # naming a missing field can't be evaluated, so QGIS would show the tab, empty
            rule = QgsExpression(tab.get("visibilityExpression") or "")
            self.assertEqual(tab.get("visibilityExpressionEnabled"), "1", dataset.table)
            for fields, values, shown in ((["navn"], {}, False), (photos, {}, False),
                                          (photos, {photos[0]: "https://geofa.geodanmark.dk/foto.jpg"}, True)):
                feature = QgsFeature(_qgs_fields(fields))
                for name, value in values.items():
                    feature[name] = value
                context = QgsExpressionContext()
                context.setFeature(feature)
                self.assertEqual(bool(rule.evaluate(context)), shown, f"{dataset.table}: {fields} {values}")
                self.assertFalse(rule.hasEvalError(), f"{dataset.table}: {rule.evalErrorString()}")
            # Each link in a row of its own, shown only when that field has a link, label above it
            rows = tab.findall("attributeEditorContainer")
            self.assertEqual(sorted(row.get("name") for row in rows), sorted(photos), dataset.table)
            on_top = {f.get("name") for f in root.iter("field") if f.get("labelOnTop") == "1"}
            for row in rows:
                self.assertEqual((row.get("type"), row.get("showLabel")), ("Row", "0"), dataset.table)
                own = QgsExpression(row.get("visibilityExpression"))
                for value, shown in (("https://geofa.geodanmark.dk/foto.jpg", True), (None, False)):
                    feature = QgsFeature(_qgs_fields(photos))
                    feature[row.get("name")] = value
                    context = QgsExpressionContext()
                    context.setFeature(feature)
                    self.assertEqual(bool(own.evaluate(context)), shown, f"{dataset.table}.{row.get('name')}")
                self.assertIn(row.get("name"), on_top, dataset.table)
        self.assertTrue({"t_5800_fac_pkt", "t_5607_ladefacilitet", "t_6205_bygningsvurdering"} <= found)
        environments = {d.table: d.photo_environments for d in self.datasets}
        self.assertEqual(environments["t_5800_fac_pkt"], ("production", "test"))
        self.assertEqual(environments["t_5607_ladefacilitet"], ("production",))
        self.assertEqual(environments["t_5710_born_skole_dis"], ())

    def test_map_tips_are_off(self):
        # Without a template QGIS would show its guess at a name field, such as gpx_link
        for table, root in self.styles.items():
            tips = root.findall("mapTip")
            self.assertEqual([(tip.get("enabled"), tip.text) for tip in tips], [("0", None)], table)

    def test_every_symbol_the_styles_use_is_shipped(self):
        for table, root in self.styles.items():
            for option in root.iter("Option"):
                value = option.get("value") or ""
                if option.get("name") == "name" and value.lower().endswith(".svg"):
                    self.assertTrue((Path(SYMBOLS_DIR) / value).exists(), f"{table}: {value}")

    def test_form_fingerprint_ignores_attribute_order(self):
        folder = Path(tempfile.mkdtemp(prefix="geofa_qml_"))
        one, two = folder / "one.qml", folder / "two.qml"
        one.write_text('<qgis version="3.44"><aliases><alias field="navn" index="0" name="Navn (navn)"/></aliases>'
                       '<renderer-v2 type="a"/></qgis>', encoding="utf-8")
        two.write_text('<qgis version="4.2"><aliases><alias name="Navn (navn)" index="0" field="navn"/></aliases>'
                       '<renderer-v2 type="b"/></qgis>', encoding="utf-8")
        self.assertEqual(form_fingerprint(one), form_fingerprint(two))  # symbology and versions don't count
        two.write_text('<qgis><aliases><alias field="navn" index="0" name="Facilitetnavn (navn)"/></aliases></qgis>',
                       encoding="utf-8")
        self.assertNotEqual(form_fingerprint(one), form_fingerprint(two))


class PackageTests(unittest.TestCase):
    """The plugin as packed for plugins.qgis.org: folder geofa/ with geofa_plugin's files, minus tests etc."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="geofa_package_"))
        cls.package = cls.root / "geofa"
        shutil.copytree(PLUGIN, cls.package, ignore=shutil.ignore_patterns(*RELEASE_EXCLUDES))

    def test_metadata_is_complete(self):
        metadata = configparser.ConfigParser(interpolation=None)
        metadata.read(self.package / "metadata.txt", encoding="utf-8")
        general = metadata["general"]
        for key in ("name", "qgisMinimumVersion", "qgisMaximumVersion", "description", "about", "version",
                    "author", "email", "repository", "tracker", "homepage", "icon"):
            self.assertTrue(general.get(key), key)
        self.assertEqual(general["qgisMinimumVersion"], "3.34")
        self.assertGreaterEqual(float(general["qgisMaximumVersion"]), 4.0)
        self.assertEqual(general.get("supportsQt6"), "True")  # QGIS 4 lists only plugins that say so
        self.assertTrue((self.package / general["icon"]).exists())
        # Each version has a changelog entry, newest first
        self.assertRegex(general["version"], r"^\d+\.\d+\.\d+$")
        self.assertIn(f"version {general['version']},", general["changelog"].splitlines()[0])

    def test_package_holds_no_tests_or_credentials(self):
        self.assertFalse((self.package / "test").exists())
        self.assertFalse(list(self.package.rglob(".env")))
        self.assertFalse([p for p in self.package.rglob(".*")])  # plugins.qgis.org turns down hidden files
        for path in self.package.rglob("*"):
            if path.suffix.lower() in (".py", ".txt", ".json", ".qml", ".md", ".ui", ".xml", ".cfg"):
                match = SECRET.search(path.read_text(encoding="utf-8", errors="replace"))
                self.assertIsNone(match, f"{path.relative_to(self.root)}: {match.group(1) if match else ''}")

    def test_package_loads_in_qgis(self):
        sys.path.insert(0, str(self.root))
        try:
            module = importlib.import_module("geofa")
            iface = FakeIface()
            plugin = module.classFactory(iface)
            plugin.initGui()
            self.assertEqual(len(plugin.catalogue.datasets()), 80)
            self.assertEqual(plugin.menu.title(), "&GeoFA")
            plugin.unload()
            self.assertEqual(iface.locator_filters, [])
        finally:
            sys.path.remove(str(self.root))
            for name in [name for name in sys.modules if name == "geofa" or name.startswith("geofa.")]:
                del sys.modules[name]
