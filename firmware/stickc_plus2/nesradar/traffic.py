"""adsb.fi normalization, slot allocation, and scene flags.

Ports, in one module:
- extract_targets() from server/src/c64_reference/ultimate_radar_server.py,
  merged with extract_targets_with_details() from nes_radar_server.py. The
  desktop runs them as two passes and re-matches aircraft by callsign, type,
  and distance; here the detail fields come from the same JSON item directly.
- to_nes_target(), SlotAllocator and scene_flags() from nes_radar_server.py.
- TrafficService.refresh()'s snapshot/stale rules from the C64 reference.

MicroPython on the ESP32 uses single-precision floats. Positions and
distances can therefore differ from the desktop in the last pixel or tenth
at a boundary; tests/test_parity.py checks this within that tolerance.
"""

import math

from nesradar import clock
from nesradar.constants import (
    FETCH_SPACING_MS,
    LDV_PIXELS_PER_NM,
    LDV_RADIUS_PIXELS,
    LDV_SCOPE_CENTER,
    MIN_GROUND_SPEED_KT,
    RANGE_NM,
    STALE_AFTER_MS,
)
from nesradar.protocol import (
    IDENTITY_CHARACTERS,
    MAX_TARGETS,
    SCENE_STALE,
    SCENE_TRUNCATED,
    SCENE_UPSTREAM_DOWN,
    Identity,
    Target,
)

NM_PER_KM = 0.539957
EARTH_RADIUS_KM = 6371.0


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        value = float(value)
    else:
        try:
            value = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def distance_nm(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    h = min(1.0, max(0.0, h))
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h)) * NM_PER_KM


