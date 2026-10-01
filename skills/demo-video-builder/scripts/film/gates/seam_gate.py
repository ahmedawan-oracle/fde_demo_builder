# -*- coding: utf-8 -*-
"""seam_gate.py — the seam gate: does the eye's momentum survive every cut?  (qa_film.py plug-in)

Gates (GATE_NAMES, in order):
  seam ledger   the plan is consistent: every row's exit and entry share an axis and a signed direction,
                no two consecutive seams reverse each other without a cause (click | chapter | impact),
                cuts resolve to seconds inside the film. WARN: > 3 techniques, > 1 reserved vector per act.
  seams move    frame-based, on the rendered film: for each ledger row the picture is still moving in the
                last 0.1 s before the cut and already mid-flight in the first 0.1 s after it, in the ledger's
                direction, and the cut frame is one side or the other — never a blend of both (no dissolve).
                Motion is the dominant translation (phase correlation, x/y rows) or dominant scale change
                (z rows) between two frames two frames apart, corroborated by mean-abs-diff + the shift of
                the picture's edge-energy centroid ("optical-flow-lite"). Static below 15 px/s on a 1920
                frame (5 px/s at the 640-wide QA frame) or 0.04 scale/s; entry/exit speed ratio > 3 = WARN.
  seam flash    white-flash guard: no frame within ±2 frames of any cut (timeline cuts + ledger cuts) whose
                mean luma exceeds BOTH neighbours by > 40 (0–255) or is > 235 while neither neighbour is.
                A sustained bright screen passes; a one-frame spike that belongs to neither side fails.
  stage ground  static: the authored scene declares an opaque background on html, body or #stage (an
                unpainted root composites the mid-cut opacity dip over white).
  idle wobble   static WARN (never FAIL): Math.sin/cos of t feeding a transform/left/top in an authored
                scene outside an element marked data-diegetic — the idle loop the doctrine bans.

Ledger source: out/timeline.json "seams" (written by export_timeline.js from seams.json via lib/seams.js)
or, failing that, <project>/seams.json (qa.json "seams" overrides the path); cue expressions such as
"wt('ask','question')" or "P.close" are resolved here from scenes/timing_<name>_data.js. No ledger = the
ledger gates pass with a note; the flash guard and the static lints always run.

Standalone:
  python gates/seam_gate.py --selftest                      synthetic film: a good seam, a settled cut, a
                                                            dissolve, a white flash and a zoom-through
  python gates/seam_gate.py probe <film.mp4> <t> [fps]      measured vectors around t (author the ledger
                                                            from measurement, not guesswork)
  python gates/seam_gate.py verify <film.mp4> <seams.json|timeline.json> [fps] [--edges 1.0]
                                                            (--edges 0 for a short harness clip)
qa.json keys: "seams" (ledger path, default seams.json), "seam_edges" (seconds excluded at both ends, 1.0)

Thresholds are the study's numbers; measure a failing seam (probe) before loosening any of them.
"""
import json, math, os, re, subprocess, sys

import numpy as np

GATE_NAMES = ['seam ledger', 'seams move', 'seam flash', 'stage ground', 'idle wobble']

THRESH = {
    'static_pxs_1920': 15.0,   # x/y: slower than this (on a 1920-wide frame) = static; scaled to the measured width
    'static_scale_s': 0.04,    # z: effective-scale units per second
    'speed_ratio': 3.0,        # entry/exit velocity ratio beyond this = WARN
    'window_s': 0.1,           # exit window cut-0.1 .. cut-1f, entry window cut+1f .. cut+0.1 (two frames apart at 30 fps)
    'flash_jump': 40.0,        # luma spike over both neighbours
    'flash_white': 235.0,      # or near-white while neither neighbour is
    'min_change': 1.0,         # mean-abs-diff between the two sides below this = no visible cut (WARN, cuts-land owns it)
    'carrier_px': 12, 'carrier_size': 0.05,   # DOM-mode tolerances (documented; see motion-doctrine.md)
}
W, H = 640, 360                # measurement frame (grey), same as qa_film.py's cut gates
ZW, ZH = 320, 180              # z search frame
RESERVED = ('y-1', 'z+1', 'z-1')
CAUSES = ('click', 'chapter', 'impact')
# per-technique exit window (seconds before the cut) when the row does not say: the waterfall's last word
# dies 0.02 s before the cut, so its streak is measured a little earlier
EXIT_WINDOW = {'waterfall': (0.20, 0.10)}


# ------------------------------------------------------------------------------------------ frames
def decode(film, k0, n, fps=30, w=W, h=H):
    """n consecutive grey frames starting at frame index k0 (one ffmpeg call). Frame k is the picture drawn
    at t = k/fps; seeking to (k0 - 0.5)/fps makes frame k0 the first one ffmpeg emits."""
    k0 = max(0, int(k0))
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.4f' % ((k0 - 0.5) / fps), '-i', film, '-frames:v', str(n),
                        '-vf', 'scale=%d:%d,format=gray' % (w, h), '-f', 'rawvideo', '-'], capture_output=True)
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    got = len(buf) // (w * h)
    return [buf[i * w * h:(i + 1) * w * h].reshape(h, w) for i in range(got)]


def cut_frame(c, fps=30):
    """index of the first frame drawn at or after the cut time (the incoming side's first frame)."""
    return int(math.ceil(c * fps - 1e-6))


def _norm(a):
    f = a.astype(np.float32)
    f -= f.mean()
    sd = f.std()
    return f / sd if sd > 1e-6 else f


