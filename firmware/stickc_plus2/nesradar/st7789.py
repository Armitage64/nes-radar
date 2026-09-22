"""Minimal ST7789V2 driver for the Plus2's 135x240 panel, landscape.

Drawing happens in a MicroPython framebuf (240x135 RGB565, 64,800 bytes) and
show() pushes the whole frame in one SPI write. The panel is big-endian
RGB565 and framebuf stores little-endian, so color() pre-swaps the bytes.
Offsets follow the panel's 240x320 RAM window as M5Stack configures it.
"""

import framebuf
from machine import SPI, Pin

from nesradar import clock

WIDTH = 240
HEIGHT = 135
X_OFFSET = 40
Y_OFFSET = 53
MADCTL_LANDSCAPE = 0x60  # MV | MX, RGB order


def color(red, green, blue):
    value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
    return ((value & 0xFF) << 8) | (value >> 8)


class Display:
    def __init__(self, sck=13, mosi=15, dc=14, rst=12, cs=5, backlight=27):
        # SPI(1) claims its default MISO, G12, as an input. The panel has no
        # MISO and G12 is its reset line, so the reset Pin is created after
        # the bus, which leaves G12 driven as an output.
        self.spi =SPI(1, baudrate=27_000_000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.backlight = Pin(backlight, Pin.OUT, value=0)
        self.buffer = bytearray(WIDTH * HEIGHT * 2)
        self.frame = framebuf.FrameBuffer(self.buffer, WIDTH, HEIGHT, framebuf.RGB565)
        self._reset()
        self.backlight.value(1)

    def _command(self, command, data=None):
        self.cs.value(0)
        self.dc.value(0)
        self.spi.write(bytes((command,)))
        if data:
            self.dc.value(1)
            self.spi.write(data)
        self.cs.value(1)

    def _reset(self):
        self.rst.value(0)
        clock.sleep_ms(10)
        self.rst.value(1)
        clock.sleep_ms(120)
        self._command(0x01)  # SWRESET
        clock.sleep_ms(150)
        self._command(0x11)  # SLPOUT
        clock.sleep_ms(120)
        self._command(0x3A, b"\x55")  # COLMOD 16-bit
        self._command(0x36, bytes((MADCTL_LANDSCAPE,)))
        self._command(0x21)  # INVON: this panel is inverted
        self._command(0x13)  # NORON
        self._command(0x29)  # DISPON

    def set_backlight(self, on):
        self.backlight.value(1 if on else 0)

    def show(self):
        x0, y0 = X_OFFSET, Y_OFFSET
        x1, y1 = X_OFFSET + WIDTH - 1, Y_OFFSET + HEIGHT - 1
        self._command(0x2A, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._command(0x2B, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self._command(0x2C, self.buffer)
