# Audio: carve the bed, even the cast, cut on bars (v3.1)

`scripts/film/audio/` holds three libraries that return ffmpeg filter **fragments** (strings) and JSON facts;
`build_film.py` splices them into its graph and never shells out through them. `gates/audio_gate.py` checks
the result on the pre-master stems. Everything is deterministic: the narration's word times drive the duck,
the bed's own onsets drive the grid, numpy does the analysis (no librosa, no runtime, no credentials).

## 1. Carve, don't duck (`audio/carve_bed.py`)

Today's mix pulls the WHOLE bed down under speech (`sidechaincompress` thr 0.04 ratio 4 release 500) — the
music goes limp for the whole narration and pumps between words. A carve dips only the bands the voice
occupies and lets the low end and the air keep playing.

Measured (ffmpeg 8.1.1, pink bed, gated 220 Hz voice): a 250–2500 Hz-only sidechain (thr 0.03, ratio 6) drops
the **mid band 9.7 dB** under the voice while the **whole bed moves 1.3 dB**; the old full-band duck on a
−9 dB bed pulled it a further 4.9 dB everywhere. The selftest reproduces 9.9 dB in-band.

```
python audio/carve_bed.py vo_film.mp3 --strength 0.5 --json out/carve_film.json     # prints the fragment
carve_fragment(vo_path, bed_label, sc_label, out_label, mode='dynamic', strength=0.5, split=None,
               ratio=6, threshold=0.03|'auto', attack_ms=15, release_ms=2000, level_match=False,
               static_depth=0.5, gain_label=None, json_out=None) -> str
```

The analysis (the bands are measured, not guessed): decode the assembled VO to mono 48 kHz → Welch power
spectrum, FRAME 4096 / HOP 2048 / Hann, **every** hop averaged → score nine third-octave candidates
160/250/400/630/1000/1600/2500/4000/6000 Hz by `10·log10(band power) − bias·30 dB·(1 − e^(−(log2(f/2000))²/2))`
(a penalty in dB: a multiplicative weight has ≤ 5 dB of authority against speech's 20–30 dB tilt and always
picks the fundamental) → keep the top N → depth = maxCut × 10^((score − top)/10), floored at maxCut/2.

| strength | max cut | bands | Q | bias | duck | headroom | reads as |
|---|---|---|---|---|---|---|---|
| 0.25 | 6 dB | 3 | 1.4 | 0.7 | 6 dB | 9 dB | "music got out of the way" |
| **0.5 (default, TTS)** | 10 dB | 4 | 1.7 | 0.8 | 12 dB | 12 dB | starts to read as an effect |
| 0.8 | 14.8 dB | 6 | 2.06 | 0.92 | 19.2 dB | 15.6 dB | six cuts 250–2500 ≈ −7.4 dB each |

Formulas: maxCut 2 + 16·s · bands round(1 + 6·s) in 1..6 · Q 1.1 + 1.2·s · bias min(1, 0.6 + 0.4·s) ·
duck 24·s · headroom 6 + 12·s. TTS voices are already compressed — 0.5 is plenty.

Fragment, mode `dynamic` (default). The caller supplies `[bed]` (stereo fltp 48 kHz, level + fades applied)
and `[vsc]` (a copy of the upmixed voice); the fragment splits the key itself when it needs two copies:

```
[bed]equalizer=f=400:width_type=q:w=1.70:g=-2.50,equalizer=f=1600:…:g=-5.00[_cv_bq];      ← static room, HALF depth
[_cv_bq]acrossover=split=356 2806:order=4th[_cv_lo][_cv_mid][_cv_hi];                    ← Linkwitz-Riley, sums flat
[_cv_mid][vsc]sidechaincompress=threshold=0.0300:ratio=6:attack=15:release=2000:makeup=1[_cv_midd];
[_cv_lo][_cv_midd][_cv_hi]amix=inputs=3:normalize=0:duration=first[bedc]                 ← normalize=0 → unity
```

