import re
import csv
import uuid
import os
from django.conf import settings as SETTINGS
from django.db import connection, transaction, DatabaseError

ALLOWED_CONTENT_TYPES = [

]

def handleUploadedDoc(f):
    """Write a doc to the media directory"""
    #if f.content_type not in ALLOWED_CONTENT_TYPES:
    #    raise TypeError("Not a CSV! It is '%s'" % (f.content_type))
    ext = os.path.splitext(f.name)[1]

    filename = uuid.uuid4()
    path = os.path.join(SETTINGS.MEDIA_ROOT, str(filename.hex) + ext)
    with open(path, 'wb+') as dest:
            for chunk in f.chunks():
                dest.write(chunk)
    return path
