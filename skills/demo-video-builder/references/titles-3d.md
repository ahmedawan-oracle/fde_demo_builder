# 3D titles — `lib/title3d.js` (`T3D`)

Three opener devices on three.js, driven only by the film clock: build once, then `state.seek(localT)`
draws that instant. One WebGL renderer per title, drawing buffer kept so the frame renderer's screenshot
captures it, no animation loop, seeded randomness only (`MOTION.rng`). Everything below was measured on the
software GL path at 1920x1080.

## Loading

```html
<script src="../node_modules/gsap/dist/gsap.min.js"></script>
<script src="../node_modules/d3-delaunay/dist/d3-delaunay.min.js"></script>   <!-- UMD: window.d3.Delaunay -->
<script src="lib/motion.js"></script><script src="lib/title3d.js"></script>
<div id="gl3d" style="position:absolute;inset:0;z-index:6"></div>
<script>
const ready = T3D.load('../node_modules/three/build/three.module.js');   // three is ESM-only: the lib imports it
let title; ready.then(() => { title = T3D.shardTitle($('#gl3d'), { text: 'ONE SURFACE\nEVERY ANSWER', seed: 7, total: F.openEnd }); });
function frame(t) { /* … */ if (title) title.at(t, 0, F.openEnd); /* draws local time inside the window, hides outside */ }
window.__seek = t => ready.then(() => { /* reset, frame(t) … */ });    // the renderer awaits the promise
</script>
```

Paths are document-relative, never a CDN (`npm i three d3-delaunay`). `T3D.load` resolves the module path
against the document and sets `ColorManagement.enabled = false`, so the palette hex you pass is what reaches
the pixels. Stage units are CSS pixels of the 1280x720 stage on the z = 0 plane (camera distance 1343.5 at
fov 30). Title fonts must appear in an `@font-face` / `local()` rule in the scene so the glyph raster runs
after `document.fonts.ready`.

## `T3D.shardTitle(host, o)` — glass panes

The headline is rasterised, its silhouette seeded (`tiles` 10, 2–64, seeds inside the ink with a minimum
distance of 0.74·√(area/tiles) and two relaxation steps) and cut into a Voronoi tiling whose shared edges are
jittered by a hash of their position (neighbours agree, no overlaps), inset by `gap` 3 px and rounded
(`round` 5). Each cell becomes a thin extruded pane (`thickness` 6, `bevel` 1.5) carrying its slice of the
glyph texture. Shading is our own pane shader: tinted glass with a soft key light, fresnel rim (power 3),
sharp highlight (power 70), a light band sweeping once across the hold, brighter extruded sides, fog by view
depth folded into alpha; the back-cap glyph seen through the 26 % front cap reads as real thickness.

Choreography per pane, a pure function of local time:

- **in** (`flyIn` 2.3 s, delays spread over `stagger` 0.27 s, left → right with ±17.5 % jitter): xy converge
  on power2.out over 94 % of the flight, the tumble resolves on power3.out over 96 %, depth travels on
  sine.inOut for the whole flight and lands with a 16-unit forward click in the last 26 %; alpha ramps in
  over the first 12 %. Panes emerge from fog (`fogNear` 180 … `fogFar` 1250 beyond the camera) at their own
  start depth (`depth` [900, 1700]) and scatter ([260, 600] px).
- **hold** (`hold` 1.6 s, or `total` so the hold absorbs the slack, min 0.3): the sanctioned slow push
  1.2 %/s plus the light sweep.
- **out** (`flyOut` 2.4 s): power3.in past the lens (camera + 700), outward drift 120–260 px power2.in, a
  second tumble, faded over v 0.5–0.85 so nothing covers the glass. The fly-out is a push (z+1): write the
  following cut as a `zoom-through` with exit selector `#gl3d`.

