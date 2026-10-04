---
title: <Hero line — three words or fewer>
version: 1                      # == number of "## Changes from" blocks + 1 (tools/storyboard.py check)
name: film                      # film.json "name" / vo_script SCENES key → vo/film_phases.json is the clock
format: 1920x1080
duration: 36s                   # booth trailer: 30–45 s; the beats below must sum to it (± 10 %)
message: "<one sentence the viewer should be able to repeat after 36 seconds>"
audience: people walking past a screen with the sound off, then on
arc: Trailer — pain in one line → title → the product, full screen → the answer lands → the proof figure → close
mood: energetic, exact, one accent
music: bed                      # film.json "bed" — the bed breathes −3 dB at every cut and swells under the riser
captions: yes                   # keynote lane; the hero question in karaoke; nothing authored below 83 % of the height
template: booth-trailer         # templates/films/booth-trailer — grammar, seams, caption style and skin pre-wired
---

<!-- Booth-trailer skeleton (templates/films/booth-trailer). Everything is FICTIONAL (Acme, synthetic data).
     Replace every <…> and keep the shape: the fields are the template's grammar, the words are yours.
     Heading = "## Beat NN — Name (t0–t1, ~dur s)" in absolute seconds; the sum is checked against duration.
     Quote EVERY word that renders on screen. Figures: "— figure —" until claims.json supplies the number. -->

## Video direction
- palette: the skin (skins/ember.json): warm near-black ground, one ember accent per beat, keynote captions; `python tools/skin_apply.py skins/ember.json`
- motion profile: high — entries 0.25 s expo.out, exits 0.20 s power3.in, stagger 0.04 s per item (≤ 0.4 s), push 0.9 s landing ×1.5–2.0, hold ≥ 1.5 s
- scarcity: one `gl` accent seam (into the proof card), one slam, one hero element per beat, bloom on the proof card only
- real footage is sacred: every product beat opens on the ORIGINAL full screen (~1 s) then zooms; masks are small soft blurs; nothing recolours product pixels
- seam rule: leftward current (exits travel left, entries arrive from the right); the one reserved z+1 push is the entry into the product
- keep-out: nothing authored below 83 % of the height except the caption lane and the mandatory credit
- never invent figures: every spoken number is a claim in claims.json and is visible on screen when it is spoken

## Decisions
- spine (hero prop): the question "<the question the product answers, word for word>" — spoken in 03, typed in 03, answered in 04
- callback: 01 plants "<the pain word>"; 06 returns it in the lockup
- breather: 06 — the lockup is the one deliberately still read
- tokens: skins/ember.json (design.md tokens are rewritten from it by tools/skin_apply.py)
- truthfulness line: "<Acme> is fictional, and so is its data." — spoken in 02 and shown as the title-card caption

## Still open
- <the first thing the author still has to decide>

## Locked
- the six-beat trailer shape and the single gl accent into the proof card

## Beat 01 — Cold open (0.0–5.0, ~5.0 s)
- phase: hook
- act: OPEN
- real: recreated
- voice: narrator
- vo: "<the pain in outcome language, one sentence with one figure in it>"
- screen: "<hero line>" built word by word on the dark ground; the figure "— figure —" counts up and lands on its spoken word
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- hero_prop: —
- motion: TYPO.centerBuild BUILDS the line word by word 0.25 s per word expo.out, first motion at 0.15 s; BL2.countUp LANDS on wt(hook, "<figure word>") with the 1.07 pulse; nothing else moves
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static (recreated layer)
- seam: cut → 02, leftward (cut-the-curve)
- caption: none (the words are already on screen)
- constraint: one accent element (the figure); no glow drift; no second line before the figure lands
- why: a passer-by decides in four seconds — the pain and its cost, nothing about the product yet
- type: hook
- persuasion: contrast (the cost of the question)
- beat: tension

## Beat 02 — Title + honesty (5.0–9.0, ~4.0 s)
- phase: title
- act: OPEN
- real: recreated
- voice: narrator
- vo: "<Acme> is fictional, and so is its data. <one clause on what the film shows>."
- screen: title "<Hero line>" as a shard title; caption "Fictional company · synthetic data"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: T3D.shardTitle FLIES the panes in from depth 0.6 s expo.out, SETTLES, HOLDS 2 s; caption FADES in 0.2 s on "fictional"
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: zoom-through (z+1, the one reserved push of the act) → 03 on the first word of the product phase
- caption: "Fictional company · synthetic data"
- constraint: one title device only (shard OR lockup, never both); no logo unless the skin's logo slot is set
- why: says what is real before the product appears; the only 3D moment in the film
- type: value
- persuasion: honesty as credibility
- beat: trust

