# -*- coding: utf-8 -*-
"""review_notes.py — the reviewer proposes, you choose: a ledger of whole-cut notes mapped to the edit.

    python tools/review_notes.py add     --t 12.4 --note "the push lands after the word" [--by name] [--kind rhythm|cut|grade|loop|other]
    python tools/review_notes.py import  notes.txt            one note per line: "12.4 text" | "0:12.4 text" | "t=12.4 text" | "[12.4] text"
    python tools/review_notes.py decide  N --accept | --reject --why "…"
    python tools/review_notes.py list | table                 table = the markdown block DELIVERY.md carries
    python tools/review_notes.py --selftest
      common: [--project DIR] [--notes out/review/review_notes.json] [--timeline out/timeline.json] [--json]

A whole-cut review (the demo-qa-reviewer agent's last pass, or a colleague watching the film) produces notes with
approximate timecodes: "around 12 s the cut feels early", "the grade jumps at the close". A timecode spoken from a
player is never a frame; the edit is. This tool snaps every note to the nearest boundary of the edit as
out/timeline.json knows it — a cut, a seam row, a shot start or end, the head or the tail — and keeps the note
beside that boundary with the distance it moved. Each note then carries a decision: accepted or rejected, and the
one-line reason. Rejections are first-class: a reviewer's eye proposes, the editor decides, and the next reader
sees both. tools/export.py share_pack prints the table into DELIVERY.md.

review_notes.json: {"film": name, "timeline": path, "notes": [{"n": 1, "t": 12.4, "shot": {"t": 12.37, "label": "cut 3",
"delta": 0.03}, "note": "…", "kind": "cut", "by": "…", "accepted": null|true|false, "why": "…"}]}
Stdlib only; never writes out/timeline.json.
"""
import argparse, json, os, re, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

KINDS = ('rhythm', 'cut', 'grade', 'loop', 'other')
LINE = re.compile(r'^\s*(?:\[|t=|@)?\s*(?:(\d+):)?(\d+(?:\.\d+)?)\s*(?:s|\])?\s*[-–—:]?\s*(.+?)\s*$')


def _load(p, default):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def boundaries(tl):
    """[(t, label)] — every place the edit changes: head, cuts, seam rows, shot starts/ends, tail. Sorted, deduplicated
    (a seam's id beats 'cut N', which beats a shot boundary at the same instant)."""
    if not tl:
        return [(0.0, 'head')]
    B = {}

    def put(t, label, rank):
        t = round(float(t), 3)
        if t not in B or rank < B[t][1]:
            B[t] = (label, rank)
    put(0.0, 'head', 3)
    if tl.get('total'):
        put(tl['total'], 'tail', 3)
    for i, c in enumerate(tl.get('cuts', []) or []):
        if isinstance(c, (int, float)):
            put(c, 'cut %d' % (i + 1), 1)
    for r in tl.get('seams', []) or []:
        if isinstance(r, dict) and isinstance(r.get('cut'), (int, float)):
            put(r['cut'], 'seam %s' % r.get('id', '?'), 0)
    for s in tl.get('shots', []) or []:
        if s.get('t0') is not None:
            put(s['t0'], '%s start' % (s.get('clip') or 'shot'), 2)
        if s.get('t1') is not None:
            put(s['t1'], '%s end' % (s.get('clip') or 'shot'), 2)
    return [(t, B[t][0]) for t in sorted(B)]


def nearest(t, bounds):
    """the boundary nearest to t → {'t', 'label', 'delta'} (delta = boundary − note, seconds)."""
    if not bounds:
        return {'t': t, 'label': '—', 'delta': 0.0}
    bt, lab = min(bounds, key=lambda b: abs(b[0] - t))
    return {'t': bt, 'label': lab, 'delta': round(bt - t, 3)}


def parse_line(line):
    """'12.4 text' | '0:12.4 text' | 't=12.4 text' | '[12.4] text' → (t, text) or None."""
    m = LINE.match(line)
    if not m or not m.group(3):
        return None
    t = float(m.group(2)) + (60.0 * int(m.group(1)) if m.group(1) else 0.0)
    return t, m.group(3)


