# -*- coding: utf-8 -*-
"""idle_detect.py — find the dead air in a product recording and propose the cuts, speed ramps and caret-follows
that make it vanish, without hand-timing a single span.

    python tools/idle_detect.py RECORDING [--out idle.json] [--t0 S] [--t1 S] [--sheet idle.png] [--json]
    python tools/idle_detect.py RECORDING --config thresholds.json      (JSON in: override any threshold below)
    python tools/idle_detect.py --make-fixture fixture.mp4              (synthetic Acme UI: idle, spinner, typing, scroll, page)
    python tools/idle_detect.py --selftest

    exit 0 = analysed, nothing to fix   exit 1 = dead air found (proposals written)   exit 2 = usage / decoder error

THE METHOD, FROM FIRST PRINCIPLES
A screen recording is a sequence of frames; what a viewer experiences as "nothing is happening" is a stretch where
consecutive frames are nearly identical. So the whole analysis rests on one number per frame — the CHANGE ENERGY:
decode the recording at 320x180 and 10 fps (ffmpeg `fps=10,scale=320:180`, grey), box-blur each frame 3x3 (so
single-pixel compression noise and sub-pixel anti-aliasing do not count as change), and take the mean absolute
difference to the previous blurred frame, in 0..255 grey levels. 320x180 is the grid for a 1080p source; the
grid keeps 6 source pixels per analysis pixel (clamped to 320..640 wide), so a 2426- or 3160-wide retina capture
is analysed at 400x210 / 520x310 and its UI is not shrunk out of existence (--density 4 for very small fonts).
Measured on three real product recordings (1920x1080@30, 2426x1282 VFR, 3160x1904 VFR; 409 s in all):
a static screen with a blinking caret or a wandering pointer measures 0.00-0.11 (median 0.01); a scroll of a
mostly-white page 0.25-3.2 (median 1.4; px/s 20-1110); a visible UI action (menu, dialog, panel) 0.6-12;
a full page change 36-158. The thresholds below sit in the gaps between those bands.

Five kinds of span are then recognised from that energy and from WHERE the change is:

  (a) idle      energy < 0.6 for >= 1.5 s. The 320x180 frame has 57 600 pixels; a change worth 0.6 mean grey is
                ~140 pixels flipping fully from black to white — more than a caret (2x24 px at 1080p becomes
                0.3x4 px here) or a pointer, less than any widget a viewer would notice.
  (b) spinner   while the frame is otherwise idle, a SMALL region keeps changing: the per-cell energy (10x10 px
                cells, 32x18 grid) is above 1.5 in cells covering <= 6 % of the frame, and that region is active
                in >= 50 % of frames (a caret blink is active in ~20 %, which is how it stays "idle").
                A second decode of just that window crops the region, removes its temporal mean and correlates
                frame k with frame k+L: a rotating/pulsing indicator shows an autocorrelation PEAK at its period,
                L in 0.3-2.0 s (lags 3-20 at 10 fps), coefficient >= 0.35. A progress bar is not periodic but its
                mean brightness drifts monotonically (|corr(time, brightness)| >= 0.6) — tagged sub:"progress".
  (c) typing    the active cells form a NARROW HORIZONTAL BAND (<= 3 cell rows = 30 px here = 16 % of the height,
                >= 3 cells wide), the band changes at 2-12 Hz (active frames per second; 10 fps caps the measure
                at 10), and the x-centroid of the change drifts rightwards (corr(time, x) >= 0.5 — a caret moves
                one way). The second decode gives the caret path: the rightmost changed column per frame.
  (d) scroll    the dominant VERTICAL SHIFT between frames, from row-profile cross-correlation: average each row
                of the blurred frame over the columns that changed (so a static sidebar does not vote), then
                find the shift s in -60..60 px that maximises the Pearson correlation q[y] ~ p[y+s] over the rows
                that changed, refined to half pixels. Repeating table rows make s and s ± row-period score
                alike, so among near-equal peaks the one nearest the previous frame's shift wins. Accepted when
                corr >= 0.85 and clearly better than the no-shift correlation (+0.05); same-direction wheel
                steps <= 0.5 s apart are one scroll. px/s is given in SOURCE pixels (shift x H/180 x 10);
                positive = scrolled down; a run whose net speed is under 20 px/s (a hunting hand) is not a
                scroll. The gate is energy >= 0.15, not 0.6: a slow scroll of a white page measures 0.25-0.6
                and must still be a scroll, not idle.
  (e) page      energy > 25 and more than 40 % of the cells changed by > 12 — a hard-cut candidate. A fast scroll
                can also score that high, so the scroll test is run first and wins when it fits.

Spans are contiguous runs of per-frame labels (scroll runs tolerate a one-frame stutter; typing runs tolerate pauses
up to 0.6 s). Idle is the complement of spinner/typing inside each quiet run, so a 20 s wait with a 3 s spinner in
the middle becomes idle / spinner / idle, each with its own proposal.

PROPOSALS (what the editor pastes, all in recording seconds; `lane` and `map` are clip-local to the analysed window):
  idle >= 4 s      -> cut: drop [t0+0.5, t1-0.5]        idle 1.5-4 s -> ramp 6x
  spinner          -> ramp 4x + a "working" caption hook (proposals.captions)
  typing           -> ramp 1.6x + caret_follow {t0,t1,box,caret:[[t,x],...]} for the camera
  scroll           -> keep 1x when |px/s| <= 400, else 2x (a scroll above 400 px/s at 1x reads as a blur anyway)
  page (<= 0.3 s)  -> hard-cut candidate at t0
  proposals.lane   [[t, rate], ...] — the speed-ramp lane footage.js accepts as play.rate (lib/vfx.js VFX.ramp:
                   0.1..10, log interpolation); 0.25 s eases on both sides of every ramp; cuts are NOT in the lane
  proposals.map    [[dt, u], ...] — film seconds since play.at -> clip fraction 0..1, piecewise linear, drops as
                   vertical steps; wire as play: { at, map: t => interp(MAP, t - at) }.

Determinism: ffmpeg decodes identically run to run, numpy arithmetic is deterministic, every float is rounded to
3 decimals, no wall-clock enters the output. `--selftest` renders the synthetic fixture, analyses it twice and
diffs the JSON. Memory stays flat on long recordings: pass 1 streams frames and keeps only per-frame features;
pass 2 re-decodes just the candidate windows (<= 60 s each).

CALIBRATION (read-only, three real recordings; nothing from them is stored here): 78-97 % of frames were quiet;
the tool proposed saving 74-108 s per recording (58-79 %). Typing at 6 Hz in a 3160-wide capture was found with
its caret path; typing at ~2 chars/s in a ~10 px font on a 2426-wide capture was NOT (each glyph scores 1.8-3.0,
the caret-blink exclusion also removes 2 Hz events) — that is the known floor, see --density. A title fade-in and
a graph animating in were rejected as "progress" by the leading-edge rule. See references/idle-ramps.md.

Requires numpy, scipy, Pillow, ffmpeg/ffprobe on PATH. Python 3.10+.
"""
import argparse, json, math, os, shutil, subprocess, sys, tempfile

import numpy as np
from scipy import ndimage

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VERSION = 1

# ---------------------------------------------------------------------------------------------- measured thresholds
DEFAULTS = {
    'aw': 320, 'ah': 180, 'fps': 10.0, 'blur': 3, 'cell': 10,
    'density': 6.0, 'aw_min': 320, 'aw_max': 640,        # source px per analysis px (1920 → 320); retina/4K captures grow the grid
    'threads': 2,
    'idle_energy': 0.6, 'idle_min_s': 1.5, 'cut_min_s': 4.0, 'cut_pad_s': 0.5,
    'page_energy': 25.0, 'page_cell': 12.0, 'page_frac': 0.40, 'page_cut_max_s': 0.3,
    'cell_active': 1.5, 'rest_quiet': 0.3, 'sustain_half': 5, 'sustain_min': 3,
    'spin_area': 0.06, 'spin_lag_s': [0.3, 2.0], 'spin_peak': 0.35, 'spin_duty': 0.5, 'spin_min_s': 1.0,
    'progress_corr': 0.6, 'progress_edge': 0.5,
    'type_rows': 3, 'type_cols': 3, 'type_hz': [2.0, 12.0], 'type_drift': 0.5, 'type_gap_s': 0.6, 'edge_gap_s': 0.3, 'type_min_s': 0.8,
    'slow_gap_s': 1.5, 'slow_min_s': 3.0, 'slow_min_events': 6, 'slow_drift': 0.6, 'slow_right': 0.7,
    'scroll_min_pxs': 20.0,
    'scroll_energy': 0.15, 'scroll_corr': 0.85, 'scroll_gain': 0.05, 'scroll_max_px': 60, 'scroll_min_s': 0.3,
    'scroll_keep_pxs': 400.0, 'scroll_fast_rate': 2.0, 'scroll_merge_s': 0.5,
    'rate_idle': 6.0, 'rate_spinner': 4.0, 'rate_typing': 1.6, 'ease_s': 0.25, 'rate_max': 10.0, 'rate_min': 0.1,
    'pass2_max_s': 60.0,
}
KINDS = ('idle', 'spinner', 'typing', 'scroll', 'page')
PALETTE = {'navy': (8, 42, 52), 'navy2': (32, 74, 86), 'ink': (233, 243, 249), 'cream': (236, 222, 195),
           'coral': (229, 107, 94), 'mint': (129, 169, 171), 'gold': (232, 200, 116)}
