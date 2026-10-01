# Changelog

## 4.0.0 — HyperFrames-inspired production craft

v4 keeps everything v3 does and adds the craft that turns a clean demo into a film people remember. The ideas come from
HeyGen's open-source HyperFrames (Apache-2.0; see NOTICE.md), re-expressed for our real-pixel, narration-is-the-clock
pipeline. Everything still renders on your laptop; nothing needs an account or a cloud. The fictional "Acme Console"
sample passes all 51 gates end to end (`make_sample_recording.py` → `build_film.py` → `qa_film.py`).

- **Motion and seams.** `lib/seams.js`: velocity-matched seams (cut-the-curve, zoom-through and its inverse, waterfall,
  nudge/whip, rack-focus), waterfall entries, carriers. A `seams.json` ledger declares each cut; `gates/seam_gate.py`
  measures the rendered frames and fails any cut that stops early, mirrors direction, dissolves, or flashes white.
- **Camera.** `lib/camera.js`: punch-in/out, zoom-out reveal, focus pull, caret-follow, dolly zoom, pose ladder, drift-to-
  zero. `gates/motion_diag.py`: per-shot camera curves, zoom budget (≤ 88 % of frame, ≤ 2× source pixels), onion-skin sheet.
- **Captions and overlays.** `lib/captions.js`: a burned-in caption lane on the narration's own word times (drop / rail /
  embed, eight corporate presets, fit-text) that matches the SRT. `lib/overlays.js`: lower-thirds, stat cards, hero word,
  pull-quote, PiP frame, lockup, CTA close. `gates/overlay_gate.py`: safe zones, clipping, collisions, caption shape.
- **Audio.** `audio/carve_bed.py`: the bed ducks only in the bands the narration occupies; mono→stereo pan fix (+3 dB that
  `aformat` silently lost). `audio/voice_presets.py`: clean / broadcast / warm / telephone / PA chains and per-phase level
  match. `audio/beat_grid.py`: beats.json from a bed so cuts land on bars. `gates/audio_gate.py`: voice-over-bed ≥ 12 LU,
  duck depth, even voices, true peak.
- **QA and determinism.** `gates/lint_scene.py` (wall-clock code, CSS transitions, unseeded random, remote refs, fonts),
  `gates/canary.py` (render twice, compare hashes), `gates/snapshot.py` (golden frames + diff contact sheet),
  `tools/doctor.py` (ffmpeg / Node / Chrome / edge-tts / fonts / RAM / disk preflight, `--json`), `tools/fonts_localize.py`,
  `tools/audit_text.js` (overflow + WCAG contrast). Gates are plug-ins (`gates/*.py`, `GATE_NAMES` + `run(ctx)`);
  CREDIT always runs last and cannot be disabled.
- **Planning and review.** `templates/BRIEF.example.md` + `tools/brief.py` (message, audience, destination, what is real,
  stated-vs-inferred), `templates/STORYBOARD.example.md` + `tools/storyboard.py` (beat arithmetic against the narration,
  truthfulness tag per beat, storyboard.html sketch sheet), `templates/design.example.md`, `gates/text_gate.py` (words per
  second and per beat, on-screen text budget, hooks that open with table names).
- **Blocks.** `lib/blocks.js`: chat reveal with human typing rhythm, count-up that lands on the spoken number, state rail /
  HUD / agent tag, flash cut and freeze dressing, title lockup and dead-still close, focus zoom + click ring, the shared
  elastic envelope.
- **Media and export.** `tools/ledger.py` + `gates/ledger_gate.py`: every asset's source and licence in `media.jsonl`;
  the render refuses remote URLs. `tools/export.py`: booth loop, LinkedIn, YouTube, vertical, square, GIF teaser and a
  share pack from one master, each re-checked for the credit. `tools/timeline.py`: human-readable timeline.
  `templates/skin_tokens.example.json`: brand tokens for re-skins.
