# -*- coding: utf-8 -*-
"""sfx_synth.py — synthesize the film's sound-effect set from first principles (numpy, 48 kHz, seeded).

    python audio/sfx_synth.py --out audio/sfx                       # writes <name>.wav + manifest.json
    python audio/sfx_synth.py --out audio/sfx --riser 3.0 --seed 11 # a 3 s riser, another noise seed
    python audio/sfx_synth.py --list                                 # names, durations, uses (JSON)
    python audio/sfx_synth.py --selftest

No sample packs. Every effect is a short physical model written as a function of time, so two runs with the
same seed produce byte-identical WAVs (the manifest carries each file's md5). Peaks are normalised to −6 dBFS
(0.5012 linear) so the placer's bus gain is the only level decision (see sfx_place.py).

The eight sounds and how they are made
  whoosh       0.35 s of white noise through a resonant band-pass whose centre sweeps 400 → 4000 Hz
               exponentially (Q 4: narrow enough that the sweep is a visible ridge on a spectrogram) under a
               Hann window. The ear hears the sweep as motion; the Hann puts the
               loudest moment exactly at 0.175 s, which is where the placer aligns a cut (manifest `align`).
  tick         a 2 ms half-sine impulse followed by a 1.2 kHz resonance decaying with τ = 6 ms (−60 dB in
               41 ms). The count-up landing sound: short enough to sit between two words.
  snap         an impact: a sine that drops from 180 Hz to 60 Hz over 60 ms (pitch drop = perceived "hit")
               with τ = 70 ms decay, plus a 40 ms band-passed (2–6 kHz) noise burst for the crack. 0.25 s.
  impact-low   a sub thump at 45 Hz with a 0.5 s exponential decay (τ = 0.12 s → −36 dB at 0.5 s, then a 20 ms
               fade to zero) plus a 5 ms transient click so it reads on small speakers that cannot play 45 Hz.
  riser        N seconds (default 2.0) of noise through a band-pass rising 400 → 6000 Hz with an exponential
               swell from −30 dB to 0 dB (the loudness ramp is what builds tension; the pitch ramp tells the
               ear where the end is), cut dead at N with a 10 ms fade. `align` = N: the END lands on the cue.
  shimmer      six partials 2–6 kHz (2000·2^(k/5)), each as a detuned pair (±0.35 %) so they beat slowly;
               5 ms attack, exponential decay τ = 0.28 s, 0.8 s total. A "data arrived" glow.
  ui-confirm   two sines, 880 Hz then 1320 Hz (a perfect fifth), 60 ms each with 5 ms raised-cosine edges —
               0.12 s. The receipt-stamp / answer-landed sound.
  key-0..key-5 typewriter keys: a 1.5 ms noise impulse band-passed around a per-key centre drawn from
               2.2–4.8 kHz, a tiny 300 Hz body (τ 8 ms) and a per-key level ±1.5 dB, all from MOTION-style
               seeded draws (numpy default_rng(seed + k)); 30 ms each. Six variants so a typed line never
               sounds like one sample repeated.

Filters: a Chamberlin state-variable filter stepped per sample (f = 2·sin(π·fc/sr)) — its state is the
physical low-pass/band-pass signal, so a sweeping centre frequency never clicks (a biquad with carried
state does). Static band-passes use scipy.signal.butter sos. Everything is float64 inside, 24-bit PCM out.

manifest.json: {"sr":48000, "peak_dbfs":-6, "seed":7, "sfx":[{"name","file","dur","peak_dbfs","align","use","md5"}]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
from typing import Callable

import numpy as np
from scipy import signal

SR = 48000
PEAK_DBFS = -6.0
DEFAULT_SEED = 7
RISER_DEFAULT_S = 2.0
N_KEYS = 6

USE = {
    'whoosh': 'seam cuts and camera moves (peak at 0.175 s lands on the cut)',
    'tick': 'count-up land, keystroke send, small UI commit',
    'snap': 'flash, cut-with-cause (click / chapter)',
    'impact-low': 'act open, chapter, big reveal — at most one per act',
    'riser': 'run-in to the climax cue; its END lands on the cue',
    'shimmer': 'data arrives, reveal glow, result highlight',
    'ui-confirm': 'receipt stamp, answer landed, confirmation toast',
    'key': 'typewriter key (six seeded variants, rotate per keystroke)',
}


# ----------------------------------------------------------------------------------------------- primitives
def _t(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR


def hann(n: int) -> np.ndarray:
    """Periodic-free symmetric Hann: 0 at both ends, 1 in the middle."""
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / max(1, n - 1))


def raised_cosine_edges(n: int, edge_s: float) -> np.ndarray:
    """Unity window with raised-cosine fades of `edge_s` at both ends (clicks are what untreated edges make)."""
    e = int(round(edge_s * SR))
    w = np.ones(n)
    if e > 0 and n >= 2 * e:
        r = 0.5 - 0.5 * np.cos(np.pi * np.arange(e) / e)
        w[:e] = r
        w[-e:] = r[::-1]
    return w


def svf_bandpass(x: np.ndarray, fc: np.ndarray | float, q: float) -> np.ndarray:
    """Chamberlin state-variable band-pass, per-sample centre `fc` (Hz, scalar or array). Oversampled ×2 for
    stability above sr/6 (6 kHz needs it at 48 kHz)."""
    fc = np.broadcast_to(np.asarray(fc, dtype=np.float64), x.shape)
    f = 2.0 * np.sin(np.pi * np.minimum(fc, SR * 0.45) / (2 * SR))          # ×2 oversampled step
    qq = 1.0 / max(q, 0.5)
    low = band = 0.0
    out = np.empty_like(x)
    for i in range(x.size):
        xi, fi = x[i], f[i]
        for _ in range(2):                                              # two half-steps per sample
            low += fi * band
            high = xi - low - qq * band
            band += fi * high
        out[i] = band
    return out


def butter_bp(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, [lo, hi], btype='bandpass', fs=SR, output='sos')
    return signal.sosfilt(sos, x)


def normalise(x: np.ndarray, peak_dbfs: float = PEAK_DBFS) -> np.ndarray:
    p = float(np.max(np.abs(x))) or 1.0
    return x * (10 ** (peak_dbfs / 20.0) / p)


def exp_sweep(n: int, f0: float, f1: float) -> np.ndarray:
    """Per-sample frequency moving exponentially f0 -> f1 over n samples (equal time per octave)."""
    return f0 * (f1 / f0) ** (np.arange(n) / max(1, n - 1))


# ----------------------------------------------------------------------------------------------- the sounds
def whoosh(rng: np.random.Generator, dur: float = 0.35, f0: float = 400.0, f1: float = 4000.0, q: float = 4.0) -> np.ndarray:
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    return normalise(svf_bandpass(noise, exp_sweep(n, f0, f1), q) * hann(n))


def tick(rng: np.random.Generator, dur: float = 0.045, f_res: float = 1200.0, tau: float = 0.006) -> np.ndarray:
    n = int(dur * SR); t = _t(n)
    imp = np.zeros(n); m = int(0.002 * SR)
    imp[:m] = np.sin(np.pi * np.arange(m) / m)                           # 2 ms half-sine impulse
    res = np.sin(2 * np.pi * f_res * t) * np.exp(-t / tau)
    return normalise((imp + 0.8 * res) * raised_cosine_edges(n, 0.001))


def snap(rng: np.random.Generator, dur: float = 0.25) -> np.ndarray:
    n = int(dur * SR); t = _t(n)
    f = 60.0 + 120.0 * np.exp(-t / 0.02)                                 # 180 -> 60 Hz, ~60 ms
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-t / 0.07)
    nb = int(0.04 * SR)
    burst = np.zeros(n)
    burst[:nb] = butter_bp(rng.standard_normal(nb), 2000, 6000) * np.exp(-np.arange(nb) / (0.012 * SR))
    return normalise((body + 0.9 * burst) * raised_cosine_edges(n, 0.002))


def impact_low(rng: np.random.Generator, dur: float = 0.6, f: float = 45.0, tau: float = 0.12) -> np.ndarray:
    n = int(dur * SR); t = _t(n)
    sub = np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    sub[t > 0.5] *= np.clip(1 - (t[t > 0.5] - 0.5) / 0.02, 0, 1)         # dead by 0.52 s
    m = int(0.005 * SR)
    click = np.zeros(n); click[:m] = butter_bp(rng.standard_normal(m), 800, 3000) * np.linspace(1, 0, m)
    return normalise((sub + 0.35 * click) * raised_cosine_edges(n, 0.002))


def riser(rng: np.random.Generator, dur: float = RISER_DEFAULT_S, f0: float = 400.0, f1: float = 6000.0, swell_db: float = -30.0) -> np.ndarray:
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    bp = svf_bandpass(noise, exp_sweep(n, f0, f1), 2.5)
    swell = 10 ** (swell_db * (1 - np.arange(n) / max(1, n - 1)) / 20.0)   # -30 dB -> 0 dB exponentially
    out = bp * swell
    e = int(0.010 * SR); out[-e:] *= np.linspace(1, 0, e)                # dead at exactly `dur`
    out[:e] *= np.linspace(0, 1, e)
    return normalise(out)


def shimmer(rng: np.random.Generator, dur: float = 0.8, tau: float = 0.28) -> np.ndarray:
    n = int(dur * SR); t = _t(n)
    out = np.zeros(n)
    for k in range(6):
        fk = 2000.0 * 2 ** (k / 5.0)
        for d in (-0.0035, 0.0035):
            out += np.sin(2 * np.pi * fk * (1 + d) * t + k) * np.exp(-t / tau) / (1 + 0.35 * k)
    env = np.minimum(1.0, t / 0.005)
    return normalise(out * env * raised_cosine_edges(n, 0.004))


def ui_confirm(rng: np.random.Generator, f_a: float = 880.0, f_b: float = 1320.0, each: float = 0.06) -> np.ndarray:
    m = int(each * SR); t = _t(m)
    tone = lambda f: np.sin(2 * np.pi * f * t) * raised_cosine_edges(m, 0.005)
    return normalise(np.concatenate([tone(f_a), tone(f_b)]))


def key(rng: np.random.Generator, dur: float = 0.03) -> np.ndarray:
    n = int(dur * SR); t = _t(n)
    fc = rng.uniform(2200.0, 4800.0)
    lvl = 10 ** (rng.uniform(-1.5, 1.5) / 20.0)
    m = int(0.0015 * SR)
    imp = np.zeros(n); imp[:m] = rng.standard_normal(m)
    click = butter_bp(imp, fc * 0.7, min(fc * 1.4, 0.45 * SR))
    body = np.sin(2 * np.pi * 300.0 * t) * np.exp(-t / 0.008) * 0.4
    return normalise((click + body) * raised_cosine_edges(n, 0.001)) * lvl


def synth_set(seed: int = DEFAULT_SEED, riser_s: float = RISER_DEFAULT_S) -> dict[str, tuple[np.ndarray, float, str]]:
    """{name: (samples, align_s, use)} in a fixed order. Each sound draws from its own rng(seed + index) so a
    change to one recipe does not alter the others."""
    rng = lambda i: np.random.default_rng(seed + i)
    out = {
        'whoosh': (whoosh(rng(1)), 0.175, USE['whoosh']),
        'tick': (tick(rng(2)), 0.0, USE['tick']),
        'snap': (snap(rng(3)), 0.0, USE['snap']),
        'impact-low': (impact_low(rng(4)), 0.0, USE['impact-low']),
        'riser': (riser(rng(5), riser_s), riser_s, USE['riser']),
        'shimmer': (shimmer(rng(6)), 0.0, USE['shimmer']),
        'ui-confirm': (ui_confirm(rng(7)), 0.0, USE['ui-confirm']),
    }
    for k in range(N_KEYS):
        out['key-%d' % k] = (key(rng(10 + k)), 0.0, USE['key'])
    return out


# ----------------------------------------------------------------------------------------------- WAV i/o
def write_wav(path: str, x: np.ndarray, sr: int = SR, bits: int = 24) -> None:
    """Write mono (1-D) or stereo (N×2) float samples as PCM WAV. bits 16/24 (clipped) or 32 (IEEE float)."""
    x = np.asarray(x, dtype=np.float64)
    ch = 1 if x.ndim == 1 else x.shape[1]
    frames = x.reshape(-1, ch)
    if bits == 32:
        data = frames.astype('<f4').tobytes(); fmt = 3
    elif bits == 16:
        data = np.round(np.clip(frames, -1, 1) * 32767).astype('<i2').tobytes(); fmt = 1
    else:
        i = np.round(np.clip(frames, -1, 1) * 8388607).astype('<i4').reshape(-1, 1).view(np.uint8).reshape(-1, 4)[:, :3]
        data = i.tobytes(); fmt = 1
    bps = bits // 8
    hdr = b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE' + b'fmt ' + struct.pack('<IHHIIHH', 16, fmt, ch, sr, sr * ch * bps, ch * bps, bits)
    with open(path, 'wb') as f:
        f.write(hdr + b'data' + struct.pack('<I', len(data)) + data)


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """Read the PCM/float WAVs this module writes (and plain 16/24/32-bit RIFF files). Returns (N×ch float64, sr)."""
    b = open(path, 'rb').read()
    pos = 12; fmt = None; data = None
    while pos + 8 <= len(b):
        cid, sz = b[pos:pos + 4], struct.unpack('<I', b[pos + 4:pos + 8])[0]
        body = b[pos + 8:pos + 8 + sz]
        if cid == b'fmt ':
            fmt = struct.unpack('<HHIIHH', body[:16])
        elif cid == b'data':
            data = body
        pos += 8 + sz + (sz & 1)
    if fmt is None or data is None:
        raise ValueError('not a PCM WAV: %s' % path)
    tag, ch, sr, _, _, bits = fmt
    if tag == 3 or bits == 32 and tag != 1:
        x = np.frombuffer(data, dtype='<f4').astype(np.float64)
    elif bits == 16:
        x = np.frombuffer(data, dtype='<i2').astype(np.float64) / 32768.0
    elif bits == 24:
        u = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3)
        i = (u[:, 0].astype(np.int32) | (u[:, 1].astype(np.int32) << 8) | (u[:, 2].astype(np.int32) << 16))
        i = np.where(i >= 1 << 23, i - (1 << 24), i)
        x = i.astype(np.float64) / 8388608.0
    elif bits == 32:
        x = np.frombuffer(data, dtype='<i4').astype(np.float64) / 2147483648.0
    else:
        raise ValueError('unsupported WAV bit depth %d' % bits)
    return x.reshape(-1, ch), sr


def md5_of(path: str) -> str:
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


def dbfs(x: np.ndarray) -> float:
    p = float(np.max(np.abs(x)))
    return 20 * math.log10(p) if p > 0 else -120.0


# ----------------------------------------------------------------------------------------------- build
def build(out_dir: str, seed: int = DEFAULT_SEED, riser_s: float = RISER_DEFAULT_S, peak_dbfs: float = PEAK_DBFS) -> dict:
    """Synthesize the set into out_dir/<name>.wav and out_dir/manifest.json; returns the manifest."""
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for name, (x, align, use) in synth_set(seed, riser_s).items():
        x = x if name.startswith('key') else normalise(x, peak_dbfs)   # keys keep their ±1.5 dB spread
        p = os.path.join(out_dir, name + '.wav')
        write_wav(p, x)
        rows.append({'name': name, 'file': name + '.wav', 'dur': round(x.size / SR, 4), 'peak_dbfs': round(dbfs(x), 2),
                     'align': round(align, 4), 'use': use, 'md5': md5_of(p)})
    man = {'sr': SR, 'peak_dbfs': peak_dbfs, 'seed': seed, 'riser_s': riser_s, 'sfx': rows}
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1)
    return man


# ----------------------------------------------------------------------------------------------- selftest
def selftest() -> int:
    import tempfile, time
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix='sfx_synth_')
    a = build(os.path.join(tmp, 'a')); b = build(os.path.join(tmp, 'b'))
    fails = []
    for ra, rb in zip(a['sfx'], b['sfx']):
        if ra['md5'] != rb['md5']:
            fails.append('non-deterministic: %s' % ra['name'])
        if not ra['name'].startswith('key') and abs(ra['peak_dbfs'] - PEAK_DBFS) > 0.05:
            fails.append('%s peak %.2f dBFS (want %.1f)' % (ra['name'], ra['peak_dbfs'], PEAK_DBFS))
    by = {r['name']: r for r in a['sfx']}
    # whoosh: loudest 10 ms sits at the Hann peak; riser: loudest at the end; ui-confirm second half is higher pitched
    w, _ = read_wav(os.path.join(tmp, 'a', 'whoosh.wav')); w = w[:, 0]
    env = np.convolve(w ** 2, np.ones(480) / 480, 'same'); tpk = int(np.argmax(env)) / SR
    if abs(tpk - 0.175) > 0.04:
        fails.append('whoosh peak at %.3f s (want 0.175)' % tpk)
    r, _ = read_wav(os.path.join(tmp, 'a', 'riser.wav')); r = r[:, 0]
    if np.sqrt(np.mean(r[-4800:-480] ** 2)) < 4 * np.sqrt(np.mean(r[:4800] ** 2)):
        fails.append('riser does not swell')
    if abs(r[-1]) > 1e-3 or abs(by['riser']['dur'] - RISER_DEFAULT_S) > 1e-3:
        fails.append('riser does not end dead at %.1f s' % RISER_DEFAULT_S)
    u, _ = read_wav(os.path.join(tmp, 'a', 'ui-confirm.wav')); u = u[:, 0]; h = u.size // 2
    za = np.mean(np.abs(np.diff(np.sign(u[:h])))) ; zb = np.mean(np.abs(np.diff(np.sign(u[h:]))))
    if not zb > za * 1.3:
        fails.append('ui-confirm second tone is not higher')
    keys = [by['key-%d' % k]['md5'] for k in range(N_KEYS)]
    if len(set(keys)) != N_KEYS:
        fails.append('typewriter keys are not distinct')
    print('sfx_synth selftest: %d sounds, %.1f s, %s' % (len(a['sfx']), time.time() - t0, 'OK' if not fails else '; '.join(fails)))
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='synthesize the film SFX set (numpy, 48 kHz, seeded, peak -6 dBFS)')
    ap.add_argument('--out', help='output directory (writes <name>.wav + manifest.json)')
    ap.add_argument('--seed', type=int, default=DEFAULT_SEED)
    ap.add_argument('--riser', type=float, default=RISER_DEFAULT_S, help='riser length in seconds (its end lands on the climax cue)')
    ap.add_argument('--peak', type=float, default=PEAK_DBFS, help='peak normalisation in dBFS')
    ap.add_argument('--list', action='store_true', help='print the set as JSON without writing files')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.list:
        rows = [{'name': n, 'dur': round(x.size / SR, 4), 'align': al, 'use': u} for n, (x, al, u) in synth_set(a.seed, a.riser).items()]
        print(json.dumps(rows, indent=1)); return 0
    if not a.out:
        ap.print_help(); return 2
    man = build(a.out, a.seed, a.riser, a.peak)
    print(json.dumps({'out': a.out, 'count': len(man['sfx']), 'manifest': os.path.join(a.out, 'manifest.json')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
