#!/bin/sh
# Copy NES Radar onto a Stick that is already running MicroPython.
#
#   tools/deploy.sh [serial-port]
#
# Needs mpremote (pip install mpremote) and a config.json next to this
# script's parent directory (copy config.example.json). The serial port is
# optional; mpremote finds a single attached board on its own.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
BUILD="$HERE/build"
PORT=${1:-auto}

if [ ! -f "$HERE/config.json" ]; then
    echo "Missing $HERE/config.json -- copy config.example.json and fill in Wi-Fi." >&2
    exit 1
fi

mkdir -p "$BUILD"
python3 "$HERE/tools/build_airports.py" "$BUILD/airports.bin"

if [ "$PORT" = auto ]; then
    set -- mpremote
else
    set -- mpremote connect "$PORT"
fi

"$@" mkdir :nesradar 2>/dev/null || true
for module in "$HERE"/nesradar/*.py; do
    "$@" cp "$module" ":nesradar/$(basename "$module")"
done
"$@" cp "$BUILD/airports.bin" :airports.bin
"$@" cp "$HERE/config.json" :config.json
if [ -f "$HERE/ca.der" ]; then
    "$@" cp "$HERE/ca.der" :ca.der
fi
"$@" cp "$HERE/main.py" :main.py
"$@" reset
echo "Deployed. The Stick restarts into NES Radar."
