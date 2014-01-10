from django.utils.datastructures import SortedDict
from django.conf import settings as SETTINGS
from django.db import models, connection, transaction, DatabaseError, connections

AUDIT_SCHEMA_NAME = "_version"

class SchemataItem(object):
    """A base class for all items that represent schemata (Schemas, Tables, Columns)"""
    def __unicode__(self):
        return self.name

class Schema(SchemataItem):
    """
    This isn't really a model, it represents a Schema in the database. And allows a schema to be created
    """
    def __init__(self, name):
        self.tables = []
        self.views = []
        self.name = name

    def __iter__(self):
        return iter(self.tables + self.views)

    @classmethod
    def create(cls, name):
        name = sanitize(name)
        cursor = connection.cursor()
        # we aren't using the second parameter to execute() to pass the name in
        # because we already (hopefully) escaped the input
        cursor.execute("CREATE SCHEMA %s" % name)

        # use the stored proc created by mharvey to setup the proper perms on the
        # table
        cursor.execute("SELECT dc_set_perms(%s);", (name,))


class TableOrView(models.Model):
    """The Table model and View models are both proxies for this."""
    table_id = models.AutoField(primary_key=True)
    # the name of the view/table itself
    name = models.CharField(max_length=255)
    # the name of the schema this table belongs in
    schema = models.CharField(max_length=255)
    created_on = models.DateTimeField(null=True, default=None)
    # whether this object represents a table or a view
    is_view = models.BooleanField(default=False, blank=True)

    owner = models.ForeignKey('accounts.User', related_name="+")
    
    class Meta:
        db_table = 'table'
        ordering = ['schema', 'name']

    def __unicode__(self):
        return u'%s' % (self.name)


class View(SchemataItem, TableOrView):
    """This model represents a view in a schema"""
    class Meta:
        proxy = True

    def __init__(self, *args, **kwargs):
        super(View, self).__init__(*args, **kwargs)
        self.columns = []
        self.name = self.name or kwargs.pop("name", None)
        self.is_view = True

    def toJSON(self):
        return {"name": self.name, "columns": self.columns, "is_view": self.is_view}

    def create(self, sql):
        # this will raise a database Error is there is a problem with the SQL (hopefully)
        SQLHandle(sql).count()
        cursor = connection.cursor()
        cursor.execute("SELECT dc_create_view(%s, %s, %s)", (self.schema, self.name, sql))

    def delete(self):
        cursor = connection.cursor()
        cursor.execute('SELECT dc_drop_view(%s,%s)', (sanitize(self.schema), sanitize(self.name)))
        super(View, self).delete()


class TableManager(models.Manager):
    def get_queryset(self):
        return super(TableManager, self).get_queryset().filter(is_view=False)

    def groupedBySchema(self, owner=None, include_views=False):
        # build a set of all the (schema, table) tuples in the db
        topology = getDatabaseTopology()
        s = set()
        for schema in topology:
            for table in schema.tables:
                s.add((schema.name, table.name))

        if owner is None:
            tables = Table.objects.exclude(created_on=None)
        else:
            tables = Table.objects.filter(owner=owner).exclude(created_on=None)

        if not include_views:
            tables = tables.exclude(is_view=True)

        results = SortedDict()
        for table in tables:
            # the tables in the database, and the tables in the "table" table
            # might not quite match. So only return the results where there is a match
            if (table.schema, table.name) in s:
                results.setdefault(table.schema, []).append(table)

        return results


