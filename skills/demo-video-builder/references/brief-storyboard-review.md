# Brief, storyboard, review loop (v4 creative layer)

The plan layer between the shot log (pixels) and `vo_script.py` (the clock): a durable intake brief, a beat list
the arithmetic can check, a script-free review sheet, and the text/design economics gate. Fictional examples
only ("Acme"). Files: `templates/BRIEF.example.md`, `templates/STORYBOARD.example.md`, `templates/design.example.md`,
`tools/brief.py`, `tools/storyboard.py`, `gates/text_gate.py`.

## 1. The review loop — fidelity one pass at a time

| Pass | Artifact | The one question | Cost of a change |
|---|---|---|---|
| Brief | `BRIEF.md` | the gaps, one field per message, recommended option first with its receipt | seconds |
| Plan | `STORYBOARD.md` + chat echo "This film tells [audience] that [message]" + frame table (NN · beat · on screen · why) | approve or change? sketches first, or straight to build? | 30 s |
| Sketch | `out/storyboard.html` (`tools/storyboard.py sheet`) | does the sheet look right, or which cells change? | a minute |
| Build | render on the confirmed layouts — dress, never redraw | — | minutes |
| Final look | `qa_film.py` + `storyboard.py sheet --truth` (frames from the real film, durations from the clock) | ship, or what changes? | a render |

Feedback is recorded verbatim under `## Changes from vN`, open items under `## Still open`, settled items under
`## Locked`; the version in the frontmatter equals the number of change blocks + 1 and `check` enforces it.
Revise only the cells named. Build only after the lock (`check` fails without `## Locked`; `--autonomous` waives
it for a drive-it run, which still posts the same decisions and the sheet). A confirmed sheet is a valid stopping
point when someone only wanted a storyboard to pitch. Render stays user-gated in both run shapes.

