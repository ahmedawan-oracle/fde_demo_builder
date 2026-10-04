# -*- coding: utf-8 -*-
"""cursor_track.py — recover the pointer's path and its clicks from a screen recording that has no telemetry.

    python tools/cursor_track.py recording.mp4 --out events.jsonl [--fps auto] [--width 960] [--sheet out/cursor_sheet.jpg]
    python tools/cursor_track.py recording.mp4 --out events.jsonl --start 12 --duration 40      # a window of the tape
    python tools/cursor_track.py --selftest                                                      # synthetic 6 s tape, < 60 s
    python tools/cursor_track.py --help

Why this exists. The footage lane erases the real pointer (per-pixel median stills), so the film needs to know
where the presenter's hand was in order to redraw a clean cursor (lib/cursor.js) and to let the camera follow the
work (tools/camera_from_events.py). record_events.py gives that for free at capture time; this tool is the fallback
for tapes recorded without it. It writes the same events.jsonl, every line carrying a confidence.

Method, from first principles
  1. Decode. ffmpeg decodes the tape to grey frames at a reduced rate and size: every k-th SOURCE frame is kept
     (select=not(mod(n,k)), k = the smallest integer that brings the rate to <= 15 fps: 30 -> 15, 60 -> 15,
     25 -> 12.5), so an analysis frame is a real frame and its time is exact. A variable-frame-rate tape (macOS)
     is first regularised to its nominal rate. Width = 0.64 x the source width by default (1920 -> 1228,
     2426 -> 1552): an OS pointer is ~12 x 19 px on a 1x display whatever its resolution (measured 12 x 20 px on the
     2426-px calibration tape) and 2x that on a Retina capture, and the matcher needs it >= 12 px tall — at a
     960-wide decode the calibration pointer was 5 x 8 px and nothing could find it. A pointer moves at up to
     ~2000 px/s, so 15 fps keeps consecutive positions within ~130 source px, which sizes the local search window.
  2. Signed gradients, not pixels. A pointer is a white shape with a black outline (Windows) or a black shape with
     a white outline (macOS). We match the pointer's own Sobel gradient field (gx, gy) — the orientation pattern of
     its outline — not the grey image (text and the pointer share grey statistics) and not the gradient magnitude
     (text strokes have the same edge density; measured: a magnitude match scored text 0.59-0.65 and the pointer
     0.61-0.71, no margin). Taking |score| makes both polarities score alike.
  3. Templates we draw ourselves (Pillow, 4x supersampled, box-filtered): an arrow at 10 / 13 / 17 / 22 px tall
     (a 1x pointer lands at 12-15 px after step 1, a 2x Retina pointer at 22-24), an I-beam at 11 / 15 / 20 px and
     a pointing hand at 12 / 16 / 21 px — ten templates. Each is masked to its own silhouette plus a 2 px ring
     (where the outline-to-ground step lives), so the ground around the pointer never enters the score.
  4. Score = masked normalised cross-correlation of the template gradients against the frame gradients: three FFT
     correlations per template (gx*tx + gy*ty for the numerator, gx^2+gy^2 under the mask for the denominator,
     floored at a 1.5-grey-level noise energy so flat regions score ~0); the frame region is transformed once per
     frame, the template spectra once per run. Per frame the search is a fixed 220 x 220 decoded-px window centred
     on the PREDICTED position (last + 0.8 x velocity); every 2.0 s, whenever the local best is weak or a large part
     of the frame changed (scroll / page change), a global pass over the whole frame runs. Peaks are the local maxima
     of each score map, strongest first, refined to sub-pixel precision with a 3-point parabola. Hysteresis: a peak is
     accepted at >= 0.55 when (re)acquiring globally and >= 0.45 inside the local window; measured, the pointer scores
     0.58-0.71 (0.70-0.78 at rest on flat ground) and the strongest false peaks on text and icons 0.54-0.67 — shape
     alone has no margin, which is why 4b-4d exist. The hot spot (arrow tip, I-beam centre, finger tip) is what gets
     returned, in SOURCE pixels.
  4b. Time. The pointer is the one thing that never becomes part of the background. A background image follows each
     frame by at most 30 grey levels per frame where the frame did NOT change since the previous one (static UI, a
     panel that just opened: gone from the foreground in ~5 frames) and by 3 where it did (a moving pointer, an
     animation); a page change resets it. A global (re)acquisition candidate must have foreground (|frame -
     background| > 20) under >= 8 % of its mask (measured: the real pointer 0.13-0.5, static icons and text 0.00-0.01).
     A pointer that rests sinks into the background and is kept by continuity (a candidate within 4 px of the last
     position is exempt) but returned with half confidence once it has shown no foreground for 3 s (stale).
  4c. Continuity is evidence. Inside the window, candidates compete on score - 0.0012 x distance from the predicted
     position (a fresh panel edge 165 px away at 0.60 no longer beats the moving pointer at 0.58); an alive local
     track (foreground under it) yields to a global candidate only at +0.10 score, a resting one at +0.05, and a
     stale lock to any foreground candidate at the continuity threshold — motion wins over a dead lock.
  4d. Kinds and size. The I-beam (a stem with serifs — also a checkbox edge, a "|" separator, an "l") is matched only
     within 40 px of the hand, only at the full acquisition score, and with a 0.06 prior against it: the arrow is the
     common case. The OS pointer has one size: after 10 consistent arrow acceptances, global acquisition only
     considers templates within 0.75-1.35 x that height.
  5. Clicks cannot be seen, only their consequences. A click is declared when the pointer dwells (moves < 6
     decoded px) for >= 150 ms and, within 300 ms after the dwell, the pixels in a 160 x 160 source-px box around
     it change (>= 2.5 % of the box's pixels move by > 8 grey levels — a selection tint is ~10, codec noise < 4; the pointer's own footprint masked out so
     the hand leaving does not count). The click time is one analysis frame before the change (the UI reacts within
     a frame of the press); `down` and `up` are written 80 ms apart. Confidence = pointer confidence x a
     change-strength factor, x 0.6 when the whole frame changed (a navigation may also have been a scroll).

Output events.jsonl (same schema as record_events.py; all coordinates are SOURCE pixels):
    {"type":"meta","tool":"cursor_track","source":[W,H],"fps":15.0,"decode":[960,540],"accept":0.6,...}
    {"t":1.200,"x":1210.4,"y":296.8,"type":"move","conf":0.71,"kind":"arrow"}
    {"t":1.800,"x":1210.4,"y":296.8,"type":"down","button":"left","conf":0.64}
    {"t":1.880,"x":1210.4,"y":296.8,"type":"up","button":"left","conf":0.64}
Exit codes: 0 ok (>= 60 % of frames tracked), 1 findings (fewer frames tracked, printed), 2 usage.
Deterministic: pure numpy/scipy on the decoded frames, no randomness, no wall clock in the output.
Dependencies: numpy, scipy, Pillow, ffmpeg/ffprobe on PATH. Nothing from the tape is kept except the events.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
from scipy import ndimage

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VERSION = '1.0'
DEFAULTS = {
    'width': 'auto',       # decode width: auto = 0.64 x source width (a 19 px OS pointer stays >= 12 px tall); height follows the aspect
    'width_scale': 0.64,
    'fps': 'auto',         # analysis rate: source rate / smallest k that brings it <= 15
    'accept': 0.55,        # NCC accept threshold for (re)acquisition — measured, see docstring
    'accept_local': 0.45,  # accept threshold inside the local window around the last position (continuity)
    'stale_s': 3.0,        # a lock with no foreground for this long loses its continuity privilege (motion elsewhere wins)
    'swap_margin_alive': 0.10,   # a global candidate must beat an alive (foreground-covered) local track by this much
    'swap_margin_rest': 0.05,    # ... and a resting (not yet stale) one by this much
    'size_lock_n': 10,     # consistent arrow acceptances before the pointer size is trusted
    'size_ratio': (0.75, 1.35),  # templates within this ratio of the locked height stay eligible for global acquisition
    'local': 110,          # local search half-window, decoded px
    'global_every': 2.0,   # seconds between global passes
    'scene_change': 0.30,  # fraction of frame pixels changed that forces a global pass
    'dwell_px': 6,         # decoded px the pointer may wander and still be "still"
    'dwell_ms': 150,       # minimum dwell before a click is possible
    'react_ms': 300,       # the UI must react within this time after the dwell
    'click_box': 160,      # source px, side of the box watched for the reaction
    'click_frac': 0.025,   # fraction of box pixels that must change
    'click_level': 8,      # grey-level change that counts (a selection tint is ~10 levels; codec noise stays under 4)
    'bg_step': 3.0,        # background absorption where the frame CHANGED since the previous one (a moving pointer never sinks in)
    'bg_step_still': 30.0, # ... where it did not change (static UI, a panel that just opened: gone from the foreground in ~5 frames)
    'still_level': 4.0,    # |frame - previous frame| below this counts as unchanged
    'fg_level': 20.0,      # |frame - background| above this = foreground
    'min_cov': 0.08,       # foreground must cover this share of a candidate's mask to (re)acquire it globally (real pointer 0.13+, static icons 0.00-0.01)
    'warmup': 0,           # frames after a background reset during which coverage is not required (0: the pointer must move once to be found)
    'arrow_heights': (10, 13, 17, 22), 'ibeam_heights': (11, 15, 20), 'hand_heights': (12, 16, 21),
}


def decode_width(source_w, want='auto', cfg=None):
    """Decode width in px: an explicit number, or 0.64 x the source width rounded to an even number (never above the source)."""
    if want not in (None, 'auto'):
        return int(want)
    k = (cfg or DEFAULTS)['width_scale']
    return min(int(source_w), int(round(source_w * k / 2.0)) * 2)


# ---------------------------------------------------------------- templates (drawn, never copied)
def _render(draw_fn, w, h, ss=4):
    """Draw at ss x size with Pillow and box-filter down. Returns (shape grey in [0,1], mask in [0,1]).
    draw_fn(d, ss, mask_only): the same shape twice — once as it looks (fill + outline), once as a solid mask."""
    from PIL import Image, ImageDraw
    im = Image.new('L', (w * ss, h * ss), 128)          # mid-grey ground; only the shape's own edges carry gradient
    draw_fn(ImageDraw.Draw(im), ss, False)
    mk = Image.new('L', (w * ss, h * ss), 0)
    draw_fn(ImageDraw.Draw(mk), ss, True)
    g = np.asarray(im.resize((w, h), Image.BOX), dtype=np.float32) / 255.0
    m = np.asarray(mk.resize((w, h), Image.BOX), dtype=np.float32) / 255.0
    return g, m


def arrow_template(hgt):
    """The classic arrow: tip top-left, straight left edge, notched tail. Hot spot = tip."""
    pad = 3
    w, h = int(round(hgt * 0.62)) + 2 * pad, hgt + 2 * pad
    H = float(hgt)
    pts = [(0, 0), (0, 0.84 * H), (0.21 * H, 0.67 * H), (0.35 * H, 0.98 * H), (0.47 * H, 0.93 * H),
           (0.33 * H, 0.62 * H), (0.60 * H, 0.62 * H)]

    def draw(d, ss, mask_only):
        poly = [((x + pad) * ss, (y + pad) * ss) for x, y in pts]
        if mask_only:
            d.polygon(poly, fill=255)
            d.line(poly + [poly[0]], fill=255, width=max(1, int(1.2 * ss)))
            return
        d.polygon(poly, fill=255, outline=0)
        d.line(poly + [poly[0]], fill=0, width=max(1, int(1.2 * ss)))
    return _render(draw, w, h), (pad, pad), 'arrow'


def ibeam_template(hgt):
    """Text cursor: a vertical stem with short serifs. Hot spot = centre of the stem."""
    pad = 3
    w, h = int(round(hgt * 0.55)) + 2 * pad, hgt + 2 * pad
    H = float(hgt)

    def draw(d, ss, mask_only):
        cx = (w / 2.0) * ss
        d.line([(cx, pad * ss), (cx, (pad + H) * ss)], fill=255, width=max(2, int(1.6 * ss)))
        if not mask_only:
            d.line([(cx, pad * ss), (cx, (pad + H) * ss)], fill=0, width=max(1, int(0.6 * ss)))
        for yy in (pad, pad + H):
            d.line([((pad + 0.1 * H) * ss, yy * ss), ((pad + 0.45 * H) * ss, yy * ss)], fill=255 if mask_only else 0, width=max(1, int(1.2 * ss)))
    return _render(draw, w, h), (w / 2.0, h / 2.0), 'ibeam'


def hand_template(hgt):
    """Pointing hand, simplified: a rounded palm with a raised index finger. Hot spot = finger tip."""
    pad = 3
    w, h = int(round(hgt * 0.75)) + 2 * pad, hgt + 2 * pad
    H = float(hgt)

    def draw(d, ss, mask_only):
        fx0, fx1 = (pad + 0.28 * H) * ss, (pad + 0.44 * H) * ss
        kw = dict(fill=255) if mask_only else dict(fill=255, outline=0, width=max(1, int(1.2 * ss)))
        d.rounded_rectangle([(pad + 0.12 * H) * ss, (pad + 0.42 * H) * ss, (pad + 0.72 * H) * ss, (pad + 0.98 * H) * ss], radius=0.14 * H * ss, **kw)
        d.rounded_rectangle([fx0, pad * ss, fx1, (pad + 0.55 * H) * ss], radius=0.08 * H * ss, **kw)
    return _render(draw, w, h), (pad + 0.36 * H, pad), 'hand'


def gradients(img):
    """Signed Sobel gradients (gx, gy) of a float32 image, edge-replicated (numpy slicing: ~20x faster than ndimage here)."""
    p = np.pad(img, 1, mode='edge')
    sm_y = p[:-2, :] + 2 * p[1:-1, :] + p[2:, :]          # vertical [1,2,1] smoothing, rows now = H
    gx = sm_y[:, 2:] - sm_y[:, :-2]
    sm_x = p[:, :-2] + 2 * p[:, 1:-1] + p[:, 2:]          # horizontal smoothing, cols now = W
    gy = sm_x[2:, :] - sm_x[:-2, :]
    return gx.astype(np.float32), gy.astype(np.float32)


def template_bank(cfg=None):
    """[{'tx','ty' (masked, jointly unit-norm), 'mask' (shape + 2 px ring), 'hot', 'kind', 'shape'}] — seven templates."""
    cfg = cfg or DEFAULTS
    raw = [(arrow_template(h), h) for h in cfg['arrow_heights']] + [(ibeam_template(h), h) for h in cfg['ibeam_heights']] + [(hand_template(h), h) for h in cfg['hand_heights']]
    out = []
    for ((g, m), hot, kind), hgt in raw:
        mask = ndimage.binary_dilation(m > 0.05, iterations=2).astype(np.float32)   # the outline-to-ground step lives in the ring
        tx, ty = gradients(g)
        tx, ty = tx * mask, ty * mask
        n = float(np.sqrt((tx * tx + ty * ty).sum())) or 1.0
        out.append({'tx': (tx / n).astype(np.float32), 'ty': (ty / n).astype(np.float32), 'mask': mask, 'hot': hot, 'kind': kind, 'shape': g.shape, 'h': hgt})
    return out


# ---------------------------------------------------------------- masked, signed-gradient NCC
def _refine(score, y, x):
    """3-point parabolic sub-pixel refinement of a peak at integer (y, x)."""
    def off(a, b, c):
        d = a - 2 * b + c
        return 0.0 if abs(d) < 1e-9 else max(-0.5, min(0.5, 0.5 * (a - c) / d))
    dy = off(score[y - 1, x], score[y, x], score[y + 1, x]) if 0 < y < score.shape[0] - 1 else 0.0
    dx = off(score[y, x - 1], score[y, x], score[y, x + 1]) if 0 < x < score.shape[1] - 1 else 0.0
    return y + dy, x + dx


class Matcher:
    """|NCC| of every template's masked signed gradients against a region of fixed shape (H, W), via FFT correlation.

    Numerator: sum over the mask of gx*tx + gy*ty. Denominator: the frame's gradient energy under the mask
    (correlation of gx^2+gy^2 with the mask), floored at a 1.5-grey-level noise energy so flat regions score ~0.
    |.| makes a black-on-white pointer (macOS) and a white-on-black one (Windows) score the same.
    The region is transformed ONCE per frame (3 forward FFTs); each template costs 2 inverse FFTs against spectra
    precomputed at construction. corr[i, j] = sum_k region[i+k, j+l] * tmpl[k, l]: the peak IS the template's top-left."""

    def __init__(self, bank, shape):
        from scipy.fft import next_fast_len, rfft2
        self.H, self.W = shape
        hmax = max(T['shape'][0] for T in bank)
        wmax = max(T['shape'][1] for T in bank)
        self.P = (next_fast_len(self.H + hmax), next_fast_len(self.W + wmax))
        self.T, self.masks = [], []
        for T in bank:
            self.T.append({'cx': np.conj(rfft2(T['tx'], self.P)), 'cy': np.conj(rfft2(T['ty'], self.P)), 'cm': np.conj(rfft2(T['mask'], self.P)),
                           'floor': float(T['mask'].sum()) * (1.5 * 4) ** 2, 'msum': float(T['mask'].sum()), 'hot': T['hot'], 'kind': T['kind'], 'shape': T['shape'], 'h': T.get('h', T['shape'][0] - 6)})
            self.masks.append(T['mask'])

    def best(self, gx, gy, fg=None, min_cov=0.0, floor_score=0.3, anchor=None, anchor_px=4.0, topk=24, allow=None, pred=None, penalty=0.0012, ibeam_px=40.0, ibeam_min=0.55, ibeam_bias=0.06):
        """Best (score, hotspot_y, hotspot_x, kind, coverage, template_h) over the bank for a region of exactly self.shape.

        fg: bool foreground map of the region (|frame - slow background| > level). A candidate peak is accepted only if
        the foreground covers >= min_cov of its template mask — a pointer-shaped UI icon is part of the background and
        fails this; a pointer that just arrived passes — or if it lies within anchor_px of `anchor` (a resting pointer
        has sunk into the background, so continuity vouches for it). Peaks are the local maxima of each score map
        (5x5), strongest first, so a static false peak cannot hide the true one behind it.
        pred: the predicted position (last + velocity); when given, candidates compete on score - penalty * distance
        (0.0012 per decoded px: a candidate 100 px off the prediction needs +0.12 score to win — a moving pointer scores
        ~0.58 while a fresh panel edge 165 px away scored 0.60 and used to steal the track), and an I-beam is only
        eligible within ibeam_px of it (a text cursor appears where the arrow was, never out of nowhere).
        The returned score is the raw NCC, not the penalised one."""
        from scipy.fft import irfft2, rfft2
        Fx, Fy, Fe = rfft2(gx, self.P), rfft2(gy, self.P), rfft2(gx * gx + gy * gy, self.P)
        best, best_eff = (-2.0, 0.0, 0.0, '', 0.0, 0), -9.0
        for T, mask in zip(self.T, self.masks):
            if allow is not None and not allow(T):
                continue
            h, w = T['shape']
            vh, vw = self.H - h + 1, self.W - w + 1          # valid top-left positions
            if vh < 3 or vw < 3:
                continue
            num = irfft2(Fx * T['cx'] + Fy * T['cy'], self.P)[:vh, :vw]
            e = irfft2(Fe * T['cm'], self.P)[:vh, :vw]
            sc = np.abs(num) / np.sqrt(np.maximum(e, T['floor']))
            if (fg is None or min_cov <= 0) and pred is None:
                cands = [np.unravel_index(int(np.argmax(sc)), sc.shape)]
            else:
                peaks = (sc == ndimage.maximum_filter(sc, size=5)) & (sc >= floor_score)
                ys, xs = np.nonzero(peaks)
                if len(ys) == 0:
                    continue
                order = np.argsort(-sc[ys, xs])[:topk]
                cands = list(zip(ys[order], xs[order]))
            for iy, ix in cands:
                s = float(sc[iy, ix])
                if s <= best_eff:
                    break                                      # candidates are strongest-first; penalties only lower them
                hy, hx = iy + T['hot'][1], ix + T['hot'][0]
                d = math.hypot(hy - pred[0], hx - pred[1]) if pred is not None else 0.0
                if T['kind'] == 'ibeam' and ((pred is not None and d > ibeam_px) or s < ibeam_min):
                    continue                                   # a text cursor: only near the hand, and only a confident match
                eff = s - penalty * d - (ibeam_bias if T['kind'] == 'ibeam' else 0.0)   # kind prior: the arrow is the common case
                if eff <= best_eff:
                    continue
                cov = 1.0
                if fg is not None and min_cov > 0:
                    cov = float((fg[iy:iy + h, ix:ix + w] * mask).sum() / T['msum'])
                    near = anchor is not None and math.hypot(hy - anchor[0], hx - anchor[1]) <= anchor_px
                    if cov < min_cov and not near:
                        continue
                ry, rx = _refine(sc, iy, ix)
                best, best_eff = (s, ry + T['hot'][1], rx + T['hot'][0], T['kind'], cov, T['h']), eff
        return best


