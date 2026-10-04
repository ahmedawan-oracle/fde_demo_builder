# -*- coding: utf-8 -*-
"""storyboard.py — STORYBOARD.md: lenient parser → manifest, arithmetic/plan checks, and the review sheet.

    python tools/storyboard.py parse  [STORYBOARD.md] [--json]
    python tools/storyboard.py check  [STORYBOARD.md] [--phases vo/<name>_phases.json] [--clips clips.json]
                                      [--qa qa.json] [--brief BRIEF.md] [--autonomous] [--build]
                                      [--require-approvals [out/review/approvals.json]] [--no-require-approvals]
                                      [--timeline out/timeline.json]   (hold: per beat vs FILM.holds / shots.js, > 0.05 fails)
    python tools/storyboard.py sheet  [STORYBOARD.md] [--out out/storyboard.html] [--design design.md] [--mobile]
                                      [--truth --film out/<film>.mp4] [--phases ...] [--timeline out/timeline.json]
    python tools/storyboard.py set    STORYBOARD.md NN key value          (in-place bullet rewrite)
    python tools/storyboard.py --selftest

The storyboard is the plan layer between the shot log (pixels) and vo_script.py (the clock). One beat per
idea; every beat carries the same field set (see templates/STORYBOARD.example.md). The parser never raises:
anything surprising becomes a warning, unknown keys are kept under `extra`.

Measured rules enforced here (references/brief-storyboard-review.md):
  * beat arithmetic: t0/t1 contiguous, durations sum to the frontmatter `duration`, and — once the narration
    exists — each beat's planned span is compared with vo/<name>_phases.json (drift > 10 % fails, 5-10 % warns)
  * narration pace per beat: words / measured seconds; WARN outside 1.8-3.0 w/s, FAIL above 3.4; WARN > 24 words
  * recreated beats 1.5-8 s (promo grammar 1.5-3.5 s, read beats ~3 s); product beats 4-20 s — advisory
  * why: and constraint: on every beat; callbacks point backwards; exactly one breather; the hero prop's
    quoted text is identical wherever it appears; the value claim lands by beat 2; no subject-internal
    vocabulary (identifiers, table/function names) in the first two beats
  * truthfulness: real: recorded|recreated|placeholder — recorded beats name a clip in clips.json, recreated
    beats' quoted on-screen strings must exist in the authored files at --build, placeholders fail at --build
    unless BRIEF.md allows them
  * first and last frame (v5.1): `start:` and `end:` describe the first and the last moment of a beat in one
    sentence each. `end:` is mandatory on recreated beats (`--build` fails without it; `check` warns before that);
    `start:` is advised everywhere. The end frame matters more than the start: it is what the next cut lands on.
  * approvals (v5.1): when out/review/approvals.json exists (review_pack.py "Approve start / Approve end"), or
    --require-approvals is given, `--build` refuses while any beat's END frame is unapproved
  * review loop: build only after '## Locked' (unless --autonomous); version == number of '## Changes from'
    blocks + 1
  * TTS spelling: digits, %, $, multipliers, acronyms and domains in a vo: line are flagged with the spoken form
Stdlib only.
"""
import json, os, re, subprocess, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.normpath(os.path.join(HERE, '..', 'templates'))

REAL_TAGS = ('recorded', 'recreated', 'placeholder')
ALIASES = {
    'voiceover': 'vo', 'voice_over': 'vo', 'narration': 'vo', 'line': 'vo',
    'on_screen': 'screen', 'onscreen': 'screen', 'scene': 'screen', 'description': 'screen', 'summary': 'screen',
    'seam_out': 'seam', 'transition': 'seam', 'transition_out': 'seam', 'cut': 'seam',
    'truth': 'real', 'truthfulness': 'real', 'footage': 'real',
    'job': 'why', 'purpose': 'why',
    'cam': 'camera', 'move': 'camera',
    'cap': 'caption', 'subtitle': 'caption',
    'no': 'constraint', 'constraints': 'constraint', 'ban': 'constraint',
    'prop': 'hero_prop', 'hero': 'hero_prop',
    'callback_to': 'callback', 'answers': 'callback',
    'emotion': 'beat', 'feel': 'beat',
    'device': 'persuasion',
    'dur': 'duration', 'length': 'duration',
    'sfx': 'audio', 'sound': 'audio', 'music': 'audio',
    'start_frame': 'start', 'first_frame': 'start', 'first': 'start', 'opens_on': 'start',
    'end_frame': 'end', 'last_frame': 'end', 'last': 'end', 'end_state': 'end', 'ends_on': 'end',
}
# physical motion vocabulary — a recreated beat must name a verb (impact / directional / build / organic / mechanical)
VERBS = ('SLAMS', 'STAMPS', 'DROPS', 'LANDS', 'SLIDES', 'PUSHES', 'WIPES', 'CUTS', 'RISES', 'PANS', 'DRAWS', 'FILLS',
         'GROWS', 'COUNTS', 'REVEALS', 'UNCOVERS', 'FLOATS', 'DRIFTS', 'BREATHES', 'TYPES', 'CLICKS', 'LOCKS', 'SCROLLS',
         'HOLDS', 'FADES', 'INVERTS', 'SETTLES')
LAZY_VERBS = ('FLOATS', 'DRIFTS', 'BREATHES')           # sanctioned only when the beat says so (screensaver failure)
STOP = set('a an the and or of to in on for with at by from as is are was were be it its this that these those we you '
           'they our your their one same every any all can will into than then there here what which who whom how'.split())
HOOK_BANNED = [r'\b[a-z]+_[a-z_]+\b', r'\b\w+\.\w+\(', r'\bgroupBy\b', r'\bSELECT\b', r'\bimport\b', r'\bspark\.\w+',
               r'\bAPI\b', r'\bJSON\b', r'\bSQL\b']
TTS_RULES = [
    (r'\$\s?\d[\d,.]*\s*[kKmMbBtT]?\b', 'spell money the way the voice should say it ("nearly two trillion dollars")'),
    (r'\d+(?:\.\d+)?\s?%', 'spell the percent ("ninety nine point nine percent")'),
    (r'\b\d+(?:\.\d+)?x\b', 'say the multiplier ("ten times")'),
    (r'\b\d[\d,]*\+', 'say the floor ("more than one hundred thirty five")'),
    (r'\b\d{2,}(?:[.,]\d+)?\b', 'spell numbers of two digits or more ("twenty three point two"); the screen keeps the exact figure'),
    (r'\b[\w-]+\.(?:com|io|ai|org|net)\b', 'say the domain ("acme dot com")'),
    (r'\b[A-Z]{2,5}\b', 'space the acronym ("A P I") unless the voice already reads it as a word'),
]
DEFAULT_TOKENS = {'ground': '#082A34', 'ink': '#E9F3F9', 'accent': '#E56B5E', 'muted': '#81A9AB',
                  'display': 'Georgia, serif', 'sans': '"Helvetica Neue", Arial, sans-serif', 'mono': 'Consolas, monospace'}


# ------------------------------------------------------------------------------------------------ frontmatter (YAML-lite)
def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1].replace('\\"', '"').replace("\\'", "'")
    if v.startswith('[') and v.endswith(']'):
        return [_scalar(x) for x in _split_commas(v[1:-1]) if x.strip()]
    if v.startswith('{') and v.endswith('}'):
        d = {}
        for part in _split_commas(v[1:-1]):
            if ':' in part:
                k, x = part.split(':', 1)
                d[k.strip().strip('"\'')] = _scalar(x)
        return d
    if re.fullmatch(r'-?\d+', v):
        return int(v)
    if re.fullmatch(r'-?\d*\.\d+', v):
        return float(v)
    if v.lower() in ('true', 'false'):
        return v.lower() == 'true'
    return v


def _split_commas(s):
    out, cur, q = [], '', None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch; cur += ch
        elif ch == ',':
            out.append(cur); cur = ''
        else:
            cur += ch
    out.append(cur)
    return out


