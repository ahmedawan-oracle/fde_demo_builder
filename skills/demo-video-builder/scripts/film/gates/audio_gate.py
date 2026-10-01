# -*- coding: utf-8 -*-
"""audio_gate.py — qa_film.py plug-in: does the voice actually sit over the bed, and does the duck behave?

    python gates/audio_gate.py --selftest

Gate 8 measures the integrated loudness of the finished file; a bed that buries the voice still passes if the
sum is −16 LUFS. These gates read the pre-master STEMS build_film.py writes (out/stem_vo_<name>.wav and
out/stem_bed_<name>.wav — the master applies one linear gain, so every difference below is preserved) and the
narration's own word times, so they need no detector and are fully deterministic.

  voice over bed   median over speech windows of (voice_M − bed_M) in LU: target ≥ 12, FAIL below 9
                   (momentary LUFS every 100 ms via ebur128; a relationship gate, never an absolute target)
  duck depth       bed_M under speech vs the bed's recovered level in gaps ≥ 0.8 s: 3 … 12 dB
                   (0 = the duck is not working, > 12 = a limp bed). Measured in the CARVED band (the split from
                   out/carve_<name>.json, default 250–2500 Hz) when the film uses the carve, full-band otherwise.
  duck breathes    in every gap ≥ 1.5 s the bed recovers ≥ 60 % of the duck depth (a slow release must still
                   come back between sentences)
  voices even      per-phase stems vo/<name>_<phase>.mp3 within ±1.5 LU of the cast median (phrases < 3 s are
                   measured as speaking-window RMS re-based onto LUFS), and the 1.2 s window spread of each phase
                   ≤ 8 dB (4–6 dB is normal prosody, 12 dB is a defect)
  true peak        out/master_<name>.wav ≤ −1.4 dBTP (build target −1.5) and the voice stem is not clipped (≤ −0.1)
  mono upmix       the voice stem is stereo with L = R and sits within 0.7 dB of the mono source: the default
                   mono→stereo rematrix (aformat / -ac 2) loses 3 dB and this catches it

qa.json keys (defaults): voice_over_bed_lu 12, voice_over_bed_fail_lu 9, duck_min_db 3, duck_max_db 12,
duck_recover_frac 0.6, voices_even_lu 1.5, voice_spread_db 8, tp_max_dbtp -1.4, upmix_tol_db 0.7.
Gates whose inputs legitimately do not exist (no bed configured, no per-phase stems) PASS with a 'skipped'
detail; inputs that are configured but missing (bed set, stems absent) FAIL with the hook to add.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'audio'))
import carve_bed                                  # noqa: E402  (speech_spans, decode)
import voice_presets                              # noqa: E402  (level_match, measure_lufs)

GATE_NAMES = ['voice over bed', 'duck depth', 'duck breathes', 'voices even', 'true peak', 'mono upmix']
DEFAULTS = {'voice_over_bed_lu': 12.0, 'voice_over_bed_fail_lu': 9.0, 'duck_min_db': 3.0, 'duck_max_db': 12.0,
            'duck_recover_frac': 0.6, 'voices_even_lu': 1.5, 'voice_spread_db': 8.0, 'tp_max_dbtp': -1.4, 'upmix_tol_db': 0.7}
GAP_DEPTH_S, GAP_BREATHE_S, SPEAK_RANGE_DB, SILENCE_LUFS, TAIL = 0.8, 1.5, 30.0, -70.0, 1.2
STEMS_HINT = 'add the stems hook to build_film.mixdown (see references/audio-carve-and-beats.md)'


# ----------------------------------------------------------------------------------------------- measurement
def momentary_lufs(path: str, band: tuple[float, float] | None = None) -> np.ndarray:
    """Momentary loudness (LUFS) every 100 ms, index k ↔ t = 0.1·k. `band` = (lo, hi) Hz measures a band-passed copy
    (4th-order Linkwitz-Riley split, the same acrossover the carve uses, keeping the middle band)."""
    pre = 'acrossover=split=%d %d:order=4th[a][b][c];[a]anullsink;[c]anullsink;[b]' % band if band else ''
    af = pre + 'ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.M:file=-'
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-i', path]
    cmd += ['-filter_complex', '[0:a]' + af + '[o]', '-map', '[o]'] if band else ['-af', af]
    r = subprocess.run(cmd + ['-f', 'null', '-'], capture_output=True, text=True)
    vals = [float(v) for v in re.findall(r'lavfi\.r128\.M=(-?[\d.]+)', r.stdout)]
    if not vals:
        raise RuntimeError('ebur128 produced no momentary values for %s: %s' % (path, r.stderr[-200:]))
    return np.asarray(vals)


def frames_in(spans, n: int, total: float) -> np.ndarray:
    """Boolean mask over 100 ms frames that fall inside any span (clipped to the narration clock)."""
    m = np.zeros(n, dtype=bool)
    for s, e in spans:
        a, b = int(math.floor(max(0.0, s) * 10)), int(math.ceil(min(e, total) * 10))
        m[a:min(b, n)] = True
    return m


def gaps_between(spans, total: float, min_len: float):
    """Gaps between consecutive speech spans (head and tail excluded) at least `min_len` long."""
    out = []
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        if s1 - e0 >= min_len and e0 < total:
            out.append((e0, min(s1, total)))
    return out


def true_peak(path: str) -> float:
    return voice_presets.measure_lufs(path)['tp']


def channel_rms_db(path: str, pre: str = '') -> list[float]:
    """Per-channel RMS (dBFS) via astats, optionally after a filter chain `pre` (e.g. the voice preset)."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-af', (pre + ',' if pre else '') + 'astats=measure_perchannel=RMS_level:measure_overall=none',
                        '-f', 'null', '-'], capture_output=True, text=True)
    return [float(l.split(':')[-1]) for l in r.stderr.splitlines() if 'RMS level dB' in l]


