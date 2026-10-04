# -*- coding: utf-8 -*-
"""chart_gate.py — qa_film.py plug-in: a chart is a claim. Every figure a chart draws is traced to claims.json.

    python gates/chart_gate.py --selftest        (synthetic project, node lib/charts.js --check, < 5 s)

lib/charts.js refuses literal numbers at build time; this gate is the adversarial pass over the AUTHORED files and
the mounted charts, so a scene that bypasses the library (or a claims.json edited after the build) still fails QA.

Gates (GATE_NAMES, in order):
  chart claims     `node lib/charts.js --check claims.json <authored files>` — every `claim: '<id>'` / `total: '<id>'`
                   reference in scenes/film.html, scenes/shots.js and qa.json "authored" resolves in claims.json
                   "values" ({id: {value, unit, source}} or {id: number}). FAIL lists file:line id. PASS 'no charts'
                   when the scene loads no lib/charts.js and has no claim: references.
  chart figures    (a) static: inside every CHART.<bars|line|kpiTiles|race|donut>(...) call (comments stripped) no
                   `value:` literal number and no label / legend / note / title / name string that reads as a figure
                   (12.4 %, $3.2M, 1,204 — Q3 / 2025 / Week 12 pass, the same rule as CHART.guardText);
                   (b) mounted: when the scene's receipts are available (gates/_receipts.py: CHART.manifest()), every
                   rendered ref's value equals claims.json values[id].value — the chart shows the traced number, not a
                   stale one. Derived figures (shares, deltas, totals) are never computed: each is its own claim.

qa.json keys: "claims" (default claims.json), "authored" (extra files), "chart_receipts": false to skip (b).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GATE_NAMES = ['chart claims', 'chart figures']
CHART_KINDS = ('bars', 'line', 'kpiTiles', 'race', 'donut')
FIGURE_RE = re.compile(r'\d[\d,]*\.\d+|\d+ ?%|[$€£] ?\d|\d{1,3}(,\d{3})+')     # CHART.guardText's rule
TEXT_KEYS = ('label', 'legend', 'note', 'title', 'name', 'totalLabel', 'sub')
STRIP = lambda s: re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S))


def _charts_js(project):
    for p in (os.path.join(project, 'scenes', 'lib', 'charts.js'), os.path.join(FILM_DIR, 'lib', 'charts.js')):
        if os.path.exists(p):
            return p
    return None


def authored_files(ctx):
    P, Q = ctx['project'], ctx.get('qa') or {}
    files = [ctx.get('scene_html'), ctx.get('shots_js')] + [os.path.join(P, f) for f in Q.get('authored', [])]
    out, seen = [], set()
    for f in files:
        if f and os.path.exists(f) and os.path.abspath(f) not in seen:
            seen.add(os.path.abspath(f)); out.append(f)
    return out


def call_args(txt, pos, limit=6000):
    depth, i = 1, pos
    while i < len(txt) and i - pos < limit:
        ch = txt[i]
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    return txt[pos:i]


def static_figures(files):
    """[(file, line, what)] — literal values and figure-like free text inside CHART.<kind>(...) calls."""
    bad = []
    for f in files:
        txt = STRIP(open(f, encoding='utf-8', errors='replace').read())
        base = os.path.basename(f)
        for m in re.finditer(r'\bCHART\s*\.\s*(%s)\s*\(' % '|'.join(CHART_KINDS), txt):
            args = call_args(txt, m.end())
            line0 = txt.count('\n', 0, m.start()) + 1
            for v in re.finditer(r'\bvalue\s*:\s*(-?\d+(?:\.\d+)?)', args):
                bad.append((base, line0 + args.count('\n', 0, v.start()), 'CHART.%s value: %s is a literal — give a claim id' % (m.group(1), v.group(1))))
            for s in re.finditer(r'\b(%s)\s*:\s*([\'"])((?:(?!\2).)*)\2' % '|'.join(TEXT_KEYS), args):
                if FIGURE_RE.search(s.group(3)):
                    bad.append((base, line0 + args.count('\n', 0, s.start()), 'CHART.%s %s %r reads as a figure' % (m.group(1), s.group(1), s.group(3)[:40])))
    return bad


def load_values(claims_path):
    if not os.path.exists(claims_path):
        return None
    doc = json.load(open(claims_path, encoding='utf-8'))
    V = doc.get('values') if isinstance(doc, dict) else None
    out = {}
    for k, v in (V or {}).items():
        out[k] = float(v['value']) if isinstance(v, dict) else float(v)
    return out


def mounted_figures(receipts, values):
    """[(chart id, claim id, shown, traced)] for every CHART.manifest() ref whose value is not the claim's value."""
    bad = []
    for ch in (receipts or {}).get('charts') or []:
        for r in ch.get('refs') or []:
            cid = r.get('claim')
            if cid not in (values or {}):
                bad.append((ch.get('id'), cid, r.get('value'), None))
            elif r.get('value') is None or abs(float(r['value']) - values[cid]) > 1e-9:
                bad.append((ch.get('id'), cid, r.get('value'), values[cid]))
    return bad


