"""ICAO -> (latitude, longitude) from a packed, sorted table in flash.

The desktop server keeps ~10,000 airports as a 290 KB JSON dict. Parsing that
on the Stick would cost far more RAM than it needs, so tools/build_airports.py
packs the same data, with the per-airport overrides from
server/src/data/airports/ already applied, into fixed 12-byte records:

    4 ASCII bytes code | float32 latitude | float32 longitude   (little-endian)

sorted by code. Lookup is a binary search that seeks within the open file.
"""

import struct

RECORD = struct.calcsize("<4sff")


class AirportTable:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
        if size % RECORD:
            raise ValueError("airport table is not a whole number of records")
        self.count = size // RECORD

    def resolve(self, code):
        code = code.strip().upper()
        if len(code) != 4 or not code.isalpha():
            raise ValueError("ICAO must contain four letters")
        key = code.encode("ascii")
        low, high = 0, self.count - 1
        with open(self.path, "rb") as handle:
            while low <= high:
                middle = (low + high) // 2
                handle.seek(middle * RECORD)
                found, latitude, longitude = struct.unpack("<4sff", handle.read(RECORD))
                if found == key:
                    return latitude, longitude
                if found < key:
                    low = middle + 1
                else:
                    high = middle - 1
        raise ValueError("ICAO %s is not in the airport database" % code)
