#!/usr/bin/env python3
"""
gen_vo_multivoice.py — multi-voice narration with word-level timestamps (v2).

Reads VOICES / SCENES / PLACED from vo_script.py (see vo_script.example.py) and produces,
per scene or per recording segment:

  vo/<name>_<phase>.mp3          one MP3 per phase/beat (its cast voice)
  vo_<name>.mp3                  the assembled track for that scene/segment
  vo/<name>_phases.json          {"total": s, "phases":[{"name","start","dur"}]}
  vo/<name>_words.json           per-phase word boundaries (for word-synced animation)
  scenes/timing_<name>.js        window.PHASES / window.WORDS for b-roll scenes (SCENES only)

Two kinds of narration:

  SCENES  — sequential: phases play back-to-back with a small breath gap. Used for
            animated b-roll (openers, interstitials, finales). The scene HTML loads
            timing_<name>.js and keys every animation to spoken words (see
            references/broll-scenes.md).

  PLACED  — beats pinned to fixed offsets over a silent bed, so narration lands exactly
            on the on-screen action of a screen recording you re-voice. Each beat has a
            time `budget`; if the rendered audio overruns it, the beat is re-rendered a
            notch faster (up to twice) and a WARN is printed if it still doesn't fit.
            (See references/multi-voice.md for how to derive offsets and budgets.)

Usage:
    pip install edge-tts
    python gen_vo_multivoice.py                # everything in vo_script.py
    python gen_vo_multivoice.py opener         # just one scene/segment by name

Voice-casting tips (from real productions):
  - 2–3 voices is the sweet spot: a narrator (story), a guide (product walkthrough),
    and a character (an operator/executive quote, a refusal line). More gets noisy.
  - en-US-ChristopherNeural reads ~10% slower than Andrew/Ava — budget accordingly.
  - `radio: True` on a phase applies a handheld-radio bandpass — great for field/ops
    "voice moments". Skip it for office/desk characters.
  - Hyphenated phrases arrive as ONE WordBoundary token ("twenty-three-point-five" is
    a single word for sync purposes). Spell numbers the way they should sound.
"""
import asyncio
import json
import os
import subprocess
import sys

import edge_tts

from vo_script import VOICES, SCENES, PLACED

HERE = os.path.dirname(os.path.abspath(__file__))
VO_DIR = os.path.join(HERE, "vo")
SCENE_DIR = os.path.join(HERE, "scenes")
os.makedirs(VO_DIR, exist_ok=True)
os.makedirs(SCENE_DIR, exist_ok=True)


def dur(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True)
    return float(out.stdout.strip())


def bump(rate, pct):
    return f"+{int(rate.strip('+%')) + pct}%"


async def tts(text, voice, rate, path, tries=4):
    """Render one phrase; capture WordBoundary events for word-level sync."""
    for i in range(tries):
        try:
            words, audio = [], b""
            com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
            async for ch in com.stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    words.append({"t": round(ch["offset"] / 1e7, 3), "w": ch["text"]})
            if not audio:
                raise RuntimeError("no audio returned")
            with open(path, "wb") as fh:
                fh.write(audio)
            return words
        except Exception as e:                        # transient network errors are common
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} for {os.path.basename(path)}: {e}")
            await asyncio.sleep(2 * (i + 1))


def radioize(path):
    """Handheld-radio treatment: band-limit + a touch of drive, loudness preserved."""
    tmp = path.replace(".mp3", "_r.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-af",
         "highpass=f=320,lowpass=f=3300,volume=1.6,alimiter=limit=0.92,volume=0.85",
         "-c:a", "libmp3lame", "-q:a", "2", tmp],
        check=True, capture_output=True)
    os.replace(tmp, path)


def build_track(out_path, placed, total):
    """Mix per-phase MP3s at offsets over a silent bed of `total` seconds."""
    args = ["ffmpeg", "-y", "-f", "lavfi", "-t", f"{total}", "-i", "anullsrc=r=44100:cl=mono"]
    for f, _ in placed:
        args += ["-i", f]
    fc, labels = "", ["[0:a]"]
    for i, (f, off) in enumerate(placed):
        fc += f"[{i + 1}:a]adelay={int(off * 1000)}:all=1[d{i}];"
        labels.append(f"[d{i}]")
    fc += "".join(labels) + f"amix=inputs={len(labels)}:normalize=0[a]"
    args += ["-filter_complex", fc, "-map", "[a]", "-c:a", "libmp3lame", "-q:a", "2", out_path]
    subprocess.run(args, check=True, capture_output=True)


