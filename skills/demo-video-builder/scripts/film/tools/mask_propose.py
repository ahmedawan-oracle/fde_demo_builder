# -*- coding: utf-8 -*-
"""mask_propose.py — turn leaks.json hits into the blur fixes clips.json already understands (v5, leak-gate area).

    python tools/mask_propose.py leaks.json [--clips clips.json] [--out leaks.masks.json] [--feather 6] [--all]
    python tools/mask_propose.py leaks.json --apply           merge the proposal into clips.json (clips.json.bak kept)
    python tools/mask_propose.py leaks.json --verify          blur copies of the hit frames and re-scan them
    python tools/mask_propose.py --selftest
    exit 0 ok · 1 findings (verify left legible text / nothing to propose) · 2 usage

WHAT A MASK IS HERE. extract_clips.py applies `fix: [{"blur": [x, y, w, h, r]}]` to a clip after assembly — clip px
on stills and seqs (origin = the crop), doc px on pages (origin = the band), frame px under `chrome.fix` for the
chrome_k.jpg frames. The blur is a Gaussian of radius r over the box, pasted back; it is the one privacy edit the
footage lane allows (never a white box, never a redraw). This tool writes exactly those entries, as a PROPOSAL the
author reads and accepts with --apply, then re-runs extract_clips.py so the blur lands in the pixels and
gates/leak_gate.py passes.

RULES, MEASURED
  feather   every hit box grows by 6 px on each side (--feather) so antialiased edges and the OCR box's own slack
            are inside the blur; boxes that then touch or overlap on the same clip and coordinate space merge into
            one entry (one blur per cluster reads calmer than five adjacent ones).
  radius    text: r = max(6, ceil(0.45 x text height)). Pillow's GaussianBlur(radius) has sigma = radius; at 0.45 x
            the glyph height the strokes of a 14-24 px UI line fuse into a grey band that neither OCR engine reads
            (the selftest renders an e-mail at 12/16/20/24 px, blurs it at the rule radius and asserts no detector
            fires; its horizontal gradient energy drops to under 15 % of the original). avatar: r = max(6, ceil(d/3))
            — initials or a face at a third of the diameter are gone while the disc stays a disc, which is why
            leak_gate treats an avatar inside a declared mask as handled.
  time gate a clip's blur is on screen exactly when the clip is: the entry records the shot window from leaks.json
            (`leak.window`) so a reviewer sees when it matters. A seq blur covers every frame of the seq — the
            identifier is in the recording for the whole take.
  edits     hits in authored text (clips.json "shows", meta, shots, scene) cannot be masked; they are listed under
            `edits` with file:line for a manual fix.

The extra keys inside an entry (`leak`) are ignored by extract_clips.py and kept for provenance.
"""
import json, math, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
FEATHER = 6
TEXT_RADIUS_K = 0.45
MIN_RADIUS = 6


def _gate():
    for d in (os.path.join(HERE, '..', 'gates'), os.path.join(os.getcwd(), 'gates'), os.path.join(os.getcwd(), 'scenes', '..', 'gates')):
        d = os.path.normpath(d)
        if os.path.exists(os.path.join(d, 'leak_gate.py')):
            if d not in sys.path:
                sys.path.insert(0, d)
            import leak_gate
            return leak_gate
    raise ImportError('gates/leak_gate.py not found')


def radius_for(kinds, text_h, diameter):
    r = MIN_RADIUS
    if any(k != 'avatar' for k in kinds):
        r = max(r, int(math.ceil(TEXT_RADIUS_K * text_h)))
    if 'avatar' in kinds:
        r = max(r, int(math.ceil(diameter / 3.0)))
    return r


def _union(a, b):
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return [x0, y0, x1 - x0, y1 - y0]


def _touch(a, b):
    return not (a[0] + a[2] < b[0] or b[0] + b[2] < a[0] or a[1] + a[3] < b[1] or b[1] + b[3] < a[1])


