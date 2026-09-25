"""Golden vectors from the desktop server, for checking the port under MicroPython.

MicroPython cannot import the desktop modules (dataclasses, pyserial), so
CPython computes the expected bytes here and mp_check.py compares the
package's output against them on the real interpreter.
"""

import json
from pathlib import Path
import random

from sim import run_session, standard_scenario

import nes_radar_server as radar
import nes_uart_request as desktop_reverse
import scene_protocol as desktop
from c64_reference import ultimate_radar_server as C64
from nes_icao_request import LocationRequest, PauseRequest, request_bytes

FIXTURES = Path(__file__).resolve().parent / "fixtures"
KLAX = (33.942501, -118.407997)


def _event(event):
    if isinstance(event, LocationRequest):
        return event.code
    if isinstance(event, PauseRequest):
        return "pause"
    return event


def build_golden():
    rng = random.Random(2026)
    golden = {"scenes": [], "identities": [], "locations": [], "scans": [], "traffic": {}}

    for frame in range(0, 120, 11):
        for fixture in (desktop.synthetic_targets(frame), desktop.synthetic_approach_targets(frame)):
            flags = rng.randint(0, 0x1F)
            golden["scenes"].append({
                "sequence": frame,
                "flags": flags,
                "targets": [vars(target) for target in fixture],
                "packet": desktop.encode_scene(frame, fixture, flags).hex(),
            })
    golden["identities"].append({
        "sequence": 0x33,
        "identities": [vars(identity) for identity in desktop.BASE_IDENTITIES],
        "packet": desktop.encode_identity(0x33, desktop.BASE_IDENTITIES).hex(),
    })
    for code, valid in (("KSBA", True), ("klax", False)):
        golden["locations"].append({
            "code": code,
            "valid": valid,
            "packet": desktop.encode_location_result(4, code, valid).hex(),
        })

    pieces = [request_bytes("KSBA"), request_bytes("KJFK"), bytes.fromhex("5000000000F5"),
              b"\x00", b"\x4E", b"\x50", b"\xA5"]
    for _ in range(400):
        buffer = b"".join(rng.choice(pieces) for _ in range(rng.randint(0, 5)))
        buffer = buffer[rng.randrange(len(buffer)):] if buffer and rng.random() < 0.3 else buffer
        event, consumed = desktop_reverse.scan_for_frame(buffer, False)
        golden["scans"].append({"buffer": buffer.hex(), "event": _event(event), "consumed": consumed})

    payload = json.loads((FIXTURES / "klax_adsbfi.json").read_text())
    scope = C64.Scope(KLAX[0], KLAX[1], radar.DEFAULT_RANGE_NM).validated()
    assigned = radar.SlotAllocator().assign(radar.extract_targets_with_details(payload, scope))
    golden["traffic"] = {
        "center": list(KLAX),
        "scene": desktop.encode_scene(1, assigned.targets, 0).hex(),
        "identity": desktop.encode_identity(1, assigned.identities).hex(),
    }
    script, resolve, fetch = standard_scenario(payload)
    golden["session"] = [[at, byte] for at, byte in run_session(script, resolve, fetch, 3)]
    golden["airports"] = {code: list(radar.resolve_airport(code))
                          for code in ("KSBA", "EGLL", "KCMA", "KLAX", "RJTT", "YSSY")}
    radar.AIRPORTS = None
    return golden
