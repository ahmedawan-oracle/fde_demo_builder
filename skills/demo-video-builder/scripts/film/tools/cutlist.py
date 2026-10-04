# -*- coding: utf-8 -*-
"""cutlist.py — the edit as a text list (clip, length, start, speed, reverse) that round-trips with shots.js `play{}`.

    python tools/cutlist.py export   [--project DIR] [--out cutlist.txt]            out/timeline.json shots + broll meta → text list
    python tools/cutlist.py resolve  cutlist.txt [--auto-window] [--fit] [--max-speed 1.6] [--out cutlist.resolved.txt]
                                                 fill `auto` starts and `fit` speeds from the clips' own frames
    python tools/cutlist.py emit     cutlist.txt [--out scenes/cutlist_data.js]      → window.CUTLIST = {clip: {from, to, rate, reverse, pad}}
    python tools/cutlist.py check    cutlist.txt [--check-length]                    every row resolves; lengths match the shots on the clock
    python tools/cutlist.py render   cutlist.txt [--out out/cutlist_preview.mp4]     ffmpeg preview of the list (no browser)
    python tools/cutlist.py bump     v3.txt v4.txt --replace 'send=send_b' [--replace …] [--previous-film out/<film>.mp4]
                                                 version N+1 from N by text replacement; out/cutlist_bump.json names the changed
                                                 clips so gates/identity_gate.py can prove the untouched shots rendered the same
    python tools/cutlist.py --selftest

The list (whitespace- or |-separated, `#` comments; one row per footage shot that plays real motion):

    # clip     length   start   speed   reverse
    send       2.20     0.45    1.0     no          start = seconds into the source clip; speed 1.0 = real time
    wizard     3.00     auto    fit     no          auto = the window with the most motion; fit = speed to the slot
    answer     1.50     0.00    1.0     yes         reverse = play the window backwards

How a row becomes play{}: from = round(start·fps) + 1 (1-based source frame), rate = speed, to = from + ⌈length·fps·speed⌉ − 1
bounded by the clip; reverse rides through; `at` stays in shots.js because it is a cue (a spoken word), not a number:

    play: Object.assign({ at: SEND + 0.45 }, CUTLIST.send)         // scenes/cutlist_data.js, written by `emit`

Rules the list encodes (measured on our own footage):
  * --auto-window picks the `length·speed` seconds of the clip whose summed frame difference is largest — the window where
    the product actually does something — instead of the first N seconds.
  * --fit computes speed = available frames / required frames. A clip longer than its slot plays faster (up to --max-speed,
    default 1.6; beyond that the window is trimmed and the row says so). A clip shorter than its slot plays at 1.0 and its
    END STATE is held: `pad` frames clone the last frame (lib/footage.js already holds the last frame past `to`; ffmpeg
    previews use tpad=stop_mode=clone). The slot is never shortened — the narration is the clock.
  * --check-length: each row's length equals its shot's t1 − t0 on the clock within one frame; the sum of the rows equals
    the footage span. A list that does not add up fails (exit 1) before anything renders.
  * reverse is a real tool (a pull-back shot cut from a push-in; an undo shown as an undo) and footage.js plays it frame-exact.
Stdlib + Pillow (+ ffmpeg for `render` and for mp4 sources).
"""
import argparse, json, math, os, re, subprocess, sys, tempfile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

COLS = ('clip', 'length', 'start', 'speed', 'reverse')
MAX_SPEED, MIN_SPEED = 1.6, 0.5
YES = ('yes', 'y', 'true', '1', 'rev', 'reverse')


# ------------------------------------------------------------------------------------------------ the list
def parse(text):
    """text → [row dict]: clip, length (s), start (s | 'auto'), speed (float | 'fit'), reverse (bool), plus any 'k=v' extras."""
    rows = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in (line.split('|') if '|' in line else line.split())]
        parts = [p for p in parts if p != '']
        if len(parts) < 2:
            raise ValueError('line %d: a row needs at least clip and length: %r' % (ln, raw))
        row = {'clip': parts[0], 'length': float(parts[1]), 'start': 0.0, 'speed': 1.0, 'reverse': False, 'line': ln}
        extras = [p for p in parts[2:] if '=' in p]
        plain = [p for p in parts[2:] if '=' not in p]
        if len(plain) > 0:
            row['start'] = 'auto' if plain[0].lower() == 'auto' else float(plain[0])
        if len(plain) > 1:
            row['speed'] = 'fit' if plain[1].lower() == 'fit' else float(plain[1])
        if len(plain) > 2:
            row['reverse'] = plain[2].lower() in YES
        for e in extras:
            k, v = e.split('=', 1)
            row[k.strip()] = _num(v.strip())
        if row['length'] <= 0:
            raise ValueError('line %d: length must be positive' % ln)
        if isinstance(row['speed'], float) and row['speed'] <= 0:
            raise ValueError('line %d: speed must be positive' % ln)
        rows.append(row)
    return rows


