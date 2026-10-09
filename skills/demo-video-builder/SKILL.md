---
name: demo-video-builder
description: Use when building a polished, voice-narrated demo video from a screen recording — turning a raw capture of a product demo into a shareable MP4 with cut lag, scrubbed privacy leaks, synced VO, optional animated opener/outro. v2 adds cinematic "story rebuilds" — animated b-roll acts word-synced to a multi-voice cast. v3 adds production films — real-pixel footage (original full screen → zoom, real scrolls and typing), the narration as the clock, deterministic frame-by-frame render, linear-loudness mastering, QA gates. v4 adds production craft — velocity-matched seams, camera kit, caption lane, carved audio, lint + determinism canary, storyboard review, blocks, media ledger, honest finishing. v5 is the picture layer — GSAP timelines on the clock, kinetic type, WebGL transitions, 3D titles, story blocks, light / depth / annotation / glass, reveals, a redrawn cursor and camera from telemetry, idle detection, an OCR leak gate, karaoke captions, staging and vertical reflow, brand kits + ten skins, a live studio, a review pack, synthesized SFX — on software GL, with the mandatory FDE Demo Builder end-screen credit. Triggers on "build a demo video", "narrate this recording", "make a demo from this screen capture", "cut the thinking lags and add voiceover", "add a wow animated opener", "multi voice demo", "b-roll story animation", "booth trailer", "make this look like a product film", "kinetic titles", "karaoke captions", "vertical cut".
---

# Demo Video Builder

Turn one screen recording into a polished, narrated, privacy-clean demo video — **fully scripted**, no
video editor.

## MANDATORY: the end-screen credit

Every video made with this plugin — v1, v2, v3, v4, v5, cut-downs and re-exports — ends with one small line,
centred in the footer of the end screen: **"Crafted with FDE Demo Builder · by Ahmed Awan"**. `credit.py`
stamps it (last 4 s, fade-in, auto light/dark) and verifies it; `build.py`, `assemble.example.sh` and
`build_film.py` call it as their final step, `qa_film.py` and the `demo-qa-reviewer` agent fail a video
without it. Never skip, reword, restyle, move or cover it; custom pipelines must call `python credit.py stamp`
on the final file. → `references/credit-footer.md`

## Operating principles (read first)

- **Use the real screen, never mock-ups.** Every product frame comes from the actual recording. Do not
  fabricate UI, type-ins or numbers. If a number is spoken, it is visible on screen at that moment and listed
  in `claims.json`. Recreated cards are labelled recreated.
- **Real footage is sacred.** Product pixels are scaled, moved and masked with small soft blurs — never
  recoloured, warped, grained, redrawn or blended. Effects cross footage only inside a declared seam window
  ≤ 0.5 s. Every product beat opens on the original full screen (~1 s), then zooms.
- **Privacy is non-negotiable and easy to miss.** Address bars with tokens, bookmarks, extension badges,
  usernames, avatars, internal names typed into fields. Every shipped frame is scrubbed; in v5 the leak gate
  reads the pixels, not your intentions. → `references/privacy-scrubbing.md`, `references/privacy-leak-gate.md`
- **One clock.** Narration word times drive every cut, move, caption and sound (`wt(phase, word)`); every
  visual is a pure function of `t`; two renders are byte-identical.
- **Cut the dead air.** Spinners, loads and idle hands are the difference between a slog and a tight film.
- **One source of truth** per workflow (`demo_config.py`, `vo_script.py` + `STORYBOARD.md` + the ledgers).
  Change the source, re-run — never hand-edit intermediate files.
- **QA until clean.** A demo is done when the gates pass and the adversarial reviewer finds nothing.

## v1 — Polish one recording (7 phases)

1. **Map** beats and lags. → `references/map-and-cut.md` 2. **Cut lags** with `spans`. 3. **Scrub privacy**
(chrome bar, time-gated masks). → `references/privacy-scrubbing.md` 4. **Frame & zoom** (native scale, gentle
push-in). → `references/framing-and-zoom.md` 5. **Voiceover** per beat with edge-tts. 6. **Assemble & sync**
(`build.py` time-fits footage to VO). → `references/voiceover-and-sync.md` 7. **QA** → `references/qa-checklist.md`.
Scaffold with `/fde-demo-builder:new-demo <name>`; `gen_vo.py` → `build.py` → `out/demo.mp4`. Pitfalls:
`references/ffmpeg-gotchas.md`.

