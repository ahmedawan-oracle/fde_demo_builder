# -*- coding: utf-8 -*-
"""build_film.py — v4: plan → preflight → render → mix → master → mux → captions → MANDATORY credit → ledger → exports.

    python build_film.py [--skip-render] [--skip-canary] [--autonomous]        (reads film.json; see film.example.json)

  0. plan + preflight
       export_timeline.js      cuts, seams (seams.json → scenes/seams_data.js), shots → out/timeline.json
       captions export         scenes/captions.json → out/caption_groups.json + scenes/captions_data.js (lib/captions.js)
       doctor --fast           ffmpeg / node / Chrome / edge-tts / fonts / disk
       lint_scene              static determinism + seekability scan (errors block the render; "lint": "strict" blocks warnings)
       camera ladder           node scenes/lib/camera.js --curves (pose ladder lint + zoom budget → out/camera_report.json)
       storyboard check        STORYBOARD.md must be locked and add up to the narration (--autonomous for a drive-it run)
       canary                  render a few frames twice and compare (determinism); --skip-canary to accept a known seam
  1. render   scenes/film.html deterministically (render_frames.js): 1920x1080, 30 fps CFR, frame 0 = clock 0
  2. mix      narration (pan-upmixed, optional voice preset) + bed carved around the voice band + optional SFX;
              writes out/stem_vo_<name>.wav / out/stem_bed_<name>.wav for the audio gates
  3. master   two-pass LINEAR loudnorm to -16 LUFS / TP -1.5; refuses to ship if loudnorm falls back to dynamic
  4. mux      video copy + AAC 256k, faststart, provenance in the container comment (no paths, no user names)
  5. captions out/<film>.srt (+ .vtt) from the same caption groups the lane burns in, or per phase when no lane
  6. credit   credit.py stamps "Crafted with FDE Demo Builder · by Ahmed Awan" on the end screen and verifies it.
              This step is not optional: there is no flag to skip it, and QA fails a video without it.
  7. after    media ledger marks what the build used; film.json "exports" derive presets (tools/export.py);
              the storyboard truth pass redraws out/storyboard.html from the real frames.

The narration is the clock: the total length comes from vo/<name>_phases.json, so picture and sound cannot drift.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
C = json.load(open(os.path.join(HERE, 'film.json'), encoding='utf-8'))
NAME = C.get('name', 'film')
OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
PHASES_JSON = os.path.join(HERE, 'vo', NAME + '_phases.json')
WORDS_JSON = os.path.join(HERE, 'vo', NAME + '_words.json')
TOTAL = float(json.load(open(PHASES_JSON))['total'])
FPS = int(C.get('fps', 30))
SCENE = C.get('scene', 'scenes/film.html')
SEG = os.path.join(OUT, 'seg_%s.mp4' % NAME)
MIX, MASTER, RAW = (os.path.join(OUT, '%s_%s.wav' % (k, NAME)) for k in ('mix', 'master', 'raw'))
STEM_VO, STEM_BED = (os.path.join(OUT, 'stem_%s_%s.wav' % (k, NAME)) for k in ('vo', 'bed'))
PRE = os.path.join(OUT, 'precredit_%s.mp4' % NAME)
FILM = os.path.join(HERE, C.get('output', 'out/%s.mp4' % NAME))
SRT = os.path.splitext(FILM)[0] + '.srt'
VO = os.path.join(HERE, 'vo_%s.mp3' % NAME)
BED = os.path.join(HERE, C['bed']) if C.get('bed') else None
SFX = os.path.join(HERE, C['sfx']) if C.get('sfx') else None
BED_DB = float(C.get('bed_db', -12.0))             # v4 default -12 (was -9): the pan upmix restores 3 dB of voice
LUFS_I, LUFS_TP, LUFS_LRA = -16.0, -1.5, 11.0
TAIL = 1.2                                          # music/room tail after the last word
ARGS = sys.argv[1:]
TIMING_DATA = os.path.join(HERE, 'scenes', 'timing_%s_data.js' % NAME)
SHOTS_JS = os.path.join(HERE, 'scenes', 'shots.js')

sys.path.insert(0, os.path.join(HERE, 'audio')); sys.path.insert(0, os.path.join(HERE, 'tools'))
try:
    import carve_bed as CB, voice_presets as VP, beat_grid as BG
except ImportError:                                 # a v3 project without the audio/ folder keeps the v3 graph
    CB = VP = BG = None


def run(cmd, **kw):
    print('  $', ' '.join(str(c) for c in cmd[:8]), '...' if len(cmd) > 8 else '')
    return subprocess.run(cmd, check=True, **kw)


def have(*rel):
    return os.path.exists(os.path.join(HERE, *rel))


# ---------------------------------------------------------------- 0. plan + preflight
def plan():
    print('[0/7] plan: timeline, seams, captions')
    if have('export_timeline.js'):
        run(['node', os.path.join(HERE, 'export_timeline.js'), TIMING_DATA, SHOTS_JS], cwd=HERE)
    cap = C.get('captions') or {}
    if cap.get('config') and have(cap['config']) and have('scenes', 'lib', 'captions.js'):
        if cap.get('luma') and not have(cap['luma']) and have('gates', 'overlay_gate.py') and '--skip-render' not in ARGS:
            # the lane picks dark ink on bright screens: probe the scene once (captions off) for per-phase luma
            subprocess.run([sys.executable, os.path.join(HERE, 'gates', 'overlay_gate.py'), '--probe', SCENE.split('?')[0]], cwd=HERE)
        cmd = ['node', os.path.join(HERE, 'scenes', 'lib', 'captions.js'), TIMING_DATA, os.path.join(HERE, cap['config']),
               '--out', os.path.join(OUT, 'caption_groups.json'), '--js', os.path.join(HERE, 'scenes', 'captions_data.js')]
        if cap.get('luma') and have(cap['luma']):
            cmd += ['--luma', os.path.join(HERE, cap['luma'])]
        run(cmd, cwd=HERE)


def preflight():
    print('[0/7] preflight: doctor, lint, camera ladder, storyboard, canary')
    if have('tools', 'doctor.py'):
        r = subprocess.run([sys.executable, os.path.join(HERE, 'tools', 'doctor.py'), '--project', HERE, '--fast', '--json'], capture_output=True, text=True)
        try:
            ok = json.loads(r.stdout or '{}').get('ok')
        except ValueError:
            ok = False
        if not ok:
            raise SystemExit('REFUSING: environment not ready — run python tools/doctor.py')
    if have('gates', 'lint_scene.py'):
        lint = [sys.executable, os.path.join(HERE, 'gates', 'lint_scene.py'), SCENE.split('?')[0], '--project', HERE]
        if C.get('lint') == 'strict':
            lint.append('--strict')
        if subprocess.run(lint, cwd=HERE).returncode != 0:
            raise SystemExit('REFUSING: fix lint errors before rendering (python gates/lint_scene.py %s --project .)' % SCENE)
    if have('scenes', 'lib', 'camera.js') and have('broll', 'clips.js'):
        r = subprocess.run(['node', os.path.join(HERE, 'scenes', 'lib', 'camera.js'), '--curves', TIMING_DATA, SHOTS_JS,
                            os.path.join(HERE, 'broll', 'clips.js'), '--out', OUT], cwd=HERE)
        if r.returncode and not C.get('camera_lint_soft'):
            raise SystemExit('REFUSING: camera lint FAIL or zoom budget exceeded (out/camera_report.json; "camera_lint_soft": true renders anyway).')
    sb = os.path.join(HERE, C.get('storyboard', 'STORYBOARD.md'))
    if os.path.exists(sb) and have('tools', 'storyboard.py'):
        rc = subprocess.run([sys.executable, os.path.join(HERE, 'tools', 'storyboard.py'), 'check', sb, '--build']
                            + (['--autonomous'] if '--autonomous' in ARGS else []), cwd=HERE).returncode
        if rc:
            raise SystemExit('REFUSING: STORYBOARD.md check failed (see above). Fix the plan, or pass --autonomous for a drive-it run.')
    if C.get('canary', True) and '--skip-canary' not in ARGS and have('gates', 'canary.py'):
        rc = subprocess.run([sys.executable, os.path.join(HERE, 'gates', 'canary.py'), SCENE.split('?')[0], '--dur', '%.3f' % (TOTAL + TAIL),
                             '--workers', str(C.get('workers', 3)), '--fps', str(FPS)], cwd=HERE).returncode
        if rc:
            raise SystemExit('REFUSING: the determinism canary found a seam (out/canary/); render with --skip-canary only if you accept it')


# ---------------------------------------------------------------- 1. picture
def render():
    print('[1/7] render picture (%.2f s)' % (TOTAL + TAIL))
    scene = SCENE
    if (C.get('captions') or {}).get('burn') is False:
        scene += ('&' if '?' in scene else '?') + 'nocap'
    run(['node', os.path.join(HERE, 'render_frames.js'), scene, SEG, '%.3f' % (TOTAL + TAIL), str(FPS), '96', str(C.get('workers', 3))], cwd=HERE)


# ---------------------------------------------------------------- 2. audio
def bed_plan():
    """Bed in-point and fade-out end from out/beats_<name>.json (film.json: beats, bed_offset 'auto'|s, bed_anchor, bed_end)."""
    off = 0.0 if C.get('bed_offset') == 'auto' else float(C.get('bed_offset') or 0.0)
    fade_end = TOTAL + TAIL
    bp = os.path.join(HERE, C['beats']) if C.get('beats') else None
    if not (BG and bp and os.path.exists(bp)):
        return off, fade_end
    G = json.load(open(bp, encoding='utf-8'))
    ph = json.load(open(PHASES_JSON, encoding='utf-8')); wd = json.load(open(WORDS_JSON, encoding='utf-8'))
    P = {p['name']: p['start'] for p in ph['phases']}
    norm = lambda s: re.sub(r'[^a-z0-9]', '', str(s).lower())
    if C.get('bed_offset') == 'auto':
        pname, word = (list(C.get('bed_anchor') or [ph['phases'][0]['name'], None]) + [None])[:2]
        anchor = P[pname] + next((w['t'] for w in wd.get(pname, []) if word is None or norm(w['w']) == norm(word)), 0.0)
        plan_ = BG.bed_in_point(G, anchor, 1.5, TOTAL + TAIL)
        off = plan_['offset']
        print('      bed in-point %.2f s -> downbeat on %.2f s (%s)' % (off, anchor, plan_['reason']))
    if C.get('bed_end', 'tail') == 'phrase':
        last = max(p['start'] + max([w['t'] for w in wd.get(p['name'], [])] or [p['dur']]) for p in ph['phases'])
        be = BG.bed_end(G, last, off)
        fade_end = min(TOTAL + TAIL, be['fade_end'])
        print('      bed fade completes at %.2f s (%s)' % (fade_end, be['reason']))
    return off, fade_end


def mixdown(dest, pre_db=0.0, limit_db=None):
    """Narration at unity (pan upmix: mono -> stereo without the 3 dB aformat loses), the bed ducked under speech —
    band-limited (carve) when audio/carve_bed.py is present, full-band sidechain otherwise — and optional SFX.
    pre_db lifts the whole mix; limit_db caps sample peaks so the master can stay LINEAR. Stems on the RAW pass."""
    T = TOTAL + TAIL
    stems = dest == RAW and CB is not None
    upmix = CB.VO_UPMIX if CB else 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'
    vchain = (VP.preset_chain(C['voice_preset'], C.get('voice_evenness'), C.get('voice_deess', False), C.get('voice_jobs', [])) + ',') if (VP and C.get('voice_preset')) else ''
    ins = ['-i', VO]
    fc = ['[0:a]%s%s,apad=whole_dur=%.3f,asplit=%d[v][vsc]%s' % (vchain, upmix, T, 3 if stems else 2, '[vst]' if stems else '')]
    mixes = ['[v]']; n_in = 1
    if BED:
        off, fade_end = bed_plan()
        fi, fo = (BG.clamp_fades(float(C.get('bed_fade_in', 1.5)), float(C.get('bed_fade_out', 3.0)), fade_end) if BG
                  else (float(C.get('bed_fade_in', 1.5)), float(C.get('bed_fade_out', 3.0))))
        ins += ['-ss', '%.3f' % off, '-stream_loop', '-1', '-i', BED]
        fmt = CB.STEREO_FMT if CB else 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'
        fc.append('[%d:a]%s,atrim=0:%.3f,asetpts=N/SR/TB,volume=%.1fdB,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f[bed]'
                  % (n_in, fmt, T, BED_DB, fi, max(0.0, fade_end - fo), fo))
        n_in += 1
        if CB:
            mode = {True: 'dynamic', False: 'full'}.get(C.get('carve', True), C.get('carve'))
            gain_label = None
            if mode == 'envelope':
                env = CB.envelope_for_film(PHASES_JSON, WORDS_JSON, os.path.join(OUT, 'duck_%s.wav' % NAME), T, float(C.get('duck_db', -10.0)))
                ins += ['-i', env['wav']]; gain_label = '%d:a' % n_in; n_in += 1
            fc.append(CB.carve_fragment(VO, 'bed', 'vsc', 'bedc', mode=mode, gain_label=gain_label,
                                        json_out=os.path.join(OUT, 'carve_%s.json' % NAME), verbose=stems, **C.get('carve_opts', {})))
            fc.append('[bedc]asplit=2[b][bst]' if stems else '[bedc]anull[b]')
        else:
            fc.append('[bed][vsc]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=500[b]')
        mixes.append('[b]')
    else:
        fc.append('[vsc]anullsink')
    if SFX:
        ins += ['-i', SFX]
        fc.append('[%d:a]%s,volume=%.1fdB[k]' % (n_in, upmix, C.get('sfx_db', -5.0))); n_in += 1
        mixes.append('[k]')
    chain = ';'.join(fc) + ';' + ''.join(mixes) + 'amix=inputs=%d:duration=first:normalize=0:dropout_transition=0[m];[m]volume=%.2fdB' % (len(mixes), pre_db)
    if limit_db is not None:
        chain += ',alimiter=limit=%.5f:attack=5:release=80:level=false' % (10 ** (limit_db / 20.0))
    chain += ',atrim=0:%.3f,asetpts=N/SR/TB[out]' % T
    outs = ['-map', '[out]', '-c:a', 'pcm_s24le', '-ar', '48000', dest]
    if stems:
        outs += ['-map', '[vst]', '-c:a', 'pcm_s24le', STEM_VO] + (['-map', '[bst]', '-c:a', 'pcm_s24le', STEM_BED] if BED else [])
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + ins + ['-filter_complex', chain] + outs)


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
    print('[2/7] mix narration%s%s' % (' + carved bed' if BED else '', ' + sfx' if SFX else ''))
    mixdown(RAW)
    raw_i = float(measure(RAW)['input_i'])
    pre, ceil = (LUFS_I + 0.45) - raw_i, LUFS_TP - 0.8
    print('      raw %.2f LUFS -> pre-gain %+.2f dB, limiter %.2f dBFS' % (raw_i, pre, ceil))
    mixdown(MIX, pre_db=pre, limit_db=ceil)


def master():
    print('[3/7] master (two-pass linear loudnorm)')
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


def tool_versions():
    def ver(cmd, rx):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
            m = re.search(rx, out); return m.group(1) if m else '?'
        except Exception:
            return '?'
    return ver(['ffmpeg', '-version'], r'ffmpeg version (\S+)'), ver(['node', '--version'], r'v?(\S+)')


def mux():
    print('[4/7] mux')
    ffv, nodev = tool_versions()
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', SEG, '-i', MASTER, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
         '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-ac', '2', '-shortest',
         '-metadata', 'comment=FDE Demo Builder 4 · ffmpeg %s · node %s · %d fps' % (ffv, nodev, FPS),
         '-movflags', '+faststart', PRE])


# ---------------------------------------------------------------- 5. captions
def captions():
    print('[5/7] captions')
    gp = os.path.join(OUT, 'caption_groups.json')
    if os.path.exists(gp) and have('tools', 'captions_srt.py'):
        cmd = [sys.executable, os.path.join(HERE, 'tools', 'captions_srt.py'), gp, SRT]
        if (C.get('captions') or {}).get('vtt'):
            cmd += ['--vtt', os.path.splitext(FILM)[0] + '.vtt']
        run(cmd)
        return
    sys.path.insert(0, HERE)
    import vo_script
    txt = {p['name']: ' '.join(p['text'].split()) for p in vo_script.SCENES[NAME]['phases']}
    ph = json.load(open(PHASES_JSON))['phases']
    ts = lambda x: '%02d:%02d:%02d,%03d' % (int(x // 3600), int(x % 3600 // 60), int(x % 60), round((x - int(x)) * 1000) % 1000)
    out = []
    for i, p in enumerate(ph):
        end = min(p['start'] + p['dur'] + 0.35, ph[i + 1]['start'] if i + 1 < len(ph) else TOTAL + TAIL)
        out.append('%d\n%s --> %s\n%s\n' % (i + 1, ts(p['start']), ts(end), txt.get(p['name'], '')))
    open(SRT, 'w', encoding='utf-8').write('\n'.join(out))


# ---------------------------------------------------------------- 6. credit (mandatory)
def credit():
    print('[6/7] credit (mandatory)')
    sys.path.insert(0, HERE)
    import credit as CR
    CR.stamp(PRE, FILM)
    if not CR.check(FILM):
        raise SystemExit('REFUSING: the FDE Demo Builder credit is not legible on the end screen.')
    os.remove(PRE)


# ---------------------------------------------------------------- 7. after the film
def after():
    print('[7/7] ledger, exports, storyboard truth pass')
    lp = os.path.join(HERE, C.get('ledger', 'media.jsonl'))
    if os.path.exists(lp) and have('tools', 'ledger.py'):
        import ledger as LG
        L = LG.Ledger(HERE, C.get('ledger', 'media.jsonl'))
        film_rel = os.path.relpath(FILM, HERE).replace('\\', '/')
        for rel in filter(None, [C.get('bed'), C.get('sfx'), 'vo_%s.mp3' % NAME]):
            if os.path.exists(os.path.join(HERE, rel)):
                L.add(rel); L.mark_used(rel.replace('\\', '/'), film_rel)
        print('      ledger: %d assets, %d licence UNKNOWN' % (len(L.current()), len(L.unknown())))
    if C.get('exports') and have('tools', 'export.py'):
        import export as EX
        EX.Exporter(HERE).run(list(C['exports']))
    sb = os.path.join(HERE, C.get('storyboard', 'STORYBOARD.md'))
    if os.path.exists(sb) and have('tools', 'storyboard.py'):
        subprocess.run([sys.executable, os.path.join(HERE, 'tools', 'storyboard.py'), 'sheet', sb, '--truth', '--film', FILM], cwd=HERE)
        print('      storyboard truth pass -> out/storyboard.html')


if __name__ == '__main__':
    plan()
    if '--skip-render' not in ARGS:
        preflight()
        render()
    mix(); master(); mux(); captions(); credit(); after()
    print('\nDONE  ' + FILM)