def bearing_degrees(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def extract_targets(payload, center, range_nm=RANGE_NM):
    aircraft = payload.get("ac") or payload.get("aircraft") or []
    if not isinstance(aircraft, list):
        return []
    targets = []
    for item in aircraft:
        if not isinstance(item, dict):
            continue
        if str(item.get("alt_baro", "")).lower() == "ground":
            continue
        speed = _number(item.get("gs"))
        if speed is not None and speed < MIN_GROUND_SPEED_KT:
            continue
        latitude = _number(item.get("lat"))
        longitude = _number(item.get("lon"))
        if latitude is None or longitude is None:
            continue
        distance = distance_nm(center, (latitude, longitude))
        if distance > range_nm:
            continue
        track = _number(item.get("track"))
        if track is None:
            track = _number(item.get("true_heading"))
        rate = item.get("baro_rate")
        if rate is None:
            rate = item.get("geom_rate")
        try:
            vertical_rate = None if rate is None else float(rate)
        except (TypeError, ValueError):
            vertical_rate = None
        targets.append({
            "callsign": str(item.get("flight") or item.get("r") or item.get("hex") or "----").strip(),
            "type": str(item.get("t") or "----").strip(),
            "alt": _number(item.get("alt_baro")),
            "gs": speed,
            "trk": track,
            "distance": distance,
            "bearing": bearing_degrees(center, (latitude, longitude)),
            "registration": item.get("r"),
            "squawk": item.get("squawk"),
            "category": item.get("category"),
            "vertical_rate": vertical_rate,
        })
    targets.sort(key=lambda target: target["distance"])
    return targets


def clean_identity(value, width):
    text = str(value or "").strip().upper()
    cleaned = "".join(
        character if character in IDENTITY_CHARACTERS else "-" for character in text
    )
    return cleaned[:width]


def target_identity(target):
    return (
        clean_identity(target.get("callsign"), 8),
        clean_identity(target.get("type"), 4),
        clean_identity(target.get("registration"), 6),
        clean_identity(target.get("squawk"), 4),
        clean_identity(target.get("category"), 2),
    )


def to_nes_target(slot, target):
    bearing = math.radians(float(target["bearing"]))
    distance = float(target["distance"])
    radius = min(LDV_RADIUS_PIXELS, distance * LDV_PIXELS_PER_NM)
    x = LDV_SCOPE_CENTER + round(math.sin(bearing) * radius)
    y = LDV_SCOPE_CENTER - round(math.cos(bearing) * radius)
    track = target.get("trk")
    altitude = target.get("alt")
    speed = target.get("gs")
    vertical_rate = target.get("vertical_rate")
    return Target(
        slot=slot,
        x=max(0, min(143, x)),
        y=max(0, min(143, y)),
        track=0 if track is None else round(float(track) * 256 / 360) & 0xFF,
        altitude_hundreds=(
            0 if altitude is None else max(0, min(65535, round(float(altitude) / 100)))
        ),
        speed_knots=0 if speed is None else max(0, min(255, round(float(speed)))),
        vertical_rate_hundreds=(
            0 if vertical_rate is None
            else max(-99, min(99, round(float(vertical_rate) / 100)))
        ),
        distance_tenths=max(0, min(99, round(distance * 10))),
        track_valid=track is not None,
        altitude_valid=altitude is not None,
        speed_valid=speed is not None,
        vertical_rate_valid=vertical_rate is not None,
        distance_valid=True,
    )


class AssignedScene:
    def __init__(self, targets, identities, identity_changed):
        self.targets = targets
        self.identities = identities
        self.identity_changed = identity_changed


class SlotAllocator:
    """Assign markers 1..8 nearest-to-farthest, matching the desktop server."""

    def __init__(self):
        self._identity_keys = None

    def assign(self, targets):
        nearest = sorted(
            (
                target for target in targets
                if 0.0 <= float(target.get("distance", float("inf"))) <= 9.0
            ),
            key=lambda target: float(target.get("distance", float("inf"))),
        )[:MAX_TARGETS]
        scene_targets = tuple(to_nes_target(slot, target) for slot, target in enumerate(nearest))
        by_slot = {}
        for slot, target in enumerate(nearest):
            by_slot[slot] = Identity(slot, *target_identity(target))
        identities = tuple(
            by_slot.get(slot) or Identity(slot, "", "") for slot in range(MAX_TARGETS)
        )
        keys = tuple(identity.key() for identity in identities)
        changed = keys != self._identity_keys
        self._identity_keys = keys
        return AssignedScene(scene_targets, identities, changed)


class Snapshot:
    def __init__(self, targets, total, good_ms, stale, error=None):
        self.targets = targets
        self.total = total
        self.good_ms = good_ms
        self.stale = stale
        self.error = error


def scene_flags(snapshot):
    flags = 0
    if snapshot.stale:
        flags |= SCENE_STALE
    if snapshot.total > MAX_TARGETS:
        flags |= SCENE_TRUNCATED
    if snapshot.error:
        flags |= SCENE_UPSTREAM_DOWN
    return flags


class TrafficService:
    """One scope's adsb.fi snapshot with the desktop's stale/error rules.

    fetch_json(latitude, longitude, dist_nm) does the network call and is
    injected so the rules can be tested without one.
    """

    def __init__(self, latitude, longitude, fetch_json, range_nm=RANGE_NM,
                 stale_after_ms=STALE_AFTER_MS):
        self.center = (latitude, longitude)
        self.range_nm = range_nm
        self.fetch_json = fetch_json
        self.stale_after_ms = stale_after_ms
        self.snapshot = None
        self._last_fetch_ms = None

    def provider_distance(self):
        return max(1, min(250, int(math.ceil(self.range_nm + 1.0))))

    def refresh(self):
        if self._last_fetch_ms is not None:
            wait = FETCH_SPACING_MS - clock.ticks_diff(clock.ticks_ms(), self._last_fetch_ms)
            clock.sleep_ms(wait)
        self._last_fetch_ms = clock.ticks_ms()
        try:
            payload = self.fetch_json(self.center[0], self.center[1], self.provider_distance())
            targets = extract_targets(payload, self.center, self.range_nm)
            snapshot = Snapshot(targets, len(targets), clock.ticks_ms(), False)
        except Exception as error:  # every upstream failure becomes a flagged scene
            old = self.snapshot
            message = str(error) or type(error).__name__
            if old is not None:
                stale = (
                    old.good_ms is None
                    or clock.ticks_diff(clock.ticks_ms(), old.good_ms) >= self.stale_after_ms
                )
                snapshot = Snapshot(old.targets, old.total, old.good_ms, stale, message)
            else:
                snapshot = Snapshot([], 0, None, True, message)
        self.snapshot = snapshot
        return snapshot
