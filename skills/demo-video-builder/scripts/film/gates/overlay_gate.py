# -*- coding: utf-8 -*-
"""overlay_gate.py — QA gates for the caption lane and the graphic overlays (plug-in for qa_film.py).

  overlays safe      the caption lane and hero words stay inside title-safe (80 %, 10 % inset per edge; qa.json
                     overlay_safe_box), lower thirds / callouts / quotes inside action-safe (90 %; qa.json
                     overlay_action_box), no visible text element leaves the canvas by > 2 px
                     (> 8 px fails, <= 8 px warns), no two visible overlays intersect, nothing sits in the credit
                     footer (bottom 120/1080 of the frame, centre 60 %) during the last 4 s. data-ov-bleed="1" opts a
                     deliberate edge-kiss out of the safe-zone test only.
  caption shape      <= caption_max_words (6; keynote 5) words, <= 2 lines, each line <= caption_max_chars_per_line (42)
                     and narrower than 92 % of the lane box when measured with the real TTF, >= 0.5 s on screen, one
                     group visible at a time, >= 1.5 s median cadence (warn).
  caption timing     every caption word matches the narration WORDS within 80 ms, group windows envelop their words
                     (in <= first start, out >= last end), the SRT cues equal the shown groups (count + times, 20 ms).
  caption contrast   WCAG ratio between the lane ink and the REAL composited background under the glyphs (captions-off
                     pass, scrim alpha composited) >= 4.5 (>= 3.0 for text >= 0.04*h at weight >= 600), and no light
                     ink over a p95 background luma > 180 (washout).
  hero scarcity      promoted words: <= hero_max_per_film (2), never two co-visible, >= 0.6 s air between windows.

How it measures: a small puppeteer script (written to out/qa/measure_overlays.js) opens the scene at 1280x720,
DPR 1, seeks a 0.5 s grid plus every cut + 0.4 s and every caption mid-point, records every [data-ov] box and any
visible text box leaving the canvas, reads window.OVL.windows(), then reopens the scene with ?nocap and saves the
lane rect's pixels at every caption mid-point (out/qa/capbg/<id>.jpg) for the contrast probe. Results → out/overlays.json.

CLI:
    python gates/overlay_gate.py --selftest                       synthetic frames + fixtures, no browser
    python gates/overlay_gate.py --measure scenes/film.html       measurement pass only (needs out/timeline.json)
    python gates/overlay_gate.py --probe scenes/film.html         + writes out/caption_luma.json {phase: {mean, p95}}
                                                                  (feed it back: node lib/captions.js … --luma out/caption_luma.json)
Thresholds are the measured HyperFrames rules re-expressed; see references/captions-and-overlays.md.
"""
import json, os, subprocess, sys, tempfile

GATE_NAMES = ['overlays safe', 'caption shape', 'caption timing', 'caption contrast', 'hero scarcity']
HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)

# per-style shape tokens (mirror of CAP.STYLES: words / chars per line / lines / size as a fraction of h / weight / font file)
STYLE = {
    'anchor':      dict(words=6, chars=42, lines=2, sizeH=0.045, weight=600, ink='#F2EFE9', scrim=('shadow', 0.65), font='seguisb.ttf'),
    'broadcast':   dict(words=6, chars=34, lines=2, sizeH=0.045, weight=600, ink='#FFFFFF', scrim=('pill', 0.40), font='seguisb.ttf'),
    'documentary': dict(words=6, chars=42, lines=2, sizeH=0.045, weight=500, ink='#F5EFE6', scrim=('shadow', 0.55), font='segoeui.ttf'),
    'keynote':     dict(words=5, chars=22, lines=2, sizeH=0.16,  weight=800, ink='#FFFFFF', scrim=('none', 0.0), font='segoeuib.ttf'),
    'ink':         dict(words=6, chars=42, lines=2, sizeH=0.045, weight=600, ink='#111418', scrim=('pill-light', 0.55), font='seguisb.ttf'),
    'conference':  dict(words=6, chars=40, lines=2, sizeH=0.042, weight=700, ink='#FFFFFF', scrim=('pill-dark', 0.72), font='segoeuib.ttf'),
    'typewriter':  dict(words=8, chars=48, lines=1, sizeH=0.040, weight=500, ink='#E9F3F9', scrim=('gradient', 0.40), font='consola.ttf'),
    'clipwipe':    dict(words=6, chars=36, lines=2, sizeH=0.05,  weight=300, ink='#FFFFFF', scrim=('shadow', 0.6), font='segoeuil.ttf'),
}
FONT_DIRS = ['C:/Windows/Fonts', '/System/Library/Fonts', '/Library/Fonts', '/usr/share/fonts/truetype/dejavu']
FALLBACK_FONTS = ['segoeui.ttf', 'arial.ttf', 'Helvetica.ttc', 'DejaVuSans.ttf']

