# -*- coding: utf-8 -*-
"""look_gate.py — one look per SHOT TYPE, and every beat checked against the look of its type.  (qa_film.py plug-in)

A film does not have one look; it has one look per kind of shot. Product footage is shown as it was recorded;
recreated cards carry the house identity; a title may spend an effect a card may not; people (b-roll of a
presenter) take a soft treatment and never a glitch. design.md declares the looks, every beat names its type, and
this gate reads the authored CSS / effects against the type's rules.

design.md frontmatter:
    looks:
      product:   { forbid: [haze, grain, vignette, bloom, blur, filter, blend, recolour], selectors: ["#clipWrap", "#clipImg", "#camera"] }
      recreated: { forbid: [glitch], selectors: [".card"] }
      title:     { forbid: [], selectors: ["#titleCard", "#closeCard"] }
      people:    { forbid: [glitch, sharpen, chromatic], selectors: [".people"] }
Without a `looks:` block the defaults above apply (product forbids every cosmetic effect — the footage rule the
grade gate already enforces, now by beat).

Beat type: `look: product|recreated|title|people` in STORYBOARD.md; `type:` is read when it names a look; else
recorded → product, recreated → title when the phase is title/open/close, recreated otherwise. In the scene an
element can carry data-look="product" to join a look's selector set.

Gates (GATE_NAMES):
  look types     every beat resolves to a declared look (FAIL on an unknown look name); the note lists the counts
  look effects   (a) authored CSS: a rule on one of a look's selectors (or a data-look element) that applies a
                 forbidden effect — filter (other than none), backdrop-filter, mix-blend-mode, a VFX.<effect>( or
                 GL.pass/chain( call whose arguments name the selector; (b) the storyboard: a beat's motion:/screen:
                 names a forbidden effect for its type without a negation ("no haze" is a constraint, not a use).
                 Product footage is never graded — a filter on the lane is a FAIL whatever the beat says.

    python gates/look_gate.py --selftest
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_NAMES = ['look types', 'look effects']
LOOKS = ('product', 'recreated', 'title', 'people')
DEFAULT_LOOKS = {
    'product': {'forbid': ['haze', 'grain', 'vignette', 'bloom', 'blur', 'filter', 'blend', 'recolour', 'recolor', 'glitch', 'chromatic', 'sharpen'],
                'selectors': ['#clipWrap', '#clipImg', '#camera', '#pageView', '#pageImg']},
    'recreated': {'forbid': ['glitch'], 'selectors': ['.card']},
    'title': {'forbid': [], 'selectors': ['#titleCard', '#closeCard', '#title', '#close']},
    'people': {'forbid': ['glitch', 'sharpen', 'chromatic'], 'selectors': ['.people']},
}
EFFECT_WORDS = {'haze': r'\bhaz[ey]\b', 'grain': r'\bgrain', 'vignette': r'\bvignett', 'bloom': r'\bbloom', 'blur': r'\bblur', 'filter': r'(?:\bcss\s+)?\bfilter\s*(?:\(|:)|\b(?:a|the|no|any)\s+filter\b|\bfilter\s+(?:on|over|across)\b|\bfiltered\b',
                'blend': r'\b(?:mix-)?blend', 'recolour': r'\brecolou?r', 'recolor': r'\brecolor', 'glitch': r'\bglitch', 'chromatic': r'\bchromatic', 'sharpen': r'\bsharpen'}
NEG = re.compile(r'\b(?:no|never|without|not|zero)\b(?:\s+\w+){0,2}\s*$', re.I)
VFX_CALL = re.compile(r'\b(?:VFX\s*\.\s*(\w+)|GL\s*\.\s*(pass|chain))\s*\(([^;]*)')


def _split_top(s):
    """split on commas outside [] {} and quotes."""
    out, cur, depth, q = [], '', 0, None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch; cur += ch
        elif ch in '[{':
            depth += 1; cur += ch
        elif ch in ']}':
            depth -= 1; cur += ch
        elif ch == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _inline(v):
    """a YAML-lite inline value: "str" | [a, b] | {k: v} (nested) | number | word."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1]
    if v.startswith('[') and v.endswith(']'):
        return [_inline(x) for x in _split_top(v[1:-1]) if x.strip()]
    if v.startswith('{') and v.endswith('}'):
        d = {}
        for part in _split_top(v[1:-1]):
            if ':' in part:
                k, x = part.split(':', 1); d[k.strip().strip('"\'')] = _inline(x)
        return d
    try:
        return float(v) if '.' in v else int(v)
    except ValueError:
        return v


