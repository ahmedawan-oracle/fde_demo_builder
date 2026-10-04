# -*- coding: utf-8 -*-
"""fx_chain.py — a declared FX chain per bus (voice / bed / sfx) as ffmpeg filter strings from a JSON spec.

    python audio/fx_chain.py --preset voice-booth                             # print the filtergraph fragment
    python audio/fx_chain.py --preset voice-booth vo_film.mp3 --out out/vo_fx.wav --json out/fx_vo.json
    python audio/fx_chain.py --spec fx.json --bus bed bed.mp3 --out out/bed_fx.wav
    python audio/fx_chain.py --presets                                        # the three presets as JSON
    python audio/fx_chain.py --selftest

Why a declared chain
  A polish pass that lives in someone's head is not repeatable. Here every stage is a JSON row with explicit
  numbers; the tool turns the rows into ONE ffmpeg filter_complex fragment (`[in] … [out]`), prints it, runs it,
  and measures before/after with ebur128 (integrated LUFS, loudness range, sample peak) plus the 5–8 kHz band
  share, so a change is a number, not an opinion. The same JSON drives build_film.py's mixdown.

Stages (type → ffmpeg)
  highpass    {f, poles=2}                         highpass=f=F:poles=P            (rumble, desk thumps, HVAC)
  lowpass     {f, poles=2}                         lowpass=f=F:poles=P
  deess       {lo=5000, hi=8000, threshold_db=-30, ratio=4, attack=1, release=60}
              there is no de-esser filter in ffmpeg, so it is built from parts: acrossover splits the signal at
              lo and hi (4th-order Linkwitz-Riley — the three bands sum back to unity, verified in carve_bed),
              only the middle band goes through acompressor, and amix=normalize=0 reassembles. Sibilance lives
              in 5–8 kHz; a 1 ms attack catches an "s" (20–40 ms long), a 60 ms release lets it go before the
              next vowel. Measured on the selftest voice (stage alone): 5–8 kHz RMS −2.5 dB, full-band −0.2 LU.
  eq          {bands:[{f, g, q=1.0}]}              equalizer=f=F:t=q:w=Q:g=G per band (peaking)
  shelf       {kind:'low'|'high', f, g}            lowshelf / highshelf
  compressor  {threshold_db=-20, ratio=3, attack=10, release=150, makeup_db=0, knee=2.8}
                                                   acompressor (threshold as linear; attack/release in ms)
  gate        {threshold_db=-45, range_db=-12, attack=10, release=200}
                                                   agate (range is how far it closes — never to silence on a
                                                   voice bus; −12 dB hides room tone without chopping breaths)
  limiter     {ceiling_db=-1.0, attack=5, release=50}
                                                   alimiter=limit=L:attack:release:level=false (no auto-gain)
  echo        {in=0.8, out=0.25, delays=[60], decays=[0.3]}   aecho — bed only (a hall under a voice smears words)
  widen       {amount=1.25}                        extrastereo=m=A:c=0 — bed only; mono input is passed through
  gain        {db}                                 volume=XdB

Presets (JSON, override any field)
  voice-booth      highpass 80 Hz · de-esser 5–8 kHz −30 dB 4:1 · eq −2 dB @ 250 Hz Q1 (boxiness) +1.5 dB @ 3 kHz
                   Q1 (presence) · compressor −20 dB 3:1 10/150 ms +3 dB make-up · gate −45 dB range −12 ·
                   limiter −1 dBFS. A home recording comes out sitting like a booth take.
  bed-under-voice  highpass 40 Hz · eq −3 dB @ 2.5 kHz Q1.2 (the carve does the dynamic part; this is the static
                   bias toward the voice's presence band) · compressor −24 dB 2:1 30/400 ms (evens phrases) ·
                   widen 1.25 · limiter −3 dBFS.
  sfx-tight        highpass 30 Hz (keeps the 45 Hz thump) · compressor −18 dB 4:1 2/80 ms (one consistent
                   transient size) · limiter −3 dBFS.

Spec JSON: {"buses": {"voice": {"preset": "voice-booth", "chain": [...]}, "bed": {...}}}  or a bare chain
list [{"type": ..., ...}]. A bus with both `preset` and `chain` runs the preset THEN the chain.
Report JSON: {bus, preset, chain, filter, before:{lufs, lra, peak_dbfs, hf_share_db, hf_db}, after:{…}, delta:{…}}
Exit codes: 0 ok, 1 ffmpeg failed or the measurement is missing, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sfx_synth  # noqa: E402

SR = 48000
BED_ONLY = {'echo', 'widen'}

PRESETS = {
    'voice-booth': [
        {'type': 'highpass', 'f': 80},
        {'type': 'deess', 'lo': 5000, 'hi': 8000, 'threshold_db': -30, 'ratio': 4, 'attack': 1, 'release': 60},
        {'type': 'eq', 'bands': [{'f': 250, 'g': -2.0, 'q': 1.0}, {'f': 3000, 'g': 1.5, 'q': 1.0}]},
        {'type': 'compressor', 'threshold_db': -20, 'ratio': 3, 'attack': 10, 'release': 150, 'makeup_db': 3},
        {'type': 'gate', 'threshold_db': -45, 'range_db': -12, 'attack': 10, 'release': 200},
        {'type': 'limiter', 'ceiling_db': -1.0},
    ],
    'bed-under-voice': [
        {'type': 'highpass', 'f': 40},
        {'type': 'eq', 'bands': [{'f': 2500, 'g': -3.0, 'q': 1.2}]},
        {'type': 'compressor', 'threshold_db': -24, 'ratio': 2, 'attack': 30, 'release': 400},
        {'type': 'widen', 'amount': 1.25},
        {'type': 'limiter', 'ceiling_db': -3.0},
    ],
    'sfx-tight': [
        {'type': 'highpass', 'f': 30},
        {'type': 'compressor', 'threshold_db': -18, 'ratio': 4, 'attack': 2, 'release': 80},
        {'type': 'limiter', 'ceiling_db': -3.0},
    ],
}
BUS_PRESET = {'voice': 'voice-booth', 'bed': 'bed-under-voice', 'sfx': 'sfx-tight'}


def lin(db: float) -> float:
    return 10 ** (db / 20.0)


# ----------------------------------------------------------------------------------------------- stage -> filter
def stage_filters(st: dict, bus: str, tag: str) -> list[str]:
    """One stage -> a list of filter_complex SEGMENTS. A segment with `{i}`/`{o}` placeholders is single-in,
    single-out; the de-esser returns one self-contained multi-stream segment using `tag` for unique labels."""
    t = st['type']
    if t in BED_ONLY and bus != 'bed':
        raise ValueError('stage %r is bed-only (a hall or a widener under a voice smears words); bus=%s' % (t, bus))
    if t == 'highpass':
        return ['{i}highpass=f=%g:poles=%d{o}' % (st['f'], st.get('poles', 2))]
    if t == 'lowpass':
        return ['{i}lowpass=f=%g:poles=%d{o}' % (st['f'], st.get('poles', 2))]
    if t == 'deess':
        lo, hi = st.get('lo', 5000), st.get('hi', 8000)
        comp = 'acompressor=threshold=%.5f:ratio=%g:attack=%g:release=%g:makeup=1:knee=2' % (
            lin(st.get('threshold_db', -30)), st.get('ratio', 4), st.get('attack', 1), st.get('release', 60))
        return ['{i}acrossover=split=%g %g:order=4th[%sL][%sM][%sH];[%sM]%s[%sMc];[%sL][%sMc][%sH]amix=inputs=3:normalize=0:duration=longest{o}'
                % (lo, hi, tag, tag, tag, tag, comp, tag, tag, tag, tag)]
    if t == 'eq':
        return ['{i}' + ','.join('equalizer=f=%g:t=q:w=%g:g=%g' % (b['f'], b.get('q', 1.0), b['g']) for b in st['bands']) + '{o}']
    if t == 'shelf':
        return ['{i}%sshelf=f=%g:g=%g{o}' % (st.get('kind', 'low'), st['f'], st['g'])]
    if t == 'compressor':
        return ['{i}acompressor=threshold=%.5f:ratio=%g:attack=%g:release=%g:makeup=%.4f:knee=%g{o}' % (
            lin(st.get('threshold_db', -20)), st.get('ratio', 3), st.get('attack', 10), st.get('release', 150),
            lin(st.get('makeup_db', 0)), st.get('knee', 2.8))]
    if t == 'gate':
        return ['{i}agate=threshold=%.5f:range=%.5f:attack=%g:release=%g:ratio=2{o}' % (
            lin(st.get('threshold_db', -45)), lin(st.get('range_db', -12)), st.get('attack', 10), st.get('release', 200))]
    if t == 'limiter':
        return ['{i}alimiter=limit=%.5f:attack=%g:release=%g:level=false{o}' % (
            lin(st.get('ceiling_db', -1.0)), st.get('attack', 5), st.get('release', 50))]
    if t == 'echo':
        return ['{i}aecho=%g:%g:%s:%s{o}' % (st.get('in', 0.8), st.get('out', 0.25),
                                              '|'.join('%g' % d for d in st.get('delays', [60])), '|'.join('%g' % d for d in st.get('decays', [0.3])))]
    if t == 'widen':
        return ['{i}extrastereo=m=%g:c=0{o}' % st.get('amount', 1.25)]
    if t == 'gain':
        return ['{i}volume=%gdB{o}' % st['db']]
    raise ValueError('unknown stage type %r' % t)


def chain_fragment(chain: list[dict], bus: str = 'voice', inp: str = 'in', out: str = 'out') -> str:
    """The whole chain as a filter_complex fragment `[inp]...[out]`. Consecutive single-stream stages are joined with
    commas; a multi-stream stage (de-esser) gets its own `;`-separated segment with labels <bus>_fx<k>."""
    segs, pending, cur = [], [], '[%s]' % inp
    k = c = 0
    for st in chain:
        for f in stage_filters(st, bus, '%s_fx%d' % (bus, k)):
            k += 1
            if ';' in f:                                    # multi-stream: flush pending, give it its own segment
                if pending:
                    c += 1; nxt = '[%s_c%d]' % (bus, c); segs.append(cur + ','.join(pending) + nxt); cur, pending = nxt, []
                c += 1; nxt = '[%s_c%d]' % (bus, c); segs.append(f.replace('{i}', cur).replace('{o}', nxt)); cur = nxt
            else:
                pending.append(f.replace('{i}', '').replace('{o}', ''))
    if pending:
        segs.append(cur + ','.join(pending) + '[%s]' % out)
    elif cur != '[%s]' % inp:
        segs.append(cur + 'anull[%s]' % out)
    else:
        segs.append(cur + 'anull[%s]' % out)
    frag = ';'.join(segs)
    return frag


def resolve_chain(spec: dict | list | None, bus: str, preset: str | None) -> tuple[str | None, list[dict]]:
    """(preset_name, chain) for a bus from a spec and/or a preset name. Bus defaults: voice->voice-booth, bed->bed-under-voice, sfx->sfx-tight."""
    chain: list[dict] = []
    if isinstance(spec, dict) and 'buses' in spec:
        b = spec['buses'].get(bus, {})
        preset = preset or b.get('preset')
        chain = list(b.get('chain', []))
    elif isinstance(spec, list):
        chain = list(spec)
    if preset is None and not chain:
        preset = BUS_PRESET.get(bus)
    if preset:
        if preset not in PRESETS:
            raise ValueError('unknown preset %r (have %s)' % (preset, ', '.join(PRESETS)))
        chain = [dict(s) for s in PRESETS[preset]] + chain
    return preset, chain


# ----------------------------------------------------------------------------------------------- measurement
def measure(path: str) -> dict:
    """Integrated LUFS, LRA and sample peak via ebur128's summary, plus the 5–8 kHz share of the energy in dB
    (10·log10(E_5–8k / E_total)) from a numpy FFT of the decoded mono signal."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-af', 'ebur128=peak=sample', '-f', 'null', '-'],
                       capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind('Summary:'):] if 'Summary:' in r.stderr else ''
    g = lambda pat: float(re.search(pat, tail).group(1)) if re.search(pat, tail) else None
    out = {'lufs': g(r'I:\s*(-?[\d.]+) LUFS'), 'lra': g(r'LRA:\s*(-?[\d.]+) LU'), 'peak_dbfs': g(r'Peak:\s*(-?[\d.]+) dBFS')}
    if out['lufs'] is None:
        raise RuntimeError('ebur128 summary missing for %s: %s' % (path, r.stderr[-200:]))
    x = decode(path)
    w = np.hanning(x.size)
    spec = np.abs(np.fft.rfft(x * w)) ** 2
    f = np.fft.rfftfreq(x.size, 1 / SR)
    hf = spec[(f >= 5000) & (f <= 8000)].sum(); tot = spec.sum() or 1.0
    out['hf_share_db'] = round(10 * math.log10(max(hf, 1e-20) / tot), 2)
    out['hf_db'] = round(10 * math.log10(max(2 * hf / (x.size * float(np.sum(w ** 2))), 1e-20)), 2)   # band RMS in dBFS (Parseval)
    return out


