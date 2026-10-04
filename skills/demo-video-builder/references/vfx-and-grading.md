# VFX and grading: where it is honest, and where it is not (v5)

Two layers live in every v3/v4 film. The **footage lane** (`#clipWrap`: stills, pages, seqs from the
recording) is evidence: the product as it was. The **recreated layers** (title, cold open, payoff and
closing cards, haze, lower thirds) are authored. Finishing effects belong to the second layer only;
the first may receive *corrections* that a reviewer could not tell from a better capture.

| On product footage | On recreated cards |
|---|---|
| levels, exposure match between captures, neutral white balance — **verified by swatches** | anything in `lib/vfx.js`: vignette, grain, bloom, haze, glitch, wave, seams, mattes |
| never: saturation, hue, curves, LUTs, grain, glitch, blur, blend modes | one house LUT at 30–50 % intensity is fine |
| never "make the product match the brand" | the brand *is* the palette here |

Code enforces this: `grade.py` refuses non-adjust keys on product clips, `VFX.*` throws when aimed at
`#clipWrap` or anything with `data-footage`, and `gates/grade_gate.py` re-checks both statically and
by measuring the finished film.

## 1. Grading real footage — `tools/grade.py`

**Measure first.** `python tools/grade.py probe recording.mp4 [t0 t1] [--write broll/nb/meta.json]`
runs ffprobe + ffmpeg `signalstats` on 5 frames and prints YMIN/YLOW/YAVG/YHIGH/YMAX/UAVG/VAVG and a
*bounded* suggestion: exposure only when YAVG/255 < 0.28 and YHIGH/255 < 0.65 (`(0.32−avg)·1.2`) or
avg > 0.72 with YLOW/255 > 0.3 (`(0.68−avg)·1.2`); contrast when the YLOW–YHIGH spread < 0.35
(`(0.35−spread)·0.4`); blacks +0.08 per unit of shadow-clip risk (YLOW ≤ 16); temperature
`−0.25·warmth` when |warmth| ≥ 0.08 with warmth = ((V−128)+(128−U))/128; tint `−cast/512` when
|U+V−256| ≥ 10. On UI footage highlight-clip risk (YHIGH ≥ 235) is **reported, not corrected**: a
white panel is supposed to sit there. `--match other/meta.json` prints the offsets that bring one
capture of a screen onto another's levels and cast. Put the numbers in the shot log's "levels / cast"
column.

**Adjust maths** (sRGB floats, Rec.709 luma, fixed order): gain `2^exposure` → shadows
`·0.35·(1−smoothstep(0,0.65,Y))`, highlights `·0.35·smoothstep(0.35,1,Y)` → black point
`blacks·0.18`, white point `1−whites·0.18`, `(c−bp)/(wp−bp)` → `R += 0.08·T + 0.04·tint`,
`G −= 0.08·tint`, `B −= 0.08·T − 0.04·tint` → contrast `(c−0.5)(1+k)+0.5` → *(b-roll only)*
vibrance, saturation `mix(Y, c, 1+s)`, LUT. Limits: exposure ±2, everything else ±1.
**Product limits** on top: exposure ±0.3 EV, temperature/tint ±0.15 (0.05 ≈ one 8-bit level,
0.15 ≈ three — the point where flat panels visibly shift). White-panel apps: prefer `blacks`/`whites`
to any positive exposure — +0.1 EV clips `#E8F0FE` to white (the selftest proves it).

**Swatch guard.** `clips.json` → `"grade": {"blacks":0.03,"temperature":-0.05}` plus
`"swatches": [[x,y,"#hex"?,"name"?], …]` (up to 6: the brand accent, a status red/green, the panel
background, body ink). `apply_adjust_image()` refuses if any 5×5 patch moves more than **dE76 6**.
Grade before blur/word/text fixes and before the JPEG save, so repainted words sample corrected ink
and nothing is quantised twice. A seq graded in ffmpeg instead uses `grade.py filter --adjust …`
(a `lutrgb` chain: identical luma moves on R, G, B plus the neutral per-channel cast offset; the
selftest shows ≤ 1 level from the numpy path; shadows/highlights are luma-masked and stay numpy-only).

**Compare sheet.** `grade.py compare broll/nb/f_001.jpg grades.json out/qa/grade_compare.png
[--crop x,y,w,h --native]`: `original` first, then every candidate, 4 per row, 560 px cells, 32 px
labels. If any product clip is graded, attach the sheet to the review — it is how a 1–2 level
levels-match becomes a 10-second approval.

**LUTs (b-roll only).** `grade.py lut look.cube [--apply in out --intensity 0.4]` parses a 3D `.cube`
(≤ 64³, DOMAIN/INPUT_RANGE honoured, 1D rejected), applies it trilinearly, and prints the ffmpeg
fragment (`lut3d=file=…:interp=trilinear`, blended at < 1 intensity). `grade.py bake-lut adjust.json
look.cube --size 33` turns a house adjust vector into one file for every recreated card.

## 2. Finishing recreated cards — `lib/vfx.js` (`window.VFX`)

All functions are pure in `t` + explicit state; seeds are `Math.round(t·fps)`; nothing uses
`Math.random`, the wall clock or CSS animation, so `__seek` and `__step` agree.

