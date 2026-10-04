# Shot spec — a shot's own contract (v5.1)

One line of constraint per beat in the storyboard is a sentence; a shot can also carry a machine-checkable contract in
`shots.js`:

```js
{ t0: ANSWER_AT, t1: P.close, clip: 'answer', seam: true,
  spec: { forbidden: ['TODO', 'lorem', 'placeholder'], claims: ['regions_over_target'], references: ['Study A'] } }
```

`export_timeline.js` writes `spec` into `out/timeline.json → shots[].spec`; `gates/spec_gate.py` reads the rendered film.

| Gate | Checks | Verdict |
|---|---|---|
| `spec forbidden` | frames at t0 + 0.5 s, the midpoint and t1 − 0.5 s of every shot with a `forbidden` list are OCR'd (the leak gate's engine); a listed token on any of them — case-insensitive, whole word, OCR confusions tolerated (l/1/I, O/0, S/5) | FAIL with shot, time and word; WARN-pass without an engine |
| `spec claims` | every entry resolves in `claims.json` — a `figures[].id`, a `claims[].id`, or a verbatim phrase | FAIL: a shot that promises a figure the film never traced |
| `spec references` | every name is a logged title in `refs.json` (tools/ref_study.py) | WARN only |

Why on the shot and not only in the storyboard: the storyboard's `constraint:` is read by people; the spec is read
by the gate against the pixels the shot actually rendered. Use `forbidden` for the words that must never leak into a
product frame — a build tag, a placeholder, a colleague's name the leak gate's denylist does not carry; use `claims`
to bind the shot to the figure it exists to show.

Selftest: `python gates/spec_gate.py --selftest` — a synthetic film, a stub OCR that returns known words per frame
(a `BETA` tag and a `T0DO` caught), claims by id and by phrase, an unlogged reference, the no-engine path.
