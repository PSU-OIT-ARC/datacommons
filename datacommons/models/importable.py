import json
import requests
from itertools import izip
import re
import uuid
import os
import zipfile
import shapefile
import fnmatch
from django.forms import ValidationError
from django.conf import settings as SETTINGS
from shapely.geometry import asShape
import fnmatch
from django.forms import ValidationError
from django.conf import settings as SETTINGS
from django.contrib.gis import geos
from django.db import connection, transaction, DatabaseError
from .models import ColumnTypes, ImportableUpload, Version
from .dbhelpers import sanitize, getPrimaryKeysForTable, inferColumnTypes, getColumnsForTable
from datacommons.unicodecsv import UnicodeReader

class Importable(object):
    """
    This is an abstract base class. CSV files and shapefiles subclass from
    this. It provides a method to upload a file, parse it, iterate over it, and
    insert/update/delete it into the database
    """

    ALLOWED_CONTENT_TYPES = []

    @classmethod
    def upload(cls, f):
        """Write a file to the media directory. Returns a cls object"""
        if f.content_type not in cls.ALLOWED_CONTENT_TYPES:
            raise TypeError("Not a valid file type! It is '%s'" % (f.content_type))

        filename = str(uuid.uuid4().hex) + ".tmp"
        path = os.path.join(SETTINGS.MEDIA_ROOT, filename)
        with open(path, 'wb+') as dest:
            for chunk in f.chunks():
                dest.write(chunk)

        return cls(filename)

    def __init__(self, filename):
        self.path = os.path.join(SETTINGS.MEDIA_ROOT, filename)

    def parse(self):
        """Parse a file and return the header row, some of the data rows and
        inferred data types"""
        raise NotImplementedError("You must implement the parse method")

    def __iter__(self):
        """
        Provide a mechanism to iterate over the importable object that this
        class represents
        """
        raise NotImplementedError("You must implement the __iter__ method")

    def importInto(self, table, column_names, column_name_to_column_index, mode, user=None):
        """Read a file and insert into schema_name.table_name"""
        # create a new version for the table
        with transaction.commit_on_success():
            version = Version(user=user, table=table)
            version.save()

            # sanitize everything
            schema_name = sanitize(table.schema)
            table_name = sanitize(table.name)
            names = []
            for name in column_names:
                names.append(sanitize(name))
            column_names = names

            column_types = getColumnsForTable(schema_name, table_name)

            audit_table_name = table.auditTableName()

            # build the query string for insert
            do_insert = mode in [ImportableUpload.CREATE, ImportableUpload.APPEND, ImportableUpload.UPSERT]
            if do_insert:
                cols = ','.join([n for n in column_names])
                escape_string = []
                for column_info in column_types:
                    if column_info['type'] == ColumnTypes.GEOMETRY:
                        escape_string.append("ST_GeomFromText(%%s, %s)" % (self.srid()))
                    else:
                        escape_string.append("%s")
                escape_string = ",".join(escape_string)
                insert_sql = """INSERT INTO %s.%s (%s) VALUES(%s)""" % (schema_name, table_name, cols, escape_string)
                
                audit_insert_sql = """INSERT INTO public.%s (%s, _inserted_or_deleted, _version_id) VALUES(%s, 1, %%s)""" % (audit_table_name, cols, escape_string)

            # build the query string for delete
            do_delete = mode in [ImportableUpload.UPSERT, ImportableUpload.DELETE]
            if do_delete:
                pks = getPrimaryKeysForTable(schema_name, table_name)
                escape_string = " AND ".join(["%s = %%s" % pk for pk in pks])
                delete_sql = "DELETE FROM %s.%s WHERE %s" % (schema_name, table_name, escape_string)

                escape_string = ",".join(["%s" for _ in pks])
                audit_delete_sql = """INSERT INTO public.%s (%s, _inserted_or_deleted, _version_id) VALUES(%s, -1, %%s)""" % (audit_table_name, ",".join(pks), escape_string)

            # execute the query string for every row
            for row_i, row in enumerate(self):
                if row_i == 0: continue # skip header row
                # convert empty strings to null
                for col_i, col in enumerate(row):
                    row[col_i] = col if col != "" else None

                if do_delete:
                    # remap the primary key columns since the order of the columns in the CSV does not match
                    # the order of the columns in the db table
                    params = [row[column_name_to_column_index[k]] for k in pks]
                    self._doSQL(delete_sql, params, "delete", row_i + 1)
                    self._doSQL(audit_delete_sql, params + [version.pk], "insert", row_i+1)

                if do_insert:
                    # remap the columns since the order of the columns in the CSV does not match
                    # the order of the columns in the db table
                    params = [row[column_name_to_column_index[k]] for k in column_names]
                    self._doSQL(insert_sql, params, "insert", row_i + 1)
                    self._doSQL(audit_insert_sql, params + [version.pk], "insert", row_i + 1)

    def _doSQL(self, sql, params, exception_operation, exception_line):
        """
        helper for importCSVInto(), just runs the sql, with params, and
        generates a nice exception
        """
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
        except DatabaseError as e:
            connection._rollback()
            raise DatabaseError("Tried to %s line %s of the CSV, got this from database: %s. SQL was: %s" % 
                (exception_operation, exception_line, str(e), connection.queries[-1]['sql'])) 

