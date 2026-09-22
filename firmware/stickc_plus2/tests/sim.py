"""A virtual clock and a scripted NES, shared by CPython and MicroPython tests.

Kept to the MicroPython-compatible subset so mp_check.py can run the same
session simulation on the real interpreter.
"""

from nesradar import app, clock
from nesradar.link import Link


class VirtualClock:
    def __init__(self):
        self.now = 0

    def ticks_ms(self):
        return self.now

    def sleep_ms(self, ms):
        if ms > 0:
            self.now += ms


class ScriptedNes:
    """A fake UART: the NES side sends frames at scripted times; TX is recorded."""

    def __init__(self, virtual, script):
        self.virtual = virtual
        self.script = sorted(script)
        self.tx = []

    def write(self, data):
        for byte in bytes(data):
            self.tx.append((self.virtual.now, byte))
        # 10 bits at 9600 baud per byte before flush() returns.
        self.virtual.now += len(data) * 10 * 1000 // 9600 or 1

    def flush(self):
        pass

    def any(self):
        return sum(len(chunk) for at, chunk in self.script if at <= self.virtual.now)

    def read(self, count):
        ready = [item for item in self.script if item[0] <= self.virtual.now]
        self.script = [item for item in self.script if item[0] > self.virtual.now]
        return b"".join(chunk for _at, chunk in ready)


def run_session(script, resolve, fetch, max_frames, virtual=None):
    """Run Session.serve() on a virtual clock; return the recorded TX."""
    virtual = virtual or VirtualClock()
    saved = (clock.ticks_ms, clock.sleep_ms)
    clock.ticks_ms = virtual.ticks_ms
    clock.sleep_ms = virtual.sleep_ms
    try:
        nes = ScriptedNes(virtual, script)
        app.Session(Link(nes), resolve, fetch, max_frames=max_frames).serve()
        return nes.tx
    finally:
        clock.ticks_ms, clock.sleep_ms = saved


def standard_scenario(klax_payload):
    """The request, stream, pause, and re-select flow used by both interpreters."""
    request_ksba = bytes((0x4E, 0x4B, 0x53, 0x42, 0x41, 0xF0))
    request_klax = bytes((0x4E, 0x4B, 0x4C, 0x41, 0x58, 0xA5 ^ 0x4E ^ 0x4B ^ 0x4C ^ 0x41 ^ 0x58))
    pause = bytes((0x50, 0, 0, 0, 0, 0xF5))
    script = [
        (100, b"\x00" + request_ksba + b"\x00"),
        (15000, pause),
        (18000, request_klax),
    ]
    airports = {"KSBA": (34.4262, -119.8404), "KLAX": (33.942501, -118.407997)}

    def resolve(code):
        if code not in airports:
            raise ValueError("unknown")
        return airports[code]

    def fetch(latitude, longitude, dist):
        return klax_payload if abs(latitude - 33.9425) < 0.01 else {"ac": []}

    return script, resolve, fetch
