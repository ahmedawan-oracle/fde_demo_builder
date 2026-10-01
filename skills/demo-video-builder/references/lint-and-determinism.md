# Lint, determinism and the pre-render loop (v4)

A v3 film is one HTML scene whose only input is the clock `t`. Everything the seek cannot drive — a CSS
transition, `Date.now()`, a rAF outside the preview loop, `Math.random()`, state that advances per call —
makes the three-worker render differ chunk to chunk and makes stills lie. Before `build_film.py` spends ten
minutes rendering, four cheap tools say whether it will be worth it.

```
python tools/doctor.py                                   # 1  environment: ffmpeg, node, Chrome, fonts, disk
python gates/lint_scene.py scenes/film.html --project .  # 2  static scan (ms): determinism, css, media, fonts…
node   tools/audit_text.js scenes/film.html --contrast   # 3  runtime text layout + WCAG AA at the shot times
python gates/canary.py scenes/film.html                  # 4  render-determinism canary (~25 s)
python gates/snapshot.py scenes/film.html [--update]     # 5  golden frames per shot + diff sheet
```

Rule of thumb from HyperFrames' troubleshooting guide, kept: on any failure run doctor → lint → check.

## 1  doctor.py — pre-flight

`python tools/doctor.py [--project .] [--fast] [--offline] [--json]`. Checks python ≥ 3.10 and pip modules,
ffmpeg/ffprobe (found AND start within 5 s, major ≥ 6, libx264 + aac, filters loudnorm · sidechaincompress ·
alimiter · acrossover · lut3d · psnr), node ≥ 18, where `puppeteer` resolves from, Chrome (same resolution
order as `render_frames.js`, then a real headless launch through puppeteer), edge-tts (warn-only), credit
font, scene fonts, disk ≥ 2048 MB at `out/` and `%TEMP%` (< 1024 MB fails), memory ≥ 2048 MB, UNC/synced
project path, `recording.mp4` decodable. `--json` always exits 0 and redacts the home directory — gate on
`.ok`. Exit `3221225595` / `0xC0000409` from a bundled chrome-headless-shell is STATUS_STACK_BUFFER_OVERRUN:
set `PUPPETEER_EXECUTABLE_PATH` to the system Chrome.

## 2  lint_scene.py — what the lint refuses

`python gates/lint_scene.py <scene.html> [more] [--project .] [--profile v3|v2] [--strict] [--json] [--verbose]`
Exit 1 on errors; `--strict` also on warnings; info hidden unless `--verbose`. JS comments and string
literals are stripped before matching (a displayed snippet containing `Math.random` is inert); CSS comments
are stripped before the font scan (a `}` inside one truncates an `@font-face` block). `--profile v2`
downgrades the seekability rules to info because b-roll scenes use transitions and `__start()` by design.