def _num(v):
    try:
        return float(v) if '.' in v else int(v)
    except ValueError:
        return v


def format_rows(rows, header=True):
    out = ['# clip         length    start    speed   reverse   (resolved: from= to= rate= pad=)'] if header else []
    for r in rows:
        extra = ' '.join('%s=%s' % (k, r[k]) for k in ('from', 'to', 'pad', 'note') if k in r and r[k] not in (None, ''))
        line = '%-13s %-9s %-8s %-7s %-9s %s' % (r['clip'], '%.2f' % r['length'], r['start'] if isinstance(r['start'], str) else '%.2f' % r['start'],
                                                 r['speed'] if isinstance(r['speed'], str) else '%.3f' % r['speed'], 'yes' if r['reverse'] else 'no', extra)
        out.append(line.rstrip())
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------------------------------------------ clips
def clip_meta(project, name, broll='broll'):
    """{frames, fps, dir, files|mp4} for a seq clip: broll/<name>/meta.json, else broll/clips.js, else the f_*.jpg files, else <name>.mp4."""
    d = os.path.join(project, broll, name)
    meta = {}
    mp = os.path.join(d, 'meta.json')
    if os.path.exists(mp):
        try:
            meta = json.load(open(mp, encoding='utf-8'))
        except ValueError:
            meta = {}
    if not meta:
        cj = os.path.join(project, broll, 'clips.js')
        if os.path.exists(cj):
            m = re.search(r'=\s*(\{.*\})\s*;?\s*$', open(cj, encoding='utf-8').read(), re.S)
            if m:
                try:
                    meta = json.loads(m.group(1)).get(name, {}) or {}
                except ValueError:
                    meta = {}
    files = sorted(f for f in os.listdir(d) if re.match(r'^f_\d+\.(jpg|png)$', f)) if os.path.isdir(d) else []
    out = {'name': name, 'dir': d, 'files': files, 'fps': float(meta.get('fps', 30) or 30), 'frames': int(meta.get('frames') or len(files) or 0)}
    mp4 = os.path.join(project, broll, name + '.mp4')
    if not files and os.path.exists(mp4):
        out['mp4'] = mp4
        pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames,r_frame_rate',
                             '-of', 'default=nw=1', mp4], capture_output=True, text=True).stdout
        kv = dict(l.split('=', 1) for l in pr.splitlines() if '=' in l)
        if kv.get('r_frame_rate') and '/' in kv['r_frame_rate']:
            a, b = kv['r_frame_rate'].split('/'); out['fps'] = float(a) / float(b)
        if kv.get('nb_read_frames', '').isdigit():
            out['frames'] = int(kv['nb_read_frames'])
    if files and out['frames'] != len(files):
        out['frames'] = len(files)
    return out


