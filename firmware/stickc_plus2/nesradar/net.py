"""Wi-Fi and the adsb.fi HTTPS client (MicroPython only).

The request is HTTP/1.0 so the reply is never chunked, and it asks for no
compression, so the body can go straight into json.load() from the socket.
A busy airport (KLAX, dist 10) was about 22 KB of JSON when this was written;
with the Plus2's PSRAM that is comfortably inside the heap.

Certificate verification: MicroPython's ssl does not verify by default and has
no system trust store. If /ca.der exists (see README), it is loaded and
verification is required; otherwise the connection is encrypted but the
server is not authenticated. The data is public, read-only aircraft
positions, so the unverified mode is a deliberate, documented default.
"""

import json
import socket
import ssl

import network

from nesradar import clock
from nesradar.constants import ADSB_FI_HOST, ADSB_FI_PATH, FETCH_TIMEOUT_S, USER_AGENT

CA_PATH = "/ca.der"

_wlan = None


def wlan():
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
        _wlan.active(True)
    return _wlan


def connect(ssid, password, timeout_ms=20000, on_wait=None):
    station = wlan()
    if station.isconnected():
        return True
    station.connect(ssid, password)
    started = clock.ticks_ms()
    while not station.isconnected():
        if clock.ticks_diff(clock.ticks_ms(), started) >= timeout_ms:
            return False
        if on_wait is not None:
            on_wait()
        clock.sleep_ms(100)
    return True


def is_connected():
    return _wlan is not None and _wlan.isconnected()


def _ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with open(CA_PATH, "rb") as handle:
            context.load_verify_locations(cadata=handle.read())
        context.verify_mode = ssl.CERT_REQUIRED
    except OSError:
        context.verify_mode = ssl.CERT_NONE
    return context


def certificate_mode():
    try:
        open(CA_PATH, "rb").close()
        return "verified"
    except OSError:
        return "unverified"


def fetch_json(latitude, longitude, dist_nm):
    if not is_connected():
        raise OSError("Wi-Fi is not connected")
    path = "%s/lat/%.6f/lon/%.6f/dist/%d" % (ADSB_FI_PATH, latitude, longitude, dist_nm)
    address = socket.getaddrinfo(ADSB_FI_HOST, 443, 0, socket.SOCK_STREAM)[0][-1]
    raw = socket.socket()
    raw.settimeout(FETCH_TIMEOUT_S)
    stream = None
    try:
        raw.connect(address)
        stream = _ssl_context().wrap_socket(raw, server_hostname=ADSB_FI_HOST)
        request = (
            "GET %s HTTP/1.0\r\n"
            "Host: %s\r\n"
            "User-Agent: %s\r\n"
            "Accept: application/json\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        ) % (path, ADSB_FI_HOST, USER_AGENT)
        stream.write(request.encode("ascii"))
        status = stream.readline().split(None, 2)
        if len(status) < 2 or status[1] != b"200":
            raise OSError("adsb.fi HTTP %s" % (status[1].decode() if len(status) > 1 else "?"))
        while True:
            line = stream.readline()
            if not line or line == b"\r\n":
                break
        return json.load(stream)
    finally:
        (stream or raw).close()
