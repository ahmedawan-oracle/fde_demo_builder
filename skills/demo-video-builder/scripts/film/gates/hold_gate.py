# -*- coding: utf-8 -*-
"""hold_gate.py — move first, then hold: the stillness a recreated beat owes the cut that follows it.  (qa_film.py plug-in)

A footage match-cut carries motion through the cut (the seam doctrine, measured by seam_gate). A recreated or
explainer beat does the opposite: everything it has to say moves in the first part of the beat, then the composition
HOLDS — only a declared background may drift — so the end frame is a still the next cut can land on and an editor can
trim. The hold is declared per segment as a fraction of its length (`hold: 0.6` = the last 40 % is still):

    shots.js      { t0, t1, clip, hold: 0.6, holdBg: 0.8 }               a footage shot that ends on a held state
    FILM.holds    [{ id: 'title', t0: 0, t1: FILM.openEnd, hold: 0.6, bg: 0.4 }, …]   the recreated segments
    export_timeline.js writes both into out/timeline.json → holds[] ({id, t0, t1, hold, bg?, footage?})

Gates (GATE_NAMES):
  hold declared   the plan is consistent: 0.3 ≤ hold ≤ 0.95; every recreated beat in STORYBOARD.md is covered by a
                  hold row (REQUIRED) unless the beat writes an explicit waiver — `hold: none (reason)` — which is
                  reported as a WARN, never silently; a footage shot whose end is a vector seam or a match-cut row in
                  the ledger carries no hold (FORBIDDEN — the eye's momentum must survive that cut); gl rows are
                  allowed (the window is the transition, not the shot).
  hold still      on the rendered film (10 fps, 320x180 grey): inside [t0 + hold·(t1−t0), t1 − cut_pad] the mean
                  absolute frame difference per 0.1 s stays under the background allowance (`bg`, default 1.0 % of
                  full scale — a slow drift, a breathing lamp, a flake field); anything above it is motion that
                  belongs in the first part of the beat → FAIL with the time and the value. WARN when nothing at all
                  moved before the hold (a slide, not a shot).

seam_gate reads the same holds and skips `seams move` for a row whose cut ends a held segment (the hold wins; the
cut still lands on a word). Doctrine: references/hold-doctrine.md and motion-doctrine.md Part 1.

qa.json: {"hold": {"bg": 1.0, "fps": 10, "cut_pad": 0.15, "min_move": 0.3, "min": 0.3, "max": 0.95, "cover": 0.5}}

    python gates/hold_gate.py --selftest                      synthetic film, no browser
    python gates/hold_gate.py <project> [film.mp4]            run both gates on a project
"""
import json, os, subprocess, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_NAMES = ['hold declared', 'hold still']
DEFAULTS = {'bg': 1.0, 'fps': 10, 'res': (320, 180), 'cut_pad': 0.15, 'min_move': 0.3, 'min': 0.3, 'max': 0.95, 'cover': 0.5, 'near': 0.05}
VECTOR_TYPES = ('cut', 'match-cut', 'morph')       # ledger row types whose cut carries motion through — a hold may not end there


def _cfg(qa):
    c = dict(DEFAULTS)
    c.update({k: v for k, v in ((qa or {}).get('hold') or {}).items()})
    return c


# ---------------------------------------------------------------- the plan
def load_holds(ctx):
    """hold rows with numeric spans from out/timeline.json (holds[] + shots[] carrying `hold`)."""
    tl = ctx.get('timeline') or {}
    rows = []
    for h in tl.get('holds', []) or []:
        if isinstance(h, dict) and all(isinstance(h.get(k), (int, float)) for k in ('t0', 't1', 'hold')):
            rows.append(dict(h))
    seen = {(r['t0'], r['t1']) for r in rows}
    for s in tl.get('shots', []) or []:
        if isinstance(s.get('hold'), (int, float)) and s.get('t0') is not None and s.get('t1') is not None and (s['t0'], s['t1']) not in seen:
            rows.append({'id': s.get('clip') or 'shot', 't0': float(s['t0']), 't1': float(s['t1']), 'hold': float(s['hold']), 'footage': True})
    return sorted(rows, key=lambda r: r['t0'])


def hold_ends(ctx):
    """the times at which held segments end — seam_gate skips 'seams move' for a cut within `near` of one."""
    return [float(r['t1']) for r in load_holds(ctx)]


def window(row, cfg):
    """(move_a, move_b, hold_a, hold_b): the move part and the measured hold part of a row."""
    t0, t1, h = float(row['t0']), float(row['t1']), float(row['hold'])
    split = t0 + h * (t1 - t0)
    return (t0 + cfg['cut_pad'], split, split, t1 - cfg['cut_pad'])


