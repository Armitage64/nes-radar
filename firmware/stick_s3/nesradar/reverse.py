"""Decode the NES reverse channel (OUT0 -> Stick RX, 9,600 8N1).

A non-blocking port of server/src/nes_uart_request.py. The desktop reader
blocks in its own thread; here the single main loop calls service() with
whatever the UART has buffered, so the frame rules are the same but the loop
is turned inside out:

- six-byte frames, a marker 4E (location) or 50 (pause), XOR check seeded $A5;
- a location payload must be four letters A-Z, a pause payload four zeros;
- resync is one byte at a time, forward, because a good frame often sits one
  byte later;
- 250 ms without a byte ends a burst and discards its residue;
- the buffer outlives a single read, so two bursts in one read both decode.

The ESP32 UART may report the ROM's resting break (OUT0 low) as 0x00 bytes,
as the FT232R does, or drop it. Both are ordinary noise to the scanner.
"""

REQUEST_MARKER = 0x4E
PAUSE_MARKER = 0x50
CHECK_SEED = 0xA5
FRAME_BYTES = 6
PAYLOAD_BYTES = 4
MARKERS = (REQUEST_MARKER, PAUSE_MARKER)
BURST_GAP_MS = 250
MAX_BUFFER_BYTES = 256

ACTIVITY = "activity"
PAUSE = "pause"


def frame_checksum(body):
    value = CHECK_SEED
    for byte in body:
        value ^= byte
    return value


def decode_frame(frame):
    """Return an ICAO code, PAUSE, or None for one six-byte window."""
    if len(frame) != FRAME_BYTES:
        return None
    marker = frame[0]
    if marker not in MARKERS:
        return None
    if frame_checksum(frame[:FRAME_BYTES - 1]) != frame[FRAME_BYTES - 1]:
        return None
    payload = frame[1:1 + PAYLOAD_BYTES]
    if marker == PAUSE_MARKER:
        for byte in payload:
            if byte:
                return None
        return PAUSE
    for byte in payload:
        if not 0x41 <= byte <= 0x5A:
            return None
    return bytes(payload).decode("ascii")


def scan_for_frame(buffer):
    """(event, consumed) with the same contract as nes_uart_request.scan_for_frame."""
    for start in range(0, max(0, len(buffer) - FRAME_BYTES + 1)):
        event = decode_frame(bytes(buffer[start:start + FRAME_BYTES]))
        if event is not None:
            return event, start + FRAME_BYTES
    return None, max(0, len(buffer) - (FRAME_BYTES - 1))


class ReverseDecoder:
    def __init__(self):
        self.buffer = b""
        self.last_byte_at = None
        self.activity_reported = False

    def _drain(self, events):
        while self.buffer:
            event, consumed = scan_for_frame(self.buffer)
            if event is not None:
                self.buffer = self.buffer[consumed:]
                if not self.buffer:
                    self.activity_reported = False
                events.append(event)
                continue
            if consumed:
                self.buffer = self.buffer[consumed:]
            if len(self.buffer) > MAX_BUFFER_BYTES:
                self.buffer = self.buffer[len(self.buffer) - (FRAME_BYTES - 1):]
            return

    def service(self, chunk, now_ms, ticks_diff=None):
        """Feed newly read bytes (possibly empty); return events in arrival order.

        Events are ACTIVITY (a burst opened with a marker byte), PAUSE, or a
        four-letter ICAO string. ACTIVITY precedes the frame it announces,
        exactly as MonitorActivity precedes the request on the desktop.
        """
        if ticks_diff is None:
            def ticks_diff(a, b):
                return a - b
        events = []
        self._drain(events)
        if chunk:
            was_empty = not self.buffer
            self.buffer += bytes(chunk)
            self.last_byte_at = now_ms
            if was_empty and not self.activity_reported and self.buffer[0] in MARKERS:
                self.activity_reported = True
                events.append(ACTIVITY)
            self._drain(events)
        elif (self.buffer and self.last_byte_at is not None
              and ticks_diff(now_ms, self.last_byte_at) >= BURST_GAP_MS):
            self.buffer = b""
            self.activity_reported = False
        return events
