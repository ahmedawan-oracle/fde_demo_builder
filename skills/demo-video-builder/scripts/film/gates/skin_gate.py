# -*- coding: utf-8 -*-
"""skin_gate.py — qa_film.py plug-in: the look was approved before the build, and the scene draws only from it.

    python gates/skin_gate.py --selftest        (shipped skins + a synthetic scene, < 2 s)

Gates (GATE_NAMES, in order):
  skin check       film.json "skin" (or qa.json "skin") names the active skin JSON (skins/<name>.json or a
                   brand_kit.py extract). tools/brand_kit.check_skin runs on it: 16 token ids present, hex colours, no
                   pure #000/#FFF, WCAG floors against the paper (ink 7:1, ink-soft/muted 4.5:1, accent/gold 3:1),
                   fonts in the local table, motion profile inside the doctrine, caption style known, <= 3 seam
                   techniques, when_to_use non-empty. PASS 'scene defaults' when no skin is configured.
  skin tokens      every design token the scene uses — `var(--x)` in CSS / inline styles / JS strings — is one of the
                   skin's token ids (plus library-owned prefixes --glass-*, --cap-*, --ovl-* and qa.json
                   "skin_extra_tokens"). A token the scene declares in :root but the skin does not know is listed.
                   FAIL with a skin; without one the house set (templates/skin_tokens.example.json) is the reference
                   and unknown tokens are a WARN (v4 scenes keep passing).
  review lock      STORYBOARD.md's ## Locked section carries the sign-off tools/review_pack.py --lock writes
                   (`- signed off by: NAME`). qa.json "review_lock": "warn" (default: PASS with the hint) | "require"
                   (FAIL until the plan is signed off) | "off". Skipped when there is no storyboard.
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(FILM_DIR, 'tools'))

GATE_NAMES = ['skin check', 'skin tokens', 'palette tones', 'review lock']
TONES = ('black', 'mid', 'live', 'warm')
LIB_PREFIXES = ('--glass-', '--cap-', '--ovl-', '--hud-', '--cursor-')      # tokens the libraries install themselves
STRIP = lambda s: re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S))


def skin_path(ctx):
    cfg, qa, P = ctx.get('cfg') or {}, ctx.get('qa') or {}, ctx['project']
    rel = cfg.get('skin') or qa.get('skin')
    return os.path.join(P, rel) if rel else None


def used_tokens(text):
    """Custom properties a scene reads (var(--x)) and declares (--x: in CSS or setProperty('--x'))."""
    txt = STRIP(text)
    used = set(m.group(1) for m in re.finditer(r'var\(\s*(--[\w-]+)', txt))
    declared = set(m.group(1) for m in re.finditer(r'(?<![\w-])(--[\w-]+)\s*:', txt))
    declared |= set(m.group(1) for m in re.finditer(r'setProperty\(\s*[\'"](--[\w-]+)', txt))
    return used, declared


def token_findings(used, declared, skin_ids, extra=()):
    """(unknown_used, unknown_declared) against the skin's ids; library prefixes and extras are allowed."""
    allowed = set('--' + k for k in skin_ids) | set(extra)
    ok = lambda t: t in allowed or t.startswith(LIB_PREFIXES)
    return sorted(t for t in used if not ok(t)), sorted(t for t in declared if not ok(t))


def house_ids():
    p = os.path.join(FILM_DIR, 'templates', 'skin_tokens.example.json')
    try:
        return list((json.load(open(p, encoding='utf-8')).get('tokens') or {}).keys())
    except (OSError, ValueError):
        return []


