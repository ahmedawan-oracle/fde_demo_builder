# -*- coding: utf-8 -*-
"""ledger_gate.py — QA gates for media provenance (v4, media area). Loaded by qa_film.py via gates/*.py.

    media ledger    every asset the film mixes in or draws from has a CURRENT record in media.jsonl: the bed and sfx
                    named in film.json, the assembled narration vo_<name>.mp3, every broll/<clip>/ folder and source
                    recording in clips.json, every local @font-face / <img>/<video> file the scene loads. A record
                    whose sha256 no longer matches the file is "stale" (re-add it; never hand-edit the ledger).
    licences        every music / sfx / font / image record carries a licence that is not UNKNOWN and does not refuse
                    commercial use (a booth is commercial use). Footage ("Own recording") and voice (edge-tts) pass.
    no remote refs  the authored scene, shots and scenes/lib/*.js load nothing over the network: no http(s):// or
                    protocol-relative // inside src= / href= / url( / @import / fetch( / import( (comments stripped,
                    so a licence URL in a comment is fine). A render on a booth laptop without network must not differ.
    frozen local    every relative file the scene references resolves to an existing file INSIDE the project.
    credit font     at least one font credit.py can draw the mandatory end-screen credit with exists on this machine.

A project without a ledger: `media ledger` and `licences` still pass when nothing licensable is referenced (no bed, no
sfx, no local fonts/images) so the shipped sample keeps passing, with the detail telling you to run
`python tools/ledger.py adopt` to record footage and voice provenance. The moment a bed or sfx is configured, the ledger
becomes mandatory.

    python gates/ledger_gate.py --selftest
"""
import importlib, json, os, re, sys

GATE_NAMES = ['media ledger', 'licences', 'no remote refs', 'frozen local', 'credit font']

HERE = os.path.dirname(os.path.abspath(__file__))
# http(s) or protocol-relative URLs where the scene would load something: attributes, CSS url(), @import, fetch/import()
REMOTE_RE = re.compile(r"""(?:\b(?:src|href|poster|data-src)\s*=\s*["']?\s*(?:https?:)?//[^\s"'>]+)"""
                       r"""|(?:url\(\s*["']?\s*(?:https?:)?//[^)"']+)"""
                       r"""|(?:@import\s+(?:url\()?\s*["']?\s*(?:https?:)?//[^\s"')]+)"""
                       r"""|(?:\b(?:fetch|import)\(\s*["'](?:https?:)?//[^"']+)""", re.I)
LOCAL_REF_RE = re.compile(r"""(?:\b(?:src|href|poster)\s*=\s*["']([^"'<>:]+?)["'])|(?:url\(\s*["']?([^)"':]+?)["']?\s*\))""", re.I)
FONT_FACE_RE = re.compile(r'@font-face\s*\{[^}]*\}', re.I | re.S)


def _strip_comments(s):
    s = re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S)
    return re.sub(r'''(?m)(?<![:\w"'(])//[^\n]*''', ' ', s)           # keep '://' and url(//cdn…) refs inside strings


def _ledger_module(project):
    """tools/ledger.py from the project (scaffolded copy) or from the plugin tree beside this gate."""
    for d in (os.path.join(project, 'tools'), os.path.join(HERE, '..', 'tools')):
        if os.path.exists(os.path.join(d, 'ledger.py')):
            if d not in sys.path:
                sys.path.insert(0, d)
            return importlib.import_module('ledger')
    raise ImportError('tools/ledger.py not found')


def _credit_module(project):
    for d in (project, os.path.join(HERE, '..', '..')):
        if os.path.exists(os.path.join(d, 'credit.py')):
            if d not in sys.path:
                sys.path.insert(0, d)
            return importlib.import_module('credit')
    return None


