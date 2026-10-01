/* blocks.js — BL: pure frame(t) block builders for recreated scenes (v4).

   Every block here is a function of the film clock t (absolute seconds) plus an explicit options object.
   Nothing animates on its own: no CSS transitions, no rAF, no wall-clock, no Math.random (a fixed-seed LCG
   only). A scene calls `BL.<block>.build(host, opts)` ONCE (creates the DOM inside `host`, bakes tables, returns
   a state object) and then `BL.<block>.draw(state, t[, win])` from its frame(t) (`win` = {t0, t1, exit, …} overrides merged over the build
   options, so one built block can be re-timed per cue). draw() is idempotent: the same t
   always paints the same pixels, which is what `__seek` / `__step` need. Every block also exposes a pure
   `calc(t, opts[, state])` that returns a plain object (what the harness and QA tools read), and most return
   `sync: [{id, t}]` — named sync points the mix stage can route to SFX.

   The envelope law shared by all blocks (BL.env): a fixed IN, an elastic HOLD that absorbs whatever window the
   host gives, and an OUT only when exit != 'none' (default none: hard cuts are our transitions). When the window
   is shorter than IN + OUT the phases compress proportionally; the timeline is never time-scaled; any hold
   drift is two explicit finite tweens followed by 0.25–0.35 s of authored stillness; sync points sit at fixed
   offsets into IN, never inside the HOLD. Count-ups and typed text read from frame-quantised tables (BL.rows)
   so a seek and a step show the same digit.

   Honesty: blocks are for RECREATED cards, call-outs and openers. Never fake the product UI inside the demo
   act; a block may overlay real footage only where the catalog row says so (references/blocks-catalog.md).
   Measured numbers: references/blocks-catalog.md. Fictional content only ("Acme"). */