def shift(a, b):
    """dominant translation (dx, dy) such that b ~= a moved by (dx, dy), plus the peak response (0..1).
    Phase correlation on Hann-windowed, normalised frames with a parabolic sub-pixel fit."""
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    A, B = np.fft.fft2(_norm(a) * win), np.fft.fft2(_norm(b) * win)
    R = B * np.conj(A)
    R /= (np.abs(R) + 1e-9)
    r = np.real(np.fft.ifft2(R))
    iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)
    peak = float(r[iy, ix])

    def sub(v_m, v_0, v_p):
        d = v_m - 2 * v_0 + v_p
        return 0.0 if abs(d) < 1e-12 else 0.5 * (v_m - v_p) / d
    dx = ix + sub(r[iy, (ix - 1) % w], r[iy, ix], r[iy, (ix + 1) % w])
    dy = iy + sub(r[(iy - 1) % h, ix], r[iy, ix], r[(iy + 1) % h, ix])
    if dx > w / 2: dx -= w
    if dy > h / 2: dy -= h
    return float(dx), float(dy), peak * (h * w) / max(1.0, float((win * win).sum()))


def edge_centroid(a):
    """centroid of the picture's edge energy (where the detail is); its shift corroborates the direction."""
    f = a.astype(np.float32)
    g = np.abs(np.diff(f, axis=1))[:-1, :] + np.abs(np.diff(f, axis=0))[:, :-1]
    s = g.sum()
    if s < 1e-6:
        return (a.shape[1] / 2.0, a.shape[0] / 2.0)
    ys, xs = np.indices(g.shape)
    return (float((g * xs).sum() / s), float((g * ys).sum() / s))


def _zoom(a, s):
    from PIL import Image
    h, w = a.shape
    im = Image.fromarray(a, mode='F')
    cx, cy = w / 2.0, h / 2.0
    return np.asarray(im.transform((w, h), Image.AFFINE, (1 / s, 0, cx - cx / s, 0, 1 / s, cy - cy / s), resample=Image.BILINEAR))


def scale_change(a, b, lo=0.85, hi=1.18):
    """dominant scale s such that b ~= a zoomed by s about the frame centre (coarse 0.01 then fine 0.001),
    compared on the central 80 % so the border fill does not vote."""
    from PIL import Image, ImageFilter
    soft = lambda f: np.asarray(Image.fromarray(f).resize((ZW, ZH), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2)))   # same softness both sides
    A, B = _norm(soft(a)), _norm(soft(b))
    my, mx = ZH // 10, ZW // 10
    Bc = B[my:-my, mx:-mx]
    cost = lambda s: float(np.abs(_zoom(A, s)[my:-my, mx:-mx] - Bc).mean())
    coarse = np.arange(lo, hi + 1e-9, 0.01)
    s0 = float(coarse[int(np.argmin([cost(s) for s in coarse]))])
    fine = np.arange(s0 - 0.01, s0 + 0.01 + 1e-9, 0.001)
    costs = [cost(s) for s in fine]
    return float(fine[int(np.argmin(costs))])


def mad(a, b):
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def highpass(f, radius=6):
    """320x180 high-pass copy (detail minus its local mean): what the eye reads as structure."""
    from PIL import Image, ImageFilter
    im = Image.fromarray(f).resize((ZW, ZH), Image.BILINEAR)
    lo = im.filter(ImageFilter.GaussianBlur(radius))
    return (np.asarray(im).astype(np.float32) - np.asarray(lo).astype(np.float32)).ravel()


def blend_fit(fm, f0, fp):
    """is the cut frame a mix of its neighbours? Least-squares on HIGH-PASS copies: hp(f0) ~= a*hp(fm) +
    b*hp(fp) + c. A dissolve carries both sides' structure (a, b both well above zero, tight fit); a hard
    cut whose incoming layer ignites at 0.35 opacity over the stage ground carries only the incoming
    structure (a ~ 0), even though its brightness sits between the neighbours. Returns (a, b, r2, corr)."""
    m, z, p = highpass(fm), highpass(f0), highpass(fp)
    corr = float(np.corrcoef(m, p)[0, 1]) if m.std() > 1e-6 and p.std() > 1e-6 else 1.0
    X = np.stack([m, p, np.ones_like(m)], 1)
    coef = np.linalg.lstsq(X, z, rcond=None)[0]
    pred = X @ coef
    ss = float(((z - z.mean()) ** 2).sum())
    r2 = 1.0 - float(((z - pred) ** 2).sum()) / ss if ss > 1e-6 else 0.0
    return float(coef[0]), float(coef[1]), r2, corr


BLEND_MIN_COEF, BLEND_MIN_R2, SAME_SIDES_CORR = 0.25, 0.6, 0.995   # corr guard only for near-identical sides (ill-conditioned fit)


def snap_cut(F, kc):
    """the final MP4 can sit one frame off the clock (mux/credit re-wrap); pick the frame among kc-1, kc,
    kc+1 where the picture actually changes, when that change is clearly the biggest. Returns (k, note)."""
    d = {k: mad(F(k - 1), F(k)) for k in (kc - 1, kc, kc + 1)}
    best = max(d, key=d.get)
    rest = sorted(d.values())[-2]
    if best != kc and d[best] >= 2.0 * max(rest, 0.5):
        return best, ' (cut frame snapped %+d)' % (best - kc)
    return kc, ''