def _read(p):
    try:
        return open(p, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


def authored_files(ctx):
    """Scene HTML, shots.js, the files qa.json lists under "authored", and scenes/lib/*.js (deduplicated, existing)."""
    project, files = ctx['project'], []
    for f in [ctx.get('scene_html'), ctx.get('shots_js')] + [os.path.join(project, a) for a in (ctx.get('qa') or {}).get('authored', [])]:
        if f and os.path.exists(f) and f not in files:
            files.append(f)
    libdir = os.path.join(os.path.dirname(ctx.get('scene_html') or os.path.join(project, 'scenes', 'x')), 'lib')
    if os.path.isdir(libdir):
        files += sorted(os.path.join(libdir, x) for x in os.listdir(libdir) if x.endswith('.js'))
    return files


def referenced_assets(ctx):
    """[(project-relative POSIX path, kind)] of everything the film draws from or mixes in."""
    project, cfg, refs = ctx['project'], ctx.get('cfg') or {}, []
    name = cfg.get('name', 'film')
    add = lambda rel, kind: refs.append((rel.replace('\\', '/'), kind)) if (rel and (rel.replace('\\', '/'), kind) not in refs) else None
    if cfg.get('bed'): add(cfg['bed'], 'music')
    if cfg.get('sfx'): add(cfg['sfx'], 'sfx')
    if os.path.exists(os.path.join(project, 'vo_%s.mp3' % name)): add('vo_%s.mp3' % name, 'voice')
    cj = os.path.join(project, 'clips.json')
    if os.path.exists(cj):
        try:
            for c in json.load(open(cj, encoding='utf-8')):
                if c.get('name'): add('broll/%s/' % c['name'], 'footage')
                src = c.get('file', 'recording.mp4')
                if os.path.exists(os.path.join(project, src)): add(src, 'footage')
        except ValueError:
            pass
    scene = ctx.get('scene_html')
    if scene and os.path.exists(scene):
        html, sdir = _strip_comments(_read(scene)), os.path.dirname(scene)
        for block in FONT_FACE_RE.findall(html):
            for m in LOCAL_REF_RE.finditer(block):
                rel = m.group(1) or m.group(2)
                if rel and not rel.startswith(('data:', '#')):
                    add(os.path.relpath(os.path.normpath(os.path.join(sdir, rel)), project), 'font')
        for m in re.finditer(r"""<(?:img|video|source|audio)\b[^>]*\bsrc\s*=\s*["']([^"'<>:]+?)["']""", html, re.I):
            rel = m.group(1)
            if rel and os.path.splitext(rel)[1].lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.mp4', '.webm', '.mp3', '.wav'):
                add(os.path.relpath(os.path.normpath(os.path.join(sdir, rel)), project), 'image')
    return refs


def run(ctx):
    project, cfg, qa, out = ctx['project'], ctx.get('cfg') or {}, ctx.get('qa') or {}, []
    LG = _ledger_module(project)
    L = LG.Ledger(project, cfg.get('ledger') or qa.get('ledger') or LG.LEDGER_FILE)
    refs = referenced_assets(ctx)
    licensable = [r for r, k in refs if k in LG.LICENSABLE]
    # 1 + 2 — the ledger and its licences
    if not L.exists():
        hint = 'no %s — run `python tools/ledger.py adopt` to record %d asset%s' % (os.path.basename(L.path), len(refs), '' if len(refs) == 1 else 's')
        out.append(('media ledger', not licensable, hint if not licensable else hint + '; REQUIRED: licensable %s' % licensable))
        out.append(('licences', not licensable, 'nothing licensable referenced' if not licensable else 'unrecorded %s' % licensable))
    else:
        cur, problems = L.current(), []
        for rel, kind in refs:
            st = L.check_path(rel)[0]
            if st == 'missing': problems.append('missing ' + rel)
            elif st == 'stale': problems.append('stale ' + rel)
            elif st == 'absent': problems.append('file gone ' + rel)
        out.append(('media ledger', not problems, '; '.join(problems)[:200] if problems else '%d referenced assets recorded, sha256 current' % len(refs)))
        bad = [r['path'] for r in L.unknown()]                                    # any licensable record in the ledger
        for rel in licensable:                                                      # referenced but unrecorded counts too
            if rel not in cur and rel not in bad: bad.append(rel)
        out.append(('licences', not bad, 'UNKNOWN / refused: %s' % bad[:6] if bad else
                    '%d licensable (music/sfx/font/image) cleared' % len([r for r in cur.values() if r['kind'] in LG.LICENSABLE])))
    # 3 — no remote refs
    hits = []
    for f in authored_files(ctx):
        for i, line in enumerate(_strip_comments(_read(f)).splitlines(), 1):
            m = REMOTE_RE.search(line)
            if m:
                hits.append('%s:%d %s' % (os.path.relpath(f, project).replace('\\', '/'), i, m.group(0).strip()[:60]))
    out.append(('no remote refs', not hits, hits[0] + (' (+%d)' % (len(hits) - 1) if len(hits) > 1 else '') if hits else 'scene and libs load local files only'))
    # 4 — frozen local: every relative reference resolves inside the project
    broken, n = [], 0
    scene = ctx.get('scene_html')
    if scene and os.path.exists(scene):
        sdir, html = os.path.dirname(scene), _strip_comments(_read(scene))
        for m in LOCAL_REF_RE.finditer(html):
            rel = m.group(1) or m.group(2)
            if not rel or rel.startswith(('data:', '#', '?')) or re.match(r'^[a-z][a-z0-9+.-]*:', rel, re.I):
                continue
            ap = os.path.normpath(os.path.join(sdir, rel.split('?')[0]))
            n += 1
            if not ap.startswith(os.path.abspath(project)): broken.append('outside project: ' + rel)
            elif not os.path.exists(ap): broken.append('not found: ' + rel)
    out.append(('frozen local', not broken, '; '.join(broken)[:200] if broken else '%d local references resolve inside the project' % n))
    # 5 — credit font
    CR = _credit_module(project)
    fonts = [f for f in (getattr(CR, 'FONT_CANDIDATES', []) if CR else []) if os.path.exists(f)]
    out.append(('credit font', bool(fonts), os.path.basename(fonts[0]) if fonts else 'none of credit.py FONT_CANDIDATES exists — install a system font'))
    return out


# ----------------------------------------------------------------------------------------------- selftest
def selftest():
    import tempfile, wave
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, 'scenes', 'lib')); os.makedirs(os.path.join(td, 'music')); os.makedirs(os.path.join(td, 'broll', 'q'))
        open(os.path.join(td, 'scenes', 'lib', 'grammar.js'), 'w').write('// see https://example.com/licence (comment is fine)\nwindow.G={};\n')
        open(os.path.join(td, 'scenes', 'shots.js'), 'w').write('window.SHOTS=[];\n')
        open(os.path.join(td, 'broll', 'q', 'f_001.jpg'), 'wb').write(b'\xff\xd8\xff\xd9')
        json.dump([{'name': 'q', 'kind': 'still', 't': 1.0}], open(os.path.join(td, 'clips.json'), 'w'))
        scene_ok = ('<html><head><style>@font-face{font-family:X;src:url("../fonts/x.woff2")}</style></head><body>'
                    '<script src="lib/grammar.js"></script><script src="shots.js"></script></body></html>')
        open(os.path.join(td, 'scenes', 'film.html'), 'w').write(scene_ok.replace('<style>@font-face{font-family:X;src:url("../fonts/x.woff2")}</style>', ''))
        ctx = {'project': td, 'cfg': {'name': 'film', 'bed': None, 'sfx': None}, 'qa': {'authored': ['scenes/film.html', 'scenes/shots.js']},
               'scene_html': os.path.join(td, 'scenes', 'film.html'), 'shots_js': os.path.join(td, 'scenes', 'shots.js')}
        r = dict((n, (ok, d)) for n, ok, d in run(ctx))
        assert [n for n, _, _ in run(ctx)] == GATE_NAMES
        assert r['media ledger'][0] and r['licences'][0], ('no ledger + nothing licensable must pass', r)
        assert r['no remote refs'][0] and r['frozen local'][0] and r['credit font'][0], r
        # a bed with no ledger → the ledger becomes mandatory
        with wave.open(os.path.join(td, 'music', 'bed.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\0' * 16000)
        ctx['cfg']['bed'] = 'music/bed.wav'
        r = dict((n, (ok, d)) for n, ok, d in run(ctx))
        assert not r['media ledger'][0] and not r['licences'][0], r
        # adopt → recorded but UNKNOWN → licences fails, ledger passes
        LG = _ledger_module(td); L = LG.Ledger(td); L.adopt(verbose=False)
        r = dict((n, (ok, d)) for n, ok, d in run(ctx))
        assert r['media ledger'][0] and not r['licences'][0], r
        L.add('music/bed.wav', licence={'name': 'Acme Library Licence', 'url': 'https://example.com/l', 'commercial_ok': True})
        r = dict((n, (ok, d)) for n, ok, d in run(ctx))
        assert r['licences'][0], r
        # a re-trimmed bed → stale
        with open(os.path.join(td, 'music', 'bed.wav'), 'ab') as f: f.write(b'\0\0')
        r = dict((n, (ok, d)) for n, ok, d in run(ctx))
        assert not r['media ledger'][0] and 'stale' in r['media ledger'][1], r
        # remote refs and a missing local file
        open(os.path.join(td, 'scenes', 'film.html'), 'w').write(
            '<link href="https://fonts.example.com/css2?family=Inter" rel="stylesheet"><style>@import url(//cdn.example.com/x.css);'
            '#a{background:url("../assets/missing.png")}</style><script src="lib/grammar.js"></script>')
        r = dict((n, (ok, d)) for n, ok, d in run(ctx))
        assert not r['no remote refs'][0] and 'film.html:1' in r['no remote refs'][1], r
        assert not r['frozen local'][0] and 'missing.png' in r['frozen local'][1], r
    print('ledger_gate selftest OK: ' + ' / '.join(GATE_NAMES) + ' (pass, mandatory-with-bed, UNKNOWN, cleared, stale, remote, missing-local)')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(selftest() if '--selftest' in sys.argv else (print(__doc__) or 2))
