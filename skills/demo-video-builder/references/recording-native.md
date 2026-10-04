# Recording-native — the frame follows the hand, dead air is found, not timed

The footage lane erases the real pointer (median stills) and plays the recording as it was. v5 puts a clean
pointer back, names the keys the presenter pressed, moves the frame to where the work happens, and finds the
idle, spinner, typing and scroll spans so their edits are proposals, not guesswork. Everything downstream
reads one file: `events.jsonl`. Code: `tools/record_events.py`, `tools/cursor_track.py`,
`tools/camera_from_events.py`, `tools/idle_detect.py`, `lib/cursor.js`, `lib/hud.js`.

## events.jsonl

One JSON object per line; the first is `{"type":"meta", "source":[W,H], …}`; then `{t, x, y, type}` with
`type` = `move` | `down` | `up` (`button`) | `key` (`key`, `mods`, `char`, `vk`). `t` is RECORDING seconds
(t = 0 is frame 0), `x`/`y` recording pixels. Tracker lines add `conf` (0–1) and `kind` (arrow / ibeam /
hand). **The file is as confidential as the tape** (typed text is in it): keep it beside the recording, never
in the repo; the scaffold's `.gitignore` lists `events.jsonl` and `*.events.jsonl`.

## Capture (Windows) — `tools/record_events.py`

1. Start the screen recorder. 2. `python tools/record_events.py capture --out events.jsonl`. 3. Press **F8**
once: the screen flashes white for ~70 ms (two frames) — the clap. 4. Do the demo. 5. Press **F9** (or Ctrl+C).
6. `python tools/record_events.py align events.jsonl --video recording.mp4` finds the flash (first 160x90 grey
frame with mean ≥ 235 and a jump ≥ 60) and rewrites every `t`; precision within one video frame.

Polls the OS pointer and key state at 60 Hz through ctypes (nothing injected); keys become names and the
character the layout produces; Ctrl+K is one event with `mods`. Forgot the clap: `--clap-at <video seconds>` or
`--offset <s>`. Secondary monitor: `--origin X,Y`; recording not at screen size: `--scale-to WxH`.
**Privacy:** it is a key logger while it runs — use `--no-text` (shortcuts and special keys only) when a sign-in
happens in the take, and never type credentials while capturing. Windows only (exit 2 elsewhere); a macOS
recorder is deferred.

## No telemetry — `tools/cursor_track.py`

`python tools/cursor_track.py recording.mov --out events.jsonl --sheet out/cursor_sheet.jpg`

Decodes every k-th source frame (≤ 15 fps) at 0.64× the source width — an OS pointer is ~12x19 px on a 1×
display and the matcher needs ≥ 12 px. Matches ten hand-drawn templates (arrow 10/13/17/22, I-beam, hand) by
normalised cross-correlation of *signed* gradients (grey and edge-magnitude matching scored text like the
pointer); |score| equalises Windows and macOS polarities. Shape alone has no margin (pointer 0.58–0.71, text
and icons up to 0.67), so time decides: a background model absorbs static UI at 30 levels/frame and changing
pixels at 3; a candidate must have foreground under ≥ 8 % of its mask; candidates compete on score minus
distance from the predicted position (an alive track yields only to +0.10, a resting one to +0.05, a stale lock
to any foreground). Clicks are inferred: dwell ≥ 150 ms, then ≥ 2.5 % of a 160 px box changes by > 8 levels
within 300 ms; `down`/`up` 80 ms apart with a confidence.

**Measured:** synthetic tape 96.7 % of frames within 6 px (median 2.2 px), both clicks; a real 1× macOS tape
~50 % by eye on 12 crops (hovers found; fast motion and page loads lost). So: always open the `--sheet`, treat
the output as a proposal the author accepts in the storyboard, and prefer `record_events.py` whenever the
presenter is on Windows. Tracker events never produce `key` lines. Exit 0 when ≥ 60 % of frames tracked.

## The camera proposal — `tools/camera_from_events.py`

`python tools/camera_from_events.py events.jsonl --out out/camera_auto.json --rec-start 12 --film-t0 8.4 --clip-end 52`

Clicks and keys (placed at the last click within 5 s) chain into attention islands when ≤ 1.2 s and ≤ 220 px
apart. Each island gets a box (points + 120 px, never under 480x270) and the largest ladder zoom 1.0 / 1.35 /
1.6 / 2.0 whose viewport contains it under the upsample budget (≤ 1.6 = `motion_diag`'s WARN line; 2.0 only
with `--max-upsample 2.0`); a lone click is a glance and stays at 1.35. Timing follows the camera rules: push
starts 0.8 s before the first point and lasts 1.0 s, hold until 0.6 s after the last point and ≥ 2 s, ≥ 1 s
dwell between moves, pull back when there is room, pull back after 6 s of nothing, nothing in the last 1.5 s.
With `vo/<name>_words.json` present each push snaps to the nearest word onset within ±0.4 s — a push lands on a
spoken word, never 0.2 s after a click. Outputs: `camera_auto.json` (cues in stage px, a `moves_js` block to
paste into `shots.js` with `abs: true`, lint, budget) and `camera_auto.md` — one `- camera:` line per cue in the
storyboard grammar. The storyboard is where the author accepts, edits or deletes each one; the tool never
writes `shots.js`.

