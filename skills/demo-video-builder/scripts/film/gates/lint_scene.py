# -*- coding: utf-8 -*-
"""lint_scene.py — static determinism / seekability / font / media / markup scan of frame(t) scenes.

A v3 film is one HTML scene whose only input is the clock t. Anything the seek cannot drive (a CSS
transition, Date.now(), a rAF outside the preview loop, Math.random()) silently makes the multi-worker
render differ chunk to chunk and makes stills lie. This scan runs in milliseconds and refuses the
exact classes of bug that only show up after a ten-minute render.

    python gates/lint_scene.py scenes/film.html [more.html ...] [--project .] [--profile v3|v2]
                               [--strict] [--json] [--verbose] [--selftest]

  exit 0  clean (or warnings only)        exit 1  errors (with --strict also warnings)        exit 2  usage

Every finding carries: code, severity (error | warning | info), file, line, message, hint. Findings are
deduplicated on (code, severity, file, line, message). Matches inside JS comments and string literals are
ignored (a displayed code snippet containing "Math.random" is inert). CSS comments are stripped before the
font scan (a "}" inside a comment would otherwise truncate an @font-face block).

Rule groups and ids (severity for the v3 profile; `--profile v2` downgrades the seekability rules to info
because v2 b-roll scenes use CSS transitions and __start() by design):

  determinism   non_deterministic_code (E)  wall_clock_scheduler (E)  fetch_mid_render (E)
                missing_render_contract (E)  seeded_random_helper (I)  scene_file_too_large (W > 300 lines)
  css           css_transition_present (E)  css_animation_present (E)  fullframe_overlay_starts_visible (E/I)
                missing_opaque_stage_background (E)  transform_set_twice (W)  layout_property_motion (W/I)
  media         video_or_audio_tag_in_scene (E)  img_loading_lazy (E)  media_preload_none (W)
                placeholder_media_url (E)  remote_ref (E)  base64_media (E audio/video, W image > 50 KB)
                crossorigin_attr (W)  img_without_decode (W)  imperative_media_control (E)
  fonts         font_family_unresolved (E: no @font-face, not on this machine, no resolvable fallback)
                font_family_system_only (W: renders from this machine's OS font — localize it)
                font_fallback_in_use (W: first choice missing here, a later family will render)
                font_face_local_only (I)  font_face_remote_src (E)
  markup        unbalanced_style_tags (E)  unbalanced_script_tags (E)  visible_markup_comment (E)
                unclosed_tag_swallowed_element (E)  self_closing_media_tag (E)  html_dir_attribute (E)
                root_css_zoom (E)  js_syntax_error (E)  negative_z_index (W)  id_starts_with_digit (W)
                stage_dimensions_mismatch (W)  css_brace_balance (W)
  perf          heavy_overlay_count (W >= 25)  large_image_asset (W: > 3840x4320, seq frames > 1920x1080)
  project       missing_local_asset (E)  shot_clip_unknown (E)  timing_total_mismatch (E)

QA gates (qa_film.py loads this module): GATE_NAMES = ['lint', 'text layout', 'contrast']
  lint          PASS when the scene, its lib/*.js and the project assets produce zero errors
                (qa.json "lint_strict": true also fails on warnings; "lint_profile": "v2" for b-roll scenes)
  text layout   tools/audit_text.js at the scene's own sample times: no text issue held >= 2 consecutive samples
  contrast      WCAG AA on every visible text block; warning-only unless qa.json "contrast": "error"
                (qa.json "audit_text": false skips both browser gates)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

MAX_SCENE_LINES = 300            # HyperFrames' composition-size datum: beyond this a scene is hard to review
HEAVY_OVERLAY_LIMIT = 25         # blur / backdrop-filter / radial-gradient / clip-path declarations
LARGE_IMAGE_W, LARGE_IMAGE_H = 3840, 4320      # 2x a 1080p delivery frame; taller stitched pages are legitimate
SEQ_FRAME_W, SEQ_FRAME_H = 1920, 1080
BASE64_IMAGE_WARN_BYTES = 50 * 1024
STAGE_W, STAGE_H = 1280, 720

GENERIC_FAMILIES = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif',
                    'ui-sans-serif', 'ui-monospace', 'ui-rounded', 'math', 'emoji', 'fangsong',
                    '-apple-system', 'blinkmacsystemfont', 'inherit', 'initial', 'unset', 'revert'}
PLACEHOLDER_HOSTS = ('placehold.co', 'placeholder.com', 'placekitten.com', 'picsum.photos', 'example.com',
                     'via.placeholder.com', 'dummyimage.com', 'loremflickr.com', 'placehold.it')

SEV_ORDER = {'error': 0, 'warning': 1, 'info': 2}


# ----------------------------------------------------------------------------------------------------- helpers
def _line_of(src, idx):
    return src.count('\n', 0, max(0, idx)) + 1


def strip_js_comments(src):
    """Blank out // and /* */ comments, keeping every newline (line numbers stay valid). String, template and
    regex literals are skipped so a '//' inside them is not mistaken for a comment."""
    out, i, n = [], 0, len(src)
    prev_sig = ''                                         # last significant char, decides regex vs division
    while i < n:
        c = src[i]
        if c in '\'"`':
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == '\\':
                    j += 1
                elif c == '`' and src[j] == '\n':
                    pass
                elif c != '`' and src[j] == '\n':
                    break
                j += 1
            out.append(src[i:j + 1]); i = j + 1; prev_sig = c
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i)); i = j
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r'[^\n]', ' ', src[i:j])); i = j
            continue
        if c == '/' and prev_sig in '(,=:[!&|?{};+-*%<>~^' or (c == '/' and prev_sig == ''):
            j = i + 1                                       # regex literal: skip to the closing slash
            in_class = False
            while j < n and src[j] != '\n':
                if src[j] == '\\':
                    j += 1
                elif src[j] == '[':
                    in_class = True
                elif src[j] == ']':
                    in_class = False
                elif src[j] == '/' and not in_class:
                    break
                j += 1
            out.append(src[i:j + 1]); i = j + 1; prev_sig = '/'
            continue
        out.append(c)
        if not c.isspace():
            prev_sig = c
        i += 1
    return ''.join(out)


def strip_js_strings(src):
    """Replace the contents of string / template literals with spaces (quotes stay, newlines stay)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in '\'"`':
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == '\\':
                    j += 1
                j += 1
            body = re.sub(r'[^\n]', ' ', src[i + 1:j])
            out.append(c + body + (src[j] if j < n else '')); i = j + 1
            continue
        out.append(c); i += 1
    return ''.join(out)


