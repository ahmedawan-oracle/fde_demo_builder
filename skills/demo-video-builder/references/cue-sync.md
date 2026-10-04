# Cue sync — every sound proven on its frame after the mux (v5.1)

Placement is exact by construction (`audio/sfx_place.py` writes a sample-accurate stem). The mix, the limiter and the
mux are where a cue can drift — a resampler that pads, a concat that rounds, an encoder that trims a priming frame —
and nothing in the pipeline reported it. Code: `audio/cues_check.py`; gate `cue sync` in `gates/sfx_gate.py`.

## The check

```
python audio/cues_check.py --cues out/cues_film.json --film out/Acme_Film.mp4        # the finished audio
python audio/cues_check.py --cues out/cues_film.json --master out/master_film.wav
```

For every placed cue (`start`, `file` from `out/cues_<name>.json`) the SFX file is cross-correlated with the
finished audio inside a ±50 ms window around the planned start. Both signals are first-differenced (a one-pole
high-pass): the bed and the voice live under ~1 kHz, a transient's attack does not, so the correlation reads the
onset and not what hums under it. The peak is refined to a fraction of a sample (parabolic fit); its lag is the
measured offset. Over **1 ms** (48 samples) fails with the cue id, the planned and the measured start. A peak with
no prominence (< 4× the median) means the sound is not there — reported as *not found*. A riser is a swell and is
measured on its landing (the last 0.3 s of its file).

Measured on the fixture: exact cues read within 0.05 ms before the mux and within 0.1 ms after an AAC mux; a cue
moved 3 ms reads 3.0 ms both times. `qa.json "cue_tol_ms"` widens the limit with a reason.

## What it found first

On the fictional sample, both whooshes read **+4.98 ms** late with a 0.96 peak: the mastering limiter's 5 ms attack is a
look-ahead buffer that delays the whole mix — voice included — by 239 samples. Inaudible as sync, but exactly the kind of
constant that a build never reports. `build_film.py` now trims that latency off the front of the mix, and the gate reads
≈ 0 ms. A constant offset on every cue points at the chain; one cue off points at its placement.

## Beat snap for unanchored sounds (`sfx_place.py`)

A block landing sits on a spoken word; a seam sits on its cut; neither ever moves. A hand-placed moment in
`sync.json` with no word under it — a flash, an impact, a chapter mark, a climax, a reveal — is **unanchored**: when
the bed has a rhythmic grid (`out/beats_<name>.json`, `beats.rhythmic`) it snaps to the nearest beat if that beat is
within half a period. `"snap": false` on the point opts out, `"snap": true` forces it (any distance). The word guard
runs after the snap, so a snapped cue that lands within 0.15 s of a loud word is still nudged or dropped — words win,
the bed moves. The plan records `t_before_snap` and `snapped: true`.

Selftests: `python audio/cues_check.py --selftest` (synthetic bed + tone + three bursts, one 3 ms late; AAC round
trip) · `python audio/sfx_place.py --selftest` (an unanchored flash snaps to 3.0, `snap: false` stays, a landing never
moves) · `python gates/sfx_gate.py --selftest`.
