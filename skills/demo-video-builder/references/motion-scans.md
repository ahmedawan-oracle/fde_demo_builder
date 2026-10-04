# Motion scans — spikes, half-frame pans, the roster (v5.1)

Three failures a frame-by-frame eye catches and an average does not. They live in `gates/motion_diag.py` as flags
and the first also rides along as a WARN inside the `motion traced` gate.

## `--spikes` — the single-frame jump

```
python gates/motion_diag.py --spikes out/<film>.mp4
```

The film at 10 fps, 320x180 grey, as a series of frame-to-frame changes. A **spike** is a frame that differs from
both of its neighbours by more than 2 % while the frames before and after it are nearly the same picture (their
difference under a quarter of the jump): the picture jumped and came back — a dropped frame re-ordered, a glyph
that rendered once, a compositor miss. The plain isolated outlier (one step more than 4× both neighbours) is
reported too, for a dropped or doubled frame. Steps touching a cut are skipped; cuts are supposed to jump. Exit 1
when any spike is found; the gate detail lists `(t, %, before, after)`.

## `--pan-halves` — a partial pan

```
python gates/motion_diag.py --pan-halves out/<film>.mp4 12.0 15.0
```

The camera recovered (scale + shift, the Fourier–Mellin / phase-correlation estimator `motion traced` uses) on the
**left half** and the **right half** of the frame separately, per 0.1 s interval. A real pan or push moves both
halves the same way. When one half moves and the other does not — a shift difference over 1.5 px or a scale
difference over 0.01 with either half moving — the camera did not move; one element did. That is a partial pan: a
slide that pretends to be a camera move, or a card drifting under a still frame. Exit 1 when any interval
disagrees; the printout shows both halves' numbers and marks `PARTIAL`.

## `--roster` — who arrived, who left

```
python gates/motion_diag.py --roster out/pairs/title_start.jpg out/pairs/title_end.jpg
```

OCR both stills with the leak gate's engine and compare their named entities (Title-case words of three letters
or more, stop words removed): `new` and `gone` between the two. The people-roster check of a start → end pair when
the storyboard is not at hand (`pair roster` does the same against the `end:` sentence). Without an OCR engine the
command prints a note and exits 0.

Selftest: `python gates/motion_diag.py --selftest` — a one-frame jump in a still sequence is caught once and not
near a cut; a left-half-only shift disagrees while a whole-frame pan and a still frame agree.