With `level_match=True` the key is `asplit` and a second, shallow full-band stage follows the recombine:
`sidechaincompress=ratio=2:attack=50:release=2400` — spectral room first, then level, which is the order that
keeps pauses open (1.6 s release still read as the music "coming back" at every sentence break; 2.4 s did not).

| mode | what moves | when |
|---|---|---|
| `dynamic` | static EQ at half the analysed depth + sidechain on the mid band | default |
| `envelope` | mid band × a gain curve computed from word times (`out/duck_<name>.wav`, `amultiply`) | when the duck must lead the voice or be identical on every build |
| `static` | the analysed EQ only (pass `static_depth=1.0` knowingly) | silent films with sparse captions |
| `full` | today's whole-bed sidechain, unchanged | A/B listening, legacy projects |

Envelope numbers: spans = first word → last word + 0.25 s per phase, gaps < 0.6 s merged; depth −10 dB;
attack 0.15 s starting **0.15 s before the first word**; release 1.5 s; unity at t = 0. The curve is baked
into a float WAV because an ffmpeg `volume=if(lt(t,…))` expression overflows the evaluator past ~95 nested
terms (RDP-simplify to ≤ 32 segments, ε 0.005, if you ever must use the expression path).

`threshold='auto'` derives the linear sidechain threshold from the voice itself (20th percentile of the
speaking windows − 6 dB, clamped 0.01..0.1): use it whenever a voice preset changes the stem level.

### The mono-narration upmix gotcha

`gen_vo_multivoice.build_track()` writes MONO. ffmpeg's default mono→stereo rematrix (`aformat=…stereo`,
`-ac 2`) attenuates **3 dB** — measured −41.1 → −44.1 dB RMS. Every v3 film so far entered the mix 3 dB
quieter than its stems, and the two-pass master hid it by lifting voice and bed together. Use
`carve_bed.VO_UPMIX = pan=stereo|FL=FL+FC|FR=FR+FC,aformat=sample_fmts=fltp:sample_rates=48000` (keeps the
level, passes a stereo input through unchanged — verified both). Because the voice comes back 3 dB, the
`bed_db` default moves from −9 to **−12**; projects with a hand-tuned `bed_db` will hear a louder voice
(3.1 behaviour change). The same rule applies to a mono bed or SFX file.

## 2. Voice presets and level match (`audio/voice_presets.py`)

```
python audio/voice_presets.py clean [--evenness 0.5] [--deess] [--job add_clarity]   → ffmpeg -af chain
python audio/voice_presets.py --level-match vo film                                  → per-phase gains
preset_chain(name, evenness=None, deess=False, jobs=(), trim=True) -> str
level_match(paths, target_lufs=-20.0) -> rows · phase_gains(vo_dir, name) · gain_chain(delta_db) -> 'volume=…dB'
```

