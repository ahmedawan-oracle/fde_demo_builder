# GL transitions — `lib/shaders.js` (`GL`) and `type: gl` seams

Two pictures in, one out, at a progress the clock computes. Every effect is a fragment program over RGBA8
textures, drawn on demand inside `frame(t)` — never in a loop. The render default is software GL
(SwiftShader behind ANGLE), so the pixels do not depend on the laptop.

## What a cut can be

| Transition | Window | What the eye sees | Numbers |
|---|---|---|---|
| `chromaSplit` | 0.25–0.5 s (0.35) | red and blue pull apart radially, the picture breathes 1.5 % in, the cut lands at the peak, channels converge on the new picture | offset 3.5 % of the half-frame at the edge, 5-tap smear, hard cut at u 0.5, envelope sin²(πu) |
| `warpDissolve` | 0.4–0.6 s (0.5) | an ink cloud: seeded domain-warped noise sweeps a soft threshold; both sides breathe slightly | 2.6 cycles, feather 0.12, warp 0.6, optional gold edge glow (cards only, 0 on footage) |
| `lightLeak` | 0.6–0.9 s (0.7) between recreated cards; **0.5 s when a side is footage** (`split 0.15`, intensity 0.6) | a warm streak (gold core, coral skirt) sweeps across; the cut hides under its brightest moment | σ 10 % of the half-frame, −20°, core + 0.6 skirt + 0.35 haze + 0.4 trail, screen-combined, 0.12 white lift; default intensity 0.6 (1.0 read as a saturated reel beam and tinted the answer still gold 0.11 s before the cut) |
| `flashWhite` | 0.28 s | a white hit on the cut frame decaying to nothing | 0.55 → 0, power 1.6 |
| `iris` | 0.5–0.7 s (0.6) between recreated cards; **0.5 s when a side is footage** | a feathered circle (or rounded rectangle) grows the new picture / shrinks the old | power 2 (4–6 squarer), feather 6 %, the far corner is always covered |
| `slitScan` | 0.45 s | vertical slices on a wipe travelling left → right with a sine ripple | 32 slices, 22 % amplitude, scatter 0.25 |
| `crossWarp` | 0.5 s | both pictures travel the house current; the old grows and leaves, the new settles from behind the frame | 18 % travel, 12 % zoom, 5 % liquid bend, broad noise field decides hand-over order |

