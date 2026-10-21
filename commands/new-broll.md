---
description: Scaffold a v2 "story rebuild" demo project — animated b-roll acts + multi-voice re-narration over a screen recording.
argument-hint: <project-name>
---

This file is the shared Claude Code and Codex scaffolding specification. A Claude slash-command invocation
expands its project-name and plugin-root placeholders. When this file is read directly in either client and a
placeholder remains literal, take the project name from the user's request and resolve the plugin root as
`dirname(<absolute SKILL.md path>)/../..`. Execute the same steps and constraints in either client.

Scaffold a new story-rebuild demo project named **$0** using the FDE Demo Builder v2 templates.

Do the following:

1. Create `$0/` in the current working directory (error out politely if it already exists).
2. Copy from `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/` into `$0/`:
   - `vo_script.example.py`        → `$0/vo_script.py`
   - `gen_vo_multivoice.py`        → `$0/gen_vo_multivoice.py`
   - `tts_providers.py`            → `$0/tts_providers.py`
   - `render_scene.js`             → `$0/render_scene.js`
   - `shot.js`                     → `$0/shot.js`
   - `assemble.example.sh`         → `$0/assemble.sh`
   - `requirements.txt`            → `$0/requirements.txt`
   - `credit.py`                   → `$0/credit.py`   (mandatory end-screen credit; assemble.sh calls it)
   - create `$0/scenes/` and copy `scenes/broll_opener.example.html` → `$0/scenes/opener.html`
3. Create empty `$0/vo/`, `$0/out/`, `$0/qa/`, `$0/assets/` folders.
4. Print concise next steps:
   - Drop the source demo in as `$0/recording.mp4`.
   - **Review first**: extract frames (`ffmpeg -i recording.mp4 -vf "fps=1/12,scale=800:-1" qa/f_%02d.jpg`)
     and transcribe (faster-whisper) to map slides-vs-recording stretches and cut boundaries.
   - Edit `$0/vo_script.py`: cast the voices, write the SCENES (animated acts) and PLACED
     beats (re-voiced recording), then `python gen_vo_multivoice.py`.
   - Rewrite `$0/scenes/opener.html` for the story (it's a working template — keep the boot
     and loop blocks verbatim, replace the layers). QA with `node shot.js scenes/opener.html 12 qa/op12.png`,
     render with `node render_scene.js scenes/opener.html vo_opener.mp3 out/seg1_opener.mp4`.
   - Cut + mux the recording segments and run `bash assemble.sh` (recipes are in the file).
   - Finish with the shared reviewer specification: Claude invokes the `demo-qa-reviewer` agent; Codex uses a
     separate no-edit review pass on the final MP4.
   - Method details: `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/references/broll-scenes.md`
     and `references/multi-voice.md`.

Also remind them that **the FDE Demo Builder credit ("Crafted with FDE Demo Builder · by Ahmed Awan") is
on by default** on the end screen — `assemble.sh` stamps and verifies it; do not alter it, and omit it only when the brief explicitly asks (see `references/credit-footer.md`). And the hard rules: **no customer names or internal identifiers anywhere**
(scenes, VO text, examples — use fictional brands and synthetic numbers), and **scrub every
privacy leak** in recorded frames before sharing.

Use forward-slash paths and platform-appropriate copy commands. Do not overwrite an existing `$0/`.