def decode(path: str, sr: int = SR) -> np.ndarray:
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError('decode failed for %s: %s' % (path, r.stderr.decode('utf-8', 'replace')[-300:]))
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)


def apply(src: str, dest: str, chain: list[dict], bus: str, stereo: bool = True) -> str:
    """Run the chain on `src` -> `dest` (pcm_s24le 48 kHz). Returns the filter_complex used."""
    fmt = 'aformat=sample_fmts=fltp:sample_rates=48000' + (':channel_layouts=stereo' if stereo else '')
    frag = '[0:a]%s[in];' % fmt + chain_fragment(chain, bus)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, '-filter_complex', frag, '-map', '[out]', '-c:a', 'pcm_s24le', dest],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('ffmpeg failed: %s\n%s' % (r.stderr[-400:], frag))
    return frag


def run_bus(src: str, dest: str, spec, bus: str, preset: str | None, json_out: str | None = None) -> dict:
    preset, chain = resolve_chain(spec, bus, preset)
    before = measure(src)
    frag = apply(src, dest, chain, bus)
    after = measure(dest)
    rep = {'bus': bus, 'preset': preset, 'chain': chain, 'filter': frag, 'src': src, 'out': dest, 'before': before, 'after': after,
           'delta': {k: (round(after[k] - before[k], 2) if before.get(k) is not None and after.get(k) is not None else None) for k in before}}
    if json_out:
        json.dump(rep, open(json_out, 'w', encoding='utf-8'), indent=1)
    return rep


