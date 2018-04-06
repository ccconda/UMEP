# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DSMGenerator
                                 A QGIS plugin
 This plugin generates a DSM from DEM and OSM or other polygon height data.
                              -------------------
        begin                : 2017-10-26
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Nils Wallenberg
        email                : nils.wallenberg@gvc.gu.se
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, QFileInfo, QVariant
from PyQt4.QtGui import QAction, QIcon, QFileDialog, QMessageBox, QButtonGroup
from qgis.gui import QgsMapLayerComboBox, QgsMapLayerProxyModel, QgsFieldComboBox, QgsFieldProxyModel
from qgis.core import QgsVectorLayer, QgsField, QgsExpression, QgsVectorFileWriter
from qgis.analysis import QgsZonalStatistics
import webbrowser, subprocess, urllib, ogr, osr, string
import numpy as np
from osgeo import gdal, ogr
from dsm_generator_dialog import DSMGeneratorDialog
import os.path
import sys


class DSMGenerator:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'DSMGenerator_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg = DSMGeneratorDialog()

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&DSM Generator')
        # TODO: We are going to let the user set this up in a future iteration
        # self.toolbar = self.iface.addToolBar(u'DSMGenerator')
        # self.toolbar.setObjectName(u'DSMGenerator')

        # Declare variables
        self.OSMoutputfile = None
        self.DSMoutputfile = None

        if not (os.path.isdir(self.plugin_dir + '/temp')):
            os.mkdir(self.plugin_dir + '/temp')

        # Access the raster layer
        self.layerComboManagerDEM = QgsMapLayerComboBox(self.dlg.widgetRaster)
        self.layerComboManagerDEM.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.layerComboManagerDEM.setFixedWidth(175)
        self.layerComboManagerDEM.setCurrentIndex(-1)

        # Access the vector layer and an attribute field
        self.layerComboManagerPolygon = QgsMapLayerComboBox(self.dlg.widgetPolygon)
        self.layerComboManagerPolygon.setCurrentIndex(-1)
        self.layerComboManagerPolygon.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.layerComboManagerPolygon.setFixedWidth(175)
        self.layerComboManagerPolygonField = QgsFieldComboBox(self.dlg.widgetField)
        self.layerComboManagerPolygonField.setFilters(QgsFieldProxyModel.Numeric)
        self.layerComboManagerPolygonField.setFixedWidth(150)
        self.layerComboManagerPolygon.layerChanged.connect(self.layerComboManagerPolygonField.setLayer)

        # Set up of DSM file save dialog
        self.DSMfileDialog = QFileDialog()
        self.dlg.saveButton.clicked.connect(self.savedsmfile)

        # Set up of OSM polygon file save dialog
        self.OSMfileDialog = QFileDialog()
        self.dlg.savePolygon.clicked.connect(self.saveosmfile)

        # Set up for the Help button
        self.dlg.helpButton.clicked.connect(self.help)

        # Set up for the Close button
        self.dlg.closeButton.clicked.connect(self.resetPlugin)

        # Set up for the Run button
        self.dlg.runButton.clicked.connect(self.start_progress)

        # Set up extent
        self.dlg.canvasButton.toggled.connect(self.checkbox_canvas)
        # self.dlg.layerButton.toggled.connect(self.checkbox_layer)

        self.layerComboManagerExtent = QgsMapLayerComboBox(self.dlg.widgetLayerExtent)
        self.layerComboManagerExtent.setCurrentIndex(-1)
        self.layerComboManagerExtent.layerChanged.connect(self.checkbox_layer)
        self.layerComboManagerExtent.setFixedWidth(175)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        return QCoreApplication.translate('DSMGenerator', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = ':/plugins/DSMGenerator/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'DSM Generator'),
            callback=self.run,
            parent=self.iface.mainWindow())

    def savedsmfile(self):
        self.DSMoutputfile = self.DSMfileDialog.getSaveFileName(None, "Save File As:", None, "Raster Files (*.tif)")
        self.dlg.DSMtextOutput.setText(self.DSMoutputfile)

    def saveosmfile(self):
        self.OSMoutputfile = self.OSMfileDialog.getSaveFileName(None, "Save File As:", None, "Shapefiles (*.shp)")
        self.dlg.OSMtextOutput.setText(self.OSMoutputfile)

    def checkbox_canvas(self):
        extent = self.iface.mapCanvas().extent()
        self.dlg.lineEditNorth.setText(str(extent.yMaximum()))
        self.dlg.lineEditSouth.setText(str(extent.yMinimum()))
        self.dlg.lineEditWest.setText(str(extent.xMinimum()))
        self.dlg.lineEditEast.setText(str(extent.xMaximum()))

    def checkbox_layer(self):
        dem_layer_extent = self.layerComboManagerExtent.currentLayer()
        if dem_layer_extent:
            extent = dem_layer_extent.extent()
            self.dlg.lineEditNorth.setText(str(extent.yMaximum()))
            self.dlg.lineEditSouth.setText(str(extent.yMinimum()))
            self.dlg.lineEditWest.setText(str(extent.xMinimum()))
            self.dlg.lineEditEast.setText(str(extent.xMaximum()))

    # Help button
    def help(self):
        url = "http://www.urban-climate.net/umep/UMEP_Manual#Spatial_Data:_DSM_Generator"
        webbrowser.open_new_tab(url)

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&DSM Generator'),
                action)
            # self.iface.removeToolBarIcon(action)
        # remove the toolbar
        # del self.toolbar

    def run(self):
        self.dlg.show()
        self.dlg.exec_()

    def start_progress(self):
        import datetime
        start = datetime.datetime.now()
        #Check OS and dep
        if sys.platform == 'darwin':
            gdal_os_dep = '/Library/Frameworks/GDAL.framework/Versions/Current/Programs/'
        else:
            gdal_os_dep = ''

        if self.dlg.canvasButton.isChecked():
            # Map Canvas
            extentCanvasCRS = self.iface.mapCanvas()
            can_wkt = extentCanvasCRS.mapRenderer().destinationCrs().toWkt()
            can_crs = osr.SpatialReference()
            can_crs.ImportFromWkt(can_wkt)
            # Raster Layer
            dem_layer = self.layerComboManagerDEM.currentLayer()
            dem_prov = dem_layer.dataProvider()
            dem_path = str(dem_prov.dataSourceUri())
            dem_raster = gdal.Open(dem_path)
            #dem_wkt = dem_layer.exportToWkt()
            dem_wkt = dem_raster.GetProjection()
            dem_crs = osr.SpatialReference()
            dem_crs.ImportFromWkt(dem_wkt)
            #print can_crs, "-------------", dem_crs
            if can_wkt != dem_crs:
                extentCanvas = self.iface.mapCanvas().extent()
                extentDEM = dem_layer.extent()

                transformExt = osr.CoordinateTransformation(can_crs, dem_crs)

                canminx = extentCanvas.xMinimum()
                canmaxx = extentCanvas.xMaximum()
                canminy = extentCanvas.yMinimum()
                canmaxy = extentCanvas.yMaximum()

                canxymin = transformExt.TransformPoint(canminx, canminy)
                canxymax = transformExt.TransformPoint(canmaxx, canmaxy)

                extDiffminx = canxymin[0] - extentDEM.xMinimum() # If smaller than zero = warning
                extDiffminy = canxymin[1] - extentDEM.yMinimum() # If smaller than zero = warning
                extDiffmaxx = canxymax[0] - extentDEM.xMaximum() # If larger than zero = warning
                extDiffmaxy = canxymax[0] - extentDEM.yMaximum() # If larger than zero = warning

                if extDiffminx < 0 or extDiffminy < 0 or extDiffmaxx > 0 or extDiffmaxy > 0:
                    QMessageBox.warning(None, "Warning! Extent of map canvas is larger than raster extent.", "Change to an extent equal to or smaller than the raster extent.")
                    return

        # Extent
        self.yMax = self.dlg.lineEditNorth.text()
        self.yMin = self.dlg.lineEditSouth.text()
        self.xMin = self.dlg.lineEditWest.text()
        self.xMax = self.dlg.lineEditEast.text()

        if not self.DSMoutputfile:
            QMessageBox.critical(None, "Error", "Specify a raster output file")
            return

        if self.dlg.checkBoxPolygon.isChecked() and not self.OSMoutputfile:
            QMessageBox.critical(None, "Error", "Specify an output file for OSM data")
            return

        # Acquiring geodata and attributes
        dem_layer = self.layerComboManagerDEM.currentLayer()
        if dem_layer is None:
            QMessageBox.critical(None, "Error", "No valid raster layer is selected")
            return
        else:
            provider = dem_layer.dataProvider()
            filepath_dem = str(provider.dataSourceUri())
        demRaster = gdal.Open(filepath_dem)
        dem_layer_crs = osr.SpatialReference()
        dem_layer_crs.ImportFromWkt(demRaster.GetProjection())
        self.dem_layer_unit = dem_layer_crs.GetAttrValue("UNIT")
        posUnits = ['metre', 'US survey foot', 'meter', 'm', 'ft', 'feet', 'foot', 'ftUS', 'International foot'] # Possible units
        if not self.dem_layer_unit in posUnits:
            QMessageBox.critical(None, "Error", "Raster projection is not in metre or foot. Please reproject.")
            return

        polygon_layer = self.layerComboManagerPolygon.currentLayer()
        osm_layer = self.dlg.checkBoxOSM.isChecked()
        if polygon_layer is None and osm_layer is False:
            QMessageBox.critical(None, "Error", "No valid building height layer is selected")
            return
        elif polygon_layer:
            vlayer = QgsVectorLayer(polygon_layer.source(), "buildings", "ogr")
            fileInfo = QFileInfo(polygon_layer.source())
            polygon_ln = fileInfo.baseName()

            polygon_field = self.layerComboManagerPolygonField.currentField()
            idx = vlayer.fieldNameIndex(polygon_field)
            flname = vlayer.attributeDisplayName(idx)

            if idx == -1:
                QMessageBox.critical(None, "Error", "An attribute with unique fields must be selected")
                return

        ### main code ###

        self.dlg.progressBar.setRange(0, 5)

        self.dlg.progressBar.setValue(1)

        if self.dlg.checkBoxOSM.isChecked():
            dem_original = gdal.Open(filepath_dem)
            dem_wkt = dem_original.GetProjection()
            ras_crs = osr.SpatialReference()
            ras_crs.ImportFromWkt(dem_wkt)
            rasEPSG = ras_crs.GetAttrValue("PROJCS|AUTHORITY", 1)
            if self.dlg.layerButton.isChecked():
                old_crs = ras_crs
            elif self.dlg.canvasButton.isChecked():
                canvasCRS = self.iface.mapCanvas()
                outputWkt = canvasCRS.mapRenderer().destinationCrs().toWkt()
                old_crs = osr.SpatialReference()
                old_crs.ImportFromWkt(outputWkt)

            wgs84_wkt = """
            GEOGCS["WGS 84",
                DATUM["WGS_1984",
                    SPHEROID["WGS 84",6378137,298.257223563,
                        AUTHORITY["EPSG","7030"]],
                    AUTHORITY["EPSG","6326"]],
                PRIMEM["Greenwich",0,
                    AUTHORITY["EPSG","8901"]],
                UNIT["degree",0.01745329251994328,
                    AUTHORITY["EPSG","9122"]],
                AUTHORITY["EPSG","4326"]]"""

            new_crs = osr.SpatialReference()
            new_crs.ImportFromWkt(wgs84_wkt)

            transform = osr.CoordinateTransformation(old_crs, new_crs)

            minx = float(self.xMin)
            miny = float(self.yMin)
            maxx = float(self.xMax)
            maxy = float(self.yMax)
            lonlatmin = transform.TransformPoint(minx, miny)
            lonlatmax = transform.TransformPoint(maxx, maxy)

            if ras_crs != old_crs:
                rasTrans = osr.CoordinateTransformation(old_crs, ras_crs)
                raslonlatmin = rasTrans.TransformPoint(float(self.xMin), float(self.yMin))
                raslonlatmax = rasTrans.TransformPoint(float(self.xMax), float(self.yMax))
            #else:
                #raslonlatmin = [float(self.xMin), float(self.yMin)]
                #raslonlatmax = [float(self.xMax), float(self.yMax)]

                self.xMin = raslonlatmin[0]
                self.yMin = raslonlatmin[1]
                self.xMax = raslonlatmax[0]
                self.yMax = raslonlatmax[1]

            # Make data queries to overpass-api
            urlStr = 'http://overpass-api.de/api/map?bbox=' + str(lonlatmin[0]) + ',' + str(lonlatmin[1]) + ',' + str(lonlatmax[0]) + ',' + str(lonlatmax[1])
            osmXml = urllib.urlopen(urlStr).read()
            #print urlStr

            # Make OSM building file
            osmPath = self.plugin_dir + '/temp/OSM_building.osm'
            osmFile = open(osmPath, 'w')
            osmFile.write(osmXml)
            if os.fstat(osmFile.fileno()).st_size < 1:
                urlStr = 'http://api.openstreetmap.org/api/0.6/map?bbox=' + str(lonlatmin[0]) + ',' + str(lonlatmin[1]) + ',' + str(lonlatmax[0]) + ',' + str(lonlatmax[1])
                osmXml = urllib.urlopen(urlStr).read()
                osmFile.write(osmXml)
                #print 'Open Street Map'
                if os.fstat(osmFile.fileno()).st_size < 1:
                    QMessageBox.critical(None, "Error", "No OSM data available")
                    return

            osmFile.close()

            outputshp = self.plugin_dir + '/temp/'

            osmToShape = gdal_os_dep + 'ogr2ogr --config OSM_CONFIG_FILE "' + self.plugin_dir + '/osmconf.ini" -skipfailures -t_srs EPSG:' + str(rasEPSG) + ' -overwrite -nlt POLYGON -f "ESRI Shapefile" "' + outputshp + '" "' + osmPath + '"'

            if sys.platform == 'win32':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.call(osmToShape, startupinfo=si)
            else:
                os.system(osmToShape)

            driver = ogr.GetDriverByName('ESRI Shapefile')
            driver.DeleteDataSource(outputshp + 'lines.shp')
            driver.DeleteDataSource(outputshp + 'multilinestrings.shp')
            driver.DeleteDataSource(outputshp + 'other_relations.shp')
            driver.DeleteDataSource(outputshp + 'points.shp')

            osmPolygonPath = outputshp + 'multipolygons.shp'
            vlayer = QgsVectorLayer(osmPolygonPath, 'multipolygons', 'ogr')
            polygon_layer = vlayer
            fileInfo = QFileInfo(polygon_layer.source())
            polygon_ln = fileInfo.baseName()

            def renameField(srcLayer, oldFieldName, newFieldName):
                ds = gdal.OpenEx(srcLayer.source(), gdal.OF_VECTOR | gdal.OF_UPDATE)
                ds.ExecuteSQL('ALTER TABLE {} RENAME COLUMN {} TO {}'.format(srcLayer.name(), oldFieldName, newFieldName))
                srcLayer.reload()
            vlayer.startEditing()
            renameField(vlayer, 'building_l', 'bld_levels')
            renameField(vlayer, 'building_h', 'bld_hght')
            renameField(vlayer, 'building_c', 'bld_colour')
            renameField(vlayer, 'building_m', 'bld_materi')
            renameField(vlayer, 'building_u', 'bld_use')
            vlayer.commitChanges()

            vlayer.startEditing()
            vlayer.dataProvider().addAttributes([QgsField('bld_height', QVariant.Double, 'double', 3, 2)])
            vlayer.updateFields()
            bld_lvl = vlayer.fieldNameIndex('bld_levels')
            hght = vlayer.fieldNameIndex('height')
            bld_hght = vlayer.fieldNameIndex('bld_hght')
            bld_height = vlayer.fieldNameIndex('bld_height')

            bldLvlHght = float(self.dlg.doubleSpinBoxBldLvl.value())
            illegal_chars = string.ascii_letters + "!#$%&'*+^_`|~:" + " "
            counterNone = 0
            counter = 0
            #counterWeird = 0
            for feature in vlayer.getFeatures():
                if feature[hght]:
                    try:
                        #feature[bld_height] = float(re.sub("[^0-9]", ".", str(feature[hght])))
                        feature[bld_height] = float(str(feature[hght]).translate(None, illegal_chars))
                    except:
                        counterNone += 1
                elif feature[bld_hght]:
                    try:
                        #feature[bld_height] = float(re.sub("[^0-9]", ".", str(feature[bld_hght])))
                        feature[bld_height] = float(str(feature[bld_hght]).translate(None, illegal_chars))
                    except:
                        counterNone += 1
                elif feature[bld_lvl]:
                    try:
                        #feature[bld_height] = float(re.sub("[^0-9]", "", str(feature[bld_lvl])))*bldLvlHght
                        feature[bld_height] = float(str(feature[bld_lvl]).translate(None, illegal_chars)) * bldLvlHght
                    except:
                        counterNone += 1
                else:
                    counterNone += 1
                vlayer.updateFeature(feature)
                counter += 1
            vlayer.commitChanges()
            flname = vlayer.attributeDisplayName(bld_height)
            counterDiff = counter - counterNone

        # Zonal statistics
        vlayer.startEditing()
        zoneStat = QgsZonalStatistics(vlayer, filepath_dem, "stat_", 1, QgsZonalStatistics.Mean)
        zoneStat.calculateStatistics(None)
        vlayer.dataProvider().addAttributes([QgsField('height_asl', QVariant.Double)])
        vlayer.updateFields()
        e = QgsExpression('stat_mean + ' + flname)
        e.prepare(vlayer.pendingFields())
        idx = vlayer.fieldNameIndex('height_asl')

        for f in vlayer.getFeatures():
            f[idx] = e.evaluate(f)
            vlayer.updateFeature(f)

        vlayer.commitChanges()

        vlayer.startEditing()
        idx2 = vlayer.fieldNameIndex('stat_mean')
        vlayer.dataProvider().deleteAttributes([idx2])
        vlayer.updateFields()
        vlayer.commitChanges()

        self.dlg.progressBar.setValue(2)

        # Convert polygon layer to raster

        # Define pixel_size and NoData value of new raster
        pixel_size = int(self.dlg.spinBox.value())  # half picture size

        # Create the destination data source
        
        gdalrasterize = gdal_os_dep + 'gdal_rasterize -a ' + 'height_asl' + ' -te ' + str(self.xMin) + ' ' + str(self.yMin) + ' ' + str(self.xMax) + ' ' + str(self.yMax) +\
                        ' -tr ' + str(pixel_size) + ' ' + str(pixel_size) + ' -l "' + str(polygon_ln) + '" "' \
                         + str(polygon_layer.source()) + '" "' + self.plugin_dir + '/temp/clipdsm.tif"'

        gdalclipdem = gdal_os_dep + 'gdalwarp -dstnodata -9999 -q -overwrite -te ' + str(self.xMin) + ' ' + str(self.yMin) + ' ' + str(self.xMax) + ' ' + str(self.yMax) +\
                      ' -tr ' + str(pixel_size) + ' ' + str(pixel_size) + \
                      ' -of GTiff ' + '"' + filepath_dem + '" "' + self.plugin_dir + '/temp/clipdem.tif"'

        # Rasterize
        if sys.platform == 'win32':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.call(gdalrasterize, startupinfo=si)
            subprocess.call(gdalclipdem, startupinfo=si)
        else:
            os.system(gdalrasterize)
            os.system(gdalclipdem)

        self.dlg.progressBar.setValue(3)

        # Adding DSM to DEM
        # Read DEM
        dem_raster = gdal.Open(self.plugin_dir + '/temp/clipdem.tif')
        dem_array = np.array(dem_raster.ReadAsArray().astype(np.float))
        dsm_raster = gdal.Open(self.plugin_dir + '/temp/clipdsm.tif')
        dsm_array = np.array(dsm_raster.ReadAsArray().astype(np.float))

        indx = dsm_array.shape
        for ix in range(0, int(indx[0])):
            for iy in range(0, int(indx[1])):
                if int(dsm_array[ix, iy]) == 0:
                    dsm_array[ix, iy] = dem_array[ix, iy]

        if self.dlg.checkBoxPolygon.isChecked():
            vlayer.startEditing()
            idxHght = vlayer.fieldNameIndex('height_asl')
            idxBld = vlayer.fieldNameIndex('building')
            features = vlayer.getFeatures()
            #for f in vlayer.getFeatures():
            for f in features:
                geom = f.geometry()
                posUnitsMetre = ['metre', 'meter', 'm']  # Possible metre units
                posUnitsFt = ['US survey foot', 'ft', 'feet', 'foot', 'ftUS', 'International foot'] # Possible foot units
                if self.dem_layer_unit in posUnitsMetre:
                    sqUnit = 1
                elif self.dem_layer_unit in posUnitsFt:
                    sqUnit = 10.76
                if int(geom.area()) > 50000*sqUnit:
                    vlayer.deleteFeature(f.id())

                #if not f[idxHght]:
                    #vlayer.deleteFeature(f.id())
                #elif not f[idxBld]:
                    #vlayer.deleteFeature(f.id())
            vlayer.updateFields()
            vlayer.commitChanges()
            QgsVectorFileWriter.writeAsVectorFormat(vlayer, str(self.OSMoutputfile), "UTF-8", None, "ESRI Shapefile")

        else:
            vlayer.startEditing()
            idx3 = vlayer.fieldNameIndex('height_asl')
            vlayer.dataProvider().deleteAttributes([idx3])
            vlayer.updateFields()
            vlayer.commitChanges()

        self.dlg.progressBar.setValue(4)

        # Save raster
        def saveraster(gdal_data, filename,
                       raster):  # gdal_data = raster extent, filename = output filename, raster = numpy array (raster to be saved)
            rows = gdal_data.RasterYSize
            cols = gdal_data.RasterXSize

            outDs = gdal.GetDriverByName("GTiff").Create(filename, cols, rows, int(1), gdal.GDT_Float32)
            outBand = outDs.GetRasterBand(1)

            # write the data
            outBand.WriteArray(raster, 0, 0)
            # flush data to disk, set the NoData value and calculate stats
            outBand.FlushCache()
            outBand.SetNoDataValue(-9999)

            # georeference the image and set the projection
            outDs.SetGeoTransform(gdal_data.GetGeoTransform())
            outDs.SetProjection(gdal_data.GetProjection())

        saveraster(dsm_raster, self.DSMoutputfile, dsm_array)

        # Load result into canvas
        rlayer = self.iface.addRasterLayer(self.DSMoutputfile)

        # Trigger a repaint
        if hasattr(rlayer, "setCacheImage"):
            rlayer.setCacheImage(None)
        rlayer.triggerRepaint()

        self.dlg.progressBar.setValue(5)

        #runTime = datetime.datetime.now() - start

        if self.dlg.checkBoxOSM.isChecked():
            QMessageBox.information(self.dlg, 'DSM Generator', 'Operation successful! ' + str(counterDiff) + ' building polygons out of ' + str(counter) + ' contained height values.')
            #self.iface.messageBar().pushMessage("DSM Generator. Operation successful! " + str(counterDiff) + " buildings out of " + str(counter) + " contained height values.", level=QgsMessageBar.INFO, duration=5)
        else:
            #self.iface.messageBar().pushMessage("DSM Generator. Operation successful!", level=QgsMessageBar.INFO, duration=5)
            QMessageBox.information(self.dlg, 'DSM Generator', 'Operation successful!')

        self.resetPlugin()

        #print "finished run: %s\n\n" % (datetime.datetime.now() - start)

    def resetPlugin(self):       # Reset plugin
        self.dlg.canvasButton.setAutoExclusive(False)
        self.dlg.canvasButton.setChecked(False)
        self.dlg.layerButton.setAutoExclusive(False)
        self.dlg.layerButton.setChecked(False)
        self.dlg.checkBoxOSM.setCheckState(0)
        self.dlg.checkBoxPolygon.setCheckState(0)

        # Extent
        self.layerComboManagerExtent.setCurrentIndex(-1)
        self.dlg.lineEditNorth.setText("")
        self.dlg.lineEditSouth.setText("")
        self.dlg.lineEditWest.setText("")
        self.dlg.lineEditEast.setText("")

        # Output boxes
        self.dlg.OSMtextOutput.setText("")
        self.dlg.DSMtextOutput.setText("")

        # Input raster
        self.layerComboManagerDEM.setCurrentIndex(-1)

        # Input polygon
        self.layerComboManagerPolygon.setCurrentIndex(-1)

        # Progress bar
        self.dlg.progressBar.setValue(0)

        # Spin boxes
        self.dlg.spinBox.setValue(2)
        self.dlg.doubleSpinBoxBldLvl.setValue(2.5)
