# -*- coding: utf-8 -*-
"""Adding GeoFA layers to the project, and making them read-only or editable.

The test/production setting only decides where new layers come from: a layer stays in
the environment it was added from, and test layers are named " [TEST]", so the project
shows which is which. Editing (WFS-T with the user's own login from QGIS's password
store) applies to the layers from the chosen environment; the others stay read-only.
"""
from dataclasses import dataclass, replace

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (Qgis, QgsDataSourceUri, QgsExpressionContextUtils, QgsMapLayer, QgsProject, QgsSettings,
                       QgsVectorLayer)

from . import credentials, municipalities
from .catalogue import RENAMED_TABLES, SYMBOLS_DIR, catalogue

PRODUCTION_HOST = "https://geofa.geodanmark.dk"
TEST_HOST = "https://geofa-test.geodanmark.dk"
GEOFA_DOMAIN = "geodanmark.dk"  # in the source of every GeoFA layer, from any plugin version
TABLE_PROPERTY = "geofa/table"  # set on every layer the plugin adds
FORM_PROPERTY = "geofa/form"  # the form version the layer got (see Dataset.form_version)
FORM_CATEGORIES = (QgsMapLayer.StyleCategory.Fields | QgsMapLayer.StyleCategory.Forms
                   | QgsMapLayer.StyleCategory.MapTips)
OLD_DOMAIN_SOURCE = "/api/v2/sql/fkg"  # how 0.36 loaded the fkg.d_* tables into projects
PHOTO_SCHEMA = "fkg_foto_gpx_link"  # GeoFA's photo-link versions of some tables
USER_VARIABLE = "geofa_bruger_id"  # the forms fill bruger_id (and cvr_kode) from it
TEST_SUFFIX = " [TEST]"
# GeoFA gives each login access to some of its datasets; a layer the login can't read shows the public objects
NO_ACCESS_MESSAGE = ("Dit login har måske ikke adgang til {names} i GeoFA, så der vises kun de offentlige objekter, "
                     "uden redigering.")
# Only the objects in the map view are fetched, page by page
COMMON_PARAMS = {"pagingEnabled": "true", "preferCoordinatesForWfsT11": "false", "restrictToRequestBBOX": "1",
                 "srsname": "EPSG:25832", "version": "1.1.0"}


@dataclass(frozen=True)
class Mode:
    """The settings as they affect the layers. edit: use the stored login (editable layers, which
    also show the objects that aren't public); test: new layers come from the test environment."""
    edit: bool
    test: bool
    username: str
    kommune: str = ""  # komkode of the municipality filter (municipalities.py); empty: the whole country

    @classmethod
    def from_settings(cls, settings):
        # Editing needs a stored GeoFA login; without one the plugin only shows the layers
        return cls(edit=bool(settings.value("wfst")) and credentials.has_login(), test=bool(settings.value("testmiljo")),
                   username=(settings.value("username") or "").strip(),
                   kommune=(settings.value("kommune") or "").strip())


def environment(mode):
    return "test" if mode.test else "production"


def layer_source(table, mode):
    """The WFS source for a GeoFA table in the given mode. Never holds a password.

    Read-only layers come from GeoFA's photo-link version of the table (schema fkg_foto_gpx_link)
    where there is one: the same layer, with links to GeoFA's photos filled in. Editing always
    uses the normal table, which is the one that can be edited.
    """
    host = TEST_HOST if mode.test else PRODUCTION_HOST
    dataset = catalogue().get(table)
    uri = QgsDataSourceUri()
    if mode.edit:
        uri.setAuthConfigId(credentials.AUTHCFG_ID)
        uri.setParam("url", f"{host}/wfs/{mode.username}@fkg/fkg/25832")
        uri.setParam("typename", f"fkg:{table}")
    elif dataset is not None and environment(mode) in dataset.photo_environments:
        uri.setParam("url", f"{host}/ows/fkg/{PHOTO_SCHEMA}")
        uri.setParam("typename", f"fkg:{PHOTO_SCHEMA}.{table}")
    else:
        uri.setParam("url", f"{host}/ows/fkg/fkg")
        uri.setParam("typename", f"fkg:fkg.{table}")
    for key, value in COMMON_PARAMS.items():
        uri.setParam(key, value)
    municipality_filter = municipalities.intersects_filter(mode.kommune)
    if municipality_filter:
        uri.setParam("filter", municipality_filter)
        # With a municipality the layer holds that municipality's objects, read once; QGIS would
        # otherwise combine the filter with the map view's box, re-serialised at more than twice
        # its length, which takes larger municipalities over GeoFA's ~8,190-character URL limit
        uri.removeParam("restrictToRequestBBOX")
    return uri.uri(False)