def _beats(ctx):
    """[(number, t0, t1, real)] from STORYBOARD.md (spans from the narration clock when phases exist)."""
    project = ctx.get('project') or '.'
    sb = os.path.join(project, ((ctx.get('cfg') or {}).get('storyboard') or 'STORYBOARD.md'))
    if not os.path.exists(sb):
        return None
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
    try:
        import storyboard as SB
    except ImportError:
        return None
    man = SB.parse(open(sb, encoding='utf-8').read())
    phases = ctx.get('vo_phases')
    if phases:
        try:
            SB.check(man, phases=phases, autonomous=True)
        except Exception:
            pass
    out = []
    for b in man['beats']:
        s, e = b.get('actual') or (b['t0'], b['t1'])
        if s is not None and e is not None:
            out.append((b['number'], float(s), float(e), b.get('real', ''), (b['fields'].get('hold') or '').strip()))
    return out


def check_plan(rows, beats, seams, cfg):
    """(errors, notes) for 'hold declared'."""
    E, N = [], []
    for r in rows:
        if not (cfg['min'] <= float(r['hold']) <= cfg['max']):
            E.append('%s: hold %.2f outside %.2f–%.2f (a hold is the last part of a beat, never all of it or none)' % (r.get('id', '?'), r['hold'], cfg['min'], cfg['max']))
        if float(r['t1']) - float(r['t0']) < 2 * cfg['cut_pad'] + 0.2:
            E.append('%s: segment %.2f–%.2f is too short to hold anything' % (r.get('id', '?'), r['t0'], r['t1']))
    waived = []
    if beats:
        for n, s, e, real, hv in beats:
            if real != 'recreated':
                continue
            if hv.lower().startswith(('none', 'no ', 'no:', 'no(', 'no—', 'no -')) or hv.lower() == 'no':
                waived.append('beat %02d waives its hold: %s' % (n, hv.split(None, 1)[1].strip('(—-: )') if len(hv.split(None, 1)) > 1 else 'no reason given'))
                continue
            cover = 0.0
            for r in rows:
                cover += max(0.0, min(e, float(r['t1'])) - max(s, float(r['t0'])))
            if (e - s) > 0 and cover / (e - s) < cfg['cover']:
                E.append('beat %02d (recreated, %.1f–%.1f s) has no hold — declare one (FILM.holds / shots.js hold:) or waive it in the storyboard (hold: none (reason))' % (n, s, e))
        N.append('%d recreated beats covered' % sum(1 for b in beats if b[3] == 'recreated' and not any(('beat %02d ' % b[0]) in w for w in waived)))
        if waived:
            N.append('WARN ' + ' | '.join(waived))
    for r in rows:
        if not r.get('footage'):
            continue
        for row in seams or []:
            c = row.get('cut')
            if isinstance(c, (int, float)) and abs(float(c) - float(r['t1'])) <= cfg['near'] and row.get('type', 'cut') in VECTOR_TYPES:
                E.append('%s: hold forbidden — its end is the %s seam %s (motion must carry through a footage match-cut)' % (r.get('id', '?'), row.get('type', 'cut'), row.get('id', '?')))
    N.insert(0, '%d hold rows' % len(rows))
    return E, N


# ---------------------------------------------------------------- the picture
def decode_gray(film, fps, res, t0, dur):
    w, h = res
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % max(0.0, t0), '-i', film, '-t', '%.3f' % dur,
           '-vf', 'fps=%s,scale=%d:%d:flags=area,format=gray' % (fps, w, h), '-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], dtype=np.uint8).reshape(n, h, w)


def change_pct(a, b):
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16)))) / 255.0 * 100.0


def measure(film, row, cfg):
    """{'hold': [(t, pct)], 'move_max': float, 'hold_max': (t, pct), 'ok': bool}"""
    fps = float(cfg['fps'])
    ma, mb, ha, hb = window(row, cfg)
    t0 = ma
    frames = decode_gray(film, fps, tuple(cfg['res']), t0, max(0.0, hb - t0) + 1.0 / fps)
    series = [(t0 + i / fps, change_pct(frames[i - 1], frames[i])) for i in range(1, len(frames))]
    move = [p for t, p in series if t < mb]
    hold = [(t, p) for t, p in series if ha <= t <= hb]
    allow = float(row.get('bg', cfg['bg']) or cfg['bg'])
    worst = max(hold, key=lambda x: x[1]) if hold else (ha, 0.0)
    return {'hold': hold, 'move_max': max(move) if move else 0.0, 'hold_max': worst, 'allow': allow,
            'ok': worst[1] <= allow, 'moved': (max(move) if move else 0.0) >= cfg['min_move']}


