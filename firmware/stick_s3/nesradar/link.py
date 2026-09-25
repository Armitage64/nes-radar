"""The controller-port link: paced transmit and reverse-channel waits.

Transmit ports write_packet, write_oam_heartbeat and wait_with_oam_heartbeats
from server/src/nes_radar_server.py. The UART clocks the bits; this code only
holds the gaps SIGNALING.md specifies, and every one of them is a minimum, so
a late wake-up (garbage collection, a display refresh) only makes the link
quieter, never faster.

Receive replaces the desktop's LocationRequestMonitor thread. The UART's own
RX buffer holds bytes while the main loop is busy (writing a packet, or an
HTTPS fetch), and every wait drains it through ReverseDecoder, so nothing the
ROM sends is lost, only noticed a little later.

The uart object needs write(), any(), read(), and flush() (MicroPython 1.20+
waits in flush() until the TX FIFO is empty, which is what pyserial's
flush() promises on the desktop).
"""

from nesradar import clock
from nesradar.constants import (
    BYTE_GUARD_MS,
    CHUNK_BYTES,
    CHUNK_GAP_MS,
    OAM_HEARTBEAT,
    OAM_HEARTBEAT_GAP_MS,
)
from nesradar.reverse import ACTIVITY, PAUSE, ReverseDecoder

POLL_MS = 2


class LocationChangeRequested(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class LocationRequestStarted(Exception):
    """A request preamble began; pause the old stream before decoding completes."""


class NavigationPauseRequested(Exception):
    """Select requested exclusive controller ownership for the ICAO editor."""


class Link:
    def __init__(self, uart, *, byte_guard_ms=BYTE_GUARD_MS, chunk_bytes=CHUNK_BYTES,
                 chunk_gap_ms=CHUNK_GAP_MS, idle=None, sleep_ms=None):
        self.uart = uart
        self.byte_guard_ms = byte_guard_ms
        self.chunk_bytes = chunk_bytes
        self.chunk_gap_ms = chunk_gap_ms
        self.idle = idle
        self.sleep_ms = sleep_ms or clock.sleep_ms
        self.decoder = ReverseDecoder()
        self.events = []
        self.bytes_sent = 0
        self.requests_seen = 0

    # -- transmit ---------------------------------------------------------

    def _send(self, data):
        self.uart.write(data)
        self.uart.flush()
        self.bytes_sent += len(data)

    def write_packet(self, packet):
        """One byte at a time; a chunk gap after every 8th byte except the last."""
        last = len(packet)
        for index in range(1, last + 1):
            self._send(packet[index - 1:index])
            if self.chunk_bytes and index % self.chunk_bytes == 0 and index != last:
                self.sleep_ms(self.chunk_gap_ms)
            else:
                self.sleep_ms(self.byte_guard_ms)

    def write_oam_heartbeat(self):
        self._send(OAM_HEARTBEAT)
        self.sleep_ms(OAM_HEARTBEAT_GAP_MS)

    # -- receive ----------------------------------------------------------

    def pump(self):
        waiting = self.uart.any()
        chunk = self.uart.read(waiting) if waiting else b""
        for event in self.decoder.service(chunk or b"", clock.ticks_ms(), clock.ticks_diff):
            if event != ACTIVITY:
                self.requests_seen += 1
            self.events.append(event)

    def wait(self, timeout_ms=None, include_activity=False, include_pause=False):
        """Mirror LocationRequestMonitor.wait: return an ICAO code or None on timeout.

        Activity raises LocationRequestStarted and a pause raises
        NavigationPauseRequested when asked for; otherwise they are consumed.
        """
        started = clock.ticks_ms()
        while True:
            self.pump()
            while self.events:
                event = self.events.pop(0)
                if event == ACTIVITY:
                    if include_activity:
                        raise LocationRequestStarted()
                    continue
                if event == PAUSE:
                    if include_pause:
                        raise NavigationPauseRequested()
                    continue
                return event
            if timeout_ms is not None and clock.ticks_diff(clock.ticks_ms(), started) >= timeout_ms:
                return None
            if self.idle is not None:
                self.idle()
            self.sleep_ms(POLL_MS)

    def check_for_location_change(self, timeout_ms=0):
        """wait_for_location_change() from the desktop server."""
        code = self.wait(timeout_ms, include_activity=True, include_pause=True)
        if code is not None:
            raise LocationChangeRequested(code)

    def wait_until(self, deadline_ms):
        remaining = clock.ticks_diff(deadline_ms, clock.ticks_ms())
        if remaining > 0:
            self.check_for_location_change(remaining)

    def wait_with_oam_heartbeats(self, scene_deadline_ms, heartbeat_start_ms):
        """Idle until the next scene, sending $5A every 25 ms once the window is over."""
        if clock.ticks_diff(heartbeat_start_ms, scene_deadline_ms) < 0:
            self.wait_until(heartbeat_start_ms)
        else:
            self.wait_until(scene_deadline_ms)
        while clock.ticks_diff(scene_deadline_ms, clock.ticks_ms()) > OAM_HEARTBEAT_GAP_MS:
            self.check_for_location_change(0)
            if self.idle is not None:
                self.idle()
            self.write_oam_heartbeat()
        self.wait_until(scene_deadline_ms)
