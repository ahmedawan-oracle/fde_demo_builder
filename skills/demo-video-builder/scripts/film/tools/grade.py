# -*- coding: utf-8 -*-
"""grade.py -- truthful footage normalisation for real product recordings (v4, vfx area).

    python tools/grade.py probe recording.mp4 [t0 t1] [--frames 5] [--broll] [--write broll/nb/meta.json] [--match other_meta.json]
    python tools/grade.py apply in.jpg out.jpg --adjust '{"exposure":0.1,"temperature":-0.05,"blacks":0.03}' [--broll] [--swatches swatches.json]
    python tools/grade.py filter --adjust '{...}'                      -> the equivalent ffmpeg -vf fragment for seq clips
    python tools/grade.py compare frame.jpg grades.json out/qa/grade_compare.png [--crop x,y,w,h] [--cell 560]
    python tools/grade.py lut look.cube [--apply in.png out.png --intensity 0.4]   (b-roll only; prints the lut3d fragment)
    python tools/grade.py bake-lut adjust.json look.cube [--size 33]
    python tools/grade.py ramp '[[0,3],[2,3],[2.5,1]]' --fps 30 --frames 120 [--dur 4]
    python tools/grade.py --selftest

Doctrine (encoded in code, not just in the docs)
  * Product footage may only be CORRECTED: exposure, contrast, highlights, shadows, whites, blacks, temperature, tint
    (the "adjust" vector). Saturation, vibrance, curves, LUTs and every stylising effect are refused unless the clip is
    marked broll=True. Product limits are tighter than the maths allows: exposure +-0.3 EV, temperature/tint +-0.15.
  * Every correction of product pixels is verified: up to 6 UI swatches (brand accent, a status red/green, the panel
    background, body text) must stay within dE76 <= 6 after the grade, or apply_adjust_image() raises.
  * Measure before you grade: probe() runs ffprobe + ffmpeg signalstats on 5 frames and derives a BOUNDED suggestion.
    On UI footage highlight-clip risk is reported, never auto-corrected (a white panel legitimately sits at Y >= 235).

Maths (sRGB floats 0..1, Rec.709 luma 0.2126/0.7152/0.0722, fixed order)
  gain 2^exposure -> shadows*0.35*(1-smoothstep(0,0.65,Y)) + highlights*0.35*smoothstep(0.35,1,Y)
  -> black point blacks*0.18, white point 1-whites*0.18, (c-bp)/(wp-bp) -> R += 0.08*T + 0.04*tint, G -= 0.08*tint,
  B -= 0.08*T - 0.04*tint -> contrast (c-0.5)*(1+k)+0.5 -> [b-roll only] vibrance, saturation mix(Y, c, 1+s) -> clip.
  Limits: exposure +-2, every other key +-1.

Speed ramps (seq clips): a lane [[t, rate], ...] in clip-local seconds; rates clamp 0.1..10; log-space interpolation
(0.5 -> 2 passes 1 at the midpoint); source time = trapezoid integral at 48 cells per segment. The same maths lives in
lib/vfx.js (VFX.ramp) so the film and the QA agree on which source frame is on screen at a word.
"""
import json, math, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ADJUST_KEYS = ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks', 'temperature', 'tint')
BROLL_KEYS = ADJUST_KEYS + ('saturation', 'vibrance', 'lut', 'lut_intensity')
LIMITS = {'exposure': 2.0}                              # every other adjust key: +-1
PRODUCT_LIMITS = {'exposure': 0.3, 'temperature': 0.15, 'tint': 0.15}   # the plugin's honesty budget for UI footage
DE_PRODUCT = 6.0                                        # swatch budget at extraction (clean pixels)
LUMA709 = np.array([0.2126, 0.7152, 0.0722], np.float32)
SAMPLE_FRAMES = 5


