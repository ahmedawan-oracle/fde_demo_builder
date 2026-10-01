# FDE Demo Builder

A Claude Code plugin that turns a **raw screen recording** of a product/customer demo into a
**polished, voice‑narrated, privacy‑scrubbed demo video** — with an optional animated opener/outro —
**entirely from scripts**. No video editor, no manual timeline. Edit a config, run one command, get a
shareable `.mp4`.

## What it does

Given one screen recording, the pipeline:

1. **Maps** the recording into named "beats" (setup, question 1, answer 1, …).
2. **Cuts the dead air** — the "thinking…", spinner, and loading lags between actions.
3. **Scrubs privacy leaks** — browser chrome (URL/token/bookmarks), usernames, extension badges, internal
   names — by covering/masking them (including *time‑gated* masks for content that scrolls mid‑beat).
4. **Generates the voiceover** with neural TTS (`edge-tts`, Andrew voice by default).
5. **Syncs VO to the screen** — each beat's footage is time‑fit to its narration so words land on the
   on‑screen action; short answers can freeze‑hold; a gentle push‑in zoom improves readability.
6. **Bookends** with an animated opener/outro (headless‑Chrome render of an HTML/Canvas scene) — optional.
7. **Self‑QAs** — decode integrity, silence gaps, and a frame contact sheet; plus an adversarial QA agent.

Everything is driven by a single `demo_config.py` (one source of truth for beats + narration) and two
scripts (`gen_vo.py`, `build.py`). It's fully reproducible: change the config, re‑run.

## Prerequisites

| Tool | Why | Check |
|---|---|---|
| **ffmpeg / ffprobe** (≥ 6) | all video assembly | `ffmpeg -version` |
| **Python** (≥ 3.10) + **edge-tts** | narration | `pip install edge-tts` |
| **Node.js** (≥ 18) + **puppeteer** (+ **puppeteer-screen-recorder** for v1/v2 bookends) | v3 film render; animated opener/outro | `npm i puppeteer puppeteer-screen-recorder` |
| **Pillow** + **numpy** | mandatory credit stamp; v3 clip extraction | `pip install pillow numpy` |
| *(optional)* **faster-whisper** | word‑timestamps to sync opener beats to VO | `pip install faster-whisper` |

A **1920×1080** source recording is assumed throughout (adjust coords if yours differs).

## Install (as a Claude Code plugin)

Clone this repo, then add it as a local plugin (or via your team marketplace):

```bash
git clone https://github.com/ahmedawan-oracle/fde_demo_builder.git
# In Claude Code:  /plugin  → add local plugin → point at the cloned folder
```

Once installed you get:

- **Skill** `demo-video-builder` — the full methodology; Claude follows it when you ask to build a demo video.
- **Command** `/fde-demo-builder:new-demo <name>` — scaffolds a new demo project (scripts + starter config).
- **Command** `/fde-demo-builder:new-broll <name>` — *(v2)* scaffolds a story-rebuild project (b-roll scenes + multi-voice).
- **Command** `/fde-demo-builder:new-film <name>` — *(v3)* scaffolds a production film (real-pixel footage, narration clock, 14 QA gates).
- **Agent** `demo-qa-reviewer` — adversarially QAs a finished video (privacy, VO‑sync, readability, playback, credit).

> **Mandatory credit.** Every video built with this plugin ends with a small centred footer line on the end
> screen — *Crafted with FDE Demo Builder · by Ahmed Awan*. The build scripts stamp and verify it
> automatically; QA fails any video without it. Please keep it.

## v2 — Story rebuilds (b-roll + multi-voice)

Version 2 adds a second workflow that turns an existing demo (slides + screen recording) into a
**cinematic film**: animated story acts around the real footage, narrated by a cast of voices.

- **B-roll story scenes** — clock-driven HTML/Canvas acts (problem-statement openers, interstitials,
  finales) where every element is keyed to the *spoken word* via edge-tts word timestamps: title
  reveals, stat cards, character "voice moment" cards, particle/flake fields, rain, animated charts,
  and Ken Burns cameras with spotlights over a real architecture diagram. QA with deterministic
  stills (`shot.js`), render once (`render_scene.js`).
- **Multi-voice narration** — cast a narrator, a guide, and a character voice
  (`gen_vo_multivoice.py` + `vo_script.py`); optional handheld-radio treatment for field/ops lines.
- **Placed re-voicing** — pin new narration beats at the original beat offsets of an existing
  recording so every line still lands on its on-screen action, with per-beat time budgets and
  automatic rate-bumping.
- **Assembly** — VO-length-derived trims, segment concat, one loudness pass
  (`assemble.example.sh`).

Method docs: [references/broll-scenes.md](skills/demo-video-builder/references/broll-scenes.md) ·
[references/multi-voice.md](skills/demo-video-builder/references/multi-voice.md).

## v3 — Production films (real pixels on the narration clock)

Version 3 turns a screen recording into a **booth-ready production film** where every product frame is the
recording's own pixels, driven on the narration's clock:

- **Original screen first, then the zoom** — every product beat opens on the whole, uncropped screen and
  pushes into the detail; write your framing in a cropped view and `FOOT.fullscreen()` maps it.
- **Real scrolls** — long documents are stitched from the recording's parked scroll positions and scrolled
  for real inside the app's own chrome (the TOC highlight follows the scroll).
- **Real typing** — typed questions are uncovered glyph by glyph as the voice speaks them, then the real
  send frames play.
