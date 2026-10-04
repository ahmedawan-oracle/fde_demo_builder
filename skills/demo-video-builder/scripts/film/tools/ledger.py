# -*- coding: utf-8 -*-
"""ledger.py — media.jsonl, the per-film ledger of every asset that goes into a film (v4, media area).

A booth or customer film ships music, SFX, fonts, b-roll stills and a product recording. The ledger answers
"where did that track / font / clip come from, and can we show it?" in one command, and lets the QA gate
`gates/ledger_gate.py` refuse a film whose bed has no licence on file.

    python tools/ledger.py adopt  [--project DIR] [--by NAME]           bulk-register existing assets (ffprobe facts,
                                                                         sha256); music/sfx/font/image start UNKNOWN
    python tools/ledger.py add    <path> --kind music --licence "..." [--licence-url U] [--attribution A]
                                  [--commercial-ok yes|no] [--source licensed|recording|extracted|generated|bundled|existing]
                                  [--url SRC] [--description D] [--by NAME] [--used-in FILM]
    python tools/ledger.py list   [--kind K] [--unknown] [--json]
    python tools/ledger.py index                                         regenerate media_index.md
    python tools/ledger.py used   <path> <film>                          mark an asset as used in a deliverable
    python tools/ledger.py check                                         exit 1 on any UNKNOWN licence or stale sha256
    python tools/ledger.py --selftest

Record (one JSON object per line; `path` is POSIX-relative to the project):

    {"id": "music_001", "kind": "music", "path": "music/bed.mp3", "sha256": "…", "bytes": 1234567,
     "probe": {"duration": 92.3, "sample_rate": 48000, "channels": 2, "codec": "mp3"},
     "source": {"kind": "licensed", "url": "https://…", "recording": null, "window": null, "provider": null},
     "licence": {"name": "Pixabay Content License", "url": "https://…", "attribution": "", "commercial_ok": true},
     "description": "bed", "added_by": "ahmed", "date": "2026-10-01T12:00:00Z", "used_in": ["out/Acme_Film.mp4"]}

Rules:
  * append-only and keyed by path: the LAST record for a path is the file's record; history survives rejections;
  * ids are <kind>_NNN (zero-padded to 3); duration is stored rounded to 0.1 s (QA keeps using vo/<name>_phases.json);
  * writes are serialised by a lock file beside the ledger: 15 s stale-steal, 20 s acquire timeout;
  * malformed lines are skipped, never fatal; media_index.md is regenerated after every write;
  * kinds: music | sfx | footage | image | font | voice | deliverable (the last one is written by tools/export.py);
  * music / sfx / font / image need a licence; footage is "Own recording"; voice is "Generated speech (edge-tts)".
  * adopt is idempotent (skips paths already registered unless the file changed) and never matches by fuzzy words.
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, time
from contextlib import contextmanager

KINDS = ('music', 'sfx', 'footage', 'image', 'font', 'voice', 'deliverable')
LICENSABLE = ('music', 'sfx', 'font', 'image')          # kinds that must carry a real licence before QA passes
UNKNOWN = 'UNKNOWN'
LOCK_STALE_S, LOCK_TIMEOUT_S = 15.0, 20.0
LEDGER_FILE, INDEX_FILE = 'media.jsonl', 'media_index.md'

AUDIO_EXT = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp'}
VIDEO_EXT = {'.mp4', '.webm', '.mov', '.mkv'}
FONT_EXT = {'.ttf', '.otf', '.woff', '.woff2'}
SCAN_DIRS = ('vo', 'broll', 'music', 'assets', 'sfx', 'fonts', 'images', 'img', 'logo')
SKIP_DIRS = {'out', 'node_modules', '.history', '__pycache__', '.git', '.media', 'snap'}
SKIP_NAMES = {'clips.js', 'meta.json'}

DEFAULT_LICENCE = {
    'footage': {'name': 'Own recording', 'url': '', 'attribution': '', 'commercial_ok': True},
    'voice': {'name': 'Generated speech (edge-tts)', 'url': '', 'attribution': '', 'commercial_ok': True},
    'deliverable': {'name': 'Derived from this film', 'url': '', 'attribution': '', 'commercial_ok': True},
}


# ----------------------------------------------------------------------------------------------- helpers
def posix_rel(project, path):
    """Project-relative POSIX path (the ledger never stores backslashes or absolute paths). Directories end with '/'."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(project)).replace('\\', '/')
    return rel + '/' if os.path.isdir(os.path.join(project, rel)) and not rel.endswith('/') else rel


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


