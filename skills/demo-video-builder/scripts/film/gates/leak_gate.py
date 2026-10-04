# -*- coding: utf-8 -*-
"""leak_gate.py — nothing private ships in the real footage (v5, leak-gate area). Loaded by qa_film.py via gates/*.py.

    leaks      every real-footage source the film draws from (broll/<clip>/ median stills, stitched pages and their
               chrome frames, typed-line stills, every Nth frame of a seq, rasters the scene loads, optional frames of
               the finished MP4) is scanned for identifiers. FAIL on any hit that is on screen and not neutralised by a
               declared mask; the hits are written to leaks.json for tools/mask_propose.py.
    leak ocr   which OCR backend ran and how fast. Never FAILs: with no backend it reads "WARN ocr backend unavailable"
               and the regex detectors are skipped while the avatar and denylist detectors still run.

WHY A PIXEL GATE. The `hygiene` gate in qa_film.py reads authored text (narration, scene, shots). A recording bakes
its leaks into pixels: the address bar (tenancy host, session id, an id_token), the account avatar, a user name in
the header, a tenancy OCID in a form, customer names in a table. The only honest check is to read the pixels that
will actually be shown, after extraction and masking, the same files footage.js loads.

METHOD, FROM FIRST PRINCIPLES
  1. Sources. clips.json names every clip; extract_clips.py writes broll/<clip>/ (still: f_001.jpg, seq: f_NNN.jpg,
     page: page.jpg + chrome_k.jpg). The media ledger (media.jsonl) may list broll/ folders no clip names any more
     and the scene may load local rasters (<img src>); both are scanned too. A seq is sampled every `seq_stride`
     frames (15 = 0.5 s at 30 fps, at most `seq_max_frames` per clip, first and last always); a sampled frame whose
     160x90 grey differs from the last OCR'd frame of the clip by < 1.0 levels on average reuses that frame's text
     (parked UI with a wandering pointer: one OCR pass instead of eight).
  2. OCR. A pluggable backend with recognize(PIL.Image) -> [{text, box:[x,y,w,h], conf, words?}]. Probe order:
     rapidocr_onnxruntime (PP-OCRv3 det+rec on onnxruntime, needs opencv-python-headless), then winocr (the Windows
     OS engine), else none. Measured on this machine (Python 3.14, Windows 11, shared CPU): rapidocr 1.2.3 reads a
     1920x1015 browser frame with 66 lines in 25-40 s (the recogniser dominates at ~0.4 s per line; a 1920x1080 frame
     with 5 lines takes 7.8 s); winocr reads the same frame in 0.27-0.45 s with more character confusions (l->1,
     missing dots) but every URL, e-mail and OCID still matches the tolerant patterns below. Import order matters:
     onnxruntime must load before winocr in the same process or its DLL fails to initialise, so `auto` probes
     rapidocr first. Because of the 100x gap, `auto` hands the remaining frames to winocr when the first rapidocr
     pass takes longer than `slow_ms` (10 000 ms) and winocr imports (the detail says so); set leak.backend to pin
     one engine. The selftests probe the fastest engine first to stay inside their 60 s budget (on this machine the
     1280x720 fixture frame with 20 lines takes 33 s on rapidocr and 0.4 s on winocr).
     Frames wider than `ocr_width` (1920) are downscaled for OCR and the boxes scaled back; pages
     taller than 2000 px are read in 1080 px strips with a 48 px overlap (duplicates removed by box overlap).
     OCR results are cached in out/leak_ocr_cache.json keyed by file sha1 + backend, so a re-run costs nothing and the
     output is identical with or without the cache.
  3. Regex detectors on each OCR line (raw text and the text with spaces removed, because both engines split or
     merge words): e-mail, OCID (ocid1.<type>.oc1..<chars>, tolerant of l/1/i confusions), IPv4, any scheme URL,
     bare internal host names (.internal .corp .local .lan .test .dev., -dev., staging, localhost, :port), JWT
     (eyJ… two or three base64url segments) and any three long base64 segments, 32+ hex runs, UUIDs, phone numbers
     (3-3-4 with separators or +cc …), "Bearer <token>", key shapes (AKIA…, sk-…, key=/token=/password=, OCI
     fingerprints aa:bb:…, PEM headers). `allow_patterns` (qa.json leak.allow_patterns) whitelist texts such as your
     own public docs domain.
  4. Denylist: BRIEF.md "## Never on screen" (one term per line, with or without a leading "- ") plus a --deny file
     and qa.json leak.deny_terms. Matching is fuzzy: at most one edit per 8 characters, rounded up (a 6-letter name
     tolerates one OCR confusion, a 17-letter one three), as an approximate substring of the alphanumeric-only
     lower-cased line, so "G1obex Industries" still hits "Globex". The same terms are matched (word-exact, then
     fuzzy) in the authored text that names footage — clips.json, broll/*/meta.json, shots.js, the scene, the
     ledger — which is the denylist path that needs no OCR.
  5. Avatar detector, no OCR: an account badge is a compact disc OR rounded square (zoomed in, both real product
     badges measured here are rounded squares with initials over a patterned fill — the "near-circular" assumption
     does not hold) that contrasts with its header bar, 16-72 px wide at 1920-px-normalised scale (measured: 27 px
     at 2426 wide = 21 px normalised, 42 px at 3160 wide = 26 px normalised), in the top `avatar_band` of the SOURCE
     frame (20 %: a macOS Chrome window with tabs + address bar + bookmarks puts the product header's badge at 17.4 %
     of the frame height, a Windows capture at 8 %) and in the right 30 % of the frame (`right_of` 0.70: both real
     badges sit at 96-98 % of the width; a red rounded-square bookmark icon at 24 % is what the prior rejects).
     Background is LOCAL: the median colour of a tile eight diameters wide around each column, per row (a whole-row
     median failed on a real frame where a modal dialog was wider than the header bar: the bar became "foreground"
     and swallowed the badge). Pixels farther than `contrast` (24 levels in any channel; the two real badges sit 53
     and 90 levels from their bars, a hover container 19) are foreground; holes are filled so initials merge into the
     badge; components are kept when width and height are within range, aspect in 0.8-1.25, fill ratio (area / bbox)
     in 0.60-1.0 (disc 0.785, rounded square 0.95-0.97), 4*pi*area/perimeter^2 >= 0.5 (on the 8-connected boundary a
     31 px disc measures 0.65) and boundary-radius spread (std / mean distance from the centroid) <= 0.2 (disc 0.03,
     square 0.11, glyph 0.4+). Then the colour test: the median colour of the inner 30 % radius must differ from the
     median colour of the 3x3 patches in the bounding box's own four inside corners by more than `contrast` — a disc
     or rounded square leaves bar colour in those corners, a sharp filled square icon does not, and a ring icon, a
     hollow "G" favicon or a browser profile ring has centre = corners = background. Decorative circles lower on the
     page never enter the band. When OCR runs, a second seed catches low-contrast badges: a line that is just 1-3
     capitals inside the band and right of `right_of` becomes an avatar hit boxed at 2.4 x the text height. A round
     or rounded-square logo at the right end of a header will be flagged too — list it under qa.json leak.ignore.
  6. Cross-checks. Declared masks are clips.json `fix:[{"blur":[x,y,w,h,r]}]` (clip px on stills/seqs, doc px on
     pages) and `chrome.fix` (frame px on chrome_k.jpg). A hit is `masked` when >= 80 % of its box lies inside a
     declared blur. An avatar inside a declared mask passes (a blurred disc is still a disc, the identity is gone).
     TEXT inside a declared mask that OCR can still read FAILS with "declared mask not applied or too weak": either
     extract_clips.py was not re-run or the radius is too small (rule of thumb from the selftest: Pillow
     GaussianBlur radius >= 0.45 x text height, never below 6, makes a line unreadable to both engines). The
     timeline (out/timeline.json shots) gives each clip the windows it is on screen; a hit in a clip no shot uses is
     listed with on_screen:false and does not fail.

OUTPUT leaks.json {version, backend, frames, hits:[{src, clip, kind, text, box:[x,y,w,h], conf, t0, t1, masked,
legible, on_screen, fails}], summary}. `text` is redacted to its first 3 and last 2 characters unless qa.json
leak.full_text is true, so the artefact itself never becomes the leak. No timings or dates are written (the file
is byte-identical across runs); timings are printed and shown in the gate detail.

    python gates/leak_gate.py --project DIR [--out leaks.json] [--deny FILE] [--backend auto|rapidocr|winocr|none]
                              [--no-ocr] [--seq-stride N] [--max-frames N] [--full-text] [--json]
    python gates/leak_gate.py --scan IMG [IMG ...] [--deny FILE]          ad-hoc frames (exit 1 on any hit)
    python gates/leak_gate.py --selftest [--no-ocr]                       synthetic Acme fixture, < 60 s
    exit 0 clean · 1 findings · 2 usage / error

qa.json knobs (all optional, under "leak"): backend, seq_stride (15), seq_max_frames (8), max_ocr_frames (60),
ocr_width (1920), src_size ([1920,1080]), avatar {band 0.20, dmin 16, dmax 72, contrast 40}, deny (file),
deny_terms [], allow_patterns [], ignore [{clip|src, box:[x,y,w,h]}], film_frames (0), full_text (false),
cache ("out/leak_ocr_cache.json"), out ("leaks.json").
"""
import glob, hashlib, io, json, math, os, re, subprocess, sys, time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

