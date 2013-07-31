from collections import defaultdict
from django.db import models
from django.utils.datastructures import SortedDict
from django.contrib.auth.models import User
from dochelpers import handleUploadedDoc

class ColumnTypes:
    """An enum for column types"""
    INTEGER = 1
    NUMERIC = 2
    TIMESTAMP = 4
    TIMESTAMP_WITH_ZONE = 8
    CHAR = 16
    GEOMETRY = 32

    # map the enum to human readable form
    TO_HUMAN = {
        INTEGER: "Integer", 
        NUMERIC: "Decimal",
        TIMESTAMP: "Timestamp",
        TIMESTAMP_WITH_ZONE: "Timestamp w/timezone",
        CHAR: "Text",
        GEOMETRY: "Geometry",
    }

    # map to a PG datatype
    TO_PG_TYPE = {
        INTEGER: "integer", 
        NUMERIC: "numeric",
        TIMESTAMP: "timestamp without time zone",
        TIMESTAMP_WITH_ZONE: "timestamp with time zone",
        CHAR: "text",
        GEOMETRY: "geometry",
    }

    # maps a *cursor* type code to the enum value
    # you can get these numbers from the cursor.description
    FROM_PG_CURSOR_TYPE_CODE = {
        23: INTEGER,
        1700: NUMERIC,
        1114: TIMESTAMP,
        1184: TIMESTAMP_WITH_ZONE,
        25: CHAR,
        16463: GEOMETRY,
    }

    @classmethod
    def toString(cls, enum):
        """Convert type number to a human readable form"""
        return cls.TO_HUMAN[enum]

    @classmethod
    def toPGType(cls, enum):
        """Convert a type number to a PG data type string"""
        return cls.TO_PG_TYPE[enum]

    @classmethod
    def isValidType(cls, enum):
        return enum in cls.TO_HUMAN

    @classmethod 
    def fromPGCursorTypeCode(cls, type_code):
        """Convert a cursor.description type_code to a type number"""
        return cls.FROM_PG_CURSOR_TYPE_CODE[type_code]

    @classmethod 
    def fromPGTypeName(cls, type_code):
        """Convert a PG column type like "timestamp" to a type number"""
        # assume user defined types are geometries
        if type_code == "USER-DEFINED":
            return cls.GEOMETRY
        # invert the PG_TYPE_NAME dict
        return dict(zip(cls.TO_PG_TYPE.values(), cls.TO_PG_TYPE.keys()))[type_code]

# Create your models here.
class ImportableUpload(models.Model):
    # mode
    CREATE = 1
    APPEND = 2
    UPSERT = 3
    DELETE = 4

    # status
    DONE = 4
    PENDING = 8

    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=255)
    status = models.IntegerField(choices=((DONE, "Done"), (PENDING, "Pending")), default=PENDING)
    mode = models.IntegerField(choices=(
        (APPEND, "Append"), 
        (CREATE, "Create"),
        (UPSERT, "Upsert"),
        (DELETE, "Delete"),
    ))

    table = models.OneToOneField('Table')
    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'csv'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s.%s' % (self.table.schema, self.table.name)

class Source(models.Model):
    source_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, default="")
    rank = models.IntegerField(verbose_name="Order") # just the order these rows should appear in

    class Meta:
        db_table = 'source'
        ordering = ['rank']

    def __unicode__(self):
        return u'%s' % (self.name)

class DocUpload(models.Model):
    upload_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, default="")
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=handleUploadedDoc)

    source = models.ForeignKey(Source)
    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'document'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s' % (self.filename)

class TableManager(models.Manager):
    def groupedBySchema(self, owner):
        tables = Table.objects.filter(owner=owner).exclude(created_on=None)
        results = SortedDict()
        for table in tables:
            results.setdefault(table.schema, []).append(table)

        return results

class Table(models.Model):
    table_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    schema = models.CharField(max_length=255)
    created_on = models.DateTimeField(null=True, default=None)

    owner = models.ForeignKey(User, related_name="+")
    
    objects = TableManager()

    class Meta:
        db_table = 'table'
        ordering = ['schema', 'name']

    def __unicode__(self):
        return u'%s' % (self.name)

    def canDo(self, user, permission_bit, perm=None):
        # owner can always do stuff
        if self.owner == user:
            return True

        try:
            if not perm:
                perm = TablePermission.objects.get(table=self, user=user)
        except TablePermission.DoesNotExist:
            return False

        return bool(perm.permission & permission_bit)

    def canInsert(self, user, perm=None):
        return self.canDo(user, TablePermission.INSERT, perm)
    def canUpdate(self, user, perm=None):
        return self.canDo(user, TablePermission.UPDATE, perm)
    def canDelete(self, user, perm=None):
        return self.canDo(user, TablePermission.DELETE, perm)

    def grant(self, user, perm_bit):
        try:
            perm = TablePermission.objects.get(table=self, user=user)
        except TablePermission.DoesNotExist:
            perm = TablePermission(table=self, user=user, permission=0)

        perm.permission |= perm_bit
        perm.save()

    def revoke(self, user, perm_bit):
        try:
            perm = TablePermission.objects.get(table=self, user=user)
        except TablePermission.DoesNotExist:
            perm = TablePermission(table=self, user=user, permission=0)

        perm.permission &= ~perm_bit
        perm.save()

        # if there are no permissions set, just delete the record
        if perm.permission == 0:
            perm.delete()

    def permissionGrid(self):
        perms = TablePermission.objects.filter(table=self).select_related("user")
        rows = {}
        for perm in perms:
            item = rows.setdefault(perm.user, {})
            item['can_insert'] = self.canInsert(perm.user, perm)
            item['can_update'] = self.canUpdate(perm.user, perm)
            item['can_delete'] = self.canDelete(perm.user, perm)

        return rows

class TablePermission(models.Model):
    # permissions need to be powers of 2 so we can do bitwise ANDs and ORs
    INSERT = 1
    UPDATE = 2
    DELETE = 4

    table_permission_id = models.AutoField(primary_key=True)
    table = models.ForeignKey(Table)
    user = models.ForeignKey(User)
    permission = models.IntegerField()

    class Meta:
        db_table = 'tablepermission'
        unique_together = ("table", "user")
