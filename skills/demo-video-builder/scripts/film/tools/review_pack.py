# -*- coding: utf-8 -*-
"""review_pack.py — one offline HTML a stakeholder can approve a film from: storyboard, a frame per beat, the claims
table, the QA report, the timeline, the media ledger, honesty flags and a comment box per beat (v5, brand-skins-review).

    python tools/review_pack.py build  [--project DIR] [--out out/review/index.html] [--film out/<film>.mp4]
                                       [--taps out/taps] [--qa out/qa_report.json|out/qa.log] [--comments out/review/comments.json]
                                       [--no-embed] [--json]
    python tools/review_pack.py --serve [--project DIR] [--port 8765] [--dir out/review]
                                       local http.server on 127.0.0.1: GET serves the pack, POST /comments saves comments.json,
                                       POST /approvals saves approvals.json
    python tools/review_pack.py --lock  --by "Name" [--date YYYY-MM-DD] [--project DIR] [--comments out/review/comments.json]
                                       [--force]   writes the "signed off by / date" block into STORYBOARD.md's ## Locked section;
                                                   refuses (exit 1) while any comment is still open unless --force
    python tools/review_pack.py --selftest

Why one file. Reviewers open attachments, not repos. The pack is a single HTML with every image embedded as a
data: URI and no external request (no fonts, no scripts, no CSS from the network) — it renders the same from a
mail attachment, a USB stick or a share, and it can be diffed: two builds of the same project are byte-identical
(no wall clock, no random ids, sorted keys).

What it reads (each one optional; a missing artefact becomes a visible "not available" card, never a crash):
  STORYBOARD.md         beats, direction, decisions, still-open, locked (tools/storyboard.py parse — one parser)
  BRIEF.md              honesty_line, destination, review shape (frontmatter only)
  out/taps/*.jpg        one frame per beat: a file named NN_*.jpg / NN.jpg / beatNN.jpg maps to beat NN, t<sec>.jpg maps
                        to the beat whose span contains the time; else out/storyboard/NN.jpg (the truth pass); else, with
                        --film, a frame is pulled at each beat's midpoint (ffmpeg) into out/review/frames/NN.jpg
  claims.json           every spoken figure with its on-screen source + dropped_from_the_original_narration
  out/qa_report.json    {gates:[{name, ok, detail}]} — or the text log qa_film.py prints (two spaces, name, PASS|FAIL, detail)
  out/timeline.json     total, cuts, seams, shots, phases (export_timeline.js) → the ruler
  media.jsonl           last record per path, licence flags (UNKNOWN / commercial_ok false)
  comments.json         the reviewer's comments so the rebuilt pack shows them
  out/pairs/pairs.json  (v5.1) the first and last frame of every segment (gates/snapshot.py --pairs); a pair maps to the
                        beat whose span holds its midpoint — the beat shows START | END with "Approve start / Approve end"
  approvals.json        (v5.1) {pack, approvals:[{beat, start, end, by, at}]} beside the pack; tools/storyboard.py check
                        --build refuses while any END frame is unapproved once this file exists

Honesty flags are derived, not authored: a placeholder beat; a claim dropped from the original narration; a failing
claims / over-claims / required-lines / hygiene gate; a ledger asset with an unknown or non-commercial licence; a
storyboard still-open item; a brief without an honesty line; an END frame not yet approved and a shot whose two
frames are the same picture (nothing moved). They are listed first because they decide the sign-off.

Comments. Each beat has a text box, a status (open/resolved) and the reviewer's name. "Save" POSTs to /comments
when the pack is served (--serve) and downloads comments.json when opened as a file; "Load" merges a comments.json
back in. The lock (--lock) is the end of the loop: it writes `signed off by`, `date` and the pack's sha256 into the
## Locked section of STORYBOARD.md, so tools/storyboard.py check --build passes only on a reviewed plan.

Measured defaults: thumbnails 640 px wide JPEG q82 (a 6-beat pack is ~0.5 MB); the comment payload cap is 1 MB; the
server binds 127.0.0.1 only and refuses cross-origin writes: every request must carry a Host of 127.0.0.1:<port> or
localhost:<port>; a POST must be application/json, come from an Origin of http://127.0.0.1:<port> or http://localhost:<port>,
and carry the per-session random token the served page embeds (X-Review-Token) — anything else is 403. Exit codes: 0 ok,
1 findings (open comments on --lock, honesty flags with --strict), 2 usage. Stdlib + Pillow (thumbnails; falls back to embedding the file as-is); ffmpeg only for --film frames.
"""
import argparse, base64, glob, hashlib, io, json, os, re, secrets, subprocess, sys, threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
try:
    import storyboard as SB                                             # the one storyboard parser
except ImportError:                                                     # pragma: no cover
    SB = None

THUMB_W = 640
THUMB_Q = 82
MAX_POST = 1 << 20
HONESTY_GATES = ('claims traced', 'no over-claims', 'required lines', 'hygiene', 'CREDIT')
QA_LINE = re.compile(r'^\s{2}(\S.*?)\s{2,}(PASS|FAIL)\s*(.*)$')


# ------------------------------------------------------------------------------------------------ small helpers
def _esc(s):
    return (str(s) if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _load_json(p, default=None):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _read(p):
    try:
        with open(p, encoding='utf-8') as fh:
            return fh.read()
    except OSError:
        return None


def _rel(p, base):
    try:
        return os.path.relpath(p, base).replace('\\', '/')
    except ValueError:
        return p.replace('\\', '/')


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or 'film').lower()).strip('-') or 'film'


def _fmt_t(t):
    return '%.1f' % t if isinstance(t, (int, float)) else '—'


# ------------------------------------------------------------------------------------------------ readers
def parse_qa_log(text):
    """qa_film.py's printed gates → [{name, ok, detail}] (the summary line is skipped)."""
    out = []
    for ln in (text or '').splitlines():
        m = QA_LINE.match(ln)
        if m:
            out.append({'name': m.group(1).strip(), 'ok': m.group(2) == 'PASS', 'detail': m.group(3).strip()})
    return out


def read_qa(project, explicit=None):
    cands = [explicit] if explicit else [os.path.join(project, 'out', 'qa_report.json'), os.path.join(project, 'out', 'qa.log'),
                                         os.path.join(project, 'out', 'qa.txt')]
    for p in cands:
        if p and os.path.exists(p):
            if p.endswith('.json'):
                d = _load_json(p, {})
                gates = d.get('gates') if isinstance(d, dict) else d
                if isinstance(gates, list):
                    return {'path': p, 'gates': [{'name': g.get('name'), 'ok': bool(g.get('ok')), 'detail': g.get('detail', '')} for g in gates]}
            else:
                return {'path': p, 'gates': parse_qa_log(_read(p))}
    return None


def read_ledger(path):
    """media.jsonl → [records] (last record per path wins, lines without a path skipped), sorted by path."""
    txt = _read(path)
    if txt is None:
        return None
    by = {}
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get('path'):
            by[rec['path']] = rec
    return [by[k] for k in sorted(by)]


def read_frontmatter(path):
    txt = _read(path)
    if txt is None or SB is None:
        return None
    fm, _, _ = SB.frontmatter(txt)
    return fm


def find_taps(project, beats, taps_dir=None, film=None, frames_out=None):
    """Beat number → image path. Priority: taps dir (by NN or t<sec>), out/storyboard/NN.jpg, ffmpeg from --film."""
    found = {}
    taps_dir = taps_dir or os.path.join(project, 'out', 'taps')
    files = sorted(f for ext in ('jpg', 'jpeg', 'png') for f in glob.glob(os.path.join(taps_dir, '*.' + ext))) if os.path.isdir(taps_dir) else []
    spans = [(b['number'], b.get('actual') or (b['t0'], b['t1'])) for b in beats]
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        m = re.match(r'^(?:beat)?(\d{1,2})(?:[_\-. ]|$)', base, re.I)
        if m and int(m.group(1)) in [n for n, _ in spans]:
            found.setdefault(int(m.group(1)), f); continue
        m = re.match(r'^t(\d+(?:\.\d+)?)', base)
        if m:
            t = float(m.group(1))
            for n, (s, e) in spans:
                if s is not None and e is not None and s <= t < e:
                    found.setdefault(n, f); break
    for n, _ in spans:
        if n in found:
            continue
        p = os.path.join(project, 'out', 'storyboard', '%02d.jpg' % n)
        if os.path.exists(p):
            found[n] = p
    missing = [(n, sp) for n, sp in spans if n not in found and sp[0] is not None and sp[1] is not None]
    if missing and film and os.path.exists(film):
        frames_out = frames_out or os.path.join(project, 'out', 'review', 'frames')
        os.makedirs(frames_out, exist_ok=True)
        for n, (s, e) in missing:
            dst = os.path.join(frames_out, '%02d.jpg' % n)
            if not os.path.exists(dst):
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', '%.3f' % ((s + e) / 2.0), '-i', film, '-frames:v', '1',
                                '-vf', 'scale=%d:-2' % THUMB_W, dst], check=False)
            if os.path.exists(dst):
                found[n] = dst
    return found