GATE_NAMES = ['leaks', 'leak ocr']
HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = 1

DEFAULTS = {
    'backend': 'auto', 'seq_stride': 15, 'seq_max_frames': 8, 'max_ocr_frames': 60, 'ocr_width': 1920,
    'src_size': [1920, 1080], 'dedupe_levels': 1.0, 'text_score': 0.5, 'film_frames': 0, 'full_text': False, 'slow_ms': 10000,
    'cache': 'out/leak_ocr_cache.json', 'out': 'leaks.json', 'deny': None, 'deny_terms': [], 'allow_patterns': [],
    'ignore': [], 'mask_cover': 0.8,
    'avatar': {'band': 0.20, 'right_of': 0.70, 'dmin': 16, 'dmax': 72, 'contrast': 24, 'fill': [0.60, 1.0], 'roundness': 0.50, 'radius_cv': 0.20},
}
TEXT_KINDS = ('email', 'ocid', 'ipv4', 'url', 'host', 'jwt', 'hex', 'uuid', 'phone', 'bearer', 'key', 'deny')

# ----------------------------------------------------------------------------------------------- detectors
HOST_TLDS = r'(?:internal|corp|local|lan|intranet|test|dev|localdomain)'
DETECTORS = [
    ('email', re.compile(r"[A-Za-z0-9][\w.+-]{0,63}[@\u00a9][A-Za-z0-9-]+(?:[._][A-Za-z0-9-]+)+", re.I)),
    ('ocid',  re.compile(r"oc[il1]d[l1i][._-][a-z0-9]{2,}[._-]oc[\dlI][\w.-]*", re.I)),     # OCR turns the dots into _ or - on small JPEG text
    ('ipv4',  re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")),
    ('url',   re.compile(r"\bhttps?:/{1,2}[^\s\"'<>]{4,}", re.I)),
    ('host',  re.compile(r"\b(?:[a-z0-9-]+\.)+" + HOST_TLDS + r"\b(?::\d{2,5})?|\b[a-z0-9.-]*(?:-dev\.|\.dev\.|staging\.|-stg\.|-test\.|\.test\.)[a-z0-9.-]+|\blocalhost(?::\d{2,5})?\b|\b(?:[a-z0-9-]+\.)+[a-z]{2,}:\d{2,5}\b", re.I)),
    ('jwt',   re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]{4,})?|[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")),
    ('hex',   re.compile(r"\b[0-9a-f]{32,}\b", re.I)),
    ('uuid',  re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)),
    ('phone', re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{3}\)[\s.-]?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w.])|(?<![\w.])\+\d{2,3}(?:[\s.-]?\d{2,4}){3,4}(?![\w.])")),
    ('bearer', re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ('key',   re.compile(r"\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{20,}|\b(?:api[_-]?key|access[_-]?key|secret|token|passw(?:or)?d|pwd)\s*[:=]\s*[^\s'\"]{6,}|(?:[0-9a-f]{2}:){15}[0-9a-f]{2}|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)),
]


def _cfg(qa):
    """DEFAULTS overlaid with qa.json "leak" (nested avatar dict merged)."""
    c = json.loads(json.dumps(DEFAULTS))
    for k, v in ((qa or {}).get('leak') or {}).items():
        if k == 'avatar' and isinstance(v, dict):
            c['avatar'].update(v)
        else:
            c[k] = v
    return c


def redact(s, full=False):
    s = ' '.join(str(s).split())
    if full or len(s) <= 5:
        return s
    return s[:3] + '\u2026' + s[-2:]


# ----------------------------------------------------------------------------------------------- OCR backends
class OcrBackend(object):
    """recognize(PIL.Image RGB) -> [{'text': str, 'box': [x, y, w, h], 'conf': float, 'words': [{'text','box'}]|None}]
    `upscale` is the factor ocr_image() enlarges a frame by before recognition (boxes come back in frame px)."""
    name = 'none'
    version = ''
    upscale = 1

    def recognize(self, im):
        raise NotImplementedError


class RapidOcrBackend(OcrBackend):
    name = 'rapidocr'

    def __init__(self, text_score=0.5):
        import importlib.metadata as md
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR(text_score=text_score)
        try:
            self.version = md.version('rapidocr-onnxruntime')
        except Exception:
            self.version = '?'

    def recognize(self, im):
        arr = np.asarray(im.convert('RGB'))[:, :, ::-1].copy()          # the engine expects BGR
        res, _ = self.engine(arr)
        out = []
        for box, text, conf in (res or []):
            xs = [float(p[0]) for p in box]; ys = [float(p[1]) for p in box]
            out.append({'text': str(text), 'box': [int(min(xs)), int(min(ys)), int(math.ceil(max(xs) - min(xs))), int(math.ceil(max(ys) - min(ys)))],
                        'conf': round(float(conf), 3), 'words': None})
        return out


class WinOcrBackend(OcrBackend):
    name = 'winocr'
    upscale = 2          # measured: at 1x the OS engine turns the dots of 14-16 px UI text into '_' and skips a short IP line;
                         # at 2x it reads them cleanly (296 ms vs 168 ms on a 1280x720 frame with 25 lines)

    def __init__(self, lang='en'):
        import importlib.metadata as md
        import winocr
        self.w, self.lang = winocr, lang
        try:
            self.version = md.version('winocr')
        except Exception:
            self.version = '?'

    def recognize(self, im):
        r = self.w.recognize_pil_sync(im.convert('RGB'), self.lang)
        lines = r['lines'] if isinstance(r, dict) else getattr(r, 'lines', [])
        out = []
        for ln in lines:
            words = ln['words'] if isinstance(ln, dict) else getattr(ln, 'words', [])
            ws = []
            for w in words:
                br = w['bounding_rect'] if isinstance(w, dict) else getattr(w, 'bounding_rect', None)
                txt = w['text'] if isinstance(w, dict) else getattr(w, 'text', '')
                if br is None:
                    continue
                g = (lambda k: br[k]) if isinstance(br, dict) else (lambda k: getattr(br, k))
                ws.append({'text': str(txt), 'box': [int(g('x')), int(g('y')), int(math.ceil(g('width'))), int(math.ceil(g('height')))]})
            if not ws:
                continue
            x0 = min(w['box'][0] for w in ws); y0 = min(w['box'][1] for w in ws)
            x1 = max(w['box'][0] + w['box'][2] for w in ws); y1 = max(w['box'][1] + w['box'][3] for w in ws)
            out.append({'text': ' '.join(w['text'] for w in ws), 'box': [x0, y0, x1 - x0, y1 - y0], 'conf': 1.0, 'words': ws})
        return out


def pick_backend(prefer='auto', text_score=0.5, fastest=False):
    """First backend that imports, in the documented order (rapidocr, winocr); `fastest` flips it (selftests, and
    the slow-frame switch in scan_sources). Returns (backend|None, note)."""
    order = (['winocr', 'rapidocr'] if fastest else ['rapidocr', 'winocr']) if prefer in (None, 'auto') else [prefer]
    notes = []
    for name in order:
        if name == 'none':
            return None, 'ocr disabled'
        try:
            if name == 'rapidocr':
                return RapidOcrBackend(text_score), ''
            if name == 'winocr':
                return WinOcrBackend(), ''
            notes.append('unknown backend %r' % name)
        except Exception as e:                                        # ImportError, DLL failures, missing OS language pack
            notes.append('%s: %s' % (name, type(e).__name__))
    return None, 'ocr backend unavailable (%s) \u2014 pip install rapidocr-onnxruntime opencv-python-headless, or winocr on Windows' % '; '.join(notes)


# ----------------------------------------------------------------------------------------------- text analysis
def _norm_map(s):
    """lower-case alphanumeric-only copy of s plus the index of each kept char in s."""
    out, idx = [], []
    for i, ch in enumerate(s.lower()):
        if ch.isalnum():
            out.append(ch); idx.append(i)
    return ''.join(out), idx


def fuzzy_find(term, text, max_edits):
    """Approximate substring search: smallest edit distance of `term` against any substring of `text` (Sellers'
    DP, free start and end). Returns (distance, end_index) or (None, None) when distance > max_edits."""
    m, n = len(term), len(text)
    if m == 0 or n == 0:
        return None, None
    prev = list(range(m + 1))                      # prev[i] = cost of matching term[:i] ending at current column
    best, best_j = None, None
    cur = [0] * (m + 1)
    for j in range(1, n + 1):
        cur[0] = 0
        tj = text[j - 1]
        for i in range(1, m + 1):
            cost = 0 if term[i - 1] == tj else 1
            cur[i] = min(prev[i - 1] + cost, prev[i] + 1, cur[i - 1] + 1)
        if cur[m] <= max_edits and (best is None or cur[m] < best):
            best, best_j = cur[m], j
        prev, cur = cur, prev
    if best is None:
        return None, None
    return best, best_j


def deny_allowance(term):
    """at most one edit per 8 characters, rounded up; terms under 4 characters must match exactly."""
    n = len(term)
    return 0 if n < 4 else int(math.ceil(n / 8.0))


def load_denylist(project, qa_cfg, extra_file=None):
    """BRIEF.md '## Never on screen' + qa leak.deny file + --deny file + leak.deny_terms. Sorted, unique, >= 2 chars."""
    terms = []
    brief = os.path.join(project, ((qa_cfg or {}).get('brief') if isinstance(qa_cfg, dict) else None) or 'BRIEF.md') if project else None
    if brief and os.path.exists(brief):
        cur = None
        for raw in open(brief, encoding='utf-8', errors='replace').read().splitlines():
            m = re.match(r'^#{2,3}\s+(.+?)\s*$', raw)
            if m:
                cur = m.group(1).strip().lower(); continue
            if cur and cur.startswith('never on screen'):
                s = re.sub(r'<!--.*?-->', '', raw).strip()
                if s.startswith(('- ', '* ')):
                    s = s[2:].strip()
                if s and not s.startswith('#'):
                    terms.append(s)
    L = _cfg(qa_cfg)
    for f in [L.get('deny'), extra_file]:
        if f:
            p = f if os.path.isabs(f) or not project else os.path.join(project, f)
            if os.path.exists(p):
                terms += [t.strip() for t in open(p, encoding='utf-8', errors='replace').read().splitlines()
                          if t.strip() and not t.strip().startswith('#')]
    terms += [str(t) for t in L.get('deny_terms') or []]
    return sorted(set(t for t in terms if len(t.strip()) >= 2))


def scan_text(text, denylist, allow=None):
    """[(kind, start, end, matched_text)] on one OCR line: regex detectors on the raw text and on the text with
    whitespace removed (mapped back), then the fuzzy denylist on the alphanumeric-only text."""
    hits = []
    variants = [(text, list(range(len(text))))]
    nospace, idx = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            nospace.append(ch); idx.append(i)
    if len(nospace) != len(text):
        variants.append((''.join(nospace), idx))
    for s, mp in variants:
        for kind, rx in DETECTORS:
            for m in rx.finditer(s):
                a, b = mp[m.start()], mp[m.end() - 1] + 1
                hits.append((kind, a, b, m.group(0)))
    norm, nidx = _norm_map(text)
    for term in denylist:
        tn, _ = _norm_map(term)
        if not tn:
            continue
        d, j = fuzzy_find(tn, norm, deny_allowance(tn))
        if d is None:
            continue
        a = nidx[max(0, j - len(tn))]; b = nidx[j - 1] + 1
        hits.append(('deny', a, b, text[a:b]))
    if allow:
        hits = [h for h in hits if not any(rx.search(h[3]) for rx in allow)]
    # keep the longest hit per overlapping span of the same kind
    hits.sort(key=lambda h: (h[0], h[1], -(h[2] - h[1])))
    out = []
    for h in hits:
        if out and out[-1][0] == h[0] and h[1] < out[-1][2]:
            continue
        out.append(h)
    return out


def span_box(line, a, b):
    """Box of chars [a, b) of an OCR line: the union of the words it touches (winocr) or the line box."""
    words = line.get('words')
    if not words:
        return list(line['box'])
    pos, picked = 0, []
    for w in words:
        s, e = pos, pos + len(w['text'])
        if e > a and s < b:
            picked.append(w['box'])
        pos = e + 1
    if not picked:
        return list(line['box'])
    x0 = min(w[0] for w in picked); y0 = min(w[1] for w in picked)
    x1 = max(w[0] + w[2] for w in picked); y1 = max(w[1] + w[3] for w in picked)
    return [x0, y0, x1 - x0, y1 - y0]


# ----------------------------------------------------------------------------------------------- avatar detector
def avatar_blobs(im, band_rows, scale=1.0, A=None):
    """Near-circular contrasting discs inside image rows [y0, y1). `scale` = image px per 1920-normalised px.
    Returns [{'box': [x, y, w, h], 'fill': f, 'roundness': r, 'conf': c}] sorted by x."""
    A = A or DEFAULTS['avatar']
    try:
        from scipy import ndimage
    except ImportError:                       # scipy missing: the detector is skipped, the gate reports it
        return None
    y0, y1 = int(max(0, band_rows[0])), int(min(im.height, band_rows[1]))
    if y1 - y0 < 8:
        return []
    band = np.asarray(im.convert('RGB'))[y0:y1].astype(np.int16)
    H, W = band.shape[:2]
    dmin, dmax = A['dmin'] * scale, A['dmax'] * scale
    # local background: the median colour of a tile 8 avatar-diameters wide around each column, per row. A whole-row
    # median fails the moment a dialog or a page body is wider than the header bar in that row (measured: a modal
    # made the bar itself "foreground" and swallowed the avatar); a tile a few hundred px wide is always mostly bar.
    tw = max(64, int(round(8 * dmax)))
    bg = np.empty_like(band)
    x = 0
    while x < W:
        lo, hi = max(0, x - tw // 2), min(W, x + tw // 2)
        bg[:, x:min(W, x + tw // 4)] = np.median(band[:, lo:hi], axis=1, keepdims=True)
        x += tw // 4
    dist = np.abs(band - bg).max(axis=2)
    fg = ndimage.binary_fill_holes(dist > int(A['contrast']))
    lab, n = ndimage.label(fg, structure=np.ones((3, 3), bool))
    if n == 0:
        return []
    out = []
    for k, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None:
            continue
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (dmin <= w <= dmax and dmin <= h <= dmax):
            continue
        if not (0.8 <= w / float(h) <= 1.25):
            continue
        if sl[0].start == 0 or sl[0].stop == H:                     # cut by the band edge: not a whole disc
            continue
        comp = (lab[sl] == k)
        area = int(comp.sum())
        fill = area / float(w * h)
        if not (A['fill'][0] <= fill <= A['fill'][1]):
            continue
        edge = comp & ~ndimage.binary_erosion(comp, structure=np.ones((3, 3), bool), border_value=0)
        per = int(edge.sum())
        roundness = 4 * math.pi * area / float(per * per) if per else 0.0
        if roundness < A['roundness']:
            continue
        ys, xs = np.nonzero(edge)
        cy, cx = ys.mean(), xs.mean()
        r = np.hypot(ys - cy, xs - cx)
        cv = float(r.std() / max(1e-6, r.mean()))
        if cv > A['radius_cv']:
            continue
        ry0, rx0 = sl[0].start, sl[1].start
        if (rx0 + w / 2.0) < float(A.get('right_of', 0.70)) * W:     # account badges live at the right end of the bar
            continue
        # badge test in colour: a disc or a rounded square leaves background in the INSIDE corners of its own
        # bounding box, so the centre colour differs from the corner colour; a sharp filled square does not, and a
        # ring icon or hollow glyph has centre = corners = background.
        rad = 0.3 * min(w, h)
        yy, xx = np.mgrid[0:h, 0:w]
        inner = (np.hypot(yy - (h - 1) / 2.0, xx - (w - 1) / 2.0) <= rad)
        patch = band[ry0:ry0 + h, rx0:rx0 + w]
        centre = np.median(patch[inner], axis=0)
        corners = np.concatenate([patch[0:3, 0:3].reshape(-1, 3), patch[0:3, w - 3:w].reshape(-1, 3),
                                  patch[h - 3:h, 0:3].reshape(-1, 3), patch[h - 3:h, w - 3:w].reshape(-1, 3)])
        corner = np.median(corners, axis=0)
        cdiff = float(np.abs(centre - corner).max())
        if cdiff <= int(A['contrast']):
            continue
        conf = round(min(1.0, 0.4 * (1 - min(1.0, abs(fill - 0.785) / 0.25)) + 0.3 * (1 - cv / A['radius_cv']) + 0.3 * min(1.0, cdiff / 120.0)), 3)
        out.append({'box': [int(rx0), int(y0 + ry0), int(w), int(h)], 'fill': round(fill, 3), 'roundness': round(roundness, 3),
                    'contrast': int(cdiff), 'conf': max(0.0, conf)})
    return sorted(out, key=lambda b: (b['box'][0], b['box'][1]))


INITIALS_RE = re.compile(r'^[A-Z]{1,3}$')


def initials_seed(lines, im_w, band_rows, blobs, right_of=0.70):
    """OCR-side avatar seed: a line that is just 1-3 capitals, inside the avatar band and in the right 30 % of the
    frame, is an initials badge (measured on two real headers: "AD" at x = 98 % and 96 % of the width). The box is a
    square of 2.4 x the text height centred on the text. Seeds already covered by a pixel blob are dropped."""
    out = []
    for ln in lines:
        t = ''.join(ln['text'].split())
        x, y, w, h = ln['box']
        if not INITIALS_RE.match(t) or h < 6:
            continue
        if not (band_rows[0] <= y + h / 2.0 < band_rows[1]) or (x + w / 2.0) < float(right_of) * im_w:
            continue
        side = int(round(2.4 * h))
        box = [int(round(x + w / 2.0 - side / 2.0)), int(round(y + h / 2.0 - side / 2.0)), side, side]
        if any(_cover(b['box'], box) > 0.5 or _cover(box, b['box']) > 0.5 for b in blobs):
            continue
        out.append({'box': box, 'conf': 0.6, 'seed': 'initials'})
    return out


# ----------------------------------------------------------------------------------------------- sources
def _rel(p, project):
    return os.path.relpath(p, project).replace('\\', '/') if project else p.replace('\\', '/')


def _windows_for(clip, timeline):
    shots = (timeline or {}).get('shots') or []
    total = float((timeline or {}).get('total') or 0) or None
    w = []
    for s in shots:
        if s.get('clip') == clip and isinstance(s.get('t0'), (int, float)):
            t1 = s.get('t1') if isinstance(s.get('t1'), (int, float)) else total
            w.append([round(float(s['t0']), 3), round(float(t1), 3) if t1 is not None else None])
    return sorted(w, key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))


def _seq_indices(n, stride, cap):
    if n <= 0:
        return []
    idx = sorted(set([1] + list(range(1, n + 1, max(1, stride))) + [n]))
    if len(idx) > cap:                                   # evenly thin to the cap, keeping first and last
        idx = sorted(set(int(round(1 + (n - 1) * k / float(cap - 1))) for k in range(cap)))
    return idx


def collect_sources(ctx, L):
    """[{src, path, clip, kind, coord, frame, scale, src_rect, masks, windows, on_screen}] sorted by src.
    coord: 'clip' (still/seq px, origin = crop), 'doc' (page px, origin = band), 'frame' (chrome / asset / film)."""
    project = ctx['project']
    cfg = ctx.get('cfg') or {}
    broll = os.path.join(project, cfg.get('broll', 'broll'))
    timeline = ctx.get('timeline')
    have_tl = bool((timeline or {}).get('shots'))
    out, seen = [], set()

    def add(path, clip, kind, coord, frame, scale, src_rect, masks, windows):
        rel = _rel(path, project)
        if rel in seen or not os.path.exists(path):
            return
        seen.add(rel)
        out.append({'src': rel, 'path': path, 'clip': clip, 'kind': kind, 'coord': coord, 'frame': frame, 'scale': scale,
                    'src_rect': src_rect, 'masks': masks, 'windows': windows,
                    'on_screen': (bool(windows) if have_tl and clip else None)})

    clips = []
    cj = os.path.join(project, cfg.get('clips', 'clips.json'))
    if os.path.exists(cj):
        try:
            clips = [c for c in json.load(open(cj, encoding='utf-8')) if isinstance(c, dict) and c.get('name')]
        except ValueError:
            clips = []
    for c in sorted(clips, key=lambda c: c['name']):
        name, d = c['name'], os.path.join(broll, c['name'])
        meta = {}
        if os.path.exists(os.path.join(d, 'meta.json')):
            try:
                meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
            except ValueError:
                meta = {}
        windows = _windows_for(name, timeline)
        masks = [[int(v) for v in f['blur'][:4]] for f in c.get('fix', []) if isinstance(f, dict) and 'blur' in f]
        cmasks = [[int(v) for v in f['blur'][:4]] for f in ((c.get('chrome') or {}).get('fix') or []) if isinstance(f, dict) and 'blur' in f]
        kind = c.get('kind', meta.get('kind', 'still'))
        if kind == 'page':
            band = c.get('band') or meta.get('band') or [0, 0, L['src_size'][0], L['src_size'][1]]
            add(os.path.join(d, 'page.jpg'), name, 'page', 'doc', 1, 1.0, band, masks, windows)
            for k, p in enumerate(sorted(glob.glob(os.path.join(d, 'chrome_*.jpg')))):
                add(p, name, 'chrome', 'frame', k, 1.0, [0, 0, L['src_size'][0], L['src_size'][1]], cmasks, windows)
        else:
            crop = c.get('crop') or meta.get('crop') or [0, 0, L['src_size'][0], L['src_size'][1]]
            scale = (float(c['width']) / crop[2]) if c.get('width') and crop[2] else 1.0
            files = sorted(glob.glob(os.path.join(d, 'f_*.jpg')))
            if kind == 'seq':
                for i in _seq_indices(len(files), int(L['seq_stride']), int(L['seq_max_frames'])):
                    add(files[i - 1], name, 'seq', 'clip', i, scale, crop, masks, windows)
            elif files:
                add(files[0], name, 'still', 'clip', 1, scale, crop, masks, windows)
    # ledger footage folders no clip names any more
    lp = os.path.join(project, cfg.get('ledger') or (ctx.get('qa') or {}).get('ledger') or 'media.jsonl')
    if os.path.exists(lp):
        for line in open(lp, encoding='utf-8', errors='replace'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('kind') == 'footage' and str(r.get('path', '')).startswith('broll/') and r['path'].endswith('/'):
                d = os.path.join(project, r['path'])
                nm = r['path'].rstrip('/').split('/')[-1]
                if os.path.isdir(d) and nm not in set(c['name'] for c in clips):
                    files = sorted(glob.glob(os.path.join(d, '*.jpg')))
                    for i in _seq_indices(len(files), int(L['seq_stride']), int(L['seq_max_frames'])):
                        add(files[i - 1], nm, 'ledger', 'frame', i, 1.0, [0, 0, L['src_size'][0], L['src_size'][1]], [], _windows_for(nm, timeline))
    # rasters the scene loads
    scene = ctx.get('scene_html')
    if scene and os.path.exists(scene):
        html = re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', open(scene, encoding='utf-8', errors='replace').read(), flags=re.S)
        for m in re.finditer(r"""<(?:img|video|source)\b[^>]*\bsrc\s*=\s*["']([^"'<>:]+?)["']""", html, re.I):
            rel = m.group(1)
            if os.path.splitext(rel)[1].lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                p = os.path.normpath(os.path.join(os.path.dirname(scene), rel))
                add(p, None, 'asset', 'frame', 1, 1.0, None, [], [])
    # ignore boxes behave like declared masks (author-reviewed false positives)
    for ig in L.get('ignore') or []:
        for s in out:
            if (ig.get('clip') and s['clip'] == ig['clip']) or (ig.get('src') and s['src'] == ig['src']):
                s['masks'] = s['masks'] + [list(map(int, ig['box']))]
    return sorted(out, key=lambda s: (s['src']))


# ----------------------------------------------------------------------------------------------- scanning
def _sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _small_grey(im):
    return np.asarray(im.convert('L').resize((160, 90), Image.BILINEAR), dtype=np.float32)


def ocr_image(backend, im, ocr_width):
    """OCR with the width cap and tall-image strips; boxes in the image's own px."""
    k = 1.0
    up = int(getattr(backend, 'upscale', 1) or 1)
    # an upscaling (fast) backend reads frames up to 4000 px wide at 2x their NATIVE size: measured on a 3160-wide
    # Retina capture, 1920x2 and native both missed the address bar line entirely, native x2 (6320 px) read it in
    # full — host, session id and tenancy OCID — in 2.2 s. Slow backends keep the ocr_width cap.
    cap = ocr_width if up == 1 else max(ocr_width, min(im.width, 4000))
    target = min(im.width, cap) * up
    if target != im.width:
        k = im.width / float(target)                                   # image px per OCR px (< 1 when upscaling)
        im = im.resize((target, int(round(im.height / k))), Image.LANCZOS if k > 1 else Image.BICUBIC)
    lines = []
    if im.height > 2400:
        step, ov, y = 1200, 64, 0
        while y < im.height:
            strip = im.crop((0, y, im.width, min(im.height, y + step)))
            for ln in backend.recognize(strip):
                ln['box'][1] += y
                if ln.get('words'):
                    for w in ln['words']:
                        w['box'][1] += y
                dup = any(_cover(ln['box'], o['box']) > 0.5 and _cover(o['box'], ln['box']) > 0.5 for o in lines)
                if not dup:
                    lines.append(ln)
            if y + step >= im.height:
                break
            y += step - ov
    else:
        lines = backend.recognize(im)
    if k != 1.0:
        for ln in lines:
            ln['box'] = [int(round(v * k)) for v in ln['box']]
            for w in (ln.get('words') or []):
                w['box'] = [int(round(v * k)) for v in w['box']]
    return lines


def _cover(box, by):
    """fraction of `box` area inside `by`."""
    ax0, ay0, aw, ah = box; bx0, by0, bw, bh = by
    ix = max(0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0)); iy = max(0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    return (ix * iy) / float(max(1, aw * ah))


def scan_sources(sources, L, backend, denylist, project=None, cache_path=None, allow=None):
    """Run every detector over the sources. Returns (hits, stats)."""
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path, encoding='utf-8'))
        except ValueError:
            cache = {}
    stats = {'frames': 0, 'ocr_frames': 0, 'ocr_ms': 0.0, 'reused': 0, 'cached': 0, 'skipped_budget': 0, 'avatar_skipped': False,
             'switched': None, 'backend': backend}
    hits, last = [], {}
    band_frac = float(L['avatar']['band'])
    src_w, src_h = L['src_size']
    for s in sources:
        try:
            im = Image.open(s['path']).convert('RGB')
        except Exception:
            continue
        stats['frames'] += 1
        # --- avatar band in this image's rows (top band_frac of the SOURCE frame mapped through the source rect)
        if s['src_rect'] is None:
            rows, scale = (0, int(round(im.height * band_frac))), im.width / 1920.0
        else:
            rx, ry, rw, rh = s['src_rect'][:4]
            top_src = band_frac * src_h
            scale = (im.width / float(rw)) if rw else 1.0
            rows = (0, int(round(max(0.0, top_src - ry) * scale))) if s['coord'] != 'frame' else (0, int(round(top_src * im.height / float(max(1, rh)))))
            scale = scale * (src_w / 1920.0) if s['coord'] != 'frame' else (im.width / 1920.0)
        blobs = avatar_blobs(im, rows, scale, L['avatar']) if rows[1] > rows[0] else []
        if blobs is None:
            stats['avatar_skipped'] = True; blobs = []
        for b in blobs:
            hits.append({'src': s['src'], 'clip': s['clip'], 'kind': 'avatar', 'text': None, 'box': b['box'], 'conf': b['conf'], '_s': s})
        # --- OCR + regex + fuzzy denylist
        if backend is None:
            continue
        lines, g = None, _small_grey(im)
        key = s['clip'] or s['src']
        if key in last and float(np.abs(last[key][0] - g).mean()) < float(L['dedupe_levels']):
            lines = last[key][1]; stats['reused'] += 1
        else:
            ck = '%s|%s|%s|%d' % (_sha1(s['path']), backend.name, backend.version, int(L['ocr_width']))
            if ck in cache:
                lines = cache[ck]; stats['cached'] += 1
            elif stats['ocr_frames'] >= int(L['max_ocr_frames']):
                stats['skipped_budget'] += 1; continue
            else:
                t = time.perf_counter()
                lines = ocr_image(backend, im, int(L['ocr_width']))
                ms = (time.perf_counter() - t) * 1000
                stats['ocr_ms'] += ms; stats['ocr_frames'] += 1
                cache[ck] = lines
                # a slow first pass on `auto` hands the remaining frames to the OS engine when it imports
                if stats['ocr_frames'] == 1 and L.get('backend') in (None, 'auto') and backend.name == 'rapidocr' and ms > float(L['slow_ms']):
                    try:
                        alt = WinOcrBackend()
                        stats['switched'] = '%s %.0f ms/frame on the first frame -> %s' % (backend.name, ms, alt.name)
                        backend = alt
                    except Exception:
                        pass
            last[key] = (g, lines)
        for seed in (initials_seed(lines, im.width, rows, blobs, L['avatar'].get('right_of', 0.70)) if rows[1] > rows[0] else []):
            hits.append({'src': s['src'], 'clip': s['clip'], 'kind': 'avatar', 'text': 'initials', 'box': seed['box'], 'conf': seed['conf'], '_s': s})
        for ln in lines:
            if float(ln.get('conf', 1.0)) < float(L['text_score']):
                continue
            for kind, a, b, txt in scan_text(ln['text'], denylist, allow):
                hits.append({'src': s['src'], 'clip': s['clip'], 'kind': kind, 'text': txt, 'box': span_box(ln, a, b),
                             'conf': round(float(ln.get('conf', 1.0)), 3), '_s': s})
    stats['backend'] = backend
    if cache_path and backend is not None:
        try:
            os.makedirs(os.path.dirname(cache_path) or '.', exist_ok=True)
            json.dump(cache, open(cache_path, 'w', encoding='utf-8'), sort_keys=True)
        except OSError:
            pass
    return hits, stats


def authored_deny_hits(ctx, denylist, allow=None):
    """The denylist against the text that names footage (no OCR): clips.json, broll/*/meta.json, shots.js, scene,
    ledger. Word-exact first, then fuzzy per line. BRIEF.md and deny files are excluded (they define the terms)."""
    if not denylist:
        return []
    project = ctx['project']
    files = [os.path.join(project, (ctx.get('cfg') or {}).get('clips', 'clips.json')), ctx.get('shots_js'), ctx.get('scene_html'),
             os.path.join(project, (ctx.get('cfg') or {}).get('ledger') or 'media.jsonl')]
    files += sorted(glob.glob(os.path.join(project, (ctx.get('cfg') or {}).get('broll', 'broll'), '*', 'meta.json')))
    files += [os.path.join(project, a) for a in (ctx.get('qa') or {}).get('authored', [])]
    hits, seen = [], set()
    for f in files:
        if not f or not os.path.exists(f) or f in seen:
            continue
        seen.add(f)
        rel = _rel(f, project)
        for i, line in enumerate(open(f, encoding='utf-8', errors='replace').read().splitlines(), 1):
            for kind, a, b, txt in scan_text(line, denylist, allow):
                if kind != 'deny':
                    continue
                hits.append({'src': rel, 'clip': None, 'kind': 'deny', 'text': txt, 'box': None, 'conf': 1.0, 'line': i,
                             'masked': False, 'legible': True, 'on_screen': True, 't0': None, 't1': None, 'fails': True,
                             'why': 'denylisted term in authored text'})
    return hits


def judge(hits, L):
    """Fill masked / legible / on_screen / fails / why on every pixel hit and drop the private source record."""
    out = []
    for h in hits:
        s = h.pop('_s')
        covered = max([_cover(h['box'], m) for m in s['masks']] or [0.0]) >= float(L['mask_cover'])
        on = s['on_screen'] if s['on_screen'] is not None else True
        w = s['windows']
        h.update({'frame': s['frame'], 'coord': s['coord'], 'masked': bool(covered),
                  'legible': h['kind'] != 'avatar', 'on_screen': bool(on),
                  't0': w[0][0] if w else None, 't1': w[-1][1] if w else None})
        if not on:
            h['fails'], h['why'] = False, 'clip not on screen (no shot uses it)'
        elif covered and h['kind'] == 'avatar':
            h['fails'], h['why'] = False, 'inside a declared mask'
        elif covered:
            h['fails'], h['why'] = True, 'declared mask not applied or too weak \u2014 re-run extract_clips.py or raise the blur radius'
        else:
            h['fails'], h['why'] = True, 'unmasked'
        out.append(h)
    return out


def finalize(hits, L):
    for h in hits:
        if h.get('text') is not None:
            h['text'] = redact(h['text'], bool(L.get('full_text')))
    key = lambda h: (h['src'], h['kind'], h.get('box') or [-1, h.get('line', 0), 0, 0], h.get('text') or '')
    uniq, seen = [], set()
    for h in sorted(hits, key=key):
        k = json.dumps(key(h))
        if k in seen:
            continue
        seen.add(k); uniq.append(h)
    return uniq


def run_scan(ctx, backend_pref=None, deny_file=None, out_path=None, no_cache=False, verbose=False):
    """Everything the gate does, returned as the leaks.json dict plus (backend_note, stats)."""
    project = ctx['project']
    L = _cfg(ctx.get('qa'))
    if backend_pref:
        L['backend'] = backend_pref
    denylist = load_denylist(project, ctx.get('qa'), deny_file)
    allow = [re.compile(p, re.I) for p in (L.get('allow_patterns') or [])]
    sources = collect_sources(ctx, L)
    if int(L.get('film_frames') or 0) > 0 and ctx.get('film') and os.path.exists(ctx['film']):
        sources += film_sources(ctx, L)
    backend, note = (None, 'ocr disabled') if L['backend'] == 'none' else pick_backend(L['backend'], float(L['text_score']))
    cache_path = None if no_cache else os.path.join(project, L['cache'])
    hits, stats = scan_sources(sources, L, backend, denylist, project, cache_path, allow)
    backend = stats.get('backend') or backend
    if stats.get('switched'):
        note = (note + '; ' if note else '') + 'switched: ' + stats['switched']
    hits = judge(hits, L) + authored_deny_hits(ctx, denylist, allow)
    hits = finalize(hits, L)
    failing = [h for h in hits if h['fails']]
    doc = {'version': VERSION, 'backend': {'name': backend.name if backend else None, 'version': backend.version if backend else None,
                                           'note': note or None},
           'denylist_terms': len(denylist), 'frames': stats['frames'], 'ocr_frames_total': stats['ocr_frames'] + stats['cached'] + stats['reused'],
           'sources': [{'src': s['src'], 'clip': s['clip'], 'kind': s['kind'], 'on_screen': s['on_screen']} for s in sources],
           'hits': hits,
           'summary': {'hits': len(hits), 'failing': len(failing), 'by_kind': {k: sum(1 for h in failing if h['kind'] == k) for k in sorted(set(h['kind'] for h in failing))},
                       'avatar_detector': 'skipped (scipy missing)' if stats['avatar_skipped'] else 'ran',
                       'ocr_budget_skipped': stats['skipped_budget']}}
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write('\n')
    return doc, note, stats


def film_sources(ctx, L):
    """`film_frames` evenly spaced frames of the finished MP4, written to out/leak_frames/ (frame px)."""
    n, film, project = int(L['film_frames']), ctx['film'], ctx['project']
    dur = float(ctx.get('dur') or 0)
    d = os.path.join(project, 'out', 'leak_frames')
    os.makedirs(d, exist_ok=True)
    out = []
    for k in range(n):
        t = (k + 0.5) * dur / n if dur else k
        p = os.path.join(d, 'film_%03d.png' % (k + 1))
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', '%.3f' % t, '-i', film, '-frames:v', '1', p], capture_output=True)
        if os.path.exists(p):
            out.append({'src': _rel(p, project), 'path': p, 'clip': None, 'kind': 'film', 'coord': 'frame', 'frame': k + 1, 'scale': 1.0,
                        'src_rect': None, 'masks': [], 'windows': [[round(t, 3), round(t, 3)]], 'on_screen': True})
    return out


def describe(doc, stats):
    b = doc['backend']
    if not b['name']:
        ocr = 'WARN %s \u2014 regex detectors skipped; avatar + denylist ran' % (b['note'] or 'ocr backend unavailable')
    else:
        per = stats['ocr_ms'] / stats['ocr_frames'] if stats['ocr_frames'] else 0.0
        ocr = '%s %s \u00b7 %d frames, %d OCR passes (%d cached, %d reused) \u00b7 %.0f ms/frame' % (
            b['name'], b['version'], doc['frames'], stats['ocr_frames'], stats['cached'], stats['reused'], per)
        if stats.get('switched'):
            ocr += ' \u00b7 ' + stats['switched']
        if stats['skipped_budget']:
            ocr += ' \u00b7 WARN budget: %d frames not read (raise leak.max_ocr_frames)' % stats['skipped_budget']
    fails = [h for h in doc['hits'] if h['fails']]
    if fails:
        ex = '; '.join('%s %s%s %s' % (h['kind'], h['src'], ('@%s' % h['box']) if h.get('box') else (':%d' % h.get('line', 0)), h.get('text') or '') for h in fails[:3])
        leaks = '%d unmasked hit%s (%s) \u2014 %s%s \u2192 python tools/mask_propose.py leaks.json' % (
            len(fails), '' if len(fails) == 1 else 's', ', '.join('%s %d' % kv for kv in sorted(doc['summary']['by_kind'].items())), ex,
            ' (+%d)' % (len(fails) - 3) if len(fails) > 3 else '')
    else:
        soft = len(doc['hits'])
        leaks = '%d sources clean%s' % (doc['frames'], (' (%d hits masked / off screen)' % soft) if soft else '')
        if not doc['frames']:
            leaks = 'no footage sources found (clips.json / broll/) \u2014 nothing to scan'
    return leaks, ocr


def run(ctx):
    L = _cfg(ctx.get('qa'))
    out_path = os.path.join(ctx['project'], L['out'])
    doc, note, stats = run_scan(ctx, out_path=out_path)
    leaks, ocr = describe(doc, stats)
    return [('leaks', not any(h['fails'] for h in doc['hits']), leaks), ('leak ocr', True, ocr)]


# ----------------------------------------------------------------------------------------------- synthetic fixture
_FONTS = {}


def _font(px):
    if px not in _FONTS:
        f = None
        for p in ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                  '/System/Library/Fonts/Supplemental/Arial.ttf'):
            if os.path.exists(p):
                f = ImageFont.truetype(p, px); break
        _FONTS[px] = f or ImageFont.load_default(size=px)
    return _FONTS[px]


FIX = {   # planted leaks of the fictional Acme fixture (1280x720 source frame)
    'url': 'https://console.acme-corp.test/app?wsid=0bbd4f87-7b79-478b-8078-a9b77a1b26a5&id_token=eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJqYW5lIn0.c2lnbmF0dXJl',
    'email': 'jane.doe@acme-corp.test',
    'ocid': 'ocid1.tenancy.oc1..aaaaaaaab3k7q2m9x4p1acmefakeidentifierz',
    'ipv4': '10.42.7.19',
    'phone': '+1 (555) 010-0199',
    'deny': 'Globex Industries',
    'avatar': [1236, 47, 30, 30],
}
FIX_ROWS = [('Owner', 'email'), ('Tenancy OCID', 'ocid'), ('Gateway', 'ipv4'), ('Support', 'phone'), ('Partner', 'deny')]


def draw_fixture_frame(pointer=(700, 500), blur=None):
    """A fake Acme Console screen, 1280x720: browser bar with a URL, navy header with an initials avatar, a table
    holding one of each identifier. `blur` = [x, y, w, h, r] applied the way extract_clips.py applies a fix."""
    W, H = 1280, 720
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 40), fill=(236, 238, 241))
    d.rounded_rectangle((60, 8, 1180, 32), 12, fill=(255, 255, 255), outline=(200, 204, 210))
    d.text((72, 12), FIX['url'], font=_font(14), fill=(40, 44, 52))
    d.rectangle((0, 40, W, 84), fill=(8, 42, 52))
    d.text((18, 52), 'Acme Console', font=_font(18), fill=(233, 243, 249))
    d.rounded_rectangle((420, 50, 900, 76), 6, fill=(32, 74, 86))
    d.text((432, 55), 'Search', font=_font(14), fill=(180, 200, 206))
    ax, ay, aw, ah = FIX['avatar']
    d.ellipse((ax, ay, ax + aw, ay + ah), fill=(129, 169, 171))
    d.text((ax + 7, ay + 7), 'JD', font=_font(13), fill=(8, 42, 52))
    d.text((300, 110), 'Tenancy', font=_font(24), fill=(20, 24, 30))
    d.text((300, 146), 'Settings and contacts for this environment', font=_font(15), fill=(96, 104, 112))
    y = 200
    for label, key in FIX_ROWS:
        d.line((300, y - 10, 1180, y - 10), fill=(226, 230, 234))
        d.text((300, y), label, font=_font(16), fill=(96, 104, 112))
        d.text((520, y), FIX[key], font=_font(16), fill=(20, 24, 30))
        y += 44
    for label, val in (('Region', 'us-sample-1'), ('Status', 'Healthy'), ('Plan', 'Standard')):
        d.line((300, y - 10, 1180, y - 10), fill=(226, 230, 234))
        d.text((300, y), label, font=_font(16), fill=(96, 104, 112)); d.text((520, y), val, font=_font(16), fill=(20, 24, 30))
        y += 44
    d.rectangle((0, 84, 260, H), fill=(246, 247, 249))
    for i, item in enumerate(('Home', 'Catalog', 'Workspaces', 'Agents', 'Settings')):
        d.text((24, 110 + 36 * i), item, font=_font(15), fill=(40, 44, 52))
    if pointer:
        px, py = pointer
        d.polygon([(px, py), (px, py + 16), (px + 4, py + 12), (px + 11, py + 12)], fill=(0, 0, 0))
    if blur:
        x, y0, w, h, r = blur
        im.paste(im.crop((x, y0, x + w, y0 + h)).filter(ImageFilter.GaussianBlur(r)), (x, y0))
    return im