def smoothstep(a, b, x):
    u = np.clip((x - a) / (b - a), 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


# ----------------------------------------------------------------------------------------------------- adjust vector
def validate_adjust(adj, broll=False):
    """Return a clean adjust dict or raise ValueError. Product clips: adjust keys only, within PRODUCT_LIMITS."""
    if not isinstance(adj, dict):
        raise ValueError('grade must be an object of adjust keys')
    allowed = BROLL_KEYS if broll else ADJUST_KEYS
    bad = [k for k in adj if k not in allowed]
    if bad:
        raise ValueError('grade keys %s are not allowed on %s (%s)' % (bad, 'b-roll' if broll else 'PRODUCT footage',
                         'allowed: ' + ', '.join(allowed)))
    out = {}
    for k, v in adj.items():
        if k == 'lut':
            out[k] = str(v); continue
        v = float(v)
        lim = LIMITS.get(k, 1.0)
        if abs(v) > lim + 1e-9:
            raise ValueError('%s=%.3f exceeds the maths limit +-%.1f' % (k, v, lim))
        if not broll and k in PRODUCT_LIMITS and abs(v) > PRODUCT_LIMITS[k] + 1e-9:
            raise ValueError('%s=%.3f exceeds the PRODUCT limit +-%.2f (a visible UI colour change; mark the clip broll or lower it)'
                             % (k, v, PRODUCT_LIMITS[k]))
        out[k] = v
    return out


def apply_adjust(arr, adj, broll=False):
    """arr: float32 HxWx3 in 0..1 -> graded float32 (clipped). Pure numpy, fixed order (see module doc)."""
    a = validate_adjust(adj, broll)
    c = arr.astype(np.float32) * np.float32(2.0 ** a.get('exposure', 0.0))
    if a.get('shadows') or a.get('highlights'):
        Y = c @ LUMA709
        c = c + (a.get('shadows', 0.0) * 0.35 * (1.0 - smoothstep(0.0, 0.65, Y)) + a.get('highlights', 0.0) * 0.35 * smoothstep(0.35, 1.0, Y))[..., None]
    bp, wp = a.get('blacks', 0.0) * 0.18, 1.0 - a.get('whites', 0.0) * 0.18
    if bp != 0.0 or wp != 1.0:
        c = (c - bp) / (wp - bp)
    T, tn = a.get('temperature', 0.0), a.get('tint', 0.0)
    if T or tn:
        c = c + np.array([0.08 * T + 0.04 * tn, -0.08 * tn, -(0.08 * T - 0.04 * tn)], np.float32)
    k = a.get('contrast', 0.0)
    if k:
        c = (c - 0.5) * (1.0 + k) + 0.5
    if broll:
        if a.get('vibrance'):
            Y = c @ LUMA709
            sat = c.max(axis=-1) - c.min(axis=-1)
            skin = smoothstep(0.02, 0.18, c[..., 0] - c[..., 1]) * smoothstep(0.0, 0.16, c[..., 1] - c[..., 2]) * smoothstep(0.18, 0.82, Y)
            w = a['vibrance'] * (1.0 - sat * 0.72) * (1.0 - 0.45 * skin)
            c = Y[..., None] + (c - Y[..., None]) * (1.0 + w)[..., None]
        if a.get('saturation'):
            Y = c @ LUMA709
            c = Y[..., None] + (c - Y[..., None]) * (1.0 + a['saturation'])
        if a.get('lut'):
            c = apply_lut(np.clip(c, 0, 1), parse_cube(a['lut']), a.get('lut_intensity', 1.0))
    return np.clip(c, 0.0, 1.0).astype(np.float32)


def to_float(im):
    return np.asarray(im.convert('RGB'), np.float32) / 255.0


def to_image(arr):
    return Image.fromarray(np.clip(np.rint(arr * 255.0), 0, 255).astype(np.uint8), 'RGB')


def apply_adjust_image(im, adj, broll=False, swatches=None, de_max=DE_PRODUCT):
    """PIL in -> PIL out. On product footage the swatch guard runs (swatches = [[x, y, '#hex'?], ...] in image px):
    every 5x5 patch must stay within dE76 <= de_max of its pre-grade colour, else ValueError. Apply BEFORE blur/word/text
    fixes and BEFORE the JPEG save, so repainted words sample corrected ink and nothing is quantised twice."""
    src = to_float(im)
    dst = apply_adjust(src, adj, broll)
    if swatches and not broll:
        rep = swatch_report(src, dst, swatches)
        worst = max(rep, key=lambda r: r['de76'])
        if worst['de76'] > de_max:
            raise ValueError('UI colour truth: swatch %s moved dE76 %.1f (> %.1f) hue %+.1f deg sat %+.1f %%: lower the grade'
                             % (worst['name'], worst['de76'], de_max, worst['hue_shift'], worst['sat_change']))
    return to_image(dst)


# --------------------------------------------------------------------------------------------------- colour metrics
def srgb_to_lab(rgb):
    """rgb float 0..1 (..., 3) -> CIE Lab (D65)."""
    c = np.asarray(rgb, np.float64)
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def de76(a, b):
    return float(np.sqrt(((srgb_to_lab(a) - srgb_to_lab(b)) ** 2).sum()))


def hue_sat(rgb):
    """-> (hue degrees 0..360, HSV saturation in %, chroma 0..255) of one rgb float triple."""
    r, g, b = [float(v) for v in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    ch = mx - mn
    if ch < 1e-6:
        return 0.0, 0.0, 0.0
    if mx == r: h = ((g - b) / ch) % 6
    elif mx == g: h = (b - r) / ch + 2
    else: h = (r - g) / ch + 4
    return (h * 60.0) % 360.0, 100.0 * ch / mx if mx > 0 else 0.0, ch * 255.0


def hue_delta(h0, h1):
    d = (h1 - h0 + 180.0) % 360.0 - 180.0
    return d


def sample_patch(arr, x, y, r=2):
    h, w = arr.shape[:2]
    x0, x1, y0, y1 = max(0, int(x) - r), min(w, int(x) + r + 1), max(0, int(y) - r), min(h, int(y) + r + 1)
    return arr[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)


def swatch_report(before, after, swatches, scale=(1.0, 1.0), min_chroma=12.0):
    """before/after float arrays; swatches [[x, y, '#hex'?, 'name'?], ...] or dicts {xy, hex?, name?} in BEFORE px;
    scale maps before px -> after px. Hue shift is only measured when both patches have chroma >= min_chroma (hue is
    undefined on grey)."""
    out = []
    for i, s in enumerate(swatches):
        if isinstance(s, dict):
            x, y = s['xy']; hx = s.get('hex'); name = s.get('name', 'swatch%d' % i)
        else:
            x, y = s[0], s[1]; hx = s[2] if len(s) > 2 and isinstance(s[2], str) and s[2].startswith('#') else None
            name = s[3] if len(s) > 3 else (s[2] if len(s) > 2 and isinstance(s[2], str) and not s[2].startswith('#') else 'swatch%d' % i)
        ref = hex_to_rgb(hx) if hx else sample_patch(before, x, y)
        got = sample_patch(after, x * scale[0], y * scale[1])
        h0, s0, c0 = hue_sat(ref); h1, s1, c1 = hue_sat(got)
        out.append({'name': name, 'xy': [x, y], 'ref': rgb_to_hex(ref), 'got': rgb_to_hex(got), 'de76': round(de76(ref, got), 2),
                    'hue_shift': round(hue_delta(h0, h1), 2) if min(c0, c1) >= min_chroma else 0.0,
                    'sat_change': round(s1 - s0, 2), 'chroma': round(min(c0, c1), 1)})
    return out


def auto_swatches(arr, n=6, patch=5, min_chroma=40.0, max_std=4.0, grid=24):
    """Pick up to n flat, saturated 5x5 regions (chip faces, accent bars) plus the flattest bright region (panel
    background) and the flattest dark one (text/ink) from a float image. Returns [[x, y, None, name], ...]."""
    h, w = arr.shape[:2]
    cands = []
    for gy in range(grid):
        for gx in range(grid):
            x, y = int((gx + 0.5) * w / grid), int((gy + 0.5) * h / grid)
            r = patch // 2
            p = arr[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3)
            std = float(p.std(axis=0).max() * 255.0)
            if std > max_std:
                continue
            m = p.mean(axis=0); _, _, ch = hue_sat(m)
            cands.append((ch, std, x, y, m))
    sat = sorted([c for c in cands if c[0] >= min_chroma], key=lambda c: -c[0])
    picked, seen = [], []
    for ch, std, x, y, m in sat:
        if any(abs(x - sx) < w / grid * 2 and abs(y - sy) < h / grid * 2 for sx, sy in seen):
            continue
        picked.append([x, y, None, 'accent%d' % (len(picked) + 1)]); seen.append((x, y))
        if len(picked) >= n: break
    grey = [c for c in cands if c[0] < min_chroma]
    if grey:
        bright = max(grey, key=lambda c: c[4].sum()); dark = min(grey, key=lambda c: c[4].sum())
        picked.append([bright[2], bright[3], None, 'panel']); picked.append([dark[2], dark[3], None, 'ink'])
    return picked


def hex_to_rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], np.float32)


