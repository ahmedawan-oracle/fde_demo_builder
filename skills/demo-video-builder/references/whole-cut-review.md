# Whole-cut review — the reviewer proposes, you choose (v5.1)

Gates find what is wrong in a frame or at a cut. A film is also wrong or right as a whole: the rhythm of its shot
lengths, the kind of transition at each cut, whether the grade holds from the first beat to the last, whether the
loop closes. That pass is a viewing, not a measurement, and its notes arrive as approximate timecodes. Two things
make them usable: snapping each note to the edit, and recording the decision on each note — including the
rejections. Code: `agents/demo-qa-reviewer.md` (the whole-cut pass), `tools/review_notes.py`, `tools/export.py
share_pack` (the table in `DELIVERY.md`).

## The pass (demo-qa-reviewer, last step)

Watch the whole cut once at speed, then once with the shot list open, and write one note per observation:

| Lens | What to look for | Note kind |
|---|---|---|
| rhythm | shot lengths against the narration pace — a run of equal lengths reads as a slideshow, one long beat after short ones reads as a stall; the breather is the one deliberate still | `rhythm` |
| transition per cut | name what the cut *is* (hard cut on a word, seam on the current, gl accent, match-cut hand-over, reveal) and whether that is what the ledger says; a dissolve or a fade between scenes is a finding, not a style | `cut` |
| grade | the recreated layers keep one palette and one contrast across the film; product footage keeps its own and is never graded; a jump at a cut between two recreated beats is a note | `grade` |
| loop closure | for a booth loop, the last frame against the first: does the dip land on the same ground, does the credit clear before the head fade | `loop` |

Each note: a timecode as heard, the observation, the fix you would try. The agent does not change files; it hands
the notes over.

## The ledger (`tools/review_notes.py`)

```
python tools/review_notes.py add --t 12.4 --note "the title leaves before the word" --kind cut --by reviewer
python tools/review_notes.py import notes.txt                 # "12.4 note" | "0:12.4 note" | "t=12.4 note" | "[12.4] note"
python tools/review_notes.py decide 1 --accept --why "moved the exit 0.3 s later"
python tools/review_notes.py decide 2 --reject --why "the comma before the send is deliberate (SEAM.comma)"
python tools/review_notes.py list | table
```

Every note is snapped to the nearest boundary of the edit in `out/timeline.json` — a seam row (by id), a cut, a shot
start or end, the head or the tail — and keeps the distance it moved (`+0.70 s`). A timecode read off a player is
never a frame; the edit is. `remap` moves the notes with the edit after a narration regen.

`out/review/review_notes.json`: `{film, timeline, notes:[{n, t, shot:{t, label, delta}, note, kind, by, accepted,
why}]}`. `accepted` is `null` until decided; `list` exits 1 while anything is pending, so a pack is not shipped with
undecided notes.

## Why rejections are kept

A note that was seen and declined is information for the next reader — the stakeholder who had the same thought,
the editor who rebuilds the film in a year. `export.py --preset share_pack` prints the full table into
`DELIVERY.md` under *Reviewer notes — proposed, decided*: at, nearest boundary, kind, note, **accepted** /
**rejected**, why, and the count. The reviewer's eye proposes; the editor decides; the delivery shows both.

Selftest (no browser, no ffmpeg): `python tools/review_notes.py --selftest` — boundaries from a synthetic timeline,
snapping, the import forms, decisions persisting, the table, remap after a changed clock. `python tools/export.py
--selftest` proves the table lands in `DELIVERY.md`.