Order is always *subtractive EQ → dynamics → tone → character → ceiling* ("subtract before you add, level
after you filter, relationships after level, ceiling last").

| preset | chain | use |
|---|---|---|
| `clean` | HP 80 Hz 12 dB/oct → 250 Hz −3 Q1.2 → comp −20 dB 3:1 12/180 ms +3 → 3 kHz +2.5 Q1 → limiter −1 dBFS | the bus default |
| `broadcast` | HP 90 → 400 −3 Q1.4 → comp −24 4:1 8/150 +5 → 2.5 kHz +3 Q0.9 → highshelf 8 kHz +2 → tanh −12 → limiter −1 | thick bed |
| `warm` | HP 70 → lowshelf 180 +2 → comp −18 2.5:1 20/250 +2 → 3 kHz +1.5 Q0.8 → limiter −1.5 | calm, dark films |
| `telephone` | HP 300 ×2 + LP 3400 ×2 (24 dB/oct), 1200 +6 Q1.2, 550 −4 Q1, tanh −9, out −2, trim +4.4 | a caller |
| `pa` | HP 250 ×2, LP 5000 ×2, 2400 +9 Q2, tanh −10, `aecho 40/70 ms` (no IR reverb in ffmpeg), trim +8.2 | a concourse |
| `intercom` | gate −40/range −30, HP 500 ×2, LP 3000 ×2, 2000 +6 Q2, 11-bit crush mix 0.3, trim +1.2 | a dispatcher |
| `radio` | HP 220, LP 2200, 1200 −5 Q0.9, lowshelf 500 +4, tanh −8/−1, 8-bit crush mix 0.45, trim +2.1 | replaces radioize |

Costume trims were measured once on a −20 LUFS synthetic voice so a costumed line lands within 0.1 dB of the
untreated one. The three presets are not trimmed (`clean` lifts a −20 LUFS stem ≈ +5.6 dB; the master absorbs
it). Rules: TTS is already clean — at most `clean`, applied ONCE to the assembled bus after pads/pauses, never
per phrase. Costumes only on lines ≤ 3 s, never on the voice that explains the product, never two at once.

Jobs: tame_boominess 200 −4 Q1.4 · reduce_mud 250 −3 Q1.2 · reduce_boxiness 400 −3 Q1.4 · add_clarity 3 kHz
+2.5 Q1 · soften_harshness 3.2 kHz −3 Q1.6. `preset_chain` raises if a job lands within a third octave of a
band the preset already moves in the same direction (−6 where −3 was meant). Evenness knob 0..1: threshold
−12 − 18·s, ratio 2 + 4·s, attack 25 − 20·s ms, release 300 − 210·s ms, makeup 9.5·s² (level-matched; a
linear 1/3/7 dB makeup left the track −2.5 dB at full). `deess` inserts ffmpeg's real `deesser=i=0.3:m=0.5:f=0.5`.

Level match is the TTS-friendly leveller: ONE `volume` per phase to a −20 LUFS stem target (moves < 0.4 dB
snap to nothing, lift/cut capped at 12 dB). Phrases under 3 s under-read on integrated LUFS, so they are
measured as speaking-window RMS (400 ms windows within 42 dB of the peak) and re-based with the LUFS−RMS
offset of the long phrases. Not a dynamic leveller: a 5–6 dB prosody decline across a sentence is the voice.

## 3. Beat grid (`audio/beat_grid.py`)

```
python audio/beat_grid.py bed.mp3 --out out/beats_film.json --anchor 3.25 --film-len 94.5
analyse(path) -> dict · snap(t, grid, tol=0.25) · bed_in_point(grid, anchor_t, fade_in=1.5, film_len=None)
bed_end(grid, last_word_t, bed_offset=0, min_gap=0.6, fade=3.0) · loop_plan(bed_dur, need_dur, xfade=0.6) · clamp_fades(fi, fo, span)
```

Energy per 1024-sample window hop 512 at 22.05 kHz → onset = local max > 1.5 × mean of ±20 windows, ≥ 0.1 s
apart → BPM₁ = 60 / median IOI (≥ 4 onsets); BPM₂ = autocorrelation of the onset-strength curve (60–200);
folded to 60–120: agree < 5 % → `high`, < 10 % → `low` (average), else `uncertain` (raw onsets, no grid) →
grid phase = the first-10-onset anchor capturing the most onsets within ±25 % of a beat, then a least-squares
refinement of interval + phase (our addition: the hop-quantised median drifted 0.18 s over 30 s at 100 BPM)
→ beats whose ±50 ms RMS < 12 % of the loudest are dropped, strength = RMS/peak → downbeats = the bar phase
with the most kick (< 150 Hz) energy, phrases every 4 bars → 1 s RMS phases VOID < 0.2 / LOW < 0.4 /
MEDIUM < 0.65 / HIGH, key moments |Δ| > 0.12, hard stops < −0.25 in the last 40 %.

**Trust rule.** `rhythmic` is true only with a confident tempo, ≥ 1 onset/s and ≥ half the grid beats
backed by a real onset. Most royalty-free underscores are calm: expect `rhythmic:false`, `snap()` becomes a
no-op, and you pace by phrases and energy. **Never move a word-anchored cut to a beat — words win, the bed
moves.** Use `snap()` only on cues that are not tied to words (opener reveal, closing card, SFX hits).

In-point: `bed_in_point` returns the bed offset that puts the first downbeat after the fade-in on the anchor
(`wt('title','Acme')`), preferring an entrance whose first 5 s are at least as strong as the bed's median
second (do not assume the file's start is the best entrance) and leaving enough bed to cover the film.
Ending: `bed_end` puts the END of the 3 s fade on the first phrase boundary or hard stop ≥ 0.6 s after the
last word — the music finishes on purpose, not at the file edge. `loop_plan` joins N copies of a short bed with
0.6 s `acrossfade` seams instead of `-stream_loop` (which clicks and breaks the grid); `clamp_fades` scales
fade-in + fade-out proportionally when they exceed the bed span. Pick a bed longer than the film when you want bars.

## 4. Gates (`gates/audio_gate.py`, loaded by qa_film.py)

Stems: build_film.py writes `out/stem_vo_<name>.wav` and `out/stem_bed_<name>.wav` from the same graph
(extra `-map` outputs on the first mixdown pass, pre-gain, pre-limiter). The master applies one linear gain,
so every difference below is preserved. Momentary loudness comes from
`ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.M` (one value per 100 ms).

| gate | measure | pass | qa.json |
|---|---|---|---|
| `voice over bed` | median over voiced frames of voice_M − bed_M | ≥ 9 LU (target 12, flagged below) | `voice_over_bed_lu` 12, `voice_over_bed_fail_lu` 9 |
| `duck depth` | bed under speech vs its recovered level in gaps ≥ 0.8 s, in the carved band (else full band) | 3 … 12 dB | `duck_min_db` 3, `duck_max_db` 12 |
| `duck breathes` | every gap ≥ 1.5 s recovers a fraction of the depth | ≥ 0.6 | `duck_recover_frac` 0.6 |
| `voices even` | per-phase vo/<name>_<phase>.mp3 vs the cast median; 1.2 s window spread | ±1.5 LU; ≤ 8 dB | `voices_even_lu`, `voice_spread_db` |
| `true peak` | out/master_<name>.wav; voice stem not clipped | ≤ −1.4 dBTP; ≤ −0.1 | `tp_max_dbtp` |
| `mono upmix` | voice stem L = R and within 0.7 dB of the mono source | catches the 3 dB rematrix loss | `upmix_tol_db` |

A film without a bed skips the first three (PASS, "skipped"); a bed configured without stems FAILS with the hook
to add. These are relationship gates (a pink-ish bed vs a speech stem is not a pure band comparison), never absolute targets.

## 5. Worked example (fictional "Acme Console" film)

```json
{ "name": "film", "bed": "music/acme_underscore.mp3", "bed_db": -12.0,
  "carve": true, "carve_opts": {"strength": 0.5, "threshold": "auto", "level_match": true},
  "voice_preset": "clean", "beats": "out/beats_film.json", "bed_offset": "auto",
  "bed_anchor": ["title", "Acme"], "bed_end": "phrase" }
```

Build log: `carve dynamic strength 0.50  bands 400Hz -5.0dB q1.70, 630Hz -5.0dB q1.70, 1600Hz -10.0dB q1.70,
2500Hz -5.0dB q1.70  split 356/2806 Hz  thr 0.031  + level match` · `bed in-point 2.09 s (first downbeat
after the fade-in with a strong, clean entrance)` · QA: `voice over bed PASS 14.2 LU`, `duck depth PASS band
356-2806 Hz … 9.9 dB`, `mono upmix PASS loss 0.2 dB`.

Selftests (synthetic audio, < 40 s each, no renders): `--selftest` on carve_bed.py, voice_presets.py, beat_grid.py, gates/audio_gate.py.