def measure(fa, fb, dt, axis):
    """velocity of the dominant motion between two frames dt seconds apart, on the ledger axis.
    x/y → px/s at the measured width (and the 1920-frame equivalent); z → effective-scale units/s."""
    if axis == 'z':
        s = scale_change(fa, fb)
        return {'v': (s - 1.0) / dt, 'unit': 'scale/s', 'detail': 's %.3f' % s, 'mad': mad(fa, fb)}
    dx, dy, resp = shift(fa, fb)
    ca, cb = edge_centroid(fa), edge_centroid(fb)
    cen = (cb[0] - ca[0]) if axis == 'x' else (cb[1] - ca[1])
    v = (dx if axis == 'x' else dy) / dt
    return {'v': v, 'v1920': v * 1920.0 / fa.shape[1], 'unit': 'px/s', 'resp': resp, 'centroid': cen / dt, 'mad': mad(fa, fb),
            'detail': 'shift %.2f px resp %.2f centroid %+.1f px/s mad %.1f' % ((dx if axis == 'x' else dy), resp, cen / dt, mad(fa, fb))}


def is_static(m, axis, width=W):
    if axis == 'z':
        return abs(m['v']) < THRESH['static_scale_s']
    return abs(m['v']) < THRESH['static_pxs_1920'] * width / 1920.0


# ------------------------------------------------------------------------------------------ per-cut checks
def check_seam(film, row, fps=30, dur=None):
    """frame checks for one ledger row → (ok, warn, [lines]). Rows of type match-cut/morph skip the vector
    checks (their motion may start at the boundary) and keep the overlap test."""
    c = float(row['cut'])
    kc0 = cut_frame(c, fps)
    axis = row.get('entry', {}).get('axis')
    want = row.get('entry', {}).get('dir')
    typ = row.get('type', 'cut')
    tech = row.get('technique', 'cut-the-curve')
    ew = row.get('exitWindow') or EXIT_WINDOW.get(tech, (THRESH['window_s'], 1.0 / fps))
    nb = int(round(ew[0] * fps))                       # exit frames before the cut: kc-nb .. kc-na
    na = max(1, int(round(ew[1] * fps)))
    ne = int(round(THRESH['window_s'] * fps))          # entry frames: kc+1 .. kc+ne
    k0 = kc0 - max(nb, 4) - 1
    frames = decode(film, k0, max(nb, 4) + max(ne, 4) + 3, fps)
    if len(frames) < max(nb, 4) + max(ne, 4) + 3:
        return False, False, ['%s: could not decode frames around %.3f s' % (row.get('id', '?'), c)]
    F = lambda k: frames[k - k0]
    kc, snap = snap_cut(F, kc0)
    lines, ok, warn = [], True, False
    tag = '%s @%.3f%s' % (row.get('id', 'seam'), c, snap)
    # one side per frame: the cut frame must look like one neighbour, never like their mix
    fm, f0, fp = F(kc - 1), F(kc), F(kc + 1)
    cross = mad(fm, fp)
    a, b, r2, corr = blend_fit(fm, f0, fp)
    if cross < THRESH['min_change'] or corr > SAME_SIDES_CORR:
        warn = True
        lines.append('%s: WARN the two sides barely differ (mad %.2f, corr %.2f) — is this a cut?' % (tag, cross, corr))
    elif a > BLEND_MIN_COEF and b > BLEND_MIN_COEF and r2 > BLEND_MIN_R2:
        ok = False
        lines.append('%s: FAIL cut frame is a blend of both sides (%.2f out + %.2f in, fit %.2f) — a dissolve, not a cut' % (tag, a, b, r2))
    if typ != 'cut' or axis not in ('x', 'y', 'z') or want not in (1, -1):
        lines.append('%s: %s — overlap only (%s)' % (tag, typ, 'blend-free' if ok else 'blend'))
        return ok, warn, lines
    dt_e = (nb - na) / fps if nb > na else 1.0 / fps
    mex = measure(F(kc - nb), F(kc - na), dt_e, axis)
    men = measure(F(kc + 1), F(kc + ne), (ne - 1) / fps if ne > 1 else 1.0 / fps, axis)
    if axis == 'z':
        # a z entry arrives at peak blur (10–18 px) and low opacity, which flattens the scale estimate on its
        # very first frames; also measure one frame later (still inside the first 0.13 s) and keep the stronger
        men2 = measure(F(kc + 2), F(kc + ne + 1), (ne - 1) / fps if ne > 1 else 1.0 / fps, axis)
        if abs(men2['v']) > abs(men['v']):
            men = dict(men2, detail=men2['detail'] + ' (kc+2..kc+%d)' % (ne + 1))
    sgn = lambda v: 1 if v > 0 else -1
    for side, m in (('exit', mex), ('entry', men)):
        if is_static(m, axis):
            ok = False
            lines.append('%s: FAIL %s is static (%s %.3g %s; %s)' % (tag, side, axis, m['v'], m['unit'], m['detail']))
        elif sgn(m['v']) != want:
            ok = False
            lines.append('%s: FAIL %s moves %s%s, ledger says %s%s (%s)' % (tag, side, axis, '+' if m['v'] > 0 else '-', axis, '+' if want > 0 else '-', m['detail']))
        else:
            lines.append('%s: ok %s %s%s %.3g %s (%s)' % (tag, side, axis, '+' if m['v'] > 0 else '-', m['v'], m['unit'], m['detail']))
    if not is_static(mex, axis) and not is_static(men, axis):
        ratio = abs(men['v']) / max(1e-9, abs(mex['v']))
        if ratio > THRESH['speed_ratio'] or ratio < 1.0 / THRESH['speed_ratio']:
            warn = True
            lines.append('%s: WARN entry/exit speed ratio %.2f (want within %gx)' % (tag, ratio, THRESH['speed_ratio']))
    return ok, warn, lines


