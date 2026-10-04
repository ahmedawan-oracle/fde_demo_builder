# Audio: carve the bed, even the cast, cut on bars (v5)

`scripts/film/audio/` holds libraries that return ffmpeg filter **fragments** and JSON facts; `build_film.py`
splices them into its graph; `gates/audio_gate.py` checks the result on the pre-master stems. The narration's
word times drive the duck, the bed's own onsets drive the grid, numpy does the analysis. Synthesized SFX, bus
chains and bed automation are the layer above: `audio-fx-and-sfx.md`.

## 1. Carve, don't duck (`audio/carve_bed.py`)

A full-band duck pulls the WHOLE bed down under speech: the music goes limp and pumps between words. A carve
dips only the bands the voice occupies and lets the low end and the air keep playing. Measured on a pink bed
with a gated voice: a mid-band-only sidechain drops the **mid band 9.7 dB** under the voice while the **whole
bed moves 1.3 dB**; the old full-band duck pulled it a further 4.9 dB everywhere.

```
python audio/carve_bed.py vo_film.mp3 --bed music/bed.mp3 --bed-db -12 --strength 0.5 --json out/carve_film.json
carve_fragment(vo_path, bed_label, sc_label, out_label, mode='dynamic', strength=0.5, split=None,
               ratio=6, threshold=0.03|'auto', attack_ms=15, release_ms=2000, level_match=False,
               static_depth=0.5, gain_label=None, json_out=None, bed_path=None, bed_gain_db=0.0) -> str
```

The analysis asks one question per band: **how much would a cut here help the words?** Decode the assembled
VO to mono 48 kHz → long-term spectrum of the SPEAKING frames only (4096/2048 Hann; frames 30 dB under the
loudest are pauses) → fifteen third-octave band levels 200 … 5000 Hz. Do the same for the bed at its mix gain
(`bed_path`, `bed_gain_db` — `build_film.py` passes them); with no bed, assume pink noise 12 dB under the voice
(the gate target). Then

```
snr_b     = voice_b − bed_b
audible   = clamp((snr + 15) / 30, 0, 1)      a band is unheard at −15 dB voice-to-bed, fully heard at +15
benefit_b = audible(snr_b + maxCut) − audible(snr_b)
weight_b  = 1 − bias · (1 − presence_b)       presence = 1 across 300–3400 Hz, −12 dB/oct outside
score_b   = weight_b · benefit_b              K best are cut; depth = maxCut × clamp(score/top, 0.5, 1)
```

A band the voice already wins by 15 dB is never cut (it would only thin the bed); a bass-heavy pad moves the
carve down to 250–400 Hz, a bright bed up to 2–3 kHz (measured: vs the pink reference → 1000/1250/2500/3150 Hz;
vs a C–E–G chord bed at −12 dB → 200/250/315/400 Hz). All fifteen rows are in `out/carve_<name>.json → ranking`.

| strength | max cut | bands | Q | bias | duck | headroom | reads as |
|---|---|---|---|---|---|---|---|
| 0.25 | 6 dB | 2 | 1.5 | 0.63 | 7 dB | 10.5 dB | "music got out of the way" |
| **0.5 (default, TTS)** | 9 dB | 4 | 2.0 | 0.75 | 10 dB | 12 dB | clean, still music |
| 0.8 | 12.6 dB | 5 | 2.6 | 0.9 | 13.6 dB | 13.8 dB | starts to read as an effect |
| 1.0 | 15 dB | 6 | 3.0 | 1.0 | 16 dB | 15 dB | the ceiling before a peaking cut rings |

