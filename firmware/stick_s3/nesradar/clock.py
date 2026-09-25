"""Millisecond clock that works on MicroPython and CPython.

MicroPython has ticks_ms/ticks_diff/sleep_ms and no monotonic(); CPython has
the reverse. Everything else in the package goes through these three names.
"""

import time

if hasattr(time, "ticks_ms"):
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
    ticks_add = time.ticks_add
    sleep_ms = time.sleep_ms
else:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def ticks_add(a, delta):
        return a + delta

    def sleep_ms(ms):
        if ms > 0:
            time.sleep(ms / 1000)
