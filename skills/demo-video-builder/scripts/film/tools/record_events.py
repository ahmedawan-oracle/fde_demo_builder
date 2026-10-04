# -*- coding: utf-8 -*-
"""record_events.py — capture pointer, button and key telemetry WHILE you record a demo (Windows, ctypes only).

    python tools/record_events.py capture --out events.jsonl [--hz 60] [--clap-key F8] [--stop-key F9] [--no-text]
    python tools/record_events.py align events.jsonl --video recording.mp4 [--out events_aligned.jsonl]
    python tools/record_events.py align events.jsonl --offset 3.417            # when you know the clap's time in the video
    python tools/record_events.py align events.jsonl --clap-at 3.417           # same thing, said the other way
    python tools/record_events.py --selftest                                   # scripted poller + synthetic flash video, < 60 s
    python tools/record_events.py --help

Why. The footage lane erases the real pointer (median stills), so the film needs to know where the hand was in order
to redraw a clean cursor (lib/cursor.js), to show keystrokes (lib/hud.js) and to let the camera follow the work
(tools/camera_from_events.py). Capture-time telemetry is exact and free; tools/cursor_track.py is the fallback for
tapes recorded without it. Both write the same events.jsonl.

How it works (first principles)
  * Polling, not hooks. Every 1/60 s the loop calls user32.GetCursorPos (physical pixels; the process is made
    per-monitor-DPI-aware first so the numbers match the recording's pixels) and user32.GetAsyncKeyState for the three
    mouse buttons and every virtual key 0x08-0xFE. A key's state bit 0x8000 says "down now"; comparing with the
    previous tick gives down/up transitions. 60 Hz means a tap shorter than ~17 ms can be missed — human key presses
    last 60-120 ms, clicks 80-150 ms, so nothing of a demo is lost. No pynput, no global hook DLL, nothing injected.
  * Keys become names (Enter, Esc, Tab, F5, Left, Ctrl, ...) and, for printable keys, the character the active layout
    produces (user32.ToUnicode with the live Shift / CapsLock / AltGr state). A key event is written only for
    non-modifier keys, with the modifiers held at that moment in `mods` — Ctrl+K arrives as one event.
  * Time. Every event's t is seconds since the loop started (time.perf_counter). The recording has its own clock, so
    the two are joined with a CLAP: press the clap key once (default F8) while recording. The tool stores clap_t_raw
    and flashes a white, topmost, full-screen window for ~70 ms (2 frames at 30 fps) that the recording captures.
    `align --video` finds that flash (the first decoded frame whose mean luminance jumps by >= 60 to above 235,
    searched over the first --search seconds at 30 fps / 160x90 grey) and rewrites every t so that t = 0 is the
    recording's frame 0. Expected precision: within one video frame (the flash is drawn 2-6 ms after clap_t_raw and
    lasts two frames). If you forgot the clap, `--offset` / `--clap-at` do the same arithmetic by hand.
  * Multi-monitor / scaled captures. Coordinates are relative to the primary monitor's origin. For a recording of a
    secondary monitor pass `--origin X,Y` (that monitor's top-left in virtual-screen coordinates) and, when the
    recording's pixel size differs from the screen's, `--scale-to WxH` (both at align time; they are written to meta).

Privacy. This is a key logger while it runs. It writes to a local file only, records nothing until you start it and
stops at the stop key (default F9) or Ctrl+C. Do not type credentials while capturing; `--no-text` keeps only shortcut
and special keys (no printable characters) and is the right choice when a sign-in happens during the take. The
events file stays with the recording — it is as confidential as the tape (names typed into fields are in it).

events.jsonl (every line one JSON object; the first is the meta line; coordinates in SCREEN/recording pixels):
    {"type":"meta","tool":"record_events","hz":60,"screen":[1920,1080],"clap_t_raw":3.102,"aligned":false,...}
    {"t":0.017,"x":812,"y":440,"type":"move"}
    {"t":0.350,"x":812,"y":440,"type":"down","button":"left"}
    {"t":0.452,"x":812,"y":440,"type":"up","button":"left"}
    {"t":1.204,"x":812,"y":440,"type":"key","key":"K","mods":["Ctrl"],"char":null,"vk":75}
    {"t":2.010,"x":812,"y":440,"type":"key","key":"h","mods":[],"char":"h","vk":72}
Exit codes: 0 ok, 1 findings (e.g. no flash found, nothing captured), 2 usage / not Windows.
Deterministic where it matters: `align` and `--selftest` are pure functions of their inputs. Stdlib only (tkinter for
the flash; falls back to a console beep + printed clap time when tkinter is missing).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VERSION = '1.0'
IS_WIN = sys.platform.startswith('win')

VK_NAMES = {0x08: 'Backspace', 0x09: 'Tab', 0x0D: 'Enter', 0x13: 'Pause', 0x14: 'CapsLock', 0x1B: 'Esc', 0x20: 'Space',
            0x21: 'PageUp', 0x22: 'PageDown', 0x23: 'End', 0x24: 'Home', 0x25: 'Left', 0x26: 'Up', 0x27: 'Right', 0x28: 'Down',
            0x2C: 'PrintScreen', 0x2D: 'Insert', 0x2E: 'Delete', 0x5B: 'Win', 0x5C: 'Win', 0x5D: 'Menu', 0x90: 'NumLock', 0x91: 'ScrollLock',
            0xA0: 'Shift', 0xA1: 'Shift', 0xA2: 'Ctrl', 0xA3: 'Ctrl', 0xA4: 'Alt', 0xA5: 'Alt'}
for _i in range(24):
    VK_NAMES[0x70 + _i] = 'F%d' % (_i + 1)
MODIFIER_VKS = (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)
GENERIC_SKIP = (0x10, 0x11, 0x12, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x0A, 0x0B, 0x0C, 0x0E, 0x0F, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1E, 0x1F)
KEY_NAME_TO_VK = {v: k for k, v in VK_NAMES.items() if k not in (0x5C, 0xA1, 0xA3, 0xA5)}
BUTTONS = ((0x01, 'left'), (0x02, 'right'), (0x04, 'middle'))


# ---------------------------------------------------------------- Windows poller (ctypes)
class WinPoller:
    """GetCursorPos + GetAsyncKeyState + ToUnicode, nothing else. Constructed only on Windows."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.u32 = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)        # per-monitor DPI aware: physical pixels
        except Exception:
            try:
                self.u32.SetProcessDPIAware()
            except Exception:
                pass
        self.pt = wintypes.POINT()
        self.u32.GetAsyncKeyState.restype = ctypes.c_short
        self.u32.ToUnicode.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_wchar_p, ctypes.c_int, wintypes.UINT]
        self.state = (ctypes.c_ubyte * 256)()
        self.buf = ctypes.create_unicode_buffer(8)

    def screen(self):
        return [int(self.u32.GetSystemMetrics(0)), int(self.u32.GetSystemMetrics(1))]

    def virtual_screen(self):
        return [int(self.u32.GetSystemMetrics(i)) for i in (76, 77, 78, 79)]   # x, y, w, h

    def cursor(self):
        self.u32.GetCursorPos(self.ct.byref(self.pt))
        return int(self.pt.x), int(self.pt.y)

    def down(self, vk):
        return bool(self.u32.GetAsyncKeyState(vk) & 0x8000)

    def toggled(self, vk):
        return bool(self.u32.GetKeyState(vk) & 0x0001)

    def char_for(self, vk):
        """The character the active layout gives this key with the live Shift/CapsLock/AltGr state; None when not printable."""
        st = self.state
        for i in range(256):
            st[i] = 0
        if self.down(0xA0) or self.down(0xA1):
            st[0x10] = 0x80
        if self.down(0xA2) or self.down(0xA3):
            st[0x11] = 0x80
        if self.down(0xA4) or self.down(0xA5):
            st[0x12] = 0x80
        if self.toggled(0x14):
            st[0x14] = 0x01
        scan = self.u32.MapVirtualKeyW(vk, 0)
        n = self.u32.ToUnicode(vk, scan, st, self.buf, 8, 0)
        if n <= 0:
            return None
        ch = self.buf.value[:n]
        return ch if ch.isprintable() and ch.strip() else None


