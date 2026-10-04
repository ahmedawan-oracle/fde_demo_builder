# -*- coding: utf-8 -*-
"""reveal_gate.py — qa_film.py plug-in: a reveal hands the first (or last) real still to the footage lane on ONE frame.

    python gates/reveal_gate.py --selftest        (synthetic still + two short films, ~15 s of ffmpeg)

lib/reveals.js returns a receipt for every reveal it mounts: {kind, at, dur, end, frame, target, sampled?}. The frame
grid is the contract — `end` is snapped, `frame = round(end * fps)`, the footage shot after a heroDive / assemble /
lightWipe / irisFrom / matchCutHandover starts at `end`, the shot before a pullBack stops at its `at`. This gate reads
the receipts and the rendered film and refuses a join the eye could see.

Where the receipts come from (first that exists):
  1. out/timeline.json "reveals"          — export_timeline.js may run REVEAL.plan on a reveals.json ledger
  2. out/scene_receipts.json              — gates/_receipts.py (REVEAL.list() read from the mounted scene)
  3. reveals.json (project root)          — rows {kind, at | land, dur?, target?, particles?, seed?} with numeric
                                            times, planned here through `node lib/reveals.js --plan`
A scene that loads no lib/reveals.js and has no ledger passes with 'no reveals'.

Gates (GATE_NAMES, in order):
  reveal handover  every receipt: `end` (pullBack: `at`) sits on a footage shot boundary in out/timeline.json
                   (|dt| <= 1 ms), `end` is on the frame grid and frame == round(end * fps); an assemble receipt with
                   sampled == false fails (the canvas was tainted and the particles fell back to cream). More than one
                   opener reveal (heroDive / assemble before the first shot) is a WARN in the detail.
  reveal join      on the film, the hand-over pair (frame - 1, frame) at stage resolution: mean |dY| <= qa.reveal_join_max
                   (1.0 luma level) AND fewer than 1 % of pixels moved by > 24 levels (qa_film's own 'a cut landed' metric —
                   identical content through the encoder is ~0.3 / 0.3 %; a 1 px vertical slip on text rows reads ~3 / 1.5 %).
  reveal sampled   the frame the lane takes over on equals the still the plate carried: the clip's own file
                   (broll/<clip>/f_001.jpg, or the page band at scroll 0) rendered into the receipt's target rect vs the
                   film frame at `end`, mean |dY| <= qa.reveal_still_max (3.0: JPEG + x264 + resampling). Page clips
                   with chrome compare against chrome_0.jpg — the app's full screen at the first parked position, which
                   is what the lane composes at scroll 0.
qa.json keys: reveal_join_max 1.0, reveal_still_max 3.0, "reveals" (ledger path, default reveals.json), "clips".
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GATE_NAMES = ['reveal handover', 'reveal join', 'reveal sampled']
DEFAULTS = {'reveal_join_max': 1.0, 'reveal_still_max': 3.0}
STARTERS = ('heroDive', 'assemble', 'lightWipe', 'irisFrom', 'matchCutHandover')     # the lane starts at `end`
AW, AH = 1280, 720                                                                     # analysis size = the stage (1 px slips stay 1 px)


# ----------------------------------------------------------------------------------------------- receipts
def _reveals_js(project):
    for p in (os.path.join(project, 'scenes', 'lib', 'reveals.js'), os.path.join(FILM_DIR, 'lib', 'reveals.js')):
        if os.path.exists(p):
            return p
    return None


def plan_rows(project, rows):
    """Receipts for ledger rows with numeric at/land, through `node lib/reveals.js --plan`."""
    js = _reveals_js(project)
    out = []
    for r in rows:
        if js is None:
            raise RuntimeError('lib/reveals.js not found')
        p = subprocess.run(['node', js, '--plan', json.dumps(r)], capture_output=True, text=True, cwd=project)
        s = p.stdout.strip()
        if p.returncode not in (0, 1) or '{' not in s:
            raise RuntimeError('reveals.js --plan failed: ' + (p.stderr or s)[-160:])
        rec = json.loads(s[s.index('{'):])
        rec.setdefault('id', r.get('id'))
        if r.get('clip'):
            rec['clip'] = r['clip']
        out.append(rec)
    return out


def receipts(ctx):
    """(list of receipts, source note) or ([], note)."""
    P, Q, TL = ctx['project'], ctx.get('qa') or {}, ctx.get('timeline') or {}
    if isinstance(TL.get('reveals'), list):
        return TL['reveals'], 'out/timeline.json reveals'
    import _receipts
    if _receipts.uses(ctx, 'reveals'):
        R, note = _receipts.load(ctx)
        if R is not None and isinstance(R.get('reveals'), list):
            return R['reveals'], note
        led = os.path.join(P, Q.get('reveals', 'reveals.json'))
        if not os.path.exists(led):
            raise RuntimeError('scene loads lib/reveals.js but no receipts: %s (or write reveals.json)' % note)
    led = os.path.join(P, Q.get('reveals', 'reveals.json'))
    if os.path.exists(led):
        doc = json.load(open(led, encoding='utf-8'))
        rows = doc.get('reveals', doc) if isinstance(doc, dict) else doc
        return plan_rows(P, rows), 'reveals.json via reveals.js --plan'
    return [], 'no reveals'


# ----------------------------------------------------------------------------------------------- pure checks
def handover_time(r):
    return float(r['at']) if r.get('kind') == 'pullBack' else float(r['end'])


def check_handover(recs, shots, fps=30, tol=1e-3):
    """[(id/kind, problem)] for receipts whose timing is off the contract."""
    bad, openers = [], 0
    t0s = [float(s['t0']) for s in shots if s.get('t0') is not None]
    t1s = [float(s['t1']) for s in shots if s.get('t1') is not None]
    first = min(t0s) if t0s else None
    for r in recs:
        k, tag = r.get('kind'), r.get('id') or r.get('kind')
        f = r.get('fps') or fps
        th = handover_time(r)
        if abs(th * f - round(th * f)) > 1e-4:
            bad.append((tag, '%s %.4f is not on the %d fps frame grid' % ('at' if k == 'pullBack' else 'end', th, f)))
        if r.get('frame') is not None and int(r['frame']) != int(round(th * f)):
            bad.append((tag, 'frame %s != round(%.3f * %d) = %d' % (r['frame'], th, f, round(th * f))))
        if k == 'pullBack':
            if not any(abs(th - x) <= tol for x in t1s):
                bad.append((tag, 'pullBack at %.3f is not a footage shot t1 (the lane must stop there)' % th))
        elif k in STARTERS:
            if not any(abs(th - x) <= tol for x in t0s):
                bad.append((tag, '%s end %.3f is not a footage shot t0 (FILM.openEnd = dive.end)' % (k, th)))
            if first is not None and abs(th - first) <= tol and k in ('heroDive', 'assemble'):
                openers += 1
        if k == 'assemble' and r.get('sampled') is False:
            bad.append((tag, 'assemble sampled == false: tainted canvas, particles fell back to cream'))
        if k == 'matchCutHandover' and isinstance(r.get('transform'), dict) and r['transform'].get('ok') is False:
            bad.append((tag, 'matchCut aspect mismatch %s above the warn level' % r['transform'].get('aspect')))
    return bad, openers


def pair_frames(film, frame, fps=30):
    """Grey (frame-1, frame) of the film at stage resolution (1280x720) as int16 arrays."""
    t = max(0.0, (frame - 1) / float(fps) - 0.5 / fps)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.4f' % t, '-i', film, '-frames:v', '2', '-vf',
                        'scale=%d:%d:flags=area,format=gray' % (AW, AH), '-f', 'rawvideo', '-'], capture_output=True)
    n = len(r.stdout) // (AW * AH)
    if n < 2:
        raise RuntimeError('could not decode frames %d-%d' % (frame - 1, frame))
    a = np.frombuffer(r.stdout[:2 * AW * AH], np.uint8).reshape(2, AH, AW).astype(np.int16)
    return a[0], a[1]


def mean_abs(a, b, rect=None):
    if rect is not None:
        x0, y0, x1, y1 = rect
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16)))) if a.size else 0.0


def changed_pct(a, b, thr=24):
    """Share of pixels (%) whose grey level moved more than `thr` — qa_film.py's own 'a cut landed' metric."""
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16)) > thr) * 100.0) if a.size else 0.0