KIND_RGB = {'idle': PALETTE['mint'], 'spinner': PALETTE['gold'], 'typing': PALETTE['cream'],
            'scroll': (120, 170, 220), 'page': PALETTE['coral']}


def r3(x):
    return float(round(float(x) + 0.0, 3))


class UsageError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- ffmpeg front end
def probe(path):
    if not os.path.isfile(path):
        raise UsageError('no such recording: %s' % path)
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration',
           '-of', 'json', path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise UsageError('ffprobe failed: %s' % (getattr(e, 'stderr', None) or e))
    j = json.loads(out)
    st = (j.get('streams') or [{}])[0]
    return {'width': int(st.get('width') or 0), 'height': int(st.get('height') or 0),
            'duration': float((j.get('format') or {}).get('duration') or 0.0)}


def decode(path, t0, dur, cfg):
    """Yield grey uint8 frames (ah, aw) at cfg.fps, starting at recording second t0 (frames at t0 + k/fps)."""
    aw, ah = cfg['aw'], cfg['ah']
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-threads', str(int(cfg['threads']))]
    if t0 > 0:
        cmd += ['-ss', '%.3f' % t0]
    cmd += ['-i', path]
    if dur is not None:
        cmd += ['-t', '%.3f' % dur]
    cmd += ['-an', '-sn', '-vf', 'fps=%g,scale=%d:%d:flags=area,format=gray' % (cfg['fps'], aw, ah),
            '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    n = aw * ah
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise UsageError('ffmpeg not runnable: %s' % e)
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(ah, aw)
    finally:
        p.stdout.close()
        err = p.stderr.read().decode('utf-8', 'replace').strip()
        p.wait()
        if p.returncode not in (0, None) and err:
            raise UsageError('ffmpeg: %s' % err[:300])


def blur(frame, cfg):
    return ndimage.uniform_filter(frame.astype(np.float32), size=cfg['blur'], mode='nearest')


# ---------------------------------------------------------------------------------------------- pass 1 features
def est_shift(prevB, B, D, cfg, prior=0):
    """Dominant vertical shift between two blurred frames via row-profile cross-correlation over the changed
    columns/rows. Returns (shift_px, corr_at_shift, corr_at_zero); shift > 0 = content moved up (scrolled down).
    Repeating rows (a table with 48 px rows, alternating shading) make the correlation periodic: s and s ± period
    score alike. Among candidates within 0.08 of the best, the one nearest `prior` (the previous frame's shift,
    else 0) wins — a scroll does not jump by a row period between two frames 0.1 s apart."""
    ah = B.shape[0]
    colact = D.mean(axis=0) > 1.0
    rowact = D.mean(axis=1) > 1.0
    if colact.sum() < 8 or rowact.sum() < 12:
        return 0, 0.0, 0.0
    p = prevB[:, colact].mean(axis=1)
    q = B[:, colact].mean(axis=1)
    if q[rowact].std() < 0.5:
        return 0, 0.0, 0.0
    S = int(cfg['scroll_max_px'])
    shifts = np.arange(-S, S + 1)
    y = np.arange(ah)
    idx = y[:, None] + shifts[None, :]
    valid = (idx >= 0) & (idx < ah) & rowact[:, None]
    P = p[np.clip(idx, 0, ah - 1)]
    Q = np.broadcast_to(q[:, None], P.shape)
    n = valid.sum(axis=0).astype(np.float64)
    nz = np.maximum(n, 1.0)
    mq = (Q * valid).sum(axis=0) / nz
    mp = (P * valid).sum(axis=0) / nz
    dq = (Q - mq) * valid
    dp = (P - mp) * valid
    cov = (dq * dp).sum(axis=0)
    r = cov / np.sqrt((dq * dq).sum(axis=0) * (dp * dp).sum(axis=0) + 1e-6)
    r[n < 12] = -1.0
    rmax = float(r.max())
    cands = np.where(r >= rmax - 0.08)[0]
    best = int(cands[np.argmin(np.abs(shifts[cands] - prior) * 1000 + np.abs(shifts[cands]))])
    s0 = int(shifts[best])
    # sub-pixel: a 7.5 px shift fits neither 7 nor 8 well; try the half steps with an interpolated profile
    bs, br = float(s0), float(r[best])
    for sf in (s0 - 0.5, s0 + 0.5):
        rf = _pearson_shift(p, q, rowact, sf)
        if rf > br:
            bs, br = sf, rf
    return bs, br, float(r[S])


def _pearson_shift(p, q, rowact, s):
    """Pearson correlation of q[y] with p[y+s] (fractional s, linear interpolation) over the active rows."""
    ah = len(p)
    y = np.arange(ah)
    f = s - math.floor(s); i0 = y + int(math.floor(s)); i1 = i0 + 1
    valid = rowact & (i0 >= 0) & (i1 < ah)
    if valid.sum() < 12:
        return -1.0
    ps = (1 - f) * p[np.clip(i0, 0, ah - 1)] + f * p[np.clip(i1, 0, ah - 1)]
    a, b = q[valid], ps[valid]
    a = a - a.mean(); b = b - b.mean()
    return float((a * b).sum() / math.sqrt((a * a).sum() * (b * b).sum() + 1e-6))


def pass1(path, t0, dur, cfg):
    aw, ah, c = cfg['aw'], cfg['ah'], cfg['cell']
    gh, gw = ah // c, aw // c
    E, CELLS, SHIFT, CORR, CORR0, PAGE = [], [], [], [], [], []
    prev = None
    nframes = 0
    prior = 0
    for fr in decode(path, t0, dur, cfg):
        nframes += 1
        B = blur(fr, cfg)
        if prev is None:
            prev = B
            continue
        D = np.abs(B - prev)
        e = float(D.mean())
        cell = D[:gh * c, :gw * c].reshape(gh, c, gw, c).mean(axis=(1, 3))
        sh, cr, c0 = (0.0, 0.0, 0.0)
        if e >= cfg['scroll_energy']:
            sh, cr, c0 = est_shift(prev, B, D, cfg, prior)
        prior = sh if (abs(sh) >= 0.5 and cr >= cfg['scroll_corr']) else 0.0
        E.append(e); CELLS.append(cell.astype(np.float32)); SHIFT.append(sh); CORR.append(cr); CORR0.append(c0)
        PAGE.append(e > cfg['page_energy'] and float((cell > cfg['page_cell']).mean()) > cfg['page_frac'])
        prev = B
    if nframes < 3:
        raise UsageError('recording too short or undecodable (%d frames at %g fps)' % (nframes, cfg['fps']))
    return {'energy': np.array(E, dtype=np.float64), 'cells': np.stack(CELLS), 'shift': np.array(SHIFT, dtype=np.float64),
            'corr': np.array(CORR), 'corr0': np.array(CORR0), 'page': np.array(PAGE, dtype=bool), 'nframes': nframes}


def label_frames(F, cfg):
    """0 quiet, 1 motion, 2 scroll, 3 page — one label per diff frame (index k = change visible at frame k+1)."""
    n = len(F['energy'])
    lab = np.zeros(n, dtype=np.int8)
    moving = (np.abs(F['shift']) >= 0.5) & (F['corr'] >= F['corr0'] + cfg['scroll_gain']) & (F['energy'] >= cfg['scroll_energy'])
    scroll = moving & (F['corr'] >= cfg['scroll_corr'])
    lab[F['energy'] >= cfg['idle_energy']] = 1
    lab[F['page']] = 3
    lab[scroll] = 2
    # a one-frame stutter inside a scroll stays a scroll
    for k in range(1, n - 1):
        if lab[k] != 2 and lab[k - 1] == 2 and lab[k + 1] == 2 and np.sign(F['shift'][k - 1]) == np.sign(F['shift'][k + 1]):
            lab[k] = 2
    # the first/last frame of a scroll (acceleration, the fractional-shift onset) joins it when it nearly qualifies
    nearly = moving & (F['corr'] >= cfg['scroll_corr'] - 0.1) & (lab == 1)
    for a, b in runs(lab == 2):
        if a > 0 and nearly[a - 1]:
            lab[a - 1] = 2
        if b + 1 < n and nearly[b + 1]:
            lab[b + 1] = 2
    # mouse-wheel steps: same-direction scroll bursts <= scroll_merge_s apart are one scroll (never across a page change)
    mergef = int(round(cfg['scroll_merge_s'] * cfg['fps']))
    R = runs(lab == 2)
    for (a1, b1), (a2, b2) in zip(R, R[1:]):
        gap = lab[b1 + 1:a2]
        if 0 < len(gap) <= mergef and not (gap == 3).any() and np.sign(np.median(F['shift'][a1:b1 + 1])) == np.sign(np.median(F['shift'][a2:b2 + 1])):
            lab[b1 + 1:a2] = 2
    # scroll runs shorter than scroll_min_s are plain motion
    minf = int(round(cfg['scroll_min_s'] * cfg['fps']))
    for a, b in runs(lab == 2):
        if b - a + 1 < minf:
            lab[a:b + 1] = 1
    return lab


def runs(mask):
    """[(a, b)] inclusive index runs where mask is True."""
    out, a = [], None
    for i, v in enumerate(mask):
        if v and a is None:
            a = i
        if not v and a is not None:
            out.append((a, i - 1)); a = None
    if a is not None:
        out.append((a, len(mask) - 1))
    return out


# ---------------------------------------------------------------------------------------------- pass 2 (windows)
def periodicity(patches, lo, hi):
    """Autocorrelation of the mean-removed patch sequence; returns (best_lag, coefficient) for a LOCAL peak in lo..hi."""
    Z = patches - patches.mean(axis=0, keepdims=True)
    Z = Z.reshape(len(Z), -1)
    norms = np.sqrt((Z * Z).sum(axis=1)) + 1e-6
    m = len(Z)
    rs = {}
    for L in range(1, min(hi + 2, m - 2) + 1):
        num = (Z[:-L] * Z[L:]).sum(axis=1)
        rs[L] = float((num / (norms[:-L] * norms[L:])).mean())
    best, bestr = 0, -1.0
    for L in range(lo, hi + 1):
        if L not in rs:
            break
        r = rs[L]
        if r > bestr and r >= rs.get(L - 1, -1) and r >= rs.get(L + 1, -1):
            best, bestr = L, r
    return best, bestr


def classify_micro(path, win_t0, F, lab, a, b, cfg, info, dbg=None):
    """A micro-active segment [a, b] (diff indices) inside a quiet run → span dict or None (stays idle)."""
    fps, c = cfg['fps'], cfg['cell']
    gh, gw = F['cells'].shape[1], F['cells'].shape[2]
    cells = F['cells'][a:b + 1]
    act = sustained(cells > cfg['cell_active'], cfg)        # geometry from the busy cells only: a blinking caret
    anyact = act.any(axis=(1, 2))                           # elsewhere must not stretch a spinner's box
    n = b - a + 1
    duty = float(anyact.mean())
    U = act.any(axis=0)
    if not U.any():
        return None
    area = float(U.sum()) / (gh * gw)
    rows = np.where(U.any(axis=1))[0]; cols = np.where(U.any(axis=0))[0]
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())
    # rest of the frame quiet?
    mask = np.zeros((gh, gw), dtype=bool); mask[r0:r1 + 1, c0:c1 + 1] = True
    rest = cells[:, ~mask].mean(axis=1) if (~mask).any() else np.zeros(n)
    if float((rest < cfg['rest_quiet']).mean()) < 0.9:
        return None
    sx, sy = info['width'] / cfg['aw'], info['height'] / cfg['ah']
    box = [r3(c0 * c * sx), r3(r0 * c * sy), r3((c1 - c0 + 1) * c * sx), r3((r1 - r0 + 1) * c * sy)]
    t_abs = lambda k: win_t0 + (k + 1) / fps          # diff index k ↔ change visible at frame k+1
    dur_s = n / fps
    # ---- typing: narrow horizontal band, 2-12 Hz, rightward drift
    if (r1 - r0 + 1) <= cfg['type_rows'] and (c1 - c0 + 1) >= cfg['type_cols'] and dur_s >= cfg['type_min_s']:
        hz = duty * fps
        ks = np.where(anyact)[0]
        if len(ks) >= 4 and cfg['type_hz'][0] <= hz <= cfg['type_hz'][1]:
            cx = np.array([np.average(np.where(act[k].any(axis=0))[0]) for k in ks])
            drift = float(np.corrcoef(ks.astype(float), cx)[0, 1]) if cx.std() > 1e-6 else 0.0
            if dbg is not None:
                dbg.append('  %.1f-%.1f band rows %d cols %d hz %.1f drift %.2f' % (win_t0 + a / fps, t_abs(b), r1 - r0 + 1, c1 - c0 + 1, hz, drift))
            if drift >= cfg['type_drift']:
                caret = caret_path(path, win_t0, a, b, r0, r1, cfg, info)
                return {'t0': r3(win_t0 + a / fps), 't1': r3(t_abs(b)), 'kind': 'typing', 'confidence': r3(min(1.0, drift)),
                        'box': box, 'rate_hz': r3(hz), 'caret': caret}
    # ---- spinner / progress: small region, high duty, periodic or monotone
    if area <= cfg['spin_area'] and duty >= cfg['spin_duty'] and dur_s >= cfg['spin_min_s']:
        P = patches(path, win_t0, a, b, r0, r1, c0, c1, cfg)
        if P is not None and len(P) >= 8:
            lo = max(2, int(round(cfg['spin_lag_s'][0] * fps))); hi = int(round(cfg['spin_lag_s'][1] * fps))
            L, r = periodicity(P, lo, hi)
            if L and r >= cfg['spin_peak']:
                return {'t0': r3(win_t0 + a / fps), 't1': r3(t_abs(b)), 'kind': 'spinner', 'confidence': r3(min(1.0, r)),
                        'box': box, 'period_s': r3(L / fps)}
            # progress bar: only its LEADING EDGE changes (few cells per frame against a union that grows along x,
            # brightness drifting one way). A fade-in lights every cell every frame and is not "working".
            bright = P.reshape(len(P), -1).mean(axis=1)
            per_frame = float(act.sum(axis=(1, 2))[anyact].mean()) / max(1, U.sum())
            ks = np.where(anyact)[0]
            cx = np.array([np.average(np.where(act[k].any(axis=0))[0]) for k in ks])
            drift = abs(float(np.corrcoef(ks.astype(float), cx)[0, 1])) if (len(ks) >= 4 and cx.std() > 1e-6) else 0.0
            if bright.std() > 1e-6 and per_frame <= cfg['progress_edge'] and drift >= cfg['type_drift']:
                mono = float(np.corrcoef(np.arange(len(P), dtype=float), bright)[0, 1])
                if abs(mono) >= cfg['progress_corr']:
                    return {'t0': r3(win_t0 + a / fps), 't1': r3(t_abs(b)), 'kind': 'spinner', 'sub': 'progress',
                            'confidence': r3(0.25 + 0.5 * abs(mono)), 'box': box}
            if dbg is not None:
                dbg.append('  %.1f-%.1f small region, no period (peak %.2f @ %d), edge %.2f drift %.2f → idle' % (win_t0 + a / fps, t_abs(b), r, L, per_frame, drift))
    elif dbg is not None:
        dbg.append('  %.1f-%.1f area %.1f%% rows %d cols %d duty %.2f → idle' % (win_t0 + a / fps, t_abs(b), 100 * area, r1 - r0 + 1, c1 - c0 + 1, duty))
    return None


