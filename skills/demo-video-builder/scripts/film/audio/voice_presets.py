# -*- coding: utf-8 -*-
"""voice_presets.py — ffmpeg chains for the TTS cast, plus per-phase level matching.

    python audio/voice_presets.py clean                         # prints the chain
    python audio/voice_presets.py broadcast --evenness 0.5 --deess --job add_clarity
    python audio/voice_presets.py --list
    python audio/voice_presets.py --level-match vo film          # per-phase LUFS → gains to a common target
    python audio/voice_presets.py --selftest

Presets (always in the order  subtractive EQ → dynamics → tone → character → ceiling):
  clean      HP 80 Hz 12 dB/oct → 250 Hz −3 dB Q1.2 → comp −20 dB 3:1 12/180 ms +3 → 3 kHz +2.5 Q1 → limiter −1 dBFS
  broadcast  HP 90 → 400 Hz −3 Q1.4 → comp −24 4:1 8/150 +5 → 2.5 kHz +3 Q0.9 → highshelf 8 kHz +2 → tanh −12 → limiter −1
  warm       HP 70 → lowshelf 180 Hz +2 → comp −18 2.5:1 20/250 +2 → 3 kHz +1.5 Q0.8 → limiter −1.5
  telephone  HP 300 ×2 + LP 3400 ×2 (24 dB/oct), 1200 Hz +6 Q1.2 honk, 550 Hz −4 Q1, tanh drive, −2 dB out
  pa         HP 250 ×2, LP 5000 ×2, 2400 Hz +9 Q2, tanh −10, short echo instead of a room (ffmpeg has no IR reverb)
  intercom   gate −40 dB / range −30, HP 500 ×2, LP 3000 ×2, 2000 Hz +6 Q2, 11-bit crush mix 0.3
  radio      HP 220, LP 2200, 1200 Hz −5 Q0.9 (IF droop), lowshelf 500 +4, tanh −8/−1, 8-bit crush mix 0.45
Costumes (telephone / pa / intercom / radio) carry a measured `trim_db` so a costumed line lands within ~1 dB
of the untreated voice (measured once on the synthetic −20 LUFS voice with --calibrate: telephone +4.4, pa +8.2,
intercom +1.2, radio +2.1 dB). The non-costume presets are NOT trimmed: `clean` lifts a −20 LUFS stem about +5.6 dB
(makeup + compression), `warm` +4.5, `broadcast` +0.8 — the two-pass master absorbs it; use threshold='auto' in
carve_bed so the sidechain key follows the new level. Never stack two costumes; keep
them on lines ≤ 3 s and never on the voice that explains the product.

Jobs (one-band fixes, never stacked on a preset that already contains the same band — that is −6 where −3 was
meant): tame_boominess 200 Hz −4 Q1.4 · reduce_mud 250 Hz −3 Q1.2 · reduce_boxiness 400 Hz −3 Q1.4 ·
add_clarity 3 kHz +2.5 Q1 · soften_harshness 3.2 kHz −3 Q1.6.

Evenness knob 0..1 (replaces the preset compressor): threshold −12 − 18·s dB, ratio 2 + 4·s, attack 25 − 20·s ms,
release 300 − 210·s ms, makeup 9.5·s² dB (level-matched; a linear 1/3/7 dB left the track −2.5 dB at full).
De-ess: ffmpeg has a real `deesser` (i=0.3 m=0.5 f=0.5), inserted right after the compressor.

Rules for TTS: neural voices are already clean and compressed — apply at most `clean`, once, to the assembled
bus (vo_<name>.mp3) after pads/pauses are in, never per phrase (per-phrase loudnorm pumps).

Per-phase level match (static, TTS-friendly version of a leveller): measure each vo/<name>_<phase>.mp3 with
ebur128/loudnorm, compute one `volume=<delta>dB` so every phase lands at a common target (−20 LUFS stem
default). Phrases under 3 s under-read on integrated LUFS, so they are measured as speaking-window RMS
(400 ms windows within 42 dB of the peak) and re-based onto LUFS with the offset observed on the long phrases.
Not a dynamic leveller: a 5–6 dB prosody decline across a sentence is the voice, not a defect.

Band vocabulary: Rumble 20–80 · Weight 80–250 · Mud 250–600 · Middle 600–2k · Presence 2–5k · Edge 5–10k · Air 10–20k.
Order rule: subtract before you add, level after you filter, relationships (duck/carve) after level, ceiling last.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from typing import Sequence

import numpy as np

LUFS_TARGET_STEM = -20.0           # per-phase stem target (the master lifts the whole mix later)
SHORT_PHRASE_S = 3.0               # under this, integrated LUFS under-reads → speaking-window RMS
WINDOW_S, RMS_FLOOR_DB = 0.4, 42.0 # speaking windows: 400 ms, within 42 dB of the peak
SPREAD_WINDOW_S = 1.2              # prosody spread window (4–6 dB normal, ≥ 12 dB defect)
_LIM = lambda db: 'alimiter=limit=%.3f:attack=5:release=50:level=false' % (10 ** (db / 20.0))   # limit is LINEAR


def _eq(f, g, q):
    return 'equalizer=f=%d:width_type=q:w=%.1f:g=%s' % (f, q, ('%+.1f' % g).replace('+', ''))


def _comp(thr, ratio, att, rel, makeup):
    return 'acompressor=threshold=%ddB:ratio=%s:attack=%s:release=%s:makeup=%s' % (thr, ratio, att, rel, makeup)


# Each preset is five ordered stages; stages are lists of ffmpeg nodes. (type, f, g) tuples under 'eq_bands' let
# the job-collision check see which bands a preset already touches.
PRESETS: dict[str, dict] = {
    'clean': {
        'sub': ['highpass=f=80:poles=2', _eq(250, -3, 1.2)],
        'dyn': [_comp(-20, 3, 12, 180, 3)],
        'tone': [_eq(3000, 2.5, 1)],
        'char': [],
        'ceil': [_LIM(-1)],
        'eq_bands': [(250, -3), (3000, 2.5)], 'costume': False, 'trim_db': 0.0,
        'use': 'the bus default: evens the cast, consonant presence for a loud booth'},
    'broadcast': {
        'sub': ['highpass=f=90:poles=2', _eq(400, -3, 1.4)],
        'dyn': [_comp(-24, 4, 8, 150, 5)],
        'tone': [_eq(2500, 3, 0.9), 'highshelf=f=8000:g=2'],
        'char': ['asoftclip=type=tanh:threshold=0.251'],          # −12 dBFS
        'ceil': [_LIM(-1)],
        'eq_bands': [(400, -3), (2500, 3), (8000, 2)], 'costume': False, 'trim_db': 0.0,
        'use': 'denser, brighter announcer read; only when the bed is thick'},
    'warm': {
        'sub': ['highpass=f=70:poles=2'],
        'dyn': [_comp(-18, 2.5, 20, 250, 2)],
        'tone': ['lowshelf=f=180:g=2', _eq(3000, 1.5, 0.8)],
        'char': [],
        'ceil': [_LIM(-1.5)],
        'eq_bands': [(180, 2), (3000, 1.5)], 'costume': False, 'trim_db': 0.0,
        'use': 'softer narrator for a calm, dark-palette film'},
    'telephone': {
        'sub': ['highpass=f=300:poles=2', 'highpass=f=300:poles=2', 'lowpass=f=3400:poles=2', 'lowpass=f=3400:poles=2'],
        'dyn': [],
        'tone': [_eq(1200, 6, 1.2), _eq(550, -4, 1)],
        'char': ['asoftclip=type=tanh:threshold=0.355', 'volume=-2dB'],   # drive −9 dBFS, out −2
        'ceil': [],
        'eq_bands': [(1200, 6), (550, -4)], 'costume': True, 'trim_db': 4.4,
        'use': 'a caller; one or two vivid lines'},
    'pa': {
        'sub': ['highpass=f=250:poles=2', 'highpass=f=250:poles=2', 'lowpass=f=5000:poles=2', 'lowpass=f=5000:poles=2'],
        'dyn': [],
        'tone': [_eq(2400, 9, 2)],
        'char': ['asoftclip=type=tanh:threshold=0.316', 'aecho=0.8:0.6:40|70:0.25|0.18', 'volume=-1dB'],  # drive −10, concourse
        'ceil': [],
        'eq_bands': [(2400, 9)], 'costume': True, 'trim_db': 8.2,
        'use': 'an announcement in a concourse'},
    'intercom': {
        'sub': ['agate=threshold=0.01:range=0.0316:attack=1:release=120',                   # −40 dB, range −30
                'highpass=f=500:poles=2', 'highpass=f=500:poles=2', 'lowpass=f=3000:poles=2', 'lowpass=f=3000:poles=2'],
        'dyn': [],
        'tone': [_eq(2000, 6, 2)],
        'char': ['acrusher=bits=11:mix=0.3'],
        'ceil': [],
        'eq_bands': [(2000, 6)], 'costume': True, 'trim_db': 1.2,
        'use': 'a dispatcher / door intercom'},
    'radio': {
        'sub': ['highpass=f=220:poles=2', 'lowpass=f=2200:poles=2', _eq(1200, -5, 0.9)],
        'dyn': [],
        'tone': ['lowshelf=f=500:g=4'],
        'char': ['asoftclip=type=tanh:threshold=0.398', 'volume=-1dB', 'acrusher=bits=8:mix=0.45'],    # drive −8, out −1
        'ceil': [],
        'eq_bands': [(1200, -5), (500, 4)], 'costume': True, 'trim_db': 2.1,
        'use': 'AM / handheld radio (replaces the old 320–3300 Hz radioize)'},
}

JOBS: dict[str, tuple[int, float, float]] = {           # name: (Hz, dB, Q)
    'tame_boominess': (200, -4, 1.4),
    'reduce_mud': (250, -3, 1.2),
    'reduce_boxiness': (400, -3, 1.4),
    'add_clarity': (3000, 2.5, 1.0),
    'soften_harshness': (3200, -3, 1.6),
}

DEESSER = 'deesser=i=0.3:m=0.5:f=0.5'


def evenness_compressor(s: float) -> str:
    """One-knob compressor (0 = barely there, 1 = broadcast-dense), level-matched by the makeup curve."""
    s = min(1.0, max(0.0, float(s)))
    return 'acompressor=threshold=%.1fdB:ratio=%.2f:attack=%.1f:release=%.0f:makeup=%.2f' % (
        -12 - 18 * s, 2 + 4 * s, 25 - 20 * s, 300 - 210 * s, 9.5 * s * s)


def _collides(preset: dict, job: tuple[int, float, float]) -> bool:
    """A job collides when the preset already moves a band within a third octave of it in the same direction."""
    f, g, _ = job
    return any(abs(math.log2(pf / f)) <= 1 / 3 and (pg < 0) == (g < 0) for pf, pg in preset['eq_bands'])


def preset_chain(name: str, evenness: float | None = None, deess: bool = False, jobs: Sequence[str] = (),
                 trim: bool = True) -> str:
    """ffmpeg -af chain for a preset.  evenness replaces the preset compressor (or adds one to a costume);
    deess inserts the deesser after dynamics; jobs add one-band fixes (ValueError on a collision — never stack
    a job on a preset that already contains it); trim applies the costume's measured level trim."""
    if name not in PRESETS:
        raise KeyError('unknown preset %r (have %s)' % (name, ', '.join(PRESETS)))
    p = PRESETS[name]
    sub, dyn, tone, char, ceil = (list(p[k]) for k in ('sub', 'dyn', 'tone', 'char', 'ceil'))
    for j in jobs:
        if j not in JOBS:
            raise KeyError('unknown job %r (have %s)' % (j, ', '.join(JOBS)))
        if _collides(p, JOBS[j]):
            raise ValueError('job %s stacks on a band preset %s already moves (would double the cut/boost)' % (j, name))
        f, g, q = JOBS[j]
        (sub if g < 0 else tone).append(_eq(f, g, q))
    if evenness is not None:
        dyn = [evenness_compressor(evenness)]
    if deess:
        dyn.append(DEESSER)
    if trim and p['costume'] and abs(p['trim_db']) >= 0.05:
        char.append('volume=%.1fdB' % p['trim_db'])
    return ','.join(sub + dyn + tone + char + ceil)


