import uuid
import os
from django.conf import settings as SETTINGS
from django.db import models, transaction, DatabaseError
from datacommons.schemas.models import ColumnTypes, Version, TableMutator
from datacommons.accounts.models import User

class ImportableUpload(models.Model):
    """This class represents a file in the process of being uploaded and
    imported. It must be subclassed and subclasses must declare themselves as
    proxys in the their Meta class. See the comments below the Meta class for
    more info on subclassing"""
    # mode enums
    CREATE = 1
    APPEND = 2
    UPSERT = 3
    DELETE = 4
    REPLACE = 5

    # status enums
    DONE = 4
    PENDING = 8

    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    # filename relative to MEDIA_ROOT
    filename = models.CharField(max_length=255)
    status = models.IntegerField(choices=((DONE, "Done"), (PENDING, "Pending")), default=PENDING)
    mode = models.IntegerField(choices=(
        (APPEND, "Append"), 
        (CREATE, "Create"),
        (UPSERT, "Upsert"),
        (DELETE, "Delete"),
        (REPLACE, "Replace"),
    ))

    table = models.ForeignKey('schemas.Table')
    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'csv' # TODO rename

    def __unicode__(self):
        return u'%s.%s' % (self.table.schema, self.table.name)

    @property
    def path(self):
        """Return the full path to the file this object represents"""
        return os.path.join(SETTINGS.MEDIA_ROOT, self.filename)


    """
    Subclasses need to provide a way to upload the file, a way to parse the
    file, and a way to iterate over it. 
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

        return cls(filename=filename)

    def parse(self):
        """Parse a file and return the header row, some of the data rows and
        inferred data types.

        For example, a CSV file would return something like

        return ["id", "name"], [[1, "Matt"], [13, "John"]], [ColumnTypes.INTEGER, ColumnTypes.TEXT]
        """
        
        raise NotImplementedError("You must implement the parse method")

    def __iter__(self):
        """
        Provide a mechanism to iterate over the importable object that this
        class represents.

        For example, a CSV would iterate through all the data rows

        for row in some_csv_file:
            yield row
        """
        raise NotImplementedError("You must implement the __iter__ method")

    def importInto(self, columns):
        """Read a file and insert into schema_name.table_name"""
        with transaction.atomic():
            # create a new version for the table
            version = Version(user=self.user, table=self.table)
            version.save()

            tm = TableMutator(version, columns)
            do_insert = self.mode in [ImportableUpload.CREATE, ImportableUpload.APPEND, ImportableUpload.UPSERT, ImportableUpload.REPLACE]
            do_delete = self.mode in [ImportableUpload.UPSERT, ImportableUpload.DELETE]


            # execute the query string for every row
            try:
                if self.mode == ImportableUpload.REPLACE:
                    # delete every existing row
                    tm.deleteAllRows()
            except DatabaseError as e:
                raise DatabaseError("Tried to delete all rows, got this `%s`. SQL was: `%s`:" % (
                    str(e),
                    e.sql,
                ))

            try:
                for row_i, row in enumerate(self):
                    # convert empty strings to null
                    for col_i, col in enumerate(row):
                        row[col_i] = col if col != "" else None

                    if do_delete:
                        # extract out the PKs from the row
                        params = [item for item, col in zip(row, columns) if col.is_pk]
                        tm.deleteRow(params)

                    if do_insert:
                        tm.insertRow(row)
            except DatabaseError as e:
                raise DatabaseError("Tried to insert line %d of the data, got this `%s`. SQL was: `%s`:" % (
                    row_i+1,
                    str(e),
                    e.sql,
                ))