def write_meta(name, total, phases, words, emit_timing_js):
    json.dump({"total": round(total, 3), "phases": phases},
              open(os.path.join(VO_DIR, f"{name}_phases.json"), "w"), indent=1)
    json.dump(words, open(os.path.join(VO_DIR, f"{name}_words.json"), "w"), indent=1)
    if emit_timing_js:
        with open(os.path.join(SCENE_DIR, f"timing_{name}.js"), "w", encoding="utf-8") as fh:
            fh.write(f"window.PHASES={json.dumps({'total': round(total, 3), 'phases': phases})};\n")
            fh.write(f"window.WORDS={json.dumps(words)};\n")
        # node twin for build/QA tools (check_cues.js, export_timeline.js)
        with open(os.path.join(SCENE_DIR, f"timing_{name}_data.js"), "w", encoding="utf-8") as fh:
            fh.write("module.exports=" + json.dumps({"PHASES": {"total": round(total, 3), "phases": phases}, "WORDS": words}) + ";\n")


async def gen_scene(name, spec):
    """Sequential scene: phases back-to-back with a breath gap."""
    gap = spec.get("gap", 0.4)
    pad = spec.get("pad", 0.0)          # extra lead-in before each phase (keeps onsets off the previous tail)
    phases, words, files, t = [], {}, [], 0.0
    for ph in spec["phases"]:
        t += pad
        voice, rate = VOICES[ph["voice"]]
        f = os.path.join(VO_DIR, f"{name}_{ph['name']}.mp3")
        w = await tts(ph["text"], voice, ph.get("rate", rate), f)
        if ph.get("radio"):
            radioize(f)
        d = dur(f)
        phases.append({"name": ph["name"], "start": round(t, 3), "dur": round(d, 3)})
        words[ph["name"]] = w
        files.append((f, t))
        t += d + gap + ph.get("pause", 0.0)      # optional dramatic silence after a phrase
    total = t - gap
    build_track(os.path.join(HERE, f"vo_{name}.mp3"), files, total + 0.6)
    write_meta(name, total, phases, words, emit_timing_js=True)
    print(f"[{name}] total={total:.2f}s")
    for p in phases:
        print(f"   {p['name']:12s} start={p['start']:7.2f} dur={p['dur']:5.2f}")


async def gen_placed(name, spec):
    """Placed segment: beats pinned at offsets; auto rate-bump on budget overrun."""
    seg_len = spec["length"]
    phases, words, placed = [], {}, []
    for b in spec["beats"]:
        voice, rate = VOICES[b["voice"]]
        f = os.path.join(VO_DIR, f"{name}_{b['name']}.mp3")
        r = b.get("rate", rate)
        for attempt in range(3):
            w = await tts(b["text"], voice, r, f)
            d = dur(f)
            if d <= b["budget"] - 0.25 or attempt == 2:
                break
            r = bump(r, 7)
            print(f"   {b['name']}: {d:.2f}s > budget {b['budget']}s -> rate {r}")
        if b.get("radio"):
            radioize(f)
        d = dur(f)
        if d > b["budget"]:
            print(f"   WARN {b['name']}: {d:.2f}s exceeds budget {b['budget']}s "
                  f"(shorten the line, or shift the next beat)")
        phases.append({"name": b["name"], "start": b["at"], "dur": round(d, 3)})
        words[b["name"]] = w
        placed.append((f, b["at"]))
    build_track(os.path.join(HERE, f"vo_{name}.mp3"), placed, seg_len)
    write_meta(name, seg_len, phases, words, emit_timing_js=False)
    print(f"[{name}] placed {len(placed)} beats over {seg_len}s")
    for p in phases:
        print(f"   {p['name']:6s} @{p['start']:7.2f} dur={p['dur']:6.2f}")


async def main():
    which = set(sys.argv[1:])
    for name, spec in SCENES.items():
        if not which or name in which:
            await gen_scene(name, spec)
    for name, spec in PLACED.items():
        if not which or name in which:
            await gen_placed(name, spec)


if __name__ == "__main__":
    asyncio.run(main())
