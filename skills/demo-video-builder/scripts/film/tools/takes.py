# -*- coding: utf-8 -*-
"""takes.py — the per-take ledger: what every build cost, what it rendered, and whether its gates passed.

    python tools/takes.py list      [--project DIR]            one line per take: when, wall s, frames, workers, gl, gates, what changed
    python tools/takes.py time      [--project DIR]            time per take (our cost): last, median, total; frames per second of wall time
    python tools/takes.py annotate  [--project DIR]            fill the latest take's gates from out/qa_report.json
    python tools/takes.py keep      [--project DIR]            copy the latest take's scene + film + reports into .history/takes/<take>/
    python tools/takes.py prune     --after-lock [--keep 1]    delete retained takes once STORYBOARD.md carries the sign-off
    python tools/takes.py --selftest

build_film.py appends one record per build to out/takes.jsonl:
  {take, when, scene_md5, wall_s, frames, workers, gl, gl_renderer, film, gates: {pass, fail, failed: [...]} | null}
and retains the take (`keep`): scenes/film.html, scenes/shots.js, out/timeline.json, the film and out/qa_report.json
under .history/takes/<take>/. Every take is kept until the review is locked (tools/review_pack.py --lock writes
`signed off by` into ## Locked); `prune --after-lock` then removes all but the newest --keep takes and refuses while
the plan is unsigned. scene_md5 is the md5 of the scene html + shots.js: two takes with the same hash rendered the
same picture, so a changed hash beside a gate flip says which edit did it.
Stdlib only.
"""
import argparse, datetime, hashlib, json, os, re, shutil, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RETAIN = ('scenes/film.html', 'scenes/shots.js', 'out/timeline.json', 'out/qa_report.json')


def scene_md5(project, scene='scenes/film.html', shots='scenes/shots.js'):
    h = hashlib.md5()
    for rel in (scene, shots):
        p = os.path.join(project, rel.split('?')[0])
        if os.path.exists(p):
            h.update(open(p, 'rb').read())
    return h.hexdigest()[:12]


def read(project):
    p = os.path.join(project, 'out', 'takes.jsonl')
    out = []
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8'):
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    return out


def gates_from_report(project):
    p = os.path.join(project, 'out', 'qa_report.json')
    try:
        d = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return None
    g = d.get('gates', [])
    return {'pass': sum(1 for x in g if x.get('ok')), 'fail': sum(1 for x in g if not x.get('ok')), 'failed': [x.get('name') for x in g if not x.get('ok')], 'profile': d.get('profile')}


