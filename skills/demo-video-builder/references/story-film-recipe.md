# Kinetic Story Films

Use for a cinematic, narration-led customer or industry film: a business situation becomes a problem, product work
changes the decision, and the outcome resolves the opening. This is a treatment of the existing production pipeline,
not a new renderer. Honor the requested duration, evidence requirements and creator-credit preference.

## Choose the Story and Its Length

Take the audience, decision, systems, approved media and desired outcome from the existing brief, including prose.
For a generic industry demo, use an operator role and an industry title. A customer name, website and logo are optional.
For a customer film, inspect approved public branding and visible computed styles; record colours, type and asset
provenance. Public availability alone does not establish reuse rights. With no brand assets, choose a shipped skin.

Write the cause-and-effect chain before listing product features. Select only the connected capabilities that prove
it. An illustrative two-minute allocation is 12 s of context, 15 s of pressure, 15 s of architecture, 63 s of real
product work and decision, then 15 s of outcome/close. These total 120 s including transitions. Longer requested films
can expand the investigation, comparison, approval/action and everyday-use beats; never expand two minutes to five
just because a reference film is longer. Existing verified narrative details are inputs, not another questionnaire.

The `customer-story` template is deliberately calm. For an explicitly kinetic brief, follow `commands/new-film.md`
using the base production scaffold, then author the story beats and choose a suitable medium/high motion skin.
Treat the sample scene as scaffolding, not delivered content. Do not inherit the calm template's no-kinetic,
quiet-only-SFX rules and then describe the result as cinematic. Change the treatment coherently: brief, design,
storyboard, skin, seams, captions and audio settings must agree. This is not a new `--template` value.

## One Story, One Evidence Ledger

Use `claims.json` as the source of truth for narrative figures: its `values` feed counters/charts and its `claims`
link the spoken phrase to evidence. Record units, scenario assumptions and measured/synthetic/illustrative status
in each source entry. Technical timings, camera coordinates and scene indices are not business facts.
Do not introduce a second manually maintained `facts.json`. If supplied facts exist, import and reconcile them once.
Derive any scene data module from the ledger, and check narration against it before synthesis.

Choose three to six meaningful figures, not a screen full of metrics. A dramatized starting condition must be marked
illustrative; a claimed improvement needs a comparable baseline and a verified result. Synthetic input data does not
make an invented model metric or agent answer valid. Label synthetic scenarios wherever the figures appear.

Prefer the full product name in audience-facing narration and titles (for example, "Oracle AI Data Platform").
Preserve the actual names and text in recorded UI, code and identifiers. Avoid invented people or customer adoption
claims. Explain "zero copy", automatic ontology generation, optimality or agent execution only when independently
supported by the implementation/evidence; these are not default title cards.

## Build the Acts on the Narration Clock

| Story beat | Visual treatment | Evidence and timing |
| --- | --- | --- |
| Context | Approved b-roll or stills; readable location/industry title; restrained push | Establish the operator's decision and one relevant fact; no invented customer branding |
| Pressure | A queue, deadline, threshold or timeline visibly changes; one counter lands | Illustrative figures are labelled and ledger-backed; the change lands on its spoken word |
| How data becomes useful | Systems and data objects connect into the actual pipeline/model/semantic relationships | Animate outside the product screen; distinguish implemented links from a proposed design |
| Work and decision | Real notebook, run, pipeline, lineage, model comparison or agent interaction | Establish the full screen, show the action, hold the result, then emphasize the evidence |
| Action and consequence | Real authorized execution and receipt, or a labelled proposed next step | An animated approval click never proves a real approval or execution |
| Outcome and close | Before/after or supported result, concise next step, steady closing frame | Resolve the opening question; hold 3-4 s within the duration; honor creator_credit |

Use two or three purposeful voices: narrator for stakes/transitions, operator for the business question, and guide
for product explanation. An agent voice is optional and must quote/paraphrase a verified answer faithfully; never
add agent dialogue solely to use a third presenter. Audition the opening and one numeric result before full synthesis.
Keep warm, engaged delivery, actual-audio transcription and clean speaker handoffs.

Generate word timings with the existing narration tools. Anchor emphasis, reveals and counters to resolved word
cues, using occurrence/context when a word repeats. A lead-in is one shared timeline offset, applied once to all
voices, captions and visuals. Group captions into short readable phrases (about 6-11 words), never across a speaker
or phase, respecting the selected caption style's stricter `maxWords`. Reconcile recognizer tokens with the approved
script before word lookup; inspect punctuation in the existing caption configuration without moving timestamps.
Use the existing captions and timeline
modules; there is no prerequisite `words.js` or `hubk.js` engine.

## Motion and Sound Direction

- Use the existing `lib/typo.js`, `blocks2.js`, `charts.js`, `annotate.js`, `reel.js`, `camera.js` and `seams.js` devices.
  Pick devices by meaning: a threshold breaks when pressure rises, connectors draw when sources join, a counter
  settles when the result is named. Avoid an effect on every noun.
- Keep real product pixels untouched. Brand grading belongs only on approved b-roll and recreated explanatory art.
  A measured recreation is still a recreation; if the engagement requires live product capture, it cannot replace
  missing Agent Hub, chat, workflow or action evidence. Any separately requested concept sequence is visibly labelled.
- Use a small motion vocabulary: rise/settle, short staggers, a decisive payoff push and at most two or three major
  transition styles. Ordinarily leave several seconds between large accents. One slam or reveal earns more attention
  than repeated bursts. Rich art direction does not require a dark palette, decorative particles or continuous drift.
