#!/usr/bin/env python

import os
import sys
import sqlite3

from osgeo import ogr, osr, gdal

class VFKParBuilderError(Exception):
    pass

class VFKParBuilder:
    def __init__(self, filename):
        """Constructor VFKParBuilder

        :param str filename: path to VFK file 
        :raises VFKParBuilderError: if the database for writing is not connected
        """
        self.filename = os.path.splitext(filename)[0]
        self.dsn_vfk = ogr.Open(self.filename + '.vfk')
        # this hack is needed only for GDAL < 2.2
        if int(gdal.VersionInfo()) < 2020000:
            self.dsn_vfk.GetLayerByName('HP').GetFeature(1)
        if self.dsn_vfk is None:
            raise VFKParBuilderError('Nelze otevrit datasource')
        self.dsn_vfk = None

        self.dbname = os.getenv('OGR_VFK_DB_NAME')
        if self.dbname is None:
            self.dbname = self.filename + '.db'
        
        #add tables
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
        
        # Set coordinate system
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5514)
        # New layer
        table = 'PAR'  # TASK:set capital letters, is it possible?
        self.layer_par = self.dsn_db.CreateLayer(table, srs, ogr.wkbPolygon,
                                                 ['OVERWRITE=YES',
                                                  'LAUNDER=NO']    # force uppercase names (PAR, BUD)
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


    def get_par(self):
        """Form a unique list of parcel ids by SQL command
        
        :return: list of parcels
        :raises VFKParBuilderError: if the db file is not exist in the directory
        """

        # zdroj: http://zetcode.com/db/sqlitepythontutorial/
        #Connect to db
        db = sqlite3.connect(self.dbname)
        if db is None:
            raise VFKParBuilderError('Databaze nepripojena')
        #New list to save parcel numbers
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
        
        :param int id_par: The id number of parcel is looking for the boundaries
        :return: list of unsorted and both direction vertices for specified parcel number
        :raises VFKParBuilderError: if vfk source file in not connected
        """

        #DataSource
        # Data in layer HP
        lyr_hp = self.dsn_db.GetLayerByName('HP')
        if lyr_hp is None:
            raise VFKParBuilderError('Nelze nacist vrstvu HP')
        #Filter of vertices on specified parcel
        hp_list = []
        lyr_hp.SetAttributeFilter("PAR_ID_1 = '{0}' or PAR_ID_2 = '{0}'".format(id_par))
        for feat in lyr_hp:
            hp_list.append(feat)
        lyr_hp.SetAttributeFilter(None)

        return hp_list #jen prvky ve vrstve, nikoliv geometrie (ta je oznacena list_hp)

    def build_par(self, list_hp):
        """Build a geometry of number specified parcel in geometric way 
        
        #:param int id_par: The number of parcel which the geometry is build
        :param int list_hp: unsorted list of vertices forming par boundary
        :return: polygon geometry on the specified parcel
        """
        def first_line(ring, list_hp):
            # Add the first vertix and remove it from the list of vertices
            vertix_1 = list_hp[0]
            for i in range(len(vertix_1)):
                bod = vertix_1[i]
                ring.AddPoint(bod[0], bod[1])
            list_hp.pop(0)

        # Create a ring
        rings = []
        rings.append(ogr.Geometry(ogr.wkbLinearRing))
        ring = rings[0]
        first_line(ring, list_hp)

        # Adding the next vertix
        # Searching for the end point of the ring in the list of vertices - the first searched point
        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))  # end point
        while len(list_hp) > 0:  # it runs till list_hp contains vertices
            count1 = len(list_hp)
            for position in range(len(list_hp)): #position-shows the position of added vertice in list_hp
                if search in list_hp[position]:
                    if (list_hp[position].index(search)) == 0: #the vertix has the same orientation as the first added
                        self.add_boundary(position, 'front', list_hp, ring)
                        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                        break
                    if (list_hp[position].index(search)) > 0:  # the vertix has opposite orientation
                        self.add_boundary(position, 'back', list_hp, ring)
                        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                        break
            #Test if there is another ring
            count2 = len(list_hp)
            if count1 == count2:
            # no match, create new ring
                rings.append(ogr.Geometry(ogr.wkbLinearRing))
                ring = rings[-1]
                first_line(ring, list_hp)
                search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                #print 'Hledam', search
        #Test of closed polygons
        for ring in rings:
            first = ring.GetPoint(0)
            last = ring.GetPoint(ring.GetPointCount() - 1)
            if first != last:
                return None
        # Test on holes in polygon - find outRing
        if len(rings)>1:
            #Get geometries and envelopes
            envelops = []
            for polygon in rings:
                poly = ogr.Geometry(ogr.wkbPolygon)
                poly.AddGeometry(polygon)
                envelops.append(poly.GetEnvelope())
            #Find outRing
            #1)Extrems
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
            #2)Indexes
            minX_i = minX.index(minX_v)
            maxX_i = maxX.index(maxX_v)
            minY_i = minY.index(minY_v)
            maxY_i = maxY.index(maxY_v)
            #3)Conclusion - which ring is outRing
            if minX_i == maxX_i == minY_i ==maxY_i:
                outRing = rings[minX_i] #ring with the biggest envelope is outRing
                rings.pop(minX_i)
                innerRings = rings #the rest in rings are innerRings(holes)
            #else:
                #print 'Indexes do not match'
            #Create a polygon with holes
            poly_geom = ogr.Geometry(ogr.wkbPolygon)
            poly_geom.AddGeometry(outRing)
            for holes in innerRings:
                poly_geom.AddGeometry(holes)
            return poly_geom

        else:
            # Create a polygon
            poly_geom = ogr.Geometry(ogr.wkbPolygon)
            poly_geom.AddGeometry(ring)
            return poly_geom

    def add_boundary(self,position,direction, list_hp, ring):
        """Add the vertice to the END of ring(geometry of the parcel) 
        
        :param int position: shows the position of added vertix in the list_hp
        :param str direction: specifies vertix direction - 'front' or 'back'
        :param int list_hp: list of unsorted and both direction geometric vertices for specified parcel number
        :param geometry ring: geometry of the parcel that is built #jaky typ u geometrie?
        :return: the ring with added vertix
        """

        vertices = list_hp[position]
        if direction == 'front':
            for i in range(1, len(vertices)):
                point = vertices[i]
                ring.AddPoint(point[0], point[1])
        if direction == 'back':
            for i in range(len(vertices) - 2, -1, -1):
                point = vertices[i]
                ring.AddPoint(point[0], point[1])
        list_hp.pop(position)
        return ring

    def build_all(self, limit=None):
        """Build the boundaries of specified amount of parcels according to the unique list of parcel ids and write them in to the database
        
        :param int limit: define amount of built parcels 
        :return: built parcels and corresponding parcel numbers all written in the source database 
        """
        if self.layer_par is None:
            return
        
        counter = 0

        # get list of unique par ids
        parcels = self.get_par()

        db = sqlite3.connect(self.dbname)
        if db is None:
            raise VFKParBuilderError('Database not connected')
        
        #Start transaction
        self.layer_par.StartTransaction()

        count = len(parcels)
        idx = 1
        unclosed = []
        for par_id in parcels:
            #print("{}/{} ".format(idx, count))
            idx += 1
            
            list_hp = [] # vytvoreni prazdneho seznamu pro ulozeni hranic sestavovane parcely
            # collect unsorted list of vertices forming par boundary
            for feature in self.filter_hp(par_id):
                geom = feature.GetGeometryRef()
                list_hp.append(geom.GetPoints()) # seznam hranic parcel - jiz geometrie
            #Create par geometry
            poly_geom = self.build_par(list_hp)
            if poly_geom is not None:
                #Convert to 2D
                poly_geom.FlattenTo2D()
                #WRITE TO DATABASE
            else:
                #print 'Unclosed polygon'
                unclosed.append(par_id)
            # Create the feature
            value = ogr.Feature(self.layer_par_def)
            #Set geometry
            value.SetGeometry(poly_geom)
            #Set id_par field
            value.SetField("id_par", par_id)
            #Set par number fields
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

        #End transaction
        self.layer_par.CommitTransaction()

        db.close()
        #Unclosed
        #print ('The number of unclosed parcels: {}'.format(len(unclosed)))
        #Close database
        self.dsn_db = None

    def get_sql_commands_from_file(self, fileName):

         file = open(fileName, 'r')
         sqlFile = file.read()
         file.close()
         sqlCommands = sqlFile.split(';')

         return sqlCommands

    def add_tables(self, sqlfileName):
        #Connection to the database
        db = sqlite3.connect(self.dbname)
        if db is None:
            raise VFKParBuilderError('Database not connected')
        #Adding tables
        cur = db.cursor()
        sqlCommands = self.get_sql_commands_from_file(sqlfileName)
        #print 'Pocet prikazu', len(sqlCommands)
        for command in sqlCommands:
            cur.execute(command)
        db.commit()#withou commit it does not write data from the last sql command
        db.close()

if __name__ == "__main__":
    #Funkcnost tridy
    object = VFKParBuilder('600016.vfk')
    #object.get_par()
    #object.filter_hp(706860403)
    object.build_all()
    #object.add_tables('add_HP_SBP_geom.sql')
    #print(object.build_all.__doc__) #vypis dokumentacniho retezce