Timings: `inEnd = flyIn + stagger`, `outStart = inEnd + hold`, `total = outStart + flyOut` (defaults 2.57 /
4.17 / 6.57 s). Colours: `glass` #204A56, `rim` #E8C874, `ink` #ECDEC3, `bg`/`fog` #082A34, `glow` #81A9AB
(a faint light pool, `glow` 0.10; 0 = flat clear colour, no draw call).

## `T3D.portalTitle(host, o)` — outline pieces (the light fallback)

The silhouette's contours are traced (square marching), smoothed once, points < 1.6 px apart dropped, and the
chains cut into ~28 px pieces (`piece`). Each piece flies rigidly from a seeded scattered start (`scatter`
[280, 620], `depth` [500, 1200], `spin` 1.4 rad) with delay = `stagger` 0.5 × (0.75 × x-position + 0.25 ×
rng) over `flyIn` 2.0, holds under the same light sweep and push, then scatters toward the lens (`flyOut`
1.6). All motion runs in the vertex shader (one uniform); the outline is a continuous ribbon (`width` 2.2 →
4.4 px core in `line` #E8C874, `halo` 7 additive in `glow` #81A9AB). Two draw calls. A two-line 150 px
headline becomes ~366 pieces / 5119 segments.

## `T3D.depthStack(host, cards, o)` — parallax stack with a dolly

Camera-facing cards `gap` 420 apart, offset by `spread` [90, 44] alternately; the camera dollies from the
first to the last card over `dolly` {t0, t1, from, to, ease} (default the whole `total`, sine.inOut, last card
framed at the end). Cards dissolve as they approach the lens (760 → 220 units); a soft shadow plate sits two
units behind each. Text cards are rasterised plates (label / serif title / body, `tone` navy or cream).
**Footage cards (`src`) are sacred**: billboarded (never tilted), no fog, no tint, no rounding — only scaled
and translated.

## Performance and anti-aliasing (software GL, ms per frame above the ~100 ms DOM-screenshot baseline)

| shard, no AA | shard, 4× MSAA | shard, own post pass | shard, 2× supersample | shard, physical transmission | portal | stack (4 cards) |
|---|---|---|---|---|---|---|
| 70 | **105 (default)** | 121 | 257 | 1390 (hardware only) | 82 | 135 |

The pane rims are sub-pixel geometry: a post pass cannot restore their dropouts, so MSAA is both cheaper and
cleaner (`aa: 'auto'` = `'msaa'`; `'post' | 'ssaa' | 'none'` force a mode). `material: 'physical'` (real
transmission, ior 1.45) costs 9× the 150 ms budget in software GL, so the default `'shaded'` shader fakes
thickness and does not refract the backdrop — on a flat navy ground nothing is missed. Numbers are the
minimum of three interleaved passes; single runs on a shared machine swing up to 4×. `T3D.MEASURED` carries
the table; `T3D.softwareGL()` tells a scene which path it is on.

## State and rules

`state = { seek(localT), at(t, start, end), show(), hide(), total, timings {inEnd, outStart, total}, canvas,
renderer, info(), dispose() }` for all three devices (plus `panes[]`, `pieces`, `cards`).

- Everything is a function of `localT`; `at(t, start, end)` hides the canvas outside the window.
- One title per host layer; `dispose()` before a rebuild. Scenes with a T3D title render with `workers: 1`
  or lazily mount/dispose — three.js contexts are the memory cost of the render.
- Two GL contexts per page (T3D and `GL`) are fine; to hand a three.js frame to a `GL` transition, pass
  `renderer.domElement` to `GL.texture` with `refresh: true`.
- Lint: `title3d.js` is clean; `three.module.js`, `three.core.js`, `d3-delaunay.min.js` under
  `node_modules` are known libraries; the dynamic `import()` of a relative `node_modules/three` path is
  allowed, remote imports are not.
- Test: render twice (`render_frames.js`, software GL default), `ffmpeg -f framemd5` both, diff — identical
  or it does not ship.
