# Cinematic grammar for product films (v3)

Measured rules that separate a booth-ready film from a screen recording with music.

## Story shape (2–3 min booth/session film)

| Act | Share | What happens |
|---|---|---|
| Cold open | 15–25 % | the **problem**, as a recreated animated scene (not a slide): stakes, a number, a persona's line |
| Title + thesis | 5–10 % | the promise in one sentence + an honesty caption ("Fictional company · synthetic data") |
| The demo | 45–60 % | real product footage in persona acts ("THE ANALYST", "THE BUSINESS USER"), lower-third per act |
| Turn / payoff | 10 % | the finding, and **what the product won't claim** (the trust beat) |
| What's next | 5–10 % | labelled as roadmap, never as available |
| Close | 3–5 % | a two- or three-line antithesis card; the mandatory credit sits in its footer |

## Voices

Use two or three warm role-based voices: narrator for the story and turns, guide for product proof, and at most one
first-person customer persona. A fourth product voice is useful only when the product itself speaks. Edge TTS is the
default; approved OCI Speech `TTS_2_NATURAL` is optional. Speak on-screen text exactly as shown and leave a tight,
audible handoff between speakers.

## Camera

- **Establish, then push.** Each product beat opens on the original full screen (1.0x) and pushes in.
- Push ×1.3–2.2 in 0.9–1.4 s (sine-out for pushes, sine-in-out for pans and scrolls), hold 2–2.5 s,
  pull back in ~1 s. Push onto the thing the voice is naming, landing on its word.
- Nothing static for more than ~5 s: long reads get a slow push (2–3 %/s).
- Browser-eased scrolls: `1 − (1 − u)³` over ~1.1 s, starting ~0.3 s before the word.
- Use clock-driven CSS/Canvas transforms or FDE camera primitives, which retain subpixel positions. Do not build
  camera motion from integer `crop`/`zoompan` steps, alternate between neighbouring crop rectangles, or add sinusoidal
  wandering. If the only source is a low-rate screenshot sequence, select a clean parked frame and move the camera
  deterministically instead of duplicating frames to imitate a 30 fps recording.
- End a shot at zero or near-zero camera velocity before a dissolve, or match its position and velocity into the next
  shot. Run `motion_diag.py --spikes --pan-halves`; inspect every reported boundary before delivery.

## Pointer and clicks

- Capture real pointer telemetry where possible. With median stills, restore that path using `lib/cursor.js` so the
  cursor travels with the product pixels through camera moves.
- Show a restrained click ring and short press response on meaningful actions. Keep the real response visible and
  place any click sound away from speech onsets.
- Never add a decorative click, move the pointer to an element that was not used, or imply a result the capture does
  not contain.

## Cuts

- Hard cut on every screen change; cut on the word that names the new screen.
- Seamless hand-offs (still → real motion of the same screen) are not cuts.
- Never cut to a flat, empty plate; if a card fades in, its first words must already be inked.

## Recreated scenes

Clock-driven HTML/Canvas (see `broll-scenes.md`): one accent colour, particle fields, odometer digits
(0.5–0.8 s), typed questions at 55–90 c/s in word chunks, lower thirds with a label + one line.
Recreate *ideas* (architecture, the problem), never fake the product UI inside the demo act.

## Trust

- Every spoken number is visible on screen at that moment (`claims.json`).
- If the product states a limitation, **use it** — the film's trust beat.
- No availability claims for pre-GA capability; roadmap is labelled "where it goes next".