def _strip_comment(line):
    out, q = '', None
    for ch in line:
        if q:
            out += ch
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch; out += ch
        elif ch == '#':
            break
        else:
            out += ch
    return out.rstrip()


def frontmatter(text):
    """'---' block at the top → (dict, body, warnings). Handles key: value, one level of indented maps/lists,
    inline [a, b] and {k: v}. Unknown shapes are kept as strings; never raises."""
    warnings = []
    if not text.startswith('---'):
        return {}, text, warnings
    end = re.search(r'(?m)^---\s*$', text[3:])
    if not end:
        warnings.append('frontmatter opened with --- but never closed')
        return {}, text, warnings
    block, body = text[3:3 + end.start()], text[3 + end.end():]
    fm, key = {}, None
    for raw in block.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        if line.startswith((' ', '\t')) and key is not None:
            s = line.strip()
            if s.startswith('- '):
                if not isinstance(fm.get(key), list):
                    fm[key] = [] if fm.get(key) in (None, '') else [fm[key]]
                fm[key].append(_scalar(s[2:]))
            elif ':' in s:
                if not isinstance(fm.get(key), dict):
                    fm[key] = {}
                k, v = s.split(':', 1)
                fm[key][k.strip().strip('"\'')] = _scalar(v)
            else:
                warnings.append('frontmatter: cannot read "%s"' % s)
            continue
        if ':' not in line:
            warnings.append('frontmatter: cannot read "%s"' % line.strip())
            continue
        key, v = line.split(':', 1)
        key = key.strip().lower()
        fm[key] = _scalar(v) if v.strip() else ''
    return fm, body, warnings


# ------------------------------------------------------------------------------------------------ storyboard parser
HEAD = re.compile(r'^(#{2,3})\s*(?:Beat|Frame|Scene|Shot)?\s*(\d{1,3})\s*(?:[-–—:.·]+\s*)?(.*?)\s*$', re.I)
SECT = re.compile(r'^(#{2,3})\s*(.+?)\s*$')
BULLET = re.compile(r'^\s*[-*]\s*([A-Za-z_][\w ]*?)\s*:\s*(.*)$')
SPAN = re.compile(r'\(([^()]*)\)\s*$')
QUOTES = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')


def _times(s):
    """'0.0–6.5, ~6.5 s' → (t0, t1, dur) with None for the parts that are absent."""
    t0 = t1 = dur = None
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:[-–—]|to)\s*(\d+(?:\.\d+)?)', s)
    if m:
        t0, t1 = float(m.group(1)), float(m.group(2))
    m = re.search(r'~\s*(\d+(?:\.\d+)?)', s)
    if m:
        dur = float(m.group(1))
    return t0, t1, dur


def _seconds(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'(\d+(?:\.\d+)?)', str(v))
    return float(m.group(1)) if m else None


def quotes(s):
    """Every on-screen string written verbatim in quotes ("..." or “...”)."""
    return [a or b for a, b in QUOTES.findall(s or '')]


def parse(text):
    """STORYBOARD.md → manifest dict: globals, sections, beats[], warnings[]. Lenient: never raises."""
    fm, body, warnings = frontmatter(text)
    man = {'globals': fm, 'sections': {'direction': [], 'decisions': [], 'changes': [], 'still_open': [], 'locked': [],
                                       'other': {}},
           'beats': [], 'warnings': warnings}
    cur, sect, sect_depth = None, None, 0
    for ln, raw in enumerate(body.splitlines(), 1):
        hm = HEAD.match(raw)
        if hm:
            n, title = int(hm.group(2)), hm.group(3)
            t0 = t1 = dur = None
            sm = SPAN.search(title)
            if sm:
                t0, t1, dur = _times(sm.group(1))
                title = title[:sm.start()].strip()
            cur = {'index': len(man['beats']), 'number': n, 'title': title.strip(' -–—'), 't0': t0, 't1': t1,
                   'dur': dur, 'fields': {}, 'extra': {}, 'narrative': [], 'line': ln}
            man['beats'].append(cur); sect = None
            if dur is None and t0 is not None and t1 is not None:
                cur['dur'] = round(t1 - t0, 3)
            if n != len(man['beats']):
                warnings.append('beat %02d at line %d is out of order (expected %02d)' % (n, ln, len(man['beats'])))
            continue
        sm = SECT.match(raw)
        if sm and not raw.startswith('#' * 4):
            cur = None
            name = sm.group(2).lower()
            if name.startswith('video direction') or name == 'direction':
                sect = 'direction'
            elif name.startswith('decision'):
                sect = 'decisions'
            elif name.startswith('changes from'):
                man['sections']['changes'].append({'from': sm.group(2), 'notes': []}); sect = 'changes'
            elif name.startswith('still open'):
                sect = 'still_open'
            elif name.startswith('locked'):
                sect = 'locked'
            else:
                sect = 'other:' + sm.group(2)
                man['sections']['other'][sm.group(2)] = []
            continue
        if cur is not None:
            bm = BULLET.match(raw)
            if bm:
                key = re.sub(r'\s+', '_', bm.group(1).strip().lower())
                key = ALIASES.get(key, key)
                val = bm.group(2).strip()
                cur['_last'] = key
                cur['fields'][key] = val
            elif raw.startswith((' ', '\t')) and raw.strip() and cur.get('_last'):
                cur['fields'][cur['_last']] += ' ' + raw.strip()          # continuation line
            elif raw.strip():
                cur['narrative'].append(raw.rstrip()); cur['_last'] = None
            continue
        if sect and raw.strip():
            item = raw.strip()
            if item.startswith(('- ', '* ')):
                item = item[2:]
            if sect == 'changes':
                man['sections']['changes'][-1]['notes'].append(item)
            elif sect.startswith('other:'):
                man['sections']['other'][sect[6:]].append(item)
            else:
                man['sections'][sect].append(item)
    for b in man['beats']:
        b.pop('_last', None)
        f = b['fields']
        if 'duration' in f and b['dur'] is None:
            b['dur'] = _seconds(f['duration'])
        if 't0' in f and b['t0'] is None:
            b['t0'] = _seconds(f['t0'])
        if b['t0'] is not None and b['dur'] is not None and b['t1'] is None:
            b['t1'] = round(b['t0'] + b['dur'], 3)
        b['quotes'] = quotes(f.get('screen', ''))
        b['real'] = (f.get('real') or '').strip().lower().split()[0] if f.get('real') else ''
        if f.get('real') and b['real'] not in REAL_TAGS:
            warnings.append('beat %02d: real: "%s" is not one of %s' % (b['number'], f['real'], '|'.join(REAL_TAGS)))
        b['narrative'] = '\n'.join(b['narrative']).strip()
    return man


def set_field(text, n, key, value):
    """Rewrite one '- key: value' bullet of beat n in place (or insert it after the beat's last bullet).
    Multi-line values collapse to one line; the rest of the document is untouched."""
    value = ' '.join(str(value).split())
    lines = text.splitlines(keepends=True)
    start = end = None
    for i, raw in enumerate(lines):
        hm = HEAD.match(raw.rstrip('\n'))
        if hm and int(hm.group(2)) == n and start is None:
            start = i
        elif start is not None and (hm or (SECT.match(raw.rstrip('\n')) and not raw.startswith('####'))):
            end = i; break
    if start is None:
        raise KeyError('beat %02d not found' % n)
    end = end if end is not None else len(lines)
    last_bullet = start
    for i in range(start + 1, end):
        bm = BULLET.match(lines[i].rstrip('\n'))
        if bm:
            last_bullet = i
            k = ALIASES.get(re.sub(r'\s+', '_', bm.group(1).strip().lower()), re.sub(r'\s+', '_', bm.group(1).strip().lower()))
            if k == ALIASES.get(key, key):
                lines[i] = '- %s: %s\n' % (bm.group(1).strip(), value)
                return ''.join(lines)
    lines.insert(last_bullet + 1, '- %s: %s\n' % (key, value))
    return ''.join(lines)


