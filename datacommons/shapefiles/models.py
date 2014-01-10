import json
import requests
from itertools import izip
import os
import zipfile
import shapefile
import fnmatch
from django.forms import ValidationError
from django.conf import settings as SETTINGS
from shapely.geometry import asShape
from django.db import models 
from datacommons.schemas.models import ColumnTypes
from datacommons.utils.dbhelpers import sanitize, inferColumnTypes
from datacommons.utils.models import ImportableUpload

# Create your models here.
class ShapefileImport(ImportableUpload):
    ALLOWED_CONTENT_TYPES = [
        'application/x-zip-compressed',
    ]

    class Meta:
        proxy = True

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

        missing_files = set(k for k, v in required_files.items() if v is None)
        if missing_files:
            raise ValidationError("Missing some files: %s" % (", ".join(missing_files)))
        # extract the zip
        # the last part of the path is a guid (except for the .ext part, which we trim off)
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

        # change the path of the importabled object to the .shp file
        importable.filename = guid + '.shp'

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
        if shp.shapeType in [shapefile.POINT, shapefile.POINTM, shapefile.POINTZ, shapefile.MULTIPOINT, shapefile.MULTIPOINTM, shapefile.MULTIPOINTZ]:
            return 'MULTIPOINT'
        elif shp.shapeType in [shapefile.POLYLINE, shapefile.POLYLINEM, shapefile.POLYLINEZ]:
            return 'MULTILINESTRING'
        elif shp.shapeType in [shapefile.POLYGON, shapefile.POLYGONM, shapefile.POLYGONZ]:
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
        shp = shapefile.Reader(self.path)
        for row, shape in izip(shp.iterRecords(), shp.iterShapes()):
            row.append(asShape(shape).wkt)
            yield row

