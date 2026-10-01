# Camera moves (v4) — `lib/camera.js` (CAM) + `gates/motion_diag.py`

The v3 camera knows one verb: a 0.9–1.4 s sine push after an establishing hold. CAM adds the rest of a
camera's vocabulary as pure functions of the film clock, keeps every pixel real (footage is only ever
scaled, translated, blurred or dimmed — never tilted, warped or re-drawn), and ships a gate that reads the
camera back off the rendered frames. Everything below is fictional ("Acme"). `G.camState` / `G.applyCam`
and `footage.js` are unchanged; CAM understands a superset of the shot fields.

## Measured rules (defaults in `CAM.RULES`)

| Move | Numbers |
|---|---|
| Push / pull (zoom) | 1.0–2.0 s (under 0.8 s teleports, over 2.5 s drags); start 0.5–1.5 s after the layout lands; dwell >= 1.0 s after it settles, 1.5–2.5 s at a hero moment; later phases settle deeper |
| Ease law | power4.out / expo.out on dives, landings, reveals; power2/3.inOut on repositioning; never spring, back or elastic; four identical pushes read as a slideshow |
| Punch | 0.14–0.25 s power4.out, <= +25 % scale, then hold >= 0.8 s; never two punches inside 1 s; under 0.5 s reads as a cut, which is the point |
| Perceived scale | < 5 % imperceptible; 1.05–1.15 comfortable emphasis; 1.15–1.30 focus a region; 1.5–2.5 dramatic; 3+ fills the frame |
| Zoom budget | target <= 88 % of the stage at peak (`fitScale`); upsample = s x 1920 / source px spanning the stage: WARN > 1.6, FAIL > 2.0 (a 1920-px recording on a 1080p output: the camera scale IS the upsample) |
| Whip-pan | nudge curve 10 / 65 / 25 % of the distance over 20 / 18 / 62 % of the time (power3.in, linear, power4.out; tail >= 3x ramp); blur 0 -> 18 px -> 0 on 'X 0' (brief whip may touch 24); 0.3–0.5 s; swap the content in the burst, read after the tail |
| Zoom-through | outgoing scale 1 -> 2.2, blur 0 -> 8, opacity -> 0 over 0.4 s power3.in; incoming 0.6 -> 1, blur 8 -> 0, starting +0.15 x dur, power3.out |
| Seam grammar | one primary (hard cut on the word) for 60–70 % of changes + 1–2 accents (whip on an act change, zoom-through on the product entry or payoff); <= 2 kinds, accents <= 25 % of cuts; never fade-out-then-fade-in |
| Match / velocity cut | solve the incoming s0/c0 so the shared element keeps its stage rect; exit .in, entry .out (power2.out, 1.0 s) so the fastest points meet at the cut |
| Focus pull | blur 8 soft / 16 default / 24 heavy; dim 0.55 default (never < 0.35 — reads as removed); shift 0.5–1.2 s power2.inOut; rack = two tweens on one window; refocus before any hand-off |
| Dolly zoom | P(t) = subjectScale x d(t), rig translateZ(P - d); d0 1400 (600–3000), ratio 2 (1.1–4), power2.inOut, 4 s; planes at >= 2 depths (-560 … -3200), d + N > 0; recreated cards ONLY |
| Zoom-out reveal | open tight (<= 2.0 on 1920-px footage), ONE outward expo.out / power4.out pull (0.5–1 s burst or a long continuous pull), lock; no zoom-in anywhere in the shot; the pull ends before the shot does |
| Caret follow | pin the caret at 0.5–0.75 of the frame with cx = max(cx, caretX - (frac - 0.5) W / s) — continuous by construction, never a threshold branch |
| Idle | drift 2–8 px x / 1–4 px y, frequency ratio 1.2–1.5 (equal = mechanical diagonal), 1–3 cycles per scene; breathing <= 1–2 %; footage idle is camera-only and <= 1 % |
| Freeze hit | flash 0.55 -> 0 over 0.28 s power2.out (< 0.3 s total so blank-after-cut is unaffected); dressing snaps on, settles to 0.75 over 0.35 s; +2 % over 0.14 s; connector: 0.12 s stretch 1.35 / 0.92, switch at +0.14 s, recover 0.18 s |
| Travel blur | stdDeviation rides the camera speed: 0 under one element-width per frame (24 px), peak 18 by 4x that, cap 20 on a full-frame wrapper; never on a reveal-typing shot |
| Frames | stepped holds quantize on the integer frame index (`frameIdx`, `stepHold`), never on seconds; parallel workers differ by +-1 level at chunk boundaries, so pixel gates sit above 0.25 |
| Onion skin | 9 ghosts (max 60), alpha 0.14 -> 1.0 oldest -> newest; even spacing = constant speed, clustered = settle, gaps = fast travel; trust painted pixels over logs |

