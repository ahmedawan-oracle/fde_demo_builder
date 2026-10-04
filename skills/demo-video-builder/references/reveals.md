# Reveals — the first and last three seconds (`lib/reveals.js`, `REVEAL`)

How a film brings the first real still onto the stage and takes the last one off. Built on MOTION/GSAP.
Everything below is measured on the 1280x720 stage at DPR 1.5; the still is the footage lane's own file
(`broll/<clip>/f_001.jpg`), so the lane can take over on one frame.

```html
<div id="reveals"></div>   <!-- stage sibling after #camera: z 9, above the lane, below #ovl; inset 0, overflow hidden -->
<script src="lib/reveals.js"></script>
<script>
const RV   = REVEAL.host($('#stage'));
const hero = REVEAL.mount(RV, { still: '../broll/nb/f_001.jpg' });                 // the lane's first median still
let dive;
MOTION.block('opener', tl => { dive = REVEAL.heroDive(tl, { el: hero, land: F.openEnd }); }, { start: 0, end: F.openEnd + 1, hide: false });
F.openEnd = dive.end;                                                               // the lane takes over on dive.frame
const last = REVEAL.mount(RV, { still: '../broll/send/f_last.jpg' });
MOTION.block('closer', tl => REVEAL.pullBack(tl, { el: last, at: F.close, exit: 'hold' }), { start: F.close - 1, hide: false });
function frame(t) { MOTION.seek(t); applyCam(t); /* … */ return pend.concat([REVEAL.pending()].filter(Boolean)); }
</script>
```

## The hand-over contract

Every reveal returns `{ at, dur, end, frame }`. `end` is snapped to the frame grid and `frame = round(end × fps)`.
The footage shot after a dive, an assemble or a wipe starts at `end` (`FILM.openEnd = dive.end`); the shot
before a `pullBack` stops at its `at`. On the hand-over frame the plate sits at identity over the target rect
and the lane draws the same file at scale 1; the frame before is already within 0.2 % of identity (power3.inOut
tail), so the motion ends and the lane begins without a visible join. Pass `land: wt('phase', 'word')` instead
of `at` to put the landing on a spoken word. `REVEAL.plan({kind, at|land, …})` computes the same receipt in
node so `shots.js` can take `t0` from it before the scene exists.

## The five reveals

| Helper | Numbers | Use |
|---|---|---|
| `heroDive(tl, {el, at\|land, dur 0.9})` | scale .62 → 1, perspective 1400, rotationX 6°, rotationY −8°, power3.inOut; hairline 1 px cream .42 and a soft shadow (0 40px 90px −20px) fade over the last 25 % | the opener: the product arrives as a floating plate and flattens into the lane |
| `pullBack(tl, {el, at, dur 0.9, exit 'hold'\|'fade'})` | the same pose in reverse from the frame the lane stops; `hold` lets the close card compose around the lifted plate, `fade` 0.35 s | the closer (the reserved z−1 arrival) |
| `assemble(tl, {el, at\|land, dur 1.2, particles 6000, seed, order, focus})` | 4000–9000 particles (6000 → 103x58 cells of 12.4 px), colour = the still box-filtered to the grid; flight 50 % of the window on power3.out; launch spread 40 % (65 % distance from the focus + 35 % seed); scatter 0.55–1.45 half-diagonals, curl ±0.30, size .35 → 1.06 cells; all landed by 90 %; the last 10 % cross-fades canvas → real `<img>` | an opener for a data-heavy screen: the UI compiles out of noise |
| `irisFrom(tl, {el, target, at\|land, dur 0.5, origin {x, y} %, shape 'circle'\|'squircle'})` | power2.inOut from a control's position, radius to the farthest corner, feather 24 px (circle = feathered radial mask; squircle = clip-path polygon, n 4, 64 points, hard edge); click ring 44 px / 0.36 s / 2 px coral on the same frame | a state change caused by a click |
| `lightWipe(tl, {host, el, at\|land, dur 0.7, angle −14, width 220})` | power2.inOut; cream band, screen blend, opacity peak .85 × sin(πu)^0.6; the still is uncovered under the band's trailing edge; `card` cuts out on `end` | card → still without a cut |
| `matchCutHandover(tl, {from:{el, rect}, to:{el, rect}, at, mode 'uniform'\|'stretch', settle})` | `from` cuts out, `to` cuts in on frame `at` with `fit(from.rect, to.rect)` (uniform scale, centred; `stretch` warns above 1 % aspect mismatch) | a recreated preview becomes the real screen |

## Rules

- **Real footage is sacred — and reveals are the one sanctioned exception to the 0.5 s rule.** A reveal may
  touch the FIRST real still as the film opens (heroDive 0.9 s, assemble 1.2 s, irisFrom 0.5 s, lightWipe
  0.7 s) and the LAST still as it closes (pullBack 0.9 s); never a still between shots. Inside the window the
  still is only displaced (transform, mask, clip, particle positions) — never recoloured, grained or redrawn —
  and on the hand-over frame the `<img>` is drawn plain. `reveal_gate` proves it on the rendered film: the
  hand-over pair differs by a mean |ΔY| ≤ 1.0 with fewer than 1 % of pixels moved by > 24 levels, and the frame
  at `end` matches the clip file within 3.0. Hairline, shadow, ring and band are siblings in `#reveals`, never
  children of `#clipWrap`. Written into `picture-doctrine.md` law 2.
- One plate per reveal (`REVEAL.mount`); a plate's initial inline state is its state at t = 0.
- No zero-duration tweens: a cut is a 1/60 s step-ease tween that is 1 on the cut frame; 30 fps frames never
  sample its interior. Particle, iris and wipe frames come from GSAP plugins whose `render(ratio)` is pure, so
  they survive suppressed-event seeks; a late image decode repaints the last ratio through the same function.
- `assemble` samples pixels through a canvas: `file://` pages need `--allow-file-access-from-files`
  (`render_frames.js` sets it). A tainted canvas falls back to cream particles and the receipt says
  `sampled: false` — QA fails on it. Mid-assemble frames of a mostly-white UI read as light confetti; pick
  `heroDive` for white screens or set the focus on the densest region.
- Return `REVEAL.pending()` from `frame(t)` so `__seek` awaits decode and sampling before frame 0.
- Doctrine: the dive enters on z (grow = push) — answer it with the house current, not a pull; the pullBack
  is the reserved z−1 arrival at the close. One opener reveal per film; iris and wipe are accents (≤ 25 % of cuts).

## Receipts and checks

`REVEAL.list()` returns every reveal's receipt (`kind, at, end, frame, particles, sampled, …`); the scene
exposes it for `export_timeline.js`. `gates/reveal_gate.py` (`reveal handover`, `reveal join`, `reveal sampled`)
checks: every heroDive / assemble / lightWipe `end`
equals a footage shot `t0` and every pullBack `at` equals a shot `t1` (tolerance 0); `frame` is an integer at
the film fps; assemble receipts have `sampled: true`; on the rendered film the mean |ΔY| across each hand-over
frame pair is ≤ 1.0 luma level (the join is invisible). `node lib/reveals.js --selftest` (17 checks, < 1 s:
table determinism, coverage by 90 %, fit, frame snapping, iris radius) and `--plan '{"kind":"assemble","land":2.6}'`
print the receipt a ledger row should match. Render the opener twice and compare `ffmpeg -f framemd5`; look
at the hand-over frame pair and the particle mid-flight frame on the contact sheet.