def check_flash(film, c, fps=30):
    """luma spike test on frames kc-2 .. kc+2 → list of (frame_index, luma, left, right) offenders."""
    kc = cut_frame(c, fps)
    fr = decode(film, kc - 3, 7, fps, 160, 90)
    if len(fr) < 7:
        return []
    L = [float(f.mean()) for f in fr]
    out = []
    for i in range(1, 6):                        # frames kc-2 .. kc+2 with both neighbours available (covers a ±1 frame container offset)
        m, a, b = L[i], L[i - 1], L[i + 1]
        if (m - a > THRESH['flash_jump'] and m - b > THRESH['flash_jump']) or (m > THRESH['flash_white'] and a <= THRESH['flash_white'] and b <= THRESH['flash_white']):
            out.append((kc - 3 + i, round(m, 1), round(a, 1), round(b, 1)))
    return out


# ------------------------------------------------------------------------------------------ ledger
def validate_rows(rows):
    """mirror of SEAM.validate(): (errors, warnings)."""
    errors, warnings, techs, spent, seen = [], [], set(), {}, set()
    R = sorted(rows, key=lambda r: r.get('cut', 0) if isinstance(r.get('cut'), (int, float)) else 0)
    prev = None
    for i, r in enumerate(R):
        rid, typ = r.get('id', 'row %d' % i), r.get('type', 'cut')
        c = r.get('cut')
        if not isinstance(c, (int, float)) or not math.isfinite(c):
            errors.append('%s: cut is not resolved to seconds (%r)' % (rid, c)); continue
        if c in seen:
            errors.append('%s: duplicate cut time %s' % (rid, c))
        seen.add(c)
        if typ != 'cut':
            car = r.get('carrier') or {}
            if not (car.get('out') and car.get('in')):
                errors.append('%s: %s rows need carrier {out, in}' % (rid, typ))
            continue
        ex, en = r.get('exit'), r.get('entry')
        if not ex or not en:
            errors.append('%s: needs exit and entry vectors' % rid); continue
        for side, v in (('exit', ex), ('entry', en)):
            if v.get('axis') not in ('x', 'y', 'z'):
                errors.append('%s: %s.axis must be x, y or z' % (rid, side))
            if v.get('dir') not in (1, -1):
                errors.append('%s: %s.dir must be +1 or -1' % (rid, side))
        if ex.get('axis') != en.get('axis'):
            errors.append('%s: exit/entry axis differ (%s vs %s) — fix the plan, not the ease' % (rid, ex.get('axis'), en.get('axis')))
        elif ex.get('dir') != en.get('dir'):
            errors.append('%s: exit/entry direction mirrored on %s — fix the plan, not the ease' % (rid, ex.get('axis')))
        tech = r.get('technique')
        if tech:
            techs.add(tech)
        if tech == 'inverse zoom-through' and not (en.get('axis') == 'z' and en.get('dir') == -1):
            errors.append('%s: inverse zoom-through is z-1 (pull) by definition' % rid)
        if tech == 'zoom-through' and not (en.get('axis') == 'z' and en.get('dir') == 1):
            errors.append('%s: zoom-through is z+1 (push) by definition' % rid)
        key = '%s%s' % (en.get('axis'), '+1' if en.get('dir') == 1 else '-1')
        if key in RESERVED:
            spent.setdefault(r.get('act', 'film'), []).append('%s %s' % (rid, key))
        if prev and prev['entry'].get('axis') == en.get('axis') and prev['entry'].get('dir') == -en.get('dir', 0) and r.get('cause') not in CAUSES:
            errors.append('%s: ping-pong — reverses %s on %s without a cause (click | chapter | impact)' % (rid, prev.get('id', 'the previous seam'), en.get('axis')))
        prev = r
    if len(techs) > 3:
        warnings.append('transition budget: %d seam techniques (%s); a film repeats 2–3' % (len(techs), ', '.join(sorted(techs))))
    for act, v in spent.items():
        if len(v) > 1:
            warnings.append('act "%s" spends %d reserved vectors (%s); one per act' % (act, len(v), '; '.join(v)))
    return errors, warnings


def _norm_word(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


def load_timing(ctx):
    """P (phase starts/ends) + WORDS from the timeline or scenes/timing_<name>_data.js / vo/<name>_words.json."""
    P, WORDS = {}, {}
    tl = ctx.get('timeline') or {}
    for p in tl.get('phases', []):
        P[p['name']] = p['start']; P[p['name'] + '_end'] = p['start'] + p['dur']
    if ctx.get('words'):
        WORDS = ctx['words']
    else:
        name = (ctx.get('cfg') or {}).get('name', 'film')
        f = os.path.join(ctx.get('project', '.'), 'scenes', 'timing_%s_data.js' % name)
        if os.path.exists(f):
            src = open(f, encoding='utf-8').read()
            m = re.search(r'=\s*(\{.*\})\s*;?\s*$', src, re.S)
            if m:
                d = json.loads(m.group(1))
                WORDS = d.get('WORDS', {})
                if not P:
                    for p in d.get('PHASES', {}).get('phases', []):
                        P[p['name']] = p['start']; P[p['name'] + '_end'] = p['start'] + p['dur']
    return P, WORDS


def resolve_cut(expr, P, WORDS):
    """python twin of SEAM.resolveCut: numbers, P.<phase>, P.<phase>_end, wt('phase','word'[,n]), arithmetic."""
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr)

    def wt(m):
        ph, w, n = m.group(1), m.group(2), int(m.group(3) or 1)
        if ph not in P:
            raise ValueError('wt(%s, %s): unknown phase' % (ph, w))
        k = 0
        for x in WORDS.get(ph, []):
            if _norm_word(x['w']) == _norm_word(w):
                k += 1
                if k == n:
                    return repr(P[ph] + x['t'])
        raise ValueError('wt(%s, %s) does not resolve to a spoken word' % (ph, w))
    s = re.sub(r"wt\(\s*'([^']+)'\s*,\s*'([^']+)'\s*(?:,\s*(\d+))?\s*\)", wt, s)

    def ph(m):
        if m.group(1) not in P:
            raise ValueError('unknown phase P.%s' % m.group(1))
        return repr(P[m.group(1)])
    s = re.sub(r'\bP\.([A-Za-z0-9_]+)', ph, s)
    if re.search(r'\bFILM\.', s):
        raise ValueError('FILM.* cuts resolve only in the scene — use P./wt() in seams.json or export the ledger via export_timeline.js')
    if not re.fullmatch(r'[\d.\s+\-*/()eE]+', s):
        raise ValueError('unresolved tokens in cut "%s": %s' % (expr, s))
    return float(_arith(s))


