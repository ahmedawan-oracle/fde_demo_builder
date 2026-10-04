# Changelog

## 5.1.0 — Frames first, then motion (Wave 1)

v5.1 adds the review discipline of a storyboard that is approved on stills before anything moves, a hold doctrine
by shot type, a whole-cut review whose notes become decisions, and the edit as a text cut list. Everything renders
and tests without a browser except the scene-side pair capture; every new tool and gate ships a Chrome-free
`--selftest` on synthetic frames.

- **Storyboard start / end frames.** `STORYBOARD.md` beats carry `start:` and `end:` — the first and the last frame
  in one sentence each. `end:` is mandatory on recreated beats (`check` warns; `check --build` fails without it): the
  end frame is the one the next cut lands on. `storyboard.py sheet` prints both under every cell; `sheet --mobile`
  lays the sheet out for a phone (one column under 480 px, larger type, a tap on a frame zooms it edge to edge — CSS
  focus, still no scripts). Templates (`STORYBOARD.example.md`, the three film templates) carry the lines.
  → `references/storyboard-start-end.md`
- **First/last frame pairs + approvals.** `gates/snapshot.py --pairs [film|scene]` captures `t0 + 0.1 s` and
  `t1 − 0.1 s` of every segment (title, each shot, close) into `out/pairs/<label>_{start,end}.jpg`, tiles them as
  START | END rows in `pairs.jpg`, lists them in `pairs.json` with `changed_pct` (a pair under 0.5 % is flagged
  `static`). From a rendered film the frames come straight out of ffmpeg. `tools/review_pack.py` shows the pair under
  the beat whose span holds the segment, with the `start:` / `end:` sentences and **Approve start / Approve end**;
  Save writes `out/review/approvals.json` (`POST /approvals` when served). `tools/storyboard.py check --build` refuses
  while any END frame is unapproved once that file exists (`--require-approvals [path]`, `--no-require-approvals`).
  → `references/frame-pairs-and-approvals.md`
- **Hold doctrine by shot type.** Footage match-cuts keep motion through the cut; recreated / explainer beats move
  first and then hold. `shots.js` shots take `hold: 0.6` (`holdBg` for the background allowance); `FILM.holds`
  declares the recreated segments; `export_timeline.js` writes `holds[]` and `shots[].hold` (and `play{}`) into
  `out/timeline.json`. New `gates/hold_gate.py` (in the `picture` profile): `hold declared` (0.3–0.95; required on
  every recreated storyboard beat unless the beat writes `hold: none (reason)`, which is printed as a WARN; forbidden
  on a footage shot whose end is a vector or match-cut seam row; gl rows allowed) and `hold still` (10 fps, 320x180:
  mean frame change per 0.1 s inside `[t0 + hold·(t1−t0), t1 − 0.15 s]` ≤ `bg`, default 1.0 %; WARN when nothing moved
  before the hold). `seam_gate` skips `seams move` for the row that ends a held segment (still validated, still
  flash-guarded). `storyboard.py check` reads `hold:` per beat (range, waiver reason, never on a footage match-cut).
  `motion-doctrine.md` Part 1 rule 4 rewritten by shot type. The sample declares `FILM.holds` for the close card and
  waives the hook and the title in the storyboard. → `references/hold-doctrine.md`
- **Whole-cut review + notes ledger.** `agents/demo-qa-reviewer.md` gains a whole-cut pass — rhythm, the transition
  type at every cut, grade continuity, loop closure — handed over as `<seconds> <note>` lines. New
  `tools/review_notes.py` (`add / import / decide / list / table / remap`) snaps every note to the nearest boundary of
  the edit in `out/timeline.json` (seam id > cut N > shot start/end > head/tail) with the distance moved, and keeps
  `out/review/review_notes.json` entries `{t, shot, note, kind, by, accepted, why}`; `list` exits 1 while a note is
  undecided. `export.py --preset share_pack` prints the accepted / rejected table into `DELIVERY.md` under *Reviewer
  notes — proposed, decided* and ships the JSON. → `references/whole-cut-review.md`
- **Cut list.** New `tools/cutlist.py`: one text row per footage shot (clip, length, start, speed, reverse) that
  round-trips with `shots.js play{}` through `scenes/cutlist_data.js` (`window.CUTLIST`) and back from
  `out/timeline.json` (`export`). `--auto-window` picks the `length·speed` window with the most frame-to-frame motion;
  `--fit` sets speed = available / required frames, capped at `--max-speed 1.6` (trimmed beyond, and the row says so),
  and holds a short clip's end state with cloned frames (`pad`) instead of shortening the slot; `--check-length` fails
  a list whose rows do not match their shots on the clock; `render` previews the list through ffmpeg (reverse,
  setpts, `tpad=stop_mode=clone`). `lib/footage.js` gains `play.to` and `play.reverse` and exposes the pure
  `FOOT.seqFrameIndex` (the end state is held past `to`; a reversed window holds its first frame).
  → `references/cut-list.md`