# ------------------------------------------------------------------------------------------------ helpers for check
def words(s):
    return [w for w in re.findall(r"[A-Za-z0-9][\w'’-]*", s or '')]


def norm(s):
    return ' '.join(re.sub(r'[^\w\s]', ' ', re.sub(r"['’]", '', (s or '').lower())).split())


def load_json(path):
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    return None


def strip_code_comments(s):
    return re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S))


def phase_spans(phases):
    """phases.json → {name: (start, end)} where end = next phase start (or total): the beat the phase owns."""
    out, ph = {}, phases.get('phases', [])
    for i, p in enumerate(ph):
        end = ph[i + 1]['start'] if i + 1 < len(ph) else float(phases.get('total', p['start'] + p['dur']))
        out[p['name']] = (float(p['start']), float(end), float(p['dur']))
    return out


# ------------------------------------------------------------------------------------------------ check
def _sentences(s):
    """How many sentences a start:/end: line carries (a terminal . ! ? followed by a space and a capital)."""
    s = QUOTES.sub('"x"', (s or '').strip())        # quoted on-screen strings carry their own punctuation
    if not s:
        return 0
    return 1 + len(re.findall(r'[.!?]\s+(?=[A-Z"“])', s))


def load_approvals(path):
    """out/review/approvals.json -> {beat: {'start': bool, 'end': bool, 'by': str, 'at': str}}; {} when absent/unreadable."""
    d = load_json(path)
    out = {}
    for a in (d or {}).get('approvals', []) if isinstance(d, dict) else []:
        try:
            n = int(a.get('beat'))
        except (TypeError, ValueError):
            continue
        cur = out.setdefault(n, {'start': False, 'end': False})
        for k in ('start', 'end'):
            if a.get(k) is True:
                cur[k] = True
            elif a.get(k) is False:
                cur[k] = False
        for k in ('by', 'at'):
            if a.get(k):
                cur[k] = a[k]
    return out


def load_holds(timeline_path):
    """out/timeline.json → [{id, t0, t1, hold}] (holds[] + shots[] carrying `hold`); [] when absent."""
    tl = load_json(timeline_path) or {}
    rows = [dict(h) for h in tl.get('holds', []) or [] if isinstance(h, dict) and all(isinstance(h.get(k), (int, float)) for k in ('t0', 't1', 'hold'))]
    seen = {(r['t0'], r['t1']) for r in rows}
    rows += [{'id': sh.get('clip') or 'shot', 't0': sh['t0'], 't1': sh['t1'], 'hold': sh['hold']} for sh in tl.get('shots', []) or []
             if isinstance(sh.get('hold'), (int, float)) and sh.get('t0') is not None and sh.get('t1') is not None and (sh['t0'], sh['t1']) not in seen]
    return rows


