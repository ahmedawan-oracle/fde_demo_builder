# Captions and graphic overlays (v5)

Burned-in captions and overlays for the v3/v4 film: `lib/captions.js` (CAP), `lib/overlays.js` (OVL),
`tools/captions_srt.py`, `gates/overlay_gate.py`, `templates/captions.example.json`. Everything is a pure
function of the narration clock `t`; nothing here grades the footage. Examples are fictional (Acme).

## Doctrine

- **Three fates for a spoken phrase.** *Drop* (not shown — fillers in a real-audio segment, or a phase whose
  words are already the title card), *rail* (the verbatim lower-third lane, the default: scripted TTS has
  no fillers, so the lane is 100 % verbatim), *embed* (the phrase becomes the picture: big, centred, one at
  a time — the title/thesis beat or the closing antithesis). Set the default with `mode`, per phase with
  `phases`, per word with `overrides[].drop`.
- **Overlay, not a reserved band.** Captions and cards are composited on the finished frame in screen space
  (outside `#camera`, so a push can never move them off safe). Compose the picture on the true centre
  (y = H/2); keep only critical small text out of the bottom ~80 px centre span. The one real keep-out is the
  mandatory credit footer (bottom ~120/1080 of the frame, last 4 s): the lane hides itself there.
- **Legibility is glyph-local.** Soft dark shadow (0 3px 14px rgba(0,0,0,.65)) or a 30–40 % scrim / gradient
  pill sized to the text box; a hard white box is the last resort; never a frame-wide bar, never a grade.
- **Subject reads first.** The product UI the voice is naming is the subject: never put a caption, callout or
  hero over readable product text (text-on-text); restate a figure that is on screen, never introduce one
  (every callout value goes in `claims.json`).
- **One family, two weights, one accent hue.** Display tracking −0.015…−0.035 em, body +0.005…+0.015 em;
  body cap height 3.5–5 % of frame height (40–55 px at 1080), emphasis 70–100 px; never italic for emphasis
  (only a literal quotation). Animate transform / opacity / clip-path only — never letter-spacing, size,
  weight or blur on word spans. Exits run at ~60–75 % of entrances; never fade a caption out during speech.
- **Emphasis ladder per film:** 70 % plain, 20 % slight lift (colour *or* weight), 8 % full emphasis, 2 % climax;
  em words on ≤ ~30 % of groups, never two adjacent. A rhythm break every ~30 s.

## Style presets (`CAP.STYLES`, tokens at 1080p, scaled by stage height)

| style | use when | face / size / weight | treatment | motion |
|---|---|---|---|---|
| `anchor` | default verbatim rail; pick when unsure | Segoe UI 0.045·h, 600 (em 700) | shadow .65 | in 0.12 s y4, out 0.15 s y6 |
| `broadcast` | busy footage, BBC-length lines (34 chars) | 0.045·h, 600 | 40 % gradient pill | 200 ms up / 150 ms down |
| `documentary` | trust beat, gravitas; bottom-left block at 10 % | 0.045·h, 500/700, bone #F5EFE6 | shadow, no accent | none; held 0.5 s past the last word |
| `keynote` | title / thesis beat (embed fate) | 0.16·h, 800, uppercase, −0.045 em | none | wipe-x 0.4 s expo-out, exit 0.3 s |
| `ink` | bright product screens (lane luma > 150) | near-black #111418, 600 | light pill .55 | 0.12 s fade, no float |
| `conference` | persona lines: role 400 / line 700 card | 0.042·h, 700 on charcoal | pill .72 | 0.4 s swipe once, then static |
| `typewriter` | the product's own voice | Consolas 0.040·h, 500 | 40 % gradient band | 33 chars/s, 600 ms cursor blink |
| `clipwipe` | openers / chapter lines | 0.05·h, 300 → 700 on line 2 | shadow | per-word clip wipe 0.25 s |
| `karaoke` (v5) | the hero question, a quoted answer (≤ 2 phases per film) | Segoe UI 0.045·h, 600 → 700 cross-fade, accent #E8C874 | shadow .65 | spoken word: attack 0.12 s, pulse 1.06, rest 0.82 / future 0.55 — no reflow |
| `kinetic` (v5) | recreated lines, chapter cards | 0.05·h, 700, accent #E56B5E | shadow .6 | word waterfall 0.06 s × 0.84ⁱ ≤ 0.3 s, lead 0.3 s, block exit 0.18 s |

