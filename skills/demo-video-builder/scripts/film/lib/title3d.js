/* title3d.js — T3D: three.js title assemblies driven by the film clock (openers, act cards, closers).

   Three devices, all pure functions of a local time:
     T3D.shardTitle(host, o)   — the headline is cut into glass panes along a seeded Voronoi tiling; the panes fly in from
                                 depth with per-pane stagger and a gentle tumble, settle into the tiled headline, hold under a
                                 light sweep and a slow push, then fly out past the lens.
     T3D.portalTitle(host, o)  — the headline's outline, traced from its silhouette, assembles from scattered edge pieces.
                                 Cheaper than the shards (two draw calls); the fallback for weak GPUs.
     T3D.depthStack(host, cards, o) — camera-facing cards at increasing depth with a dolly through them (parallax by depth).
                                 Footage cards are only scaled and translated: never tilted, fogged or tinted.

   Contract (same as every v5 layer): build once, then state.seek(localT) draws that instant and nothing else. One
   WebGLRenderer per state, created once, preserveDrawingBuffer on (the frame renderer screenshots the canvas), no
   animation loop, no wall clock, no Math.random (MOTION.rng(seed) only). Software GL (ANGLE/SwiftShader) is the target.

   Loading (three is ESM-only; d3-delaunay is a UMD script; both from the project's node_modules, never a CDN):
     <script src="../node_modules/d3-delaunay/dist/d3-delaunay.min.js"></script>
     <script src="lib/motion.js"></script>              <!-- rng + ease vocabulary -->
     <script src="lib/title3d.js"></script>
     const ready = T3D.load('../node_modules/three/build/three.module.js');     // once, before the first build
     ready.then(() => { title = T3D.shardTitle($('#gl'), { text: 'SEMANTIC\nREASONING', seed: 7 }); });
     window.__seek = t => ready.then(() => frame(t));   // the renderer awaits the promise; __step may stay synchronous

   Colour: T3D works in display space — the palette hex values are what reaches the pixels (ColorManagement off,
   linear output); no tone mapping. Stage units are CSS pixels of the 1280x720 stage on the z = 0 plane. */
