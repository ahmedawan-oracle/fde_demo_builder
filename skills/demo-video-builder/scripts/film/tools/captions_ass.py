# -*- coding: utf-8 -*-
"""captions_ass.py — word-timed sidecar captions (.ass with per-word \\k tags, plus .srt / .vtt) from the lane's own groups.

    python tools/captions_ass.py out/caption_groups.json [--out out/<film>.ass] [--srt out/<film>.srt] [--vtt out/<film>.vtt]
                                 [--overrides captions_overrides.json] [--font "Segoe UI"] [--burn] [--json]
    python tools/captions_ass.py scenes/timing_<name>_data.js --config scenes/captions.json ...     # groups via node lib/captions.js
    python tools/captions_ass.py vo/<name>_words.json --config scenes/captions.json ...             # sibling <name>_phases.json
    python tools/captions_ass.py --selftest

WHY A SECOND CAPTION FORMAT. The burned-in lane (lib/captions.js) is pixels: it survives nothing but the picture.
SRT/VTT survive re-encodes and platform players but carry no word timing. SubStation Alpha (.ass) is the one
sidecar every renderer we ship through understands (ffmpeg's libass on v1/v2 timelines, VLC, mpv, YouTube upload)
AND can time individual words: a line is a sequence of karaoke syllables, each introduced by {\\kN} where N is the
syllable's duration in centiseconds, counted from the end of the previous syllable. Text ahead of the running
syllable is drawn in SecondaryColour, text at or behind it in PrimaryColour — exactly the future/past split the
lane draws. Nothing is re-grouped here: the groups, line breaks and in/out windows come from out/caption_groups.json,
which node lib/captions.js wrote from the SAME word times the burn-in reads, so the sidecar cannot disagree with
the picture (the SRT/VTT written here reuse tools/captions_srt.py).

HOW A WORD IS TIMED. For group words w0..wn with absolute starts s_i and ends e_i and a cue window [in, out):
    lead syllable   {\\k round((s_0 - in)·100)}                 silent: the air before the first word (the lane's 0.08 s lead)
    word i < n      {\\k round((s_{i+1} - s_i)·100)} text_i     the gap to the next word belongs to this word (no flicker)
    last word       {\\k round((e_n - s_n)·100)} text_n
Rounding is done on the cumulative clock (not per syllable) so a line of 12 words drifts by < 1 cs, never by 12.
Line breaks are the lane's own (group.lines → \\N). WrapStyle 2 stops libass from re-wrapping what we broke.

HOW THE KARAOKE LOOK IS CARRIED. The lane's karaoke style = future 0.55, active 1.0 + accent + bold cross-fade +
1.06 pulse, past 0.82 (0.12 s attack, 0.3 s release). In ASS: SecondaryColour = ink at alpha 0x73 (= 1 − 0.55),
and every word carries two \\t transitions relative to the line start: \\t(a, a+120, \\1c&Haccent&) on its onset and
\\t(b, b+300, \\1c&Hink&\\1a&H2E&) on its offset (0x2E = 1 − 0.82). The bold cross-fade and the 1.06 pulse are left out
on purpose: \\b and \\fscx inside a line re-measure the glyph run in libass and shift neighbouring words — the one
thing the lane's reserved-width bold layer exists to prevent. The kinetic style's waterfall is carried as per-word
alpha ramps: fill, karaoke fill, outline and shadow all start at FF and \\t(d_i, d_i+250, …) ramps them to the style's
alphas (00 / 00 / 80 / 5E), d_i = Σ 0.06·0.84^j capped at 0.3 s (CAP.waterfallDelay). Starting the outline and shadow
transparent too matters: libass otherwise draws a dark outlined ghost of every word that has not arrived yet.

STYLE BLOCK (one [V4+ Styles] row per lane style used, at PlayRes 1920x1080): Fontname from the lane's family
(Segoe UI → "Segoe UI Semibold" for weight 600; Bold -1 for ≥ 700; Consolas for the mono styles; --font overrides),
Fontsize = round(sizeH·720)·1.5 exactly as the lane rounds at the 720 stage before DPR 1.5 (48 for the 0.045 body, 54
for kinetic's 0.05), Outline 1.5 / Shadow 2.5 at 50 % / 63 % black (the soft
glyph-local shadow, never a frame-wide bar), MarginL/R 192 (= the 80 % max-width box), MarginV = the lane's bottomPx
(112), Alignment 2 (bottom centre) / 1 (bottom left for left-aligned styles) / 5 (centre for embed fates).
ScaledBorderAndShadow yes so a 720p burn and a 1080p burn look alike.

OVERRIDES (captions_overrides.json): {"<word_index>": {"text"?: str, "t0"?: s, "t1"?: s}}. word_index is either the
running 0-based index of the word over the shown groups in output order (the --json report lists every word with
its index) or "<phase>:<i>" with the phase-local index i from the timing data. text replaces the displayed word in
every output (.ass, .srt, .vtt — lines are rebuilt keeping the lane's words-per-line); t0/t1 move the word and, if
needed, widen the cue window around it. A key that matches no word, or t1 ≤ t0, is a finding (exit 1).

--burn prints the ffmpeg video-filter for export.py / a v1-v2 timeline:  ass='C\\:/…/film.ass'  (filtergraph
escaping: ':' → '\\:', backslashes → '/'). JSON out (--json): {ass, srt, vtt, cues, words, styles, burn_filter, findings}.

Exit codes: 0 ok · 1 findings (bad override, overlapping or zero-length cue, blank selftest frame) · 2 usage.
Stdlib + (selftest only) numpy; ffmpeg with libass on PATH for --selftest and the burn.
"""
import json, os, re, shutil, subprocess, sys, tempfile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import captions_srt as SRT                                  # the SRT/VTT twin: one writer, one truth
except Exception:                                               # pragma: no cover - tools dir moved
    SRT = None

