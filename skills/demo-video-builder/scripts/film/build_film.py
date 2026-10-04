# -*- coding: utf-8 -*-
"""build_film.py — v5: plan → preflight → render → mix → master → mux → captions → MANDATORY credit → ledger → exports.

    python build_film.py [--skip-render] [--skip-canary] [--autonomous]        (reads film.json; see film.example.json)

  0. plan + preflight   (v5.1: every build is a take — out/takes.jsonl + .history/takes/<n>/, tools/takes.py)
       skin                    film.json "skin": skins/<name>.json → tools/skin_apply.py writes scenes/skin_data.js (window.SKIN +
                               the tokens as CSS variables on :root at load) and rewrites design.md's tokens; the head-fade plate
                               is the skin's `black` token (light skins open from their own paper, never from a dark flash)
       export_timeline.js      cuts, seams (seams.json → scenes/seams_data.js), shots, sync points → out/timeline.json
       captions export         scenes/captions.json → out/caption_groups.json + scenes/captions_data.js (lib/captions.js)
       chapters                film.json "chapters": tools/chapters.py from STORYBOARD.md + seams.json + the narration →
                               out/chapters.vtt, chapters_youtube.txt, timeline.md, chapters.json (--merge when the film is < 60 s)
       doctor --fast           ffmpeg / node / Chrome / edge-tts / fonts / disk
       lint_scene              static determinism + seekability scan (errors block the render; "lint": "strict" blocks warnings)
       camera ladder           node scenes/lib/camera.js --curves (pose ladder lint + zoom budget → out/camera_report.json)
       storyboard check        STORYBOARD.md must be locked and add up to the narration (--autonomous for a drive-it run)
       canary                  render a few frames twice and compare (determinism); --skip-canary to accept a known seam
  1. render   scenes/film.html deterministically (render_frames.js): 1920x1080, 30 fps CFR, frame 0 = clock 0;
              the first frame is compared with the skin's head-fade plate (warn-only)
  2. mix      narration (pan-upmixed, optional voice preset, optional "fx" voice chain) + bed (optional "fx" bed chain, carved
              around the voice band, optional "bed_env" breathe/swell gain curve) + SFX: a hand-made stem ("sfx": "path.wav")
              or "sfx": {"auto": true} → audio/sfx_synth.py (once) + audio/sfx_place.py from out/timeline.json + sync.json,
              word-safe, rendered as out/sfx_<name>.wav with the bus gain already in it (optional "fx" sfx chain);
              writes out/stem_vo_<name>.wav / out/stem_bed_<name>.wav for the audio gates
  3. master   two-pass LINEAR loudnorm to -16 LUFS / TP -1.5; refuses to ship if loudnorm falls back to dynamic
  4. mux      video copy + AAC 256k, faststart, provenance in the container comment (no paths, no user names)
  5. captions out/<film>.srt (+ .vtt) from the same caption groups the lane burns in — with "captions": {"ass": true} the
              .ass sidecar with per-word timing, .srt and .vtt come from ONE tools/captions_ass.py call (+ overrides)
  6. credit   credit.py stamps "Crafted with FDE Demo Builder · by Ahmed Awan" on the end screen and verifies it.
              This step is not optional: there is no flag to skip it, and QA fails a video without it.
  7. after    media ledger marks what the build used; film.json "exports" derive presets (tools/export.py: chapters, .ass,
              burn_ass, reflow crops ride along); the storyboard truth pass redraws out/storyboard.html from the real frames.

film.json keys added in v5 (every one opt-in; a v4 film.json builds exactly as before):
    "skin": "skins/harbor.json", "skin_design": true, "skin_strict": false
    "captions": {..., "ass": true, "overrides": "captions_overrides.json"}
    "chapters": true | {"merge": "auto"|true|false, "min": 10, "max_title": 40, "snap": 0.75}
    "sfx": {"auto": true, "sync": "sync.json", "db": -14, "guard": 0.15, "nudge": 0.12, "dir": "audio/sfx"}
    "fx": {"buses": {"voice": {"preset": "voice-booth"}, "bed": {"preset": "bed-under-voice"}, "sfx": {"preset": "sfx-tight"}}}
    "bed_env": true | {"breathe": -3, "swell": "climax"|<seconds>|null, "swell_dur": 2.0, "max_slope": 6}
Order inside the voice bus: voice_preset first, then the "fx" chain (level_match in the gates still sees the raw stems).
The bed chain runs BEFORE the carve (its static presence dip is the bias the carve works under); the gain curve multiplies
the carved bed. Templates with everything switched on: templates/films/<booth-trailer|customer-story|feature-walkthrough>.

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
SFX_CFG = C.get('sfx')
SFX = os.path.join(HERE, SFX_CFG) if isinstance(SFX_CFG, str) and SFX_CFG else None      # v4: a hand-made stem; v5 dict → sfx_auto()
SFX_DB = float(C.get('sfx_db', -5.0))
BED_DB = float(C.get('bed_db', -12.0))             # v4 default -12 (was -9): the pan upmix restores 3 dB of voice
LUFS_I, LUFS_TP, LUFS_LRA = -16.0, -1.5, 11.0
LIMITER_LATENCY_S = 239 / 48000.0                   # alimiter attack=5 ms look-ahead = 239 samples of delay at 48 kHz (v5.1, measured)
TAIL = 3.6                                          # music/room tail after the last word (TAIL_S): the closing card HOLDS while the credit lands —
                                                    # credit.py's 4 s window starts at END + TAIL - 4 = END - 0.4, after the lockup's rule has finished
                                                    # (was 1.2: the credit faded in while the last title words were still arriving)
ARGS = sys.argv[1:]
TIMING_DATA = os.path.join(HERE, 'scenes', 'timing_%s_data.js' % NAME)
SHOTS_JS = os.path.join(HERE, 'scenes', 'shots.js')
SKIN = C.get('skin')
SKIN_INFO = None                                    # tools/skin_apply.py report (head_fade, css_vars …) once the skin is applied
FX = (C.get('fx') or {}).get('buses') if isinstance(C.get('fx'), dict) else None
BED_ENV = None                                      # out/bedenv_<name>.wav once audio/envelope.py has written the gain curve

sys.path.insert(0, os.path.join(HERE, 'audio')); sys.path.insert(0, os.path.join(HERE, 'tools'))
try:
    import carve_bed as CB, voice_presets as VP, beat_grid as BG
except ImportError:                                 # a v3 project without the audio/ folder keeps the v3 graph
    CB = VP = BG = None
try:
    import fx_chain as FXC
except ImportError:
    FXC = None


def run(cmd, **kw):
    print('  $', ' '.join(str(c) for c in cmd[:8]), '...' if len(cmd) > 8 else '')
    return subprocess.run(cmd, check=True, **kw)


RECEIPT = {}                                        # the renderer's last JSON line (frames, workers, gl, gl_renderer, wall_s) → the take ledger
T_START = None


def run_receipt(cmd, **kw):
    """run() that streams the child's output and keeps its last JSON line as the render receipt."""
    print('  $', ' '.join(str(c) for c in cmd[:8]), '...' if len(cmd) > 8 else '')
    pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', **kw)
    last = None
    for line in pr.stdout:
        sys.stdout.write(line)
        if line.lstrip().startswith('{') and '"frames"' in line:
            last = line.strip()
    rc = pr.wait()
    if last:
        try:
            RECEIPT.update(json.loads(last))
        except ValueError:
            pass
    if rc:
        raise subprocess.CalledProcessError(rc, cmd)


