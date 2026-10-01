# -*- coding: utf-8 -*-
"""export.py — delivery presets derived from the MASTERED film (v4, media area). Never a second render.

    python tools/export.py [--project DIR] [--film out/X.mp4] --preset linkedin,booth_loop [--all] [--seconds 12]
                           [--fill band|crop] [--with-source] [--json]
    python tools/export.py --selftest

Every preset reads build_film.py's outputs — the credited film, out/master_<name>.wav (24-bit, -16 LUFS) and the
.srt — and writes next to the film as  <stem>_<preset>_<YYYY-MM-DD>_<HH-MM-SS>.<ext>  plus a stable  <stem>_<preset>.<ext>
copy. Every MP4 goes through credit.check and a loudness probe before it is kept; the ledger (media.jsonl, when
present) gets one `deliverable` record per output with the preset, target LUFS and measured values.

  booth_loop     film + 1.0 s loop pad (last frame held, dipping to black over the final 0.6 s) so a looping booth player
                 restarts on the scene's own head fade; audio padded with silence. Also writes *_silent.mp4 (no audio
                 stream) for booth screens that run muted. CRF 17, AAC 192k, faststart. -16 LUFS.
  linkedin       1080p H.264 High CRF 18, AAC 192k, faststart, -16 LUFS (narration target); WARNS when > 10 min.
  youtube        the CRF 17 master picture (stream-copied when it already is H.264 — no generation loss), audio
                 re-mastered from the WAV to -14 LUFS / TP -1.5 (two-pass linear, refuses dynamic), AAC 256k.
  vertical_9x16  1080x1920. --fill band (default): the 16:9 picture at 1080 px wide (1080x608) centred inside
                 title-safe over a blurred, darkened fill of itself; --fill crop: a smart 9:16 crop whose x-centre is
                 where the picture's edge energy lives. The credit is re-stamped for the new canvas and checked; a
                 *.captions.md note says where burned-in text now sits and where to re-place the SRT.
  square_1x1     1080x1080, same two fill modes, credit re-stamped and checked.
  gif_teaser     first N s (default 12) + a 1.5 s hold on the credit frame; 15 fps, 960 px wide, two-pass palette
                 (palettegen → paletteuse), no audio.
  share_pack     <stem>_share_<date>.zip: film, preset variants present, .srt, media_index.md, claims.json, generated
                 DELIVERY.md (duration, size, loudness, credit, what feedback is wanted); --with-source adds the authored
                 set. NEVER recording.mp4, broll/, vo/, .history/, out/seg_*. Refuses on a licence UNKNOWN or a hygiene
                 regex hit (qa.json) in any included text file.

Measured rules kept: GIF two-pass palette at 15 fps and no audio; -14 LUFS / TP -1.5 / LRA 11 for socials, -16 for
narration; two-pass LINEAR loudnorm with the build's pre-gain + limiter two-stage trick and its REFUSE rule; timestamped
output names so runs never clobber; no 4K (1080p product recordings gain nothing). Re-master from the WAV, never the AAC.
"""
import argparse, datetime, importlib, json, os, re, shutil, subprocess, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = ('booth_loop', 'linkedin', 'youtube', 'vertical_9x16', 'square_1x1', 'gif_teaser', 'share_pack')
LUFS_NARRATION, LUFS_SOCIAL, TP, LRA = -16.0, -14.0, -1.5, 11.0
LOOP_PAD, LOOP_DIP = 1.0, 0.6                       # booth loop: pad after the credit frame, dip-to-black inside the pad
GIF_FPS, GIF_WIDTH, GIF_SECONDS, GIF_CREDIT_HOLD = 15, 960, 12.0, 1.5
LINKEDIN_MAX_MIN = 10.0
TITLE_SAFE = 0.10                                   # 10 % inset per edge (80 % title-safe box)
CREDIT_BAND_1080 = 120                              # bottom px reserved for the credit on a 1080-line canvas

# share pack: what never leaves the project
SHARE_NEVER = re.compile(r'^(recording\.mp4|broll/|vo/|\.history/|out/seg_|out/.*\.part\d+\.mp4|out/(raw|mix|master)_.*\.wav|.*\.lock)$')
SOURCE_SET = ('film.json', 'qa.json', 'clips.json', 'claims.json', 'vo_script.py', 'media.jsonl', 'scenes/')


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError('%s failed:\n%s' % (os.path.basename(str(cmd[0])), (r.stderr or r.stdout)[-1500:]))
    return r


