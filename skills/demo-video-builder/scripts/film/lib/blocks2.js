/* blocks2.js — BL2: the story blocks a trailer needs, built on MOTION (GSAP timelines that only move when the
   film clock says so).

   Every builder here is called ONCE: BL2.<name>(host, opts) creates the DOM inside `host`, lays a GSAP timeline
   through MOTION.block and returns a handle { el, tl, block, start, LAND, land(t), sync(), at(t) }. Nothing
   animates on its own — no CSS transitions, no rAF, no wall clock, no Math.random (MOTION.rng(seed) only). The
   scene calls MOTION.seek(t) from its frame(t); the same t paints the same pixels on any machine, in any worker.

   Landing is the contract. Each block has one moment the narration points at (a figure reaching its value, a seal
   hitting the card, a surface forming). `LAND` is that moment in block-local seconds; `land()` returns it as film
   time, `land(tFilm)` re-anchors the block so the moment falls exactly on tFilm (the usual way to key a block to a
   spoken word: BL2.countUp(host, { … }).land(wt('open', 'percent'))). Pass `start` instead to key the entrance.

   Three rules keep a block seek-safe, and every helper below obeys them:
     1. explicit from-values on every tween (fromTo; never a bare .to() whose start is read from the DOM),
     2. the DOM's initial inline state equals the first tween's from-state (set in init(), re-applied on remount),
     3. no zero-duration tweens: a hard cut is a 1/60 s tween with a step ease that is 1 on the cut frame.
   Count-ups and typed text are written by two tiny GSAP plugins (b2num, b2txt) whose render() is a pure function of
   the eased ratio, so they survive suppressed-event seeks and never depend on history.

   Honesty: blocks are for RECREATED cards, call-outs and openers. They frame, transition between or sit beside
   product footage; they never recolour, warp or grain the product pixels (BL2.flash passes over footage only inside
   the cut window, ≤ 0.5 s). Fictional content only in examples ("Acme"). Reference: references/blocks2.md. */