def have(*rel):
    return os.path.exists(os.path.join(HERE, *rel))


def lesson(step):
    """v5.1: the one lesson a stage was built on, printed under its header (tools/lessons.py)."""
    try:
        import lessons as LS
        ln = LS.line(step)
        if ln:
            print(ln)
    except Exception:
        pass


def hex_luma_y(hexc):
    """Full-range BT.601 luma of a #RRGGBB plate — what ffmpeg's format=gray reports for a flat frame of that colour
    (measured: the #05161C plate reads 16-17, the #F4F1EA paper ~241)."""
    h = hexc.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


# ---------------------------------------------------------------- 0. plan + preflight
def skin():
    """film.json "skin" → scenes/skin_data.js (+ design.md tokens). The scene must load it: <script src="skin_data.js"></script>."""
    global SKIN_INFO
    if not SKIN:
        return
    if not have('tools', 'skin_apply.py'):
        raise SystemExit('REFUSING: film.json names a skin but tools/skin_apply.py is missing')
    import skin_apply as SK
    SKIN_INFO = SK.apply(HERE, SKIN, design=C.get('skin_design', True))
    print('      skin %s (%s ground, motion %s, captions %s) -> %s · head fade plate %s%s' % (
        SKIN_INFO['name'], SKIN_INFO['background'], SKIN_INFO['motion'], SKIN_INFO['captions'], SKIN_INFO['out'], SKIN_INFO['head_fade'],
        ('; design.md: ' + ', '.join(SKIN_INFO['design_changed'])) if SKIN_INFO['design_changed'] else ''))
    for f in SKIN_INFO['findings']:
        print('      SKIN FINDING  ' + f)
    if SKIN_INFO['findings'] and C.get('skin_strict'):
        raise SystemExit('REFUSING: skin check findings (python tools/brand_kit.py check %s)' % SKIN)
    scene_path = os.path.join(HERE, SCENE.split('?')[0])
    if os.path.exists(scene_path) and 'skin_data.js' not in open(scene_path, encoding='utf-8', errors='replace').read():
        print('      WARN  %s does not load skin_data.js — add <script src="skin_data.js"></script> after its <style> block, or the skin never reaches the DOM' % SCENE)


