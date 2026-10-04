# -*- coding: utf-8 -*-
"""camera_from_events.py — propose camera cues from where the presenter actually worked (clicks and typing).

    python tools/camera_from_events.py events.jsonl --out out/camera_auto.json [--md out/camera_auto.md]
                                       [--source 1920x1080] [--rec-start 12.0 --film-t0 8.4] [--max-upsample 1.6]
    python tools/camera_from_events.py --selftest
    python tools/camera_from_events.py --help

Why. A film built from a real recording should move the frame to where the hand is working without the author
hand-writing every zoom cue. events.jsonl (from record_events.py or cursor_track.py) says where clicks and keystrokes
happened; this tool turns them into a short list of proposed camera moves for shots.js, with a storyboard fragment the
author reads and accepts. It proposes; the storyboard decides.

Method
  1. Attention points. Every `down` (click) is a point. Every `key` event is a point placed at the last click within
     5 s (typing happens where the field was clicked), else at the pointer. Pointer movement alone is not attention.
  2. Islands. Points are chained in time order: a point joins the open island when it is <= 1.2 s after the island's
     last point and <= 220 px from the island's centroid (source px); otherwise a new island starts. This is a
     density link in space-time (one-pass, DBSCAN-like with eps = 220 px / 1.2 s, minPts = 1), so a typed sentence
     plus its send button become one island and a click on the far side of the screen starts another.
  3. Pose from the ladder. Each island gets a target box (its points' bounds, padded 120 px, never smaller than
     480x270 source px). The pose is the LARGEST zoom in the ladder 1.0 / 1.35 / 1.6 / 2.0 whose viewport
     (source W/z x H/z) still contains the box, and whose upsample (z x 1920 / W, the camera.js budget) is <=
     --max-upsample (default 1.6 = motion_diag's WARN line; 2.0 is its FAIL line and is only reachable by asking for
     it). A lone click is a glance and is capped at 1.35; typing or several clicks are the work and may take the
     largest rung that fits. Centre = box centre, clamped so the viewport stays inside the frame. When no zoom > 1
     fits, the camera stays wide (cause says so).
  4. Timing (the measured camera rules in references/cinematic-grammar.md and camera.js RULES): the push starts
     0.8 s before the island's first point and lasts 1.0 s, so it lands just after the click; the pose is held from
     arrival until 0.6 s after the island's last point and never less than 2.0 s; two consecutive islands that fit
     in one viewport are merged into one hold; a hold longer than 6 s with nothing happening pulls back to 1.0
     (nothing stays static for long); between islands the camera pulls back to 1.0 (1.0 s) when there is room for
     pull + 1.0 s dwell + push, otherwise it pans/zooms directly from pose to pose in one move; a final pull-back
     closes the sequence unless the clip ends within 1.5 s. Every move is >= 0.8 s (under that teleports) and
     <= 2.5 s, and >= 1.0 s of dwell separates two moves.
  5. Film time. Events are in RECORDING seconds; a shot shows recording time rec_start at film time film_t0, so
     t_film = t_rec - rec_start + film_t0 (--rec-start / --film-t0, default 0 / 0 = same clock).

Output camera_auto.json:
    {"source":[1920,1080], "stage":[1280,720], "islands":[{"t0","t1","n_clicks","n_keys","box":[x,y,w,h],"zoom","centre":[x,y]}],
     "cues":[{"t":12.4,"dur":1.0,"zoom":1.35,"cx":640,"cy":300,"src":[960,450],"hold":3.2,"cause":"3 clicks + 12 keys ...","ease":"io"}],
     "moves_js":"{ t0: 12.40, dur: 1.0, s: 1.35, c: [640, 300], ease: 'io', abs: true },  // ...", "lint":[...], "budget":{...}}
  cx/cy are STAGE pixels (1280x720) — exactly what a shots.js move with abs:true takes; src is the same point in
  source pixels. camera_auto.md is the storyboard fragment: one "- camera:" line per cue in the STORYBOARD.md field
  grammar, ready to paste into the beat and edit.
Exit codes: 0 ok, 1 findings (a lint item or a cue over the budget), 2 usage. Deterministic: sorted, seedless, no clock.
Stdlib only.
"""
import argparse
import json
import math
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