(function (root) {
  'use strict';
  const M = root.MOTION;
  if (!M) throw new Error('blocks2.js: load gsap and lib/motion.js before lib/blocks2.js');
  const G = M.gsap;

  /* ------------------------------------------------------------ tokens and measured numbers ---------------- */
  const TOK = { paper: '#082A34', paper2: '#204A56', ink: '#E9F3F9', cream: '#ECDEC3', coral: '#E56B5E', mint: '#81A9AB', gold: '#E8C874', black: '#05161C',
    grey: '#7E939B', title: 'Georgia,serif', body: "Arial,'Segoe UI',sans-serif", mono: "Consolas,'Courier New',monospace" };
  const N = {
    arrive: 0.38,        // every card / figure entrance: opacity power2.out, y 16 px + scale 0.98 → 1 power3.out
    count: 1.72,         // default count duration, sine.inOut
    pulse: 0.165,        // landing pulse: 1 → 1.07 power3.out, back power2.out, each 0.165 s
    pulseScale: 1.07,
    snap: 0.02,          // "lands with a 2 % snap": scale 1.02 on the landing frame, settles power3.out
    snapDur: 0.24,
    cut: 1 / 60,         // a hard cut is a one-tick tween with a step ease
    exit: 0.36,          // exits ≈ 75 % of an entrance window, power4.in
    flashPeak: 0.55, flashDur: 0.28,
    type: 0.9,           // decision card: the whole JSON block types in 0.9 s (machine rhythm)
    cps: [55, 90],       // human typing: characters per second, drawn per word
    keyGaps: [0.033, 0.067, 0.100, 0.133, 0.167, 0.200], keyW: [3, 5, 4, 2, 1, 1],   // key-level human rhythm (mean ≈ 90 ms)
    machine: 0.022,      // machine typing (audit line): 22 ms per character
    dotsAt: 0.30, dotsGone: 0.567, streamAt: 0.633,   // chat: thinking dots after the send, stream start
    wordGap: 0.367, wordZero: 0.15, wordInk: 0.267,     // chat stream: gaps 0–367 ms, 15 % zero bursts, grey → ink
    receiptAt: 0.467,    // receipt line after the last streamed word
    push: 0.012          // the sanctioned slow push, 1.2 % per second
  };
  const HARD = p => (p >= 1 ? 1 : 0);   // step ease: 0 until the tween's last tick, 1 on it (GSAP clamps the end within 1e-10)

  /* ------------------------------------------------------------ small helpers --------------------------------- */
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const mk = (tag, cls, parent, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; if (parent) parent.appendChild(e); return e; };
  const SVGNS = 'http://www.w3.org/2000/svg';
  const svg = (name, attrs, parent) => { const e = document.createElementNS(SVGNS, name); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
  const fmtNum = (v, dec, locale) => { if (Math.abs(v) < 0.5 * Math.pow(10, -(dec || 0))) v = 0; return v.toLocaleString(locale || 'en-US', { minimumFractionDigits: dec || 0, maximumFractionDigits: dec || 0 }); };   // never "-0"
  const hash = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
  const pick = (rnd, vals, w) => { const tot = w.reduce((a, b) => a + b, 0); let r = rnd() * tot; for (let i = 0; i < vals.length; i++) { r -= w[i]; if (r < 0) return vals[i]; } return vals[vals.length - 1]; };
  const lower = (lo, hi) => (lo < hi ? lo : hi);

  /* set NOW: motion.js keeps gsap's global timeline paused, and a plain gsap.set() under a paused ancestor only renders on
     the next tick — which never comes. An explicit immediateRender writes the values on this line. */
  function set(el, vars) { return G.set(el, Object.assign({ immediateRender: true, lazy: false, force3D: false }, vars)); }
  /* tween wrapper: explicit from, no immediate render (the from-state is applied when the tween is reached), no lazy writes,
     and 2D transforms only — a 3D transform promotes the element to a compositor layer whose raster scale Chrome chooses
     from wall-clock animation heuristics (measured: a 0.9 → 1 button press differed run-to-run at 68 dB); 2D transforms
     rasterize at exact scale on every frame */
  function tw(tl, el, from, to, at) { return tl.fromTo(el, from, Object.assign({ immediateRender: false, lazy: false, force3D: false }, to), at); }
  /* arrive: 0.38 s — opacity power2.out; y 16 px + scale 0.98 → 1 power3.out (two tweens so each has its own ease) */
  function arrive(tl, el, at, o) {
    o = o || {}; const dur = o.dur || N.arrive;
    tw(tl, el, { opacity: 0 }, { opacity: 1, duration: dur, ease: 'power2.out' }, at);
    tw(tl, el, { y: o.dy === undefined ? 16 : o.dy, x: o.dx || 0, scale: o.scale0 === undefined ? 0.98 : o.scale0 }, { y: 0, x: 0, scale: 1, duration: dur, ease: 'power3.out' }, at);
    return at + dur;
  }
  /* pulse on a landing: 1 → 1.07 over 0.165 s power3.out, back over 0.165 s power2.out */
  function pulse(tl, el, at, s) {
    s = s || N.pulseScale;
    tw(tl, el, { scale: 1 }, { scale: s, duration: N.pulse, ease: 'power3.out' }, at);
    tw(tl, el, { scale: s }, { scale: 1, duration: N.pulse, ease: 'power2.out' }, at + N.pulse);
    return at + 2 * N.pulse;
  }
  /* snap: the element is 2 % large on the landing frame and settles over 0.24 s power3.out */
  function snap(tl, el, at, amt, dur) { tw(tl, el, { scale: 1 + (amt === undefined ? N.snap : amt) }, { scale: 1, duration: dur || N.snapDur, ease: 'power3.out' }, at); return at + (dur || N.snapDur); }
  /* hard cut: visible (or hidden) from the cut frame on; nothing in between */
  function cutIn(tl, el, at) { tw(tl, el, { opacity: 0 }, { opacity: 1, duration: N.cut, ease: HARD }, at - N.cut); }
  function cutOut(tl, el, at) { tw(tl, el, { opacity: 1 }, { opacity: 0, duration: N.cut, ease: HARD }, at - N.cut); }
  /* exit: 'fade' | 'up' (−18 px) | 'left' (−120 px, the house current); 0.36 s power4.in */
  function exit(tl, el, at, kind) {
    if (!kind || kind === 'none' || !Number.isFinite(at)) return;
    const to = { opacity: 0, duration: N.exit, ease: 'power4.in' }, from = { opacity: 1 };
    if (kind === 'up') { from.y = 0; to.y = -18; } else if (kind === 'left') { from.x = 0; to.x = -120; }
    tw(tl, el, from, to, at);
  }
  /* fade a child in (opacity only) over a window */
  function fadeIn(tl, el, at, dur, ease) { tw(tl, el, { opacity: 0 }, { opacity: 1, duration: dur || 0.3, ease: ease || 'power2.out' }, at); return at + (dur || 0.3); }
  /* draw an SVG stroke by dash offset: path length L → 0 */
  function draw(tl, el, at, dur, ease) {
    const L = (el.getTotalLength ? el.getTotalLength() : 0) || parseFloat(el.getAttribute('data-len') || '0') || 1;
    set(el, { strokeDasharray: L, strokeDashoffset: L, opacity: 0 });   // hidden until the draw starts: a fully offset dash still leaves a one-pixel speck at the path start
    tw(tl, el, { opacity: 0 }, { opacity: 1, duration: 0.05, ease: 'none' }, at);
    tw(tl, el, { strokeDashoffset: L }, { strokeDashoffset: 0, duration: dur || 0.5, ease: ease || 'power3.out' }, at);
    return at + (dur || 0.5);
  }

  /* ------------------------------------------------------------ GSAP plugins (pure of the eased ratio) -------- */
  /* b2num: { from, to, dec, prefix, suffix, token, locale } → textContent; `token` is shown verbatim at ratio 1 */
  G.registerPlugin({ name: 'b2num', headless: true,
    init(target, v) { this.t = target; this.v = v; },
    render(r, d) { const v = d.v; const s = r >= 1 && v.token != null ? String(v.token) : fmtNum(v.from + (v.to - v.from) * r, v.dec, v.locale); d.t.textContent = (v.prefix || '') + s + (v.suffix || ''); } });
  /* b2txt: { text, times[] (cumulative seconds per character, last = total), total, before? } → text.slice(0, n);
     with `before`, that string is shown until the ratio reaches 1 (a hard clear / replace on one frame) */
  G.registerPlugin({ name: 'b2txt', headless: true,
    init(target, v) { this.t = target; this.v = v; },
    render(r, d) { const v = d.v; if (v.before != null && r < 1) { d.t.textContent = v.before; return; }
      const lim = r * v.total + 1e-9, T = v.times; let lo = 0, hi = T.length; while (lo < hi) { const m = (lo + hi) >> 1; if (T[m] <= lim) lo = m + 1; else hi = m; } d.t.textContent = v.text.slice(0, lo); } });
  /* lay a typed text tween: the span is empty before `at`, complete at `at + total` */
  function typeInto(tl, span, sched, at) { tw(tl, span, { b2txt: { text: sched.text, times: sched.times, total: 1e-9 } }, { b2txt: { text: sched.text, times: sched.times, total: sched.total }, duration: Math.max(sched.total, 1e-3), ease: 'none' }, at); return at + sched.total; }

  /* ------------------------------------------------------------ typing schedules (pure, seeded) --------------- */
  /* human word-chunk rhythm: a cps per word drawn from [55, 90]; pauses: 0.5 s after . ! ?, 0.15 s after , ; : */
  function humanTimes(text, rnd, o) {
    o = o || {}; const cps = o.cps || N.cps, times = []; let t = 0;
    const toks = text.match(/\S+\s*/g) || [text];
    for (const tok of toks) {
      const dt = 1 / (cps[0] + (cps[1] - cps[0]) * rnd());
      for (let i = 0; i < tok.length; i++) { t += dt; times.push(t); }
      if (/[.!?]\s*$/.test(tok)) t += o.stop === undefined ? 0.5 : o.stop; else if (/[,;:]\s*$/.test(tok)) t += o.comma === undefined ? 0.15 : o.comma;
    }
    return fitTimes(text, times, o.total);
  }
  /* key-level human rhythm for short words ("Submit"): gaps from {33 … 200} ms weighted to the 67–100 ms mode */
  function keyTimes(text, rnd, o) {
    o = o || {}; const times = []; let t = 0;
    for (let i = 0; i < text.length; i++) { if (i > 0) t += pick(rnd, N.keyGaps, N.keyW); else t += 0.04; times.push(t); }
    return fitTimes(text, times, o.total);
  }
  /* machine rhythm: a constant per-character step, a short breath on every newline */
  function machineTimes(text, o) {
    o = o || {}; const per = o.per || N.machine, times = []; let t = 0;
    for (let i = 0; i < text.length; i++) { t += text[i] === '\n' ? per * 3 : per; times.push(t); }
    return fitTimes(text, times, o.total);
  }
  /* scale a schedule onto an exact total (compress or stretch), so a block can promise "typed in 0.9 s" */
  function fitTimes(text, times, total) {
    const nat = times.length ? times[times.length - 1] : 0;
    if (total && nat > 0) { const k = total / nat; for (let i = 0; i < times.length; i++) times[i] *= k; }
    return { text, times, total: times.length ? times[times.length - 1] : 0 };
  }

  /* ------------------------------------------------------------ handle: mount, land, sync ---------------------- */
  /* build(tl, api) is laid on a fresh timeline each mount; init() re-applies the DOM from-state first */
  function handle(id, el, o, LAND, init, build, syncLocal) {
    installStyles();
    const h = { id, el, tl: null, block: null, start: 0, end: Infinity, LAND, o };
    const endOf = start => (o.end !== undefined ? o.end : o.span !== undefined ? start + o.span : Infinity);   // `span` keeps the window relative when a block is re-anchored
    h.remount = function (start) {
      h.start = start; h.end = endOf(start); init();
      h.block = M.block(id, (tl, _el, api) => build(tl, api), { el, start, end: h.end, exit: o.exit && o.exit !== 'none' ? N.exit : 0, seed: o.seed });
      h.tl = h.block.tl; return h;
    };
    h.land = function (t) { return t === undefined ? h.start + LAND : h.remount(t - LAND); };
    h.sync = function () { return (syncLocal || []).map(s => ({ id: s.id, t: h.start + s.t })); };
    h.at = function (t) { const l = t - h.start; return { local: l, u: LAND > 0 ? clamp(l / LAND, 0, 1) : (l >= 0 ? 1 : 0), landed: l >= LAND, inWindow: t >= h.start && t < h.end }; };
    h.remount(o.start !== undefined ? o.start : o.land !== undefined ? o.land - LAND : 0);
    return h;
  }
  const seedOf = (o, id) => (o.seed === undefined ? hash(id) : o.seed);

  /* ============================================================ countUp ======================================== */
  /* BL2.countUp(host, { id='count', land | start, end, exit='none', value, from=0, dec=0, prefix='', suffix='', token,
                        label, sub, count=1.72, mode='count'|'land', then:{ value|token, from=0, dec, prefix, suffix, gap=0.5, count=0.9 } })
     Schedule (local): arrive 0.38 → count `count` s sine.inOut → LAND, pulse 1.07/0.165 s; label 0.15–0.45 s; sub lands
     0.1 s after LAND. mode 'land': the figure arrives already at its value and the pulse IS the landing (LAND = 0.38) —
     for a small integer, counting 0 → 1 → 2 → 3 parades three values that are not the claim; the pulse on the spoken
     word is the whole event. With `then` (a two-figure transition, "29 % → <1 %"): the first figure lands, waits `gap`, dims to
     mint while an arrow draws (0.3 s power3.out); the second figure arrives 0.2 s into the arrow and counts (0.9 s) or
     lands its token; LAND = the second landing. Tabular digits; the figure's min-width is fixed in ch so nothing shifts. */
  function countUp(host, o) {
    o = Object.assign({ id: 'count', value: 0, from: 0, dec: 0, prefix: '', suffix: '', count: N.count, size: 128 }, o || {});
    if (o.mode === 'land') { o.from = o.value; o.count = 0; }   // the figure is its value from the first frame it is visible
    const el = mk('div', 'b2 b2-count', host);
    el.style.fontSize = o.size + 'px';
    const label = mk('div', 'b2-count-label', el, o.label || ''); if (!o.label) label.style.display = 'none';
    const row = mk('div', 'b2-count-row', el);
    const figA = mk('span', 'b2-fig', row);
    const finalA = o.prefix + (o.token != null ? String(o.token) : fmtNum(o.value, o.dec, o.locale)) + o.suffix;
    figA.style.minWidth = finalA.length + 'ch';
    let arrow = null, head = null, figB = null, finalB = '';
    const TH = o.then ? Object.assign({ from: 0, dec: o.dec, prefix: '', suffix: o.suffix, gap: 0.5, count: 0.9 }, o.then) : null;
    if (TH) {
      arrow = mk('span', 'b2-arrow', row);
      const s = svg('svg', { viewBox: '0 0 48 24', width: '0.42em', height: '0.21em' }, arrow);
      head = svg('path', { d: 'M4 12 H42 M32 3 L42 12 L32 21', fill: 'none', stroke: TOK.mint, 'stroke-width': 2.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, s);
      figB = mk('span', 'b2-fig b2-fig-b', row);
      finalB = TH.prefix + (typeof TH.value === 'number' ? fmtNum(TH.value, TH.dec, o.locale) : String(TH.token != null ? TH.token : TH.value)) + TH.suffix;
      figB.style.minWidth = finalB.length + 'ch';
    }
    const sub = mk('div', 'b2-count-sub', el, o.sub || ''); if (!o.sub) sub.style.display = 'none';
    /* local schedule */
    const landA = N.arrive + o.count;
    let LAND = landA, arrowAt = 0, bAt = 0, landB = 0;
    if (TH) { arrowAt = landA + TH.gap; bAt = arrowAt + 0.2; landB = bAt + (typeof TH.value === 'number' ? Math.max(N.arrive, TH.count) : N.arrive); LAND = landB; }
    const init = () => {
      set(el, { opacity: 0, y: 16, scale: 0.98 }); set(label, { opacity: 0 }); set(sub, { opacity: 0, y: 6 });
      figA.textContent = o.prefix + fmtNum(o.from, o.dec, o.locale) + o.suffix; set(figA, { scale: 1, color: TOK.ink });
      if (TH) { set(arrow, { opacity: 0 }); figB.textContent = typeof TH.value === 'number' ? TH.prefix + fmtNum(TH.from, TH.dec, o.locale) + TH.suffix : finalB; set(figB, { opacity: 0, x: -10, scale: 0.98 }); }
    };
    el.dataset.align = o.align || 'left';
    const build = (tl, api) => {
      arrive(tl, el, 0);
      if (o.label) fadeIn(tl, label, 0.15, 0.3);
      if (o.count > 0) tw(tl, figA, { b2num: { from: o.from, to: o.value, dec: o.dec, prefix: o.prefix, suffix: o.suffix, locale: o.locale } },
        { b2num: { from: o.from, to: o.value, dec: o.dec, prefix: o.prefix, suffix: o.suffix, token: o.token, locale: o.locale }, duration: o.count, ease: 'sine.inOut' }, N.arrive);
      else if (o.token != null) figA.textContent = o.prefix + String(o.token) + o.suffix;   // mode 'land' with a token figure
      pulse(tl, figA, landA);
      if (TH) {
        tw(tl, figA, { color: TOK.ink }, { color: TOK.mint, duration: 0.3, ease: 'power2.out' }, arrowAt);
        fadeIn(tl, arrow, arrowAt, 0.12); draw(tl, head, arrowAt, 0.3, 'power3.out');
        tw(tl, figB, { opacity: 0 }, { opacity: 1, duration: N.arrive, ease: 'power2.out' }, bAt);
        tw(tl, figB, { x: -10, scale: 0.98 }, { x: 0, scale: 1, duration: N.arrive, ease: 'power3.out' }, bAt);
        if (typeof TH.value === 'number') tw(tl, figB, { b2num: { from: TH.from, to: TH.value, dec: TH.dec, prefix: TH.prefix, suffix: TH.suffix, locale: o.locale } },
          { b2num: { from: TH.from, to: TH.value, dec: TH.dec, prefix: TH.prefix, suffix: TH.suffix, token: TH.token, locale: o.locale }, duration: TH.count, ease: 'sine.inOut' }, bAt);
        pulse(tl, figB, landB);   // a token figure ("<1 %") is set at init and simply arrives, then pulses
      }
      if (o.sub) { tw(tl, sub, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.3, ease: 'power2.out' }, LAND + 0.1); }
      exit(tl, el, api.exitAt, o.exit);
    };
    const syncL = [{ id: 'land', t: landA }]; if (TH) syncL.push({ id: 'arrow', t: arrowAt }, { id: 'land-2', t: landB });
    return handle(o.id, el, o, LAND, init, build, syncL);
  }

  /* ============================================================ decisionCard =================================== */
  /* BL2.decisionCard(host, { id='decision', land | start, end, exit, title='decision', fields:{…}, seal='receipt stamped',
                              typeDur=0.9, sealAt=+0.25 })
     A monospace card. Arrive 0.38 s; the JSON-like block types in `typeDur` (0.9 s, machine rhythm, keys and values
     coloured: keys mint, strings cream, numbers gold, booleans coral) behind a 2 px caret; `sealAt` after the last
     character a rotated seal (−6°) hits from scale 1.35 over 0.22 s power3.in and the card recoils 2 % — that frame
     is LAND. The caret dies on the seal frame. Fields are rendered in the order given; values are shown verbatim. */
  function decisionCard(host, o) {
    o = Object.assign({ id: 'decision', title: 'decision', seal: 'receipt stamped', typeDur: N.type, sealAt: 0.25, width: 520 }, o || {});
    const F = o.fields || { decision: 'hold', rv: 0.82, confidence: 'high', escalate: false, receipt: 'rcpt_7f3a' };
    const el = mk('div', 'b2 b2-dcard', host); el.style.width = o.width + 'px';
    const head = mk('div', 'b2-dcard-head', el); mk('span', 'b2-dcard-dot', head); mk('span', 'b2-dcard-title', head, o.title);
    const body = mk('pre', 'b2-dcard-body', el);
    /* one span per token so colours survive typing: the typed text is the concatenation, revealed by character count */
    const keys = Object.keys(F), pad = Math.max(...keys.map(k => k.length)) + 3;
    const toks = [{ c: 'b2-p', s: '{\n' }];
    keys.forEach((k, i) => {
      const v = F[k], cls = typeof v === 'number' ? 'b2-n' : typeof v === 'boolean' ? 'b2-b' : 'b2-s';
      toks.push({ c: 'b2-p', s: '  ' }, { c: 'b2-k', s: '"' + k + '":' }, { c: 'b2-p', s: ' '.repeat(pad - k.length - 3 + 1) }, { c: cls, s: typeof v === 'string' ? '"' + v + '"' : String(v) }, { c: 'b2-p', s: (i < keys.length - 1 ? ',' : '') + '\n' });
    });
    toks.push({ c: 'b2-p', s: '}' });
    const full = toks.map(t => t.s).join('');
    const spans = toks.map(t => mk('span', t.c, body));
    const caret = mk('span', 'b2-caret', body);
    const sched = machineTimes(full, { total: o.typeDur });
    /* per-token schedules: each span types its slice during its own window of the shared schedule */
    let off = 0; const parts = toks.map((t, i) => { const a = off, b = off + t.s.length; off = b; const t0 = a > 0 ? sched.times[a - 1] : 0; const times = sched.times.slice(a, b).map(x => x - t0); return { span: spans[i], at: t0, sched: { text: t.s, times, total: times.length ? times[times.length - 1] : 0 } }; });
    const seal = mk('div', 'b2-seal', el, o.seal);
    const typeAt = N.arrive * 0.6, typedAt = typeAt + sched.total, sealHit = typedAt + o.sealAt, LAND = sealHit;
    const init = () => {
      set(el, { opacity: 0, y: 16, scale: 0.98 }); spans.forEach(s => { s.textContent = ''; }); set(caret, { opacity: 0 });
      set(seal, { opacity: 0, scale: 1.35, rotation: -6 });
    };
    const build = (tl, api) => {
      arrive(tl, el, 0);
      fadeIn(tl, caret, typeAt - 0.1, 0.06);
      parts.forEach(p => { if (p.sched.text.length) typeInto(tl, p.span, p.sched, typeAt + p.at); });
      tw(tl, caret, { opacity: 1 }, { opacity: 0, duration: N.cut, ease: HARD }, sealHit - N.cut);
      tw(tl, seal, { opacity: 0 }, { opacity: 1, duration: 0.22, ease: 'power3.in' }, sealHit - 0.22);
      tw(tl, seal, { scale: 1.35, rotation: -6 }, { scale: 1, rotation: -6, duration: 0.22, ease: 'power3.in' }, sealHit - 0.22);
      tw(tl, el, { scale: 1 - N.snap }, { scale: 1, duration: N.snapDur, ease: 'power3.out' }, sealHit);   // the recoil
      exit(tl, el, api.exitAt, o.exit);
    };
    return handle(o.id, el, o, LAND, init, build, [{ id: 'typed', t: typedAt }, { id: 'sealed', t: sealHit }]);
  }

  /* ============================================================ receipt ======================================== */
  /* BL2.receipt(host, { id='receipt', land | start, end, exit, parts:[…], check=true, tone='mint' })
     A slim pill: check glyph + parts joined by '·'. Arrives 0.42 s (y 14 → 0, power4.out) — the landing frame carries
     the 2 % snap (scale 1.02 → 1, 0.24 s power3.out); the check draws over 0.3 s from landing − 0.2; parts cascade
     from 0.12 s with 0.06 s gaps (×0.84), 0.28 s each. LAND = 0.42. */
  function receipt(host, o) {
    o = Object.assign({ id: 'receipt', parts: ['grounded in the ontology', '21 tools', '14 tables', '0 writes'], check: true, tone: 'mint' }, o || {});
    const el = mk('div', 'b2 b2-receipt b2-tone-' + o.tone, host);
    let check = null;
    if (o.check) { const s = svg('svg', { viewBox: '0 0 24 24', class: 'b2-receipt-check' }, el); check = svg('path', { d: 'M4 12.5 L9.5 18 L20 6.5', fill: 'none', stroke: 'currentColor', 'stroke-width': 2.2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, s); }
    const parts = [];
    o.parts.forEach((p, i) => { if (i) parts.push(mk('span', 'b2-receipt-sep', el, '·')); parts.push(mk('span', 'b2-receipt-part', el, p)); });
    const LAND = 0.42;
    const init = () => { set(el, { opacity: 0, y: 14, scale: 1 }); parts.forEach(p => set(p, { opacity: 0, y: 4 })); if (check) set(check, { strokeDashoffset: 40, strokeDasharray: 40 }); };
    const build = (tl, api) => {
      tw(tl, el, { opacity: 0 }, { opacity: 1, duration: 0.3, ease: 'power2.out' }, 0);
      tw(tl, el, { y: 14 }, { y: 0, duration: LAND, ease: 'power4.out' }, 0);
      snap(tl, el, LAND);
      if (check) draw(tl, check, LAND - 0.2, 0.3, 'power3.out');
      let gap = 0.06, acc = 0.12;
      parts.forEach(p => { tw(tl, p, { opacity: 0, y: 4 }, { opacity: 1, y: 0, duration: 0.28, ease: 'power3.out' }, acc); acc += gap; gap *= 0.84; });
      exit(tl, el, api.exitAt, o.exit);
    };
    return handle(o.id, el, o, LAND, init, build, [{ id: 'land', t: LAND }]);
  }

  /* ============================================================ twoLayers ====================================== */
  /* BL2.twoLayers(host, { id='layers', start | land, end, dur=10 (8–12), w=1000, h=560, cols=16, rows=6, seed,
                          ring='Enterprise Ontology', ringSub='generated automatically', field='tables · columns · files',
                          surface='one surface', surfaceSub='every answer grounded' })
     Pure SVG + GSAP. Phases as fractions of `dur` (10 s base): tiles scatter in (0 → 0.08·dur, seeded order, 0.3 s each);
     three waves cross the field (0.10 · 0.22 · 0.34 ·dur; each tile lifts to 0.85 opacity in 0.3 s and falls in 0.55 s,
     the middle wave in gold); the ring draws above (0.46·dur, 1.1 s power3.inOut) with seven nodes cascading, its label
     rising; leaders fall from four nodes to the tiles they govern (0.60·dur, 0.5 s each, +0.08 s); the surface outline
     draws around both (0.70·dur, 0.9 s power3.inOut) and its fill rises; LAND = 0.84·dur — the surface label lands with
     the 2 % snap on the whole diagram, tiles dim beneath it and the ring turns gold; then the sanctioned slow push
     (1.2 %/s) to `end`. */
  function twoLayers(host, o) {
    o = Object.assign({ id: 'layers', dur: 10, w: 1000, h: 560, cols: 16, rows: 6, ring: 'Enterprise Ontology', ringSub: 'generated automatically', field: 'tables · columns · files', surface: 'one surface', surfaceSub: 'every answer grounded' }, o || {});
    const D = clamp(o.dur, 8, 12), W = o.w, H = o.h, rnd = M.rng(seedOf(o, o.id));
    const el = mk('div', 'b2 b2-layers', host); el.style.width = W + 'px'; el.style.height = H + 'px';
    const root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H }, el);
    const defs = svg('defs', {}, root);
    const grad = svg('linearGradient', { id: o.id + '-g', x1: '0', y1: '0', x2: '1', y2: '1' }, defs);
    svg('stop', { offset: '0', 'stop-color': TOK.cream }, grad); svg('stop', { offset: '1', 'stop-color': TOK.mint }, grad);
    const all = svg('g', { class: 'b2-layers-all' }, root);
    /* surface (drawn first so it sits behind) */
    const sx = 60, sy = 36, sw = W - 120, sh = H - 72;
    const surfFill = svg('rect', { x: sx, y: sy, width: sw, height: sh, rx: 22, fill: TOK.ink, 'fill-opacity': 0 }, all);
    const surfLine = svg('rect', { x: sx, y: sy, width: sw, height: sh, rx: 22, fill: 'none', stroke: 'url(#' + o.id + '-g)', 'stroke-width': 1.6 }, all);
    /* field of tiles: a tabletop tilt */
    const cw = 40, ch = 28, fw = o.cols * cw - 10, fieldG = svg('g', { transform: 'translate(' + (W / 2) + ' ' + (H * 0.58) + ') skewX(-14) scale(1.12 0.74) translate(' + (-fw / 2) + ' 0)' }, all);
    const tiles = [];
    for (let r = 0; r < o.rows; r++) for (let c = 0; c < o.cols; c++) {
      const kind = rnd(), tw_ = kind < 0.55 ? 30 : kind < 0.85 ? 14 : 20;
      const t = svg('rect', { x: c * cw + (30 - tw_) / 2, y: r * ch, width: tw_, height: 18, rx: 3, fill: TOK.mint, 'fill-opacity': 0.16, stroke: TOK.mint, 'stroke-opacity': 0.35, 'stroke-width': 1 }, fieldG);
      tiles.push({ el: t, c, r, order: rnd(), cx: c * cw + 15, cy: r * ch + 9 });
    }
    const fieldLabel = svg('text', { x: W / 2, y: H * 0.58 + 152, 'text-anchor': 'middle', fill: TOK.mint, 'font-family': TOK.body, 'font-size': 14, 'letter-spacing': 2 }, all); fieldLabel.textContent = o.field.toUpperCase();
    /* ring (a dotted orbit sits outside it so the label inside stays clean) */
    const rcx = W / 2, rcy = H * 0.31, rr = 100;
    const ringIn = svg('circle', { cx: rcx, cy: rcy, r: rr + 16, fill: 'none', stroke: TOK.mint, 'stroke-opacity': 0.5, 'stroke-width': 1, 'stroke-dasharray': '2 8' }, all);
    const ring = svg('circle', { cx: rcx, cy: rcy, r: rr, fill: 'none', stroke: TOK.cream, 'stroke-width': 2.2, transform: 'rotate(-90 ' + rcx + ' ' + rcy + ')' }, all);
    const nodes = []; for (let i = 0; i < 7; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 7; nodes.push({ el: svg('circle', { cx: rcx + rr * Math.cos(a), cy: rcy + rr * Math.sin(a), r: 5, fill: TOK.gold }, all), x: rcx + rr * Math.cos(a), y: rcy + rr * Math.sin(a) }); }
    const ringT = svg('text', { x: rcx, y: rcy - 2, 'text-anchor': 'middle', fill: TOK.ink, 'font-family': TOK.title, 'font-size': 24 }, all); ringT.textContent = o.ring;
    const ringS = svg('text', { x: rcx, y: rcy + 20, 'text-anchor': 'middle', fill: TOK.mint, 'font-family': TOK.body, 'font-size': 12, 'letter-spacing': 1.5 }, all); ringS.textContent = o.ringSub.toUpperCase();
    /* leaders from four lower nodes to governed tile clusters (screen-space endpoints via the field transform) */
    const ctm = () => fieldG.getCTM(), toScreen = (x, y) => { const m = ctm(); if (!m) return { x: W / 2, y: H * 0.56 }; const p = root.createSVGPoint(); p.x = x; p.y = y; const q = p.matrixTransform(m); return { x: q.x, y: q.y }; };
    const governed = [tiles[1 * o.cols + 2], tiles[2 * o.cols + 6], tiles[1 * o.cols + 10], tiles[3 * o.cols + 13]].filter(Boolean);
    const leaderNodes = [nodes[4], nodes[3], nodes[3], nodes[4]];
    const leaders = governed.map((g, i) => { const p = toScreen(g.cx, g.cy), n = leaderNodes[i] || nodes[3]; return svg('path', { d: 'M' + n.x + ' ' + n.y + ' Q ' + ((n.x + p.x) / 2) + ' ' + (n.y + 60) + ' ' + p.x + ' ' + p.y, fill: 'none', stroke: TOK.gold, 'stroke-opacity': 0.8, 'stroke-width': 1.2 }, all); });
    /* surface label */
    /* surface labels live in the plate's free corners (the ring is centred, so the corners are quiet) */
    const surfT = svg('text', { x: sx + 32, y: sy + 48, 'text-anchor': 'start', fill: TOK.gold, 'font-family': TOK.title, 'font-size': 28 }, all); surfT.textContent = o.surface;
    const surfS = svg('text', { x: sx + sw - 32, y: sy + 44, 'text-anchor': 'end', fill: TOK.mint, 'font-family': TOK.body, 'font-size': 13, 'letter-spacing': 2 }, all); surfS.textContent = o.surfaceSub.toUpperCase();
    /* schedule */
    const tField = 0, tWave = [0.10 * D, 0.22 * D, 0.34 * D], tRing = 0.46 * D, tLead = 0.60 * D, tSurf = 0.70 * D, LAND = 0.84 * D;
    const init = () => {
      set(el, { opacity: 1 }); set(all, { scale: 1, transformOrigin: '50% 50%' });
      tiles.forEach(t => set(t.el, { scale: 0, transformOrigin: '50% 50%', fillOpacity: 0.16, fill: TOK.mint }));
      set(fieldLabel, { opacity: 0 }); set([ringIn, ringT, ringS, surfT, surfS], { opacity: 0 }); set(ring, { stroke: TOK.cream });
      nodes.forEach(n => set(n.el, { scale: 0, transformOrigin: '50% 50%' }));
      set(surfFill, { fillOpacity: 0 }); set(surfT, { y: 8 }); set(fieldG, { opacity: 1 });   // on SVG, GSAP x/y are translates
    };
    const build = (tl, api) => {
      /* 1 — tiles scatter in */
      const order = tiles.slice().sort((a, b) => a.order - b.order);
      order.forEach((t, i) => tw(tl, t.el, { scale: 0 }, { scale: 1, duration: 0.3, ease: 'power3.out' }, tField + (0.08 * D - 0.3) * i / order.length));
      fadeIn(tl, fieldLabel, 0.06 * D, 0.4);
      /* 2 — waves */
      tWave.forEach((t0, k) => { const col = k === 1 ? TOK.gold : TOK.mint; tiles.forEach(t => { const d = 0.9 * t.c / o.cols + 0.06 * t.order; const up = t0 + d;
        tw(tl, t.el, { fillOpacity: 0.16, fill: TOK.mint }, { fillOpacity: 0.85, fill: col, duration: 0.3, ease: 'power2.out' }, up);
        tw(tl, t.el, { fillOpacity: 0.85, fill: col }, { fillOpacity: 0.16, fill: TOK.mint, duration: 0.55, ease: 'power2.in' }, up + 0.3); }); });
      /* 3 — the ring */
      draw(tl, ring, tRing, 1.1, 'power3.inOut'); fadeIn(tl, ringIn, tRing + 0.4, 0.5);
      nodes.forEach((n, i) => tw(tl, n.el, { scale: 0 }, { scale: 1, duration: 0.3, ease: 'power3.out' }, tRing + 0.5 + 0.07 * i));
      tw(tl, ringT, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.4, ease: 'power3.out' }, tRing + 0.7); fadeIn(tl, ringS, tRing + 0.9, 0.3);
      /* 4 — leaders + governed tiles hold gold */
      leaders.forEach((l, i) => { draw(tl, l, tLead + 0.08 * i, 0.5, 'power2.out'); const g = governed[i]; if (g) { tw(tl, g.el, { fillOpacity: 0.16, fill: TOK.mint }, { fillOpacity: 0.95, fill: TOK.gold, duration: 0.25, ease: 'power2.out' }, tLead + 0.08 * i + 0.45); } });
      /* 5 — one surface */
      draw(tl, surfLine, tSurf, 0.9, 'power3.inOut'); tw(tl, surfFill, { fillOpacity: 0 }, { fillOpacity: 0.06, duration: 0.6, ease: 'power2.out' }, tSurf + 0.5);
      fadeIn(tl, surfS, tSurf + 0.6, 0.3);
      tw(tl, surfT, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.3, ease: 'power3.out' }, LAND - 0.3);
      snap(tl, all, LAND);
      tw(tl, fieldG, { opacity: 1 }, { opacity: 0.55, duration: 0.5, ease: 'power2.out' }, LAND);
      tw(tl, ring, { stroke: TOK.cream }, { stroke: TOK.gold, duration: 0.5, ease: 'power2.out' }, LAND);
      const pushEnd = Number.isFinite(api.end) ? api.end - api.start : D;
      if (pushEnd > LAND + N.snapDur) tw(tl, all, { scale: 1 }, { scale: 1 + N.push * (pushEnd - LAND - N.snapDur), duration: pushEnd - LAND - N.snapDur, ease: 'none' }, LAND + N.snapDur);
      exit(tl, el, api.exitAt, o.exit);
    };
    const syncL = [{ id: 'field', t: tField }, { id: 'wave-1', t: tWave[0] }, { id: 'wave-2', t: tWave[1] }, { id: 'wave-3', t: tWave[2] }, { id: 'ring', t: tRing }, { id: 'leaders', t: tLead }, { id: 'surface', t: LAND }];
    const h = handle(o.id, el, Object.assign({ span: D }, o), LAND, init, build, syncL);
    h.dur = D; return h;
  }

  /* ============================================================ sceneCards ===================================== */
  /* BL2.sceneCards(host, { id='scenes', start, end, period=3, push=0.035, glWindow=0.33, cards:[{icon, title, line}] })
     Five (or n) full-plate cards. Each card is a hard cut (one-tick step) at start + k·period; inside its 3 s the card
     pushes 1 → 1.035 linearly (mid-flight on both sides of every cut), the icon draws 0.45 s, the title rises 18 px
     over 0.28 s power4.out, the line follows +0.07 s, the index rule grows 0.5 s. `cuts` lists the film times of the
     k ≥ 1 cuts; `cutAt(t)` → { k, cut, u } with u 0 → 1 across the ±glWindow/2 window around the nearest cut (null
     outside) — the hook a GL transition reads. `cardAt(t)` → index. LAND = the last card's cut. Icons: a name from
     BL2.ICONS (bank, factory, hospital, retail, telecom, energy) or an SVG path string in a 64×64 box. */
  const ICONS = {
    bank: 'M8 26 L32 10 L56 26 Z M12 30 V48 M24 30 V48 M40 30 V48 M52 30 V48 M8 52 H56',
    factory: 'M8 54 V28 L22 36 V28 L36 36 V28 L50 36 V16 H56 V54 Z M16 44 H22 M30 44 H36 M44 44 H50',
    hospital: 'M20 10 H44 V22 H56 V54 H8 V22 H20 Z M32 26 V42 M24 34 H40',
    retail: 'M14 22 H50 L54 54 H10 Z M22 22 V16 A10 10 0 0 1 42 16 V22',
    telecom: 'M32 54 V24 M20 54 L32 24 L44 54 M22 16 A14 14 0 0 1 42 16 M14 10 A24 24 0 0 1 50 10 M28 24 A4 4 0 1 0 36 24 A4 4 0 1 0 28 24',
    energy: 'M34 8 L14 36 H30 L28 56 L50 26 H34 Z'
  };
  function sceneCards(host, o) {
    o = Object.assign({ id: 'scenes', period: 3, push: 0.035, glWindow: 0.33, start: 0 }, o || {});
    const cards = o.cards || [{ icon: 'bank', title: 'Banking', line: 'Who is really behind this account?' }, { icon: 'factory', title: 'Manufacturing', line: 'Which line will miss its shift target?' }, { icon: 'hospital', title: 'Healthcare', line: 'Where are the beds we cannot see?' }, { icon: 'retail', title: 'Retail', line: 'Which stores are quietly losing margin?' }, { icon: 'telecom', title: 'Telecom', line: 'Which towers fail before the storm?' }];
    const n = cards.length, P = o.period, L0 = 0.12;   // every card's content is already mid-flight on its cut frame: its tweens start L0 before the cut, behind the hidden plate
    const el = mk('div', 'b2 b2-scenes', host);
    const items = cards.map((c, i) => {
      const outer = mk('div', 'b2-sc-card', el), inner = mk('div', 'b2-sc-push', outer);
      const idx = mk('div', 'b2-sc-idx', inner, String(i + 1).padStart(2, '0') + ' / ' + String(n).padStart(2, '0'));
      const s = svg('svg', { viewBox: '0 0 64 64', class: 'b2-sc-icon' }, inner);
      const path = svg('path', { d: ICONS[c.icon] || c.icon || ICONS.energy, fill: 'none', stroke: TOK.mint, 'stroke-width': 2.2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, s);
      const rule = mk('div', 'b2-sc-rule', inner), title = mk('div', 'b2-sc-title', inner, c.title), line = mk('div', 'b2-sc-line', inner, c.line);
      return { outer, inner, idx, path, rule, title, line };
    });
    const LAND = L0 + (n - 1) * P;   // block-local; the block itself starts L0 before the first card
    const init = () => items.forEach(it => { set(it.outer, { opacity: 0 }); set(it.inner, { scale: 1 }); set(it.title, { opacity: 0, y: 18 }); set(it.line, { opacity: 0, y: 14 }); set(it.idx, { opacity: 0 }); set(it.rule, { scaleX: 0, transformOrigin: '0 50%' }); });
    const build = (tl, api) => {
      items.forEach((it, k) => {
        const a = L0 + k * P, b = a + P;
        cutIn(tl, it.outer, a); if (k < n - 1) cutOut(tl, it.outer, b);
        tw(tl, it.inner, { scale: 1 }, { scale: 1 + o.push, duration: P + L0, ease: 'none' }, a - L0);
        draw(tl, it.path, a - L0, 0.45, 'power2.out');
        tw(tl, it.title, { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.28, ease: 'power4.out' }, a - 0.10);
        tw(tl, it.line, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.28, ease: 'power4.out' }, a - 0.04);
        tw(tl, it.rule, { scaleX: 0 }, { scaleX: 1, duration: 0.5, ease: 'power3.out' }, a - 0.06);
        fadeIn(tl, it.idx, a + 0.1, 0.25);
      });
      exit(tl, el, api.exitAt, o.exit);
    };
    const O = Object.assign({ span: L0 + n * P }, o); if (O.start !== undefined) O.start -= L0;   // `start` is the first card's cut frame
    const h = handle(o.id, el, O, LAND, init, build, cards.map((c, k) => ({ id: 'cut-' + k, t: L0 + k * P })));
    Object.defineProperty(h, 'cuts', { get() { const r = []; for (let k = 1; k < n; k++) r.push(h.start + L0 + k * P); return r; } });
    h.cardAt = t => clamp(Math.floor((t - h.start - L0) / P), 0, n - 1);
    h.cutAt = t => { let best = null; for (let k = 1; k < n; k++) { const c = h.start + L0 + k * P, u = (t - (c - o.glWindow / 2)) / o.glWindow; if (u >= 0 && u <= 1 && (!best || Math.abs(t - c) < Math.abs(t - best.cut))) best = { k, cut: c, u }; } return best; };
    return h;
  }

  /* ============================================================ chatReveal ===================================== */
  /* BL2.chatReveal(host, { id='chat', start | land, end, exit, question, answer (string | string[]), send?, answerEnd?,
                           receipt?, seed, cps=[55,90], width=560, grow=0.6 })
     A neutral chat shell. The card arrives at the composer's own height (the thread is folded to 0) and GROWS to its
     full height over `grow` s power3.out from the send (grow: 0 keeps the old fixed-height box) — an empty 150 px thread
     above a typing composer read as a frozen plate for the three seconds before the first bubble. The question types in the composer at human word-chunk rhythm (55–90 c/s, pauses after
     punctuation) behind a caret from local 0.4 s; `send` (local, default tDone + 0.167 s) lifts it into a bubble
     (0.25 s power3.out) and clears the composer; thinking dots at send + 0.30 s (three dots, −9 px bobs of 0.28 s,
     0.09 s apart, integer cycles) die the frame the stream starts (send + 0.633 s); answer words stream with seeded
     gaps 0–367 ms (15 % zero bursts), each word fading in 0.12 s and inking grey → ink over 0.267 s; `answerEnd`
     (local) compresses the stream so the last word lands there; LAND = that word. An optional receipt line lands
     0.467 s later. */
  function chatReveal(host, o) {
    o = Object.assign({ id: 'chat', question: 'Which shifts drove the unreconciled hours last quarter?', answer: ['Three night shifts at the Acme Riverside plant account for 23.75 of the 31 unreconciled hours.'], width: 560, grow: 0.6 }, o || {});
    const rnd = M.rng(seedOf(o, o.id));
    const el = mk('div', 'b2 b2-chat', host); el.style.width = o.width + 'px';
    const thread = mk('div', 'b2-chat-thread', el);
    const bubble = mk('div', 'b2-chat-q', thread, o.question);
    const dots = mk('div', 'b2-chat-dots', thread); const dotEls = [0, 1, 2].map(() => mk('span', 'b2-chat-dot', dots));
    const paras = (Array.isArray(o.answer) ? o.answer : [o.answer]).map(p => mk('p', 'b2-chat-a', thread));
    const words = []; paras.forEach((p, pi) => { (Array.isArray(o.answer) ? o.answer : [o.answer])[pi].split(' ').forEach((w, i) => { if (i) p.appendChild(document.createTextNode(' ')); words.push(mk('span', 'b2-chat-w', p, w)); }); });
    const rline = o.receipt ? mk('div', 'b2-chat-receipt', thread, o.receipt) : null;
    const composer = mk('div', 'b2-chat-composer', el); const typed = mk('span', 'b2-chat-typed', composer); const caret = mk('span', 'b2-caret', composer); const sendBtn = mk('span', 'b2-chat-send', composer, '<svg viewBox="0 0 24 24"><path d="M4 12 H19 M13 6 L19 12 L13 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>');
    /* schedule */
    const typeAt = 0.4, qs = humanTimes(o.question, rnd, { cps: o.cps }), tDone = typeAt + qs.total;
    const send = o.send !== undefined ? o.send : tDone + 0.167, dotsAt = send + N.dotsAt, streamAt = send + N.streamAt;
    let acc = 0; const wt = words.map(() => { const g = rnd() < N.wordZero ? 0 : rnd() * N.wordGap; acc += g; return acc; });
    const natEnd = streamAt + acc; let k = 1; if (o.answerEnd !== undefined && acc > 0) k = Math.max(0.05, (o.answerEnd - streamAt) / acc);
    const wordAt = wt.map(x => streamAt + x * k), LAND = wordAt.length ? wordAt[wordAt.length - 1] : streamAt, receiptAt = LAND + N.receiptAt;
    let threadH = 0;                                                     // the thread's natural height, measured once at init (fonts are loaded before a scene mounts)
    const init = () => {
      if (o.grow > 0) { thread.style.minHeight = '0px'; thread.style.height = ''; threadH = thread.offsetHeight || 0; if (threadH > 0) set(thread, { height: 0 }); }
      set(el, { opacity: 0, y: 16, scale: 0.98 }); typed.textContent = ''; set(caret, { opacity: 0 }); set(sendBtn, { opacity: 0.35 });
      set(bubble, { opacity: 0, y: 14 }); set(dots, { opacity: 0 }); dotEls.forEach(d => set(d, { y: 0 }));
      words.forEach(w => set(w, { opacity: 0, color: TOK.grey })); if (rline) set(rline, { opacity: 0, y: 6 });
    };
    const build = (tl, api) => {
      arrive(tl, el, 0);
      fadeIn(tl, caret, typeAt - 0.1, 0.06);
      typeInto(tl, typed, qs, typeAt);
      tw(tl, sendBtn, { opacity: 0.35 }, { opacity: 1, duration: 0.15, ease: 'power2.out' }, tDone);
      tw(tl, sendBtn, { scale: 1 }, { scale: 0.9, duration: 0.08, ease: 'power2.in' }, send - 0.08); tw(tl, sendBtn, { scale: 0.9 }, { scale: 1, duration: 0.16, ease: 'power2.out' }, send);
      tw(tl, typed, { b2txt: { text: qs.text, times: qs.times, total: qs.total } }, { b2txt: { text: '', times: [], total: 1, before: qs.text }, duration: N.cut, ease: HARD }, send - N.cut);   // the composer clears on the send frame
      tw(tl, caret, { opacity: 1 }, { opacity: 0, duration: N.cut, ease: HARD }, send - N.cut);
      tw(tl, sendBtn, { opacity: 1 }, { opacity: 0.35, duration: 0.2, ease: 'power2.out' }, send + 0.1);
      tw(tl, bubble, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.25, ease: 'power3.out' }, send);
      if (o.grow > 0 && threadH > 0) tw(tl, thread, { height: 0 }, { height: threadH, duration: o.grow, ease: 'power3.out' }, send - 0.05);   // the card morphs from the composer's height as the question lifts into its bubble
      /* dots: bounded integer bob cycles, gone on the stream frame */
      fadeIn(tl, dots, dotsAt, 0.12);
      const cycles = Math.max(1, Math.floor((streamAt - dotsAt - 0.12) / 0.56));
      dotEls.forEach((d, i) => { for (let c = 0; c < cycles; c++) { const t0 = dotsAt + 0.09 * i + c * 0.56; tw(tl, d, { y: 0 }, { y: -9, duration: 0.28, ease: 'sine.inOut' }, t0); tw(tl, d, { y: -9 }, { y: 0, duration: 0.28, ease: 'sine.inOut' }, t0 + 0.28); } });
      cutOut(tl, dots, streamAt);
      words.forEach((w, i) => { tw(tl, w, { opacity: 0 }, { opacity: 1, duration: 0.12, ease: 'power2.out' }, wordAt[i]); tw(tl, w, { color: TOK.grey }, { color: TOK.ink, duration: N.wordInk, ease: 'none' }, wordAt[i]); });
      if (rline) tw(tl, rline, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.3, ease: 'power3.out' }, receiptAt);
      exit(tl, el, api.exitAt, o.exit);
    };
    const h = handle(o.id, el, o, LAND, init, build, [{ id: 'typed', t: tDone }, { id: 'send', t: send }, { id: 'stream', t: streamAt }, { id: 'answered', t: LAND }].concat(rline ? [{ id: 'receipt', t: receiptAt }] : []));
    h.times = { typeAt, tDone, send, dotsAt, streamAt, natEnd, wordAt, LAND }; return h;
  }

  /* ============================================================ approvalCard =================================== */
  /* BL2.approvalCard(host, { id='approval', start | land, end, exit, title, caveat, action='Submit', button='Confirm',
                             consequence, audit, seed, width=520 })
     An action card: title and caveat (gold dash) cascade after the 0.38 s arrive; the action word types at key-level
     human rhythm from 0.9 s behind a caret; 0.25 s after the last key the button presses (0.96 for 0.08 s, back
     0.16 s); the consequence chip pops on the release (0.85 → 1, 0.3 s power3.out; coral outline) — LAND; the audit
     line types at machine rhythm (22 ms/char) from LAND + 0.35 s. */
  function approvalCard(host, o) {
    o = Object.assign({ id: 'approval', title: 'Raise the Acme Northfield credit line', caveat: 'Caveat: the ownership chain has one unverified step.', action: 'Submit', button: 'Confirm', consequence: 'writes 1 record · reversible for 24 h', audit: 'audit  rcpt_7f3a · 14:02:11 · approver a.chen', width: 520 }, o || {});
    const rnd = M.rng(seedOf(o, o.id));
    const el = mk('div', 'b2 b2-acard', host); el.style.width = o.width + 'px';
    const title = mk('div', 'b2-acard-title', el, o.title);
    const cav = mk('div', 'b2-acard-caveat', el); mk('span', 'b2-acard-dash', cav); mk('span', '', cav, o.caveat);
    const row = mk('div', 'b2-acard-row', el); const field = mk('div', 'b2-acard-field', row); const typed = mk('span', 'b2-acard-typed', field); const caret = mk('span', 'b2-caret', field); const btn = mk('div', 'b2-acard-btn', row, o.button);
    const chip = mk('div', 'b2-chip', el, o.consequence);
    const audit = mk('div', 'b2-acard-audit', el); const auditTxt = mk('span', '', audit);
    const typeAt = 0.9, ks = keyTimes(o.action, rnd), tDone = typeAt + ks.total, press = tDone + 0.25, LAND = press + 0.08, auditAt = LAND + 0.35, as = machineTimes(o.audit), auditDone = auditAt + as.total;
    const init = () => {
      set(el, { opacity: 0, y: 16, scale: 0.98 }); set([title, cav], { opacity: 0, y: 10 }); typed.textContent = ''; auditTxt.textContent = ''; set(caret, { opacity: 0 });
      set(btn, { scale: 1, opacity: 0.55 }); set(chip, { opacity: 0, scale: 0.85 }); set(audit, { opacity: 0 });
    };
    const build = (tl, api) => {
      arrive(tl, el, 0);
      tw(tl, title, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.32, ease: 'power3.out' }, 0.18);
      tw(tl, cav, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.32, ease: 'power3.out' }, 0.30);
      fadeIn(tl, caret, typeAt - 0.1, 0.06); typeInto(tl, typed, ks, typeAt);
      tw(tl, btn, { opacity: 0.55 }, { opacity: 1, duration: 0.15, ease: 'power2.out' }, tDone);
      tw(tl, caret, { opacity: 1 }, { opacity: 0, duration: N.cut, ease: HARD }, press - N.cut);
      tw(tl, btn, { scale: 1 }, { scale: 0.96, duration: 0.08, ease: 'power2.in' }, press); tw(tl, btn, { scale: 0.96 }, { scale: 1, duration: 0.16, ease: 'power2.out' }, LAND);
      tw(tl, chip, { opacity: 0, scale: 0.85 }, { opacity: 1, scale: 1, duration: 0.3, ease: 'power3.out' }, LAND);
      fadeIn(tl, audit, auditAt - 0.05, 0.1); typeInto(tl, auditTxt, as, auditAt);
      exit(tl, el, api.exitAt, o.exit);
    };
    const h = handle(o.id, el, o, LAND, init, build, [{ id: 'typed', t: tDone }, { id: 'submit', t: press }, { id: 'consequence', t: LAND }, { id: 'audit', t: auditDone }]);
    h.times = { typeAt, tDone, press, LAND, auditAt, auditDone }; return h;
  }

  /* ============================================================ flash ========================================== */
  /* BL2.flash(host, { id='flash', at, peak=0.55, dur=0.28, snap=0.02, snapEl?, color='#FFFDFA', blend='normal' })
     The editorial flash: a full-plate wash at `peak` opacity on the frame `at`, clearing to 0 over `dur` power3.out;
     `snapEl` (a dedicated wrapper — never the footage <img>) is 2 % large on that frame and settles over the same
     window. The block's window is exactly [at, at + dur], so it is inert everywhere else. LAND = at. Max one per act;
     over footage only as the cut-window hand-off (≤ 0.5 s). */
  function flash(host, o) {
    o = Object.assign({ id: 'flash', at: 0, peak: N.flashPeak, dur: N.flashDur, snap: N.snap, color: '#FFFDFA', blend: 'normal' }, o || {});
    const el = mk('div', 'b2 b2-flash', host); el.style.background = o.color; el.style.mixBlendMode = o.blend;
    /* `snapEl` lives outside the block, so its tween must not sit at local 0: MOTION renders a block at 0 whenever the
       film is before its window, and a from-state parked there would scale the world early. One tick of lead fixes it. */
    const lead = N.cut;
    const init = () => { set(el, { opacity: 0 }); if (o.snapEl) set(o.snapEl, { scale: 1 }); };
    const build = tl => {
      tw(tl, el, { opacity: o.peak }, { opacity: 0, duration: o.dur, ease: 'power3.out' }, lead);
      if (o.snapEl) tw(tl, o.snapEl, { scale: 1 + o.snap }, { scale: 1, duration: o.dur, ease: 'power3.out' }, lead);
    };
    return handle(o.id, el, Object.assign({}, o, { start: o.at - lead, span: o.dur + lead, end: undefined }), lead, init, build, [{ id: 'flash', t: lead }]);
  }

  /* ============================================================ styles ========================================= */
  let styled = false;
  function installStyles(T) {
    if (styled) return; styled = true; T = Object.assign({}, TOK, T || {});
    const css = `
.b2{position:absolute;box-sizing:border-box;color:${T.ink};font-family:${T.body};-webkit-font-smoothing:antialiased}
.b2 *{box-sizing:border-box}
.b2-caret{display:inline-block;width:2px;height:1em;background:${T.ink};vertical-align:-0.12em;margin-left:1px}
.b2-count{transform-origin:0 50%}
.b2-count-label{font:500 16px/1 ${T.body};letter-spacing:.14em;text-transform:uppercase;color:${T.mint};margin:0 0 .18em .04em}
.b2-count-row{display:flex;align-items:baseline;gap:.08em;white-space:nowrap}
.b2-fig{display:inline-block;font:400 1em/1 ${T.title};letter-spacing:-.02em;font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;transform-origin:0 70%}
.b2-count[data-align=center]{transform-origin:50% 50%}.b2-count[data-align=center] .b2-count-row{justify-content:center}.b2-count[data-align=center] .b2-fig{transform-origin:50% 70%;text-align:center}
.b2-count[data-align=center] .b2-count-label,.b2-count[data-align=center] .b2-count-sub{text-align:center}
.b2-arrow{display:inline-block;line-height:0;margin:0 .04em}
.b2-count-sub{font:400 20px/1.3 ${T.body};color:${T.cream};margin-top:.16em}
.b2-dcard{background:${T.black};border:1px solid rgba(129,169,171,.28);border-radius:12px;padding:16px 22px 20px;transform-origin:50% 50%;box-shadow:0 24px 60px rgba(5,22,28,.45)}
.b2-dcard-head{display:flex;align-items:center;gap:10px;font:500 16px/1 ${T.mono};letter-spacing:.18em;text-transform:uppercase;color:${T.mint};margin-bottom:12px}
.b2-dcard-dot{width:8px;height:8px;border-radius:50%;background:${T.coral}}
.b2-dcard-body{margin:0;font:400 20px/1.5 ${T.mono};color:${T.ink};white-space:pre;min-height:1.5em}
.b2-k{color:${T.mint}}.b2-s{color:${T.cream}}.b2-n{color:${T.gold}}.b2-b{color:${T.coral}}.b2-p{color:rgba(233,243,249,.55)}
.b2-seal{position:absolute;right:22px;bottom:18px;padding:7px 12px;border:2px solid ${T.gold};border-radius:6px;color:${T.gold};font:600 13px/1 ${T.mono};letter-spacing:.16em;text-transform:uppercase;transform-origin:50% 50%}
.b2-receipt{display:inline-flex;align-items:center;gap:10px;padding:10px 18px 10px 14px;border-radius:999px;background:rgba(5,22,28,.72);border:1px solid rgba(129,169,171,.4);font:500 16px/1 ${T.body};letter-spacing:.02em;color:${T.cream};white-space:nowrap;transform-origin:50% 50%}
.b2-receipt-check{width:16px;height:16px;color:${T.mint}}
.b2-tone-gold .b2-receipt-check,.b2-tone-gold .b2-receipt-sep{color:${T.gold}}
.b2-receipt-sep{color:${T.mint};opacity:.9}
.b2-receipt-part{display:inline-block}
.b2-layers{transform-origin:50% 50%}
.b2-scenes{inset:0;overflow:hidden}
.b2-sc-card{position:absolute;inset:0}
.b2-sc-push{position:absolute;inset:0;transform-origin:50% 50%}
.b2-sc-idx{position:absolute;right:96px;top:72px;font:500 16px/1 ${T.mono};letter-spacing:.2em;color:${T.mint}}
.b2-sc-icon{position:absolute;left:160px;top:208px;width:72px;height:72px}
.b2-sc-rule{position:absolute;left:160px;top:312px;width:72px;height:3px;background:${T.coral}}
.b2-sc-title{position:absolute;left:160px;top:342px;font:400 58px/1.05 ${T.title};letter-spacing:-.01em;color:${T.ink}}
.b2-sc-line{position:absolute;left:162px;top:422px;font:400 23px/1.35 ${T.body};color:${T.cream};max-width:760px}
.b2-chat{background:rgba(5,22,28,.62);border:1px solid rgba(129,169,171,.26);border-radius:16px;padding:22px 24px 18px;transform-origin:50% 50%;display:flex;flex-direction:column;gap:14px;box-shadow:0 24px 60px rgba(5,22,28,.4)}
.b2-chat-thread{display:flex;flex-direction:column;gap:12px;min-height:150px;overflow:hidden}
.b2-chat-q{align-self:flex-end;max-width:84%;padding:10px 14px;border-radius:14px 14px 4px 14px;background:rgba(129,169,171,.22);border:1px solid rgba(129,169,171,.35);font:400 18px/1.4 ${T.body};color:${T.ink}}
.b2-chat-dots{display:flex;gap:6px;padding:6px 4px;height:22px;align-items:center}
.b2-chat-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:${T.mint}}
.b2-chat-a{margin:0;font:400 18px/1.5 ${T.body};color:${T.ink}}
.b2-chat-w{display:inline}
.b2-chat-receipt{font:500 16px/1 ${T.mono};letter-spacing:.14em;text-transform:uppercase;color:${T.mint};padding-top:4px}
.b2-chat-composer{display:flex;align-items:center;min-height:46px;padding:0 10px 0 16px;border-radius:12px;background:rgba(233,243,249,.06);border:1px solid rgba(129,169,171,.3);font:400 18px/1.3 ${T.body};color:${T.ink}}
.b2-chat-typed{flex:1 1 auto;white-space:pre-wrap}
.b2-chat-send{width:30px;height:30px;border-radius:8px;background:${T.coral};color:${T.black};display:inline-flex;align-items:center;justify-content:center;transform-origin:50% 50%}
.b2-chat-send svg{width:18px;height:18px}
.b2-acard{background:rgba(5,22,28,.72);border:1px solid rgba(129,169,171,.26);border-radius:14px;padding:22px 24px 20px;transform-origin:50% 50%;display:flex;flex-direction:column;gap:14px;box-shadow:0 24px 60px rgba(5,22,28,.4)}
.b2-acard-title{font:400 26px/1.2 ${T.title};color:${T.ink}}
.b2-acard-caveat{display:flex;gap:10px;align-items:flex-start;font:400 16px/1.4 ${T.body};color:${T.gold}}
.b2-acard-dash{flex:0 0 18px;height:2px;background:${T.gold};margin-top:9px}
.b2-acard-row{display:flex;gap:10px;align-items:center}
.b2-acard-field{flex:1 1 auto;min-height:42px;display:flex;align-items:center;padding:0 14px;border-radius:9px;background:rgba(233,243,249,.06);border:1px solid rgba(129,169,171,.3);font:400 17px/1 ${T.mono};color:${T.ink}}
.b2-acard-btn{padding:0 18px;height:42px;display:inline-flex;align-items:center;border-radius:9px;background:${T.coral};color:${T.black};font:600 15px/1 ${T.body};letter-spacing:.04em;transform-origin:50% 50%}
.b2-chip{align-self:flex-start;padding:7px 12px;border-radius:999px;border:1.5px solid ${T.coral};color:${T.coral};font:500 13px/1 ${T.body};letter-spacing:.04em;transform-origin:0 50%}
.b2-acard-audit{font:400 16px/1 ${T.mono};letter-spacing:.04em;color:${T.mint};min-height:1em}
.b2-flash{inset:0;pointer-events:none}
`;
    const st = document.createElement('style'); st.id = 'b2-styles'; st.textContent = css; document.head.appendChild(st);
  }

  root.BL2 = { countUp, decisionCard, receipt, twoLayers, sceneCards, chatReveal, approvalCard, flash, installStyles,
    N, TOK, ICONS, HARD, humanTimes, keyTimes, machineTimes, fitTimes, arrive, pulse, snap, cutIn, cutOut, exit, draw, tw, fmtNum };
})(typeof window !== 'undefined' ? window : globalThis);
