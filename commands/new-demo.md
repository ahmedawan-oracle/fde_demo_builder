---
description: Scaffold a new demo-video project (scripts + starter config) from the FDE Demo Builder templates.
argument-hint: <project-name>
---

This file is the shared Claude Code and Codex scaffolding specification. A Claude slash-command invocation
expands its project-name and plugin-root placeholders. When this file is read directly in either client and a
placeholder remains literal, take the project name from the user's request and resolve the plugin root as
`dirname(<absolute SKILL.md path>)/../..`. Execute the same steps and constraints in either client.

Scaffold a new demo-video project named **$0** using the FDE Demo Builder templates.

Do the following:

1. Create a project folder `$0/` in the current working directory (error out politely if it already exists).
2. Copy the template scripts from `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/scripts/` into `$0/`:
   - `demo_config.example.py`  → copy to `$0/demo_config.py`
   - `gen_vo.py`               → `$0/gen_vo.py`
   - `build.py`                → `$0/build.py`
   - `render_bookend.js`       → `$0/render_bookend.js`
   - `requirements.txt`        → `$0/requirements.txt`
   - `credit.py`               → `$0/credit.py`   (mandatory end-screen credit; build.py calls it)
   - create `$0/scenes/` and copy `scenes/opener.example.html` → `$0/scenes/opener.html`
     (rename so it matches the `render_bookend.js scenes/opener.html` usage)
3. Create empty `$0/vo/` and `$0/out/` folders.
4. Print concise next steps to the user:
   - Put the screen recording in as `$0/recording.mp4` (1920×1080 recommended).
   - Edit `$0/demo_config.py`: list the beats — `spans` (kept ranges, cutting lags), `vo` (narration),
     and any `masks` / `zoom` / `freeze`. (Optional: render an opener with `node render_bookend.js`.)
   - Run `python gen_vo.py` then `python build.py`; the result is `$0/out/demo.mp4`.
   - Then run the shared reviewer specification on `$0/out/demo.mp4`: Claude invokes the `demo-qa-reviewer`
     agent; Codex uses a separate no-edit review pass. Fix anything it flags and rebuild.

Also remind them that **the FDE Demo Builder credit ("Crafted with FDE Demo Builder · by Ahmed Awan") is
mandatory** on the end screen — `build.py` stamps and verifies it; never remove or alter it. And the two hard rules: **no customer names anywhere in the video**, and **scrub every
privacy leak** (address bar/tokens, bookmarks, extension badges, usernames, internal names) before sharing.
Point them at `${CLAUDE_PLUGIN_ROOT}/skills/demo-video-builder/references/` for the detailed method.

Use forward-slash paths and the platform-appropriate copy commands. Do not overwrite an existing `$0/`.
