/* charts.js — CHART: data-truth chart blocks on the film clock (GSAP via lib/motion.js, SVG only).

   WHY. A chart in a demo film is a claim. Every number it shows is something the narration asserts and the product
   screen must be able to back. So no chart here accepts a literal number: a series entry says `claim: 'late_west'`
   and the value is looked up in the claims map (claims.json → "values": { id: { value, unit, source } }). A reference
   that does not resolve throws at BUILD time, so the film cannot render. Axis ticks are scale, not statements: they
   are "nice" round numbers derived from the largest claimed value (step = nice(max / 4)). Derived figures (shares,
   deltas, totals) are never computed and drawn — if the narration says "a third", "a third" is its own claim.
   Free text (labels, legend, notes) may not carry something that reads as a figure (12.4 %, $3.2M, 1,204) unless
   strict: false — "Q3", "2025", "Week 12" are fine.

   MOTION (measured, shared by every chart): marks grow FROM THE BASELINE over 0.6 s on power3.out, staggered 0.06 s
   per mark; value labels count up on the same tween with tabular digits; the frame (axis, labels, legend) arrives
   0.45 s before the first mark (MOTION.arrive). `land` is the absolute film second on which the LAST value must sit
   still — pass wt(phase, word) — and the block solves its own start: growStart = land − 0.6 − 0.06·(n − 1).
   Type: axis labels 14 px (13–16 allowed), tick labels 13 px, value labels 16 px semibold, legend sentence 14 px.
   Colours are the house palette (series order mint, coral, gold, cream), ink text on the navy ground.

   SEEK-SAFETY. Count-ups are rendered by a GSAP property plugin (`claimText`), not by onUpdate callbacks:
   MOTION.seek sets timelines with totalTime(t, true), which suppresses callbacks but renders every plugin. Every
   tween is a fromTo with explicit values and immediateRender: false; initial attributes are written at build, so
   a worker whose first frame is mid-chart shows the same pixels as one that played from the start.

   API (host = a stage-level element, usually a child of #ovl or a card; never the footage lane):
     CHART.use(claims)                                  default claims map (window.CLAIMS from scenes/claims_data.js)
     CHART.resolve(ref, claims?) → {id, value, unit, source}         throws when the id is missing
     CHART.fmt(v, {dec, unit, unitPos:'suffix'|'prefix', locale:'en-US'})
     CHART.bars(host, { id, series:[{label, claim}], land, end, start?, w:640, h:360, legend, unit?, dec?, exit? })
     CHART.line(host, { id, points:[{label, claim}], land, end, legend, … })          straight segments only
     CHART.kpiTiles(host, { id, tiles:[{label, claim, note?, dec?, unit?}], land, end, w:900, h:150, legend })
     CHART.race(host, { id, series:[{name}], periods:[{label, values:{name: claimId}}], periodDur:1.2, land, end, barCount:6 })
     CHART.donut(host, { id, segments:[{label, claim}], total?:claimId, land, end, legend, w:520, h:360 })
       → block { id, kind, el (svg), wrap, start, end, land, refs:[{claim, value}], tl }   (also registered in MOTION)
     CHART.manifest() → [{id, kind, land, refs}]       the gate hook: every rendered figure with its claim id
   Node CLI (gate hook, no browser):
     node lib/charts.js --check claims.json scenes/film.html scenes/shots.js …   every `claim: '<id>'` in the authored
       files must exist in claims.json "values" (exit 1 with the list of missing ids)   — text_gate 'chart values'
     node lib/charts.js --selftest        pure parts: resolve, fmt, ticks, layout, race ranks, strict-text guard */
