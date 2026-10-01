/* vfx.js — finishing effects for the RECREATED layers of a clock-driven film, as pure functions of t.
   window.VFX. Rules: references/vfx-and-grading.md

   Scope (what this file is for)
     vignette        darkening outside a superellipse (CSS gradient setter, or an exact canvas mask)
     grain           deterministic hash grain seeded by the FRAME INDEX, drawn as mid-grey noise for soft-light
     bloom           highlight bloom on a canvas layer (Rec.601 threshold, 9-tap Gaussian at radius 8, additive)
     matte           luma / alpha matte as a CSS mask: a word, a wipe or a circle that reveals the layer behind it
     fbm / haze      seeded value-noise field (32-bit lattice hash) drawn as a low-res tile for dark card backdrops
     glitch, wave    the "problem beat" devices: 60-band tear + RGB split, and a sine wave warp — RECREATED ONLY
     seam            the shader-transition grammar re-expressed as six canvas/CSS seams for recreated ↔ footage
     ramp            speed-ramp maths for seq clips: a (t, rate) lane → source time (trapezoid integral)

   Contract (same as grammar.js / footage.js)
     - Pure functions of t plus explicit state (a ctx, an element, an options object). No wall clock, no
       Math.random, no CSS transitions. Every seed is Math.round(t * fps) — the integer frame index — so
       __seek(t) and __step(t) draw the same pixels.
     - DOM writes only through the documented setters (vignette, applyMatte, applySeam, applyBloomGhost).
     - NOTHING here may touch the footage lane. Every drawing function calls assertRecreated() and throws
       if its target is #clipWrap or a descendant (or carries data-footage). gates/grade_gate.py repeats the
       check statically on the authored files. A grainy or glitched screenshot reads as a broken product.

   Measured defaults (see the reference for where each number comes from)
     vignette: darkening 0.75*amount, superellipse power 8..1.8 by roundness, midpoint 0.22..1.08 of the
               half-frame, feather 0.08..0.72; restrained amounts 0.10–0.18.
     grain:    cells 1..6 px by size, fine layer mixed at 0.35 by roughness, strength 0.025..0.08 masked
               to midtones (soft-light does the masking here); presets 0.08–0.16 at size 0.12–0.18.
     bloom:    9 taps (0.227, 0.1946, 0.1216, 0.054, 0.0162), radius 8, one-click amount 0.55.
     glitch:   envelope u(1-u)*4 (zero at both ends), 60 bands, tear 0.18, RGB shift 0.035, 8 levels at peak.
     wave:     height 10 px, width 40 px, 1 wave/s, sine only, transparent beyond the edges.
     seams:    power2.inOut; calm 0.5–0.8 s, medium 0.3–0.5 s, high 0.15–0.3 s; blur capped at 15 px.
     ramp:     rates 0.1..10, log-space interpolation, 48 trapezoid cells per segment. */
