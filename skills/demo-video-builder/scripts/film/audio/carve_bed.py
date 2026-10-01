# -*- coding: utf-8 -*-
"""carve_bed.py — carve the music bed around the narration instead of ducking the whole thing.

    python audio/carve_bed.py vo_film.mp3                       # prints an ffmpeg filter_complex FRAGMENT
    python audio/carve_bed.py vo_film.mp3 --strength 0.5 --mode dynamic --json out/carve_film.json
    python audio/carve_bed.py vo_film.mp3 --mode envelope --phases vo/film_phases.json --words vo/film_words.json \
                                          --envelope-wav out/duck_film.wav --total 93.3
    python audio/carve_bed.py --selftest

What it does
  1. Decodes the assembled narration (vo_<name>.mp3, every voice already summed on the film clock) to mono
     48 kHz float and measures its Welch power spectrum: FRAME 4096, HOP 2048, Hann, EVERY hop averaged
     (striding the hops was measured to change the chosen bands).
  2. Scores nine third-octave candidate bands (160 … 6000 Hz) by band power minus an intelligibility
     penalty of  bias × 30 dB × (1 − exp(−(log2(f/2000))² / 2))  — a penalty in dB, because a multiplicative
     weight has at most ~5 dB of authority against speech's own 20–30 dB tilt and always picks the fundamental.
  3. Maps ONE knob (strength 0..1) to the six mechanism numbers:
        max cut 2 + 16·s dB · bands round(1 + 6·s) in 1..6 · Q 1.1 + 1.2·s · bias min(1, 0.6 + 0.4·s)
        duck 24·s dB · headroom under the voice 6 + 12·s dB
     Selected-band depth = maxCut × 10^((score − top)/10), floored at maxCut/2.
  4. Emits an ffmpeg filter_complex fragment (a string, no shelling out) that build_film.py splices into its
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
        full      today's whole-bed sidechain (threshold 0.04, ratio 4, attack 20, release 500) for A/B.
     --level-match adds HyperFrames' second stage: a shallow full-band sidechain (ratio 2, release 2.4 s —
     1.6 s still read as the music 'coming back' at every sentence break) AFTER the spectral stage.

Measured here (ffmpeg 8.1.1, pink bed, gated 220 Hz voice): a 250–2500 Hz-only sidechain (thr 0.03, ratio 6)
dropped the mid band 9.7 dB under the voice while the whole bed moved 1.3 dB; the full-band duck on a −9 dB
bed pulled it a further 4.9 dB everywhere.

Mono-narration gotcha: gen_vo_multivoice.build_track() writes MONO. ffmpeg's default mono→stereo rematrix
(aformat / -ac 2) loses 3 dB (measured −41.1 → −44.1 dB RMS). Upmix with VO_UPMIX below (pan keeps the level
and passes a stereo input through unchanged). The fragment assumes the caller already did this.

Band-selection and the strength→profile mapping follow HyperFrames' audioCarve.ts (Apache-2.0, HeyGen); see
NOTICE.md. Everything else is re-expressed for ffmpeg.
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
CANDIDATES_HZ = (160, 250, 400, 630, 1000, 1600, 2500, 4000, 6000)   # third-octave centres speech occupies
FRAME, HOP = 4096, 2048                                              # Welch analysis frame / hop
BIAS_AUTHORITY_DB = 30.0                                             # full-strength ranking authority (dB)
SPEAKING_RANGE_DB = 30.0                                             # a window 30 dB under the voice peak is not speech
SR = 48000

#: Mono → stereo WITHOUT the 3 dB rematrix loss; a stereo input passes through unchanged.
VO_UPMIX = 'pan=stereo|FL=FL+FC|FR=FR+FC,aformat=sample_fmts=fltp:sample_rates=48000'
#: Stereo conform for a bed / sfx / gain-curve input (already stereo → no change).
STEREO_FMT = 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'

#: Today's whole-bed duck, kept verbatim as mode 'full' for A/B listening.
FULL_DUCK = 'sidechaincompress=threshold=0.04:ratio=4:attack=20:release=500'

# Deterministic word-timestamp envelope defaults (envelope mode).
ENV_MERGE_GAP_S = 0.6        # speech spans closer than this merge, so the bed does not pump between words
ENV_TAIL_S = 0.25            # span runs this far past the last word's onset (edge-tts adds ~0.5 s of silence)
ENV_LEAD_S = 0.15            # the duck starts this far BEFORE the first word (anticipation a compressor cannot do)
ENV_ATTACK_S = 0.15
ENV_RELEASE_S = 1.5          # between HyperFrames' 0.4 s UI duck and its 2.4 s level release
ENV_DEPTH_DB = -10.0


# ----------------------------------------------------------------------------------------------- decode
def decode(path: str, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` through ffmpeg (-f f32le). Returns a 1-D array."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr),
                        '-f', 'f32le', '-'], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError('decode failed for %s: %s' % (path, r.stderr.decode('utf-8', 'replace')[-400:]))
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


# ----------------------------------------------------------------------------------------------- analysis
def profile(strength: float) -> dict:
    """One knob → six numbers. 0.25 = 6 dB in 3 bands with 6 dB room; 0.5 ≈ 10 dB (starts to read as an effect);
    0.8 = six bands ≈ −7.4 dB each (−14.8 at the top band), Q 2.06, 19 dB of level room."""
    s = min(1.0, max(0.0, float(strength))) if math.isfinite(strength) else 0.5
    return {
        'strength': round(s, 3),
        'max_cut_db': round(2 + s * 16, 2),
        'bands': max(1, min(6, int(math.floor(1 + s * 6 + 0.5)))),   # half-up like JS Math.round (0.25 -> 3)
        'q': round(1.1 + s * 1.2, 2),
        'bias': round(min(1.0, 0.6 + s * 0.4), 2),
        'duck_db': round(s * 24, 2),
        'headroom_db': round(6 + s * 12, 2),
    }


def power_spectrum(mono: np.ndarray, sr: int = SR, frame: int = FRAME, hop: int = HOP) -> tuple[np.ndarray, np.ndarray]:
    """Welch-averaged power spectrum over EVERY hop (Hann window). Returns (freqs, power), both length frame/2+1."""
    x = np.asarray(mono, dtype=np.float32)
    if x.size < frame:
        x = np.pad(x, (0, frame - x.size))
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(frame) / (frame - 1))).astype(np.float32)
    n_frames = 1 + (x.size - frame) // hop
    acc = np.zeros(frame // 2 + 1, dtype=np.float64)
    view = np.lib.stride_tricks.sliding_window_view(x, frame)[::hop][:n_frames]
    for k in range(0, n_frames, 512):                           # chunked so a 5-minute VO stays under ~50 MB
        spec = np.fft.rfft(view[k:k + 512] * win, axis=1)
        acc += (spec.real ** 2 + spec.imag ** 2).sum(axis=0)
    acc /= max(1, n_frames)
    freqs = np.arange(frame // 2 + 1) * (sr / frame)
    return freqs, acc


def band_power(freqs: np.ndarray, power: np.ndarray, center: float) -> float:
    """Mean bin power inside the third-octave band around `center` (center / 2^(1/6) … center × 2^(1/6))."""
    lo, hi = center / 2 ** (1 / 6), center * 2 ** (1 / 6)
    m = (freqs >= lo) & (freqs < hi)
    return float(power[m].mean()) if m.any() else 0.0


def penalty_db(center: float, bias: float) -> float:
    """Ranking penalty: 0 dB at 2 kHz (where intelligibility lives), rising with octave distance either way."""
    oct_from_2k = math.log2(center / 2000.0)
    return bias * BIAS_AUTHORITY_DB * (1 - math.exp(-(oct_from_2k ** 2) / 2))


def analyse_bands(mono: np.ndarray, sr: int = SR, prof: dict | None = None) -> list[dict]:
    """Rank the candidate bands for this voice and return the cuts, ascending in frequency:
    [{'f': Hz, 'gain_db': −depth, 'q': Q, 'score_db': ranking score}]."""
    prof = prof or profile(0.5)
    if mono.size == 0:
        return []
    freqs, power = power_spectrum(mono, sr)
    scored = []
    for c in CANDIDATES_HZ:
        p = band_power(freqs, power, c)
        if p > 0:
            scored.append((10 * math.log10(p) - penalty_db(c, prof['bias']), c))
    scored.sort(reverse=True)
    sel = scored[:max(1, prof['bands'])]
    if not sel:
        return []
    top = sel[0][0]
    out = []
    for score, c in sel:
        rel = 10 ** ((score - top) / 10)
        depth = min(prof['max_cut_db'], max(prof['max_cut_db'] / 2, prof['max_cut_db'] * rel))
        out.append({'f': c, 'gain_db': -round(depth, 2), 'q': prof['q'], 'score_db': round(score, 2)})
    return sorted(out, key=lambda b: b['f'])


def split_from_bands(bands: Sequence[dict], lo_floor: float = 250.0, hi_cap: float = 6000.0) -> list[float]:
    """Crossover points enclosing the selected bands by a third octave. The low split never goes under 250 Hz:
    the fundamental (160–250 Hz) is the loudest band but cutting it only thins the bed."""
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
                   json_out: str | None = None, analysis: dict | None = None, verbose: bool = True) -> str:
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
    json_out     also write out/carve_<name>.json {bands, split, headroom_db, duck_db, threshold, mode, report}
    analysis     reuse a previous analysis dict (skips the decode)
    """
    if mode not in ('dynamic', 'static', 'envelope', 'full'):
        raise ValueError('mode must be dynamic | static | envelope | full, got %r' % mode)
    prof = profile(strength)
    if analysis is None:
        voice = decode(vo_path)
        bands = analyse_bands(voice, SR, prof)
        thr = speaking_threshold(voice) if threshold == 'auto' else float(threshold)
    else:
        bands, thr = analysis['bands'], float(analysis.get('threshold', threshold if threshold != 'auto' else 0.03))
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
        parts.append('%s%s[%s]' % (bed_in, (eq + ',' if eq else '') + 'anull', '_cv_bq'))
        parts.append('[_cv_bq][%s]%s[%s]' % (sc_label, FULL_DUCK, out_label))
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
            parts.append('[_cv_mid]%ssidechaincompress=threshold=%.4f:ratio=%.2f:attack=%.1f:release=%.0f:makeup=1[_cv_midd]'
                         % (key, thr, ratio, attack_ms, release_ms))
        else:                                               # envelope
            if not gain_label:
                raise ValueError('mode envelope needs gain_label (the gain-curve WAV input)')
            parts.append('[%s]%s[_cv_g]' % (gain_label, VO_UPMIX))
            parts.append('[_cv_mid][_cv_g]amultiply[_cv_midd]')
        recomb = out_label if not (level_match and mode == 'dynamic') else '_cv_rc'
        parts.append('[_cv_lo][_cv_midd][_cv_hi]amix=inputs=3:normalize=0:duration=first[%s]' % recomb)
        if level_match and mode == 'dynamic':
            parts.append('[_cv_rc][_cv_k2]sidechaincompress=threshold=%.4f:ratio=2:attack=50:release=2400[%s]' % (thr, out_label))
    if sink:
        parts.append('[%s]anullsink' % sc_label)
    frag = ';'.join(parts)

    rep = {'mode': mode, 'strength': prof['strength'], 'profile': prof, 'bands': bands, 'split': split,
           'headroom_db': prof['headroom_db'], 'duck_db': prof['duck_db'], 'threshold': round(thr, 4),
           'static_depth': static_depth, 'level_match': bool(level_match), 'report': report_line(bands), 'fragment': frag}
    if json_out:
        os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
        json.dump(rep, open(json_out, 'w', encoding='utf-8'), indent=1)
    if verbose:
        print('carve %s strength %.2f  %s  split %d/%d Hz  thr %.3f%s' % (mode, prof['strength'], rep['report'], split[0], split[1],
              thr, '  + level match' if level_match else ''), file=sys.stderr)
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


