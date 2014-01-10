from django.db import models

class DownloadLog(models.Model):
    download_id = models.AutoField(primary_key=True)
    file_extension = models.CharField(max_length=4)
    downloaded_on = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey("accounts.User", null=True)
    table = models.ForeignKey("schemas.TableOrView")
    version = models.ForeignKey("schemas.Version", null=True)

    class Meta:
        db_table = 'downloadlog'
