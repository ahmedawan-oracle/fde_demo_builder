# Pilot — judge two variants as a cut (v5.1)

A look, a skin or a choreography is never decided on a still. What decides it is how three or four shots cut
together: the rhythm, whether the seam reads, how the type sits on the footage. `tools/pilot.py` renders the same
shots from two scene variants, cuts each set into a sequence and stacks the two on one clock.

```
python tools/pilot.py scenes/film.html "scenes/film.html?skin=cobalt" --shots 3-6
python tools/pilot.py scenes/film.html scenes/film_b.html --windows "13.6-21.8,21.8-26.5" --labels harbor,cobalt
python tools/pilot.py --from-renders out/a.mp4 out/b.mp4 --shots 3-6          # two existing films, ffmpeg only
```

- **A and B** are scene files or the same scene with a query (`?skin=…`); `--shots` are 1-based indices into
  `out/timeline.json shots[]`, `--windows` explicit spans. Both variants are rendered through `render_frames.js` to
  the end of the last window, so the frame times are shared.
- **The cut.** Each variant's windows are trimmed and joined in order with the film clock burned in (seconds of the
  original film, so "B wins at 15.2" names the same instant in both).
- **The stack.** A above, B below, each at 960×540, labelled → `out/pilot.mp4` (960×1080 — reads on a phone) with
  `out/pilot_sheet.jpg` (one tile per second, A row over B row) and `out/pilot.json` (windows, frames, length).
- **The decision** is written where decisions live: `STORYBOARD.md ## Decisions` — which variant, and why, in one
  line. Price the pipeline, not the clip: both variants paid the same render and are read in the same minute.

Selftest: `python tools/pilot.py --selftest` — two synthetic films (cool and warm) through `--from-renders`, two
windows, 105 frames at 960×1080, A on top, the sheet and the record written. Rendering A and B needs Chrome.
