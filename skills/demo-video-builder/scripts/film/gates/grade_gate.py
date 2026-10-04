# -*- coding: utf-8 -*-
"""grade_gate.py -- QA gates for colour truth on product footage (v4, vfx area). Loaded by qa_film.py.

  ui colour truth      Known UI swatches (brand accent, status chips, panel background, body text) are sampled
                       5x5 in the FINISHED FILM at a full-screen moment and compared with the same patch in the RAW
                       RECORDING (or a user-stated #hex). FAIL when any swatch shifts hue > 6 deg (measured only when
                       both patches have chroma >= 12/255), changes saturation > 10 points, or moves dE76 > 8
                       (the 6 of grade.py plus JPEG q96 + yuv420p loss). If a product clip is graded but no
                       swatches are listed, the gate FAILS: graded product pixels must be verified, not trusted.
  effects off footage  Static: (a) clips.json -- every product clip's `grade` uses adjust keys only, within the
                       product limits (exposure +-0.3, temperature/tint +-0.15), and never lut/saturation/vibrance;
                       (b) the authored scene + shots (comments stripped) never aim a VFX drawing call, a GL finishing
                       pass (GL.pass / GL.chain: vignette, grain, bloom, chromatic aberration), a CSS filter or a blend
                       mode at the footage lane (#clipWrap, #clipImg, #pageImg, #pageDoc, #pageView, FOOT.*, lane.*);
                       (c) film.json `grade` never targets product clips.

swatches.json (project root; path from qa.json "swatches", default "swatches.json"):
  [ {"clip": "nb", "t": 12.4, "name": "accent",  "xy": [1680, 32],  "hex": "#0E7C86"},
    {"clip": "nb", "t": 12.4, "name": "panel",   "xy": [900, 600]},
    {"clip": "q",  "t": 20.1, "auto": 6} ]
  xy = SOURCE px of the recording (1920x1080). `t` = film seconds at which that clip is on screen at scale 1.0
  (the establishing hold: shot.t0 + establish.hold + 0.1); when out/timeline.json carries `shots` the gate finds
  t itself from clip + establish. `hex` replaces the raw-recording reference when the brand colour is known.
  `auto: n` picks n flat saturated patches + the flattest bright and dark patch from the raw frame.

    python gates/grade_gate.py --selftest        (synthetic recording + film, ~3 s of ffmpeg)
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
import numpy as np
from PIL import Image

GATE_NAMES = ['ui colour truth', 'effects off footage']
HUE_DEG, SAT_PCT, DE76_MAX, MIN_CHROMA = 6.0, 10.0, 8.0, 12.0
ADJUST_KEYS = ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks', 'temperature', 'tint')
PRODUCT_LIMITS = {'exposure': 0.3, 'temperature': 0.15, 'tint': 0.15}
FOOTAGE_RE = re.compile(r'clipWrap|clipImg|pageImg|pageDoc|pageView|revealHost|stillHl|pageHl|\bFOOT\.|\blane\.|data-footage|footage', re.I)
VFX_CALL_RE = re.compile(r'\b(?:VFX\s*\.\s*(grain|haze|glitch|waveWarp|bloom|applyBloomGhost|chromaticSplit|drawSeam|vignette)|GL\s*\.\s*(pass|chain))\s*\(')


def call_args(txt, pos, limit=400):
    """The balanced argument list that starts at txt[pos] (just after the opening paren)."""
    depth, i = 1, pos
    while i < len(txt) and i - pos < limit:
        ch = txt[i]
        if ch in '([{': depth += 1
        elif ch in ')]}':
            depth -= 1
            if depth == 0: break
        i += 1
    return txt[pos:i]
CSS_RULE_RE = re.compile(r'#(clipWrap|clipImg|pageImg|pageDoc|pageView)\b[^{]*\{([^}]*)\}', re.S)
STRIP = lambda s: re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S))


_frames = {}


def rgb_frame(path, t, w=None, h=None):
    """One RGB frame of a video (or image) as float32 HxWx3 in 0..1 (cached per path + time)."""
    key = (path, None if t is None else round(t, 3), w, h)
    if key not in _frames: _frames[key] = _rgb_frame(path, t, w, h)
    return _frames[key]


def _rgb_frame(path, t, w=None, h=None):
    vf = ['scale=%d:%d' % (w, h)] if w and h else []
    cmd = ['ffmpeg', '-nostdin', '-v', 'error']
    if t is not None: cmd += ['-ss', '%.3f' % t]
    cmd += ['-i', path, '-frames:v', '1'] + (['-vf', ','.join(vf)] if vf else []) + ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    r = subprocess.run(cmd, capture_output=True)
    if not w or not h:
        info = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path],
                              capture_output=True, text=True).stdout.strip().split(',')
        w, h = int(info[0]), int(info[1])
    if len(r.stdout) < w * h * 3:
        raise RuntimeError('no frame at %.2f s in %s' % (t or 0, os.path.basename(path)))
    return np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3).astype(np.float32) / 255.0


def source_time_of(clip):
    """A representative source time for a clip spec (the median window's middle, a still's t, a seq's t0)."""
    if 'win' in clip: return (clip['win'][0] + clip['win'][1]) / 2.0
    if 't' in clip: return float(clip['t'])
    if 't0' in clip: return float(clip['t0']) + 0.05
    L = (clip.get('layers') or [{}])[0]
    return (L['win'][0] + L['win'][1]) / 2.0 if 'win' in L else float(L.get('t', 0))


def map_to_film(clip, x, y, film_w=1920, film_h=1080, src_w=1920):
    """Source px -> film px at camera scale 1.0. still/seq: the crop fills the stage width; page+chrome: full screen;
    page without chrome: the band fills the stage width (scroll assumed at 0 at the sample time)."""
    kind = clip.get('kind')
    if kind == 'page':
        if 'chrome' in clip: return x * film_w / src_w, y * film_w / src_w
        b = clip['band']; k = film_w / b[2]; return (x - b[0]) * k, (y - b[1]) * k
    c = clip.get('crop', [0, 0, src_w, int(src_w * 9 / 16)]); k = film_w / c[2]
    return (x - c[0]) * k, (y - c[1]) * k


def shot_time(clip_name, timeline, swatch):
    if swatch.get('t') is not None: return float(swatch['t'])
    for sh in timeline.get('shots', []) or []:
        if sh.get('clip') == clip_name and sh.get('t0') is not None:
            est = sh.get('establish') or {}
            return float(sh['t0']) + float(est.get('hold', 0)) + 0.1
    return None


def colour_truth(ctx):
    import grade as GR
    P, Q, C = ctx['project'], ctx.get('qa') or {}, ctx.get('cfg') or {}
    clips_path = os.path.join(P, Q.get('clips', 'clips.json'))
    clips = {c['name']: c for c in json.load(open(clips_path, encoding='utf-8'))} if os.path.exists(clips_path) else {}
    graded = [n for n, c in clips.items() if c.get('grade') and not c.get('broll')]
    sw_path = os.path.join(P, Q.get('swatches', 'swatches.json'))
    if not os.path.exists(sw_path):
        if graded: return False, 'graded product clips %s but no swatches.json to verify them' % graded
        return True, 'no graded product clips, nothing to verify (add swatches.json to check anyway)'
    rows, bad, errs = [], [], []
    for s in json.load(open(sw_path, encoding='utf-8')):
        cl = clips.get(s.get('clip'))
        if not cl: errs.append('%s: unknown clip' % s.get('clip')); continue
        t = shot_time(s['clip'], ctx.get('timeline') or {}, s)
        if t is None: errs.append('%s: no t (give "t" or export shots in timeline.json)' % s['clip']); continue
        if any(w[0] <= t <= w[1] for w in [(x.get('t0', 0), x.get('t1', 0)) for x in (ctx.get('timeline') or {}).get('seams', [])]):
            errs.append('%s: t=%.2f is inside a seam window' % (s['clip'], t)); continue
        src_file = os.path.join(P, cl.get('file', C.get('recording', 'recording.mp4')))
        try:
            raw = rgb_frame(src_file, source_time_of(cl)) if (not s.get('hex') or s.get('auto')) else None
            film = rgb_frame(ctx['film'], t)
        except Exception as e:
            errs.append('%s: %s' % (s['clip'], str(e)[:80])); continue
        picks = GR.auto_swatches(raw, n=int(s['auto'])) if s.get('auto') else [[s['xy'][0], s['xy'][1], s.get('hex'), s.get('name', s['clip'])]]
        for x, y, hx, name in picks:
            fx, fy = map_to_film(cl, x, y, film.shape[1], film.shape[0])
            if not (0 <= fx < film.shape[1] and 0 <= fy < film.shape[0]): errs.append('%s/%s: maps off screen' % (s['clip'], name)); continue
            ref = GR.hex_to_rgb(hx) if hx else GR.sample_patch(raw, x, y)
            got = GR.sample_patch(film, fx, fy)
            h0, s0, c0 = GR.hue_sat(ref); h1, s1, c1 = GR.hue_sat(got)
            de = GR.de76(ref, got); dh = GR.hue_delta(h0, h1) if min(c0, c1) >= MIN_CHROMA else 0.0; ds = s1 - s0
            row = (s['clip'], name, round(de, 1), round(dh, 1), round(ds, 1)); rows.append(row)
            if de > DE76_MAX or abs(dh) > HUE_DEG or abs(ds) > SAT_PCT: bad.append(row)
    if errs: return False, 'errors ' + '; '.join(errs)[:200]
    if bad: return False, 'shifted (clip, swatch, dE76, hue deg, sat pts) %s' % bad[:4]
    return True, '%d swatches within dE76 %.0f / hue %.0f deg / sat %.0f pts; worst dE %.1f' % (len(rows), DE76_MAX, HUE_DEG, SAT_PCT, max([r[2] for r in rows] or [0]))


def effects_off_footage(ctx):
    P, Q, C = ctx['project'], ctx.get('qa') or {}, ctx.get('cfg') or {}
    problems = []
    clips_path = os.path.join(P, Q.get('clips', 'clips.json'))
    if os.path.exists(clips_path):
        for c in json.load(open(clips_path, encoding='utf-8')):
            g = c.get('grade')
            if not g or c.get('broll'): continue
            extra = [k for k in g if k not in ADJUST_KEYS]
            if extra: problems.append('%s: non-adjust grade %s on product footage' % (c['name'], extra))
            for k, lim in PRODUCT_LIMITS.items():
                if abs(float(g.get(k, 0))) > lim + 1e-9: problems.append('%s: %s=%s beyond +-%.2f' % (c['name'], k, g[k], lim))
            for k in g:
                if k in ADJUST_KEYS and abs(float(g[k])) > (2.0 if k == 'exposure' else 1.0): problems.append('%s: %s out of range' % (c['name'], k))
    files = [ctx.get('scene_html'), ctx.get('shots_js')] + [os.path.join(P, f) for f in Q.get('authored', [])]
    seen = set()
    for f in files:
        if not f or not os.path.exists(f) or f in seen: continue
        seen.add(f); txt = STRIP(open(f, encoding='utf-8', errors='replace').read()); base = os.path.basename(f)
        for m in VFX_CALL_RE.finditer(txt):
            args = call_args(txt, m.end())
            who = ('VFX.' + m.group(1)) if m.group(1) else ('GL.' + m.group(2))
            if FOOTAGE_RE.search(args): problems.append('%s: %s(%s) targets the footage lane' % (base, who, ' '.join(args.split())[:40]))
        for m in CSS_RULE_RE.finditer(txt):
            body = m.group(2)
            if re.search(r'(?<![-\w])(filter|mix-blend-mode|backdrop-filter)\s*:', body) and not re.search(r'filter\s*:\s*none', body):
                problems.append('%s: CSS #%s has a filter/blend' % (base, m.group(1)))
        for m in re.finditer(r'(clipWrap|clipImg|pageImg)[^;\n]{0,60}style\.(filter|mixBlendMode)\s*=\s*(?!["\']none["\'])', txt):
            problems.append('%s: %s.style.%s set in script' % (base, m.group(1), m.group(2)))
    fg = C.get('grade')
    if isinstance(fg, dict):
        for k in ('product', 'footage', 'clips_lut'):
            if k in fg: problems.append('film.json grade.%s: grading must happen per clip in clips.json (adjust only)' % k)
    if problems: return False, '; '.join(problems)[:360]
    return True, 'no VFX/filters on the footage lane; product grades adjust-only within limits'


def run(ctx):
    out = []
    for name, fn in zip(GATE_NAMES, (colour_truth, effects_off_footage)):
        try: ok, detail = fn(ctx)
        except Exception as e: ok, detail = False, 'gate crashed: %s: %s' % (type(e).__name__, str(e)[:140])
        out.append((name, ok, detail))
    return out


# --------------------------------------------------------------------------------------------------------- selftest
def selftest(tmp=None):
    import grade as GR
    tmp = tmp or os.path.join(os.environ.get('TEMP', '/tmp'), 'grade_gate_selftest'); os.makedirs(tmp, exist_ok=True)
    ok = True
    def check(name, cond, detail=''):
        nonlocal ok; ok = ok and bool(cond); print('  %-34s %s  %s' % (name, 'PASS' if cond else 'FAIL', detail[:110]))
    ui = GR._synthetic_ui(1920, 1080); raw_png = os.path.join(tmp, 'raw.png'); ui.save(raw_png)
    rec = os.path.join(tmp, 'recording.mp4'); good = os.path.join(tmp, 'good.mp4'); bad = os.path.join(tmp, 'bad.mp4')
    enc = lambda src, dst: subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-loop', '1', '-i', src, '-t', '0.7', '-r', '30', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '17', '-pix_fmt', 'yuv420p', dst], check=True)
    R = lambda **kw: {n: (o, d) for n, o, d in run(dict(base, **kw))}
    enc(raw_png, rec)
    GR.to_image(GR.apply_adjust(GR.to_float(ui), {'blacks': 0.03, 'temperature': -0.05})).save(os.path.join(tmp, 'good.png')); enc(os.path.join(tmp, 'good.png'), good)
    GR.to_image(GR.apply_adjust(GR.to_float(ui), {'temperature': 0.6, 'saturation': 0.5}, broll=True)).save(os.path.join(tmp, 'bad.png')); enc(os.path.join(tmp, 'bad.png'), bad)
    sw = [{'clip': 'ui', 't': 0.5, 'name': 'accent', 'xy': [960, 32]}, {'clip': 'ui', 't': 0.5, 'name': 'red', 'xy': [410, 160]},
          {'clip': 'ui', 't': 0.5, 'name': 'panel', 'xy': [1000, 500], 'hex': '#E8F0FE'}, {'clip': 'ui', 't': 0.5, 'auto': 3}]
    json.dump(sw, open(os.path.join(tmp, 'swatches.json'), 'w'))
    clips = [{'name': 'ui', 'kind': 'still', 't': 0.5, 'crop': [0, 0, 1920, 1080], 'grade': {'blacks': 0.03, 'temperature': -0.05}}]
    json.dump(clips, open(os.path.join(tmp, 'clips.json'), 'w'))
    scene_ok = os.path.join(tmp, 'film.html'); scene_bad = os.path.join(tmp, 'film_bad.html')
    open(scene_ok, 'w').write('<style>#clipWrap{position:absolute;filter:none}</style><script>/* VFX.grain(clipCtx) in a comment is fine */\nVFX.grain(grainCtx, t, {amount:0.12}); VFX.vignette($("#vig"));\n'
                              'GL.chain(glx, titleCanvas, [["vignette", {amount: 0.12}], ["grain", {frame: GL.frameIndex(t)}]]); GL.pass(glx, "copy", card, {zoom: push.z});</script>')
    open(scene_bad, 'w').write('<style>#clipImg{filter:saturate(1.3)}</style><script>VFX.glitch(ctx, $("#clipWrap"), t, 3, 0.3); clipImg.style.mixBlendMode="screen";\n'
                               'GL.pass(glx, "grain", $("#clipImg"), {amount: 0.06}); GL.chain(glx, lane.imageFor("q"), [["vignette", {}]]);</script>')
    base = {'project': tmp, 'qa': {'swatches': 'swatches.json', 'clips': 'clips.json'}, 'cfg': {'recording': 'recording.mp4'}, 'timeline': {}, 'shots_js': None}
    r = R(film=good, scene_html=scene_ok)
    check('good grade passes colour truth', r['ui colour truth'][0], r['ui colour truth'][1])
    check('clean scene passes effects gate', r['effects off footage'][0], r['effects off footage'][1])
    r = R(film=bad, scene_html=scene_bad)
    check('warm+saturated film fails truth', not r['ui colour truth'][0], r['ui colour truth'][1])
    check('filter on footage fails', not r['effects off footage'][0] and 'glitch' in r['effects off footage'][1] and 'CSS' in r['effects off footage'][1], r['effects off footage'][1])
    check('GL.pass / GL.chain on the lane fail', 'GL.pass(' in r['effects off footage'][1] and 'GL.chain(' in r['effects off footage'][1], r['effects off footage'][1])
    json.dump([dict(clips[0], grade={'saturation': 0.3, 'temperature': 0.2})], open(os.path.join(tmp, 'clips.json'), 'w'))
    r = R(film=good, scene_html=scene_ok)
    check('non-adjust grade on product fails', not r['effects off footage'][0] and 'non-adjust' in r['effects off footage'][1] and 'beyond' in r['effects off footage'][1], r['effects off footage'][1])
    os.remove(os.path.join(tmp, 'swatches.json'))
    r = R(film=good, scene_html=scene_ok)
    check('graded clip without swatches fails', not r['ui colour truth'][0], r['ui colour truth'][1])
    json.dump([dict(clips[0], grade=None)], open(os.path.join(tmp, 'clips.json'), 'w'))
    r = R(film=good, scene_html=scene_ok)
    check('ungraded + no swatches passes', r['ui colour truth'][0], r['ui colour truth'][1])
    tl = {'shots': [{'clip': 'ui', 't0': 0.2, 'establish': {'hold': 0.2}}]}
    json.dump([dict(sw[0], t=None)], open(os.path.join(tmp, 'swatches.json'), 'w')); json.dump(clips, open(os.path.join(tmp, 'clips.json'), 'w'))
    r = R(film=good, scene_html=scene_ok, timeline=tl)
    check('t resolved from timeline shots', r['ui colour truth'][0], r['ui colour truth'][1])
    fx, fy = map_to_film({'kind': 'still', 'crop': [480, 150, 1400, 900]}, 480 + 700, 150 + 450)
    check('map: cropped still -> film px', abs(fx - 960.0) < 1e-6 and abs(fy - 450 * 1920 / 1400) < 1e-6, '(%.1f, %.1f)' % (fx, fy))
    print('\n%s  (%s)' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', tmp))
    return ok


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        a = [x for x in sys.argv[1:] if x != '--selftest']
        sys.exit(0 if selftest(a[0] if a else None) else 1)
    print(__doc__)
