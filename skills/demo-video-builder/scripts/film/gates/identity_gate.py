# -*- coding: utf-8 -*-
"""identity_gate.py — version N+1 from version N: the shots you did not touch are provably the same picture.  (qa_film.py plug-in)

When a cut list is bumped by text replacement (tools/cutlist.py bump v3 v4 --replace 'send=send_b'), only the rows
whose text changed may render differently. This gate takes the previous render and the new one, the shot spans from
out/timeline.json and the list of changed clips (out/cutlist_bump.json, or qa.json "identity": {"previous": …,
"changed": [...]}) and asserts, for every UNTOUCHED shot:

  identity frames   both renders carry the same number of frames inside the shot span (10 fps sampling of the span
                    plus a frame-count probe on each file: a shot that grew or shrank fails)
  identity colour   per sampled frame, the mean colour of the two renders differs by ≤ 0.5 ΔE (CIE76 on the mean
                    sRGB → Lab) — codec noise on a 1080p frame sits around 0.1; a changed element moves it past 1

Changed shots are reported, not judged (that is what the bump was for). Without a previous render or a bump record
the gate passes with a note.

    python gates/identity_gate.py --selftest                       two synthetic ffmpeg clips, one shot changed
    python gates/identity_gate.py <project> <previous.mp4> [<current.mp4>] [--changed clip,clip]
"""
import json, os, subprocess, sys

import numpy as np

GATE_NAMES = ['identity frames', 'identity colour']
DE_MAX, FPS_SAMPLE = 0.5, 10


def _rgb_means(film, t0, dur, fps=FPS_SAMPLE):
    """mean RGB per sampled frame inside [t0, t0+dur) → (N, 3) float."""
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t0, '-i', film, '-t', '%.3f' % dur,
                          '-vf', 'fps=%d,scale=64:36:flags=area' % fps, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    n = len(raw) // (64 * 36 * 3)
    fr = np.frombuffer(raw[:n * 64 * 36 * 3], dtype=np.uint8).reshape(n, 36, 64, 3).astype(np.float32)
    return fr.mean(axis=(1, 2))


def frame_count(film):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', film], capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def srgb_to_lab(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    return np.stack([L, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def delta_e(a, b):
    return float(np.sqrt(((srgb_to_lab(a) - srgb_to_lab(b)) ** 2).sum(axis=-1)).max()) if len(a) and len(b) else 0.0


def compare(prev, cur, shots, changed, de_max=DE_MAX):
    """shots: [{clip, t0, t1}] ; changed: set of clip names. → {frames_ok, colour_ok, rows, detail}"""
    rows, fbad, cbad = [], [], []
    nprev, ncur = frame_count(prev), frame_count(cur)
    for s in shots:
        if s.get('t0') is None or s.get('t1') is None:
            continue
        dur = float(s['t1']) - float(s['t0'])
        if dur <= 0:
            continue
        a, b = _rgb_means(prev, float(s['t0']), dur), _rgb_means(cur, float(s['t0']), dur)
        row = {'clip': s.get('clip'), 'changed': s.get('clip') in changed, 'frames': (len(a), len(b)), 'de': round(delta_e(a[:min(len(a), len(b))], b[:min(len(a), len(b))]), 3)}
        rows.append(row)
        if row['changed']:
            continue
        if len(a) != len(b):
            fbad.append('%s: %d vs %d sampled frames' % (row['clip'], len(a), len(b)))
        if row['de'] > de_max:
            cbad.append('%s: ΔE %.2f (limit %g)' % (row['clip'], row['de'], de_max))
    if nprev != ncur:
        fbad.append('film: %d vs %d frames' % (nprev, ncur))
    return {'frames_ok': not fbad, 'colour_ok': not cbad, 'rows': rows, 'frames_bad': fbad, 'colour_bad': cbad, 'counts': (nprev, ncur)}


def load_bump(project):
    p = os.path.join(project, 'out', 'cutlist_bump.json')
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None


def run(ctx):
    project = ctx.get('project') or '.'
    q = (ctx.get('qa') or {}).get('identity') or {}
    bump = load_bump(project) or {}
    prev = q.get('previous') or bump.get('previous_film')
    changed = set(q.get('changed') or bump.get('changed') or [])
    if not prev or not os.path.exists(os.path.join(project, prev) if not os.path.isabs(prev) else prev):
        return [(n, True, 'no previous render to compare (qa.json identity.previous or out/cutlist_bump.json)') for n in GATE_NAMES]
    prev = os.path.join(project, prev) if not os.path.isabs(prev) else prev
    shots = (ctx.get('timeline') or {}).get('shots', [])
    if not shots:
        return [(n, True, 'no shots in out/timeline.json') for n in GATE_NAMES]
    R = compare(prev, ctx['film'], shots, changed, float(q.get('de_max', DE_MAX)))
    un = [r for r in R['rows'] if not r['changed']]
    return [('identity frames', R['frames_ok'], '; '.join(R['frames_bad'])[:300] if not R['frames_ok'] else '%d untouched shots keep their frame count (%d changed: %s)' % (len(un), len(changed), ', '.join(sorted(changed)) or '—')),
            ('identity colour', R['colour_ok'], '; '.join(R['colour_bad'])[:300] if not R['colour_ok'] else 'max ΔE %.2f over %d untouched shots' % (max([r['de'] for r in un] or [0.0]), len(un)))]