def slow_typing(path, win_t0, F, a, b, free, cfg, info, dbg=None):
    """Clusters of leftover single-frame events (gaps <= slow_gap_s) that stay within type_rows rows, touch >= 3
    distinct columns, last >= slow_min_s and drift rightwards (corr(t, x) >= slow_drift) → typing spans."""
    fps, c = cfg['fps'], cfg['cell']
    ev = np.where(free)[0]
    if len(ev) < cfg['slow_min_events']:
        return []
    gapf = int(round(cfg['slow_gap_s'] * fps))
    clusters, s0 = [], 0
    for i in range(1, len(ev) + 1):
        if i == len(ev) or ev[i] - ev[i - 1] > gapf:
            clusters.append(ev[s0:i]); s0 = i
    out = []
    sx, sy = info['width'] / cfg['aw'], info['height'] / cfg['ah']
    for ks in clusters:
        if len(ks) < cfg['slow_min_events'] or (ks[-1] - ks[0] + 1) / fps < cfg['slow_min_s']:
            continue
        act = F['cells'][a + ks] > cfg['cell_active']
        # the dominant text line: the 10th-90th percentile band of per-event rows (a stray pointer event or the
        # field above does not widen it); events outside the band are dropped before the drift test
        erow = np.array([np.average(np.where(act[i].any(axis=1))[0]) for i in range(len(ks))])
        lo, hi = int(np.floor(np.percentile(erow, 10))), int(np.ceil(np.percentile(erow, 90)))
        keep = (erow >= lo - 0.5) & (erow <= hi + 0.5)
        ks, act = ks[keep], act[keep]
        if len(ks) >= cfg['slow_min_events']:
            act = act.copy(); act[:, :lo, :] = False; act[:, hi + 1:, :] = False
            nz = act.any(axis=(1, 2)); ks, act = ks[nz], act[nz]
        U = act.any(axis=0) if len(ks) else np.zeros(F['cells'].shape[1:], dtype=bool)
        rows = np.where(U.any(axis=1))[0]; cols = np.where(U.any(axis=0))[0]
        if len(ks) < cfg['slow_min_events'] or rows.max() - rows.min() + 1 > cfg['type_rows'] or len(cols) < cfg['type_cols']:
            if dbg is not None:
                dbg.append('  %.1f-%.1f slow events %d rows %d cols %d → idle' % (win_t0 + (a + ks[0]) / fps, win_t0 + (a + ks[-1] + 1) / fps, len(ks), (rows.max() - rows.min() + 1) if len(rows) else 0, len(cols)))
            continue
        cx = np.array([np.average(np.where(act[i].any(axis=0))[0]) for i in range(len(ks))])
        drift = float(np.corrcoef(ks.astype(float), cx)[0, 1]) if cx.std() > 1e-6 else 0.0
        dx = np.diff(cx); dx = dx[dx != 0]
        right = float((dx > 0).mean()) if len(dx) else 0.0        # share of moves that go right: a typist's hand
        if dbg is not None:
            dbg.append('  %.1f-%.1f slow events %d rows %d cols %d drift %.2f right %.2f' % (win_t0 + (a + ks[0]) / fps, win_t0 + (a + ks[-1] + 1) / fps, len(ks), rows.max() - rows.min() + 1, len(cols), drift, right))
        if drift < cfg['slow_drift'] and right < cfg['slow_right']:
            continue
        drift = max(drift, right)
        ma, mb = int(ks[0]), int(ks[-1])
        r0, r1, c0, c1 = int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())
        box = [r3(c0 * c * sx), r3(r0 * c * sy), r3((c1 - c0 + 1) * c * sx), r3((r1 - r0 + 1) * c * sy)]
        caret = caret_path(path, win_t0, a + ma, a + mb, r0, r1, cfg, info)
        out.append(({'t0': r3(win_t0 + (a + ma) / fps), 't1': r3(win_t0 + (a + mb + 1) / fps), 'kind': 'typing', 'sub': 'slow',
                     'confidence': r3(min(1.0, 0.8 * drift)), 'box': box, 'rate_hz': r3(len(ks) / ((mb - ma + 1) / fps)), 'caret': caret}, (ma, mb)))
    return out


