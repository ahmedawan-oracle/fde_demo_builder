/* seams.js — velocity-matched seams as pure functions of the film clock t (seconds).
   Namespace: window.SEAM (browser) / module.exports (node, for export_timeline.js and tests).

   The law (references/motion-doctrine.md): how a scene leaves decides how the next one arrives —
   same axis, same signed direction, matched speed through mirrored eases (exit power4.in, entry
   power4.out), and the cut lands mid-flight on both sides. Partial travel (~12 % of the frame,
   153.6 px on the 1280 stage), never a full off-screen slide; never a crossfade.

   Every helper returns plain state objects for the two sides of a cut:
       { out: {x, y, s, op, blur, visible}, in: {x, y, s, op, blur, visible}, phase: 'before'|'after'|'idle' }
   x/y in stage px, s = scale, op = opacity, blur in px. `visible` is false for the incoming side
   before the cut and for the outgoing side from the cut frame on (zero overlap: one side per frame).
   The scene applies a state with SEAM.applyLayer(el, st) (idempotent) or composes it into its own
   camera transform via SEAM.offset(t, selector) for a wrapper it already drives (#camera).

   Ledger: SEAM.build(rows, TX) resolves one row per cut (cut = seconds or a cue expression such as
   "wt('ask','question') + 0.1" or "P.close"), SEAM.validate() lints the vector plan, SEAM.state(t)
   evaluates every active seam, SEAM.apply(t) writes them. gates/seam_gate.py reads the same rows.

   Nothing here touches the DOM except applyLayer/apply. No wall clock, no randomness. */
