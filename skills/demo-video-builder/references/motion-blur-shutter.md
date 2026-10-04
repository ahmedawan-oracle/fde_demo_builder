# Motion blur by accumulation — `render_frames.js --shutter` (v5.1, default off)

A frame(t) scene renders every frame razor-sharp. A real camera does not: during a fast pan each frame integrates
the picture over the time the shutter is open, and the eye reads that smear as motion. Our renders are deterministic
and that must stay true, so the blur is built from real frames, not from a filter guessing a direction.

```
node render_frames.js scenes/film.html out/seg.mp4 39.0 30 96 3 --shutter 240       # or RENDER_SHUTTER=240
```

## What happens

- **Where.** Only inside windows where the picture was measured to move faster than **3 stage px per output frame**:
  `out/qa/camera_measured.json` (written by `gates/motion_diag.py` — the per-interval recovered shift and scale) is
  read and every interval above the threshold becomes a window. `RENDER_SHUTTER_WINDOWS=<json>` (`[{t0, t1, flow}]`)
  overrides it for a hand-chosen pass.
- **How many.** `k = min(48, 2·⌈flow / 3⌉)` sub-frames per blurred frame — a pure function of the measured flow, so two
  renders accumulate the same sub-frames.
- **When.** The k sub-frames are spread over the shutter angle: 240° = two thirds of the frame interval, each one a
  real `__seek` of the scene (so blocks, captions and the lane all move with it).
- **Averaged** by ffmpeg's `tmix` in integer arithmetic (the same inputs give the same mean) and handed to the output
  pipe as one JPEG like every other frame. The scene is left on the frame's own time afterwards.
- **Receipt.** `shutter: {deg, windows, frames_accumulated}` in the render receipt (and the take ledger).

Measured on the sample: a 1 s pass with one 0.3 s window at flow 12 accumulated 10 frames at k = 8 and cost 34 s
wall — the price is paid only where the camera moves.

## Rules

- Off by default. A product demo rarely wants it; a booth trailer with a hard push or a slide-through of cards does.
- Never on a hold window (`hold_gate` — nothing moves there) and never to hide a stutter (`seq quantized` catches
  the stutter; blur would only smear it).
- The determinism canary compares plain renders; a shutter render is compared with another shutter render.

Verified on the fictional sample: `--shutter 240` with a synthetic window → 30/30 frames, 10 accumulated, receipt filled.