def read_pairs(project, beats, pairs_json=None):
    """out/pairs/pairs.json → {beat: {'start': {t, path}, 'end': {t, path}, 'labels': [...], 'static': bool}} plus
    'unmapped': [labels]. A segment's START frame belongs to the beat whose span holds the start time and its END frame
    to the beat whose span holds the end time — a title segment that carries two storyboard beats gives beat 1 its START
    and beat 2 its END. A beat with several segments opens on the first START and leaves on the last END; a beat may
    have one side only."""
    pairs_json = pairs_json or os.path.join(project, 'out', 'pairs', 'pairs.json')
    d = _load_json(pairs_json)
    if not d or not isinstance(d.get('pairs'), list):
        return None
    base = os.path.dirname(os.path.abspath(pairs_json))
    spans = [(b['number'], b.get('actual') or (b['t0'], b['t1'])) for b in beats]
    out, unmapped = {}, []
    fix = lambda f: f if os.path.isabs(f) else os.path.join(base, f)
    beat_at = lambda t: _beat_at(spans, t)
    for r in sorted(d['pairs'], key=lambda r: r.get('t0', 0)):
        if not (r.get('start') and r.get('end')):
            continue
        hs, he = beat_at(float(r['start']['t'])), beat_at(float(r['end']['t']))
        if hs is None and he is None:
            unmapped.append(r['label']); continue
        if hs is not None:
            cur = out.setdefault(hs, {'labels': [], 'static': False})
            if 'start' not in cur:
                cur['start'] = {'t': r['start']['t'], 'path': fix(r['start']['file'])}
            if r['label'] not in cur['labels']:
                cur['labels'].append(r['label'])
        if he is not None:
            cur = out.setdefault(he, {'labels': [], 'static': False})
            cur['end'] = {'t': r['end']['t'], 'path': fix(r['end']['file'])}
            if r['label'] not in cur['labels']:
                cur['labels'].append(r['label'])
            cur['static'] = cur['static'] or (bool(r.get('static')) and hs == he)
    out['unmapped'] = unmapped
    return out


def _beat_at(spans, t):
    """the beat whose span holds t; a time past the last beat (the closing hold and the credit tail) belongs to the last beat."""
    hit = next((n for n, (a, b) in spans if a is not None and b is not None and a <= t < b), None)
    if hit is None:
        last = [(n, b) for n, (a, b) in spans if b is not None]
        if last and t >= max(b for _, b in last):
            hit = max(last, key=lambda x: x[1])[0]
    return hit


def read_approvals(path):
    """approvals.json → {pack, approvals:[{beat, start, end, by, at}]} (sorted by beat; a missing file is empty)."""
    d = _load_json(path, None)
    if not isinstance(d, dict) or not isinstance(d.get('approvals'), list):
        return {'pack': None, 'approvals': []}
    rows = []
    for a in d['approvals']:
        try:
            rows.append({'beat': int(a.get('beat')), 'start': bool(a.get('start')), 'end': bool(a.get('end')), 'by': a.get('by') or '', 'at': a.get('at') or ''})
        except (TypeError, ValueError):
            continue
    return {'pack': d.get('pack'), 'approvals': sorted(rows, key=lambda a: a['beat'])}


def data_uri(path, embed=True, base=None):
    """Image → data: URI (640 px JPEG) or a relative src when --no-embed."""
    if not embed:
        return _rel(path, base) if base else path
    try:
        from PIL import Image
        im = Image.open(path).convert('RGB')
        if im.size[0] > THUMB_W:
            im = im.resize((THUMB_W, max(1, round(im.size[1] * THUMB_W / im.size[0]))), Image.Resampling.LANCZOS)
        buf = io.BytesIO(); im.save(buf, 'JPEG', quality=THUMB_Q, optimize=True)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        with open(path, 'rb') as fh:
            raw = fh.read()
        mime = 'image/png' if path.lower().endswith('.png') else 'image/jpeg'
        return 'data:%s;base64,' % mime + base64.b64encode(raw).decode('ascii')


# ------------------------------------------------------------------------------------------------ collect
def collect(project, film=None, taps=None, qa=None, comments=None, out_html=None, embed=True):
    """Every artefact of the project → one plain dict (the pack). Pure given the files; no wall clock."""
    sb_path = os.path.join(project, 'STORYBOARD.md')
    sb_text = _read(sb_path)
    man = SB.parse(sb_text) if (sb_text is not None and SB) else {'globals': {}, 'sections': {'direction': [], 'decisions': [], 'changes': [], 'still_open': [], 'locked': [], 'other': {}}, 'beats': [], 'warnings': ['STORYBOARD.md not found' if sb_text is None else 'storyboard parser unavailable']}
    cfg = _load_json(os.path.join(project, 'film.json'), {}) or {}
    name = cfg.get('name', 'film')
    phases = _load_json(os.path.join(project, 'vo', name + '_phases.json'))
    if phases and SB and man['beats']:
        try:
            SB.check(man, phases=phases, autonomous=True)              # fills beat['actual'] from the clock
        except Exception:
            pass
    film = film or (os.path.join(project, cfg['output']) if cfg.get('output') else None)
    out_html = out_html or os.path.join(project, 'out', 'review', 'index.html')
    out_dir = os.path.dirname(os.path.abspath(out_html))
    tap_paths = find_taps(project, man['beats'], taps, film, os.path.join(out_dir, 'frames'))
    design = None
    if SB and os.path.exists(os.path.join(project, 'design.md')):
        try:
            design = SB.load_design(os.path.join(project, 'design.md'))[0]
        except Exception:
            design = None
    pack = {
        'id': '%s-v%s' % (_slug(man['globals'].get('title') or name), man['globals'].get('version', 1)),
        'project': project, 'name': name, 'film': film if film and os.path.exists(film) else None,
        'storyboard': man, 'storyboard_path': sb_path if sb_text is not None else None,
        'brief': read_frontmatter(os.path.join(project, 'BRIEF.md')),
        'design': design or (SB.DEFAULT_TOKENS if SB else {}),
        'claims': _load_json(os.path.join(project, 'claims.json')),
        'qa': read_qa(project, qa),
        'timeline': _load_json(os.path.join(project, 'out', 'timeline.json')),
        'ledger': read_ledger(os.path.join(project, cfg.get('ledger', 'media.jsonl'))),
        'comments_path': comments or os.path.join(out_dir, 'comments.json'),
        'approvals_path': os.path.join(out_dir, 'approvals.json'),
        'taps': {str(n): {'path': p, 'src': data_uri(p, embed, out_dir)} for n, p in sorted(tap_paths.items())},
        'out_html': out_html,
    }
    pr = read_pairs(project, man['beats'])
    pack['pairs'] = None
    if pr is not None:
        pack['pairs'] = {'unmapped': pr.pop('unmapped', [])}
        for n, v in pr.items():
            e = {'labels': v['labels'], 'static': v['static']}
            for side in ('start', 'end'):
                if v.get(side):
                    e[side] = {'t': v[side]['t'], 'path': v[side]['path'], 'src': data_uri(v[side]['path'], embed, out_dir)}
            pack['pairs'][str(n)] = e
    pack['approvals'] = read_approvals(pack['approvals_path'])
    pack['comments'] = _load_json(pack['comments_path'], {'pack': pack['id'], 'comments': []})
    pack['flags'] = honesty_flags(pack)
    return pack


