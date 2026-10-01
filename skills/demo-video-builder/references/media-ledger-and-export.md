# Media ledger, export presets, timeline printout, skin tokens (v4 — media area)

Four tools and one gate module answer the questions a booth film gets asked after it is built: *where did
that music / font / clip come from, can we show it; give me the LinkedIn cut; show me the edit before you
render; make the same film in the day-time skin.* Everything is fictional in the examples ("Acme").

## 1. The media ledger — `tools/ledger.py`, `media.jsonl`, `media_index.md`

One append-only JSONL file per film, keyed by path: the **last record for a path is the file's record**, so a
rejected version's history survives and nothing is ever deleted. `media_index.md` is a regenerated table.

| field | meaning |
|---|---|
| `id` | `<kind>_NNN`, zero-padded to 3; an asset keeps its id when it is re-registered |
| `kind` | `music` · `sfx` · `footage` · `image` · `font` · `voice` · `deliverable` (written by export.py) |
| `path` | POSIX, project-relative; footage folders end with `/` (`broll/nb/`) |
| `sha256`, `bytes` | of the file, or a digest over every file of a footage folder — a re-trimmed bed is **stale** until re-added |
| `probe` | ffprobe facts: `duration` rounded to 0.1 s, `width`/`height`, `codec`, `sample_rate`, `channels` (QA keeps timing from `vo/<name>_phases.json`) |
| `source` | `{kind: recording · extracted · generated · licensed · bundled · existing · derived, url, recording, window, provider}` — e.g. `extracted recording.mp4 14.60-15.10 s (median n=3)` |
| `licence` | `{name, url, attribution, commercial_ok}` — `UNKNOWN` until a human fills it in |
| `added_by`, `date`, `used_in` | who, when (UTC), which deliverables mixed it in |

Measured rules kept from the HyperFrames media-use ledger: append-only / last-wins, `<type>_NNN` ids, 0.1 s
duration rounding, a lock file with a **15 s stale-steal and 20 s timeout**, malformed lines skipped (never fatal),
index regenerated after every write. Our addition is the licence block — their ledger recorded provider and
prompt but kept rights in a separate credits file, which is exactly the gap a booth film cannot afford.

```bash
python tools/ledger.py adopt                   # walk vo/ broll/ music/ sfx/ assets/ fonts/ images/ + recording.mp4 + vo_<name>.mp3
python tools/ledger.py add music/bed.mp3 --kind music --licence "Example Music Library Standard Licence" \
       --licence-url https://music.example.com/licence --attribution "Quiet Monday" --commercial-ok yes \
       --source licensed --url https://music.example.com/tracks/quiet-monday
python tools/ledger.py list --unknown          # what still needs a licence
python tools/ledger.py check                   # exit 1 on UNKNOWN or stale sha256
python tools/ledger.py used music/bed.mp3 out/Acme_Monday_Film.mp4
```

`adopt` infers the kind from folder + extension (`vo/`, `vo_*.mp3` → voice; `sfx/`, `/sound` → sfx; other audio →
music; `broll/` images → footage; `.ttf/.otf/.woff2` → font), skips 0-byte files loudly, skips `out/` and
`*.partN.mp4`, and is idempotent. Defaults: footage = "Own recording", voice = "Generated speech (edge-tts)" (voice
name from `vo_script.py`), music/sfx/font/image = **UNKNOWN** so the gate fails until someone records the source.
It never matches assets by fuzzy words — our films name every asset in `film.json` / `clips.json`.

Python API: `Ledger(project, path=None)` → `.records()`, `.current()`, `.get(path)`, `.add(path, kind, licence,
source, description, added_by, used_in, force)`, `.adopt(by)`, `.mark_used(path, film)`, `.unknown()`,
`.check_path(rel) → 'ok'|'stale'|'missing'|'absent'`, `.write_index()`. Helpers: `sha256_file`, `sha256_dir`,
`ffprobe_facts`, `infer_kind`, `licence_ok`, `posix_rel`, `find_project`, `ledger_for(project)`.

## 2. The gate — `gates/ledger_gate.py` (five names, loaded by `qa_film.py`)