| group | code (severity) | fix hint |
|---|---|---|
| determinism | `non_deterministic_code` (E) `Math.random(` `Date.now(` zero-arg `new Date()` `performance.now(` `crypto.getRandomValues(` | derive from `t`; seeded noise; `new Date(fixed)` is fine |
| | `wall_clock_scheduler` (E) setTimeout / setInterval / rAF outside `if (!RENDER)` or `function loop()` | only the preview branch schedules |
| | `fetch_mid_render` (E) · `missing_render_contract` (E) · `scene_file_too_large` (W > 300 lines) | load assets via tags / the footage lane; copy the contract block from the template |
| css | `css_transition_present` (E) · `css_animation_present` (E, incl. `@keyframes`) | `G.rmp / EZ / EIO / fadeInOut` inside `frame(t)` |
| | `missing_opaque_stage_background` (E) html/body not opaque → white flash pre-seek | `html,body{background:#082A34}` |
| | `fullframe_overlay_starts_visible` (E; info when the script drives the id) | author `opacity:0`, raise it in `frame(t)` |
| | `transform_set_twice` (W) · `layout_property_motion` (W width/height in frame(); I otherwise) | the script owns the whole transform; prefer translate/scale |
| media | `video_or_audio_tag_in_scene` (E) · `img_loading_lazy` (E) · `placeholder_media_url` (E) · `remote_ref` (E) · `base64_media` (E a/v; W image > 50 KB or < 15 unique chars) · `imperative_media_control` (E) · `media_preload_none` (W) · `crossorigin_attr` (W) · `img_without_decode` (W) | extracted JPEG frames via `lib/footage.js`; every asset local; push `img.decode()` into the pending list |
| fonts | `font_family_unresolved` (E) no @font-face, not on this machine, no resolvable fallback · `font_family_system_only` (W) · `font_fallback_in_use` (W) · `font_face_remote_src` (E) · `font_face_local_only` (I) | `tools/fonts_localize.py`, or `src: local('Exact Name')` |
| markup | `unbalanced_style_tags` / `unbalanced_script_tags` (E) · `visible_markup_comment` (E) · `unclosed_tag_swallowed_element` (E) · `self_closing_media_tag` (E) · `html_dir_attribute` (E) · `root_css_zoom` (E) · `js_syntax_error` (E, `node --check`) · `negative_z_index` · `id_starts_with_digit` · `stage_dimensions_mismatch` · `css_brace_balance` (W) | five-minute regex checks for the blank-frame bugs |
| perf | `heavy_overlay_count` (W ≥ 25 blur/backdrop-filter/radial-gradient/clip-path) · `large_image_asset` (W > 3840×4320; seq frames > 1920×1080) | flatten decorative layers; source at most 2× delivery |
| project | `missing_local_asset` (E) every CLIPS file on disk, bed/sfx, scripts · `shot_clip_unknown` (E) · `timing_total_mismatch` (E) | `extract_clips.py`, `gen_vo_multivoice.py` |

Generic families (`serif`, `sans-serif`, `monospace`, `system-ui`, `ui-*`, `-apple-system`, …) and
`inherit/initial/unset/revert` are never flagged; `var(--x)` tokens are skipped; Google Fonts `<link>` /
`@import` families count as declared (and are themselves a `remote_ref`). Tall stitched pages are legitimate:
`large_image_asset` warns, never blocks. `--selftest` lints a bundled bad/good pair (24 codes must fire; the
good scene must be error-free; exactly four live non-deterministic calls, string and comment ignored).

## 3  fonts_localize.py — rule out your machine as a variable

Fonts are the usual reason a render "shifts by a pixel between machines": a teammate's Mac has no Georgia,
title lines re-wrap, the honesty caption lands on a different word.
`python tools/fonts_localize.py scenes/film.html [--out scenes/fonts] [--local] [--dry-run] [--offline]`
reads every family the scene uses, finds the undeclared ones in the OS folders (Windows `%WINDIR%/Fonts` +
`%LOCALAPPDATA%/Microsoft/Windows/Fonts`, macOS `/Library/Fonts` + `/System/Library/Fonts(+/Supplemental)`,
Linux `~/.fonts`, `~/.local/share/fonts`, `/usr/share/fonts`, depth ≤ 2; family read from the font's name
table), picks the regular weight plus the weights/italics the CSS asks for (woff2 > otf > ttf > woff > ttc,
5 MB per-family cap), copies them to `scenes/fonts/`, writes `scenes/fonts.css` and inserts
`<link rel="stylesheet" href="fonts.css">` after the last `<style>`. Remote Google Fonts are downloaded and
rewritten. **Licences:** the tool writes into *your* project only. Never commit Segoe UI / Helvetica Neue /
Arial files to a public repo — use `--local` (`src: local('Exact Name')`) or an OFL family. The shipped
example keeps OS fonts and therefore lints with warnings, not errors.

## 4  canary.py — the three seek paths must agree

