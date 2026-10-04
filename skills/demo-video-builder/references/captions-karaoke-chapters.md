# Karaoke and kinetic captions, .ass sidecars, chapters (v5)

`lib/captions.js` styles `karaoke` and `kinetic`, `tools/captions_ass.py`, `tools/chapters.py`. Same
contract as the rest of the lane (`references/captions-and-overlays.md`): pure functions of the narration
clock `t`, groups computed once from the word times, identical in node and in the browser, nothing touches
the footage lane. Examples are fictional (Acme).

## Karaoke — the spoken word lights up

A word has three ages and one envelope:

| age | opacity | colour | weight | scale |
|---|---|---|---|---|
| future | 0.55 | ink | body (600) | 1.0 |
| spoken (attack 0.12 s) | → 1.0 | ink → accent `#E8C874` | 600 → 700 (cross-fade) | pulse to 1.06 at 0.06 s, back to 1.0 at 0.12 s |
| past (release 0.3 s) | → 0.82 | accent → ink | 700 → 600 | 1.0 |

- **No layout shift.** Each word is two layers: a bold layer *in flow at opacity 0* (so the word's box is already
  the bold width) and the regular layer absolutely centred on top. Lighting a word cross-fades the two; nothing
  is re-measured, so neighbours never move. Weight and size are never animated on a span.
- **The pulse is a sine bump**, `1 + 0.06·sin(π·u)` over 0.12 s: it peaks mid-onset and is exactly 1.0 when it
  ends, so a run of short words never accumulates scale. The rail cap of 1.10 still applies.
- **Short words never jump**: the release starts from whatever level the attack reached.
- Use it on the hero question and on quoted product text; not on fillers, not on the credit. `em` words keep
  the accent at rest and still take the pulse.

`CAP.karaoke(t, word, env)` → `{op, u, sc}`; `env` defaults to `{attack .12, release .3, rest .82, future .55,
scale .06, pulse .12}`. Style tokens: Segoe UI 600/700, 0.045·h, bottom 112 px, ≤ 6 words / 42 chars / 2 lines.

## Kinetic — word waterfall in, block out

- Word *i* arrives at `in + Σ_{j<i} 0.06·0.84^j`, cumulative delay capped at 0.3 s (0, .060, .110, .153, .188,
  .218, .243, .264 …), each rising 10 px and fading up over 0.25 s on power3.out. The whole caption leaves as one
  block (0.18 s, 8 px, exit ≈ 70 % of the entrance).
- The style opens its window 0.3 s before the first word (`lead` token) so the waterfall is finished when the
  voice arrives; the previous group therefore ends 0.05 s earlier than it would before an anchor group.
- For recreated beats and chapter lines; never on top of readable product text.

`CAP.waterfallDelay(i, {gap0, decay, cap})` is the same arithmetic `MOTION.cascade` uses, so a lower third
and a caption that enter together land on the same beat. Pick styles per phase in `scenes/captions.json`:
`"phases": {"ask": {"fate": "rail", "style": "karaoke"}, "close": {"fate": "rail", "style": "kinetic"}}`.

## .ass sidecar with per-word timing — `tools/captions_ass.py`

```
node scenes/lib/captions.js scenes/timing_film_data.js scenes/captions.json --out out/caption_groups.json
python tools/captions_ass.py out/caption_groups.json --out out/film.ass --srt out/film.srt --vtt out/film.vtt \
       --overrides captions_overrides.json --burn
```

- Input is the groups file the burn-in draws from (or `timing_*_data.js` / `vo/<name>_words.json`, run through
  the same node grouper). Burn-in, .srt, .vtt and .ass can therefore never disagree.
- Every word is a `{\kN}` syllable, N in centiseconds, rounded on the cumulative clock (a 12-word line drifts
  < 1 cs). A silent lead syllable carries the 0.08 s air before the first word; the gap to the next word belongs
  to the word before it, so nothing flickers. Line breaks are the lane's own (`\N`, WrapStyle 2).
