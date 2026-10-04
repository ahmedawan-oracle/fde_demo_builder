# -*- coding: utf-8 -*-
"""annotate_gate.py — qa_film.py plug-in: the hand-drawn layer points at evidence and never writes over product text;
glass stays inside its budget; a light leak lives only in a seam window.

    python gates/annotate_gate.py --selftest        (synthetic still + ledgers, node lib/annotate.js geometry, < 10 s)

Ledgers (gates/_receipts.py reads them from the mounted scene, or out/scene_receipts.json):
    annot  ANNOTATE.ledger()  [{kind, rect {x,y,w,h} in FOOTAGE px, at, drawEnd, until, seed, text, clip?, t?}]
    glass  GLASS.ledger()     [{id, variant, rect (stage px), window [t0,t1], at, until}]
    light  LIGHT.ledger()     {blooms:[{at, until, peak}], leaks:[{at, end, window}], sweeps:[...]}
Evidence: claims.json "figures": [{id, rect [x,y,w,h] | {x,y,w,h} (source px), clip?, source}] and the recording's
own clicks from events.jsonl (tools/record_events.py: {"type":"down","x","y","t"}; qa.json "events", default
events.jsonl, or film.json "events").

Gates (GATE_NAMES, in order):
  annot evidence   every circle / arrow / box / underline / strike / label rect overlaps a claims figure or holds a logged
                   click within 12 px (ANNOTATE.lint's rule); spotlights frame, they do not point, and are exempt. More
                   than two strokes drawing at once is a finding (marks_stacked).
  annot ink        the stroke band of every stroke mark (the path lib/annotate.js draws, dilated by 3 footage px) crosses
                   no product text: on the clip's own still (broll/<clip>/f_001.jpg, footage -> still px through the clip
                   crop) the share of band pixels whose luma differs from the local background by > 64 levels (dark ink on
                   a light UI, light ink on a dark one) must stay <= qa.annot_ink_max (0.15). The clip comes from the mark's
                   `clip`, the matched figure's `clip`, the footage shot on screen at the mark's film time `t`/`at`, or
                   the only clip in clips.json; page clips are noted, not measured.
  glass budget     GLASS.lint in Python: <= qa.glass_max (2) panels visible at once, no panel reaching the caption lane
                   (stage y >= 570), none off the stage.
  light leak       LIGHT.lint in Python: every leak <= 0.5 s and inside its declared window; that window sits inside a
                   seam window of out/timeline.json (+-0.05 s) when seams exist; bloom peaks <= 0.45.

A scene that loads none of lib/annotate.js, lib/glass.js, lib/light.js passes with 'no marks'. A scene that loads
them but yields no receipts fails 'annot evidence' with the probe's note (the gate never guesses).
qa.json keys: annot_ink_max 0.15, annot_tol 12, glass_max 2, caption_lane_y 570, "events", "claims", "clips".
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GATE_NAMES = ['annot evidence', 'annot ink', 'glass budget', 'light leak']
DEFAULTS = {'annot_ink_max': 0.15, 'annot_tol': 12.0, 'glass_max': 2, 'caption_lane_y': 570.0}
STROKES = ('circle', 'arrow', 'box', 'underline', 'strike')
BAND_PX, INK_DELTA, LEAK_MAX, BLOOM_CEIL = 3.0, 64, 0.5, 0.45


# ----------------------------------------------------------------------------------------------- geometry
def R(r):
    return {'x': float(r[0]), 'y': float(r[1]), 'w': float(r[2]), 'h': float(r[3])} if isinstance(r, (list, tuple)) else \
        {'x': float(r['x']), 'y': float(r['y']), 'w': float(r['w']), 'h': float(r['h'])}


def overlap(a, b):
    return a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']


def hit(r, p, tol):
    return r['x'] - tol <= p[0] <= r['x'] + r['w'] + tol and r['y'] - tol <= p[1] <= r['y'] + r['h'] + tol


def evidence_findings(marks, figures, clicks, tol=12.0):
    """ANNOTATE.lint's rule in Python: [(i, kind, message)]."""
    out = []
    for i, m in enumerate(marks):
        if m.get('kind') == 'spotlight':
            continue
        r = R(m['rect'])
        if (figures or clicks) and not any(overlap(r, R(f['rect'])) for f in figures) and not any(hit(r, p, tol) for p in clicks):
            out.append((i, m.get('kind'), '%s at %.2f s sits on no claims figure and no logged click' % (m.get('kind'), float(m.get('at', 0)))))
        elif not figures and not clicks:
            out.append((i, m.get('kind'), '%s at %.2f s: no evidence lists (claims.json figures / events.jsonl)' % (m.get('kind'), float(m.get('at', 0)))))
    strokes = [m for m in marks if m.get('kind') not in ('spotlight', 'label')]
    for m in strokes:
        n = sum(1 for x in strokes if float(x.get('at', 0)) < float(m.get('drawEnd', 0)) and float(m.get('at', 0)) < float(x.get('drawEnd', 0)))
        if n > 2:
            out.insert(0, (-1, 'stack', '%d marks drawing at once around %.2f s (max 2)' % (n, float(m.get('at', 0)))))
            break
    return out