def rgb_to_hex(rgb):
    return '#%02X%02X%02X' % tuple(int(round(float(v) * 255)) for v in rgb)


# ------------------------------------------------------------------------------------------------- ffmpeg fragments
def ffmpeg_filter(adj, broll=False):
    """The adjust vector as an ffmpeg -vf fragment for seq clips graded in ffmpeg instead of numpy.
    Luma moves (gain, black/white point, contrast) are applied identically to R, G and B; the cast correction
    (temperature, tint) is a per-channel additive offset -- i.e. levels + a neutral cast, nothing hue-selective.
    shadows/highlights depend on luma and are NOT expressible per channel: use the numpy path for them."""
    a = validate_adjust(adj, broll)
    g, bp, wp, k = 2.0 ** a.get('exposure', 0.0), a.get('blacks', 0.0) * 0.18, 1.0 - a.get('whites', 0.0) * 0.18, a.get('contrast', 0.0)
    T, tn = a.get('temperature', 0.0), a.get('tint', 0.0)
    offs = {'r': 0.08 * T + 0.04 * tn, 'g': -0.08 * tn, 'b': -(0.08 * T - 0.04 * tn)}
    expr = lambda o: "'clip(((((val/255)*%.6f-%.6f)/%.6f+%.6f-0.5)*%.6f+0.5)*255,0,255)'" % (g, bp, wp - bp, o, 1.0 + k)   # quoted: commas inside
    parts = ['lutrgb=r=%s:g=%s:b=%s' % (expr(offs['r']), expr(offs['g']), expr(offs['b']))]
    if broll and a.get('saturation'):
        parts.append('eq=saturation=%.4f' % (1.0 + a['saturation']))
    if broll and a.get('lut'):
        parts.append(lut_filter(a['lut'], a.get('lut_intensity', 1.0)))
    if a.get('shadows') or a.get('highlights'):
        sys.stderr.write('note: shadows/highlights are luma-masked and omitted from the ffmpeg fragment; grade in numpy for those\n')
    return ','.join(parts)


def lut_filter(cube_path, intensity=1.0):
    """ffmpeg fragment for a .cube LUT at a given intensity (b-roll only). Path must be forward-slash absolute on Windows."""
    p = os.path.abspath(cube_path).replace('\\', '/').replace(':', '\\:')
    if intensity >= 0.999:
        return 'lut3d=file=%s:interp=trilinear' % p
    return 'split[a][b];[b]lut3d=file=%s:interp=trilinear[c];[a][c]blend=all_mode=normal:all_opacity=%.3f' % (p, intensity)


# ------------------------------------------------------------------------------------------------------------ probe
def _ffprobe_meta(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=color_space,color_transfer,color_primaries,pix_fmt,width,height,duration:format=duration', '-of', 'json', path],
                       capture_output=True, text=True)
    d = json.loads(r.stdout or '{}')
    st = (d.get('streams') or [{}])[0]; fm = d.get('format') or {}
    dur = float(st.get('duration') or fm.get('duration') or 0) or None
    g = lambda k: st.get(k) or 'unknown'
    return {'duration': dur, 'color_space': g('color_space'), 'transfer': g('color_transfer'), 'primaries': g('color_primaries'),
            'pix_fmt': g('pix_fmt'), 'width': st.get('width'), 'height': st.get('height')}


def parse_signalstats(raw):
    frames, cur = [], None
    for line in raw.splitlines():
        if re.match(r'^frame:\d', line):
            if cur: frames.append(cur)
            m = re.search(r'pts_time:([+-]?\d*\.?\d+)', line); cur = {'pts_time': float(m.group(1)) if m else None}
            continue
        m = re.search(r'lavfi\.signalstats\.([A-Z]+)=([+-]?\d*\.?\d+)', line)
        if m:
            cur = cur or {}; cur[m.group(1)] = float(m.group(2))
    if cur: frames.append(cur)
    need = ('YMIN', 'YLOW', 'YAVG', 'YHIGH', 'YMAX', 'UAVG', 'VAVG')
    return [f for f in frames if all(k in f for k in need)]


def summarize(frames):
    if not frames:
        raise RuntimeError('ffmpeg returned no analysable frames')
    avg = lambda k: sum(f[k] for f in frames) / len(frames)
    return {'frames': len(frames), 'YMIN': min(f['YMIN'] for f in frames), 'YLOW': avg('YLOW'), 'YAVG': avg('YAVG'), 'YHIGH': avg('YHIGH'),
            'YMAX': max(f['YMAX'] for f in frames), 'UAVG': avg('UAVG'), 'VAVG': avg('VAVG'), 'SATAVG': sum(f.get('SATAVG', 0) for f in frames) / len(frames),
            'shadow_clip_risk': sum(1 for f in frames if f['YLOW'] <= 16) / len(frames),
            'highlight_clip_risk': sum(1 for f in frames if f['YHIGH'] >= 235) / len(frames)}


