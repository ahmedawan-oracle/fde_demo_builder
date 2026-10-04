# The cut list — the edit as text, round-tripping with `play{}` (v5.1)

A footage shot that plays real motion is five numbers: which clip, how long the slot is, where in the clip to
start, how fast, and which way. Written as one text row per shot the edit can be read, diffed, reviewed in a
message and regenerated; the numbers flow into `scenes/shots.js` as `play{}` and back out of `out/timeline.json`.
Code: `tools/cutlist.py`, `lib/footage.js` (`play.to`, `play.reverse`, `FOOT.seqFrameIndex`).

## The list

```
# clip     length   start   speed   reverse
send       2.20     0.45    1.0     no          start = seconds into the source clip; speed 1.0 = real time
wizard     3.00     auto    fit     no          auto = the window with the most motion; fit = speed to the slot
answer     1.50     0.00    1.0     yes         reverse = play the window backwards
```

`length` is the slot on the clock (`t1 − t0` of the shot); the narration decides it and the list never shortens it.

## The round trip

```
python tools/cutlist.py export                       # out/timeline.json shots[].play + broll meta → cutlist.txt
python tools/cutlist.py resolve cutlist.txt          # fills auto / fit → cutlist.resolved.txt (from= to= pad= per row)
python tools/cutlist.py emit cutlist.resolved.txt    # → scenes/cutlist_data.js: window.CUTLIST = {clip: {from, to, rate, reverse, pad}}
python tools/cutlist.py check cutlist.txt --check-length
python tools/cutlist.py render cutlist.resolved.txt  # ffmpeg preview of the list, no browser
```

In `shots.js` the cue stays a cue and the numbers come from the list:

```js
{ t0: SEND, t1: ANSWER_AT, clip: 'send', play: Object.assign({ at: SEND + 0.45 }, CUTLIST.send), … }
```

`from = round(start·fps) + 1` (1-based source frame), `rate = speed`, `to = from + ⌈length·fps·speed⌉ − 1` bounded
by the clip, `reverse` rides through. `lib/footage.js` holds the frame at `to` once the window is spent (and the
frame at `from` when reversed) — the end state is cloned, never trimmed. `export_timeline.js` writes `play{}` back
into `timeline.json` (functions such as `map` are dropped), so `export` regenerates the list from the scene.

## The three options

- **`--auto-window`** (`start: auto`): the frame differences of the clip (its `f_*.jpg` frames, or an mp4) are summed
  over a sliding window of `length·speed` seconds; the window with the most motion wins. The product shot opens
  where the product does something, not at second zero.
- **`--fit`** (`speed: fit`): `speed = available frames / required frames`. A clip longer than its slot plays faster,
  up to `--max-speed` (1.6; beyond it the window is trimmed and the row says so — faster than that reads as a
  glitch). A clip shorter than its slot plays at 1.0 and its end state is held: `pad` frames clone the last frame
  (`tpad=stop_mode=clone` in the preview; `footage.js` does the same by construction). Speed to fit, never trim
  the slot: the narration is the clock.
- **`--check-length`**: each row's length equals its shot's `t1 − t0` within one frame and the rows sum to the span of
  their shots; a list that does not add up fails before anything renders.

`reverse` is a real tool — a pull-back cut from a push-in, an undo shown as an undo — and the frame index is exact
(`FOOT.seqFrameIndex` is a pure function; the selftest runs it under node against the list's own numbers).

## Version N+1 from N

`python tools/cutlist.py bump v3.txt v4.txt --replace 'old=new' --previous-film out/<film>_v3.mp4` writes the next
list by text replacement and records the changed clips in `out/cutlist_bump.json`; after the render,
`gates/identity_gate.py` proves every untouched shot has the same frame count and the same mean colour per frame
(≤ 0.5 ΔE) as the previous render. → `identity-and-bump.md`

## What it does not do

It does not edit `shots.js`. The scene reads `CUTLIST.<clip>` from the generated data twin, the same way it reads
`claims_data.js` and `seams_data.js`; a hand-written `play{}` still works and `export` reads it back. It does not
touch footage pixels: speed is frame selection, reverse is frame order, pad is a held frame.

Selftest (no browser): `python tools/cutlist.py --selftest` — synthetic frame sequences, auto-window on a square that
crosses the frame, fit with a cap and with a pad, the play round trip, `--check-length`, an ffmpeg preview whose
reversed clip darkens frame by frame and then holds, and `footage.js` playing the same numbers under node.
