# Motion and typography — `lib/motion.js` (`MOTION`) and `lib/typo.js` (`TYPO`)

Eased, composable keyframes that still obey the film clock. GSAP supplies the easing and the timeline
algebra; `MOTION` makes every timeline a paused object that `seek(t)` sets, so the same `t` gives the same
pixels in any worker, in any order. `TYPO` builds the type devices on top of it. Fonts are local (Georgia ·
Arial · Segoe UI · Consolas); sizes are for the 1280x720 stage.

## MOTION — the clock adapter

```html
<script src="../node_modules/gsap/dist/gsap.min.js"></script>   <!-- npm i gsap; never a CDN -->
<script src="lib/motion.js"></script>
<script>
const title = MOTION.block('title', (tl, el, api) => {
  tl.fromTo(el.querySelector('h1'), { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: 'power3.out' });
  tl.to(el, { scale: 1.048, duration: 4, ease: 'none' }, 0);          // the sanctioned slow push, 1.2 %/s
}, { el: $('#titleCard'), start: 0, end: P.nb, exit: 0.4 });
function frame(t) { /* lane, camera … */ MOTION.seek(t); /* captions … */ }
</script>
```

| API | What it does |
|---|---|
| `block(id, build(tl, el, api), {el, start, end, exit, seed, hide})` | mounts one paused timeline; `build` runs once, synchronously; `api.exitAt` = where the exit segment starts; outside `[start, end)` the element is hidden by visibility, so hard cuts cost nothing; a second block with the same id replaces the first |
| `seek(t)` | sets every mounted timeline to its local time, then runs the seek hooks |
| `onSeek(fn)` | per-frame hook for libs that need a callback (cursor, HUD) — GSAP suppresses `onUpdate` on a time-set |
| `set(target, vars)` | an immediate set that renders now; a bare `gsap.set` does nothing under the paused ticker |
| `rng(seed)` | the only randomness a block may use (mulberry32; the same generator REVEAL uses) |
| `arrive(tl, el, at, {dy 24, scale0 .985, dur .5})` · `leave(tl, el, at, …)` · `cascade(tl, els, at, {gap0 .06, decay .84, cap .5})` | the shared entrance (power4.out), exit (power4.in) and waterfall (gaps 0.06 s × 0.84ⁱ, group offset capped at 0.5 s) |
| `EASE` | the vocabulary every lib shares: push `sine.out`, pan `sine.inOut`, reveal `power4.out`, exit `power4.in`, settle `power3.out`, expo `expo.out` — mirrored in `grammar.js` `EASE_NAME / EASE_FN / easeFn` |
| `get / remove / list` | inspection; `list()` gives `{id, start, end, dur}` per block |

Rules that keep a block seek-safe: every tween is a `fromTo` with explicit from-values (a bare `.to()` reads
its start from whatever the first-rendering worker saw); the DOM's inline state at mount equals the first
from-state; no zero-duration tweens — a hard cut is a 1/60 s tween with a step ease that is 1 on the cut
frame; nothing outside the block root is touched at local 0; 2D transforms only (`force3D:false` — measured
68 dB PSNR run-to-run on a 0.9 → 1 button press until it was set); no `will-change` on anything (a promoted
layer rasters at a scale picked from its transform history — 46/76 frames differed on a settling glass panel);
per-frame text or paint goes through a GSAP property plugin whose `render(ratio)` is pure. Any immediate
write outside a block goes through `MOTION.set` — a bare `gsap.set` never renders under the paused clock
(`typo.js` slam / heroWord pivots were the live case). Lint forbids `gsap.ticker` play, `.play()/.resume()`,
`repeat: -1`, timelines on the global clock (`timeline_autoplay`) and `will-change` (`will_change_layer`).

## TYPO — text that moves on the clock

Every builder is `TYPO.<name>(tl, el, opts) → {start, end, …}`, called inside a block build; it splits the
text once (`.ty-w` wrapper for transform + blur, `.ty-i` child for opacity + colour) and chains on `state.end`.

### Tokens (`TYPO.tokens`)

| Group | Values |
|---|---|
| size | display 64 · 44 · 32, body 22, label 16 (16–18 — 16 stage px / 24 px at 1080p is the legibility floor for every label, kicker and tick), hero word 0.16–0.22 h (115–158 px) |
| weight / tracking | display 400 −0.01 em · label 500 +0.12 em caps · hero 700 |
| colour | navy #082A34 / #204A56, ink #E9F3F9, cream #ECDEC3, coral #E56B5E, mint #81A9AB, gold #E8C874 |
| motion | entry 0.55 s power3.out, blur 3.5 → 0 px, travel 36 px; exit 0.30 s power4.in lift 22 px; stagger 0.06 s × 0.84ⁱ ≤ 0.5 s |

### Builders