def _source_key(source):
    """The parts of a source repoint() compares: a layer whose key differs from its target's gets
    a new source. A change to COMMON_PARAMS alone doesn't reach layers already in projects."""
    uri = QgsDataSourceUri(source)
    return uri.param("url"), uri.param("typename"), uri.authConfigId(), uri.param("version"), uri.param("filter")


def _typename_table(uri):
    """The table in a GeoFA source's typename (fkg:t_5800_fac_pkt, fkg:fkg.t_5800_fac_pkt, ...)."""
    return uri.param("typename").split(":")[-1].split(".")[-1]


def table_of(layer):
    """The GeoFA table a project layer shows, or None if it isn't a GeoFA layer."""
    table = layer.customProperty(TABLE_PROPERTY)
    if table:
        return RENAMED_TABLES.get(table, table)
    if layer.providerType() != "WFS":
        return None
    # Layers added by older versions of the plugin: recognise them by their source
    uri = QgsDataSourceUri(layer.source())
    if GEOFA_DOMAIN not in uri.param("url"):
        return None
    name = _typename_table(uri)
    return RENAMED_TABLES.get(name, name) if name.startswith("t_") else None


def in_test(layer):
    """Whether a GeoFA layer shows GeoFA's test environment."""
    return TEST_HOST.split("://")[1] in QgsDataSourceUri(layer.source()).param("url")


def host_of(layer):
    """The GeoFA host (production or test) a layer comes from; its code lists are read from the same one."""
    return TEST_HOST if in_test(layer) else PRODUCTION_HOST


def geofa_layers(project=None):
    """[(layer, table)] for the project's layers that show a dataset in the catalogue."""
    project = project or QgsProject.instance()
    return [(layer, table) for layer in project.mapLayers().values()
            if (table := table_of(layer)) and catalogue().get(table)]


def layer_name(name, mode):
    """The layer's name with " [TEST]" when it shows the test environment."""
    name = name.removesuffix(TEST_SUFFIX)
    return name + TEST_SUFFIX if mode.test else name


def ensure_symbol_path():
    """Add the plugin's symbol folder to QGIS's SVG search paths: the styles name their symbols
    by file name only."""
    settings = QgsSettings()
    paths = settings.value("svg/searchPathsForSVG", []) or []
    if isinstance(paths, str):
        paths = [paths]
    if SYMBOLS_DIR not in paths:
        settings.setValue("svg/searchPathsForSVG", list(paths) + [SYMBOLS_DIR])


def set_user_variable(username, project=None):
    """Make @geofa_bruger_id the current user's GeoFA username.

    A global variable, so it's never saved in projects; a project variable from an older
    version (perhaps a colleague's username) would override it, so that one is removed.
    """
    QgsExpressionContextUtils.setGlobalVariable(USER_VARIABLE, username)
    project = project or QgsProject.instance()
    variables = project.customVariables()
    if USER_VARIABLE in variables:
        del variables[USER_VARIABLE]
        project.setCustomVariables(variables)


def _group_node(project, name):
    root = project.layerTreeRoot()
    return root.findGroup(name) or root.insertGroup(0, name)