(function (root) {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, x) => a + (b - a) * x;
  const sstep = (a, b, x) => { const u = clamp((x - a) / (b - a), 0, 1); return u * u * (3 - 2 * u); };
  const quintic = f => f * f * f * (f * (f * 6 - 15) + 10);
  const EIO2 = x => { x = clamp(x, 0, 1); return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; };   // power2.inOut
  const EIN2 = x => { x = clamp(x, 0, 1); return x * x; };
  const EOUT2 = x => { x = clamp(x, 0, 1); return 1 - (1 - x) * (1 - x); };
  const frameIndex = (t, fps) => Math.round(t * (fps || 30));
  const W0 = 1280, H0 = 720;

  /* ---------- footage guard: effects never touch the product lane ---------- */
  const FOOTAGE_SELECTOR = '#clipWrap, [data-footage]';
  function isFootage(el) {
    if (!el || typeof el !== 'object') return false;
    if (typeof Element !== 'undefined' && el instanceof Element) {
      if (el.matches && el.matches(FOOTAGE_SELECTOR)) return true;
      if (el.closest && el.closest(FOOTAGE_SELECTOR)) return true;
      if (el.dataset && 'footage' in el.dataset) return true;
      return false;
    }
    if (el.canvas) return isFootage(el.canvas);                       // a 2D context
    return false;
  }
  function assertRecreated(el, what) {
    if (isFootage(el)) throw new Error('VFX.' + (what || 'effect') + ' refused: target is the footage lane (' + FOOTAGE_SELECTOR + '). Effects are for recreated layers only.');
    return el;
  }

  /* ---------- offscreen canvas cache (keyed by purpose + size) ---------- */
  const _off = {};
  function off(key, w, h) {
    let c = _off[key];
    if (!c || c.width !== w || c.height !== h) { c = document.createElement('canvas'); c.width = w; c.height = h; _off[key] = c; }
    return c;
  }

  /* ---------- 32-bit lattice hash + value-noise fBm (re-expressed) ---------- */
  function hash(ix, iy, seed) {
    let h = ((Math.imul(ix | 0, 374761393) ^ Math.imul(iy | 0, 668265263) ^ Math.imul(seed | 0, 1274126177)) + 2654435769) >>> 0;
    h = (h ^ (h >>> 13)) >>> 0; h = Math.imul(h, 1274126177) >>> 0; h = (h ^ (h >>> 16)) >>> 0;
    return h / 4294967296;
  }
  function vnoise(x, y, seed) {
    const cx = Math.floor(x), cy = Math.floor(y), fx = quintic(x - cx), fy = quintic(y - cy);
    const b = lerp(hash(cx, cy, seed), hash(cx + 1, cy, seed), fx), tp = lerp(hash(cx, cy + 1, seed), hash(cx + 1, cy + 1, seed), fx);
    return lerp(b, tp, fy);
  }
  /* fbm(x, y, seed, octaves=5, gain=0.5, lac=2.0): value-noise fBm in [0,1]; the corpus "haze" point is
     6 octaves, gain 0.70, lacunarity 1/0.56 at scale 411 px. */
  function fbm(x, y, seed, octaves, gain, lac) {
    octaves = octaves || 5; gain = gain === undefined ? 0.5 : gain; lac = lac || 2.0;
    let amp = 1, freq = 1, sum = 0, norm = 0;
    for (let i = 0; i < octaves; i++) { sum += amp * vnoise(x * freq, y * freq, (seed | 0) + i); norm += amp; amp *= gain; freq *= lac; }
    return norm > 0 ? sum / norm : 0;
  }

  /* ---------- vignette ---------- */
  /* vignetteParams(o) → {dark, power, mid, feather} from the 0..1 knobs (measured mapping). */
  function vignetteParams(o) {
    o = o || {};
    const amount = clamp(o.amount === undefined ? 0.12 : o.amount, 0, 1), round = clamp(o.roundness === undefined ? 0.5 : o.roundness, 0, 1);
    return { dark: 0.75 * amount, power: lerp(8, 1.8, round), mid: lerp(0.22, 1.08, clamp(o.mid === undefined ? 0.5 : o.mid, 0, 1)),
             feather: lerp(0.08, 0.72, clamp(o.feather === undefined ? 0.65 : o.feather, 0, 1)) };
  }
  /* vignette(el, o): idempotent CSS setter. Distance unit = the half-height (circle closest-side), so a stop at
     p% is d = p/100; the smoothstep(mid, mid+feather) ramp is sampled into 9 stops. CSS can only draw a circle
     (power 2); use vignetteMask() when the squarer superellipse matters. */
  function vignette(el, o) {
    assertRecreated(el, 'vignette');
    const p = vignetteParams(o), key = JSON.stringify(p);
    if (el.dataset.vfxVignette === key) return el;
    const stops = [];
    for (let i = 0; i <= 8; i++) { const d = p.mid + p.feather * i / 8, a = sstep(p.mid, p.mid + p.feather, d) * p.dark; stops.push('rgba(0,0,0,' + a.toFixed(4) + ') ' + (d * 100).toFixed(1) + '%'); }
    el.style.background = 'radial-gradient(circle closest-side at 50% 50%, rgba(0,0,0,0) 0%, ' + stops.join(', ') + ', rgba(0,0,0,' + p.dark.toFixed(4) + ') 300%)';
    el.style.pointerEvents = 'none'; el.dataset.vfxVignette = key;
    return el;
  }
  /* vignetteMask(W, H, o) → cached canvas with the exact superellipse darkening (alpha = mask*0.75*amount),
     to drawImage over a canvas card. Computed at 1/4 resolution and upscaled (smooth). */
  function vignetteMask(W, H, o) {
    W = W || W0; H = H || H0;
    const p = vignetteParams(o), key = 'vig|' + W + 'x' + H + '|' + JSON.stringify(p);
    if (_off[key]) return _off[key];
    const r = 4, w = Math.ceil(W / r), h = Math.ceil(H / r), c = document.createElement('canvas'); c.width = w; c.height = h;
    const ctx = c.getContext('2d'), im = ctx.createImageData(w, h), d = im.data, asp = W > H ? [W / H, 1] : [1, H / W];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const ux = Math.abs(((x + 0.5) / w - 0.5) * 2) * asp[0], uy = Math.abs(((y + 0.5) / h - 0.5) * 2) * asp[1];
      const dist = Math.pow(Math.pow(ux, p.power) + Math.pow(uy, p.power), 1 / p.power);
      const a = sstep(p.mid, p.mid + p.feather, dist) * p.dark;
      const i = (y * w + x) * 4; d[i] = 0; d[i + 1] = 0; d[i + 2] = 0; d[i + 3] = Math.round(a * 255);
    }
    ctx.putImageData(im, 0, 0); _off[key] = c; return c;
  }

  /* ---------- grain ---------- */
  /* grain(ctx, t, o): fills ctx's canvas with mid-grey noise (128 ± d) for a layer styled
       mix-blend-mode: soft-light   (50 % grey is identity; soft-light fades the effect in shadows and
                                     highlights, which stands in for the measured midtone mask)
     o: {amount:0.12, size:0.18, roughness:0.65, fps:30, seed:0, res:2, gain:1, W, H}
     cell px = 1..6 by size; base = hash(cell) - hash(cell+offset) (triangular ±1); fine = per-pixel hash - 0.5;
     grain = mix(base*0.7, base + fine*0.35, roughness); d = grain * 0.16 * amount * gain (soft-light ≈ halves it,
     so the on-screen offset is amount*0.08*grain — the measured peak strength). Seed = frame index. Computed at
     1/res resolution and upscaled nearest-neighbour; cells ≥ 2 px survive JPEG q96. */
  function grain(ctx, t, o) {
    o = o || {}; assertRecreated(ctx, 'grain');
    const W = o.W || ctx.canvas.width, H = o.H || ctx.canvas.height, res = Math.max(1, o.res || 2);
    const amount = clamp(o.amount === undefined ? 0.12 : o.amount, 0, 1), rough = clamp(o.roughness === undefined ? 0.65 : o.roughness, 0, 1);
    const cell = Math.max(1, Math.round(lerp(1, 6, clamp(o.size === undefined ? 0.18 : o.size, 0, 1))));
    const seed = ((o.seed | 0) + frameIndex(t, o.fps)) | 0, k = 0.16 * amount * (o.gain === undefined ? 1 : o.gain) * 255;
    const w = Math.ceil(W / res), h = Math.ceil(H / res), tile = off('grain', w, h), tctx = tile.getContext('2d');
    const im = tctx.createImageData(w, h), d = im.data, ncx = Math.ceil(w * res / cell) + 1, baseRow = new Float32Array(ncx);
    let lastCy = -1;
    for (let y = 0; y < h; y++) {
      const cy = Math.floor(y * res / cell);
      if (cy !== lastCy) { for (let cx = 0; cx < ncx; cx++) baseRow[cx] = hash(cx, cy, seed) - hash(cx + 19, cy + 73, seed); lastCy = cy; }   // 2 hashes per CELL, not per pixel
      for (let x = 0; x < w; x++) {
        const base = baseRow[Math.floor(x * res / cell)];
        const fine = rough > 0 ? hash(x, y, seed * 2 + 1) - 0.5 : 0;
        const g = lerp(base * 0.7, base + fine * 0.35, rough);
        const v = clamp(Math.round(128 + g * k), 0, 255), i = (y * w + x) * 4;
        d[i] = v; d[i + 1] = v; d[i + 2] = v; d[i + 3] = 255;
      }
    }
    tctx.putImageData(im, 0, 0);
    ctx.save(); ctx.globalCompositeOperation = o.composite || 'source-over'; ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, W, H); ctx.drawImage(tile, 0, 0, W, H); ctx.restore();
    return { seed, cell, w, h };
  }

  /* ---------- bloom ---------- */
  const TAPS = [0.227027, 0.1945946, 0.1216216, 0.054054, 0.016216];
  function blur9(src, dst, w, h, step, horiz) {
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let r = 0, g = 0, b = 0;
      for (let k = -4; k <= 4; k++) {
        const wgt = TAPS[Math.abs(k)];
        const sx = horiz ? clamp(x + k * step, 0, w - 1) : x, sy = horiz ? y : clamp(y + k * step, 0, h - 1), i = (sy * w + sx) * 4;
        r += src[i] * wgt; g += src[i + 1] * wgt; b += src[i + 2] * wgt;
      }
      const j = (y * w + x) * 4; dst[j] = r; dst[j + 1] = g; dst[j + 2] = b; dst[j + 3] = 255;
    }
  }
  /* bloom(ctx, src, o): adds a blurred copy of src's highlights onto ctx (globalCompositeOperation 'lighter').
     o: {threshold:0.6 (Rec.601 luma), radius:8 (stage px), amount:0.55 (0..3), res:radius, x:0, y:0, w, h}
     Work happens at 1/res resolution (default res = radius, so one tap step = one pixel and the 9 taps reach
     ±4·radius stage px): threshold → separable 9-tap → bilinear upscale.
     Judge bloom at 1:1 on the frame, never by a clip metric: a bloomed card measures LESS clipped than its source. */
  function bloom(ctx, src, o) {
    o = o || {}; assertRecreated(ctx, 'bloom'); assertRecreated(src, 'bloom');
    const radius = o.radius === undefined ? 8 : o.radius;
    // work at a resolution where one tap step is one pixel (a step > 1 px leaves a comb pattern after upscaling)
    const W = o.w || ctx.canvas.width, H = o.h || ctx.canvas.height, res = Math.max(1, o.res || Math.round(radius)), w = Math.ceil(W / res), h = Math.ceil(H / res);
    const thr = clamp(o.threshold === undefined ? 0.6 : o.threshold, 0, 1) * 255, amount = clamp(o.amount === undefined ? 0.55 : o.amount, 0, 3);
    const step = Math.max(1, Math.round(radius / res));
    const a = off('bloomA', w, h), b = off('bloomB', w, h), actx = a.getContext('2d'), bctx = b.getContext('2d');
    actx.clearRect(0, 0, w, h); actx.drawImage(src, 0, 0, w, h);
    const im = actx.getImageData(0, 0, w, h), d = im.data;
    for (let i = 0; i < d.length; i += 4) {
      const Y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      if (Y < thr) { d[i] = 0; d[i + 1] = 0; d[i + 2] = 0; }
      d[i + 3] = 255;
    }
    const tmp = new Uint8ClampedArray(d.length), out = bctx.createImageData(w, h);
    blur9(d, tmp, w, h, step, true); blur9(tmp, out.data, w, h, step, false);
    bctx.putImageData(out, 0, 0);
    ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    let left = amount; while (left > 0) { ctx.globalAlpha = Math.min(1, left); ctx.drawImage(b, o.x || 0, o.y || 0, W, H); left -= 1; }
    ctx.restore();
    return { w, h, step, amount };
  }
  /* bloomGhostStyle(amount, radius) → style for a DOM "ghost" copy of a card's text stacked over the original:
     blur(radius px), screen, opacity amount*0.3 (0 hides it). applyBloomGhost(el, amount, radius) sets it. */
  function bloomGhostStyle(amount, radius) {
    amount = clamp(amount === undefined ? 0.55 : amount, 0, 3); radius = radius === undefined ? 8 : radius;
    return { filter: 'blur(' + radius + 'px)', mixBlendMode: 'screen', opacity: clamp(amount * 0.3, 0, 1).toFixed(3), pointerEvents: 'none' };
  }
  function applyBloomGhost(el, amount, radius) {
    assertRecreated(el, 'bloom'); const s = bloomGhostStyle(amount, radius);
    el.style.filter = s.filter; el.style.mixBlendMode = s.mixBlendMode; el.style.opacity = s.opacity; el.style.pointerEvents = 'none'; return el;
  }

  /* ---------- luma / alpha matte as a CSS mask ("reveal through the product") ---------- */
  /* matteStyle(kind, u, o) → {maskImage, maskMode, maskSize, maskRepeat, maskPosition, url?}
       'wipe'   linear-gradient edge at progress u (o.angle deg, o.soft % of the run, default 4)
       'circle' radial reveal, radius 120*u % of the half-height at (o.cx, o.cy) %
       'text'   an SVG word (o.text, o.font, o.weight, o.px) scaled by o.from..o.to (default 0.6→1) × u, luminance mask
     The layer that is masked may contain the product footage: a mask is a compositing shape, it changes no
     product pixel. 'text' uses a data URL: applyMatte() returns a decode Promise — add it to the scene's
     pending list so __seek/__step wait for it. */
  function matteStyle(kind, u, o) {
    o = o || {}; u = clamp(u, 0, 1);
    const st = { maskRepeat: 'no-repeat', maskSize: '100% 100%', maskPosition: '0 0', maskMode: 'alpha' };
    if (kind === 'wipe') {
      const soft = o.soft === undefined ? 4 : o.soft, p = u * (100 + soft) - soft;
      st.maskImage = 'linear-gradient(' + (o.angle === undefined ? 90 : o.angle) + 'deg, #000 0%, #000 ' + p.toFixed(2) + '%, rgba(0,0,0,0) ' + (p + soft).toFixed(2) + '%)';
    } else if (kind === 'circle') {
      const r = 120 * u, soft = o.soft === undefined ? 3 : o.soft;
      st.maskImage = 'radial-gradient(circle closest-side at ' + (o.cx === undefined ? 50 : o.cx) + '% ' + (o.cy === undefined ? 50 : o.cy) + '%, #000 ' + r.toFixed(2) + '%, rgba(0,0,0,0) ' + (r + soft).toFixed(2) + '%)';
    } else if (kind === 'text') {
      const W = o.W || W0, H = o.H || H0, s = lerp(o.from === undefined ? 0.6 : o.from, o.to === undefined ? 1 : o.to, u);
      const px = o.px || 220, font = (o.font || 'Georgia, serif').replace(/"/g, "'"), text = String(o.text || 'ACME').replace(/[<>&]/g, '');
      const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + H + '"><rect width="100%" height="100%" fill="#000"/>' +
        '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" font-family="' + font + '" font-weight="' + (o.weight || 700) + '" font-size="' + px + '" fill="#fff" ' +
        'transform="translate(' + (W / 2) + ' ' + (H / 2) + ') scale(' + s.toFixed(4) + ') translate(' + (-W / 2) + ' ' + (-H / 2) + ')">' + text + '</text></svg>';
      st.url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg); st.maskImage = 'url("' + st.url + '")'; st.maskMode = 'luminance';
    } else throw new Error('VFX.matteStyle: unknown kind ' + kind);
    return st;
  }
  function applyMatte(el, st) {
    const S = el.style;
    S.webkitMaskImage = st.maskImage; S.maskImage = st.maskImage; S.webkitMaskSize = st.maskSize; S.maskSize = st.maskSize;
    S.webkitMaskRepeat = st.maskRepeat; S.maskRepeat = st.maskRepeat; S.webkitMaskPosition = st.maskPosition; S.maskPosition = st.maskPosition;
    S.maskMode = st.maskMode;
    if (st.url) { const im = new Image(); im.src = st.url; return im.decode().catch(() => {}); }
    return Promise.resolve();
  }
  function clearMatte(el) { const S = el.style; S.webkitMaskImage = ''; S.maskImage = ''; S.maskMode = ''; return el; }

  /* ---------- seeded haze (fBm backdrop) ---------- */
  /* haze(ctx, t, o): draws a low-res fBm tile (default 160x90) scaled up smoothly to W×H. Time enters only as a
     translation (evolution = t*drift). o: {scale:400, opacity:0.05, drift:0.01, seed:0, octaves:6, gain:0.7,
     lac:1/0.56, contrast:5.62, brightness:0, tile:[160,90], color:[255,255,255], composite:'source-over'} */
  function haze(ctx, t, o) {
    o = o || {}; assertRecreated(ctx, 'haze');
    const W = o.W || ctx.canvas.width, H = o.H || ctx.canvas.height, tw = (o.tile || [160, 90])[0], th = (o.tile || [160, 90])[1];
    const scale = Math.max(1, o.scale || 400) * tw / W, ev = (t || 0) * (o.drift === undefined ? 0.01 : o.drift) * 100;
    const oct = o.octaves || 6, gain = o.gain === undefined ? 0.7 : o.gain, lac = o.lac || (1 / 0.56), con = o.contrast === undefined ? 5.62 : o.contrast, bri = o.brightness || 0;
    const col = o.color || [255, 255, 255], alpha = clamp(o.opacity === undefined ? 0.05 : o.opacity, 0, 1);
    const tile = off('haze', tw, th), tctx = tile.getContext('2d'), im = tctx.createImageData(tw, th), d = im.data;
    for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
      let v = fbm(x / scale + ev, y / scale + ev * 0.5, o.seed | 0, oct, gain, lac);
      v = clamp((v - 0.5) * con + 0.5 + bri, 0, 1);
      const i = (y * tw + x) * 4; d[i] = col[0]; d[i + 1] = col[1]; d[i + 2] = col[2]; d[i + 3] = Math.round(v * alpha * 255);
    }
    tctx.putImageData(im, 0, 0);
    ctx.save(); ctx.globalCompositeOperation = o.composite || 'source-over'; ctx.imageSmoothingEnabled = true; ctx.drawImage(tile, 0, 0, W, H); ctx.restore();
    return { tw, th, ev };
  }

  /* ---------- channel-isolated copies (for RGB split) ---------- */
  function channelCopy(key, img, W, H, scale, color) {
    const c = off(key, W, H), x = c.getContext('2d');
    const place = () => { x.save(); x.translate(W / 2, H / 2); x.scale(scale, scale); x.translate(-W / 2, -H / 2); x.drawImage(img, 0, 0, W, H); x.restore(); };
    x.save(); x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, W, H); place(); x.restore();
    x.save(); x.globalCompositeOperation = 'multiply'; x.fillStyle = color; x.fillRect(0, 0, W, H); x.restore();
    // 'multiply' over a transparent backdrop paints the solid fill colour: restore the image's own alpha
    x.save(); x.globalCompositeOperation = 'destination-in'; place(); x.restore();
    return c;
  }
  /* chromaticSplit(ctx, img, shift, o): draws img with its R and B channels scaled 1±shift about the centre
     (0.06 = the measured full split; glitch uses 0.035*intensity). Exact at shift 0. */
  function chromaticSplit(ctx, img, shift, o) {
    o = o || {}; assertRecreated(ctx, 'chromaticSplit'); assertRecreated(img, 'chromaticSplit');
    const W = o.w || ctx.canvas.width, H = o.h || ctx.canvas.height, k = o.key || 'cs';
    // R 1+s, G 1+s/2, B 1: the same R-B separation as ±s/2 about G, but no copy below 1.0 uncovers the frame edge
    const R = channelCopy(k + 'R', img, W, H, 1 + shift, '#ff0000'), G = channelCopy(k + 'G', img, W, H, 1 + shift / 2, '#00ff00'), B = channelCopy(k + 'B', img, W, H, 1, '#0000ff');
    ctx.save(); ctx.globalCompositeOperation = 'source-over'; ctx.drawImage(R, o.x || 0, o.y || 0, W, H);
    ctx.globalCompositeOperation = 'lighter'; ctx.drawImage(G, o.x || 0, o.y || 0, W, H); ctx.drawImage(B, o.x || 0, o.y || 0, W, H); ctx.restore();
  }

  /* ---------- glitch beat (recreated cards only, once per film, ≤ 0.4 s) ---------- */
  /* glitch(ctx, img, t, t0, dur, o): intensity = u(1-u)*4 so the first and last frame equal the plain card.
     60 horizontal bands; a band tears sideways by ±0.18*intensity*W when its frame-hash passes the 0.35
     jitter gate; R/B split 0.035*intensity*W as a radial scale; 8-level posterise mixed in at posterMix (0.5)
     when intensity > 0.6 (getImageData at 1/2 res; o.levels=0 skips it). o: {seed, bands:60, tear:0.18,
     jitter:0.35, shift:0.035, levels:8, posterMix:0.5, fps:30, W, H}. Returns the intensity. */
  function glitch(ctx, img, t, t0, dur, o) {
    o = o || {}; assertRecreated(ctx, 'glitch'); assertRecreated(img, 'glitch');
    const W = o.W || ctx.canvas.width, H = o.H || ctx.canvas.height, u = clamp((t - t0) / Math.max(1e-6, dur), 0, 1), I = u * (1 - u) * 4;
    if (I <= 0) { ctx.drawImage(img, 0, 0, W, H); return 0; }
    const fi = frameIndex(t, o.fps), seed = (o.seed | 0) + fi, bands = o.bands || 60, bh = H / bands;
    const tear = (o.tear === undefined ? 0.18 : o.tear) * I * W, jitter = o.jitter === undefined ? 0.35 : o.jitter;
    const torn = off('glitchT', W, H), tx = torn.getContext('2d');
    tx.clearRect(0, 0, W, H);
    for (let b = 0; b < bands; b++) {
      const gate = hash(b, 1, seed), amt = (hash(b, 2, seed) - 0.5) * 2, dx = gate < jitter * I + 0.05 ? Math.round(amt * tear) : 0;
      const sy = Math.round(b * bh), sh = Math.round((b + 1) * bh) - sy;
      tx.drawImage(img, 0, sy * img.height / H, img.width, sh * img.height / H, dx, sy, W, sh);
    }
    ctx.save(); ctx.clearRect(0, 0, W, H); ctx.restore();
    chromaticSplit(ctx, torn, (o.shift === undefined ? 0.035 : o.shift) * I, { w: W, h: H, key: 'gl' });
    const levels = o.levels === undefined ? 8 : o.levels;
    if (levels > 1 && I > 0.6) {
      const q = off('glitchQ', Math.ceil(W / 2), Math.ceil(H / 2)), qx = q.getContext('2d');
      qx.clearRect(0, 0, q.width, q.height); qx.drawImage(ctx.canvas, 0, 0, q.width, q.height);
      const im = qx.getImageData(0, 0, q.width, q.height), d = im.data, stepv = 255 / (levels - 1);
      for (let i = 0; i < d.length; i += 4) { d[i] = Math.round(d[i] / stepv) * stepv; d[i + 1] = Math.round(d[i + 1] / stepv) * stepv; d[i + 2] = Math.round(d[i + 2] / stepv) * stepv; }
      qx.putImageData(im, 0, 0);
      ctx.save(); ctx.globalAlpha = clamp((I - 0.6) / 0.4, 0, 1) * (o.posterMix === undefined ? 0.5 : o.posterMix); ctx.imageSmoothingEnabled = false; ctx.drawImage(q, 0, 0, W, H); ctx.restore();   // half-mixed: 8 levels at full strength reads music-video on a dark gradient
    }
    return I;
  }

  /* ---------- wave warp (recreated cards only) ---------- */
  /* waveWarp(ctx, img, t, o): rows shift sideways by height*sin(2π(-y/width + phase/360 + speed*t)); travel is
     vertical (direction 0), swing horizontal. Edges carry transparency. o: {height:10, width:40, speed:1,
     phase:0, rows:1, t0, dur (optional u(1-u)*4 envelope), W, H}. Returns the effective height. */
  function waveWarp(ctx, img, t, o) {
    o = o || {}; assertRecreated(ctx, 'waveWarp'); assertRecreated(img, 'waveWarp');
    const W = o.W || ctx.canvas.width, H = o.H || ctx.canvas.height, rows = Math.max(1, o.rows || 1);
    let height = Math.min(10, o.height === undefined ? 10 : o.height);
    if (o.dur) { const u = clamp((t - o.t0) / o.dur, 0, 1); height *= u * (1 - u) * 4; }
    const width = Math.max(1, o.width === undefined ? 40 : o.width), speed = o.speed === undefined ? 1 : o.speed, ph = (o.phase || 0) / 360;
    ctx.clearRect(0, 0, W, H);
    if (Math.abs(height) < 0.01) { ctx.drawImage(img, 0, 0, W, H); return 0; }
    const ky = img.height / H;
    for (let y = 0; y < H; y += rows) {
      const h = Math.min(rows, H - y), dx = height * Math.sin(2 * Math.PI * (-(y + h / 2) / width + ph + speed * t));
      ctx.drawImage(img, 0, y * ky, img.width, h * ky, dx, y, W, h);
    }
    return height;
  }

  /* ---------- seams: the shader grammar as six canvas/CSS seams ---------- */
  const SEAMS = {
    'flash-white':     { kind: 'css',    energy: 'medium', dur: 0.5, use: 'cold open → first real screen; payoff card → close. The transition IS the exit.' },
    'blur-dissolve':   { kind: 'css',    energy: 'medium', dur: 0.4, use: 'demo → payoff card (same mood, new layer); blur ≤ 15 px, dur ≤ 0.5 s.' },
    'iris':            { kind: 'css',    energy: 'calm',   dur: 0.6, use: 'title card → the product (a focus opens on the screen); one per film.' },
    'chromatic-split': { kind: 'canvas', energy: 'high',   dur: 0.25, use: 'problem beat on a recreated card only (reads as a jolt).' },
    'noise-dissolve':  { kind: 'canvas', energy: 'calm',   dur: 0.7, use: 'between two RECREATED cards (never footage → footage).' },
    'cross-warp':      { kind: 'canvas', energy: 'medium', dur: 0.5, use: 'between two RECREATED cards when one should "become" the other.' }
  };
  /* seam(kind, t, t0, dur, o) → {u, active, from, to, overlay, ring} style objects (CSS kinds), or {u, active,
     canvas:true} for the canvas kinds (then call drawSeam). u is power2.inOut of (t-t0)/dur. */
  function seam(kind, t, t0, dur, o) {
    o = o || {}; const S = SEAMS[kind]; if (!S) throw new Error('VFX.seam: unknown kind ' + kind);
    dur = dur || S.dur; let x = clamp((t - t0) / Math.max(1e-6, dur), 0, 1); if (x > 1 - 1e-6) x = 1; if (x < 1e-6) x = 0;   // float-safe ends
    const u = (o.ease || EIO2)(x), active = t >= t0 && t < t0 + dur;
    const r = { kind, u, active, from: {}, to: {}, overlay: { opacity: '0' }, ring: { opacity: '0' } };
    if (S.kind === 'canvas') { r.canvas = true; return r; }
    if (kind === 'flash-white') {
      const white = u < 0.5 ? sstep(0, 0.45, u) : 1 - sstep(0.5, 1, u);
      r.from.opacity = u < 0.5 ? '1' : '0'; r.to.opacity = u < 0.5 ? '0' : '1';
      r.overlay = { opacity: white.toFixed(4), background: o.color || '#ffffff' };
    } else if (kind === 'blur-dissolve') {
      const cap = clamp(o.blur === undefined ? 15 : o.blur, 0, 30), a = EIN2(x), b = EOUT2(x);
      r.from = { filter: 'blur(' + (cap * a).toFixed(2) + 'px)', transform: 'scale(' + (1 + 0.05 * a).toFixed(4) + ')', opacity: (1 - a).toFixed(4) };
      r.to = { filter: 'blur(' + (cap * (1 - b)).toFixed(2) + 'px)', transform: 'scale(' + (0.95 + 0.05 * b).toFixed(4) + ')', opacity: b.toFixed(4) };
      if (x >= 1) { r.from.filter = 'none'; r.to.filter = 'none'; r.to.transform = 'none'; }
      if (x <= 0) { r.from.filter = 'none'; r.from.transform = 'none'; }
    } else if (kind === 'iris') {
      const H = o.H || H0, rad = 1.2 * u * H, cx = o.cx === undefined ? 50 : o.cx, cy = o.cy === undefined ? 50 : o.cy;
      r.from.opacity = '1'; r.to.opacity = '1';
      r.to.clipPath = x >= 1 ? 'none' : 'circle(' + rad.toFixed(1) + 'px at ' + cx + '% ' + cy + '%)';
      const glow = u * (1 - u) * 4 * 0.6;
      r.ring = { opacity: glow.toFixed(4), width: (2 * rad).toFixed(1) + 'px', height: (2 * rad).toFixed(1) + 'px',
                 left: 'calc(' + cx + '% - ' + rad.toFixed(1) + 'px)', top: 'calc(' + cy + '% - ' + rad.toFixed(1) + 'px)', borderColor: o.accent || '#E56B5E' };
    }
    return r;
  }
  /* applySeam(layers, st): layers = {from, to, overlay, ring} elements (any may be null). Idempotent. */
  function applySeam(L, st) {
    const set = (el, s) => { if (!el || !s) return; for (const k in s) if (el.style[k] !== s[k]) el.style[k] = s[k]; };
    set(L.from, st.from); set(L.to, st.to); set(L.overlay, st.overlay); set(L.ring, st.ring);
  }
  function noiseMask(key, W, H, u, o) {
    const tw = 320, th = 180, tile = off(key, tw, th), tctx = tile.getContext('2d'), im = tctx.createImageData(tw, th), d = im.data;   // 320x180: a smooth edge at the threshold
    const sc = (o.scale || 3) / tw, seed = o.seed | 0;
    for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
      const n = fbm(x * sc * 4 / 3 + 3.1, y * sc * 0.75 + 1.7, seed + 11, 5, 0.5, 2.02), a = sstep(0.4, 0.6, n + u * 1.2 - 0.6);
      const i = (y * tw + x) * 4; d[i] = 0; d[i + 1] = 0; d[i + 2] = 0; d[i + 3] = Math.round(a * 255);
    }
    tctx.putImageData(im, 0, 0); return tile;
  }
  function rowWarp(key, img, W, H, amp, o) {
    const c = off(key, W, H), x = c.getContext('2d'), rows = o.rows || 4, ky = img.height / H; x.clearRect(0, 0, W, H);
    for (let y = 0; y < H; y += rows) {
      const h = Math.min(rows, H - y), n = fbm(0.37, (y + h / 2) / H * 3, (o.seed | 0) + 5, 5, 0.5, 2.02) - 0.5;
      x.drawImage(img, 0, y * ky, img.width, h * ky, Math.round(n * amp), y, W, h);
    }
    return c;
  }
  /* drawSeam(kind, ctx, fromImg, toImg, u, o): the canvas kinds. Pure in (u, seed, images); u=0 draws fromImg
     exactly, u=1 draws toImg exactly.
       chromatic-split  from split by 0.06*u, to split by 0.06*(1-u), mixed by u
       noise-dissolve   to shown where smoothstep(0.4,0.6, fbm + 1.2u - 0.6) (5-octave quintic fBm, 160x90 tile)
       cross-warp       rows of from drift +0.5*u*disp, rows of to drift -0.5*(1-u)*disp, blended by the same noise */
  function drawSeam(kind, ctx, fromImg, toImg, u, o) {
    o = o || {}; assertRecreated(ctx, 'drawSeam'); u = clamp(u, 0, 1);
    const W = o.W || ctx.canvas.width, H = o.H || ctx.canvas.height;
    ctx.save(); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
    if (u <= 0) { ctx.drawImage(fromImg, 0, 0, W, H); ctx.restore(); return; }
    if (u >= 1) { ctx.drawImage(toImg, 0, 0, W, H); ctx.restore(); return; }
    if (kind === 'chromatic-split') {
      chromaticSplit(ctx, fromImg, 0.06 * u, { w: W, h: H, key: 'csF' });
      const toC = off('csTo', W, H), tc = toC.getContext('2d'); tc.clearRect(0, 0, W, H); chromaticSplit(tc, toImg, 0.06 * (1 - u), { w: W, h: H, key: 'csT' });
      ctx.globalAlpha = u; ctx.drawImage(toC, 0, 0, W, H);
    } else if (kind === 'noise-dissolve' || kind === 'cross-warp') {
      const warp = kind === 'cross-warp', amp = 0.5 * W * (o.amp === undefined ? 1 : o.amp);
      const A = warp ? rowWarp('cwA', fromImg, W, H, amp * u, o) : fromImg, B = warp ? rowWarp('cwB', toImg, W, H, -amp * (1 - u), o) : toImg;
      ctx.drawImage(A, 0, 0, W, H);
      const m = off('ndM', W, H), mx = m.getContext('2d'); mx.save(); mx.globalCompositeOperation = 'source-over'; mx.clearRect(0, 0, W, H); mx.drawImage(B, 0, 0, W, H);
      mx.globalCompositeOperation = 'destination-in'; mx.imageSmoothingEnabled = true; mx.imageSmoothingQuality = 'high'; mx.drawImage(noiseMask('ndT', W, H, u, o), 0, 0, W, H); mx.restore();
      ctx.drawImage(m, 0, 0, W, H);
    } else throw new Error('VFX.drawSeam: ' + kind + ' is not a canvas seam');
    ctx.restore();
  }
  /* seamWindows(list) → [{t0, t1, kind}] for export_timeline.js, so QA skips cut frames inside a seam. */
  const seamWindows = list => (list || []).map(s => ({ t0: s.at, t1: s.at + (s.dur || SEAMS[s.seam].dur), kind: s.seam }));
  const inSeam = (t, list) => seamWindows(list).some(w => t >= w.t0 - 1e-6 && t <= w.t1 + 1e-6);

  /* ---------- speed ramp maths (seq clips) ---------- */
  /* A lane is [[t, rate], ...] in clip-local seconds, optionally [t, rate, curve] with curve −1..1 bending the
     segment that starts at that point (x^(2^(2*curve))). Rates clamp to 0.1..10; interpolation is in LOG space
     (0.5 → 2 passes 1 at the midpoint). srcTime(lane, dt) is the trapezoid integral tabulated at 48 cells per
     segment and binary-searched, so preview and render agree. */
  const RMIN = 0.1, RMAX = 10, CELLS = 48, _tables = new WeakMap();
  const normLane = lane => (lane || []).map(p => [p[0], clamp(p[1], RMIN, RMAX), p[2] || 0]).sort((a, b) => a[0] - b[0]);
  function rateAt(lane, dt) {
    const P = normLane(lane); if (!P.length) return 1;
    if (dt <= P[0][0]) return P[0][1]; if (dt >= P[P.length - 1][0]) return P[P.length - 1][1];
    let lo = 0, hi = P.length - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (P[m][0] <= dt) lo = m; else hi = m; }
    const a = P[lo], b = P[hi], span = b[0] - a[0]; if (span <= 0) return b[1];
    let x = (dt - a[0]) / span; if (a[2]) x = Math.pow(x, Math.pow(2, 2 * a[2]));
    return Math.exp(Math.log(a[1]) + (Math.log(b[1]) - Math.log(a[1])) * x);
  }
  function table(lane) {
    let T = _tables.get(lane); if (T) return T;
    const P = normLane(lane), ts = [0], ss = [0];
    const push = t => { const pt = ts[ts.length - 1]; if (t <= pt) return; ts.push(t); ss.push(ss[ss.length - 1] + (rateAt(lane, pt) + rateAt(lane, t)) / 2 * (t - pt)); };
    if (P.length) { push(Math.max(0, P[0][0])); for (let i = 1; i < P.length; i++) { const a = P[i - 1][0], b = P[i][0]; if (b <= 0) continue; for (let k = 1; k <= CELLS; k++) push(Math.max(a, 0) + (b - a) * k / CELLS); } }
    T = { ts, ss, first: P.length ? P[0][1] : 1, last: P.length ? P[P.length - 1][1] : 1 }; _tables.set(lane, T); return T;
  }
  const interp = (xs, ys, x) => { let lo = 0, hi = xs.length - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] <= x) lo = m; else hi = m; } return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo]); };
  function srcTime(lane, dt) {
    if (typeof lane === 'number') return dt * lane;
    const T = table(lane), n = T.ts.length - 1;
    if (dt <= 0) return dt * T.first; if (dt >= T.ts[n]) return T.ss[n] + (dt - T.ts[n]) * T.last; return interp(T.ts, T.ss, dt);
  }
  function timeAt(lane, s) {
    if (typeof lane === 'number') return s / lane;
    const T = table(lane), n = T.ts.length - 1;
    if (s <= 0) return s / T.first; if (s >= T.ss[n]) return T.ts[n] + (s - T.ss[n]) / T.last; return interp(T.ss, T.ts, s);
  }
  /* frameAt(lane, dt, fps, nFrames, from=1) → source frame index on the film clock, held on the last frame. */
  function frameAt(lane, dt, fps, nFrames, from) {
    from = from || 1; const f = from + Math.floor(Math.max(0, srcTime(lane, Math.max(0, dt))) * fps + 1e-6); return clamp(f, from, nFrames);
  }
  /* rampTo(revealSrc, landAt, ease=0.25) → a lane that runs fast through the wait and is at exactly 1.0× when the
     source moment `revealSrc` (clip-local source seconds) is on screen at clip time `landAt` (a wt() word), easing
     into 1× over the last `ease` seconds. Returns null when the rate would leave 0.1..10. Never below 0.5× on UI
     motion: a stall reads as a bug. */
  function rampTo(revealSrc, landAt, ease) {
    ease = Math.min(ease === undefined ? 0.25 : ease, landAt); const flat = landAt - ease;
    const integral = r => r * flat + (Math.abs(r - 1) < 1e-9 ? ease : ease * (r - 1) / Math.log(r));
    let lo = RMIN, hi = RMAX; if (revealSrc < integral(lo) || revealSrc > integral(hi)) return null;
    for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (integral(m) < revealSrc) lo = m; else hi = m; }
    const r = (lo + hi) / 2; return flat > 0 ? [[0, r], [flat, r], [landAt, 1]] : [[0, r], [landAt, 1]];
  }
  const ramp = { RMIN, RMAX, CELLS, rateAt, srcTime, timeAt, frameAt, rampTo, table };

  root.VFX = { FOOTAGE_SELECTOR, isFootage, assertRecreated, hash, vnoise, fbm, sstep, EIO2,
               vignette, vignetteParams, vignetteMask, grain, bloom, bloomGhostStyle, applyBloomGhost,
               matteStyle, applyMatte, clearMatte, haze, chromaticSplit, glitch, waveWarp,
               SEAMS, seam, applySeam, drawSeam, seamWindows, inSeam, ramp, frameIndex };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.VFX;
})(typeof window !== 'undefined' ? window : globalThis);