def chapters():
    """film.json "chapters" → tools/chapters.py (findings are warnings; the YouTube rules are the gate's call)."""
    cfg = C.get('chapters')
    if not cfg or not have('tools', 'chapters.py'):
        return
    cfg = cfg if isinstance(cfg, dict) else {}
    sb = os.path.join(HERE, C.get('storyboard', 'STORYBOARD.md'))
    if not os.path.exists(sb):
        print('      chapters: no %s — skipped' % os.path.basename(sb)); return
    merge = cfg.get('merge', 'auto')
    merge = (TOTAL < 60.0) if merge == 'auto' else bool(merge)
    cmd = [sys.executable, os.path.join(HERE, 'tools', 'chapters.py'), sb, '--phases', PHASES_JSON, '--out', OUT]
    seams = os.path.join(HERE, cfg.get('seams', 'seams.json'))
    if os.path.exists(seams):
        cmd += ['--seams', seams]
    for key, flag in (('min', '--min'), ('max_title', '--max-title'), ('snap', '--snap')):
        if key in cfg:
            cmd += [flag, str(cfg[key])]
    if merge:
        cmd.append('--merge')
    rc = subprocess.run(cmd, cwd=HERE).returncode
    if rc == 2:
        raise SystemExit('REFUSING: tools/chapters.py could not read the storyboard (usage error above)')
    if rc:
        print('      WARN  chapters: findings above — add/adjust `- chapter:` bullets in STORYBOARD.md%s' % ('' if merge else ', or set "chapters": {"merge": true}'))
    else:
        print('      chapters -> out/chapters.vtt, chapters_youtube.txt, timeline.md%s' % (' (--merge: film under 60 s)' if merge and TOTAL < 60.0 else ''))


