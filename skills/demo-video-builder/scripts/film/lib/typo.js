/* typo.js — TYPO: kinetic typography on the film clock (built on lib/motion.js + GSAP).

   Every builder has one shape: TYPO.<name>(tl, el, opts) → state. Call it inside a MOTION.block build: it splits the
   text once, adds eased keyframes to that block's paused timeline and returns the times it used ({start, end, …}),
   so the next beat chains on state.end. Nothing here moves on its own — MOTION.seek(t) is the only thing that moves a
   glyph, so the frame at t is the same frame in any worker, in any order, on any machine.

   What the builders obey
   - text is split into spans once, at build; layout is final before frame 0, a line never reflows mid-shot
   - blur lives on a wrapper span, opacity on its child (one element compositing both is unreliable in headless
     Chrome); the wrapper's filter is cleared the moment the blur reaches 0 so settled glyphs are crisp
   - no wall clock, no unseeded randomness: choices come from MOTION.rng; the scramble soup is a hash of (seed, i, step)
   - per-frame text changes (scramble) go through a tiny GSAP plugin whose render(ratio) is a pure function — the clock
     suppresses callbacks, it never suppresses property renders
   - fonts are local only (Georgia / Arial / Segoe UI / Consolas); widths come from canvas measureText, which is
     synchronous for installed fonts, so a title can be fitted before the page has laid out
   - nothing here touches the footage lane; TYPO draws on recreated cards and in screen-space layers

   Scene wiring
     <script src="../node_modules/gsap/dist/gsap.min.js"></script>   (npm i gsap — never a CDN)
     <script src="lib/motion.js"></script><script src="lib/typo.js"></script>
     MOTION.block('open', (tl, el) => {
       const a = TYPO.centerBuild(tl, el.querySelector('.line'), { at: 0.1, gap: 0.12 });
       TYPO.heroWord(tl, el.querySelector('.line'), { word: 'data', at: a.end });
     }, { el: $('#openCard'), start: 0, end: P.nb, exit: 0.4 });

   Defaults are the measured numbers (TYPO.tokens.motion); every builder takes overrides. Sizes are for the 720p stage. */
