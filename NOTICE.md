# Notices

fde_demo_builder is released under the MIT License (see LICENSE).

Parts of version 4 were inspired by, or re-implemented from, the open-source HyperFrames project
(https://github.com/heygen-com/hyperframes), licensed under the Apache License, Version 2.0. Doctrine and
measured rules were re-expressed in our own words; where a routine was ported rather than re-implemented,
the file carries an attribution line and is listed below.

## Ported routines (Apache-2.0, HeyGen / HyperFrames contributors)

<!-- implementers: append one line per ported routine: `- <plugin file>: <what was ported> (from <hyperframes path>)` -->
- skills/demo-video-builder/scripts/film/audio/carve_bed.py: candidate-band selection, intelligibility ranking penalty and strength->profile mapping (from packages/core/src/audioCarve.ts)
- skills/demo-video-builder/scripts/film/audio/beat_grid.py: energy-onset detection, median-IOI tempo, phase-fit grid and silence gate (from packages/core/src/beats/beatDetection.ts)
- `skills/demo-video-builder/scripts/film/lib/captions.js`, `lib/overlays.js`, `gates/overlay_gate.py`, `tools/captions_srt.py`,
  `references/captions-and-overlays.md` — caption grouping thresholds, the active-word envelope, lower-third / card motion
  timings, safe-zone and overflow measurement approach (visible text bbox walk, 2 px / 8 px tolerances) and the
  glyph-bbox contrast sampling idea are re-expressed from HyperFrames (Apache License 2.0,
  https://github.com/heygen-com/hyperframes). Code was re-implemented; no HyperFrames source or prose is copied.
- skills/demo-video-builder/scripts/film/lib/vfx.js, tools/grade.py, gates/grade_gate.py, references/vfx-and-grading.md (vfx area): adjust-grade maths constants (gain/shadow/highlight/levels/temperature/tint), signalstats analyzer thresholds, vignette/grain/bloom/glitch/wave-warp defaults, the fractal-noise 32-bit lattice hash constants, shader-seam shapes and speed-ramp lane maths (log interpolation, 48-cell trapezoid table) are re-expressed from HyperFrames (Apache License 2.0, packages/core/src/colorGrading.ts, mediaGradeAnalyzer.ts, speedRamp.ts, vfx/*.frag.ts, shader-transitions/src/shaders/registry.ts). Code re-implemented from scratch in Python/JS; no HyperFrames source or prose is copied.
- skills/demo-video-builder/scripts/film/lib/blocks.js: rank-baked bar-race row solver (10 keyframes per period, smoothstep swap over one interval, nice-step axis) and the critically damped camera spring (omega 6, 60 Hz x 4 substeps, read back by time) re-implemented after registry/blocks/bar-chart-race/bar-chart-race.html and registry/components/cursor-zoom-follow/cursor-zoom-follow.html; all other block envelopes (count-up, chat reveal, exploded stack, chart story, state rail, telemetry HUD, device stage, flash, lockup, CTA) are re-expressions of measured numbers only, no HyperFrames source or prose copied.
- skills/demo-video-builder/scripts/film/lib/camera.js, gates/motion_diag.py, references/camera-moves.md (camera area): the nudge-curve ratios (10/65/25 over 20/18/62), whip/streak blur envelope, punch / zoom / dwell / ease-law numbers, 88 % headroom and source-resolution budget, depth-of-field blur/dim values, dolly-zoom invariant P = subjectScale x d, caret-follow min() form, Lissajous idle ratios, freeze-hit timings and the onion-skin alpha ramp (0.14 -> 1.0) are re-expressed from HyperFrames doctrine (Apache License 2.0, skills/hyperframes-animation/rules/*, registry/blocks/*, packages/cli/src/commands/motionShot*.ts). All code re-implemented from scratch; no HyperFrames source or prose is copied.