Forbidden in this register (`CAP.FORBIDDEN`): highlight sweeps, neon, glitch, kinetic slams, particle
bursts, emoji pops, gradient fills, matrix decodes. Fonts are local Windows/mac families only — never a
web-font URL (offline booth builds, determinism).

## Grouping and timing (`CAP.group`, identical in node and the browser)

Word end = edge-tts `d` (fallback `min(next.t − 0.03, t + 0.35)`). Cut a new group at a pause ≥ 0.35 s
(our breath gaps come from `pause`/`pad`), a sentence terminator, a comma followed by ≥ 0.25 s, or when
the style's cap is reached (anchor 6 words / 42 chars × 2 lines; keynote 5 / 22) or 2.5 s elapsed. Never
cross a phase (a phase = one voice). Hard shape: ≥ 2 words (singles merge into a neighbour), ≥ 0.5 s on
screen, one group at a time, ≤ 2 lines, no dangling 1-word second line (balanced break).
Windows: `in = first.start − 0.08`, `out = min(next.in − 0.05, last.end + 0.6)`, always ≥ `last.end`;
fades are clamped to the air around the words so the lane hard-cuts rather than fading during speech.
`density: true` lowers the cap to 2 / 3 / 4 words at > 3.5 / > 2.5 words per second (1 s window).
Active-word envelope (`CAP.env`): linear attack 0.12 s → sustain to the word end → release 0.3 s to rest
0.55; drives colour dim→ink and an optional scale ≤ 1.10 (rail default 0).

## Files and build steps

```
scenes/captions.json              copy of templates/captions.example.json — style, mode, phases, overrides, grouping
node scenes/lib/captions.js scenes/timing_film_data.js scenes/captions.json \
     --out out/caption_groups.json --js scenes/captions_data.js [--luma out/caption_luma.json]
python tools/captions_srt.py out/caption_groups.json out/<film>.srt --vtt out/<film>.vtt
python tools/captions_ass.py out/caption_groups.json --out out/<film>.ass --srt out/<film>.srt --vtt out/<film>.vtt   # v5: + .ass with per-word tags
python tools/chapters.py STORYBOARD.md --seams seams.json --phases vo/film_phases.json --out out               # v5: chapters on cuts
python gates/overlay_gate.py --probe scenes/film.html        # per-phase lane luma -> out/caption_luma.json
```
Run the export before `render_frames.js` (the scene loads `captions_data.js`) and the SRT step after it,
in place of the per-phase SRT. Feed the probe back once (`--luma`) and the lane picks ink per phase with
hysteresis: luma > 150 → dark ink + light pill; < 60 → bare light text; between → light + scrim 0.45.
Add `scenes/captions.json` to `qa.json → authored` so display substitutions pass hygiene / over-claims.

### Scene wiring (screen space, outside `#camera`)