(function (root) {
  'use strict';
  const M = root.MOTION;
  if (!M) throw new Error('typo.js: load lib/motion.js (and gsap) before lib/typo.js');
  const G = M.gsap;
  const num = (v, d) => (v === undefined || v === null || Number.isNaN(v) ? d : v);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  /* ------------------------------------------------------------------ tokens ------------------------------------- */
  const tokens = {
    stage: { w: 1280, h: 720 },
    font: {
      display: 'Georgia, "Times New Roman", serif',
      body: 'Arial, "Segoe UI", sans-serif',
      label: '"Segoe UI", Arial, sans-serif',
      mono: 'Consolas, "Courier New", monospace'
    },
    size: { display: 64, display2: 44, display3: 32, body: 22, label: 16, labelMin: 16, labelMax: 18, hero: { min: 0.16, max: 0.22 } },   // label 16 stage px (24 px at 1080p) is the legibility floor for every label, kicker and tick — the same number as design.md scale.label_min
    weight: { display: 400, body: 400, label: 500, hero: 700 },
    tracking: { display: '-0.01em', body: '0', label: '0.12em' },
    leading: { display: 1.1, body: 1.4, label: 1 },
    color: { navy: '#082A34', navy2: '#204A56', ink: '#E9F3F9', cream: '#ECDEC3', coral: '#E56B5E', mint: '#81A9AB', gold: '#E8C874' },
    motion: {
      blurIn: 3.5,        // px of blur a glyph carries on entry, gone by the end of the entry
      enterDx: 36,        // px a word travels in from the right (centerBuild)
      enter: 0.55,        // s, a word's entry (power3.out)
      wordGap: 0.12,      // s between words when no word times are given
      swapOut: 0.30, swapIn: 0.42, swapLift: 22, swapLag: 0.15,   // s / s / px / s
      gap0: 0.06, gapDecay: 0.84, gapCap: 0.5,                   // the shrinking-gap stagger law
      scramble: 0.8, scrambleMin: 0.6, scrambleMax: 1.0, soupRate: 15,   // s / s / s / glyph changes per second
      slamScale: 1.12, slamPulse: 0.165, slamSnap: 0.05,          // scale / s / s (opacity snap)
      shimmer: 0.9, heroScale: 1.08, hero: 0.35, rule: 0.5, kicker: 0.4
    }
  };
  const MT = tokens.motion;

  /* ------------------------------------------------------------------ one-time style ----------------------------- */
  let styled = false;
  function ensureStyle() {
    if (styled || typeof document === 'undefined') return;
    styled = true;
    const s = document.createElement('style');
    s.setAttribute('data-typo', '');
    s.textContent = [
      '.ty-w{display:inline-block;white-space:nowrap;vertical-align:baseline}',
      '.ty-i{display:inline-block}',
      '.ty-c{text-align:center}',
      '.ty-swap{position:relative;display:block}',
      '.ty-swap>.ty-line{display:block}',
      '.ty-swap>.ty-line.ty-in{position:absolute;left:0;right:0;top:0}',
      '.ty-cell{display:inline-block;position:relative;white-space:nowrap;vertical-align:baseline}',
      '.ty-cell>.ty-out,.ty-cell>.ty-in{position:absolute;left:0;top:0;white-space:nowrap}',
      '.ty-cell>.ty-ghost{visibility:hidden}',
      '.ty-lockup{display:flex;flex-direction:column;align-items:center;text-align:center}',
      '.ty-lockup.ty-left{align-items:flex-start;text-align:left}',
      '.ty-lockup>*{margin:0}',
      '.ty-kicker{display:block}'
    ].join('\n');
    document.head.appendChild(s);
  }

  /* ------------------------------------------------------------------ helpers ------------------------------------ */
  function mk(tag, cls, parent) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (parent) parent.appendChild(e);
    return e;
  }
  function hashStr(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function hash3(a, b, c) {               // integer mix of (seed, index, step) → 32-bit
    let h = (a ^ 0x9E3779B9) >>> 0;
    h = Math.imul(h ^ (b + 0x7F4A7C15), 0x85EBCA6B) >>> 0; h ^= h >>> 13;
    h = Math.imul(h ^ (c + 0x165667B1), 0xC2B2AE35) >>> 0; h ^= h >>> 16;
    return h >>> 0;
  }
  let canvasCtx = null;
  function fontOf(el, sizePx) {
    const cs = getComputedStyle(el);
    const size = sizePx !== undefined ? sizePx + 'px' : cs.fontSize;
    return { font: [cs.fontStyle, cs.fontWeight, size, cs.fontFamily].join(' '), letterSpacing: parseFloat(cs.letterSpacing) || 0, size: parseFloat(size) };
  }
  /* width of `text` in a CSS font string (+ letter-spacing px per gap); synchronous for installed fonts */
  function measure(text, font, letterSpacing) {
    if (!canvasCtx) canvasCtx = document.createElement('canvas').getContext('2d');
    canvasCtx.font = typeof font === 'string' ? font : fontOf(font).font;
    const ls = letterSpacing !== undefined ? letterSpacing : (typeof font === 'string' ? 0 : fontOf(font).letterSpacing);
    const n = Array.from(text).length;
    return canvasCtx.measureText(text).width + Math.max(0, n - 1) * ls;
  }

  /* split an element's text into animatable spans (once; idempotent per mode). Each item is a wrapper .ty-w holding a
     child .ty-i: transforms + blur on the wrapper, opacity (and colour) on the child. Word mode keeps real spaces
     between wrappers so the line wraps and centres as text; char mode makes a space its own (invisible) item. */
  function split(el, o) {
    o = o || {}; ensureStyle();
    const by = o.by === 'char' ? 'char' : 'word';
    if (el.dataset.typoSplit === by && o.text === undefined) return Array.from(el.querySelectorAll(':scope > .ty-w'));
    const text = (o.text !== undefined ? String(o.text) : el.textContent).replace(/\s+/g, ' ').trim();
    el.textContent = '';
    el.dataset.typoSplit = by;
    const items = [];
    if (by === 'word') {
      const words = text.length ? text.split(' ') : [];
      words.forEach((w, i) => {
        const wrap = mk('span', 'ty-w', el); mk('span', 'ty-i', wrap).textContent = w; items.push(wrap);
        if (i < words.length - 1) el.appendChild(document.createTextNode(' '));
      });
    } else {
      Array.from(text).forEach(ch => {
        const wrap = mk('span', 'ty-w ty-c', el); const inner = mk('span', 'ty-i', wrap);
        if (ch === ' ') { inner.textContent = ' '; wrap.classList.add('ty-sp'); } else inner.textContent = ch;
        items.push(wrap);
      });
    }
    return items;
  }
  const innerOf = w => w.querySelector(':scope > .ty-i') || w;

  /* the shared entry: travel (dx, dy) + blur on the wrapper, opacity on the child; filter cleared when settled */
  function enter(tl, wrap, at, o) {
    const inner = innerOf(wrap);
    const dur = num(o.dur, MT.enter), blur = num(o.blur, 0);
    const from = { x: num(o.dx, 0), y: num(o.dy, 0) }, to = { x: 0, y: 0, duration: dur, ease: o.ease || 'power3.out', immediateRender: o.immediateRender !== false };
    if (blur > 0) { from.filter = 'blur(' + blur + 'px)'; to.filter = 'blur(0px)'; }
    tl.fromTo(wrap, from, to, at);
    tl.fromTo(inner, { opacity: 0 }, { opacity: 1, duration: dur * num(o.fadeFrac, 0.6), ease: o.fadeEase || 'power2.out', immediateRender: o.immediateRender !== false }, at);
    if (blur > 0) tl.set(wrap, { filter: 'none' }, at + dur);
    return at + dur;
  }
  /* the shared exit: lift + fade, power4.in, 0.3 s (≈ 75 % of a 0.42 s entry) */
  function exit(tl, el, at, o) {
    o = o || {};
    tl.to(el, { x: num(o.dx, 0), y: num(o.dy, -MT.swapLift), opacity: 0, duration: num(o.dur, MT.swapOut), ease: o.ease || 'power4.in' }, at);
    return at + num(o.dur, MT.swapOut);
  }

  /* the GSAP plugin that lets a timeline paint text: tl.to({}, { duration, ease: 'none', typoPaint: fn }, at) calls
     fn(ratio) on every render of that tween — forwards, backwards, on a jump — never from a callback */
  G.registerPlugin({
    name: 'typoPaint',
    rawVars: 1,                                   // hand the function over untouched (GSAP would otherwise call it as a value)
    init(target, fn) { this.fn = typeof fn === 'function' ? fn : (fn && typeof fn.paint === 'function' ? fn.paint : () => {}); this.fn(0); },
    render(ratio, data) { data.fn(clamp(ratio, 0, 1)); }
  });

  /* ------------------------------------------------------------------ centerBuild -------------------------------- */
  /* words arrive one by one from the right (dx 36 px, blur 3.5 → 0, 0.55 s power3.out) while the line stays centred.
     mode 'run' (default): the visible run is re-centred as each word lands (the shown words glide left by half the
     new word's width); mode 'slot': the final layout is fixed and each word slides into its slot.
     opts: at (s), gap (s, default 0.12) or times [s per word] (narration word times), dx, dur, blur, ease, text, mode */
  function centerBuild(tl, el, o) {
    o = o || {};
    const at = num(o.at, 0), items = split(el, { by: 'word', text: o.text });
    const dur = num(o.dur, MT.enter), dx = num(o.dx, MT.enterDx), blur = num(o.blur, MT.blurIn), ease = o.ease || 'power3.out';
    const times = items.map((_, i) => Array.isArray(o.times) ? num(o.times[Math.min(i, o.times.length - 1)], at) : at + i * num(o.gap, MT.wordGap));
    items.forEach((w, i) => enter(tl, w, times[i], { dx, dur, blur, ease }));
    const mode = o.mode || 'run';
    let shifts = null;
    if (mode === 'run' && items.length > 1) {
      // re-centre the visible run: shift the whole line right by (W − W_k)/2 while k words are showing
      const f = fontOf(el), space = measure(' ', f.font, 0);
      const widths = items.map(w => measure(innerOf(w).textContent, f.font, f.letterSpacing));
      const W = widths.reduce((a, b) => a + b, 0) + space * (items.length - 1);
      shifts = []; let shown = 0;
      for (let k = 0; k <= items.length; k++) { shifts.push((W - shown) / 2); if (k < items.length) shown += widths[k] + (k ? space : 0); }
      el.style.display = el.style.display || 'inline-block';
      tl.set(el, { x: shifts[1] }, 0);                       // one word showing: run centred (the first word enters in place)
      for (let k = 1; k < items.length; k++) tl.to(el, { x: shifts[k + 1], duration: dur * 0.7, ease }, times[k]);
    }
    const end = Math.max.apply(null, times) + dur;
    return { el, items, times, start: times[0], end, mode, shifts };
  }

  /* ------------------------------------------------------------------ swap --------------------------------------- */
  /* a phrase replaced by another: the outgoing lifts 22 px and fades over 0.30 s power4.in; the incoming rises from
     +22 px over 0.42 s power4.out, starting 0.15 s after. matchCut: words shared at the start/end of both phrases stay
     put — only the differing run swaps, inside a cell whose width glides from one phrase to the other (power3.inOut),
     so the line re-centres by a few px instead of jumping.
     opts: at, from (default: host text), to, matchCut, lift, outDur, inDur, lag, cellEase */
  function swap(tl, host, o) {
    o = o || {}; ensureStyle();
    const at = num(o.at, 0), from = (o.from !== undefined ? String(o.from) : host.textContent).replace(/\s+/g, ' ').trim(), to = String(o.to || '').replace(/\s+/g, ' ').trim();
    const lift = num(o.lift, MT.swapLift), outD = num(o.outDur, MT.swapOut), inD = num(o.inDur, MT.swapIn), lag = num(o.lag, MT.swapLag);
    host.textContent = ''; host.classList.add('ty-swap');
    let outEl, inEl, cell = null, shared = null;
    if (o.matchCut) {
      const A = from.split(' '), B = to.split(' ');
      let p = 0; while (p < A.length && p < B.length && A[p] === B[p]) p++;
      let s = 0; while (s < A.length - p && s < B.length - p && A[A.length - 1 - s] === B[B.length - 1 - s]) s++;
      const pre = A.slice(0, p), midA = A.slice(p, A.length - s), midB = B.slice(p, B.length - s), suf = A.slice(A.length - s);
      shared = { pre, suf };
      const row = mk('span', 'ty-row', host);
      if (pre.length) mk('span', 'ty-part ty-pre', row).textContent = pre.join(' ') + ' ';
      cell = mk('span', 'ty-cell', row);
      mk('span', 'ty-ghost', cell).textContent = '​';          // gives the cell a line box and a baseline
      outEl = mk('span', 'ty-out', cell); outEl.textContent = midA.join(' ');
      inEl = mk('span', 'ty-in', cell); inEl.textContent = midB.join(' ');
      if (suf.length) mk('span', 'ty-part ty-suf', row).textContent = ' ' + suf.join(' ');
      const f = fontOf(host);
      const wA = measure(midA.join(' '), f.font, f.letterSpacing), wB = measure(midB.join(' '), f.font, f.letterSpacing);
      cell.style.width = wA.toFixed(2) + 'px';
      tl.to(cell, { width: wB.toFixed(2) + 'px', duration: inD, ease: o.cellEase || 'power3.inOut' }, at + lag * 0.4);
    } else {
      outEl = mk('span', 'ty-line ty-out', host); outEl.textContent = from;
      inEl = mk('span', 'ty-line ty-in', host); inEl.textContent = to;
    }
    tl.to(outEl, { y: -lift, opacity: 0, duration: outD, ease: 'power4.in' }, at);
    tl.fromTo(inEl, { y: lift, opacity: 0 }, { y: 0, opacity: 1, duration: inD, ease: 'power4.out', immediateRender: true }, at + lag);
    return { host, outEl, inEl, cell, shared, start: at, end: at + lag + inD };
  }

  /* ------------------------------------------------------------------ stagger ------------------------------------ */
  /* waterfall: characters (default) or words cascade in with the shrinking gap law 0.06 s × 0.84^i, the whole group's
     offset capped at 0.5 s (gaps tighten, durations don't). Each item rises 18 px on power4.out over 0.42 s.
     opts: at, by 'char'|'word', dy, dx, dur, blur (0), gap0, decay, cap, ease, text, reverse */
  function stagger(tl, el, o) {
    o = o || {};
    const at = num(o.at, 0), items = split(el, { by: o.by || 'char', text: o.text });
    const gap0 = num(o.gap0, MT.gap0), decay = num(o.decay, MT.gapDecay), cap = num(o.cap, MT.gapCap), dur = num(o.dur, 0.42);
    const order = o.reverse ? items.slice().reverse() : items;
    let gap = gap0, acc = 0; const times = new Array(items.length);
    order.forEach(w => {
      const i = items.indexOf(w), tt = at + Math.min(acc, cap); times[i] = tt;
      if (w.classList.contains('ty-sp')) return;                     // a space takes no slot and no time
      enter(tl, w, tt, { dy: num(o.dy, 18), dx: num(o.dx, 0), dur, blur: num(o.blur, 0), ease: o.ease || 'power4.out' });
      acc += gap; gap *= decay;
    });
    return { el, items, times, start: at, end: at + Math.min(acc, cap) + dur };
  }

  /* ------------------------------------------------------------------ scramble ----------------------------------- */
  /* letters resolve from a seeded glyph soup to the final text over 0.6–1.0 s (default 0.8). The sweep runs left to
     right with seeded jitter; unresolved glyphs change 15×/s and sit in a muted colour until they lock. Each character
     keeps the width of its final glyph (locked at build), so a proportional face doesn't jitter; a monospace face
     needs no lock. opts: at, dur, seed, soupColor, rate, order 'sweep'|'random', lead (fade-in s, 0.12), text, lock */
  const SOUPS = { lower: 'abcdefghkmnoprstuvwxyz', upper: 'ABCDEFGHKLMNPRSTUVWXYZ', digit: '0123456789', other: '#%&*+=<>/' };
  function scramble(tl, el, o) {
    o = o || {};
    const at = num(o.at, 0), dur = clamp(num(o.dur, MT.scramble), 0.2, 3), rate = num(o.rate, MT.soupRate);
    const items = split(el, { by: 'char', text: o.text });
    const finals = items.map(w => innerOf(w).textContent);
    const seed = num(o.seed, hashStr(finals.join(''))) >>> 0, rnd = M.rng(seed), soupColor = o.soupColor || tokens.color.mint;
    if (o.lock !== false) {
      const f = fontOf(el);
      items.forEach((w, i) => { if (!w.classList.contains('ty-sp')) w.style.width = measure(finals[i], f.font, 0).toFixed(2) + 'px'; });
    }
    const n = items.length, order = [];
    for (let i = 0; i < n; i++) order.push(o.order === 'random' ? rnd() : (i + 0.6 * rnd()) / Math.max(1, n));
    const maxU = Math.max.apply(null, order) || 1;
    const resolveU = order.map(u => 0.1 + 0.9 * (u / maxU));           // the last glyph locks exactly at the end
    const kind = ch => /[a-z]/.test(ch) ? 'lower' : /[A-Z]/.test(ch) ? 'upper' : /[0-9]/.test(ch) ? 'digit' : /[\s ]/.test(ch) ? null : 'other';
    const kinds = finals.map(kind);
    const soup = (i, step) => { const set = SOUPS[kinds[i]]; let g = set[hash3(seed, i, step) % set.length]; if (g === finals[i]) g = set[(hash3(seed, i, step) + 1) % set.length]; return g; };
    const paint = u => {
      const step = Math.floor(u * dur * rate);
      for (let i = 0; i < n; i++) {
        const inner = innerOf(items[i]);
        if (!kinds[i]) continue;
        if (u >= resolveU[i]) { if (inner.textContent !== finals[i]) inner.textContent = finals[i]; if (inner.style.color) inner.style.color = ''; }
        else { const g = soup(i, step); if (inner.textContent !== g) inner.textContent = g; if (inner.style.color !== soupColor) inner.style.color = soupColor; }
      }
    };
    const lead = num(o.lead, 0.12);
    if (lead > 0) tl.fromTo(el, { opacity: 0 }, { opacity: 1, duration: lead, ease: 'none', immediateRender: true }, at);
    tl.to({}, { duration: dur, ease: 'none', typoPaint: paint }, at);
    return { el, items, seed, start: at, end: at + dur, resolveAt: resolveU.map(u => at + u * dur) };
  }

  /* ------------------------------------------------------------------ slam --------------------------------------- */
  /* a 1–3 word hit lands on its spoken word: scale 1.12 → 1 over a 0.165 s pulse (expo.out), opacity snaps in 0.05 s.
     opts: at, scale0, pulse, kicker (string → a small label inserted above el, or an element), kickerAt (default at − 0.25),
     hold (s: slow 1.2 %/s push after the hit), origin */
  function slam(tl, el, o) {
    o = o || {}; ensureStyle();
    const at = num(o.at, 0), s0 = num(o.scale0, MT.slamScale), pulse = num(o.pulse, MT.slamPulse);
    M.set(el, { transformOrigin: o.origin || '50% 60%' });   // MOTION.set renders now; a bare gsap.set() under the paused global timeline never does (measured: inline style still empty 600 ms later)
    tl.fromTo(el, { scale: s0 }, { scale: 1, duration: pulse, ease: 'expo.out', immediateRender: true }, at);
    tl.fromTo(el, { opacity: 0 }, { opacity: 1, duration: num(o.snap, MT.slamSnap), ease: 'none', immediateRender: true }, at);
    let kicker = null;
    if (o.kicker) {
      if (typeof o.kicker === 'string') {
        kicker = document.createElement('div'); kicker.className = 'ty-kicker';
        kicker.textContent = o.kicker;
        Object.assign(kicker.style, { font: tokens.weight.label + ' ' + tokens.size.label + 'px/1 ' + tokens.font.label, letterSpacing: tokens.tracking.label, textTransform: 'uppercase', color: o.kickerColor || tokens.color.mint, marginBottom: '14px' });
        el.parentNode.insertBefore(kicker, el);
      } else kicker = o.kicker;
      const ka = num(o.kickerAt, at - 0.25);
      tl.fromTo(kicker, { y: 10, opacity: 0 }, { y: 0, opacity: 1, duration: MT.kicker, ease: 'power3.out', immediateRender: true }, ka);
    }
    if (o.hold > 0) tl.to(el, { scale: 1 + 0.012 * o.hold, duration: o.hold, ease: 'none' }, at + pulse);
    return { el, kicker, start: at, end: at + pulse };
  }

  /* ------------------------------------------------------------------ shimmer ------------------------------------ */
  /* a light sweep across the glyphs, once, 0.9 s (sine.inOut): each text run is painted with a gradient clipped to its
     own glyphs (base = that run's colour, a highlight band at the centre) and the band travels left → right across the
     whole line. Works on a plain element and on a line already split by another builder: every .ty-i child gets the
     same gradient offset by its measured position, so the band crosses word boundaries seamlessly (background-clip
     can only clip to text painted by the element itself, never by a transformed child). The runs keep the gradient
     after the sweep — its base is their colour, so they read as plain text. Not for a line whose colour is still being
     tweened (heroWord): run the shimmer before the promotion or on another element.
     opts: at, dur, color (base override), highlight (default gold), angle (100), band (0.16 of the sweep image) */
  function shimmer(tl, el, o) {
    o = o || {}; ensureStyle();
    const at = num(o.at, 0), dur = num(o.dur, MT.shimmer), hi = o.highlight || tokens.color.gold, band = num(o.band, 0.16);
    const split_ = el.dataset.typoSplit, runs = split_ ? Array.from(el.querySelectorAll(':scope > .ty-w')).map(innerOf) : [el];
    const f = fontOf(el), space = split_ === 'word' ? measure(' ', f.font, 0) : 0;
    const offsets = []; let total = 0;
    runs.forEach(r => { offsets.push(total); total += measure(r.textContent, f.font, f.letterSpacing) + space; });
    total = Math.max(1, total - space);
    const W = total * 2.5, a = (50 - band * 50).toFixed(1), b = (50 + band * 50).toFixed(1), angle = num(o.angle, 100);
    runs.forEach(r => {
      const base = o.color || getComputedStyle(r).color || tokens.color.ink;
      Object.assign(r.style, {
        backgroundImage: 'linear-gradient(' + angle + 'deg, ' + base + ' 0%, ' + base + ' ' + a + '%, ' + hi + ' 50%, ' + base + ' ' + b + '%, ' + base + ' 100%)',
        backgroundSize: W.toFixed(1) + 'px 100%', backgroundRepeat: 'no-repeat', webkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent'
      });
      if (getComputedStyle(r).display === 'inline') r.style.display = 'inline-block';
    });
    // band centre travels from just left of the line to just right of it; each run sees the image shifted by its offset
    const paint = u => {
      const c = -0.2 * total + u * 1.4 * total, left = c - W / 2;
      runs.forEach((r, i) => { r.style.backgroundPosition = (left - offsets[i]).toFixed(2) + 'px 0px'; });
    };
    tl.to({}, { duration: dur, ease: o.ease || 'sine.inOut', typoPaint: paint }, at);
    return { el, runs, start: at, end: at + dur };
  }

  /* ------------------------------------------------------------------ heroWord ----------------------------------- */
  /* one word in a sentence promoted: colour (→ coral), weight (→ 700) and 1.08 scale over 0.35 s. By default the
     promoted weight is set at build, so the line is laid out once and only colour + scale animate (weightAt: 'build');
     weightAt: 'promote' snaps the weight at `at` inside a slot pre-sized to the bold width, so nothing reflows (the
     slot shows as extra air before the hit). size: px (≥ 1) or a fraction of the stage height (< 1; the measured hero
     range is 0.16–0.22 h), applied at build. opts: word | index, at, color, weight, weightAt, scale, dur, size, origin */
  function heroWord(tl, el, o) {
    o = o || {};
    const at = num(o.at, 0), items = split(el, { by: 'word', text: o.text });
    const norm = s => s.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();
    const idx = o.index !== undefined ? o.index : items.findIndex(w => norm(innerOf(w).textContent) === norm(String(o.word || '')));
    if (idx < 0 || idx >= items.length) throw new Error('typo.heroWord: word not found: ' + o.word);
    const w = items[idx], inner = innerOf(w), weight = num(o.weight, tokens.weight.hero), dur = num(o.dur, MT.hero);
    if (o.size !== undefined) w.style.fontSize = (o.size < 1 ? o.size * tokens.stage.h : o.size).toFixed(1) + 'px';
    if (o.weightAt === 'promote') {
      const f = fontOf(w);
      const bold = measure(inner.textContent, f.font.replace(/^(\S+)\s+\S+/, '$1 ' + weight), f.letterSpacing);
      w.style.width = bold.toFixed(2) + 'px'; w.style.textAlign = 'center';
      tl.set(inner, { fontWeight: weight }, at + dur * 0.3);
    } else if (weight) inner.style.fontWeight = String(weight);
    M.set(w, { transformOrigin: o.origin || '50% 70%' });   // MOTION.set, not gsap.set (see slam)
    tl.to(inner, { color: o.color || tokens.color.coral, duration: dur, ease: 'power2.out' }, at);
    tl.to(w, { scale: num(o.scale, MT.heroScale), duration: dur, ease: 'power3.out' }, at);
    return { el, word: w, index: idx, start: at, end: at + dur };
  }

  /* ------------------------------------------------------------------ fit ---------------------------------------- */
  /* shrink a single line to a width: starts at max (default tokens.size.display) and scales down, never below min,
     in half-pixel steps; sets el.style.fontSize and returns { size, width, fits }. Measured, so it works before layout. */
  function fit(el, maxWidthPx, o) {
    o = o || {};
    const min = num(o.min, 24), max = num(o.max, tokens.size.display), text = o.text !== undefined ? String(o.text) : el.textContent;
    const f = fontOf(el, max), wAtMax = measure(text, f.font, f.letterSpacing);
    let size = wAtMax > 0 ? Math.min(max, max * maxWidthPx / wAtMax) : max;
    size = Math.max(min, Math.floor(size * 2) / 2);
    el.style.fontSize = size + 'px';
    const width = wAtMax * size / max;
    return { size, width, fits: width <= maxWidthPx + 0.5 };
  }

  /* ------------------------------------------------------------------ lockup ------------------------------------- */
  /* a title lock-up: kicker (label 14, mint, tracked caps) → title (display 64 Georgia) → rule (coral, scaleX 0 → 1
     over 0.5 s power4.out) → sub (body 22 cream). Entries: kicker rises 12 px (0.4 s), title enters with blur
     (dy 24, 0.55 s) or as a centerBuild (build: 'center'), rule draws from the left (or the centre when centred),
     sub rises 16 px (0.5 s). fit: max title width px (shrinks the title before anything is built).
     opts: at, kicker, kickerAt (default at — give the kicker its own spoken word so the card is never an empty plate while the
     title waits for its words), title, sub, align 'center'|'left', build 'rise'|'center'|'stagger', fit, accent, colors {…},
     sizes {title, sub, kicker}, rule {w, h} */
  function lockup(tl, host, o) {
    o = o || {}; ensureStyle();
    const at = num(o.at, 0), left = o.align === 'left', sizes = o.sizes || {}, col = o.colors || {};
    host.classList.add('ty-lockup'); if (left) host.classList.add('ty-left');
    host.textContent = '';
    const els = {};
    let t = at;
    if (o.kicker) {
      els.kicker = mk('div', 'ty-kicker', host); els.kicker.textContent = o.kicker;
      Object.assign(els.kicker.style, { font: tokens.weight.label + ' ' + num(sizes.kicker, tokens.size.label) + 'px/1 ' + tokens.font.label, letterSpacing: tokens.tracking.label, textTransform: 'uppercase', color: col.kicker || tokens.color.mint, marginBottom: '18px' });
      tl.fromTo(els.kicker, { y: 12, opacity: 0 }, { y: 0, opacity: 1, duration: MT.kicker, ease: 'power3.out', immediateRender: true }, num(o.kickerAt, t));
      if (o.kickerAt === undefined) t += 0.08;
    }
    els.title = mk('div', 'ty-title', host); els.title.textContent = o.title || '';
    Object.assign(els.title.style, { font: tokens.weight.display + ' ' + num(sizes.title, tokens.size.display) + 'px/' + tokens.leading.display + ' ' + tokens.font.display, letterSpacing: tokens.tracking.display, color: col.title || tokens.color.ink });
    if (o.fit) fit(els.title, o.fit, { min: num(o.fitMin, tokens.size.display3), max: num(sizes.title, tokens.size.display) });
    let titleEnd;
    if (o.build === 'center') { const st = centerBuild(tl, els.title, { at: t, gap: o.gap, times: o.times }); titleEnd = st.end; els.titleWords = st.items; }
    else if (o.build === 'stagger') { const st = stagger(tl, els.title, { at: t, by: 'word', dy: 24, blur: MT.blurIn }); titleEnd = st.end; els.titleWords = st.items; }
    else {
      els.title.textContent = '';
      const inner = mk('span', 'ty-i', els.title); inner.textContent = o.title || '';
      els.title.classList.add('ty-w'); els.title.style.whiteSpace = 'normal';
      titleEnd = enter(tl, els.title, t, { dy: 24, dur: MT.enter, blur: MT.blurIn, ease: 'power4.out' });
    }
    const ruleAt = t + 0.42, rl = o.rule || {};
    els.rule = mk('div', 'ty-rule', host);
    Object.assign(els.rule.style, { width: num(rl.w, 90) + 'px', height: num(rl.h, 3) + 'px', background: o.accent || tokens.color.coral, marginTop: '26px', transformOrigin: left ? '0 50%' : '50% 50%' });
    tl.fromTo(els.rule, { scaleX: 0 }, { scaleX: 1, duration: MT.rule, ease: 'power4.out', immediateRender: true }, ruleAt);
    let subEnd = ruleAt + MT.rule;
    if (o.sub) {
      els.sub = mk('div', 'ty-sub', host); els.sub.textContent = o.sub;
      Object.assign(els.sub.style, { font: tokens.weight.body + ' ' + num(sizes.sub, tokens.size.body) + 'px/' + tokens.leading.body + ' ' + tokens.font.body, color: col.sub || tokens.color.cream, marginTop: '18px' });
      const subAt = ruleAt + 0.2;
      tl.fromTo(els.sub, { y: 16, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5, ease: 'power4.out', immediateRender: true }, subAt);
      subEnd = subAt + 0.5;
    }
    return { host, els, start: at, end: Math.max(titleEnd, subEnd), ruleAt };
  }

  root.TYPO = { tokens, split, measure, fit, enter, exit, centerBuild, swap, stagger, scramble, slam, shimmer, heroWord, lockup };
})(typeof window !== 'undefined' ? window : globalThis);
