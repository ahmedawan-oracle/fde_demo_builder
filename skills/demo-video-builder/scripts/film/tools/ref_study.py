# -*- coding: utf-8 -*-
"""ref_study.py — reference study: log the films a demo wants to resemble, measure the ones you have, derive the rules.

    python tools/ref_study.py log      --title "…" [--note "…"] --shot "len|camera|lighting|cut" [--shot …]  [--project DIR]
    python tools/ref_study.py measure  <film.mp4> --title "…" [--note "…"]            shot lengths, median, cut rhythm, luma/contrast
    python tools/ref_study.py report   [--out REFERENCES.md]                           the derived rules for THIS film
    python tools/ref_study.py lint                                                     craft not content
    python tools/ref_study.py --selftest

Borrow craft, never content. A reference is logged as measurements — shot length, camera, lighting, how it cuts — and
never as what it shows: no logos, no copy, no scene to recreate. `lint` fails any entry whose text names content
(logo, tagline, their text, same scene, recreate, copy the, frame for frame, screenshot of, brand colour …) or quotes a
string; `report` refuses while lint fails.

What `measure` does (10 fps, 160x90 grey, one ffmpeg pass): cuts are the frame-difference outliers above
max(8 grey levels, mean + 3σ), merged within 0.3 s; shot lengths follow; the median shot and the cut rhythm (cuts per
10 s and the coefficient of variation of the lengths — under 0.4 reads as metronomic, over 1.0 as uneven on purpose);
per shot the mean luma and its standard deviation (contrast), and the film's luma percentiles p10 / p50 / p90.

`report` → REFERENCES.md: the table of references and the rules this film inherits from them — a target median shot,
a shot-length band (p25–p75 across the measured references), a cut-rhythm band, a luma band and a contrast band —
written as numbers the storyboard (`duration` per beat) and the gates (`no long freeze`, `hold still`) can be checked
against. refs.json is the log; REFERENCES.md is generated from it, never hand-edited.
Stdlib + numpy; ffmpeg only for `measure`.
"""
import argparse, json, os, re, subprocess, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CONTENT_WORDS = [r'\blogos?\b', r'\btagline\b', r'\bslogan\b', r'\btheir (?:text|copy|words|font|music|voice)\b', r'\bsame scene\b',
                 r'\brecreate\b', r'\bcopy (?:the|their|its)\b', r'\bframe[- ]for[- ]frame\b', r'\bscreenshot of\b', r'\bbrand colou?rs?\b',
                 r'\btrademark\b', r'\bverbatim\b', r'\blyrics?\b', r'\bcharacters? (?:from|of)\b', r'\bthe actor\b']
QUOTED = re.compile(r'"[^"\n]{3,}"|“[^”\n]{3,}”')
CRAFT_FIELDS = ('len', 'camera', 'lighting', 'cut')


def _load(p, default):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


class Refs:
    def __init__(self, project, path=None):
        self.project = os.path.abspath(project)
        self.path = path or os.path.join(self.project, 'refs.json')
        self.doc = _load(self.path, {'refs': []})
        if not isinstance(self.doc, dict) or not isinstance(self.doc.get('refs'), list):
            self.doc = {'refs': []}

    def save(self):
        with open(self.path, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(self.doc, fh, indent=1, ensure_ascii=False); fh.write('\n')
        return self.path

    def log(self, title, shots, note=''):
        rows = []
        for sh in shots:
            parts = [p.strip() for p in str(sh).split('|')]
            if len(parts) < 1 or not parts[0]:
                raise ValueError('a shot is "len|camera|lighting|cut" (len in seconds): %r' % sh)
            row = dict(zip(CRAFT_FIELDS, parts + [''] * (4 - len(parts))))
            row['len'] = float(re.search(r'\d+(?:\.\d+)?', row['len']).group())
            rows.append(row)
        ref = {'title': title, 'note': note or '', 'shots': rows, 'measured': False}
        self.doc['refs'].append(ref)
        return ref


# ------------------------------------------------------------------------------------------------ measure
def decode_gray(film, fps=10, size=(160, 90)):
    import numpy as np
    w, h = size
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', film, '-vf', 'fps=%d,scale=%d:%d:flags=area,format=gray' % (fps, w, h),
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], dtype=np.uint8).reshape(n, h, w)


def find_cuts(frames, fps=10, floor=8.0, sigmas=3.0, merge_s=0.3):
    """[t] of scene cuts: frame-difference outliers above max(floor, mean + sigmas·σ), merged within merge_s."""
    import numpy as np
    if len(frames) < 3:
        return [], []
    d = np.array([float(np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)).mean()) for i in range(1, len(frames))])
    thr = max(floor, float(d.mean() + sigmas * d.std()))
    cuts, last = [], -10.0
    for i, v in enumerate(d):
        t = (i + 1) / fps
        if v > thr and t - last >= merge_s:
            cuts.append(round(t, 2)); last = t
    return cuts, d.tolist()