(function (root) {
  'use strict';

  /* ---------- maths ---------- */
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rmp = (t, a, b) => (b <= a ? (t >= b ? 1 : 0) : clamp((t - a) / (b - a), 0, 1));
  const lerp = (a, b, x) => a + (b - a) * x;

  /* eases (x in 0..1). "in" accelerates, "out" decelerates. Pops use EP3O or BACK_O(1.4–1.7);
     bounce and elastic are not offered on purpose (the most common amateur tell). */
  const EP2I = x => x * x;
  const EP2O = x => 1 - (1 - x) * (1 - x);
  const EP3I = x => x * x * x;
  const EP3O = x => 1 - Math.pow(1 - x, 3);
  const EP4I = x => x * x * x * x;
  const EP4O = x => 1 - Math.pow(1 - x, 4);
  const EXPO_O = x => (x >= 1 ? 1 : x <= 0 ? 0 : 1 - Math.pow(2, -10 * x));
  const BACK_O = (s = 1.5) => x => { const y = x - 1; return 1 + (s + 1) * y * y * y + s * y * y; };
  const EASES = { 'power2.in': EP2I, 'power2.out': EP2O, 'power3.in': EP3I, 'power3.out': EP3O,
    'power4.in': EP4I, 'power4.out': EP4O, 'expo.out': EXPO_O, linear: x => clamp(x, 0, 1) };

  const STAGE = [1280, 720];
  const FPS = 30, F = 1 / FPS;
  const TRAVEL = 0.12 * STAGE[0];                      // 153.6 px — the 230 px of a 1920 frame
  const VIS = 0.04;                                    // below this opacity a side counts as invisible

  const rest = () => ({ x: 0, y: 0, s: 1, op: 1, blur: 0, visible: true });
  const gone = () => ({ x: 0, y: 0, s: 1, op: 0, blur: 0, visible: false });
  const axisXY = (axis, d) => (axis === 'y' ? { x: 0, y: d } : { x: d, y: 0 });

  /* ---------- 1. cut-the-curve: the default boundary, riding the current ----------
     Exit: power4.in over exitDur (0.34 s) across `travel` (12 % of the frame), opacity power3.in to 0
     so the card is still ~27 % present one frame before the cut and gone on it (stamp form). Entry:
     ignites at inOp (0.35) `travel` off-centre and decelerates on power4.out over entryDur (0.42 s,
     entry >= exit). fadeFrac < 1 shortens the fade to that fraction of the exit (hand form, 0.3 =
     "gone by 30 % of the travel") — only for word cascades where the next word already moves. */
  const CUT_CURVE = { axis: 'x', dir: -1, travel: TRAVEL, entryTravel: TRAVEL, exitDur: 0.34, entryDur: 0.42,
    fadeFrac: 1, fadeEase: EP3I, inOp: 0.35, blur: 0 };
  function cutCurve(t, cut, o) {
    const p = Object.assign({}, CUT_CURVE, o || {});
    if (t < cut - p.exitDur || t >= cut + p.entryDur) return { out: t < cut ? rest() : gone(), in: t < cut ? gone() : rest(), phase: 'idle' };
    if (t < cut) {
      const u = rmp(t, cut - p.exitDur, cut), e = EP4I(u), d = p.dir * p.travel * e;
      const fu = rmp(u, 0, p.fadeFrac), op = 1 - p.fadeEase(fu);
      return { out: Object.assign(rest(), axisXY(p.axis, d), { op, blur: p.blur * e, visible: op > VIS }), in: gone(), phase: 'before' };
    }
    const u = rmp(t, cut, cut + p.entryDur), e = EP4O(u), d = -p.dir * p.entryTravel * (1 - e);
    return { out: gone(), in: Object.assign(rest(), axisXY(p.axis, d), { op: lerp(p.inOp, 1, e), blur: p.blur * (1 - e), visible: true }), phase: 'after' };
  }

  /* ---------- 2/3. zoom-through (push, z+1) and inverse zoom-through (pull, z-1) ----------
     Push: exit scale 1 -> 1.2 on power3.in over 0.2 s, blur 0 -> blur px on the same curve, opacity on
     its own LINEAR fade to 0.15; hard swap; entry 0.75 -> 1 on expo.out over 0.5 s from 0.15 opacity.
     Pull (arrival beats only): 1 -> 0.8 then 1.25 -> 1, ~0.7 s split 30/70. blur: 10 px for text,
     18 px for a full-frame surface (never more). d(scale)/dt keeps one sign across the cut. */
  const ZOOM = { exitDur: 0.2, entryDur: 0.5, blur: 10, floor: 0.15, exitTo: 1.2, entryFrom: 0.75 };
  const ZOOM_INV = { exitDur: 0.21, entryDur: 0.49, blur: 10, floor: 0.15, exitTo: 0.8, entryFrom: 1.25 };
  function zoomSeam(t, cut, p) {
    if (t < cut - p.exitDur || t >= cut + p.entryDur) return { out: t < cut ? rest() : gone(), in: t < cut ? gone() : rest(), phase: 'idle' };
    if (t < cut) {
      const u = rmp(t, cut - p.exitDur, cut), e = EP3I(u), op = lerp(1, p.floor, u);
      return { out: Object.assign(rest(), { s: lerp(1, p.exitTo, e), blur: p.blur * e, op, visible: op > VIS }), in: gone(), phase: 'before' };
    }
    const u = rmp(t, cut, cut + p.entryDur), e = EXPO_O(u);
    return { out: gone(), in: Object.assign(rest(), { s: lerp(p.entryFrom, 1, e), blur: p.blur * (1 - e), op: lerp(p.floor, 1, e), visible: true }), phase: 'after' };
  }
  const zoomThrough = (t, cut, o) => zoomSeam(t, cut, Object.assign({}, ZOOM, o || {}));
  const inverseZoom = (t, cut, o) => zoomSeam(t, cut, Object.assign({}, ZOOM_INV, o || {}));

  /* ---------- 2b. combined lateral + pull ("both shrink") ----------
     For a beat that must land on the whole screen (establish rule) after a pushed-in beat: the outgoing
     slides 12 % on the current and pulls 1 -> 0.92, the incoming arrives at 1.08 and retracts to 1.
     Both sides shrink, so the z sign agrees and the x vector rides the current. */
  const COMBINED = Object.assign({}, CUT_CURVE, { exitTo: 0.92, entryFrom: 1.08 });
  function combined(t, cut, o) {
    const p = Object.assign({}, COMBINED, o || {}), st = cutCurve(t, cut, p);
    if (st.phase === 'before') st.out.s = lerp(1, p.exitTo, EP4I(rmp(t, cut - p.exitDur, cut)));
    if (st.phase === 'after') st.in.s = lerp(p.entryFrom, 1, EP4O(rmp(t, cut, cut + p.entryDur)));
    return st;
  }

  /* ---------- 5. rack-focus blur-cut: the one seam meant to be seen ----------
     Same surface, new state. The outgoing stays fully opaque, defocuses to `peak` (8–12 px, never
     > 18) with ~1.06 lens breathing on power2.in; the swap lands at peak blur; the incoming refocuses
     on power2.out (entry >= exit), continuing the scale sign (1/scale -> 1) and the small lateral
     drift `dx` in the same direction. At most once per ~8 s, never mid-caption. */
  const RACK = { peak: 12, scale: 1.06, dx: 80, axis: 'x', dir: -1, exitDur: 0.30, entryDur: 0.36 };
  function rackFocus(t, cut, o) {
    const p = Object.assign({}, RACK, o || {});
    p.peak = Math.min(p.peak, 18);
    if (t < cut - p.exitDur || t >= cut + p.entryDur) return { out: t < cut ? rest() : gone(), in: t < cut ? gone() : rest(), phase: 'idle' };
    if (t < cut) {
      const e = EP2I(rmp(t, cut - p.exitDur, cut));
      return { out: Object.assign(rest(), axisXY(p.axis, p.dir * p.dx * e), { s: lerp(1, p.scale, e), blur: p.peak * e, op: 1, visible: true }), in: gone(), phase: 'before' };
    }
    const e = EP2O(rmp(t, cut, cut + p.entryDur));
    return { out: gone(), in: Object.assign(rest(), axisXY(p.axis, -p.dir * p.dx * (1 - e)), { s: lerp(1 / p.scale, 1, e), blur: p.peak * (1 - e), op: 1, visible: true }), phase: 'after' };
  }

  /* ---------- 4. waterfall cut: cut-the-curve per word (recreated text beats only) ----------
     Outgoing words leave in reading order, each 0.34 s power4.in across 12 % with a 0.18 s linear
     fade, staggered 0.022 s; the LAST word's fade ends 0.02 s before the cut so it still streaks when
     the first incoming word ignites. Incoming words start at the cut with gaps 0.05 s shrinking by
     0.84 per word, each 0.30 s power4.out from 0.35 opacity, pre-set 12 % off on the far side.
     Returns { out: [state…], in: [state…], phase }. */
  const WATERFALL = { axis: 'x', dir: -1, travel: TRAVEL, exitDur: 0.34, exitFade: 0.18, exitStagger: 0.022,
    lastFadeEnd: 0.02, entryDur: 0.30, inOp: 0.35, gap0: 0.05, decay: 0.84 };
  function waterfallCut(t, cut, nOut, nIn, o) {
    const p = Object.assign({}, WATERFALL, o || {});
    const outs = [], ins = [];
    const lastStart = cut - p.lastFadeEnd - p.exitFade;
    for (let i = 0; i < nOut; i++) {
      const st = lastStart - (nOut - 1 - i) * p.exitStagger;
      if (t < st) { outs.push(rest()); continue; }
      const u = rmp(t, st, st + p.exitDur), op = 1 - rmp(t, st, st + p.exitFade);
      const vis = t < cut && op > VIS;
      outs.push(Object.assign(rest(), axisXY(p.axis, p.dir * p.travel * EP4I(u)), { op: vis ? op : 0, visible: vis }));
    }
    let st = cut, gap = p.gap0;
    for (let i = 0; i < nIn; i++) {
      if (t < st) ins.push(Object.assign(gone(), axisXY(p.axis, -p.dir * p.travel)));
      else { const e = EP4O(rmp(t, st, st + p.entryDur)); ins.push(Object.assign(rest(), axisXY(p.axis, -p.dir * p.travel * (1 - e)), { op: lerp(p.inOp, 1, e), visible: true })); }
      st += gap; gap *= p.decay;
    }
    return { out: outs, in: ins, phase: t < cut ? 'before' : 'after', entryEnd: st - gap / p.decay + p.entryDur };
  }

  /* ---------- 6. waterfall entry: arrival cascade (snaps, never fades) ----------
     items = [{w:'heavy'|'word'|'light'|'frag', dy?, dur?}]: each element becomes visible on its start
     frame (opacity 0 -> 1, binary) and whips from `dy` below to rest on power4.out. Weight table
     (30 fps): heavy 70 px / 0.18 s then a 1-frame gap; word 45 px / 0.15 s overlapping 1 frame;
     light 40 px / 0.12 s overlapping 2 frames; frag (a split final word) 70 px / 0.16 s overlapping
     1 frame. nextStart = prevStart + prevDur - overlapFrames/30. The total stagger (first start to
     last start) is capped at `cap` (0.5 s): a longer group has its per-item delays tightened
     proportionally, durations untouched. One direction per cascade; key t0 to wt() so the wave lands
     with the spoken words. Returns [{y, visible, u, t0}] with .end and .stagger. */
  const WEIGHT = { heavy: { dy: 70, dur: 0.18, next: -1 }, word: { dy: 45, dur: 0.15, next: 1 },
    light: { dy: 40, dur: 0.12, next: 2 }, frag: { dy: 70, dur: 0.16, next: 1 } };
  function cascadeSchedule(t0, items, cap = 0.5) {
    let st = t0; const S = [];
    items.forEach(it => {
      const w = WEIGHT[it.w] || WEIGHT.word, dur = it.dur || w.dur;
      S.push({ t0: st, dur, dy: it.dy !== undefined ? it.dy : w.dy });
      st = st + dur - (it.next !== undefined ? it.next : w.next) * F;
    });
    const span = S.length ? S[S.length - 1].t0 - t0 : 0;
    if (cap && span > cap) S.forEach(s => { s.t0 = t0 + (s.t0 - t0) * cap / span; });
    S.end = S.length ? Math.max.apply(null, S.map(s => s.t0 + s.dur)) : t0;
    S.stagger = S.length ? S[S.length - 1].t0 - t0 : 0;
    return S;
  }
  function cascade(t, t0, items, o) {
    const dirSign = (o && o.from === 'above') ? -1 : 1, S = cascadeSchedule(t0, items, o && o.cap !== undefined ? o.cap : 0.5);
    const out = S.map(s => { const u = rmp(t, s.t0, s.t0 + s.dur), on = t >= s.t0;
      return { y: on ? dirSign * s.dy * (1 - EP4O(u)) : dirSign * s.dy, visible: on, u, t0: s.t0 }; });
    out.end = S.end; out.stagger = S.stagger; return out;
  }

  /* ---------- 7. nudge curve: slow-fast-slow group slide (no cut) ----------
     Three segments on one property: power3.in ramp (~10 % of the distance in ~20 % of the time), a
     LINEAR burst (~65 % in ~18 %, about twice the average speed — reveal new content here, the speed
     masks it), a power4.out tail (~25 % in ~62 %, >= 3x the ramp in time). Reference: 270 px in
     0.57 s = -30 @0.12 s, -210 @0.22 s, -270 @0.57 s. Returns the signed offset. */
  const NUDGE = { d: [0.10, 0.65, 0.25], t: [0.20, 0.18, 0.62] };
  function nudge(t, t0, dist, dur = 0.57, ratios = NUDGE) {
    const d = ratios.d, r = ratios.t, t1 = t0 + dur * r[0], t2 = t1 + dur * r[1], t3 = t0 + dur;
    if (t <= t0) return 0;
    if (t < t1) return dist * d[0] * EP3I(rmp(t, t0, t1));
    if (t < t2) return dist * (d[0] + d[1] * rmp(t, t1, t2));
    return dist * (d[0] + d[1] + d[2] * EP4O(rmp(t, t2, t3)));
  }
  /* which segment t falls in: 0 before, 1 ramp, 2 burst (reveal here), 3 tail, 4 settled */
  function nudgePhase(t, t0, dur = 0.57, ratios = NUDGE) {
    const r = ratios.t, t1 = t0 + dur * r[0], t2 = t1 + dur * r[1], t3 = t0 + dur;
    return t < t0 ? 0 : t < t1 ? 1 : t < t2 ? 2 : t < t3 ? 3 : 4;
  }

  /* ---------- carriers: one concrete object handed across the cut ----------
     carrier(t, cut, {from, to, lead, tail}) interpolates a rect {x,y,w,h}: in the `lead` (0.3 s)
     before the cut it covers the first third of the path on power2.in; after the cut it finishes on
     power2.out over `tail` (0.6 s). Speeds match at the cut exactly (2/3 of lead == 2·2/3 / tail at
     the defaults). Both the outgoing card and the incoming scene place the element from this rect;
     the gate tolerance for a carrier is 12 px centre / 5 % size at cut ± 1 frame. */
  function carrier(t, cut, o) {
    const lead = o.lead || 0.3, tail = o.tail || 0.6, split = o.split || 1 / 3, A = o.from, B = o.to;
    const u = t < cut ? split * EP2I(rmp(t, cut - lead, cut)) : split + (1 - split) * EP2O(rmp(t, cut, cut + tail));
    const r = { x: lerp(A.x, B.x, u), y: lerp(A.y, B.y, u), u, side: t < cut ? 'out' : 'in' };
    if (A.w !== undefined) { r.w = lerp(A.w, B.w, u); r.h = lerp(A.h, B.h, u); }
    return r;
  }
  /* cursorHandoff: the cursor as carrier — two waypoint legs for G.cursorAt-style schedules */
  function cursorHandoff(cut, from, to, o) {
    const lead = (o && o.lead) || 0.3, tail = (o && o.tail) || 0.6, split = (o && o.split) || 1 / 3;
    const mid = { x: lerp(from.x, to.x, split), y: lerp(from.y, to.y, split) };
    return { legA: { t0: cut - lead, t1: cut, from, to: mid, ease: 'power2.in' },
      legB: { t0: cut, t1: cut + tail, from: mid, to, ease: 'power2.out' },
      at: t => carrier(t, cut, { from, to, lead, tail, split }) };
  }
  /* morphRect: a container docks into the next layout — uniform scale + radius over 0.6–1.2 s;
     old content gone in the first ~40 %, new content in the last ~40 %, anchor pixel-identical. */
  function morphRect(t, t0, dur, A, B, rA = 0, rB = 0, ease = EP3O) {
    const u = ease(rmp(t, t0, t0 + dur));
    return { x: lerp(A.x, B.x, u), y: lerp(A.y, B.y, u), w: lerp(A.w, B.w, u), h: lerp(A.h, B.h, u), r: lerp(rA, rB, u),
      oldOp: 1 - rmp(u, 0, 0.4), newOp: rmp(u, 0.6, 1), u };
  }

  /* ---------- stillness before climax: the comma between action and result ----------
     comma(t, action, {hold: 0.45, dwell: 1.0}) — the result lands `hold` (0.3–0.75 s) after the
     action and must stay >= `dwell` (1 s, 2 s for a dramatic beat). dwellOK(resultAt, shotEnd). */
  function comma(t, action, o) {
    const hold = (o && o.hold) || 0.45, dwell = (o && o.dwell) || 1.0, resultAt = action + hold;
    return { resultAt, dwellEnd: resultAt + dwell, waiting: t >= action && t < resultAt, landed: t >= resultAt, u: rmp(t, action, resultAt) };
  }
  const dwellOK = (resultAt, shotEnd, dramatic) => shotEnd - resultAt >= (dramatic ? 2.0 : 1.0);

  /* ---------- idle, if unavoidable ----------
     Idle loops are banned as a way to fill time (name a route instead). When one is truly needed:
     amplitude 0.008–0.015 of scale (default 0.012), period 1.5–3 s, phase 0 at t0 (no jump), fades
     out over the last 20 % before t1 (a seam), scaled by 1/sqrt(N) concurrent idles. Returns scale. */
  function idle(t, t0, t1, o) {
    const amp = (o && o.amp) || 0.012, period = (o && o.period) || 2.2, N = (o && o.N) || 1;
    if (t < t0 || t >= t1) return 1;
    const fade = 1 - rmp(t, t1 - 0.2 * (t1 - t0), t1);
    return 1 + amp / Math.sqrt(N) * Math.sin(2 * Math.PI * (t - t0) / period) * fade;
  }

  /* ---------- the vector ledger ---------- */
  const VECTORS = {
    'x-1': 'the current (LEFT): next beat', 'x+1': 'against the current: needs a cause or a chapter',
    'y-1': 'reserved: elevation — a conclusion rises', 'y+1': 'descent: rare, needs a cause',
    'z+1': 'reserved: deeper into the same thought (zoom-through)', 'z-1': 'reserved: arrival — something bigger lands (inverse zoom)'
  };
  const RESERVED = ['y-1', 'z+1', 'z-1'];
  const CAUSES = ['click', 'chapter', 'impact'];
  const TECH = { 'cut-the-curve': cutCurve, 'zoom-through': zoomThrough, 'inverse zoom-through': inverseZoom,
    combined, 'rack-focus': rackFocus };
  /* shader seams (type 'gl'): no DOM transform here — the scene asks GL.cutTransition to draw the window;
     the ledger still owns the time so every gate treats it as a scheduled seam. split = share of dur before the cut. */
  const GL_SEAM = { dur: 0.3, split: 0.5 };
  const glWindow = r => { const d = r.dur === undefined ? GL_SEAM.dur : r.dur, s = r.split === undefined ? GL_SEAM.split : r.split; return { exitDur: d * s, entryDur: d * (1 - s) }; };
  const vkey = v => v.axis + (v.dir > 0 ? '+1' : '-1');

  /* resolve a cut: a number, or an expression over P.<phase>, P.<phase>_end, wt('phase','word'[,n]),
     FILM.<key> and arithmetic. Anything else throws (a typo must never fall back silently). */
  function resolveCut(expr, TX, FILM) {
    if (typeof expr === 'number') return expr;
    let s = String(expr);
    s = s.replace(/wt\(\s*'([^']+)'\s*,\s*'([^']+)'\s*(?:,\s*(\d+))?\s*\)/g, (m, ph, w, n) => {
      if (!TX) throw new Error('seam cut "' + expr + '" needs the timeline (TX)');
      const v = TX.wt(ph, w, n ? +n : 1);
      if (v === TX.P[ph] && !(TX.WORDS[ph] || []).some(x => TX.norm(x.w) === TX.norm(w))) throw new Error('seam cue wt(' + ph + ', ' + w + ') does not resolve');
      return String(v);
    });
    s = s.replace(/\bP\.([A-Za-z0-9_]+)/g, (m, k) => { if (!TX || TX.P[k] === undefined) throw new Error('seam cut "' + expr + '": unknown phase ' + k); return String(TX.P[k]); });
    s = s.replace(/\bFILM\.([A-Za-z0-9_]+)/g, (m, k) => { if (!FILM || typeof FILM[k] !== 'number') throw new Error('seam cut "' + expr + '": FILM.' + k + ' is not a number'); return String(FILM[k]); });
    if (!/^[\d.\s+\-*/()eE]+$/.test(s)) throw new Error('seam cut "' + expr + '" has unresolved tokens: ' + s);
    return Function('"use strict";return (' + s + ')')();
  }

  /* validate the plan (no DOM, no frames): returns {ok, errors[], warnings[]} */
  function validate(rows, o) {
    const errors = [], warnings = [], R = rows.slice().sort((a, b) => a.cut - b.cut), seen = {}, techs = new Set(), spent = {};
    R.forEach((r, i) => {
      const id = r.id || ('row ' + i), type = r.type || 'cut';
      if (typeof r.cut !== 'number' || !isFinite(r.cut)) errors.push(id + ': cut is not resolved to seconds');
      if (seen[r.cut]) errors.push(id + ': duplicate cut time ' + r.cut); seen[r.cut] = 1;
      if (type === 'gl') {
        // a shader seam (lib/shaders.js GL.cutTransition): the two sides are textures, the window is the transition
        if (!r.technique) errors.push(id + ': gl rows name the transition in technique (chromaSplit, warpDissolve, lightLeak, flashWhite, iris, slitScan, crossWarp)');
        const d = r.dur === undefined ? GL_SEAM.dur : r.dur;
        if (!(d >= 0.1 && d <= 0.5)) errors.push(id + ': gl seam dur ' + d + ' s is outside 0.1–0.5 s (a transition over footage never exceeds half a second)');
        if (r.technique) techs.add('gl:' + r.technique);
        if (/^(whip|zoom|cinematic)/i.test(r.technique || '') && CAUSES.indexOf(r.cause) < 0) errors.push(id + ': a whip/zoom shader seam needs a cause (click | chapter | impact)');
        return;
      }
      if (type !== 'cut') { if (!r.carrier || !r.carrier.out || !r.carrier.in) errors.push(id + ': ' + type + ' rows need carrier {out, in}'); return; }
      if (!r.exit || !r.entry) { errors.push(id + ': needs exit and entry vectors'); return; }
      for (const side of ['exit', 'entry']) {
        const v = r[side];
        if (!/^[xyz]$/.test(v.axis || '')) errors.push(id + ': ' + side + '.axis must be x, y or z');
        if (v.dir !== 1 && v.dir !== -1) errors.push(id + ': ' + side + '.dir must be +1 or -1');
      }
      if (r.exit.axis !== r.entry.axis) errors.push(id + ': exit/entry axis differ (' + r.exit.axis + ' vs ' + r.entry.axis + ') — fix the plan, not the ease');
      else if (r.exit.dir !== r.entry.dir) errors.push(id + ': exit/entry direction mirrored on ' + r.exit.axis + ' — fix the plan, not the ease');
      if (r.technique) techs.add(r.technique);
      if (r.technique === 'inverse zoom-through' && !(r.entry.axis === 'z' && r.entry.dir === -1)) errors.push(id + ': inverse zoom-through is z-1 (pull) by definition');
      if (r.technique === 'zoom-through' && !(r.entry.axis === 'z' && r.entry.dir === 1)) errors.push(id + ': zoom-through is z+1 (push) by definition');
      const k = vkey(r.entry);
      if (RESERVED.indexOf(k) >= 0) { const act = r.act || 'film'; (spent[act] = spent[act] || []).push(id + ' ' + k); }
      const prev = R.slice(0, i).reverse().find(q => (q.type || 'cut') === 'cut' && q.exit && q.entry);
      if (prev && prev.entry.axis === r.entry.axis && prev.entry.dir === -r.entry.dir && CAUSES.indexOf(r.cause) < 0)
        errors.push(id + ': ping-pong — reverses ' + (prev.id || 'the previous seam') + ' on ' + r.entry.axis + ' without a cause (click | chapter | impact)');
    });
    if (techs.size > 3) warnings.push('transition budget: ' + techs.size + ' seam techniques (' + Array.from(techs).join(', ') + '); a film repeats 2–3');
    Object.keys(spent).forEach(act => { if (spent[act].length > 1) warnings.push('act "' + act + '" spends ' + spent[act].length + ' reserved vectors (' + spent[act].join('; ') + '); one per act'); });
    return { ok: !errors.length, errors, warnings };
  }

  /* build: resolve cuts, attach the technique function, keep the rows for state()/apply()/toJSON() */
  let LEDGER = { rows: [], current: 'x-1', fps: FPS };
  function build(ledger, TX, FILM) {
    const rows = (ledger.seams || ledger.rows || ledger).map((r, i) => {
      const row = Object.assign({}, r, { cut: +resolveCut(r.cut, TX, FILM || root.FILM).toFixed(3) });
      row.type = row.type || 'cut'; row.id = row.id || ('seam ' + (i + 1));
      if (row.type === 'cut' && !row.technique) row.technique = 'cut-the-curve';
      if (row.type === 'cut' && row.technique !== 'waterfall' && !TECH[row.technique]) throw new Error(row.id + ': unknown technique ' + row.technique + ' (' + Object.keys(TECH).join(', ') + ', waterfall)');
      return row;
    }).sort((a, b) => a.cut - b.cut);
    LEDGER = { rows, current: ledger.current || 'x-1', fps: ledger.fps || FPS, stage: ledger.stage || STAGE };
    return LEDGER;
  }
  /* per-row options passed to the technique function (ledger `opts` plus axis/dir from the entry vector) */
  const rowOpts = r => Object.assign({ axis: r.entry.axis, dir: r.entry.dir }, r.opts || {});
  function rowState(r, t) {
    if (r.type !== 'cut' || r.technique === 'waterfall') return null;
    return TECH[r.technique](t, r.cut, rowOpts(r));
  }
  /* state(t): { selector: layerState } for every layer inside an active seam window at t */
  function state(t) {
    const out = {};
    for (const r of LEDGER.rows) {
      const st = rowState(r, t); if (!st || st.phase === 'idle') continue;
      if (r.exit && r.exit.selector) out[r.exit.selector] = Object.assign({ seam: r.id, side: 'out' }, st.out);
      if (r.entry && r.entry.selector) out[r.entry.selector] = Object.assign({ seam: r.id, side: 'in' }, st.in);
    }
    return out;
  }
  const offset = (t, selector) => state(t)[selector] || null;
  /* windows(): [{id, cut, t0, t1, technique, exit, entry}] — what export_timeline.js writes next to cuts */
  /* glSeams(): [{id, at, dur, name, cause}] — what a scene hands to GL.cutTransition, straight from the ledger */
  function glSeams() {
    return LEDGER.rows.filter(r => r.type === 'gl').map(r => { const w = glWindow(r); return { id: r.id, at: +(r.cut - w.exitDur).toFixed(3), dur: +(w.exitDur + w.entryDur).toFixed(3), split: r.split === undefined ? GL_SEAM.split : r.split, name: r.technique, cause: r.cause, opts: r.opts || {} }; });
  }
  function windows() {
    return LEDGER.rows.map(r => { const p = r.type === 'gl' ? glWindow(r) : r.type !== 'cut' ? { exitDur: 0, entryDur: 0 } : r.technique === 'waterfall' ? WATERFALL
      : r.technique === 'rack-focus' ? RACK : /zoom/.test(r.technique) ? (r.technique === 'zoom-through' ? ZOOM : ZOOM_INV) : CUT_CURVE;
      const o = Object.assign({}, p, r.opts || {});
      return { id: r.id, cut: r.cut, t0: +(r.cut - o.exitDur).toFixed(3), t1: +(r.cut + o.entryDur).toFixed(3), type: r.type, technique: r.technique,
        exit: r.exit, entry: r.entry, carrier: r.carrier, cause: r.cause, act: r.act }; });
  }
  const toJSON = () => ({ current: LEDGER.current, fps: LEDGER.fps, seams: windows() });

  /* ---------- DOM (browser only) ---------- */
  /* applyLayer(el, st): transform/opacity/filter from a state. Blur sits on the element and opacity on
     it too; when a layer has children that fade separately put the blur on the wrapper (headless Chrome
     composites blur + opacity on one element badly in some versions — keep windows short). Idempotent:
     the computed strings are cached on the element. */
  function applyLayer(el, st) {
    if (!el || !st) return;
    const tf = (st.x || st.y) || (st.s !== undefined && Math.abs(st.s - 1) > 1e-4)
      ? 'translate(' + (st.x || 0).toFixed(2) + 'px,' + (st.y || 0).toFixed(2) + 'px) scale(' + (st.s === undefined ? 1 : st.s).toFixed(4) + ')' : 'none';
    const op = st.visible === false ? '0' : clamp(st.op === undefined ? 1 : st.op, 0, 1).toFixed(3);
    const fl = st.blur > 0.05 ? 'blur(' + st.blur.toFixed(1) + 'px)' : 'none';
    if (el.__seamTf !== tf) { el.style.transform = tf; el.__seamTf = tf; }
    if (el.__seamOp !== op) { el.style.opacity = op; el.__seamOp = op; }
    if (el.__seamFl !== fl) { el.style.filter = fl; el.__seamFl = fl; }
  }
  /* apply(t, skip): write every active layer; `skip` lists selectors the scene composes itself (#camera) */
  function apply(t, skip) {
    if (typeof document === 'undefined') return {};
    const S = state(t), sk = skip || [];
    Object.keys(S).forEach(sel => { if (sk.indexOf(sel) >= 0) return; const el = document.querySelector(sel); if (el) applyLayer(el, S[sel]); });
    return S;
  }

  const SEAM = { clamp, rmp, lerp, EP2I, EP2O, EP3I, EP3O, EP4I, EP4O, EXPO_O, BACK_O, EASES, STAGE, TRAVEL, VIS, FPS,
    CUT_CURVE, ZOOM, ZOOM_INV, COMBINED, RACK, WATERFALL, WEIGHT, NUDGE, VECTORS, RESERVED, CAUSES,
    cutCurve, zoomThrough, inverseZoom, combined, rackFocus, waterfallCut, cascade, cascadeSchedule, nudge, nudgePhase,
    carrier, cursorHandoff, morphRect, comma, dwellOK, idle,
    GL_SEAM, glSeams, resolveCut, validate, build, state, offset, windows, toJSON, applyLayer, apply, ledger: () => LEDGER };
  if (typeof module !== 'undefined' && module.exports) module.exports = SEAM;
  root.SEAM = SEAM;
})(typeof window !== 'undefined' ? window : globalThis);