def run(ctx):
    P, Q = ctx['project'], ctx.get('qa') or {}
    claims = os.path.join(P, Q.get('claims', 'claims.json'))
    files = authored_files(ctx)
    refs = sum(len(re.findall(r'\b(?:claim|total)\s*:\s*[\'"]', STRIP(open(f, encoding='utf-8', errors='replace').read()))) for f in files)
    scene = ctx.get('scene_html') or ''
    uses = bool(scene and os.path.exists(scene) and re.search(r'lib/charts\.js', open(scene, encoding='utf-8', errors='replace').read()))
    res = []
    if not uses and not refs:
        return [('chart claims', True, 'no charts in this scene (no lib/charts.js, no claim: references)'),
                ('chart figures', True, 'no charts in this scene')]
    js = _charts_js(P)
    if not os.path.exists(claims):
        res.append(('chart claims', False, '%s missing: charts need a "values" map to draw from' % os.path.relpath(claims, P)))
    elif js is None:
        res.append(('chart claims', False, 'lib/charts.js not found (copy lib/charts.js into scenes/lib/)'))
    else:
        r = subprocess.run(['node', js, '--check', claims] + files, capture_output=True, text=True, cwd=P)
        try:                                       # charts.js prints one pretty-printed JSON object
            s = r.stdout.strip()
            rep = json.loads(s[s.index('{'):]) if '{' in s else {}
        except ValueError:
            rep = {}
        if r.returncode == 0 and rep:
            res.append(('chart claims', True, '%d claim refs resolve in %d values' % (rep.get('found', 0), rep.get('values', 0))))
        elif r.returncode == 1 and rep.get('missing'):
            miss = ['%s:%s %s' % (os.path.basename(x['file']), x['line'], x['id']) for x in rep['missing']]
            res.append(('chart claims', False, 'untraceable %s (add them to claims.json "values" with a source)' % miss[:4]))
        else:
            res.append(('chart claims', False, 'charts.js --check failed (%s): %s' % (r.returncode, (r.stderr or r.stdout).strip()[-160:])))
    bad = static_figures(files)
    parts = []
    if bad:
        parts.append('literal figures %s' % ['%s:%d %s' % b for b in bad[:3]])
    values = load_values(claims) or {}
    if Q.get('chart_receipts', True) is not False and uses:
        import _receipts
        R, note = _receipts.load(ctx)
        if R is None:
            parts.append('mounted charts not checked (%s)' % note[:80])
        else:
            mb = mounted_figures(R, values)
            if mb:
                parts.append('mounted value != claim (chart, id, shown, traced) %s' % mb[:3])
                bad = bad or mb
            else:
                n = sum(len(c.get('refs') or []) for c in R.get('charts') or [])
                parts.append('%d mounted figures equal their claims' % n)
    res.append(('chart figures', not bad, '; '.join(parts) if parts else 'no literal figures in CHART calls'))
    return res