def measure(film, fps=10):
    import numpy as np
    frames = decode_gray(film, fps)
    total = len(frames) / fps
    cuts, d = find_cuts(frames, fps)
    edges = [0.0] + cuts + [round(total, 2)]
    shots = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < 1.0 / fps:
            continue
        k0, k1 = int(a * fps), max(int(a * fps) + 1, int(b * fps))
        seg = frames[k0:k1]
        shots.append({'t0': a, 't1': b, 'len': round(b - a, 2), 'luma': round(float(seg.mean()), 1), 'contrast': round(float(seg.std(axis=(1, 2)).mean()), 1)})
    lens = np.array([s['len'] for s in shots]) if shots else np.array([total])
    lum = frames.mean(axis=(1, 2))
    return {'total': round(total, 2), 'cuts': cuts, 'shots': shots,
            'median_shot': round(float(np.median(lens)), 2), 'p25_shot': round(float(np.percentile(lens, 25)), 2), 'p75_shot': round(float(np.percentile(lens, 75)), 2),
            'cuts_per_10s': round(10.0 * len(cuts) / max(total, 1e-6), 2), 'length_cv': round(float(lens.std() / lens.mean()), 2) if lens.mean() > 0 else 0.0,
            'luma_p10': round(float(np.percentile(lum, 10)), 1), 'luma_p50': round(float(np.percentile(lum, 50)), 1), 'luma_p90': round(float(np.percentile(lum, 90)), 1),
            'contrast': round(float(np.mean([s['contrast'] for s in shots])), 1) if shots else 0.0}


# ------------------------------------------------------------------------------------------------ lint + report
def lint(doc):
    """[findings]: content words or quoted strings anywhere in a reference's text; a shot row that is not craft."""
    F = []
    for i, r in enumerate(doc.get('refs', []), 1):
        texts = [('title', r.get('title', '')), ('note', r.get('note', ''))]
        for j, sh in enumerate(r.get('shots', []), 1):
            for k in CRAFT_FIELDS:
                if k in sh and isinstance(sh[k], str):
                    texts.append(('shot %d %s' % (j, k), sh[k]))
            extra = [k for k in sh if k not in CRAFT_FIELDS + ('t0', 't1', 'luma', 'contrast')]
            if extra:
                F.append('ref %d "%s" shot %d: fields %s are not craft (len | camera | lighting | cut)' % (i, r.get('title', '?'), j, extra))
        for where, txt in texts:
            for pat in CONTENT_WORDS:
                m = re.search(pat, txt or '', re.I)
                if m:
                    F.append('ref %d "%s" %s: "%s" names content — log the craft (length, camera, lighting, cut), never what it shows' % (i, r.get('title', '?'), where, m.group()))
                    break
            if QUOTED.search(txt or ''):
                F.append('ref %d "%s" %s: a quoted string — on-screen words are content, not craft' % (i, r.get('title', '?'), where))
    return F


def rules(doc):
    import numpy as np
    R = [r for r in doc.get('refs', []) if r.get('shots')]
    if not R:
        return None
    lens = np.array([float(s['len']) for r in R for s in r['shots'] if s.get('len')])
    meas = [r for r in R if r.get('measured')]
    out = {'refs': len(R), 'shots': int(lens.size), 'median_shot': round(float(np.median(lens)), 2),
           'shot_band': [round(float(np.percentile(lens, 25)), 2), round(float(np.percentile(lens, 75)), 2)],
           'longest_shot': round(float(lens.max()), 2)}
    if meas:
        out['cuts_per_10s'] = [round(min(r['summary']['cuts_per_10s'] for r in meas), 2), round(max(r['summary']['cuts_per_10s'] for r in meas), 2)]
        out['length_cv'] = [round(min(r['summary']['length_cv'] for r in meas), 2), round(max(r['summary']['length_cv'] for r in meas), 2)]
        out['luma_band'] = [round(min(r['summary']['luma_p10'] for r in meas), 1), round(max(r['summary']['luma_p90'] for r in meas), 1)]
        out['luma_mid'] = round(float(np.median([r['summary']['luma_p50'] for r in meas])), 1)
        out['contrast_band'] = [round(min(r['summary']['contrast'] for r in meas), 1), round(max(r['summary']['contrast'] for r in meas), 1)]
    cams = [s.get('camera', '') for r in R for s in r['shots'] if s.get('camera')]
    cuts = [s.get('cut', '') for r in R for s in r['shots'] if s.get('cut')]
    out['camera_vocab'] = sorted(set(c.lower() for c in cams))[:8]
    out['cut_vocab'] = sorted(set(c.lower() for c in cuts))[:8]
    return out