- **Reference study.** New `tools/ref_study.py`: `log` references as craft (shot length | camera | lighting | cut), `measure`
  a local mp4 (10 fps scene-cut detection above max(8, mean + 3σ), shot lengths, median, cuts per 10 s, length CV, per-shot
  luma and contrast, luma percentiles), `report` → `REFERENCES.md` with the derived bands this film is written against,
  `lint` = craft not content (logos, taglines, quoted copy, "recreate", "copy the" … refused at log time and by report).
  → `references/reference-study.md`
- **Looks per shot type.** `design.md looks:` (product / recreated / title / people: `forbid` effects + `selectors`; defaults
  when absent), `look:` per storyboard beat (inferred from `real:`/phase otherwise). New `gates/look_gate.py` (`picture`
  profile): `look types`, `look effects` — authored CSS (`filter`, `backdrop-filter`, `mix-blend-mode`) and `VFX.*` /
  `GL.pass|chain` calls on a look's selectors (or `data-look` elements), and a beat's `motion:`/`screen:` naming a
  forbidden effect without a negation. `templates/design.example.md` carries a `looks:` block. → `references/looks-per-shot-type.md`
- **Pair gate.** New `gates/pair_gate.py` on `out/pairs/pairs.json` for recreated beats: `pair anchors` (top-band ink
  boxes relocated by normalised cross-correlation, ≤ 2 px at 1080p; a vanished anchor warns unless `end:` says it leaves),
  `pair words` (end-frame OCR words ⊆ `end:` ∪ quotes ∪ screen/motion/caption ∪ claims), `pair roster` (Title-case
  newcomers must be named in `end:`). OCR through the leak gate's backends; without an engine the two OCR gates pass with
  a WARN. → `references/pair-gate.md`
- **Bump + identity.** `tools/cutlist.py bump v3 v4 --replace 'old=new' [--previous-film]` writes version N+1 by text
  replacement and `out/cutlist_bump.json` (changed clips). New `gates/identity_gate.py`: `identity frames` (same frame
  count per untouched shot and per file) and `identity colour` (mean colour per sampled frame ≤ 0.5 ΔE76 vs the previous
  render); changed shots reported, not judged. → `references/identity-and-bump.md`
- **Hard-cut loop closure.** `export.py --preset booth_loop --closure hardcut [--closure-min 0.6]`: Sobel column profiles
  of the final and opening second correlated pairwise; the best (last, first) pair ≥ 1 s apart cuts the loop with no pad
  and no dip when its score clears the floor, else the dip is kept and the record says why (`closure`, `closure_score`,
  `cut_at`). → `references/loop-closure.md`
- **Motion scans.** `gates/motion_diag.py --spikes` (a frame that differs from both neighbours while they match each other,
  plus the plain isolated outlier; also a WARN inside `motion traced`), `--pan-halves film t0 t1` (camera recovered on the
  left and right halves separately; disagreement = partial pan), `--roster start.jpg end.jpg` (named entities via OCR).
  → `references/motion-scans.md`
- **Takes.** `build_film.py` records every build in `out/takes.jsonl` (take, when, scene md5, wall s, frames, workers, gl,
  gl_renderer from the render receipt, film, gates) and retains scene + shots + timeline + QA report + film under
  `.history/takes/<n>/`. New `tools/takes.py list / time / annotate / keep / prune --after-lock` (refuses before the
  storyboard carries `signed off by`). → `references/takes-ledger.md`
- **Review server hardening.** `review_pack.py --serve` refuses cross-origin writes: Host must be `127.0.0.1:<port>` /
  `localhost:<port>` (GET and POST), a POST must be `application/json` from an Origin of `http://127.0.0.1:<port>` /
  `http://localhost:<port>` and carry the per-session token the served page embeds (`X-Review-Token`); anything else
  is 403 (body drained first). Selftest covers the good request and five refusals.
- **Storyboard ↔ scene holds.** `storyboard.py check` reads `out/timeline.json` holds and fails a beat whose `hold:` differs
  from the scene's declared row by more than 0.05 (warns on a plan hold with no row, and on a waived beat with a row).
- **Text fits, strokes finish, captions own their shape.** New `gates/overflow_gate.py` (`text overflow`, `full` profile):
  the scene seeked every second in headless Chrome, every visible text box whose scrollWidth / scrollHeight exceeds its
  client box by > 3 px fails with (t, id, text, box) — icon-node labels, line-height rounding (vertical excess under
  half the font size, no horizontal excess) and full-stage containers excluded; `out/qa/overflow.json`. `lint_scene` rule
  `dash_nonscaling_stroke`: a `stroke-dashoffset` draw-on in the same authored file as `vector-effect: non-scaling-stroke`
  is an error (the dash is in user units; the stroke stops part-way on a scaled path). `overlay_gate` `caption shape`
  honours explicit `qa.json` limits when both `caption_max_words` and `caption_max_chars_per_line` are set (a lane
  regrouped into whole clauses owns its shape; the 92 % pixel width stays the hard limit). → `references/text-fit-and-draw-on.md`
