"""Wire the Stick's hardware to Session (UIFlow 2.0 firmware only).

UIFlow keeps the user's files under /flash and the Wi-Fi network set up in
M5Burner (or UIFlow's launcher) in NVS ("uiflow": ssid0/pswd0). NES Radar
joins only that network. Wi-Fi credentials are deliberately not read from
config.json, so they never sit in a plain file on the Stick or next to the
source.
"""

import gc
import json
import sys

import esp32

from nesradar import VERSION, board, clock, net
from nesradar.airports import AirportTable
from nesradar.app import Session, StopSession
from nesradar.constants import LEAD_IN_MS
from nesradar.link import Link
from nesradar.ui import StatusScreen

FS_ROOT = "/flash"
CONFIG_PATH = FS_ROOT + "/config.json"
AIRPORTS_PATH = FS_ROOT + "/airports.bin"
BATTERY_EVERY_MS = 10000
RETRY_DELAY_MS = 2000


def uiflow_wifi():
    """(ssid, password) saved by M5Burner or UIFlow's setup."""
    nvs = esp32.NVS("uiflow")
    try:
        ssid = nvs.get_str("ssid0")
    except OSError:
        ssid = ""
    if not ssid:
        raise ValueError("No Wi-Fi saved. Use M5Burner.")
    try:
        password = nvs.get_str("pswd0")
    except OSError:
        password = ""
    return ssid, password


def load_config():
    try:
        with open(CONFIG_PATH) as handle:
            config = json.load(handle)
    except OSError:
        config = {}  # config.json is optional
    config["ssid"], config["password"] = uiflow_wifi()
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
        board.init()
        self.screen = StatusScreen(VERSION)
        self.buttons = board.Buttons()
        self.uart = None
        self.link = None
        self.config = {}
        self._battery_at = None

    # Called from every idle wait in Link: keep this short.
    def idle(self):
        now = clock.ticks_ms()
        a_pressed, b_held = self.buttons.poll()
        if a_pressed:
            self.screen.toggle_backlight()
        if b_held:
            raise StopSession()
        if self._battery_at is None or clock.ticks_diff(now, self._battery_at) >= BATTERY_EVERY_MS:
            self._battery_at = now
            self.screen.set(battery="%d%%" % board.battery_percent())
        if self.link is not None:
            self.screen.set(link="tx %d B, rx %d req" % (self.link.bytes_sent,
                                                        self.link.requests_seen))
        self.screen.refresh()

    def status(self, **fields):
        # State changes draw at once; only idle() refreshes are rate-limited.
        self.screen.set(**fields)
        self.screen.refresh(now=True)

    def fetch_json(self, latitude, longitude, dist_nm):
        if not net.is_connected():
            self.status(wifi="reconnecting")
            if not net.connect(self.config["ssid"], self.config.get("password", ""),
                               timeout_ms=4000):
                raise OSError("Wi-Fi reconnect failed")
            self.status(wifi=self.config["ssid"])
        try:
            return net.fetch_json(latitude, longitude, dist_nm)
        finally:
            gc.collect()

    def run(self):
        self.screen.refresh(force=True)
        try:
            board.check_board()
            self.config = load_config()
        except (OSError, ValueError) as error:
            self.status(state="ERROR CONFIG", error=str(error))
            return
        self.status(wifi="joining " + self.config["ssid"])
        if not net.connect(self.config["ssid"], self.config.get("password", ""),
                           on_wait=self.screen.refresh):
            self.status(wifi="FAILED", error="could not join Wi-Fi; will retry on fetch")
        else:
            self.status(wifi=self.config["ssid"])

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
            # deinit would float G8 and the shifter input.
            self.link.sleep_ms(LEAD_IN_MS)
        self.screen.off()
        board.power_off()


def main():
    Device().run()
