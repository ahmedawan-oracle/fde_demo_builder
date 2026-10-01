# Blocks catalog — `lib/blocks.js` (`window.BL`, v4)

Pure `frame(t)` builders for **recreated** cards, openers, call-outs and the "product is thinking" beat. Every
block is `BL.<name>.build(host, opts) → state` once, then `BL.<name>.draw(state, t[, win]) → plain state` from
the scene's `frame(t)`; `BL.<name>.calc(t, opts)` is the pure core. No CSS transitions, no rAF, no wall-clock,
no `Math.random` (seeded LCG only). Times are **absolute film seconds** — pass `wt(phase, word)` values.
`BL.installStyles(tokens?)` injects the default `.bl-*` stylesheet once (override in the scene).
Example scene: `scripts/film/scenes_blocks_demo.html` (four blocks + a flash on a 10 s clock, fictional Acme).

## The envelope law (shared by every block)

`BL.env(t, {t0, t1, exit:'none'|'fade'|'up'}, IN, OUT=0.45) → {phase, u, k, lt, …}`

- Fixed **IN**, elastic **HOLD**, **OUT only when `exit != 'none'`** (default none: our hard cuts are the transitions).
- Window shorter than IN+OUT → phases compress proportionally (`k`); the timeline is never time-scaled.
  Schedules are authored on `lt = (t − t0) / k`, so "the pulse at 2.1 s" compresses with the window.
- Sync points sit at fixed offsets into IN, never inside the HOLD. Every `calc` returns `sync:[{id, t}]`;
  `BL.collectSync(...states)` merges them for `out/timeline.json → sync` (SFX routing, see integrator notes).
- Hold drift = two explicit finite tweens then 0.25–0.35 s stillness (`BL.holdDrift`), or integer-cycle
  micro-drift that is exactly zero at both ends (`BL.driftZero(t, t0, dur, [2,3], [0.0016,0.0011], 0.35)`,
  only when the hold ≥ 1.2 s). Sanctioned aliveness: `BL.jitter` (scale 0.008–0.015, 2–3 px, periods
  2.1/1.9/2.4 s, amp/√N, fades over the last 20 %).
- `BL.rows(fn, dur, fps=30)` bakes a frame-quantised table so `__seek` and `__step` show the same digit.
- Eases in `BL.E`: power3.out by default ("smooth over bouncy"); `backOut(s)` only where a row says so.

## Honesty column

| Column | Meaning |
|---|---|
| **R** | recreated scenes only (openers, cards, closers) — never inside the demo act |
| **O** | may overlay real footage, but only as an overlay that leaves product pixels untouched |
| **C** | call-out that quotes a real on-screen figure (must be in `claims.json`) |

## Catalog

