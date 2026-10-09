/* reel.js — REEL: showreel motion for the RECREATED layer, as pure functions of t. Never over product pixels.

   Nine devices that make a pitch film read as a motion-design reel rather than a slide deck. Each one is a pure
   function of the film clock (no state between frames, no randomness, no wall clock), so a cold __seek(t) and a
   stepped render paint identical pixels, and every device draws into a canvas or a DOM node the SCENE owns.

     REEL.hud(cv, t, o)            film frame: four corner brackets, a chapter index with a decode-on label, a running
                                   timecode with a live dot. One canvas above the act, below captions + logo.
     REEL.stinger(cv, t, o)        pixel-matrix cut: navy tiles close in on a diagonal while the pattern morphs
                                   square → cross → triangle, the cut happens fully covered, then the tiles open.
                                   Only at DECLARED cuts (o.cuts); REEL.coverAt(t, o) tells the scene how covered it is.
     REEL.streaks(ctx, x, y, u, o) light-speed burst: radial streaks out of a point, u 0 → 1 over ~1 s.
     REEL.rings(ctx, x, y, u, o)   ripple rings: concentric ellipses bloom out of a point, staggered, alternating weight.
     REEL.voxel(cv, t, o)          an iso voxel field over a flat grid (a calendar, a heat map): columns rise with a
                                   height(cell, t) the scene supplies, the camera tilts/yaws, and REEL.view() can
                                   un-tilt to top-down with heights → 0 so the field LANDS EXACTLY on the flat DOM grid
                                   (hand-off to a DOM shatter, a morph, anything).
     REEL.blob(parent, x, y, w, h) a glossy liquid core: smooth-union metaballs, orthographic raymarch on WebGL (works on
                                   software GL). draw(balls, t, wob); balls in STAGE px, so droplets can be launched from
                                   any DOM element's position and merge into the core.
     REEL.slam(host, o)            two colour panels snap shut on a word and split open onto the title behind them.
     REEL.marquee(el, t, t0, o)    an outline-text row that drifts (pair two rows in opposite directions behind a title).
     REEL.smear(v, o)              a vertical motion trail for a rising glyph, as a text-shadow string (v 1 → 0).
     REEL.decode(text, u, seed)    decode-on text: glyph soup resolving left → right, deterministic.

   Doctrine (also in references/showreel-motion.md)
     - Recreated layer only. A stinger may pass over footage only inside its own window (≤ 0.8 s, centred on a
       declared cut); the voxel field, the liquid core, the slam and the marquee never sit on product pixels.
     - One accent colour is the reel's hand (slam, crests, hot tiles, the core); the rest stays in the film palette.
     - Every device lands on a spoken word: t0 values are wt(phase, word) from lib/timeline.js, never typed seconds.
     - Canvases are 1.5× the 1280×720 stage (1920×1080) unless the scene says otherwise; pass o.k = canvas px / stage px.

   Scene wiring:
     <script src="lib/reel.js"></script>
     const hudCv = mkCanvas(#stage, z 30);  REEL.hud(hudCv, t, { chapters: [[0,'The problem'],[P.fix,'The fix']] });
     REEL.stinger(hudCv, t, { cuts: [P.fix], clear: false });         // same canvas, after the HUD
     REEL.streaks(fxCtx, 640, 300, K.rmp(t, wt('open','four'), wt('open','four') + 1));
     const core = REEL.blob(host, 300, 200, 680, 460);  core.draw([[640, 500, 80], [x, y, 14]], t, 1);

   Node (no DOM): node lib/reel.js --help | --selftest
   JSON out; exit 0 ok, 1 findings, 2 usage. */