CUT_PCT = 1.0                                   # qa_film 'cuts land': across >= 1.0 % reads as a cut


def still_on_stage(path, target, clip=None):
    """The clip's own file placed into `target` ([x,y,w,h] stage px) on a 1280x720 canvas, as 640x360 grey (int16),
    plus the analysis rect. Page clips: the band at scroll 0 (chrome -> None)."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('L')
        if clip and clip.get('kind') == 'page' and not os.path.basename(path).startswith('chrome_'):
            im = im.crop((0, 0, im.size[0], min(im.size[1], int(im.size[0] * 9 / 16))))     # the band fills the stage width at scroll 0
        # a page WITH chrome compares against chrome_0.jpg — the app's own full screen at the first parked position, which is
        # exactly what the lane composes at scroll 0 (chrome frame + the band's top), so no crop is needed
        if not isinstance(target, (list, tuple)) or len(target) != 4:
            target = [0, 0, 1280, 720]            # a selector string or a missing rect: compare against the full stage (the ledger should carry [x, y, w, h])
        tx, ty, tw, th = [float(v) for v in target]
        im = im.resize((max(1, int(round(tw))), max(1, int(round(th)))), Image.LANCZOS)
        canvas = Image.new('L', (AW, AH), 8)
        canvas.paste(im, (int(round(tx)), int(round(ty))))
        rect = (int(round(tx)) + 4, int(round(ty)) + 4, min(AW, int(round(tx + tw))) - 4, min(AH, int(round(ty + th))) - 4)
        return np.asarray(canvas, dtype=np.int16), rect


def clip_file(project, clip):
    d = os.path.join(project, 'broll', clip['name'])
    if clip.get('kind') == 'page':
        # clips.json may say chrome: {} (requested) while extract_clips.py writes chrome: 3 (frames) — the file on disk decides
        chrome0 = os.path.join(d, 'chrome_0.jpg')
        return chrome0 if (clip.get('chrome') is not None and os.path.exists(chrome0)) else os.path.join(d, 'page.jpg')
    return os.path.join(d, 'f_001.jpg')


# ----------------------------------------------------------------------------------------------- the gate
def run(ctx):
    P, Q, TL = ctx['project'], ctx.get('qa') or {}, ctx.get('timeline') or {}
    K = {k: float(Q.get(k, v)) for k, v in DEFAULTS.items()}
    fps = int(ctx.get('fps', 30))
    try:
        recs, src = receipts(ctx)
    except Exception as e:
        return [(GATE_NAMES[0], False, str(e)[:200])] + [(n, False, 'no receipts') for n in GATE_NAMES[1:]]
    if not recs:
        return [(n, True, 'no reveals in this film') for n in GATE_NAMES]
    shots = TL.get('shots') or []
    bad, openers = check_handover(recs, shots, fps)
    d = '%d reveal(s) from %s: %s' % (len(recs), src, ', '.join(sorted(set(str(r.get('kind')) for r in recs))))
    if openers > 1:
        d += '; WARN %d opener reveals (doctrine: one per film)' % openers
    res = [('reveal handover', not bad, ('%s; ' % bad[:3]) + d if bad else d)]
    film = ctx.get('film')
    if not film or not os.path.exists(film):
        return res + [(n, False, 'film missing') for n in GATE_NAMES[1:]]
    joins, worst = [], 0.0
    for r in recs:
        fr = int(r.get('frame') if r.get('frame') is not None else round(handover_time(r) * fps))
        if fr <= 0:
            continue
        try:
            a, b = pair_frames(film, fr, fps)
        except Exception as e:
            joins.append((r.get('id') or r.get('kind'), fr, str(e)[:60])); continue
        m, ch = mean_abs(a, b), changed_pct(a, b)
        worst = max(worst, m)
        if m > K['reveal_join_max'] or ch > CUT_PCT:
            joins.append((r.get('id') or r.get('kind'), fr, round(m, 2), round(ch, 2)))
    res.append(('reveal join', not joins, ('visible join (reveal, frame, mean |dY|, %% px > 24) %s; ' % joins[:3] if joins else '') +
                'worst hand-over pair %.2f luma levels (max %.1f; a cut changes >= %.0f %% of pixels by 24 levels)' % (worst, K['reveal_join_max'], CUT_PCT)))
    clips_p = os.path.join(P, Q.get('clips', 'clips.json'))
    clips = {c['name']: c for c in json.load(open(clips_p, encoding='utf-8'))} if os.path.exists(clips_p) else {}
    off, notes, n_ok = [], [], 0
    for r in recs:
        if r.get('kind') not in STARTERS and r.get('kind') != 'pullBack':
            continue
        th = handover_time(r)
        sh = next((s for s in shots if s.get('t0') is not None and abs(float(s['t0']) - th) <= 1e-3), None) if r.get('kind') != 'pullBack' else \
            next((s for s in shots if s.get('t1') is not None and abs(float(s['t1']) - th) <= 1e-3), None)
        clip = clips.get(r.get('clip') or (sh or {}).get('clip'))
        tag = r.get('id') or r.get('kind')
        if not clip:
            notes.append('%s: no clip to compare (shot/clips.json)' % tag); continue
        path = clip_file(P, clip)
        if not os.path.exists(path):
            notes.append('%s: %s missing' % (tag, os.path.relpath(path, P))); continue
        ref, rect = still_on_stage(path, r.get('target'), clip)
        if ref is None:
            notes.append('%s: page with chrome not compared' % tag); continue
        fr = int(r.get('frame') if r.get('frame') is not None else round(th * fps))
        try:                                   # pair = (fr-1, fr): the lane's first frame after a start, its last before a pullBack
            a, b = pair_frames(film, max(1, fr), fps)
            got = a if r.get('kind') == 'pullBack' else b
        except Exception as e:
            off.append((tag, str(e)[:60])); continue
        m = mean_abs(ref, got, rect)
        if m > K['reveal_still_max']:
            off.append((tag, round(m, 2)))
        else:
            n_ok += 1
    d = '%d plate(s) equal the lane still within %.1f' % (n_ok, K['reveal_still_max']) if n_ok else 'nothing compared'
    if off:
        d = 'lane frame differs from the still (reveal, mean |dY|) %s; ' % off[:3] + d
    if notes:
        d += '; ' + '; '.join(notes[:2])
    res.append(('reveal sampled', not off, d))
    return res


# ----------------------------------------------------------------------------------------------- selftest
def _ui_still(w=1280, h=720, seed=5):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (w, h), (250, 250, 248))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 56], fill=(14, 124, 134))
    rng = np.random.default_rng(seed)
    for row in range(10):
        y = 90 + row * 58
        d.rectangle([40, y, 40 + int(rng.integers(300, 900)), y + 14], fill=(40, 44, 52))
        d.rectangle([40, y + 24, 40 + int(rng.integers(200, 600)), y + 32], fill=(120, 124, 132))
    d.rectangle([900, 120, 1220, 400], fill=(232, 240, 254), outline=(14, 124, 134), width=3)
    return im


def _film(path, still, end_frame, dive=True, slip=0, dark=False, n=45, fps=30, dy=0):
    """Frames < end_frame: plate (still scaled .62 -> 1) over navy; frames >= end_frame: the lane (still full, optionally slipped)."""
    from PIL import Image
    d = tempfile.mkdtemp(prefix='revfilm_')
    W, H = 1280, 720
    for i in range(n):
        if i < end_frame:
            u = (i + 1) / float(end_frame)
            s = 0.62 + 0.38 * (1 - (1 - u) ** 3)          # power3 tail: the last plate frame is within 0.01 % of identity (sub-pixel)
            fr = Image.new('RGB', (W, H), (8, 42, 52))
            pl = still.resize((int(W * s), int(H * s)), Image.LANCZOS)
            fr.paste(pl, ((W - pl.size[0]) // 2, (H - pl.size[1]) // 2))
        else:
            fr = Image.new('RGB', (W, H), (8, 42, 52))
            src = still.point(lambda v: int(v * 0.6)) if dark else still
            fr.paste(src, (slip, dy))
        fr.save(os.path.join(d, 'f_%04d.png' % i))
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-framerate', str(fps), '-i', os.path.join(d, 'f_%04d.png'), '-vf', 'scale=1920:1080:flags=lanczos',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', path], check=True)


def _selftest():
    import time
    T0 = time.time()
    tmp = tempfile.mkdtemp(prefix='revgate_')
    os.makedirs(os.path.join(tmp, 'broll', 'nb')); os.makedirs(os.path.join(tmp, 'out'))
    still = _ui_still()
    still.save(os.path.join(tmp, 'broll', 'nb', 'f_001.jpg'), quality=92)
    json.dump([{'name': 'nb', 'kind': 'still', 'crop': [0, 0, 1920, 1080]}], open(os.path.join(tmp, 'clips.json'), 'w'))
    good, bad = os.path.join(tmp, 'good.mp4'), os.path.join(tmp, 'bad.mp4')
    _film(good, still, 30); _film(bad, still, 30, slip=6, dark=True)
    rec = {'id': 'opener', 'kind': 'heroDive', 'at': 0.1, 'dur': 0.9, 'end': 1.0, 'frame': 30, 'fps': 30, 'target': [0, 0, 1280, 720]}
    TL = {'total': 1.5, 'shots': [{'clip': 'nb', 't0': 1.0, 't1': 1.5}], 'reveals': [rec]}
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok = ok and bool(cond)
        print('  %-46s %s  %s' % (label, 'PASS' if cond else 'FAIL', str(detail)[:120]))
    base = {'project': tmp, 'qa': {}, 'fps': 30, 'timeline': TL, 'film': good, 'scene_html': None}
    R = {n: (o, d) for n, o, d in run(base)}
    for n in GATE_NAMES:
        print('    %-16s %s  %s' % (n, 'PASS' if R[n][0] else 'FAIL', R[n][1][:110]))
    check('good: handover on shot t0, frame grid', R['reveal handover'][0], R['reveal handover'][1])
    check('good: join invisible (<= 1.0)', R['reveal join'][0], R['reveal join'][1])
    check('good: lane frame equals the still', R['reveal sampled'][0], R['reveal sampled'][1])
    R = {n: (o, d) for n, o, d in run(dict(base, film=bad))}
    for n in GATE_NAMES:
        print('    %-16s %s  %s' % (n, 'PASS' if R[n][0] else 'FAIL', R[n][1][:110]))
    check('bad film: 6 px slip + darker lane -> join fails', not R['reveal join'][0], R['reveal join'][1])
    check('bad film: lane frame != still', not R['reveal sampled'][0], R['reveal sampled'][1])
    slip = os.path.join(tmp, 'slip.mp4'); _film(slip, still, 30, dy=1)
    R = {n: (o, d) for n, o, d in run(dict(base, film=slip))}
    check('1 px vertical slip on the hand-over frame is caught', not R['reveal join'][0], R['reveal join'][1])
    recs_bad = [dict(rec, end=1.02, frame=30), dict(rec, id='asm', kind='assemble', sampled=False, end=1.0),
                {'id': 'pb', 'kind': 'pullBack', 'at': 1.4, 'dur': 0.9, 'end': 2.3, 'frame': 42, 'fps': 30}]
    bad_h, openers = check_handover(recs_bad, TL['shots'], 30)
    check('handover: off-grid end, bad frame, unsampled, pullBack off t1', len(bad_h) >= 4 and any('grid' in b[1] for b in bad_h) and any('sampled' in b[1] for b in bad_h)
          and any('pullBack' in b[1] for b in bad_h), bad_h)
    good_h, openers = check_handover([rec, dict(rec, id='asm2', kind='assemble', sampled=True)], TL['shots'], 30)
    check('handover: two openers -> WARN counted', not good_h and openers == 2, (good_h, openers))
    R = {n: (o, d) for n, o, d in run(dict(base, timeline={'total': 1.5, 'shots': TL['shots']}))}
    check('no receipts, no ledger -> PASS no reveals', all(o for o, _ in R.values()) and 'no reveals' in R['reveal handover'][1])
    json.dump({'reveals': [{'id': 'opener', 'kind': 'heroDive', 'land': 1.0, 'clip': 'nb'}]}, open(os.path.join(tmp, 'reveals.json'), 'w'))
    R = {n: (o, d) for n, o, d in run(dict(base, timeline={'total': 1.5, 'shots': TL['shots']}))}
    check('reveals.json ledger planned through reveals.js', all(o for o, _ in R.values()) and '--plan' in R['reveal handover'][1], R['reveal handover'][1])
    a, b = pair_frames(good, 30)
    check('pair_frames: dive tail vs lane < 1.0, lane vs plate mid-dive > 5', mean_abs(a, b) < 1.0 and mean_abs(pair_frames(good, 15)[0], b) > 5, '%.2f' % mean_abs(a, b))
    print('\n%s  (%.1f s)  %s' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', time.time() - T0, tmp))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
