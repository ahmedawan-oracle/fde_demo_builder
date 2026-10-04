# -*- coding: utf-8 -*-
"""text_gate.py — qa_film.py plug-in gate: text-beat economics + design adherence on the AUTHORED layers.

GATE_NAMES (in order):
  text budget      rendered strings in the authored scene/shots files (HTML text nodes + JS string literals, comments
                   stripped): FAIL if a string of >= 8 words is also spoken verbatim in the narration (captions already
                   print the words — double-print); WARN on any rendered string > 9 words (motion-graphics copy is a hero
                   word, a stat, a one-word emphasis).
  narration pace   per phase of vo_script.py against vo/<name>_phases.json: words / measured seconds. WARN outside
                   1.8–3.0 w/s (natural ~2.5), FAIL above 3.4; WARN on a phase over 24 words (1–2 sentences, 6–20 words).
  brief message    BRIEF.md (qa.json "brief", default BRIEF.md): message non-empty and >= 60 % of its content words appear
                   in the narration or the authored text — the film provably says its one thing (fuzzy, so it does not
                   fight the narration edit loop); honesty_line spoken. Skipped (PASS) when there is no BRIEF.md.
  design tokens    design.md (qa.json "design", default design.md): every hex / rgb(a) literal in authored CSS/JS is in
                   the declared palette (alpha variants allowed when allow_alpha), every font-family is declared; WARN on
                   radii / shadows outside the declared levels and on font sizes under scale.justify_below. Skipped (PASS)
                   when there is no design.md. Product footage is never scanned — only authored CSS/JS.
  lazy defaults    the AI-design tells, grep'd on the authored files: gradient ground on dark, gradient text, pure
                   #000/#fff, > 2 left-edge accent stripes, banned monoculture fonts, bouncy eases, clock-driven ambient
                   drift (screensaver), decorative opacity under 10 %, type under the stage floor. WARN by default; rows
                   named in qa.json "css_fail" FAIL (recommended once the scene is yours: ["gradient-ground", "banned-font"]).

qa.json keys (all optional):
  "text": {"double_print_words": 8, "long_string_words": 9, "exempt": ["Fictional company · synthetic data"]}
  "pace": {"warn": [1.8, 3.0], "fail": 3.4, "max_words": 24}
  "brief": "BRIEF.md", "message_coverage": 0.6, "design": "design.md", "css_fail": [], "css_patterns": {name: regex}
Run `python gates/text_gate.py --selftest` (synthetic project, no render).
"""
import json, os, re, sys, importlib.util

GATE_NAMES = ['text budget', 'narration pace', 'brief message', 'design tokens', 'lazy defaults']

DEFAULTS = {
    'text': {'double_print_words': 8, 'long_string_words': 9, 'exempt': []},
    'pace': {'warn': [1.8, 3.0], 'fail': 3.4, 'max_words': 24},
    'message_coverage': 0.6,
    'stage_min_px': 11,                # 16 px at 1080p / 1.5 — the label floor on the 1280×720 stage
}
STOP = set('a an the and or of to in on for with at by from as is are was were be it its this that these those we you '
           'they our your their one same every any all can will into than then there here what which who whom how now'.split())
GENERIC_FONTS = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif', 'ui-sans-serif',
                 'ui-monospace', 'inherit', 'initial', 'unset', 'emoji', 'math'}
BANNED_FONTS = {'Inter', 'Roboto', 'Open Sans', 'Noto Sans', 'Arimo', 'Lato', 'Source Sans', 'PT Sans', 'Nunito', 'Poppins',
                'Outfit', 'Sora', 'Playfair Display', 'Cormorant Garamond', 'Bodoni Moda', 'EB Garamond', 'Cinzel', 'Prata', 'Syne'}
