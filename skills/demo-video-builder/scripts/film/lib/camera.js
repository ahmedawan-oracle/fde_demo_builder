/* camera.js — CAM: camera moves beyond the sine push, as pure functions of the film clock t (seconds).

   Additive to lib/grammar.js (G.camState / G.applyCam stay untouched) and to lib/footage.js (its shot fields
   keep their meaning; CAM only understands MORE of them). Nothing here reads the wall clock, nothing is
   random, and the only DOM writes are the documented apply* setters, each of which writes every property it
   owns on every call (seek-safe: a frame never depends on the frame before it).

   What it adds (numbers are the measured rules in references/camera-moves.md):
     eases       power2/3/4 out ('p2','p3','p4'), 'expo', in-eases for exits ('p2in','p3in','p4in'), inOut
                 ('p2io','p3io'), plus footage.js's 'io' (sine in-out) and 'out' (sine out, the default)
     pose        CAM.resolve(sh, t, ctx): s0/c0 + moves with named eases + revealOut + punches + caret follow
                 + idle drift + the stage clamp — a superset of footage.js camFor
     punch       CAM.punchTo / CAM.punchOut: 0.14–0.25 s power4.out hard reframe, <= +25 % scale, hold >= 0.8 s
     whip        CAM.whip: lateral smear hand-off between two real screens (nudge curve 10/65/25 over
                 20/18/62, blur 0 -> 18 -> 0 on 'X 0'); CAM.zoomThrough and CAM.connector are the other accents
     match cut   CAM.matchCut solves the incoming s0/c0 so a shared element lands on the same stage rect;
                 CAM.velocityMatch continues an in-progress move across the cut with a power2.out entry
     focus pull  CAM.focus / CAM.rack: blur + dim everything except a rect (blur 16, dim 0.55, never < 0.35)
     dolly zoom  CAM.dolly: perspective P(t) = subjectScale * d(t), rig translateZ(P - d); recreated cards only
     reveal out  sh.revealOut = {s0, c0, at, dur, ease:'expo'}: open tight, one outward pull, lock
     caret       CAM.followCaret / CAM.caretX: pin the typed caret at ~60 % of the frame, min()-continuous
     ladder      CAM.ladder / CAM.lint: pose ladder per shot + dwell / ease-law / verb-variety lint
     budget      CAM.fitScale / CAM.pushToFit / CAM.upsample / CAM.budget: 88 % headroom, upsample warn 1.6 fail 2.0
     idle        CAM.idle (Lissajous, ratio 1.3) and CAM.pushLong (ease window longer than the shot)
     hit         CAM.hit: flash 0.55 -> 0 over 0.28 s, dressing settles to 0.75, +2 % snap
     streak      CAM.speed / CAM.streak / CAM.travelBlur: directional blur that rides the camera speed
     trace       CAM.trace: 30 fps camera curves + scheduled-motion windows for gates/motion_diag.py
     frames      CAM.frameIdx / CAM.stepHold: quantize stepped effects on the integer frame index

   Node CLI (same require() chain as export_timeline.js; run after gen_vo_multivoice.py every time):
     node scenes/lib/camera.js --curves scenes/timing_<name>_data.js scenes/shots.js broll/clips.js [--out out] [--fps 30]
       -> out/camera_curves.json  per-shot samples {t,s,cx,cy}, speed px/frame, windows of scheduled motion
       -> out/camera_report.json  pose ladder, lint items (WARN/FAIL), zoom budget per shot, seq schedules
       exit 1 when any lint item is a FAIL or any shot exceeds the zoom budget. */