(function (root) {
  'use strict';
  const PAL = { navy: '#082A34', navy2: '#204A56', ink: '#E9F3F9', cream: '#ECDEC3', coral: '#E56B5E', mint: '#81A9AB', gold: '#E8C874' };
  const SERIES = [PAL.mint, PAL.coral, PAL.gold, PAL.cream];
  const FONT = "Arial,'Segoe UI',sans-serif";
  const M = { grow: 0.6, stagger: 0.06, lead: 0.45, ease: 'power3.out', axisPx: 14, tickPx: 13, valuePx: 16, legendPx: 14 };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const FIGURE = /\d[\d,]*\.\d+|\d+\s?%|[$€£]\s?\d|\d{1,3}(,\d{3})+/;     // "reads as a figure" in free text
  let CLAIMS = null, charts = [];

  /* ---------- claims ---------- */
  function use(c) { CLAIMS = c || null; return CLAIMS; }
  function valuesOf(c) { c = c || CLAIMS; if (!c) throw new Error('charts.js: no claims map — CHART.use(window.CLAIMS) or pass {claims}'); return c.values && typeof c.values === 'object' ? c.values : c; }
  function resolve(ref, c) {
    const V = valuesOf(c), e = V[ref];
    if (e === undefined || e === null) throw new Error('charts.js: value "' + ref + '" is not in claims.json values — a chart may only show what the narration claims and the screen shows');
    const v = typeof e === 'number' ? e : e.value;
    if (typeof v !== 'number' || !isFinite(v)) throw new Error('charts.js: claims value "' + ref + '" is not a finite number');
    return { id: ref, value: v, unit: typeof e === 'object' ? (e.unit || '') : '', source: typeof e === 'object' ? (e.source || '') : '' };
  }
  function guardText(s, strict, what) {
    if (strict !== false && s && FIGURE.test(String(s))) throw new Error('charts.js: ' + what + ' "' + s + '" reads as a figure; figures must be claims (or pass strict:false)');
    return s === undefined || s === null ? '' : String(s);
  }
  function fmt(v, o) {
    o = o || {}; const dec = o.dec === undefined ? (Math.abs(v) < 10 && v % 1 !== 0 ? 1 : 0) : o.dec;
    const s = Number(v).toLocaleString(o.locale || 'en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
    if (!o.unit) return s;
    return (o.unitPos === 'prefix' || /^[$€£]$/.test(o.unit)) ? o.unit + s : s + (o.unit === '%' ? '%' : ' ' + o.unit);
  }
  function niceStep(x) { if (x <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(x))), f = x / p; return (f <= 1.2 ? 1 : f <= 2.4 ? 2 : f <= 3.2 ? 2.5 : f <= 6 ? 5 : 10) * p; }   // loose nice numbers: 3–6 ticks
  function ticks(max, n) { const step = niceStep(Math.max(1e-9, max) / (n || 4)), out = []; for (let v = 0; v <= max * 1.0001 + step * 0.999; v += step) { out.push(+v.toFixed(10)); if (out.length > 12) break; } return { step, ticks: out, top: out[out.length - 1] }; }
  function decOf(refs, o) { if (o.dec !== undefined) return o.dec; return refs.some(r => r.value % 1 !== 0) ? 1 : 0; }

  /* ---------- GSAP plugin: formatted digits as a rendered property ---------- */
  let pluginReady = false;
  function ensurePlugin(G) {
    if (pluginReady) return;
    // rawVars: GSAP otherwise treats function-valued vars (our fmt) as function-based values and calls them at init
    G.registerPlugin({ name: 'claimText', rawVars: 1, init(target, vars) { this.t = target; this.a = vars.from || 0; this.d = vars.to - this.a; this.f = vars.fmt || (v => String(v)); return true; },
      render(ratio, data) { const v = data.a + data.d * ratio; data.t.textContent = data.f(v); } });
    pluginReady = true;
  }

  /* ---------- svg helpers ---------- */
  const NS = 'http://www.w3.org/2000/svg';
  function mk(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) if (attrs[k] !== undefined) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
  function text(parent, x, y, s, o) {
    o = o || {}; const e = mk('text', { x, y, fill: o.fill || PAL.ink, 'font-family': FONT, 'font-size': o.px || M.axisPx, 'font-weight': o.weight || 400, 'text-anchor': o.anchor || 'start', 'dominant-baseline': o.base || 'auto' }, parent);
    e.style.fontVariantNumeric = 'tabular-nums'; e.textContent = s; return e;
  }
  function frameFor(host, o, kind) {
    const wrap = document.createElement('div'); wrap.className = 'chart chart-' + kind; wrap.id = o.id;
    wrap.style.cssText = 'position:absolute;left:' + (o.x || 0) + 'px;top:' + (o.y || 0) + 'px;width:' + o.w + 'px;height:' + o.h + 'px;visibility:hidden';
    const svg = mk('svg', { width: o.w, height: o.h, viewBox: '0 0 ' + o.w + ' ' + o.h }, null); wrap.appendChild(svg); host.appendChild(wrap);
    return { wrap, svg };
  }
  function legendLine(svg, o, y) { if (o.legend) text(svg, o.w / 2, y, guardText(o.legend, o.strict, 'legend'), { px: M.legendPx, fill: PAL.cream, anchor: 'middle' }); }
  function schedule(o, n, perMark) {
    if (typeof o.land !== 'number') throw new Error('charts.js: ' + o.id + ' needs land (absolute film second the last value sits still on)');
    const span = M.grow + (perMark === undefined ? M.stagger : perMark) * Math.max(0, n - 1);
    const growStart = o.land - span, start = o.start === undefined ? growStart - M.lead : o.start;
    if (growStart - start < 0.2) throw new Error('charts.js: ' + o.id + ' start is too late for its land (frame needs >= 0.2 s before the first mark)');
    return { span, growStart, start, end: o.end === undefined ? Infinity : o.end, growAt: growStart - start };
  }
  function register(kind, o, S, el, refs, build) {
    const G = root.MOTION && root.MOTION.gsap; if (!G) throw new Error('charts.js: load gsap and lib/motion.js before lib/charts.js charts are built');
    ensurePlugin(G);
    const b = root.MOTION.block(o.id, (tl, elx, api) => {
      root.MOTION.arrive(tl, elx, 0, { dy: 18, dur: 0.5 });
      build(tl, api);
      if (o.exit && Number.isFinite(api.exitAt)) root.MOTION.leave(tl, elx, api.exitAt, { dx: -80, dur: 0.36 });
    }, { el: el.wrap, start: S.start, end: S.end, exit: o.exit ? 0.4 : 0 });
    const block = { id: o.id, kind, el: el.svg, wrap: el.wrap, start: S.start, end: S.end, land: o.land, refs: refs.map(r => ({ claim: r.id, value: r.value })), tl: b.tl };
    const i = charts.findIndex(c => c.id === o.id); if (i >= 0) charts[i] = block; else charts.push(block);
    return block;
  }
  const fmtOf = (o, dec) => v => fmt(v, { dec, unit: o.unit, unitPos: o.unitPos, locale: o.locale });

  /* ---------- bars ---------- */
  function barsLayout(o, refs) {
    const w = o.w, h = o.h, ml = 56, mr = 16, mt = 30, mb = o.legend ? 66 : 44, n = refs.length;
    const T = ticks(Math.max.apply(null, refs.map(r => r.value).concat([0])), o.ticks || 4), pw = w - ml - mr, ph = h - mt - mb, base = mt + ph;
    const pitch = pw / n, bw = Math.min(72, pitch * 0.58);
    const bars = refs.map((r, i) => { const bh = ph * r.value / T.top; return { x: ml + pitch * (i + 0.5) - bw / 2, w: bw, y: base - bh, h: bh, cx: ml + pitch * (i + 0.5) }; });
    return { ml, mr, mt, mb, pw, ph, base, T, bars };
  }
  function bars(host, o) {
    o = Object.assign({ w: 640, h: 360 }, o || {}); if (!o.id || !Array.isArray(o.series) || !o.series.length) throw new Error('charts.js: bars needs id and series[]');
    const refs = o.series.map(s => resolve(s.claim, o.claims)), dec = decOf(refs, o), L = barsLayout(o, refs), S = schedule(o, refs.length), el = frameFor(host, o, 'bars'), svg = el.svg;
    L.T.ticks.forEach(v => { const y = L.base - L.ph * v / L.T.top; mk('line', { x1: L.ml, x2: o.w - L.mr, y1: y, y2: y, stroke: v === 0 ? 'rgba(233,243,249,.55)' : 'rgba(233,243,249,.14)', 'stroke-width': 1 }, svg); text(svg, L.ml - 8, y + 4, fmt(v, { dec: 0, unit: o.unit, unitPos: o.unitPos }), { px: M.tickPx, fill: PAL.mint, anchor: 'end' }); });
    const rects = [], vals = [];
    L.bars.forEach((b, i) => {
      rects.push(mk('rect', { x: b.x, y: L.base, width: b.w, height: 0, rx: 3, fill: o.series[i].color || o.color || SERIES[0] }, svg));
      text(svg, b.cx, L.base + 20, guardText(o.series[i].label, o.strict, 'bar label'), { px: clamp(o.axisPx || M.axisPx, 13, 16), fill: PAL.ink, anchor: 'middle' });
      const v = text(svg, b.cx, b.y - 8, fmt(0, { dec, unit: o.unit, unitPos: o.unitPos }), { px: M.valuePx, weight: 600, fill: PAL.ink, anchor: 'middle' }); v.setAttribute('y', L.base - 8); vals.push(v);
    });
    legendLine(svg, o, o.h - 14);
    return register('bars', o, S, el, refs, (tl) => {
      L.bars.forEach((b, i) => { const at = S.growAt + i * M.stagger;
        tl.fromTo(rects[i], { attr: { y: L.base, height: 0 } }, { attr: { y: b.y, height: b.h }, duration: M.grow, ease: M.ease, immediateRender: false }, at);
        tl.fromTo(vals[i], { attr: { y: L.base - 8 } }, { attr: { y: b.y - 8 }, claimText: { from: 0, to: refs[i].value, fmt: fmtOf(o, dec) }, duration: M.grow, ease: M.ease, immediateRender: false }, at); });
    });
  }

  /* ---------- line ---------- */
  function line(host, o) {
    o = Object.assign({ w: 640, h: 360 }, o || {}); if (!o.id || !Array.isArray(o.points) || o.points.length < 2) throw new Error('charts.js: line needs id and >= 2 points');
    const refs = o.points.map(p => resolve(p.claim, o.claims)), dec = decOf(refs, o), n = refs.length, S = schedule(o, n), el = frameFor(host, o, 'line'), svg = el.svg;
    const ml = 56, mr = 24, mt = 30, mb = o.legend ? 66 : 44, pw = o.w - ml - mr, ph = o.h - mt - mb, base = mt + ph, T = ticks(Math.max.apply(null, refs.map(r => r.value)), o.ticks || 4);
    const pts = refs.map((r, i) => ({ x: ml + pw * (n === 1 ? 0.5 : i / (n - 1)), y: base - ph * r.value / T.top }));
    T.ticks.forEach(v => { const y = base - ph * v / T.top; mk('line', { x1: ml, x2: o.w - mr, y1: y, y2: y, stroke: v === 0 ? 'rgba(233,243,249,.55)' : 'rgba(233,243,249,.14)' }, svg); text(svg, ml - 8, y + 4, fmt(v, { dec: 0, unit: o.unit, unitPos: o.unitPos }), { px: M.tickPx, fill: PAL.mint, anchor: 'end' }); });
    const d = pts.map((p, i) => (i ? 'L' : 'M') + p.x.toFixed(2) + ' ' + p.y.toFixed(2)).join(' ');
    let len = 0; for (let i = 1; i < n; i++) len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    const path = mk('path', { d, fill: 'none', stroke: o.color || SERIES[0], 'stroke-width': 3, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-dasharray': len + ' ' + len, 'stroke-dashoffset': len }, svg);
    const dots = [], vals = [];
    pts.forEach((p, i) => { dots.push(mk('circle', { cx: p.x, cy: base, r: 4.5, fill: PAL.ink, stroke: o.color || SERIES[0], 'stroke-width': 2 }, svg));
      text(svg, p.x, base + 20, guardText(o.points[i].label, o.strict, 'point label'), { px: clamp(o.axisPx || M.axisPx, 13, 16), anchor: 'middle' });
      vals.push(text(svg, p.x, base - 12, fmt(0, { dec, unit: o.unit, unitPos: o.unitPos }), { px: M.valuePx, weight: 600, anchor: 'middle' })); });
    legendLine(svg, o, o.h - 14);
    return register('line', o, S, el, refs, (tl) => {
      tl.fromTo(path, { attr: { 'stroke-dashoffset': len } }, { attr: { 'stroke-dashoffset': 0 }, duration: S.span, ease: 'power2.out', immediateRender: false }, S.growAt);
      pts.forEach((p, i) => { const at = S.growAt + i * M.stagger;
        tl.fromTo(dots[i], { attr: { cy: base } }, { attr: { cy: p.y }, duration: M.grow, ease: M.ease, immediateRender: false }, at);
        tl.fromTo(vals[i], { attr: { y: base - 12 } }, { attr: { y: p.y - 12 }, claimText: { from: 0, to: refs[i].value, fmt: fmtOf(o, dec) }, duration: M.grow, ease: M.ease, immediateRender: false }, at); });
    });
  }

  /* ---------- kpi tiles ---------- */
  function kpiTiles(host, o) {
    o = Object.assign({ w: 900, h: 150, gap: 18 }, o || {}); if (!o.id || !Array.isArray(o.tiles) || !o.tiles.length) throw new Error('charts.js: kpiTiles needs id and tiles[]');
    const refs = o.tiles.map(t => resolve(t.claim, o.claims)), n = refs.length, S = schedule(o, n), el = frameFor(host, o, 'kpi'), svg = el.svg;
    const legendH = o.legend ? 26 : 0, tw = (o.w - o.gap * (n - 1)) / n, th = o.h - legendH, groups = [], vals = [];
    refs.forEach((r, i) => {
      const x = i * (tw + o.gap), g = mk('g', { transform: 'translate(0 ' + (th * 0.35) + ')', opacity: 0 }, svg);
      mk('rect', { x, y: 0, width: tw, height: th, rx: 12, fill: 'rgba(32,74,86,.72)', stroke: 'rgba(233,243,249,.12)' }, g);
      mk('rect', { x: x + 18, y: 18, width: 28, height: 3, rx: 1.5, fill: o.tiles[i].color || SERIES[i % SERIES.length] }, g);
      text(g, x + 18, 46, guardText(o.tiles[i].label, o.strict, 'tile label'), { px: clamp(o.axisPx || M.axisPx, 13, 16), fill: PAL.cream });
      const dec = o.tiles[i].dec === undefined ? (r.value % 1 !== 0 ? 1 : 0) : o.tiles[i].dec, unit = o.tiles[i].unit === undefined ? (r.unit || o.unit || '') : o.tiles[i].unit;
      vals.push({ el: text(g, x + 18, th - (o.tiles[i].note ? 44 : 28), fmt(0, { dec, unit }), { px: 42, weight: 600, fill: PAL.ink }), dec, unit, v: r.value });
      if (o.tiles[i].note) text(g, x + 18, th - 18, guardText(o.tiles[i].note, o.strict, 'tile note'), { px: 13, fill: PAL.mint });
      groups.push(g);
    });
    legendLine(svg, o, o.h - 8);
    return register('kpi', o, S, el, refs, (tl) => {
      groups.forEach((g, i) => { const at = S.growAt + i * M.stagger;
        tl.fromTo(g, { attr: { transform: 'translate(0 ' + (th * 0.35) + ')', opacity: 0 } }, { attr: { transform: 'translate(0 0)', opacity: 1 }, duration: M.grow, ease: M.ease, immediateRender: false }, at);
        tl.fromTo(vals[i].el, { claimText: { from: 0, to: 0, fmt: v => fmt(v, { dec: vals[i].dec, unit: vals[i].unit }) } }, { claimText: { from: 0, to: vals[i].v, fmt: v => fmt(v, { dec: vals[i].dec, unit: vals[i].unit }) }, duration: M.grow, ease: M.ease, immediateRender: false }, at); });
    });
  }

  /* ---------- race ---------- */
  /* pure: per period, series sorted by value (ties by series order) → rank table + the scale top per period */
  function racePlan(o, claims) {
    const names = o.series.map(s => s.name), refsAll = [];
    const periods = o.periods.map(p => {
      const vals = names.map(nm => { const ref = p.values[nm]; if (ref === undefined) throw new Error('charts.js: race period "' + p.label + '" has no value for series "' + nm + '"'); const r = resolve(ref, claims); refsAll.push(r); return r.value; });
      const order = names.map((_, i) => i).sort((a, b) => vals[b] - vals[a] || a - b), rank = []; order.forEach((si, k) => { rank[si] = k; });
      return { label: guardText(p.label, o.strict, 'period label'), vals, rank, top: ticks(Math.max.apply(null, vals), 4).top };
    });
    return { names, periods, refs: refsAll };
  }
  function race(host, o) {
    o = Object.assign({ w: 640, h: 360, periodDur: 1.2, barCount: 6 }, o || {}); if (!o.id || !Array.isArray(o.series) || !Array.isArray(o.periods) || !o.periods.length) throw new Error('charts.js: race needs id, series[] and periods[]');
    const P = racePlan(o, o.claims), n = P.names.length, T = P.periods.length, S = schedule(o, T, o.periodDur), el = frameFor(host, o, 'race'), svg = el.svg;
    const nameW = 120, ml = nameW + 12, mr = 90, mt = 44, mb = o.legend ? 40 : 16, pw = o.w - ml - mr, rows = Math.min(o.barCount, n), pitch = (o.h - mt - mb) / rows, bh = Math.max(14, pitch * 0.62);
    const dec = decOf(P.refs, o), yOf = k => mt + k * pitch + (pitch - bh) / 2, wOf = (v, top) => pw * v / top;
    // one label per period, toggled with attr opacity set()s (a rendered property; never textContent via a callback)
    const periodEls = P.periods.map((pd, k) => text(svg, o.w - mr + 70, 30, pd.label, { px: 26, weight: 600, fill: PAL.gold, anchor: 'end' }));
    periodEls.forEach((e, k) => e.setAttribute('opacity', k === 0 ? 1 : 0));
    mk('line', { x1: ml, x2: ml, y1: mt - 6, y2: o.h - mb, stroke: 'rgba(233,243,249,.45)' }, svg);
    const bars = P.names.map((nm, i) => {
      const g = mk('g', { transform: 'translate(0 ' + yOf(P.periods[0].rank[i]) + ')' }, svg);
      text(g, nameW, bh / 2 + 5, guardText(nm, o.strict, 'series name'), { px: clamp(o.axisPx || M.axisPx, 13, 16), anchor: 'end' });
      const r = mk('rect', { x: ml, y: 0, width: 0, height: bh, rx: 3, fill: o.series[i].color || SERIES[i % SERIES.length] }, g);
      const v = text(g, ml + 8, bh / 2 + 5, fmt(0, { dec, unit: o.unit, unitPos: o.unitPos }), { px: M.valuePx, weight: 600 });
      return { g, r, v };
    });
    legendLine(svg, o, o.h - 10);
    return register('race', o, S, el, P.refs, (tl) => {
      P.periods.forEach((pd, k) => {
        const at = S.growAt + k * o.periodDur, prev = P.periods[Math.max(0, k - 1)];
        P.names.forEach((nm, i) => {
          const w0 = k === 0 ? 0 : wOf(prev.vals[i], prev.top), w1 = wOf(pd.vals[i], pd.top), y0 = yOf(prev.rank[i]), y1 = yOf(pd.rank[i]);
          tl.fromTo(bars[i].r, { attr: { width: w0 } }, { attr: { width: w1 }, duration: M.grow, ease: M.ease, immediateRender: false }, at + (k === 0 ? i * M.stagger : 0));
          tl.fromTo(bars[i].v, { attr: { x: ml + 8 + w0 }, claimText: { from: k === 0 ? 0 : prev.vals[i], to: k === 0 ? 0 : prev.vals[i], fmt: fmtOf(o, dec) } }, { attr: { x: ml + 8 + w1 }, claimText: { from: k === 0 ? 0 : prev.vals[i], to: pd.vals[i], fmt: fmtOf(o, dec) }, duration: M.grow, ease: M.ease, immediateRender: false }, at + (k === 0 ? i * M.stagger : 0));
          if (k > 0 && y0 !== y1) tl.fromTo(bars[i].g, { attr: { transform: 'translate(0 ' + y0 + ')' } }, { attr: { transform: 'translate(0 ' + y1 + ')' }, duration: M.grow, ease: M.ease, immediateRender: false }, at);
        });
        if (k > 0) { const sw = at + M.grow * 0.5; tl.set(periodEls[k - 1], { attr: { opacity: 0 } }, sw); tl.set(periodEls[k], { attr: { opacity: 1 } }, sw); }
      });
    });
  }

  /* ---------- donut ---------- */
  function donut(host, o) {
    o = Object.assign({ w: 520, h: 360 }, o || {}); if (!o.id || !Array.isArray(o.segments) || !o.segments.length) throw new Error('charts.js: donut needs id and segments[]');
    const refs = o.segments.map(s => resolve(s.claim, o.claims)), n = refs.length, S = schedule(o, n), el = frameFor(host, o, 'donut'), svg = el.svg;
    const dec = decOf(refs, o), R = Math.min(o.h - (o.legend ? 60 : 30), o.w * 0.55) / 2 - 24, sw = 34, cx = o.w * 0.34, cy = (o.h - (o.legend ? 30 : 0)) / 2, C = 2 * Math.PI * R;
    const sum = refs.reduce((a, r) => a + r.value, 0); if (sum <= 0) throw new Error('charts.js: donut segments must sum to > 0');
    mk('circle', { cx, cy, r: R, fill: 'none', stroke: 'rgba(233,243,249,.10)', 'stroke-width': sw }, svg);
    const arcs = [], vals = []; let acc = 0;
    refs.forEach((r, i) => {
      const len = C * r.value / sum, col = o.segments[i].color || SERIES[i % SERIES.length];
      arcs.push({ el: mk('circle', { cx, cy, r: R, fill: 'none', stroke: col, 'stroke-width': sw, 'stroke-dasharray': '0 ' + C, 'stroke-dashoffset': -acc, transform: 'rotate(-90 ' + cx + ' ' + cy + ')' }, svg), len });
      const ly = cy - R + 14 + i * 30, lx = o.w * 0.66;
      mk('rect', { x: lx, y: ly - 11, width: 12, height: 12, rx: 3, fill: col }, svg);
      text(svg, lx + 20, ly, guardText(o.segments[i].label, o.strict, 'segment label'), { px: clamp(o.axisPx || M.axisPx, 13, 16), fill: PAL.cream });
      vals.push(text(svg, o.w - 8, ly, fmt(0, { dec, unit: o.unit, unitPos: o.unitPos }), { px: M.valuePx, weight: 600, anchor: 'end' }));
      acc += len;
    });
    let total = null; if (o.total) { total = resolve(o.total, o.claims); refs.push(total); text(svg, cx, cy - 4, '', { px: 34, weight: 600, anchor: 'middle' }); }
    const totalEl = total ? svg.lastChild : null; if (total && o.totalLabel) text(svg, cx, cy + 22, guardText(o.totalLabel, o.strict, 'total label'), { px: 13, fill: PAL.mint, anchor: 'middle' });
    legendLine(svg, o, o.h - 10);
    return register('donut', o, S, el, refs, (tl) => {
      arcs.forEach((a, i) => { const at = S.growAt + i * M.stagger;
        tl.fromTo(a.el, { attr: { 'stroke-dasharray': '0 ' + C } }, { attr: { 'stroke-dasharray': a.len + ' ' + (C - a.len) }, duration: M.grow, ease: M.ease, immediateRender: false }, at);
        tl.fromTo(vals[i], { claimText: { from: 0, to: 0, fmt: fmtOf(o, dec) } }, { claimText: { from: 0, to: refs[i].value, fmt: fmtOf(o, dec) }, duration: M.grow, ease: M.ease, immediateRender: false }, at); });
      if (totalEl) tl.fromTo(totalEl, { claimText: { from: 0, to: 0, fmt: fmtOf(o, dec) } }, { claimText: { from: 0, to: total.value, fmt: fmtOf(o, dec) }, duration: S.span, ease: M.ease, immediateRender: false }, S.growAt);
    });
  }

  function manifest() { return charts.map(c => ({ id: c.id, kind: c.kind, start: c.start, end: c.end, land: c.land, refs: c.refs })); }

  /* ---------- node: gate hook + selftest ---------- */
  function checkFiles(claimsPath, files, fs) {
    const claims = JSON.parse(fs.readFileSync(claimsPath, 'utf8')), V = (claims.values && typeof claims.values === 'object') ? claims.values : {};
    const missing = [], found = [];
    files.forEach(f => { const src = fs.readFileSync(f, 'utf8'); const re = /\b(?:claim|total)\s*:\s*(['"])([^'"\n]+)\1/g; let m;
      while ((m = re.exec(src))) { const id = m[2], line = src.slice(0, m.index).split('\n').length; (V[id] === undefined ? missing : found).push({ file: f, line, id }); } });
    return { values: Object.keys(V).length, found: found.length, missing };
  }
  function selftest() {
    const out = [], fail = m => out.push('FAIL ' + m), ok = m => out.push('ok   ' + m);
    const claims = { values: { a: { value: 12.4, unit: '%', source: 'row West' }, b: 7, c: { value: 1204, unit: '', source: 'count' }, tot: 1223 } };
    (resolve('a', claims).value === 12.4 && resolve('b', claims).value === 7 ? ok : fail)('resolve: object and plain-number claims');
    let threw = false; try { resolve('nope', claims); } catch (e) { threw = /not in claims\.json/.test(e.message); } (threw ? ok : fail)('resolve throws on an untraceable value');
    (fmt(12.4, { dec: 1, unit: '%' }) === '12.4%' && fmt(1204) === '1,204' && fmt(3.5, { unit: '$' }) === '$3.5' ? ok : fail)('fmt: 12.4% · 1,204 · $3.5');
    const T = ticks(12.4, 4); (T.step === 2.5 && T.top === 12.5 ? ok : fail)('ticks: max 12.4 → step 2.5, top 12.5 (got ' + T.step + '/' + T.top + ')');
    (ticks(1204, 4).step === 250 && ticks(1204, 4).top === 1250 ? ok : fail)('ticks: max 1204 → step 250, top 1250');
    let g = false; try { guardText('up 12.4% this week', true, 'legend'); } catch (e) { g = true; } (g ? ok : fail)('strict text guard refuses "12.4%" in free text');
    (guardText('Q3 2025, week 12', true, 'legend') === 'Q3 2025, week 12' ? ok : fail)('strict text guard allows Q3 / 2025 / week 12');
    const refs = [resolve('a', claims), resolve('b', claims)], L = barsLayout({ w: 640, h: 360, legend: 'x' }, refs);
    (Math.abs(L.bars[0].h - L.ph * 12.4 / 12.5) < 1e-9 && Math.abs(L.bars[0].y + L.bars[0].h - L.base) < 1e-9 ? ok : fail)('bars layout grows from the baseline to value/top');
    const plan = racePlan({ series: [{ name: 'N' }, { name: 'S' }, { name: 'W' }], periods: [{ label: 'Jan', values: { N: 'b', S: 'a', W: 'c' } }, { label: 'Feb', values: { N: 'c', S: 'b', W: 'a' } }] }, claims);
    (plan.periods[0].rank.join('') === '210' && plan.periods[1].rank.join('') === '021' ? ok : fail)('race ranks: Jan W>S>N, Feb N>W>S (got ' + plan.periods.map(p => p.rank.join('')).join(' ') + ')');
    const n = 4, land = 10, span = M.grow + M.stagger * (n - 1); (Math.abs(land - span - (land - 0.78)) < 1e-9 ? ok : fail)('schedule: 4 marks land at 10.0 → grow starts 9.22 (0.6 + 3×0.06)');
    const sched = schedule({ id: 'x', land: 10 }, 4); (Math.abs(sched.start - (10 - span - M.lead)) < 1e-9 ? ok : fail)('schedule: frame arrives 0.45 s before the first mark');
    const bad = out.filter(l => l.startsWith('FAIL')).length; return { ok: bad === 0, lines: out, failures: bad };
  }
  function cli(argv) {
    const fs = require('fs');
    if (!argv.length || argv.includes('--help') || argv.includes('-h')) { console.log('charts.js — data-truth charts\n  node lib/charts.js --check claims.json <authored files…>   every claim:/total: ref must exist in claims.json values\n  node lib/charts.js --selftest\n  exit 0 ok · 1 findings · 2 usage'); return argv.length ? 0 : 2; }
    if (argv.includes('--selftest')) { const r = selftest(); console.log(r.lines.join('\n')); console.log(JSON.stringify({ selftest: 'charts.js', ok: r.ok, failures: r.failures })); return r.ok ? 0 : 1; }
    if (argv.includes('--check')) {
      const i = argv.indexOf('--check'), claimsPath = argv[i + 1], files = argv.slice(i + 2).filter(f => !f.startsWith('--'));
      if (!claimsPath || !fs.existsSync(claimsPath) || !files.length) { console.error('usage: --check claims.json <files…>'); return 2; }
      const r = checkFiles(claimsPath, files.filter(f => fs.existsSync(f)), fs); console.log(JSON.stringify(r, null, 1)); return r.missing.length ? 1 : 0;
    }
    console.error('usage: --check claims.json <files…> | --selftest | --help'); return 2;
  }

  const CHART = { use, resolve, fmt, ticks, niceStep, bars, line, kpiTiles, race, donut, manifest, racePlan, barsLayout, guardText, checkFiles, selftest, PAL, SERIES, M };
  root.CHART = CHART;
  if (typeof module !== 'undefined' && module.exports) { module.exports = CHART; if (require.main === module) process.exit(cli(process.argv.slice(2))); }
})(typeof window !== 'undefined' ? window : globalThis);
