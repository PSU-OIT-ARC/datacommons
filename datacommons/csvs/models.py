from django.db import models
from datacommons.utils.models import ImportableUpload
from datacommons.unicodecsv import UnicodeReader
from datacommons.utils.dbhelpers import sanitize, inferColumnTypes

# Create your models here.
class CSVImport(ImportableUpload):
    ALLOWED_CONTENT_TYPES = [
        'text/csv', 
        'application/vnd.ms-excel', 
        'text/comma-separated-values',
    ]

    class Meta:
        proxy = True

    def parse(self):
        """Parse a CSV and return the header row, some of the data rows and
        inferred data types"""
        rows = []
        max_rows = 10
        # read in the first few rows, and save to a buffer.
        # Continue reading to check for any encoding errors
        try:
            last_row = None
            for i, row in enumerate(self):
                if i < max_rows:
                    rows.append(row)
                if last_row != None and len(last_row) != len(row):
                    raise ValueError("CSV rows are not all the same length. Or maybe you have an extra newline at the bottom of your file")
                last_row = row
        except UnicodeDecodeError as e:
            # tack on the line number to the exception so the caller can know
            # which line the error was on. The +2 is because i starts at 0, *and*
            # i in not incremented when the exception is thrown
            e.line = (i + 2)
            raise

        header = [sanitize(c) for c in self.header()]
        data = rows
        types = inferColumnTypes(data)
        return header, data, types

    def header(self):
        with open(self.path, 'r') as csvfile:
            reader = UnicodeReader(csvfile)
            for i, row in enumerate(reader):
                return [col.strip() for col in row]

    def __iter__(self):
        with open(self.path, 'r') as csvfile:
            reader = UnicodeReader(csvfile)
            for i, row in enumerate(reader):
                # skip over the header row
                if i == 0: continue
                yield [col.strip() for col in row]


