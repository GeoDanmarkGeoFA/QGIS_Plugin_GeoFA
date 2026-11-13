from qgis.core import QgsVectorLayer, QgsProject, QgsDataSourceUri, Qgis, QgsMapLayer, QgsSettings
import os
import os.path
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QProgressDialog, QProgressBar, QApplication
class import_geofa:

    @staticmethod
    def generate_menu_items():
        """Generate the menu items as a function."""
        # to edit menu names edit the one to the right of the colon the left one is the key for the action and
        # should not be changed unless it's absolutely necessary
        menu_items = {
            "Administration": {
                "Skoledistrikter": "Skoledistrikter",
                "Andre distrikter": "Andre distrikter",
                "Pleje- og ældredistrikter": "Pleje- og ældredistrikter",
                "Prognose- og statistik distrikter": "Prognose- og statistik distrikter"
            },
            "Sport, fritid og friluftsliv": {
                "Friluftsliv faciliteter, punkter": "Friluftsliv faciliteter, punkter",
                "Friluftsliv faciliteter, flader": "Friluftsliv faciliteter, flader",
                "Friluftsliv faciliteter, linjer": "Friluftsliv faciliteter, linjer"
            },
            "Vej og trafik": {
                "Ladefaciliteter": "Ladefaciliteter",
                "Cykelknudepunkter": "Cykelknudepunkter",
                "Cykelknudepunktsstrækninger": "Cykelknudepunktsstrækninger"
            },
        }
        return menu_items

    def run_action(self, submenu, plugin_path, update=False):
        """Perform work based on the action name."""

        # Get menu items
        menu_items = import_geofa.generate_menu_items()

        # Run actions
        if submenu == menu_items["Administration"]["Skoledistrikter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5710_born_skole_dis", plugin_path, update=update)
        elif submenu == menu_items["Administration"]["Andre distrikter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5711_and_dis", plugin_path, update=update)
        elif submenu == menu_items["Administration"]["Pleje- og ældredistrikter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5712_plej_aeldr_dis", plugin_path, update=update)
        elif submenu == menu_items["Administration"]["Prognose- og statistik distrikter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5713_prog_stat_dis", plugin_path, update=update)

        elif submenu == menu_items["Sport, fritid og friluftsliv"]["Friluftsliv faciliteter, punkter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5800_fac_pkt", plugin_path, update=update)
        elif submenu == menu_items["Sport, fritid og friluftsliv"]["Friluftsliv faciliteter, flader"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5801_fac_fl", plugin_path, update=update)
        elif submenu == menu_items["Sport, fritid og friluftsliv"]["Friluftsliv faciliteter, linjer"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5802_fac_li", plugin_path, update=update)

        elif submenu == menu_items["Vej og trafik"]["Ladefaciliteter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5607_ladefacilitet", plugin_path, update=update)
        elif submenu == menu_items["Vej og trafik"]["Cykelknudepunkter"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5608_cykelknudepunkter", plugin_path, update=update)
        elif submenu == menu_items["Vej og trafik"]["Cykelknudepunktsstrækninger"]:
            import_geofa.create_geofa_layer(self, submenu, "fkg:t_5609_cykelknudepunktsstraekninger", plugin_path, update=update)

    def d_tables(self, update=False):

        # Lists of all d_tables
        d_tables = ["d_5607_ladefacilitet_type",
                    "d_5607_tilgaengelighed_type",
                    "d_5607_effekt_type",
                    "d_5710_udd_distrikt_type",
                    "d_5711_an_distrikt_type",
                    "d_5712_plej_distrikt_type",
                    "d_5713_prog_distrikt_type",
                    "d_5800_facilitet",
                    "d_5800_saeson",
                    "d_5800_kvalitet",
                    "d_5802_certifi",
                    "d_5802_svaerhed",
                    "d_5802_rutetype",
                    "d_5802_rute_uty",
                    "d_5802_kategori",
                    "d_5802_hierarki",
                    "d_basis_trin",
                    "d_basis_handicapegnet",
                    "d_basis_ansvarlig_myndighed",
                    "d_basis_ja_nej",
                    "d_basis_oprindelse",
                    "d_basis_status",
                    "d_basis_offentlig",
                    "d_basis_belaegning",
                    "d_basis_planstatus",
                    "d_basis_ansva_v"]

        # Get all layers
        layers = [layer.name() for layer in QgsProject.instance().mapLayers().values()]

        dialog = None

        # Add missing layers
        for idx, d_table in enumerate(d_tables):

            if d_table not in layers or update:

                # Set url
                if not self.testmiljo:
                    url = f"https://geofa.geodanmark.dk/api/v2/sql/fkg?q=SELECT%20*%20FROM%20fkg.{d_table}"
                if self.testmiljo:
                    # virker ikke med test lige pt. ændre når det gør
                    url = f"https://geofa-test.geodanmark.dk/api/v2/sql/fkg?q=SELECT%20*%20FROM%20fkg.{d_table}"

                # Update layer if it already exists
                if update:
                    layer = QgsProject.instance().mapLayersByName(d_table)
                    if len(layer) > 0:
                        layer = layer[0]

                        # Get old url
                        data_provider = layer.dataProvider()
                        old_url = data_provider.dataSourceUri()

                        if old_url != url:

                            # Update layer
                            layer.setDataSource(url, d_table, "ogr")

                            # Create the progress dialog when the first table is processed
                            if dialog is None:
                                # Create progress bar
                                dialog = QProgressDialog()
                                bar = QProgressBar(dialog)
                                bar.setTextVisible(True)
                                bar.setMaximum(len(d_tables))
                                dialog.setBar(bar)
                                dialog.setMinimumWidth(300)
                                dialog.setWindowTitle("Opdaterer lag")
                                dialog.setLabelText("Opdaterer GeoFA domæneværditabeller, vent venligst")
                                dialog.show()

                            # Update progress bar
                            bar.setValue(idx + 1)

                            # Process other events to update UI
                            QApplication.processEvents()


                else:
                    # Create layer
                    dlayer = QgsVectorLayer(url, d_table, "ogr")

                    # Set layer properties
                    # https://gis.stackexchange.com/questions/318506/setting-layer-identifiable-seachable-and-removable-with-python-in-qgis-3
                    dlayer.setFlags(
                    (QgsMapLayer.LayerFlag.Private | QgsMapLayer.LayerFlag.Removable | QgsMapLayer.LayerFlag.Searchable))

                    # Check if the layer was loaded successfully
                    if dlayer.isValid():
                        QgsProject.instance().addMapLayer(dlayer)

                        # Create the progress dialog when the first table is processed
                        if dialog is None:
                            # Create progress bar
                            dialog = QProgressDialog()
                            bar = QProgressBar(dialog)
                            bar.setTextVisible(True)
                            bar.setMaximum(len(d_tables))
                            dialog.setBar(bar)
                            dialog.setMinimumWidth(300)
                            dialog.setWindowTitle("Indlæser lag")
                            dialog.setLabelText("Indlæser GeoFA domæneværditabeller, vent venligst")
                            dialog.show()

                        # Update progress bar
                        bar.setValue(idx + 1)

                        # Process other events to update UI
                        QApplication.processEvents()



                    else:
                        iface.messageBar().pushMessage("Error", f'{dlayer.name()} could not be loaded.', level=Qgis.MessageLevel.Critical)

        if dialog is not None:
            dialog.close()

    def create_geofa_layer(self, layer_name, typename, plugin_path, update=False, ):
        """Create a layer from WFS service."""

        # Add d_tables to project
        import_geofa.d_tables(self)

        # Get all layers
        layers = [layer.name() for layer in QgsProject.instance().mapLayers().values()]

        # Flag whether the update happens or not
        run_update_flag = False

        # Create URI for layers and add them to the project
        if layer_name not in layers or update:
            preferCoordinatesForWfsT11 = 'false'
            restrictToRequestBBOX = '1'
            srsname = 'EPSG:25832'

            if not self.testmiljo and not self.wfst:
                url = f'https://geofa.geodanmark.dk/ows/fkg/fkg'
                pagingEnabled = 'false'
            if not self.testmiljo and self.wfst:
                url = f'https://geofa.geodanmark.dk/wfs/{self.username}@fkg/fkg/25832'
                pagingEnabled = 'true'
            if self.testmiljo and not self.wfst:
                url = f'https://geofa-test.geodanmark.dk/ows/fkg/fkg'
                pagingEnabled = 'false'
            if self.testmiljo and self.wfst:
                url = f'https://geofa-test.geodanmark.dk/wfs/{self.username}@fkg/fkg/25832'
                pagingEnabled = 'true'

            version = 'auto'

            # Create connection string
            if self.wfst:

                connection_string = f"user={self.username}@fkg " \
                                    f"password={self.password} " \
                                    f"pagingEnabled={pagingEnabled} " \
                                    f"preferCoordinatesForWfsT11={preferCoordinatesForWfsT11} " \
                                    f"restrictToRequestBBOX={restrictToRequestBBOX} " \
                                    f"srsname={srsname} " \
                                    f"typename={typename} " \
                                    f"url={url} " \
                                    f"version={version}"

            if not self.wfst:
                connection_string = f"pagingEnabled={pagingEnabled} " \
                                    f"preferCoordinatesForWfsT11={preferCoordinatesForWfsT11} " \
                                    f"restrictToRequestBBOX={restrictToRequestBBOX} " \
                                    f"srsname={srsname} " \
                                    f"typename={typename.replace('fkg:','fkg:fkg.')} " \
                                    f"url={url} " \
                                    f"version={version}"

            # Create the URI
            uri = QgsDataSourceUri(connection_string).uri(False)

            # if the layer already exists, update it
            if update:
                # Get the layer
                layer = QgsProject.instance().mapLayersByName(layer_name)
                if len(layer) > 0:
                    layer = layer[0]

                    # Get datasource uri
                    data_provider = layer.dataProvider()
                    old_uri = data_provider.dataSourceUri()

                    # Check if the uri has changed
                    if old_uri != uri:
                        # set run_update_flag to True
                        run_update_flag = True

                        # Update the layer
                        layer.setDataSource(uri, layer_name, "WFS")

                        # Refresh the map view
                        iface.mapCanvas().refresh()

            else:
                # Add svg path, so it can find symbols used in the styles
                # https://gis.stackexchange.com/questions/281698/relative-path-to-the-plugin-folder-for-svg-file-in-qgis3-sld-file
                svg_paths = QgsSettings().value('svg/searchPathsForSVG', [])

                # make sure the svg_paths is a list
                if isinstance(svg_paths, str):
                    svg_paths = [svg_paths]

                if plugin_path + "/geofa_symboler" not in svg_paths:
                    QgsSettings().setValue('svg/searchPathsForSVG', svg_paths + [plugin_path + "/geofa_symboler"])

                # Create the layer
                layer = QgsVectorLayer(uri, layer_name, "WFS")

                # Load style
                style = os.path.join(os.path.dirname(__file__), f'qml/{layer_name}.qml')
                layer.loadNamedStyle(style)

                # Check if the layer was loaded successfully
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)

                    # Refresh the map view
                    iface.mapCanvas().refresh()
                else:
                    iface.messageBar().pushMessage("Error", f'{layer_name} could not be loaded.',level=Qgis.MessageLevel.Critical)
        else:
            iface.messageBar().pushMessage("Info", f'{layer_name} already exists.', level=Qgis.MessageLevel.Info, duration=5)

        if run_update_flag:
            iface.messageBar().pushMessage("Info", f'GeoFA lag opdateret.', level=Qgis.MessageLevel.Info, duration=15)
