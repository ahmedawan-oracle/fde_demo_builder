# -*- coding: utf-8 -*-
"""brand_kit.py — a brand's logo (and optionally its website) → a complete, contrast-checked film skin + a 6-frame
style sheet, so the look is approved BEFORE a single film frame is rendered (v5, brand-skins-review area).

    python tools/brand_kit.py extract --logo logo.png [--site site.png] [--bg dark|light|auto]
                                      [--mood editorial|technical|friendly|corporate] [--name acme]
                                      [--title "Monday, answered."] [--subtitle "..."] [--caption "..."]
                                      [--out skin_tokens.json] [--sheet out/style_sheet.png] [--json]
    python tools/brand_kit.py --from-skin skins/harbor.json [--sheet skins/sheets/harbor.png] [--json]
    python tools/brand_kit.py compose --name harbor --paper "#082A34" --accent "#E56B5E" [--ink ..] [--muted ..] [--gold ..]
                                      [--bg dark|light] [--mood ..] [--profile calm|medium|high] [--caption-style documentary]
                                      [--seams "cut-the-curve,inverse zoom-through"] [--when "..."] [--out skins/harbor.json] [--sheet ..]
                                                                      hand-picked colours → the same contrast-fixed skin document
    python tools/brand_kit.py check skin_tokens.json [--json]        design-adherence lint of a skin (exit 1 on findings)
    python tools/brand_kit.py --selftest                             synthetic logo → skin → sheet, twice, byte-identical

The method, from first principles
---------------------------------
1. Pixels. The logo is reduced to <= 160 px on its longest side with a box filter (every source pixel counts
   once — deterministic, no sampling). Pixels with alpha < 128 are dropped; near-white (min channel > 235) and
   near-black (max channel < 24) pixels are dropped too, because they are the page, not the brand. Low-chroma
   pixels (max - min < 12) are kept aside as NEUTRAL candidates. A website screenshot, when given, is reduced the
   same way and its pixels weigh 0.35 of a logo pixel: it confirms the palette, it never outvotes the mark.
2. Clustering. The chromatic pixels go to weighted k-means (k = 6, k-means++ seeding, seed 0, 4 restarts, best
   inertia kept) in CIE L*a*b* — the space where Euclidean distance approximates perceived difference (1 unit ~ one
   just-noticeable step), so a gradient on the mark collapses into its one intended colour instead of six. The
   canonical engine is our own numpy implementation (identical on any machine, ~0.1 s); BRAND_KIT_ENGINE=sklearn
   runs scikit-learn's KMeans with the same seed as a cross-check. Clusters are sorted by weight, then hex, so the
   output order never depends on floating-point luck.
3. Roles. PRIMARY = the heaviest cluster with chroma >= 15. ACCENT = the cluster whose hue sits farthest from the
   primary (>= 40 deg apart, chroma >= 20), ranked by sqrt(weight) so a thin but deliberate second colour still
   wins; with no second colour the accent is synthesised at hue + 150 deg. NEUTRAL = the median of the grey
   candidates, else the primary at chroma 10.
4. Background. `--bg dark` (the booth default) tints a deep paper with the primary hue at L* 15 / chroma <= 12
   (never pure black — pure #000 crushes on an H.264 booth screen) and a second stop at L* 24 for the stage
   gradient; `--bg light` builds a paper at L* 95 and ink at L* 15 in the same hue. `auto` picks dark unless the
   mark itself is mostly dark (mean L* of the chromatic pixels < 45).
5. Contrast. Every text-bearing token is checked with the WCAG 2.x relative-luminance ratio against the paper and
   nudged in L* (1 step at a time, hue fixed, chroma shrunk only when out of gamut) until it passes:
   ink >= 7:1 (AAA body text — a booth is read from 2-4 m), ink-soft >= 4.5:1, muted >= 4.5:1, accent >= 3:1
   (graphics / large text), gold >= 3:1. The achieved ratios are written into the skin so a reviewer sees them.
6. Type. A fixed table of fonts that ship with Windows (so the sheet and the film agree on a laptop with no
   installs): editorial = Georgia / Segoe UI, technical = Bahnschrift / Segoe UI, friendly = Segoe UI / Segoe UI,
   corporate = Cambria / Arial; Consolas is the mono face in every pairing. Sizes follow design.example.md:
   title 64 stage px (<= 3 words), body 22, label 13 tracked +0.12 em, all on the 1280x720 stage (x1.5 = 1080p).
7. Motion. The skin names a motion profile (calm / medium / high) whose numbers come from motion-doctrine.md and
   cinematic-grammar.md: a single entry <= 0.8 s, exit ~ 75 % of the entry, a stagger finishes inside 0.5 s with
   0.04-0.08 s per item, a push lasts 0.9-2.0 s and lands x1.3-x2.0, the hold after it is >= 1 s (2-2.5 s normal).
8. The sheet. Six 640x360 frames (half the stage) drawn with Pillow in the skin's own fonts and colours: title
   card, caption lane over a synthetic product plate, KPI tiles, lower third, chart, close card with the mandatory
   credit. The dashed line at 83 % of the height is the caption keep-out. Figures on the sheet are labelled
   "sample" — a film never invents a figure; a sheet only shows how one would look.

Output: skin_tokens.json in the shape of templates/skin_tokens.example.json (same token ids, same types) plus
`brand` (clusters, roles, contrast ratios), `type`, `motion`, `captions`, `seams`, `when_to_use`. Deterministic:
same inputs → byte-identical JSON and PNG. Exit codes: 0 ok, 1 findings (check) / contrast could not be met, 2 usage.
Deps: Pillow, numpy (scikit-learn only for the optional cross-check engine). No network, no wall clock.
"""
import argparse, json, math, os, sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
FILM = os.path.normpath(os.path.join(HERE, '..'))
TEMPLATES = os.path.join(FILM, 'templates')
SKINS_DIR = os.path.join(FILM, 'skins')
CREDIT = 'Crafted with FDE Demo Builder · by Ahmed Awan'      # mandatory, verbatim — the close frame of the sheet shows it