def check(man, phases=None, clips=None, qa=None, brief=None, authored_text='', autonomous=False, build=False,
          pace=None, approvals=None, holds=None, pair_beats=None):
    """Return (errors, warnings, rows). rows = per-beat table for the plan echo (number, name, span, real, why).
    approvals: {beat: {'start','end'}} from load_approvals(); when given (not None) and build=True, every beat's END
    frame must be approved."""
    E, W, rows = [], [], []
    qa = qa or {}
    pace = pace or qa.get('pace') or {}
    warn_lo, warn_hi = pace.get('warn', [1.8, 3.0])
    fail_hi, max_words = pace.get('fail', 3.4), pace.get('max_words', 24)
    g, beats = man['globals'], man['beats']
    W.extend(man['warnings'])
    if not beats:
        return ['no beats found (headings look like "## Beat 01 — Name (t0–t1, ~dur s)")'], W, rows
    if not g.get('message'):
        E.append('frontmatter: message is empty — the film has to say one thing')
    target = _seconds(g.get('duration')) if g.get('duration') not in (None, '') else None

    # --- review loop: version and lock
    ver = g.get('version', 1)
    try:
        ver = int(str(ver).lstrip('vV'))
    except ValueError:
        W.append('frontmatter: version "%s" is not a number' % g.get('version')); ver = None
    nchg = len(man['sections']['changes'])
    if ver is not None and ver != nchg + 1:
        E.append('version is v%s but there are %d "## Changes from" blocks (expected v%d)' % (ver, nchg, nchg + 1))
    if not man['sections']['locked'] and not autonomous:
        E.append('no "## Locked" section — build only after the lock (or pass --autonomous for a drive-it run)')

    # --- arithmetic
    total_planned = 0.0
    for i, b in enumerate(beats):
        if b['t0'] is None or b['t1'] is None:
            E.append('beat %02d: heading needs absolute times "(t0–t1, ~dur s)"' % b['number']); continue
        d = b['t1'] - b['t0']
        if b['dur'] is not None and abs(b['dur'] - d) > 0.15:
            E.append('beat %02d: ~%.1f s stated but %.1f–%.1f is %.1f s' % (b['number'], b['dur'], b['t0'], b['t1'], d))
        if i and beats[i - 1]['t1'] is not None and abs(beats[i - 1]['t1'] - b['t0']) > 0.15:
            E.append('beat %02d starts at %.1f but beat %02d ends at %.1f (beats must be contiguous)'
                     % (b['number'], b['t0'], beats[i - 1]['number'], beats[i - 1]['t1']))
        total_planned = max(total_planned, b['t1'])
        if b['real'] == 'recreated' and not (1.5 <= d <= 9.0):
            W.append('beat %02d: recreated beat runs %.1f s (measured 1.5–3.5 s for promo cards, up to ~9 s for a two-reveal read)' % (b['number'], d))
        if b['real'] == 'recorded' and not (4.0 <= d <= 20.0):
            W.append('beat %02d: product beat runs %.1f s (establish 0.9–1.6 → push 1.0–1.4 → hold 2–2.5 wants 4–20 s)' % (b['number'], d))
    if target and total_planned:
        drift = abs(total_planned - target) / target
        (E if drift > 0.10 else W if drift > 0.05 else []).append(
            'beats sum to %.1f s, frontmatter duration is %.0f s (%.0f %% drift)' % (total_planned, target, drift * 100))

    # --- per-beat fields
    breathers, hero_texts, numbers = [], {}, {b['number'] for b in beats}
    for b in beats:
        f, n = b['fields'], b['number']
        if not b['real']:
            E.append('beat %02d: real: recorded|recreated|placeholder is required' % n)
        for key in ('why', 'constraint', 'screen', 'seam'):
            if not f.get(key):
                E.append('beat %02d: "%s:" is required' % (n, key))
        if not f.get('vo') and not f.get('silent'):
            E.append('beat %02d: "vo:" is required (write "vo: silent" for a beat the visual carries alone)' % n)
        if f.get('why') and not any(w in norm(g.get('message', '')) for w in norm(f['why']).split() if w not in STOP and len(w) > 3):
            W.append('beat %02d: why: shares no content word with the message — trace it or cut the beat' % n)
        # first / last frame: the storyboard is a contract on where a beat opens and where it leaves the viewer
        for key in ('start', 'end'):
            v = f.get(key)
            if v and _sentences(v) > 1:
                W.append('beat %02d: %s: is %d sentences — one sentence: what the viewer sees at that instant' % (n, key, _sentences(v)))
            if v and len(words(v)) > 40:
                W.append('beat %02d: %s: runs %d words — name the elements and their state, not the motion between' % (n, key, len(words(v))))
        if b['real'] == 'recreated' and not f.get('end'):
            (E if build else W).append('beat %02d: recreated beats need an "end:" line (the last frame, one sentence) — the next cut lands on it%s'
                                       % (n, '' if build else ' (fails at --build)'))
        if b['real'] in ('recreated', 'recorded') and not f.get('start'):
            W.append('beat %02d: no "start:" line — say what is on screen on the first frame' % n)
        # move first, then hold (gates/hold_gate.py): a recreated beat declares the fraction after which only the background moves,
        # or writes a waiver with its reason — `hold: none (…)`; a footage match-cut must not carry one
        hv = (f.get('hold') or '').strip()
        if b['real'] == 'recreated':
            if not hv:
                W.append('beat %02d: recreated beat has no "hold:" (fraction, e.g. 0.6 — or "none (reason)"); hold_gate requires one at QA' % n)
            elif re.fullmatch(r'0?\.\d+|1(\.0+)?', hv.split()[0]):
                hf = float(hv.split()[0])
                if not (0.3 <= hf <= 0.95):
                    E.append('beat %02d: hold: %.2f is outside 0.3–0.95' % (n, hf))
                # the plan and the scene must say one number: FILM.holds / shots.js hold (out/timeline.json) vs this line
                if holds is not None and b['t0'] is not None and b['t1'] is not None:
                    s0, e0 = b.get('actual') or (b['t0'], b['t1'])
                    mid = (s0 + e0) / 2.0
                    row = next((r for r in holds if float(r['t0']) <= mid < float(r['t1'])), None)
                    if row is None:
                        W.append('beat %02d: hold: %.2f in the plan but no FILM.holds / shots.js hold row covers %.1f–%.1f s in out/timeline.json (hold_gate fails at QA)' % (n, hf, s0, e0))
                    elif abs(float(row['hold']) - hf) > 0.05:
                        E.append('beat %02d: hold: %.2f in the plan but the scene declares %.2f (%s in out/timeline.json) — one number, change the one that is wrong' % (n, hf, float(row['hold']), row.get('id', '?')))
            elif holds is not None and hv.lower().startswith(('none', 'no')) and b['t0'] is not None and b['t1'] is not None:
                s0, e0 = b.get('actual') or (b['t0'], b['t1'])
                mid = (s0 + e0) / 2.0
                row = next((r for r in holds if float(r['t0']) <= mid < float(r['t1'])), None)
                if row is not None:
                    W.append('beat %02d waives its hold but the scene declares one (%s, %.2f) — drop the waiver or the row' % (n, row.get('id', '?'), float(row['hold'])))
            elif not hv.lower().startswith(('none', 'no')):
                W.append('beat %02d: hold: "%s" is neither a fraction nor "none (reason)"' % (n, hv[:30]))
            elif '(' not in hv and len(hv.split()) < 3:
                W.append('beat %02d: hold: none — say why in brackets; the gate prints the reason' % n)
        elif b['real'] == 'recorded' and hv and re.search(r'match', f.get('seam', ''), re.I):
            E.append('beat %02d: hold: on a footage match-cut — motion must carry through that cut (hold is for recreated beats)' % n)
        if approvals is not None and build and (pair_beats is None or n in pair_beats):
            ap = approvals.get(n) or {}
            if not ap.get('end'):
                E.append('beat %02d: END frame not approved (approvals.json) — approve it in the review pack or pass --no-require-approvals' % n)
        if b['real'] == 'recreated':
            mo = (f.get('motion') or '').upper()
            if not f.get('motion'):
                E.append('beat %02d: recreated beats need a "motion:" line (VERB + ease + duration)' % n)
            else:
                if not any(re.search(r'\b%s\b' % v, mo) for v in VERBS):
                    E.append('beat %02d: motion: names no verb (%s …) — an element without a verb is not designed' % (n, ', '.join(VERBS[:6])))
                if not re.search(r'\d+(\.\d+)?\s*s\b', mo, re.I):
                    W.append('beat %02d: motion: has no duration (e.g. "0.5 s")' % n)
                if not re.search(r'(SINE|POWER|EXPO|CUBIC|LINEAR|EASE)', mo):
                    W.append('beat %02d: motion: has no ease (sine-out for entrances, sine-in-out for moves)' % n)
                lazy = [v for v in LAZY_VERBS if re.search(r'\b%s\b' % v, mo)]
                if lazy and not str(f.get('breather', '')).lower().startswith('y'):
                    W.append('beat %02d: motion: uses %s — ambient drift reads as a screensaver; reveal on words instead' % (n, '/'.join(lazy)))
            if not b['quotes']:
                W.append('beat %02d: recreated beat quotes no on-screen words — every word that renders must be in quotes' % n)
        if b['real'] == 'recorded':
            if not f.get('clip'):
                E.append('beat %02d: recorded beats must name the clip (clip: <id in clips.json>)' % n)
            elif clips is not None and f['clip'] not in {c.get('name') for c in clips}:
                E.append('beat %02d: clip "%s" is not in clips.json' % (n, f['clip']))
            if not f.get('camera'):
                W.append('beat %02d: recorded beat has no camera: line (establish → push → hold)' % n)
        if b['real'] == 'placeholder' and build:
            allowed = str((brief or {}).get('placeholders', 'no')).lower().startswith('y')
            (W if allowed else E).append('beat %02d is a placeholder%s' % (n, ' (allowed by BRIEF.md)' if allowed else ' — supply the capture or cut it before building'))
        if str(f.get('breather', '')).lower().startswith(('y', 'true')):
            breathers.append(n)
        if f.get('callback'):
            m = re.search(r'\d+', f['callback'])
            tgt = int(m.group()) if m else None
            if tgt not in numbers:
                E.append('beat %02d: callback: %s names a beat that does not exist' % (n, f['callback']))
            elif tgt >= n:
                E.append('beat %02d: callback: %02d must point backwards (plant first, return later)' % (n, tgt))
        if f.get('hero_prop') and f['hero_prop'].strip('—-– ') :
            q = quotes(f['hero_prop'])
            if q:
                hero_texts.setdefault(norm(q[0]), []).append(n)
        if len(b['quotes']) > qa.get('max_text_blocks', 4):
            W.append('beat %02d: %d on-screen strings at once (budget %d — fewer words, larger type)' % (n, len(b['quotes']), qa.get('max_text_blocks', 4)))
        for q in b['quotes']:
            if len(words(q)) > 9:
                W.append('beat %02d: on-screen string "%s…" is %d words — motion-graphics copy is a hero word, a stat, a one-word emphasis' % (n, q[:28], len(words(q))))
            if len(words(q)) >= 8 and f.get('vo') and norm(q) in norm(f['vo']):
                W.append('beat %02d: "%s…" is a narration sentence on screen — captions already print it (double-print)' % (n, q[:28]))
        if b['real'] == 'recreated' and build and authored_text:
            for q in b['quotes']:
                if norm(q) not in norm(authored_text):
                    E.append('beat %02d: on-screen string "%s" is not in the authored scene/shots files' % (n, q))
        # TTS spelling (skip verbatim beats: the typed question must stay word for word)
        if f.get('vo') and not str(f.get('verbatim', '')).lower().startswith('y'):
            for pat, hint in TTS_RULES:
                for m in re.finditer(pat, f['vo']):
                    if m.group().upper() in set(qa.get('tts_ok', ['OK', 'TV', 'US', 'UK', 'AI'])):
                        continue
                    W.append('beat %02d: vo "%s" — %s' % (n, m.group(), hint))
                    break
        rows.append((n, b['title'], '%s–%s' % (b['t0'], b['t1']), b['real'], f.get('why', '')))
    if len(breathers) != 1:
        E.append('exactly one beat must be the breather (breather: yes) — found %s' % (breathers or 'none'))
    if len(hero_texts) > 1:
        E.append('the hero prop is quoted differently across beats: %s' % '; '.join('"%s" in %s' % (k[:40], v) for k, v in hero_texts.items()))

    # --- value-first spine: hook vocabulary and message by beat 2
    hooks = [b for b in beats[:2] if b['real'] != 'recorded']
    pats = qa.get('hook_banned_tokens', HOOK_BANNED)
    for b in hooks:
        txt = (b['fields'].get('vo', '') + ' ' + b['fields'].get('screen', ''))
        for p in pats:
            m = re.search(p, txt)
            if m and not str(b['fields'].get('verbatim', '')).lower().startswith('y'):
                E.append('beat %02d (hook): "%s" is subject-internal vocabulary — the hook speaks outcome language' % (b['number'], m.group()))
                break
        if re.match(r'\s*(welcome to|introducing)\b', b['fields'].get('vo', ''), re.I):
            E.append('beat %02d: "Welcome to / Introducing" openings restart — open on tension, a question or a contrast' % b['number'])
    types = [(b['number'], (b['fields'].get('type') or '').lower()) for b in beats]
    if not any(t in ('value', 'claim', 'promise', 'thesis', 'message') for n, t in types[:2]):
        W.append('no beat in the first two is tagged type: value|claim — the value claim lands by beat 2, everything after is evidence')
    if types and all(t not in ('value', 'claim', 'promise', 'thesis', 'message') for n, t in types):
        W.append('delete-test: no value beat at all — a film that still works without one is a feature tour')

    # --- narration: phases.json arithmetic + pace
    if phases:
        spans = phase_spans(phases)
        seen = set()
        for b in beats:
            ph = b['fields'].get('phase') or (phases['phases'][b['index']]['name'] if b['index'] < len(phases['phases']) else None)
            if ph not in spans:
                E.append('beat %02d: phase "%s" is not in phases.json' % (b['number'], ph)); continue
            seen.add(ph)
            s, e, d = spans[ph]
            b['actual'] = (round(s, 2), round(e, 2))
            if b['t0'] is not None:
                plan = b['t1'] - b['t0']
                drift = abs((e - s) - plan) / max(plan, 0.1)
                if drift > 0.10 and abs((e - s) - plan) > 0.5:
                    E.append('beat %02d: planned %.1f s, narration gives %.1f s (%.0f %% drift) — re-plan or re-write' % (b['number'], plan, e - s, drift * 100))
                elif drift > 0.05:
                    W.append('beat %02d: planned %.1f s vs %.1f s measured' % (b['number'], plan, e - s))
            nw = len(words(b['fields'].get('vo', '')))
            if nw and d > 0:
                r = nw / d
                if r > fail_hi:
                    E.append('beat %02d: %d words in %.1f s = %.1f w/s — too fast to follow (fail > %.1f)' % (b['number'], nw, d, r, fail_hi))
                elif not (warn_lo <= r <= warn_hi):
                    W.append('beat %02d: %.1f w/s (%d words / %.1f s; natural 1.8–3.0)' % (b['number'], r, nw, d))
                if nw > max_words:
                    W.append('beat %02d: %d spoken words — 1–2 sentences, 6–20 words per beat' % (b['number'], nw))
        for name in spans:
            if name not in seen:
                E.append('phase "%s" has no beat — every phase of the narration is planned' % name)
        tot = float(phases.get('total', 0))
        if target and tot and abs(tot - target) / target > 0.10:
            E.append('narration total %.1f s vs storyboard duration %.0f s (> 10 %%) — update the plan, the clock does not move' % (tot, target))
    return E, W, rows


