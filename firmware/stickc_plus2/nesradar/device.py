"""Wire the Stick's hardware to Session (MicroPython only)."""

import gc
import json
import sys

from nesradar import VERSION, board, clock, net
from nesradar.airports import AirportTable
from nesradar.app import Session, StopSession
from nesradar.constants import LEAD_IN_MS
from nesradar.link import Link
from nesradar.ui import StatusScreen

CONFIG_PATH = "/config.json"
AIRPORTS_PATH = "/airports.bin"
POWER_OFF_HOLD_MS = 2000
BATTERY_EVERY_MS = 10000
RETRY_DELAY_MS = 2000


def load_config():
    with open(CONFIG_PATH) as handle:
        config = json.load(handle)
    if not config.get("ssid"):
        raise ValueError("config.json needs an ssid")
    # The same floors parse_args() enforces on the desktop.
    if config.get("byte_guard_ms", 5) < 1:
        raise ValueError("byte_guard_ms must be at least 1")
    if config.get("chunk_gap_ms", 30) < 25:
        raise ValueError("chunk_gap_ms must be at least 25")
    if not isinstance(config.get("invert", True), bool):
        raise ValueError("invert must be true (NPN shifter) or false")
    return config


class Device:
    def __init__(self):
        board.hold_power()
        self.screen = StatusScreen(VERSION)
        self.buttons = board.Buttons()
        self.battery = board.Battery()
        self.uart = None
        self.link = None
        self._b_down_at = None
        self._battery_at = None

    # Called from every idle wait in Link: keep this short.
    def idle(self):
        now = clock.ticks_ms()
        for button in self.buttons.pressed():
            if button == "A":
                self.screen.toggle_backlight()
            elif button == "B":
                self._b_down_at = now
        if self._b_down_at is not None:
            if not self.buttons.b_held():
                self._b_down_at = None
            elif clock.ticks_diff(now, self._b_down_at) >= POWER_OFF_HOLD_MS:
                raise StopSession()
        if self._battery_at is None or clock.ticks_diff(now, self._battery_at) >= BATTERY_EVERY_MS:
            self._battery_at = now
            self.screen.set(battery="%d%%" % self.battery.percent())
        if self.link is not None:
            self.screen.set(link="tx %d B, rx %d req" % (self.link.bytes_sent,
                                                        self.link.requests_seen))
        self.screen.refresh()

    def status(self, **fields):
        self.screen.set(**fields)
        self.screen.refresh()

    def fetch_json(self, latitude, longitude, dist_nm):
        if not net.is_connected():
            self.status(wifi="reconnecting")
            if not net.connect(self.config["ssid"], self.config.get("password", ""),
                               timeout_ms=4000):
                raise OSError("Wi-Fi reconnect failed")
            self.status(wifi=self.config["ssid"][:23])
        try:
            return net.fetch_json(latitude, longitude, dist_nm)
        finally:
            gc.collect()

    def run(self):
        self.screen.refresh(force=True)
        try:
            self.config = load_config()
        except (OSError, ValueError) as error:
            self.status(state="ERROR CONFIG", error=str(error))
            return
        self.status(wifi="joining " + self.config["ssid"][:15])
        if not net.connect(self.config["ssid"], self.config.get("password", ""),
                           on_wait=self.screen.refresh):
            self.status(wifi="FAILED", error="could not join Wi-Fi; will retry on fetch")
        else:
            self.status(wifi=self.config["ssid"][:23])

        airports = AirportTable(AIRPORTS_PATH)
        self.uart = board.open_link_uart(invert=self.config.get("invert", True))
        self.link = Link(
            self.uart,
            byte_guard_ms=self.config.get("byte_guard_ms", 5),
            chunk_gap_ms=self.config.get("chunk_gap_ms", 30),
            idle=self.idle,
        )
        clock.sleep_ms(LEAD_IN_MS)
        fixed_icao = self.config.get("icao") or None
        session = Session(
            self.link,
            airports.resolve,
            self.fetch_json,
            self.status,
            sequence=self.config.get("sequence", 0),
            fixed_icao=fixed_icao.upper() if fixed_icao else None,
        )
        try:
            while True:
                try:
                    session.serve()
                    return
                except StopSession:
                    raise
                except Exception as error:  # keep serving; a reboot would need a ROM reload
                    sys.print_exception(error)
                    self.status(state="ERROR", error="%s: %s" % (type(error).__name__, error))
                    self.link.sleep_ms(RETRY_DELAY_MS)
                    session.fixed_icao = None
        except StopSession:
            self.status(state="POWER OFF", error="")
        finally:
            # Leave the UART running so TX stays at mark (D0 high at the NES);
            # deinit would float G26 and the shifter input.
            self.link.sleep_ms(LEAD_IN_MS)
        self.screen.display.set_backlight(False)
        board.power_off()


def main():
    Device().run()
