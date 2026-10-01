---
# design.example.md — the identity of the RECREATED layers (title card, lower thirds, call-outs, closing card).
# Copy to <project>/design.md. Product footage keeps its own palette; gates/text_gate.py scans authored CSS/JS only.
# Everything here is fictional (Acme). Tokens come from a capture of the real product + the house identity, never from memory.
name: acme-booth
source: "ground/ink from the house identity; accent and paper measured on the sample recording's own UI (extract_clips.py median still)"
colors:
  ground: "#082A34"        # the one ground
  ink: "#E9F3F9"           # the one ink
  accent: "#E56B5E"        # the focal element only — never a second emphasis hue
  muted: "#81A9AB"         # labels, captions (3-step ladder: ink → muted → ground)
  paper: "#FFFFFF"         # the product's page colour, allowed only behind footage (clipWrap)
  black: "#05161C"         # head fade plate (tinted toward the ground, not pure #000)
  ground2: "#204A56"       # the ground gradient's lighter stop
  ink_soft: "#ECDEC3"      # subtitles on the cards (cream)
  gold: "#E8C874"          # the one warm highlight on the closing card
allow_alpha: true          # rgba() of a declared colour counts as on-palette
type:
  display: { family: "Georgia, serif", weight: 400, px: 64, tracking: "-0.01em", lh: 1.1 }
  sans:    { family: "\"Helvetica Neue\", Arial, sans-serif", weight: 400, px: 22, lh: 1.4 }
  label:   { family: "Arial, sans-serif", weight: 600, px: 13, tracking: "0.12em", upper: true }
  mono:    { family: "Consolas, monospace", weight: 400, px: 18 }
fonts: ["Georgia", "Helvetica Neue", "Arial", "Segoe UI", "Consolas"]
scale:                     # stage px at 1280×720 (× 1.5 = 1080p): full-screen floor 60 / 20 / 16 px → 40 / 14 / 11 stage px
  headline_min: 40
  body_min: 14
  label_min: 11
  justify_below: 16        # any authored font-size under 16 stage px (24 px at 1080p) needs a reason in a comment
radii: [0, 4]              # px; nothing rounder on a booth screen
borders: [2, 3]            # px; 1 px vanishes on video
shadows: none              # flat depth; emphasis through inversion and scale
keepout: 0.17              # bottom 17 % of the canvas reserved for captions + credit
eases: { push: sine-out, pan: sine-in-out, scroll: cubic-out, reveal: power4-out, exit: sine-in }
motion: { enter_s: [0.3, 0.6], exit_s: [0.2, 0.35], stagger_total_s: 0.5, first_motion_s: 0.2, offset_after_cut_s: [0.1, 0.3] }
bans: [gradient-text, left-stripe, pure-bw, gradient-ground, bouncy-ease, banned-font, screensaver-drift, ghost-opacity]
---

# Acme booth — design spec for the recreated layers

The frontmatter is normative: exact hex, families, weight relationships, radii, borders, depth. The prose is
judgement. Brand is strict; layout is free — type sizes, spacing, decorative opacity and border weight are
adapted for video (1 px borders and 6 % shadows vanish on a booth screen).

## Two-colour discipline
One ground, one ink. A bigger moment gets bigger through inversion (ink card on the ground, ground text on an
ink card), scale (a 5 cqw word next to a 1.6 cqw label) or density (one line alone on the canvas). The accent
is spent on exactly one focal element per beat — a rule, a boxed row, a stat — at full saturation; as
atmosphere it sits at 15–25 % opacity, never under 10 % (invisible after H.264). Neutrals are tinted toward
the ground hue; nothing is pure #000 or #fff.

## Type scale (1280×720 stage, DPR 1.5)
| Role | Stage px | At 1080p | Notes |
|---|---|---|---|
| display | 64 (h1, ≤ 3 words) / 44 (h2, 4–6) / 32 (h3, 7+) | 96 / 66 / 48 | tracking −0.03…−0.05 em at display sizes; headline block ≤ 78 % of the width |
| body | 22 | 33 | light-on-dark: weight 350 instead of 400, line-height +0.05–0.1 |
| label | 13–16 | 20–24 | uppercase, +0.12 em tracking; legibility floor ≈ 1.4 % of the width (18 stage px) |
| mono / digits | 18 | 27 | `font-variant-numeric: tabular-nums` wherever digits stack |

Fit to measure: ≤ 3 words → h1, 4–6 → h2, 7+ → h3. Three seconds on screen must be readable in two: fewer
words, larger type. In-feed destinations (LinkedIn/X) scale everything ×1.5 again.

## Spacing and depth
Padding 40–90 stage px (60–140 at 1080p); content anchored to an edge or a zone (60/40 split), not centred and
floating. Two focal points minimum per recreated frame; three depth layers (ground treatment, content, one
structural accent). Borders 2–3 px, radii 0 or 4 px, no shadows. Nothing authored below 83 % of the height.

## Motion profile
Entrances 0.3–0.6 s with an `-out` ease, exits 0.2–0.35 s with an `-in` ease, moves `-in-out`; a stagger of
several elements finishes inside 0.5 s in order of importance (the first thing to appear is the most
important). First visible motion within 0.2 s of a beat; the first animation after a cut is offset 0.1–0.3 s.
Speed is weight: 0.15–0.3 s energetic, 0.3–0.5 professional, 0.5–0.8 gravity, 0.8–2.0 cinematic; the slowest
beat is about 3× slower than the fastest. No bouncy eases unless the beat is explicitly playful. No breathing
loops, no glow drift, no slow push in the back half of a beat — reveal the next piece on its spoken word.

## Craft bar (eyeball tests before the sheet goes out)
- Squint: one element dominates at 3–6× its neighbour.
- Silence: cover the captions — does the frame still say the beat's one thing?
- Restraint: could one more element be removed without losing the point? Remove it.
- Reference: name the film this frame wants to resemble and what its failure version looks like.
- Numbers: never invent a figure, percentage or date. Render "— figure —" or "+NN %" until the script and the
  screen supply it; a directional chip needs a real comparison on screen.
