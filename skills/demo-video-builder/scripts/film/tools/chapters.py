# -*- coding: utf-8 -*-
"""chapters.py — jumpable chapters from the storyboard's beats: chapters.vtt, a YouTube description block, timeline.md, chapters.json.

    python tools/chapters.py STORYBOARD.md [--seams seams.json] [--phases vo/<name>_phases.json | --timing scenes/timing_<name>_data.js]
                             [--out out] [--merge] [--min 10] [--max-title 40] [--snap 0.75] [--json]
    python tools/chapters.py --selftest

WHERE CHAPTERS COME FROM. A storyboard beat is one idea; a chapter is one stretch a viewer would jump to. Beats
(tools/storyboard.py parse) carry `t0–t1` in the heading plus `- phase:`, `- act:` and optional `- chapter:` bullets,
so the chapter boundaries are read in this order of intent:
    1. any beat with `- chapter: <title>` (or `chapter: yes`, then the beat title is used) starts a chapter — explicit wins
    2. otherwise a change of `- act:` between consecutive beats starts a chapter (acts are the film's own sections)
    3. otherwise every beat is a chapter (and --merge is what makes that usable)
The first chapter always starts at 0.000 (players and YouTube require 00:00); the last ends at the film length
(frontmatter `duration`, else the measured phases total, else the last beat's t1).

WHERE THE TIMES COME FROM. The storyboard's t0 is a plan. When the narration exists (vo/<name>_phases.json or
scenes/timing_<name>_data.js) the beat's `phase:` start is the measured truth and replaces the plan. Then, when
seams.json is given, each chapter start is snapped to the nearest CUT within ±`snap` s (0.75 s): a chapter must begin on a
cut, never mid-shot, and the ledger is where the cuts are. Cue expressions in seams.json (P.<phase>, P.<phase>_end,
wt(<phase>,<word>[,n]), arithmetic) are resolved from the same timing data; a cut that cannot be resolved is skipped
with a finding. Only a numeric cut, or one that resolves, can attract a chapter.

THE RULES CHECKED (findings → exit 1): every chapter ≥ `--min` s (10 s: YouTube rejects shorter chapters and a
booth viewer cannot read a shorter one), every title ≤ `--max-title` chars (40: the longest string the YouTube
chapter strip shows without an ellipsis at 1080p; ASCII-safe, no trailing punctuation). Warnings (exit 0): fewer
than 3 chapters (YouTube ignores the list), duplicate titles, a chapter whose beats mix `recorded` and `placeholder`.
--merge folds too-short chapters before checking: the shortest first, into its SHORTER neighbour (so a 32 s film
becomes two balanced chapters rather than everything cascading into chapter 1); the merged chapter keeps the longer
part's title and the earlier part's start. Every merge is reported in chapters.json and timeline.md.

FILES (in --out, default out/): chapters.vtt — WebVTT with one cue per chapter (players: VLC, mpv, the booth
player, YouTube on upload); chapters_youtube.txt — "mm:ss Title" lines (hh:mm:ss past one hour, floor-rounded as
YouTube reads them); timeline.md — a reviewable table of chapters → beats → narration → truth tag; chapters.json —
the machine twin with every snap, merge and finding. All four are pure functions of the inputs: no wall clock,
sorted iteration, fixed key order (run it twice, diff nothing).

Exit codes: 0 ok · 1 findings · 2 usage. Stdlib only (imports tools/storyboard.py for the parser).
"""
import json, os, re, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import storyboard as SB

MIN_S, MAX_TITLE, SNAP_S = 10.0, 40, 0.75
YES = ('yes', 'true', 'y', '1', 'new')


