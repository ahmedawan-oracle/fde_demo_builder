---
title: Monday, answered.
version: 1                      # == number of "## Changes from" blocks + 1 (tools/storyboard.py check)
name: film                      # film.json "name" / vo_script SCENES key → vo/film_phases.json is the clock
format: 1920x1080
duration: 32s                   # expectation from BRIEF.md length_s; the beats below must sum to it (± 10 %)
message: "A question that took a day now takes a minute, on data the team already trusts."
audience: operations leads and the analysts who serve them
arc: Demo Loop — question → intro → demo cycle → answer → trust → close
mood: calm, exact, unhurried
music: none
captions: yes                   # bottom 17 % of the canvas is the caption keep-out (y ≤ 598 on the 720 stage)
---

<!-- Everything here is FICTIONAL (Acme, synthetic data). Copy to <project>/STORYBOARD.md.
     One beat per idea. Heading = "## Beat NN — Name (t0–t1, ~dur s)" in absolute seconds; the sum is checked.
     Fields are "- key: value" bullets; unknown keys are kept. Quote EVERY word that renders on screen. -->

## Video direction
- palette: ground "#082A34" + ink "#E9F3F9"; the accent "#E56B5E" touches one focal element per beat and nothing else
- two-colour discipline: emphasis by inversion, scale or density — never a third hue
- reveal model: at t=0 only what the narrator is saying is on screen; every further piece lands on its spoken word; reveals spread over the back ~50 % of a beat, never front-loaded in the first ~25 %
- holds: a held read beats bad motion; no breathing loops, no glow drift, no slow push in the back half; low-amplitude jitter is the only sanctioned aliveness
- seam rule: leftward — exits travel left, entries arrive from the right; hard cut on every screen change
- keep-out: nothing authored below 83 % of the height except the mandatory credit box
- no slideshow (a fresh card that enters then freezes) and no screensaver (motion that says nothing)
- no gradient text, no left-edge accent stripes, no pure #000/#fff, no full-screen linear gradient on the dark ground, no bouncy eases
- never invent figures: render "— figure —" until the script supplies the number

## Decisions
- spine (hero prop): the question "Which regions missed their on-time delivery target last week?" — spoken in 04, typed in 04, answered in 05; identical word for word in all three
- callback: 01 plants "Monday"; 06 returns it as "Monday, answered."
- breather: 06 — the closing card is the one deliberately still read
- tokens: design.md (two colours + accent, Georgia display / Helvetica Neue sans)
- truthfulness line: "Acme is fictional, and so is its data." — spoken in 02 and shown as the title-card caption

## Still open
- does the lower third on 03 need the persona's role, or is the first-person voice enough?

## Locked
- beat order and the Demo Loop arc
- the hero prop wording
- the two-colour palette

## Beat 01 — Hook (0.0–7.4, ~7.4 s)
- phase: hook
- real: recreated
- voice: narrator
- vo: "Every Monday, the operations lead at Acme asks the same question. And every Monday, it takes a day to answer."
- screen: title card on the dark ground: "Monday, answered." then a short accent rule
- hero_prop: —
- motion: "Monday, answered." RISES 12 px, sine-in-out, 0.5 s, landing on wt(hook, "Monday") − 0.1; the rule DRAWS 0.5 s on "question"
- camera: static (recreated layer)
- seam: cut → 02, leftward
- caption: none yet
- constraint: no glow drift, no card scale creep, nothing else on the canvas until "question"
- why: states the pain in outcome language — a question that costs a day — before any product word
- type: hook
- persuasion: contrast (every Monday / a day)
- beat: tension

