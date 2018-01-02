#!/usr/bin/env python

import os
import sys
import sqlite3
from qgis.core import *

from osgeo import ogr, osr, gdal


class VFKParBuilderError(Exception):
    pass


class VFKBuilder(object):
    def __init__(self, filename):
        """Constructor VFKBuilder

        :param str filename: path to VFK file 
        :raises VFKParBuilderError: if the database for writing is not connected
        """
        self.filename = os.path.splitext(filename)[0]
        # QgsMessageLog.logMessage('X{}'.format(os.environ['OGR_VFK_DB_NAME']), 'X to je jedno', QgsMessageLog.INFO)
        self.dsn_vfk = ogr.Open(self.filename + '.vfk')
        if self.dsn_vfk is None:
            raise VFKParBuilderError('Nelze otevrit VFK soubor {}'.format(self.filename + '.vfk'))
        # this hack is needed only for GDAL < 2.2
        if int(gdal.VersionInfo()) < 2020000:
            self.dsn_vfk.GetLayerByName('HP').GetFeature(1)
        self.dsn_vfk = None

        self.dbname = os.getenv('OGR_VFK_DB_NAME')
        if self.dbname is None:
            self.dbname = self.filename + '.db'

        # add tables
        self.add_tables(os.path.join(
            os.path.dirname(__file__),
            'sql_commands',
            'add_HP_SBP_geom.sql'
        ))

        self.dsn_db = ogr.Open(self.dbname, True)
        if self.dsn_db is None:
            raise VFKParBuilderError('Database in write mode is not connected')

        if self.dsn_db.GetLayerByName('PAR'):
            self.layer_par = None
            return

    def build_bound(self, list_vertices):
        """Build a geometry of specified boundary in geometric way 

        :param list list_vertices: unsorted list of vertices forming boundary
        :return: geometry poly_geom: geometry of the specified boundary
        """

        def first_line(ring, list_vertices):
            # Add the first vertix and remove it from the list of vertices
            vertix_1 = list_vertices[0]
            for i in range(len(vertix_1)):
                bod = vertix_1[i]
                ring.AddPoint(bod[0], bod[1])
            list_vertices.pop(0)

        # Create a ring
        rings = []
        rings.append(ogr.Geometry(ogr.wkbLinearRing))
        ring = rings[0]
        first_line(ring, list_vertices)

        # Adding the next vertix
        # Searching for the end point of the ring in the list of vertices - the first searched point
        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))  # end point
        while len(list_vertices) > 0:  # it runs till list_vertices contains vertices
            count1 = len(list_vertices)
            for position in range(len(list_vertices)):  # position-shows the position of added vertice in list_vertices
                if search in list_vertices[position]:
                    if (list_vertices[position].index(search)) == 0:  # the vertix has the same orientation as the first added
                        self.add_boundary(position, 'front', list_vertices, ring)
                        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                        break
                    if (list_vertices[position].index(search)) > 0:  # the vertix has opposite orientation
                        self.add_boundary(position, 'back', list_vertices, ring)
                        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                        break
            # Test if there is another ring
            count2 = len(list_vertices)
            if count1 == count2:
                # no match, create new ring
                rings.append(ogr.Geometry(ogr.wkbLinearRing))
                ring = rings[-1]
                first_line(ring, list_vertices)
                search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                # print 'Hledam', search
        # Test of closed polygons
        for ring in rings:
            first = ring.GetPoint(0)
            last = ring.GetPoint(ring.GetPointCount() - 1)
            if first != last:
                return None
        # Test on holes in polygon - find outRing
        if len(rings) > 1:
            # Get geometries and envelopes
            envelops = []
            for polygon in rings:
                poly = ogr.Geometry(ogr.wkbPolygon)
                poly.AddGeometry(polygon)
                envelops.append(poly.GetEnvelope())
            # Find outRing
            # 1)Extrems
            minX = []
            maxX = []
            minY = []
            maxY = []
            for env in envelops:
                minX.append(env[0])
                maxX.append(env[1])
                minY.append(env[2])
                maxY.append(env[3])
            minX_v = min(minX)
            maxX_v = max(maxX)
            minY_v = min(minY)
            maxY_v = max(maxY)
            # 2)Indexes
            minX_i = minX.index(minX_v)
            maxX_i = maxX.index(maxX_v)
            minY_i = minY.index(minY_v)
            maxY_i = maxY.index(maxY_v)
            # 3)Conclusion - which ring is outRing
            if minX_i == maxX_i == minY_i == maxY_i:
                outRing = rings[minX_i]  # ring with the biggest envelope is outRing
                rings.pop(minX_i)
                innerRings = rings  # the rest in rings are innerRings(holes)
                # Create a polygon with holes
                poly_geom = ogr.Geometry(ogr.wkbPolygon)
                poly_geom.AddGeometry(outRing)
                for holes in innerRings:
                    poly_geom.AddGeometry(holes)
                return poly_geom
            else:
                return None

        else:
            # Create a polygon
            poly_geom = ogr.Geometry(ogr.wkbPolygon)
            poly_geom.AddGeometry(ring)
            return poly_geom

    def add_boundary(self, position, direction, list_vertices, ring):
        """Add the vertix point by point to the END of ring(geometry of the parcel) 

        :param int position: shows the position of added vertix in the list_vertices
        :param str direction: specifies vertix direction - 'front' or 'back'
        :param int list_vertices: list of unsorted and both direction geometric vertices for specified boundary
        :param geometry ring: geometry of the boundary that is built #jaky typ u geometrie?
        :return: geometry ring: the ring with added vertix
        """

        vertices = list_vertices[position]
        if direction == 'front':
            for i in range(1, len(vertices)):
                point = vertices[i]
                ring.AddPoint(point[0], point[1])
        if direction == 'back':
            for i in range(len(vertices) - 2, -1, -1):
                point = vertices[i]
                ring.AddPoint(point[0], point[1])
        list_vertices.pop(position)

        return ring

    def get_sql_commands_from_file(self, fileName):
        """Load sql commands from file

        :param str fileName: path to the file with sql commands
        :return: sql commands
        """
        file = open(fileName, 'r')
        sqlFile = file.read()
        file.close()
        sqlCommands = sqlFile.split(';')

        return sqlCommands

    def add_tables(self, sqlfileName):
        """Add tables to the database by sql commands

        :param str sqlfileName: path to the file with sql commands
        :return: added tables in the database
        """
        # Connection to the database
        db = sqlite3.connect(self.dbname)
        if db is None:
            raise VFKParBuilderError('Database not connected')
        # Adding tables
        cur = db.cursor()
        sqlCommands = self.get_sql_commands_from_file(sqlfileName)
        for command in sqlCommands:
            cur.execute(command)
        db.commit()  # without commit it does not write data from the last sql command
        db.close()

