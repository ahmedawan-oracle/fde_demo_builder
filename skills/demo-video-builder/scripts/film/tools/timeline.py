# -*- coding: utf-8 -*-
"""timeline.py — a human-readable printout of the edit, before a render (v4, media area).

    python tools/timeline.py [--project DIR] [--json] [--at 12.5] [--write out/timeline_rows.json] [--no-node]
    python tools/timeline.py --selftest

Reads the project statically (no browser): out/timeline.json (total, cuts, phases — written by export_timeline.js),
vo/<name>_phases.json + vo_script.py (voices, word counts), scenes/shots.js (via a tiny node dump of FILM / SHOTS / HL
after lib/timeline.js and lib/footage.js, the same way export_timeline.js loads them), the .srt and film.json's bed/sfx.

Prints `timeline <N>s`, a cut ruler, then one block per track kind in a FIXED order — footage → cards → highlights →
captions → narration → audio — one row per element, ordered by absolute start. Each row is a 40-column bar over the whole
film (█ span, · empty) with exact seconds beside it (bars under-resolve a 0.3 s cue; the numbers do not), then extras
only when present (clip=, establish, scroll×n, moves×n, seam, play, reveal, voice=, words=, cue=, vol=). Durations that are
not authored carry a provenance tag: dur=default 3.5 s (lower-third), dur=inferred (shot end) (highlight), dur=media (srt).
Two derived checks close the printout: `coverage gap` (a moment between FILM.openEnd and FILM.close with no shot — a
positive delta between consecutive shots) and `shot overlap` (two non-seam shots sharing time — a negative delta). They
are printed as OK/FOUND; the integrator may promote them to QA gates.

--json prints {total, end, cuts, rows[], checks[]} (rows: kind, id, start, end, extras, dur_from) so an agent can answer
"what plays at T" or "where are the holes" without opening files. out/timeline.json itself is never rewritten.
"""
import argparse, json, os, re, subprocess, sys, tempfile

KINDS = ('footage', 'cards', 'highlights', 'captions', 'narration', 'audio')
COLS = 40
LOWER_THIRD_DUR = 3.5                  # film.example.html shows an act lower-third from t0+0.3 to t0+3.8
TAIL = 1.2                             # build_film.py's room tail after the last word

NODE_DUMP = r"""
const path = require('path'); global.window = global;
const [P, NAME] = process.argv.slice(2);
require(path.join(P, 'scenes/lib/grammar.js'));
global.TX = require(path.join(P, 'scenes/lib/timeline.js')).load(path.join(P, 'scenes/timing_' + NAME + '_data.js'));
require(path.join(P, 'scenes/lib/footage.js'));
require(path.join(P, 'scenes/shots.js'));
const F = global.FILM || {}, SH = global.SHOTS || [], HL = global.HL || {};
const shots = SH.map((s, i) => ({ i, t0: s.t0, t1: s.t1, clip: s.clip, seam: !!s.seam, establish: !!s.establish,
  scrolls: (s.scroll || []).length, moves: (s.moves || []).length - (s.establish ? 1 : 0), play: !!s.play, reveal: !!s.reveal, drift: !!s.drift }));
const hl = [];
for (const clip in HL) for (const h of HL[clip]) {
  const a = TX.wt(h.cue[0], h.cue[1], h.cue[2]) + (h.dt || 0);
  const until = h.until ? TX.wt(h.until[0], h.until[1]) : null;
  hl.push({ clip, id: h.id, kind: h.kind, t: a, until, cue: h.cue.join(':'), dt: h.dt || 0 });
}
console.log(JSON.stringify({ FILM: { openEnd: F.openEnd, close: F.close, title: F.title, acts: (F.acts || []).map(a => ({ label: a.label, t0: a.t0 })) }, SHOTS: shots, HL: hl }));
"""


