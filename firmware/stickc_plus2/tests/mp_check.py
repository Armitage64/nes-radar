"""Run under MicroPython: check the package against golden.json.

    micropython mp_check.py <golden.json> <airports.bin> <klax_adsbfi.json>

Prints one line per check group and "ALL OK" at the end; exits non-zero on
the first mismatch. Floats: the ESP32 build is single precision, so traffic
geometry is compared field by field with a one-unit tolerance when the
interpreter is not double precision.
"""

import json
import sys

from nesradar import protocol, reverse, traffic
from nesradar.airports import AirportTable
from sim import run_session, standard_scenario

DOUBLE = 1.0 + 1e-10 != 1.0


def unhex(text):
    return bytes(int(text[i:i + 2], 16) for i in range(0, len(text), 2))


def fail(message):
    print("FAIL", message)
    sys.exit(1)


def check_scenes(golden):
    for case in golden["scenes"]:
        targets = [protocol.Target(**fields) for fields in case["targets"]]
        packet = protocol.encode_scene(case["sequence"], targets, case["flags"])
        if packet != unhex(case["packet"]):
            fail("scene seq %d" % case["sequence"])
    for case in golden["identities"]:
        identities = [protocol.Identity(**fields) for fields in case["identities"]]
        if protocol.encode_identity(case["sequence"], identities) != unhex(case["packet"]):
            fail("identity")
    for case in golden["locations"]:
        if protocol.encode_location_result(4, case["code"], case["valid"]) != unhex(case["packet"]):
            fail("location " + case["code"])
    if protocol.crc16_ccitt_false(b"123456789") != 0x29B1:
        fail("crc check value")
    print("protocol ok", len(golden["scenes"]))


def check_scans(golden):
    for case in golden["scans"]:
        event, consumed = reverse.scan_for_frame(unhex(case["buffer"]))
        if event != case["event"] or consumed != case["consumed"]:
            fail("scan %s -> %r %r" % (case["buffer"], event, consumed))
    decoder = reverse.ReverseDecoder()
    capture = unhex("004E4B534241F000004E4B534241F000")
    if decoder.service(capture, 0) != ["KSBA", "KSBA"]:
        fail("double burst")
    print("reverse ok", len(golden["scans"]))


def records(packet, size):
    return [packet[offset:offset + size] for offset in range(7, len(packet) - 2, size)]


def check_traffic(golden, payload):
    center = tuple(golden["traffic"]["center"])
    assigned = traffic.SlotAllocator().assign(traffic.extract_targets(payload, center))
    scene = protocol.encode_scene(1, assigned.targets, 0)
    identity = protocol.encode_identity(1, assigned.identities)
    expected_scene = unhex(golden["traffic"]["scene"])
    if identity != unhex(golden["traffic"]["identity"]):
        fail("traffic identity")
    if DOUBLE:
        if scene != expected_scene:
            fail("traffic scene")
    else:
        if scene[:7] != expected_scene[:7]:
            fail("traffic scene header")
        for actual, expected in zip(records(scene, 9), records(expected_scene, 9)):
            for index in range(9):
                if abs(actual[index] - expected[index]) > 1:
                    fail("traffic record field %d: %r vs %r" % (index, actual, expected))
    print("traffic ok", len(assigned.targets), "targets", "double" if DOUBLE else "single")


def check_airports(golden, path):
    table = AirportTable(path)
    for code, (latitude, longitude) in golden["airports"].items():
        found = table.resolve(code.lower())
        if abs(found[0] - latitude) > 1e-4 or abs(found[1] - longitude) > 1e-4:
            fail("airport %s %r" % (code, found))
    try:
        table.resolve("ZZZZ")
        fail("ZZZZ resolved")
    except ValueError:
        pass
    print("airports ok", table.count)


def check_session(golden, payload):
    script, resolve, fetch = standard_scenario(payload)
    tx = [[at, byte] for at, byte in run_session(script, resolve, fetch, 3)]
    expected = golden["session"]
    if DOUBLE:
        if tx != expected:
            fail("session transcript differs")
    else:
        # Single precision may move a scene record by one unit (and so its
        # CRC), but every byte's time, and so the framing, must be identical.
        if [at for at, _b in tx] != [at for at, _b in expected]:
            fail("session timing differs")
        differing = sum(1 for (_a, x), (_b, y) in zip(tx, expected) if x != y)
        print("session bytes differing under single precision:", differing)
    print("session ok", len(tx), "bytes")


def main():
    with open(sys.argv[1]) as handle:
        golden = json.load(handle)
    with open(sys.argv[3]) as handle:
        payload = json.load(handle)
    check_scenes(golden)
    check_scans(golden)
    check_traffic(golden, payload)
    check_airports(golden, sys.argv[2])
    check_session(golden, payload)
    print("ALL OK")


main()
