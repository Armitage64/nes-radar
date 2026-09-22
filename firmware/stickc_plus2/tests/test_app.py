"""Drive Session end to end on a virtual clock against a scripted NES.

Everything the Stick transmits is captured with its timestamp, split into
packets, and decoded with the desktop's own decoders from scene_protocol.py,
so these tests check the transaction sequence of SIGNALING.md and the wire
timing, not just the port's self-consistency.
"""

import json
from pathlib import Path
import unittest

import scene_protocol as desktop
from nes_icao_request import request_bytes

from nesradar import app, clock, constants
from nesradar.link import Link
from sim import ScriptedNes, VirtualClock, run_session, standard_scenario

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PAUSE_FRAME = bytes.fromhex("5000000000F5")
AIRPORTS = {"KSBA": (34.4262, -119.8404), "KLAX": (33.942501, -118.407997)}


def split_packets(tx):
    """[(start_ms, kind, payload_bytes, [byte times])] with heartbeats as their own kind."""
    packets = []
    index = 0
    while index < len(tx):
        at, byte = tx[index]
        if byte == 0x5A:
            packets.append((at, "heartbeat", bytes((byte,)), [at]))
            index += 1
            continue
        assert byte == desktop.MARKER, "stray byte %02X at %d ms" % (byte, at)
        length = tx[index + 6][1]
        end = index + 9 + length
        chunk = tx[index:end]
        data = bytes(value for _t, value in chunk)
        kind = {1: "scene", 2: "identity", 3: "location"}[data[1]]
        packets.append((at, kind, data, [t for t, _v in chunk]))
        index = end
    return packets


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.virtual = VirtualClock()
        self.saved = (clock.ticks_ms, clock.sleep_ms)
        clock.ticks_ms = self.virtual.ticks_ms
        clock.sleep_ms = self.virtual.sleep_ms
        self.klax = json.loads((FIXTURES / "klax_adsbfi.json").read_text())
        self.fetches = []

    def tearDown(self):
        clock.ticks_ms, clock.sleep_ms = self.saved

    def fetch(self, latitude, longitude, dist):
        self.fetches.append((self.virtual.now, round(latitude, 3)))
        return self.klax if round(latitude, 3) == 33.943 else {"ac": []}

    def resolve(self, code):
        try:
            return AIRPORTS[code]
        except KeyError:
            raise ValueError("unknown")

    def run_session(self, script, max_frames):
        nes = ScriptedNes(self.virtual, script)
        session = app.Session(Link(nes), self.resolve, self.fetch, max_frames=max_frames)
        session.serve()
        return split_packets(nes.tx)

    def test_request_stream_pause_and_change_airport(self):
        script = [
            (100, b"\x00" + request_bytes("KSBA") + b"\x00"),
            (15000, PAUSE_FRAME),
            (18000, request_bytes("KLAX")),
        ]
        packets = self.run_session(script, max_frames=3)
        kinds = [kind for _at, kind, _data, _times in packets if kind != "heartbeat"]
        self.assertEqual(kinds, [
            "location",                      # KSBA accepted
            "identity", "scene", "scene",    # stream KSBA (empty airspace)
            "identity",                      # pause acknowledgement
            "location",                      # KLAX accepted
            "identity", "scene", "scene", "scene",
        ])
        decoded = [(at, kind, data) for at, kind, data, _t in packets if kind != "heartbeat"]

        at, _kind, data = decoded[0]
        result = desktop.decode_location_result(data)
        self.assertEqual((result.code, result.valid), ("KSBA", True))
        self.assertGreaterEqual(at, 100 + constants.REQUEST_SETTLE_MS)

        ack = desktop.decode_identity(decoded[4][2])
        self.assertEqual(ack.identities, ())
        self.assertGreater(decoded[4][0], 15000)

        result = desktop.decode_location_result(decoded[5][2])
        self.assertEqual((result.code, result.valid), ("KLAX", True))

        identities = desktop.decode_identity(decoded[6][2])
        self.assertTrue(any(identity.callsign for identity in identities.identities))
        klax_scenes = [desktop.decode_scene(data) for _at, kind, data in decoded[7:]]
        self.assertTrue(all(scene.targets for scene in klax_scenes))
        self.assertEqual([scene.sequence for scene in klax_scenes], [2, 3, 4])

    def test_scene_interval_heartbeats_and_byte_gaps(self):
        packets = self.run_session([(0, request_bytes("KLAX"))], max_frames=4)
        scenes = [(at, times) for at, kind, _data, times in packets if kind == "scene"]
        starts = [at for at, _times in scenes]
        for earlier, later in zip(starts, starts[1:]):
            self.assertGreaterEqual(later - earlier, constants.SCENE_INTERVAL_MS)
            self.assertLess(later - earlier, constants.SCENE_INTERVAL_MS + 60)

        for at, kind, data, times in packets:
            if kind == "heartbeat":
                continue
            for index in range(1, len(times)):
                gap = times[index] - times[index - 1]
                minimum = constants.CHUNK_GAP_MS if index % 8 == 0 else constants.BYTE_GUARD_MS
                self.assertGreaterEqual(gap, minimum, (kind, index))

        # Heartbeats only after the display window, >= 25 ms apart, and
        # never inside the last 25 ms before the next scene.
        for (scene_at, times), next_start in zip(scenes, starts[1:]):
            scene_end = times[-1]
            beats = [at for at, kind, _d, _t in packets
                     if kind == "heartbeat" and scene_end < at < next_start]
            self.assertTrue(beats)
            self.assertGreaterEqual(beats[0] - scene_end, constants.DISPLAY_QUIET_MS)
            for earlier, later in zip(beats, beats[1:]):
                self.assertGreaterEqual(later - earlier, constants.OAM_HEARTBEAT_GAP_MS)
            self.assertGreaterEqual(next_start - beats[-1], constants.OAM_HEARTBEAT_GAP_MS)

    def test_fetches_happen_inside_the_display_window(self):
        packets = self.run_session([(0, request_bytes("KLAX"))], max_frames=4)
        scene_ends = [times[-1] for _at, kind, _d, times in packets if kind == "scene"]
        later_fetches = [at for at, _lat in self.fetches[1:]]
        self.assertEqual(len(later_fetches), len(scene_ends))
        for fetched, scene_end in zip(later_fetches, scene_ends):
            self.assertLess(fetched - scene_end, constants.DISPLAY_QUIET_MS)
        for earlier, later in zip(self.fetches, self.fetches[1:]):
            self.assertGreaterEqual(later[0] - earlier[0], constants.FETCH_SPACING_MS)

    def test_unknown_airport_is_rejected_then_retried(self):
        script = [(0, request_bytes("ZZZZ")), (2000, request_bytes("KSBA"))]
        packets = self.run_session(script, max_frames=1)
        locations = [desktop.decode_location_result(data)
                     for _at, kind, data, _t in packets if kind == "location"]
        self.assertEqual([(r.code, r.valid) for r in locations],
                         [("ZZZZ", False), ("KSBA", True)])

    def test_standard_scenario_helper_matches(self):
        # sim.standard_scenario is what mp_check replays under MicroPython.
        script, resolve, fetch = standard_scenario(self.klax)
        kinds = [kind for _at, kind, _d, _t in split_packets(run_session(script, resolve, fetch, 3))
                 if kind != "heartbeat"]
        self.assertEqual(kinds.count("location"), 2)
        self.assertEqual(kinds.count("scene"), 5)

    def test_new_request_mid_stream_reselects(self):
        # Three KSBA frames run to ~19.3 s, so the 12 s request lands mid-stream.
        script = [(0, request_bytes("KSBA")), (12000, request_bytes("KLAX"))]
        packets = self.run_session(script, max_frames=3)
        locations = [desktop.decode_location_result(data).code
                     for _at, kind, data, _t in packets if kind == "location"]
        self.assertEqual(locations, ["KSBA", "KLAX"])

    def test_upstream_failure_sets_scene_flags(self):
        def failing(*_args):
            raise OSError("timed out")

        self.fetch = failing
        packets = self.run_session([(0, request_bytes("KSBA"))], max_frames=1)
        scene = [desktop.decode_scene(data) for _at, kind, data, _t in packets if kind == "scene"][0]
        self.assertEqual(scene.flags, desktop.SCENE_STALE | desktop.SCENE_UPSTREAM_DOWN)


if __name__ == "__main__":
    unittest.main()