## v2 — Story rebuilds: b-roll acts + a multi-voice cast

Review the source (frames + transcript) → write `vo_script.py` (2–3 voices, SCENES + PLACED beats) →
`gen_vo_multivoice.py` (word timestamps) → clock-driven b-roll scenes (`frame(t)`, `wt()`, flakes, Ken Burns)
QA'd with `shot.js` and rendered with `render_scene.js` → `assemble.sh`. B-roll is clearly stylised and
fictional; recorded segments are real screens only. → `references/broll-scenes.md`, `references/multi-voice.md`,
`/fde-demo-builder:new-broll`.

## v3 — Production films: real pixels on the narration clock

Shot log + honesty audit → narration is the clock (`check_cues.js` fails unresolved cues) → `extract_clips.py`
(median stills, stitched pages in the app's own chrome, 30 fps seqs, inverted zooms, repaint never rewrite) →
original screen first then the zoom (`establish`, `FOOT.fullscreen`), real scrolls, typed text uncovered as
it is spoken → `render_frames.js` (frame-by-frame, N workers, frame 0 = clock 0) → `build_film.py` (carved
bed, two-pass linear loudnorm to −16 LUFS, captions, **credit**) → `qa_film.py`. → `references/real-pixel-footage.md`,
`deterministic-render.md`, `cinematic-grammar.md`, `honesty-audit.md`, `audio-mix.md`.

## v4 — Production craft

| Layer | Lib / tool | Gate | Reference |
|---|---|---|---|
| Seams: cut-the-curve, zoom-through (+inverse), waterfall, nudge, rack-focus, carriers, the vector ledger `seams.json` | `lib/seams.js` | `seam_gate` | `motion-doctrine.md` |
| Camera: punch in/out, zoom-out reveal, focus pull, caret-follow, pose ladder, zoom budget (≤ 88 % frame, ≤ 2× source px) | `lib/camera.js` | `motion_diag` | `camera-moves.md` |
| Caption lane on the word times (8 presets) + lower thirds, stat cards, hero word, pull-quote, PiP | `lib/captions.js`, `lib/overlays.js`, `tools/captions_srt.py` | `overlay_gate` | `captions-and-overlays.md` |
| Audio: band-limited voice carve, pan upmix, voice presets, level match, beat grid | `audio/carve_bed.py`, `voice_presets.py`, `beat_grid.py` | `audio_gate` | `audio-carve-and-beats.md` |
| Lint + determinism, golden frames, doctor, fonts, text audit | `gates/lint_scene.py`, `tools/doctor.py`, `fonts_localize.py`, `audit_text.js` | `canary`, `snapshot`, `lint_scene` | `lint-and-determinism.md` |
| Planning: BRIEF, STORYBOARD arithmetic + sketch sheet + lock, design tokens; `start:` / `end:` per beat and a phone sheet (v5.1) | `tools/brief.py`, `tools/storyboard.py` (`sheet --mobile`) | `text_gate` | `brief-storyboard-review.md`, `storyboard-start-end.md` |
| v4 blocks (delegating to v5 where they overlap) | `lib/blocks.js` | — | `blocks-catalog.md` |
| Media ledger, export presets, timeline printout | `tools/ledger.py`, `tools/export.py`, `tools/timeline.py` | `ledger_gate` | `media-ledger-and-export.md` |
| Finishing on recreated layers only; truthful footage normalisation | `lib/vfx.js`, `tools/grade.py` | `grade_gate` | `vfx-and-grading.md` |

## v5 — The picture layer: what the viewer sees

Start with `references/picture-doctrine.md` (one clock, the layers, the device vocabulary, the spending rules).
Everything below is deterministic on software GL (`render_frames.js` default; `RENDER_GL=hardware` for
previews), loads its libraries from the project's `node_modules` by relative path (`npm i puppeteer gsap three
d3-delaunay`), and never touches a product pixel. Gates are footnotes: the device is the point.

| What the viewer sees | Device | Lib / tool | Reference |
|---|---|---|---|
| A number that lands on the word that names it; a card that types, seals and recoils; a receipt that snaps into place; a question typed at human rhythm and answered in a stream | `BL2.countUp` · `decisionCard` · `receipt` · `twoLayers` · `sceneCards` · `chatReveal` · `approvalCard` · `flash` ¹ | `lib/blocks2.js` on `lib/motion.js` | `story-blocks.md`, `motion-and-typography.md` |
| Titles whose words arrive as they are spoken, a phrase that becomes another phrase without the line jumping, one word promoted, a slam on the payoff, glyph soup resolving into a headline | `TYPO.centerBuild` · `swap` (match cut) · `heroWord` · `slam` · `scramble` · `stagger` · `shimmer` · `lockup` | `lib/typo.js` | `motion-and-typography.md` |
| A headline cut into glass shards that fly in from depth, settle, hold and fly past the lens; or an outline that assembles from pieces; a stack of cards the camera dollies through | `T3D.shardTitle` · `portalTitle` · `depthStack` | `lib/title3d.js` (three, d3-delaunay) | `titles-3d.md` |
| A cut that splits the colours and converges on the new screen, an ink dissolve, a warm light leak, an iris from a click, a slit-scan wipe, a cross-warp on the house current — ≤ 0.5 s over footage, never between two product screens ² | `GL.cutTransition` driven by `seams.json` `type: gl` rows | `lib/shaders.js` (WebGL2) | `gl-transitions.md` |
| The first real screen arriving as a floating plate that flattens into the lane, or compiling out of 6000 particles; the last one lifting away for the close | `REVEAL.heroDive` · `assemble` · `irisFrom` · `lightWipe` · `matchCutHandover` · `pullBack` ³ | `lib/reveals.js` | `reveals.md` |
| A clean pointer with click rings where the real one was erased; the keys the presenter pressed; a frame that moves to where the work happens, landing on a spoken word | `record_events.py` (clap-aligned telemetry) · `cursor_track.py` (proposal from pixels) · `camera_from_events.py` · `CURSOR.mount` · `HUD.mount` | `tools/`, `lib/cursor.js`, `lib/hud.js` | `recording-native.md` |
| Dead air gone: idle, spinner, typing, scroll and page change found from change energy and turned into cuts, speed ramps, caret-follow and a "working" caption | `idle_detect.py` → `play.map` / `play.rate` / camera hops ⁴ | `tools/idle_detect.py` | `recording-native.md` |
| A hand-drawn circle, arrow, box or underline on the figure the voice names, a spotlight that glides between two stops, a label with a leader — projected through the camera | `ANNOTATE.circle` · `arrow` · `box` · `underline` · `strike` · `spotlight` · `label` ⁵ | `lib/annotate.js` | `light-depth-annotation.md` |
| A card that is lit: a lamp behind it, a 105° light sweep on the landing word, a 1 px rim; parallax planes with one occluder crossing; a dolly with real differential growth; frosted panels | `LIGHT.bloom` · `leak` · `sweep` · `rim` · `DEPTH.planes` · `dolly` · `GLASS.panel` ⁶ | `lib/light.js`, `lib/depth.js`, `lib/glass.js` | `light-depth-annotation.md` |
| A reel, not a deck: a grid of days that rises as iso cubes and lands back on the flat grid; two accent panels that slam shut and split onto the title; a pixel-matrix wipe at the big cuts; light-speed bursts and ripple rings on the payoff word; a glossy liquid core that drinks every arriving artifact; outline marquees, smear trails, a film HUD with chapters and timecode | `REEL.voxel` · `view` · `slam` · `stinger` · `streaks` · `rings` · `blob` · `marquee` · `smear` · `hud` · `decode` | `lib/reel.js` (no GSAP; `scenes_reel_demo.html`) | `showreel-motion.md` |
| Charts whose every value is a claim; a before/after split, wipe or picture-in-picture where both halves are the recording's own pixels | `CHART.bars` · `line` · `kpiTiles` · `race` · `donut` ⁷ · `COMPARE.split` · `wipe` · `pip` | `lib/charts.js`, `lib/compare.js` | `story-blocks.md` |
| The screen in a frame (wallpaper, padding, neutral title bar) and a vertical or square cut that follows the cursor like an operator | `STAGE.mount` · `stage.pose` · `STAGE.reflow` → `export.py --reflow` | `lib/stage.js` | `staging-and-reflow.md` |
| The spoken word lighting up in the caption; a word waterfall on recreated lines; the same timing in the burn-in, the .srt/.vtt and an .ass with per-word tags; chapters that start on cuts | `karaoke` · `kinetic` styles · `captions_ass.py` · `chapters.py` ⁸ | `lib/captions.js`, `tools/` | `captions-karaoke-chapters.md` |
| Nothing private: every extracted frame OCR'd for e-mails, identifiers, URLs, tokens, phone numbers, denylisted names and account badges; a blur proposal with a measured radius | `leak_gate.py` · `mask_propose.py --verify --apply` ⁹ | `gates/`, `tools/` | `privacy-leak-gate.md` |
| A look approved before the build: a logo → a contrast-checked skin + a six-frame style sheet; ten shipped skins with motion profiles and caption styles | `brand_kit.py extract · compose · check` · `skins/*.json` · `skin_apply.py` ¹⁰ | `tools/`, `skins/` | `brand-kits-and-skins.md` |
| Any frame in under a second, hot reload at the same t, a 1920x1080 tap through the real renderer; one offline review page with honesty flags, per-beat comments and the storyboard sign-off | `studio.py` (T tap, Q lint) · `review_pack.py build · --serve · --lock` ¹¹ | `tools/`, `studio/` | `review-pack-and-studio.md` |
| Sound that was never sampled: whoosh, tick, snap, impact, riser, shimmer, confirm and six keys synthesized at −6 dBFS, placed on seams and block landings, never within 0.15 s of a word; a voice chain with a built de-esser; a bed that breathes at seams | `sfx_synth.py` · `sfx_place.py` · `fx_chain.py` · `envelope.py` ¹² | `audio/` | `audio-fx-and-sfx.md` |

¹ sync points → `out/timeline.json` for SFX; `flash` over footage ≤ 0.5 s once per act. ² `seam ledger` validates gl rows (0.1–0.5 s, ≤ 3 techniques, cause on whip/zoom kinds); `effects off footage` forbids `GL.pass` on the lane; `determinism` proves two renders identical with the same `gl_renderer`. ³ `reveal handover` · `reveal join` (≤ 1 luma level across the hand-over pair) · `reveal sampled`. ⁴ proposals are accepted in the storyboard; `zoom budget` measures the pushes you paste; a declined analysis carries `"accepted": false`. ⁵ `annot evidence` (a mark sits on a claim figure or a logged click, ≤ 2 strokes at once) · `annot ink` (never across product text). ⁶ `light leak` (≤ 0.5 s, inside a seam row, bloom ceiling .45) · `glass budget` (≤ 2 panels, never on the caption lane). ⁷ `chart claims` (every `claim:` id resolves in `claims.json`) · `chart figures` (every rendered figure equals its claim); derived figures are never computed. ⁸ `caption shape / timing / contrast` unchanged; `captions_ass.py` and `chapters.py` (≥ 10 s, ≤ 40 chars, starts on cuts) exit 1 on findings. ⁹ `leaks` FAILs on any live unmasked hit; `leak ocr` warns without an engine. ¹⁰ `skin check` · `skin tokens`. ¹¹ `review lock`: `## Locked` carries a sign-off before the build that ships. ¹² `sfx word-safe` · `sfx one impact` · `sfx level`. Full index: `references/qa-gates.md`.

## v5.1 — Frames first, then motion

| What the viewer (and the reviewer) gets | Device | Lib / tool | Reference |
|---|---|---|---|
| A beat that is approved on two stills — the frame it opens on and the frame the next cut lands on — before any motion exists; the storyboard writes both in one sentence each and is read on a phone | `start:` / `end:` per beat (END mandatory on recreated beats) · `storyboard.py sheet --mobile` · `snapshot.py --pairs` → `out/pairs/pairs.jpg` · review pack **Approve start / Approve end** → `approvals.json`; `check --build` refuses while an END is unapproved | `tools/storyboard.py`, `gates/snapshot.py`, `tools/review_pack.py` | `storyboard-start-end.md`, `frame-pairs-and-approvals.md` |
| A recreated beat that moves first and then holds, so its end frame is a still the cut can land on — while footage match-cuts keep carrying motion through the cut | `hold: 0.6` per shot / `FILM.holds` (required on recreated beats, forbidden on footage match-cuts, `hold: none (reason)` as a written waiver) · `hold declared` · `hold still` · `seams move` skips the cut that ends a hold ¹³ | `gates/hold_gate.py`, `lib/footage.js` | `hold-doctrine.md`, `motion-doctrine.md` |
| A whole-cut review — rhythm, the transition at every cut, grade, loop closure — whose notes snap to the edit and carry a decision, rejections included, into the delivery | `demo-qa-reviewer` whole-cut pass · `review_notes.py add / import / decide / table` → `review_notes.json` → `DELIVERY.md` *Reviewer notes — proposed, decided* | `tools/review_notes.py`, `tools/export.py share_pack` | `whole-cut-review.md` |
| The edit as a text list — clip, length, start, speed, reverse — that opens where the product does something, speeds a long clip to its slot instead of trimming it, holds a short clip's end state, plays a window backwards frame-exact | `cutlist.py export / resolve --auto-window --fit / emit / check --check-length / render` ↔ `play{from, to, rate, reverse}` via `scenes/cutlist_data.js` | `tools/cutlist.py`, `lib/footage.js` | `cut-list.md` |

| A film that knows which films it resembles — as numbers: median shot, shot-length band, cut rhythm, luma and contrast bands — and never as content | `ref_study.py log / measure / report / lint` → `refs.json`, `REFERENCES.md` (craft-not-content lint refuses logos, taglines, quoted copy) | `tools/ref_study.py` | `reference-study.md` |
| One look per kind of shot — product as recorded, cards in the house identity, titles allowed their effect, people never glitched — and every beat checked against the look of its type | `design.md looks:` · `look:` per beat · `look types` · `look effects` | `gates/look_gate.py` | `looks-per-shot-type.md` |
| An end frame that is an edit of the start frame: anchors within 2 px, no word the plan never wrote, no name that arrives unannounced | `pair anchors` · `pair words` · `pair roster` (OCR via the leak gate's engine, WARN-pass without one) | `gates/pair_gate.py` | `pair-gate.md` |
| Version N+1 written from N by text replacement, with proof that the shots you did not touch rendered the same picture | `cutlist.py bump --replace --previous-film` → `out/cutlist_bump.json` · `identity frames` · `identity colour` (≤ 0.5 ΔE) | `tools/cutlist.py`, `gates/identity_gate.py` | `identity-and-bump.md` |
| A booth loop that restarts on a matching picture instead of a dip — when the edges line up | `export.py --preset booth_loop --closure hardcut` (Sobel column-profile correlation, score reported, dip fallback) | `tools/export.py` | `loop-closure.md` |
| The failures a mean misses: a single-frame jump, a pan that moved one half of the frame, a roster that changed between two stills | `motion_diag.py --spikes · --pan-halves · --roster` (+ spikes as a WARN in `motion traced`) | `gates/motion_diag.py` | `motion-scans.md` |
| Every build as a take — wall time, frames, GL path, scene hash, gates — kept with its scene and film until the review is locked | `out/takes.jsonl` · `takes.py list / time / annotate / prune --after-lock` · `.history/takes/<n>/` | `build_film.py`, `tools/takes.py` | `takes-ledger.md` |

| Text that fits its box at every second, draw-on strokes that reach their end, a caption lane that may own its shape when it speaks in clauses | `text overflow` (scroll box ≤ client box + 3 px, browser-measured) · lint `dash_nonscaling_stroke` · `caption shape` explicit limits | `gates/overflow_gate.py`, `gates/lint_scene.py`, `gates/overlay_gate.py` | `text-fit-and-draw-on.md` |

| Every sound proven on its frame after the mux; hand-placed moments that sit on the beat while landings sit on their words | `cue sync` (≤ 1 ms, high-passed cross-correlation in the finished audio) · `sfx_place.py` beat snap for unanchored sync points | `audio/cues_check.py`, `gates/sfx_gate.py` | `cue-sync.md` |
| A fast push or a slide-through that smears the way a camera would — only where the picture moves, and the same on every render | `render_frames.js --shutter 240` (k real sub-frames per measured window, averaged by `tmix`; receipt `shutter`) | `render_frames.js`, `gates/motion_diag.py` | `motion-blur-shutter.md` |
| Four tones the film rests on and a speed ladder it moves at | `design.md tones:` · `palette tones` · `seq quantized` playback rates | `gates/skin_gate.py`, `gates/motion_diag.py` | `palette-tones-and-speed-contrast.md` |
| A shot's own contract read against its rendered frames: words that may never show, the figure it must trace, the study it borrows | `shots.js spec{}` · `spec forbidden` · `spec claims` · `spec references` | `gates/spec_gate.py` | `shot-spec.md` |
| Two looks judged as a cut — the same shots, stacked on one clock | `pilot.py A B --shots 3-6` → `out/pilot.mp4` + sheet | `tools/pilot.py` | `pilot.md` |
| The lesson each step was built on, printed where it runs; a delivery that lists the decisions a person made | `lessons.py <step>` · `build_film.py` stage lessons · `DELIVERY.md → Decisions kept manual` | `tools/lessons.py`, `tools/export.py` | `lessons-and-decisions.md` |

¹³ `hold still` measures ≤ 1.0 % mean frame change per 0.1 s inside `[t0 + hold·(t1−t0), t1 − 0.15 s]` (the declared background allowance, `bg:`); `hold declared` wants 0.3–0.95 and coverage of every recreated storyboard beat.

## Lessons by step (`tools/lessons.py --md`)

| Step | The lesson | The rule it became | Kept manual |
|---|---|---|---|
| brief | A brief that infers an answer has not asked the question. | One field per message, the recommended option first with its receipt; stated and inferred as two groups. | the message, the audience, what is real |
| references | A reference logged as what it shows gets copied; logged as how it is cut it gets learned. | Shot length, camera, lighting, cut — never logos, taglines or quoted copy; the report turns them into bands the plan is checked against. | which five to ten films, and which bands to keep |
| look | One look for every shot flattens the film; a look per shot type lets a title spend what a product frame may not. | Product as recorded, cards in the house identity, titles allowed their effect, people never glitched; the gate reads CSS and effect calls per type. | the skin, the four tones, the per-type forbid lists |
| storyboard | A beat that has not written its last frame has not decided where it stops moving. | start: and end: in one sentence each, end: mandatory on recreated beats; hold: says when only the background may move; the arithmetic must add up to the narration. | beat order, the hero prop, the breather, every end: sentence |
| sketch | A storyboard read on a phone gets comments; one read in a repo gets approval. | sheet --mobile, one column, tap to zoom; every comment at this stage costs a sentence, after a render it costs a render. | which cells change |
| lock | Building before the lock means rebuilding after it. | check --build refuses without ## Locked (--autonomous waives it for a drive-it run) and, once approvals exist, without every END frame approved. | the sign-off itself |
| cutlist | A footage shot trimmed to its slot loses its end state; one sped to its slot keeps it. | The text list (clip, length, start, speed, reverse) opens where the product does something, speeds a long clip up to 1.6x, holds a short one; --check-length fails a list that does not add up. | start, speed and direction of every clip |
| seams | A cut lands mid-motion on both sides, or it reads as a slide. | seams.json before the shots: one current, reserved vectors spent once per act, at most one gl accent per act, never between two product screens; recreated beats move first and then hold. | the current, the one reserved vector, the accent |
| narration | The narration is the clock; everything else is a function of it. | Word times drive every cut, move, caption and sound; a VO regen moves every cut and re-opens every seam — re-run the gates. | the words, the pauses, the voices |
| footage | Every product frame comes from the recording; a redrawn one is a fabrication. | Median stills, stitched pages in the app's own chrome, real 30 fps seqs, small soft blurs for privacy, the original full screen before any zoom. | what to show, what to blur, where to push |
| scene | Every visual is a pure function of t, or two renders differ. | No wall clock, no CSS transitions, no unseeded random, no will-change; libraries from node_modules by relative path; devices by moment, gates as footnotes. | which device carries each moment |
| build | A render that cannot be reproduced cannot be reviewed. | Software GL, compositor settle, exact CFR join, the capture-probe fallback when Chrome hangs; every build is a take with its wall time, scene hash and gates. | the take to keep |
| qa | A broken gate is a failed gate, never a skipped one. | qa_film.py runs the picture and sound checks and every gates/*.py module; measure a failing gate before loosening it; CREDIT is last and cannot be disabled. | which WARNs to act on |
| pairs | A cut is the end frame of one shot meeting the start frame of the next; approve those two stills first. | snapshot.py --pairs, the review pack's Approve start / Approve end, pair_gate on anchors, words and names. | every START and END approval |
| review | Reviewers open attachments, not repos. | One offline HTML with the frames, the claims, the gates, the honesty flags and a comment box per beat; served locally, same-origin writes only; --lock writes the sign-off. | the sign-off, every open comment |
| notes | A reviewer proposes; the editor decides and says why. | Whole-cut notes snap to the nearest edit boundary and carry accepted / rejected with a reason; rejections are kept and shipped in DELIVERY.md. | every accept / reject and its reason |
| export | A delivery that hides its decisions invites the same questions twice. | Presets from the mastered film only, every output re-checked for the credit; DELIVERY.md carries the reviewer notes and the decisions kept manual. | cut points, speeds, the take, the notes, the final length |

**How the pieces meet.** `build_film.py` runs plan (timeline + seams + gl rows + captions + chapters) →
preflight (doctor, lint, camera ladder, storyboard lock, canary) → render (software GL, compositor sync,
first-frame settle) → mix (carve, SFX stem, bus chains, bed envelope) → master → captions (.srt/.vtt/.ass) →
**credit** → ledger → exports (incl. reflow) → storyboard truth pass. `qa_film.py --profile picture` is the
fast set; `full` runs every module; CREDIT is last and cannot be disabled. The scene loads only the libs it
uses; overlays, marks, glass and captions live in screen space outside `#camera`; nothing may filter the lane.

**Working rules (v5).** Write `seams.json` before the shots; 2–3 techniques per film, one `gl` accent per act
(≤ 0.5 s next to footage, `split 0.15`, ≤ 2 frames of tint on product pixels; reveals on the first and last still
are the one sanctioned exception, proven by `reveal_gate`). One slam, one hero, one accent seam per beat. Light
is a lamp, not a route; glass ≤ 2 panels; charts on a plate. Inside a block `tl.set`, outside `MOTION.set`;
per-frame hooks through `MOTION.onSeek`; never `will-change` in a scene or a lib (the renderer waits two
animation frames after every step and joins the chunks at exact CFR — two 3-worker renders of the sample made
concurrently are byte-identical, 0/1099 frames). One type floor: labels 16 stage px (24 px at 1080p), body 18,
headline 40. Marks on evidence only. `events.jsonl` stays with the tape. Capture beats recovery: ask for `record_events.py` on every
Windows take. Pick the skin before the sketch; lock the storyboard before the build; sign the review before
the export. Everything the scene loads is a local file.

**Flow.** references (`ref_study.py` → REFERENCES.md) → BRIEF → look pass (brand kit sheet or a skin; `design.md looks:`) → STORYBOARD (with `start:` / `end:` / `hold:` / `look:` per beat) →
sketch sheet (`--mobile` for a phone) → lock → cut list (`cutlist.py` for the footage windows) → build → QA (incl.
`hold_gate`, `look_gate`) → `snapshot.py --pairs` → `pair_gate` → review pack (approve END frames, comments) → whole-cut notes decided
(`review_notes.py`) → sign-off → `takes.py prune --after-lock` → export (`--closure hardcut` for a loop; DELIVERY.md carries
the notes table). A change after that is a `cutlist.py bump` and an `identity_gate` pass. `/fde-demo-builder:new-film <name>` walks it; the fictional
Acme sample (`make_sample_recording.py`) runs end to end and passes every gate.
