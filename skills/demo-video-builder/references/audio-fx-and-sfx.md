# Sound design without a sample pack — `audio/sfx_synth.py`, `sfx_place.py`, `fx_chain.py`, `envelope.py`

Every sound in a film is synthesized on the machine from a short physical description, placed on the
narration clock by rule, and mixed through a declared chain. Nothing is sampled, nothing is licensed, and two
builds of the same film produce byte-identical audio. The carve and the beat grid are in
`audio-carve-and-beats.md`; this page is the layer on top.

## 1. The set — `audio/sfx_synth.py`

`python audio/sfx_synth.py --out audio/sfx` writes thirteen 48 kHz 24-bit files plus `manifest.json`
(`name, dur, peak_dbfs, align, use, md5`). Every file peaks at −6 dBFS (±0.05 measured) so level is decided
once, at the bus. `align` is the instant inside the file that must land on the cue time.

| sound | how it is made | lands on |
|---|---|---|
| whoosh 0.35 s | white noise through a state-variable band-pass sweeping 400 → 4 kHz (Q 4) under a Hann; peak at 0.175 s | a cut, a camera move |
| tick 45 ms | 2 ms half-sine impulse + 1.2 kHz ring (τ 6 ms) | a count-up landing, a send |
| snap 0.25 s | sine dropping 180 → 60 Hz (τ 70 ms) + 40 ms 2–6 kHz burst | a flash, a cut with cause |
| impact-low 0.6 s | 45 Hz thump (τ 0.12 s) + 5 ms click for small speakers; dead by 0.52 s | act open / chapter, one per act |
| riser N s | noise band rising 400 → 6 kHz, swell −30 → 0 dB exponential, 10 ms fade, dead at N | the climax: its END is the cue |
| shimmer 0.8 s | six partials 2000·2^(k/5) as ±0.35 % detuned pairs, τ 0.28 s | data arriving, a reveal |
| ui-confirm 0.12 s | 880 then 1320 Hz, 60 ms each, 5 ms raised-cosine edges | a receipt stamp, an answer landed |
| key-0..5 30 ms | 1.5 ms noise impulse band-passed at a centre drawn per key in 2.2–4.8 kHz + 300 Hz body (τ 8 ms), ±1.5 dB | typewriter, rotated per keystroke |

The sweeping filter is stepped per sample: its state is the physical signal, so a moving centre frequency
never clicks. Change a recipe and only that file's md5 changes. `sfx_place.ensure_sfx()` rebuilds the set when
`manifest.json` is missing; the generated WAVs are never committed.

## 2. Placing — `audio/sfx_place.py`

Cues come from three places and are never invented:

- **seams** — every cut in `out/timeline.json` (or a numeric `seams.json`) is a whoosh; a cut whose `cause` is
  `impact` or `chapter` is an impact-low. The row's `act` is kept.
- **sync points** — blocks return `sync()` (`BL2.countUp` → land; `chatReveal` → send, stream, answered); the
  scene pushes them to `window.__sync` as `'<block>:<kind>'` with `kind` / `act`; `export_timeline.js` writes
  them into `out/timeline.json`. Hand-authored moments live in `sync.json`:
  `{"points":[{"t":41.2,"kind":"flash","id":"reveal:flash","act":"demo"}]}`. Kinds: cut, impact, chapter, flash,
  land, send, reveal, stamp, receipt, confirm, answer-landed, key, climax; stream and none are silent;
  `"sfx": "shimmer"` names a sound outright; `"force": true` keeps a cue the word guard would drop.
- **beats** — only a point flagged `"snap": true` moves to the nearest beat, and only on a rhythmic grid.
  Words win; the bed moves.

Rules, with the numbers behind them:

- **Level.** Bus gain −14 dB on −6 dBFS files puts an isolated cue at −20 dBFS (measured). A booth narration
  peaks at −8 dBFS on the median 150 ms window, so a transient reads without touching a word; under a
  −30 LUFS bed seven cues add 0.7 LU integrated. (The −14 dB is a bus gain relative to the files, not to the bed.)
- **Word guard.** No transient within 0.15 s of a word onset whose 150 ms peak is above −20 dBFS (98 % of real
  words). A colliding cue is nudged earlier in 10 ms steps up to 0.12 s, then later up to 0.04 s (early is
  forgiven, late barely), otherwise dropped and listed. Dense narration (a word every 0.4 s) leaves ~0.1 s
  windows — expect drops; silence beats a masked word.
- **Riser.** A swell, not a transient: never moved, only its landing is checked; start = climax − length.
- **Stacking.** Two transients inside 0.08 s mask each other; priority impact > snap > whoosh > ui-confirm >
  shimmer > tick > key decides which stays. Keys may cluster with keys.