class CSVImport(Importable):
    ALLOWED_CONTENT_TYPES = [
        'text/csv', 
        'application/vnd.ms-excel', 
        'text/comma-separated-values',
    ]

    def parse(self):
        """Parse a CSV and return the header row, some of the data rows and
        inferred data types"""
        rows = []
        max_rows = 10
        # read in the first few rows, and save to a buffer.
        # Continue reading to check for any encoding errors
        try:
            for i, row in enumerate(self):
                if i < max_rows:
                    rows.append(row)
        except UnicodeDecodeError as e:
            # tack on the line number to the exception so the caller can know
            # which line the error was on. The +2 is because i starts at 0, *and*
            # i in not incremented when the exception is thrown
            e.line = (i + 2)
            raise

        header = [sanitize(c) for c in rows[0]]
        data = rows[1:]
        types = inferColumnTypes(data)
        return header, data, types

    def __iter__(self):
        with open(self.path, 'r') as csvfile:
            reader = UnicodeReader(csvfile)
            for row in reader:
                yield row


class ShapefileImport(Importable):
    ALLOWED_CONTENT_TYPES = [
        'application/x-zip-compressed',
    ]

    @classmethod
    def upload(cls, f):
        importable = super(ShapefileImport, cls).upload(f)
        # extra the zip
        z = zipfile.ZipFile(importable.path, 'r')
        is_safe_path = lambda x: os.path.abspath(x).startswith(os.path.abspath("."))
        # make sure the zipfile entry names aren't hackable
        for entry in z.infolist():
            if not is_safe_path(entry.filename):
                raise ValueError("Security violation") 

        # make sure all the required files exist
        required_files = {
            "*.shp": None, 
            "*.shx": None, 
            "*.dbf": None, 
            "*.prj": None,
        }
        # don't be hating on my O(n*m) algorithm
        for entry in z.infolist():
            for file_ext_glob in required_files:
                if fnmatch.fnmatch(entry.filename, file_ext_glob):
                    required_files[file_ext_glob] = entry.filename

        missing_files = dict([(k, v) for k, v in required_files.items() if v is None])
        if missing_files:
            raise ValidationError("Missing some files: %s" % (", ".join(missing_files.keys())))
        # extract the zip
        guid = os.path.split(importable.path)[1].split(".")[0]
        extract_to = os.path.join(SETTINGS.MEDIA_ROOT, guid)
        z.extractall(extract_to)
        z.close()

        # move the required files
        for file_ext_glob, path in required_files.items():
            ext = file_ext_glob.replace("*", "")
            new_path = os.path.normpath(os.path.join(SETTINGS.MEDIA_ROOT, guid + ext))
            old_path = os.path.normpath(os.path.join(SETTINGS.MEDIA_ROOT, guid, path))
            os.rename(old_path, new_path)
            required_files[file_ext_glob] = new_path

        # change the path of the importabled object to the .shp file
        importable.path = required_files['*.shp']

        return importable

    def srid(self):
        prj_path = self.path.replace(".shp", ".prj")
        prj_file = open(prj_path, 'r')
        prj_text = prj_file.read()

        response = requests.get("http://prj2epsg.org/search.json", params={"terms": prj_text})
        results = json.loads(response.text)
        return int(results['codes'][0]['code'])

    def geometryType(self):
        shp = shapefile.Reader(self.path)
        shp = shp.shape(0)
        if shp.shapeType in [shapefile.POINT, shapefile.POINTM, shapefile.POINTZ]:
            return 'POINT' 
        elif shp.shapeType in [shapefile.MULTIPOINT, shapefile.MULTIPOINTM, shapefile.MULTIPOINTZ]:
            return 'MULTIPOINT'
        elif shp.shapeType in [shapefile.POLYLINE, shapefile.POLYLINEM, shapefile.POLYLINEZ]:
            if len(shp.parts) == 1:
                return 'LINESTRING'
            else:
                return 'MULTILINESTRING'
        elif shp.shapeType in [shapefile.POLYGON, shapefile.POLYGONM, shapefile.POLYGONZ]:
            if len(shp.parts) == 1:
                return 'POLYGON' 
            else:
                return 'MULTIPOLYGON'

    def parse(self):
        """Parse a shapefile and return the header row, some of the data rows and
        inferred data types"""
        rows = []
        max_rows = 10
        # read in the first few rows, and save to a buffer.
        # Unlike parsing CSVs, we do not continue reading after the first few
        # rows, because we assume the shapefile is wellformed
        try:
            for i, row in enumerate(self):
                if i < max_rows:
                    rows.append(row)
                else:
                    break
        except shapefile.ShapefileException as e:
            raise
        except ValueError as e:
            # Python3's `raise SomeException from other_exception` would be nice here
            raise shapefile.ShapefileException("Could not parse shapefile")

        shp = shapefile.Reader(self.path)
        header = [sanitize(field[0]) for field in shp.fields[1:]]
        header.append("the_geom")
        data = rows
        types = inferColumnTypes(data)
        if types[-1] != ColumnTypes.GEOMETRY:
            raise ValidationError("The geometry in the shapefile is invalid") 
        return header, data, types

    def __iter__(self):
        import pdb; pdb.set_trace()
        shp = shapefile.Reader(self.path)
        for row, shape in izip(shp.iterRecords(), shp.iterShapes()):
            row.append(asShape(shape).wkt)
            yield row

