# -*- coding: utf-8 -*-
"""skin_apply.py — make a look a one-flag choice: skin JSON → scenes/skin_data.js (+ design.md tokens).

    python tools/skin_apply.py skins/<name>.json [--project .] [--out scenes/skin_data.js] [--no-design] [--json]
    python tools/skin_apply.py --selftest

build_film.py runs this when film.json has  "skin": "skins/<name>.json"  (step 0, before the lint and the render).

HOW A SCENE APPLIES THE TOKENS. The scene's CSS already reads var(--paper), var(--ink), var(--accent), var(--black)
… with the fictional Acme defaults on :root. This tool writes `scenes/skin_data.js`, a plain local script that

    1. sets window.SKIN = <the whole skin document> (shots.js may read SKIN.motion.enter_s / push_s / hold_s,
       SKIN.captions.style, SKIN.seams.allowed — guidance, never the clock);
    2. sets every style/layout token as a CSS custom property on document.documentElement AT LOAD, synchronously,
       before the first __seek: colour and font tokens → `--<id>: <value>`, number tokens → `--<id>: <value><unit>`,
       enum tokens → `--<id>` plus a `data-skin-<id>` attribute on <html>; `data-skin="<name>"` names the look;
    3. exposes SKIN.bind(document) for the content slots (title, subtitle, caption, logo): called by a scene that
       wants the skin's copy, it fills only EMPTY bound elements, so authored FILM.* text is never overwritten;
       a bound logo's decode() lands in SKIN.pending — the scene awaits SKIN.ready() in its first __seek.

The scene includes it once, right after its <style> block and before any script that measures layout:

    <script src="skin_data.js"></script>

No skin in film.json → no file is written and the scene renders with its own :root defaults, exactly as before.
There is no query-string or fetch() path: a file: scene cannot fetch, and a generated local script is what the
lint and the determinism canary can see. To preview another look, run the tool again with another skin.

HEAD FADE. The scene's #black plate (the only fade in a film: the head fade-in) is `background: var(--black)`.
Light skins set `black` = `paper` (brand_kit.py does this for every light ground), so with the skin applied a
light film opens from its own paper, never from a dark flash. build_film.py logs the plate colour and compares
the first rendered frame against it; tools/export.py uses the same token for the booth-loop dip.

DESIGN.MD. The project's design.md frontmatter (gates/text_gate.py reads it to police authored colours) is
rewritten from the skin so the two cannot disagree: colors.ground ← paper, ground2 ← paper2, ink, ink_soft,
muted, accent, gold, black; type.display.family ← title-font; type.sans.family ← body-font; fonts ← the skin's
families; a `skin:` line names the source. colors.paper (the PRODUCT's page colour behind footage) is never
touched — it is not a brand token. Only those lines move; comments and the prose stay; the file keeps its
newline style. Pass --no-design to leave design.md alone.

Deterministic: same skin → byte-identical skin_data.js (sorted keys, no clock). Exit 0 ok · 1 skin check
findings (file still written) · 2 usage. Stdlib only; tools/brand_kit.py is used for the skin check when present.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE_TYPES = ('color', 'font', 'number', 'enum')
DESIGN_COLOURS = (('ground', 'paper'), ('ground2', 'paper2'), ('ink', 'ink'), ('ink_soft', 'ink-soft'), ('muted', 'muted'),
                  ('accent', 'accent'), ('gold', 'gold'), ('black', 'black'))

LOADER = r"""
(function (S) {
  'use strict';
  if (typeof document === 'undefined' || !S || !S.tokens) return;
  var html = document.documentElement, root = html.style, keys = Object.keys(S.tokens).sort();
  for (var i = 0; i < keys.length; i++) {
    var id = keys[i], slot = S.tokens[id];
    if (!slot || typeof slot !== 'object') continue;
    var v = slot['default'], type = slot.type || 'color';
    if (v === null || v === undefined) continue;
    if (type === 'color' || type === 'font') root.setProperty('--' + id, String(v));
    else if (type === 'number') root.setProperty('--' + id, String(v) + (slot.unit || ''));
    else if (type === 'enum') { root.setProperty('--' + id, String(v)); html.setAttribute('data-skin-' + id, String(v)); }
  }
  html.setAttribute('data-skin', String(S.name || ''));
  html.setAttribute('data-skin-ground', String(S.background || ''));
  /* content slots bind on request only, and only into empty elements: authored FILM.* copy always wins.
     A bound logo's decode() is collected in SKIN.pending; the scene awaits SKIN.ready() in its first __seek. */
  S.pending = [];
  S.ready = function () { return Promise.all(S.pending); };
  S.bind = function (doc) {
    doc = doc || document; var n = 0;
    for (var j = 0; j < keys.length; j++) {
      var id2 = keys[j], s2 = S.tokens[id2];
      if (!s2 || typeof s2 !== 'object' || !s2.binds) continue;
      var val = s2['default'], el = doc.querySelector(s2.binds);
      if (!el || val === null || val === undefined) continue;
      if (s2.type === 'string' && !(el.textContent || '').trim()) { el.textContent = String(val); n++; }
      else if (s2.type === 'image') { el.src = String(val); el.hidden = false; S.pending.push(el.decode ? el.decode().catch(function () {}) : Promise.resolve()); n++; }
    }
    return n;
  };
})(window.SKIN);
"""


def load_skin(path):
    skin = json.load(open(path, encoding='utf-8'))
    if not isinstance(skin, dict) or not isinstance(skin.get('tokens'), dict):
        raise SystemExit('skin_apply: %s is not a skin (no "tokens" object)' % path)
    return skin


def token(skin, tid, default=None):
    slot = skin.get('tokens', {}).get(tid)
    if isinstance(slot, dict):
        return slot.get('default', default)
    return slot if slot is not None else default


def head_fade(skin):
    """The head-fade plate colour: the `black` token, else the paper (a light skin opens from its own ground)."""
    return token(skin, 'black') or token(skin, 'paper') or '#05161C'


def css_vars(skin):
    """{'--id': value} the loader will set — for logs, the selftest and anyone who wants the CSS snippet."""
    out = {}
    for tid in sorted(skin.get('tokens', {})):
        slot = skin['tokens'][tid]
        if not isinstance(slot, dict) or slot.get('default') is None:
            continue
        t = slot.get('type', 'color')
        if t in ('color', 'font', 'enum'):
            out['--' + tid] = str(slot['default'])
        elif t == 'number':
            out['--' + tid] = '%s%s' % (slot['default'], slot.get('unit', ''))
    return out


def skin_js(skin, source_rel):
    body = json.dumps(skin, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    head = ('/* scenes/skin_data.js — generated by tools/skin_apply.py from %s. Do not edit: re-run the tool.\n'
            '   Sets window.SKIN and the skin tokens as CSS custom properties on :root at load (colour, font, number, enum);\n'
            '   SKIN.bind(document) fills empty content slots on request. Head-fade plate (--black): %s */\n' % (source_rel, head_fade(skin)))
    return head + 'window.SKIN = ' + body + ';' + LOADER


def _detect_nl(raw):
    return '\r\n' if b'\r\n' in raw else '\n'


def update_design(path, skin, skin_rel):
    """Rewrite the token lines of design.md's frontmatter from the skin. Returns the list of keys changed."""
    raw = open(path, 'rb').read()
    nl = _detect_nl(raw)
    text = raw.decode('utf-8').replace('\r\n', '\n')
    m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    if not m:
        return []
    fm, rest = m.group(1), text[m.end():]
    lines = fm.split('\n')
    changed = []

    def set_quoted(prefix_rx, value, key):
        for i, ln in enumerate(lines):
            mm = re.match(prefix_rx, ln)
            if mm:
                new = '%s"%s"%s' % (mm.group(1), value, ln[mm.end():])
                if new != ln:
                    lines[i] = new; changed.append(key)
                return True
        return False

    for dkey, tid in DESIGN_COLOURS:
        v = token(skin, tid)
        if v:
            set_quoted(r'^(\s+%s:\s*)"[^"]*"' % re.escape(dkey), v, 'colors.' + dkey)
    tf, bf = token(skin, 'title-font'), token(skin, 'body-font')
    if tf:
        set_quoted(r'^(\s+display:\s*\{\s*family:\s*)"(?:[^"\\]|\\.)*"', tf.replace('"', '\\"'), 'type.display.family')
    if bf:
        set_quoted(r'^(\s+sans:\s*\{\s*family:\s*)"(?:[^"\\]|\\.)*"', bf.replace('"', '\\"'), 'type.sans.family')
    typ = skin.get('type') or {}
    fams = [f for f in (typ.get('display'), typ.get('body'), typ.get('mono')) if f]
    if fams:
        for i, ln in enumerate(lines):
            if re.match(r'^fonts:\s*\[', ln):
                new = 'fonts: [%s]' % ', '.join('"%s"' % f for f in dict.fromkeys(fams))
                if new != ln:
                    lines[i] = new; changed.append('fonts')
                break
    skin_line = 'skin: %s                 # tokens rewritten by tools/skin_apply.py from this skin' % skin_rel.replace('\\', '/')
    for i, ln in enumerate(lines):
        if re.match(r'^skin:\s', ln):
            if ln != skin_line:
                lines[i] = skin_line; changed.append('skin')
            break
    else:
        at = next((i for i, ln in enumerate(lines) if re.match(r'^name:\s', ln)), 0)
        lines.insert(at + 1, skin_line); changed.append('skin')
    out = '---\n' + '\n'.join(lines) + '\n---\n' + rest
    if changed:
        open(path, 'wb').write(out.replace('\n', nl).encode('utf-8'))
    return changed


