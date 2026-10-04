# -*- coding: utf-8 -*-
"""spec_gate.py — a shot's own contract: what it may never show, what it must trace, what it borrows.  (qa_film.py plug-in)

shots.js, per shot:
    { t0, t1, clip: 'answer', spec: { forbidden: ['Beta', 'TODO', 'lorem'], claims: ['regions_over_target'], references: ['Study A'] } }
export_timeline.js writes `spec` into out/timeline.json → shots[].spec. The gate reads the rendered film:

  spec forbidden   frames at t0 + 0.5 s, the midpoint and t1 − 0.5 s of every shot with a `forbidden` list are OCR'd (the leak
                   gate's engine); a forbidden token on any of them FAILS with the shot, the time and the word. Case-insensitive,
                   whole word, OCR confusions tolerated (l/1/I, O/0). Without an engine: PASS with a WARN.
  spec claims      every id or phrase in `claims` resolves in claims.json (by `id`, or verbatim `phrase`) — a shot that promises
                   a figure the film never traced FAILS.
  spec references  every name in `references` is a logged title in refs.json (tools/ref_study.py) — WARN only; a reference the
                   study never saw is a note, not a failure.

    python gates/spec_gate.py --selftest        synthetic frames + a stub OCR backend (no browser, no engine)
    python gates/spec_gate.py <project> [film]
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_NAMES = ['spec forbidden', 'spec claims', 'spec references']
CONFUSE = {'l': '[l1I|]', '1': '[l1I|]', 'i': '[iI1l]', 'o': '[oO0]', '0': '[oO0]', 's': '[sS5]', '5': '[sS5]'}


def _pattern(token):
    return re.compile(r'(?<!\w)' + ''.join(CONFUSE.get(ch.lower(), re.escape(ch)) for ch in token) + r'(?!\w)', re.I)


def frame_at(film, t, path):
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', '%.3f' % max(0.0, t), '-i', film, '-frames:v', '1', '-q:v', '3', path], capture_output=True)
    return r.returncode == 0 and os.path.exists(path)


def ocr_text(backend, path):
    from PIL import Image
    sys.path.insert(0, HERE)
    import leak_gate as LG
    return ' '.join(ln.get('text', '') for ln in LG.ocr_image(backend, Image.open(path).convert('RGB'), 1920))


def times_for(shot):
    t0, t1 = float(shot['t0']), float(shot['t1'])
    if t1 - t0 < 1.2:
        return [round((t0 + t1) / 2, 3)]
    return [round(t0 + 0.5, 3), round((t0 + t1) / 2, 3), round(t1 - 0.5, 3)]


def check_forbidden(film, shots, backend, work_dir, ocr=ocr_text):
    """[(shot, t, token)] forbidden tokens read on the shot's frames."""
    os.makedirs(work_dir, exist_ok=True)
    hits = []
    for s in shots:
        forb = (s.get('spec') or {}).get('forbidden') or []
        if not forb or s.get('t1') is None:
            continue
        pats = [(tok, _pattern(str(tok))) for tok in forb]
        for t in times_for(s):
            p = os.path.join(work_dir, 'spec_%s_%.2f.jpg' % (re.sub(r'\W+', '_', str(s.get('clip', 'shot'))), t))
            if not frame_at(film, t, p):
                continue
            text = ocr(backend, p)
            for tok, pat in pats:
                if pat.search(text):
                    hits.append((s.get('clip', 'shot'), t, tok))
    return hits


def check_claims(shots, claims_doc):
    ids = {str(c.get('id')) for c in (claims_doc or {}).get('claims', []) if c.get('id')}
    phrases = {' '.join(str(c.get('phrase', '')).lower().split()) for c in (claims_doc or {}).get('claims', [])}
    figs = {str(f.get('id')) for f in (claims_doc or {}).get('figures', []) if f.get('id')}
    bad = []
    for s in shots:
        for c in (s.get('spec') or {}).get('claims') or []:
            k = str(c)
            if k not in ids and k not in figs and ' '.join(k.lower().split()) not in phrases:
                bad.append((s.get('clip', 'shot'), k))
    return bad


def check_references(shots, refs_doc):
    titles = {str(r.get('title', '')).lower() for r in (refs_doc or {}).get('refs', [])}
    bad = []
    for s in shots:
        for r in (s.get('spec') or {}).get('references') or []:
            if str(r).lower() not in titles:
                bad.append((s.get('clip', 'shot'), str(r)))
    return bad