def report(doc, out_path):
    F = lint(doc)
    if F:
        raise ValueError('craft not content:\n  ' + '\n  '.join(F))
    R = rules(doc)
    L = ['# REFERENCES — what this film borrows, as numbers', '',
         'Borrow craft, never content. Every reference below is logged as shot length, camera, lighting and the kind of cut;',
         'nothing here names what a reference shows. Generated by tools/ref_study.py from refs.json — do not hand-edit.', '',
         '| # | reference | shots | median shot | cuts / 10 s | length CV | luma p50 | contrast | note |', '|---|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(doc.get('refs', []), 1):
        s = r.get('summary') or {}
        lens = [float(x['len']) for x in r.get('shots', []) if x.get('len')]
        med = s.get('median_shot') if s else (sorted(lens)[len(lens) // 2] if lens else '')
        L.append('| %d | %s | %d | %s | %s | %s | %s | %s | %s |' % (i, r.get('title', '?'), len(r.get('shots', [])), med, s.get('cuts_per_10s', '—'), s.get('length_cv', '—'),
                                                               s.get('luma_p50', '—'), s.get('contrast', '—'), (r.get('note') or '').replace('|', '/')))
    L.append('')
    if R:
        L += ['## Derived rules for this film', '',
              '- **Shot length.** Target median %.1f s; most beats between %.1f and %.1f s (p25–p75 of %d reference shots); nothing longer than %.1f s without a reason written in the storyboard (`no long freeze` and `hold still` guard the long ones).' % (R['median_shot'], R['shot_band'][0], R['shot_band'][1], R['shots'], R['longest_shot'])]
        if 'cuts_per_10s' in R:
            L += ['- **Cut rhythm.** %.1f–%.1f cuts per 10 s; shot-length CV %.2f–%.2f (under 0.4 is metronomic, over 1.0 uneven on purpose — pick one and write it under `## Video direction`).' % (R['cuts_per_10s'][0], R['cuts_per_10s'][1], R['length_cv'][0], R['length_cv'][1]),
                  '- **Luma.** The references live between %.0f and %.0f (0–255) with a middle of %.0f; the recreated layers\' ground and ink should land in that band (design.md `colors`), product footage keeps its own.' % (R['luma_band'][0], R['luma_band'][1], R['luma_mid']),
                  '- **Contrast.** Within-shot luma spread %.0f–%.0f: softer than that reads flat on a booth screen, harder than that fights the captions.' % (R['contrast_band'][0], R['contrast_band'][1])]
        if R['camera_vocab']:
            L.append('- **Camera vocabulary.** %s — use these and no others (`camera-moves.md`).' % ', '.join(R['camera_vocab']))
        if R['cut_vocab']:
            L.append('- **Cut vocabulary.** %s — 2–3 techniques per film, repeated (`motion-doctrine.md`).' % ', '.join(R['cut_vocab']))
        L.append('')
    L += ['## What is never borrowed', '', 'Logos, copy, taglines, on-screen words, scenes, music, voices, brand colours, characters. If a line in refs.json names one of',
          'these, `python tools/ref_study.py lint` fails and this file is not written.', '']
    with open(out_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(L))
    return out_path, R


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    import tempfile, shutil
    import numpy as np
    d = tempfile.mkdtemp(prefix='ref_study_')
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    # synthetic reference film: shots of 2.0 / 1.0 / 3.0 / 2.0 s, each a different flat tone with a textured bar (contrast)
    film = os.path.join(d, 'ref.mp4'); fps = 30
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '160x90', '-r', str(fps), '-i', '-',
                          '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', film], stdin=subprocess.PIPE)
    tones, edges = [40, 160, 90, 200], [0.0, 2.0, 3.0, 6.0, 8.0]
    rng = np.random.RandomState(3)
    bars = [np.clip(tone + rng.randint(-60, 60, (30, 120)), 0, 255).astype(np.uint8) for tone in tones]   # one texture per shot
    for k in range(int(8.0 * fps)):
        tt = k / fps
        i = max(j for j in range(4) if edges[j] <= tt)
        f = np.full((90, 160), tones[i], np.uint8)
        f[30:60, 20:140] = bars[i]
        p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()
    m = measure(film)
    t(len(m['cuts']) == 3 and all(abs(c - e) <= 0.15 for c, e in zip(m['cuts'], [2.0, 3.0, 6.0])), 'measure: three cuts found at 2 / 3 / 6 s (%s)' % m['cuts'])
    t(abs(m['median_shot'] - 2.0) < 0.2 and [s['len'] for s in m['shots']] and abs(m['shots'][1]['len'] - 1.0) < 0.15, 'measure: shot lengths 2/1/3/2, median 2.0 (%s)' % [s['len'] for s in m['shots']])
    t(abs(m['shots'][3]['luma'] - 200) < 15 and m['shots'][0]['luma'] < 70 and m['contrast'] > 5, 'measure: per-shot luma and contrast read (%s, %.1f)' % ([s['luma'] for s in m['shots']], m['contrast']))
    R = Refs(d)
    R.log('Study A', ['2.4|static|soft key|hard cut', '1.2|push in|hard|match cut', '3.5|hold|soft|hard cut'], note='calm, three-beat rhythm')
    ref = {'title': 'Study B (measured)', 'note': 'a booth loop', 'shots': m['shots'], 'measured': True, 'summary': {k: v for k, v in m.items() if k not in ('shots', 'cuts')}}
    R.doc['refs'].append(ref); R.save()
    t(lint(R.doc) == [], 'lint: craft-only entries pass')
    out, rules_ = report(R.doc, os.path.join(d, 'REFERENCES.md'))
    md = open(out, encoding='utf-8').read()
    t('## Derived rules' in md and 'Target median' in md and 'Cut rhythm' in md and 'static' in md and rules_['refs'] == 2, 'report: REFERENCES.md with derived rules (median %.1f s, band %s)' % (rules_['median_shot'], rules_['shot_band']))
    R.log('Study C', ['2.0|static|soft|hard cut'], note='copy the logo wipe and the tagline "Faster together"')
    F = lint(R.doc)
    t(len(F) >= 2 and any('names content' in f for f in F) and any('quoted string' in f for f in F), 'lint: content words and a quoted string fail (%d findings)' % len(F))
    try:
        report(R.doc, os.path.join(d, 'REFERENCES.md')); t(False, 'report refuses while lint fails')
    except ValueError as e:
        t('craft not content' in str(e), 'report refuses while lint fails')
    try:
        R.log('bad', ['static|soft']); t(False, 'log rejects a shot without a length')
    except (ValueError, AttributeError):
        t(True, 'log rejects a shot without a length')
    shutil.rmtree(d, ignore_errors=True)
    print('ref_study selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ CLI
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='ref_study.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['log', 'measure', 'report', 'lint'])
    ap.add_argument('film', nargs='?')
    ap.add_argument('--project', default=os.getcwd()); ap.add_argument('--refs'); ap.add_argument('--out')
    ap.add_argument('--title'); ap.add_argument('--note', default=''); ap.add_argument('--shot', action='append', default=[])
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    R = Refs(a.project, a.refs)
    if a.cmd == 'log':
        if not a.title or not a.shot:
            print('log needs --title and at least one --shot "len|camera|lighting|cut"', file=sys.stderr); return 2
        ref = R.log(a.title, a.shot, a.note)
        F = lint({'refs': [ref]})
        if F:
            print('REFUSED — craft not content:\n  ' + '\n  '.join(F)); return 1
        R.save(); print('logged "%s" with %d shots → %s' % (a.title, len(ref['shots']), os.path.relpath(R.path, R.project))); return 0
    if a.cmd == 'measure':
        if not a.film or not os.path.exists(a.film):
            print('measure needs a local mp4', file=sys.stderr); return 2
        m = measure(a.film)
        ref = {'title': a.title or os.path.basename(a.film), 'note': a.note, 'shots': m['shots'], 'measured': True,
               'summary': {k: v for k, v in m.items() if k not in ('shots', 'cuts')}, 'cuts': m['cuts']}
        F = lint({'refs': [ref]})
        if F:
            print('REFUSED — craft not content:\n  ' + '\n  '.join(F)); return 1
        R.doc['refs'].append(ref); R.save()
        if a.json:
            print(json.dumps(m, indent=1))
        else:
            print('%s: %.1f s, %d cuts, median shot %.2f s (p25–p75 %.2f–%.2f), %.1f cuts/10 s, CV %.2f, luma p10/50/90 %.0f/%.0f/%.0f, contrast %.1f'
                  % (ref['title'], m['total'], len(m['cuts']), m['median_shot'], m['p25_shot'], m['p75_shot'], m['cuts_per_10s'], m['length_cv'], m['luma_p10'], m['luma_p50'], m['luma_p90'], m['contrast']))
        return 0
    if a.cmd == 'lint':
        F = lint(R.doc)
        for f in F:
            print('FAIL  ' + f)
        print('refs.json: %d references, %s' % (len(R.doc['refs']), 'craft only' if not F else '%d content findings' % len(F)))
        return 1 if F else 0
    out = a.out or os.path.join(R.project, 'REFERENCES.md')
    try:
        path, rl = report(R.doc, out)
    except ValueError as e:
        print('REFUSED — ' + str(e)); return 1
    print('wrote %s (%s)' % (os.path.relpath(path, R.project), ('%d refs, median shot %.1f s' % (rl['refs'], rl['median_shot'])) if rl else 'no shots logged yet'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