def propose(leaks, clips=None, feather=FEATHER, include_all=False):
    """leaks.json dict (+ clips.json list for width-resized clips) -> proposal dict."""
    clips = clips or []
    byname = dict((c.get('name'), c) for c in clips if isinstance(c, dict))
    groups, edits = {}, []
    for h in sorted(leaks.get('hits', []), key=lambda h: (h['src'], h['kind'], json.dumps(h.get('box')))):
        if not (h.get('fails') or include_all):
            continue
        if not h.get('clip') or not h.get('box'):
            edits.append({'src': h['src'], 'line': h.get('line'), 'kind': h['kind'], 'text': h.get('text'), 'why': h.get('why')})
            continue
        if h['kind'] == 'avatar' and h.get('masked'):
            continue
        where = 'chrome.fix' if h.get('coord') == 'frame' else 'fix'
        c = byname.get(h['clip'], {})
        k = 1.0
        if where == 'fix' and c.get('width') and c.get('crop'):
            k = float(c['crop'][2]) / float(c['width'])                   # image px -> clip px
        x, y, w, hh = h['box']
        box = [int(math.floor(x * k)), int(math.floor(y * k)), int(math.ceil(w * k)), int(math.ceil(hh * k))]
        g = groups.setdefault((h['clip'], where), [])
        g.append({'box': box, 'kind': h['kind'], 'src': h['src'], 'window': [h.get('t0'), h.get('t1')], 'text_h': box[3] if h['kind'] != 'avatar' else 0,
                  'diameter': max(box[2], box[3]) if h['kind'] == 'avatar' else 0})
    proposal = []
    for (clip, where) in sorted(groups):
        items = groups[(clip, where)]
        clusters = []
        for it in items:
            pb = [max(0, it['box'][0] - feather), max(0, it['box'][1] - feather), it['box'][2] + 2 * feather, it['box'][3] + 2 * feather]
            merged = False
            for cl in clusters:
                if _touch(cl['box'], pb):
                    cl['box'] = _union(cl['box'], pb); cl['items'].append(it); merged = True; break
            if not merged:
                clusters.append({'box': pb, 'items': [it]})
        # merging can make previously separate clusters touch: settle
        changed = True
        while changed:
            changed = False
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    if _touch(clusters[i]['box'], clusters[j]['box']):
                        clusters[i]['box'] = _union(clusters[i]['box'], clusters[j]['box']); clusters[i]['items'] += clusters[j]['items']
                        del clusters[j]; changed = True; break
                if changed:
                    break
        for cl in sorted(clusters, key=lambda c: (c['box'][1], c['box'][0])):
            kinds = sorted(set(i['kind'] for i in cl['items']))
            r = radius_for(kinds, max([i['text_h'] for i in cl['items']] or [0]), max([i['diameter'] for i in cl['items']] or [0]))
            t0s = [i['window'][0] for i in cl['items'] if i['window'][0] is not None]
            t1s = [i['window'][1] for i in cl['items'] if i['window'][1] is not None]
            proposal.append({'clip': clip, 'where': where,
                             'entry': {'blur': cl['box'] + [r],
                                       'leak': {'kinds': kinds, 'n': len(cl['items']), 'feather': feather,
                                                'window': [min(t0s) if t0s else None, max(t1s) if t1s else None],
                                                'srcs': sorted(set(i['src'] for i in cl['items']))}}})
    return {'version': 1, 'proposal': proposal, 'edits': edits,
            'apply': 'python tools/mask_propose.py leaks.json --apply', 'then': 'python extract_clips.py && python qa_film.py',
            'note': 'blur = [x, y, w, h, radius] in clip px (still/seq), doc px (page) or frame px (chrome.fix); accept by --apply, then re-extract'}