## Beat 02 — Thesis + honesty (7.4–12.4, ~5.0 s)
- phase: title
- real: recreated
- voice: narrator
- vo: "Acme is fictional, and so is its data. The workflow is the point."
- screen: subtitle "From an analyst’s notebook to a question anyone can ask" under the title; caption "Fictional company · synthetic data"
- motion: subtitle RISES 12 px, sine-in-out, 0.5 s on "workflow"; caption FADES in 0.4 s on "fictional"
- camera: static
- seam: cut → 03 on the first word of the notebook phase, leftward
- caption: "Fictional company · synthetic data"
- constraint: no third line, no logo, no gradient
- why: lands the value claim by beat 2 — a question anyone can ask in a minute — and says what is real before the product appears
- type: value
- persuasion: honesty as credibility
- beat: trust

## Beat 03 — The analyst's notebook (12.4–18.6, ~6.2 s)
- phase: nb
- real: recorded
- clip: nb
- voice: analyst
- vo: "My notebook loads the orders, filters the late deliveries, and counts them by region."
- screen: the whole notebook screen, then the stitched page scrolls to Part 2 on "filters" and Part 3 on "counts"; the output row is boxed
- camera: establish full screen 0.9 s hold → scroll 1.1 s → scroll 1.1 s → push ×1.35 onto the Part 3 output, sine-out 1.0 s, hold 2 s
- push: [480, 760, 1400, 140]          # screen px of the pushed-onto rect (the "full screen, then zoom" frame on the sheet)
- act: THE ANALYST
- seam: cut → 04 on "Which", leftward
- caption: lower third "THE ANALYST — Build it where the data is."
- constraint: no repainted code, no masked output, no cut before the full screen has been seen
- why: evidence — the day of work the question used to cost, shown on real pixels
- type: evidence
- persuasion: demonstration
- beat: recognition

## Beat 04 — The question, typed (18.6–23.3, ~4.7 s)
- phase: ask
- real: recorded
- clip: q
- voice: lead
- vo: "Which regions missed their on-time delivery target last week?"
- verbatim: yes
- screen: the composer full screen; the typed line uncovered word by word as it is spoken
- hero_prop: "Which regions missed their on-time delivery target last week?"
- camera: establish full screen 0.5 s → push ×1.0→1.25 onto the composer, sine-out 1.0 s
- push: [420, 700, 1320, 180]
- act: THE OPERATIONS LEAD
- seam: hand-off (seamless) → 05 real send frames
- caption: lower third "THE OPERATIONS LEAD — Ask it where the work is."
- constraint: no synthetic typing cursor, no paraphrase — the spoken words are the typed words
- why: the hero prop — the same question, now asked in a minute where the work is
- type: evidence
- persuasion: demonstration
- beat: anticipation

## Beat 05 — The answer (23.3–28.2, ~4.8 s)
- phase: answer
- real: recorded
- clip: send
- voice: assistant
- vo: "I send the question, and the answer comes back from the same governed data."
- screen: the real send frames play; pull back to the whole screen, then push ×1.6 onto the sent message on "governed"
- hero_prop: "Which regions missed their on-time delivery target last week?"
- callback: 04
- camera: play at the hand-off → pull to full 1.1 s sine-in-out → push ×1.6 on "governed", 1.2 s
- push: [700, 120, 900, 220]
- seam: cut → 06 on "One", leftward
- caption: none
- constraint: no invented figures in the answer, no highlight that is not on the product's own pixels
- why: the proof that the question now takes a minute on data the team already trusts
- type: proof
- persuasion: demonstration + trust (same governed data)
- beat: relief

## Beat 06 — Close (28.2–32.3, ~4.1 s)
- phase: close
- real: recreated
- voice: narrator
- vo: "One notebook. One question. One answer the whole team can trust."
- screen: closing card, three lines: "One notebook." / "One question." / "One answer the whole team can trust."
- callback: 01
- breather: yes
- motion: each line RISES 12 px, sine-in-out, 0.5 s, on its own "One"; then the card HOLDS — nothing moves while the credit lands
- camera: static
- seam: end — the mandatory credit is stamped by build_film.py in the footer
- caption: none
- constraint: no scale creep, no glow, bottom 120 px free for the credit
- why: restates the message as an antithesis the audience can repeat — the team already trusts the answer
- type: close
- persuasion: antithesis
- beat: resolve