def probe(path):
    r = sh(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height,r_frame_rate:format=duration,size',
            '-of', 'json', path])
    j = json.loads(r.stdout)
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'), {})
    a = next((s for s in j.get('streams', []) if s.get('codec_type') == 'audio'), None)
    return {'w': int(v.get('width', 0)), 'h': int(v.get('height', 0)), 'vcodec': v.get('codec_name'), 'has_audio': a is not None,
            'dur': float(j['format'].get('duration', 0)), 'bytes': int(j['format'].get('size', 0))}


def measure_loudness(path, I=LUFS_NARRATION):
    """Integrated loudness and true peak of a file's audio via a loudnorm measurement pass; None without audio."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-af', 'loudnorm=I=%.1f:TP=%.1f:LRA=%.1f:print_format=json' % (I, TP, LRA),
                        '-f', 'null', '-'], capture_output=True, text=True)
    m = re.findall(r'\{[^{}]*"input_i"[\s\S]*?\}', r.stderr)
    if not m:
        return None
    st = json.loads(m[-1])
    return {'I': float(st['input_i']), 'TP': float(st['input_tp']), 'raw': st}


def remaster(src_wav, dst_wav, I, tp=TP, lra=LRA):
    """Two-stage re-master to a new target: pre-gain + sample-peak limiter land the mix ~0.45 LU above target with
    headroom, then two-pass loudnorm with linear=true. Refuses (raises) if loudnorm reports dynamic."""
    st = measure_loudness(src_wav, I)
    if not st:
        raise RuntimeError('loudnorm measurement failed on ' + src_wav)
    pre, ceil = (I + 0.45) - st['I'], tp - 0.8
    tmp = dst_wav + '.pre.wav'
    sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src_wav, '-af',
        'volume=%.2fdB,alimiter=limit=%.5f:attack=5:release=80:level=false' % (pre, 10 ** (ceil / 20.0)), '-c:a', 'pcm_s24le', '-ar', '48000', tmp])
    s2 = measure_loudness(tmp, I)['raw']
    af = ('loudnorm=I=%.1f:TP=%.1f:LRA=%.1f:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true:print_format=json'
          % (I, tp, lra, s2['input_i'], s2['input_tp'], s2['input_lra'], s2['input_thresh'], s2['target_offset']))
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-y', '-i', tmp, '-af', af, '-ar', '48000', '-c:a', 'pcm_s24le', dst_wav],
                       capture_output=True, text=True)
    os.remove(tmp)
    rep = json.loads(re.findall(r'\{[^{}]*"normalization_type"[\s\S]*?\}', r.stderr)[-1])
    if rep['normalization_type'].lower() != 'linear':
        raise RuntimeError('REFUSING: loudnorm fell back to %s re-mastering to %.0f LUFS' % (rep['normalization_type'], I))
    return {'type': rep['normalization_type'], 'out_I': float(rep['output_i']), 'out_TP': float(rep['output_tp']), 'pre_db': pre}


def smart_crop_center(film, dur, crop_w, src_w, src_h, samples=12):
    """x-centre (source px) of the crop window with the most horizontal edge energy over `samples` grey frames at 192x108."""
    import numpy as np
    W, H = 192, 108
    acc = np.zeros(W - 1)
    for k in range(samples):
        t = dur * (k + 0.5) / samples
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', film, '-frames:v', '1', '-vf',
                            'scale=%d:%d,format=gray' % (W, H), '-f', 'rawvideo', '-'], capture_output=True)
        if len(r.stdout) < W * H:
            continue
        g = np.frombuffer(r.stdout[:W * H], dtype=np.uint8).reshape(H, W).astype(np.float32)
        acc += np.abs(np.diff(g, axis=1)).sum(axis=0)
    win = max(1, int(round(crop_w / src_w * W)))
    if win >= len(acc):
        return src_w / 2.0
    sums = np.convolve(acc, np.ones(win), mode='valid')
    x0 = int(np.argmax(sums))
    return (x0 + win / 2.0) / W * src_w


class Exporter:
    """One mastered film and the presets derived from it. `Exporter(project).run(['linkedin', 'gif_teaser'])`."""

    def __init__(self, project, film=None, verbose=True):
        self.project = os.path.abspath(project)
        self.cfg = json.load(open(os.path.join(self.project, 'film.json'), encoding='utf-8')) if os.path.exists(os.path.join(self.project, 'film.json')) else {}
        self.name = self.cfg.get('name', 'film')
        self.film = os.path.abspath(os.path.join(self.project, film or self.cfg.get('output', 'out/%s.mp4' % self.name)))
        if not os.path.exists(self.film):
            raise FileNotFoundError(self.film)
        self.dir, self.stem = os.path.dirname(self.film), os.path.splitext(os.path.basename(self.film))[0]
        self.srt = os.path.splitext(self.film)[0] + '.srt'
        self.master = os.path.join(self.project, 'out', 'master_%s.wav' % self.name)
        self.info = probe(self.film)
        self.stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        self.verbose, self.outputs, self._tmp = verbose, [], tempfile.TemporaryDirectory(prefix='fde_export_')
        self.CR = self._credit()
        self.ledger = self._ledger()

    # ---- plumbing
    def log(self, *a):
        if self.verbose: print(*a)

    def _credit(self):
        for d in (self.project, os.path.join(HERE, '..', '..')):
            if os.path.exists(os.path.join(d, 'credit.py')):
                sys.path.insert(0, d); return importlib.import_module('credit')
        raise ImportError('credit.py not found (project or plugin scripts/)')

    def _ledger(self):
        for d in (HERE, os.path.join(self.project, 'tools')):
            if os.path.exists(os.path.join(d, 'ledger.py')):
                if d not in sys.path: sys.path.insert(0, d)
                LG = importlib.import_module('ledger')
                L = LG.Ledger(self.project, self.cfg.get('ledger') or LG.LEDGER_FILE)
                return L if L.exists() else None
        return None

    def out_path(self, preset, ext='mp4', suffix=''):
        return os.path.join(self.dir, '%s_%s%s_%s.%s' % (self.stem, preset, suffix, self.stamp, ext))

    def audio_wav(self, I):
        """A WAV at the target loudness: the master itself at -16, a re-master otherwise; the film's AAC only as a last resort."""
        src = self.master
        if not os.path.exists(src):
            src = os.path.join(self._tmp.name, 'from_aac.wav')
            self.log('  WARN  out/master_%s.wav missing — re-mastering from the film\'s AAC (lossy source)' % self.name)
            sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-vn', '-c:a', 'pcm_s24le', '-ar', '48000', src])
        if abs(I - LUFS_NARRATION) < 0.01 and src == self.master:
            return src, None
        dst = os.path.join(self._tmp.name, 'master_%+.0f.wav' % I)
        if not os.path.exists(dst):
            rep = remaster(src, dst, I)
            self.log('  re-master -> %.0f LUFS: %s, out I %.2f TP %.2f (pre %+.2f dB)' % (I, rep['type'], rep['out_I'], rep['out_TP'], rep['pre_db']))
        return dst, I

    def finish(self, path, preset, lufs, check_credit=True, extra=None):
        """credit.check + loudness probe + stable copy + ledger record. Deletes and raises when the credit is missing."""
        info = probe(path)
        credit_ok = self.CR.check(path, verbose=False) if check_credit else None
        if check_credit and not credit_ok:
            os.remove(path)
            raise RuntimeError('REFUSING %s: the FDE Demo Builder credit is not legible on its end screen' % os.path.basename(path))
        loud = measure_loudness(path, lufs or LUFS_NARRATION) if info['has_audio'] else None
        latest = re.sub(r'_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(\.\w+)$', r'\1', path)
        shutil.copyfile(path, latest)
        rec = {'preset': preset, 'file': os.path.relpath(path, self.project).replace('\\', '/'), 'latest': os.path.relpath(latest, self.project).replace('\\', '/'),
               'dur': round(info['dur'], 2), 'size_mb': round(info['bytes'] / 1e6, 2), 'w': info['w'], 'h': info['h'],
               'credit': 'PRESENT' if credit_ok else ('n/a' if credit_ok is None else 'MISSING'),
               'lufs_target': lufs, 'lufs': round(loud['I'], 2) if loud else None, 'tp': round(loud['TP'], 2) if loud else None}
        rec.update(extra or {})
        self.outputs.append(rec)
        self.log('  %-14s %s  %.2f s  %.1f MB  %sx%s  credit %s%s' % (preset, rec['file'], rec['dur'], rec['size_mb'], rec['w'], rec['h'], rec['credit'],
                                                                    ('  I %.2f LUFS TP %.2f' % (loud['I'], loud['TP'])) if loud else '  (no audio)'))
        if self.ledger:
            try:
                self.ledger.add(rec['latest'], kind='deliverable', description='%s export of %s' % (preset, os.path.basename(self.film)), added_by='export.py',
                                source={'kind': 'derived', 'provider': 'tools/export.py', 'preset': preset, 'from': os.path.relpath(self.film, self.project).replace('\\', '/'),
                                        'lufs_target': lufs, 'lufs': rec['lufs'], 'tp': rec['tp']}, force=True)
            except Exception as e:
                self.log('  WARN  ledger record failed: %s' % e)
        return rec

    # ---- presets
    def booth_loop(self):
        dur, pad = self.info['dur'], LOOP_PAD
        wav, _ = self.audio_wav(LUFS_NARRATION)
        vf = 'tpad=stop_mode=clone:stop_duration=%.3f,fade=t=out:st=%.3f:d=%.3f' % (pad, dur + pad - LOOP_DIP, LOOP_DIP)
        out = self.out_path('booth_loop')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-i', wav, '-map', '0:v:0', '-map', '1:a:0', '-vf', vf,
            '-af', 'apad=whole_dur=%.3f' % (dur + pad), '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', out])
        seam = self._luma(out, 0.02), self._luma(out, dur + pad - 0.05)
        rec = self.finish(out, 'booth_loop', LUFS_NARRATION, extra={'loop_seam_luma': [round(seam[0], 1), round(seam[1], 1)]})
        silent = self.out_path('booth_loop', suffix='_silent')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', out, '-an', '-c:v', 'copy', '-movflags', '+faststart', silent])
        self.finish(silent, 'booth_loop_silent', None)
        self.log('  loop seam: first-frame luma %.1f, last-frame luma %.1f (both near black = seamless restart)' % seam)
        return rec

    def _luma(self, path, t):
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', path, '-frames:v', '1', '-vf', 'scale=32:18,format=gray',
                            '-f', 'rawvideo', '-'], capture_output=True)
        return sum(r.stdout) / max(1, len(r.stdout))

    def linkedin(self):
        if self.info['dur'] > LINKEDIN_MAX_MIN * 60:
            self.log('  WARN  %.1f min exceeds the %.0f-minute LinkedIn limit — cut down before posting' % (self.info['dur'] / 60, LINKEDIN_MAX_MIN))
        wav, _ = self.audio_wav(LUFS_NARRATION)
        out = self.out_path('linkedin')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-i', wav, '-map', '0:v:0', '-map', '1:a:0',
            '-vf', 'scale=1920:1080:flags=lanczos', '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', out])
        return self.finish(out, 'linkedin', LUFS_NARRATION)

    def youtube(self):
        wav, _ = self.audio_wav(LUFS_SOCIAL)
        out = self.out_path('youtube')
        vargs = ['-c:v', 'copy'] if self.info['vcodec'] == 'h264' else ['-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p']
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-i', wav, '-map', '0:v:0', '-map', '1:a:0'] + vargs +
           ['-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-shortest', '-movflags', '+faststart', out])
        return self.finish(out, 'youtube', LUFS_SOCIAL, extra={'video': 'stream copy (crf 17 master)' if vargs[1] == 'copy' else 'libx264 crf 17'})

    def _reframe(self, preset, W, H, fill):
        """Re-aspect to W x H (band = letterbox on a blurred fill of itself; crop = smart crop), then re-stamp + check the credit."""
        sw, shh, dur = self.info['w'], self.info['h'], self.info['dur']
        wav, _ = self.audio_wav(LUFS_NARRATION)
        if fill == 'crop':
            cw = int(round(shh * W / H)); cx = smart_crop_center(self.film, dur, cw, sw, shh)
            x0 = int(max(0, min(sw - cw, round(cx - cw / 2.0))))
            graph = ['-vf', 'crop=%d:%d:%d:0,scale=%d:%d:flags=lanczos' % (cw, shh, x0, W, H), '-map', '0:v:0']
            band = {'mode': 'crop', 'crop_x': x0, 'crop_w': cw}
        else:
            bh = int(round(W * shh / sw / 2.0) * 2); by = (H - bh) // 2
            graph = ['-filter_complex', '[0:v]split[a][b];[a]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,gblur=sigma=28,'
                     'eq=brightness=-0.18:saturation=0.8[bg];[b]scale=%d:%d:flags=lanczos[fg];[bg][fg]overlay=0:%d[v]' % (W, H, W, H, W, bh, by), '-map', '[v]']
            band = {'mode': 'band', 'band_y': [by, by + bh], 'scale': round(W / sw, 3)}
        pre = os.path.join(self._tmp.name, preset + '_pre.mp4')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-i', wav] + graph + ['-map', '1:a:0',
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', pre])
        out = self.out_path(preset)
        self.CR.stamp(pre, out)                                 # credit for the new canvas (credit.py prints one line)
        rec = self.finish(out, preset, LUFS_NARRATION, extra=band)
        stable = os.path.splitext(os.path.join(self.project, rec['latest']))[0]      # note + srt beside the stable copy
        rec['captions_note'] = os.path.relpath(self._caption_note(stable + '.mp4', W, H, band), self.project).replace('\\', '/')
        if os.path.exists(self.srt):
            shutil.copyfile(self.srt, stable + '.srt')
        return rec

    def _caption_note(self, out, W, H, band):
        ts, cb = int(H * TITLE_SAFE), int(round(CREDIT_BAND_1080 * H / 1080.0))
        if band['mode'] == 'band':
            y0, y1 = band['band_y']
            where = ('The 16:9 picture sits in the band y %d-%d at %.0f%% scale, so any text burned into the film (title caption, '
                     'lower-thirds, the small original credit) is inside that band and %.0f%% smaller.' % (y0, y1, band['scale'] * 100, (1 - band['scale']) * 100))
            place = 'Re-place captions from the .srt in the free zone below the band: y %d-%d (inside title-safe, above the credit band).' % (y1 + 24, H - cb - 24)
        else:
            where = ('Smart crop kept source columns x %d-%d; anything burned into the film outside that window is gone — check lower-thirds and '
                     'the title caption.' % (band['crop_x'], band['crop_x'] + band['crop_w']))
            place = 'Re-place captions from the .srt in the lower title-safe zone: y %d-%d.' % (int(H * 0.72), H - cb - 24)
        txt = ['# %s — caption and text placement' % os.path.basename(out), '', 'Canvas %dx%d. Title-safe box: x %d-%d, y %d-%d. The bottom %d px (y >= %d) is the credit band — keep it clear.'
               % (W, H, int(W * TITLE_SAFE), W - int(W * TITLE_SAFE), ts, H - ts, cb, H - cb), '', where, '', place, '',
               'The mandatory FDE Demo Builder credit was re-stamped for this canvas by credit.py and verified (credit.check).']
        note = os.path.splitext(out)[0] + '.captions.md'
        open(note, 'w', encoding='utf-8').write('\n'.join(txt) + '\n')
        return note

    def vertical_9x16(self, fill='band'):
        return self._reframe('vertical_9x16', 1080, 1920, fill)

    def square_1x1(self, fill='band'):
        return self._reframe('square_1x1', 1080, 1080, fill)

    def gif_teaser(self, seconds=GIF_SECONDS):
        dur = self.info['dur']; n = min(seconds, max(0.5, dur - GIF_CREDIT_HOLD))
        pal = os.path.join(self._tmp.name, 'palette.png')
        chain = ('[0:v]trim=0:%.3f,setpts=PTS-STARTPTS[a];[0:v]trim=start=%.3f,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0,fps=%d,scale=%d:-2:flags=lanczos'
                 % (n, max(0.0, dur - GIF_CREDIT_HOLD), GIF_FPS, GIF_WIDTH))
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-filter_complex', chain + ',palettegen=stats_mode=diff', pal])
        out = self.out_path('gif_teaser', 'gif')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', self.film, '-i', pal, '-filter_complex',
            chain + '[g];[g][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle', '-loop', '0', out])
        return self.finish(out, 'gif_teaser', None, check_credit=False, extra={'seconds': round(n, 2), 'credit_hold': GIF_CREDIT_HOLD, 'fps': GIF_FPS})

    def share_pack(self, with_source=False):
        qa = json.load(open(os.path.join(self.project, 'qa.json'), encoding='utf-8')) if os.path.exists(os.path.join(self.project, 'qa.json')) else {}
        if self.ledger and self.ledger.unknown():
            raise RuntimeError('REFUSING share pack: licence UNKNOWN on %s' % [r['path'] for r in self.ledger.unknown()])
        files = [self.film] + ([self.srt] if os.path.exists(self.srt) else [])
        for f in sorted(os.listdir(self.dir)):                  # stable preset copies beside the film
            if f.startswith(self.stem + '_') and re.search(r'_(%s)(_silent)?\.(mp4|gif)$' % '|'.join(PRESETS), f) and not re.search(r'_\d{4}-\d{2}-\d{2}_', f):
                files.append(os.path.join(self.dir, f))
            if f.startswith(self.stem + '_') and f.endswith(('.captions.md', '.srt')) and os.path.join(self.dir, f) not in files and not re.search(r'_\d{4}-\d{2}-\d{2}_', f):
                files.append(os.path.join(self.dir, f))
        for f in ('media_index.md', 'claims.json'):
            if os.path.exists(os.path.join(self.project, f)): files.append(os.path.join(self.project, f))
        if self.ledger: self.ledger.write_index()
        if with_source:
            for s in SOURCE_SET:
                p = os.path.join(self.project, s)
                if os.path.isdir(p):
                    for r, _, fs in os.walk(p):
                        files += [os.path.join(r, x) for x in fs if not x.endswith(('.mp3', '.wav', '.mp4'))]
                elif os.path.exists(p): files.append(p)
        rel = lambda p: os.path.relpath(p, self.project).replace('\\', '/')
        files = [f for f in dict.fromkeys(files) if not SHARE_NEVER.match(rel(f))]
        pats = qa.get('hygiene_patterns', {})
        for f in files:
            if f.endswith(('.md', '.json', '.srt', '.py', '.js', '.html', '.txt', '.jsonl')):
                body = open(f, encoding='utf-8', errors='replace').read()
                for k, p in pats.items():
                    m = re.search(p, body, re.I)
                    if m: raise RuntimeError('REFUSING share pack: hygiene pattern "%s" matched %r in %s' % (k, m.group(0)[:40], rel(f)))
        loud = measure_loudness(self.film)
        d = ['# DELIVERY — %s' % os.path.basename(self.film), '', '| | |', '|---|---|', '| duration | %.2f s |' % self.info['dur'],
             '| picture | %dx%d %s |' % (self.info['w'], self.info['h'], self.info['vcodec']), '| size | %.1f MB |' % (self.info['bytes'] / 1e6),
             '| loudness | I %.2f LUFS, TP %.2f dBTP (target -16 / -1.5) |' % (loud['I'], loud['TP']) if loud else '| loudness | no audio |',
             '| credit | %s |' % ('PRESENT' if self.CR.check(self.film, verbose=False) else 'MISSING'),
             '| ledger | %s |' % ('%d assets, 0 licence UNKNOWN (media_index.md)' % len(self.ledger.current()) if self.ledger else 'none'),
             '| QA | run `python qa_film.py` in the project; attach its output when sharing for approval |', '',
             '## In this pack', ''] + ['- ' + rel(f) for f in files] + ['',
             '## Feedback wanted', '', 'Say which: story · visuals · timing · facts (claims.json lists every spoken figure and where it is on screen) · approval.', '',
             'Fictional company and synthetic data unless the ledger says otherwise. Crafted with FDE Demo Builder · by Ahmed Awan.']
        delivery = os.path.join(self._tmp.name, 'DELIVERY.md'); open(delivery, 'w', encoding='utf-8').write('\n'.join(d) + '\n')
        out = os.path.join(self.dir, '%s_share_%s.zip' % (self.stem, self.stamp))
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(delivery, 'DELIVERY.md')
            for f in files: z.write(f, rel(f))
        latest = os.path.join(self.dir, '%s_share.zip' % self.stem); shutil.copyfile(out, latest)
        rec = {'preset': 'share_pack', 'file': rel(out), 'latest': rel(latest), 'files': len(files) + 1, 'size_mb': round(os.path.getsize(out) / 1e6, 2), 'with_source': with_source}
        self.outputs.append(rec); self.log('  %-14s %s  %d files  %.1f MB' % ('share_pack', rec['file'], rec['files'], rec['size_mb']))
        return rec

    # ---- driver
    def run(self, presets, seconds=GIF_SECONDS, fill='band', with_source=False):
        self.log('EXPORT  %s  (%.2f s, %dx%d, master wav %s)' % (os.path.relpath(self.film, self.project), self.info['dur'], self.info['w'], self.info['h'],
                                                               'present' if os.path.exists(self.master) else 'MISSING'))
        for p in presets:
            if p not in PRESETS: raise SystemExit('unknown preset %r (choose from %s)' % (p, ', '.join(PRESETS)))
        order = [p for p in PRESETS if p in presets]            # share_pack last so it can pick up the variants
        for p in order:
            if p == 'gif_teaser': self.gif_teaser(seconds)
            elif p in ('vertical_9x16', 'square_1x1'): getattr(self, p)(fill)
            elif p == 'share_pack': self.share_pack(with_source)
            else: getattr(self, p)()
        man = os.path.join(self.dir, '%s_exports.json' % self.stem)
        json.dump({'film': os.path.relpath(self.film, self.project).replace('\\', '/'), 'when': self.stamp, 'outputs': self.outputs}, open(man, 'w', encoding='utf-8'), indent=1)
        self._tmp.cleanup()
        return self.outputs