def apply(proposal, clips_path):
    clips = json.load(open(clips_path, encoding='utf-8'))
    byname = dict((c.get('name'), c) for c in clips if isinstance(c, dict))
    added = 0
    for p in proposal['proposal']:
        c = byname.get(p['clip'])
        if c is None:
            continue
        if p['where'] == 'chrome.fix':
            c.setdefault('chrome', {})
            if not isinstance(c['chrome'], dict):
                c['chrome'] = {}
            lst = c['chrome'].setdefault('fix', [])
        else:
            lst = c.setdefault('fix', [])
        if any(isinstance(f, dict) and f.get('blur') == p['entry']['blur'] for f in lst):
            continue
        lst.append(p['entry']); added += 1
    if added:
        shutil.copyfile(clips_path, clips_path + '.bak')
        with open(clips_path, 'w', encoding='utf-8') as f:
            json.dump(clips, f, indent=1, ensure_ascii=False); f.write('\n')
    return added


def blur_copy(src_path, dst_path, blurs):
    from PIL import Image, ImageFilter
    im = Image.open(src_path).convert('RGB')
    for x, y, w, h, r in blurs:
        x, y = max(0, int(x)), max(0, int(y)); w, h = min(im.width - x, int(w)), min(im.height - y, int(h))
        if w > 0 and h > 0:
            im.paste(im.crop((x, y, x + w, y + h)).filter(ImageFilter.GaussianBlur(r)), (x, y))
    im.save(dst_path, quality=94)


def verify(proposal, project, leaks, clips=None, backend_pref='auto'):
    """Blur copies of every source frame the proposal covers (image px) and re-run the detectors with no masks.
    Returns (remaining_text_hits, scanned)."""
    LG = _gate()
    clips = clips or []
    byname = dict((c.get('name'), c) for c in clips if isinstance(c, dict))
    L = LG._cfg({'leak': {'backend': backend_pref}})
    L['full_text'] = True
    td = tempfile.mkdtemp(prefix='mask_verify_')
    try:
        per_src = {}
        for p in proposal['proposal']:
            c = byname.get(p['clip'], {})
            k = 1.0
            if p['where'] == 'fix' and c.get('width') and c.get('crop'):
                k = float(c['width']) / float(c['crop'][2])               # clip px -> image px
            x, y, w, h, r = p['entry']['blur']
            b = [x * k, y * k, w * k, h * k, max(MIN_RADIUS, r * k)]
            for s in p['entry']['leak']['srcs']:
                per_src.setdefault(s, []).append(b)
        srcs = []
        for s in sorted(per_src):
            sp = os.path.join(project, s)
            if not os.path.exists(sp):
                continue
            dp = os.path.join(td, s.replace('/', '__'))
            blur_copy(sp, dp, per_src[s])
            srcs.append({'src': s, 'path': dp, 'clip': None, 'kind': 'verify', 'coord': 'frame', 'frame': 1, 'scale': 1.0,
                         'src_rect': None, 'masks': [], 'windows': [], 'on_screen': None})
        backend, note = (None, 'ocr disabled') if backend_pref == 'none' else LG.pick_backend(backend_pref, L['text_score'])
        denylist = [t for t in leaks.get('_denylist', [])]
        hits, _ = LG.scan_sources(srcs, L, backend, denylist)
        remaining = []
        for h in hits:
            if h['kind'] == 'avatar':
                continue                                                   # a blurred disc is still a disc: covered by design
            inside = any(LG._cover(h['box'], [int(b[0]), int(b[1]), int(b[2]), int(b[3])]) >= 0.5 for b in per_src.get(h['src'], []))
            if inside:
                remaining.append({'src': h['src'], 'kind': h['kind'], 'box': h['box'], 'text': LG.redact(h['text'])})
        return remaining, len(srcs), (backend.name if backend else None)
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ----------------------------------------------------------------------------------------------- selftest
def _gradient_energy(im, box):
    import numpy as np
    x, y, w, h = box
    g = np.asarray(im.convert('L').crop((x, y, x + w, y + h)), dtype=np.float32)
    return float(np.abs(np.diff(g, axis=1)).sum())