def plan():
    print('[0/7] plan: skin, timeline, seams, captions, chapters'); lesson('seams')
    skin()
    if have('export_timeline.js'):
        run(['node', os.path.join(HERE, 'export_timeline.js'), TIMING_DATA, SHOTS_JS], cwd=HERE)
    cap = C.get('captions') or {}
    if cap.get('config') and have(cap['config']) and have('scenes', 'lib', 'captions.js'):
        def captions_cmd(with_luma):
            cmd = ['node', os.path.join(HERE, 'scenes', 'lib', 'captions.js'), TIMING_DATA, os.path.join(HERE, cap['config']),
                   '--out', os.path.join(OUT, 'caption_groups.json'), '--js', os.path.join(HERE, 'scenes', 'captions_data.js')]
            if with_luma and cap.get('luma') and have(cap['luma']):
                cmd += ['--luma', os.path.join(HERE, cap['luma'])]
            return cmd
        run(captions_cmd(True), cwd=HERE)                       # groups first: the probe crops the lane at every group's mid-point
        if cap.get('luma') and not have(cap['luma']) and have('gates', 'overlay_gate.py') and '--skip-render' not in ARGS:
            # the lane picks dark ink on bright screens: probe the scene once (captions off) for per-phase luma, THEN rebuild the
            # groups with it — probing before caption_groups.json exists finds no groups and never writes the luma file
            subprocess.run([sys.executable, os.path.join(HERE, 'gates', 'overlay_gate.py'), '--probe', SCENE.split('?')[0]], cwd=HERE)
            if have(cap['luma']):
                run(captions_cmd(True), cwd=HERE)
    chapters()


def preflight():
    print('[0/7] preflight: doctor, lint, camera ladder, storyboard, canary'); lesson('lock')
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
def head_fade_check():
    """Frame 0 must sit on the skin's plate (var(--black) in the scene): a light skin opens from its paper, never from a dark flash."""
    plate = (SKIN_INFO or {}).get('head_fade') or '#05161C'
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', SEG, '-frames:v', '1', '-vf', 'scale=32:18,format=gray', '-f', 'rawvideo', '-'],
                       capture_output=True)
    if not r.stdout:
        return None
    luma, want = sum(r.stdout) / float(len(r.stdout)), hex_luma_y(plate)
    ok = abs(luma - want) < 40
    print('      head fade: frame 0 luma %.0f vs plate %s (Y %.0f) — %s' % (luma, plate, want, 'OK' if ok else
          'MISMATCH: does the scene load skin_data.js and does #black read var(--black)?'))
    return ok


def render():
    print('[1/7] render picture (%.2f s)' % (TOTAL + TAIL)); lesson('build')
    scene = SCENE
    if (C.get('captions') or {}).get('burn') is False:
        scene += ('&' if '?' in scene else '?') + 'nocap'
    run_receipt(['node', os.path.join(HERE, 'render_frames.js'), scene, SEG, '%.3f' % (TOTAL + TAIL), str(FPS), '96', str(C.get('workers', 3))], cwd=HERE)
    head_fade_check()


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


def sfx_auto():
    """film.json "sfx": {"auto": true}: synthesize the set once (audio/sfx/), place cues from out/timeline.json (seams + block sync
    points) and sync.json (hand-authored flash/stamp/climax; "force": true skips the word guard for that point), render the stem."""
    global SFX, SFX_DB
    if not (isinstance(SFX_CFG, dict) and SFX_CFG.get('auto')):
        return None
    if not (have('audio', 'sfx_place.py') and have('audio', 'sfx_synth.py')):
        raise SystemExit('REFUSING: "sfx": {"auto": true} needs audio/sfx_place.py and audio/sfx_synth.py')
    import sfx_place as SP
    sfx_dir = os.path.join(HERE, SFX_CFG.get('dir', 'audio/sfx'))
    tl = os.path.join(OUT, 'timeline.json'); sync = os.path.join(HERE, SFX_CFG.get('sync', 'sync.json'))
    beats = os.path.join(HERE, C['beats']) if C.get('beats') and have(C['beats']) else None
    plan_ = SP.plan_from_files(timeline=tl if os.path.exists(tl) else None, sync=sync if os.path.exists(sync) else None, beats=beats,
                               words=WORDS_JSON if os.path.exists(WORDS_JSON) else None, phases=PHASES_JSON, vo=VO if os.path.exists(VO) else None,
                               total=TOTAL + TAIL, sfx_dir=sfx_dir, sfx_db=float(SFX_CFG.get('db', SP.SFX_BUS_DB)),
                               guard=float(SFX_CFG.get('guard', SP.GUARD_S)), nudge=float(SFX_CFG.get('nudge', SP.NUDGE_S)))
    stem = os.path.join(OUT, 'sfx_%s.wav' % NAME)
    SP.render(plan_, sfx_dir, stem)
    plan_['stem'] = os.path.relpath(stem, HERE).replace('\\', '/'); plan_['sfx_dir'] = os.path.relpath(sfx_dir, HERE).replace('\\', '/')
    json.dump(plan_, open(os.path.join(OUT, 'cues_%s.json' % NAME), 'w', encoding='utf-8'), indent=1)
    forced = [c for c in plan_['cues'] if c.get('forced')]
    print('      sfx: %d cues placed (%d dropped by the word guard, %d demoted, %d forced), %d words guarded -> out/sfx_%s.wav' % (
        len(plan_['cues']), len(plan_['dropped']), len(plan_['demoted']), len(forced), plan_['words_guarded'], NAME))
    for d in plan_['dropped']:
        print('        dropped %s: %s' % (d['id'], d['reason']))
    SFX, SFX_DB = stem, 0.0                           # the bus gain is already in the stem
    return plan_