def _annotate_js(project):
    for p in (os.path.join(project, 'scenes', 'lib', 'annotate.js'), os.path.join(FILM_DIR, 'lib', 'annotate.js')):
        if os.path.exists(p):
            return p
    return None


def path_points(d, per_seg=10):
    """Sample an SVG path of M/L/C/Q commands (absolute) into [(x, y)]."""
    pts, cur = [], None
    for cmd, body in re.findall(r'([MLCQZ])([^MLCQZ]*)', d):
        nums = [float(v) for v in re.findall(r'-?\d*\.?\d+(?:e-?\d+)?', body)]
        if cmd == 'M' and len(nums) >= 2:
            cur = (nums[0], nums[1]); pts.append(cur)
        elif cmd == 'L':
            for i in range(0, len(nums) - 1, 2):
                nxt = (nums[i], nums[i + 1])
                for k in range(1, per_seg + 1):
                    u = k / per_seg; pts.append((cur[0] + (nxt[0] - cur[0]) * u, cur[1] + (nxt[1] - cur[1]) * u))
                cur = nxt
        elif cmd == 'C':
            for i in range(0, len(nums) - 5, 6):
                p1, p2, p3 = (nums[i], nums[i + 1]), (nums[i + 2], nums[i + 3]), (nums[i + 4], nums[i + 5])
                for k in range(1, per_seg + 1):
                    u = k / per_seg; v = 1 - u
                    pts.append((v ** 3 * cur[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u ** 3 * p3[0],
                                v ** 3 * cur[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u ** 3 * p3[1]))
                cur = p3
        elif cmd == 'Q':
            for i in range(0, len(nums) - 3, 4):
                p1, p2 = (nums[i], nums[i + 1]), (nums[i + 2], nums[i + 3])
                for k in range(1, per_seg + 1):
                    u = k / per_seg; v = 1 - u
                    pts.append((v * v * cur[0] + 2 * v * u * p1[0] + u * u * p2[0], v * v * cur[1] + 2 * v * u * p1[1] + u * u * p2[1]))
                cur = p2
    return pts


def fallback_points(kind, r, frm=None, n=160):
    """Geometry without node: ellipse at pad 1.22, box at pad 6, underline 6 px below, strike through the centre, arrow straight."""
    cx, cy = r['x'] + r['w'] / 2, r['y'] + r['h'] / 2
    if kind == 'circle':
        a, b = r['w'] * 1.22 / 2, r['h'] * 1.22 / 2
        return [(cx + a * math.cos(2 * math.pi * i / n), cy + b * math.sin(2 * math.pi * i / n)) for i in range(n)]
    if kind == 'box':
        x0, y0, x1, y1 = r['x'] - 6, r['y'] - 6, r['x'] + r['w'] + 6, r['y'] + r['h'] + 6
        per = [(x0 + (x1 - x0) * i / n, y0) for i in range(n)] + [(x1, y0 + (y1 - y0) * i / n) for i in range(n)]
        return per + [(x1 - (x1 - x0) * i / n, y1) for i in range(n)] + [(x0, y1 - (y1 - y0) * i / n) for i in range(n)]
    if kind == 'underline':
        return [(r['x'] + r['w'] * i / n, r['y'] + r['h'] + 6) for i in range(n + 1)]
    if kind == 'strike':
        return [(r['x'] + r['w'] * i / n, cy) for i in range(n + 1)]
    fx, fy = frm if frm else (r['x'] + r['w'] + 120, r['y'] + r['h'] + 90)
    tx, ty = min(max(fx, r['x']), r['x'] + r['w']), min(max(fy, r['y']), r['y'] + r['h'])
    return [(fx + (tx - fx) * i / n, fy + (ty - fy) * i / n) for i in range(n + 1)]


def stroke_points(project, m):
    """Points along the mark's drawn path in footage px (node lib/annotate.js --shape; pure fallback when node fails)."""
    r = R(m['rect'])
    js = _annotate_js(project)
    if js:
        cmd = ['node', js, '--shape', m['kind'], '--rect', '%g,%g,%g,%g' % (r['x'], r['y'], r['w'], r['h']), '--seed', str(m.get('seed', 7)), '--variants', '1']
        if m.get('from'):
            cmd += ['--from', '%g,%g' % tuple(m['from'])]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            s = p.stdout.strip()
            doc = json.loads(s[s.index('{'):]) if '{' in s else {}
            paths = doc.get('variants') or ([doc['path']] if doc.get('path') else [])
            pts = []
            for d in paths:
                if isinstance(d, str):
                    pts += path_points(d)
                elif isinstance(d, dict):
                    for v in d.values():
                        if isinstance(v, str) and v.startswith('M'):
                            pts += path_points(v)
            if pts:
                return pts, 'annotate.js'
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return fallback_points(m['kind'], r, m.get('from')), 'fallback geometry'


def ink_density(still_gray, pts, band=BAND_PX, delta=INK_DELTA):
    """Share of band pixels (within `band` px of the sampled path, still px) whose luma is > delta from the local
    background (median of the path's neighbourhood). (density, band pixel count)."""
    H, W = still_gray.shape
    mask = np.zeros((H, W), dtype=bool)
    rb = int(math.ceil(band))
    yy, xx = np.mgrid[-rb:rb + 1, -rb:rb + 1]
    disc = (xx * xx + yy * yy) <= band * band
    for x, y in pts:
        ix, iy = int(round(x)), int(round(y))
        if -rb <= ix < W + rb and -rb <= iy < H + rb:
            y0, y1, x0, x1 = max(0, iy - rb), min(H, iy + rb + 1), max(0, ix - rb), min(W, ix + rb + 1)
            if y1 > y0 and x1 > x0:
                mask[y0:y1, x0:x1] |= disc[(y0 - iy + rb):(y1 - iy + rb), (x0 - ix + rb):(x1 - ix + rb)]
    n = int(mask.sum())
    if n == 0:
        return 0.0, 0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    pad = 24
    x0, x1 = max(0, int(min(xs)) - pad), min(W, int(max(xs)) + pad + 1)
    y0, y1 = max(0, int(min(ys)) - pad), min(H, int(max(ys)) + pad + 1)
    bg = float(np.median(still_gray[y0:y1, x0:x1])) if y1 > y0 and x1 > x0 else float(np.median(still_gray))
    ink = np.abs(still_gray[mask].astype(np.int16) - bg) > delta
    return float(ink.mean()), n


def to_still_px(pts, clip):
    """Footage (source) px -> still px for still/seq clips through the clip crop (page clips return None)."""
    if clip.get('kind') == 'page':
        return None
    c = clip.get('crop') or [0, 0, 1920, 1080]
    k = 1.0                                     # extract_clips.py writes the crop at source resolution
    return [((x - c[0]) * k, (y - c[1]) * k) for x, y in pts]


def load_clicks(path):
    pts = []
    if path and os.path.exists(path):
        for line in open(path, encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('type') in ('down', 'click') and e.get('x') is not None:
                pts.append((float(e['x']), float(e['y']), float(e.get('t', 0))))
    return pts


def glass_findings(panels, max_panels=2, lane_y=570.0, W=1280, H=720):
    out, edges = [], []
    for p in panels:
        r = R(p['rect'])
        if r['y'] + r['h'] > lane_y:
            out.append('%s reaches y=%g (caption lane from %g)' % (p.get('id'), r['y'] + r['h'], lane_y))
        if r['x'] < 0 or r['y'] < 0 or r['x'] + r['w'] > W or r['y'] + r['h'] > H:
            out.append('%s leaves the stage' % p.get('id'))
        w = p.get('window') or [-1e9, 1e9]
        edges += [(float(w[0]), 1), (float(w[1]), -1)]
    edges.sort()
    n = worst = 0; at = None
    for t, d in edges:
        n += d
        if n > worst:
            worst, at = n, t
    if worst > max_panels:
        out.append('%d panels visible at once from t=%s (max %d)' % (worst, at, max_panels))
    return out


def light_findings(led, seam_windows=None):
    out = []
    for i, l in enumerate((led or {}).get('leaks') or []):
        at, end = float(l['at']), float(l['end'])
        if end - at > LEAK_MAX + 1e-6:
            out.append('leak %d lasts %.2f s (max %.1f)' % (i, end - at, LEAK_MAX))
        w = l.get('window')
        if w and (at < float(w[0]) - 1e-6 or end > float(w[1]) + 1e-6):
            out.append('leak %d leaves its window %s' % (i, w))
        if w and seam_windows and not any(float(w[0]) >= s0 - 0.05 and float(w[1]) <= s1 + 0.05 for s0, s1 in seam_windows):
            out.append('leak %d window %s is not inside a declared seam window' % (i, w))
    for i, b in enumerate((led or {}).get('blooms') or []):
        if float(b.get('peak', 0)) > BLOOM_CEIL + 1e-6:
            out.append('bloom %d peak %s > %.2f' % (i, b.get('peak'), BLOOM_CEIL))
    return out


# ----------------------------------------------------------------------------------------------- the gate
def run(ctx):
    P, Q, C, TL = ctx['project'], ctx.get('qa') or {}, ctx.get('cfg') or {}, ctx.get('timeline') or {}
    K = dict(DEFAULTS); K.update({k: Q[k] for k in DEFAULTS if k in Q})
    import _receipts
    libs = [l for l in ('annotate', 'glass', 'light') if _receipts.uses(ctx, l)]
    Rc = ctx.get('_ledgers')                                   # tests inject ledgers directly
    note = 'injected'
    if Rc is None:
        if not libs:
            return [(n, True, 'no marks: the scene loads none of lib/annotate.js, lib/glass.js, lib/light.js') for n in GATE_NAMES]
        Rc, note = _receipts.load(ctx)
        if Rc is None:
            return [(GATE_NAMES[0], False, 'scene loads lib/%s.js but no receipts: %s' % ('/'.join(libs), note))] + [(n, False, 'no receipts') for n in GATE_NAMES[1:]]
    marks = Rc.get('annot') or []
    claims_p = os.path.join(P, Q.get('claims', 'claims.json'))
    figures = []
    if os.path.exists(claims_p):
        doc = json.load(open(claims_p, encoding='utf-8'))
        figures = [f for f in (doc.get('figures') or []) if f.get('rect')]
    ev = Q.get('events') or C.get('events') or 'events.jsonl'
    clicks3 = load_clicks(os.path.join(P, ev))
    clicks = [(x, y) for x, y, _ in clicks3]
    res = []
    if not marks:
        res.append(('annot evidence', True, 'no annotation marks (%s)' % note))
        res.append(('annot ink', True, 'no stroke marks'))
    else:
        bad = evidence_findings(marks, figures, clicks, float(K['annot_tol']))
        res.append(('annot evidence', not bad, ('%s; ' % [b[2] for b in bad[:3]] if bad else '') + '%d marks vs %d figures, %d clicks' % (len(marks), len(figures), len(clicks))))
        clips_p = os.path.join(P, Q.get('clips', 'clips.json'))
        clips = {c['name']: c for c in json.load(open(clips_p, encoding='utf-8'))} if os.path.exists(clips_p) else {}
        shots = TL.get('shots') or []
        footage_clips = [n for n in clips if clips[n].get('kind') in ('still', 'seq', 'page')]
        ink_bad, notes, n_ok, src_used = [], [], 0, set()
        for i, m in enumerate(marks):
            if m.get('kind') not in STROKES:
                continue
            r = R(m['rect'])
            name = m.get('clip')
            if not name:
                fig = next((f for f in figures if f.get('clip') and overlap(r, R(f['rect']))), None)
                name = fig['clip'] if fig else None
            if not name:
                t = m.get('t', m.get('at'))
                sh = next((s for s in shots if s.get('t0') is not None and float(s['t0']) <= float(t) < float(s.get('t1') or 1e9)), None) if t is not None else None
                name = sh['clip'] if sh else None
            if not name and len(footage_clips) == 1:
                name = footage_clips[0]
            clip = clips.get(name)
            if not clip:
                notes.append('mark %d (%s): clip unresolved — give the mark `clip` or the figure `clip`' % (i, m.get('kind'))); continue
            if clip.get('kind') == 'page':
                notes.append('mark %d on page clip %s not measured' % (i, name)); continue
            still_p = os.path.join(P, 'broll', name, 'f_001.jpg')
            if not os.path.exists(still_p):
                notes.append('mark %d: %s missing' % (i, os.path.relpath(still_p, P))); continue
            from PIL import Image
            with Image.open(still_p) as im:
                g = np.asarray(im.convert('L'), dtype=np.int16)
            pts, src = stroke_points(P, m)
            src_used.add(src)
            spts = to_still_px(pts, clip)
            dens, n = ink_density(g, spts)
            if dens > float(K['annot_ink_max']):
                ink_bad.append((i, m.get('kind'), name, round(dens, 3)))
            else:
                n_ok += 1
        d = '%d stroke(s) clear of product text (ink <= %.2f, band %g px, %s)' % (n_ok, float(K['annot_ink_max']), BAND_PX, '/'.join(sorted(src_used)) or 'no geometry')
        if ink_bad:
            d = 'stroke crosses product text (mark, kind, clip, ink share) %s; ' % ink_bad[:3] + d
        if notes:
            d += '; ' + '; '.join(notes[:2])
        res.append(('annot ink', not ink_bad, d))
    panels = Rc.get('glass') or []
    gb = glass_findings(panels, int(K['glass_max']), float(K['caption_lane_y']))
    res.append(('glass budget', not gb, '; '.join(gb)[:200] if gb else '%d panel(s) within the budget (<= %d at once, above y=%g)' % (len(panels), int(K['glass_max']), float(K['caption_lane_y']))))
    seams = [(float(w['t0']), float(w['t1'])) for w in TL.get('seams') or [] if isinstance(w, dict) and 't0' in w and 't1' in w]
    seams += [(float(g['at']), float(g['at']) + float(g['dur'])) for g in TL.get('glSeams') or [] if 'at' in g and 'dur' in g]
    lf = light_findings(Rc.get('light') or {}, seams or None)
    L = Rc.get('light') or {}
    res.append(('light leak', not lf, '; '.join(lf)[:200] if lf else '%d leak(s) <= %.1f s inside their seam windows, %d bloom(s) <= %.2f' % (len(L.get('leaks') or []), LEAK_MAX, len(L.get('blooms') or []), BLOOM_CEIL)))
    return res


# ----------------------------------------------------------------------------------------------- selftest
def _ui_still(w=1920, h=1080):
    """A fictional light UI: dark text rows on the left, one KPI figure box at the right, empty margin below."""
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (w, h), (250, 250, 248))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 60], fill=(14, 124, 134))
    for row in range(12):
        y = 110 + row * 52
        d.rectangle([60, y, 60 + 700, y + 16], fill=(40, 44, 52))
    d.rectangle([1200, 200, 1500, 320], fill=(232, 240, 254), outline=(14, 124, 134), width=3)
    d.rectangle([1260, 240, 1440, 280], fill=(40, 44, 52))      # the KPI figure glyphs
    return im


