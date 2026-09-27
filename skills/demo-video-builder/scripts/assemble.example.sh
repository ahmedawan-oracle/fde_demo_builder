#!/bin/sh
# assemble.example.sh — concat b-roll acts + re-voiced recording segments into the master (v2).
#
# Pattern: animated segments record ~2.4 s past their VO; trim each at TOTAL + ~1.9 s
# (where the built-in fade-to-black completes). Recording segments are used full length.
# One loudnorm on the final mix keeps all voices at one level. Copy, rename, edit.
cd "$(dirname "$0")"

# Trim points derived from the measured VO, never hardcoded:
OP=$(python -c "import json;print(json.load(open('vo/opener_phases.json'))['total']+1.9)")
FI=$(python -c "import json;print(json.load(open('vo/finale_phases.json'))['total']+2.1)")

ffmpeg -y -i out/seg1_opener.mp4 -i out/seg2_walkthrough.mp4 -i out/seg3_finale.mp4 \
 -filter_complex "
[0:v]trim=0:${OP},setpts=PTS-STARTPTS[v0];[0:a]atrim=0:${OP},asetpts=PTS-STARTPTS[a0];
[1:v]setpts=PTS-STARTPTS[v1];[1:a]asetpts=PTS-STARTPTS[a1];
[2:v]trim=0:${FI},setpts=PTS-STARTPTS[v2];[2:a]atrim=0:${FI},asetpts=PTS-STARTPTS[a2];
[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a];
[a]loudnorm=I=-16:TP=-1.5:LRA=13[am]" \
 -map "[v]" -map "[am]" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 \
 -c:a aac -b:a 192k -ar 44100 -ac 2 -movflags +faststart \
 out/demo_precredit.mp4

# MANDATORY: stamp and verify the FDE Demo Builder end-screen credit (never skip this step)
python credit.py stamp out/demo_precredit.mp4 out/demo_final.mp4 && python credit.py check out/demo_final.mp4 || exit 1

# Reminder: a recording segment is built by muxing its placed VO over the video-only cut:
#   ffmpeg -y -ss <cutStart> -to <cutEnd> -i recording.mp4 \
#     -vf "fps=30,format=yuv420p,fade=t=in:st=0:d=0.4" -an -c:v libx264 -crf 20 out/walk_v.mp4
#   ffmpeg -y -i out/walk_v.mp4 -i vo_walkthrough.mp3 -filter_complex "[1:a]apad[a]" \
#     -map 0:v -map "[a]" -shortest -c:v copy -c:a aac out/seg2_walkthrough.mp4