def fixture_row_box(key):
    """[x, y, w, h] of a planted table value in the 1280x720 frame (measured from the drawing code)."""
    i = [k for _, k in FIX_ROWS].index(key)
    f = _font(16); bb = f.getbbox(FIX[key])
    return [520 + bb[0] - 2, 200 + 44 * i + bb[1] - 2, bb[2] - bb[0] + 4, bb[3] - bb[1] + 4]


def build_fixture(root):
    """A tiny project: clips.json (still q, page nb with chrome, seq send with one applied blur over the IP, unused
    still spare), broll files, BRIEF.md with '## Never on screen', out/timeline.json, scenes/."""
    for d in ('broll/q', 'broll/nb', 'broll/send', 'broll/spare', 'out', 'scenes'):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    frame = draw_fixture_frame()
    frame.save(os.path.join(root, 'broll', 'q', 'f_001.jpg'), quality=94)
    json.dump({'kind': 'still', 'frames': 1, 'fps': 30, 'w': 1280, 'h': 720, 'crop': [0, 0, 1280, 720]}, open(os.path.join(root, 'broll', 'q', 'meta.json'), 'w'))
    # page: band of the body stitched twice (doc px), chrome frames = the full screen
    band = [280, 90, 920, 600]
    page = Image.new('RGB', (band[2], band[3] + 400), (255, 255, 255))
    body = frame.crop((band[0], band[1], band[0] + band[2], band[1] + band[3]))
    page.paste(body, (0, 0)); page.paste(body.crop((0, 30, band[2], band[3])), (0, 430))
    page.save(os.path.join(root, 'broll', 'nb', 'page.jpg'), quality=94)
    frame.save(os.path.join(root, 'broll', 'nb', 'chrome_0.jpg'), quality=94)
    draw_fixture_frame(pointer=(900, 300)).save(os.path.join(root, 'broll', 'nb', 'chrome_1.jpg'), quality=94)
    json.dump({'kind': 'page', 'frames': 1, 'fps': 30, 'w': band[2], 'h': band[3] + 400, 'band': band, 'offsets': [0, 400]}, open(os.path.join(root, 'broll', 'nb', 'meta.json'), 'w'))
    # seq: 30 frames, pointer drifting, IP blurred for real with r=8 (the declared mask)
    ipbox = fixture_row_box('ipv4')
    blur = [ipbox[0] - 6, ipbox[1] - 6, ipbox[2] + 12, ipbox[3] + 12, 8]
    for k in range(16):
        draw_fixture_frame(pointer=(700 + 3 * k, 500 + k), blur=blur).save(os.path.join(root, 'broll', 'send', 'f_%03d.jpg' % (k + 1)), quality=92)
    json.dump({'kind': 'seq', 'frames': 16, 'fps': 30, 'dur': 0.533, 'w': 1280, 'h': 720, 'crop': [0, 0, 1280, 720], 't0': 3.0}, open(os.path.join(root, 'broll', 'send', 'meta.json'), 'w'))
    frame.save(os.path.join(root, 'broll', 'spare', 'f_001.jpg'), quality=94)
    clips = [
        {'name': 'q', 'kind': 'still', 'shows': 'the tenancy page (median: no pointer)', 'win': [1.0, 2.0], 'n': 3, 'crop': [0, 0, 1280, 720]},
        {'name': 'nb', 'kind': 'page', 'shows': 'the tenancy page stitched from two parked positions', 'band': band,
         'layers': [{'t': 1.0, 'off': 0}, {'t': 2.0, 'off': 400}], 'trim': 30, 'chrome': {}},
        {'name': 'send', 'kind': 'seq', 'shows': 'REAL: the Globex partner row', 't0': 3.0, 't1': 4.0, 'crop': [0, 0, 1280, 720],
         'fix': [{'blur': blur}]},
        {'name': 'spare', 'kind': 'still', 'shows': 'unused take', 't': 5.0, 'crop': [0, 0, 1280, 720]},
    ]
    json.dump(clips, open(os.path.join(root, 'clips.json'), 'w'), indent=1)
    json.dump({'total': 12.0, 'cuts': [2.0, 4.0, 8.0], 'seams': [],
               'shots': [{'clip': 'q', 't0': 2.0, 't1': 4.0, 'establish': None, 'seam': False},
                         {'clip': 'nb', 't0': 4.0, 't1': 8.0, 'establish': None, 'seam': False},
                         {'clip': 'send', 't0': 8.0, 't1': 10.0, 'establish': None, 'seam': True}]},
              open(os.path.join(root, 'out', 'timeline.json'), 'w'))
    open(os.path.join(root, 'BRIEF.md'), 'w', encoding='utf-8').write(
        '---\nname: film\n---\n\n## Intent\nA fixture.\n\n## Never on screen\n<!-- one term per line -->\n- Globex\n- Initech\n\n## Bans\n- plain English\n')
    open(os.path.join(root, 'scenes', 'film.html'), 'w', encoding='utf-8').write('<html><body><div id="stage"></div><script src="shots.js"></script></body></html>\n')
    open(os.path.join(root, 'scenes', 'shots.js'), 'w', encoding='utf-8').write('window.SHOTS = [];\n')
    return {'project': root, 'cfg': {'name': 'film'}, 'qa': {'leak': {'src_size': [1280, 720]}}, 'timeline': json.load(open(os.path.join(root, 'out', 'timeline.json'))),
            'scene_html': os.path.join(root, 'scenes', 'film.html'), 'shots_js': os.path.join(root, 'scenes', 'shots.js')}