def selftest():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    LG = _gate()
    t0 = time.perf_counter()
    # 1 — radius rule on an e-mail at four UI sizes: gradient energy < 15 %, and OCR (if any) reads no identifier
    backend, _ = LG.pick_backend('auto', fastest=True)                 # 60 s budget: fastest engine first
    L = LG._cfg({}); L['full_text'] = True
    for px in (12, 16, 20, 24):
        im = Image.new('RGB', (640, 120), (255, 255, 255)); d = ImageDraw.Draw(im)
        f = LG._font(px); txt = 'jane.doe@acme-corp.test'; d.text((20, 40), txt, font=f, fill=(20, 24, 30))
        bb = f.getbbox(txt); box = [20 + bb[0] - 2, 40 + bb[1] - 2, bb[2] - bb[0] + 4, bb[3] - bb[1] + 4]
        r = radius_for(['email'], box[3], 0)
        pb = [max(0, box[0] - FEATHER), max(0, box[1] - FEATHER), box[2] + 2 * FEATHER, box[3] + 2 * FEATHER]
        e0 = _gradient_energy(im, box)
        im.paste(im.crop((pb[0], pb[1], pb[0] + pb[2], pb[1] + pb[3])).filter(ImageFilter.GaussianBlur(r)), (pb[0], pb[1]))
        e1 = _gradient_energy(im, box)
        assert e1 / max(1.0, e0) < 0.15, ('blur too weak at %d px: energy %.2f' % (px, e1 / e0))
        if backend is not None:
            lines = backend.recognize(im)
            hits = [k for ln in lines for k, _, _, _ in LG.scan_text(ln['text'], ['acme-corp'])]
            assert not hits, ('OCR still reads the %d px line after r=%d: %s' % (px, r, hits))
        print('  %2d px text -> r=%d: gradient energy %.1f %%%s' % (px, r, 100 * e1 / max(1.0, e0), '' if backend is None else ', OCR reads nothing'))
    # 2 — end to end on the synthetic fixture
    td = tempfile.mkdtemp(prefix='mask_propose_')
    try:
        ctx = LG.build_fixture(td)
        pref = backend.name if backend is not None else 'none'
        ctx['qa']['leak']['backend'] = pref
        leaks, _, _ = LG.run_scan(ctx, out_path=os.path.join(td, 'leaks.json'))
        leaks['_denylist'] = LG.load_denylist(td, ctx['qa'])
        clips = json.load(open(os.path.join(td, 'clips.json')))
        P = propose(leaks, clips)
        where = set((p['clip'], p['where']) for p in P['proposal'])
        assert ('q', 'fix') in where and ('nb', 'chrome.fix') in where, where
        if backend is not None:
            assert ('nb', 'fix') in where and ('send', 'fix') in where, where
        assert all(p['entry']['blur'][4] >= MIN_RADIUS for p in P['proposal'])
        assert any(e['src'] == 'clips.json' for e in P['edits']), 'the authored Globex mention must be listed as an edit'
        assert all(p['entry']['leak']['window'][0] is not None for p in P['proposal'] if p['clip'] != 'spare'), 'windows missing'
        # verify: blurred copies hold
        remaining, n, bname = verify(P, td, leaks, clips, pref)
        assert not remaining, remaining
        # apply: entries land where extract_clips.py reads them, idempotent
        cp = os.path.join(td, 'clips.json')
        added = apply(P, cp); assert added == len(P['proposal']) and os.path.exists(cp + '.bak'), added
        assert apply(P, cp) == 0, 'second apply must add nothing'
        cj = json.load(open(cp))
        q = [c for c in cj if c['name'] == 'q'][0]; nb = [c for c in cj if c['name'] == 'nb'][0]
        assert any('blur' in f for f in q['fix']) and any('blur' in f for f in nb['chrome']['fix'])
        # the gate now sees declared masks: avatar hits pass, text (not yet re-extracted) fails with the re-extract message
        leaks2, _, _ = LG.run_scan(ctx, out_path=os.path.join(td, 'leaks2.json'))
        av = [h for h in leaks2['hits'] if h['kind'] == 'avatar' and h['clip'] in ('q', 'nb')]
        assert av and all(h['masked'] and not h['fails'] for h in av), av
        tx = [h for h in leaks2['hits'] if h['kind'] != 'avatar' and h['clip'] == 'q']
        assert all(h['masked'] and 'not applied' in h['why'] for h in tx), tx
        # determinism
        a = json.dumps(propose(leaks, clips), sort_keys=True); b = json.dumps(propose(leaks, clips), sort_keys=True)
        assert a == b
        print('  fixture: %d proposal entries over %s, %d edits, verify on %d blurred frames (%s): nothing legible; apply idempotent' % (
            len(P['proposal']), ', '.join(sorted(set(p['clip'] for p in P['proposal']))), len(P['edits']), n, bname or 'no OCR'))
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print('mask_propose selftest OK: radius rule / propose / verify / apply / gate semantics / deterministic  (%.1f s)' % (time.perf_counter() - t0))
    return 0