# ----------------------------------------------------------------------------------------------- selftest
def _selftest():
    import time
    T0 = time.time()
    tmp = tempfile.mkdtemp(prefix='chartgate_')
    os.makedirs(os.path.join(tmp, 'scenes'))
    json.dump({'claims': [], 'values': {'late_west': {'value': 15.2, 'unit': '%', 'source': 'Deliveries table'}, 'late_north': 9.8}},
              open(os.path.join(tmp, 'claims.json'), 'w'))
    good = ("<script src=\"lib/charts.js\"></script><script>\n// CHART.bars(x, {value: 99}) in a comment is inert\n"
            "CHART.bars($('#ovl'), { id: 'lateBars', series: [{label: 'West', claim: 'late_west'}, {label: 'North', claim: 'late_north'}],\n"
            "  legend: 'Late delivery rate by region, Q3 2025 (synthetic data)', land: 12.4, end: 30 });\n</script>")
    bad = ("<script src=\"lib/charts.js\"></script><script>\nCHART.bars($('#ovl'), { id: 'b', series: [{label: 'South', claim: 'late_south'}],\n"
           "  value: 12.4, legend: 'up 12.4% this week' });\n</script>")
    sg, sb = os.path.join(tmp, 'scenes', 'good.html'), os.path.join(tmp, 'scenes', 'bad.html')
    open(sg, 'w', encoding='utf-8').write(good); open(sb, 'w', encoding='utf-8').write(bad)
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok = ok and bool(cond)
        print('  %-44s %s  %s' % (label, 'PASS' if cond else 'FAIL', str(detail)[:120]))
    base = {'project': tmp, 'qa': {'claims': 'claims.json', 'chart_receipts': True}, 'shots_js': None}
    R = {n: (o, d) for n, o, d in run(dict(base, scene_html=sg, _receipts=({'charts': [{'id': 'lateBars', 'refs': [{'claim': 'late_west', 'value': 15.2}, {'claim': 'late_north', 'value': 9.8}]}]}, 'synthetic')))}
    check('good scene: claims resolve', R['chart claims'][0], R['chart claims'][1])
    check('good scene: no literal figures, mounted == claims', R['chart figures'][0] and '2 mounted' in R['chart figures'][1], R['chart figures'][1])
    R = {n: (o, d) for n, o, d in run(dict(base, scene_html=sb, _receipts=({'charts': [{'id': 'b', 'refs': [{'claim': 'late_west', 'value': 15.0}]}]}, 'synthetic')))}
    check('bad scene: missing claim id fails', not R['chart claims'][0] and 'late_south' in R['chart claims'][1], R['chart claims'][1])
    check('bad scene: literal value + figure text fail', not R['chart figures'][0] and 'value: 12.4' in R['chart figures'][1] and 'reads as a figure' in R['chart figures'][1], R['chart figures'][1])
    check('bad scene: stale mounted value listed', 'mounted value != claim' in R['chart figures'][1], R['chart figures'][1])
    R = {n: (o, d) for n, o, d in run(dict(base, scene_html=sg, _receipts=(None, 'no puppeteer')))}
    check('receipts unavailable -> static only, noted', R['chart figures'][0] and 'not checked' in R['chart figures'][1], R['chart figures'][1])
    plain = os.path.join(tmp, 'scenes', 'plain.html'); open(plain, 'w').write('<script>const x = 1;</script>')
    R = {n: (o, d) for n, o, d in run(dict(base, scene_html=plain))}
    check('scene without charts -> PASS no charts', all(o for o, _ in R.values()) and 'no charts' in R['chart claims'][1])
    check('static_figures: Q3 / 2025 / Week 12 allowed', not static_figures([sg]))
    check('mounted_figures pure: 1e-9 tolerance', not mounted_figures({'charts': [{'id': 'a', 'refs': [{'claim': 'x', 'value': 1.0 + 1e-12}]}]}, {'x': 1.0}))
    print('\n%s  (%.1f s)  %s' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', time.time() - T0, tmp))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
