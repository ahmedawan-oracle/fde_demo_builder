# Film template — feature walkthrough

**When to use it.** A 60–120 s film that shows two or three features of one product, each as its own chapter a
viewer can jump to: a release note with pictures, a partner enablement clip, a docs page video. Watched at a desk
with the sound on. The grammar is medium-paced and technical: full screen first, then a push to where the
presenter works, a redrawn cursor and a keystroke pill, idle time ramped out, one recreated result card per feature
that lands on the real answer.

**Not for:** a passer-by screen (use `booth-trailer`) or a narrative with a person in it (use `customer-story`).

## What is pre-wired

| File | What it fixes |
|---|---|
| `STORYBOARD.md` | nine beats, 90 s: hook → title → feature one (real, chapter) → result card → feature two (real, chapter) → result card → feature three (real, chapter) → recap → close |
| `seams.json` | cut-the-curve on the current; `zoom-through` (z+1) into each feature's screen — one reserved vector per act, as the doctrine allows; `rack-focus` once, into the recap; no `gl` rows |
| `captions.json` | `broadcast` lane; chapter lines (the hook and the recap) `kinetic`; the hero question of feature one `karaoke`; result cards `drop` |
| `skin.json` | `skins/meridian-dark.json` — charcoal ground, electric teal accent, `medium` profile, broadcast captions. `mint-ledger.json` is the light alternative |
| `film.json` | `.ass` sidecar, chapters on (one per feature, no merge), SFX on (tick on landings, ui-confirm on the result cards, one impact per act, no riser), bus chains, bed breathe at seams, caret/cursor telemetry expected (`events.jsonl`) |

## Grammar (what the viewer sees)

- **Hook** one line, `TYPO.centerBuild` on the `medium` profile (0.4 s power4.out); the job the feature does, not its name.
- **Title** `TYPO.lockup` with the feature's name and the honesty caption.
- **Each feature** opens on the ORIGINAL full screen (~1 s) → one push ×1.4–1.8 over 1.1 s to where the presenter works (`tools/camera_from_events.py` proposes it from `events.jsonl`, snapped to the nearest spoken word) → `CURSOR` redraw with click rings, `HUD` keystroke pill → `tools/idle_detect.py` ramps spinners and dead air → hold ≥ 2 s.
- **Result card** `BL2.receipt` or `BL2.decisionCard` lands on the real answer's words (`ui-confirm` on the stamp); `LIGHT.sweep` once per card.
- **Recap** `BL2.sceneCards` — one card per feature, cut-the-curve between them, `rack-focus` into the set.
- **Close** `TYPO.lockup`, `REVEAL.pullBack`, hold; the credit lands.

Chapters: every feature beat carries `- chapter: <title ≤ 40 chars>`; `tools/chapters.py` snaps each start to its cut and
writes `chapters.vtt` + the YouTube block the share pack carries.

## Using it

`/new-film <name> --template feature-walkthrough` copies these six files over the base scaffold. Then:

```
python tools/skin_apply.py skins/meridian-dark.json
python tools/brand_kit.py --from-skin skins/meridian-dark.json --sheet out/style_sheet.png
python tools/record_events.py --out events.jsonl        # while recording (Windows); or accept cursor_track.py proposals
python tools/storyboard.py check STORYBOARD.md
```

Studio taps for the review pack: `out/taps/NN_<label>.jpg`. Everything here is fictional (Acme, synthetic data); `events.jsonl`
is confidential and stays out of the repo. The credit line is never reworded or moved.
