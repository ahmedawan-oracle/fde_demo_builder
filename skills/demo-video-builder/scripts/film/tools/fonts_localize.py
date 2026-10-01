# -*- coding: utf-8 -*-
"""fonts_localize.py — make a scene's fonts part of the project so the render is reproducible on any machine.

    python tools/fonts_localize.py scenes/film.html [--out scenes/fonts] [--css fonts.css] [--local]
                                   [--dry-run] [--offline] [--json] [--selftest]

What it does
  1. Collects every font-family (and `font:` shorthand) from <style> blocks and inline styles — CSS comments
     stripped first, var(--x) tokens skipped, generic families ignored (serif, sans-serif, system-ui, ...).
  2. For each family without an @font-face: locates it in the OS font folders (Windows: %WINDIR%/Fonts and
     %LOCALAPPDATA%/Microsoft/Windows/Fonts; macOS: /Library/Fonts, /System/Library/Fonts(+/Supplemental),
     ~/Library/Fonts; Linux: ~/.fonts, ~/.local/share/fonts, /usr/share/fonts — depth <= 2). The family name is
     read from the font's own name table (PIL/FreeType); the file name is only a fallback.
  3. Picks the regular weight first, then the other weights/italics the scene asks for; file types are preferred
     woff2 > otf > ttf > woff > ttc; a family whose chosen files exceed 5 MB is skipped with a warning.
  4. Copies the files to scenes/fonts/ and writes scenes/fonts.css with one @font-face per variant
     (font-family, src: url('fonts/X.ttf') format('truetype'), font-weight, font-style), then inserts
     `<link rel="stylesheet" href="fonts.css">` after the last <style> in the scene (idempotent).
  5. Remote fonts (Google Fonts <link>, @font-face src:url(https://...)) are downloaded into the same folder
     and rewritten to local files (skip with --offline).

`--local` writes `src: local('Exact Name')` @font-face rules instead of copying files: the escape hatch for OS
fonts you may not redistribute (Segoe UI, Helvetica Neue, ...). Files are only ever written into YOUR project —
never commit proprietary font files to a public repository; the shipped example uses OS fonts via local().

Public API (imported by gates/lint_scene.py and tools/doctor.py):
  locate_family(name) -> [ {path, family, style, weight, italic, ext, size} ]   (empty list when not found)
  scan_scene(html)    -> {'stacks': [[families...]], 'declared': set, 'remote_links': [...], 'remote_faces': [...]}
  localize(scene_path, out_dir='scenes/fonts', css_name='fonts.css', local=False, dry_run=False, offline=False)
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time

FAMILY_SIZE_CAP = 5 * 1024 * 1024          # per family; bigger font sets are skipped with a warning
EXT_PREF = {'.woff2': 0, '.otf': 1, '.ttf': 2, '.woff': 3, '.ttc': 4}
FORMAT_OF = {'.woff2': 'woff2', '.woff': 'woff', '.ttf': 'truetype', '.otf': 'opentype', '.ttc': 'collection'}
WEIGHT_TOKENS = [('ultrablack', 950), ('extrablack', 950), ('ultrabold', 800), ('extrabold', 800), ('heavy', 800),
                 ('semibold', 600), ('demibold', 600), ('demi', 600), ('medium', 500), ('regular', 400), ('normal', 400),
                 ('book', 400), ('roman', 400), ('light', 300), ('ultralight', 200), ('extralight', 200), ('thin', 100),
                 ('hairline', 100), ('black', 900), ('bold', 700)]
GENERIC_FAMILIES = {'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-serif', 'ui-sans-serif',
                    'ui-monospace', 'ui-rounded', 'math', 'emoji', 'fangsong', '-apple-system', 'blinkmacsystemfont',
                    'inherit', 'initial', 'unset', 'revert'}
# families whose files must not be redistributed in a public repo (warn; suggest --local)
RESTRICTED_HINT = {'segoe ui', 'helvetica neue', 'helvetica', 'arial', 'georgia', 'calibri', 'cambria', 'times new roman',
                   'verdana', 'tahoma', 'sf pro', 'sf pro text', 'sf pro display', 'consolas', 'trebuchet ms', 'candara', 'corbel'}
MAGIC = (b'wOFF', b'wOF2', b'OTTO', b'\x00\x01\x00\x00', b'true', b'ttcf')


# --------------------------------------------------------------------------------------------- CSS parsing
def strip_css_comments(css):
    return re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)


def split_families(value):
    """Top-level comma split honouring quotes/parens; drops var(), generics and CSS-wide keywords."""
    parts, cur, depth, q = [], '', 0, None
    for ch in value:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in '\'"':
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
        p = re.sub(r'!important', '', p).strip().rstrip(';').strip()
        if not p or p.startswith('var('):
            continue
        p = p.strip('\'"').strip()
        if p and p.lower() not in GENERIC_FAMILIES:
            out.append(p)
    return out


def _shorthand_families(v):
    m = re.search(r'(?:^|\s)[\d.]+(?:px|em|rem|%|pt|vw|vh)(?:\s*/\s*[\d.]+[a-z%]*)?\s+(.+)$', v.strip())
    return split_families(m.group(1)) if m else []


def _weight_of(tokens):
    for tok, w in WEIGHT_TOKENS:
        if tok in tokens:
            return w
    return 400


def scan_scene(html):
    """Families used, families declared by @font-face / Google Fonts, and the remote sources to localize.
    Also returns the (weight, italic) variants each family is used with, so only needed files are copied."""
    css = '\n'.join(strip_css_comments(m.group(1)) for m in re.finditer(r'<style\b[^>]*>(.*?)</style\s*>', html, flags=re.S | re.I))
    inline = ' '.join(m.group(1) for m in re.finditer(r'\sstyle\s*=\s*"([^"]*)"', html))
    stacks, variants = [], {}
    for m in re.finditer(r'(?<![-\w])font-family\s*:\s*([^;}]+)', css + '\n' + inline):
        fams = split_families(m.group(1))
        if fams:
            stacks.append(fams)
    for m in re.finditer(r'(?<![-\w])font\s*:\s*([^;}]+)', css + '\n' + inline):
        fams = _shorthand_families(m.group(1))
        if fams:
            stacks.append(fams)
            toks = m.group(1).lower()
            w = re.search(r'\b([1-9]00)\b', toks)
            weight = int(w.group(1)) if w else _weight_of(toks)
            variants.setdefault(fams[0].lower(), set()).add((weight, 'italic' in toks or 'oblique' in toks))
    # weights declared in rules that also name a family (same rule block) — approximate: block-level scan
    for m in re.finditer(r'\{([^}]*)\}', css):
        body = m.group(1)
        fam = re.search(r'(?<![-\w])font-family\s*:\s*([^;]+)', body)
        if not fam:
            continue
        fams = split_families(fam.group(1))
        if not fams:
            continue
        w = re.search(r'font-weight\s*:\s*(\w+)', body)
        weight = 400
        if w:
            weight = int(w.group(1)) if w.group(1).isdigit() else _weight_of(w.group(1).lower())
        italic = bool(re.search(r'font-style\s*:\s*(italic|oblique)', body))
        variants.setdefault(fams[0].lower(), set()).add((weight, italic))
    declared, remote_faces = set(), []
    for m in re.finditer(r'@font-face\s*\{([^}]*)\}', css, flags=re.I):
        fam = re.search(r'font-family\s*:\s*([^;]+)', m.group(1))
        if fam:
            for f in split_families(fam.group(1)):
                declared.add(f.lower())
        src = re.search(r'src\s*:\s*([^;]+)', m.group(1))
        if src:
            for u in re.finditer(r'url\(\s*["\']?(https?://[^"\')]+)', src.group(1)):
                remote_faces.append({'family': split_families(fam.group(1))[0] if fam else '?', 'url': u.group(1), 'block': m.group(0)})
    remote_links = []
    for m in re.finditer(r'<link\b[^>]*href\s*=\s*["\']([^"\']*fonts\.googleapis\.com[^"\']*)["\'][^>]*>', html, flags=re.I):
        remote_links.append({'tag': m.group(0), 'url': m.group(1).replace('&amp;', '&')})
        for fam in re.findall(r'family=([^&:"\']+)', m.group(1)):
            declared.add(fam.replace('+', ' ').lower())
    for m in re.finditer(r'@import\s+url\(\s*["\']?([^"\')]*fonts\.googleapis\.com[^"\')]*)', css):
        remote_links.append({'tag': m.group(0), 'url': m.group(1)})
    return {'stacks': stacks, 'declared': declared, 'remote_links': remote_links, 'remote_faces': remote_faces, 'variants': variants}


# ------------------------------------------------------------------------------------------- OS font index
def font_dirs():
    dirs = []
    if sys.platform.startswith('win'):
        dirs += [os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts')]
    elif sys.platform == 'darwin':
        dirs += ['/Library/Fonts', '/System/Library/Fonts', '/System/Library/Fonts/Supplemental', os.path.expanduser('~/Library/Fonts')]
    else:
        dirs += [os.path.expanduser('~/.fonts'), os.path.expanduser('~/.local/share/fonts'), '/usr/share/fonts', '/usr/local/share/fonts']
    return [d for d in dirs if d and os.path.isdir(d)]


def _valid_font(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) in MAGIC
    except OSError:
        return False


def _name_from_file(stem):
    """Fallback when the name table is unreadable: split camelCase/_/-, strip style suffixes."""
    toks = re.sub(r'([a-z])([A-Z])', r'\1 \2', stem).replace('_', ' ').replace('-', ' ').split()
    style = [t for t in toks if t.lower() in dict(WEIGHT_TOKENS) or t.lower() in ('italic', 'oblique', 'condensed', 'narrow', 'it')]
    fam = ' '.join(t for t in toks if t not in style) or stem
    low = ' '.join(style).lower()
    return fam, ' '.join(style) or 'Regular', _weight_of(low), 'italic' in low or 'oblique' in low or ' it' in ' ' + low


def _read_names(path):
    """(family, style) via FreeType; the first face of a collection."""
    from PIL import ImageFont
    f = ImageFont.truetype(path, 12)
    fam, style = f.getname()
    return fam or '', style or 'Regular'


_INDEX = None


def font_index(refresh=False):
    """[{path, family, style, weight, italic, ext, size}] for every font file in the OS dirs (depth <= 2), cached
    on disk for a day (the index is keyed by path+mtime so a new font is picked up on the next refresh)."""
    global _INDEX
    if _INDEX is not None and not refresh:
        return _INDEX
    cache = os.path.join(tempfile.gettempdir(), 'fde_font_index.json')
    files = []
    for d in font_dirs():
        for root, subdirs, names in os.walk(d):
            if root[len(d):].count(os.sep) >= 2:
                subdirs[:] = []
            for n in names:
                if os.path.splitext(n)[1].lower() in EXT_PREF:
                    p = os.path.join(root, n)
                    try:
                        files.append((p, int(os.path.getmtime(p)), os.path.getsize(p)))
                    except OSError:
                        pass
    key = hashlib.sha1(repr(sorted(files)).encode()).hexdigest()
    if not refresh and os.path.exists(cache):
        try:
            c = json.load(open(cache, encoding='utf-8'))
            if c.get('key') == key and time.time() - c.get('ts', 0) < 86400:
                _INDEX = c['fonts']
                return _INDEX
        except (ValueError, OSError):
            pass
    out = []
    for p, _, size in files:
        if not _valid_font(p):
            continue
        stem = os.path.splitext(os.path.basename(p))[0]
        try:
            fam, style = _read_names(p)
            low = style.lower()
            weight, italic = _weight_of(low), ('italic' in low or 'oblique' in low)
        except Exception:
            fam, style, weight, italic = _name_from_file(stem)
        out.append({'path': p.replace('\\', '/'), 'family': fam, 'style': style, 'weight': weight, 'italic': italic,
                    'ext': os.path.splitext(p)[1].lower(), 'size': size})
    _INDEX = out
    try:
        json.dump({'key': key, 'ts': time.time(), 'fonts': out}, open(cache, 'w', encoding='utf-8'))
    except OSError:
        pass
    return out


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def locate_family(name):
    """Every installed variant of `name` (exact family match on the name table; file-name fallback), sorted
    regular-first then by file type preference. [] when the family is not on this machine."""
    want = _norm(name)
    if not want:
        return []
    hits = [f for f in font_index() if _norm(f['family']) == want]
    if not hits:   # file-name fallback for fonts whose name table differs (e.g. 'Arial' files named arialbd)
        for f in font_index():
            stem = _norm(os.path.splitext(os.path.basename(f['path']))[0])
            if stem == want or (stem.startswith(want) and stem[len(want):] in ('b', 'bd', 'i', 'z', 'bi', 'l', 'li', 'sb', 'sl', 'bl', 'r', 'regular', 'bold', 'italic')):
                hits.append(f)
    hits.sort(key=lambda f: (0 if (f['weight'] == 400 and not f['italic']) else 1, abs(f['weight'] - 400), f['italic'], EXT_PREF.get(f['ext'], 9)))
    return hits


def pick_variants(hits, wanted):
    """Choose one file per (weight, italic) the scene uses (always include regular); nearest weight wins."""
    wanted = set(wanted or []) | {(400, False)}
    chosen = {}
    for w, it in wanted:
        cands = [h for h in hits if h['italic'] == it] or hits
        best = min(cands, key=lambda h: (abs(h['weight'] - w), EXT_PREF.get(h['ext'], 9)))
        chosen[best['path']] = best
    return list(chosen.values())


# ----------------------------------------------------------------------------------------------- localize
def _download(url, dest):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    if dest:
        open(dest, 'wb').write(data)
    return data


def _safe_name(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)


def localize(scene_path, out_dir=None, css_name='fonts.css', local=False, dry_run=False, offline=False):
    """Localize every font the scene uses. Returns a report dict; writes fonts + fonts.css + the <link> unless dry_run."""
    scene_path = os.path.abspath(scene_path)
    scene_dir = os.path.dirname(scene_path)
    out_dir = os.path.abspath(out_dir or os.path.join(scene_dir, 'fonts'))
    rel_out = os.path.relpath(out_dir, scene_dir).replace('\\', '/')
    html = open(scene_path, encoding='utf-8').read()
    info = scan_scene(html)
    faces, actions, warnings, unresolved = [], [], [], []
    seen = set()
    for stack in info['stacks']:
        for fam in stack:
            k = fam.lower()
            if k in seen or k in info['declared']:
                continue
            seen.add(k)
            hits = locate_family(fam)
            if not hits:
                unresolved.append(fam)
                nxt = next((g for g in stack[stack.index(fam) + 1:] if locate_family(g) or g.lower() in info['declared']), None)
                warnings.append("'%s' is not on this machine%s" % (fam, (" — '%s' renders instead; put it first or install the font" % nxt) if nxt else ' and nothing in its stack is: Chrome will use a generic font'))
                continue
            if local:
                names = sorted({h['family'] for h in hits} | {fam})
                faces.append("@font-face{font-family:'%s';src:%s}" % (fam, ','.join("local('%s')" % n for n in names)))
                actions.append("%s -> local('%s') (no file copied)" % (fam, fam))
                continue
            chosen = pick_variants(hits, info['variants'].get(k))
            total = sum(h['size'] for h in chosen)
            if total > FAMILY_SIZE_CAP:
                warnings.append("'%s' skipped: %.1f MB of files exceeds the %d MB per-family cap (use --local)" % (fam, total / 1e6, FAMILY_SIZE_CAP // (1024 * 1024)))
                continue
            if k in RESTRICTED_HINT:
                warnings.append("'%s' is an OS font with a restrictive licence: keep the copied files out of public repos, or use --local" % fam)
            for h in chosen:
                fn = _safe_name(os.path.basename(h['path']))
                dest = os.path.join(out_dir, fn)
                if not dry_run:
                    os.makedirs(out_dir, exist_ok=True)
                    if not os.path.exists(dest):
                        shutil.copy2(h['path'], dest)
                faces.append("@font-face{font-family:'%s';src:url('%s/%s') format('%s');font-weight:%d;font-style:%s}"
                             % (fam, rel_out, fn, FORMAT_OF.get(h['ext'], 'truetype'), h['weight'], 'italic' if h['italic'] else 'normal'))
                actions.append('%s %s -> %s/%s (%d KB)' % (fam, h['style'], rel_out, fn, h['size'] // 1024))
    new_html = html
    if not offline:
        for link in info['remote_links']:
            try:
                css = _download(link['url'], None).decode('utf-8', 'replace')
            except Exception as e:
                warnings.append('could not fetch %s (%s) — leaving the <link>' % (link['url'][:60], type(e).__name__))
                continue
            for m in re.finditer(r'@font-face\s*\{([^}]*)\}', css):
                body = m.group(1)
                fam = re.search(r'font-family\s*:\s*([^;]+)', body); url = re.search(r'url\(\s*["\']?([^"\')]+)', body)
                if not (fam and url):
                    continue
                w = re.search(r'font-weight\s*:\s*(\d+)', body); it = re.search(r'font-style\s*:\s*(\w+)', body)
                ext = os.path.splitext(url.group(1).split('?')[0])[1] or '.woff2'
                fn = _safe_name('%s-%s-%s%s' % (fam.group(1).strip().strip('\'"'), w.group(1) if w else '400', it.group(1) if it else 'normal', ext))
                if not dry_run:
                    os.makedirs(out_dir, exist_ok=True)
                    try:
                        _download(url.group(1), os.path.join(out_dir, fn))
                    except Exception as e:
                        warnings.append('download failed %s (%s)' % (url.group(1)[:60], type(e).__name__)); continue
                faces.append("@font-face{font-family:%s;src:url('%s/%s') format('%s');font-weight:%s;font-style:%s}"
                             % (fam.group(1).strip(), rel_out, fn, FORMAT_OF.get(ext, 'woff2'), w.group(1) if w else '400', it.group(1) if it else 'normal'))
                actions.append('%s (remote) -> %s/%s' % (fam.group(1).strip(), rel_out, fn))
            new_html = new_html.replace(link['tag'], '<!-- fonts localized: ' + link['url'][:60] + ' -->' if link['tag'].startswith('<link') else '')
        for face in info['remote_faces']:
            ext = os.path.splitext(face['url'].split('?')[0])[1] or '.woff2'
            fn = _safe_name(face['family'] + ext)
            try:
                if not dry_run:
                    os.makedirs(out_dir, exist_ok=True); _download(face['url'], os.path.join(out_dir, fn))
                new_html = new_html.replace(face['url'], '%s/%s' % (rel_out, fn))
                actions.append('%s (remote @font-face) -> %s/%s' % (face['family'], rel_out, fn))
            except Exception as e:
                warnings.append('download failed %s (%s)' % (face['url'][:60], type(e).__name__))
    css_path = os.path.join(scene_dir, css_name)
    link_tag = '<link rel="stylesheet" href="%s">' % css_name
    if faces and link_tag not in new_html:
        i = new_html.lower().rfind('</style>')
        new_html = (new_html[:i + 8] + '\n' + link_tag + new_html[i + 8:]) if i >= 0 else new_html.replace('</head>', link_tag + '\n</head>', 1)
    if not dry_run:
        if faces:
            open(css_path, 'w', encoding='utf-8').write('/* generated by tools/fonts_localize.py — local fonts for a reproducible render */\n' + '\n'.join(faces) + '\n')
        if new_html != html:
            open(scene_path, 'w', encoding='utf-8').write(new_html)
    return {'ok': not unresolved, 'faces': faces, 'actions': actions, 'warnings': warnings, 'unresolved': unresolved,
            'css': css_path if faces else None, 'dry_run': dry_run}


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    ok = True
    fams = split_families("var(--f), 'Helvetica Neue', Arial, \"Noto Sans\", sans-serif, inherit")
    print('selftest  split: %s' % fams)
    ok &= fams == ['Helvetica Neue', 'Arial', 'Noto Sans']
    probe = 'Arial' if sys.platform.startswith('win') else ('Helvetica' if sys.platform == 'darwin' else 'DejaVu Sans')
    t0 = time.time(); hits = locate_family(probe); dt = time.time() - t0
    print('selftest  locate(%s): %d variants in %.1fs, first %s' % (probe, len(hits), dt, hits[0]['path'] if hits else None))
    ok &= bool(hits) and hits[0]['weight'] == 400 and not hits[0]['italic']
    print('selftest  locate(No Such Family Zq): %s' % locate_family('No Such Family Zq'))
    ok &= locate_family('No Such Family Zq') == []
    d = tempfile.mkdtemp(prefix='fonts_selftest_')
    scene = os.path.join(d, 'scene.html')
    open(scene, 'w', encoding='utf-8').write('<html><head><style>body{font-family:%s,sans-serif}.h{font:700 40px/1 %s}</style></head><body></body></html>' % (probe, probe))
    rep = localize(scene, out_dir=os.path.join(d, 'fonts'), dry_run=False, offline=True)
    html = open(scene, encoding='utf-8').read()
    print('selftest  localize: %d faces, %d files copied, link inserted %s' % (len(rep['faces']), len(os.listdir(os.path.join(d, 'fonts'))) if os.path.isdir(os.path.join(d, 'fonts')) else 0, 'fonts.css' in html))
    for a in rep['actions']:
        print('            ' + a)
    ok &= len(rep['faces']) >= 1 and 'fonts.css' in html and os.path.exists(rep['css'])
    rep2 = localize(scene, out_dir=os.path.join(d, 'fonts'), local=True, dry_run=True, offline=True)
    print('selftest  --local dry-run: %s' % (rep2['faces'][:1]))
    ok &= not rep2['faces'] or "local(" in rep2['faces'][0]        # already declared via fonts.css? no: link only, faces still generated
    shutil.rmtree(d, ignore_errors=True)
    print('selftest  ' + ('PASS' if ok else 'FAIL'))
    return bool(ok)


def main(argv):
    if '--selftest' in argv:
        return 0 if selftest() else 1
    args = [a for a in argv if not a.startswith('--')]
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default
    for name in ('--out', '--css'):
        v = opt(name)
        if v in args:
            args.remove(v)
    if not args:
        print(__doc__.split('\n\n')[0]); return 2
    rep = localize(args[0], out_dir=opt('--out'), css_name=opt('--css', 'fonts.css'), local='--local' in argv,
                   dry_run='--dry-run' in argv, offline='--offline' in argv)
    if '--json' in argv:
        print(json.dumps(rep, indent=1)); return 0 if rep['ok'] else 1
    for a in rep['actions']:
        print('  ' + a)
    for w in rep['warnings']:
        print('  WARNING ' + w)
    if rep['css']:
        print('  wrote %s%s' % (os.path.relpath(rep['css']), ' (dry run — nothing written)' if rep['dry_run'] else ''))
    if not rep['actions'] and not rep['warnings']:
        print('  nothing to localize: every family is declared')
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main(sys.argv[1:]))
