# -*- coding: utf-8 -*-
"""build_film.py — v3: render → mix → master → mux → captions → MANDATORY credit.

    python build_film.py [--skip-render]          (reads film.json; see film.example.json)

  1. render   scenes/film.html deterministically (render_frames.js): 1920x1080, 30 fps CFR, frame 0 = clock 0
  2. mix      narration (vo_<name>.mp3) + optional music bed, sidechain-ducked under the voices, + optional SFX
  3. master   two-pass LINEAR loudnorm to -16 LUFS / TP -1.5; refuses to ship if loudnorm falls back to dynamic
  4. mux      video copy + AAC 256k, faststart
  5. captions out/<film>.srt from the narration phases
  6. credit   credit.py stamps "Crafted with FDE Demo Builder · by Ahmed Awan" on the end screen and verifies
              it. This step is not optional: there is no flag to skip it, and QA fails a video without it.

The narration is the clock: the total length comes from vo/<name>_phases.json, so picture and sound cannot drift.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
C = json.load(open(os.path.join(HERE, 'film.json'), encoding='utf-8'))
NAME = C.get('name', 'film')
OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
TOTAL = float(json.load(open(os.path.join(HERE, 'vo', NAME + '_phases.json')))['total'])
FPS = int(C.get('fps', 30))
SEG = os.path.join(OUT, 'seg_%s.mp4' % NAME)
MIX, MASTER, RAW = (os.path.join(OUT, '%s_%s.wav' % (k, NAME)) for k in ('mix', 'master', 'raw'))
PRE = os.path.join(OUT, 'precredit_%s.mp4' % NAME)
FILM = os.path.join(HERE, C.get('output', 'out/%s.mp4' % NAME))
SRT = os.path.splitext(FILM)[0] + '.srt'
VO = os.path.join(HERE, 'vo_%s.mp3' % NAME)
BED = os.path.join(HERE, C['bed']) if C.get('bed') else None
SFX = os.path.join(HERE, C['sfx']) if C.get('sfx') else None
LUFS_I, LUFS_TP, LUFS_LRA = -16.0, -1.5, 11.0
TAIL = 1.2                                      # music/room tail after the last word


def run(cmd, **kw):
    print('  $', ' '.join(str(c) for c in cmd[:8]), '...' if len(cmd) > 8 else '')
    return subprocess.run(cmd, check=True, **kw)


def render():
    print('[1/6] render picture (%.2f s)' % (TOTAL + TAIL))
    run(['node', os.path.join(HERE, 'render_frames.js'), C.get('scene', 'scenes/film.html'), SEG,
         '%.3f' % (TOTAL + TAIL), str(FPS), '96', str(C.get('workers', 3))], cwd=HERE)


def mixdown(dest, pre_db=0.0, limit_db=None):
    ins, fc, mixes = ['-i', VO], ['[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad=whole_dur=%.3f,asplit=2[v][vsc]' % (TOTAL + TAIL)], ['[v]']
    if BED:
        ins += ['-stream_loop', '-1', '-i', BED]
        fc.append('[%d:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,atrim=0:%.3f,asetpts=N/SR/TB,'
                  'volume=%.1fdB,afade=t=in:st=0:d=1.5,afade=t=out:st=%.3f:d=3[bedraw]'
                  % (1, TOTAL + TAIL, C.get('bed_db', -9.0), max(0.0, TOTAL + TAIL - 3.0)))
        fc.append('[bedraw][vsc]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=500[b]')
        mixes.append('[b]')
    else:
        fc.append('[vsc]anullsink')
    if SFX:
        k = 2 if BED else 1
        ins += ['-i', SFX]
        fc.append('[%d:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=%.1fdB[k]' % (k, C.get('sfx_db', -5.0)))
        mixes.append('[k]')
    chain = ';'.join(fc) + ';' + ''.join(mixes) + 'amix=inputs=%d:duration=first:normalize=0:dropout_transition=0[m];[m]volume=%.2fdB' % (len(mixes), pre_db)
    if limit_db is not None:
        chain += ',alimiter=limit=%.5f:attack=5:release=80:level=false' % (10 ** (limit_db / 20.0))
    chain += ',atrim=0:%.3f,asetpts=N/SR/TB[out]' % (TOTAL + TAIL)
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + ins + ['-filter_complex', chain, '-map', '[out]',
         '-c:a', 'pcm_s24le', '-ar', '48000', dest])


def measure(p):
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', p, '-af', 'loudnorm=I=%.1f:TP=%.1f:LRA=%.1f:print_format=json'
                        % (LUFS_I, LUFS_TP, LUFS_LRA), '-f', 'null', '-'], capture_output=True, text=True)
    m = re.findall(r'\{[^{}]*"input_i"[\s\S]*?\}', r.stderr)
    if not m:
        raise SystemExit('loudnorm measurement failed:\n' + r.stderr[-1200:])
    return json.loads(m[-1])


def mix():
    # Two stages: a linear master only survives if the mix arrives near the target with headroom, so lift the
    # raw mix to just above target and sample-peak-limit it below the true-peak ceiling first.
    print('[2/6] mix narration%s%s' % (' + ducked bed' if BED else '', ' + sfx' if SFX else ''))
    mixdown(RAW)
    raw_i = float(measure(RAW)['input_i'])
    pre, ceil = (LUFS_I + 0.45) - raw_i, LUFS_TP - 0.8
    print('      raw %.2f LUFS -> pre-gain %+.2f dB, limiter %.2f dBFS' % (raw_i, pre, ceil))
    mixdown(MIX, pre_db=pre, limit_db=ceil)


def master():
    print('[3/6] master (two-pass linear loudnorm)')
    st = measure(MIX)
    af = ('loudnorm=I=%.1f:TP=%.1f:LRA=%.1f:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:offset=%s:'
          'linear=true:print_format=json' % (LUFS_I, LUFS_TP, LUFS_LRA, st['input_i'], st['input_tp'], st['input_lra'],
                                             st['input_thresh'], st['target_offset']))
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-y', '-i', MIX, '-af', af, '-ar', '48000', '-c:a', 'pcm_s24le', MASTER],
                       capture_output=True, text=True)
    rep = json.loads(re.findall(r'\{[^{}]*"normalization_type"[\s\S]*?\}', r.stderr)[-1])
    print('      %s  out I %s  TP %s' % (rep['normalization_type'], rep['output_i'], rep['output_tp']))
    if rep['normalization_type'].lower() != 'linear':
        raise SystemExit('REFUSING: loudnorm fell back to %s. Lower the bed or raise TP headroom.' % rep['normalization_type'])


def mux():
    print('[4/6] mux')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', SEG, '-i', MASTER, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
         '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-ac', '2', '-shortest', '-movflags', '+faststart', PRE])


def captions():
    print('[5/6] captions')
    sys.path.insert(0, HERE)
    import vo_script
    txt = {p['name']: ' '.join(p['text'].split()) for p in vo_script.SCENES[NAME]['phases']}
    ph = json.load(open(os.path.join(HERE, 'vo', NAME + '_phases.json')))['phases']
    ts = lambda x: '%02d:%02d:%02d,%03d' % (int(x // 3600), int(x % 3600 // 60), int(x % 60), round((x - int(x)) * 1000) % 1000)
    out = []
    for i, p in enumerate(ph):
        end = min(p['start'] + p['dur'] + 0.35, ph[i + 1]['start'] if i + 1 < len(ph) else TOTAL + TAIL)
        out.append('%d\n%s --> %s\n%s\n' % (i + 1, ts(p['start']), ts(end), txt.get(p['name'], '')))
    open(SRT, 'w', encoding='utf-8').write('\n'.join(out))


def credit():
    print('[6/6] credit (mandatory)')
    sys.path.insert(0, HERE)
    import credit as CR
    CR.stamp(PRE, FILM)
    if not CR.check(FILM):
        raise SystemExit('REFUSING: the FDE Demo Builder credit is not legible on the end screen.')
    os.remove(PRE)


if __name__ == '__main__':
    if '--skip-render' not in sys.argv:
        render()
    mix(); master(); mux(); captions(); credit()
    print('\nDONE  ' + FILM)