```html
<div id="ovl"></div><div id="cap"></div>          <!-- z above footage, below #black -->
<script src="lib/captions.js"></script><script src="lib/overlays.js"></script><script src="captions_data.js"></script>
<script>
const lane = CAP.build(TX, Object.assign({ end: END + 1.2 }, window.CAPTIONS || {}));
function frame(t) { …
  const lt = OVL.lowerThird($('#ovl'), t, { id:'lt-nb', t0: P.nb + 0.2, dur: 4.8, label:'THE ANALYST',
                              text:'Build it where the data is.', variant:'auto', phase:'nb' });
  const co = OVL.callout($('#ovl'), t, { id:'co-late', t0: wt('nb','counts') - 0.2, dur: 3.6, zone:'lower-right',
                              kicker:'LATE DELIVERIES', value:{ from:0, to:23, dec:0 }, detail:'last week · 3 regions', style:'swiss' });
  OVL.hero($('#ovl'), t, { id:'h-gov', t0: wt('answer','governed') - 0.08, dur: 2.0, text:'governed', style:'ink' });
  lane.draw($('#cap'), t, { avoid: [lt.rect, co.rect] });      // lane bottom = overlay top − 24 px when they collide
}
</script>
```

## Overlay components (`OVL`, tokens at 1080p)

- **Lower third** `OVL.lowerThird(host, t, {id, t0, dur:4.8, label, text, variant:'card'|'cardless'|'dark'|'auto', accent, side, phase})`.
  Anchor left 120–130 / bottom 110–120 px. Card: clip-path inset(0 100% 0 0)→0 over 0.55 s power3-out at
  +0.10, accent tab scaleY 0.45 s at +0.28, line y22→0 0.5 s at +0.34, label at +0.44; exit y+18 + fade
  0.35 s power2-in. Cardless: line y28→0 0.55 s at +0.10, 6 px rule scaleX 0.5 s power4-out at +0.30, label
  y16→0 at +0.46; exit label 0.3 s, rule retracts 0.3 s, line lifts −16 px 0.32 s; text-shadow 0 2px 22px
  rgba(0,0,0,.45). Rule: cardless over clean footage, charcoal `#16181d` card over bright or busy footage —
  `variant:'auto'` decides from the probed luma. Cards follow the design tokens: radius ≤ 4, no drop shadow, and
  no accent stripe unless asked (`tab:false` is the house default — the sample's craft review found the 12 px
  stripe, 14 px radius and shadow all banned by `design.md`); the line starts with the wipe so the plate is
  never empty. Label ≥ 16 stage px. Give it ≥ 4.8 s so the exit plays, or 2 s for a short hand-off when one voice
  must own the hero line (the sample's ask beat). Labels are roles ("THE ANALYST"), never names; quote the copy
  verbatim.
- **Callout / stat card** `OVL.callout(host, t, {id, t0, dur, zone:'lower-right'|'lower-left'|'side-panel'|'glass', kicker, value:{from,to,dec,prefix,suffix}, detail, style:'swiss'|'minimal'|'terminal'|'glass'})`.
  Card fade 0.4 s power2-out + y12; kicker +0.05 (16 px 600 uppercase tracking 0.28 em); odometer
  `G.odo(from,to,t,t0+0.3,0.7,dec)` at 60 px 800; rule grow-x 0.5 s power3-out at +0.65; detail 26 px at
  +1.05; exit 0.35 s power2-in. Glass = solid rgba(15,16,22,.82) + radius 18 (no backdrop blur: first-frame
  decode differences between workers). Zones: lower band, right 42 % panel, 660×540 at (48,460).
- **Pull-quote** `OVL.quote(host, t, {id, t0, dur, kicker, lines, attribution, style:'editorial'|'minimal', zone})` —
  cream #f1e8d5 / ink #0e1018 / coral block, Georgia italic (literal quotation); kicker → words (step 0.1 s,
  fade 0.3 s) → rule → attribution. Quotes are verbatim from the narration or the screen.
- **Hairline / PiP frame** `OVL.hairline(host, rect, {accent})`, `OVL.pip(t, spec)` → geometry for the real
  screen shrinking to 460×258 at (1432,28) or 400×300 at (1480,760) over 0.6 s power2-inOut,
  `OVL.pipFrame(host, t, spec)` draws the pill ring (0 0 0 4px rgba(255,255,255,.7) + 5px rgba(0,0,0,.18),
  radius 14, shadow 0 24px 60px −20px) and the double-stroke viewfinder with 24 px corner ticks. Mark the
  transition `seam:true`; never during a typed or scroll beat; never a frame over full-bleed video.