# ------------------------------------------------------------------------------------------------ fixed tables
MOODS = ('editorial', 'technical', 'friendly', 'corporate')
FONTS_DIR = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
# family → (regular file, bold file, css fallback stack)
FACES = {
    'Georgia':     ('georgia.ttf', 'georgiab.ttf', 'Georgia, "Times New Roman", serif'),
    'Cambria':     ('cambria.ttc', 'cambriab.ttf', 'Cambria, Georgia, serif'),
    'Segoe UI':    ('segoeui.ttf', 'segoeuib.ttf', '"Segoe UI", Arial, sans-serif'),
    'Arial':       ('arial.ttf', 'arialbd.ttf', 'Arial, Helvetica, sans-serif'),
    'Consolas':    ('consola.ttf', 'consolab.ttf', 'Consolas, "Courier New", monospace'),
    'Bahnschrift': ('bahnschrift.ttf', 'bahnschrift.ttf', 'Bahnschrift, "Segoe UI", sans-serif'),
}
PAIRINGS = {                     # mood → (display, body, mono, display weight)
    'editorial': ('Georgia', 'Segoe UI', 'Consolas', 400),
    'technical': ('Bahnschrift', 'Segoe UI', 'Consolas', 600),
    'friendly':  ('Segoe UI', 'Segoe UI', 'Consolas', 700),
    'corporate': ('Cambria', 'Arial', 'Consolas', 400),
}
# measured motion profiles (motion-doctrine.md Part 4 + cinematic-grammar.md Camera); seconds on the film clock
MOTION_PROFILES = {
    'calm':   {'profile': 'calm', 'enter_s': 0.6, 'exit_s': 0.45, 'stagger_total_s': 0.5, 'per_item_s': 0.08,
               'push_s': 1.4, 'push_scale': [1.3, 1.6], 'hold_s': 2.5, 'first_motion_s': 0.2, 'offset_after_cut_s': 0.3,
               'rack_focus_min_gap_s': None, 'eases': {'enter': 'power4.out', 'exit': 'sine.in', 'push': 'sine.out', 'pan': 'sine.inOut'}},
    'medium': {'profile': 'medium', 'enter_s': 0.4, 'exit_s': 0.3, 'stagger_total_s': 0.5, 'per_item_s': 0.06,
               'push_s': 1.1, 'push_scale': [1.4, 1.8], 'hold_s': 2.0, 'first_motion_s': 0.2, 'offset_after_cut_s': 0.2,
               'rack_focus_min_gap_s': 8.0, 'eases': {'enter': 'power4.out', 'exit': 'power2.in', 'push': 'sine.out', 'pan': 'sine.inOut'}},
    'high':   {'profile': 'high', 'enter_s': 0.25, 'exit_s': 0.2, 'stagger_total_s': 0.4, 'per_item_s': 0.04,
               'push_s': 0.9, 'push_scale': [1.5, 2.0], 'hold_s': 1.5, 'first_motion_s': 0.15, 'offset_after_cut_s': 0.1,
               'rack_focus_min_gap_s': 8.0, 'eases': {'enter': 'expo.out', 'exit': 'power3.in', 'push': 'sine.out', 'pan': 'sine.inOut'}},
}
CAPTION_STYLES = ('anchor', 'broadcast', 'documentary', 'keynote', 'ink', 'conference', 'typewriter', 'clipwipe')
SEAM_TECHNIQUES = ('cut-the-curve', 'zoom-through', 'inverse zoom-through', 'combined', 'rack-focus', 'waterfall')
TOKEN_IDS = ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black', 'title-font', 'body-font',
             'title-size', 'title', 'subtitle', 'caption', 'logo', 'density')
CONTRAST_MIN = {'ink': 7.0, 'ink-soft': 4.5, 'muted': 4.5, 'accent': 3.0, 'gold': 3.0}
FORBIDDEN = ('narration', 'fps', 'width', 'height', 'total', 'codec', 'credit')
STAGE = (1280, 720)
KEEPOUT = 0.83


# ------------------------------------------------------------------------------------------------ colour maths
def hex_to_rgb(h):
    h = h.strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return '#%02X%02X%02X' % tuple(int(round(min(255, max(0, c)))) for c in rgb)


def _lin(c):
    c = np.asarray(c, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _gam(c):
    c = np.clip(np.asarray(c, dtype=float), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055) * 255.0


def rel_lum(hexc):
    r, g, b = _lin(hex_to_rgb(hexc))
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)


def contrast(a, b):
    """WCAG 2.x contrast ratio between two hex colours (1.0 .. 21.0)."""
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


_M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_M_XYZ2RGB = np.linalg.inv(_M_RGB2XYZ)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb):
    """sRGB (N,3) 0-255 → CIE L*a*b* (N,3), D65."""
    xyz = _lin(np.asarray(rgb, dtype=float).reshape(-1, 3)) @ _M_RGB2XYZ.T / _WHITE
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[:, 1] - 16
    return np.stack([L, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def lab_to_rgb(lab):
    lab = np.asarray(lab, dtype=float).reshape(-1, 3)
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    f = np.stack([fx, fy, fz], axis=1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) * 27 / 24389) * _WHITE
    return _gam(xyz @ _M_XYZ2RGB.T)


def in_gamut(lab):
    """True when the Lab colour maps inside sRGB (linear channels within 0..1, 0.2 % slack)."""
    lab = np.asarray(lab, dtype=float).reshape(-1, 3)
    fy = (lab[:, 0] + 16) / 116
    f = np.stack([fy + lab[:, 1] / 500, fy, fy - lab[:, 2] / 200], axis=1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) * 27 / 24389) * _WHITE
    rgb = xyz @ _M_XYZ2RGB.T
    return bool(np.all(rgb > -0.002) and np.all(rgb < 1.002))


def lch(L, C, h):
    """L*, chroma, hue(deg) → hex, chroma shrunk until the colour is inside sRGB."""
    for c in np.arange(C, -1, -2):
        lab = [L, c * math.cos(math.radians(h)), c * math.sin(math.radians(h))]
        if in_gamut(lab):
            return rgb_to_hex(lab_to_rgb(lab)[0])
    return rgb_to_hex(lab_to_rgb([L, 0, 0])[0])


def to_lch(hexc):
    L, a, b = rgb_to_lab([hex_to_rgb(hexc)])[0]
    return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360)


def hue_dist(h1, h2):
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


def fix_contrast(hexc, paper, target, prefer=None):
    """Nudge L* one step at a time (hue fixed) until contrast(hex, paper) >= target. `prefer` = 'lighter' | 'darker'
    | None (away from the paper). Returns (hex, ratio, steps)."""
    L, C, h = to_lch(hexc)
    Lp = to_lch(paper)[0]
    direction = 1 if (prefer == 'lighter' or (prefer is None and L >= Lp)) else -1
    cur, steps = hexc, 0
    while contrast(cur, paper) < target and 0 <= L + direction <= 100 and steps < 120:
        L += direction
        steps += 1
        cur = lch(L, C, h)
    return cur, round(contrast(cur, paper), 2), steps


# ------------------------------------------------------------------------------------------------ pixels → clusters
def load_pixels(path, max_side=160):
    """Image → (chromatic rgb (N,3), neutral rgb (M,3)). Box-reduced so every source pixel counts once."""
    im = Image.open(path).convert('RGBA')
    w, h = im.size
    f = max(1, int(math.ceil(max(w, h) / float(max_side))))
    if f > 1:
        im = im.reduce(f)
    a = np.asarray(im, dtype=np.float64).reshape(-1, 4)
    a = a[a[:, 3] >= 128][:, :3]
    if not len(a):
        return np.zeros((0, 3)), np.zeros((0, 3))
    mx, mn = a.max(axis=1), a.min(axis=1)
    keep = (mn <= 235) & (mx >= 24)
    a = a[keep]; mx, mn = mx[keep], mn[keep]
    grey = (mx - mn) < 12
    return a[~grey], a[grey]


ENGINE = os.environ.get('BRAND_KIT_ENGINE', 'numpy')          # numpy (canonical, seeded, ~0.1 s) | sklearn (cross-check; import ~20 s cold)