- **Cue sync.** New `audio/cues_check.py`: every placed SFX is located in the finished audio by high-passed cross-correlation
  inside ±50 ms of its planned start (sub-sample peak); over 1 ms fails, no prominence = not found, a riser is measured on
  its landing. `sfx_gate` gains `cue sync` (`qa.json cue_tol_ms`). `sfx_place.py` snaps UNANCHORED sync points (flash,
  impact, chapter, climax, reveal with no `snap` key) to the nearest beat within half a period on a rhythmic grid;
  `snap: false` opts out; block landings and seams never move; the word guard still runs after. → `references/cue-sync.md`
- **Limiter latency fixed.** The first thing `cue sync` found on the finished sample: every SFX read +4.98 ms late (peak 0.96) —
  the mastering limiter's 5 ms attack is a look-ahead buffer that delayed the whole mix by 239 samples, voice included.
  `build_film.py` now trims that latency off the front of the mix (`LIMITER_LATENCY_S`), so the narration clock and the picture
  agree to the sample.
- **Motion blur by accumulation.** `render_frames.js --shutter <deg>` (or `RENDER_SHUTTER`; default off): inside windows where
  `out/qa/camera_measured.json` (or `RENDER_SHUTTER_WINDOWS`) shows the picture moving > 3 stage px per frame, k = min(48,
  2·⌈flow/3⌉) real sub-frame seeks spread over the shutter angle are averaged by ffmpeg `tmix` (integer, deterministic);
  receipt `shutter: {deg, windows, frames_accumulated}`. Measured: a 1 s pass with one 0.3 s window accumulated 10 frames
  at k = 8. → `references/motion-blur-shutter.md`
- **Four tones + speed contrast.** `design.md tones: {black, mid, live, warm}` and `skin_gate` `palette tones` (roles present,
  luma order black < mid < live/warm, two saturated accents ≥ 30° apart); `motion-doctrine.md` Part 4 gains the speed-contrast
  rule (product 1.3–1.5×, people ~0.8×, slowest ≈ 3× the fastest) and `motion_diag` `seq quantized` prints every real-motion
  shot's playback rate (WARN outside 0.5–2.0× or all equal). → `references/palette-tones-and-speed-contrast.md`
