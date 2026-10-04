# Brand kit and skins — the look is approved before the build

Three pieces: `tools/brand_kit.py` (a brand → a contrast-checked skin + a six-frame style sheet), `skins/`
(ten complete looks, catalogued in `skins/README.md`), and the `?skin=` loader (`tools/skin_apply.py` →
`scenes/skin_data.js`; `film.json → "skin"`). The review pack that signs the plan off is in
`review-pack-and-studio.md`.

## 1. From a logo to a skin

```
python tools/brand_kit.py extract --logo assets/logo.png --site assets/site.png --bg dark --mood corporate \
       --name acme --out skin_tokens.json --sheet out/style_sheet.png
```

| Step | Rule |
|---|---|
| pixels | box-reduce to ≤ 160 px so every pixel counts once; drop alpha < 128, near-white (min channel > 235), near-black (max < 24); greys (max − min < 12) kept as neutral candidates; a site screenshot weighs 0.35 of a logo pixel |
| clusters | weighted k-means in CIE L\*a\*b\*, k = 6, k-means++ seed 0, 4 restarts, best inertia; sorted by weight then hex (our own numpy engine; `BRAND_KIT_ENGINE=sklearn` cross-checks and lands on the same roles) |
| primary | heaviest cluster with chroma ≥ 15 |
| accent | farthest hue from the primary (≥ 40°, chroma ≥ 20), ranked by √weight × hue distance; none → synthesised at hue + 150°, L\* 66, C 55 |
| dark ground | paper L\* 15 / C ≤ 12 in the primary hue, paper2 L\* 24, ink L\* 95, muted L\* 70, gold L\* 82 C 48 at hue 85 |
| light ground | paper L\* 95, paper2 L\* 90, ink L\* 15, muted L\* 48, gold L\* 58; `black` (the head-fade plate) = the paper |
| contrast | WCAG 2.x against the paper: ink ≥ 7:1, ink-soft ≥ 4.5, muted ≥ 4.5, accent ≥ 3, gold ≥ 3 — L\* nudged one step at a time, hue fixed, chroma shrunk only to stay in gamut; achieved ratios are written into the skin |
| type | Windows-local pairings by mood: editorial Georgia / Segoe UI · technical Bahnschrift / Segoe UI · friendly Segoe UI / Segoe UI · corporate Cambria / Arial; Consolas mono. Stage sizes: title 64, body 22, label 13 (+0.12 em), mono 18 |
| motion | mood → profile: editorial calm, corporate + technical medium, friendly high |
| captions | mood → lane style: documentary · anchor · broadcast · keynote |

Nothing is pure #000 or #FFF (it crushes on an H.264 booth screen). `--bg auto` picks light only when the
mark itself is mostly dark (mean L\* of the chromatic pixels < 45). Logos must be rasterised PNGs (no SVG
rasteriser is installed — export from the browser or the design tool first).

## 2. The style sheet

Six half-stage frames (640x360) in the skin's own fonts and colours: title card, caption lane over a
*synthetic* product plate (the active word in the accent; an inverted pill falls back to gold when the
accent is < 3:1 on the ink), KPI tiles (one focal tile takes the accent), lower third (3 px accent edge,
tracked label, one line), chart (one focal bar), close card (first line gold) with the mandatory credit.
The dashed line at 83 % is the caption keep-out. Figures are labelled *sample values* — a film shows only
figures traced in `claims.json`. Look at the sheet before the build; if it is wrong, change the skin, not the
scene. A 2000x912 PNG; `python tools/brand_kit.py --from-skin skins/<name>.json --sheet out/sheet.png`
regenerates one for any skin.

## 3. Skins

A skin is `templates/skin_tokens.example.json` (the 16 token ids the scene reads as `--paper`, `--ink`,
`--accent` … plus `forbidden_tokens` and `css_snippet`) plus the sections that make a look complete:
`type`, `motion`, `captions`, `seams` (the 2–3 techniques the film repeats), `when_to_use`, `contrast`. Ten
ship in `skins/` — Harbor (the house look, deep navy + coral), Meridian Dark, Paper, Signal, Slate, Ember,
Cobalt, Mint Ledger, Noir, Sunrise — with their sheets in `skins/sheets/`. Compose your own from colours you
already have:

```
python tools/brand_kit.py compose --name acme --paper "#082A34" --accent "#E56B5E" --bg dark --mood editorial \
       --profile calm --caption-style documentary --seams "cut-the-curve,inverse zoom-through" --when "…"
python tools/brand_kit.py check skins/acme.json          # exit 1 on findings
```

Motion profiles (seconds on the film clock; inside the doctrine: entry ≤ 0.8 s, exit ≈ 75 % of entry,
stagger ≤ 0.5 s at 0.04–0.08 s per item, push 0.9–2.0 s landing ×1.3–×2.0, dwell ≥ 1 s):

| Profile | Entry | Exit | Per item | Push | Hold | Rack focus |
|---|---|---|---|---|---|---|
| calm | 0.60 power4.out | 0.45 sine.in | 0.08 | 1.4 s ×1.3–1.6 | 2.5 s | no |
| medium | 0.40 power4.out | 0.30 power2.in | 0.06 | 1.1 s ×1.4–1.8 | 2.0 s | ≤ 1 per 8 s |
| high | 0.25 expo.out | 0.20 power3.in | 0.04 | 0.9 s ×1.5–2.0 | 1.5 s | ≤ 1 per 8 s |

`check` fails a skin outside these ranges, with a missing token, a pure black/white, a contrast below the
floor, a font outside the local table, an unknown caption style or seam technique, more than three
techniques, or no `when_to_use`. The `motion` / `captions` / `seams` sections guide the author and the gate;
they never move the clock.

## 4. Applying a skin

`film.json → "skin": "skins/harbor.json"` (or your `skin_tokens.json`). `tools/skin_apply.py skins/<name>.json`
writes `scenes/skin_data.js`; the scene sets each token on `:root` before any block is built, binds string
and image slots (`binds` selectors), and exposes `window.SKIN` so `shots.js` reads `SKIN.motion.enter_s /
exit_s / push_s / push_scale / hold_s` and `captions.json` defaults to `SKIN.captions.style`. `?skin=<json>`
on the scene URL does the same for a preview. `seams.json` techniques stay inside `SKIN.seams.allowed`. On a
light-ground skin `build_film.py` takes the head-fade plate from the `black` token, so the film does not open
on a dark flash. Gates (`skin_gate`): `skin check` runs `brand_kit.check_skin` on the active skin; `skin tokens`
confirms the scene reads the 16 token ids; `review lock` needs the sign-off in `## Locked`.

## Rules

- Change the skin, not the scene: a scene reads tokens; it never hard-codes a brand colour.
- One accent per film; the gold is for figures and the first line of the close.
- Every value the sheet shows is a sample; every value the film shows is a claim.
- Fonts in a skin are faces that ship with the OS (Georgia, Cambria, Segoe UI, Arial, Consolas, Bahnschrift);
  `tools/fonts_localize.py --local` keeps a public repo free of font files.
