# Motion doctrine: seams, the current, carriers (v4)

How a film feels like one camera move instead of a stack of slides. The law is in Part 1, the catalog
and its numbers in Part 2, the ledger + gate in Part 3, performance between seams in Part 4. Code:
`scripts/film/lib/seams.js` (`window.SEAM`), gate: `scripts/film/gates/seam_gate.py`, ledger template:
`scripts/film/templates/seams.example.json`. Everything measured on the 1280x720 stage (12 % = 153.6 px).

## Part 1 — The vector law

How a scene leaves decides how the next one arrives:

1. **Axis** — x stays x, y stays y, z stays z across the cut.
2. **Direction** — never mirrored. On z the direction is the sign of d(scale)/dt: growing = push,
   shrinking = pull. The classic violation is a pull-back exit answered by a grow-from-small entry.
3. **Speed** — matched through mirrored eases: exit `power4.in`, entry `power4.out`, same distance; the
   incoming side is already past the half of its notional path when we see it.
4. **Phase** — the cut lands mid-motion on BOTH sides. A card that settles and then cuts, or an entry that
   starts from rest, is a dead beat (the `seams move` gate measures exactly this).

**The current.** A film picks one direction for every ordinary seam — house default LEFT (`x-1`). The other
vectors are reserved and spending one means something; spend at most one per act:

| Vector | Meaning in a demo film |
|---|---|
| `x-1` the current | next beat, neutral progress: title → footage, footage → footage |
| `y-1` upward | elevation: the conclusion / close card rises above what came before |
| `z+1` push (zoom-through) | deeper into the same thought: a headline that becomes its detail |
| `z-1` pull (inverse zoom) | ARRIVAL: the answer, the payoff, the held end state lands |
| a scale burst | leaving a world — rare, usually once, at a chapter boundary |

Consecutive seams never oppose each other (ping-pong reads as an error); a direction change needs a
visible cause (`cause: "click" | "chapter" | "impact"` in the ledger row).

**Carriers.** The eye follows objects. The strongest seams hand one concrete thing across the cut at
matched position and velocity: the typed question plate becoming the sent message, the lower-third label,
an odometer figure that becomes the on-screen number, a cursor mid-path. Carriers land on something that is
really in the recording — never carry a synthetic element into the product frame as if the product drew it.
Tolerance: 12 px centre, 5 % size at cut ± 1 frame. With no natural carrier the scene heroes carry the
motion (partial travel + early fade, entry mid-flight). A crossfade carries nothing and is banned.

**Cause before effect.** Each move is launched by the last (click → press → release → flight → impact →
reveal); the effect starts ON the causing frame, big things rebound slower, small things snap, and a force
is the only licence to change direction. Only for recreated scenes: the recording owns its own causality.

Anti-patterns: a fade between scenes; the exit completes, then the scene changes; an entry from rest; a pull
exit answered by grow-from-small; the incoming scene's own pop-in under a z seam (hold it composed for the
first 0.5 s); reserved vectors used as variety; a reaction a few frames after its cause.

## Part 2 — The catalog (lib/seams.js)

All helpers are pure functions of `t` returning `{out:{x,y,s,op,blur,visible}, in:{…}, phase}`; one side is
visible per frame (opacity < 0.04 counts as invisible). Numbers are the defaults.

