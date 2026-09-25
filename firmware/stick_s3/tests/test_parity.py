"""Hold the Stick port byte-for-byte to the desktop server it was ported from.

Run with the server's requirements installed (pyserial, certifi), because the
desktop modules are imported as the reference:

    python -m pytest firmware/stick_s3/tests
"""

import json
import math
from pathlib import Path
import random
import tempfile
import unittest

import nes_radar_server as radar
import nes_uart_request as desktop_reverse
import scene_protocol as desktop
from c64_reference import ultimate_radar_server as C64
from nes_icao_request import LocationRequest, PauseRequest, request_bytes

import build_airports
from nesradar import constants, link, protocol, reverse, traffic
from nesradar.airports import AirportTable

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def stick_target(target):
    return protocol.Target(**vars(target))


def stick_identity(identity):
    return protocol.Identity(**vars(identity))


class ConstantsTests(unittest.TestCase):
    def test_link_timing_matches_desktop(self):
        self.assertEqual(constants.BAUD, radar.BAUD)
        self.assertEqual(constants.BYTE_GUARD_MS / 1000, radar.DEFAULT_BYTE_GUARD_SECONDS)
        self.assertEqual(constants.CHUNK_BYTES, radar.DEFAULT_CHUNK_BYTES)
        self.assertEqual(constants.CHUNK_GAP_MS / 1000, radar.DEFAULT_CHUNK_GAP_SECONDS)
        self.assertEqual(constants.OAM_HEARTBEAT, radar.OAM_HEARTBEAT)
        self.assertEqual(constants.OAM_HEARTBEAT_GAP_MS / 1000, radar.OAM_HEARTBEAT_GAP_SECONDS)
        self.assertEqual(constants.POLL_MS / 1000, radar.DEFAULT_POLL_SECONDS)
        self.assertEqual(constants.SCENE_INTERVAL_MS / 1000, radar.DEFAULT_SCENE_INTERVAL_SECONDS)
        self.assertEqual(constants.DISPLAY_WINDOW_FRAMES, radar.DISPLAY_WINDOW_FRAMES)
        self.assertEqual(constants.DISPLAY_COMMIT_FRAMES, radar.DISPLAY_COMMIT_FRAMES)
        self.assertEqual(constants.NES_FIELD_HZ, radar.NES_FIELD_HZ)
        self.assertEqual(constants.DISPLAY_SCHEDULING_MARGIN_MS / 1000,
                         radar.DISPLAY_SCHEDULING_MARGIN_SECONDS)
        self.assertEqual(constants.IDENTITY_SETTLE_MS / 1000, radar.IDENTITY_SETTLE_SECONDS)
        self.assertEqual(constants.LEAD_IN_MS / 1000, radar.LEAD_IN_SECONDS)
        self.assertEqual(constants.REQUEST_SETTLE_MS / 1000, radar.REQUEST_SETTLE_SECONDS)
        self.assertEqual(constants.RANGE_NM, radar.DEFAULT_RANGE_NM)
        self.assertEqual(constants.LDV_SCOPE_CENTER, radar.LDV_SCOPE_CENTER)
        self.assertEqual(constants.LDV_RADIUS_PIXELS, radar.LDV_RADIUS_PIXELS)
        self.assertEqual(constants.MIN_GROUND_SPEED_KT, C64.MIN_GROUND_SPEED_KT)
        self.assertEqual(constants.USER_AGENT, C64.USER_AGENT)
        self.assertTrue(C64.ADSB_FI_BASE.endswith(constants.ADSB_FI_HOST + constants.ADSB_FI_PATH))

    def test_display_quiet_window_matches_desktop_arithmetic(self):
        desktop_seconds = (
            (radar.DISPLAY_COMMIT_FRAMES + radar.DISPLAY_WINDOW_FRAMES) / radar.NES_FIELD_HZ
            + radar.DISPLAY_SCHEDULING_MARGIN_SECONDS
        )
        self.assertAlmostEqual(constants.DISPLAY_QUIET_MS / 1000, desktop_seconds, delta=0.001)

    def test_rom_display_window_constant(self):
        rom = (radar.SOURCE_ROOT.parents[1] / "nes_radar" / "nes" / "nes_radar_scope_v3.s").read_text()
        self.assertRegex(rom, r"DISPLAY_WINDOW_FRAMES\s*=\s*%d\b" % constants.DISPLAY_WINDOW_FRAMES)


