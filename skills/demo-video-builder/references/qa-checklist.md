# QA checklist

A demo isn't done until an adversarial pass finds nothing. Run `build.py`'s built-in QA, then the
`demo-qa-reviewer` agent, fix everything, and rebuild. Re-verify after every rebuild.

## Automated (build.py prints these)
- **Decode integrity** — `ffmpeg -v error -i out/demo.mp4 -f null -` returns clean (no errors).
- **Silence gaps** — `silencedetect` finds no gap > 0.8 s (i.e. every screen is narrated).
- **Contact sheet** — `out/qa/contact.jpg` for a whole-video eyeball.

## Privacy (hard gate — see privacy-scrubbing.md)
- [ ] No address-bar URL / token / tenancy id anywhere.
- [ ] No bookmarks bar, no extension badges, no "update available" banners.
- [ ] No username / email / avatar (app header, composer, taskbar).
- [ ] No internal names typed in fields (Name/Description/Instructions).
- [ ] No other customers/other data on any list page.
- [ ] Chrome-cover bar color matches the app (no odd letterbox line).
Sample frames at the start/middle/end of every beat and every scroll/focus moment; **look** at each.

## VO sync
- [ ] Every number spoken is visible on screen at that moment.
- [ ] No heavy slow-motion (time-fit factor near 1.0; use freeze instead).
- [ ] Answers stay on screen (or frozen) through their number-heavy narration.
- [ ] Narration is continuous; no dead air on any screen.

## Readability & framing
- [ ] Answer text/tables are legible (zoom in if not).
- [ ] Original framing preserved (unless a crop was requested); no content clipped off the sides.
- [ ] Transitions between beats aren't jarring; cuts land on stable frames.

## Content accuracy (no fabrication)
- [ ] Every figure/label read from the real recording, not invented.
- [ ] If data is synthetic/sample, the opener/outro don't claim it's production/real.
- [ ] Product/feature names are correct; no customer names anywhere in the video.

## Playback
- [ ] Plays start-to-finish to the outro (not cut off). Verify duration and the last second's frame.
- [ ] Uniform 1920×1080 / 30fps h264 + aac; ~sane file size.

## The loop
Find issues → fix in `demo_config.py` (spans/masks/vo/zoom/freeze) → `python gen_vo.py` (if VO changed) →
`python build.py` → re-verify. Repeat until the adversarial pass is empty.

## Mandatory credit (every video)
- [ ] The last seconds show, centred in the footer: **Crafted with FDE Demo Builder · by Ahmed Awan**.
      `python credit.py check out/<video>.mp4` → PRESENT. Missing, reworded, cropped or covered = BLOCKER.

## v4 / v5 film gates

`python qa_film.py --profile=picture` runs the 12 picture gates; `--profile=full` runs every plug-in module
(seams, camera, overlays, audio, lint, canary, golden, text, grade, ledger, leaks, sfx, reveals, charts,
annotation, skins). The index with every gate and its rule is `qa-gates.md`; the
`demo-qa-reviewer` agent's v5 blockers are leaks, recoloured or transitioned-over footage, chart values
without a claim, marks off their evidence, and the credit.

## v3 film gates (`python qa_film.py`)
container · duration vs narration · open frame · black frames · cuts land (relative) · blank after cut ·
no freeze > 5 s (640x360) · loudness −16 LUFS / TP ≤ −1 · required lines · no over-claims (rendered text,
comments stripped) · hygiene patterns · claims traced to the screen (`claims.json`) · captions · **CREDIT**.
Measure a failing gate before changing it: most "false" failures are real (a card that sits still, a cut to
white-on-white, a claim the screen never shows).
