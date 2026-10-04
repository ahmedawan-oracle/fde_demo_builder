# Pair gate — the end frame is an edit of the start frame (v5.1)

A recreated beat's end frame should be its start frame with the state changed: the eyebrow where it was, the
headline where it was, the mark where it was, the new element landed where the plan said. `gates/pair_gate.py`
reads the first/last frame pairs (`gates/snapshot.py --pairs`) against the storyboard and says when the end frame
is a new picture instead. A segment is judged by the beat that owns its END frame (the frame the next cut lands on); a title segment that carries two storyboard beats gives beat 1 its START and beat 2 its END. Recorded beats are not compared — a product screen scrolls and carries a thousand
words by design.

## Three gates

| Gate | Measures | Fails when |
|---|---|---|
| `pair anchors` | the ink boxes in the top 35 % of the start frame (eyebrow, headline, mark — anything wider than 5 % of the frame), each located again in the end frame by normalised cross-correlation inside ±12 px | an anchor moved more than **2 px at 1080p**. An anchor that cannot be found at all is a WARN — unless the beat's `end:` says it leaves (*gone, leaves, exits, cleared*) |
| `pair words` | the words OCR reads on the end frame | a word that is in none of: the beat's `end:` sentence, its quoted on-screen strings, `screen:` / `motion:` / `caption:`, or a `claims.json` phrase (digits and 1–2 letter tokens are free) — an element the plan never named |
| `pair roster` | the named entities (Title-case tokens) on the start frame vs the end frame | a name that arrives on the end frame that neither the `end:` sentence, the beat's quoted on-screen strings nor its `screen:` names (the mandatory credit is always allowed) |

OCR runs through the backends the leak gate uses (`gates/leak_gate.py pick_backend`, the fast one first).
Without an engine the two OCR gates PASS with a `WARN no OCR engine` note — never a silent pass; the anchor gate
needs no engine and always runs.

## Why pixels for the anchors

A headline that drifts 3 px between the first and the last frame reads as a flicker at the cut and as sloppiness
on the pair sheet; nobody notices why. Normalised cross-correlation of the start box inside a small window of the
end frame finds the shift to the pixel without reading the words, so the gate works on a mark, a rule or a
kicker as well as on text. 2 px at 1080p is the tolerance an anti-aliased edge needs and nothing more.

## Reading a failure

- `anchor at (60,90 461x51) moved 6.0 px` — the headline's block sits lower on the end frame: a layout that reflows
  when the sub line lands. Give the sub line its own slot.
- `on the end frame but not in the plan: Quarterly, Revenue` — the scene draws words the storyboard never wrote.
  Either the `end:` line is incomplete or the scene invents copy; fix the one that is wrong.
- `names that arrive without the end: line saying so: northwind` — a newcomer. Name it in `end:` or cut it.

qa.json: `{"pair": {"anchor_px": 2, "search_px": 12, "top": 0.35, "min_box": 0.05}}`.

Selftest: `python gates/pair_gate.py --selftest` — drawn frames (unchanged anchors, a 3-px drift, a vanished
headline) and a stub OCR backend that returns the words we drew; the whole gate on a two-beat project, and the
no-engine path.
