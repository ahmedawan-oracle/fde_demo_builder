# -*- coding: utf-8 -*-
"""motion_diag.py — camera gates on the rendered film: did the camera do what the shots say, is every zoom
within the source-resolution budget, do real-motion clips step cleanly, and an onion-skin sheet per shot.

Plug-in for qa_film.py (see PORT_CONTRACT: GATE_NAMES + run(ctx)). Inputs:
    out/camera_curves.json, out/camera_report.json   written by `node scenes/lib/camera.js --curves ...`
                                                     (rebuilt here when missing or older than scenes/shots.js)
    the film itself, decoded ONCE at 10 fps / 320x180 grey (numpy), plus one short colour decode per shot

Gates (names <= 18 chars):
    motion traced   per 0.1 s interval inside every shot: measured pixel change (mean |diff| / 255, %) vs the
                    scripted camera speed (px/frame, from the curves) and the shot's scheduled motion windows
                    (scroll / seq / reveal / stream / highlight / seam / focus / lower-third):
                      FAIL  a scripted camera move (> 1 px/frame) changes < 30 % of what that move should change on the
                            frame's own content (frame k warped by the scripted scale/shift; only judged when the
                            expected change is >= 0.3 %) -> the camera did nothing
                      FAIL  > 4 % change with no camera, no scheduled motion and no cut within 0.15 s -> unscripted motion
                      (scheduled = the shot's own windows, qa.json motion.allow, every seam window in out/timeline.json
                      and every shader seam window [at, at + dur] from its glSeams)
                      WARN  a velocity discontinuity in the scripted curve (> 3x its neighbours) not at a cut
                    Also recovers the camera from the pixels (Fourier-Mellin scale + phase-correlation shift
                    between consecutive frames) and writes out/qa/camera_measured.json for the editor.
    zoom budget     the effective upsample of the recording per shot (camera scale x 1920 / source px that span
                    the stage): FAIL above qa.json zoom_max (2.0), WARN above zoom_warn (1.6); FAIL when a
                    pushToFit target exceeds 88 % of the stage.
    seq quantized   every real-motion (seq) clip: the output frames each source frame is shown for must follow
                    the rate exactly (rate 1 -> one output frame per source frame, never 0 or 2) — the stutter a
                    seconds-domain floor produces; plus a pixel read of frozen frames inside the window (detail).
    onion sheets    out/qa/motion_<shot>.png: 9 ghosts (alpha 0.14 -> 1.0, oldest faintest) blended over the
                    shot plus a filmstrip and the scripted camera path in miniature. Open it first when a push
                    "does not feel right": even ghost spacing = constant speed, clustered = settle, gaps = fast.

qa.json keys (all optional):
    "zoom_max": 2.0, "zoom_warn": 1.6,
    "motion": {"fps": 10, "min_change": 0.3, "max_unscripted": 4.0, "disc_ratio": 3.0, "cam_min": 1.0,
               "cut_pad": 0.15, "noise": 0.25, "samples": 9, "allow": [[t0, t1], ...]}

Scans (v5.1) — the failures a frame-by-frame eye catches and a mean does not:
    --spikes <film>                   isolated frame-difference outliers: one 0.1 s step whose change is > 4x both of its
                                      neighbours and > 2 % (a single-frame jump, a dropped or doubled frame, a glitch) away from
                                      any cut; reported as WARN inside `motion traced` and listed by this flag
    --pan-halves <film> [t0 t1]       the camera recovered on the LEFT and the RIGHT half of the frame separately: a real pan or
                                      push moves both halves the same way; a disagreement (> 1.5 px shift or > 0.01 scale with one
                                      half moving) is a partial pan — one element moved, not the camera
    --roster <start.jpg> <end.jpg>    OCR the two stills (the leak gate's engine) and compare their named entities (Title-case
                                      words): who arrived, who left — the people-roster mismatch start → end

Self-test (synthetic frames, no ffmpeg, < 10 s):   python gates/motion_diag.py --selftest
"""
import json, math, os, subprocess, sys, time

import numpy as np

GATE_NAMES = ['motion traced', 'zoom budget', 'seq quantized', 'onion sheets']

DEFAULTS = {
    'fps': 10,                # analysis rate for the film decode
    'res': (320, 180),        # analysis resolution (mean |diff| is resolution-robust; speed thresholds are in stage px)
    'min_change': 0.3,        # % change a scripted camera move must produce on a textured frame
    'max_unscripted': 4.0,    # % change that is suspicious with nothing scripted
    'disc_ratio': 3.0,        # velocity discontinuity: speed > ratio x max(neighbours)
    'cam_min': 1.0,           # px/frame below which the camera counts as still
    'dead_ratio': 0.3,        # measured change below this share of the change the scripted move should produce = dead camera
    'cut_pad': 0.15,          # s around a cut / shot boundary where change is expected
    'noise': 0.25,            # mean |diff| (grey levels) of multi-worker render noise at chunk boundaries
    'samples': 9,             # onion ghosts per shot (max 60)
    'zoom_max': 2.0, 'zoom_warn': 1.6, 'headroom': 0.88,
}


# ---------------------------------------------------------------- helpers
def _cfg(qa):
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (qa.get('motion') or {}).items()})
    if 'zoom_max' in qa:
        c['zoom_max'] = float(qa['zoom_max'])
    if 'zoom_warn' in qa:
        c['zoom_warn'] = float(qa['zoom_warn'])
    c['samples'] = max(1, min(60, int(c['samples'])))
    return c


