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

`qa_film.py` gate 8: −17 … −15 LUFS and TP ≤ −1 dBTP on the final file. Also listen once end to end on
laptop speakers; booth screens are loud rooms.
