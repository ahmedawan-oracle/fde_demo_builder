# Real-pixel footage (v3)

Viewers trust a demo when the product on screen is the product — not a mock-up, not a re-typed answer.
v3 drives **the recording's own pixels** on the film clock: real scrolls, real typing, real motion, and
camera moves that always start from the original full screen. Tools: `film/extract_clips.py` (pixels)
and `film/lib/footage.js` (placement). Template: `film/film.example.html` + `film/shots.example.js`.

## 1. Map the recording first (shot log)

Scrub the capture at 1 fps and write `SHOTLOG.md` before touching code:

| Column | What to note |
|---|---|
| time range | where each screen lives, to 0.1 s |
| state | parked (nothing moves but the pointer) / scrolling / typing / loading / zoomed |
| scroll area | the rectangle that scrolls (`band` = x, y, w, h) vs the fixed chrome around it |
| baked zooms | where the presenter zoomed the recording itself (you'll need to invert them) |
| leaks | anything private (emails, tokens, other customers) and where it sits |
| on-screen claims | every number or statement the narration may cite, with its time |

## 2. Clip kinds

| Kind | Use it for | Key trick |
|---|---|---|
| `still` | a screen that doesn't change | `win:[t0,t1], n` = per-pixel **median** of n frames: text stays exact, the wandering pointer, caret blink and hover states vanish |
| `seq` | real motion (a send, a spinner, a chart drawing) | plays at 30 fps on the film clock: `play:{at, from, rate, loop:[a,b]}` |
| `page` | a long document the presenter scrolled | stitch the **parked scroll positions** into one tall page (`layers[].off` = doc y); later layers skip their top `trim` px so no half-clipped row sits on a seam |

A film that cuts between several recordings gives each clip its own `"file"`; long speed-ramped sequences can set
`"fps": 15` and `"width"` to keep the frame count and disk size sane; `--out DIR` writes somewhere other than `broll/`.

`page` + `chrome` also saves the original full screen for each parked position (`chrome_k.jpg`). The film
draws the page inside the app's real chrome, and swaps the chrome as the scroll passes each position, so
the app's own state (table-of-contents highlight, scrollbar thumb) follows the scroll.

Baked-in zoom: measure two landmarks at 1.0x and zoomed, solve `x' = s·x + tx`, and give the layer
`unzoom: [s, tx, ty]`. Take chrome for that position from an unzoomed frame (`chrome.layers[k] = {"t": …}`),
because the inverted frame has empty edges.

## 3. Original screen first, then the zoom (mandatory framing rule)

Every product beat **opens on the whole, original screen** at 1.0x, holds ~0.9–1.6 s, then pushes into the
region of interest (sine-in-out, 1.0–1.4 s). Viewers must see where they are before they see detail.

Write each shot in the view you think in (the page band, or a crop), then let `FOOT.fullscreen(SHOTS, VIEW)`
map it onto the full screen and add `establish: {hold, dur}`. Moves with `abs: true` are already in
full-screen coordinates (pull back to the whole screen: `{s: 1, c: [640, 360], abs: true}`).

## 4. Typing that is real

If the presenter pasted or typed fast, uncover the **already-typed glyphs** word by word as the voice
speaks them (`reveal`). Measure the line and word ends with:

```bash
python extract_clips.py --word-ends recording.mp4 15.0 520 982 1500 1012
```

Voice the question **exactly as it appears on screen** so each spoken word maps to one on-screen word.
Then hand off to the real send frames with a `seam: true` seq shot (QA won't count it as a cut).

Streaming answers: `stream: {t0, dur, from, to}` lowers a curtain top-down over a finished answer.

## 5. Repaint vs mask vs leave alone

| Content | Default | Tool |
|---|---|---|
| Private data: emails, tokens, OCIDs, other customers' names, personal bookmarks | **mask** | `blur` fix |
| A baked-in pointer or tooltip on blank space | erase | `fill` fix with the sampled background |
| Demo-authored words you're renaming (headings, prose, TOC entries) | repaint | `word` fix: measures cap height (including antialiasing) and ink colour, redraws; `bg: "mode"` on highlighted rows |
| Real code, API names, tool labels | **leave as recorded** | never rewrite code; ask the owner before masking it |

Many reviewers want the real product untouched. Ask before masking anything that isn't private.

## 6. Checks before rendering

- `node check_cues.js scenes/timing_film_data.js scenes/shots.js scenes/film.html` → every `wt()` resolves.
- Snapshot stills around every beat (full screen → push → detail) and look at them.
- No freeze longer than ~5 s: add a slow push (`drift`, or a 2–3 %/s move) on long holds.