def honesty_flags(pack):
    """Derived flags [{level, beat, text}] — fail > warn > info, then beat, then text."""
    F = []
    man, claims, qa, ledger, brief = pack['storyboard'], pack['claims'], pack['qa'], pack['ledger'], pack['brief']
    for b in man['beats']:
        if b.get('real') == 'placeholder':
            F.append({'level': 'fail', 'beat': b['number'], 'text': 'beat %02d is a placeholder — no pixels behind "%s"' % (b['number'], b['fields'].get('screen', '')[:60])})
        if b.get('real') == 'recorded' and not b['fields'].get('clip'):
            F.append({'level': 'warn', 'beat': b['number'], 'text': 'beat %02d is recorded but names no clip' % b['number']})
    if claims is None:
        F.append({'level': 'fail', 'beat': None, 'text': 'claims.json missing — no spoken figure is traced to the screen'})
    else:
        for c in claims.get('claims', []):
            if not c.get('source'):
                F.append({'level': 'fail', 'beat': None, 'text': 'claim without an on-screen source: "%s"' % c.get('phrase', '')[:80]})
        for d in claims.get('dropped_from_the_original_narration', []):
            F.append({'level': 'info', 'beat': None, 'text': 'dropped from the original narration: %s' % (d if isinstance(d, str) else json.dumps(d, ensure_ascii=False))[:120]})
    if qa is None:
        F.append({'level': 'warn', 'beat': None, 'text': 'no QA report (out/qa_report.json or out/qa.log) — the gates have not run on this cut'})
    else:
        for g in qa['gates']:
            if not g['ok'] and g['name'] in HONESTY_GATES:
                F.append({'level': 'fail', 'beat': None, 'text': 'gate %s FAILED: %s' % (g['name'], g['detail'][:100])})
    if ledger:
        for r in ledger:
            lic = r.get('licence') or {}
            if lic.get('name', 'UNKNOWN') == 'UNKNOWN' or lic.get('commercial_ok') is False:
                F.append({'level': 'warn', 'beat': None, 'text': 'ledger: %s has licence %s (commercial_ok=%s)' % (r.get('path'), lic.get('name', 'UNKNOWN'), lic.get('commercial_ok'))})
    if pack.get('pairs'):
        ap = {a['beat']: a for a in pack['approvals']['approvals']}
        for k, v in pack['pairs'].items():
            if k == 'unmapped':
                continue
            n = int(k)
            if v.get('end') and not (ap.get(n) or {}).get('end'):
                F.append({'level': 'warn', 'beat': n, 'text': 'beat %02d: END frame not approved — the build waits for it once approvals.json exists' % n})
            if v.get('static'):
                F.append({'level': 'warn', 'beat': n, 'text': 'beat %02d: its first and last frame are the same picture — nothing moved (a slide, not a shot)' % n})
    for s in man['sections'].get('still_open', []):
        F.append({'level': 'info', 'beat': None, 'text': 'still open: %s' % s[:120]})
    if brief is not None and not brief.get('honesty_line'):
        F.append({'level': 'warn', 'beat': None, 'text': 'BRIEF.md has no honesty_line'})
    if brief is None:
        F.append({'level': 'info', 'beat': None, 'text': 'no BRIEF.md — stated vs inferred cannot be shown'})
    order = {'fail': 0, 'warn': 1, 'info': 2}
    F.sort(key=lambda f: (order[f['level']], f['beat'] if f['beat'] is not None else 99, f['text']))
    return F


# ------------------------------------------------------------------------------------------------ render
CSS = '''
:root{--ground:%(ground)s;--ink:%(ink)s;--accent:%(accent)s;--muted:%(muted)s;--display:%(display)s;--sans:%(sans)s;--mono:%(mono)s}
*{box-sizing:border-box}html,body{margin:0;background:#f4f1ea;color:#1b1b1b;font:15px/1.45 var(--sans)}
header{padding:28px 36px 10px;border-bottom:2px solid #1b1b1b}header h1{font:400 32px/1.1 var(--display);margin:0}
header .v{font:600 13px var(--mono);color:var(--accent);margin-left:10px;vertical-align:middle}
.dek{font-size:17px;margin:8px 0 2px}.tag{font:12px var(--mono);color:#666;margin:0 0 12px}
.strip{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 4px}.pill{font:600 12px var(--mono);padding:4px 10px;border:1px solid #1b1b1b;border-radius:2px;background:#fff}
.pill.fail{background:#1b1b1b;color:#fff}.pill.warn{border-color:var(--accent);color:var(--accent)}.pill.ok{border-color:#2f6f4e;color:#2f6f4e}
section{padding:18px 36px}section h2{font:600 12px var(--mono);letter-spacing:.14em;text-transform:uppercase;margin:0 0 10px;color:#555}
.flags li{margin:3px 0}.flags .fail b{color:#fff;background:#1b1b1b;padding:1px 6px}.flags .warn b{color:var(--accent)}.flags .info b{color:#555}
.ruler{position:relative;height:84px;background:#fff;border:2px solid #1b1b1b;margin:6px 0 10px}
.ruler .beat{position:absolute;top:8px;height:26px;border-left:1px solid #1b1b1b;font:11px var(--mono);padding:4px 0 0 4px;white-space:nowrap;overflow:hidden}
.ruler .beat.recorded{background:#dfe8ee}.ruler .beat.recreated{background:#f3d9d4}.ruler .beat.placeholder{background:repeating-linear-gradient(45deg,#eee 0 6px,#ddd 6px 12px)}
.ruler .cut{position:absolute;top:40px;height:18px;border-left:2px solid #1b1b1b}.ruler .seam{position:absolute;top:40px;height:18px;border-left:2px dashed var(--accent)}
.ruler .tick{position:absolute;top:62px;font:10px var(--mono);color:#666;border-left:1px solid #bbb;padding-left:2px;height:16px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px 20px}
.cell{margin:0;container-type:inline-size;background:#fff;border:2px solid #1b1b1b;padding:0 0 10px}
.frame{position:relative;aspect-ratio:16/9;background:var(--ground);color:var(--ink);overflow:hidden;border-bottom:2px solid #1b1b1b}
.frame img{position:absolute;inset:0;width:100%%;height:100%%;object-fit:cover;display:block}
.sk{position:absolute;left:7cqw;top:12cqw;right:7cqw;bottom:17%%;display:flex;flex-direction:column;justify-content:center;gap:1.4cqw}
.sk h1{font:400 5cqw/1.1 var(--display);margin:0;max-width:78%%}.sk p{font:1.8cqw/1.3 var(--sans);margin:0;color:var(--muted)}
.plate{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:#d9d9d2;color:#333;font:600 2.2cqw var(--mono)}
.badge{position:absolute;top:2.2cqw;right:2.2cqw;font:600 1.5cqw/1 var(--mono);letter-spacing:.1em;padding:.8cqw 1.2cqw;border:1px solid}
.badge.recorded{background:#1b1b1b;color:#fff}.badge.recreated{background:var(--accent);color:#fff;border-color:var(--accent)}.badge.placeholder{background:#fff;color:#1b1b1b}
.keepout{position:absolute;left:0;right:0;top:83%%;border-top:1px dashed rgba(255,255,255,.35)}
.lab{display:flex;justify-content:space-between;font:600 12px var(--mono);letter-spacing:.06em;padding:8px 10px 0}
.fields{padding:4px 10px;font-size:13.5px}.fields p{margin:4px 0}.fields b{font:600 11px var(--mono);letter-spacing:.08em;color:#555;margin-right:6px;text-transform:uppercase}
.vo{font-style:italic}.chips{padding:0 10px}.chip{display:inline-block;font:11px var(--mono);border:1px solid #999;padding:2px 7px;margin:2px 4px 0 0;border-radius:2px}
.chip.claim{border-color:#2f6f4e;color:#2f6f4e}.chip.flag{border-color:#1b1b1b;background:#1b1b1b;color:#fff}
.cbox{margin:8px 10px 0;border-top:1px dashed #999;padding-top:8px}.cbox textarea{width:100%%;min-height:56px;font:13px var(--sans);border:1px solid #999;padding:6px;resize:vertical}
.cbox .row{display:flex;gap:8px;align-items:center;margin-top:6px;font:12px var(--mono)}.cbox select{font:12px var(--mono)}
.old{font-size:12.5px;color:#444;margin:4px 0}.old b{font:600 11px var(--mono)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:8px 10px 0}.pair figure{margin:0}.pair .pf{position:relative;aspect-ratio:16/9;background:#111;overflow:hidden;border:1px solid #1b1b1b}
.pair .pf img{position:absolute;inset:0;width:100%%;height:100%%;object-fit:cover;display:block}.pair .pf i{position:absolute;left:4px;top:4px;font:600 10px var(--mono);letter-spacing:.1em;background:rgba(27,27,27,.85);color:#fff;padding:2px 6px}
.pair .se{font-size:12px;color:#333;margin:4px 0 0;min-height:1em}.pair button{width:100%%;margin-top:4px}.pair button.on{background:#2f6f4e;border-color:#2f6f4e;color:#fff}
.pair .meta{font:10px var(--mono);color:#666;margin-top:2px}.pill.ap{border-color:#2f6f4e;color:#2f6f4e}
table{border-collapse:collapse;width:100%%;background:#fff;font-size:13px}th,td{border:1px solid #bbb;padding:5px 8px;text-align:left;vertical-align:top}th{font:600 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;background:#eee}
td.ok{color:#2f6f4e;font-weight:600}td.fail{color:#fff;background:#1b1b1b;font-weight:600}
.notes{display:inline-block;vertical-align:top;margin:6px 24px 6px 0;max-width:420px}.notes h3{font:600 12px var(--mono);margin:0 0 4px;letter-spacing:.08em}.notes ul{margin:0;padding-left:18px;font-size:13px}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font:12px var(--mono);margin:6px 0}.toolbar input[type=text]{font:13px var(--sans);padding:4px 6px;border:1px solid #999}
button{font:600 12px var(--mono);padding:6px 12px;border:1px solid #1b1b1b;background:#fff;cursor:pointer}button.primary{background:#1b1b1b;color:#fff}
.na{background:#fff;border:2px dashed #999;padding:14px;font:12px var(--mono);color:#666}
footer{padding:0 36px 30px;font:12px var(--mono);color:#777}
@media print{.cbox,.toolbar,button{display:none}}
'''