# ----------------------------------------------------------------------------------------------- selftest
def selftest(no_ocr=False):
    import shutil, tempfile
    t_all = time.perf_counter()
    td = tempfile.mkdtemp(prefix='leak_gate_')
    try:
        ctx = build_fixture(td)
        # unit: fuzzy denylist and detectors
        assert fuzzy_find('globex', 'thegl0bexpartner', 1)[0] == 1 and fuzzy_find('globex', 'nothing', 1)[0] is None
        kinds = set(k for k, _, _, _ in scan_text(FIX['url'] + ' ' + FIX['email'] + ' ' + FIX['ocid'] + ' ' + FIX['ipv4'] + ' ' + FIX['phone'] + ' Bearer abcdefghijklmnopqrstuv', ['Globex']))
        assert {'url', 'uuid', 'jwt', 'email', 'ocid', 'ipv4', 'phone', 'bearer'} <= kinds, kinds
        assert ('deny', 4, 10, 'G1obex') in scan_text('the G1obex partner', ['Globex']), scan_text('the G1obex partner', ['Globex'])
        assert not [h for h in scan_text('Revenue 1,234.56 in Q3 2026 up 12.5 % at 10:30', [])], 'plain numbers must not hit'
        # avatar on the fixture frame, no OCR
        blobs = avatar_blobs(draw_fixture_frame(), (0, 144), 1280 / 1920.0)
        assert blobs and _cover(FIX['avatar'], blobs[0]['box']) > 0.8, blobs
        assert not avatar_blobs(Image.new('RGB', (1280, 720), (240, 240, 240)), (0, 144), 1280 / 1920.0)
        # 1 — no-OCR path: avatar + denylist (authored text) only
        ctx_no = dict(ctx); ctx_no['qa'] = {'leak': {'src_size': [1280, 720], 'backend': 'none'}}
        doc0, _, _ = run_scan(ctx_no, out_path=os.path.join(td, 'leaks_noocr.json'), no_cache=True)
        kinds0 = set(h['kind'] for h in doc0['hits'])
        assert kinds0 == {'avatar', 'deny'}, kinds0
        av = [h for h in doc0['hits'] if h['kind'] == 'avatar']
        assert {h['src'] for h in av} >= {'broll/q/f_001.jpg', 'broll/nb/chrome_0.jpg', 'broll/send/f_001.jpg'}, [h['src'] for h in av]
        assert not any(h['fails'] for h in av if h['src'].startswith('broll/spare/')), 'unused clip must not fail'
        assert any(h['src'] == 'clips.json' and h['fails'] for h in doc0['hits'] if h['kind'] == 'deny'), 'Globex in clips.json "shows" must hit without OCR'
        rows0 = run(ctx_no)
        assert [n for n, _, _ in rows0] == GATE_NAMES and not rows0[0][1] and rows0[1][1] and 'ocr disabled' in rows0[1][2], rows0
        # backend-unavailable wording
        b, note = pick_backend('nonexistent')
        assert b is None and 'unavailable' in note, note
        print('  no-OCR path: %d avatar hits, %d denylist hits in authored text, unused clip excused' % (len(av), sum(1 for h in doc0['hits'] if h['kind'] == 'deny')))
        if no_ocr:
            print('leak_gate selftest OK (--no-ocr): detectors / fuzzy denylist / avatar / gate rows')
            return 0
        backend, note = pick_backend('auto', fastest=True)          # the selftest budget is 60 s: fastest engine first
        if backend is None:
            print('  WARN ' + note)
            print('leak_gate selftest OK (no OCR backend on this machine): detectors / fuzzy denylist / avatar / gate rows')
            return 0
        ctx['qa']['leak']['backend'] = backend.name
        # 2 — with OCR: every planted leak found, the applied blur on the seq holds, declared mask semantics
        doc1, note1, st1 = run_scan(ctx, out_path=os.path.join(td, 'leaks.json'))        # cache builds in out/ (fresh temp project)
        found = {}
        for h in doc1['hits']:
            found.setdefault(h['kind'], set()).add(h['src'].split('/')[1] if h['src'].startswith('broll/') else h['src'])
        for k in ('email', 'ocid', 'phone', 'deny', 'avatar'):
            assert 'q' in found.get(k, set()), ('planted %s not found in still q' % k, {k: sorted(v) for k, v in found.items()})
        assert found.get('url') or found.get('jwt') or found.get('uuid') or found.get('host'), 'address bar not read'
        assert 'ipv4' in found and 'q' in found['ipv4'], 'IP must be legible on the unmasked still'
        assert 'send' not in found.get('ipv4', set()), 'IP must be unreadable after the applied r=8 blur'
        assert any(h['src'].startswith('broll/nb/page.jpg') for h in doc1['hits']), 'page not scanned'
        assert all(not h['fails'] for h in doc1['hits'] if h['src'].startswith('broll/spare/')), 'unused clip must not fail'
        rows = run(ctx)
        assert not rows[0][1] and 'unmasked' in rows[0][2] and rows[1][1] and backend.name in rows[1][2], rows
        # declared-but-not-applied mask: text still legible inside it fails with the re-extract message
        ctx2 = json.loads(json.dumps({k: v for k, v in ctx.items()}))
        cj = json.load(open(os.path.join(td, 'clips.json')))
        eb = fixture_row_box('email'); cj[0]['fix'] = [{'blur': [eb[0] - 6, eb[1] - 6, eb[2] + 12, eb[3] + 12, 8]}]
        json.dump(cj, open(os.path.join(td, 'clips.json'), 'w'))
        doc2, _, _ = run_scan(ctx2, out_path=os.path.join(td, 'leaks2.json'))
        e2 = [h for h in doc2['hits'] if h['kind'] == 'email' and h['src'] == 'broll/q/f_001.jpg']
        assert e2 and e2[0]['masked'] and e2[0]['fails'] and 'not applied' in e2[0]['why'], e2
        # 3 — determinism: a second run (cache on, then off) is byte-identical
        run_scan(ctx2, out_path=os.path.join(td, 'leaks3.json'))
        run_scan(ctx2, out_path=os.path.join(td, 'leaks4.json'))
        b3, b4 = open(os.path.join(td, 'leaks3.json'), 'rb').read(), open(os.path.join(td, 'leaks4.json'), 'rb').read()
        assert b3 == b4 == open(os.path.join(td, 'leaks2.json'), 'rb').read(), 'leaks.json differs between runs'
        assert b'acme-corp.test' not in b3, 'redaction failed: full identifier written to leaks.json'
        per = st1['ocr_ms'] / max(1, st1['ocr_frames'])
        print('  OCR path: %s %s, %d sources, %d OCR passes (%d reused), %.0f ms/frame; found %s' % (
            backend.name, backend.version, doc1['frames'], st1['ocr_frames'], st1['reused'], per, ', '.join(sorted(found))))
        print('leak_gate selftest OK: detectors / fuzzy denylist / avatar / no-OCR path / planted leaks / applied blur holds / '
              'declared-not-applied fails / deterministic / redacted  (%.1f s)' % (time.perf_counter() - t_all))
        return 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ----------------------------------------------------------------------------------------------- CLI