def sha256_dir(path):
    """Digest of a footage directory (broll/<clip>/): sha256 over sorted "relname sha256" lines. Returns (hex, bytes, n)."""
    h, total, n = hashlib.sha256(), 0, 0
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, path).replace('\\', '/')
            h.update(('%s %s\n' % (rel, sha256_file(p))).encode('utf-8'))
            total += os.path.getsize(p); n += 1
    return h.hexdigest(), total, n


def ffprobe_facts(path):
    """Container/stream facts via ffprobe: duration (0.1 s), width, height, codec, sample_rate, channels. Images fall
    back to Pillow; fonts and unknown files return {}. Never raises."""
    facts = {}
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration,format_name:stream=codec_type,codec_name,width,height,sample_rate,channels',
                            '-of', 'json', path], capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or '{}')
        fmt = j.get('format', {})
        if fmt.get('duration') not in (None, 'N/A'):
            facts['duration'] = round(float(fmt['duration']), 1)
        if fmt.get('format_name'):
            facts['container'] = fmt['format_name'].split(',')[0]
        for s in j.get('streams', []):
            if s.get('codec_type') == 'video' and 'width' not in facts:
                facts['width'], facts['height'], facts['codec'] = int(s.get('width', 0)), int(s.get('height', 0)), s.get('codec_name')
            elif s.get('codec_type') == 'audio' and 'sample_rate' not in facts:
                facts['sample_rate'] = int(s.get('sample_rate', 0)); facts['channels'] = int(s.get('channels', 0))
                facts.setdefault('codec', s.get('codec_name'))
    except Exception:
        pass
    if 'width' not in facts and os.path.splitext(path)[1].lower() in IMAGE_EXT:
        try:
            from PIL import Image
            with Image.open(path) as im:
                facts['width'], facts['height'] = im.size
        except Exception:
            pass
    return facts


def infer_kind(rel):
    """Kind from folder + extension (POSIX-relative path). None = not a media asset (configs, scripts, renders)."""
    low = rel.lower()
    base, ext = os.path.basename(low), os.path.splitext(low)[1]
    if base in SKIP_NAMES or re.search(r'\.part\d+\.mp4$', low) or low.startswith('out/'):
        return None
    if ext in FONT_EXT:
        return 'font'
    if ext in AUDIO_EXT:
        if low.startswith('vo/') or '/voice/' in low or '/narrat' in low or re.match(r'^vo_[^/]+\.mp3$', low):
            return 'voice'
        if low.startswith('sfx/') or '/sfx/' in low or '/sound' in low:
            return 'sfx'
        return 'music'                                  # music/, bgm/, assets/… default for audio
    if ext in VIDEO_EXT:
        return 'footage'
    if ext in IMAGE_EXT:
        if low.startswith('broll/') or '/broll/' in low:
            return 'footage'                            # extracted real pixels
        return 'image'
    return None


def default_licence(kind):
    return dict(DEFAULT_LICENCE.get(kind) or {'name': UNKNOWN, 'url': '', 'attribution': '', 'commercial_ok': None})


def licence_ok(rec):
    """A record is cleared when its licence name is present and not UNKNOWN, and commercial use is not refused."""
    lic = rec.get('licence') or {}
    name = (lic.get('name') or '').strip()
    return bool(name) and name.upper() != UNKNOWN and lic.get('commercial_ok') is not False


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


