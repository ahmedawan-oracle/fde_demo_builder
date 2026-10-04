# QA gates — the index (`qa_film.py` + `gates/*.py`)

`qa_film.py` runs its built-in picture and sound checks, then every `gates/*.py` module (`GATE_NAMES` +
`run(ctx) → [(name, ok, detail)]`), and **CREDIT last — it cannot be disabled**. `--profile picture` is the
default fast set (12 picture gates: cuts land, blank after cut, freeze, loudness, captions, CREDIT, lint,
determinism, seams move, zoom budget, contrast, claims traced); `--profile full` runs every module. The
verdict is printed; `out/qa_report.json` repeats it for the review pack. A broken gate is a failed gate,
never a skipped one. Measure a failing gate before loosening it.

## Built in (v3)

container · duration vs narration · open frame · black frames · cuts land (relative) · blank after cut ·
no freeze > 5 s (640x360) · loudness −16 LUFS / TP ≤ −1 · required lines · no over-claims (rendered text) ·
hygiene patterns · claims traced to the screen (`claims.json`) · captions · **CREDIT**.

## Modules

| module | gates | reference |
|---|---|---|
| `seam_gate` | seam ledger · seams move · seam flash · stage ground · idle wobble; `type: gl` rows measured in their window, brightening kinds exempt from the flash check | motion-doctrine, gl-transitions |
| `motion_diag` | motion traced (+ WARN single-frame spikes) · zoom budget (≤ 1.6 warn, ≤ 2.0) · seq quantized (+ per-shot playback rates, the speed-contrast ladder) · onion sheets; flags `--spikes` · `--pan-halves` · `--roster` | camera-moves, motion-scans, palette-tones-and-speed-contrast |
| `hold_gate` | hold declared (0.3–0.95; required on recreated beats unless waived in writing; forbidden on footage match-cuts) · hold still (≤ 1.0 % change per 0.1 s inside the hold window; WARN when nothing moved before it) | hold-doctrine |
| `look_gate` | look types (every beat resolves to a `design.md looks:` type) · look effects (no forbidden effect on a look's selectors in authored CSS / VFX / GL calls, none named in a beat's motion/screen) | looks-per-shot-type |
| `pair_gate` | pair anchors (top-band ink boxes within 2 px at 1080p start → end) · pair words (end-frame OCR words ⊆ end: ∪ quotes ∪ claims) · pair roster (newcomers named in end:); OCR gates WARN-pass without an engine | pair-gate |
| `overflow_gate` | text overflow (every second, every visible text box: scroll box ≤ client box + 3 px; icon labels, headline rounding and the stage excluded; needs the browser) | text-fit-and-draw-on |
| `identity_gate` | identity frames · identity colour (untouched shots across a cut-list bump: same frame count, mean colour ≤ 0.5 ΔE per frame vs the previous render) | identity-and-bump |
| `overlay_gate` | overlays safe · caption shape (explicit qa.json limits when both caption keys are set) · caption timing · caption contrast · hero scarcity | captions-and-overlays, text-fit-and-draw-on |
| `audio_gate` | voice over bed ≥ 12 LU · duck depth · duck breathes · voices even · true peak · mono upmix | audio-carve-and-beats |
| `lint_scene` | lint (0 errors on scene + libs) · text layout · contrast; node_modules libraries are known and unlinted; `timeline_autoplay` forbids GSAP on the global clock; `will_change_layer` forbids `will-change` in scenes and libs; `dash_nonscaling_stroke` forbids non-scaling-stroke on a dashoffset draw-on | lint-and-determinism, text-fit-and-draw-on |
| `canary` | determinism (two cold renders identical, same `gl_renderer`) · seek parity (cold == stepped at the exact frame time; PNG hashes inside one page; probe waits two animation frames before each capture like the renderer) | lint-and-determinism |
| `snapshot` | golden (per-shot frames vs `golden/`) | lint-and-determinism |
| `text_gate` | text budget · narration pace · brief message · design tokens · lazy defaults | brief-storyboard-review |
| `grade_gate` | ui colour truth · effects off footage (no `VFX.*`, `GL.pass`, `GL.chain` or CSS filter on the lane) | vfx-and-grading |
| `ledger_gate` | media ledger · licences · no remote refs · frozen local · credit font | media-ledger-and-export |
| `leak_gate` | leaks (OCR + patterns + fuzzy denylist + account badge on every footage file) · leak ocr | privacy-leak-gate |
| `chart_gate` | chart claims (every `claim:` id resolves in `claims.json`, `node lib/charts.js --check`) · chart figures (every rendered figure equals its claim) | story-blocks |
| `annotate_gate` | annot evidence (a mark sits on a claim figure or a logged click, ≤ 2 strokes at once) · annot ink (never across product text) · glass budget (≤ 2 panels, never on the caption lane) · light leak (≤ 0.5 s, inside a seam window, bloom ≤ .45) | light-depth-annotation |
| `reveal_gate` | reveal handover (`end` / `at` equal a shot boundary, integer frame) · reveal join (≤ 1 luma level across the hand-over pair) · reveal sampled (no tainted-canvas fallback) | reveals |
| `sfx_gate` | sfx word-safe (no transient within 0.15 s of a loud word onset) · sfx one impact (one impact-low per act) · sfx level (stem peak −24…−16 dBFS, +0.1…3 LU on the bed) · cue sync (every placed sound located in the finished audio within 1 ms) | audio-fx-and-sfx, cue-sync |
| `skin_gate` | skin check (`brand_kit.check_skin` on the active skin) · skin tokens (the scene reads the 16 token ids) · palette tones (`design.md tones:` black/mid/live/warm in luma order, two accents ≥ 30° apart) · review lock (`## Locked` carries a sign-off) | brand-kits-and-skins, palette-tones-and-speed-contrast, review-pack-and-studio |
| `spec_gate` | spec forbidden (OCR of three frames per shot vs the shot's `forbidden` list) · spec claims (every promised figure in claims.json) · spec references (WARN: unlogged in refs.json) | shot-spec |

Every module answers `--selftest`; `tools/doctor.py` runs the environment preflight before any of them.

## The rules the gates encode

- Footage is never recoloured, filtered or displaced outside a declared window ≤ 0.5 s; every product beat
  opens full screen then zooms; masks are small soft blurs.
- Every spoken or drawn figure is a claim; charts show only claims; marks sit on a claim figure or a logged click.
- Nothing private is on screen; nothing remote is loaded; nothing moves on the wall clock.
- One group of captions at a time, inside title-safe, never over product text, never over the credit.
- Sound never lands on a word; one impact per act; the bed breathes at seams.
- The plan is locked, every END frame approved, and the review signed before the render that ships.
- A recreated beat moves first and then holds; a footage match-cut carries motion through the cut.
- **"Crafted with FDE Demo Builder · by Ahmed Awan"** is on the end screen of every output and every export.
