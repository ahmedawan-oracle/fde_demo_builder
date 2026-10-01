---
name: demo-video-builder
description: Use when building a polished, voice-narrated demo video from a screen recording — turning a raw capture of a product demo into a shareable MP4 with cut lag, scrubbed privacy leaks, synced VO, optional animated opener/outro. v2 adds cinematic "story rebuilds" — animated b-roll acts word-synced to a multi-voice cast. v3 adds production films — real-pixel footage (original full screen → zoom, real scrolls and typing from the recording's own pixels), the narration as the clock, deterministic frame-by-frame render, linear-loudness mastering, 14 QA gates, and the mandatory FDE Demo Builder end-screen credit. Triggers on "build a demo video", "narrate this recording", "make a demo from this screen capture", "cut the thinking lags and add voiceover", "add a wow animated opener", "multi voice demo", "b-roll story animation", "turn this demo into an animated story".
---

# Demo Video Builder

Turn one screen recording into a polished, narrated, privacy-clean demo video — **fully scripted**, no
video editor.

## MANDATORY: the end-screen credit

Every video made with this plugin — v1, v2, v3, cut-downs and re-exports — ends with one small line, centred
in the footer of the end screen: **"Crafted with FDE Demo Builder · by Ahmed Awan"**. `credit.py` stamps it
(last 4 s, fade-in, auto light/dark) and verifies it; `build.py`, `assemble.example.sh` and `build_film.py`
call it as their final step, `qa_film.py` and the `demo-qa-reviewer` agent fail a video without it. Never
skip, reword, restyle, move or cover it; custom pipelines must call `python credit.py stamp` on the final
file. → `references/credit-footer.md`

## Operating principles (read first)

- **Use the real screen, never mock-ups.** Every frame comes from the actual recording. Do not fabricate
  UI, type-ins, or numbers. If a number is spoken in VO, it must be visible on screen at that moment.
- **Privacy is non-negotiable and easy to miss.** Real recordings bake in leaks: address-bar URLs with
  tokens/tenancy IDs, personal bookmarks, browser-extension badges (e.g. Grammarly), usernames, avatars,
  and internal engineer/customer names typed into fields. **Every** shipped frame must be scrubbed. See
  `references/privacy-scrubbing.md`.
- **Original framing by default.** Keep each screen at its native scale; only cover the browser chrome.
  Reframe/crop only when asked. Use a gentle push-in *zoom* for readability, not a permanent crop.
- **Sync VO to the action.** Fit each beat's footage to its narration so words land on what's on screen.
- **Cut the dead air.** Remove "thinking…" / spinner / loading lags — they're the difference between a
  3:30 slog and a tight 3:00.
- **One source of truth.** `demo_config.py` holds the beats *and* their narration. `gen_vo.py` and
  `build.py` both read it. Change the config, re-run — never hand-edit intermediate files.
- **QA until clean.** A demo isn't done until an adversarial pass finds no privacy leak, no VO-sync drift,
  and clean playback. Use the `demo-qa-reviewer` agent.

## The pipeline (7 phases)

1. **Map** the recording into beats. Watch/scrub it; note the start/end seconds of each meaningful action
   (setup, question typed, answer rendered) and every lag to cut. → `references/map-and-cut.md`
2. **Cut lags** — a beat's `spans` list concatenates only the kept ranges; the gaps (thinking/loading) are
   dropped automatically. → `references/map-and-cut.md`
3. **Scrub privacy** — cover the browser chrome with a color-matched bar; `drawbox`-mask any residual leak
   (subtitle names, extension badges, usernames). Use *time-gated* masks when content scrolls mid-beat.
   → `references/privacy-scrubbing.md`
4. **Frame & zoom** — keep native scale (cover chrome, don't crop); add a slow push-in `zoompan` on dense
   answers for readability. → `references/framing-and-zoom.md`
5. **Voiceover** — write tight, domain-accurate narration per beat in `demo_config.py`; `gen_vo.py`
   renders one MP3 per beat with `edge-tts`. → `references/voiceover-and-sync.md`
6. **Assemble & sync** — `build.py` time-fits each beat's footage to its VO (freeze-hold if footage is
   short), overlays the VO, and concatenates with the opener/outro. → `references/voiceover-and-sync.md`
7. **QA** — decode integrity, silence gaps, contact sheet, then the `demo-qa-reviewer` agent. Fix, rebuild.
   → `references/qa-checklist.md`

## Files (in a scaffolded demo project)

```
my-demo/
├── recording.mp4          # your source capture (1920x1080 recommended)
├── demo_config.py         # THE spec: beats (spans, vo text, masks, zoom, freeze) + settings
├── gen_vo.py              # reads demo_config → vo/<beat>.mp3     (edit rarely)
├── build.py               # reads demo_config → out/demo.mp4      (edit rarely)
├── render_bookend.js      # optional: HTML/Canvas scene → mp4 (opener/outro)
├── scenes/opener.html     # optional: your animated title card
├── vo/                    # generated narration
└── out/                   # clips/ + demo.mp4 + qa/
```

Scaffold one with `/fde-demo-builder:new-demo <name>`, or copy `scripts/` from this skill.

## Typical loop

```bash
python gen_vo.py        # regenerate narration after editing demo_config.py
python build.py         # rebuild the video
# then: run the demo-qa-reviewer agent on out/demo.mp4, fix flags, repeat
```

## Key techniques (the "cool" parts)

- **Lag cutting** — `spans=[(a,b),(c,d)]` keeps only b−a and d−c; the (b→c) thinking gap vanishes.
- **Chrome-cover bar** — a `drawbox` over the top ~96px hides the address bar/bookmarks/extensions while
  keeping the app at 1:1 (dark bar for dark app headers, white for light UIs, so it blends).
- **Time-gated masks** — `enable='between(t,5.5,12)'` covers a leak (e.g. a typed internal name) only for
  the span where it's visible, so it doesn't blank content after the page scrolls.
- **VO time-fit** — `setpts=factor*PTS` with `factor = (vo_dur+0.4)/footage_dur`; keep factor ≈ 1.0.
- **Freeze-hold** — `tpad=stop_duration=N:stop_mode=clone` holds the last answer frame when the VO outlasts
  the footage (better than heavy slow-mo).
- **Push-in zoom** — `zoompan` ramp 1.0→1.10 focused on the answer, for readability without reframing.
- **Animated bookends** — an HTML/Canvas scene recorded via headless Chrome; beats timed to VO word
  anchors (whisper). → `references/opener-outro.md`

Detailed, copy-pasteable ffmpeg and the pitfalls that will bite you are in `references/ffmpeg-gotchas.md`.
Read it before debugging — most "it silently produced a stale/black/soundless file" issues are listed there.

## v2 — Story rebuilds: b-roll acts + a multi-voice cast

The v1 pipeline polishes **one recording**. The v2 workflow rebuilds a demo as a **film**:
animated story acts around (and over) the real product footage, narrated by a cast of voices.
Use it when someone says "make this a wow demo", "add an animated problem-statement story",
or "multi-voice this".

The five moves:

1. **Review the source** — extract frames (`ffmpeg -vf fps=1/12`) and transcribe the audio
   (faster-whisper) to map its structure: which stretches are slides (replace with b-roll),
   which are real product recordings (keep, re-voice), and the exact cut boundaries.
2. **Write the script** — `vo_script.py`: cast 2–3 voices (narrator / guide / character),
   sequential `SCENES` for the animated acts, `PLACED` beats pinned to the recording's
   original narration offsets. → `references/multi-voice.md`
3. **Generate VO** — `python gen_vo_multivoice.py` renders every phrase with word-level
   timestamps and emits `scenes/timing_<name>.js` for the scenes.
4. **Build the b-roll scenes** — clock-driven HTML (`scenes/broll_opener.example.html` is a
   working template): one pure `frame(t)`, every element keyed to spoken words via `wt()`,
   canvas particle fields ("flakes"), optional Ken Burns camera + spotlight over a diagram
   frame. QA with `node shot.js <scene> <t> <png>` stills, then render with
   `node render_scene.js <scene> <vo.mp3> <out.mp4>`. → `references/broll-scenes.md`
5. **Assemble** — mux placed VO over the video-only recording cuts, concat all segments,
   one `loudnorm` on the final mix. → `assemble.example.sh`

Hard rules carried over from v1: real screens only in recording segments (b-roll is clearly
stylized, fictional-branded, and labeled synthetic); privacy-scrub every recorded frame; and
**no customer names or internal identifiers anywhere** — in scenes, VO text, file names, or
example data.

## v3 — Production films: real pixels on the narration clock

v2 rebuilds a demo as a story; v3 makes it a **production film** that holds up on a booth screen and in
front of the people who built the product. Use it when someone says "polish this demo for the event",
"make the screen actions real", "show the original screen, then zoom", or "booth-ready".

The moves:

1. **Map + audit** — write a shot log (parked / scrolling / typing / zoomed, the scrolling band, leaks) and
   audit the source narration against the screen; drop or rewrite every claim the screen contradicts or
   never shows. → `references/real-pixel-footage.md`, `references/honesty-audit.md`
2. **Narration is the clock** — one sequential SCENE in `vo_script.py`, 3–4 voices, the on-screen question
   voiced verbatim; `gen_vo_multivoice.py` emits word timings; every cut/scroll/push/highlight is
   `wt(phase, word)`; `check_cues.js` fails on any unresolved cue. → `references/deterministic-render.md`
3. **Real pixels** — `extract_clips.py`: median stills (pointer-free), stitched tall pages from parked
   scroll positions with the app's own full-screen chrome per position, 30 fps seqs, inverted baked-in
   zooms, `--word-ends` for typed lines, repaint (never rewrite code), mask private data only.
4. **Original screen first, then the zoom** — every product beat opens on the whole screen and pushes in
   (`establish`, `FOOT.fullscreen`); real scrolls with browser easing; typed text uncovered word by word as
   it is spoken, then the real send frames. → `references/cinematic-grammar.md`
5. **Render deterministically** — `render_frames.js`: frame-by-frame, N workers, `__seek/__step` decode
   Promises, frame 0 = clock 0, no dropped frames.
6. **Mix + master + credit** — `build_film.py`: bed sidechain-ducked under the voices, two-pass *linear*
   loudnorm to −16 LUFS (refuses dynamic fallback), captions, then the **mandatory credit**.
   → `references/audio-mix.md`
7. **QA** — `qa_film.py` (14 gates incl. relative cut detection, freeze > 5 s at 640x360, claims traced,
   CREDIT) + the `demo-qa-reviewer` agent. Measure a failing gate before loosening it.

Scaffold with `/fde-demo-builder:new-film <name>`. `make_sample_recording.py` builds a fictional
"Acme Console" capture so the whole pipeline runs out of the box (every gate passes on it).

## v4 — Production craft (HyperFrames-inspired)

v4 keeps the v3 pipeline and layers the craft a booth film needs. Ideas come from HeyGen's open-source HyperFrames
(Apache-2.0, see NOTICE.md), re-expressed for our real-pixel, narration-is-the-clock architecture: pure `frame(t)`,
puppeteer, ffmpeg, python. Nothing needs an account or a cloud. Every reference is ≤ 180 lines and carries the measured
numbers; read the one for the layer you are touching.

| Layer | Lib / tool | Gate | Reference |
|---|---|---|---|
| Seams: cut-the-curve, zoom-through (+inverse), waterfall, nudge, rack-focus, carriers, the vector ledger `seams.json` | `lib/seams.js` | `gates/seam_gate.py` (ledger lint, motion across the cut, white flash, stage ground) | `motion-doctrine.md` |
| Camera: punch in/out, zoom-out reveal, focus pull, caret-follow, dolly, pose ladder, zoom budget (≤ 88 % frame, ≤ 2× source px) | `lib/camera.js` (`--curves` CLI) | `gates/motion_diag.py` | `camera-moves.md` |
| Caption lane on the narration's word times (drop / rail / embed, 8 presets) + lower thirds, stat cards, hero word, pull-quote, PiP | `lib/captions.js`, `lib/overlays.js`, `tools/captions_srt.py` | `gates/overlay_gate.py` (safe zones, overflow, collisions, shape, contrast, hero scarcity) | `captions-and-overlays.md` |
| Audio: band-limited voice carve, pan upmix (+3 dB), voice presets, level match, beat grid | `audio/carve_bed.py`, `voice_presets.py`, `beat_grid.py` | `gates/audio_gate.py` (voice over bed ≥ 12 LU, duck depth, voices even, TP, upmix) | `audio-carve-and-beats.md` |
| Lint + determinism: wall-clock code, CSS transitions, unseeded random, remote refs, fonts; render twice and compare; golden frames | `gates/lint_scene.py`, `tools/doctor.py`, `tools/fonts_localize.py`, `tools/audit_text.js` | `gates/canary.py`, `gates/snapshot.py`, `lint_scene` | `lint-and-determinism.md` |
| Planning: BRIEF.md intake, STORYBOARD.md beat arithmetic + sketch sheet + lock, design tokens, text-beat economics | `tools/brief.py`, `tools/storyboard.py` | `gates/text_gate.py` | `brief-storyboard-review.md` |
| Blocks: chat reveal, KPI count-up, state rail / HUD / agent tag, flash + freeze dressing, title lockup, CTA close, focus zoom | `lib/blocks.js` (+ `scenes_blocks_demo.html`) | — | `blocks-catalog.md` |
| Media: ledger with licences, export presets (booth loop, LinkedIn, YouTube, vertical, square, GIF, share pack), timeline printout, skin tokens | `tools/ledger.py`, `tools/export.py`, `tools/timeline.py` | `gates/ledger_gate.py` | `media-ledger-and-export.md` |
| Finishing: vignette, seeded grain, bloom, matte, haze — recreated layers only; truthful footage normalisation | `lib/vfx.js`, `tools/grade.py` | `gates/grade_gate.py` (UI colour truth, effects off footage) | `vfx-and-grading.md` |

**How the pieces meet.** `build_film.py` runs plan (timeline + seams + captions export) → preflight (doctor, lint,
camera ladder, storyboard lock, canary) → render → mix (carve) → master → captions → **credit** → ledger → exports →
storyboard truth pass. `qa_film.py` runs the built-in gates, then every `gates/*.py` module (`GATE_NAMES` + `run(ctx)`),
and CREDIT last — it cannot be disabled. The scene loads the libs it uses; overlays and captions live in screen space,
outside `#camera`; nothing from VFX may touch the footage lane.

**Working rules (v4).** Write `seams.json` before the shots. One route per phase; no idle wobble. Captions are an
overlay, not a reserved band; one group at a time, ≤ 6 words / 2.5 s. Every spoken figure is in `claims.json` and on
screen. Mask private data only; never recolour product pixels. Everything the scene loads is a local file.