def load_looks(design_path):
    """design.md looks: → {name: {forbid: [...], selectors: [...]}} (defaults fill the gaps). (looks, note)"""
    looks = {k: {'forbid': list(v['forbid']), 'selectors': list(v['selectors'])} for k, v in DEFAULT_LOOKS.items()}
    if not design_path or not os.path.exists(design_path):
        return looks, 'default looks (no design.md)'
    text = open(design_path, encoding='utf-8', errors='replace').read()
    m = re.search(r'(?ms)^looks:[ \t]*\n((?:[ \t]+\S[^\n]*\n?)+)', text)
    if not m:
        return looks, 'default looks (design.md has no looks:)'
    blk = {}
    for line in m.group(1).splitlines():
        line = re.sub(r'(?<!["\w])#(?![0-9a-fA-F]{3,8}).*$', '', line).strip()
        if ':' in line:
            k, v = line.split(':', 1)
            blk[k.strip().strip('"\'')] = _inline(v.strip())
    for name, spec in blk.items():
        if not isinstance(spec, dict):
            continue
        cur = looks.setdefault(name, {'forbid': [], 'selectors': []})
        if 'forbid' in spec:
            cur['forbid'] = [str(x).lower() for x in (spec['forbid'] if isinstance(spec['forbid'], list) else [spec['forbid']])]
        if 'selectors' in spec:
            cur['selectors'] = [str(x) for x in (spec['selectors'] if isinstance(spec['selectors'], list) else [spec['selectors']])]
    return looks, 'looks from %s: %s' % (os.path.basename(design_path), ', '.join(sorted(blk)))


def beat_look(b):
    f = b['fields']
    for key in ('look', 'type'):
        v = (f.get(key) or '').strip().lower().split()
        if v and v[0] in LOOKS:
            return v[0]
    if (f.get('look') or '').strip():
        return (f.get('look') or '').strip().lower().split()[0]          # unknown name → 'look types' fails it
    if b.get('real') == 'recorded':
        return 'product'
    if b.get('real') == 'recreated':
        return 'title' if (f.get('phase') or '').lower() in ('title', 'open', 'opener', 'close', 'closing', 'end') else 'recreated'
    return 'recreated'


def _css_rules(src):
    css = ' '.join(re.findall(r'<style[^>]*>(.*?)</style>', src, re.S | re.I)) or (src if '<' not in src[:200] else '')
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)]


def _effects_in_css(body):
    out = []
    for m in re.finditer(r'(backdrop-filter|filter|mix-blend-mode)\s*:\s*([^;]+)', body, re.I):
        prop, val = m.group(1).lower(), m.group(2).strip().lower()
        if val in ('none', 'normal', 'inherit', 'initial', 'unset'):
            continue
        out.append('blend' if 'blend' in prop else ('blur' if 'blur(' in val else 'filter'))
        if 'blur(' in val and 'filter' not in out:
            out.append('filter')
    return out


def _data_look_selectors(src):
    out = {}
    for m in re.finditer(r'<(\w+)[^>]*\bdata-look\s*=\s*"(\w+)"[^>]*>', src, re.I):
        tag = m.group(0)
        idm = re.search(r'\bid\s*=\s*"([^"]+)"', tag)
        clm = re.search(r'\bclass\s*=\s*"([^"]+)"', tag)
        sels = (['#' + idm.group(1)] if idm else []) + (['.' + c for c in clm.group(1).split()] if clm else [])
        out.setdefault(m.group(2).lower(), []).extend(sels)
    return out