def add_dataset(dataset, mode, message_bar, project=None):
    """Add a GeoFA dataset to the project in the given mode. Returns the layer, or None."""
    project = project or QgsProject.instance()
    for layer, table in geofa_layers(project):
        # The same dataset may be in the project from both production and test
        if table == dataset.table and in_test(layer) == mode.test:
            message_bar.pushMessage("GeoFA", f"»{layer.name()}« er allerede i projektet.",
                                    level=Qgis.MessageLevel.Info, duration=5)
            return layer
    if mode.edit and not credentials.ensure_login(mode.username):
        message_bar.pushMessage(
            "GeoFA", "Der er ikke gemt et GeoFA-login. Indtast brugernavn og kode under "
                     "GeoFA › Indstillinger … for at bruge dit login.",
            level=Qgis.MessageLevel.Warning, duration=15)
        return None
    ensure_symbol_path()
    set_user_variable(mode.username, project)
    name = layer_name(dataset.title, mode)
    layer = QgsVectorLayer(layer_source(dataset.table, mode), name, "WFS")
    if not layer.isValid() and mode.edit:
        # GeoFA gives a login access dataset by dataset; without access, the public objects instead
        public = QgsVectorLayer(layer_source(dataset.table, replace(mode, edit=False)), name, "WFS")
        if public.isValid():
            message_bar.pushMessage("GeoFA", NO_ACCESS_MESSAGE.format(names=f"»{dataset.title}«"),
                                    level=Qgis.MessageLevel.Warning, duration=15)
            layer = public
    if not layer.isValid():
        where = "GeoFA's testmiljø" if mode.test else "GeoFA"
        message_bar.pushMessage("GeoFA", f"»{dataset.title}« kunne ikke hentes fra {where}.",
                                level=Qgis.MessageLevel.Critical, duration=15)
        return None
    layer.loadNamedStyle(dataset.style_path)
    layer.setCustomProperty(TABLE_PROPERTY, dataset.table)
    layer.setCustomProperty(FORM_PROPERTY, dataset.form_version)
    project.addMapLayer(layer, False)
    _group_node(project, dataset.group).insertLayer(0, layer)
    return layer


def replace_layer(project, layer, source, name):
    """Swap a GeoFA layer for a new one with another source, keeping its style, filter and place.

    Changing the source in place (setDataSource) crashes QGIS while a WFS layer is still
    downloading, so the layer is replaced the way a user would: add the new one, remove the old.
    Returns the new layer, or None when the new source can't be read (the old layer stays) or
    the old layer left the project while the new one loaded.
    """
    new = QgsVectorLayer(source, name, "WFS")
    if not new.isValid() or not _in_project(project, layer):
        return None
    style = QDomDocument()
    layer.exportNamedStyle(style)
    new.importNamedStyle(style)
    for key in layer.customPropertyKeys():
        new.setCustomProperty(key, layer.customProperty(key))
    # The user's own filter carries over. A WFS layer's subset string is its "filter" setting, so
    # the plugin's municipality filter shows up here too; that one comes from the new source instead
    if layer.subsetString() and not municipalities.is_municipality_filter(layer.subsetString()):
        new.setSubsetString(layer.subsetString())
    project.addMapLayer(new, False)
    root = project.layerTreeRoot()
    node = root.findLayer(layer.id())
    parent = node.parent() if node else root
    index = parent.children().index(node) if node else 0
    new_node = parent.insertLayer(index, new)
    if node:
        new_node.setItemVisibilityChecked(node.itemVisibilityChecked())
        new_node.setExpanded(node.isExpanded())
    project.removeMapLayer(layer.id())
    return new


def _in_project(project, layer):
    """Whether the layer is still in the project. Loading a WFS layer runs Qt's event loop, where
    the plugin itself may swap layers (when the login is removed in QGIS's Options, say), so a
    layer in hand can be gone and must not be touched. Compared by identity: a gone layer's
    Python object is left, but its C++ object is deleted."""
    return any(layer is other for other in project.mapLayers().values())


def editing_layers(project=None):
    """GeoFA layers being edited right now; they can't change source until saved or rolled back."""
    return [layer for layer, _ in geofa_layers(project) if layer.isEditable()]


def target_source(layer, table, mode):
    """The source a GeoFA layer should have in the given mode: in its own environment,
    editable only when editing is on and the layer is from the chosen environment, and
    with the chosen municipality filter."""
    test = in_test(layer)
    return layer_source(table, replace(mode, edit=mode.edit and test == mode.test, test=test))