VERSION = '1.0'
LADDER = (1.0, 1.35, 1.6, 2.0)
RULES = {
    'link_px': 220.0, 'link_s': 1.2,          # island chaining (space / time)
    'key_click_window': 5.0,                  # a key event sits at the last click within this many seconds
    'pad_px': 120.0, 'min_box': (480.0, 270.0),
    'lead': 0.8, 'push': 1.0, 'pull': 1.0,    # seconds: push starts `lead` before the first point; move durations
    'tail': 0.6, 'min_hold': 2.0, 'max_hold': 6.0,
    'dwell': 1.0, 'move_min': 0.8, 'move_max': 2.5,
    'warn_upsample': 1.6, 'fail_upsample': 2.0, 'out_w': 1920.0,
    'end_slack': 1.5,
}
STAGE = (1280.0, 720.0)


# ---------------------------------------------------------------- input
def read_events(path):
    meta, ev = {}, []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                o = json.loads(line)
                if o.get('type') == 'meta':
                    meta = o
                else:
                    ev.append(o)
    ev.sort(key=lambda e: (e['t'], e['type']))
    return meta, ev


def attention_points(events, rules=RULES):
    """[(t, x, y, kind)] — clicks, and keys placed at the last click within key_click_window."""
    pts, last_click = [], None
    for e in events:
        if e['type'] == 'down':
            last_click = (e['t'], e['x'], e['y'])
            pts.append((e['t'], float(e['x']), float(e['y']), 'click'))
        elif e['type'] == 'key':
            if last_click and e['t'] - last_click[0] <= rules['key_click_window']:
                pts.append((e['t'], float(last_click[1]), float(last_click[2]), 'key'))
            else:
                pts.append((e['t'], float(e['x']), float(e['y']), 'key'))
    return pts


def islands(points, rules=RULES):
    """Chain points into attention islands (eps 220 px / 1.2 s, one pass in time order)."""
    out = []
    for t, x, y, kind in points:
        if out:
            isl = out[-1]
            cx, cy = isl['sx'] / isl['n'], isl['sy'] / isl['n']
            if t - isl['t1'] <= rules['link_s'] and math.hypot(x - cx, y - cy) <= rules['link_px']:
                isl['t1'] = t
                isl['n'] += 1
                isl['sx'] += x
                isl['sy'] += y
                isl['xs'].append(x)
                isl['ys'].append(y)
                isl['n_clicks' if kind == 'click' else 'n_keys'] += 1
                continue
        out.append({'t0': t, 't1': t, 'n': 1, 'sx': x, 'sy': y, 'xs': [x], 'ys': [y],
                    'n_clicks': 1 if kind == 'click' else 0, 'n_keys': 1 if kind == 'key' else 0})
    res = []
    for isl in out:
        x0, x1, y0, y1 = min(isl['xs']), max(isl['xs']), min(isl['ys']), max(isl['ys'])
        res.append({'t0': round(isl['t0'], 3), 't1': round(isl['t1'], 3), 'n_clicks': isl['n_clicks'], 'n_keys': isl['n_keys'],
                    'points': [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)]})
    return res


# ---------------------------------------------------------------- pose
def target_box(isl, source, rules=RULES):
    x, y, w, h = isl['points']
    pad = rules['pad_px']
    bx, by, bw, bh = x - pad, y - pad, w + 2 * pad, h + 2 * pad
    mw, mh = rules['min_box']
    if bw < mw:
        bx -= (mw - bw) / 2.0
        bw = mw
    if bh < mh:
        by -= (mh - bh) / 2.0
        bh = mh
    W, H = source
    bx = min(max(0.0, bx), max(0.0, W - bw))
    by = min(max(0.0, by), max(0.0, H - bh))
    return [round(bx, 1), round(by, 1), round(min(bw, W), 1), round(min(bh, H), 1)]


def upsample(z, source, rules=RULES):
    return z * rules['out_w'] / float(source[0])


def pick_pose(box, source, max_up, rules=RULES, zmax=2.0):
    """Largest ladder zoom <= zmax whose viewport contains the box and whose upsample <= max_up; centre clamped.
    Returns (z, cx, cy, level). zmax = 1.35 for a lone click (a glance), 2.0 for typing or several clicks (the work)."""
    W, H = source
    bx, by, bw, bh = box
    z = 1.0
    for cand in LADDER:
        if cand <= zmax + 1e-9 and W / cand >= bw - 1e-6 and H / cand >= bh - 1e-6 and upsample(cand, source, rules) <= max_up + 1e-9:
            z = cand
    vw, vh = W / z, H / z
    cx = min(max(bx + bw / 2.0, vw / 2.0), W - vw / 2.0)
    cy = min(max(by + bh / 2.0, vh / 2.0), H - vh / 2.0)
    up = upsample(z, source, rules)
    level = 'fail' if up > rules['fail_upsample'] + 1e-9 else 'warn' if up > rules['warn_upsample'] + 1e-9 else 'ok'
    return z, cx, cy, level