def find_project(start=None):
    for base in (start, os.getcwd(), HERE):
        d = os.path.abspath(base or os.getcwd())
        for _ in range(6):
            if os.path.exists(os.path.join(d, 'film.json')): return d
            nd = os.path.dirname(d)
            if nd == d: break
            d = nd
    return os.path.abspath(start or os.getcwd())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project'); ap.add_argument('--film', help='film path relative to the project (default: film.json output)')
    ap.add_argument('--preset', default='', help='comma-separated: ' + ','.join(PRESETS)); ap.add_argument('--all', action='store_true')
    ap.add_argument('--seconds', type=float, default=GIF_SECONDS, help='gif_teaser length (default 12)')
    ap.add_argument('--fill', choices=('band', 'crop'), default='band', help='vertical/square framing (default band)')
    ap.add_argument('--with-source', action='store_true', help='share_pack: include the authored scene set')
    ap.add_argument('--json', action='store_true'); ap.add_argument('--selftest', action='store_true')
    ns = ap.parse_args(argv)
    if ns.selftest: return selftest()
    presets = list(PRESETS) if ns.all else [p.strip() for p in ns.preset.split(',') if p.strip()]
    if not presets: ap.print_help(); return 2
    ex = Exporter(find_project(ns.project), ns.film, verbose=not ns.json)
    outs = ex.run(presets, ns.seconds, ns.fill, ns.with_source)
    if ns.json: print(json.dumps(outs, indent=1))
    return 0