def bed_env():
    """film.json "bed_env": the bed breathes −3 dB into every cut and swells under the riser — keyframes limited to ±6 dB/s,
    rendered by audio/envelope.py as a float32 gain WAV that multiplies the carved bed."""
    global BED_ENV
    cfg = C.get('bed_env')
    if not cfg or not BED:
        return None
    if not have('audio', 'envelope.py'):
        raise SystemExit('REFUSING: "bed_env" needs audio/envelope.py')
    import envelope as EV
    cfg = cfg if isinstance(cfg, dict) else {}
    T = TOTAL + TAIL
    lists, note = [], []
    depth = cfg.get('breathe', -3.0)
    tl = os.path.join(OUT, 'timeline.json')
    if depth is not None and os.path.exists(tl):
        cuts = [t for t in EV.seam_times_from(tl) if 0.0 < t < T]
        if cuts:
            lists.append(EV.breathe(cuts, float(depth))); note.append('breathe %.1f dB at %d cuts' % (float(depth), len(cuts)))
    sw = cfg.get('swell')
    if sw == 'climax':
        sw = None
        sync = os.path.join(HERE, SFX_CFG.get('sync', 'sync.json') if isinstance(SFX_CFG, dict) else 'sync.json')
        if os.path.exists(sync):
            pts = json.load(open(sync, encoding='utf-8'))
            pts = pts.get('points', pts if isinstance(pts, list) else [])
            cl = [float(p['t']) for p in pts if 't' in p and (str(p.get('kind', '')).lower() == 'climax' or str(p.get('id', '')).endswith(':climax'))]
            if cl:
                sw = max(cl)
    if isinstance(sw, (int, float)) and 0.0 < float(sw) <= T:
        lists.append(EV.swell(float(sw), float(cfg.get('swell_dur', EV.SWELL['dur'])))); note.append('swell to %.2f s' % float(sw))
    if not lists:
        print('      bed envelope: nothing to automate (no cuts in out/timeline.json, no climax point)'); return None
    keys = EV.merge(*lists) if len(lists) > 1 else lists[0]
    rep = EV.resolve(keys, T, float(cfg.get('max_slope', EV.MAX_SLOPE_DB_S)))
    wav = os.path.join(OUT, 'bedenv_%s.wav' % NAME)
    EV.to_wav(rep['keyframes'], T, wav)
    json.dump(dict(rep, wav=os.path.relpath(wav, HERE).replace('\\', '/')), open(os.path.join(OUT, 'env_%s.json' % NAME), 'w', encoding='utf-8'), indent=1)
    for w in rep['warnings']:
        print('      WARN  envelope: ' + w)
    print('      bed envelope: %s; %d keyframes, %.1f .. %.1f dB -> out/bedenv_%s.wav' % ('; '.join(note), len(rep['keyframes']), rep['min_db'], rep['max_db'], NAME))
    BED_ENV = wav
    return rep


def fx_frag(bus, inp, out):
    """(preset, fragment) for a bus declared in film.json "fx" {"buses": {bus: {preset, chain}}}; None when the bus has no chain."""
    if not (FXC and isinstance(FX, dict) and bus in FX):
        return None
    preset, chain = FXC.resolve_chain({'buses': FX}, bus, None)
    if not chain:
        return None
    return preset, FXC.chain_fragment(chain, bus, inp, out)