def fits(box, z, cx, cy, source):
    """Does the box lie inside the viewport of pose (z, cx, cy)?"""
    W, H = source
    vw, vh = W / z, H / z
    bx, by, bw, bh = box
    return bx >= cx - vw / 2 - 1e-6 and by >= cy - vh / 2 - 1e-6 and bx + bw <= cx + vw / 2 + 1e-6 and by + bh <= cy + vh / 2 + 1e-6


# ---------------------------------------------------------------- cues
def plan(isls, source, max_up=None, rec_start=0.0, film_t0=0.0, clip_end=None, rules=RULES):
    """Islands -> cues (film time). Returns (cues, islands_out, lint)."""
    max_up = rules['warn_upsample'] if max_up is None else max_up
    R = rules
    shift = film_t0 - rec_start
    out_isl, poses = [], []
    for isl in isls:
        box = target_box(isl, source, R)
        z, cx, cy, level = pick_pose(box, source, max_up, R, zmax=1.35 if isl['n_clicks'] + isl['n_keys'] == 1 else 2.0)
        out_isl.append(dict(isl, box=box, zoom=z, centre=[round(cx, 1), round(cy, 1)], budget=level))
        poses.append((z, cx, cy, box))
    # merge consecutive islands that fit in one viewport and are close in time
    merged = []
    for isl, pose in zip(out_isl, poses):
        if merged:
            prev, ppose = merged[-1]
            if pose[0] > 1.0 and ppose[0] > 1.0 and fits(pose[3], ppose[0], ppose[1], ppose[2], source) and isl['t0'] - prev['t1'] <= R['max_hold']:
                prev['t1'] = isl['t1']
                prev['n_clicks'] += isl['n_clicks']
                prev['n_keys'] += isl['n_keys']
                prev['merged'] = prev.get('merged', 1) + 1
                continue
        merged.append((dict(isl), pose))
    cues, lint = [], []
    cur = (1.0, source[0] / 2.0, source[1] / 2.0)        # current pose, source px
    cur_arrive = None                                   # film time the current pose was reached
    sx, sy = STAGE[0] / source[0], STAGE[1] / source[1]

    def cue(t, dur, z, cx, cy, hold, cause, ease='io'):
        cues.append({'t': round(t, 3), 'dur': round(dur, 3), 'zoom': z, 'cx': round(cx * sx, 1), 'cy': round(cy * sy, 1),
                     'src': [round(cx, 1), round(cy, 1)], 'hold': round(hold, 3), 'cause': cause, 'ease': ease,
                     'upsample': round(upsample(z, source, R), 3)})

    for i, (isl, (z, cx, cy, box)) in enumerate(merged):
        ta, tb = isl['t0'] + shift, isl['t1'] + shift
        what = ' + '.join(s for s in ['%d click%s' % (isl['n_clicks'], '' if isl['n_clicks'] == 1 else 's') if isl['n_clicks'] else '',
                                      '%d key%s' % (isl['n_keys'], '' if isl['n_keys'] == 1 else 's') if isl['n_keys'] else ''] if s)
        where = 'around (%d, %d)' % (cx, cy)
        if z <= 1.0:
            cause = '%s %s — target box %dx%d too wide for any ladder zoom under the budget, stay wide' % (what, where, box[2], box[3])
            if cur[0] > 1.0:
                t_pull = max(ta - R['lead'], (cur_arrive or -1e9) + R['dwell'])
                cue(t_pull, R['pull'], 1.0, source[0] / 2.0, source[1] / 2.0, 0.0, 'pull back: ' + cause)
                cur, cur_arrive = (1.0, source[0] / 2.0, source[1] / 2.0), t_pull + R['pull']
            else:
                lint.append({'level': 'INFO', 'at': round(ta, 2), 'rule': 'stay wide', 'detail': cause})
            continue
        t_push = ta - R['lead']
        hold_end = max(tb + R['tail'], t_push + R['push'] + R['min_hold'])
        cause = '%s %s' % (what, where)
        if cur[0] > 1.0:
            # coming from another pose: room for pull + dwell + push?  else one direct move
            gap = t_push - (cur_arrive + R['dwell'])
            if gap >= R['pull'] + R['dwell']:
                t_pull = cur_arrive + max(R['dwell'], R['min_hold'] - 0.0)
                t_pull = max(t_pull, cur_arrive + R['dwell'])
                cue(t_pull, R['pull'], 1.0, source[0] / 2.0, source[1] / 2.0, t_push - (t_pull + R['pull']), 'pull back before the next island')
                cur, cur_arrive = (1.0, source[0] / 2.0, source[1] / 2.0), t_pull + R['pull']
                cue(t_push, R['push'], z, cx, cy, hold_end - (t_push + R['push']), cause)
            else:
                t_move = max(t_push, cur_arrive + R['dwell'])
                cue(t_move, R['push'], z, cx, cy, max(0.0, hold_end - (t_move + R['push'])), 'move on: ' + cause)
                t_push = t_move
        else:
            if cur_arrive is not None and t_push < cur_arrive + R['dwell']:
                t_push = cur_arrive + R['dwell']
            cue(t_push, R['push'], z, cx, cy, hold_end - (t_push + R['push']), cause)
        cur, cur_arrive = (z, cx, cy), t_push + R['push']
        # a long quiet hold pulls back on its own ("nothing static for long")
        nxt = merged[i + 1][0]['t0'] + shift - R['lead'] if i + 1 < len(merged) else None
        if nxt is None or nxt - hold_end > R['pull'] + R['dwell']:
            if nxt is None and clip_end is not None and clip_end + shift - hold_end < R['end_slack']:
                continue
            t_pull = min(hold_end, cur_arrive + R['max_hold'])
            t_pull = max(t_pull, cur_arrive + R['dwell'])
            cue(t_pull, R['pull'], 1.0, source[0] / 2.0, source[1] / 2.0, 0.0, 'pull back after the island' if t_pull >= hold_end - 1e-6 else 'pull back: hold would exceed %.0f s' % R['max_hold'])
            cur, cur_arrive = (1.0, source[0] / 2.0, source[1] / 2.0), t_pull + R['pull']
    # ---- lint the proposal against the camera rules
    for a, b in zip(cues, cues[1:]):
        gap = b['t'] - (a['t'] + a['dur'])
        if gap < R['dwell'] - 1e-6:
            lint.append({'level': 'WARN', 'at': b['t'], 'rule': 'no dwell', 'detail': '%.2f s between moves (>= %.1f s)' % (gap, R['dwell'])})
    for c in cues:
        if c['dur'] < R['move_min'] - 1e-6 or c['dur'] > R['move_max'] + 1e-6:
            lint.append({'level': 'FAIL', 'at': c['t'], 'rule': 'move duration', 'detail': '%.2f s (0.8-2.5 s)' % c['dur']})
        if c['upsample'] > R['fail_upsample'] + 1e-9:
            lint.append({'level': 'FAIL', 'at': c['t'], 'rule': 'zoom budget', 'detail': 'upsample %.2f > %.1f' % (c['upsample'], R['fail_upsample'])})
        elif c['upsample'] > R['warn_upsample'] + 1e-9:
            lint.append({'level': 'WARN', 'at': c['t'], 'rule': 'zoom budget', 'detail': 'upsample %.2f > %.1f (soft text on a booth wall)' % (c['upsample'], R['warn_upsample'])})
        if c['zoom'] > 1.0 and c['hold'] + 1e-6 < R['min_hold'] and not c['cause'].startswith('move on'):
            lint.append({'level': 'WARN', 'at': c['t'], 'rule': 'short hold', 'detail': '%.2f s (>= %.1f s)' % (c['hold'], R['min_hold'])})
    out_islands = [dict(isl, box=isl['box'], zoom=pose[0]) for isl, pose in merged]
    return cues, out_islands, lint


