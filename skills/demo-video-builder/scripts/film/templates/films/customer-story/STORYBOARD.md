---
title: <The customer's line — four to six words>
version: 1                      # == number of "## Changes from" blocks + 1 (tools/storyboard.py check)
name: film                      # film.json "name" / vo_script SCENES key → vo/film_phases.json is the clock
format: 1920x1080
duration: 120s                  # customer story: 90–150 s; the beats below must sum to it (± 10 %)
message: "<what changed for the team, in one sentence they would say themselves>"
audience: <the customer's peers — the people who recognise the Monday>
arc: Story — the customer → the situation → the turn → the work → the question → the answer → what changed → the team today → close
mood: calm, warm, exact
music: bed                      # the bed breathes −3 dB at every cut; no swell, no riser in a story
captions: yes                   # ink lane on the paper ground; the hero question in karaoke
template: customer-story        # templates/films/customer-story — grammar, seams, caption style and skin pre-wired
---

<!-- Customer-story skeleton (templates/films/customer-story). Everything is FICTIONAL (Acme, synthetic data).
     Replace every <…> and keep the shape. Nine beats; real beats 12–20 s on the original full screen, then one slow push.
     Heading = "## Beat NN — Name (t0–t1, ~dur s)" in absolute seconds; the sum is checked against duration.
     Quote EVERY word that renders on screen. Figures: "— figure —" until claims.json supplies the number. -->