def flash_white(ms=70):
    """A topmost white full-screen window for ~ms (2 frames at 30 fps). Returns True when shown."""
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        r = tk.Tk()
        r.overrideredirect(True)
        r.attributes('-topmost', True)
        r.attributes('-fullscreen', True)
        r.configure(bg='white')
        r.update()
        time.sleep(ms / 1000.0)
        r.destroy()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- capture loop (poller-agnostic, so it can be tested)
class Capture:
    """Runs the polling loop against any poller exposing cursor()/down(vk)/char_for(vk). clock/sleep are injectable."""

    def __init__(self, poller, hz=60, clap_vk=0x77, stop_vk=0x78, no_text=False, clock=time.perf_counter, sleep=time.sleep, flash=flash_white, log=None):
        self.p, self.hz, self.clap_vk, self.stop_vk, self.no_text = poller, hz, clap_vk, stop_vk, no_text
        self.clock, self.sleep, self.flash, self.log = clock, sleep, flash, log or (lambda s: None)
        self.events, self.clap_t_raw, self.flash_shown = [], None, False
        self.vks = [vk for vk in range(0x08, 0xFF) if vk not in GENERIC_SKIP]

    def run(self, duration=None):
        p = self.p
        t0 = self.clock()
        period = 1.0 / self.hz
        prev_xy = None
        prev_btn = {b: False for _, b in BUTTONS}
        prev_key = {vk: False for vk in self.vks}
        tick = 0
        while True:
            now = self.clock()
            t = now - t0
            if duration is not None and t >= duration:
                break
            x, y = p.cursor()
            if (x, y) != prev_xy:
                self.events.append({'t': round(t, 4), 'x': x, 'y': y, 'type': 'move'})
                prev_xy = (x, y)
            for vk, name in BUTTONS:
                d = p.down(vk)
                if d != prev_btn[name]:
                    self.events.append({'t': round(t, 4), 'x': x, 'y': y, 'type': 'down' if d else 'up', 'button': name})
                    prev_btn[name] = d
            stop = False
            for vk in self.vks:
                d = p.down(vk)
                if d == prev_key[vk]:
                    continue
                prev_key[vk] = d
                if not d:
                    continue
                if vk == self.clap_vk:
                    if self.clap_t_raw is None:
                        self.clap_t_raw = round(t, 4)
                        self.log('clap at raw t = %.3f s — flashing' % t)
                        self.flash_shown = bool(self.flash()) or self.flash_shown
                    continue
                if vk == self.stop_vk:
                    stop = True
                    break
                if vk in MODIFIER_VKS:
                    continue
                mods = []
                if p.down(0xA2) or p.down(0xA3):
                    mods.append('Ctrl')
                if p.down(0xA4) or p.down(0xA5):
                    mods.append('Alt')
                if p.down(0xA0) or p.down(0xA1):
                    mods.append('Shift')
                if p.down(0x5B) or p.down(0x5C):
                    mods.append('Win')
                name = VK_NAMES.get(vk)
                ch = None if name else p.char_for(vk)
                if name is None:
                    name = ch if ch else 'VK%02X' % vk
                shortcut = any(m in mods for m in ('Ctrl', 'Alt', 'Win'))
                if self.no_text and ch is not None and not shortcut:
                    continue                                   # printable text suppressed by request
                if self.no_text and ch is not None:
                    ch = None
                self.events.append({'t': round(t, 4), 'x': x, 'y': y, 'type': 'key', 'key': name, 'mods': mods, 'char': ch, 'vk': vk})
            if stop:
                self.log('stop key — %d events' % len(self.events))
                break
            tick += 1
            target = t0 + tick * period
            dt = target - self.clock()
            if dt > 0:
                self.sleep(dt)
        return self.events


