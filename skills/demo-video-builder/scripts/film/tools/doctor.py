# -*- coding: utf-8 -*-
"""doctor.py — environment pre-flight for the film pipeline. One command that says what will break before the
first ten-minute render does.

    python tools/doctor.py [--project .] [--fast] [--offline] [--json]

  human mode   prints ok / WARN / FAIL per check with a one-line hint, exits 1 on any FAIL
  --json       {ok, platform, checks:[{name, ok, level, detail, hint}]} — ALWAYS exits 0 (gate on payload.ok);
               the home directory is redacted to ~ and nothing secret is ever printed
  --fast       the render subset only (ffmpeg, node + puppeteer, Chrome launch) — build_film.py runs this
  --offline    skip the edge-tts voice-list probe (it needs the network)

Checks (thresholds are HyperFrames' doctor numbers unless noted):
  python >= 3.10; pillow, numpy, edge_tts importable (faster_whisper optional)
  ffmpeg / ffprobe found AND start (`-version` with a 5 s timeout — a binary that exists but cannot start is
    'cannot start'); major >= 6; libx264 + aac encoders; filters loudnorm, sidechaincompress, alimiter,
    acrossover, lut3d, psnr (FFMPEG_PATH / FFPROBE_PATH env overrides are honoured; a configured path that does
    not exist is a FAIL)
  node >= 18; `require('puppeteer')` resolved from the project dir upward (and NODE_PATH) — prints where
  Chrome: PUPPETEER_EXECUTABLE_PATH -> puppeteer.executablePath() -> Program Files (the same order as
    render_frames.js), then a `--version` launch probe (5 s); Windows exit 3221225595 / 0xC0000409 means
    STATUS_STACK_BUFFER_OVERRUN -> point PUPPETEER_EXECUTABLE_PATH at the system Chrome
  edge-tts: `python -m edge_tts --list-voices` (10 s, warn-only: offline is not a build failure)
  fonts: credit.py's FONT_CANDIDATES present; every font-family the scene uses is declared or on this machine
  disk >= 2048 MB free at project/out and at %TEMP% (< 1024 MB is a FAIL, < 2048 MB a WARN)
  memory >= 2048 MB available
  project path: UNC (\\\\server\\share) -> WARN (Chrome may not launch from a network share); OneDrive-synced
    -> WARN (sync can lock part files mid-render)
  recording.mp4 present -> ffprobe decodable, 1920x1080 recommended
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HOME = os.path.expanduser('~')
HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)
MIN_FREE_FAIL_MB, MIN_FREE_WARN_MB, MIN_MEM_MB = 1024, 2048, 2048
TOOL_TIMEOUT = 5
REQUIRED_FILTERS = ['loudnorm', 'sidechaincompress', 'alimiter', 'acrossover', 'lut3d', 'psnr']
CHROME_CANDIDATES = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
                     '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium']
WINDOWS_CRASH = ('3221225595', '0xC0000409', 'STATUS_STACK_BUFFER_OVERRUN')


def redact(s):
    return str(s).replace(HOME, '~').replace(HOME.replace('\\', '/'), '~') if s else s


def _run(cmd, timeout=TOOL_TIMEOUT, **kw):
    """subprocess with a list (never a shell), returning (code, stdout+stderr) or (None, reason)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except FileNotFoundError:
        return None, 'not found'
    except subprocess.TimeoutExpired:
        return None, 'cannot start (timeout %ds)' % timeout
    except OSError as e:
        return None, 'cannot start (%s)' % type(e).__name__