class ProtocolParityTests(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(protocol.crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_fixture_scenes_and_identities(self):
        for frame in range(0, 200, 7):
            for fixture in (desktop.synthetic_targets(frame), desktop.synthetic_approach_targets(frame)):
                for flags in (0, 0x01, 0x06, 0x1F):
                    expected = desktop.encode_scene(frame, fixture, flags)
                    actual = protocol.encode_scene(frame, [stick_target(t) for t in fixture], flags)
                    self.assertEqual(actual, expected)
        expected = desktop.encode_identity(0x33, desktop.BASE_IDENTITIES)
        actual = protocol.encode_identity(0x33, [stick_identity(i) for i in desktop.BASE_IDENTITIES])
        self.assertEqual(actual, expected)
        self.assertEqual(protocol.encode_identity(7, ()), desktop.encode_identity(7, ()))
        self.assertEqual(protocol.encode_scene(300, ()), desktop.encode_scene(300, ()))

    def test_random_targets(self):
        rng = random.Random(1234)
        for _ in range(500):
            count = rng.randint(0, 8)
            slots = rng.sample(range(8), count)
            targets = [
                desktop.Target(
                    slot=slot,
                    x=rng.randint(0, 159),
                    y=rng.randint(0, 159),
                    track=rng.randint(0, 255),
                    altitude_hundreds=rng.randint(0, 65535),
                    speed_knots=rng.randint(0, 255),
                    vertical_rate_hundreds=rng.randint(-99, 99),
                    distance_tenths=rng.randint(0, 99),
                    track_valid=rng.random() < 0.8,
                    altitude_valid=rng.random() < 0.8,
                    speed_valid=rng.random() < 0.8,
                    alert=rng.random() < 0.2,
                    vertical_rate_valid=rng.random() < 0.8,
                    distance_valid=rng.random() < 0.8,
                )
                for slot in slots
            ]
            sequence = rng.randint(0, 255)
            flags = rng.randint(0, 0x1F)
            self.assertEqual(
                protocol.encode_scene(sequence, [stick_target(t) for t in targets], flags),
                desktop.encode_scene(sequence, targets, flags),
            )

    def test_location_results(self):
        for code in ("KSBA", "klax", " egll "):
            for valid in (True, False):
                self.assertEqual(
                    protocol.encode_location_result(9, code, valid),
                    desktop.encode_location_result(9, code, valid),
                )

    def test_clear_packets(self):
        self.assertEqual(protocol.clear_packets(0x42), radar.clear_packets(0x42))

    def test_same_inputs_are_rejected(self):
        bad_targets = (
            dict(slot=8, x=0, y=0, track=0, altitude_hundreds=0, speed_knots=0),
            dict(slot=0, x=160, y=0, track=0, altitude_hundreds=0, speed_knots=0),
            dict(slot=0, x=0, y=0, track=0, altitude_hundreds=0, speed_knots=0,
                 vertical_rate_hundreds=100),
            dict(slot=0, x=0, y=0, track=0, altitude_hundreds=0, speed_knots=0,
                 distance_tenths=100),
        )
        for fields in bad_targets:
            with self.assertRaises(ValueError):
                desktop.Target(**fields).encode()
            with self.assertRaises(ValueError):
                protocol.Target(**fields).encode()
        for fields in (("AB$", "B738"), ("TOOLONGCS", "B738"), ("UAL1", "B7378")):
            with self.assertRaises(ValueError):
                desktop.Identity(0, *fields).encode()
            with self.assertRaises(ValueError):
                protocol.Identity(0, *fields).encode()
        for code in ("KSB", "KSB1", "KSBAX", "ÄSBA"):
            with self.assertRaises(ValueError):
                desktop.encode_location_result(0, code, True)
            with self.assertRaises(ValueError):
                protocol.encode_location_result(0, code, True)
        duplicate = [protocol.Target(0, 1, 1, 0, 0, 0), protocol.Target(0, 2, 2, 0, 0, 0)]
        with self.assertRaises(ValueError):
            protocol.encode_scene(0, duplicate)
        with self.assertRaises(ValueError):
            protocol.encode_scene(0, (), 0x20)


def desktop_event(event):
    if isinstance(event, LocationRequest):
        return event.code
    if isinstance(event, PauseRequest):
        return reverse.PAUSE
    return event


class ReverseParityTests(unittest.TestCase):
    def test_signaling_worked_examples(self):
        self.assertEqual(reverse.decode_frame(bytes.fromhex("4E4B4A464BE7")), "KJFK")
        self.assertEqual(reverse.decode_frame(bytes.fromhex("4E4B534241F0")), "KSBA")
        self.assertEqual(reverse.decode_frame(bytes.fromhex("5000000000F5")), reverse.PAUSE)
        self.assertEqual(reverse.decode_frame(request_bytes("EGLL")), "EGLL")

    def test_scan_matches_desktop_on_random_buffers(self):
        rng = random.Random(99)
        pieces = [request_bytes("KSBA"), request_bytes("KLAX"), bytes.fromhex("5000000000F5"),
                  b"\x00", b"\x00\x00", b"\x4E", b"\x50", b"\xFF", b"KSBA"]
        for _ in range(3000):
            buffer = b"".join(rng.choice(pieces) for _ in range(rng.randint(0, 6)))
            if rng.random() < 0.3 and buffer:
                cut = rng.randrange(len(buffer))
                buffer = buffer[cut:]
            expected_event, expected_consumed = desktop_reverse.scan_for_frame(buffer, False)
            actual_event, actual_consumed = reverse.scan_for_frame(buffer)
            self.assertEqual(actual_consumed, expected_consumed, buffer.hex())
            self.assertEqual(actual_event, desktop_event(expected_event), buffer.hex())

    def run_desktop(self, timeline):
        """Play (ms, chunk) arrivals through the desktop ReverseUartReader."""
        now = [0.0]
        pending = list(timeline)
        end = (timeline[-1][0] if timeline else 0) + 1000
        events = []

        class Port:
            @property
            def in_waiting(self):
                return len(pending[0][1]) if pending and pending[0][0] <= now[0] * 1000 else 0

            def read(self, count):
                return pending.pop(0)[1]

        def sleep(seconds):
            now[0] += seconds

        reader = desktop_reverse.ReverseUartReader()
        while True:
            try:
                event = reader(
                    Port(),
                    stop_requested=lambda: now[0] * 1000 > end,
                    on_activity=lambda: events.append(reverse.ACTIVITY),
                    monotonic=lambda: now[0],
                    sleep=sleep,
                )
            except desktop_reverse.RequestCancelled:
                return events
            events.append(desktop_event(event))

    def run_stick(self, timeline):
        """The same arrivals through ReverseDecoder, polled every 2 ms like Link.wait."""
        pending = list(timeline)
        end = (timeline[-1][0] if timeline else 0) + 1000
        decoder = reverse.ReverseDecoder()
        events = []
        now = 0
        while now <= end:
            chunk = pending.pop(0)[1] if pending and pending[0][0] <= now else b""
            events.extend(decoder.service(chunk, now))
            now += 2
        return events

    def assert_same_events(self, timeline, expected=None):
        actual = self.run_stick(timeline)
        self.assertEqual(actual, self.run_desktop(timeline))
        if expected is not None:
            self.assertEqual(actual, expected)

    def test_two_bursts_in_one_read_both_decode(self):
        # The first real console capture: one read, the same frame twice.
        capture = bytes.fromhex("004E4B534241F000004E4B534241F000")
        self.assert_same_events([(0, capture)], ["KSBA", "KSBA"])

    def test_activity_precedes_frame_split_across_reads(self):
        frame = request_bytes("KLAX")
        self.assert_same_events([(0, frame[:3]), (20, frame[3:])],
                                [reverse.ACTIVITY, "KLAX"])

    def test_burst_gap_discards_residue(self):
        frame = request_bytes("KLAX")
        self.assert_same_events([(0, frame[:4]), (300, frame[4:]), (320, frame)])
        # Without the gap the stale head would pair with the new tail.
        self.assertEqual(self.run_stick([(0, frame[:4]), (300, frame[4:])]), [reverse.ACTIVITY])

    def test_resync_one_byte_forward(self):
        self.assert_same_events([(0, b"\x4E\x4B" + request_bytes("KSBA"))],
                                [reverse.ACTIVITY, "KSBA"])

    def test_random_timelines_match_desktop(self):
        rng = random.Random(5)
        pieces = [request_bytes("KSBA"), request_bytes("KJFK"), bytes.fromhex("5000000000F5"),
                  b"\x00", b"\x4E", b"\x50", b"\xA5"]
        for _ in range(150):
            stream = b"".join(rng.choice(pieces) for _ in range(rng.randint(1, 5)))
            timeline, at, index = [], 0, 0
            while index < len(stream):
                size = rng.randint(1, 8)
                timeline.append((at, stream[index:index + size]))
                index += size
                at += rng.choice((2, 10, 40, 300))
            self.assert_same_events(timeline)


class TrafficParityTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((FIXTURES / "klax_adsbfi.json").read_text())
        self.scope = C64.Scope(33.942501, -118.407997, radar.DEFAULT_RANGE_NM).validated()
        self.center = (self.scope.latitude, self.scope.longitude)

    def test_extract_matches_desktop_two_pass(self):
        expected = radar.extract_targets_with_details(self.payload, self.scope)
        actual = traffic.extract_targets(self.payload, self.center)
        self.assertGreater(len(expected), 3)
        self.assertEqual(actual, expected)

    def test_assigned_scene_bytes_match(self):
        desktop_allocator = radar.SlotAllocator()
        stick_allocator = traffic.SlotAllocator()
        targets = traffic.extract_targets(self.payload, self.center)
        for trim in (len(targets), 5, 1, 0, 0, len(targets)):
            subset = targets[:trim]
            expected = desktop_allocator.assign(subset)
            actual = stick_allocator.assign(subset)
            self.assertEqual(
                protocol.encode_scene(3, actual.targets, 2),
                desktop.encode_scene(3, expected.targets, 2),
            )
            self.assertEqual(
                protocol.encode_identity(3, actual.identities),
                desktop.encode_identity(3, expected.identities),
            )
            self.assertEqual(actual.identity_changed, expected.identity_changed)

    def test_float32_geometry_stays_within_one_pixel(self):
        # MicroPython on the ESP32 computes in single precision. Model that by
        # rounding every input to float32 and compare against double results.
        import struct

        def f32(value):
            return struct.unpack("f", struct.pack("f", value))[0]

        for item in self.payload["ac"]:
            if "lat" not in item:
                continue
            point = (item["lat"], item["lon"])
            rough = (f32(point[0]), f32(point[1]))
            rough_center = (f32(self.center[0]), f32(self.center[1]))
            distance = traffic.distance_nm(self.center, point)
            self.assertAlmostEqual(traffic.distance_nm(rough_center, rough), distance, delta=0.01)
            radius = min(71, distance * constants.LDV_PIXELS_PER_NM)
            bearing = traffic.bearing_degrees(self.center, point)
            rough_bearing = traffic.bearing_degrees(rough_center, rough)
            delta = abs((bearing - rough_bearing + 180) % 360 - 180)
            self.assertLess(math.radians(delta) * radius, 0.5)

    def test_scene_flags_match(self):
        snapshots = [
            traffic.Snapshot([], 0, 0, False),
            traffic.Snapshot([], 12, 0, False),
            traffic.Snapshot([], 3, 0, True, "timeout"),
            traffic.Snapshot([], 9, None, True, "HTTP 503"),
        ]
        for snapshot in snapshots:
            self.assertEqual(traffic.scene_flags(snapshot), radar.scene_flags(snapshot))

    def test_service_stale_rules(self):
        now = [0]
        responses = [self.payload, OSError("down"), OSError("down")]

        def fetch(latitude, longitude, dist):
            self.assertEqual(dist, 10)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        original = traffic.clock.ticks_ms, traffic.clock.sleep_ms
        traffic.clock.ticks_ms = lambda: now[0]
        traffic.clock.sleep_ms = lambda ms: now.__setitem__(0, now[0] + max(0, ms))
        try:
            service = traffic.TrafficService(*self.center, fetch)
            first = service.refresh()
            self.assertFalse(first.stale)
            self.assertIsNone(first.error)
            now[0] += 10000
            held = service.refresh()
            self.assertFalse(held.stale)
            self.assertEqual(held.error, "down")
            self.assertEqual(held.total, first.total)
            now[0] += 25000
            stale = service.refresh()
            self.assertTrue(stale.stale)
        finally:
            traffic.clock.ticks_ms, traffic.clock.sleep_ms = original

    def test_service_first_failure_is_stale_and_empty(self):
        def fetch(*_args):
            raise OSError("no route")

        snapshot = traffic.TrafficService(*self.center, fetch).refresh()
        self.assertTrue(snapshot.stale)
        self.assertEqual(snapshot.total, 0)
        self.assertEqual(traffic.scene_flags(snapshot), 0x05)


class AirportParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "airports.bin"
        cls.airports = build_airports.load_airports()
        cls.path.write_bytes(build_airports.pack(cls.airports))
        cls.table = AirportTable(str(cls.path))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tearDown(self):
        radar.AIRPORTS = None

    def test_table_covers_the_desktop_database(self):
        self.assertEqual(self.table.count, len(self.airports))
        self.assertGreater(self.table.count, 10000)

    def test_lookups_match_desktop_resolve(self):
        rng = random.Random(7)
        codes = ["KSBA", "EGLL", "KCMA", "KLAX", "KJFK"] + rng.sample(sorted(self.airports), 300)
        for code in codes:
            expected = radar.resolve_airport(code)
            actual = self.table.resolve(code.lower())
            self.assertAlmostEqual(actual[0], expected[0], delta=1e-4, msg=code)
            self.assertAlmostEqual(actual[1], expected[1], delta=1e-4, msg=code)

    def test_unknown_and_malformed_codes(self):
        for code in ("ZZZZ", "AAAA", "KSB", "K5BA"):
            with self.assertRaises(ValueError):
                self.table.resolve(code)


class FakePort:
    def __init__(self, log):
        self.log = log

    def write(self, data):
        self.log.append(("write", bytes(data)))

    def flush(self):
        pass


class WritePacketParityTests(unittest.TestCase):
    def test_bytes_and_gaps_match_desktop(self):
        packets = [
            desktop.encode_scene(1, desktop.BASE_TARGETS),
            desktop.encode_identity(2, desktop.BASE_IDENTITIES),
            desktop.encode_location_result(0, "KSBA", True),
            desktop.encode_scene(1, ()),
        ]
        for packet in packets:
            expected = []
            radar.write_packet(FakePort(expected), packet, radar.DEFAULT_BYTE_GUARD_SECONDS,
                               lambda seconds: expected.append(("sleep", round(seconds * 1000))))
            actual = []
            stick = link.Link(FakePort(actual),
                              sleep_ms=lambda ms: actual.append(("sleep", ms)))
            stick.write_packet(packet)
            self.assertEqual(actual, expected)

    def test_heartbeat_matches_desktop(self):
        expected = []
        radar.write_oam_heartbeat(FakePort(expected),
                                  lambda seconds: expected.append(("sleep", round(seconds * 1000))))
        actual = []
        link.Link(FakePort(actual), sleep_ms=lambda ms: actual.append(("sleep", ms))).write_oam_heartbeat()
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