def _selftest() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix='carve_')
    vo = _synth_voice()
    raw = os.path.join(tmp, 'vo.f32')
    open(raw, 'wb').write(vo.tobytes())
    vo_wav = os.path.join(tmp, 'vo.wav')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', raw, vo_wav], check=True)
    ok = True
    # 1. profile anchors from the study
    p8, p25 = profile(0.8), profile(0.25)
    ok &= p8['bands'] == 6 and abs(p8['q'] - 2.06) < 1e-9 and abs(p8['max_cut_db'] - 14.8) < 1e-9 and abs(p8['headroom_db'] - 15.6) < 1e-9
    ok &= p25['bands'] == 3 and abs(p25['max_cut_db'] - 6.0) < 1e-9 and abs(p25['headroom_db'] - 9.0) < 1e-9
    print('profile(0.8) %s' % p8); print('profile(0.25) %s' % p25)
    # 2. penalty: 0 at 2 kHz, symmetric-ish in octaves, 30·bias far away
    ok &= abs(penalty_db(2000, 1.0)) < 1e-9 and 20 < penalty_db(160, 1.0) < 30 and penalty_db(1600, 1.0) < 2
    print('penalty 160 %.1f 1600 %.2f 2000 %.1f 6000 %.1f dB' % (penalty_db(160, 1), penalty_db(1600, 1), penalty_db(2000, 1), penalty_db(6000, 1)))
    # 3. analysis picks the formant/presence bands, never only the fundamental
    bands = analyse_bands(vo, SR, profile(0.5))
    fs = [b['f'] for b in bands]
    print('selected %s' % report_line(bands))
    ok &= len(bands) == 4 and 160 not in fs and any(f >= 1000 for f in fs)      # formants/presence win, not the fundamental
    ok &= all(-profile(0.5)['max_cut_db'] <= b['gain_db'] <= -profile(0.5)['max_cut_db'] / 2 for b in bands)
    # 4. fragments parse and run in ffmpeg against a pink bed (all four modes)
    bed = os.path.join(tmp, 'bed.wav')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anoisesrc=c=pink:r=48000:d=6:a=0.1:s=7', '-ac', '2', bed], check=True)
    ph = {'total': 6.0, 'phases': [{'name': 'a', 'start': 0.5, 'dur': 2.0}, {'name': 'b', 'start': 3.0, 'dur': 2.2}]}
    wd = {'a': [{'t': 0.0, 'w': 'Acme'}, {'t': 1.6, 'w': 'console'}], 'b': [{'t': 0.1, 'w': 'shows'}, {'t': 1.9, 'w': 'why'}]}
    json.dump(ph, open(os.path.join(tmp, 'ph.json'), 'w')); json.dump(wd, open(os.path.join(tmp, 'wd.json'), 'w'))
    env = envelope_for_film(os.path.join(tmp, 'ph.json'), os.path.join(tmp, 'wd.json'), os.path.join(tmp, 'duck.wav'), total=7.0)
    g = np.frombuffer(open(env['wav'], 'rb').read()[44:], dtype='<f4')
    ok &= env['spans'] == [[0.5, 2.35], [3.1, 5.15]] and abs(g[0] - 1.0) < 1e-6 and abs(20 * math.log10(g[int(1.0 * SR)]) + 10) < 0.05 \
        and abs(g[int(0.3 * SR)] - 1.0) < 1e-6 and g[int(0.4 * SR)] < 1.0 and abs(g[-1] - 1.0) < 1e-6
    print('envelope spans %s  gain@0.3s %.3f @0.4s %.3f @1.0s %.3f end %.3f' % (env['spans'], g[int(0.3 * SR)], g[int(0.4 * SR)], g[int(1.0 * SR)], g[-1]))
    for mode, lm in (('dynamic', False), ('dynamic', True), ('static', False), ('envelope', False), ('full', False)):
        frag = carve_fragment(vo_wav, 'bed', 'vsc', 'bedc', mode=mode, level_match=lm, gain_label='dk' if mode == 'envelope' else None,
                              threshold='auto', json_out=os.path.join(tmp, 'carve_%s.json' % mode), verbose=False)
        ins = ['-i', vo_wav, '-i', bed] + (['-i', env['wav']] if mode == 'envelope' else [])
        graph = ('[0:a]%s,asplit=2[v][vsc];[1:a]%s,volume=-12dB[bed];%s;[v][bedc]amix=inputs=2:normalize=0:duration=first[out]'
                 % (VO_UPMIX, STEREO_FMT, frag.replace('[dk]', '[2:a]')))
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + ins + ['-filter_complex', graph, '-map', '[out]', '-f', 'null', '-'],
                           capture_output=True, text=True)
        good = r.returncode == 0
        ok &= good
        print('%-8s %-5s %s' % (mode, 'lm' if lm else '', 'RUNS' if good else 'FAILED ' + r.stderr[-300:]))
        print('         ' + frag[:150] + ('...' if len(frag) > 150 else ''))
    # 5. mono upmix: VO_UPMIX keeps the level, aformat loses 3 dB
    def rms_db(filt):
        r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', vo_wav, '-af', filt + ',astats=measure_perchannel=RMS_level:measure_overall=none',
                            '-f', 'null', '-'], capture_output=True, text=True)
        return float([l for l in r.stderr.splitlines() if 'RMS level dB' in l][0].split(':')[-1])
    a, b = rms_db(VO_UPMIX), rms_db('aformat=channel_layouts=stereo')
    ok &= abs(a - b - 3.0) < 0.15
    print('upmix pan %.2f dB vs aformat %.2f dB (delta %.2f, expect 3.0)' % (a, b, a - b))
    print('SELFTEST %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('vo', nargs='?', help='assembled narration (vo_<name>.mp3)')
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
                         static_depth=a.static_depth, gain_label=a.gain_label, json_out=a.json))
    return 0


if __name__ == '__main__':
    sys.exit(main())
