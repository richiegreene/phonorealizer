# Phonorealism Perform

A browser-based in-ear monitoring system for ensembles playing highly specific
spectral music. Each performer opens a page on their own phone, claims a part,
and gets two things at once: their line re-synthesised into their earbuds, and a
scrolling display comparing what they are actually playing — pitch and amplitude,
from their microphone — against what is written.

The conductor loads the score, watches the ensemble assemble, and starts the
downbeat for everyone simultaneously.

This is the browser counterpart to the desktop `Perform` window in
[`phonorealism_modifier`](../phonorealism_modifier), and it reads the same
material: **justidraw `.sav`** files (the current workflow) and **phonorealizer
CSV**.

---

## The one thing to understand

**Nothing streams between devices.** Once the downbeat lands, every phone plays
its part from its own `AudioContext` clock and no further packets matter.

So this is not a streaming problem, it is a *clock synchronisation* problem. The
hub's only real job is to hand out a single timestamp. Each device measures its
offset from the hub by round-trip probing and keeps the sample with the **lowest**
observed RTT — a fast round trip is one that queued behind nothing in either
direction, so it is also the most symmetric, and symmetry is exactly what the
`offset = tServer − (t0+t1)/2` estimator assumes.

Your downbeat error is therefore about **half the minimum RTT**, not the average
latency:

| network | min RTT | downbeat spread |
| --- | --- | --- |
| LAN Wi-Fi | 3–15 ms | ±2–7 ms (inaudible, ≈2 m of air) |
| internet, hub in region | 20–60 ms | ±10–30 ms (slight flam at the edges) |
| congested / distant | 100 ms+ | ±50 ms+ (audibly ragged) |

Both the conductor's screen and each performer's header show the measured figure
live, so you can tell whether tonight's network is good enough **before** you
start rather than after.

---

## Running it

### Default: your own domain, via Cloudflare Tunnel

The hub runs on your laptop; `cloudflared` publishes it at your domain with a
real certificate. Costs nothing, and the server stays in the room with you.

```bash
cd phonorealism_web
./run.command                      # hub on http://localhost:8000

# in another terminal
cloudflared tunnel --url http://localhost:8000
```

Point the tunnel at your hostname and give performers `https://your.domain/performer`
— the QR code on the conductor page encodes whatever URL you are actually served
over.

### Offline fallback: LAN with a self-signed certificate

For a venue with no usable internet. Works off a travel router or a phone
hotspot with no upstream connection at all.

```bash
./run.command --tls                # https on :8443, cert generated on first run
```

Each performer will have to tap through a browser certificate warning once.

### Why one of those two is mandatory

`getUserMedia()` only runs in a **secure context**. `http://192.168.1.5:8000` on a
phone will **never** be granted a microphone, in any browser, regardless of
settings. This is the single biggest practical obstacle to a LAN setup and the
reason the hosted path is the default. Both the conductor page and the performer
page detect an insecure origin and say so plainly rather than failing at the
microphone prompt.

---

## Score formats

### justidraw `.sav`

Read directly — a JS implementation of Calvin Rose's **binser** format lives in
[`static/js/lib/binser.js`](static/js/lib/binser.js). The unit mappings, verified
against a round-tripped export of `lowlands_test` (51,680 vertices / 32 partials):

```
time (s)  = x * 60 / (400 * bpm)     playhead advances 4*100*bpm/(60*sr) per sample
freq (Hz) = 440 * 2^(-y / 1200)      y is negative cents from A440
amplitude = w                        see "amplitude response" below
```

A justidraw track is a flat vertex list linked into curves by `l`/`r`, so each
linked chain becomes one partial. Note that this nests one level deeper per
vertex, which is why the reader is an explicit state machine — a recursive parser
overflows the stack long before 51,680 vertices.

> `.sav` is ambiguous in this project: justidraw writes binser binary, while the
> modifier's Tessera export writes a Lua source table under the same extension.
> The loader sniffs the first byte and tells you which one you handed it.

### phonorealizer CSV

`time,frequency,amplitude,harmonic_index`. Amplitude is auto-detected as linear
or dBFS.

### Partial numbering is canonical, not as-filed

The two formats disagree about ordering. A justidraw export comes out in
frequency order; the CSV carries SPEAR's `harmonic_index`, which is a tracking id
in essentially arbitrary order. The same music produces the same 32 frequencies
either way, but numbered differently.

**Partials are therefore renumbered by ascending median frequency on load**, so
partial 1 is always the lowest and "you're on partial 7" survives a re-export.

### Amplitude response

The phonorealizer export writes justidraw's `w` = linear amplitude straight from
the spectral analysis, but justidraw's own synth plays `w` through
`amp_curve(x) = x²`. The conductor chooses:

