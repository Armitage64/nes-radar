"""Host-to-NES packet encoders (protocol v2), MicroPython-compatible.

A port of the encoding half of server/src/scene_protocol.py. The desktop
module uses dataclasses, str.ljust and str.isascii, none of which exist on
MicroPython, so this is a separate copy rather than a shared import.
tests/test_parity.py holds it byte-identical to the original.
"""

MARKER = 0xA5
PACKET_TYPE_SCENE = 0x01
PACKET_TYPE_IDENTITY = 0x02
PACKET_TYPE_LOCATION = 0x03
VERSION = 0x02
MAX_TARGETS = 8
RECORD_SIZE = 9
IDENTITY_RECORD_SIZE = 25
SCOPE_SIZE = 160

SCENE_STALE = 0x01
SCENE_TRUNCATED = 0x02
SCENE_UPSTREAM_DOWN = 0x04

TRACK_INVALID = 0x08
ALT_INVALID = 0x10
SPEED_INVALID = 0x20
ALERT = 0x40

IDENTITY_CHARACTERS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"


def _pad(text, width):
    return text + " " * (width - len(text))


def _check_int(name, value, low, high):
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError("%s must be an integer from %d through %d" % (name, low, high))


class Target:
    def __init__(
        self,
        slot,
        x,
        y,
        track,
        altitude_hundreds,
        speed_knots,
        vertical_rate_hundreds=0,
        distance_tenths=0,
        track_valid=True,
        altitude_valid=True,
        speed_valid=True,
        alert=False,
        vertical_rate_valid=True,
        distance_valid=True,
    ):
        self.slot = slot
        self.x = x
        self.y = y
        self.track = track
        self.altitude_hundreds = altitude_hundreds
        self.speed_knots = speed_knots
        self.vertical_rate_hundreds = vertical_rate_hundreds
        self.distance_tenths = distance_tenths
        self.track_valid = track_valid
        self.altitude_valid = altitude_valid
        self.speed_valid = speed_valid
        self.alert = alert
        self.vertical_rate_valid = vertical_rate_valid
        self.distance_valid = distance_valid

    def encode(self):
        _check_int("slot", self.slot, 0, 7)
        _check_int("x", self.x, 0, SCOPE_SIZE - 1)
        _check_int("y", self.y, 0, SCOPE_SIZE - 1)
        _check_int("track", self.track, 0, 255)
        _check_int("altitude_hundreds", self.altitude_hundreds, 0, 65535)
        _check_int("speed_knots", self.speed_knots, 0, 255)
        _check_int("vertical_rate_hundreds", self.vertical_rate_hundreds, -99, 99)
        _check_int("distance_tenths", self.distance_tenths, 0, 99)
        flags = self.slot
        if not self.track_valid:
            flags |= TRACK_INVALID
        if not self.altitude_valid:
            flags |= ALT_INVALID
        if not self.speed_valid:
            flags |= SPEED_INVALID
        if self.alert:
            flags |= ALERT
        return bytes((
            flags,
            self.x,
            self.y,
            self.track,
            self.altitude_hundreds & 0xFF,
            (self.altitude_hundreds >> 8) & 0xFF,
            self.speed_knots,
            self.vertical_rate_hundreds & 0xFF if self.vertical_rate_valid else 0x80,
            self.distance_tenths if self.distance_valid else 0xFF,
        ))


def normalize_identity_field(value, width):
    if not isinstance(value, str):
        raise ValueError("identity fields must be strings")
    normalized = value.strip().upper()
    if len(normalized) > width:
        raise ValueError("identity field is longer than %d characters" % width)
    for character in normalized:
        if character not in IDENTITY_CHARACTERS:
            raise ValueError("identity fields use only A-Z, 0-9, space, and hyphen")
    return normalized


class Identity:
    def __init__(self, slot, callsign, aircraft_type, registration="", squawk="", category=""):
        self.slot = slot
        self.callsign = callsign
        self.aircraft_type = aircraft_type
        self.registration = registration
        self.squawk = squawk
        self.category = category

    def key(self):
        return (
            self.slot,
            self.callsign,
            self.aircraft_type,
            self.registration,
            self.squawk,
            self.category,
        )

    def encode(self):
        if not isinstance(self.slot, int) or not 0 <= self.slot < MAX_TARGETS:
            raise ValueError("slot must be an integer from 0 through 7")
        text = (
            _pad(normalize_identity_field(self.callsign, 8), 8)
            + _pad(normalize_identity_field(self.aircraft_type, 4), 4)
            + _pad(normalize_identity_field(self.registration, 6), 6)
            + _pad(normalize_identity_field(self.squawk, 4), 4)
            + _pad(normalize_identity_field(self.category, 2), 2)
        )
        return bytes((self.slot,)) + text.encode("ascii")


def crc16_ccitt_false(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _envelope(packet_type, sequence, flags, count, payload):
    body = bytes((
        packet_type,
        VERSION,
        sequence & 0xFF,
        flags,
        count,
        len(payload),
    )) + payload
    crc = crc16_ccitt_false(body)
    return bytes((MARKER,)) + body + bytes(((crc >> 8) & 0xFF, crc & 0xFF))


def _unique_slots(items, message):
    slots = [item.slot for item in items]
    if len(set(slots)) != len(slots):
        raise ValueError(message)


def encode_scene(sequence, targets, flags=0):
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    if not isinstance(flags, int) or not 0 <= flags <= 0x1F:
        raise ValueError("flags must use only scene bits 0 through 4")
    target_list = tuple(targets)
    if len(target_list) > MAX_TARGETS:
        raise ValueError("a scene can contain at most eight targets")
    _unique_slots(target_list, "target slots must be unique within a scene")
    payload = b"".join(target.encode() for target in target_list)
    return _envelope(PACKET_TYPE_SCENE, sequence, flags, len(target_list), payload)


def encode_identity(sequence, identities):
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    identity_list = tuple(identities)
    if len(identity_list) > MAX_TARGETS:
        raise ValueError("an identity packet can contain at most eight slots")
    _unique_slots(identity_list, "identity slots must be unique within a packet")
    payload = b"".join(identity.encode() for identity in identity_list)
    return _envelope(PACKET_TYPE_IDENTITY, sequence, 0, len(identity_list), payload)


def is_icao(code):
    if not isinstance(code, str) or len(code) != 4:
        return False
    for character in code:
        if not "A" <= character <= "Z":
            return False
    return True


def normalize_icao(code):
    if not isinstance(code, str):
        raise ValueError("ICAO code must be text")
    normalized = code.strip().upper()
    if not is_icao(normalized):
        raise ValueError("ICAO code must contain exactly four ASCII letters")
    return normalized


def encode_location_result(sequence, code, valid):
    if not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    payload = normalize_icao(code).encode("ascii")
    return _envelope(PACKET_TYPE_LOCATION, sequence, 0 if valid else 1, 1, payload)


def clear_packets(sequence):
    """Blank all identity slots and send an empty stale scene (--clear)."""
    identities = tuple(Identity(slot, "", "") for slot in range(MAX_TARGETS))
    return (
        encode_identity(sequence, identities),
        encode_scene(sequence, (), SCENE_STALE),
    )