def _arith(s):
    """evaluate + - * / and parentheses over numbers via the AST (no names, no calls, no eval)."""
    import ast, operator as op
    OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.USub: op.neg, ast.UAdd: op.pos}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.operand))
        raise ValueError('bad token in cut expression: %s' % ast.dump(n))
    return ev(ast.parse(s.strip(), mode='eval'))


def load_rows(ctx):
    """ledger rows with numeric cuts: timeline.json "seams" first, then <project>/seams.json. Returns
    (rows, source, errors)."""
    tl = ctx.get('timeline') or {}
    if tl.get('seams'):
        rows = tl['seams']
        return [dict(r, type=r.get('type', 'cut')) for r in rows], 'out/timeline.json', []
    path = os.path.join(ctx.get('project', '.'), (ctx.get('qa') or {}).get('seams', 'seams.json'))
    if not os.path.exists(path):
        return [], None, []
    led = json.load(open(path, encoding='utf-8'))
    rows = led.get('seams', led if isinstance(led, list) else [])
    P, WORDS = load_timing(ctx)
    out, errors = [], []
    for i, r in enumerate(rows):
        r = dict(r)
        r.setdefault('type', 'cut'); r.setdefault('id', 'seam %d' % (i + 1))
        if r['type'] == 'cut':
            r.setdefault('technique', 'cut-the-curve')
        try:
            r['cut'] = round(resolve_cut(r.get('cut'), P, WORDS), 3)
        except Exception as e:
            errors.append('%s: %s' % (r['id'], e))
        out.append(r)
    return out, os.path.relpath(path, ctx.get('project', '.')), errors


# ------------------------------------------------------------------------------------------ static lints
def stage_ground(html):
    """True when html, body or #stage carries an opaque background declaration in a <style> block."""
    css = ' '.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S | re.I)) or html
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        names = [s.strip() for s in sel.split(',')]
        if not any(n in ('html', 'body', '#stage') for n in names):
            continue
        for m in re.finditer(r'background(?:-color)?\s*:\s*([^;]+)', body, re.I):
            v = m.group(1).strip().lower()
            if v in ('transparent', 'none', 'inherit', 'initial', 'unset'):
                continue
            if re.match(r'rgba\([^)]*,\s*0(\.0+)?\s*\)', v) or re.match(r'hsla\([^)]*,\s*0(\.0+)?\s*\)', v):
                continue
            return True
    return False


def wobble_sites(src):
    """lines where Math.sin/cos(...t...) feeds a transform/left/top, outside data-diegetic / 'diegetic' marks."""
    hits = []
    for n, line in enumerate(src.splitlines(), 1):
        if 'diegetic' in line:
            continue
        if re.search(r'Math\.(sin|cos)\([^)]*\bt\b', line) and re.search(r'transform|\.left\b|\.top\b|translate|scale\(', line):
            hits.append(n)
    return hits


