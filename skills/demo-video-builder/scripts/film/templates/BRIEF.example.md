---
# BRIEF.example.md — the intake brief a /new-film run writes BEFORE any pixel. Copy to <project>/BRIEF.md.
# One key per confirmed field. tools/brief.py validates it, prints the gaps as questions and seeds qa.json / claims.json.
# Everything here is FICTIONAL (Acme, synthetic data).
name: film                              # film.json "name" and the vo_script SCENES key
version: 1
message: "A question that took a day now takes a minute, on data the team already trusts."
audience: "operations leads and the analysts who serve them"
destination: booth                      # booth | session | linkedin | youtube | internal
aspect: 1920x1080                       # derived from destination (booth/session/youtube → 1920x1080; linkedin → 1080x1080 or 1920x1080; vertical → 1080x1920)
length_s: 150                           # target; 6–10 beats at ~2.5 words/s; booth loops run 60–180 s
angle: "one Monday, two people, one question"
narration: restructured                 # verbatim (the recording's own words) | restructured (rewritten around the message)
voices: 4                               # narrator + persona voices + the product's own voice
honesty_line: "Acme is fictional, and so is its data."
review: with-me                         # with-me (plan → sketch → build → final look, ask at each) | drive-it (post decisions, keep going)
storyboard: yes                         # yes → STORYBOARD.md + storyboard.html pass before any render
placeholders: no                        # may a placeholder beat ship? no = tools/storyboard.py check --build fails on one
credit: "Crafted with FDE Demo Builder · by Ahmed Awan"   # mandatory, verbatim — never reworded, moved or covered
---

## Intent
Show an operations lead that the Monday question she waits a day for can be asked where the work is and
answered from the data the analysts already trust. Calm, exact, unhurried — closer to a well-run handover
than a launch. The chosen telling: *one Monday, two people, one question* (rejected: "the agent's night
shift", "the audit trail" — see Notes).

## Stated
<!-- facts the requester gave, one per line: field — value — where it was said -->
- message — "a question that took a day now takes a minute" — the request ("Mondays cost us a day")
- audience — operations leads + their analysts — the request
- destination — booth loop at the event — the request
- honesty_line — Acme is fictional — team policy, restated by the requester
- review — with me — "show me the plan first"

## Inferred
<!-- defaults we chose, each with its receipt; this is where corrections live -->
- aspect 1920x1080 — derived from destination: booth
- length_s 150 — six beats at ~2.5 words/s with product beats of 8–20 s; the sample recording is 16 s of usable screen
- narration restructured — the recording's own narration names tables and functions in the hook (honesty audit)
- voices 4 — narrator, analyst, operations lead, the product's own voice
- storyboard yes — more than two beats
- placeholders no — the capture covers every beat

## Must-haves
- the on-screen question spoken verbatim and typed word for word (hero prop)
- every product beat opens on the original full screen, then zooms
- the truthfulness line spoken once and shown on the title card
- the mandatory credit on the end screen

## Deferred asks
- lower-third copy per persona (after the shot log)
- a music bed (after the first mix; booth may run silent)
- a LinkedIn cut-down (after the booth version ships)

## Assets
- recording.mp4 — the Acme Console capture from make_sample_recording.py; the only source of product pixels
- SHOTLOG.md — parked / scrolling / typing map with the leaks to mask

## Bans
<!-- one per line; tools/brief.py --seed-qa appends them to qa.json banned_phrases -->
- plain English
- generally available
- available now
- instantly
- seamless
- unlock the power

## Notes
- Integration check: a 150 s booth loop with four voices leaves ~2 s between acts — keep the gap at 0.45 s and
  let the lower thirds carry the hand-off, or the film reads as six separate clips.
- Rejected tellings: "the agent's night shift" (no overnight run in the capture), "the audit trail" (the
  capture never shows lineage).
- Render stays gated: the sketch pass is the default stop; build only after "## Locked" in STORYBOARD.md.
