# -*- coding: utf-8 -*-
"""cues_check.py — after the mux, prove every sound landed on its cue: locate each SFX onset in the master and fail past 1 ms.

    python audio/cues_check.py --cues out/cues_film.json --master out/master_film.wav [--sfx-dir audio/sfx] [--tol-ms 1] [--json]
    python audio/cues_check.py --cues out/cues_film.json --film out/Acme_Film.mp4           (decodes the film's audio)
    python audio/cues_check.py --selftest

The placement (audio/sfx_place.py) is sample-exact by construction; the mix, the limiter and the mux are where a cue can
drift — a resampler that pads, a concat that rounds, an encoder that trims a priming frame. This check reads the finished
audio, takes each placed SFX file (out/cues_<name>.json: start, file) and cross-correlates it with the master inside a
±50 ms window around the planned start. The lag of the correlation peak is the measured offset; anything beyond --tol-ms
(1 ms = 48 samples at 48 kHz) FAILS with the cue id, the planned and the measured start. Two cues overlapping within 80 ms
are placement's business (sfx_place drops the lower one); a riser is a swell and is measured on its landing (its file end).

qa_film.py plug-in (gates/sfx_gate.py imports this as `cue sync` when out/cues_<name>.json exists).
numpy + ffmpeg (decode).
"""
import argparse, json, os, subprocess, sys

import numpy as np

SR = 48000
WINDOW_S, TOL_MS = 0.05, 1.0


def decode(path, sr=SR):
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def measure(master, sfx, start_s, window_s=WINDOW_S, sr=SR):
    """offset of the sfx inside master relative to start_s, in seconds (+ = late), and the peak correlation (0..1)."""
    n = len(sfx)
    if n < 8:
        return None, 0.0
    a = int(round((start_s - window_s) * sr)); b = int(round((start_s + window_s) * sr)) + n
    a0 = max(0, a); seg = master[a0:min(len(master), b)]
    if len(seg) < n:
        return None, 0.0
    # first difference = a one-pole high-pass: the bed and the voice live below ~1 kHz, a transient's attack does not — so the
    # correlation reads the onset, not whatever hums under it
    seg = np.diff(seg.astype(np.float64), prepend=seg[0]); sfx = np.diff(sfx.astype(np.float64), prepend=sfx[0])
    s = sfx - sfx.mean(); s = s / (np.sqrt((s * s).sum()) or 1.0)
    # normalised cross-correlation over every lag in the window (FFT)
    L = len(seg) - n + 1
    size = 1 << int(np.ceil(np.log2(len(seg) + n)))
    corr = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(s, size)), size)[:L]
    # local energy of the master under each lag so a loud bed does not win
    csum = np.concatenate([[0.0], np.cumsum(seg.astype(np.float64) ** 2)])
    energy = np.sqrt(np.maximum(csum[n:n + L] - csum[:L], 1e-12))
    ncc = corr / energy
    k = int(np.argmax(ncc))
    prominence = float(ncc[k] / (np.median(np.abs(ncc)) + 1e-9))
    # parabolic sub-sample refinement
    if 0 < k < L - 1:
        y0, y1, y2 = ncc[k - 1], ncc[k], ncc[k + 1]
        d = y0 - 2 * y1 + y2
        k_ref = k + (0.5 * (y0 - y2) / d if abs(d) > 1e-12 else 0.0)
    else:
        k_ref = float(k)
    measured_start = (a0 + k_ref) / sr
    return measured_start - start_s, float(ncc[k]) if prominence >= 4.0 else 0.0


def check(cues_doc, master, sfx_dir, tol_ms=TOL_MS, sr=SR):
    rows, bad = [], []
    for c in cues_doc.get('cues', []):
        f = c.get('file')
        if not f:
            continue
        p = f if os.path.isabs(f) else os.path.join(sfx_dir, os.path.basename(f))
        if not os.path.exists(p):
            rows.append({'id': c.get('id'), 'kind': c.get('kind'), 'planned': c.get('start'), 'error': 'file missing %s' % p}); bad.append('%s: file missing' % c.get('id')); continue
        sfx = decode(p, sr)
        g = float(c.get('gain_db') or 0.0)
        if c.get('kind') == 'climax':                                   # a riser: measure its landing (last 0.3 s of the file)
            tail = int(0.3 * sr); sfx = sfx[-tail:]; start = float(c['start']) + (len(decode(p, sr)) - tail) / sr
        else:
            start = float(c['start'])
        off, peak = measure(master, sfx, start, sr=sr)
        row = {'id': c.get('id'), 'kind': c.get('kind'), 'planned': round(start, 4), 'offset_ms': None if off is None else round(off * 1000, 3), 'peak': round(peak, 3), 'gain_db': g}
        rows.append(row)
        if off is None or peak < 0.1:
            bad.append('%s @%.3f: not found in the master (peak %.2f)' % (c.get('id'), start, peak))
        elif abs(off * 1000) > tol_ms:
            bad.append('%s @%.3f: %+.2f ms off its cue (limit %g)' % (c.get('id'), start, off * 1000, tol_ms))
    worst = max([abs(r['offset_ms']) for r in rows if r.get('offset_ms') is not None] or [0.0])
    return {'ok': not bad, 'rows': rows, 'bad': bad, 'worst_ms': round(worst, 3), 'n': len(rows)}


