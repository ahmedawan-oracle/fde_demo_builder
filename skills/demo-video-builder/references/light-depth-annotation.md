# Light, depth, a human hand, frosted glass — `LIGHT`, `DEPTH`, `ANNOTATE`, `GLASS`

The recreated layer must feel lit, deep and touched by a person — and never touch a product pixel. Four
libraries (`lib/light.js`, `lib/depth.js`, `lib/annotate.js`, `lib/glass.js`), all on `lib/motion.js`,
all seek-safe. Every helper has the shape `X.name(tl, target, at, opts)` with `at` in block-local seconds,
paints its own frame-0 state at build (never rely on GSAP's lazy first render) and keeps every blur radius
fixed: motion rides opacity and transform only. Marks, glow and glass live in `#ovl` or a stage sibling;
nothing is appended inside `#camera`.

```html
<script src="lib/light.js"></script><script src="lib/depth.js"></script>
<script src="lib/annotate.js"></script><script src="lib/glass.js"></script>
<script>
let poseNow = { s: 1, cx: 640, cy: 360 };                      // applyCam writes the clamped pose here every frame
ANNOTATE.install({ host: $('#ovl'), project: ANNOTATE.projector(() => poseNow, 1280 / 1920), fps: 30 });
GLASS.install();
MOTION.block('kpiMarks', (tl, el, api) => {
  ANNOTATE.spotlight(tl, [{ rect: KPI, at: 0 }, { rect: ROW, at: 1.8 }], 0.2, { until: api.exitAt });
  ANNOTATE.circle(tl, KPI_FIG, wt('nb', 'counts') - P.nb, { seed: 11, until: api.exitAt });
  ANNOTATE.label(tl, KPI_FIG, wt('nb', 'counts') - P.nb + 0.4, { text: 'open claims', side: 'below' });
}, { el: null, start: P.nb, end: P.ask, exit: 0.3, hide: false });
// in frame(t): applyCam(...) first, then MOTION.seek(t) — marks read the pose when they paint
</script>
```

## Light (`LIGHT`)

| Helper | What it does | Numbers |
|---|---|---|
| `bloom(tl, el, at, o)` | radial glow in a sibling layer behind a card or figure, plus a coloured box-shadow on the card | opacity 0 → .30 (ceiling .45) and scale .80 → 1 over 1.0 s power3.out (0.6–1.4 s); blur 28 px fixed; breathe .05/√N, period 2.4 s, dead over the last 20 % of the hold |
| `leak(tl, stage, at, o)` | three warm ellipses (amber #E8A24A, coral, gold) on a screen-blend layer, drifting ±8 % on seeded offsets | ≤ 0.5 s; envelope 0 → .90 (35 %) → .46 (70 %) → 0; blur 30 px fixed; over footage ONLY inside `o.window = [t0, t1]` (a seam row) — the helper throws otherwise |
| `sweep(tl, el, at)` | one 105° light band across a card on the landing word | 0.9 s power2.inOut, band 55 % of the width, peak .32 mid-travel, once per beat |
| `rim(el)` | static 1 px top-edge highlight | white .55 at centre, clear at the corners |

A bloom is a lamp, not a route: it lands with the card and then holds. Five lamps breathe at under half the
swing of one, so a stack of figures never pulses. `LIGHT.lint(LIGHT.ledger())` reports `leak_too_long`,
`leak_outside_window`, `bloom_over_ceiling`.

## Depth (`DEPTH`)

`DEPTH.planes(host, [{el, rate .2, blur 6}, {el, rate 1}, {el, rate 6, blur 22}], {start, end | tl, at, hold})`
moves each plane as a pure function of the block's time (never of the camera): drift −rate × 14 px over a
6 s hold (.2 ≈ 3 px, 1 ≈ 14 px, 6 ≈ 84 px) and growth 1 + min(rate, 2) × .004/s. Exactly one near occluder
(highest rate, or `o.occluder`) crosses the headline band once, centred a third into the hold (window 28 %
of the hold, sine.inOut, overshoot 1.25 W), then parks off the far side — the one event a hold needs so
nothing idles. Planes are absolutely positioned by the scene (explicit insets; when a dolly also runs, put
the plane transform on an inner element).

`DEPTH.dolly(tl, host, at, {from 1, to 1.08, dur 4, perspective 1200})` puts perspective on the host,
`translateZ` on the rig's children (−120 / 0 / +90 px, or `data-z`) and moves the rig along z so the z = 0
plane scales `from → to`: `z_rig = P (1 − 1/s)`. A child at z appears at `P / (P − z_rig − z)`: the near one
grows 1.175×, the far one 0.909 → 0.975 — differential growth is what reads as camera travel. `to` is capped
at 1.2; inside a fixed frame (a glass panel) keep `to ≤ 1.04`; 1.08 is for stage-filling cards.

## A human hand (`ANNOTATE`)

Rects are given in FOOTAGE coordinates (source px) and projected every frame through
`ANNOTATE.projector(() => pose, 1280 / sourceWidth)` — the same pose `applyCam` used. Marks are SVG paths from
a seeded generator, drawn on with `stroke-dashoffset` (length measured once at build), stroke coral 3 px on
screen (the width attribute is divided by the camera scale), cap `butt` while drawing then `round`.

| Mark | Geometry | Timing |
|---|---|---|
| `circle` | 24-point ellipse, radial noise ±4.5 %, 1.08 turns so the end overlaps, padding 1.22× | draw 0.45 s power2.out |
| `arrow` | quadratic shaft (bend .18) from `from` to the rect's nearest edge (8 px off), open V head 14 px at ±28° after the shaft | 0.45 s |
| `box` | 6 points a side, ±1.2 px, 12 px overshoot past the start corner | 0.45 s |
| `underline` / `strike` | 6 px under the rect with a 2 px bow / through the centre, tilt −2°, 6 % overshoot | 0.45 s |
| `spotlight` | dim rgba(6,8,12,.55) with a radial hole: clear to 52 %, opaque from 88 %, the 52 % ring at 1.15× the half-extent | fade .35 in / .30 out; glide between stops 0.8 s power2.inOut |
| `label` | tag (navy, ink 16 px — the label floor, coral bar) + 1.5 px leader + 3 px dot; the tag never scales with the camera | arrives .35 s, leader .30 s |

Boil: three path variants (seed, seed+1, seed+2) swapped every 3 frames plus ±1.6 px / ±0.5° jitter from a
generator seeded by (seed, step) — a pure function of the frame index, identical in every worker. Marks fade
out over 0.25 s at `until`.

**Gate rule.** A mark sits on a `claims.json` figure or on a logged click from the recording — never across
product text, never as decoration. `ANNOTATE.ledger()` lists every mark with its rect and times;
`ANNOTATE.lint(ledger, {claims, clicks, tol 12})` applies the rule (`mark_off_evidence`) and caps simultaneous
strokes at two (`marks_stacked`). Spotlights frame, they do not point, and are exempt.

## Frosted glass (`GLASS`)

`GLASS.install()` writes the tokens as `--glass-*` variables (blur 26 px, saturate 1.4, radius 18) and one
static stylesheet. `GLASS.panel(host, {variant dark|light|page, x, y, w, h, tl, at, until, window, html})` builds
a plate with `backdrop-filter: blur(26px) saturate(1.4)` (24–28 px, fixed), fill rgba(255,255,255,.08) on the
dark variant (over a dark card), rgba(0,0,0,.28) on the light variant (over light footage) or the `page` fill
rgba(5,22,28,.86) over a white product page — the house ground as a near-opaque frost, so the panel reads as the
recreated layer and its light ink, mint label and cream sub stay above 10:1 (the .28 black left ink at ~2.3:1, a
.34 black would too, and the .66 the scene first tried read as a mid-grey slab). The `page` variant carries no
backdrop blur: a backdrop root re-rasters the footage beneath it history-dependently (62/1171 frames differed between
two renders with it, 0 without) and at .86 the blur was invisible anyway — frosted `dark`/`light` panels belong over
recreated cards, never over the footage lane. 1 px border rgba(255,255,255,.25), radius 18 (16–20), a 1 px inner top
highlight; settle .96 → 1 power3.out over 0.45 s with opacity over the first 0.30 s; exit 0.30 s power3.in to
.98. The panel carries no `will-change`: with the hint its text rasterised at the scale the compositor picked
mid-settle and 46/76 frames differed run to run; the backdrop-filter already gives it a surface. Panel type
(h3, labels) sits at the 16 px floor.

Budget: at most two panels visible at once and never on the caption lane (stage y ≥ 570). Each backdrop blur
is a compositor pass at DPR 1.5: the mini scene with one panel, one bloom, one spotlight and one leak
rendered at ~1.2 s/frame on software GL — short beats only, bloom on cards only. Declare `window: [t0, t1]`
so the budget can be counted. `GLASS.lint(GLASS.ledger(), {captionLaneY 570, maxPanels 2})` reports
`panels_over_budget`, `panel_on_caption_lane`, `panel_off_stage`.

## Ledgers and gates

The scene exposes `window.__ledgers = { annot: ANNOTATE.ledger(), glass: GLASS.ledger(), light: LIGHT.ledger() }`
once at load; `export_timeline.js` dumps them next to `out/timeline.json`. `gates/annotate_gate.py` (`annot
evidence`, `annot ink`, `glass budget`, `light leak`) runs `node lib/annotate.js --lint out/annot_ledger.json
--claims claims.json`, `node lib/glass.js --lint … --lane 570 --max 2` and the light lint (exit 0 / 1 / 2). Lint notes: each panel adds one
`backdrop-filter`, each bloom/leak one `filter: blur` + one gradient, each spotlight one mask — 2 panels +
3 blooms + 1 leak + 1 spotlight stay under the `heavy_overlay_count` warning (25).

## Determinism and tests

No wall clock, no `Math.random`, no CSS transitions; every per-frame value comes from a paint plugin whose
`render(ratio)` is pure, registered headless so `node lib/<name>.js --selftest` runs without a window (envelopes,
geometry, seek-order independence, lint rules; under a second each). `--help` lists the JSON CLIs:
`light --envelope bloom|leak|sweep`, `depth --dolly|--planes`, `annotate --shape kind --rect x,y,w,h | --lint`,
`glass --lint`.