| Block | Use | API (opts → state) | Measured numbers | Where |
|---|---|---|---|---|
| `kpi` | a spoken number landing on its word | `{t0, t1?, land, value, from=0, dec, prefix, suffix, token?, label, fill:{kind:'bar'\|'ring', pct}, pulse=true}` → `{op, y, scale, text, fillU, suffixOp, suffixX, labelOp}` | arrive 0.38 s (op power2.out; y 2.2 % H + scale 0.98→1 power3.out); count = `land − t0 − 0.38` (min 0.7; 1.72 when no land) sine.inOut from a 30 fps table; pulse 1.07 / 0.165 s power3.out, back 0.165 s power2.out; suffix slides 8 px after the land; label 0.15–0.45 s; fill shares the count's ease; tabular-nums, weight 600, fixed `min-width` in `ch`; sync `land` | R, C |
| `count` | odometer drop-in | `BL.count(from, to, t, t0, dur=0.7, dec)` → string (memoised table) | sine.inOut, exact final token | R, C |
| `chatReveal` | question → thinking → streamed answer → receipt | `{t0, t1?, question, answer (string \| paragraphs[]), send?, answerEnd?, receipt, seed=7, variant='human'\|'beat'}` → `{composer:{text, caret, sendOp}, question:{op, scale}, dots:{op, dy[3]}, ink[], receipt:{op}}` | keystrokes 33–200 ms (mode 67–100, mean ≈ 90), 2 chars on the first beat, caret 0.533 s; send = tDone + 0.167 s (compress only on overflow); bubble 0.167 s; dots at send + 0.3 s: alpha 0.49→1 in 13 × 33 ms, bob −9 px / 0.28 s × 5, gone at +0.567 s; stream starts +0.633 s, word gaps 0–367 ms with ~15 % zero bursts, grey #767676 → ink over 0.267 s linear, last word at `answerEnd`; receipt +0.467 s. Beat variant: 50 ms/char, 110 ms space. Neutral shell — no Claude/ChatGPT/iOS trade dress; sync `send`, `stream`, `answer-landed` | R |
| `keystrokes` / `prompt` | typed text tables | `BL.keystrokes(text, t0, {seed, variant, endAt})`, `BL.prompt(text, t0, {cues:[{word,t}], correction:{word, wrong}, seed, variant='chunk'})` → `{at(t), caret(t), tDone, wordStart[]}` | chunk: 1–3 chars/chunk, 0.1–0.2 s/word; uniform 55 ms/char + 110 ms/word; correction: wrong word, 0.4 s realise, 50 ms backspaces, retype; cues anchor word N start, compress only on overflow; integer blink cycles then solid | R (typed text must match the narrator verbatim) |
| `thinkDot`, `stream`, `bubble`, `dots` | the chat primitives, exposed | pure functions, see source | as above | R |
| `stack` | exploded architecture (sources → lakehouse → ontology → agents) | `{t0, t1?, layers:[{label, color, glyph?}], unit=56, open=0.3, stagger=0.06, land?:[t…] \| landAt=1.25 + 0.45·i, close?, cx, cy, accent}` → `layers[{lift, z, labelOp, labelX, labelY, ink, leader}]` | plates 4.2 × 0.22 units, gap 1.55, edge 0.08; `rotateX(55°) rotateZ(−45°)`, orthographic (CSS 3D, no WebGL/CDN); open 0.3 s + 0.06 s stagger, eased-out with a soft first frame; bottom plate static, top travels furthest / leaves first; labels: leader + dot from the right corner (+90 px, text +24 px, whole-pixel translations); close 0.6 s / 0.05 s stagger; glyph grey #8b909a → accent in focus; sync `open`, `label-i` | R |
| `chart` | one chart, one message | `{t0, t1?, type:'bars'\|'line'\|'donut'\|'progress', data[], labels[], emphasize, token, unit, land, max, w, h}` → `{op, stageY, axisU, bars[], lineU, areaOp, donut[], labels[], callout:{op, scale, text}}` | IN 3.3 s rescaled so `land` = 3.05 s: stage 0.5, axis 0.15–0.55, build 0.55→2.15 (0.85 s each, reading-order stagger), labels from 0.85 (+0.08), callout pop 2.35 + 0.7 s roll landing the **raw token** at 3.05; line by measured `getTotalLength`; accent = the one emphasised datum; sync `callout-landed` | R, C |
| `race` | bar chart race | `{t0, periods[], series[{name, values[]}], barCount=6, periodDur=2, prefix, suffix, dec}` → `{rows[{pos, w, text, lead, op, z}], ticks[], period}` | 10 keyframes/period, ranks baked, rows solved from rank (swap over periodDur/10, smoothstep), axis continuous with 6 % headroom, nice ticks 1-2-5, leader painted in front, accent = current leader only, flat fill | R |
| `deviceFrame` (`browserFrame`) | neutral chrome around a recreated UI / cropped still / roadmap screen | `{t0, t1?, chrome:'browser'\|'window'\|'phone', title, w, h}`; `state.screen` is the slot | settle 0.9 s: rise 4.5 % H, scale 0.965→1 power3.out, op over 0.66·IN; hold drift −0.5 % H as two tweens then 0.35 s still; phone keeps the top 8 % clear; hairline + muted dots + pill, no traffic-light colours | R (never around real full-screen footage) |
| `screenSwap` | swap two screens in a slot | `BL.screenSwap(t, {at, dur=0.55})` → `{aOp, bOp, bY}` + `.apply(elA, elB, s)` | A fully gone (power1.in, first half) before B rises 1.6 % H (power2.out); no frame with two partial screens; sync `swap` | R / O (two real stills) |
| `beforeAfter` | honest comparison of two real stills | `BL.beforeAfter(t, {at, dur=1.05, rest=0.5})` → `{split, dividerOp, clip}` | wipe from the left 1.05 s power3.out to `rest`; divider hidden until the wipe; both stills share one crop; sync `wipe-land` | O |
| `screenRail` | 2–5 screens on a rail (roadmap, labelled) | `BL.screenRail(t, {t0, screens, cues[], pitch=520, throwDur=0.6})` → `{screens[{x, scale, op, active}], captionIndex}` | neighbours 0.86 / 0.55 dim; throw = power4.in half → power4.out half (peak speed at the midpoint); last throw lands with stillness | R / O (roadmap label mandatory) |
| `code` + `codeType`, `sweep`, `diff`, `scrollTo` | recreated code / pointing at one line | `build(host, {lines[], lineH=24})`, `draw(st, t, {t0, type:'typing'\|'sweep'\|'diff'\|'scroll', at, line, removed[], added[]})` | typing 28 ms/char, 0.12 s glyph fade, whitespace instant, caret glides to each glyph's edge; editor fade 0.45 s, settle 0.985→1 over 0.5 s; sweep 0→line+18 px over 0.9 s power2.inOut, others dim 0.45; diff 46→0 / 0.55 s, +0.15 s, 0→46 / 0.6 s; scroll 1.7 s power2.inOut, dim 0.35 over 0.5 s, box 0.45 s from −0.35 s | R; `sweep`/`scrollTo` are O as overlays over a stitched real page (repaint, never rewrite real code) |
| `stateRail` | agent working-state chips | `{t0, t1, states[], times?[], enter=0.3, gap=0.05, badges[], badgeState=1}` → `{chips[{state, enterU}], badges[{scale, op}], active}` | chips enter 0.2–0.45 s / gaps 0.02–0.08 s; advances are instantaneous data-state snaps (seek-exact); active = ink on surface, done dims by colour-mix (never opacity), pending hollow; badges pop 0.25 s keeping their slot at scale 0; default cues spread to ~1 s before `t1`; diegetic loops must die the frame the answer lands; elapsed-time chips stay honest ("5 min compressed") | R / O |
| `hud` | quiet telemetry readouts | `{t0, t1?, readouts[{label, value, accent?}], cues?[], standIns=false}` → `{bracketU, readouts[{text, op, accent}]}` | brackets from 0.12 s over 0.5 s; ticks at 1.0 + 0.28·i s, 0.5 s each, resolve left→right in 8 steps; one accent readout; then dead still; unresolved glyphs show `·` — same-class stand-ins only with `standIns:true` and never on a claimed figure; sync `readouts-settled` | R / O (values from the recording) |
| `agentTag` | agent cursor + typed step label | `{t0, steps[], targets[[x,y]], start, perTarget=1.35, typeMs=22, done?}` → `{x, y, label, dotScale, checkU, ring}` | 22 ms/char ≤ 0.3 s, 1.35 s per target (0.35 typing + 1.0 s power3.out arc, bend 0.12), ring at arrival, live dot 1.2 s breath, check back.out(2.4) 0.3 s at `done`, pulses die that frame | O only at recorded click positions/times (log it) |
| `flash` | editorial hand-off card → footage, or the trust beat | `BL.flash(t, tHit)` + `flash.build(host)` / `flash.draw(st, t, tHit)` | wash 255,253,250 → 0.92 in 0.04 s power4.in, clear 0.18 s power3.out; core 0.86→1 at −5° in 0.05 s → 1.18 fading 0.34 s; sweep −12→8 % in 0.04 s → 28 % over 0.3 s; ≤ 0.4 s, inset −12 %, screen blend; max one per act; register as `seam`, keep scripted cuts ≥ 0.5 s away | R→footage |
| `freezeDress` | "this is the number" on a frozen real screen | `{at, rect, badge, flash=true}` | snaps on (no tween), one exposure flash 0.55→0 over 0.28 s, never a strobe; mask first, dress second | O, C |
| `hardCut`, `recHud` | connector streak; REC/time label | `BL.hardCut(t, tSwitch)`, `BL.recHud(t, {start, clock0})` | streak scaleX 0.35→1.6 / 0.12 s power4.in, 14 px blur, 1.35 brightness; incoming lands at the switch, ±24 px settle 0.4 s, 1.02 push / 1.17 s; REC blinks 0.55 s (1 / 0.25), hh:mm:ss floored | O |
| `titleLockup` | kicker / wordmark / rule / label | `{kicker, wordmark, label, accent, fg, bg}` + `win {t0, t1, exit}` | IN 1.80 s: kicker 0–0.45, wordmark 0.96→1 over 0.25–1.10, rule 0.90–1.45 by measured dash, label 1.30–1.80; then truly still; kicker/label ink = 62 % fg over bg (`BL.ink62`) | R |
| `ctaClose` | the action-only close | `{line, button, accent}` + `win {t0}` | words rise 24 px + fade power3.out, 0.10 s stagger; capsule from 0.85 at 0.72 s, one restrained overshoot, settled by 1.32 s; dead still; keeps the bottom 16.67 % free for the credit | R |
| `wordSweep` | karaoke ink across a sentence | `BL.wordSweep(t, t0, t1, n)` → ink[] | one linear scalar | R / captions |
| `servo` / `focusZoom` | camera-servo law | `BL.servo(t, {t0, dur=1.1, anchor, s=1.6, target?, from, stage})` → `{s, cx, cy, capped}` + `servo.transform(c)`; `BL.focusZoom(t, {t0, t1, cue, anchor, s, target, halo})` | one world wrapper, T = −offset × S; headroom cap: target ≤ 88 % of the canvas; cover clamp; 1.1 s power2.inOut on its cue; halo 0.75 s from halfway; drift zero-ended then 0.35 s still | O (over the clip wrapper) |
| `spring`, `follow` | screen-recording auto-zoom | `BL.spring(aim, {omega=6, fps=60, sub=4, dur, t0})` → `pos(t)`; `BL.follow({t0, start, clicks[{t,x,y}], zoom=1.8, exitAt})` → `{cam(t), cursor(t), ring(t), press(t)}` | aim 60 % toward the next click (the push leads); critically damped ω = 6 at 60 Hz × 4 substeps, pre-integrated once per shot; zoom 1.8 over 0.85 s power3.inOut; arcs bend 0.12 power3.out; exit 1.0 s | O at recorded clicks only |
| `clickRing`, `press`, `cursorArc`, `cursorLeave` | click grammar | pure | ring 12→44 over 0.35 s fading; press 80 ms down / 200 ms up, cursor 0.9, target 0.96 in lockstep; the cursor leaves the frame physically (0.4 s power2.in), never fades in place | O |

