# Changelog

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