- **Shot spec.** `shots.js` per-shot `spec: {forbidden, claims, references}` rides into `out/timeline.json`; new
  `gates/spec_gate.py`: `spec forbidden` (three frames per shot OCR'd, confusion-tolerant whole-word match), `spec claims`
  (figure id / claim id / verbatim phrase in claims.json), `spec references` (WARN: unlogged in refs.json). The sample's
  answer shot carries one. → `references/shot-spec.md`
- **Pilot.** New `tools/pilot.py A B --shots 3-6 | --windows | --from-renders`: the same shots from two scene variants (or
  `?skin=` variants) rendered, cut as sequences with the film clock burned in, stacked A over B at 960×1080 → `out/pilot.mp4`
  + `pilot_sheet.jpg` + `pilot.json`; drawtext uses an explicit font file (Windows ffmpeg has no fontconfig). → `references/pilot.md`
- **Lessons and decisions.** New `tools/lessons.py` (17 steps: cause, rule, kept manual; `--md` writes the SKILL.md table);
  `build_film.py` prints a stage's lesson under its header; `export.py share_pack` adds *Decisions kept manual* to
  `DELIVERY.md` (final length, cut points, speeds, holds, take, reviewer notes, frame approvals, sign-off — read from the
  project files). → `references/lessons-and-decisions.md`
- **Probe fallback everywhere.** `gates/canary.py` and `gates/_receipts.py` (and so `snapshot.py`) carry the same capture
  probe as the renderer: a 30 s race on a plain page, then a relaunch without the compositor-sync flags when it hangs;
  `RENDER_COMPOSITOR_SYNC=0` is no longer needed by hand. Receipts record `compositor_sync`.
- **Render hardening.** `render_frames.js` launches Chrome with `protocolTimeout: 900000` and probes one capture on a plain
  page before the render: on Chrome 154 the compositor-sync flags (`--run-all-compositor-stages-before-draw` …) make
  `Page.captureScreenshot` wait forever (measured: a one-frame probe hung past 150 s with the flags, 2.3 s without, same
  scene, same machine), so a probe that hangs 30 s kills that Chrome and relaunches without the flags — the receipt carries
  `compositor_sync: on | off (fallback …)` and the console says so. The first-frame settle loop waits two animation frames
  before each capture like the per-frame path. `gates/canary.py`, `snapshot.py` and `_receipts.py` still take the flags from
  `RENDER_COMPOSITOR_SYNC` as the default and fall back the same way (see *Probe fallback everywhere*).
- **Docs and flow.** SKILL.md gains the v5.1 table and the extended flow; `/new-film` walks start/end/hold lines, the
  cut list, the pairs, the approvals and the whole-cut notes; `qa-gates.md`, `brief-storyboard-review.md`,
  `review-pack-and-studio.md` updated. Selftests: `storyboard.py`, `snapshot.py --selftest --pairs`, `review_pack.py`,
  `hold_gate.py`, `seam_gate.py`, `review_notes.py`, `cutlist.py`, `export.py` — all synthetic, none launch a browser.
- **Credit.** Unchanged and mandatory: "Crafted with FDE Demo Builder · by Ahmed Awan" on every output and every export.

## 5.0.0 — The picture layer

v5 keeps everything v3 and v4 do and adds the layer the viewer actually sees, every line of it our own: GSAP
timelines on the narration clock, kinetic type, WebGL transitions in declared windows, 3D titles, story blocks,
light / depth / annotation / glass, reveals, a redrawn cursor and camera from telemetry, idle detection, an OCR
leak gate, karaoke captions, staging and reflow, brand kits and ten skins, a live studio, a review pack, and
synthesized sound. Nothing needs an account or a cloud; libraries come from npm and pip under their own
licences (NOTICE.md). Product pixels are never recoloured; effects cross footage only inside a seam window
≤ 0.5 s. Read `references/picture-doctrine.md` first.

- **Render.** `render_frames.js` defaults to Chrome's software GL path (`--use-gl=angle --use-angle=swiftshader
  --enable-unsafe-swiftshader --disable-gpu`): WebGL2 present, a DOM shot in **80 ms vs 157 ms** on the laptop GPU
  path, **120/120 frames identical** across two three-worker renders, hardware and software frames differ on every
  frame so they are never mixed; `RENDER_GL=hardware` for previews. Compositor-sync flags on by default
  (`RENDER_COMPOSITOR_SYNC=0` opts out). The first frame is captured until two captures agree (local fonts paint up
  to ~1 s late). After every step the renderer waits two animation frames before the capture (the compositor must
  commit and activate the step's writes — without it two 3-worker renders of the finished sample differed on
  98/1099 frames under load; with it 0/1099, two renders running concurrently). The multi-worker join states each
  part's `duration`, so the master is exactly CFR (`avg_frame_rate 30/1`; before, every chunk boundary slid
  0.33 ms early). The receipt carries `gl` and `gl_renderer`; `canary.py` and `doctor.py` use the same path.
- **Motion and type.** `lib/motion.js` (`MOTION.block / seek / onSeek / set / rng / arrive / leave / cascade`): paused
  GSAP timelines set per frame; one ease table shared through `grammar.js`. `lib/typo.js`: centerBuild (run / slot),
  match-cut swap, stagger 0.06 s × 0.84ⁱ ≤ 0.5 s, scramble (0.6–1.0 s, 15 glyph changes/s, seeded), slam 1.12 → 1 in
  0.165 s, shimmer, heroWord, fit, lockup (rule draws 0.5 s); size tokens 64 / 44 / 32 / 22 at 720p with the label
  token at 16 (16–18) — one legibility floor across the plugin: labels 16 stage px (24 px at 1080p), body 18,
  headline 40, in `design.md → scale`, `typo.js`, `text_gate` and every reference.
- **GL transitions.** `lib/shaders.js`: chromaSplit 0.35 s, warpDissolve 0.5, lightLeak 0.7 between cards (0.5 s,
  `split 0.15`, intensity 0.6 when a side is footage — ≤ 2 frames of visible tint on product pixels), flashWhite
  0.28, iris 0.6 between cards (0.5 s next to footage), slitScan 0.45, crossWarp 0.5; passes vignette, grain (seeded
  by frame index), bloom, chromatic aberration; `GL.pass` refuses footage textures and `GL.cutTransition` refuses a
  window > 0.5 s with footage on either side; the texture cache is keyed per picture (`currentSrc`), not per
  element. `seams.json` gains `type: gl` rows (dur 0.1–0.5 s, `split`), `SEAM.glSeams()`,
  `out/timeline.json → glSeams`; `seam_gate.py` measures them (brightening kinds exempt from the flash check).
  Mixing in encoded space: u = 0 / 1 byte-exact; the 120-frame GL mini scene renders byte-identical.
- **3D titles.** `lib/title3d.js` on three (ESM, imported from `node_modules`) + d3-delaunay: shardTitle (Voronoi
  glass panes, fly-in 2.3 s / hold / fly-out 2.4 s), portalTitle, depthStack (footage cards billboarded, never
  tinted). Measured on software GL at 1080p, ms/frame above the DOM baseline: shard 4× MSAA **105** (default),
  no AA 70, post AA 121, 2× SSAA 257, physical transmission 1390 (hardware only); portal 82; stack 135.
- **Story blocks, charts, comparisons.** `lib/blocks2.js`: countUp (1.72 s, pulse 1.07 / 0.165 s), decisionCard (types
  in 0.9 s, seal from 1.35), receipt (2 % snap), twoLayers, sceneCards (period 3 s, `cutAt` 0.33 s hook), chatReveal,
  approvalCard, flash — every block `land()`s on a word and publishes `sync()`. `lib/charts.js`: bars / line / kpiTiles /
  race / donut take `claim:` ids only, grow from the baseline 0.6 s / 0.06 s stagger, sit on a plate; `--check` fails
  an untraceable id. `lib/compare.js`: split, wipe (0.9 s), PiP at 28 % — both halves pixel-exact. `lib/blocks.js`
  lockup / kpi / flash delegate to the new libs.
- **Light, depth, annotation, glass.** `lib/light.js` bloom (peak .30, ceiling .45, blur 28 fixed), leak (≤ 0.5 s, seam
  window required), sweep 105° / 0.9 s, rim; `lib/depth.js` planes (rates .2 / 1 / 6, one occluder crossing) and dolly
  (perspective 1200, near 1.175×, far 0.909 → 0.975); `lib/annotate.js` circle / arrow / box / underline / strike with
  a 3-frame boil, spotlight glide 0.8 s, label — projected through the camera pose; `lib/glass.js` panels (blur 26 px
  fixed, ≤ 2, never on the caption lane). Measured: one panel + bloom + spotlight + leak ≈ 1.2 s/frame at DPR 1.5.
- **Reveals.** `lib/reveals.js`: heroDive (.62 → 1, 0.9 s), pullBack, assemble (6000 → 103x58 cells, landed by 90 %),
  irisFrom, lightWipe, matchCutHandover — each ending on the exact frame the footage lane takes over.
- **Recording-native.** `tools/record_events.py` (60 Hz pointer + keys, F8 clap flash, align within one video frame),
  `tools/cursor_track.py` (signed-gradient templates + background model; **96.7 % within 6 px** on the synthetic tape,
  ~50 % on a fast real one → proposal grade, sheet mandatory), `tools/camera_from_events.py` (islands ≤ 1.2 s / 220 px,
  ladder 1.0 / 1.35 / 1.6 / 2.0 under the upsample budget, pushes snap to word onsets ±0.4 s), `lib/cursor.js`
  (12x19 arrow at 1.75×, ring 28 → 64 px / 0.32 s), `lib/hud.js` (keycap pill at bottom 170). `tools/idle_detect.py`:
  change energy measured on 409 s of real recordings (static 0.00–0.11, scroll 0.25–3.2, action 0.6–12, page change
  36–158); idle / spinner / typing / scroll / page → cuts, ramps (6× / 4× / 1.6× / 2×), caret follow, `working` hook;
  `--exit-zero` for scaffold use.
- **Privacy.** `gates/leak_gate.py` (gates `leaks`, `leak ocr`): OCR (winocr **0.3–0.5 s/frame** on Windows vs 25–40 s
  for the bundled model → winocr preferred on win32), identifier patterns tolerant of OCR confusions, fuzzy
  denylist from `BRIEF.md → ## Never on screen` (1 edit per 8 chars), account-badge detector (16–72 px, top 20 %,
  right 30 %, contrast ≥ 24, inside-corner test); results cached and byte-identical. `tools/mask_propose.py`:
  radius `max(6, ceil(0.45 × text height))` (< 1 % gradient energy left; neither engine reads it), `--verify`, `--apply`.