def mixdown(dest, pre_db=0.0, limit_db=None):
    """Narration at unity (pan upmix: mono -> stereo without the 3 dB aformat loses), the bed ducked under speech —
    band-limited (carve) when audio/carve_bed.py is present, full-band sidechain otherwise — and optional SFX.
    Declared bus chains ("fx") splice in per bus; the bed gain curve ("bed_env") multiplies the carved bed.
    pre_db lifts the whole mix; limit_db caps sample peaks so the master can stay LINEAR. Stems on the RAW pass."""
    T = TOTAL + TAIL
    stems = dest == RAW and CB is not None
    upmix = CB.VO_UPMIX if CB else 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'
    stereo_fmt = CB.STEREO_FMT if CB else 'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo'
    vchain = (VP.preset_chain(C['voice_preset'], C.get('voice_evenness'), C.get('voice_deess', False), C.get('voice_jobs', [])) + ',') if (VP and C.get('voice_preset')) else ''
    ins = ['-i', VO]
    split = 'apad=whole_dur=%.3f,asplit=%d[v][vsc]%s' % (T, 3 if stems else 2, '[vst]' if stems else '')
    vfx = fx_frag('voice', 'v0', 'v1')
    if vfx:                                           # voice preset first, then the declared chain, then the split;
        # the voice STEM is tapped before the chain so the audio gates (mono upmix, level match) still see the raw upmix
        fc = ['[0:a]%s%s,apad=whole_dur=%.3f,asplit=%d[v0]%s' % (vchain, upmix, T, 2 if stems else 1, '[vst]' if stems else ''), vfx[1],
              '[v1]asplit=2[v][vsc]']
    else:
        fc = ['[0:a]%s%s,%s' % (vchain, upmix, split)]
    mixes = ['[v]']; n_in = 1
    if BED:
        off, fade_end = bed_plan()
        fi, fo = (BG.clamp_fades(float(C.get('bed_fade_in', 1.5)), float(C.get('bed_fade_out', 3.0)), fade_end) if BG
                  else (float(C.get('bed_fade_in', 1.5)), float(C.get('bed_fade_out', 3.0))))
        ins += ['-ss', '%.3f' % off, '-stream_loop', '-1', '-i', BED]
        fc.append('[%d:a]%s,atrim=0:%.3f,asetpts=N/SR/TB,volume=%.1fdB,afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f[bed]'
                  % (n_in, stereo_fmt, T, BED_DB, fi, max(0.0, fade_end - fo), fo))
        n_in += 1
        bed_lbl = 'bed'
        bfx = fx_frag('bed', 'bed', 'bedf')
        if bfx:                                       # the bed chain runs before the carve: its static dip is the bias the carve works under
            fc.append(bfx[1]); bed_lbl = 'bedf'
        if CB:
            mode = {True: 'dynamic', False: 'full'}.get(C.get('carve', True), C.get('carve'))
            gain_label = None
            if mode == 'envelope':
                env = CB.envelope_for_film(PHASES_JSON, WORDS_JSON, os.path.join(OUT, 'duck_%s.wav' % NAME), T, float(C.get('duck_db', -10.0)))
                ins += ['-i', env['wav']]; gain_label = '%d:a' % n_in; n_in += 1
            # the carve ranks the bed's own bands against the voice at the mix gain (a pink reference stands in when no bed is given)
            fc.append(CB.carve_fragment(VO, bed_lbl, 'vsc', 'bedc', mode=mode, gain_label=gain_label,
                                        json_out=os.path.join(OUT, 'carve_%s.json' % NAME), verbose=stems,
                                        bed_path=BED, bed_gain_db=BED_DB, **C.get('carve_opts', {})))
            carved = 'bedc'
            if BED_ENV:                               # the gain curve (mono float32) rides both channels of the carved bed
                ins += ['-i', BED_ENV]
                fc.append('[%d:a]aformat=sample_fmts=fltp:sample_rates=48000,pan=stereo|c0=c0|c1=c0,apad=whole_dur=%.3f,atrim=0:%.3f[env]' % (n_in, T, T)); n_in += 1
                fc.append('[bedc][env]amultiply[bede]'); carved = 'bede'
            fc.append('[%s]asplit=2[b][bst]' % carved if stems else '[%s]anull[b]' % carved)
        else:
            # both legs re-framed to the same sample count first (carve_bed.SC_ALIGN): ffmpeg 8.1.1 can spin forever on a
            # sidechaincompress whose legs arrive in different frame sizes (0/12 hangs aligned vs 5/12 unaligned)
            sc_align = CB.SC_ALIGN if CB else 'asetnsamples=n=1024:p=0'
            fc.append('[%s]%s[bda]' % (bed_lbl, sc_align)); fc.append('[vsc]%s[vsca]' % sc_align)
            fc.append('[bda][vsca]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=500[b]')
        mixes.append('[b]')
    else:
        fc.append('[vsc]anullsink')
    if SFX:
        ins += ['-i', SFX]
        fmt = stereo_fmt if isinstance(SFX_CFG, dict) else upmix          # the synthesized stem is already stereo; a hand-made mono file is pan-upmixed
        kfx = fx_frag('sfx', 'k0', 'k')
        if kfx:
            fc.append('[%d:a]%s,volume=%.1fdB[k0]' % (n_in, fmt, SFX_DB)); fc.append(kfx[1])
        else:
            fc.append('[%d:a]%s,volume=%.1fdB[k]' % (n_in, fmt, SFX_DB))
        n_in += 1
        mixes.append('[k]')
    chain = ';'.join(fc) + ';' + ''.join(mixes) + 'amix=inputs=%d:duration=first:normalize=0:dropout_transition=0[m];[m]volume=%.2fdB' % (len(mixes), pre_db)
    if limit_db is not None:
        # the limiter's 5 ms attack is a look-ahead buffer: it delays the whole mix by 239 samples (measured by audio/cues_check.py on
        # the finished sample: every SFX read +4.98 ms late, peak 0.96). Trim that latency off the front so the clock stays the clock.
        chain += ',alimiter=limit=%.5f:attack=5:release=80:level=false,atrim=start=%.6f,asetpts=PTS-STARTPTS' % (10 ** (limit_db / 20.0), LIMITER_LATENCY_S)
    chain += ',atrim=0:%.3f,asetpts=N/SR/TB[out]' % T
    outs = ['-map', '[out]', '-c:a', 'pcm_s24le', '-ar', '48000', dest]
    if stems:
        outs += ['-map', '[vst]', '-c:a', 'pcm_s24le', STEM_VO] + (['-map', '[bst]', '-c:a', 'pcm_s24le', STEM_BED] if BED else [])
    if stems and FX:
        json.dump({'buses': {b: fx_frag(b, 'in', 'out')[0] for b in ('voice', 'bed', 'sfx') if fx_frag(b, 'in', 'out')}, 'filter_complex': chain},
                  open(os.path.join(OUT, 'fx_%s.json' % NAME), 'w', encoding='utf-8'), indent=1)
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
    sfx_auto(); bed_env()
    buses = [b for b in ('voice', 'bed', 'sfx') if fx_frag(b, 'in', 'out')]
    print('[2/7] mix narration%s%s%s%s' % (' + carved bed' if BED else '', ' + bed envelope' if BED_ENV else '',
                                            (' + sfx (%s)' % ('synthesized' if isinstance(SFX_CFG, dict) else 'stem')) if SFX else '',
                                            (' · fx chains: ' + ', '.join('%s=%s' % (b, fx_frag(b, 'in', 'out')[0]) for b in buses)) if buses else ''))
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
         '-metadata', 'comment=FDE Demo Builder 5 · ffmpeg %s · node %s · %d fps' % (ffv, nodev, FPS),
         '-movflags', '+faststart', PRE])