(function (root) {
  'use strict';
  const W = 1280, H = 720;
  const PAL = { navy: 0x082A34, navy2: 0x204A56, ink: 0xE9F3F9, cream: 0xECDEC3, coral: 0xE56B5E, mint: 0x81A9AB, gold: 0xE8C874 };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, u) => a + (b - a) * u;
  /* eases — the same vocabulary motion.js names (power/expo/sine/back), as plain functions of u in [0,1] */
  const E = {
    p2o: u => { u = clamp(u, 0, 1); return 1 - (1 - u) * (1 - u); },
    p3o: u => { u = clamp(u, 0, 1); return 1 - Math.pow(1 - u, 3); },
    p4o: u => { u = clamp(u, 0, 1); return 1 - Math.pow(1 - u, 4); },
    p2i: u => { u = clamp(u, 0, 1); return u * u; },
    p3i: u => { u = clamp(u, 0, 1); return u * u * u; },
    expoO: u => { u = clamp(u, 0, 1); return u >= 1 ? 1 : 1 - Math.pow(2, -10 * u); },
    sineIO: u => 0.5 - 0.5 * Math.cos(clamp(u, 0, 1) * Math.PI),
    backO: (u, s) => { u = clamp(u, 0, 1); s = s === undefined ? 1.25 : s; const v = u - 1; return 1 + v * v * ((s + 1) * v + s); }
  };
  /* seeded PRNG: MOTION.rng when motion.js is loaded; the same generator inline so a bare test page agrees */
  function mulberry(seed) { let s = (seed >>> 0) || 1; return () => { s = (s + 0x6D2B79F5) >>> 0; let x = Math.imul(s ^ (s >>> 15), 1 | s); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }
  const rng = seed => (root.MOTION && root.MOTION.rng) ? root.MOTION.rng(seed) : mulberry(seed);
  function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  const hex3 = h => [((h >> 16) & 255) / 255, ((h >> 8) & 255) / 255, (h & 255) / 255];
  const toHex = c => typeof c === 'number' ? c : parseInt(String(c).replace('#', ''), 16);

  /* ---------- three: resolved once through a dynamic import of the project's copy ---------- */
  let THREE = root.THREE || null, loadP = null;
  function load(url) {
    if (THREE) return Promise.resolve(THREE);
    // import() inside this (classic) script would resolve against lib/, so resolve the scene's path against the document first
    const abs = new URL(url || '../node_modules/three/build/three.module.js', (root.document && root.document.baseURI) || location.href).href;
    if (!loadP) loadP = import(abs).then(m => {
      THREE = m; root.THREE = m;
      if (m.ColorManagement) m.ColorManagement.enabled = false;        // display-space colours: palette hex in = palette hex out
      return m;
    });
    return loadP;
  }
  function ready() { return THREE ? Promise.resolve(THREE) : (loadP || Promise.reject(new Error('title3d.js: call T3D.load(<path to three.module.js>) first'))); }
  function need() { if (!THREE) throw new Error('title3d.js: three is not loaded yet — await T3D.load(...) before building a title'); return THREE; }
  function needD3() { const d3 = root.d3; if (!d3 || !d3.Delaunay) throw new Error('title3d.js: load d3-delaunay (node_modules/d3-delaunay/dist/d3-delaunay.min.js) before lib/title3d.js'); return d3; }

  /* ---------- rig: one renderer + camera per state; the canvas fills the host ----------
     Anti-aliasing is the one cost that matters in software GL. Measured on SwiftShader (ANGLE/Vulkan, Subzero) at
     1920x1080 with 10 panes, GL time above the ~100 ms DOM-screenshot baseline, min of 3 interleaved passes:
     none 70 ms · 4x MSAA 105 ms · own edge-soften pass 121 ms · 2x supersample 257 ms · physical transmission 1390 ms.
     The pane rims are sub-pixel geometry, so a post pass cannot recover their dropouts: MSAA is both cheaper and
     cleaner, and 'auto' (default) means 'msaa' on every GL. o.aa: 'msaa' | 'post' | 'ssaa' | 'none' force a mode. */
  let softwareGL = null;
  function isSoftwareGL() {
    if (softwareGL !== null) return softwareGL;
    try { const c = document.createElement('canvas'); const gl = c.getContext('webgl2') || c.getContext('webgl'); const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
      const s = gl ? String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) : 'software';
      softwareGL = /swiftshader|llvmpipe|software|subzero/i.test(s); const lose = gl && gl.getExtension('WEBGL_lose_context'); if (lose) lose.loseContext();
    } catch (e) { softwareGL = true; }
    return softwareGL;
  }
  const AA_VS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';
  /* edge soften: where the local luma range says "edge", average two half-pixel taps across the edge's gradient */
  const AA_FS = [
    'precision highp float; varying vec2 vUv; uniform sampler2D uMap; uniform vec2 uTexel; uniform float uLo, uHi;',
    'float lum(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }',
    'void main(){ vec3 c = texture2D(uMap, vUv).rgb; float l = lum(c);',
    '  float n = lum(texture2D(uMap, vUv + vec2(0.0, -uTexel.y)).rgb), s = lum(texture2D(uMap, vUv + vec2(0.0, uTexel.y)).rgb);',
    '  float e = lum(texture2D(uMap, vUv + vec2(uTexel.x, 0.0)).rgb), w = lum(texture2D(uMap, vUv + vec2(-uTexel.x, 0.0)).rgb);',
    '  float range = max(max(l, n), max(max(s, e), w)) - min(min(l, n), min(min(s, e), w));',
    '  vec2 dir = abs(n - s) >= abs(e - w) ? vec2(0.0, uTexel.y) : vec2(uTexel.x, 0.0);',
    '  vec3 a = (texture2D(uMap, vUv + dir * 0.75).rgb + texture2D(uMap, vUv - dir * 0.75).rgb) * 0.5;',
    '  gl_FragColor = vec4(mix(c, a, smoothstep(uLo, uHi, range)), 1.0); }'].join('\n');
  const SS_FS = [
    'precision highp float; varying vec2 vUv; uniform sampler2D uMap; uniform vec2 uTexel;',
    'void main(){ vec3 c = texture2D(uMap, vUv + uTexel * vec2(-0.5, -0.5)).rgb + texture2D(uMap, vUv + uTexel * vec2(0.5, -0.5)).rgb + texture2D(uMap, vUv + uTexel * vec2(-0.5, 0.5)).rgb + texture2D(uMap, vUv + uTexel * vec2(0.5, 0.5)).rgb;',
    '  gl_FragColor = vec4(c * 0.25, 1.0); }'].join('\n');
  function rig(host, o) {
    const T = need();
    const canvas = document.createElement('canvas');
    canvas.className = 't3d'; canvas.setAttribute('data-diegetic', '');
    canvas.style.cssText = 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px;display:block;pointer-events:none';
    host.appendChild(canvas);
    let aa = o.aa || (o.antialias === false ? 'none' : 'auto');
    if (aa === 'auto') aa = 'msaa';
    const dpr = o.dpr || root.devicePixelRatio || 1;
    const renderer = new T.WebGLRenderer({ canvas, antialias: aa === 'msaa', alpha: false, preserveDrawingBuffer: true, stencil: false, powerPreference: 'low-power' });
    renderer.setPixelRatio(dpr);
    renderer.setSize(W, H, false);
    if (T.LinearSRGBColorSpace) renderer.outputColorSpace = T.LinearSRGBColorSpace;
    renderer.toneMapping = T.NoToneMapping;
    const bg = toHex((o.colors && o.colors.bg) || PAL.navy);
    renderer.setClearColor(new T.Color(bg), 1);
    const fov = o.fov || 30, camZ = (H / 2) / Math.tan(fov * Math.PI / 360);
    const camera = new T.PerspectiveCamera(fov, W / H, 1, 8000);
    camera.position.set(0, 0, camZ);
    const scene = new T.Scene();
    const R = { canvas, renderer, camera, scene, camZ, bg, aa, dpr };
    if (aa === 'post' || aa === 'ssaa') {
      const k = aa === 'ssaa' ? 2 : 1, bw = Math.round(W * dpr * k), bh = Math.round(H * dpr * k);
      const rt = new T.WebGLRenderTarget(bw, bh, { minFilter: T.LinearFilter, magFilter: T.LinearFilter, depthBuffer: true, stencilBuffer: false, generateMipmaps: false });
      const mat = new T.ShaderMaterial({ depthTest: false, depthWrite: false, vertexShader: AA_VS, fragmentShader: aa === 'ssaa' ? SS_FS : AA_FS,
        uniforms: { uMap: { value: rt.texture }, uTexel: { value: new T.Vector2(1 / bw, 1 / bh) }, uLo: { value: 0.05 }, uHi: { value: 0.22 } } });
      const quad = new T.Mesh(new T.PlaneGeometry(2, 2), mat); quad.frustumCulled = false;
      const qs = new T.Scene(); qs.add(quad); const qc = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      R.post = { rt, quad, qs, qc };
    }
    R.draw = () => {
      if (R.post) { renderer.setRenderTarget(R.post.rt); renderer.render(scene, camera); renderer.setRenderTarget(null); renderer.render(R.post.qs, R.post.qc); }
      else renderer.render(scene, camera);
    };
    return R;
  }
  /* a soft light pool behind everything: flat navy with a faint wash (strength 0 = pure clear colour, no draw call) */
  function groundPlane(R, o) {
    const T = THREE; const g = (o.glow === undefined ? 0.10 : o.glow);
    if (g <= 0) return null;
    const geo = new T.PlaneGeometry(2, 2);
    const mat = new T.ShaderMaterial({ depthWrite: false, depthTest: false, uniforms: { uBg: { value: new T.Vector3(...hex3(R.bg)) }, uWash: { value: new T.Vector3(...hex3(toHex((o.colors && o.colors.glow) || PAL.mint))) }, uG: { value: g }, uC: { value: new T.Vector2(o.glowAt ? o.glowAt[0] : 0.5, o.glowAt ? o.glowAt[1] : 0.46) } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.9999, 1.0); }',
      fragmentShader: 'precision highp float; varying vec2 vUv; uniform vec3 uBg, uWash; uniform float uG; uniform vec2 uC;\n' +
        'void main(){ vec2 d = (vUv - uC) * vec2(1.3, 1.0); float r = dot(d, d); float pool = exp(-r * 7.0); float edge = smoothstep(0.1, 0.9, length((vUv - 0.5) * vec2(1.0, 1.2)) ); \n' +
        ' vec3 c = mix(uBg, uWash, pool * uG) * (1.0 - edge * 0.22); gl_FragColor = vec4(c, 1.0); }' });
    const m = new T.Mesh(geo, mat); m.frustumCulled = false; m.renderOrder = -10; R.scene.add(m); return m;
  }

  /* ---------- headline raster: silhouette + glyph texture ---------- */
  function raster(text, o) {
    const lines = String(text).split('\n'); const S = 2;
    const c = document.createElement('canvas'); c.width = W * S; c.height = H * S;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.scale(S, S); g.fillStyle = '#ffffff'; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
    let size = o.size || 120; const maxW = W * (o.fit === undefined ? 0.86 : o.fit);
    const setFont = s => { g.font = (o.weight || 400) + ' ' + s + 'px ' + (o.font || 'Georgia, serif'); try { g.letterSpacing = (o.tracking === undefined ? 0.02 : o.tracking) + 'em'; } catch (e) { /* older canvas */ } };
    setFont(size);
    const wmax = Math.max.apply(null, lines.map(l => g.measureText(l).width));
    if (wmax > maxW) { size = Math.floor(size * maxW / wmax); setFont(size); }
    const lh = size * (o.lineHeight || 1.04), total = lh * lines.length;
    lines.forEach((l, k) => g.fillText(l, W / 2 + (o.dx || 0), H / 2 - total / 2 + lh * k + lh * 0.5 + size * 0.34 + (o.dy || 0)));
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let x0 = c.width, y0 = c.height, x1 = -1, y1 = -1;
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) if (d[(y * c.width + x) * 4 + 3] > 96) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    if (x1 < 0) throw new Error('title3d.js: the headline rasterised to nothing (font not available?)');
    const pad = o.pad === undefined ? 10 : o.pad;
    const bbox = { x0: x0 / S - pad, y0: y0 / S - pad, x1: x1 / S + pad, y1: y1 / S + pad };
    const inside = (x, y) => { const ix = Math.round(x * S), iy = Math.round(y * S); if (ix < 0 || iy < 0 || ix >= c.width || iy >= c.height) return false; return d[(iy * c.width + ix) * 4 + 3] > 96; };
    const crop = document.createElement('canvas'); crop.width = Math.ceil((bbox.x1 - bbox.x0) * S); crop.height = Math.ceil((bbox.y1 - bbox.y0) * S);
    crop.getContext('2d').drawImage(c, bbox.x0 * S, bbox.y0 * S, crop.width, crop.height, 0, 0, crop.width, crop.height);
    return { size, bbox, inside, tex: crop, S };
  }

  /* ---------- tiling: seeds inside the silhouette, relaxed twice, cut into cells with organic shared edges ---------- */
  function tiling(ras, n, seed) {
    const d3 = needD3(); const b = ras.bbox, bw = b.x1 - b.x0, bh = b.y1 - b.y0, R = rng(seed);
    let pts = [], dmin = Math.sqrt(bw * bh / n) * 0.74, tries = 0;
    while (pts.length < n && tries < 40000) {
      tries++; const x = b.x0 + R() * bw, y = b.y0 + R() * bh;
      if (!ras.inside(x, y)) continue;
      let ok = true; for (const p of pts) { if (Math.hypot(p[0] - x, p[1] - y) < dmin) { ok = false; break; } }
      if (ok) pts.push([x, y]);
      if (tries % 1500 === 0) dmin *= 0.85;
    }
    const bounds = [b.x0, b.y0, b.x1, b.y1];
    for (let k = 0; k < 2; k++) {                                     // two relaxation steps: even cells, still seeded
      const v = d3.Delaunay.from(pts).voronoi(bounds);
      pts = pts.map((p, i) => { const poly = v.cellPolygon(i); if (!poly) return p; const c = centroid(poly); return [lerp(p[0], c[0], 0.55), lerp(p[1], c[1], 0.55)]; });
    }
    const v = d3.Delaunay.from(pts).voronoi(bounds);
    return pts.map((p, i) => { const poly = v.cellPolygon(i); return { seed: p, poly: poly ? dedupe(poly) : null }; }).filter(c => c.poly && c.poly.length >= 3);
  }
  function centroid(poly) { let x = 0, y = 0, n = 0; for (const p of poly) { x += p[0]; y += p[1]; n++; } return [x / n, y / n]; }
  function dedupe(poly) { const out = []; for (const p of poly) { const q = out[out.length - 1]; if (!q || Math.hypot(q[0] - p[0], q[1] - p[1]) > 1e-6) out.push(p); } if (out.length > 1 && Math.hypot(out[0][0] - out[out.length - 1][0], out[0][1] - out[out.length - 1][1]) < 1e-6) out.pop(); return out; }
  /* shared-edge jitter: a vertex or edge is displaced by a hash of its position, so neighbouring cells agree and never overlap */
  function organic(poly, b, amp, amp2) {
    const key = p => Math.round(p[0] * 8) + ',' + Math.round(p[1] * 8);
    const jit = k => { const h = hash(k); return [((h & 0xffff) / 65535) * 2 - 1, (((h >>> 16) & 0xffff) / 65535) * 2 - 1]; };
    const onX = p => Math.abs(p[0] - b.x0) < 1e-3 || Math.abs(p[0] - b.x1) < 1e-3, onY = p => Math.abs(p[1] - b.y0) < 1e-3 || Math.abs(p[1] - b.y1) < 1e-3;
    const V = poly.map(p => { const j = jit(key(p)); return [p[0] + (onX(p) ? 0 : j[0] * amp), p[1] + (onY(p) ? 0 : j[1] * amp), onX(p), onY(p)]; });
    const out = [];
    for (let i = 0; i < V.length; i++) {
      const a = V[i], c = V[(i + 1) % V.length]; out.push([a[0], a[1]]);
      const ka = key(a), kc = key(c), fwd = ka < kc; const p = fwd ? a : c, q = fwd ? c : a;
      const dx = q[0] - p[0], dy = q[1] - p[1], L = Math.hypot(dx, dy); if (L < 6) continue;
      const boundary = (a[2] && c[2] && Math.abs(a[0] - c[0]) < 1e-3) || (a[3] && c[3] && Math.abs(a[1] - c[1]) < 1e-3);
      const h = boundary ? 0 : jit(ka + '|' + kc)[0] * amp2 * Math.min(1, L / 40);
      out.push([(a[0] + c[0]) / 2 - dy / L * h, (a[1] + c[1]) / 2 + dx / L * h]);
    }
    return out;
  }
  function inset(poly, gap) { const c = centroid(poly); return poly.map(p => { const dx = c[0] - p[0], dy = c[1] - p[1], L = Math.hypot(dx, dy) || 1; const g = Math.min(gap, L * 0.4); return [p[0] + dx / L * g, p[1] + dy / L * g]; }); }
  /* a THREE.Shape in pane-local world units (y up, centred on the pane centroid) with rounded corners */
  function shapeOf(poly, cx, cy, round) {
    const T = THREE; const P = poly.map(p => [p[0] - W / 2 - cx, H / 2 - p[1] - cy]);
    const sh = new T.Shape(); const n = P.length; let first = null;
    for (let i = 0; i < n; i++) {
      const a = P[(i + n - 1) % n], b = P[i], c = P[(i + 1) % n];
      const l1 = Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, l2 = Math.hypot(c[0] - b[0], c[1] - b[1]) || 1, r = Math.min(round, l1 * 0.35, l2 * 0.35);
      const p1 = [b[0] + (a[0] - b[0]) / l1 * r, b[1] + (a[1] - b[1]) / l1 * r], p2 = [b[0] + (c[0] - b[0]) / l2 * r, b[1] + (c[1] - b[1]) / l2 * r];
      if (!first) { first = p1; sh.moveTo(p1[0], p1[1]); } else sh.lineTo(p1[0], p1[1]);
      sh.quadraticCurveTo(b[0], b[1], p2[0], p2[1]);
    }
    sh.lineTo(first[0], first[1]);
    return sh;
  }

  /* ---------- the pane shader: cheap studio shading that survives software GL ----------
     glass tint lit by one soft key, a fresnel rim, a sharp highlight, a travelling light band, glyph pixels on the caps,
     brighter edges on the extruded sides, fog by view depth folded into alpha (the fog colour is the clear colour). */
  const PANE_VS = [
    'varying vec3 vN; varying vec3 vVp; varying vec2 vUv; varying float vCap;',
    'void main(){ vUv = uv; vCap = step(0.5, abs(normal.z)); vec4 mv = modelViewMatrix * vec4(position, 1.0); vVp = mv.xyz;',
    '  vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * mv; }'].join('\n');
  const PANE_FS = [
    'precision highp float; varying vec3 vN; varying vec3 vVp; varying vec2 vUv; varying float vCap;',
    'uniform sampler2D uGlyph; uniform vec3 uGlass, uRim, uInk, uKey; uniform float uGlassA, uAlpha, uSweep, uFogNear, uFogFar, uInkMix;',
    'void main(){',
    '  vec3 N = normalize(vN); if (!gl_FrontFacing) N = -N; vec3 V = normalize(-vVp);',
    '  float ndv = max(dot(N, V), 0.0); float fres = pow(1.0 - ndv, 3.0);',
    '  vec3 L = normalize(uKey); float diff = 0.5 + 0.5 * dot(N, L);',
    '  vec3 Hv = normalize(L + V); float spec = pow(max(dot(N, Hv), 0.0), 70.0);',
    '  float band = exp(-pow((vVp.x / 640.0 - (uSweep * 2.6 - 1.3)) * 2.4, 2.0)) * step(0.001, uSweep) * step(uSweep, 0.999);',
    '  vec3 glass = uGlass * (0.55 + 0.45 * diff) + uRim * (fres * 0.9 + spec * 0.8 + band * 0.22);',
    '  float ga = clamp(uGlassA + fres * 0.55 + spec * 0.5 + band * 0.12, 0.0, 0.96);',
    '  float g = texture2D(uGlyph, vUv).a * vCap;',
    '  vec3 ink = uInk * (0.84 + 0.16 * diff) + uRim * spec * 0.35 + vec3(band * 0.10);',
    '  vec3 col = mix(glass, ink, g * uInkMix); float a = mix(ga, 1.0, g * uInkMix);',
    '  vec3 side = uRim * (0.55 + 0.45 * diff) + uRim * spec * 0.6; col = mix(col, side, (1.0 - vCap) * 0.8); a = mix(a, 0.92, (1.0 - vCap) * 0.8);',
    '  float fog = smoothstep(uFogNear, uFogFar, -vVp.z);',
    '  gl_FragColor = vec4(col, a * (1.0 - fog) * uAlpha); }'].join('\n');

  function paneMaterial(R, ras, colors, o) {
    const T = THREE;
    const tex = new T.CanvasTexture(ras.tex); tex.minFilter = T.LinearMipmapLinearFilter; tex.magFilter = T.LinearFilter; tex.generateMipmaps = true; tex.anisotropy = 1;
    const u = {
      uGlyph: { value: tex }, uGlass: { value: new T.Vector3(...hex3(colors.glass)) }, uRim: { value: new T.Vector3(...hex3(colors.rim)) }, uInk: { value: new T.Vector3(...hex3(colors.ink)) },
      uKey: { value: new T.Vector3(-0.45, 0.78, 0.42) }, uGlassA: { value: o.glassAlpha === undefined ? 0.26 : o.glassAlpha }, uAlpha: { value: 1 }, uSweep: { value: 0 },
      uFogNear: { value: R.camZ + (o.fogNear === undefined ? 180 : o.fogNear) }, uFogFar: { value: R.camZ + (o.fogFar === undefined ? 1250 : o.fogFar) }, uInkMix: { value: 1 }
    };
    return new T.ShaderMaterial({ uniforms: u, vertexShader: PANE_VS, fragmentShader: PANE_FS, transparent: true, depthWrite: true, side: T.DoubleSide });
  }
  /* the expensive alternative, kept for hardware GL: a real transmissive physical material lit by two lights */
  function physicalMaterial(R, ras, colors, o) {
    const T = THREE;
    const tex = new T.CanvasTexture(ras.tex); tex.minFilter = T.LinearMipmapLinearFilter; tex.magFilter = T.LinearFilter;
    R.scene.add(new T.AmbientLight(0xffffff, 0.55));
    const key = new T.DirectionalLight(0xffffff, 1.6); key.position.set(-500, 700, 900); R.scene.add(key);
    const rim = new T.DirectionalLight(colors.rim, 1.2); rim.position.set(600, 300, -400); R.scene.add(rim);
    R.scene.fog = new T.Fog(R.bg, R.camZ + (o.fogNear === undefined ? 220 : o.fogNear), R.camZ + (o.fogFar === undefined ? 1500 : o.fogFar));
    return new T.MeshPhysicalMaterial({ color: colors.glass, transmission: 0.82, roughness: 0.16, metalness: 0, thickness: 6, ior: 1.45, side: T.DoubleSide,
      emissive: colors.ink, emissiveMap: tex, emissiveIntensity: 1.0, transparent: true, opacity: 1 });
  }

  /* ========================================================================================================
     T3D.shardTitle(host, o)
     o: { text, font:'Georgia, serif', weight:400, size:120, fit:0.86, tracking:0.02, lineHeight:1.04, tiles:10, seed:1,
          colors:{glass:#204A56, rim:#E8C874, ink:#ECDEC3, fog/bg:#082A34, glow:#81A9AB}, glow:0.10,
          flyIn:2.3, flyOut:2.4, stagger:0.27, hold:1.6 (or total), thickness:6, gap:2.4, round:5, jitter:2.6,
          scatter:[260,600], depth:[900,1700], tumble:1.0, push:0.012, bevel:1.5, fogNear:180, fogFar:1250, glassAlpha:0.26,
          material:'shaded'|'physical' (physical = real transmission, hardware GL only: 1390 ms/frame on SwiftShader),
          aa:'auto'|'msaa'|'post'|'ssaa'|'none', dpr (default devicePixelRatio) }
     → state { seek(localT), hide(), show(), total, timings:{inEnd,outStart,total}, panes, canvas, dispose() }
     ======================================================================================================== */
  function shardTitle(host, o) {
    o = o || {}; const T = need();
    const colors = Object.assign({ glass: PAL.navy2, rim: PAL.gold, ink: PAL.cream, bg: PAL.navy, glow: PAL.mint }, o.colors || {});
    for (const k in colors) colors[k] = toHex(colors[k]); if (o.colors && o.colors.fog) colors.bg = toHex(o.colors.fog);
    const R = rig(host, Object.assign({}, o, { colors }));
    groundPlane(R, Object.assign({}, o, { colors }));
    const ras = raster(o.text || 'TITLE', o);
    const seed = o.seed === undefined ? 1 : o.seed, Rn = rng(seed * 7919 + 13);
    const cells = tiling(ras, clamp(o.tiles || 10, 2, 64), seed);
    const mat = (o.material === 'physical') ? physicalMaterial(R, ras, colors, o) : paneMaterial(R, ras, colors, o);
    const b = ras.bbox, bw = b.x1 - b.x0, bh = b.y1 - b.y0, cxAll = (b.x0 + b.x1) / 2 - W / 2, cyAll = H / 2 - (b.y0 + b.y1) / 2;
    const thick = o.thickness === undefined ? 6 : o.thickness;
    const panes = cells.map((cell, i) => {
      const poly = inset(organic(cell.poly, b, o.jitter === undefined ? 2.6 : o.jitter, (o.jitter === undefined ? 2.6 : o.jitter) * 0.9), o.gap === undefined ? 3.0 : o.gap);
      const c = centroid(poly), cx = c[0] - W / 2, cy = H / 2 - c[1];
      const geo = new T.ExtrudeGeometry(shapeOf(poly, cx, cy, o.round === undefined ? 5 : o.round), { depth: thick, bevelEnabled: true, bevelThickness: 1.1, bevelSize: o.bevel === undefined ? 1.5 : o.bevel, bevelSegments: 1, curveSegments: 3 });
      geo.translate(0, 0, -thick / 2);
      const pos = geo.attributes.position, uv = new Float32Array(pos.count * 2);
      for (let k = 0; k < pos.count; k++) { const wx = pos.getX(k) + cx, wy = pos.getY(k) + cy; uv[k * 2] = ((wx + W / 2) - b.x0) / bw; uv[k * 2 + 1] = 1 - ((H / 2 - wy) - b.y0) / bh; }
      geo.setAttribute('uv', new T.BufferAttribute(uv, 2));
      const m = new T.Mesh(geo, mat.clone()); m.frustumCulled = false; R.scene.add(m);
      // the pane's own flight: outward direction from the headline centre, bent a little, a depth of its own, a tumble
      const dx = cx - cxAll, dy = cy - cyAll, L = Math.hypot(dx, dy) || 1, bend = (Rn() - 0.5) * 1.2, ca = Math.cos(bend), sa = Math.sin(bend);
      const dir = [(dx * ca - dy * sa) / L, (dx * sa + dy * ca) / L];
      const sc = o.scatter || [260, 600], dp = o.depth || [900, 1700], tum = o.tumble === undefined ? 1.0 : o.tumble;
      return { mesh: m, cx, cy, dir, s0: lerp(sc[0], sc[1], Rn()), z0: -lerp(dp[0], dp[1], Rn()),
        rot0: [(Rn() - 0.5) * 2 * tum * 1.1, (Rn() - 0.5) * 2 * tum * 1.3, (Rn() - 0.5) * 2 * tum * 0.6],
        rot1: [(Rn() - 0.5) * 2 * tum * 0.5, (Rn() - 0.5) * 2 * tum * 0.7, (Rn() - 0.5) * 2 * tum * 0.35],
        out0: lerp(120, 260, Rn()), rank: 0 };
    });
    // arrival order: left to right with a seeded shuffle, so the headline assembles along the reading direction
    const order = panes.map((p, i) => ({ i, k: p.cx + (Rn() - 0.5) * bw * 0.35 })).sort((a, b2) => a.k - b2.k);
    order.forEach((e, r) => { panes[e.i].rank = panes.length > 1 ? r / (panes.length - 1) : 0; });

    const flyIn = o.flyIn === undefined ? 2.3 : o.flyIn, flyOut = o.flyOut === undefined ? 2.4 : o.flyOut, stagger = o.stagger === undefined ? 0.27 : o.stagger;
    let hold = o.hold === undefined ? 1.6 : o.hold;
    if (o.total !== undefined) hold = Math.max(0.3, o.total - (flyIn + stagger + flyOut));
    const inEnd = flyIn + stagger, outStart = inEnd + hold, total = outStart + flyOut, outDur = Math.max(0.3, flyOut - stagger);
    const push = o.push === undefined ? 0.012 : o.push;
    const isShaded = !(o.material === 'physical');

    function seek(lt) {
      lt = Number.isFinite(lt) ? lt : 0;
      // camera: the sanctioned slow push once the headline is assembled (1.2 %/s), carried through the exit
      const pushT = clamp(lt - inEnd, 0, total - inEnd);
      R.camera.position.z = R.camZ / (1 + push * pushT);
      const sweep = lt > inEnd && lt < outStart ? clamp((lt - inEnd) / hold, 0, 1) : (lt >= outStart ? 1 : 0);
      for (const p of panes) {
        const u = clamp((lt - stagger * p.rank) / flyIn, 0, 1);
        const v = clamp((lt - outStart - stagger * (1 - p.rank)) / outDur, 0, 1);
        // in: xy converge on a soft power2 (the scatter stays readable past mid-flight), the tumble resolves on power3,
        // depth travels on its own sine curve and lands with a small forward click in the last quarter
        const exy = E.p2o(u / 0.94), erot = E.p3o(u / 0.96), ez = E.sineIO(u), click = Math.sin(Math.PI * clamp((u - 0.74) / 0.26, 0, 1)) * 16;
        let x = p.cx + p.dir[0] * p.s0 * (1 - exy), y = p.cy + p.dir[1] * p.s0 * (1 - exy), z = p.z0 * (1 - ez) + click;
        let rx = p.rot0[0] * (1 - erot), ry = p.rot0[1] * (1 - erot), rz = p.rot0[2] * (1 - erot);
        let alpha = clamp(u / 0.12, 0, 1);
        if (v > 0) {
          // out: accelerate past the lens (power3.in), drift outward, a second tumble, gone before it covers the glass
          const ezo = E.p3i(v), exo = E.p2i(v);
          z += (R.camZ + 700) * ezo; x += p.dir[0] * p.out0 * exo; y += p.dir[1] * p.out0 * exo;
          rx += p.rot1[0] * exo; ry += p.rot1[1] * exo; rz += p.rot1[2] * exo;
          alpha *= 1 - clamp((v - 0.5) / 0.35, 0, 1);
        }
        p.mesh.position.set(x, y, z); p.mesh.rotation.set(rx, ry, rz);
        p.mesh.visible = alpha > 0.002 && u > 0;
        if (isShaded) { const U = p.mesh.material.uniforms; U.uAlpha.value = alpha; U.uSweep.value = sweep; }
        else p.mesh.material.opacity = alpha;
      }
      R.draw();
    }
    return state(R, seek, { inEnd, outStart, total }, { panes, raster: ras, cells });
  }

  /* ========================================================================================================
     T3D.portalTitle(host, o) — outline pieces assemble, hold, scatter. Two draw calls (core + halo), all motion on the GPU.
     o: { text, font, weight, size, fit, tracking, seed, colors:{line:#E8C874, glow:#81A9AB, bg:#082A34}, glow:0.08,
          flyIn:2.0, flyOut:1.6, stagger:0.5, hold:1.6 (or total), width:2.2, halo:7, piece:28, step:1.5,
          scatter:[280,620], depth:[500,1200], spin:1.4, push:0.012 }
     ======================================================================================================== */
  function portalTitle(host, o) {
    o = o || {}; const T = need();
    const colors = Object.assign({ line: PAL.gold, glow: PAL.mint, bg: PAL.navy }, o.colors || {});
    for (const k in colors) colors[k] = toHex(colors[k]);
    const R = rig(host, Object.assign({}, o, { colors: { bg: colors.bg, glow: colors.glow } }));
    groundPlane(R, Object.assign({ glow: 0.08 }, o, { colors: { bg: colors.bg, glow: colors.glow } }));
    const ras = raster(o.text || 'TITLE', o), b = ras.bbox;
    const pieces = outlinePieces(ras, o.step || 1.5, o.piece || 28);
    const seed = o.seed === undefined ? 1 : o.seed, Rn = rng(seed * 104729 + 7);
    const cx0 = (b.x0 + b.x1) / 2, cy0 = (b.y0 + b.y1) / 2, bw = b.x1 - b.x0;
    const sc = o.scatter || [280, 620], dp = o.depth || [500, 1200], spin = o.spin === undefined ? 1.4 : o.spin;
    const flyIn = o.flyIn === undefined ? 2.0 : o.flyIn, flyOut = o.flyOut === undefined ? 1.6 : o.flyOut, stagger = o.stagger === undefined ? 0.5 : o.stagger;
    let hold = o.hold === undefined ? 1.6 : o.hold; if (o.total !== undefined) hold = Math.max(0.3, o.total - (flyIn + stagger + flyOut));
    const inEnd = flyIn + stagger, outStart = inEnd + hold, total = outStart + flyOut, outDur = Math.max(0.3, flyOut - stagger * 0.6);
    // geometry: one continuous ribbon per piece — two vertices per polyline point, joined across neighbours, so curves
    // stay solid; every vertex carries its piece's flight (scatter, spin, delays) and its neighbours for the screen normal
    let nPts = 0, nSeg = 0; for (const pc of pieces) { nPts += pc.length; nSeg += pc.length - 1; }
    const pos = new Float32Array(nPts * 2 * 3), prev = new Float32Array(nPts * 2 * 2), next = new Float32Array(nPts * 2 * 2), side = new Float32Array(nPts * 2), pivot = new Float32Array(nPts * 2 * 2);
    const scat = new Float32Array(nPts * 2 * 3), spn = new Float32Array(nPts * 2), dly = new Float32Array(nPts * 2), dlo = new Float32Array(nPts * 2);
    const idx = new Uint32Array(nSeg * 6); let v = 0, q = 0;
    for (const pc of pieces) {
      const pv = centroid(pc); const px = pv[0] - W / 2, py = H / 2 - pv[1];
      const dx = pv[0] - cx0, dy = pv[1] - cy0, L = Math.hypot(dx, dy) || 1, bend = (Rn() - 0.5) * 1.4, ca = Math.cos(bend), sa = Math.sin(bend);
      const dirx = (dx * ca - dy * sa) / L, diry = -(dx * sa + dy * ca) / L, rad = lerp(sc[0], sc[1], Rn());
      const S = [dirx * rad, diry * rad, -lerp(dp[0], dp[1], Rn())], SP = (Rn() - 0.5) * 2 * spin;
      const D = stagger * clamp((pv[0] - b.x0) / bw * 0.75 + Rn() * 0.25, 0, 1), DO = stagger * 0.6 * Rn();
      const Wd = pc.map(p => [p[0] - W / 2, H / 2 - p[1]]);
      const v0 = v;
      for (let i = 0; i < Wd.length; i++) {
        const P = Wd[i], Pp = Wd[Math.max(0, i - 1)], Pn = Wd[Math.min(Wd.length - 1, i + 1)];
        for (let k = 0; k < 2; k++) {
          pos[v * 3] = P[0]; pos[v * 3 + 1] = P[1]; pos[v * 3 + 2] = 0; prev[v * 2] = Pp[0]; prev[v * 2 + 1] = Pp[1]; next[v * 2] = Pn[0]; next[v * 2 + 1] = Pn[1];
          side[v] = k ? 1 : -1; pivot[v * 2] = px; pivot[v * 2 + 1] = py;
          scat[v * 3] = S[0]; scat[v * 3 + 1] = S[1]; scat[v * 3 + 2] = S[2]; spn[v] = SP; dly[v] = D; dlo[v] = DO; v++;
        }
        if (i > 0) { const c = v0 + i * 2; idx.set([c - 2, c - 1, c, c - 1, c + 1, c], q * 6); q++; }
      }
    }
    const geo = new T.BufferGeometry();
    geo.setAttribute('position', new T.BufferAttribute(pos, 3)); geo.setAttribute('aPrev', new T.BufferAttribute(prev, 2)); geo.setAttribute('aNext', new T.BufferAttribute(next, 2)); geo.setAttribute('aSide', new T.BufferAttribute(side, 1));
    geo.setAttribute('aPivot', new T.BufferAttribute(pivot, 2)); geo.setAttribute('aScatter', new T.BufferAttribute(scat, 3)); geo.setAttribute('aSpin', new T.BufferAttribute(spn, 1));
    geo.setAttribute('aDelay', new T.BufferAttribute(dly, 1)); geo.setAttribute('aDelayOut', new T.BufferAttribute(dlo, 1)); geo.setIndex(new T.BufferAttribute(idx, 1));
    const VS = [
      'attribute vec2 aPrev, aNext, aPivot; attribute vec3 aScatter; attribute float aSide, aSpin, aDelay, aDelayOut;',
      'uniform float uT, uIn, uOutStart, uOut, uWidth, uFogNear, uFogFar; uniform vec2 uRes; varying float vAcross, vAlpha, vX;',
      'float p4o(float u){ u = clamp(u, 0.0, 1.0); float v = 1.0 - u; return 1.0 - v * v * v * v; }',
      'float p3i(float u){ u = clamp(u, 0.0, 1.0); return u * u * u; }',
      'vec3 place(vec2 home, float e, float eo){ float ang = aSpin * (1.0 - e) + aSpin * 0.5 * eo; vec2 d = home - aPivot; float c = cos(ang), s = sin(ang); d = vec2(c * d.x - s * d.y, s * d.x + c * d.y);',
      '  return vec3(aPivot + d, 0.0) + aScatter * (1.0 - e) + vec3(aScatter.xy * 0.35, 1100.0) * eo; }',
      'vec2 screen(vec3 p){ vec4 c = projectionMatrix * modelViewMatrix * vec4(p, 1.0); return c.xy / c.w * uRes; }',
      'void main(){ float e = p4o((uT - aDelay) / uIn), eo = p3i((uT - uOutStart - aDelayOut) / uOut);',
      '  vec3 a = place(position.xy, e, eo); vec4 va = modelViewMatrix * vec4(a, 1.0); vec4 ca = projectionMatrix * va;',
      '  vec2 sa = ca.xy / ca.w * uRes, sp = screen(place(aPrev, e, eo)), sn = screen(place(aNext, e, eo));',
      '  vec2 d1 = sa - sp, d2 = sn - sa; float l1 = length(d1), l2 = length(d2);',
      '  vec2 tdir = (l1 > 1e-4 ? d1 / l1 : vec2(0.0)) + (l2 > 1e-4 ? d2 / l2 : vec2(0.0)); float lt = length(tdir); tdir = lt > 1e-4 ? tdir / lt : vec2(1.0, 0.0);',
      '  vec2 nrm = vec2(-tdir.y, tdir.x); vec2 off = nrm * aSide * uWidth / uRes * 2.0;',
      '  gl_Position = ca + vec4(off * ca.w, 0.0, 0.0); vAcross = aSide; vX = a.x;',
      '  float fog = smoothstep(uFogNear, uFogFar, -va.z); vAlpha = smoothstep(0.0, 0.18, e) * (1.0 - smoothstep(0.4, 0.85, eo)) * (1.0 - fog); }'].join('\n');
    const FS = [
      'precision highp float; varying float vAcross, vAlpha, vX; uniform vec3 uLine, uGlow; uniform float uMul, uSoft, uSweep;',
      'void main(){ float a = (1.0 - smoothstep(uSoft, 1.0, abs(vAcross))) * vAlpha * uMul;',
      '  float band = exp(-pow((vX / 640.0 - (uSweep * 2.6 - 1.3)) * 2.4, 2.0)) * step(0.001, uSweep) * step(uSweep, 0.999);',
      '  vec3 c = mix(uLine, vec3(1.0), band * 0.35); gl_FragColor = vec4(c, a); }'].join('\n');
    const mk = (width, mul, soft, col, blend) => new T.ShaderMaterial({ vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, depthTest: false, blending: blend, side: T.DoubleSide,   // the ribbon's winding follows its normal: never cull it
      uniforms: { uT: { value: 0 }, uIn: { value: flyIn }, uOutStart: { value: outStart }, uOut: { value: outDur }, uWidth: { value: width }, uRes: { value: new T.Vector2(W, H) },
        uFogNear: { value: R.camZ + 200 }, uFogFar: { value: R.camZ + 1400 }, uLine: { value: new T.Vector3(...hex3(col)) }, uGlow: { value: new T.Vector3(...hex3(colors.glow)) }, uMul: { value: mul }, uSoft: { value: soft }, uSweep: { value: 0 } } });
    const halo = new T.Mesh(geo, mk(o.halo === undefined ? 7 : o.halo, 0.16, 0.0, colors.glow, T.AdditiveBlending)); halo.frustumCulled = false; halo.renderOrder = 1; R.scene.add(halo);
    const core = new T.Mesh(geo, mk(o.width === undefined ? 2.2 : o.width, 1.0, 0.45, colors.line, T.NormalBlending)); core.frustumCulled = false; core.renderOrder = 2; R.scene.add(core);
    const push = o.push === undefined ? 0.012 : o.push;
    function seek(lt) {
      lt = Number.isFinite(lt) ? lt : 0;
      R.camera.position.z = R.camZ / (1 + push * clamp(lt - inEnd, 0, total - inEnd));
      const sweep = lt > inEnd && lt < outStart ? clamp((lt - inEnd) / hold, 0, 1) : (lt >= outStart ? 1 : 0);
      for (const m of [halo, core]) { m.material.uniforms.uT.value = lt; m.material.uniforms.uSweep.value = sweep; }
      R.draw();
    }
    return state(R, seek, { inEnd, outStart, total }, { pieces: pieces.length, segments: nSeg, points: nPts, raster: ras });
  }
  /* silhouette → contour polylines (square marching on the mask) → smoothed, simplified, cut into pieces of ~pieceLen px */
  function outlinePieces(ras, step, pieceLen) {
    const b = ras.bbox, cols = Math.ceil((b.x1 - b.x0) / step) + 2, rows = Math.ceil((b.y1 - b.y0) / step) + 2;
    const M = new Uint8Array(cols * rows);
    for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) M[j * cols + i] = ras.inside(b.x0 + (i - 0.5) * step, b.y0 + (j - 0.5) * step) ? 1 : 0;
    // edges of a cell: 0 top, 1 right, 2 bottom, 3 left; corner bits: 1 top-left, 2 top-right, 4 bottom-right, 8 bottom-left
    const TABLE = [[], [[3, 0]], [[0, 1]], [[3, 1]], [[1, 2]], [[3, 0], [1, 2]], [[0, 2]], [[3, 2]], [[2, 3]], [[0, 2]], [[0, 1], [2, 3]], [[1, 2]], [[1, 3]], [[0, 1]], [[3, 0]], []];
    const mid = (i, j, e) => e === 0 ? [i + 0.5, j] : e === 1 ? [i + 1, j + 0.5] : e === 2 ? [i + 0.5, j + 1] : [i, j + 0.5];
    const segs = [], byKey = new Map(); const key = p => (p[0] * 2) + ',' + (p[1] * 2);
    for (let j = 0; j < rows - 1; j++) for (let i = 0; i < cols - 1; i++) {
      const c = M[j * cols + i] | (M[j * cols + i + 1] << 1) | (M[(j + 1) * cols + i + 1] << 2) | (M[(j + 1) * cols + i] << 3);
      for (const e of TABLE[c]) { const a = mid(i, j, e[0]), d = mid(i, j, e[1]); const k = segs.length; segs.push([a, d, false]); for (const p of [a, d]) { const kk = key(p); if (!byKey.has(kk)) byKey.set(kk, []); byKey.get(kk).push(k); } }
    }
    const chains = [];
    for (let s0 = 0; s0 < segs.length; s0++) {
      if (segs[s0][2]) continue; segs[s0][2] = true; const chain = [segs[s0][0], segs[s0][1]];
      for (let dir = 0; dir < 2; dir++) {
        for (;;) {
          const end = dir === 0 ? chain[chain.length - 1] : chain[0]; const cand = (byKey.get(key(end)) || []).find(k => !segs[k][2]); if (cand === undefined) break;
          segs[cand][2] = true; const sg = segs[cand]; const nxt = key(sg[0]) === key(end) ? sg[1] : sg[0];
          if (dir === 0) chain.push(nxt); else chain.unshift(nxt);
        }
      }
      chains.push(chain);
    }
    const pieces = [];
    for (let ch of chains) {
      ch = ch.map(p => [b.x0 + (p[0] - 0.5) * step, b.y0 + (p[1] - 0.5) * step]);
      // one smoothing pass (corner cutting) then drop points closer than 1.6 px: the staircase becomes a curve
      const sm = []; for (let i = 0; i < ch.length - 1; i++) { const p = ch[i], q = ch[i + 1]; sm.push([p[0] * 0.75 + q[0] * 0.25, p[1] * 0.75 + q[1] * 0.25], [p[0] * 0.25 + q[0] * 0.75, p[1] * 0.25 + q[1] * 0.75]); }
      const sp = []; for (const p of sm) { const q = sp[sp.length - 1]; if (!q || Math.hypot(p[0] - q[0], p[1] - q[1]) >= 1.6) sp.push(p); }
      if (sp.length < 2) continue;
      let cur = [sp[0]], acc = 0;
      for (let i = 1; i < sp.length; i++) { acc += Math.hypot(sp[i][0] - sp[i - 1][0], sp[i][1] - sp[i - 1][1]); cur.push(sp[i]); if (acc >= pieceLen) { pieces.push(cur); cur = [sp[i]]; acc = 0; } }
      if (cur.length >= 2) { if (acc < pieceLen * 0.35 && pieces.length && pieces[pieces.length - 1] !== cur) { const last = pieces[pieces.length - 1]; for (let i = 1; i < cur.length; i++) last.push(cur[i]); } else pieces.push(cur); }
    }
    return pieces;
  }

  /* ========================================================================================================
     T3D.depthStack(host, cards, o) — camera-facing cards at increasing depth; the camera dollies through them.
     cards: [{ src?: HTMLImageElement|HTMLCanvasElement (footage: never tilted, fogged or tinted), w, h, x, y,
               label, title, body, tone:'navy'|'cream' }]
     o: { gap:420, spread:[90,44], dolly:{t0:0, t1:total, from:0, to:gap*(n-1), ease:'sineIO'}, total:6, fog:true,
          colors:{bg:#082A34, plate:#204A56, rim:#81A9AB, ink:#E9F3F9, soft:#ECDEC3, label:#81A9AB} }
     ======================================================================================================== */
  function depthStack(host, cards, o) {
    o = o || {}; const T = need(); cards = cards || [];
    const colors = Object.assign({ bg: PAL.navy, plate: PAL.navy2, rim: PAL.mint, ink: PAL.ink, soft: PAL.cream, label: PAL.mint, glow: PAL.mint }, o.colors || {});
    for (const k in colors) colors[k] = toHex(colors[k]);
    const R = rig(host, Object.assign({}, o, { colors }));
    groundPlane(R, Object.assign({ glow: 0.08 }, o, { colors }));
    const gap = o.gap === undefined ? 420 : o.gap, spread = o.spread || [90, 44], n = cards.length;
    const total = o.total === undefined ? 6 : o.total;
    const dolly = Object.assign({ t0: 0, t1: total, from: 0, to: gap * Math.max(0, n - 1), ease: 'sineIO' }, o.dolly || {});
    const easeFn = typeof dolly.ease === 'function' ? dolly.ease : (E[dolly.ease] || E.sineIO);
    const VS = 'varying vec2 vUv; varying float vD; void main(){ vUv = uv; vec4 mv = modelViewMatrix * vec4(position, 1.0); vD = -mv.z; gl_Position = projectionMatrix * mv; }';
    const FS = [
      'precision highp float; varying vec2 vUv; varying float vD; uniform sampler2D uMap; uniform float uHasMap, uFogMul, uRadius, uNear, uFogNear, uFogFar, uRimA; uniform vec2 uSize; uniform vec3 uPlate, uRim, uBg;',
      'float rr(vec2 p, vec2 h, float r){ vec2 q = abs(p) - h + r; return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r; }',
      'void main(){ vec2 p = (vUv - 0.5) * uSize; float d = rr(p, uSize * 0.5, uRadius); float shape = 1.0 - smoothstep(-0.8, 0.8, d);',
      '  vec3 col = uHasMap > 0.5 ? texture2D(uMap, vUv).rgb : uPlate; float rim = (1.0 - smoothstep(0.0, 1.6, abs(d + 1.0))) * uRimA; col = mix(col, uRim, rim);',
      '  float fog = smoothstep(uFogNear, uFogFar, vD) * uFogMul; col = mix(col, uBg, fog);',
      '  float near = smoothstep(220.0, 760.0, vD); gl_FragColor = vec4(col, shape * near); }'].join('\n');
    const planes = cards.map((c, i) => {
      const w = c.w || 560, h = c.h || 340, footage = !!c.src;
      let tex = null;
      if (footage) { tex = new T.Texture(c.src); tex.needsUpdate = true; tex.minFilter = T.LinearMipmapLinearFilter; tex.magFilter = T.LinearFilter; }
      else if (c.title || c.body || c.label) tex = new T.CanvasTexture(cardCanvas(c, w, h, colors));
      const mat = new T.ShaderMaterial({ vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false, uniforms: {
        uMap: { value: tex }, uHasMap: { value: tex ? 1 : 0 }, uFogMul: { value: footage || o.fog === false ? 0 : 0.85 }, uRadius: { value: footage ? 0 : (c.radius === undefined ? 14 : c.radius) },
        uNear: { value: 0 }, uFogNear: { value: R.camZ + 200 }, uFogFar: { value: R.camZ + 2200 }, uRimA: { value: footage ? 0 : 0.9 }, uSize: { value: new T.Vector2(w, h) },
        uPlate: { value: new T.Vector3(...hex3(colors.plate)) }, uRim: { value: new T.Vector3(...hex3(colors.rim)) }, uBg: { value: new T.Vector3(...hex3(colors.bg)) } } });
      const m = new T.Mesh(new T.PlaneGeometry(w, h), mat); m.frustumCulled = false;
      const sx = c.x === undefined ? ((i % 2) ? 1 : -1) * spread[0] * Math.min(1, i) : c.x, sy = c.y === undefined ? (((i >> 1) % 2) ? 1 : -1) * spread[1] * Math.min(1, i) : c.y;
      m.position.set(sx, sy, -i * gap); m.renderOrder = n - i; R.scene.add(m);
      // a soft shadow plate behind each card gives the stack its depth read (plates only; footage keeps its own edge)
      const sh = new T.Mesh(new T.PlaneGeometry(w * 1.12, h * 1.18), new T.ShaderMaterial({ transparent: true, depthWrite: false, vertexShader: VS, uniforms: { uBg: { value: new T.Vector3(...hex3(colors.bg)) } },
        fragmentShader: 'precision highp float; varying vec2 vUv; void main(){ vec2 d = (vUv - 0.5) * 2.0; float a = (1.0 - smoothstep(0.55, 1.0, length(d * vec2(0.92, 0.9)))) * 0.55; gl_FragColor = vec4(0.015, 0.06, 0.08, a); }' }));
      sh.position.set(sx, sy - 8, -i * gap - 2); sh.renderOrder = n - i - 0.5; sh.frustumCulled = false; R.scene.add(sh);
      return { mesh: m, shadow: sh, footage };
    });
    function seek(lt) {
      lt = Number.isFinite(lt) ? lt : 0;
      const u = easeFn(clamp((lt - dolly.t0) / Math.max(1e-6, dolly.t1 - dolly.t0), 0, 1));
      R.camera.position.z = R.camZ - lerp(dolly.from, dolly.to, u);
      R.draw();
    }
    return state(R, seek, { inEnd: 0, outStart: total, total }, { cards: planes.length });
  }
  /* a text card rasterised once: label (tracked caps), title (serif), body (wrapped) on the plate colour */
  function cardCanvas(c, w, h, colors) {
    const S = 2, cv = document.createElement('canvas'); cv.width = w * S; cv.height = h * S; const g = cv.getContext('2d'); g.scale(S, S);
    const hx = v => '#' + v.toString(16).padStart(6, '0');
    g.fillStyle = hx(c.tone === 'cream' ? PAL.cream : colors.plate); g.fillRect(0, 0, w, h);
    const ink = c.tone === 'cream' ? hx(PAL.navy) : hx(colors.ink), soft = c.tone === 'cream' ? hx(PAL.navy2) : hx(colors.soft);
    const padX = Math.round(w * 0.075); let y = Math.round(h * 0.16);
    if (c.label) { g.fillStyle = hx(colors.label); g.font = '600 13px Arial, sans-serif'; try { g.letterSpacing = '0.14em'; } catch (e) { /* older canvas */ } g.fillText(String(c.label).toUpperCase(), padX, y); y += 34; }
    try { g.letterSpacing = '0em'; } catch (e) { /* older canvas */ }
    if (c.title) { g.fillStyle = ink; g.font = '400 ' + (c.titleSize || 34) + 'px Georgia, serif'; for (const ln of wrap(g, c.title, w - padX * 2)) { g.fillText(ln, padX, y + 26); y += (c.titleSize || 34) * 1.15; } y += 14; }
    if (c.body) { g.fillStyle = soft; g.font = '400 18px Arial, sans-serif'; for (const ln of wrap(g, c.body, w - padX * 2)) { g.fillText(ln, padX, y + 14); y += 26; } }
    return cv;
  }
  function wrap(g, text, maxW) { const out = []; for (const para of String(text).split('\n')) { let line = ''; for (const wd of para.split(' ')) { const t = line ? line + ' ' + wd : wd; if (g.measureText(t).width > maxW && line) { out.push(line); line = wd; } else line = t; } out.push(line); } return out; }

  /* ---------- the state every device returns ---------- */
  function state(R, seek, timings, extra) {
    const st = Object.assign({
      kind: 't3d', canvas: R.canvas, renderer: R.renderer, scene: R.scene, camera: R.camera, timings, total: timings.total,
      seek, hide() { if (R.canvas.style.visibility !== 'hidden') R.canvas.style.visibility = 'hidden'; }, show() { if (R.canvas.style.visibility !== 'visible') R.canvas.style.visibility = 'visible'; },
      /* convenience for a scene with a window: draws the local time inside [start, end), hides the canvas outside */
      at(t, start, end) { if (t >= start && t < (end === undefined ? Infinity : end)) { st.show(); seek(t - start); return true; } st.hide(); return false; },
      dispose() { R.scene.traverse(ob => { if (ob.geometry) ob.geometry.dispose(); if (ob.material) { const u = ob.material.uniforms; if (u) for (const k in u) if (u[k].value && u[k].value.isTexture) u[k].value.dispose(); ob.material.dispose(); } }); if (R.post) { R.post.rt.dispose(); R.post.quad.geometry.dispose(); R.post.quad.material.dispose(); } R.renderer.dispose(); if (R.canvas.parentNode) R.canvas.parentNode.removeChild(R.canvas); },
      info() { const gl = R.renderer.getContext(); const ext = gl.getExtension('WEBGL_debug_renderer_info'); return { renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER), drawingBuffer: [gl.drawingBufferWidth, gl.drawingBufferHeight], samples: gl.getParameter(gl.SAMPLES), aa: R.aa, dpr: R.dpr }; }
    }, extra || {});
    return st;
  }

  /* the numbers behind the defaults (SwiftShader, 1920x1080, GL ms per frame above the DOM-screenshot baseline) */
  const MEASURED = { shard_none: 70, shard_msaa4: 105, shard_post: 121, shard_ssaa2: 257, shard_physical_transmission: 1390, portal: 82, stack4: 135, dom_screenshot_baseline: 100 };
  root.T3D = { load, ready, shardTitle, portalTitle, depthStack, softwareGL: isSoftwareGL, MEASURED, PAL, E, W, H, get THREE() { return THREE; } };
})(typeof window !== 'undefined' ? window : globalThis);