- **Captions and chapters.** `karaoke` (attack 0.12 s, pulse 1.06, rest 0.82 / future 0.55, bold cross-fade without
  reflow) and `kinetic` (waterfall ≤ 0.3 s, lead 0.3 s) styles; `tools/captions_ass.py` writes .ass (`\k` per word,
  PlayRes 1920x1080) + .srt + .vtt from one groups file, per-word overrides (`phase:i`), `--burn`;
  `tools/chapters.py` (starts snap to cuts within 0.75 s, ≥ 10 s, ≤ 40 chars, `--merge` under 60 s).
- **Staging and reflow.** `lib/stage.js`: wallpaper + frame (k = 0.775 at padding 64 with a window bezel),
  `stage.pose()`, `stage.full()`; `--reflow 9:16 | 1:1 | 4:5` (τ 0.6 s, 18 % dead zone, ≤ ~53 px/frame) with per-format
  safe zones; `export.py --reflow` and a `portrait_4x5` preset.
- **Look and review.** `tools/brand_kit.py` (Lab k-means k = 6, WCAG floors ink 7:1 / 4.5 / 3, type by mood, motion
  profiles calm / medium / high, 2000x912 sheet, `check`), ten skins in `skins/` with sheets, `tools/skin_apply.py` +
  `?skin=`; `tools/review_pack.py` (one offline HTML ≈ 52 KB + 25 KB/frame, honesty flags, comments, `--serve`,
  `--lock` writes the sign-off into `## Locked`); `tools/studio.py` (any frame < 1 s, hot reload 0.03–0.4 s after a
  write, **T** = a 1920x1080 tap through the real renderer ≈ 4 s, **Q** = quick lint, `--manifest`, `--selftest`).
