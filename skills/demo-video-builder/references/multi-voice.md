# Multi-voice narration (v2)

One voice reads a script; a **cast** tells a story. This reference covers casting, the
placed-beat method for re-voicing a recording, and the failure modes that actually bite.

The default is a warm two- or three-role cast. A single voice is acceptable only when the brief asks for it or the
format is too short for a role handoff. Voice changes must mark a story function, not provide random variety.

## Casting

Two or three voices, each with a *job* — not voices for variety's sake:

| Role | Job | Good default |
|---|---|---|
| **Narrator** | the problem story, the turns, the close | `en-US-AndrewNeural` `+3%` |
| **Guide** | the product walkthrough ("here's the screen…") | `en-US-AvaNeural` `+4%` |
| **Character** | one persona with 1–3 short lines: an operator call, an exec question, a system refusal | `en-US-ChristopherNeural` `+2%` |

Edge TTS remains the zero-OCI-dependency default and sends text to Microsoft. With explicit cloud-TTS approval, OCI Speech
`TTS_2_NATURAL` can supply natural voices and authoritative word marks; see `oci-speech.md`. Do not silently fall
back between providers because a voice change alters duration, word timing, pronunciation, and the approved media
provenance.

Rules that held up across productions:

- **The character never explains the product.** One vivid line ("I've got twelve alerts and
  one crew") lands harder than a paragraph. Give explanations to the guide.
- **Hand the narrative *turns* to the narrator** even mid-walkthrough — the voice change
  itself signals "this is the important part".
- **Christopher reads ~10% slower** than Andrew/Ava at the same rate setting. Give his
  beats ~15% more budget or shorter lines. Slow spots that keep overrunning after two
  auto-bumps need a shorter line, not a faster rate (+16% starts to sound rushed).
- **Radio treatment** (`radio: True`) — bandpass 320–3300 Hz + slight drive — sells field
  radio / dispatch moments. Don't use it for office characters; it reads as "walkie-talkie".
- TTS reads long IDs and case numbers *very* slowly. "Case A B C one two three four" can eat
  4 seconds — abbreviate spoken IDs ("storm case open") and show the full ID on screen.

## Word timestamps (the sync backbone)

`gen_vo_multivoice.py` requests `WordBoundary` events from Edge TTS or word speech marks from OCI Speech and saves
per-word offsets to `vo/<name>_words.json`. Two facts to rely on:

1. **Same text + voice + speed reproduces stable audio and word times for a locked provider.** Cache and preserve
   the approved voice files; do not assume two providers or model revisions are interchangeable. You can
   re-render a scene without regenerating VO and nothing drifts.
2. **Hyphenated phrases are ONE token.** "twenty-three-point-five" arrives as a single word —
   the scene's `wt()` helper strips non-alphanumerics, so look it up as
   `twentythreepointfive`. When in doubt, print the tokens from the words JSON.

## Placed beats: re-voicing a screen recording

The v1 pipeline fits footage to VO. The v2 `PLACED` mode does the reverse — it pins narration
to a recording that keeps its original timing, so cursor movement and UI reveals stay in sync:

1. **Find the cut boundaries.** Extract 1 fps frames around candidate points
   (`ffmpeg -ss A -to B -i rec.mp4 -vf fps=1 f_%02d.jpg`) and pick the exact second the
   screen content changes. Transcribe the original audio (faster-whisper) to get every
   original narration beat's start time.
2. **Offsets**: `at = original_beat_start − cut_start`. Because the original narration was
   already aligned to the screen, placing new lines at the same offsets keeps them aligned.
3. **Budgets**: `budget = next_beat_at − this_beat_at − 0.3`. The generator re-renders an
   overrunning beat up to twice at +7% rate each, then WARNs. On a WARN: shorten the line
   first; shifting the beat (if the target screen lingers) is the fallback — 1–1.5 s of
   drift is usually invisible.
4. **Verify placement** without listening:
   `ffmpeg -i vo_<seg>.mp3 -af silencedetect=noise=-38dB:d=1.2 -f null -` — each
   `silence_end` should match a beat's `at` (±0.2 s).
5. **Mux**: cut the recording video-only (add fade in/out), then map the placed VO over it
   with `apad` + `-shortest` (exact commands in `assemble.example.sh`).

## Levels

Don't loudnorm per beat (it pumps). Level-match the cast within about 2 dB, then apply one
`loudnorm=I=-16:TP=-1.5:LRA=13` on the **final concatenated mix** and spot-check with
`volumedetect` at a few points per segment — means within ~2 dB of each other is done.
The radio filter chain already compensates its own level.

## QA that catches real bugs

- `silencedetect` offsets vs the beat map (above) — catches placement mistakes.
- One QA still per beat at `at + 1s` over the recording — catches "line lands on the wrong
  screen" (wrong cut boundary math) which audio checks can't see.
- Listen to the first 20 seconds of every **voice transition** — clipped starts mean a beat
  overlaps the previous one's trailing silence (edge-tts adds ~0.5 s tail; overlaps ≤0.3 s
  are inaudible, more is not).