JS = r'''
(function(){
var PACK=%(pack_json)s;
var S={pack:PACK.id,comments:(PACK.comments&&PACK.comments.comments)||[],approvals:(PACK.approvals&&PACK.approvals.approvals)||[]};
function ap(n){var a=S.approvals.filter(function(x){return x.beat===n})[0];if(!a){a={beat:n,start:false,end:false,by:'',at:''};S.approvals.push(a)}return a}
function renderApprovals(){
  $all('.pair button[data-side]').forEach(function(b){var n=+b.getAttribute('data-beat'),side=b.getAttribute('data-side'),a=ap(n);
    b.className=a[side]?'on':'';b.textContent=(a[side]?'Approved ':'Approve ')+side;var m=$('.meta[data-side="'+side+'"]',b.parentNode);if(m)m.textContent=a[side]?((a.by||'?')+' · '+(a.at||'')):''});
  var tot=$all('.pair button[data-side="end"]').length,done=S.approvals.filter(function(a){return a.end}).length;var e=$('#apcount');if(e)e.textContent=done+'/'+tot+' END approved';
}
function toggle(ev){var b=ev.currentTarget,n=+b.getAttribute('data-beat'),side=b.getAttribute('data-side'),a=ap(n);a[side]=!a[side];a.by=who();a.at=new Date().toISOString().slice(0,16).replace('T',' ');renderApprovals()}
function apPayload(){return JSON.stringify({pack:S.pack,approvals:S.approvals.filter(function(a){return a.start||a.end}).sort(function(x,y){return x.beat-y.beat})},null,1)}
var served=location.protocol==='http:'||location.protocol==='https:';
var TOKEN=(document.querySelector('meta[name="review-token"]')||{}).content||'';
function hdr(){return {'Content-Type':'application/json','X-Review-Token':TOKEN}}
function $(q,el){return (el||document).querySelector(q)}
function $all(q,el){return Array.prototype.slice.call((el||document).querySelectorAll(q))}
function who(){return ($('#who').value||'').trim()}
function render(){
  $all('.cell').forEach(function(c){var n=+c.getAttribute('data-beat');var old=$('.old-list',c);old.innerHTML='';
    S.comments.filter(function(x){return x.beat===n}).forEach(function(x){var p=document.createElement('p');p.className='old';
      p.innerHTML='<b>'+esc(x.by||'?')+' · '+esc(x.status||'open')+(x.at?' · '+esc(x.at):'')+'</b> '+esc(x.text);old.appendChild(p)})});
  var open=S.comments.filter(function(x){return x.status!=='resolved'}).length;
  $('#ccount').textContent=S.comments.length+' comments · '+open+' open';
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function collect(){
  $all('.cell').forEach(function(c){var n=+c.getAttribute('data-beat');var ta=$('textarea',c);var st=$('select',c);
    if(ta.value.trim()){S.comments.push({beat:n,by:who(),text:ta.value.trim(),status:st.value,at:new Date().toISOString().slice(0,16).replace('T',' ')});ta.value=''}});
}
function payload(){return JSON.stringify({pack:S.pack,comments:S.comments},null,1)}
function dl(name,text){var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'application/json'}));a.download=name;document.body.appendChild(a);a.click();a.remove()}
function save(){collect();render();renderApprovals();var hasPairs=$all('.pair').length>0;
  if(served){var posts=[fetch('/comments',{method:'POST',headers:hdr(),body:payload()}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.text()})];
    if(hasPairs)posts.push(fetch('/approvals',{method:'POST',headers:hdr(),body:apPayload()}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.text()}));
    Promise.all(posts).then(function(t){$('#status').textContent='saved → comments.json ('+t[0].trim()+')'+(t[1]?' · approvals.json ('+t[1].trim()+')':'')}).catch(function(e){$('#status').textContent='save failed: '+e})}
  else{dl('comments.json',payload());if(hasPairs)dl('approvals.json',apPayload());$('#status').textContent='downloaded comments.json'+(hasPairs?' + approvals.json':'')+' — put them beside index.html and rebuild the pack, or --serve to save in place'}
}
function load(ev){var f=ev.target.files[0];if(!f)return;var r=new FileReader();r.onload=function(){try{var d=JSON.parse(r.result);var seen={};S.comments.concat(d.comments||[]).forEach(function(x){seen[x.beat+'|'+x.by+'|'+x.text]=x});S.comments=Object.keys(seen).map(function(k){return seen[k]});render();$('#status').textContent='merged '+(d.comments||[]).length+' comments'}catch(e){$('#status').textContent='not a comments.json: '+e}};r.readAsText(f)}
function resolveAll(){S.comments.forEach(function(x){x.status='resolved'});render()}
document.addEventListener('DOMContentLoaded',function(){
  $('#save').addEventListener('click',save);$('#load').addEventListener('change',load);$('#resolve').addEventListener('click',resolveAll);
  $all('.cell').forEach(function(c){var n=+c.getAttribute('data-beat');$('.goto',c).addEventListener('click',function(){var r=$('#beat-span-'+n);if(r)r.scrollIntoView({block:'center'})})});
  $('#mode').textContent=served?'served · Save writes comments.json (+ approvals.json) next to the pack':'file · Save downloads comments.json (+ approvals.json)';
  $all('.pair button[data-side]').forEach(function(b){b.addEventListener('click',toggle)});
  render();renderApprovals();
});
})();
'''


def _ruler(tl, beats):
    if not tl and not beats:
        return '<div class="na">no out/timeline.json and no beat spans — run export_timeline.js or fill the storyboard spans</div>'
    total = float(tl['total']) if tl and tl.get('total') else max([b['t1'] or 0 for b in beats] + [1.0])
    total = max(total, 0.1)
    out = ['<div class="ruler">']
    for b in beats:
        s, e = b.get('actual') or (b['t0'], b['t1'])
        if s is None or e is None:
            continue
        out.append('<div class="beat %s" id="beat-span-%d" style="left:%.2f%%;width:%.2f%%" title="%s">%02d %s</div>'
                   % (b.get('real') or 'unknown', b['number'], 100 * s / total, max(0.3, 100 * (e - s) / total), _esc(b['title']), b['number'], _esc(b['title'][:14])))
    if tl:
        seam_cuts = [w.get('cut') for w in tl.get('seams', []) if isinstance(w, dict) and isinstance(w.get('cut'), (int, float))]
        for c in tl.get('cuts', []):
            if isinstance(c, (int, float)):
                kind = 'seam' if any(abs(c - sc) < 0.05 for sc in seam_cuts) else 'cut'
                out.append('<div class="%s" style="left:%.2f%%" title="%s %.2f s"></div>' % (kind, 100 * c / total, kind, c))
    step = 5 if total <= 60 else (10 if total <= 180 else 30)
    t = 0
    while t <= total:
        out.append('<div class="tick" style="left:%.2f%%">%d</div>' % (100 * t / total, t))
        t += step
    out.append('</div>')
    out.append('<p class="tag">%.1f s%s · %d cuts%s · bars: beats (dark = recorded, warm = recreated, hatched = placeholder); solid ticks = cuts, dashed = ledger seams</p>'
               % (total, ' on the narration clock' if tl else ' planned', len(tl.get('cuts', [])) if tl else 0, (' · %d seams' % len(tl.get('seams', []))) if tl and tl.get('seams') else ''))
    return ''.join(out)