class Table(SchemataItem, TableOrView):
    """
    This object represents a table in a schema
    """
    objects = TableManager()

    class Meta:
        proxy = True

    def __init__(self, *args, **kwargs):
        super(Table, self).__init__(*args, **kwargs)
        self.columns = []
        self.name = self.name or kwargs.pop("name", None)
        self.is_view = False

    def __iter__(self):
        return iter(self.columns)

    def toJSON(self):
        return {"name": self.name, "columns": self.columns, "is_view": self.is_view}

    def auditTableName(self):
        return "_" + self.schema + "_" + self.name

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
    def canRestore(self, user, perm=None):
        return self.canInsert(user, perm) and self.canUpdate(user, perm) and self.canDelete(user, perm)

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

    def create(self, columns):
        column_names = [col.name for col in columns if col.type != ColumnTypes.GEOMETRY]
        column_types = [col.type for col in columns if col.type != ColumnTypes.GEOMETRY]

        # santize all the names
        schema_name = sanitize(self.schema)
        table_name = sanitize(self.name)

        # sanitize 
        names = []
        for name in column_names:
            names.append(sanitize(name))
        column_names = names

        names = []
        for name in [col.name for col in columns if col.is_pk]:
            names.append(sanitize(name))
        primary_keys = names

        # get all the column type names
        types = []
        for type in column_types:
            types.append(ColumnTypes.toPGType(int(type)))

        column_sql = []
        for i in range(len(column_names)):
            column_sql.append(column_names[i] + " " + types[i])
        column_sql = ",".join(column_sql)

        # sure hope this is SQL injection proof
        create_table_sql = """
            CREATE TABLE "%s"."%s" (
                %s
            );
        """ % (schema_name, table_name, column_sql)
        cursor = connection.cursor()
        cursor.execute(create_table_sql)

        # now add the audit table
        audit_table_name = self.auditTableName()
        audit_table_sql = """
            CREATE TABLE "%s"."%s" (
                _version_id INTEGER NOT NULL REFERENCES "version" ("version_id") DEFERRABLE INITIALLY DEFERRED,
                _inserted_or_deleted smallint,
                %s
            );
        """ % (AUDIT_SCHEMA_NAME, audit_table_name, column_sql)
        cursor.execute(audit_table_sql)

        # add the primary key, if there is one
        if len(primary_keys):
            sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % (schema_name, table_name, ",".join(primary_keys))
            cursor.execute(sql)

            audit_pks = primary_keys + ['_version_id', '_inserted_or_deleted']
            sql = """ALTER TABLE "%s"."%s" ADD PRIMARY KEY (%s);""" % (AUDIT_SCHEMA_NAME, audit_table_name, ",".join(audit_pks))
            cursor.execute(sql)

        has_geom = any(col.srid for col in columns)
        if has_geom:
            # find the column with the geometry
            col = [col for col in columns if col.srid][0]
            self._addGeometryColumn(schema_name, table_name, col)
            self._addGeometryColumn(AUDIT_SCHEMA_NAME, audit_table_name, col)

        # run morgan's fancy proc
        cursor.execute("SELECT dc_set_perms(%s, %s);", (schema_name, table_name))
        cursor.execute("SELECT dc_set_perms(%s, %s);", (AUDIT_SCHEMA_NAME, audit_table_name))

    def _addGeometryColumn(self, schema_name, table_name, col):
        cursor = connection.cursor()
        cursor.execute("""SELECT AddGeometryColumn(%s, %s, %s, %s, %s, 2)""",
            (schema_name, table_name, col.name, SETTINGS.OFFICIAL_SRID, col.geom_type))


class TablePermission(models.Model):
    # permissions need to be powers of 2 so we can do bitwise ANDs and ORs
    INSERT = 1
    UPDATE = 2
    DELETE = 4

    table_permission_id = models.AutoField(primary_key=True)
    table = models.ForeignKey('Table')
    user = models.ForeignKey('accounts.User')
    permission = models.IntegerField()

    class Meta:
        db_table = 'tablepermission'
        unique_together = ("table", "user")


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
        return cls.FROM_PG_CURSOR_TYPE_CODE.get(type_code, cls.CHAR)

    @classmethod 
    def fromPGTypeName(cls, type_code):
        """Convert a PG column type like "timestamp" to a type number"""
        # assume user defined types are geometries
        return dict(zip(cls.TO_PG_TYPE.values(), cls.TO_PG_TYPE.keys()))[type_code]


class Column(SchemataItem):
    """This just represents a column in a table/view"""
    def __init__(self, name, type, is_pk, srid=None, geom_type=None):
        self.name = name
        self.type = type
        self.is_pk = is_pk
        self.srid = srid
        self.geom_type = geom_type

        self.type_label = ColumnTypes.toString(self.type)


