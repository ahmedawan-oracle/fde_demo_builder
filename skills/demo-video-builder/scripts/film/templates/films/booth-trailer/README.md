# Film template — booth trailer

**When to use it.** A 30–45 s film for a screen that nobody is listening to yet: an event booth, a lobby wall, a
LinkedIn feed. One product, one hero question, one figure that lands. The viewer decides in the first four
seconds whether to stop walking, so the grammar spends its energy at the open and the proof, and holds still
everywhere else. Loops (the `booth_loop` export pads the tail so the restart lands on the head fade).

**Not for:** a story that needs context (use `customer-story`), or more than one feature (use `feature-walkthrough`).

## What is pre-wired

| File | What it fixes |
|---|---|
| `STORYBOARD.md` | six beats, 36 s: cold open → title → product full screen → answer lands → proof figure → close; every field filled with this template's grammar — change the words, keep the shape |
| `seams.json` | cut-the-curve on the current (leftward), ONE `zoom-through` reserved for the push into the product, ONE `gl` accent (`flashWhite`, cause `impact`) into the proof card; nothing else is allowed |
| `captions.json` | `keynote` lane; the hero question in `karaoke` (the spoken word lights up), the closing line `kinetic`; title and close cards `drop` (their words are already on screen) |
| `skin.json` | `skins/ember.json` — warm near-black ground, ember accent, `high` motion profile, keynote captions. `signal.json` is the light alternative |
| `film.json` | captions `.ass` sidecar on, chapters on (`--merge` because the film is under 60 s), synthesized SFX on (whoosh on cuts, one impact per act, tick on the figure landing, riser into the proof), bus chains on, bed breathe at seams |

## Grammar (what the viewer sees)

- **0–5 s** the pain in one line, built word by word (`TYPO.centerBuild`), one figure counting up to the spoken number (`BL2.countUp`), a `GL.chromaSplit` only if the words earn it.
- **Title** three seconds, shard or lockup (`T3D.shardTitle` / `TYPO.lockup`), honesty caption under it.
- **Product** opens on the ORIGINAL full screen for ~1 s, then one push (×1.4–1.8, 0.9 s on the `high` profile); redrawn cursor if telemetry exists; the hero question lights up word by word in the lane.
- **Answer** pull back to the whole screen, then a punch onto the spoken figure with `ANNOTATE.circle` on that figure only — never across product text.
- **Proof** the one card that may glow: `BL2.countUp` landing on the word, `LIGHT.bloom` on the card, `DEPTH.planes` behind it; the only `gl` seam of the film brings it in.
- **Close** `TYPO.lockup`, `REVEAL.pullBack`, hold; the mandatory credit is stamped by the build.

Scarcity rules the gates enforce: one accent seam, one slam, one hero per beat, no SFX within 0.15 s of a word.

## Using it

`/new-film <name> --template booth-trailer` copies these six files over the base scaffold (`STORYBOARD.md`, `seams.json`,
`scenes/captions.json`, `film.json`; `skin.json` is read and its path written into `film.json` `"skin"`). Then:

```
python tools/skin_apply.py skins/ember.json          # scenes/skin_data.js + design.md tokens (build_film.py repeats this)
python tools/brand_kit.py --from-skin skins/ember.json --sheet out/style_sheet.png     # look pass: approve before the sketch
python tools/storyboard.py check STORYBOARD.md       # the skeleton passes as a plan; fill the <…> fields, then lock
```

Studio taps for the review pack go to `out/taps/NN_<label>.jpg` (beat number, then a short label) — `tools/studio.py`
writes them there and `tools/review_pack.py` reads them in that order.

Everything in this template is fictional (Acme, synthetic data). The credit line is never reworded or moved.