(function (root) {
  'use strict';
  const G = root.G || {};
  const clamp = G.clamp || ((x, a, b) => Math.max(a, Math.min(b, x)));
  const rmp = G.rmp || ((t, a, b) => clamp((t - a) / (b - a), 0, 1));
  const lerp = G.lerp || ((a, b, x) => a + (b - a) * x);
  const STAGE = [1280, 720];

  /* ---------- eases (u in 0..1) ---------- */
  const EZ = x => Math.sin(clamp(x, 0, 1) * Math.PI / 2);                      // sine-out  (footage default)
  const EIO = x => 0.5 - 0.5 * Math.cos(clamp(x, 0, 1) * Math.PI);             // sine-in-out (footage 'io')
  const P2 = x => 1 - Math.pow(1 - clamp(x, 0, 1), 2);                        // power2.out
  const P3 = x => 1 - Math.pow(1 - clamp(x, 0, 1), 3);                        // power3.out (browser scroll)
  const P4 = x => 1 - Math.pow(1 - clamp(x, 0, 1), 4);                        // power4.out (punch, dive, landing)
  const EXPO = x => (x = clamp(x, 0, 1)) >= 1 ? 1 : 1 - Math.pow(2, -10 * x);  // expo.out (reveal pull)
  const P2IN = x => Math.pow(clamp(x, 0, 1), 2), P3IN = x => Math.pow(clamp(x, 0, 1), 3), P4IN = x => Math.pow(clamp(x, 0, 1), 4);
  const P2IO = x => (x = clamp(x, 0, 1)) < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
  const P3IO = x => (x = clamp(x, 0, 1)) < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  const LIN = x => clamp(x, 0, 1);
  const EASE = { out: EZ, io: EIO, p2: P2, p3: P3, p4: P4, expo: EXPO, p2in: P2IN, p3in: P3IN, p4in: P4IN, p2io: P2IO, p3io: P3IO, lin: LIN };
  /* ease name or function -> function; unknown names fall back to the footage default (sine-out) */
  const easeOf = e => typeof e === 'function' ? e : (EASE[e] || EZ);

  /* ---------- measured rules (defaults for every helper and for the lint) ---------- */
  const RULES = {
    punch: { dur: 0.22, durMin: 0.14, durMax: 0.25, maxGain: 0.25, hold: 0.8, gap: 1.0 },
    zoom: { durMin: 0.5, teleport: 0.8, durMax: 2.5, dwell: 1.0, heroDwell: 1.5, startAfter: 0.5 },
    headroom: 0.88,
    budget: { warn: 1.6, fail: 2.0, outW: 1920 },
    whip: { dur: 0.45, peak: 18, cap: 24, dist: [0.10, 0.65, 0.25], time: [0.20, 0.18, 0.62] },
    zoomThrough: { dur: 0.4, outScale: 2.2, inScale: 0.6, blur: 8, offset: 0.15 },
    connector: { stretch: 0.12, sx: 1.35, sy: 0.92, blur: 14, switchAt: 0.14, recover: 0.18 },
    focus: { blur: 16, soft: 8, heavy: 24, dim: 0.55, dimMin: 0.35, dur: 0.8, release: 0.3 },
    dolly: { d0: 1400, d0Min: 600, d0Max: 3000, ratio: 2, ratioMin: 1.1, ratioMax: 4, dur: 4 },
    idle: { ax: 5, ay: 2.5, ratio: 1.3, cycles: 1, ds: 0.01, footageMax: 0.01 },
    hit: { flash: 0.55, flashDur: 0.28, settle: 0.75, settleAt: 0.35, settleDur: 0.35, snap: 1.02, snapDur: 0.14 },
    streak: { peak: 18, cap: 20, min: 24 },
    seams: { maxKinds: 2, accentShare: 0.25 },
    onion: { samples: 9, maxSamples: 60, alphaLo: 0.14 }
  };

  /* ---------- pose: {s, cx, cy} on the 1280x720 stage ---------- */
  /* the stage clamp applyCam performs (so budgets, curves and seams see the camera that is really rendered) */
  function clampPose(p, stage) {
    const W = (stage || STAGE)[0], H = (stage || STAGE)[1];
    if (p.s < 1.0005) return { s: 1, cx: W / 2, cy: H / 2 };
    const hw = W / 2 / p.s, hh = H / 2 / p.s;
    return { s: p.s, cx: clamp(p.cx, hw, W - hw), cy: clamp(p.cy, hh, H - hh) };
  }
  /* the moves a shot really runs: authored moves + the single revealOut pull (appended, abs) */
  function movesOf(sh) {
    const M = (sh.moves || []).slice();
    if (sh.revealOut) { const r = sh.revealOut; M.push({ t0: r.at, dur: r.dur, s: 1, c: [640, 360], ease: r.ease || 'expo', abs: true, reveal: true }); }
    return M;
  }
  function startPose(sh) {
    if (sh.revealOut) return { s: sh.revealOut.s0, cx: sh.revealOut.c0[0], cy: sh.revealOut.c0[1] };
    return { s: sh.s0 || 1, cx: (sh.c0 || [640, 360])[0], cy: (sh.c0 || [640, 360])[1] };
  }
  /* raw camera of a shot at t: same sequential-lerp semantics as footage.js camFor, plus named eases, revealOut,
     punches (moves with ease 'p4' / punch:true), drift. No clamp, no idle, no caret follow. */
  function pose(sh, t) {
    const p = startPose(sh); let s = p.s, cx = p.cx, cy = p.cy;
    for (const m of movesOf(sh)) { const u = easeOf(m.ease)(rmp(t, m.t0, m.t0 + m.dur)); s = lerp(s, m.s, u); cx = lerp(cx, m.c[0], u); cy = lerp(cy, m.c[1], u); }
    if (sh.drift) s += (t - sh.t0) * sh.drift;
    return { s, cx, cy };
  }
  /* the camera to render: pose + caret follow (ctx.caretX, stage px before the camera) + idle + clamp.
     ctx: {caretX, stage}. sh.idle = {ax, ay, ratio, cycles, ds} (footage: keep ds <= 0.01). */
  function resolve(sh, t, ctx) {
    ctx = ctx || {};
    let p = pose(sh, t);
    if (sh.followCaret && typeof ctx.caretX === 'number') p = followCaret(p, ctx.caretX, sh.followCaret, ctx.stage);
    if (sh.idle) p = withIdle(p, idle(t, sh.t0, Object.assign({ dur: (sh.t1 || sh.t0 + 6) - sh.t0 }, sh.idle)));
    return clampPose(p, ctx.stage);
  }
  /* write a pose onto the camera wrapper (same transform form as G.applyCam: translate then scale, origin 0 0).
     opts.streakNode: an <feGaussianBlur> to receive opts.streak ('X 0' string) — '0 0' when absent. */
  function applyPose(el, p, opts) {
    opts = opts || {}; const W = (opts.stage || STAGE)[0], H = (opts.stage || STAGE)[1], q = clampPose(p, opts.stage);
    el.style.transform = q.s < 1.0005 ? 'none' : `translate(${(W / 2 - q.s * q.cx).toFixed(2)}px,${(H / 2 - q.s * q.cy).toFixed(2)}px) scale(${q.s.toFixed(4)})`;
    if (opts.streakNode) opts.streakNode.setAttribute('stdDeviation', opts.streak || '0 0');
    return q;
  }

  /* ---------- punch: near-instant reframe on the same subject (0.14–0.25 s power4.out, then hold >= 0.8 s) ---------- */
  /* rect [x,y,w,h] in stage px of the FULL screen (abs) — or of the shot's VIEW when abs=false (FOOT.fullscreen converts) */
  const punchTo = (t0, s, rect, dur, abs) => ({ t0, dur: dur || RULES.punch.dur, s, c: [rect[0] + rect[2] / 2, rect[1] + rect[3] / 2], ease: 'p4', punch: true, abs: abs !== false });
  const punchOut = (t0, dur) => ({ t0, dur: dur || RULES.punch.dur, s: 1, c: [640, 360], ease: 'p4', punch: true, abs: true });
  const isPunch = m => !!(m.punch || ((m.ease === 'p4' || m.ease === 'expo') && m.dur <= 0.3));

  /* ---------- zoom budget: headroom (88 %) and source-resolution cap ---------- */
  const fitScale = (rect, fill, stage) => { const W = (stage || STAGE)[0], H = (stage || STAGE)[1], f = fill || RULES.headroom; return Math.min(f * W / rect[2], f * H / rect[3]); };
  /* a push whose scale is derived from the rect (never larger than the headroom allows); rect in stage px (abs) */
  const pushToFit = (t0, dur, rect, fill, ease) => ({ t0, dur, s: fitScale(rect, fill), c: [rect[0] + rect[2] / 2, rect[1] + rect[3] / 2], ease: ease || 'io', abs: true, fit: rect.slice() });
  /* source pixels that span the 1280 stage for a clip (page bands can be narrower than the recording) */
  const sourceWidth = c => !c ? RULES.budget.outW : (c.kind === 'page' ? (c.chrome ? (c.frameW || 1920) : c.band[2]) : c.crop[2]);
  /* effective upsample of the recording's pixels on the output: s * outW / sourceWidth (1920-px recording at s=1 -> 1.0) */
  const upsample = (s, clip, outW) => s * (outW || RULES.budget.outW) / sourceWidth(clip);
  /* the camera scale at which the upsample reaches the cap (2.0 by default) */
  const maxScale = (clip, cap, outW) => (cap || RULES.budget.fail) * sourceWidth(clip) / (outW || RULES.budget.outW);
  /* per-shot budget: peak scale over the ladder, its upsample, level ok/warn/fail, headroom offenders (fit rects > 88 %) */
  function budget(sh, clip, opts) {
    opts = opts || {}; const warn = opts.warn || RULES.budget.warn, fail = opts.fail || RULES.budget.fail;
    let peak = startPose(sh).s, at = sh.t0;
    for (const m of movesOf(sh)) if (m.s > peak) { peak = m.s; at = m.t0 + m.dur; }
    if (sh.drift && sh.t1) { const sd = pose(sh, sh.t1 - 1 / 30).s; if (sd > peak) { peak = sd; at = sh.t1; } }
    const up = upsample(peak, clip, opts.outW);
    const head = movesOf(sh).filter(m => m.fit && Math.max(m.s * m.fit[2] / STAGE[0], m.s * m.fit[3] / STAGE[1]) > RULES.headroom + 1e-6).map(m => +m.t0.toFixed(2));
    return { peak: +peak.toFixed(4), at: +at.toFixed(3), upsample: +up.toFixed(3), maxScale: +maxScale(clip, fail, opts.outW).toFixed(3),
      level: up > fail ? 'fail' : up > warn ? 'warn' : 'ok', headroomFails: head };
  }

  /* ---------- whip-pan seam: lateral smear hand-off between two real screens ---------- */
  /* nudge curve: distance fraction as a function of time fraction x — ramp (power3.in, 10 % over 20 %),
     burst (linear, 65 % over 18 %), tail (power4.out, 25 % over 62 %); the tail is >= 3x the ramp in time */
  function nudge(x, o) {
    const D = (o && o.dist) || RULES.whip.dist, T = (o && o.time) || RULES.whip.time; x = clamp(x, 0, 1);
    if (x < T[0]) return D[0] * P3IN(x / T[0]);
    if (x < T[0] + T[1]) return D[0] + D[1] * (x - T[0]) / T[1];
    return D[0] + D[1] + D[2] * P4(( x - T[0] - T[1]) / T[2]);
  }
  /* blur envelope for the same x: 0 -> peak over the ramp (power3.in), peak through the burst, -> 0 over the tail (power4.out) */
  function whipBlur(x, peak, o) {
    const T = (o && o.time) || RULES.whip.time; x = clamp(x, 0, 1);
    if (x < T[0]) return peak * P3IN(x / T[0]);
    if (x < T[0] + T[1]) return peak;
    return peak * (1 - P4((x - T[0] - T[1]) / T[2]));
  }
  /* o: {t0, dur:0.45, dir:'left'|'right' (where the OUTGOING picture travels), peak:18, W:1280}
     -> {active, x (time fraction), u (distance), phase, xPrev, xNext (px), blur (px), swap (burst window: reveal here)} */
  function whip(t, o) {
    const dur = o.dur || RULES.whip.dur, W = o.W || STAGE[0], sign = o.dir === 'right' ? 1 : -1, peak = Math.min(o.peak || RULES.whip.peak, RULES.whip.cap);
    const x = rmp(t, o.t0, o.t0 + dur), T = RULES.whip.time;
    if (t < o.t0 || t >= o.t0 + dur) return { active: false, x: t < o.t0 ? 0 : 1, u: t < o.t0 ? 0 : 1, phase: t < o.t0 ? 'before' : 'done', xPrev: 0, xNext: 0, blur: 0, swap: false };
    const u = nudge(x, o);
    return { active: true, x, u, phase: x < T[0] ? 'ramp' : x < T[0] + T[1] ? 'burst' : 'tail', xPrev: sign * W * u, xNext: -sign * W * (1 - u),
      blur: whipBlur(x, peak, o), swap: x >= T[0] && x < T[0] + T[1] };
  }
  /* ---------- zoom-through accent: outgoing frame zooms out of focus while the incoming settles in ---------- */
  /* o: {t0, dur:0.4} -> {active, prev:{scale, blur, opacity}, next:{scale, blur}} */
  function zoomThrough(t, o) {
    const R = RULES.zoomThrough, dur = o.dur || R.dur, a = rmp(t, o.t0, o.t0 + dur), b = rmp(t, o.t0 + R.offset * dur, o.t0 + dur * (1 + R.offset));
    if (t < o.t0 || t >= o.t0 + dur * (1 + R.offset)) return { active: false, prev: { scale: 1, blur: 0, opacity: t < o.t0 ? 1 : 0 }, next: { scale: 1, blur: 0 } };
    const ua = P3IN(a), ub = P3(b);
    return { active: true, prev: { scale: lerp(1, R.outScale, ua), blur: R.blur * ua, opacity: 1 - ua }, next: { scale: lerp(R.inScale, 1, ub), blur: R.blur * (1 - ub) } };
  }
  /* ---------- hard-cut connector (freeze-hit's exit): 0.12 s stretch power3.in, switch at +0.14, recover 0.18 s power3.out ---------- */
  function connector(t, t0) {
    const R = RULES.connector, a = P3IN(rmp(t, t0, t0 + R.stretch)), r = P3(rmp(t, t0 + R.switchAt, t0 + R.switchAt + R.recover));
    const active = t >= t0 && t < t0 + R.switchAt + R.recover, k = t < t0 + R.switchAt ? a : 1 - r;
    return { active, switched: t >= t0 + R.switchAt, sx: lerp(1, R.sx, k), sy: lerp(1, R.sy, k), blur: R.blur * k };
  }
  /* sh.enter = {kind:'whip'|'zoomthrough'|'stretch', dir, dur, peak} evaluated at t */
  function seam(t, sh) {
    const e = sh && sh.enter; if (!e) return null;
    if (e.kind === 'whip') return Object.assign({ kind: 'whip' }, whip(t, Object.assign({ t0: sh.t0 }, e)));
    if (e.kind === 'zoomthrough') return Object.assign({ kind: 'zoomthrough' }, zoomThrough(t, Object.assign({ t0: sh.t0 }, e)));
    if (e.kind === 'stretch') return Object.assign({ kind: 'stretch' }, connector(t, sh.t0));
    return null;
  }
  /* when export_timeline should place the cut for QA sampling: whip at the burst, zoom-through at the midpoint, stretch at the switch */
  const seamCutAt = sh => !sh.enter ? sh.t0 : sh.enter.kind === 'whip' ? sh.t0 + 0.4 * (sh.enter.dur || RULES.whip.dur)
    : sh.enter.kind === 'zoomthrough' ? sh.t0 + 0.5 * (sh.enter.dur || RULES.zoomThrough.dur) : sh.t0 + RULES.connector.switchAt;
  /* seam duration (how long after t0 the picture is still in motion) */
  const seamDur = sh => !sh.enter ? 0 : sh.enter.kind === 'whip' ? (sh.enter.dur || RULES.whip.dur) : sh.enter.kind === 'zoomthrough'
    ? (sh.enter.dur || RULES.zoomThrough.dur) * (1 + RULES.zoomThrough.offset) : RULES.connector.switchAt + RULES.connector.recover;
  /* DOM setter for seams. els: {prev (img/wrapper holding the previous shot's last frame), next (the incoming clip wrapper),
     blurNode (<feGaussianBlur> of the filter on the element that wraps both)}. Writes every property every call. */
  function applySeam(els, st) {
    const P = els.prev && els.prev.style, N = els.next && els.next.style;
    if (!st || !st.active) {
      if (P) { P.display = 'none'; P.transform = 'none'; P.opacity = '1'; P.filter = 'none'; }
      if (N) { N.transform = 'none'; N.filter = 'none'; }
      if (els.blurNode) els.blurNode.setAttribute('stdDeviation', '0 0');
      return;
    }
    if (st.kind === 'whip') {
      if (P) { P.display = 'block'; P.transform = `translateX(${st.xPrev.toFixed(2)}px)`; P.opacity = '1'; P.filter = 'none'; }
      if (N) { N.transform = `translateX(${st.xNext.toFixed(2)}px)`; N.filter = 'none'; }
      if (els.blurNode) els.blurNode.setAttribute('stdDeviation', `${st.blur.toFixed(2)} 0`);
    } else if (st.kind === 'zoomthrough') {
      if (P) { P.display = st.prev.opacity > 0.002 ? 'block' : 'none'; P.transform = `scale(${st.prev.scale.toFixed(4)})`; P.opacity = st.prev.opacity.toFixed(3); P.filter = `blur(${st.prev.blur.toFixed(2)}px)`; }
      if (N) { N.transform = `scale(${st.next.scale.toFixed(4)})`; N.filter = st.next.blur > 0.05 ? `blur(${st.next.blur.toFixed(2)}px)` : 'none'; }
      if (els.blurNode) els.blurNode.setAttribute('stdDeviation', '0 0');
    } else if (st.kind === 'stretch') {
      if (P) { P.display = st.switched ? 'none' : 'block'; P.transform = 'none'; P.opacity = '1'; P.filter = 'none'; }
      if (N) { N.transform = 'none'; N.filter = 'none'; }
      if (els.blurNode) els.blurNode.setAttribute('stdDeviation', `${st.blur.toFixed(2)} ${(st.blur * 0.3).toFixed(2)}`);
      if (els.stage) els.stage.style.transform = `scale(${st.sx.toFixed(4)},${st.sy.toFixed(4)})`;
    }
    if (els.stage && st.kind !== 'stretch') els.stage.style.transform = 'none';
  }
  /* create (once) the SVG filter the seam/travel blur writes to; returns the <feGaussianBlur>. target gets filter:url(#id). */
  function ensureStreakFilter(doc, id, target) {
    id = id || 'camStreak'; let fe = doc.getElementById(id + 'Blur');
    if (!fe) {
      const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '0'); svg.setAttribute('height', '0'); svg.setAttribute('aria-hidden', 'true'); svg.style.position = 'absolute';
      const f = doc.createElementNS('http://www.w3.org/2000/svg', 'filter'); f.setAttribute('id', id);
      f.setAttribute('x', '-50%'); f.setAttribute('y', '-50%'); f.setAttribute('width', '200%'); f.setAttribute('height', '200%');
      fe = doc.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur'); fe.setAttribute('id', id + 'Blur'); fe.setAttribute('in', 'SourceGraphic'); fe.setAttribute('stdDeviation', '0 0');
      f.appendChild(fe); svg.appendChild(f); doc.body.appendChild(svg);
    }
    if (target) target.style.filter = `url(#${id})`;
    return fe;
  }

  /* ---------- match cut: land the incoming shot so a shared element keeps its stage rect ---------- */
  /* out: {pose:{s,cx,cy} at t1, rect:[x,y,w,h]} ; inn: {rect} — rects in each clip's own stage px (see toStage) */
  function matchCut(out, inn, stage) {
    const W = (stage || STAGE)[0], H = (stage || STAGE)[1], q = clampPose(out.pose, stage);
    const s = q.s * out.rect[2] / inn.rect[2];                                       // same on-screen width
    const X = W / 2 + q.s * (out.rect[0] + out.rect[2] / 2 - q.cx), Y = H / 2 + q.s * (out.rect[1] + out.rect[3] / 2 - q.cy);   // where it sits now
    return { s: +s.toFixed(4), c: [+(inn.rect[0] + inn.rect[2] / 2 - (X - W / 2) / s).toFixed(2), +(inn.rect[1] + inn.rect[3] / 2 - (Y - H / 2) / s).toFixed(2)] };
  }
  /* source px rect -> stage px rect of a clip (k = 1280 / source width spanning the stage; crop = clip.crop or band) */
  const toStage = (r, k, crop) => [(r[0] - (crop ? crop[0] : 0)) * k, (r[1] - (crop ? crop[1] : 0)) * k, r[2] * k, r[3] * k];
  /* camera velocity (per second) of a shot at t by central difference of the clamped pose */
  function velocityAt(sh, t, dt) {
    dt = dt || 1 / 60; const a = clampPose(pose(sh, t - dt)), b = clampPose(pose(sh, t + dt));
    return { ds: (b.s - a.s) / (2 * dt), dcx: (b.cx - a.cx) / (2 * dt), dcy: (b.cy - a.cy) / (2 * dt) };
  }
  /* if the outgoing shot still moves at t1, a power2.out entry move for the incoming shot with the same initial velocity
     (power2.out has u'(0) = 2, so the travel is v * dur / 2). start = the incoming shot's first pose. null when at rest. */
  function velocityMatch(outSh, t1, start, o) {
    o = o || {}; const dur = o.dur || 1.0, v = velocityAt(outSh, t1 - 1 / 60);
    const speed = Math.abs(v.ds) * STAGE[0] / 2 + start.s * Math.hypot(v.dcx, v.dcy);
    if (speed < (o.minSpeed || 20)) return null;                                     // < 20 px/s: nothing to match
    return { t0: t1, dur, s: +(start.s + v.ds * dur / 2).toFixed(4), c: [+(start.cx + v.dcx * dur / 2).toFixed(2), +(start.cy + v.dcy * dur / 2).toFixed(2)], ease: 'p2', abs: true, matched: true };
  }

  /* ---------- focus pull: blur + dim everything except a rect ---------- */
  /* f: {t0, dur:0.8, blur:16, dim:0.55, end (release starts end-0.3), release:0.3} -> {u, blur (px), veil (overlay opacity), active}
     dim = how visible the rest stays (0.55 default, never below 0.35); veil = (1 - dim) * u for a dark overlay. */
  function focus(t, f) {
    const R = RULES.focus, dur = f.dur || R.dur, blur = f.blur === undefined ? R.blur : f.blur, dim = Math.max(R.dimMin, f.dim === undefined ? R.dim : f.dim);
    let u = P2IO(rmp(t, f.t0, f.t0 + dur));
    if (f.end !== undefined) u *= 1 - P2IO(rmp(t, f.end - (f.release || R.release), f.end));
    return { u, blur: blur * u, veil: (1 - dim) * u, active: u > 0.002 };
  }
  /* rack focus between planes a and b over one window: a blurs as b sharpens, crossing at the midpoint; b is pre-blurred */
  function rack(t, o) {
    const R = RULES.focus, u = P2IO(rmp(t, o.t0, o.t0 + (o.dur || R.dur))), blur = o.blur || R.blur, dim = Math.max(R.dimMin, o.dim || R.dim);
    return { a: { blur: blur * u, veil: (1 - dim) * u }, b: { blur: blur * (1 - u), veil: (1 - dim) * (1 - u) }, u };
  }
  /* clip-path with a rectangular hole (evenodd) over rect [x,y,w,h] in the element's own px */
  const holePath = (rect, W, H) => `polygon(evenodd, 0 0, ${W}px 0, ${W}px ${H}px, 0 ${H}px, 0 0, ${rect[0]}px ${rect[1]}px, ${rect[0]}px ${rect[1] + rect[3]}px, ${rect[0] + rect[2]}px ${rect[1] + rect[3]}px, ${rect[0] + rect[2]}px ${rect[1]}px, ${rect[0]}px ${rect[1]}px)`;
  /* DOM setter. els: {src (the sharp clip <img>), blurImg (a second <img> above it), veil (a dark div above both)}.
     rect in stage px (for pages, pass rect already shifted by -scrollY*k). Returns a decode Promise when blurImg changed. */
  function applyFocus(els, st, rect, stage) {
    const W = (stage || STAGE)[0], H = (stage || STAGE)[1]; let pending = null;
    if (!st || !st.active) { els.blurImg.style.display = 'none'; els.veil.style.display = 'none'; return pending; }
    const src = els.src && els.src.getAttribute ? els.src.getAttribute('src') : null;   // mirror the sharp clip image
    if (src && els.blurImg.getAttribute('src') !== src) { els.blurImg.setAttribute('src', src); pending = els.blurImg.decode().catch(() => {}); }
    const cp = holePath(rect, W, H);
    els.blurImg.style.display = 'block'; els.blurImg.style.filter = `blur(${st.blur.toFixed(2)}px)`; els.blurImg.style.clipPath = cp;
    els.veil.style.display = 'block'; els.veil.style.opacity = st.veil.toFixed(3); els.veil.style.clipPath = cp;
    return pending;
  }

  /* ---------- dolly zoom (recreated cards only): subject keeps its size while depth planes rush ---------- */
  /* o: {t0, dur:4, d0:1400, ratio:2, dir:'out'|'in', ease:'p2io', subjectScale:1} -> {u, d, perspective, rigZ, active}
     'out' = dolly back + zoom in (background rushes in); 'in' = push forward + zoom out (background falls away).
     Planes sit at translateZ(-N) with at least two distinct N (560 … 3200 px) and must keep d + N > 0. */
  function dolly(t, o) {
    const R = RULES.dolly, d0 = clamp(o.d0 || R.d0, R.d0Min, R.d0Max), ratio = clamp(o.ratio || R.ratio, R.ratioMin, R.ratioMax);
    const d1 = o.dir === 'in' ? d0 / ratio : d0 * ratio, u = easeOf(o.ease || 'p2io')(rmp(t, o.t0, o.t0 + (o.dur || R.dur)));
    const d = lerp(d0, d1, u), k = o.subjectScale || 1, P = k * d;
    return { u, d, perspective: P, rigZ: P - d, active: t >= o.t0 && t < o.t0 + (o.dur || R.dur) };
  }
  /* DOM setter: lens gets the perspective (no overflow:hidden, filter or opacity < 1 between it and the planes), rig the z */
  function applyDolly(lensEl, rigEl, st) {
    lensEl.style.perspective = st.perspective.toFixed(1) + 'px'; lensEl.style.perspectiveOrigin = '50% 50%';
    rigEl.style.transform = `translateZ(${st.rigZ.toFixed(2)}px)`; rigEl.style.transformStyle = 'preserve-3d';
  }

  /* ---------- zoom-out reveal: open tight on a detail, one outward pull, lock ---------- */
  /* sets sh.revealOut; the opening pose is honest only within the zoom budget (1920 px source -> s0 <= 2.0) */
  function revealOut(sh, o) { sh.revealOut = { s0: o.s0, c0: o.c0, at: o.at, dur: o.dur, ease: o.ease || 'expo' }; return sh; }

  /* ---------- caret follow: keep the last typed glyph in frame, min()-continuous ---------- */
  /* p = pose, caretX in stage px before the camera, o:{frac:0.6}: cx = max(cx, caretX - (frac - 0.5) * W / s) */
  function followCaret(p, caretX, o, stage) {
    const W = (stage || STAGE)[0], frac = clamp((o && o.frac) || 0.6, 0.5, 0.75);
    return { s: p.s, cx: Math.max(p.cx, caretX - (frac - 0.5) * W / p.s), cy: p.cy };
  }
  /* caret x (stage px, before the camera) of a reveal shot at t, from FOOT.REVEAL's progress (the same walk
     footage.js drawReveal performs). k = 1280 / crop width, ox = crop x of the clip (source px). */
  function caretX(sh, T, t, k, ox) {
    const R = root.FOOT && root.FOOT.REVEAL, r = sh.reveal; if (!R || !r) return null;
    let left = R.progress(r, T, t), x = null;
    for (const L of r.lines) { const w = L[2] - L[0]; if (left >= w) { left -= w; continue; } x = L[0] + left; break; }
    if (x === null) x = r.lines[r.lines.length - 1][2];
    return (x - (ox || 0)) * k;
  }

  /* ---------- idle: Lissajous drift + breathing, so a hold never dies ---------- */
  /* o: {ax:5, ay:2.5 (px), ratio:1.3, cycles:1, dur, ds:0.01} -> {dx, dy, ds (multiplier)} */
  function idle(t, t0, o) {
    const R = RULES.idle, ax = o.ax === undefined ? R.ax : o.ax, ay = o.ay === undefined ? R.ay : o.ay, ratio = o.ratio || R.ratio;
    const ph = 2 * Math.PI * (o.cycles || R.cycles) * (t - t0) / Math.max(0.1, o.dur || 6);
    return { dx: ax * Math.sin(ph), dy: ay * Math.sin(ratio * ph), ds: 1 + (o.ds === undefined ? R.ds : o.ds) * Math.sin(0.7 * ph) };
  }
  const withIdle = (p, d) => ({ s: p.s * d.ds, cx: p.cx - d.dx / p.s, cy: p.cy - d.dy / p.s });
  /* a push whose ease window runs 0.5 s past the move, so velocity never reaches zero on screen */
  const pushLong = (t0, dur, s, c, ease) => ({ t0, dur: dur + 0.5, s, c, ease: ease || 'out', abs: true, long: true });

  /* ---------- freeze-hit beat: snap-on dressing + 60 ms exposure flash + settle ---------- */
  function hit(t, t0, o) {
    const R = Object.assign({}, RULES.hit, o || {}), on = t >= t0;
    return { on, flash: on ? R.flash * (1 - P2(rmp(t, t0, t0 + R.flashDur))) : 0, settle: on ? lerp(1, R.settle, rmp(t, t0 + R.settleAt, t0 + R.settleAt + R.settleDur)) : 0,
      scale: on ? lerp(1, R.snap, P4(rmp(t, t0, t0 + R.snapDur))) : 1 };
  }

  /* ---------- travel blur: directional streak that rides the camera speed ---------- */
  /* picture speed in stage px per frame between two poses: scale change moves the frame edge by ds*W/2, a pan moves by s*dc */
  const speed = (a, b, W) => Math.abs(b.s - a.s) * (W || STAGE[0]) / 2 + ((a.s + b.s) / 2) * Math.hypot(b.cx - a.cx, b.cy - a.cy);
  /* stdDeviation string: '0 0' under one element-width per frame (min 24 px), ramps to peak (18) by 4x min, capped at 20 */
  function streak(v, o) {
    o = o || {}; const R = RULES.streak, min = o.min || R.min, peak = Math.min(o.peak || R.peak, o.cap || R.cap);
    if (v < min) return '0 0';
    const sd = (peak * clamp((v - min) / (3 * min), 0, 1)).toFixed(2);
    return o.axis === 'y' ? `0 ${sd}` : o.axis === 'b' ? `${sd} ${sd}` : `${sd} 0`;
  }
  /* the streak for a shot at t (pure: compares the pose at t and t - 1/fps). Never blurs a reveal (text must land sharp). */
  function travelBlur(sh, t, o) {
    o = o || {}; if (sh.reveal || sh.noBlur) return '0 0';
    const a = clampPose(pose(sh, t - 1 / (o.fps || 30))), b = clampPose(pose(sh, t));
    const axis = o.axis || (Math.abs(b.s - a.s) * STAGE[0] / 2 > b.s * Math.hypot(b.cx - a.cx, b.cy - a.cy) ? 'b' : Math.abs(b.cx - a.cx) >= Math.abs(b.cy - a.cy) ? 'x' : 'y');
    return streak(speed(a, b), Object.assign({ axis }, o));
  }

  /* ---------- frame-index quantization for stepped effects ---------- */
  const frameIdx = (t, fps) => Math.round(t * (fps || 30));
  /* stepped hold: which n-frame step frame t belongs to (never divide seconds — seek times are not exact 1/fps doubles) */
  const stepHold = (t, n, fps) => Math.floor(frameIdx(t, fps) / Math.max(1, n || 2));
  /* the output frames each source frame of a seq is shown for, under footage.js's schedule (diagnostic for the gate) */
  function seqSchedule(sh, clip, fps) {
    const FPS = fps || 30, n = clip.frames, from = (sh.play && sh.play.from) || 1, at = sh.play ? sh.play.at : sh.t0, rate = (sh.play && sh.play.rate) || 1;
    const i0 = Math.ceil(sh.t0 * FPS - 1e-6), i1 = Math.floor((sh.t1 || sh.t0 + n / clip.fps) * FPS - 1e-6), seq = [];
    for (let i = i0; i <= i1; i++) {
      const t = i / FPS; let f = from + Math.floor(Math.max(0, t - at) * clip.fps * rate + 1e-6);
      if (f > n) { if (sh.play && sh.play.loop) { const a = sh.play.loop[0] + 1, b = sh.play.loop[1] + 1; f = a + ((f - n - 1) % (b - a + 1)); } else f = n; }
      seq.push(f);
    }
    return { i0, i1, at, rate, from, frames: n, fps: clip.fps, seq, end: at + (n - from + 1) / (clip.fps * rate) };
  }

  /* ---------- pose ladder + lint ---------- */
  const verbOf = (a, b, m) => {
    if (m && (m.reveal)) return 'reveal';
    if (m && isPunch(m)) return b.s > a.s ? 'punch-in' : 'punch-out';
    const ds = b.s / Math.max(1e-6, a.s) - 1, pan = ((a.s + b.s) / 2) * Math.hypot(b.cx - a.cx, b.cy - a.cy);
    if (ds > 0.02) return 'push-in'; if (ds < -0.02) return 'pull-out'; if (pan > 8) return 'pan'; return 'hold';
  };
  /* flatten a shot into legs (moves) and holds (dwell between them) */
  function ladder(sh) {
    const legs = [], M = movesOf(sh).slice().sort((a, b) => a.t0 - b.t0); let cur = clampPose(startPose(sh));
    for (const m of M) {
      const to = clampPose({ s: m.s, cx: m.c[0], cy: m.c[1] });
      legs.push({ t0: +m.t0.toFixed(3), t1: +(m.t0 + m.dur).toFixed(3), dur: +m.dur.toFixed(3), from: cur, to, verb: verbOf(cur, to, m), ease: typeof m.ease === 'string' ? m.ease : (m.ease ? 'fn' : 'out'), punch: isPunch(m), fit: m.fit || null, long: !!m.long, matched: !!m.matched });
      cur = to;
    }
    const holds = []; let prev = sh.t0;
    for (const l of legs) { if (l.t0 - prev > 1e-3) holds.push({ t0: +prev.toFixed(3), t1: l.t0, dur: +(l.t0 - prev).toFixed(3) }); prev = l.t1; }
    if (sh.t1 && sh.t1 - prev > 1e-3) holds.push({ t0: +prev.toFixed(3), t1: +sh.t1.toFixed(3), dur: +(sh.t1 - prev).toFixed(3) });
    return { legs, holds, shape: legs.filter(l => l.verb !== 'hold').length ? 'ladder' : 'flat', open: clampPose(startPose(sh)), end: cur };
  }
  /* rules: {dwell:1.0, durMin:0.5, teleport:0.8, durMax:2.5, sameVerb:3, punchGap:1.0, punchGain:0.25, punchHold:0.8}
     cuts: hard-cut times (a move still running into a hard cut fails). Returns {items:[{shot, level, rule, detail}], fails, warns}. */
  function lint(SHOTS, o) {
    o = o || {}; const R = Object.assign({ dwell: RULES.zoom.dwell, durMin: RULES.zoom.durMin, teleport: RULES.zoom.teleport, durMax: RULES.zoom.durMax, sameVerb: 3,
      punchGap: RULES.punch.gap, punchGain: RULES.punch.maxGain, punchHold: RULES.punch.hold, punchDurMax: RULES.punch.durMax }, o.rules || {});
    const cuts = (o.cuts || []).map(x => +x), items = [], name = (sh, i) => sh.name || (sh.clip + '@' + (+sh.t0).toFixed(2)) + '#' + i;
    SHOTS.forEach(function (sh, i) {
      const L = ladder(sh), id = name(sh, i), add = (level, rule, detail) => items.push({ shot: id, level, rule, detail });
      let run = 1;
      L.legs.forEach(function (l, j) {
        if (l.punch) {
          if (l.dur > R.punchDurMax + 1e-6 || l.dur < RULES.punch.durMin - 1e-6) add('WARN', 'punch dur', `${l.dur} s (0.14–0.25 s)`);
          if (l.to.s / l.from.s - 1 > R.punchGain + 1e-6) add('FAIL', 'punch gain', `+${Math.round((l.to.s / l.from.s - 1) * 100)} % (<= +25 %)`);
          const nxt = L.legs[j + 1]; if (nxt && nxt.t0 - l.t1 < R.punchHold - 1e-6) add('WARN', 'punch hold', `${(nxt.t0 - l.t1).toFixed(2)} s before the next move (>= 0.8 s)`);
          if (nxt && nxt.punch && nxt.t0 - l.t0 < R.punchGap - 1e-6) add('FAIL', 'punch gap', `two punches ${(nxt.t0 - l.t0).toFixed(2)} s apart (>= 1.0 s)`);
        } else if (l.verb !== 'hold') {
          if (l.dur < R.durMin - 1e-6) add('FAIL', 'move too short', `${l.verb} ${l.dur} s (< 0.5 s and not a punch)`);
          else if (l.dur < R.teleport - 1e-6) add('WARN', 'teleport', `${l.verb} ${l.dur} s (under 0.8 s teleports)`);
          if (l.dur > R.durMax + 1e-6 && !l.long && l.verb !== 'reveal') add('FAIL', 'move too long', `${l.verb} ${l.dur} s (> 2.5 s drags)`);
        }
        if (['out', 'io', 'fn'].indexOf(l.ease) < 0 && !EASE[l.ease]) add('FAIL', 'unknown ease', `'${l.ease}'`);
        if (j > 0) {
          const gap = l.t0 - L.legs[j - 1].t1;
          if (gap < R.dwell - 1e-6 && !(l.punch && gap >= R.punchHold - 1e-6) && !L.legs[j - 1].punch) add('WARN', 'no dwell', `${gap.toFixed(2)} s between ${L.legs[j - 1].verb} and ${l.verb} (>= ${R.dwell} s)`);
          run = l.verb === L.legs[j - 1].verb && l.verb !== 'hold' ? run + 1 : 1;
          if (run === R.sameVerb) add('WARN', 'same verb', `${run} consecutive ${l.verb} legs read as a slideshow`);
        }
        if (sh.t1 && l.t1 > sh.t1 + 1e-3 && !l.long && cuts.some(c => Math.abs(c - sh.t1) < 1e-3)) add('FAIL', 'move across cut', `${l.verb} still running at the hard cut ${sh.t1}`);
        if (sh.revealOut && !l.verb.startsWith('reveal') && l.t0 >= sh.revealOut.at && l.to.s > 1.0005) add('FAIL', 'zoom-in after reveal', `${l.verb} at ${l.t0} (one outward move, then lock)`);
      });
      if (sh.revealOut && sh.t1 && sh.revealOut.at + sh.revealOut.dur > sh.t1 + 1e-3) add('FAIL', 'reveal ends late', 'the pull must end before the shot does');
      if (sh.establish && sh.establish.hold < RULES.zoom.startAfter - 1e-6) add('WARN', 'early push', `establish hold ${sh.establish.hold} s (start 0.5–1.5 s after the layout lands)`);
    });
    const kinds = {}; let accents = 0;
    SHOTS.forEach(sh => { if (sh.enter) { kinds[sh.enter.kind] = 1; accents++; } });
    const hard = SHOTS.filter(s => !s.seam).length;
    if (Object.keys(kinds).length > RULES.seams.maxKinds) items.push({ shot: '*', level: 'WARN', rule: 'seam kinds', detail: `${Object.keys(kinds).join(', ')} (one primary + <= 2 accents)` });
    if (hard && accents / hard > RULES.seams.accentShare) items.push({ shot: '*', level: 'WARN', rule: 'accent share', detail: `${accents}/${hard} cuts are accent seams (<= 25 %)` });
    return { items, fails: items.filter(x => x.level === 'FAIL').length, warns: items.filter(x => x.level === 'WARN').length };
  }

  /* ---------- trace: 30 fps camera curve + windows of scheduled non-camera motion (for gates/motion_diag.py) ---------- */
  /* ctx: {T (timeline), CL (clips), HL (highlights), fps:30} */
  function trace(sh, ctx) {
    ctx = ctx || {}; const fps = ctx.fps || 30, T = ctx.T, c = ctx.CL && ctx.CL[sh.clip], t1 = sh.t1 || sh.t0 + 5;
    const samples = [], spd = []; let prev = null;
    for (let i = Math.ceil(sh.t0 * fps - 1e-6); i <= Math.floor(t1 * fps + 1e-6); i++) {
      const t = i / fps, p = resolve(sh, t);
      samples.push({ t: +t.toFixed(4), s: +p.s.toFixed(5), cx: +p.cx.toFixed(2), cy: +p.cy.toFixed(2) });
      spd.push(prev ? +speed(prev, p).toFixed(3) : 0); prev = p;
    }
    const W = { scroll: [], seq: [], reveal: [], stream: [], hl: [], seam: [], focus: [], establish: [] };
    (sh.scroll || []).forEach(k => W.scroll.push([k.t0, k.t0 + k.dur]));
    if (c && c.kind === 'seq') { const S = seqSchedule(sh, c, fps); W.seq.push([S.at, sh.play && sh.play.loop ? t1 : Math.min(t1, S.end + 1 / fps)]); }
    if (sh.reveal && T && root.FOOT) { const R = root.FOOT.REVEAL; W.reveal.push([sh.t0, R.end(sh.reveal, T) + 0.1]); }
    if (sh.stream) W.stream.push([sh.stream.t0, sh.stream.t0 + sh.stream.dur + 0.25]);
    if (T && ctx.HL && ctx.HL[sh.clip]) ctx.HL[sh.clip].forEach(h => {
      const a = T.wt(h.cue[0], h.cue[1], h.cue[2]) + (h.dt || 0); W.hl.push([a, a + 0.32]);
      if (h.until) { const b = T.wt(h.until[0], h.until[1]); W.hl.push([b, b + 0.3]); }
      if (h.kind === 'focus') W.focus.push([a, h.until ? T.wt(h.until[0], h.until[1]) : t1]);
    });
    if (sh.enter) W.seam.push([sh.t0, sh.t0 + seamDur(sh) + 0.05]);
    if (sh.focus) W.focus.push([sh.focus.t0, sh.focus.end || t1]);
    if (sh.establish) W.establish.push([sh.t0, sh.t0 + sh.establish.hold]);
    const L = ladder(sh), peak = Math.max.apply(null, spd.concat([0]));
    return { shot: sh.name || sh.clip + '@' + (+sh.t0).toFixed(2), clip: sh.clip, kind: c ? c.kind : null, t0: +sh.t0.toFixed(3), t1: +t1.toFixed(3), seam: !!sh.seam,
      enter: sh.enter ? sh.enter.kind : null, cutAt: +seamCutAt(sh).toFixed(3), fps, samples, speed: spd, peak: +peak.toFixed(3), shape: L.shape,
      verbs: L.legs.map(l => l.verb), dwell: L.holds.map(h => h.dur), windows: W };
  }

  /* ---------- node CLI ---------- */
  function cli(argv) {
    const path = require('path'), fs = require('fs');
    const args = argv.slice(); const opt = (k, d) => { const i = args.indexOf(k); if (i < 0) return d; const v = args.splice(i, 2)[1]; return v; };
    const outDir = opt('--out', 'out'), fps = parseInt(opt('--fps', '30'), 10); args.splice(args.indexOf('--curves'), 1);
    const [timing, shots, clips] = args;
    if (!timing || !shots) { console.error('usage: node camera.js --curves scenes/timing_<name>_data.js scenes/shots.js [broll/clips.js] [--out out] [--fps 30]'); process.exit(2); }
    global.window = global; const here = __dirname;
    require(path.resolve(here, 'grammar.js'));
    global.TX = require(path.resolve(here, 'timeline.js')).load(timing);
    require(path.resolve(here, 'footage.js'));
    if (clips && fs.existsSync(clips)) require(path.resolve(clips));
    require(path.resolve(shots));
    const F = global.FILM || {}, SH = global.SHOTS || [], CL = global.CLIPS || {}, HL = global.HL || {};
    const cuts = [F.openEnd, F.close].concat(SH.filter(s => !s.seam).map(s => s.t0)).filter(x => typeof x === 'number');
    const curves = SH.map(sh => trace(sh, { T: global.TX, CL, HL, fps }));
    const L = lint(SH, { cuts });
    const budgets = SH.map(sh => Object.assign({ shot: sh.name || sh.clip + '@' + (+sh.t0).toFixed(2), clip: sh.clip, sourceWidth: sourceWidth(CL[sh.clip]) }, budget(sh, CL[sh.clip])));
    const seqs = SH.filter(sh => CL[sh.clip] && CL[sh.clip].kind === 'seq').map(sh => Object.assign({ shot: sh.name || sh.clip + '@' + (+sh.t0).toFixed(2), clip: sh.clip, t0: sh.t0, t1: sh.t1 }, seqSchedule(sh, CL[sh.clip], fps)));
    const ladders = SH.map((sh, i) => Object.assign({ shot: sh.name || sh.clip + '@' + (+sh.t0).toFixed(2), t0: sh.t0, t1: sh.t1 }, ladder(sh)));
    // recreated overlays that move inside the footage act (lower thirds: fade in 0.3 s, fade out 0.35 s) are not footage motion
    const acts = (F.acts || []).filter(a => typeof a.t0 === 'number').map(a => [[a.t0 + 0.3, a.t0 + 0.65], [a.t0 + 3.4, a.t0 + 3.85]]).flat();
    fs.mkdirSync(path.resolve(outDir), { recursive: true });
    fs.writeFileSync(path.resolve(outDir, 'camera_curves.json'), JSON.stringify({ fps, total: global.TX.total, openEnd: F.openEnd, close: F.close, cuts, allow: acts, shots: curves }, null, 1));
    fs.writeFileSync(path.resolve(outDir, 'camera_report.json'), JSON.stringify({ fps, rules: RULES, ladders, lint: L, budget: budgets, seqs, cuts }, null, 1));
    const pad = (s, n) => String(s).padEnd(n);
    console.log(pad('shot', 18) + pad('verbs', 34) + pad('peak px/f', 11) + pad('dwell s', 16) + 'upsample');
    curves.forEach((c, i) => console.log(pad(c.shot, 18) + pad(c.verbs.join(',') || 'flat', 34) + pad(c.peak, 11) + pad(c.dwell.map(d => d.toFixed(1)).join(','), 16) + budgets[i].upsample + ' ' + budgets[i].level));
    L.items.forEach(x => console.log(`  ${x.level}  ${x.shot}  ${x.rule}: ${x.detail}`));
    const bad = budgets.filter(b => b.level === 'fail' || b.headroomFails.length);
    console.log(`${curves.length} shots -> ${outDir}/camera_curves.json, ${outDir}/camera_report.json | lint ${L.fails} FAIL ${L.warns} WARN | budget ${bad.length} over`);
    process.exit(L.fails || bad.length ? 1 : 0);
  }

  const CAM = { RULES, EASE, easeOf, EZ, EIO, P2, P3, P4, EXPO, P2IN, P3IN, P4IN, P2IO, P3IO, LIN,
    clampPose, pose, resolve, applyPose, movesOf, startPose,
    punchTo, punchOut, isPunch, fitScale, pushToFit, sourceWidth, upsample, maxScale, budget,
    nudge, whipBlur, whip, zoomThrough, connector, seam, seamCutAt, seamDur, applySeam, ensureStreakFilter,
    matchCut, toStage, velocityAt, velocityMatch, focus, rack, holePath, applyFocus, dolly, applyDolly, revealOut,
    followCaret, caretX, idle, withIdle, pushLong, hit, speed, streak, travelBlur, frameIdx, stepHold, seqSchedule,
    verbOf, ladder, lint, trace };
  root.CAM = CAM;
  if (typeof module !== 'undefined' && module.exports) { module.exports = CAM; if (require.main === module && process.argv.indexOf('--curves') > 0) cli(process.argv.slice(2)); }
})(typeof window !== 'undefined' ? window : globalThis);
