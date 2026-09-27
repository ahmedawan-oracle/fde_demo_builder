# -*- coding: utf-8 -*-
"""qa_film.py — adversarial gates on a finished v3 film. Every gate prints PASS/FAIL; exit 1 if any FAIL.

    node export_timeline.js scenes/timing_film_data.js scenes/shots.js     # writes out/timeline.json
    python qa_film.py                                                      # reads qa.json + film.json

  1  container        1920x1080, 30 fps CFR
  2  duration         film length = narration clock (+ tail)
  3  open frame       not black once the head fade is done
  4  black frames     no black / near-black frames mid-film
  5  cuts land        the picture changes across every scripted cut far more than just before it (relative test:
                      white-to-white UI cuts change 2-4 % of pixels, a push in progress ~7 %, a still ~0 %)
  6  blank after cut  the frame 0.4 s after a cut is not a flat, inkless plate
  7  no long freeze   never frozen longer than max_hold (measured at 640x360 so slow pushes register)
  8  loudness         -17..-15 LUFS integrated, true peak <= -1 dBTP
  9  required lines   phrases that must be in the narration (honesty line, product messaging)
 10  no over-claims   banned phrases absent from narration and rendered scene text (comments stripped)
 11  hygiene          no identifier pattern (emails, tokens, internal hosts, customer names) in authored text
 12  claims traced    every figure/claim the narration speaks is listed in claims.json with its on-screen source
 13  captions         SRT exists, ordered, ends inside the film
 14  CREDIT           the mandatory "Crafted with FDE Demo Builder · by Ahmed Awan" line is on the end screen
"""
import array, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
Q = json.load(open(os.path.join(HERE, 'qa.json'), encoding='utf-8'))
C = json.load(open(os.path.join(HERE, 'film.json'), encoding='utf-8'))
NAME = C.get('name', 'film')
FILM = os.path.join(HERE, C.get('output', 'out/%s.mp4' % NAME))
SRT = os.path.splitext(FILM)[0] + '.srt'
TL = json.load(open(os.path.join(HERE, 'out', 'timeline.json'), encoding='utf-8'))
TOTAL, FPS, fails = float(TL['total']), 30, []
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def gate(name, ok, detail=''):
    print('  %-18s %s  %s' % (name, 'PASS' if ok else 'FAIL', detail))
    if not ok:
        fails.append(name)


def frame(t, w=160, h=90):
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', FILM, '-frames:v', '1',
                        '-vf', 'scale=%d:%d,format=gray' % (w, h), '-f', 'rawvideo', '-'], capture_output=True)
    seg = array.array('B', r.stdout)
    m = sum(seg) / max(1, len(seg))
    sd = (sum((x - m) ** 2 for x in seg) / max(1, len(seg))) ** 0.5
    return m, sd, min(seg or [0]), seg


print('QA  ' + os.path.relpath(FILM, HERE))
if not os.path.exists(FILM):
    raise SystemExit('missing ' + FILM)
info = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                       'stream=width,height,r_frame_rate,avg_frame_rate:format=duration', '-of', 'default=nw=1', FILM],
                      capture_output=True, text=True).stdout
d = dict(l.split('=', 1) for l in info.splitlines() if '=' in l)
dur = float(d.get('duration', 0))
gate('container', d.get('width') == '1920' and d.get('height') == '1080' and d.get('r_frame_rate') == '30/1'
     and d.get('r_frame_rate') == d.get('avg_frame_rate'), '%sx%s %s' % (d.get('width'), d.get('height'), d.get('r_frame_rate')))
gate('duration', TOTAL - 0.1 <= dur <= TOTAL + 2.0, 'film %.2f s vs narration %.2f s' % (dur, TOTAL))

m, sd = frame(0.45)[:2]
gate('open frame', m > 12 or sd > 6, 'mean %.1f std %.1f' % (m, sd))
bad, t = [], 0.6
while t < dur - 0.6:
    m, sd = frame(t)[:2]
    if m < 4 and sd < 2:
        bad.append(round(t, 2))
    t += 0.5
gate('black frames', not bad, 'offenders %s' % (bad[:6] or 'none'))

cuts = [c for c in TL['cuts'] if 1.0 < c < dur - 1.0]
changed = lambda a, b: 100.0 * sum(1 for x, y in zip(a, b) if abs(x - y) > 24) / len(a)
weak = []
for c in cuts:
    p0, p1, po = (frame(x, 640, 360)[3] for x in (c - 6.5 / FPS, c - 3.5 / FPS, c + 1.5 / FPS))
    across, before = changed(p1, po), changed(p0, p1)
    if not (across >= 1.0 and across >= 3.0 * before + 0.2):
        weak.append((round(c, 2), round(across, 1), round(before, 1)))