# ----------------------------------------------------------------------------------------------- gate
def run(ctx: dict) -> list[tuple[str, bool, str]]:
    cfg, qa, proj = ctx.get('cfg', {}), ctx.get('qa', {}), ctx['project']
    Q = {k: float(qa.get(k, v)) for k, v in DEFAULTS.items()}
    name = cfg.get('name', 'film')
    out = os.path.join(proj, 'out')
    stem_vo, stem_bed = os.path.join(out, 'stem_vo_%s.wav' % name), os.path.join(out, 'stem_bed_%s.wav' % name)
    master, vo_src = os.path.join(out, 'master_%s.wav' % name), os.path.join(proj, 'vo_%s.mp3' % name)
    ph, wd = ctx.get('vo_phases'), ctx.get('words')
    total = float(ph['total']) if ph else float(ctx.get('dur', 0.0)) - TAIL
    spans = carve_bed.speech_spans(ph, wd or {}) if ph else []
    res: list[tuple[str, bool, str]] = []
    has_bed = bool(cfg.get('bed'))

    # -- voice over bed / duck depth / duck breathes --------------------------------------------------------------
    if not has_bed:
        res += [(n, True, 'skipped: no bed configured') for n in GATE_NAMES[:3]]
    elif not (os.path.exists(stem_vo) and os.path.exists(stem_bed)):
        res += [(n, False, 'stems missing: ' + STEMS_HINT) for n in GATE_NAMES[:3]]
    elif not spans:
        res += [(n, False, 'no speech spans: vo/<name>_phases.json missing') for n in GATE_NAMES[:3]]
    else:
        band = None
        cj = os.path.join(out, 'carve_%s.json' % name)
        if cfg.get('carve') or os.path.exists(cj):
            band = tuple(json.load(open(cj, encoding='utf-8'))['split']) if os.path.exists(cj) else (250, 2500)
            band = (int(band[0]), int(band[1]))
        v, b = momentary_lufs(stem_vo), momentary_lufs(stem_bed)
        bb = momentary_lufs(stem_bed, band) if band else b
        n = min(v.size, b.size, bb.size)
        v, b, bb = v[:n], b[:n], bb[:n]
        speech = frames_in(spans, n, total)
        voiced = speech & (v > max(v[speech].max() if speech.any() else SILENCE_LUFS, SILENCE_LUFS + 1) - SPEAK_RANGE_DB) & (b > SILENCE_LUFS)
        if voiced.sum() < 5:
            res.append(('voice over bed', False, 'too few voiced frames (%d) to compare' % int(voiced.sum())))
        else:
            diff = float(np.median(v[voiced] - b[voiced]))
            okv = diff >= Q['voice_over_bed_fail_lu']
            res.append(('voice over bed', okv, 'voice - bed median %.1f LU over %d frames (target >= %.0f, fail < %.0f)%s'
                        % (diff, int(voiced.sum()), Q['voice_over_bed_lu'], Q['voice_over_bed_fail_lu'],
                           '' if diff >= Q['voice_over_bed_lu'] else '  BELOW TARGET')))
        under = float(np.mean(bb[voiced])) if voiced.sum() else float('nan')
        gaps = gaps_between(spans, total, GAP_DEPTH_S)
        gap_levels = [float(bb[a:c].max()) for a, c in ((int(s * 10), int(e * 10)) for s, e in gaps) if c > a and (bb[a:c] > SILENCE_LUFS).any()]
        where = 'band %d-%d Hz' % band if band else 'full band'
        if not gap_levels:
            res.append(('duck depth', True, 'skipped: no gaps >= %.1f s to compare against (%s)' % (GAP_DEPTH_S, where)))
            depth = 0.0
        else:
            depth = float(np.mean(gap_levels)) - under
            okd = Q['duck_min_db'] <= depth <= Q['duck_max_db']
            res.append(('duck depth', okd, '%s: bed %.1f under speech vs %.1f recovered in %d gaps = %.1f dB duck (want %.0f..%.0f)'
                        % (where, under, float(np.mean(gap_levels)), len(gap_levels), depth, Q['duck_min_db'], Q['duck_max_db'])))
        long_gaps = gaps_between(spans, total, GAP_BREATHE_S)
        if depth < 0.5 or not long_gaps:
            res.append(('duck breathes', True, 'skipped: %s' % ('no duck to recover from' if depth < 0.5 else 'no gaps >= %.1f s' % GAP_BREATHE_S)))
        else:
            rec = []
            for s, e in long_gaps:
                a, c = int(s * 10), int(e * 10)
                seg = bb[a:c]
                rec.append((round(s, 1), round((float(seg.max()) - under) / depth, 2) if seg.size else 0.0))
            bad = [(t, f) for t, f in rec if f < Q['duck_recover_frac']]
            res.append(('duck breathes', not bad, ('%d gaps >= %.1f s all recover >= %.0f%% of the %.1f dB duck' % (len(rec), GAP_BREATHE_S, Q['duck_recover_frac'] * 100, depth))
                        if not bad else 'bed stays down in gaps at %s (recovered fraction)' % bad[:4]))

    # -- voices even ----------------------------------------------------------------------------------------------
    vo_dir = os.path.join(proj, 'vo')
    phase_files = [os.path.join(vo_dir, '%s_%s.mp3' % (name, p['name'])) for p in (ph['phases'] if ph else [])]
    phase_files = [f for f in phase_files if os.path.exists(f)]
    if len(phase_files) < 2:
        res.append(('voices even', True, 'skipped: fewer than two per-phase stems in vo/'))
    else:
        rows = voice_presets.level_match(phase_files)
        lv = np.array([r['measured'] for r in rows])
        med = float(np.median(lv))
        off = [(os.path.basename(r['path']).replace(name + '_', '').replace('.mp3', ''), round(r['measured'] - med, 1))
               for r in rows if abs(r['measured'] - med) > Q['voices_even_lu']]
        wide = [(os.path.basename(r['path']).replace(name + '_', '').replace('.mp3', ''), r['spread_db']) for r in rows if r['spread_db'] > Q['voice_spread_db']]
        oke = not off and not wide
        detail = '%d phases, median %.1f LUFS, spread %.1f..%.1f' % (len(rows), med, lv.min() - med, lv.max() - med)
        if off:
            detail += '  OFF by > %.1f LU: %s' % (Q['voices_even_lu'], off[:4])
        if wide:
            detail += '  1.2 s spread > %.0f dB: %s' % (Q['voice_spread_db'], wide[:4])
        res.append(('voices even', oke, detail))

    # -- true peak ------------------------------------------------------------------------------------------------
    target = master if os.path.exists(master) else ctx.get('film')
    try:
        tp = true_peak(target)
        parts = ['%s %.2f dBTP (max %.1f)' % (os.path.basename(target), tp, Q['tp_max_dbtp'])]
        okt = tp <= Q['tp_max_dbtp']
        if os.path.exists(stem_vo):
            tpv = true_peak(stem_vo)
            parts.append('voice stem %.2f dBTP' % tpv)
            okt &= tpv <= -0.1
        res.append(('true peak', okt, '  '.join(parts)))
    except Exception as e:
        res.append(('true peak', False, 'measurement failed: %s' % e))

    # -- mono upmix -----------------------------------------------------------------------------------------------
    if not os.path.exists(stem_vo):                         # before the stems hook exists: L = R sanity on the film only
        ch = channel_rms_db(ctx['film']) if ctx.get('film') and os.path.exists(ctx['film']) else []
        oku = len(ch) == 2 and abs(ch[0] - ch[1]) <= 0.2
        res.append(('mono upmix', oku, 'film L %.1f R %.1f dBFS; level check skipped (no voice stem): %s' % (ch[0], ch[1], STEMS_HINT) if len(ch) == 2
                    else 'film audio has %d channels (want stereo)' % len(ch)))
    elif not os.path.exists(vo_src):
        res.append(('mono upmix', False, 'narration %s missing' % os.path.basename(vo_src)))
    else:
        ch = channel_rms_db(stem_vo)
        vp = cfg.get('voice_preset')                            # the stem is tapped AFTER the preset: measure the source through it too
        pre = voice_presets.preset_chain(vp, cfg.get('voice_evenness'), cfg.get('voice_deess', False), cfg.get('voice_jobs', [])) if vp else ''
        src = channel_rms_db(vo_src, pre)
        if len(ch) != 2 or not src:
            res.append(('mono upmix', False, 'voice stem has %d channels (want stereo)' % len(ch)))
        else:
            loss = src[0] - ch[0]
            oku = abs(loss) <= Q['upmix_tol_db'] and abs(ch[0] - ch[1]) <= 0.2
            res.append(('mono upmix', oku, 'stem L %.1f R %.1f vs mono source%s %.1f dBFS (loss %.1f dB, tol %.1f)%s'
                        % (ch[0], ch[1], ' via preset %s' % vp if vp else '', src[0], loss, Q['upmix_tol_db'],
                           '' if oku else '  -> upmix with pan=stereo|FL=FL+FC|FR=FR+FC, not aformat/-ac 2')))
    return res


