"""Bench helper: print every byte the Stick receives from the NES, and decode it.

    mpremote run tools/rx_monitor.py

Shows the reverse channel without a logic analyzer. Enter an airport in the
NES editor and press Start: a correct build prints the six-byte request, for
example KSBA as 4e 4b 53 42 41 f0, and then the decoded code. Break bytes
(0x00) around the frame are normal.

It also reports how many bytes arrive while nothing is being sent, which
shows whether controller-strobe pulses on OUT0 reach the UART as noise.

`mpremote run` interrupts NES Radar before starting this, and the Stick stays
powered. Run it on USB power, and run `mpremote reset` afterwards to go back
to NES Radar.
"""

import json
import time

from nesradar import board
from nesradar.reverse import ACTIVITY, ReverseDecoder

REPORT_MS = 5000


def invert_setting():
    try:
        with open("/flash/config.json") as handle:
            return json.load(handle).get("invert", True)
    except (OSError, ValueError):
        return True


def main():
    invert = invert_setting()
    uart = board.open_link_uart(invert=invert)
    decoder = ReverseDecoder()
    print("listening on G1, invert=%s; press Start on the NES; Ctrl-C to stop" % invert)
    quiet_bytes = 0
    report_at = time.ticks_add(time.ticks_ms(), REPORT_MS)
    try:
        while True:
            now = time.ticks_ms()
            waiting = uart.any()
            chunk = uart.read(waiting) if waiting else b""
            if chunk:
                print("rx", " ".join("%02x" % byte for byte in chunk))
                quiet_bytes += len(chunk)
            for event in decoder.service(chunk or b"", now, time.ticks_diff):
                if event != ACTIVITY:
                    print("  decoded:", event)
                    quiet_bytes = 0
            if time.ticks_diff(now, report_at) >= 0:
                print("%d byte(s) in the last %d s outside decoded frames"
                      % (quiet_bytes, REPORT_MS // 1000))
                quiet_bytes = 0
                report_at = time.ticks_add(now, REPORT_MS)
            time.sleep_ms(2)
    except KeyboardInterrupt:
        print("stopped")


main()