def render_html(pack):
    man, g = pack['storyboard'], pack['storyboard']['globals']
    beats = man['beats']
    tok = dict(SB.DEFAULT_TOKENS if SB else {'ground': '#082A34', 'ink': '#E9F3F9', 'accent': '#E56B5E', 'muted': '#81A9AB', 'display': 'Georgia, serif', 'sans': 'Arial, sans-serif', 'mono': 'Consolas, monospace'})
    tok.update({k: v for k, v in (pack.get('design') or {}).items() if k in tok})
    claims = (pack['claims'] or {}).get('claims', []) if pack['claims'] else []
    qa = pack['qa']
    flags = pack['flags']
    nfail = sum(1 for f in flags if f['level'] == 'fail'); nwarn = sum(1 for f in flags if f['level'] == 'warn')
    qfail = [x for x in qa['gates'] if not x['ok']] if qa else []
    ncom = len(pack['comments'].get('comments', [])); nopen = sum(1 for c in pack['comments'].get('comments', []) if c.get('status') != 'resolved')
    total_planned = max([b['t1'] or 0 for b in beats] + [0])
    actual = max([b.get('actual', (0, 0))[1] for b in beats] + [0])

    H = ['<header><h1>%s <span class="v">v%s · review pack</span></h1>' % (_esc(g.get('title') or pack['name']), _esc(g.get('version', 1))),
         '<p class="dek">%s</p>' % _esc(g.get('message', '')),
         '<p class="tag">%s · %d beats · %.1f s planned%s · %s%s</p>' % (_esc(g.get('format', '1920x1080')), len(beats), total_planned,
                                                                       (' · %.1f s on the clock' % actual) if actual else '', _esc(g.get('arc', '')),
                                                                       (' · film %s' % _esc(os.path.basename(pack['film']))) if pack['film'] else ' · no rendered film yet'),
         '<div class="strip">',
         '<span class="pill %s">honesty: %d fail · %d warn</span>' % ('fail' if nfail else ('warn' if nwarn else 'ok'), nfail, nwarn),
         '<span class="pill %s">QA: %s</span>' % (('fail' if qfail else 'ok') if qa else 'warn', ('%d/%d gates pass' % (len(qa['gates']) - len(qfail), len(qa['gates']))) if qa else 'not run'),
         '<span class="pill %s">claims: %d traced</span>' % ('ok' if claims else 'warn', len(claims)),
         '<span class="pill %s">storyboard: %s</span>' % ('ok' if man['sections']['locked'] else 'warn', 'locked' if man['sections']['locked'] else 'not locked'),
         '<span class="pill" id="ccount">%d comments · %d open</span>' % (ncom, nopen),
         ('<span class="pill ap" id="apcount">%d/%d END approved</span>' % (sum(1 for a in pack['approvals']['approvals'] if a['end'] and (pack['pairs'].get(str(a['beat'])) or {}).get('end')), len([k for k, v in pack['pairs'].items() if k != 'unmapped' and v.get('end')]))) if pack.get('pairs') else '',
         '</div>',
         '<div class="toolbar">reviewer <input type="text" id="who" placeholder="your name"> <button class="primary" id="save">Save comments</button> '
         '<label><button type="button" onclick="document.getElementById(\'load\').click()">Load comments.json</button><input type="file" id="load" accept=".json" style="display:none"></label> '
         '<button id="resolve">Mark all resolved</button> <span id="mode"></span> <span id="status"></span></div>',
         '</header>']

    # honesty flags
    H.append('<section><h2>Honesty flags — decide the sign-off</h2>')
    if flags:
        H.append('<ul class="flags">' + ''.join('<li class="%s"><b>%s</b> %s</li>' % (f['level'], f['level'].upper(), _esc(f['text'])) for f in flags) + '</ul>')
    else:
        H.append('<p class="tag">none — every beat has pixels, every claim a source, every asset a licence</p>')
    H.append('</section>')

    # timeline
    H.append('<section><h2>Timeline</h2>%s</section>' % _ruler(pack['timeline'], beats))

    # beats
    H.append('<section><h2>Beats — one frame, the plan, your comment</h2>')
    if pack.get('pairs'):
        H.append('<p class="tag">first and last frame per beat from gates/snapshot.py --pairs — approve the END frame first: it is what the next cut lands on; '
                 'the build refuses while an END is unapproved%s</p>' % ((' · unmapped segments: %s' % _esc(', '.join(pack['pairs']['unmapped']))) if pack['pairs'].get('unmapped') else ''))
    if not beats:
        H.append('<div class="na">no STORYBOARD.md beats found in %s</div>' % _esc(pack['project']))
    H.append('<div class="grid">')
    for b in beats:
        f, n = b['fields'], b['number']
        badge = {'recorded': 'REAL', 'recreated': 'RECREATED', 'placeholder': 'PLACEHOLDER'}.get(b['real'], '?')
        tap = pack['taps'].get(str(n))
        if tap:
            inner = '<img src="%s" alt="beat %02d">' % (tap['src'], n)
        elif b['real'] == 'recorded':
            inner = '<div class="plate"><span>REAL · clip %s · no frame yet</span></div>' % _esc(f.get('clip', '?'))
        else:
            qs = b['quotes'] or ['— figure —']
            inner = '<div class="sk"><h1>%s</h1>%s</div>' % (_esc(qs[0]), ''.join('<p>%s</p>' % _esc(q) for q in qs[1:4]))
        span = b.get('actual') or (b['t0'], b['t1'])
        vo = f.get('vo', '')
        mine = [c for c in claims if c.get('phrase') and c['phrase'] in vo]
        bflags = [x for x in flags if x['beat'] == n]
        rows = ''.join('<p><b>%s</b>%s</p>' % (k, _esc(f[k])) for k in ('screen', 'camera', 'motion', 'seam', 'caption', 'constraint', 'why') if f.get(k))
        pr = (pack.get('pairs') or {}).get(str(n))
        pair_html = ''
        if pr:
            pair_html = '<div class="pair">' + ''.join(
                ('<figure><div class="pf"><img src="%s" alt="beat %02d %s"><i>%s · %.2f s</i></div><p class="se">%s</p>'
                 '<button type="button" data-beat="%d" data-side="%s">Approve %s</button><div class="meta" data-side="%s"></div></figure>'
                 % (pr[side]['src'], n, side, side.upper(), pr[side]['t'], _esc(f.get(side) or ('— no %s: line in the storyboard —' % side)), n, side, side, side))
                if pr.get(side) else
                ('<figure><div class="pf"><i>%s · in the %s beat</i></div><p class="se">%s</p></figure>'
                 % (side.upper(), 'previous' if side == 'start' else 'next', _esc(f.get(side) or '— this beat shares its segment; the %s frame belongs to its neighbour —' % side)))
                for side in ('start', 'end')) + '</div>'
        elif f.get('start') or f.get('end'):
            pair_html = '<div class="fields">' + ''.join('<p><b>%s</b>%s</p>' % (k, _esc(f[k])) for k in ('start', 'end') if f.get(k)) + '</div>'

        H.append(
            '<figure class="cell" id="beat-%02d" data-beat="%d"><div class="frame">%s<span class="badge %s">%s</span><i class="keepout"></i></div>'
            '<div class="lab"><span>%02d · %s</span><span>%s · %s–%s s</span></div>'
            '<div class="fields">%s%s</div>%s<div class="chips">%s%s<span class="chip goto" style="cursor:pointer">▸ timeline</span></div>'
            '<div class="cbox"><div class="old-list"></div><textarea placeholder="comment on beat %02d — what changes, or “approved”"></textarea>'
            '<div class="row">status <select><option value="open">open</option><option value="resolved">resolved</option></select>'
            '<span>%s</span></div></div></figure>'
            % (n, n, inner, b['real'] or 'unknown', badge, n, _esc(b['title'].upper()), _esc(f.get('phase', 'beat')), _fmt_t(span[0]), _fmt_t(span[1]),
               ('<p class="vo"><b>%s</b>“%s”</p>' % (_esc(f.get('voice', 'vo')), _esc(vo))) if vo else '', rows, pair_html,
               ''.join('<span class="chip claim" title="%s">claim · %s</span>' % (_esc(c.get('source', '')), _esc(c['phrase'][:28])) for c in mine),
               ''.join('<span class="chip flag">%s</span>' % _esc(x['level']) for x in bflags), n,
               _esc(tap['path'] if tap and not tap['src'].startswith('data:') else (os.path.basename(tap['path']) if tap else 'no frame'))))
    H.append('</div></section>')

    # claims
    H.append('<section><h2>Claims — every spoken figure and where it is on screen</h2>')
    if pack['claims'] is None:
        H.append('<div class="na">claims.json missing</div>')
    else:
        H.append('<table><tr><th>#</th><th>phrase (verbatim in the narration)</th><th>on-screen source</th><th>beat</th></tr>')
        for i, c in enumerate(claims, 1):
            bn = [b['number'] for b in beats if c.get('phrase') and c['phrase'] in b['fields'].get('vo', '')]
            H.append('<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (i, _esc(c.get('phrase')), _esc(c.get('source') or '— none —'), ', '.join('%02d' % x for x in bn) or '—'))
        H.append('</table>')
        dropped = pack['claims'].get('dropped_from_the_original_narration', [])
        if dropped:
            H.append('<p class="tag">dropped from the original narration: %s</p>' % _esc('; '.join(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False) for d in dropped)))
    H.append('</section>')

    # QA
    H.append('<section><h2>QA report</h2>')
    if qa is None:
        H.append('<div class="na">no QA report — run qa_film.py and keep its output as out/qa.log (or write out/qa_report.json)</div>')
    else:
        H.append('<table><tr><th>gate</th><th>result</th><th>detail</th></tr>' + ''.join(
            '<tr><td>%s</td><td class="%s">%s</td><td>%s</td></tr>' % (_esc(x['name']), 'ok' if x['ok'] else 'fail', 'PASS' if x['ok'] else 'FAIL', _esc(x['detail'])) for x in qa['gates']) + '</table>')
        H.append('<p class="tag">source: %s</p>' % _esc(_rel(qa['path'], pack['project'])))
    H.append('</section>')

    # ledger
    H.append('<section><h2>Media ledger</h2>')
    if pack['ledger'] is None:
        H.append('<div class="na">media.jsonl missing — tools/ledger.py adopt</div>')
    else:
        H.append('<table><tr><th>kind</th><th>path</th><th>source</th><th>licence</th><th>commercial</th><th>used in</th></tr>' + ''.join(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                _esc(r.get('kind')), _esc(r.get('path')), _esc((r.get('source') or {}).get('kind')), _esc((r.get('licence') or {}).get('name')),
                _esc((r.get('licence') or {}).get('commercial_ok')), _esc(', '.join(r.get('used_in') or []))) for r in pack['ledger']) + '</table>')
    H.append('</section>')

    # storyboard notes
    H.append('<section><h2>Storyboard notes</h2>')
    for title, items in (('Video direction', man['sections']['direction']), ('Decisions', man['sections']['decisions']),
                         ('Changes', [x for c in man['sections']['changes'] for x in ['<b>%s</b>' % _esc(c['from'])] + [_esc(n) for n in c['notes']]]),
                         ('Still open', [_esc(x) for x in man['sections']['still_open']]), ('Locked', [_esc(x) for x in man['sections']['locked']])):
        if items:
            H.append('<div class="notes"><h3>%s</h3><ul>%s</ul></div>' % (title, ''.join('<li>%s</li>' % (x if title in ('Changes', 'Still open', 'Locked') else _esc(x)) for x in items)))
    if pack['brief']:
        H.append('<div class="notes"><h3>Brief</h3><ul>%s</ul></div>' % ''.join('<li><b>%s</b> %s</li>' % (_esc(k), _esc(pack['brief'][k])) for k in ('message', 'audience', 'destination', 'honesty_line', 'review', 'narration') if k in pack['brief']))
    H.append('</section>')

    pack_json = json.dumps({'id': pack['id'], 'comments': pack['comments'], 'approvals': pack['approvals']}, sort_keys=True, ensure_ascii=False).replace('</', '<\\/')
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>%s — review pack v%s</title>'
            '<style>%s</style></head><body>%s<footer>generated by tools/review_pack.py from the project files — offline, no external requests; '
            'comments are yours (comments.json). The pack is not a source of timing truth: the narration clock is.</footer><script>%s</script></body></html>'
            % (_esc(g.get('title') or pack['name']), _esc(g.get('version', 1)), CSS % tok, ''.join(H), JS % {'pack_json': pack_json}))
    return html