- **Pointer-free stills** — per-pixel median across a parked window erases the wandering cursor.
- **Narration is the clock** — 3–4 voices; every cut, scroll, push and highlight is a spoken word
  (`wt(phase, word)`), verified by `check_cues.js`.
- **Deterministic render** — frame-by-frame headless Chrome, multi-worker, no dropped frames.
- **Broadcast-grade audio** — music bed ducked under the voices, two-pass *linear* loudnorm to −16 LUFS.
- **14 QA gates** — cuts land, no blank plates, no freeze > 5 s, loudness, over-claims, identifier hygiene,
  every spoken figure traced to the screen (`claims.json`), captions, and the credit.
- **Try it in one minute** — `make_sample_recording.py` generates a fictional "Acme Console" capture that
  the example config renders end to end.

```
/fde-demo-builder:new-film acme-monday
cd acme-monday && python make_sample_recording.py && python gen_vo_multivoice.py && python extract_clips.py
node export_timeline.js scenes/timing_film_data.js scenes/shots.js && python build_film.py && python qa_film.py
```

Method docs: [real-pixel-footage](skills/demo-video-builder/references/real-pixel-footage.md) ·
[deterministic-render](skills/demo-video-builder/references/deterministic-render.md) ·
[cinematic-grammar](skills/demo-video-builder/references/cinematic-grammar.md) ·
[honesty-audit](skills/demo-video-builder/references/honesty-audit.md) ·
[audio-mix](skills/demo-video-builder/references/audio-mix.md) ·
[credit-footer](skills/demo-video-builder/references/credit-footer.md).

## v4 — Production craft (HyperFrames-inspired)

Version 4 adds the craft that turns a clean demo into a film people remember, re-expressed from HeyGen's open-source
HyperFrames for our real-pixel pipeline (see NOTICE.md). Everything still renders on your laptop.

- **Seams, not cuts** — a `seams.json` ledger declares each cut; the outgoing screen is still moving when the next
  arrives, same axis, matched speed. The seam gate measures the rendered frames and fails any cut that stops early,
  mirrors direction, dissolves or flashes white.
- **Camera kit** — punch-ins, zoom-out reveals, focus pulls, caret-follow; a zoom budget stops pushes past 88 % of the
  frame or 2× the recording's pixels; diagnostics print each shot's camera curve.
- **Captions and overlays** — a burned-in caption lane on the narration's own word times (eight quiet presets) that
  matches the SRT; lower thirds, stat cards, a scarce hero word, pull-quotes, PiP; a gate for safe zones, clipping,
  collisions and contrast.
- **Audio** — the bed ducks only in the bands the voice occupies; a mono→stereo fix recovers 3 dB; voice presets;
  per-phase level match; a beat grid so cuts land on bars; gates for separation, duck depth, even voices, true peak.
- **QA and determinism** — `lint_scene` (wall-clock code, CSS transitions, remote refs, fonts), a canary that renders
  twice and compares, golden snapshots, `doctor` preflight, text overflow + WCAG contrast audit. Gates are plug-ins;
  CREDIT stays last.
- **Planning and review** — `BRIEF.md` intake, `STORYBOARD.md` beat arithmetic rendered as a sketch sheet you lock
  before anything is built, design tokens, a text gate for beats that talk too fast or screens that say too much.
- **Blocks** — chat reveal with human typing rhythm, KPI count-up that lands on the spoken number, state rail / HUD,
  flash cut, title lockup, CTA close.
- **Media and export** — a ledger with every asset's source and licence; export presets (booth loop, LinkedIn, YouTube,
  vertical, square, GIF, share pack), each re-checked for the credit.
- **Finishing** — vignette, seeded grain, haze for recreated scenes only; a colour-truth gate proves product pixels were
  never recoloured.

Method docs: [motion-doctrine](skills/demo-video-builder/references/motion-doctrine.md) ·
[camera-moves](skills/demo-video-builder/references/camera-moves.md) ·
[captions-and-overlays](skills/demo-video-builder/references/captions-and-overlays.md) ·
[audio-carve-and-beats](skills/demo-video-builder/references/audio-carve-and-beats.md) ·
[lint-and-determinism](skills/demo-video-builder/references/lint-and-determinism.md) ·
[brief-storyboard-review](skills/demo-video-builder/references/brief-storyboard-review.md) ·
[blocks-catalog](skills/demo-video-builder/references/blocks-catalog.md) ·
[media-ledger-and-export](skills/demo-video-builder/references/media-ledger-and-export.md) ·
[vfx-and-grading](skills/demo-video-builder/references/vfx-and-grading.md).

## Quickstart

```
/fde-demo-builder:new-demo acme-widgets
```

Then, in the new `acme-widgets/` folder:

1. Drop your recording in as `recording.mp4`.
2. Edit `demo_config.py` — list your beats: `spans` (start/end seconds), `vo` (narration), and any
   `masks`/`zoom`/`freeze`.
3. `python gen_vo.py`   → narration MP3s in `vo/`
4. `python build.py`    → `out/demo.mp4`
5. Ask Claude to run the `demo-qa-reviewer` agent on `out/demo.mp4`; fix anything it flags; rebuild.

See [skills/demo-video-builder/SKILL.md](skills/demo-video-builder/SKILL.md) and the
[references/](skills/demo-video-builder/references/) for the detailed method and hard‑won ffmpeg lessons.

## Scope

This plugin builds the **demo video** from a recording. The *live* demo backend it records
(data, agents, connectors) is out of scope and set up separately.

## License

Released under the MIT License. See [LICENSE](LICENSE).
