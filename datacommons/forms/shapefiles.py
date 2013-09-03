from django import forms
from .csvs import ImportableUploadForm, ImportablePreviewForm
from ..models.importable import ShapefileImport 
from ..models import ColumnTypes
from ..models import schemata

class ShapefileUploadForm(ImportableUploadForm):
    IMPORTABLE = ShapefileImport

class ShapefilePreviewForm(ImportablePreviewForm):
    IMPORTABLE = ShapefileImport

    def __init__(self, *args, **kwargs):
        super(ShapefilePreviewForm, self).__init__(*args, **kwargs)
        # find the geom column and make it uneditable
        last_field_index = 0
        for k, v in self.fields.items():
            if k.startswith("column_name_"):
                index = int(k[len("column_name_"):])
                if index > last_field_index:
                    last_field_index = index

        self.fields['column_name_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
        self.fields['column_name_%d' % last_field_index].required = False
        self.fields['type_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
        self.fields['type_%d' % last_field_index].required = False
        self.fields['is_pk_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
        self.fields['is_pk_%d' % last_field_index].required = False

        setattr(self, "clean_column_name_%d" % last_field_index, lambda: self.clean_geometry_name())
        setattr(self, "clean_type_%d" % last_field_index, lambda: self.clean_geometry_type())
        setattr(self, "clean_is_pk_%d" % last_field_index, lambda: self.clean_geometry_pk())

    def clean_geometry_name(self):
        return "the_geom"

    def clean_geometry_type(self):
        return ColumnTypes.GEOMETRY

    def clean_geometry_pk(self):
        return False

    def _columns(self):
        columns = super(ShapefilePreviewForm, self)._columns()
        srid = self.importable.srid()
        type = self.importable.geometryType()
        columns.append(Column("the_geom", ColumnTypes.GEOMETRY, False, srid=srid, geom_type=type))
        return columns