def repoint(mode, project=None):
    """Give the project's GeoFA layers the sources the mode asks for: read-only or editable, the
    username and the municipality filter.

    Layers never move between production and test, and keep their names. A layer the login can't
    read gets the read-only source with the public objects instead.
    Returns (number of layers changed, names of layers being edited, names of layers that
    couldn't be read in the new mode, names of layers left read-only because the login couldn't
    read them); layers being edited and layers that couldn't be read are left as they were.
    """
    project = project or QgsProject.instance()
    changed, editing, failed, public_only = 0, [], [], []
    for layer, table in geofa_layers(project):
        if not _in_project(project, layer):  # swapped or removed while an earlier layer loaded
            continue
        if layer.providerType() != "WFS":  # e.g. a GeoFA layer saved to a file: its source isn't ours to change
            continue
        source = target_source(layer, table, mode)
        if _source_key(layer.source()) == _source_key(source):
            continue
        if layer.isEditable():
            editing.append(layer.name())
            continue
        name = layer.name()
        # Layers from older versions are recognised only by their source: tag them, so the new
        # layer (which gets the old one's properties) is recognised by its table
        layer.setCustomProperty(TABLE_PROPERTY, table)
        if replace_layer(project, layer, source, name):
            changed += 1
            continue
        if not _in_project(project, layer):  # swapped or removed while the new one loaded
            continue
        public = target_source(layer, table, replace(mode, edit=False))
        if public == source:
            failed.append(name)
        elif _source_key(layer.source()) == _source_key(public):
            public_only.append(name)
        elif replace_layer(project, layer, public, name):
            changed += 1
            public_only.append(name)
        elif _in_project(project, layer):
            failed.append(name)
    return changed, editing, failed, public_only


def layers_outside(mode, project=None):
    """GeoFA layers from the other environment than the chosen one."""
    return [layer for layer, _ in geofa_layers(project) if in_test(layer) != mode.test]


def mark_test_layers(project=None):
    """Name test layers " [TEST]" (older versions didn't). Returns the number renamed."""
    renamed = 0
    for layer, _ in geofa_layers(project):
        if in_test(layer) and not layer.name().endswith(TEST_SUFFIX):
            layer.setName(layer.name() + TEST_SUFFIX)
            renamed += 1
    return renamed


def update_form(layer, dataset):
    """Give a layer the plugin's current fields and form: aliases, widgets, defaults, tabs, and
    map tips switched off.

    Its symbology, labels and filter stay as they are; the caller then fills the dropdowns from
    GeoFA (CodeLists.fill). Returns whether the style could be read.
    """
    _, ok = layer.loadNamedStyle(dataset.style_path, categories=FORM_CATEGORIES)
    if ok:
        layer.setCustomProperty(FORM_PROPERTY, dataset.form_version)
    return ok


def outdated_layers(project=None):
    """GeoFA layers whose form differs from the plugin's (every layer from 0.36 among them): [(layer, dataset)]."""
    return [(layer, dataset) for layer, table in geofa_layers(project)
            if layer.customProperty(FORM_PROPERTY) != (dataset := catalogue().get(table)).form_version]


def code_list_layers(project=None):
    """GeoFA layers with the plugin's forms, whose dropdowns are filled from GeoFA: [(layer, dataset, host)].

    Layers from 0.36 are left out until their forms are updated; they still use 0.36's tables.
    """
    return [(layer, catalogue().get(table), host_of(layer)) for layer, table in geofa_layers(project)
            if layer.customProperty(FORM_PROPERTY)]


def old_domain_layers(project=None):
    """The fkg.d_* tables 0.36 put in projects (as hidden layers) that no form uses any more."""
    project = project or QgsProject.instance()
    layers = list(project.mapLayers().values())
    candidates = [layer for layer in layers if layer.providerType() == "ogr"
                  and OLD_DOMAIN_SOURCE in layer.source() and "fkg.d_" in layer.source()]
    used = set()
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue
        for index in range(layer.fields().count()):
            setup = layer.editorWidgetSetup(index)
            if setup.type() == "ValueRelation":
                used.update({setup.config().get("Layer"), setup.config().get("LayerName")})
    return [layer for layer in candidates if layer.id() not in used and layer.name() not in used]


def fix_renamed_tables(project=None):
    """Point layers from older versions at tables GeoFA has since renamed (5608, 5609)."""
    project = project or QgsProject.instance()
    fixed = 0
    for layer in list(project.mapLayers().values()):
        if layer.providerType() != "WFS":
            continue
        uri = QgsDataSourceUri(layer.source())
        typename = uri.param("typename")
        old = _typename_table(uri)
        if GEOFA_DOMAIN in uri.param("url") and old in RENAMED_TABLES:
            uri.removeParam("typename")  # setParam would add a second typename, not replace it
            uri.setParam("typename", typename.replace(old, RENAMED_TABLES[old]))
            layer.setCustomProperty(TABLE_PROPERTY, RENAMED_TABLES[old])
            if replace_layer(project, layer, uri.uri(False), layer.name()):
                fixed += 1
    return fixed
