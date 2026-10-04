# Review pack and studio — iterate in seconds, approve from one file

Two tools that shorten the loop around the render. `tools/studio.py` is a local preview that shows any frame
of the scene instantly through the scene's own contract and takes one-frame "taps" through the real
renderer. `tools/review_pack.py` builds one offline HTML a stakeholder approves from, and its `--lock` writes
the sign-off into `STORYBOARD.md`.

## Studio — `tools/studio.py`

```bash
python tools/studio.py                              # serves the project at http://127.0.0.1:8765/ and opens it
python tools/studio.py --project ../my-film --port 8766 --no-browser --node-path ./node_modules
```

Stdlib only (`http.server` + `threading`), binds 127.0.0.1, serves the project under `/p/` (realpath-confined,
`Cache-Control: no-store`); exit 2 if the port is busy (pass `--port`). The UI lives beside the tool in `studio/`.

**What you see.** The scene in an iframe at its authoring size, 1280x720, CSS-scaled to fit; the studio calls
`window.__seek(t)` (full reset) and `window.__step(t)` (sequential) — the same contract `render_frames.js`
uses — so the picture is the scene's pure `frame(t)`, not an approximation. A HUD with `t`, frame / total,
phase (from `scenes/timing_<name>.js`), storyboard beat, live camera scale (read from `#camera`'s transform)
and the active seam. A words panel with the spoken word on the gold chip. A timeline with phase bands,
storyboard beats, seam windows as coral bands with the cut line, the camera scale trace per shot (from
`out/camera_curves.json`; `node scenes/lib/camera.js --curves` refreshes it) with establish windows in gold, a
ruler and the playhead. Guides as siblings of the iframe, never inside the scene: title safe (10 % inset),
action safe (5 %), the caption lane (bottom 17 %, y ≥ 598), an optional centre cross, a captions-off switch.

| key | action |
|---|---|
| ← / → | one frame back / forward (shift = 10) |
| space | play / pause from this t — the one place a real-time loop is allowed: it is a viewer |
| Home / End | first / last frame |
| T | tap: a 1920x1080 still of this frame through the real renderer |
| Q | QA quick: `gates/lint_scene.py --json` on the scene |
| G | toggle all guides · R reload the scene at this t · `?t=` opens at a time |

Every seek is frame-quantised (`round(t × fps) / fps`), so frame, phase and word agree with the render grid.

**Hot reload.** A watcher thread stats `scenes/**`, `lib/**`, `timing*.js`, `seams.json`, `STORYBOARD.md`,
`film.json`, `clips.json` and `broll/clips.js` every 500 ms (skipping `out/`, `node_modules`, `vo/`, `broll/`
frames). The page holds a long poll on `/changes?since=N`; when a file changes the iframe reloads with a
cache-buster at the SAME t, the manifest is re-fetched and a toast names the files. Measured wake-up:
0.03–0.4 s after the write.

**Taps: what ships, not what the preview shows.** The preview runs on your GPU with the browser's scaling. A
tap spawns `render_frames.js` for ONE frame: headless Chrome, software GL, DPR 1.5, fonts settled, scaled
to 1920x1080, TV range — the pipeline that renders the film. Because the renderer always starts at clock 0,
the tap writes a shim (`out/taps/_shim.html`) that iframes the scene with `?render` and forwards
`__seek(t) → __seek(t + T0)`; the one-frame mp4 is unwrapped to `out/taps/tap_f<frame>.png`. Two taps at the
same t are pixel-identical (verified); a tap costs ~4 s on an idle machine, far more when another render
shares the CPU. Taps are scratch (`out/taps/` is build output, never a deliverable); name the ones you keep
for the review pack `out/taps/NN_<label>.jpg` (beat number) or `t<sec>.jpg`.

**Cue resolution.** When `out/timeline.json` exists its resolved seam rows are used; otherwise `seams.json`
cuts (`P.nb`, `wt(ask,'typed') + 0.4`) are resolved with the same arithmetic as `lib/timeline.js` — numbers
and `+ − × ÷ ( )` only, parsed, never evaluated. Window defaults match `lib/seams.js`: cut-the-curve
0.34 / 0.42 s, zoom-through 0.20 / 0.50, inverse zoom-through 0.21 / 0.49; gl rows use `dur` and `split`.

```bash
python tools/studio.py --manifest        # the JSON the UI draws (sorted keys, no wall clock; byte-identical on an unchanged project)
python tools/studio.py --tap 14.0        # one still, JSON receipt {ok, t, frame, png, renderer:{gl, gl_renderer}} (exit 1 on failure)
python tools/studio.py --qa              # quick lint, JSON
python tools/studio.py --selftest [--with-tap]   # 14 checks (16 with a tap) on a synthetic fixture, ~2 s (≈ 9 s with the tap)
```

### Who may talk to the studio server
The studio binds 127.0.0.1 and answers GET only (POST is 405). Every request must carry a Host of `127.0.0.1:<port>`,
`localhost:<port>` or `[::1]:<port>`; a page on another site cannot forge that header, so a rebinding or cross-site page
never reaches the routes. The two routes that start a subprocess, `/tap` and `/qa`, also need the per-session token the
served page embeds in `<meta name="studio-token">` and sends back as `X-Studio-Token`, and when the browser adds an
`Origin` header it must be the studio's own. Anything else is 403; reloading the page refreshes the token. The selftest
covers the foreign Host, missing and wrong token, foreign Origin and POST cases.

## Review pack — `tools/review_pack.py`

```
python tools/review_pack.py build --project . [--film out/<film>.mp4] [--taps out/taps] [--qa out/qa_report.json]
python tools/review_pack.py --serve --project .              # http://127.0.0.1:8765 — Save posts comments.json
python tools/review_pack.py --lock --by "Name" --date 2026-10-02
```

One HTML, every image embedded as a data URI (640 px JPEG q82), no external request, byte-identical across
builds: ~52 KB for the six-beat Acme sample with four frames, plus ~25 KB per frame. It reads what exists and
marks what does not: `STORYBOARD.md` (the one parser; actual spans when `vo/<name>_phases.json` exists),
`BRIEF.md` frontmatter, a frame per beat (`out/taps/NN_*.jpg` or `t<sec>.jpg`, else `out/storyboard/NN.jpg`,
else a midpoint frame from `--film`), `claims.json`, the QA report (`out/qa_report.json`, or a saved
`qa_film.py` log), `out/timeline.json` (the ruler: beats coloured recorded / recreated / placeholder, solid
ticks = cuts, dashed = ledger seams), `media.jsonl`, `comments.json`, and (v5.1) `out/pairs/pairs.json` from
`gates/snapshot.py --pairs`: the first and last frame of every segment, shown under the beat whose span holds the
segment with the storyboard's `start:` / `end:` sentence beside each frame and **Approve start / Approve end**
buttons. Save writes `approvals.json` beside the pack (`POST /approvals` when served); the header counts END
approvals; an unapproved END and a pair whose two frames are the same picture are honesty flags. Once
`approvals.json` exists, `tools/storyboard.py check --build` refuses while any END frame is unapproved
(→ `frame-pairs-and-approvals.md`).

**Honesty flags come first** because they decide the sign-off: a placeholder beat, a recorded beat without a
clip, a missing `claims.json`, a claim without a source, a dropped narration line, a failing claims /
over-claims / required-lines / hygiene / CREDIT gate, an UNKNOWN or non-commercial licence, a still-open item,
a brief without an honesty line. Each beat card shows the frame, the plan fields, the claims spoken in that
beat and a comment box (name, status open / resolved). Opened as a file, Save downloads `comments.json`;
served, it POSTs to `/comments` (127.0.0.1 only, ≤ 1 MB). `--strict` exits 1 on any FAIL flag.

**The server trusts only its own page.** `--serve` binds 127.0.0.1, but a page from any other origin in the same
browser could still try to write into the pack, so every request is checked: the `Host` header must be
`127.0.0.1:<port>` or `localhost:<port>` (GET and POST); a POST must be `application/json`, must come from an
`Origin` of `http://127.0.0.1:<port>` or `http://localhost:<port>`, and must carry the per-session random token
the served `index.html` embeds (`<meta name="review-token">`, sent back as `X-Review-Token`). Anything else is
refused with 403 before a byte is written; the body is drained first so the client sees the status, not a reset.
The token changes on every start; a pack opened as a file never needs it (Save downloads the JSON instead).

`--lock` is the end of the loop: it refuses while any comment is open (`--force` overrides) and writes
`signed off by`, `signed off date`, the pack's sha256 and the comment tally into `## Locked`, so
`storyboard.py check --build` and the `review lock` gate pass only on a reviewed plan. Re-signing replaces the
bullets; nothing else in the file moves. The date defaults to today — the one deliberate wall-clock read,
because a sign-off date is the real date; the selftest always passes `--date`. The pack is not a source of
timing truth: the narration clock is.

## The loop

Edit → studio shows the frame (< 1 s) → **T** taps the frames you will show → `build_film.py` → `qa_film.py`
→ `snapshot.py --pairs` → `review_pack.py build` → send `out/review/index.html` → approve END frames, resolve
comments → `--lock` → whole-cut notes decided (`tools/review_notes.py`, → `whole-cut-review.md`) → export. Exit codes
everywhere: 0 ok · 1 findings / open comments · 2 usage.
