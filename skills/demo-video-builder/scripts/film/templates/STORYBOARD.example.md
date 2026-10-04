---
title: Monday, answered.
version: 1                      # == number of "## Changes from" blocks + 1 (tools/storyboard.py check)
name: film                      # film.json "name" / vo_script SCENES key → vo/film_phases.json is the clock
format: 1920x1080
duration: 35s                   # expectation from BRIEF.md length_s; the beats below must sum to it (± 10 %)
message: "A question that took a day now takes a minute, on data the team already trusts."
audience: operations leads and the analysts who serve them
arc: Demo Loop — the old way → the promise → the notebook → the question → the answer → close
mood: calm, exact, unhurried
music: none
captions: yes                   # bottom 17 % of the canvas is the caption keep-out (y ≤ 598 on the 720 stage)
---

<!-- Everything here is FICTIONAL (Acme, synthetic data). Copy to <project>/STORYBOARD.md.
     One beat per idea. Heading = "## Beat NN — Name (t0–t1, ~dur s)" in absolute seconds; the sum is checked.
     Fields are "- key: value" bullets; unknown keys are kept. Quote EVERY word that renders on screen.
     start: / end: = the first and the last frame of the beat in one sentence each (end: is mandatory on recreated
     beats — the next cut lands on it; check --build refuses without it). The review pack shows both frames per
     beat with Approve start / Approve end; once approvals.json exists the build waits for every END.
     hold: = move first, then hold (gates/hold_gate.py): on a recreated beat the fraction after which only the background
     may move (0.3–0.95), or "none (reason)" as a written waiver the gate prints; never on a footage match-cut. -->

## Video direction
- palette: ground "#082A34" + ink "#E9F3F9"; the accent "#E56B5E" touches one focal element per beat and nothing else
- two-colour discipline: emphasis by inversion, scale or density — never a third hue
- reveal model: at t=0 only what the narrator is saying is on screen; every further piece lands on its spoken word; reveals spread over the back ~50 % of a beat, never front-loaded in the first ~25 %
- holds: a held read beats bad motion; no breathing loops, no glow drift, no slow push in the back half; low-amplitude jitter is the only sanctioned aliveness
- seam rule: leftward — exits travel left, entries arrive from the right; hard cut on every screen change; one shader accent per act, never between two product screens
- keep-out: nothing authored below 83 % of the height except the mandatory credit box
- no slideshow (a fresh card that enters then freezes) and no screensaver (motion that says nothing)
- no empty plates: a card's first words are inked on the frame it appears; a lower third's line starts with its wipe
- no gradient text, no left-edge accent stripes, no pure #000/#fff, no full-screen linear gradient on the dark ground, no bouncy eases
- legibility floor: 16 stage px for every label, kicker and tick (24 px at 1080p), 18 for body lines
- never invent figures: every number a block shows is a claims.json value; render "— figure —" until the script supplies it

## Decisions
- spine (hero prop): the question "Which regions missed their on-time delivery target last week?" — spoken in 04, typed in 04, answered in 05; identical word for word in all three
- the old way first: 01 is a recreated chat (labelled recreated) where the same question waits a day; 02 answers it with the title
- callback: 01 plants "Monday"; 02 says "Monday, answered."; 06 returns it as the sub line
- the one figure: "3" — spoken in 03, landed directly by a call-out beside the notebook's own boxed output row, circled in 05 on the answer card
- the typed question is its own caption: 04 captions nothing; one voice owns the hero line
- breather: 06 — the closing card is the one deliberately still read, and it holds while the credit lands
- tokens: design.md (two colours + accent, Georgia display / Segoe UI sans), skin harbor
- truthfulness line: "Acme is fictional, and so is its data." — spoken in 02 and shown as the title-card caption

## Still open
- does the lower third on 03 need the persona's role, or is the first-person voice enough?

## Locked
- beat order and the Demo Loop arc
- the hero prop wording
- the two-colour palette

