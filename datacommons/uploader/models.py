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

    PG_TYPE = {
        INTEGER: "integer", 
        NUMERIC: "numeric",
        TIMESTAMP: "timestamp  with time zone",
        TIMESTAMP_WITH_ZONE: "timestamp  without time zone",
        CHAR: "Text",
    }

    @classmethod
    def toString(cls, enum):
        return cls.DESCRIPTION[enum]

    @classmethod
    def toPGType(cls, enum):
        return cls.PG_TYPE[enum]

# Create your models here.
class CSVUpload(models.Model):
    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255)
    schema = models.CharField(max_length=255)
    table = models.CharField(max_length=255)
    name = models.CharField(max_length=255, default="")
    status = models.IntegerField(default=0)

    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'upload'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s.%s' % (self.schema, self.name)