# ------------------------------------------------------------------------------------------ the gate
def run(ctx):
    film, fps, dur = ctx['film'], int(ctx.get('fps', 30)), float(ctx.get('dur', 0))
    res = []
    rows, source, rerr = load_rows(ctx)
    edge = float((ctx.get('qa') or {}).get('seam_edges', 1.0))      # head fade / tail credit are excluded like the other cut gates
    inside = lambda c: edge < c < dur - edge
    if not rows and not rerr:
        res.append(('seam ledger', True, 'no seams.json — ledger optional (write one: templates/seams.example.json)'))
        res.append(('seams move', True, 'no ledger rows to measure'))
    else:
        errors, warnings = validate_rows(rows)
        errors = rerr + errors
        outside = [r['id'] for r in rows if isinstance(r.get('cut'), (int, float)) and not inside(r['cut'])]
        det = '%d rows from %s' % (len(rows), source)
        if outside:
            warnings.append('rows outside %g s..dur-%g s skipped: %s' % (edge, edge, outside))
        if warnings:
            det += '  WARN ' + ' | '.join(warnings)
        res.append(('seam ledger', not errors, ('; '.join(errors)[:300] if errors else det)))
        bad, warn, n = [], [], 0
        for r in rows:
            if not isinstance(r.get('cut'), (int, float)) or not inside(r['cut']):
                continue
            n += 1
            ok, w, lines = check_seam(film, r, fps, dur)
            if not ok:
                bad.extend(l for l in lines if 'FAIL' in l)
            if w:
                warn.extend(l for l in lines if 'WARN' in l)
        det = ('%d seams move across the cut' % n) + ('  WARN ' + ' | '.join(warn)[:200] if warn else '')
        res.append(('seams move', not bad, ' | '.join(bad)[:400] if bad else det))
    cuts = sorted(set([c for c in (ctx.get('timeline') or {}).get('cuts', []) if inside(c)] + [r['cut'] for r in rows if isinstance(r.get('cut'), (int, float)) and inside(r['cut'])]))
    flashes = []
    for c in cuts:
        for k, m, a, b in check_flash(film, c, fps):
            flashes.append('t %.3f frame %d luma %.0f (neighbours %.0f/%.0f)' % (k / fps, k, m, a, b))
    res.append(('seam flash', not flashes, ' | '.join(flashes)[:300] if flashes else 'no luma spike within ±2 frames of %d cuts' % len(cuts)))
    html_path = ctx.get('scene_html')
    if html_path and os.path.exists(html_path):
        html = open(html_path, encoding='utf-8').read()
        res.append(('stage ground', stage_ground(html), 'opaque background on html/body/#stage' if stage_ground(html) else 'no opaque background on html, body or #stage in %s' % os.path.basename(html_path)))
    else:
        res.append(('stage ground', True, 'no scene html to lint (skipped)' if not html_path else 'scene html not found, skipped: %s' % html_path))
    sites = []
    for f in (ctx.get('qa') or {}).get('authored', ['scenes/film.html', 'scenes/shots.js']):
        p = os.path.join(ctx.get('project', '.'), f)
        if os.path.exists(p):
            sites.extend('%s:%d' % (f, n) for n in wobble_sites(open(p, encoding='utf-8').read()))
    res.append(('idle wobble', True, ('WARN sine/cosine of t drives a transform at %s — name a route instead (motion-doctrine.md)' % ', '.join(sites[:4])) if sites else 'no idle loops in authored scenes'))
    return res


# ------------------------------------------------------------------------------------------ standalone
def probe(film, t, fps=30):
    """print the measured vectors around t so a ledger row can be written from measurement."""
    kc = cut_frame(t, fps)
    fr = decode(film, kc - 4, 9, fps)
    F = lambda k: fr[k - (kc - 4)]
    print('probe %s @ %.3f s (frame %d)' % (os.path.basename(film), t, kc))
    for side, (ka, kb) in (('exit  (kc-3 .. kc-1)', (kc - 3, kc - 1)), ('entry (kc+1 .. kc+3)', (kc + 1, kc + 3))):
        for axis in ('x', 'y', 'z'):
            m = measure(F(ka), F(kb), 2.0 / fps, axis)
            print('  %s %s %+9.3g %s  %s%s' % (side, axis, m['v'], m['unit'], m['detail'], '' if not is_static(m, axis) else '  (static)'))
    fm, f0, fp = F(kc - 1), F(kc), F(kc + 1)
    a, b, r2, corr = blend_fit(fm, f0, fp)
    print('  cut frame = %.2f x (kc-1) + %.2f x (kc+1)  fit %.2f  sides corr %.2f  cross mad %.1f%s' % (a, b, r2, corr, mad(fm, fp), '  BLEND' if a > BLEND_MIN_COEF and b > BLEND_MIN_COEF and r2 > BLEND_MIN_R2 else ''))
    print('  luma kc-2..kc+2: %s' % [round(float(F(k).mean()), 1) for k in range(kc - 2, kc + 3)])
    print('ledger row: axis = the row above with the largest non-static |v| on both sides; dir = its sign')


