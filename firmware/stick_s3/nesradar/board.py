"""M5StickS3 hardware on UIFlow 2.0 firmware (MicroPython only).

UIFlow's M5 module (M5Unified underneath) already knows this board: the
display, buttons, and the M5PM1 power chip (battery gauge, power-off). This
module only adds the link UART, which UIFlow leaves alone.

The proto hat plugs into the odd row of the 16-pin Hat2-Bus, which keeps the
old StickC 8-pin order: GND, EXT_5V, G0, G1, G8, BAT, 3V3_L2, 5V_IN.

  G8 = TX (hat slot 5). An ordinary input/output pin.
  G1 = RX (hat slot 4). An ordinary input/output pin, used as an input.
  G0 (slot 3, where older Sticks had G26) is not used. It is the boot-mode
  strapping pin: anything holding it low at power-up (a transistor's base
  resistor, or the RX collector while the NES idles OUT0 high) makes the
  ESP32-S3 start in download mode instead of running NES Radar.
  EXT_5V (slot 2) is a power input by default and stays unconnected.
  G3 (JTAG strap) and G43/G44 (UART0, which carries the boot ROM log) are
  avoided; the even row is out of the proto hat's reach.
Both go through a level shifter (see README). The default is a pair of NPN
transistor stages, each of which inverts the signal, so the UART inverts TX
and RX in hardware to cancel it. The non-inverting shifters (TXU0202, or the
two single-gate buffers) need "invert": false in config.json.
"""

from machine import UART

import M5

from nesradar.constants import BAUD

LINK_TX_PIN = 8
LINK_RX_PIN = 1
LINK_UART_ID = 1
POWER_OFF_HOLD_MS = 2000


def init():
    """Start M5Unified. UIFlow's own boot does this too; calling it again is safe."""
    M5.begin()


def check_board():
    """Refuse to drive the link pins on any board but a StickS3."""
    if M5.getBoard() != M5.BOARD.M5StickS3:
        raise ValueError("NES Radar needs an M5StickS3")


def open_link_uart(invert=True):
    # 9600 8N1, no flow control. At the NES the line idles HIGH (UART mark),
    # as SIGNALING.md requires: with an inverting shifter G8 idles LOW, which
    # leaves the transistor off and its pull-up holding D0 high. A generous RX
    # buffer carries reverse-channel bytes across an HTTPS fetch.
    check_board()
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
