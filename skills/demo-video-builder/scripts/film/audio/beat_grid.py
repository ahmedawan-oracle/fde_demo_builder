# -*- coding: utf-8 -*-
"""beat_grid.py — a beat grid for the music bed, so the few cuts that are not word-anchored can land on bars.

    python audio/beat_grid.py bed.mp3 --out out/beats_film.json
    python audio/beat_grid.py bed.mp3 --anchor 3.25 --film-len 93.3       # also prints the bed in-point
    python audio/beat_grid.py --selftest

Recipe (numpy only; onset/grid steps follow HyperFrames' beatDetection.ts, Apache-2.0, HeyGen — see NOTICE.md):
  decode mono 22.05 kHz → energy per 1024-sample window, hop 512 → an ONSET is a local maximum above 1.5 × the
  mean of the ±20 neighbouring windows, ≥ 0.1 s after the previous onset → BPM₁ = 60 / median inter-onset
  interval (needs ≥ 4 onsets).  A second, independent reading BPM₂ comes from the autocorrelation of the
  onset-strength curve (60–200 BPM lag range; replaces the browser-only bpm-detective).  Both are folded to
  60–120 for comparison: agree within 5 % → confidence 'high' (BPM₂ octave-aligned to the onset pulse),
  within 10 % → 'low' (average), else 'uncertain' (raw onsets are the beats, no grid).  The grid is the BPM
  laid from the phase (searched over the first ten onsets) that puts the most onsets within ±25 % of a beat;
  intervals under 0.125 s bail to raw onsets.  Beats whose ±50 ms RMS is under 12 % of the loudest are dropped
  (intro/outro) and each survivor carries strength = RMS / peak.
  Downbeats: the bar phase (of 4) whose beats carry the most kick energy (< 150 Hz).  Phrases: every 4 bars.
  Energy phases from 1 s RMS normalised to the loudest second: VOID < 0.2, LOW < 0.4, MEDIUM < 0.65, else HIGH;
  key moments |Δ| > 0.12 between consecutive seconds; a hard stop is a drop < −0.25 inside the last 40 %.

Trust rule: BPM and beat precision are reliable only on rhythmic music. On a calm underscore the grid is a
metronome the tracker imposed (often octave-doubled, more grid beats than real onsets): `rhythmic` is False,
snap() becomes a no-op, and you pace by phrases and energy instead. Never move a word-anchored cut to a beat —
words win, the bed moves (the in-point).

Outputs out/beats_<name>.json:
  {bpm, confidence, offset, beats:[{t, strength}], downbeats:[t], phrases:[t], energy_phases:[{start, end,
   level, rms}], key_moments:[t], hard_stops:[t], rhythmic, duration}
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from typing import Sequence

import numpy as np

SR = 22050
WINDOW, HOP = 1024, 512
LOCAL_WINDOWS, ONSET_FACTOR, MIN_ONSET_GAP_S = 20, 1.5, 0.1
GRID_TOL, MIN_BEAT_S, PHASE_ANCHORS = 0.25, 0.125, 10
SILENCE_FRAC, STRENGTH_WINDOW_S = 0.12, 0.05
KICK_HZ, KICK_WINDOW_S, BEATS_PER_BAR, BARS_PER_PHRASE = 150.0, 0.1, 4, 4   # a kick lasts 100-200 ms
ENERGY_LEVELS = ((0.2, 'VOID'), (0.4, 'LOW'), (0.65, 'MEDIUM'), (9.0, 'HIGH'))
KEY_MOMENT_DELTA, HARD_STOP_DROP, HARD_STOP_TAIL = 0.12, -0.25, 0.4
RHYTHMIC_MIN_ONSET_RATE, RHYTHMIC_MIN_COVERAGE = 1.0, 0.5     # onsets/s and share of grid beats backed by an onset
SNAP_TOL_S = 0.25


# ----------------------------------------------------------------------------------------------- decode + onsets
def decode(path: str, sr: int = SR) -> np.ndarray:
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError('decode failed for %s: %s' % (path, r.stderr.decode('utf-8', 'replace')[-300:]))
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def energy_curve(x: np.ndarray, window: int = WINDOW, hop: int = HOP) -> np.ndarray:
    """Mean-square energy per window."""
    if x.size < window:
        return np.zeros(0)
    v = np.lib.stride_tricks.sliding_window_view(x, window)[::hop]
    return (v.astype(np.float64) ** 2).mean(axis=1)


def detect_onsets(energies: np.ndarray, sr: int = SR, hop: int = HOP) -> list[float]:
    """Local maxima above 1.5 × the mean of the surrounding ±20 windows, at least 0.1 s apart."""
    e, L = energies, LOCAL_WINDOWS
    if e.size <= 2 * L + 1:
        return []
    c = np.concatenate([[0.0], np.cumsum(e)])
    local_mean = (c[2 * L:] - c[:-2 * L]) / (2 * L)                 # mean of e[i-L : i+L] for i in L..n-L
    idx = np.arange(L, e.size - L)
    local_mean = local_mean[:idx.size]
    cur = e[idx]
    peak = (cur > ONSET_FACTOR * local_mean) & (cur > e[idx - 1]) & (cur > e[idx + 1])
    out: list[float] = []
    for i in idx[peak]:
        t = i * hop / sr
        if not out or t - out[-1] > MIN_ONSET_GAP_S:
            out.append(round(t, 3))
    return out


def bpm_from_onsets(onsets: Sequence[float]) -> float | None:
    if len(onsets) < 4:
        return None
    ioi = np.diff(np.asarray(onsets))
    med = float(np.median(ioi))
    return round(60.0 / med, 1) if med > 0 else None


def bpm_autocorr(energies: np.ndarray, sr: int = SR, hop: int = HOP, lo_bpm: float = 60, hi_bpm: float = 200) -> float | None:
    """Second detector: autocorrelation of the onset-strength curve (half-wave rectified log-energy difference)."""
    if energies.size < 8:
        return None
    le = np.log(energies + 1e-10)
    osf = np.maximum(0.0, np.diff(le))
    osf -= osf.mean()
    n = 1 << int(math.ceil(math.log2(2 * osf.size)))
    f = np.fft.rfft(osf, n)
    ac = np.fft.irfft(f * np.conj(f), n)[:osf.size]
    sec_per_hop = hop / sr
    lo, hi = int(60.0 / hi_bpm / sec_per_hop), int(60.0 / lo_bpm / sec_per_hop)
    if hi <= lo + 1 or hi >= ac.size:
        return None
    lag = lo + int(np.argmax(ac[lo:hi]))
    return round(60.0 / (lag * sec_per_hop), 1)


def canonical(bpm: float) -> float:
    while bpm > 120:
        bpm /= 2
    while bpm < 60:
        bpm *= 2
    return bpm


def octave_align(bpm: float, reference: float) -> float:
    return min((bpm / 2, bpm, bpm * 2), key=lambda c: abs(c - reference))


def regularize(onsets: Sequence[float], bpm: float, duration: float) -> tuple[list[float], float]:
    """Lay the BPM grid from the phase (among the first ten onsets) that captures the most onsets within ±25 %,
    then refine interval + phase by a least-squares fit of the captured onsets (our addition: the median IOI is
    quantised to the 23 ms hop, which drifted 0.18 s over 30 s at 100 BPM). Returns (beats, refined_bpm)."""
    if not onsets or bpm <= 0 or duration <= 0:
        return list(onsets), bpm
    iv = 60.0 / bpm
    if iv < MIN_BEAT_S:
        return list(onsets), bpm
    on = np.asarray(onsets, dtype=np.float64)
    ph = np.mod(on, iv)
    best_off, best = 0.0, -1
    for a in onsets[:PHASE_ANCHORS]:
        off = a % iv
        d = np.abs(ph - off)
        score = int(((np.minimum(d, iv - d)) < iv * GRID_TOL).sum())
        if score > best:
            best, best_off = score, off
    k = np.round((on - best_off) / iv)
    resid = on - (best_off + k * iv)
    hit = np.abs(resid) < iv * GRID_TOL
    if hit.sum() >= 4 and np.ptp(k[hit]) > 0:
        slope, icpt = np.polyfit(k[hit], on[hit], 1)
        if abs(slope - iv) / iv < 0.05:                    # accept only a small correction of the tempo
            iv, best_off = float(slope), float(icpt % slope)
    beats = [round(float(t), 3) for t in np.arange(best_off, duration + 1e-3, iv)]
    return beats, round(60.0 / iv, 2)


def rms_at(x: np.ndarray, sr: int, t: float, half_s: float = STRENGTH_WINDOW_S) -> float:
    h = int(sr * half_s)
    c = int(t * sr)
    seg = x[max(0, c - h):min(x.size, c + h)]
    return float(np.sqrt((seg.astype(np.float64) ** 2).mean())) if seg.size else 0.0


def gate_by_silence(beats: Sequence[float], x: np.ndarray, sr: int = SR) -> tuple[list[float], list[float], float]:
    """Drop beats in near-silence (±50 ms RMS under 12 % of the loudest beat); strength = RMS / peak."""
    if not beats:
        return [], [], 1e-6
    e = np.array([rms_at(x, sr, t) for t in beats])
    peak = max(float(e.max()), 1e-6)
    keep = e >= peak * SILENCE_FRAC
    return [float(b) for b, k in zip(beats, keep) if k], [round(float(min(1.0, v / peak)), 3) for v, k in zip(e, keep) if k], float(peak)


# ----------------------------------------------------------------------------------------------- structure
def kick_band(x: np.ndarray, sr: int = SR, cutoff: float = KICK_HZ) -> np.ndarray:
    """Brick-wall low-pass via FFT (no scipy): the kick fundamental region."""
    X = np.fft.rfft(x.astype(np.float64))
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    X[f > cutoff] = 0
    return np.fft.irfft(X, x.size)


def downbeat_phase(beats: Sequence[float], x: np.ndarray, sr: int = SR) -> int:
    """Bar phase (0..3) whose beats carry the most kick (< 150 Hz) energy."""
    if len(beats) < BEATS_PER_BAR:
        return 0
    k = kick_band(x, sr)
    scores = [sum(rms_at(k, sr, t, KICK_WINDOW_S) ** 2 for t in beats[p::BEATS_PER_BAR]) for p in range(BEATS_PER_BAR)]
    return int(np.argmax(scores))


def energy_phases(x: np.ndarray, sr: int = SR) -> tuple[list[dict], list[float], list[float]]:
    """1 s RMS normalised to the loudest second → contiguous level phases, key moments, hard stops."""
    n = x.size // sr
    if n == 0:
        return [], [], []
    rms = np.sqrt((x[:n * sr].reshape(n, sr).astype(np.float64) ** 2).mean(axis=1))
    norm = rms / max(float(rms.max()), 1e-9)
    level = lambda v: next(name for lim, name in ENERGY_LEVELS if v < lim)
    phases: list[dict] = []
    for i, v in enumerate(norm):
        lv = level(v)
        if phases and phases[-1]['level'] == lv:
            phases[-1]['end'] = i + 1
            phases[-1]['_acc'].append(v)
        else:
            phases.append({'start': i, 'end': i + 1, 'level': lv, '_acc': [v]})
    for p in phases:
        p['rms'] = round(float(np.mean(p.pop('_acc'))), 3)
    delta = np.diff(norm)
    key = [int(i + 1) for i in np.where(np.abs(delta) > KEY_MOMENT_DELTA)[0]]
    tail_from = int(n * (1 - HARD_STOP_TAIL))
    stops = [int(i + 1) for i in np.where(delta < HARD_STOP_DROP)[0] if i + 1 >= tail_from]
    return phases, key, stops


def is_rhythmic(onsets: Sequence[float], grid: Sequence[float], bpm: float | None, duration: float, confidence: str) -> bool:
    """Trust rule: a confident tempo, ≥ 1 onset/s, and at least half the grid beats backed by a real onset."""
    if confidence == 'uncertain' or not bpm or not grid or duration <= 0:
        return False
    if len(onsets) / duration < RHYTHMIC_MIN_ONSET_RATE:
        return False
    on = np.asarray(onsets)
    tol = 60.0 / bpm * GRID_TOL
    covered = sum(1 for b in grid if np.abs(on - b).min() <= tol)
    return covered / len(grid) >= RHYTHMIC_MIN_COVERAGE


# ----------------------------------------------------------------------------------------------- analyse
def analyse(path: str) -> dict:
    """Full analysis of a bed file → the beats.json dict (see module docstring)."""
    x = decode(path)
    duration = x.size / SR
    e = energy_curve(x)
    onsets = detect_onsets(e)
    b1, b2 = bpm_from_onsets(onsets), bpm_autocorr(e)
    bpm, conf, grid_bpm = None, 'uncertain', None
    if b1 and b2:
        pct = abs(canonical(b1) - canonical(b2)) / canonical(b2)
        if pct < 0.05:
            bpm, conf = octave_align(b2, b1), 'high'
        elif pct < 0.10:
            bpm, conf = round((b1 + b2) / 2), 'low'
        else:
            bpm, conf = b1, 'uncertain'
        grid_bpm = bpm if conf != 'uncertain' else None
    elif b1:
        bpm, conf, grid_bpm = b1, 'low', b1
    elif b2:                                             # autocorrelation alone, under 4 onsets: a hint, never a grid
        bpm, conf, grid_bpm = b2, 'uncertain', None
    if grid_bpm:
        grid, bpm = regularize(onsets, grid_bpm, duration)
    else:
        grid = list(onsets)
    phase = downbeat_phase(grid, x)                      # on the FULL grid, before quiet beats are dropped
    downbeat_set = set(grid[phase::BEATS_PER_BAR])
    times, strengths, peak = gate_by_silence(grid, x)
    downbeats = [t for t in times if t in downbeat_set]
    phrases = downbeats[::BARS_PER_PHRASE]
    ep, key, stops = energy_phases(x)
    return {
        'source': os.path.basename(path), 'duration': round(duration, 3), 'bpm': round(bpm, 1) if bpm else None,
        'bpm_onsets': b1, 'bpm_autocorr': b2, 'confidence': conf, 'offset': times[0] if times else None, 'bar_phase': phase,
        'beats': [{'t': t, 'strength': s} for t, s in zip(times, strengths)], 'downbeats': downbeats, 'phrases': phrases,
        'onsets': onsets, 'energy_phases': ep, 'key_moments': key, 'hard_stops': stops,
        'rhythmic': is_rhythmic(onsets, times, bpm, duration, conf),
    }


# ----------------------------------------------------------------------------------------------- helpers for build / shots
def beat_times(grid: dict) -> list[float]:
    return [b['t'] if isinstance(b, dict) else float(b) for b in grid.get('beats', [])]


def snap(t: float, grid: dict, tol: float = SNAP_TOL_S) -> float:
    """Nearest beat within `tol` seconds, else `t` unchanged. A no-op when the bed is not rhythmic (trust rule).
    Use ONLY on cues not tied to words (opener reveal, closing card, SFX hits)."""
    if not grid.get('rhythmic'):
        return t
    bt = beat_times(grid)
    if not bt:
        return t
    arr = np.asarray(bt)
    i = int(np.abs(arr - t).argmin())
    return float(arr[i]) if abs(arr[i] - t) <= tol else t


def bed_in_point(grid: dict, anchor_t: float, fade_in: float = 1.5, film_len: float | None = None, section_s: float = 5.0) -> dict:
    """Where to start the bed so a downbeat lands on `anchor_t` (film clock, e.g. wt('title', 'Acme')).
    offset = downbeat − anchor_t ≥ 0 (an anchor inside the fade-in is allowed and noted); among candidates prefer one whose
    first `section_s` seconds of bed audio are at least as strong as the bed's median section (do not assume the
    file's start is the best entrance) and, if film_len is given, leave enough bed to cover the film. Returns
    {'offset', 'downbeat', 'bed_rms', 'median_rms', 'reason'}; offset 0 with a reason when nothing fits."""
    dbs = [d for d in grid.get('downbeats', []) if d - anchor_t >= 0]
    if not grid.get('rhythmic'):
        return {'offset': 0.0, 'downbeat': None, 'reason': 'not rhythmic: pace by phrases and energy, keep the file start'}
    if not dbs:
        return {'offset': 0.0, 'downbeat': None, 'reason': 'no downbeat at or after the anchor time'}
    note = '' if anchor_t >= fade_in else ' (anchor %.2f s is inside the %.1f s fade-in: the downbeat lands mid-fade)' % (anchor_t, fade_in)
    ep = grid.get('energy_phases', [])
    per_sec = []
    for p in ep:
        per_sec += [p['rms']] * (p['end'] - p['start'])
    med = float(np.median(per_sec)) if per_sec else 0.0
    dur = grid.get('duration', 0.0)
    best = None
    for d in dbs:
        off = d - anchor_t
        if film_len is not None and off + film_len > dur + 0.01:
            continue
        s0 = int(off)
        window = per_sec[s0:s0 + int(section_s)] if per_sec else []
        strength = float(np.mean(window)) if window else 0.0
        cand = {'offset': round(float(off), 3), 'downbeat': float(d), 'bed_rms': round(strength, 3), 'median_rms': round(med, 3)}
        if strength >= med:
            cand['reason'] = 'first downbeat on the anchor with a strong, clean entrance' + note
            return cand
        if best is None or strength > best['bed_rms']:
            best = cand
    if best:
        best['reason'] = 'no section reached the median level; strongest available entrance' + note
        return best
    return {'offset': 0.0, 'downbeat': None, 'reason': 'no downbeat leaves enough bed to cover the film: loop or pick a longer bed'}


def bed_end(grid: dict, last_word_t: float, bed_offset: float = 0.0, min_gap: float = 0.6, fade: float = 3.0) -> dict:
    """Finish the music on purpose: the first phrase boundary (or hard stop) on the film clock at least `min_gap`
    after the last word; the fade-out should COMPLETE there. Falls back to last_word + min_gap + fade."""
    marks = sorted(set(grid.get('phrases', [])) | set(float(s) for s in grid.get('hard_stops', [])))
    film_marks = [m - bed_offset for m in marks if m - bed_offset >= last_word_t + min_gap]
    if film_marks:
        end = film_marks[0]
        return {'fade_end': round(float(end), 3), 'fade_start': round(float(max(0.0, end - fade)), 3), 'reason': 'phrase boundary / hard stop'}
    end = last_word_t + min_gap + fade
    return {'fade_end': round(end, 3), 'fade_start': round(end - fade, 3), 'reason': 'no boundary found: timed tail'}


# ----------------------------------------------------------------------------------------------- bed edges
LOOP_XFADE_S = 0.6     # loop seam crossfade (HyperFrames joins generated beds with 0.3 s; 0.6 is kinder to a sustained pad)


def loop_plan(bed_dur: float, need_dur: float, xfade: float = LOOP_XFADE_S) -> tuple[int, str]:
    """How many copies of the bed and which filter_complex join them with crossfades instead of a hard seam
    (`-stream_loop -1` clicks or breaks a bar mid-sentence). Returns (copies, graph) where the graph expects the
    SAME file given `copies` times as inputs [0:a]..[n-1:a] and writes [bedloop]; copies == 1 → graph 'anull'.
    Verified: two 12 s inputs with d=0.3 → 23.7 s. Keep the total crossfade budget under the bed length."""
    if bed_dur <= 0:
        return 1, '[0:a]anull[bedloop]'
    copies = 1
    while bed_dur * copies - xfade * (copies - 1) < need_dur and copies < 64:
        copies += 1
    if copies == 1:
        return 1, '[0:a]anull[bedloop]'
    parts, prev = [], '[0:a]'
    for i in range(1, copies):
        out = '[bedloop]' if i == copies - 1 else '[_lp%d]' % i
        parts.append('%s[%d:a]acrossfade=d=%.2f:c1=tri:c2=tri%s' % (prev, i, xfade, out))
        prev = out
    return copies, ';'.join(parts)


def clamp_fades(fade_in: float, fade_out: float, span: float) -> tuple[float, float]:
    """If fade-in + fade-out exceed the bed span, scale both proportionally so they meet inside it."""
    total = fade_in + fade_out
    if total <= span or total <= 0:
        return fade_in, fade_out
    k = span / total
    return round(fade_in * k, 3), round(fade_out * k, 3)


# ----------------------------------------------------------------------------------------------- selftest
def _synth_drums(bpm: float = 100.0, dur: float = 30.0, sr: int = SR, phase_s: float = 0.3) -> np.ndarray:
    """Kick on beat 1 of every bar, snare on 2 and 4, hats on 8ths, with a 4-bar swell; starts at phase_s."""
    rng = np.random.default_rng(7)
    n = int(dur * sr)
    x = np.zeros(n)
    beat = 60.0 / bpm
    t_dec = np.arange(int(0.25 * sr)) / sr
    kick = np.sin(2 * np.pi * (55 * t_dec + (40 / 30) * (1 - np.exp(-t_dec * 30)))) * np.exp(-t_dec * 14) * 0.9   # 95 -> 55 Hz sweep
    snare = rng.standard_normal(t_dec.size) * np.exp(-t_dec * 25) * 0.35
    hat = rng.standard_normal(t_dec.size // 4) * np.exp(-np.arange(t_dec.size // 4) / sr * 80) * 0.12
    k = 0
    while True:
        t = phase_s + k * beat
        if t + 0.3 > dur:
            break
        i = int(t * sr)
        bar_pos = k % 4
        if bar_pos == 0:
            x[i:i + kick.size] += kick
        if bar_pos in (1, 3):
            x[i:i + snare.size] += snare
        x[i:i + hat.size] += hat
        h = int((t + beat / 2) * sr)
        if h + hat.size < n:
            x[h:h + hat.size] += hat * 0.6
        k += 1
    swell = 0.6 + 0.4 * (np.arange(n) / n)
    return (x * swell / np.abs(x).max() * 0.8).astype(np.float32)


def _synth_pad(dur: float = 30.0, sr: int = SR) -> np.ndarray:
    """A calm underscore: slow chord swell, no transients."""
    t = np.arange(int(dur * sr)) / sr
    x = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((110, 0.5), (165, 0.35), (220, 0.3), (277, 0.2)))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * t / 12.0 - np.pi / 2)
    return (x * env * 0.3).astype(np.float32)


def _write_wav(path: str, x: np.ndarray, sr: int = SR) -> str:
    raw = path + '.f32'
    open(raw, 'wb').write(x.astype(np.float32).tobytes())
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', raw, path], check=True)
    os.remove(raw)
    return path


def _selftest() -> int:
    import tempfile
    tmp = tempfile.mkdtemp(prefix='beats_')
    ok = True
    drums = _write_wav(os.path.join(tmp, 'drums.wav'), _synth_drums())
    g = analyse(drums)
    print('drums: bpm %s (onsets %s, autocorr %s) conf %s  beats %d  downbeats %d  phrases %d  rhythmic %s  offset %s'
          % (g['bpm'], g['bpm_onsets'], g['bpm_autocorr'], g['confidence'], len(g['beats']), len(g['downbeats']), len(g['phrases']), g['rhythmic'], g['offset']))
    ok &= g['bpm'] is not None and abs(g['bpm'] - 100) <= 2 and g['confidence'] == 'high' and g['rhythmic']
    # downbeats land on the kicks at 0.3 + 2.4·k
    db_err = max(min(abs(d - (0.3 + 2.4 * k)) for k in range(14)) for d in g['downbeats'])
    ok &= db_err <= 0.03
    print('       downbeat max error vs kicks %.3f s  first downbeats %s' % (db_err, g['downbeats'][:4]))
    # snap: a cue 80 ms off a beat snaps; one exactly between two beats (0.3 s from each at 100 BPM) stays put
    b1 = g['beats'][5]['t']
    ok &= snap(b1 + 0.08, g) == b1 and snap(b1 + 0.3, g) == b1 + 0.3
    print('       snap(%.3f+0.08) -> %.3f ; snap(+0.30) -> %.3f' % (b1, snap(b1 + 0.08, g), snap(b1 + 0.3, g)))
    # in-point: title word at 3.0 s on the film clock, film 20 s long
    ip = bed_in_point(g, anchor_t=3.0, film_len=20.0)
    ok &= ip['downbeat'] is not None and abs((ip['downbeat'] - ip['offset']) - 3.0) < 1e-6 and ip['offset'] + 20.0 <= g['duration']
    print('       in-point %s' % ip)
    be = bed_end(g, last_word_t=15.0, bed_offset=ip['offset'])
    ok &= be['fade_end'] >= 15.6 and be['reason'].startswith('phrase')
    print('       bed end %s' % be)
    pad = _write_wav(os.path.join(tmp, 'pad.wav'), _synth_pad())
    p = analyse(pad)
    print('pad:   bpm %s conf %s  onsets %d  beats %d  rhythmic %s  energy phases %s'
          % (p['bpm'], p['confidence'], len(p['onsets']), len(p['beats']), p['rhythmic'], [(e['level'], e['start'], e['end']) for e in p['energy_phases']][:6]))
    ok &= not p['rhythmic'] and snap(7.77, p) == 7.77
    ok &= any(e['level'] == 'HIGH' for e in p['energy_phases']) and any(e['level'] in ('VOID', 'LOW') for e in p['energy_phases'])
    # bed edges: a 30 s bed looped to cover 50 s with 0.6 s crossfades = 2 copies, 59.4 s; fades clamp proportionally
    copies, graph = loop_plan(30.0, 50.0)
    lp = os.path.join(tmp, 'loop.wav')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + ['-i', drums] * copies + ['-filter_complex', graph, '-map', '[bedloop]', lp], check=True)
    ld = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', lp], capture_output=True, text=True).stdout)
    ok &= copies == 2 and abs(ld - 59.4) < 0.05 and clamp_fades(1.5, 3.0, 3.0) == (1.0, 2.0) and clamp_fades(1.5, 3.0, 90.0) == (1.5, 3.0)
    print('loop:  %d copies -> %.2f s (expect 59.4)  clamp_fades(1.5, 3.0, span 3.0) -> %s' % (copies, ld, clamp_fades(1.5, 3.0, 3.0)))
    out = os.path.join(tmp, 'beats.json')
    json.dump(g, open(out, 'w'), indent=1)
    ok &= os.path.getsize(out) > 500
    print('SELFTEST %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='bed → beats.json (BPM, downbeats, phrases, energy) + bed in-point', formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('bed', nargs='?')
    ap.add_argument('--out', help='write beats json here (default: print a summary only)')
    ap.add_argument('--anchor', type=float, help='film-clock time a downbeat should land on (e.g. the title word)')
    ap.add_argument('--film-len', type=float, help='film length incl. tail, to keep the in-point inside the bed')
    ap.add_argument('--fade-in', type=float, default=1.5)
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.bed:
        ap.error('bed path required (or --selftest)')
    g = analyse(a.bed)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump(g, open(a.out, 'w', encoding='utf-8'), indent=1)
    print('%s  %.1f s  bpm %s (%s)  beats %d  downbeats %d  phrases %d  rhythmic %s' % (
        g['source'], g['duration'], g['bpm'], g['confidence'], len(g['beats']), len(g['downbeats']), len(g['phrases']), g['rhythmic']))
    print('energy: ' + ' '.join('%s[%d-%d]' % (e['level'], e['start'], e['end']) for e in g['energy_phases'][:12]))
    if g['hard_stops']:
        print('hard stops at %s s' % g['hard_stops'])
    if not g['rhythmic']:
        print('TRUST RULE: not rhythmic - pace by phrases/energy, snap() is a no-op, do not hard-cut to the grid')
    if a.anchor is not None:
        print('in-point: %s' % bed_in_point(g, a.anchor, a.fade_in, a.film_len))
    return 0


if __name__ == '__main__':
    sys.exit(main())
