# -*- coding: utf-8 -*-
"""studio.py — a local preview studio for clock-driven film scenes: scrub, step, play, tap a still, hot-reload.

    python tools/studio.py [--project DIR] [--scene scenes/film.html] [--port 8765] [--host 127.0.0.1]
                           [--no-browser] [--node-path DIR] [--verbose]
    python tools/studio.py --manifest [--project DIR]            JSON of everything the UI draws (no server)
    python tools/studio.py --tap 12.4 [--project DIR]            one 1920x1080 still into out/taps/, JSON result
    python tools/studio.py --qa [--project DIR]                  the quick lint (gates/lint_scene.py --json)
    python tools/studio.py --selftest [--with-tap]               synthetic fixture, < 60 s

  exit 0  ok        exit 1  findings (tap failed, lint errors, selftest FAIL)        exit 2  usage

WHY A STUDIO
  A v4/v5 film is one HTML scene whose only input is the clock t (window.__seek / window.__step, see
  render_frames.js). A full render costs minutes; a 32 s film at 30 fps is 960 deterministic frames. But
  because every frame is a pure function of t, the browser can show ANY frame instantly without rendering the
  ones before it. This tool exploits that: it serves the project over plain HTTP, loads the scene in an iframe
  at the authoring size (1280x720, CSS-scaled to fit the window), and drives the iframe's own __seek(t) /
  __step(t) from a timeline. The iteration loop becomes: edit shots.js -> the iframe reloads at the same t
  (< 1 s) -> look -> edit. Nothing here is part of the render path; the film's determinism contract is untouched.

WHAT THE SERVER DOES (stdlib only: http.server + threading; binds 127.0.0.1, port 8765 by default)
  /                       the studio page (studio/ui.html, studio.js, studio.css next to this tools/ folder)
  /p/<path>               any file of the project directory (the scene, scenes/lib/*.js, broll/, out/taps/)
  /api/project            the manifest: clock (phases + word times), seam windows, storyboard beats, camera
                          trace, caption lane geometry, safe zones, watched files — everything the UI draws
  /changes?since=N        LONG POLL for hot reload. A watcher thread stats scenes/**, lib/**, timing*.js,
                          seams.json, STORYBOARD.md, clips.js every 500 ms (os.scandir, mtime_ns). Any change
                          bumps a version counter and wakes waiting requests; a client holds a request open
                          for up to 25 s, then re-asks. No WebSocket, no extra dependency.
  /tap?t=12.4             a 1920x1080 still of frame round(t*fps) through the REAL renderer (below)
  /qa                     runs gates/lint_scene.py <scene> --project . --json and returns its report

HOW A TAP IS RENDERED (and why it is the renderer, not a screenshot of the preview)
  The preview iframe runs on the machine's GPU with the browser's own scaling; a shipped frame comes from
  render_frames.js: headless Chrome, software GL, DPR 1.5, fonts settled, lanczos scale to 1920x1080, the TV
  range colour pipeline. A tap must show what ships, so it spawns the renderer with a ONE-FRAME duration
  (seconds = 1/fps -> N = round(1/fps * fps) = 1 frame). The renderer always starts at film clock 0, so the
  tap writes a tiny shim scene, out/taps/_shim.html, whose window.__seek(t) forwards to the real scene's
  __seek(t + T0) inside an iframe (the renderer's --allow-file-access-from-files flag makes the file:// frames
  one origin). The one-frame .mp4 is then unwrapped with ffmpeg into out/taps/tap_f<frame>.png. Measured on
  the synthetic Acme project (32 s film, 1280x720 @ DPR 1.5): 4.2 s per tap on an idle machine, 23-60 s while
  another render shared the CPU (Chrome launch + the shot's image decode dominate; the one frame itself is
  ~80 ms). Pixels are identical tap-to-tap for the same t (the renderer's own determinism contract; verified
  with a per-pixel diff of two taps at t = 14.0).

CUE RESOLUTION
  seams.json writes cuts as cue expressions ("P.nb", "wt(ask,'typed') + 0.4"). When out/timeline.json exists
  (export_timeline.js already resolved them) its rows are used verbatim. Otherwise the expression is resolved
  here: P.<phase> / P.<phase>_end / wt(phase, word[, n]) are substituted from the timing file and the remaining
  arithmetic is evaluated with Python's ast restricted to numbers and + - * / ( ) — never eval(). Seam
  windows default to the technique's measured durations from lib/seams.js: cut-the-curve exit 0.34 s /
  entry 0.42 s, zoom-through 0.20 / 0.50, inverse zoom-through 0.21 / 0.49; opts.exitDur / entryDur win.

GUIDES
  Title safe = 10 % inset (128x72 px on the 1280x720 stage), action safe = 5 % inset (64x36 px): the broadcast
  convention the overlay gate also assumes. Caption lane = the bottom 17 % of the stage (y >= 598), the keep-out
  STORYBOARD.md declares; the lane box is read from scenes/captions.json "stage" when present. The mandatory
  credit box is not drawn here (credit.py stamps it on the final video).

DETERMINISM
  The manifest has no wall-clock fields and iterates files in sorted order, so two calls on an unchanged
  project are byte-identical (the selftest proves it). Only the preview loop in studio.js uses
  requestAnimationFrame — that is a viewer, not a renderer; the scene files it loads stay pure functions of t.
"""
import argparse
import ast
import glob
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)                      # scripts/film (render_frames.js, gates/, studio/)
STUDIO_DIR = os.path.join(FILM_DIR, 'studio')