- One style row per lane style at PlayRes 1920x1080: Fontname from the family (Segoe UI Semibold for 600,
  Bold for ≥ 700, Consolas for mono), Fontsize = round(sizeH·720)·1.5 (48 body / 54 kinetic), Outline 1.5 /
  Shadow 2.5 at 50 % / 63 % black, MarginL/R 192 (= 80 % box), MarginV 112, Alignment 2 / 1 (left styles) / 5 (embed).
- Karaoke carries over as SecondaryColour = ink at 55 % plus per-word `\t` to the accent on onset and back to
  ink at 82 % on offset. The bold cross-fade and the pulse are deliberately *not* emitted: `\b` / `\fscx` inside
  a libass line re-measure the run and shift neighbours — the sidecar carries colour and alpha only. Kinetic
  carries over as per-word alpha ramps on fill, outline and shadow (outline starts transparent too, or libass
  draws a dark ghost of unarrived words).
- `captions_overrides.json`: `{"<phase>:<i>": {"text"?, "t0"?, "t1"?}}` — prefer the `phase:i` form; running
  word indices move whenever grouping changes. Unknown keys and reversed spans are findings (exit 1). Add the
  file to `qa.json → authored` so display substitutions pass the hygiene and over-claims gates.
- `--burn` prints `ass='C\:/…/film.ass'` for the v1/v2 timeline or `export.py`. ffmpeg must be built with libass
  (`ffmpeg -filters | grep ass`). Selftest: writes the .ass twice (byte-identical), burns it onto a 2 s navy
  clip and asserts ≥ 300 lit pixels in the bottom 40 % at three times.

## Chapters — `tools/chapters.py`

```
python tools/chapters.py STORYBOARD.md --seams seams.json --phases vo/film_phases.json --out out [--merge]
```

- Boundaries, in order of intent: a beat's `- chapter: <title>` (or `yes` → the beat title) › a change of
  `- act:` › every beat. The first chapter is pinned to 00:00; the last ends at the frontmatter `duration`,
  else the measured total, else the last beat's `t1`.
- Times: the beat's `phase:` start from the narration replaces the planned `t0`; then each start snaps to the
  nearest seam **cut** within 0.75 s (a chapter begins on a cut, never mid-shot). Cue expressions (`P.nb`,
  `wt('ask','question') + 0.1`) resolve from the timing data without `eval`; `seam: true` hand-offs are not cuts.
- Rules: a chapter ≥ 10 s and a title ≤ 40 chars are failures (video platforms reject shorter chapters and
  truncate longer titles; a booth viewer cannot read a shorter one). Fewer than 3 chapters, duplicate titles,
  and a chapter mixing `recorded` with `placeholder` beats are warnings.
- `--merge` folds the shortest short chapter into its *shorter* neighbour, keeping the longer part's title, so a
  32 s film becomes two balanced chapters instead of everything cascading into chapter 1. `build_film.py`
  passes `--merge` when the film is under 60 s. Every merge and snap is written to `chapters.json` and `timeline.md`.
- Outputs: `chapters.vtt` (one cue per chapter), `chapters_youtube.txt` (`mm:ss Title`, floor-rounded,
  `h:mm:ss` past one hour), `timeline.md` (chapters → beats → first narration → truth tags → notes),
  `chapters.json`. Pure functions of the inputs: run twice, diff nothing. Exit 0 ok / 1 findings / 2 usage.

## Checklist

- karaoke on ≤ 2 phases per film (the hero question, one quoted answer); kinetic on recreated lines only
- `captions_overrides.json` in `qa.json → authored`; `phase:i` keys
- `.ass` + `.vtt` + `chapters.vtt` + `chapters_youtube.txt` travel in the share pack; `.ass` is the burn source
  for v1/v2; the `youtube` export preset appends the chapter block to `DELIVERY.md`
- chapters: run after the narration exists (`--phases`), with `seams.json`, and read the FAIL lines before `--merge`
- gates: `caption shape / timing / contrast` (`overlay_gate`, unchanged — the lane box carries
  `data-cap-style`); `captions_ass.py` and `chapters.py` exit 1 on findings and the build reports them