def record(project, wall_s, frames, workers, gl=None, gl_renderer=None, film=None, scene='scenes/film.html', shots='scenes/shots.js', when=None):
    """Append one take (build_film.py calls this at the end of a build). Returns the record."""
    takes = read(project)
    rec = {'take': (takes[-1]['take'] + 1) if takes else 1, 'when': when or datetime.datetime.now().isoformat(timespec='seconds'),
           'scene_md5': scene_md5(project, scene, shots), 'wall_s': round(float(wall_s), 1), 'frames': int(frames), 'workers': int(workers),
           'gl': gl, 'gl_renderer': gl_renderer, 'film': film, 'gates': None}
    os.makedirs(os.path.join(project, 'out'), exist_ok=True)
    with open(os.path.join(project, 'out', 'takes.jsonl'), 'a', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def annotate(project):
    """Fill the newest take's gates from out/qa_report.json (QA runs after the build)."""
    takes = read(project)
    if not takes:
        return None
    g = gates_from_report(project)
    if g is None:
        return None
    takes[-1]['gates'] = g
    with open(os.path.join(project, 'out', 'takes.jsonl'), 'w', encoding='utf-8', newline='\n') as fh:
        for r in takes:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    return takes[-1]


def keep(project, take=None, film=None):
    """Retain a take under .history/takes/<take>/ (scene, shots, timeline, qa report, the film). Returns the directory."""
    takes = read(project)
    if not takes:
        return None
    rec = takes[-1] if take is None else next((r for r in takes if r['take'] == take), None)
    if rec is None:
        return None
    d = os.path.join(project, '.history', 'takes', '%03d' % rec['take'])
    os.makedirs(d, exist_ok=True)
    for rel in list(RETAIN) + [film or rec.get('film') or '']:
        if not rel:
            continue
        src = os.path.join(project, rel)
        if os.path.exists(src):
            dst = os.path.join(d, rel.replace('/', os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    json.dump(rec, open(os.path.join(d, 'take.json'), 'w', encoding='utf-8'), indent=1)
    return d


def locked(project, storyboard='STORYBOARD.md'):
    """True when STORYBOARD.md's ## Locked section carries `signed off by` (tools/review_pack.py --lock)."""
    p = os.path.join(project, storyboard)
    if not os.path.exists(p):
        return False
    m = re.search(r'^##\s+Locked\b(.*?)(?=^##\s|\Z)', open(p, encoding='utf-8').read(), re.S | re.M | re.I)
    return bool(m and re.search(r'^\s*-\s*signed off by:\s*\S', m.group(1), re.M | re.I))


def prune(project, after_lock=True, keep_n=1):
    """Delete retained takes (oldest first) once the plan is signed off. Returns (removed, kept, message)."""
    root = os.path.join(project, '.history', 'takes')
    dirs = sorted(d for d in (os.listdir(root) if os.path.isdir(root) else []) if re.fullmatch(r'\d{3}', d))
    if after_lock and not locked(project):
        return [], dirs, 'refused: STORYBOARD.md is not signed off — every take is kept until review_pack.py --lock'
    victims = dirs[:max(0, len(dirs) - max(0, keep_n))]
    for d in victims:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    return victims, dirs[len(victims):], 'pruned %d take(s), kept %d' % (len(victims), len(dirs) - len(victims))


def table(takes):
    L = ['take  when                 wall s  frames  w  gl        gates          scene']
    prev = None
    for r in takes:
        g = r.get('gates')
        gs = ('%d/%d%s' % (g['pass'], g['pass'] + g['fail'], (' FAIL ' + ','.join(g['failed'][:2])) if g['fail'] else '')) if g else 'not run'
        ch = '' if prev is None else ('same' if prev == r['scene_md5'] else 'CHANGED')
        L.append('%4d  %-19s %7.1f %7d %2d  %-9s %-14s %s %s' % (r['take'], r['when'][:19], r['wall_s'], r['frames'], r['workers'], (r.get('gl') or '?')[:9], gs[:14], r['scene_md5'], ch))
        prev = r['scene_md5']
    return '\n'.join(L)


def cost(takes):
    if not takes:
        return None
    w = sorted(r['wall_s'] for r in takes)
    med = w[len(w) // 2]
    last = takes[-1]
    return {'takes': len(takes), 'last_s': last['wall_s'], 'median_s': med, 'total_s': round(sum(w), 1),
            'fps_wall': round(last['frames'] / last['wall_s'], 2) if last['wall_s'] else None}


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    import tempfile
    d = tempfile.mkdtemp(prefix='takes_')
    os.makedirs(os.path.join(d, 'scenes')); os.makedirs(os.path.join(d, 'out'))
    open(os.path.join(d, 'scenes', 'film.html'), 'w').write('<html>a</html>'); open(os.path.join(d, 'scenes', 'shots.js'), 'w').write('SHOTS=[]')
    open(os.path.join(d, 'out', 'film.mp4'), 'wb').write(b'\x00' * 64)
    json.dump({'total': 3}, open(os.path.join(d, 'out', 'timeline.json'), 'w'))
    open(os.path.join(d, 'STORYBOARD.md'), 'w').write('---\ntitle: t\n---\n## Locked\n- beat order\n')
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    r1 = record(d, 61.2, 1170, 3, 'software', 'ANGLE (software)', 'out/film.mp4', when='2026-01-01T09:00:00')
    k1 = keep(d)
    json.dump({'gates': [{'name': 'a', 'ok': True}, {'name': 'hold still', 'ok': False}]}, open(os.path.join(d, 'out', 'qa_report.json'), 'w'))
    a1 = annotate(d)
    open(os.path.join(d, 'scenes', 'shots.js'), 'w').write('SHOTS=[1]')
    r2 = record(d, 58.0, 1170, 3, 'software', 'ANGLE (software)', 'out/film.mp4', when='2026-01-01T09:05:00')
    k2 = keep(d)
    T = read(d)
    t(r1['take'] == 1 and r2['take'] == 2 and T[0]['gates']['fail'] == 1 and T[0]['gates']['failed'] == ['hold still'] and T[1]['gates'] is None, 'record + annotate: two takes, the first carries its gates from qa_report.json')
    t(T[0]['scene_md5'] != T[1]['scene_md5'] and 'CHANGED' in table(T), 'scene_md5 changes when shots.js changes (table says CHANGED)')
    t(os.path.exists(os.path.join(k1, 'scenes', 'film.html')) and os.path.exists(os.path.join(k1, 'out', 'film.mp4')) and os.path.exists(os.path.join(k2, 'take.json')), 'keep: .history/takes/001 and 002 retain scene, film, reports')
    c = cost(T)
    t(c['takes'] == 2 and c['last_s'] == 58.0 and c['median_s'] == 61.2 and c['total_s'] == 119.2 and c['fps_wall'] > 20, 'time per take: last / median / total / frames per wall second (%s)' % c)
    rem, kept, msg = prune(d)
    t(rem == [] and 'refused' in msg and len(kept) == 2, 'prune --after-lock refuses while the plan is unsigned')
    with open(os.path.join(d, 'STORYBOARD.md'), 'a') as fh:
        fh.write('- signed off by: Reviewer\n- signed off date: 2026-01-02\n')
    rem, kept, msg = prune(d, keep_n=1)
    t(rem == ['001'] and kept == ['002'] and not os.path.exists(k1) and os.path.exists(k2), 'prune after the lock removes the older take, keeps the newest')
    shutil.rmtree(d, ignore_errors=True)
    print('takes selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='takes.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['list', 'time', 'annotate', 'keep', 'prune'])
    ap.add_argument('--project', default=os.getcwd()); ap.add_argument('--after-lock', action='store_true'); ap.add_argument('--keep', type=int, default=1)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    P = os.path.abspath(a.project)
    T = read(P)
    if a.cmd == 'list':
        print(table(T) if T else 'no takes yet (out/takes.jsonl is written by build_film.py)'); return 0
    if a.cmd == 'time':
        c = cost(T)
        if not c:
            print('no takes yet'); return 0
        print(json.dumps(c) if a.json else '%d takes — last %.1f s, median %.1f s, total %.1f s (%.1f min); %.1f frames per wall second' % (c['takes'], c['last_s'], c['median_s'], c['total_s'], c['total_s'] / 60, c['fps_wall'] or 0)); return 0
    if a.cmd == 'annotate':
        r = annotate(P); print('take %d gates: %s' % (r['take'], r['gates']) if r else 'nothing to annotate (no takes or no out/qa_report.json)'); return 0
    if a.cmd == 'keep':
        k = keep(P); print('kept → %s' % k if k else 'no take to keep'); return 0
    if a.cmd == 'prune':
        if not a.after_lock:
            print('prune needs --after-lock (takes are kept until the review is signed off)', file=sys.stderr); return 2
        rem, kept, msg = prune(P, True, a.keep); print(msg); return 1 if 'refused' in msg else 0


if __name__ == '__main__':
    sys.exit(main())