class Version(models.Model):
    """
    This model stores simple data about the history of a table. Anytime someone
    mutates a table, a new version is created
    """
    version_id = models.AutoField(primary_key=True)
    created_on = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey('accounts.User')
    table = models.ForeignKey('Table')

    class Meta:
        db_table = 'version'
        ordering = ['created_on']

    def diff(self, columns):
        """Compares this version of the table with the current version. Returns
        an iterator of 4-tuples, where each element in the 4-tuple is:
            * a row from the current version of the table
            * the corresponding row from this version of the table
            * a tuple of the primary key values (these will be the same for the current and old version)
            * a string "update", "insert" or "delete" that indicates should be
              done to the current table to make it match this version 
        """
        table_name = '"%s"."%s"' % (sanitize(self.table.schema), sanitize(self.table.name))
        audit_table_name = '"%s"' % (internalSanitize(self.table.auditTableName()))

        safe_params = {
            "table_name": table_name,
            "pks": ",".join('"%s"' % sanitize(col.name) for col in columns if col.is_pk), 
            "audit_table_name": audit_table_name,
            "audit_schema_name": AUDIT_SCHEMA_NAME,
            "table_columns": ",".join('%s."%s"' % (table_name, sanitize(col.name)) for col in columns),
            "audit_table_columns": ",".join('%s."%s"' % (audit_table_name, col.name) for col in columns),
        }

        sql = """
        SELECT 
            %(table_columns)s, 
            _restore_to.*, 
            %(pks)s,
            CASE WHEN _restore_to.* IS null THEN 'delete' WHEN %(table_name)s.* IS NULL THEN 'insert' ELSE 'update' END
        FROM 
        (
            SELECT %(audit_table_columns)s FROM
                (
                    SELECT
                        SUM(_inserted_or_deleted),
                        MAX(_version_id) AS _version_id,
                        %(pks)s
                    FROM
                        %(audit_schema_name)s.%(audit_table_name)s
                    WHERE _version_id <= %%s
                    GROUP BY
                        %(pks)s
                    HAVING
                        SUM(_inserted_or_deleted) >= 0
                ) pks
                INNER JOIN %(audit_schema_name)s.%(audit_table_name)s USING(%(pks)s, _version_id)
                WHERE _inserted_or_deleted = 1
        ) _restore_to

        FULL OUTER JOIN

        %(table_name)s USING(%(pks)s)

        WHERE COALESCE(_restore_to.* != %(table_name)s.*, true)
        """ % safe_params
        cursor = connection.cursor()

        cursor.execute(sql, (self.pk,))
        for row in cursor.fetchall():
            original_data = row[0:len(columns)]
            restore_to = row[len(columns):2*len(columns)]
            pk_values = row[len(columns)*2:-1]
            action = row[-1]
            yield original_data, restore_to, pk_values, action

    def restore(self, user):
        """Overwrite all the data in the table, and replace it with this version""" 
        with transaction.atomic():
            version = Version(user=user, table=self.table)
            version.save()
            tm = TableMutator(version)

            rows = self.diff(tm.columns)
            for original_data, restore_to, pk_values, action in rows:
                if action in ['delete', 'update']:
                    tm.deleteRow(pk_values)

                if action in ['update', 'insert']:
                    tm.insertRow(restore_to)

    def fetchRows(self):
        """Fetch all the rows in the table for this version of the table"""
        table = self.table
        audit_table_name = table.auditTableName()
        pks = getPrimaryKeysForTable(table.schema, table.name)
        pks_str = ",".join(pk.name for pk in pks)
        columns = [col.name for col in getColumnsForTable(table.schema, table.name)]
        columns_str = ",".join(columns)

        safe_params = {
            "table": audit_table_name, 
            "pks": pks_str, 
            "columns": columns_str,
            "schema": AUDIT_SCHEMA_NAME,
        }
        params = (self.pk,)
        sql = """
        SELECT %(columns)s FROM
        (
            SELECT 
                SUM(_inserted_or_deleted), 
                MAX(_version_id) AS _version_id, 
                %(pks)s
            FROM 
                %(schema)s.%(table)s
            WHERE _version_id <= %%s
            GROUP BY 
                %(pks)s
            HAVING 
                SUM(_inserted_or_deleted) >= 0
        ) pks
        INNER JOIN %(schema)s.%(table)s USING(%(pks)s, _version_id)
        WHERE _inserted_or_deleted = 1
        ORDER BY %(pks)s
        """ % safe_params
        #cursor = connection.cursor()
        #cursor.execute(sql, params)
        return SQLHandle(sql, params, privileged=True)


