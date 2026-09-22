"""The server lifecycle: request, validate, stream, pause, repeat.

Ports ConnectionLifecycle._serve_open_port, _validate_and_reply,
_acknowledge_pause_and_wait and stream_scope from nes_radar_server.py. What
differs on the Stick:

- There is no adapter discovery. The UART is always there.
- The adsb.fi fetch happens right after a scene is sent, at the start of
  the ROM's 6-second display window, while the host would otherwise be
  silent. The desktop fetches just before the next scene instead. Moving it
  keeps a slow TLS handshake from delaying a packet or the heartbeats. The
  data is about as fresh, because --poll (8 s) is shorter than the scene
  interval (9.5 s), so either way every scene follows a new fetch.

Session takes all its I/O as arguments so tests/test_app.py can run it on
CPython against a scripted fake UART.
"""

from nesradar import clock
from nesradar.constants import (
    DISPLAY_QUIET_MS,
    IDENTITY_SETTLE_MS,
    LEAD_IN_MS,
    POLL_MS,
    REQUEST_SETTLE_MS,
    SCENE_INTERVAL_MS,
)
from nesradar.link import (
    LocationChangeRequested,
    LocationRequestStarted,
    NavigationPauseRequested,
)
from nesradar.protocol import (
    encode_identity,
    encode_location_result,
    encode_scene,
)
from nesradar.traffic import SlotAllocator, TrafficService, scene_flags


class StopSession(Exception):
    """Raised by a status hook to end serve() (power-off, tests)."""


class Session:
    def __init__(self, link, resolve_airport, fetch_json, status=None, *,
                 sequence=0, fixed_icao=None, max_frames=0,
                 poll_ms=POLL_MS, scene_interval_ms=SCENE_INTERVAL_MS):
        self.link = link
        self.resolve_airport = resolve_airport
        self.fetch_json = fetch_json
        self.status = status or (lambda **fields: None)
        self.sequence = sequence
        self.fixed_icao = fixed_icao
        self.max_frames = max_frames
        self.poll_ms = poll_ms
        self.scene_interval_ms = scene_interval_ms
        self.last_airport = None

    # -- request handling -------------------------------------------------

    def _request_code(self, include_pause=False):
        self.status(state="WAITING", airport=self.last_airport or "----")
        code = self.link.wait(None, include_pause=include_pause)
        self.status(state="VALIDATING", airport=code)
        return code

    def _validate_and_reply(self, code):
        while True:
            self.link.sleep_ms(REQUEST_SETTLE_MS)
            try:
                self.resolve_airport(code)
            except ValueError:
                self.link.write_packet(encode_location_result(self.sequence, code, False))
                self.status(state="INVALID", airport=code, error="unknown ICAO " + code)
                code = self._request_code()
                continue
            self.link.write_packet(encode_location_result(self.sequence, code, True))
            self.status(error="")
            self.last_airport = code
            return code

    def _acknowledge_pause_and_wait(self):
        self.status(state="PAUSED")
        self.link.sleep_ms(LEAD_IN_MS)
        # A legal zero-record identity packet is the pause acknowledgement.
        self.link.write_packet(encode_identity(self.sequence, ()))
        code = self.link.wait(None)
        self.status(state="VALIDATING", airport=code)
        return self._validate_and_reply(code)

    def serve(self):
        selected = None
        if self.fixed_icao is None:
            try:
                code = self._request_code(include_pause=True)
            except NavigationPauseRequested:
                selected = self._acknowledge_pause_and_wait()
            else:
                selected = self._validate_and_reply(code)
        else:
            selected = self.fixed_icao
            self.last_airport = selected
        while True:
            try:
                return self.stream(selected)
            except LocationChangeRequested as change:
                self.status(state="VALIDATING", airport=change.code)
                selected = self._validate_and_reply(change.code)
            except NavigationPauseRequested:
                selected = self._acknowledge_pause_and_wait()
            except LocationRequestStarted:
                self.status(state="REQUEST")
                try:
                    code = self.link.wait(None, include_pause=True)
                except NavigationPauseRequested:
                    selected = self._acknowledge_pause_and_wait()
                    continue
                self.status(state="VALIDATING", airport=code)
                selected = self._validate_and_reply(code)

    # -- streaming --------------------------------------------------------

    def _refresh(self, service, allocator):
        self.status(state="STREAMING", traffic="fetching...")
        snapshot = service.refresh()
        assigned = allocator.assign(snapshot.targets)
        if snapshot.error:
            traffic = "%d near, %s" % (snapshot.total, "STALE" if snapshot.stale else "held")
            self.status(traffic=traffic, error=snapshot.error)
        else:
            self.status(traffic="%d near, %d shown" % (snapshot.total, len(assigned.targets)),
                        error="")
        return snapshot, assigned

    def stream(self, code):
        latitude, longitude = self.resolve_airport(code)
        service = TrafficService(latitude, longitude, self.fetch_json)
        allocator = SlotAllocator()
        self.status(state="STREAMING", airport=code)
        snapshot, assigned = self._refresh(service, allocator)
        refresh_deadline = clock.ticks_add(clock.ticks_ms(), self.poll_ms)
        identity_pending = assigned.identity_changed
        frame = 0
        scene_deadline = clock.ticks_ms()
        heartbeat_start = scene_deadline
        while self.max_frames == 0 or frame < self.max_frames:
            if frame:
                self.link.wait_with_oam_heartbeats(scene_deadline, heartbeat_start)
            self.link.check_for_location_change(0)

            if identity_pending:
                self.link.write_packet(encode_identity(self.sequence, assigned.identities))
                self.link.sleep_ms(IDENTITY_SETTLE_MS)
                identity_pending = False
                self.link.check_for_location_change(0)

            scene_start = clock.ticks_ms()
            self.link.write_packet(encode_scene(self.sequence, assigned.targets,
                                                scene_flags(snapshot)))
            heartbeat_start = clock.ticks_add(clock.ticks_ms(), DISPLAY_QUIET_MS)
            self.status(scene="#%d seq $%02X %d tgt" % (frame + 1, self.sequence,
                                                       len(assigned.targets)))
            self.sequence = (self.sequence + 1) & 0xFF
            frame += 1
            scene_deadline = clock.ticks_add(scene_start, self.scene_interval_ms)

            # Fetch now, inside the ROM's display window, if the next scene
            # would otherwise be built from data older than the poll interval.
            if clock.ticks_diff(scene_deadline, refresh_deadline) >= 0:
                snapshot, assigned = self._refresh(service, allocator)
                refresh_deadline = clock.ticks_add(clock.ticks_ms(), self.poll_ms)
                identity_pending = identity_pending or assigned.identity_changed
        return 0