Rule of thumb: 2–3 devices per film, repeated. A transition passes over product footage only inside its
window and that window is ≤ 0.5 s — so `lightLeak` and `iris` must be given `dur: 0.5` (or less) whenever
`from()` or `to()` is the footage lane; their longer defaults are for card ↔ card cuts. Next to footage the
cut sits early in the window (`split 0.15`: 0.075 s = 2 frames at 30 fps before the cut on the footage side,
where the leak's envelope is still dim) so **no more than 2 frames of visible tint** land on product pixels;
the bright moment belongs to the card side. Check it on the contact sheet of the window edges (the sample's
`answer->close` row: footage → recreated close card). The leak and the dissolve belong between recreated
cards or card ↔ footage; **never between two product screens** — a dissolve there implies a continuity that
did not happen. Three guards: `seams.json` rows of `type: gl` are clamped to 0.1–0.5 s by `lib/seams.js`; the
lint (`gl_transition_over_footage`) refuses the static case; and `GL.cutTransition` resolves `from()` / `to()`
once at registration and throws when `dur` > 0.5 s and either side is the footage lane (the runtime twin — a
thunk that returns `#clipImg` with the 0.7 s default no longer renders).

## Finishing (recreated layers only)

`vignette` (0.75·amount darkening outside a superellipse, mid .78, feather .45), `grain` (hash noise
seeded by the integer frame index, midtone-masked, size 1.5·dpr px), `bloom` (threshold 0.72, knee 0.1,
9-tap separable blur at half resolution, screen-combined, amount 0.55), `chromaticAberration` (0.25 %
radial). `GL.pass` and `GL.chain` throw when the texture came from the footage lane (except `copy`, the
sanctioned slow push via a `MOTION` proxy).

## How a scene uses it

```html
<canvas id="glx"></canvas>              <!-- one screen-space canvas at z 30: above cards and camera, below #ovl -->
<script src="lib/shaders.js"></script>  <!-- after lib/motion.js; no npm dependency -->
<script>
const glx  = GL.create($('#glx'), { width: 1280, height: 720, dpr: devicePixelRatio, edgeColor: '#082A34' });
const card = GL.textCard(glx, { title: F.title, sub: F.subtitle });            // cards are DRAWN to canvases
for (const s of SEAM.glSeams())                                                 // the ledger is the single source of truth
  GL.cutTransition(glx, { at: s.at, dur: s.dur, name: s.name, from: () => sideA(s), to: () => sideB(s), params: s.opts });
function frame(t) { /* DOM layers, SEAM.apply … */ GL.drive(glx, t); }         // null outside every window → canvas hidden
</script>
```

Sources: an `<img>` (footage — `lane.imageFor(shot, t)` gives the decoded frame for one side of a cut, uploaded
once **per picture**: the texture cache is keyed on `currentSrc`, so the lane's own `<img>`, whose `src` changes
every frame of a seq clip at a constant size, re-uploads when the picture changes instead of showing whichever
frame the worker started on), a `<canvas>` / `<video>` (re-uploaded each call), or another GL result. The browser cannot read a DOM
subtree back synchronously, so `GL.snapshotToCanvas` refuses one with instructions: draw the card with
`GL.cardCanvas` / `GL.textCard` or mirror it to a canvas the scene owns. `GL.cutTransition` is a no-op outside
`[at, at + dur)`, hides the canvas on the first frame after, and throws on overlapping windows. Chains
(`GL.chain(glx, tex, [['vignette', {}], ['grain', { frame: GL.frameIndex(t) }]])`) ping-pong through two FBOs.

## The ledger rows (`seams.json`, `type: "gl"`)

```json
{ "id": "title->notebook", "type": "gl", "technique": "chromaSplit", "cut": "P.nb", "dur": 0.35, "split": 0.5,
  "act": "demo", "cause": "chapter" }
```

A gl row has no exit/entry vectors: the two sides are textures and the window (`dur`, `split` before/after the
cut) *is* the transition. `SEAM.glSeams()` resolves the rows to `{id, at, dur, name, cause, opts}` for the scene;
`export_timeline.js` writes them to `out/timeline.json → glSeams`; `seam_gate.py` measures them. Validation:
`technique` must name one of the seven; `dur` within 0.1–0.5 s; the technique set counts toward the ≤ 3 per
film. `flashWhite` and `lightLeak` brighten by design and are exempt from the luma-spike check (`seam flash`).
`BL2.sceneCards.cutAt(t)` offers a 0.33 s hook for card-to-card cuts; when a gl row exists for that cut the
row wins and the hook is ignored.

## The honesty matrix

| from → to | allowed | why |
|---|---|---|
| card → card | every transition, finishing on either side | both sides are ours |
| card → footage, footage → card | chromaSplit, flashWhite, iris, crossWarp, slitScan at ≤ 0.5 s; leak and dissolve only at `dur 0.5, split 0.15`, intensity ≤ 0.6, with the card side carrying the light | the footage texture is sampled, never displaced beyond the window; ≤ 2 frames of visible tint on the footage side; `passes` apply to the card side only |
| footage → footage | **none** — a hard cut on a `cut-the-curve` row | a dissolve between product screens fabricates continuity |
| any, `dur` > 0.5 s over footage | **refused** by the ledger, the lint and `GL.cutTransition` itself | half a second is the longest a product frame may be touched |
| whip / zoom kinds (`slitScan`, `crossWarp`, `iris`) | need a `cause` | a direction change without a cause reads as an error |

Footage may sit on a side only if that texture is never displaced outside the window; on the last frame the
lane draws the real file plain.

## Determinism

No wall clock, no scheduling, no unseeded randomness. Seeds come from params (default: a hash of the effect
name); the only time-like inputs are `u` and the integer frame index for grain. Mixing happens in encoded
(sRGB) space so `u = 0` is picture A to the byte and `u = 1` is picture B to the byte; uploads skip the
browser's colour-space conversion; light is added with a screen combine so it never clips. Edges clamp (or
mirror); displacing programs return the stage ground outside the frame (`fill: 'edge'`), so a displaced slice
shows navy, not a smeared border. Integer PCG hash, `highp float`, RGBA8 only. Measured: the GL mini scene
(3 cuts + finishing, 120 frames) is byte-identical across two renders; 1920x1080 at ~0.6 s/frame on
software GL. `GL.create` takes `dpr` explicitly — pass 1.5 so preview and render agree on grain cell size.
Chrome prints "GPU stall due to ReadPixels" per screenshot under SwiftShader; it is harmless. The canvas never
asks for `will-change`; the renderer waits two animation frames after every step before it captures, so the
last `GL.drive` of a window is composited before the shot (`deterministic-render.md`).

## Gates

`determinism` (the gl canary: two renders identical and the same `gl_renderer` in the receipt) · `effects off footage`
(no `GL.pass` / `GL.chain` on the lane, `grade_gate`) · `seam ledger` (gl rows valid, ≤ 0.5 s, techniques ≤ 3)
· `seams move` / `seam flash` on gl rows (brightening kinds exempt) · lint: one GL owner per scene
(`getContext('webgl2')` only in `lib/shaders.js` and `lib/title3d.js`), `cutTransition` over footage ≤ 0.5 s.
