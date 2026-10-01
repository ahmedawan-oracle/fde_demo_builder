# -*- coding: utf-8 -*-
"""brief.py — validate a BRIEF.md (the intake brief written before any pixel) and seed the QA files from it.

    python tools/brief.py [BRIEF.md]                 validate: required fields, banned claims, the credit; gaps as questions
    python tools/brief.py BRIEF.md --summary         the hand-off: what the requester STATED vs what was INFERRED
    python tools/brief.py BRIEF.md --seed-qa [qa.json] [--write]
                                                     qa.json additions: required_phrases += honesty_line, banned_phrases += Bans,
                                                     brief/design/hook_banned_tokens keys (prints JSON; --write merges)
    python tools/brief.py BRIEF.md --seed-claims [claims.json] [--write]
                                                     claims.json skeleton with the honesty line as the first traced claim
    python tools/brief.py BRIEF.md --json            manifest
    python tools/brief.py --selftest

A brief is YAML frontmatter (one key per confirmed field) plus prose sections: Intent, Stated, Inferred, Must-haves,
Deferred asks, Assets, Bans, Notes (templates/BRIEF.example.md). The question protocol it encodes:
one field per message, recommended option first with its receipt, inference is not an answer, the two run-shape
questions (review with-me|drive-it, storyboard yes|no) last, one integration check, stated and inferred shown as two
groups, and a revision to the summary is not a confirmation. Render stays user-gated in both run shapes.
Stdlib only; never raises on a malformed brief — it reports.
"""
import json, os, re, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.normpath(os.path.join(HERE, '..', 'templates'))
CREDIT = 'Crafted with FDE Demo Builder · by Ahmed Awan'           # mandatory, verbatim (credit.py stamps and checks it)

DESTINATIONS = {
    #  name       aspects accepted (first = derived default)   length_s range   receipt
    'booth':    (['1920x1080'], (60, 180), 'a booth loop is glanced at from 2–4 m: biggest type, 1–3 min'),
    'session':  (['1920x1080'], (120, 240), 'a session clip plays once on a projector with a speaker beside it'),
    'linkedin': (['1080x1080', '1920x1080'], (30, 90), 'a feed fights for its first second and plays small: ×1.5 type, under 90 s'),
    'youtube':  (['1920x1080'], (60, 300), 'full-screen viewing; a longer read is fine'),
    'vertical': (['1080x1920'], (15, 60), 'stories/shorts: vertical, fast'),
    'internal': (['1920x1080'], (60, 600), 'a team review; length follows the material'),
}
NARRATION = ('verbatim', 'restructured')
REVIEW = ('with-me', 'drive-it')
YESNO = ('yes', 'no')
# cliché / over-claim defaults; qa.json banned_phrases and the brief's ## Bans are added on top
BANNED_DEFAULT = ['plain english', 'generally available', 'available now', 'guaranteed', '100% accurate', 'instantly',
                  'seamless', 'unlock the power', 'streamline your workflow', 'revolutionary', 'game-changing']
# subject-internal vocabulary has no place in the ONE claim (value-first spine)
INTERNAL = [r'\b[a-z]+_[a-z_]+\b', r'\b\w+\.\w+\(', r'\bgroupBy\b', r'\bSELECT\b', r'\bimport\b', r'\bAPI\b', r'\bSQL\b',
            r'\bJSON\b', r'\b\d+ (?:files?|tables?|lines?|rows?) ']
HOOK_BANNED_TOKENS = [r'\b[a-z]+_[a-z_]+\b', r'\b\w+\.\w+\(', r'\bgroupBy\b', r'\bSELECT\b', r'\bimport\b', r'\bspark\.\w+',
                      r'\bAPI\b', r'\bJSON\b', r'\bSQL\b']

