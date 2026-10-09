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

## Requirements

| Tool | Why | Check |
|---|---|---|
| **ffmpeg / ffprobe** (≥ 6, built with libx264, aac and libass) | all video assembly, loudness, caption burn-in | `ffmpeg -version`, `ffmpeg -filters \| grep ass` |
| **Python** (≥ 3.10) + `pip install -r requirements.txt` (edge-tts, Pillow, numpy, **scipy** — hard: SFX synth, voice chain, cursor tracking, idle detection, the leak gate's avatar detector) | narration, extraction, gates, tools | `python tools/doctor.py` (checks scipy too) |
| **Node.js** (≥ 18) + `npm i puppeteer gsap three d3-delaunay` | the deterministic render; the v5 picture libraries, loaded from the project's `node_modules` by relative path (never a CDN) | `tools/doctor.py` → `node libs` |
| *(optional)* `winocr` — **preferred on Windows** (the OS engine: 0.3–0.5 s per frame, 60–100× faster than the bundled model at equal recall) — or `rapidocr-onnxruntime opencv-python-headless onnxruntime` elsewhere | OCR in the leak gate; without an engine the gate warns and still runs its pattern, denylist and badge detectors | `python gates/leak_gate.py --selftest` |
| *(optional)* `faster-whisper`, `puppeteer-screen-recorder` | v1/v2 word timestamps and bookends | |

A **1920×1080** source recording is assumed throughout (adjust coords if yours differs). Renders run on
Chrome's software GL path by default so the frames are identical on every machine; `RENDER_GL=hardware` is
for previews. Windows 10/11 fonts (Georgia, Cambria, Segoe UI, Arial, Consolas, Bahnschrift) are the skins'
local pairings; `tools/fonts_localize.py --local` keeps a public project free of font files.

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
- **Command** `/fde-demo-builder:new-film <name>` — *(v3–v5)* scaffolds a production film: BRIEF → look pass →
  STORYBOARD → sketch → lock → build → QA → studio taps → review pack → export.
- **Agent** `demo-qa-reviewer` — adversarially QAs a finished video (privacy, footage honesty, chart truth, VO‑sync, credit).

> **Mandatory credit.** Every video built with this plugin ends with a small centred footer line on the end
> screen — *Crafted with FDE Demo Builder · by Ahmed Awan*. The build scripts stamp and verify it
> automatically; QA fails any video without it. Please keep it.

## v5 — The picture layer

Version 5 is about what the viewer sees. Every device runs on the narration clock, never touches a product pixel
and renders byte-identically on software GL. Read [picture-doctrine](skills/demo-video-builder/references/picture-doctrine.md) first.

- **Motion and type on the clock** — GSAP timelines mounted paused and set per frame; words arrive as they are
  spoken, a phrase swaps with a match cut, one hero word, one slam, glyph soup resolving into a headline.
- **Transitions you can defend** — seven WebGL2 cuts (chroma split, ink dissolve, light leak, white hit, iris,
  slit scan, cross warp) declared in `seams.json`, ≤ 0.5 s over footage, never between two product screens.
- **3D titles** — a headline cut into glass shards that fly in from depth and past the lens; an outline that
  assembles from pieces; a card stack the camera dollies through (105 ms/frame with 4× MSAA on software GL).
- **Story blocks, charts, comparisons** — a count-up that lands on its word, a decision card that types and
  seals, a receipt that snaps, a chat reveal at human rhythm; charts that accept only `claims.json` ids;
  before/after split, wipe and picture-in-picture with both halves pixel-exact.
- **Light, depth, a human hand, glass** — a lamp behind a card, a light sweep on the landing word, parallax
  planes, a perspective dolly, hand-drawn circles / arrows / boxes projected through the camera, a spotlight
  that glides, frosted panels (≤ 2, never on the caption lane).
- **Reveals** — the first real screen arrives as a floating plate or compiles out of 6000 particles and hands
  over to the footage lane on one frame; the last one lifts away for the close.
- **Showreel motion** — for pitch films and team reels: a grid of days that rises as an iso voxel field and lands
  exactly back on the flat grid; a split-panel slam onto the title; pixel-matrix wipes at the big cuts; light-speed
  bursts and ripple rings on the payoff word; a glossy liquid core that drinks every arriving artifact (WebGL, works
  on software GL); outline marquees, smear trails and a film HUD with chapters and timecode. Pure functions of t,
  byte-identical renders, recreated layer only.
- **Recording-native** — pointer and keys captured while you record (clap-aligned) or recovered from an old
  tape as a proposal; a camera that pushes to where the work happens and lands on a spoken word; a redrawn
  cursor with click rings; a keystroke pill; idle / spinner / typing / scroll detection that proposes the cuts.
- **Privacy, measured** — the leak gate OCRs every extracted frame for e-mails, identifiers, URLs, tokens,
  denylisted names and account badges and fails on anything unmasked; blur proposals with a measured radius.
- **Captions, chapters, reflow** — karaoke and kinetic caption styles; one groups file feeds the burn-in,
  `.srt`, `.vtt` and an `.ass` with per-word tags; chapters start on cuts; the screen in a frame; 9:16 / 1:1 /
  4:5 crops that follow the cursor or the camera like an operator.
- **Look before the build** — a logo becomes a contrast-checked skin and a style sheet; ten skins ship; a live
  studio shows any frame in under a second and taps a still through the real renderer; one offline review
  page carries honesty flags, comments and the storyboard sign-off.
- **Sound without a sample pack** — thirteen synthesized sounds placed on seams and block landings, never
  within 0.15 s of a word; bus chains with a built de-esser; a bed that breathes at seams.

```
/fde-demo-builder:new-film acme-monday
cd acme-monday && npm i puppeteer gsap three d3-delaunay && pip install -r requirements.txt
python make_sample_recording.py && python gen_vo_multivoice.py && python extract_clips.py
node export_timeline.js scenes/timing_film_data.js scenes/shots.js && python build_film.py && python qa_film.py
```

## How it compares

Against code-first video frameworks and screen-recorder tools, without naming any:

| Capability | Code-first video frameworks | Screen-recorder tools | FDE Demo Builder v5 |
|---|---|---|---|
| Source of truth for timing | code / a composition timeline | the recording | the narration's word times — every cut, move, caption and sound is a spoken word |
| Real product pixels | imported as media; freely graded | the recording, auto-zoomed | sacred: scaled, moved, soft-masked; never recoloured; a gate measures it |
| Transitions over footage | any shader, any length | presets | seven cuts, declared in a ledger, ≤ 0.5 s over footage, never between two product screens |
| Determinism | usually, if you avoid wall-clock code | real-time capture | render twice → byte-identical; software GL default; a canary gate proves it |
| Cursor, zoom, keystrokes | none (you animate them) | automatic from the live pointer | from recorded telemetry (clap-aligned) or recovered from the tape; camera proposals you accept in the storyboard |
| Dead air | manual trims | manual trims, some auto | measured change energy → proposed cuts, ramps, caret follow |
| Privacy | none | blur tools | OCR + identifier patterns + fuzzy denylist + badge detector on every shipped frame; blur proposals |
| Charts and numbers | any | none | only values traced in `claims.json`; derived figures refused |
| Captions | plugins | auto subtitles | karaoke / kinetic styles, one groups file → burn-in + .srt/.vtt/.ass, chapters on cuts |
| Look | code | themes | brand kit → contrast-checked skin + style sheet; ten skins; approved before the build |
| Review | your own | share links | one offline HTML with honesty flags, comments and a storyboard sign-off; a live studio with real-renderer taps |
| Sound | your assets | library SFX | synthesized on the machine, placed by rule, word-safe |
| Runs | locally / cloud render | desktop app | locally, offline, no account; libraries from npm/pip under their own licences |

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
- **QA gates** — cuts land, no blank plates, no freeze > 5 s, loudness, over-claims, identifier hygiene,
  every spoken figure traced to the screen (`claims.json`), captions, and the credit.
- **Try it in one minute** — `make_sample_recording.py` generates a fictional "Acme Console" capture that
  the example config renders end to end.

Method docs: [real-pixel-footage](skills/demo-video-builder/references/real-pixel-footage.md) ·
[deterministic-render](skills/demo-video-builder/references/deterministic-render.md) ·
[cinematic-grammar](skills/demo-video-builder/references/cinematic-grammar.md) ·
[honesty-audit](skills/demo-video-builder/references/honesty-audit.md) ·
[audio-mix](skills/demo-video-builder/references/audio-mix.md) ·
[credit-footer](skills/demo-video-builder/references/credit-footer.md).

## v4 — Production craft

Version 4 adds the craft that turns a clean demo into a film people remember, built for our real-pixel pipeline.
Everything still renders on your laptop; the third-party libraries it uses are listed in NOTICE.md.

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
[vfx-and-grading](skills/demo-video-builder/references/vfx-and-grading.md) ·
[qa-gates](skills/demo-video-builder/references/qa-gates.md).

## Quickstart (v1)

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

Released under the MIT License — see [LICENSE](LICENSE). Third-party libraries (gsap, three, d3-delaunay,
puppeteer, numpy, scipy, Pillow, the optional OCR engines, edge-tts, ffmpeg) are installed from npm or pip
under their own licences and are never vendored; GSAP is used under its standard no-charge licence. The full
list is in [NOTICE.md](NOTICE.md).