DEFAULT_PORT = 8765
DEFAULT_HOST = '127.0.0.1'
POLL_S = 0.5
LONGPOLL_MAX_S = 25.0
STAGE = (1280, 720)
TITLE_SAFE = 0.10
ACTION_SAFE = 0.05
CAPTION_KEEPOUT = 0.17                                # bottom 17 % of the stage (y >= 598 on 720)
SEAM_DEFAULTS = {                                     # lib/seams.js measured defaults (exitDur, entryDur)
    'cut-the-curve': (0.34, 0.42), 'combined': (0.34, 0.42), 'rack-focus': (0.34, 0.42), 'waterfall': (0.34, 0.42),
    'zoom-through': (0.20, 0.50), 'inverse zoom-through': (0.21, 0.49),
}
WATCH_SKIP = {'out', 'node_modules', '.git', '__pycache__', 'vo', 'broll', 'music', 'sfx'}
BEAT_HEAD = re.compile(r'^##\s*Beat\s+(\d+)\s*[—–-]+\s*(.*?)\s*\((\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)', re.I)


# ---------------------------------------------------------------- project reading
def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def project_config(project):
    cfg = read_json(os.path.join(project, 'film.json'), {}) or {}
    name = cfg.get('name', 'film')
    scene = cfg.get('scene', 'scenes/film.html')
    fps = int(cfg.get('fps', 30))
    return {'name': name, 'scene': scene.replace('\\', '/'), 'fps': fps, 'output': cfg.get('output')}


def load_timing(project, name):
    """window.PHASES / window.WORDS from scenes/timing_<name>.js, or vo/<name>_phases.json + _words.json."""
    js = os.path.join(project, 'scenes', 'timing_%s.js' % name)
    phases, words = None, None
    try:
        txt = open(js, encoding='utf-8').read()
        m1 = re.search(r'window\.PHASES\s*=\s*(\{.*?\});\s*$', txt, re.M | re.S)
        m2 = re.search(r'window\.WORDS\s*=\s*(\{.*?\});\s*$', txt, re.M | re.S)
        if m1:
            phases = json.loads(m1.group(1))
        if m2:
            words = json.loads(m2.group(1))
    except (OSError, ValueError):
        pass
    if phases is None:
        phases = read_json(os.path.join(project, 'vo', '%s_phases.json' % name))
    if words is None:
        words = read_json(os.path.join(project, 'vo', '%s_words.json' % name), {})
    if not phases:
        return None
    return {'total': float(phases.get('total', 0.0)), 'phases': phases.get('phases', []), 'words': words or {}}


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


class Clock(object):
    """P[phase], P[phase_end], wt(phase, word, n) — the same arithmetic as lib/timeline.js."""

    def __init__(self, timing):
        self.P = {}
        for p in timing['phases']:
            self.P[p['name']] = float(p['start'])
            self.P[p['name'] + '_end'] = float(p['start']) + float(p['dur'])
        self.W = timing['words']
        self.total = timing['total']

    def wt(self, phase, word, n=1):
        want, k = _norm(word), 0
        for x in self.W.get(phase, []):
            if _norm(x['w']) == want:
                k += 1
                if k == n:
                    return self.P.get(phase, 0.0) + float(x['t'])
        return self.P.get(phase, 0.0)

    def phase_at(self, t):
        cur = None
        for p in self.timing_phases():
            if t >= p['start']:
                cur = p['name']
        return cur

    def timing_phases(self):
        return sorted([{'name': k, 'start': v} for k, v in self.P.items() if not k.endswith('_end')], key=lambda p: p['start'])


_WT = re.compile(r"wt\(\s*['\"]?([A-Za-z0-9_]+)['\"]?\s*,\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(\d+)\s*)?\)")
_PX = re.compile(r'\bP\.([A-Za-z0-9_]+)')


def resolve_cue(expr, clock):
    """'P.nb + 0.4' / 'wt(ask, \"typed\")' -> seconds. Numbers pass through. Returns None when unresolvable."""
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr).strip()
    if clock is None:
        try:
            return float(s)
        except ValueError:
            return None
    s = _WT.sub(lambda m: repr(clock.wt(m.group(1), m.group(2), int(m.group(3) or 1))), s)
    s = _PX.sub(lambda m: repr(clock.P.get(m.group(1), 0.0)), s)
    try:
        tree = ast.parse(s, mode='eval')
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = ev(n.operand)
            return v if isinstance(n.op, ast.UAdd) else -v
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            return a / b if b else 0.0
        raise ValueError('cue syntax not allowed: %s' % s)
    try:
        return round(ev(tree), 4)
    except (ValueError, ZeroDivisionError):
        return None