def load_json(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return default


def dump_shots(project, name):
    """FILM / SHOTS / HL as plain data via node (None when node or the files are unavailable)."""
    if not os.path.exists(os.path.join(project, 'scenes', 'shots.js')):
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(NODE_DUMP); tmp = f.name
    try:
        r = subprocess.run(['node', tmp, project, name], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    finally:
        os.remove(tmp)


def srt_cues(path):
    if not os.path.exists(path):
        return []
    ts = re.findall(r'(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)', open(path, encoding='utf-8').read())
    return [(int(a) * 3600 + int(b) * 60 + int(c) + int(e) / 1000, int(f) * 3600 + int(g) * 60 + int(h) + int(i) / 1000) for a, b, c, e, f, g, h, i in ts]


def build_rows(project, cfg, tl, shots, phases_json, words_json, srt, voices, film_dur=None):
    """rows: {kind, id, start, end, extras: [..], dur_from} + derived checks. Pure data, no printing."""
    total = float(tl['total'])
    end = film_dur if film_dur else total + TAIL
    rows, checks = [], []
    F = (shots or {}).get('FILM') or {}
    SH = (shots or {}).get('SHOTS') or []
    HL = (shots or {}).get('HL') or []
    open_end, close = F.get('openEnd'), F.get('close')
    # footage
    for s in SH:
        ex = ['clip=%s' % s.get('clip')]
        if s.get('establish'): ex.append('establish')
        if s.get('scrolls'): ex.append('scroll×%d' % s['scrolls'])
        if s.get('moves'): ex.append('moves×%d' % s['moves'])
        for k in ('seam', 'play', 'reveal', 'drift'):
            if s.get(k): ex.append(k)
        rows.append({'kind': 'footage', 'id': 'shot%d' % (s['i'] + 1), 'start': s['t0'], 'end': s['t1'], 'extras': ex, 'dur_from': 'authored'})
    # cards
    if open_end is not None:
        rows.append({'kind': 'cards', 'id': 'title', 'start': 0.0, 'end': open_end, 'extras': (['"%s"' % F['title']] if F.get('title') else []), 'dur_from': 'authored'})
    if close is not None:
        rows.append({'kind': 'cards', 'id': 'close', 'start': close, 'end': end, 'extras': [], 'dur_from': 'authored'})
    for a in F.get('acts', []):
        if a.get('t0') is not None:
            rows.append({'kind': 'cards', 'id': 'lower-third', 'start': a['t0'] + 0.3, 'end': a['t0'] + 0.3 + LOWER_THIRD_DUR,
                         'extras': ['"%s"' % a.get('label', '')], 'dur_from': 'default %.1f s' % LOWER_THIRD_DUR})
    # highlights: until-cue or the end of the shot that shows the clip
    for h in HL:
        host = [s for s in SH if s.get('clip') == h.get('clip') and s['t0'] <= h['t'] < s['t1']]
        if h.get('until') is not None:
            e, src = h['until'], 'authored (until)'
        elif host:
            e, src = host[0]['t1'], 'inferred (shot end)'
        else:
            e, src = h['t'] + 1.0, 'default 1.0 s (no host shot)'
        rows.append({'kind': 'highlights', 'id': h.get('id'), 'start': h['t'], 'end': e, 'extras': ['cue=%s' % h.get('cue'), 'clip=%s' % h.get('clip')] +
                     (['dt=%+.1f' % h['dt']] if h.get('dt') else []), 'dur_from': src})
    # captions: one track
    if srt:
        rows.append({'kind': 'captions', 'id': 'srt', 'start': srt[0][0], 'end': srt[-1][1], 'extras': ['cues=%d' % len(srt)], 'dur_from': 'media'})
    # narration: phases with voice + word count
    for p in tl.get('phases') or (phases_json or {}).get('phases') or []:
        ex = []
        if voices.get(p['name']): ex.append('voice=%s' % voices[p['name']])
        if words_json and p['name'] in words_json: ex.append('words=%d' % len(words_json[p['name']]))
        rows.append({'kind': 'narration', 'id': p['name'], 'start': p['start'], 'end': p['start'] + p['dur'], 'extras': ex, 'dur_from': 'media'})
    # audio
    name = cfg.get('name', 'film')
    if os.path.exists(os.path.join(project, 'vo_%s.mp3' % name)):
        rows.append({'kind': 'audio', 'id': 'vo_%s.mp3' % name, 'start': 0.0, 'end': total, 'extras': ['vol=0 dB'], 'dur_from': 'media'})
    if cfg.get('bed'):
        rows.append({'kind': 'audio', 'id': cfg['bed'], 'start': 0.0, 'end': end, 'extras': ['vol=%.1f dB' % float(cfg.get('bed_db', -9.0)), 'ducked'], 'dur_from': 'loop to film end'})
    if cfg.get('sfx'):
        rows.append({'kind': 'audio', 'id': cfg['sfx'], 'start': 0.0, 'end': end, 'extras': ['vol=%.1f dB' % float(cfg.get('sfx_db', -5.0))], 'dur_from': 'media'})
    # derived checks over the footage lane
    gaps, overlaps = [], []
    if SH and open_end is not None and close is not None:
        lane = sorted(SH, key=lambda s: s['t0'])
        if lane[0]['t0'] > open_end + 0.001: gaps.append((open_end, lane[0]['t0']))
        for a, b in zip(lane, lane[1:]):
            delta = b['t0'] - a['t1']                              # positive = gap, negative = overlap
            if delta > 0.001: gaps.append((a['t1'], b['t0']))
            elif delta < -0.001 and not (a.get('seam') or b.get('seam')): overlaps.append((b['t0'], a['t1']))
        if lane[-1]['t1'] < close - 0.001: gaps.append((lane[-1]['t1'], close))
    checks.append({'check': 'coverage gap', 'ok': not gaps, 'spans': [[round(a, 2), round(b, 2)] for a, b in gaps]})
    checks.append({'check': 'shot overlap', 'ok': not overlaps, 'spans': [[round(a, 2), round(b, 2)] for a, b in overlaps]})
    for r in rows:
        r['start'], r['end'] = round(float(r['start']), 3), round(float(r['end']), 3)
    return {'total': total, 'end': round(end, 3), 'cuts': tl.get('cuts', []), 'rows': rows, 'checks': checks}


def bar(start, end, length, cols=COLS):
    a = max(0, min(cols, int(round(start / length * cols))))
    b = max(a + 1, min(cols, int(round(end / length * cols))))
    return '·' * a + '█' * (b - a) + '·' * (cols - b)


def render(data, at=None):
    """The printout as text."""
    L, out = data['end'], ['timeline %.2fs  (narration %.2fs + tail)' % (data['end'], data['total'])]
    ruler = ['·'] * COLS
    for c in data['cuts']:
        ruler[max(0, min(COLS - 1, int(round(c / L * COLS))))] = '|'
    out.append('%-11s %s  cuts %s' % ('cuts', ''.join(ruler), ' '.join('%.2f' % c for c in data['cuts']) or 'none'))
    rows = data['rows'] if at is None else [r for r in data['rows'] if r['start'] <= at < r['end']]
    if at is not None:
        out.append('at %.2fs:' % at)
    for k in KINDS:
        rs = sorted((r for r in rows if r['kind'] == k), key=lambda r: r['start'])
        if not rs:
            continue
        out.append(k)
        for r in rs:
            ex = ' '.join(r['extras'])
            tag = '' if r['dur_from'] in ('authored', 'media') else '  dur=%s' % r['dur_from']
            out.append('  %s  %-12s %6.2f-%-6.2f s%s%s' % (bar(r['start'], r['end'], L), r['id'][:12], r['start'], r['end'], ('  ' + ex) if ex else '', tag))
    if at is None:
        for c in data['checks']:
            out.append('check  %-13s %s' % (c['check'], 'OK' if c['ok'] else 'FOUND ' + ' '.join('%.2f-%.2f' % tuple(s) for s in c['spans'])))
    return '\n'.join(out)


def voices_for(project):
    try:
        sys.path.insert(0, project)
        import importlib
        vs = importlib.import_module('vo_script')
        V, out = getattr(vs, 'VOICES', {}), {}
        for sc in getattr(vs, 'SCENES', {}).values():
            for p in sc.get('phases', []):
                v = V.get(p.get('voice'))
                out[p['name']] = p.get('voice') if not isinstance(v, (list, tuple)) else '%s(%s)' % (p['voice'], v[0].replace('Neural', ''))
        return out
    except Exception:
        return {}


def gather(project, use_node=True):
    cfg = load_json(os.path.join(project, 'film.json'), {}) or {}
    name = cfg.get('name', 'film')
    tl = load_json(os.path.join(project, 'out', 'timeline.json'))
    if not tl:
        raise SystemExit('missing out/timeline.json — run: node export_timeline.js scenes/timing_%s_data.js scenes/shots.js' % name)
    shots = dump_shots(project, name) if use_node else None
    film = os.path.join(project, cfg.get('output', 'out/%s.mp4' % name))
    film_dur = None
    if os.path.exists(film):
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', film], capture_output=True, text=True)
        try: film_dur = float(r.stdout.strip())
        except ValueError: pass
    srt = srt_cues(os.path.splitext(film)[0] + '.srt')
    return build_rows(project, cfg, tl, shots, load_json(os.path.join(project, 'vo', name + '_phases.json')),
                      load_json(os.path.join(project, 'vo', name + '_words.json')), srt, voices_for(project), film_dur)


def find_project(start=None):
    for base in (start, os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = os.path.abspath(base or os.getcwd())
        for _ in range(6):
            if os.path.exists(os.path.join(d, 'film.json')): return d
            nd = os.path.dirname(d)
            if nd == d: break
            d = nd
    return os.path.abspath(start or os.getcwd())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project'); ap.add_argument('--json', action='store_true'); ap.add_argument('--at', type=float)
    ap.add_argument('--write', help='also write the rows JSON here (e.g. out/timeline_rows.json)')
    ap.add_argument('--no-node', action='store_true', help='skip the node shots dump (phases, captions and audio only)')
    ap.add_argument('--selftest', action='store_true')
    ns = ap.parse_args(argv)
    if ns.selftest: return selftest()
    project = find_project(ns.project)
    data = gather(project, use_node=not ns.no_node)
    if ns.write:
        p = os.path.join(project, ns.write); os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        json.dump(data, open(p, 'w', encoding='utf-8'), indent=1)
    print(json.dumps(data, indent=1) if ns.json else render(data, ns.at))
    return 0


def selftest():
    """Synthetic edit: a gap and an overlap in the footage lane, a highlight inferring its end, a default lower-third."""
    tl = {'total': 30.0, 'cuts': [10.0, 18.0, 26.0], 'phases': [{'name': 'hook', 'start': 0.1, 'dur': 9.5}, {'name': 'nb', 'start': 10.0, 'dur': 7.6},
                                                                  {'name': 'close', 'start': 26.0, 'dur': 3.9}]}
    shots = {'FILM': {'openEnd': 10.0, 'close': 26.0, 'title': 'Monday, answered.', 'acts': [{'label': 'THE ANALYST', 't0': 10.0}]},
             'SHOTS': [{'i': 0, 't0': 10.0, 't1': 17.0, 'clip': 'nb', 'seam': False, 'establish': True, 'scrolls': 2, 'moves': 1},
                       {'i': 1, 't0': 18.0, 't1': 23.0, 'clip': 'q', 'seam': False, 'establish': True, 'scrolls': 0, 'moves': 0, 'reveal': True},
                       {'i': 2, 't0': 22.5, 't1': 26.0, 'clip': 'send', 'seam': False, 'establish': False, 'scrolls': 0, 'moves': 2, 'play': True}],
             'HL': [{'clip': 'nb', 'id': 'late', 'kind': 'box', 't': 15.2, 'until': None, 'cue': 'nb:counts', 'dt': 1.0}]}
    cfg = {'name': 'film', 'bed': 'music/bed.mp3', 'bed_db': -9.0}
    words = {'hook': [{'w': 'x', 't': 0}] * 20, 'nb': [{'w': 'x', 't': 0}] * 14, 'close': [{'w': 'x', 't': 0}] * 11}
    data = build_rows('.', cfg, tl, shots, None, words, [(0.1, 9.6), (26.0, 29.9)], {'hook': 'narrator(en-US-Andrew)', 'nb': 'analyst(en-US-Ava)', 'close': 'narrator(en-US-Andrew)'})
    kinds = [r['kind'] for r in data['rows']]
    assert all(k in KINDS for k in kinds) and data['end'] == 31.2
    hl = [r for r in data['rows'] if r['kind'] == 'highlights'][0]
    assert hl['end'] == 17.0 and hl['dur_from'] == 'inferred (shot end)', hl
    lt = [r for r in data['rows'] if r['id'] == 'lower-third'][0]
    assert lt['start'] == 10.3 and lt['end'] == 13.8 and lt['dur_from'].startswith('default'), lt
    ck = {c['check']: c for c in data['checks']}
    assert not ck['coverage gap']['ok'] and ck['coverage gap']['spans'] == [[17.0, 18.0]], ck
    assert not ck['shot overlap']['ok'] and ck['shot overlap']['spans'] == [[22.5, 23.0]], ck
    txt = render(data)
    pos = [txt.index('\n%s\n' % k) for k in KINDS]                  # block headers on their own line, in the fixed order
    assert txt.startswith('timeline 31.20s') and pos == sorted(pos), pos
    assert 'check  coverage gap  FOUND 17.00-18.00' in txt and 'check  shot overlap  FOUND 22.50-23.00' in txt, txt
    assert len(bar(0, 31.2, 31.2)) == COLS and bar(0, 15.6, 31.2) == '█' * 20 + '·' * 20
    at = render(data, at=12.0)
    assert 'shot1' in at and 'shot2' not in at and 'nb' in at, at
    # a seam shot sharing a boundary is not an overlap
    shots['SHOTS'][2]['seam'] = True
    d2 = build_rows('.', cfg, tl, shots, None, None, [], {})
    assert {c['check']: c['ok'] for c in d2['checks']}['shot overlap'], d2['checks']
    print(txt); print('timeline selftest OK: kinds order / bars / inferred+default durations / coverage gap / shot overlap / --at / seam exemption')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