| Helper | Vector | Exit | Entry | Notes |
|---|---|---|---|---|
| `SEAM.cutCurve(t, cut, {axis:'x', dir:-1})` | x / y | 12 % (153.6 px) on power4.in, 0.34 s, opacity power3.in to 0 (still 27 % one frame before the cut, gone on it) | from 12 % off at 0.35 opacity, power4.out, 0.42 s | the default boundary; `fadeFrac: 0.3` = hand form (gone by 30 % of travel) for word cascades; `blur` 8–10 optional |
| `SEAM.zoomThrough(t, cut, {blur:10})` | z+1 | 1 → 1.2 power3.in 0.2 s, blur 0 → 10, separate linear fade to 0.15 | 0.75 → 1 expo.out 0.5 s from 0.15 | headlines only; blur 18 for a full-frame surface |
| `SEAM.inverseZoom(t, cut, {blur:10})` | z-1 | 1 → 0.8, 0.21 s | 1.25 → 1 expo.out 0.49 s | arrival beats only; the incoming arrives composed |
| `SEAM.combined(t, cut)` | x-1 + z-1 | slide 12 % and 1 → 0.92 | arrives at 1.08 and slides home | when the previous beat ends pushed in and the next must open on the whole screen: both sides shrink |
| `SEAM.rackFocus(t, cut, {peak:12, dx:80, scale:1.06})` | x (small) + z+ | fully opaque, blur to peak (8–12, max 18) + lens breathing 1.06, power2.in 0.30 s | refocus power2.out 0.36 s, 1/1.06 → 1 | the one cut meant to be seen: same surface, new state; ≤ once per ~8 s, never mid-caption |
| `SEAM.waterfallCut(t, cut, nOut, nIn)` | x-1 per word | 0.34 s power4.in each, 0.18 s fade, +0.022 s stagger; last word dies 0.02 s before the cut | 0.30 s power4.out from 0.35, gaps 0.05 s × 0.84 | recreated text beats only; returns arrays |

In-scene (no cut):

- `SEAM.cascade(t, t0, items)` — **arrivals snap, seams fade**: binary 0 → 1 visibility, whip from below on
  power4.out. heavy 70 px / 0.18 s then a 1-frame gap; word 45 px / 0.15 s overlapping 1 frame; light 40 px /
  0.12 s overlapping 2; `frag` (split final word) 70 px / 0.16 s. Group stagger capped at 0.5 s (delays are
  tightened, not durations). Key `t0` to `wt()`. Never on captions or lower thirds.
- `SEAM.nudge(t, t0, dist, 0.57)` — slow-fast-slow slide: power3.in 10 % of distance in 20 % of time, linear
  burst 65 % in 18 % (about 2× average speed — reveal new content here), power4.out tail 25 % in 62 % (≥ 3×
  the ramp). Reference 270 px: −30 @0.12 s, −210 @0.22 s, −270 @0.57 s. `SEAM.nudgePhase()` says which.
- `SEAM.carrier(t, cut, {from, to, lead:0.3, tail:0.6})` — rect covering the first third on power2.in before
  the cut, finishing on power2.out after, speeds equal at the cut. `SEAM.cursorHandoff(cut, a, b)` gives the
  two cursor legs; `SEAM.morphRect(t, t0, dur, A, B, rA, rB)` docks a container (0.6–1.2 s, old content gone
  in the first 40 %, new in the last 40 %).
- `SEAM.comma(t, action, {hold:0.45, dwell:1.0})` — stillness before climax: the result lands 0.3–0.75 s
  after the click / send, then stays ≥ 1 s (2 s dramatic): `SEAM.dwellOK(resultAt, shotEnd)`. Write the
  comma into the script too (`pause` after the question phrase): the narration is the clock.
- `SEAM.idle(t, t0, t1, {amp:0.012, period:2.2, N})` — only if a loop is unavoidable: ±1.2 % scale, phase 0
  at t0, fades over the last 20 % before a seam, 1/√N for concurrent idles.

Eases exposed: `EP2I/EP2O, EP3I/EP3O, EP4I/EP4O, EXPO_O, BACK_O(1.4–1.7)`. No bounce, no elastic.

Blur: 10 px for text, 18–20 px for a full-frame surface, never on something that must be read now; put blur
on the wrapper and opacity on the child (headless Chrome composites the pair badly on one element). Every
full-frame blur costs render time at DPR 1.5 — keep windows short.

## Part 3 — The ledger and the gate

Write `seams.json` before the shots: one row per cut (`seam: true` hand-offs are not cuts).

```json
{ "current": "x-1", "seams": [
  { "id": "title→notebook", "cut": "P.nb", "technique": "cut-the-curve", "act": "demo",
    "exit":  { "selector": "#titleCard", "axis": "x", "dir": -1 },
    "entry": { "selector": "#camera",    "axis": "x", "dir": -1 } },
  { "id": "answer→close", "cut": "P.close", "technique": "inverse zoom-through", "act": "close", "cause": "chapter",
    "exit":  { "selector": "#camera",    "axis": "z", "dir": -1 },
    "entry": { "selector": "#closeCard", "axis": "z", "dir": -1 }, "opts": { "blur": 10 } } ] }
```