def window_frames(path, win_t0, a, b, cfg):
    """Re-decode the frames behind diff indices a..b (that is frames a..b+1) → list of blurred frames; None if too long."""
    fps = cfg['fps']
    if (b - a + 2) / fps > cfg['pass2_max_s']:
        b = a + int(cfg['pass2_max_s'] * fps) - 2
    t0 = win_t0 + a / fps
    dur = (b - a + 2) / fps + 0.5 / fps
    frames = [blur(fr, cfg) for fr in decode(path, round(t0, 3), round(dur, 3), cfg)]
    return frames[:b - a + 2]


def patches(path, win_t0, a, b, r0, r1, c0, c1, cfg):
    fr = window_frames(path, win_t0, a, b, cfg)
    if len(fr) < 3:
        return None
    c = cfg['cell']
    y0, y1 = max(0, (r0 - 1) * c), min(cfg['ah'], (r1 + 2) * c)
    x0, x1 = max(0, (c0 - 1) * c), min(cfg['aw'], (c1 + 2) * c)
    return np.stack([f[y0:y1, x0:x1] for f in fr])


def caret_path(path, win_t0, a, b, r0, r1, cfg, info):
    """[[t, x_source_px], ...] one sample per 0.5 s: the rightmost column that changed inside the typing band."""
    fr = window_frames(path, win_t0, a, b, cfg)
    if len(fr) < 2:
        return []
    c, fps = cfg['cell'], cfg['fps']
    y0, y1 = r0 * c, min(cfg['ah'], (r1 + 1) * c)
    sx = info['width'] / cfg['aw']
    xs = []
    for k in range(1, len(fr)):
        D = np.abs(fr[k][y0:y1] - fr[k - 1][y0:y1])
        cols = np.where(D.max(axis=0) > 8.0)[0]
        xs.append(float(cols.max()) if len(cols) else None)
    out, step = [], int(round(0.5 * fps))
    for s in range(0, len(xs), step):
        chunk = [x for x in xs[s:s + step] if x is not None]
        if chunk:
            out.append([r3(win_t0 + (a + s + 1) / fps), r3(float(np.median(chunk)) * sx)])
    return out


# ---------------------------------------------------------------------------------------------- spans
def sustained(act, cfg):
    """A cell counts as busy in frame k only if it is also active in >= `sustain_min` of the 10 surrounding frames
    (k-5..k+5). A caret blinking at 1 Hz flips twice a second — 2 of 10 — and so never counts; a spinner (every
    frame) and typing at >= 3 Hz do. This is what keeps a blinking caret 'idle' without a special case."""
    n = len(act)
    if n == 0:
        return act
    half, need = int(cfg['sustain_half']), int(cfg['sustain_min'])
    c = np.cumsum(np.concatenate([np.zeros((1,) + act.shape[1:], dtype=np.int32), act.astype(np.int32)]), axis=0)
    lo = np.clip(np.arange(n) - half, 0, n); hi = np.clip(np.arange(n) + half + 1, 0, n)
    around = c[hi] - c[lo] - act.astype(np.int32)
    return act & (around >= need)