def run(ctx):
    cfg = _cfg(ctx.get('qa'))
    rows = load_holds(ctx)
    tl = ctx.get('timeline') or {}
    beats = _beats(ctx)
    res = []
    if not rows and not any(b[3] == 'recreated' for b in (beats or [])):
        return [('hold declared', True, 'no hold rows and no recreated beats — nothing to hold'),
                ('hold still', True, 'no hold rows to measure')]
    E, N = check_plan(rows, beats, tl.get('seams', []), cfg)
    res.append(('hold declared', not E, '; '.join(E)[:400] if E else ', '.join(N)))
    film = ctx.get('film')
    if not film or not os.path.exists(film):
        res.append(('hold still', False, 'film not found'))
        return res
    bad, warn, det = [], [], []
    for r in rows:
        m = measure(film, r, cfg)
        det.append('%s hold %.0f%% max %.2f%%/0.1s (allow %.1f)' % (r.get('id', '?'), 100 * float(r['hold']), m['hold_max'][1], m['allow']))
        if not m['ok']:
            bad.append('%s: %.2f%% change at %.2f s inside the hold (allow %.1f%% — background only; move earlier or raise bg with a reason)' % (r.get('id', '?'), m['hold_max'][1], m['hold_max'][0], m['allow']))
        if not m['moved']:
            warn.append('%s: nothing moved before the hold (max %.2f%%) — a slide, not a shot' % (r.get('id', '?'), m['move_max']))
    d = ('%d holds still' % len(rows)) + ('  WARN ' + ' | '.join(warn) if warn else '') + '  [' + '; '.join(det)[:220] + ']'
    res.append(('hold still', not bad, ' | '.join(bad)[:400] if bad else d))
    return res


