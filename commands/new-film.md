---
description: Scaffold a v5 production film — real-pixel footage (original full screen → zoom, real scrolls and typing) on a word-synced multi-voice narration; GSAP timelines on the clock, kinetic type, WebGL transitions, 3D titles, story blocks, light / depth / annotation, reveals, a redrawn cursor, idle detection, an OCR leak gate, karaoke captions, skins, a live studio and a review pack; deterministic software-GL render, 60+ QA gates and the mandatory credit.
argument-hint: <project-name> [--template booth-trailer|customer-story|feature-walkthrough]
---

Scaffold a new v5 film project named **$1** from the FDE Demo Builder templates. `--template <name>` picks one of
the three film templates in step 2 without asking (30–45 s booth trailer · 90–150 s customer story · 60–120 s
feature walkthrough); without it, offer them and let the author choose or keep the Acme defaults.

0. **Brief first.** If the request names no angle, run the pitch round: five tellings (the subject's world · the emotion ·
   the audience met or broken · the anti-pattern inverted · an unusual format), three lines each, at least two unlikely
   ones, all five before a recommendation; mixing is an answer; one round. Then fill `BRIEF.md` one field per message,
   recommended option first with its receipt; skip fields the request already answered (inference is not an answer);
   hand off with STATED and INFERRED as two groups. Add the `## Never on screen` list (customer and colleague names the
   recording may show — the leak gate fuzzy-matches them). `python tools/brief.py BRIEF.md` must print BRIEF OK.
1. Create `$1/` in the current working directory (stop politely if it already exists; never overwrite).
2. From `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/film/` copy into `$1/`:
   - `vo_script.example.py` → `vo_script.py` · `clips.example.json` → `clips.json` · `film.example.json` → `film.json`
     · `qa.example.json` → `qa.json` · `claims.example.json` → `claims.json`
   - `templates/seams.example.json` → `seams.json` · `templates/captions.example.json` → `scenes/captions.json`
     · `templates/captions_overrides.example.json` → `captions_overrides.json` (if present)
     · `templates/BRIEF.example.md` → `BRIEF.md` · `templates/STORYBOARD.example.md` → `STORYBOARD.md`
     · `templates/design.example.md` → `design.md` (do NOT copy `templates/media.example.jsonl`; `ledger.py adopt` writes the real one)
   - the film templates in `templates/films/` (booth-trailer · customer-story · feature-walkthrough; each has a README,
     a STORYBOARD skeleton, `seams.json`, `captions.json`, `film.json`, `skin.json`): copy the one named by `--template`
     (or chosen when offered) over the defaults — `STORYBOARD.md`, `seams.json`, `scenes/captions.json`, `film.json`,
     and its `skin.json` as `film.json → "skin"`.
   - `extract_clips.py`, `render_frames.js`, `build_film.py`, `qa_film.py`, `check_cues.js`, `export_timeline.js`,
     `make_sample_recording.py` (unchanged)
   - `film.example.html` → `scenes/film.html` · `shots.example.js` → `scenes/shots.js`
   - `lib/*.js` → `scenes/lib/` (all of them: grammar, timeline, footage, camera, seams, captions, overlays, blocks, vfx,
     motion, typo, shaders, title3d, blocks2, light, depth, annotate, glass, reveals, stage, charts, compare, cursor, hud)
   - `gates/*.py` → `gates/` · `tools/*` → `tools/` · `audio/*.py` → `audio/` · `skins/` → `skins/` · `studio/` → `studio/`
3. From `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/` copy `gen_vo_multivoice.py`, `credit.py` and
   `requirements.txt` into `$1/`.
4. Create empty `$1/broll/`, `$1/vo/`, `$1/out/`, `$1/music/`, `$1/golden/`; run `python tools/ledger.py adopt` inside `$1/`.
   Append to the project `.gitignore`: `events.jsonl`, `*.events.jsonl`, `leaks.json`, `out/`, `audio/sfx/`.
5. Install once, in the project or a parent folder: `npm i puppeteer gsap three d3-delaunay` (scenes load the three
   libraries from `node_modules` by relative path — never from a CDN) and `pip install -r requirements.txt`
   (edge-tts, Pillow, numpy and **scipy** — scipy is a hard dependency of the SFX synth, the voice chain, cursor
   tracking, idle detection and the leak gate's avatar detector; + `pip install winocr` on Windows — the preferred
   OCR engine there, 60–100× faster than the bundled model at equal recall — or `rapidocr-onnxruntime
   opencv-python-headless onnxruntime` elsewhere, to enable OCR in the leak gate). `python tools/doctor.py` confirms
   ffmpeg, node, Chrome, the Python modules (scipy included), the node libs and the GL path.