def scan_scene(src, looks):
    """[(look, selector, effect, where)] forbidden effects applied to a look's selectors in authored CSS / effect calls."""
    hits = []
    extra = _data_look_selectors(src)
    sel_of = {name: list(spec['selectors']) + extra.get(name, []) for name, spec in looks.items()}
    for sel, body in _css_rules(src):
        effs = _effects_in_css(body)
        if not effs:
            continue
        for name, sels in sel_of.items():
            if any(s and s in sel for s in sels):
                for e in effs:
                    if e in looks[name]['forbid'] or (e == 'blur' and 'filter' in looks[name]['forbid']):
                        hits.append((name, sel, e, 'css'))
    code = re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', src, flags=re.S))
    for m in VFX_CALL.finditer(code):
        eff = (m.group(1) or m.group(2) or '').lower()
        args = m.group(3)
        effs = [eff] + re.findall(r'["\'](vignette|grain|bloom|haze|blur|glitch|chromatic\w*|sharpen)["\']', args, re.I)
        for name, sels in sel_of.items():
            if any(s and (s in args or s.lstrip('#.') in re.findall(r'\b(\w+)\b', args)) for s in sels):
                for e in effs:
                    key = e.lower().replace('applybloomghost', 'bloom').replace('chromaticsplit', 'chromatic')
                    key = next((k for k in EFFECT_WORDS if key.startswith(k) or k.startswith(key)), key)
                    if key in looks[name]['forbid']:
                        hits.append((name, sels[0], key, 'VFX/GL call'))
    return hits


def scan_beats(beats, looks):
    """[(beat, look, effect, field)] a beat's motion:/screen: naming a forbidden effect for its look (negations skipped)."""
    hits = []
    for b in beats:
        name = beat_look(b)
        spec = looks.get(name)
        if not spec:
            continue
        for field in ('motion', 'screen'):
            txt = b['fields'].get(field) or ''
            for eff in spec['forbid']:
                pat = EFFECT_WORDS.get(eff, r'\b' + re.escape(eff))
                for m in re.finditer(pat, txt, re.I):
                    if NEG.search(txt[:m.start()]):
                        continue
                    hits.append((b['number'], name, eff, field)); break
    return hits


def _beats(ctx):
    project = ctx.get('project') or '.'
    sb = os.path.join(project, ((ctx.get('cfg') or {}).get('storyboard') or 'STORYBOARD.md'))
    if not os.path.exists(sb):
        return None
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
    import storyboard as SB
    return SB.parse(open(sb, encoding='utf-8').read())['beats']


def run(ctx):
    project = ctx.get('project') or '.'
    looks, note = load_looks(os.path.join(project, (ctx.get('qa') or {}).get('design', 'design.md')))
    beats = _beats(ctx)
    res = []
    if beats is None:
        res.append(('look types', True, 'no STORYBOARD.md — %s, beats not typed' % note))
    else:
        unknown = [(b['number'], beat_look(b)) for b in beats if beat_look(b) not in looks]
        counts = {}
        for b in beats:
            counts[beat_look(b)] = counts.get(beat_look(b), 0) + 1
        res.append(('look types', not unknown, ('unknown look on beat %s' % unknown[:4]) if unknown else '%s; %s' % (', '.join('%s %d' % kv for kv in sorted(counts.items())), note)))
    hits = []
    for f in (ctx.get('qa') or {}).get('authored', ['scenes/film.html', 'scenes/shots.js']):
        p = os.path.join(project, f)
        if os.path.exists(p):
            hits += [('%s: %s on %s (%s, %s)' % (look, eff, sel, f, where)) for look, sel, eff, where in scan_scene(open(p, encoding='utf-8', errors='replace').read(), looks)]
    if beats:
        hits += ['beat %02d (%s): %s: names %s' % (n, look, field, eff) for n, look, eff, field in scan_beats(beats, looks)]
    res.append(('look effects', not hits, '; '.join(sorted(set(hits)))[:400] if hits else 'no forbidden effect on any look (%d looks)' % len(looks)))
    return res