def write_events(path, events, meta):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(dict({'type': 'meta'}, **meta), sort_keys=True) + '\n')
        for e in events:
            f.write(json.dumps(e, sort_keys=True) + '\n')


def read_events(path):
    meta, events = {}, []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if o.get('type') == 'meta':
                meta = o
            else:
                events.append(o)
    return meta, events


# ---------------------------------------------------------------- the clap in the video
def find_flash(video, search_s=120.0, fps=30, thresh=235.0, jump=60.0):
    """Time of the first frame whose mean grey jumps by >= `jump` to >= `thresh`: the clap flash. None when absent."""
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-t', '%.3f' % search_s, '-i', video, '-vf', 'fps=%d,scale=160:90,format=gray' % fps,
           '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n, prev, k = 160 * 90, None, 0
    found = None
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n:
            break
        m = sum(buf) / float(n)
        if prev is not None and m >= thresh and m - prev >= jump:
            found = k / float(fps)
            break
        prev = m
        k += 1
    p.stdout.close()
    p.kill()
    p.wait()
    return found


def align(meta, events, offset=None, clap_at=None, video=None, origin=None, scale_to=None, search_s=120.0):
    """Rewrite t so that t = 0 is the recording's frame 0. Returns (meta, events, report). Pure given its inputs
    (the video is only read to find the flash). Exactly one of offset / clap_at / video is used, in that order."""
    rep = {}
    if offset is None:
        if clap_at is None and video is not None:
            clap_at = find_flash(video, search_s)
            rep['flash_found_at'] = clap_at
            if clap_at is None:
                return meta, events, dict(rep, error='no flash found in the first %.0f s — use --offset or --clap-at' % search_s)
        if clap_at is not None:
            if meta.get('clap_t_raw') is None:
                return meta, events, dict(rep, error='events have no clap_t_raw — use --offset')
            offset = clap_at - float(meta['clap_t_raw'])
    if offset is None:
        return meta, events, dict(rep, error='nothing to align with: pass --video, --clap-at or --offset')
    ox, oy = (origin or (0, 0))
    sxy = (1.0, 1.0)
    if scale_to and meta.get('screen'):
        sxy = (scale_to[0] / float(meta['screen'][0]), scale_to[1] / float(meta['screen'][1]))
    out = []
    for e in events:
        n = dict(e)
        n['t'] = round(e['t'] + offset, 4)
        n['x'] = round((e['x'] - ox) * sxy[0], 1) if sxy != (1.0, 1.0) else e['x'] - ox
        n['y'] = round((e['y'] - oy) * sxy[1], 1) if sxy != (1.0, 1.0) else e['y'] - oy
        out.append(n)
    m = dict(meta, aligned=True, offset=round(offset, 4), origin=[ox, oy], scale_to=list(scale_to) if scale_to else None)
    if scale_to:
        m['source'] = list(scale_to)
    elif meta.get('screen'):
        m['source'] = list(meta['screen'])
    rep.update(offset=round(offset, 4), events=len(out), first_t=out[0]['t'] if out else None, last_t=out[-1]['t'] if out else None)
    return m, out, rep