def motion_series(meta, size=(160, 90)):
    """mean |diff| per consecutive frame pair (0..255), from the frame files (PIL) or the mp4 (ffmpeg)."""
    import numpy as np
    if meta.get('files'):
        from PIL import Image
        prev, out = None, []
        for f in meta['files']:
            with Image.open(os.path.join(meta['dir'], f)) as im:
                a = np.asarray(im.convert('L').resize(size, Image.BILINEAR), dtype=np.int16)
            if prev is not None:
                out.append(float(np.abs(a - prev).mean()))
            prev = a
        return out
    if meta.get('mp4'):
        w, h = size
        raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', meta['mp4'], '-vf', 'scale=%d:%d,format=gray' % (w, h), '-f', 'rawvideo', '-'], capture_output=True).stdout
        n = len(raw) // (w * h)
        fr = np.frombuffer(raw[:n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.int16)
        return [float(np.abs(fr[i] - fr[i - 1]).mean()) for i in range(1, n)]
    return []


def auto_window(series, win_frames):
    """first frame index (0-based) of the `win_frames`-long window with the largest summed motion."""
    if not series:
        return 0
    n = len(series) + 1
    win = max(1, min(win_frames, n))
    if win >= n:
        return 0
    # series[i] = change between frame i and i+1; a window of frames [a, a+win) spans series[a .. a+win-2]
    k = win - 1
    best, best_a, acc = -1.0, 0, sum(series[:k])
    for a in range(0, n - win + 1):
        if a > 0:
            acc += series[a + k - 1] - series[a - 1]
        if acc > best:
            best, best_a = acc, a
    return best_a


# ------------------------------------------------------------------------------------------------ resolve
def resolve(rows, project, auto=False, fit=False, max_speed=MAX_SPEED, min_speed=MIN_SPEED, fps_film=30, broll='broll'):
    """fill start/speed and derive from/to/rate/pad per row (in place). Returns [notes]."""
    notes = []
    for r in rows:
        m = clip_meta(project, r['clip'], broll)
        n, fps = m['frames'], m['fps']
        if not n:
            raise FileNotFoundError('%s: no frames under %s/%s (extract_clips.py first)' % (r['clip'], broll, r['clip']))
        r['fps'] = fps
        required = int(round(r['length'] * fps))
        speed = r['speed']
        if r['start'] == 'auto':
            if not auto:
                raise ValueError('%s: start is auto — pass --auto-window' % r['clip'])
            win = int(math.ceil(required * (speed if isinstance(speed, float) else 1.0)))
            a = auto_window(motion_series(m), win)
            r['start'] = round(a / fps, 3); r['note'] = 'auto-window'
        frm = int(round(float(r['start']) * fps)) + 1
        if frm > n:
            raise ValueError('%s: start %.2f s is past the clip (%d frames @ %g fps)' % (r['clip'], r['start'], n, fps))
        avail = n - frm + 1
        pad = 0
        if speed == 'fit':
            if not fit:
                raise ValueError('%s: speed is fit — pass --fit' % r['clip'])
            if avail >= required:
                speed = avail / float(required)
                if speed > max_speed:
                    notes.append('%s: fit wants %.2fx, capped at %.2fx — the window is trimmed to %.2f s of the clip' % (r['clip'], speed, max_speed, required * max_speed / fps))
                    speed = max_speed
            else:
                speed = 1.0; pad = required - avail
                notes.append('%s: %d frames short of the slot — the end state is held (%d cloned frames)' % (r['clip'], pad, pad))
            r['note'] = (r.get('note', '') + ' fit').strip()
        elif isinstance(speed, float):
            need = int(math.ceil(required * speed))
            if need > avail:
                pad = int(math.ceil((need - avail) / speed))
                notes.append('%s: the clip runs out %d frames before the slot ends — the end state is held (%d cloned frames)' % (r['clip'], need - avail, pad))
        r['speed'] = round(float(speed), 3)
        used = min(avail, int(math.ceil(required * r['speed'])))
        r['from'], r['to'], r['pad'], r['frames'], r['required'] = frm, frm + used - 1, pad, n, required
    return notes


def to_play(rows):
    """window.CUTLIST entries: {clip: {from, to, rate, reverse, pad}} — the play{} fields that are numbers, not cues."""
    out = {}
    for r in rows:
        if 'from' not in r:
            raise ValueError('%s: resolve the list first' % r['clip'])
        e = {'from': r['from'], 'to': r['to'], 'rate': r['speed']}
        if r['reverse']:
            e['reverse'] = True
        if r.get('pad'):
            e['pad'] = r['pad']
        out[r['clip']] = e
    return out


def from_timeline(project, broll='broll'):
    """out/timeline.json shots that play a seq clip → rows (the round trip back from shots.js)."""
    tl = json.load(open(os.path.join(project, 'out', 'timeline.json'), encoding='utf-8'))
    rows = []
    for s in tl.get('shots', []):
        p = s.get('play')
        if not p or s.get('t1') is None:
            continue
        m = clip_meta(project, s['clip'], broll)
        fps = m['fps'] or 30
        frm = int(p.get('from') or 1)
        rate = p.get('rate') if isinstance(p.get('rate'), (int, float)) else 1.0
        rows.append({'clip': s['clip'], 'length': round(float(s['t1']) - float(s['t0']), 3), 'start': round((frm - 1) / fps, 3), 'speed': float(rate),
                     'reverse': bool(p.get('reverse')), 'line': 0})
    return rows, tl


def check_length(rows, tl, fps_film=30):
    """[errors]: each row's length equals its shot's span within one frame; the rows' sum equals the footage span of those shots."""
    E = []
    shots = {s['clip']: s for s in tl.get('shots', []) if s.get('t1') is not None}
    seen, total = 0, 0.0
    for r in rows:
        total += r['length']
        s = shots.get(r['clip'])
        if not s:
            E.append('%s: no shot plays this clip on the clock (out/timeline.json)' % r['clip']); continue
        seen += 1
        span = float(s['t1']) - float(s['t0'])
        if abs(span - r['length']) > 1.0 / fps_film + 1e-6:
            E.append('%s: length %.2f s but the shot runs %.2f s (%.2f–%.2f) — the slot is the clock, change the list' % (r['clip'], r['length'], span, s['t0'], s['t1']))
    spans = sum(float(shots[r['clip']]['t1']) - float(shots[r['clip']]['t0']) for r in rows if r['clip'] in shots)
    if seen and abs(spans - total) > 1.0 / fps_film + 1e-6:
        E.append('rows sum to %.2f s, their shots to %.2f s' % (total, spans))
    return E


# ------------------------------------------------------------------------------------------------ bump: N → N+1
def bump(src_text, replacements):
    """apply 'a=b' replacements row by row → (new_text, changed_clips, rows_changed). Comments and blank lines ride through."""
    out, changed, nrows = [], [], 0
    for raw in src_text.splitlines():
        line = raw
        for a, b in replacements:
            line = line.replace(a, b)
        body = raw.split('#', 1)[0].strip()
        if body and line != raw:
            nrows += 1
            parts = body.split('|') if '|' in body else body.split()
            changed.append(parts[0].strip())
            new_body = line.split('#', 1)[0].strip()
            new_parts = new_body.split('|') if '|' in new_body else new_body.split()
            if new_parts and new_parts[0].strip() != parts[0].strip():
                changed.append(new_parts[0].strip())            # a renamed clip: both names count as changed
        out.append(line)
    return '\n'.join(out) + ('\n' if src_text.endswith('\n') else ''), sorted(set(changed)), nrows


# ------------------------------------------------------------------------------------------------ preview
def render(rows, project, out, broll='broll', fps_film=30):
    """ffmpeg assembly of the resolved list: trim window → reverse → speed → pad (clone last frame) → exactly length·fps frames."""
    tmp = tempfile.mkdtemp(prefix='cutlist_')
    segs = []
    for i, r in enumerate(rows):
        m = clip_meta(project, r['clip'], broll)
        fps = m['fps']
        count = r['to'] - r['from'] + 1
        want = int(round(r['length'] * fps_film))
        filt = []
        if r['reverse']:
            filt.append('reverse')
        filt.append('setpts=PTS/%.6f' % r['speed'])
        filt.append('fps=%d' % fps_film)
        filt.append('tpad=stop_mode=clone:stop=%d' % max(0, want))          # hold the end state as long as the slot needs, then cut to length
        seg = os.path.join(tmp, 'seg_%02d.mp4' % i)
        if m.get('files'):
            pat = os.path.join(m['dir'], re.sub(r'\d+', lambda mm: '%%0%dd' % len(mm.group()), m['files'][0], count=1))
            cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-framerate', '%g' % fps, '-start_number', str(r['from']), '-i', pat, '-frames:v', str(count)]
            cmd = cmd[:-2] + ['-vf', 'select=lt(n\\,%d),' % count + ','.join(filt), '-frames:v', str(want)]
        else:
            cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', m['mp4'], '-vf', 'select=between(n\\,%d\\,%d),setpts=N/FRAME_RATE/TB,' % (r['from'] - 1, r['to'] - 1) + ','.join(filt), '-frames:v', str(want)]
        cmd += ['-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', '-r', str(fps_film), seg]
        rr = subprocess.run(cmd, capture_output=True, text=True)
        if rr.returncode != 0:
            raise RuntimeError('%s: ffmpeg failed: %s' % (r['clip'], rr.stderr[-400:]))
        segs.append(seg)
    lst = os.path.join(tmp, 'list.txt')
    open(lst, 'w', encoding='utf-8').write(''.join("file '%s'\n" % s.replace('\\', '/') for s in segs))
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    rr = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', out], capture_output=True, text=True)
    if rr.returncode != 0:
        raise RuntimeError('concat failed: %s' % rr.stderr[-400:])
    return out


def _frames_of(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path], capture_output=True, text=True)
    return int(r.stdout.strip() or 0)


