#!/usr/bin/env python3
"""Pack the desktop server's airport data into airports.bin for the Stick.

Reads server/src/data/airports_cache.json and applies every override in
server/src/data/airports/<icao>.json, the same precedence resolve_airport()
uses on the desktop. Writes sorted 12-byte records; see nesradar/airports.py.

The Stick does not refresh this table from OurAirports on its own (the CSV is
~12 MB). Re-run this and redeploy to pick up a newer server/src/data cache.
"""

import argparse
import json
from pathlib import Path
import struct
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "server" / "src" / "data"


def load_airports(data_dir: Path = DATA) -> dict:
    raw = json.loads((data_dir / "airports_cache.json").read_text(encoding="utf-8"))
    airports = {
        str(code).upper(): (float(position[0]), float(position[1]))
        for code, position in raw["airports"].items()
    }
    for override in sorted((data_dir / "airports").glob("*.json")):
        position = json.loads(override.read_text(encoding="utf-8"))
        airports[override.stem.upper()] = (float(position["lat"]), float(position["lon"]))
    return {
        code: position for code, position in airports.items()
        if len(code) == 4 and code.isascii() and code.isalpha()
    }


def pack(airports: dict) -> bytes:
    return b"".join(
        struct.pack("<4sff", code.encode("ascii"), latitude, longitude)
        for code, (latitude, longitude) in sorted(airports.items())
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="path of the airports.bin to write")
    args = parser.parse_args(argv)
    airports = load_airports()
    if len(airports) < 1000:
        print(f"refusing to write only {len(airports)} airports", file=sys.stderr)
        return 1
    data = pack(airports)
    args.output.write_bytes(data)
    print(f"wrote {len(airports):,} airports ({len(data):,} bytes) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