def build(project, out_html=None, film=None, taps=None, qa=None, comments=None, embed=True):
    pack = collect(project, film, taps, qa, comments, out_html, embed)
    html = render_html(pack)
    out = pack['out_html']
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(html)
    pack['sha256'] = hashlib.sha256(html.encode('utf-8')).hexdigest()
    pack['bytes'] = len(html.encode('utf-8'))
    return pack


# ------------------------------------------------------------------------------------------------ lock
def lock_storyboard(sb_path, by, date, pack_html=None, comments=None, force=False):
    """Write the sign-off into ## Locked (created when missing). Returns (ok, message, open_comments)."""
    text = _read(sb_path)
    if text is None:
        return False, 'missing %s' % sb_path, []
    com = (comments or {}).get('comments', [])
    open_c = [c for c in com if c.get('status') != 'resolved']
    if open_c and not force:
        return False, '%d comment(s) still open — resolve them in the pack or pass --force' % len(open_c), open_c
    sha = ''
    if pack_html and os.path.exists(pack_html):
        with open(pack_html, 'rb') as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()[:12]
    lines = ['- signed off by: %s' % by, '- signed off date: %s' % date,
             '- review pack: %s%s' % (os.path.basename(pack_html) if pack_html else '—', (' · sha256 %s' % sha) if sha else ''),
             '- comments: %d total, %d resolved, %d open%s' % (len(com), len(com) - len(open_c), len(open_c), ' (forced)' if open_c else '')]
    body = text.rstrip('\n').split('\n')
    # drop earlier sign-off bullets anywhere in the Locked section, then append the new ones to it
    idx = next((i for i, ln in enumerate(body) if re.match(r'^##\s+Locked\b', ln, re.I)), None)
    if idx is None:
        body += ['', '## Locked'] + lines
    else:
        end = next((j for j in range(idx + 1, len(body)) if re.match(r'^##\s', body[j])), len(body))
        sect = [ln for ln in body[idx + 1:end] if not re.match(r'^\s*-\s*(signed off by|signed off date|review pack|comments):', ln, re.I)]
        while sect and not sect[-1].strip():
            sect.pop()
        body = body[:idx + 1] + sect + lines + ([''] if end < len(body) else []) + body[end:]
    with open(sb_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(body) + '\n')
    return True, 'locked: %s signed off %s (%d comments, %d open)' % (by, date, len(com), len(open_c)), open_c


# ------------------------------------------------------------------------------------------------ serve
def make_server(directory, comments_path, port=8765, host='127.0.0.1', approvals_path=None, token=None):
    """The review server. Local only, and defended against a page from another origin writing into the pack:
    Host must be 127.0.0.1:<port> / localhost:<port> (GET and POST); a POST must be application/json, its Origin one
    of http://127.0.0.1:<port> / http://localhost:<port>, and it must carry the session token the served index.html
    embeds (<meta name="review-token">) as X-Review-Token. Anything else: 403. `server.token` holds the token."""
    import http.server
    os.makedirs(directory, exist_ok=True)
    approvals_path = approvals_path or os.path.join(directory, 'approvals.json')
    token = token or secrets.token_hex(16)
    G = {'hosts': set(), 'origins': set()}           # filled once the port is known (port=0 picks a free one)

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=directory, **k)

        def log_message(self, *a):
            pass

        def _host_ok(self):
            return (self.headers.get('Host') or '').strip().lower() in G['hosts']

        def do_GET(self):
            if not self._host_ok():
                self.send_error(403, 'bad Host'); return
            route = self.path.split('?', 1)[0]
            if route in ('/', '/index.html'):
                p = os.path.join(directory, 'index.html')
                if not os.path.exists(p):
                    self.send_error(404); return
                html = open(p, encoding='utf-8').read()
                html = html.replace('<head>', '<head><meta name="review-token" content="%s">' % token, 1).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(html)))
                self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(html); return
            super().do_GET()

        def _reject(self, code, msg, n):
            # drain the body first so the client reads the status instead of a reset connection
            if 0 < n <= MAX_POST:
                self.rfile.read(n)
            self.send_error(code, msg)

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            if not self._host_ok():
                self._reject(403, 'bad Host', n); return
            origin = (self.headers.get('Origin') or '').strip().lower().rstrip('/')
            if origin not in G['origins']:
                self._reject(403, 'bad Origin', n); return
            if not (self.headers.get('Content-Type') or '').lower().startswith('application/json'):
                self._reject(403, 'application/json only', n); return
            if not secrets.compare_digest(self.headers.get('X-Review-Token') or '', token):
                self._reject(403, 'missing or wrong X-Review-Token', n); return
            route = self.path.rstrip('/')
            if route not in ('/comments', '/approvals'):
                self._reject(404, 'not found', n); return
            key, dest = ('comments', comments_path) if route == '/comments' else ('approvals', approvals_path)
            if n > MAX_POST:
                self.send_error(413); return
            raw = self.rfile.read(n)
            try:
                d = json.loads(raw.decode('utf-8'))
                assert isinstance(d, dict) and isinstance(d.get(key), list)
                if key == 'approvals':
                    assert all(isinstance(a, dict) and isinstance(a.get('beat'), int) for a in d[key])
            except Exception:
                self.send_error(400, '%s.json must be {pack, %s:[...]}' % (key, key)); return
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            with open(dest, 'w', encoding='utf-8', newline='\n') as fh:
                json.dump(d, fh, indent=1, sort_keys=True, ensure_ascii=False); fh.write('\n')
            body = ('%d %s' % (len(d[key]), key)).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'text/plain; charset=utf-8'); self.send_header('Content-Length', str(len(body))); self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer((host, port), H)
    real = srv.server_address[1]
    G['hosts'] = {'127.0.0.1:%d' % real, 'localhost:%d' % real}
    G['origins'] = {'http://127.0.0.1:%d' % real, 'http://localhost:%d' % real}
    srv.token = token
    return srv


