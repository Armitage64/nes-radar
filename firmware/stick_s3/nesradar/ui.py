"""Status screen on UIFlow's M5.Lcd. Redraws changed rows only, at most twice a second.

The StickS3's panel is 135x240; rotation 1 makes it 240x135 landscape. Rows are
repainted individually (background fill, then text) so a refresh never
blanks the whole screen, and only from idle waits, never mid-packet.
"""

import M5

from nesradar import clock

BLACK = 0x000000
GREEN = 0x00FF40
AMBER = 0xFFB000
RED = 0xFF3030
GREY = 0x8C8C8C
WHITE = 0xFFFFFF

REDRAW_MS = 500
BRIGHTNESS = 96
WIDTH = 240
ROW_TOP = 22
ROW_HEIGHT = 16
VALUE_X = 58
MAX_VALUE_CHARS = 26
MAX_ERROR_CHARS = 34

ROWS = ("wifi", "state", "airport", "traffic", "scene", "link", "error")
LABELS = {
    "wifi": "WIFI",
    "state": "STATE",
    "airport": "ICAO",
    "traffic": "ADSB",
    "scene": "SCENE",
    "link": "LINK",
    "error": "",
}


class StatusScreen:
    def __init__(self, version):
        self.lcd = M5.Lcd
        self.version = version
        self.fields = {name: "" for name in ROWS}
        self.fields.update(wifi="starting", state="BOOT", airport="----")
        self.battery = ""
        self.backlight = True
        self._dirty = set(ROWS)
        self._header_dirty = True
        self._last_draw = None
        self.lcd.setRotation(1)
        self.lcd.setBrightness(BRIGHTNESS)
        self.lcd.fillScreen(BLACK)

    def set(self, **fields):
        for key, value in fields.items():
            value = str(value)
            if key == "battery":
                if value != self.battery:
                    self.battery = value
                    self._header_dirty = True
            elif self.fields.get(key) != value:
                self.fields[key] = value
                self._dirty.add(key)

    def toggle_backlight(self):
        self.backlight = not self.backlight
        self.lcd.setBrightness(BRIGHTNESS if self.backlight else 0)

    def off(self):
        self.lcd.setBrightness(0)

    def refresh(self, force=False, now=False):
        """Draw changed rows. force redraws everything; now skips the rate limit."""
        ticks = clock.ticks_ms()
        if force:
            self._dirty = set(ROWS)
            self._header_dirty = True
        elif not self._dirty and not self._header_dirty:
            return
        elif (not now and self._last_draw is not None
              and clock.ticks_diff(ticks, self._last_draw) < REDRAW_MS):
            return
        self._last_draw = ticks
        self.lcd.startWrite()
        try:
            if self._header_dirty:
                self._draw_header()
            for index, name in enumerate(ROWS):
                if name in self._dirty:
                    self._draw_row(index, name)
        finally:
            self.lcd.endWrite()
        self._dirty = set()
        self._header_dirty = False

    def _draw_header(self):
        lcd = self.lcd
        lcd.fillRect(0, 0, WIDTH, ROW_TOP - 2, BLACK)
        lcd.setFont(lcd.FONTS.Montserrat14)
        lcd.setTextColor(GREEN, BLACK)
        lcd.drawString("NES RADAR", 4, 2)
        lcd.setFont(lcd.FONTS.Montserrat12)
        lcd.setTextColor(GREY, BLACK)
        lcd.drawString("v" + self.version, 96, 4)
        if self.battery:
            lcd.drawString(self.battery, WIDTH - lcd.textWidth(self.battery) - 4, 4)
        lcd.drawLine(0, ROW_TOP - 3, WIDTH - 1, ROW_TOP - 3, GREEN)

    def _value_color(self, name, value):
        if name == "error":
            return RED
        if name == "state":
            if value.startswith("ERROR"):
                return RED
            return GREEN if value == "STREAMING" else AMBER
        return WHITE

    def _draw_row(self, index, name):
        lcd = self.lcd
        y = ROW_TOP + index * ROW_HEIGHT
        lcd.fillRect(0, y, WIDTH, ROW_HEIGHT, BLACK)
        lcd.setFont(lcd.FONTS.Montserrat12)
        value = self.fields[name]
        if name == "error":
            lcd.setTextColor(RED, BLACK)
            lcd.drawString(value[:MAX_ERROR_CHARS], 4, y + 1)
            return
        lcd.setTextColor(GREY, BLACK)
        lcd.drawString(LABELS[name], 4, y + 1)
        lcd.setTextColor(self._value_color(name, value), BLACK)
        lcd.drawString(value[:MAX_VALUE_CHARS], VALUE_X, y + 1)