- **As notated (`w`)** — what the composer wrote, and what a performer should be
  held to. Default.
- **As justidraw sounds it (`w²`)** — makes the displayed envelope match what you
  hear when you press play in justidraw.

### Octave convention — check this

The desktop Perform window doubles the live microphone pitch before comparing it
to the score (`freqs * 2`), and the exporter halves frequencies when synthesising
— meaning in that workflow players sound an **octave below** the written
frequency. justidraw takes the same numbers literally.

That factor of two is **not** assumed here. If your scores use it, set
*Setup → Octave → Down one octave*, which transposes both the in-ear reference
and the pitch you are measured against together.

---

## Using it

**Conductor** (`/conductor`) — load a `.sav` or `.csv`; it is parsed in the
browser and uploaded to the hub. Group partials into named parts ("Violin 1" =
`3, 7, 12-14`), export the part map as JSON to reuse next rehearsal. Watch the
readiness grid: who has claimed what, whose microphone is live, each device's
sync quality, and each player's live cent deviation. Start stays enabled at your
discretion — an unready player is reported, never a veto.

**Performer** (`/performer`) — pick your part, enable the microphone, calibrate,
tap ready. Then wait; the conductor starts everyone together.

- **Balance** crossfades between your own line and the rest of the ensemble.
  Equal-power, so the midpoint does not dip.
- **Pitch span / mode** — `follow` centres on your notated pitch for intonation
  work and widens automatically to keep all of your own partials on screen;
  `range` fits the part's whole contour.
- **Search band** keeps the pitch tracker locked to your partial instead of
  jumping to a louder neighbour. This matters: phonorealism parts are often quiet
  high partials sitting under something much louder. Narrow is safer; widen it
  when you want to see how far off you really are.

Calibration exists because the score's amplitude is a normalised spectral
magnitude while your microphone's RMS depends on your instrument, your distance
and your phone. The two are not comparable until anchored, so you are asked for
your loudest sustained tone.

---

## Accuracy and limits

**Pitch tracking** is FFT peak-picking with parabolic interpolation across the
peak, at fftSize 8192 (~170 ms at 48 kHz). Interpolation is what makes it usable
— measured against synthetic tones deliberately placed between bins:

```
608.04 Hz -> 608.00 Hz   0.10¢   (raw bin index: 3.8¢)
  440 Hz  -> 440.02 Hz   0.07¢   (raw bin index: 2.2¢)
 3040.2 Hz-> 3040.17 Hz  0.02¢   (raw bin index: 0.5¢)
```

Worst case under a cent. The 170 ms window trades time resolution for frequency
resolution, which suits sustained spectral material and would not suit fast
passagework.

Echo cancellation, noise suppression and auto gain control are all explicitly
disabled — AGC would flatten the very dynamics being measured, noise suppression
is trained on speech and treats a sustained high partial as noise, and echo
cancellation would try to subtract the in-ear reference from the signal.

**Pre-rendering** the monitor mix costs roughly 0.6 s per 19 s of score on a
laptop and perhaps 6× that on a phone, so a long score takes visible seconds. It
happens when a performer taps *ready*, not at the downbeat, and is reported in the
UI. Playback is capped at 5 minutes, and if both mixes would exceed a 96 MB
buffer budget the ensemble mix is dropped rather than risking an out-of-memory
kill mid-rehearsal — the performer is told.

**Known limits**

- Phone microphones roll off steeply above ~15 kHz. High partials of a dense
  spectrum may not be trackable on cheap hardware at all.
- Bluetooth earbuds add 150–250 ms of output latency. This is compensated via
  `getOutputTimestamp()` where the browser provides it, but wired is safer.
- The hub keeps state in memory plus a cached `data/score.json`, so it survives a
  restart mid-rehearsal. It is not multi-session: one hub, one ensemble.
- There is no authentication. Anyone who can reach the URL can claim a part.
  Fine on a LAN; think before leaving a public tunnel running.

---

## Layout

```
server/hub.py            clock probes, session state, score distribution, static serving
static/js/
  lib/binser.js          justidraw .sav reader (iterative — see above)
  score.js               both formats -> one normalised model; canonical numbering
  net.js                 WebSocket + the clock estimator
  analyser.js            microphone pitch/amplitude; peakFrequency() is pure and testable
  synth.js               monitor mix, scheduling, buffer budget
  render-worker.js       additive re-synthesis off the main thread
  render.js              the scrolling display
  performer.js / conductor.js
```

The score parsers run **only in the browser**, so there is exactly one
implementation of each format; the hub just stores and forwards the normalised
JSON (gzipped, ~1.2 MB → ~300 KB for the test score).
