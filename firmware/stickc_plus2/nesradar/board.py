"""M5StickC Plus2 hardware on UIFlow 2.0 firmware (MicroPython only).

UIFlow's M5 module (M5Unified underneath) already knows this board: the
display, buttons, battery gauge, and power latch. Its boot.py also drives the
power-hold pin (G4) high before main.py runs. This module only adds the link
UART, which UIFlow leaves alone.

Top header: GND, 5V OUT, G26, G36/G25, G0, BAT, 3V3, 5V IN.

The link uses the header, where the proto hat plugs in:
  G26 = TX. An ordinary input/output pin.
  G36 = RX. Input-only, which suits receiving. G36 shares its header pad with
        G25, so G25 must stay an input; nothing here configures it.
  G0 is not used. It is a boot-mode strapping pin: held low at power-up
  (for example by the NES resting OUT0 low), the ESP32 would start in
  download mode instead of running NES Radar.
Both go through a level shifter (see README). The default is a pair of NPN
transistor stages, each of which inverts the signal, so the UART inverts TX
and RX in hardware to cancel it. The non-inverting shifters (TXU0202, or the
two single-gate buffers) need "invert": false in config.json.
"""

from machine import UART

import M5

from nesradar.constants import BAUD

LINK_TX_PIN = 26
LINK_RX_PIN = 36
LINK_UART_ID = 1
POWER_OFF_HOLD_MS = 2000


def init():
    """Start M5Unified. UIFlow's own boot does this too; calling it again is safe."""
    M5.begin()


def open_link_uart(invert=True):
    # 9600 8N1, no flow control. At the NES the line idles HIGH (UART mark),
    # as SIGNALING.md requires: with an inverting shifter G26 idles LOW, which
    # leaves the transistor off and its pull-up holding D0 high. A generous RX
    # buffer carries reverse-channel bytes across an HTTPS fetch.
    return UART(
        LINK_UART_ID,
        baudrate=BAUD,
        bits=8,
        parity=None,
        stop=1,
        tx=LINK_TX_PIN,
        rx=LINK_RX_PIN,
        rxbuf=1024,
        txbuf=256,
        timeout=0,
        invert=(UART.INV_TX | UART.INV_RX) if invert else 0,
    )


class Buttons:
    """Front button A and side button B, through M5Unified's debounced state."""

    def poll(self):
        """Call often. Returns (A was pressed, B held long enough to power off)."""
        M5.update()
        return M5.BtnA.wasPressed(), M5.BtnB.pressedFor(POWER_OFF_HOLD_MS)


def battery_percent():
    return M5.Power.getBatteryLevel()


def power_off():
    """On battery this turns the Stick off; on USB power it stays on."""
    M5.Power.powerOff()