def load_seams(project, clock):
    """Seam windows [{id, cut, t0, t1, technique, act}] — out/timeline.json first, else seams.json resolved here."""
    tl = read_json(os.path.join(project, 'out', 'timeline.json'))
    if tl and isinstance(tl.get('seams'), list):
        rows = []
        for s in tl['seams']:
            if s.get('cut') is None:
                continue
            rows.append({'id': s.get('id', ''), 'cut': float(s['cut']), 't0': float(s.get('t0', s['cut'])), 't1': float(s.get('t1', s['cut'])),
                         'technique': s.get('technique', ''), 'act': s.get('act', ''), 'source': 'out/timeline.json'})
        return sorted(rows, key=lambda r: r['cut'])
    sj = read_json(os.path.join(project, 'seams.json'))
    rows = []
    if sj and isinstance(sj.get('seams'), list):
        for s in sj['seams']:
            cut = resolve_cue(s.get('cut'), clock)
            if cut is None:
                continue
            tech = s.get('technique', 'cut-the-curve')
            ex, en = SEAM_DEFAULTS.get(tech, SEAM_DEFAULTS['cut-the-curve'])
            o = s.get('opts') or {}
            ex, en = float(o.get('exitDur', ex)), float(o.get('entryDur', en))
            rows.append({'id': s.get('id', ''), 'cut': cut, 't0': round(cut - ex, 4), 't1': round(cut + en, 4),
                         'technique': tech, 'act': s.get('act', ''), 'source': 'seams.json'})
    return sorted(rows, key=lambda r: r['cut'])


def load_beats(project):
    """STORYBOARD.md '## Beat NN — Name (t0–t1, ~dur s)' headings -> [{n, title, t0, t1}]."""
    path = os.path.join(project, 'STORYBOARD.md')
    beats = []
    try:
        for raw in open(path, encoding='utf-8'):
            m = BEAT_HEAD.match(raw.strip())
            if m:
                beats.append({'n': int(m.group(1)), 'title': m.group(2).strip(' -–—'), 't0': float(m.group(3)), 't1': float(m.group(4))})
    except OSError:
        pass
    return beats