# name → (regex, flags, mode, why).  mode: 'any' = one hit is a finding; 'count>2' = more than two hits
LAZY = {
    'gradient-ground': (r'(?:#stage|body|html)[^{}]*\{[^{}]*background(?:-image)?\s*:[^;}]*linear-gradient', re.S,
                        'any', 'a full-screen linear gradient on a dark ground bands under H.264 — use a solid, a radial, or solid + local glow'),
    'gradient-text': (r'background-clip\s*:\s*text', 0, 'any', 'gradient text is the first AI-design tell'),
    'pure-bw': (r'(?<![0-9a-fA-F])#(?:000|fff|000000|ffffff)\b', re.I, 'any', 'pure #000/#fff — tint toward the ground hue'),
    'left-stripe': (r'border-left\s*:\s*[3-9]px\s+solid', 0, 'count>2', 'left-edge accent stripes on more than two selectors'),
    'bouncy-ease': (r'\b(?:back|elastic|bounce)(?:\.(?:in|out|inOut))?\b|cubic-bezier\([^)]*,\s*1\.[3-9]\d*\s*,', 0, 'any',
                    'bouncy eases only when the beat is explicitly playful'),
    'screensaver-drift': (r'(?:Math\.sin|Math\.cos)\(\s*t\s*\*|\*\s*t\s*%\s*\d', 0, 'any',
                          'clock-driven ambient drift reads as a screensaver — reveal the next piece on its spoken word'),
    'ghost-opacity': (r'opacity\s*:\s*0?\.0\d', 0, 'any', 'decorative opacity under 10 % is invisible after encoding'),
}


# ------------------------------------------------------------------------------------------------ helpers
def strip(s):
    return re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S))


def norm(s):
    return ' '.join(re.sub(r'[^\w\s]', ' ', re.sub(r"['’]", '', (s or '').lower())).split())


def words(s):
    return re.findall(r"[A-Za-z0-9][\w'’-]*", s or '')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def authored_files(ctx):
    out = []
    for f in ctx['qa'].get('authored', ['scenes/film.html', 'scenes/shots.js']):
        p = f if os.path.isabs(f) else os.path.join(ctx['project'], f)
        if os.path.exists(p):
            out.append((p, _read(p)))
    return out


def rendered_strings(src, is_html):
    """Human-readable strings a scene could put on screen: HTML text nodes outside <script>/<style>, plus JS/HTML
    string literals of >= 2 words that read as prose (not selectors, paths, CSS or code)."""
    src = strip(src)
    out = []
    if is_html:
        body = re.sub(r'<script\b.*?</script>|<style\b.*?</style>', ' ', src, flags=re.S | re.I)
        for line in re.sub(r'<[^>]+>', '\n', body).splitlines():
            if len(words(line)) >= 2:
                out.append(line.strip())
    for m in re.finditer(r"'([^'\\\n]{3,}?)'|\"([^\"\\\n]{3,}?)\"|`([^`\n]{3,}?)`", src):
        s = (m.group(1) or m.group(2) or m.group(3)).strip()
        if len(words(s)) < 2 or re.match(r'[#.\[]|\.\./|/|\w+\.(js|png|jpg|mp4|json|html)', s):
            continue
        if re.search(r'\d+px|:\s*\w|[{};=<>]|\(\)', s) and not re.search(r'[.!?…]$', s):
            continue
        out.append(s)
    return out


def css_declarations(src):
    """All 'prop: value' pairs in CSS and inline-style strings (comments stripped)."""
    return re.findall(r'([a-zA-Z-]+)\s*:\s*([^;{}\n"\']+)', strip(src))


def font_families(src):
    fams = []
    for prop, val in css_declarations(src):
        if prop == 'font-family':
            fams += [x.strip().strip('"\'') for x in val.split(',')]
        elif prop == 'font':
            m = re.search(r'\d[\d.]*(?:px|em|rem|%|cqw)(?:\s*/\s*[\d.]+)?\s+(.+)$', val.strip())
            if m:
                fams += [x.strip().strip('"\'') for x in m.group(1).split(',')]
    for m in re.finditer(r'(?:fontFamily|font-family)\s*[=:]\s*["\']([^"\']+)["\']', src):
        fams += [x.strip().strip('"\'') for x in m.group(1).split(',')]
    return [f for f in fams if f]


def hex_to_rgb(h):
    h = h.lstrip('#')
    if len(h) in (3, 4):
        h = ''.join(c * 2 for c in h[:3])
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) in (6, 8) else None