def _kmeans(X, k, weights):
    """Weighted k-means on Lab rows → (centres (k,3), weight per centre). The canonical engine is our own seeded
    k-means++ (4 restarts, best inertia) so the result is identical on any machine and any library version;
    ENGINE=sklearn runs scikit-learn's KMeans with the same seed as a cross-check."""
    if ENGINE == 'sklearn':
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=k, n_init=4, random_state=0, max_iter=300).fit(X, sample_weight=weights)
        labels, centres = km.labels_, km.cluster_centers_
    else:
        rng = np.random.default_rng(0)
        best = None
        for _ in range(4):
            c = [X[rng.integers(len(X))]]
            for _ in range(1, k):
                d2 = np.min(((X[:, None, :] - np.array(c)[None]) ** 2).sum(-1), axis=1) * weights
                c.append(X[rng.choice(len(X), p=d2 / d2.sum())])
            c = np.array(c)
            for _ in range(300):
                lab = np.argmin(((X[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
                new = np.array([np.average(X[lab == j], axis=0, weights=weights[lab == j]) if np.any(lab == j) else c[j] for j in range(k)])
                if np.allclose(new, c):
                    break
                c = new
            inertia = float((((X - c[lab]) ** 2).sum(-1) * weights).sum())
            if best is None or inertia < best[0]:
                best = (inertia, lab, c)
        labels, centres = best[1], best[2]
    wsum = np.array([weights[labels == j].sum() for j in range(k)])
    return centres, wsum


def cluster_colours(logo_rgb, site_rgb=None, k=6, site_weight=0.35):
    """Chromatic pixels → sorted clusters [{hex, weight, L, C, h}] (weight = share of all weighted pixels)."""
    parts, wts = [logo_rgb], [np.ones(len(logo_rgb))]
    if site_rgb is not None and len(site_rgb):
        parts.append(site_rgb); wts.append(np.full(len(site_rgb), site_weight))
    rgb = np.concatenate(parts); w = np.concatenate(wts)
    if not len(rgb):
        return []
    X = rgb_to_lab(rgb)
    k = int(min(k, len(np.unique(np.round(X, 0), axis=0))))
    if k <= 1:
        centres, wsum = X.mean(axis=0, keepdims=True), np.array([w.sum()])
    else:
        centres, wsum = _kmeans(X, k, w)
    out = []
    for c, ws in zip(centres, wsum):
        hx = rgb_to_hex(lab_to_rgb(c)[0])
        L, C, h = to_lch(hx)
        out.append({'hex': hx, 'weight': round(float(ws / w.sum()), 4), 'L': round(L, 1), 'C': round(C, 1), 'h': round(h, 1)})
    out.sort(key=lambda d: (-d['weight'], d['hex']))
    return out


def pick_roles(clusters, neutral_rgb):
    """Clusters → {primary, accent, neutral, accent_synthesised}."""
    chroma = [c for c in clusters if c['C'] >= 15] or clusters
    primary = chroma[0] if chroma else {'hex': '#204A56', 'weight': 0, 'L': 29, 'C': 12, 'h': 215}
    cands = [c for c in clusters if c is not primary and c['C'] >= 20 and hue_dist(c['h'], primary['h']) >= 40]
    synth = False
    if cands:
        cands.sort(key=lambda c: (-(math.sqrt(c['weight']) * hue_dist(c['h'], primary['h'])), c['hex']))
        accent = cands[0]['hex']
    else:
        synth = True
        accent = lch(66, 55, (primary['h'] + 150) % 360)
    if len(neutral_rgb):
        med = np.median(neutral_rgb, axis=0)
        neutral = rgb_to_hex(med)
    else:
        neutral = lch(60, 10, primary['h'])
    return {'primary': primary['hex'], 'accent': accent, 'neutral': neutral, 'accent_synthesised': synth}


def derive_tokens(roles, bg, clusters=None):
    """Brand roles + background choice → the flat token values of skin_tokens.example.json, contrast-fixed."""
    Lp, Cp, hp = to_lch(roles['primary'])
    La, Ca, ha = to_lch(roles['accent'])
    t = {}
    if bg == 'dark':
        t['paper'] = lch(15, min(12, Cp * 0.4), hp)
        t['paper2'] = lch(24, min(14, Cp * 0.5), hp)
        t['black'] = lch(6, min(6, Cp * 0.2), hp)
        t['ink'] = lch(95, 4, hp)
        t['ink-soft'] = lch(88, 12, 85)
        t['muted'] = lch(70, 14, hp)
        t['accent'] = lch(max(La, 58), min(Ca, 70), ha)
        t['gold'] = lch(82, 48, 85)
        prefer = 'lighter'
    else:
        t['paper'] = lch(95, min(4, Cp * 0.2), hp)
        t['paper2'] = lch(90, min(6, Cp * 0.3), hp)
        t['black'] = t['paper']                                         # head fade plate matches the light ground
        t['ink'] = lch(15, min(10, Cp * 0.5), hp)
        t['ink-soft'] = lch(35, min(12, Cp * 0.5), hp)
        t['muted'] = lch(48, 12, hp)
        t['accent'] = lch(min(La, 52), min(Ca, 75), ha)
        t['gold'] = lch(58, 55, 80)
        prefer = 'darker'
    ratios = {}
    for k, mn in CONTRAST_MIN.items():
        t[k], ratios[k], _ = fix_contrast(t[k], t['paper'], mn, prefer)
    ratios['paper2'] = round(contrast(t['paper2'], t['paper']), 2)
    return t, ratios


def compose_tokens(given, bg):
    """Hand-picked colours (paper + accent at least) → the full token set. Missing tokens are derived from the paper's
    hue exactly as `derive_tokens` would, given ones win, then every text token is contrast-fixed against the paper."""
    paper = given.get('paper') or ('#1A2430' if bg == 'dark' else '#F4F1EA')
    accent = given.get('accent') or lch(66 if bg == 'dark' else 50, 55, 40)
    Lp, Cp, hp = to_lch(paper)
    base, _ = derive_tokens({'primary': lch(50, max(Cp, 20), hp), 'accent': accent, 'neutral': lch(60, 8, hp)}, bg)
    t = dict(base)
    t['paper'] = paper
    t.setdefault('paper2', lch(Lp + (9 if bg == 'dark' else -5), min(Cp + 2, 16), hp))
    if 'paper2' not in given:
        t['paper2'] = lch(Lp + (9 if bg == 'dark' else -5), min(Cp + 2, 16), hp)
    if 'black' not in given:
        t['black'] = lch(max(2, Lp - 9), min(Cp, 6), hp) if bg == 'dark' else paper
    for k in ('ink', 'ink-soft', 'muted', 'accent', 'gold', 'paper2', 'black'):
        if given.get(k):
            t[k] = given[k]
    ratios = {}
    prefer = 'lighter' if bg == 'dark' else 'darker'
    for k, mn in CONTRAST_MIN.items():
        t[k], ratios[k], _ = fix_contrast(t[k], t['paper'], mn, prefer)
    ratios['paper2'] = round(contrast(t['paper2'], t['paper']), 2)
    return t, ratios


def type_pairing(mood):
    d, b, m, wt = PAIRINGS[mood]
    return {'mood': mood, 'display': d, 'body': b, 'mono': m, 'display_weight': wt,
            'display_file': FACES[d][1] if wt >= 600 else FACES[d][0], 'body_file': FACES[b][0], 'body_bold_file': FACES[b][1],
            'mono_file': FACES[m][0], 'title_css': FACES[d][2], 'body_css': FACES[b][2], 'mono_css': FACES[m][2],
            'sizes_stage_px': {'title': 64, 'subtitle': 22, 'body': 22, 'label': 13, 'mono': 18}}


MOOD_MOTION = {'editorial': 'calm', 'corporate': 'medium', 'technical': 'medium', 'friendly': 'high'}
MOOD_CAPTION = {'editorial': 'documentary', 'corporate': 'anchor', 'technical': 'broadcast', 'friendly': 'keynote'}


def build_skin(name, tokens, ratios, typ, motion, caption_style, brand, bg, when='', content=None, seams=None):
    """Assemble the skin document (templates/skin_tokens.example.json shape + the v5 sections)."""
    content = content or {}
    T = {
        'paper':      {'type': 'color', 'default': tokens['paper'], 'role': 'style', 'description': 'stage background (top of the gradient)'},
        'paper2':     {'type': 'color', 'default': tokens['paper2'], 'role': 'style', 'description': 'stage background (bottom of the gradient)'},
        'ink':        {'type': 'color', 'default': tokens['ink'], 'role': 'style', 'description': 'title and lower-third text'},
        'ink-soft':   {'type': 'color', 'default': tokens['ink-soft'], 'role': 'style', 'description': 'subtitle text'},
        'muted':      {'type': 'color', 'default': tokens['muted'], 'role': 'style', 'description': 'caption line, lower-third label, glow'},
        'accent':     {'type': 'color', 'default': tokens['accent'], 'role': 'style', 'description': 'rule, highlight boxes, lower-third edge — one focal element per beat'},
        'gold':       {'type': 'color', 'default': tokens['gold'], 'role': 'style', 'description': 'first line of the closing card'},
        'black':      {'type': 'color', 'default': tokens['black'], 'role': 'style', 'description': 'head fade plate'},
        'title-font': {'type': 'font', 'default': typ['title_css'], 'role': 'style', 'description': 'title + closing card face (local system family)'},
        'body-font':  {'type': 'font', 'default': typ['body_css'], 'role': 'style', 'description': 'subtitles, captions, lower-thirds'},
        'title-size': {'type': 'number', 'default': 64, 'min': 44, 'max': 84, 'step': 2, 'unit': 'px', 'role': 'layout', 'description': 'title h1 size on the 1280x720 stage'},
        'title':      {'type': 'string', 'default': content.get('title', 'Monday, answered.'), 'role': 'content', 'portrays': ['subject_tagline'], 'binds': '#tTitle'},
        'subtitle':   {'type': 'string', 'default': content.get('subtitle', 'From an analyst’s notebook to a question anyone can ask'), 'role': 'content', 'portrays': ['subject_tagline'], 'binds': '#tSub'},
        'caption':    {'type': 'string', 'default': content.get('caption', 'Fictional company · synthetic data'), 'role': 'content', 'portrays': ['authority_badge'], 'binds': '#tCap',
                       'description': 'the honesty line; keep it unless the film shows a real customer’s own data with their approval'},
        'logo':       {'type': 'image', 'default': content.get('logo'), 'role': 'content', 'portrays': ['subject_logo'], 'binds': '#logo', 'description': 'local file inside the project (assets/…); null hides the slot'},
        'density':    {'type': 'enum', 'default': 'booth', 'options': ['booth', 'desk'], 'role': 'layout', 'description': 'booth = larger type, fewer words on screen'},
    }
    css = ':root{' + ';'.join('--%s:%s' % (k, tokens[k]) for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black')) + \
          ';--title-font:%s;--body-font:%s;--title-size:64px}' % (typ['title_css'], typ['body_css'])
    return {
        'name': name, 'label': content.get('label', name.replace('-', ' ').title()), 'when_to_use': when, 'background': bg,
        'mood': typ['mood'], 'tokens': T, 'forbidden_tokens': list(FORBIDDEN), 'css_snippet': css,
        'type': typ, 'motion': motion, 'captions': {'style': caption_style, 'ink': 'light' if bg == 'dark' else 'dark'},
        'seams': seams or {'current': 'x-1', 'allowed': ['cut-the-curve', 'inverse zoom-through'], 'max_techniques': 3},
        'brand': brand, 'contrast': ratios,
        'generated_by': 'tools/brand_kit.py (deterministic: same inputs → identical file)',
    }


def flat_tokens(skin):
    """Skin document → {id: value} for the sheet and the checks."""
    return {k: v.get('default') if isinstance(v, dict) else v for k, v in skin.get('tokens', {}).items()}


# ------------------------------------------------------------------------------------------------ the style sheet
def _font(file, size, fonts_dir=None):
    for d in (fonts_dir, FONTS_DIR):
        if d and file and os.path.exists(os.path.join(d, file)):
            try:
                return ImageFont.truetype(os.path.join(d, file), size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _rgb(hexc, alpha=None):
    r, g, b = hex_to_rgb(hexc)
    return (r, g, b) if alpha is None else (r, g, b, alpha)


def _blend(a, b, u):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return tuple(int(round(x + (y - x) * u)) for x, y in zip(ra, rb))


def _gradient(w, h, top, bottom):
    im = Image.new('RGB', (w, h))
    px = im.load()
    for y in range(h):
        c = _blend(top, bottom, y / max(1, h - 1))
        for x in range(w):
            px[x, y] = c
    return im


def _tracked(draw, xy, text, font, fill, tracking=0.0):
    """Draw text with letter-spacing (tracking in em of the font size)."""
    x, y = xy
    size = font.size if hasattr(font, 'size') else 12
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking * size
    return x


def _product_plate(w, h, paper):
    """A synthetic, fictional product window (grey chrome, cards, lines) — never real pixels."""
    im = Image.new('RGB', (w, h), (238, 239, 241))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, int(h * 0.09)], fill=(222, 224, 228))
    for i in range(3):
        d.ellipse([12 + i * 18, int(h * 0.03), 22 + i * 18, int(h * 0.03) + 10], fill=(190, 192, 198))
    d.rectangle([0, int(h * 0.09), int(w * 0.18), h], fill=(228, 230, 234))
    for i in range(7):
        d.rectangle([14, int(h * 0.14) + i * 26, int(w * 0.15), int(h * 0.14) + i * 26 + 9], fill=(200, 203, 210))
    x0 = int(w * 0.21)
    for j in range(3):
        xx = x0 + j * int(w * 0.26)
        d.rectangle([xx, int(h * 0.14), xx + int(w * 0.23), int(h * 0.36)], fill=(252, 252, 253), outline=(214, 216, 222))
        d.rectangle([xx + 12, int(h * 0.18), xx + int(w * 0.12), int(h * 0.18) + 8], fill=(206, 209, 216))
        d.rectangle([xx + 12, int(h * 0.25), xx + int(w * 0.18), int(h * 0.25) + 16], fill=(170, 174, 184))
    d.rectangle([x0, int(h * 0.42), w - 20, h - 20], fill=(252, 252, 253), outline=(214, 216, 222))
    for i in range(6):
        y = int(h * 0.48) + i * 22
        d.rectangle([x0 + 14, y, x0 + 14 + int(w * 0.5) - (i % 3) * 40, y + 8], fill=(214, 216, 222))
    return im


def _keepout(d, w, h, ink):
    y = int(h * KEEPOUT)
    for x in range(0, w, 12):
        d.line([x, y, x + 6, y], fill=_rgb(ink, 110), width=1)


def _rounded(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def frame_title(T, F, w, h, content):
    im = _gradient(w, h, T['paper'], T['paper2']).convert('RGBA')
    d = ImageDraw.Draw(im)
    title = content.get('title') or 'Monday, answered.'
    f1 = _font(F['display_file'], int(F['sizes_stage_px']['title'] * w / STAGE[0]), F.get('fonts_dir'))
    f2 = _font(F['body_file'], int(F['sizes_stage_px']['subtitle'] * w / STAGE[0]), F.get('fonts_dir'))
    f3 = _font(F['body_file'], int(F['sizes_stage_px']['label'] * w / STAGE[0]), F.get('fonts_dir'))
    x = int(w * 0.07)
    y = int(h * 0.30)
    d.text((x, y), title, font=f1, fill=_rgb(T['ink']))
    y += f1.size + int(h * 0.04)
    d.rectangle([x, y, x + int(w * 0.09), y + 2], fill=_rgb(T['accent']))
    y += int(h * 0.05)
    d.text((x, y), content.get('subtitle') or 'From an analyst’s notebook to a question anyone can ask', font=f2, fill=_rgb(T['ink-soft']))
    _tracked(d, (x, int(h * 0.76)), (content.get('caption') or 'Fictional company · synthetic data').upper(), f3, _rgb(T['muted']), 0.12)
    _keepout(d, w, h, T['ink'])
    return im.convert('RGB')


def frame_caption(T, F, w, h, style, ink_mode):
    im = _product_plate(w, h, T['paper']).convert('RGBA')
    ov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f = _font(F['body_bold_file'] if style in ('broadcast', 'anchor', 'conference') else F['body_file'], int(24 * w / STAGE[0]), F.get('fonts_dir'))
    words = ['Which', 'regions', 'missed', 'their', 'target']
    active = 2
    active_fill = _rgb(T['accent'])
    widths = [d.textlength(wd, font=f) for wd in words]
    gap = f.size * 0.33
    tw = sum(widths) + gap * (len(words) - 1)
    pad = f.size * 0.6
    x0 = (w - tw) / 2
    y0 = h * 0.86 - f.size
    box = [x0 - pad, y0 - pad * 0.45, x0 + tw + pad, y0 + f.size + pad * 0.55]
    if style in ('broadcast', 'anchor', 'conference', 'clipwipe'):
        _rounded(d, box, 4 if style != 'conference' else 0, _rgb(T['paper'], 200))
        text_fill = _rgb(T['ink'])
    elif style == 'ink':
        _rounded(d, box, 2, _rgb(T['ink'], 235))
        text_fill = _rgb(T['paper'])
        if contrast(T['accent'], T['ink']) < 3.0:                     # inverted pill: the active word needs >= 3:1 on the ink
            active_fill = _rgb(T['gold']) if contrast(T['gold'], T['ink']) >= 3.0 else _rgb(T['paper2'])
    elif style == 'typewriter':
        f = _font(F['mono_file'], int(22 * w / STAGE[0]), F.get('fonts_dir'))
        widths = [d.textlength(wd, font=f) for wd in words]; tw = sum(widths) + gap * (len(words) - 1); x0 = (w - tw) / 2
        _rounded(d, [x0 - pad, y0 - pad * 0.45, x0 + tw + pad, y0 + f.size + pad * 0.55], 0, _rgb(T['paper'], 215))
        text_fill = _rgb(T['ink'])
    else:                                                               # documentary / keynote: bare text, soft shadow
        text_fill = _rgb(T['ink']) if ink_mode == 'light' else _rgb(T['paper'])
        for dx, dy in ((1, 1), (2, 2)):
            x = x0
            for wd, ww in zip(words, widths):
                d.text((x + dx, y0 + dy), wd, font=f, fill=(0, 0, 0, 90)); x += ww + gap
        if ink_mode == 'light':                                         # a dark plate needs the ink to read on a bright screen
            text_fill = _rgb(T['paper'])
    x = x0
    for i, (wd, ww) in enumerate(zip(words, widths)):
        d.text((x, y0), wd, font=f, fill=active_fill if i == active else text_fill)
        x += ww + gap
    lab = _font(F['mono_file'], int(12 * w / STAGE[0]), F.get('fonts_dir'))
    d.text((int(w * 0.02), int(h * 0.92)), 'caption style: %s · active word in accent' % style, font=lab, fill=(60, 60, 64, 255))
    _keepout(d, w, h, '#101010')
    return Image.alpha_composite(im, ov).convert('RGB')


def frame_kpi(T, F, w, h):
    im = _gradient(w, h, T['paper'], T['paper2']).convert('RGBA')
    d = ImageDraw.Draw(im)
    fl = _font(F['body_file'], int(13 * w / STAGE[0]), F.get('fonts_dir'))
    fv = _font(F['display_file'], int(56 * w / STAGE[0]), F.get('fonts_dir'))
    fs = _font(F['body_file'], int(16 * w / STAGE[0]), F.get('fonts_dir'))
    tiles = [('TIME TO ANSWER', '4.2 min', 'was a day'), ('LATE DELIVERIES', '-38 %', 'week on week'), ('REGIONS', '12', 'all covered')]
    tw = int(w * 0.27); gap = int(w * 0.03); x = int((w - (tw * 3 + gap * 2)) / 2); y = int(h * 0.22)
    for i, (lab, val, sub) in enumerate(tiles):
        box = [x, y, x + tw, y + int(h * 0.44)]
        d.rectangle(box, outline=_rgb(T['muted'], 140), width=2)
        if i == 1:
            d.rectangle([x, y, x + tw, y + 3], fill=_rgb(T['accent']))
        _tracked(d, (x + 16, y + 16), lab, fl, _rgb(T['muted']), 0.12)
        d.text((x + 16, y + int(h * 0.13)), val, font=fv, fill=_rgb(T['accent']) if i == 1 else _rgb(T['ink']))
        d.text((x + 16, y + int(h * 0.33)), sub, font=fs, fill=_rgb(T['ink-soft']))
        x += tw + gap
    lab = _font(F['mono_file'], int(12 * w / STAGE[0]), F.get('fonts_dir'))
    d.text((int(w * 0.07), int(h * 0.75)), 'sample values · a film shows only figures traced in claims.json', font=lab, fill=_rgb(T['muted']))
    _keepout(d, w, h, T['ink'])
    return im.convert('RGB')


def frame_lower_third(T, F, w, h):
    im = _product_plate(w, h, T['paper']).convert('RGBA')
    ov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    fl = _font(F['body_bold_file'], int(13 * w / STAGE[0]), F.get('fonts_dir'))
    ft = _font(F['body_file'], int(22 * w / STAGE[0]), F.get('fonts_dir'))
    x, y = int(w * 0.06), int(h * 0.62)
    bw, bh = int(w * 0.46), int(h * 0.15)
    d.rectangle([x, y, x + bw, y + bh], fill=_rgb(T['paper'], 225))
    d.rectangle([x, y, x + 3, y + bh], fill=_rgb(T['accent']))
    _tracked(d, (x + 18, y + 10), 'THE ANALYST', fl, _rgb(T['muted']), 0.12)
    d.text((x + 18, y + 10 + fl.size + 6), 'Build it where the data is.', font=ft, fill=_rgb(T['ink']))
    _keepout(d, w, h, '#101010')
    return Image.alpha_composite(im, ov).convert('RGB')


def frame_chart(T, F, w, h):
    im = _gradient(w, h, T['paper'], T['paper2']).convert('RGBA')
    d = ImageDraw.Draw(im)
    ft = _font(F['body_file'], int(22 * w / STAGE[0]), F.get('fonts_dir'))
    fm = _font(F['mono_file'], int(13 * w / STAGE[0]), F.get('fonts_dir'))
    d.text((int(w * 0.07), int(h * 0.12)), 'Late deliveries by region', font=ft, fill=_rgb(T['ink']))
    vals = [(('North', 0.42)), ('East', 0.31), ('South', 0.88), ('West', 0.55), ('Central', 0.23)]
    x0, y0, x1, y1 = int(w * 0.09), int(h * 0.26), int(w * 0.93), int(h * 0.70)
    d.line([x0, y1, x1, y1], fill=_rgb(T['muted'], 160), width=1)
    n = len(vals); bw = int((x1 - x0) / n * 0.56); step = (x1 - x0) / n
    peak = max(v for _, v in vals)
    for i, (lab, v) in enumerate(vals):
        bx = int(x0 + i * step + (step - bw) / 2)
        top = int(y1 - (y1 - y0) * v)
        d.rectangle([bx, top, bx + bw, y1], fill=_rgb(T['accent']) if v == peak else _rgb(T['muted']))
        d.text((bx, y1 + 8), lab, font=fm, fill=_rgb(T['ink-soft']))
        d.text((bx, top - fm.size - 6), '%d' % round(v * 100), font=fm, fill=_rgb(T['ink']))
    d.text((int(w * 0.07), int(h * 0.76)), 'sample values · the one focal bar takes the accent', font=fm, fill=_rgb(T['muted']))
    _keepout(d, w, h, T['ink'])
    return im.convert('RGB')


def frame_close(T, F, w, h):
    im = _gradient(w, h, T['paper'], T['paper2']).convert('RGBA')
    d = ImageDraw.Draw(im)
    f1 = _font(F['display_file'], int(44 * w / STAGE[0]), F.get('fonts_dir'))
    fc = _font(F['body_file'], int(13 * w / STAGE[0]), F.get('fonts_dir'))
    lines = [('One notebook.', T['gold']), ('One question.', T['ink']), ('One answer the whole team can trust.', T['ink'])]
    x, y = int(w * 0.07), int(h * 0.22)
    for txt, col in lines:
        d.text((x, y), txt, font=f1, fill=_rgb(col))
        y += int(f1.size * 1.25)
    d.text((x, int(h * 0.88)), CREDIT, font=fc, fill=_rgb(T['muted']))
    _keepout(d, w, h, T['ink'])
    return im.convert('RGB')


def style_sheet(skin, out_png, fonts_dir=None):
    """Six half-stage frames (640x360) in a 3x2 grid with labels; header = name · bg · type · contrast · motion."""
    T = flat_tokens(skin)
    F = dict(skin['type']); F['fonts_dir'] = fonts_dir
    content = {'title': T.get('title'), 'subtitle': T.get('subtitle'), 'caption': T.get('caption')}
    cap = skin.get('captions', {})
    fw, fh, lab_h, pad, head = 640, 360, 34, 20, 64
    frames = [('TITLE CARD', frame_title(T, F, fw, fh, content)), ('CAPTION LANE', frame_caption(T, F, fw, fh, cap.get('style', 'documentary'), cap.get('ink', 'light'))),
              ('KPI TILES', frame_kpi(T, F, fw, fh)), ('LOWER THIRD', frame_lower_third(T, F, fw, fh)),
              ('CHART', frame_chart(T, F, fw, fh)), ('CLOSE + CREDIT', frame_close(T, F, fw, fh))]
    W = fw * 3 + pad * 4
    H = head + (fh + lab_h + pad) * 2 + pad
    sheet = Image.new('RGB', (W, H), (244, 241, 234))
    d = ImageDraw.Draw(sheet)
    fh1 = _font('consola.ttf', 18, fonts_dir); fh2 = _font('consola.ttf', 13, fonts_dir)
    m = skin.get('motion', {}); c = skin.get('contrast', {})
    d.text((pad, 14), '%s  ·  %s ground  ·  %s / %s / %s' % (skin.get('label', skin.get('name', 'skin')), skin.get('background', '?'),
                                                              F.get('display', '?'), F.get('body', '?'), F.get('mono', '?')), font=fh1, fill=(27, 27, 27))
    d.text((pad, 40), 'contrast vs paper  ink %.1f  muted %.1f  accent %.1f  gold %.1f   ·   motion %s: enter %.2f s  exit %.2f s  push %.1f s x%.1f  hold %.1f s   ·   captions %s'
           % (c.get('ink', 0), c.get('muted', 0), c.get('accent', 0), c.get('gold', 0), m.get('profile', '?'), m.get('enter_s', 0), m.get('exit_s', 0),
              m.get('push_s', 0), (m.get('push_scale') or [0, 0])[1], m.get('hold_s', 0), cap.get('style', '?')), font=fh2, fill=(90, 90, 90))
    for i, (label, fr) in enumerate(frames):
        col, row = i % 3, i // 3
        x = pad + col * (fw + pad); y = head + row * (fh + lab_h + pad)
        sheet.paste(fr, (x, y))
        d.rectangle([x - 1, y - 1, x + fw, y + fh], outline=(27, 27, 27), width=1)
        d.text((x, y + fh + 8), '%d  %s' % (i + 1, label), font=fh2, fill=(27, 27, 27))
    sw = [(k, T[k]) for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black') if k in T]
    x = W - pad - len(sw) * 54
    for k, hx in sw:
        d.rectangle([x, 12, x + 46, 46], fill=_rgb(hx), outline=(120, 120, 120))
        d.text((x, 48), k[:7], font=_font('consola.ttf', 10, fonts_dir), fill=(60, 60, 60))
        x += 54
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    sheet.save(out_png, 'PNG', optimize=True)
    return out_png


# ------------------------------------------------------------------------------------------------ check
def check_skin(skin):
    """Design-adherence findings for a skin document → list of strings (empty = pass)."""
    E = []
    tok = skin.get('tokens') or {}
    for k in TOKEN_IDS:
        if k not in tok:
            E.append('token missing: %s' % k)
    T = flat_tokens(skin)
    for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black'):
        v = T.get(k)
        if not isinstance(v, str) or not v.startswith('#') or len(v) not in (4, 7):
            E.append('token %s is not a hex colour: %r' % (k, v)); continue
        if v.upper() in ('#000000', '#FFFFFF', '#000', '#FFF'):
            E.append('token %s is pure %s — tint it toward the ground hue' % (k, v))
    if all(isinstance(T.get(k), str) and T[k].startswith('#') for k in CONTRAST_MIN) and isinstance(T.get('paper'), str):
        for k, mn in CONTRAST_MIN.items():
            r = contrast(T[k], T['paper'])
            if r < mn:
                E.append('contrast %s vs paper %.2f < %.1f' % (k, r, mn))
    for k in FORBIDDEN:
        if k in tok:
            E.append('forbidden token present: %s' % k)
    typ = skin.get('type') or {}
    for role in ('display', 'body', 'mono'):
        if typ.get(role) and typ[role] not in FACES:
            E.append('type %s "%s" is not in the local font table %s' % (role, typ[role], sorted(FACES)))
    m = skin.get('motion') or {}
    if m:
        if not (0.1 <= m.get('enter_s', 0) <= 0.8):
            E.append('motion enter_s %.2f outside 0.1-0.8 s (a longer entry is a stagger of several elements)' % m.get('enter_s', 0))
        if m.get('exit_s', 0) > m.get('enter_s', 0):
            E.append('motion exit_s %.2f > enter_s %.2f (exits run ~75 %% of entries)' % (m.get('exit_s', 0), m.get('enter_s', 0)))
        if m.get('stagger_total_s', 0) > 0.5:
            E.append('motion stagger_total_s %.2f > 0.5 s' % m['stagger_total_s'])
        if not (0.04 <= m.get('per_item_s', 0.05) <= 0.08):
            E.append('motion per_item_s %.3f outside 0.04-0.08 s' % m.get('per_item_s', 0))
        if not (0.9 <= m.get('push_s', 1.0) <= 2.0):
            E.append('motion push_s %.2f outside 0.9-2.0 s' % m.get('push_s', 0))
        ps = m.get('push_scale') or [1.3, 1.6]
        if not (1.0 < ps[0] <= ps[1] <= 2.0):
            E.append('motion push_scale %s outside x1.0-x2.0 (zoom budget)' % ps)
        if m.get('hold_s', 2.0) < 1.0:
            E.append('motion hold_s %.2f < 1.0 s dwell' % m['hold_s'])
    cap = skin.get('captions') or {}
    if cap.get('style') and cap['style'] not in CAPTION_STYLES:
        E.append('caption style "%s" not in %s' % (cap['style'], CAPTION_STYLES))
    sm = skin.get('seams') or {}
    bad = [t for t in sm.get('allowed', []) if t not in SEAM_TECHNIQUES]
    if bad:
        E.append('seam techniques unknown: %s' % bad)
    if len(sm.get('allowed', [])) > 3:
        E.append('%d seam techniques allowed — a film repeats 2-3' % len(sm['allowed']))
    if sm.get('current', 'x-1') not in ('x-1', 'x+1', 'y-1', 'y+1'):
        E.append('seam current "%s" must be an x/y vector' % sm.get('current'))
    if not skin.get('when_to_use'):
        E.append('when_to_use is empty — one line that says when this skin fits')
    return E


# ------------------------------------------------------------------------------------------------ extract
def extract(logo, site=None, bg='dark', mood='editorial', name='brand', content=None, when=''):
    chrom, grey = load_pixels(logo)
    site_chrom = None
    if site:
        sc, sg = load_pixels(site)
        site_chrom = sc
        grey = np.concatenate([grey, sg]) if len(sg) else grey
    clusters = cluster_colours(chrom, site_chrom)
    if bg == 'auto':
        meanL = float(rgb_to_lab(chrom)[:, 0].mean()) if len(chrom) else 50.0
        bg = 'light' if meanL < 45 else 'dark'
    roles = pick_roles(clusters, grey)
    tokens, ratios = derive_tokens(roles, bg, clusters)
    typ = type_pairing(mood)
    motion = dict(MOTION_PROFILES[MOOD_MOTION[mood]])
    brand = {'logo': os.path.basename(logo), 'site': os.path.basename(site) if site else None, 'clusters': clusters,
             'primary': roles['primary'], 'accent': roles['accent'], 'neutral': roles['neutral'],
             'accent_synthesised': roles['accent_synthesised'], 'pixels': {'chromatic': int(len(chrom)), 'neutral': int(len(grey))}}
    when = when or ('%s brand on a %s ground; %s pairing' % (name, bg, mood))
    return build_skin(name, tokens, ratios, typ, motion, MOOD_CAPTION[mood], brand, bg, when, content)


def write_json(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write('\n')


# ------------------------------------------------------------------------------------------------ selftest
def _synthetic_logo(path, seed=0):
    """A fictional 'Acme' mark: two overlapping discs (navy + coral) with a grey wordmark bar on transparent."""
    rng = np.random.default_rng(seed)
    im = Image.new('RGBA', (320, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([20, 20, 180, 180], fill=(16, 64, 112, 255))
    d.ellipse([130, 70, 220, 160], fill=(232, 104, 72, 255))
    d.rectangle([240, 70, 310, 130], fill=(120, 124, 130, 255))
    px = im.load()
    for _ in range(600):                                              # a little anti-aliasing noise on the mark edge
        x, y = int(rng.integers(20, 230)), int(rng.integers(20, 180))
        r, g, b, a = px[x, y]
        if a:
            px[x, y] = (min(255, r + 6), min(255, g + 6), min(255, b + 6), a)
    im.save(path)
    return path


def selftest():
    import hashlib, tempfile
    d = tempfile.mkdtemp(prefix='brand_kit_')
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)

    logo = _synthetic_logo(os.path.join(d, 'acme_logo.png'))
    outs = []
    for i in (1, 2):
        skin = extract(logo, bg='dark', mood='editorial', name='acme-test')
        jp, pp = os.path.join(d, 'skin_%d.json' % i), os.path.join(d, 'sheet_%d.png' % i)
        write_json(skin, jp); style_sheet(skin, pp)
        outs.append((hashlib.sha256(open(jp, 'rb').read()).hexdigest(), hashlib.sha256(open(pp, 'rb').read()).hexdigest()))
    t(outs[0] == outs[1], 'deterministic: skin JSON + sheet PNG byte-identical across two runs')
    skin = extract(logo, bg='dark', mood='editorial', name='acme-test')
    T = flat_tokens(skin)
    Lp, Cp, hp = to_lch(skin['brand']['primary'])
    t(250 <= hp <= 300, 'primary is the navy disc (Lab hue %.0f)' % hp)
    La, Ca, ha = to_lch(skin['brand']['accent'])
    t(20 <= ha <= 60 and not skin['brand']['accent_synthesised'], 'accent is the coral disc (Lab hue %.0f), not synthesised' % ha)
    t(all(contrast(T[k], T['paper']) >= v for k, v in CONTRAST_MIN.items()), 'contrast: ink %.1f muted %.1f accent %.1f gold %.1f' %
      tuple(contrast(T[k], T['paper']) for k in ('ink', 'muted', 'accent', 'gold')))
    t(not check_skin(skin), 'check: extracted skin passes the design lint (%s)' % (check_skin(skin) or 'clean'))
    light = extract(logo, bg='light', mood='corporate', name='acme-light')
    TL = flat_tokens(light)
    t(to_lch(TL['paper'])[0] > 90 and contrast(TL['ink'], TL['paper']) >= 7, 'light ground: paper L* %.0f, ink contrast %.1f' % (to_lch(TL['paper'])[0], contrast(TL['ink'], TL['paper'])))
    auto = extract(logo, bg='auto', mood='technical', name='acme-auto')
    t(auto['background'] in ('dark', 'light'), 'auto background chose %s' % auto['background'])
    bad = json.loads(json.dumps(skin)); bad['tokens']['ink']['default'] = '#FFFFFF'; bad['motion']['enter_s'] = 1.4; bad['captions']['style'] = 'neon'
    E = check_skin(bad)
    t(any('pure' in e for e in E) and any('enter_s' in e for e in E) and any('caption style' in e for e in E), 'check: catches pure white, a 1.4 s entry and an unknown caption style (%d findings)' % len(E))
    sheet = Image.open(os.path.join(d, 'sheet_1.png'))
    t(sheet.size[0] == 2000 and sheet.size[1] > 700, 'sheet is %dx%d with six frames' % sheet.size)
    skins = sorted(f for f in os.listdir(SKINS_DIR) if f.endswith('.json')) if os.path.isdir(SKINS_DIR) else []
    if skins:
        bad_skins = {f: check_skin(json.load(open(os.path.join(SKINS_DIR, f), encoding='utf-8'))) for f in skins}
        bad_skins = {k: v for k, v in bad_skins.items() if v}
        t(not bad_skins, 'skins/: %d shipped skins pass check (%s)' % (len(skins), bad_skins or 'clean'))
    print('selftest %s  (%s)' % ('PASS' if ok else 'FAIL', d))
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ CLI
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='brand_kit.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', choices=['extract', 'compose', 'check'], help='extract a skin from a logo | compose from hand-picked colours | check a skin JSON')
    ap.add_argument('skin_path', nargs='?', help='for check: the skin JSON')
    ap.add_argument('--logo', help='logo PNG (SVG: rasterise first, e.g. with a browser or Inkscape)')
    ap.add_argument('--site', help='optional website screenshot PNG/JPG (weighs 0.35 of the logo)')
    ap.add_argument('--bg', default='dark', choices=['dark', 'light', 'auto'])
    ap.add_argument('--mood', default='editorial', choices=MOODS)
    ap.add_argument('--name', default='brand')
    ap.add_argument('--title'); ap.add_argument('--subtitle'); ap.add_argument('--caption'); ap.add_argument('--when', default='')
    for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black'):
        ap.add_argument('--' + k, dest='tok_' + k.replace('-', '_'), help='compose: hex for token %s' % k)
    ap.add_argument('--label', help='compose: display name of the skin')
    ap.add_argument('--profile', choices=sorted(MOTION_PROFILES), help='compose: motion profile (default from --mood)')
    ap.add_argument('--caption-style', dest='caption_style', choices=CAPTION_STYLES, help='compose: caption lane style (default from --mood)')
    ap.add_argument('--seams', help='compose: comma list of allowed seam techniques (default "cut-the-curve,inverse zoom-through")')
    ap.add_argument('--out', help='skin_tokens.json path (extract)')
    ap.add_argument('--sheet', help='style sheet PNG path')
    ap.add_argument('--from-skin', dest='from_skin', help='draw the sheet (and check) for an existing skin JSON')
    ap.add_argument('--fonts-dir', dest='fonts_dir', help='override the Windows Fonts folder')
    ap.add_argument('--json', action='store_true', help='print the resulting skin / findings as JSON')
    a = ap.parse_args(argv)

    if a.from_skin:
        skin = json.load(open(a.from_skin, encoding='utf-8'))
        E = check_skin(skin)
        out = a.sheet or os.path.join(os.path.dirname(os.path.abspath(a.from_skin)), 'sheets', skin.get('name', 'skin') + '.png')
        style_sheet(skin, out, a.fonts_dir)
        if a.json:
            print(json.dumps({'skin': skin.get('name'), 'sheet': out, 'findings': E}, indent=1))
        else:
            print('sheet  %s' % out)
            for e in E:
                print('  FINDING  %s' % e)
        return 1 if E else 0
    if a.cmd == 'check':
        if not a.skin_path:
            ap.print_usage(); return 2
        skin = json.load(open(a.skin_path, encoding='utf-8'))
        E = check_skin(skin)
        print(json.dumps({'skin': skin.get('name'), 'findings': E}, indent=1) if a.json else ('check  %s  %s' % (skin.get('name'), 'PASS' if not E else '\n  '.join([''] + E))))
        return 1 if E else 0
    if a.cmd == 'compose':
        if a.bg == 'auto':
            print('compose needs --bg dark|light', file=sys.stderr); return 2
        given = {k: getattr(a, 'tok_' + k.replace('-', '_')) for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black')}
        given = {k: v for k, v in given.items() if v}
        tokens, ratios = compose_tokens(given, a.bg)
        typ = type_pairing(a.mood)
        motion = dict(MOTION_PROFILES[a.profile or MOOD_MOTION[a.mood]])
        seams = {'current': 'x-1', 'allowed': [x.strip() for x in (a.seams or 'cut-the-curve,inverse zoom-through').split(',') if x.strip()], 'max_techniques': 3}
        content = {k: v for k, v in (('title', a.title), ('subtitle', a.subtitle), ('caption', a.caption), ('label', a.label)) if v}
        brand = {'source': 'composed from hand-picked colours', 'given': given}
        skin = build_skin(a.name, tokens, ratios, typ, motion, a.caption_style or MOOD_CAPTION[a.mood], brand, a.bg, a.when, content, seams)
        out = a.out or os.path.join(SKINS_DIR, a.name + '.json')
        write_json(skin, out)
        E = check_skin(skin)
        sheet = a.sheet
        if sheet:
            style_sheet(skin, sheet, a.fonts_dir)
        if a.json:
            print(json.dumps({'skin': out, 'sheet': sheet, 'tokens': flat_tokens(skin), 'contrast': ratios, 'findings': E}, indent=1, ensure_ascii=False))
        else:
            print('skin   %s' % out + (('\nsheet  ' + sheet) if sheet else ''))
            for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold'):
                print('  %-8s %s   contrast %.2f' % (k, tokens[k], contrast(tokens[k], tokens['paper'])))
            for e in E:
                print('  FINDING  %s' % e)
        return 1 if E else 0
    if a.cmd == 'extract':
        if not a.logo or not os.path.exists(a.logo):
            print('extract needs --logo <png>', file=sys.stderr); return 2
        content = {k: v for k, v in (('title', a.title), ('subtitle', a.subtitle), ('caption', a.caption)) if v}
        skin = extract(a.logo, a.site, a.bg, a.mood, a.name, content, a.when)
        out = a.out or 'skin_tokens.json'
        write_json(skin, out)
        sheet = a.sheet or os.path.join(os.path.dirname(os.path.abspath(out)), 'style_sheet.png')
        style_sheet(skin, sheet, a.fonts_dir)
        E = check_skin(skin)
        if a.json:
            print(json.dumps({'skin': out, 'sheet': sheet, 'tokens': flat_tokens(skin), 'contrast': skin['contrast'], 'brand': skin['brand'], 'findings': E}, indent=1, ensure_ascii=False))
        else:
            print('skin   %s\nsheet  %s' % (out, sheet))
            for k in ('paper', 'ink', 'accent', 'muted', 'gold'):
                print('  %-8s %s   contrast %.2f' % (k, flat_tokens(skin)[k], contrast(flat_tokens(skin)[k], flat_tokens(skin)['paper'])))
            for e in E:
                print('  FINDING  %s' % e)
        return 1 if E else 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