# ------------------------------------------------------------------------------------------------ timing + seams
def load_timing(phases_path=None, timing_js=None):
    """→ (P: {name: start, name_end: end}, WORDS: {phase: [{t, d, w}]}, total) or (None, None, None)."""
    if timing_js and os.path.exists(timing_js):
        src = open(timing_js, encoding='utf-8').read()
        m = re.search(r'module\.exports\s*=\s*(\{.*\});?\s*$', src, re.S)
        if not m:
            return None, None, None
        d = json.loads(m.group(1))
        ph, wd = d.get('PHASES', {}), d.get('WORDS', {})
    elif phases_path and os.path.exists(phases_path):
        ph = json.load(open(phases_path, encoding='utf-8'))
        wp = phases_path[:-len('_phases.json')] + '_words.json' if phases_path.endswith('_phases.json') else None
        wd = json.load(open(wp, encoding='utf-8')) if wp and os.path.exists(wp) else {}
    else:
        return None, None, None
    P = {}
    for p in ph.get('phases', []):
        P[p['name']] = float(p['start']); P[p['name'] + '_end'] = float(p['start']) + float(p['dur'])
    return P, wd, float(ph.get('total') or 0) or None


def resolve_cut(expr, P, WORDS):
    """seconds | 'P.x' | 'P.x_end' | "wt('ph','word'[,n])" | arithmetic of those → float or None."""
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr).strip()
    if re.fullmatch(r'-?\d+(\.\d+)?', s):
        return float(s)
    if P is None:
        return None
    norm = lambda x: re.sub(r'[^a-z0-9]', '', str(x).lower())

    def wt(m):
        ph, word, n = m.group(1), m.group(2), int(m.group(3) or 1)
        k = 0
        for x in WORDS.get(ph, []):
            if norm(x['w']) == norm(word):
                k += 1
                if k == n:
                    return '%.6f' % (P.get(ph, 0.0) + float(x['t']))
        return 'nan'
    s = re.sub(r"wt\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(\d+))?\s*\)", wt, s)
    s = re.sub(r'P\.([A-Za-z_][\w]*)', lambda m: '%.6f' % P[m.group(1)] if m.group(1) in P else 'nan', s)
    if 'nan' in s or not re.fullmatch(r'[\d\s.+\-*/()]+', s):
        return None
    try:
        return float(arith(s))
    except Exception:
        return None


def arith(s):
    """Tiny recursive-descent evaluator for '+ - * / ( )' over numbers — no eval, no names, nothing else."""
    toks = re.findall(r'\d+(?:\.\d+)?|[+\-*/()]', s)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1; return toks[pos[0] - 1]

    def atom():
        t = take()
        if t == '(':
            v = expr(); assert take() == ')'; return v
        if t == '-':
            return -atom()
        if t == '+':
            return atom()
        return float(t)

    def term():
        v = atom()
        while peek() in ('*', '/'):
            op = take(); r = atom(); v = v * r if op == '*' else v / r
        return v

    def expr():
        v = term()
        while peek() in ('+', '-'):
            op = take(); r = term(); v = v + r if op == '+' else v - r
        return v
    v = expr()
    assert peek() is None, 'trailing tokens'
    return v


def load_cuts(seams_path, P, WORDS):
    """→ (sorted cut seconds, findings)."""
    if not seams_path or not os.path.exists(seams_path):
        return [], []
    doc = json.load(open(seams_path, encoding='utf-8'))
    rows = doc.get('seams', doc if isinstance(doc, list) else [])
    cuts, findings = [], []
    for r in rows:
        if r.get('seam') is True:
            continue                                                            # hand-offs are not cuts
        c = resolve_cut(r.get('cut'), P, WORDS)
        if c is None:
            findings.append(('warn', 'seam "%s": cut "%s" could not be resolved (pass --phases/--timing); not used for snapping' % (r.get('id', '?'), r.get('cut'))))
        else:
            cuts.append(round(c, 3))
    return sorted(set(cuts)), findings


# ------------------------------------------------------------------------------------------------ chapters
def clean_title(s):
    s = re.sub(r'\s+', ' ', str(s or '')).strip().strip('"“”')
    return s.rstrip(' .:;,-–—')


