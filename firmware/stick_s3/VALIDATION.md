# NES Radar on an M5StickS3 or M5StickC Plus2: validation

What has and hasn't been checked on the Stick host described in the
[README](README.md), and the bench procedure for checking the level shifter.

## Status

The deploy and UIFlow checks listed below first passed on a StickC Plus2 with
UIFlow 2.5.3 (tag `stickc-plus2-final`), and have since been repeated on a
StickS3. The Plus2 ran them with TX on G26; it now sends on G0, the same hat
slot as the StickS3's TX, and has been checked there too (below).

Done offline:

- `python -m pytest firmware/stick_s3/tests`, with `server/requirements.txt`
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
  written from UIFlow's source (on the Plus2 version). That checks the wiring,
  not the real `M5` behaviour. `tests/test_board.py` checks each board's
  link pins and the board guard the same way on CPython.

Done on hardware, with the NPN shifter and its 100 kΩ RX base resistor:

- The link works on a real NES.
- The link works on the MiSTer NES core through a 2‑player NES SNAC adapter,
  with the Stick on port 2, and controller 1 still responds. With the
  original 10 kΩ RX base resistor, both controllers stopped responding. The
  NPN shifter's "How it works" explains why.
- The [bench tests](#bench-tests-dmm-and-scope) below, stages 1–6, pass on
  the built PCB: the voltage levels are in range and the waveforms look
  correct.
- On a StickS3: `M5.getBoard()` reports `M5StickS3`, the Proto Hat seats on
  the Hat2 odd row, 3V3_L2 stays on while running, and the battery gauge
  works.
- On the StickS3's UIFlow 2.0: `tools/deploy.sh` runs cleanly (also from the
  UIFlow launcher and after `erase_apps.py`), the Stick boots straight into
  NES Radar and joins the saved Wi‑Fi, the status screen is legible, A resets
  the server, B toggles the backlight, holding B powers off, and
  [Going back to UIFlow](README.md#going-back-to-uiflow) restores the
  launcher.
- On a StickC Plus2 on its new pins (G0 TX, G36 RX): the link works on a real
  NES and on the MiSTer NES core, with the shifter on a breadboard rewired to
  the hat's slots and with the nesp32 hat PCB.

Not yet done, and needed before this is more than experimental:

- [ ] Real NTSC console run: KSBA and KLAX for 30+ minutes each, on battery and
      on USB, including Select/airport changes, with no `LINK ERROR`.
- [ ] Certificate verification with `ca.der`.

## Bench tests (DMM and scope)

The pins below are the StickS3's. On a StickC Plus2 read G8 as G0, G1 as
G36, 3V3_L2 as 3V3 and EXT_5V as 5V OUT; slot 3 is G26 there, still left
open, and G0 is the TX pin, so the checks that nothing reaches G0 don't
apply. The Plus2 must still boot into NES Radar with the hat on.

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
| G8 and TX transistor base | 10 kΩ |
| TX collector and NES pin 4 (D0) | 1 kΩ |
| TX collector and NES pin 5 (+5 V) | 10 kΩ |
| NES pin 3 (OUT0) and RX transistor base | 100 kΩ |
| RX collector and G1 | 0 Ω |
| RX collector and Stick 3V3_L2 | 10 kΩ |
| Stick GND and NES pin 1 | 0 Ω |
| NES pin 5 and each of Stick 5V_IN, EXT_5V, 3V3_L2, BAT | open (no continuity) |
| G0 (slot 3) and anything | open |

In‑circuit resistance readings can be a little off where a transistor junction
is in parallel. A reading near the expected value is fine. A short or an
open is not.

### Stage 2: Stick on, NES off (DMM)

Run the normal NES Radar deploy with the NES cable plugged in and the console
off. The Stick shows `WAITING`.

| Measure (to GND) | Expect | Why |
|---|---|---|
| G8 | about 0 V | the UART idles low with `"invert": true` |
| G1 | about 3.3 V | OUT0 is low, which the decoder treats as a break |
| NES pin 5 (+5 V) | below 0.1 V | nothing back‑powers the console |
| NES pin 4 (D0) | below 0.1 V | the D0 pull‑up gets its power from the NES |

If G8 idles near 3.3 V, `invert` is off in `config.json`, which is wrong for
this circuit.

### Stage 3: NES on, ROM in the airport editor (DMM)

| Measure (to GND) | Expect |
|---|---|
| NES pin 5 | 4.75–5.25 V (*record*) |
| NES pin 4 (D0) | within 0.2 V of pin 5: idle is high |
| NES pin 3 (OUT0) | near 0 V: the ROM rests OUT0 low |
| G1 | about 3.3 V |

Then power‑cycle the Stick with the NES still on. It must boot into NES Radar,
not download mode, which confirms nothing reaches G0.

Then **turn the Stick off**, leaving the NES on: unplug its USB, then hold B
for 2 s.

| Measure (to GND) | Expect |
|---|---|
| NES pin 4 (D0) | still within 0.2 V of pin 5 |
| Stick 3V3_L2 pin | below 0.5 V (*record*): little leaks back into the powered‑down Stick |

### Stage 4: TX waveform (scope, `tx_pattern.py`)

NES on with the ROM in the airport editor, then `mpremote run tools/tx_pattern.py`.

- **Ch1 on NES pin 4 (D0), ch2 on G8.** Trigger on ch1's falling edge, 200 µs/div.
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

- **Ch1 on NES pin 3 (OUT0), ch2 on G1.** Trigger on ch1's rising edge,
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
    at 60 Hz, and G1 may show matching dips a few µs wide.
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