# ----------------------------------------------------------------------------------------------- selftest
def selftest():
    """A synthetic 6 s 1920x1080 'film' (testsrc2 + tone at -16 LUFS, credit stamped) in a temp project; every preset runs;
    outputs are probed for dimensions, duration, loudness, credit, and the share pack for its contents and refusals."""
    with tempfile.TemporaryDirectory(prefix='fde_export_selftest_') as td:
        out = os.path.join(td, 'out'); os.makedirs(out)
        json.dump({'name': 'film', 'output': 'out/Acme_Test_Film.mp4', 'bed': None}, open(os.path.join(td, 'film.json'), 'w'))
        json.dump({'hygiene_patterns': {'email': r'[\w.+-]+@[\w-]+\.[a-z]{2,}'}}, open(os.path.join(td, 'qa.json'), 'w'))
        json.dump({'claims': []}, open(os.path.join(td, 'claims.json'), 'w'))
        master, tone = os.path.join(out, 'master_film.wav'), os.path.join(td, 'tone.wav')
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000', '-t', '6',
            '-af', 'tremolo=f=0.5:d=0.6', '-ac', '2', '-c:a', 'pcm_s24le', tone])
        gain = LUFS_NARRATION - measure_loudness(tone)['I']        # a realistic master sits at -16 LUFS like build_film.py's
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', tone, '-af', 'volume=%.2fdB' % gain, '-c:a', 'pcm_s24le', master])
        raw = os.path.join(td, 'pre.mp4')                         # a dark scene with movement, fading from black like the film template
        sh(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30', '-i', master, '-t', '6',
            '-vf', 'eq=brightness=-0.35,fade=t=in:st=0:d=0.3', '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '256k', '-shortest', raw])
        sys.path.insert(0, os.path.join(HERE, '..', '..')); CR = importlib.import_module('credit')
        film = os.path.join(out, 'Acme_Test_Film.mp4'); CR.stamp(raw, film)
        open(os.path.join(out, 'Acme_Test_Film.srt'), 'w').write('1\n00:00:00,100 --> 00:00:02,000\nAcme is fictional.\n')
        ex = Exporter(td, verbose=True)
        outs = ex.run(list(PRESETS), seconds=2.0, fill='band')
        by = {o['preset']: o for o in outs}
        assert set(by) == set(PRESETS) | {'booth_loop_silent'}, sorted(by)
        assert abs(by['booth_loop']['dur'] - (6.0 + LOOP_PAD)) < 0.15 and by['booth_loop']['credit'] == 'PRESENT', by['booth_loop']
        assert by['booth_loop']['loop_seam_luma'][0] < 20 and by['booth_loop']['loop_seam_luma'][1] < 20, by['booth_loop']
        assert by['booth_loop_silent']['lufs'] is None and by['booth_loop_silent']['credit'] == 'PRESENT'
        assert by['linkedin']['w'] == 1920 and -17 <= by['linkedin']['lufs'] <= -15, by['linkedin']
        assert -15 <= by['youtube']['lufs'] <= -13 and by['youtube']['tp'] <= -1.0 and by['youtube']['video'].startswith('stream copy'), by['youtube']
        assert (by['vertical_9x16']['w'], by['vertical_9x16']['h']) == (1080, 1920) and by['vertical_9x16']['credit'] == 'PRESENT'
        assert (by['square_1x1']['w'], by['square_1x1']['h']) == (1080, 1080) and by['square_1x1']['credit'] == 'PRESENT'
        assert os.path.exists(os.path.join(out, 'Acme_Test_Film_vertical_9x16.captions.md'))
        assert by['gif_teaser']['w'] == 960 and abs(by['gif_teaser']['dur'] - (2.0 + GIF_CREDIT_HOLD)) < 0.3, by['gif_teaser']
        names = zipfile.ZipFile(os.path.join(td, by['share_pack']['latest'])).namelist()
        assert 'DELIVERY.md' in names and 'out/Acme_Test_Film.mp4' in names and 'out/Acme_Test_Film.srt' in names and 'out/Acme_Test_Film_linkedin.mp4' in names, names
        assert not any(n.startswith(('vo/', 'broll/')) or 'seg_' in n or n.endswith('.wav') for n in names), names
        # smart crop path + hygiene refusal
        ex2 = Exporter(td, verbose=False); ex2.run(['square_1x1'], fill='crop')
        assert ex2.outputs[0]['mode'] == 'crop' and 0 <= ex2.outputs[0]['crop_x'] <= 1920 - 1080
        open(os.path.join(td, 'claims.json'), 'w').write('{"claims": [{"phrase": "mail someone@example.com"}]}')
        try:
            Exporter(td, verbose=False).run(['share_pack']); raise AssertionError('share pack must refuse a hygiene hit')
        except RuntimeError as e:
            assert 'hygiene' in str(e)
    print('export selftest OK: booth_loop(+silent, seam) / linkedin / youtube(-14 linear, stream copy) / vertical_9x16 / square_1x1(band+crop) / gif_teaser / share_pack(+refusal)')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
