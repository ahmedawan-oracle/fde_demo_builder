---
title: <Feature set name — two to four words>
version: 1                      # == number of "## Changes from" blocks + 1 (tools/storyboard.py check)
name: film                      # film.json "name" / vo_script SCENES key → vo/film_phases.json is the clock
format: 1920x1080
duration: 90s                   # feature walkthrough: 60–120 s; the beats below must sum to it (± 10 %)
message: "<the job these features do for the person at the desk, in one sentence>"
audience: <practitioners who will use the feature this week>
arc: Walkthrough — the job → the name → feature one → its result → feature two → its result → feature three → recap → close
mood: technical, medium pace, one accent
music: bed                      # the bed breathes −3 dB at every cut; no riser in a walkthrough
captions: yes                   # broadcast lane; chapter lines kinetic; the hero question karaoke
template: feature-walkthrough   # templates/films/feature-walkthrough — grammar, seams, caption style and skin pre-wired
---

<!-- Feature-walkthrough skeleton (templates/films/feature-walkthrough). Everything is FICTIONAL (Acme, synthetic data).
     Replace every <…> and keep the shape. Each feature beat is a chapter (`- chapter:` ≤ 40 chars) and opens on the
     ORIGINAL full screen, then pushes to where the presenter works. Heading = "## Beat NN — Name (t0–t1, ~dur s)".
     Quote EVERY word that renders on screen. Figures: "— figure —" until claims.json supplies the number. -->

