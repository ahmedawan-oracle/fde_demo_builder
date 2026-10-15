# Audio mix and master (v3)

`build_film.py` does all of this; the notes explain the numbers.

## Mix

- Narration at unity, split with `asplit` so one copy keys the sidechain.
- Optional music bed at about −9 dB, faded in 1.5 s and out 3 s, **ducked under the voices** with
  `sidechaincompress=threshold=0.04:ratio=4:attack=20:release=500`. Use licensed or royalty-free music
  (keep the licence with the project); never copy another company's soundtrack.
- Optional SFX track (typing keys, clicks) at about −5 dB, generated from the same word timings.

## Master: two-pass linear loudnorm

Targets: **−16 LUFS integrated, true peak ≤ −1.5 dBTP, LRA 11**. Linear normalisation keeps the mix's
dynamics; dynamic fallback pumps the music. It only stays linear if the mix arrives close to target with
peak headroom, so:

1. Render the raw mix, measure it.
2. Re-render with a pre-gain that lands ~0.45 LU above target and a sample-peak limiter ~0.8 dB under the
   true-peak ceiling.
3. Pass 1 measures, pass 2 applies with `linear=true`. The build **refuses** to ship if the report says
   `dynamic`.

## QA

For a short pilot with a deliberately quiet tail, measured LRA can exceed 11 even when the mix is healthy.
An explicit `film.json` `loudness_range` in 1..50 LU changes that mastering target (default stays 11).
Use FFmpeg 6+ for the full range; older FFmpeg releases may only support values up to 20.
Inspect the measured range and audition the mix before increasing it; do not use it to conceal pumping or
to bypass the linear-only master check. Final loudness and true-peak limits are unchanged.

The momentary gate preserves non-finite digital-silence windows only after checking the same filtered PCM
per channel. A failed measurement or non-silent/non-finite PCM still fails; never drop windows or loosen
ducking thresholds to make a shifted timeline pass. Level-match cast members before assembly, then recheck
actual final mixed speech, handoffs, bed recovery and cue audibility after every audio edit.
The LRA override applies to the primary master; export presets retain their separately defined mastering
targets. Inspect and validate exported audio independently, including any short-pilot export.
The frame-preservation guard covers the primary master, including optional credit stamping; transformed
export presets have independent timing and still require their own final-frame and duration checks.

Mux to the narration clock plus tail, not `-shortest`: AAC packet rounding can drop the final picture frame.
Check decoded frame count, duration and the actual last frame of the delivered MP4, not just its source segment.

`qa_film.py` gate 8: −17 … −15 LUFS and TP ≤ −1 dBTP on the final file. Also listen once end to end on
laptop speakers; booth screens are loud rooms.