def moves_js(cues):
    return '\n'.join("{ t0: %.2f, dur: %.1f, s: %.2f, c: [%d, %d], ease: '%s', abs: true },   // %s" %
                     (c['t'], c['dur'], c['zoom'], round(c['cx']), round(c['cy']), c['ease'], c['cause']) for c in cues)


def storyboard_md(cues, source):
    lines = ['<!-- camera_from_events.py proposal: paste each camera line into the beat it falls in, then edit or delete. -->', '']
    for c in cues:
        verb = 'PULL' if c['zoom'] <= 1.0 else 'PUSH'
        if c['cause'].startswith('move on'):
            verb = 'PAN/ZOOM'
        tgt = 'to the full screen' if c['zoom'] <= 1.0 else 'onto (%d, %d) of %dx%d' % (c['src'][0], c['src'][1], source[0], source[1])
        hold = ', hold %.1f s' % c['hold'] if c['hold'] > 0 else ''
        lines.append('- camera: %s %.2fx %s at %.2f s, %.1f s sine-in-out%s — auto: %s' % (verb, c['zoom'], tgt, c['t'], c['dur'], hold, c['cause']))
    return '\n'.join(lines) + '\n'


def run(events, source, max_up=None, rec_start=0.0, film_t0=0.0, clip_end=None):
    pts = attention_points(events)
    isls = islands(pts)
    cues, isl_out, lint = plan(isls, source, max_up, rec_start, film_t0, clip_end)
    peak = max([c['upsample'] for c in cues] or [upsample(1.0, source)])
    return {'tool': 'camera_from_events', 'version': VERSION, 'source': list(source), 'stage': [1280, 720], 'ladder': list(LADDER),
            'rec_start': rec_start, 'film_t0': film_t0, 'points': len(pts), 'islands': isl_out, 'cues': cues, 'moves_js': moves_js(cues),
            'lint': lint, 'budget': {'peak_upsample': round(peak, 3), 'level': 'fail' if peak > RULES['fail_upsample'] else 'warn' if peak > RULES['warn_upsample'] else 'ok'}}