def derive(man, P=None, WORDS=None, total=None, cuts=None, min_s=MIN_S, max_title=MAX_TITLE, snap=SNAP_S, merge=False):
    """manifest (storyboard.parse) → report dict with chapters, merges, findings, ok."""
    beats = [b for b in man['beats'] if b.get('t0') is not None]
    findings, cuts = [], cuts or []
    if not beats:
        return {'total': total or 0.0, 'chapters': [], 'merges': [], 'findings': [{'level': 'fail', 'msg': 'no beats with times in the storyboard'}], 'ok': False}
    g = man.get('globals', {})
    film_total = SB._seconds(g.get('duration')) if g.get('duration') not in (None, '') else None
    film_total = film_total or total or max(float(b['t1'] or b['t0']) for b in beats)
    # measured phase starts replace the plan
    starts = []
    for b in beats:
        ph = (b['fields'].get('phase') or '').strip()
        t = float(b['t0'])
        src = 'plan'
        if P and ph in P:
            t, src = P[ph], 'phase'
        starts.append((round(t, 3), src))
    # boundaries
    has_chapter = any('chapter' in b['fields'] for b in beats)
    has_act = any(b['fields'].get('act') for b in beats)
    mode = 'chapter' if has_chapter else 'act' if has_act else 'beat'
    chapters = []
    for i, b in enumerate(beats):
        f = b['fields']
        new, title = False, None
        if mode == 'chapter':
            v = (f.get('chapter') or '').strip()
            if v and v.lower() not in ('no', 'false', 'none', '-', '—'):
                new = True
                title = b['title'] if v.lower() in YES else v
        elif mode == 'act':
            act = (f.get('act') or '').strip()
            prev = (beats[i - 1]['fields'].get('act') or '').strip() if i else None
            if i == 0 or act != prev:
                new, title = True, (act or b['title'])
        else:
            new, title = True, b['title']
        if i == 0 and not new:
            new, title = True, ((f.get('act') if mode == 'act' else None) or b['title'])   # the film always starts a chapter
        if new:
            chapters.append({'title': clean_title(title).title() if mode == 'act' and title and title.isupper() else clean_title(title),
                             'start': starts[i][0], 'start_source': starts[i][1], 'beats': [b['number']], 'phase': (f.get('phase') or '').strip() or None,
                             'snapped_from': None, 'merged': []})
        else:
            chapters[-1]['beats'].append(b['number'])
    if mode == 'beat':
        findings.append(('warn', 'no "chapter:" or "act:" bullets - every beat became a chapter (use --merge or add act: lines)'))
    # snap to the ledger's cuts (never the first chapter: it is pinned to 0)
    for k, c in enumerate(chapters):
        if k == 0:
            if c['start'] != 0.0:
                c['snapped_from'] = c['start']; c['start'] = 0.0; c['start_source'] = 'pinned'
            continue
        if cuts:
            near = min(cuts, key=lambda x: abs(x - c['start']))
            if abs(near - c['start']) <= snap and near != c['start']:
                c['snapped_from'] = c['start']; c['start'] = near; c['start_source'] = 'seam'
    chapters.sort(key=lambda c: c['start'])
    # ends
    for k, c in enumerate(chapters):
        c['end'] = chapters[k + 1]['start'] if k + 1 < len(chapters) else round(float(film_total), 3)
    merges = []
    if merge:
        # shortest short chapter first, folded into its SHORTER neighbour (balanced chapters, no cascade into chapter 1);
        # the merged chapter keeps the title of the longer part and the earlier part's start
        dur = lambda c: c['end'] - c['start']
        while len(chapters) > 1:
            short = [c for c in chapters if dur(c) < min_s]
            if not short:
                break
            c = min(short, key=lambda x: (dur(x), x['start']))
            k = chapters.index(c)
            j = min([j for j in (k - 1, k + 1) if 0 <= j < len(chapters)], key=lambda j: (dur(chapters[j]), j))
            a, b = (chapters[j], c) if j < k else (c, chapters[j])
            keep = chapters[j] if dur(chapters[j]) >= dur(c) else c
            merged = {'title': keep['title'], 'start': a['start'], 'start_source': a['start_source'], 'snapped_from': a['snapped_from'], 'end': b['end'],
                      'beats': a['beats'] + b['beats'], 'phase': a['phase'], 'merged': a['merged'] + b['merged'] + [x['title'] for x in (a, b) if x is not keep]}
            merges.append({'chapter': c['title'], 'into': chapters[j]['title'], 'dur': round(dur(c), 3), 'kept_title': keep['title']})
            lo = min(k, j); chapters[lo] = merged; chapters.pop(lo + 1)
    # validate
    seen = set()
    for c in chapters:
        c['dur'] = round(c['end'] - c['start'], 3)
        if c['dur'] < min_s:
            findings.append(('fail', 'chapter "%s" is %.1f s (< %.0f s)' % (c['title'], c['dur'], min_s)))
        if len(c['title']) > max_title:
            findings.append(('fail', 'title "%s" is %d chars (> %d)' % (c['title'], len(c['title']), max_title)))
        if not c['title']:
            findings.append(('fail', 'a chapter starting at %.1f s has no title' % c['start']))
        if c['title'].lower() in seen:
            findings.append(('warn', 'duplicate title "%s"' % c['title']))
        seen.add(c['title'].lower())
        reals = {b['real'] for b in beats if b['number'] in c['beats'] and b.get('real')}
        if 'placeholder' in reals and 'recorded' in reals:
            findings.append(('warn', 'chapter "%s" mixes recorded and placeholder beats' % c['title']))
    if len(chapters) < 3:
        findings.append(('warn', 'only %d chapter(s) - YouTube needs at least 3 to show a chapter list' % len(chapters)))
    for i, c in enumerate(chapters):
        c['index'] = i + 1
    ordered = [{'index': c['index'], 'title': c['title'], 'start': c['start'], 'end': c['end'], 'dur': c['dur'], 'beats': c['beats'], 'phase': c['phase'],
                'start_source': c['start_source'], 'snapped_from': c['snapped_from'], 'merged': c['merged']} for c in chapters]
    return {'total': round(float(film_total), 3), 'mode': mode, 'min_s': min_s, 'max_title': max_title, 'snap_s': snap, 'cuts': cuts,
            'chapters': ordered, 'merges': merges, 'findings': [{'level': l, 'msg': m} for l, m in findings],
            'ok': not any(l == 'fail' for l, _ in findings)}