class Notes:
    def __init__(self, project, notes_path=None, timeline_path=None):
        self.project = os.path.abspath(project)
        self.path = notes_path or os.path.join(self.project, 'out', 'review', 'review_notes.json')
        self.tl_path = timeline_path or os.path.join(self.project, 'out', 'timeline.json')
        cfg = _load(os.path.join(self.project, 'film.json'), {}) or {}
        self.doc = _load(self.path, None) or {'film': cfg.get('name', 'film'), 'timeline': os.path.relpath(self.tl_path, self.project).replace('\\', '/'), 'notes': []}
        self.tl = _load(self.tl_path, None)
        self.bounds = boundaries(self.tl)

    def add(self, t, note, by='', kind='other'):
        n = {'n': len(self.doc['notes']) + 1, 't': round(float(t), 3), 'shot': nearest(float(t), self.bounds), 'note': ' '.join(str(note).split()),
             'kind': kind if kind in KINDS else 'other', 'by': by or '', 'accepted': None, 'why': ''}
        self.doc['notes'].append(n)
        return n

    def decide(self, n, accepted, why):
        for x in self.doc['notes']:
            if x['n'] == int(n):
                x['accepted'] = bool(accepted); x['why'] = ' '.join(str(why or '').split())
                return x
        raise KeyError('note %s not found' % n)

    def remap(self):
        for x in self.doc['notes']:
            x['shot'] = nearest(float(x['t']), self.bounds)

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(self.doc, fh, indent=1, ensure_ascii=False, sort_keys=True); fh.write('\n')
        return self.path

    def counts(self):
        N = self.doc['notes']
        return {'total': len(N), 'accepted': sum(1 for x in N if x['accepted'] is True), 'rejected': sum(1 for x in N if x['accepted'] is False),
                'pending': sum(1 for x in N if x['accepted'] is None)}