## Beat 03 — The product, full screen (9.0–17.0, ~8.0 s)
- phase: demo
- act: DEMO
- real: recorded
- clip: demo
- voice: lead
- vo: "<the hero question, exactly as typed on screen>"
- verbatim: yes
- screen: the ORIGINAL full product screen; the composer; the question typed word for word as it is spoken
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- hero_prop: "<the hero question>"
- camera: establish full screen 1.0 s hold → push ×1.5 onto the composer 0.9 s sine-out → hold ≥ 1.5 s; redrawn cursor from events.jsonl if telemetry exists
- push: [<x>, <y>, <w>, <h>]                 # screen px of the pushed-onto rect
- seam: cut → 04 on "<first word of the answer phase>", leftward
- caption: karaoke — the spoken word lights up on the hero question
- constraint: no synthetic typing cursor; no paraphrase; no cut before the full screen has been seen; identifiers masked with small soft blurs only
- why: the promise made concrete — the question asked where the work is
- type: evidence
- persuasion: demonstration
- beat: anticipation

## Beat 04 — The answer lands (17.0–25.0, ~8.0 s)
- phase: answer
- act: DEMO
- real: recorded
- clip: answer
- voice: assistant
- vo: "<the answer in the product's own words, with the figure the proof will repeat>"
- screen: the real answer frames play; pull back to the whole screen; punch ×1.6 onto the spoken figure; ANNOTATE.circle on that figure only
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence>
- hero_prop: "<the hero question>"
- callback: 03
- camera: play at the hand-off → pull to full 1.0 s sine-in-out → punch ×1.6 on wt(answer, "<figure word>") 0.9 s → hold ≥ 1.5 s
- push: [<x>, <y>, <w>, <h>]
- seam: gl flashWhite 0.3 s, cause impact → 05 (the one accent seam of the film)
- caption: rail (keynote)
- constraint: the circle sits on a claim figure, never across product text; no invented figure in the answer
- why: proof on real pixels — the answer the whole team can trust
- type: proof
- persuasion: demonstration + trust
- beat: relief

## Beat 05 — The proof figure (25.0–31.0, ~6.0 s)
- phase: proof
- act: PROOF
- real: recreated
- voice: narrator
- vo: "<the outcome sentence with the one figure>"
- screen: a single card: "— figure —" large, one label under it "<what the figure is>"
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- motion: BL2.countUp COUNTS to the claim and LANDS on wt(proof, "<figure word>") with the 1.07 pulse; LIGHT.bloom BLOOMS on the card 0.4 s sine-out; DEPTH.planes HOLD two planes behind it; the riser ENDS on the landing
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: cut → 06 on "<first word of the close>", leftward
- caption: none (the figure is the caption)
- constraint: bloom on this card only; one figure; the figure is a claim in claims.json
- why: the one number a passer-by takes away
- type: proof
- persuasion: evidence
- beat: resolve

## Beat 06 — Close (31.0–36.0, ~5.0 s)
- phase: close
- act: CLOSE
- real: recreated
- voice: narrator
- vo: "<the message as a line the audience can repeat>"
- screen: lockup "<Hero line>" with its rule; then nothing moves while the credit lands
- start: <what is on screen on the first frame — one sentence>
- end: <the last frame the next cut lands on — one sentence; mandatory on a recreated beat>
- callback: 01
- breather: yes
- motion: TYPO.lockup DRAWS the rule 0.5 s on wt(close, "<first word>"); REVEAL.pullBack PULLS the card to rest 0.8 s sine-in-out; then HOLDS — nothing moves while the credit lands
- hold: 0.6 (the last 40 % holds; only a declared background may move — or "none (reason)")
- camera: static
- seam: end — the mandatory credit is stamped by build_film.py in the footer
- caption: kinetic — the closing line waterfalls in, leaves as a block
- constraint: bottom 120 px free for the credit; no scale creep; no glow
- why: the callback closes the loop; the still read is where the credit lands
- type: close
- persuasion: antithesis
- beat: resolve