- **Acts.** One impact per act; the second is demoted to a snap and reported.

```
python audio/sfx_place.py --timeline out/timeline.json --sync sync.json --words vo/<name>_words.json \
       --phases vo/<name>_phases.json --vo vo_<name>.mp3 --render out/sfx_<name>.wav --json out/cues_<name>.json
```

`--render` writes a sample-accurate stereo stem (constant-power pan; a whoosh leans 0.25 toward the side new
content enters); `build_film.py` mixes it as `sfx` with `sfx_db: 0`. The equivalent `adelay` / `amix` fragment
is printed for graphs that prefer the files. Exit 1 when anything dropped — move the cue in the scene, never
the word.

## 3. Bus chains — `audio/fx_chain.py`

A chain is a JSON list of stages; the tool prints one `[in]…[out]` fragment, runs it, and measures
before/after (ebur128 I, LRA, sample peak; 5–8 kHz RMS). Presets:

- **voice-booth** — highpass 80 Hz; de-esser 5–8 kHz (−30 dB, 4:1, 1/60 ms); −2 dB @ 250 Hz, +1.5 dB @ 3 kHz;
  compressor −20 dB 3:1 10/150 ms +3 dB; gate −45 dB closing 12 dB; limiter −1 dBFS.
- **bed-under-voice** — highpass 40 Hz; −3 dB @ 2.5 kHz Q 1.2 (a static bias under the carve); compressor
  −24 dB 2:1 30/400 ms; widen 1.25; limiter −3 dBFS.
- **sfx-tight** — highpass 30 Hz (keeps the 45 Hz thump); compressor −18 dB 4:1 2/80 ms; limiter −3 dBFS.

ffmpeg has no de-esser, so it is built: `acrossover` splits at 5 and 8 kHz (4th order, sums flat within
0.1 LU), only the middle band is compressed, `amix normalize=0` reassembles. Measured on the selftest voice:
5–8 kHz RMS −2.5 dB for −0.2 LU full-band; the whole voice-booth preset −2.2 LU, peak 0 → −7.6 dBFS, LRA
0.5 → 0.1. Echo and widen are refused on the voice bus. `film.json`:
`"fx": {"buses": {"voice": {"preset": "voice-booth"}, "bed": {"preset": "bed-under-voice"}, "sfx": {"preset": "sfx-tight"}}}`.

## 4. Automation — `audio/envelope.py`

The bed's deliberate moves are keyframes `{t, db}`, not a compressor: a **breathe** at every seam (−3 dB
arriving at the cut, 0.4 s lead, 0.1 s hold, 1.2 s recovery = 2.5 dB/s) and a **swell** under the riser
(−6 → 0 dB landing on the climax, with a 1 s settle before it). Ramps are limited to 6 dB/s: a down-ramp
starts earlier (the duck leads, like the carve), an up-ramp ends later; a blocked stretch is reported, never
silently clipped (a 24 dB/s request becomes a 2.0 s lead-in). Where lists overlap the lower level wins.
Output as a `volume=` expression (21 ms frames, 0.13 dB steps), a sendcmd file, or a float32 gain WAV for
`[bed][env]amultiply` — sample-exact, the form the build uses. Verified: ffmpeg renders the expression dip
to −3.0 dB within 0.4 dB at the seam.

```
python audio/envelope.py --seams out/timeline.json --breathe -3 --swell <climax_t> --total <T> --wav out/bedenv_<name>.wav --json out/env_<name>.json
```

`film.json`: `"sfx": "out/sfx_<name>.wav", "sfx_db": 0, "bed_env": "out/bedenv_<name>.wav"`.

## Checklist and gates

1. `sfx_synth --out audio/sfx` (once; regenerated automatically if missing).
2. Publish block sync points; write `sync.json` for flash / stamp / climax.
3. `sfx_place … --render … --json …`; read the dropped list.
4. `envelope --seams out/timeline.json --breathe -3 --swell <climax> --total <T> --wav …`.
5. Chains by bus in `film.json → fx`; read the before/after numbers in the reports.

Gates (`sfx_gate`): `sfx word-safe` (every cue except the riser ≥ 0.15 s from every loud word onset; drops are
a WARN detail) · `sfx one impact` (one impact-low per act; a second is demoted) · `sfx level` (stem peak between
−24 and −16 dBFS; the stem adds 0.1–3 LU to the bed). qa.json keys:
`sfx_guard_s` 0.15, `sfx_peak_min` −24, `sfx_peak_max` −16, `sfx_lu_min` 0.1, `sfx_lu_max` 3.0. Selftests on all
four tools run under 60 s even on a loaded machine (`sfx_synth` 7–20 s, `sfx_place` 11–26 s).