## Beat 01 — The old way (0.0–7.4, ~7.4 s)
- phase: hook
- real: recreated
- voice: narrator
- vo: "Every Monday, the operations lead at Acme asks the same question. And every Monday, it takes a day to answer."
- screen: a recreated chat card on the dark ground: kicker "Every Monday", the card's tag "recreated · fictional"; the card arrives at the composer's own height, the question "Which regions missed the on-time target last week?" TYPES into the composer, is sent, the card GROWS as the question lifts into its bubble, three dots wait, and the reply "On it. I will have it by tomorrow." streams in
- start: the dark ground with the kicker "Every Monday" alone, top-left of the card slot; the card is not there yet
- end: the recreated chat card at full height with the sent question in its bubble and the reply "On it. I will have it by tomorrow." fully streamed, the dots gone
- hero_prop: —
- motion: kicker RISES 12 px on wt(hook, "Monday"), sine-out; the card arrives 0.38 s; the question TYPES at 18–24 characters per second; the card grows 0.6 s power3-out on the send; the reply LANDS word by word on wt(hook, "answer")
- hold: none (the reply streams word by word on "answer", the last spoken word — the hook has no still to hold; the title cut lands on the finished bubble)
- camera: static (recreated layer)
- seam: cut → 02, leftward (cut-the-curve)
- caption: lane, anchor
- constraint: no product pixels yet, no glow drift, the card is labelled recreated, never an empty box
- why: states the pain in outcome language — a question that costs a day — before any product word
- type: hook
- persuasion: contrast (every Monday / a day)
- beat: tension