def _hex_rgb(h):
    m = re.match(r'#?([0-9a-fA-F]{6})\b', str(h).strip())
    if not m:
        return None
    v = m.group(1)
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _luma(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _hue(rgb):
    import colorsys
    return colorsys.rgb_to_hls(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)[0] * 360.0


def _sat(rgb):
    import colorsys
    return colorsys.rgb_to_hls(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)[2]


def palette_tones(design_path):
    """design.md `tones:` {black, mid, live, warm} → (errors, note). Each role names a `colors:` token or a hex. Rules:
    four roles present; black is the darkest and mid sits between black and the lighter two (luma); live and warm are
    saturated (> 0.25) and at least 30° of hue apart — one cool accent that moves, one warm accent that lands."""
    if not design_path or not os.path.exists(design_path):
        return None, 'no design.md'
    sys.path.insert(0, HERE)
    import look_gate as LKG
    text = open(design_path, encoding='utf-8', errors='replace').read()
    colors = {}
    m = re.search(r'(?ms)^colors:[ \t]*\n((?:[ \t]+\S[^\n]*\n?)+)', text)
    if m:
        for line in m.group(1).splitlines():
            line = re.sub(r'(?<!["\w])#(?![0-9a-fA-F]{3,8}\b).*$', '', line).strip()
            if ':' in line:
                k, v = line.split(':', 1); colors[k.strip().strip('"\'')] = str(LKG._inline(v.strip()))
    m = re.search(r'(?m)^tones:[ \t]*(\{[^\n]*?\})', text)
    block = LKG._inline(m.group(1)) if m else None
    if block is None:
        m = re.search(r'(?ms)^tones:[ \t]*\n((?:[ \t]+\S[^\n]*\n?)+)', text)
        if m:
            block = {}
            for line in m.group(1).splitlines():
                line = re.sub(r'(?<!["\w])#(?![0-9a-fA-F]{3,8}\b).*$', '', line).strip()
                if ':' in line:
                    k, v = line.split(':', 1); block[k.strip().strip('"\'')] = LKG._inline(v.strip())
    if not isinstance(block, dict):
        return None, 'design.md has no tones: block'
    E, rgb = [], {}
    for role in TONES:
        v = block.get(role)
        if v is None:
            E.append('tones.%s missing' % role); continue
        hx = colors.get(str(v), str(v))
        c = _hex_rgb(hx)
        if c is None:
            E.append('tones.%s = %r is neither a colors: token nor a hex' % (role, v)); continue
        rgb[role] = c
    if len(rgb) == 4:
        L = {k: _luma(v) for k, v in rgb.items()}
        if not (L['black'] < L['mid'] < min(L['live'], L['warm'])):
            E.append('luma order broken: black %.0f, mid %.0f, live %.0f, warm %.0f (black < mid < live/warm)' % (L['black'], L['mid'], L['live'], L['warm']))
        for role in ('live', 'warm'):
            if _sat(rgb[role]) < 0.25:
                E.append('tones.%s is not an accent (saturation %.2f < 0.25)' % (role, _sat(rgb[role])))
        dh = abs(_hue(rgb['live']) - _hue(rgb['warm'])); dh = min(dh, 360 - dh)
        if dh < 30:
            E.append('live and warm are the same hue (%.0f° apart; want ≥ 30°)' % dh)
    return E, '%s' % ', '.join('%s=%s' % (r, block.get(r)) for r in TONES)


def signed_off(storyboard_text):
    m = re.search(r'^##\s+Locked\b(.*?)(?=^##\s|\Z)', storyboard_text, re.M | re.S | re.I)
    if not m:
        return None, 'no ## Locked section'
    s = re.search(r'^\s*-\s*signed off by:\s*(\S.*)$', m.group(1), re.M | re.I)
    return (s.group(1).strip() if s else ''), ('signed off by ' + s.group(1).strip() if s else 'no "signed off by" bullet in ## Locked')


def run(ctx):
    P, qa = ctx['project'], ctx.get('qa') or {}
    res = []
    sp = skin_path(ctx)
    skin, ids = None, []
    if sp is None:
        res.append(('skin check', True, 'no skin in film.json (scene defaults; set "skin": "skins/<name>.json" after the look pass)'))
    elif not os.path.exists(sp):
        res.append(('skin check', False, 'skin file missing: %s' % os.path.relpath(sp, P)))
    else:
        try:
            import brand_kit
            skin = json.load(open(sp, encoding='utf-8'))
            E = brand_kit.check_skin(skin)
            ids = list((skin.get('tokens') or {}).keys())
            res.append(('skin check', not E, ('%s clean (%d tokens, %s ground, %s/%s)' % (skin.get('name', os.path.basename(sp)), len(ids), skin.get('background', '?'),
                                                                                       skin.get('mood', '?'), (skin.get('motion') or {}).get('profile', '?'))) if not E else '; '.join(E)[:200]))
        except Exception as e:
            res.append(('skin check', False, 'brand_kit check failed: %s: %s' % (type(e).__name__, str(e)[:120])))
    scene = ctx.get('scene_html')
    if not scene or not os.path.exists(scene):
        res.append(('skin tokens', True, 'skipped: no scene'))
    else:
        used, declared = used_tokens(open(scene, encoding='utf-8', errors='replace').read())
        ref = ids if ids else house_ids()
        bad_used, bad_decl = token_findings(used, declared, ref, qa.get('skin_extra_tokens') or [])
        strict = bool(ids)
        d = '%d tokens used, %d declared vs %s' % (len(used), len(declared), 'skin %s' % skin.get('name') if skin else 'the house set')
        if bad_used:
            d = ('tokens not in the skin %s; ' % bad_used[:5] if strict else 'WARN tokens outside the house set %s; ' % bad_used[:5]) + d
        if bad_decl:
            d += '; declared but unknown to the skin %s' % bad_decl[:5]
        res.append(('skin tokens', not (strict and bad_used), d))
    E, note = palette_tones(os.path.join(P, qa.get('design', 'design.md')))
    if E is None:
        res.append(('palette tones', True, 'skipped: %s (four roles — black, mid, live, warm — give a film its speed of colour)' % note))
    else:
        res.append(('palette tones', not E, '; '.join(E)[:300] if E else 'four tones in order (%s)' % note))
    sb = os.path.join(P, qa.get('storyboard', 'STORYBOARD.md'))
    mode = str(qa.get('review_lock', 'warn')).lower()
    if mode == 'off':
        res.append(('review lock', True, 'disabled in qa.json'))
    elif not os.path.exists(sb):
        res.append(('review lock', True, 'skipped: no %s' % os.path.basename(sb)))
    else:
        who, d = signed_off(open(sb, encoding='utf-8', errors='replace').read())
        ok = bool(who)
        if not ok:
            d += ' — python tools/review_pack.py --lock --by NAME' + ('' if mode == 'require' else '  (WARN; qa.json "review_lock": "require" to fail)')
        res.append(('review lock', ok or mode != 'require', d))
    return res


# ----------------------------------------------------------------------------------------------- selftest
def _selftest():
    import time
    T0 = time.time()
    tmp = tempfile.mkdtemp(prefix='skingate_')
    os.makedirs(os.path.join(tmp, 'scenes')); os.makedirs(os.path.join(tmp, 'skins'))
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok = ok and bool(cond)
        print('  %-46s %s  %s' % (label, 'PASS' if cond else 'FAIL', str(detail)[:120]))
    harbor = os.path.join(FILM_DIR, 'skins', 'harbor.json')
    skin = json.load(open(harbor, encoding='utf-8'))
    json.dump(skin, open(os.path.join(tmp, 'skins', 'good.json'), 'w'))
    bad = json.loads(json.dumps(skin))
    bad['tokens']['ink'] = {'type': 'color', 'default': '#FFFFFF'} if isinstance(bad['tokens']['ink'], dict) else '#FFFFFF'
    bad['tokens'].pop('gold', None)
    json.dump(bad, open(os.path.join(tmp, 'skins', 'bad.json'), 'w'))
    scene = ("<style>:root{--paper:#082A34;--accent:#E56B5E}\n.card{background:var(--paper);color:var(--ink)}\n"
             "#g{backdrop-filter:blur(var(--glass-blur))}</style><script>/* var(--comment-only) */ el.style.color = 'var(--accent)';</script>")
    scene_bad = scene.replace('var(--ink)', 'var(--ink);border-color:var(--neon-pink)') + '<style>:root{--mystery:1}</style>'
    sg, sb = os.path.join(tmp, 'scenes', 'good.html'), os.path.join(tmp, 'scenes', 'bad.html')
    open(sg, 'w', encoding='utf-8').write(scene); open(sb, 'w', encoding='utf-8').write(scene_bad)
    open(os.path.join(tmp, 'STORYBOARD.md'), 'w', encoding='utf-8').write('# Plan\n\n## Locked\n- beat order\n\n## Beat 01\n- x\n')
    base = {'project': tmp, 'qa': {}, 'cfg': {'skin': 'skins/good.json'}, 'scene_html': sg}
    R = {n: (o, d) for n, o, d in run(base)}
    for n in GATE_NAMES:
        print('    %-14s %s  %s' % (n, 'PASS' if R[n][0] else 'FAIL', R[n][1][:110]))
    check('shipped skin passes check', R['skin check'][0], R['skin check'][1])
    check('scene tokens subset of the skin (glass-* allowed)', R['skin tokens'][0] and 'not in the skin' not in R['skin tokens'][1], R['skin tokens'][1])
    check('unsigned storyboard: WARN by default (PASS)', R['review lock'][0] and 'signed off by' in R['review lock'][1], R['review lock'][1])
    R = {n: (o, d) for n, o, d in run(dict(base, cfg={'skin': 'skins/bad.json'}, scene_html=sb, qa={'review_lock': 'require'}))}
    for n in GATE_NAMES:
        print('    %-14s %s  %s' % (n, 'PASS' if R[n][0] else 'FAIL', R[n][1][:110]))
    check('pure white ink + missing gold fail the check', not R['skin check'][0] and 'pure' in R['skin check'][1] and 'missing' in R['skin check'][1], R['skin check'][1])
    check('token outside the skin fails, declared unknown listed', not R['skin tokens'][0] and '--neon-pink' in R['skin tokens'][1] and '--mystery' in R['skin tokens'][1], R['skin tokens'][1])
    check('review_lock require: unsigned fails', not R['review lock'][0], R['review lock'][1])
    open(os.path.join(tmp, 'STORYBOARD.md'), 'a', encoding='utf-8').write('')
    txt = open(os.path.join(tmp, 'STORYBOARD.md'), encoding='utf-8').read().replace('- beat order\n', '- beat order\n- signed off by: Reviewer\n- signed off date: 2026-01-02\n')
    open(os.path.join(tmp, 'STORYBOARD.md'), 'w', encoding='utf-8').write(txt)
    R = {n: (o, d) for n, o, d in run(dict(base, cfg={}, qa={'review_lock': 'require'}))}
    check('signed storyboard passes require', R['review lock'][0] and 'Reviewer' in R['review lock'][1], R['review lock'][1])
    check('no skin -> scene defaults, house set reference', R['skin check'][0] and 'house set' in R['skin tokens'][1], R['skin tokens'][1])
    R = {n: (o, d) for n, o, d in run(dict(base, cfg={}, scene_html=sb))}
    check('no skin: unknown token is WARN only', R['skin tokens'][0] and 'WARN' in R['skin tokens'][1], R['skin tokens'][1])
    R = {n: (o, d) for n, o, d in run(dict(base, cfg={'skin': 'skins/none.json'}))}
    check('missing skin file fails', not R['skin check'][0], R['skin check'][1])
    for name in sorted(os.listdir(os.path.join(FILM_DIR, 'skins'))):
        if name.endswith('.json'):
            r = run(dict(base, cfg={'skin': 'skins/' + name}, project=FILM_DIR, scene_html=None))[0]
            check('shipped skins/%s' % name, r[1], r[2])
    u, d = used_tokens('a{color:var(--x)} b{--y:1} /* var(--z) */')
    check('used_tokens pure (comments ignored)', u == {'--x'} and d == {'--y'})
    print('\n%s  (%.1f s)  %s' % ('SELFTEST PASS' if ok else 'SELFTEST FAIL', time.time() - T0, tmp))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
