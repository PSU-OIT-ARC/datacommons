import re
import uuid
import os
from django.conf import settings as SETTINGS
from django.db import connection, transaction, DatabaseError

ALLOWED_CONTENT_TYPES = [

]

def handleUploadedDoc(instance, filename):
    """Return a filepath for the document"""
    ext = os.path.splitext(filename)[1]

    filename = uuid.uuid4()
    return str(filename.hex) + ext