# ----------------------------------------------------------------------------- pure checks (unit-tested) ----
def luma(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def rel_lum(rgb):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def wcag(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hex_rgb(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def composite(bg, scrim):
    """Background seen through the lane's glyph-local treatment: pill = black/charcoal/white at alpha, gradient = 0.4 black,
    shadow = a soft dark halo modelled as a 35 % black composite, none = raw."""
    kind, a = scrim
    if kind == 'none':
        return bg
    col, alpha = (0, 0, 0), a
    if kind == 'pill-light':
        col = (255, 255, 255)
    elif kind == 'pill-dark':
        col = (22, 24, 29)
    elif kind == 'shadow':
        alpha = 0.35
    return tuple(bg[i] * (1 - alpha) + col[i] * alpha for i in range(3))


def contrast_check(ink_hex, bg_mean, bg_p95, scrim, size_px, weight, h):
    """-> (ok, ratio, threshold, note). Large text (>= 0.04*h at weight >= 600) needs 3.0, else 4.5; light ink over a p95
    composited luma > 180 is a washout regardless of the mean."""
    ink = hex_rgb(ink_hex)
    thr = 3.0 if (size_px >= 0.04 * h and weight >= 600) else 4.5
    cm, cp = composite(bg_mean, scrim), composite(bg_p95, scrim)
    ratio = wcag(ink, cm)
    ok = ratio >= thr
    note = ''
    if luma(ink) > 128 and luma(cp) > 180:
        ok, note = False, 'washout: light ink over p95 luma %.0f' % luma(cp)
    return ok, ratio, thr, note


def intersects(a, b, pad=0.0):
    return a[0] < b[0] + b[2] + pad and b[0] < a[0] + a[2] + pad and a[1] < b[1] + b[3] + pad and b[1] < a[1] + a[3] + pad


def inside(box, safe, tol=1.0):
    return box[0] >= safe[0] - tol and box[1] >= safe[1] - tol and box[0] + box[2] <= safe[0] + safe[2] + tol and box[1] + box[3] <= safe[1] + safe[3] + tol


def safe_box(W, H, frac=0.8):
    ix, iy = W * (1 - frac) / 2, H * (1 - frac) / 2
    return [ix, iy, W - 2 * ix, H - 2 * iy]


def credit_zone(W, H):
    return [W * 0.2, H - 120.0 * H / 1080.0, W * 0.6, 120.0 * H / 1080.0]


TITLE_SAFE_KINDS = ('cap', 'hero')          # captions and key text: title-safe (80 %); lower thirds / cards / quotes: action-safe (90 %)


def check_overlays(samples, W, H, dur, frac=0.8, keep_out=4.0, action=0.9):
    """samples: [{t, boxes:[{kind, id, box:[x,y,w,h], opacity, bleed, text}], overflow:[{text, off}]}] -> (fails, warns)."""
    sb, ab, cz, fails, warns = safe_box(W, H, frac), safe_box(W, H, action), credit_zone(W, H), [], []
    for s in samples:
        vis = [b for b in s['boxes'] if b.get('opacity', 1) >= 0.06 and b['box'][2] > 0 and b['box'][3] > 0]
        for b in vis:
            title = b['kind'] in TITLE_SAFE_KINDS
            if not b.get('bleed') and not inside(b['box'], sb if title else ab):
                fails.append('t=%.2f %s "%s" outside %s-safe %s' % (s['t'], b['kind'], (b.get('text') or '')[:28], 'title' if title else 'action', [round(v) for v in b['box']]))
            if s['t'] >= dur - keep_out and intersects(b['box'], cz):
                fails.append('t=%.2f %s in the credit footer' % (s['t'], b['kind']))
        for i in range(len(vis)):
            for j in range(i + 1, len(vis)):
                a, b = vis[i], vis[j]
                if a['kind'] == 'pip' or b['kind'] == 'pip':
                    continue
                if intersects(a['box'], b['box']):
                    fails.append('t=%.2f %s x %s collide' % (s['t'], a['kind'], b['kind']))
        for o in s.get('overflow', []):
            worst = max(o['off'].values()) if o.get('off') else 0
            (fails if worst > 8 else warns).append('t=%.2f "%s" off-canvas %s' % (s['t'], o.get('text', '')[:28], o['off']))
    return fails, warns


def _font(name, px):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for d in FONT_DIRS:
        for n in [name] + FALLBACK_FONTS:
            p = os.path.join(d, n)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, int(px))
                except Exception:
                    pass
    return None


def check_shape(groups, W, H, max_words=6, max_chars=42, keep_out=4.0, end=None):
    fails, warns, durs, prev = [], [], [], None
    for g in groups:
        if g.get('fate') == 'drop':
            continue
        st = STYLE.get(g.get('style', 'anchor'), STYLE['anchor'])
        mw, mc = min(max_words, st['words']), min(max_chars, st['chars']) if st['chars'] < max_chars else max_chars
        lines = g.get('lines') or [g.get('text', '')]
        if len(g.get('words', [])) > mw:
            fails.append('%s %d words > %d' % (g['id'], len(g['words']), mw))
        if len(lines) > st['lines']:
            fails.append('%s %d lines > %d' % (g['id'], len(lines), st['lines']))
        for ln in lines:
            if len(ln) > mc:
                fails.append('%s line "%s" %d chars > %d' % (g['id'], ln[:20], len(ln), mc))
        px = st['sizeH'] * H
        f = _font(st['font'], px)
        box_w = (0.9 if g.get('fate') == 'embed' else 0.8) * W * 0.92
        if f is not None:
            for ln in lines:
                w = f.getlength(ln)
                if w > box_w:
                    fails.append('%s line "%s" measures %.0f px > 92%% of the box (%.0f)' % (g['id'], ln[:20], w, box_w))
        d = g['out'] - g['in']
        durs.append(d)
        if d < 0.5 - 1e-6:
            fails.append('%s on screen %.2f s < 0.5' % (g['id'], d))
        if prev is not None and g['in'] < prev['out'] - 1e-3:
            fails.append('%s co-visible with %s' % (g['id'], prev['id']))
        if len(lines) == 2 and len(lines[1].split()) == 1 and len(lines[0].split()) > 2:
            warns.append('%s dangling 1-word line' % g['id'])
        prev = g
    if durs:
        med = sorted(durs)[len(durs) // 2]
        if med < 1.5:
            warns.append('median caption %.2f s < 1.5 s cadence (strobe risk)' % med)
    if end is not None:
        late = [g['id'] for g in groups if g.get('fate') != 'drop' and g['out'] > end - keep_out]
        if late:
            warns.append('%d groups reach the credit window (lane hides them; sidecar keeps them)' % len(late))
    return fails, warns


def check_timing(groups, phases, words, srt_cues=None, tol=0.08):
    """phases: [{name,start,dur}], words: {phase: [{t,d,w}]} (vo/<name>_words.json). -> (fails, warns)."""
    fails, warns = [], []
    P = {p['name']: p['start'] for p in phases}
    for g in groups:
        ws = g.get('words', [])
        if not ws:
            fails.append('%s has no words' % g['id']); continue
        if g['in'] > ws[0]['start'] + 1e-3:
            fails.append('%s in %.2f > first word %.2f' % (g['id'], g['in'], ws[0]['start']))
        if g['out'] < ws[-1]['end'] - 1e-3:
            fails.append('%s out %.2f < last word end %.2f (fades during speech)' % (g['id'], g['out'], ws[-1]['end']))
        src = (words or {}).get(g['phase'])
        if src is None or g['phase'] not in P:
            warns.append('%s phase %s not in WORDS' % (g['id'], g['phase'])); continue
        for w in ws:
            i = w.get('i')
            if i is None or i >= len(src):
                fails.append('%s word "%s" has no WORDS index' % (g['id'], w.get('w'))); continue
            drift = abs(P[g['phase']] + src[i]['t'] - w['start'])
            if drift > tol:
                fails.append('%s "%s" drifts %.0f ms from the narration' % (g['id'], w.get('w'), drift * 1000))
            if ''.join(c for c in str(src[i]['w']).lower() if c.isalnum()) != ''.join(c for c in str(w.get('w', '')).lower() if c.isalnum()):
                fails.append('%s word "%s" != narration "%s"' % (g['id'], w.get('w'), src[i]['w']))
    if srt_cues is not None:
        shown = [g for g in groups if g.get('fate') != 'drop']
        if len(srt_cues) != len(shown):
            fails.append('SRT has %d cues, lane shows %d groups' % (len(srt_cues), len(shown)))
        else:
            for (a, b), g in zip(srt_cues, shown):
                if abs(a - g['in']) > 0.02 or (abs(b - g['out']) > 0.02 and b < g['out']):
                    fails.append('%s SRT %.2f-%.2f != lane %.2f-%.2f' % (g['id'], a, b, g['in'], g['out']))
                    break
    return fails, warns


def crop_stats(path):
    """(mean rgb, p95 rgb-by-luma) of a saved lane crop, inset 1 px, <= 12x6 grid like the HyperFrames contrast audit."""
    from PIL import Image
    im = Image.open(path).convert('RGB')
    w, h = im.size
    xs = list(range(1, max(2, w - 1), max(1, (w - 2) // 12))); ys = list(range(1, max(2, h - 1), max(1, (h - 2) // 6)))
    px = [im.getpixel((x, y)) for y in ys for x in xs] or [im.getpixel((0, 0))]
    mean = tuple(sum(p[i] for p in px) / len(px) for i in range(3))
    px.sort(key=luma)
    return mean, px[min(len(px) - 1, int(0.95 * (len(px) - 1)))]


def check_contrast(groups, crops, H, luma_override=None):
    """crops: {group id: path to the lane crop (captions-off pass)}; -> (fails, warns, per_phase_luma)."""
    fails, warns, per_phase = [], [], {}
    for g in groups:
        if g.get('fate') == 'drop' or g['id'] not in crops:
            continue
        st = STYLE.get(g.get('style', 'anchor'), STYLE['anchor'])
        mean, p95 = crop_stats(crops[g['id']])
        per_phase.setdefault(g['phase'], []).append((luma(mean), luma(p95)))
        ink, scrim = st['ink'], st['scrim']
        if luma_override and luma_override.get(g['phase'], {}).get('mean', 0) > 150:   # the lane switched to dark ink for this phase
            ink, scrim = STYLE['ink']['ink'], STYLE['ink']['scrim']
        ok, ratio, thr, note = contrast_check(ink, mean, p95, scrim, st['sizeH'] * H, st['weight'], H)
        if not ok:
            fails.append('%s %.2f:1 < %.1f (%s)' % (g['id'], ratio, thr, note or 'bg luma %.0f' % luma(mean)))
    out = {ph: {'mean': round(sum(m for m, _ in v) / len(v), 1), 'p95': round(max(p for _, p in v), 1)} for ph, v in per_phase.items()}
    return fails, warns, out


def check_heroes(windows, max_per_film=2):
    H = sorted([w for w in windows if w.get('kind') == 'hero'], key=lambda w: w['t0'])
    bad = []
    if len(H) > max_per_film:
        bad.append('%d hero windows > %d' % (len(H), max_per_film))
    for a, b in zip(H, H[1:]):
        if b['t0'] < a['t1']:
            bad.append('%s and %s co-visible' % (a['id'], b['id']))
        elif b['t0'] - a['t1'] < 0.6:
            bad.append('%.2f s air between %s and %s (< 0.6)' % (b['t0'] - a['t1'], a['id'], b['id']))
    return bad


# ----------------------------------------------------------------------------- the measurement pass ----
MEASURE_JS = r"""
/* measure_overlays.js (generated by gates/overlay_gate.py) — seeks the scene and records overlay boxes.
   node measure_overlays.js <scene.html> <times.json> <out/overlays.json> <capbg dir> */
const puppeteer = require('puppeteer'); const fs = require('fs'); const path = require('path');
const [SCENE, TIMES, OUT, CAPDIR] = process.argv.slice(2);
function chromePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) return process.env.PUPPETEER_EXECUTABLE_PATH;
  try { const p = puppeteer.executablePath(); if (fs.existsSync(p)) return p; } catch (e) {}
  return ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(fs.existsSync);
}
const T = JSON.parse(fs.readFileSync(TIMES, 'utf8'));
const url = q => 'file://' + path.resolve(SCENE.split('?')[0]) + '?render' + q;
async function open(b, q) {
  const p = await b.newPage(); await p.setViewport({ width: T.W, height: T.H, deviceScaleFactor: 1 });
  await p.goto(url(q), { waitUntil: 'load', timeout: 120000 }); await new Promise(r => setTimeout(r, 800));
  await p.evaluate(async () => { try { await document.fonts.ready; } catch (e) {} });
  return p;
}
const MEASURE = (W, H) => {
  const out = { boxes: [], overflow: [] };
  for (const el of document.querySelectorAll('[data-ov]')) {
    const cs = getComputedStyle(el); let op = parseFloat(cs.opacity); let p = el.parentElement;
    while (p && p !== document.body) { const c = getComputedStyle(p); op *= parseFloat(c.opacity); if (c.visibility === 'hidden' || c.display === 'none') op = 0; p = p.parentElement; }
    if (cs.visibility === 'hidden' || cs.display === 'none') op = 0;
    const r = el.getBoundingClientRect();
    out.boxes.push({ kind: el.getAttribute('data-ov'), id: el.getAttribute('data-ovid') || '', box: [r.left, r.top, r.width, r.height], opacity: +op.toFixed(3),
      bleed: el.getAttribute('data-ov-bleed') === '1', text: (el.textContent || '').trim().slice(0, 60) });
  }
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('#camera')) continue;                       // footage is framed by design; overlays and cards are screen space
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
    if (!own) continue;
    const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.06) continue;
    let p = el.parentElement, hid = false; while (p && p !== document.body) { const c = getComputedStyle(p); if (c.visibility === 'hidden' || parseFloat(c.opacity) < 0.06) { hid = true; break; } p = p.parentElement; }
    if (hid) continue;
    const b = el.getBoundingClientRect(); if (!b.width || !b.height) continue;
    const off = { left: Math.max(0, Math.round(-b.left - 2)), right: Math.max(0, Math.round(b.right - W - 2)), top: Math.max(0, Math.round(-b.top - 2)), bottom: Math.max(0, Math.round(b.bottom - H - 2)) };
    if (off.left || off.right || off.top || off.bottom) out.overflow.push({ text: own.slice(0, 42), off });
  }
  out.windows = window.OVL && window.OVL.windows ? window.OVL.windows() : [];
  out.hasCap = !!(window.CAP && window.CAP.lane);
  return out;
};
(async () => {
  const b = await puppeteer.launch({ headless: 'new', executablePath: chromePath(), args: ['--no-sandbox', '--hide-scrollbars', '--font-render-hinting=none', '--disable-lcd-text'] });
  const res = { W: T.W, H: T.H, samples: [], windows: [], crops: {}, hasCap: false };
  const p = await open(b, '');
  let first = true;
  for (const t of T.times) {
    await p.evaluate(t => (first => first ? window.__seek(t) : (window.__step || window.__seek)(t))(true), t);
    const m = await p.evaluate(MEASURE, T.W, T.H);
    res.samples.push({ t, boxes: m.boxes, overflow: m.overflow }); res.windows = m.windows; res.hasCap = m.hasCap; first = false;
  }
  await p.close();
  if (T.caps && T.caps.length) {                                   // captions-off pass: the real pixels under each caption
    fs.mkdirSync(CAPDIR, { recursive: true });
    const q = await open(b, '&nocap');
    for (const c of T.caps) {
      await q.evaluate(t => window.__seek(t), c.t);
      const r = c.box; const clip = { x: Math.max(0, r[0] + 1), y: Math.max(0, r[1] + 1), width: Math.max(2, Math.min(T.W - r[0] - 2, r[2] - 2)), height: Math.max(2, Math.min(T.H - r[1] - 2, r[3] - 2)) };
      const f = path.join(CAPDIR, c.id + '.jpg'); await q.screenshot({ type: 'jpeg', quality: 92, path: f, clip }); res.crops[c.id] = f;
    }
    await q.close();
  }
  await b.close();
  fs.mkdirSync(path.dirname(path.resolve(OUT)), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(res));
  console.log('overlays: ' + res.samples.length + ' samples, ' + res.windows.length + ' overlay windows, ' + Object.keys(res.crops).length + ' caption crops -> ' + OUT);
})().catch(e => { console.error(e); process.exit(1); });
"""


def measure(scene_html, project, timeline, groups, W=1280, H=720, dur=None, grid=0.5):
    """Run the puppeteer pass. Returns the parsed out/overlays.json (or raises)."""
    qa_dir = os.path.join(project, 'out', 'qa'); os.makedirs(qa_dir, exist_ok=True)
    js = os.path.join(qa_dir, 'measure_overlays.js')
    open(js, 'w', encoding='utf-8').write(MEASURE_JS)
    total = float(dur or timeline.get('total', 0))
    times = set()
    t = 0.3
    while t < total - 0.1:
        times.add(round(t, 3)); t += grid
    for c in timeline.get('cuts', []):
        if 0 < c + 0.4 < total:
            times.add(round(c + 0.4, 3))
    caps = []
    for g in groups or []:
        if g.get('fate') == 'drop':
            continue
        mid = round((g['in'] + g['out']) / 2, 3)
        times.add(mid)
        caps.append({'id': g['id'], 't': mid})
    times = sorted(times)
    tj = os.path.join(qa_dir, 'overlay_times.json')
    out = os.path.join(project, 'out', 'overlays.json')
    # pass 1 (boxes) decides the lane rect per caption; pass 2 needs those rects -> run pass 1 first without crops
    json.dump({'W': W, 'H': H, 'times': times, 'caps': []}, open(tj, 'w'))
    env = dict(os.environ)
    if 'NODE_PATH' not in env:
        for cand in [os.path.join(project, 'node_modules'), os.path.join(FILM_DIR, 'node_modules')]:
            if os.path.isdir(cand):
                env['NODE_PATH'] = cand
    r = subprocess.run(['node', js, scene_html, tj, out, os.path.join(qa_dir, 'capbg')], cwd=project, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError('measure pass failed: ' + (r.stderr or r.stdout)[-400:])
    res = json.load(open(out, encoding='utf-8'))
    if caps and res.get('hasCap'):
        by_t = {s['t']: s for s in res['samples']}
        want = []
        for c in caps:
            s = by_t.get(c['t'])
            box = next((b['box'] for b in (s or {}).get('boxes', []) if b['kind'] == 'cap' and b['opacity'] >= 0.06), None)
            if box and box[2] > 4 and box[3] > 4:
                want.append({'id': c['id'], 't': c['t'], 'box': box})
        if want:
            json.dump({'W': W, 'H': H, 'times': [], 'caps': want}, open(tj, 'w'))
            out2 = os.path.join(qa_dir, 'overlays_caps.json')
            r = subprocess.run(['node', js, scene_html, tj, out2, os.path.join(qa_dir, 'capbg')], cwd=project, capture_output=True, text=True, env=env)
            if r.returncode != 0:
                raise RuntimeError('caption crop pass failed: ' + (r.stderr or r.stdout)[-400:])
            res['crops'] = json.load(open(out2, encoding='utf-8')).get('crops', {})
            json.dump(res, open(out, 'w'))
    return res


# ----------------------------------------------------------------------------- gate entry point ----
def run(ctx):
    qa, project = ctx.get('qa', {}), ctx['project']
    W, H = 1280, 720
    dur = float(ctx.get('dur') or ctx['timeline'].get('total', 0))
    gpath = os.path.join(project, 'out', 'caption_groups.json')
    gdoc = json.load(open(gpath, encoding='utf-8')) if os.path.exists(gpath) else None
    groups = (gdoc or {}).get('groups', [])
    keep_out = float((gdoc or {}).get('creditKeepOut', 4.0))
    res = []
    try:
        M = measure(ctx['scene_html'], project, ctx['timeline'], groups, W, H, dur, grid=float(qa.get('overlay_grid', 0.5)))
    except Exception as e:                                   # a gate that cannot measure is a failed gate, never a skipped one
        return [(GATE_NAMES[0], False, 'measure pass: %s' % str(e)[:140])] + [(n, False, 'no measurement') for n in GATE_NAMES[1:]]
    fails, warns = check_overlays(M['samples'], W, H, dur, float(qa.get('overlay_safe_box', 0.8)), keep_out, float(qa.get('overlay_action_box', 0.9)))
    nbox = sum(len([b for b in s['boxes'] if b['opacity'] >= 0.06]) for s in M['samples'])
    res.append((GATE_NAMES[0], not fails, (fails[:3] if fails else '%d samples, %d visible overlay boxes' % (len(M['samples']), nbox)) if not warns or fails else '%d samples, %d boxes; warn %s' % (len(M['samples']), nbox, warns[:2])))
    if gdoc is None:
        res += [(n, True, 'no caption lane (out/caption_groups.json absent)') for n in GATE_NAMES[1:4]]
    else:
        f, w = check_shape(groups, W, H, int(qa.get('caption_max_words', 6)), int(qa.get('caption_max_chars_per_line', 42)), keep_out, gdoc.get('end'))
        shown = len([g for g in groups if g.get('fate') != 'drop'])
        res.append((GATE_NAMES[1], not f, f[:3] if f else '%d groups shown%s' % (shown, '; warn %s' % w[:2] if w else '')))
        srt = ctx.get('srt')
        cues = None
        if srt and os.path.exists(srt):
            sys.path.insert(0, os.path.join(FILM_DIR, 'tools'))
            try:
                from captions_srt import parse_srt
                cues = parse_srt(open(srt, encoding='utf-8').read())
            except Exception:
                cues = None
        f, w = check_timing(groups, ctx['timeline'].get('phases', []), ctx.get('words'), cues)
        res.append((GATE_NAMES[2], not f, f[:3] if f else 'words within 80 ms, windows envelop, SRT == lane%s' % ('; warn %s' % w[:2] if w else '')))
        if M.get('crops'):
            f, w, per_phase = check_contrast(groups, M['crops'], H, (gdoc.get('luma') or None))
            json.dump(per_phase, open(os.path.join(project, 'out', 'caption_luma.json'), 'w'), indent=1)
            res.append((GATE_NAMES[3], not f, f[:3] if f else '%d captions probed, per-phase luma -> out/caption_luma.json' % len(M['crops'])))
        else:
            res.append((GATE_NAMES[3], not M.get('hasCap') or not shown, 'no caption crops (lane not drawn in the scene?)' if shown and M.get('hasCap') else 'lane off'))
    bad = check_heroes(M.get('windows', []), int(qa.get('hero_max_per_film', 2)))
    nh = len([w for w in M.get('windows', []) if w.get('kind') == 'hero'])
    res.append((GATE_NAMES[4], not bad, bad[:3] if bad else '%d hero window%s' % (nh, '' if nh == 1 else 's')))
    return res


# ----------------------------------------------------------------------------- selftest + CLI ----
def selftest():
    from PIL import Image
    W, H, dur = 1280, 720, 40.0
    sb = safe_box(W, H); assert [round(v) for v in sb] == [128, 72, 1024, 576], sb
    # overlays: a safe lower third, a caption, an off-safe callout, a collision, a credit-zone hit, an 11 px overflow
    S = [{'t': 5.0, 'boxes': [{'kind': 'lt', 'id': 'lt1', 'box': [80, 560, 400, 80], 'opacity': 1}, {'kind': 'cap', 'id': '', 'box': [520, 600, 600, 44], 'opacity': 1}], 'overflow': []},
         {'t': 9.0, 'boxes': [{'kind': 'callout', 'id': 'c1', 'box': [1100, 500, 300, 120], 'opacity': 1}], 'overflow': [{'text': 'long persona name', 'off': {'right': 11}}]},
         {'t': 12.0, 'boxes': [{'kind': 'lt', 'id': 'lt2', 'box': [200, 500, 400, 80], 'opacity': 1}, {'kind': 'cap', 'id': '', 'box': [300, 540, 600, 44], 'opacity': 1}], 'overflow': []},
         {'t': 37.5, 'boxes': [{'kind': 'cap', 'id': '', 'box': [400, 605, 400, 40], 'opacity': 0.9}], 'overflow': []},
         {'t': 20.0, 'boxes': [{'kind': 'hero', 'id': 'h', 'box': [0, 300, 1280, 160], 'opacity': 1, 'bleed': True}], 'overflow': [{'text': 'kiss', 'off': {'left': 3}}]}]
    f, w = check_overlays(S, W, H, dur)
    assert len(f) == 4 and any('action-safe' in x for x in f) and any('collide' in x for x in f) and any('credit' in x for x in f) and any('off-canvas' in x for x in f), f
    assert len(w) == 1, w                                     # the 3 px kiss is a warning, the bleed opt-out skips the safe test
    # shape
    G = [{'id': 'cg-0', 'phase': 'hook', 'style': 'anchor', 'fate': 'rail', 'in': 0.02, 'out': 2.6, 'lines': ['Every Monday, the operations', 'lead at Acme asks.'],
          'words': [{'w': 'Every', 'start': 0.1, 'end': 0.3, 'i': 0}, {'w': 'Monday,', 'start': 0.36, 'end': 0.7, 'i': 1}, {'w': 'the', 'start': 0.76, 'end': 0.9, 'i': 2}]},
         {'id': 'cg-1', 'phase': 'hook', 'style': 'anchor', 'fate': 'rail', 'in': 2.5, 'out': 2.8, 'lines': ['a', 'b', 'c'], 'words': [{'w': 'x', 'start': 2.55, 'end': 2.7, 'i': 3}] * 7},
         {'id': 'cg-2', 'phase': 'close', 'style': 'keynote', 'fate': 'embed', 'in': 30.0, 'out': 32.0, 'lines': ['ONE ANSWER THE WHOLE TEAM CAN TRUST TODAY'], 'words': [{'w': 'One', 'start': 30.1, 'end': 30.3, 'i': 0}]}]
    f, w = check_shape(G, W, H, end=41.2)
    assert any('7 words' in x for x in f) and any('3 lines' in x for x in f) and any('< 0.5' in x for x in f) and any('co-visible' in x for x in f), f
    assert any('chars >' in x for x in f) and any('92%' in x for x in f), f
    assert not [x for x in f if x.startswith('cg-0')], f
    # timing
    phases = [{'name': 'hook', 'start': 0.0, 'dur': 9.0}, {'name': 'close', 'start': 29.0, 'dur': 5.0}]
    words = {'hook': [{'t': 0.1, 'd': 0.2, 'w': 'Every'}, {'t': 0.36, 'd': 0.34, 'w': 'Monday,'}, {'t': 0.76, 'd': 0.14, 'w': 'the'}, {'t': 2.55, 'd': 0.15, 'w': 'x'}], 'close': [{'t': 1.1, 'd': 0.2, 'w': 'One'}]}
    f, w = check_timing(G[:1], phases, words, srt_cues=[(0.02, 2.6)])
    assert not f, f
    bad = dict(G[0]); bad['in'] = 0.35; bad['words'] = [dict(G[0]['words'][0], start=0.3)] + G[0]['words'][1:]
    f, w = check_timing([bad], phases, words, srt_cues=[(0.5, 2.6), (3, 4)])
    assert any('in 0.35 > first' in x for x in f) and any('drifts 200 ms' in x for x in f) and any('SRT has 2' in x for x in f), f
    # contrast: synthetic crops — dark footage, white product page, mid grey
    d = tempfile.mkdtemp()
    crops = {}
    for gid, col in [('cg-dark', (20, 24, 30)), ('cg-white', (250, 250, 252)), ('cg-mid', (120, 120, 120))]:
        p = os.path.join(d, gid + '.jpg'); Image.new('RGB', (400, 60), col).save(p, quality=95); crops[gid] = p
    GG = [{'id': k, 'phase': k, 'style': 'anchor', 'fate': 'rail', 'in': 0, 'out': 1} for k in crops]
    f, w, per = check_contrast(GG, crops, H)
    assert [x.split()[0] for x in f] == ['cg-white'], f                       # anchor (shadow) fails only over the white page
    assert per['cg-white']['mean'] > 240 and per['cg-dark']['mean'] < 40, per
    f2, _, _ = check_contrast(GG, crops, H, luma_override=per)                 # with the probe fed back the lane switches to dark ink
    assert not f2, f2
    ok, ratio, thr, note = contrast_check('#FFFFFF', (250, 250, 250), (255, 255, 255), ('none', 0.0), 32.4, 600, 720)
    assert not ok and 'washout' in note, (ok, ratio, note)
    assert abs(wcag((255, 255, 255), (0, 0, 0)) - 21.0) < 0.01
    # heroes
    Wn = [{'kind': 'hero', 'id': 'h1', 't0': 10, 't1': 12.4}, {'kind': 'hero', 'id': 'h2', 't0': 12.8, 't1': 15}, {'kind': 'hero', 'id': 'h3', 't0': 14.5, 't1': 16}, {'kind': 'lt', 'id': 'l', 't0': 0, 't1': 5}]
    bad = check_heroes(Wn)
    assert len(bad) == 3 and any('co-visible' in x for x in bad) and any('air' in x for x in bad) and any('> 2' in x for x in bad), bad
    assert not check_heroes(Wn[:1])
    print('overlay_gate selftest OK: safe box %s, overflow/collision/credit, shape, timing, contrast (dark %.0f / white %.0f / mid %.0f luma), heroes'
          % ([round(v) for v in sb], per['cg-dark']['mean'], per['cg-white']['mean'], per['cg-mid']['mean']))


if __name__ == '__main__':
    argv = sys.argv[1:]
    if '--selftest' in argv:
        selftest(); sys.exit(0)
    if '--measure' in argv or '--probe' in argv:
        scene = argv[argv.index('--measure' if '--measure' in argv else '--probe') + 1]
        project = os.path.abspath(argv[argv.index('--project') + 1]) if '--project' in argv else os.getcwd()
        TL = json.load(open(os.path.join(project, 'out', 'timeline.json'), encoding='utf-8'))
        gp = os.path.join(project, 'out', 'caption_groups.json')
        gdoc = json.load(open(gp, encoding='utf-8')) if os.path.exists(gp) else {'groups': []}
        res = measure(scene, project, TL, gdoc['groups'], dur=float(gdoc.get('end') or TL['total']))
        dur = float(gdoc.get('end') or TL['total'])
        f, w = check_overlays(res['samples'], res['W'], res['H'], dur)
        print('overlays safe: %s %s' % ('PASS' if not f else 'FAIL', f[:4] or w[:2] or ''))
        if res.get('crops'):
            f, w, per = check_contrast(gdoc['groups'], res['crops'], res['H'], gdoc.get('luma'))
            json.dump(per, open(os.path.join(project, 'out', 'caption_luma.json'), 'w'), indent=1)
            print('caption contrast: %s %s  luma per phase -> out/caption_luma.json %s' % ('PASS' if not f else 'FAIL', f[:4] or '', per))
        print('heroes:', check_heroes(res.get('windows', [])) or 'ok (%d windows)' % len(res.get('windows', [])))
        sys.exit(0)
    print(__doc__)