# ---------------------------------------------------------------- selftest
def _clip(path, tones, fps=30, dur=2.0, mark=None):
    """3 shots of `dur` s at 160x90, flat tones with a block; `mark` = (shot index, extra width) changes the block in one shot."""
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x90', '-r', str(fps), '-i', '-',
                          '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', path], stdin=subprocess.PIPE)
    for k in range(int(len(tones) * dur * fps)):
        i = int(k / fps / dur)
        f = np.zeros((90, 160, 3), np.uint8); f[:] = tones[i]
        w = 60 + (mark[1] if mark and mark[0] == i else 0)          # the changed shot shows a wider, brighter block
        f[30:60, 40:40 + w] = (250, 200, 40) if (mark and mark[0] == i) else (230, 120, 40)
        p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()


def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix='identity_')
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    tones = [(20, 40, 60), (200, 200, 200), (90, 30, 30)]
    a, b, c = (os.path.join(d, n) for n in ('v3.mp4', 'v4.mp4', 'v5.mp4'))
    _clip(a, tones); _clip(b, tones, mark=(1, 50)); _clip(c, tones, dur=2.0)
    shots = [{'clip': 'open', 't0': 0.0, 't1': 2.0}, {'clip': 'send', 't0': 2.0, 't1': 4.0}, {'clip': 'close', 't0': 4.0, 't1': 6.0}]
    R = compare(a, b, shots, {'send'})
    t(R['frames_ok'] and R['colour_ok'] and R['rows'][1]['changed'] and R['rows'][1]['de'] > 1.0 and max(r['de'] for r in R['rows'] if not r['changed']) < 0.5,
      'v3 → v4 with "send" declared changed: untouched shots identical (max ΔE %.2f), the changed one moved (ΔE %.2f)' % (max(r['de'] for r in R['rows'] if not r['changed']), R['rows'][1]['de']))
    R2 = compare(a, b, shots, set())
    t(not R2['colour_ok'] and 'send' in R2['colour_bad'][0], 'the same change undeclared fails identity colour (%s)' % R2['colour_bad'][0])
    R3 = compare(a, c, shots, set())
    t(R3['frames_ok'] and R3['colour_ok'], 'two renders of the same list are identical (%d frames)' % R3['counts'][0])
    # a shorter render fails on frames
    _clip(c, tones, dur=1.8)
    R4 = compare(a, c, [{'clip': 'open', 't0': 0.0, 't1': 2.0}, {'clip': 'close', 't0': 3.6, 't1': 5.4}], set())
    t(not R4['frames_ok'] and any('film:' in x for x in R4['frames_bad']), 'a render with a different frame count fails identity frames (%s)' % R4['frames_bad'][-1])
    os.makedirs(os.path.join(d, 'out'))
    json.dump({'previous_film': 'v3.mp4', 'changed': ['send']}, open(os.path.join(d, 'out', 'cutlist_bump.json'), 'w'))
    G = {n: (o, dd) for n, o, dd in run({'project': d, 'film': b, 'qa': {}, 'timeline': {'shots': shots}})}
    t(G['identity frames'][0] and G['identity colour'][0] and 'send' in G['identity frames'][1], 'run(): reads out/cutlist_bump.json (%s)' % G['identity frames'][1])
    G2 = {n: (o, dd) for n, o, dd in run({'project': d, 'film': b, 'qa': {'identity': {'previous': 'nope.mp4'}}, 'timeline': {'shots': shots}})}
    t(G2['identity frames'][0] and 'no previous' in G2['identity frames'][1], 'run(): no previous render → pass with a note')
    shutil.rmtree(d, ignore_errors=True)
    print('identity_gate selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if '--selftest' in sys.argv or len(a) < 2:
        sys.exit(selftest())
    proj = os.path.abspath(a[0]); prev = a[1]
    cfg = json.load(open(os.path.join(proj, 'film.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'film.json')) else {}
    cur = a[2] if len(a) > 2 else os.path.join(proj, cfg.get('output', 'out/%s.mp4' % cfg.get('name', 'film')))
    changed = []
    if '--changed' in sys.argv:
        changed = sys.argv[sys.argv.index('--changed') + 1].split(',')
    tl = json.load(open(os.path.join(proj, 'out', 'timeline.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'out', 'timeline.json')) else {}
    bad = 0
    for name, ok, dd in run({'project': proj, 'film': cur, 'qa': {'identity': {'previous': prev, 'changed': changed}}, 'timeline': tl}):
        print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', dd)); bad += 0 if ok else 1
    sys.exit(1 if bad else 0)
