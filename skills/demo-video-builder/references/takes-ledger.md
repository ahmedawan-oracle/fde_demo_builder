# Takes — what every build cost, kept until the review is locked (v5.1)

A retake is free in pixels (two renders are byte-identical) and not free in time. The take ledger says what each
build cost, whether its picture changed, and how its gates went; retention keeps every take's scene and film until
the plan is signed off, so a reviewer can ask for "the one before" and get it. Code: `tools/takes.py`,
`build_film.py` (`take_ledger()` at the end of a build).

## The ledger — `out/takes.jsonl`

One line per build:

```
{"take": 4, "when": "2026-10-04T11:02:17", "scene_md5": "9b1c…", "wall_s": 61.2, "frames": 1170, "workers": 3,
 "gl": "software", "gl_renderer": "ANGLE (…)", "film": "out/Acme_Film.mp4", "gates": {"pass": 48, "fail": 1, "failed": ["hold still"]}}
```

`scene_md5` is the md5 of `scenes/film.html` + `scenes/shots.js`: two takes with the same hash rendered the same
picture, so a changed hash beside a gate flip says which edit did it. `gl` / `gl_renderer` come from the render
receipt (the last JSON line `render_frames.js` prints); `wall_s` is the whole build. `gates` is filled by
`takes.py annotate` after `qa_film.py` has written `out/qa_report.json` (QA runs after the build).

```
python tools/takes.py list        # take · when · wall s · frames · workers · gl · gates · scene hash · same / CHANGED
python tools/takes.py time        # last, median and total wall seconds; frames rendered per wall second
python tools/takes.py annotate    # copy the gate verdicts of out/qa_report.json onto the newest take
```

## Retention — `.history/takes/<take>/`

`build_film.py` calls `takes.py keep` after every build: `scenes/film.html`, `scenes/shots.js`,
`out/timeline.json`, `out/qa_report.json` (when present) and the film are copied under `.history/takes/004/`
with `take.json`. Nothing is deleted on its own. Once `tools/review_pack.py --lock` has written `signed off by`
into `## Locked`:

```
python tools/takes.py prune --after-lock [--keep 1]
```

removes the older takes and keeps the newest `--keep`. Before the lock the command refuses — a reviewer's "go
back two takes" must still be answerable while the plan is open. `.history/` is git-ignored and never leaves
the project (`export.py share_pack` excludes it).

Selftest: `python tools/takes.py --selftest` — two synthetic takes with a scene change between them, annotate
from a QA report, keep, time per take, prune refused before the lock and applied after it.
