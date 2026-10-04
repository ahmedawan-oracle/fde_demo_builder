# Text that fits, strokes that finish, captions that own their shape (v5.1)

Three small rules learned on a real build, each caught by a gate so nobody has to read every frame for them.

## 1. No text box overflows its box — `gates/overflow_gate.py`

A caption that wraps one word past its pill, a kicker whose last glyph is clipped, a card line that runs under the
card's edge: the renderer reports nothing and the frame shows a cut-off word. The gate opens the scene once in
headless Chrome, seeks it every second, and reads every visible element that carries text of its own: when
`scrollWidth` exceeds `clientWidth` or `scrollHeight` exceeds `clientHeight` by **more than 3 px**, the text does not
fit. Each offender is reported with its time, id, text and box, and the full measurement goes to `out/qa/overflow.json`.

Excluded on purpose, because they are not failures:

| Excluded | Why |
|---|---|
| icon-node labels (`class` contains `icon` / `node-label`, or `data-overflow-ok`) | a label is drawn wider than its node by design |
| line-height rounding (vertical excess under half the font size, no horizontal excess — a 64 px headline, a 22 px karaoke word span) | a descender past a tight line box; a lost line is at least one line tall |
| full-stage containers (≥ 95 % of the stage in both axes) | the stage scrolls nothing a viewer sees |

`qa.json: {"overflow": {"step": 1.0, "px": 3, "line_frac": 0.5, "ok_classes": ["icon", "node-label"]}}`. Runs in
the `full` profile (it needs the browser: ~1 s per sampled second); standalone
`python gates/overflow_gate.py scenes/film.html --total 35.4 --step 1`. Fix: a wider box, a shorter line, a smaller
size — never `overflow: visible`, which only hides the number.

## 2. A draw-on stroke finishes — `lint_scene` rule `dash_nonscaling_stroke`

An icon or a rule that draws on animates `stroke-dashoffset` from the measured path length to zero. The dash is
measured in the path's user units, and `vector-effect: non-scaling-stroke` makes the browser scale the stroke
pattern by the inverse of the path's transform — so on any scaled path the dash no longer equals the measured length
and the draw-on stops part-way (or overshoots). Seen on an icon draw-on frozen at about 70 %. The lint fails any
authored scene or library file where a `stroke-dashoffset` animation shares the file with
`vector-effect: non-scaling-stroke` (CSS, attribute or `setAttribute`). Drop the effect on every path that draws on,
or scale the dash length by the path's transform.

## 3. Captions may own their shape — `overlay_gate` `caption shape`, explicit limits

The lane's per-style limits (words and characters per line) assume word-group captions. A film that regroups the
lane into whole spoken clauses (`captions.json` grouping) knows its own shape: when `qa.json` sets **both**
`caption_max_words` and `caption_max_chars_per_line`, `caption shape` uses those numbers as the limits instead of
clamping them to the style's own. The pixel measurement stays the hard constraint either way — a line may never
measure more than 92 % of its box. Setting one key without the other keeps the old behaviour (tighten only).

Selftests: `python gates/overflow_gate.py --selftest` (the judge on synthetic measurements) and `--selftest --chrome`
(a tiny scene through the real probe: a pill that overflows throughout, a line that appears and overflows at 2 s);
`python gates/lint_scene.py --selftest` (the bad snippet carries a dashed path with non-scaling-stroke);
`python gates/overlay_gate.py --selftest`.