# ---------------------------------------------------------------- 5. captions
def captions():
    print('[5/7] captions')
    gp = os.path.join(OUT, 'caption_groups.json')
    cap = C.get('captions') or {}
    if os.path.exists(gp) and cap.get('ass') and have('tools', 'captions_ass.py'):
        # one call writes .ass (per-word \k timing) + .srt + .vtt from the groups the lane burns in — the sidecars cannot disagree
        ass = os.path.splitext(FILM)[0] + '.ass'
        cmd = [sys.executable, os.path.join(HERE, 'tools', 'captions_ass.py'), gp, '--out', ass, '--srt', SRT]
        if cap.get('vtt'):
            cmd += ['--vtt', os.path.splitext(FILM)[0] + '.vtt']
        ov = cap.get('overrides')
        if ov and have(ov):
            cmd += ['--overrides', os.path.join(HERE, ov)]
        rc = subprocess.run(cmd, cwd=HERE).returncode
        if rc == 2:
            raise SystemExit('REFUSING: tools/captions_ass.py could not read out/caption_groups.json')
        if rc:
            print('      WARN  captions_ass findings above (overrides) — the sidecars were still written')
        return
    if os.path.exists(gp) and have('tools', 'captions_srt.py'):
        cmd = [sys.executable, os.path.join(HERE, 'tools', 'captions_srt.py'), gp, SRT]
        if cap.get('vtt'):
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
    print('[7/7] ledger, exports, storyboard truth pass'); lesson('export')
    lp = os.path.join(HERE, C.get('ledger', 'media.jsonl'))
    if os.path.exists(lp) and have('tools', 'ledger.py'):
        import ledger as LG
        L = LG.Ledger(HERE, C.get('ledger', 'media.jsonl'))
        film_rel = os.path.relpath(FILM, HERE).replace('\\', '/')
        for rel in filter(None, [C.get('bed'), SFX_CFG if isinstance(SFX_CFG, str) else None, 'vo_%s.mp3' % NAME]):
            if os.path.exists(os.path.join(HERE, rel)):
                rel = rel.replace('\\', '/')
                if rel not in L.current():                 # a registered asset keeps its licence; add() would reset it to UNKNOWN
                    L.add(rel)
                L.mark_used(rel, film_rel)
        print('      ledger: %d assets, %d licence UNKNOWN' % (len(L.current()), len(L.unknown())))
    if C.get('exports') and have('tools', 'export.py'):
        import export as EX
        EX.Exporter(HERE).run(list(C['exports']))
    sb = os.path.join(HERE, C.get('storyboard', 'STORYBOARD.md'))
    if os.path.exists(sb) and have('tools', 'storyboard.py'):
        subprocess.run([sys.executable, os.path.join(HERE, 'tools', 'storyboard.py'), 'sheet', sb, '--truth', '--film', FILM], cwd=HERE)
        print('      storyboard truth pass -> out/storyboard.html')
    take_ledger()