# ----------------------------------------------------------------------------------------------- measurement
def measure_lufs(path: str) -> dict:
    """Integrated loudness / true peak / LRA of a file via loudnorm's measurement pass (what the master uses)."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json',
                        '-f', 'null', '-'], capture_output=True, text=True)
    m = re.findall(r'\{[^{}]*"input_i"[\s\S]*?\}', r.stderr)
    if not m:
        raise RuntimeError('loudnorm measurement failed for %s' % path)
    d = json.loads(m[-1])
    return {'lufs': float(d['input_i']), 'tp': float(d['input_tp']), 'lra': float(d['input_lra'])}


def _decode(path: str, sr: int = 48000) -> np.ndarray:
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace')[-300:])
    return np.frombuffer(r.stdout, dtype=np.float32)


def window_db(x: np.ndarray, sr: int = 48000, win_s: float = WINDOW_S) -> np.ndarray:
    """RMS in dBFS per non-overlapping window."""
    n = int(sr * win_s)
    k = x.size // n
    if k == 0:
        return np.array([20 * math.log10(max(1e-9, float(np.sqrt((x.astype(np.float64) ** 2).mean()))))]) if x.size else np.array([])
    rms = np.sqrt((x[:k * n].reshape(k, n).astype(np.float64) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def speaking_rms_db(path: str) -> dict:
    """Mean RMS (dBFS) of the speaking windows (within 42 dB of the loudest window) plus the 1.2 s spread —
    plain RMS, not LUFS. Returns {'rms_db', 'spread_db', 'dur'}."""
    x = _decode(path)
    w = window_db(x)
    if w.size == 0:
        return {'rms_db': float('-inf'), 'spread_db': 0.0, 'dur': 0.0}
    speaking = w[w > w.max() - RMS_FLOOR_DB]
    w12 = window_db(x, win_s=SPREAD_WINDOW_S)
    sp = w12[w12 > w12.max() - RMS_FLOOR_DB] if w12.size else w12
    return {'rms_db': float(speaking.mean()), 'spread_db': float(sp.max() - sp.min()) if sp.size > 1 else 0.0,
            'dur': x.size / 48000.0}


def level_match(paths: Sequence[str], target_lufs: float = LUFS_TARGET_STEM, short_s: float = SHORT_PHRASE_S) -> list[dict]:
    """Per-phase gains to land every phrase at `target_lufs`. Long phrases: integrated LUFS. Short phrases: speaking
    RMS re-based with the LUFS−RMS offset observed on the long ones (RMS as-is when there are no long phrases).
    Returns [{'path', 'dur', 'method', 'measured', 'gain_db', 'spread_db'}] in input order."""
    rows = []
    for p in paths:
        r = speaking_rms_db(p)
        row = {'path': p, 'dur': round(r['dur'], 2), 'spread_db': round(r['spread_db'], 1), 'rms_db': r['rms_db']}
        if r['dur'] >= short_s:
            row.update(method='lufs', measured=measure_lufs(p)['lufs'])
        rows.append(row)
    long_rows = [r for r in rows if r.get('method') == 'lufs']
    offset = float(np.median([r['measured'] - r['rms_db'] for r in long_rows])) if long_rows else 0.0
    for r in rows:
        if r.get('method') != 'lufs':
            r.update(method='rms+%.1f' % offset if long_rows else 'rms', measured=r['rms_db'] + offset)
        r['measured'] = round(r['measured'], 2)
        r['gain_db'] = round(target_lufs - r['measured'], 2)
        r.pop('rms_db', None)
    return rows


def phase_gains(vo_dir: str, name: str, target_lufs: float = LUFS_TARGET_STEM) -> dict[str, dict]:
    """level_match() over vo/<name>_<phase>.mp3 in phases.json order → {phase: row}."""
    ph = json.load(open(os.path.join(vo_dir, name + '_phases.json'), encoding='utf-8'))['phases']
    paths = [os.path.join(vo_dir, '%s_%s.mp3' % (name, p['name'])) for p in ph]
    return {p['name']: r for p, r in zip(ph, level_match(paths, target_lufs))}


def gain_chain(delta_db: float) -> str:
    """The single static gain a phase gets (snap moves under 0.4 dB to nothing, cap lift/cut at 12 dB)."""
    d = max(-12.0, min(12.0, delta_db))
    return 'anull' if abs(d) < 0.4 else 'volume=%.2fdB' % d


# ----------------------------------------------------------------------------------------------- calibration / selftest
def _synth_voice_wav(path: str, sr: int = 48000, dur: float = 5.0, level_db: float = -20.0) -> str:
    t = np.arange(int(sr * dur)) / sr
    f0 = 140 * (1 + 0.04 * np.sin(2 * np.pi * 2.3 * t))
    ph = np.cumsum(2 * np.pi * f0 / sr)
    x = np.zeros_like(t)
    for k in range(1, 40):
        f = 140 * k
        tilt = (f / 400.0) if f < 400 else (400.0 / f)
        x += tilt * (1 + 2.0 * math.exp(-((f - 500) / 180) ** 2) + 2.5 * math.exp(-((f - 1800) / 350) ** 2)) * np.sin(k * ph)
    gate = ((np.sin(2 * np.pi * 1.4 * t) > -0.2) & (t > 0.3) & (t < dur - 0.4)).astype(np.float64)
    x = x * gate
    x *= 10 ** (level_db / 20) / math.sqrt(float((x[gate > 0] ** 2).mean()))
    raw = path + '.f32'
    open(raw, 'wb').write(x.astype(np.float32).tobytes())
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', raw, path], check=True)
    os.remove(raw)
    return path


def calibrate(verbose: bool = True) -> dict[str, float]:
    """Measure the trim each costume needs to land a −20 LUFS synthetic voice back at −20 LUFS (trim=False)."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix='vpres_')
    src = _synth_voice_wav(os.path.join(tmp, 'voice.wav'))
    base = measure_lufs(src)['lufs']
    out = {}
    for name, p in PRESETS.items():
        dst = os.path.join(tmp, name + '.wav')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-af', preset_chain(name, trim=False), dst], check=True)
        got = measure_lufs(dst)['lufs']
        out[name] = round(base - got, 1)
        if verbose:
            print('  %-10s in %.1f -> out %.1f LUFS   trim needed %+.1f dB%s' % (name, base, got, out[name], '' if p['costume'] else '  (not a costume: left as is)'))
    return out


