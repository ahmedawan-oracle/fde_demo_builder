---
description: Scaffold a v2 "story rebuild" demo project — animated b-roll acts + multi-voice re-narration over a screen recording.
argument-hint: <project-name>
---

Scaffold a new story-rebuild demo project named **$1** using the FDE Demo Builder v2 templates.

Do the following:

1. Create `$1/` in the current working directory (error out politely if it already exists).
2. Copy from `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/` into `$1/`:
   - `vo_script.example.py`        → `$1/vo_script.py`
   - `gen_vo_multivoice.py`        → `$1/gen_vo_multivoice.py`
   - `render_scene.js`             → `$1/render_scene.js`
   - `shot.js`                     → `$1/shot.js`
   - `assemble.example.sh`         → `$1/assemble.sh`
   - `requirements.txt`            → `$1/requirements.txt`
   - `credit.py`                   → `$1/credit.py`   (mandatory end-screen credit; assemble.sh calls it)
   - create `$1/scenes/` and copy `scenes/broll_opener.example.html` → `$1/scenes/opener.html`
3. Create empty `$1/vo/`, `$1/out/`, `$1/qa/`, `$1/assets/` folders.
4. Print concise next steps:
   - Drop the source demo in as `$1/recording.mp4`.
   - **Review first**: extract frames (`ffmpeg -i recording.mp4 -vf "fps=1/12,scale=800:-1" qa/f_%02d.jpg`)
     and transcribe (faster-whisper) to map slides-vs-recording stretches and cut boundaries.
   - Edit `$1/vo_script.py`: cast the voices, write the SCENES (animated acts) and PLACED
     beats (re-voiced recording), then `python gen_vo_multivoice.py`.
   - Rewrite `$1/scenes/opener.html` for the story (it's a working template — keep the boot
     and loop blocks verbatim, replace the layers). QA with `node shot.js scenes/opener.html 12 qa/op12.png`,
     render with `node render_scene.js scenes/opener.html vo_opener.mp3 out/seg1_opener.mp4`.
   - Cut + mux the recording segments and run `bash assemble.sh` (recipes are in the file).
   - Finish with the `demo-qa-reviewer` agent on the final MP4.
   - Method details: `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/references/broll-scenes.md`
     and `references/multi-voice.md`.

Also remind them that **the FDE Demo Builder credit ("Crafted with FDE Demo Builder · by Ahmed Awan") is
mandatory** on the end screen — `assemble.sh` stamps and verifies it; never remove or alter it. And the hard rules: **no customer names or internal identifiers anywhere**
(scenes, VO text, examples — use fictional brands and synthetic numbers), and **scrub every
privacy leak** in recorded frames before sharing.

Use forward-slash paths and platform-appropriate copy commands. Do not overwrite an existing `$1/`.
