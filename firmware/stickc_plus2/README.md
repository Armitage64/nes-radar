# NES Radar on an M5StickC Plus2

**Experimental.** This runs the NES Radar server on an
[M5StickC Plus2](https://docs.m5stack.com/en/core/M5StickC%20PLUS2) instead
of a computer and FTDI cable. The Stick joins Wi‑Fi, polls adsb.fi, and speaks
the [`SIGNALING.md`](../../SIGNALING.md) link from its own UART, powered by
its internal battery or USB‑C. It runs on M5Stack's **UIFlow 2.0** firmware,
which the Stick usually ships with, and uses UIFlow's built‑in display, button,
and battery support.

> [!CAUTION]
> This host path has **not** had real‑console acceptance. The hardware‑accepted
> reference is still the macOS server with an FT232R 5 V cable. Everything here
> has been checked offline only (see [Validation](#validation)). Connect a
> vintage NES at your own risk.

## What's different from the computer server

| | Computer + FTDI | StickC Plus2 |
|---|---|---|
| Runtime | CPython, `server/src/` | UIFlow 2.0 firmware (MicroPython 1.27 in UIFlow 2.5.3) |
| Serial | FT232R over USB | ESP32 UART1, G26 TX / G36 RX (top header), 9600 8N1 |
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

The ESP32 is a 3.3 V part and **not 5 V tolerant**, and a 3.3 V high is not
guaranteed to register on the NES. Each direction goes through one NPN
transistor stage, all through‑hole, which fits the M5Stick proto hat's 5 × 8
board with no adapters. See [Why a level shifter](#why-a-level-shifter).

The link uses the Stick's top 8‑pin header, the one the proto hat plugs into.
It does not use the Grove port.

### NPN shifter (default, through‑hole)

```
 TX (Stick → NES)                          RX (NES → Stick)

 NES +5 V (pin 5)                          Stick 3V3
     │                                         │
   [10 kΩ]                                   [10 kΩ]
     │                                         │
     ├──[1 kΩ]──► NES D0 (pin 4)               ├──────► Stick G36/G25
     │                                         │
    C│                                        C│
 G26 ─[10 kΩ]─B  2N3904              NES OUT0 ─[10 kΩ]─B  2N3904
    E│                              (pin 3)   E│
    GND                                        GND

 Stick GND ── NES GND (pin 1)
 5V IN, 5V OUT, BAT, G0 ── not connected
```

**Parts:** two 2N3904 (TO‑92), four 10 kΩ, and one 1 kΩ resistor. Any small
NPN works (2N2222A, BC547, PN2222); check the E‑B‑C lead order, which
differs between parts and makers.

| From | Through | To |
|---|---|---|
| Stick G26 | 10 kΩ | TX 2N3904 base |
| TX 2N3904 emitter | – | GND |
| TX 2N3904 collector | 10 kΩ | NES pin 5 (+5 V) |
| TX 2N3904 collector | 1 kΩ | NES pin 4 (D0) |
| NES pin 3 (OUT0) | 10 kΩ | RX 2N3904 base |
| RX 2N3904 emitter | – | GND |
| RX 2N3904 collector | 10 kΩ | Stick 3V3 |
| RX 2N3904 collector | – | Stick G36/G25 |
| Stick GND | – | NES pin 1 (GND) |

| Header pin | Use |
|---|---|
| G26 | TX, to the TX transistor's base resistor |
| G36/G25 | RX, from the RX transistor's collector. G36 is input‑only; its shared partner G25 stays an input. |
| 3V3 | RX pull‑up (0.33 mA while OUT0 is high) |
| GND | common ground |
| G0 | **not used.** It is a boot‑mode pin. If anything held it low at power‑up (such as the NES resting OUT0 low), the Stick would start in firmware‑download mode instead of running NES Radar. |
| 5V IN, 5V OUT, BAT | not connected |

**How it works.** Each stage inverts, and the ESP32 UART inverts TX and RX in
hardware to cancel it (`"invert": true`, the default).

- **TX:** the UART idles with G26 low, so the transistor is off and the
  10 kΩ pull‑up holds D0 at the NES's own 5 V, which is idle (mark). A space
  bit turns the transistor on and pulls D0 to about 0.1 V. A 2N3904 switches at
  about 0.7 V on its base, so 3.3 V drives it hard, and both levels sit far
  inside the NES input's limits.
- **RX:** OUT0 high turns the transistor on and pulls G36 low; the UART's RX
  inversion restores it. It works whenever OUT0 reaches about 1 V, so how high
  the NES CPU's unbuffered OUT0 really goes no longer matters. It draws about
  0.2–0.4 mA from OUT0.
- **Idle and power states:**
  - While the Stick is off or booting, G26 floats, the TX transistor stays
    off, and D0 rests high, the correct idle level.
  - While the NES is off, OUT0 is low, so G36 reads a break, which the decoder
    ignores.
  - Pull‑ups come from the side they drive: D0's from the NES, G36's from the
    Stick. Nothing actively drives a powered‑down side. The small leftover paths
    through a transistor's base junction (a fraction of a milliamp, via
    10 kΩ) are about a tenth of what the tested FTDI cable pushes into an
    unpowered NES through its 1 kΩ.
- **Speed:** a pull‑up makes the rising edge take about 0.3 µs, roughly 1/300
  of a 9600‑baud bit. The ROM samples mid‑bit.
- **Why the 1 kΩ stays:** it is the same fault‑current limiter the FTDI
  cable uses on D0. On the RX side the 10 kΩ base resistor does that job.

**Fit on the 5 × 8 proto hat:**
- Each TO‑92 takes 3 holes in a row. After soldering, bend it over flat so it
  stands about 3 mm tall.
- Use 1/8 W mini resistors laid flat across 3 holes (0.3″); they stand about
  2 mm tall.
- The whole circuit uses about 21 of the 40 holes.
- Make all connections with the NES off and the Stick off. Identify leads by
  continuity, not color.

### Alternative: TXU0202 (surface mount, non‑inverting)

If you have room for an MSOP/VSSOP‑8‑to‑DIP adapter, one TI TXU0202
(`TXU0202DCUR`, VSSOP‑8, 0.5 mm pitch) does both directions with levels
guaranteed by its datasheet. Set **`"invert": false`** in `config.json`.

| TXU0202 pin | Name | Connect to |
|---|---|---|
| 1 | B2 (input, 5 V side) | 1 kΩ from NES pin 3 (OUT0) |
| 2 | GND | Stick GND and NES pin 1 (GND) |
| 3 | VCCA | Stick 3V3, with 0.1 µF to GND |
| 4 | A2Y (output, 3.3 V side) | Stick G36 (RX) |
| 5 | A1 (input, 3.3 V side) | Stick G26 (TX) |
| 6 | OE | Stick 3V3. **Active high.** |
| 7 | VCCB | NES pin 5 (+5 V), with 0.1 µF to GND |
| 8 | B1Y (output, 5 V side) | 1 kΩ, then NES pin 4 (D0) |

- This pinout is for the `DCU` package (TI datasheet SCES942A, figure 6‑1).
  The SON and X2SON packages differ and are impractical by hand.
- Per the datasheet:
  - The A inputs read a high at 1.92 V or more at a 3 V supply.
  - The B inputs read a high at about 3.0 V at 5 V (2.74 V at 4.5 V, 3.33 V at
    5.5 V).
  - Both outputs go high‑impedance if either supply falls below 100 mV.
  - The supplies may come up in any order, and every input has a weak 5 MΩ
    pull‑down.
- G36 floats while the NES is off; an optional 100 kΩ from G36 to GND keeps
  it quiet.

### Alternative: two single‑gate buffers (surface mount, non‑inverting)

Two SOT‑23‑5 (0.95 mm pitch) buffers, each on its own SOT‑23‑5/6‑to‑DIP
adapter. Set **`"invert": false`** in `config.json`.

| Pin | TX: 74AHCT1G125, powered from NES pin 5 | RX: 74LVC1G125, powered from Stick 3V3 |
|---|---|---|
| 1 OE (active low) | GND | GND |
| 2 A | Stick G26 | 1 kΩ from NES OUT0, plus 100 kΩ to GND |
| 3 GND | common GND | common GND |
| 4 Y | 1 kΩ, then NES D0 | Stick G36 |
| 5 VCC | NES pin 5, with 0.1 µF to GND | Stick 3V3, with 0.1 µF to GND |

- Pinouts are for TI's `DBV` package, SN74AHCT1G125DBVR and SN74LVC1G125DBVR.
- The AHCT input needs only 2.0 V for a high, and its output swings to 5 V.
  Powered from the NES, it switches off with the console.
- LVC inputs tolerate 5.5 V even when unpowered and need only 2.0 V for a high
  at a 3.3 V supply. The 100 kΩ holds the input low when the NES is off.
- The DIP‑14 SN74AHCT125N can replace the TX part: use one gate, tie its OE
  low, and tie each unused gate's input to GND and its OE high.

**Not recommended:** a 1 kΩ series resistor plus 2 kΩ to GND on the RX side.
It only guarantees a high if OUT0 stays **at or above 3.7 V** under that
1.7 mA load, which is undocumented.

### Why a level shifter

**Stick → NES (D0).** On an NES‑001 front‑loader, D0 goes into a 74HC368
inverting buffer powered at 5 V. TI's SN74HC368 datasheet guarantees a high
only above 3.15 V at a 4.5 V supply and 4.2 V at 6 V, which is about 3.5 V at
the NES's 5 V. The ESP32 drives about 3.3 V (guaranteed only
0.8 × 3.3 V ≈ 2.64 V). Straight 3.3 V would probably work, because HC gates
typically switch near 2.5 V, but it would rely on typical behaviour rather than
the datasheet. A marginal level shows up as bad samples in the ROM's
cycle‑timed receiver. The top‑loader, Famicom, and PAL consoles have not been
checked.

**NES → Stick (OUT0).** OUT0 comes straight from the NES's 2A03 CPU with no
buffer, and how high that NMOS output stays under load is not documented. The
ESP32 is not 5 V tolerant and needs at least 0.75 × 3.3 V ≈ 2.48 V for a
guaranteed high. The FTDI cable working does not settle this, because the
FT232R's input switches at a lower voltage.

**Why NPN rather than MOSFET:** the through‑hole MOSFETs (2N7000, BS170) are
only guaranteed to switch fully on by around 3 V, which leaves no margin at
3.3 V. The BSS138 used on level‑shift boards switches reliably at 3.3 V but is
surface mount. A bipolar transistor needs only about 0.7 V on its base.

Sources: [TI TXU0202 datasheet](https://www.ti.com/lit/ds/symlink/txu0202.pdf),
[NESdev CPU pinout](https://www.nesdev.org/wiki/CPU_pinout),
[NESdev controller port pinout](https://www.nesdev.org/wiki/Controller_port_pinout),
[NESdev forum on the inverted '368 inputs](https://forums.nesdev.org/viewtopic.php?t=16734),
[raphnet NES VS mod (74HC368 at U7)](https://www.raphnet.net/electronique/nes_vs/nes_vs_en.php?section_id=5),
[TI SN74HC368 datasheet](https://www.ti.com/lit/ds/symlink/sn74hc368.pdf).

## Setup

1. **Check the firmware.** The Stick needs UIFlow 2.0.
   - If it shows the UIFlow launcher at power‑on, it already has it.
   - Otherwise, flash **UIFlow2.0 StickC Plus2** with M5Stack's
     [M5Burner](https://docs.m5stack.com/en/uiflow2/m5burner/intro).
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
3. **Deploy.** Connect the Stick by USB‑C, run `pip install mpremote`, then
   `tools/deploy.sh`. The script:
   - packs `airports.bin` from `server/src/data`;
   - saves UIFlow's own `/flash/main.py` as `/flash/main_uiflow.py`, the first
     time only;
   - copies NES Radar into `/flash`;
   - sets UIFlow to start NES Radar at power‑on instead of its launcher;
   - restarts the Stick.

   Re‑run it after a server airport‑data refresh to update the Stick's table.

   **"could not enter raw repl"?** Another app on the Stick is running and
   won't give up the REPL, so `mpremote` can't interrupt it. Erase the Stick's
   user files and deploy again:

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

NES Radar replaces UIFlow's launcher at power‑on. To get the launcher back,
restore UIFlow's `main.py` and its boot option:

```
mpremote exec "import os, esp32; os.rename('/flash/main_uiflow.py', '/flash/main.py'); n = esp32.NVS('uiflow'); n.set_u8('boot_option', 1); n.commit()" reset
```

This leaves NES Radar's files in `/flash`, so `tools/deploy.sh` switches back.

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

- **A** toggles the backlight, which saves battery.
- **Hold B (the side button) for 2 s** to power off, leaving TX at idle. On
  USB power the Stick stays on; unplug it first.

The ROM behaves the same way it does with the computer server. Rebooting the
Stick counts as a server restart, so reload the ROM afterwards, as the main
README describes.

Battery life with Wi‑Fi active is roughly 1.5–2 hours from the 200 mAh cell.
Use USB‑C for long sessions.

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
| `tests/` | parity, session, and MicroPython golden‑vector tests |

## Validation

Done offline:

- `python -m pytest firmware/stickc_plus2/tests`, with `server/requirements.txt`
  installed:
  - Encoders, reverse decoder, airport lookup, target conversion, and packet
    pacing are compared byte‑for‑byte with the desktop modules.
  - A virtual‑clock NES runs the full request → stream → pause → re‑select
    sequence. Its output is decoded with the desktop's own decoders and checked
    against the SIGNALING.md timing.
- With `MICROPYTHON=/path/to/micropython` set, the same golden vectors and
  session transcript are checked on the MicroPython unix port. This passed on
  v1.27.0, the version inside UIFlow 2.5.3, in both double and **single**
  precision; the ESP32 uses single.
- Every module compiles with MicroPython 1.27's `mpy-cross -march=xtensawin`.
- The UIFlow layer (`board.py`, `ui.py`, `device.py`) ran end to end on the
  unix port against stand‑in `M5`, `esp32`, `machine`, and `network` modules
  written from UIFlow's source. That checks the wiring, not the real `M5`
  behaviour.

Not yet done, and needed before this is more than experimental:

- [ ] The [bench tests](#bench-tests-dmm-and-scope) below, stages 1–6.
- [ ] Real NTSC console run: KSBA and KLAX for 30+ minutes each, on battery and
      on USB, including Select/airport changes, with no `LINK ERROR`.
- [ ] On UIFlow 2.5.3: `tools/deploy.sh` runs cleanly, the Stick boots
      straight into NES Radar, the status screen fits and is legible, A
      toggles the backlight, holding B powers off on battery, and
      [Going back to UIFlow](#going-back-to-uiflow) restores the launcher.
- [ ] Certificate verification with `ca.der`.

## Bench tests (DMM and scope)

These check the NPN shifter with a multimeter and a two‑channel scope; no logic
analyzer is needed. The two helper scripts run on the Stick through `mpremote`
after a normal deploy:

- `tools/tx_pattern.py` sends 0x55 every 20 ms. That is a 10‑bit square
  wave, easy to trigger on.
- `tools/rx_monitor.py` prints every byte received from the NES and decodes
  requests.

`mpremote run` interrupts NES Radar first, and `mpremote reset` restarts it
afterwards. Keep the Stick on USB power for the bench.

**Scope setup, unless a step says otherwise:** DC coupling, 2 V/div, ground
clip on NES pin 1 (GND), normal (not auto) trigger. A 9600‑baud bit is 104 µs
and one byte (10 bits) is 1.04 ms.

Write down every reading, including the ones marked *record*. They are the
measurements this design is missing.

### Stage 1: unpowered checks (DMM)

Before soldering, identify each transistor's leads with the DMM's diode test:
red on the base reads about 0.6–0.7 V to both the emitter and the collector,
and every reverse reading is open.

With everything unpowered and the NES cable plugged into port 2:

| Measure between | Expect |
|---|---|
| G26 and TX transistor base | 10 kΩ |
| TX collector and NES pin 4 (D0) | 1 kΩ |
| TX collector and NES pin 5 (+5 V) | 10 kΩ |
| NES pin 3 (OUT0) and RX transistor base | 10 kΩ |
| RX collector and G36 | 0 Ω |
| RX collector and Stick 3V3 | 10 kΩ |
| Stick GND and NES pin 1 | 0 Ω |
| NES pin 5 and each of Stick 5V IN, 5V OUT, 3V3, BAT | open (no continuity) |
| G0 and anything | open |

In‑circuit resistance readings can be a little off where a transistor junction
is in parallel. A reading near the expected value is fine. A short or an
open is not.

### Stage 2: Stick on, NES off (DMM)

Run the normal NES Radar deploy with the NES cable plugged in and the console
off. The Stick shows `WAITING`.

| Measure (to GND) | Expect | Why |
|---|---|---|
| G26 | about 0 V | the UART idles low with `"invert": true` |
| G36 | about 3.3 V | OUT0 is low, which the decoder treats as a break |
| NES pin 5 (+5 V) | below 0.1 V | nothing back‑powers the console |
| NES pin 4 (D0) | below 0.1 V | the D0 pull‑up gets its power from the NES |

If G26 idles near 3.3 V, `invert` is off in `config.json`, which is wrong for
this circuit.

### Stage 3: NES on, ROM in the airport editor (DMM)

| Measure (to GND) | Expect |
|---|---|
| NES pin 5 | 4.75–5.25 V (*record*) |
| NES pin 4 (D0) | within 0.2 V of pin 5: idle is high |
| NES pin 3 (OUT0) | near 0 V: the ROM rests OUT0 low |
| G36 | about 3.3 V |

Then **turn the Stick off**, leaving the NES on: unplug its USB, then hold B
for 2 s.

| Measure (to GND) | Expect |
|---|---|
| NES pin 4 (D0) | still within 0.2 V of pin 5 |
| Stick 3V3 pin | below 0.5 V (*record*): little leaks back into the powered‑down Stick |

### Stage 4: TX waveform (scope, `tx_pattern.py`)

NES on with the ROM in the airport editor, then `mpremote run tools/tx_pattern.py`.

- **Ch1 on NES pin 4 (D0), ch2 on G26.** Trigger on ch1's falling edge, 200 µs/div.
- **Ch1:** a burst of ten 104 µs bits alternating `L H L H L H L H L H`,
  starting low, repeating every 20 ms, and high between bursts.
  - High at least 4.5 V, low at most 0.4 V (*record both*).
  - Each bit 101–107 µs wide.
- **Ch2:** the exact inverse of ch1, swinging 0 to 3.3 V.
- **Rising edge on ch1:** at 1 µs/div, 10–90 % in under 2 µs (*record*).
  The 10 kΩ pull‑up makes it slower than the falling edge, as expected.
- **Wrong polarity:** if ch1 idles low, or the burst starts high, the
  `invert` setting does not match the hardware.

### Stage 5: RX waveform (scope, `rx_monitor.py`)

NES on with the ROM in the airport editor, then `mpremote run tools/rx_monitor.py`.

- **Ch1 on NES pin 3 (OUT0), ch2 on G36.** Trigger on ch1's rising edge,
  1 ms/div, single‑shot. Enter KSBA on the NES and press Start.
- **Ch1:** OUT0 rises from its resting low, stays high for about 0.85 ms, then
  carries about 7 ms of serial data.
  - *Record* OUT0's high level. It is the undocumented number that motivated
    this circuit; anything above about 1.5 V is enough here.
  - Zoom to 200 µs/div on the first byte (0x4E). It should read
    `L L H H H L L H L H`.
- **Ch2:** the inverse of ch1, low at most 0.3 V while OUT0 is high, about
  3.3 V otherwise.
- **The monitor prints** `rx … 4e 4b 53 42 41 f0 …` and `decoded: KSBA`.
  - *Record* whether `00` break bytes appear around the frame. The decoder
    accepts either.
- **Noise with no Start pressed:**
  - At 5 µs/div, OUT0 shows the ROM's roughly 2 µs controller‑strobe pulses
    at 60 Hz, and G36 may show matching dips a few µs wide.
  - *Record* the monitor's "byte(s) … outside decoded frames" count while the
    editor sits idle. Some noise bytes are acceptable. A missed or wrong
    `decoded:` line is not.

### Stage 6: full link (scope and console)

Run `mpremote reset`, then load the ROM and request KSBA (or KLAX for traffic).

- **Stick and console:** the Stick shows `STREAMING`. The console goes to
  `LINK IDLE`, then `LINK RECEIVING`, and never shows `LINK ERROR`.
- **Byte pacing:** ch1 on D0, 10 ms/div, trigger on the falling edge. During a
  packet, bytes start about 6 ms apart (1.04 ms of bits, then at least 5 ms
  high). After every 8th byte the gap is at least 30 ms.
- **Heartbeats:** about 6.1 s after a scene ends, single bytes start arriving
  every 25–27 ms. At 200 µs/div one of them (0x5A) reads `L L H L H H L H L H`.
- **Scene interval:** scene starts are 9.5 s apart. Use roll mode at 1 s/div,
  or watch the scene counter on the Stick.