## Worked example (fictional)

```js
BL.installStyles();
const kpi = BL.kpi.build($('#kpiHost'), { t0: P.open, t1: P.nb, land: wt('open', 'hours'), value: 23.75, dec: 2, suffix: 'h',
  label: 'Unreconciled hours · last quarter', fill: { kind: 'bar', pct: 0.72 }, exit: 'fade' });
const rail = BL.stateRail.build($('#railHost'), { t0: P.think, t1: P.answer, states: ['plan', 'query', 'reason', 'answer'],
  times: [wt('think', 'plan'), wt('think', 'query'), wt('think', 'reason')], badges: ['orders', 'shifts'], badgeState: 1 });
function frame(t) { BL.kpi.draw(kpi, t); BL.stateRail.draw(rail, t); /* … footage lane … */ }
window.__sync = BL.collectSync(BL.kpi.calc(0, kpi.o, kpi), BL.stateRail.calc(0, rail.o));
```

Rules of thumb: reveal each element on its spoken word across the back half of the shot (never dump the canvas
in the first 25 %); one accent with one meaning per scene; charts and stacks recreate the *idea*, never the
product UI; a real chart on screen stays real pixels (push/highlight it, do not redraw it); the number in a
`kpi` or `chart` callout must equal the on-screen figure listed in `claims.json`.
