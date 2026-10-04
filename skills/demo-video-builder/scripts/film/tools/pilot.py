# -*- coding: utf-8 -*-
"""pilot.py — judge two variants as a CUT, not as a frame: the same shots from scene A and scene B, stacked on one clock.

    python tools/pilot.py A B --shots 3-6 [--project DIR] [--out out/pilot.mp4] [--workers 2]
        A, B = scene files (scenes/film.html, scenes/film_b.html) or the same scene with a query (scenes/film.html?skin=cobalt)
    python tools/pilot.py --from-renders a.mp4 b.mp4 --windows "13.6-21.8,21.8-26.5" [--out out/pilot.mp4]
    python tools/pilot.py --selftest

Why a pilot. A look, a skin or a choreography is never judged on a still: what matters is how three or four shots cut
together — the rhythm, the seam, the weight of the type against the footage. `pilot.py` renders the SAME shots (by index
from out/timeline.json shots[], or explicit windows) from two scene variants through render_frames.js, cuts each set into
a sequence, and stacks the two sequences top / bottom (A above, B below) with one shared clock burned in — the film time of
the frame, so a note like "B wins at 15.2" points at the same instant in both. Output: out/pilot.mp4 (1920x2160 → scaled
to 960x1080 for a phone) and out/pilot_sheet.jpg (a frame per second, A row over B row). Price the pipeline, not the clip:
both variants pay the same render and are read in the same minute.

Chrome is needed to render A and B; `--from-renders` takes two existing films and does the cut + stack + sheet with ffmpeg
only (the selftest uses that path on synthetic clips).
"""
import argparse, json, os, re, subprocess, sys, tempfile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
FILM_DIR = os.path.dirname(HERE)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('%s failed: %s' % (os.path.basename(cmd[0]), (r.stderr or r.stdout)[-600:]))
    return r


def _fontfile():
    """ffmpeg's drawtext needs a font it can find without fontconfig (Windows builds have none): the first common face wins."""
    for f in ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/System/Library/Fonts/Helvetica.ttc'):
        if os.path.exists(f):
            return f.replace(':', '\\:')
    return None


def _drawtext(text, x, y, size):
    """a drawtext filter stage, or '' when no font file is available (the clock is then left to the sheet labels)."""
    ff = _fontfile()
    if not ff:
        return ''
    return ",drawtext=fontfile='%s':text='%s':x=%s:y=%s:fontsize=%d:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=8" % (ff, text, x, y, size)


def parse_shots(spec, shots):
    """'3-6' | '3,5,6' (1-based indices into timeline shots[]) → [(t0, t1, label)]."""
    idx = []
    for part in str(spec).split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1); idx += list(range(int(a), int(b) + 1))
        elif part:
            idx.append(int(part))
    out = []
    for i in idx:
        if 1 <= i <= len(shots) and shots[i - 1].get('t1') is not None:
            s = shots[i - 1]; out.append((float(s['t0']), float(s['t1']), s.get('clip') or 'shot %d' % i))
    return out


def parse_windows(spec):
    out = []
    for part in str(spec).split(','):
        m = re.match(r'\s*([\d.]+)\s*-\s*([\d.]+)\s*$', part)
        if m:
            out.append((float(m.group(1)), float(m.group(2)), '%s-%s' % (m.group(1), m.group(2))))
    return out


