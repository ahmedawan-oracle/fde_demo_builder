# Deterministic render + narration as the clock (v3)

## The narration is the clock

1. Write the whole film's narration as one sequential SCENE in `vo_script.py` (phases back to back).
2. `python gen_vo_multivoice.py` renders it with edge-tts **WordBoundary** timestamps and writes
   `scenes/timing_<name>.js` (browser) + `scenes/timing_<name>_data.js` (node) + `vo/<name>_phases.json`.
3. Every event in the film is a spoken word: `wt('nb', 'counts')` = the moment "counts" is said in phase
   `nb`. Change a line, regenerate, and every cut, scroll and push moves with it.
4. `node check_cues.js …` fails the build if any cue silently falls back to its phase start (a typo, or a
   word edge-tts tokenised differently — hyphenated phrases arrive as one token, "Three" can come back
   as "free", acronyms may split into letters).

`pad` (lead-in before each phase) and `pause` (silence after a phrase) shape the rhythm without touching
the text.

## The scene contract

A scene is one HTML page with one pure function `frame(t)` of the film clock:

- `?render` in the URL → `body.pre` hides the stage until the first seek (no flash of unstyled frame 0).
- `window.__seek(t)` → full reset, draw t, return a Promise that resolves when every image is decoded.
- `window.__step(t)` → draw t sequentially (keeps caches), return the decode Promise.
- `window.__total` → film length.
- No `Date.now()`, no CSS animations, no transitions: everything is computed from `t`.

## Rendering

```bash
node render_frames.js scenes/film.html out/seg_film.mp4 33.2 30 96 3
```

Frame-by-frame, never real-time: each of N workers seeks once, then steps frame by frame, screenshots
(JPEG q96 at DPR 1.5 → 1920x1080) and pipes into its own ffmpeg (libx264 crf 17, CFR). Chunks are
joined losslessly. No dropped frames, no timing jitter, identical output every run, and frame 0 is
film time 0 (so audio offsets need no head-trim).

Needs `puppeteer` (bundled Chromium, `PUPPETEER_EXECUTABLE_PATH`, or a system Chrome).