- **Finishing.** `lib/vfx.js`: vignette, seeded grain, bloom, matte reveal, haze — recreated scenes only. `tools/grade.py` +
  `gates/grade_gate.py`: levels/cast normalisation that proves product pixels were never recoloured.
- **Extractor.** Per-clip `"file"` (films that cut between recordings), `"fps"`, `"width"`, `--out`; `play.map` speed ramps
  in the footage lane.
- **Credit.** Unchanged and mandatory: "Crafted with FDE Demo Builder · by Ahmed Awan" on every output and every export.

## 3.0.0 — Production films

**New: v3 film workflow** (`/fde-demo-builder:new-film`, `scripts/film/`)
- **Real-pixel footage engine** (`extract_clips.py` + `lib/footage.js`):
  - Per-pixel median stills remove the pointer.
  - Tall pages are stitched from parked scroll positions, drawn inside the app's own full-screen chrome, with one chrome frame per position.
  - Real 30 fps motion clips.
  - Baked-in recording zooms can be inverted.
  - Demo-authored words can be repainted (auto cap height, ink and background).
  - `--word-ends` measures typed lines.
- **Original screen first, then the zoom**: each shot can open on the full screen with `establish` and push into your framing. `FOOT.fullscreen()` maps edits written in cropped views, and `abs` moves pull back to the whole screen.
- **Real typing and streaming**:
  - Typed glyphs are uncovered word by word on the narration clock, handing off seamlessly to the real send frames.
  - A curtain effect streams answers in.
- **Narration as the clock**: `lib/timeline.js` provides `wt(phase, word)`, and `check_cues.js` fails on any cue that doesn't resolve.
  - `gen_vo_multivoice.py` now emits a node timing twin.
  - It also supports `pad` (lead-in before a phase) and `pause` (silence after one).
- **Deterministic renderer** (`render_frames.js`): frame by frame, multi-worker, decode-aware `__seek`/`__step`, CFR, and frame 0 equals clock 0.
- **Build** (`build_film.py`):
  - Music bed sidechain-ducked under the voices, plus optional SFX.
  - Two-pass *linear* loudnorm to −16 LUFS / TP −1.5; the build refuses to ship if loudnorm falls back to dynamic.
  - Captions.
  - Mandatory credit.
- **14 QA gates** (`qa_film.py` + `qa.json`):
  - Relative cut detection, blank-after-cut, and freeze over 5 s measured at 640×360.
  - Loudness.
  - Required lines, over-claims (rendered text only), identifier hygiene.
  - Claims traced to the screen (`claims.json`).
  - Captions and CREDIT.
- **Runnable out of the box**: `make_sample_recording.py` generates a fictional "Acme Console" capture. The example film passes all 14 gates.
- **New references**: `real-pixel-footage`, `deterministic-render`, `cinematic-grammar`, `honesty-audit`, `audio-mix`, `credit-footer`.

**New: mandatory end-screen credit** (all workflows)
- `credit.py` stamps **"Crafted with FDE Demo Builder · by Ahmed Awan"**:
  - Small and centred in the footer.
  - Shown over the last 4 s, with a fade-in.
  - Automatically light or dark to suit the end screen.
- It also verifies the stamp by correlating the end frame against the credit's glyphs.
- The stamp and check are wired into v1 `build.py`, v2 `assemble.example.sh` and v3 `build_film.py`. The `CREDIT` QA gate and the `demo-qa-reviewer` agent treat a missing credit as a BLOCKER.

**Changed**
- Privacy guidance: mask private data, not the product. Ask before masking code.
- `requirements.txt` adds `pillow` and `numpy`.

## 2.0.0 — Story rebuilds
B-roll story scenes and multi-voice narration (`gen_vo_multivoice.py`, `render_scene.js`, `shot.js`, `/new-broll`).

## 0.1.0 — First release
Beats, lag cutting, privacy scrubbing and VO sync (`demo_config.py`, `gen_vo.py`, `build.py`), `/new-demo`, and the `demo-qa-reviewer` agent.
