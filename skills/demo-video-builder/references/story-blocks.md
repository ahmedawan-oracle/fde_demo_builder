# Story blocks, charts and comparisons — `lib/blocks2.js` (`BL2`), `lib/charts.js` (`CHART`), `lib/compare.js` (`COMPARE`)

The recreated cards a trailer is made of, the charts that may only show claimed values, and the honest
before/after. All three run on `lib/motion.js`: a block is a GSAP timeline mounted through `MOTION.block`
and moved only by `MOTION.seek(t)`. Same `t`, same pixels, in any worker, in any order. Example scene:
`scenes_blocks2_demo.html` (fictional Acme). `lib/blocks.js` (`BL`) stays for the v4 scenes; its lockup,
kpi/count and flash now delegate to `TYPO.lockup`, `BL2.countUp` and `BL2.flash`.

## Contract

`BL2.<name>(host, opts) → { el, tl, block, start, end, LAND, land(t?), sync(), at(t), remount(start) }`, once.

- **Landing is the key.** Each block has one moment the voice points at. `LAND` is that moment in block
  seconds; `land()` returns it as film time; `land(wt('open', 'percent'))` re-anchors the block so the moment
  falls on the word. Pass `start` instead to key the entrance; `end` (absolute) or `span` (relative) closes the
  window — outside it MOTION hides the block, so hard cuts cost nothing.
- `exit: 'none' | 'fade' | 'up' | 'left'` — 0.36 s power4.in, starting 0.36 s before `end`. Default none: our
  cuts are the transitions.
- `sync()` → `[{id, t}]` absolute, pushed to `window.__sync` as `'<block>:<kind>'` for `out/timeline.json →
  sync` (SFX routing). `at(t)` → `{local, u, landed, inWindow}`. Give every block a unique `id`.

## Catalog (measured defaults)

