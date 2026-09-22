"""Link timing and scope constants.

Every value here is copied from server/src/nes_radar_server.py and is part of
the link contract in SIGNALING.md. tests/test_parity.py fails if any of them
drift from the desktop server. Times are integer milliseconds because
MicroPython's clock is ticks_ms.
"""

BAUD = 9600

BYTE_GUARD_MS = 5
CHUNK_BYTES = 8
CHUNK_GAP_MS = 30
OAM_HEARTBEAT = b"\x5A"
OAM_HEARTBEAT_GAP_MS = 25

POLL_MS = 8000
SCENE_INTERVAL_MS = 9500
STALE_AFTER_MS = 30000
FETCH_SPACING_MS = 1050
FETCH_TIMEOUT_S = 5

# Must equal DISPLAY_WINDOW_FRAMES in nes/nes_radar_scope_v3.s.
DISPLAY_WINDOW_FRAMES = 360
DISPLAY_COMMIT_FRAMES = 4
NES_FIELD_HZ = 60
DISPLAY_SCHEDULING_MARGIN_MS = 50
# (4 + 360) fields at 60 Hz plus the margin: when heartbeats may begin.
DISPLAY_QUIET_MS = (
    (DISPLAY_COMMIT_FRAMES + DISPLAY_WINDOW_FRAMES) * 1000 // NES_FIELD_HZ
    + DISPLAY_SCHEDULING_MARGIN_MS
)

IDENTITY_SETTLE_MS = 50
LEAD_IN_MS = 20
REQUEST_SETTLE_MS = 300

RANGE_NM = 9.0
MIN_GROUND_SPEED_KT = 40.0
LDV_SCOPE_CENTER = 72
LDV_RADIUS_PIXELS = 71
LDV_PIXELS_PER_NM = LDV_RADIUS_PIXELS / RANGE_NM

ADSB_FI_HOST = "opendata.adsb.fi"
ADSB_FI_PATH = "/api/v3"
USER_AGENT = "NES-Radar (+https://github.com/k6lcm/nes-radar)"
