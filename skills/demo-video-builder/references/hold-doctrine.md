# Hold doctrine — move first, then hold (v5.1)

Two kinds of shot want two kinds of ending. A footage match-cut carries motion through the cut: the eye's momentum
survives because both sides are moving in the ledger's direction (`motion-doctrine.md` Part 1, `seam_gate`). A
recreated or explainer beat does the opposite: everything it has to say moves early, then the composition **holds**
— only a declared background may drift — so the end frame is a still the next cut can land on, a reviewer can
approve (`frame-pairs-and-approvals.md`) and an editor can trim without losing the state. The cut still lands on a
word; what changes is which side owes the motion. Code: `gates/hold_gate.py`; declared in `scenes/shots.js`.

## The rule

| Shot type | `hold:` | Why |
|---|---|---|
| recreated / explainer beat (title, hook card, close, any card segment) | **required** — `0.3`–`0.95`, house default `0.6` | the end state is the point of the beat; it must exist as a still |
| footage shot that ends on a settled state (the answer card, a dashboard that has finished loading) | optional | the recording owns its own causality; declare the hold if you want the gate to protect it |
| footage match-cut (a ledger `cut` row with vectors, or a `match-cut` / `morph` row at the shot's end) | **forbidden** | motion must carry through that cut; a hold there is a dead beat |

A recreated beat that truly cannot hold — every element lands on its spoken word up to the cut — writes the waiver
in the storyboard: `- hold: none (reason)`. The gate prints the reason as a WARN instead of failing. A waiver with no
reason is still a warning in `storyboard.py check`; a missing line is a FAIL at QA.

## Declaring it

```js
// shots.js — a footage shot that ends held
{ t0: ANSWER_AT, t1: P.close, clip: 'answer', hold: 0.6, holdBg: 1.0 }

// the recreated segments (FILM.holds): id, span, fraction, optional background allowance (% change per 0.1 s)
root.FILM.holds = [ { id: 'close', t0: P.close, t1: T.total + 3.6, hold: 0.55, bg: 1.0 } ];
```

`export_timeline.js` writes both into `out/timeline.json → holds[]` (and `shots[].hold`). The storyboard carries
the same number per beat (`- hold: 0.6`) so the plan and the scene say one thing; `storyboard.py check` reads it.

`hold` is a fraction of the segment: with `hold: 0.6` the first 60 % may move, the last 40 % may not. The measured
window is `[t0 + hold·(t1−t0), t1 − 0.15 s]` (the cut pad keeps the seam's own exit out of the test).

## What the gate measures

`gates/hold_gate.py` (in the `picture` profile):

| Gate | Checks | Threshold |
|---|---|---|
| `hold declared` | `0.3 ≤ hold ≤ 0.95`; every recreated beat covered by a hold row (or waived in writing); no hold on a footage shot whose end is a vector or match-cut seam row; gl rows allowed | coverage ≥ 50 % of the beat |
| `hold still` | the film at 10 fps, 320x180 grey: mean absolute frame difference per 0.1 s inside the hold window | ≤ `bg` (default 1.0 % of full scale; per row `bg:`; `qa.json hold.bg`) — a slow drift, a breathing lamp or a flake field sit well under it; a word landing or a card sliding sits well over. WARN when nothing moved before the hold (max < 0.3 %: a slide) |

`seam_gate` reads the same rows and skips `seams move` for a ledger row whose cut ends a held segment — the hold
wins; the row is still validated and still guarded against flashes.

## Writing to the rule

- Put every landing in the first 60 %: the headline, the figure, the rule, the sub. The words that carry them are
  usually there anyway; when the narration's last word is the beat's last landing, shorten the beat's motion, not
  the hold — or waive and say so.
- Declare the background. A lamp that breathes at 0.2 % per 0.1 s is background; raise `bg` only with a reason you
  can measure (`hold still` prints the max it saw).
- The hold is where the reviewer's END frame lives. If `hold still` fails, the approved END frame is not what the
  film shows for the last 40 % of the beat — fix the motion, not the approval.

Selftest (no browser): `python gates/hold_gate.py --selftest` — a synthetic card that moves for 60 % over a drifting
background passes; one that keeps sliding into its hold fails at the time and value; the plan rules (coverage,
waiver, forbidden on a vector seam, allowed on a gl row, range) are exercised on a tiny ledger and storyboard.