def load_camera(project, max_per_s=4):
    """out/camera_curves.json (node scenes/lib/camera.js --curves) -> a thinned scale trace per shot."""
    cc = read_json(os.path.join(project, 'out', 'camera_curves.json'))
    if not cc or not isinstance(cc.get('shots'), list):
        return None
    fps = int(cc.get('fps', 30))
    stride = max(1, fps // max_per_s)
    shots = []
    for sh in cc['shots']:
        samples = sh.get('samples') or []
        pts = [[round(s['t'], 3), round(s['s'], 4)] for i, s in enumerate(samples) if i % stride == 0 or i == len(samples) - 1]
        shots.append({'shot': sh.get('shot', ''), 'clip': sh.get('clip', ''), 't0': sh.get('t0'), 't1': sh.get('t1'),
                      'peak_speed_px_per_frame': sh.get('peak'), 'verbs': sh.get('verbs', []), 'trace': pts, 'windows': sh.get('windows', {})})
    return {'fps': fps, 'cuts': cc.get('cuts', []), 'shots': shots}


def caption_lane(project):
    cj = read_json(os.path.join(project, 'scenes', 'captions.json')) or {}
    stage = cj.get('stage') or list(STAGE)
    w, h = int(stage[0]), int(stage[1])
    y0 = round(h * (1 - CAPTION_KEEPOUT))
    return {'stage': [w, h], 'box': [0, y0, w, h - y0], 'style': cj.get('style'), 'mode': cj.get('mode'), 'burn': cj.get('burn')}


def watched_files(project):
    """Sorted {relpath: mtime_ns} of everything an edit-look loop touches (cheap: a few hundred stats)."""
    out = {}

    def walk(rel):
        base = os.path.join(project, rel)
        if not os.path.isdir(base):
            return
        stack = [base]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.name in WATCH_SKIP or e.name.startswith('.'):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            out[os.path.relpath(e.path, project).replace('\\', '/')] = e.stat().st_mtime_ns
            except OSError:
                pass
    walk('scenes')
    walk('lib')
    for pat in ('timing*.js', 'seams.json', 'STORYBOARD.md', 'film.json', 'clips.json', 'broll/clips.js'):
        for p in glob.glob(os.path.join(project, pat)):
            try:
                out[os.path.relpath(p, project).replace('\\', '/')] = os.stat(p).st_mtime_ns
            except OSError:
                pass
    return dict(sorted(out.items()))


def manifest(project, scene_override=None):
    cfg = project_config(project)
    if scene_override:
        cfg['scene'] = scene_override.replace('\\', '/')
    timing = load_timing(project, cfg['name'])
    clock = Clock(timing) if timing else None
    files = watched_files(project)
    m = {
        'name': cfg['name'], 'scene': cfg['scene'], 'fps': cfg['fps'], 'stage': list(STAGE),
        'total': timing['total'] if timing else None,
        'phases': timing['phases'] if timing else [], 'words': timing['words'] if timing else {},
        'seams': load_seams(project, clock), 'beats': load_beats(project), 'camera': load_camera(project),
        'captions': caption_lane(project),
        'guides': {'title_safe': [round(STAGE[0] * TITLE_SAFE), round(STAGE[1] * TITLE_SAFE), round(STAGE[0] * (1 - 2 * TITLE_SAFE)), round(STAGE[1] * (1 - 2 * TITLE_SAFE))],
                   'action_safe': [round(STAGE[0] * ACTION_SAFE), round(STAGE[1] * ACTION_SAFE), round(STAGE[0] * (1 - 2 * ACTION_SAFE)), round(STAGE[1] * (1 - 2 * ACTION_SAFE))]},
        'scene_exists': os.path.exists(os.path.join(project, cfg['scene'])),
        'renderer': find_renderer(project) is not None, 'lint': find_lint(project) is not None,
        'watched': sorted(files.keys()), 'taps': sorted(os.path.basename(p) for p in glob.glob(os.path.join(project, 'out', 'taps', 'tap_f*.png'))),
    }
    return m


def find_renderer(project):
    for p in (os.path.join(project, 'render_frames.js'), os.path.join(FILM_DIR, 'render_frames.js')):
        if os.path.exists(p):
            return p
    return None


def find_lint(project):
    for p in (os.path.join(project, 'gates', 'lint_scene.py'), os.path.join(FILM_DIR, 'gates', 'lint_scene.py')):
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- tap: one frame through the real renderer
SHIM = """<!doctype html><html><head><meta charset="utf-8"><title>tap shim</title>
<style>html,body{margin:0;width:1280px;height:720px;overflow:hidden;background:#000}iframe{border:0;width:1280px;height:720px;display:block}</style>
</head><body><iframe id="f"></iframe>
<script>
/* one-frame tap: render_frames.js calls __seek(0) then screenshots; we forward to the real scene at T0 */
var T0 = %(t0)s, f = document.getElementById('f');
var ready = new Promise(function (r) { f.onload = r; });
f.src = %(src)s;
window.__seek = function (t) {
  return ready.then(function () { var w = f.contentWindow; return w.document.fonts.ready.then(function () { return w; }); })
    .then(function (w) { return new Promise(function (r) { setTimeout(function () { r(w); }, 400); }); })
    .then(function (w) { w.document.body.classList.remove('pre'); return w.__seek(t + T0); });
};
window.__step = function (t) { return f.contentWindow.__step(t + T0); };
</script></body></html>
"""
_tap_lock = threading.Lock()


def tap(project, t, scene=None, node_path=None, fps=None, quality=96):
    """Render frame round(t*fps) at 1920x1080 -> out/taps/tap_f<frame>.png via render_frames.js (1-frame duration)."""
    cfg = project_config(project)
    scene = (scene or cfg['scene']).replace('\\', '/')
    fps = int(fps or cfg['fps'])
    renderer = find_renderer(project)
    if not renderer:
        return {'ok': False, 'error': 'render_frames.js not found (project root or the skill film/ folder)'}
    scene_abs = os.path.join(project, scene)
    if not os.path.exists(scene_abs):
        return {'ok': False, 'error': 'scene not found: %s' % scene}
    frame = int(round(float(t) * fps))
    t_q = frame / float(fps)
    taps = os.path.join(project, 'out', 'taps')
    os.makedirs(taps, exist_ok=True)
    shim = os.path.join(taps, '_shim.html')
    mp4 = os.path.join(taps, 'tap_f%05d.mp4' % frame)
    png = os.path.join(taps, 'tap_f%05d.png' % frame)
    env = dict(os.environ)
    if node_path:
        env['NODE_PATH'] = node_path + os.pathsep + env.get('NODE_PATH', '') if env.get('NODE_PATH') else node_path
    t_start = time.time()
    with _tap_lock:
        with open(shim, 'w', encoding='utf-8') as fh:
            fh.write(SHIM % {'t0': repr(t_q), 'src': json.dumps(Path(scene_abs).resolve().as_uri() + '?render')})
        cmd = ['node', renderer, shim, mp4, repr(1.0 / fps), str(fps), str(quality), '1']
        try:
            r = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, timeout=240)
        except FileNotFoundError:
            return {'ok': False, 'error': 'node not on PATH'}
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'renderer timed out (240 s)'}
        receipt = None
        for line in (r.stdout or '').splitlines()[::-1]:
            if line.startswith('{'):
                try:
                    receipt = json.loads(line)
                    break
                except ValueError:
                    pass
        if r.returncode != 0 or not os.path.exists(mp4):
            return {'ok': False, 'error': 'renderer exit %d' % r.returncode, 'stderr': (r.stderr or '')[-2000:], 'stdout': (r.stdout or '')[-1000:], 'cmd': cmd}
        ff = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', mp4, '-frames:v', '1', png], capture_output=True, text=True)
        if ff.returncode != 0 or not os.path.exists(png):
            return {'ok': False, 'error': 'ffmpeg could not unwrap the tap', 'stderr': (ff.stderr or '')[-1000:]}
        try:
            os.remove(mp4)
        except OSError:
            pass
    rel = 'out/taps/' + os.path.basename(png)
    return {'ok': True, 't': round(t_q, 4), 'frame': frame, 'png': rel, 'size': os.path.getsize(png), 'wall_s': round(time.time() - t_start, 1),
            'renderer': {k: receipt.get(k) for k in ('chrome', 'gl', 'gl_renderer', 'errors')} if receipt else None}