def _selftest() -> int:
    import tempfile
    ok = True
    tmp = tempfile.mkdtemp(prefix='vpres_')
    # 1. every preset (with and without evenness / deess) parses and runs
    src = _synth_voice_wav(os.path.join(tmp, 'v.wav'))
    for name in PRESETS:
        for kw in ({}, {'evenness': 0.5, 'deess': True}):
            ch = preset_chain(name, **kw)
            r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-af', ch, '-f', 'null', '-'], capture_output=True, text=True)
            ok &= r.returncode == 0
            print('%-10s %-22s %s' % (name, 'evenness+deess' if kw else '', 'RUNS' if r.returncode == 0 else 'FAILED ' + r.stderr[-200:]))
    # 2. evenness formulas at the anchors
    e0, e1 = evenness_compressor(0), evenness_compressor(1)
    ok &= 'threshold=-12.0dB:ratio=2.00:attack=25.0:release=300:makeup=0.00' in e0 and 'threshold=-30.0dB:ratio=6.00:attack=5.0:release=90:makeup=9.50' in e1
    print('evenness 0: %s\nevenness 1: %s' % (e0, e1))
    # 3. jobs: a collision is refused, a non-colliding one is placed in the right stage
    try:
        preset_chain('clean', jobs=['add_clarity']); ok = False; print('collision NOT refused')
    except ValueError as e:
        print('collision refused: %s' % e)
    ch = preset_chain('telephone', jobs=['reduce_boxiness', 'add_clarity'], evenness=0.3)   # cut → sub stage, boost → tone stage
    ok &= ch.index('equalizer=f=400') < ch.index('acompressor') < ch.index('equalizer=f=3000:width_type=q:w=1.0:g=2.5') < ch.index('asoftclip')
    print('telephone + jobs: %s' % ch)
    # 4. costumes land within 1.5 dB of the source with their trims
    base = measure_lufs(src)['lufs']
    for name, p in PRESETS.items():
        if not p['costume']:
            continue
        dst = os.path.join(tmp, name + '.wav')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-af', preset_chain(name), dst], check=True)
        got = measure_lufs(dst)['lufs']
        ok &= abs(got - base) <= 1.5
        print('%-10s trimmed: %.1f -> %.1f LUFS (delta %+.1f)' % (name, base, got, got - base))
    # 5. level match: three phrases at -14 / -20 / -26 dB (one short) come back to the target within 1 dB
    paths = [_synth_voice_wav(os.path.join(tmp, 'p%d.wav' % i), dur=d, level_db=lv) for i, (d, lv) in enumerate(((4.0, -14), (5.0, -20), (2.0, -26)))]
    rows = level_match(paths)
    for r in rows:
        dst = r['path'].replace('.wav', '_m.wav')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', r['path'], '-af', gain_chain(r['gain_db']), dst], check=True)
        after = speaking_rms_db(dst)['rms_db'] + (LUFS_TARGET_STEM - r['measured'] - r['gain_db'])
        after_l = measure_lufs(dst)['lufs'] if r['dur'] >= SHORT_PHRASE_S else None
        print('%s dur %.1f %-9s measured %.1f gain %+.1f -> %s' % (os.path.basename(r['path']), r['dur'], r['method'], r['measured'], r['gain_db'],
                                                                   ('%.1f LUFS' % after_l) if after_l is not None else 'short (rms path)'))
        if after_l is not None:
            ok &= abs(after_l - LUFS_TARGET_STEM) <= 1.0
    gains = [r['gain_db'] for r in rows]
    ok &= gains[0] < gains[1] < gains[2] and abs(gains[2] - gains[1] - 6) < 1.5 and abs(gains[1] - gains[0] - 6) < 1.0
    print('SELFTEST %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='ffmpeg voice preset chains + per-phase level match', formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('preset', nargs='?', help=' | '.join(PRESETS))
    ap.add_argument('--evenness', type=float); ap.add_argument('--deess', action='store_true')
    ap.add_argument('--job', action='append', default=[], help=' | '.join(JOBS))
    ap.add_argument('--no-trim', action='store_true', help='omit the costume level trim')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--level-match', nargs=2, metavar=('VO_DIR', 'NAME'), help='print per-phase gains for vo/<name>_<phase>.mp3')
    ap.add_argument('--target', type=float, default=LUFS_TARGET_STEM)
    ap.add_argument('--calibrate', action='store_true'); ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.calibrate:
        print(json.dumps(calibrate(), indent=1)); return 0
    if a.list:
        for n, p in PRESETS.items():
            print('%-10s %-8s trim %+.1f dB  %s' % (n, 'costume' if p['costume'] else 'preset', p['trim_db'], p['use']))
        for n, (f, g, q) in JOBS.items():
            print('job %-18s %d Hz %+.1f dB Q%.1f' % (n, f, g, q))
        return 0
    if a.level_match:
        rows = phase_gains(a.level_match[0], a.level_match[1], a.target)
        for ph, r in rows.items():
            print('%-14s dur %5.2f  %-9s %6.1f  gain %+5.1f dB  spread %4.1f dB  -> %s' % (ph, r['dur'], r['method'], r['measured'], r['gain_db'], r['spread_db'], gain_chain(r['gain_db'])))
        return 0
    if not a.preset:
        ap.error('preset name required (or --list / --level-match / --selftest)')
    print(preset_chain(a.preset, a.evenness, a.deess, a.job, trim=not a.no_trim))
    return 0


if __name__ == '__main__':
    sys.exit(main())