# ----------------------------------------------------------------------------------------------- the ledger
class Ledger:
    """Append-only JSONL ledger. `Ledger(project)` reads <project>/media.jsonl (or the path film.json names)."""

    def __init__(self, project, path=None):
        self.project = os.path.abspath(project)
        self.path = os.path.join(self.project, path or LEDGER_FILE)
        self.index_path = os.path.join(os.path.dirname(self.path), INDEX_FILE)

    # ---- reading
    def exists(self):
        return os.path.exists(self.path)

    def records(self):
        """Every record in file order; malformed lines are skipped."""
        if not self.exists():
            return []
        out = []
        with open(self.path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and rec.get('path'):
                        out.append(rec)
                except ValueError:
                    continue
        return out

    def current(self):
        """{path: record} with only the last record per path, in first-seen order."""
        cur = {}
        for r in self.records():
            cur[r['path']] = r
        return cur

    def get(self, path):
        return self.current().get(path if '/' in path or not os.path.isabs(path) else posix_rel(self.project, path))

    def unknown(self):
        """Current records of licensable kinds without a cleared licence."""
        return [r for r in self.current().values() if r.get('kind') in LICENSABLE and not licence_ok(r)]

    def next_id(self, kind, records=None):
        n = 0
        for r in (records if records is not None else self.records()):
            m = re.match(r'^%s_(\d+)$' % re.escape(kind), str(r.get('id', '')))
            if m:
                n = max(n, int(m.group(1)))
        return '%s_%03d' % (kind, n + 1)

    # ---- writing
    @contextmanager
    def _lock(self):
        lock, t0 = self.path + '.lock', time.time()
        while True:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)); break
            except FileExistsError:
                try:
                    if time.time() - os.stat(lock).st_mtime > LOCK_STALE_S:
                        os.remove(lock); continue             # steal a stale lock from a dead holder
                except FileNotFoundError:
                    continue
                if time.time() - t0 > LOCK_TIMEOUT_S:
                    raise RuntimeError('timed out acquiring ' + lock)
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                os.remove(lock)
            except OSError:
                pass

    def append(self, rec):
        """Append one record (id/date filled in if missing) under the lock, then regenerate the index."""
        with self._lock():
            recs = self.records()
            rec = dict(rec)
            rec.setdefault('id', self.next_id(rec['kind'], recs))
            rec.setdefault('date', now_iso())
            rec.setdefault('used_in', [])
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            self.write_index(recs + [rec])
        return rec

    def describe(self, path, kind=None):
        """sha256 + probe facts for a file or a footage directory. Returns (sha, bytes, probe, kind)."""
        ap = os.path.join(self.project, path)
        rel = posix_rel(self.project, ap)
        if os.path.isdir(ap):
            sha, nbytes, n = sha256_dir(ap)
            probe, k = {'files': n}, kind or 'footage'
            meta = os.path.join(ap, 'meta.json')
            if os.path.exists(meta):
                try:
                    m = json.load(open(meta, encoding='utf-8'))
                    probe.update({x: m[x] for x in ('kind', 'frames', 'fps', 'w', 'h', 'dur') if x in m})
                    if 'dur' in m:
                        probe['duration'] = round(float(m['dur']), 1)
                except ValueError:
                    pass
            return sha, nbytes, probe, k
        return sha256_file(ap), os.path.getsize(ap), ffprobe_facts(ap), kind or infer_kind(rel)

    def add(self, path, kind=None, licence=None, source=None, description=None, added_by=None, used_in=None, force=False):
        """Register (or re-register) one asset. Returns the record, or the existing one when nothing changed and not force."""
        ap = os.path.join(self.project, path)
        if not os.path.exists(ap):
            raise FileNotFoundError(ap)
        if os.path.isfile(ap) and os.path.getsize(ap) == 0:
            raise ValueError('refusing a 0-byte asset: ' + path)
        rel = posix_rel(self.project, ap)
        sha, nbytes, probe, k = self.describe(rel, kind)
        if k not in KINDS:
            raise ValueError('kind %r is not one of %s' % (k, '/'.join(KINDS)))
        prev = self.current().get(rel)
        lic = dict(default_licence(k)); lic.update(licence or {})
        src = {'kind': 'existing', 'url': None, 'recording': None, 'window': None, 'provider': None}; src.update(source or {})
        rec = {'kind': k, 'path': rel, 'sha256': sha, 'bytes': nbytes, 'probe': probe, 'source': src, 'licence': lic,
               'description': description or (prev or {}).get('description') or os.path.basename(rel.rstrip('/')),
               'added_by': added_by or (prev or {}).get('added_by') or 'ledger', 'used_in': list(used_in or (prev or {}).get('used_in') or [])}
        if prev and not force and prev.get('sha256') == sha and prev.get('licence') == lic and prev.get('kind') == k \
                and prev.get('source') == src and prev.get('used_in') == rec['used_in']:
            return prev
        if prev:
            rec['id'] = prev['id']                          # the same asset keeps its id across re-registrations
        return self.append(rec)

    def mark_used(self, path, film):
        rec = self.current().get(path)
        if not rec:
            raise KeyError(path)
        film = film.replace('\\', '/')
        if film in rec.get('used_in', []):
            return rec
        new = dict(rec); new['used_in'] = rec.get('used_in', []) + [film]; new.pop('date', None)
        return self.append(new)

    # ---- adopt
    def _clip_windows(self):
        """clips.json → {clip name: (source file, "a-b s" window text)} so extracted footage records carry their origin."""
        out, cj = {}, os.path.join(self.project, 'clips.json')
        if not os.path.exists(cj):
            return out
        try:
            clips = json.load(open(cj, encoding='utf-8'))
        except ValueError:
            return out
        for c in clips if isinstance(clips, list) else []:
            win = None
            if 't' in c: win = '%.2f s' % float(c['t'])
            elif 'win' in c: win = '%.2f-%.2f s (median n=%s)' % (c['win'][0], c['win'][1], c.get('n', 1))
            elif 't0' in c and 't1' in c: win = '%.2f-%.2f s' % (c['t0'], c['t1'])
            elif 'layers' in c:
                ws = ['%.2f-%.2f' % tuple(l['win']) if 'win' in l else '%.2f' % l.get('t', 0) for l in c['layers']]
                win = 'layers ' + ', '.join(ws) + ' s'
            out[c.get('name')] = (c.get('file', 'recording.mp4').replace('\\', '/'), win)
        return out

    def _voice_names(self):
        """vo_script.py VOICES → {phase: voice name}; empty when the script cannot be imported."""
        try:
            sys.path.insert(0, self.project)
            import importlib
            vs = importlib.import_module('vo_script')
            voices = getattr(vs, 'VOICES', {})
            out = {}
            for scene in getattr(vs, 'SCENES', {}).values():
                for p in scene.get('phases', []):
                    v = voices.get(p.get('voice'))
                    out[p['name']] = v[0] if isinstance(v, (list, tuple)) else str(v)
            return out
        except Exception:
            return {}

    def adopt(self, by='adopt', verbose=True):
        """Walk the project for media, register what is unregistered or changed, regenerate the index. Returns new records."""
        cur, new, windows, voices = self.current(), [], self._clip_windows(), self._voice_names()
        cands = []                                              # (rel, kind, source, description)
        # the product recording(s)
        srcs = {w[0] for w in windows.values()} | {'recording.mp4'}
        for s in sorted(srcs):
            if os.path.isfile(os.path.join(self.project, s)):
                cands.append((s, 'footage', {'kind': 'recording'}, 'product screen recording'))
        # the assembled narration track(s)
        for f in sorted(os.listdir(self.project)):
            if re.match(r'^vo_[^/]+\.mp3$', f):
                cands.append((f, 'voice', {'kind': 'generated', 'provider': 'edge-tts'}, 'assembled narration track'))
        for d in SCAN_DIRS:
            root = os.path.join(self.project, d)
            if not os.path.isdir(root):
                continue
            if d == 'broll':
                for e in sorted(os.listdir(root)):
                    p = os.path.join(root, e)
                    if os.path.isdir(p):
                        srcf, win = windows.get(e, ('recording.mp4', None))
                        cands.append(('broll/%s/' % e, 'footage', {'kind': 'extracted', 'recording': srcf, 'window': win,
                                                                      'provider': 'extract_clips.py'}, 'extracted real pixels: ' + e))
                    elif infer_kind('broll/' + e):
                        cands.append(('broll/' + e, 'footage', {'kind': 'extracted'}, e))
                continue
            for r, dirs, files in os.walk(root):
                dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
                for f in sorted(files):
                    rel = posix_rel(self.project, os.path.join(r, f))
                    k = infer_kind(rel)
                    if not k:
                        continue
                    if os.path.getsize(os.path.join(r, f)) == 0:
                        if verbose: print('  skip 0-byte asset %s' % rel)
                        continue
                    src = {'kind': 'existing'}
                    desc = os.path.splitext(f)[0]
                    if k == 'voice':
                        m = re.match(r'^(.+?)_(.+)\.mp3$', f)
                        src = {'kind': 'generated', 'provider': 'edge-tts', 'voice': voices.get(m.group(2)) if m else None}
                        desc = 'narration phase ' + (m.group(2) if m else desc)
                    cands.append((rel, k, src, desc))
        for rel, k, src, desc in cands:
            try:
                sha = self.describe(rel, k)[0]
            except Exception as e:
                if verbose: print('  skip %s (%s)' % (rel, e))
                continue
            prev = cur.get(rel)
            if prev and prev.get('sha256') == sha:
                continue                                        # idempotent: known and unchanged
            s = {'kind': 'existing', 'url': None, 'recording': None, 'window': None, 'provider': None}; s.update(src)
            rec = self.add(rel, kind=k, source=s, description=desc if not prev else None, added_by=by,
                           licence=(prev or {}).get('licence') if prev else None, force=True)
            new.append(rec)
            if verbose:
                flag = '' if licence_ok(rec) else '   <- licence %s: fill it in with `ledger.py add`' % UNKNOWN
                print('  %-12s %-9s %s%s' % (rec['id'], rec['kind'], rel, flag))
        self.write_index()
        return new

    # ---- the index
    def write_index(self, records=None):
        recs = records if records is not None else self.records()
        cur = {}
        for r in recs:
            cur[r['path']] = r
        rows = list(cur.values())
        unknown = [r for r in rows if r.get('kind') in LICENSABLE and not licence_ok(r)]
        lines = ['# media ledger · %d asset%s · %d licence %s' % (len(rows), '' if len(rows) == 1 else 's', len(unknown), UNKNOWN), '',
                 'Generated by tools/ledger.py from %s — do not edit; re-run `ledger.py index`.' % os.path.basename(self.path), '',
                 '| id | kind | dur | dims | licence | commercial | path | source | used in | description |',
                 '|---|---|---|---|---|---|---|---|---|---|']
        for r in rows:
            p, lic, src = r.get('probe') or {}, r.get('licence') or {}, r.get('source') or {}
            dur = ('%.1f s' % p['duration']) if p.get('duration') is not None else ('%d frames' % p['frames'] if p.get('frames') else '—')
            dims = '%sx%s' % (p.get('width') or p.get('w'), p.get('height') or p.get('h')) if (p.get('width') or p.get('w')) else '—'
            com = {True: 'yes', False: 'NO', None: '?'}[lic.get('commercial_ok') if lic.get('commercial_ok') in (True, False) else None]
            s = src.get('kind') or '—'
            if src.get('window'): s += ' ' + src['window']
            if src.get('url'): s += ' ' + src['url']
            cell = lambda x: str(x if x is not None else '').replace('|', '\\|')
            lines.append('| %s |' % ' | '.join(cell(x) for x in (r.get('id'), r.get('kind'), dur, dims, lic.get('name') or UNKNOWN, com,
                                                                   r.get('path'), s, ', '.join(r.get('used_in') or []) or '—', r.get('description'))))
        os.makedirs(os.path.dirname(self.index_path) or '.', exist_ok=True)
        open(self.index_path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
        return self.index_path

    # ---- verification
    def check_path(self, rel):
        """('ok' | 'stale' | 'missing' | 'absent', record) for a project-relative path (absent = file not on disk)."""
        rec = self.current().get(rel)
        ap = os.path.join(self.project, rel)
        if not os.path.exists(ap):
            return 'absent', rec
        if not rec:
            return 'missing', None
        return ('ok' if self.describe(rel, rec.get('kind'))[0] == rec.get('sha256') else 'stale'), rec


# ----------------------------------------------------------------------------------------------- CLI
def find_project(start=None):
    """Nearest directory (upwards from start / cwd / this file) holding film.json; falls back to cwd."""
    for base in (start, os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = os.path.abspath(base or os.getcwd())
        for _ in range(6):
            if os.path.exists(os.path.join(d, 'film.json')):
                return d
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    return os.path.abspath(start or os.getcwd())


def ledger_for(project, path=None):
    """The ledger film.json names ("ledger": "media.jsonl"), or the default beside film.json."""
    if path is None:
        try:
            path = json.load(open(os.path.join(project, 'film.json'), encoding='utf-8')).get('ledger')
        except (OSError, ValueError):
            path = None
    return Ledger(project, path)


def _yesno(v):
    return None if v is None else str(v).lower() in ('1', 'yes', 'y', 'true')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', help='film project dir (default: nearest film.json)')
    ap.add_argument('--ledger', help='ledger path relative to the project (default: film.json "ledger" or media.jsonl)')
    ap.add_argument('--selftest', action='store_true')
    sub = ap.add_subparsers(dest='cmd')
    a = sub.add_parser('adopt'); a.add_argument('--by', default='adopt'); a.add_argument('--json', action='store_true')
    b = sub.add_parser('add'); b.add_argument('path'); b.add_argument('--kind', choices=KINDS); b.add_argument('--licence')
    b.add_argument('--licence-url', default=''); b.add_argument('--attribution', default=''); b.add_argument('--commercial-ok')
    b.add_argument('--source', default=None); b.add_argument('--url'); b.add_argument('--description'); b.add_argument('--by')
    b.add_argument('--used-in', action='append')
    c = sub.add_parser('list'); c.add_argument('--kind'); c.add_argument('--unknown', action='store_true'); c.add_argument('--json', action='store_true')
    sub.add_parser('index')
    u = sub.add_parser('used'); u.add_argument('path'); u.add_argument('film')
    sub.add_parser('check')
    ns = ap.parse_args(argv)
    if ns.selftest:
        return selftest()
    if not ns.cmd:
        ap.print_help(); return 2
    L = ledger_for(find_project(ns.project), ns.ledger)
    if ns.cmd == 'adopt':
        new = L.adopt(by=ns.by, verbose=not ns.json)
        if ns.json:
            print(json.dumps({'ledger': posix_rel(L.project, L.path), 'added': new, 'unknown': [r['path'] for r in L.unknown()]}, indent=1))
        else:
            print('%d record%s added -> %s ; %d licence %s' % (len(new), '' if len(new) == 1 else 's', posix_rel(L.project, L.path),
                                                                len(L.unknown()), UNKNOWN))
        return 0
    if ns.cmd == 'add':
        lic = None
        if ns.licence is not None:
            lic = {'name': ns.licence, 'url': ns.licence_url, 'attribution': ns.attribution,
                   'commercial_ok': _yesno(ns.commercial_ok) if ns.commercial_ok is not None else True}
        src = {}
        if ns.source: src['kind'] = ns.source
        if ns.url: src['url'] = ns.url
        rec = L.add(ns.path, kind=ns.kind, licence=lic, source=src or None, description=ns.description, added_by=ns.by,
                    used_in=ns.used_in, force=bool(lic or ns.description or ns.used_in))
        print(json.dumps(rec, ensure_ascii=False, indent=1)); return 0
    if ns.cmd == 'list':
        rows = [r for r in L.current().values() if (not ns.kind or r['kind'] == ns.kind) and (not ns.unknown or not licence_ok(r))]
        if ns.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                print('%-14s %-11s %-44s %s%s' % (r['id'], r['kind'], r['path'], (r.get('licence') or {}).get('name') or UNKNOWN,
                                                  '' if licence_ok(r) or r['kind'] not in LICENSABLE else '  <- needs a licence'))
            print('%d record%s' % (len(rows), '' if len(rows) == 1 else 's'))
        return 0
    if ns.cmd == 'index':
        print('wrote ' + L.write_index()); return 0
    if ns.cmd == 'used':
        print(json.dumps(L.mark_used(ns.path.replace('\\', '/'), ns.film), indent=1)); return 0
    if ns.cmd == 'check':
        bad = []
        for rel, r in L.current().items():
            st = L.check_path(rel)[0]
            if st in ('stale', 'absent'):
                bad.append('%s %s' % (st, rel))
            if r['kind'] in LICENSABLE and not licence_ok(r):
                bad.append('licence %s %s' % (UNKNOWN, rel))
        print('\n'.join(bad) if bad else 'ledger clean: %d assets, licences present, sha256 current' % len(L.current()))
        return 1 if bad else 0
    return 2


# ----------------------------------------------------------------------------------------------- selftest
def selftest():
    """Synthetic project in a temp dir: adopt, idempotence, UNKNOWN flagging, add licence, stale detection, lock, index."""
    import tempfile, wave, struct
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, 'music')); os.makedirs(os.path.join(td, 'vo')); os.makedirs(os.path.join(td, 'broll', 'nb'))
        json.dump({'name': 'film', 'bed': 'music/bed.wav'}, open(os.path.join(td, 'film.json'), 'w'))
        json.dump([{'name': 'nb', 'kind': 'page', 'layers': [{'win': [0.1, 3.9], 'n': 5, 'off': 0}]}], open(os.path.join(td, 'clips.json'), 'w'))
        with wave.open(os.path.join(td, 'music', 'bed.wav'), 'wb') as w:                         # 1.0 s of silence
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000); w.writeframes(struct.pack('<%dh' % 96000, *([0] * 96000)))
        with wave.open(os.path.join(td, 'vo', 'film_hook.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b'\0' * 48000)
        open(os.path.join(td, 'music', 'empty.mp3'), 'wb').close()                             # 0-byte → skipped loudly
        from PIL import Image
        Image.new('RGB', (64, 32), '#fff').save(os.path.join(td, 'broll', 'nb', 'page.jpg'))
        json.dump({'kind': 'page', 'frames': 1, 'w': 64, 'h': 32}, open(os.path.join(td, 'broll', 'nb', 'meta.json'), 'w'))
        L = Ledger(td)
        new = L.adopt(by='selftest')
        assert {r['path'] for r in new} == {'music/bed.wav', 'vo/film_hook.wav', 'broll/nb/'}, [r['path'] for r in new]
        assert L.get('music/bed.wav')['probe']['duration'] == 1.0 and L.get('music/bed.wav')['probe']['sample_rate'] == 48000
        assert L.get('vo/film_hook.wav')['kind'] == 'voice' and licence_ok(L.get('vo/film_hook.wav'))
        assert L.get('broll/nb/')['source']['window'] == 'layers 0.10-3.90 s' and L.get('broll/nb/')['probe']['files'] == 2
        assert [r['path'] for r in L.unknown()] == ['music/bed.wav'], 'bed must start UNKNOWN'
        assert L.adopt(verbose=False) == [], 'adopt must be idempotent'
        rec = L.add('music/bed.wav', licence={'name': 'Acme Library Licence', 'url': 'https://example.com/licence', 'commercial_ok': True},
                    source={'kind': 'licensed', 'url': 'https://example.com/bed'})
        assert rec['id'] == 'music_001' and L.unknown() == [] and len(L.records()) == 4, 'same id, appended not rewritten'
        with open(os.path.join(td, 'music', 'bed.wav'), 'ab') as f: f.write(b'\0' * 4)
        assert L.check_path('music/bed.wav')[0] == 'stale'
        assert L.check_path('broll/nb/')[0] == 'ok' and L.check_path('nope.mp3')[0] == 'absent'
        with open(L.path, 'a', encoding='utf-8') as f: f.write('{not json\n')
        assert len(L.records()) == 4, 'malformed line skipped'
        L.mark_used('music/bed.wav', 'out/Acme.mp4'); assert L.get('music/bed.wav')['used_in'] == ['out/Acme.mp4']
        idx = open(L.index_path, encoding='utf-8').read()
        assert '# media ledger · 3 assets · 0 licence UNKNOWN' in idx and '| music_001 | music | 1.0 s |' in idx, idx[:200]
        # lock: a fresh lock file blocks; a stale one (mtime 16 s ago) is stolen
        lock = L.path + '.lock'; open(lock, 'w').close(); os.utime(lock, (time.time() - 16, time.time() - 16))
        L.append({'kind': 'sfx', 'path': 'sfx/click.wav', 'sha256': '0' * 64, 'bytes': 1, 'probe': {}, 'source': {}, 'licence': default_licence('sfx')})
        assert not os.path.exists(lock) and L.next_id('sfx') == 'sfx_002'
        assert infer_kind('out/seg_film.mp4') is None and infer_kind('broll/clips.js') is None and infer_kind('fonts/Inter.woff2') == 'font'
        assert infer_kind('vo_film.mp3') == 'voice' and infer_kind('assets/logo.png') == 'image' and infer_kind('sfx/key.wav') == 'sfx'
    print('ledger selftest OK: adopt / idempotent / UNKNOWN flag / add keeps id / stale sha / malformed skip / used_in / index / lock steal / kinds')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