def suggest(m, ui=True):
    """Bounded starting correction from the measured 8-bit YUV stats (the analyzer thresholds, re-expressed).
    ui=True (product footage): highlight-clip risk is reported, not corrected, and the product limits apply."""
    lim = lambda k, v: max(-LIMITS.get(k, 1.0), min(LIMITS.get(k, 1.0), v))
    avg, lo, hi = m['YAVG'] / 255.0, m['YLOW'] / 255.0, m['YHIGH'] / 255.0
    exp = 0.0
    if avg < 0.28 and hi < 0.65: exp = (0.32 - avg) * 1.2
    elif avg > 0.72 and lo > 0.3: exp = (0.68 - avg) * 1.2
    spread = hi - lo
    con = (0.35 - spread) * 0.4 if spread < 0.35 else 0.0
    warmth = ((m['VAVG'] - 128) + (128 - m['UAVG'])) / 128.0
    cast = m['UAVG'] + m['VAVG'] - 256
    adj = {'exposure': lim('exposure', exp), 'contrast': lim('contrast', con), 'blacks': lim('blacks', 0.08 * m['shadow_clip_risk']),
           'whites': 0.0 if ui else lim('whites', -0.08 * m['highlight_clip_risk']),
           'temperature': lim('temperature', -0.25 * warmth) if abs(warmth) >= 0.08 else 0.0,
           'tint': lim('tint', -cast / 512.0) if abs(cast) >= 10 else 0.0}
    notes = []
    if ui:
        for k, v in list(adj.items()):
            if k in PRODUCT_LIMITS and abs(v) > PRODUCT_LIMITS[k]:
                notes.append('%s %.3f capped to the product limit +-%.2f' % (k, v, PRODUCT_LIMITS[k])); adj[k] = math.copysign(PRODUCT_LIMITS[k], v)
        if m['highlight_clip_risk'] > 0:
            notes.append('highlights at Y>=235 in %.0f%% of frames: expected on white UI panels, reported not corrected' % (100 * m['highlight_clip_risk']))
        if m['shadow_clip_risk'] > 0:
            notes.append('deep shadows (YLOW<=16): dark theme or crushed levels? check the raw frame before lifting')
    return {k: round(v, 3) + 0.0 for k, v in adj.items()}, notes