- **Hero word** `OVL.hero(host, t, {id, t0, dur:2.4, text, style:'keynote'|'ink'|'documentary', apex, dim:0.12})`.
  ≤ 1 per beat, never two co-visible, ≥ 0.6 s air, ≤ `hero_max_per_film` (2), one apex per film. Size fits
  0.9·W from 0.22·h down to the 0.18·h floor (widen the box, never go smaller); apex tracks a short word up to
  +0.32 em toward 93 % of the usable width. Wipe-up 0.6 s power4-out, dwell ≥ 1 s, exit 0.45 s power2-in to
  opacity 0, a local 10–15 % plate under the word only. **Yield rule:** the lane dims to 0.55 from t0 − 0.2 s
  to t1 + 0.9 s and hides the promoted word's own group. Pick the payoff, not the topic; a promoted figure
  must be in `claims.json`; `ink` style over bright screens.

## Gates (`gates/overlay_gate.py`, measured by one puppeteer pass + a captions-off pass)

| gate | fails when |
|---|---|
| `overlays safe` | lane/hero outside title-safe (80 %, `overlay_safe_box`); lower third/callout/quote outside action-safe (90 %, `overlay_action_box`); any text > 8 px off-canvas (≤ 8 px warns); two visible overlays intersect; anything in the credit footer in the last 4 s. `data-ov-bleed="1"` opts a deliberate edge-kiss out. |
| `caption shape` | > `caption_max_words` (6; keynote 5), > 2 lines, line > `caption_max_chars_per_line` (42) or wider than 92 % of the box with the real TTF, < 0.5 s on screen, two groups co-visible. Warns on median cadence < 1.5 s and dangling 1-word lines. |
| `caption timing` | a word drifts > 80 ms from WORDS, a window does not envelop its words, SRT cues ≠ shown groups (count + 20 ms). |
| `caption contrast` | WCAG ratio (ink vs. real composited pixels under the glyphs, scrim composited) < 4.5, or < 3.0 for text ≥ 0.04·h at weight ≥ 600; light ink over a p95 luma > 180 (washout). Writes `out/caption_luma.json`. |
| `hero scarcity` | > `hero_max_per_film` heroes, two co-visible, < 0.6 s air. |

Sampling: a 0.5 s grid (`overlay_grid`) + every cut + 0.4 s + every caption mid-point; ~10 s per 40 s of film.
Everything is in `out/overlays.json` / `out/qa/capbg/` for inspection.

## Reviewer checklist (give the fresh-eyes reviewer only stills at caption mid-points + this list)

Five failures, any one blocks: **washout** (light text on a bright band), **text-on-text** (overlay over
product text), **reading order** (eye goes to the card before the UI the voice names), **hero presence**
(the promoted word is timid or two are up), **balance** (lane and lower third stacked on one side).
Five positives, pass ≥ 4: poster test (one still sells the beat), timid test (type has mass), one-glance
hierarchy at thumbnail size, scene handshake (≥ 2 of: accent from the UI, ink matches the band, card
aligns to the UI grid), dead-air audit (no caption lingering over a deliberate ≥ 1.5 s silence).

## Worked example (fictional Acme, `templates/captions.example.json`)

Phases hook → title → nb → ask → answer → close. `title` is dropped (the words are the title card),
`answer` runs the `typewriter` lane (the product's voice), `close` is `embed` in `keynote` ("ONE ANSWER /
THE WHOLE TEAM" · "CAN TRUST."). Overrides: `governed` in `answer` is an em word; a hero `governed` in `ink`
style lands at `wt('answer','governed') − 0.08` for 2.0 s while the lane yields. The probe reports
nb/ask/answer at luma ≈ 255 (white notebook), so the lane switches to dark ink for those phases and the
`auto` lower third renders the charcoal card; hook/close stay light on the dark cards.