# ------------------------------------------------------------------------------------------------ selftest
def selftest():
    import shutil
    import numpy as np
    from PIL import Image
    d = tempfile.mkdtemp(prefix='cutlist_selftest_')
    fps = 30
    # clip "send": 90 frames (3 s); still for 1 s, a square crosses the frame during 1.0–2.0 s, still again; brightness encodes the frame index
    cd = os.path.join(d, 'broll', 'send'); os.makedirs(cd)
    for k in range(90):
        f = np.full((90, 160), 30, np.uint8)
        f[0:4, :] = min(255, 40 + 2 * k)                      # a frame-index strip (top rows)
        if 30 <= k < 60:                                      # the square slides in from off-frame and out again: no appearance jump
            x = -18 + (k - 30) * 6; f[30:60, max(0, x):max(0, x + 20)] = 220
        Image.fromarray(f).save(os.path.join(cd, 'f_%03d.jpg' % (k + 1)), quality=95)
    json.dump({'kind': 'seq', 'frames': 90, 'fps': fps}, open(os.path.join(cd, 'meta.json'), 'w'))
    # clip "short": 20 frames (0.67 s) for the fit / pad path
    sd = os.path.join(d, 'broll', 'short'); os.makedirs(sd)
    for k in range(20):
        f = np.full((90, 160), 30 + 5 * k, np.uint8); Image.fromarray(f).save(os.path.join(sd, 'f_%03d.jpg' % (k + 1)), quality=95)
    json.dump({'kind': 'seq', 'frames': 20, 'fps': fps}, open(os.path.join(sd, 'meta.json'), 'w'))
    os.makedirs(os.path.join(d, 'out'))
    json.dump({'total': 10.0, 'shots': [{'clip': 'send', 't0': 2.0, 't1': 3.0, 'play': {'at': 2.0, 'from': 31, 'to': 60, 'rate': 1}},
                                        {'clip': 'short', 't0': 3.0, 't1': 4.0, 'play': {'at': 3.0, 'from': 1, 'rate': 1}}]},
              open(os.path.join(d, 'out', 'timeline.json'), 'w'))
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    rows = parse('# clip length start speed reverse\nsend 1.00 auto 1.0 no\nshort 1.00 0.0 fit yes\n')
    t(rows[0]['start'] == 'auto' and rows[1]['speed'] == 'fit' and rows[1]['reverse'] is True, 'parse: auto / fit / reverse columns')
    notes = resolve(rows, d, auto=True, fit=True)
    t(rows[0]['start'] == 1.0 and rows[0]['from'] == 31 and rows[0]['to'] == 60, '--auto-window finds the 1 s window where the square moves (start %.2f, frames %d–%d)' % (rows[0]['start'], rows[0]['from'], rows[0]['to']))
    t(rows[1]['speed'] == 1.0 and rows[1]['pad'] == 10 and rows[1]['to'] == 20 and any('held' in n for n in notes), '--fit: a 20-frame clip in a 30-frame slot plays at 1.0 and holds its end state for 10 frames')
    v3 = '# clip length start speed reverse\nsend 1.00 1.00 1.0 no\nshort 1.00 0.0 1.0 yes\n'
    v4, ch, nr = bump(v3, [('short 1.00 0.0 1.0 yes', 'short 1.00 0.0 1.2 yes')])
    t(ch == ['short'] and nr == 1 and 'send 1.00 1.00 1.0 no' in v4 and '1.2' in v4 and parse(v4)[1]['speed'] == 1.2, 'bump: text replacement changes one row, names the changed clip (%s)' % ch)
    v5, ch2, _ = bump(v3, [('send', 'send_b')])
    t(ch2 == ['send', 'send_b'], 'bump: a renamed clip counts both names as changed (%s)' % ch2)
    rows2 = parse('send 1.00 0.00 fit no\n'); resolve(rows2, d, fit=True)
    t(abs(rows2[0]['speed'] - 1.6) < 1e-9 and rows2[0]['to'] == 48, '--fit: a 3 s clip in a 1 s slot wants 3x, capped at 1.6x (frames 1–%d)' % rows2[0]['to'])
    rows3 = parse('send 1.00 0.00 fit no\n'); resolve(rows3, d, fit=True, max_speed=3.0)
    t(rows3[0]['speed'] == 3.0 and rows3[0]['to'] == 90, '--fit --max-speed 3: the whole clip fits the slot at 3x')
    P = to_play(rows)
    t(P['send'] == {'from': 31, 'to': 60, 'rate': 1.0} and P['short'] == {'from': 1, 'to': 20, 'rate': 1.0, 'reverse': True, 'pad': 10}, 'emit: play{} entries (%s)' % P)
    back, tl = from_timeline(d)
    t([(r['clip'], r['length'], r['start'], r['speed']) for r in back] == [('send', 1.0, 1.0, 1.0), ('short', 1.0, 0.0, 1.0)], 'export: timeline.json shots → rows (round trip)')
    t(check_length(rows, tl) == [] and any('runs 1.00 s' in e for e in check_length(parse('send 1.50 1.0 1.0 no\n'), tl)), '--check-length: matching rows pass, a 1.5 s row against a 1.0 s shot fails')
    txt = format_rows(rows)
    t(parse(txt)[0]['from'] == 31 and parse(txt)[1]['pad'] == 10, 'format → parse keeps the resolved columns (%d chars)' % len(txt))
    # ffmpeg preview: 60 frames; the reversed short clip opens on its LAST source frame (brightest) and holds it from frame 50 on
    out = os.path.join(d, 'out', 'preview.mp4')
    render(rows, d, out)
    n = _frames_of(out)
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', out, '-vf', 'crop=160:40:0:40,format=gray', '-f', 'rawvideo', '-'], capture_output=True).stdout
    fr = np.frombuffer(raw[:n * 160 * 40], dtype=np.uint8).reshape(n, 40, 160)
    means = [float(x.mean()) for x in fr]
    t(n == 60, 'render: exactly 60 frames for two 1 s rows (%d)' % n)
    t(means[30] > means[31] > means[40] and abs(means[49] - means[50]) < 2 and abs(means[50] - means[59]) < 2, 'render: reversed clip gets darker frame by frame, then holds its end state (cloned frames)')
    # footage.js plays the same numbers (node, pure function)
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib')
    if os.path.exists(os.path.join(lib, 'footage.js')) and shutil.which('node'):
        js = ("global.window=global;require(%r);require(%r);const c={frames:20,fps:30};const f=t=>FOOT.seqFrameIndex({t0:3,play:Object.assign({at:3},%s)},c,t);"
              "console.log([f(3.0),f(3.1),f(3.6),f(3.9)].join(','));" % (os.path.join(lib, 'grammar.js').replace('\\', '/'), os.path.join(lib, 'footage.js').replace('\\', '/'), json.dumps(P['short'])))
        r = subprocess.run(['node', '-e', js], capture_output=True, text=True)
        t(r.stdout.strip() == '20,17,2,1', 'footage.js seqFrameIndex plays the reversed window and holds frame 1 (%s)' % r.stdout.strip())
    shutil.rmtree(d, ignore_errors=True)
    print('cutlist selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


# ------------------------------------------------------------------------------------------------ CLI
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='cutlist.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['export', 'resolve', 'emit', 'check', 'render', 'bump'])
    ap.add_argument('list', nargs='?', help='the cut list (not for export)')
    ap.add_argument('target', nargs='?', help='bump: the new list to write')
    ap.add_argument('--replace', action='append', default=[], help="bump: 'old=new' text replacement (repeatable)")
    ap.add_argument('--previous-film', help='bump: the render of the previous list, for gates/identity_gate.py')
    ap.add_argument('--project', default=os.getcwd()); ap.add_argument('--out'); ap.add_argument('--broll', default='broll')
    ap.add_argument('--auto-window', action='store_true'); ap.add_argument('--fit', action='store_true')
    ap.add_argument('--max-speed', type=float, default=MAX_SPEED); ap.add_argument('--check-length', action='store_true')
    ap.add_argument('--fps', type=int, default=30, help='film frame rate (the clock)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    project = os.path.abspath(a.project)
    if a.cmd == 'export':
        rows, tl = from_timeline(project, a.broll)
        txt = format_rows(rows)
        out = a.out or os.path.join(project, 'cutlist.txt')
        open(out, 'w', encoding='utf-8', newline='\n').write(txt)
        print(txt.rstrip()); print('wrote %s (%d rows from out/timeline.json)' % (os.path.relpath(out, project), len(rows))); return 0
    if not a.list or not os.path.exists(a.list):
        print('%s needs the cut list file' % a.cmd, file=sys.stderr); return 2
    if a.cmd == 'bump':
        if not a.target or not a.replace or any('=' not in r for r in a.replace):
            print("bump v3.txt v4.txt --replace 'old=new' [--replace …]", file=sys.stderr); return 2
        reps = [tuple(r.split('=', 1)) for r in a.replace]
        new_text, changed, nrows = bump(open(a.list, encoding='utf-8').read(), reps)
        parse(new_text)                                            # the bumped list must still parse
        open(a.target, 'w', encoding='utf-8', newline='\n').write(new_text)
        os.makedirs(os.path.join(project, 'out'), exist_ok=True)
        rec = {'from': os.path.relpath(a.list, project).replace('\\', '/'), 'to': os.path.relpath(a.target, project).replace('\\', '/'),
               'replacements': ['%s=%s' % r for r in reps], 'rows_changed': nrows, 'changed': changed,
               'previous_film': (os.path.relpath(a.previous_film, project).replace('\\', '/') if a.previous_film else None)}
        json.dump(rec, open(os.path.join(project, 'out', 'cutlist_bump.json'), 'w', encoding='utf-8'), indent=1)
        print('%s → %s: %d row(s) changed, clips %s → out/cutlist_bump.json%s' % (rec['from'], rec['to'], nrows, changed or '—',
              '' if a.previous_film else '  (add --previous-film so identity_gate can compare the renders)'))
        return 0
    rows = parse(open(a.list, encoding='utf-8').read())
    tl_p = os.path.join(project, 'out', 'timeline.json')
    tl = json.load(open(tl_p, encoding='utf-8')) if os.path.exists(tl_p) else None
    try:
        notes = resolve(rows, project, auto=a.auto_window or a.cmd == 'resolve', fit=a.fit or a.cmd == 'resolve', max_speed=a.max_speed, fps_film=a.fps, broll=a.broll)
    except (ValueError, FileNotFoundError) as e:
        print('FAIL  %s' % e); return 1
    for n in notes:
        print('note  ' + n)
    E = check_length(rows, tl, a.fps) if (a.check_length and tl) else []
    if a.check_length and not tl:
        E.append('--check-length needs out/timeline.json (node export_timeline.js first)')
    if a.cmd == 'resolve':
        out = a.out or re.sub(r'(\.txt)?$', '.resolved.txt', a.list, count=1)
        open(out, 'w', encoding='utf-8', newline='\n').write(format_rows(rows)); print(format_rows(rows).rstrip()); print('wrote %s' % out)
    elif a.cmd == 'emit':
        P = to_play(rows)
        out = a.out or os.path.join(project, 'scenes', 'cutlist_data.js')
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        open(out, 'w', encoding='utf-8', newline='\n').write('/* generated by tools/cutlist.py from %s -- do not edit; shots.js: play: Object.assign({ at: <cue> }, CUTLIST.<clip>) */\nwindow.CUTLIST = %s;\n'
                                                               % (os.path.basename(a.list), json.dumps(P, indent=1)))
        print(json.dumps(P, indent=1) if a.json else 'wrote %s (%d clips)' % (os.path.relpath(out, project), len(P)))
    elif a.cmd == 'render':
        out = a.out or os.path.join(project, 'out', 'cutlist_preview.mp4')
        render(rows, project, out, a.broll, a.fps); print('preview %s (%d frames)' % (os.path.relpath(out, project), _frames_of(out)))
    else:
        print(format_rows(rows).rstrip())
    for e in E:
        print('FAIL  ' + e)
    print('cutlist %s (%d rows%s)' % ('FAILED' if E else 'OK', len(rows), ', lengths checked' if a.check_length and tl else ''))
    return 1 if E else 0


if __name__ == '__main__':
    sys.exit(main())
