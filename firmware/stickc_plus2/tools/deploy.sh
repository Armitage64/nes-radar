#!/bin/sh
# Copy NES Radar onto an M5StickC Plus2 running UIFlow 2.0 firmware.
#
#   tools/deploy.sh [serial-port]
#
# Needs mpremote (pip install mpremote). The serial port is optional;
# mpremote finds a single attached board on its own.
#
# What it changes on the Stick:
#   - copies nesradar/, airports.bin, main.py (and config.json / ca.der if
#     present here) into /flash, UIFlow's user filesystem;
#   - saves UIFlow's existing /flash/main.py as /flash/main_uiflow.py the
#     first time, so it can be put back;
#   - sets UIFlow's boot_option to 0, so the Stick runs NES Radar at power-on
#     instead of the UIFlow launcher. See "Going back to UIFlow" in README.md.
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
BUILD="$HERE/build"
PORT=${1:-auto}

mkdir -p "$BUILD"
python3 "$HERE/tools/build_airports.py" "$BUILD/airports.bin"

if [ "$PORT" = auto ]; then
    set -- mpremote
else
    set -- mpremote connect "$PORT"
fi

if ! "$@" exec "
import os
try:
    os.stat('/flash/main_uiflow.py')
except OSError:
    try:
        os.rename('/flash/main.py', '/flash/main_uiflow.py')
        print('saved UIFlow main.py as /flash/main_uiflow.py')
    except OSError:
        pass
try:
    os.mkdir('/flash/nesradar')
except OSError:
    pass
"; then
    echo "" >&2
    echo "Could not reach the Stick's REPL. Either an app is running and will" >&2
    echo "not stop, or the Stick is not running UIFlow at all. Check with:" >&2
    echo "    python3 tools/erase_apps.py --dry-run" >&2
    echo "It erases the stuck app, or says to reflash UIFlow with M5Burner." >&2
    exit 1
fi
for module in "$HERE"/nesradar/*.py; do
    "$@" cp "$module" ":/flash/nesradar/$(basename "$module")"
done
"$@" cp "$BUILD/airports.bin" :/flash/airports.bin
if [ -f "$HERE/config.json" ]; then
    "$@" cp "$HERE/config.json" :/flash/config.json
fi
if [ -f "$HERE/ca.der" ]; then
    "$@" cp "$HERE/ca.der" :/flash/ca.der
fi
"$@" cp "$HERE/main.py" :/flash/main.py
"$@" exec "
import esp32
nvs = esp32.NVS('uiflow')
nvs.set_u8('boot_option', 0)
nvs.commit()
print('UIFlow boot_option set to 0: the Stick now starts NES Radar')
"
"$@" reset
echo "Deployed. The Stick restarts into NES Radar."
