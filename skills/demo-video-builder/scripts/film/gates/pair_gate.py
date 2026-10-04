# -*- coding: utf-8 -*-
"""pair_gate.py — start vs end of the same shot: the end frame is an EDIT of the start frame, not a new picture.  (qa_film.py plug-in)

Reads out/pairs/pairs.json (gates/snapshot.py --pairs) and STORYBOARD.md, and for every RECREATED beat compares the
two stills:

  pair anchors   layout anchors — the ink boxes in the top 35 % of the start frame (eyebrow, headline, mark) — sit
                 within 2 px (at 1080p) of the same place in the end frame. Pure pixels: each anchor box is located
                 again in the end frame by normalised cross-correlation inside a ±12 px search; a shift above 2 px
                 FAILS; an anchor that cannot be found at all is a WARN unless the beat's end: says it leaves.
  pair words     every word OCR reads on the end frame is in the storyboard's end: sentence, the beat's quoted
                 on-screen strings, screen:/motion:, or a claims.json phrase (numbers and 1–2 letter tokens are free):
                 an element on the end frame that the plan never named FAILS.
  pair roster    the named entities (Title-case tokens) of the end frame equal those of the start frame, unless the
                 end: sentence names the newcomer. A name that appears without the plan saying so FAILS.

OCR runs through the same backends the leak gate uses (gates/leak_gate.py pick_backend); without an engine the
two OCR gates PASS with a WARN note, never a silent pass. Product (recorded) beats are not compared — a product
screen scrolls and carries thousands of words by design.

qa.json: {"pair": {"anchor_px": 2, "search_px": 12, "top": 0.35, "min_box": 0.05}}
    python gates/pair_gate.py --selftest        synthetic frames + a stub OCR backend; no browser, no engine needed
"""
import json, os, re, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_NAMES = ['pair anchors', 'pair words', 'pair roster']
DEFAULTS = {'anchor_px': 2.0, 'search_px': 12, 'top': 0.35, 'min_box': 0.05, 'ink': 40}
STOP = set('a an the and or of to in on for with at by from as is are was were be it its this that these those we you they our your '
           'their one same every any all can will into than then there here what which who how not no yes now'.split())
LEAVES = re.compile(r'\b(gone|leaves|leave|left|exits?|disappears?|cleared|off)\b', re.I)


def _cfg(qa):
    c = dict(DEFAULTS); c.update({k: v for k, v in ((qa or {}).get('pair') or {}).items()}); return c


# ---------------------------------------------------------------- anchors (pixels)
def _grey(path, w=None):
    from PIL import Image
    im = Image.open(path).convert('L')
    return np.asarray(im, dtype=np.float32), im.size


def ink_boxes(g, top=0.35, min_box=0.05, ink=40):
    """boxes [x, y, w, h] of ink in the top band: rows/cols whose |pixel − background| > ink, grouped into bands then runs."""
    h, w = g.shape
    bg = float(np.median(g))
    band = g[:int(h * top)]
    mask = np.abs(band - bg) > ink
    rows = mask.any(axis=1)
    boxes, y = [], 0
    while y < len(rows):
        if not rows[y]:
            y += 1; continue
        y0 = y
        while y < len(rows) and (rows[y] or (y + 2 < len(rows) and rows[y + 1:y + 3].any())):
            y += 1
        sub = mask[y0:y].any(axis=0)
        x = 0
        while x < w:
            if not sub[x]:
                x += 1; continue
            x0 = x
            gap = max(6, int(0.02 * w))
            while x < w and (sub[x] or sub[x:x + gap].any()):
                x += 1
            if (x - x0) >= min_box * w and (y - y0) >= 3:
                boxes.append([x0, y0, x - x0, y - y0])
        y += 1
    return boxes