def check(skin):
    """brand_kit.check_skin when the tool is beside us; otherwise the minimal structural check."""
    try:
        sys.path.insert(0, HERE)
        import brand_kit
        return list(brand_kit.check_skin(skin))
    except Exception:
        missing = [k for k in ('paper', 'ink', 'accent') if not token(skin, k)]
        return ['missing token %s' % k for k in missing]


def apply(project, skin_path, out_rel='scenes/skin_data.js', design=True):
    project = os.path.abspath(project)
    sp = skin_path if os.path.isabs(skin_path) else os.path.join(project, skin_path)
    if not os.path.exists(sp):
        raise SystemExit('skin_apply: no such skin ' + sp)
    skin = load_skin(sp)
    rel = os.path.relpath(sp, project).replace('\\', '/') if os.path.commonpath([os.path.abspath(sp), project]) == project else os.path.basename(sp)
    findings = check(skin)
    out = os.path.join(project, out_rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    js = skin_js(skin, rel)
    open(out, 'w', encoding='utf-8', newline='\n').write(js)
    changed = []
    dp = os.path.join(project, 'design.md')
    if design and os.path.exists(dp):
        changed = update_design(dp, skin, rel)
    return {'skin': rel, 'name': skin.get('name'), 'background': skin.get('background'), 'head_fade': head_fade(skin),
            'css_vars': css_vars(skin), 'out': os.path.relpath(out, project).replace('\\', '/'), 'design_changed': changed,
            'findings': findings, 'motion': (skin.get('motion') or {}).get('profile'), 'captions': (skin.get('captions') or {}).get('style')}


# ------------------------------------------------------------------------------------------------ selftest
NODE_PROBE = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8');
const props = {}, attrs = {}, bound = {};
const els = { '#tTitle': { textContent: 'Authored title' }, '#tSub': { textContent: '' }, '#tCap': { textContent: '' }, '#logo': { hidden: true } };
const document = { documentElement: { style: { setProperty: (k, v) => { props[k] = v; } }, setAttribute: (k, v) => { attrs[k] = v; } },
                   querySelector: s => els[s] || null };
const window = {}; const fn = new Function('window', 'document', src); fn(window, document);
const n = window.SKIN.bind(document);
console.log(JSON.stringify({ props, attrs, bound: n, title: els['#tTitle'].textContent, sub: els['#tSub'].textContent, name: window.SKIN.name }));
"""


def selftest():
    import shutil, subprocess, tempfile
    film = os.path.normpath(os.path.join(HERE, '..'))
    paper = os.path.join(film, 'skins', 'paper.json'); harbor = os.path.join(film, 'skins', 'harbor.json')
    design_ex = os.path.join(film, 'templates', 'design.example.md')
    assert os.path.exists(paper) and os.path.exists(design_ex), 'skins/paper.json or templates/design.example.md missing'
    td = tempfile.mkdtemp(prefix='skin_apply_self_')
    try:
        os.makedirs(os.path.join(td, 'skins')); shutil.copy(paper, os.path.join(td, 'skins', 'paper.json')); shutil.copy(harbor, os.path.join(td, 'skins', 'harbor.json'))
        raw = open(design_ex, 'rb').read().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')     # a CRLF design.md must stay CRLF
        open(os.path.join(td, 'design.md'), 'wb').write(raw)
        r1 = apply(td, 'skins/paper.json')
        js1 = open(os.path.join(td, 'scenes', 'skin_data.js'), 'rb').read()
        r2 = apply(td, 'skins/paper.json')
        js2 = open(os.path.join(td, 'scenes', 'skin_data.js'), 'rb').read()
        assert js1 == js2, 'skin_data.js not byte-identical across two runs'
        assert r1['head_fade'].upper() == '#F4F1EA' and r1['background'] == 'light', r1
        assert r2['design_changed'] == [], 'second run must change nothing in design.md: %s' % r2['design_changed']
        assert 'colors.ground' in r1['design_changed'] and 'skin' in r1['design_changed'] and 'type.display.family' in r1['design_changed'], r1['design_changed']
        d = open(os.path.join(td, 'design.md'), 'rb').read()
        assert b'\r\n' in d and b'ground: "#F4F1EA"' in d and b'black: "#F4F1EA"' in d and b'paper: "#FFFFFF"' in d, 'design.md tokens/newlines wrong'
        assert b'skin: skins/paper.json' in d and d.count(b'skin: skins/') == 1
        assert re.search(rb'display: \{ family: "Georgia, \\"Times New Roman\\", serif"', d), 'display family not rewritten'
        # the loader in a DOM stub: :root vars, attributes, bind() fills only empty slots
        probe = os.path.join(td, 'probe.js'); open(probe, 'w', encoding='utf-8').write(NODE_PROBE)
        r = subprocess.run(['node', probe, os.path.join(td, 'scenes', 'skin_data.js')], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-400:]
        res = json.loads(r.stdout.strip().splitlines()[-1])
        assert res['props']['--black'] == '#F4F1EA' and res['props']['--paper'] == '#F4F1EA' and res['props']['--ink'] == '#1C1815', res['props']
        assert res['props']['--title-size'] == '64px' and res['props']['--density'] == 'booth' and res['attrs']['data-skin-density'] == 'booth', res
        assert res['attrs']['data-skin'] == 'paper' and res['attrs']['data-skin-ground'] == 'light' and res['name'] == 'paper', res['attrs']
        assert res['title'] == 'Authored title' and res['sub'].startswith('From an analyst') and res['bound'] == 2, res   # logo null → not bound
        assert set(css_vars(load_skin(paper))) == {'--' + k for k in ('paper', 'paper2', 'ink', 'ink-soft', 'muted', 'accent', 'gold', 'black', 'title-font', 'body-font', 'title-size', 'density')}
        # a dark skin keeps a dark plate; switching skins rewrites the same lines once more
        r3 = apply(td, 'skins/harbor.json')
        assert r3['head_fade'].upper() != '#F4F1EA' and r3['background'] == 'dark' and 'colors.ground' in r3['design_changed'], r3
        assert b'skin: skins/harbor.json' in open(os.path.join(td, 'design.md'), 'rb').read()
        # --no-design and a project without design.md
        shutil.rmtree(os.path.join(td, 'scenes')); os.remove(os.path.join(td, 'design.md'))
        r4 = apply(td, 'skins/paper.json', design=False)
        assert r4['design_changed'] == [] and os.path.exists(os.path.join(td, 'scenes', 'skin_data.js'))
        for bad in ('http://', 'https://', 'Date.now', 'Math.random', 'requestAnimationFrame'):      # local, clock-free loader
            assert bad not in js1.decode('utf-8'), bad
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print('skin_apply selftest OK: paper skin → :root --black=#F4F1EA (light head fade), 12 CSS vars, data-skin attrs, bind() fills 2 empty slots only; '
          'design.md CRLF kept, ground/black/type rewritten, product paper untouched, idempotent; harbor re-skin; byte-identical twice')
    return 0


def main(argv):
    if '--selftest' in argv:
        return selftest()
    if '--help' in argv or '-h' in argv or not argv or argv[0].startswith('--'):
        print(__doc__); return 0 if ('--help' in argv or '-h' in argv) else 2

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default
    project = opt('--project', os.getcwd())
    rep = apply(project, argv[0], opt('--out', 'scenes/skin_data.js'), design='--no-design' not in argv)
    if '--json' in argv:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        print('skin_apply: %s (%s ground, motion %s, captions %s) -> %s · head fade plate %s%s' % (
            rep['name'], rep['background'], rep['motion'], rep['captions'], rep['out'], rep['head_fade'],
            ('; design.md: ' + ', '.join(rep['design_changed'])) if rep['design_changed'] else ''))
        for f in rep['findings']:
            print('  FINDING  ' + f)
    return 1 if rep['findings'] else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main(sys.argv[1:]))
