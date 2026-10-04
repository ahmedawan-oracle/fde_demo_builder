# ffmpeg gotchas (read before debugging)

These are the pitfalls that silently produce a stale, black, soundless, or truncated file. Most "why is
the output wrong?" moments are here.

- **Trim/seek before the right input.** Put `-ss`/`-t` **before** the `-i` you want to seek, and never
  between the video input and a second (audio) input — it will silently truncate the wrong stream. In
  filtergraphs, prefer `trim=start:end,setpts=PTS-STARTPTS` per input.

- **`setpts` must reset the origin.** Use `setpts=FACTOR*(PTS-STARTPTS)`, not `setpts=FACTOR*PTS`. With a
  non-zero starting PTS the latter offsets the whole clip and playback breaks.

- **Concat demuxer needs uniform inputs.** All segments must share codec/params (same WxH, fps, pixel
  format, and audio codec/rate/channels). Normalize every clip *and* the opener/outro to the same spec
  (this builder encodes everything as 1920x1080 / 30fps / yuv420p h264 + 48kHz stereo aac). Mismatches
  cause glitches or dropped audio at the joins.

- **Concat list paths.** Use forward-slash absolute paths (`C:/work/acme-demo/clip.mp4`). A Git-Bash `$(pwd)`
  style `/c/...` path can make ffmpeg silently read nothing and emit a stale/short file.

- **A clip with no audio breaks concat.** If a segment (or a bookend) has no audio track, add silence
  (`-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000`) so every segment has audio. `build.py`
  does this automatically.

- **VO overlay timing.** Delay narration slightly and pad it so `-shortest` cuts to the video, not the
  audio: `[1:a]adelay=150:all=1,apad`. Make the beat ~0.4s longer than the VO so it doesn't end abruptly.

- **Slow-motion freeze.** Time-fitting with a large `setpts` factor (footage much shorter than VO) looks
  like a stall. Above ~1.3×, prefer a **freeze-hold** instead: `tpad=stop_duration=N:stop_mode=clone`
  after `fps`. Holding a fully-rendered answer reads as "let it sink in," not "it froze."

- **`.hidden{display:none}` in opener HTML** gets overridden by a later `display:flex`. Use `!important`
  or toggle via opacity/transform (the example scene uses opacity/transform, which is safe).

- **Animation runs ahead of VO.** If your opener animates from page load, it finishes before recording is
  meaningful. Start it *after* recording begins via `window.__start()` (render_bookend.js calls it).

- **Headless-Chrome scale.** Pass `--force-device-scale-factor=1` and set a 1920x1080 viewport, or the
  recording comes out at the wrong resolution / DPI.

- **Machine saturation.** Many parallel headless-Chrome renders can exhaust the machine and time out.
  Render bookends one at a time; the ffmpeg beats are cheap and can run sequentially in `build.py`.

- **`zoompan` on video.** Keep it identity at zoom=1.0 (`s=` equal to the frame size) so it doesn't
  upscale/soften when not zooming; ramp modestly (≤1.10). Apply it **after** fps normalization so the
  per-frame `on` counter is stable.