def _curves(ctx):
    """Load out/camera_curves.json + out/camera_report.json, rebuilding them with node when missing or stale.
    Returns (curves, report, note). note is a SKIP reason when the project has no scenes/lib/camera.js."""
    P = ctx['project']
    cam_js = os.path.join(P, 'scenes', 'lib', 'camera.js')
    cur_p, rep_p = os.path.join(P, 'out', 'camera_curves.json'), os.path.join(P, 'out', 'camera_report.json')
    shots = ctx.get('shots_js') or os.path.join(P, 'scenes', 'shots.js')
    name = ctx['cfg'].get('name', 'film')
    timing = os.path.join(P, 'scenes', 'timing_%s_data.js' % name)
    clips = os.path.join(P, 'broll', 'clips.js')
    deps = [f for f in (shots, timing, cam_js) if os.path.exists(f)]
    fresh = all(os.path.exists(p) for p in (cur_p, rep_p)) and deps and \
        min(os.path.getmtime(p) for p in (cur_p, rep_p)) >= max(os.path.getmtime(f) for f in deps)
    if not fresh:
        if not os.path.exists(cam_js):
            return None, None, 'SKIP: scenes/lib/camera.js not in this project (copy lib/camera.js; node scenes/lib/camera.js --curves ...)'
        if not os.path.exists(timing) or not os.path.exists(shots):
            return None, None, 'SKIP: missing %s' % ('scenes/shots.js' if not os.path.exists(shots) else os.path.relpath(timing, P))
        r = subprocess.run(['node', cam_js, '--curves', timing, shots, clips, '--out', os.path.join(P, 'out')],
                           cwd=P, capture_output=True, text=True)
        if not (os.path.exists(cur_p) and os.path.exists(rep_p)):
            raise RuntimeError('camera.js --curves failed: ' + (r.stderr or r.stdout)[-200:])
    return json.load(open(cur_p, encoding='utf-8')), json.load(open(rep_p, encoding='utf-8')), None


def decode_gray(film, fps, res, t0=None, dur=None):
    """Decode the film (or a window of it) to a (N, H, W) uint8 grey array via one ffmpeg pass."""
    w, h = res
    cmd = ['ffmpeg', '-nostdin', '-v', 'error']
    if t0 is not None:
        cmd += ['-ss', '%.3f' % t0]
    cmd += ['-i', film]
    if dur is not None:
        cmd += ['-t', '%.3f' % dur]
    cmd += ['-vf', 'fps=%s,scale=%d:%d:flags=area,format=gray' % (fps, w, h), '-f', 'rawvideo', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h)
    return np.frombuffer(raw[:n * w * h], dtype=np.uint8).reshape(n, h, w)


def decode_rgb_at(film, times, t0, size=(640, 360), fps=30):
    """Colour frames at absolute times `times` (one ffmpeg pass over [t0, max(times)]); returns list of (H, W, 3).
    After an input seek the frame clock restarts near 0 with a sub-frame offset, so each pick is a one-frame-wide window."""
    if not times:
        return []
    w, h = size
    dur = max(times) - t0 + 0.2
    sel = '+'.join('between(t,%.4f,%.4f)' % (t - t0 - 0.5 / fps, t - t0 + 0.5 / fps - 1e-4) for t in times)
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t0, '-i', film, '-t', '%.3f' % dur,
           '-vf', "select='%s',scale=%d:%d:flags=area" % (sel, w, h), '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    fr = np.frombuffer(raw[:n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)
    return [fr[i] for i in range(min(n, len(times)))]


def change_pct(a, b):
    """Mean absolute difference between two grey frames as a percentage of full scale."""
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16)))) / 255.0 * 100.0


def ghost_alphas(n, lo=0.14):
    """Onion-skin alphas: linear ramp lo -> 1.0, oldest first (n = 1 -> [1.0])."""
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    return [round(lo + (1.0 - lo) * i / (n - 1), 3) for i in range(n)]


def in_windows(a, b, W, pad=0.0):
    """True when [a, b] overlaps any window [w0, w1] (grown by pad)."""
    return any(a <= w1 + pad and b >= w0 - pad for w0, w1 in W)


# ---------------------------------------------------------------- camera recovery from pixels (diagnostic)
def _phase_corr(a, b):
    """Integer+parabolic peak of the phase correlation of two equal-shape float arrays -> (dy, dx) shift of b vs a."""
    F = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
    F /= np.abs(F) + 1e-6
    r = np.real(np.fft.ifft2(F))
    iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape

    def sub(v, i, n):
        m, p, q = v[(i - 1) % n], v[i], v[(i + 1) % n]
        d = (m - 2 * p + q)
        return i + (0.5 * (m - q) / d if abs(d) > 1e-9 else 0.0)
    fy, fx = sub(r[:, ix], iy, h), sub(r[iy, :], ix, w)
    if fy > h / 2:
        fy -= h
    if fx > w / 2:
        fx -= w
    return fy, fx, float(r[iy, ix])


def _logpolar(mag, nr=192, nt=96):
    h, w = mag.shape
    cy, cx, R = h / 2.0, w / 2.0, min(h, w) / 2.0 - 1
    r = np.exp(np.linspace(0.0, math.log(R), nr))
    th = np.linspace(0.0, math.pi, nt, endpoint=False)
    X = np.clip(np.round(cx + r[None, :] * np.cos(th[:, None])).astype(int), 0, w - 1)
    Y = np.clip(np.round(cy + r[None, :] * np.sin(th[:, None])).astype(int), 0, h - 1)
    return mag[Y, X], math.log(R) / nr


def estimate_motion(a, b):
    """Recover (scale, dx, dy) of grey frame b relative to a: Fourier-Mellin on the spectra magnitudes gives the
    scale (rotation assumed 0 — a camera over a flat screen), then phase correlation on b un-scaled gives the shift.
    scale > 1 = b is a zoomed-in version of a (a push); dx, dy in pixels of the analysis frame."""
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    A = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2((a - a.mean()) * win))))
    B = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2((b - b.mean()) * win))))
    LA, step = _logpolar(A)
    LB, _ = _logpolar(B)
    _, kx, _ = _phase_corr(LA, LB)
    scale = math.exp(kx * step)          # spectrum of a zoomed-in image shrinks -> log-r shift
    scale = max(0.5, min(2.0, scale))
    if abs(scale - 1.0) > 0.002:         # undo the zoom on b, then measure the pure shift
        from PIL import Image
        im = Image.fromarray(b.astype(np.uint8)).resize((max(2, int(round(w / scale))), max(2, int(round(h / scale)))), Image.BILINEAR)
        bb = np.asarray(im, dtype=np.float32)
        out = np.full((h, w), b.mean(), np.float32)
        y0, x0 = (h - bb.shape[0]) // 2, (w - bb.shape[1]) // 2
        if y0 >= 0 and x0 >= 0:
            out[y0:y0 + bb.shape[0], x0:x0 + bb.shape[1]] = bb
        else:
            out = bb[-y0:-y0 + h, -x0:-x0 + w]
        b = out
    dy, dx, pk = _phase_corr(a * win, b * win)
    return scale, -dx, -dy, pk          # phase_corr reports where a sits in b; we want b's motion


