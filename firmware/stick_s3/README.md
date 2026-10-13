# NES Radar on an M5StickS3

**Experimental.** This runs the NES Radar server on an
[M5StickS3](https://docs.m5stack.com/en/core/StickS3) instead
of a computer and FTDI cable. The Stick joins Wi‑Fi, polls adsb.fi, and speaks
the [`SIGNALING.md`](../../SIGNALING.md) link from its own UART, powered by
its internal battery or USB‑C. It runs on M5Stack's **UIFlow 2.0** firmware,
which the Stick usually ships with, and uses UIFlow's built‑in display, button,
and battery support.

> [!CAUTION]
> This host path has **not** had real‑console acceptance. The hardware‑accepted
> reference is still the macOS server with an FT232R 5 V cable. The StickS3
> link has worked on a real NES and on a MiSTer SNAC adapter and has passed
> its bench tests, but the long console runs are still to do (see
> [VALIDATION.md](VALIDATION.md)). Connect a vintage NES at your own risk.

> [!NOTE]
> This used to target the M5StickC Plus2, which is no longer sold. The two
> Sticks need differently wired hats (see [Converting a Plus2 hat](https://github.com/Armitage64/nesp32/blob/main/docs/WIRING.md#converting-a-plus2-hat)),
> so the Plus2 is no longer supported. Its last version is the git tag
> `stickc-plus2-final`, in `firmware/stickc_plus2/`.

## What's different from the computer server

| | Computer + FTDI | StickS3 |
|---|---|---|
| Runtime | CPython, `server/src/` | UIFlow 2.0 firmware for the StickS3 (MicroPython) |
| Serial | FT232R over USB | ESP32‑S3 UART1, G8 TX / G1 RX (Hat2‑Bus), 9600 8N1 |
| Level shifting | built into the 5 V cable | **you add it**: two NPN transistors (below) |
| Airport choice | NES controller (`--nes-icao`) | same, or a fixed `icao` in `config.json` |
| Wi‑Fi | the computer's | the network saved in M5Burner / UIFlow |
| Airport data | refreshed from OurAirports every 30 days | packed from `server/src/data` at deploy time |
| Status | terminal | the Stick's LCD |

Protocol, packet formats, timing constants, and scheduling are unchanged. The
Stick's copies in `nesradar/` are tested byte‑for‑byte against the desktop
modules. One scheduling difference: the adsb.fi fetch happens at the start of
the ROM's 6‑second display window, right after a scene, instead of just before
the next one. That way a slow TLS handshake can never delay a packet.

## Wiring

The hat, its pins on the StickS3, the level shifter and the reasons for it
are in [nesp32's wiring document](https://github.com/Armitage64/nesp32/blob/main/docs/WIRING.md), which this section
became: the same hat serves every ROM that uses a nesp32.

## Setup

1. **Check the firmware.** The Stick needs UIFlow 2.0.
   - If it shows the UIFlow launcher at power‑on, it already has it.
   - Otherwise, flash **UIFlow2.0 StickS3** with M5Stack's
     [M5Burner](https://docs.m5stack.com/en/uiflow2/m5burner/intro). The boot
     option you pick there doesn't matter; `tools/deploy.sh` sets it.
   - Either way, set up Wi‑Fi in M5Burner's configure step (or UIFlow's
     launcher). NES Radar joins only that network. Wi‑Fi credentials are
     deliberately never read from `config.json`, so they don't sit in a plain
     file on the Stick or next to the source.
   - **Blank screen at power‑on?** UIFlow's own `boot.py` stops with
     `ESP_ERR_NVS_NOT_FOUND` when no Wi‑Fi is saved, before NES Radar can
     start. If M5Burner's configure step doesn't save it, run
     `python3 tools/set_wifi.py` **in your own terminal**. It prompts for the
     network name and, without echoing, the password, and writes them to the
     Stick over USB. The password never goes to a file, your shell history, or
     a command line.
2. **Configure (optional).** Everything has a working default, so you only need
   a `config.json` to change something. To make one, copy `config.example.json`
   to `config.json` next to it:
   - `icao`: leave it `null` to pick airports on the NES. Set a code (e.g.
     `"KSBA"`) to stream without a controller request, which is handy on the
     bench.
   - `invert`: leave it `true` for the NPN shifter. Set it to `false` for the
     TXU0202 or two‑buffer alternatives.
3. **Deploy.** Connect the Stick by USB‑C, run `pip install mpremote` (it also
   brings pyserial, which `set_wifi.py` and `stick_repl.py` use), then
   `tools/deploy.sh`. The StickS3 has native USB, so its port is
   `/dev/cu.usbmodem…` on macOS or `/dev/ttyACM…` on Linux; the tools find a
   single Stick on their own. It works whether the Stick is running NES Radar, the
   UIFlow launcher, or nothing. The script:
   - packs `airports.bin` from `server/src/data`;
   - saves UIFlow's own `/flash/main.py` as `/flash/main_uiflow.py`, the first
     time only;
   - copies NES Radar into `/flash`;
   - sets UIFlow to start NES Radar at power‑on instead of its launcher;
   - restarts the Stick.

   Re‑run it after a server airport‑data refresh to update the Stick's table.

   **"Could not reach the Stick's REPL"?** Another app on the Stick is running
   and won't stop when interrupted, or the Stick isn't running UIFlow at all.
   Erase the Stick's user files and deploy again:

   ```
   pip install esptool
   python3 tools/erase_apps.py      # add --dry-run to only show what it would erase
   tools/deploy.sh
   ```

   `erase_apps.py` goes through the chip's bootloader, so no running app can
   block it. It erases only UIFlow's `/flash` partition (every app, `main.py`,
   and `boot.py`, which UIFlow recreates on the next boot). The firmware,
   UIFlow's fonts and images, and your saved Wi‑Fi are kept.

   If the Stick has other firmware entirely (for example an Arduino sketch,
   whose partitions are named `app0`, `app1`, and `spiffs`), UIFlow is gone
   and there is no REPL at all. `erase_apps.py` says so and erases nothing.
   Reflash UIFlow 2.0 with M5Burner, then run `tools/set_wifi.py` (a full
   reflash usually clears the saved Wi‑Fi) and `tools/deploy.sh`.

### Going back to UIFlow

NES Radar replaces UIFlow's launcher at power‑on. To get the launcher back:

```
tools/restore_uiflow.sh
```

It restores UIFlow's `main.py` from the backup `deploy.sh` made. If there is
no backup (after `erase_apps.py`, `/flash` had no `main.py` to save), it
writes UIFlow's stock one‑line `main.py` instead. Then it sets UIFlow's boot
option back to the launcher and restarts the Stick. NES Radar's files stay in
`/flash`, so `tools/deploy.sh` switches back.

### Optional: verify adsb.fi's certificate

MicroPython has no system trust store. By default the connection is encrypted
but adsb.fi is not authenticated; the data is public, read‑only aircraft
positions.

To require verification, save the **GTS Root R4** certificate in DER form (from
<https://pki.goog/repository/>) as `ca.der` next to `config.example.json`
and deploy again. This has not yet been exercised on hardware.

## Using it

The screen shows Wi‑Fi, state (`WAITING`, `STREAMING`, `PAUSED`, …), the airport,
the aircraft count, the last scene, and link byte counters.

- **A** (front) resets the server: it drops the current stream and waits for
  a new airport request, as after a reboot, but keeps Wi‑Fi. Press it after
  resetting the NES or when changing airports. A reset is noticed between
  packets, so during an adsb.fi fetch it can take a second or two.
- **B** (side) toggles the backlight, which saves battery.
- **Hold B for 2 s** to power off, leaving TX at idle. On USB power the Stick
  stays on; unplug it first.
- **Don't hold A while powering on.** UIFlow treats that as a request for its
  startup menu and keeps showing the menu until `tools/deploy.sh` runs again.
- **The side power button:** press once to power on or reset, double‑press to
  power off, and hold it to enter download mode. Download mode is also what
  you'll see if something on the hat pulls G0 low at power‑up.

The ROM behaves the same way it does with the computer server. Rebooting the
Stick counts as a server restart, so reload the ROM afterwards, as the main
README describes.

Battery life with Wi‑Fi active hasn't been measured on the StickS3; expect
around 2 hours from its 250 mAh cell. Use USB‑C for long sessions.

## Layout

| Path | What it is |
|---|---|
| `main.py` | boot entry point |
| `nesradar/protocol.py` | packet encoders (port of `scene_protocol.py`) |
| `nesradar/reverse.py` | reverse‑channel decoder (port of `nes_uart_request.py`) |
| `nesradar/traffic.py` | adsb.fi normalizing, slot allocation, stale rules |
| `nesradar/link.py` | paced UART transmit, heartbeats, request waits |
| `nesradar/app.py` | request → stream → pause lifecycle (port of `ConnectionLifecycle`/`stream_scope`) |
| `nesradar/airports.py` | binary search over `airports.bin` |
| `nesradar/net.py`, `board.py`, `ui.py`, `device.py` | Wi‑Fi/HTTPS, link UART and UIFlow `M5` hardware, status screen, wiring (UIFlow only) |
| `tools/build_airports.py`, `tools/deploy.sh` | airport packing and deployment |
| `tools/tx_pattern.py`, `tools/rx_monitor.py` | bench helpers for the scope tests, run with `mpremote run` |
| `tools/set_wifi.py` | saves Wi‑Fi into UIFlow's settings when M5Burner doesn't |
| `tools/erase_apps.py` | erases UIFlow's user files through the bootloader when an app won't stop |
| `tools/restore_uiflow.sh` | returns the Stick to the UIFlow launcher at power‑on |
| `tools/stick_repl.py` | runs code on the Stick without `mpremote`'s soft reset, which would start the UIFlow launcher; used by the scripts above |
| `tests/` | parity, session, and MicroPython golden‑vector tests |
| `VALIDATION.md` | validation status and the bench tests |

## Validation

What has been checked offline and on hardware, what is still open, and the
multimeter and scope bench tests are in [VALIDATION.md](VALIDATION.md).