# ------------------------------------------------------------------------------------------------ selftest
def _synthetic_project(d):
    """A fictional Acme project: the template storyboard/claims/ledger + a synthetic qa log, timeline and taps."""
    import shutil
    from PIL import Image, ImageDraw
    T = os.path.join(FILM_DIR, 'templates')
    shutil.copy(os.path.join(T, 'STORYBOARD.example.md'), os.path.join(d, 'STORYBOARD.md'))
    shutil.copy(os.path.join(T, 'BRIEF.example.md'), os.path.join(d, 'BRIEF.md'))
    shutil.copy(os.path.join(FILM_DIR, 'claims.example.json'), os.path.join(d, 'claims.json'))
    shutil.copy(os.path.join(T, 'media.example.jsonl'), os.path.join(d, 'media.jsonl'))
    shutil.copy(os.path.join(T, 'design.example.md'), os.path.join(d, 'design.md'))
    with open(os.path.join(d, 'film.json'), 'w', encoding='utf-8') as fh:
        json.dump({'name': 'film', 'output': 'out/Acme_Monday_Film.mp4', 'ledger': 'media.jsonl'}, fh)
    os.makedirs(os.path.join(d, 'out', 'taps'), exist_ok=True)
    with open(os.path.join(d, 'out', 'timeline.json'), 'w', encoding='utf-8') as fh:
        json.dump({'total': 32.3, 'cuts': [7.4, 12.4, 18.6, 28.2], 'seams': [{'cut': 12.4}, {'cut': 28.2}], 'phases': []}, fh)
    with open(os.path.join(d, 'out', 'qa.log'), 'w', encoding='utf-8') as fh:
        fh.write('QA  out/Acme_Monday_Film.mp4\n  container          PASS  1920x1080 30/1\n  duration           PASS  film 33.10 s vs narration 32.30 s\n'
                 '  claims traced      FAIL  unbacked [\'counts them by region\']\n  seam ledger        PASS  2 rows\n  CREDIT             PASS  "Crafted with FDE Demo Builder · by Ahmed Awan" on the end screen (mandatory)\n\nFAILED: claims traced  (1 failed)\n')
    for n, col in ((1, (8, 42, 52)), (3, (238, 239, 241)), (4, (238, 239, 241))):
        im = Image.new('RGB', (1280, 720), col); dr = ImageDraw.Draw(im)
        dr.rectangle([80, 80, 1200, 640], outline=(229, 107, 94), width=6); dr.text((100, 100), 'synthetic tap %02d' % n, fill=(120, 120, 120))
        im.save(os.path.join(d, 'out', 'taps', '%02d_tap.jpg' % n), quality=85)
    Image.new('RGB', (1280, 720), (32, 74, 86)).save(os.path.join(d, 'out', 'taps', 't28.0.jpg'), quality=85)     # → beat 05 (26.5–31.3 s) by time
    # first/last frame pairs (gates/snapshot.py --pairs shape): title → beat 01, two notebook segments → beat 03, close → beat 06
    pd = os.path.join(d, 'out', 'pairs'); os.makedirs(pd, exist_ok=True)
    rows = []
    for lab, t0, t1, static in (('title', 0.0, 7.4, False), ('nb', 13.6, 17.0, False), ('nb_2', 17.0, 21.8, True), ('close', 31.3, 35.4, False)):
        row = {'label': lab, 't0': t0, 't1': t1, 'changed_pct': 0.1 if static else 12.0, 'static': static}
        for side, t, col in (('start', t0 + 0.1, (40, 60, 80)), ('end', t1 - 0.1, (200, 120, 90))):
            f = os.path.join(pd, '%s_%s.jpg' % (lab, side))
            im = Image.new('RGB', (960, 540), col); ImageDraw.Draw(im).text((20, 20), '%s %s' % (lab, side), fill=(255, 255, 255)); im.save(f, quality=80)
            row[side] = {'t': round(t, 3), 'file': f}
        rows.append(row)
    json.dump({'total': 35.4, 'pairs': rows, 'errors': [], 'ok': True}, open(os.path.join(pd, 'pairs.json'), 'w'))
    return d