## Video direction
- palette: the skin (skins/paper.json): warm paper ground, serif display, one oxblood accent per beat, ink captions; `python tools/skin_apply.py skins/paper.json`
- light ground: the head fade opens from the paper (the skin's black token = paper), never from a dark flash
- motion profile: calm — entries 0.6 s power4.out, exits 0.45 s sine.in, stagger 0.08 s per item (≤ 0.5 s), push 1.4 s landing ×1.3–1.6, hold ≥ 2.5 s, no rack focus
- real footage is sacred: every product beat opens on the ORIGINAL full screen (~1 s) then zooms; masks are small soft blurs; nothing recolours product pixels
- seam rule: leftward current; the one reserved z−1 arrival is the entry into the "team today" beat; no shader seams in a story
- comparisons: both halves of a wipe or split are real stills, pixel-exact; charts show only claims.json values; nothing derived
- keep-out: nothing authored below 83 % of the height except the caption lane and the mandatory credit
- never invent figures: every spoken number is a claim in claims.json and is visible on screen when it is spoken

## Decisions
- spine (hero prop): the question "<the question the team asks every week, word for word>" — spoken in 05, typed in 05, answered in 06
- callback: 01 plants "<the day of the week>"; 09 returns it
- breather: 09 — the closing card is the one deliberately still read
- tokens: skins/paper.json (design.md tokens are rewritten from it by tools/skin_apply.py)
- truthfulness line: "<Acme> is fictional, and so is its data." — spoken in 01 and shown as the title-card caption

## Still open
- <does the lower third on 04 need the person's role, or is the first-person voice enough?>

## Locked
- the nine-beat story shape, the calm profile, no shader seams

## Beat 01 — Open on the customer (0.0–9.0, ~9.0 s)
- phase: open
- act: THE CUSTOMER
- real: recreated
- voice: narrator
- vo: "<who they are and the Monday they recognise>. <Acme> is fictional, and so is its data."
- screen: title card on the paper ground: "<The customer's line>" then a short accent rule; caption "Fictional company · synthetic data"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- hero_prop: —
- motion: TYPO.centerBuild BUILDS the line 0.6 s power4.out landing on wt(open, "<first stressed word>"); the rule DRAWS 0.5 s; caption FADES in 0.4 s on "fictional"
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static (recreated layer)
- seam: cut → 02, leftward (cut-the-curve)
- caption: "Fictional company · synthetic data"
- constraint: no logo unless the skin's logo slot is set; no third line; nothing else moves
- why: the viewer meets a person before a product
- type: hook
- persuasion: recognition
- beat: tension

## Beat 02 — The situation (9.0–22.0, ~13.0 s)
- phase: before
- act: THE CUSTOMER
- real: recorded
- clip: before
- voice: analyst
- vo: "<first person: how the question was answered before — the day it cost>"
- screen: the whole screen of the old way (a notebook, a spreadsheet, a ticket queue), then the stitched page scrolls; the output row is boxed
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- camera: establish full screen 1.0 s hold → scroll 1.2 s → push ×1.35 onto the output 1.4 s sine-out → hold ≥ 2.5 s
- push: [<x>, <y>, <w>, <h>]
- seam: cut → 03 on "<first word of the turn>", leftward
- caption: lower third "<ROLE> — <one line>"
- constraint: no repainted code; no masked output; no cut before the full screen has been seen
- why: evidence of the cost, on real pixels
- type: value
- persuasion: demonstration
- beat: recognition

## Beat 03 — The turn (22.0–30.0, ~8.0 s)
- phase: turn
- act: THE TURN
- real: recreated
- voice: narrator
- vo: "<the decision the team made, in one sentence>"
- screen: one line on the paper: "<the turn, four words>"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: TYPO.swap SWAPS "<old word>" for "<new word>" 0.6 s power4.out on wt(turn, "<new word>"); then HOLDS
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: cut → 04 on the first word of the work phase, leftward
- caption: none (the line is on screen)
- constraint: one swap; no second device
- why: the hinge of the story stated plainly
- type: value
- persuasion: contrast
- beat: anticipation

## Beat 04 — The work, where it lives (30.0–50.0, ~20.0 s)
- phase: work
- act: THE WORK
- chapter: The work, where it lives
- real: recorded
- clip: work
- voice: analyst
- vo: "<first person: what the pipeline / notebook / model does, in the order the screen shows it>"
- screen: the whole screen; STAGE frame (window bezel on a mesh wallpaper) when the recording is a bare browser; scrolls to each part on its spoken word
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- camera: establish full screen 1.0 s hold → scroll 1.2 s on "<part two word>" → scroll 1.2 s on "<part three word>" → push ×1.3 onto the result 1.4 s → hold ≥ 2.5 s
- push: [<x>, <y>, <w>, <h>]
- seam: cut → 05 on "<first word of the question>", leftward
- caption: lower third "<ROLE> — Build it where the data is."
- constraint: no repainted code; identifiers masked with small soft blurs only
- why: the day of work the question used to cost, shown as it is
- type: evidence
- persuasion: demonstration
- beat: recognition

## Beat 05 — The question anyone can ask (50.0–68.0, ~18.0 s)
- phase: ask
- act: THE QUESTION
- chapter: The question anyone can ask
- real: recorded
- clip: q
- voice: lead
- vo: "<the hero question, exactly as typed on screen>"
- verbatim: yes
- screen: the composer full screen; the typed line uncovered word by word as it is spoken
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- hero_prop: "<the hero question>"
- camera: establish full screen 1.0 s → push ×1.3 onto the composer 1.4 s sine-out → hold ≥ 2.5 s
- push: [<x>, <y>, <w>, <h>]
- seam: hand-off (seamless) → 06 real send frames
- caption: karaoke — the spoken word lights up on the hero question
- constraint: no synthetic typing cursor; no paraphrase — the spoken words are the typed words
- why: the hero prop — the same question, asked where the work is
- type: evidence
- persuasion: demonstration
- beat: anticipation

## Beat 06 — The answer, traced (68.0–86.0, ~18.0 s)
- phase: answer
- act: THE QUESTION
- real: recorded
- clip: send
- voice: assistant
- vo: "<the answer in the product's own words, with the figure the change beat repeats>"
- screen: the real send frames play; pull back to the whole screen; push ×1.5 onto the spoken figure; ANNOTATE.underline on that figure only
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- hero_prop: "<the hero question>"
- callback: 05
- camera: play at the hand-off → pull to full 1.4 s sine-in-out → push ×1.5 on wt(answer, "<figure word>") 1.4 s → hold ≥ 2.5 s
- push: [<x>, <y>, <w>, <h>]
- seam: cut → 07 on "<first word of the change>", leftward
- caption: rail (ink)
- constraint: the mark sits on a claim figure, never across product text; no invented figure
- why: the proof that the question now takes a minute on data the team already trusts
- type: proof
- persuasion: demonstration + trust
- beat: relief

## Beat 07 — What changed (86.0–95.0, ~9.0 s)
- phase: change
- act: WHAT CHANGED
- chapter: What changed
- real: recreated
- voice: narrator
- vo: "<before and after, two figures, one sentence>"
- screen: COMPARE.wipe of two real stills "Before" / "After"; two tiles "— figure —" / "— figure —" with their labels under them
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: COMPARE.wipe WIPES left to right 0.9 s sine-in-out on wt(change, "<after word>"); BL2.countUp COUNTS both tiles and LANDS each on its spoken figure with the 1.07 pulse
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: inverse zoom-through (z−1, the one reserved arrival) → 08 on the first word of the today phase
- caption: none (the figures are the caption)
- constraint: both halves real and pixel-exact; both figures are claims; no third tile
- why: the change made visible without a single invented number
- type: proof
- persuasion: evidence
- beat: resolve

## Beat 08 — The team today (95.0–112.0, ~17.0 s)
- phase: today
- act: TODAY
- real: recorded
- clip: today
- voice: analyst
- vo: "<first person: what Monday looks like now>"
- screen: the whole screen of the new routine (the morning review, the shared answer); one slow push onto the thing the team reads first
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- camera: establish full screen 1.0 s hold → push ×1.3 onto the first read 1.4 s sine-out → hold ≥ 2.5 s → pull to full 1.4 s before the cut
- push: [<x>, <y>, <w>, <h>]
- seam: cut → 09 on "<first word of the close>", leftward
- caption: lower third "<ROLE> — <one line>"
- constraint: no cut before the full screen has been seen; no highlight that is not on the product's own pixels
- why: the story ends in the customer's own routine, not in a slogan
- type: evidence
- persuasion: demonstration
- beat: relief

## Beat 09 — Close (112.0–120.0, ~8.0 s)
- phase: close
- act: CLOSE
- real: recreated
- voice: narrator
- vo: "<the message as a line the team would say>"
- screen: closing card, two lines: "<line one>" / "<line two>"; then nothing moves while the credit lands
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- callback: 01
- breather: yes
- motion: each line RISES 12 px 0.6 s power4.out on its own spoken word; TYPO.lockup DRAWS the rule 0.5 s; then the card HOLDS
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: end — the mandatory credit is stamped by build_film.py in the footer
- caption: none
- constraint: bottom 120 px free for the credit; no scale creep; no glow
- why: the still read where the credit lands
- type: close
- persuasion: antithesis
- beat: resolve