# ---------------------------------------------------------------- selftest
class ScriptedPoller:
    """A fake Windows: cursor along a line, left button 0.50-0.60 s, Ctrl held 0.78-0.86 s with K tapped at 0.80-0.84 s,
    'h' typed at 1.00-1.05 s, the clap key tapped at 0.20-0.24 s, the stop key at 1.40 s. Time comes from `clock`."""

    def __init__(self, clock):
        self.clock = clock
        self.t0 = clock()

    def _t(self):
        return self.clock() - self.t0

    def cursor(self):
        t = self._t()
        return int(100 + 400 * min(1.0, t / 1.2)), int(200 + 100 * min(1.0, t / 1.2))

    def down(self, vk):
        t = self._t()
        if vk == 0x01:
            return 0.50 <= t < 0.60
        if vk in (0xA2, 0xA3):
            return 0.78 <= t < 0.86
        if vk == 0x4B:
            return 0.80 <= t < 0.84
        if vk == 0x48:
            return 1.00 <= t < 1.05
        if vk == 0x77:
            return 0.20 <= t < 0.24
        if vk == 0x78:
            return t >= 1.40
        return False

    def toggled(self, vk):
        return False

    def char_for(self, vk):
        return {0x4B: 'k', 0x48: 'h'}.get(vk)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += max(0.0, dt)


def make_flash_video(path, flash_at_frame=20, n=60, fps=30, size=(320, 180)):
    """A 2 s synthetic clip: dark grey with a little texture, two white frames at flash_at_frame (Pillow + ffmpeg)."""
    from PIL import Image, ImageDraw
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % size, '-r', str(fps), '-i', '-',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for k in range(n):
        if flash_at_frame <= k < flash_at_frame + 2:
            im = Image.new('RGB', size, (255, 255, 255))
        else:
            im = Image.new('RGB', size, (40, 44, 52))
            d = ImageDraw.Draw(im)
            d.rectangle([20, 20, 300, 60], fill=(60, 66, 76))
            d.text((30, 30), 'Acme Console — synthetic clap test', fill=(200, 210, 220))
        p.stdin.write(im.tobytes())
    p.stdin.close()
    err = p.stderr.read()
    if p.wait() != 0:
        raise SystemExit('ffmpeg failed: ' + err.decode('utf-8', 'replace')[-200:])
    return path


