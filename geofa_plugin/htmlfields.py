# -*- coding: utf-8 -*-
"""Long descriptions written in HTML: lang_beskr, and its English and German versions.

While a layer is read-only, the form shows them formatted (paragraphs, bold, links). While
it's being edited, the form shows the HTML itself as text, so what is saved is exactly what
the user typed: Qt's formatted-text editor would rewrite the HTML.
"""
import functools

from qgis.core import QgsEditorWidgetSetup

HTML_FIELDS = ("lang_beskr", "uk_l_beskr", "d_l_beskr")
OWN_WIDGETS = ("TextEdit", "")  # any other widget is the user's own choice and is left alone
# Set on a layer object once its editing is followed. Not a set of layer ids: QGIS gives a layer
# its saved id again when a project is reopened, and the new layer object must be followed too
FOLLOWED_PROPERTY = "geofa_html_followed"


def setup(html):
    return QgsEditorWidgetSetup("TextEdit", {"IsMultiline": True, "UseHtml": html})


def show(layer, html):
    """Show the layer's HTML fields formatted (html=True) or as their HTML text."""
    fields = layer.fields()
    for name in HTML_FIELDS:
        index = fields.indexOf(name)
        if index < 0:
            continue
        current = layer.editorWidgetSetup(index)
        if current.type() not in OWN_WIDGETS:
            continue
        config = current.config()
        if current.type() == "TextEdit" and bool(config.get("UseHtml")) == html and config.get("IsMultiline"):
            continue
        layer.setEditorWidgetSetup(index, setup(html))


def follow(layer):
    """Switch the layer's HTML fields as it goes in and out of editing. Returns whether it has any."""
    if not any(layer.fields().indexOf(name) >= 0 for name in HTML_FIELDS):
        return False
    if not layer.property(FOLLOWED_PROPERTY):
        layer.setProperty(FOLLOWED_PROPERTY, True)
        layer.editingStarted.connect(functools.partial(show, layer, False))
        layer.editingStopped.connect(functools.partial(show, layer, True))
    show(layer, not layer.isEditable())
    return True