def probe(path, t0=None, t1=None, frames=SAMPLE_FRAMES, ui=True):
    """ffprobe colour metadata + ffmpeg signalstats over `frames` frames spread across [t0, t1] -> dict."""
    meta = _ffprobe_meta(path)
    is_img = path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))
    span = (t1 - t0) if (t0 is not None and t1 is not None) else meta['duration']
    vf = []
    if not is_img and span:
        vf.append('fps=%.4f' % max(0.1, min(2.0, frames / span)))
    vf += ['format=yuv444p', 'signalstats', 'metadata=print:file=-']
    cmd = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error']
    if t0 is not None: cmd += ['-ss', '%.3f' % t0]
    cmd += ['-i', path]
    if t0 is not None and t1 is not None: cmd += ['-t', '%.3f' % (t1 - t0)]
    cmd += ['-vf', ','.join(vf), '-frames:v', str(frames), '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = summarize(parse_signalstats((r.stdout or '') + '\n' + (r.stderr or '')))     # Windows builds print to either stream
    adj, notes = suggest(m, ui)
    hdr = meta['transfer'] in ('smpte2084', 'arib-std-b67')
    if hdr: notes.append('HDR transfer flagged; this pipeline is SDR sRGB only')
    return {'source': meta, 'hdr': hdr, 'window': [t0, t1], 'measured': {k: round(v, 3) for k, v in m.items()}, 'suggest': adj, 'notes': notes}


def match(a, b, ui=True):
    """Offsets that bring measured B onto measured A's levels and cast (two clips of the same product screen)."""
    ya, yb = max(1.0, a['YAVG']), max(1.0, b['YAVG'])
    exp = math.log2(ya / yb)
    temp = -0.25 * (((b['VAVG'] - a['VAVG']) + (a['UAVG'] - b['UAVG'])) / 128.0)
    tint = -((b['UAVG'] + b['VAVG']) - (a['UAVG'] + a['VAVG'])) / 512.0
    cap = lambda k, v: max(-PRODUCT_LIMITS[k], min(PRODUCT_LIMITS[k], v)) if ui else v
    return {'exposure': round(cap('exposure', exp), 3), 'temperature': round(cap('temperature', temp), 3), 'tint': round(cap('tint', tint), 3),
            'delta': {'YAVG': round(b['YAVG'] - a['YAVG'], 2), 'UAVG': round(b['UAVG'] - a['UAVG'], 2), 'VAVG': round(b['VAVG'] - a['VAVG'], 2)}}


# ----------------------------------------------------------------------------------------------------- compare sheet
def _font(px):
    for p in ('C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def compare_sheet(frame_path, grades, out, crop=None, cell_w=560, cols=4, pad=16, label_h=32, native=False):
    """One reference frame under every candidate grade (grades: {label: adjust | {'lut':..,'intensity':..}}), the
    untouched frame first as 'original'; up to 16 cells, 4 per row. native=True keeps the crop at 1:1 so 1-2 level
    shifts stay visible (a 560 px downscale hides them)."""
    im = Image.open(frame_path).convert('RGB')
    if crop: x, y, w, h = crop; im = im.crop((x, y, x + w, y + h))
    src = to_float(im)
    cells = [('original', src)]
    for label, g in list(grades.items())[:15]:
        g = dict(g); broll = bool(g.pop('broll', False))
        cells.append((label, apply_adjust(src, g, broll=broll or 'lut' in g or 'saturation' in g or 'vibrance' in g)))
    cw = im.width if native else cell_w
    ch = int(round(im.height * cw / im.width))
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new('RGB', (pad + cols * (cw + pad), pad + rows * (ch + label_h + pad)), (24, 24, 24))
    d = ImageDraw.Draw(sheet); f = _font(16)
    for i, (label, arr) in enumerate(cells):
        r, c = divmod(i, cols); x0, y0 = pad + c * (cw + pad), pad + r * (ch + label_h + pad)
        d.rectangle((x0, y0, x0 + cw - 1, y0 + label_h - 1), fill=(40, 40, 40)); d.text((x0 + 8, y0 + 8), label, font=f, fill=(235, 235, 235))
        sheet.paste(to_image(arr).resize((cw, ch), Image.LANCZOS) if (cw, ch) != im.size else to_image(arr), (x0, y0 + label_h))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True); sheet.save(out)
    return sheet.size, len(cells)


# ------------------------------------------------------------------------------------------------------------- LUTs
def parse_cube(path, max_size=64):
    """.cube -> {'size': N, 'table': float32 (N,N,N,3) indexed [r][g][b], 'domain': (min, max), 'title'}.
    3D only (LUT_1D_SIZE is rejected); size <= 64; exactly N^3 rows in the standard red-fastest order."""
    size, title, dmin, dmax, rows = None, '', np.zeros(3), np.ones(3), []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for ln, line in enumerate(fh, 1):
            s = line.strip()
            if not s or s.startswith('#'): continue
            key = s.split()[0].upper()
            if key == 'TITLE': title = s[5:].strip().strip('"')
            elif key == 'LUT_1D_SIZE': raise ValueError('%s: 1D LUTs are not supported' % path)
            elif key == 'LUT_3D_SIZE':
                size = int(s.split()[1])
                if not 2 <= size <= max_size: raise ValueError('%s: LUT_3D_SIZE %d outside 2..%d' % (path, size, max_size))
            elif key == 'DOMAIN_MIN': dmin = np.array([float(v) for v in s.split()[1:4]])
            elif key == 'DOMAIN_MAX': dmax = np.array([float(v) for v in s.split()[1:4]])
            elif key == 'LUT_3D_INPUT_RANGE': dmin, dmax = np.full(3, float(s.split()[1])), np.full(3, float(s.split()[2]))
            else:
                try: rows.append([float(v) for v in s.split()[:3]])
                except ValueError: raise ValueError('%s:%d unreadable line %r' % (path, ln, s[:40]))
    if size is None: raise ValueError('%s: missing LUT_3D_SIZE' % path)
    if len(rows) != size ** 3: raise ValueError('%s: expected %d rows, found %d' % (path, size ** 3, len(rows)))
    if (dmax <= dmin).any(): raise ValueError('%s: DOMAIN_MAX must exceed DOMAIN_MIN' % path)
    tbl = np.array(rows, np.float32).reshape(size, size, size, 3).transpose(2, 1, 0, 3)     # file order: r fastest -> [r][g][b]
    return {'size': size, 'table': tbl, 'domain': (dmin, dmax), 'title': title}


def apply_lut(arr, lut, intensity=1.0):
    """Trilinear 3D LUT lookup on a float image, mixed with the source by intensity. B-ROLL ONLY."""
    N, T = lut['size'], lut['table']; dmin, dmax = lut['domain']
    p = np.clip((arr - dmin) / (dmax - dmin), 0, 1) * (N - 1)
    i0 = np.floor(p).astype(np.int32); i0 = np.clip(i0, 0, N - 2); f = p - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]                 # (..., 1) so they broadcast over the 3 output channels
    c00 = T[r0, g0, b0] * (1 - fr) + T[r0 + 1, g0, b0] * fr
    c10 = T[r0, g0 + 1, b0] * (1 - fr) + T[r0 + 1, g0 + 1, b0] * fr
    c01 = T[r0, g0, b0 + 1] * (1 - fr) + T[r0 + 1, g0, b0 + 1] * fr
    c11 = T[r0, g0 + 1, b0 + 1] * (1 - fr) + T[r0 + 1, g0 + 1, b0 + 1] * fr
    c0 = c00 * (1 - fg) + c10 * fg; c1 = c01 * (1 - fg) + c11 * fg
    out = c0 * (1 - fb) + c1 * fb
    return arr + (out - arr) * float(intensity)


def bake_cube(adj, out, size=33, title='FDE Demo Builder adjust bake'):
    """Bake an adjust vector (b-roll keys allowed) into a .cube so build tools can apply it with ffmpeg lut3d."""
    g = np.linspace(0, 1, size, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing='ij')                      # red fastest in the file
    grid = np.stack([r, gg, b], axis=-1).reshape(-1, 1, 3)
    graded = apply_adjust(grid, adj, broll=True).reshape(-1, 3)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('TITLE "%s"\nLUT_3D_SIZE %d\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n' % (title, size))
        fh.write('\n'.join('%.6f %.6f %.6f' % tuple(v) for v in graded) + '\n')
    return out


# ------------------------------------------------------------------------------------------------------ speed ramps
RMIN, RMAX, CELLS = 0.1, 10.0, 48


def _lane(lane):
    return sorted([[float(p[0]), max(RMIN, min(RMAX, float(p[1]))), float(p[2]) if len(p) > 2 else 0.0] for p in lane], key=lambda p: p[0])


def rate_at(lane, dt):
    """Rate at clip-local dt: log-space interpolation, optional per-segment bend x^(2^(2*curve))."""
    if isinstance(lane, (int, float)): return float(lane)
    P = _lane(lane)
    if not P: return 1.0
    if dt <= P[0][0]: return P[0][1]
    if dt >= P[-1][0]: return P[-1][1]
    lo, hi = 0, len(P) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        if P[m][0] <= dt: lo = m
        else: hi = m
    a, b = P[lo], P[hi]; span = b[0] - a[0]
    if span <= 0: return b[1]
    x = (dt - a[0]) / span
    if a[2]: x = x ** (2.0 ** (2.0 * a[2]))
    return math.exp(math.log(a[1]) + (math.log(b[1]) - math.log(a[1])) * x)