def take_ledger():
    """v5.1: one record per build in out/takes.jsonl (tools/takes.py) and the take retained under .history/takes/<n>/ until the
    review is locked. The cost of a retake is the wall time; the scene hash says whether the picture changed."""
    if not have('tools', 'takes.py'):
        return
    import takes as TK
    import time
    wall = (time.time() - T_START) if T_START else float(RECEIPT.get('wall_s') or 0)
    rec = TK.record(HERE, wall, RECEIPT.get('frames') or int(round((TOTAL + TAIL) * FPS)), RECEIPT.get('workers') or C.get('workers', 3),
                    RECEIPT.get('gl'), RECEIPT.get('gl_renderer'), os.path.relpath(FILM, HERE).replace('\\', '/'), SCENE.split('?')[0], 'scenes/shots.js')
    kept = TK.keep(HERE)
    print('      take %d: %.0f s wall, %s frames, %s workers, gl %s, scene %s -> out/takes.jsonl%s' % (
        rec['take'], rec['wall_s'], rec['frames'], rec['workers'], rec.get('gl') or '?', rec['scene_md5'], (' · retained in %s' % os.path.relpath(kept, HERE)) if kept else ''))


if __name__ == '__main__':
    import time as _time
    T_START = _time.time()
    plan()
    if '--skip-render' not in ARGS:
        preflight()
        render()
    mix(); master(); mux(); captions(); credit(); after()
    print('\nDONE  ' + FILM)