# (field, question with the recommended option first and its receipt)
QUESTIONS = [
    ('message', 'What is the ONE claim this film makes, as a sentence? Recommended: write it in outcome language — what the '
                'audience gains or stops losing — not what the product does; the hook and the close both have to say it.'),
    ('audience', 'Who watches? Recommended: the role that asks the on-screen question, plus whoever approves their tooling.'),
    ('destination', 'Where does it play — booth | session | linkedin | youtube | vertical | internal? Recommended: booth — it '
                    'sets the loudest room and the smallest readable type; aspect is derived from it.'),
    ('length_s', 'Target length in seconds? Recommended: 120–180 for a booth film — 6–10 beats at ~2.5 words/s, product '
                 'beats 8–20 s each; the usable screen time in the recording is the ceiling.'),
    ('angle', 'Which telling? Recommended: run the pitch round (five tellings, three lines each) and pick by reaction; '
              'record the two rejected alternatives under ## Notes.'),
    ('narration', 'Narration mode — verbatim (the recording\'s own words) | restructured (rewritten around the message)? '
                  'Recommended: restructured — the honesty audit usually drops what the screen contradicts.'),
    ('voices', 'How many voices? Recommended: 3–4 — a narrator, first-person persona voices, the product\'s own voice.'),
    ('honesty_line', 'What is the truthfulness line? Recommended: "Acme is fictional, and so is its data." — spoken once '
                     'and shown as the title-card caption; it becomes a required phrase in qa.json.'),
    ('storyboard', 'Review a storyboard first — yes | no? Recommended: yes for anything beyond two beats (plan in chat, '
                   'sketch sheet, then build).'),
    ('review', 'Review with me, or drive it? Recommended: with-me — ask at each pass; drive-it posts the same decisions '
               'with reasons and keeps going. Rendering waits for you in both.'),
    ('placeholders', 'May a placeholder beat ship — yes | no? Recommended: no — a placeholder holds a slot in the plan, '
                     'never a frame in the film.'),
    ('name', 'What is the film called in film.json / vo_script.py? Recommended: "film" — the sample uses it.'),
    ('credit', 'The mandatory credit line, verbatim: "%s". It is stamped by build_film.py; the brief records it so '
               'nobody plans a closing card that covers it.' % CREDIT),
]
REQUIRED = [q[0] for q in QUESTIONS]


