from django import forms
from .csvs import ImportableUploadForm, ImportablePreviewForm
from ..models.importable import ShapefileImport 
from ..models import ColumnTypes
from ..models import schemata

class ShapefileUploadForm(ImportableUploadForm):
    MODEL = ShapefileImport

class ShapefilePreviewForm(ImportablePreviewForm):
    MODEL = ShapefileImport

    def __init__(self, *args, **kwargs):
        super(ShapefilePreviewForm, self).__init__(*args, **kwargs)
        # find the geom column and make it uneditable
        last_field_index = 0
        for k, v in self.fields.items():
            if k.startswith("column_name_"):
                index = int(k[len("column_name_"):])
                last_field_index = max(index, last_field_index)

        # make the geom field disabled and not required
        self.fields['column_name_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
        self.fields['column_name_%d' % last_field_index].required = False
        self.fields['type_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
        self.fields['type_%d' % last_field_index].required = False
        self.fields['is_pk_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
        self.fields['is_pk_%d' % last_field_index].required = False

        # create the clean_* methods for all the geom fields. The field
        # name will always be "the_geom" and it will always be of type GEOMETRY
        # and always not part of the PK 
        setattr(self, "clean_column_name_%d" % last_field_index, lambda: "the_geom")
        setattr(self, "clean_type_%d" % last_field_index, lambda: ColumnTypes.GEOMETRY)
        setattr(self, "clean_is_pk_%d" % last_field_index, lambda: False)

    def _columns(self):
        columns = super(ShapefilePreviewForm, self)._columns()
        # the last column is assumed to be the geometry column
        # add on the srid and geom type
        srid = self.model.srid()
        type = self.model.geometryType()
        columns[-1].srid = srid
        columns[-1].geom_type = type
        return columns
