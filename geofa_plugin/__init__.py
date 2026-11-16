# -*- coding: utf-8 -*-
"""The GeoFA plugin for QGIS. QGIS loads it through classFactory().

This program is free software; you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation; either version 2 of the
License, or (at your option) any later version.
"""


def classFactory(iface):  # noqa: N802 - the name QGIS looks for
    """The plugin, for QGIS's interface iface."""
    from .geofa import GeoFA
    return GeoFA(iface)
