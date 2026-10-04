# Version N+1 from N — bump the cut list by text, prove the rest unchanged (v5.1)

A new version of the edit should be the old one with a named change, and everything else provably the same. The
cut list makes that possible: version N+1 is written from version N by text replacement, the replacement names the
clips it touched, and a gate compares the two renders shot by shot. Code: `tools/cutlist.py bump`,
`gates/identity_gate.py`.

## Bump

```
python tools/cutlist.py bump cutlist_v3.txt cutlist_v4.txt --replace 'short 1.00 0.0 1.0 yes=short 1.00 0.0 1.2 yes' \
                                                           --previous-film out/Acme_Film_v3.mp4
```

Every `--replace 'old=new'` is applied row by row; comments and blank lines ride through; the new list must still
parse. `out/cutlist_bump.json` records `from`, `to`, the replacements, the rows changed, the **changed clips** (a
renamed clip counts under both names) and the previous film. Then `resolve` / `emit` the new list and render.

## Identity

`gates/identity_gate.py` (every untouched shot, from `out/timeline.json` spans):

| Gate | Asserts | Threshold |
|---|---|---|
| `identity frames` | the previous and the current render carry the same number of frames inside the shot (10 fps sampling) and the two files the same frame count | exact |
| `identity colour` | per sampled frame, the mean colour of the two renders (sRGB mean → CIE Lab, ΔE76) | ≤ **0.5 ΔE** — codec noise on a 1080p frame sits near 0.1; a changed element moves it past 1 |

Changed shots are reported, not judged — that is what the bump was for. The previous render comes from
`out/cutlist_bump.json` or `qa.json "identity": {"previous": "out/v3.mp4", "changed": ["send"]}`; without one the
gate passes with a note. A mean colour is blind to an element that merely moves within the frame — that is the
job of `pair anchors` and `motion traced`; this gate answers a different question: did a shot I did not touch
render as the same picture at every frame.

Standalone: `python gates/identity_gate.py <project> out/v3.mp4 [out/v4.mp4] --changed send`.

Selftest: `python gates/identity_gate.py --selftest` — two synthetic three-shot clips where the middle shot
differs; declared → pass, undeclared → `identity colour` fails on that shot; a shorter render fails
`identity frames`; the bump record is read.
