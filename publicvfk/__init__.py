#!/usr/bin/env python

import os
import sys
import sqlite3

from osgeo import ogr, osr

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
        if self.dsn_vfk is None:
            raise VFKParBuilderError('Nelze otevrit datasource')

        self.dsn_db = ogr.Open(self.filename + '.db', True)
        if self.dsn_db is None:
            raise VFKParBuilderError('Database in write mode is not connected')
        # Set coordinate system
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(5514)
        # New layer
        table = 'PAR'  # TASK:set capital letters, is it possible?
        self.layer_par = self.dsn_db.CreateLayer(table, srs, ogr.wkbPolygon, ['OVERWRITE=YES'])
        # Layer definition
        self.layer_par_def = self.layer_par.GetLayerDefn()
        # New field - atribute "id_par"
        idField = ogr.FieldDefn("id_par", ogr.OFTInteger)
        self.layer_par.CreateField(idField)

    def get_par(self):
        """Form a unique list of parcel ids by SQL command
        
        :return: list of parcels
        :raises VFKParBuilderError: if the db file is not exist in the directory
        """

        # zdroj: http://zetcode.com/db/sqlitepythontutorial/
        #Connect to db
        db = sqlite3.connect(self.filename + '.db')
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
        
        :param int id_par: The number of parcel is looking for the boundaries
        :return: list of unsorted and both direction vertices for specified parcel number
        :raises VFKParBuilderError: if vfk source file in not connected
        """

        #DataSource
        # Data in layer HP
        lyr_hp = self.dsn_vfk.GetLayerByName('HP')
        if lyr_hp is None:
            raise VFKParBuilderError('Nelze nacist vrstvu HP')
        #Filter of vertices on specified parcel
        hp_list = []
        lyr_hp.SetAttributeFilter("PAR_ID_1 = '{0}' or PAR_ID_2 = '{0}'".format(id_par))
        for feat in lyr_hp:
            hp_list.append(feat)
        lyr_hp.SetAttributeFilter(None)

        return hp_list #jen prvky ve vrstve, nikoliv geometrie (ta je oznacena list_hp)

    def build_par(self, list_hp): #, id_par
        """Build a geometry of number specified parcel in geometric way 
        
        #:param int id_par: The number of parcel which the geometry is build
        :param int list_hp: unsorted list of vertices forming par boundary
        :return: polygon geometry on the specified parcel
        """

        # Create a ring
        ring = ogr.Geometry(ogr.wkbLinearRing)

        # Add the first vertice and remove it in the list of vertices
        vertice_1 = list_hp[0]
        for i in range(len(vertice_1)):
            bod = vertice_1[i]
            ring.AddPoint(bod[0], bod[1])
        list_hp.pop(0)

        # Adding the next vertices
        # Searchng for the end point of the ring in the list of vertices - the first searched point
        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))  # end point

        while len(list_hp) > 0:  # it runs till list_hp contains vertices
            for position in range(len(list_hp)): #position-shows the position of added vertice in list_hp
                if search in list_hp[position]:
                    if (list_hp[position].index(search)) == 0: #the vertice has the same orientation as the first added
                        self.add_boundary(position, 'front', list_hp, ring)
                        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                        break
                    if (list_hp[position].index(search)) > 0:  # the vertice has opposite orientation
                        self.add_boundary(position, 'back', list_hp, ring)
                        search = (ring.GetX(ring.GetPointCount() - 1), ring.GetY(ring.GetPointCount() - 1))
                        break

        # Create polygon
        poly_geom = ogr.Geometry(ogr.wkbPolygon)
        poly_geom.AddGeometry(ring)

        return poly_geom

    def add_boundary(self,position,direction, list_hp, ring):
        """Add the vertice to the ring(geometry of the parcel) 
        
        :param int position: shows the position of added vertice in the list_hp
        :param str direction: specifies vertice direction - 'front' or 'back'
        :param int list_hp: list of unsorted and both direction geometric vertices for specified parcel number
        :param geometry ring: geometry of the parcel that is built #jaky typ u geometrie?
        :return: the ring with added vertice
        """

        vertices = list_hp[position]
        first = (ring.GetX(0), ring.GetY(0))  # the first point in the ring, is not added when the ring is closed(already in)
        if direction == 'front':
            for i in range(1, len(vertices)):
                point = vertices[i]
                if point == first:  #secures doubled first point
                    break
                ring.AddPoint(point[0], point[1])
        if direction == 'back':
            for i in range(len(vertices) - 2, -1, -1):
                point = vertices[i]
                if point == first: #secures doubled first point
                    break
                ring.AddPoint(point[0], point[1])
        list_hp.pop(position)
        return ring

    def build_all(self, limit=None):
        """Build the boundaries of specified amount of parcels according to the unique list of parcel ids and write them in to the database
        
        :param int limit: define amount of built parcels 
        :return: built parcels and corresponding parcel numbers all written in the source database 
        """

        counter = 0

        # get list of unique par ids
        parcels = self.get_par()

        #Start transaction
        self.layer_par.StartTransaction()

        for par_id in parcels:
            list_hp = [] # vytvoreni prazdneho seznamu pro ulozeni hranic sestavovane parcely

            # collect unsorted list of vertices forming par boundary
            for feature in self.filter_hp(par_id):
                geom = feature.GetGeometryRef()
                list_hp.append(geom.GetPoints()) # seznam hranic parcel - jiz geometrie
            #Create par geometry
            poly_geom = self.build_par(list_hp) #(par_id, list_hp)

            #WRITE TO DATABASE
            # Create the feature
            value = ogr.Feature(self.layer_par_def)
            #Set geometry
            value.SetGeometry(poly_geom)
            print("Cislo zapsane parcely: {} ".format(par_id))
            #Set id_par field
            value.SetField("id_par", par_id)
            self.layer_par.CreateFeature(value)
            value = None

            # print result to stdout and check limit (will be removed)
            #print (par_id, poly_geom.ExportToWkt())
            counter += 1
            if limit and counter > limit:
                break
        #End transaction
        self.layer_par.CommitTransaction()

        #Close database
        self.dsn_db = None
        self.dsn_vfk = None

#Funkcnost tridy
object = VFKParBuilder('600016.vfk')
#object.get_par()
#object.filter_hp(706860403)
object.build_all()
#print(object.build_all.__doc__) #vypis dokumentacniho retezce