def _ctx_from_project(project):
    project = os.path.abspath(project)
    cfg, qa, tl = {}, {}, None
    for name, dst in (('film.json', 'cfg'), ('qa.json', 'qa')):
        p = os.path.join(project, name)
        if os.path.exists(p):
            try:
                if dst == 'cfg': cfg = json.load(open(p, encoding='utf-8'))
                else: qa = json.load(open(p, encoding='utf-8'))
            except ValueError:
                pass
    tp = os.path.join(project, 'out', 'timeline.json')
    if os.path.exists(tp):
        try:
            tl = json.load(open(tp, encoding='utf-8'))
        except ValueError:
            tl = None
    film = os.path.join(project, cfg.get('output', 'out/%s.mp4' % cfg.get('name', 'film')))
    return {'project': project, 'cfg': cfg, 'qa': qa, 'timeline': tl, 'film': film if os.path.exists(film) else None,
            'scene_html': os.path.join(project, cfg.get('scene', 'scenes/film.html')), 'shots_js': os.path.join(project, 'scenes', 'shots.js')}


def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not argv or '-h' in argv or '--help' in argv:
        print(__doc__); return 0 if argv else 2
    if '--selftest' in argv:
        return selftest(no_ocr='--no-ocr' in argv)
    opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else d
    backend = 'none' if '--no-ocr' in argv else opt('--backend')
    deny = opt('--deny')
    if '--scan' in argv:
        imgs = [a for a in argv[argv.index('--scan') + 1:] if not a.startswith('--') and os.path.exists(a)]
        if not imgs:
            print('usage: leak_gate.py --scan IMG [IMG ...]'); return 2
        L = _cfg({})
        if backend: L['backend'] = backend
        if '--full-text' in argv: L['full_text'] = True
        denylist = load_denylist(None, {}, deny) if deny else []
        be, note = (None, 'ocr disabled') if L['backend'] == 'none' else pick_backend(L['backend'], L['text_score'])
        srcs = [{'src': p.replace('\\', '/'), 'path': p, 'clip': None, 'kind': 'image', 'coord': 'frame', 'frame': 1, 'scale': 1.0,
                 'src_rect': None, 'masks': [], 'windows': [], 'on_screen': None} for p in imgs]
        hits, stats = scan_sources(srcs, L, be, denylist)
        hits = finalize(judge(hits, L), L)
        failing = [h for h in hits if h['fails']]
        doc = {'version': VERSION, 'backend': {'name': be.name if be else None, 'version': be.version if be else None, 'note': note or None},
               'frames': stats['frames'], 'hits': hits,
               'summary': {'hits': len(hits), 'failing': len(failing), 'by_kind': {k: sum(1 for h in failing if h['kind'] == k) for k in sorted(set(h['kind'] for h in failing))}}}
        if '--json' in argv:
            print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))
        else:
            for h in hits:
                print('  %-7s %s @%s %s' % (h['kind'], h['src'], h['box'], h.get('text') or ''))
            l, o = describe(doc, stats)
            print(l); print(o)
        return 1 if any(h['fails'] for h in hits) else 0
    project = opt('--project', os.getcwd())
    if not os.path.isdir(project):
        print('no such project dir: ' + project); return 2
    ctx = _ctx_from_project(project)
    if '--seq-stride' in argv or '--max-frames' in argv or '--full-text' in argv:
        ctx['qa'].setdefault('leak', {})
        if opt('--seq-stride'): ctx['qa']['leak']['seq_stride'] = int(opt('--seq-stride'))
        if opt('--max-frames'): ctx['qa']['leak']['max_ocr_frames'] = int(opt('--max-frames'))
        if '--full-text' in argv: ctx['qa']['leak']['full_text'] = True
    out = opt('--out', os.path.join(project, _cfg(ctx['qa'])['out']))
    doc, note, stats = run_scan(ctx, backend_pref=backend, deny_file=deny, out_path=out, no_cache='--no-cache' in argv)
    leaks, ocr = describe(doc, stats)
    if '--json' in argv:
        print(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))
    else:
        print('  %-18s %s  %s' % ('leaks', 'FAIL' if doc['summary']['failing'] else 'PASS', leaks))
        print('  %-18s %s  %s' % ('leak ocr', 'PASS', ocr))
        print('  wrote ' + out)
    return 1 if doc['summary']['failing'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