Formulas (v5): maxCut 3 + 12·s · bands 1 + round(5·s) in 1..6 · Q 1 + 2·s · bias 0.5 + 0.5·s · duck 4 + 12·s ·
headroom 9 + 6·s (9 LU is the gate's floor, 12 its target). 3 dB is the smallest band change a listener notices,
so every chosen band gets at least half the full cut. TTS voices are already compressed — 0.5 is plenty. The v4
profile was 0.5 → 10 dB / 4 bands / Q 1.7 and 0.8 → 14.8 dB / 6 bands: hand-tuned films carve slightly shallower.

Fragment, mode `dynamic` (default), given `[bed]` (stereo fltp 48 kHz, level + fades applied) and `[vsc]` (a
copy of the upmixed voice): static `equalizer` cuts at HALF the analysed depth → `acrossover` (4th-order
Linkwitz-Riley, sums flat) at the carve band's edges → `sidechaincompress` (thr 0.03, ratio 6, 15/2000 ms) on
the mid band only → `amix normalize=0` back to unity. With `level_match=True` the key is `asplit` and a second, shallow full-band stage follows the recombine:
`sidechaincompress=ratio=2:attack=50:release=2400` — spectral room first, then level, which is the order that
keeps pauses open (1.6 s release still read as the music "coming back" at every sentence break; 2.4 s did not).

| mode | what moves | when |
|---|---|---|
| `dynamic` | static EQ at half the analysed depth + sidechain on the mid band | default |
| `envelope` | mid band × a gain curve computed from word times (`out/duck_<name>.wav`, `amultiply`) | when the duck must lead the voice or be identical on every build |
| `static` | the analysed EQ only (pass `static_depth=1.0` knowingly) | silent films with sparse captions |
| `full` | the whole-bed sidechain, unchanged | A/B listening, legacy projects |

Envelope numbers: spans = first word → last word + 0.25 s per phase, gaps < 0.6 s merged; depth −10 dB; attack
0.15 s starting **0.15 s before the first word**; release 1.5 s; baked into a float WAV (an ffmpeg `volume=if(…)`
expression overflows past ~95 terms). `threshold='auto'` = the voice's 20th-percentile speaking level − 6 dB,
clamped 0.01..0.1: use it whenever a voice preset changes the stem level.

**The mono-narration upmix gotcha.** `gen_vo_multivoice.build_track()` writes MONO, and ffmpeg's default
mono→stereo rematrix attenuates **3 dB** (measured −41.1 → −44.1 dB RMS). Use `carve_bed.VO_UPMIX =
pan=stereo|FL=FL+FC|FR=FR+FC,aformat=sample_fmts=fltp:sample_rates=48000` (keeps the level, passes stereo
through unchanged). Because the voice comes back 3 dB, the `bed_db` default is **−12**; the same rule applies
to a mono bed or SFX file.

## 2. Voice presets and level match (`audio/voice_presets.py`)

```
python audio/voice_presets.py clean [--evenness 0.5] [--deess] [--job add_clarity]   → ffmpeg -af chain
python audio/voice_presets.py --level-match vo film                                  → per-phase gains
preset_chain(name, evenness=None, deess=False, jobs=(), trim=True) -> str
level_match(paths, target_lufs=-20.0) -> rows · phase_gains(vo_dir, name) · gain_chain(delta_db) -> 'volume=…dB'
```

Order is always *subtractive EQ → dynamics → tone → character → ceiling*.

| preset | chain | use |
|---|---|---|
| `clean` | HP 80 Hz 12 dB/oct → 250 Hz −3 Q1.2 → comp −20 dB 3:1 12/180 ms +3 → 3 kHz +2.5 Q1 → limiter −1 dBFS | the bus default |
| `broadcast` | HP 90 → 400 −3 Q1.4 → comp −24 4:1 8/150 +5 → 2.5 kHz +3 Q0.9 → highshelf 8 kHz +2 → tanh −12 → limiter −1 | thick bed |
| `warm` | HP 70 → lowshelf 180 +2 → comp −18 2.5:1 20/250 +2 → 3 kHz +1.5 Q0.8 → limiter −1.5 | calm, dark films |
| `telephone` | HP 300 ×2 + LP 3400 ×2 (24 dB/oct), 1200 +6 Q1.2, 550 −4 Q1, tanh −9, out −2, trim +4.4 | a caller |
| `pa` | HP 250 ×2, LP 5000 ×2, 2400 +9 Q2, tanh −10, `aecho 40/70 ms`, trim +8.2 | a concourse |
| `intercom` | gate −40/range −30, HP 500 ×2, LP 3000 ×2, 2000 +6 Q2, 11-bit crush mix 0.3, trim +1.2 | a dispatcher |
| `radio` | HP 220, LP 2200, 1200 −5 Q0.9, lowshelf 500 +4, tanh −8/−1, 8-bit crush mix 0.45, trim +2.1 | field / ops lines |

Costume trims were measured once on a −20 LUFS synthetic voice so a costumed line lands within 0.1 dB of the
untreated one; the three presets are not trimmed (`clean` lifts a −20 LUFS stem ≈ +5.6 dB; the master absorbs
it). Rules: TTS is already clean — at most `clean`, applied ONCE to the assembled bus, never per phrase.
Costumes only on lines ≤ 3 s, never on the voice that explains the product, never two at once.

Jobs: tame_boominess 200 −4 Q1.4 · reduce_mud 250 −3 Q1.2 · reduce_boxiness 400 −3 Q1.4 · add_clarity 3 kHz
+2.5 Q1 · soften_harshness 3.2 kHz −3 Q1.6; `preset_chain` raises if a job lands within a third octave of a
band the preset already moves the same way. Evenness 0..1: threshold −12 − 18·s, ratio 2 + 4·s, attack
25 − 20·s ms, release 300 − 210·s ms, makeup 9.5·s² (level-matched). `deess` inserts ffmpeg's `deesser`.

Level match is the TTS-friendly leveller: ONE `volume` per phase to a −20 LUFS stem target (moves < 0.4 dB
snap to nothing, lift/cut capped at 12 dB). Phrases under 3 s are measured as speaking-window RMS (400 ms
windows within 42 dB of the peak) and re-based with the LUFS−RMS offset of the long phrases. Not a dynamic
leveller: a 5–6 dB prosody decline across a sentence is the voice.

## 3. Beat grid (`audio/beat_grid.py`)

```
python audio/beat_grid.py bed.mp3 --out out/beats_film.json --anchor 3.25 --film-len 94.5
analyse(path) -> dict · snap(t, grid, tol=0.25) · bed_in_point(grid, anchor_t, fade_in=1.5, film_len=None)
bed_end(grid, last_word_t, bed_offset=0, min_gap=0.6, fade=3.0) · loop_plan(bed_dur, need_dur, xfade=0.6) · clamp_fades(fi, fo, span)
```

**Onsets.** 1024-sample Hann frames, hop 256 (11.6 ms) at 22.05 kHz → log-compressed magnitudes
log(1 + 20·|X|) → half-wave-rectified spectral flux (only energy ARRIVING counts). Threshold = 1.5 × running
median over ±0.35 s + 3 % of the peak, never under 15 nats (a sustained pad yields zero onsets). Local maxima
above it are onsets at the frame centre; onsets closer than 80 ms keep the stronger. Strength = flux / peak.

**Tempo.** Every onset pair ≤ 2 s apart votes its interval into a 10 ms histogram (weight = product of
strengths); each interval d folds onto d, d/2, d/3, d/4 (weight 1/m) and 2d (weight ½) inside 60–180 BPM; the
parabola-refined peak is BPM₁. BPM₂ is the autocorrelation of the flux (60–200). Folded to 60–120: agree < 5 %
→ `high` and the tempo is BPM₁'s precision in BPM₂'s octave (hats on eighths do not double the grid); < 10 %
→ `low` (average); else `uncertain` (raw onsets, no grid).

**Grid.** Scan 64 phases across one period for the largest strength-weighted Gaussian (σ = 0.1 period) onset
mass, then three rounds of weighted least squares on the inliers (|residual| < 0.2 period); the period may move
≤ 6 %. `grid_fit` reports period, phase, inliers and the weighted residual (synthetic drums: 7 ms downbeat
error, 19 ms residual; 72 BPM drums with eighth-note hats → 72.0 BPM where the histogram alone said 144.5).

**Silence gate.** Beats whose ±50 ms RMS is under −45 dBFS are dropped; survivors carry strength = RMS /
loudest beat. Downbeats = the bar phase with the most kick (< 150 Hz) energy, phrases every 4 bars; 1 s RMS
phases VOID < 0.2 / LOW < 0.4 / MEDIUM < 0.65 / HIGH, key moments |Δ| > 0.12, hard stops < −0.25 in the last 40 %.

**Trust rule.** `rhythmic` is true only with a confident tempo, ≥ 1 onset/s and ≥ half the grid beats backed
by a real onset; most underscores are calm, `snap()` becomes a no-op and you pace by phrases and energy.
**Never move a word-anchored cut to a beat — words win, the bed moves.** `snap()` is for cues not tied to words.

In-point: `bed_in_point` puts the first downbeat after the fade-in on the anchor (`wt('title','Acme')`), preferring
an entrance whose first 5 s are at least as strong as the bed's median second. Ending: `bed_end` puts the END of
the 3 s fade on the first phrase boundary or hard stop ≥ 0.6 s after the last word. `loop_plan` joins copies of a
short bed with 0.6 s `acrossfade` seams (never `-stream_loop`); `clamp_fades` scales fades to the bed span.

## 4. Gates (`gates/audio_gate.py`, loaded by qa_film.py)

Stems: `build_film.py` writes `out/stem_vo_<name>.wav` and `out/stem_bed_<name>.wav` from the same graph
(pre-gain, pre-limiter); the master applies one linear gain, so every difference below is preserved.
Momentary loudness comes from `ebur128` metadata (one value per 100 ms).

| gate | measure | pass | qa.json |
|---|---|---|---|
| `voice over bed` | median over voiced frames of voice_M − bed_M | ≥ 9 LU (target 12, flagged below) | `voice_over_bed_lu` 12, `voice_over_bed_fail_lu` 9 |
| `duck depth` | bed under speech vs its recovered level in gaps ≥ 0.8 s, in the carved band (else full band) | 3 … 12 dB | `duck_min_db` 3, `duck_max_db` 12 |
| `duck breathes` | every gap ≥ 1.5 s recovers a fraction of the depth | ≥ 0.6 | `duck_recover_frac` 0.6 |
| `voices even` | per-phase vo/<name>_<phase>.mp3 vs the cast median; 1.2 s window spread | ±1.5 LU; ≤ 8 dB | `voices_even_lu`, `voice_spread_db` |
| `true peak` | out/master_<name>.wav; voice stem not clipped | ≤ −1.4 dBTP; ≤ −0.1 | `tp_max_dbtp` |
| `mono upmix` | voice stem L = R and within 0.7 dB of the mono source | catches the 3 dB rematrix loss | `upmix_tol_db` |

A film without a bed skips the first three; a bed without stems FAILS. Relationship gates, never absolute targets.

## 5. Worked example (fictional "Acme Console" film)

`film.json`: `"bed": "music/acme_underscore.mp3", "bed_db": -12.0, "carve": true, "carve_opts": {"strength": 0.5,
"threshold": "auto", "level_match": true}, "voice_preset": "clean", "beats": "out/beats_film.json", "bed_offset":
"auto", "bed_anchor": ["title", "Acme"], "bed_end": "phrase"`.

Build log: `carve dynamic strength 0.50  bands 1000Hz -9.0dB q2.00, 1250Hz -7.8dB q2.00, 2500Hz -9.0dB q2.00,
3150Hz -9.0dB q2.00  split 891/3536 Hz  thr 0.031  + level match  vs acme_underscore.mp3` · `bed in-point 2.09 s
(first downbeat after the fade-in with a strong, clean entrance)` · QA: `voice over bed PASS 14.2 LU`,
`duck depth PASS band 891-3536 Hz … 9.1 dB`, `mono upmix PASS loss 0.2 dB`.

Selftests (synthetic audio, no renders): `--selftest` on carve_bed.py, voice_presets.py, beat_grid.py, gates/audio_gate.py.