def ramp_table(lane):
    """(ts, ss): clip-local times and the source seconds consumed by each, 48 trapezoid cells per segment."""
    P = _lane(lane); ts, ss = [0.0], [0.0]
    def push(t):
        pt = ts[-1]
        if t <= pt: return
        ts.append(t); ss.append(ss[-1] + (rate_at(lane, pt) + rate_at(lane, t)) / 2.0 * (t - pt))
    if P:
        push(max(0.0, P[0][0]))
        for i in range(1, len(P)):
            a, b = P[i - 1][0], P[i][0]
            if b <= 0: continue
            for k in range(1, CELLS + 1): push(max(a, 0.0) + (b - a) * k / CELLS)
    return ts, ss, (P[0][1] if P else 1.0), (P[-1][1] if P else 1.0)


def _interp(xs, ys, x):
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        if xs[m] <= x: lo = m
        else: hi = m
    return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo])


def source_time(lane, dt):
    """Source seconds on screen at clip-local dt (the integral of the rate)."""
    if isinstance(lane, (int, float)): return dt * float(lane)
    ts, ss, first, last = ramp_table(lane)
    if dt <= 0: return dt * first
    if dt >= ts[-1]: return ss[-1] + (dt - ts[-1]) * last
    return _interp(ts, ss, dt)


def time_at_source(lane, s):
    """Inverse: the clip-local time at which `s` source seconds have been consumed."""
    if isinstance(lane, (int, float)): return s / float(lane)
    ts, ss, first, last = ramp_table(lane)
    if s <= 0: return s / first
    if s >= ss[-1]: return ts[-1] + (s - ss[-1]) / last
    return _interp(ss, ts, s)


def frame_at(lane, dt, fps, n_frames, from_=1):
    """Source frame index (1-based, like f_001.jpg) shown at dt; held on the last frame once the source runs out."""
    f = from_ + int(math.floor(max(0.0, source_time(lane, max(0.0, dt))) * fps + 1e-6))
    return max(from_, min(n_frames, f))


def hold_frames(lane, shot_dur, fps, n_frames, from_=1):
    """How many film frames of the shot show the held last source frame (0 = the source outlasts the shot)."""
    avail = (n_frames - from_ + 1) / float(fps)
    t_end = time_at_source(lane, avail)
    return max(0, int(round((shot_dur - t_end) * fps))) if t_end < shot_dur else 0


def ramp_to(reveal_src, land_at, ease=0.25):
    """Lane that runs fast through the wait and is at exactly 1.0x when source moment `reveal_src` is on screen at
    clip time `land_at` (a wt() word), easing into 1x over the last `ease` s. None if the rate leaves 0.1..10."""
    ease = min(ease, land_at); flat = land_at - ease
    def integral(r):
        return r * flat + (ease if abs(r - 1) < 1e-9 else ease * (r - 1) / math.log(r))
    lo, hi = RMIN, RMAX
    if reveal_src < integral(lo) or reveal_src > integral(hi): return None
    for _ in range(60):
        m = (lo + hi) / 2
        if integral(m) < reveal_src: lo = m
        else: hi = m
    r = (lo + hi) / 2
    return [[0.0, r], [flat, r], [land_at, 1.0]] if flat > 0 else [[0.0, r], [land_at, 1.0]]


JS_SNIPPET = """// footage.js seqFrame(): accept play.rate as a number OR a lane [[t, rate], ...] in clip-local seconds
const rate = (sh.play && sh.play.rate) || 1, dt = Math.max(0, t - at);
let f = Array.isArray(rate) ? root.VFX.ramp.frameAt(rate, dt, c.fps, n, from) : from + Math.floor(dt * c.fps * rate + 1e-6);"""


# --------------------------------------------------------------------------------------------------------- selftest
def _synthetic_ui(w=1280, h=720):
    """A fictional 'Acme Console' panel: white page, grey rail, teal accent, red/green status chips, dark text."""
    im = Image.new('RGB', (w, h), '#FFFFFF'); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w, 64), fill='#0E7C86'); d.rectangle((0, 64, 240, h), fill='#F1F3F4')
    d.rectangle((300, 140, 520, 180), fill='#D93025'); d.rectangle((560, 140, 780, 180), fill='#1E8E3E')
    d.rectangle((300, 220, 1180, 236), fill='#1C1815'); d.rectangle((300, 260, 900, 272), fill='#5F6368')
    d.rectangle((300, 320, 1180, 640), fill='#E8F0FE', outline='#1A73E8', width=3)
    return im


SWATCHES = [[640, 32, None, 'accent'], [410, 160, None, 'status red'], [670, 160, None, 'status green'],
            [120, 400, None, 'rail'], [740, 228, None, 'ink'], [1000, 500, None, 'panel']]


