---
description: Scaffold a v3 production film — real-pixel footage (establishing full screen → zoom, real scrolls and typing) on a word-synced multi-voice narration, deterministic render, 14 QA gates and the mandatory credit.
argument-hint: <project-name>
---

Scaffold a new v3 film project named **$1** from the FDE Demo Builder templates.

1. Create `$1/` in the current working directory (stop politely if it already exists; never overwrite).
2. From `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/film/` copy into `$1/`:
   - `vo_script.example.py` → `vo_script.py`
   - `clips.example.json` → `clips.json`
   - `film.example.json` → `film.json`
   - `qa.example.json` → `qa.json`
   - `claims.example.json` → `claims.json`
   - `extract_clips.py`, `render_frames.js`, `build_film.py`, `qa_film.py`, `check_cues.js`,
     `export_timeline.js`, `make_sample_recording.py` (unchanged)
   - `film.example.html` → `scenes/film.html`
   - `shots.example.js` → `scenes/shots.js`
   - `lib/grammar.js`, `lib/timeline.js`, `lib/footage.js` → `scenes/lib/`
3. From `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/` copy `gen_vo_multivoice.py`, `credit.py`
   and `requirements.txt` into `$1/`.
4. Create empty `$1/broll/`, `$1/vo/`, `$1/out/`, `$1/music/`.
5. Print the next steps:
   - Try it first: `python make_sample_recording.py` creates a fictional `recording.mp4`. The example
     config renders it end to end.
   - For a real demo, put the capture in as `recording.mp4`. Write a shot log and an honesty audit
     (`references/real-pixel-footage.md`, `references/honesty-audit.md`).
   - `python gen_vo_multivoice.py` → narration + word timings (the clock).
   - `python extract_clips.py` → real-pixel clips in `broll/` (median stills, stitched pages + chrome, seqs).
   - `node check_cues.js scenes/timing_film_data.js scenes/shots.js scenes/film.html`
   - `node export_timeline.js scenes/timing_film_data.js scenes/shots.js`
   - `python build_film.py` → render, mix, master, captions, **credit** → `out/<film>.mp4`
   - `python qa_film.py` (14 gates), then run the `demo-qa-reviewer` agent on the final MP4.
   - `npm i puppeteer` once, in the project or a parent folder.

Remind them of the hard rules:
- Every product beat opens on the original full screen, then zooms in.
- Every spoken figure must be visible on screen and listed in `claims.json`.
- Mask private data only. Ask before masking code.
- No customer names or internal identifiers in the scenes, the VO or the examples.
- **The FDE Demo Builder credit ("Crafted with FDE Demo Builder · by Ahmed Awan") is mandatory on the
  end screen.** The build stamps it and QA fails without it. Never remove it or alter it.

Use forward-slash paths and platform-appropriate copy commands.
