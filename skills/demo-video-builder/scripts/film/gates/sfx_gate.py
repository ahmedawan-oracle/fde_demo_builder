# -*- coding: utf-8 -*-
"""sfx_gate.py — qa_film.py plug-in: the synthesized sound effects never mask a word, never thump twice, sit at level.

    python gates/sfx_gate.py --selftest          (synthetic cue plan + stems, ~10 s of ffmpeg)

Inputs (all written by audio/sfx_place.py and build_film.py):
    out/cues_<name>.json   the placed plan {cues:[{t, kind, id, act, sfx, ...}], dropped:[...], demoted:[...]}
    out/sfx_<name>.wav     the rendered SFX stem (bus gain already applied) — film.json "sfx": {"auto": true} builds it
                           there; a string "sfx": "path.wav" names a hand-made stem instead
    out/stem_bed_<name>.wav  the bed stem (when a bed is configured) for the "adds to the bed" measurement
    vo/<name>_words.json + vo/<name>_phases.json + vo_<name>.mp3  the narration clock and its waveform

Gates (GATE_NAMES, in order):
  sfx word-safe    every placed transient (everything but the riser, which is a swell) is >= qa.sfx_guard_s (0.15 s)
                   from every narration word onset whose 150 ms peak is above -20 dBFS (sfx_place.word_onsets — the
                   same rule the placer used, re-measured here from the files so a hand-edited plan cannot drift).
                   A non-empty `dropped` list shows as WARN in the detail (silence beats a masked word), and so does
                   a cue the author pinned with "force": true (reported `forced: true` by the placer): it may sit
                   inside the guard by decision, the gate names it and the gap, and does not fail the film for it.
  sfx one impact   at most one `impact-low` per act (a second impact must have been demoted to a snap).
  sfx level        the stem's sample peak sits between qa.sfx_peak_min (-24) and qa.sfx_peak_max (-16) dBFS (files at
                   -6 dBFS through the -14 dB bus = -20 dBFS); when a bed stem exists, bed + sfx is 0.1 .. 3.0 LU louder
                   than the bed alone (qa.sfx_lu_min / sfx_lu_max): audible, never a second music layer.

Skips: no "sfx" in film.json and no cue plan -> every row PASS 'skipped'. A film.json "sfx" file without a cue plan
(a hand-made stem) is measured for level only.
qa.json keys (defaults): sfx_guard_s 0.15, sfx_peak_min -24, sfx_peak_max -16, sfx_lu_min 0.1, sfx_lu_max 3.0,
sfx_word_floor_dbfs -20.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'audio'))
import sfx_place                                   # noqa: E402  (word_onsets, GUARD_S, WORD_FLOOR_DBFS)
import fx_chain                                    # noqa: E402  (measure)

GATE_NAMES = ['sfx word-safe', 'sfx one impact', 'sfx level', 'cue sync']
DEFAULTS = {'sfx_guard_s': sfx_place.GUARD_S, 'sfx_peak_min': -24.0, 'sfx_peak_max': -16.0, 'sfx_lu_min': 0.1, 'sfx_lu_max': 3.0,
            'sfx_word_floor_dbfs': sfx_place.WORD_FLOOR_DBFS}
SWELLS = ('riser',)                                # a swell has no transient to guard; only its landing matters (checked by the placer)


# ----------------------------------------------------------------------------------------------- pure checks
def word_safe(cues, onsets, guard):
    """[(id, t, nearest onset, gap)] for every transient cue closer than `guard` to a word onset."""
    on = np.asarray(sorted(onsets), dtype=np.float64)
    bad = []
    for c in sorted(cues, key=lambda c: (float(c['t']), str(c.get('id')))):
        if (c.get('sfx') or '') in SWELLS or on.size == 0:
            continue
        t = float(c['t'])
        i = int(np.searchsorted(on, t))
        near = min([abs(t - on[j]) for j in (i - 1, i) if 0 <= j < on.size], default=None)
        if near is not None and near < guard - 1e-9:
            j = i if i < on.size and abs(t - on[i]) == near else i - 1
            bad.append((c.get('id'), round(t, 3), round(float(on[j]), 3), round(float(near), 3)))
    return bad


def impacts_per_act(cues):
    """{act: n} of impact-low cues; the gate fails on any n > 1."""
    n = {}
    for c in cues:
        if c.get('sfx') == 'impact-low':
            a = str(c.get('act', 'film'))
            n[a] = n.get(a, 0) + 1
    return dict(sorted(n.items()))


def lu_added(bed_wav, sfx_wav):
    """Integrated loudness of bed, and of bed + sfx summed sample-accurately (ffmpeg amix normalize=0)."""
    fd, mix = tempfile.mkstemp(suffix='.wav', prefix='sfxmix_')
    os.close(fd)
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', bed_wav, '-i', sfx_wav, '-filter_complex',
                        '[0:a][1:a]amix=inputs=2:normalize=0:duration=first[o]', '-map', '[o]', '-c:a', 'pcm_s24le', mix], check=True)
        b, m = fx_chain.measure(bed_wav), fx_chain.measure(mix)
        return float(b['lufs']), float(m['lufs'])
    finally:
        try:
            os.remove(mix)
        except OSError:
            pass


# ----------------------------------------------------------------------------------------------- the gate
def run(ctx):
    cfg, qa, P = ctx.get('cfg') or {}, ctx.get('qa') or {}, ctx['project']
    Q = {k: float(qa.get(k, v)) for k, v in DEFAULTS.items()}
    name = cfg.get('name', 'film')
    cues_p = os.path.join(P, 'out', 'cues_%s.json' % name)
    hand_made = cfg.get('sfx') if isinstance(cfg.get('sfx'), str) and cfg.get('sfx') else None     # {"auto": true} -> out/sfx_<name>.wav
    stem = os.path.join(P, hand_made) if hand_made else os.path.join(P, 'out', 'sfx_%s.wav' % name)
    bed_stem = os.path.join(P, 'out', 'stem_bed_%s.wav' % name)
    if not cfg.get('sfx') and not os.path.exists(cues_p):
        return [(n, True, 'skipped: no SFX configured (film.json "sfx" null, no out/cues_%s.json)' % name) for n in GATE_NAMES]
    res = []
    plan = json.load(open(cues_p, encoding='utf-8')) if os.path.exists(cues_p) else None
    if plan is None:
        res += [('sfx word-safe', True, 'skipped: no cue plan (out/cues_%s.json) — a hand-made stem is measured for level only' % name),
                ('sfx one impact', True, 'skipped: no cue plan'), ('cue sync', True, 'skipped: no cue plan')]
    else:
        cues = plan.get('cues', [])
        vo = os.path.join(P, 'vo_%s.mp3' % name)
        words, phases = ctx.get('words'), ctx.get('vo_phases')
        if words is None:
            res.append(('sfx word-safe', False, 'vo/%s_words.json missing: the guard cannot be re-measured' % name))
        else:
            onsets, n_words = sfx_place.word_onsets(words, phases, vo if os.path.exists(vo) else None, Q['sfx_word_floor_dbfs'])
            forced = {c.get('id') for c in cues if c.get('forced')}
            hits = word_safe(cues, onsets, Q['sfx_guard_s'])
            bad = [h for h in hits if h[0] not in forced]
            pinned = [h for h in hits if h[0] in forced]          # author's decision ("force": true): named, not failed
            d = '%d cues vs %d/%d loud word onsets (guard %.2f s)' % (len(cues), len(onsets), n_words, Q['sfx_guard_s'])
            if bad:
                d = 'inside the guard (id, t, onset, gap) %s; ' % bad[:4] + d
            if pinned:
                d += '  WARN %d forced cue(s) inside the guard (id, gap s): %s' % (len(pinned), [(h[0], h[3]) for h in pinned][:4])
            if plan.get('dropped'):
                d += '  WARN %d cue(s) dropped by the placer: %s' % (len(plan['dropped']), [x.get('id') for x in plan['dropped']][:4])
            res.append(('sfx word-safe', not bad, d))
        per = impacts_per_act(cues)
        over = {a: n for a, n in per.items() if n > 1}
        res.append(('sfx one impact', not over, ('%s has %s impacts (max 1 per act; the placer demotes the second to a snap)' % (list(over)[0], over[list(over)[0]]))
                    if over else '%d impact(s) across %d act(s)%s' % (sum(per.values()), len(per), ' %s' % per if per else '')))
        # cue sync (v5.1): every placed sound is located in the FINISHED film's audio and must sit within 1 ms of its cue
        film = ctx.get('film')
        if cues and film and os.path.exists(film):
            try:
                import cues_check as CC
                sfx_dir = os.path.join(P, plan.get('sfx_dir', 'audio/sfx'))
                R = CC.check(plan, CC.decode(film), sfx_dir, float(qa.get('cue_tol_ms', CC.TOL_MS)))
                res.append(('cue sync', R['ok'], '; '.join(R['bad'])[:300] if not R['ok'] else '%d cues located in the master, worst %.2f ms (limit %g ms)' % (R['n'], R['worst_ms'], float(qa.get('cue_tol_ms', CC.TOL_MS)))))
            except Exception as e:
                res.append(('cue sync', False, 'cues_check failed: %s: %s' % (type(e).__name__, str(e)[:120])))
        else:
            res.append(('cue sync', True, 'skipped: no cues or no film'))
    if not os.path.exists(stem):
        res.append(('sfx level', False, 'SFX stem missing: %s (audio/sfx_place.py --render)' % os.path.relpath(stem, P)))
        return res
    try:
        m = fx_chain.measure(stem)
        pk = float(m['peak_dbfs'])
        ok = Q['sfx_peak_min'] - 1e-6 <= pk <= Q['sfx_peak_max'] + 1e-6
        d = 'stem peak %.1f dBFS (want %.0f..%.0f)' % (pk, Q['sfx_peak_min'], Q['sfx_peak_max'])
        if os.path.exists(bed_stem):
            b, bm = lu_added(bed_stem, stem)
            add = bm - b
            ok = ok and Q['sfx_lu_min'] - 1e-6 <= add <= Q['sfx_lu_max'] + 1e-6
            d += '; bed %.1f -> bed+sfx %.1f LUFS = +%.2f LU (want %.1f..%.1f)' % (b, bm, add, Q['sfx_lu_min'], Q['sfx_lu_max'])
        else:
            d += '; no bed stem to compare against'
        res.append(('sfx level', ok, d))
    except Exception as e:
        res.append(('sfx level', False, 'measurement failed: %s' % str(e)[:140]))
    return res


# ----------------------------------------------------------------------------------------------- selftest
def _wav(path, x, sr=48000):
    import wave
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], -1)
    pcm = np.clip(x * 32767.0, -32768, 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


def _burst(x, t, dur, peak_db, sr, f=1200.0):
    a, b = int(t * sr), int((t + dur) * sr)
    n = max(0, min(b, x.size) - a)
    if n <= 0:
        return
    tt = np.arange(n) / sr
    env = np.exp(-tt / (dur / 4.0))
    x[a:a + n] += (10 ** (peak_db / 20.0)) * env * np.sin(2 * math.pi * f * tt)


def _selftest():
    import time
    T0 = time.time()
    tmp = tempfile.mkdtemp(prefix='sfxgate_')
    os.makedirs(os.path.join(tmp, 'out')); os.makedirs(os.path.join(tmp, 'vo'))
    SR, name, total = 48000, 'film', 12.0
    rng = np.random.default_rng(3)
    # narration: two phases, a word every 0.5 s; the voice file has a -12 dBFS burst on each word (loud -> guarded)
    phases = {'total': total, 'phases': [{'name': 'open', 'start': 1.0, 'dur': 4.0}, {'name': 'demo', 'start': 6.0, 'dur': 5.0}]}
    words = {ph['name']: [{'t': round(0.1 + i * 0.5, 3), 'w': 'acme%d' % i} for i in range(8)] for ph in phases['phases']}
    json.dump(phases, open(os.path.join(tmp, 'vo', name + '_phases.json'), 'w'))
    json.dump(words, open(os.path.join(tmp, 'vo', name + '_words.json'), 'w'))
    onsets_true = sorted(ph['start'] + w['t'] for ph in phases['phases'] for w in words[ph['name']])
    vo = np.zeros(int((total + 1) * SR))
    for t in onsets_true:
        _burst(vo, t, 0.12, -12.0, SR, 220.0)
    vo_wav = os.path.join(tmp, 'vo_tmp.wav'); _wav(vo_wav, vo, SR)
    vo_mp3 = os.path.join(tmp, 'vo_%s.mp3' % name)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', vo_wav, '-c:a', 'libmp3lame', '-q:a', '2', vo_mp3], check=True)
    # a bed stem: lightly smoothed noise at about -30 LUFS (a quiet booth bed)
    bed = rng.standard_normal(int((total + 1) * SR)) * 0.035
    bed = np.convolve(bed, np.ones(4) / 4.0, 'same')
    _wav(os.path.join(tmp, 'out', 'stem_bed_%s.wav' % name), bed, SR)

    def plan_and_stem(cues, peak_db, dropped=()):
        json.dump({'cues': cues, 'dropped': list(dropped), 'demoted': [], 'words_guarded': len(onsets_true), 'words_total': len(onsets_true),
                   'total': total, 'sfx_db': -14.0}, open(os.path.join(tmp, 'out', 'cues_%s.json' % name), 'w'))
        x = np.zeros(int((total + 1) * SR))
        for c in cues:
            _burst(x, c['t'], 0.08, peak_db, SR)
        _wav(os.path.join(tmp, 'out', 'sfx_%s.wav' % name), x, SR)

    ctx = {'project': tmp, 'cfg': {'name': name, 'sfx': 'out/sfx_%s.wav' % name}, 'qa': {}, 'words': words, 'vo_phases': phases}
    ok, rows = True, []

    def check(label, cond, detail=''):
        nonlocal ok
        ok = ok and bool(cond); rows.append((label, cond))
        print('  %-40s %s  %s' % (label, 'PASS' if cond else 'FAIL', str(detail)[:120]))

    # good: cues midway between words (0.25 s from every onset), one impact per act
    good = [{'t': round(onsets_true[1] + 0.25, 3), 'kind': 'land', 'id': 'kpi:land', 'act': 'open', 'sfx': 'tick'},
            {'t': round(onsets_true[2] + 0.25, 3), 'kind': 'impact', 'id': 'open-hit', 'act': 'open', 'sfx': 'impact-low'},
            {'t': round(onsets_true[9] + 0.25, 3), 'kind': 'cut', 'id': 'nb->q', 'act': 'demo', 'sfx': 'whoosh'},
            {'t': round(onsets_true[11] + 0.25, 3), 'kind': 'chapter', 'id': 'demo-hit', 'act': 'demo', 'sfx': 'impact-low'},
            {'t': round(onsets_true[12] + 0.02, 3), 'kind': 'climax', 'id': 'close:climax', 'act': 'demo', 'sfx': 'riser'}]
    plan_and_stem(good, -20.0)
    R = {n: (o, d) for n, o, d in run(ctx)}
    for n in GATE_NAMES:
        print('    %-16s %s  %s' % (n, 'PASS' if R[n][0] else 'FAIL', R[n][1][:110]))
    check('good plan: word-safe', R['sfx word-safe'][0], R['sfx word-safe'][1])
    check('good plan: riser exempt from the guard', R['sfx word-safe'][0] and 'inside' not in R['sfx word-safe'][1])
    check('good plan: one impact per act', R['sfx one impact'][0], R['sfx one impact'][1])
    check('good stem: level -20 dBFS in range, LU added', R['sfx level'][0], R['sfx level'][1])
    # bad: a tick 0.05 s before a word, two impacts in one act, stem 10 dB hot, a dropped cue listed
    bad = [dict(good[0], t=round(onsets_true[1] - 0.05, 3)), good[1], dict(good[1], id='open-hit-2', t=round(onsets_true[4] + 0.25, 3))] + good[2:]
    plan_and_stem(bad, -10.0, dropped=[{'id': 'late:land', 'reason': 'inside the guard'}])
    R = {n: (o, d) for n, o, d in run(ctx)}
    for n in GATE_NAMES:
        print('    %-16s %s  %s' % (n, 'PASS' if R[n][0] else 'FAIL', R[n][1][:110]))
    check('bad plan: cue 0.05 s before a word fails', not R['sfx word-safe'][0] and 'kpi:land' in R['sfx word-safe'][1], R['sfx word-safe'][1])
    check('bad plan: dropped list shows as WARN', 'WARN 1 cue' in R['sfx word-safe'][1])
    check('bad plan: two impacts in one act fail', not R['sfx one impact'][0] and 'open' in R['sfx one impact'][1], R['sfx one impact'][1])
    check('hot stem (-10 dBFS) fails level', not R['sfx level'][0], R['sfx level'][1])
    # forced: the same early tick pinned by the author ("force": true -> forced: true) is a WARN, not a failure
    pinned = [dict(bad[0], forced=True)] + good[1:]
    plan_and_stem(pinned, -20.0)
    R = {n: (o, d) for n, o, d in run(ctx)}
    check('forced cue inside the guard -> WARN, word-safe PASS', R['sfx word-safe'][0] and 'WARN 1 forced' in R['sfx word-safe'][1] and 'kpi:land' in R['sfx word-safe'][1], R['sfx word-safe'][1])
    # film.json "sfx": {"auto": true} -> the stem is out/sfx_<name>.wav
    R = {n: (o, d) for n, o, d in run(dict(ctx, cfg={'name': name, 'sfx': {'auto': True}}))}
    check('"sfx": {"auto": true} resolves the stem in out/', R['sfx level'][0] and 'missing' not in R['sfx level'][1], R['sfx level'][1])
    # pure helpers
    check('word_safe pure: gap 0.149 flagged, 0.151 clean', word_safe([{'t': 2.149, 'id': 'a', 'sfx': 'tick'}], [2.0], 0.15) and not word_safe([{'t': 2.151, 'id': 'a', 'sfx': 'tick'}], [2.0], 0.15))
    check('impacts_per_act counts only impact-low', impacts_per_act([{'act': 'a', 'sfx': 'impact-low'}, {'act': 'a', 'sfx': 'snap'}, {'act': 'b', 'sfx': 'impact-low'}]) == {'a': 1, 'b': 1})
    # skips
    R = {n: (o, d) for n, o, d in run({'project': tempfile.mkdtemp(prefix='sfxnone_'), 'cfg': {'name': 'x'}, 'qa': {}})}
    check('no sfx configured -> all rows skipped PASS', all(o for o, _ in R.values()) and all('skipped' in d for _, d in R.values()))
    print('\n%s  (%d/%d, %.1f s)  %s' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', sum(1 for _, c in rows if c), len(rows), time.time() - T0, tmp))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
