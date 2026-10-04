# Four tones and speed contrast — the colour the film rests on, the speed it moves at (v5.1)

Two rules that make a cut read as one film instead of a sequence of frames: the palette has four roles and the
playback speeds have a ladder.

## Four tones (`design.md tones:`, gate `palette tones` in `skin_gate`)

```yaml
tones: { black: black, mid: ground2, live: accent, warm: gold }     # names from colors:, or hexes
```

| Role | What it is for |
|---|---|
| `black` | the dark the film rests on — the head fade, the ground under the cards |
| `mid` | the mid the recreated layers sit in — plates, panels, the ground gradient's lighter stop |
| `live` | the one accent that **moves**: the hue the eye tracks — the figure that counts, the rule that draws |
| `warm` | the one accent that **lands**, once: the closing card's highlight, the receipt's seal |

`palette tones` checks: four roles present and resolvable; luma ordered `black < mid < live, warm`; `live` and `warm`
saturated (> 0.25) and at least 30° of hue apart — one cool accent that moves, one warm that lands. Without a `tones:`
block the gate passes with a note. `templates/design.example.md` carries the house four.

## Speed contrast (motion-doctrine.md, reported by `motion_diag` `seq quantized`)

A film where every clip plays at 1.0× has no tempo. Product footage reads best **1.3–1.5×** (a UI that answers
briskly; the idle detector's ramps go further where nothing happens); people — a presenter, a hand — **~0.8×** (a face
at 1.3× looks nervous). The slowest beat of a film sits about 3× slower than the fastest. `seq quantized` prints the
playback rate of every real-motion shot (`playback rates send 1.00x, wizard 1.40x`) and WARNs when a rate is outside
0.5–2.0× (slower reads as a stall, faster as a glitch) or when every clip sits at the same rate. The cut list is where
the speeds are set (`cutlist.py --fit`, `speed` column).