| Builder | What the eye sees | Numbers |
|---|---|---|
| `centerBuild(tl, line, {times \| gap, mode})` | words arrive one by one from the right with a short blur; in `'run'` mode (default) the visible run stays centred — shown words glide left by half the new word's measured width; `'slot'` slides each word into a fixed layout | 36 px, 0.55 s power3.out, blur 3.5 px; gap 0.12 s or one `times[i]` per spoken word |
| `swap(tl, host, {to, matchCut})` | a phrase replaced: outgoing lifts and fades, incoming rises in under it | out 22 px / 0.30 s power4.in; in from +22 px / 0.42 s power4.out, 0.15 s later |
| … `matchCut: true` | shared leading/trailing words stay put; only the differing run swaps, inside a cell whose width glides so the line re-centres by a few px instead of jumping | cell wA → wB over 0.42 s power3.inOut |
| `stagger(tl, el, {by: 'char' \| 'word'})` | letters or words waterfall in, gaps tightening | rise 18 px, 0.42 s power4.out; 0.06 s × 0.84ⁱ, cap 0.5 s; spaces take no slot |
| `scramble(tl, el, {dur, seed})` | glyph soup resolves left → right into the text; soup in mint, locked glyphs in ink | 0.6–1.0 s (default 0.8), 15 glyph changes/s, seeded by a hash of the text; each slot pre-sized to its final glyph |
| `slam(tl, el, {kicker, hold})` | a 1–3 word hit lands on its spoken word | scale 1.12 → 1 over the 0.165 s pulse (expo.out), opacity snaps in 0.05 s; kicker label 0.25 s earlier; optional 1.2 %/s hold push |
| `shimmer(tl, el)` | one light band sweeps across the glyphs | 0.9 s sine.inOut, gold band at 100°, 16 % wide; works across a split line |
| `heroWord(tl, line, {word})` | one word promoted: colour, weight, a little bigger | coral, 700 set at build (no reflow), scale 1.08 over 0.35 s; `weightAt: 'promote'` snaps the weight at the hit inside a pre-sized slot |
| `fit(el, maxWidth, {min 24, max 64})` | a long title shrinks to its column before frame 0 | 0.5 px steps, canvas-measured, no layout pass |
| `lockup(tl, host, {kicker, title, sub, build, fit, sizes})` | kicker → title → rule draws → sub | kicker at the label token (16 px; the sample's close kicker 22 px via `sizes.kicker`) rising 12 px / 0.4 s; title rise + blur 0.55 s (or `build: 'center' \| 'stagger'`); rule scaleX 0 → 1 over 0.5 s power4.out at title + 0.42; sub rises 16 px / 0.5 s, 0.2 s after the rule |

`TYPO.enter / exit` are the shared entry and exit every builder uses; `TYPO.measure(text, font)` is the
synchronous canvas `measureText` behind run-mode glides, match-cut cells, scramble slots and `fit`. The
`typoPaint` GSAP plugin (`tl.to({}, {duration, ease, typoPaint: fn})`) calls `fn(u)` on every render —
forwards, backwards, on a worker jump — for effects that must rewrite text or backgrounds over time.

### Rules

1. **Key to words.** `at` / `times` come from `wt(phase, word)`; a title word lands as it is spoken. Never
   animate the caption lane or lower thirds with these builders — they have their own grammar.
2. **One builder owns a line.** Chain effects on one line in one block build (`heroWord` after `centerBuild`
   shares the split). `shimmer` after `heroWord` on the same line is not allowed (the colour is still
   tweening); put the second effect on a second element.
3. **Layout is final before frame 0.** Splits, slot widths and fits happen at build; only a match-cut cell
   changes a line's geometry mid-shot. Build after `document.fonts.ready` when the scene declares
   `@font-face src: local()` faces (the renderer waits; blocks built at script load do not).
4. **Blur on the wrapper, opacity on the child**, filter cleared when the blur reaches zero so settled glyphs
   stay crisp at DPR 1.5. Blur windows ≤ 0.6 s — a full-frame filter costs render time.
5. **Per-character splits lose kerning pairs.** Use word splits for display serif lines, char splits for
   short hits and mono labels.
6. **Seeded only.** The same seed renders the same soup forever.
7. **Footage is sacred.** These builders draw on recreated cards and screen-space layers; nothing touches
   `#camera` or the footage lane.

### Doctrine fit

Entries ≤ 0.8 s (longer = a stagger), exits ≈ 75 % of entries, siblings share one ease and duration. A word
swap is a `y` move and a slam is a `z` arrival — spend them where the vector law allows (one reserved vector
per act). A run-mode build on the title card, one match-cut swap and one slam is a full trailer's worth of type.

## Lint and test

`gsap.min.js` under `node_modules` is a known library (left unlinted); `lib/motion.js` parks the global
timeline with `pause()` by design; `typo.js` injects one layout-only `<style data-typo>` and uses a 2D
canvas for measurement only. Both libs lint with 0 errors. Test any scene that uses them: render twice with
one worker, `ffmpeg -f framemd5`, diff empty; then the seek canary (step vs jump vs shuffled inside one
page, PNG hashes equal).
