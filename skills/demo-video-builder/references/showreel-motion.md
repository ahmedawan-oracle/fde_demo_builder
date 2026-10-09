# Showreel motion — `lib/reel.js` (REEL)

A pitch film and a product walkthrough want different things from motion. The walkthrough wants calm: the product
is the picture. A pitch film — a team reel, a field-enablement short, a booth loop — has to make a claim feel
fast and certain in under two minutes, and that wants the grammar of a motion-design reel: hard rhythm, one hot
accent, geometry that builds and breaks, a frame that looks engineered. `lib/reel.js` is that grammar as nine
pure functions of the film clock, for the RECREATED layer only.

Everything here renders identically cold or stepped (two renders with the same worker count are byte-identical:
`framemd5` 0 / 420 on `scenes_reel_demo.html`), uses no GSAP, and draws into canvases and DOM nodes the scene owns.

## The devices

| Device | What the viewer sees | Use it for | Never |
|---|---|---|---|
| `REEL.hud(cv, t, o)` | four thin corner brackets, `01 / 09  CHAPTER` with a decode-on label at the top left, a running `TC mm:ss:ff` with a live dot at the bottom left | the whole film, on one overlay canvas above the act and below captions + logo | on a product-UI film whose screens already carry chrome at the corners — set `corners: [0,1,1,1]` while a block owns a corner |
| `REEL.stinger(cv, t, o)` | navy tiles close in on a diagonal, the pattern morphs square → cross → triangle in accent + cream, the cut happens fully covered, the tiles open | the two or three big chapter cuts of a reel | more than one per 20 s; a window over 0.8 s (it throws); a cut inside a sentence that is still on screen |
| `REEL.streaks(ctx, x, y, u, o)` | a light-speed burst of radial streaks out of a point | the payoff word: a title landing, a brand mark, "start" | two bursts within 3 s of each other |
| `REEL.rings(ctx, x, y, u, o)` | concentric ellipses bloom out of a point, staggered, alternating heavy/light | a sign-off, the moment a set completes | behind body text (it is thin, but it moves) |
| `REEL.voxel(cv, t, o)` + `REEL.view(t, o)` | a flat grid (a calendar, a heat map) seen as an iso field of cubes whose heights the scene drives; a crest can ripple out; the camera can **un-tilt to top-down with heights → 0**, so the field lands exactly on the flat DOM grid | turning a dry grid into weight ("a quarter of days"), then handing off to a DOM move (shatter, morph, re-flow) with no visible seam | product data you have not verified — a voxel height is a claim |
| `REEL.blob(parent, x, y, w, h, o)` | a glossy liquid core (smooth-union metaballs, orthographic raymarch, accent colour); `draw(balls, t, wob)` takes balls in STAGE px, so a droplet can start at any element's position and merge | "everything lands in one place" — artifacts, sources, signals arriving at a platform | a beat whose message is that nothing moves (e.g. zero-copy): keep the core still, pulse it, no droplets |
| `REEL.slam(host, o)` | two accent panels snap shut on the word and split open onto the title behind them | one title per film | stacking with a white flash or a GL cut in the same second |
| `REEL.marquee(el, t, t0, o)` | an outline-text row that drifts; pair two in opposite directions behind a title | holding a title for 2–4 s without it going static | readable copy — the outline is texture, the title says it |
| `REEL.smear(v, o)` | a vertical motion trail behind a rising glyph (text-shadow string, v 1 → 0) | per-character rises on a headline or a brand line | text that stays put |
| `REEL.decode(text, u, seed)` | glyph soup resolving left → right | HUD labels, small mono tags | a headline (use `TYPO.scramble`, which has the full timing model) |

## Doctrine

- **Recreated layer only.** The stinger may cross footage only inside its own window (≤ 0.8 s, centred on a
  declared cut); the voxel field, the core, the slam and the marquee never sit on product pixels.
- **One hand.** The accent (`REEL.tokens.accent`) is the reel's hand: slam panels, hot tiles, the voxel crest, the
  core. Everything else stays in the film palette. Override tokens from the brand kit before frame 0.
- **Every device lands on a word.** `t0` values are `wt(phase, word)` from `lib/timeline.js`. A burst that fires on
  silence reads as decoration.
- **Spend it.** A two-minute reel carries one voxel moment, one slam, two or three stingers, one core, two bursts.
  More than that and nothing is the payoff.
- **Hand-offs are exact.** `REEL.view(t, { grid, flatAt })` reaches pit = yaw = 0 and heights × 0 at `flatAt`;
  `REEL.project` then maps every cell centre onto its flat position with zero error (the selftest checks this), so
  fade the canvas out over the last 60 ms and the DOM grid in over the same frames.
- **The core is not data.** Droplets merging into a core say "these arrive here". If the claim is that data stays
  where it is, the core pulses as links connect and nothing travels.

## Wiring

```html
<script src="lib/reel.js"></script>
```

```js
// one overlay canvas, 1920x1080 for the 1280x720 stage, above the act (z 30), below captions (45) and logo (50)
const hud = mkCanvas(stage, 30);
function frame(t) {
  /* … the act … */
  REEL.hud(hud, t, { chapters: [[0, 'The problem'], [P.fix, 'The fix'], [P.close, 'Start']], end: TOTAL });
  REEL.stinger(hud, t, { cuts: [P.fix, P.close - .2], clear: false });   // same canvas, after the HUD
}

// voxel field over a 13 x 7 calendar that lives in the DOM at (332, 176), pitch 48, cells 40
const G = { x: 332, y: 176, cols: 13, rows: 7, pitch: 48, size: 40 };
REEL.voxel(vxCanvas, t, { grid: G, view: REEL.view(t, { grid: G, flatAt: wt('answer', 'Not') - .05 }),
  height: (cell, t) => 12 * fillOf(cell, t) + 34 * crestOf(cell, t),
  color:  (cell, t) => ({ top: [129, 169, 171, .26], side: [38, 70, 78], line: [129, 169, 171, .3], crest: crestOf(cell, t), a: fillOf(cell, t) }) });

// the liquid core behind a card; droplets from each landing chip
const core = REEL.blob(group, 300, 200, 680, 460);
core.draw([[640, 512, 80], [640 + 60 * Math.cos(t * 1.3), 512, 34, .2], ...droplets], t, 1);

// the slam on "four"
const slam = REEL.slam(root, { z: 60 });   slam.draw(t, wt('answer', 'four'));
```

Canvases are 1.5 × the stage by default (`o.k` = canvas px per stage px if yours differ). `REEL.coverAt(t, { cuts })`
returns 0 … 1 so the scene can pause anything expensive while the frame is fully covered.

## Proof

```
node scripts/film/lib/reel.js --selftest            # 13 checks: decode, stinger window + full cover + 0.8 s guard,
                                                     # streak determinism, voxel flatten lands on the grid, hud, smear
python scripts/film/gates/lint_scene.py scripts/film/scenes_reel_demo.html scripts/film/lib/reel.js   # 0 errors
node scripts/film/render_frames.js "scripts/film/scenes_reel_demo.html?render" out/reel.mp4 14 30 94 2   # twice → framemd5 identical
```

`lib/reel.js` is the third sanctioned WebGL owner after `lib/shaders.js` and `lib/title3d.js` (`REEL.blob` makes its
own context on its own canvas; `lint_scene.py` knows it). The core renders on software GL in ~0.3 s per frame at
680 × 460; budget it to the seconds it is on screen.
