# Start and end frames — the storyboard as a two-still contract (v5.1)

A beat is approved on two stills before anyone sees motion: the frame it opens on and the frame the next cut
lands on. Writing both into the storyboard turns a paragraph of intent into a contract the sheet, the review pack
and the gates can check. Code: `tools/storyboard.py` (fields, `check`, `sheet --mobile`), template:
`templates/STORYBOARD.example.md`.

## The two lines

```
- start: "Monday," already inked at the headline position on the dark ground, nothing else
- end: the title card gone and the notebook's first still landed flat in the staged window frame
```

- One sentence each: the elements and their state at that instant — not the motion between them (that is
  `motion:`), not the voice (that is `vo:`). `check` warns on a second sentence or more than 40 words.
- **`end:` is mandatory on recreated beats.** `check` warns while the plan is drafted and `check --build` fails
  without it: the end frame is the one the next cut lands on, and a recreated beat that has no written end state
  has not decided where it stops moving. `start:` is advised on every beat with pixels.
- The end frame is an *edit* of the start frame: same layout anchors, the same props, the state changed. When the
  end names an element the start does not, that element's arrival is the beat's job — say so in `motion:`.
- Aliases: `first_frame / opens_on → start`, `last_frame / end_state / ends_on → end`.

## Where the two lines go

| Surface | What they do |
|---|---|
| `storyboard.py sheet` | START / END printed under every cell (END in the accent); the sheet stays script-free |
| `storyboard.py sheet --mobile` | one column under 480 px, larger type, a tap on a frame zooms it edge to edge (CSS `:focus`, no scripts) — a storyboard is reviewed on a phone, every comment there is a free change |
| `gates/snapshot.py --pairs` | captures the real first/last frame of every segment so the words can be compared with pixels → `frame-pairs-and-approvals.md` |
| `tools/review_pack.py` | shows the pair per beat with the two sentences beside the two frames and the Approve buttons |
| `gates/hold_gate.py` | the end state is what the hold protects: nothing but background moves after `hold:` → `hold-doctrine.md` |

## Review on a phone

`python tools/storyboard.py sheet STORYBOARD.md --mobile --out out/storyboard_mobile.html`, then open the file on
the phone (mail it to yourself, or `review_pack.py --serve` and open the URL on the same network). The grid becomes
one column; a tap on a frame fills the screen; a tap outside drops it. Every fix at this stage costs a sentence; the
same fix after a render costs a render.

## What `check` says

| Finding | Level |
|---|---|
| recreated beat without `end:` | WARN, **FAIL at `--build`** |
| `start:`/`end:` with two sentences or > 40 words | WARN |
| no `start:` on a beat with pixels | WARN |
| END frame not approved while `out/review/approvals.json` exists (or `--require-approvals`) | **FAIL at `--build`** (`--no-require-approvals` to opt out) |
