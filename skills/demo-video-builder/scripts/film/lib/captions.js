/* captions.js — the burned-in caption lane on the narration clock (window.CAP / module.exports).

   Every spoken phrase has one of three fates:
     drop    not shown (fillers in real-audio segments; a phase whose text is already on screen)
     rail    the verbatim lower-third lane — one group at a time, ≤ 2 lines, glyph-local legibility (DEFAULT)
     embed   the phrase becomes the picture: big, centred, one caption at a time (keynote/title beats)
   The lane is an OVERLAY composited on the finished frame, never a reserved band: compose on the true centre
   and only keep critical small text out of the bottom ~80 px centre span. The one real keep-out is the
   mandatory credit footer (bottom ~120 px of 1080, last 4 s) — the lane hides itself there.

   Browser:  <div id="cap"></div> in screen space OUTSIDE #camera (z above footage, below #black), then
               const lane = CAP.build(TX, window.CAPTIONS);     // CAPTIONS = scenes/captions_data.js (node export)
               frame(t) { … lane.draw($('#cap'), t, { lift: ltUp ? ltTopPx : 0 }); … }
   Node:     node scenes/lib/captions.js scenes/timing_film_data.js scenes/captions.json
               → out/caption_groups.json (SRT/VTT twin, QA) + scenes/captions_data.js (window.CAPTIONS)
   The grouping is pure arithmetic on WORDS, so browser and node produce identical groups; the sidecar
   (tools/captions_srt.py) is written from the same JSON, so burn-in and SRT cannot diverge.

   Measured defaults (1080-line frame, scaled by stage height): body 0.045*h, weight 600, box bottom 112 px up (inside title-safe),
   max-width 80 %, fade 0.12 s up / 0.15 s down (exits ≈ 60–75 % of entrances), one family + two weights,
   ≤ 6 words / 2.5 s / 42 chars per line / 2 lines, ≥ 0.5 s on screen, group.in = first − 0.08,
   group.out = min(next.in − 0.05, last.end + 0.6). Active-word envelope: attack 0.12 s, release 0.3 s,
   rest 0.55, scale ≤ 1.04 (rail allows ≤ 1.1). Doctrine: references/captions-and-overlays.md.

   v5 word-level styles (references/karaoke-kinetic-captions.md):
     karaoke   the spoken word lights up on its own word time: colour → accent over 0.12 s, weight 600 → 700 by
               cross-fading a second, bold layer (the bold layer is in-flow at opacity 0, so the word's box is
               already the bold width and nothing reflows), a 1.06 scale pulse that peaks at 0.06 s and is back
               at 1.0 by 0.12 s; past words settle to ink at 0.82 opacity over 0.3 s, future words wait at 0.55.
     kinetic   each caption line arrives as a word waterfall (word i enters at Σ 0.06·0.84^j, cumulative delay
               capped at 0.3 s, each word 0.25 s rise 10 px + fade) and the whole caption leaves as one block.
   Both keep every lane rule: wrap honours maxChars, one group at a time, lane position, data-ov="cap". */