def selftest(tmp=None):
    tmp = tmp or os.path.join(os.environ.get('TEMP', '/tmp'), 'grade_selftest'); os.makedirs(tmp, exist_ok=True)
    ok = True
    def check(name, cond, detail=''):
        nonlocal ok; ok = ok and bool(cond); print('  %-34s %s  %s' % (name, 'PASS' if cond else 'FAIL', detail))
    ui = _synthetic_ui(); src = to_float(ui); png = os.path.join(tmp, 'ui.png'); ui.save(png)
    # 1 adjust maths + swatch guard
    g1 = {'blacks': 0.03, 'temperature': -0.05, 'tint': 0.02}          # a white-panel UI: levels + cast, never + exposure
    out = apply_adjust_image(ui, g1, swatches=SWATCHES)
    rep = swatch_report(src, to_float(out), SWATCHES)
    check('adjust keeps UI colour truth', max(r['de76'] for r in rep) <= DE_PRODUCT and max(abs(r['hue_shift']) for r in rep) <= 6,
          'worst dE76 %.2f hue %+.2f deg sat %+.1f%%' % (max(r['de76'] for r in rep), max((r['hue_shift'] for r in rep), key=abs), max((r['sat_change'] for r in rep), key=abs)))
    try: apply_adjust_image(ui, {'exposure': 0.1}, swatches=SWATCHES); check('guard: +0.1 EV clips a light panel', False)
    except ValueError as e: check('guard: +0.1 EV clips a light panel', 'panel' in str(e), str(e)[:72])
    mid = np.full((4, 4, 3), 0.5, np.float32)
    check('exposure gain 2^x', abs(apply_adjust(mid, {'exposure': 0.3})[0, 0, 0] - 0.5 * 2 ** 0.3) < 1e-6)
    check('temperature +0.1 -> R +0.008 B -0.008', np.allclose(apply_adjust(mid, {'temperature': 0.1})[0, 0], [0.508, 0.5, 0.492], atol=1e-6))
    check('levels bp/wp', abs(apply_adjust(np.full((1, 1, 3), 0.18 * 0.5, np.float32), {'blacks': 0.5})[0, 0, 0]) < 1e-6)
    for bad, why in (({'saturation': 0.3}, 'saturation on product'), ({'temperature': 0.3}, 'temperature beyond +-0.15'), ({'lut': 'x.cube'}, 'LUT on product'), ({'exposure': 0.5}, 'exposure beyond +-0.3')):
        try: validate_adjust(bad); check('refuses ' + why, False)
        except ValueError as e: check('refuses ' + why, True, str(e)[:60])
    check('b-roll allows saturation', validate_adjust({'saturation': 0.3}, broll=True) == {'saturation': 0.3})
    try: apply_adjust_image(ui, {'temperature': 0.15, 'tint': 0.15, 'exposure': 0.3}, swatches=SWATCHES, de_max=2.0); check('swatch guard raises on a big move', False)
    except ValueError as e: check('swatch guard raises on a big move', 'UI colour truth' in str(e), str(e)[:70])
    # 2 ffmpeg fragment == numpy (no shadows/highlights)
    g2 = {'exposure': -0.2, 'contrast': 0.1, 'blacks': 0.05, 'whites': -0.05, 'temperature': 0.1, 'tint': -0.08}
    ff = os.path.join(tmp, 'ff.png')
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', png, '-vf', ffmpeg_filter(g2), ff], capture_output=True, text=True)
    if r.returncode == 0:
        diff = np.abs(to_float(Image.open(ff)) - apply_adjust(src, g2)).max() * 255
        check('ffmpeg lutrgb fragment == numpy', diff <= 2.0, 'max |diff| %.2f levels' % diff)
    else: check('ffmpeg lutrgb fragment == numpy', False, r.stderr[-120:])
    # 3 probe on a 1 s synthetic recording
    mp4 = os.path.join(tmp, 'rec.mp4')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-loop', '1', '-i', png, '-t', '1', '-r', '30', '-vf', 'scale=1920:1080', '-pix_fmt', 'yuv420p', mp4], check=True)
    pr = probe(mp4)
    y_expect = 16 + 219 * float((src @ np.array([0.299, 0.587, 0.114], np.float32)).mean())
    check('probe YAVG matches the frame', abs(pr['measured']['YAVG'] - y_expect) <= 4, 'YAVG %.1f expected %.1f, %d frames' % (pr['measured']['YAVG'], y_expect, pr['measured']['frames']))
    check('probe reports highlight risk, no whites fix', pr['measured']['highlight_clip_risk'] > 0 and pr['suggest']['whites'] == 0.0, '; '.join(pr['notes'])[:90])
    dark = {'YAVG': 50, 'YLOW': 10, 'YHIGH': 120, 'YMIN': 0, 'YMAX': 200, 'UAVG': 120, 'VAVG': 140, 'SATAVG': 20, 'shadow_clip_risk': 1.0, 'highlight_clip_risk': 0.0}
    s, _ = suggest(dark, ui=False)
    check('suggest: dark warm clip', abs(s['exposure'] - min(2, (0.32 - 50 / 255) * 1.2)) < 1e-3 and s['blacks'] == 0.08 and s['temperature'] < 0, json.dumps(s))
    mm = match(pr['measured'], dict(pr['measured'], YAVG=pr['measured']['YAVG'] * 0.9))
    check('match: 10% darker clip -> +exposure', 0.1 < mm['exposure'] <= 0.3, json.dumps(mm['exposure']))
    # 4 LUT round trip
    cube = os.path.join(tmp, 'look.cube'); bake_cube({'temperature': 0.3, 'saturation': 0.2, 'contrast': 0.1}, cube, size=33)
    lut = parse_cube(cube)
    diff = np.abs(apply_lut(src, lut) - apply_adjust(src, {'temperature': 0.3, 'saturation': 0.2, 'contrast': 0.1}, broll=True)).max() * 255
    check('bake -> parse -> trilinear == numpy', lut['size'] == 33 and diff <= 3.0, 'max |diff| %.2f levels (33^3)' % diff)
    ident = os.path.join(tmp, 'ident.cube'); bake_cube({}, ident, size=9)
    check('identity LUT is identity', np.abs(apply_lut(src, parse_cube(ident)) - src).max() * 255 < 0.6)
    check('lut3d fragment at 0.4', 'blend=all_mode=normal:all_opacity=0.400' in lut_filter(cube, 0.4))
    # 5 compare sheet
    size, n = compare_sheet(png, {'A levels': g1, 'B warm': {'temperature': 0.1}, 'look 40%': {'lut': cube, 'lut_intensity': 0.4, 'broll': True}}, os.path.join(tmp, 'sheet.png'))
    check('compare sheet 4 cells', n == 4 and size[0] == 16 + 4 * (560 + 16), '%sx%s' % size)
    # 6 ramp maths
    lane = [[0, 0.5], [1, 2]]
    check('log lane: 0.5->2 passes 1 at midpoint', abs(rate_at(lane, 0.5) - 1.0) < 1e-9)
    check('integral of the log lane', abs(source_time(lane, 1.0) - 1.5 / math.log(4)) < 2e-4, '%.5f vs %.5f' % (source_time(lane, 1.0), 1.5 / math.log(4)))
    check('inverse round trip', abs(time_at_source(lane, source_time(lane, 0.73)) - 0.73) < 1e-6)
    r2 = ramp_to(6.0, 3.0)
    check('rampTo lands the reveal at 1x', r2 is not None and abs(source_time(r2, 3.0) - 6.0) < 1e-3 and abs(rate_at(r2, 3.0) - 1.0) < 1e-9, json.dumps([[round(a, 3), round(b, 3)] for a, b in [(p[0], p[1]) for p in r2]]) if r2 else 'None')
    check('rampTo refuses impossible', ramp_to(100.0, 1.0) is None)
    check('frame hold on the last frame', frame_at([[0, 3], [2, 1]], 10.0, 30, 90) == 90 and hold_frames([[0, 3]], 4.0, 30, 90) == 90,
          '3 s source at 3x inside a 4 s shot -> %d held frames' % hold_frames([[0, 3]], 4.0, 30, 90))
    check('rate clamp 0.1..10', rate_at([[0, 50]], 0) == 10.0)
    print('\n%s  (%s)' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', tmp))
    return ok


# -------------------------------------------------------------------------------------------------------------- CLI
def _arg(args, flag, default=None, cast=str):
    if flag in args:
        i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return cast(v)
    return default


def main(argv):
    args = list(argv)
    if not args or args[0] in ('-h', '--help'):
        print(__doc__); return 0
    if args[0] == '--selftest':
        return 0 if selftest(args[1] if len(args) > 1 else None) else 1
    cmd = args.pop(0)
    if cmd == 'probe':
        frames = _arg(args, '--frames', SAMPLE_FRAMES, int); broll = '--broll' in args; args = [a for a in args if a != '--broll']
        write = _arg(args, '--write'); other = _arg(args, '--match')
        path = args.pop(0); t0 = float(args.pop(0)) if args else None; t1 = float(args.pop(0)) if args else None
        res = probe(path, t0, t1, frames, ui=not broll)
        if other:
            o = json.load(open(other, encoding='utf-8')); o = o.get('measured', o)
            res['match'] = match(o, res['measured'], ui=not broll)
        if write:
            meta = json.load(open(write, encoding='utf-8')) if os.path.exists(write) else {}
            meta['measured'] = res['measured']; meta['grade_suggest'] = res['suggest']; json.dump(meta, open(write, 'w'), indent=1)
        print(json.dumps(res, indent=1)); return 0
    if cmd == 'apply':
        adj = json.loads(_arg(args, '--adjust', '{}')); broll = '--broll' in args; args = [a for a in args if a != '--broll']
        sw = _arg(args, '--swatches'); src, dst = args[0], args[1]
        swl = json.load(open(sw, encoding='utf-8')) if sw else None
        im = Image.open(src).convert('RGB')
        if swl is None and not broll:
            swl = auto_swatches(to_float(im)); print('auto swatches:', json.dumps(swl))
        out = apply_adjust_image(im, adj, broll=broll, swatches=swl)
        out.save(dst, quality=94)
        if swl and not broll: print(json.dumps(swatch_report(to_float(im), to_float(out), swl), indent=1))
        print('wrote', dst); return 0
    if cmd == 'filter':
        adj = json.loads(_arg(args, '--adjust', '{}')); print(ffmpeg_filter(adj, broll='--broll' in args)); return 0
    if cmd == 'compare':
        crop = _arg(args, '--crop'); cell = _arg(args, '--cell', 560, int); native = '--native' in args; args = [a for a in args if a != '--native']
        frame, gj, out = args[0], args[1], args[2]
        size, n = compare_sheet(frame, json.load(open(gj, encoding='utf-8')), out, crop=[int(v) for v in crop.split(',')] if crop else None, cell_w=cell, native=native)
        print('wrote %s  %dx%d  %d cells' % (out, size[0], size[1], n)); return 0
    if cmd == 'lut':
        inten = _arg(args, '--intensity', 1.0, float); ap = _arg(args, '--apply')
        cube = args[0]; lut = parse_cube(cube)
        print('LUT %s size %d title %r' % (cube, lut['size'], lut['title'])); print(lut_filter(cube, inten))
        if ap:
            dst = args[1]; im = Image.open(ap).convert('RGB'); to_image(apply_lut(to_float(im), lut, inten)).save(dst); print('wrote', dst, '(b-roll only)')
        return 0
    if cmd == 'bake-lut':
        size = _arg(args, '--size', 33, int); adj = json.load(open(args[0], encoding='utf-8')); print('wrote', bake_cube(adj, args[1], size)); return 0
    if cmd == 'ramp':
        fps = _arg(args, '--fps', 30, int); n = _arg(args, '--frames', 0, int); dur = _arg(args, '--dur', None, float)
        lane = json.loads(args[0]); dur = dur if dur is not None else (time_at_source(lane, n / fps) if n else max(p[0] for p in lane))
        rows = []
        for k in range(int(round(dur * fps)) + 1):
            dt = k / fps; rows.append({'film_frame': k, 'dt': round(dt, 3), 'rate': round(rate_at(lane, dt), 3), 'src_s': round(source_time(lane, dt), 3),
                                       'src_frame': frame_at(lane, dt, fps, n) if n else None})
        print(json.dumps({'lane': lane, 'hold_frames': hold_frames(lane, dur, fps, n) if n else None, 'rows': rows}, indent=1)); return 0
    print('unknown command', cmd); print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