def selftest():
    t_start = time.time()
    checks = []

    def ok(name, cond, detail=''):
        checks.append((name, bool(cond), detail))

    clk = FakeClock()
    cap = Capture(ScriptedPoller(clk.now), hz=60, clock=clk.now, sleep=clk.sleep, flash=lambda: True)
    ev = cap.run(duration=3.0)
    kinds = [e['type'] for e in ev]
    downs = [e for e in ev if e['type'] == 'down']
    ups = [e for e in ev if e['type'] == 'up']
    keys = [e for e in ev if e['type'] == 'key']
    ok('moves recorded', kinds.count('move') >= 60, '%d moves' % kinds.count('move'))
    ok('one left click, paired', len(downs) == 1 and len(ups) == 1 and downs[0]['button'] == 'left' and 0.08 <= ups[0]['t'] - downs[0]['t'] <= 0.12,
       '%s' % ([(d['t'], u['t']) for d, u in zip(downs, ups)]))
    ok('Ctrl+K as one event', any(k['key'] == 'K' or k['key'] == 'k' for k in keys) and any('Ctrl' in k['mods'] for k in keys),
       str([(k['key'], k['mods'], k['char']) for k in keys]))
    ok('typed h with char', any(k['char'] == 'h' and not k['mods'] for k in keys))
    ok('no bare modifier events', not any(k['key'] in ('Ctrl', 'Shift', 'Alt', 'Win') for k in keys))
    ok('clap recorded + flashed', cap.clap_t_raw is not None and abs(cap.clap_t_raw - 0.2) < 0.02 and cap.flash_shown, 'clap_t_raw=%s' % cap.clap_t_raw)
    ok('stopped at stop key', ev[-1]['t'] < 1.5, 'last t %.3f' % ev[-1]['t'])
    ok('monotonic time', all(ev[i]['t'] <= ev[i + 1]['t'] for i in range(len(ev) - 1)))
    cap2 = Capture(ScriptedPoller(clk.now), hz=60, clock=clk.now, sleep=clk.sleep, flash=lambda: True, no_text=True)
    # no_text: a fresh poller is timed from its own start, so re-run with a fresh clock origin
    clk2 = FakeClock()
    cap2 = Capture(ScriptedPoller(clk2.now), hz=60, clock=clk2.now, sleep=clk2.sleep, flash=lambda: True, no_text=True)
    ev2 = cap2.run(duration=3.0)
    k2 = [e for e in ev2 if e['type'] == 'key']
    ok('--no-text keeps shortcuts, drops text', len(k2) == 1 and 'Ctrl' in k2[0]['mods'] and k2[0]['char'] is None, str([(k['key'], k['mods'], k['char']) for k in k2]))

    meta = {'tool': 'record_events', 'version': VERSION, 'hz': 60, 'screen': [1920, 1080], 'clap_t_raw': cap.clap_t_raw, 'aligned': False}
    tmp = tempfile.mkdtemp(prefix='record_events_')
    vid = make_flash_video(os.path.join(tmp, 'flash.mp4'), flash_at_frame=20)
    m1, e1, r1 = align(meta, ev, video=vid, search_s=5)
    m2, e2, r2 = align(meta, ev, video=vid, search_s=5)
    ok('flash found at frame 20', r1.get('flash_found_at') is not None and abs(r1['flash_found_at'] - 20 / 30.0) <= 1 / 30.0 + 1e-6, str(r1.get('flash_found_at')))
    ok('aligned: clap lands on the flash', e1 and abs((cap.clap_t_raw + r1['offset']) - 20 / 30.0) <= 1 / 30.0 + 1e-6, 'offset %s' % r1.get('offset'))
    ok('align deterministic', json.dumps([m1, e1, r1], sort_keys=True) == json.dumps([m2, e2, r2], sort_keys=True))
    m3, e3, r3 = align(meta, ev, offset=2.5, origin=(1920, 0), scale_to=(1280, 720))
    ok('offset + origin + scale', e3 and abs(e3[0]['t'] - ev[0]['t'] - 2.5) < 1e-6 and m3['source'] == [1280, 720] and abs(e3[0]['x'] - (ev[0]['x'] - 1920) * (1280 / 1920.0)) < 0.11)
    p = os.path.join(tmp, 'events.jsonl')
    write_events(p, e1, m1)
    mm, ee = read_events(p)
    ok('round trip', mm.get('aligned') is True and len(ee) == len(e1))
    passed = all(c[1] for c in checks)
    print(json.dumps({'PASS': passed, 'checks': [{'name': n, 'ok': o, 'detail': d} for n, o, d in checks], 'events_sample': ev[:3] + downs + keys[:2],
                      'tmp': tmp, 'seconds': round(time.time() - t_start, 1)}, indent=1))
    return 0 if passed else 1