# ---------------------------------------------------------------- quick QA
def quick_qa(project, scene=None, timeout=180):
    cfg = project_config(project)
    scene = (scene or cfg['scene']).replace('\\', '/')
    lint = find_lint(project)
    if not lint:
        return {'ok': False, 'error': 'gates/lint_scene.py not found'}
    cmd = [sys.executable, lint, scene, '--project', project, '--json']
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'lint timed out'}
    rep = None
    out = r.stdout or ''
    i = out.find('{')
    if i >= 0:
        try:
            rep = json.loads(out[i:])
        except ValueError:
            rep = None
    findings = []
    if rep:
        for f in rep.get('findings', rep.get('items', [])) or []:
            findings.append({k: f.get(k) for k in ('code', 'severity', 'file', 'line', 'message', 'hint')})
    counts = {}
    for f in findings:
        counts[f.get('severity') or '?'] = counts.get(f.get('severity') or '?', 0) + 1
    return {'ok': r.returncode == 0, 'exit': r.returncode, 'wall_s': round(time.time() - t0, 1), 'counts': dict(sorted(counts.items())),
            'findings': findings[:200], 'raw': None if rep else out[-2000:] + (r.stderr or '')[-1000:]}


# ---------------------------------------------------------------- watcher + server
class Watcher(threading.Thread):
    def __init__(self, project, poll_s=POLL_S):
        super().__init__(daemon=True)
        self.project, self.poll_s = project, poll_s
        self.cond = threading.Condition()
        self.version = 1
        self.changed = []
        self.snapshot = watched_files(project)
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(self.poll_s):
            self.scan()

    def scan(self):
        now = watched_files(self.project)
        diff = sorted(set(k for k in set(now) | set(self.snapshot) if now.get(k) != self.snapshot.get(k)))
        if diff:
            with self.cond:
                self.snapshot = now
                self.version += 1
                self.changed = diff
                self.cond.notify_all()
        return diff

    def wait(self, since, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.version > since, timeout=timeout)
            return {'version': self.version, 'changed': self.changed if self.version > since else []}


def make_handler(project, scene, watcher, node_path, verbose, guard=None):
    """guard = {'hosts', 'origins', 'token'} — filled by serve() once the port is known. Every request must carry a Host of
    127.0.0.1:<port> / localhost:<port> (a page on another site cannot forge Host, so neither a rebinding nor a cross-site
    page reaches the server); the two routes that start a subprocess (/tap, /qa) also need the per-session token the served
    page embeds (<meta name="studio-token"> → X-Studio-Token) and, when an Origin header is present, an allowed origin.
    POST is not a verb this server has: 405."""
    proj_root = os.path.realpath(project)
    G = guard if guard is not None else {'hosts': set(), 'origins': set(), 'token': secrets.token_hex(16)}

    class H(BaseHTTPRequestHandler):
        server_version = 'fde-studio/1.0'
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *a):
            if verbose:
                sys.stderr.write('[studio] ' + (fmt % a) + '\n')

        def _send(self, code, body, ctype='application/json; charset=utf-8'):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, sort_keys=True).encode('utf-8')
            elif isinstance(body, str):
                body = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _file(self, root, rel):
            rel = urllib.parse.unquote(rel).replace('\\', '/').lstrip('/')
            full = os.path.realpath(os.path.join(root, rel))
            if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
                return self._send(404, {'error': 'not found', 'path': rel})
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            if full.endswith(('.js', '.mjs')):
                ctype = 'application/javascript; charset=utf-8'
            elif full.endswith('.html'):
                ctype = 'text/html; charset=utf-8'
            elif full.endswith('.css'):
                ctype = 'text/css; charset=utf-8'
            elif full.endswith('.json'):
                ctype = 'application/json; charset=utf-8'
            with open(full, 'rb') as fh:
                self._send(200, fh.read(), ctype)

        def do_HEAD(self):
            self.do_GET()

        def _host_ok(self):
            h = (self.headers.get('Host') or '').strip().lower()
            return (not G['hosts']) or h in G['hosts']

        def _token_ok(self):
            if (self.headers.get('X-Studio-Token') or '') != G['token']:
                return False
            o = (self.headers.get('Origin') or '').strip().lower()
            return (not o) or (not G['origins']) or o in G['origins']

        def do_POST(self):
            self._send(405, {'error': 'this server only answers GET'})

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {'error': 'bad Host'})
            u = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            p = u.path
            try:
                if p in ('/', '/index.html', '/studio', '/studio/'):
                    with open(os.path.join(STUDIO_DIR, 'ui.html'), 'rb') as fh:
                        page = fh.read().decode('utf-8')
                    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta name="studio-token" content="%s">' % G['token'], 1)
                    return self._send(200, page, 'text/html; charset=utf-8')
                if p.startswith('/studio/'):
                    return self._file(STUDIO_DIR, p[len('/studio/'):])
                if p.startswith('/p/'):
                    return self._file(proj_root, p[3:])
                if p == '/favicon.ico':
                    return self._send(204, b'', 'image/x-icon')
                if p == '/api/project':
                    return self._send(200, manifest(project, scene))
                if p == '/changes':
                    since = int(q.get('since', '0') or 0)
                    timeout = min(LONGPOLL_MAX_S, float(q.get('timeout', LONGPOLL_MAX_S) or LONGPOLL_MAX_S))
                    return self._send(200, watcher.wait(since, timeout))
                if p in ('/tap', '/qa') and not self._token_ok():
                    return self._send(403, {'error': 'missing or wrong X-Studio-Token (reload the studio page)'})
                if p == '/tap':
                    try:
                        t = float(q.get('t', '0'))
                    except ValueError:
                        return self._send(400, {'ok': False, 'error': 't must be seconds'})
                    return self._send(200, tap(project, t, scene, node_path))
                if p == '/qa':
                    return self._send(200, quick_qa(project, scene))
                return self._send(404, {'error': 'no such route', 'path': p})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:                   # a preview server must not die on one bad request
                try:
                    self._send(500, {'error': repr(e)})
                except Exception:
                    pass
    return H


