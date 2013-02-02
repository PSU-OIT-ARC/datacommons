import re
import csv
import uuid
import os
from django.conf import settings as SETTINGS
from django.db import connection, transaction, DatabaseError

ALLOWED_CONTENT_TYPES = [

]

def handleUploadedDoc(instance, filename):
    """Return a filepath for the document"""
    #if f.content_type not in ALLOWED_CONTENT_TYPES:
    #    raise TypeError("Not a CSV! It is '%s'" % (f.content_type))
    ext = os.path.splitext(filename)[1]

    filename = uuid.uuid4()
    return str(filename.hex) + ext