# ---------------------------------------------------------------- selftest
def selftest():
    """8 s synthetic film: segment A moves for 60 % then holds over a drifting background (PASS); segment B keeps moving
    into its hold (FAIL); plus the plan checks on a tiny storyboard and ledger."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix='hold_gate_')
    os.makedirs(os.path.join(tmp, 'out'))
    film = os.path.join(tmp, 'out', 'film.mp4')
    fps, W, H, END = 30, 320, 180, 8.0
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '%dx%d' % (W, H), '-r', str(fps), '-i', '-',
                          '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', '-g', '30', film], stdin=subprocess.PIPE)
    ramp = np.tile(np.linspace(0, 1, W, dtype=np.float32), (H, 1))
    for k in range(int(END * fps)):
        t = k / fps
        if t < 4.0:
            bg = 18 + 6 * ramp + 2.0 * (t / 4.0)          # the declared background: a slow brightening, ~0.1 grey levels per 0.1 s
            f = bg.astype(np.uint8)
            u = min(1.0, t / 2.4)                           # the card slides in during the first 60 %, then sits
            x = int(20 + 160 * (1 - (1 - u) ** 3))
            f[50:130, x:x + 90] = 200
        else:
            f = np.full((H, W), 20, np.uint8)
            u = min(1.0, (t - 4.0) / 3.5)                   # the card keeps sliding until 7.5 s — into the hold
            x = int(10 + 220 * u)
            f[30:150, x:x + 90] = 220
        p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()
    tl = {'total': END, 'cuts': [4.0],
          'holds': [{'id': 'A', 't0': 0.0, 't1': 4.0, 'hold': 0.6}, {'id': 'B', 't0': 4.0, 't1': 8.0, 'hold': 0.6}],
          'shots': [], 'seams': [{'id': 'A→B', 'cut': 4.0, 'type': 'cut', 'exit': {'axis': 'x', 'dir': -1}, 'entry': {'axis': 'x', 'dir': -1}}]}
    json.dump(tl, open(os.path.join(tmp, 'out', 'timeline.json'), 'w'))
    sb = ('---\ntitle: t\nversion: 1\nduration: 8s\nmessage: "m"\n---\n## Locked\n- yes\n\n## Beat 01 — A (0.0–4.0, ~4.0 s)\n- real: recreated\n- vo: x\n'
          '## Beat 02 — B (4.0–8.0, ~4.0 s)\n- real: recreated\n- vo: y\n')
    open(os.path.join(tmp, 'STORYBOARD.md'), 'w', encoding='utf-8').write(sb)
    ctx = {'film': film, 'fps': fps, 'dur': END, 'timeline': tl, 'project': tmp, 'cfg': {}, 'qa': {}}
    fails = 0

    def check(name, cond, detail=''):
        nonlocal fails
        print('  %s %s  %s' % ('PASS' if cond else 'FAIL', name, str(detail)[:200]))
        if not cond:
            fails += 1
    cfg = _cfg({})
    mA, mB = measure(film, tl['holds'][0], cfg), measure(film, tl['holds'][1], cfg)
    check('A: moved first (max %.2f%%), hold under the background allowance (max %.2f%%)' % (mA['move_max'], mA['hold_max'][1]), mA['ok'] and mA['moved'])
    check('B: motion inside the hold is caught (%.2f%% at %.2f s)' % (mB['hold_max'][1], mB['hold_max'][0]), not mB['ok'] and mB['moved'])
    out = {n: (ok, d) for n, ok, d in run(ctx)}
    check('run(): hold declared PASS on the consistent plan', out['hold declared'][0], out['hold declared'][1])
    check('run(): hold still FAILs on B only', not out['hold still'][0] and 'B:' in out['hold still'][1] and 'A:' not in out['hold still'][1], out['hold still'][1])
    # the plan rules
    beats = [(1, 0.0, 4.0, 'recreated', ''), (2, 4.0, 8.0, 'recreated', ''), (3, 8.0, 10.0, 'recorded', '')]
    E, _ = check_plan([tl['holds'][0]], beats, tl['seams'], cfg)
    check('a recreated beat without a hold row fails', any('beat 02' in e and 'no hold' in e for e in E), E)
    E, N2 = check_plan([tl['holds'][0]], [(1, 0.0, 4.0, 'recreated', ''), (2, 4.0, 8.0, 'recreated', 'none (every word lands on its cue up to the cut)')], tl['seams'], cfg)
    check('a written waiver turns the FAIL into a visible WARN', not E and any('waives its hold: every word lands' in n for n in N2), N2)
    E, _ = check_plan([{'id': 'clip', 't0': 0.0, 't1': 4.0, 'hold': 0.6, 'footage': True}], [], tl['seams'], cfg)
    check('a footage hold ending on a vector seam is forbidden', any('forbidden' in e for e in E), E)
    E, _ = check_plan([{'id': 'clip', 't0': 0.0, 't1': 4.0, 'hold': 0.6, 'footage': True}], [], [{'id': 'g', 'cut': 4.0, 'type': 'gl', 'technique': 'lightLeak'}], cfg)
    check('a footage hold ending on a gl row is allowed', not E, E)
    E, _ = check_plan([{'id': 'x', 't0': 0.0, 't1': 4.0, 'hold': 0.1}, {'id': 'y', 't0': 4.0, 't1': 8.0, 'hold': 1.0}], [], [], cfg)
    check('hold outside 0.3–0.95 fails', len(E) == 2, E)
    ctx2 = {'film': film, 'fps': fps, 'dur': END, 'timeline': {'total': END, 'shots': [{'clip': 'a', 't0': 0.0, 't1': 4.0, 'hold': 0.6}]}, 'project': tmp, 'cfg': {}, 'qa': {}}
    check('shots[].hold rides into the rows; hold_ends() = [4.0]', hold_ends(ctx2) == [4.0] and load_holds(ctx2)[0].get('footage'))
    ctx3 = {'film': film, 'fps': fps, 'dur': END, 'timeline': {'total': END}, 'project': tempfile.mkdtemp(prefix='hold_empty_'), 'cfg': {}, 'qa': {}}
    r3 = {n: (ok, d) for n, ok, d in run(ctx3)}
    check('no holds, no recreated beats: both gates pass with a note', r3['hold declared'][0] and r3['hold still'][0])
    shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(ctx3['project'], ignore_errors=True)
    print('\n%s  (%d failed)' % ('SELFTEST PASS' if not fails else 'SELFTEST FAILED', fails))
    return fails


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if not a or a[0] == '--selftest':
        sys.exit(1 if selftest() else 0)
    proj = os.path.abspath(a[0])
    tlp = os.path.join(proj, 'out', 'timeline.json')
    cfg = json.load(open(os.path.join(proj, 'film.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'film.json')) else {}
    film = a[1] if len(a) > 1 else os.path.join(proj, cfg.get('output', 'out/%s.mp4' % cfg.get('name', 'film')))
    qa = json.load(open(os.path.join(proj, 'qa.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'qa.json')) else {}
    ctx = {'film': film, 'fps': 30, 'timeline': json.load(open(tlp, encoding='utf-8')) if os.path.exists(tlp) else {}, 'project': proj, 'cfg': cfg, 'qa': qa}
    bad = 0
    for name, ok, d in run(ctx):
        print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', d)); bad += 0 if ok else 1
    sys.exit(1 if bad else 0)