def serve(project, scene=None, host=DEFAULT_HOST, port=DEFAULT_PORT, node_path=None, open_browser=True, verbose=False, block=True):
    project = os.path.abspath(project)
    watcher = Watcher(project)
    watcher.start()
    guard = {'hosts': set(), 'origins': set(), 'token': secrets.token_hex(16)}
    handler = make_handler(project, scene, watcher, node_path, verbose, guard)
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as e:
        sys.stderr.write('studio: cannot bind %s:%d (%s) — is another studio running? try --port\n' % (host, port, e))
        return None
    httpd.daemon_threads = True
    bound = httpd.server_address[1]
    guard['hosts'] = {'127.0.0.1:%d' % bound, 'localhost:%d' % bound, '[::1]:%d' % bound}
    guard['origins'] = {'http://127.0.0.1:%d' % bound, 'http://localhost:%d' % bound}
    httpd.token = guard['token']
    url = 'http://%s:%d/' % (host, bound)
    if block:
        cfg = project_config(project)
        print('studio  %s  project=%s  scene=%s  fps=%d  (Ctrl-C to stop)' % (url, project, scene or cfg['scene'], cfg['fps']))
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop.set()
            httpd.server_close()
        return None
    th = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True)
    th.start()
    return {'httpd': httpd, 'watcher': watcher, 'url': url, 'thread': th}