def strip_css_comments(css):
    return re.sub(r'/\*.*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), css, flags=re.S)


def _blocks(html, tag):
    """[(attrs, content, content_start_index)] for every <tag ...>...</tag>."""
    res = []
    for m in re.finditer(r'<%s\b([^>]*)>(.*?)</%s\s*>' % (tag, tag), html, flags=re.S | re.I):
        res.append((m.group(1), m.group(2), m.start(2)))
    return res


def _brace_block(src, start):
    """Index just past the '}' that closes the first '{' at/after start (-1 when unbalanced)."""
    i = src.find('{', start)
    if i < 0:
        return -1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return j + 1
    return -1


def split_font_families(value):
    """Top-level comma split honouring quotes and parentheses; returns bare family names (no quotes)."""
    parts, cur, depth, q = [], '', 0, None
    for ch in value:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in '\'"':
            q = ch; cur += ch
        elif ch == '(':
            depth += 1; cur += ch
        elif ch == ')':
            depth -= 1; cur += ch
        elif ch == ',' and depth == 0:
            parts.append(cur); cur = ''
        else:
            cur += ch
    parts.append(cur)
    out = []
    for p in parts:
        p = p.strip().rstrip(';').strip()
        if not p or p.startswith('var('):
            continue
        p = p.strip('\'"').strip()
        if p and p.lower().rstrip('!important').strip() not in GENERIC_FAMILIES:
            out.append(p)
    return out


def _font_shorthand_families(decl_value):
    """`font: 400 64px/1.1 Georgia, serif` → the family list after the size token."""
    m = re.search(r'(?:^|\s)[\d.]+(?:px|em|rem|%|pt|vw|vh)(?:\s*/\s*[\d.]+[a-z%]*)?\s+(.+)$', decl_value.strip())
    return split_font_families(m.group(1)) if m else []


# ---------------------------------------------------------------------------------------------- the linter
class Linter(object):
    def __init__(self, profile='v3', project=None, verbose=False):
        self.profile = profile
        self.project = os.path.abspath(project) if project else None
        self.verbose = verbose
        self.findings = []
        self._seen = set()

    # ---- emit
    def add(self, code, sev, file, line, message, hint, snippet=''):
        key = (code, sev, file, line, message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append({'code': code, 'severity': sev, 'file': file, 'line': line, 'message': message,
                              'hint': hint, 'snippet': snippet.strip()[:120]})

    def seek_sev(self, default):
        """v2 b-roll scenes use transitions and __start() by design: downgrade seekability rules to info."""
        return 'info' if self.profile == 'v2' else default

    # ---- entry points
    def lint_file(self, path):
        src = open(path, encoding='utf-8', errors='replace').read()
        rel = os.path.relpath(path, self.project) if self.project else os.path.basename(path)
        if path.lower().endswith(('.html', '.htm')):
            self.lint_html(src, rel, os.path.dirname(os.path.abspath(path)))
        else:
            self.lint_js(src, rel, scene=False)

    def lint_html(self, html, rel, base_dir):
        lines = html.count('\n') + 1
        if lines > MAX_SCENE_LINES:
            self.add('scene_file_too_large', 'warning', rel, 1,
                     '%d lines (> %d)' % (lines, MAX_SCENE_LINES),
                     'move shared helpers into lib/*.js; a scene should be a short frame(t) over the libraries')
        self._markup(html, rel)
        styles = _blocks(html, 'style')
        css_all = '\n'.join(strip_css_comments(c) for _, c, _ in styles)
        inline_styles = [(m.start(1), m.group(1)) for m in re.finditer(r'\sstyle\s*=\s*"([^"]*)"', html)]
        self._css_rules(html, rel, styles, inline_styles)
        self._media_markup(html, rel, base_dir)
        scripts = _blocks(html, 'script')
        inline_js = []
        for attrs, content, start in scripts:
            m = re.search(r'\bsrc\s*=\s*["\']([^"\']+)["\']', attrs)
            if m:
                src_path = m.group(1)
                if re.match(r'https?://', src_path):
                    self.add('remote_ref', 'error', rel, _line_of(html, start), '<script src> loads from the network: ' + src_path,
                             'copy the library into scenes/lib/ — a render must not depend on the network')
                else:
                    p = os.path.normpath(os.path.join(base_dir, src_path.split('?')[0]))
                    if not os.path.exists(p):
                        self.add('missing_local_asset', 'error', rel, _line_of(html, start), 'script not found: ' + src_path,
                                 'check the path relative to the scene file')
                continue
            if content.strip():
                inline_js.append((content, _line_of(html, start) - 1))
        joined = '\n'.join(c for c, _ in inline_js)
        self._render_contract(joined, rel)
        for content, line0 in inline_js:
            self.lint_js(content, rel, scene=True, line0=line0)
            self._js_syntax(content, rel, line0)
        self._fonts(html, rel, css_all, inline_styles, base_dir)
        self._transform_conflicts(css_all, joined, rel)
        self._perf(css_all, inline_styles, rel)

    # ---- JS rules (scene inline scripts and lib/*.js)
    def lint_js(self, js, rel, scene, line0=0):
        code = strip_js_strings(strip_js_comments(js))
        L = lambda idx: line0 + _line_of(code, idx)
        for pat, label in ((r'\bMath\.random\s*\(', 'Math.random()'), (r'\bDate\.now\s*\(', 'Date.now()'),
                           (r'\bnew\s+Date\s*\(\s*\)', 'new Date()'), (r'\bperformance\.now\s*\(', 'performance.now()'),
                           (r'\bcrypto\.getRandomValues\s*\(', 'crypto.getRandomValues()')):
            for m in re.finditer(pat, code):
                self.add('non_deterministic_code', 'error', rel, L(m.start()), label + ' makes frames depend on something other than t',
                         'derive every value from t; for noise use a seeded generator (see lib/vfx.js seeded noise) — new Date(fixedTimestamp) is fine')
        if re.search(r'\bfunction\s+(rnd|rand|seed\w*|mulberry32|lcg|xorshift\w*)\s*\(|\b(rnd|seeded\w*)\s*=\s*\(?\w*\)?\s*=>', code):
            self.add('seeded_random_helper', 'info', rel, line0 + 1, 'a seeded random helper is defined (fine: same seed, same frames)', '')
        for m in re.finditer(r'\b(fetch|XMLHttpRequest|WebSocket|navigator\.sendBeacon|importScripts)\s*\(', code):
            self.add('fetch_mid_render', 'error', rel, L(m.start()), m.group(1) + '() during a render is a race the frame cannot wait for',
                     'load every asset through <script src>, <img src> or the footage lane (decode Promises) before frame 0')
        allowed = self._preview_ranges(code) if scene else []
        for m in re.finditer(r'\b(setTimeout|setInterval|requestAnimationFrame)\s*\(', code):
            if any(a <= m.start() < b for a, b in allowed):
                continue
            self.add('wall_clock_scheduler', self.seek_sev('error'), rel, L(m.start()),
                     m.group(1) + ' runs on wall-clock time, not on the film clock',
                     'only the preview branch `if (!RENDER) { ... requestAnimationFrame(loop) }` may schedule; everything else is frame(t)')
        for m in re.finditer(r'\.(play|pause|load)\s*\(\s*\)|\.currentTime\s*=', code):
            self.add('imperative_media_control', 'error', rel, L(m.start()), 'imperative media control (%s) is not seekable' % m.group(0).strip(),
                     'use extracted JPEG frames via lib/footage.js (seq clips) — sound is mixed by build_film.py')
        for m in re.finditer(r'(\.src\s*=|\.setAttribute\s*\(\s*[\'"]src[\'"])[^;\n]*', code):
            stmt = code[m.start():m.end()]
            nxt = code[m.end():m.end() + 160]
            if 'decode(' not in stmt and 'decode(' not in nxt.split('}')[0]:
                self.add('img_without_decode', 'warning', rel, L(m.start()), 'an image src is set without awaiting img.decode()',
                         'push img.decode() into the pending list that __seek/__step return (lib/footage.js setSrc does this)')
        frame_body = self._function_body(code, 'frame')
        for m in re.finditer(r'\.style\.(width|height|top|left)\s*=', code):
            in_frame = frame_body and frame_body[0] <= m.start() < frame_body[1]
            sev = 'warning' if (in_frame and m.group(1) in ('width', 'height')) else 'info'
            self.add('layout_property_motion', sev, rel, L(m.start()), 'per-frame .style.%s assignment' % m.group(1),
                     'prefer transform: translate()/scale() for sub-pixel smooth motion (G.applyCam, rise); layout properties reflow')

    def _function_body(self, code, name):
        m = re.search(r'\bfunction\s+%s\s*\([^)]*\)\s*\{' % re.escape(name), code)
        if not m:
            return None
        end = _brace_block(code, m.end() - 1)
        return (m.start(), end if end > 0 else len(code))

    def _preview_ranges(self, code):
        """Regions where wall-clock scheduling is legitimate: the body of function loop() and `if (!RENDER)` blocks."""
        ranges = []
        fb = self._function_body(code, 'loop')
        if fb:
            ranges.append(fb)
        for m in re.finditer(r'\bif\s*\(\s*!\s*RENDER\s*\)', code):
            rest = code[m.end():]
            if re.match(r'\s*\{', rest):
                end = _brace_block(code, m.end())
                ranges.append((m.start(), end if end > 0 else len(code)))
            else:
                semi = code.find(';', m.end())
                ranges.append((m.start(), semi if semi > 0 else len(code)))
        return ranges

    def _render_contract(self, js, rel):
        if self.profile == 'v2':
            need = {'window.__start': r'window\.__start\s*=', '?render test': r'\[\?&\]render|[?&]render|location\.search'}
        else:
            need = {'window.__seek': r'window\.__seek\s*=', 'window.__step': r'window\.__step\s*=',
                    'window.__total': r'window\.__total\s*=', "body 'pre' class gate": r"classList\.(add|remove)\(\s*['\"]pre['\"]",
                    '?render test': r'\[\?&\]render|[?&]render'}
        miss = [k for k, p in need.items() if not re.search(p, js)]
        if miss:
            self.add('missing_render_contract', 'error', rel, 1, 'render contract incomplete: missing ' + ', '.join(miss),
                     'copy the contract block from film.example.html (RENDER flag, __seek/__step/__total, body.pre)')

    def _js_syntax(self, js, rel, line0):
        fd, tmp = tempfile.mkstemp(suffix='.js', prefix='lint_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(js)
            r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                m = re.search(r':(\d+)\n', r.stderr)
                line = line0 + (int(m.group(1)) if m else 1)
                msg = [l for l in r.stderr.splitlines() if l.startswith('SyntaxError')]
                self.add('js_syntax_error', 'error', rel, line, (msg[0] if msg else 'node --check failed'), 'fix the script; a parse error blanks the whole scene')
        except (OSError, subprocess.TimeoutExpired) as e:
            self.add('js_syntax_error', 'info', rel, line0 + 1, 'node --check skipped: %s' % type(e).__name__, 'install node to enable syntax checks')
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ---- CSS rules
    def _css_rules(self, html, rel, styles, inline_styles):
        for attrs, content, start in styles:
            css = strip_css_comments(content)
            L = lambda idx: _line_of(html, start + idx)
            for m in re.finditer(r'(?<![-\w])transition(?:-property|-duration)?\s*:\s*([^;}]+)', css):
                if m.group(1).strip().lower() not in ('none', '0s', 'none 0s'):
                    self.add('css_transition_present', self.seek_sev('error'), rel, L(m.start()), 'CSS transition is not seekable: ' + m.group(0).strip()[:60],
                             'drive the property from t with G.rmp / G.EZ / G.EIO / G.fadeInOut inside frame(t)')
            for m in re.finditer(r'(?<![-\w])animation(?:-name)?\s*:\s*([^;}]+)|@keyframes\b', css):
                if m.group(1) is None or m.group(1).strip().lower() != 'none':
                    self.add('css_animation_present', self.seek_sev('error'), rel, L(m.start()), 'CSS animation / @keyframes runs on wall-clock time',
                             'express the motion as a function of t (frame(t)); the renderer steps frames, it never waits')
            for m in re.finditer(r'(html|body|#stage)\s*(?:,\s*(?:html|body|#stage)\s*)*\{([^}]*)\}', css):
                body = m.group(2)
                z = re.search(r'(?<![-\w])zoom\s*:\s*([^;]+)', body)
                if z and z.group(1).strip() not in ('1', 'normal', '100%'):
                    self.add('root_css_zoom', 'error', rel, L(m.start()), 'CSS zoom on %s paints outside the 1280x720 capture' % m.group(1),
                             'scale with transform on an inner element; keep html/body/#stage at 1280x720')
                w = re.search(r'(?<![-\w])width\s*:\s*(\d+)px', body); h = re.search(r'(?<![-\w])height\s*:\s*(\d+)px', body)
                if (w and int(w.group(1)) != STAGE_W) or (h and int(h.group(1)) != STAGE_H):
                    self.add('stage_dimensions_mismatch', 'warning', rel, L(m.start()),
                             '%s is %sx%s, the renderer captures %dx%d' % (m.group(1), w.group(1) if w else '?', h.group(1) if h else '?', STAGE_W, STAGE_H),
                             'author at 1280x720 (DPR 1.5 → 1920x1080); render_frames.js clips to that stage')
            self._stage_background(css, rel, L)
            self._fullframe_overlays(css, html, rel, L)
            for m in re.finditer(r'z-index\s*:\s*-\d+', css):
                self.add('negative_z_index', 'warning', rel, L(m.start()), m.group(0) + ' hides the element behind an opaque root', 'stack with positive z-index inside #stage')
            opens, closes = css.count('{'), css.count('}')
            if opens != closes:
                self.add('css_brace_balance', 'warning', rel, L(0), 'unbalanced braces in <style> (%d { vs %d })' % (opens, closes), 'a stray brace silently drops every later rule')
        for idx, st in inline_styles:
            L = _line_of(html, idx)
            if re.search(r'(?<![-\w])transition\s*:\s*(?!none)', st):
                self.add('css_transition_present', self.seek_sev('error'), rel, L, 'inline transition is not seekable', 'drive it from t')
            if re.search(r'(?<![-\w])animation\s*:\s*(?!none)', st):
                self.add('css_animation_present', self.seek_sev('error'), rel, L, 'inline animation runs on wall-clock time', 'drive it from t')

    def _stage_background(self, css, rel, L):
        """White-flash hazard: the stage is hidden until the first seek (body.pre), so html/body must be opaque."""
        def opaque(body):
            m = re.search(r'(?<![-\w])background(?:-color)?\s*:\s*([^;}]+)', body)
            if not m:
                return False
            v = m.group(1).strip().lower()
            if v in ('none', 'transparent') or re.search(r'rgba?\([^)]*,\s*0(\.0+)?\s*\)$', v) or re.search(r'#[0-9a-f]{6}00\b', v):
                return False
            return True
        roots = {}
        for m in re.finditer(r'((?:html|body|#stage)(?:\s*,\s*(?:html|body|#stage))*)\s*\{([^}]*)\}', css):
            for sel in re.split(r'\s*,\s*', m.group(1)):
                roots[sel.strip()] = roots.get(sel.strip(), False) or opaque(m.group(2))
        if not (roots.get('html') or roots.get('body')):
            self.add('missing_opaque_stage_background', 'error', rel, L(0),
                     'html/body have no opaque background — pre-seek and seam frames flash white',
                     'add `html,body{background:#082A34}` (your darkest stage colour); #stage may layer a gradient on top')
        elif '#stage' in css and not roots.get('#stage') and not re.search(r'#stage\s*\{[^}]*background', css):
            self.add('missing_opaque_stage_background', 'warning', rel, L(0), '#stage has no background of its own (inherits body — fine if body is opaque)',
                     'give #stage an explicit background so a repositioned stage never shows the page behind it')

    def _fullframe_overlays(self, css, html, rel, L):
        """A full-frame element with a background whose authored opacity is not 0 covers frame 0 unless frame(t) drives it."""
        scripts = ' '.join(c for _, c, _ in _blocks(html, 'script'))
        for m in re.finditer(r'(#[\w-]+)\s*\{([^}]*)\}', css):
            sel, body = m.group(1), m.group(2)
            if sel == '#stage':
                continue
            full = re.search(r'(?<![-\w])inset\s*:\s*0', body) or (re.search(r'width\s*:\s*(100%%|%dpx)' % STAGE_W, body) and re.search(r'height\s*:\s*(100%%|%dpx)' % STAGE_H, body))
            if not full or not re.search(r'(?<![-\w])background', body) or re.search(r'display\s*:\s*none', body):
                continue
            op = re.search(r'(?<![-\w])opacity\s*:\s*([\d.]+)', body)
            if op and float(op.group(1)) == 0:
                continue
            driven = re.search(r"['\"#]%s['\"]|getElementById\(\s*['\"]%s['\"]" % (re.escape(sel[1:]), re.escape(sel[1:])), scripts)
            self.add('fullframe_overlay_starts_visible', 'info' if driven else self.seek_sev('error'), rel, L(m.start()),
                     '%s covers the whole frame with an opaque background and authored opacity %s' % (sel, op.group(1) if op else '1'),
                     'author `opacity:0` and let frame(t) raise it (op(el, G.rmp(...))) — a cover that starts visible is the "first second is black/white" bug')

    def _transform_conflicts(self, css_all, js, rel):
        static = {m.group(1) for m in re.finditer(r'(#[\w-]+)\s*\{[^}]*(?<![-\w])transform\s*:\s*(?!none)[^;}]+', css_all)}
        code = strip_js_strings(strip_js_comments(js))
        for sel in static:
            ident = re.escape(sel[1:])
            if re.search(r"(\$\(\s*'#%s'\s*\)|getElementById\(\s*'%s'\s*\)|\b%s\b)[^;\n]*\.style\.transform\s*=" % (ident, ident, ident), js) \
               or re.search(r"\b%s\.style\.transform\s*=" % ident, code):
                self.add('transform_set_twice', 'warning', rel, 1, '%s has a static CSS transform AND the script assigns .style.transform' % sel,
                         'the script owns the full transform (it overwrites the CSS one, losing e.g. translate(-50%)); move the static part into the script')

    # ---- media / markup
    def _media_markup(self, html, rel, base_dir):
        for m in re.finditer(r'<(video|audio)\b[^>]*>', html, flags=re.I):
            tag = m.group(0)
            if tag.rstrip().endswith('/>'):
                self.add('self_closing_media_tag', 'error', rel, _line_of(html, m.start()), '<%s/> is not self-closing in HTML: everything after it disappears' % m.group(1),
                         'remove the tag — v3 scenes draw extracted frames, sound is mixed by build_film.py')
            self.add('video_or_audio_tag_in_scene', self.seek_sev('error'), rel, _line_of(html, m.start()), '<%s> cannot be frame-stepped' % m.group(1),
                     'extract the motion with extract_clips.py (seq clip) and play it on the clock via lib/footage.js')
            if re.search(r'preload\s*=\s*["\']none', tag, re.I):
                self.add('media_preload_none', 'warning', rel, _line_of(html, m.start()), 'preload="none": the renderer cannot load the media', 'drop preload="none"')
        for m in re.finditer(r'<(img|video|audio|source|link|script|iframe)\b[^>]*>', html, flags=re.I):
            tag, line = m.group(0), _line_of(html, m.start())
            if re.search(r'loading\s*=\s*["\']lazy', tag, re.I):
                self.add('img_loading_lazy', 'error', rel, line, 'loading="lazy" images load only when shown — blank on first frames', 'remove loading="lazy"')
            if re.search(r'\scrossorigin\b', tag, re.I):
                self.add('crossorigin_attr', 'warning', rel, line, 'crossorigin on a file:// asset breaks the render', 'remove the crossorigin attribute')
            for a in re.finditer(r'\b(src|href)\s*=\s*["\']([^"\']+)["\']', tag, re.I):
                url = a.group(2).strip()
                if any(h in url.lower() for h in PLACEHOLDER_HOSTS):
                    self.add('placeholder_media_url', 'error', rel, line, 'placeholder URL will 404 at render: ' + url[:80], 'use a real local asset')
                elif re.match(r'https?://', url, re.I):
                    if re.search(r'fonts\.googleapis|fonts\.gstatic|\.woff2?\b|\.ttf\b|\.otf\b', url, re.I):
                        self.add('remote_ref', 'error', rel, line, 'remote font: ' + url[:80], 'run tools/fonts_localize.py — fonts must be local for a reproducible render')
                    elif 'icon' in tag.lower() and 'rel=' in tag.lower():
                        continue
                    else:
                        self.add('remote_ref', 'error', rel, line, 'remote asset: ' + url[:80], 'copy it into the project; a render must not depend on the network')
                elif url.lower().startswith('data:'):
                    self._base64(url, rel, line)
                elif url and not url.startswith('#') and not url.startswith('javascript:') and m.group(1).lower() in ('img', 'source', 'video', 'audio', 'link'):
                    p = os.path.normpath(os.path.join(base_dir, url.split('?')[0]))
                    if 'stylesheet' in tag.lower() or m.group(1).lower() != 'link':
                        if not os.path.exists(p):
                            self.add('missing_local_asset', 'error', rel, line, '%s not found: %s' % (m.group(1), url), 'check the path relative to the scene file')
        for m in re.finditer(r'url\(\s*["\']?(https?://[^"\')]+)', html, flags=re.I):
            self.add('remote_ref', 'error', rel, _line_of(html, m.start()), 'remote url() in CSS: ' + m.group(1)[:80], 'copy the asset into the project')
        for m in re.finditer(r'url\(\s*["\']?(data:[^"\')]{0,64})', html, flags=re.I):
            full = re.search(r'url\(\s*["\']?(data:[^"\')]+)', html[m.start():m.start() + 4_000_000])
            if full:
                self._base64(full.group(1), rel, _line_of(html, m.start()))

    def _base64(self, url, rel, line):
        kind = re.match(r'data:(\w+)/', url)
        kind = kind.group(1) if kind else ''
        payload = url.split(',', 1)[1] if ',' in url else ''
        size = len(payload) * 3 // 4
        uniq = len(set(payload[:4000]))
        if kind in ('audio', 'video'):
            self.add('base64_media', 'error', rel, line, 'base64 %s (%d KB) in the scene' % (kind, size // 1024), 'media is pre-extracted to broll/ and mixed by ffmpeg, never inlined')
        elif kind == 'image' and (size > BASE64_IMAGE_WARN_BYTES or (uniq < 15 and size > 1024)):
            self.add('base64_media', 'warning', rel, line, 'base64 image %d KB%s' % (size // 1024, ' (likely fabricated: < 15 unique chars)' if uniq < 15 else ''),
                     'save it as a file in broll/ or scenes/ and reference it by path')

    def _markup(self, html, rel):
        for tag in ('style', 'script'):
            o, c = len(re.findall(r'<%s\b' % tag, html, re.I)), len(re.findall(r'</%s\s*>' % tag, html, re.I))
            if o != c:
                self.add('unbalanced_%s_tags' % tag, 'error', rel, 1, '%d <%s> vs %d </%s>' % (o, tag, c, tag),
                         'an unclosed <%s> swallows the markup; an extra </%s> dumps its text on screen' % (tag, tag))
        if re.search(r'<html\b[^>]*\sdir\s*=', html, re.I):
            self.add('html_dir_attribute', 'error', rel, 1, '<html dir=...> previews fine but renders a black video', 'remove dir from <html>; set direction on an inner element')
        for m in re.finditer(r'\sid\s*=\s*["\'](\d[^"\']*)', html):
            self.add('id_starts_with_digit', 'warning', rel, _line_of(html, m.start()), 'id="%s" breaks querySelector("#...")' % m.group(1), 'start ids with a letter')
        # visible /* */ outside style/script/pre/code/textarea/template blocks and outside tags
        text = re.sub(r'<!--.*?-->', ' ', html, flags=re.S)
        text = re.sub(r'<(style|script|pre|code|textarea|template)\b[^>]*>.*?</\1\s*>', ' ', text, flags=re.S | re.I)
        no_tags = re.sub(r'<[^>]*>', ' ', text)
        for m in re.finditer(r'/\*', no_tags):
            self.add('visible_markup_comment', 'error', rel, 1, '"/* ... */" outside <style>/<script> renders as on-screen text', 'use <!-- --> in markup')
        for m in re.finditer(r'<[a-zA-Z][^>]*>', re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', ' ', html, flags=re.S | re.I)):
            inner = re.sub(r'(["\']).*?\1', '', m.group(0)[1:])
            if '<' in inner:
                self.add('unclosed_tag_swallowed_element', 'error', rel, _line_of(html, m.start()), 'a "<" inside an unclosed tag swallows the next element: ' + m.group(0)[:50],
                         'close the tag with ">"')

    # ---- fonts
    def _fonts(self, html, rel, css_all, inline_styles, base_dir):
        declared, local_only = set(), set()
        for m in re.finditer(r'@font-face\s*\{([^}]*)\}', css_all, flags=re.I):
            body = m.group(1)
            fam = re.search(r'font-family\s*:\s*([^;]+)', body)
            if fam:
                for f in split_font_families(fam.group(1)):
                    declared.add(f.lower())
                src = re.search(r'src\s*:\s*([^;]+)', body)
                if src and 'url(' not in src.group(1) and 'local(' in src.group(1):
                    local_only.add(fam.group(1).strip().strip('\'"'))
                if src and re.search(r'url\(\s*["\']?https?://', src.group(1)):
                    self.add('font_face_remote_src', 'error', rel, 1, '@font-face loads from the network', 'run tools/fonts_localize.py')
                if src:
                    for u in re.finditer(r'url\(\s*["\']?([^"\')]+)', src.group(1)):
                        if not re.match(r'(https?:|data:)', u.group(1)) and not os.path.exists(os.path.normpath(os.path.join(base_dir, u.group(1)))):
                            self.add('missing_local_asset', 'error', rel, 1, 'font file not found: ' + u.group(1), 'check the url() path relative to the scene')
        for m in re.finditer(r'fonts\.googleapis\.com/css2?\?[^"\')\s]*', html):
            for fam in re.findall(r'family=([^&:"\']+)', m.group(0)):
                declared.add(fam.replace('+', ' ').lower())
        for f in local_only:
            self.add('font_face_local_only', 'info', rel, 1, "@font-face for '%s' uses local() only — renders only where that OS font exists" % f,
                     'fine for OS fonts you may not redistribute; otherwise copy the file (tools/fonts_localize.py)')
        stacks = []
        for m in re.finditer(r'(?<![-\w])font-family\s*:\s*([^;}]+)', css_all):
            stacks.append((split_font_families(m.group(1)), _line_of(css_all, m.start())))
        for m in re.finditer(r'(?<![-\w])font\s*:\s*([^;}]+)', css_all):
            fams = _font_shorthand_families(m.group(1))
            if fams:
                stacks.append((fams, _line_of(css_all, m.start())))
        for idx, st in inline_styles:
            for m in re.finditer(r'(?<![-\w])font-family\s*:\s*([^;]+)', st):
                stacks.append((split_font_families(m.group(1)), _line_of(html, idx)))
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
            import fonts_localize as FL
            locate = lambda fam: bool(FL.locate_family(fam))
        except Exception:
            locate = None                       # tools/fonts_localize.py absent: OS fonts cannot be verified
        cache = {}
        def resolvable(fam):
            k = fam.lower()
            if k in declared:
                return 'declared'
            if locate is None:
                return 'unverified'
            if k not in cache:
                cache[k] = locate(fam)
            return 'system' if cache[k] else None
        reported = set()
        for fams, line in stacks:
            states = [(f, resolvable(f)) for f in fams]
            if not states:
                continue
            any_ok = any(s for _, s in states)
            for i, (f, s) in enumerate(states):
                if (f.lower(), s) in reported:
                    continue
                reported.add((f.lower(), s))
                if s == 'declared':
                    continue
                if s == 'unverified':
                    self.add('font_family_unverified', 'warning', rel, line, "'%s' has no @font-face and tools/fonts_localize.py is not available to check the OS fonts" % f,
                             'copy scripts/film/tools/ into the project, or declare the font with @font-face')
                elif s == 'system':
                    self.add('font_family_system_only', 'warning', rel, line, "'%s' has no @font-face; it renders from this machine's OS font" % f,
                             "python tools/fonts_localize.py scenes/film.html  (copies it to scenes/fonts/ + @font-face) or add src: local('%s')" % f)
                elif any_ok:
                    nxt = next((g for g, t in states[i + 1:] if t), None)
                    self.add('font_fallback_in_use', 'warning', rel, line, "'%s' is not on this machine — '%s' will render instead (metrics differ across machines)" % (f, nxt),
                             'put the font you actually see first in the stack, or localize it with tools/fonts_localize.py')
                else:
                    self.add('font_family_unresolved', 'error', rel, line, "'%s' has no @font-face and no file on this machine — Chrome falls back to a generic font" % f,
                             "add @font-face { src: url('fonts/X.woff2') } (tools/fonts_localize.py) or src: local('Exact Name')")

    # ---- perf
    def _perf(self, css_all, inline_styles, rel):
        pat = r'filter\s*:\s*[^;}]*blur|backdrop-filter\s*:|radial-gradient\(|clip-path\s*:'
        n = len(re.findall(pat, css_all)) + sum(len(re.findall(pat, st)) for _, st in inline_styles)
        if n >= HEAVY_OVERLAY_LIMIT:
            self.add('heavy_overlay_count', 'warning', rel, 1, '%d blur / backdrop-filter / radial-gradient / clip-path declarations (>= %d)' % (n, HEAVY_OVERLAY_LIMIT),
                     'HyperFrames measured ~40 such layers capturing solid black for half a render; flatten decorative layers into one image')

    # ---- project pass
    def lint_project(self):
        P = self.project
        if not P:
            return
        cfg = {}
        fj = os.path.join(P, 'film.json')
        if os.path.exists(fj):
            cfg = json.load(open(fj, encoding='utf-8'))
            for key in ('bed', 'sfx'):
                if cfg.get(key) and not os.path.exists(os.path.join(P, cfg[key])):
                    self.add('missing_local_asset', 'error', 'film.json', 1, '%s not found: %s' % (key, cfg[key]), 'fix the path or set it to null')
        name = cfg.get('name', 'film')
        clips = self._load_clips(os.path.join(P, 'broll', 'clips.js'))
        shots_js = os.path.join(P, 'scenes', 'shots.js')
        if os.path.exists(shots_js) and clips is not None:
            src = strip_js_comments(open(shots_js, encoding='utf-8').read())
            for m in re.finditer(r'\bclip\s*:\s*[\'"](\w+)[\'"]', src):
                if m.group(1) not in clips:
                    self.add('shot_clip_unknown', 'error', 'scenes/shots.js', _line_of(src, m.start()), "shot uses clip '%s' which is not in broll/clips.js" % m.group(1),
                             'add it to clips.json and run extract_clips.py')
        for cname, c in (clips or {}).items():
            d = os.path.join(P, 'broll', cname)
            need = []
            if c.get('kind') == 'still':
                need = ['f_001.jpg']
            elif c.get('kind') == 'seq':
                need = ['f_%03d.jpg' % k for k in range(1, int(c.get('frames', 1)) + 1)]
            elif c.get('kind') == 'page':
                need = ['page.jpg'] + (['chrome_%d.jpg' % k for k in range(len(c.get('offsets', [])))] if c.get('chrome') else [])
            missing = [f for f in need if not os.path.exists(os.path.join(d, f))]
            if missing:
                self.add('missing_local_asset', 'error', 'broll/%s' % cname, 1, '%d file(s) missing, e.g. %s' % (len(missing), missing[0]),
                         'python extract_clips.py %s' % cname)
            self._image_sizes(d, cname, c.get('kind'))
        tj, pj = os.path.join(P, 'scenes', 'timing_%s.js' % name), os.path.join(P, 'vo', '%s_phases.json' % name)
        if os.path.exists(tj) and os.path.exists(pj):
            m = re.search(r'"total"\s*:\s*([\d.]+)', open(tj, encoding='utf-8').read())
            tot_js = float(m.group(1)) if m else None
            tot_vo = float(json.load(open(pj, encoding='utf-8')).get('total', -1))
            if tot_js is None or abs(tot_js - tot_vo) > 0.001:
                self.add('timing_total_mismatch', 'error', 'scenes/timing_%s.js' % name, 1, 'timing total %s != vo total %.3f' % (tot_js, tot_vo),
                         'python gen_vo_multivoice.py regenerates both from the same narration')
        elif os.path.exists(pj) and not os.path.exists(tj):
            self.add('missing_local_asset', 'error', 'scenes/timing_%s.js' % name, 1, 'timing file missing', 'python gen_vo_multivoice.py')

    def _load_clips(self, path):
        if not os.path.exists(path):
            return None
        src = open(path, encoding='utf-8').read()
        m = re.search(r'window\.CLIPS\s*=\s*(\{.*\})\s*;?\s*$', src, flags=re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except ValueError:
            try:
                r = subprocess.run(['node', '-e', 'global.window=global;require(process.argv[1]);process.stdout.write(JSON.stringify(window.CLIPS))', os.path.abspath(path)],
                                   capture_output=True, text=True, timeout=20)
                return json.loads(r.stdout) if r.returncode == 0 else None
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return None

    def _image_sizes(self, d, cname, kind):
        try:
            from PIL import Image
        except ImportError:
            return
        if not os.path.isdir(d):
            return
        for f in sorted(os.listdir(d))[:400]:
            if not f.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            try:
                with Image.open(os.path.join(d, f)) as im:
                    w, h = im.size
            except Exception:
                continue
            if w > LARGE_IMAGE_W or h > LARGE_IMAGE_H:
                self.add('large_image_asset', 'warning', 'broll/%s/%s' % (cname, f), 1, '%dx%d exceeds %dx%d (decoded every frame)' % (w, h, LARGE_IMAGE_W, LARGE_IMAGE_H),
                         'trim the page band in clips.json (extract_clips.py) — larger than 2x delivery adds decode time, not detail')
            elif kind == 'seq' and (w > SEQ_FRAME_W or h > SEQ_FRAME_H):
                self.add('large_image_asset', 'warning', 'broll/%s/%s' % (cname, f), 1, 'seq frame %dx%d > %dx%d' % (w, h, SEQ_FRAME_W, SEQ_FRAME_H), 'extract seq frames at the recording size')
                break

    # ---- result
    def summary(self, strict=False):
        errs = [f for f in self.findings if f['severity'] == 'error']
        warns = [f for f in self.findings if f['severity'] == 'warning']
        ok = not errs and not (strict and warns)
        return {'ok': ok, 'errorCount': len(errs), 'warningCount': len(warns),
                'findings': sorted(self.findings, key=lambda f: (SEV_ORDER[f['severity']], f['file'], f['line']))}


def lint_paths(paths, project=None, profile='v3', strict=False, with_libs=True):
    """Lint scene files (+ the lib/*.js they load, + the project asset pass). Returns the summary dict."""
    L = Linter(profile=profile, project=project)
    for p in paths:
        if os.path.exists(p):
            L.lint_file(p)
        else:
            L.add('missing_local_asset', 'error', p, 1, 'file not found', '')
    if with_libs:
        seen = set()
        for p in paths:
            html = open(p, encoding='utf-8', errors='replace').read() if os.path.exists(p) else ''
            for m in re.finditer(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', html):
                jp = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(p)), m.group(1).split('?')[0]))
                if jp in seen or not os.path.exists(jp) or 'timing_' in os.path.basename(jp) or os.path.basename(jp) == 'clips.js':
                    continue
                seen.add(jp)
                L.lint_file(jp)
    L.lint_project()
    return L.summary(strict)


def print_report(rep, verbose=False):
    for f in rep['findings']:
        if f['severity'] == 'info' and not verbose:
            continue
        print('  %-7s %-34s %s:%d  %s' % (f['severity'].upper(), f['code'], f['file'], f['line'], f['message']))
        if f['hint']:
            print('          -> ' + f['hint'])
    print('lint: %d error(s), %d warning(s)%s' % (rep['errorCount'], rep['warningCount'], '' if rep['ok'] else '  -> FIX BEFORE RENDERING'))


# ------------------------------------------------------------------------------------------------ QA gates
GATE_NAMES = ['lint', 'text layout', 'contrast']


def audit_text(scene, project, end=None, contrast=True, timeout=300):
    """Run tools/audit_text.js (puppeteer) and return its JSON report; raises on a tool failure."""
    tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'audit_text.js')
    out = os.path.join(project, 'out', 'audit_text.json')
    cmd = ['node', tool, scene, '--out', out] + (['--contrast'] if contrast else []) + (['--end', '%.3f' % end] if end else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=project)
    if r.returncode not in (0, 1) or not os.path.exists(out):
        raise RuntimeError('audit_text.js failed (%s): %s' % (r.returncode, (r.stderr or r.stdout).strip()[-300:]))
    return json.load(open(out, encoding='utf-8'))


def run(ctx):
    q = ctx.get('qa') or {}
    scene = ctx.get('scene_html'); project = ctx.get('project') or '.'
    rep = lint_paths([scene], project=project, profile=q.get('lint_profile', 'v3'), strict=bool(q.get('lint_strict', False)))
    codes = sorted({f['code'] for f in rep['findings'] if f['severity'] == 'error'})
    wcodes = sorted({f['code'] for f in rep['findings'] if f['severity'] == 'warning'})
    detail = '%d errors, %d warnings' % (rep['errorCount'], rep['warningCount'])
    if codes:
        detail += ' | errors: ' + ', '.join(codes[:5])
    elif wcodes:
        detail += ' | warnings: ' + ', '.join(wcodes[:4])
    res = [('lint', rep['ok'], detail)]
    if q.get('audit_text', True) is False:
        return res + [('text layout', True, 'disabled in qa.json'), ('contrast', True, 'disabled in qa.json')]
    try:
        total = float((ctx.get('timeline') or {}).get('total', 0)) or None
        A = audit_text(scene, project, end=total, contrast=True)
    except Exception as e:                      # a broken gate is a failed gate
        return res + [('text layout', False, 'audit failed: %s' % str(e)[:140]), ('contrast', False, 'audit failed')]
    lay = [f for f in A['findings'] if f['code'] != 'low_contrast']
    con = [f for f in A['findings'] if f['code'] == 'low_contrast']
    lay_err = [f for f in lay if f['severity'] == 'error']
    if A.get('pageErrors'):
        res.append(('text layout', False, 'page error: ' + A['pageErrors'][0][:120]))
    elif lay_err:
        f = lay_err[0]
        res.append(('text layout', False, '%d held issue(s): %s %s t=%.2f — %s' % (len(lay_err), f['code'], f['selector'][:30], f['t'], f['detail'][:70])))
    else:
        res.append(('text layout', True, '%d samples clean%s' % (len(A['times']), ', %d transient' % len(lay) if lay else '')))
    strict_contrast = str(q.get('contrast', 'warning')).lower() == 'error'
    if con:
        f = con[0]
        res.append(('contrast', not strict_contrast, '%d below WCAG AA%s: %s %s:1 < %s:1 (try %s)%s' % (len(con), '' if strict_contrast else ' (warning; qa.json "contrast": "error" to fail)',
                    f['selector'][:28], f.get('ratio'), f.get('required'), f.get('suggested'), ' at t=%.2f' % f['t'])))
    else:
        res.append(('contrast', True, 'every text block >= 4.5:1 (3:1 large) at %d samples' % len(A['times'])))
    return res


# ------------------------------------------------------------------------------------------------ selftest
BAD_SNIPPET = r'''<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">
<style>
html,body{margin:0;width:1920px;height:1080px}
#stage{position:absolute;inset:0}
#cover{position:absolute;inset:0;background:#fff}
.fade{transition:opacity .3s}
.spin{animation:spin 2s infinite}
@keyframes spin{to{transform:rotate(360deg)}}
#cam{transform:translate(-50%,-50%)}
.t{font-family:"Nonexistent Family Zq"}
.u{font-family:'Helvetica Neue',Arial;z-index:-1}
</style></head>
<body><div id="stage"><div id="cover"></div><div id="cam"></div><div id="1st" class="t">x</div>
<img src="https://example.com/placeholder.png" loading="lazy">
<video src="clip.mp4" preload="none"/>
<p>/* visible */</p>
<div class="u" <span>swallowed</span>
</div>
<script>
const seed = Math.random();           // live
const t0 = Date.now(), now = performance.now(), d = new Date();
setTimeout(() => {}, 100);
fetch('/x');
document.querySelector('#cam').style.transform = 'scale(2)';
const v = document.querySelector('video'); v.play(); v.currentTime = 2;
const s = "Math.random() in a string is inert";   /* Date.now() in a comment is inert */
const img = new Image(); img.src = 'a.jpg';
function frame(t) { img.style.width = t + 'px'; }
</script></body></html>'''

GOOD_SNIPPET = r'''<!doctype html><html><head><meta charset="utf-8">
<style>
html,body{margin:0;background:#082A34;width:1280px;height:720px;font-family:Arial,sans-serif}
body.pre #stage{visibility:hidden}
#stage{position:absolute;inset:0;overflow:hidden;background:linear-gradient(180deg,#082A34,#204A56)}
#camera{position:absolute;inset:0;transform-origin:0 0;will-change:transform}
#black{position:absolute;inset:0;background:#05161C;opacity:0}
@font-face{font-family:'Acme Sans';src:local('Arial')}
.card h1{font:400 64px/1.1 'Acme Sans',Georgia,serif}
</style></head>
<body><div id="stage"><div id="camera"><img id="clipImg" alt=""></div><div id="black"></div></div>
<script>
'use strict';
const RENDER = /[?&]render/.test(location.search);
if (RENDER) document.body.classList.add('pre');
const img = document.getElementById('clipImg');
let pend = [];
function setSrc(src) { if (img.getAttribute('src') !== src) { img.setAttribute('src', src); pend.push(img.decode().catch(() => {})); } }
function frame(t) { pend = []; document.getElementById('camera').style.transform = 'scale(' + (1 + 0.01 * t).toFixed(4) + ')'; return pend.length ? Promise.all(pend) : undefined; }
let t0 = null;
function loop(now) { if (t0 === null) t0 = now; frame((now - t0) / 1000); requestAnimationFrame(loop); }
window.__seek = t => { document.body.classList.remove('pre'); return Promise.resolve(frame(t)).then(() => frame(t)); };
window.__step = t => frame(t);
window.__total = 10;
if (!RENDER) { requestAnimationFrame(loop); }
</script></body></html>'''

EXPECT_BAD = ['non_deterministic_code', 'wall_clock_scheduler', 'fetch_mid_render', 'missing_render_contract',
              'css_transition_present', 'css_animation_present', 'fullframe_overlay_starts_visible',
              'missing_opaque_stage_background', 'transform_set_twice', 'layout_property_motion',
              'video_or_audio_tag_in_scene', 'img_loading_lazy', 'media_preload_none', 'placeholder_media_url',
              'self_closing_media_tag', 'html_dir_attribute', 'visible_markup_comment', 'unclosed_tag_swallowed_element',
              'negative_z_index', 'id_starts_with_digit', 'stage_dimensions_mismatch', 'imperative_media_control',
              'img_without_decode', 'font_family_unresolved']


def selftest():
    d = tempfile.mkdtemp(prefix='lint_selftest_')
    bad, good = os.path.join(d, 'bad.html'), os.path.join(d, 'good.html')
    open(bad, 'w', encoding='utf-8').write(BAD_SNIPPET)
    open(good, 'w', encoding='utf-8').write(GOOD_SNIPPET)
    rb = lint_paths([bad], with_libs=False)
    rg = lint_paths([good], with_libs=False)
    got = {f['code'] for f in rb['findings']}
    missing = [c for c in EXPECT_BAD if c not in got]
    good_errs = [f['code'] for f in rg['findings'] if f['severity'] == 'error']
    # string / comment immunity: exactly four live non-deterministic calls in BAD (random, now, perf, new Date)
    nd = [f for f in rb['findings'] if f['code'] == 'non_deterministic_code']
    print('selftest  bad.html : %d findings, %d errors, codes fired %d/%d' % (len(rb['findings']), rb['errorCount'], len(EXPECT_BAD) - len(missing), len(EXPECT_BAD)))
    print('selftest  good.html: %d findings, %d errors %s' % (len(rg['findings']), rg['errorCount'], good_errs or ''))
    print('selftest  non_deterministic_code live hits: %d (expect 4; string + comment ignored)' % len(nd))
    ok = not missing and not good_errs and len(nd) == 4 and not rb['ok'] and rg['ok']
    if missing:
        print('selftest  MISSING on bad.html: ' + ', '.join(missing))
    print('selftest  ' + ('PASS' if ok else 'FAIL'))
    return ok


def main(argv):
    if '--selftest' in argv:
        return 0 if selftest() else 1
    args = [a for a in argv if not a.startswith('--')]
    opts = [a for a in argv if a.startswith('--')]
    project = None
    for i, a in enumerate(argv):
        if a == '--project' and i + 1 < len(argv):
            project = argv[i + 1]; args = [x for x in args if x != project]
        if a == '--profile' and i + 1 < len(argv):
            args = [x for x in args if x != argv[i + 1]]
    profile = argv[argv.index('--profile') + 1] if '--profile' in argv else 'v3'
    if not args:
        print(__doc__.split('\n\n')[1]); return 2
    strict = '--strict' in opts
    rep = lint_paths(args, project=project, profile=profile, strict=strict)
    if '--json' in opts:
        print(json.dumps(rep, indent=1))
    else:
        print_report(rep, verbose='--verbose' in opts)
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main(sys.argv[1:]))