def table(doc):
    """the markdown table (one row per note, decided or pending) + a one-line count."""
    N = (doc or {}).get('notes', [])
    if not N:
        return ''
    c = {'accepted': sum(1 for x in N if x['accepted'] is True), 'rejected': sum(1 for x in N if x['accepted'] is False), 'pending': sum(1 for x in N if x['accepted'] is None)}
    esc = lambda s: str(s or '').replace('|', '\\|')
    rows = ['| # | at | nearest boundary | kind | note | decision | why |', '|---|---|---|---|---|---|---|']
    for x in N:
        sh = x.get('shot') or {}
        dec = 'accepted' if x['accepted'] is True else ('rejected' if x['accepted'] is False else 'pending')
        rows.append('| %d | %.2f s | %s @ %.2f (%+.2f) | %s | %s | **%s** | %s |' % (x['n'], x['t'], esc(sh.get('label', '—')), sh.get('t', x['t']), sh.get('delta', 0.0),
                                                                                   esc(x.get('kind', 'other')), esc(x['note']), dec, esc(x.get('why', ''))))
    rows.append('')
    rows.append('%d notes — %d accepted, %d rejected, %d pending. The reviewer proposes; the editor decides and says why.' % (len(N), c['accepted'], c['rejected'], c['pending']))
    return '\n'.join(rows)


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix='review_notes_')
    os.makedirs(os.path.join(d, 'out'))
    json.dump({'total': 35.4, 'cuts': [7.4, 13.6, 21.8, 31.3], 'seams': [{'id': 'title→nb', 'cut': 13.6}, {'id': 'answer→close', 'cut': 31.3}],
               'shots': [{'clip': 'nb', 't0': 13.6, 't1': 21.8}, {'clip': 'q', 't0': 21.8, 't1': 27.2}, {'clip': 'send', 't0': 27.2, 't1': 31.3}]},
              open(os.path.join(d, 'out', 'timeline.json'), 'w'))
    json.dump({'name': 'film'}, open(os.path.join(d, 'film.json'), 'w'))
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    N = Notes(d)
    labels = [b[1] for b in N.bounds]
    t(labels == ['head', 'cut 1', 'seam title→nb', 'cut 3', 'q end', 'seam answer→close', 'tail'], 'boundaries: seam id beats cut N beats shot boundary (%s)' % labels)
    a = N.add(12.9, 'the title leaves too early', by='R', kind='cut')
    b = N.add(27.0, 'the send feels late', kind='rhythm')
    c = N.add(35.0, 'loop: the last frame does not match the first', kind='loop')
    t(a['shot']['label'] == 'seam title→nb' and abs(a['shot']['delta'] - 0.7) < 1e-6 and b['shot']['label'] == 'q end' and c['shot']['label'] == 'tail', 'notes snap to the nearest boundary with the distance moved')
    t(parse_line('0:12.4 cut early') == (12.4, 'cut early') and parse_line('t=3.5 - grade jumps') == (3.5, 'grade jumps') and parse_line('[27] late') == (27.0, 'late') and parse_line('no time here') is None, 'import line forms')
    N.decide(1, True, 'moved the exit 0.3 s later'); N.decide(2, False, 'the comma before the send is deliberate (SEAM.comma)')
    p = N.save()
    N2 = Notes(d)
    t(N2.counts() == {'total': 3, 'accepted': 1, 'rejected': 1, 'pending': 1} and N2.doc['notes'][1]['why'].startswith('the comma'), 'decisions persist in review_notes.json (%s)' % N2.counts())
    md = table(N2.doc)
    t('| 1 | 12.90 s | seam title→nb @ 13.60 (+0.70) | cut |' in md and '**rejected**' in md and '1 accepted, 1 rejected, 1 pending' in md, 'markdown table for DELIVERY.md')
    try:
        N2.decide(9, True, 'x'); t(False, 'decide on a missing note raises')
    except KeyError:
        t(True, 'decide on a missing note raises')
    json.dump({'total': 35.4, 'cuts': [7.4, 13.0, 21.8, 31.3]}, open(os.path.join(d, 'out', 'timeline.json'), 'w'))
    N3 = Notes(d); N3.remap()
    t(N3.doc['notes'][0]['shot']['label'] == 'cut 2' and abs(N3.doc['notes'][0]['shot']['t'] - 13.0) < 1e-6, 'remap after a VO regen moves the notes with the edit')
    shutil.rmtree(d, ignore_errors=True)
    print('review_notes selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ CLI
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='review_notes.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['add', 'import', 'decide', 'list', 'table', 'remap'])
    ap.add_argument('arg', nargs='?', help='import: the notes file · decide: the note number')
    ap.add_argument('--project', default=os.getcwd())
    ap.add_argument('--notes'); ap.add_argument('--timeline')
    ap.add_argument('--t', type=float); ap.add_argument('--note'); ap.add_argument('--by', default=''); ap.add_argument('--kind', default='other', choices=KINDS)
    ap.add_argument('--accept', action='store_true'); ap.add_argument('--reject', action='store_true'); ap.add_argument('--why', default='')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    N = Notes(a.project, a.notes, a.timeline)
    if N.tl is None:
        print('note: no %s — notes keep their raw time until export_timeline.js has run (then `remap`)' % os.path.relpath(N.tl_path, N.project), file=sys.stderr)
    if a.cmd == 'add':
        if a.t is None or not a.note:
            print('add needs --t <seconds> --note "…"', file=sys.stderr); return 2
        n = N.add(a.t, a.note, a.by, a.kind); N.save()
        print('note %d @ %.2f s → %s @ %.2f (%+.2f s): %s' % (n['n'], n['t'], n['shot']['label'], n['shot']['t'], n['shot']['delta'], n['note'])); return 0
    if a.cmd == 'import':
        if not a.arg or not os.path.exists(a.arg):
            print('import needs a notes file', file=sys.stderr); return 2
        k = 0
        for line in open(a.arg, encoding='utf-8'):
            p = parse_line(line)
            if p:
                N.add(p[0], p[1], a.by, a.kind); k += 1
        N.save(); print('imported %d notes → %s' % (k, os.path.relpath(N.path, N.project))); return 0
    if a.cmd == 'decide':
        if not a.arg or a.accept == a.reject:
            print('decide N --accept | --reject --why "…"', file=sys.stderr); return 2
        if not a.why:
            print('say why — the reason is the point of the ledger', file=sys.stderr); return 2
        x = N.decide(a.arg, a.accept, a.why); N.save()
        print('note %d %s: %s' % (x['n'], 'accepted' if x['accepted'] else 'rejected', x['why'])); return 0
    if a.cmd == 'remap':
        N.remap(); N.save(); print('remapped %d notes to %s' % (len(N.doc['notes']), os.path.relpath(N.tl_path, N.project))); return 0
    if a.cmd == 'table':
        print(table(N.doc) or '(no notes)'); return 0
    if a.json:
        print(json.dumps(dict(N.doc, counts=N.counts()), indent=1, ensure_ascii=False)); return 0
    for x in N.doc['notes']:
        dec = 'accepted' if x['accepted'] is True else ('rejected' if x['accepted'] is False else 'pending ')
        print('  %2d  %6.2f s  → %-22s %+.2f  %-8s %s%s' % (x['n'], x['t'], x['shot']['label'][:22], x['shot']['delta'], dec, x['note'][:70], ('  — ' + x['why'][:60]) if x['why'] else ''))
    c = N.counts()
    print('%d notes — %d accepted, %d rejected, %d pending' % (c['total'], c['accepted'], c['rejected'], c['pending']))
    return 1 if c['pending'] else 0


if __name__ == '__main__':
    sys.exit(main())