gate('cuts land', not weak, 'weak (t, across%%, before%%) %s' % weak[:5] if weak else 'all %d cuts read' % len(cuts))
blank = []
for c in cuts:
    m, sd, mn = frame(c + 0.4, 640, 360)[:3]
    if sd < 6 and mn > 180 and (m > 235 or m < 20):
        blank.append(round(c, 2))
gate('blank after cut', not blank, 'offenders %s' % (blank or 'none'))

hold, run, t = float(Q.get('max_hold', 5.0)), 0.0, 1.0
prev, frozen = frame(t, 640, 360)[3], []
while t < dur - 1.0:
    t += 0.5
    cur = frame(t, 640, 360)[3]
    run = run + 0.5 if sum(abs(x - y) for x, y in zip(prev, cur)) / len(cur) < 0.25 else 0.0
    if run >= hold:
        frozen.append(round(t, 1))
    prev = cur
gate('no long freeze', not frozen, 'frozen at %s' % frozen[:5] if frozen else 'never > %.0f s' % hold)

r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', FILM, '-af', 'loudnorm=I=-16:TP=-1:print_format=json', '-f', 'null', '-'],
                   capture_output=True, text=True)
st = json.loads(re.findall(r'\{[^{}]*"input_i"[\s\S]*?\}', r.stderr)[-1])
I, TP = float(st['input_i']), float(st['input_tp'])
gate('loudness', -17.0 <= I <= -15.0 and TP <= -1.0, 'I %.2f LUFS  TP %.2f dBTP' % (I, TP))

sys.path.insert(0, HERE)
import vo_script
script = ' '.join(' '.join(p['text'].split()) for p in vo_script.SCENES[NAME]['phases'])
strip = lambda s: re.sub(r'(?m)//[^\n]*', ' ', re.sub(r'/\*.*?\*/|<!--.*?-->', ' ', s, flags=re.S))
authored = ''.join(open(os.path.join(HERE, f), encoding='utf-8').read() for f in Q.get('authored', ['scenes/film.html', 'scenes/shots.js']))
missing = [p for p in Q.get('required_phrases', []) if p.lower() not in script.lower()]
gate('required lines', not missing, 'missing %s' % missing if missing else '%d present' % len(Q.get('required_phrases', [])))
said = (script + ' ' + strip(authored)).lower()
hit = [p for p in Q.get('banned_phrases', []) if p.lower() in said]
gate('no over-claims', not hit, 'found %s' % hit if hit else 'clean')
found = {k: sorted(set(re.findall(p, script + authored, re.I)))[:3] for k, p in Q.get('hygiene_patterns', {}).items()
         if re.search(p, script + authored, re.I)}
gate('hygiene', not found, str(found) if found else 'clean')

cp = os.path.join(HERE, Q.get('claims', 'claims.json'))
if os.path.exists(cp):
    CL = json.load(open(cp, encoding='utf-8'))['claims']
    flat = ' '.join(script.split())
    un = [c['phrase'] for c in CL if c['phrase'] not in flat or not c.get('source')]
    gate('claims traced', not un, 'unbacked %s' % un if un else 'all %d claims traced to the screen' % len(CL))
else:
    gate('claims traced', False, 'claims.json missing')

if os.path.exists(SRT):
    ts = re.findall(r'(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)', open(SRT, encoding='utf-8').read())
    secs = [(int(a) * 3600 + int(b) * 60 + int(c) + int(e) / 1000, int(f) * 3600 + int(g) * 60 + int(h) + int(i) / 1000)
            for a, b, c, e, f, g, h, i in ts]
    ok = bool(secs) and all(secs[k][1] <= secs[k + 1][0] + 0.001 for k in range(len(secs) - 1)) and secs[-1][1] <= dur + 0.05
    gate('captions', ok, '%d cues' % len(secs))
else:
    gate('captions', False, 'missing ' + SRT)

import credit as CR
gate('CREDIT', CR.check(FILM, verbose=False), '"%s" on the end screen (mandatory)' % CR.CREDIT_TEXT)

print('\n%s  (%d failed)' % ('ALL GATES PASS' if not fails else 'FAILED: ' + ', '.join(fails), len(fails)))
sys.exit(1 if fails else 0)