| Call | Measured defaults | Use |
|---|---|---|
| `VFX.vignette(el, {amount:.12, mid:.5, feather:.65})` | darkening 0.75·amount outside a superellipse; midpoint 0.22–1.08, feather 0.08–0.72 of the half-frame; restrained 0.10–0.18 | CSS gradient on an overlay div (idempotent). `vignetteMask(W,H,o)` = exact superellipse canvas (power 8 square … 1.8 round) |
| `VFX.grain(ctx, t, {amount:.12, size:.18, roughness:.65})` | cells 1–6 px, fine layer at 0.35, strength 0.025–0.08 → the canvas holds 128 ± d for a `mix-blend-mode: soft-light` layer (soft-light stands in for the midtone mask) | keeps a held card alive *with* the mandatory 1–3 %/s push; never alone |
| `VFX.bloom(ctx, src, {threshold:.6, radius:8, amount:.55})` | Rec.601 threshold, 9 taps (.227 .1946 .1216 .054 .0162), additive | judge at 1:1 — a bloomed card measures *less* clipped. DOM variant: `applyBloomGhost(ghostEl, amount)` = blur 8 px, screen, opacity amount·0.3 |
| `VFX.matteStyle(kind, u, o)` + `applyMatte(el, st)` | `text` (SVG word, luminance), `wipe`, `circle` (r = 120·u %) | "reveal through the product": the masked layer may *contain* footage (a mask is a shape, not a pixel change). `applyMatte` returns a decode Promise — push it to the scene's pending list |
| `VFX.haze(ctx, t, {scale:400, opacity:.05, drift:.01})` | value-noise fBm, 32-bit lattice hash, 6 octaves, gain 0.70, lacunarity 1/0.56, contrast 562 %; 160×90 tile upscaled | dark card backdrops only; opacity ≤ 0.06 so captions and the credit stay legible |
| `VFX.glitch(ctx, img, t, t0, dur, {seed})` | envelope u(1−u)·4, 60 bands, tear 0.18, RGB split 0.035, 8 levels mixed at 0.5 near peak | the problem beat: once per film, ≤ 0.4 s, recreated card only |
| `VFX.waveWarp(ctx, img, t, {height:10, width:40, speed:1, t0, dur})` | sine only, transparent edges | same rules as glitch |

**Transitions moved to the GL layer (v5).** `lib/vfx.js` keeps the finishing above (vignette, grain, bloom,
matte, haze, glitch, wave, the speed ramp); picture-to-picture transitions are drawn by `lib/shaders.js` and
declared as `type: gl` rows in `seams.json` (`gl-transitions.md`). Doctrine unchanged: one primary seam plus at
most two accents per film; calm 0.5–0.8 s, medium 0.3–0.5 s, high 0.15–0.3 s; never fade-out-then-fade-in; the
transition *is* the exit. **Never on a footage → footage cut** — a dissolve between two product screens implies
a continuity that did not happen; UI changes stay hard cuts. A transition may pass over footage only inside its
declared window and the window is ≤ 0.5 s; the ledger, the lint and `seam_gate` all refuse longer ones.

## 3. Speed ramps on seq clips — `VFX.ramp` / `grade.py ramp`

A lane `[[t, rate], …]` in clip-local seconds (optional third value: curve bend −1..1). Rates clamp
0.1–10 and interpolate in **log space** (0.5 → 2 passes 1 at the midpoint); the source time shown is
the trapezoid integral tabulated at 48 cells per segment, binary-searched, so render and QA agree on
the frame. `VFX.ramp.frameAt(lane, dt, fps, n, from)` holds the last frame; `VFX.ramp.rampTo(revealSrc,
landAt)` solves the one shape a demo needs — *fast through the wait, exactly 1× when the reveal
lands on its word* (e.g. 6 s of spinner shown in 3 s: `[[0,2.049],[2.75,2.049],[3,1]]`). Never below
0.5× on UI motion (reads as a stall), never over a typed reveal (REVEAL already owns it). Montage /
bullet / jump-cut presets are music-video grammar: not provided.

## 4. The gates — `gates/grade_gate.py`

- **ui colour truth**: swatches from `swatches.json` (`{"clip","t","name","xy","hex"?}` or
  `{"clip","t","auto":6}`) are sampled 5×5 in the finished film at a full-screen moment (scale 1.0,
  outside seam windows) and compared with the raw recording (or the stated hex). FAIL if hue shifts
  > **6°** (only measured when chroma ≥ 12/255), saturation moves > **10 points**, or dE76 > **8**
  (grade.py's 6 plus JPEG q96 + yuv420p). A graded product clip with no swatches is a FAIL.
- **effects off footage**: product `grade` keys ⊆ adjust and within the product limits; no `VFX.*`
  call, CSS `filter`/`mix-blend-mode` or `style.filter` aimed at `#clipWrap`/`#clipImg`/`#pageImg`/
  `#pageDoc`/`#pageView`/`FOOT.`/`lane.`; `film.json → grade` never targets product clips.

## 5. Worked example (fictional Acme film)

Two captures of the Acme Console, one from a warmer laptop. `probe` on both → `--match` says
`temperature −0.06, exposure +0.04` for the second. `clips.json`: `"grade": {"temperature": -0.06,
"blacks": 0.02}`, `"swatches": [[1680,32,"#0E7C86","accent"],[410,160,null,"status red"],
[1000,500,null,"panel"]]`; `extract_clips.py` applies it before the privacy blur, the guard reports
worst dE76 1.8. `grade.py compare` sheet goes in `out/qa/`. The title card gets `VFX.vignette` 0.12
+ `VFX.grain` 0.12 over its 1.2 %/s push; the cold open's "spreadsheet nobody trusts" card takes a
0.3 s `VFX.glitch`; the title → notebook hand-off is one `flash-white` 0.5 s. `qa_film.py` then shows
`ui colour truth PASS 3 swatches … worst dE 1.8` and `effects off footage PASS`.