## Drawing it — `lib/cursor.js` and `lib/hud.js`

```html
<script src="lib/cursor.js"></script><script src="lib/hud.js"></script><script src="events_data.js"></script>
<script>
const SPANS = [{ t0: P.ask, t1: SEND, src: CLIPS.q.t0 }, { t0: SEND, t1: P.close, src: CLIPS.send.t0 }]; // film window → recording time
CURSOR.mount($('#camera'), window.EVENTS, { scale: 1.75, spans: SPANS, crop: CLIPS.q.crop });
HUD.mount($('#stage'), window.EVENTS, { bottom: 170, spans: SPANS });
</script>
```

`spans` map film windows to recording time (outside them both layers are hidden); `crop` is the source rect a
cropped clip shows. The cursor is our own 12x19 arrow at 1.75× with a soft shadow, riding a Catmull-Rom path
through the samples (`smooth: 1–2` for 15 fps tracker data), fading after 1.2 s of stillness, waking in
0.12 s; every click draws a stroke-only ring 28 → 64 stage px in 0.32 s (power2.out) and squeezes the arrow
10 % for 0.16 s. It lives INSIDE `#camera` as a sibling of the footage lane, so pushes carry it and the grade
gate still proves the pixels untouched. The HUD pill sits at bottom 170 stage px, above a two-line caption
lane: keycaps for shortcuts and special keys (0.9 s), a growing `typed` run for text (merge gap 0.6 s,
Backspace edits, 24-char tail, 0.8 s after the last key), one pill at a time; 0.26 s in on back.out(1.6) —
the one sanctioned overshoot — and 0.20 s out on power2.in. Both register with `MOTION.onSeek`; the scene
changes nothing in `frame(t)`. Rendered twice: identical frames. Rules: one pill, one ring, one cursor; a
lower third wins over the pill; scrolled pages follow the still, not the document — mount the cursor on
still/seq shots only.

## Dead air — `tools/idle_detect.py`

```
python tools/idle_detect.py raw.mov --t0 W0 --t1 W1 --js scenes/idle.js --clip send --sheet out/idle_send.png
python tools/idle_detect.py --selftest        # synthetic fixture, every kind within ±0.3 s, JSON twice identical (5–14 s)
```

Reads the recording once at 10 fps, grey, on a grid of 6 source px per analysis px (320x180 for 1080p;
400x210 / 520x310 for 2426- / 3160-wide captures so small UI survives). **The one number: change energy** —
3x3 box blur, then the mean absolute difference to the previous frame in grey levels. Measured on three real
product recordings (409 s): a static screen with a blinking caret or wandering pointer 0.00–0.11 (median
0.01); a scroll of a mostly-white page 0.25–3.2 (median 1.4; 20–1110 px/s); a visible UI action 0.6–12; a page
change 36–158. Thresholds sit in the gaps: idle < 0.6, page > 25. Spinners and typing are both below 0.6
globally (a 24 px spinner ≈ 0.03), so they are found in the 10x10 px cell map inside the quiet runs.

| kind | test | proposal |
|---|---|---|
| idle | energy < 0.6 for ≥ 1.5 s | ≥ 4 s: drop [t0 + 0.5, t1 − 0.5]; else 6× |
| spinner | ≤ 6 % of cells busy in ≥ 50 % of frames, rest quiet; patch autocorrelation peaks at 0.3–2.0 s (r ≥ 0.35); or a progress bar (only the leading edge changes) | 4× + a `working` caption hook |
| typing | narrow band (≤ 3 cell rows, ≥ 3 cols), 2–12 Hz, caret drifting right; slow pass for < 3 chars/s | 1.6× + `caret_follow` {box, caret:[[t, x]]} |
| scroll | row-profile cross-correlation over the changed columns, half-pixel shift, corr ≥ 0.85; wheel steps ≤ 0.5 s apart merge | keep 1× when ≤ 400 px/s, else 2× |
| page | energy > 25 and > 40 % of cells changed by > 12 | hard-cut candidate at t0 |

A busy cell must be active in ≥ 3 of its 10 surrounding frames, so a 1 Hz caret never counts; a title fading
in lights every cell and is rejected as progress. The shots consume `proposals.lane` (`[[t, rate]]`, 0.25 s
eases, `play: {at, rate: lane}`), `proposals.map` (`[[dt, u]]`, drops as vertical steps, `play: {at, map}`),
`caret_follow[].caret` (every 0.5 s; take every second sample so the ≥ 1 s dwell rule holds), `captions[]`
(`{t0, t1, hook: 'working'}`; the caption lane owns the wording) and `summary.saved_s`. The footage is never
touched. Exit 0 nothing to fix / 1 dead air found / 2 usage; `--exit-zero` for scaffold and doctor use. A clip with
heavy proposals is either wired as `IDLE.<clip>` in `shots.js` or carries `"accepted": false` next to the
proposal, so a reviewer can see the decision. Read the sheet: spans by kind on top, energy on a log scale with the 0.6 and 25 lines,
the proposed edit below.
