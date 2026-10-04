# Leak gate — nothing private ships in the footage (`gates/leak_gate.py`, `tools/mask_propose.py`)

`gates/leak_gate.py` reads the pixels the film will actually show and fails QA on any identifier that is on
screen and not neutralised. `tools/mask_propose.py` turns its findings into the blur fixes `clips.json`
already understands. Together they close the gap every recorder and every code-first video tool leaves to
the user: the address bar, the account badge, the tenancy identifier in a form, a customer name in a table.
`references/privacy-scrubbing.md` is the hand checklist; this is the adversarial pass — it reads the pixels,
not your intentions.

## What is scanned

| source | file(s) | coordinates | sampling |
|---|---|---|---|
| still (median) | `broll/<clip>/f_001.jpg` | clip px (origin = crop) | the one frame |
| page (stitched) | `broll/<clip>/page.jpg`, `chrome_k.jpg` | doc px / frame px | page once, every chrome frame |
| seq | `broll/<clip>/f_NNN.jpg` | clip px | every 15th frame, ≤ 8 per clip, first + last; a frame whose 160x90 grey matches the last OCR'd frame (< 1 level) reuses its text |
| footage folders no clip names | `broll/*/` | frame px | as a seq |
| rasters the scene loads | `<img src>` png/jpg/webp | frame px | once |
| finished film (opt-in) | `out/<film>.mp4` | frame px | `leak.film_frames` evenly spaced frames |

Budget: `max_ocr_frames` 60 per run; results cached by file hash in `out/leak_ocr_cache.json`, so re-runs
cost nothing and the output is identical with or without the cache. `leaks.json` carries no timings or dates
and is byte-identical across runs.

## Four detectors

1. **OCR** through a pluggable backend (`recognize(PIL.Image) → [{text, box, conf}]`). Two engines:
   `rapidocr_onnxruntime` (a bundled PP-OCRv3 model on onnxruntime, needs `opencv-python-headless`) and
   `winocr` (the Windows OS engine). Measured on the build machine (Python 3.14, Windows 11): rapidocr reads
   a dense 1920-px browser frame in 25–40 s, winocr in 0.3–0.5 s with more character confusions — all still
   caught by the tolerant patterns. **Prefer winocr on Windows** (`"leak": {"backend": "winocr"}`), rapidocr
   elsewhere; `auto` hands the remaining frames to winocr when a first rapidocr pass exceeds 10 s. winocr reads
   frames up to 4000 px wide at 2× native — a Retina address bar that 1920-wide OCR missed is read in full.
   No engine → `leak ocr` reads WARN and the three detectors below still run.
2. **Patterns** on every OCR line (raw and with spaces removed): e-mail, cloud resource identifiers (tolerant
   of OCR `.` → `_`/`-` and `l`/`1`), IPv4, any `http(s)` URL, internal host names (`.internal .corp .local
   .lan .test .dev`, `-dev.`, `staging`, `localhost`, `host:port`), JWT and other three-segment tokens, 32+ hex,
   UUID, phone, `Bearer …`, key shapes (`AKIA…`, `sk-…`, `token=`, key fingerprints, PEM headers).
   `leak.allow_patterns` whitelists your own public domains.
3. **Denylist** from `BRIEF.md → ## Never on screen` (one term per line) plus `leak.deny` / `--deny` files.
   Fuzzy: at most one edit per 8 characters, rounded up, as an approximate substring, so `G1obex` hits
   `Globex`. The same terms are checked in the text that names footage — `clips.json` "shows", `meta.json`,
   `shots.js`, the scene, the ledger — the path that needs no OCR.
4. **Account badge**, no OCR. Real product badges are discs *or rounded squares* with initials over a
   patterned fill, 16–72 px at 1920-normalised scale (measured 21 and 26 px), in the top 20 % of the source
   frame (8 % on a Windows capture, 17.4 % on macOS with tabs and bookmarks) and the right 30 % of the width
   (measured 96–98 %). The bar colour is a local tile median (a whole-row median failed beside a modal
   dialog). Candidates must contrast with the bar by 24 levels (measured 53 and 90), be compact (aspect
   0.8–1.25, fill 0.60–1.0, radius spread ≤ 0.2) and pass the inside-corner test: the centre colour differs
   from the bounding-box corners — keeps discs and rounded squares, rejects sharp square icons, ring favicons
   and hollow logos. A browser profile ring or a round header logo may be flagged — list it under `leak.ignore`.

## Masks and windows

Declared masks are `clips.json` `fix: [{"blur": [x, y, w, h, r]}]` (clip px on stills/seqs, doc px on pages)
and `chrome.fix` (frame px). A hit ≥ 80 % inside one is `masked`. **A badge inside a declared mask passes** (a
blurred disc is still a disc; the identity is gone). **Text inside a declared mask that OCR can still read
fails** with *declared mask not applied or too weak*: `extract_clips.py` was not re-run or the radius is too
small. `out/timeline.json` shots give every clip its on-screen window; a hit in a clip no shot uses is listed
with `on_screen: false` and does not fail.

## From hit to mask

```
python qa_film.py                                  # leaks FAIL → leaks.json (text redacted to 3+2 chars)
python tools/mask_propose.py leaks.json --verify   # proposal → leaks.masks.json; blurred copies re-scanned
python tools/mask_propose.py leaks.json --apply    # accept: entries appended to clips.json (.bak kept)
python extract_clips.py && python qa_film.py       # the blur lands in the pixels; leaks PASS
```

The proposal pads every box by 6 px, merges touching boxes on the same clip, and sets the radius by rule:
`r = max(6, ceil(0.45 × text height))` — at that radius a 12–24 px UI line keeps under 1 % of its horizontal
gradient energy and neither engine reads it — and `ceil(d / 3)` for badges. Each entry records which kinds it
covers and the shot window it is on screen. Hits in authored text cannot be masked; they are listed under
`edits` with file:line. `--apply` is idempotent.

## Knobs (`qa.json → "leak"`)

`backend` auto|rapidocr|winocr|none · `seq_stride` 15 · `seq_max_frames` 8 · `max_ocr_frames` 60 · `ocr_width`
1920 · `src_size` [1920, 1080] · `slow_ms` 10000 · `avatar` {band 0.20, right_of 0.70, dmin 16, dmax 72,
contrast 24} · `deny` · `deny_terms` · `allow_patterns` · `ignore` [{clip|src, box}] · `film_frames` 0 ·
`full_text` false · `cache` · `out`.

## Rules of the lane

Mask private data only, with a small soft blur, never a white box and never a redraw. The gate reads the
extracted files, not the recording, so it judges exactly what `footage.js` will load. `leaks.json` never
contains the identifier it found. Run `python gates/leak_gate.py --scan frame.png` on any grab to check a
recording before you extract from it. Install: `pip install winocr` on Windows (fast) or
`pip install rapidocr-onnxruntime opencv-python-headless onnxruntime` elsewhere — both optional; the badge
and denylist detectors need neither. Gates: `leaks` (FAIL on any live unmasked hit) · `leak ocr` (backend and
ms/frame; WARN when no engine). CLI: `--project DIR [--out leaks.json] [--deny FILE] [--backend X] [--no-ocr]
[--seq-stride N] [--max-frames N] [--full-text] [--no-cache] [--json]`; `--scan IMG…`; `--selftest [--no-ocr]`;
exit 0 clean / 1 findings / 2 usage.