- **Audio.** `audio/carve_bed.py` rewritten: fifteen third-octave bands 200–5000 Hz, speaking-frames spectrum,
  benefit = audibility(snr + cut) − audibility(snr) weighted by speech presence, ranked against the real bed at its
  mix gain (pink reference without one). **Profile numbers changed:** strength 0.5 = 9 dB in 4 bands, Q 2.0, duck 10,
  headroom 12 (was 10 dB / 4 / Q 1.7 / duck 12); 0.25 = 6 dB / 2 bands; 0.8 = 12.6 dB / 5 bands (was 14.8 / 6); 1.0 = 15 dB
  / 6 bands / Q 3 — hand-tuned films carve slightly shallower. `audio/beat_grid.py` rewritten: log-compressed
  half-wave spectral flux, interval histogram folded over subdivisions + autocorrelation octave, weighted
  least-squares grid (downbeat error 7 ms, residual 19 ms on synthetic drums), −45 dBFS silence gate. New:
  `audio/sfx_synth.py` (13 sounds at −6 dBFS, md5 manifest), `audio/sfx_place.py` (seams → whoosh, one impact per act,
  word guard 0.15 s, bus −14 dB → cue peaks −20 dBFS), `audio/fx_chain.py` (voice-booth with a built de-esser: 5–8 kHz
  −2.5 dB for −0.2 LU; bed-under-voice; sfx-tight), `audio/envelope.py` (breathe −3 dB at seams, swell under the riser,
  ≤ 6 dB/s, gain WAV).
- **Gates and lint.** `qa_film.py --profile picture | full`, `out/qa_report.json`. New gate modules: `leak_gate`
  (leaks, leak ocr), `sfx_gate` (word-safe, one impact, level), `reveal_gate` (handover, join, sampled), `chart_gate`
  (claims, figures), `annotate_gate` (annot evidence, annot ink, glass budget, light leak), `skin_gate` (skin check,
  skin tokens, review lock); `seam_gate` gl rows;
  `canary` seek parity hashes PNGs inside one page (framemd5 of separately encoded chunks differs by codec noise).
  `lint_scene.py`: node_modules libraries are known and unlinted, `timeline_autoplay` (GSAP on the global clock,
  `gsap.ticker`, `.play()/.resume()`, `repeat: -1`), relative `import()` of three allowed, remote refs still errors,
  finishing never on the footage lane, one GL owner per scene.
- **Consolidation.** One ease table (`grammar.js`), one seam registry (`seams.js`: transform | css | gl backends),
  `vfx.js` keeps grain / vignette / bloom / haze / matte / ramp and hands transitions to `GL`; idle rules scoped to
  `#clipWrap` (footage never wobbles; recreated layers never freeze); `footage.js` `imageFor / preload / srcFor`.