# ------------------------------------------------------------------------------------------------ sheet (storyboard.html)
def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def load_design(path):
    tok = dict(DEFAULT_TOKENS)
    if not path or not os.path.exists(path):
        return tok, {}
    with open(path, encoding='utf-8') as fh:
        fm, _, _ = frontmatter(fh.read())
    for k, v in (fm.get('colors') or {}).items():
        if isinstance(v, str):
            tok[k] = v
    for role, spec in (fm.get('type') or {}).items():
        if isinstance(spec, dict) and spec.get('family'):
            tok[role] = spec['family']
    return tok, fm


def _fit(q):
    """Fit-to-measure: ≤ 3 words → h1, 4–6 → h2, 7+ → h3."""
    n = len(words(q))
    return 'h1' if n <= 3 else 'h2' if n <= 6 else 'h3'


def _rel(path, sheet_dir):
    return os.path.relpath(path, sheet_dir).replace('\\', '/')


def sheet(man, out_path, project, design=None, truth_dir=None, timeline=None, broll='broll', mobile=False):
    """Write the script-free, asset-free review sheet. Recreated beats are drawn as HTML sketches from their
    quoted on-screen strings; recorded beats show broll/<clip>/median.jpg (relative) with the establish→push
    frame when the beat gives push: [x, y, w, h] in source px; truth frames (out/storyboard/NN.jpg) win."""
    tok, dfm = load_design(design)
    g, beats = man['globals'], man['beats']
    sheet_dir = os.path.dirname(os.path.abspath(out_path)); os.makedirs(sheet_dir, exist_ok=True)
    total = max([b['t1'] or 0 for b in beats] + [0])
    actual = max([b.get('actual', (0, 0))[1] for b in beats] + [0])
    ver = g.get('version', 1)
    head = ['<header><h1>%s <span class="v">v%s%s</span></h1>' % (_esc(g.get('title', 'Storyboard')), _esc(ver), ' · truth pass' if truth_dir else ''),
            '<p class="dek">%s</p>' % _esc(g.get('message', '')),
            '<p class="tag">%s · %s · %d beats%s · %s</p>' % (_esc(g.get('format', '1920x1080')), '%.1f s planned' % total,
                                                              len(beats), (' · %.1f s actual' % actual) if actual else '',
                                                              _esc(g.get('arc', '')))]
    for title, items in (('Changes', [n for c in man['sections']['changes'] for n in ['<b>%s</b>' % _esc(c['from'])] + [_esc(x) for x in c['notes']]]),
                         ('Still open', [_esc(x) for x in man['sections']['still_open']]),
                         ('Locked', [_esc(x) for x in man['sections']['locked']])):
        if items:
            head.append('<div class="notes"><h3>%s</h3><ul>%s</ul></div>' % (title, ''.join('<li>%s</li>' % x for x in items)))
    head.append('</header>')
    cells, act = [], None
    for b in beats:
        f, n = b['fields'], b['number']
        if f.get('act') and f['act'] != act:
            act = f['act']; cells.append('<div class="act">%s</div>' % _esc(act))
        badge = {'recorded': 'REAL', 'recreated': 'RECREATED', 'placeholder': 'PLACEHOLDER'}.get(b['real'], '?')
        img = None
        if truth_dir and os.path.exists(os.path.join(truth_dir, '%02d.jpg' % n)):
            img = os.path.join(truth_dir, '%02d.jpg' % n)
        elif f.get('sketch') and os.path.exists(os.path.join(project, f['sketch'])):
            img = os.path.join(project, f['sketch'])
        elif b['real'] == 'recorded' and f.get('clip') and os.path.exists(os.path.join(project, broll, f['clip'], 'median.jpg')):
            img = os.path.join(project, broll, f['clip'], 'median.jpg')
        inner = ''
        if img:
            inner = '<img src="%s" alt="">' % _esc(_rel(img, sheet_dir))
        elif b['real'] == 'recorded':
            inner = '<div class="plate"><span>REAL · clip %s</span></div>' % _esc(f.get('clip', '?'))
        elif b['real'] == 'placeholder':
            inner = '<div class="plate ph"><span>— placeholder —</span><small>%s</small></div>' % _esc(f.get('screen', '')[:90])
        else:
            qs = b['quotes'] or ['— figure —']
            inner = '<div class="sk">' + ''.join('<%s>%s</%s>' % (_fit(q) if i == 0 else 'p', _esc(q), _fit(q) if i == 0 else 'p')
                                                   for i, q in enumerate(qs[:4])) + '</div>'
        if f.get('push') and b['real'] == 'recorded':
            m = re.findall(r'\d+(?:\.\d+)?', f['push'])
            if len(m) >= 4:
                x, y, w, h = (float(v) for v in m[:4])
                # full original screen (outer box) → push target (dashed): the "full screen, then zoom" rule, in source px
                inner += ('<svg class="push" viewBox="0 0 1920 1080" preserveAspectRatio="none"><rect x="8" y="8" width="1904" height="1064"/>'
                          '<rect class="tgt" x="%.0f" y="%.0f" width="%.0f" height="%.0f"/></svg>' % (x, y, w, h))
        span = b.get('actual') or (b['t0'], b['t1'])
        # bold lead: what moves first — the first VERB clause of motion:, or the first camera segment
        mo = f.get('motion') or ''
        vm = re.search(r'^(.*?\b(?:%s)\b[^,;]*)' % '|'.join(VERBS), mo, re.I)
        first = (vm.group(1) if vm else (f.get('camera') or mo).split('→')[0]).strip()[:80]
        frames = ''.join('<p class="se %s"><b>%s</b> %s</p>' % (k, k.upper(), _esc(f[k])) for k in ('start', 'end') if f.get(k))
        cells.append(
            '<figure class="cell" id="frame-%02d"><div class="frame" tabindex="0">%s<span class="badge %s">%s</span><i class="keepout"></i></div>'
            '<figcaption><div class="lab"><span>%02d · %s</span><span>%s · %s–%s</span></div>'
            '<p class="note"><b>%s</b> %s</p>%s<div class="chips"><span class="chip">seam: %s</span>%s</div></figcaption></figure>'
            % (n, inner, b['real'] or 'unknown', badge, n, _esc(b['title'].upper()), _esc(f.get('phase', 'beat')), span[0], span[1],
               _esc(first), _esc(f.get('why', '')), frames, _esc(f.get('seam', '—')),
               ('<span class="chip">%s</span>' % _esc(f['caption'])) if f.get('caption') else ''))
    seams = ''.join('<span>%02d</span><em>%s</em>' % (b['number'], _esc(re.split(r'[,(;—]', b['fields'].get('seam') or '→')[0].strip()[:26])) for b in beats)
    swatches = ''.join('<span class="sw" style="background:%s"><small>%s</small></span>' % (_esc(tok[k]), k) for k in ('ground', 'ink', 'accent', 'muted') if k in tok)
    bans = [x for x in man['sections']['direction'] if re.match(r'(no|never|ban|negative)\b', x, re.I)]
    cells.append('<figure class="cell wide" id="seam-map"><div class="strip">%s</div><figcaption><div class="lab"><span>SEAM MAP</span><span>one direction rule for the whole film</span></div></figcaption></figure>' % seams)
    cells.append('<figure class="cell" id="tokens"><div class="tokens">%s<p class="type">display · %s<br>sans · %s<br>mono · %s</p>%s</div>'
                 '<figcaption><div class="lab"><span>TOKENS</span><span>%s</span></div></figcaption></figure>'
                 % (swatches, _esc(tok.get('display', '')), _esc(tok.get('sans', '')), _esc(tok.get('mono', '')),
                    ('<ul class="bans">%s</ul>' % ''.join('<li>%s</li>' % _esc(x[:80]) for x in bans[:8])) if bans else '',
                    _esc(os.path.basename(design) if design else 'default tokens')))
    css = '''
:root{--ground:%(ground)s;--ink:%(ink)s;--accent:%(accent)s;--muted:%(muted)s;--display:%(display)s;--sans:%(sans)s;--mono:%(mono)s}
html,body{margin:0;background:#f4f1ea;color:#1b1b1b;font:15px/1.45 var(--sans)}
header{padding:28px 36px 12px}header h1{font:400 32px/1.1 var(--display);margin:0}header .v{font:600 13px var(--mono);color:var(--accent);margin-left:10px;vertical-align:middle}
.dek{font-size:17px;margin:8px 0 2px}.tag{font:12px var(--mono);color:#666;margin:0 0 10px}
.notes{display:inline-block;vertical-align:top;margin:6px 24px 6px 0;max-width:420px}.notes h3{font:600 12px var(--mono);margin:0 0 4px;letter-spacing:.08em}.notes ul{margin:0;padding-left:18px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px 20px;padding:12px 36px 40px}
.act{grid-column:1/-1;font:600 12px var(--mono);letter-spacing:.14em;color:#555;border-top:2px solid #1b1b1b;padding-top:8px;margin-top:8px}
.cell{margin:0;container-type:inline-size}.cell.wide{grid-column:1/-1}
.frame{position:relative;aspect-ratio:16/9;background:var(--ground);color:var(--ink);overflow:hidden;border:2px solid #1b1b1b}
.frame img{position:absolute;inset:0;width:100%%;height:100%%;object-fit:cover;display:block}
.sk{position:absolute;left:7cqw;top:12cqw;right:7cqw;bottom:17%%;display:flex;flex-direction:column;justify-content:center;gap:1.4cqw}
.sk h1{font:400 5cqw/1.1 var(--display);margin:0;letter-spacing:-.02em;max-width:78%%}.sk h2{font:400 3.5cqw/1.15 var(--display);margin:0;max-width:78%%}.sk h3{font:400 2.6cqw/1.25 var(--sans);margin:0;max-width:78%%}
.sk p{font:1.6cqw/1.3 var(--sans);margin:0;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
.sk p:nth-child(2){color:var(--ink);font-size:2cqw;text-transform:none;letter-spacing:0}
.plate{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#d9d9d2;color:#333;font:600 2.2cqw var(--mono)}
.plate.ph{background:repeating-linear-gradient(45deg,#e8e4da 0 12px,#d9d4c8 12px 24px)}.plate small{font:1.6cqw var(--sans);margin-top:1cqw;padding:0 6cqw;text-align:center}
.push{position:absolute;inset:0;width:100%%;height:100%%;fill:none;stroke:var(--accent);stroke-width:10}.push .tgt{stroke-dasharray:28 18}
.badge{position:absolute;top:2.2cqw;right:2.2cqw;font:600 1.5cqw/1 var(--mono);letter-spacing:.1em;padding:.8cqw 1.2cqw;border:1px solid}
.badge.recorded{background:#1b1b1b;color:#fff}.badge.recreated{background:var(--accent);color:#fff;border-color:var(--accent)}.badge.placeholder{background:#fff;color:#1b1b1b}
.keepout{position:absolute;left:0;right:0;top:83%%;border-top:1px dashed rgba(255,255,255,.35)}
figcaption{padding:8px 2px 0}.lab{display:flex;justify-content:space-between;font:600 12px var(--mono);letter-spacing:.06em}
.note{margin:6px 0 4px;font-size:13.5px}.chips .chip{display:inline-block;font:11px var(--mono);border:1px solid #999;padding:2px 7px;margin:2px 4px 0 0;border-radius:2px}
.strip{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:14px;border:2px solid #1b1b1b;background:#fff;font:12px var(--mono)}.strip span{font-weight:700}.strip em{font-style:normal;color:#555}.strip em:after{content:" →"}
.tokens{aspect-ratio:16/9;border:2px solid #1b1b1b;background:#fff;padding:4cqw 5cqw;box-sizing:border-box;font:2.4cqw/1.4 var(--mono)}
.sw{display:inline-block;width:16cqw;height:10cqw;margin:0 1.6cqw 1.6cqw 0;border:1px solid #999;vertical-align:top;position:relative}.sw small{position:absolute;left:.8cqw;bottom:.6cqw;font-size:1.8cqw;color:#fff;mix-blend-mode:difference}
.type{margin:1cqw 0}.bans{margin:1cqw 0 0;padding-left:3cqw;font-size:2cqw;color:#555}
.se{margin:4px 0;font-size:12.5px;color:#333}.se b{font:600 10px var(--mono);letter-spacing:.1em;margin-right:6px;color:#555}.se.end b{color:var(--accent)}
''' % tok
    if mobile:
        # phone review: one column, type that reads on a 390 px screen, and a tap on a frame zooms it edge to edge (CSS only:
        # the frame takes focus; a tap elsewhere or Escape drops it) — no scripts, still offline
        css += '''
@media (max-width:480px){
  header{padding:18px 16px 8px}header h1{font-size:24px}.grid{grid-template-columns:1fr;gap:18px;padding:10px 14px 30px}
  .notes{display:block;max-width:none;margin:6px 0}.note{font-size:15px}.se{font-size:14px}.lab{font-size:12px}
  .frame{cursor:zoom-in}.frame:focus{position:fixed;left:0;right:0;top:50%;transform:translateY(-50%);z-index:9;aspect-ratio:16/9;border-width:0;outline:0;cursor:zoom-out;box-shadow:0 0 0 100vmax rgba(0,0,0,.82)}
  .frame:focus .badge{font-size:11px;padding:4px 7px}
}'''
    html = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>%s — storyboard v%s</title><style>%s</style></head>'
            '<body>%s<main class="grid">%s</main><footer style="padding:0 36px 30px;font:12px var(--mono);color:#777">'
            'generated by tools/storyboard.py from STORYBOARD.md%s — never hand-edit the sheet; it is not a source of timing truth.</footer></body></html>'
            % (_esc(g.get('title', 'Storyboard')), _esc(ver), css, ''.join(head), ''.join(cells),
               ' + vo/<name>_phases.json' if actual else ''))
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return out_path