`render_frames.js` splits the film across W workers: worker k **cold**-seeks to `i0/FPS`, worker k−1
**steps** up to `i0−1`. Any state kept across frames shows up as a seam exactly there. The canary renders
a handful of frames three ways (cold #1, cold #2, stepped from `t − 1 s`) and compares decoded pixels:

- **determinism** = cold #1 == cold #2 (run-to-run); **seek parity** = cold == stepped (seek order).
- Default times: every chunk boundary `round(k·N/W)/fps`, first cut + 0.4 s, 0.5 s, END − 0.05 s (≤ 8).
- Verdict: byte-identical, or *invisible* — no pixel moved more than the cut threshold (|Δgray| > 24) AND
  PSNR ≥ 60 dB. Measured on the Acme sample: Chrome promotes a fading lower-third to its own compositor layer
  after a few stepped frames and moves **one** pixel by 21 levels (85.8 dB; 68.7 dB with `--disable-gpu`).
  A real seam (the per-call odometer in `--selftest`) sits near 32 dB with 0.13 % of pixels changed.
- `--cross-machine` relaxes to PSNR ≥ 40 dB (HyperFrames' regression-harness floor). `RENDER_SOFTWARE_GPU=1`
  adds `--disable-gpu` for both probe and (if you mirror it) render.
- On a mismatch: `out/canary/diff_*.png` (|a−b| × 8) and the changed-pixel % with the first offending t.

The probe pins Chrome's determinism flags: `--font-render-hinting=none --disable-lcd-text
--force-color-profile=srgb --disable-background-timer-throttling --disable-renderer-backgrounding`, waits for
`document.fonts.ready`, awaits the decode Promise that `__seek/__step` return, forces layout before the shot.

## 5  snapshot.py — golden frames per shot

Captures title (`FILM.openEnd/2`), each shot `t0 + 1 s`, close (`FILM.close + 0.5`), explicit `--at` times
and the readable tail `END − max(0.05 s, 3 % · END)` (seeking to the exact end renders blank). Saved as
960×540 JPEG q85 in `out/snapshots/` with `contact.jpg` (cols = min(4, ⌈√n⌉)). With a `golden/` folder each
capture is compared: PASS when identical, changed-pixel % ≤ 1.0 or PSNR ≥ 40 dB; changed shots go into
`diff.jpg` as rows golden | current | |Δ| × 8. `--update` promotes the current set after review.

## 6  audit_text.js — text that leaves the frame

At the scene's own sample times (every shot `t0 + 0.4`, lower-third middles `acts.t0 + 2`, title, END − 0.5,
END − 0.05): `clipped_text` (overflow hidden and scroll − client > 2 px), `text_box_overflow` (2 px; vertical
max(2 px, 0.2 × font-size) when nothing clips), `stage_overflow`, `credit_zone` (y ≥ 600 during the last 4 s —
where `credit.py` stamps the mandatory line), `text_overlap`. Visible = not display:none, `checkVisibility`,
opacity chain ≥ 0.5. Held at ≥ 2 consecutive samples → error; one sample → info. `--contrast`: glyph paint
made transparent, one screenshot, paint restored first, median background inside the text box, WCAG AA
4.5:1 (3:1 for ≥ 24 px or ≥ 19 px bold) with a suggested colour nudged toward the passing side. Opt-outs:
`data-qa-ignore`, `data-qa-allow-overflow`, `data-qa-allow-overlap`, `data-qa-allow-contrast`.

## QA gates added (qa_film.py loads `gates/*.py`)

| gate | module | PASS | qa.json |
|---|---|---|---|
| `lint` | lint_scene | 0 errors on scene + lib/*.js + project assets | `lint_strict`, `lint_profile` |
| `text layout` | lint_scene | no text issue held ≥ 2 samples, no page error | `audit_text: false` skips |
| `contrast` | lint_scene | warning-only unless `"contrast": "error"` | `contrast` |
| `determinism` | canary | cold #1 == cold #2 at every time | `canary: {times, max_times, approach, cross_machine, enabled}` |
| `seek parity` | canary | cold == stepped (≥ 60 dB invisible) | same |
| `golden` | snapshot | every shot within threshold of golden/ (info when no golden/) | `snapshot: {golden, max_changed, psnr}` |

## Worked example (fictional Acme sample)

```
$ python gates/lint_scene.py scenes/film.html --project .
  WARNING font_fallback_in_use      scenes/film.html:2  'Helvetica Neue' is not on this machine — 'Arial' will render instead
  WARNING font_family_system_only   scenes/film.html:2  'Arial' has no @font-face; it renders from this machine's OS font
lint: 0 error(s), 3 warning(s)
$ python gates/canary.py scenes/film.html
canary  Chrome/154  5 times: 11.07, 22.17, 12.80, 0.50, 33.20
  t= 22.17  run-to-run same  cold-vs-stepped near  {'changed_pct': 0.0, 'psnr': 85.84}
determinism PASS | seek parity PASS -> out/canary
```