def selftest():
    import tempfile, time, urllib.request, urllib.error
    d = _synthetic_project(tempfile.mkdtemp(prefix='review_pack_'))
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)

    p1 = build(d); h1 = p1['sha256']
    p2 = build(d); h2 = p2['sha256']
    t(h1 == h2, 'deterministic: two builds byte-identical (sha256 %s…, %d KB)' % (h1[:12], p1['bytes'] // 1024))
    html = _read(p1['out_html'])
    t(len(p1['taps']) == 4 and '5' in p1['taps'] and '1' in p1['taps'], 'taps mapped by number (01,03,04) and by time (t28.0 → beat 05): %s' % sorted(p1['taps']))
    t('http://' not in html.replace('http://www.w3.org', '') and 'https://' not in html.split('<body>')[0] and html.count('data:image/jpeg') == 4 + 6, 'offline: 4 embedded taps + 6 pair frames, no external request in the head')
    t(any(f['level'] == 'fail' and 'claims traced' in f['text'] for f in p1['flags']), 'honesty flags: the failing claims gate is a FAIL flag')
    t(any('UNKNOWN' in f['text'] for f in p1['flags']) is False and any('still open' in f['text'] for f in p1['flags']), 'honesty flags: licensed ledger clean, still-open item listed')
    t(p1['qa'] and len(p1['qa']['gates']) == 5 and sum(1 for g in p1['qa']['gates'] if not g['ok']) == 1, 'qa log parsed: 5 gates, 1 FAIL')
    t('Which regions missed their on-time delivery target last week?' in html and 'class="chip claim"' in html, 'claims table + per-beat claim chips rendered')
    t('class="ruler"' in html and html.count('class="cut"') == 2 and html.count('class="seam"') == 2, 'timeline ruler: 2 plain cuts + 2 seam cuts')
    # serve + POST comments
    srv = make_server(os.path.dirname(p1['out_html']), p1['comments_path'], port=0)
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    port = srv.server_address[1]
    payload = json.dumps({'pack': p1['id'], 'comments': [{'beat': 3, 'by': 'Reviewer', 'text': 'push lands late', 'status': 'open', 'at': '2026-01-01 09:00'}]}).encode('utf-8')
    GOOD = {'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:%d' % port, 'X-Review-Token': srv.token}

    def post(path, body, headers, host=None):
        h = dict(headers)
        if host:
            h['Host'] = host
        try:
            return urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d%s' % (port, path), data=body, headers=h, method='POST'), timeout=5).read().decode('utf-8'), 200
        except urllib.error.HTTPError as e:
            return '', e.code
    resp, code = post('/comments', payload, GOOD)
    got = urllib.request.urlopen('http://127.0.0.1:%d/index.html' % port, timeout=5).read()
    bad_host = post('/comments', payload, GOOD, host='evil.example:%d' % port)[1]
    bad_origin = post('/comments', payload, dict(GOOD, Origin='http://evil.example'))[1]
    no_token = post('/comments', payload, {k: v for k, v in GOOD.items() if k != 'X-Review-Token'})[1]
    wrong_token = post('/comments', payload, dict(GOOD, **{'X-Review-Token': 'nope'}))[1]
    text_body = post('/comments', payload, dict(GOOD, **{'Content-Type': 'text/plain'}))[1]
    try:
        urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/index.html' % port, headers={'Host': 'evil.example:%d' % port}), timeout=5); get_bad = 200
    except urllib.error.HTTPError as e:
        get_bad = e.code
    srv.shutdown(); srv.server_close()
    saved = _load_json(p1['comments_path'], {})
    t(code == 200 and resp.strip() == '1 comments' and saved.get('comments', [{}])[0].get('beat') == 3 and b'name="review-token"' in got and srv.token.encode() in got,
      '--serve: a same-origin POST with the session token saved comments.json; GET served the pack with the token embedded (%d bytes)' % len(got))
    t((bad_host, bad_origin, no_token, wrong_token, text_body, get_bad) == (403, 403, 403, 403, 403, 403),
      '--serve refuses: wrong Host %d · wrong Origin %d · missing token %d · wrong token %d · text/plain body %d · GET with wrong Host %d' % (bad_host, bad_origin, no_token, wrong_token, text_body, get_bad))
    p3 = build(d)
    t('push lands late' in _read(p3['out_html']), 'rebuilt pack embeds the saved comment')
    # first/last frame pairs mapped to beats + approvals round trip
    pr = p1['pairs']
    t(pr and sorted(k for k in pr if k != 'unmapped') == ['1', '3', '6'] and pr['3']['labels'] == ['nb', 'nb_2'] and pr['3']['static'] is True
      and abs(pr['3']['start']['t'] - 13.7) < 1e-6 and abs(pr['3']['end']['t'] - 21.7) < 1e-6, 'pairs: segments mapped to beats 01/03/06; beat 03 opens on nb START, leaves on nb_2 END (%s)' % sorted(pr or {}))
    t(html.count('class="pair"') == 3 and html.count('<button type="button" data-beat=') == 6 and 'Approve end' in html, 'pairs rendered: 3 beats x (start | end) with 6 Approve buttons')
    t(any('END frame not approved' in f['text'] and f['beat'] == 6 for f in p1['flags']) and any('nothing moved' in f['text'] and f['beat'] == 3 for f in p1['flags']), 'honesty flags: unapproved END and a static shot are warnings')
    srv2 = make_server(os.path.dirname(p1['out_html']), p1['comments_path'], port=0, approvals_path=p1['approvals_path'])
    th2 = threading.Thread(target=srv2.serve_forever, daemon=True); th2.start()
    port2 = srv2.server_address[1]
    apl = json.dumps({'pack': p1['id'], 'approvals': [{'beat': 1, 'start': True, 'end': True, 'by': 'R', 'at': '2026-01-01 09:00'}, {'beat': 3, 'end': True, 'by': 'R', 'at': '2026-01-01 09:01'}]}).encode('utf-8')
    GOOD2 = {'Content-Type': 'application/json', 'Origin': 'http://localhost:%d' % port2, 'X-Review-Token': srv2.token}
    resp2 = urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/approvals' % port2, data=apl, headers=dict(GOOD2, Host='localhost:%d' % port2), method='POST'), timeout=5).read().decode('utf-8')
    bad = None
    try:
        urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/approvals' % port2, data=b'{"approvals": [{"beat": "x"}]}', headers=GOOD2, method='POST'), timeout=5)
    except urllib.error.HTTPError as e:
        bad = e.code
    srv2.shutdown(); srv2.server_close()
    t(resp2.strip() == '2 approvals' and os.path.exists(p1['approvals_path']) and bad == 400, 'POST /approvals saved approvals.json; a malformed beat is refused (400)')
    p4 = build(d)
    t(len(p4['approvals']['approvals']) == 2 and p4['approvals']['approvals'][1]['beat'] == 3 and '2/3 END approved' in _read(p4['out_html']) and not any('END frame not approved' in f['text'] and f['beat'] in (1, 3) for f in p4['flags']),
      'rebuilt pack carries the approvals (2/3 END approved) and drops their flags')
    if SB:
        man4 = SB.parse(_read(os.path.join(d, 'STORYBOARD.md')))
        E_a = SB.check(man4, autonomous=True, build=True, approvals=SB.load_approvals(p4['approvals_path']))[0]
        t(any('beat 06: END frame not approved' in e for e in E_a) and not any('beat 01: END' in e or 'beat 03: END' in e for e in E_a), 'storyboard.py check --build reads the same approvals.json and refuses on beat 06')
    # lock refuses while open, then signs off
    sbp = os.path.join(d, 'STORYBOARD.md')
    ok1, msg1, _ = lock_storyboard(sbp, 'Reviewer', '2026-01-02', p3['out_html'], saved)
    t(not ok1 and 'open' in msg1, 'lock refused with an open comment: %s' % msg1)
    saved['comments'][0]['status'] = 'resolved'
    ok2, msg2, _ = lock_storyboard(sbp, 'Reviewer', '2026-01-02', p3['out_html'], saved)
    sbt = _read(sbp)
    t(ok2 and '- signed off by: Reviewer' in sbt and '- signed off date: 2026-01-02' in sbt and sbt.count('## Locked') == 1, 'lock wrote the sign-off into ## Locked once')
    ok3, _, _ = lock_storyboard(sbp, 'Reviewer', '2026-01-03', p3['out_html'], saved)
    sbt = _read(sbp)
    t(ok3 and sbt.count('signed off by') == 1 and '2026-01-03' in sbt, 'lock is idempotent (re-sign replaces the bullets)')
    if SB:
        E, W = SB.check(SB.parse(sbt), autonomous=False)[:2]
        t(not any('Locked' in e for e in E), 'storyboard.py check accepts the locked plan')
    # empty project → pack still builds with "not available" cards
    e = tempfile.mkdtemp(prefix='review_pack_empty_')
    pe = build(e)
    t(pe['bytes'] > 2000 and 'STORYBOARD.md not found' in str(pe['storyboard']['warnings']), 'empty project: pack still builds (%d bytes) with missing-artefact cards' % pe['bytes'])
    print('selftest %s  (%s)' % ('PASS' if ok else 'FAIL', d))
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ CLI
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='review_pack.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', choices=['build'], help='build the pack (default when --serve/--lock are absent)')
    ap.add_argument('--project', default=os.getcwd())
    ap.add_argument('--out', help='pack HTML (default out/review/index.html)')
    ap.add_argument('--film', help='rendered film for midpoint frames when no taps exist')
    ap.add_argument('--taps', help='directory of frame taps (default out/taps)')
    ap.add_argument('--qa', help='out/qa_report.json or a saved qa_film.py log')
    ap.add_argument('--comments', help='comments.json (default beside the pack)')
    ap.add_argument('--no-embed', dest='embed', action='store_false', help='link images relatively instead of embedding')
    ap.add_argument('--strict', action='store_true', help='exit 1 when any FAIL honesty flag exists')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--serve', action='store_true', help='serve the pack directory and accept POST /comments')
    ap.add_argument('--dir', help='directory to serve (default the pack directory)')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--lock', action='store_true', help='write the sign-off block into STORYBOARD.md')
    ap.add_argument('--by', help='--lock: who signs off')
    ap.add_argument('--date', help='--lock: sign-off date YYYY-MM-DD (default: today)')
    ap.add_argument('--force', action='store_true', help='--lock even with open comments')
    a = ap.parse_args(argv)
    project = os.path.abspath(a.project)
    out_html = os.path.abspath(a.out) if a.out else os.path.join(project, 'out', 'review', 'index.html')
    comments_path = os.path.abspath(a.comments) if a.comments else os.path.join(os.path.dirname(out_html), 'comments.json')

    if a.lock:
        if not a.by:
            print('--lock needs --by "Name"', file=sys.stderr); return 2
        date = a.date
        if not date:
            import datetime
            date = datetime.date.today().isoformat()
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            print('--date must be YYYY-MM-DD', file=sys.stderr); return 2
        ok, msg, open_c = lock_storyboard(os.path.join(project, 'STORYBOARD.md'), a.by, date, out_html if os.path.exists(out_html) else None, _load_json(comments_path, {}), a.force)
        if a.json:
            print(json.dumps({'ok': ok, 'message': msg, 'open': open_c}, indent=1, ensure_ascii=False))
        else:
            print(msg)
            for c in open_c[:10]:
                print('  open  beat %02d  %s: %s' % (c.get('beat') or 0, c.get('by', '?'), c.get('text', '')[:80]))
        return 0 if ok else 1

    if a.serve:
        directory = os.path.abspath(a.dir) if a.dir else os.path.dirname(out_html)
        if not os.path.exists(os.path.join(directory, 'index.html')):
            build(project, out_html, a.film, a.taps, a.qa, comments_path, a.embed)
        approvals_path = os.path.join(os.path.dirname(out_html), 'approvals.json')
        srv = make_server(directory, comments_path, a.port, approvals_path=approvals_path)
        print('serving %s at http://127.0.0.1:%d/  (POST /comments → %s; POST /approvals → %s; same-origin + session token only)  Ctrl-C to stop' % (directory, srv.server_address[1], comments_path, approvals_path))
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
        return 0

    pack = build(project, out_html, a.film, a.taps, a.qa, comments_path, a.embed)
    nfail = sum(1 for f in pack['flags'] if f['level'] == 'fail')
    if a.json:
        print(json.dumps({'out': pack['out_html'], 'sha256': pack['sha256'], 'bytes': pack['bytes'], 'beats': len(pack['storyboard']['beats']),
                          'taps': {k: v['path'] for k, v in pack['taps'].items()}, 'flags': pack['flags'],
                          'qa': {'gates': len(pack['qa']['gates']), 'failed': [g['name'] for g in pack['qa']['gates'] if not g['ok']]} if pack['qa'] else None,
                          'comments': len(pack['comments'].get('comments', []))}, indent=1, ensure_ascii=False))
    else:
        print('pack   %s  (%d KB, sha256 %s…)' % (pack['out_html'], pack['bytes'] // 1024, pack['sha256'][:12]))
        print('beats  %d · frames %d · claims %d · qa %s · comments %d%s' % (len(pack['storyboard']['beats']), len(pack['taps']),
              len((pack['claims'] or {}).get('claims', [])), ('%d gates' % len(pack['qa']['gates'])) if pack['qa'] else 'none', len(pack['comments'].get('comments', [])),
              (' · pairs %d beats, %d END approved' % (len([k for k in pack['pairs'] if k != 'unmapped']), sum(1 for x in pack['approvals']['approvals'] if x['end']))) if pack.get('pairs') else ''))
        for f in pack['flags']:
            print('  %-4s  %s' % (f['level'].upper(), f['text']))
    return 1 if (a.strict and nfail) else 0


if __name__ == '__main__':
    sys.exit(main())