# ----------------------------------------------------------------------------------------------- selftest
def _selftest() -> int:
    import tempfile
    SR = 48000
    tmp = tempfile.mkdtemp(prefix='agate_')
    os.makedirs(os.path.join(tmp, 'out')); os.makedirs(os.path.join(tmp, 'vo'))
    name = 'film'
    # a 14 s narration of three phrases with a 2.2 s gap and a 1.0 s gap; words every ~0.45 s
    phases, words, t = [], {}, 0.6
    for pname, dur, gap in (('open', 3.2, 2.2), ('mid', 3.6, 1.0), ('close', 2.8, 0.0)):
        n_w = int(dur / 0.45)
        words[pname] = [{'t': round(0.1 + i * 0.45, 3), 'w': 'acme%d' % i} for i in range(n_w)]
        phases.append({'name': pname, 'start': round(t, 3), 'dur': dur}); t += dur + gap
    total = round(t, 3)
    ph = {'total': total, 'phases': phases}
    json.dump(ph, open(os.path.join(tmp, 'vo', name + '_phases.json'), 'w')); json.dump(words, open(os.path.join(tmp, 'vo', name + '_words.json'), 'w'))
    # per-phase stems: synthetic voice at -20 dB RMS (one deliberately quiet copy for the negative test)
    voice = carve_bed._synth_voice(SR, 4.0)
    for p in phases:
        seg = voice[:int(p['dur'] * SR)]
        raw = os.path.join(tmp, 'seg.f32'); open(raw, 'wb').write(seg.tobytes())
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-i', raw, '-c:a', 'libmp3lame', '-q:a', '2',
                        os.path.join(tmp, 'vo', '%s_%s.mp3' % (name, p['name']))], check=True)
    # the assembled mono narration on the film clock
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-t', str(total + 0.6), '-i', 'anullsrc=r=44100:cl=mono']
    fc, labels = '', ['[0:a]']
    for i, p in enumerate(phases):
        args += ['-i', os.path.join(tmp, 'vo', '%s_%s.mp3' % (name, p['name']))]
        fc += '[%d:a]adelay=%d:all=1[d%d];' % (i + 1, int(p['start'] * 1000), i); labels.append('[d%d]' % i)
    fc += ''.join(labels) + 'amix=inputs=%d:normalize=0[a]' % len(labels)
    vo_mp3 = os.path.join(tmp, 'vo_%s.mp3' % name)
    subprocess.run(args + ['-filter_complex', fc, '-map', '[a]', '-c:a', 'libmp3lame', '-q:a', '2', vo_mp3], check=True)
    # stems through the real carve fragment (dynamic + level match) over a pink bed at -14 dB; then a master
    frag = carve_bed.carve_fragment(vo_mp3, 'bed', 'vsc', 'bedc', mode='dynamic', threshold='auto', level_match=True,
                                    json_out=os.path.join(tmp, 'out', 'carve_%s.json' % name), verbose=False)
    T = total + TAIL

    def build(upmix, bed_db, suffix=''):
        graph = ('[0:a]%s,apad=whole_dur=%.3f,asplit=3[v][vsc][vst];[1:a]%s,atrim=0:%.3f,asetpts=N/SR/TB,volume=%.1fdB[bed];%s;'
                 '[bedc]asplit=2[b][bst];[v][b]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.7:attack=5:release=80:level=false,atrim=0:%.3f,asetpts=N/SR/TB[out]'
                 % (upmix, T, carve_bed.STEREO_FMT, T, bed_db, frag, T))
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', vo_mp3, '-f', 'lavfi', '-i', 'anoisesrc=c=pink:r=48000:d=%.1f:a=0.2:s=3' % (T + 1),
                        '-filter_complex', graph, '-map', '[out]', '-c:a', 'pcm_s24le', os.path.join(tmp, 'out', 'master_%s.wav' % name),
                        '-map', '[vst]', '-c:a', 'pcm_s24le', os.path.join(tmp, 'out', 'stem_vo_%s.wav' % name),
                        '-map', '[bst]', '-c:a', 'pcm_s24le', os.path.join(tmp, 'out', 'stem_bed_%s.wav' % name)], check=True)

    ctx = {'project': tmp, 'cfg': {'name': name, 'bed': 'bed.wav', 'carve': True}, 'qa': {}, 'vo_phases': ph, 'words': words,
           'film': os.path.join(tmp, 'out', 'master_%s.wav' % name), 'dur': T}
    ok = True
    print('-- good build (pan upmix, bed -14 dB, carve dynamic + level match)')
    build(carve_bed.VO_UPMIX, -14.0)
    good = run(ctx)
    for n, o, d in good:
        print('  %-16s %s  %s' % (n, 'PASS' if o else 'FAIL', d))
    ok &= all(o for _, o, _ in good) and [n for n, _, _ in good] == GATE_NAMES
    print('-- bad build (aformat upmix = -3 dB voice, bed +8 dB, one phase stem -8 dB)')
    quiet = os.path.join(tmp, 'vo', '%s_mid.mp3' % name)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', quiet, '-af', 'volume=-8dB', '-c:a', 'libmp3lame', '-q:a', '2', quiet + '.tmp.mp3'], check=True)
    os.replace(quiet + '.tmp.mp3', quiet)
    build('aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo', 8.0)
    bad = dict((n, (o, d)) for n, o, d in run(ctx))
    for n, (o, d) in bad.items():
        print('  %-16s %s  %s' % (n, 'PASS' if o else 'FAIL', d))
    ok &= not bad['mono upmix'][0] and not bad['voices even'][0] and not bad['voice over bed'][0]
    print('SELFTEST %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
