# Deterministic render + narration as the clock (v5)

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

## Software GL (v5)

Chrome is launched on the software rasteriser by default (`--use-gl=angle --use-angle=swiftshader
--enable-unsafe-swiftshader --disable-gpu`), so WebGL2 scenes (`lib/shaders.js`, `lib/title3d.js`) render the
same bytes on every machine. Measured 2026-10-02: a DOM shot in 80 ms (157 ms through the GPU process),
120/120 frames identical across two three-worker renders, hardware vs software frames different on every
frame — never mix the two paths in one film. `RENDER_GL=hardware` opts out for previews. Compositor-sync flags
(`--run-all-compositor-stages-before-draw --disable-checker-imaging --disable-threaded-animation
--disable-image-animation-resync`) are on by default so nested scaled layers (a staged lane, an arriving PiP)
are not captured mid re-raster; `RENDER_COMPOSITOR_SYNC=0` disables them. Every declared `@font-face` is
loaded and the first frame is captured until two captures agree (max 8 × 250 ms) — local fonts paint up to
~1 s late. The receipt (`{out, frames, fps, workers, chrome, gl, gl_renderer, errors, wall_s}`) records the GL
path so the canary can prove two renders used the same rasteriser. Scenes with a 3D title render with one worker.
GSAP scenes mount every timeline through `MOTION.block`; the ticker never runs (`motion-and-typography.md`).

## Capture settle, exact CFR and what used to break them (verified 2026-10-02)

The determinism verifier rendered the finished Acme sample (36.6 s, 1099 frames) twice with three workers
while the machine was busy and found **98 frames** that differed: a receipt pill still drawn one frame past
its exit, the glyph edges of a scrolling page, and a frosted panel's text rasterised at a different scale for
the panel's whole life. Three mechanisms, three rules — all in the renderer and the libs now:

- **Two animation frames after every step, before the capture.** `__step(t)` resolves when the DOM writes and
  image decodes are done, not when the compositor has committed and *activated* them, so an immediate
  screenshot can still show the previous frame's tiles. `render_frames.js` awaits
  `requestAnimationFrame(() => requestAnimationFrame(r))` between the step and `page.screenshot` (≈ 2 × 16 ms a
  frame). Measured under load: tail 30.9–31.6 s 2/22 differing frames → 0/22 with the wait; the whole film
  98/1099 → 46/1099 (the remainder was the panel below). The canary's probe waits the same way.
- **Never `will-change` in a scene or a lib.** A promoted layer whose transform changes rasters its content at a
  scale the compositor picks from how that transform has been changing, so a cold seek and a stepped run — or two
  renders under load — raster the same glyphs differently. Measured: the `lib/glass.js` panel settling .96 → 1
  with `will-change: transform, opacity` differed on 46/76 frames run to run; without it 0/76. Removed from
  glass.js, depth.js, light.js and annotate.js; `lint_scene.py` `will_change_layer` (error) refuses it in scenes
  and in `lib/*.js`. Blur, backdrop-filter and canvases are composited anyway — nothing in a `frame(t)` scene
  needs a hint. Same reason `force3D: false` is set on every GSAP tween.
- **The concat list states each part's `duration`.** Without it the concat demuxer offsets the next part by the
  mp4 header's millisecond-rounded duration (100 frames → 3.333 s, five ticks short at timescale 15360): pts
  3.333008, 3.366341 …, `avg_frame_rate 460800/15359`, and ffmpeg's `psnr` filter mis-pairs frames across the
  seam. `render_frames.js` writes `duration (i1 − i0)/FPS` under every `file` line: `avg_frame_rate 30/1`,
  duration exact, pixels identical to the previous encode.

With all three: two 3-worker renders of the sample running **concurrently** → **0/1099** differing frames
(`ffmpeg -f framemd5`), 275 s wall each (the unfixed sequential renders took 504–555 s under the same load).

Also measured and kept as rules:

- **Staging scales the lane with `transform: scale(k)`** (`#clipWrap` inside `STAGE.mount`). Do not switch to
  CSS `zoom`: geometry matches, but whole worker chunks differ run to run (18/54 frames, PSNR 37.7) because a
  zoomed lane rasters at a per-page scale. With `transform` the staged mini scene rendered 0/54 twice, with the
  compositor-sync flags on and off.
- **`gsap.set()` is a no-op under the paused clock.** The global timeline never ticks, so a zero-duration tween
  without `immediateRender` never renders (probe: the inline style still empty 600 ms and two rAFs later).
  Inside a block use `tl.set`; outside use `MOTION.set`, which writes at once. The live case was `typo.js`
  slam / heroWord pivoting about 50 % 50 % instead of 50 % 60 % / 50 % 70 %.
- **`MOTION.onSeek(fn)` is the per-frame hook.** GSAP suppresses `onUpdate` when a timeline is set by time, so a
  lib that must run code each frame (cursor, HUD) registers here instead of wrapping `MOTION.seek`.
- **One GL texture per picture, not per element.** `GL.texture` caches an `<img>` by `currentSrc`: the footage
  lane's `<img>` changes `src` every frame of a seq clip and keeps its size, so a per-element cache showed
  whichever frame the worker happened to upload first (chunk-boundary dependent).
- **`framemd5` of a 1-worker and a 3-worker render legitimately differ** (x264 chunk boundaries); compare
  decoded frames (`ffmpeg -i a.mp4 -i b.mp4 -lavfi psnr`) or run the canary. Two renders with the *same* worker
  count must match byte for byte.
- **Proof recipe.** Render twice with 3 workers *while the machine is busy* (or start both renders at once) and
  diff `ffmpeg -f framemd5`; a quiet machine hides compositor races. `gates/canary.py` samples 5–8 frames and
  snaps each requested time to the exact frame (`round(t·fps)/fps`, csv at six decimals) — a 3-decimal snap
  seeked 0.33 ms off the frame the stepped path ends on and reported a 43 dB phantom "seek parity" failure on
  a gliding title.
- Inside a cut-the-curve window two overlapping opacity ramps can differ cold vs stepped by ≤ 14 grey levels on
  the entering glyphs (PSNR 45, no pixel > 24): Chrome partial raster, not scene state. The canary's *invisible*
  verdict covers it; a chunk boundary inside such a window is still byte-stable run to run.