- On product shots use establish, eased push, readable hold, then pull back or a matched cut. Keep reading surfaces
  stable. Subtle 1-2% drift may suit b-roll; never let it shake text. For animated transitions inspect both sides of
  every join, including full-frame coverage when the design relies on a covering stinger. Do not place stylized
  wipes between product screens when the existing seam rules prohibit them.
- Score the emotional change: restrained tension under the problem, space around proof, and a small lift at the
  verified outcome. Use the existing carved bed, envelopes and synthesized SFX; keep speech-word guards and ducking.
  Do not copy fixed dB gains from a reference: source levels differ. Measure the mastered mix and the final words.
- Localize and license fonts before rendering. Keep the plugin's stronger readability floor, responsive caption
  safe zones and letter-spacing conventions; never copy a reference's fixed pixel bands onto a different stage.

## Reuse and Verify

Reuse `tools/ref_study.py`, `brand_kit.py`, `storyboard.py`, `pilot.py`, `fonts_localize.py`, `check_cues.js`,
`render_frames.js`, `build_film.py`, `qa_film.py` and the existing gates. If a reference mentions a private Agent Hub
engine, brand scraper or act-builder API, verify it exists before calling it. None is required for this treatment.
Independent assets or scene modules can be authored in parallel after agreeing on the shared clock, ledger, palette,
safe zones and join times; final timing/mix/integration remain one coordinated build. Start with one render worker.

Before a full render, inspect a small style sheet and a 10-15 s pilot containing context, a representative real
product beat, one transition and a speaker handoff. It must establish audience relevance, legibility, motion and
voice/music balance. Choose the treatment internally when the requester has delegated direction; do not require
another questionnaire or invent human sign-off. A pilot that feels like disconnected slides needs reworking.

Build that mixed pilot as a small separate production project with two or three short narration phases using
`build_film.py` (`--autonomous` only for delegated production), the selected provider, licensed bed, SFX and captions. Author its own brief/storyboard/claims with
the short duration; do not mutate the full-film plan. Reuse verified media and voices, then transfer the selected
style/settings to the main project. `tools/pilot.py` is only a silent A/B look comparison and is not this acceptance
pilot. Never synthesize the scaffold's default cloud voices without approval: configure the selected provider first
and use `doctor.py --offline` when its external speech probe is not authorized.

Use `tts_providers.verify_audio_content(text, path, language)` for every provider's takes and the final mixed
narration (or extracted phase windows), followed by listening and exact checks of names/figures. Its similarity
threshold is a screening check, not proof that every figure is right. Load the local ASR model before synthesis;
a verifier setup failure is not a reason to change speech provider. Set `FDE_WHISPER_MODEL_PATH` to the approved
downloaded model directory when using a pinned/offline model.

Keep `BRIEF.md`'s `credit` field consistent with `film.json`: use `credit: none` when `creator_credit=false`.
For delegated creative direction, deliberately set `qa.json`'s `review_lock` to `off` and document the agent's pilot
decision; do not manufacture a human signature. If human review was required, keep `review_lock: require` and wait.
Do not disable technical, evidence, privacy or audio gates.

Run the film doctor after project dependencies are installed. Verify Puppeteer/Chrome, software WebGL2 when used,
project-local JS libraries, fonts, local ASR model, FFmpeg filters, disk and memory. Browser control alone does not
prove the render environment works. Keep scenes pure functions of time; no scene randomness, wall-clock timers or
CSS animations. Compare repeated short renders with the same browser, fonts, assets and worker count; do not
promise byte identity across arbitrary machines/encoders. Use the existing determinism gate for the final project.
Scene `__seek`/`__step` callbacks must return nothing or a finite frame-decode promise, never a paused GSAP timeline:
GSAP timelines are thenable and can make the renderer wait indefinitely.

Delivery requires the evidence, privacy, captions, motion, audio, content-transcription and applicable credit gates,
plus a complete viewing of the final mix. Explicitly report unavailable capabilities, proposed actions and any QA
still incomplete. The recipe improves production decisions; passing technical checks alone does not certify taste.
Manually inspect synthetic disclosures wherever scenario figures appear; no single gate verifies this completely.

## Rebuild and Retention

For a film rebuild, dated real captures and matching execution receipts may be reused when they still prove
the requested story. Disclose reuse; do not call it a fresh live run. Record capture dates and local receipt
references in claims provenance and redacted delivery notes. Recheck that
the evidence supports the intended product/version claims; recapture when a current-state claim needs it.
Recapture is live activity and requires the same authorization as other live work. Without it, omit the
current-state claim or qualify the evidence as of its capture date; do not log in or rerun workloads implicitly.
Label intentional recorded-screen holds, use eased subpixel camera moves, and do not pass low-rate screenshots
off as smooth new interaction. Preserve
real pointer evidence; never invent clicks. Keep configuration, evaluation, deployment and realized outcomes
distinct in both script and claims. Omit unavailable components rather than inventing a successful result.

Give each voice a role in the conversation, not equal airtime. Let the score rise between lines and land a
small number of word-safe transition cues. Reject or regenerate a cold/garbled performance before adding
tempo processing; ASR similarity alone does not validate pronunciation, warmth or the exact spoken number.

Review OCR false positives in their exact source context. Keep the original findings, review reasons and
source/frame hashes; never suppress all matches for a short company name or call a sampled scan full-frame.
Keep raw OCR text and denylists internal; deliver only redacted review summaries with no leaked identifiers.
Only reuse cached OCR when the decoded pixels match, and bind final QA reports to the delivered MP4 hash.
An alternative OCR backend is not a pass of another backend's validator; state actual coverage and limitations.

After acceptance, prune superseded exports and regenerable frame/render caches only when authorized. Keep
the accepted master, captions, claims, QA/review evidence, source captures, approved voice takes, media licenses,
scene/build scripts and dependency lockfiles. Remove references to deleted projects before pruning them.
