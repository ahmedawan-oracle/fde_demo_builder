# Picture doctrine — how a v5 film is put together (read this first)

A film is one HTML scene whose only input is the narration clock `t`. Everything the viewer sees is a pure
function of that number, drawn on top of, beside or between the recording's own pixels. This page is the
map: the four laws, the layers, the device vocabulary and when to spend which device. Every number here
was measured on the 1280x720 stage rendered at DPR 1.5 (1920x1080) on the software GL path.

## The four laws

1. **One clock.** Word times from `gen_vo_multivoice.py` are the clock; `wt(phase, word)` is the only way to
   say *when*. A scene exposes `__seek(t)` (full reset) and `__step(t)` (sequential) and nothing else moves it.
   GSAP timelines are mounted paused through `MOTION.block` and set per frame by `MOTION.seek(t)`; the ticker
   never runs. No `Date.now`, no `performance.now`, no `Math.random` (use `MOTION.rng(seed)`), no rAF outside
   the preview branch and the studio, and **never `will-change`** in a scene or a lib (a promoted layer rasters
   at a scale picked from its transform history; the lint refuses it). Proof: render twice with three workers
   while the machine is busy, `ffmpeg -f framemd5`, diff empty — 0/1099 frames on the Acme sample with two
   3-worker renders running at the same time.
2. **Real footage is sacred.** Product pixels are evidence. They are scaled uniformly, moved by the camera,
   masked with small soft blurs — never recoloured, warped, grained, redrawn or blended. An effect may pass
   over footage only inside a declared seam window ≤ 0.5 s, with at most 2 frames of visible tint on the
   footage side (a `lightLeak` or `iris` next to footage runs at `dur 0.5, split 0.15`, intensity 0.6). Every
   product beat opens full screen (~1 s), then zooms. `grade_gate`, `seam_gate` and the lint enforce this;
   `GL.pass` throws on a footage texture and `GL.cutTransition` refuses a window > 0.5 s with footage on a side.
   **The one sanctioned exception: reveals.** `lib/reveals.js` may move, mask or particle-assemble the FIRST
   real still as the film opens (heroDive 0.9 s, assemble 1.2 s, irisFrom 0.5 s, lightWipe 0.7 s) and lift the
   LAST still as it closes (pullBack 0.9 s). Inside that window the still is only displaced — transform, clip,
   particle positions — never recoloured, grained or redrawn, and on the hand-over frame the footage lane shows
   the file plain. `reveal_gate` measures that frame pair (mean |ΔY| ≤ 1.0, fewer than 1 % of pixels moved by
   > 24 levels) and the still at `end` against the clip file (≤ 3.0), and fails the film otherwise. Scarcity:
   one reveal in, one reveal out, none between shots; the 0.5 s rule governs every other transition over footage.
