#!/usr/bin/env python3
"""
build.py — assemble the demo video from demo_config.py, fully scripted (ffmpeg only).

For each beat it:
  1) trims + concatenates the kept `spans` (dropping thinking/loading lags between them),
  2) covers the browser chrome with a color bar and applies privacy `masks`,
  3) time-fits the footage to the beat's narration (or freeze-holds if footage is short),
  4) optionally push-in `zoom`s for readability,
  5) overlays the narration MP3 (vo/<id>.mp3, delayed 150ms).
Then it normalizes the optional opener/outro and concatenates everything to out/demo.mp4,
and runs a QA pass (decode integrity, silence gaps, contact sheet).

    python gen_vo.py     # first, to create vo/*.mp3
    python build.py

Requires: ffmpeg + ffprobe on PATH.
"""
import os
import subprocess
from demo_config import BEATS, SRC, OPENER, OUTRO, W, H, FPS

HERE   = os.path.dirname(os.path.abspath(__file__))
VO_DIR = os.path.join(HERE, "vo")
OUT    = os.path.join(HERE, "out")
CLIPS  = os.path.join(OUT, "clips")
QADIR  = os.path.join(OUT, "qa")
for d in (OUT, CLIPS, QADIR):
    os.makedirs(d, exist_ok=True)

VO_LEAD   = 0.15   # seconds of silence before narration starts in each beat
VO_TAIL   = 0.40   # seconds of footage after narration ends
CHROME_H  = 98     # height of the top chrome-cover bar (px)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit("FFMPEG ERROR:\n" + " ".join(map(str, cmd)) + "\n" + p.stderr[-2000:])
    return p


def dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def build_beat(b):
    bid   = b["id"]
    spans = b["spans"]
    footage = sum(e - s for s, e in spans)
    vo = os.path.join(VO_DIR, bid + ".mp3")
    have_vo = os.path.exists(vo)
    vod = dur(vo) if have_vo else 0.0
    target = round((vod + VO_TAIL) if have_vo else footage, 3)
    freeze = float(b.get("freeze", 0) or 0)

    # 1) trim + concat kept spans
    parts, labels = [], []
    for i, (s, e) in enumerate(spans):
        parts.append(f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS[c{i}]")
        labels.append(f"[c{i}]")
    fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(spans)}:v=1[cat];"

    # 2) chrome-cover bar + privacy masks (native coords, before time-fit)
    chain = "[cat]"
    filters = []
    if b.get("chrome"):
        filters.append(f"drawbox=x=0:y=0:w={W}:h={CHROME_H}:color={b['chrome']}:t=fill")
    filters += list(b.get("masks", []))

    # 3) time-fit (or freeze) then normalize fps
    if freeze > 0:
        filters += ["setpts=PTS-STARTPTS", f"fps={FPS}",
                    f"tpad=stop_duration={freeze}:stop_mode=clone"]
    else:
        factor = round(target / footage, 5) if footage else 1.0
        if factor > 1.5:
            print(f"  ! {bid}: factor {factor} (>1.5) — footage much shorter than VO; consider `freeze`.")
        filters += [f"setpts={factor}*(PTS-STARTPTS)", f"fps={FPS}"]

    # 4) optional push-in zoom (hold 1.5s, ramp to 1.10, then hold), focused on (fx,fy)
    if b.get("zoom"):
        fx, fy = b["zoom"]
        z = "if(lte(on,45),1.0,min(1.0+(on-45)*0.00040,1.10))"
        filters.append(f"zoompan=z='{z}':d=1:x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}':"
                       f"s={W}x{H}:fps={FPS}")

    chain += ",".join(filters) + "[v]"
    fc += chain

    vpath = os.path.join(CLIPS, bid + "_v.mp4")
    run(["ffmpeg", "-y", "-i", SRC, "-filter_complex", fc, "-map", "[v]", "-an",
         "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", vpath])

    # 5) attach audio: narration (delayed) or silence
    apath = os.path.join(CLIPS, bid + ".mp4")
    if have_vo:
        run(["ffmpeg", "-y", "-i", vpath, "-i", vo,
             "-filter_complex", f"[1:a]adelay={int(VO_LEAD*1000)}:all=1,apad[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-ac", "2", "-shortest", apath])
    else:
        run(["ffmpeg", "-y", "-i", vpath, "-f", "lavfi", "-i",
             "anullsrc=channel_layout=stereo:sample_rate=48000",
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", apath])

    fit = f"freeze={freeze}" if freeze > 0 else f"factor={round(target/footage,3) if footage else 1.0}"
    print(f"  {bid:16} vo={vod:5.1f} footage={footage:5.1f} {fit}"
          f"{' zoom' if b.get('zoom') else ''} -> {dur(apath):5.1f}s")
    return apath


def normalize_bookend(src, name):
    out = os.path.join(CLIPS, name)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}")
    if has_audio(src):
        run(["ffmpeg", "-y", "-i", src, "-vf", vf,
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", out])
    else:
        run(["ffmpeg", "-y", "-i", src, "-f", "lavfi", "-i",
             "anullsrc=channel_layout=stereo:sample_rate=48000", "-vf", vf,
             "-map", "0:v", "-map", "1:a", "-shortest",
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", out])
    return out


def qa(final):
    print("\nQA:")
    # decode integrity
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", final, "-f", "null", "-"],
                       capture_output=True, text=True)
    print("  decode:", "clean" if p.returncode == 0 and not p.stderr.strip() else "ERRORS ->\n" + p.stderr[:800])
    # silence gaps (>0.8s) — every screen should be narrated
    s = subprocess.run(["ffmpeg", "-v", "error", "-i", final, "-af",
                        "silencedetect=noise=-45dB:d=0.8", "-f", "null", "-"],
                       capture_output=True, text=True)
    gaps = [ln for ln in s.stderr.splitlines() if "silence_start" in ln]
    print("  silence gaps >0.8s:", "none" if not gaps else f"{len(gaps)} (check narration coverage)")
    for ln in gaps:
        print("   ", ln.strip())
    # contact sheet (every ~8s) for a quick eyeball
    sheet = os.path.join(QADIR, "contact.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-i", final, "-vf",
                    "fps=1/8,scale=320:-1,tile=6x5", sheet], capture_output=True, text=True)
    print("  contact sheet:", os.path.relpath(sheet, HERE))


if __name__ == "__main__":
    print("Building beats:")
    seq = []
    if OPENER:
        seq.append(normalize_bookend(OPENER, "z_opener.mp4"))
    for b in BEATS:
        seq.append(build_beat(b))
    if OUTRO:
        seq.append(normalize_bookend(OUTRO, "z_outro.mp4"))

    lst = os.path.join(CLIPS, "concat.txt")
    with open(lst, "w") as f:
        for p in seq:
            f.write("file '" + p.replace("\\", "/") + "'\n")

    final = os.path.join(OUT, "demo.mp4")
    pre = os.path.join(CLIPS, "precredit.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", pre])
    # MANDATORY: the FDE Demo Builder end-screen credit (credit.py). Not optional, no flag to skip.
    import credit
    credit.stamp(pre, final)
    if not credit.check(final):
        raise SystemExit("REFUSING: the FDE Demo Builder credit is not legible on the end screen.")
    print(f"\nFINAL: {os.path.relpath(final, HERE)}  ({round(dur(final),1)}s)")
    qa(final)
