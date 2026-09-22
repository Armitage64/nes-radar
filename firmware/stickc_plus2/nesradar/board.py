"""M5StickC Plus2 pins and power (MicroPython only).

Pin map from https://docs.m5stack.com/en/core/M5StickC%20PLUS2:
  HOLD G4 (must be driven high or the Stick powers off on battery)
  Button A G37, B G39, C G35 (power); battery sense G38 (1:2 divider)
  LCD ST7789V2: MOSI G15, SCLK G13, DC G14, RST G12, CS G5, backlight G27
  Top header: GND, 5V OUT, G26, G36/G25, G0, BAT, 3V3, 5V IN.

The link uses the header, where the protoboard hat plugs in:
  G26 = TX. An ordinary input/output pin.
  G36 = RX. Input-only, which suits receiving. G36 shares its header pad with
        G25, so G25 must stay an input; nothing here configures it.
Both go through a level shifter (see README). The default is a pair of NPN
transistor stages, each of which inverts the signal, so the UART inverts TX
and RX in hardware to cancel it. The non-inverting shifters (TXU0202, or the
two single-gate buffers) need "invert": false in config.json.
  G0 is not used. It is a boot-mode strapping pin: held low at power-up
  (for example by the NES resting OUT0 low), the ESP32 would start
  in download mode instead of running NES Radar.
"""

from machine import ADC, Pin, UART

from nesradar.constants import BAUD

HOLD_PIN = 4
BUTTON_A_PIN = 37
BUTTON_B_PIN = 39
BATTERY_PIN = 38
LINK_TX_PIN = 26
LINK_RX_PIN = 36
LINK_UART_ID = 1

_hold = None


def hold_power():
    """Latch the power switch. Call first thing at boot."""
    global _hold
    _hold = Pin(HOLD_PIN, Pin.OUT, value=1)


def power_off():
    """Release the latch. On battery this turns the Stick off; on USB it continues."""
    if _hold is not None:
        _hold.value(0)


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
    """Edge-detected, polled buttons (active low)."""

    def __init__(self):
        self.a = Pin(BUTTON_A_PIN, Pin.IN)
        self.b = Pin(BUTTON_B_PIN, Pin.IN)
        self._last_a = 1
        self._last_b = 1

    def pressed(self):
        """Return 'A' and/or 'B' for each button newly pressed since the last call."""
        events = []
        a, b = self.a.value(), self.b.value()
        if self._last_a and not a:
            events.append("A")
        if self._last_b and not b:
            events.append("B")
        self._last_a, self._last_b = a, b
        return events

    def b_held(self):
        return not self.b.value()


class Battery:
    def __init__(self):
        self.adc = ADC(Pin(BATTERY_PIN))
        self.adc.atten(ADC.ATTN_11DB)

    def volts(self):
        return self.adc.read_uv() * 2 / 1_000_000

    def percent(self):
        volts = self.volts()
        return max(0, min(100, int((volts - 3.3) / (4.15 - 3.3) * 100)))