# ---------------------------------------------------------------- selftest on a synthetic fixture
FIXTURE_SCENE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1280px;height:720px;overflow:hidden;background:#082A34;font-family:Arial,sans-serif}
body.pre #stage{visibility:hidden}#stage{position:absolute;inset:0}
#camera{position:absolute;inset:0;transform-origin:0 0}
.plate{position:absolute;left:140px;top:120px;width:1000px;height:420px;background:#ECDEC3;border-radius:8px}
#t{position:absolute;left:180px;top:160px;font:48px Georgia,serif;color:#082A34}
#bar{position:absolute;left:180px;top:300px;height:24px;background:#E56B5E}
</style></head><body><div id="stage"><div id="camera"><div class="plate"></div><div id="t"></div><div id="bar"></div></div></div>
<script src="timing_film.js"></script><script>
'use strict';
const RENDER=/[?&]render/.test(location.search);if(RENDER)document.body.classList.add('pre');
const END=window.PHASES.total;
function frame(t){const s=1+0.25*Math.min(1,Math.max(0,(t-2)/2));document.getElementById('camera').style.transform=s>1.0005?'translate('+(640-s*640).toFixed(2)+'px,'+(360-s*360).toFixed(2)+'px) scale('+s.toFixed(4)+')':'none';
document.getElementById('t').textContent='Acme fixture t='+t.toFixed(2);document.getElementById('bar').style.width=(Math.min(1,t/END)*900).toFixed(1)+'px';}
window.__seek=t=>{document.body.classList.remove('pre');frame(t);return Promise.resolve();};window.__step=t=>frame(t);window.__total=END;
if(!RENDER){const q=new URLSearchParams(location.search);if(q.has('t'))window.__seek(parseFloat(q.get('t')));else window.__seek(0);}
</script></body></html>
"""


def make_fixture(root):
    os.makedirs(os.path.join(root, 'scenes'), exist_ok=True)
    with open(os.path.join(root, 'film.json'), 'w', encoding='utf-8') as fh:
        json.dump({'name': 'film', 'scene': 'scenes/film.html', 'fps': 30}, fh)
    with open(os.path.join(root, 'scenes', 'film.html'), 'w', encoding='utf-8') as fh:
        fh.write(FIXTURE_SCENE)
    phases = {'total': 6.0, 'phases': [{'name': 'a', 'start': 0.0, 'dur': 2.8}, {'name': 'b', 'start': 3.0, 'dur': 3.0}]}
    words = {'a': [{'t': 0.1, 'w': 'Every'}, {'t': 0.6, 'w': 'Monday'}, {'t': 1.4, 'w': 'asks'}], 'b': [{'t': 0.2, 'w': 'One'}, {'t': 1.1, 'w': 'answer'}, {'t': 2.0, 'w': 'One'}]}
    with open(os.path.join(root, 'scenes', 'timing_film.js'), 'w', encoding='utf-8') as fh:
        fh.write('window.PHASES=%s;\nwindow.WORDS=%s;\n' % (json.dumps(phases), json.dumps(words)))
    with open(os.path.join(root, 'seams.json'), 'w', encoding='utf-8') as fh:
        json.dump({'seams': [{'id': 'a->b', 'cut': 'P.b', 'technique': 'cut-the-curve'},
                             {'id': 'word', 'cut': "wt(b, 'One', 2) - 0.25", 'technique': 'zoom-through', 'opts': {'entryDur': 0.6}}]}, fh)
    with open(os.path.join(root, 'STORYBOARD.md'), 'w', encoding='utf-8') as fh:
        fh.write('---\ntitle: fixture\n---\n\n## Beat 01 — Hook (0.0–3.0, ~3.0 s)\n- vo: "Every Monday"\n\n## Beat 02 — Answer (3.0–6.0, ~3.0 s)\n- vo: "One answer"\n')


def selftest(with_tap=False, node_path=None):
    import urllib.request
    t_start = time.time()
    root = tempfile.mkdtemp(prefix='studio_selftest_')
    oks = []

    def check(cond, label):
        oks.append(bool(cond))
        print('selftest  %s  %s' % ('ok  ' if cond else 'FAIL', label))

    try:
        make_fixture(root)
        m1 = manifest(root)
        m2 = manifest(root)
        check(json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True), 'manifest is deterministic (two calls identical)')
        check(m1['total'] == 6.0 and len(m1['phases']) == 2, 'clock read from scenes/timing_film.js (total 6.0, 2 phases)')
        seams = {s['id']: s for s in m1['seams']}
        check(abs(seams['a->b']['cut'] - 3.0) < 1e-6 and abs(seams['a->b']['t0'] - 2.66) < 1e-6 and abs(seams['a->b']['t1'] - 3.42) < 1e-6, 'P.b cue -> 3.0, cut-the-curve window 2.66..3.42')
        check(abs(seams['word']['cut'] - 4.75) < 1e-6 and abs(seams['word']['t1'] - 5.35) < 1e-6, "wt(b,'One',2) - 0.25 -> 4.75, opts.entryDur 0.6 honoured")
        check(len(m1['beats']) == 2 and m1['beats'][1]['t0'] == 3.0, 'STORYBOARD.md beats parsed (2 beats)')
        check(m1['captions']['box'] == [0, 598, 1280, 122], 'caption lane = bottom 17 % (y >= 598)')
        check(resolve_cue('__import__("os")', Clock(load_timing(root, 'film'))) is None, 'cue resolver rejects non-arithmetic')
        srv = serve(root, host='127.0.0.1', port=0, node_path=node_path, open_browser=False, block=False)
        check(bool(srv), 'server bound on an ephemeral port')
        url = srv['url']

        def get(path, timeout=10):
            with urllib.request.urlopen(url.rstrip('/') + path, timeout=timeout) as r:
                return r.status, r.read()
        st, body = get('/api/project')
        check(st == 200 and json.loads(body)['name'] == 'film', 'GET /api/project')
        st, body = get('/p/scenes/film.html')
        check(st == 200 and b'__seek' in body, 'GET /p/scenes/film.html serves the scene')
        try:
            st, _ = get('/p/../film.json')
        except urllib.error.HTTPError as e:
            st = e.code
        check(st == 404, 'path traversal refused')
        def get_h(path, headers, method='GET'):
            req = urllib.request.Request(url.rstrip('/') + path, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code
        check(get_h('/api/project', {'Host': 'evil.example:80'}) == 403, 'guard: foreign Host -> 403')
        check(get_h('/qa', {}) == 403, 'guard: /qa without the session token -> 403')
        check(get_h('/qa', {'X-Studio-Token': 'nope'}) == 403, 'guard: /qa with a wrong token -> 403')
        check(get_h('/qa', {'X-Studio-Token': srv['httpd'].token, 'Origin': 'http://evil.example'}) == 403, 'guard: foreign Origin -> 403')
        check(get_h('/api/project', {}, 'POST') == 405, 'guard: POST -> 405')
        st, body = get('/')
        check(st == 200 and ('studio-token" content="%s"' % srv['httpd'].token).encode('utf-8') in body, 'studio page embeds the session token')
        try:
            st, body = get('/')
            check(st == 200 and b'studio' in body.lower(), 'GET / serves studio/ui.html')
        except urllib.error.HTTPError as e:
            check(False, 'GET / -> %d (studio/ui.html missing?)' % e.code)
        st, body = get('/changes?since=0&timeout=2')
        v = json.loads(body)['version']
        check(st == 200 and v >= 1, 'long poll returns the current version immediately when since is stale')
        res = {}

        def poller():
            s, b = get('/changes?since=%d&timeout=8' % v, timeout=12)
            res['status'], res['body'] = s, json.loads(b)
        th = threading.Thread(target=poller)
        th.start()
        time.sleep(0.7)
        t_touch = time.time()
        with open(os.path.join(root, 'scenes', 'film.html'), 'a', encoding='utf-8') as fh:
            fh.write('\n<!-- touched -->\n')
        th.join(12)
        dt = time.time() - t_touch
        check(res.get('status') == 200 and res['body']['version'] == v + 1 and 'scenes/film.html' in res['body']['changed'] and dt < 3.0,
              'touching scenes/film.html wakes the long poll in %.2f s with the changed path' % dt)
        if with_tap:
            r = tap(root, 4.5, node_path=node_path)
            check(r.get('ok') and r.get('frame') == 135 and os.path.exists(os.path.join(root, r['png'])), 'tap t=4.5 -> frame 135 png (%s)' % (r.get('error') or '%.1f s' % r.get('wall_s', 0)))
            if r.get('ok'):
                try:
                    from PIL import Image
                    im = Image.open(os.path.join(root, r['png']))
                    check(im.size == (1920, 1080), 'tap is 1920x1080')
                except ImportError:
                    pass
        else:
            print('selftest  skip  tap (pass --with-tap; needs node + puppeteer, ~10 s)')
        srv['httpd'].shutdown()
        srv['watcher'].stop.set()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    ok = all(oks)
    print('selftest  %s  (%d checks, %.1f s)' % ('PASS' if ok else 'FAIL', len(oks), time.time() - t_start))
    return ok


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog='studio.py', description='Local preview studio for clock-driven film scenes (scrub / step / play / tap / hot reload).',
                                 epilog='Keys in the UI: left/right = 1 frame, shift = 10 frames, space = play, Home/End, T = tap, G = guides, Q = quick QA.')
    ap.add_argument('--project', default='.', help='film project directory (default: cwd; contains film.json, scenes/, out/)')
    ap.add_argument('--scene', default=None, help='scene path relative to the project (default: film.json "scene" or scenes/film.html)')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT, help='port (default 8765; 0 = ephemeral)')
    ap.add_argument('--host', default=DEFAULT_HOST, help='bind address (default 127.0.0.1 — keep it local)')
    ap.add_argument('--no-browser', action='store_true', help='do not open the browser')
    ap.add_argument('--node-path', default=None, help='NODE_PATH for the tap renderer (a node_modules with puppeteer)')
    ap.add_argument('--verbose', action='store_true', help='log every request')
    ap.add_argument('--manifest', action='store_true', help='print the project manifest JSON and exit')
    ap.add_argument('--tap', type=float, default=None, metavar='T', help='render one still at T seconds and exit (JSON)')
    ap.add_argument('--qa', action='store_true', help='run the quick lint and exit (JSON)')
    ap.add_argument('--selftest', action='store_true', help='synthetic fixture test (< 60 s)')
    ap.add_argument('--with-tap', action='store_true', help='selftest: also render one tap through node/puppeteer')
    a = ap.parse_args(argv)

    if a.selftest:
        return 0 if selftest(with_tap=a.with_tap, node_path=a.node_path) else 1
    project = os.path.abspath(a.project)
    if not os.path.isdir(project):
        ap.error('project directory not found: %s' % project)
    if a.manifest:
        print(json.dumps(manifest(project, a.scene), indent=1, sort_keys=True))
        return 0
    if a.tap is not None:
        r = tap(project, a.tap, a.scene, a.node_path)
        print(json.dumps(r, indent=1, sort_keys=True))
        return 0 if r.get('ok') else 1
    if a.qa:
        r = quick_qa(project, a.scene)
        print(json.dumps(r, indent=1, sort_keys=True))
        return 0 if r.get('ok') else 1
    cfg = project_config(project)
    scene = a.scene or cfg['scene']
    if not os.path.exists(os.path.join(project, scene)):
        ap.error('scene not found: %s (use --scene)' % os.path.join(project, scene))
    r = serve(project, a.scene, a.host, a.port, a.node_path, open_browser=not a.no_browser, verbose=a.verbose, block=True)
    return 2 if r is False else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