CAPTIONS_JS = os.path.normpath(os.path.join(HERE, '..', 'lib', 'captions.js'))
PLAY_W, PLAY_H = 1920, 1080

# the lane's tokens we need for the style rows (mirrors CAP.STYLES at 1080p; node is the source of truth for
# grouping, this table only shapes the sidecar's look). Unknown style names fall back to 'anchor'.
STYLE_TOKENS = {
    'anchor':      dict(family='sans', weight=600, sizeH=0.045, bottom=112, ink='#F2EFE9', dim=0.55, accent='#EFCB9A', align='center', case='none', tracking=0.012),
    'broadcast':   dict(family='sans', weight=600, sizeH=0.045, bottom=112, ink='#FFFFFF', dim=0.55, accent='#FFFFFF', align='center', case='none', tracking=0.01, box=0.40),
    'documentary': dict(family='sans', weight=500, sizeH=0.045, bottom=108, ink='#F5EFE6', dim=1.0, accent='#F5EFE6', align='left', case='none', tracking=0.005),
    'keynote':     dict(family='sans', weight=800, sizeH=0.16, bottom=0, ink='#FFFFFF', dim=1.0, accent='#FFFFFF', align='center', case='upper', tracking=-0.045),
    'ink':         dict(family='sans', weight=600, sizeH=0.045, bottom=112, ink='#111418', dim=0.55, accent='#B23A2E', align='center', case='none', tracking=0.008, box=0.55, light=True),
    'conference':  dict(family='sans', weight=700, sizeH=0.042, bottom=116, ink='#FFFFFF', dim=0.62, accent='#EFCB9A', align='left', case='none', tracking=0.0, box=0.72),
    'typewriter':  dict(family='mono', weight=500, sizeH=0.040, bottom=112, ink='#E9F3F9', dim=1.0, accent='#E8C874', align='center', case='none', tracking=0.0),
    'clipwipe':    dict(family='sans', weight=300, sizeH=0.05, bottom=112, ink='#FFFFFF', dim=1.0, accent='#FFFFFF', align='center', case='none', tracking=-0.01),
    'karaoke':     dict(family='sans', weight=600, sizeH=0.045, bottom=112, ink='#E9F3F9', dim=0.55, accent='#E8C874', align='center', case='none', tracking=0.012,
                        karaoke=dict(attack=0.12, release=0.3, rest=0.82)),
    'kinetic':     dict(family='sans', weight=700, sizeH=0.05, bottom=112, ink='#E9F3F9', dim=1.0, accent='#E56B5E', align='center', case='none', tracking=-0.01,
                        waterfall=dict(gap0=0.06, decay=0.84, cap=0.3, dur=0.25)),
}
LEAD_DEFAULT = 0.08