class VFKParBuilder(VFKBuilder):
    def __init__(self, filename):
        """Constructor VFKParBuilder

        :param str filename: path to VFK file 
        """
        VFKBuilder.__init__(self, filename)
        # Set coordinate system
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5514)
        # New layer
        table = 'PAR'
        self.layer_par = self.dsn_db.CreateLayer(table, srs, ogr.wkbPolygon,
                                                 ['OVERWRITE=YES',
                                                  'LAUNDER=NO']  # force uppercase names (PAR, BUD)
                                                 )
        # Layer definition
        self.layer_par_def = self.layer_par.GetLayerDefn()
        # New fields - atributes "id_par", "kmenove_cislo_par", "poddeleni_cisla_par"
        idField = ogr.FieldDefn("id_par", ogr.OFTInteger)
        kmenField = ogr.FieldDefn("kmenove_cislo_par", ogr.OFTInteger)
        podField = ogr.FieldDefn("poddeleni_cisla_par", ogr.OFTInteger)
        self.layer_par.CreateField(idField)
        self.layer_par.CreateField(kmenField)
        self.layer_par.CreateField(podField)
        self.dsn_vfk = None

    def get_par(self):
        """Form a unique list of parcel ids by SQL command

        :return: list of parcels
        :raises VFKParBuilderError: if the db file is not exist in the directory
        """

        # zdroj: http://zetcode.com/db/sqlitepythontutorial/
        # Connect to db
        db = sqlite3.connect(self.dbname)
        if db is None:
            raise VFKParBuilderError('Databaze nepripojena')
        # New list to save parcel numbers
        parcels = []

        cur = db.cursor()
        cur.execute('SELECT par_id_1 as id FROM hp UNION SELECT par_id_2 as id from hp')
        while True:
            row = cur.fetchone()
            if row == None:
                break
            parcels.append(row[0])
        db.close()

        return parcels

    def filter_hp(self, id_par):
        """Form a list of vertices for number specified parcel

        :param int id_par: The id number of parcel is looking for vertices(geomatry)
        :return: list of unsorted and both direction vertices for specified parcel number
        :raises VFKParBuilderError: if layer 'HP' is not in the source database
        """

        # Data in layer HP
        lyr_hp = self.dsn_db.GetLayerByName('HP')
        if lyr_hp is None:
            raise VFKParBuilderError('Layer HP is empty')
        # Filter of vertices on specified parcel id
        hp_list = []
        lyr_hp.SetAttributeFilter("PAR_ID_1 = '{0}' or PAR_ID_2 = '{0}'".format(id_par))
        for feat in lyr_hp:
            hp_list.append(feat)
        lyr_hp.SetAttributeFilter(None)

        return hp_list  # just features in layer, no geometry(geometry in list_vertices) (jen prvky ve vrstve, nikoliv geometrie (ta je oznacena list_vertices))

    def build_all_par(self, limit=None):
        """Build the boundaries of specified amount of parcels
         according to the unique list of parcel ids and write them into the database

        :param int limit: define amount of built parcels, default is None - no limit
        :return: built parcel geometries and corresponding parcel numbers are written in the source database 
        """
        if self.layer_par is None:
            return

        counter = 0

        # get list of unique par ids
        parcels = self.get_par()

        db = sqlite3.connect(self.dbname)
        if db is None:
            raise VFKParBuilderError('Database not connected')

        # Start transaction
        self.layer_par.StartTransaction()

        count = len(parcels)
        idx = 1
        unclosed = []
        for par_id in parcels:
            # print("{}/{} ".format(idx, count))
            idx += 1
            # create empty list to save the boundaries of built parcel
            list_vertices = []  # vytvoreni prazdneho seznamu pro ulozeni hranic sestavovane parcely
            # collect unsorted list of vertices forming par boundary
            for feature in self.filter_hp(par_id):
                geom = feature.GetGeometryRef()
                list_vertices.append(geom.GetPoints())  # list of parcel boundaries - already geometry(seznam hranic parcel - jiz geometrie)
            # Create par geometry
            poly_geom = self.build_bound(list_vertices)
            if poly_geom is not None:
                # Convert to 2D
                poly_geom.FlattenTo2D()
                # WRITE TO DATABASE
            else:
                # print 'Unclosed polygon'
                unclosed.append(par_id)
            # Create the feature
            value = ogr.Feature(self.layer_par_def)
            # Set geometry
            value.SetGeometry(poly_geom)
            # Set id_par field
            value.SetField("id_par", par_id)
            # Set par number fields
            cur = db.cursor()
            cur.execute(
                'SELECT distinct op.text FROM(SELECT par_id_1 as id FROM hp UNION SELECT par_id_2 as id from hp) uniq_par JOIN op ON op.par_id = uniq_par.id WHERE op.text is not null and par_id = {}'.format(
                    par_id))
            while True:
                row = cur.fetchone()
                if row == None:
                    break
                if '/' in row[0]:
                    value.SetField("kmenove_cislo_par", row[0].split('/')[0])
                    value.SetField("poddeleni_cisla_par", row[0].split('/')[1])
                else:
                    value.SetField("kmenove_cislo_par", row[0])

            self.layer_par.CreateFeature(value)
            value = None

            # print result to stdout and check limit (will be removed)
            counter += 1
            if limit and counter > limit:
                break

        # End transaction
        self.layer_par.CommitTransaction()

        db.close()
        # Unclosed
        # print ('The number of unclosed parcels: {}'.format(len(unclosed)))
        # Close database
        self.dsn_db = None