def run(ctx, backend='auto'):
    project = ctx.get('project') or '.'
    shots = [s for s in (ctx.get('timeline') or {}).get('shots', []) if isinstance(s.get('spec'), dict)]
    if not shots:
        return [(n, True, 'no shot carries a spec{} (optional: shots.js spec: {forbidden, claims, references})') for n in GATE_NAMES]
    res = []
    film = ctx.get('film')
    if any((s['spec'].get('forbidden') or []) for s in shots):
        be, note = backend, ''
        if isinstance(backend, str):
            sys.path.insert(0, HERE)
            import leak_gate as LG
            be, note = LG.pick_backend(backend, fastest=True)
        if be is None:
            res.append(('spec forbidden', True, 'WARN no OCR engine — forbidden tokens not read (%s)' % note[:80]))
        elif not film or not os.path.exists(film):
            res.append(('spec forbidden', False, 'film not found'))
        else:
            hits = check_forbidden(film, shots, be, os.path.join(project, 'out', 'qa', 'spec'))
            res.append(('spec forbidden', not hits, '; '.join('%s @%.2f shows "%s"' % h for h in hits)[:300] if hits else '%d shot(s) read clean (%s)' % (sum(1 for s in shots if s['spec'].get('forbidden')), getattr(be, 'name', 'ocr'))))
    else:
        res.append(('spec forbidden', True, 'no forbidden lists'))
    cp = ctx.get('claims_json') or os.path.join(project, 'claims.json')
    claims = json.load(open(cp, encoding='utf-8')) if cp and os.path.exists(cp) else None
    bad = check_claims(shots, claims)
    res.append(('spec claims', not bad, '; '.join('%s promises "%s" — not in claims.json' % b for b in bad)[:300] if bad else '%d shot claim(s) traced' % sum(len(s['spec'].get('claims') or []) for s in shots)))
    rp = os.path.join(project, 'refs.json')
    refs = json.load(open(rp, encoding='utf-8')) if os.path.exists(rp) else None
    badr = check_references(shots, refs)
    res.append(('spec references', True, ('WARN %s' % '; '.join('%s borrows from "%s" — not logged in refs.json' % b for b in badr)[:250]) if badr else '%d reference(s) logged' % sum(len(s['spec'].get('references') or []) for s in shots)))
    return res


# ---------------------------------------------------------------- selftest
class _Stub(object):
    name, upscale = 'stub', 1

    def __init__(self, by_time):
        self.by_time = by_time

    def recognize(self, im):
        return []


def selftest():
    import tempfile, shutil
    import numpy as np
    d = tempfile.mkdtemp(prefix='spec_gate_')
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    film = os.path.join(d, 'f.mp4')
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '160x90', '-r', '30', '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', film], stdin=subprocess.PIPE)
    for k in range(180):
        f = np.full((90, 160), 20 + (k // 90) * 100, np.uint8); p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()
    shots = [{'clip': 'a', 't0': 0.0, 't1': 3.0, 'spec': {'forbidden': ['Beta', 'lorem'], 'claims': ['regions_over_target', 'three regions'], 'references': ['Study A']}},
             {'clip': 'b', 't0': 3.0, 't1': 6.0, 'spec': {'forbidden': ['TODO'], 'claims': ['made_up'], 'references': ['Study Z']}}]
    read = {('a', 0.5): 'Which regions missed the target', ('a', 1.5): 'the answer card BETA build', ('a', 2.5): 'ok', ('b', 3.5): 'T0DO fix me', ('b', 4.5): '', ('b', 5.5): ''}
    stub = _Stub(read)
    fake = lambda be, path: read.get((re.search(r'spec_(\w+)_([\d.]+)\.jpg$', path).group(1), float(re.search(r'spec_(\w+)_([\d.]+)\.jpg$', path).group(2))), '')
    hits = check_forbidden(film, shots, stub, os.path.join(d, 'work'), ocr=fake)
    t(hits == [('a', 1.5, 'Beta'), ('b', 3.5, 'TODO')], 'forbidden tokens read on the frames (case and OCR confusions tolerated): %s' % hits)
    t(times_for({'t0': 0, 't1': 3}) == [0.5, 1.5, 2.5] and times_for({'t0': 0, 't1': 1}) == [0.5], 'three frames per shot, one for a short shot')
    claims = {'claims': [{'id': 'c1', 'phrase': 'Three regions', 'source': 'x'}], 'figures': [{'id': 'regions_over_target'}]}
    bad = check_claims(shots, claims)
    t(bad == [('b', 'made_up')], 'claims: a figure id or a verbatim phrase resolves, an invented one fails (%s)' % bad)
    t(check_references(shots, {'refs': [{'title': 'Study A'}]}) == [('b', 'Study Z')], 'references: an unlogged study is listed')
    R = {n: (o, dd) for n, o, dd in run({'project': d, 'film': film, 'timeline': {'shots': shots}, 'claims_json': None}, backend=None)}
    t(R['spec forbidden'][0] and 'WARN no OCR' in R['spec forbidden'][1] and not R['spec claims'][0] and R['spec references'][0] and 'WARN' in R['spec references'][1], 'run(): no engine → forbidden WARN-pass; claims FAIL on made_up; references WARN')
    R2 = {n: (o, dd) for n, o, dd in run({'project': d, 'film': film, 'timeline': {'shots': []}})}
    t(all(v[0] for v in R2.values()), 'no spec anywhere → all pass with a note')
    shutil.rmtree(d, ignore_errors=True)
    print('spec_gate selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if '--selftest' in sys.argv or not a:
        sys.exit(selftest())
    proj = os.path.abspath(a[0])
    cfg = json.load(open(os.path.join(proj, 'film.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'film.json')) else {}
    film = a[1] if len(a) > 1 else os.path.join(proj, cfg.get('output', 'out/%s.mp4' % cfg.get('name', 'film')))
    tl = json.load(open(os.path.join(proj, 'out', 'timeline.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'out', 'timeline.json')) else {}
    bad = 0
    for name, ok, dd in run({'project': proj, 'film': film, 'timeline': tl}):
        print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', dd)); bad += 0 if ok else 1
    sys.exit(1 if bad else 0)
