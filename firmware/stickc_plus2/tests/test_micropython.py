"""Run mp_check.py under a real MicroPython interpreter, when one is available.

Set MICROPYTHON to a unix-port binary (see the README) to enable:

    MICROPYTHON=/path/to/micropython python -m pytest firmware/stickc_plus2/tests
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import build_airports
from golden import FIXTURES, build_golden

STICK_ROOT = Path(__file__).resolve().parents[1]
MICROPYTHON = os.environ.get("MICROPYTHON")


@unittest.skipUnless(MICROPYTHON, "set MICROPYTHON to a MicroPython binary to run")
class MicroPythonTests(unittest.TestCase):
    def test_package_matches_golden_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "golden.json"
            airports_path = Path(tmp) / "airports.bin"
            golden_path.write_text(json.dumps(build_golden()))
            airports_path.write_bytes(build_airports.pack(build_airports.load_airports()))
            result = subprocess.run(
                [MICROPYTHON, str(Path(__file__).with_name("mp_check.py")),
                 str(golden_path), str(airports_path), str(FIXTURES / "klax_adsbfi.json")],
                cwd=STICK_ROOT,
                env={**os.environ, "MICROPYPATH": "%s:.frozen" % STICK_ROOT},
                capture_output=True,
                text=True,
                timeout=120,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ALL OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
