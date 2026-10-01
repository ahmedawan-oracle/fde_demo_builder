---
description: Scaffold a v4 production film — real-pixel footage (original full screen → zoom, real scrolls and typing) on a word-synced multi-voice narration, velocity-matched seams, a caption lane, carved audio, deterministic render, 25+ QA gates and the mandatory credit.
argument-hint: <project-name>
---

Scaffold a new v4 film project named **$1** from the FDE Demo Builder templates.

0. **Brief first.** If the request names no angle, run the pitch round: five tellings (the subject's world · the emotion ·
   the audience met or broken · the anti-pattern inverted · an unusual format), three lines each, at least two unlikely
   ones, all five before a recommendation; mixing is an answer; one round. Then fill `BRIEF.md` one field per message,
   recommended option first with its receipt; skip fields the request already answered (inference is not an answer);
   hand off with STATED and INFERRED as two groups. `python tools/brief.py BRIEF.md` must print BRIEF OK.
1. Create `$1/` in the current working directory (stop politely if it already exists; never overwrite).
2. From `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/film/` copy into `$1/`:
   - `vo_script.example.py` → `vo_script.py` · `clips.example.json` → `clips.json` · `film.example.json` → `film.json`
     · `qa.example.json` → `qa.json` · `claims.example.json` → `claims.json`
   - `templates/seams.example.json` → `seams.json` · `templates/captions.example.json` → `scenes/captions.json`
     · `templates/BRIEF.example.md` → `BRIEF.md` · `templates/STORYBOARD.example.md` → `STORYBOARD.md`
     · `templates/design.example.md` → `design.md` (do NOT copy `templates/media.example.jsonl`; `ledger.py adopt` writes the real one)
   - `extract_clips.py`, `render_frames.js`, `build_film.py`, `qa_film.py`, `check_cues.js`, `export_timeline.js`,
     `make_sample_recording.py` (unchanged)
   - `film.example.html` → `scenes/film.html` · `shots.example.js` → `scenes/shots.js`
   - `lib/*.js` → `scenes/lib/` (grammar, timeline, footage, camera, seams, captions, overlays, blocks, vfx)
   - `gates/*.py` → `gates/` (all plug-in QA gates) · `tools/*` → `tools/` · `audio/*.py` → `audio/`
3. From `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/` copy `gen_vo_multivoice.py`, `credit.py` and
   `requirements.txt` into `$1/`.
4. Create empty `$1/broll/`, `$1/vo/`, `$1/out/`, `$1/music/`, `$1/golden/`; run `python tools/ledger.py adopt` inside `$1/`.
5. Print the next steps:
   - Try it first: `python make_sample_recording.py` creates a fictional `recording.mp4`; the example config renders it
     end to end and passes every gate.
   - For a real demo, put the capture in as `recording.mp4`. Write the shot log and the honesty audit
     (`references/real-pixel-footage.md`, `references/honesty-audit.md`).
   - Plan: edit `STORYBOARD.md` (one beat per idea, `real: recorded|recreated|placeholder` on each, the beats must add up
     to the narration); `python tools/storyboard.py check STORYBOARD.md`; `python tools/storyboard.py sheet STORYBOARD.md`
     → open `out/storyboard.html`, revise only the cells that change, write `## Locked`. The sketch pass is the default
     stop; `build_film.py` runs only after the lock (`--autonomous` for a drive-it run).
   - Write the vector ledger `seams.json` BEFORE the shots: one row per cut, every ordinary seam on the current (LEFT),
     at most one reserved vector per act (`references/motion-doctrine.md`).
   - `python gen_vo_multivoice.py` → narration + word timings (the clock).
   - `python extract_clips.py` → real-pixel clips in `broll/`; `python tools/ledger.py adopt` again; for music/SFX/fonts:
     `python tools/ledger.py add <path> --kind music --licence "…" --licence-url … --commercial-ok yes`.
   - (with a bed) `python audio/beat_grid.py <bed> --out out/beats_film.json`; `python audio/carve_bed.py vo_film.mp3`
     prints which bands the cast occupies — keep `"carve": true`.
   - `node check_cues.js scenes/timing_film_data.js scenes/shots.js scenes/film.html seams.json`
   - `node scenes/lib/camera.js --curves scenes/timing_film_data.js scenes/shots.js broll/clips.js` — the pose ladder;
     fix every FAIL (move < 0.5 s that is not a punch, > 2.5 s, still moving at a hard cut, upsample > 2.0).
   - `python tools/doctor.py` → `python build_film.py` (plan → preflight → render → mix → master → captions → **credit**
     → ledger → exports → storyboard truth pass) → `python qa_film.py` → `python tools/timeline.py`.
   - After the first reviewed build: `python gates/snapshot.py scenes/film.html --update` freezes one golden frame per
     shot; later runs diff against it. `python tools/export.py --preset linkedin,booth_loop,share_pack` for deliverables.
   - Then run the `demo-qa-reviewer` agent on the final MP4.
   - `npm i puppeteer` once, in the project or a parent folder; `pip install -r requirements.txt`.

Remind them of the hard rules:
- Every product beat opens on the original full screen, then zooms in.
- Every cut is a seam in `seams.json`: same axis, same direction, mid-flight on both sides; never a fade between
  scenes; no idle wobble — name a route for every phase.
- Every spoken figure must be visible on screen and listed in `claims.json`; every beat carries a truthfulness tag;
  a placeholder never ships.
- On-screen text is a hero word, a stat or a one-word emphasis — never a narration sentence. Nothing authored in the
  bottom 17 % except the caption lane and the credit.
- Mask private data only (small soft blurs). Ask before masking code. Never recolour product pixels.
- Everything the scene loads is a local file inside the project — a URL in the scene is a bug.
- No customer names or internal identifiers in the scenes, the VO or the examples.
- **The FDE Demo Builder credit ("Crafted with FDE Demo Builder · by Ahmed Awan") is mandatory on the end screen and on
  every export.** The build stamps it and QA fails without it. Never remove it or alter it.

Use forward-slash paths and platform-appropriate copy commands.