def best_match(gx, gy, bank, window=None, matchers=None, fg=None, min_cov=0.0, anchor=None, allow=None, pred=None):
    """Best (score, hotspot_y, hotspot_x, kind, coverage, template_height); window = (y0, y1, x0, x1) in decoded px or
    None (whole frame). anchor = (y, x) of the last accepted hotspot in frame coordinates. allow(T) filters templates."""
    matchers = matchers if matchers is not None else {}
    if window is None:
        y0, x0, sx_, sy_ = 0, 0, gx, gy
        f_ = fg
    else:
        y0, y1, x0, x1 = window
        sx_, sy_ = gx[y0:y1, x0:x1], gy[y0:y1, x0:x1]
        f_ = fg[y0:y1, x0:x1] if fg is not None else None
    key = sx_.shape
    if key not in matchers:
        matchers[key] = Matcher(bank, key)
    a = (anchor[0] - y0, anchor[1] - x0) if anchor is not None else None
    p = (pred[0] - y0, pred[1] - x0) if pred is not None else None
    s, py, px, kind, cov, h = matchers[key].best(sx_, sy_, f_, min_cov, anchor=a, allow=allow, pred=p)
    return (s, y0 + py, x0 + px, kind, cov, h)


# ---------------------------------------------------------------- decode
def probe(path, full=False):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,r_frame_rate,avg_frame_rate:format=duration', '-of', 'json', path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('ffprobe failed: %s' % r.stderr.strip()[:200])
    j = json.loads(r.stdout)
    st = j['streams'][0]

    def rate(s):
        a, _, b = s.partition('/')
        return float(a) / float(b or 1) if float(b or 1) else 0.0
    r_fr = rate(st.get('r_frame_rate') or '30/1')
    a_fr = rate(st.get('avg_frame_rate') or '0/0') or r_fr
    is_vfr = abs(r_fr - a_fr) > 0.5
    fr = r_fr if 1 < r_fr < 240 else a_fr
    out = (int(st['width']), int(st['height']), fr, float(j.get('format', {}).get('duration') or 0))
    return out + (is_vfr,) if full else out