class TableMutator(object):
    """
    This handles building the SQL to actually mutate the table, since it all
    has to be created dynamically. It also provides methods to perform
    mutations
    """
    def __init__(self, version, columns=None):
        self.table = version.table

        # the caller can pass in the columns, or we can fetch them ourselves
        if columns is None:
            self.columns = getColumnsForTable(self.table.schema, self.table.name)
        else:
            self.columns = columns

        # build SQL query strings for inserting data and deleting data from the
        # table itself, and the audit table
        
        # build the escape string for insert queries. A little complex because
        # we have to handle Geometry columns. 
        escape_string = []
        for col in self.columns:
            if col.type == ColumnTypes.GEOMETRY:
                escape_string.append("ST_Multi(ST_Transform(ST_GeomFromText(%%s, %s), %d))" % (col.srid, SETTINGS.OFFICIAL_SRID))
            else:
                escape_string.append("%s")
        escape_string = ",".join(escape_string)
        safe_col_name_str = ",".join('"%s"' % sanitize(col.name) for col in self.columns)
        self.insert_sql = """INSERT INTO "%s"."%s" (%s) VALUES(%s)""" % (
            sanitize(self.table.schema), 
            sanitize(self.table.name),
            safe_col_name_str,
            escape_string,
        )
        self.audit_insert_sql = """INSERT INTO "%s"."%s" (%s, _inserted_or_deleted, _version_id) VALUES(%s, 1, %s)""" % (
            AUDIT_SCHEMA_NAME,
            internalSanitize(self.table.auditTableName()),
            safe_col_name_str, 
            escape_string,
            int(version.pk),
        )

        # now build the delete SQL strings
        escape_string = " AND ".join(['"%s" = %%s' % sanitize(col.name) for col in self.columns if col.is_pk])
        self.delete_sql = 'DELETE FROM "%s"."%s" WHERE %s' % (
            sanitize(self.table.schema), 
            sanitize(self.table.name), 
            escape_string
        )
        escape_string = ",".join(["%s" for col in self.columns if col.is_pk])
        safe_pk_name_str = ",".join(['"%s"' % sanitize(col.name) for col in self.columns if col.is_pk])
        self.audit_delete_sql = """INSERT INTO %s.%s (%s, _inserted_or_deleted, _version_id) VALUES(%s, -1, %s)""" % (
            AUDIT_SCHEMA_NAME,
            internalSanitize(self.table.auditTableName()), 
            safe_pk_name_str,
            escape_string,
            int(version.pk)
        )
        self.cursor = connection.cursor()

    def insertRow(self, values):
        """Values is a tuple of values that corresponds to the order of self.columns"""
        self._doSQL(self.insert_sql, values)
        self._doSQL(self.audit_insert_sql, values)

    def deleteRow(self, values):
        """Values is a tuple of pk values that corresponds to the order of self.columns"""
        if self._doSQL(self.delete_sql, values) > 0:
            self._doSQL(self.audit_delete_sql, values)

    def deleteAllRows(self):
        pks = [col.name for col in self.columns if col.is_pk]
        handle = fetchRowsFor(self.table.schema, self.table.name, pks)
        for row in handle:
            self.deleteRow(row)

    def _doSQL(self, sql, params):
        cursor = self.cursor
        try:
            with transaction.atomic():
                cursor.execute(sql, params)
        except DatabaseError as e:
            # tack on the SQL statement that caused the error, the last
            # statement will be a rollback, and the 2nd to last will be the
            # actual statement that caused the error
            e.sql = connection.queries[-2]['sql'] if len(connection.queries) >= 2 else ""
            raise

        return cursor.rowcount

from datacommons.utils.dbhelpers import sanitize, SQLHandle, getDatabaseTopology, internalSanitize, getPrimaryKeysForTable, getColumnsForTable, fetchRowsFor
