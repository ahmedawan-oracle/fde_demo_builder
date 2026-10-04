# Reference study — borrow craft, never content (v5.1)

Before a storyboard, name the films this one wants to resemble and write down what they *do*: how long a shot
runs, how the camera behaves, how the light sits, how the cut lands. Never what they *show*. The references become
numbers the plan and the gates are checked against. Code: `tools/ref_study.py`; log: `refs.json`; output:
`REFERENCES.md` (generated).

## Log a reference you watched

```
python tools/ref_study.py log --title "Study A" --note "calm, three-beat rhythm" \
    --shot "2.4|static|soft key|hard cut" --shot "1.2|push in|hard|match cut" --shot "3.5|hold|soft|hard cut"
```

One `--shot` per shot: `length s | camera | lighting | cut`. Five to ten references is the useful range; three
is thin, twenty is a catalogue nobody reads.

## Measure a film you have

```
python tools/ref_study.py measure path/to/film.mp4 --title "Study B" --note "a booth loop"
```

Ten frames a second at 160x90 grey, one ffmpeg pass. Cuts are the frame-difference outliers above
max(8 grey levels, mean + 3σ), merged within 0.3 s; from them the shot lengths, the median shot, the cut rhythm
(cuts per 10 s; the coefficient of variation of the lengths — under 0.4 reads as metronomic, over 1.0 as uneven on
purpose), per-shot mean luma and its spread (contrast), and the film's luma percentiles p10 / p50 / p90. The
measured shots are logged like the watched ones; the summary rides along.

## The report

`python tools/ref_study.py report` writes `REFERENCES.md`: the table of references and the rules this film inherits —

| Rule | Derived from |
|---|---|
| target median shot; most beats within p25–p75 of every logged shot; nothing longer than the longest without a written reason | shot lengths |
| cuts per 10 s band; shot-length CV band (pick metronomic or uneven and write it under `## Video direction`) | measured references |
| luma band and middle for the recreated layers' ground and ink (product footage keeps its own) | luma percentiles |
| within-shot contrast band (softer reads flat on a booth screen, harder fights the captions) | per-shot spread |
| camera vocabulary and cut vocabulary — use these and no others; 2–3 cut techniques per film | the `camera` / `cut` columns |

The storyboard's beat durations and `## Video direction` are written against these numbers; `no long freeze` and
`hold still` guard the long shots, `seam ledger` the technique count.

## Craft not content

`python tools/ref_study.py lint` fails any entry whose text names content — *logo, tagline, slogan, their text,
same scene, recreate, copy the, frame for frame, screenshot of, brand colour, trademark, verbatim, lyrics,
characters from* — or quotes a string (on-screen words are content). `log` and `measure` refuse such an entry on
the spot; `report` refuses to write while lint fails. A reference row carries four craft fields and nothing else.

Selftest: `python tools/ref_study.py --selftest` — a synthetic four-shot film (2 / 1 / 3 / 2 s) measured to its
cuts, lengths, luma and contrast; a clean log and a report; a content entry caught by lint and refused by report.