## Beat 02 — Monday, answered (7.4–13.6, ~6.2 s)
- phase: title
- real: recreated
- voice: narrator
- vo: "Monday, answered. Acme is fictional, and so is its data. The workflow is the point."
- screen: title card: "Monday, answered." builds word by word, "Monday," already inked on the cut frame; subtitle "From an analyst’s notebook to a question anyone can ask"; caption "Fictional company · synthetic data"; at the end the notebook's first still DIVES onto an empty window frame
- start: "Monday," already inked at the headline position on the dark ground, nothing else
- end: the title card gone and the notebook's first still landed flat in the staged window frame, the lane about to take over
- motion: "Monday," and "answered." ARRIVE on their spoken words with a short blur, sine-out; "answered." promoted to the accent; a soft cream lamp GROWS behind the line (the card's own ink, not a third hue); two muted depth planes DRIFT and one accent plane crosses once, under the headline; the rule DRAWS on "Acme"; caption RISES on "fictional"; subtitle RISES on "workflow"; the plate DIVES 0.9 s and LANDS on wt(nb, "notebook")
- hold: none (every element of the title lands on its spoken word and the plate dives on the last one; the dive's landing frame is the held state)
- camera: static; the slow push 1.2 %/s on the inner card only
- seam: match-cut → 03: the card cuts out on the frame the plate appears; the lane takes over on the frame the dive ends
- caption: none (the words are on the card)
- constraint: no third line, no logo, two hues only; the plate is the lane's own first still, never recoloured
- why: lands the value claim by beat 2 and says what is real before the product appears
- type: value
- persuasion: honesty as credibility
- beat: trust

## Beat 03 — The analyst's notebook (13.6–21.8, ~8.2 s)
- phase: nb
- real: recorded
- clip: nb
- voice: analyst
- vo: "My notebook loads the orders, filters the late deliveries, and counts them by region. Three regions are over target."
- screen: the notebook in a window on the mesh wallpaper (staged), then the stitched page scrolls to Part 2 on "filters" and Part 3 on "counts"; the camera lands the boxed output row in the upper-middle third; on blank page beside it a small call-out "regions over target" LANDS its figure "3" directly on "Three" with one pulse, sub "Part 3 · synthetic data"
- start: the staged notebook window on the mesh wallpaper, whole and unpushed, Part 1 at the top
- end: the Part 3 boxed output row in the upper-middle third at ×1.58 with the call-out "regions over target · 3" settled beside it
- camera: establish the window 0.9 s hold → push ×1.15 into the page 1.2 s, sine-out → scroll 1.1 s → scroll 1.1 s → push to ×1.58 onto the Part 3 output on "region", 1.0 s, sine-in-out
- push: [480, 760, 1400, 140]
- act: THE ANALYST
- seam: cut → 04 on "Which", leftward (cut-the-curve on the camera)
- caption: lower third "THE ANALYST — Build it where the data is." (card, no stripe, above the lane); lane, anchor
- constraint: no repainted code, no masked output, the staged window never recolours the recording; the call-out sits on blank page and shows the claims.json value only; the accent is spent once — on the boxed row
- why: evidence — the day of work the question used to cost, shown on real pixels, and the figure the film will return to
- type: evidence
- persuasion: demonstration
- beat: recognition

## Beat 04 — The question, typed (21.8–26.5, ~4.7 s)
- phase: ask
- real: recorded
- clip: q
- voice: lead
- vo: "Which regions missed their on-time delivery target last week?"
- verbatim: yes
- screen: the whole screen for the typing: the typed line uncovered word by word as it is spoken; a tight spotlight FRAMES the composer (the hole is the composer) and GLIDES to the Send control as the presenter's hand arrives (redrawn from the recording's telemetry)
- start: the whole chat screen, composer empty, the spotlight framing the composer
- end: the typed question complete in the composer at ×1.15, the spotlight resting on Send, the hand arrived
- hero_prop: "Which regions missed their on-time delivery target last week?"
- camera: the whole screen 0.5 s → push ×1.15 onto the chat column (thread above, composer below), sine-out 1.0 s → hold
- push: [420, 180, 1480, 880]
- act: THE OPERATIONS LEAD
- seam: hand-off → 05 real send frames
- caption: lower third "THE OPERATIONS LEAD — Ask it where the work is." for 2 s, then gone; lane: drop (the typed question is the caption)
- constraint: no synthetic typing cursor on the footage, no paraphrase — the spoken words are the typed words; nothing authored stacks in the bottom 15 % with the composer
- why: the hero prop — the same question, now asked in a minute where the work is
- type: evidence
- persuasion: demonstration
- beat: anticipation

## Beat 05 — The answer (26.5–31.3, ~4.8 s)
- phase: answer
- real: recorded
- clip: send
- voice: assistant
- vo: "I send the question, and the answer comes back from the same governed data."
- screen: the real send frames play on "send" (the redrawn cursor clicks, a ring); pull back to the whole screen; the answer card arrives on "comes"; a hand-drawn circle LANDS on its figure "3" on "back"; a receipt pill "grounded in the notebook · same governed data · traceable" lands under the card, on blank page, on "governed"
- start: the same ×1.15 pose as the typing ended on, the cursor on Send, the ring about to fire
- end: the answer card on the whole screen with the circle closed on "3" and the receipt pill resting under the card
- hero_prop: "Which regions missed their on-time delivery target last week?"
- callback: 04
- camera: play at the hand-off → pull to full 0.8 s sine-in-out → hold
- push: [700, 120, 900, 220]
- seam: gl → 06: a light leak in the accent and the ground sweeps the answer still into the closing card, 0.4 s, split 0.15, on "One"
- caption: lane, karaoke; "governed" in the accent
- constraint: the circle sits on the claims.json figure and nowhere else; no highlight that is not on the product's own pixels; the leak shows at most two dim frames over the footage side and never grades the answer still
- why: the proof that the question now takes a minute on data the team already trusts
- type: proof
- persuasion: demonstration + trust (same governed data)
- beat: relief

## Beat 06 — Close (31.3–35.4, ~4.1 s)
- phase: close
- real: recreated
- voice: narrator
- vo: "One notebook. One question. One answer the whole team can trust."
- screen: closing card: the lockup's kicker "One notebook · One question" (22 px, the card's ink-soft); the title "One answer the whole team can trust." builds word by word on its spoken words; the rule DRAWS on "trust"; sub "Monday, answered."
- start: the dark ground with the kicker "One notebook · One question" alone at the top of the lockup
- end: the full lockup — kicker, "One answer the whole team can trust.", the drawn rule and the sub "Monday, answered." — still, the answer still long gone with the leak that carried it, the credit in the footer
- callback: 02
- breather: yes
- motion: the kicker RISES the moment the leak window clears, sine-out; each title word ARRIVES on its word; the rule DRAWS 0.5 s; the sub RISES 16 px; then the card HOLDS for the 3.6 s tail — nothing moves while the credit lands
- hold: 0.55 (FILM.holds "close": the lockup is complete by the end of the narration and holds through the 3.6 s tail while the credit lands)
- camera: static
- seam: end — the mandatory credit is stamped by build_film.py in the footer
- caption: none
- constraint: no scale creep, no glow, bottom 120 px free for the credit
- why: restates the message as an antithesis the audience can repeat — the team already trusts the answer
- type: close
- persuasion: antithesis
- beat: resolve