## API (window.CAM, also `require()`-able in node)

- Eases: `CAM.EASE = {out, io, p2, p3, p4, expo, p2in, p3in, p4in, p2io, p3io, lin}`, `CAM.easeOf(nameOrFn)`.
  Moves may name any of them in `ease`; footage.js's own camFor only knows `io`, so render shots that use
  the new eases through `CAM.resolve` (below).
- Pose: `CAM.pose(sh, t)` raw; `CAM.resolve(sh, t, {caretX, stage})` = pose + caret follow + idle + stage
  clamp; `CAM.applyPose(el, pose, {streakNode, streak})` writes the wrapper transform (+ the blur).
- Punch: `CAM.punchTo(t0, s, rect, dur=0.22, abs=true)`, `CAM.punchOut(t0, dur=0.22)` -> moves with `ease:'p4', punch:true`.
- Budget: `CAM.fitScale(rect, fill=0.88)`, `CAM.pushToFit(t0, dur, rect, fill, ease)`, `CAM.sourceWidth(clip)`,
  `CAM.upsample(s, clip)`, `CAM.maxScale(clip, cap=2.0)`, `CAM.budget(sh, clip)` -> `{peak, upsample, maxScale, level, headroomFails}`.
- Seams: shot field `enter: {kind:'whip'|'zoomthrough'|'stretch', dir, dur, peak}`; `CAM.seam(t, sh)` ->
  state; `CAM.applySeam({prev, next, blurNode, stage}, state)`; `CAM.ensureStreakFilter(doc, id, target)`
  creates the SVG filter once; `CAM.seamCutAt(sh)` / `CAM.seamDur(sh)` for export_timeline; raw curves
  `CAM.nudge(x)`, `CAM.whip(t, o)`, `CAM.zoomThrough(t, o)`, `CAM.connector(t, t0)`.
- Match cut: `CAM.matchCut({pose, rect}, {rect})` -> `{s, c}`; `CAM.toStage(rectSrc, k, crop)`;
  `CAM.velocityAt(sh, t)`; `CAM.velocityMatch(outSh, t1, startPose, {dur:1.0})` -> an entry move or null.
- Focus: `CAM.focus(t, {t0, dur, blur, dim, end, release})` -> `{u, blur, veil, active}`; `CAM.rack(t, o)`;
  `CAM.applyFocus({src, blurImg, veil}, state, rectStagePx)` (clip-path evenodd hole; returns a decode Promise).
- Dolly: `CAM.dolly(t, {t0, dur, d0, ratio, dir, ease, subjectScale})` -> `{perspective, rigZ, d, u}`; `CAM.applyDolly(lens, rig, st)`.
- Reveal out: `CAM.revealOut(sh, {s0, c0, at, dur, ease:'expo'})` or author `sh.revealOut` directly.
- Caret: `CAM.followCaret(pose, caretX, {frac:0.6})`; `CAM.caretX(sh, T, t, k, ox)` from FOOT.REVEAL.
- Idle: `CAM.idle(t, t0, {ax, ay, ratio, cycles, dur, ds})`, `CAM.withIdle(pose, drift)`, `CAM.pushLong(t0, dur, s, c)`.
- Hit: `CAM.hit(t, t0)` -> `{on, flash, settle, scale}`.
- Streak: `CAM.speed(a, b)`, `CAM.streak(pxPerFrame, {peak, cap, min, axis})`, `CAM.travelBlur(sh, t, {fps})`.
- Frames: `CAM.frameIdx(t, fps)`, `CAM.stepHold(t, n, fps)`, `CAM.seqSchedule(sh, clip, fps)`.
- Ladder: `CAM.ladder(sh)` -> `{legs, holds, shape}`; `CAM.lint(SHOTS, {cuts, rules})` -> `{items, fails, warns}`;
  `CAM.trace(sh, {T, CL, HL, fps})` -> 30 fps samples + speed + scheduled-motion windows.
- CLI: `node scenes/lib/camera.js --curves scenes/timing_<name>_data.js scenes/shots.js broll/clips.js`
  -> `out/camera_curves.json`, `out/camera_report.json`, a console table; exit 1 on a lint FAIL or a budget
  overrun. Run it after every `gen_vo_multivoice.py` (word-keyed times move) and before the render.

