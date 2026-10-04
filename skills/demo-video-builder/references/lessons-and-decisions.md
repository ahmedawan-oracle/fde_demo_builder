# Lessons by step, and the decisions kept manual (v5.1)

Every step of the flow was built on one lesson from a real build. The lesson is printed where the step runs, so the
reason travels with the command; and every delivery lists what no gate decided — a person did — with the file that
records it. Code: `tools/lessons.py`, `build_film.py` (`lesson()` under its stage headers), `tools/export.py share_pack`
(`DELIVERY.md → Decisions kept manual`).

## Lessons

```
python tools/lessons.py qa            # one step
python tools/lessons.py --md          # the table SKILL.md carries
```

Each entry is one sentence of cause, one of consequence, and what the step leaves to a person on purpose. The
table lives in `SKILL.md` ("Lessons by step") and is generated from `lessons.py`, so the two never disagree. A lesson
changes only when a build teaches us otherwise.

## Decisions kept manual (`DELIVERY.md`)

| decision | what was chosen | where it is recorded |
|---|---|---|
| final length | seconds and frames | the narration clock + the closing tail |
| cut points | cuts, seam rows, the current | `seams.json` · `out/timeline.json` |
| speeds | every re-timed clip's rate (and reverse) | `cutlist.txt` · `shots.js play{}` |
| holds | the held segments and their fractions | `FILM.holds` · `STORYBOARD.md hold:` |
| take | which take shipped, its wall time, scene hash and gates | `out/takes.jsonl` · `.history/takes/` |
| reviewer notes | accepted / rejected / pending | `out/review/review_notes.json` (table above it) |
| frame approvals | START and END approvals | `out/review/approvals.json` · `out/pairs/pairs.jpg` |
| sign-off | who signed, or *not signed* | `STORYBOARD.md ## Locked` |

The table is built from the project files at export time — nothing is typed in by hand — so it says what the
project actually recorded, including the gaps ("none recorded", "not signed").

Selftests: `python tools/lessons.py --selftest`; the decisions table is asserted inside `python tools/export.py
--selftest`.