def find_spans(path, win_t0, F, lab, cfg, info, dbg=None):
    fps = cfg['fps']
    n = len(lab)
    spans = []
    sy = info['height'] / cfg['ah']
    t_of = lambda k: r3(win_t0 + (k + 1) / fps)
    for a, b in runs(lab == 3):
        d = (b - a + 1) / fps
        frac = float((F['cells'][a:b + 1] > cfg['page_cell']).mean())
        spans.append({'t0': r3(win_t0 + a / fps), 't1': t_of(b), 'kind': 'page', 'confidence': r3(min(1.0, frac / 0.6) * (1.0 if d <= 0.5 else 0.5)),
                      'energy': r3(F['energy'][a:b + 1].mean())})
    for a, b in runs(lab == 2):
        sh = F['shift'][a:b + 1]
        mv = np.abs(sh) >= 0.5                                # merged wheel-step gaps carry no shift
        sh = sh[mv] if mv.any() else sh
        med = float(np.median(sh))
        inl = sh[np.abs(sh - med) <= 2]                      # 7/8 px alternation averages to the true 7.5
        pxs = float(np.mean(inl if len(inl) else sh)) * sy * fps
        if abs(pxs) < cfg['scroll_min_pxs']:
            lab[a:b + 1] = 1                                  # a hunting hand, not a scroll a viewer would follow
            continue
        conf = float(F['corr'][a:b + 1][mv].mean()) if mv.any() else float(F['corr'][a:b + 1].mean())
        spans.append({'t0': r3(win_t0 + a / fps), 't1': t_of(b), 'kind': 'scroll', 'confidence': r3(conf),
                      'px_per_s': r3(pxs), 'energy': r3(F['energy'][a:b + 1].mean())})
    gapf = int(round(cfg['type_gap_s'] * fps))
    minidle = int(round(cfg['idle_min_s'] * fps))
    for a, b in runs(lab == 0):
        raw = (F['cells'][a:b + 1] > cfg['cell_active']).any(axis=(1, 2))
        act = sustained(F['cells'][a:b + 1] > cfg['cell_active'], cfg).any(axis=(1, 2))
        # micro-active segments on the sustained cells, bridging gaps <= type_gap_s
        micro, s0, last = [], None, None
        for i, v in enumerate(act):
            if v:
                if s0 is None:
                    s0 = i
                elif i - last > gapf:
                    micro.append((s0, last)); s0 = i
                last = i
        if s0 is not None:
            micro.append((s0, last))
        # one hop (no chaining) over raw activity within edge_gap_s of each edge: the last isolated keystroke
        # (0.1-0.3 s after the run) belongs to it; a caret blink 0.5 s away does not
        ext, edgef = [], int(round(cfg['edge_gap_s'] * fps))
        for ma, mb in micro:
            lo = [i for i in range(max(0, ma - edgef), ma) if raw[i]]
            hi = [i for i in range(mb + 1, min(len(raw), mb + edgef + 1)) if raw[i]]
            ext.append((lo[0] if lo else ma, hi[-1] if hi else mb))
        micro = []
        for ma, mb in ext:                                      # merge overlaps created by the extension
            if micro and ma <= micro[-1][1]:
                micro[-1] = (micro[-1][0], max(micro[-1][1], mb))
            else:
                micro.append((ma, mb))
        taken = np.zeros(b - a + 1, dtype=bool)
        for ma, mb in micro:
            if (mb - ma + 1) / fps < min(cfg['type_min_s'], cfg['spin_min_s']):
                continue
            sp = classify_micro(path, win_t0, F, lab, a + ma, a + mb, cfg, info, dbg)
            if sp:
                spans.append(sp); taken[ma:mb + 1] = True
        # slow typing (< 3 chars/s, small fonts): single keystrokes the sustained rule ignores, but which march
        # rightwards along one text line for seconds — a caret blink never leaves its column
        for sp, (ma, mb) in slow_typing(path, win_t0, F, a, b, raw & ~taken, cfg, info, dbg):
            spans.append(sp); taken[ma:mb + 1] = True
        for ia, ib in runs(~taken):
            if ib - ia + 1 >= minidle:
                e = float(F['energy'][a + ia:a + ib + 1].mean())
                conf = min(1.0, (ib - ia + 1) / fps / 3.0) * max(0.2, 1.0 - e / cfg['idle_energy'])
                sp = {'t0': r3(win_t0 + (a + ia) / fps), 't1': t_of(a + ib), 'kind': 'idle', 'confidence': r3(conf), 'energy': r3(e)}
                if act[ia:ib + 1].any():
                    sp['note'] = 'micro-activity (pointer, caret) ignored'
                spans.append(sp)
    spans.sort(key=lambda s: (s['t0'], s['t1']))
    return spans


# ---------------------------------------------------------------------------------------------- proposals
def build_proposals(spans, win_t0, win_t1, cfg):
    cuts, ramps, caret, captions = [], [], [], []
    for s in spans:
        d = s['t1'] - s['t0']
        k = s['kind']
        if k == 'idle':
            if d >= cfg['cut_min_s']:
                cuts.append({'t0': r3(s['t0'] + cfg['cut_pad_s']), 't1': r3(s['t1'] - cfg['cut_pad_s']), 'kind': 'drop',
                             'reason': 'idle %.1f s' % d})
            else:
                ramps.append({'t0': s['t0'], 't1': s['t1'], 'rate': cfg['rate_idle'], 'kind': 'idle'})
        elif k == 'spinner':
            ramps.append({'t0': s['t0'], 't1': s['t1'], 'rate': cfg['rate_spinner'], 'kind': 'spinner', 'caption': 'working'})
            captions.append({'t0': s['t0'], 't1': s['t1'], 'hook': 'working', 'box': s.get('box')})
        elif k == 'typing':
            ramps.append({'t0': s['t0'], 't1': s['t1'], 'rate': cfg['rate_typing'], 'kind': 'typing'})
            caret.append({'t0': s['t0'], 't1': s['t1'], 'box': s.get('box'), 'caret': s.get('caret', [])})
        elif k == 'scroll':
            fast = abs(s.get('px_per_s', 0.0)) > cfg['scroll_keep_pxs']
            ramps.append({'t0': s['t0'], 't1': s['t1'], 'rate': cfg['scroll_fast_rate'] if fast else 1.0, 'kind': 'scroll',
                          'note': 'fast scroll' if fast else 'keep real-time'})
        elif k == 'page' and d <= cfg['page_cut_max_s']:
            cuts.append({'t': s['t0'], 'kind': 'hard', 'reason': 'page change'})
    lane = build_lane(ramps, win_t0, cfg)
    mp, film_dur = build_map(cuts, ramps, win_t0, win_t1, cfg)
    return {'cuts': cuts, 'ramps': ramps, 'caret_follow': caret, 'captions': captions, 'lane': lane, 'map': mp,
            'source_duration': r3(win_t1 - win_t0), 'film_duration': r3(film_dur), 'saved_s': r3(win_t1 - win_t0 - film_dur)}


def build_lane(ramps, win_t0, cfg):
    """[[t, rate], ...] clip-local, 0.25 s eases, monotonic times, rates clamped to the VFX.ramp range."""
    ez, pts = cfg['ease_s'], [[0.0, 1.0]]
    for r in sorted((r for r in ramps if abs(r['rate'] - 1.0) > 1e-9), key=lambda r: r['t0']):
        rate = min(cfg['rate_max'], max(cfg['rate_min'], r['rate']))
        a, b = r['t0'] - win_t0, r['t1'] - win_t0
        for t, v in ((a - ez, 1.0), (a, rate), (b, rate), (b + ez, 1.0)):
            t = max(t, 0.0)
            if t <= pts[-1][0]:
                if pts[-1][1] == v:
                    continue
                t = pts[-1][0] + 0.01
            pts.append([r3(t), r3(v)])
    return pts


def build_map(cuts, ramps, win_t0, win_t1, cfg):
    """[[dt, u], ...]: film seconds since play.at → clip fraction. Drops are vertical steps, ramps get a one-point ease."""
    span = max(1e-6, win_t1 - win_t0)
    segs = [(c['t0'], c['t1'], None) for c in cuts if c.get('kind') == 'drop'] + \
           [(r['t0'], r['t1'], r['rate']) for r in ramps if abs(r['rate'] - 1.0) > 1e-9]
    segs.sort()
    ez = cfg['ease_s']
    u = lambda t: r3((t - win_t0) / span)
    pairs, dt, cur = [[0.0, 0.0]], 0.0, win_t0
    for a, b, rate in segs:
        if a < cur:
            continue
        if a > cur:
            dt += a - cur; pairs.append([r3(dt), u(a)])
        if rate is None:
            pairs.append([r3(dt), u(b)])
        else:
            src_e = ez * (1.0 + rate) / 2.0                 # source seconds consumed by a 0.25 s film-time ease
            if (b - a) > 2.2 * src_e:
                dt += ez; pairs.append([r3(dt), u(a + src_e)])
                dt += (b - a - 2 * src_e) / rate; pairs.append([r3(dt), u(b - src_e)])
                dt += ez; pairs.append([r3(dt), u(b)])
            else:
                dt += (b - a) / rate; pairs.append([r3(dt), u(b)])
        cur = b
    if win_t1 > cur:
        dt += win_t1 - cur
    pairs.append([r3(dt), 1.0])
    return pairs, dt


