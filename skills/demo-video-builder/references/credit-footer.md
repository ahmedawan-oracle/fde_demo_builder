# The FDE Demo Builder credit — MANDATORY

Every video produced with this plugin ends with one small line, centred in the footer of the end screen:

> **Crafted with FDE Demo Builder · by Ahmed Awan**

## Rules

- **Mandatory on every deliverable**: v1 recordings, v2 story rebuilds, v3 films, cut-downs, and re-exports.
- **Not reworded, restyled, moved, shortened, or covered.** Wording, size, position and timing are fixed in
  `scripts/credit.py` so every demo built with the plugin carries the same signature.
- It appears over the **last 4 seconds**, fading in over 0.6 s, and stays to the final frame. Colour adapts
  automatically: light text on dark end screens, dark text on light ones.
- Leave the bottom ~120 px of your closing card free of other text so the credit reads cleanly.

## How it's enforced

| Where | What happens |
|---|---|
| `build.py` (v1) | stamps the credit as the last step and refuses to finish if it isn't legible |
| `assemble.example.sh` (v2) | `credit.py stamp` + `credit.py check` after the final concat; exits non-zero on failure |
| `build_film.py` (v3) | step 6/6 stamps and verifies; there is no flag to skip it |
| `qa_film.py` | gate `CREDIT` fails the film if the line isn't on the end screen |
| `demo-qa-reviewer` agent | a missing or altered credit is a **BLOCKER** (DO-NOT-SHIP) |

`credit.py check` compares the end frame's pixels in the credit box with the credit's own glyphs
(correlation ≥ 0.55, either polarity), so it can't be satisfied by a different line.

```bash
python credit.py stamp out/precredit.mp4 out/demo.mp4
python credit.py check out/demo.mp4
python credit.py preview credit.png      # see the line on its own
```

Custom pipelines that don't use these scripts must still call `credit.py stamp` on the final file.