3. **Software GL by default.** `render_frames.js` launches Chrome on the software rasteriser
   (`--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader --disable-gpu`): WebGL2 present, a DOM
   shot in 80 ms (157 ms through the laptop GPU), frames identical across machines, and the hardware frames
   differ from the software ones on every frame — so they are never mixed. `RENDER_GL=hardware` is for previews.
   Compositor sync flags are on by default (`RENDER_COMPOSITOR_SYNC=0` opts out); the first frame is captured
   until two captures agree (late local-font paint); every step is followed by two animation frames before the
   capture (the compositor must activate the step's writes — measured 98/1099 differing frames without it); the
   multi-worker join states each part's duration so the master is exactly CFR (`avg_frame_rate 30/1`). The
   receipt carries `gl` and `gl_renderer`. Details and numbers: `deterministic-render.md`.
4. **Honest numbers.** A figure shown by a block, chart or annotation equals the on-screen product figure
   listed in `claims.json`; derived figures (shares, deltas, totals) are never computed — every spoken number
   is its own claim. Nothing private ships: the leak gate reads the pixels, not your intentions.

## The layers (bottom to top, inside `#stage`)

| z | layer | who draws it | may touch footage? |
|---|---|---|---|
| 0 | wallpaper (`STAGE.mount`) | stage.js | — |
| 1 | `#camera` → `#clipWrap` footage lane (+ `CURSOR` as a sibling) | footage.js, camera.js | the lane IS the footage |
| 5–6 | recreated cards, `#cmp` comparisons, `#gl3d` 3D title | BL2, TYPO, T3D, COMPARE | never |
| 9 | `#reveals` plates (first / last real still) | REVEAL | displaces the still only inside its window |
| 30 | `#glx` GL transition canvas | GL via `SEAM.glSeams()` | only inside a `type: gl` row ≤ 0.5 s |
| 40 | `#ovl` marks, glass, light, charts, lower thirds; `#cap` caption lane; `HUD` pill | ANNOTATE, GLASS, LIGHT, CHART, OVL, CAP | overlays only; no filter on the lane |
| top | `#black` head/tail plate, the mandatory credit | build_film.py, credit.py | — |

Overlays live in screen space, outside `#camera`, so a push can never move them off safe. Marks are
projected through the camera pose every frame (`ANNOTATE.projector`), so they stay on the figure they point at.

## The device vocabulary

| Moment in a film | Device | Lib | Reference |
|---|---|---|---|
| cold open, a number lands on its word | `BL2.countUp`, `TYPO.centerBuild`, `TYPO.slam` | blocks2, typo | story-blocks, motion-and-typography |
| the title | `TYPO.lockup`, or a 3D `T3D.shardTitle` (fallback `portalTitle`) | typo, title3d | motion-and-typography, titles-3d |
| the first real screen arrives | `REVEAL.heroDive` / `assemble`, hand-over on one frame to the lane | reveals | reveals |
| product beat | lane: full screen ~1 s → camera push; `CURSOR` redraw, `HUD` keys, idle ramps | footage, camera, cursor, hud | recording-native, camera-moves |
| point at a figure | `ANNOTATE.circle` / `arrow` / `box` / `underline`, `spotlight` glide, `label` | annotate | light-depth-annotation |
| a recreated card between beats | `BL2.decisionCard` / `receipt` / `twoLayers` / `sceneCards`, `GLASS.panel`, `LIGHT.bloom`, `DEPTH.planes` | blocks2, glass, light, depth | story-blocks, light-depth-annotation |
| a chart | `CHART.bars` / `line` / `kpiTiles` / `race` / `donut` — values are claim ids | charts | story-blocks |
| before / after | `COMPARE.split` / `wipe` / `pip`, both halves pixel-exact | compare | story-blocks |
| the cut | a `seams.json` row: cut-the-curve (default) · zoom-through · inverse · one `gl` accent | seams, shaders | motion-doctrine, gl-transitions |
| captions | `anchor` rail by default; `karaoke` on the hero question; `kinetic` on recreated lines | captions | captions-karaoke-chapters |
| the close | `TYPO.swap` → `TYPO.lockup`, `REVEAL.pullBack`, the credit | typo, reveals, credit.py | reveals, credit-footer |

## Spending rules (scarcity is the style)

- **2–3 seam techniques per film, repeated.** One `gl` accent per act at most; whip/zoom kinds need a `cause`.
- **One accent seam, one slam, one hero per beat.** Kinetic devices read as social reels when stacked.
- **One opener reveal per film**; iris and wipe are accents (≤ 25 % of cuts).
- **Light is a lamp, not a route**: bloom lands with its card and holds (peak .30, ceiling .45); a leak lives
  only inside a seam window ≤ 0.5 s; one sweep per beat.
- **Glass budget**: ≤ 2 panels on screen, never on the caption lane (stage y ≥ 570). Bloom on cards only.
  Measured cost: one panel + one bloom + one spotlight + one leak at DPR 1.5 ≈ 1.2 s/frame on software GL —
  keep these beats short.
- **Charts sit on a plate** (navy rgba(8,42,52,.92), r 14, pad 16) so they read over white UI.
- **Footage never wobbles; recreated layers never freeze.** Idle rules are scoped to `#clipWrap`; a card may
  breathe through its block's own timeline. Pause at any second — something meaningful is mid-flight.
- **Entry ≤ 0.8 s, exit ≈ 75 % of entry, stagger ≤ 0.5 s (0.06 s × 0.84ⁱ)**, siblings share one ease.
- **Masks are small soft blurs** (`r = max(6, ceil(0.45 × text height))`), never white fills, never a redraw.
- **One legibility floor.** Labels, kickers, chart axes and ticks, lower-third labels, receipt and chat text:
  **16 stage px minimum** (24 px at 1080p); body 18; headlines 40. `design.md → scale` (`label_min 16`,
  `body_min 18`, `headline_min 40`, `justify_below 18`) and `text_gate` carry the same numbers; the craft review
  of the sample measured 13–15 px kickers and labels unreadable at a booth distance.
- **Lower thirds are flat**: a rule and two lines, no accent stripe, no radius above 4 px, no drop shadow (the
  design tokens ban all three); the ask beat's lower third is short so one voice owns the hero line.

## Timelines inside blocks

Inside a `MOTION.block` build use `tl.fromTo` with explicit from-values and `tl.set`; outside a block use
`MOTION.set` (a bare `gsap.set` is a no-op under the paused ticker). Per-frame hooks register with
`MOTION.onSeek(fn)` — GSAP suppresses `onUpdate` when a timeline is set by time. Per-frame text or paint goes
through a GSAP property plugin whose `render(ratio)` is pure (`typoPaint`, `b2num`, `b2txt`, `claimText`).
2D transforms only (`force3D:false`) and no `will-change` anywhere: a promoted layer re-rasters on Chrome's own
clock, at a scale it picks from history (glass panel: 46/76 frames differed run to run until the hint went).

## The build, end to end

BRIEF → look pass (`brand_kit.py` sheet or a skin from `skins/`) → STORYBOARD → sketch sheet → lock →
`build_film.py` (plan → preflight → render → mix → master → captions → **credit** → ledger → exports) →
`qa_film.py` (`--profile picture` = the 12 picture gates; `full` = everything) → studio taps → review pack →
sign-off → export. `commands/new-film.md` walks it; `qa-gates.md` lists every gate.

## Where the numbers come from

Every reference quotes what was measured, not what was intended: a software-GL DOM shot 80 ms; a glass beat
1.2 s/frame; the shard title 105 ms/frame with 4× MSAA (1390 ms with real transmission — not shipped);
cursor tracking 96.7 % within 6 px on the synthetic tape, ~50 % on a fast real one (so the tracker proposes,
telemetry decides); OCR 0.3–0.5 s per frame on the OS engine versus 25–40 s on the bundled model. When you
change a device, re-measure and update the page that quotes it.
