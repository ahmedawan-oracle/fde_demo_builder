# Frame pairs and approvals — first and last still per shot, approved before the cut ships (v5.1)

Reviewers read a film from stills before they watch it. One still per shot (the golden set) says *what* a shot
is; two stills — the frame it opens on and the frame it leaves on — say whether the cut will work, because every
cut is the end frame of one shot meeting the start frame of the next. Code: `gates/snapshot.py --pairs`,
`tools/review_pack.py` (Approve start / Approve end → `approvals.json`), `tools/storyboard.py check --build`.

## Capture

```
python gates/snapshot.py --pairs out/<film>.mp4          # from the rendered film (ffmpeg, no browser)
python gates/snapshot.py --pairs scenes/film.html        # from the scene through the canary probe
```

For every segment — the title card, each footage shot, the closing card — the frame at `t0 + 0.1 s` and the frame
at `t1 − 0.1 s` go to `out/pairs/<label>_start.jpg` and `<label>_end.jpg` (960x540, `--png` for 1280x720), tiled as
rows START | END in `out/pairs/pairs.jpg`, listed in `out/pairs/pairs.json`
(`{label, t0, t1, start:{t, file}, end:{t, file}, changed_pct, static}`). Segments come from `scenes/shots.js`
(via node) or `out/timeline.json`. Segments under 0.3 s have no still to approve and are skipped. A pair whose two
frames differ by less than 0.5 % of pixels is flagged `static`: nothing moved — a slide, not a shot.

## Approve

`python tools/review_pack.py build --project .` shows the pair under every beat (a segment belongs to the beat whose
span holds its midpoint; a beat with two segments opens on the first START and leaves on the last END), with the
storyboard's `start:` / `end:` sentence beside each frame and two buttons: **Approve start**, **Approve end**. Save
writes `out/review/approvals.json` (`{pack, approvals:[{beat, start, end, by, at}]}`) — POSTed to `/approvals` when
served, downloaded beside `comments.json` when opened as a file. The header pill counts END approvals; an unapproved
END and a static pair are honesty flags.

Approve the END frame first. It is the frame the next cut lands on, and the frame a reviewer remembers.

## The gate

Once `out/review/approvals.json` exists, `tools/storyboard.py check --build` (which `build_film.py` runs in
preflight) refuses while any beat's END frame is unapproved: `beat 06: END frame not approved (approvals.json)`.
`--require-approvals [path]` forces the check on; `--no-require-approvals` opts out for a drive-it run. The approval
is per pack version — a storyboard edit that changes an end state wants a new look at the frame, so re-run `--pairs`
and re-approve; the pack id (`<title>-v<version>`) is stored with the approvals.

## Why two frames and not the film

- A still is reviewed in a second; a film takes its own length. Ten shots are twenty stills on one sheet.
- A wrong end frame is visible before a render exists: `storyboard.py sheet` prints the two sentences, `--pairs`
  on the scene prints the two frames, and the pair is compared with the sentence, not with a memory of the film.
- The approval is a record. `approvals.json` says who approved which frame and when; the lock (`--lock`) and the
  `review lock` gate remain the sign-off for the whole plan.

Selftest (no browser): `python gates/snapshot.py --selftest --pairs` builds a synthetic film with a title, a sliding
shot, a frozen shot and a close, and checks the plan, the files, the times and the static flag.
`python tools/review_pack.py --selftest` maps synthetic pairs to beats, posts approvals and proves the storyboard
check reads the same file.