# ----------------------------------------------------------------------------------------------- selftest
def _synth_voice(dur: float = 6.0, seed: int = 3) -> np.ndarray:
    """A voice-like test signal: 120 Hz pulse train through formant-ish resonances, syllable gating at 4 Hz, with
    sibilant noise bursts (5–8 kHz) on every third syllable and a -50 dBFS room-tone floor."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR); t = np.arange(n) / SR
    src = np.where((t * 120.0) % 1.0 < 0.08, 1.0, -0.08)
    from scipy import signal as sg
    v = np.zeros(n)
    for f, q, g in ((500, 6, 1.0), (1500, 8, 0.5), (2500, 10, 0.3)):
        sos = sg.butter(2, [f / math.sqrt(1 + 1 / q), f * math.sqrt(1 + 1 / q)], btype='bandpass', fs=SR, output='sos')
        v += g * sg.sosfilt(sos, src)
    syl = np.clip(np.sin(2 * np.pi * 4 * t), 0, 1) ** 0.5
    v *= syl
    sib = sfx_synth.butter_bp(rng.standard_normal(n), 5000, 8000) * (np.floor(t * 4) % 3 == 2) * (1 - syl) * 0.6
    sent = (t % 3.0) < 2.2                                             # sentences with 0.8 s gaps
    sig = (v / np.max(np.abs(v)) * 0.5 + sib * 0.5) * sent + rng.standard_normal(n) * lin(-50)
    m = int(0.05 * SR); sig[2 * SR:2 * SR + m] += 0.95 * np.sin(2 * np.pi * 60 * t[:m])          # a desk thump
    return sig


def selftest() -> int:
    import tempfile, time
    t0 = time.time(); fails = []
    tmp = tempfile.mkdtemp(prefix='fx_')
    src = os.path.join(tmp, 'src_voice.wav'); sfx_synth.write_wav(src, _synth_voice())
    for bus in ('voice', 'bed', 'sfx'):                                # every preset parses and runs
        try:
            frag = chain_fragment(resolve_chain(None, bus, None)[1], bus)
            apply(src, os.path.join(tmp, bus + '.wav'), resolve_chain(None, bus, None)[1], bus)
        except Exception as e:
            fails.append('%s preset failed: %s' % (bus, e))
    rep = run_bus(src, os.path.join(tmp, 'vo_fx.wav'), None, 'voice', 'voice-booth', os.path.join(tmp, 'fx.json'))
    d = rep['delta']
    # the de-esser alone: 5-8 kHz RMS down by >= 2 dB while the full-band loudness moves < 1 LU
    de = run_bus(src, os.path.join(tmp, 'deess.wav'), [PRESETS['voice-booth'][1]], 'voice', None)
    if not (de['delta']['hf_db'] < -2.0 and abs(de['delta']['lufs']) < 1.0):
        fails.append('de-esser stage: hf %.2f dB, lufs %.2f LU (want <= -2 dB and |LU| < 1)' % (de['delta']['hf_db'], de['delta']['lufs']))
    if not (rep['after']['peak_dbfs'] <= -0.9):
        fails.append('limiter ceiling missed: peak %.2f dBFS' % rep['after']['peak_dbfs'])
    if not (-4.0 < d['lufs'] < 4.0):
        fails.append('voice-booth moved loudness by %.1f LU (expected a small change)' % d['lufs'])
    # the de-esser crossover sums flat: bypassing the compressor returns the input within 0.1 dB
    flat = [{'type': 'deess', 'threshold_db': 0, 'ratio': 1}]
    apply(src, os.path.join(tmp, 'flat.wav'), flat, 'voice')
    a, b = measure(src), measure(os.path.join(tmp, 'flat.wav'))
    if abs(a['lufs'] - b['lufs']) > 0.1:
        fails.append('crossover does not sum to unity (%.2f LU)' % (b['lufs'] - a['lufs']))
    try:
        chain_fragment([{'type': 'widen'}], 'voice'); fails.append('bed-only stage accepted on the voice bus')
    except ValueError:
        pass
    # determinism: two runs -> identical bytes
    apply(src, os.path.join(tmp, 'r1.wav'), PRESETS['voice-booth'], 'voice'); apply(src, os.path.join(tmp, 'r2.wav'), PRESETS['voice-booth'], 'voice')
    if sfx_synth.md5_of(os.path.join(tmp, 'r1.wav')) != sfx_synth.md5_of(os.path.join(tmp, 'r2.wav')):
        fails.append('chain output not deterministic')
    print('fx_chain selftest: de-esser alone hf %.2f dB / %.2f LU; voice-booth lufs %+.1f LU, lra %.1f -> %.1f, peak %.1f -> %.1f dBFS; %.1f s, %s' % (
        de['delta']['hf_db'], de['delta']['lufs'], d['lufs'], rep['before']['lra'], rep['after']['lra'], rep['before']['peak_dbfs'], rep['after']['peak_dbfs'],
        time.time() - t0, 'OK' if not fails else '; '.join(fails)))
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='declared FX chain per bus -> ffmpeg filtergraph; runs it and measures before/after')
    ap.add_argument('src', nargs='?', help='input audio (omit to only print the filtergraph)')
    ap.add_argument('--bus', default='voice', choices=['voice', 'bed', 'sfx'])
    ap.add_argument('--preset', help='voice-booth | bed-under-voice | sfx-tight (default by bus)')
    ap.add_argument('--spec', help='JSON spec ({"buses":{bus:{preset,chain}}} or a chain list)')
    ap.add_argument('--out', help='output WAV (pcm_s24le 48 kHz)')
    ap.add_argument('--json', help='write the report')
    ap.add_argument('--presets', action='store_true', help='print the presets as JSON')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.presets:
        print(json.dumps(PRESETS, indent=1)); return 0
    spec = json.load(open(a.spec, encoding='utf-8')) if a.spec else None
    try:
        preset, chain = resolve_chain(spec, a.bus, a.preset)
        frag = chain_fragment(chain, a.bus)
    except ValueError as e:
        print('error: %s' % e, file=sys.stderr); return 2
    if not a.src:
        print(frag); return 0
    if not a.out:
        print('error: --out is required to run the chain', file=sys.stderr); return 2
    try:
        rep = run_bus(a.src, a.out, spec, a.bus, a.preset, a.json)
    except RuntimeError as e:
        print('error: %s' % e, file=sys.stderr); return 1
    print(rep['filter'])
    print(json.dumps({'before': rep['before'], 'after': rep['after'], 'delta': rep['delta']}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
