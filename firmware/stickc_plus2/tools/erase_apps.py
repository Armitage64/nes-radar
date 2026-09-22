#!/usr/bin/env python3
"""Erase every user file on a UIFlow Stick, whatever app is running.

    python3 tools/erase_apps.py [serial-port] [--dry-run] [--yes]

Use this when tools/deploy.sh fails with "could not enter raw repl": some
running app is not giving up the REPL (a long blocking call, or Ctrl-C
disabled), so mpremote cannot interrupt it.

This does not ask the running app for anything. esptool resets the chip into
its ROM bootloader over USB, reads the partition table, and erases only the
"vfs" partition: UIFlow's /flash (main.py, boot.py, apps, NES Radar). On the
next boot UIFlow finds it empty and recreates a fresh boot.py and folders.

Kept: the firmware, UIFlow's /system files (fonts, images), and the "nvs"
settings partition, so Wi-Fi from M5Burner or tools/set_wifi.py survives.
Run tools/deploy.sh afterwards.

Needs esptool: pip install esptool
"""

import argparse
import glob
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile

TABLE_OFFSET = 0x8000
TABLE_SIZE = 0xC00
ENTRY = struct.Struct("<2sBBII16sI")
ENTRY_MAGIC = b"\xaa\x50"
USER_PARTITION = b"vfs"


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/ttyUSB*")
                   + glob.glob("/dev/ttyACM*"))
    if len(ports) != 1:
        sys.exit("Found %d serial ports %s; pass the Stick's port as an argument."
                 % (len(ports), ports))
    return ports[0]


def esptool(*args):
    command = [sys.executable, "-m", "esptool", *args]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("esptool failed:\n" + (result.stdout + result.stderr)[-2000:])
    return result.stdout


def parse_partitions(table):
    """[(label, type, subtype, offset, size)] from an ESP-IDF partition table."""
    partitions = []
    for start in range(0, len(table) - ENTRY.size + 1, ENTRY.size):
        magic, kind, subtype, offset, size, label, _flags = ENTRY.unpack_from(table, start)
        if magic != ENTRY_MAGIC:
            break  # 0xFFFF padding or the MD5 entry ends the table
        partitions.append((label.rstrip(b"\x00"), kind, subtype, offset, size))
    return partitions


def main():
    parser = argparse.ArgumentParser(description="Erase UIFlow's user files (/flash).")
    parser.add_argument("port", nargs="?", help="serial port (found automatically if one)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and show the partition table, erase nothing")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()
    if importlib.util.find_spec("esptool") is None:
        sys.exit("esptool is not installed: pip install esptool")
    port = args.port or find_port()

    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, "partitions.bin")
        print("Reading the partition table from %s ..." % port)
        esptool("--port", port, "read_flash", hex(TABLE_OFFSET), hex(TABLE_SIZE), dump)
        with open(dump, "rb") as handle:
            partitions = parse_partitions(handle.read())
    if not partitions:
        sys.exit("No partition table found; is this an ESP32 running UIFlow?")

    print("\n  %-10s %10s %10s" % ("partition", "offset", "size"))
    user = None
    for label, _kind, _subtype, offset, size in partitions:
        note = ""
        if label == USER_PARTITION:
            user = (offset, size)
            note = "<- erased: /flash user files"
        elif label == b"nvs":
            note = "kept: Wi-Fi and UIFlow settings"
        print("  %-10s %#10x %#10x  %s" % (label.decode(errors="replace"), offset, size, note))
    if user is None:
        labels = {partition[0] for partition in partitions}
        kind = ("an Arduino or ESP-IDF app" if {b"app0", b"spiffs"} & labels
                else "some other firmware")
        sys.exit(
            "\nNothing erased: this Stick is not running UIFlow 2.0 (no 'vfs'\n"
            "partition; the table above looks like %s). Reflash UIFlow 2.0\n"
            "with M5Burner, then run tools/set_wifi.py and tools/deploy.sh." % kind
        )
    offset, size = user
    if args.dry_run:
        print("\nDry run: nothing erased.")
        return
    if not args.yes:
        answer = input("\nErase %d KB of user files at %#x? This cannot be undone. [y/N] "
                       % (size // 1024, offset))
        if answer.strip().lower() not in ("y", "yes"):
            sys.exit("Nothing erased.")
    print("Erasing ...")
    # esptool hard-resets the chip after each command, so it restarts itself.
    esptool("--port", port, "erase_region", hex(offset), hex(size))
    print("Done. The Stick restarts with an empty /flash; run tools/deploy.sh next.")


if __name__ == "__main__":
    main()