def locate(g_start, g_end, box, search=12):
    """where the start box sits in the end frame: (dx, dy, score) by normalised cross-correlation in a ±search window."""
    x, y, w, h = box
    T = g_start[y:y + h, x:x + w]
    T = T - T.mean()
    tn = float(np.sqrt((T ** 2).sum())) or 1.0
    best = (0, 0, -1.0)
    H, W = g_end.shape
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            yy, xx = y + dy, x + dx
            if yy < 0 or xx < 0 or yy + h > H or xx + w > W:
                continue
            P = g_end[yy:yy + h, xx:xx + w]
            P = P - P.mean()
            pn = float(np.sqrt((P ** 2).sum())) or 1.0
            sc = float((T * P).sum()) / (tn * pn)
            if sc > best[2]:
                best = (dx, dy, sc)
    return best


def check_anchors(start_path, end_path, end_text='', cfg=None):
    """(fails, warns, info) for one pair."""
    cfg = cfg or DEFAULTS
    gs, (w, h) = _grey(start_path); ge, _ = _grey(end_path)
    k = 1080.0 / h                                  # px at 1080p per frame px
    boxes = ink_boxes(gs, cfg['top'], cfg['min_box'], cfg['ink'])
    fails, warns, moved = [], [], []
    for b in boxes:
        dx, dy, sc = locate(gs, ge, b, int(cfg['search_px'] / k) + 1)
        if sc < 0.6:
            if not LEAVES.search(end_text or ''):
                warns.append('anchor at (%d,%d %dx%d) not found on the end frame (corr %.2f) — the end: line does not say it leaves' % (b[0], b[1], b[2], b[3], sc))
            continue
        shift = max(abs(dx), abs(dy)) * k
        moved.append(round(shift, 1))
        if shift > cfg['anchor_px'] + 1e-6:
            fails.append('anchor at (%d,%d %dx%d) moved %.1f px at 1080p (dx %+d, dy %+d; limit %g)' % (b[0], b[1], b[2], b[3], shift, dx, dy, cfg['anchor_px']))
    return fails, warns, {'anchors': len(boxes), 'max_shift': max(moved) if moved else 0.0}


# ---------------------------------------------------------------- words / roster (OCR)
def _words(s):
    return [w for w in re.findall(r"[A-Za-z][\w'’-]*", s or '')]


def _norm(w):
    return re.sub(r"[^a-z0-9]", '', w.lower())


def ocr_words(backend, path):
    from PIL import Image
    sys.path.insert(0, HERE)
    import leak_gate as LG
    lines = LG.ocr_image(backend, Image.open(path).convert('RGB'), 1920)
    return [w for ln in lines for w in _words(ln.get('text', ''))]


def check_words(end_words, allowed_text, claims_phrases=()):
    allowed = {_norm(w) for w in _words(allowed_text)} | {_norm(w) for p in claims_phrases for w in _words(p)}
    bad = []
    for w in end_words:
        n = _norm(w)
        if len(n) < 3 or n.isdigit() or n in STOP or n in allowed:
            continue
        if any(a.startswith(n) or n.startswith(a) for a in allowed if len(a) >= 4 and len(n) >= 4):
            continue
        bad.append(w)
    return sorted(set(bad))


def roster(words):
    return {_norm(w) for w in words if w[:1].isupper() and len(_norm(w)) >= 3 and _norm(w) not in STOP}


def check_roster(start_words, end_words, end_text):
    new = roster(end_words) - roster(start_words)
    named = roster(_words(end_text)) | {_norm(w) for w in _words(end_text)}
    return sorted(w for w in new if w not in named and not any(a.startswith(w) or w.startswith(a) for a in named if len(a) >= 4))


# ---------------------------------------------------------------- the gate
def _beats(ctx):
    project = ctx.get('project') or '.'
    sb = os.path.join(project, ((ctx.get('cfg') or {}).get('storyboard') or 'STORYBOARD.md'))
    if not os.path.exists(sb):
        return None
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
    import storyboard as SB
    man = SB.parse(open(sb, encoding='utf-8').read())
    if ctx.get('vo_phases'):
        try:
            SB.check(man, phases=ctx['vo_phases'], autonomous=True)
        except Exception:
            pass
    return man['beats']