- **Scaffold and docs.** `/new-film`: BRIEF → look pass → STORYBOARD → sketch → lock → build → QA → studio taps →
  review pack → export; `npm i puppeteer gsap three d3-delaunay`; optional OCR extras in `requirements.txt`.
  New references: picture-doctrine (entry point), motion-and-typography, gl-transitions, titles-3d, story-blocks,
  light-depth-annotation, reveals, recording-native, privacy-leak-gate, captions-karaoke-chapters,
  staging-and-reflow, brand-kits-and-skins, review-pack-and-studio, audio-fx-and-sfx, qa-gates. SKILL.md rewritten
  as viewer-visible devices with gates as footnotes. NOTICE.md lists third-party libraries only. `requirements.txt`
  lists scipy as a hard dependency (sfx_synth, fx_chain, cursor_track, idle_detect, the leak gate's avatar detector)
  and `doctor.py` checks it; `winocr` is the preferred OCR engine on Windows (60–100× faster than the bundled model
  at equal recall), rapidocr elsewhere. `/new-film --template booth-trailer | customer-story | feature-walkthrough`
  copies a film template over the defaults.
- **Verified fixes (three adversarial reviews of the finished build).** Determinism: the two-animation-frame capture
  settle and the exact-CFR concat list above; `canary.py` snaps every time to the exact frame (`round(t·fps)/fps`,
  six decimals — a 3-decimal snap reported a phantom 43 dB seek-parity failure on a gliding title) and mirrors
  the renderer (explicit FontFace loads, first-frame settle, two-rAF wait); `will-change` removed from
  `glass.js`, `depth.js`, `light.js` and `annotate.js` (a settling glass panel differed on 46/76 frames run to run
  with the hint, 0/76 without) and refused by the new lint rule `will_change_layer` in scenes and libs;
  `typo.js` slam / heroWord pivots written through `MOTION.set` (a bare `gsap.set` never renders under the paused
  clock); the typewriter caret's border reset on every caption rebuild; `GL.texture` cached per picture. Hygiene:
  scipy in `requirements.txt`; `carve_bed.py` runs ffmpeg through a bounded wait with a retry (ffmpeg 8.1 spun
  forever on the asplit → sidechaincompress + acrossover + amix graph in 3 of 15 launches; the hung child is killed);
  `tools/storyboard.py --selftest` fixture realigned to the template's 32.3 s beats; lint allows exactly gsap /
  three / d3-delaunay from `node_modules`. Craft, on the sample: the ask beat stays unstaged with a shallower push
  (×1.25) and a tight spotlight (dim .22, clear 0.8, opaque 0.98) and its typed question is no longer captioned
  twice; the light leak into the close is tamed (`dur 0.4–0.5, split 0.15`, intensity 0.45, accent + ground
  colours, never gold over the answer still); `countUp` lands directly on its spoken number instead of counting
  0 → 1 → 2 → 3; glass panels get a `page` fill for white product pages (`rgba(5,22,28,.34)`); lower thirds lose
  the accent stripe, the 14 px radius and the drop shadow (design tokens: radius ≤ 4, no shadow); every label,
  kicker and chat line sits at or above the 16 px floor; the title card keeps one hue (no gold halo over a coral
  plane); the close card holds while the credit lands — `build_film.py` renders END + 3.6 s (`TAIL`, was 1.2).
- **Final-check fixes (fourth review).** Run-to-run determinism: the glass `page` panel no longer carries a backdrop blur (a backdrop root re-rasters the footage beneath it history-dependently — 62/1171 frames differed between two concurrent 3-worker renders, 0 without; `dark`/`light` keep the frost via `.frost`, for recreated cards only). `build_film.py` runs `captions.js` before the luma probe and again with `--luma`, so bright product pages get dark-ink captions and charcoal lower thirds (the probe used to run before any caption group existed). `qa_film.py` duration tolerance follows `TAIL` (3.6 s closing hold). The Send click's cursor ring + spotlight release are declared in `qa.example.json motion.allow`; the opener reveal registers a ledger row so `reveal_gate` measures it instead of passing on an empty list. Self-test fixtures repaired: `snapshot.py` (6-decimal probe keys), `storyboard.py` (35.4 s template clock), `review_pack.py` (tap by time). Sample craft (round 2): ask beat full screen then ×1.15 with a tight spotlight and no duplicated caption; page call-out rgba(5,22,28,.86) beside the boxed row; `countUp mode: 'land'`; title inked on the cut frame; lockup kicker; lower thirds without stripe/radius/shadow; label floor 16 px everywhere; receipt pill under the answer card; chat card grows from the composer; `ink` caption pill .92.
- **Credit.** Unchanged and mandatory: "Crafted with FDE Demo Builder · by Ahmed Awan" on every output and every export.

## 4.0.0 — Production craft

v4 keeps everything v3 does and adds the craft that turns a clean demo into a film people remember, built for our
real-pixel, narration-is-the-clock pipeline. Everything still renders on your laptop; nothing needs an account or a cloud. The fictional "Acme Console"
sample passes all 51 gates end to end (`make_sample_recording.py` → `build_film.py` → `qa_film.py`).

- **Motion and seams.** `lib/seams.js`: velocity-matched seams (cut-the-curve, zoom-through and its inverse, waterfall,
  nudge/whip, rack-focus), waterfall entries, carriers. A `seams.json` ledger declares each cut; `gates/seam_gate.py`
  measures the rendered frames and fails any cut that stops early, mirrors direction, dissolves, or flashes white.
- **Camera.** `lib/camera.js`: punch-in/out, zoom-out reveal, focus pull, caret-follow, dolly zoom, pose ladder, drift-to-
  zero. `gates/motion_diag.py`: per-shot camera curves, zoom budget (≤ 88 % of frame, ≤ 2× source pixels), onion-skin sheet.
- **Captions and overlays.** `lib/captions.js`: a burned-in caption lane on the narration's own word times (drop / rail /
  embed, eight corporate presets, fit-text) that matches the SRT. `lib/overlays.js`: lower-thirds, stat cards, hero word,
  pull-quote, PiP frame, lockup, CTA close. `gates/overlay_gate.py`: safe zones, clipping, collisions, caption shape.
- **Audio.** `audio/carve_bed.py`: the bed ducks only in the bands the narration occupies; mono→stereo pan fix (+3 dB that
  `aformat` silently lost). `audio/voice_presets.py`: clean / broadcast / warm / telephone / PA chains and per-phase level
  match. `audio/beat_grid.py`: beats.json from a bed so cuts land on bars. `gates/audio_gate.py`: voice-over-bed ≥ 12 LU,
  duck depth, even voices, true peak.
- **QA and determinism.** `gates/lint_scene.py` (wall-clock code, CSS transitions, unseeded random, remote refs, fonts),
  `gates/canary.py` (render twice, compare hashes), `gates/snapshot.py` (golden frames + diff contact sheet),
  `tools/doctor.py` (ffmpeg / Node / Chrome / edge-tts / fonts / RAM / disk preflight, `--json`), `tools/fonts_localize.py`,
  `tools/audit_text.js` (overflow + WCAG contrast). Gates are plug-ins (`gates/*.py`, `GATE_NAMES` + `run(ctx)`);
  CREDIT always runs last and cannot be disabled.