# ---------------------------------------------------------------- selftest
def synthetic_events():
    """A fictional take: click a field (1.0 s), type 12 keys there (1.3-3.4 s), click Send 180 px right (4.0 s);
    a far click top-left at 12.0 s; two quick clicks bottom-right at 20.0 / 20.5 s; nothing else until 26 s."""
    ev = []
    for k in range(0, 260):
        t = k / 10.0
        ev.append({'t': round(t, 3), 'x': 400 + 2 * k, 'y': 300 + k, 'type': 'move'})
    ev += [{'t': 1.0, 'x': 900, 'y': 640, 'type': 'down', 'button': 'left'}, {'t': 1.08, 'x': 900, 'y': 640, 'type': 'up', 'button': 'left'}]
    for i in range(12):
        ev.append({'t': round(1.3 + i * 0.18, 3), 'x': 1300, 'y': 900, 'type': 'key', 'key': 'abcdefghijkl'[i], 'mods': [], 'char': 'abcdefghijkl'[i], 'vk': 65 + i})
    ev += [{'t': 4.0, 'x': 1080, 'y': 650, 'type': 'down', 'button': 'left'}, {'t': 4.08, 'x': 1080, 'y': 650, 'type': 'up', 'button': 'left'},
           {'t': 12.0, 'x': 180, 'y': 140, 'type': 'down', 'button': 'left'}, {'t': 12.08, 'x': 180, 'y': 140, 'type': 'up', 'button': 'left'},
           {'t': 20.0, 'x': 1700, 'y': 950, 'type': 'down', 'button': 'left'}, {'t': 20.08, 'x': 1700, 'y': 950, 'type': 'up', 'button': 'left'},
           {'t': 20.5, 'x': 1640, 'y': 980, 'type': 'down', 'button': 'left'}, {'t': 20.58, 'x': 1640, 'y': 980, 'type': 'up', 'button': 'left'}]
    ev.sort(key=lambda e: (e['t'], e['type']))
    return ev