# ----------------------------------------------------------------------------------------------- CLI
def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not argv or '-h' in argv or '--help' in argv:
        print(__doc__); return 0 if argv else 2
    if '--selftest' in argv:
        return selftest()
    opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else d
    leaks_path = next((a for a in argv if not a.startswith('--') and a.endswith('.json') and a != opt('--clips') and a != opt('--out')), None)
    if not leaks_path or not os.path.exists(leaks_path):
        print('usage: mask_propose.py leaks.json [--clips clips.json] [--out leaks.masks.json] [--apply] [--verify]'); return 2
    project = os.path.dirname(os.path.abspath(leaks_path)) or os.getcwd()
    clips_path = opt('--clips', os.path.join(project, 'clips.json'))
    out = opt('--out', os.path.join(project, 'leaks.masks.json'))
    feather = int(opt('--feather', FEATHER))
    leaks = json.load(open(leaks_path, encoding='utf-8'))
    clips = json.load(open(clips_path, encoding='utf-8')) if os.path.exists(clips_path) else []
    P = propose(leaks, clips, feather, include_all='--all' in argv)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(P, f, indent=1, sort_keys=True, ensure_ascii=False); f.write('\n')
    print('%d mask entr%s proposed over %s; %d authored-text edit%s -> %s' % (
        len(P['proposal']), 'y' if len(P['proposal']) == 1 else 'ies', ', '.join(sorted(set(p['clip'] for p in P['proposal']))) or 'no clips',
        len(P['edits']), '' if len(P['edits']) == 1 else 's', out))
    for p in P['proposal']:
        print('  %-8s %-10s blur %s  %s  window %s' % (p['clip'], p['where'], p['entry']['blur'], '+'.join(p['entry']['leak']['kinds']), p['entry']['leak']['window']))
    for e in P['edits']:
        print('  EDIT     %s:%s %s %s' % (e['src'], e.get('line'), e['kind'], e.get('text') or ''))
    rc = 0
    if '--verify' in argv:
        LG = _gate()
        leaks['_denylist'] = LG.load_denylist(project, json.load(open(os.path.join(project, 'qa.json'))) if os.path.exists(os.path.join(project, 'qa.json')) else {}, opt('--deny'))
        remaining, n, bname = verify(P, project, leaks, clips, 'none' if '--no-ocr' in argv else opt('--backend', 'auto'))
        print('verify: %d frames blurred with the proposal, %d legible hit%s left (%s)' % (n, len(remaining), '' if len(remaining) == 1 else 's', bname or 'no OCR'))
        for r in remaining:
            print('  STILL LEGIBLE %s %s @%s %s' % (r['kind'], r['src'], r['box'], r['text']))
        rc = 1 if remaining else rc
    if '--apply' in argv:
        if not os.path.exists(clips_path):
            print('no clips.json at ' + clips_path); return 2
        added = apply(P, clips_path)
        print('applied %d entr%s to %s (backup %s.bak) -> re-run extract_clips.py, then qa_film.py' % (added, 'y' if added == 1 else 'ies', clips_path, os.path.basename(clips_path)))
    if not P['proposal'] and not P['edits']:
        print('nothing to propose: leaks.json has no failing hits'); rc = max(rc, 1)
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