# ---------------------------------------------------------------- CLI
def _parse_key(name):
    if name.upper() in KEY_NAME_TO_VK:
        return KEY_NAME_TO_VK[name.upper()]
    if name.capitalize() in KEY_NAME_TO_VK:
        return KEY_NAME_TO_VK[name.capitalize()]
    if len(name) == 1:
        return ord(name.upper())
    raise SystemExit('unknown key name: %s (use F1..F24, Pause, ScrollLock, a letter, ...)' % name)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Pointer/button/key telemetry for a demo recording (Windows, ctypes). JSON lines out.')
    sub = ap.add_subparsers(dest='cmd')
    c = sub.add_parser('capture', help='poll at --hz until the stop key / Ctrl+C / --duration; press the clap key once while recording')
    c.add_argument('--out', default='events.jsonl')
    c.add_argument('--hz', type=int, default=60)
    c.add_argument('--clap-key', default='F8', help='hotkey that stores clap_t_raw and flashes the screen (default F8)')
    c.add_argument('--stop-key', default='F9', help='hotkey that ends the capture (default F9)')
    c.add_argument('--duration', type=float, help='stop after this many seconds')
    c.add_argument('--no-text', action='store_true', help='record shortcuts and special keys only — never printable characters')
    a_ = sub.add_parser('align', help='rewrite t so that t=0 is the recording\'s frame 0 (clap flash, --clap-at or --offset)')
    a_.add_argument('events')
    a_.add_argument('--video', help='the recording; the clap flash is searched in its first --search seconds')
    a_.add_argument('--search', type=float, default=120.0)
    a_.add_argument('--offset', type=float, help='seconds to add to every t (video time of the clap minus clap_t_raw)')
    a_.add_argument('--clap-at', type=float, help='video time of the clap flash, when you read it off the tape yourself')
    a_.add_argument('--origin', help='X,Y of the recorded monitor in virtual-screen coordinates (secondary monitors)')
    a_.add_argument('--scale-to', help='WxH of the recording when it differs from the screen size')
    a_.add_argument('--out', help='output path (default: <events>_aligned.jsonl)')
    ap.add_argument('--selftest', action='store_true', help='scripted poller + synthetic flash video; no Windows needed')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == 'capture':
        if not IS_WIN:
            print('capture needs Windows (user32); on other platforms use tools/cursor_track.py on the tape', file=sys.stderr)
            return 2
        poller = WinPoller()
        cap = Capture(poller, hz=a.hz, clap_vk=_parse_key(a.clap_key), stop_vk=_parse_key(a.stop_key), no_text=a.no_text, log=lambda s: print('  ' + s, file=sys.stderr))
        print('recording telemetry at %d Hz — press %s once while the screen recorder runs (clap), %s to stop%s' %
              (a.hz, a.clap_key, a.stop_key, '; printable text suppressed' if a.no_text else ''), file=sys.stderr)
        try:
            cap.run(a.duration)
        except KeyboardInterrupt:
            pass
        meta = {'tool': 'record_events', 'version': VERSION, 'hz': a.hz, 'screen': poller.screen(), 'virtual_screen': poller.virtual_screen(),
                'clap_t_raw': cap.clap_t_raw, 'flash_shown': cap.flash_shown, 'aligned': False, 'no_text': a.no_text,
                'clap_key': a.clap_key, 'stop_key': a.stop_key}
        write_events(a.out, cap.events, meta)
        findings = []
        if not cap.events:
            findings.append('no events captured')
        if cap.clap_t_raw is None:
            findings.append('no clap pressed — align with --offset or --clap-at')
        print(json.dumps({'out': a.out, 'events': len(cap.events), 'clap_t_raw': cap.clap_t_raw, 'flash_shown': cap.flash_shown, 'findings': findings}, indent=1))
        return 1 if findings else 0
    if a.cmd == 'align':
        meta, events = read_events(a.events)
        origin = tuple(int(v) for v in a.origin.split(',')) if a.origin else None
        scale_to = tuple(int(v) for v in a.scale_to.lower().split('x')) if a.scale_to else None
        m, e, rep = align(meta, events, offset=a.offset, clap_at=a.clap_at, video=a.video, origin=origin, scale_to=scale_to, search_s=a.search)
        if rep.get('error'):
            print(json.dumps(rep, indent=1))
            return 1
        out = a.out or os.path.splitext(a.events)[0] + '_aligned.jsonl'
        write_events(out, e, m)
        print(json.dumps(dict(rep, out=out), indent=1))
        return 0
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
