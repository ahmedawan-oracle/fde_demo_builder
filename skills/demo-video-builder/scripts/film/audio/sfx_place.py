# -*- coding: utf-8 -*-
"""sfx_place.py — place the synthesized SFX on the narration clock from seams / sync points / beats, word-safe.

    python audio/sfx_place.py --timeline out/timeline.json --words vo/film_words.json --phases vo/film_phases.json \\
                              --vo vo_film.mp3 --render out/sfx_film.wav --json out/cues_film.json
    python audio/sfx_place.py --sync sync.json --seams seams.json --total 93.3 --render out/sfx.wav
    python audio/sfx_place.py --selftest

What a cue is
  A cue is {t, kind, id, act} — a moment on the film clock that deserves a sound. Three sources feed it:
    seams     out/timeline.json "seams" (or seams.json with numeric cuts): every cut → kind "cut" (a whoosh),
              a cut whose `cause` is "impact" or "chapter" → kind "impact". The row's `act` is kept.
    sync      sync.json {"points":[{"t","kind","id","act"?,"snap"?,"sfx"?}]} written by the scene, or the
              "sync" list export_timeline.js already writes into out/timeline.json from window.__sync
              ([{id, t}] — the kind is the id's suffix after the last ':' , e.g. "kpi-revenue:land" → land,
              bare ids "land" / "send" / "answer-landed" are kinds themselves).
    beats     out/beats_<name>.json (beat_grid.py): a cue flagged "snap": true moves to the nearest beat when
              the grid is rhythmic. Nothing else is moved — words win, the bed moves.
  How a scene exports sync points: a block's draw() returns sync: [{id, t}] (BL.kpi → 'land', BL.chat → 'send',
  'stream', 'answer-landed'); the scene appends them to window.__sync with the block id as prefix
  (`window.__sync.push({id: 'kpi-revenue:land', t})`), or writes sync.json by hand for flash / stamp / climax.

kind → sound (sfx_synth.py set; `align` is the instant inside the file that lands on t)
    cut, zoom-through → whoosh (peak at 0.175 s on the cut; panned 0.25 toward the side new content enters)
    impact, chapter   → impact-low (≤ 1 per act: later ones in the same act are demoted to snap)
    flash             → snap            land, send, tick → tick           reveal → shimmer
    stamp, receipt, confirm, answer-landed → ui-confirm        key → key-0..5 rotating per keystroke
    climax            → riser, START = t − riser length so the riser ENDS exactly on the cue
    stream, none      → no sound.   A point may name its sound outright: "sfx": "shimmer".

The rules, measured
  level      every file peaks at −6 dBFS; the bus gain (--sfx-db, default −14) puts the peaks at −20 dBFS.
             Narration peaks sit around −6…−12 dBFS and the bed (−12 dB gain, carved) around −22 dBFS, so a
             transient reads clearly without ever competing with a word. Selftest: a 10 s −30 LUFS bed with
             seven cues under it rises 0.7 LU integrated — audible punctuation, not a second track.
  word guard no transient within GUARD = 0.15 s of a narration word onset whose peak is above −20 dBFS
             (--vo supplies the audio; without it every word counts). Calibrated on a real 3-minute booth
             narration: 150 ms speaking windows peak at −15 / −8 / −5 dBFS (p10 / p50 / p90) and 98 % of them
             are above −20 dBFS, so the floor only releases genuinely swallowed words. A colliding cue is nudged EARLIER in
             10 ms steps up to --nudge 0.12 s, then LATER up to 0.04 s — sound slightly early is forgiven,
             late barely (the broadcast sync tolerance is about −125 ms early / +45 ms late) — otherwise it
             is dropped and listed. Dense narration (a word every 0.4 s) leaves only ~0.1 s clear windows,
             so expect drops there: a cue that cannot be heard cleanly is better absent.
             The riser is a swell, not a transient, so only its landing is checked and it is never moved.
             A sync point may carry "force": true — the sound lands exactly where the author put it, the word
             guard is skipped for that cue alone (it is reported with forced: true and still counted by the
             sfx gate). Use it for the one landing that must be heard even in dense narration; never on cuts.
  stacking   two transients closer than 0.08 s mask each other: the lower-priority one is dropped
             (impact > snap > whoosh > ui-confirm > shimmer > tick > key; keys may cluster with keys).
  acts       at most one impact per act (act from the seam row or sync point; default "film").

Outputs
  --render   a stereo 24-bit 48 kHz stem of `total` seconds (numpy, sample-accurate, deterministic) that
             build_film.py mixes as its `sfx` input with sfx_db 0 (the bus gain is already applied).
  --json     {cues:[{t, start, kind, id, act, sfx, file, gain_db, pan, source, nudged_s (+ = moved earlier)}], dropped:[{…, reason}],
              demoted:[…], words_guarded, total, sfx_db, fragment, inputs}
  stdout     the equivalent ffmpeg filter_complex fragment ([k:a]…adelay…[sK]; […]amix…[sfx]) for graphs that
             prefer to mix the files directly (adelay is ms-precise; the rendered stem is sample-precise).
Exit codes: 0 ok, 1 cues were dropped or the inputs are inconsistent, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sfx_synth  # noqa: E402

SR = 48000
GUARD_S = 0.15
NUDGE_S = 0.12
NUDGE_LATE_S = 0.04
NUDGE_STEP_S = 0.01
STACK_S = 0.08
WORD_FLOOR_DBFS = -20.0
WORD_WINDOW_S = 0.15
SFX_BUS_DB = -14.0
WHOOSH_PAN = 0.25
DEFAULT_SFX_DIR = os.path.join(HERE, 'sfx')

KIND_SFX = {
    'cut': 'whoosh', 'zoom-through': 'whoosh', 'whoosh': 'whoosh',
    'impact': 'impact-low', 'chapter': 'impact-low',
    'flash': 'snap', 'snap': 'snap',
    'land': 'tick', 'send': 'tick', 'tick': 'tick',
    'reveal': 'shimmer', 'shimmer': 'shimmer',
    'stamp': 'ui-confirm', 'receipt': 'ui-confirm', 'confirm': 'ui-confirm', 'answer-landed': 'ui-confirm',
    'key': 'key', 'climax': 'riser', 'riser': 'riser',
    'stream': None, 'none': None,
}
PRIORITY = {'impact-low': 0, 'snap': 1, 'whoosh': 2, 'ui-confirm': 3, 'shimmer': 4, 'tick': 5, 'key': 6, 'riser': 7}
UNANCHORED_KINDS = ('flash', 'impact', 'chapter', 'climax', 'reveal')     # hand-placed moments with no word under them: these snap to the beat
IMPACT_KINDS = {'impact', 'chapter'}


def lin(db: float) -> float:
    return 10 ** (db / 20.0)


# ----------------------------------------------------------------------------------------------- inputs
def load_json(path: str | None):
    return json.load(open(path, encoding='utf-8')) if path else None


def cues_from_seams(rows: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(rows):
        if r.get('type', 'cut') != 'cut' or not isinstance(r.get('cut'), (int, float)) or r.get('sfx') is False:
            continue
        kind = 'impact' if str(r.get('cause', '')).lower() in IMPACT_KINDS else 'cut'
        entry = r.get('entry') or {}
        pan = -WHOOSH_PAN * float(entry.get('dir', 0)) if entry.get('axis') == 'x' and kind == 'cut' else 0.0
        out.append({'t': float(r['cut']), 'kind': kind, 'id': r.get('id', 'seam %d' % (i + 1)), 'act': r.get('act', 'film'),
                    'source': 'seams', 'pan': pan, 'sfx': r.get('sfx') if isinstance(r.get('sfx'), str) else None})
    return out


def kind_of(point: dict) -> str:
    if point.get('kind'):
        return str(point['kind']).lower()
    pid = str(point.get('id', ''))
    return pid.rsplit(':', 1)[-1].lower() if pid else 'none'


def cues_from_sync(points: list[dict], source: str = 'sync') -> list[dict]:
    out = []
    for i, p in enumerate(points):
        if 't' not in p:
            continue
        out.append({'t': float(p['t']), 'kind': kind_of(p), 'id': p.get('id', 'sync %d' % (i + 1)), 'act': p.get('act', 'film'),
                    'source': source, 'pan': float(p.get('pan', 0.0)), 'snap': (None if p.get('snap') is None else bool(p.get('snap'))),
                    'force': bool(p.get('force', False)),
                    'sfx': p.get('sfx') if isinstance(p.get('sfx'), str) else None})
    return out


def word_onsets(words, phases: dict | None, vo_path: str | None, floor_dbfs: float = WORD_FLOOR_DBFS) -> tuple[list[float], int]:
    """Word onsets on the film clock that the guard protects. words: {phase: [{t, w}]} relative to phases[].start,
    or a flat [{t}] list already on the clock. With `vo_path` only words whose WORD_WINDOW_S peak is above
    `floor_dbfs` count. Returns (sorted onsets, total words seen)."""
    ts: list[float] = []
    if isinstance(words, dict):
        starts = {p['name']: float(p['start']) for p in (phases or {}).get('phases', [])}
        for ph, ws in words.items():
            if ph not in starts:
                continue
            ts += [starts[ph] + float(w['t']) for w in ws]
    elif isinstance(words, list):
        ts = [float(w['t']) for w in words]
    n = len(ts)
    if vo_path and ts:
        x = decode(vo_path)
        keep = []
        for t in ts:
            a, b = int(t * SR), int((t + WORD_WINDOW_S) * SR)
            pk = float(np.max(np.abs(x[a:b]))) if b > a and a < x.size else 0.0
            if pk > 0 and 20 * math.log10(pk) > floor_dbfs:
                keep.append(t)
        ts = keep
    return sorted(ts), n


def decode(path: str, sr: int = SR) -> np.ndarray:
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError('decode failed for %s: %s' % (path, r.stderr.decode('utf-8', 'replace')[-300:]))
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)


def ensure_sfx(sfx_dir: str) -> dict:
    """Load manifest.json from sfx_dir, synthesizing the set there first if it is missing."""
    man = os.path.join(sfx_dir, 'manifest.json')
    if not os.path.exists(man):
        sfx_synth.build(sfx_dir)
    return json.load(open(man, encoding='utf-8'))


# ----------------------------------------------------------------------------------------------- placement
def place(cues: list[dict], onsets: list[float], manifest: dict, total: float, beats: dict | None = None,
          sfx_db: float = SFX_BUS_DB, guard: float = GUARD_S, nudge: float = NUDGE_S, stack: float = STACK_S) -> dict:
    """Resolve cues -> placed sounds. Pure function of its inputs (sorted, seeded, no clock)."""
    by = {r['name']: r for r in manifest['sfx']}
    n_keys = sum(1 for n in by if n.startswith('key-'))
    onsets_a = np.asarray(onsets, dtype=np.float64)
    placed, dropped, demoted = [], [], []

    # 1. kind -> sound, impacts <= 1 per act, optional beat snap
    seen_impact: set[str] = set()
    k_idx = 0
    work = []
    for c in sorted(cues, key=lambda c: (c['t'], c['id'])):
        c = dict(c)
        name = c.get('sfx') or KIND_SFX.get(c['kind'], None if c['kind'] not in by else c['kind'])
        if name is None:
            continue
        if c['kind'] in IMPACT_KINDS and not c.get('sfx'):
            if c['act'] in seen_impact:
                demoted.append(dict(c, **{'from': 'impact-low', 'to': 'snap', 'reason': 'second impact in act %r' % c['act']}))
                name = 'snap'
            else:
                seen_impact.add(c['act'])
        if name == 'key':
            name = 'key-%d' % (k_idx % max(1, n_keys)); k_idx += 1
        if name not in by:
            dropped.append(dict(c, reason='unknown sfx %r' % name)); continue
        # beat snap (v5.1): a cue asks for it (snap: true), or it is an UNANCHORED sync point — a flash, impact, chapter, climax
        # or reveal written by hand with no `snap` key — on a rhythmic grid: it moves to the nearest beat when that is closer than
        # half a beat. Block landings (land, send, stamp, receipt, confirm, keys, ticks) sit on a spoken word and never move;
        # seams sit on their cut and never move; "snap": false opts a point out. The word guard below still wins.
        unanchored = c.get('source') == 'sync' and c.get('snap') is None and not c.get('force') and c['kind'] in UNANCHORED_KINDS
        if (c.get('snap') is True or unanchored) and beats and beats.get('rhythmic') and beats.get('beats'):
            bt = np.asarray(sorted(float(b['t']) for b in beats['beats']))
            period = float(np.median(np.diff(bt))) if bt.size > 1 else 0.0
            near = float(bt[np.argmin(np.abs(bt - c['t']))])
            if c.get('snap') is True or (period and abs(near - c['t']) <= period / 2.0 + 1e-9):
                c['t_before_snap'] = c['t']; c['t'] = near; c['snapped'] = True
        c['sfx'] = name
        work.append(c)

    # 2. word guard (transients only; the riser is a swell), nudge earlier, else drop — unless the point is forced
    guarded = []
    for c in work:
        c['nudged_s'] = 0.0
        if c.get('force'):
            c['forced'] = True
            if onsets_a.size and c['sfx'] != 'riser':
                c['word_gap_s'] = round(float(np.min(np.abs(onsets_a - c['t']))), 3)
        elif onsets_a.size and c['sfx'] != 'riser':
            t = c['t']
            offsets = [-k * NUDGE_STEP_S for k in range(int(round(nudge / NUDGE_STEP_S)) + 1)] +                       [k * NUDGE_STEP_S for k in range(1, int(round(NUDGE_LATE_S / NUDGE_STEP_S)) + 1)]
            ok = False
            for off in offsets:
                tt = t + off
                if tt < 0:
                    continue
                if float(np.min(np.abs(onsets_a - tt))) >= guard - 1e-9:
                    c['nudged_s'] = round(-off, 3); c['t'] = round(tt, 4); ok = True; break
            if not ok:
                w = float(onsets_a[np.argmin(np.abs(onsets_a - t))])
                dropped.append(dict(c, reason='within %.2f s of word onset at %.3f (nudge %.2f s exhausted)' % (guard, w, nudge))); continue
        guarded.append(c)

    # 3. stacking: higher priority wins inside `stack`; keys may cluster with keys
    guarded.sort(key=lambda c: (PRIORITY.get(c['sfx'].split('-')[0] if c['sfx'].startswith('key') else c['sfx'], 9), c['t'], c['id']))
    kept: list[dict] = []
    for c in guarded:
        clash = next((k for k in kept if abs(k['t'] - c['t']) < stack and k['sfx'] != 'riser' and c['sfx'] != 'riser'
                      and not (k['sfx'].startswith('key') and c['sfx'].startswith('key'))), None)
        if clash:
            dropped.append(dict(c, reason='stacked on %s (%s) at %.3f' % (clash['id'], clash['sfx'], clash['t']))); continue
        kept.append(c)

    # 4. file, start time, gain
    for c in kept:
        r = by[c['sfx']]
        c['file'] = r['file']; c['align'] = r['align']; c['dur'] = r['dur']
        c['start'] = round(c['t'] - r['align'], 4)
        c['gain_db'] = round(sfx_db + float(c.get('gain_db', 0.0)), 2)
        c['pan'] = round(float(np.clip(c.get('pan', 0.0), -1, 1)), 3)
        if c['start'] + r['dur'] > total + 1e-6:
            c['note'] = 'tail trimmed at total'
    kept.sort(key=lambda c: (c['start'], c['id']))
    return {'cues': kept, 'dropped': sorted(dropped, key=lambda c: (c['t'], c['id'])), 'demoted': demoted,
            'words_guarded': len(onsets), 'total': total, 'sfx_db': sfx_db, 'guard_s': guard, 'nudge_s': nudge}


def render(plan: dict, sfx_dir: str, out_path: str) -> str:
    """Sum the placed cues into a stereo 24-bit stem of plan['total'] seconds (constant-power pan)."""
    n = int(round(plan['total'] * SR))
    buf = np.zeros((n, 2), dtype=np.float64)
    cache: dict[str, np.ndarray] = {}
    for c in plan['cues']:
        if c['file'] not in cache:
            x, sr = sfx_synth.read_wav(os.path.join(sfx_dir, c['file']))
            if sr != SR:
                raise ValueError('%s is %d Hz, expected %d' % (c['file'], sr, SR))
            cache[c['file']] = x[:, 0]
        x = cache[c['file']] * lin(c['gain_db'])
        s = int(round(c['start'] * SR))
        a, b = max(0, s), min(n, s + x.size)
        if b <= a:
            continue
        seg = x[a - s:b - s]
        th = (c['pan'] + 1) * math.pi / 4                      # -1 -> left only, 0 -> equal power, +1 -> right only
        buf[a:b, 0] += seg * math.cos(th) * math.sqrt(2)
        buf[a:b, 1] += seg * math.sin(th) * math.sqrt(2)
    sfx_synth.write_wav(out_path, buf, SR, bits=24)
    return out_path


def fragment(plan: dict, sfx_dir: str, first_input: int = 0, label: str = 'sfx') -> tuple[list[str], str]:
    """(input paths, filter_complex fragment) equivalent to render(): one input per cue, adelay per cue, amix."""
    ins, segs, labels = [], [], []
    for k, c in enumerate(plan['cues']):
        ins.append(os.path.join(sfx_dir, c['file']))
        ms = max(0, int(round(c['start'] * 1000)))
        th = (c['pan'] + 1) * math.pi / 4
        segs.append('[%d:a]aformat=sample_fmts=fltp:sample_rates=48000,volume=%.2fdB,pan=stereo|c0=%.4f*c0|c1=%.4f*c0,adelay=%d|%d[s%d]'
                    % (first_input + k, c['gain_db'], math.cos(th) * math.sqrt(2), math.sin(th) * math.sqrt(2), ms, ms, k))
        labels.append('[s%d]' % k)
    if not ins:
        return [], 'anullsrc=r=48000:cl=stereo,atrim=0:%.3f[%s]' % (plan['total'], label)
    segs.append(''.join(labels) + 'amix=inputs=%d:normalize=0:duration=longest,apad=whole_dur=%.3f,atrim=0:%.3f[%s]'
                % (len(labels), plan['total'], plan['total'], label))
    return ins, ';'.join(segs)


def plan_from_files(timeline=None, sync=None, seams=None, beats=None, words=None, phases=None, vo=None, total=None,
                    sfx_dir=DEFAULT_SFX_DIR, sfx_db=SFX_BUS_DB, guard=GUARD_S, nudge=NUDGE_S) -> dict:
    TL = load_json(timeline) or {}
    cues = []
    cues += cues_from_seams(TL.get('seams', []))
    cues += cues_from_sync(TL.get('sync', []), 'timeline')
    S = load_json(seams)
    if S:
        cues += cues_from_seams(S.get('seams', S if isinstance(S, list) else []))
    Y = load_json(sync)
    if Y:
        cues += cues_from_sync(Y.get('points', Y if isinstance(Y, list) else []), 'sync')
    PH = load_json(phases) or ({'phases': TL['phases'], 'total': TL.get('total')} if TL.get('phases') else None)
    onsets, n_words = word_onsets(load_json(words), PH, vo) if words else ([], 0)
    T = total or (PH or {}).get('total') or TL.get('total') or (max([c['t'] for c in cues], default=0.0) + 1.0)
    man = ensure_sfx(sfx_dir)
    plan = place(cues, onsets, man, float(T), load_json(beats), sfx_db, guard, nudge)
    plan['words_total'] = n_words
    return plan


# ----------------------------------------------------------------------------------------------- selftest
def selftest() -> int:
    import tempfile, time
    sys.path.insert(0, HERE)
    import fx_chain
    t0 = time.time(); fails = []
    tmp = tempfile.mkdtemp(prefix='sfx_place_')
    sfx_dir = os.path.join(tmp, 'sfx'); man = ensure_sfx(sfx_dir)
    total = 10.0
    # a fake narration: two phases, words every 0.5 s; one word (b[1] at 7.0) deliberately quiet in the vo file
    phases = {'total': total, 'phases': [{'name': 'a', 'start': 1.0, 'dur': 2.6}, {'name': 'b', 'start': 6.0, 'dur': 2.6}]}
    words = {'a': [{'t': round(i * 0.5, 2), 'w': 'acme%d' % i} for i in range(6)], 'b': [{'t': round(i * 0.5, 2), 'w': 'ok%d' % i} for i in range(6)]}
    rng = np.random.default_rng(1)
    vo = np.zeros(int(total * SR))
    for ph in phases['phases']:
        for w in words[ph['name']]:
            t = ph['start'] + w['t']; a = int(t * SR); m = int(0.12 * SR)
            amp = 0.02 if (ph['name'] == 'b' and w['t'] == 1.0) else 0.4                 # -34 dBFS (at 7.0) vs -8 dBFS
            vo[a:a + m] += amp * np.sin(2 * np.pi * 180 * np.arange(m) / SR) * np.hanning(m)
    vo_path = os.path.join(tmp, 'vo.wav'); sfx_synth.write_wav(vo_path, vo)
    # cues: a seam at 4.0 (clear), a land at 2.05 (0.05 s from the word at 2.0 -> nudge to 1.85), a land at 7.0 (quiet word -> allowed),
    # two impacts in act 'open' (one demoted), a climax at 9.0 (riser ends there), a flash at 2.47 (word at 2.5 -> nudge fails -> drop? 2.47-0.12=2.35 is 0.15 from 2.5: kept at 2.35)
    seams = {'seams': [{'id': 'title->ui', 'cut': 4.0, 'act': 'demo', 'entry': {'axis': 'x', 'dir': -1}},
                       {'id': 'open-hit', 'cut': 0.5, 'act': 'open', 'cause': 'impact'},
                       {'id': 'open-hit-2', 'cut': 0.8, 'act': 'open', 'cause': 'impact'}]}
    sync = {'points': [{'t': 2.42, 'kind': 'land', 'id': 'kpi:land'}, {'t': 7.0, 'kind': 'land', 'id': 'kpi2:land'},
                       {'t': 9.0, 'kind': 'climax', 'id': 'reveal:climax'}, {'t': 3.42, 'kind': 'flash', 'id': 'flash'},
                       {'t': 2.05, 'kind': 'land', 'id': 'late:land'}, {'t': 3.2, 'kind': 'stream', 'id': 'chat:stream'},
                       {'t': 2.05, 'kind': 'confirm', 'id': 'forced:confirm', 'force': True}]}      # same spot, forced: kept, word gap reported
    for name, obj in (('seams.json', seams), ('sync.json', sync), ('ph.json', phases), ('words.json', words)):
        json.dump(obj, open(os.path.join(tmp, name), 'w'))
    args = dict(sync=os.path.join(tmp, 'sync.json'), seams=os.path.join(tmp, 'seams.json'), words=os.path.join(tmp, 'words.json'),
                phases=os.path.join(tmp, 'ph.json'), vo=vo_path, total=total, sfx_dir=sfx_dir)
    plan = plan_from_files(**args)
    ids = {c['id']: c for c in plan['cues']}
    onsets, _ = word_onsets(words, phases, vo_path)
    if plan['words_guarded'] != 11:
        fails.append('loud-word gate: %d guarded (want 11 of 12)' % plan['words_guarded'])
    for c in plan['cues']:
        if c['sfx'] == 'riser' or c.get('forced'):
            continue
        d = min(abs(c['t'] - w) for w in onsets)
        if d < GUARD_S - 1e-9:
            fails.append('%s at %.3f is %.3f s from a word' % (c['id'], c['t'], d))
    if 'kpi:land' not in ids or abs(ids['kpi:land']['t'] - 2.35) > 1e-6 or abs(ids['kpi:land']['nudged_s'] - 0.07) > 1e-6:
        fails.append('land at 2.42 not nudged to 2.35: %s' % ids.get('kpi:land'))
    if 'flash' not in ids or abs(ids['flash']['t'] - 3.35) > 1e-6:
        fails.append('flash at 3.42 not nudged to 3.35: %s' % ids.get('flash'))
    if not any(d['id'] == 'late:land' for d in plan['dropped']):
        fails.append('land 0.05 s after a word should be dropped')
    if 'kpi2:land' not in ids or ids['kpi2:land']['nudged_s'] != 0.0:
        fails.append('quiet word should not guard: %s' % ids.get('kpi2:land'))
    fc = ids.get('forced:confirm')
    if not (fc and fc.get('forced') is True and abs(fc['t'] - 2.05) < 1e-6 and fc['nudged_s'] == 0.0 and abs(fc.get('word_gap_s', 9) - 0.05) < 1e-6 and fc['sfx'] == 'ui-confirm'):
        fails.append('forced point should stay at 2.05 with word_gap_s 0.05: %s' % fc)
    if 'reveal:climax' not in ids or abs(ids['reveal:climax']['start'] + ids['reveal:climax']['dur'] - 9.0) > 1e-6:
        fails.append('riser does not end on the climax: %s' % ids.get('reveal:climax'))
    if not (len(plan['demoted']) == 1 and ids.get('open-hit-2', {}).get('sfx') == 'snap' and ids.get('open-hit', {}).get('sfx') == 'impact-low'):
        fails.append('impact-per-act rule: %s' % [(c['id'], c['sfx']) for c in plan['cues']])
    if abs(ids.get('title->ui', {}).get('start', 0) - (4.0 - 0.175)) > 1e-6 or ids['title->ui']['pan'] != WHOOSH_PAN:
        fails.append('whoosh not aligned/panned on the cut: %s' % ids.get('title->ui'))
    if any(c['id'] == 'chat:stream' for c in plan['cues']):
        fails.append('stream should be silent')
    # render twice: identical bytes; mixed under a -30 dBFS bed the integrated loudness rises by 0.1 ... 3 LU
    r1 = render(plan, sfx_dir, os.path.join(tmp, 'sfx1.wav')); r2 = render(plan, sfx_dir, os.path.join(tmp, 'sfx2.wav'))
    if sfx_synth.md5_of(r1) != sfx_synth.md5_of(r2):
        fails.append('stem render not deterministic')
    bed = sfx_synth.butter_bp(rng.standard_normal((int(total * SR))), 60, 8000); bed *= lin(-36) / np.sqrt(np.mean(bed ** 2))
    bed_path = os.path.join(tmp, 'bed.wav'); sfx_synth.write_wav(bed_path, np.stack([bed, bed], 1))
    stem, _ = sfx_synth.read_wav(r1)
    mix_path = os.path.join(tmp, 'mix.wav'); sfx_synth.write_wav(mix_path, np.stack([bed, bed], 1) + stem)
    lb, lm = fx_chain.measure(bed_path)['lufs'], fx_chain.measure(mix_path)['lufs']
    if not (0.1 <= lm - lb <= 3.0):
        fails.append('bed %.1f -> bed+sfx %.1f LUFS (want +0.1 ... +3 LU)' % (lb, lm))
    pk = 20 * math.log10(float(np.max(np.abs(stem))))
    tick_pk = 20 * math.log10(float(np.max(np.abs(stem[int(2.3 * SR):int(2.45 * SR)]))))     # the isolated, centre-panned tick
    if abs(tick_pk - (-20.0)) > 0.3:
        fails.append('isolated cue peaks at %.1f dBFS (want -20 with the -14 dB bus)' % tick_pk)
    ins, frag = fragment(plan, sfx_dir)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + sum([['-i', p] for p in ins], []) + ['-filter_complex', frag, '-map', '[sfx]',
                        '-c:a', 'pcm_s24le', os.path.join(tmp, 'frag.wav')], capture_output=True, text=True)
    if r.returncode != 0:
        fails.append('ffmpeg rejected the fragment: %s' % r.stderr[-200:])
    else:
        fr, _ = sfx_synth.read_wav(os.path.join(tmp, 'frag.wav'))
        if abs(20 * math.log10(float(np.max(np.abs(fr)))) - pk) > 0.3 or abs(fr.shape[0] - stem.shape[0]) > 48:
            fails.append('fragment and stem disagree (peak %.2f vs %.2f dBFS, %d vs %d frames)' % (20 * math.log10(float(np.max(np.abs(fr)))), pk, fr.shape[0], stem.shape[0]))
    # v5.1: unanchored sync cues snap to the beat grid; snap:false stays; a landing never moves
    grid = {'rhythmic': True, 'beats': [{'t': x * 0.5} for x in range(0, 24)]}
    cs = cues_from_sync([{'id': 'flash-1', 't': 2.93, 'kind': 'flash'}, {'id': 'flash-2', 't': 4.43, 'kind': 'flash', 'snap': False}, {'id': 'kpi:land', 't': 6.46}])
    pl = place(cs, [], man, 12.0, beats=grid)
    got = {c['id']: c['t'] for c in pl['cues']}
    if not (abs(got.get('flash-1', 0) - 3.0) < 1e-6 and abs(got.get('flash-2', 0) - 4.43) < 1e-6 and abs(got.get('kpi:land', 0) - 6.46) < 1e-6):
        fails.append('beat snap: unanchored flash -> 3.0, snap:false stays, a landing never moves: %s' % got)
    print('sfx_place selftest: %d placed, %d dropped, %d demoted; bed %.1f -> %.1f LUFS; stem peak %.1f dBFS; %.1f s, %s' % (
        len(plan['cues']), len(plan['dropped']), len(plan['demoted']), lb, lm, pk, time.time() - t0, 'OK' if not fails else '; '.join(fails)))
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='place synthesized SFX on the narration clock (seams / sync / beats), word-safe, as a stem + ffmpeg fragment')
    ap.add_argument('--timeline', help='out/timeline.json (seams + sync + phases + total)')
    ap.add_argument('--sync', help='sync.json {"points":[{t, kind, id, act?, snap?, sfx?}]}')
    ap.add_argument('--seams', help='seams.json with numeric cuts (or out/timeline.json)')
    ap.add_argument('--beats', help='out/beats_<name>.json for "snap": true cues')
    ap.add_argument('--words', help='vo/<name>_words.json ({phase:[{t,w}]} with --phases, or a flat [{t}] list)')
    ap.add_argument('--phases', help='vo/<name>_phases.json')
    ap.add_argument('--vo', help='assembled narration audio: only words peaking above --word-floor guard')
    ap.add_argument('--total', type=float, help='film length in seconds')
    ap.add_argument('--sfx-dir', default=DEFAULT_SFX_DIR, help='directory with manifest.json (synthesized there if missing)')
    ap.add_argument('--sfx-db', type=float, default=SFX_BUS_DB, help='bus gain on the -6 dBFS files (default -14 -> peaks at -20 dBFS)')
    ap.add_argument('--guard', type=float, default=GUARD_S)
    ap.add_argument('--nudge', type=float, default=NUDGE_S)
    ap.add_argument('--render', help='write the stereo SFX stem WAV')
    ap.add_argument('--json', help='write the cue plan')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.timeline or a.sync or a.seams):
        ap.print_help(); return 2
    try:
        plan = plan_from_files(a.timeline, a.sync, a.seams, a.beats, a.words, a.phases, a.vo, a.total, a.sfx_dir, a.sfx_db, a.guard, a.nudge)
    except (RuntimeError, ValueError, KeyError) as e:
        print('error: %s' % e, file=sys.stderr); return 2
    ins, frag = fragment(plan, a.sfx_dir)
    plan['inputs'] = ins; plan['fragment'] = frag
    if a.render:
        plan['stem'] = render(plan, a.sfx_dir, a.render)
    if a.json:
        json.dump(plan, open(a.json, 'w', encoding='utf-8'), indent=1)
    print(frag)
    print(json.dumps({'placed': len(plan['cues']), 'dropped': [(d['id'], d['reason']) for d in plan['dropped']],
                      'demoted': [(d['id'], d['reason']) for d in plan['demoted']], 'words_guarded': plan['words_guarded'],
                      'forced': [(c['id'], c.get('word_gap_s')) for c in plan['cues'] if c.get('forced')],
                      'stem': plan.get('stem')}, indent=1), file=sys.stderr)
    return 1 if plan['dropped'] else 0


if __name__ == '__main__':
    sys.exit(main())