# ------------------------------------------------------------------------------------------------ parsing
def _frontmatter(text):
    """Minimal YAML-lite: key: value lines (quotes stripped, '#' comments outside quotes dropped)."""
    if not text.startswith('---'):
        return {}, text
    end = re.search(r'(?m)^---\s*$', text[3:])
    if not end:
        return {}, text
    fm = {}
    for raw in text[3:3 + end.start()].splitlines():
        line, q = '', None
        for ch in raw:
            if q:
                line += ch
                if ch == q:
                    q = None
            elif ch in '"\'':
                q = ch; line += ch
            elif ch == '#':
                break
            else:
                line += ch
        if ':' not in line or line.startswith((' ', '\t')):
            continue
        k, v = line.split(':', 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        fm[k.strip().lower()] = v
    return fm, text[3 + end.end():]


def parse(text):
    """BRIEF.md → {'fields': {...}, 'sections': {name: [items]}, 'prose': {name: text}}."""
    fm, body = _frontmatter(text)
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    sections, prose, cur = {}, {}, None
    for raw in body.splitlines():
        m = re.match(r'^#{2,3}\s+(.+?)\s*$', raw)
        if m:
            cur = m.group(1).strip().lower(); sections[cur] = []; prose[cur] = ''
            continue
        if cur is None or not raw.strip():
            continue
        if raw.lstrip().startswith(('- ', '* ')):
            sections[cur].append(raw.strip()[2:].strip())
        else:
            prose[cur] += raw.strip() + ' '
    return {'fields': fm, 'sections': sections, 'prose': {k: v.strip() for k, v in prose.items()}}


def _sect(brief, *names):
    for n in names:
        for k, v in brief['sections'].items():
            if k.startswith(n):
                return v
    return []


def words(s):
    return re.findall(r"[A-Za-z0-9][\w'’-]*", s or '')


# ------------------------------------------------------------------------------------------------ validation
def validate(brief, qa=None):
    """→ (errors, warnings, questions). Questions are the gaps, phrased for the one-field-per-message protocol."""
    E, W, Q = [], [], []
    f = brief['fields']
    for field, question in QUESTIONS:
        if not str(f.get(field, '')).strip():
            Q.append((field, question))
    if Q:
        E.append('missing fields: %s' % ', '.join(k for k, _ in Q))
    msg = str(f.get('message', '')).strip()
    if msg:
        n = len(words(msg))
        if n > 25:
            E.append('message is %d words — one sentence, one claim (≤ 25 words)' % n)
        if len(re.findall(r'[.!?](\s|$)', msg)) > 1:
            W.append('message has more than one sentence — the film says one thing')
        if re.match(r'\s*(welcome to|introducing)\b', msg, re.I):
            E.append('message opens with "Welcome to / Introducing" — that is a restart, not a claim')
        for p in INTERNAL:
            m = re.search(p, msg)
            if m:
                E.append('message contains subject-internal vocabulary "%s" — write the claim in outcome language' % m.group())
                break
        banned = [b.lower() for b in BANNED_DEFAULT] + [b.lower() for b in (qa or {}).get('banned_phrases', [])] \
            + [b.lower() for b in _sect(brief, 'bans', 'banned')]
        hit = [b for b in banned if b in msg.lower()]
        if hit:
            E.append('message uses a banned claim: %s' % hit)
    dest = str(f.get('destination', '')).lower()
    if dest and dest not in DESTINATIONS:
        E.append('destination "%s" is not one of %s' % (dest, '|'.join(DESTINATIONS)))
    elif dest:
        aspects, (lo, hi), receipt = DESTINATIONS[dest]
        asp = str(f.get('aspect', '')).lower()
        if asp and asp not in aspects:
            E.append('aspect %s does not follow from destination %s (expected %s)' % (asp, dest, ' or '.join(aspects)))
        try:
            L = float(f.get('length_s', 0))
            if L and not (lo <= L <= hi):
                W.append('length_s %.0f is outside the %s range %d–%d s (%s)' % (L, dest, lo, hi, receipt))
        except ValueError:
            E.append('length_s "%s" is not a number of seconds' % f.get('length_s'))
    for field, allowed in (('narration', NARRATION), ('review', REVIEW), ('storyboard', YESNO), ('placeholders', YESNO)):
        v = str(f.get(field, '')).lower()
        if v and v not in allowed:
            E.append('%s "%s" must be one of %s' % (field, v, '|'.join(allowed)))
    cr = ' '.join(str(f.get('credit', '')).split())
    if cr and cr != CREDIT:
        E.append('credit must read exactly "%s" (found "%s") — it is mandatory and verbatim' % (CREDIT, cr))
    hl = str(f.get('honesty_line', '')).strip()
    if hl and qa is not None and hl.lower() not in [p.lower() for p in qa.get('required_phrases', [])]:
        W.append('honesty_line is not in qa.json required_phrases — run brief.py --seed-qa --write')
    if hl and len(words(hl)) > 14:
        W.append('honesty_line is %d words — one short sentence the narrator can say in ~3 s' % len(words(hl)))
    if not _sect(brief, 'stated'):
        W.append('no "## Stated" section — list what the requester actually said, one field per line, with where it was said')
    if not _sect(brief, 'inferred'):
        W.append('no "## Inferred" section — list the defaults you chose with their receipts; corrections live there')
    if not _sect(brief, 'must-have', 'must have'):
        W.append('no "## Must-haves" — name what the film cannot ship without')
    if not brief['prose'].get('intent') and not _sect(brief, 'intent'):
        W.append('no "## Intent" prose — the chosen telling and tone in the requester\'s own words')
    if not any('integration' in n.lower() for n in _sect(brief, 'notes')):
        W.append('no integration check in ## Notes — look for the consequence the combined answers create that no single answer showed')
    return E, W, Q


def summary(brief):
    """Stated vs inferred, as two groups. Stated = fields named in ## Stated; everything else in the frontmatter is inferred
    unless ## Inferred claims it (then its receipt is printed)."""
    f = brief['fields']
    stated = {}
    for item in _sect(brief, 'stated'):
        k = re.split(r'\s[—–-]\s', item, maxsplit=1)[0].strip().lower().replace(' ', '_')
        stated[k] = item
    inferred_notes = {}
    for item in _sect(brief, 'inferred'):
        k = item.split()[0].strip().lower() if item.split() else ''
        inferred_notes[k] = item
    out_s, out_i = [], []
    for k, v in f.items():
        if k in stated:
            out_s.append('%-14s %s   ← %s' % (k, v, stated[k].split('—', 2)[-1].strip() if '—' in stated[k] else 'stated'))
        else:
            out_i.append('%-14s %s   ← %s' % (k, v, inferred_notes.get(k, 'default').split('—', 1)[-1].strip() if k in inferred_notes else 'default'))
    if 'aspect' not in f and str(f.get('destination', '')).lower() in DESTINATIONS:
        out_i.append('%-14s %s   ← derived from destination %s' % ('aspect', DESTINATIONS[f['destination'].lower()][0][0], f['destination']))
    return out_s, out_i


def seed_qa(brief, qa=None):
    """qa.json additions derived from the brief (merge, never replace)."""
    qa = dict(qa or {})
    f = brief['fields']
    req = list(qa.get('required_phrases', []))
    if f.get('honesty_line') and f['honesty_line'] not in req:
        req.append(f['honesty_line'])
    ban = list(qa.get('banned_phrases', []))
    for b in _sect(brief, 'bans', 'banned') + BANNED_DEFAULT:
        if b.lower() not in [x.lower() for x in ban]:
            ban.append(b)
    qa.update({'required_phrases': req, 'banned_phrases': ban, 'brief': qa.get('brief', 'BRIEF.md'),
               'design': qa.get('design', 'design.md'), 'storyboard': qa.get('storyboard', 'STORYBOARD.md'),
               'hook_banned_tokens': qa.get('hook_banned_tokens', HOOK_BANNED_TOKENS)})
    return qa


def seed_claims(brief, claims=None):
    claims = dict(claims or {'_comment': 'Every figure or claim the narration makes, with where it is visible on screen. '
                                         "'phrase' must appear verbatim in vo_script.py.", 'claims': [],
                             'dropped_from_the_original_narration': []})
    hl = brief['fields'].get('honesty_line')
    if hl and not any(c.get('phrase') == hl for c in claims['claims']):
        claims['claims'].insert(0, {'phrase': hl, 'source': 'title card caption (shown while it is spoken)'})
    return claims


# ------------------------------------------------------------------------------------------------ CLI
def _load(path):
    if path and os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    return None


def main(argv):
    if '--selftest' in argv:
        return selftest()
    pos = [a for a in argv if not a.startswith('--')]
    path = next((a for a in pos if a.lower().endswith('.md')), 'BRIEF.md')
    if not os.path.exists(path):
        print('missing %s — scaffold it from templates/BRIEF.example.md and answer the questions one at a time' % path)
        for field, q in QUESTIONS:
            print('  ? %-13s %s' % (field, q))
        return 2
    proj = os.path.dirname(os.path.abspath(path))
    brief = parse(open(path, encoding='utf-8').read())
    if '--json' in argv:
        print(json.dumps(brief, indent=1, ensure_ascii=False)); return 0
    if '--seed-qa' in argv:
        qp = next((a for a in pos if a.endswith('.json')), os.path.join(proj, 'qa.json'))
        qa = seed_qa(brief, _load(qp))
        if '--write' in argv:
            json.dump(qa, open(qp, 'w', encoding='utf-8'), indent=1, ensure_ascii=False); print('merged into ' + qp)
        else:
            print(json.dumps(qa, indent=1, ensure_ascii=False))
        return 0
    if '--seed-claims' in argv:
        cp = next((a for a in pos if a.endswith('.json')), os.path.join(proj, 'claims.json'))
        cl = seed_claims(brief, _load(cp))
        if '--write' in argv:
            json.dump(cl, open(cp, 'w', encoding='utf-8'), indent=1, ensure_ascii=False); print('merged into ' + cp)
        else:
            print(json.dumps(cl, indent=1, ensure_ascii=False))
        return 0
    if '--summary' in argv:
        s, i = summary(brief)
        print('STATED by the requester'); print('\n'.join('  ' + x for x in s) or '  (nothing — every field is inferred)')
        print('INFERRED or defaulted (corrections live here)'); print('\n'.join('  ' + x for x in i) or '  (nothing)')
        print('\nRevision is not confirmation: after any correction, present this summary again and wait for a yes.')
        return 0
    qa = _load(os.path.join(proj, 'qa.json'))
    E, W, Q = validate(brief, qa)
    f = brief['fields']
    print('BRIEF  %s  v%s' % (path, f.get('version', 1)))
    if f.get('message'):
        print('This film tells %s that %s' % (f.get('audience', '[audience]'), f['message']))
    for w in W:
        print('  WARN  ' + w)
    for e in E:
        print('  FAIL  ' + e)
    if Q:
        print('\nGaps, as questions (ask one per message; recommended option first):')
        for field, q in Q:
            print('  ? %-13s %s' % (field, q))
    print('\n%s  (%d errors, %d warnings, %d open questions)' % ('BRIEF OK' if not E else 'BRIEF INCOMPLETE', len(E), len(W), len(Q)))
    return 1 if E else 0


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    ok = True

    def t(cond, label):
        nonlocal ok
        print('  %s  %s' % ('ok  ' if cond else 'FAIL', label)); ok = ok and bool(cond)

    text = open(os.path.join(TEMPLATES, 'BRIEF.example.md'), encoding='utf-8').read()
    b = parse(text)
    E, W, Q = validate(b, {'required_phrases': ['fictional'], 'banned_phrases': []})
    for e in E:
        print('      unexpected: ' + e)
    t(not E and not Q, 'template brief validates (%d warnings)' % len(W))
    t(any('honesty_line is not in qa.json' in w for w in W), 'warns when the honesty line is not yet a required phrase')
    bad = text.replace('message: "A question that took a day now takes a minute, on data the team already trusts."',
                       'message: "Introducing spark.table() for the groupBy in plain English"')
    bad = bad.replace('credit: "Crafted with FDE Demo Builder · by Ahmed Awan"', 'credit: "Made with FDE Demo Builder"')
    bad = bad.replace('destination: booth', 'destination: linkedin').replace('aspect: 1920x1080', 'aspect: 1080x1920')
    bad = re.sub(r'(?m)^honesty_line:.*$', 'honesty_line:', bad)
    E2, W2, Q2 = validate(parse(bad))
    t(any('Welcome to / Introducing' in e for e in E2), 'rejects a "Introducing" message')
    t(any('subject-internal' in e for e in E2), 'rejects identifiers in the one claim')
    t(any('banned claim' in e for e in E2), 'rejects a banned claim in the message')
    t(any('credit must read exactly' in e for e in E2), 'rejects a reworded credit')
    t(any('aspect' in e for e in E2), 'checks the aspect against the destination')
    t([k for k, _ in Q2] == ['honesty_line'], 'prints the missing field as a question: %s' % [k for k, _ in Q2])
    s, i = summary(b)
    t(len(s) == 5 and any(x.startswith('aspect') for x in i), 'summary splits stated (%d) from inferred (%d)' % (len(s), len(i)))
    qa = seed_qa(b, {'required_phrases': ['fictional'], 'banned_phrases': ['guaranteed']})
    t('Acme is fictional, and so is its data.' in qa['required_phrases'] and 'plain English' in qa['banned_phrases']
      and 'guaranteed' in qa['banned_phrases'] and qa['brief'] == 'BRIEF.md', 'seed_qa merges honesty line + bans into qa.json')
    cl = seed_claims(b)
    t(cl['claims'][0]['phrase'] == 'Acme is fictional, and so is its data.', 'seed_claims puts the honesty line first')
    print('\nbrief.py selftest: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