# ------------------------------------------------------------------------------------------------ small helpers
def ass_time(x):
    """seconds → H:MM:SS.cc (centiseconds, floor-rounded on the absolute clock)."""
    cs = int(round(max(0.0, float(x)) * 100))
    return '%d:%02d:%02d.%02d' % (cs // 360000, cs % 360000 // 6000, cs % 6000 // 100, cs % 100)


def ass_colour(hex_rgb, opacity=1.0):
    """'#RRGGBB' + opacity → '&HAABBGGRR' (ASS stores alpha as transparency: 00 opaque, FF invisible)."""
    h = hex_rgb.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = max(0, min(255, int(round(255 * (1.0 - opacity)))))
    return '&H%02X%02X%02X%02X' % (a, b, g, r)


def ass_bgr(hex_rgb):
    """'#RRGGBB' → 'BBGGRR' for \\1c&H…& overrides."""
    h = hex_rgb.lstrip('#')
    return (h[4:6] + h[2:4] + h[0:2]).upper()


def alpha_hex(opacity):
    return '%02X' % max(0, min(255, int(round(255 * (1.0 - opacity)))))


def esc_text(s):
    """ASS text: braces open override blocks, so they are spelled out; hard spaces keep leading blanks."""
    return str(s).replace('{', '(').replace('}', ')').replace('\n', '\\N')


def waterfall_delay(i, o):
    acc, gap = 0.0, o['gap0']
    for _ in range(i):
        acc += gap
        gap *= o['decay']
    return min(acc, o['cap'])


def font_for(tok, override=None):
    """(Fontname, Bold) for a lane style on a Windows/mac booth machine."""
    if override:
        return override, (-1 if tok['weight'] >= 700 else 0)
    if tok['family'] == 'mono':
        return 'Consolas', (-1 if tok['weight'] >= 700 else 0)
    if tok['weight'] >= 700:
        return 'Segoe UI', -1
    if tok['weight'] == 600:
        return 'Segoe UI Semibold', 0
    if tok['weight'] <= 300:
        return 'Segoe UI Light', 0
    return 'Segoe UI', 0


# ------------------------------------------------------------------------------------------------ loading groups
def load_groups(path, config=None):
    """caption_groups.json → dict. A timing_*_data.js or <name>_words.json is first run through node lib/captions.js
    (the same grouper the burn-in uses) into a temp groups file."""
    low = path.lower()
    if low.endswith('.json') and not low.endswith('_words.json'):
        doc = json.load(open(path, encoding='utf-8'))
        if 'groups' in doc:
            return doc
        raise SystemExit('captions_ass: %s has no "groups" — pass out/caption_groups.json, timing_*_data.js or vo/<name>_words.json' % path)
    if not shutil.which('node'):
        raise SystemExit('captions_ass: node is required to group raw timing data (or pass out/caption_groups.json)')
    tmp = tempfile.mkdtemp(prefix='capass_')
    timing = path
    if low.endswith('_words.json'):
        phases = path[:-len('_words.json')] + '_phases.json'
        if not os.path.exists(phases):
            raise SystemExit('captions_ass: %s needs its sibling %s' % (path, os.path.basename(phases)))
        ph = json.load(open(phases, encoding='utf-8')); wd = json.load(open(path, encoding='utf-8'))
        timing = os.path.join(tmp, 'timing_data.js')
        with open(timing, 'w', encoding='utf-8') as fh:
            fh.write('module.exports=' + json.dumps({'PHASES': {'total': ph['total'], 'phases': ph['phases']}, 'WORDS': wd}) + ';\n')
    out = os.path.join(tmp, 'caption_groups.json')
    cmd = ['node', CAPTIONS_JS, os.path.abspath(timing)] + ([os.path.abspath(config)] if config else []) + ['--out', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise SystemExit('captions_ass: node lib/captions.js failed:\n' + (r.stderr or r.stdout))
    return json.load(open(out, encoding='utf-8'))


# ------------------------------------------------------------------------------------------------ overrides
def word_table(doc, include_all=False):
    """Flat word list with running indices over the shown groups (output order)."""
    rows, k = [], 0
    for gi, g in enumerate(doc['groups']):
        if g.get('fate') == 'drop' and not include_all:
            continue
        for wi, w in enumerate(g.get('words') or []):
            rows.append({'index': k, 'group': g.get('id', 'cg-%d' % gi), 'gi': gi, 'wi': wi, 'phase': g.get('phase', ''), 'i': w.get('i', wi),
                         'text': w.get('display', w.get('w', '')), 't0': float(w['start']), 't1': float(w['end'])})
            k += 1
    return rows


def apply_overrides(doc, overrides, lead=LEAD_DEFAULT):
    """Mutates doc in place; returns findings (strings). Keys: '<index>' or '<phase>:<i>'. Values: text / t0 / t1."""
    findings = []
    if not overrides:
        return findings
    table = word_table(doc)
    by_index = {r['index']: r for r in table}
    by_phase = {'%s:%s' % (r['phase'], r['i']): r for r in table}
    touched = set()
    for key in sorted(overrides.keys(), key=lambda s: (len(str(s)), str(s))):
        if str(key).startswith('_'):
            continue
        o = overrides[key] or {}
        row = by_index.get(int(key)) if re.fullmatch(r'\d+', str(key)) else by_phase.get(str(key))
        if row is None:
            findings.append('override "%s" matches no word (indices 0..%d, or phase:i)' % (key, len(table) - 1))
            continue
        g = doc['groups'][row['gi']]; w = g['words'][row['wi']]
        if 'text' in o and o['text'] is not None:
            w['display'] = str(o['text'])
        t0 = float(o['t0']) if o.get('t0') is not None else float(w['start'])
        t1 = float(o['t1']) if o.get('t1') is not None else float(w['end'])
        if t1 <= t0:
            findings.append('override "%s": t1 %.3f <= t0 %.3f' % (key, t1, t0))
            continue
        w['start'], w['end'] = round(t0, 3), round(t1, 3)
        g['in'] = round(min(float(g['in']), t0 - lead), 3)
        g['out'] = round(max(float(g['out']), t1 + 0.02), 3)
        touched.add(row['gi'])
    for gi in sorted(touched):                                  # rebuild text + lines, keeping the lane's words-per-line
        g = doc['groups'][gi]
        counts = [len(l.split(' ')) for l in (g.get('lines') or [g.get('text', '')])]
        words = [w.get('display', w.get('w', '')) for w in g['words']]
        lines, k = [], 0
        for n in counts:
            lines.append(' '.join(words[k:k + n])); k += n
        if k < len(words):
            lines[-1] = (lines[-1] + ' ' + ' '.join(words[k:])).strip()
        g['lines'] = [l for l in lines if l]
        g['text'] = ' '.join(words)
    return findings


# ------------------------------------------------------------------------------------------------ the .ass writer
def style_rows(styles_used, font_override=None):
    rows = []
    for name in sorted(styles_used):
        tok = STYLE_TOKENS.get(name, STYLE_TOKENS['anchor'])
        fontname, bold = font_for(tok, font_override)
        size = int(round(round(tok['sizeH'] * 720) * 1.5))                       # the lane rounds at the 720 stage, then DPR 1.5 → 48 px for the 0.045 body
        primary = ass_colour(tok['ink'])
        secondary = ass_colour(tok['ink'], tok['dim'])
        if tok.get('box'):
            outline, shadow, ocol, bcol, border = 0, 0, ass_colour('#000000', 0.0), ass_colour('#FFFFFF' if tok.get('light') else '#000000', tok['box']), 3
        else:
            outline, shadow, ocol, bcol, border = 1.5, 2.5, ass_colour('#000000', 0.50), ass_colour('#000000', 0.63), 1
        fate_embed = name == 'keynote'
        align = 5 if fate_embed else (1 if tok['align'] == 'left' else 2)
        spacing = round(tok['tracking'] * size, 2)
        rows.append('Style: %s,%s,%d,%s,%s,%s,%s,%d,0,0,0,100,100,%.2f,0,%d,%.1f,%.1f,%d,%d,%d,%d,1' % (
            name, fontname, size, primary, secondary, ocol, bcol, bold, spacing, border, outline, shadow, align,
            int(PLAY_W * 0.10), int(PLAY_W * 0.10), int(tok['bottom'])))
    return rows


def karaoke_text(g, tok):
    """One Dialogue text: {\\k} syllables on the cumulative clock + the style's per-word transitions + \\N breaks."""
    words = g['words']
    t_in = float(g['in'])
    counts = [len(l.split(' ')) for l in (g.get('lines') or [g.get('text', '')])]
    parts, cs_done = [], 0
    kar, wf = tok.get('karaoke'), tok.get('waterfall')

    def syl(dur_end_abs):
        nonlocal cs_done
        target = int(round((dur_end_abs - t_in) * 100))
        d = max(0, target - cs_done); cs_done = target
        return d
    lead_cs = syl(float(words[0]['start'])) if words else 0
    if lead_cs > 0:
        parts.append('{\\k%d}' % lead_cs)
    k, li = 0, 0
    for i, w in enumerate(words):
        s, e = float(w['start']), float(w['end'])
        nxt = float(words[i + 1]['start']) if i + 1 < len(words) else e
        d = syl(max(nxt, e) if i + 1 < len(words) else e)
        tags = '\\k%d' % d
        a, b = int(round((s - t_in) * 1000)), int(round((e - t_in) * 1000))
        if kar:
            tags += '\\t(%d,%d,\\1c&H%s&)\\t(%d,%d,\\1c&H%s&\\1a&H%s&)' % (a, a + int(kar['attack'] * 1000), ass_bgr(tok['accent']),
                                                                           b, b + int(kar['release'] * 1000), ass_bgr(tok['ink']), alpha_hex(kar['rest']))
        if wf:
            d0 = int(round(waterfall_delay(i, wf) * 1000))
            # fill, karaoke fill, outline AND shadow start fully transparent (otherwise libass draws a dark outlined ghost of the
            # unarrived words), then ramp to the style's own alphas: fill 00, outline 80 (50 % black), shadow 5E (63 % black)
            tags += '\\1a&HFF&\\2a&HFF&\\3a&HFF&\\4a&HFF&\\t(%d,%d,\\1a&H00&\\2a&H%s&\\3a&H80&\\4a&H5E&)' % (d0, d0 + int(wf['dur'] * 1000), alpha_hex(tok['dim']))
        if w.get('em'):
            tags += '\\1c&H%s&' % ass_bgr(tok['accent'])
        txt = w.get('display', w.get('w', ''))
        if tok.get('case') == 'upper':
            txt = txt.upper()
        parts.append('{%s}%s' % (tags, esc_text(txt)))
        k += 1
        if li < len(counts) - 1 and k >= counts[li]:
            parts.append('\\N'); li += 1; k = 0
        elif i + 1 < len(words):
            parts.append(' ')
    return ''.join(parts)


def build_ass(doc, title='captions', font_override=None, include_all=False):
    """→ (ass_text, findings, meta). Cues are monotonic and clamped to the film end, like the SRT twin."""
    findings, events, styles_used = [], [], set()
    end_film = float(doc.get('end') or doc.get('total') or 1e9)
    prev_end = 0.0
    for g in doc['groups']:
        if g.get('fate') == 'drop' and not include_all:
            continue
        if not g.get('words'):
            continue
        a, b = max(float(g['in']), prev_end), min(float(g['out']), end_film)
        if b - a < 0.05:
            findings.append('%s: cue %.3f–%.3f collapses after clamping (overlap with the previous cue or the film end)' % (g.get('id'), float(g['in']), float(g['out'])))
            continue
        name = g.get('style') if g.get('style') in STYLE_TOKENS else 'anchor'
        if g.get('fate') == 'embed':
            name = 'keynote'
        styles_used.add(name)
        tok = STYLE_TOKENS[name]
        g2 = dict(g); g2['in'] = a
        fade = '{\\fad(120,150)}' if not tok.get('waterfall') else '{\\fad(0,180)}'
        events.append('Dialogue: 0,%s,%s,%s,,0,0,0,,%s%s' % (ass_time(a), ass_time(b), name, fade, karaoke_text(g2, tok)))
        prev_end = b
    head = ['[Script Info]', '; written by tools/captions_ass.py from the lane\'s caption groups - edit captions.json / captions_overrides.json, not this file',
            'Title: %s' % title, 'ScriptType: v4.00+', 'PlayResX: %d' % PLAY_W, 'PlayResY: %d' % PLAY_H, 'WrapStyle: 2',
            'ScaledBorderAndShadow: yes', 'YCbCr Matrix: TV.709', '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
            'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding']
    head += style_rows(styles_used or {'anchor'}, font_override)
    head += ['', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    text = '\n'.join(head + events) + '\n'
    return text, findings, {'cues': len(events), 'styles': sorted(styles_used), 'k_tags': text.count('\\k')}


def burn_filter(ass_path):
    p = os.path.abspath(ass_path).replace('\\', '/').replace(':', '\\:')
    return "ass='%s'" % p


# ------------------------------------------------------------------------------------------------ selftest
def _synthetic_doc():
    """Three fictional Acme captions: karaoke, anchor, kinetic (a 2 s film, cues at 0.2–1.0, 1.05–1.5, 1.55–2.0)."""
    def words(spec, t0):
        out, t = [], t0
        for i, (w, d) in enumerate(spec):
            out.append({'w': w, 'display': w, 'start': round(t, 3), 'end': round(t + d, 3), 'em': False, 'i': i}); t += d + 0.04
        return out
    g0 = words([('Which', 0.16), ('regions', 0.2), ('missed', 0.18), ('target?', 0.22)], 0.28)
    g1 = words([('Acme', 0.16), ('is', 0.08), ('fictional.', 0.2)], 1.1)
    g2 = words([('One', 0.1), ('answer,', 0.16), ('trusted.', 0.18)], 1.6)
    g2[-1]['em'] = True
    return {'total': 2.0, 'end': 2.0, 'style': 'karaoke', 'stage': [1280, 720], 'groups': [
        {'id': 'cg-0', 'phase': 'ask', 'fate': 'rail', 'style': 'karaoke', 'in': 0.2, 'out': 1.0, 'text': 'Which regions missed target?', 'lines': ['Which regions', 'missed target?'], 'words': g0},
        {'id': 'cg-1', 'phase': 'honest', 'fate': 'rail', 'style': 'anchor', 'in': 1.02, 'out': 1.5, 'text': 'Acme is fictional.', 'lines': ['Acme is fictional.'], 'words': g1},
        {'id': 'cg-2', 'phase': 'close', 'fate': 'rail', 'style': 'kinetic', 'in': 1.52, 'out': 2.0, 'text': 'One answer, trusted.', 'lines': ['One answer, trusted.'], 'words': g2}]}


def _frame_rgb(video, t, w=640, h=360):
    import numpy as np
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', video, '-frames:v', '1', '-vf', 'scale=%d:%d' % (w, h),
                        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    return a.reshape(h, w, 3) if a.size == w * h * 3 else None


def selftest():
    import numpy as np
    doc = _synthetic_doc()
    d = tempfile.mkdtemp(prefix='capass_self_')
    ass1, f1, meta = build_ass(doc, 'selftest')
    ass2, _, _ = build_ass(_synthetic_doc(), 'selftest')
    assert ass1 == ass2, 'the .ass is not a pure function of its inputs'
    assert not f1, f1
    assert meta['cues'] == 3 and meta['styles'] == ['anchor', 'karaoke', 'kinetic'], meta
    assert meta['k_tags'] >= 10, meta                                            # 10 words + lead syllables
    assert ass1.count('Dialogue:') == 3 and '\\N' in ass1 and 'Style: karaoke,Segoe UI Semibold,48,' in ass1, ass1[:600]
    assert ass_time(3661.456) == '1:01:01.46' and ass_colour('#E9F3F9') == '&H00F9F3E9' and ass_colour('#E9F3F9', 0.55) == '&H73F9F3E9'
    # overrides: by index and by phase:i; a bad key and a reversed span are findings, not crashes
    doc2 = _synthetic_doc()
    fnd = apply_overrides(doc2, {'1': {'text': 'areas'}, 'close:2': {'t0': 1.95, 't1': 2.0}, '99': {'text': 'x'}, 'ask:0': {'t0': 0.5, 't1': 0.4}})
    assert doc2['groups'][0]['words'][1]['display'] == 'areas' and doc2['groups'][0]['lines'][0] == 'Which areas', doc2['groups'][0]['lines']
    assert doc2['groups'][2]['words'][2]['start'] == 1.95 and doc2['groups'][2]['out'] >= 2.02, doc2['groups'][2]
    assert len(fnd) == 2 and 'matches no word' in fnd[0] and 't1' in fnd[1], fnd
    # files + the SRT/VTT twin
    ass_path = os.path.join(d, 'self.ass'); open(ass_path, 'w', encoding='utf-8-sig').write(ass1)
    if SRT:
        cs = SRT.cues(doc); SRT.write_srt(cs, os.path.join(d, 'self.srt')); SRT.write_vtt(cs, os.path.join(d, 'self.vtt'))
        assert len(cs) == 3 and open(os.path.join(d, 'self.vtt'), encoding='utf-8').read().startswith('WEBVTT'), cs
    # burn the .ass onto a 2 s navy clip and prove the frame is not blank (karaoke cue up at t = 0.6)
    clip = os.path.join(d, 'navy.mp4')
    vf = burn_filter(ass_path)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x082A34:s=1280x720:d=2:r=30', '-vf', vf,
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', clip], capture_output=True, text=True)
    assert r.returncode == 0 and os.path.exists(clip), 'ffmpeg burn failed: ' + (r.stderr or '')[-400:]
    navy = np.array([0x08, 0x2A, 0x34], dtype=np.int16)
    lit, gold = 0, 0
    for t in (0.6, 1.3, 1.9):
        fr = _frame_rgb(clip, t)
        assert fr is not None, 'no frame at %.1f' % t
        dev = np.abs(fr.astype(np.int16) - navy).max(axis=2)
        n = int((dev > 40).sum()); lit += n
        gold += int(((fr[:, :, 0] > 180) & (fr[:, :, 1] > 150) & (fr[:, :, 2] < 160)).sum())      # warm accent pixels (the lit word)
        assert n >= 300, 'frame at %.1f s is blank (%d pixels differ from navy)' % (t, n)
        rows = np.where((dev > 40).any(axis=1))[0]
        assert rows.min() > 360 * 0.6, 'caption pixels found above the lane (row %d of 360)' % rows.min()   # lane sits in the bottom 40 %
    print('captions_ass selftest OK: %d cues, %d \\k tags, styles %s; burn frames lit=%d px (accent %d px); %s' % (
        meta['cues'], meta['k_tags'], ','.join(meta['styles']), lit, gold, vf))
    return 0


# ------------------------------------------------------------------------------------------------ CLI
def main(argv):
    if '--selftest' in argv:
        return selftest()
    if '--help' in argv or '-h' in argv or not argv or argv[0].startswith('--'):
        print(__doc__); return 2 if not ('--help' in argv or '-h' in argv) else 0

    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default
    src = argv[0]
    if not os.path.exists(src):
        print('captions_ass: no such file ' + src); return 2
    try:
        doc = load_groups(src, opt('--config'))
    except SystemExit as e:
        print(str(e)); return 2
    findings = []
    ov_path = opt('--overrides')
    if ov_path:
        if not os.path.exists(ov_path):
            print('captions_ass: no such overrides file ' + ov_path); return 2
        findings += apply_overrides(doc, json.load(open(ov_path, encoding='utf-8')))
    stem = os.path.splitext(opt('--out') or (os.path.splitext(src)[0] if src.lower().endswith('.json') else 'out/captions'))[0]
    ass_path = opt('--out') or stem + '.ass'
    title = os.path.basename(stem)
    text, f2, meta = build_ass(doc, title, opt('--font'), include_all='--all' in argv)
    findings += f2
    os.makedirs(os.path.dirname(os.path.abspath(ass_path)), exist_ok=True)
    with open(ass_path, 'w', encoding='utf-8-sig') as fh:                      # BOM: libass and VLC read the UTF-8 for certain
        fh.write(text)
    srt_path, vtt_path = opt('--srt'), opt('--vtt')
    cues = []
    if SRT and (srt_path or vtt_path):
        cues = SRT.cues(doc, include_all='--all' in argv)
        if srt_path:
            SRT.write_srt(cues, srt_path)
        if vtt_path:
            SRT.write_vtt(cues, vtt_path)
    report = {'ass': ass_path.replace('\\', '/'), 'srt': srt_path, 'vtt': vtt_path, 'cues': meta['cues'], 'k_tags': meta['k_tags'], 'styles': meta['styles'],
              'words': word_table(doc, include_all='--all' in argv), 'burn_filter': burn_filter(ass_path), 'findings': findings}
    if '--json' in argv:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print('captions_ass: %d cues, %d \\k tags, styles %s -> %s%s%s' % (meta['cues'], meta['k_tags'], ','.join(meta['styles']), ass_path,
              (' + ' + srt_path) if srt_path else '', (' + ' + vtt_path) if vtt_path else ''))
        for f in findings:
            print('  FINDING  ' + f)
    if '--burn' in argv:
        print('-vf "%s"' % report['burn_filter'])
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
