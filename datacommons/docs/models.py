from django.db import models
from datacommons.accounts.models import User

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
    file = models.FileField(upload_to=lambda instance, filename: str(uuid.uuid4().hex) + os.path.splitext(filename)[-1])

    source = models.ForeignKey(Source)
    user = models.ForeignKey(User, related_name='+', null=True, default=None)

    class Meta:
        db_table = 'document'
        #ordering = ['created_on']

    def __unicode__(self):
        return u'%s' % (self.filename)