| gate | fails when |
|---|---|
| `media ledger` | an asset the film uses has no current record or a stale sha256: `film.json` bed/sfx, `vo_<name>.mp3`, every `broll/<clip>/` and source recording in `clips.json`, local `@font-face` files and `<img>/<video>` sources in the scene |
| `licences` | any music / sfx / font / image record is `UNKNOWN`, empty, or `commercial_ok: false` (a booth is commercial use) |
| `no remote refs` | `src=`, `href=`, `url(`, `@import`, `fetch(`/`import(` point at `http(s)://` or `//host` in the scene, shots or `scenes/lib/*.js` (comments stripped — a licence URL in a comment is fine). A booth laptop without network must render the same film |
| `frozen local` | a relative reference in the scene does not resolve to an existing file inside the project |
| `credit font` | none of `credit.py`'s font candidates exists, so the mandatory credit could not be drawn |

Without a ledger file the first two gates pass **only while nothing licensable is referenced** (the shipped sample:
no bed, no sfx, system fonts) and tell you to run `adopt`; the moment `film.json` names a bed the ledger is required.
Rule for every scene: *everything the render loads is a local file inside the project — a URL is a bug.*

## 3. Export presets — `tools/export.py` (derived from the master, never a second render)

Inputs are `build_film.py`'s outputs: the credited film, `out/master_<name>.wav` (24-bit, −16 LUFS) and the `.srt`.
Outputs land next to the film as `<stem>_<preset>_<YYYY-MM-DD>_<HH-MM-SS>.<ext>` plus a stable `<stem>_<preset>.<ext>`
copy; a run manifest goes to `<stem>_exports.json`. **Every MP4 passes `credit.check` or is deleted**, is probed for
loudness, and (when a ledger exists) gets a `deliverable` record carrying preset, target and measured LUFS/TP.

| preset | destination | what it does |
|---|---|---|
| `booth_loop` | looping booth player | 1.0 s loop pad: last (credit) frame held, dipping to black over the final 0.6 s so the restart lands on the scene's own head fade; silence-padded audio; CRF 17, AAC 192k; also `*_silent.mp4` with no audio stream; prints first/last-frame luma (both near black = seamless) |
| `linkedin` | LinkedIn / Teams post | 1080p H.264 High CRF 18, AAC 192k, faststart, −16 LUFS from the WAV; WARN above 10 min |
| `youtube` | upload | the CRF 17 master picture stream-copied (no generation loss), audio re-mastered to **−14 LUFS / TP −1.5 / LRA 11** (socials target), AAC 256k |
| `vertical_9x16` | phone feed | 1080x1920. `--fill band` (default): picture at 1080 px wide centred inside title-safe over a blurred, darkened fill of itself; `--fill crop`: smart 9:16 crop centred on the picture's edge energy (12 sampled grey frames). Credit re-stamped for the canvas and checked; `*.captions.md` says where burned-in text now sits and where to re-place the SRT; SRT copied beside |
| `square_1x1` | feed | 1080x1080, same two modes, same credit + note |
| `gif_teaser` | PRs, docs, chat | first N s (`--seconds`, default 12) + a 1.5 s hold on the credit frame; 15 fps, 960 px, two-pass `palettegen` → `paletteuse`, no audio |
| `share_pack` | what leaves the project | `<stem>_share_<date>.zip`: film, stable preset variants, `.srt`, `media_index.md`, `claims.json`, generated `DELIVERY.md` (duration, size, loudness, credit, ledger status, feedback wanted); `--with-source` adds the authored set. **Never** `recording.mp4`, `broll/`, `vo/`, `.history/`, `out/seg_*`, WAVs. Refuses on a licence `UNKNOWN` or a `qa.json` hygiene-regex hit in any included text file |

```bash
python tools/export.py --preset linkedin,gif_teaser
python tools/export.py --all --fill crop --seconds 8 --json
```

Re-mastering reuses the build's two-stage trick (pre-gain to +0.45 LU above target + sample-peak limiter 0.8 dB
under the ceiling, then two-pass `loudnorm` with `linear=true`) and its REFUSE rule: a `dynamic` report aborts the
preset. Always from the 24-bit WAV; the film's AAC is used only when the WAV is gone, with a warning. No 4K preset:
product recordings are 1080p and upscaling adds no detail. Finish checklist for any export: watch the file itself,
first and last seconds, the hardest cut, the credit, duration / dimensions / audio, and the versioned filename.