def segments(project, beats):
    """[(label, start, end, start_beat, end_beat)] from out/pairs/pairs.json: each segment's START belongs to the beat that
    holds its start time, its END to the beat that holds its end time (the tail past the last beat belongs to the last beat)."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
    import review_pack as RP
    pj = os.path.join(project, 'out', 'pairs', 'pairs.json')
    d = RP._load_json(pj)
    if not d or not isinstance(d.get('pairs'), list):
        return None
    base = os.path.dirname(os.path.abspath(pj))
    fix = lambda f: f if os.path.isabs(f) else os.path.join(base, f)
    spans = [(b['number'], b.get('actual') or (b['t0'], b['t1'])) for b in beats]
    out = []
    for r in sorted(d['pairs'], key=lambda r: r.get('t0', 0)):
        if not (r.get('start') and r.get('end')):
            continue
        s = {'t': r['start']['t'], 'path': fix(r['start']['file'])}; e = {'t': r['end']['t'], 'path': fix(r['end']['file'])}
        out.append((r['label'], s, e, RP._beat_at(spans, float(s['t'])), RP._beat_at(spans, float(e['t']))))
    return out


def run(ctx, backend='auto'):
    project = ctx.get('project') or '.'
    cfg = _cfg(ctx.get('qa'))
    beats = _beats(ctx)
    if beats is None:
        return [(n, True, 'no STORYBOARD.md — nothing to compare') for n in GATE_NAMES]
    segs = segments(project, beats)
    if not segs:
        return [(n, True, 'no out/pairs/pairs.json — python gates/snapshot.py --pairs first') for n in GATE_NAMES]
    by_n = {b['number']: b for b in beats}
    # a segment is judged by the beat that owns its END frame (the frame the next cut lands on); recreated beats only
    rec = [(lab, s, e, by_n[eb]) for lab, s, e, sb, eb in segs if eb in by_n and by_n[eb].get('real') == 'recreated']
    if not rec:
        return [(n, True, 'no segment ends in a recreated beat') for n in GATE_NAMES]
    claims = ['Crafted with FDE Demo Builder by Ahmed Awan']          # the mandatory credit sits on the last frame of every film
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
        import credit as CR
        claims = [CR.CREDIT_TEXT.replace('·', ' ')]
    except Exception:
        pass
    cp = ctx.get('claims_json') or os.path.join(project, 'claims.json')
    if cp and os.path.exists(cp):
        try:
            claims += [c.get('phrase', '') for c in json.load(open(cp, encoding='utf-8')).get('claims', [])]
        except (OSError, ValueError):
            claims = []
    af, aw, info = [], [], []
    for lab, s, e, b in rec:
        f, w, i = check_anchors(s['path'], e['path'], b['fields'].get('end', ''), cfg)
        af += ['beat %02d (%s): %s' % (b['number'], lab, x) for x in f]; aw += ['beat %02d (%s): %s' % (b['number'], lab, x) for x in w]
        info.append('%02d/%s %d anchors ≤ %.1f px' % (b['number'], lab, i['anchors'], i['max_shift']))
    res = [('pair anchors', not af, '; '.join(af)[:400] if af else ('%s' % ', '.join(info)) + ('  WARN ' + ' | '.join(aw)[:200] if aw else ''))]
    be = backend
    if isinstance(backend, str):
        sys.path.insert(0, HERE)
        import leak_gate as LG
        be, note = LG.pick_backend(backend, fastest=True)
    if be is None:
        return res + [('pair words', True, 'WARN no OCR engine — words not compared (%s)' % note[:80]), ('pair roster', True, 'WARN no OCR engine — roster not compared')]
    wf, rf, n = [], [], 0
    for lab, s, e, b in rec:
        f = b['fields']
        sw, ew = ocr_words(be, s['path']), ocr_words(be, e['path'])
        n += 1
        allowed = ' '.join([f.get('end', ''), f.get('screen', ''), f.get('motion', ''), f.get('caption', ''), ' '.join(b.get('quotes') or [])])
        bad = check_words(ew, allowed, claims)
        if bad:
            wf.append('beat %02d (%s): on the end frame but not in the plan: %s' % (b['number'], lab, ', '.join(bad[:6])))
        # a newcomer is planned when the end: line, the beat's quoted on-screen strings or its screen: name it (or it is the credit)
        new = check_roster(sw, ew, ' '.join([f.get('end', ''), f.get('screen', ''), ' '.join(b.get('quotes') or []), ' '.join(claims)]))
        if new:
            rf.append('beat %02d (%s): names that arrive without the end: line saying so: %s' % (b['number'], lab, ', '.join(new[:6])))
    res.append(('pair words', not wf, '; '.join(wf)[:400] if wf else '%d segments ending in a recreated beat: every end-frame word is in the plan (%s)' % (n, getattr(be, 'name', 'ocr'))))
    res.append(('pair roster', not rf, '; '.join(rf)[:400] if rf else '%d pairs: same roster start → end (newcomers named)' % n))
    return res


# ---------------------------------------------------------------- selftest
class _StubOcr(object):
    """a backend that 'reads' the words we drew (keyed by file name) — tests the logic without an engine."""
    name, upscale = 'stub', 1

    def __init__(self, table):
        self.table = table
        self.current = None

    def recognize(self, im):
        return [{'text': self.table.get(self.current, ''), 'box': [0, 0, im.width, 20], 'conf': 1.0, 'words': None}]


def selftest():
    import tempfile, shutil
    from PIL import Image, ImageDraw
    d = tempfile.mkdtemp(prefix='pair_gate_')
    pd = os.path.join(d, 'out', 'pairs'); os.makedirs(pd)
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)

    def frame(path, kicker_x=60, headline=True, extra=None, shift=0):
        im = Image.new('L', (960, 540), 20); dr = ImageDraw.Draw(im)
        dr.rectangle([kicker_x, 40 + shift, kicker_x + 160, 56 + shift], fill=230)                     # the eyebrow
        if headline:
            dr.rectangle([60, 90 + shift, 520, 140 + shift], fill=235)                                  # the headline block
            for i in range(6):
                dr.rectangle([70 + i * 75, 100 + shift, 120 + i * 75, 130 + shift], fill=60)           # glyph texture inside it
        if extra:
            dr.rectangle(extra, fill=200)
        im.save(path, quality=92)
    a_s, a_e = os.path.join(pd, 'a_start.jpg'), os.path.join(pd, 'a_end.jpg')
    frame(a_s); frame(a_e, extra=[60, 300, 400, 340])                                                  # same anchors, a sub line lands
    b_s, b_e = os.path.join(pd, 'b_start.jpg'), os.path.join(pd, 'b_end.jpg')
    frame(b_s); frame(b_e, shift=3)                                                                     # the headline drifted 3 frame px = 6 px at 1080p
    c_s, c_e = os.path.join(pd, 'c_start.jpg'), os.path.join(pd, 'c_end.jpg')
    frame(c_s); frame(c_e, headline=False)                                                              # the headline leaves
    f, w, i = check_anchors(a_s, a_e, 'the headline with the sub line "Monday, answered." under it')
    t(not f and not w and i['anchors'] == 2 and i['max_shift'] <= 2.0, 'anchors: unchanged eyebrow + headline pass (%d anchors, max %.1f px)' % (i['anchors'], i['max_shift']))
    f, w, i = check_anchors(b_s, b_e, 'the same card')
    t(len(f) >= 1 and 'moved 6.0 px' in f[0], 'anchors: a 3-px drift (6 px at 1080p) fails (%s)' % (f[0][:60] if f else ''))
    f, w, i = check_anchors(c_s, c_e, 'the kicker alone, the headline gone')
    f2, w2, _ = check_anchors(c_s, c_e, 'the kicker alone')
    t(not f and not w and not f2 and len(w2) == 1, 'anchors: a vanished headline warns unless end: says it leaves')
    t(check_words(_words('Monday answered Acme fictional 3 Which regions'), 'the title "Monday, answered." and the caption Acme is fictional', ['Which regions missed']) == [],
      'words: end-frame words covered by end:, quotes and claims pass')
    bad = check_words(_words('Monday answered Quarterly Revenue 2026'), 'the title "Monday, answered."')
    t(bad == ['Quarterly', 'Revenue'], 'words: unplanned words fail (%s)' % bad)
    t(check_roster(_words('Every Monday Acme'), _words('Every Monday Acme Northwind'), 'the card now names Northwind as the customer') == [] and
      check_roster(_words('Every Monday Acme'), _words('Every Monday Acme Northwind'), 'the card settles') == ['northwind'], 'roster: a newcomer passes only when end: names it')
    # the whole gate on a tiny project with a stub OCR
    rows = [{'label': 'a', 't0': 0.0, 't1': 4.0, 'start': {'t': 0.1, 'file': a_s}, 'end': {'t': 3.9, 'file': a_e}},
            {'label': 'b', 't0': 4.0, 't1': 8.0, 'start': {'t': 4.1, 'file': b_s}, 'end': {'t': 7.9, 'file': b_e}}]
    json.dump({'total': 8.0, 'pairs': rows}, open(os.path.join(pd, 'pairs.json'), 'w'))
    open(os.path.join(d, 'STORYBOARD.md'), 'w', encoding='utf-8').write(
        '---\ntitle: t\nversion: 1\nduration: 8s\nmessage: "m"\n---\n## Locked\n- x\n\n## Beat 01 — A (0.0–4.0, ~4.0 s)\n- real: recreated\n- vo: a\n- screen: title "Monday, answered."\n'
        '- end: the title "Monday, answered." with the sub line "Acme is fictional" under it\n## Beat 02 — B (4.0–8.0, ~4.0 s)\n- real: recreated\n- vo: b\n- screen: card "One question"\n- end: the card settles\n')
    json.dump({'claims': [{'phrase': 'three regions', 'source': 'x'}]}, open(os.path.join(d, 'claims.json'), 'w'))
    stub = _StubOcr({a_s: 'Monday answered', a_e: 'Monday answered Acme is fictional three regions', b_s: 'One question', b_e: 'One question Northwind Revenue'})
    import pair_gate as PG
    orig = PG.ocr_words
    PG.ocr_words = lambda be, path: (setattr(be, 'current', path) or _words(be.table.get(path, '')))
    try:
        R = {n: (o, dd) for n, o, dd in PG.run({'project': d, 'cfg': {}, 'qa': {}, 'claims_json': os.path.join(d, 'claims.json')}, backend=stub)}
    finally:
        PG.ocr_words = orig
    t(not R['pair anchors'][0] and 'beat 02' in R['pair anchors'][1] and 'beat 01' not in R['pair anchors'][1], 'run(): anchors fail on beat 02 only')
    t(not R['pair words'][0] and 'beat 02' in R['pair words'][1] and 'Revenue' in R['pair words'][1] and 'beat 01' not in R['pair words'][1], 'run(): words fail on beat 02 (Northwind, Revenue), beat 01 covered by end: + claims')
    t(not R['pair roster'][0] and 'northwind' in R['pair roster'][1], 'run(): roster fails on the unnamed newcomer')
    R2 = {n: (o, dd) for n, o, dd in PG.run({'project': d, 'cfg': {}, 'qa': {}}, backend='none')}
    t(R2['pair words'][0] and 'WARN no OCR' in R2['pair words'][1] and R2['pair roster'][0], 'no OCR engine: words/roster pass with a WARN, anchors still measured')
    shutil.rmtree(d, ignore_errors=True)
    print('pair_gate selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.path.insert(0, HERE)
    if '--selftest' in sys.argv or len(sys.argv) < 2:
        sys.exit(selftest())
    proj = os.path.abspath(sys.argv[1])
    qa = json.load(open(os.path.join(proj, 'qa.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'qa.json')) else {}
    bad = 0
    for name, ok, dd in run({'project': proj, 'cfg': {}, 'qa': qa}):
        print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', dd)); bad += 0 if ok else 1
    sys.exit(1 if bad else 0)
