# Film template — customer story

**When to use it.** A 90–150 s film with a person in it: a team, a Monday, a question that used to cost a day.
Watched with the sound on, often in a bright room (an executive briefing, a conference session, a customer's
own all-hands). The grammar is calm: long product beats on the original full screen, a slow push, one figure per
beat, a before/after that is pixel-exact on both halves, and a closing card that holds still. Nothing glows.

**Not for:** a passer-by screen (use `booth-trailer`) or a feature tour (use `feature-walkthrough`).

## What is pre-wired

| File | What it fixes |
|---|---|
| `STORYBOARD.md` | nine beats, 120 s: open on the customer → the situation (real) → the turn → the work where it lives (real, chapter) → the question (real, hero) → the answer traced (real) → what changed (before/after) → the team today (real) → close |
| `seams.json` | cut-the-curve only, plus ONE `inverse zoom-through` (z−1, arrival) into the "team today" beat; no `gl` rows — a story is not a trailer |
| `captions.json` | `ink` lane (dark ink on the light paper); the hero question in `karaoke`; no kinetic; title and close cards `drop` |
| `skin.json` | `skins/paper.json` — warm paper ground, serif display, oxblood accent, `calm` profile. Light ground: the head fade opens from the paper, never from black. `noir.json` is the dark alternative |
| `film.json` | `.ass` sidecar, chapters on (acts become chapters, no merge: nine beats over 120 s give ≥ 3 chapters of ≥ 10 s), SFX on but quiet (−18 dB bus, whoosh and tick only — no impact, no riser), bus chains, bed breathe only (no swell) |

## Grammar (what the viewer sees)

- **Open** a still card in the skin's serif, one line built slowly (`TYPO.centerBuild`, 0.6 s power4.out), the honesty line spoken and shown.
- **Real beats** 12–20 s each; open on the ORIGINAL full screen for ~1 s, one push ×1.3–1.6 over 1.4 s, hold ≥ 2.5 s; `STAGE.mount` frames a still with a window bezel on a mesh wallpaper when the recording is a bare browser.
- **The question** `karaoke` on the typed line; the typed words are the spoken words.
- **The answer** `ANNOTATE.underline` or `circle` on the spoken figure, never across product text; the figure is a claim.
- **What changed** `COMPARE.wipe` or `split` of two real stills (both halves pixel-exact) with `BL2.countUp` on the before/after claims; `CHART.bars` only over `claims.json` values.
- **Close** `TYPO.lockup`, hold; the credit lands on the still read.

The `calm` profile forbids rack focus and keeps every entry at 0.6 s; the gates hold the film to it.

## Using it

`/new-film <name> --template customer-story` copies these six files over the base scaffold. Then:

```
python tools/skin_apply.py skins/paper.json
python tools/brand_kit.py --from-skin skins/paper.json --sheet out/style_sheet.png
python tools/storyboard.py check STORYBOARD.md
```

Studio taps for the review pack: `out/taps/NN_<label>.jpg`. Everything here is fictional (Acme, synthetic data); a real
customer's data appears only with their approval, and the honesty line changes to say so. The credit line is never
reworded or moved.
