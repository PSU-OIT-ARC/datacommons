from django import forms
from datacommons.importable.forms import ImportableUploadForm, ImportablePreviewForm
from datacommons.schemas.models import ColumnTypes
from datacommons.importable.models import ImportableUpload
from .models import ShapefileImport 

class ShapefileUploadForm(ImportableUploadForm):
    MODEL = ShapefileImport

class ShapefilePreviewForm(ImportablePreviewForm):
    MODEL = ShapefileImport
    srid = forms.TypedChoiceField(choices=(
        (4326, "4326 - WGS 84"),
        (3857, "3857 - Web Mercator")
        ), empty_value=None, coerce=int)

    def __init__(self, *args, **kwargs):
        super(ShapefilePreviewForm, self).__init__(*args, **kwargs)
        if self.model.mode == ImportableUpload.CREATE:
            # find the geom column and make it uneditable
            last_field_index = 0
            for k, v in self.fields.items():
                if k.startswith("column_name_"):
                    index = int(k[len("column_name_"):])
                    last_field_index = max(index, last_field_index)

            # make the geom field disabled and not required
            self.fields['column_name_%d' % last_field_index].widget.attrs["disabled"] = "disabled"
            self.fields['column_name_%d' % last_field_index].required = False
            self.fields['column_name_%d' % last_field_index].initial = "the_geom"
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
        srid = self.cleaned_data['srid']
        type = self.model.geometryType()
        columns[-1].srid = srid
        columns[-1].geom_type = type
        return columns