def selftest():
    import time
    t0 = time.time()
    ev = synthetic_events()
    r1 = run(ev, (1920, 1080), clip_end=26.0)
    r2 = run(ev, (1920, 1080), clip_end=26.0)
    checks = []

    def ok(name, cond, detail=''):
        checks.append({'name': name, 'ok': bool(cond), 'detail': detail})
    isl = r1['islands']
    ok('three islands (typing+send, far click, double click)', len(isl) == 3, '%d: %s' % (len(isl), [(i['t0'], i['t1'], i['n_clicks'], i['n_keys']) for i in isl]))
    ok('keys sit at the clicked field', isl and isl[0]['n_keys'] == 12 and isl[0]['box'][0] <= 900 <= isl[0]['box'][0] + isl[0]['box'][2])
    cues = r1['cues']
    ok('every zoom from the ladder', all(c['zoom'] in LADDER for c in cues), str([c['zoom'] for c in cues]))
    ok('budget never above warn by default', all(c['upsample'] <= 1.6 + 1e-9 for c in cues), str(r1['budget']))
    ok('pushes hold >= 2 s', all(c['hold'] >= 2.0 - 1e-6 for c in cues if c['zoom'] > 1 and not c['cause'].startswith('move on')), str([(c['zoom'], c['hold']) for c in cues]))
    ok('>= 1 s dwell between moves', all(b['t'] - (a['t'] + a['dur']) >= 1.0 - 1e-6 for a, b in zip(cues, cues[1:])), str([round(b['t'] - a['t'] - a['dur'], 2) for a, b in zip(cues, cues[1:])]))
    ok('first push lands just after the first click', cues and abs(cues[0]['t'] - (1.0 - 0.8)) < 1e-6 and cues[0]['zoom'] > 1)
    ok('pull back between distant islands', any(c['zoom'] == 1.0 for c in cues[1:]))
    ok('stage coordinates inside 1280x720', all(0 <= c['cx'] <= 1280 and 0 <= c['cy'] <= 720 for c in cues))
    ok('no lint FAIL', not any(l['level'] == 'FAIL' for l in r1['lint']), str(r1['lint']))
    ok('deterministic twice', json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    r3 = run(ev, (1920, 1080), max_up=2.0, clip_end=26.0)
    ok('--max-upsample 2.0 reaches 2.0 and lints WARN', any(c['zoom'] == 2.0 for c in r3['cues']) and any(l['rule'] == 'zoom budget' for l in r3['lint']), str([c['zoom'] for c in r3['cues']]))
    r4 = run(ev, (2426, 1282), clip_end=26.0)
    ok('a 2426-px tape may use the 2.0 rung (upsample 1.58)', any(c['zoom'] == 2.0 for c in r4['cues']) and r4['budget']['level'] == 'ok', str(r4['budget']))
    r5 = run(ev, (1920, 1080), rec_start=10.0, film_t0=30.0, clip_end=26.0)
    ok('film-time shift', abs(r5['cues'][0]['t'] - (r1['cues'][0]['t'] + 20.0)) < 1e-6)
    md = storyboard_md(cues, (1920, 1080))
    ok('storyboard fragment has one camera line per cue', md.count('- camera:') == len(cues))
    passed = all(c['ok'] for c in checks)
    print(json.dumps({'PASS': passed, 'checks': checks, 'cues': cues, 'moves_js': r1['moves_js'], 'md': md, 'seconds': round(time.time() - t0, 2)}, indent=1))
    return 0 if passed else 1


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description='Propose camera cues (shots.js moves + storyboard lines) from click/typing events. JSON in / JSON out.')
    ap.add_argument('events', nargs='?', help='events.jsonl from record_events.py (aligned) or cursor_track.py')
    ap.add_argument('--out', help='camera_auto.json (default beside the events)')
    ap.add_argument('--md', help='storyboard fragment path (default: <out>.md)')
    ap.add_argument('--source', help='WxH of the recording (default: the events meta "source", else 1920x1080)')
    ap.add_argument('--max-upsample', type=float, default=RULES['warn_upsample'], help='largest allowed upsample (default 1.6 = warn line; 2.0 = fail line)')
    ap.add_argument('--rec-start', type=float, default=0.0, help='recording time shown at --film-t0')
    ap.add_argument('--film-t0', type=float, default=0.0, help='film time at which recording time --rec-start is shown')
    ap.add_argument('--clip-end', type=float, help='recording time where the shot ends (suppresses a pull-back in the last 1.5 s)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.events:
        ap.print_help()
        return 2
    if not os.path.exists(a.events):
        print('no such file: ' + a.events, file=sys.stderr)
        return 2
    meta, ev = read_events(a.events)
    if a.source:
        source = tuple(int(v) for v in a.source.lower().split('x'))
    else:
        source = tuple(meta.get('source') or meta.get('screen') or (1920, 1080))
    rep = run(ev, source, a.max_upsample, a.rec_start, a.film_t0, a.clip_end)
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.events)), 'camera_auto.json')
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(rep, f, indent=1, sort_keys=True)
    md = a.md or os.path.splitext(out)[0] + '.md'
    with open(md, 'w', encoding='utf-8') as f:
        f.write(storyboard_md(rep['cues'], source))
    findings = [l for l in rep['lint'] if l['level'] in ('WARN', 'FAIL')]
    print(json.dumps({'out': out, 'md': md, 'points': rep['points'], 'islands': len(rep['islands']), 'cues': len(rep['cues']),
                      'budget': rep['budget'], 'findings': findings}, indent=1))
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
