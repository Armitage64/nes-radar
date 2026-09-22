"""Status screen. Redraws at most twice a second, and only from idle waits."""

from nesradar import clock
from nesradar.st7789 import HEIGHT, WIDTH, Display, color

BLACK = color(0, 0, 0)
GREEN = color(0, 255, 64)
AMBER = color(255, 176, 0)
RED = color(255, 48, 48)
GREY = color(140, 140, 140)
WHITE = color(255, 255, 255)

REDRAW_MS = 500


class StatusScreen:
    def __init__(self, version):
        self.display = Display()
        self.version = version
        self.fields = {
            "wifi": "starting",
            "state": "BOOT",
            "airport": "----",
            "traffic": "",
            "scene": "",
            "link": "",
            "error": "",
            "battery": "",
        }
        self.backlight = True
        self._dirty = True
        self._last_draw = None

    def set(self, **fields):
        for key, value in fields.items():
            if self.fields.get(key) != value:
                self.fields[key] = value
                self._dirty = True

    def toggle_backlight(self):
        self.backlight = not self.backlight
        self.display.set_backlight(self.backlight)

    def refresh(self, force=False):
        now = clock.ticks_ms()
        if not force:
            if not self._dirty:
                return
            if self._last_draw is not None and clock.ticks_diff(now, self._last_draw) < REDRAW_MS:
                return
        self._last_draw = now
        self._dirty = False
        self._draw()

    def _draw(self):
        frame = self.display.frame
        fields = self.fields
        frame.fill(BLACK)
        frame.text("NES RADAR", 4, 4, GREEN)
        frame.text(fields["battery"], WIDTH - 8 * len(fields["battery"]) - 4, 4, GREY)
        frame.hline(0, 15, WIDTH, GREEN)
        state = fields["state"]
        state_color = RED if state.startswith("ERROR") else AMBER if state != "STREAMING" else GREEN
        rows = (
            ("WIFI", fields["wifi"], WHITE),
            ("STATE", state, state_color),
            ("ICAO", fields["airport"], WHITE),
            ("ADSB", fields["traffic"], WHITE),
            ("SCENE", fields["scene"], WHITE),
            ("LINK", fields["link"], WHITE),
        )
        y = 22
        for label, value, value_color in rows:
            frame.text(label, 4, y, GREY)
            frame.text(str(value)[:23], 56, y, value_color)
            y += 13
        error = fields["error"]
        if error:
            frame.text(error[:29], 4, y + 2, RED)
            if len(error) > 29:
                frame.text(error[29:58], 4, y + 12, RED)
        frame.text("A:light  hold B:off  v" + self.version, 4, HEIGHT - 10, GREY)
        self.display.show()
