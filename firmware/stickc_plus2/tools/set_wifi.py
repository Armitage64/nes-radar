#!/usr/bin/env python3
"""Save Wi-Fi settings into the Stick's UIFlow settings (NVS), from your terminal.

    python3 tools/set_wifi.py [serial-port]

Use this when M5Burner's configure step does not stick. UIFlow's boot.py
reads these settings on every start, even with "Run main.py directly"; if any
is missing it stops with ESP_ERR_NVS_NOT_FOUND and never runs main.py, which
leaves the screen blank.

The password is read with getpass (not echoed) and sent over the USB serial
link in MicroPython's raw REPL. It never touches a file, your shell history,
or a command line. Needs pyserial, which mpremote already installs.
"""

import getpass
import glob
import sys
import time

import serial

BAUD = 115200


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/ttyUSB*")
                   + glob.glob("/dev/ttyACM*"))
    if len(ports) != 1:
        sys.exit("Found %d serial ports %s; pass the Stick's port as an argument."
                 % (len(ports), ports))
    return ports[0]


def read_until(link, marker, timeout=10.0):
    data = b""
    end = time.time() + timeout
    while time.time() < end:
        data += link.read(256)
        if marker in data:
            return data
    raise TimeoutError("no response from the Stick (got %r)" % data[-80:])


def raw_exec(link, code):
    """Run code in MicroPython's raw REPL; return (stdout, stderr)."""
    link.write(b"\r\x03\x03")
    time.sleep(0.3)
    link.reset_input_buffer()
    link.write(b"\r\x01")
    read_until(link, b"raw REPL; CTRL-B to exit\r\n>")
    link.write(code.encode("utf-8") + b"\x04")
    # Reply: "OK", stdout, 0x04, stderr, 0x04, ">" -- possibly in one read.
    reply = read_until(link, b"\x04>")
    link.write(b"\x02")
    if not reply.startswith(b"OK"):
        raise RuntimeError("the Stick did not accept the code: %r" % reply[:80])
    output, errors = reply[2:reply.rindex(b"\x04>")].split(b"\x04", 1)
    return output.decode(errors="replace"), errors.decode(errors="replace")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    ssid = input("Wi-Fi network name (SSID): ").strip()
    if not ssid:
        sys.exit("No SSID given; nothing changed.")
    password = getpass.getpass("Wi-Fi password (not shown): ")
    # Every key UIFlow's startup() reads with get_str. DHCP leaves the
    # static-address fields empty.
    settings = {
        "net_mode": "WIFI",
        "ssid0": ssid,
        "pswd0": password,
        "protocol": "DHCP",
        "ip_addr": "",
        "netmask": "",
        "gateway": "",
        "dns": "",
    }
    code = (
        "import esp32\n"
        "n = esp32.NVS('uiflow')\n"
        "for k, v in %r.items():\n"
        "    n.set_str(k, v)\n"
        "n.commit()\n"
        "print('saved', len(%r), 'settings')\n"
    ) % (settings, settings)
    with serial.Serial(port, BAUD, timeout=0.2) as link:
        output, errors = raw_exec(link, code)
    if errors:
        sys.exit("The Stick reported an error:\n" + errors)
    print(output.strip())
    print("Done. Power-cycle the Stick (or run `mpremote reset`).")


if __name__ == "__main__":
    main()
