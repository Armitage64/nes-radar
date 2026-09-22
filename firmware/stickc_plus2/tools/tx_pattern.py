"""Bench helper: send a steady scope-friendly pattern on the link TX.

    mpremote run tools/tx_pattern.py

Sends 0x55 every 20 ms until Ctrl-C. At 9600 8N1, LSB first, 0x55 is a clean
square wave on the wire: ten 104 us bits alternating L H L H L H L H L H
(start bit, eight data bits, stop bit), then idle high. With the NPN shifter
and "invert": true, the NES side (D0) must show exactly that, and G26 its
inverse.

0x55 is not a packet marker, so a ROM listening for packets ignores it. Run
it with the NES on and the ROM in the airport editor; with the NES off, the
D0 pull-up has no supply and there is nothing to see on D0.

`mpremote run` interrupts NES Radar before starting this, and the Stick stays
powered. Run it on USB power, and run `mpremote reset` afterwards to go back
to NES Radar.
"""

import json
import time

from nesradar import board

PATTERN = b"\x55"
PERIOD_MS = 20


def invert_setting():
    try:
        with open("/config.json") as handle:
            return json.load(handle).get("invert", True)
    except (OSError, ValueError):
        return True


def main():
    invert = invert_setting()
    uart = board.open_link_uart(invert=invert)
    print("sending 0x55 every %d ms on G26, invert=%s; Ctrl-C to stop" % (PERIOD_MS, invert))
    try:
        while True:
            uart.write(PATTERN)
            uart.flush()
            time.sleep_ms(PERIOD_MS)
    except KeyboardInterrupt:
        print("stopped; TX left at idle")


main()