def render_variant(scene, total, fps, workers, project, out_mp4):
    """render_frames.js over the whole clock (the windows are cut from it afterwards, so both variants share frame times)."""
    rf = os.path.join(project, 'render_frames.js')
    if not os.path.exists(rf):
        rf = os.path.join(FILM_DIR, 'render_frames.js')
    r = subprocess.run(['node', rf, scene, out_mp4, '%.3f' % total, str(fps), '90', str(workers)], cwd=project, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('render of %s failed: %s' % (scene, (r.stderr or r.stdout)[-500:]))
    return out_mp4


def cut_sequence(src, windows, out_mp4, fps=30):
    """the windows of one render, in order, as a sequence with the film clock burned in (top-left) — each window is one trim."""
    parts = []
    for i, (a, b, lab) in enumerate(windows):
        clock = "%%{eif\\:%.3f+t\\:d\\:3}.%%{eif\\:mod((%.3f+t)*100\\,100)\\:d\\:2}  %s" % (a, a, lab.replace("'", '').replace(':', ' ').replace(',', ' '))
        parts.append("[0:v]trim=start=%.4f:end=%.4f,setpts=PTS-STARTPTS%s[v%d]" % (a, b, _drawtext(clock, 24, 18, 34), i))
    graph = ';'.join(parts) + ';' + ''.join('[v%d]' % i for i in range(len(windows))) + 'concat=n=%d:v=1:a=0[out]' % len(windows)
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-filter_complex', graph, '-map', '[out]', '-r', str(fps), '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', out_mp4])
    return out_mp4


def stack(a_mp4, b_mp4, out_mp4, labels=('A', 'B')):
    """A over B at half scale (960x540 each → 960x1080), each half labelled."""
    graph = ("[0:v]scale=960:540%s[a];[1:v]scale=960:540%s[b];[a][b]vstack=inputs=2[out]" % (_drawtext(labels[0], 'w-tw-20', 14, 30), _drawtext(labels[1], 'w-tw-20', 14, 30)))
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', a_mp4, '-i', b_mp4, '-filter_complex', graph, '-map', '[out]', '-shortest', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out_mp4])
    return out_mp4


def sheet(pilot_mp4, out_jpg, every=1.0):
    """a frame every `every` seconds of the stacked pilot, tiled left to right (A row over B row by construction)."""
    from PIL import Image
    d = tempfile.mkdtemp(prefix='pilot_sheet_')
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', pilot_mp4, '-vf', 'fps=%g,scale=320:360' % (1.0 / every), os.path.join(d, 'f_%03d.jpg')])
    files = sorted(f for f in os.listdir(d) if f.endswith('.jpg'))
    if not files:
        return None
    cols = min(8, len(files)); rows = (len(files) + cols - 1) // cols
    im = Image.new('RGB', (cols * 320, rows * 360), (5, 22, 28))
    for i, f in enumerate(files):
        with Image.open(os.path.join(d, f)) as tile:
            im.paste(tile.convert('RGB'), ((i % cols) * 320, (i // cols) * 360))
    im.save(out_jpg, quality=86)
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    return out_jpg


def frames_of(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', path], capture_output=True, text=True)
    return int(r.stdout.strip() or 0)


def pilot(a_mp4, b_mp4, windows, out_mp4, fps=30, labels=('A', 'B')):
    d = tempfile.mkdtemp(prefix='pilot_')
    sa, sb = cut_sequence(a_mp4, windows, os.path.join(d, 'a.mp4'), fps), cut_sequence(b_mp4, windows, os.path.join(d, 'b.mp4'), fps)
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    stack(sa, sb, out_mp4, labels)
    js = sheet(out_mp4, os.path.splitext(out_mp4)[0] + '_sheet.jpg')
    rec = {'pilot': out_mp4, 'sheet': js, 'windows': [{'t0': a, 't1': b, 'label': l} for a, b, l in windows], 'frames': frames_of(out_mp4),
           'length_s': round(sum(b - a for a, b, _ in windows), 3), 'a': a_mp4, 'b': b_mp4}
    json.dump(rec, open(os.path.splitext(out_mp4)[0] + '.json', 'w', encoding='utf-8'), indent=1)
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    return rec


# ---------------------------------------------------------------- selftest
def selftest():
    import shutil
    d = tempfile.mkdtemp(prefix='pilot_selftest_')
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)
    a, b = os.path.join(d, 'a.mp4'), os.path.join(d, 'b.mp4')
    for p, col in ((a, '0x204A56'), (b, '0x8A2E2E')):
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', "color=c=%s:s=640x360:r=30,drawbox=x='40+t*60':y=100:w=60:h=160:c=white:t=fill" % col, '-t', '8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', p])
    shots = [{'clip': 'open', 't0': 0.0, 't1': 2.0}, {'clip': 'nb', 't0': 2.0, 't1': 4.0}, {'clip': 'q', 't0': 4.0, 't1': 5.5}, {'clip': 'ans', 't0': 5.5, 't1': 8.0}]
    W = parse_shots('2-3', shots)
    t(W == [(2.0, 4.0, 'nb'), (4.0, 5.5, 'q')] and parse_shots('1,4', shots)[1][2] == 'ans' and parse_windows('1.5-3,4-4.5') == [(1.5, 3.0, '1.5-3'), (4.0, 4.5, '4-4.5')], 'shot ranges and explicit windows parse')
    out = os.path.join(d, 'out', 'pilot.mp4')
    rec = pilot(a, b, W, out)
    t(rec['frames'] == 105 and abs(rec['length_s'] - 3.5) < 1e-6, 'pilot: two windows (2 + 1.5 s) cut and stacked → %d frames' % rec['frames'])
    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', out], capture_output=True, text=True).stdout.strip()
    t(pr == '960,1080', 'stacked A over B at 960x1080 (%s)' % pr)
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '1.0', '-i', out, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    fr = np.frombuffer(raw, dtype=np.uint8).reshape(1080, 960, 3)
    top, bot = fr[300, 900].astype(int), fr[840, 900].astype(int)
    t(top[2] > top[0] and bot[0] > bot[2], 'A (cool) on top, B (warm) below at the same clock')
    t(rec['sheet'] and os.path.exists(rec['sheet']) and os.path.exists(os.path.splitext(out)[0] + '.json'), 'pilot_sheet.jpg and pilot.json written')
    shutil.rmtree(d, ignore_errors=True)
    print('pilot selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog='pilot.py', description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('a', nargs='?'); ap.add_argument('b', nargs='?')
    ap.add_argument('--shots', help='1-based shot indices from out/timeline.json, e.g. 3-6 or 3,5')
    ap.add_argument('--windows', help='explicit windows "t0-t1,t0-t1"')
    ap.add_argument('--from-renders', nargs=2, metavar=('A_MP4', 'B_MP4'))
    ap.add_argument('--project', default=os.getcwd()); ap.add_argument('--out'); ap.add_argument('--workers', type=int, default=2); ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--labels', default='A,B')
    ns = ap.parse_args(argv)
    project = os.path.abspath(ns.project)
    tl_p = os.path.join(project, 'out', 'timeline.json')
    tl = json.load(open(tl_p, encoding='utf-8')) if os.path.exists(tl_p) else {}
    windows = parse_windows(ns.windows) if ns.windows else (parse_shots(ns.shots, tl.get('shots', [])) if ns.shots else [])
    if not windows:
        print('nothing to pilot: give --shots (needs out/timeline.json) or --windows', file=sys.stderr); return 2
    out = ns.out or os.path.join(project, 'out', 'pilot.mp4')
    labels = tuple((ns.labels.split(',') + ['A', 'B'])[:2])
    if ns.from_renders:
        a_mp4, b_mp4 = ns.from_renders
    else:
        if not (ns.a and ns.b):
            print('give two scene variants A B (or --from-renders)', file=sys.stderr); return 2
        total = max(b for _, b, _ in windows) + 0.5
        d = os.path.join(project, 'out', 'pilot_renders'); os.makedirs(d, exist_ok=True)
        print('rendering A (%s) and B (%s) to %.1f s …' % (ns.a, ns.b, total))
        a_mp4 = render_variant(ns.a, total, ns.fps, ns.workers, project, os.path.join(d, 'a.mp4'))
        b_mp4 = render_variant(ns.b, total, ns.fps, ns.workers, project, os.path.join(d, 'b.mp4'))
    rec = pilot(a_mp4, b_mp4, windows, out, ns.fps, labels)
    print('pilot  %s  (%d frames, %.1f s of %d windows)  sheet %s' % (os.path.relpath(rec['pilot'], project), rec['frames'], rec['length_s'], len(windows), os.path.relpath(rec['sheet'], project) if rec['sheet'] else '—'))
    print('judge it as a cut: which variant holds the rhythm, which seam reads, which type sits on the footage — then pick one and write why in STORYBOARD.md ## Decisions')
    return 0


if __name__ == '__main__':
    sys.exit(main())