class Doctor(object):
    def __init__(self, project=None, offline=False):
        self.project = os.path.abspath(project or os.getcwd())
        self.offline = offline
        self.checks = []

    def add(self, name, ok, detail='', hint='', level=None):
        level = level or ('ok' if ok else 'fail')
        self.checks.append({'name': name, 'ok': bool(ok) or level == 'warn', 'level': level, 'detail': redact(detail), 'hint': hint})

    # ---- python
    def python(self):
        v = sys.version_info
        self.add('python', v >= (3, 10), '%d.%d.%d' % v[:3], 'install Python 3.10 or newer')
        for mod, pip, req in (('PIL', 'pillow', True), ('numpy', 'numpy', True), ('edge_tts', 'edge-tts', True), ('faster_whisper', 'faster-whisper', False)):
            try:
                m = __import__(mod)
                self.add('pip ' + pip, True, getattr(m, '__version__', 'ok'))
            except Exception as e:
                self.add('pip ' + pip, not req, 'missing (%s)' % type(e).__name__, 'pip install %s' % pip, level=None if req else 'warn')

    # ---- ffmpeg
    def ffmpeg(self):
        for tool, env in (('ffmpeg', 'FFMPEG_PATH'), ('ffprobe', 'FFPROBE_PATH')):
            exe = os.environ.get(env) or tool
            if os.environ.get(env) and not os.path.exists(os.environ[env]):
                self.add(tool, False, '%s points to a missing file' % env, 'fix or unset %s' % env); continue
            code, out = _run([exe, '-version'])
            if code is None:
                self.add(tool, False, out, 'install ffmpeg >= 6 and put it on PATH (or set %s)' % env); continue
            m = re.search(r'version\s+(?:n)?(\d+)(?:\.(\d+))?', out)
            major = int(m.group(1)) if m else 0
            self.add(tool, major >= 6, 'v%s' % (m.group(0).split()[-1] if m else '?') + (' at ' + shutil.which(exe) if shutil.which(exe) else ''),
                     'ffmpeg >= 6 is needed for linear loudnorm + sidechaincompress')
            if tool == 'ffmpeg' and major:
                code, enc = _run([exe, '-hide_banner', '-encoders'], timeout=15)
                have = {e for e in ('libx264', 'aac') if re.search(r'\s%s\s' % e, enc or '')}
                self.add('ffmpeg encoders', have == {'libx264', 'aac'}, ', '.join(sorted(have)) or 'none', 'use a full ffmpeg build (libx264 + aac)')
                code, flt = _run([exe, '-hide_banner', '-filters'], timeout=15)
                missing = [f for f in REQUIRED_FILTERS if not re.search(r'\s%s\s' % f, flt or '')]
                self.add('ffmpeg filters', not missing, 'missing: ' + ', '.join(missing) if missing else ', '.join(REQUIRED_FILTERS),
                         'a full ffmpeg build ships every filter the mix/master/QA use')

    # ---- node / puppeteer / chrome
    def node(self):
        code, out = _run(['node', '--version'])
        if code is None:
            self.add('node', False, out, 'install Node 18+ (https://nodejs.org)'); return None
        major = int(re.sub(r'\D', '', out.split('.')[0]) or 0)
        self.add('node', major >= 18, out.strip(), 'Node 18 or newer')
        probe = ("try{const p=require.resolve('puppeteer');const pp=require('puppeteer');let ex='';try{ex=pp.executablePath()}catch(e){ex=''}"
                 "console.log(JSON.stringify({p,ex}))}catch(e){console.log(JSON.stringify({err:e.message.split('\\n')[0]}))}")
        code, out = _run(['node', '-e', probe], timeout=20, cwd=self.project)
        try:
            info = json.loads(out.strip().splitlines()[-1])
        except Exception:
            info = {'err': out.strip()[:120]}
        if info.get('err'):
            self.add('puppeteer', False, info['err'][:120], 'npm i puppeteer in the project or a parent folder (or set NODE_PATH)'); return None
        self.add('puppeteer', True, 'resolved from ' + info['p'])
        return info.get('ex') or ''

    def chrome(self, bundled):
        path = os.environ.get('PUPPETEER_EXECUTABLE_PATH')
        source = 'PUPPETEER_EXECUTABLE_PATH'
        if path and not os.path.exists(path):
            self.add('chrome', False, 'PUPPETEER_EXECUTABLE_PATH points to a missing file', 'fix or unset it'); return
        if not path and bundled and os.path.exists(bundled):
            path, source = bundled, 'puppeteer bundled browser'
        if not path:
            path = next((c for c in CHROME_CANDIDATES if os.path.exists(c)), None); source = 'system install'
        if not path:
            self.add('chrome', False, 'no Chrome found', 'npx puppeteer browsers install chrome, or install Google Chrome, or set PUPPETEER_EXECUTABLE_PATH'); return
        # On Windows `chrome.exe --version` detaches and prints nothing, so the launch probe goes through puppeteer
        # exactly like render_frames.js does: launch headless, read browser.version(), close.
        probe = ("const pp=require('puppeteer');(async()=>{const b=await pp.launch({headless:'new',executablePath:process.argv[1],"
                 "args:['--no-sandbox','--disable-gpu']});const v=await b.version();await b.close();console.log(v)})()"
                 ".catch(e=>{console.error(String(e&&e.message||e).split('\\n')[0]);process.exit(4)})")
        code, out = _run(['node', '-e', probe, path], timeout=TOOL_TIMEOUT * 6, cwd=self.project)
        if code is None or code != 0:
            hint = 'set PUPPETEER_EXECUTABLE_PATH to the system Chrome (chrome-headless-shell crashed with STATUS_STACK_BUFFER_OVERRUN)' \
                if any(w in str(out) for w in WINDOWS_CRASH) else 'the browser exists but cannot start headless; reinstall it or point PUPPETEER_EXECUTABLE_PATH elsewhere'
            self.add('chrome', False, '%s (%s) exit %s %s' % (path, source, code, str(out).strip()[:100]), hint); return
        self.add('chrome', True, '%s launches (%s: %s)' % (out.strip().splitlines()[-1], source, path))

    # ---- edge-tts
    def edge_tts(self):
        if self.offline:
            self.add('edge-tts', True, 'skipped (--offline)', level='warn'); return
        code, out = _run([sys.executable, '-m', 'edge_tts', '--list-voices'], timeout=15)
        if code == 0 and 'Neural' in out:
            self.add('edge-tts', True, '%d voices reachable' % len(re.findall(r'Neural', out)))
        else:
            self.add('edge-tts', True, 'voice list unavailable (offline?) %s' % str(out).strip()[:60], 'narration needs the network; cached vo/*.mp3 still build', level='warn')

    # ---- fonts
    def fonts(self):
        try:
            sys.path.insert(0, os.path.dirname(FILM_DIR)); sys.path.insert(0, self.project)
            import credit as CR
            present = [f for f in CR.FONT_CANDIDATES if os.path.exists(f)]
            self.add('credit font', bool(present), present[0] if present else 'none of FONT_CANDIDATES present', 'credit.py falls back to PIL default (ugly); install Segoe UI / Arial / DejaVu Sans')
        except Exception as e:
            self.add('credit font', True, 'credit.py not importable here (%s)' % type(e).__name__, level='warn')
        scene = os.path.join(self.project, 'scenes', 'film.html')
        if not os.path.exists(scene):
            return
        try:
            sys.path.insert(0, HERE)
            import fonts_localize as FL
            info = FL.scan_scene(open(scene, encoding='utf-8').read())
            unresolved, system = [], []
            for stack in info['stacks']:
                for fam in stack:
                    if fam.lower() in info['declared']:
                        continue
                    (system if FL.locate_family(fam) else unresolved).append(fam)
            unresolved, system = sorted(set(unresolved)), sorted(set(system))
            if unresolved:
                self.add('scene fonts', True, 'not on this machine: ' + ', '.join(unresolved), 'put the font you see first in the stack, or tools/fonts_localize.py', level='warn')
            elif system:
                self.add('scene fonts', True, 'OS fonts (not localized): ' + ', '.join(system), 'python tools/fonts_localize.py scenes/film.html for cross-machine reproducibility', level='warn')
            else:
                self.add('scene fonts', True, 'every family declared via @font-face')
        except Exception as e:
            self.add('scene fonts', True, 'font scan skipped (%s)' % type(e).__name__, level='warn')

    # ---- disk / memory / paths
    def disk(self):
        for label, p in (('disk project/out', os.path.join(self.project, 'out')), ('disk temp', tempfile.gettempdir())):
            q = p
            while not os.path.exists(q) and os.path.dirname(q) != q:
                q = os.path.dirname(q)
            try:
                free_mb = shutil.disk_usage(q).free // (1024 * 1024)
            except OSError as e:
                self.add(label, False, 'cannot stat %s (%s)' % (p, type(e).__name__)); continue
            level = 'fail' if free_mb < MIN_FREE_FAIL_MB else ('warn' if free_mb < MIN_FREE_WARN_MB else 'ok')
            self.add(label, level != 'fail', '%d MB free at %s' % (free_mb, q), 'a 3-worker render + wavs needs ~2 GB headroom', level=level)

    def memory(self):
        avail = None
        try:
            if sys.platform.startswith('win'):
                import ctypes
                class MS(ctypes.Structure):
                    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong), ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong), ('ullTotalVirtual', ctypes.c_ulonglong),
                                ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
                ms = MS(); ms.dwLength = ctypes.sizeof(MS)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                    avail = ms.ullAvailPhys // (1024 * 1024)
            elif os.path.exists('/proc/meminfo'):
                m = re.search(r'MemAvailable:\s+(\d+)', open('/proc/meminfo').read())
                avail = int(m.group(1)) // 1024 if m else None
            else:
                code, out = _run(['sysctl', '-n', 'hw.memsize'])
                avail = int(out.strip()) // (1024 * 1024) if code == 0 else None
        except Exception:
            avail = None
        if avail is None:
            self.add('memory', True, 'could not measure', level='warn')
        else:
            self.add('memory', avail >= MIN_MEM_MB, '%d MB available' % avail, 'close other apps or render with "workers": 1 in film.json')

    def paths(self):
        p = self.project.replace('/', '\\') if sys.platform.startswith('win') else self.project
        if p.startswith('\\\\'):
            self.add('project path', True, 'UNC path', 'Chrome may not launch from a network share; copy the project to a local disk', level='warn')
        elif re.search(r'onedrive|dropbox|google drive|icloud', self.project, re.I):
            self.add('project path', True, 'inside a synced folder', 'sync clients lock part files mid-render; pause sync or move the project', level='warn')
        else:
            self.add('project path', True, 'local disk')
        rec = os.path.join(self.project, 'recording.mp4')
        if os.path.exists(rec):
            code, out = _run([os.environ.get('FFPROBE_PATH') or 'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,codec_name', '-of', 'json', rec], timeout=15)
            try:
                s = json.loads(out)['streams'][0]
            except Exception:
                s = None
            if code == 0 and s:
                wh = '%sx%s' % (s.get('width'), s.get('height'))
                self.add('recording.mp4', True, '%s %s' % (wh, s.get('codec_name', '')), '1920x1080 is the expected capture size' if wh != '1920x1080' else '', level='ok' if wh == '1920x1080' else 'warn')
            else:
                self.add('recording.mp4', False, 'not decodable: ' + str(out).strip()[:80], 're-export the capture as H.264 MP4')

    def run(self, fast=False):
        if fast:
            self.ffmpeg(); bundled = self.node(); self.chrome(bundled)
        else:
            self.python(); self.ffmpeg(); bundled = self.node(); self.chrome(bundled); self.edge_tts(); self.fonts(); self.disk(); self.memory(); self.paths()
        ok = all(c['level'] != 'fail' for c in self.checks)
        return {'ok': ok, 'platform': '%s %s / python %s' % (platform.system(), platform.release(), platform.python_version()),
                'project': redact(self.project), 'checks': self.checks}


def main(argv):
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default
    rep = Doctor(project=opt('--project'), offline='--offline' in argv).run(fast='--fast' in argv)
    if '--json' in argv:
        print(json.dumps(rep, indent=1)); return 0            # always 0: callers gate on payload.ok
    print('doctor  %s  project %s' % (rep['platform'], rep['project']))
    for c in rep['checks']:
        tag = {'ok': 'ok  ', 'warn': 'WARN', 'fail': 'FAIL'}[c['level']]
        print('  %s  %-16s %s' % (tag, c['name'], c['detail']))
        if c['hint'] and c['level'] != 'ok':
            print('        -> ' + c['hint'])
    print('\n' + ('READY' if rep['ok'] else 'NOT READY: fix the FAIL lines above'))
    return 0 if rep['ok'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main(sys.argv[1:]))
