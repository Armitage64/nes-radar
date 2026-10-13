"""M5StickS3 and M5StickC Plus2 hardware on UIFlow 2.0 firmware (MicroPython only).

UIFlow's M5 module (M5Unified underneath) already knows both boards: the
display, buttons, battery gauge and power-off. This module only adds the link
UART, which UIFlow leaves alone.

One proto hat serves both boards, wired as nesp32's docs/WIRING.md has it:
its slots reach different pins on each, and the link is on the same two slots.

  slot     1    2       3    4        5    6    7       8
  S3       GND  EXT_5V  G0   G1       G8   BAT  3V3_L2  5V_IN
  Plus2    GND  5V OUT  G26  G36/G25  G0   BAT  3V3     5V IN

  S3:    TX on G8 (slot 5), RX on G1 (slot 4). The hat plugs into the odd
         row of the 16-pin Hat2-Bus. EXT_5V is a power input by default and
         stays unconnected. G3 (JTAG strap) and G43/G44 (UART0, which carries
         the boot ROM log) are avoided; the even row is out of the hat's reach.
  Plus2: TX on G0 (slot 5), RX on G36 (slot 4). G36 is input-only and shares
         its pad with G25, which must stay an input; nothing here configures
         it.

G0 is the boot-mode strapping pin on both. On a StickS3 it is slot 3, which
the hat leaves open: either stage there (a transistor's base resistor, or the
RX collector while the NES idles OUT0 high) would start the board in download
mode instead of NES Radar. On a StickC Plus2 it is slot 5, the hat's TX, and
the board starts all the same with the TX stage's 10 k base resistor on it.
A hat built for the Plus2's old pins, with TX on slot 3 (G26), has to be
converted first (docs/WIRING.md).

Both go through a level shifter (see README). The default is a pair of NPN
transistor stages, each of which inverts the signal, so the UART inverts TX
and RX in hardware to cancel it. The non-inverting shifters (TXU0202, or the
two single-gate buffers) need "invert": false in config.json.
"""

from machine import UART

import M5

from nesradar.constants import BAUD

# (TX, RX) by board, read through link_pins().
S3_LINK_PINS = (8, 1)
PLUS2_LINK_PINS = (0, 36)
LINK_UART_ID = 1
POWER_OFF_HOLD_MS = 2000


def init():
    """Start M5Unified. UIFlow's own boot does this too; calling it again is safe."""
    M5.begin()


def link_pins():
    """The (TX, RX) pins the hat reaches on this board; refuse any other board."""
    board_id = M5.getBoard()
    if board_id == M5.BOARD.M5StickS3:
        return S3_LINK_PINS
    if board_id == M5.BOARD.M5StickCPlus2:
        return PLUS2_LINK_PINS
    raise ValueError("NES Radar needs an M5StickS3 or an M5StickC Plus2")


def open_link_uart(invert=True):
    # 9600 8N1, no flow control. At the NES the line idles HIGH (UART mark),
    # as SIGNALING.md requires: with an inverting shifter TX idles LOW, which
    # leaves the transistor off and its pull-up holding D0 high. A generous RX
    # buffer carries reverse-channel bytes across an HTTPS fetch.
    tx, rx = link_pins()
    return UART(
        LINK_UART_ID,
        baudrate=BAUD,
        bits=8,
        parity=None,
        stop=1,
        tx=tx,
        rx=rx,
        rxbuf=1024,
        txbuf=256,
        timeout=0,
        invert=(UART.INV_TX | UART.INV_RX) if invert else 0,
    )


class Buttons:
    """Front button A and side button B, through M5Unified's debounced state."""

    def poll(self):
        """Call often. Returns (A was pressed, B was clicked, B held long enough to power off).

        A click is a release before M5Unified's hold threshold, so the press
        that starts a power-off hold never also toggles the backlight.
        """
        M5.update()
        return (M5.BtnA.wasPressed(), M5.BtnB.wasClicked(),
                M5.BtnB.pressedFor(POWER_OFF_HOLD_MS))


def battery_percent():
    return M5.Power.getBatteryLevel()


def power_off():
    """On battery this turns the Stick off; on USB power it stays on."""
    M5.Power.powerOff()