## 4. The timeline printout — `tools/timeline.py`

Static (no browser). Reads `out/timeline.json`, `vo/<name>_phases.json` + `vo_script.py`, a node dump of
`FILM`/`SHOTS`/`HL` from `scenes/shots.js` (same loading as `export_timeline.js`), the `.srt` and `film.json`.

```
timeline 33.23s  (narration 32.03s + tail)
cuts        ···············|······|···········|·····  cuts 12.38 18.62 27.93
footage
  ···············███████··················  shot1         12.38-18.62  s  clip=nb establish scroll×2 moves×1
cards
  ···············████·····················  lower-third   12.68-16.18  s  "THE ANALYST"  dur=default 3.5 s
highlights
  ·····················█··················  late          17.41-18.62  s  cue=nb:counts clip=nb dt=+1.0  dur=inferred (shot end)
captions / narration / audio …
check  coverage gap  OK
check  shot overlap  OK
```

Kinds print in a **fixed order — footage → cards → highlights → captions → narration → audio** — one row per
element by absolute start, a 40-column bar (`█` span, `·` empty) with exact seconds beside it (bars under-resolve a
0.3 s cue; the numbers do not), extras only when present, and a provenance tag on every unauthored duration
(`default`, `inferred`, `media`). One caption track, never one row per cue. "The graphics track has a 2 s hole at
41 s" is how we talk about the edit. Derived checks: `coverage gap` (a moment between `FILM.openEnd` and `FILM.close`
with no shot — positive delta) and `shot overlap` (two non-seam shots sharing time — negative delta); they print
OK/FOUND and `--json` carries them, ready to be promoted to QA gates. `--at 20` lists what plays at 20 s; `--json`
prints `{total, end, cuts, rows[], checks[]}`; `out/timeline.json` itself is never rewritten.

## 5. Skin tokens — `templates/skin_tokens.example.json`

A skin is a flat set of typed slots (`color`, `font`, `number` with min/max/step/unit, `string`, `image`, `enum`),
each with a default, a `role` (style / content / layout) and optional `portrays` tags (`subject_tagline`,
`subject_logo`, `authority_badge`, `host_identity`) so an agent knows which slots carry identity. Every scalar becomes
`--<id>` on the scene's `:root`; strings fill `[data-var-text]`, images `[data-var-src]`. Defaults are the colours
`film.example.html` ships with, so a film without a skin renders unchanged. Precedence (ours): **skin file > batch row
override > authored `:root` values**. Apply before the first `__seek` (`?skin=<json>` on the scene URL; `film.json`
`"skin"` names it). Never tokens: narration text (the clock), fps, 1920x1080, total length, codec, the credit.
Prove a re-skin differentially — a probe skin with paper/ink inverted must change > 5 % of a 160x90 grey still.

Batch re-skin: `rows.json` → one film per row (`{name, tokens}`), output template `out/{name}.mp4` with `{index}`
and row keys; missing placeholders or output collisions are errors; rows touching a forbidden token are refused;
picture re-rendered per row, audio master shared unless `bed_db` changes; `out/batch_manifest.json` records
`{row, skin, output, duration, qa, credit}`; every output still passes `qa_film.py` and the CREDIT gate.

## Not ported (HeyGen-account items and conflicts)

Hosted `publish` / cloud render / deploy templates; media `resolve` providers (bgm/sfx/image/avatar catalogues,
favicon logo resolver); the global cross-project asset cache (a cross-customer leak by design); telemetry; the
Studio GUI and `timeline move/trim/split` mutations (our timing is the narration clock); webm-alpha / ProRes / PNG
sequence / HLS / 4K exports; bundled third-party SFX files. Only the local, licence-carrying discipline is kept.

## Self-tests (synthetic fixtures, no renders)

```bash
python tools/ledger.py --selftest && python gates/ledger_gate.py --selftest
python tools/timeline.py --selftest && python tools/export.py --selftest     # export: a 6 s testsrc film, ~70 s
```