# ---------------------------------------------------------------- scans (v5.1)
def spikes(frames, fps, cuts=(), thr=2.0, ratio=4.0, cut_pad=0.15):
    """[(t, pct, before, after)] single-frame jumps: frame k+1 differs from both neighbours by > thr while frames k and k+2 are
    nearly the same picture (their difference < pct / ratio) — the picture jumped and came back. Plus the plain isolated
    outlier (one step > ratio x both of its neighbours) for a dropped or doubled frame. Steps touching a cut are skipped."""
    ch = [change_pct(frames[k], frames[k + 1]) for k in range(len(frames) - 1)]
    out = []
    for k in range(1, len(ch) - 1):
        a, b = k / fps, (k + 1) / fps
        if any(abs(c - a) < cut_pad or abs(c - b) < cut_pad for c in cuts):
            continue
        back = change_pct(frames[k], frames[k + 2])
        if ch[k] > thr and ch[k + 1] > thr and back < max(0.5, ch[k] / ratio):
            out.append((round(b, 2), round(ch[k], 2), round(ch[k - 1], 2), round(ch[k + 1], 2))); continue
        nb = max(ch[k - 1], ch[k + 1])
        if ch[k] > thr and ch[k] > ratio * nb + 0.2:
            out.append((round(a, 2), round(ch[k], 2), round(ch[k - 1], 2), round(ch[k + 1], 2)))
    return out


def pan_halves(a, b, shift_tol=1.5, scale_tol=0.01, still=0.3):
    """camera recovered on the left and the right half separately → {'left': (s, dx, dy), 'right': (...), 'disagree': bool}."""
    w = a.shape[1] // 2
    L = estimate_motion(a[:, :w], b[:, :w])[:3]
    R = estimate_motion(a[:, w:], b[:, w:])[:3]
    moving = max(abs(L[1]), abs(L[2]), abs(R[1]), abs(R[2])) > still or abs(L[0] - 1) > 0.003 or abs(R[0] - 1) > 0.003
    dis = moving and (abs(L[1] - R[1]) > shift_tol or abs(L[2] - R[2]) > shift_tol or abs(L[0] - R[0]) > scale_tol)
    return {'left': tuple(round(float(x), 3) for x in L), 'right': tuple(round(float(x), 3) for x in R), 'disagree': bool(dis)}


def pan_halves_film(film, t0, t1, fps=10, res=(320, 180)):
    """[(t, left, right, disagree)] over [t0, t1] at `fps`."""
    fr = decode_gray(film, fps, res, t0, max(0.2, t1 - t0))
    return [(round(t0 + k / fps, 2),) + tuple(pan_halves(fr[k], fr[k + 1])[x] for x in ('left', 'right', 'disagree')) for k in range(len(fr) - 1)]


