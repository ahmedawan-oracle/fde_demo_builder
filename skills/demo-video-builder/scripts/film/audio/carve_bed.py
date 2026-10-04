# -*- coding: utf-8 -*-
"""carve_bed.py — carve the music bed around the narration instead of ducking the whole thing.

    python audio/carve_bed.py vo_film.mp3                       # prints an ffmpeg filter_complex FRAGMENT
    python audio/carve_bed.py vo_film.mp3 --bed music/bed.mp3 --bed-db -12 --strength 0.5 --json out/carve_film.json
    python audio/carve_bed.py vo_film.mp3 --mode envelope --phases vo/film_phases.json --words vo/film_words.json \
                                          --envelope-wav out/duck_film.wav --total 93.3
    python audio/carve_bed.py --selftest

What it does
  1. Decodes the assembled narration (vo_<name>.mp3, every voice already summed on the film clock) to mono
     48 kHz float and measures its long-term spectrum over the SPEAKING frames only (frames within 30 dB of
     the loudest; FRAME 4096, HOP 2048, Hann). Pauses carry room tone, not speech, so they are left out.
  2. Integrates that spectrum into fifteen third-octave bands, 200 … 5000 Hz, and does the same for the bed
     when one is given (`bed_path`, at its mix gain `bed_gain_db`). Without a bed it assumes a pink reference
     sitting 12 dB under the voice — the voice-over-bed target the audio gate checks for.
  3. Ranks the bands by HOW MUCH A CUT WOULD HELP THE WORDS, not by how loud the voice is in them:
        snr_b      = voice_b − bed_b                            (per band, at mix levels)
        audible(r) = clamp((r + 15) / 30, 0, 1)                 (a band contributes nothing below −15 dB
                                                                 voice-to-bed and is fully heard above +15)
        benefit_b  = audible(snr_b + cut) − audible(snr_b)      (what `cut` dB of carve buys in that band)
        weight_b   = 1 − bias · (1 − presence_b)                (presence: 1 inside 300–3400 Hz, −12 dB per
                                                                 octave outside; bias from the profile)
        score_b    = weight_b · benefit_b
     The K highest scores are cut. Depth per band = maxCut × clamp(score / top, 0.5, 1): every chosen band
     gets at least half the full cut (3 dB is about the smallest band change a listener notices).
     A band where the voice already wins by 15 dB is never cut — carving it would only thin the bed.
  4. Maps ONE knob (strength 0..1) to the mechanism numbers (see `profile`).
  5. Emits an ffmpeg filter_complex fragment (a string, no shelling out) that build_film.py splices into its
     graph. Modes:
        dynamic   (default) static EQ at half the analysed depth + acrossover into low/mid/high and a
                  sidechain compressor on the MID band only (ratio 6, attack 15 ms, release 2000 ms), bands
                  recombined with amix normalize=0 (Linkwitz-Riley 4th order sums flat; verified unity).
        static    the analysed peaking cuts only — no dynamics (thins the bed through every pause; use
                  --static-depth 1.0 knowingly).
        envelope  the mid band is multiplied by a deterministic word-timestamp gain curve (out/duck_<name>.wav)
                  built from vo/<name>_phases.json + _words.json: spans merge gaps < 0.6 s, duck −10 dB,
                  attack 0.15 s starting 0.15 s BEFORE the first word, release 1.5 s. No compressor, so a
                  breath or a plosive cannot change the duck, and the duck leads the voice.
        full      the whole-bed sidechain (threshold 0.04, ratio 4, attack 20, release 500) for A/B.
     --level-match adds a second stage: a shallow full-band sidechain (ratio 2, release 2.4 s — 1.6 s still
     read as the music 'coming back' at every sentence break) AFTER the spectral stage.

Measured here (ffmpeg 8.1.1, pink bed, gated 220 Hz voice): a 250–2500 Hz-only sidechain (thr 0.03, ratio 6)
dropped the mid band 9.7 dB under the voice while the whole bed moved 1.3 dB; the full-band duck on a −9 dB
bed pulled it a further 4.9 dB everywhere.

Mono-narration gotcha: gen_vo_multivoice.build_track() writes MONO. ffmpeg's default mono→stereo rematrix
(aformat / -ac 2) loses 3 dB (measured −41.1 → −44.1 dB RMS). Upmix with VO_UPMIX below (pan keeps the level
and passes a stereo input through unchanged). The fragment assumes the caller already did this.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import subprocess
import sys
from typing import Iterable, Sequence

import numpy as np

# ----------------------------------------------------------------------------------------------- constants
#: Third-octave cut candidates (standard preferred centres). Below 200 Hz the voice carries only its fundamental,
#: which nobody needs to understand a word, and the bed carries its weight; above 5 kHz the bed is 'air'.
THIRD_OCTAVES_HZ = (200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000)
SPEECH_PLATEAU_HZ = (300.0, 3400.0)     # speech-presence weighting is flat here (the band a phone line keeps)
PRESENCE_SLOPE_DB_PER_OCT = 12.0        # and falls this fast outside it
AUDIBILITY_WINDOW_DB = (-15.0, 15.0)    # voice-to-bed ratio window inside which a band's clarity changes
REF_VOICE_OVER_BED_DB = 12.0            # no bed given: pink reference this far under the voice (the gate target)
FRAME, HOP = 4096, 2048                 # analysis frame / hop at 48 kHz (85 ms / 43 ms)
SPEAKING_RANGE_DB = 30.0                # a frame 30 dB under the loudest frame is a pause, not speech
SR = 48000

#: Mono → stereo WITHOUT the 3 dB rematrix loss; a stereo input passes through unchanged.
VO_UPMIX = 'pan=stereo|FL=FL+FC|FR=FR+FC,aformat=sample_fmts=fltp:sample_rates=48000'
#: Stereo conform for a bed / sfx / gain-curve input (already stereo → no change).
STEREO_FMT = 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'

#: The whole-bed duck, kept verbatim as mode 'full' for A/B listening.
FULL_DUCK = 'sidechaincompress=threshold=0.04:ratio=4:attack=20:release=500'
# Both legs of every sidechaincompress are re-framed to the same sample count first. Without it ffmpeg 8.1.1 spins forever
# (100 % CPU, never exits) when the key arrives in frames of a different size than the band it ducks — the acrossover leg
# and the asplit voice key do exactly that. Replayed 12x under load: shipped graph 5 hangs, voice fed twice 2, with
# -filter_complex_threads 1 6, with this alignment on both legs 0 (median 0.1 s). Pure re-framing: the samples are unchanged.
SC_ALIGN = 'asetnsamples=n=1024:p=0'

# Deterministic word-timestamp envelope defaults (envelope mode).
ENV_MERGE_GAP_S = 0.6        # speech spans closer than this merge, so the bed does not pump between words
ENV_TAIL_S = 0.25            # span runs this far past the last word's onset (edge-tts adds ~0.5 s of silence)
ENV_LEAD_S = 0.15            # the duck starts this far BEFORE the first word (anticipation a compressor cannot do)
ENV_ATTACK_S = 0.15
ENV_RELEASE_S = 1.5          # long enough that the music does not 'come back' at every sentence break
ENV_DEPTH_DB = -10.0


# ----------------------------------------------------------------------------------------------- ffmpeg guard
def _ffmpeg(args: Sequence[str], tries: int = 3, timeout: float = 120, check: bool = False, text: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg with a bounded wait and a retry. ffmpeg 8.1.1 occasionally spins forever (100 % CPU, never exits) on a
    filter graph that pairs asplit -> sidechaincompress with acrossover + amix — measured 3 hangs in 15 launches of the
    carve selftest graph, independent of -threads / -filter_complex_threads. A hung child is killed (subprocess does that
    on TimeoutExpired) so it cannot linger as an orphan, and the next try normally finishes in a couple of seconds."""
    last: Exception | None = None
    for _ in range(max(1, tries)):
        try:
            r = subprocess.run(list(args), capture_output=True, text=text, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            last = e
            continue
        if check and r.returncode != 0:
            err = r.stderr if isinstance(r.stderr, str) else (r.stderr or b'').decode('utf-8', 'replace')
            raise subprocess.CalledProcessError(r.returncode, list(args), r.stdout, err)
        return r
    raise RuntimeError('ffmpeg did not finish in %d s after %d tries: %s' % (timeout, tries, ' '.join(map(str, args))[:200])) from last


# ----------------------------------------------------------------------------------------------- decode
def decode(path: str, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` through ffmpeg (-f f32le). Returns a 1-D array."""
    r = _ffmpeg(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr),
                 '-f', 'f32le', '-'], text=False)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError('decode failed for %s: %s' % (path, r.stderr.decode('utf-8', 'replace')[-400:]))
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


# ----------------------------------------------------------------------------------------------- the knob
def profile(strength: float) -> dict:
    """One knob → the mechanism numbers. Each line is anchored on something a listener can hear:

      max_cut_db  3 + 12·s   3 dB is the smallest band change people notice; past ~15 dB a peaking cut rings
      bands       1 + round(5·s), 1..6   one dip at 0, a six-band presence carve at 1
      q           1 + 2·s    Q 1 is a one-octave bowl; Q 3 keeps a deep cut inside its own third-octave
      bias        0.5 + 0.5·s   how much the speech-presence weighting steers the ranking (never under half)
      duck_db     4 + 12·s   the dynamic stage's intended dip in the mid band while the voice speaks
      headroom_db 9 + 6·s    the voice-over-bed target the carve is designed around (9 LU is the gate's floor,
                             12 LU its target at the default strength)

    0.25 → 6 dB in 2 bands; 0.5 (default — TTS voices are already compressed) → 9 dB in 4 bands, Q 2;
    0.8 → 12.6 dB in 5 bands; 1.0 → 15 dB in 6 bands, Q 3."""
    s = min(1.0, max(0.0, float(strength))) if math.isfinite(strength) else 0.5
    return {
        'strength': round(s, 3),
        'max_cut_db': round(3 + 12 * s, 2),
        'bands': max(1, min(6, 1 + int(math.floor(5 * s + 0.5)))),
        'q': round(1 + 2 * s, 2),
        'bias': round(0.5 + 0.5 * s, 2),
        'duck_db': round(4 + 12 * s, 2),
        'headroom_db': round(9 + 6 * s, 2),
    }


# ----------------------------------------------------------------------------------------------- spectrum
def _hann(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)


def long_term_spectrum(mono: np.ndarray, sr: int = SR, frame: int = FRAME, hop: int = HOP,
                       speaking_only: bool = True, range_db: float = SPEAKING_RANGE_DB) -> tuple[np.ndarray, np.ndarray]:
    """Average power spectrum (Hann, every hop) of the frames that actually carry signal.

    With `speaking_only` the frames whose RMS sits more than `range_db` under the loudest frame are skipped, so the
    narration's spectrum is the spectrum of speech, not of speech diluted by room tone. Returns (freqs_hz, power);
    power is the mean per-frame bin power, length frame/2+1."""
    x = np.asarray(mono, dtype=np.float32)
    if x.size < frame:
        x = np.pad(x, (0, frame - x.size))
    n_frames = 1 + (x.size - frame) // hop
    view = np.lib.stride_tricks.sliding_window_view(x, frame)[::hop][:n_frames]
    keep = np.ones(n_frames, dtype=bool)
    if speaking_only and n_frames > 1:
        rms_db = 10 * np.log10(np.maximum((view.astype(np.float64) ** 2).mean(axis=1), 1e-20))
        keep = rms_db >= rms_db.max() - range_db
        if not keep.any():
            keep[:] = True
    win = _hann(frame)
    acc = np.zeros(frame // 2 + 1, dtype=np.float64)
    idx = np.flatnonzero(keep)
    for k in range(0, idx.size, 512):                               # chunked so a 5-minute VO stays small in memory
        spec = np.fft.rfft(view[idx[k:k + 512]] * win, axis=1)
        acc += (spec.real ** 2 + spec.imag ** 2).sum(axis=0)
    acc /= max(1, idx.size)
    return np.arange(frame // 2 + 1) * (sr / frame), acc


def band_edges(center_hz: float) -> tuple[float, float]:
    """Lower / upper edge of the third-octave band around `center_hz` (÷ and × 2^(1/6))."""
    return center_hz / 2 ** (1 / 6), center_hz * 2 ** (1 / 6)


def third_octave_levels(freqs: np.ndarray, power: np.ndarray, centres: Sequence[float] = THIRD_OCTAVES_HZ) -> np.ndarray:
    """Integrated band energy in dB for each centre (sum of the bin powers inside the band). A band with no
    energy reads −200 dB so it ranks last instead of raising a warning."""
    out = np.empty(len(centres))
    for i, c in enumerate(centres):
        lo, hi = band_edges(c)
        m = (freqs >= lo) & (freqs < hi)
        e = float(power[m].sum()) if m.any() else 0.0
        out[i] = 10 * math.log10(e) if e > 0 else -200.0
    return out


# ----------------------------------------------------------------------------------------------- ranking
def presence_weight(center_hz: float, plateau: Sequence[float] = SPEECH_PLATEAU_HZ,
                    slope_db_per_oct: float = PRESENCE_SLOPE_DB_PER_OCT) -> float:
    """Speech-presence weight 0..1: 1 across the plateau, falling `slope_db_per_oct` per octave outside it.
    200 Hz (0.58 oct under 300) → 0.20; 5000 Hz (0.56 oct over 3400) → 0.21."""
    lo, hi = plateau
    octs = math.log2(lo / center_hz) if center_hz < lo else (math.log2(center_hz / hi) if center_hz > hi else 0.0)
    return 10 ** (-slope_db_per_oct * octs / 10)


def audibility(snr_db: float, window: Sequence[float] = AUDIBILITY_WINDOW_DB) -> float:
    """Share of a band's speech that reaches the listener for a given voice-to-bed ratio: 0 at or under the
    window's floor, 1 at or above its ceiling, linear in dB between."""
    lo, hi = window
    return min(1.0, max(0.0, (snr_db - lo) / (hi - lo)))


def carve_benefit(snr_db: float, cut_db: float) -> float:
    """How much audibility a `cut_db` carve of the bed adds in a band whose ratio is `snr_db` today."""
    return audibility(snr_db + cut_db) - audibility(snr_db)


def rank_bands(voice_db: np.ndarray, bed_db: np.ndarray, prof: dict, centres: Sequence[float] = THIRD_OCTAVES_HZ) -> list[dict]:
    """Score every candidate band (see module docstring) and return the table sorted by score, best first:
    [{'f', 'voice_db', 'bed_db', 'snr_db', 'presence', 'weight', 'benefit', 'score'}]."""
    rows = []
    for i, c in enumerate(centres):
        snr = float(voice_db[i] - bed_db[i])
        pres = presence_weight(c)
        w = 1 - prof['bias'] * (1 - pres)
        ben = carve_benefit(snr, prof['max_cut_db'])
        rows.append({'f': int(c), 'voice_db': round(float(voice_db[i]), 2), 'bed_db': round(float(bed_db[i]), 2),
                     'snr_db': round(snr, 2), 'presence': round(pres, 3), 'weight': round(w, 3),
                     'benefit': round(ben, 4), 'score': round(w * ben, 4)})
    # ties (e.g. every band saturated) fall back to presence, then to the lower frequency for stability
    rows.sort(key=lambda r: (-r['score'], -r['presence'], r['f']))
    return rows


def pink_reference(voice_db: np.ndarray, under_db: float = REF_VOICE_OVER_BED_DB) -> np.ndarray:
    """Stand-in bed when none is given: equal energy per third-octave (pink), its total across the candidate
    bands `under_db` below the voice's total across the same bands."""
    total = 10 * math.log10(float((10 ** (voice_db / 10)).sum()))
    return np.full(voice_db.shape, total - under_db - 10 * math.log10(voice_db.size))


def analyse_bands(mono: np.ndarray, sr: int = SR, prof: dict | None = None, bed: np.ndarray | None = None,
                  bed_gain_db: float = 0.0, table: list | None = None) -> list[dict]:
    """Choose the cuts for this voice (and this bed, if given), ascending in frequency:
    [{'f': Hz, 'gain_db': −depth, 'q': Q, 'score': 0..1, 'snr_db': voice-to-bed in that band}].
    Pass a list as `table` to receive the full ranking of every candidate (for the handoff JSON)."""
    prof = prof or profile(0.5)
    if mono.size == 0:
        return []
    vf, vp = long_term_spectrum(mono, sr)
    voice_db = third_octave_levels(vf, vp)
    if bed is not None and bed.size:
        bf, bp = long_term_spectrum(bed, sr, speaking_only=False)
        bed_db = third_octave_levels(bf, bp) + float(bed_gain_db)
    else:
        bed_db = pink_reference(voice_db)
    ranked = rank_bands(voice_db, bed_db, prof)
    if table is not None:
        table.extend(ranked)
    chosen = ranked[:max(1, prof['bands'])]
    top = chosen[0]['score']
    out = []
    for r in chosen:
        share = (r['score'] / top) if top > 0 else 0.0          # top == 0: the voice already wins everywhere
        depth = prof['max_cut_db'] * min(1.0, max(0.5, share))
        out.append({'f': r['f'], 'gain_db': -round(depth, 2), 'q': prof['q'], 'score': r['score'], 'snr_db': r['snr_db']})
    return sorted(out, key=lambda b: b['f'])


def split_from_bands(bands: Sequence[dict], lo_floor: float = 250.0, hi_cap: float = 6000.0) -> list[float]:
    """Crossover points enclosing the selected bands by a third octave. The low split never goes under 250 Hz:
    the fundamental is the loudest part of a voice but cutting the bed there only thins it."""
    if not bands:
        return [250.0, 2500.0]
    lo = max(lo_floor, min(b['f'] for b in bands) / 2 ** (1 / 6))
    hi = min(hi_cap, max(b['f'] for b in bands) * 2 ** (1 / 6))
    hi = max(hi, lo * 2)
    return [round(lo), round(hi)]


def speaking_threshold(mono: np.ndarray, sr: int = SR, below_db: float = 6.0) -> float:
    """Linear sidechaincompress threshold derived from the voice itself: the 20th percentile of the speaking
    windows' RMS (windows within 30 dB of the peak) minus `below_db`, clamped to 0.01..0.1 (−40..−20 dBFS)."""
    if mono.size < FRAME:
        return 0.03
    n = (mono.size // FRAME) * FRAME
    rms = np.sqrt((mono[:n].reshape(-1, FRAME).astype(np.float64) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    speaking = db[db > db.max() - SPEAKING_RANGE_DB]
    if speaking.size == 0:
        return 0.03
    thr = 10 ** ((np.percentile(speaking, 20) - below_db) / 20)
    return float(min(0.1, max(0.01, thr)))


def report_line(bands: Sequence[dict]) -> str:
    """One printable line for the handoff doc: 'bands 250Hz -7.4dB q2.06, 400Hz ...'."""
    return 'bands ' + ', '.join('%dHz %+.1fdB q%.2f' % (b['f'], b['gain_db'], b['q']) for b in bands) if bands else 'bands none'


# ----------------------------------------------------------------------------------------------- envelope (mode envelope)
def speech_spans(phases: dict, words: dict, merge_gap: float = ENV_MERGE_GAP_S, tail: float = ENV_TAIL_S) -> list[list[float]]:
    """Speech spans on the film clock from vo/<name>_phases.json + _words.json: per phase first word → last word
    + tail; spans closer than `merge_gap` are merged. Phases without word data fall back to start..start+dur."""
    spans = []
    for p in phases['phases']:
        ws = words.get(p['name']) or []
        if ws:
            s, e = p['start'] + min(w['t'] for w in ws), p['start'] + max(w['t'] for w in ws) + tail
        else:
            s, e = p['start'], p['start'] + p['dur']
        spans.append([round(s, 3), round(min(e, p['start'] + p['dur']), 3)])
    spans.sort()
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] < merge_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def envelope_curve(spans: Iterable[Sequence[float]], total: float, sr: int = SR, depth_db: float = ENV_DEPTH_DB,
                   lead: float = ENV_LEAD_S, attack: float = ENV_ATTACK_S, release: float = ENV_RELEASE_S) -> np.ndarray:
    """Linear gain curve (float32, length total×sr): unity outside speech, 10^(depth/20) inside, ramping down
    over `attack` seconds starting `lead` before each span and back up over `release` after it. Overlaps take
    the deeper value; the first sample holds unity unless speech starts inside the lead."""
    n = int(round(total * sr))
    ctrl_sr = 1000
    m = int(math.ceil(total * ctrl_sr)) + 1
    gain_db = np.zeros(m, dtype=np.float64)
    t = np.arange(m) / ctrl_sr
    for s, e in spans:
        a0, a1 = s - lead, s - lead + attack
        r0, r1 = e, e + release
        seg = np.zeros(m)
        seg[(t >= a1) & (t <= r0)] = depth_db
        ramp = (t >= a0) & (t < a1)
        seg[ramp] = depth_db * (t[ramp] - a0) / max(attack, 1e-6)
        rel = (t > r0) & (t < r1)
        seg[rel] = depth_db * (1 - (t[rel] - r0) / max(release, 1e-6))
        gain_db = np.minimum(gain_db, seg)
    gain = 10 ** (gain_db / 20)
    return np.interp(np.arange(n) / sr, t, gain).astype(np.float32)


def write_gain_wav(path: str, gain: np.ndarray, sr: int = SR) -> str:
    """Write a mono IEEE-float WAV (format tag 3) — ffmpeg reads it as pcm_f32le. Derived artefact: keep out of git."""
    data = np.asarray(gain, dtype='<f4').tobytes()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE')
        fh.write(b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 1, sr, sr * 4, 4, 32))
        fh.write(b'data' + struct.pack('<I', len(data)) + data)
    return path


# ----------------------------------------------------------------------------------------------- fragment
def static_eq_chain(bands: Sequence[dict], depth_factor: float = 0.5) -> str:
    """Peaking cuts as ffmpeg `equalizer` nodes, scaled by `depth_factor` (≤ 0.5 recommended: a static cut thins
    the bed through every pause, the dynamic stage supplies the rest)."""
    return ','.join('equalizer=f=%d:width_type=q:w=%.2f:g=%.2f' % (b['f'], b['q'], b['gain_db'] * depth_factor) for b in bands)


def carve_fragment(vo_path: str, bed_label: str, sc_label: str | None, out_label: str, *, mode: str = 'dynamic',
                   strength: float = 0.5, split: Sequence[float] | None = None, ratio: float = 6.0,
                   threshold: float | str = 0.03, attack_ms: float = 15, release_ms: float = 2000,
                   level_match: bool = False, static_depth: float = 0.5, gain_label: str | None = None,
                   json_out: str | None = None, analysis: dict | None = None, verbose: bool = True,
                   bed_path: str | None = None, bed_gain_db: float = 0.0) -> str:
    """Return an ffmpeg filter_complex FRAGMENT that reads the bed from `[bed_label]` (stereo fltp 48 kHz, level,
    fades and trims already applied) and, for the dynamic modes, the voice key from `[sc_label]`, and writes the
    carved bed to `[out_label]`. The fragment is self-contained: it asplit()s the key when it needs two copies
    and sinks it when a mode does not use it, so the caller's graph never dangles.

    mode      'dynamic' | 'static' | 'envelope' | 'full'  (see module docstring)
    strength  0..1 → profile(); default 0.5 because TTS voices are already compressed
    split     [lo, hi] Hz crossover; default derived from the analysed bands (low never under 250 Hz)
    threshold linear sidechain threshold (0.03 ≈ −30 dBFS) or 'auto' = speaking_threshold(voice)
    level_match  append the shallow full-band stage (ratio 2, attack 50 ms, release 2400 ms)
    gain_label   envelope mode: label of the gain-curve input (mono WAV from envelope_curve/write_gain_wav)
    json_out     also write out/carve_<name>.json {bands, split, headroom_db, duck_db, threshold, mode, report, ranking}
    analysis     reuse a previous analysis dict (skips the decode)
    bed_path     the bed file: its real third-octave levels (at `bed_gain_db`, the mix gain) replace the pink
                 reference, so the carve lands where THIS bed actually competes with the voice
    """
    if mode not in ('dynamic', 'static', 'envelope', 'full'):
        raise ValueError('mode must be dynamic | static | envelope | full, got %r' % mode)
    prof = profile(strength)
    ranking: list[dict] = []
    if analysis is None:
        voice = decode(vo_path)
        bed = decode(bed_path) if bed_path else None
        bands = analyse_bands(voice, SR, prof, bed, bed_gain_db, table=ranking)
        thr = speaking_threshold(voice) if threshold == 'auto' else float(threshold)
    else:
        bands, thr = analysis['bands'], float(analysis.get('threshold', threshold if threshold != 'auto' else 0.03))
        ranking = list(analysis.get('ranking', []))
    split = [float(s) for s in (split or split_from_bands(bands))]
    eq = static_eq_chain(bands, static_depth)          # static mode: pass static_depth=1.0 for the full analysed cut
    parts: list[str] = []
    bed_in = '[%s]' % bed_label
    sink = sc_label and mode in ('static', 'envelope')

    if mode == 'static':
        parts.append('%s%s[%s]' % (bed_in, eq or 'anull', out_label))
    elif mode == 'full':
        if not sc_label:
            raise ValueError('mode full needs sc_label')
        parts.append('%s%s[%s]' % (bed_in, (eq + ',' if eq else '') + SC_ALIGN, '_cv_bq'))
        parts.append('[%s]%s[_cv_ka]' % (sc_label, SC_ALIGN))
        parts.append('[_cv_bq][_cv_ka]%s[%s]' % (FULL_DUCK, out_label))
    else:
        if eq:
            parts.append('%s%s[_cv_bq]' % (bed_in, eq))
            bed_in = '[_cv_bq]'
        parts.append('%sacrossover=split=%d %d:order=4th[_cv_lo][_cv_mid][_cv_hi]' % (bed_in, split[0], split[1]))
        if mode == 'dynamic':
            if not sc_label:
                raise ValueError('mode dynamic needs sc_label')
            key = '[%s]' % sc_label
            if level_match:
                parts.append('[%s]asplit=2[_cv_k1][_cv_k2]' % sc_label)
                key = '[_cv_k1]'
            parts.append('[_cv_mid]%s[_cv_mida]' % SC_ALIGN)
            parts.append('%s%s[_cv_ka]' % (key, SC_ALIGN))
            parts.append('[_cv_mida][_cv_ka]sidechaincompress=threshold=%.4f:ratio=%.2f:attack=%.1f:release=%.0f:makeup=1[_cv_midd]'
                         % (thr, ratio, attack_ms, release_ms))
        else:                                               # envelope
            if not gain_label:
                raise ValueError('mode envelope needs gain_label (the gain-curve WAV input)')
            parts.append('[%s]%s[_cv_g]' % (gain_label, VO_UPMIX))
            parts.append('[_cv_mid][_cv_g]amultiply[_cv_midd]')
        recomb = out_label if not (level_match and mode == 'dynamic') else '_cv_rc'
        parts.append('[_cv_lo][_cv_midd][_cv_hi]amix=inputs=3:normalize=0:duration=first[%s]' % recomb)
        if level_match and mode == 'dynamic':
            parts.append('[_cv_rc]%s[_cv_rca]' % SC_ALIGN)
            parts.append('[_cv_k2]%s[_cv_k2a]' % SC_ALIGN)
            parts.append('[_cv_rca][_cv_k2a]sidechaincompress=threshold=%.4f:ratio=2:attack=50:release=2400[%s]' % (thr, out_label))
    if sink:
        parts.append('[%s]anullsink' % sc_label)
    frag = ';'.join(parts)

    rep = {'mode': mode, 'strength': prof['strength'], 'profile': prof, 'bands': bands, 'split': split,
           'headroom_db': prof['headroom_db'], 'duck_db': prof['duck_db'], 'threshold': round(thr, 4),
           'static_depth': static_depth, 'level_match': bool(level_match), 'report': report_line(bands),
           'bed': os.path.basename(bed_path) if bed_path else 'pink reference %.0f dB under the voice' % REF_VOICE_OVER_BED_DB,
           'bed_gain_db': float(bed_gain_db), 'ranking': ranking, 'fragment': frag}
    if json_out:
        os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
        json.dump(rep, open(json_out, 'w', encoding='utf-8'), indent=1)
    if verbose:
        print('carve %s strength %.2f  %s  split %d/%d Hz  thr %.3f%s  vs %s' % (mode, prof['strength'], rep['report'], split[0], split[1],
              thr, '  + level match' if level_match else '', rep['bed']), file=sys.stderr)
    return frag


def envelope_for_film(phases_path: str, words_path: str, out_wav: str, total: float | None = None,
                      depth_db: float = ENV_DEPTH_DB, release: float = ENV_RELEASE_S) -> dict:
    """Build out/duck_<name>.wav from the narration's own word times. Returns {'wav', 'spans', 'depth_db'}."""
    ph = json.load(open(phases_path, encoding='utf-8'))
    wd = json.load(open(words_path, encoding='utf-8'))
    spans = speech_spans(ph, wd)
    total = float(total if total is not None else ph['total'])
    write_gain_wav(out_wav, envelope_curve(spans, total, depth_db=depth_db, release=release))
    return {'wav': out_wav, 'spans': spans, 'depth_db': depth_db, 'total': total}


# ----------------------------------------------------------------------------------------------- selftest
def _synth_voice(sr: int = SR, dur: float = 6.0) -> np.ndarray:
    """Synthetic 'voice': 140 Hz harmonic stack with formant emphasis near 500 Hz and 1.8 kHz, gated into words."""
    t = np.arange(int(sr * dur)) / sr
    f0 = 140 * (1 + 0.04 * np.sin(2 * np.pi * 2.3 * t))
    ph = np.cumsum(2 * np.pi * f0 / sr)
    x = np.zeros_like(t)
    for k in range(1, 40):
        f = 140 * k
        tilt = (f / 400.0) if f < 400 else (400.0 / f)              # long-term speech spectrum peaks ~400 Hz, -6 dB/oct above
        amp = tilt * (1 + 2.0 * math.exp(-((f - 500) / 180) ** 2) + 2.5 * math.exp(-((f - 1800) / 350) ** 2))
        x += amp * np.sin(k * ph)
    gate = ((np.sin(2 * np.pi * 1.4 * t) > -0.2) & (t > 0.5) & (t < dur - 0.8)).astype(np.float32)
    return (x / np.abs(x).max() * 0.3 * gate).astype(np.float32)


def _synth_bed(sr: int = SR, dur: float = 6.0, hum_hz: Sequence[float] = (262.0, 330.0, 392.0)) -> np.ndarray:
    """Synthetic 'bed' with a loud sustained chord in the low mids (the case a pink reference cannot see)
    over a quiet pink-ish floor (1/f-shaped noise, deterministic seed)."""
    rng = np.random.default_rng(11)
    n = int(sr * dur)
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(n, 1 / sr)
    spec[1:] /= np.sqrt(f[1:]); spec[0] = 0
    floor = np.fft.irfft(spec, n)
    floor /= np.abs(floor).max()
    t = np.arange(n) / sr
    chord = sum(np.sin(2 * np.pi * h * t + i) for i, h in enumerate(hum_hz)) / len(hum_hz)
    return (0.05 * floor + 0.5 * chord).astype(np.float32)


def _selftest() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix='carve_')
    vo = _synth_voice()
    raw = os.path.join(tmp, 'vo.f32')
    open(raw, 'wb').write(vo.tobytes())
    vo_wav = os.path.join(tmp, 'vo.wav')
    _ffmpeg(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', raw, vo_wav], check=True)
    ok = True
    # 1. the knob: anchors from the docstring
    p0, p5, p1 = profile(0.0), profile(0.5), profile(1.0)
    ok &= p0 == {'strength': 0.0, 'max_cut_db': 3.0, 'bands': 1, 'q': 1.0, 'bias': 0.5, 'duck_db': 4.0, 'headroom_db': 9.0}
    ok &= p5 == {'strength': 0.5, 'max_cut_db': 9.0, 'bands': 4, 'q': 2.0, 'bias': 0.75, 'duck_db': 10.0, 'headroom_db': 12.0}
    ok &= p1 == {'strength': 1.0, 'max_cut_db': 15.0, 'bands': 6, 'q': 3.0, 'bias': 1.0, 'duck_db': 16.0, 'headroom_db': 15.0}
    ok &= profile(0.25)['bands'] == 2 and profile(0.8)['bands'] == 5 and profile(float('nan')) == p5
    print('profile(0.5) %s' % p5)
    # 2. presence weight and the audibility window
    ok &= all(abs(presence_weight(f) - 1.0) < 1e-12 for f in (300, 1000, 2000, 3400))
    ok &= abs(presence_weight(150) - 10 ** -1.2) < 1e-9 and abs(presence_weight(6800) - 10 ** -1.2) < 1e-9
    ok &= audibility(-15) == 0.0 and audibility(15) == 1.0 and abs(audibility(0) - 0.5) < 1e-12
    ok &= carve_benefit(20, 9) == 0.0 and abs(carve_benefit(0, 9) - 0.3) < 1e-12 and abs(carve_benefit(-20, 9) - (4 / 30)) < 1e-12
    print('presence 200 %.2f 300 %.2f 3400 %.2f 5000 %.2f  benefit(snr 0, cut 9) %.2f  benefit(snr 20) %.2f'
          % (presence_weight(200), presence_weight(300), presence_weight(3400), presence_weight(5000), carve_benefit(0, 9), carve_benefit(20, 9)))
    # 3a. vs the pink reference the carve lands in the presence region and never on the fundamental
    table: list[dict] = []
    bands = analyse_bands(vo, SR, p5, table=table)
    fs = [b['f'] for b in bands]
    print('pink ref  selected %s' % report_line(bands))
    print('          top of table: ' + ', '.join('%dHz snr %+.0f ben %.2f sc %.3f' % (r['f'], r['snr_db'], r['benefit'], r['score']) for r in table[:6]))
    ok &= len(bands) == 4 and min(fs) >= 300 and sum(1 for f in fs if 1000 <= f <= 4000) >= 3
    ok &= all(-p5['max_cut_db'] <= b['gain_db'] <= -p5['max_cut_db'] / 2 for b in bands)
    # 3b. vs a bed with a loud low-mid chord the carve moves down to where that bed competes
    bed = _synth_bed()
    bands_b = analyse_bands(vo, SR, p5, bed, bed_gain_db=-12.0)
    fs_b = [b['f'] for b in bands_b]
    print('chord bed selected %s' % report_line(bands_b))
    ok &= any(f <= 400 for f in fs_b) and fs_b != fs
    # 3c. a whisper-quiet bed (voice wins everywhere): still a minimal presence carve, never an error
    bands_q = analyse_bands(vo, SR, p5, bed, bed_gain_db=-60.0)
    ok &= len(bands_q) == 4 and all(abs(b['gain_db'] + p5['max_cut_db'] / 2) < 1e-9 for b in bands_q) and all(300 <= b['f'] <= 3400 for b in bands_q)
    print('quiet bed selected %s' % report_line(bands_q))
    # 3d. determinism: the same input twice gives byte-identical analysis
    ok &= json.dumps(analyse_bands(vo, SR, p5, bed, -12.0)) == json.dumps(bands_b)
    # 4. envelope curve from word times
    bed_wav = os.path.join(tmp, 'bed.wav')
    _ffmpeg(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anoisesrc=c=pink:r=48000:d=6:a=0.1:s=7', '-ac', '2', bed_wav], check=True)
    ph = {'total': 6.0, 'phases': [{'name': 'a', 'start': 0.5, 'dur': 2.0}, {'name': 'b', 'start': 3.0, 'dur': 2.2}]}
    wd = {'a': [{'t': 0.0, 'w': 'Acme'}, {'t': 1.6, 'w': 'console'}], 'b': [{'t': 0.1, 'w': 'shows'}, {'t': 1.9, 'w': 'why'}]}
    json.dump(ph, open(os.path.join(tmp, 'ph.json'), 'w')); json.dump(wd, open(os.path.join(tmp, 'wd.json'), 'w'))
    env = envelope_for_film(os.path.join(tmp, 'ph.json'), os.path.join(tmp, 'wd.json'), os.path.join(tmp, 'duck.wav'), total=7.0)
    g = np.frombuffer(open(env['wav'], 'rb').read()[44:], dtype='<f4')
    ok &= env['spans'] == [[0.5, 2.35], [3.1, 5.15]] and abs(g[0] - 1.0) < 1e-6 and abs(20 * math.log10(g[int(1.0 * SR)]) + 10) < 0.05 \
        and abs(g[int(0.3 * SR)] - 1.0) < 1e-6 and g[int(0.4 * SR)] < 1.0 and abs(g[-1] - 1.0) < 1e-6
    print('envelope spans %s  gain@0.3s %.3f @0.4s %.3f @1.0s %.3f end %.3f' % (env['spans'], g[int(0.3 * SR)], g[int(0.4 * SR)], g[int(1.0 * SR)], g[-1]))
    # 5. fragments parse and run in ffmpeg against the pink bed (all four modes, with and without the bed analysis)
    for mode, lm, with_bed in (('dynamic', False, False), ('dynamic', True, True), ('static', False, False), ('envelope', False, False), ('full', False, True)):
        frag = carve_fragment(vo_wav, 'bed', 'vsc', 'bedc', mode=mode, level_match=lm, gain_label='dk' if mode == 'envelope' else None,
                              threshold='auto', json_out=os.path.join(tmp, 'carve_%s.json' % mode), verbose=False,
                              bed_path=bed_wav if with_bed else None, bed_gain_db=-12.0)
        ins = ['-i', vo_wav, '-i', bed_wav] + (['-i', env['wav']] if mode == 'envelope' else [])
        graph = ('[0:a]%s,asplit=2[v][vsc];[1:a]%s,volume=-12dB[bed];%s;[v][bedc]amix=inputs=2:normalize=0:duration=first[out]'
                 % (VO_UPMIX, STEREO_FMT, frag.replace('[dk]', '[2:a]')))
        # the graph that used to spin (asplit key -> sidechaincompress inside acrossover + amix); SC_ALIGN re-frames both legs,
        # _ffmpeg still bounds the wait so a selftest can never hang the build
        r = _ffmpeg(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + ins + ['-filter_complex', graph, '-map', '[out]', '-f', 'null', '-'], timeout=45)
        good = r.returncode == 0
        rep = json.load(open(os.path.join(tmp, 'carve_%s.json' % mode), encoding='utf-8'))
        good &= len(rep['ranking']) == len(THIRD_OCTAVES_HZ) and len(rep['split']) == 2
        ok &= good
        print('%-8s %-3s %-4s %s' % (mode, 'lm' if lm else '', 'bed' if with_bed else '', 'RUNS' if good else 'FAILED ' + r.stderr[-300:]))
        print('         ' + frag[:150] + ('...' if len(frag) > 150 else ''))
    # 6. mono upmix: VO_UPMIX keeps the level, aformat loses 3 dB
    def rms_db(filt):
        r = _ffmpeg(['ffmpeg', '-nostdin', '-hide_banner', '-i', vo_wav, '-af', filt + ',astats=measure_perchannel=RMS_level:measure_overall=none',
                     '-f', 'null', '-'], timeout=45)
        return float([l for l in r.stderr.splitlines() if 'RMS level dB' in l][0].split(':')[-1])
    a, b = rms_db(VO_UPMIX), rms_db('aformat=channel_layouts=stereo')
    ok &= abs(a - b - 3.0) < 0.15
    print('upmix pan %.2f dB vs aformat %.2f dB (delta %.2f, expect 3.0)' % (a, b, a - b))
    print('SELFTEST %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('vo', nargs='?', help='assembled narration (vo_<name>.mp3)')
    ap.add_argument('--bed', help='the music bed: rank the bands against ITS spectrum instead of a pink reference')
    ap.add_argument('--bed-db', type=float, default=0.0, help='mix gain applied to the bed (film.json bed_db, e.g. -12)')
    ap.add_argument('--strength', type=float, default=0.5)
    ap.add_argument('--mode', default='dynamic', choices=['dynamic', 'static', 'envelope', 'full'])
    ap.add_argument('--bed-label', default='bed'); ap.add_argument('--sc-label', default='vsc'); ap.add_argument('--out-label', default='bedc')
    ap.add_argument('--gain-label', default='dk', help='envelope mode: label of the gain-curve input')
    ap.add_argument('--split', type=float, nargs=2, metavar=('LO', 'HI'))
    ap.add_argument('--ratio', type=float, default=6.0); ap.add_argument('--threshold', default='0.03', help="linear, or 'auto'")
    ap.add_argument('--attack-ms', type=float, default=15); ap.add_argument('--release-ms', type=float, default=2000)
    ap.add_argument('--static-depth', type=float, default=0.5); ap.add_argument('--level-match', action='store_true')
    ap.add_argument('--json', help='write out/carve_<name>.json')
    ap.add_argument('--phases'); ap.add_argument('--words'); ap.add_argument('--envelope-wav'); ap.add_argument('--total', type=float)
    ap.add_argument('--depth-db', type=float, default=ENV_DEPTH_DB); ap.add_argument('--release', type=float, default=ENV_RELEASE_S)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.vo:
        ap.error('vo path required (or --selftest)')
    if a.mode == 'envelope':
        if not (a.phases and a.words and a.envelope_wav):
            ap.error('envelope mode needs --phases --words --envelope-wav')
        env = envelope_for_film(a.phases, a.words, a.envelope_wav, a.total, a.depth_db, a.release)
        print('envelope %s  %d spans  depth %.1f dB' % (env['wav'], len(env['spans']), env['depth_db']), file=sys.stderr)
    thr = 'auto' if a.threshold == 'auto' else float(a.threshold)
    print(carve_fragment(a.vo, a.bed_label, a.sc_label, a.out_label, mode=a.mode, strength=a.strength, split=a.split, ratio=a.ratio,
                         threshold=thr, attack_ms=a.attack_ms, release_ms=a.release_ms, level_match=a.level_match,
                         static_depth=a.static_depth, gain_label=a.gain_label, json_out=a.json,
                         bed_path=a.bed, bed_gain_db=a.bed_db))
    return 0


if __name__ == '__main__':
    sys.exit(main())
