import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT / "src"))

import nes_radar_server as radar


class Response:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.data


def write_cache(path: Path, updated: float, airports: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"updated": updated, "airports": airports}),
        encoding="utf-8",
    )


class AirportDatabaseTests(unittest.TestCase):
    def tearDown(self):
        radar.AIRPORTS = None

    def test_parse_ourairports_falls_back_to_gps_code(self):
        data = (
            b"id,ident,latitude_deg,longitude_deg,icao_code,gps_code\n"
            b"1,KSBA,34.426201,-119.839996,KSBA,KSBA\n"
            b"2,KCMA,34.213699,-119.094002,,KCMA\n"
        )

        airports = radar.parse_airports_csv(data)

        self.assertEqual(airports["KSBA"], (34.426201, -119.839996))
        self.assertEqual(airports["KCMA"], (34.213699, -119.094002))

    def test_bundled_database_contains_kcma(self):
        airports, _ = radar._read_airport_cache(radar.AIRPORT_CACHE)

        self.assertEqual(airports["KCMA"], (34.213699, -119.094002))

    def test_fresh_user_cache_skips_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.json"
            cache = root / "user" / "airports_cache.json"
            write_cache(bundled, 100.0, {"KSBA": [34.426201, -119.839996]})
            write_cache(cache, 900.0, {"EGLL": [51.470748, -0.459909]})
            opener = mock.Mock(side_effect=AssertionError("download should not run"))

            message = radar.load_airport_database(
                cache,
                bundled,
                now=1000.0,
                opener=opener,
            )

        opener.assert_not_called()
        self.assertEqual(radar.AIRPORTS, {"EGLL": (51.470748, -0.459909)})
        self.assertIn("only 1 airport(s) available", message)

    def test_stale_cache_refreshes_from_fallback_and_persists(self):
        airports = {
            f"A{first}{second}{third}": (10.0, 20.0)
            for first in "ABCDEFGHIJ"
            for second in "ABCDEFGHIJ"
            for third in "ABCDEFGHIJK"
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.json"
            cache = root / "user" / "airports_cache.json"
            write_cache(bundled, 0.0, {"KSBA": [34.426201, -119.839996]})
            response = Response(b"unused")
            opener = mock.Mock(side_effect=[OSError("primary offline"), response])
            with mock.patch.object(radar, "parse_airports_csv", return_value=airports):
                message = radar.load_airport_database(
                    cache,
                    bundled,
                    now=radar.AIRPORT_CACHE_DAYS * 86400.0 + 1.0,
                    opener=opener,
                )

            saved = json.loads(cache.read_text(encoding="utf-8"))

        self.assertEqual(opener.call_count, 2)
        self.assertEqual(len(radar.AIRPORTS), 1100)
        self.assertEqual(len(saved["airports"]), 1100)
        self.assertIn("1,100 airport(s) available", message)

    def test_failed_refresh_keeps_bundled_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.json"
            cache = root / "user" / "airports_cache.json"
            write_cache(bundled, 0.0, {"EGLL": [51.470748, -0.459909]})
            opener = mock.Mock(side_effect=OSError("offline"))

            message = radar.load_airport_database(
                cache,
                bundled,
                now=radar.AIRPORT_CACHE_DAYS * 86400.0 + 1.0,
                opener=opener,
            )

        self.assertEqual(opener.call_count, 2)
        self.assertEqual(radar.resolve_airport("EGLL"), (51.470748, -0.459909))
        self.assertIn("airport database refresh failed", message)


if __name__ == "__main__":
    unittest.main()
