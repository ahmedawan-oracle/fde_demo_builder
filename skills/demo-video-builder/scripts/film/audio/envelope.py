# -*- coding: utf-8 -*-
"""envelope.py — volume automation from keyframes {t, db} with slope-limited ramps, in three ffmpeg-ready forms.

    python audio/envelope.py keys.json --total 93.3 --expr                 # ffmpeg volume= expression (stdout)
    python audio/envelope.py keys.json --total 93.3 --sendcmd out/bed.cmd   # sendcmd file for volume@bed
    python audio/envelope.py keys.json --total 93.3 --wav out/bed_env.wav   # sample-accurate gain curve (amultiply)
    python audio/envelope.py --seams seams.json --breathe -3 --total 93.3 --json out/env.json --wav out/bed_env.wav
    python audio/envelope.py --selftest

Why keyframes and not a compressor
  A sidechain follows the voice's energy, so a breath or a plosive changes the duck. The bed's two deliberate
  moves — the "breathe" at a seam (a dip and recovery that makes a cut feel intended) and the swell under a
  riser — are decisions on the narration clock, so they are written as keyframes and rendered as a pure
  function of t. Rendered twice, the curve is identical to the sample.

The ramp rule (±6 dB/s)
  A volume change the ear accepts as music "moving" is ≤ 6 dB per second; faster reads as a fault (the bed
  "stumbles"). Between consecutive keyframes the slope is |Δdb| / Δt. When it exceeds MAX_SLOPE_DB_S the ramp
  is stretched, never clipped in level:
    going DOWN  the arrival time is kept and the ramp STARTS EARLIER (a duck should lead the event — the same
                lead the carve gives the voice);
    going UP    the start is kept and the ramp ENDS LATER (recovery is allowed to be slow).
  Stretching stops at the neighbouring keyframe (a keyframe is a promise); if that still leaves the slope
  over the limit the keyframe is kept and the violation is reported in `warnings` — the author decides.
  Result: a monotone piecewise-linear curve in dB, held flat before the first and after the last keyframe.

Three outputs, all from the same curve
  --expr      volume='<piecewise expression in t>':eval=frame  — one filter string, evaluated once per audio
              frame (1024 samples = 21 ms at 48 kHz: 6 dB/s becomes 0.13 dB steps, below the 0.5 dB a listener
              can hear as a step). Fine for ≤ 60 keyframes; longer films should use the WAV.
  --sendcmd   a sendcmd file (`<t> volume@<name> volume <lin>;` every STEP s, default 0.05) for graphs that
              already carry a named volume filter.
  --wav       a mono 32-bit-float gain-curve WAV at 48 kHz, used as  [bed][env]amultiply  — sample-accurate,
              exact, the form the carve's envelope mode uses. Gains above 0 dB are allowed (float).

Helpers
  breathe(seam_times, depth_db=-3, lead=0.4, hold=0.1, recover=1.2)  → keyframes: dip `depth_db` arriving at
      the cut (start lead s before), hold, recover over `recover` s (3 dB over 1.2 s = 2.5 dB/s, inside the rule)
  swell(t_end, dur=2.0, from_db=-6, to_db=0) → keyframes rising under a riser, landing at t_end (the bed settles
      to from_db ahead of the riser at the ramp limit: 6 dB → a 1.0 s lead-in)
  merge(*keyframe_lists) → one sorted list; where lists overlap the LOWER dB wins (a duck beats a swell)

JSON in: {"keyframes":[{"t":..,"db":..}, ...]} or a bare list. JSON out (--json): {total, max_slope_db_s,
keyframes (as resolved), warnings, step, expr, sendcmd_lines, wav}.
Exit codes: 0 ok, 1 the curve has slope violations that could not be resolved, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Iterable, Sequence

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sfx_synth  # noqa: E402  (write_wav / read_wav)

SR = 48000
MAX_SLOPE_DB_S = 6.0
STEP_S = 0.05
BREATHE = {'depth_db': -3.0, 'lead': 0.4, 'hold': 0.1, 'recover': 1.2}
SWELL = {'dur': 2.0, 'from_db': -6.0, 'to_db': 0.0}


# ----------------------------------------------------------------------------------------------- keyframes
def _norm(keys: Iterable[dict]) -> list[dict]:
    rows = sorted(({'t': float(k['t']), 'db': float(k['db'])} for k in keys), key=lambda k: k['t'])
    out: list[dict] = []
    for k in rows:                                   # duplicate times: the lower level wins (a duck is a promise)
        if out and abs(out[-1]['t'] - k['t']) < 1e-6:
            out[-1]['db'] = min(out[-1]['db'], k['db'])
        else:
            out.append(k)
    return out


def limit_slopes(keys: Iterable[dict], max_slope: float = MAX_SLOPE_DB_S) -> tuple[list[dict], list[str]]:
    """Apply the ramp rule. Returns (keyframes, warnings). Down-ramps start earlier, up-ramps end later; a move is
    clamped at the neighbouring keyframe and reported when the slope still exceeds the limit."""
    ks = _norm(keys)
    warnings: list[str] = []
    for i in range(1, len(ks)):
        a, b = ks[i - 1], ks[i]
        d = b['db'] - a['db']; dt = b['t'] - a['t']
        if abs(d) <= max_slope * dt + 1e-9:
            continue
        need = abs(d) / max_slope
        if d < 0:                                     # down: start earlier, floor = previous keyframe
            lo = ks[i - 2]['t'] if i >= 2 else -math.inf
            new_t = max(lo, b['t'] - need)
            if new_t < a['t']:
                a['t'] = new_t
        else:                                         # up: end later, ceiling = next keyframe
            hi = ks[i + 1]['t'] if i + 1 < len(ks) else math.inf
            new_t = min(hi, a['t'] + need)
            if new_t > b['t']:
                b['t'] = new_t
        dt = b['t'] - a['t']
        if dt <= 0 or abs(d) / dt > max_slope + 1e-6:
            warnings.append('slope %.1f dB/s between t=%.3f and t=%.3f exceeds %.1f dB/s (neighbouring keyframes block the stretch)'
                            % (abs(d) / dt if dt > 0 else math.inf, a['t'], b['t'], max_slope))
    return [{'t': round(k['t'], 4), 'db': round(k['db'], 3)} for k in ks], warnings


def db_at(keys: Sequence[dict], t: np.ndarray | float) -> np.ndarray:
    """Piecewise-linear dB value(s) at t — flat before the first and after the last keyframe."""
    t = np.asarray(t, dtype=np.float64)
    if not keys:
        return np.zeros_like(t)
    ts = np.array([k['t'] for k in keys]); ds = np.array([k['db'] for k in keys])
    return np.interp(t, ts, ds, left=ds[0], right=ds[-1])


def breathe(seam_times: Iterable[float], depth_db: float = BREATHE['depth_db'], lead: float = BREATHE['lead'],
            hold: float = BREATHE['hold'], recover: float = BREATHE['recover'], base_db: float = 0.0) -> list[dict]:
    """Dip-and-recover around each seam: base -> depth arriving at the cut, hold, back to base."""
    ks = []
    for t in sorted(float(x) for x in seam_times):
        ks += [{'t': t - lead, 'db': base_db}, {'t': t, 'db': base_db + depth_db},
               {'t': t + hold, 'db': base_db + depth_db}, {'t': t + hold + recover, 'db': base_db}]
    return ks


def swell(t_end: float, dur: float = SWELL['dur'], from_db: float = SWELL['from_db'], to_db: float = SWELL['to_db'],
          base_db: float = 0.0) -> list[dict]:
    """Rise from `from_db` to `to_db` landing exactly at t_end (the riser's end / climax cue), then hold. The bed
    settles to `from_db` ahead of the riser at the ramp limit, so the swell itself never breaks the rule."""
    lead = abs(from_db - base_db) / MAX_SLOPE_DB_S
    return [{'t': t_end - dur - lead, 'db': base_db}, {'t': t_end - dur, 'db': from_db}, {'t': t_end, 'db': to_db}]


def merge(*lists: Iterable[dict], step: float = STEP_S) -> list[dict]:
    """Combine keyframe lists; where they overlap the lower dB wins. Sampled on `step`, then re-simplified to the
    corner points so the result stays a short keyframe list."""
    alls = [_norm(l) for l in lists if l]
    if not alls:
        return []
    t0 = min(l[0]['t'] for l in alls); t1 = max(l[-1]['t'] for l in alls)
    grid = np.arange(t0, t1 + step, step)
    curve = np.min(np.stack([db_at(l, grid) for l in alls]), axis=0)
    keep = [0] + [i for i in range(1, len(grid) - 1) if abs((curve[i] - curve[i - 1]) - (curve[i + 1] - curve[i])) > 1e-6] + [len(grid) - 1]
    return [{'t': round(float(grid[i]), 4), 'db': round(float(curve[i]), 3)} for i in keep]


# ----------------------------------------------------------------------------------------------- renderers
def to_expr(keys: Sequence[dict]) -> str:
    """ffmpeg volume filter string: piecewise-linear dB in t, converted to linear gain. eval=frame."""
    if not keys:
        return 'volume=1.0'
    if len(keys) == 1:
        return 'volume=%.4fdB' % keys[0]['db']
    expr = '%.4f' % keys[-1]['db']
    for a, b in reversed(list(zip(keys, keys[1:]))):
        s = (b['db'] - a['db']) / (b['t'] - a['t']) if b['t'] > a['t'] else 0.0
        expr = 'if(lt(t\\,%.4f)\\,%.4f+(t-%.4f)*%.5f\\,%s)' % (b['t'], a['db'], a['t'], s, expr)
    expr = 'if(lt(t\\,%.4f)\\,%.4f\\,%s)' % (keys[0]['t'], keys[0]['db'], expr)
    return "volume='pow(10\\,(%s)/20)':eval=frame" % expr


def to_sendcmd(keys: Sequence[dict], total: float, name: str = 'bed', step: float = STEP_S) -> list[str]:
    """sendcmd lines, one every `step` s, for a filter instanced as volume@<name>."""
    n = int(math.ceil(total / step)) + 1
    ts = np.arange(n) * step
    g = 10 ** (db_at(keys, ts) / 20.0)
    return ['%.3f volume@%s volume %.6f;' % (t, name, v) for t, v in zip(ts, g)]


def to_wav(keys: Sequence[dict], total: float, path: str, sr: int = SR) -> str:
    """Mono float32 gain-curve WAV of `total` seconds (for [bed][env]amultiply)."""
    n = int(round(total * sr))
    g = 10 ** (db_at(keys, np.arange(n) / sr) / 20.0)
    sfx_synth.write_wav(path, g.astype(np.float32), sr, bits=32)
    return path


def resolve(keys: Iterable[dict], total: float, max_slope: float = MAX_SLOPE_DB_S) -> dict:
    """Keyframes -> the full report (curve, expression, warnings). Pure function of its inputs."""
    ks, warns = limit_slopes(keys, max_slope)
    return {'total': total, 'max_slope_db_s': max_slope, 'keyframes': ks, 'warnings': warns, 'expr': to_expr(ks),
            'min_db': round(float(min((k['db'] for k in ks), default=0.0)), 3), 'max_db': round(float(max((k['db'] for k in ks), default=0.0)), 3)}


def seam_times_from(path: str) -> list[float]:
    """Numeric cut times from out/timeline.json ("seams"[].cut or "cuts") or a seams.json whose cuts are numbers."""
    d = json.load(open(path, encoding='utf-8'))
    rows = d.get('seams', d if isinstance(d, list) else [])
    out = [float(r['cut']) for r in rows if isinstance(r.get('cut'), (int, float))]
    if not out and isinstance(d, dict) and d.get('cuts'):
        out = [float(c) for c in d['cuts']]
    return sorted(out)


# ----------------------------------------------------------------------------------------------- selftest
def selftest() -> int:
    import tempfile, subprocess, time
    t0 = time.time(); fails = []
    # 1. the ramp rule: a 12 dB drop over 0.5 s (24 dB/s) must start 2 s before its arrival; a rise ends later
    ks, w = limit_slopes([{'t': 0, 'db': 0}, {'t': 5.0, 'db': 0}, {'t': 5.5, 'db': -12}, {'t': 6.0, 'db': -12}, {'t': 6.2, 'db': 0}])
    if abs(ks[1]['t'] - 3.5) > 1e-3:
        fails.append('down-ramp did not lead: start %.3f (want 3.5)' % ks[1]['t'])
    if abs(ks[4]['t'] - 8.0) > 1e-3:
        fails.append('up-ramp did not extend: end %.3f (want 8.0)' % ks[4]['t'])
    for a, b in zip(ks, ks[1:]):
        if b['t'] > a['t'] and abs(b['db'] - a['db']) / (b['t'] - a['t']) > MAX_SLOPE_DB_S + 1e-6:
            fails.append('slope violation survived between %.2f and %.2f' % (a['t'], b['t']))
    # 2. a blocked stretch is reported, not silently clipped
    _, w2 = limit_slopes([{'t': 0, 'db': 0}, {'t': 1.0, 'db': 0}, {'t': 1.1, 'db': -12}, {'t': 1.2, 'db': 0}])
    if not w2:
        fails.append('blocked stretch produced no warning')
    # 3. breathe at two seams + swell to a climax; the WAV, the expression and sendcmd agree with the curve
    keys = merge(breathe([3.0, 7.0]), swell(9.5))
    rep = resolve(keys, 10.0)
    if rep['warnings']:
        fails.append('merged breathe+swell should be slope-clean: %s' % rep['warnings'])
    tmp = tempfile.mkdtemp(prefix='env_')
    wav = to_wav(rep['keyframes'], 10.0, os.path.join(tmp, 'env.wav'))
    g, sr = sfx_synth.read_wav(wav)
    probe = {3.0: BREATHE['depth_db'], 1.0: 0.0, 9.49: SWELL['to_db']}
    for t, want in probe.items():
        got = 20 * math.log10(max(1e-9, g[int(t * sr), 0]))
        if abs(got - want) > 0.3:
            fails.append('wav gain at %.2f s = %.2f dB (want %.1f)' % (t, got, want))
    md5a = sfx_synth.md5_of(wav); md5b = sfx_synth.md5_of(to_wav(rep['keyframes'], 10.0, os.path.join(tmp, 'env2.wav')))
    if md5a != md5b:
        fails.append('gain WAV not deterministic')
    # the expression through ffmpeg on a constant tone reproduces the dip within 0.3 dB at the seam
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-t', '10', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-af', rep['expr'] + ',aformat=sample_fmts=flt', '-f', 'f32le', '-'], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        fails.append('ffmpeg rejected the volume expression: %s' % r.stderr.decode('utf-8', 'replace')[-200:])
    else:
        y = np.frombuffer(r.stdout, dtype=np.float32)
        lvl = lambda t: 20 * math.log10(np.sqrt(np.mean(y[int(t * 48000):int((t + 0.05) * 48000)] ** 2)))
        got = lvl(3.02) - lvl(1.0)                                     # the dip relative to the untouched bed
        if abs(got - BREATHE['depth_db']) > 0.4:
            fails.append('ffmpeg expr dip at the seam = %.2f dB (want %.1f)' % (got, BREATHE['depth_db']))
    lines = to_sendcmd(rep['keyframes'], 10.0)
    if len(lines) != 201 or 'volume@bed' not in lines[0]:
        fails.append('sendcmd lines wrong (%d)' % len(lines))
    print('envelope selftest: %d keyframes, %d warnings, %.1f s, %s' % (len(rep['keyframes']), len(rep['warnings']), time.time() - t0,
                                                                        'OK' if not fails else '; '.join(fails)))
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='volume automation from {t, db} keyframes with +-6 dB/s ramps -> ffmpeg volume expr / sendcmd / gain WAV')
    ap.add_argument('keys', nargs='?', help='keyframes JSON ({"keyframes":[{t,db}]} or a list)')
    ap.add_argument('--seams', help='out/timeline.json or seams.json with numeric cuts: add a breathe at every cut')
    ap.add_argument('--breathe', type=float, default=None, help='breathe depth in dB at each seam (e.g. -3)')
    ap.add_argument('--swell', type=float, default=None, help='climax time: add a riser swell landing there')
    ap.add_argument('--swell-dur', type=float, default=SWELL['dur'])
    ap.add_argument('--total', type=float, required=False, help='film length in seconds (needed for --sendcmd / --wav)')
    ap.add_argument('--max-slope', type=float, default=MAX_SLOPE_DB_S)
    ap.add_argument('--step', type=float, default=STEP_S)
    ap.add_argument('--name', default='bed', help='volume filter instance name for sendcmd (volume@<name>)')
    ap.add_argument('--expr', action='store_true', help='print the ffmpeg volume expression')
    ap.add_argument('--sendcmd', help='write a sendcmd file')
    ap.add_argument('--wav', help='write a float32 gain-curve WAV')
    ap.add_argument('--json', help='write the resolved report')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    lists = []
    if a.keys:
        d = json.load(open(a.keys, encoding='utf-8'))
        lists.append(d.get('keyframes', d) if isinstance(d, dict) else d)
    if a.seams and a.breathe is not None:
        lists.append(breathe(seam_times_from(a.seams), a.breathe))
    if a.swell is not None:
        lists.append(swell(a.swell, a.swell_dur))
    if not lists:
        ap.print_help(); return 2
    keys = merge(*lists, step=a.step) if len(lists) > 1 else lists[0]
    total = a.total if a.total is not None else (max(k['t'] for k in _norm(keys)) + 1.0)
    rep = resolve(keys, total, a.max_slope)
    if a.sendcmd:
        lines = to_sendcmd(rep['keyframes'], total, a.name, a.step)
        open(a.sendcmd, 'w', encoding='utf-8').write('\n'.join(lines) + '\n'); rep['sendcmd'] = a.sendcmd
    if a.wav:
        rep['wav'] = to_wav(rep['keyframes'], total, a.wav)
    if a.expr or not (a.sendcmd or a.wav or a.json):
        print(rep['expr'])
    if a.json:
        json.dump(rep, open(a.json, 'w', encoding='utf-8'), indent=1)
    if not a.expr:
        print(json.dumps({k: rep[k] for k in ('total', 'keyframes', 'warnings', 'min_db', 'max_db')}, indent=1), file=sys.stderr)
    return 1 if rep['warnings'] else 0


if __name__ == '__main__':
    sys.exit(main())
