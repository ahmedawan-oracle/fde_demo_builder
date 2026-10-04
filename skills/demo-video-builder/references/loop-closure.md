# Loop closure — a hard cut where the edges line up (v5.1)

A booth loop restarts forever. The v4 closure is a dip: the last frame is held for a second and fades to the
skin's plate so the restart lands on the film's own head fade. It always works and it always announces itself.
`--closure hardcut` looks for the alternative: a frame near the end and a frame near the start whose strongest
vertical edges sit in the same columns, and cuts the loop there — no pad, no dip, the restart lands on a picture
that matches the one it left. Code: `tools/export.py booth_loop(closure='hardcut')`.

```
python tools/export.py --preset booth_loop --closure hardcut [--closure-min 0.6]
```

## How the cut point is found

Both ends are sampled at 10 fps, 320x180 grey: the opening 1.0 s as candidate first frames, the final 1.0 s as
candidate last frames. Every frame is reduced to its **column profile** — the sum over rows of the absolute
horizontal gradient, i.e. where the vertical edges are and how strong — mean-removed and unit-normalised. The
correlation of every (last, first) pair is the match score; the best pair at least one second apart wins. A score
of 1 is the same edges in the same columns; a drifting picture scores near 0.

- score ≥ `--closure-min` (0.6): the film is trimmed to `[first, last)`, audio with it, credit re-checked; the
  record carries `closure: hardcut`, `closure_score`, `cut_at: [first, last]` and the seam lumas.
- below it: the dip is kept, and the record says `closure: dip (hardcut fallback: best match 0.31 < 0.60)` with the
  score, so the choice is visible in `*_exports.json` and `DELIVERY.md`.

## Why column profiles

A loop reads as closed when the eye's anchors do not jump: the left edge of a card, the rule under a title, the
frame of a window. Those are vertical edges, and their columns are what the viewer tracks across the restart.
Mean luma matches too much (two dark frames always agree); a full pixel difference matches too little (a word
changed on an otherwise identical card fails it). The column profile sits between: layout, not content.

## When to use which

Hard cut when the film opens and closes on the same composition — a lockup that returns, a dashboard that ends
where it began — and the storyboard's `end:` of the last beat describes the `start:` of the first. Dip when the
open and the close are different pictures; the fallback makes that call for you and tells you the score.

Selftest: part of `python tools/export.py --selftest` — the synthetic drifting film falls back to the dip with its
score; a film whose opening half second repeats its final half second is cut and comes out shorter than the pad.