Iteration discipline: one variable per edit; absolute targets ("push lands 0.4 s before the word", never "a bit
late"); a freeze clause for what already works; strip then re-layer a misfiring scene; the gates verify structure,
not quality — the loop ends at the render, not at the gate. Fire independent generations (TTS, stills) in the
background and batch visual checks at pass boundaries: one sheet beats N single-frame views.

## 2. The brief (`BRIEF.md`, `tools/brief.py`)

Frontmatter, one key per confirmed field: `name, message, audience, destination, aspect, length_s, angle,
narration (verbatim|restructured), voices, honesty_line, review (with-me|drive-it), storyboard (yes|no),
placeholders (yes|no), credit` (verbatim "Crafted with FDE Demo Builder · by Ahmed Awan"). Sections: Intent,
**Stated** (what the requester said, where), **Inferred** (defaults with receipts — corrections live here),
Must-haves, Deferred asks, Assets, Bans, Notes (with the one integration check).

Protocol: ask only what the request did not answer — inference is not an answer; one field per message; the
recommended option first with its receipt; the two run-shape questions (storyboard? review with me or drive it?)
last and separately; one integration check for a consequence no single answer showed; a hand-off that shows
stated and inferred as two groups; a revision to the summary is not a confirmation. A "just build it" signal sets
`review: drive-it, storyboard: no` and the run still posts decisions with reasons and a sheet.

`brief.py BRIEF.md` validates (message ≤ 25 words, one sentence, outcome language — no identifiers, table or API
names, no "Welcome to / Introducing", no banned claim; aspect follows destination; the credit verbatim) and prints
the gaps as questions. `--summary` prints the two groups. `--seed-qa --write` adds `honesty_line` to
`required_phrases`, `## Bans` + the cliché list to `banned_phrases`, and the `brief/design/storyboard/
hook_banned_tokens` keys. `--seed-claims --write` starts `claims.json` with the honesty line.

## 3. Pitch round — five tellings for an unformed ask

When the facts are formed but the telling is not ("make a video about this recording"), diverge once before the
brief. Internally answer four questions specifically: what the subject's own visual world looks like; what the
target emotion looks like as a frame (longing = empty space, urgency = compression, awe = one element too large
for the canvas); what the playback surface demands (a booth is glanced at from 2–4 m, a feed fights for its first
second); what every other video on this subject looks like (the anti-pattern). Then five concepts, one per path,
at least two unlikely ones, and a silhouette check (two concepts with the same bounding-box layout are one):

| Path | Acme example |
|---|---|
| the subject's world | *the ops lead's Monday* — one person, one question, one clock on the wall |
| the emotion | *the quiet minute* — the day of waiting compressed into one held frame |
| the audience, met or broken | *one question, two answers* — the notebook and the chat, side by side, same number |
| the anti-pattern inverted | *the audit trail* — start from the answer and walk back to the data (no feature tour) |
| an unusual format | *a front page from next quarter* — the result as a headline, the demo as the story under it |

Present all five as three lines each (concept · visual world · opening hook) before recommending one; mixing is
a first-class answer; one round only. The pick lands under `## Intent`, the two rejected ones under `## Notes`.

## 4. Value-first spine (checked by `storyboard.py check`)

1. The hook speaks outcome language — what the viewer gains or stops losing. Table, function, API and feature
   names are banned from the first two beats (`qa.json hook_banned_tokens`; a verbatim voiced question is exempt).
   Numbers only when they carry stakes ("a day → a minute"), never inventory ("23 files"). "Welcome to /
   Introducing" restarts the plan.
2. The value claim lands by beat 2 (`type: value`); everything after is evidence. Two delete-tests on the beat
   list: delete every evidence beat — the value must still be stated; delete the value beats — if the film still
   works, it was a feature tour.
3. The storyboard is a proposal: echo line, frame table with a `why:` traced to the message (an untraceable beat
   is cut, not decorated), receipts on the arc and the beat count, "approve or adjust".
4. Props point back to the source: the recording's own phrases, numbers and motifs. A prop that could appear
   unchanged in another product's film did not come from the source. Arcs to pick one from: PAS, Before/After/
   Bridge, Future Pacing, Feature-Benefit Cascade, and the default for product films, **Demo Loop** (question →
   intro → demo cycle → answer → trust → close), where the product's own caveat is the trust beat.

## 5. The storyboard (`STORYBOARD.md`, `tools/storyboard.py`)

Frontmatter: `title, version, name, format, duration, message, audience, arc, mood, music, captions`. Then the
decisions written once: `## Video direction` (every beat inherits it), `## Decisions` (spine / hero prop, callback
pair, the one breather, tokens file, truthfulness line), `## Changes from vN`, `## Still open`, `## Locked`.

One beat per idea: `## Beat NN — Name (t0–t1, ~dur s)` in absolute seconds, then bullets —
`phase` (vo_script phase), `real: recorded|recreated|placeholder`, `clip` (recorded), `voice`, `vo` (verbatim, or
`silent`), `verbatim: yes` (the typed question), `screen` with **every rendered word in quotes**, `hero_prop`,
`callback: NN`, `motion` (VERB + ease + duration — SLAMS / SLIDES / DRAWS / COUNTS / TYPES / RISES / HOLDS …; an
element without a verb is not designed), `camera` (establish → push → hold), `push: [x, y, w, h]` (source px, drawn
on the sheet), `act`, `seam` (one direction rule for the whole film), `caption`, `constraint` (one explicit "no …"),
`why`, `type`, `persuasion`, `beat`, `breather: yes` (exactly one), `sketch:` (an image for the sheet).

`check` fails on: broken arithmetic (gaps, sums ≠ duration ± 10 %, > 10 % drift against
`vo/<name>_phases.json`), a phase without a beat or a beat without a phase, missing `why/constraint/screen/seam/vo`,
a recreated beat without a verb, a recorded beat without a clip in `clips.json`, a placeholder at `--build` (unless
the brief allows it), a dangling or forward callback, zero or two breathers, a hero prop quoted differently, hook
vocabulary, a version/lock mismatch, and > 3.4 words/s in any beat. It warns on pace outside 1.8–3.0 w/s, > 24
words, recreated beats outside 1.5–9 s, product beats outside 4–20 s, more than 4 on-screen strings at once, a
string > 9 words or a narration sentence on screen, lazy verbs (FLOATS/DRIFTS/BREATHES), and TTS spelling
(digits, %, $, 10x, 135+, acronyms, domains — the voice rounds, the screen keeps the exact figure):

| Written | Say |
|---|---|
| 135+ | more than one hundred thirty five |
| $1.9T | nearly two trillion dollars |
| 99.999 % | ninety nine point nine percent |
| 10x | ten times |
| API / acme.com | A P I / acme dot com |

`sheet` writes the review page: header (title, version, dek = message, format · planned/actual length · beats ·
arc, the Changes / Still open / Locked notes), a three-column grid of 16:9 cells (`id="frame-NN"`, sizes in cqw so it
scales like the build) grouped under act bars, each cell drawing the beat's quoted words in the design tokens
(fit-to-measure: ≤ 3 words h1, 4–6 h2, 7+ h3), a REAL / RECREATED / PLACEHOLDER badge, the 83 % keep-out guide,
the establish → push frame for recorded beats, the label row `NN · NAME` / `phase · t0–t1`, a bold lead on what
moves first, seam and caption chips; two closing cells (seam map, tokens). No scripts, no external assets; opens
from `file://`. `--truth` pulls a frame per beat midpoint from the finished film and re-reads durations from the
clock. The sheet is generated, never hand-edited — it is not a second source of timing truth.

## 6. Direction block, design spec and the text gate

**Two-colour discipline** for recreated layers: one ground + one ink; emphasis by inversion, scale or density,
never a third hue; the brand accent only on the single focal element (15–25 % as atmosphere, never under 10 %).
**Reveal model**: at t = 0 only what the narrator is saying is on screen; each further piece lands on its spoken
word, spread over the back ~50 % of the beat, never front-loaded in the first ~25 % (the slideshow). **Holds**: a
held read beats bad motion; no breathing loops, glow drift or back-half pushes (the screensaver); subtle jitter is
the only sanctioned aliveness; exactly one breather per film. **Keep-out**: nothing authored in the bottom 17 %
except the credit. **Type** (1280×720 stage, ×1.5 at 1080p): headlines ≥ 40, body ≥ 14, labels ≥ 11 stage px;
in-feed ×1.5 again; display tracking −0.03…−0.05 em; light-on-dark body weight 350, line-height +0.05–0.1;
tabular-nums where digits stack; a 5–7-word line gets 2–2.5 s; 3 s on screen must read in 2. **Pace**: ~2.5 words/s
(15 s ≈ 37 words, 30 s ≈ 75, 60 s ≈ 150); 1–2 sentences, 6–20 words per beat; on-screen text is a hero word, a stat,
a one-word emphasis — never a narration sentence (captions already print it). **Numbers**: never invented — render
"— figure —" until the script and the screen supply them.

`design.md` (frontmatter normative: `colors`, `type`, `fonts`, `scale`, `radii`, `borders`, `shadows`, `eases`,
`motion`, `keepout`, `bans`; prose = judgement) fixes the identity once per demo; tokens come from a capture of the
real product, never from memory. `gates/text_gate.py` (five gates, auto-loaded by `qa_film.py`):

| Gate | FAIL | WARN | Skips when |
|---|---|---|---|
| text budget | a rendered string ≥ 8 words that is also spoken verbatim (double-print) | any rendered string > 9 words | — |
| narration pace | any phase > 3.4 w/s | outside 1.8–3.0 w/s; > 24 words | no phases.json / vo_script.py |
| brief message | < 60 % of the message's content words in narration + authored text; honesty line not spoken | — | no BRIEF.md |
| design tokens | a hex/rgb(a) literal off the palette; an undeclared font-family | radii/shadows off spec; type under `scale.justify_below` | no design.md |
| lazy defaults | rows listed in `qa.json css_fail` | gradient ground, gradient text, pure #000/#fff, > 2 left stripes, banned fonts, bouncy eases, clock-driven drift, opacity < 10 %, type < 11 px | — |

Only authored CSS/JS is scanned — product footage keeps its own palette and is never graded here.

## 7. Worked example (fictional)

`templates/` carries one coherent Acme set: a brief whose message is "A question that took a day now takes a
minute, on data the team already trusts", a six-beat Demo-Loop storyboard (hook → thesis + honesty → notebook →
the question typed → the answer → close; hero prop = the typed question, callback 01 → 06, breather 06, planned
35 s) and the two-colour design spec. `python tools/storyboard.py --selftest`, `python tools/brief.py --selftest`
and `python gates/text_gate.py --selftest` exercise all of it on synthetic clocks — no render.
