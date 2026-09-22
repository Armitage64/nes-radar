"""Make both the Stick package and the desktop server importable on CPython."""

from pathlib import Path
import sys

STICK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STICK_ROOT.parents[1]
SERVER_SRC = REPO_ROOT / "server" / "src"

for path in (STICK_ROOT, SERVER_SRC, STICK_ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