(function (root) {
  'use strict';
  const IS_NODE = typeof window === 'undefined';
  const REEL = {};
  const fh = (i, k) => { const v = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return v - Math.floor(v); };
  const cl = (x, a, b) => Math.max(a, Math.min(b, x)), rmp = (t, a, b) => cl((t - a) / (b - a), 0, 1), lerp = (a, b, u) => a + (b - a) * u;
  const out3 = u => 1 - Math.pow(1 - u, 3), in3 = u => u * u * u, io3 = u => u < .5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
  const back = u => { const c = 1.70158, v = u - 1; return 1 + (c + 1) * v * v * v + c * v * v; };
  REEL.ease = { out3, in3, io3, back };
  REEL.rmp = rmp;
  /* palette: override per film (brand kit). accent = the reel's hand; ink/cream/mint/gold = film palette; navy = cover */
  REEL.tokens = { accent: '#D9533F', coral: '#E56B5E', cream: '#ECDEC3', ink: '#E9F3F9', mint: '#81A9AB', gold: '#E8C874', navy: '#05161C' };
  const T = () => REEL.tokens;
  const kOf = (cv, o) => (o && o.k) || cv.width / 1280;

  /* ---------------- decode-on text ---------------- */
  const SOUP = '!<>-_/[]{}=+*^?#ABCDEFGHJKLMNPRSTUVWXYZ0123456789';
  REEL.decode = (txt, u, seed) => { seed = seed || 1; if (u >= 1) return txt; let s = '';
    for (let i = 0; i < txt.length; i++) { const c = txt[i]; if (c === ' ') { s += ' '; continue; }
      const k = i / Math.max(1, txt.length); s += u > k * .7 + .15 * fh(i, seed) ? c : (u > k * .5 ? SOUP[Math.floor(fh(i + seed, Math.floor(u * 24)) * SOUP.length)] : ''); }
    return s; };

  /* ---------------- HUD film frame ---------------- */
  REEL.hud = (cv, t, o) => { o = o || {}; const c = cv.getContext('2d'), k = kOf(cv, o), W = cv.width, H = cv.height;
    if (o.clear !== false) { c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, W, H); }
    const A = (o.alpha == null ? 1 : o.alpha) * rmp(t, o.fadeIn == null ? .25 : o.fadeIn, (o.fadeIn == null ? .25 : o.fadeIn) + .65) * (o.end ? 1 - rmp(t, o.end - 1, o.end) : 1);
    if (A <= 0) return; const corner = o.corners || [1, 1, 1, 1];   // per-corner alpha: TL, TR, BL, BR (a block that owns a corner sets 0)
    c.save(); c.strokeStyle = 'rgba(233,243,249,.38)'; c.lineWidth = 1.5 * k;
    const I = (o.inset || 24) * k, L = (o.arm || 30) * k;
    [[I, I, 1, 1], [W - I, I, -1, 1], [I, H - I, 1, -1], [W - I, H - I, -1, -1]].forEach(([x, y, sx, sy], q) => { c.globalAlpha = A * corner[q];
      c.beginPath(); c.moveTo(x, y + sy * L); c.lineTo(x, y); c.lineTo(x + sx * L, y); c.stroke(); });
    const ch = o.chapters || []; c.font = '700 ' + (10 * k).toFixed(1) + 'px Consolas, "Courier New", monospace'; c.textBaseline = 'middle';
    const x0 = (o.inset || 24) * k + 20 * k, yT = (o.inset || 24) * k + 7 * k;
    if (ch.length) { let ci = 0; ch.forEach((h, i) => { if (t >= h[0]) ci = i; });
      const idx = String(ci + 1).padStart(2, '0') + ' / ' + String(ch.length).padStart(2, '0');
      c.globalAlpha = A * corner[0]; c.fillStyle = T().coral; c.fillText(idx, x0, yT);
      c.fillStyle = 'rgba(233,243,249,.62)'; c.fillText(REEL.decode(String(ch[ci][1]).toUpperCase(), rmp(t, ch[ci][0], ch[ci][0] + .45), ci * 7 + 3), x0 + c.measureText(idx + '   ').width, yT); }
    if (o.timecode !== false) { const fps = o.fps || 30, m = Math.floor(t / 60), s = Math.floor(t % 60), f = Math.floor((t % 1) * fps), yB = H - (o.inset || 24) * k - 7 * k;
      c.globalAlpha = A * corner[2]; c.fillStyle = 'rgba(233,243,249,.45)';
      c.fillText('TC ' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0') + ':' + String(f).padStart(2, '0'), x0, yB);
      c.fillStyle = T().coral; c.globalAlpha = A * corner[2] * (.55 + .45 * Math.sin(t * 5)); c.beginPath(); c.arc(x0 - 9 * k, yB, 2.6 * k, 0, 6.2832); c.fill(); }
    c.restore(); };

  /* ---------------- pixel-matrix stinger ---------------- */
  const SDEF = { cover: .34, uncover: .38, cell: 48 };
  REEL.coverAt = (t, o) => { o = Object.assign({}, SDEF, o); let m = 0; (o.cuts || []).forEach(cc => { m = Math.max(m, rmp(t, cc - o.cover, cc) * (1 - rmp(t, cc, cc + o.uncover))); }); return m; };
  REEL.stinger = (cv, t, o) => { o = Object.assign({}, SDEF, o); const c = cv.getContext('2d'), k = kOf(cv, o), W = cv.width, H = cv.height;
    if (o.clear) { c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, W, H); }
    if (o.cover + o.uncover > .8 + 1e-9) throw new Error('reel.js stinger: cover + uncover must be ≤ 0.8 s (got ' + (o.cover + o.uncover) + ')');
    (o.cuts || []).forEach((cc, si) => {
      const a = cc - o.cover - .02, b = cc + .02 + o.uncover; if (t < a - .05 || t > b + .05) return;
      const CS = o.cell * k, NX = Math.ceil(W / CS), NY = Math.ceil(H / CS), uc = rmp(t, a, cc - .02), uu = rmp(t, cc + .02, b);
      for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) {
        const d = (si % 2 ? (NX - 1 - i) : i) / Math.max(1, NX - 1) * .62 + j / Math.max(1, NY - 1) * .38;
        const v = cl(uc * 1.6 - d * .6, 0, 1), w = cl(uu * 1.6 - d * .6, 0, 1), kk = io3(v) * (1 - io3(w)); if (kk <= .002) continue;
        const cx = i * CS + CS / 2, cy = j * CS + CS / 2, nv = Math.min(1, kk * 1.18);
        c.globalAlpha = 1; c.fillStyle = T().navy; c.fillRect(cx - CS * nv / 2 - .5, cy - CS * nv / 2 - .5, CS * nv + 1, CS * nv + 1);
        const ph = (t - a) / (b - a) + d * .25, s = CS * (.16 + .5 * kk), hot = Math.sin((i + j) * .55 - t * 14 + si) > .15;
        c.fillStyle = hot ? T().accent : T().cream; c.globalAlpha = (hot ? 1 : .9) * cl(kk * 1.4, 0, 1);
        if (ph < .42) c.fillRect(cx - s / 2, cy - s / 2, s, s);
        else if (ph < .72) { const t2 = s * .3; c.fillRect(cx - s / 2, cy - t2 / 2, s, t2); c.fillRect(cx - t2 / 2, cy - s / 2, t2, s); }
        else { const r = (i + j) % 2 ? 1 : -1; c.beginPath(); c.moveTo(cx - s / 2 * r, cy - s / 2); c.lineTo(cx + s / 2 * r, cy); c.lineTo(cx - s / 2 * r, cy + s / 2); c.closePath(); c.fill(); }
      }
      c.globalAlpha = 1; });
  };

  /* ---------------- light-speed burst ---------------- */
  REEL.streaks = (c, cx, cy, u, o) => { o = o || {}; if (u <= 0 || u >= 1) return; const k = o.k || c.canvas.width / 1280, N = o.n || 110, seed = o.seed || 5, X = cx * k, Y = cy * k;
    c.save(); c.lineCap = 'round';
    for (let i = 0; i < N; i++) { const a = fh(i, seed) * 6.2832, sp = .45 + .55 * fh(i, seed + 1), r0 = (30 + 140 * fh(i, seed + 2)) * k;
      const head = r0 + 833 * k * out3(u) * sp, len = (60 + 175 * fh(i, seed + 3)) * k * (1 - .55 * u), tail = Math.max(r0, head - len), col = fh(i, seed + 4);
      c.strokeStyle = col < .55 ? 'rgba(255,241,220,1)' : col < .85 ? T().coral : T().gold;
      c.globalAlpha = (o.a || 1) * Math.pow(1 - u, 1.3) * (.35 + .65 * fh(i, seed + 5)) * rmp(u, 0, .06);
      c.lineWidth = (.8 + 1.7 * fh(i, seed + 6)) * k * (1 - .5 * u);
      const ca = Math.cos(a), sa = Math.sin(a) * (o.sq || .62);
      c.beginPath(); c.moveTo(X + ca * tail, Y + sa * tail); c.lineTo(X + ca * head, Y + sa * head); c.stroke(); }
    c.restore(); };

  /* ---------------- ripple rings ---------------- */
  REEL.rings = (c, cx, cy, u, o) => { o = o || {}; if (u <= 0 || u >= 1) return; const k = o.k || c.canvas.width / 1280, N = o.n || 9, X = cx * k, Y = cy * k;
    c.save();
    for (let i = 0; i < N; i++) { const v = rmp(u, i * .045, .55 + i * .045); if (v <= 0 || v >= 1) continue;
      const r = ((o.r0 || 30) + (o.r1 || 620) * out3(v)) * k;
      c.strokeStyle = i % 3 === 0 ? T().coral : i % 3 === 1 ? T().cream : T().accent; c.globalAlpha = (o.a || .8) * (1 - v) * (1 - v);
      c.lineWidth = (i % 2 ? 2 : 5) * (1 - .6 * v) * k;
      c.beginPath(); c.ellipse(X, Y, r, r * (o.sq || .62), 0, 0, 6.2832); c.stroke(); }
    c.restore(); };

  /* ---------------- smear trail ---------------- */
  REEL.smear = (v, o) => { o = o || {}; if (v <= .01) return 'none'; const d = (o.dir || 1) * (o.step || 15) * v;
    return '0 ' + d.toFixed(1) + 'px 0 rgba(233,243,249,' + (.34 * v).toFixed(3) + '),0 ' + (2 * d).toFixed(1) + 'px 0 rgba(233,243,249,' + (.17 * v).toFixed(3) + '),0 ' + (3 * d).toFixed(1) + 'px 0 rgba(229,107,94,' + (.16 * v).toFixed(3) + ')'; };

  /* ---------------- iso voxel field ----------------
     o.grid = { x, y, cols, rows, pitch, size }  stage px of the FLAT grid (top-left of cell 0, cell pitch, cell size)
     o.height(cell, t) → px            cell = { i, c, r, cx, cy } (i = c * rows + r, column-major)
     o.view = REEL.view(t, {...})      camera; o.color(cell, t) → { top:[r,g,b,a], side:[r,g,b], line:[r,g,b,a], crest:0..1 } optional */
  REEL.view = (t, o) => { o = o || {}; const g = o.grid; const f = o.flatAt == null ? 0 : io3(rmp(t, o.flatAt - (o.flatDur || .48), o.flatAt));
    const it = out3(rmp(t, o.t0 || 0, (o.t0 || 0) + (o.intro || 1.8)));
    const gcy = g ? g.y + (g.rows - 1) * g.pitch / 2 + g.size / 2 : 360;
    return { pit: lerp(lerp(o.pit0 || 66, o.pit || 54, it), 0, f) * Math.PI / 180,
      yaw: lerp(lerp(o.yaw0 == null ? -20 : o.yaw0, o.yaw == null ? -32 : o.yaw, it) + (o.sway == null ? 2.5 : o.sway) * Math.sin(t * .45), 0, f) * Math.PI / 180,
      hk: 1 - f, cy: lerp(o.cy || gcy - 2, gcy, f), k: lerp(lerp(o.k0 || .9, 1, it), 1, f), flat: f }; };
  REEL.project = (x, y, z, V, g) => { const gcx = g.x + (g.cols - 1) * g.pitch / 2 + g.size / 2, gcy = g.y + (g.rows - 1) * g.pitch / 2 + g.size / 2;
    const dx = x - gcx, dy = y - gcy, c = Math.cos(V.yaw), s = Math.sin(V.yaw), rx = dx * c - dy * s, ry = dx * s + dy * c;
    return [gcx + rx * V.k, V.cy + (ry * Math.cos(V.pit) - z * Math.sin(V.pit)) * V.k, ry]; };
  const NRM = [[0, -1], [1, 0], [0, 1], [-1, 0]];
  REEL.voxel = (cv, t, o) => { const c = cv.getContext('2d'), k = kOf(cv, o), g = o.grid, V = o.view, P = (x, y, z) => REEL.project(x, y, z, V, g);
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, cv.width, cv.height); c.setTransform(k, 0, 0, k, 0, 0);
    const cs = Math.cos(V.yaw), sn = Math.sin(V.yaw), hs = g.size / 2, cells = [];
    for (let cc = 0; cc < g.cols; cc++) for (let r = 0; r < g.rows; r++) { const cx = g.x + cc * g.pitch + hs, cy = g.y + r * g.pitch + hs; cells.push({ i: cc * g.rows + r, c: cc, r, cx, cy }); }
    const gcx = g.x + (g.cols - 1) * g.pitch / 2 + hs, gcy = g.y + (g.rows - 1) * g.pitch / 2 + hs;
    const q = cells.map(cell => ({ cell, h: V.hk * Math.max(0, o.height(cell, t)), col: o.color ? o.color(cell, t) : null, ry: (cell.cx - gcx) * sn + (cell.cy - gcy) * cs })).sort((a, b) => a.ry - b.ry);
    q.forEach(e => { const cell = e.cell, H = e.h, col = e.col || { top: [129, 169, 171, .26], side: [38, 70, 78], line: [129, 169, 171, .3], crest: 0, a: 1 };
      const x0 = cell.cx - hs, x1 = cell.cx + hs, y0 = cell.cy - hs, y1 = cell.cy + hs, cn = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], a = col.a == null ? 1 : col.a;
      if (H > .4) NRM.forEach((n, kk) => { if (n[0] * sn + n[1] * cs <= .001) return; const p = cn[kk], b = cn[(kk + 1) % 4];
        const p1 = P(p[0], p[1], 0), p2 = P(b[0], b[1], 0), p3 = P(b[0], b[1], H), p4 = P(p[0], p[1], H), sh = kk === 2 ? .62 : .42, cr = col.crest || 0;
        const rgb = [lerp(col.side[0], 199, cr), lerp(col.side[1], 70, cr), lerp(col.side[2], 52, cr)].map(v => Math.round(v * sh));
        c.fillStyle = 'rgba(' + rgb.join(',') + ',' + (.95 * a).toFixed(3) + ')';
        c.beginPath(); c.moveTo(p1[0], p1[1]); c.lineTo(p2[0], p2[1]); c.lineTo(p3[0], p3[1]); c.lineTo(p4[0], p4[1]); c.closePath(); c.fill(); });
      const tp = cn.map(p => P(p[0], p[1], H)); c.beginPath(); c.moveTo(tp[0][0], tp[0][1]); for (let kk = 1; kk < 4; kk++) c.lineTo(tp[kk][0], tp[kk][1]); c.closePath();
      const m = 1 + 1.7 * V.hk; c.fillStyle = 'rgba(' + col.top.slice(0, 3).join(',') + ',' + cl(col.top[3] * m * a, 0, 1).toFixed(3) + ')'; c.fill();
      if (col.crest > .02) { c.fillStyle = 'rgba(229,107,94,' + (.85 * col.crest * V.hk).toFixed(3) + ')'; c.fill(); }
      c.strokeStyle = 'rgba(' + col.line.slice(0, 3).join(',') + ',' + cl(col.line[3] + .25 * V.hk * a, 0, 1).toFixed(3) + ')'; c.lineWidth = 1.5; c.stroke(); });
    c.setTransform(1, 0, 0, 1, 0, 0); };

  /* ---------------- split-panel slam ---------------- */
  REEL.slam = (host, o) => { o = o || {}; const W = o.w || 1280, H = o.h || 720, mk = top => { const e = host.ownerDocument.createElement('div');
      e.style.cssText = 'position:absolute;left:0;top:' + top + 'px;width:' + W + 'px;height:' + (H / 2 + 1) + 'px;opacity:0;pointer-events:none;z-index:' + (o.z || 60) + ';background:' +
        (o.background || 'radial-gradient(ellipse 80% 120% at 50% 100%,#E0624A 0%,' + T().accent + ' 55%,#A8382A 100%)'); host.appendChild(e); return e; };
    const P2 = [mk(0), mk(H / 2 - 1)];
    return { panels: P2, draw(t, at) { const on = t >= at - (o.shut || .16) && t < at + (o.open || .32) + .08, sp = in3(rmp(t, at - .02, at + (o.open || .32)));
      P2.forEach((p, i) => { p.style.opacity = on ? '1' : '0'; p.style.transform = 'translateY(' + ((i ? 1 : -1) * (H / 2 + 20) * sp).toFixed(1) + 'px)'; }); } }; };

  /* ---------------- outline marquee ---------------- */
  REEL.marquee = (el, t, t0, o) => { o = o || {}; const reps = o.reps || 4, w = el.scrollWidth / reps || 2400, v = (o.speed || 70) * (t - t0);
    el.style.transform = 'translateX(' + (o.dir < 0 ? -w + ((v % w) + w) % w : -(((v % w) + w) % w)).toFixed(1) + 'px)'; };

  /* ---------------- liquid core (WebGL) ---------------- */
  const VS = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
  const FS = ['precision highp float;uniform vec2 R;uniform vec4 B[8];uniform float T,WOB;uniform vec3 COL;',
    'float sm(float a,float b,float k){float h=clamp(.5+.5*(b-a)/k,0.,1.);return mix(b,a,h)-k*h*(1.-h);}',
    'float map(vec3 p){float d=1e5;for(int i=0;i<8;i++){vec4 b=B[i];if(b.w>0.001)d=sm(d,length(p-b.xyz)-b.w,.32);}',
    ' return d+WOB*.022*sin(p.x*7.+T*2.3)*sin(p.y*6.+T*1.9)*sin(p.z*7.+T*1.4);}',
    'vec3 nrm(vec3 p){vec2 e=vec2(.002,-.002);return normalize(e.xyy*map(p+e.xyy)+e.yyx*map(p+e.yyx)+e.yxy*map(p+e.yxy)+e.xxx*map(p+e.xxx));}',
    'void main(){vec2 uv=(gl_FragCoord.xy-.5*R)/(.5*R.y);vec3 ro=vec3(uv,2.2),rd=vec3(0.,0.,-1.);float t=0.,md=1e5;bool hit=false;',
    ' for(int i=0;i<44;i++){float d=map(ro+rd*t);md=min(md,d);if(d<.0015){hit=true;break;}t+=d*.92;if(t>4.4)break;}',
    ' float px=2./R.y;float a=hit?1.:clamp(1.-md/(1.6*px),0.,1.);if(a<=0.){gl_FragColor=vec4(0.);return;}',
    ' vec3 p=ro+rd*t;vec3 n=nrm(p);vec3 L=normalize(vec3(-.45,.62,.66));float df=max(dot(n,L),0.);',
    ' vec3 h=normalize(L-rd);float sp=pow(max(dot(n,h),0.),70.);float sp2=pow(max(dot(n,normalize(vec3(.6,-.2,.8)-rd)),0.),18.);',
    ' float fr=pow(1.-max(dot(n,-rd),0.),2.6);vec3 rf=reflect(rd,n);float sky=smoothstep(-.2,.9,rf.y);',
    ' vec3 col=COL*(.30+.78*df)+vec3(1.,.55,.42)*fr*.55+mix(vec3(.10,.03,.03),vec3(1.,.86,.74),sky)*.22*fr;',
    ' col+=vec3(1.,.97,.92)*sp*1.1+vec3(1.,.72,.6)*sp2*.18;col=col/(1.+col*.18);gl_FragColor=vec4(col*a,a);}'].join('\n');
  REEL.blob = (parent, x, y, w, h, o) => { o = o || {}; const scale = o.scale || 1.25, doc = parent.ownerDocument, cv = doc.createElement('canvas');
    cv.style.cssText = 'position:absolute;left:' + x + 'px;top:' + y + 'px;width:' + w + 'px;height:' + h + 'px;pointer-events:none'; parent.appendChild(cv);
    cv.width = Math.round(w * scale); cv.height = Math.round(h * scale);
    const g = cv.getContext('webgl', { alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true, antialias: false });
    if (!g) return { el: cv, gl: false, draw() {} };
    const sh = (ty, src) => { const s = g.createShader(ty); g.shaderSource(s, src); g.compileShader(s); if (!g.getShaderParameter(s, g.COMPILE_STATUS)) throw new Error('reel.js blob: ' + g.getShaderInfoLog(s)); return s; };
    const pr = g.createProgram(); g.attachShader(pr, sh(g.VERTEX_SHADER, VS)); g.attachShader(pr, sh(g.FRAGMENT_SHADER, FS)); g.linkProgram(pr); g.useProgram(pr);
    const bf = g.createBuffer(); g.bindBuffer(g.ARRAY_BUFFER, bf); g.bufferData(g.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), g.STATIC_DRAW);
    const lp = g.getAttribLocation(pr, 'p'); g.enableVertexAttribArray(lp); g.vertexAttribPointer(lp, 2, g.FLOAT, false, 0, 0);
    const U = n => g.getUniformLocation(pr, n), uR = U('R'), uB = U('B'), uT = U('T'), uW = U('WOB'), uC = U('COL');
    const hex = o.color || T().accent, col = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255 * .93);
    g.viewport(0, 0, cv.width, cv.height);
    return { el: cv, gl: true, x, y, w, h,
      draw(balls, t, wob) { const arr = new Float32Array(32), H2 = h / 2;
        (balls || []).slice(0, 8).forEach((b, i) => { arr[i * 4] = (b[0] - x - w / 2) / H2; arr[i * 4 + 1] = -(b[1] - y - h / 2) / H2; arr[i * 4 + 2] = b[3] || 0; arr[i * 4 + 3] = Math.max(0, b[2] / H2); });
        g.uniform2f(uR, cv.width, cv.height); g.uniform4fv(uB, arr); g.uniform1f(uT, t); g.uniform1f(uW, wob == null ? 1 : wob); g.uniform3f(uC, col[0], col[1], col[2]);
        g.clearColor(0, 0, 0, 0); g.clear(g.COLOR_BUFFER_BIT); g.drawArrays(g.TRIANGLES, 0, 3); } }; };

  /* ---------------- selftest (pure parts, no DOM) ---------------- */
  function rec(W, H) { const log = []; let alpha = 1, fill = '';
    const ctx = { canvas: { width: W, height: H }, set globalAlpha(v) { alpha = v; }, get globalAlpha() { return alpha; }, set fillStyle(v) { fill = v; }, get fillStyle() { return fill; },
      strokeStyle: '', lineWidth: 1, lineCap: '', font: '', textBaseline: '', filter: 'none',
      save() {}, restore() {}, setTransform() {}, clearRect() {}, beginPath() {}, closePath() {}, moveTo(x, y) { log.push(['m', +x.toFixed(2), +y.toFixed(2)]); },
      lineTo(x, y) { log.push(['l', +x.toFixed(2), +y.toFixed(2)]); }, stroke() { log.push(['s', +alpha.toFixed(3)]); }, fill() { log.push(['f', fill, +alpha.toFixed(3)]); },
      fillRect(x, y, w, h) { log.push(['r', fill, +w.toFixed(2), +h.toFixed(2), x, y]); }, arc() {}, ellipse(x, y, rx) { log.push(['e', +rx.toFixed(2)]); },
      measureText(s) { return { width: s.length * 6 }; }, fillText(s) { log.push(['t', s]); } };
    return { ctx, log, cv: { width: W, height: H, getContext: () => ctx } }; }
  function selftest() { const fails = [], ok = (c, m) => { if (!c) fails.push(m); };
    ok(REEL.decode('FOUR WEEKS', .3, 4) === REEL.decode('FOUR WEEKS', .3, 4), 'decode not deterministic');
    ok(REEL.decode('FOUR WEEKS', 1, 4) === 'FOUR WEEKS', 'decode does not resolve at u=1');
    const cuts = [10];
    ok(REEL.coverAt(10, { cuts }) > .99, 'stinger not fully covering at the cut');
    ok(REEL.coverAt(9.5, { cuts }) === 0 && REEL.coverAt(10.5, { cuts }) === 0, 'stinger leaks outside its window');
    { const R1 = rec(1920, 1080); REEL.stinger(R1.cv, 10, { cuts }); let area = 0; R1.log.forEach(e => { if (e[0] === 'r' && e[1] === REEL.tokens.navy) area += e[2] * e[3]; });
      ok(area >= 1920 * 1080 * .999, 'stinger navy cover < frame area at the cut (' + Math.round(area) + ')'); }
    { let threw = false; try { REEL.stinger(rec(64, 36).cv, 0, { cuts, cover: .5, uncover: .5 }); } catch (e) { threw = true; } ok(threw, 'stinger accepted a window > 0.8 s'); }
    { const A = rec(1920, 1080), B = rec(1920, 1080); REEL.streaks(A.ctx, 640, 300, .4); REEL.streaks(B.ctx, 640, 300, .4); ok(JSON.stringify(A.log) === JSON.stringify(B.log) && A.log.length > 100, 'streaks not deterministic'); }
    { const A = rec(1920, 1080); REEL.streaks(A.ctx, 640, 300, 0); REEL.rings(A.ctx, 640, 300, 1); ok(A.log.length === 0, 'streaks/rings draw outside 0<u<1'); }
    { const g = { x: 332, y: 176, cols: 13, rows: 7, pitch: 48, size: 40 }, V = REEL.view(10, { grid: g, flatAt: 9 });
      ok(V.hk === 0 && V.pit === 0 && V.yaw === 0, 'view does not reach top-down after flatAt');
      let worst = 0; for (let c = 0; c < 13; c++) for (let r = 0; r < 7; r++) { const x = g.x + c * 48 + 20, y = g.y + r * 48 + 20, p = REEL.project(x, y, 37, V, g); worst = Math.max(worst, Math.abs(p[0] - x), Math.abs(p[1] - y)); }
      ok(worst < 1e-6, 'flattened voxel field does not land on the flat grid (max err ' + worst + ' px)');
      const V2 = REEL.view(1, { grid: g, flatAt: 9 }); ok(V2.hk === 1 && V2.pit > 0, 'view not tilted before the flatten'); }
    ok(REEL.smear(0) === 'none' && /px/.test(REEL.smear(.5)), 'smear');
    { const R1 = rec(1920, 1080); REEL.hud(R1.cv, 5, { chapters: [[0, 'One'], [4, 'Two']] }); ok(R1.log.some(e => e[0] === 't' && e[1] === '02 / 02'), 'hud chapter index'); }
    return { ok: !fails.length, fails, checks: 13 }; }
  function cli(argv) { const out = s => process.stdout.write(JSON.stringify(s, null, 2) + '\n');
    if (argv.includes('--selftest')) { const r = selftest(); out(r); process.exit(r.ok ? 0 : 1); }
    process.stdout.write('reel.js — REEL showreel motion (pure functions of t)\n  node lib/reel.js --selftest\n'); process.exit(argv.includes('--help') || argv.includes('-h') ? 0 : 2); }
  REEL.selftest = selftest;
  root.REEL = REEL;
  if (IS_NODE && typeof module !== 'undefined' && module.exports) { module.exports = REEL; if (require.main === module) cli(process.argv.slice(2)); }
})(typeof window !== 'undefined' ? window : globalThis);