# ---------------------------------------------------------------- selftest
def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix='cues_check_')
    sr = SR
    rng = np.random.RandomState(5)
    ok = True

    def t(cond, msg):
        nonlocal ok
        print('  %s  %s' % ('PASS' if cond else 'FAIL', msg)); ok = ok and bool(cond)

    def wav(path, x):
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', '-', '-c:a', 'pcm_s24le', path], input=x.astype(np.float32).tobytes(), check=True)
    tt = np.arange(int(0.12 * sr)) / sr
    whoosh = (rng.randn(len(tt)) * np.exp(-tt * 30) * 0.5).astype(np.float32)               # a noise burst with a sharp attack
    tick = (np.sin(2 * np.pi * 2200 * tt) * np.exp(-tt * 60) * 0.5).astype(np.float32)
    sd = os.path.join(d, 'sfx'); os.makedirs(sd)
    wav(os.path.join(sd, 'whoosh.wav'), whoosh); wav(os.path.join(sd, 'tick.wav'), tick)
    total = 6.0
    master = (rng.randn(int(total * sr)) * 0.02).astype(np.float32)                           # a quiet bed
    master += (0.3 * np.sin(2 * np.pi * 180 * np.arange(len(master)) / sr)).astype(np.float32)   # a voice-like tone
    plan = {'cues': [{'id': 'cut1', 'kind': 'cut', 'start': 1.0, 'file': 'whoosh.wav', 'gain_db': -14},
                     {'id': 'tick1', 'kind': 'tick', 'start': 2.5, 'file': 'tick.wav', 'gain_db': -14},
                     {'id': 'cut2', 'kind': 'cut', 'start': 4.0, 'file': 'whoosh.wav', 'gain_db': -14}]}
    offsets = {'cut1': 0.0, 'tick1': 0.0, 'cut2': 0.003}                                       # the third one lands 3 ms late
    for c in plan['cues']:
        x = whoosh if 'whoosh' in c['file'] else tick
        i = int(round((c['start'] + offsets[c['id']]) * sr)); master[i:i + len(x)] += x * 10 ** (-14 / 20)
    mp = os.path.join(d, 'master.wav'); wav(mp, master)
    R = check(plan, decode(mp), sd)
    by = {r['id']: r for r in R['rows']}
    t(abs(by['cut1']['offset_ms']) <= 0.05 and abs(by['tick1']['offset_ms']) <= 0.05, 'exact cues measure within 0.05 ms (%s, %s)' % (by['cut1']['offset_ms'], by['tick1']['offset_ms']))
    t(not R['ok'] and len(R['bad']) == 1 and 'cut2' in R['bad'][0] and abs(by['cut2']['offset_ms'] - 3.0) < 0.1, 'a 3 ms late cue fails (%s)' % R['bad'][0])
    R2 = check(plan, decode(mp), sd, tol_ms=5)
    t(R2['ok'], 'the same master passes at 5 ms tolerance')
    R3 = check({'cues': [{'id': 'ghost', 'kind': 'cut', 'start': 5.0, 'file': 'whoosh.wav'}]}, decode(mp), sd)
    t(not R3['ok'] and 'not found' in R3['bad'][0], 'a cue with no sound under it is reported as not found')
    # through an AAC mux the cue still sits inside 1 ms (what the gate is for)
    mp4 = os.path.join(d, 'film.mp4')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=30', '-i', mp, '-t', str(total), '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', '-shortest', mp4], check=True)
    R4 = check(plan, decode(mp4), sd)
    t(abs(R4['rows'][0]['offset_ms']) <= 1.0 and abs(R4['rows'][2]['offset_ms'] - 3.0) < 1.0, 'after an AAC mux the exact cue is still within 1 ms (%s ms) and the late one still reads late (%s ms)' % (R4['rows'][0]['offset_ms'], R4['rows'][2]['offset_ms']))
    shutil.rmtree(d, ignore_errors=True)
    print('cues_check selftest %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if '--selftest' in argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cues', required=True); ap.add_argument('--master'); ap.add_argument('--film')
    ap.add_argument('--sfx-dir', default='audio/sfx'); ap.add_argument('--tol-ms', type=float, default=TOL_MS); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    src = a.master or a.film
    if not src or not os.path.exists(src):
        print('need --master <wav> or --film <mp4>', file=sys.stderr); return 2
    doc = json.load(open(a.cues, encoding='utf-8'))
    sfx_dir = a.sfx_dir if os.path.isdir(a.sfx_dir) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(a.cues))), doc.get('sfx_dir', 'audio/sfx'))
    R = check(doc, decode(src), sfx_dir, a.tol_ms)
    if a.json:
        print(json.dumps(R, indent=1)); return 0 if R['ok'] else 1
    for r in R['rows']:
        print('  %-18s %-8s planned %8.3f  measured %+7.2f ms  peak %.2f' % (str(r['id'])[:18], r.get('kind', ''), r['planned'], r['offset_ms'] if r['offset_ms'] is not None else float('nan'), r['peak']))
    for b in R['bad']:
        print('FAIL  ' + b)
    print('cue sync %s — %d cues, worst %.2f ms (limit %g)' % ('OK' if R['ok'] else 'FAILED', R['n'], R['worst_ms'], a.tol_ms))
    return 0 if R['ok'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