def selftest():
    """synthetic 640x360 film (no scene render): five cuts with known behaviour, then every check."""
    import tempfile
    from PIL import Image, ImageDraw
    fps, out = 30, []
    tmp = tempfile.mkdtemp(prefix='seam_gate_')
    film = os.path.join(tmp, 'synthetic.mp4')
    S = __import__('seam_gate') if __name__ != '__main__' else sys.modules[__name__]
    # eases (same as lib/seams.js)
    EP4I = lambda x: x ** 4; EP4O = lambda x: 1 - (1 - x) ** 4; EP3I = lambda x: x ** 3; EXPO_O = lambda x: 1 if x >= 1 else 1 - 2 ** (-10 * x)
    rmp = lambda t, a, b: max(0.0, min(1.0, (t - a) / (b - a)))
    TR = 0.12 * 640

    def card(draw, x, y, s, op, tone):
        """a textured card (bars + boxes) centred at (320+x, 180+y), scaled s, drawn with opacity op."""
        cx, cy, w, h = 320 + x, 180 + y, 300 * s, 150 * s
        col = int(tone * op + 20 * (1 - op))
        draw.rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=col)
        for i in range(6):
            yy = cy - h / 2 + (i + 0.5) * h / 6
            draw.rectangle([cx - w / 2 + 12 * s, yy - 4 * s, cx - w / 2 + (60 + 37 * (i % 3)) * s, yy + 4 * s], fill=int(30 * op + 20 * (1 - op)))
            draw.rectangle([cx + w / 2 - (90 - 20 * (i % 2)) * s, yy - 5 * s, cx + w / 2 - 12 * s, yy + 5 * s], fill=int((200 if i % 2 else 90) * op + 20 * (1 - op)))

    C1, C2, C3, C4, C5, END = 1.0, 2.0, 3.0, 3.6, 4.4, 5.2
    N = int(END * fps)
    frames = []
    for k in range(N):
        t = k / fps
        im = Image.new('L', (640, 360), 20)
        d = ImageDraw.Draw(im)
        if t < C1:                                       # A → cut-the-curve LEFT → B
            u = rmp(t, C1 - 0.34, C1); card(d, -TR * EP4I(u), 0, 1, 1 - EP3I(u), 200)
        elif t < C2:
            u = rmp(t, C1, C1 + 0.42); card(d, TR * (1 - EP4O(u)), 0, 1, 0.35 + 0.65 * EP4O(u), 170)   # B settles and then SITS
        elif t < C4:                                     # settled hard cut B → C (dead beat); C sits, then a 7-frame DISSOLVE straddles C3 into D
            u = rmp(t, C3 - 3.5 / fps, C3 + 3.5 / fps)
            card(d, 0, 0, 1, 1, 120)
            if u > 0:
                im2 = Image.new('L', (640, 360), 20); d2 = ImageDraw.Draw(im2); card(d2, 0, 40, 1, 1, 230)
                im = Image.blend(im, im2, u); d = ImageDraw.Draw(im)
        elif t < C5:                                     # hard cut to E with a WHITE flash on the cut frame, then zoom-through push
            if k == cut_frame(C4, fps):
                im = Image.new('L', (640, 360), 250); d = ImageDraw.Draw(im)
            else:
                u = rmp(t, C5 - 0.2, C5); card(d, 0, -30, 1 + 0.2 * EP3I(u), 1 - 0.85 * u, 160)
        else:
            u = rmp(t, C5, C5 + 0.5); card(d, 0, -30, 0.75 + 0.25 * EXPO_O(u), 0.15 + 0.85 * EXPO_O(u), 210)
        d = ImageDraw.Draw(im)
        d.rectangle([k * 4, 0, k * 4 + 3, 3], fill=255)                                  # frame-index strip (alignment test)
        frames.append(np.asarray(im))
    p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '640x360', '-r', str(fps), '-i', '-',
                          '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', '-g', '30', film], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()
    fails = 0

    def check(name, cond, detail=''):
        nonlocal fails
        print('  %s %s  %s' % ('PASS' if cond else 'FAIL', name, detail))
        if not cond:
            fails += 1
    print('selftest  synthetic film %s (%d frames)' % (film, N))
    # 1 frame alignment: decoded frame k carries index k in its strip
    kc = cut_frame(C1, fps)
    fr = decode(film, kc - 4, 9, fps)
    idx = [int(np.argmax(f[1, :] > 128)) // 4 for f in fr]
    check('decode() frame alignment', idx == list(range(kc - 4, kc + 5)), str(idx))
    # 2 phase correlation sign convention
    a = frames[5].astype(np.uint8); b = np.roll(a, -7, axis=1)
    dx, dy, resp = shift(a, b)
    check('shift() sign: content moved left 7 px → dx ≈ -7', abs(dx + 7) < 0.3 and abs(dy) < 0.3, 'dx %.2f dy %.2f resp %.2f' % (dx, dy, resp))
    kz = cut_frame(C5, fps)
    s = scale_change(frames[kz + 1], frames[kz + 3])
    check('scale_change() detects growth (entry 0.75 -> 1 on expo.out)', 1.03 < s < 1.12, 's %.3f' % s)
    rowx = lambda c, tech='cut-the-curve': {'id': 'x@%g' % c, 'cut': c, 'type': 'cut', 'technique': tech, 'exit': {'axis': 'x', 'dir': -1}, 'entry': {'axis': 'x', 'dir': -1}}
    ok, w, lines = check_seam(film, rowx(C1), fps)
    check('good cut-the-curve LEFT passes', ok, ' / '.join(lines))
    ok, w, lines = check_seam(film, dict(rowx(C1), entry={'axis': 'x', 'dir': 1}, exit={'axis': 'x', 'dir': 1}), fps)
    check('same seam declared RIGHT fails on direction', not ok and any('moves x-' in l for l in lines), lines[0] if lines else '')
    ok, w, lines = check_seam(film, rowx(C2), fps)
    check('settled card → hard cut → static entry fails (dead beat)', not ok and sum('static' in l for l in lines) == 2, ' / '.join(l for l in lines if 'FAIL' in l))
    ok, w, lines = check_seam(film, {'id': 'dissolve', 'cut': C3, 'type': 'cut', 'technique': 'cut-the-curve', 'exit': {'axis': 'y', 'dir': 1}, 'entry': {'axis': 'y', 'dir': 1}}, fps)
    check('5-frame dissolve fails as a blend', not ok and any('blend' in l for l in lines), ' / '.join(l for l in lines if 'blend' in l))
    fl = check_flash(film, C4, fps)
    check('white frame on the cut is caught', len(fl) == 1 and fl[0][0] == cut_frame(C4, fps), str(fl))
    check('no flash reported on the good seam', check_flash(film, C1, fps) == [], '')
    ok, w, lines = check_seam(film, {'id': 'push', 'cut': C5, 'type': 'cut', 'technique': 'zoom-through', 'exit': {'axis': 'z', 'dir': 1}, 'entry': {'axis': 'z', 'dir': 1}}, fps)
    check('zoom-through push passes on z+', ok, ' / '.join(lines))
    ok, w, lines = check_seam(film, {'id': 'pull?', 'cut': C5, 'type': 'cut', 'technique': 'inverse zoom-through', 'exit': {'axis': 'z', 'dir': -1}, 'entry': {'axis': 'z', 'dir': -1}}, fps)
    check('same seam declared as a pull fails on the z sign', not ok, ' / '.join(l for l in lines if 'FAIL' in l))
    ok, w, lines = check_seam(film, {'id': 'mc', 'cut': C1, 'type': 'match-cut', 'carrier': {'out': '#a', 'in': '#b'}}, fps)
    check('match-cut rows: overlap only', ok and 'overlap only' in lines[-1], lines[-1])
    # ledger lint
    e, wn = validate_rows([rowx(5), dict(rowx(9), id='pp', exit={'axis': 'x', 'dir': 1}, entry={'axis': 'x', 'dir': 1})])
    check('ping-pong is an error', any('ping-pong' in x for x in e), e[0] if e else '')
    e, wn = validate_rows([rowx(5), dict(rowx(9), id='pp', cause='click', exit={'axis': 'x', 'dir': 1}, entry={'axis': 'x', 'dir': 1})])
    check('ping-pong with a click passes', not e, str(e))
    e, wn = validate_rows([dict(rowx(5), exit={'axis': 'y', 'dir': -1})])
    check('axis mismatch is an error', any('axis differ' in x for x in e))
    e, wn = validate_rows([dict(rowx(5), exit={'axis': 'x', 'dir': 1})])
    check('mirrored direction is an error', any('mirrored' in x for x in e))
    e, wn = validate_rows([dict(rowx(5, 'inverse zoom-through'), exit={'axis': 'z', 'dir': -1}, entry={'axis': 'z', 'dir': -1}), dict(rowx(9), id='up', exit={'axis': 'y', 'dir': -1}, entry={'axis': 'y', 'dir': -1})])
    check('two reserved vectors in one act warn', any('reserved' in x for x in wn), wn[0] if wn else '')
    e, wn = validate_rows([dict(rowx(5 + 4 * i, tq), id='t%d' % i, cause='chapter') for i, tq in enumerate(['cut-the-curve', 'rack-focus', 'combined', 'waterfall'])])
    check('> 3 techniques warn', any('budget' in x for x in wn), wn[0] if wn else '')
    # cue resolver
    P, WD = {'ask': 18.622, 'ask_end': 22.774, 'close': 27.93}, {'ask': [{'t': 0.5, 'w': 'the'}, {'t': 1.2, 'w': 'question'}]}
    check('resolve_cut wt()/P./arith', abs(resolve_cut("wt('ask','question') + 0.1", P, WD) - 19.922) < 1e-9 and resolve_cut('P.close', P, WD) == 27.93 and resolve_cut(3, P, WD) == 3.0)
    bad = 0
    for ex in ("wt('ask','banana')", 'P.nope', '__import__("os")', 'FILM.openEnd'):
        try:
            resolve_cut(ex, P, WD)
        except Exception:
            bad += 1
    check('resolve_cut rejects bad cues / code', bad == 4, '%d of 4 rejected' % bad)
    # static lints
    check('stage ground: html,body{background:#082A34}', stage_ground('<style>html,body{margin:0;background:#082A34}</style>'))
    check('stage ground: gradient on #stage', stage_ground('<style>#stage{background:linear-gradient(180deg,#082A34,#204A56)}</style>'))
    check('stage ground: transparent root fails', not stage_ground('<style>html,body{background:transparent} #stage{color:#fff}</style>'))
    check('stage ground: rgba(..,0) fails', not stage_ground('<style>body{background:rgba(0,0,0,0)}</style>'))
    check('wobble: glow on a sine of t', wobble_sites("g.top = (-260 + 60 * Math.sin(t * 0.35)).toFixed(1) + 'px';") == [1])
    check('wobble: diegetic spinner exempt', wobble_sites("/* diegetic */ sp.style.transform = 'rotate(' + Math.sin(t) + 'rad)';") == [])
    check('wobble: sine not on t is not flagged', wobble_sites("x.style.left = Math.sin(phase) + 'px';") == [])
    print('\n%s  (%d failed)' % ('SELFTEST PASS' if not fails else 'SELFTEST FAILED', fails))
    return fails


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if not a or a[0] == '--selftest':
        sys.exit(1 if selftest() else 0)
    if a[0] == 'probe' and len(a) >= 3:
        probe(a[1], float(a[2]), int(a[3]) if len(a) > 3 else 30); sys.exit(0)
    if a[0] == 'verify' and len(a) >= 3:
        edges = 1.0
        if '--edges' in a:
            i = a.index('--edges'); edges = float(a[i + 1]); del a[i:i + 2]
        film, ledger, fps = a[1], a[2], int(a[3]) if len(a) > 3 else 30
        info = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', film], capture_output=True, text=True).stdout
        d = json.load(open(ledger, encoding='utf-8'))
        proj = os.path.dirname(os.path.abspath(ledger))
        tl = d if 'cuts' in d else {'cuts': [], 'phases': []}
        qa = {'seam_edges': edges}
        if 'cuts' not in d:
            qa['seams'] = os.path.basename(ledger)
        ctx = {'film': film, 'fps': fps, 'dur': float(info.strip() or 0), 'timeline': tl, 'project': proj, 'cfg': {}, 'qa': qa,
               'scene_html': os.path.join(proj, 'scenes', 'film.html')}
        if 'cuts' in d and os.path.basename(proj) == 'out':
            ctx['project'] = os.path.dirname(proj); ctx['scene_html'] = os.path.join(ctx['project'], 'scenes', 'film.html')
        bad = 0
        for name, ok, detail in run(ctx):
            print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', detail)); bad += 0 if ok else 1
        sys.exit(1 if bad else 0)
    print(__doc__)