def _selftest():
    import time
    T0 = time.time()
    tmp = tempfile.mkdtemp(prefix='annotgate_')
    os.makedirs(os.path.join(tmp, 'broll', 'nb'))
    _ui_still().save(os.path.join(tmp, 'broll', 'nb', 'f_001.jpg'), quality=92)
    json.dump([{'name': 'nb', 'kind': 'still', 'crop': [0, 0, 1920, 1080]}], open(os.path.join(tmp, 'clips.json'), 'w'))
    KPI = {'x': 1260, 'y': 240, 'w': 180, 'h': 40}
    json.dump({'claims': [], 'figures': [{'id': 'kpi', 'rect': [1260, 240, 180, 40], 'clip': 'nb', 'source': 'KPI tile'}]}, open(os.path.join(tmp, 'claims.json'), 'w'))
    open(os.path.join(tmp, 'events.jsonl'), 'w').write('{"type":"meta","screen":[1920,1080]}\n{"t":4.2,"x":400,"y":900,"type":"down","button":"left"}\n')
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok = ok and bool(cond)
        print('  %-50s %s  %s' % (label, 'PASS' if cond else 'FAIL', str(detail)[:120]))
    good = {'annot': [{'kind': 'circle', 'rect': KPI, 'at': 3.0, 'drawEnd': 3.45, 'until': 8, 'seed': 11},
                      {'kind': 'label', 'rect': KPI, 'at': 3.4, 'drawEnd': 3.75, 'until': 8, 'text': 'open claims'},
                      {'kind': 'box', 'rect': {'x': 380, 'y': 880, 'w': 60, 'h': 40}, 'at': 4.2, 'drawEnd': 4.65, 'until': 8, 'seed': 3},
                      {'kind': 'spotlight', 'rect': {'x': 0, 'y': 0, 'w': 400, 'h': 300}, 'at': 0, 'drawEnd': 0.35, 'until': 8}],
            'glass': [{'id': 'why', 'variant': 'light', 'rect': {'x': 700, 'y': 400, 'w': 440, 'h': 150}, 'window': [10, 20]}],
            'light': {'blooms': [{'at': 0.1, 'until': 6, 'peak': 0.30}], 'leaks': [{'at': 12.05, 'end': 12.5, 'window': [12.0, 12.55]}], 'sweeps': []}}
    TL = {'shots': [{'clip': 'nb', 't0': 1.0, 't1': 9.0}], 'seams': [{'id': 'x', 'cut': 12.3, 't0': 11.96, 't1': 12.72}]}
    base = {'project': tmp, 'qa': {}, 'cfg': {}, 'timeline': TL, 'scene_html': None}
    Rr = {n: (o, d) for n, o, d in run(dict(base, _ledgers=good))}
    for n in GATE_NAMES:
        print('    %-16s %s  %s' % (n, 'PASS' if Rr[n][0] else 'FAIL', Rr[n][1][:110]))
    check('good: marks on the figure / the click pass evidence', Rr['annot evidence'][0], Rr['annot evidence'][1])
    check('good: circle around the figure clears the text', Rr['annot ink'][0] and 'annotate.js' in Rr['annot ink'][1], Rr['annot ink'][1])
    check('good: one glass panel in budget', Rr['glass budget'][0], Rr['glass budget'][1])
    check('good: leak inside its seam window', Rr['light leak'][0], Rr['light leak'][1])
    bad = {'annot': [{'kind': 'circle', 'rect': {'x': 800, 'y': 700, 'w': 100, 'h': 40}, 'at': 3.0, 'drawEnd': 3.45, 'until': 8, 'seed': 1},
                     {'kind': 'strike', 'rect': {'x': 60, 'y': 110, 'w': 700, 'h': 16}, 'at': 3.1, 'drawEnd': 3.55, 'until': 8, 'seed': 2, 'clip': 'nb'},
                     {'kind': 'underline', 'rect': {'x': 60, 'y': 110, 'w': 700, 'h': 16}, 'at': 3.2, 'drawEnd': 3.65, 'until': 8, 'seed': 2, 'clip': 'nb'},
                     {'kind': 'box', 'rect': {'x': 60, 'y': 110, 'w': 700, 'h': 16}, 'at': 3.3, 'drawEnd': 3.75, 'until': 8, 'seed': 2, 'clip': 'nb'}],
           'glass': [{'id': 'a', 'rect': {'x': 0, 'y': 100, 'w': 400, 'h': 500}, 'window': [1, 5]}, {'id': 'b', 'rect': {'x': 0, 'y': 0, 'w': 400, 'h': 200}, 'window': [1, 5]},
                     {'id': 'c', 'rect': {'x': 1000, 'y': 0, 'w': 400, 'h': 200}, 'window': [2, 5]}],
           'light': {'blooms': [{'at': 0, 'until': 3, 'peak': 0.6}], 'leaks': [{'at': 20.0, 'end': 20.7, 'window': [20.0, 20.7]}], 'sweeps': []}}
    Rr = {n: (o, d) for n, o, d in run(dict(base, _ledgers=bad))}
    for n in GATE_NAMES:
        print('    %-16s %s  %s' % (n, 'PASS' if Rr[n][0] else 'FAIL', Rr[n][1][:110]))
    check('bad: mark off evidence + 3 strokes stacked fail', not Rr['annot evidence'][0] and 'no claims figure' in Rr['annot evidence'][1] and 'at once' in Rr['annot evidence'][1], Rr['annot evidence'][1])
    check('bad: strike through a text row crosses ink', not Rr['annot ink'][0] and 'strike' in Rr['annot ink'][1], Rr['annot ink'][1])
    check('bad: 3 panels, lane reach, off stage', not Rr['glass budget'][0] and 'at once' in Rr['glass budget'][1] and 'caption lane' in Rr['glass budget'][1] and 'leaves' in Rr['glass budget'][1], Rr['glass budget'][1])
    check('bad: leak 0.7 s outside any seam, bloom over ceiling', not Rr['light leak'][0] and 'lasts' in Rr['light leak'][1] and 'not inside' in Rr['light leak'][1] and 'bloom' in Rr['light leak'][1], Rr['light leak'][1])
    Rr = {n: (o, d) for n, o, d in run(dict(base, _ledgers={'annot': [], 'glass': [], 'light': {}}))}
    check('empty ledgers pass', all(o for o, _ in Rr.values()))
    scene = os.path.join(tmp, 'plain.html'); open(scene, 'w').write('<script src="lib/footage.js"></script>')
    Rr = {n: (o, d) for n, o, d in run(dict(base, scene_html=scene))}
    check('scene without the libs -> no marks PASS', all(o for o, _ in Rr.values()) and 'no marks' in Rr['annot evidence'][1])
    scene2 = os.path.join(tmp, 'libs.html'); open(scene2, 'w').write('<script src="lib/annotate.js"></script>')
    Rr = {n: (o, d) for n, o, d in run(dict(base, scene_html=scene2, _receipts=(None, 'probe off in selftest')))}
    check('libs loaded but no receipts -> FAIL with the note', not Rr['annot evidence'][0] and 'probe off' in Rr['annot evidence'][1], Rr['annot evidence'][1])
    pts = path_points('M0 0C0 10 10 10 10 0L20 0')
    check('path_points samples C and L', len(pts) == 21 and abs(pts[-1][0] - 20) < 1e-9 and abs(pts[10][0] - 10) < 1e-9, len(pts))
    g = np.asarray(_ui_still().convert('L'), dtype=np.int16)
    d_text, _ = ink_density(g, fallback_points('strike', R([60, 110, 700, 16])))
    d_clear, _ = ink_density(g, fallback_points('circle', R(KPI)))
    check('ink_density (fallback geometry): strike through text %.2f, circle around figure %.2f' % (d_text, d_clear), d_text > 0.5 and d_clear < 0.5)
    check('load_clicks reads down events', load_clicks(os.path.join(tmp, 'events.jsonl')) == [(400.0, 900.0, 4.2)])
    print('\n%s  (%.1f s)  %s' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', time.time() - T0, tmp))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