`cut` is seconds or a cue expression (`P.<phase>`, `P.<phase>_end`, `wt('phase','word'[,n])`, arithmetic);
a cue that does not resolve throws. In the scene: `SEAM.build(ledger, TX)`, `SEAM.validate(rows)` at load,
then once per frame after the base state is drawn `SEAM.apply(t, ['#camera'])` — layers the scene composes
itself (the footage `#camera` wrapper) take `SEAM.offset(t, '#camera')` and add `x/y` to the translate,
multiply `s` into the scale and apply `op/blur`. `SEAM.windows()` / `SEAM.toJSON()` give export_timeline.js
the resolved rows for `out/timeline.json`, so the gate and the scene read one source of truth. A VO regen
moves every cut and every seam together; it also re-opens every seam — rerun the gate.

`gates/seam_gate.py` (qa_film.py plug-in):

| Gate | Checks | Threshold |
|---|---|---|
| `seam ledger` | axis + direction agree per row; no ping-pong between consecutive seams without a cause; cuts inside the film | WARN: > 3 techniques; > 1 reserved vector per act |
| `seams move` | per row, on the rendered film: dominant motion (phase correlation x/y, dominant scale z) in cut−0.1 s..cut−1f and cut+1f..cut+0.1 s has the ledger's sign; the cut frame is not a mix of its neighbours | static < 15 px/s on a 1920 frame (5 px/s at 640) or < 0.04 scale/s; speed ratio > 3 WARN; blend = both neighbours' structure in the cut frame |
| `seam flash` | frames within ±2 of every cut (timeline + ledger) | mean luma above BOTH neighbours by > 40, or > 235 while neither neighbour is |
| `stage ground` | html/body/#stage declares an opaque background | static |
| `idle wobble` | `Math.sin/cos(…t…)` feeding transform/left/top outside `data-diegetic` | WARN only |

`python gates/seam_gate.py probe out/<film>.mp4 <t>` prints the measured vectors around a time so a row is
written from measurement; `--selftest` runs the synthetic film. Match-cut / morph rows (`type`) carry a
`carrier` and skip the vector checks. The final MP4 may sit one frame off the clock after mux; the gate snaps
to the real picture change within ±1 frame. Stage ground: the mid-cut opacity dip (0.35 ignition, 0.15 floor)
composites over whatever is behind — paint html/body/#stage, never leave the root transparent.

## Part 4 — Performance between seams

Idle loops (breathe, float, drift, glow pulse) are banned as a way to fill time; they read as the video
waiting. Every phase between an entry and an exit is owned by one named route:

| Route | Demo-film example |
|---|---|
| Staged reveals | title, rule, subtitle, caption each land on their spoken word |
| Camera with intent | establish on the whole screen, travel, arrive on what the voice names — by the next word |
| Sequenced UI life | the real scroll runs, highlights step, a count ticks |
| Animated sequence | a card files into the stack, the data particle reaches the agent box and lights it |
| Cursor-led action | an oversized cursor (recreated scenes only) walks the eye to the click that ignites the beat |

Test: pause at any second — something meaningful is mid-flight. Diegetic pulses (a spinner while the machine
works) are allowed and die on the frame the result lands. Flake fields are texture, not a route. Timing
intents: single entry ≤ 0.8 s (longer = a stagger of several elements), exit ≈ 75 % of entry except at a seam
(entry ≈ 127 % of exit), stagger ≤ 0.5 s with per-item 0.04–0.08 s, siblings share one ease and duration,
2–3 seam techniques per film and repeat them. Cameras: push 1.0–2.0 s, dwell ≥ 1 s, at most two real moves
per shot — see `cinematic-grammar.md`.

Worked example (fictional Acme): the title card rides the current into the notebook (`cut-the-curve`,
`#titleCard` → `#camera`), the notebook hands to the question on the same vector, and the answer arrives on
an inverse zoom into the close card (`z-1`, cause `chapter`): two techniques, one reserved vector, and every
cut lands with the picture moving.