## Video direction
- palette: the skin (skins/meridian-dark.json): charcoal ground, one electric-teal accent per beat, broadcast captions; `python tools/skin_apply.py skins/meridian-dark.json`
- motion profile: medium — entries 0.4 s power4.out, exits 0.3 s power2.in, stagger 0.06 s per item (≤ 0.5 s), push 1.1 s landing ×1.4–1.8, hold ≥ 2 s, rack focus ≤ once per 8 s
- recording-native: redrawn cursor with click rings and the keystroke pill from events.jsonl; idle spans ramped (tools/idle_detect.py), never cut mid-word; camera pushes snap to the nearest spoken word
- real footage is sacred: every feature opens on the ORIGINAL full screen (~1 s) then zooms; masks are small soft blurs; nothing recolours product pixels
- seam rule: leftward current; one reserved z+1 push per act (into each feature's screen); one rack-focus into the recap; no shader seams
- result cards are labelled recreated and land on the real answer's words; one LIGHT.sweep per card, no bloom
- keep-out: nothing authored below 83 % of the height except the caption lane and the mandatory credit
- never invent figures: every spoken number is a claim in claims.json and is visible on screen when it is spoken

## Decisions
- spine (hero prop): the question "<the question feature one answers, word for word>" — spoken in 03, typed in 03, answered in 04
- callback: 01 plants "<the job word>"; 09 returns it
- breather: 09 — the lockup is the one deliberately still read
- tokens: skins/meridian-dark.json (design.md tokens are rewritten from it by tools/skin_apply.py)
- truthfulness line: "<Acme> is fictional, and so is its data." — spoken in 02 and shown as the title-card caption

## Still open
- <feature three: a result card too, or straight into the recap?>

## Locked
- the three-chapter walkthrough shape; one reserved push per act; no shader seams

## Beat 01 — The job (0.0–6.0, ~6.0 s)
- phase: hook
- act: OPEN
- real: recreated
- voice: narrator
- vo: "<the job the features do, in one sentence — no feature name yet>"
- screen: "<the job, four words>" built word by word on the charcoal ground
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- hero_prop: —
- motion: TYPO.centerBuild BUILDS the line 0.4 s per word power4.out, first motion at 0.15 s; then HOLDS
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static (recreated layer)
- seam: cut → 02, leftward (cut-the-curve)
- caption: kinetic — the chapter line waterfalls in, leaves as a block
- constraint: one line; no figure; no glow
- why: the viewer hears what the feature is for before what it is called
- type: hook
- persuasion: relevance
- beat: tension

## Beat 02 — The name (6.0–10.0, ~4.0 s)
- phase: title
- act: OPEN
- real: recreated
- voice: narrator
- vo: "<Acme> is fictional, and so is its data. <the feature set name>, in three features."
- screen: lockup "<Feature set name>" with its rule; caption "Fictional company · synthetic data"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: TYPO.lockup DRAWS the rule 0.5 s power4.out on wt(title, "<name word>"); caption FADES in 0.2 s on "fictional"
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: zoom-through (z+1, the act's reserved push) → 03 on the first word of feature one
- caption: "Fictional company · synthetic data"
- constraint: one title device; no logo unless the skin's logo slot is set
- why: names the thing and says what is real before the product appears
- type: value
- persuasion: honesty as credibility
- beat: trust

## Beat 03 — Feature one (10.0–26.0, ~16.0 s)
- phase: f1
- act: FEATURE ONE
- chapter: <Feature one — ≤ 40 chars>
- real: recorded
- clip: f1
- voice: guide
- vo: "<what the presenter does, in the order the screen shows it; the hero question spoken exactly as typed>"
- verbatim: yes
- screen: the ORIGINAL full screen; push to where the presenter works; redrawn cursor with click rings; the keystroke pill while typing; the typed question uncovered word by word
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- hero_prop: "<the hero question>"
- camera: establish full screen 1.0 s hold → push ×1.5 onto the work area 1.1 s sine-out (from out/camera_auto.json, snapped to the spoken word) → hold ≥ 2 s; idle spans ramped from scenes/idle.js
- push: [<x>, <y>, <w>, <h>]
- seam: cut → 04 on "<first word of the result>", leftward
- caption: karaoke — the spoken word lights up on the hero question
- constraint: no synthetic typing cursor beyond the redrawn pointer; no paraphrase; no cut before the full screen has been seen; identifiers masked with small soft blurs only
- why: the first feature does the job the hook promised
- type: evidence
- persuasion: demonstration
- beat: anticipation

## Beat 04 — Result one (26.0–32.0, ~6.0 s)
- phase: r1
- act: FEATURE ONE
- real: recreated
- voice: narrator
- vo: "<what came back, with the one figure>"
- screen: recreated receipt card "RECREATED" badge; "<the answer's first line>"; "— figure —"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: BL2.receipt STAMPS on wt(r1, "<figure word>") with the 2 % snap; LIGHT.sweep SWEEPS the card once 0.5 s sine-in-out; then HOLDS
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: zoom-through (z+1, the next act's reserved push) → 05 on the first word of feature two
- caption: none (the card is the caption)
- constraint: labelled recreated; lands on the real answer's words; one sweep, no bloom
- why: the result read without the UI's noise
- type: proof
- persuasion: evidence
- beat: relief

## Beat 05 — Feature two (32.0–50.0, ~18.0 s)
- phase: f2
- act: FEATURE TWO
- chapter: <Feature two — ≤ 40 chars>
- real: recorded
- clip: f2
- voice: guide
- vo: "<what the presenter does, in the order the screen shows it>"
- screen: the ORIGINAL full screen; push to the work area; redrawn cursor; a scroll to the second part on its spoken word
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- camera: establish full screen 1.0 s hold → push ×1.4 onto the work area 1.1 s sine-out → scroll 1.1 s on "<part word>" → hold ≥ 2 s
- push: [<x>, <y>, <w>, <h>]
- seam: cut → 06 on "<first word of the result>", leftward
- caption: rail (broadcast)
- constraint: no cut before the full screen has been seen; nothing recoloured; idle ramped, never cut mid-word
- why: the second feature extends the first
- type: evidence
- persuasion: demonstration
- beat: recognition

## Beat 06 — Result two (50.0–56.0, ~6.0 s)
- phase: r2
- act: FEATURE TWO
- real: recreated
- voice: narrator
- vo: "<what changed, with the one figure>"
- screen: card: "— figure —" large, label "<what the figure is>"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: BL2.countUp COUNTS to the claim and LANDS on wt(r2, "<figure word>") with the 1.07 pulse; LIGHT.sweep SWEEPS once 0.5 s sine-in-out; then HOLDS
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: zoom-through (z+1, the next act's reserved push) → 07 on the first word of feature three
- caption: none
- constraint: the figure is a claim; one sweep
- why: one number per feature
- type: proof
- persuasion: evidence
- beat: relief

## Beat 07 — Feature three (56.0–74.0, ~18.0 s)
- phase: f3
- act: FEATURE THREE
- chapter: <Feature three — ≤ 40 chars>
- real: recorded
- clip: f3
- voice: guide
- vo: "<what the presenter does; the answer in the product's own words>"
- screen: the ORIGINAL full screen; push to the work area; ANNOTATE.box on the control the presenter clicks (logged click), then the real answer frames play
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- camera: establish full screen 1.0 s hold → push ×1.5 onto the control 1.1 s sine-out → hold ≥ 2 s → pull to full 1.1 s before the recap
- push: [<x>, <y>, <w>, <h>]
- seam: rack-focus → 08 on "<first word of the recap>"
- caption: rail (broadcast)
- constraint: the box sits on a logged click, never across product text; no cut before the full screen has been seen
- why: the third feature closes the loop the hook opened
- type: evidence
- persuasion: demonstration
- beat: anticipation

## Beat 08 — Recap (74.0–83.0, ~9.0 s)
- phase: recap
- act: RECAP
- real: recreated
- voice: narrator
- vo: "<three features, three short names, one sentence>"
- screen: three scene cards: "<Feature one>" / "<Feature two>" / "<Feature three>", each with its one figure "— figure —"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: BL2.sceneCards CUTS card to card on wt(recap, "<name word>", n) with cut-the-curve 0.33 s expo.out each; the set HOLDS after the third
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: cut → 09 on "<first word of the close>", leftward
- caption: kinetic — the chapter line waterfalls in, leaves as a block
- constraint: three cards, three figures already shown; no new figure here
- why: a viewer who skipped a chapter still leaves with all three
- type: close
- persuasion: summary
- beat: resolve

## Beat 09 — Close (83.0–90.0, ~7.0 s)
- phase: close
- act: CLOSE
- real: recreated
- voice: narrator
- vo: "<the message as a line the practitioner can repeat>"
- screen: lockup "<Feature set name>" with its rule; then nothing moves while the credit lands
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- callback: 01
- breather: yes
- motion: TYPO.lockup DRAWS the rule 0.5 s on wt(close, "<first word>"); REVEAL.pullBack PULLS the card to rest 0.8 s sine-in-out; then HOLDS
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: end — the mandatory credit is stamped by build_film.py in the footer
- caption: none
- constraint: bottom 120 px free for the credit; no scale creep; no glow
- why: the still read where the credit lands
- type: close
- persuasion: antithesis
- beat: resolve