# ------------------------------------------------------------------------------------------------ writers
def ts_vtt(x):
    ms = int(round(max(0.0, float(x)) * 1000))
    return '%02d:%02d:%02d.%03d' % (ms // 3600000, ms % 3600000 // 60000, ms % 60000 // 1000, ms % 1000)


def ts_yt(x, long=False):
    s = int(max(0.0, float(x)))                                                  # floor: YouTube reads whole seconds
    return ('%d:%02d:%02d' % (s // 3600, s % 3600 // 60, s % 60)) if long else ('%02d:%02d' % (s // 60, s % 60))


def write_vtt(rep, path):
    lines = ['WEBVTT', '']
    for c in rep['chapters']:
        lines += [str(c['index']), '%s --> %s' % (ts_vtt(c['start']), ts_vtt(c['end'])), c['title'], '']
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))


def write_youtube(rep, path):
    long = rep['total'] >= 3600
    open(path, 'w', encoding='utf-8').write('\n'.join('%s %s' % (ts_yt(c['start'], long), c['title']) for c in rep['chapters']) + '\n')


def write_timeline_md(rep, man, path):
    by_n = {b['number']: b for b in man['beats']}
    L = ['# Timeline', '', 'Chapters derived from STORYBOARD.md beats (%s boundaries), %.1f s film, %d chapters.' % (rep['mode'], rep['total'], len(rep['chapters'])), '',
         '| # | start | end | dur | chapter | beats | first narration | truth |', '|---|---|---|---|---|---|---|---|']
    for c in rep['chapters']:
        first = by_n.get(c['beats'][0], {})
        vo = re.sub(r'\s+', ' ', (first.get('fields', {}).get('vo') or '')).strip('"“” ')
        reals = sorted({by_n[n]['real'] for n in c['beats'] if n in by_n and by_n[n].get('real')})
        L.append('| %d | %s | %s | %.1f s | %s | %s | %s | %s |' % (c['index'], ts_vtt(c['start'])[3:], ts_vtt(c['end'])[3:], c['dur'], c['title'],
                 ', '.join('%02d' % n for n in c['beats']), (vo[:60] + ('…' if len(vo) > 60 else '')) or '—', ', '.join(reals) or '—'))
    notes = []
    for c in rep['chapters']:
        if c['snapped_from'] is not None:
            notes.append('- chapter %d "%s": start %.3f → %.3f (%s)' % (c['index'], c['title'], c['snapped_from'], c['start'], c['start_source']))
        for m in c['merged']:
            notes.append('- chapter %d "%s" absorbed "%s" (shorter than %.0f s)' % (c['index'], c['title'], m, rep['min_s']))
    for f in rep['findings']:
        notes.append('- %s: %s' % (f['level'].upper(), f['msg']))
    if notes:
        L += ['', '## Notes', ''] + notes
    L += ['', 'Generated by tools/chapters.py — edit STORYBOARD.md (chapter:/act: bullets) and seams.json, not this file.', '']
    open(path, 'w', encoding='utf-8').write('\n'.join(L))


def write_all(rep, man, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    paths = {'vtt': os.path.join(out_dir, 'chapters.vtt'), 'youtube': os.path.join(out_dir, 'chapters_youtube.txt'),
             'timeline': os.path.join(out_dir, 'timeline.md'), 'json': os.path.join(out_dir, 'chapters.json')}
    write_vtt(rep, paths['vtt']); write_youtube(rep, paths['youtube']); write_timeline_md(rep, man, paths['timeline'])
    json.dump(rep, open(paths['json'], 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return paths


# ------------------------------------------------------------------------------------------------ selftest
SYN_ACTS = """---
title: Monday, answered.
version: 1
name: film
duration: 60s
---

## Locked
- everything

## Beat 01 — Hook (0.0–6.0, ~6.0 s)
- phase: hook
- act: OPEN
- real: recreated
- vo: "Every Monday the operations lead at Acme asks the same question."

## Beat 02 — Thesis (6.0–12.0, ~6.0 s)
- phase: title
- act: OPEN
- real: recreated
- vo: "Acme is fictional, and so is its data."

## Beat 03 — Notebook (12.0–24.0, ~12.0 s)
- phase: nb
- act: DEMO
- real: recorded
- vo: "My notebook loads the orders."

## Beat 04 — Question (24.0–33.0, ~9.0 s)
- phase: ask
- act: DEMO
- real: recorded
- vo: "Which regions missed their target?"

## Beat 05 — Answer (33.0–52.0, ~19.0 s)
- phase: answer
- act: DEMO
- real: recorded
- vo: "The answer comes back from governed data."

## Beat 06 — Close (52.0–57.0, ~5.0 s)
- phase: close
- act: CLOSE
- real: recreated
- vo: "One answer the whole team can trust."

## Beat 07 — Credit (57.0–60.0, ~3.0 s)
- phase: credit
- act: CLOSE
- real: recreated
- vo: "Crafted with care."
"""


def selftest():
    import tempfile
    man = SB.parse(SYN_ACTS)
    assert len(man['beats']) == 7, len(man['beats'])
    # measured phases: the demo act really starts at 12.3; seams: a cut at 52.4 near the CLOSE boundary + an expression
    P = {'hook': 0.0, 'hook_end': 6.1, 'title': 6.1, 'title_end': 12.3, 'nb': 12.3, 'nb_end': 24.2, 'ask': 24.2, 'ask_end': 33.1,
         'answer': 33.1, 'answer_end': 52.0, 'close': 52.0, 'close_end': 57.2, 'credit': 57.2, 'credit_end': 60.0}
    WORDS = {'close': [{'t': 0.0, 'd': 0.2, 'w': 'One'}, {'t': 0.4, 'd': 0.3, 'w': 'answer'}]}
    assert resolve_cut('P.nb', P, WORDS) == 12.3 and resolve_cut("wt('close','answer') + 0.1", P, WORDS) == 52.5 and resolve_cut('P.nope', P, WORDS) is None
    assert resolve_cut('__import__("os")', P, WORDS) is None and resolve_cut(52.4, None, None) == 52.4
    d = tempfile.mkdtemp(prefix='chapters_self_')
    seams = os.path.join(d, 'seams.json')
    json.dump({'seams': [{'id': 'a', 'cut': 'P.nb'}, {'id': 'b', 'cut': 52.4}, {'id': 'c', 'cut': "wt('ask','never')"}, {'id': 'h', 'cut': 'P.ask', 'seam': True}]}, open(seams, 'w'))
    cuts, cf = load_cuts(seams, P, WORDS)
    assert cuts == [12.3, 52.4] and len(cf) == 1, (cuts, cf)
    rep = derive(man, P, WORDS, 60.0, cuts)
    assert rep['mode'] == 'act' and [c['title'] for c in rep['chapters']] == ['Open', 'Demo', 'Close'], rep['chapters']
    assert rep['chapters'][1]['start'] == 12.3 and rep['chapters'][1]['start_source'] == 'phase', rep['chapters'][1]
    assert rep['chapters'][2]['start'] == 52.4 and rep['chapters'][2]['start_source'] == 'seam' and rep['chapters'][2]['snapped_from'] == 52.0, rep['chapters'][2]
    assert not rep['ok'] and any('Close' in f['msg'] and '7.6 s' in f['msg'] for f in rep['findings']), rep['findings']   # 52.4–60 = 7.6 s < 10
    rep2 = derive(man, P, WORDS, 60.0, cuts, merge=True)
    assert rep2['ok'] and len(rep2['chapters']) == 2 and rep2['merges'][0]['chapter'] == 'Close' and rep2['chapters'][1]['end'] == 60.0, (rep2['merges'], rep2['findings'])
    assert any('at least 3' in f['msg'] for f in rep2['findings'])
    # explicit chapter bullets win over acts; a long title is a finding; the first chapter is pinned to 0
    txt = SYN_ACTS.replace('- act: DEMO\n- real: recorded\n- vo: "My notebook', '- act: DEMO\n- chapter: The analyst builds the answer where the data already lives\n- real: recorded\n- vo: "My notebook') \
                  .replace('- act: OPEN\n- real: recreated\n- vo: "Acme', '- act: OPEN\n- chapter: yes\n- real: recreated\n- vo: "Acme') \
                  .replace('- act: CLOSE\n- real: recreated\n- vo: "One', '- act: CLOSE\n- chapter: Close\n- real: recreated\n- vo: "One')
    man3 = SB.parse(txt)
    rep3 = derive(man3, None, None, None, [])
    titles = [c['title'] for c in rep3['chapters']]
    assert rep3['mode'] == 'chapter' and titles[0] == 'Hook' and titles[1] == 'Thesis' and titles[2].startswith('The analyst') and titles[3] == 'Close', titles
    assert rep3['chapters'][0]['start'] == 0.0 and rep3['chapters'][0]['start_source'] in ('plan', 'pinned')
    man4 = SB.parse(SYN_ACTS.replace('(0.0–6.0, ~6.0 s)', '(0.4–6.0, ~5.6 s)'))                                   # a plan that starts late is pinned to 0
    rep4 = derive(man4, None, None, None, [])
    assert rep4['chapters'][0]['start'] == 0.0 and rep4['chapters'][0]['start_source'] == 'pinned' and rep4['chapters'][0]['snapped_from'] == 0.4
    assert any('chars (> 40)' in f['msg'] for f in rep3['findings']), rep3['findings']
    assert rep3['total'] == 60.0 and rep3['chapters'][-1]['end'] == 60.0
    # files, formats, determinism
    p1 = write_all(rep, man, os.path.join(d, 'a')); p2 = write_all(derive(SB.parse(SYN_ACTS), P, WORDS, 60.0, cuts), man, os.path.join(d, 'b'))
    for k in p1:
        assert open(p1[k], 'rb').read() == open(p2[k], 'rb').read(), 'non-deterministic ' + k
    vtt = open(p1['vtt'], encoding='utf-8').read()
    assert vtt.startswith('WEBVTT\n\n1\n00:00:00.000 --> 00:00:12.300\nOpen\n\n2\n00:00:12.300 --> 00:00:52.400\nDemo'), vtt[:120]
    yt = open(p1['youtube'], encoding='utf-8').read()
    assert yt == '00:00 Open\n00:12 Demo\n00:52 Close\n', repr(yt)
    assert ts_yt(3725, True) == '1:02:05' and ts_vtt(61.0415) == '00:01:01.042'
    md = open(p1['timeline'], encoding='utf-8').read()
    assert '| 2 | 00:12.300 | 00:52.400 | 40.1 s | Demo | 03, 04, 05 |' in md and 'FAIL:' in md, md
    print('chapters selftest OK: act/chapter/beat modes, phase + seam snapping, --merge, %d findings on the synthetic board, 4 files byte-identical twice' % len(rep['findings']))
    return 0


# ------------------------------------------------------------------------------------------------ CLI
def main(argv):
    if '--selftest' in argv:
        return selftest()
    if '--help' in argv or '-h' in argv:
        print(__doc__); return 0
    sb = next((a for a in argv if not a.startswith('--') and a.lower().endswith('.md')), None)
    if not sb or not os.path.exists(sb):
        print(__doc__); print('chapters: pass STORYBOARD.md'); return 2

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default
    man = SB.parse(open(sb, encoding='utf-8').read())
    P, WORDS, total = load_timing(opt('--phases'), opt('--timing'))
    cuts, cut_findings = load_cuts(opt('--seams'), P, WORDS)
    rep = derive(man, P, WORDS, total, cuts, min_s=float(opt('--min', MIN_S)), max_title=int(opt('--max-title', MAX_TITLE)),
                 snap=float(opt('--snap', SNAP_S)), merge='--merge' in argv)
    rep['findings'] = [{'level': l, 'msg': m} for l, m in cut_findings] + rep['findings']
    rep['source'] = {'storyboard': sb.replace('\\', '/'), 'seams': opt('--seams'), 'phases': opt('--phases'), 'timing': opt('--timing')}
    out_dir = opt('--out', os.path.join(os.path.dirname(os.path.abspath(sb)), 'out'))
    paths = write_all(rep, man, out_dir)
    if '--json' in argv:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        print('chapters: %d chapters over %.1f s (%s boundaries) -> %s' % (len(rep['chapters']), rep['total'], rep['mode'], out_dir))
        for c in rep['chapters']:
            print('  %s  %-40s  %5.1f s  beats %s%s' % (ts_yt(c['start'], rep['total'] >= 3600), c['title'], c['dur'], ','.join('%02d' % n for n in c['beats']),
                  ('  (%s %.2f -> %.2f)' % (c['start_source'], c['snapped_from'], c['start'])) if c['snapped_from'] is not None else ''))
        for f in rep['findings']:
            print('  %-5s %s' % (f['level'].upper(), f['msg']))
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
