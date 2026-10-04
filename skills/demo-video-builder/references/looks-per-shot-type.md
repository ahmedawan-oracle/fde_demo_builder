# Looks per shot type — one look for each kind of shot, checked per beat (v5.1)

A film does not have one look. Product footage is shown as recorded; recreated cards carry the house identity; a
title may spend an effect a card may not; people — a presenter on camera — take a soft treatment and never a
glitch. `design.md` declares one look per shot type, every beat names its type, and `gates/look_gate.py` reads
the authored CSS and effect calls against the look of the beat they belong to.

## Declare the looks (`design.md` frontmatter)

```yaml
looks:
  product:   { forbid: [haze, grain, vignette, bloom, blur, filter, blend, recolour], selectors: ["#clipWrap", "#clipImg", "#camera"] }
  recreated: { forbid: [glitch], selectors: [".card"] }
  title:     { forbid: [], selectors: ["#titleCard", "#closeCard"] }
  people:    { forbid: [glitch, sharpen, chromatic], selectors: [".people"] }
```

`forbid` lists effect names (`haze grain vignette bloom blur filter blend recolour glitch chromatic sharpen`);
`selectors` are the ids / classes of the elements that carry that look. Without a `looks:` block the defaults
above apply — product forbids every cosmetic effect, the footage rule the grade gate already enforces, now by beat.
In the scene an element may also carry `data-look="product"` to join a look's selector set.

## Type every beat (`STORYBOARD.md`)

`- look: product | recreated | title | people`. When the line is absent: `type:` is read if it names a look;
otherwise `real: recorded` → product, `real: recreated` → title when the phase is title / open / close, recreated
otherwise. An unknown look name fails `look types`.

## What the gate checks

| Gate | Checks |
|---|---|
| `look types` | every beat resolves to a declared look; the note counts beats per look and names the design file |
| `look effects` | **scene:** a CSS rule on one of a look's selectors with `filter` (other than none), `backdrop-filter` or `mix-blend-mode`, or a `VFX.<effect>(` / `GL.pass` / `GL.chain(` call whose arguments name the selector, applying an effect the look forbids. **storyboard:** a beat's `motion:` / `screen:` naming a forbidden effect for its look without a negation ("no haze" is a constraint, not a use) |

Product footage is never graded: a filter on the lane is a FAIL whatever the beat says, and `grade_gate`'s
`effects off footage` keeps saying so from the other side. The point of the per-type rule is the other direction —
a title is allowed its shard glass and its light sweep, a card is allowed its lamp, and the gate stops asking the
same question of every element.

Selftest: `python gates/look_gate.py --selftest` — a design with three looks, a storyboard with four beats (one
unknown look), a clean scene and a scene with saturate on the lane, a blend on a card, a haze call and a GL grain
pass; the storyboard negation; the no-design default path.