(function (root) {
  'use strict';

  /* ============================================================ laws ============================================ */
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rmp = (t, a, b) => (b <= a ? (t >= b ? 1 : 0) : clamp((t - a) / (b - a), 0, 1));
  const lerp = (a, b, x) => a + (b - a) * x;
  const c01 = x => clamp(x, 0, 1);
  /* eases — power3.out by default everywhere ("smooth over bouncy"); back.out only where a row says so */
  const E = {
    lin: x => c01(x),
    p1i: x => c01(x),
    p2i: x => { x = c01(x); return x * x; },
    p3i: x => { x = c01(x); return x * x * x; },
    p4i: x => { x = c01(x); return x * x * x * x; },
    p2o: x => 1 - Math.pow(1 - c01(x), 2),
    p3o: x => 1 - Math.pow(1 - c01(x), 3),
    p4o: x => 1 - Math.pow(1 - c01(x), 4),
    p2io: x => { x = c01(x); return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; },
    p3io: x => { x = c01(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; },
    sineIn: x => 1 - Math.cos(c01(x) * Math.PI / 2),
    sineOut: x => Math.sin(c01(x) * Math.PI / 2),
    sineIO: x => 0.5 - 0.5 * Math.cos(c01(x) * Math.PI),
    expoOut: x => (x >= 1 ? 1 : x <= 0 ? 0 : 1 - Math.pow(2, -10 * x)),
    smooth: x => { x = c01(x); return x * x * (3 - 2 * x); },
    backOut: (s = 1.70158) => x => { x = c01(x) - 1; return 1 + x * x * ((s + 1) * x + s); },
    /* an eased-out curve with a soft first frame (zero velocity at both ends, long tail) */
    softOut: x => { x = c01(x); return E.p3o(x) * E.sineIn(Math.min(1, x / 0.12)); }
  };

  /* BL.env(t, {t0, t1, exit:'none'|'fade'|'up'}, IN, OUT=0.45)
       → {phase:'off'|'in'|'hold'|'out', u, k, lt, IN, OUT, hold, tHold, tOut, exit}
     k  = compression factor (1 unless the window is shorter than IN+OUT); lt = (t - t0) / k is the builder-local
     clock, so schedules authored against the uncompressed IN ("the pulse at 2.1 s") compress with the window. */
  function env(t, win, IN, OUT) {
    const t0 = win.t0 || 0, t1 = (win.t1 == null ? Infinity : win.t1), exit = win.exit || 'none';
    const outBase = exit === 'none' ? 0 : (OUT == null ? 0.45 : OUT);
    const D = t1 - t0; let k = 1;
    if (isFinite(D) && IN + outBase > 0 && D < IN + outBase) k = Math.max(1e-6, D / (IN + outBase));
    const inD = IN * k, outD = outBase * k, hold = isFinite(D) ? Math.max(0, D - inD - outD) : Infinity;
    let phase, u;
    if (t < t0) { phase = 'off'; u = 0; }
    else if (t < t0 + inD) { phase = 'in'; u = inD > 0 ? (t - t0) / inD : 1; }
    else if (t < t1 - outD) { phase = 'hold'; u = isFinite(hold) && hold > 0 ? (t - t0 - inD) / hold : 0; }
    else if (t < t1) { phase = 'out'; u = outD > 0 ? (t - (t1 - outD)) / outD : 1; }
    else { phase = 'off'; u = 1; }
    return { phase, u, k, lt: (t - t0) / k, IN: inD, OUT: outD, hold, tHold: t0 + inD, tOut: t1 - outD, exit, t0, t1 };
  }
  /* exit multiplier for an envelope: {op, y} — 'fade' fades, 'up' fades and lifts 18 px; 'none' holds to the cut */
  function exitOf(e) {
    if (e.phase === 'off') return { op: 0, y: 0 };
    if (e.phase !== 'out' || e.exit === 'none') return { op: 1, y: 0 };
    const u = E.p2i(e.u); return { op: 1 - u, y: e.exit === 'up' ? -18 * u : 0 };
  }

  /* BL.rows(fn, dur, fps=30) → frame-quantised value table; fn(tLocal, u) sampled once per frame.
     at(lt) returns the same value for every t inside a frame, so __seek and __step agree on a digit. */
  function rows(fn, dur, fps) {
    fps = fps || 30; dur = Math.max(0, dur);
    const n = Math.max(1, Math.ceil(dur * fps)), v = new Array(n + 1);
    for (let i = 0; i <= n; i++) v[i] = fn(Math.min(dur, i / fps), n ? i / n : 1);
    v[n] = fn(dur, 1);
    return { n, fps, dur, values: v, at(lt) { if (lt <= 0) return v[0]; if (lt >= dur) return v[n]; return v[Math.min(n, Math.floor(lt * fps + 1e-6))]; } };
  }

  /* BL.driftZero(t, t0, dur, cycles=[2,3], amp=[0.0016,0.0011], still=0.35) → {dx, dy, u}
     micro-drift from INTEGER sine cycles — exactly zero at both ends — over (dur - still), then stillness.
     Fractions of the frame (multiply by 1280 / 720 for px). Only when the hold is ≥ 1.2 s. */
  function driftZero(t, t0, dur, cycles, amp, still) {
    cycles = cycles || [2, 3]; amp = amp || [0.0016, 0.0011]; still = still == null ? 0.35 : still;
    const act = dur - still;
    if (!(dur >= 1.2) || t < t0 || t >= t0 + act) return { dx: 0, dy: 0, u: 0 };
    const u = (t - t0) / act, p = 2 * Math.PI * u;
    return { dx: Math.sin(p * cycles[0]) * amp[0], dy: Math.sin(p * cycles[1]) * amp[1], u };
  }
  /* hold drift as two explicit finite tweens then stillness: 0 → -amt (half 1) → -0.35·amt (half 2) → still */
  function holdDrift(t, t0, dur, amt, still) {
    still = still == null ? 0.35 : still; const act = Math.max(0, dur - still);
    if (!(dur >= 1.2) || t < t0) return 0;
    const h = act / 2, u1 = E.sineIO(rmp(t, t0, t0 + h)), u2 = E.sineIO(rmp(t, t0 + h, t0 + act));
    return -amt * u1 + 0.65 * amt * u2;
  }
  /* sanctioned aliveness: scale amplitude 0.008–0.015, 2–3 px, periods 2.1 / 1.9 / 2.4 s, amp / sqrt(N),
     settle-and-fade over the last 20 % of the hold */
  function jitter(t, o) {
    o = o || {}; const t0 = o.t0 || 0, dur = o.dur == null ? Infinity : o.dur, i = o.i || 0, n = o.n || 1;
    const amp = o.amp == null ? 0.01 : o.amp, P = (o.periods || [2.1, 1.9, 2.4])[i % 3];
    let a = amp / Math.sqrt(Math.max(1, n));
    if (isFinite(dur)) a *= 1 - rmp(t, t0 + dur * 0.8, t0 + dur);
    const s = Math.sin(2 * Math.PI * (t - t0) / P + i * 1.7);
    return { scale: 1 + a * s, dy: 2.5 * (a / 0.01) * s };
  }
  /* fixed-seed LCG (Numerical-Recipes constants) — the only randomness any block may use */
  function lcg(seed) { let s = (seed >>> 0) || 0x9e3779b9; return () => { s = (Math.imul(1664525, s) + 1013904223) >>> 0; return s / 4294967296; }; }
  function pickW(rnd, vals, w) { const tot = w.reduce((a, b) => a + b, 0); let r = rnd() * tot; for (let i = 0; i < vals.length; i++) { r -= w[i]; if (r < 0) return vals[i]; } return vals[vals.length - 1]; }

  /* colours: hex → [r,g,b]; mixColor(a, b, u) → 'rgb(...)'; ink62(fg, bg) = 62 % fg over bg (≥ 4.5:1 label ink) */
  function rgb(h) { h = String(h).trim().replace('#', ''); if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]; const n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  function mixColor(a, b, u) { const A = rgb(a), B = rgb(b); u = c01(u); return 'rgb(' + A.map((v, i) => Math.round(lerp(v, B[i], u))).join(',') + ')'; }
  const ink62 = (fg, bg) => mixColor(bg, fg, 0.62);
  const px = v => v.toFixed(2) + 'px';
  const setOp = (el, v) => { if (el) el.style.opacity = c01(v).toFixed(3); };
  const setTf = (el, s) => { if (el && el.style.transform !== s) el.style.transform = s; };
  const setTxt = (el, s) => { if (el && el.textContent !== s) el.textContent = s; };
  const mk = (tag, cls, parent, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; if (parent) parent.appendChild(e); return e; };
  const fmtNum = (v, dec, locale) => v.toLocaleString(locale || 'en-US', { minimumFractionDigits: dec || 0, maximumFractionDigits: dec || 0 });
  /* default tokens (updated by installStyles) so builders can pick the scene's ink without a per-call option */
  const TOK = { bg: '#082A34', fg: '#E9F3F9', muted: '#81A9AB', accent: '#E56B5E' };
  const collectSync = (...states) => [].concat(...states.map(s => (s && s.sync) || [])).sort((a, b) => a.t - b.t);

  /* ============================================================ kpi ============================================= */
  /* BL.kpi — count-up stat with landing pulse, suffix after the value, bar/ring fill on the count's ease.
     opts: {t0, t1?, land?, value, from=0, dec=0, prefix='', suffix='', token?, label?, fill?:{kind:'bar'|'ring', pct},
            pulse=true, locale='en-US', exit='none', H=720}
     Schedule (builder-local): arrive 0.38 s (op power2.out; y 2.2 % of H and scale 0.98→1 power3.out); count
     from 0.38 s for `count` = land - t0 - 0.38 (min 0.7 s; 1.72 s when no land) on sine.inOut from a 30 fps table;
     landing pulse scale 1.07 over 0.165 s power3.out, back 0.165 s power2.out; suffix slides in (8 px) over 0.25 s
     after the land; label fades 0.15–0.45 s; fill shares the count's ease and duration. `token` (a raw display
     string) is shown verbatim once landed — the number must equal the on-screen product figure (claims.json). */
  const kpi = {
    IN: 0.38, PULSE: 0.165,
    plan(o) {
      const count = o.land != null ? Math.max(0.7, o.land - o.t0 - kpi.IN) : (o.count || 1.72);
      const from = o.from || 0, val = +o.value, dec = o.dec || 0;
      const table = rows((tl, u) => (o.prefix || '') + fmtNum(from + (val - from) * E.sineIO(u), dec, o.locale), count);
      const final = (o.prefix || '') + (o.token != null ? String(o.token) : fmtNum(val, dec, o.locale));
      return { count, table, final, tLand: kpi.IN + count };
    },
    calc(t, o, st) {
      const p = (st && st.plan) || kpi.plan(o);
      const e = env(t, o, kpi.IN + p.count + 2 * kpi.PULSE + 0.25, 0.45), lt = e.lt, x = exitOf(e);
      const aIn = rmp(lt, 0, kpi.IN), H = o.H || 720;
      const op = E.p2o(aIn) * x.op, y = (1 - E.p3o(aIn)) * 0.022 * H + x.y, sIn = 0.98 + 0.02 * E.p3o(aIn);
      const cu = rmp(lt, kpi.IN, p.tLand);
      const text = lt >= p.tLand ? p.final : p.table.at(lt - kpi.IN);
      let pulse = 1;
      if (o.pulse !== false && lt >= p.tLand) pulse = lt < p.tLand + kpi.PULSE ? 1 + 0.07 * E.p3o((lt - p.tLand) / kpi.PULSE) : 1.07 - 0.07 * E.p2o((lt - p.tLand - kpi.PULSE) / kpi.PULSE);
      const su = E.p2o(rmp(lt, p.tLand, p.tLand + 0.25));
      return { phase: e.phase, op, y, scale: sIn * pulse, text, countU: cu, fillU: o.fill ? E.sineIO(cu) * (o.fill.pct == null ? 1 : o.fill.pct) : 0,
        suffixOp: su, suffixX: (1 - su) * 8, labelOp: rmp(lt, 0.15, 0.45), sync: [{ id: 'land', t: o.t0 + p.tLand * e.k }] };
    },
    build(host, o) {
      const plan = kpi.plan(o);
      const root = mk('div', 'bl-kpi', host);
      const label = mk('div', 'bl-kpi-label', root, o.label || '');
      const row = mk('div', 'bl-kpi-row', root);
      const num = mk('span', 'bl-kpi-num', row); num.style.minWidth = plan.final.length + 'ch'; num.style.textAlign = o.align || 'left';
      const suf = mk('span', 'bl-kpi-suffix', row, o.suffix || '');
      let fill = null, ring = null, ringLen = 0;
      if (o.fill && o.fill.kind === 'ring') {
        const svg = mk('div', 'bl-kpi-ring', root, '<svg viewBox="0 0 100 100"><circle class="bl-kpi-ring-track" cx="50" cy="50" r="44"/><circle class="bl-kpi-ring-fill" cx="50" cy="50" r="44"/></svg>');
        ring = svg.querySelector('.bl-kpi-ring-fill'); ringLen = ring.getTotalLength(); ring.style.strokeDasharray = ringLen.toFixed(2);
      } else if (o.fill) { const tr = mk('div', 'bl-kpi-track', root); fill = mk('div', 'bl-kpi-fill', tr); }
      return { o, plan, els: { root, label, num, suf, fill, ring }, ringLen };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = kpi.calc(t, O, st), e = st.els;
      setOp(e.root, s.op); setTf(e.root, 'translateY(' + px(s.y) + ') scale(' + s.scale.toFixed(4) + ')');
      setTxt(e.num, s.text); setOp(e.suf, s.suffixOp); setTf(e.suf, 'translateX(' + px(s.suffixX) + ')'); setOp(e.label, s.labelOp);
      if (e.fill) setTf(e.fill, 'scaleX(' + s.fillU.toFixed(4) + ')');
      if (e.ring) e.ring.style.strokeDashoffset = (st.ringLen * (1 - s.fillU)).toFixed(2);
      return s;
    }
  };
  /* BL.count(from, to, t, t0, dur, dec) — table-backed count for odometers (a drop-in for G.odo); tables are memoised */
  const countCache = new Map();
  function count(from, to, t, t0, dur, dec, locale) {
    dur = dur || 0.7; const key = [from, to, dur, dec || 0, locale || ''].join('|');
    let tb = countCache.get(key); if (!tb) { tb = rows((tl, u) => fmtNum(from + (to - from) * E.sineIO(u), dec, locale), dur); countCache.set(key, tb); }
    return tb.at(t - t0);
  }

  /* ============================================================ typing / chat =================================== */
  /* BL.keystrokes(text, t0, {seed=7, variant='human'|'beat'|'uniform', endAt?}) → {times, tDone, at(t), count(t), caret(t)}
     human: per-key gaps drawn from {33,67,100,133,167,200} ms weighted to the 67–100 ms mode (mean ≈ 90 ms),
     two characters on the first beat; beat: 50 ms/char with 110 ms space holds; uniform: 55 ms/char, 110 ms/word.
     `endAt` compresses proportionally ONLY when the natural schedule would overflow it (else it waits).
     caret(t): blinks on a 0.533 s period while typing, solid after, hidden before t0 - 0.4. */
  const KEY_GAPS = [0.033, 0.067, 0.100, 0.133, 0.167, 0.200], KEY_W = [3, 5, 4, 2, 1, 1];
  function keystrokes(text, t0, o) {
    o = o || {}; const rnd = lcg(o.seed == null ? 7 : o.seed), v = o.variant || 'human', times = []; let t = t0;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (i >= (v === 'human' ? 2 : 1)) t += v === 'beat' ? (ch === ' ' ? 0.110 : 0.050) : v === 'uniform' ? (ch === ' ' ? 0.110 : 0.055) : pickW(rnd, KEY_GAPS, KEY_W);
      times.push(t);
    }
    return retime(text, times, t0, o.endAt);
  }
  function retime(text, times, t0, endAt) {
    let tDone = times.length ? times[times.length - 1] : t0;
    if (endAt != null && tDone > endAt && tDone > t0) { const k = (endAt - t0) / (tDone - t0); for (let i = 0; i < times.length; i++) times[i] = t0 + (times[i] - t0) * k; tDone = endAt; }
    const countAt = t => { let lo = 0, hi = times.length; while (lo < hi) { const m = (lo + hi) >> 1; if (times[m] <= t) lo = m + 1; else hi = m; } return lo; };
    return { times, tDone, t0, count: countAt, at: t => text.slice(0, countAt(t)),
      caret: t => (t < t0 - 0.4 ? false : t < tDone ? Math.floor((t - t0 + 0.4) / (0.533 / 2)) % 2 === 0 : true) };
  }
  /* BL.prompt(text, t0, {cues?:[absolute s per word index or {word, t}], correction?:{word, wrong}, seed, variant='chunk'})
     → {events, tDone, wordStart[], at(t), caret(t)}
     chunk variant: 1–3 characters per chunk, 0.1–0.2 s per word; 'uniform' 55 ms/char + 110 ms/word.
     correction: types `wrong` in place of word N, pauses 0.4 s ("realising"), backspaces at 50 ms/char, retypes.
     cues anchor the START of word N (= wt(phase, word)); the schedule compresses proportionally only when it
     would overflow a cue, otherwise it waits. caret(t): an integer number of sine blink cycles while typing,
     then solid. The typed text must match what the narrator speaks verbatim. */
  function prompt(text, t0, o) {
    o = o || {}; const rnd = lcg(o.seed == null ? 11 : o.seed), words = text.split(' ');
    const ev = [], wordStart = []; let t = t0, shown = '';
    const typeWord = (w, trail) => {
      const full = w + trail;
      if (o.variant === 'uniform') { for (const ch of full) { t += ch === ' ' ? 0.110 : 0.055; shown += ch; ev.push({ t, text: shown }); } return; }
      const dur = 0.1 + 0.1 * rnd(); let i = 0; const chunks = [];
      while (i < full.length) { const n = 1 + Math.floor(rnd() * 3); chunks.push(full.slice(i, i + n)); i += n; }
      chunks.forEach((c, k) => { t += dur / chunks.length; shown += c; ev.push({ t, text: shown }); });
    };
    words.forEach((w, i) => {
      const trail = i < words.length - 1 ? ' ' : '';
      if (o.correction && o.correction.word === i) {
        typeWord(o.correction.wrong, ''); t += 0.4;
        for (let k = 0; k < o.correction.wrong.length; k++) { t += 0.05; shown = shown.slice(0, -1); ev.push({ t, text: shown }); }
      }
      wordStart.push(t); typeWord(w, trail);
    });
    /* anchor word starts to cues: compress the preceding segment on overflow, else shift (wait) */
    const cues = (o.cues || []).map((c, i) => (typeof c === 'number' ? { word: i, t: c } : c)).filter(c => c && c.t != null && c.word < words.length).sort((a, b) => a.word - b.word);
    let anchorT = t0, anchorNat = t0;
    for (const c of cues) {
      const nat = wordStart[c.word]; if (nat <= anchorNat) continue;
      const k = (c.t - anchorT) / (nat - anchorNat), shift = c.t - nat;
      /* compress (k<1): the segment maps linearly onto [anchorT, c.t]; wait (k>=1): everything from `nat` shifts later by `shift` */
      const map = k < 1 ? x => (x <= anchorNat ? x : x < nat ? anchorT + (x - anchorNat) * k : x + shift) : x => (x < nat ? x : x + shift);
      ev.forEach(e => { e.t = map(e.t); }); for (let i = 0; i < wordStart.length; i++) wordStart[i] = map(wordStart[i]);
      anchorT = c.t; anchorNat = c.t;
    }
    const tDone = ev.length ? ev[ev.length - 1].t : t0, typing = Math.max(0.533, tDone - t0);
    const cyc = Math.max(1, Math.round(typing / 0.533)), period = typing / cyc;
    const at = tt => { if (tt < t0) return ''; let lo = 0, hi = ev.length; while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t <= tt) lo = m + 1; else hi = m; } return lo ? ev[lo - 1].text : ''; };
    return { events: ev, tDone, t0, wordStart, at, caret: tt => (tt < t0 - 0.4 ? 0 : tt >= tDone ? 1 : 0.5 + 0.5 * Math.cos(2 * Math.PI * (tt - t0) / period)) };
  }
  /* BL.thinkDot(t, tDot) → alpha: 13 steps of 33 ms from 0.49 to 1.0, gone at +0.567 s */
  const thinkDot = (t, tDot) => (t < tDot || t >= tDot + 0.567 ? 0 : 0.49 + 0.51 * Math.min(12, Math.floor((t - tDot) / 0.033)) / 12);
  /* BL.stream(words, tStart, {endAt?, seed=3, inkDur=0.267, paraGap=0.12}) → {times, tLast, at(t) → ink[] (0..1 per word)}
     words land on uneven gaps 0–367 ms with ~15 % zero-gap bursts, '\n' adds a 0.12 s paragraph gap; each word
     arrives grey and inks to full colour over 0.267 s linearly; `endAt` rescales so the LAST word lands there
     (= wt of the narrator's last answer word). */
  function stream(words, tStart, o) {
    o = o || {}; const rnd = lcg(o.seed == null ? 3 : o.seed), inkDur = o.inkDur == null ? 0.267 : o.inkDur, times = []; let t = tStart;
    words.forEach((w, i) => { if (i) t += (rnd() < 0.15 ? 0 : 0.033 + 0.334 * rnd()) + (w.indexOf('\n') >= 0 ? (o.paraGap == null ? 0.12 : o.paraGap) : 0); times.push(t); });
    let tLast = t;
    if (o.endAt != null && tLast > tStart) {   // never rescale backwards: an endAt before the stream start keeps a 10 % floor
      const k = Math.max(0.1, (o.endAt - tStart) / (tLast - tStart));
      for (let i = 0; i < times.length; i++) times[i] = tStart + (times[i] - tStart) * k; tLast = times[times.length - 1];
    }
    return { times, tLast, tStart, inkDur, at: tt => times.map(ti => rmp(tt, ti, ti + inkDur)) };
  }
  /* BL.bubble(t, at, {dur=0.12, ease=power2.out}) → {scale 0.75→1, op 0.6→1} (message arrival from the sender's corner) */
  const bubble = (t, at, o) => { o = o || {}; const u = (o.ease || E.p2o)(rmp(t, at, at + (o.dur == null ? 0.12 : o.dur))); return { u, scale: 0.75 + 0.25 * u, op: t < at ? 0 : 0.6 + 0.4 * u }; };
  /* BL.dots(t, t0, t1) → {op, scale, dy:[3]}: pop 0.6→1 in 0.1 s, bob -9 px on a 0.28 s sine for 5 finite repeats, gone at t1 */
  function dots(t, t0, t1) {
    if (t < t0 || t >= t1) return { op: 0, scale: 0.6, dy: [0, 0, 0] };
    const pop = E.p2o(rmp(t, t0, t0 + 0.1)), rep = (t - t0) / 0.28;
    return { op: pop, scale: 0.6 + 0.4 * pop, dy: [0, 1, 2].map(i => (rep - i * 0.15 < 5 && rep - i * 0.15 > 0 ? -9 * Math.abs(Math.sin(Math.PI * (rep - i * 0.15))) : 0)) };
  }

  /* BL.chatReveal — typed question → thinking dots → streamed answer → receipt line (recreated scenes ONLY; for
     real footage use footage.js REVEAL + the stream curtain). Neutral shell: no Claude / ChatGPT / iOS trade dress.
     opts: {t0, t1?, question, answer (string | string[] paragraphs), send?, answerEnd?, receipt?, seed=7, variant='human',
            ink=scene fg, grey='#767676'}
     Clock: typing from t0 (BL.keystrokes); send = tDone + 0.167 s (or `send`, compressing only on overflow); the
     question bubble pops 0.167 s power1.out at send; thinking dots appear at send + 0.3 s (alpha ramp BL.thinkDot,
     bob BL.dots) and die the frame the stream starts (+0.633 s); words land per BL.stream, last word at `answerEnd`;
     the receipt line fades in 0.467 s after the last word. sync: send, stream, answer-landed. */
  const chatReveal = {
    plan(o) {
      const ks = keystrokes(o.question, o.t0, { seed: o.seed, variant: o.variant, endAt: o.send != null ? o.send - 0.167 : undefined });
      const send = o.send != null ? Math.max(o.send, ks.tDone + 0.167) : ks.tDone + 0.167;
      const tDot = send + 0.3, tStream = tDot + 0.633;
      const paras = Array.isArray(o.answer) ? o.answer : [o.answer];
      const words = []; paras.forEach((p, i) => p.split(/\s+/).filter(Boolean).forEach((w, j) => words.push((i && !j ? '\n' : '') + w)));
      const sm = stream(words, tStream, { endAt: o.answerEnd, seed: (o.seed || 7) + 1 });
      return { ks, send, tDot, tStream, words, sm, tReceipt: sm.tLast + 0.467 };
    },
    calc(t, o, st) {
      const p = (st && st.plan) || chatReveal.plan(o), e = env(t, o, 0.3, 0.45), x = exitOf(e);
      const typing = t < p.send;
      const qb = bubble(t, p.send, { dur: 0.167, ease: E.lin });
      const d = dots(t, p.tDot, p.tStream), dotA = thinkDot(t, p.tDot);
      return { phase: e.phase, op: x.op, y: x.y,
        composer: { text: typing ? p.ks.at(t) : '', caret: typing && p.ks.caret(t), sendOp: typing ? rmp(t, p.ks.t0, p.ks.t0 + 0.3) : 0 },
        question: { op: qb.op, scale: qb.scale, text: o.question },
        dots: { op: d.op * (dotA || 0), scale: d.scale, dy: d.dy },
        ink: p.sm.at(t), done: t >= p.sm.tLast + p.sm.inkDur,
        receipt: { op: E.p2o(rmp(t, p.tReceipt, p.tReceipt + 0.3)) },
        sync: [{ id: 'send', t: p.send }, { id: 'stream', t: p.tStream }, { id: 'answer-landed', t: p.sm.tLast }] };
    },
    build(host, o) {
      const plan = chatReveal.plan(o);
      const root = mk('div', 'bl-chat', host);
      const thread = mk('div', 'bl-chat-thread', root);
      const q = mk('div', 'bl-chat-q', thread, ''); q.textContent = o.question;
      const a = mk('div', 'bl-chat-a', thread);
      const dotsEl = mk('div', 'bl-chat-dots', a, '<i></i><i></i><i></i>');
      const spans = plan.words.map(w => { if (w[0] === '\n') { mk('br', null, a); w = w.slice(1); } const s = mk('span', 'bl-chat-w', a); s.textContent = w; a.appendChild(document.createTextNode(' ')); return s; });
      const receipt = mk('div', 'bl-chat-receipt', thread); receipt.textContent = o.receipt || '';
      const composer = mk('div', 'bl-chat-composer', root);
      const ctext = mk('span', 'bl-chat-ctext', composer), caret = mk('span', 'bl-chat-caret', composer), send = mk('span', 'bl-chat-send', composer);
      send.setAttribute('aria-hidden', 'true');
      return { o, plan, els: { root, q, a, spans, receipt, dots: dotsEl, dotEls: Array.from(dotsEl.children), composer, ctext, caret, send } };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = chatReveal.calc(t, O, st), e = st.els, ink = O.ink || TOK.fg, grey = O.grey || '#767676';
      setOp(e.root, s.op); setTf(e.root, 'translateY(' + px(s.y) + ')');
      setTxt(e.ctext, s.composer.text); setOp(e.caret, s.composer.caret ? 1 : 0); setOp(e.send, s.composer.sendOp);
      setOp(e.q, s.question.op); setTf(e.q, 'scale(' + s.question.scale.toFixed(4) + ')');
      setOp(e.dots, s.dots.op); e.dotEls.forEach((d, i) => setTf(d, 'translateY(' + px(s.dots.dy[i]) + ') scale(' + s.dots.scale.toFixed(3) + ')'));
      e.spans.forEach((sp, i) => { const u = s.ink[i]; const c = u <= 0 ? 'transparent' : mixColor(grey, ink, u); if (sp.style.color !== c) sp.style.color = c; });
      setOp(e.receipt, s.receipt.op);
      return s;
    }
  };

  /* ============================================================ stack =========================================== */
  /* BL.stack — isometric exploded architecture stack in 2D CSS 3D (no WebGL, no CDN).
     opts: {t0, t1?, layers:[{label, color, glyph?}] bottom→top, unit=56 (px per model unit), open=0.3, stagger=0.06,
            openDur=0.9, land?:[absolute s per layer] | landAt=1.25, landEvery=0.45, close?: absolute s, accent, ink='#8b909a', cx, cy}
     Geometry: plates 4.2 × 4.2 units, 0.22 thick, 0.08 edge radius, gap 1.55 units; view rotateX(55°) rotateZ(-45°)
     (orthographic — no perspective). Plates separate upward from `open` with a 0.06 s stagger on an eased-out
     curve with a soft first frame; the bottom plate never moves, the top travels furthest and leaves first on
     close (0.6 s, 0.05 s stagger). Labels land one per layer with a leader line + dot from the plate's right corner
     (anchor +90 px, text +24 px, translations rounded to whole px); the focused plate's glyph inks grey→accent. */
  const stack = {
    A: 55 * Math.PI / 180, B: -45 * Math.PI / 180,
    /* local plate point (x right, y down, z up) → screen offset from the plate centre (orthographic iso) */
    project(x, y, z) { const cb = Math.cos(stack.B), sb = Math.sin(stack.B), ca = Math.cos(stack.A), sa = Math.sin(stack.A); return [x * cb - y * sb, (x * sb + y * cb) * ca - z * sa]; },
    calc(t, o, st) {
      const n = o.layers.length, u = o.unit || 56, W = 4.2 * u, thick = 0.22 * u, gap = 1.55 * u, open = o.open == null ? 0.3 : o.open, stg = o.stagger == null ? 0.06 : o.stagger;
      const e = env(t, o, open + stg * n + (o.openDur || 0.9), 0.45), lt = e.lt, x = exitOf(e), cx = o.cx == null ? 640 : o.cx, cy = o.cy == null ? 400 : o.cy;
      const closeAt = o.close != null ? (o.close - o.t0) / e.k : Infinity;
      const layers = o.layers.map((L, i) => {
        let lift = E.softOut(rmp(lt, open + i * stg, open + i * stg + (o.openDur || 0.9)));
        if (lt >= closeAt) lift *= 1 - E.p2io(rmp(lt, closeAt + (n - 1 - i) * 0.05, closeAt + (n - 1 - i) * 0.05 + 0.6));
        const z = i * (thick + 2) + i * gap * lift;
        const landT = o.land && o.land[i] != null ? (o.land[i] - o.t0) / e.k : (o.landAt == null ? 1.25 : o.landAt) + i * (o.landEvery == null ? 0.45 : o.landEvery);
        let shown = E.p2o(rmp(lt, landT, landT + 0.4)); if (lt >= closeAt) shown *= 1 - rmp(lt, closeAt, closeAt + 0.3);
        const [ax, ay] = stack.project(W / 2, W / 2, z);
        const sx = cx + ax, sy = cy + ay;
        return { lift, z, shown, labelOp: shown, labelX: Math.round(sx + 90 + 24 + (1 - shown) * 16), labelY: Math.round(sy - 22), landT: o.t0 + landT * e.k,
          leader: { x1: sx, y1: sy, x2: sx + 90 * shown, y2: sy, op: shown }, ink: 0 };
      });
      /* focus = the layer whose label landed most recently */
      let focus = -1; layers.forEach((L, i) => { if (lt >= (L.landT - o.t0) / e.k) focus = i; });
      layers.forEach((L, i) => { L.ink = i === focus ? E.p2o(rmp(lt, (L.landT - o.t0) / e.k, (L.landT - o.t0) / e.k + 0.4)) : (focus > i ? 0.35 : 0); });
      return { phase: e.phase, op: x.op, y: x.y, layers, focus, W, thick, sync: layers.map((L, i) => ({ id: 'label-' + i, t: L.landT })).concat([{ id: 'open', t: o.t0 + open * e.k }]) };
    },
    build(host, o) {
      const u = o.unit || 56, W = 4.2 * u, thick = 0.22 * u, cx = o.cx == null ? 640 : o.cx, cy = o.cy == null ? 400 : o.cy;
      const root = mk('div', 'bl-stack', host);
      const world = mk('div', 'bl-stack-world', root); world.style.left = px(cx); world.style.top = px(cy);
      const plates = o.layers.map((L, i) => {
        const p = mk('div', 'bl-stack-plate', world); p.style.width = p.style.height = px(W); p.style.marginLeft = p.style.marginTop = px(-W / 2); p.style.borderRadius = px(0.08 * u * 2);
        const side = mk('div', 'bl-stack-side', p); side.style.background = mixColor(L.color || '#5b6b7a', '#000000', 0.35); side.style.borderRadius = p.style.borderRadius; side.style.transform = 'translateZ(' + px(-thick) + ')';
        const face = mk('div', 'bl-stack-face', p); face.style.background = L.color || '#5b6b7a'; face.style.borderRadius = p.style.borderRadius;
        const glyph = mk('div', 'bl-stack-glyph', face, L.glyph || ''); glyph.style.color = o.ink || '#8b909a';
        return { p, face, glyph };
      });
      const svg = mk('div', 'bl-stack-leaders', root, '<svg width="1280" height="720" viewBox="0 0 1280 720">' + o.layers.map(() => '<g><line stroke-width="1.5"/><circle r="3.5"/></g>').join('') + '</svg>');
      const gs = Array.from(svg.querySelectorAll('g'));
      const labels = o.layers.map(L => { const d = mk('div', 'bl-stack-label', root); d.textContent = L.label; return d; });
      return { o, els: { root, world, plates, gs, labels }, accent: o.accent || '#E56B5E' };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = stack.calc(t, O, st), e = st.els, acc = st.accent, ink = O.ink || '#8b909a';
      setOp(e.root, s.op); setTf(e.root, 'translateY(' + px(s.y) + ')');
      s.layers.forEach((L, i) => {
        setTf(e.plates[i].p, 'rotateX(55deg) rotateZ(-45deg) translateZ(' + px(L.z) + ')');
        e.plates[i].p.style.zIndex = String(i);
        const c = mixColor(ink, acc, L.ink); if (e.plates[i].glyph.style.color !== c) e.plates[i].glyph.style.color = c;
        const g = e.gs[i], ln = g.firstChild, dot = g.lastChild;
        ln.setAttribute('x1', L.leader.x1.toFixed(1)); ln.setAttribute('y1', L.leader.y1.toFixed(1)); ln.setAttribute('x2', L.leader.x2.toFixed(1)); ln.setAttribute('y2', L.leader.y2.toFixed(1));
        ln.setAttribute('stroke', acc); dot.setAttribute('fill', acc); dot.setAttribute('cx', L.leader.x2.toFixed(1)); dot.setAttribute('cy', L.leader.y2.toFixed(1));
        g.setAttribute('opacity', L.leader.op.toFixed(3));
        setOp(e.labels[i], L.labelOp); setTf(e.labels[i], 'translate(' + L.labelX + 'px,' + L.labelY + 'px)');
      });
      return s;
    }
  };

  /* ============================================================ chart / race ==================================== */
  /* BL.chart — one chart built in reading order inside a 3.3 s IN (rescaled so `land` is the 3.05 s point).
     opts: {t0, t1?, type:'bars'|'line'|'donut'|'progress', data:[n], labels?:[n], emphasize?: i, token?: 'raw display string',
            unit='', dec=0, land?, max?, w=640, h=360, accent, ink, muted}
     Schedule: stage 0–0.5 s (op power2.out, rise 3 % of h), axis 0.15–0.55 s, data build 0.55→2.15 s (each datum
     0.85 s power3.out, staggered in reading order; line by measured getTotalLength dash, area fades after; donut
     sweeps segment by segment; progress scaleX from the left), labels from 0.85 s (0.08 s stagger), callout pops at
     2.35 s and rolls its number 0.7 s to land the EXACT `token` at 3.05 s (raw token, never a re-rounded float).
     sync: callout-landed. Charts are recreated-scene material — a real product chart stays real pixels. */
  const chart = {
    IN: 3.3, LAND: 3.05,
    plan(o) {
      const n = o.data.length, k = o.land != null ? Math.max(0.3, (o.land - o.t0) / chart.LAND) : 1;
      const em = o.emphasize == null ? n - 1 : o.emphasize, val = +o.data[em];
      const token = o.token != null ? String(o.token) : fmtNum(val, o.dec || 0) + (o.unit || '');
      const roll = rows((tl, u) => fmtNum(val * E.p2o(u), o.dec || 0) + (o.unit || ''), 0.7);
      const stagger = n > 1 ? (1.6 - 0.85) / (n - 1) : 0, max = o.max || Math.max(...o.data.map(Number)) * 1.06, total = o.data.reduce((a, b) => a + +b, 0);
      return { k, em, token, roll, stagger, max, total };
    },
    calc(t, o, st) {
      const p = (st && st.plan) || chart.plan(o), lt = (t - o.t0) / p.k, e = env(t, { t0: o.t0, t1: o.t1, exit: o.exit }, chart.IN * p.k, 0.45), x = exitOf(e), h = o.h || 360;
      const n = o.data.length, build = o.data.map((v, i) => E.p3o(rmp(lt, 0.55 + i * p.stagger, 0.55 + i * p.stagger + 0.85)));
      const sweep = E.p2io(rmp(lt, 0.55, 2.15)); let cum = 0;
      const donut = o.data.map(v => { const seg = +v / p.total, vis = clamp((sweep - cum) / seg, 0, 1); cum += seg; return vis; });
      return { phase: e.phase, op: E.p2o(rmp(lt, 0, 0.5)) * x.op, stageY: (1 - E.p3o(rmp(lt, 0, 0.5))) * 0.03 * h + x.y,
        axisU: E.p2o(rmp(lt, 0.15, 0.55)), bars: build.map((u, i) => ({ u, op: 1, v: +o.data[i] / p.max })), donut,
        lineU: E.p3o(rmp(lt, 0.55, 2.15)), areaOp: 0.18 * rmp(lt, 1.9, 2.4),
        labels: o.data.map((v, i) => rmp(lt, 0.85 + i * 0.08, 0.85 + i * 0.08 + 0.35)),
        callout: { op: E.p2o(rmp(lt, 2.35, 2.6)), scale: 0.9 + 0.1 * E.p3o(rmp(lt, 2.35, 2.75)), text: lt >= chart.LAND ? p.token : p.roll.at(lt - 2.35) },
        em: p.em, sync: [{ id: 'callout-landed', t: o.t0 + chart.LAND * p.k }] };
    },
    build(host, o) {
      const plan = chart.plan(o), w = o.w || 640, h = o.h || 360, n = o.data.length, acc = o.accent || '#E56B5E', ink = o.ink || '#E9F3F9', mut = o.muted || '#81A9AB';
      const padL = 24, padB = 40, padT = 24, pw = w - padL - 24, ph = h - padT - padB, base = padT + ph;
      let inner = '';
      if (o.type === 'bars') { const bw = pw / n * 0.62, gap = pw / n; inner = o.data.map((v, i) => '<rect class="bl-bar" x="' + (padL + i * gap + (gap - bw) / 2).toFixed(1) + '" width="' + bw.toFixed(1) + '" y="' + base + '" height="0" rx="3" fill="' + (i === plan.em ? acc : mut) + '"/>').join(''); }
      else if (o.type === 'progress') { const rh = ph / n * 0.5, gap = ph / n; inner = o.data.map((v, i) => '<rect x="' + padL + '" y="' + (padT + i * gap + (gap - rh) / 2).toFixed(1) + '" width="' + pw + '" height="' + rh.toFixed(1) + '" rx="3" fill="' + mut + '" opacity="0.18"/><rect class="bl-bar" x="' + padL + '" y="' + (padT + i * gap + (gap - rh) / 2).toFixed(1) + '" width="0" height="' + rh.toFixed(1) + '" rx="3" fill="' + (i === plan.em ? acc : mut) + '"/>').join(''); }
      else if (o.type === 'line') { const pts = o.data.map((v, i) => [(padL + i * pw / Math.max(1, n - 1)), base - (+v / plan.max) * ph]); const d = 'M' + pts.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L'); inner = '<path class="bl-area" d="' + d + ' L' + pts[n - 1][0].toFixed(1) + ' ' + base + ' L' + pts[0][0].toFixed(1) + ' ' + base + ' Z" fill="' + acc + '" opacity="0"/><path class="bl-line" d="' + d + '" fill="none" stroke="' + acc + '" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>' + pts.map((p, i) => '<circle class="bl-dot" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="' + (i === plan.em ? 6 : 3.5) + '" fill="' + (i === plan.em ? acc : ink) + '" opacity="0"/>').join(''); }
      else if (o.type === 'donut') { const r = Math.min(pw, ph) / 2 - 10, cx = padL + pw / 2, cy = padT + ph / 2, circ = 2 * Math.PI * r; let cum = 0; inner = o.data.map((v, i) => { const seg = +v / plan.total, s = '<circle class="bl-seg" cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + (i === plan.em ? acc : mixColor(mut, '#000', i * 0.12)) + '" stroke-width="' + (r * 0.36).toFixed(1) + '" stroke-dasharray="0 ' + circ.toFixed(2) + '" transform="rotate(' + (-90 + cum * 360).toFixed(2) + ' ' + cx + ' ' + cy + ')" data-seg="' + seg + '" data-circ="' + circ + '"/>'; cum += seg; return s; }).join(''); }
      const labels = (o.labels || []).map((L, i) => { const cxp = o.type === 'progress' ? padL : padL + (i + 0.5) * pw / n; const cyp = o.type === 'progress' ? padT + i * ph / n + 8 : base + 24; return '<text class="bl-lab" x="' + cxp.toFixed(1) + '" y="' + cyp.toFixed(1) + '" fill="' + mut + '" font-size="13" text-anchor="' + (o.type === 'progress' ? 'start' : 'middle') + '" opacity="0">' + L + '</text>'; }).join('');
      const axis = o.type === 'donut' ? '' : '<line class="bl-axis" x1="' + padL + '" y1="' + base + '" x2="' + padL + '" y2="' + base + '" stroke="' + mut + '" stroke-opacity="0.5" stroke-width="1"/>';
      const root = mk('div', 'bl-chart', host, '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' + axis + inner + labels + '</svg><div class="bl-callout"><span></span></div>');
      const svg = root.firstChild, line = svg.querySelector('.bl-line'), len = line ? line.getTotalLength() : 0;
      if (line) line.style.strokeDasharray = len.toFixed(2);
      const callout = root.lastChild; callout.style.background = acc;
      return { o, plan, els: { root, svg, axis: svg.querySelector('.bl-axis'), bars: Array.from(svg.querySelectorAll('.bl-bar')), line, area: svg.querySelector('.bl-area'), dots: Array.from(svg.querySelectorAll('.bl-dot')), segs: Array.from(svg.querySelectorAll('.bl-seg')), labs: Array.from(svg.querySelectorAll('.bl-lab')), callout, calloutTxt: callout.firstChild }, len, geo: { padL, padT, pw, ph, base, w, h } };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = chart.calc(t, O, st), e = st.els, g = st.geo, n = O.data.length;
      setOp(e.root, s.op); setTf(e.root, 'translateY(' + px(s.stageY) + ')');
      if (e.axis) e.axis.setAttribute('x2', (g.padL + g.pw * s.axisU).toFixed(1));
      if (O.type === 'bars') e.bars.forEach((b, i) => { const hh = s.bars[i].v * g.ph * s.bars[i].u; b.setAttribute('height', hh.toFixed(2)); b.setAttribute('y', (g.base - hh).toFixed(2)); });
      if (O.type === 'progress') e.bars.forEach((b, i) => b.setAttribute('width', (g.pw * s.bars[i].v * s.bars[i].u).toFixed(2)));
      if (e.line) { e.line.style.strokeDashoffset = (st.len * (1 - s.lineU)).toFixed(2); e.area.setAttribute('opacity', s.areaOp.toFixed(3)); e.dots.forEach((d, i) => d.setAttribute('opacity', (s.lineU >= (i + 0.5) / n ? 1 : 0).toFixed(0))); }
      e.segs.forEach((c, i) => { const circ = +c.dataset.circ, seg = +c.dataset.seg; c.setAttribute('stroke-dasharray', (circ * seg * s.donut[i]).toFixed(2) + ' ' + circ.toFixed(2)); });
      e.labs.forEach((l, i) => l.setAttribute('opacity', (s.labels[i] || 0).toFixed(3)));
      setOp(e.callout, s.callout.op); setTf(e.callout, 'scale(' + s.callout.scale.toFixed(4) + ')'); setTxt(e.calloutTxt, s.callout.text);
      return s;
    }
  };

  /* BL.race — bar chart race solved from baked ranks so two bars can never cross without swapping.
     opts: {t0, periods:[labels], series:[{name, values:[per period], color?}], barCount=6, periodDur=2, prefix='', suffix='', dec=0,
            accent, bar='#81A9AB', w=640, h=360}
     10 interpolated keyframes per period; integer ranks baked per keyframe; a bar's row is solved FROM rank and a
     swap plays over one keyframe interval (periodDur / 10); the axis domain stays continuous with 6 % headroom
     (ticks glide); the overtaking bar is painted in front; the accent has exactly one binary meaning — this bar
     currently leads — as a flat fill, never a gradient. Method after the HyperFrames registry (Apache-2.0, see NOTICE.md). */
  const race = {
    K: 10,
    niceStep(x) { const e = Math.pow(10, Math.floor(Math.log10(x))), f = x / e; return e * (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10); },
    plan(o) {
      const T = o.periods.length, N = o.series.length, PD = o.periodDur || 2, K = race.K, kfDur = PD / K, kfCount = T > 1 ? (T - 1) * K + 1 : 1;
      const valueAt = (tl, j) => { const v = o.series[j].values; if (T < 2) return +v[0]; const u = tl / PD, i = clamp(Math.floor(u), 0, T - 2), f = clamp(u - i, 0, 1); return +v[i] + (+v[i + 1] - +v[i]) * f; };
      const ranks = [];
      for (let m = 0; m < kfCount; m++) { const tm = m * kfDur, ord = o.series.map((s, j) => ({ j, v: valueAt(tm, j) })).sort((a, b) => b.v - a.v || a.j - b.j); const row = new Array(N); ord.forEach((x, r) => { row[x.j] = r; }); ranks.push(row); }
      const rankPos = (tl, j) => { if (kfCount < 2) return ranks[0][j]; const m = tl / kfDur, m0 = clamp(Math.floor(m), 0, kfCount - 2), e = E.smooth(clamp(m - m0, 0, 1)); return ranks[m0][j] + (ranks[m0 + 1][j] - ranks[m0][j]) * e; };
      return { T, N, PD, kfDur, kfCount, valueAt, ranks, rankPos, seconds: T > 1 ? (T - 1) * PD : 0 };
    },
    calc(t, o, st) {
      const p = (st && st.plan) || race.plan(o), tl = clamp(t - o.t0, 0, p.seconds), bc = o.barCount || 6, inOp = E.p2o(rmp(t, o.t0, o.t0 + 0.5));
      const vals = o.series.map((s, j) => p.valueAt(tl, j)); let lead = 0; vals.forEach((v, j) => { if (v > vals[lead]) lead = j; });
      const scaleMax = Math.max(1e-9, Math.max(...vals) * 1.06), step = race.niceStep(scaleMax / 4), ticks = [];
      for (let v = 0; v <= scaleMax + 1e-9 && ticks.length < 12; v += step) ticks.push({ v, x: v / scaleMax, text: (o.prefix || '') + fmtNum(v, o.dec || 0) + (o.suffix || '') });
      const rowsOut = o.series.map((s, j) => { const pos = p.rankPos(tl, j); return { j, name: s.name, pos, w: vals[j] / scaleMax, value: vals[j], text: (o.prefix || '') + fmtNum(vals[j], o.dec || 0) + (o.suffix || ''), lead: j === lead, op: clamp(bc - pos, 0, 1) * inOp, z: j === lead ? 100 : Math.round(50 - pos) }; });
      return { op: inOp, rows: rowsOut, ticks, period: o.periods[clamp(Math.round(tl / p.PD), 0, p.T - 1)], lead, tl, done: tl >= p.seconds, sync: o.periods.map((P, i) => ({ id: 'period-' + i, t: o.t0 + i * p.PD })) };
    },
    build(host, o) {
      const plan = race.plan(o), w = o.w || 640, h = o.h || 360, bc = o.barCount || 6, nameW = 120, trackW = w - nameW - 90, pitch = (h - 40) / bc, barH = Math.max(12, pitch * 0.62);
      const root = mk('div', 'bl-race', host); root.style.width = px(w); root.style.height = px(h);
      const axis = mk('div', 'bl-race-axis', root); axis.style.left = px(nameW);
      const ticks = Array.from({ length: 12 }, () => { const tk = mk('div', 'bl-race-tick', axis); mk('span', null, tk); return tk; });
      const period = mk('div', 'bl-race-period', root);
      const rowEls = o.series.map(s => { const r = mk('div', 'bl-race-row', root); r.style.height = px(barH); const name = mk('span', 'bl-race-name', r); name.textContent = s.name; name.style.width = px(nameW - 12); const bar = mk('div', 'bl-race-bar', r); bar.style.left = px(nameW); const val = mk('span', 'bl-race-val', r); return { r, bar, val }; });
      return { o, plan, els: { root, ticks, period, rows: rowEls }, geo: { nameW, trackW, pitch, barH } };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = race.calc(t, O, st), e = st.els, g = st.geo, acc = O.accent || '#E56B5E', bar = O.bar || '#81A9AB';
      setOp(e.root, s.op); setTxt(e.period, s.period);
      e.ticks.forEach((tk, i) => { const T = s.ticks[i]; if (!T) { setOp(tk, 0); return; } setOp(tk, 1); setTf(tk, 'translateX(' + px(T.x * g.trackW) + ')'); setTxt(tk.firstChild, T.text); });
      s.rows.forEach((R, j) => { const el = e.rows[j]; setTf(el.r, 'translateY(' + px(20 + R.pos * g.pitch + (g.pitch - g.barH) / 2) + ')'); setOp(el.r, R.op); el.r.style.zIndex = String(R.z);
        const wpx = R.w * g.trackW; el.bar.style.width = px(wpx); const c = R.lead ? acc : bar; if (el.bar.style.background !== c) el.bar.style.background = c; setTxt(el.val, R.text); el.val.style.left = px(g.nameW + wpx + 8); });
      return s;
    }
  };

  /* ============================================================ frames / swaps ================================== */
  /* BL.deviceFrame — token-drawn browser / window / phone chrome around a screen slot (hairline border, muted dots,
     an address pill or title bar, a phone notch; no traffic-light colours, no branding). For RECREATED UIs, cropped
     comparison stills and labelled roadmap screens only — never around real footage that already shows its own
     full screen. opts: {t0, t1?, chrome:'browser'|'window'|'phone', title='', w, h, exit='none', H=720}
     Settle 0.9 s: rise 4.5 % of H, scale 0.965→1 power3.out, opacity over 0.66 × IN power2.out; hold drift -0.5 % of
     H as two explicit tweens then 0.35 s stillness (only when the hold ≥ 1.2 s). state.screen is the slot element. */
  const deviceFrame = {
    IN: 0.9,
    calc(t, o) {
      const e = env(t, o, deviceFrame.IN, 0.45), lt = e.lt, x = exitOf(e), H = o.H || 720, u = rmp(lt, 0, deviceFrame.IN);
      const drift = e.phase === 'hold' || e.phase === 'out' ? holdDrift(t, e.tHold, isFinite(e.hold) ? e.hold : 0, 0.005 * H) : 0;
      return { phase: e.phase, op: E.p2o(rmp(lt, 0, 0.66 * deviceFrame.IN)) * x.op, y: (1 - E.p3o(u)) * 0.045 * H + drift + x.y, scale: 0.965 + 0.035 * E.p3o(u), sync: [{ id: 'settled', t: o.t0 + deviceFrame.IN * e.k }] };
    },
    build(host, o) {
      const kind = o.chrome || 'browser', root = mk('div', 'bl-frame bl-frame-' + kind, host);
      if (o.w) root.style.width = px(o.w); if (o.h) root.style.height = px(o.h);
      let bar = null;
      if (kind === 'browser') { bar = mk('div', 'bl-frame-bar', root, '<i></i><i></i><i></i><span class="bl-frame-pill"></span>'); bar.lastChild.textContent = o.title || ''; }
      else if (kind === 'window') { bar = mk('div', 'bl-frame-bar', root, '<i></i><i></i><i></i><span class="bl-frame-title"></span>'); bar.lastChild.textContent = o.title || ''; }
      else { bar = mk('div', 'bl-frame-notch', root); }
      const screen = mk('div', 'bl-frame-screen', root);
      return { o, els: { root, bar, screen }, screen };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o; const s = deviceFrame.calc(t, O); setOp(st.els.root, s.op); setTf(st.els.root, 'translateY(' + px(s.y) + ') scale(' + s.scale.toFixed(4) + ')'); return s; }
  };
  /* BL.screenSwap(t, {at, dur=0.55, H=720}) → {aOp, bOp, bY}: fade-through — A empties completely (power1.in, first half)
     before B rises 1.6 % of H (power2.out, second half); no frame shows two screens at partial opacity. */
  function screenSwap(t, o) {
    const d = o.dur == null ? 0.55 : o.dur, h = d / 2, H = o.H || 720;
    if (t < o.at) return { aOp: 1, bOp: 0, bY: 0.016 * H, u: 0 };
    const u1 = E.p1i(rmp(t, o.at, o.at + h)), u2 = E.p2o(rmp(t, o.at + h, o.at + d));
    return { aOp: 1 - u1, bOp: t < o.at + h ? 0 : u2, bY: (1 - u2) * 0.016 * H, u: rmp(t, o.at, o.at + d), sync: [{ id: 'swap', t: o.at + h }] };
  }
  screenSwap.apply = (elA, elB, s) => { setOp(elA, s.aOp); setOp(elB, s.bOp); setTf(elB, 'translateY(' + px(s.bY) + ')'); };
  /* BL.beforeAfter(t, {at, dur=1.05, rest=0.5}) → {split, dividerOp, clip}: the before panel is the base; the after
     panel wipes in from the left over 1.05 s power3.out to rest at `rest`; the divider is hidden until the wipe
     starts. Apply `clip` as clip-path on the after layer. Both stills must share one crop. sync: wipe-land. */
  function beforeAfter(t, o) {
    const d = o.dur == null ? 1.05 : o.dur, rest = o.rest == null ? 0.5 : o.rest, split = rest * E.p3o(rmp(t, o.at, o.at + d));
    return { split, dividerOp: t >= o.at ? 1 : 0, clip: 'inset(0 ' + ((1 - split) * 100).toFixed(3) + '% 0 0)', sync: [{ id: 'wipe-land', t: o.at + d }] };
  }
  /* BL.screenRail(t, {t0, screens, cues:[absolute s per advance], pitch=520, throwDur=0.6, captions?}) → {idx, screens:[{x, scale, op, active}], captionIndex}
     2–5 screens on a rail: neighbours smaller (0.86) and dimmer (0.55); each advance is a velocity-matched throw
     (power4.in half → power4.out half, peak speed at the midpoint) with a long-tail catch; the last throw lands
     with stillness before the cut. For roadmap beats label the rail 'roadmap'. */
  function screenRail(t, o) {
    const pitch = o.pitch || 520, d = o.throwDur || 0.6, cues = o.cues || [];
    let idx = 0; cues.forEach(c => { const u = rmp(t, c, c + d); idx += u < 0.5 ? 0.5 * E.p4i(2 * u) : 0.5 + 0.5 * E.p4o(2 * u - 1); });
    const screens = Array.from({ length: o.screens }, (_, i) => { const dd = i - idx, a = Math.min(1, Math.abs(dd)); return { x: dd * pitch, scale: 1 - 0.14 * a, op: 1 - 0.45 * a, active: a < 0.5 }; });
    return { idx, screens, captionIndex: Math.round(idx), sync: cues.map((c, i) => ({ id: 'throw-' + i, t: c + d / 2 })) };
  }

  /* ============================================================ code ============================================ */
  /* BL.codeType(t, {t0, text, msPerChar=28, glyphFade=0.12}) → {count, ops[], caretCol, caretRow, done}
     per-character reveal at 28 ms/char with a 0.12 s opacity fade per glyph (whitespace instant); the caret glides
     linearly to each glyph's right edge (monospace: col × 1ch). Recreated or clearly-synthetic code only. */
  function codeType(t, o) {
    const dt = (o.msPerChar == null ? 28 : o.msPerChar) / 1000, fade = o.glyphFade == null ? 0.12 : o.glyphFade, text = o.text;
    let k = 0, row = 0, col = 0, caretCol = 0, caretRow = 0, prevT = o.t0; const ops = new Array(text.length), times = new Array(text.length);
    for (let i = 0; i < text.length; i++) { const ws = /\s/.test(text[i]); times[i] = i ? prevT + (ws ? 0 : dt) : o.t0; prevT = times[i]; }
    for (let i = 0; i < text.length; i++) {
      const ws = /\s/.test(text[i]); ops[i] = t < times[i] ? 0 : ws ? 1 : rmp(t, times[i], times[i] + fade);
      if (t >= times[i]) { k = i + 1; if (text[i] === '\n') { row++; col = 0; } else col++; caretCol = col; caretRow = row; }
    }
    /* caret glide: linear from the last revealed glyph's right edge to the next glyph's right edge (the glyph fades in beneath it) */
    if (k > 0 && k < text.length && text[k] !== '\n' && !/\s/.test(text[k])) caretCol += clamp((t - times[k - 1]) / Math.max(1e-6, times[k] - times[k - 1]), 0, 1);
    return { count: k, ops, caretCol, caretRow, done: k >= text.length, tDone: times[text.length - 1] || o.t0 };
  }
  /* BL.sweep(t, {at, dur=0.9, lineW, dim=0.45}) → {bandW, othersOp}: a band grows 0 → lineW + 18 px over 0.9 s power2.inOut
     while every other line dims to 0.45. Overlay only — the pixels beneath stay untouched. */
  const sweep = (t, o) => { const u = E.p2io(rmp(t, o.at, o.at + (o.dur == null ? 0.9 : o.dur))); return { bandW: u * ((o.lineW || 0) + 18), othersOp: 1 - (1 - (o.dim == null ? 0.45 : o.dim)) * u, u }; };
  /* BL.diff(t, {at, lines:[{kind:'same'|'removed'|'added'}], lineH=46}) → lines:[{h, op}]: removed collapse 46→0 over 0.55 s
     power2.inOut, wait 0.15 s, added expand 0→46 over 0.6 s power2.out. */
  function diff(t, o) {
    const H = o.lineH || 46, tr = o.at, ta = o.at + 0.55 + 0.15;
    return { lines: o.lines.map(L => { if (L.kind === 'removed') { const u = E.p2io(rmp(t, tr, tr + 0.55)); return { h: H * (1 - u), op: 1 - u }; } if (L.kind === 'added') { const u = E.p2o(rmp(t, ta, ta + 0.6)); return { h: H * u, op: u }; } return { h: H, op: 1 }; }), sync: [{ id: 'diff-added', t: ta + 0.6 }] };
  }
  /* BL.scrollTo(t, {at, fromY, toY, dur=1.7, dim=0.35}) → {y, othersOp, boxOp}: scroll 1.7 s power2.inOut to centre the
     target line, others dim to 0.35 over 0.5 s, the box fades in 0.45 s starting 0.35 s before arrival. */
  function scrollTo(t, o) {
    const d = o.dur == null ? 1.7 : o.dur, u = E.p2io(rmp(t, o.at, o.at + d));
    return { y: lerp(o.fromY || 0, o.toY, u), othersOp: 1 - (1 - (o.dim == null ? 0.35 : o.dim)) * rmp(t, o.at, o.at + 0.5), boxOp: rmp(t, o.at + d - 0.35, o.at + d + 0.1), u };
  }
  /* BL.code — an editor card for recreated code: build(host, {lines:[string], lineH=24}) then draw(state, t, {t0, type:'typing'|'sweep'|'diff'|'scroll', ...})
     editor fades 0.45 s and settles scale 0.985→1 over 0.5 s power2.out. */
  const code = {
    build(host, o) {
      const root = mk('div', 'bl-code', host), lh = o.lineH || 24; root.style.setProperty('--bl-lh', lh + 'px');
      const band = mk('div', 'bl-code-band', root), box = mk('div', 'bl-code-box', root);
      const lines = (o.lines || []).map((L, i) => { const d = mk('div', 'bl-code-line', root); d.style.height = px(lh); const n = mk('span', 'bl-code-n', d); n.textContent = String(i + 1); const c = mk('span', 'bl-code-c', d); c.textContent = L; return { d, c, text: L }; });
      const caret = mk('span', 'bl-code-caret', root);
      return { o, els: { root, band, box, lines, caret }, lh };
    },
    draw(st, t, o) {
      const e = st.els, lh = st.lh, lt = t - o.t0, settle = E.p2o(rmp(lt, 0, 0.5));
      setOp(e.root, rmp(lt, 0, 0.45)); setTf(e.root, 'scale(' + (0.985 + 0.015 * settle).toFixed(4) + ')');
      let s = { type: o.type };
      if (o.type === 'typing') {
        const text = st.o.lines.join('\n'), ct = codeType(t, { t0: o.at == null ? o.t0 + 0.45 : o.at, text, msPerChar: o.msPerChar }); let k = 0;
        e.lines.forEach((L, i) => { const n = L.text.length; let html = ''; for (let j = 0; j < n; j++) { const ch = L.text[j]; html += '<span style="opacity:' + ct.ops[k + j].toFixed(2) + '">' + (ch === '<' ? '&lt;' : ch === '&' ? '&amp;' : ch) + '</span>'; } k += n + 1; if (L.c.dataset.k !== html.length + ':' + ct.count) { L.c.innerHTML = html; L.c.dataset.k = html.length + ':' + ct.count; } });
        setTf(e.caret, 'translate(calc(' + ct.caretCol + 'ch + 56px),' + px(ct.caretRow * lh + 10) + ')'); setOp(e.caret, ct.done ? 1 : 1); s = Object.assign(s, ct);
      } else if (o.type === 'sweep') {
        const sw = sweep(t, { at: o.at, lineW: (e.lines[o.line] ? e.lines[o.line].text.length : 0) * 8.4, dim: o.dim });
        e.lines.forEach((L, i) => setOp(L.d, i === o.line ? 1 : sw.othersOp)); e.band.style.width = px(sw.bandW); e.band.style.top = px(o.line * lh + 10); setOp(e.band, sw.u > 0 ? 1 : 0); setOp(e.caret, 0); s = Object.assign(s, sw);
      } else if (o.type === 'diff') {
        const df = diff(t, { at: o.at, lines: e.lines.map((L, i) => ({ kind: (o.removed || []).indexOf(i) >= 0 ? 'removed' : (o.added || []).indexOf(i) >= 0 ? 'added' : 'same' })), lineH: lh });
        e.lines.forEach((L, i) => { L.d.style.height = px(df.lines[i].h); setOp(L.d, df.lines[i].op); }); setOp(e.caret, 0); s = Object.assign(s, df);
      } else if (o.type === 'scroll') {
        const sc = scrollTo(t, { at: o.at, fromY: (o.fromLine || 0) * lh, toY: Math.max(0, o.line * lh - (o.viewH || 240) / 2 + lh / 2), dim: o.dim });
        e.lines.forEach((L, i) => { setTf(L.d, 'translateY(' + px(-sc.y) + ')'); setOp(L.d, i === o.line ? 1 : sc.othersOp); }); e.box.style.top = px(o.line * lh - sc.y + 10); setOp(e.box, sc.boxOp); setOp(e.caret, 0); s = Object.assign(s, sc);
      }
      return s;
    }
  };

  /* ============================================================ working-state theatre =========================== */
  /* BL.stateRail — mono status chips that cascade in, then SNAP through a data-state machine on cues (exact in both
     seek directions). opts: {t0, t1, states:[labels], times?:[absolute s per advance], enter=0.3, gap=0.05, badges?:[labels], badgeState=1}
     Chips enter 0.2–0.45 s apart by 0.02–0.08 s gaps (power3.out); advances are instantaneous: active = ink on surface,
     done dims by colour-mix (never opacity), pending hollow — presentation is CSS on [data-state]; badges pop (0.25 s
     power3.out, 0.08 s stagger) beside `badgeState` keeping their layout slot at scale 0 so the rail never reflows.
     Default cues spread evenly from the cascade end to ~1 s before the window closes. Keep elapsed-time chips honest. */
  const stateRail = {
    times(o) {
      if (o.times) return o.times; const n = o.states.length, enter = o.enter == null ? 0.3 : o.enter, gap = o.gap == null ? 0.05 : o.gap;
      const a = o.t0 + enter + gap * n + 0.2, b = (o.t1 == null ? o.t0 + 6 : o.t1) - 1.0, m = Math.max(0, n - 1);
      return Array.from({ length: m }, (_, i) => a + (b - a) * (i + 1) / Math.max(1, m));
    },
    calc(t, o) {
      const enter = o.enter == null ? 0.3 : o.enter, gap = o.gap == null ? 0.05 : o.gap, times = stateRail.times(o);
      let active = 0; times.forEach(x => { if (t >= x) active++; }); active = Math.min(active, o.states.length - 1);
      const chips = o.states.map((s, i) => ({ label: s, state: t < o.t0 ? 'pending' : i < active ? 'done' : i === active ? 'active' : 'pending', enterU: E.p3o(rmp(t, o.t0 + i * gap, o.t0 + i * gap + enter)) }));
      const bs = o.badgeState == null ? 1 : o.badgeState, tb = bs === 0 ? o.t0 + enter : times[bs - 1];
      const badges = (o.badges || []).map((b, i) => { const u = tb == null ? 0 : E.p3o(rmp(t, tb + i * 0.08, tb + i * 0.08 + 0.25)); return { label: b, scale: u, op: u }; });
      return { chips, badges, active, times, sync: times.map((x, i) => ({ id: 'state-' + (i + 1), t: x })) };
    },
    build(host, o) {
      const root = mk('div', 'bl-rail', host), bs = o.badgeState == null ? 1 : o.badgeState;
      const chips = [], badges = [];
      o.states.forEach((s, i) => { const c = mk('div', 'bl-chip', root, '<i></i><span></span>'); c.lastChild.textContent = s; c.dataset.state = 'pending'; chips.push(c);
        if (i === bs) (o.badges || []).forEach(b => { const d = mk('div', 'bl-badge', root); d.textContent = b; badges.push(d); }); });
      return { o, els: { root, chips, badges } };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = stateRail.calc(t, O), e = st.els;
      s.chips.forEach((c, i) => { const el = e.chips[i]; if (el.dataset.state !== c.state) el.dataset.state = c.state; setOp(el, c.enterU); setTf(el, 'translateY(' + px((1 - c.enterU) * 8) + ')'); });
      s.badges.forEach((b, i) => { setTf(e.badges[i], 'scale(' + b.scale.toFixed(3) + ')'); setOp(e.badges[i], b.op); });
      return s;
    }
  };
  /* BL.hud — quiet telemetry readouts in four corner brackets. opts: {t0, t1?, readouts:[{label, value, accent?}], cues?:[absolute s], standIns=false, seed=5}
     brackets draw from 0.12 s over 0.5 s; readout i ticks at 1.0 + 0.28·i s (0.5 s each, resolving left to right in 8
     steps); one readout in accent; then dead still. Unresolved glyphs show '·' unless standIns:true (same-class
     stand-ins) — never on a readout the narration quotes as a figure (claims gate). sync: readouts-settled. */
  const hud = {
    plan(o) {
      const rnd = lcg(o.seed == null ? 5 : o.seed), D = '0123456789', U = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', L = 'abcdefghijklmnopqrstuvwxyz';
      const sub = ch => (!o.standIns ? (/\s/.test(ch) ? ch : '·') : D.indexOf(ch) >= 0 ? D[Math.floor(rnd() * 10)] : U.indexOf(ch) >= 0 ? U[Math.floor(rnd() * 26)] : L.indexOf(ch) >= 0 ? L[Math.floor(rnd() * 26)] : ch);
      const tables = o.readouts.map((r, i) => { const cue = (o.cues && o.cues[i] != null ? o.cues[i] - o.t0 : 1.0 + 0.28 * i), chars = Array.from(String(r.value)), steps = []; for (let s = 1; s <= 8; s++) { const res = s === 8 ? chars.length : Math.floor(chars.length * s / 8); steps.push({ t: cue + 0.5 * s / 8, x: chars.map((c, k) => (k < res ? c : sub(c))).join('') }); } return { cue, steps, final: String(r.value) }; });
      return { tables, settled: Math.max(...tables.map(x => x.cue + 0.5)) };
    },
    calc(t, o, st) {
      const p = (st && st.plan) || hud.plan(o), lt = t - o.t0, e = env(t, o, 1.0, 0.45), x = exitOf(e);
      return { phase: e.phase, op: rmp(lt, 0, 0.45) * x.op, bracketU: E.p3o(rmp(lt, 0.12, 0.62)),
        readouts: p.tables.map((tb, i) => { let text = '––'; for (const s of tb.steps) if (lt >= s.t) text = s.x; return { label: o.readouts[i].label, text, op: rmp(lt, 0.45 + 0.08 * i, 0.75 + 0.08 * i), accent: !!o.readouts[i].accent }; }),
        settled: lt >= p.settled, sync: [{ id: 'readouts-settled', t: o.t0 + p.settled }] };
    },
    build(host, o) {
      const plan = hud.plan(o), root = mk('div', 'bl-hud', host);
      const brackets = ['tl', 'tr', 'bl', 'br'].map(k => { const b = mk('div', 'bl-hud-br bl-hud-' + k, root, '<svg viewBox="0 0 48 48"><path d="M2 46 V2 H46" fill="none" stroke-width="2"/></svg>'); const p = b.firstChild.firstChild, len = p.getTotalLength(); p.style.strokeDasharray = len.toFixed(2); return { b, p, len }; });
      const reads = o.readouts.map((r, i) => { const d = mk('div', 'bl-hud-read bl-hud-' + ['tl', 'tr', 'bl', 'br'][i % 4] + (r.accent ? ' bl-hud-em' : ''), root, '<span class="bl-hud-l"></span><span class="bl-hud-v"></span>'); d.firstChild.textContent = r.label; return d; });
      return { o, plan, els: { root, brackets, reads } };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = hud.calc(t, O, st), e = st.els; setOp(e.root, s.op);
      e.brackets.forEach(b => { b.p.style.strokeDashoffset = (b.len * (1 - s.bracketU)).toFixed(2); });
      s.readouts.forEach((r, i) => { setOp(e.reads[i], r.op); setTxt(e.reads[i].lastChild, r.text); });
      return s;
    }
  };
  /* BL.agentTag — an agent cursor with a typed step label, click rings, a breathing live dot that becomes a check.
     opts: {t0, steps:[labels], targets:[[x,y]], start=[x,y], perTarget=1.35, typeMs=22, done?: absolute s}
     each step: label types at 22 ms/char (≤ 0.3 s), then a 1.0 s power3.out arc move (bend 0.12) to its target;
     ring at arrival; the live dot breathes on a 1.2 s period until `done`, when a check pops back.out(2.4) over
     0.3 s and every pulse dies on that frame. Synthetic cursors over real footage only at recorded click positions. */
  const agentTag = {
    calc(t, o) {
      const per = o.perTarget || 1.35, typeS = 0.35, start = o.start || [640, 360], n = o.steps.length;
      let x = start[0], y = start[1], label = '', ringAt = -1, i = Math.min(n - 1, Math.floor(Math.max(0, t - o.t0) / per));
      if (t >= o.t0) {
        const ts = o.t0 + i * per, lab = o.steps[i], tl = Math.min(0.3, lab.length * (o.typeMs || 22) / 1000);
        label = lab.slice(0, Math.floor(lab.length * rmp(t, ts, ts + tl)));
        const from = i ? o.targets[i - 1] : start, to = o.targets[i], u = E.p3o(rmp(t, ts + typeS, ts + per)), p = cursorArc(from, to, u, 0.12); x = p[0]; y = p[1];
        for (let j = 0; j <= i; j++) if (t >= o.t0 + j * per + per) ringAt = o.t0 + j * per + per; if (t >= ts + per) ringAt = ts + per;
      }
      const done = o.done != null && t >= o.done, ring = clickRing(t, ringAt);
      const breathe = done || t < o.t0 ? 1 : 1 + 0.15 * Math.sin(2 * Math.PI * (t - o.t0) / 1.2);
      return { x, y, label, step: i, dotScale: done ? 0 : breathe, checkU: done ? E.backOut(2.4)(rmp(t, o.done, o.done + 0.3)) : 0, ring, sync: o.targets.map((T, j) => ({ id: 'agent-click-' + j, t: o.t0 + j * per + per })) };
    },
    build(host, o) { const root = mk('div', 'bl-agent', host, '<div class="bl-agent-arrow"></div><div class="bl-agent-tag"><i class="bl-agent-dot"></i><b class="bl-agent-check">✓</b><span></span></div><div class="bl-agent-ring"></div>'); return { o, els: { root, tag: root.children[1], dot: root.children[1].children[0], check: root.children[1].children[1], label: root.children[1].children[2], ring: root.children[2] } }; },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o;
      const s = agentTag.calc(t, O), e = st.els; setOp(e.root, t >= O.t0 ? 1 : 0); setTf(e.root, 'translate(' + px(s.x) + ',' + px(s.y) + ')');
      setTxt(e.label, s.label); setTf(e.dot, 'scale(' + s.dotScale.toFixed(3) + ')'); setTf(e.check, 'scale(' + s.checkU.toFixed(3) + ')');
      setOp(e.ring, s.ring.op); e.ring.style.width = e.ring.style.height = px(2 * s.ring.r); setTf(e.ring, 'translate(' + px(-s.ring.r) + ',' + px(-s.ring.r) + ')');
      return s;
    }
  };

  /* ============================================================ flash / freeze / rec =========================== */
  /* BL.flash(t, tHit) → {active, washOp, coreScale, coreOp, coreRot, sweepX, sweepOp}: the editorial camera-flash — a
     wash (255,253,250) to 0.92 in 0.04 s power4.in then clear 0.18 s power3.out; a radial core popping 0.86→1 at -5°
     in 0.05 s then blowing out to 1.18 fading over 0.34 s power2.out; a 108° sweep band -12 → 8 % in 0.04 s then to
     28 % over 0.3 s. Total ≤ 0.4 s, layers inset -12 %, screen blend. Allowed card→footage or on the trust beat, max
     one per act; register the hit as a `seam` and keep scripted cuts ≥ 0.5 s away (gate 6). */
  function flash(t, tHit) {
    const d = t - tHit; if (d < 0 || d >= 0.4 - 1e-9) return { active: false, washOp: 0, coreScale: 0.86, coreOp: 0, coreRot: -5, sweepX: -12, sweepOp: 0 };
    const washOp = d < 0.04 ? 0.92 * E.p4i(d / 0.04) : 0.92 * (1 - E.p3o((d - 0.04) / 0.18));
    const coreScale = d < 0.05 ? lerp(0.86, 1, d / 0.05) : lerp(1, 1.18, E.p2o((d - 0.05) / 0.34)), coreOp = d < 0.05 ? 1 : 1 - E.p2o((d - 0.05) / 0.34);
    const sweepX = d < 0.04 ? lerp(-12, 8, d / 0.04) : lerp(8, 28, E.p2o((d - 0.04) / 0.3)), sweepOp = d < 0.04 ? 1 : 1 - E.p2o((d - 0.04) / 0.3);
    return { active: true, washOp, coreScale, coreOp, coreRot: -5, sweepX, sweepOp, sync: [{ id: 'flash', t: tHit }] };
  }
  flash.build = host => { const root = mk('div', 'bl-flash', host, '<div class="bl-flash-wash"></div><div class="bl-flash-core"></div><div class="bl-flash-sweep"></div>'); return { els: { root, wash: root.children[0], core: root.children[1], sweep: root.children[2] } }; };
  flash.draw = (st, t, tHit) => { const s = flash(t, tHit), e = st.els; e.root.style.display = s.active ? 'block' : 'none'; if (!s.active) return s; setOp(e.wash, s.washOp); setOp(e.core, s.coreOp); setTf(e.core, 'rotate(' + s.coreRot + 'deg) scale(' + s.coreScale.toFixed(3) + ')'); setOp(e.sweep, s.sweepOp); setTf(e.sweep, 'translateX(' + s.sweepX.toFixed(2) + '%) rotate(108deg)'); return s; };
  /* BL.freezeDress(t, {at, rect:[x,y,w,h], badge?, flash=true}) → {outlineOp, badgeOp, flashOp}: dressing SNAPS on at `at`
     (no tween) with one single-exposure flash 0.55 → 0 over 0.28 s (never a strobe). Goes over a real still; mask
     first, dress second. */
  function freezeDress(t, o) { const on = t >= o.at ? 1 : 0; return { outlineOp: on, badgeOp: on, flashOp: o.flash === false ? 0 : 0.55 * (1 - rmp(t, o.at, o.at + 0.28)), sync: [{ id: 'freeze', t: o.at }] }; }
  freezeDress.build = (host, o) => { const root = mk('div', 'bl-freeze', host, '<div class="bl-freeze-outline"></div><div class="bl-freeze-badge"></div><div class="bl-freeze-flash"></div>'); const r = o.rect; root.children[0].style.cssText = 'left:' + r[0] + 'px;top:' + r[1] + 'px;width:' + r[2] + 'px;height:' + r[3] + 'px'; root.children[1].style.cssText = 'left:' + r[0] + 'px;top:' + (r[1] - 30) + 'px'; root.children[1].textContent = o.badge || ''; return { o, els: { root, outline: root.children[0], badge: root.children[1], flash: root.children[2] } }; };
  freezeDress.draw = (st, t) => { const s = freezeDress(t, st.o), e = st.els; setOp(e.outline, s.outlineOp); setOp(e.badge, s.badgeOp); setOp(e.flash, s.flashOp); return s; };
  /* BL.hardCut(t, tSwitch) → {streakScale, streakOp, blur, bright, dx, dy, push}: the hard-cut connector — streak scaleX 0.35→1.6 over
     0.12 s power4.in (14 px blur, 1.35 brightness); the incoming shot lands AT the switch (no black gap) with ±24 px
     offsets settling 0.4 s power3.out, then a 1.02 push over 1.17 s sine.out. */
  function hardCut(t, tSwitch) {
    const d = t - tSwitch, pre = d >= -0.12 && d < 0, u = pre ? E.p4i((d + 0.12) / 0.12) : 0, settle = E.p3o(rmp(d, 0, 0.4));
    return { streakScale: pre ? lerp(0.35, 1.6, u) : 0, streakOp: pre ? u : 0, blur: pre ? 14 : 0, bright: pre ? 1.35 : 1, dx: d >= 0 ? 24 * (1 - settle) : 0, dy: d >= 0 ? -24 * (1 - settle) : 0, push: d >= 0 ? 1 + 0.02 * E.sineOut(rmp(d, 0, 1.17)) : 1 };
  }
  /* BL.recHud(t, {start, clock0=0}) → {rec (on/off), recOp, clock 'hh:mm:ss'}: REC blinks on a 0.55 s period (opacity 1 / 0.25);
     the counter floors real seconds — an honesty label for real recordings ("live recording"). */
  function recHud(t, o) { const d = Math.max(0, t - (o.start || 0)), s = Math.floor((o.clock0 || 0) + d), on = Math.floor(d / 0.275) % 2 === 0; const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = s % 60; return { rec: on, recOp: on ? 1 : 0.25, clock: [hh, mm, ss].map(v => String(v).padStart(2, '0')).join(':') }; }

  /* ============================================================ lockup / close ================================= */
  /* BL.titleLockup — kicker / wordmark / hairline rule / label, IN = 1.80 s, then TRULY still (no drift, no breath).
     opts: {t0, t1?, kicker, wordmark, label, accent, fg='#E9F3F9', bg='#082A34', exit='none'}
     kicker 0–0.45 s; wordmark settles scale 0.96→1 and fades over 0.25–1.10 s power3.out; the rule draws left→right
     0.90–1.45 s by measured dash; label 1.30–1.80 s. Kicker/label ink = 62 % fg mixed with bg (≥ 4.5:1). */
  const titleLockup = {
    IN: 1.8,
    calc(t, o) {
      const e = env(t, o, titleLockup.IN, 0.5), lt = e.lt, x = exitOf(e);
      return { phase: e.phase, op: x.op, y: x.y, kickerOp: E.p2o(rmp(lt, 0, 0.45)), markOp: E.p2o(rmp(lt, 0.25, 0.8)), markScale: 0.96 + 0.04 * E.p3o(rmp(lt, 0.25, 1.1)), ruleU: E.p3o(rmp(lt, 0.9, 1.45)), labelOp: E.p2o(rmp(lt, 1.3, 1.8)), still: lt >= titleLockup.IN, sync: [{ id: 'lockup-settled', t: o.t0 + titleLockup.IN * e.k }] };
    },
    build(host, o) {
      const root = mk('div', 'bl-lockup', host), ink = ink62(o.fg || '#E9F3F9', o.bg || '#082A34');
      const kicker = mk('div', 'bl-lockup-kicker', root); kicker.textContent = o.kicker || ''; kicker.style.color = ink;
      const mark = mk('div', 'bl-lockup-mark', root); mark.textContent = o.wordmark || ''; mark.style.color = o.fg || '#E9F3F9';
      const rule = mk('div', 'bl-lockup-rule', root, '<svg width="140" height="2" viewBox="0 0 140 2"><path d="M0 1 H140" stroke-width="2"/></svg>'); const p = rule.firstChild.firstChild; p.setAttribute('stroke', o.accent || '#E56B5E'); const len = p.getTotalLength(); p.style.strokeDasharray = len.toFixed(2);
      const label = mk('div', 'bl-lockup-label', root); label.textContent = o.label || ''; label.style.color = ink;
      return { o, els: { root, kicker, mark, rule: p, label }, len };
    },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o; const s = titleLockup.calc(t, O), e = st.els; setOp(e.root, s.op); setTf(e.root, 'translateY(' + px(s.y) + ')'); setOp(e.kicker, s.kickerOp); setOp(e.mark, s.markOp); setTf(e.mark, 'scale(' + s.markScale.toFixed(4) + ')'); e.rule.style.strokeDashoffset = (st.len * (1 - s.ruleU)).toFixed(2); setOp(e.label, s.labelOp); return s; }
  };
  /* BL.ctaClose — the action-only close: words land per word (rise 24 px + fade, power3.out, 0.10 s stagger), one
     capsule pops from scale 0.85 at 0.72 s with a single restrained overshoot, settled by 1.32 s, then DEAD STILL.
     opts: {t0, t1?, line, button, accent}. Keep the bottom 16.67 % band free — the mandatory credit lives there. */
  const ctaClose = {
    calc(t, o) {
      const lt = t - o.t0, words = o.line.split(' ').map((w, i) => { const u = E.p3o(rmp(lt, i * 0.1, i * 0.1 + 0.45)); return { w, op: u, y: (1 - u) * 24 }; });
      const cu = rmp(lt, 0.72, 1.32);
      return { words, capsule: { op: E.p2o(rmp(lt, 0.72, 0.95)), scale: lt < 0.72 ? 0.85 : 0.85 + 0.15 * E.backOut(1.2)(cu) }, still: lt >= 1.32, sync: [{ id: 'cta-settled', t: o.t0 + 1.32 }] };
    },
    build(host, o) { const root = mk('div', 'bl-cta', host); const line = mk('div', 'bl-cta-line', root); const words = o.line.split(' ').map(w => { const s = mk('span', null, line); s.textContent = w; line.appendChild(document.createTextNode(' ')); return s; }); const cap = mk('div', 'bl-cta-capsule', root); cap.textContent = o.button || ''; cap.style.background = o.accent || '#E56B5E'; return { o, els: { root, words, cap } }; },
    draw(st, t, win) { const O = win ? Object.assign({}, st.o, win) : st.o; const s = ctaClose.calc(t, O), e = st.els; s.words.forEach((w, i) => { setOp(e.words[i], w.op); setTf(e.words[i], 'translateY(' + px(w.y) + ')'); }); setOp(e.cap, s.capsule.op); setTf(e.cap, 'scale(' + s.capsule.scale.toFixed(4) + ')'); return s; }
  };
  /* BL.wordSweep(t, t0, t1, n) → ink[] per word: one linear scalar sweeps n words from faint to full ink evenly across t0..t1 */
  const wordSweep = (t, t0, t1, n) => { const u = rmp(t, t0, t1) * n; return Array.from({ length: n }, (_, i) => clamp(u - i, 0, 1)); };

  /* ============================================================ camera servo / cursor ========================== */
  /* Camera-servo law: one world wrapper carries translate(x, y) scale(S); the counter-translate is T = -offset × S on
     a single wrapper (T = -offset with nested wrappers); measure targets with getBoundingClientRect after
     fonts.ready; cap the scale so the target fills ≤ 88 % of the canvas; clamp the pan so the scaled world always
     covers the viewport. */
  /* BL.servo(t, {t0, dur=1.1, anchor:[x,y] stage px, s, target?:[w,h] stage px, from?:{s,cx,cy}, stage=[1280,720]}) → {s, cx, cy, u, capped} */
  function servo(t, o) {
    const st = o.stage || [1280, 720], from = o.from || { s: 1, cx: st[0] / 2, cy: st[1] / 2 }, u = E.p2io(rmp(t, o.t0, o.t0 + (o.dur == null ? 1.1 : o.dur)));
    let s = o.s == null ? 1.6 : o.s, capped = false;
    if (o.target) { const cap = 0.88 * Math.min(st[0] / Math.max(1, o.target[0]), st[1] / Math.max(1, o.target[1])); if (s > cap) { s = cap; capped = true; } }
    const S = lerp(from.s, s, u), cx = lerp(from.cx, o.anchor[0], u), cy = lerp(from.cy, o.anchor[1], u);
    const hw = st[0] / 2 / S, hh = st[1] / 2 / S;
    return { s: S, cx: S < 1.0005 ? st[0] / 2 : clamp(cx, hw, st[0] - hw), cy: S < 1.0005 ? st[1] / 2 : clamp(cy, hh, st[1] - hh), u, capped, sCap: s };
  }
  /* CSS transform for a camera state on a single world wrapper (transform-origin 0 0) */
  servo.transform = (c, stage) => { const st = stage || [1280, 720]; return c.s < 1.0005 ? 'none' : 'translate(' + (st[0] / 2 - c.s * c.cx).toFixed(2) + 'px,' + (st[1] / 2 - c.s * c.cy).toFixed(2) + 'px) scale(' + c.s.toFixed(4) + ')'; };
  /* BL.focusZoom(t, {t0, t1, cue, anchor, s=1.6, target?, halo=true, H=720}) → {op, y, scale, cam, halo:{op, scale}, drift:{dx,dy}}
     0.9 s settle (rise 4.5 % of H, scale 0.965→1, power3.out), one 1.1 s power2.inOut servo move on `cue`, an
     optional 0.75 s halo bloom starting halfway through the move, then micro-drift (BL.driftZero) ending dead still. */
  function focusZoom(t, o) {
    const fr = deviceFrame.calc(t, { t0: o.t0, t1: o.t1, exit: o.exit, H: o.H }), cam = servo(t, { t0: o.cue, dur: 1.1, anchor: o.anchor, s: o.s == null ? 1.6 : o.s, target: o.target });
    const tEnd = o.cue + 1.1, hold = (o.t1 == null ? tEnd + 2 : o.t1) - tEnd, dr = driftZero(t, tEnd, hold);
    const hu = o.halo === false ? 0 : rmp(t, o.cue + 0.55, o.cue + 1.3);
    return { op: fr.op, y: fr.y, scale: fr.scale, cam: { s: cam.s, cx: cam.cx + dr.dx * 1280, cy: cam.cy + dr.dy * 720 }, capped: cam.capped, halo: { op: Math.sin(Math.PI * hu) * 0.55, scale: 0.6 + 0.4 * E.p2o(hu) }, drift: dr, sync: [{ id: 'focus-landed', t: tEnd }] };
  }
  /* BL.spring(aimFn, {omega=6, fps=60, sub=4, dur, t0=0}) → {pos(t), samples}: a critically damped spring over aim(t)
     (returns [x,y]) integrated ONCE at 60 Hz × 4 substeps and read back by time — seekable. Pre-integrate per shot. */
  function spring(aimFn, o) {
    const omega = o.omega || 6, fps = o.fps || 60, sub = o.sub || 4, dt = 1 / (fps * sub), t0 = o.t0 || 0, n = Math.ceil((o.dur || 5) * fps) + 1;
    let p = aimFn(t0).slice(), v = [0, 0]; const S = [];
    for (let f = 0; f <= n; f++) { S.push([p[0], p[1]]); for (let j = 0; j < sub; j++) { const a = aimFn(t0 + (f * sub + j) * dt); for (let k = 0; k < 2; k++) { v[k] += (omega * omega * (a[k] - p[k]) - 2 * omega * v[k]) * dt; p[k] += v[k] * dt; } } }
    return { samples: S, pos(t) { const q = clamp((t - t0) * fps, 0, n), i = Math.floor(q), a = S[i], b = S[Math.min(n, i + 1)], f = q - i; return [lerp(a[0], b[0], f), lerp(a[1], b[1], f)]; } };
  }
  /* BL.cursorArc(p0, p1, u, bend=0.12) → [x,y]: a shallow quadratic arc between two points */
  function cursorArc(p0, p1, u, bend) { bend = bend == null ? 0.12 : bend; const cx = (p0[0] + p1[0]) / 2 - (p1[1] - p0[1]) * bend, cy = (p0[1] + p1[1]) / 2 + (p1[0] - p0[0]) * bend, w = 1 - u; return [w * w * p0[0] + 2 * w * u * cx + u * u * p1[0], w * w * p0[1] + 2 * w * u * cy + u * u * p1[1]]; }
  /* BL.clickRing(t, tClick, {dur=0.35, r0=12, r1=44}) → {r, op, active}: the ring grows 12 → 44 over 0.35 s while fading */
  function clickRing(t, tClick, o) { o = o || {}; const d = o.dur == null ? 0.35 : o.dur, u = tClick < 0 ? 1 : (t - tClick) / d; if (!(u >= 0 && u < 1)) return { r: 0, op: 0, active: false }; return { r: lerp(o.r0 == null ? 12 : o.r0, o.r1 == null ? 44 : o.r1, E.p2o(u)), op: 1 - u, active: true }; }
  /* BL.press(t, tClick, {down=0.08, up=0.2, cursor=0.9, target=0.96}) → {u, cursorScale, targetScale}: 80 ms down / 200 ms up;
     the target depresses in lockstep. (Oversized-cursor register: down 0.1 s, release 0.22 s.) */
  function press(t, tClick, o) { o = o || {}; const dn = o.down == null ? 0.08 : o.down, up = o.up == null ? 0.2 : o.up, d = t - tClick; const u = d < 0 || d >= dn + up ? 0 : d < dn ? d / dn : 1 - E.p2o((d - dn) / up); return { u, cursorScale: 1 - (1 - (o.cursor == null ? 0.9 : o.cursor)) * u, targetScale: 1 - (1 - (o.target == null ? 0.96 : o.target)) * u }; }
  /* BL.cursorLeave(t, {at, from:[x,y], dir=[1,0.3], dur=0.4, stage}) → [x,y]: the cursor leaves the frame physically (power2.in), never fades in place */
  function cursorLeave(t, o) { const st = o.stage || [1280, 720], dir = o.dir || [1, 0.3], u = E.p2i(rmp(t, o.at, o.at + (o.dur == null ? 0.4 : o.dur))), far = Math.max(st[0], st[1]) * 1.2; return [o.from[0] + dir[0] * far * u, o.from[1] + dir[1] * far * u]; }
  /* BL.follow({t0, start:[x,y], clicks:[{t, x, y}], zoom=1.8, exitAt, stage}) → {cam(t) → {s,cx,cy}, cursor(t) → [x,y], ring(t), press(t)}
     screen-recording auto-zoom: the camera aims 60 % of the way from the cursor to the click it is heading for (the
     push leads) through a critically damped spring (ω = 6); zoom to 1.8 over 0.85 s power3.inOut from t0; cursor moves
     are shallow arcs (bend 0.12) on power3.out arriving at each click; exit zoom-out 1.0 s at exitAt. Pre-integrates once.
     Honesty: over real footage only at recorded click positions / times (shot log). */
  function follow(o) {
    const st = o.stage || [1280, 720], clicks = o.clicks.slice().sort((a, b) => a.t - b.t), zoom = o.zoom || 1.8, exitAt = o.exitAt == null ? (clicks.length ? clicks[clicks.length - 1].t + 1.2 : o.t0 + 3) : o.exitAt;
    const cursor = t => { let here = o.start || [st[0] / 2, st[1] / 2]; for (const c of clicks) { const a = c.t - (c.move || 0.7); if (t < a) return here; if (t <= c.t) return cursorArc(here, [c.x, c.y], E.p3o((t - a) / (c.t - a)), 0.12); here = [c.x, c.y]; } return here; };
    const aim = t => { const c = cursor(t), nx = clicks.find(k => t <= k.t); return nx ? [lerp(c[0], nx.x, 0.6), lerp(c[1], nx.y, 0.6)] : c; };
    const sp = spring(aim, { omega: 6, fps: 60, sub: 4, dur: exitAt + 1.5 - o.t0, t0: o.t0 });
    const cam = t => { const z = t < exitAt ? lerp(1, zoom, E.p3io(rmp(t, o.t0, o.t0 + 0.85))) : lerp(zoom, 1, E.p3io(rmp(t, exitAt, exitAt + 1.0))), p = sp.pos(t), hw = st[0] / 2 / z, hh = st[1] / 2 / z; return { s: z, cx: z < 1.0005 ? st[0] / 2 : clamp(p[0], hw, st[0] - hw), cy: z < 1.0005 ? st[1] / 2 : clamp(p[1], hh, st[1] - hh) }; };
    const last = t => { let h = null; for (const c of clicks) if (t >= c.t) h = c; return h; };
    return { cam, cursor, ring: t => { const h = last(t); return clickRing(t, h ? h.t : -1); }, press: t => { const h = last(t); return press(t, h ? h.t : -99); }, exitAt, sync: clicks.map((c, i) => ({ id: 'click-' + i, t: c.t })) };
  }

  /* ============================================================ styles ========================================== */
  /* BL.installStyles(tokens?) — idempotent default stylesheet for the .bl-* classes (scenes may override). Tokens:
     {bg, fg, muted, accent, line, mono, sans}. Colours default to the v3 template palette. */
  function installStyles(T) {
    if (typeof document === 'undefined' || document.getElementById('bl-css')) return;
    T = Object.assign({ bg: TOK.bg, fg: TOK.fg, muted: TOK.muted, accent: TOK.accent, line: 'rgba(233,243,249,.18)', surface: 'rgba(233,243,249,.06)', mono: 'Consolas,"Courier New",monospace', sans: '"Helvetica Neue",Arial,sans-serif' }, T || {});
    Object.assign(TOK, { bg: T.bg, fg: T.fg, muted: T.muted, accent: T.accent });
    const css = `
.bl-kpi{position:absolute;color:${T.fg};font-family:${T.sans};opacity:0;transform-origin:50% 60%}
.bl-kpi-label{font:500 13px/1 ${T.sans};letter-spacing:.14em;text-transform:uppercase;color:${T.muted};margin-bottom:10px;white-space:nowrap}
.bl-kpi-row{display:flex;align-items:baseline;gap:8px}
.bl-kpi-num{font:600 72px/1 ${T.sans};font-variant-numeric:tabular-nums;letter-spacing:-.02em;display:inline-block;white-space:nowrap}
.bl-kpi-suffix{font:500 30px/1 ${T.sans};color:${T.muted};opacity:0}
.bl-kpi-track{height:4px;background:${T.line};border-radius:2px;margin-top:16px;overflow:hidden}
.bl-kpi-fill{height:100%;background:${T.accent};transform-origin:0 50%;transform:scaleX(0)}
.bl-kpi-ring{position:absolute;right:-110px;top:-10px;width:88px;height:88px}
.bl-kpi-ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.bl-kpi-ring-track{fill:none;stroke:${T.line};stroke-width:8}
.bl-kpi-ring-fill{fill:none;stroke:${T.accent};stroke-width:8;stroke-linecap:round}
.bl-chat{position:absolute;width:560px;height:100%;font-family:${T.sans};color:${T.fg}}
.bl-chat-thread{min-height:200px}
.bl-chat-q{display:inline-block;float:right;clear:both;max-width:78%;background:${T.surface};border:1px solid ${T.line};border-radius:14px 14px 4px 14px;padding:12px 16px;font:400 17px/1.4 ${T.sans};opacity:0;transform-origin:100% 100%}
.bl-chat-a{clear:both;position:relative;padding-top:16px;font:400 18px/1.55 ${T.sans};color:${T.fg}}
.bl-chat-w{color:transparent}
.bl-chat-receipt{margin-top:12px;font:500 12px/1 ${T.mono};letter-spacing:.06em;color:${T.muted};opacity:0}
.bl-chat-dots{position:absolute;left:0;top:22px;display:flex;gap:6px;padding:10px 14px;border-radius:14px 14px 14px 4px;background:${T.surface};opacity:0;transform-origin:0 100%}
.bl-chat-dots i{width:8px;height:8px;border-radius:50%;background:${T.muted};display:block}
.bl-chat-composer{position:absolute;left:0;right:0;bottom:0;height:52px;border:1px solid ${T.line};border-radius:12px;background:${T.surface};padding:0 56px 0 16px;display:flex;align-items:center;font:400 17px/1 ${T.sans};white-space:nowrap;overflow:hidden}
.bl-chat-caret{display:inline-block;width:2px;height:22px;background:${T.fg};margin-left:1px;opacity:0}
.bl-chat-send{position:absolute;right:10px;top:10px;width:32px;height:32px;border-radius:50%;background:${T.accent};opacity:0}
.bl-chat-send:after{content:"";position:absolute;left:12px;top:9px;width:8px;height:8px;border-top:2px solid #fff;border-right:2px solid #fff;transform:rotate(-45deg)}
.bl-stack{position:absolute;inset:0;opacity:0}
.bl-stack-world{position:absolute;transform-style:preserve-3d}
.bl-stack-plate{position:absolute;left:0;top:0;transform-style:preserve-3d;transform-origin:50% 50%}
.bl-stack-side,.bl-stack-face{position:absolute;inset:0}
.bl-stack-glyph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.bl-stack-glyph svg{width:36%;height:36%}
.bl-stack-leaders{position:absolute;inset:0;pointer-events:none}
.bl-stack-label{position:absolute;left:0;top:0;font:500 16px/1 ${T.sans};color:${T.fg};opacity:0;white-space:nowrap;letter-spacing:.02em}
.bl-chart{position:absolute;opacity:0;font-family:${T.sans}}
.bl-chart svg{display:block;overflow:visible}
.bl-chart .bl-lab{font-family:${T.sans}}
.bl-callout{position:absolute;right:0;top:0;color:#fff;font:600 22px/1 ${T.sans};font-variant-numeric:tabular-nums;padding:10px 14px;border-radius:8px;opacity:0;transform-origin:50% 100%}
.bl-race{position:absolute;font-family:${T.sans};color:${T.fg};opacity:0}
.bl-race-axis{position:absolute;top:0;right:90px;height:100%;}
.bl-race-tick{position:absolute;left:0;top:0;height:100%;border-left:1px solid ${T.line};opacity:0}
.bl-race-tick span{position:absolute;top:0;left:4px;font:500 11px/1 ${T.mono};color:${T.muted};white-space:nowrap}
.bl-race-period{position:absolute;right:0;bottom:0;font:700 48px/1 ${T.sans};color:${T.muted};opacity:.6;font-variant-numeric:tabular-nums}
.bl-race-row{position:absolute;left:0;top:0;width:100%;display:flex;align-items:center}
.bl-race-name{display:inline-block;text-align:right;font:500 14px/1 ${T.sans};white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bl-race-bar{position:absolute;top:0;height:100%;border-radius:3px;background:${T.muted}}
.bl-race-val{position:absolute;top:50%;transform:translateY(-50%);font:600 13px/1 ${T.mono};font-variant-numeric:tabular-nums;white-space:nowrap}
.bl-frame{position:absolute;border:1px solid ${T.line};border-radius:10px;background:${T.surface};overflow:hidden;opacity:0;transform-origin:50% 60%;width:720px;height:440px}
.bl-frame-bar{height:36px;display:flex;align-items:center;gap:6px;padding:0 12px;border-bottom:1px solid ${T.line}}
.bl-frame-bar i{width:9px;height:9px;border-radius:50%;background:${T.line};display:block}
.bl-frame-pill{flex:1;margin-left:10px;height:20px;border-radius:10px;background:rgba(0,0,0,.18);font:400 11px/20px ${T.mono};color:${T.muted};text-align:center;letter-spacing:.04em}
.bl-frame-title{flex:1;text-align:center;font:500 12px/1 ${T.sans};color:${T.muted}}
.bl-frame-phone{width:300px;height:620px;border-radius:36px}
.bl-frame-notch{height:8%;position:relative}
.bl-frame-notch:after{content:"";position:absolute;left:50%;top:10px;width:90px;height:22px;margin-left:-45px;border-radius:12px;background:rgba(0,0,0,.35)}
.bl-frame-screen{position:absolute;left:0;right:0;bottom:0;top:36px;overflow:hidden}
.bl-frame-phone .bl-frame-screen{top:8%}
.bl-code{position:absolute;width:620px;padding:14px 0;border:1px solid ${T.line};border-radius:10px;background:rgba(0,0,0,.28);font:400 15px/var(--bl-lh,24px) ${T.mono};color:${T.fg};opacity:0;overflow:hidden;transform-origin:50% 50%}
.bl-code-line{display:flex;white-space:pre;overflow:hidden;position:relative}
.bl-code-n{width:44px;text-align:right;padding-right:12px;color:${T.muted};opacity:.6;flex:none}
.bl-code-c{white-space:pre}
.bl-code-band{position:absolute;left:48px;top:0;height:var(--bl-lh,24px);background:${T.accent};opacity:0;border-radius:3px;mix-blend-mode:screen;filter:opacity(.45)}
.bl-code-box{position:absolute;left:48px;right:12px;height:var(--bl-lh,24px);border:1.5px solid ${T.accent};border-radius:4px;opacity:0}
.bl-code-caret{position:absolute;left:0;top:4px;width:2px;height:18px;background:${T.fg}}
.bl-rail{position:absolute;display:flex;gap:10px;align-items:center;font-family:${T.mono}}
.bl-chip{display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid ${T.line};border-radius:999px;font:500 12px/1 ${T.mono};letter-spacing:.04em;opacity:0;color:${T.muted}}
.bl-chip i{width:7px;height:7px;border-radius:50%;background:transparent;border:1px solid ${T.muted};display:block}
.bl-chip[data-state=active]{color:${T.fg};background:${T.surface};border-color:${T.accent}}
.bl-chip[data-state=active] i{background:${T.accent};border-color:${T.accent}}
.bl-chip[data-state=done]{color:color-mix(in srgb,${T.muted} 55%,${T.bg});border-color:color-mix(in srgb,${T.muted} 35%,${T.bg})}
.bl-chip[data-state=done] i{background:color-mix(in srgb,${T.accent} 45%,${T.bg});border-color:transparent}
.bl-badge{padding:6px 10px;border:1px solid ${T.line};border-radius:6px;font:500 11px/1 ${T.mono};color:${T.muted};transform:scale(0);opacity:0}
.bl-hud{position:absolute;inset:0;pointer-events:none;font-family:${T.mono};color:${T.muted};opacity:0}
.bl-hud-br{position:absolute;width:48px;height:48px}
.bl-hud-br svg{width:100%;height:100%}.bl-hud-br path{stroke:${T.muted}}
.bl-hud-tl{left:40px;top:40px}.bl-hud-tr{right:40px;top:40px;transform:rotate(90deg)}.bl-hud-br{right:40px;bottom:40px;transform:rotate(180deg)}.bl-hud-bl{left:40px;bottom:40px;transform:rotate(270deg)}
.bl-hud-read{position:absolute;display:flex;gap:10px;font:500 12px/1 ${T.mono};letter-spacing:.08em;opacity:0;transform:none!important;width:auto;height:auto}
.bl-hud-read.bl-hud-tl{left:100px;top:56px}.bl-hud-read.bl-hud-tr{right:100px;top:56px}.bl-hud-read.bl-hud-bl{left:100px;bottom:56px}.bl-hud-read.bl-hud-br{right:100px;bottom:56px}
.bl-hud-l{opacity:.7}.bl-hud-v{color:${T.fg};font-variant-numeric:tabular-nums}.bl-hud-em .bl-hud-v{color:${T.accent}}
.bl-agent{position:absolute;left:0;top:0;opacity:0;pointer-events:none}
.bl-agent-arrow{position:absolute;left:0;top:0;width:0;height:0;border-left:7px solid ${T.fg};border-top:4px solid transparent;border-bottom:8px solid transparent;transform:rotate(-30deg)}
.bl-agent-tag{position:absolute;left:14px;top:12px;display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:6px;background:${T.bg};border:1px solid ${T.line};color:${T.fg};font:500 12px/1 ${T.mono};white-space:nowrap}
.bl-agent-dot{width:7px;height:7px;border-radius:50%;background:${T.accent};display:block}
.bl-agent-check{position:absolute;left:10px;color:${T.accent};transform:scale(0);font-size:12px}
.bl-agent-ring{position:absolute;left:0;top:0;border:2px solid ${T.accent};border-radius:50%;opacity:0}
.bl-flash{position:absolute;inset:-12%;pointer-events:none;mix-blend-mode:screen;display:none}
.bl-flash-wash{position:absolute;inset:0;background:rgb(255,253,250);opacity:0}
.bl-flash-core{position:absolute;inset:0;background:radial-gradient(circle at 50% 50%,#fff 0,rgb(255,253,250) 10%,rgba(255,174,105,.55) 26%,rgba(255,174,105,0) 42%);opacity:0;transform-origin:50% 50%}
.bl-flash-sweep{position:absolute;left:-30%;top:-40%;width:70%;height:180%;background:linear-gradient(90deg,rgba(255,174,105,0),rgba(255,174,105,.45) 35%,rgba(255,253,250,.85) 50%,rgba(183,218,255,.45) 65%,rgba(183,218,255,0));opacity:0}
.bl-freeze{position:absolute;inset:0;pointer-events:none}
.bl-freeze-outline{position:absolute;border:2px solid ${T.accent};border-radius:4px;opacity:0;box-shadow:0 0 0 4px rgba(0,0,0,.25)}
.bl-freeze-badge{position:absolute;background:${T.accent};color:#fff;font:600 12px/1 ${T.sans};letter-spacing:.08em;padding:6px 10px;border-radius:4px;opacity:0;white-space:nowrap}
.bl-freeze-flash{position:absolute;inset:0;background:#fff;opacity:0}
.bl-lockup{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;font-family:${T.sans}}
.bl-lockup-kicker{font:500 13px/1 ${T.mono};letter-spacing:.22em;text-transform:uppercase;opacity:0}
.bl-lockup-mark{font:700 84px/1 ${T.sans};letter-spacing:-.02em;opacity:0;transform-origin:50% 50%}
.bl-lockup-rule svg{display:block}
.bl-lockup-label{font:500 14px/1 ${T.mono};letter-spacing:.18em;text-transform:uppercase;opacity:0}
.bl-cta{position:absolute;left:0;right:0;top:0;bottom:16.67%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;font-family:${T.sans};color:${T.fg}}
.bl-cta-line{font:700 64px/1.1 ${T.sans};letter-spacing:-.015em;text-align:center;max-width:85%}
.bl-cta-line span{display:inline-block;opacity:0}
.bl-cta-capsule{padding:16px 34px;border-radius:999px;color:#fff;font:600 20px/1 ${T.sans};opacity:0;transform-origin:50% 50%}
`;
    const el = document.createElement('style'); el.id = 'bl-css'; el.textContent = css; document.head.appendChild(el);
  }

  root.BL = { VERSION: '4.0.0', E, clamp, rmp, lerp, env, exitOf, rows, driftZero, holdDrift, jitter, lcg, mixColor, ink62, collectSync, fmtNum,
    kpi, count, keystrokes, prompt, thinkDot, stream, bubble, dots, chatReveal, stack, chart, race,
    deviceFrame, browserFrame: deviceFrame, screenSwap, beforeAfter, screenRail,
    codeType, sweep, diff, scrollTo, code, stateRail, hud, agentTag,
    flash, freezeDress, hardCut, recHud, titleLockup, ctaClose, wordSweep, tokens: TOK,
    servo, focusZoom, spring, cursorArc, clickRing, press, cursorLeave, follow, installStyles };
})(typeof window !== 'undefined' ? window : globalThis);