def pick_fps(src_fps, want):
    """Analysis rate: the source rate divided by the smallest integer k that brings it to <= 15 fps."""
    if want != 'auto':
        return float(want)
    k = max(1, int(math.ceil(src_fps / 15.0)))
    return src_fps / k


def decode_frames(path, width, fps, start=None, duration=None, vfr=None):
    """Yield (t, grey uint8 HxW). Every k-th SOURCE frame is kept (select), so an analysis frame is a real frame with an
    exact time; a variable-frame-rate tape is first regularised to its nominal rate (vfr=True, or auto-detected)."""
    W, H, src_fps, _, is_vfr = probe(path, full=True)
    h = int(round(width * H / float(W) / 2.0)) * 2
    k = max(1, int(round(src_fps / fps)))
    if vfr is None:
        vfr = is_vfr
    chain = (['fps=%.6f' % src_fps] if vfr else []) + ['select=not(mod(n\\,%d))' % k, 'setpts=N/%.6f/TB' % fps,
                                                       'scale=%d:%d:flags=area' % (width, h), 'format=gray']
    cmd = ['ffmpeg', '-nostdin', '-v', 'error']
    if start:
        cmd += ['-ss', '%.3f' % start]
    cmd += ['-i', path]
    if duration:
        cmd += ['-t', '%.3f' % duration]
    cmd += ['-vf', ','.join(chain), '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = width * h
    kf = 0
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n:
            break
        yield (start or 0.0) + kf / fps, np.frombuffer(buf, dtype=np.uint8).reshape(h, width)
        kf += 1
    p.stdout.close()
    p.wait()


# ---------------------------------------------------------------- tracking
def track(frames, fps, source_wh, decode_w, cfg=None, progress=None):
    """frames: iterable of (t, grey uint8 HxW). Returns (events, stats). Coordinates in source px."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    bank = template_bank(cfg)
    sx = source_wh[0] / float(decode_w)                 # source px per decoded px
    local, accept = int(cfg['local']), float(cfg['accept'])
    accept_local = float(cfg['accept_local'])
    glob_every = max(1, int(round(cfg['global_every'] * fps)))
    box = max(8, int(round(cfg['click_box'] / sx / 2)))  # half side, decoded px
    dwell_frames = max(1, int(math.ceil(cfg['dwell_ms'] / 1000.0 * fps)))
    react_frames = max(1, int(math.ceil(cfg['react_ms'] / 1000.0 * fps)))

    moves, prev, last, n, lost = [], None, None, 0, 0
    frame_change, local_change, matchers = [], [], {}
    bg, bg_age, last_fg_t, arrow_hs, prev_pos, last_k = None, 0, -1e9, [], None, -9
    clampf = lambda v, a, b: max(a, min(b, v))
    step, fg_level, min_cov, warm, stale_s = float(cfg['bg_step']), float(cfg['fg_level']), float(cfg['min_cov']), int(cfg['warmup']), float(cfg['stale_s'])
    for k, (t, g) in enumerate(frames):
        n += 1
        img = g.astype(np.float32)
        gx, gy = gradients(img)
        changed_frac, lc = 0.0, 0.0
        if prev is not None:
            diff = np.abs(img - prev) > cfg['click_level']
            changed_frac = float(diff.mean())
            if last is not None:
                py, px = int(round(last[2])), int(round(last[1]))
                y0, y1 = max(0, py - box), min(g.shape[0], py + box)
                x0, x1 = max(0, px - box), min(g.shape[1], px + box)
                sub = diff[y0:y1, x0:x1].copy()
                yy, xx = np.ogrid[y0:y1, x0:x1]
                sub[(yy - py) ** 2 + (xx - px) ** 2 <= 14 ** 2] = False   # the pointer's own footprint
                lc = float(sub.sum()) / max(1.0, float(sub.size) - math.pi * 14 ** 2)
        frame_change.append(changed_frac)
        local_change.append(lc)
        # slow background: the UI sinks in at <= bg_step levels per frame, the moving pointer never does; a page change resets it
        if bg is None or changed_frac > cfg['scene_change']:
            bg, bg_age = img.copy(), 0
        fg = np.abs(img - bg) > fg_level
        need_cov = min_cov if bg_age >= warm else 0.0
        stale = last is not None and (t - last_fg_t) > stale_s          # the lock has shown no foreground for a while
        periodic = last is None or (k % glob_every == 0) or changed_frac > cfg['scene_change'] or stale
        anchor = (last[2], last[1]) if last is not None else None
        # the OS pointer has one size: after size_lock_n consistent arrow acceptances, global acquisition only considers
        # templates within size_ratio of that height (text stems and icons at other scales stop competing)
        size_h = float(np.median(arrow_hs[-cfg['size_lock_n']:])) if len(arrow_hs) >= cfg['size_lock_n'] else None
        allow_global = lambda T: T['kind'] != 'ibeam' and (size_h is None or cfg['size_ratio'][0] * size_h <= T['h'] <= cfg['size_ratio'][1] * size_h)
        best = (-2.0, 0.0, 0.0, '', 0.0, 0)
        if last is not None and g.shape[0] > 2 * local and g.shape[1] > 2 * local:
            # a fixed-size window (one Matcher, spectra reused) centred on the PREDICTED position (last + velocity),
            # clamped inside the frame; the anchor keeps a resting pointer, the prediction penalises far candidates
            vy, vx = (last[2] - prev_pos[0], last[1] - prev_pos[1]) if prev_pos is not None else (0.0, 0.0)
            pred = (clampf(last[2] + 0.8 * vy, 0, g.shape[0] - 1), clampf(last[1] + 0.8 * vx, 0, g.shape[1] - 1))
            y0 = min(max(0, int(round(pred[0])) - local), g.shape[0] - 2 * local)
            x0 = min(max(0, int(round(pred[1])) - local), g.shape[1] - 2 * local)
            best = best_match(gx, gy, bank, (y0, y0 + 2 * local, x0, x0 + 2 * local), matchers, fg, need_cov, anchor, None, pred)
        if best[0] < accept_local or periodic:
            gb = best_match(gx, gy, bank, None, matchers, fg, need_cov, None, allow_global)
            # continuity is evidence: an alive local track (foreground under it) yields only to a clearly better candidate
            # (+swap_margin_alive); a resting one (no foreground yet, not stale) to +swap_margin_rest at >= accept; a stale
            # lock (no foreground for stale_s) to any foreground candidate at the continuity threshold — motion wins
            if best[0] < accept_local:
                take = gb[0] >= accept
            elif stale:
                take = gb[0] >= accept_local and gb[4] >= min_cov
            elif best[4] >= min_cov:
                take = gb[0] >= accept and gb[4] >= min_cov and gb[0] >= best[0] + cfg['swap_margin_alive']
            else:
                take = gb[0] >= accept and gb[4] >= min_cov and gb[0] >= best[0] + cfg['swap_margin_rest']
            if take:
                best = gb
        if best[0] >= accept_local:
            if best[4] >= min_cov or need_cov <= 0:
                last_fg_t = t
            if best[3] == 'arrow':
                arrow_hs.append(best[5])
            prev_pos = (last[2], last[1]) if (last is not None and last_k == k - 1) else None   # velocity only from consecutive frames
            last_k = k
            last = (t, best[2], best[1], best[0], best[3])
            conf = best[0] * (0.5 if stale and best[4] < min_cov else 1.0)      # a long-dead lock is returned, but doubted
            moves.append({'t': round(t, 4), 'x': round(best[2] * sx, 1), 'y': round(best[1] * sx, 1), 'type': 'move',
                          'conf': round(min(1.0, conf), 3), 'kind': best[3], 'fg': round(best[4], 2)})
        else:
            lost += 1
        # adaptive absorption: where the frame did not change since the previous one (static UI, a panel that just opened)
        # the background follows fast (bg_step_still); where it did (a moving pointer, an animation) only slowly (bg_step)
        if prev is not None:
            still = np.abs(img - prev) < cfg['still_level']
            sm = np.where(still, float(cfg['bg_step_still']), step).astype(np.float32)
            bg += np.clip(img - bg, -sm, sm)
        else:
            bg += np.clip(img - bg, -step, step)
        bg_age += 1
        prev = img
        if progress and k % 50 == 0:
            progress(k, t)

    # ---- clicks: dwell >= dwell_ms, then a local reaction within react_ms
    clicks = []
    i = 0
    dwell_px = cfg['dwell_px'] * sx
    while i < len(moves):
        j = i
        while j + 1 < len(moves) and math.hypot(moves[j + 1]['x'] - moves[i]['x'], moves[j + 1]['y'] - moves[i]['y']) <= dwell_px \
                and (moves[j + 1]['t'] - moves[j]['t']) <= 1.5 / fps + 1e-6:
            j += 1
        if j - i + 1 >= dwell_frames:
            k_i, k_j = int(round(moves[i]['t'] * fps)), int(round(moves[j]['t'] * fps))
            lo, hi = k_i + dwell_frames - 1, min(len(local_change) - 1, k_j + react_frames)
            found = None
            for kk in range(lo + 1, hi + 1):
                if local_change[kk] >= cfg['click_frac']:
                    found = kk
                    break
            if found is not None:
                tc = max(moves[i]['t'], (found - 1) / fps)
                m = min(moves[i:j + 1], key=lambda mm: abs(mm['t'] - tc))
                strength = min(1.0, local_change[found] / (3 * cfg['click_frac']))
                conf = m['conf'] * (0.6 + 0.4 * strength)
                if frame_change[found] > cfg['scene_change']:
                    conf *= 0.6
                if not clicks or tc - clicks[-1]['t'] > 0.4:
                    clicks.append({'t': round(tc, 4), 'x': m['x'], 'y': m['y'], 'type': 'down', 'button': 'left', 'conf': round(conf, 3)})
        i = j + 1
    events = list(moves)
    for c in clicks:
        events.append(c)
        events.append(dict(c, t=round(c['t'] + 0.08, 4), type='up'))
    events.sort(key=lambda e: (e['t'], 0 if e['type'] == 'move' else 1 if e['type'] == 'down' else 2))
    stats = {'frames': n, 'tracked': n - lost, 'tracked_frac': round((n - lost) / float(max(1, n)), 4), 'clicks': len(clicks),
             'mean_conf': round(float(np.mean([m['conf'] for m in moves])) if moves else 0.0, 4),
             'kinds': {k: sum(1 for m in moves if m['kind'] == k) for k in ('arrow', 'ibeam', 'hand')}}
    return events, stats


def write_events(path, events, meta):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(dict({'type': 'meta'}, **meta), sort_keys=True) + '\n')
        for e in events:
            f.write(json.dumps(e, sort_keys=True) + '\n')


# ---------------------------------------------------------------- the review sheet
def sheet(path_video, events, out, source_wh, n=12, width=480):
    """n frames evenly spaced over the tracked span, each with the detected position drawn (ring + cross; a click = gold ring)."""
    import io
    from PIL import Image, ImageDraw
    moves = [e for e in events if e['type'] == 'move']
    clicks = [e for e in events if e['type'] == 'down']
    if not moves:
        return None
    t0, t1 = moves[0]['t'], moves[-1]['t']
    times = [t0 + (t1 - t0) * (i + 0.5) / n for i in range(n)]
    cols = 4
    rows = int(math.ceil(n / float(cols)))
    sx = width / float(source_wh[0])
    h = int(round(source_wh[1] * sx))
    S = Image.new('RGB', (cols * width, rows * h), (8, 42, 52))
    for i, t in enumerate(times):
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', path_video, '-frames:v', '1',
                            '-vf', 'scale=%d:%d' % (width, h), '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True)
        try:
            im = Image.open(io.BytesIO(r.stdout)).convert('RGB')
        except Exception:
            im = Image.new('RGB', (width, h), (32, 74, 86))
        d = ImageDraw.Draw(im)
        m = min(moves, key=lambda mm: abs(mm['t'] - t))
        if abs(m['t'] - t) < 0.5:
            x, y = m['x'] * sx, m['y'] * sx
            d.ellipse([x - 14, y - 14, x + 14, y + 14], outline=(229, 107, 94), width=3)
            d.line([x - 22, y, x + 22, y], fill=(229, 107, 94), width=1)
            d.line([x, y - 22, x, y + 22], fill=(229, 107, 94), width=1)
            d.text((6, 6), 't=%.2fs  conf %.2f  %s' % (t, m['conf'], m['kind']), fill=(232, 200, 116))
        else:
            d.text((6, 6), 't=%.2fs  (no track)' % t, fill=(229, 107, 94))
        for c in clicks:
            if abs(c['t'] - t) < 0.6:
                x, y = c['x'] * sx, c['y'] * sx
                d.ellipse([x - 24, y - 24, x + 24, y + 24], outline=(232, 200, 116), width=4)
        S.paste(im, ((i % cols) * width, (i // cols) * h))
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    S.save(out, quality=85)
    return out


# ---------------------------------------------------------------- synthetic fixture (fictional "Acme Console")
def fixture_truth(dur=6.0, fps=30, W=1920, H=1080):
    """Ground truth for the synthetic tape: pointer tip per source frame, click times, and UI state changes."""
    way = [(0.0, 300, 420), (1.5, 1208, 302), (2.1, 1208, 302), (3.6, 900, 700), (4.2, 900, 700), (5.6, 1500, 900), (dur, 1500, 900)]
    clicks = [(1.8, 1208, 302), (3.95, 900, 700)]
    reacts = [1.9, 4.05]            # UI change times (the frame after each click at 30 fps)

    def pos(t):
        for a, b in zip(way, way[1:]):
            if a[0] <= t <= b[0]:
                u = (t - a[0]) / max(1e-6, b[0] - a[0])
                u = 0.5 - 0.5 * math.cos(math.pi * u)           # sine in-out between waypoints
                return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
        return way[-1][1], way[-1][2]
    n = int(round(dur * fps))
    return {'fps': fps, 'size': [W, H], 'tip': [pos(k / fps) for k in range(n)], 'clicks': clicks, 'reacts': reacts}


def _font(px, bold=False):
    from PIL import ImageFont
    for nme in (('arialbd.ttf',) if bold else ('arial.ttf',)) + ('DejaVuSans.ttf',):
        for d in ('C:/Windows/Fonts/', '/usr/share/fonts/truetype/dejavu/', '/Library/Fonts/'):
            try:
                return ImageFont.truetype(d + nme, px)
            except OSError:
                pass
    return ImageFont.load_default()


def fixture_ui(state, W=1920, H=1080):
    """A fictional console (Acme): sidebar, header, a table, two buttons. state: 0 base, 1 panel open, 2 row highlighted."""
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (W, H), '#f4f6f8')
    d = ImageDraw.Draw(im)
    F, FB = _font(20), _font(22, True)
    d.rectangle([0, 0, W, 64], fill='#1f2a37')
    d.text((28, 18), 'Acme Console', font=FB, fill='#ffffff')
    d.rectangle([0, 64, 260, H], fill='#ffffff')
    for i, label in enumerate(['Overview', 'Orders', 'Regions', 'Deliveries', 'Settings']):
        d.text((32, 100 + i * 48), label, font=F, fill='#30404f')
    d.rectangle([320, 110, 1860, 150], fill='#e7ebef')
    d.text((336, 118), 'Deliveries by region — week 36', font=FB, fill='#1f2a37')
    for r in range(10):
        y = 190 + r * 60
        fill = '#fff4e5' if (state == 2 and abs(y + 30 - 700) < 35) else ('#ffffff' if r % 2 == 0 else '#f7f9fb')
        d.rectangle([320, y, 1860, y + 60], fill=fill, outline='#e0e4e8')
        d.text((340, y + 18), 'Region %02d' % (r + 1), font=F, fill='#30404f')
        d.text((900, y + 18), '%d shipments' % (420 + r * 37), font=F, fill='#30404f')
        d.text((1400, y + 18), '%d %% on time' % (97 - r), font=F, fill='#30404f')
    d.rounded_rectangle([1120, 280, 1300, 326], radius=6, fill='#2457c5')
    d.text((1150, 292), 'Filter', font=FB, fill='#ffffff')
    d.rounded_rectangle([1330, 280, 1510, 326], radius=6, fill='#ffffff', outline='#2457c5', width=2)
    d.text((1360, 292), 'Export', font=FB, fill='#2457c5')
    if state == 1:
        d.rounded_rectangle([1120, 340, 1560, 560], radius=8, fill='#ffffff', outline='#c9d2dc', width=2)
        for i, s in enumerate(['Late only', 'Missed target', 'All regions', 'Last 4 weeks']):
            d.rectangle([1144, 366 + i * 44, 1164, 386 + i * 44], outline='#2457c5', width=2)
            d.text((1180, 364 + i * 44), s, font=F, fill='#30404f')
    return im


def fixture_arrow(hgt=24):
    """The fixture's OWN pointer (different proportions from the templates: a fatter, shorter-tailed arrow)."""
    from PIL import Image, ImageDraw
    ss = 4
    w, h = int(hgt * 0.7) + 4, hgt + 4
    im = Image.new('RGBA', (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    Hh = float(hgt)
    pts = [(2, 2), (2, 2 + 0.80 * Hh), (2 + 0.26 * Hh, 2 + 0.64 * Hh), (2 + 0.40 * Hh, 2 + 0.92 * Hh), (2 + 0.52 * Hh, 2 + 0.86 * Hh),
           (2 + 0.38 * Hh, 2 + 0.58 * Hh), (2 + 0.66 * Hh, 2 + 0.58 * Hh)]
    poly = [(x * ss, y * ss) for x, y in pts]
    d.polygon(poly, fill=(255, 255, 255, 255))
    d.line(poly + [poly[0]], fill=(0, 0, 0, 255), width=int(1.4 * ss))
    return im.resize((w, h), Image.BOX)


def make_fixture_video(out_mp4, truth, state_times):
    """Pipe RGB frames into ffmpeg: fixture UI (3 states) + the moving pointer. Returns the path."""
    W, H = truth['size']
    fps = truth['fps']
    uis = [fixture_ui(s, W, H) for s in range(3)]
    arrow = fixture_arrow(24)
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(fps),
           '-i', '-', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p', out_mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for k, (x, y) in enumerate(truth['tip']):
        t = k / float(fps)
        state = 0
        for s, ts in enumerate(state_times, 1):
            if t >= ts:
                state = s
        fr = uis[state].copy()
        fr.paste(arrow, (int(round(x)) - 2, int(round(y)) - 2), arrow)
        p.stdin.write(fr.tobytes())
    p.stdin.close()
    err = p.stderr.read().decode('utf-8', 'replace')
    if p.wait() != 0:
        raise SystemExit('ffmpeg fixture encode failed: ' + err[-300:])
    return out_mp4


def geometry_check():
    """Paste each template (as drawn) onto a flat frame at a known top-left; the returned hotspot must land within 0.75 px."""
    bank = template_bank()
    worst = 0.0
    for T, (hgt, mk) in zip(bank, [(h, arrow_template) for h in DEFAULTS['arrow_heights']] + [(h, ibeam_template) for h in DEFAULTS['ibeam_heights']] + [(h, hand_template) for h in DEFAULTS['hand_heights']]):
        (g, _), hot, kind = mk(hgt)
        frame = np.full((200, 300), 0.5, dtype=np.float32)
        y0, x0 = 77, 123
        frame[y0:y0 + g.shape[0], x0:x0 + g.shape[1]] = g
        gx, gy = gradients(frame * 255)
        s, py, px, k, _, _ = best_match(gx, gy, [T])
        worst = max(worst, math.hypot(py - (y0 + hot[1]), px - (x0 + hot[0])))
    return worst


def selftest(keep_dir=None):
    import time
    t_start = time.time()
    tmp = keep_dir or tempfile.mkdtemp(prefix='cursor_track_')
    os.makedirs(tmp, exist_ok=True)
    geo = geometry_check()
    truth = fixture_truth()
    video = make_fixture_video(os.path.join(tmp, 'fixture.mp4'), truth, truth['reacts'])
    t_fix = time.time()
    W, H, src_fps, dur = probe(video)
    fps = pick_fps(src_fps, 'auto')
    dw = decode_width(W)
    frames = list(decode_frames(video, dw, fps))        # decoded once, tracked twice (determinism)
    t_dec = time.time()
    events, stats = track(frames, fps, (W, H), dw)
    t_trk = time.time()
    # hit-rate: analysis frame n at t = n/fps IS source frame round(t * src_fps) (exact decimation)
    hits, errs = 0, []
    for m in (e for e in events if e['type'] == 'move'):
        k = int(round(m['t'] * truth['fps']))
        if k >= len(truth['tip']):
            continue
        tx, ty = truth['tip'][k]
        err = math.hypot(m['x'] - tx, m['y'] - ty)
        errs.append(err)
        hits += err <= 6.0
    n_frames = stats['frames']
    hit_rate = hits / float(max(1, n_frames))               # untracked frames count as misses
    clicks = [e for e in events if e['type'] == 'down']
    click_ok = len(clicks) == len(truth['clicks']) and all(any(abs(c['t'] - tc) <= 0.25 and math.hypot(c['x'] - cx, c['y'] - cy) <= 12
                                                               for c in clicks) for tc, cx, cy in truth['clicks'])
    ev_path = os.path.join(tmp, 'events.jsonl')
    write_events(ev_path, events, {'tool': 'cursor_track', 'version': VERSION, 'source': [W, H], 'fps': fps,
                                   'decode': [dw, int(round(dw * H / W / 2.0)) * 2], 'accept': DEFAULTS['accept']})
    events2, _ = track(frames, fps, (W, H), dw)
    same = json.dumps(events, sort_keys=True) == json.dumps(events2, sort_keys=True)
    rep = {'phase_s': {'fixture': round(t_fix - t_start, 1), 'decode': round(t_dec - t_fix, 1), 'track': round(t_trk - t_dec, 1), 'track2': round(time.time() - t_trk, 1)},
           'geometry_worst_px': round(geo, 3), 'frames': n_frames, 'tracked': stats['tracked'], 'hit_rate_6px': round(hit_rate, 4),
           'median_err_px': round(float(np.median(errs)) if errs else 99, 2), 'p95_err_px': round(float(np.percentile(errs, 95)) if errs else 99, 2),
           'clicks_found': [(c['t'], c['x'], c['y'], c['conf']) for c in clicks], 'clicks_truth': truth['clicks'], 'clicks_ok': click_ok,
           'deterministic': same, 'mean_conf': stats['mean_conf'], 'kinds': stats['kinds'], 'events': ev_path, 'video': video,
           'seconds': round(time.time() - t_start, 1)}
    ok = geo <= 0.75 and hit_rate >= 0.95 and click_ok and same
    rep['PASS'] = ok
    print(json.dumps(rep, indent=1))
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description='Recover pointer path + clicks from a screen recording (no telemetry). JSON in / JSON out.')
    ap.add_argument('video', nargs='?', help='recording (mp4/mov); macOS variable-frame-rate tapes are fine')
    ap.add_argument('--out', help='events.jsonl to write (default: beside the video)')
    ap.add_argument('--fps', default=DEFAULTS['fps'], help='analysis rate (default auto: source rate / smallest k that brings it <= 15)')
    ap.add_argument('--width', default='auto', help='decode width in px (default auto = 0.64 x the source width, so a 19 px OS pointer stays >= 12 px)')
    ap.add_argument('--accept', type=float, default=DEFAULTS['accept'], help='NCC accept threshold for acquisition (default 0.60)')
    ap.add_argument('--start', type=float, help='seconds into the tape to start')
    ap.add_argument('--duration', type=float, help='seconds to analyse')
    ap.add_argument('--sheet', help='write a 12-frame review sheet (jpg) with detected positions drawn')
    ap.add_argument('--config', help='JSON file overriding DEFAULTS keys')
    ap.add_argument('--selftest', action='store_true', help='synthetic 6 s tape: hit-rate >= 95 %% within 6 px, 2 clicks, deterministic twice')
    ap.add_argument('--keep', help='(selftest) directory to keep the fixture video and events in')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.keep)
    if not a.video:
        ap.print_help()
        return 2
    if not os.path.exists(a.video):
        print('no such file: ' + a.video, file=sys.stderr)
        return 2
    cfg = dict(DEFAULTS)
    if a.config:
        cfg.update(json.load(open(a.config, encoding='utf-8')))
    cfg['accept'] = a.accept
    if a.accept != DEFAULTS['accept'] and not a.config:
        cfg['accept_local'] = max(0.2, a.accept - 0.10)
    W, H, src_fps, dur = probe(a.video)
    fps = pick_fps(src_fps, a.fps)
    dw = decode_width(W, a.width, cfg)
    cfg['width'] = dw
    out = a.out or os.path.splitext(a.video)[0] + '.events.jsonl'
    frames = decode_frames(a.video, dw, fps, a.start, a.duration)
    events, stats = track(frames, fps, (W, H), dw, cfg, progress=lambda k, t: print('  frame %d  t=%.1f' % (k, t), file=sys.stderr))
    meta = {'tool': 'cursor_track', 'version': VERSION, 'source': [W, H], 'source_fps': round(src_fps, 3), 'fps': fps,
            'decode': [dw, int(round(dw * H / W / 2.0)) * 2], 'accept': cfg['accept'], 'accept_local': cfg['accept_local'],
            'start': a.start or 0.0, 'duration': a.duration}
    write_events(out, events, meta)
    rep = dict(stats, out=out, meta=meta)
    if a.sheet:
        rep['sheet'] = sheet(a.video, events, a.sheet, (W, H))
    findings = []
    if stats['tracked_frac'] < 0.6:
        findings.append('only %.0f %% of frames tracked: try --width 1280, a lower --accept, or record_events.py next time' % (100 * stats['tracked_frac']))
    rep['findings'] = findings
    print(json.dumps(rep, indent=1, sort_keys=True))
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