def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix='look_gate_')
    os.makedirs(os.path.join(d, 'scenes'))
    open(os.path.join(d, 'design.md'), 'w', encoding='utf-8').write('---\nname: t\nlooks:\n  product: { forbid: [haze, grain, vignette, filter, blend], selectors: ["#clipWrap", "#clipImg"] }\n'
                                                                   '  recreated: { forbid: [glitch, grain], selectors: [".card"] }\n  title: { forbid: [], selectors: ["#titleCard"] }\n---\n')
    sb = ('---\ntitle: t\nversion: 1\nduration: 10s\nmessage: "m"\n---\n## Locked\n- x\n\n## Beat 01 — T (0.0–3.0, ~3.0 s)\n- phase: title\n- real: recreated\n- vo: a\n- motion: grain SETTLES over the title 0.4 s\n'
          '## Beat 02 — P (3.0–7.0, ~4.0 s)\n- phase: nb\n- real: recorded\n- clip: nb\n- vo: b\n- screen: the notebook filters the late deliveries, no haze, no grain\n- camera: push\n'
          '## Beat 03 — C (7.0–10.0, ~3.0 s)\n- phase: card\n- real: recreated\n- look: recreated\n- vo: c\n- motion: the card GLITCHES in 0.3 s\n'
          '## Beat 04 — X (10.0–11.0, ~1.0 s)\n- phase: x\n- real: recreated\n- look: neon\n- vo: d\n')
    open(os.path.join(d, 'STORYBOARD.md'), 'w', encoding='utf-8').write(sb)
    good = '<style>#clipWrap{position:absolute;filter:none}.card{filter:blur(0)}#titleCard{filter:blur(8px)}</style><script>VFX.grain(titleCtx, t, {amount:.1}); /* VFX.haze(clipWrap) */</script>'
    bad = '<style>#clipImg{filter:saturate(1.2)} .card{mix-blend-mode:screen}</style><script>VFX.haze(ctx, $("#clipWrap"), t); GL.chain(glx, lane.imageFor("q"), [["grain", {}]], "#clipImg");</script>'
    open(os.path.join(d, 'scenes', 'film.html'), 'w', encoding='utf-8').write(good)
    ctx = {'project': d, 'cfg': {}, 'qa': {}}
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    looks, note = load_looks(os.path.join(d, 'design.md'))
    t(looks['product']['forbid'] == ['haze', 'grain', 'vignette', 'filter', 'blend'] and looks['title']['forbid'] == [] and 'people' in looks, 'design.md looks: parsed, defaults fill the rest (%s)' % note)
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools')); import storyboard as SB
    beats = SB.parse(sb)['beats']
    t([beat_look(b) for b in beats] == ['title', 'product', 'recreated', 'neon'], 'beat look: phase title → title, recorded → product, look: wins (%s)' % [beat_look(b) for b in beats])
    R = {n: (o, dd) for n, o, dd in run(ctx)}
    t(not R['look types'][0] and 'neon' in R['look types'][1], 'look types: an unknown look name fails')
    hb = scan_beats(beats, looks)
    t([(n, e) for n, _, e, _ in hb] == [(3, 'glitch')], 'storyboard: "GLITCHES" on a recreated beat is a hit; "no haze, no grain" on product is a negation; grain on the title is allowed (%s)' % hb)
    t(scan_scene(good, looks) == [], 'scene (good): filter:none, blur(8px) on the title, grain on the title canvas, a commented haze — no hits')
    hs = scan_scene(bad, looks)
    kinds = sorted(set((l, e) for l, s, e, w in hs))
    t(kinds == [('product', 'filter'), ('product', 'grain'), ('product', 'haze')], 'scene (bad): saturate, VFX.haze and GL grain on the lane are hits; blend on a card is allowed by this design (%s)' % kinds)
    open(os.path.join(d, 'scenes', 'film.html'), 'w', encoding='utf-8').write(bad)
    R2 = {n: (o, dd) for n, o, dd in run(ctx)}
    t(not R2['look effects'][0] and 'beat 03' in R2['look effects'][1] and 'product: filter on' in R2['look effects'][1], 'run(): look effects FAIL lists scene and storyboard hits')
    os.remove(os.path.join(d, 'design.md')); open(os.path.join(d, 'scenes', 'film.html'), 'w', encoding='utf-8').write(good)
    sb2 = sb.replace('- look: neon\n', '').replace('- motion: the card GLITCHES in 0.3 s\n', '- motion: the card SLIDES in 0.3 s\n')
    open(os.path.join(d, 'STORYBOARD.md'), 'w', encoding='utf-8').write(sb2)
    R3 = {n: (o, dd) for n, o, dd in run(ctx)}
    t(R3['look types'][0] and R3['look effects'][0] and 'default looks' in R3['look types'][1], 'no design.md: default looks, clean project passes')
    shutil.rmtree(d, ignore_errors=True)
    print('look_gate selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if '--selftest' in sys.argv or len(sys.argv) < 2:
        sys.exit(selftest())
    proj = os.path.abspath(sys.argv[1])
    qa = json.load(open(os.path.join(proj, 'qa.json'), encoding='utf-8')) if os.path.exists(os.path.join(proj, 'qa.json')) else {}
    bad = 0
    for name, ok, d in run({'project': proj, 'cfg': {}, 'qa': qa}):
        print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', d)); bad += 0 if ok else 1
    sys.exit(1 if bad else 0)
