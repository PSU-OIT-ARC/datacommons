from django.db import models
from django.contrib.auth.models import User

class ColumnTypes:
    INTEGER = 1
    NUMERIC = 2
    TIMESTAMP = 4
    TIMESTAMP_WITH_ZONE = 8
    CHAR = 16

    DESCRIPTION = {
        INTEGER: "Integer", 
        NUMERIC: "Decimal",
        TIMESTAMP: "Timestamp",
        TIMESTAMP_WITH_ZONE: "Timestamp w/timezone",
        CHAR: "Text",
    }

    PG_TYPE_NAME = {
        INTEGER: "integer", 
        NUMERIC: "numeric",
        TIMESTAMP: "timestamp without time zone",
        TIMESTAMP_WITH_ZONE: "timestamp with time zone",
        CHAR: "text",
    }

    # maps a cursor type code to one of the ColumnTypes
    PG_TYPE_CODE_TO_COLUMN_TYPE = {
        23: INTEGER,
        1700: NUMERIC,
        1184: TIMESTAMP,
        1114: TIMESTAMP_WITH_ZONE,
        25: CHAR,
    }

    @classmethod
    def toString(cls, enum):
        return cls.DESCRIPTION[enum]

    @classmethod
    def toPGType(cls, enum):
        return cls.PG_TYPE_NAME[enum]

    @classmethod
    def isValidType(cls, enum):
        return enum in cls.DESCRIPTION

    @classmethod 
    def pgColumnTypeNameToType(cls, type_code):
        # invert the PG_TYPE_NAME dict
        return cls.PG_TYPE_CODE_TO_COLUMN_TYPE[type_code]
        #return dict(zip(cls.PG_TYPE_NAME.values(), cls.PG_TYPE_NAME.keys()))[type_code]

# Create your models here.
class CSVUpload(models.Model):
    # mode
    CREATE = 1
    APPEND = 2

    # status
    DONE = 4
    PENDING = 8

    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255)
    schema = models.CharField(max_length=255)
    table = models.CharField(max_length=255, null=True)
    name = models.CharField(max_length=255, default="")
    status = models.IntegerField(default=PENDING)
    mode = models.IntegerField(choices=((APPEND, "Append"), (CREATE, "Create")))

    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'csv'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s.%s' % (self.schema, self.table)

class DocUpload(models.Model):
    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=255, default="")
    filename = models.CharField(max_length=255)

    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'document'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s' % (self.name)