def roster(start_path, end_path, backend='auto'):
    """named entities on two stills via the leak gate's OCR → {'start', 'end', 'new', 'gone', 'engine'} (or {'note'} without an engine)."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import leak_gate as LG, pair_gate as PG
    be, note = LG.pick_backend(backend, fastest=True)
    if be is None:
        return {'note': 'no OCR engine: ' + note[:80]}
    sw, ew = PG.ocr_words(be, start_path), PG.ocr_words(be, end_path)
    rs, re_ = PG.roster(sw), PG.roster(ew)
    return {'start': sorted(rs), 'end': sorted(re_), 'new': sorted(re_ - rs), 'gone': sorted(rs - re_), 'engine': be.name}


# ---------------------------------------------------------------- the gates
def gate_motion(ctx, cfg, curves, frames, report=None):
    fps, FPS = cfg['fps'], curves['fps']
    cuts = list(curves.get('cuts', [])) + [s['t0'] for s in curves['shots']] + [s['t1'] for s in curves['shots']]
    allow_global = list(curves.get('allow', [])) + [list(map(float, w)) for w in (cfg.get('allow') or [])]
    # seams declared in seams.json move both sides on purpose: their windows (out/timeline.json) are scheduled motion
    TLx = ctx.get('timeline') or {}
    for w in TLx.get('seams', []) or []:
        if isinstance(w, dict) and 't0' in w and 't1' in w:
            allow_global.append([float(w['t0']) - 0.05, float(w['t1']) + 0.05])
    # shader seams (type 'gl'): GL.cutTransition repaints the whole stage inside [at, at + dur] — scheduled like any seam
    for g in TLx.get('glSeams', []) or []:
        if isinstance(g, dict) and 'at' in g and 'dur' in g:
            allow_global.append([float(g['at']) - 0.05, float(g['at']) + float(g['dur']) + 0.05])
    dead, wild, disc, measured = [], [], [], []
    ladders = (report or {}).get('ladders', []) if report else []
    # optional masks: stage-px rects of recreated screen-space overlays (lower thirds, caption lane) ignored in both
    # the measured and the expected change
    kx, ky = cfg['res'][0] / 1280.0, cfg['res'][1] / 720.0
    masks = [(int(r[0] * kx), int(r[1] * ky), int(math.ceil((r[0] + r[2]) * kx)), int(math.ceil((r[1] + r[3]) * ky))) for r in (cfg.get('mask') or [])]

    def masked(f):
        if not masks:
            return f
        g = f.copy()
        for x0, y0, x1, y1 in masks:
            g[y0:y1, x0:x1] = 0
        return g
    for si, sh in enumerate(curves['shots']):
        W = [tuple(w) for ws in sh['windows'].values() for w in ws] + [tuple(w) for w in allow_global]
        spd = sh['speed']
        tt = [s['t'] for s in sh['samples']]
        k0, k1 = int(math.ceil(sh['t0'] * fps - 1e-6)), int(math.floor(sh['t1'] * fps + 1e-6)) - 1
        rows, exps = [], {}
        for k in range(max(0, k0), min(k1, len(frames) - 2)):
            a, b = k / fps, (k + 1) / fps
            # speed[j] is the picture travel arriving at sample j, i.e. over (t[j-1], t[j]]: take the samples inside (a, b]
            base = int(round(sh['t0'] * FPS))
            j0 = max(0, int(math.floor(a * FPS + 1e-6)) + 1 - base)
            j1 = min(len(spd), int(math.floor(b * FPS + 1e-6)) + 1 - base)
            cam = max(spd[j0:j1]) if j1 > j0 else 0.0
            fa, fb = masked(frames[k]), masked(frames[k + 1])
            ch = change_pct(fa, fb)
            near_cut = any(abs(c - a) < cfg['cut_pad'] or abs(c - b) < cfg['cut_pad'] for c in cuts)
            scheduled = in_windows(a, b, W, 0.05)
            # the change this camera move SHOULD produce on what is really in frame: warp frame k by the scripted
            # (scale ratio, centre shift) between a and b. A push over an empty white region honestly changes little.
            exp = 0.0
            if cam > cfg['cam_min'] and not near_cut:
                pa, pb = sh['samples'][min(len(spd) - 1, max(0, j0 - 1))], sh['samples'][min(len(spd) - 1, max(0, j1 - 1))]
                r = pb['s'] / max(1e-6, pa['s'])
                sx, sy = pb['s'] * (pa['cx'] - pb['cx']) * kx, pb['s'] * (pa['cy'] - pb['cy']) * kx
                # only where the warped frame is defined (a pull-out reveals border content frame k cannot predict)
                valid = _warp(np.full(frames[k].shape, 255, np.uint8), r, sx, sy) > 128
                if masks:
                    valid &= masked(np.full(frames[k].shape, 255, np.uint8)) > 128
                if valid.sum() > 0.2 * valid.size:
                    wk = _warp(frames[k], r, sx, sy)
                    exp = float(np.mean(np.abs(fa[valid].astype(np.int16) - wk[valid].astype(np.int16)))) / 255 * 100
                    chv = float(np.mean(np.abs(fa[valid].astype(np.int16) - fb[valid].astype(np.int16)))) / 255 * 100
                    exps[k] = (chv, exp)
            if cam <= cfg['cam_min'] and ch > cfg['max_unscripted'] and not scheduled and not near_cut:
                wild.append((sh['shot'], round(a, 2), round(ch, 1)))
            rows.append((a, cam, ch, scheduled, near_cut))
        # dead camera is judged per LEG (one scripted move): the measured change integrated over the move must reach
        # dead_ratio of the change the move should have produced on the frames' own content
        legs = ladders[si]['legs'] if si < len(ladders) else []
        leg_ratios = []
        for lg in legs:
            ks = [k for k in exps if lg['t0'] - 0.05 <= k / fps and (k + 1) / fps <= lg['t1'] + 0.05]
            if not ks:
                continue
            m, e = sum(exps[k][0] for k in ks), sum(exps[k][1] for k in ks)
            leg_ratios.append({'t0': lg['t0'], 't1': lg['t1'], 'verb': lg['verb'], 'measured_pct': round(m, 2), 'expected_pct': round(e, 2), 'ratio': round(m / e, 2) if e > 0 else None})
            if e / len(ks) >= cfg['min_change'] and m < cfg['dead_ratio'] * e:
                dead.append((sh['shot'], lg['t0'], lg['verb'], round(m, 2), round(e, 2)))
        # scripted velocity discontinuity (not at the shot's edges or a seam)
        for j in range(1, len(spd) - 1):
            nb = max(spd[j - 1], spd[j + 1])
            if spd[j] > 6 and spd[j] > cfg['disc_ratio'] * nb + 2.0 and tt[j] - sh['t0'] > 2.0 / FPS and sh['t1'] - tt[j] > 2.0 / FPS \
                    and not in_windows(tt[j], tt[j], [tuple(w) for w in sh['windows'].get('seam', [])], 0.05):
                disc.append((sh['shot'], round(tt[j], 2), round(spd[j], 1)))
        # camera recovered from the pixels (diagnostic: written, not gated)
        rec, s_cum = [], 1.0
        for (a, cam, ch, scheduled, near_cut) in rows:
            k = int(round(a * fps))
            if near_cut or k + 1 >= len(frames):
                rec.append({'t': round(a, 2), 'skip': True})
                continue
            sc, dx, dy, pk = estimate_motion(frames[k], frames[k + 1])
            s_cum *= sc
            rec.append({'t': round(a, 2), 'scale': round(sc, 4), 'dx': round(dx, 2), 'dy': round(dy, 2), 'peak': round(pk, 3),
                        's_cum': round(s_cum, 4), 'change_pct': round(ch, 3), 'cam_pxf': round(cam, 2), 'scheduled': scheduled})
        scripted_ds = [sh['samples'][min(len(sh['samples']) - 1, int(round((r['t'] + 1.0 / fps - sh['t0']) * FPS)))]['s']
                       - sh['samples'][max(0, int(round((r['t'] - sh['t0']) * FPS)))]['s'] for r in rec if not r.get('skip')]
        meas_ds = [r['scale'] - 1.0 for r in rec if not r.get('skip')]
        corr = None
        if len(meas_ds) > 3 and np.std(scripted_ds) > 1e-6 and np.std(meas_ds) > 1e-6:
            corr = round(float(np.corrcoef(scripted_ds, meas_ds)[0, 1]), 3)
        measured.append({'shot': sh['shot'], 't0': sh['t0'], 't1': sh['t1'], 'ds_corr': corr, 'legs': leg_ratios, 'intervals': rec})
    qa_dir = os.path.join(ctx['project'], 'out', 'qa')
    os.makedirs(qa_dir, exist_ok=True)
    json.dump({'fps': fps, 'res': list(cfg['res']), 'shots': measured}, open(os.path.join(qa_dir, 'camera_measured.json'), 'w', encoding='utf-8'), indent=1)
    ok = not dead and not wild
    corrs = [m['ds_corr'] for m in measured if m['ds_corr'] is not None]
    parts = []
    if dead:
        parts.append('camera did nothing (shot, leg t0, verb, measured %%, expected %%) %s' % dead[:3])
    if wild:
        parts.append('unscripted motion (shot, t, %%) %s' % wild[:3])
    if not parts:
        parts.append('%d shots traced' % len(measured))
    if disc:
        parts.append('WARN velocity jumps %s' % disc[:3])
    sp = spikes(frames, fps, cuts, cut_pad=cfg['cut_pad'])
    if sp:
        parts.append('WARN single-frame spikes (t, %%, before, after) %s' % sp[:3])
    if corrs:
        parts.append('pixel/script ds corr %.2f' % (sum(corrs) / len(corrs)))
    return ('motion traced', ok, '; '.join(parts))


def gate_budget(cfg, report):
    B = report.get('budget', [])
    fails = [(b['shot'], b['upsample']) for b in B if b['upsample'] > cfg['zoom_max'] + 1e-6]
    warns = [(b['shot'], b['upsample']) for b in B if cfg['zoom_warn'] < b['upsample'] <= cfg['zoom_max'] + 1e-6]
    head = [(b['shot'], b['headroomFails']) for b in B if b.get('headroomFails')]
    ok = not fails and not head
    peak = max(B, key=lambda b: b['upsample']) if B else None
    d = 'peak upsample %.2f (%s)' % (peak['upsample'], peak['shot']) if peak else 'no footage shots'
    if fails:
        d += ' FAIL > %.1f: %s' % (cfg['zoom_max'], fails[:3])
    if head:
        d += ' FAIL target > %d %% of the stage: %s' % (round(cfg['headroom'] * 100), head[:3])
    if warns:
        d += ' WARN > %.1f (soft text on a booth wall): %s' % (cfg['zoom_warn'], warns[:3])
    return ('zoom budget', ok, d)


def check_schedule(seq, rate, fps_src, FPS):
    """Output frames per source frame from a seq schedule (list of source indices per output frame).
    rate 1 -> every count must be 1; other rates allow floor/ceil of FPS / (fps_src * rate). Returns offenders."""
    if len(seq) < 3:
        return []
    counts, order = {}, []
    for f in seq:
        if f not in counts:
            order.append(f)
        counts[f] = counts.get(f, 0) + 1
    hold = FPS / float(fps_src * rate)
    allowed = {1} if abs(hold - 1.0) < 1e-6 else {int(math.floor(hold)), int(math.ceil(hold))}
    bad = []
    for f in order[1:-1]:                       # first = partial, last = held / loop
        if counts[f] not in allowed:
            bad.append((f, counts[f]))
    if hold >= 1:                               # a skipped source frame at rate <= 1 is a drop
        bad += [(f, 0) for f in range(order[0], order[-1]) if f not in counts and order[-1] - order[0] < 10000]
    return bad


def gate_seq(ctx, cfg, report, frames_fn):
    S = report.get('seqs', [])
    if not S:
        return ('seq quantized', True, 'no seq clips')
    bad, frozen = [], []
    for s in S:
        off = check_schedule(s['seq'], s['rate'], s['fps'], report['fps'])
        if off:
            bad.append((s['shot'], off[:4]))
        # pixel read: identical consecutive output frames inside the real-motion window (detail only)
        a, b = s['at'], min(s['t1'] if s.get('t1') else s['end'], s['end'])
        if b - a > 0.2:
            fr = frames_fn(a, b - a)
            if len(fr) > 2:
                d = [change_pct(fr[i], fr[i + 1]) * 2.55 for i in range(len(fr) - 2)]   # back to grey levels
                z = sum(1 for x in d if x < cfg['noise'])
                if z:
                    frozen.append((s['shot'], z, len(d)))
    ok = not bad
    d = ('stutter (shot, [(source frame, shown n)]) %s' % bad[:3]) if bad else '%d seq clip(s) step cleanly' % len(S)
    if frozen:
        d += '; identical output frames inside the motion window %s (shot, n, of)' % frozen[:3]
    # speed contrast (motion-doctrine.md): the playback rate of every real-motion shot, so the editor sees the film's speed
    # ladder at a glance — product footage reads best at 1.3–1.5x, people at ~0.8x, and a film with every clip at 1.0x has no
    # contrast. Reported, never failed; a rate outside 0.5–2.0 is a WARN (slower reads as a stall, faster as a glitch).
    rates = [(s['shot'], s['rate'] if isinstance(s.get('rate'), (int, float)) else 'lane') for s in S]
    wild = [(sh, r) for sh, r in rates if isinstance(r, (int, float)) and not (0.5 <= r <= 2.0)]
    d += '; playback rates %s' % ', '.join('%s %sx' % (sh, ('%.2f' % r) if isinstance(r, (int, float)) else r) for sh, r in rates[:6])
    if wild:
        d += '; WARN rate outside 0.5–2.0x %s' % wild[:3]
    nums = [r for _, r in rates if isinstance(r, (int, float))]
    if len(nums) >= 2 and max(nums) - min(nums) < 1e-6:
        d += '; WARN every clip at %.2fx — no speed contrast' % nums[0]
    return ('seq quantized', ok, d)


def _font(px):
    from PIL import ImageFont
    for n in ('arial.ttf', 'DejaVuSans.ttf', 'Arial.ttf'):
        for d in ('C:/Windows/Fonts/', '/usr/share/fonts/truetype/dejavu/', '/Library/Fonts/', '/System/Library/Fonts/'):
            try:
                return ImageFont.truetype(d + n, px)
            except OSError:
                pass
    return ImageFont.load_default()


def compose_sheet(rgb_frames, times, header, path_pts, stage=(1280, 720), extra=''):
    """Ghost blend (weights 0.14 -> 1.0) + filmstrip + the scripted camera path in miniature -> PIL image."""
    from PIL import Image, ImageDraw
    n = len(rgb_frames)
    al = ghost_alphas(n)
    acc = np.zeros(rgb_frames[0].shape, np.float32)
    for f, a in zip(rgb_frames, al):
        acc += f.astype(np.float32) * a
    ghost = (acc / max(1e-6, sum(al))).clip(0, 255).astype(np.uint8)
    H, W = ghost.shape[:2]
    cols = 3 if n > 4 else n
    rows_n = int(math.ceil(n / float(cols)))
    tw, th = W // cols, int(H / cols)
    sheet = Image.new('RGB', (W, 44 + H + rows_n * th + 8), '#101418')
    dr = ImageDraw.Draw(sheet)
    dr.text((10, 8), header, fill='#E9F3F9', font=_font(15))
    if extra:
        dr.text((10, 26), extra, fill='#81A9AB', font=_font(12))
    sheet.paste(Image.fromarray(ghost), (0, 44))
    # camera path inset: the stage, and the visible window at each sample (oldest faintest)
    iw, ih = 160, 90
    ins = Image.new('RGBA', (iw, ih), (8, 42, 52, 230))
    idr = ImageDraw.Draw(ins)
    for (s, cx, cy), a in zip(path_pts, al):
        hw, hh = stage[0] / 2 / s, stage[1] / 2 / s
        x0, y0 = (cx - hw) / stage[0] * iw, (cy - hh) / stage[1] * ih
        x1, y1 = (cx + hw) / stage[0] * iw, (cy + hh) / stage[1] * ih
        idr.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(229, 107, 94, int(60 + 195 * a)))
    sheet.paste(ins, (W - iw - 8, 44 + 8), ins)
    for i, (f, t) in enumerate(zip(rgb_frames, times)):
        th_img = Image.fromarray(f).resize((tw - 2, th - 2), Image.BILINEAR)
        x, y = (i % cols) * tw + 1, 44 + H + 4 + (i // cols) * th + 1
        sheet.paste(th_img, (x, y))
        dr.text((x + 4, y + 2), '%.2f s' % t, fill='#E8C874', font=_font(12))
    return sheet


def gate_sheets(ctx, cfg, curves, report):
    qa_dir = os.path.join(ctx['project'], 'out', 'qa')
    os.makedirs(qa_dir, exist_ok=True)
    budgets = {b['shot']: b for b in report.get('budget', [])}
    written, failed = [], []
    for sh in curves['shots']:
        n = cfg['samples']
        t0, t1 = sh['t0'] + 0.05, min(sh['t1'], ctx['dur']) - 0.05
        if t1 <= t0:
            continue
        times = [t0 + (t1 - t0) * i / max(1, n - 1) for i in range(n)] if n > 1 else [(t0 + t1) / 2]
        fr = decode_rgb_at(ctx['film'], times, sh['t0'])
        if len(fr) < max(1, n - 1):
            failed.append((sh['shot'], len(fr)))
            continue
        times = times[:len(fr)]
        pts = []
        for t in times:
            j = min(len(sh['samples']) - 1, max(0, int(round((t - sh['t0']) * sh['fps']))))
            p = sh['samples'][j]
            pts.append((p['s'], p['cx'], p['cy']))
        b = budgets.get(sh['shot'], {})
        head = '%s  %.2f-%.2f s  %s  peak %.1f px/f' % (sh['shot'], sh['t0'], sh['t1'], ','.join(sh['verbs']) or 'flat', sh['peak'])
        extra = 'dwell %s s   upsample %s (%s)   %d ghosts, 0.14 -> 1.0 oldest -> newest; smeared = moved, sharp = still' % (
            ','.join('%.1f' % d for d in sh['dwell']) or '-', b.get('upsample', '?'), b.get('level', '?'), len(fr))
        img = compose_sheet(fr, times, head, pts, extra=extra)
        name = ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in sh['shot'])
        p = os.path.join(qa_dir, 'motion_%s.png' % name)
        img.save(p)
        written.append(os.path.relpath(p, ctx['project']))
    ok = not failed and bool(written)
    return ('onion sheets', ok, ('%d sheets -> out/qa/motion_*.png' % len(written)) + ('; undecodable %s' % failed[:3] if failed else '') if written else 'no footage shots decoded')


def run(ctx):
    cfg = _cfg(ctx.get('qa') or {})
    curves, report, note = _curves(ctx)
    if curves is None:
        return [(n, True, note) for n in GATE_NAMES]
    frames = decode_gray(ctx['film'], cfg['fps'], cfg['res'])
    out = [gate_motion(ctx, cfg, curves, frames, report), gate_budget(cfg, report),
           gate_seq(ctx, cfg, report, lambda a, d: decode_gray(ctx['film'], ctx.get('fps', 30), cfg['res'], a, d)),
           gate_sheets(ctx, cfg, curves, report)]
    return out


# ---------------------------------------------------------------- self-test on synthetic frames
def _texture(h=180, w=320, seed=7):
    rng = np.random.default_rng(seed)
    base = rng.random((h // 4, w // 4)).astype(np.float32)
    from PIL import Image
    im = Image.fromarray((base * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    a = np.asarray(im, dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    a += 40 * ((xx // 24 + yy // 24) % 2)              # a grid: UI-like edges
    return a.clip(0, 255).astype(np.uint8)


def _warp(img, scale, dx, dy):
    from PIL import Image
    h, w = img.shape
    im = Image.fromarray(img)
    # zoom about the centre by `scale`, then shift by (dx, dy): PIL affine takes the inverse map
    a = 1.0 / scale
    cx, cy = w / 2.0, h / 2.0
    c = cx - a * (cx + dx)
    f = cy - a * (cy + dy)
    return np.asarray(im.transform((w, h), Image.AFFINE, (a, 0, c, 0, a, f), Image.BILINEAR), dtype=np.uint8)


def selftest():
    T0 = time.time()
    res = []

    def t(name, ok, detail=''):
        res.append(ok)
        print('  %-34s %s  %s' % (name, 'PASS' if ok else 'FAIL', detail))

    al = ghost_alphas(9)
    t('ghost alphas 0.14 -> 1.0', al[0] == 0.14 and al[-1] == 1.0 and len(al) == 9 and al[4] == 0.57, str(al))
    t('ghost alphas n=1', ghost_alphas(1) == [1.0])

    img = _texture()
    sc, dx, dy, _ = estimate_motion(img, _warp(img, 1.06, 0, 0))
    t('recover scale 1.06', abs(sc - 1.06) < 0.02, 'got %.3f' % sc)
    sc, dx, dy, _ = estimate_motion(img, _warp(img, 1.0, 5, -3))
    t('recover shift (5, -3)', abs(sc - 1.0) < 0.01 and abs(dx - 5) < 0.8 and abs(dy + 3) < 0.8, 'scale %.3f dx %.2f dy %.2f' % (sc, dx, dy))
    sc, dx, dy, _ = estimate_motion(img, _warp(img, 1.12, 4, 2))
    t('recover zoom + shift', abs(sc - 1.12) < 0.03 and abs(dx - 4) < 1.5 and abs(dy - 2) < 1.5, 'scale %.3f dx %.2f dy %.2f' % (sc, dx, dy))
    sc, dx, dy, _ = estimate_motion(img, img.copy())
    t('still frame -> scale 1, shift 0', abs(sc - 1.0) < 0.003 and abs(dx) < 0.1 and abs(dy) < 0.1, 'scale %.4f' % sc)

    c0 = change_pct(img, img)
    c1 = change_pct(img, _warp(img, 1.0, 3, 0))
    t('change % still 0 / 3 px pan > 0.3 %', c0 == 0.0 and c1 > 0.3, '%.3f / %.2f' % (c0, c1))
    # v5.1 scans
    seq = [img] * 12
    seq[6] = _warp(img, 1.0, 9, 0)                                              # one frame jumps and comes back
    sp = spikes(seq, 10, cuts=[])
    t('spikes: a one-frame jump is caught, nothing else', len(sp) == 1 and sp[0][0] == 0.6 and sp[0][1] > 2.0, str(sp))
    t('spikes: a cut nearby is not a spike', spikes(seq, 10, cuts=[0.55]) == [], '')
    half = img.copy(); half[:, :160] = _warp(img, 1.0, 5, 0)[:, :160]           # only the left half moved
    ph = pan_halves(img, half)
    pw = pan_halves(img, _warp(img, 1.0, 5, 0))
    t('pan halves: a partial pan disagrees, a whole-frame pan agrees', ph['disagree'] and not pw['disagree'] and abs(pw['left'][1] - 5) < 1.0 and abs(pw['right'][1] - 5) < 1.0, '%s / %s' % (ph, pw))
    t('pan halves: a still frame agrees', not pan_halves(img, img.copy())['disagree'])

    # motion-traced decision logic on a synthetic film: shot 0..3 s, a scripted push at 1..2 s, frames at 10 fps
    fps, FPS = 10, 30
    frames = np.stack([img] * 31)                       # the camera never moved in the pixels
    samples = [{'t': round(i / FPS, 4), 's': 1.0 + 0.3 * min(1, max(0, (i / FPS - 1.0))), 'cx': 640, 'cy': 360} for i in range(0, 91)]
    speed = [0.0] + [abs(samples[i]['s'] - samples[i - 1]['s']) * 640 for i in range(1, 91)]
    curves = {'fps': FPS, 'cuts': [0.0], 'allow': [], 'shots': [{'shot': 'syn', 't0': 0.0, 't1': 3.0, 'fps': FPS, 'samples': samples, 'speed': speed,
                                                                 'windows': {'scroll': [], 'seq': [], 'reveal': [], 'stream': [], 'hl': [], 'seam': [], 'focus': [], 'establish': []}}]}
    import tempfile
    tmp = tempfile.mkdtemp(prefix='motion_diag_')
    ctx = {'project': tmp, 'film': '', 'dur': 3.0}
    cfg = _cfg({})
    rep0 = {'fps': FPS, 'ladders': [{'legs': [{'t0': 1.0, 't1': 2.0, 'verb': 'push-in'}]}]}
    name, ok, d = gate_motion(ctx, cfg, curves, frames, rep0)
    t('dead camera detected (push, no change)', not ok and 'did nothing' in d, d[:90])
    # now the pixels do move during the push and stay still otherwise -> PASS
    frames2 = np.stack([_warp(img, samples[min(90, k * 3)]['s'], 0, 0) for k in range(31)])
    name, ok, d = gate_motion(ctx, cfg, curves, frames2, rep0)
    t('scripted push with real change passes', ok, d[:90])
    # a static screen-space overlay (lower third) on a sparse frame: masked out, the leg still passes
    frames2m = frames2.copy()
    frames2m[:, 150:175, 20:120] = 20
    cfg_m = dict(cfg, mask=[[80, 600, 400, 100]])
    name, ok, d = gate_motion(ctx, cfg_m, curves, frames2m, rep0)
    t('overlay mask applied', ok, d[:90])
    # unscripted: a big change at 2.5 s with the camera still
    frames3 = frames2.copy()
    frames3[26] = 255 - frames3[26]
    name, ok, d = gate_motion(ctx, cfg, curves, frames3, rep0)
    t('unscripted motion detected', not ok and 'unscripted' in d, d[:90])
    # the same change inside a shader seam window (out/timeline.json glSeams) is scheduled motion too
    name, ok, d = gate_motion(dict(ctx, timeline={'glSeams': [{'id': 'gl', 'at': 2.45, 'dur': 0.3, 'name': 'chromaSplit'}]}), cfg, curves, frames3, rep0)
    t('gl seam window is scheduled motion', ok, d[:90])
    # the same change inside an allowance window (a scheduled scroll) is fine
    curves['shots'][0]['windows']['scroll'] = [[2.4, 2.7]]
    name, ok, d = gate_motion(ctx, cfg, curves, frames3, rep0)
    t('scheduled motion is allowed', ok, d[:90])
    # velocity discontinuity warning (a one-frame spike in the scripted speed)
    curves['shots'][0]['speed'][45] = 40.0
    name, ok, d = gate_motion(ctx, cfg, curves, frames2, rep0)
    t('velocity jump reported as WARN', ok and 'velocity jumps' in d, d[-70:])
    meas = json.load(open(os.path.join(tmp, 'out', 'qa', 'camera_measured.json')))
    lg = meas['shots'][0]['legs']
    t('leg ratio measured/expected ~ 1', len(lg) == 1 and lg[0]['ratio'] is not None and 0.7 <= lg[0]['ratio'] <= 1.3, str(lg))
    meas = json.load(open(os.path.join(tmp, 'out', 'qa', 'camera_measured.json')))
    rec = [r for r in meas['shots'][0]['intervals'] if not r.get('skip') and 1.0 <= r['t'] < 1.9]
    t('recovered scale rises during the push', all(r['scale'] > 1.005 for r in rec) and len(rec) >= 7, '%s' % [r['scale'] for r in rec][:5])

    # zoom budget
    rep = {'fps': FPS, 'budget': [{'shot': 'a', 'upsample': 1.45, 'headroomFails': []}, {'shot': 'b', 'upsample': 1.85, 'headroomFails': []}]}
    name, ok, d = gate_budget(cfg, rep)
    t('budget warn at 1.85 passes', ok and 'WARN' in d, d)
    rep['budget'].append({'shot': 'c', 'upsample': 2.3, 'headroomFails': []})
    name, ok, d = gate_budget(cfg, rep)
    t('budget fail above 2.0', not ok and "'c'" in d, d[:80])
    rep = {'fps': FPS, 'budget': [{'shot': 'd', 'upsample': 1.2, 'headroomFails': [14.2]}]}
    t('headroom > 88 % fails', not gate_budget(cfg, rep)[1])

    # seq quantization: footage.js schedule at rate 1 from an arbitrary word time
    at, n, fsrc = 12.3847, 60, 30
    seq = [1 + int(math.floor(max(0, i / FPS - at) * fsrc * 1 + 1e-6)) for i in range(int(math.ceil(at * FPS)), int(math.ceil(at * FPS)) + 59)]
    t('rate-1 schedule steps 1:1', check_schedule(seq, 1, fsrc, FPS) == [], str(seq[:8]))
    seq_half = [1 + int(math.floor(max(0, i / FPS - at) * fsrc * 0.5 + 1e-6)) for i in range(int(math.ceil(at * FPS)), int(math.ceil(at * FPS)) + 59)]
    t('rate-0.5 holds each frame twice', check_schedule(seq_half, 0.5, fsrc, FPS) == [], str(seq_half[:8]))
    broken = seq[:]
    broken[10] = broken[9]                   # a seconds-domain floor that doubled a frame and dropped the next
    off = check_schedule(broken, 1, fsrc, FPS)
    t('doubled/dropped frame is caught', off and any(c in (0, 2) for _, c in off), str(off[:3]))
    t('arbitrary word-time offsets stay clean', all(check_schedule([1 + int(math.floor(max(0, i / FPS - a0) * fsrc + 1e-6)) for i in range(int(math.ceil(a0 * FPS)), int(math.ceil(a0 * FPS)) + 40)], 1, fsrc, FPS) == []
                                                    for a0 in (0.1, 7.418, 23.424000000000003, 18.622, 31.9)))

    # onion sheet composition from synthetic colour frames
    rgb = [np.stack([_warp(img, 1 + 0.04 * i, 2 * i, 0)] * 3, -1) for i in range(9)]
    sheet = compose_sheet(rgb, [i * 0.3 for i in range(9)], 'syn  0.00-2.40 s  push-in  peak 9.0 px/f', [(1 + 0.04 * i, 640 + 3 * i, 360) for i in range(9)], extra='selftest')
    p = os.path.join(tmp, 'motion_syn.png')
    sheet.save(p)
    t('onion sheet written', os.path.exists(p) and os.path.getsize(p) > 5000 and sheet.size[0] == 320, '%s %s' % (sheet.size, p))

    print('\n%s  (%d/%d, %.1f s)' % ('SELFTEST PASS' if all(res) else 'SELFTEST FAIL', sum(res), len(res), time.time() - T0))
    return 0 if all(res) else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--spikes' in sys.argv:
        film = sys.argv[sys.argv.index('--spikes') + 1]
        fr = decode_gray(film, 10, (320, 180))
        sp = spikes(fr, 10)
        for t_, pct, a, b in sp:
            print('  spike  %7.2f s  %.2f %%  (neighbours %.2f / %.2f)' % (t_, pct, a, b))
        print('%d single-frame spike(s) in %s' % (len(sp), os.path.basename(film))); sys.exit(1 if sp else 0)
    if '--pan-halves' in sys.argv:
        i = sys.argv.index('--pan-halves'); film = sys.argv[i + 1]
        t0 = float(sys.argv[i + 2]) if len(sys.argv) > i + 2 else 0.0
        t1 = float(sys.argv[i + 3]) if len(sys.argv) > i + 3 else t0 + 3.0
        rows = pan_halves_film(film, t0, t1)
        bad = [r for r in rows if r[3]]
        for t_, L, R, dis in rows:
            print('  %7.2f s  left s %.3f dx %+.1f dy %+.1f   right s %.3f dx %+.1f dy %+.1f%s' % (t_, L[0], L[1], L[2], R[0], R[1], R[2], '   PARTIAL' if dis else ''))
        print('%d/%d intervals where the halves disagree (partial pan)' % (len(bad), len(rows))); sys.exit(1 if bad else 0)
    if '--roster' in sys.argv:
        i = sys.argv.index('--roster')
        r = roster(sys.argv[i + 1], sys.argv[i + 2])
        print(json.dumps(r, indent=1, ensure_ascii=False)); sys.exit(1 if r.get('new') or r.get('gone') else 0)
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    print(__doc__)