## Gates (`gates/motion_diag.py`, auto-loaded by qa_film.py)

| Gate | Rule |
|---|---|
| `motion traced` | per camera leg: measured pixel change (10 fps, 320x180 grey) integrated over the move must reach 30 % of the change the scripted scale/shift would produce on the frames' own content (frame k warped by the scripted move, only where defined; judged when that expectation is >= 0.3 %) — else FAIL "camera did nothing". FAIL when > 4 % change happens with no camera (<= 1 px/frame), no scheduled window (scroll / seq / reveal / stream / highlight / seam / focus / lower-third / `motion.allow`) and no cut within 0.15 s. WARN on a scripted velocity jump > 3x its neighbours. Also recovers the camera from the pixels (Fourier-Mellin scale + phase-correlation shift) into `out/qa/camera_measured.json`. |
| `zoom budget` | FAIL above `zoom_max` (2.0) upsample or a pushToFit target > 88 % of the stage; WARN above `zoom_warn` (1.6). |
| `seq quantized` | each source frame of a seq is shown for exactly the output frames its rate implies (rate 1: once — never 0 or 2); frozen output frames inside the real-motion window are listed as detail. |
| `onion sheets` | `out/qa/motion_<shot>.png`: ghost blend + filmstrip + the scripted camera window in miniature. Open it first when a push "does not feel right". |

qa.json: `"zoom_max": 2.0, "zoom_warn": 1.6, "motion": {"fps": 10, "min_change": 0.3, "max_unscripted": 4.0,
"disc_ratio": 3.0, "cam_min": 1.0, "dead_ratio": 0.3, "cut_pad": 0.15, "samples": 9, "allow": [[t0, t1]],
"mask": [[x, y, w, h]]}` (mask = stage-px rects of recreated screen-space overlays to ignore).
Self-test: `python gates/motion_diag.py --selftest`.

## Worked example (fictional Acme film)

```js
// shots.js — a punch onto the figure the voice names, a whip between two real screens, a focus pull
const KPI = [1240, 90, 560, 240];                                  // source px of the "412 late orders" tile
const k = 1280 / 1920, KPI_ST = CAM.toStage(KPI, k);               // -> stage px (abs)
root.SHOTS = root.FOOT.fullscreen([
  { t0: P.overview, t1: P.detail, clip: 'overview', s0: 1, c0: [640, 360], establish: { hold: 0.9, dur: 1.2 },
    moves: [ CAM.punchTo(wt('overview', 'four') - 0.05, 1.22, KPI_ST),          // 0.22 s power4.out, +22 %
             CAM.punchOut(wt('overview', 'four') + 1.1) ] },                      // hold 1.1 s, then back home
  { t0: P.detail, t1: P.ask, clip: 'detail', s0: 1, c0: [640, 360],
    enter: { kind: 'whip', dir: 'left', dur: 0.45 },                              // the act-change accent
    focus: { t0: wt('detail', 'row') - 0.1, dur: 0.8, end: P.ask - 0.4 },        // blur + dim all but the row
    idle: { ax: 3, ay: 1.5, ds: 0.005 } },
  { t0: P.ask, t1: P.send, clip: 'q', reveal: RVQ, followCaret: { frac: 0.6 }, s0: 1.3, c0: [640, 430] }
], VIEW);
```

```js
// film.html frame(t): render through CAM (footage.js draws the pixels; CAM frames them)
const sh = lane.shotAt(SH, t); let c = lane.draw(sh, t);
const caret = sh.followCaret ? CAM.caretX(sh, T, t, kOf(sh.clip), CLIPS[sh.clip].crop[0]) : null;
const pose = CAM.resolve(sh, t, { caretX: caret });                         // named eases, punches, idle, clamp
CAM.applySeam(seamEls, CAM.seam(t, sh));                                    // whip / zoom-through / stretch
CAM.applyPose(camEl, pose, { streakNode: streak, streak: CAM.travelBlur(sh, t) });
CAM.applyFocus(focusEls, sh.focus && CAM.focus(t, sh.focus), hlRectStage); // the hole follows the camera
```

Honesty: a punch, whip, focus pull or reveal never invents a pixel; the dolly zoom is for recreated cards
only; the whip's incoming screen must be the recording's own next screen, never a re-ordered one. Zoom-out
reveals on footage open at <= 2.0, so pick a detail large enough to fill the frame at that scale.