def truth_frames(man, film, out_dir, width=480):
    """Pull one frame per beat midpoint from the finished film (ffmpeg -ss) into out_dir/NN.jpg."""
    os.makedirs(out_dir, exist_ok=True)
    for b in man['beats']:
        s, e = b.get('actual') or (b['t0'], b['t1'])
        if s is None or e is None:
            continue
        mid = (s + e) / 2.0
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', '%.3f' % mid, '-i', film, '-frames:v', '1',
                        '-vf', 'scale=%d:-2' % width, os.path.join(out_dir, '%02d.jpg' % b['number'])], check=False)
    return out_dir


# ------------------------------------------------------------------------------------------------ CLI
def _project_paths(sb_path, args):
    proj = os.path.dirname(os.path.abspath(sb_path))
    film = load_json(os.path.join(proj, 'film.json')) or {}
    name = film.get('name', 'film')
    return proj, name, film


def _opt(args, flag, default=None):
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def main(argv):
    if '--selftest' in argv:
        return selftest()
    if not argv or argv[0] not in ('parse', 'check', 'sheet', 'set'):
        print(__doc__); return 2
    cmd, args = argv[0], argv[1:]
    sb = next((a for a in args if not a.startswith('--') and a.lower().endswith('.md')), 'STORYBOARD.md')
    if not os.path.exists(sb):
        print('missing ' + sb); return 2
    text = open(sb, encoding='utf-8').read()
    man = parse(text)
    proj, name, film = _project_paths(sb, args)
    if cmd == 'parse':
        if '--json' in args:
            print(json.dumps(man, indent=1, ensure_ascii=False))
        else:
            print('%s v%s — %d beats, %d warnings' % (man['globals'].get('title', sb), man['globals'].get('version', 1), len(man['beats']), len(man['warnings'])))
            for b in man['beats']:
                print('  %02d %-28s %6s–%-6s %-11s %s' % (b['number'], b['title'][:28], b['t0'], b['t1'], b['real'], (b['fields'].get('why') or '')[:60]))
            for w in man['warnings']:
                print('  warn: ' + w)
        return 0
    if cmd == 'set':
        pos = [a for a in args if not a.startswith('--')]
        n, key, value = int(pos[1]), pos[2], ' '.join(pos[3:])
        open(sb, 'w', encoding='utf-8').write(set_field(text, n, key, value))
        print('beat %02d: %s = %s' % (n, key, value)); return 0
    phases = load_json(_opt(args, '--phases', os.path.join(proj, 'vo', name + '_phases.json')))
    if cmd == 'check':
        clips = load_json(_opt(args, '--clips', os.path.join(proj, 'clips.json')))
        qa = load_json(_opt(args, '--qa', os.path.join(proj, 'qa.json'))) or {}
        brief = {}
        bp = _opt(args, '--brief', os.path.join(proj, 'BRIEF.md'))
        if os.path.exists(bp):
            brief = frontmatter(open(bp, encoding='utf-8').read())[0]
        authored = ''
        for f in qa.get('authored', ['scenes/film.html', 'scenes/shots.js']):
            p = os.path.join(proj, f)
            if os.path.exists(p):
                authored += strip_code_comments(open(p, encoding='utf-8').read())
        approvals = None
        ap_path = os.path.join(proj, 'out', 'review', 'approvals.json')
        if '--require-approvals' in args:
            i = args.index('--require-approvals')
            if i + 1 < len(args) and not args[i + 1].startswith('--') and args[i + 1].lower().endswith('.json'):
                ap_path = args[i + 1]
            approvals = load_approvals(ap_path)
        elif '--no-require-approvals' not in args and os.path.exists(ap_path):
            approvals = load_approvals(ap_path)            # default on once the review pack has written approvals
        tl_path = _opt(args, '--timeline', os.path.join(proj, 'out', 'timeline.json'))
        holds = load_holds(tl_path) if os.path.exists(tl_path) else None
        pair_beats = None
        if approvals is not None:
            try:
                import review_pack as RP                      # the beats that own an END frame (a shared segment gives it to its last beat)
                pr = RP.read_pairs(proj, man['beats'])
                if pr is not None:
                    pair_beats = {n for n, v in pr.items() if n != 'unmapped' and v.get('end')}
            except Exception:
                pair_beats = None
        E, W, rows = check(man, phases=phases, clips=clips, qa=qa, brief=brief, authored_text=authored,
                           autonomous='--autonomous' in args, build='--build' in args, approvals=approvals, holds=holds, pair_beats=pair_beats)
        if approvals is not None and '--build' in args:
            print('approvals  %s (%d beats, %d END approved)' % (ap_path, len(approvals), sum(1 for a in approvals.values() if a.get('end'))))
        print('STORYBOARD  %s v%s  (%d beats%s)' % (sb, man['globals'].get('version', 1), len(man['beats']), ', narration measured' if phases else ', no phases.json yet'))
        print('This film tells %s that %s' % (man['globals'].get('audience', '[audience]'), man['globals'].get('message', '[message]')))
        for r in rows:
            print('  %02d  %-26s %-12s %-11s %s' % (r[0], r[1][:26], r[2], r[3], r[4][:58]))
        for w in W:
            print('  WARN  ' + w)
        for e in E:
            print('  FAIL  ' + e)
        print('\n%s  (%d errors, %d warnings)' % ('STORYBOARD OK' if not E else 'STORYBOARD FAILED', len(E), len(W)))
        return 1 if E else 0
    if cmd == 'sheet':
        out = _opt(args, '--out', os.path.join(proj, 'out', 'storyboard.html'))
        design = _opt(args, '--design', os.path.join(proj, 'design.md'))
        truth_dir = None
        if phases:
            check(man, phases=phases, autonomous=True)              # fills beat['actual'] from the clock
        if '--truth' in args:
            filmp = _opt(args, '--film', os.path.join(proj, film.get('output', 'out/%s.mp4' % name)))
            if not os.path.exists(filmp):
                print('missing film ' + filmp); return 2
            truth_dir = truth_frames(man, filmp, os.path.join(os.path.dirname(os.path.abspath(out)), 'storyboard'))
        p = sheet(man, out, proj, design=design if os.path.exists(design) else None, truth_dir=truth_dir, mobile='--mobile' in args)
        print('wrote ' + p + '  (open it from file://; no scripts, no external assets)')
        return 0


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    import tempfile, shutil
    tpl = os.path.join(TEMPLATES, 'STORYBOARD.example.md')
    text = open(tpl, encoding='utf-8').read()
    man = parse(text)
    ok = True

    def t(cond, label):
        nonlocal ok
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', label)); ok = ok and bool(cond)

    t(len(man['beats']) == 6, 'parse: 6 beats in the template')
    t(man['beats'][0]['t0'] == 0.0 and man['beats'][-1]['t1'] == 35.4, 'parse: heading arithmetic read (0.0 … 35.4)')
    t(man['beats'][3]['fields'].get('verbatim', '').startswith('y'), 'parse: alias/field handling (verbatim on beat 04)')
    t(man['sections']['locked'] and man['globals'].get('version') == 1, 'parse: ## Locked + version')
    # synthetic narration clock (≈ 2.5 words/s + 0.45 s gap + 0.1 s pad) that matches the plan within 5 %
    # the clock follows the template's beats (7.4 / 6.2 / 8.2 / 4.7 / 4.8 / 4.1 s -> 35.4 s): each phase starts 0.45 s after its cut
    # and runs 0.4 s shorter than the beat, so a template edit must be mirrored here or the drift gate fails the selftest
    phases = {'total': 36.05, 'phases': [
        {'name': 'hook', 'start': 0.10, 'dur': 7.3}, {'name': 'title', 'start': 7.85, 'dur': 5.8},
        {'name': 'nb', 'start': 14.05, 'dur': 7.8}, {'name': 'ask', 'start': 22.25, 'dur': 4.3},
        {'name': 'answer', 'start': 26.95, 'dur': 4.4}, {'name': 'close', 'start': 31.75, 'dur': 4.0}]}
    clips = [{'name': 'nb'}, {'name': 'q'}, {'name': 'send'}, {'name': 'answer'}]
    E, W, rows = check(man, phases=phases, clips=clips, qa={}, brief={'placeholders': 'no'})
    for e in E:
        print('      unexpected: ' + e)
    t(not E, 'check: template passes with a matching clock (%d warnings)' % len(W))
    bad = set_field(text, 3, 'why', '')
    bad = set_field(bad, 6, 'callback', '07')
    bad = bad.replace('- breather: yes', '- breather: no')
    bad = bad.replace('## Locked', '## Nearly locked')
    E2, W2, _ = check(parse(bad), phases=phases, clips=clips)
    t(any('why' in e for e in E2), 'check: missing why: fails')
    t(any('callback' in e for e in E2), 'check: dangling callback fails')
    t(any('breather' in e for e in E2), 'check: no breather fails')
    t(any('Locked' in e for e in E2), 'check: missing lock fails (and --autonomous waives it: %s)' % (not any('Locked' in e for e in check(parse(bad), phases=phases, clips=clips, autonomous=True)[0])))
    slow = json.loads(json.dumps(phases)); slow['phases'][2]['dur'] = 3.0
    E3, _, _ = check(man, phases=slow, clips=clips, autonomous=True)
    t(any('w/s' in e for e in E3), 'check: 15 words in 3.0 s fails the pace gate (> 3.4 w/s)')
    drift = json.loads(json.dumps(phases)); drift['total'] = 40.0; drift['phases'][5]['dur'] = 12.0
    E4, _, _ = check(man, phases=drift, clips=clips, autonomous=True)
    t(any('drift' in e or '> 10' in e for e in E4), 'check: > 10 % drift against the clock fails')
    E5, _, _ = check(parse(text.replace('- real: recorded\n- clip: nb', '- real: placeholder\n- clip: nb')), phases=phases, clips=clips, build=True)
    t(any('placeholder' in e for e in E5), 'check --build: placeholder beat fails unless BRIEF allows it')
    t('- why: ' in set_field(text, 2, 'status', 'sketched') and 'status: sketched' in set_field(text, 2, 'status', 'sketched'), 'set_field: inserts a new bullet in place')
    # v5.1 first / last frame contract
    t(all(man['beats'][i]['fields'].get('end') for i in (0, 1, 5)) and man['beats'][0]['fields'].get('start'), 'parse: start:/end: read on the recreated beats')
    noend = set_field(text, 6, 'end', '')
    E6, W6, _ = check(parse(noend), phases=phases, clips=clips, autonomous=True)
    E7, _, _ = check(parse(noend), phases=phases, clips=clips, autonomous=True, build=True)
    t(not any('"end:"' in e for e in E6) and any('"end:"' in w for w in W6) and any('"end:"' in e for e in E7), 'check: recreated beat without end: warns, fails at --build')
    two = set_field(text, 2, 'end', 'The title sits. The caption sits below it.')
    t(any('2 sentences' in w for w in check(parse(two), phases=phases, clips=clips, autonomous=True)[1]), 'check: a two-sentence end: warns')
    aps = {1: {'start': True, 'end': True}, 2: {'end': True}, 3: {'end': True}, 4: {'end': True}, 5: {'end': True}}
    E8, _, _ = check(man, phases=phases, clips=clips, autonomous=True, build=True, approvals=aps)
    E9, _, _ = check(man, phases=phases, clips=clips, autonomous=True, build=True, approvals={**aps, 6: {'end': True}})
    t(any('beat 06: END frame not approved' in e for e in E8) and not any('approved' in e for e in E9), 'check --build: an unapproved END frame refuses the build; all approved passes')
    # hold: in the plan vs the scene's declared rows (out/timeline.json)
    H_ok = [{'id': 'close', 't0': 31.3, 't1': 39.0, 'hold': 0.55}]
    Eh, Wh, _ = check(man, phases=phases, clips=clips, autonomous=True, holds=H_ok)
    Eh2, _, _ = check(man, phases=phases, clips=clips, autonomous=True, holds=[{'id': 'close', 't0': 31.3, 't1': 39.0, 'hold': 0.7}])
    _, Wh3, _ = check(man, phases=phases, clips=clips, autonomous=True, holds=[])
    _, Wh4, _ = check(man, phases=phases, clips=clips, autonomous=True, holds=H_ok + [{'id': 'title', 't0': 0.0, 't1': 13.6, 'hold': 0.6}])
    t(not any('hold' in e for e in Eh) and any('the scene declares 0.70' in e for e in Eh2), 'check: hold: 0.55 vs scene 0.55 passes; vs 0.70 fails (> 0.05)')
    t(any('no FILM.holds' in w for w in Wh3) and any('waives its hold but the scene declares' in w for w in Wh4), 'check: a plan hold without a scene row warns; a waived beat with a scene row warns')
    tmpa = tempfile.mkdtemp(prefix='sb_ap_')
    try:
        apf = os.path.join(tmpa, 'approvals.json')
        json.dump({'pack': 'x', 'approvals': [{'beat': 3, 'end': True, 'by': 'R'}, {'beat': '4', 'start': True}, {'beat': 'zz'}]}, open(apf, 'w'))
        la = load_approvals(apf)
        t(la == {3: {'start': False, 'end': True, 'by': 'R'}, 4: {'start': True, 'end': False}}, 'load_approvals: tolerant reader (%s)' % la)
    finally:
        shutil.rmtree(tmpa, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix='sb_')
    try:
        out = os.path.join(tmp, 'out', 'storyboard.html')
        check(man, phases=phases, autonomous=True)
        sheet(man, out, tmp, design=os.path.join(TEMPLATES, 'design.example.md'))
        html = open(out, encoding='utf-8').read()
        t('<script' not in html and 'http' not in html.replace('http-equiv', ''), 'sheet: no scripts, no external assets')
        t(all('id="frame-%02d"' % i in html for i in range(1, 7)) and 'id="seam-map"' in html and 'id="tokens"' in html, 'sheet: 6 cells + seam map + tokens')
        t('RECREATED' in html and 'REAL' in html and 'keepout' in html, 'sheet: truthfulness badges + keep-out guide')
        t('Monday, answered.' in html and '#082A34' in html, 'sheet: quoted words drawn in design tokens')
        t('class="se end"' in html and '@media (max-width:480px)' not in html, 'sheet: start/end lines under the frame; desktop sheet has no phone block')
        print('  sheet %d bytes → %s' % (len(html), out))
        outm = os.path.join(tmp, 'out', 'storyboard_mobile.html')
        sheet(man, outm, tmp, design=os.path.join(TEMPLATES, 'design.example.md'), mobile=True)
        hm = open(outm, encoding='utf-8').read()
        t('@media (max-width:480px)' in hm and 'grid-template-columns:1fr' in hm and '.frame:focus{position:fixed' in hm and '<script' not in hm and 'name="viewport"' in hm,
          'sheet --mobile: single column under 480 px, tap-to-zoom without scripts')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\nstoryboard.py selftest: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