# ------------------------------------------------------------------------------------------------ design.md
def _frontmatter(text):
    """Minimal YAML-lite reader for design.md (key: value, one level of indented maps/lists, inline {} / [])."""
    if not text.startswith('---'):
        return {}
    end = re.search(r'(?m)^---\s*$', text[3:])
    if not end:
        return {}
    fm, key = {}, None

    def scalar(v):
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            return v[1:-1].replace('\\"', '"')
        if v.startswith('[') and v.endswith(']'):
            return [scalar(x) for x in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', v[1:-1]) if x.strip()]
        if v.startswith('{') and v.endswith('}'):
            d = {}
            for part in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', v[1:-1]):
                if ':' in part:
                    k, x = part.split(':', 1); d[k.strip().strip('"\'')] = scalar(x)
            return d
        try:
            return float(v) if '.' in v else int(v)
        except ValueError:
            return v
    for raw in text[3:3 + end.start()].splitlines():
        line = re.sub(r'(?<!["\w])#(?![0-9a-fA-F]{3,8}\b).*$', '', raw).rstrip()
        if not line.strip():
            continue
        if line.startswith((' ', '\t')) and key is not None:
            s = line.strip()
            if s.startswith('- '):
                fm[key] = (fm[key] if isinstance(fm.get(key), list) else []) + [scalar(s[2:])]
            elif ':' in s:
                if not isinstance(fm.get(key), dict):
                    fm[key] = {}
                k, v = s.split(':', 1); fm[key][k.strip().strip('"\'')] = scalar(v)
            continue
        if ':' not in line:
            continue
        key, v = line.split(':', 1)
        key = key.strip().lower()
        fm[key] = scalar(v) if v.strip() else ''
    return fm


def load_design(path):
    """design.md → {'palette': {rgb tuple: name}, 'fonts': set, 'radii': [..], 'shadows': str, 'allow_alpha': bool,
    'justify_below': px, 'bans': [...]} or None."""
    if not path or not os.path.exists(path):
        return None
    fm = _frontmatter(_read(path))
    palette = {}
    for k, v in (fm.get('colors') or {}).items():
        if isinstance(v, str):
            m = re.match(r'#([0-9a-fA-F]{3,8})\b', v.strip())
            rgb = hex_to_rgb(m.group(0)) if m else None
            if rgb is None:
                m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', v)
                rgb = tuple(int(x) for x in m.groups()) if m else None
            if rgb:
                palette[rgb] = k
    fonts = set(str(f) for f in (fm.get('fonts') or []))
    for role, spec in (fm.get('type') or {}).items():
        if isinstance(spec, dict) and spec.get('family'):
            fonts.update(x.strip().strip('"\'') for x in str(spec['family']).split(','))
    scale = fm.get('scale') or {}
    return {'palette': palette, 'fonts': {f for f in fonts if f}, 'radii': fm.get('radii') or [], 'borders': fm.get('borders') or [],
            'shadows': str(fm.get('shadows', '')).lower(), 'allow_alpha': bool(fm.get('allow_alpha', True)),
            'justify_below': scale.get('justify_below', 16) if isinstance(scale, dict) else 16,
            'bans': fm.get('bans') or [], 'name': fm.get('name', os.path.basename(path))}


# ------------------------------------------------------------------------------------------------ gates
def gate_text_budget(ctx, files):
    cfg = dict(DEFAULTS['text']); cfg.update(ctx['qa'].get('text', {}))
    script = norm(ctx.get('script', ''))
    exempt = {norm(x) for x in cfg.get('exempt', [])}
    dbl, long_ = [], []
    for path, src in files:
        for s in rendered_strings(src, path.lower().endswith(('.html', '.htm'))):
            n = norm(s)
            if not n or n in exempt:
                continue
            nw = len(n.split())
            if nw >= cfg['double_print_words'] and n in script:
                dbl.append(s[:60])
            elif nw > cfg['long_string_words']:
                long_.append('%s (%d words)' % (s[:48], nw))
    detail = ('double-print %s' % dbl[:3]) if dbl else 'no narration sentence is rendered as text'
    if long_:
        detail += '  warn: long on-screen strings %s' % long_[:3]
    return not dbl, detail


def gate_pace(ctx):
    cfg = dict(DEFAULTS['pace']); cfg.update(ctx['qa'].get('pace', {}))
    ph = ctx.get('vo_phases')
    if not ph:
        return True, 'no vo/<name>_phases.json — skipped'
    name = ctx['cfg'].get('name', 'film')
    spec = os.path.join(ctx['project'], 'vo_script.py')
    if not os.path.exists(spec):
        return True, 'no vo_script.py — skipped'
    s = importlib.util.spec_from_file_location('vo_script_for_gate', spec)
    mod = importlib.util.module_from_spec(s); s.loader.exec_module(mod)
    texts = {p['name']: p['text'] for p in mod.SCENES[name]['phases']}
    durs = {p['name']: float(p['dur']) for p in ph['phases']}
    lo, hi = cfg['warn']
    fails, warns, tw, td = [], [], 0, 0.0
    for n, d in durs.items():
        nw = len(words(texts.get(n, '')))
        if not nw or d <= 0:
            continue
        r = nw / d; tw += nw; td += d
        if r > cfg['fail']:
            fails.append('%s %.1f w/s' % (n, r))
        elif not (lo <= r <= hi):
            warns.append('%s %.1f w/s' % (n, r))
        if nw > cfg['max_words']:
            warns.append('%s %d words' % (n, nw))
    detail = '%d words / %.1f s = %.2f w/s overall' % (tw, td, tw / max(td, 0.1))
    if fails:
        detail = 'too fast (> %.1f w/s): %s  ' % (cfg['fail'], fails[:4]) + detail
    if warns:
        detail += '  warn: %s' % warns[:4]
    return not fails, detail


def gate_brief(ctx, files):
    path = ctx['qa'].get('brief', 'BRIEF.md')
    path = path if os.path.isabs(path) else os.path.join(ctx['project'], path)
    if not os.path.exists(path):
        return True, 'no BRIEF.md — skipped (scaffold one from templates/BRIEF.example.md)'
    fm = _frontmatter(_read(path))
    msg = str(fm.get('message', '')).strip()
    if not msg:
        return False, 'BRIEF.md message is empty'
    said = norm(ctx.get('script', '')) + ' ' + ' '.join(norm(strip(src)) for _, src in files)
    cw = [w for w in norm(msg).split() if w not in STOP and len(w) > 2]
    hit = [w for w in cw if re.search(r'\b%s' % re.escape(w[:-1] if w.endswith('s') else w), said)]
    cov = len(hit) / max(1, len(cw))
    need = float(ctx['qa'].get('message_coverage', DEFAULTS['message_coverage']))
    probs = []
    if cov < need:
        probs.append('message words missing from the film: %s (%.0f %% < %.0f %%)' % ([w for w in cw if w not in hit][:6], cov * 100, need * 100))
    hl = str(fm.get('honesty_line', '')).strip()
    if hl and norm(hl) not in norm(ctx.get('script', '')):
        probs.append('honesty_line "%s" is not spoken' % hl[:40])
    return not probs, '; '.join(probs) if probs else 'message words %.0f %% present; "%s…"' % (cov * 100, msg[:50])


def gate_design(ctx, files):
    path = ctx['qa'].get('design', 'design.md')
    path = path if os.path.isabs(path) else os.path.join(ctx['project'], path)
    D = load_design(path)
    if not D:
        return True, 'no design.md — skipped (scaffold one from templates/design.example.md)'
    off, fonts_off, warns = [], [], []
    for p, src in files:
        s = strip(src)
        for m in re.finditer(r'(?<![0-9a-zA-Z])#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b', s):
            rgb = hex_to_rgb(m.group(0))
            if rgb and rgb not in D['palette']:
                off.append(m.group(0))
        for m in re.finditer(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)', s):
            rgb = tuple(int(x) for x in m.groups()[:3])
            if rgb not in D['palette']:
                off.append(m.group(0))
            elif m.group(4) is not None and not D['allow_alpha']:
                off.append(m.group(0))
        for fam in font_families(s):
            if fam.strip().startswith('var('):      # a skin token (var(--title-font)); the declared family is the token's value
                continue
            if fam.lower() not in GENERIC_FONTS and fam not in D['fonts']:
                fonts_off.append(fam)
        for prop, val in css_declarations(s):
            if prop == 'border-radius' and D['radii']:
                for r in re.findall(r'(\d+(?:\.\d+)?)px', val):
                    if float(r) not in [float(x) for x in D['radii']]:
                        warns.append('radius %spx' % r)
            if prop in ('box-shadow', 'text-shadow') and D['shadows'] in ('none', 'flat') and val.strip() != 'none':
                warns.append('%s on a flat spec' % prop)
            if prop in ('font-size', 'font'):
                for px in re.findall(r'(\d+(?:\.\d+)?)px', val):
                    if float(px) < float(D['justify_below']):
                        warns.append('%spx type' % px)
    off = sorted(set(off), key=off.index); fonts_off = sorted(set(fonts_off), key=fonts_off.index)
    probs = []
    if off:
        probs.append('off-palette colours %s' % off[:6])
    if fonts_off:
        probs.append('undeclared fonts %s' % fonts_off[:4])
    detail = '; '.join(probs) if probs else 'all colours and fonts declared in %s' % D['name']
    if warns:
        detail += '  warn: %s' % sorted(set(warns))[:5]
    return not probs, detail


def gate_lazy(ctx, files):
    rows = dict(LAZY)
    for k, v in ctx['qa'].get('css_patterns', {}).items():
        rows[k] = (v, re.I, 'any', 'project rule')
    fail_rows = set(ctx['qa'].get('css_fail', []))
    src_all = '\n'.join(strip(src) for _, src in files)
    found = []
    for name, (pat, flags, mode, why) in rows.items():
        hits = re.findall(pat, src_all, flags)
        if (mode == 'any' and hits) or (mode == 'count>2' and len(hits) > 2):
            found.append(name)
    banned = sorted({f for f in font_families(src_all) if f in BANNED_FONTS})
    if banned:
        found.append('banned-font(%s)' % ','.join(banned))
    floor = float(ctx['qa'].get('stage_min_px', DEFAULTS['stage_min_px']))
    tiny = sorted({px for prop, val in css_declarations(src_all) if prop in ('font-size', 'font')
                   for px in re.findall(r'(\d+(?:\.\d+)?)px', val) if float(px) < floor}, key=float)
    if tiny:
        found.append('tiny-type(%spx)' % ','.join(tiny[:3]))
    fails = [f for f in found if f.split('(')[0] in fail_rows]
    if not found:
        return True, 'no lazy defaults in the authored files'
    detail = ('FAIL rows %s  ' % fails if fails else '') + 'warn: %s' % [f for f in found if f not in fails]
    return not fails, detail.strip()


def run(ctx):
    files = authored_files(ctx)
    out = []
    for name, fn in zip(GATE_NAMES, (lambda: gate_text_budget(ctx, files), lambda: gate_pace(ctx),
                                     lambda: gate_brief(ctx, files), lambda: gate_design(ctx, files), lambda: gate_lazy(ctx, files))):
        try:
            ok, detail = fn()
        except Exception as e:                       # a broken gate is a failed gate
            ok, detail = False, 'gate crashed: %s: %s' % (type(e).__name__, str(e)[:120])
        out.append((name, ok, detail))
    return out


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    import tempfile, shutil
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = os.path.normpath(os.path.join(here, '..', 'templates'))
    ok = True

    def t(cond, label):
        nonlocal ok
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', label)); ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix='tg_')
    try:
        os.makedirs(os.path.join(tmp, 'scenes')); os.makedirs(os.path.join(tmp, 'vo'))
        shutil.copy(os.path.join(tpl, 'BRIEF.example.md'), os.path.join(tmp, 'BRIEF.md'))
        shutil.copy(os.path.join(tpl, 'design.example.md'), os.path.join(tmp, 'design.md'))
        script_phases = [('hook', 'Every Monday, the operations lead at Acme asks the same question. And every Monday, it takes a day to answer.', 8.0),
                         ('title', 'Acme is fictional, and so is its data. The workflow is the point.', 4.6),
                         ('nb', 'My notebook loads the orders, filters the late deliveries, and counts them by region.', 5.8),
                         ('ask', 'Which regions missed their on-time delivery target last week?', 3.6),
                         ('answer', 'I send the question, and the answer comes back from the same governed data. It takes a minute, and the team can trust it.', 9.2),
                         ('close', 'One notebook. One question. One answer the whole team can trust.', 4.8)]
        open(os.path.join(tmp, 'vo_script.py'), 'w', encoding='utf-8').write(
            'SCENES = {"film": {"phases": [' + ','.join('{"name": %r, "voice": "n", "text": %r}' % (n, x) for n, x, _ in script_phases) + ']}}\n')
        t0, ph = 0.1, []
        for n, _, d in script_phases:
            ph.append({'name': n, 'start': round(t0, 2), 'dur': d}); t0 += d + 0.55
        json.dump({'total': round(t0 - 0.45, 2), 'phases': ph}, open(os.path.join(tmp, 'vo', 'film_phases.json'), 'w'))
        script = ' '.join(x for _, x, _ in script_phases)
        clean_html = ('<!doctype html><html><head><style>'
                      'html,body{margin:0;background:#082A34;font-family:"Helvetica Neue",Arial,sans-serif}'
                      '#stage{background:#082A34}.card h1{font:400 64px/1.1 Georgia,serif;color:#E9F3F9}'
                      '.cap{font:600 13px/1 Arial;color:#81A9AB}.rule{background:#E56B5E;border-radius:4px}'
                      '.hl.box{border:2px solid #E56B5E;background:rgba(229,107,94,.08)}'
                      '</style></head><body><div id="stage"><div class="card"><h1 id="tTitle"></h1></div></div>'
                      '<script>const F={title:"Monday, answered.",caption:"Fictional company · synthetic data"};</script></body></html>')
        dirty_html = clean_html.replace('#stage{background:#082A34}', '#stage{background:linear-gradient(180deg,#082A34,#3C8FA8)}'
                                        ).replace('color:#E9F3F9', 'color:#fff').replace('Georgia,serif', 'Inter,sans-serif'
                                        ).replace('</script>', ';const G=(t)=>Math.sin(t*0.35);const L="And every Monday, it takes a day to answer.";</script>')
        shots = "(function(){window.FILM={closeLines:['One notebook.','One question.','One answer the whole team can trust.'],acts:[{label:'THE ANALYST',text:'Build it where the data is.'}]};})();"
        open(os.path.join(tmp, 'scenes', 'shots.js'), 'w', encoding='utf-8').write(shots)
        base = {'project': tmp, 'cfg': {'name': 'film'}, 'qa': {}, 'script': script, 'timeline': {}, 'dur': 36.0, 'fps': 30,
                'vo_phases': json.load(open(os.path.join(tmp, 'vo', 'film_phases.json')))}

        open(os.path.join(tmp, 'scenes', 'film.html'), 'w', encoding='utf-8').write(clean_html)
        res = {n: (okk, d) for n, okk, d in run(base)}
        for n, (okk, d) in res.items():
            print('      %-16s %s  %s' % (n, 'PASS' if okk else 'FAIL', d[:110]))
        t(all(okk for okk, _ in res.values()), 'clean synthetic project passes all five gates')

        open(os.path.join(tmp, 'scenes', 'film.html'), 'w', encoding='utf-8').write(dirty_html)
        res = {n: (okk, d) for n, okk, d in run(base)}
        for n, (okk, d) in res.items():
            print('      %-16s %s  %s' % (n, 'PASS' if okk else 'FAIL', d[:110]))
        t(not res['text budget'][0] and 'double-print' in res['text budget'][1], 'text budget: a narration sentence rendered as text fails')
        t(not res['design tokens'][0] and '#3C8FA8' in res['design tokens'][1] and 'Inter' in res['design tokens'][1],
          'design tokens: off-palette #3C8FA8 and an undeclared font fail (#fff and #204A56 pass: design.md declares paper + ground2)')
        t(res['lazy defaults'][0] and 'gradient-ground' in res['lazy defaults'][1] and 'banned-font' in res['lazy defaults'][1]
          and 'screensaver-drift' in res['lazy defaults'][1], 'lazy defaults: gradient ground, banned font, clock drift WARN by default')
        strict = dict(base); strict['qa'] = {'css_fail': ['gradient-ground', 'banned-font']}
        res2 = {n: (okk, d) for n, okk, d in run(strict)}
        t(not res2['lazy defaults'][0], 'lazy defaults: css_fail rows FAIL when the project opts in')

        fast = json.loads(json.dumps(base['vo_phases'])); fast['phases'][2]['dur'] = 3.0
        res3 = {n: (okk, d) for n, okk, d in run(dict(base, vo_phases=fast))}
        t(not res3['narration pace'][0] and 'nb' in res3['narration pace'][1], 'narration pace: 15 words in 3.0 s (5 w/s) fails')
        res4 = {n: (okk, d) for n, okk, d in run(dict(base, script='Nothing to do with the brief.'))}
        t(not res4['brief message'][0], 'brief message: a film that never says its message fails')
        nob = dict(base, project=tempfile.mkdtemp(prefix='tg_empty_'))
        res5 = {n: (okk, d) for n, okk, d in run(nob)}
        t(res5['brief message'][0] and res5['design tokens'][0] and res5['narration pace'][0], 'no BRIEF.md / design.md / vo_script.py → skipped, never a false FAIL')
        shutil.rmtree(nob['project'], ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\ntext_gate.py selftest: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(selftest() if '--selftest' in sys.argv else (print(__doc__) or 0))