class VFKBudBuilder(VFKBuilder):
    def __init__(self, filename):
        """Constructor VFKBuilder

        :param str filename: path to VFK file 
        """
        VFKBuilder.__init__(self, filename)
        # Set coordinate system
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5514)
        # New layer
        table = 'BUD'
        self.layer_bud = self.dsn_db.CreateLayer(table, srs, ogr.wkbPolygon, ['OVERWRITE=YES',
                                                                              'LAUNDER=NO'])
        # Layer definition
        self.layer_bud_def = self.layer_bud.GetLayerDefn()
        # New field - atribute "id_bud"
        idField = ogr.FieldDefn("id_bud", ogr.OFTInteger)
        self.layer_bud.CreateField(idField)
        self.dsn_vfk = None

    def get_bud_id(self):
        """Get unique bud_id numbers from the table 'OB' (amount of buildings)
         and corresponding id from the table 'OB' (ids of points which make one boundary)

        :return: uniq list of bud_id numbers and list of lists ids of points for each bud_id
        """
        # Connect to db
        db = sqlite3.connect(self.filename + '.db')
        if db is None:
            raise VFKParBuilderError('Databaze nepripojena')
        # New list to save building ids
        bud_id = []
        cur = db.cursor()
        # Unique list of bud_id
        cur.execute('SELECT distinct bud_id FROM ob')
        while True:
            row = cur.fetchone()
            if row == None:
                break
            bud_id.append(row[0])
        ids = []
        for idx in bud_id:
            list_id = []
            cur = db.cursor()
            # List of ob-id for each building
            cur.execute('SELECT id FROM ob WHERE bud_id = {0} and typppd_kod = 21700'.format(idx))  # or column obrbud_type = 'OB'
            while True:
                row2 = cur.fetchone()
                if row2 == None:
                    break
                list_id.append(row2[0])
            ids.append(list_id)
        db.close()

        return ids, bud_id

    def filter_sbp(self, ob_id):
        """Form a list of vertices for number(ob_id) specified building

        :param int ob_id: unique building number for which is looking for the points(geometry)
        :return: list of unsorted and both direction vertices for number specified building
        """
        # Data in layer SBP
        lyr_sbp = self.dsn_db.GetLayerByName('SBP')
        if lyr_sbp is None:
            raise VFKParBuilderError('Nelze nacist vrstvu SBP')
        sbp_list = []
        # extremly slow search, must go through 37508 rows
        lyr_sbp.SetAttributeFilter("OB_ID = '{0}' and PORADOVE_CISLO_BODU = '{1}'".format(ob_id, 1))
        for feat in lyr_sbp:
            sbp_list.append(feat)
        lyr_sbp.SetAttributeFilter(None)

        return sbp_list

    def build_all_bud(self, limit=None):
        """Build the boundaries of specified amount of buildings
         according to the unique list of building ids and write them into the database

        :param int limit: define amount of built buildings, default is None - no limit
        :return: built building geometries and corresponding building identification numbers are written in the source database
        """
        counter_bul = 0
        # Unique building identification numbers
        ids = self.get_bud_id()[0]
        # List of lists with points that belong to one unique bud_id
        bud_id = self.get_bud_id()[1]
        # Start transaction
        self.layer_bud.StartTransaction()

        # Unclosed buildings
        unclosed_bul = []
        for i in range(len(ids)):
            building = bud_id[i]
            lines = ids[i]
            list_sbp = []
            # print 'idecka jedne budovy',lines
            for line in lines:
                for feature in self.filter_sbp(line):
                    geom = feature.GetGeometryRef()
                    list_sbp.append(geom.GetPoints())
            # print 'ID pocitadlo', counter_id
            # Create bud geometry
            poly_geom = self.build_bound(list_sbp)
            if poly_geom is not None:
                # Convert to 2D
                poly_geom.FlattenTo2D()
            else:
                unclosed_bul.append(building)

            # WRITE TO DATABASE
            # Create the feature
            value = ogr.Feature(self.layer_bud_def)
            # Set geometry
            value.SetGeometry(poly_geom)
            # print("Cislo zapsane budovy: {} ".format(building))
            # Set id_par field
            value.SetField("id_bud", building)
            self.layer_bud.CreateFeature(value)
            value = None
            # print 'Lomove body pro jednu budovu',list_sbp
            # print (building, poly_geom.ExportToWkt())
            counter_bul += 1
            # print ('Sestavena budova cislo {}.'.format(counter_bul))
            if limit and counter_bul > limit:
                break
        # End transaction
        self.layer_bud.CommitTransaction()

        # Close database
        self.dsn_db = None

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("{} soubor.vfk".format(sys.argv[0]))

    # Funkcnost tridy
    parcel = VFKParBuilder(sys.argv[1])
    parcel.build_all_par()

    building = VFKBudBuilder(sys.argv[1])
    building.build_all_bud()