- **Planning and review.** `templates/BRIEF.example.md` + `tools/brief.py` (message, audience, destination, what is real,
  stated-vs-inferred), `templates/STORYBOARD.example.md` + `tools/storyboard.py` (beat arithmetic against the narration,
  truthfulness tag per beat, storyboard.html sketch sheet), `templates/design.example.md`, `gates/text_gate.py` (words per
  second and per beat, on-screen text budget, hooks that open with table names).
- **Blocks.** `lib/blocks.js`: chat reveal with human typing rhythm, count-up that lands on the spoken number, state rail /
  HUD / agent tag, flash cut and freeze dressing, title lockup and dead-still close, focus zoom + click ring, the shared
  elastic envelope.
- **Media and export.** `tools/ledger.py` + `gates/ledger_gate.py`: every asset's source and licence in `media.jsonl`;
  the render refuses remote URLs. `tools/export.py`: booth loop, LinkedIn, YouTube, vertical, square, GIF teaser and a
  share pack from one master, each re-checked for the credit. `tools/timeline.py`: human-readable timeline.
  `templates/skin_tokens.example.json`: brand tokens for re-skins.
- **Finishing.** `lib/vfx.js`: vignette, seeded grain, bloom, matte reveal, haze — recreated scenes only. `tools/grade.py` +
  `gates/grade_gate.py`: levels/cast normalisation that proves product pixels were never recoloured.
- **Extractor.** Per-clip `"file"` (films that cut between recordings), `"fps"`, `"width"`, `--out`; `play.map` speed ramps
  in the footage lane.
- **Credit.** Unchanged and mandatory: "Crafted with FDE Demo Builder · by Ahmed Awan" on every output and every export.

## 3.0.0 — Production films

**New: v3 film workflow** (`/fde-demo-builder:new-film`, `scripts/film/`)
- **Real-pixel footage engine** (`extract_clips.py` + `lib/footage.js`):
  - Per-pixel median stills remove the pointer.
  - Tall pages are stitched from parked scroll positions, drawn inside the app's own full-screen chrome, with one chrome frame per position.
  - Real 30 fps motion clips.
  - Baked-in recording zooms can be inverted.
  - Demo-authored words can be repainted (auto cap height, ink and background).
  - `--word-ends` measures typed lines.
- **Original screen first, then the zoom**: each shot can open on the full screen with `establish` and push into your framing. `FOOT.fullscreen()` maps edits written in cropped views, and `abs` moves pull back to the whole screen.
- **Real typing and streaming**:
  - Typed glyphs are uncovered word by word on the narration clock, handing off seamlessly to the real send frames.
  - A curtain effect streams answers in.
- **Narration as the clock**: `lib/timeline.js` provides `wt(phase, word)`, and `check_cues.js` fails on any cue that doesn't resolve.
  - `gen_vo_multivoice.py` now emits a node timing twin.
  - It also supports `pad` (lead-in before a phase) and `pause` (silence after one).
- **Deterministic renderer** (`render_frames.js`): frame by frame, multi-worker, decode-aware `__seek`/`__step`, CFR, and frame 0 equals clock 0.
- **Build** (`build_film.py`):
  - Music bed sidechain-ducked under the voices, plus optional SFX.
  - Two-pass *linear* loudnorm to −16 LUFS / TP −1.5; the build refuses to ship if loudnorm falls back to dynamic.
  - Captions.
  - Mandatory credit.
- **14 QA gates** (`qa_film.py` + `qa.json`):
  - Relative cut detection, blank-after-cut, and freeze over 5 s measured at 640×360.
  - Loudness.
  - Required lines, over-claims (rendered text only), identifier hygiene.
  - Claims traced to the screen (`claims.json`).
  - Captions and CREDIT.
- **Runnable out of the box**: `make_sample_recording.py` generates a fictional "Acme Console" capture. The example film passes all 14 gates.
- **New references**: `real-pixel-footage`, `deterministic-render`, `cinematic-grammar`, `honesty-audit`, `audio-mix`, `credit-footer`.

**New: mandatory end-screen credit** (all workflows)
- `credit.py` stamps **"Crafted with FDE Demo Builder · by Ahmed Awan"**:
  - Small and centred in the footer.
  - Shown over the last 4 s, with a fade-in.
  - Automatically light or dark to suit the end screen.
- It also verifies the stamp by correlating the end frame against the credit's glyphs.
- The stamp and check are wired into v1 `build.py`, v2 `assemble.example.sh` and v3 `build_film.py`. The `CREDIT` QA gate and the `demo-qa-reviewer` agent treat a missing credit as a BLOCKER.

**Changed**
- Privacy guidance: mask private data, not the product. Ask before masking code.
- `requirements.txt` adds `pillow` and `numpy`.

## 2.0.0 — Story rebuilds
B-roll story scenes and multi-voice narration (`gen_vo_multivoice.py`, `render_scene.js`, `shot.js`, `/new-broll`).

## 0.1.0 — First release
Beats, lag cutting, privacy scrubbing and VO sync (`demo_config.py`, `gen_vo.py`, `build.py`), `/new-demo`, and the `demo-qa-reviewer` agent.