# ---------------------------------------------------------------------------------------------- top level
def analyse(path, t0=0.0, t1=None, cfg=None, dbg=None):
    user = dict(cfg or {})
    cfg = dict(DEFAULTS, **user)
    info = probe(path)
    if info['width'] <= 0 or info['height'] <= 0:
        raise UsageError('no video stream in %s' % path)
    if 'aw' not in user:                                           # analysis grid: constant source-pixel density
        c = cfg['cell']
        aw = int(round(info['width'] / cfg['density'] / c)) * c
        cfg['aw'] = int(min(cfg['aw_max'], max(cfg['aw_min'], aw)))
    if 'ah' not in user:
        cfg['ah'] = max(cfg['cell'] * 6, int(round(info['height'] * cfg['aw'] / info['width'] / cfg['cell'])) * cfg['cell'])
    t0 = max(0.0, float(t0 or 0.0))
    t0 = round(t0 * cfg['fps']) / cfg['fps']                       # frame-aligned so pass 2 sees the same frames
    end = float(t1) if t1 is not None else info['duration']
    if end <= t0 + 0.5:
        raise UsageError('window [%g, %g] is empty or too short' % (t0, end))
    F = pass1(path, t0, end - t0, cfg)
    win_t1 = t0 + F['nframes'] / cfg['fps']
    lab = label_frames(F, cfg)
    spans = find_spans(path, t0, F, lab, cfg, info, dbg)
    props = build_proposals(spans, t0, win_t1, cfg)
    counts = {k: sum(1 for s in spans if s['kind'] == k) for k in KINDS}
    e = F['energy']
    out = {'tool': 'idle_detect', 'version': VERSION,
           'source': {'path': os.path.basename(path), 'width': info['width'], 'height': info['height'],
                      'duration': r3(info['duration']), 'window': [r3(t0), r3(win_t1)]},
           'fps': cfg['fps'],
           'analysis': {'w': cfg['aw'], 'h': cfg['ah'], 'blur': cfg['blur'], 'cell': cfg['cell'], 'frames': int(F['nframes']),
                        'energy': {'mean': r3(e.mean()), 'p50': r3(np.percentile(e, 50)), 'p90': r3(np.percentile(e, 90)),
                                   'max': r3(e.max()), 'quiet_frac': r3((e < cfg['idle_energy']).mean())},
                        'thresholds': {k: cfg[k] for k in sorted(cfg) if k not in ('aw', 'ah', 'fps', 'blur', 'cell')}},
           'spans': spans, 'proposals': props,
           'summary': dict(counts, idle_total_s=r3(sum(s['t1'] - s['t0'] for s in spans if s['kind'] == 'idle')),
                           saved_s=props['saved_s'], film_duration=props['film_duration'])}
    out['_series'] = {'t': [r3(t0 + (k + 1) / cfg['fps']) for k in range(len(e))], 'energy': [r3(v) for v in e],
                      'label': [int(v) for v in lab]}
    return out


# ---------------------------------------------------------------------------------------------- the sheet
def render_sheet(res, path):
    from PIL import Image, ImageDraw, ImageFont
    W, H, L, R = 1600, 440, 70, 1500
    im = Image.new('RGB', (W, H), PALETTE['navy'])
    dr = ImageDraw.Draw(im)
    try:
        F1, F2 = ImageFont.load_default(size=14), ImageFont.load_default(size=11)
    except TypeError:
        F1 = F2 = ImageFont.load_default()
    S = res['_series']; ts, es, labs = S['t'], S['energy'], S['label']
    wt0, wt1 = res['source']['window']
    X = lambda t: L + (t - wt0) / max(1e-6, wt1 - wt0) * (R - L)
    dr.text((L, 14), 'idle_detect  -  %s   %dx%d   window %.1f-%.1f s   %d spans   saves %.1f s of %.1f'
            % (res['source']['path'], res['source']['width'], res['source']['height'], wt0, wt1, len(res['spans']),
               res['summary']['saved_s'], res['proposals']['source_duration']), fill=PALETTE['ink'], font=F1)
    # spans band
    y0, y1 = 48, 84
    dr.rectangle([L, y0, R, y1], fill=PALETTE['navy2'])
    for s in res['spans']:
        dr.rectangle([X(s['t0']), y0, max(X(s['t1']), X(s['t0']) + 2), y1], fill=KIND_RGB[s['kind']])
    dr.text((8, y0 + 10), 'spans', fill=PALETTE['ink'], font=F2)
    # energy plot (log scale)
    py0, py1 = 100, 300
    dr.rectangle([L, py0, R, py1], fill=(14, 52, 64))
    Y = lambda e: py1 - math.log10(1 + max(0.0, e)) / math.log10(256) * (py1 - py0)
    for thr, col, name in ((res['analysis']['thresholds']['idle_energy'], PALETTE['mint'], 'idle 0.6'),
                           (res['analysis']['thresholds']['page_energy'], PALETTE['coral'], 'page 25')):
        yy = Y(thr); dr.line([L, yy, R, yy], fill=col, width=1); dr.text((R + 4, yy - 7), name, fill=col, font=F2)
    lastx = None
    for t, e, lb in zip(ts, es, labs):
        x = X(t); y = Y(e)
        col = (120, 170, 220) if lb == 2 else PALETTE['coral'] if lb == 3 else PALETTE['ink']
        if lastx is not None:
            dr.line([lastx[0], lastx[1], x, y], fill=col, width=1)
        lastx = (x, y)
    dr.text((8, py0 + 4), 'energy', fill=PALETTE['ink'], font=F2); dr.text((8, py0 + 18), '(log)', fill=PALETTE['ink'], font=F2)
    # proposals band
    q0, q1 = 316, 352
    dr.rectangle([L, q0, R, q1], fill=PALETTE['navy2'])
    for c in res['proposals']['cuts']:
        if c['kind'] == 'drop':
            xa, xb = X(c['t0']), X(c['t1'])
            dr.rectangle([xa, q0, xb, q1], fill=PALETTE['coral'])
            for x in range(int(xa), int(xb), 8):
                dr.line([x, q1, min(x + 8, xb), q0], fill=PALETTE['navy'], width=1)
        else:
            dr.line([X(c['t']), q0 - 6, X(c['t']), q1 + 6], fill=PALETTE['coral'], width=2)
    for r in res['proposals']['ramps']:
        xa, xb = X(r['t0']), X(r['t1'])
        col = PALETTE['gold'] if r['rate'] > 1.0 else PALETTE['mint']
        dr.rectangle([xa, q0 + 8, xb, q1 - 8], fill=col)
        if xb - xa > 26:
            dr.text((xa + 3, q0 + 10), '%gx' % r['rate'], fill=PALETTE['navy'], font=F2)
    for cf in res['proposals']['caret_follow']:
        dr.line([X(cf['t0']), q1 + 3, X(cf['t1']), q1 + 3], fill=PALETTE['cream'], width=2)
    dr.text((8, q0 + 10), 'edit', fill=PALETTE['ink'], font=F2)
    # axis + legend
    ay = 366
    dr.line([L, ay, R, ay], fill=PALETTE['ink'], width=1)
    step = nice_step(wt1 - wt0)
    t = math.ceil(wt0 / step) * step
    while t <= wt1 + 1e-6:
        dr.line([X(t), ay, X(t), ay + 5], fill=PALETTE['ink']); dr.text((X(t) - 8, ay + 8), '%g' % t, fill=PALETTE['ink'], font=F2); t += step
    lx = L
    for k in KINDS:
        dr.rectangle([lx, 404, lx + 14, 418], fill=KIND_RGB[k]); dr.text((lx + 18, 403), k, fill=PALETTE['ink'], font=F2); lx += 90
    dr.rectangle([lx, 404, lx + 14, 418], fill=PALETTE['coral']); dr.text((lx + 18, 403), 'cut (drop / hard)', fill=PALETTE['ink'], font=F2); lx += 140
    dr.rectangle([lx, 404, lx + 14, 418], fill=PALETTE['gold']); dr.text((lx + 18, 403), 'ramp > 1x', fill=PALETTE['ink'], font=F2); lx += 100
    dr.rectangle([lx, 404, lx + 14, 418], fill=PALETTE['mint']); dr.text((lx + 18, 403), 'keep 1x', fill=PALETTE['ink'], font=F2); lx += 90
    dr.line([lx, 411, lx + 14, 411], fill=PALETTE['cream'], width=2); dr.text((lx + 18, 403), 'caret follow', fill=PALETTE['ink'], font=F2)
    im.save(path)
    return path


def nice_step(span):
    for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
        if span / s <= 24:
            return s
    return 600