6. Print the flow as the next steps:
   - **Try it first:** `python make_sample_recording.py` creates a fictional `recording.mp4`; the example config renders
     it end to end and passes every gate.
   - **References.** `python tools/ref_study.py log --title "…" --shot "len|camera|lighting|cut" …` for the films this one
     resembles (craft only — logos, taglines and copy are refused), `measure <film.mp4>` for the ones you have, `report` →
     `REFERENCES.md` with the shot-length, rhythm, luma and contrast bands the storyboard is written against.
   - **Look pass.** Pick a skin from `skins/README.md` (open its sheet in `skins/sheets/`) or extract one from a logo:
     `python tools/brand_kit.py extract --logo assets/logo.png --bg dark --mood corporate --name $1 --out skin_tokens.json
     --sheet out/style_sheet.png`. Look at the sheet; set `film.json → "skin"`; `python tools/brand_kit.py check <skin>`;
     `python tools/skin_apply.py skins/<name>.json` writes `scenes/skin_data.js` (and the head-fade plate for light skins).
     If the look is wrong, change the skin, not the scene.
   - **Storyboard.** Edit `STORYBOARD.md` (one beat per idea, `real: recorded|recreated|placeholder`, `chapter:` on the
     beats that open a chapter; `start:` and `end:` — the first and the last frame in one sentence each, `end:` mandatory on
     recreated beats; `hold:` on recreated beats — the fraction after which only the background moves, or `none (reason)`;
     the beats must add up to the narration); `python tools/storyboard.py check STORYBOARD.md`;
     `python tools/storyboard.py sheet STORYBOARD.md` → open `out/storyboard.html`, revise only the cells that change;
     `sheet --mobile --out out/storyboard_mobile.html` for a phone review (one column, tap to zoom).
   - **Lock.** Write `## Locked`. The sketch pass is the default stop; `build_film.py` runs only after the lock
     (`--autonomous` for a drive-it run).
   - **Seams before shots.** `seams.json`: one row per cut, every ordinary seam on the current (LEFT), at most one reserved
     vector per act, at most one `type: gl` accent per act (`dur` ≤ 0.5 s, never between two product screens).
   - **Narration.** `python gen_vo_multivoice.py` → narration + word timings (the clock).
   - **Footage.** Record with telemetry when you can: `python tools/record_events.py capture --out events.jsonl` (F8 clap,
     F9 stop), then `align --video recording.mp4`. Old tape: `python tools/cursor_track.py recording.mp4 --sheet out/cursor.jpg`
     (a proposal — read the sheet). `python extract_clips.py` → real-pixel clips; `python tools/ledger.py adopt` again; for
     music / fonts: `python tools/ledger.py add <path> --kind music --licence "…" --licence-url … --commercial-ok yes`.
   - **Proposals you accept in the storyboard.** `python tools/camera_from_events.py events.jsonl --out out/camera_auto.json`
     (push / hold / pull on the 1.0 / 1.35 / 1.6 / 2.0 ladder; paste `moves_js` into `shots.js`);
     `python tools/idle_detect.py recording.mp4 --t0 W0 --t1 W1 --js scenes/idle.js --clip <clip> --sheet out/idle_<clip>.png`
     per seq clip (cuts, ramps, caret follow — wire `IDLE.<clip>.proposals.map` into the shot's `play`).
   - **Cut list.** For every footage shot that plays real motion, one text row (clip, length, start, speed, reverse):
     `python tools/cutlist.py resolve cutlist.txt --auto-window --fit` (the window with the most motion; speed to the slot,
     never trim it; a short clip holds its end state) → `emit` writes `scenes/cutlist_data.js`; in `shots.js`:
     `play: Object.assign({ at: <cue> }, CUTLIST.<clip>)`; `check --check-length` before the build.
   - **Pilot a look.** Two skins or two choreographies: `python tools/pilot.py scenes/film.html "scenes/film.html?skin=cobalt"
     --shots 3-6` → `out/pilot.mp4` (A over B on one clock) — pick one as a cut, write why in `## Decisions`.
   - **Build the scene.** Devices by moment: `references/picture-doctrine.md`. A shot may carry its contract:
     `spec: { forbidden: [...], claims: [...], references: [...] }` (gates/spec_gate.py reads the rendered frames). Every number a block or chart shows is a
     `claims.json` value; marks sit on a claim figure or a logged click. Declare the holds: `FILM.holds` for the recreated
     segments, `hold:` on a footage shot that ends settled, never on a footage match-cut (`references/hold-doctrine.md`).
   - (with a bed) `python audio/beat_grid.py <bed> --out out/beats_film.json`; `python audio/carve_bed.py vo_film.mp3 --bed <bed>
     --bed-db -12` prints which bands the carve takes — keep `"carve": true`. SFX: `python audio/sfx_synth.py --out audio/sfx`,
     then `sfx_place.py` / `envelope.py` run from the build. The word guard drops a transient within 0.15 s of a spoken
     word; a sync point that must land anyway carries `"force": true` (reported as `forced: true`, still counted by
     `sfx one impact`). Chapters: `"chapters": true` merges automatically for films under 60 s (`{"merge": "auto"}`;
     set `true`/`false` to override) — a 35 s trailer gets one chapter, not six.
   - `node check_cues.js scenes/timing_film_data.js scenes/shots.js scenes/film.html seams.json`
   - `node scenes/lib/camera.js --curves scenes/timing_film_data.js scenes/shots.js broll/clips.js` — fix every FAIL.
   - **Studio.** `python tools/studio.py` → http://127.0.0.1:8765 : scrub, frame-step, hot reload at the same t; **T** taps a
     1920x1080 still through the real renderer (`out/taps/`), **Q** runs the quick lint. Iterate here; render once.
   - **Build + QA.** `python tools/doctor.py` → `python build_film.py` (plan → preflight → render on software GL → mix →
     master → captions → **credit** → ledger → exports → truth pass) → `python qa_film.py` (`--profile=picture` for the
     fast set, `full` for every gate) → `python tools/timeline.py`. On a `leaks` FAIL: `python tools/mask_propose.py
     leaks.json --verify`, then `--apply`, re-extract, re-run.
   - **Frame pairs.** `python gates/snapshot.py --pairs out/<film>.mp4` → `out/pairs/pairs.jpg` (START | END per segment;
     a `STATIC` pair never moved); `python gates/pair_gate.py .` — anchors within 2 px, no unplanned word, no unnamed newcomer.
   - **Takes.** Every build is a take: `python tools/takes.py list | time`; `annotate` after QA; `prune --after-lock` once the
     plan is signed off. A later change is `python tools/cutlist.py bump v3.txt v4.txt --replace 'old=new' --previous-film
     out/<film>.mp4`, a render, and `python gates/identity_gate.py . out/<film>_v3.mp4` to prove the rest unchanged.
   - **Review pack.** `python tools/review_pack.py build --project . --film out/<film>.mp4` → send `out/review/index.html`
     → **Approve start / Approve end** per beat (END first — it is the frame the next cut lands on; once `approvals.json`
     exists the build refuses while an END is unapproved) → resolve comments → `python tools/review_pack.py --lock --by "Name"`;
     the `review lock` gate passes after that.
   - **Whole-cut notes.** After the `demo-qa-reviewer` agent's whole-cut pass: `python tools/review_notes.py import notes.txt`
     (each note snaps to the nearest cut / seam / shot boundary) → `decide N --accept|--reject --why "…"` → the table lands in
     `DELIVERY.md` with the share pack. Rejections are kept on purpose.
   - **Sound proof.** After the build `cue sync` (sfx_gate) locates every SFX in the finished audio; `python audio/cues_check.py
     --cues out/cues_film.json --film out/<film>.mp4` prints the per-cue offsets. `--shutter 240` on `render_frames.js` only when
     a push or slide should smear like a camera (default off).
   - **Export.** `python tools/export.py --preset linkedin,booth_loop,youtube,share_pack` (`--closure hardcut` when the film
     opens and closes on the same composition — the score and the fallback are recorded); vertical / square cuts follow
     the camera: `node scenes/lib/stage.js --reflow 9:16 --track out/camera_curves.json --total <END> --out
     out/stage_reflow_9x16.json` then `--preset vertical_9x16 --reflow out/stage_reflow_9x16.json`.
   - After the first reviewed build: `python gates/snapshot.py scenes/film.html --update` freezes golden frames. Then run
     the `demo-qa-reviewer` agent on the final MP4.
   - Render notes: the default is software GL (frames identical on every machine; a DOM shot in 80 ms); `RENDER_GL=hardware`
     is for previews only — never mix the two in one film. Scenes with a 3D title render with `"workers": 1`.

Remind them of the hard rules:
- Every product beat opens on the original full screen, then zooms in.
- Every cut is a seam in `seams.json`: same axis, same direction, mid-flight on both sides; never a fade between
  scenes; a shader transition crosses footage only inside its ≤ 0.5 s window and never between two product screens.
- Footage is never recoloured, warped, grained or redrawn; masks are small soft blurs. Ask before masking code.
- Every spoken or drawn figure is in `claims.json` and on screen; charts take claim ids, never numbers; every beat
  carries a truthfulness tag; a placeholder never ships.
- On-screen text is a hero word, a stat or a one-word emphasis — never a narration sentence. Nothing authored in the
  bottom 17 % except the caption lane and the credit.
- Everything the scene loads is a local file inside the project — a URL in the scene is a bug. No wall clock, no
  unseeded randomness; GSAP only through `MOTION` (`tl.set` inside a block, `MOTION.set` outside — a bare `gsap.set`
  never renders); **never `will-change`** in a scene or a lib (the lint refuses it: a promoted layer rasters at a
  scale the compositor picks from history and two renders stop matching). Proof is two 3-worker renders made while
  the machine is busy with an empty `framemd5` diff.
- Type floor: labels, kickers, ticks 16 stage px (24 px at 1080p), body 18, headlines 40 — `design.md → scale`.
- No customer names or internal identifiers in the scenes, the VO, the examples or `events.jsonl` in the repo.
- **The FDE Demo Builder credit ("Crafted with FDE Demo Builder · by Ahmed Awan") is mandatory on the end screen and on
  every export.** The build stamps it and QA fails without it. Never remove it or alter it.

Use forward-slash paths and platform-appropriate copy commands.