| Block | Landing | Numbers |
|---|---|---|
| `countUp` | figure reaches its value | arrive 0.38 s (opacity power2.out; y 16 px + scale 0.98 → 1 power3.out); count 1.72 s sine.inOut for a large figure — for a small integer pass `count: 0.5` or less so the figure lands directly with its pulse (counting 0 → 1 → 2 → 3 over 1.7 s shows three non-claim values, the sample's craft review); pulse 1.07 / 0.165 s power3.out, back 0.165 s power2.out; label 0.15–0.45 s; tabular digits, min-width in `ch`; `then` = two-figure transition: first figure dims to mint, arrow draws 0.3 s, second arrives 0.2 s later and counts 0.9 s or lands a token (`29 % → <1 %`) |
| `decisionCard` | the seal hits | monospace JSON-like block types in 0.9 s (machine rhythm; keys mint, strings cream, numbers gold, booleans coral) behind a 2 px caret; seal −6° from scale 1.35 over 0.22 s power3.in, card recoils 2 % over 0.24 s; caret dies on the seal frame |
| `receipt` | pill in place | y 14 → 0 power4.out 0.42 s; 2 % snap on landing (1.02 → 1, 0.24 s power3.out); check draws 0.3 s; parts cascade from 0.12 s, gaps 0.06 s × 0.84 |
| `twoLayers` | the surface forms (0.84·dur) | SVG; 8–12 s; tiles scatter 0–8 %, three waves at 10 / 22 / 34 % (0.3 s up, 0.55 s down; middle wave gold), ring 1.1 s power3.inOut at 46 % + 7 nodes, leaders 0.5 s at 60 %, surface outline 0.9 s at 70 %; snap on landing, field dims to 0.55, ring turns gold, slow push 1.2 %/s; default ring copy "Enterprise Ontology · generated automatically" |
| `sceneCards` | last card's cut | hard cut every `period` (3 s) + linear micro push 1 → 1.035; content mid-flight on the cut (starts 0.12 s early behind the plate): icon 0.45 s, title 18 px / 0.28 s power4.out, line +0.06 s, rule 0.5 s; `cuts`, `cutAt(t) → {k, cut, u}` over 0.33 s for a GL transition (a `gl` ledger row for the same cut wins), `cardAt(t)`; own 64x64 icons: bank, factory, hospital, retail, telecom, energy |
| `chatReveal` | last streamed word | typing 55–90 chars/s per word chunk (+0.5 s after `.!?`, +0.15 s after `,;:`); send = tDone + 0.167 (press 0.9 for 0.08 s); bubble 14 px / 0.25 s; dots at +0.30 (−9 px bobs 0.28 s, 0.09 s apart, integer cycles) die at +0.633 when the stream starts; word gaps 0–367 ms with 15 % zero bursts, grey → ink 0.267 s; `answerEnd` compresses; receipt +0.467; pass `cps: [11, 14]` for a slower key-level feel |
| `approvalCard` | consequence chip pops | title 0.18 s, caveat 0.30 s; action typed at key rhythm (33–200 ms, mean ≈ 90) from 0.9 s; press at tDone + 0.25 (0.96 for 0.08 s); chip 0.85 → 1 / 0.3 s power3.out on release; audit types 22 ms/char from +0.35 |
| `flash` | the frame `at` | white 0.55 → 0 over 0.28 s power3.out; `snapEl` (a dedicated wrapper, never footage) 1.02 → 1 over the same window; window exactly [at, at + 0.28]; once per act |

Helpers: `BL2.arrive / pulse / snap / cutIn / cutOut / exit / draw / tw`, `BL2.humanTimes / keyTimes /
machineTimes / fitTimes`, `BL2.HARD` (the step ease), `BL2.TOK` (palette), `BL2.N` (every number above),
plugins `b2num` and `b2txt` (pure `render(ratio)`).

## Seek-safety (what the helpers enforce)

Every tween is a `fromTo` with explicit from-values; the DOM's initial inline state equals the first
from-state; no zero-duration tweens (a hard cut is a 1/60 s step-ease tween that is 1 on the cut frame);
nothing outside the block root is touched at local 0; 2D transforms only (`force3D:false` — 68 dB PSNR
run-to-run on a button press until it was set); counts and typed text come from plugins, not `onUpdate`.

## Charts — a chart is a claim (`CHART`)

No chart accepts a literal number. A series entry says `claim: 'late_west'`; the value comes from
`claims.json → "values": {id: {value, unit, source}}` (exported as `scenes/claims_data.js`, loaded with
`CHART.use(window.CLAIMS)`). An unresolved reference throws at build. Ticks are scale, not statements (nice
step from the largest claim: 12.4 → 2.5-steps to 12.5). Derived figures are never computed — if the narration
says "a third", that is its own claim. Free text that reads as a figure (`12.4 %`, `$3.2M`, `1,204`) is refused
unless `strict: false`; `Q3`, `2025`, `Week 12` pass.

| Block | Shape |
|---|---|
| `CHART.bars(host, {series:[{label, claim}], land, end, x, y, w 640, h 360, unit, dec, legend})` | vertical bars |
| `CHART.line(host, {points:[{label, claim}], …})` | straight segments only (a curve would invent values) |
| `CHART.kpiTiles(host, {tiles:[{label, claim, note?}], w 900, h 150})` | 42 px figures |
| `CHART.race(host, {series:[{name}], periods:[{label, values:{name: claimId}}], periodDur 1.2, barCount 6})` | ranks solved per period |
| `CHART.donut(host, {segments:[{label, claim}], total?: claimId})` | optional total claim in the centre |

Motion shared by every chart: marks grow from the baseline 0.6 s power3.out, 0.06 s stagger; value labels
count up on the same tween (tabular digits, the `claimText` plugin); the frame arrives 0.45 s before the
first mark; `land` is the absolute second the LAST value must sit still on (`growStart = land − 0.6 −
0.06·(n − 1)`). Type: axis labels, ticks and legend 16 px (the legibility floor — 16 stage px, 24 px at 1080p),
values 18 semibold; nothing on a chart below 16 stage px. Palette order mint, coral,
gold, cream. Every chart sits on a plate by default (navy rgba(8,42,52,.92), radius 14, padding 16) so it
reads over white UI. Gates (`chart_gate`): `chart claims` — `node lib/charts.js --check claims.json scenes/*.js scenes/film.html`
fails on any `claim:` id missing from `claims.json`; `chart figures` — every rendered figure (`CHART.manifest()`)
equals its claim's value.

## Comparisons — honest before/after (`COMPARE`)

Both halves are the recording's own pixels, scaled uniformly and cut by a clip edge — no filter, blend or
recolour. Labels are pills in `#ovl`, never on the pixels. Blocks live in `#cmp`, a `#stage` sibling.

- `COMPARE.split(host, {a:{src, label}, b:{src, label}, start, end, divider:[{t, x}]})` — two stills in one
  rect; the 2 px divider and its 36 px grip move on power2.inOut between keyframes like a hand dragging.
- `COMPARE.wipe(host, {a, b, start, end, at, dur 0.9, dir ltr|rtl|ttb|btt})` — A alone until `at`; B wipes in
  behind a 2 px edge that fades over the last 0.15 s; BEFORE leaves / AFTER arrives at the midpoint.
- `COMPARE.pip(host, {src | frames:{base, count, fps, at}, start, end, corner 'br', width 0.28})` — a second
  recording at 28 % of the stage (358x201), 32 px margin, 14 px corners, the house shadow; arrives from its
  corner 0.5 s power4.out (0.92 → 1), leaves 0.36 s power4.in; frame sequences: call `block.draw(t)` from
  `frame(t)` and await `block.pending`.

Await `COMPARE.ready()` in `__seek` so both images are decoded before frame 0. The clip edge is written by a
rendered plugin from the same pure helpers the selftest checks (`wipeInset`, `dividerAt`).

## Honesty

Blocks are for recreated cards, openers and call-outs. They may frame, sit beside or transition between
product screenshots; they never recolour, warp or grain product pixels. `flash` may pass over footage only
as the cut-window hand-off (≤ 0.5 s), once per act; `snapEl` is always a dedicated wrapper, never the footage
`<img>`. Numbers shown by `countUp`, `kpiTiles` or any chart equal the on-screen product figure in `claims.json`.

## Testing

Render twice with one worker, `ffmpeg -f framemd5`, identical. Then the seek canary inside one page: step
every frame hashing a sample set, jump to the same frames in reverse and shuffled — hashes agree. Warm the
page (paint once, ~1 s) before hashing: local fonts settle late. `node lib/charts.js --selftest`,
`node lib/compare.js --selftest`, `node lib/stage.js --selftest` run in under a second each.
