# -*- coding: utf-8 -*-
"""GeoFA in QGIS's search bar (the locator): words typed find a dataset by its group, title or
theme code, and the result adds it. "geofa <words>" searches the GeoFA datasets only."""
from qgis.core import QgsLocatorFilter, QgsLocatorResult


class LayerLocatorFilter(QgsLocatorFilter):
    def __init__(self, data=None):
        super().__init__()
        # Shared with the clones QGIS makes of the filter for its search threads
        self.data = data or LayerLocatorFilterData()

    def set_searchable_layers(self, searchable_layers):
        self.data.set_searchable_layers(searchable_layers)

    def clone(self):
        return LayerLocatorFilter(data=self.data)

    def name(self):
        return "geofa"

    def displayName(self):
        return "GeoFA"

    def priority(self):
        return QgsLocatorFilter.Priority.Low

    def prefix(self):
        return "geofa"

    def flags(self):
        return QgsLocatorFilter.Flag.FlagFast

    def fetchResults(self, query, context, feedback):
        for layer in self.data.get_matching_layers(query):
            result = QgsLocatorResult()
            result.filter = self
            result.displayString = layer["title"]
            result.userData = layer["index"]
            result.score = 0
            self.resultFetched.emit(result)

    def triggerResult(self, result):
        self.data.get_action(result.userData).trigger()


class LayerLocatorFilterData:
    """The searchable datasets: their result titles, what they are found by, and the menu actions
    that add them."""

    def __init__(self):
        self.layers = []

    def set_searchable_layers(self, searchable_layers):
        """searchable_layers: [{"title", "category" (the group), "code", "action"}]."""
        self.layers = [{"index": index, "title": f'{layer["title"]} ({layer["category"]}, GeoFA)',
                        "search": self.create_search_string(layer), "action": layer["action"]}
                       for index, layer in enumerate(searchable_layers)]

    @staticmethod
    def create_search_string(layer):
        """Group, title and theme code (e.g. "5800"), lower case, with / and - as word breaks and a
        space in front, so a word typed matches the start of a word."""
        search_string = f'{layer["category"]} {layer["title"]} {layer.get("code", "")}'
        return " " + search_string.replace("/", " ").replace("-", " ").lower()

    def get_matching_layers(self, query):
        """The layers with a word starting with each word typed."""
        terms = query.lower().split()
        return [layer for layer in self.layers if all(" " + term in layer["search"] for term in terms)]

    def get_action(self, index):
        return self.layers[index]["action"]