# ---------------------------------------------------------------------------------------------- synthetic fixture
FIXTURE_PLAN = {                                   # expected spans (seconds) — the selftest asserts each within ±0.3 s
    'idle_1': (0.0, 2.0), 'spinner': (2.0, 5.0), 'idle_2': (5.0, 7.0), 'typing': (7.0, 11.0), 'idle_3': (11.0, 12.5),
    'scroll': (12.5, 15.0), 'page': (15.0, 15.1), 'idle_4': (15.0, 17.0),
}
FIXTURE_SCROLL_PXS = 300.0
FIXTURE_TEXT = 'open orders by region, acme west'      # 32 chars typed in 7.0-11.0 s


def make_fixture(path, w=1280, h=720, fps=20, seed=7):
    """Draw a fictional Acme UI with Pillow and encode it with ffmpeg: idle (blinking caret), a rotating spinner,
    typing, a 300 px/s table scroll behind a fixed header, then a hard page change. Deterministic (seeded)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        F_T, F_B, F_S = ImageFont.load_default(size=20), ImageFont.load_default(size=22), ImageFont.load_default(size=15)
    except TypeError:
        F_T = F_B = F_S = ImageFont.load_default()
    rng = np.random.default_rng(seed)
    NAVY, NAVY2, INK, CREAM, CORAL, MINT, GOLD = [PALETTE[k] for k in ('navy', 'navy2', 'ink', 'cream', 'coral', 'mint', 'gold')]
    # page 1
    base = Image.new('RGB', (w, h), (255, 255, 255))
    d = ImageDraw.Draw(base)
    d.rectangle([0, 0, w, 64], fill=NAVY2); d.text((24, 20), 'Acme Insights', fill=INK, font=F_T)
    d.rectangle([0, 64, 240, h], fill=(242, 240, 234))
    for i, item in enumerate(('Overview', 'Orders', 'Regions', 'Suppliers', 'Reports', 'Settings')):
        d.text((28, 96 + i * 44), item, fill=(60, 60, 60), font=F_S)
    d.rectangle([300, 120, 1180, 180], outline=(180, 180, 180), width=2, fill=(250, 250, 250))
    d.text((320, 96), 'Ask a question', fill=(120, 120, 120), font=F_S)
    # scrolling table content (tall), shown through the viewport 300..1180 x 220..700 under a fixed column header
    rows = 40
    content = Image.new('RGB', (880, rows * 48), (255, 255, 255))
    cd = ImageDraw.Draw(content)
    for i in range(rows):
        y = i * 48
        if i % 2:
            cd.rectangle([0, y, 880, y + 48], fill=(247, 247, 245))
        cd.text((16, y + 14), 'ORD-10%02d' % i, fill=(40, 40, 40), font=F_S)
        cd.text((200, y + 14), ('Acme West', 'Acme North', 'Acme East')[i % 3], fill=(40, 40, 40), font=F_S)
        cd.text((440, y + 14), '$ %d,%03d' % (1 + i % 9, (i * 137) % 1000), fill=(40, 40, 40), font=F_S)
        cd.text((640, y + 14), ('Open', 'Shipped', 'Hold')[(i * 7) % 3], fill=CORAL if (i * 7) % 3 == 2 else (40, 40, 40), font=F_S)
    header = Image.new('RGB', (880, 40), (236, 234, 228))
    hd = ImageDraw.Draw(header)
    for x, name in ((16, 'Order'), (200, 'Region'), (440, 'Amount'), (640, 'Status')):
        hd.text((x, 11), name, fill=(60, 60, 60), font=F_S)
    # page 2
    page2 = Image.new('RGB', (w, h), NAVY)
    p = ImageDraw.Draw(page2)
    p.text((80, 80), 'Acme Insights - Open orders by region', fill=CREAM, font=F_B)
    for i, (lab, val) in enumerate((('West', '1,284'), ('North', '902'), ('East', '611'))):
        x = 80 + i * 380
        p.rectangle([x, 180, x + 320, 420], fill=NAVY2); p.text((x + 24, 204), lab, fill=MINT, font=F_S); p.text((x + 24, 250), val, fill=GOLD, font=F_B)
    # typing schedule: 32 chars across 7.0-10.9 s with seeded jitter
    gaps = 1.0 + 0.5 * rng.standard_normal(len(FIXTURE_TEXT))
    gaps = np.clip(gaps, 0.4, 2.0); cum = np.concatenate([[0.0], np.cumsum(gaps)[:-1]])
    tch = 7.0 + cum / cum[-1] * 3.9 if cum[-1] > 0 else np.full(len(FIXTURE_TEXT), 7.0)
    total = 17.0
    n = int(round(total * fps))
    cmd = ['ffmpeg', '-y', '-nostdin', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (w, h),
           '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p', path]
    odir = os.path.dirname(os.path.abspath(path))
    os.makedirs(odir, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for k in range(n):
            t = k / fps
            if t >= FIXTURE_PLAN['page'][0]:
                proc.stdin.write(page2.tobytes()); continue
            im = base.copy(); dr = ImageDraw.Draw(im)
            # table viewport
            sc0, sc1 = FIXTURE_PLAN['scroll']
            off = int(round(FIXTURE_SCROLL_PXS * (min(max(t, sc0), sc1) - sc0)))
            im.paste(content.crop((0, off, 880, off + 440)), (300, 260))
            im.paste(header, (300, 220))
            # typed text + caret
            typed = FIXTURE_TEXT[:int(np.sum(tch <= t))]
            dr.text((320, 136), typed, fill=(30, 30, 30), font=F_B)
            tw = dr.textlength(typed, font=F_B) if typed else 0
            cx = int(320 + tw + 2)
            typing_now = FIXTURE_PLAN['typing'][0] <= t < FIXTURE_PLAN['typing'][1]
            if typing_now or (int(t * 2) % 2 == 0):               # steady while typing, 1 Hz blink otherwise
                dr.rectangle([cx, 138, cx + 2, 162], fill=(30, 30, 30))
            # spinner card
            sp0, sp1 = FIXTURE_PLAN['spinner']
            if sp0 <= t < sp1:
                dr.rectangle([820, 340, 1000, 460], fill=(255, 255, 255), outline=(200, 200, 200), width=2)
                dr.text((840, 356), 'Running query', fill=(90, 90, 90), font=F_S)
                a0 = (360.0 * (t - sp0)) % 360.0
                dr.arc([892, 400, 928, 436], start=a0, end=a0 + 270, fill=CORAL, width=4)
            proc.stdin.write(im.tobytes())
    except BrokenPipeError:
        pass                                                   # ffmpeg quit early; its stderr is raised below
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        err = proc.stderr.read().decode('utf-8', 'replace')
        proc.wait()
    if proc.returncode != 0:
        raise UsageError('fixture encode failed: %s' % err[:300])
    return path


# ---------------------------------------------------------------------------------------------- selftest
def public(res):
    return {k: v for k, v in res.items() if not k.startswith('_')}


def selftest(keep=None):
    import time
    t_start = time.time()
    tmp = keep or tempfile.mkdtemp(prefix='idle_selftest_')
    os.makedirs(tmp, exist_ok=True)
    fx = os.path.join(tmp, 'fixture.mp4')
    fails, notes = [], []
    make_fixture(fx)
    r1 = analyse(fx)
    r2 = analyse(fx)
    j1, j2 = json.dumps(public(r1), sort_keys=True), json.dumps(public(r2), sort_keys=True)
    if j1 != j2:
        fails.append('not deterministic: two runs differ')
    else:
        notes.append('deterministic: two runs identical (%d bytes)' % len(j1))
    spans = r1['spans']
    tol = 0.3

    def near(kind, exp, both=True):
        cands = [s for s in spans if s['kind'] == kind and abs(s['t0'] - exp[0]) <= tol and (not both or abs(s['t1'] - exp[1]) <= tol)]
        return cands[0] if cands else None

    for name, exp in FIXTURE_PLAN.items():
        kind = name.split('_')[0]
        s = near(kind, exp, both=(kind != 'page'))
        if s is None:
            got = ['%s %.1f-%.1f' % (x['kind'], x['t0'], x['t1']) for x in spans if x['kind'] == kind]
            fails.append('%s expected %s at %.1f-%.1f, got %s' % (kind, name, exp[0], exp[1], got or 'nothing'))
        else:
            notes.append('%-8s %.1f-%.1f ok (found %.1f-%.1f, conf %.2f)' % (name, exp[0], exp[1], s['t0'], s['t1'], s['confidence']))
            if kind == 'scroll' and not (0.75 * FIXTURE_SCROLL_PXS <= s['px_per_s'] <= 1.25 * FIXTURE_SCROLL_PXS):
                fails.append('scroll px/s %.0f not within 25%% of %.0f' % (s['px_per_s'], FIXTURE_SCROLL_PXS))
            if kind == 'spinner':
                bx = s['box']
                if not (bx[0] <= 910 <= bx[0] + bx[2] and bx[1] <= 418 <= bx[1] + bx[3]):
                    fails.append('spinner box %s does not contain the arc centre (910, 418)' % bx)
                if 'period_s' in s and not (0.8 <= s['period_s'] <= 1.2):
                    fails.append('spinner period %.2f s, expected ~1.0' % s['period_s'])
            if kind == 'typing':
                bx = s['box']
                if not (bx[1] <= 150 <= bx[1] + bx[3]):
                    fails.append('typing box %s misses the input line (y 136-162)' % bx)
                if len(s.get('caret', [])) < 4:
                    fails.append('typing caret path too short: %d samples' % len(s.get('caret', [])))
    extra = [s for s in spans if s['kind'] in ('spinner', 'typing', 'scroll', 'page')]
    if len(extra) != 4:
        fails.append('expected exactly one spinner/typing/scroll/page each, got %s' % [(s['kind'], s['t0']) for s in extra])
    P = r1['proposals']
    if not any(c['kind'] == 'hard' for c in P['cuts']):
        fails.append('no hard-cut candidate for the page change')
    if not any(r['kind'] == 'spinner' and r['rate'] == 4.0 for r in P['ramps']):
        fails.append('no 4x spinner ramp')
    if not P['caret_follow']:
        fails.append('no caret_follow proposal')
    if P['lane'][0] != [0.0, 1.0] or any(P['lane'][i][0] >= P['lane'][i + 1][0] for i in range(len(P['lane']) - 1)):
        fails.append('lane not monotonic: %s' % P['lane'][:6])
    if any(P['map'][i][0] > P['map'][i + 1][0] or P['map'][i][1] > P['map'][i + 1][1] + 1e-9 for i in range(len(P['map']) - 1)) \
            or P['map'][-1][1] != 1.0:
        fails.append('map not monotonic / does not end at 1.0')
    sheet = os.path.join(tmp, 'idle_sheet.png')
    render_sheet(r1, sheet)
    with open(os.path.join(tmp, 'idle.json'), 'w', encoding='utf-8') as fh:
        json.dump(public(r1), fh, indent=1)
    el = time.time() - t_start
    for n_ in notes:
        print('  ok   ' + n_)
    for f in fails:
        print('  FAIL ' + f)
    print('%s  (%.1f s; fixture, idle.json and sheet in %s)' % ('SELFTEST PASS' if not fails else 'SELFTEST FAIL', el, tmp))
    if not keep and not fails:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


def write_js(res, path, clip):
    """scenes/idle.js — the proposals as a plain script tag: window.IDLE[clip] = {...}. Pure data, so the renderer's
    determinism and the no-remote-refs gate are untouched; shots.js reads IDLE[clip].proposals.map / .lane."""
    key = json.dumps(str(clip))
    body = json.dumps(public(res), separators=(',', ':'), sort_keys=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('/* idle.js - written by tools/idle_detect.py; proposals only, the footage is untouched */\n')
        fh.write('(function (r) { r.IDLE = r.IDLE || {}; r.IDLE[%s] = %s; })(typeof window !== \'undefined\' ? window : globalThis);\n' % (key, body))
    return path


# ---------------------------------------------------------------------------------------------- CLI
def human(res):
    lines = ['%s  %dx%d  window %.1f-%.1f s  (%d frames @ %g fps, energy p50 %.2f p90 %.2f max %.1f, quiet %.0f %%)' % (
        res['source']['path'], res['source']['width'], res['source']['height'], res['source']['window'][0], res['source']['window'][1],
        res['analysis']['frames'], res['fps'], res['analysis']['energy']['p50'], res['analysis']['energy']['p90'],
        res['analysis']['energy']['max'], 100 * res['analysis']['energy']['quiet_frac'])]
    for s in res['spans']:
        ex = ''
        if 'px_per_s' in s:
            ex = ' %+.0f px/s' % s['px_per_s']
        if 'period_s' in s:
            ex = ' period %.1f s' % s['period_s']
        if s.get('sub'):
            ex += ' (%s)' % s['sub']
        if 'rate_hz' in s:
            ex = ' %.1f Hz' % s['rate_hz']
        if 'box' in s:
            ex += ' box %s' % [int(v) for v in s['box']]
        lines.append('  %7.1f-%7.1f  %-8s conf %.2f%s' % (s['t0'], s['t1'], s['kind'], s['confidence'], ex))
    P = res['proposals']
    lines.append('proposals: %d cuts, %d ramps, %d caret-follows, %d captions; %.1f s -> %.1f s (saves %.1f s)' % (
        len(P['cuts']), len(P['ramps']), len(P['caret_follow']), len(P['captions']), P['source_duration'], P['film_duration'], P['saved_s']))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Find dead air (idle, spinner, typing, scroll, page change) in a recording and propose cuts and speed ramps.',
                                 epilog='exit 0 nothing to fix · 1 dead air found · 2 usage/decoder error')
    ap.add_argument('recording', nargs='?', help='video file (ffmpeg-readable; VFR .mov is fine)')
    ap.add_argument('--out', default=None, help='idle.json path (default: next to the recording as <name>.idle.json)')
    ap.add_argument('--t0', type=float, default=0.0, help='analyse from this second')
    ap.add_argument('--t1', type=float, default=None, help='analyse up to this second')
    ap.add_argument('--sheet', default=None, help='write the energy timeline PNG here')
    ap.add_argument('--js', default=None, help='also write a scene-loadable scenes/idle.js (window.IDLE[<clip>] = idle.json); '
                    'no runtime fetch, so the "no remote refs" gate stays green')
    ap.add_argument('--clip', default=None, help='clip name used as the key in --js (default: the recording\'s stem)')
    ap.add_argument('--config', default=None, help='JSON file overriding any threshold (keys as in DEFAULTS)')
    ap.add_argument('--density', type=float, default=None, help='source px per analysis px (default 6 = 320 wide for 1080p); '
                    'use 4 for a retina capture of a small-font UI whose typing the sheet shows as idle')
    ap.add_argument('--json', action='store_true', help='print the full JSON to stdout instead of the table')
    ap.add_argument('--make-fixture', metavar='OUT.mp4', help='render the synthetic Acme fixture and exit')
    ap.add_argument('--selftest', action='store_true', help='render the fixture, analyse twice, assert every kind within ±0.3 s')
    ap.add_argument('--keep', default=None, help='(selftest) keep fixture + outputs in this directory')
    ap.add_argument('--debug', action='store_true', help='print why each micro-active segment was or was not classified')
    a = ap.parse_args(argv)
    try:
        if a.selftest:
            return selftest(a.keep)
        if a.make_fixture:
            make_fixture(a.make_fixture); print('fixture written: %s' % a.make_fixture); return 0
        if not a.recording:
            ap.print_usage(); return 2
        cfg = {}
        if a.config:
            with open(a.config, encoding='utf-8') as fh:
                cfg = json.load(fh)
            bad = sorted(set(cfg) - set(DEFAULTS))
            if bad:
                raise UsageError('unknown config keys: %s' % bad)
        if a.density:
            cfg['density'] = a.density
        dbg = [] if a.debug else None
        res = analyse(a.recording, a.t0, a.t1, cfg, dbg)
        if dbg:
            print('\n'.join(['micro-activity inside quiet runs:'] + dbg), file=sys.stderr)
        out = a.out or (os.path.splitext(a.recording)[0] + '.idle.json')
        with open(out, 'w', encoding='utf-8') as fh:
            json.dump(public(res), fh, indent=1)
        if a.sheet:
            render_sheet(res, a.sheet)
        if a.js:
            write_js(res, a.js, a.clip or os.path.splitext(os.path.basename(a.recording))[0])
        extra = [p for p in (a.sheet, a.js) if p]
        print(json.dumps(public(res), indent=1) if a.json else human(res) + '\nwrote %s' % ', '.join([out] + extra))
        P = res['proposals']
        return 1 if (P['cuts'] or any(abs(r['rate'] - 1.0) > 1e-9 for r in P['ramps'])) else 0
    except UsageError as e:
        print('usage error: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