(function (root) {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rmp = (t, a, b) => (b <= a ? (t >= b ? 1 : 0) : clamp((t - a) / (b - a), 0, 1));
  const lerp = (a, b, x) => a + (b - a) * x;
  /* local eases (transform/opacity only — never letter-spacing, size or blur on word spans) */
  const EO2 = u => 1 - Math.pow(1 - clamp(u, 0, 1), 2);
  const EO3 = u => 1 - Math.pow(1 - clamp(u, 0, 1), 3);
  const EI2 = u => { u = clamp(u, 0, 1); return u * u; };
  const EXPO = u => (u >= 1 ? 1 : 1 - Math.pow(2, -10 * clamp(u, 0, 1)));
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');   // narration text → markup-safe
  const r3 = x => Math.round(x * 1000) / 1000;
  const IS_NODE = typeof module !== 'undefined' && module.exports && typeof window === 'undefined';

  /* ------------------------------------------------------------------ style presets (tokens at 1080p) ----
     font        local Windows/mac families only (never a web font URL: offline booth builds, determinism)
     sizeH       body size as a fraction of frame height (0.045 ≈ 48 px at 1080)
     bottomPx    baseline gap from the bottom edge at 1080 (scaled by h/1080)
     scrim       {kind:'shadow'|'pill'|'gradient'|'none', alpha}  — glyph-local, sized to the text box
     enter/exit  {dur, dy}  fade + small lift; exit ≈ 60–75 % of the entrance
     env         active-word envelope {attack, release, rest, scale}; perWord=false disables it
     fate        the default fate for groups drawn in this style ('rail' or 'embed') */
  const SANS = "'Segoe UI','Helvetica Neue',Arial,sans-serif";   // single-quoted families: safe inside style="…" attributes
  const MONO = "Consolas,'Courier New',monospace";
  const STYLES = {
    anchor:      { use: 'the quiet verbatim rail — pick it when unsure', font: SANS, weightBody: 600, weightEm: 700, sizeH: 0.045, bottomPx: 112,
                   ink: '#F2EFE9', dimInk: 'rgba(242,239,233,.55)', accent: '#EFCB9A', scrim: { kind: 'shadow', alpha: 0.65 }, align: 'center', case: 'none',
                   tracking: '0.012em', maxWords: 6, maxChars: 42, lines: 2, enter: { dur: 0.12, dy: 4 }, exit: { dur: 0.15, dy: 6 }, perWord: true,
                   env: { attack: 0.12, release: 0.3, rest: 0.55, scale: 0 }, fate: 'rail' },
    broadcast:   { use: 'white on a 40 % gradient pill, BBC-style line lengths, for busy footage', font: SANS, weightBody: 600, weightEm: 700, sizeH: 0.045, bottomPx: 112,
                   ink: '#FFFFFF', dimInk: 'rgba(255,255,255,.55)', accent: '#FFFFFF', scrim: { kind: 'pill', alpha: 0.40 }, align: 'center', case: 'none',
                   tracking: '0.01em', maxWords: 6, maxChars: 34, lines: 2, enter: { dur: 0.20, dy: 6 }, exit: { dur: 0.15, dy: 6 }, perWord: true,
                   env: { attack: 0.06, release: 0.3, rest: 0.55, scale: 0 }, fate: 'rail' },
    documentary: { use: 'bone on charcoal, zero animation, bottom-left block — gravitas beats, trust beat', font: SANS, weightBody: 500, weightEm: 700, sizeH: 0.045, bottomPx: 108,
                   ink: '#F5EFE6', dimInk: '#F5EFE6', accent: '#F5EFE6', scrim: { kind: 'shadow', alpha: 0.55 }, align: 'left', case: 'none',
                   tracking: '0.005em', maxWords: 6, maxChars: 42, lines: 2, enter: { dur: 0, dy: 0 }, exit: { dur: 0, dy: 0 }, tail: 0.5, perWord: false,
                   env: { attack: 0, release: 0, rest: 1, scale: 0 }, fate: 'rail' },
    keynote:     { use: 'the title / thesis beat: 2–5 words, dead centre, opaque white, one caption at a time', font: SANS, weightBody: 800, weightEm: 800, sizeH: 0.16, bottomPx: 0,
                   ink: '#FFFFFF', dimInk: '#FFFFFF', accent: '#FFFFFF', scrim: { kind: 'none', alpha: 0 }, align: 'center', case: 'upper',
                   tracking: '-0.045em', maxWords: 5, maxChars: 22, lines: 2, enter: { dur: 0.40, dy: 0, wipe: 'x' }, exit: { dur: 0.30, dy: 0 }, perWord: false,
                   env: { attack: 0, release: 0, rest: 1, scale: 0 }, fate: 'embed' },
    ink:         { use: 'near-black type for bright product screens (lane luma > 150); letterpress stillness, no float', font: SANS, weightBody: 600, weightEm: 700, sizeH: 0.045, bottomPx: 112,
                   ink: '#111418', dimInk: 'rgba(17,20,24,.55)', accent: '#B23A2E', scrim: { kind: 'pill', alpha: 0.92, light: true }, align: 'center', case: 'none',   // .92: a near-transparent plate over code/prose is text-on-text; the pill is glyph-local so the page stays visible around the words
                   tracking: '0.008em', maxWords: 6, maxChars: 42, lines: 2, enter: { dur: 0.12, dy: 0 }, exit: { dur: 0.12, dy: 0 }, perWord: true,
                   env: { attack: 0.12, release: 0.3, rest: 0.55, scale: 0 }, fate: 'rail' },
    conference:  { use: 'persona lines: dual-weight card (role 400 / line 700), swipe-in once then static, inline active word', font: SANS, weightBody: 700, weightEm: 700, sizeH: 0.042, bottomPx: 116,
                   ink: '#FFFFFF', dimInk: 'rgba(255,255,255,.62)', accent: '#EFCB9A', scrim: { kind: 'pill', alpha: 0.72, dark: '#16181d' }, align: 'left', case: 'none',
                   tracking: '0', maxWords: 6, maxChars: 40, lines: 2, enter: { dur: 0.40, dy: 0, swipe: true }, exit: { dur: 0.30, dy: 12 }, perWord: true,
                   env: { attack: 0.08, release: 0.25, rest: 0.35, scale: 0 }, fate: 'rail' },
    typewriter:  { use: "the product's own voice: mono, 30 ms per char, 600 ms cursor blink after the last char, one line", font: MONO, weightBody: 500, weightEm: 700, sizeH: 0.040, bottomPx: 112,
                   ink: '#E9F3F9', dimInk: '#E9F3F9', accent: '#E8C874', scrim: { kind: 'gradient', alpha: 0.40 }, align: 'center', case: 'none',
                   tracking: '0', maxWords: 8, maxChars: 48, lines: 1, enter: { dur: 0.08, dy: 0, cps: 33 }, exit: { dur: 0.15, dy: 0 }, perWord: false,
                   env: { attack: 0, release: 0, rest: 1, scale: 0 }, fate: 'rail' },
    clipwipe:    { use: 'clean per-word clip-path wipe; weight 300 → 700 between line 1 and line 2 — openers, chapter lines', font: SANS, weightBody: 300, weightEm: 700, sizeH: 0.05, bottomPx: 112,
                   ink: '#FFFFFF', dimInk: '#FFFFFF', accent: '#FFFFFF', scrim: { kind: 'shadow', alpha: 0.6 }, align: 'center', case: 'none',
                   tracking: '-0.01em', maxWords: 6, maxChars: 36, lines: 2, enter: { dur: 0.25, dy: 0, wipe: 'word' }, exit: { dur: 0.18, dy: 0 }, perWord: false,
                   env: { attack: 0, release: 0, rest: 1, scale: 0 }, weightLine2: 700, fate: 'rail' },
    karaoke:     { use: 'the spoken word lights up on its word time: accent colour, +100 weight via a bold overlay, 1.06 pulse; past 0.82, future 0.55', font: SANS, weightBody: 600, weightEm: 700, sizeH: 0.045, bottomPx: 112,
                   ink: '#E9F3F9', dimInk: 'rgba(233,243,249,.55)', accent: '#E8C874', scrim: { kind: 'shadow', alpha: 0.65 }, align: 'center', case: 'none',
                   tracking: '0.012em', maxWords: 6, maxChars: 42, lines: 2, enter: { dur: 0.12, dy: 4 }, exit: { dur: 0.15, dy: 6 }, perWord: true,
                   env: { attack: 0.12, release: 0.3, rest: 0.82, future: 0.55, scale: 0.06, pulse: 0.12 }, karaoke: true, fate: 'rail' },
    kinetic:     { use: 'word waterfall in (0.06 s × 0.84^i, cumulative ≤ 0.3 s, 0.25 s rise each), block out — chapter lines, recreated beats', font: SANS, weightBody: 700, weightEm: 700, sizeH: 0.05, bottomPx: 112,
                   ink: '#E9F3F9', dimInk: '#E9F3F9', accent: '#E56B5E', scrim: { kind: 'shadow', alpha: 0.6 }, align: 'center', case: 'none',
                   tracking: '-0.01em', maxWords: 6, maxChars: 36, lines: 2, enter: { dur: 0.25, dy: 10, waterfall: { gap0: 0.06, decay: 0.84, cap: 0.3 } }, exit: { dur: 0.18, dy: 8 }, perWord: false,
                   env: { attack: 0, release: 0, rest: 1, scale: 0 }, lead: 0.3, fate: 'rail' }
  };
  /* never on a booth film (register): highlight sweeps, neon, glitch, slam, emoji pops, gradient fills */
  const FORBIDDEN = ['highlight-sweep', 'neon', 'glitch', 'kinetic-slam', 'particle-burst', 'emoji-pop', 'gradient-fill', 'matrix-decode'];

  /* ------------------------------------------------------------------ text measurement ----
     Browser: canvas measureText (memoised; local fonts → stable). Node / fallback: chars × em-advance
     (measured on Windows: Segoe UI ≈ 0.45–0.48 em per char incl. spaces, Consolas 0.55; uppercase ×1.2 for
     proportional faces; 0.56 em is the unknown-family default). Default wrap mode is
     'estimate' so node (SRT) and browser (burn-in) break lines identically; the QA gate re-measures with the
     real TTF and fails any line wider than 92 % of the box. */
  const EM = [[/segoe/i, 0.47], [/arial|helvetica/i, 0.47], [/consolas|courier|mono/i, 0.55], [/georgia|serif/i, 0.46]];
  const memo = new Map();
  let ctx2d = null;
  function fontParts(font) {                       // 'weight sizepx family' → {weight, px, family}
    const m = /^\s*(\d{3}|bold|normal)?\s*([\d.]+)px\s+(.+)$/.exec(font) || [];
    return { weight: m[1] === 'bold' ? 700 : parseInt(m[1] || '400', 10), px: parseFloat(m[2] || '48'), family: m[3] || 'sans-serif' };
  }
  function estimate(text, font) {
    const f = fontParts(font);
    let em = 0.56; for (const [re, v] of EM) if (re.test(f.family)) { em = v; break; }
    const upper = text === text.toUpperCase() && /[A-Z]/.test(text) && !/mono|consolas|courier/i.test(f.family);
    return text.length * em * f.px * (upper ? 1.2 : 1) * (f.weight >= 700 ? 1.05 : 1);
  }
  function measure(text, font, mode) {
    const key = mode + '|' + font + '|' + text;
    if (memo.has(key)) return memo.get(key);
    let w;
    if (mode === 'canvas' && typeof document !== 'undefined') {
      if (!ctx2d) ctx2d = document.createElement('canvas').getContext('2d');
      ctx2d.font = font; w = ctx2d.measureText(text).width;
    } else w = estimate(text, font);
    memo.set(key, w); return w;
  }
  /* shrink-to-fit: from base px down to min px in `step` px until the string fits maxWidth on one line.
     Only shrinks; returns {px, fits}. Heroes should widen the box instead of going under their floor. */
  function fitText(text, o) {
    o = Object.assign({ font: '600 48px ' + SANS, maxWidth: 1600, base: 78, min: 42, step: 2, mode: 'estimate' }, o || {});
    const fam = fontParts(o.font);
    for (let px = o.base; px >= o.min; px -= o.step) {
      if (measure(text, fam.weight + ' ' + px + 'px ' + fam.family, o.mode) <= o.maxWidth) return { px: px, fits: true };
    }
    return { px: o.min, fits: false };
  }
  /* greedy wrap into ≤ maxLines; a 2-line result is balanced so no line dangles a single word */
  function wrap(words, font, maxWidth, maxLines, mode, maxChars) {
    mode = mode || 'estimate'; maxLines = maxLines || 2;
    const W = words.slice(), lines = []; let cur = [];
    const width = arr => measure(arr.join(' '), font, mode);
    const over = arr => width(arr) > maxWidth || (maxChars && arr.join(' ').length > maxChars);   // pixels AND the measured char cap
    for (const w of W) {
      if (cur.length && over(cur.concat(w))) { lines.push(cur); cur = [w]; } else cur.push(w);
    }
    if (cur.length) lines.push(cur);
    if (lines.length === 2 && W.length >= 3) {                // balance: pick the break that minimises the widest line
      let best = null;
      for (let k = 1; k < W.length; k++) {
        const a = W.slice(0, k), b = W.slice(k), wa = width(a), wb = width(b);
        if (wa > maxWidth || wb > maxWidth || over(a) || over(b)) continue;
        if (b.length === 1 && a.length > 2) continue;         // no dangling 1-word second line
        const m = Math.max(wa, wb); if (!best || m < best.m) best = { m: m, a: a, b: b };
      }
      if (best) return [best.a, best.b];
    }
    return lines;                                             // may exceed maxLines: the QA gate fails it
  }

  /* ------------------------------------------------------------------ word → caption grouping ----
     Editorial cuts: pause ≥ gap (0.35 s — our breath gaps come from vo_script pause/pad), a sentence
     terminator, a comma followed by ≥ 0.25 s, maxWords / maxDur / maxChars×lines reached. Never crosses a
     phase (a phase = one voice). Word end = d, or min(next.t − 0.03, t + 0.35) when d is missing.
     Hard constraints: ≥ 2 words (merge singles into a neighbour), ≥ 0.5 s on screen, one group at a time.
     opts.density=true lowers the cap to 2 / 3 / 4 words at > 3.5 / > 2.5 / else words-per-second (1 s window). */
  /* maxWords / maxChars default to the style's own tokens (anchor 6 / 42, keynote 5 / 22 …); set them in
     cfg.grouping only to override every style at once. */
  const GROUP_DEFAULTS = { gap: 0.35, commaGap: 0.25, maxDur: 2.5, minWords: 2, minDur: 0.5, lead: 0.08, tail: 0.6, density: false,
                           maxWidthFrac: 0.8, wrapMode: 'estimate' };
  function wordsOf(T, phase, cfg) {
    const base = T.P[phase], L = (T.WORDS[phase] || []), subs = (cfg && cfg.overrides) || [];
    const counts = {};
    return L.map((x, i) => {
      const nx = L[i + 1], start = base + x.t;
      const end = start + (typeof x.d === 'number' ? x.d : Math.min(nx ? nx.t - x.t - 0.03 : 0.35, 0.35));
      const k = norm(x.w); counts[k] = (counts[k] || 0) + 1;
      const w = { w: x.w, display: x.w, start: r3(start), end: r3(Math.max(end, start + 0.04)), em: false, drop: false, i: i, phase: phase };
      for (const o of subs) {                                  // per-word override file (templates/captions.example.json)
        if (o.phase !== phase || norm(o.word) !== k || (o.n || 1) !== counts[k]) continue;
        if (o.display != null) w.display = String(o.display);
        if (o.em) w.em = true;
        if (o.drop) w.drop = true;
        if (o.color) w.color = o.color;
        if (o.weight) w.weight = o.weight;
        if (o.scale) w.scale = o.scale;
      }
      return w;
    });
  }
  function group(T, cfg) {
    cfg = cfg || {};
    const o = Object.assign({}, GROUP_DEFAULTS, cfg.grouping || {});
    const fates = cfg.phases || {}, out = [];
    const chars = ws => ws.map(w => w.display).join(' ').length;
    const term = w => /[.?!]["')\]]?$/.test(w.display);
    const comma = w => /[,;:—–-]["')\]]?$/.test(w.display);
    for (const ph of T.PHASES.phases) {
      const fateCfg = fates[ph.name];
      const fate = typeof fateCfg === 'string' ? fateCfg : (fateCfg && fateCfg.fate) || cfg.mode || 'rail';
      const style = (fateCfg && fateCfg.style) || cfg.style || 'anchor';
      const tok = STYLES[style] || STYLES.anchor;
      const maxWords = o.maxWords !== undefined ? o.maxWords : tok.maxWords, maxChars = o.maxChars !== undefined ? o.maxChars : tok.maxChars;
      const W = wordsOf(T, ph.name, cfg).filter(w => !w.drop);
      if (!W.length) continue;
      const density = i => { let n = 0; for (let j = i; j < W.length && W[j].start < W[i].start + 1.0; j++) n++; return n; };
      const groups = []; let cur = [];
      const flush = () => { if (cur.length) groups.push(cur); cur = []; };
      W.forEach((w, i) => {
        if (cur.length) {
          const prev = cur[cur.length - 1], g = w.start - prev.end;
          const cap = o.density ? Math.min(maxWords, density(i) > 3.5 ? 2 : density(i) > 2.5 ? 3 : 4) : maxWords;
          if (g >= o.gap || term(prev) || (comma(prev) && g >= o.commaGap) || cur.length >= cap ||
              (w.end - cur[0].start) > o.maxDur || chars(cur.concat(w)) > maxChars * tok.lines) flush();
        }
        cur.push(w);
      });
      flush();
      // minimum shape: merge single-word / too-short groups into a neighbour when the merge stays legal
      for (let k = 0; k < groups.length; k++) {
        const g = groups[k], dur = g[g.length - 1].end - g[0].start;
        if (g.length >= o.minWords && dur >= o.minDur) continue;
        const legal = m => m.length <= maxWords && chars(m) <= maxChars * tok.lines;
        if (k > 0 && legal(groups[k - 1].concat(g))) { groups[k - 1] = groups[k - 1].concat(g); groups.splice(k, 1); k -= 2; continue; }
        if (k + 1 < groups.length && legal(g.concat(groups[k + 1]))) { groups[k] = g.concat(groups[k + 1]); groups.splice(k + 1, 1); k--; continue; }
        if (k > 0 && groups[k - 1].length > o.minWords && legal(groups[k - 1].slice(-1).concat(g))) {   // borrow the previous group's last word
          g.unshift(groups[k - 1].pop()); k--; }
      }
      groups.forEach(g => out.push({ phase: ph.name, fate: fate, style: style, words: g }));
    }
    // windows: in = first − lead (never before the previous out + 0.02), out = min(next.in − 0.05, last.end + tail), ≥ last.end
    const leadOf = g => { const tk = STYLES[g.style] || STYLES.anchor; return tk.lead !== undefined ? tk.lead : o.lead; };   // kinetic needs its waterfall in the air before the first word
    out.forEach((g, i) => {
      const first = g.words[0], last = g.words[g.words.length - 1], tok = STYLES[g.style] || STYLES.anchor;
      g.id = 'cg-' + i;
      g.in = r3(Math.max(first.start - leadOf(g), i ? out[i - 1].out + 0.02 : 0, 0));
      if (g.in > first.start) g.in = r3(first.start);
      const nxt = out[i + 1];
      const tail = tok.tail !== undefined ? tok.tail : o.tail;
      let end = last.end + tail;
      if (nxt) end = Math.min(end, nxt.words[0].start - leadOf(nxt) - 0.05);
      g.out = r3(Math.max(end, last.end + 0.02));
      if (g.out - g.in < o.minDur) g.out = r3(g.in + o.minDur);
      if (nxt && g.out > nxt.words[0].start - 0.03) g.out = r3(Math.max(last.end + 0.02, nxt.words[0].start - 0.03));
    });
    // text + line breaks (identical in node and browser under wrapMode 'estimate')
    const H = o.stageH || 1080;
    out.forEach(g => {
      const tok = STYLES[g.style] || STYLES.anchor;
      const px = Math.round(tok.sizeH * H), font = tok.weightBody + ' ' + px + 'px ' + tok.font;
      const txt = g.words.map(w => tok.case === 'upper' ? w.display.toUpperCase() : w.display);
      const maxW = g.fate === 'embed' ? 0.9 * (o.stageW || H * 16 / 9) : (o.maxWidthFrac || 0.8) * (o.stageW || H * 16 / 9);
      g.text = txt.join(' ');
      const mc = o.maxChars !== undefined ? o.maxChars : tok.maxChars;          // the same cap the grouper used
      g.lines = wrap(txt, font, maxW, tok.lines, o.wrapMode, mc).map(l => l.join(' '));
      g.chars = Math.max.apply(null, g.lines.map(l => l.length));
    });
    return out;
  }

  /* ------------------------------------------------------------------ active-word envelope ----
     0 before start → linear attack to 1 → sustain to end → release to `rest` → hold rest. */
  function env(t, start, end, o) {
    o = Object.assign({ attack: 0.12, release: 0.3, rest: 0.55 }, o || {});
    if (t < start) return 0;
    if (t < end) return o.attack > 0 ? Math.min((t - start) / o.attack, 1) : 1;
    if (o.release > 0 && t < end + o.release) return 1 - ((t - end) / o.release) * (1 - o.rest);
    return o.rest;
  }
  /* ------------------------------------------------------------------ karaoke word state ----
     A word has three ages. Future: waits at `future` opacity (0.55), ink, regular weight. Spoken: over `attack`
     (0.12 s) its opacity climbs to 1, its colour slides to the accent and the bold layer cross-fades in; a scale
     pulse sin(π·u) over `pulse` (0.12 s) peaks at 1 + scale (1.06) after 0.06 s and is exactly 1.0 again when the
     pulse ends. Past: over `release` (0.3 s) the accent and the bold layer fade back out and the opacity settles
     at `rest` (0.82). Pure function of t; the release starts from whatever level the attack reached, so a word
     shorter than the attack never jumps. Returns { op: word opacity, u: how lit (0..1), sc: scale }. */
  function karaoke(t, w, o) {
    o = Object.assign({ attack: 0.12, release: 0.3, rest: 0.82, future: 0.55, scale: 0.06, pulse: 0.12 }, o || {});
    const a = o.attack, r = o.release, span = Math.max(w.end - w.start, 0.001);
    const uEnd = a > 0 ? Math.min(span / a, 1) : 1;
    let op, u;
    if (t < w.start) { op = o.future; u = 0; }
    else if (t < w.end) { u = a > 0 ? Math.min((t - w.start) / a, 1) : 1; op = lerp(o.future, 1, u); }
    else { const v = r > 0 ? clamp((t - w.end) / r, 0, 1) : 1; u = uEnd * (1 - v); op = lerp(lerp(o.future, 1, uEnd), o.rest, v); }
    const pu = o.pulse > 0 ? clamp((t - w.start) / o.pulse, 0, 1) : 1;
    const sc = 1 + (o.scale || 0) * Math.sin(Math.PI * pu);
    return { op: op, u: u, sc: sc < 1.0005 ? 1 : sc };
  }
  /* waterfall delay of word i: Σ_{j<i} gap0·decay^j, capped (0, 0.06, 0.110, 0.153, 0.188, 0.218, 0.243, 0.264 … ≤ 0.3) */
  function waterfallDelay(i, o) {
    o = Object.assign({ gap0: 0.06, decay: 0.84, cap: 0.3 }, o || {});
    let acc = 0, gap = o.gap0;
    for (let j = 0; j < i; j++) { acc += gap; gap *= o.decay; }
    return Math.min(acc, o.cap);
  }
  function mix(dim, bright, u) {                   // colour lerp between two css colours (#rgb/#rrggbb/rgba())
    const P = c => { let m;
      if ((m = /^#([0-9a-f]{6})$/i.exec(c))) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), 1];
      if ((m = /^#([0-9a-f]{3})$/i.exec(c))) return [17 * parseInt(m[1][0], 16), 17 * parseInt(m[1][1], 16), 17 * parseInt(m[1][2], 16), 1];
      if ((m = /^rgba?\(([^)]+)\)$/i.exec(c))) { const v = m[1].split(',').map(parseFloat); return [v[0], v[1], v[2], v.length > 3 ? v[3] : 1]; }
      return [255, 255, 255, 1]; };
    const a = P(dim), b = P(bright), c = a.map((x, i) => lerp(x, b[i], u));
    return 'rgba(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ',' + c[3].toFixed(3) + ')';
  }

  /* ------------------------------------------------------------------ the lane ----
     build(T, cfg) → { groups, at(t), draw(el, t, o), yield(t0, t1, words), hide(el), style, cfg }
     cfg (window.CAPTIONS / scenes/captions.json): { style, mode:'rail'|'drop'|'embed', burn, phases:{name: fate|{fate,style,ink}},
       overrides:[…], grouping:{…}, stage:[1280,720], end: film length (default T.total + 1.2), creditKeepOut: 4.0,
       luma:{phase:{mean,p95}} (optional probe result → per-phase ink choice with hysteresis) } */
  function build(T, cfg) {
    cfg = Object.assign({ style: 'anchor', mode: 'rail', burn: true, stage: [1280, 720], creditKeepOut: 4.0 }, cfg || {});
    const stage = cfg.stage, Wd = stage[0], H = stage[1], K = H / 1080;
    const END = cfg.end !== undefined ? cfg.end : T.total + 1.2;
    const groups = group(T, Object.assign({}, cfg, { grouping: Object.assign({ stageW: Wd, stageH: H }, cfg.grouping || {}) }));
    const nocap = typeof location !== 'undefined' && /[?&]nocap/.test(location.search);   // captions-off pass for the luma probe
    const yields = [];
    /* per-phase ink decision from the luma probe (hysteresis: per phase, never per group) */
    const inkFor = g => {
      const ph = (cfg.phases || {})[g.phase], forced = ph && typeof ph === 'object' && ph.ink;
      const L = cfg.luma && cfg.luma[g.phase];
      const tok = STYLES[g.style] || STYLES.anchor;
      if (forced === 'dark' || (!forced && L && L.mean > 150)) return Object.assign({}, tok, { ink: STYLES.ink.ink, dimInk: STYLES.ink.dimInk, scrim: STYLES.ink.scrim, accent: STYLES.ink.accent, variant: 'dark' });
      if (L && L.mean < 60 && tok.scrim.kind !== 'none') return Object.assign({}, tok, { scrim: { kind: 'shadow', alpha: 0.5 }, variant: 'bare' });
      if (L && tok.scrim.kind === 'shadow') return Object.assign({}, tok, { scrim: { kind: 'pill', alpha: 0.45 }, variant: 'scrim' });
      return Object.assign({}, tok, { variant: 'default' });
    };
    function at(t) {
      if (nocap || cfg.burn === false || t >= END - cfg.creditKeepOut) return { group: null, opacity: 0 };
      let g = null;
      for (const x of groups) { if (t >= x.in && t < x.out) { g = x; break; } if (x.in > t) break; }
      if (!g || g.fate === 'drop') return { group: null, opacity: 0 };
      const tok = inkFor(g), first = g.words[0], last = g.words[g.words.length - 1];
      const fi = tok.enter.waterfall ? 0 : Math.min(tok.enter.dur, Math.max(0, first.start - g.in));   // never fade during speech (a waterfall enters word by word, the box itself is simply there):
      const fo = Math.min(tok.exit.dur, Math.max(0, g.out - last.end));             // clamp fades to the air around the words
      const uIn = fi > 0 ? EO2(rmp(t, g.in, g.in + fi)) : 1, uOut = fo > 0 ? EI2(rmp(t, g.out - fo, g.out)) : 0;
      let opacity = Math.min(uIn, 1 - uOut), dim = 1, hidden = false;
      for (const y of yields) {                                                     // hero hand-off: dim 0.55 from −0.2 s to +0.9 s
        if (t >= y.t0 - 0.2 && t < y.t1 + 0.9) dim = Math.min(dim, 0.55);
        if (y.words && t >= y.t0 && t < y.t1 && g.words.some(w => y.words.indexOf(norm(w.display)) >= 0 || y.words.indexOf(norm(w.w)) >= 0)) hidden = true;
      }
      if (hidden) return { group: null, opacity: 0 };
      const dy = (1 - uIn) * tok.enter.dy * K + uOut * tok.exit.dy * K;
      return { group: g, tok: tok, opacity: opacity * dim, uIn: uIn, uOut: uOut, dy: dy, fi: fi, fo: fo, activeIdx: g.words.findIndex(w => t >= w.start && t < w.end) };
    }
    /* ---- DOM: the container `el` is screen space (outside #camera); one .cap-box child, rebuilt per group ---- */
    let built = null;
    function ensure(el, s) {
      if (!el.__capBox) {
        el.style.pointerEvents = 'none';
        const b = document.createElement('div'); b.setAttribute('data-ov', 'cap'); b.style.position = 'absolute'; b.style.whiteSpace = 'nowrap';
        b.style.lineHeight = '1.3'; b.style.textAlign = 'center'; el.appendChild(b); el.__capBox = b;   // 1.3: the active-word lift (dy 4) never overlaps the line below
      }
      const b = el.__capBox;
      if (built === s.group.id + '|' + s.tok.variant) return b;
      built = s.group.id + '|' + s.tok.variant;
      const g = s.group, tok = s.tok, px = Math.round(tok.sizeH * H);
      const embed = g.fate === 'embed';
      b.style.font = tok.weightBody + ' ' + px + 'px/1.2 ' + tok.font; b.style.letterSpacing = tok.tracking; b.style.color = tok.ink;
      b.style.textTransform = tok.case === 'upper' ? 'uppercase' : 'none';
      b.style.maxWidth = Math.round((embed ? 0.9 : 0.8) * Wd) + 'px'; b.style.width = 'max-content'; b.style.whiteSpace = 'normal'; b.style.overflow = 'visible';   // max-content: an absolutely positioned box at left:50% would otherwise shrink to the right half
      // position: bottom lane (centre / left 10 %) or dead centre for embed
      b.style.left = ''; b.style.right = ''; b.style.top = ''; b.style.bottom = '';
      if (embed) { b.style.left = '50%'; b.style.top = '50%'; b.style.textAlign = 'center'; }
      else if (tok.align === 'left') { b.style.left = Math.round(0.10 * Wd) + 'px'; b.style.bottom = Math.round(tok.bottomPx * K) + 'px'; b.style.textAlign = 'left'; }
      else { b.style.left = '50%'; b.style.bottom = Math.round(tok.bottomPx * K) + 'px'; b.style.textAlign = 'center'; }
      // glyph-local legibility: shadow | pill | gradient | none (never a frame-wide bar)
      const sc = tok.scrim; b.style.textShadow = 'none'; b.style.background = 'none'; b.style.padding = '0'; b.style.borderRadius = '0';
      b.style.borderRight = '';   // the typewriter caret is a border on this box: a group rebuilt after a cold seek has none, a stepped run inherited 2 px (box wider, centred text 1 px off) — reset on every rebuild
      if (sc.kind === 'shadow') b.style.textShadow = '0 ' + (3 * K).toFixed(1) + 'px ' + (14 * K).toFixed(1) + 'px rgba(0,0,0,' + sc.alpha + ')';
      if (sc.kind === 'pill') { b.style.background = sc.light ? 'rgba(255,255,255,' + sc.alpha + ')' : sc.dark ? 'rgba(22,24,29,' + sc.alpha + ')' : 'rgba(0,0,0,' + sc.alpha + ')';
        b.style.padding = '0.4em 0.7em'; b.style.borderRadius = '0.3em'; }
      if (sc.kind === 'gradient') { b.style.background = 'linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,' + sc.alpha + ') 55%, rgba(0,0,0,' + sc.alpha + ') 100%)';
        b.style.padding = '0.5em 1.2em 0.45em'; b.style.borderRadius = '0.2em'; }
      // per-word spans (inline-block so transform works without reflow; weight is set once, never animated)
      // karaoke: two layers per word — the bold layer is IN FLOW at opacity 0 (it reserves the bold width, so the
      // word never reflows when it lights), the regular layer sits absolutely centred on top; draw() cross-fades them.
      b.setAttribute('data-cap-style', g.style);
      let k = 0;
      b.innerHTML = g.lines.map((line, li) => {
        const n = line.split(' ').length, ws = g.words.slice(k, k + n); k += n;
        return '<span class="cap-line" style="display:block;' + (tok.weightLine2 && li === 1 ? 'font-weight:' + tok.weightLine2 : '') + '">' +
          ws.map(w => {
            const txt = esc(tok.case === 'upper' ? w.display.toUpperCase() : w.display);
            if (tok.karaoke) {
              return '<span class="cap-w" data-i="' + w.i + '" style="display:inline-block;position:relative;line-height:1;transform-origin:50% 70%;' +
                (w.em ? 'color:' + esc(w.color || tok.accent) + ';' : '') + '">' +
                '<span class="cap-kb" style="display:inline-block;font-weight:' + (w.weight || tok.weightEm) + ';opacity:0">' + txt + '</span>' +
                '<span class="cap-kr" style="position:absolute;left:0;right:0;top:0;text-align:center;font-weight:' + tok.weightBody + '">' + txt + '</span></span>';
            }
            return '<span class="cap-w" data-i="' + w.i + '" style="display:inline-block;line-height:1;transform-origin:50% 70%;' +
              (w.em ? 'font-weight:' + (w.weight || tok.weightEm) + ';color:' + esc(w.color || tok.accent) + ';' : '') + '">' + txt + '</span>';
          }).join(' ') + '</span>';
      }).join('');
      return b;
    }
    function draw(el, t, o) {
      const s = at(t);
      if (!s.group) { if (el.__capBox) { el.__capBox.style.opacity = '0'; el.__capBox.style.visibility = 'hidden'; } return s; }
      const b = ensure(el, s), g = s.group, tok = s.tok;
      let lift = (o && o.lift) || 0;
      if (o && o.avoid && g.fate !== 'embed') {                                       // lane bottom = overlay top − 24 px when they would collide
        const L = lane.laneRect(g), lb = L[1] + L[3];
        for (const r of o.avoid) {
          if (!r) continue;
          const hx = L[0] < r[0] + r[2] && r[0] < L[0] + L[2], vy = L[1] - lift < r[1] + r[3] && r[1] < lb - lift;
          if (hx && vy) lift = Math.max(lift, lb - r[1] + 24 * K);
        }
      }
      s.lift = lift;
      b.style.visibility = 'visible'; b.style.opacity = s.opacity.toFixed(3);
      const tx = g.fate === 'embed' || tok.align !== 'left' ? '-50%' : '0', ty = g.fate === 'embed' ? '-50%' : '0';
      b.style.transform = 'translate(' + tx + ',' + ty + ') translateY(' + (s.dy - lift).toFixed(2) + 'px)';
      if (g.fate !== 'embed' && lift) b.style.bottom = Math.round(tok.bottomPx * K) + 'px';
      // entrance treatments (clip-path / wipe / swipe / typewriter) — transform, opacity, clip-path only
      if (tok.enter.wipe === 'x') b.style.clipPath = 'inset(0 ' + ((1 - EXPO(s.uIn)) * 100).toFixed(2) + '% 0 0)';
      else if (tok.enter.swipe) b.style.clipPath = 'inset(0 ' + ((1 - EO3(rmp(t, g.in, g.in + tok.enter.dur))) * 100).toFixed(2) + '% 0 0)';
      else b.style.clipPath = 'none';
      const spans = b.querySelectorAll('.cap-w');
      if (tok.enter.cps) {                                                            // typewriter: 1/cps s per char, cursor blink 600 ms after the last char
        const full = g.text, n = Math.floor(clamp((t - g.in) / (full.length / tok.enter.cps), 0, 1) * full.length);
        let shown = 0;
        spans.forEach(sp => { const w = sp.textContent.length; const vis = clamp(n - shown, 0, w); shown += w + 1;
          sp.style.clipPath = vis >= w ? 'none' : 'inset(0 ' + (100 - 100 * vis / w).toFixed(1) + '% 0 0)'; sp.style.opacity = vis > 0 ? '1' : '0'; });
        const done = g.in + full.length / tok.enter.cps, blink = t > done && t < done + 0.6 * 2 && Math.floor((t - done) / 0.3) % 2 === 0;
        b.style.borderRight = (t <= done || blink) ? '2px solid ' + tok.ink : '2px solid transparent';
        return s;
      }
      spans.forEach((sp, j) => {
        const w = g.words[j]; if (!w) return;
        if (tok.enter.wipe === 'word') {                                            // clean per-word clip wipe over 0.25 s
          const u = EO3(rmp(t, w.start - 0.05, w.start - 0.05 + tok.enter.dur));
          sp.style.clipPath = 'inset(0 ' + ((1 - u) * 100).toFixed(2) + '% 0 0)'; sp.style.opacity = u > 0 ? '1' : '0'; return;
        }
        if (tok.enter.waterfall) {                                                   // kinetic: word j arrives at in + Σ gap, rises dy and fades up over enter.dur
          const d = waterfallDelay(j, tok.enter.waterfall), u = EO3(rmp(t, g.in + d, g.in + d + tok.enter.dur));
          sp.style.opacity = u.toFixed(3);
          sp.style.transform = u < 0.9995 ? 'translateY(' + ((1 - u) * tok.enter.dy * K).toFixed(2) + 'px)' : 'none'; return;
        }
        if (tok.karaoke) {                                                           // the spoken word lights up: opacity, accent, bold cross-fade, pulse
          const ks = karaoke(t, w, tok.env), kb = sp.firstElementChild, kr = sp.lastElementChild;
          sp.style.opacity = ks.op.toFixed(3);
          if (!w.em) sp.style.color = mix(tok.ink, tok.accent, ks.u);
          if (kb) kb.style.opacity = ks.u.toFixed(3);
          if (kr) kr.style.opacity = (1 - ks.u).toFixed(3);
          sp.style.transform = ks.sc > 1 ? 'scale(' + Math.min(ks.sc, 1.10).toFixed(4) + ')' : 'none'; return;
        }
        if (!tok.perWord) { sp.style.transform = 'none'; return; }
        const e = env(t, w.start, w.end, tok.env);
        if (!w.em) sp.style.color = mix(tok.dimInk, tok.ink, e);
        const sc = (w.scale ? w.scale - 1 : tok.env.scale || 0) * e;
        sp.style.transform = sc > 0.0005 ? 'scale(' + (1 + Math.min(sc, 0.10)).toFixed(4) + ')' : 'none';
      });
      return s;
    }
    const lane = { groups: groups, at: at, draw: draw, cfg: cfg, style: cfg.style, END: END,
      yield: (t0, t1, words) => { if (!yields.some(y => y.t0 === t0 && y.t1 === t1)) yields.push({ t0: t0, t1: t1, words: words ? words.map(norm) : null }); },   // idempotent: heroes call it every frame
      hide: el => { if (el.__capBox) { el.__capBox.style.opacity = '0'; el.__capBox.style.visibility = 'hidden'; } built = null; },
      laneRect: g => {                                                                // nominal lane box for QA (stage px)
        const tok = STYLES[g.style] || STYLES.anchor, px = tok.sizeH * H, h = g.lines.length * px * 1.2 + (tok.scrim.kind === 'pill' ? 0.8 * px : 0);
        if (g.fate === 'embed') return [Wd * 0.05, H / 2 - h / 2, Wd * 0.9, h];
        const w = Math.min(0.8 * Wd, Math.max.apply(null, g.lines.map(l => estimate(l, tok.weightBody + ' ' + px + 'px ' + tok.font))) + (tok.scrim.kind === 'pill' ? 1.4 * px : 0));
        const x = tok.align === 'left' ? 0.10 * Wd : Wd / 2 - w / 2;
        return [x, H - tok.bottomPx * K - h, w, h]; } };
    root.CAP = root.CAP || CAP; CAP.lane = lane;
    return lane;
  }

  const CAP = { STYLES, FORBIDDEN, GROUP_DEFAULTS, group, build, env, karaoke, waterfallDelay, wrap, fitText, measure, estimate, mix, norm, EO2, EO3, EI2, EXPO, _wordsOf: wordsOf };
  if (typeof module !== 'undefined' && module.exports) module.exports = CAP;
  if (typeof window !== 'undefined') root.CAP = CAP;

  /* ------------------------------------------------------------------ node CLI: export the groups ----
       node lib/captions.js <timing_data.js> [captions.json] [--out out/caption_groups.json] [--js scenes/captions_data.js]
     Writes the groups (SRT/VTT twin for tools/captions_srt.py, QA input for gates/overlay_gate.py) and the
     browser twin of the config (window.CAPTIONS) so the scene and the sidecar read one source of truth. */
  if (IS_NODE && require.main === module) {
    const fs = require('fs'), path = require('path');
    const argv = process.argv.slice(2), flag = (n, d) => { const i = argv.indexOf('--' + n); return i >= 0 ? argv[i + 1] : d; };
    const pos = argv.filter((a, i) => !a.startsWith('--') && !(i > 0 && argv[i - 1].startsWith('--')));
    if (!pos[0]) { console.error('usage: node captions.js <timing_data.js> [captions.json] [--out out/caption_groups.json] [--js scenes/captions_data.js] [--luma out/caption_luma.json]'); process.exit(2); }
    const TL = require(path.resolve(__dirname, 'timeline.js'));
    const T = TL.load(pos[0]);
    const cfg = pos[1] && fs.existsSync(pos[1]) ? JSON.parse(fs.readFileSync(pos[1], 'utf8')) : {};
    const lumaPath = flag('luma', null);                                              // out/caption_luma.json from gates/overlay_gate.py --probe
    if (lumaPath && fs.existsSync(lumaPath)) cfg.luma = Object.assign({}, cfg.luma || {}, JSON.parse(fs.readFileSync(lumaPath, 'utf8')));
    const stage = cfg.stage || [1280, 720];
    const groups = group(T, Object.assign({}, cfg, { grouping: Object.assign({ stageW: stage[0], stageH: stage[1] }, cfg.grouping || {}) }));
    const end = cfg.end !== undefined ? cfg.end : T.total + 1.2;
    const out = { luma: cfg.luma || undefined, style: cfg.style || 'anchor', mode: cfg.mode || 'rail', burn: cfg.burn !== false, total: T.total, end: end, creditKeepOut: cfg.creditKeepOut || 4.0,
      stage: stage, groups: groups.map(g => ({ id: g.id, phase: g.phase, fate: g.fate, style: g.style, in: g.in, out: g.out, text: g.text, lines: g.lines,
        words: g.words.map(w => ({ w: w.w, display: w.display, start: w.start, end: w.end, em: w.em, i: w.i })) })) };
    const dest = flag('out', 'out/caption_groups.json'), js = flag('js', null);
    fs.mkdirSync(path.dirname(path.resolve(dest)), { recursive: true });
    fs.writeFileSync(dest, JSON.stringify(out, null, 1));
    if (js) { fs.mkdirSync(path.dirname(path.resolve(js)), { recursive: true }); fs.writeFileSync(js, 'window.CAPTIONS=' + JSON.stringify(cfg) + ';\n'); }
    const shown = out.groups.filter(g => g.fate !== 'drop');
    console.log('captions: ' + out.groups.length + ' groups (' + shown.length + ' shown, ' + out.groups.filter(g => g.fate === 'embed').length + ' embed) over ' +
      T.total.toFixed(2) + ' s -> ' + dest + (js ? ' + ' + js : ''));
  }
})(typeof window !== 'undefined' ? window : globalThis);
