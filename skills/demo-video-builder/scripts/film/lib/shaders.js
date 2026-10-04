/* shaders.js — GL: a WebGL2 layer for a clock-driven film. window.GL.

   What it is for
     Two pictures in, one picture out, at a progress u the scene computes from the film clock. The pictures are
     product frames (<img> from the footage lane), recreated cards drawn to a <canvas>, or the output of another
     GL call. Fragment programs do the work: seven cut transitions and four finishing passes, all written here.

   Contract (same as motion.js / grammar.js)
     - Pure functions of (t → u, frame index) plus explicit state. No wall clock, no unseeded random source (seeds
       come from params or MOTION.rng), no scheduling. Nothing renders in a loop: every draw happens inside the scene's
       frame(t), so __seek(t) and __step(t) paint the same pixels. The only time-like uniforms are u and the
       integer frame index the scene passes for grain.
     - Software GL safe: RGBA8 (UNSIGNED_BYTE) textures and framebuffers only, highp float in the fragment stage,
       no extensions. Rendering with ANGLE on SwiftShader gives bit-identical frames across runs.
     - Real footage is sacred: a transition may pass over product pixels only inside the cut window, and that window
       is <= GL.FOOTAGE.maxDur (0.5 s). When from() or to() is the footage lane (GL.isFootage: #clipWrap and its
       descendants, [data-footage] — footage.js marks its off-DOM imageFor() images the same way) GL.cutTransition
       defaults dur to 0.5 s, refuses anything longer (at registration when the thunks resolve, and again on the
       first draw), and puts the hidden step GL.FOOTAGE.split = 0.15 of the way into the window on the footage side:
       at 0.5 s that is 0.075 s, so two frames of streak or displacement touch product pixels (the first of them at
       zero envelope) and the picture cut lands where the ledger put it. Card <-> card cuts keep GL.DUR and a
       centred step (`split` 0.5). Finishing passes (vignette, grain, bloom, chromaticAberration) are for recreated
       layers only. GL.pass refuses a texture whose source element is the footage lane.

   Sources
     GL.texture(ctx, source) accepts <img>, <canvas>, <video> (its current frame), ImageBitmap, ImageData or an
     FBO texture returned by another GL call. A DOM subtree cannot be read back synchronously by the browser, so
     a recreated card must be DRAWN to a canvas by the scene (GL.cardCanvas / GL.textCard do the common case) —
     GL.snapshotToCanvas documents and enforces that: it accepts drawable things and throws for other elements.

   Orientation and colour
     Image space has v = 0 at the TOP. Uploads are not flipped; the vertex stage flips when drawing to the canvas
     and leaves FBO targets unflipped, so an FBO texture reads back exactly like an uploaded image. Uploads skip
     the browser's colour-space conversion; mixing happens in encoded (sRGB) space so u = 0 is A to the byte and
     u = 1 is B to the byte. Additive light (leak, edge glow, bloom) uses a screen combine (1 - (1-a)(1-b)) which
     never clips. The canvas is opaque by default (alpha:false): no premultiplication path to get wrong. With
     {alpha:true} the fragment stage writes premultiplied colour, as the compositor expects.

   Edges
     Every texture is CLAMP_TO_EDGE (or MIRRORED_REPEAT with {wrap:'mirror'}). Programs that displace samples
     (slit scan, cross warp, dissolve, chroma split) read through tapA/tapB, which can instead return a flat fill
     colour outside [0,1] ({fill:'edge', edgeColor}) — the stage ground, so a displaced slice shows navy rather
     than a smeared border.

   Measured defaults (per effect, see the table in TRANSITIONS / PASSES below and references/gl-layer.md)
     chromaSplit 0.25–0.5 s: channel offset 3.5 % of the half-frame at the edge, 1.5 % zoom at the peak, cut at
     u = 0.5 under the peak. warpDissolve 0.4–0.6 s: 4-octave value noise at 2.6 cycles, feather 0.12, domain
     warp 0.6. lightLeak 0.7 s card <-> card (0.5 s with footage on a side): streak sigma 12 % of the half-frame, −20°,
     intensity 0.6 (1.0 read as a saturated reel beam and tinted the footage side gold), gold core / coral halo, cut
     under the brightest moment. flashWhite 0.28 s: 0.55 → 0 on power 1.6. iris: superellipse power 2 (circle) … 6, feather 6 %.
     slitScan 0.45 s: 48 slices, 18 % amplitude. crossWarp 0.5 s: 18 % travel on the house current, 12 % zoom.
     vignette 0.75·amount darkening, superellipse power 8 → 1.8 by roundness. grain: cells 1.5 px, strength 0.06,
     midtone-masked. bloom: threshold 0.72, 9 taps (0.227 0.195 0.122 0.054 0.016) at half resolution, amount 0.55.
     chromaticAberration 0.25 % radial. */
(function (root) {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const FOOTAGE_SELECTOR = '#clipWrap, [data-footage]';

  /* ---------- small utilities ---------- */
  function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rgb(c, dflt) {
    if (c === undefined || c === null) c = dflt;
    if (Array.isArray(c)) return c.length === 3 ? c : c.slice(0, 3);
    if (typeof c === 'string') {
      const m = c.replace('#', ''); const n = parseInt(m.length === 3 ? m.split('').map(ch => ch + ch).join('') : m, 16);
      return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
    }
    return rgb(dflt);
  }
  const EASES = {
    linear: x => x,
    in: x => x * x,
    out: x => 1 - (1 - x) * (1 - x),
    inOut: x => x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2,
    p4out: x => 1 - Math.pow(1 - x, 4)
  };
  const easeFn = e => typeof e === 'function' ? e : (EASES[e] || EASES.linear);
  const frameIndex = (t, fps) => Math.round(t * (fps || 30));
  function isFootage(el) {
    if (!el || typeof el !== 'object' || typeof Element === 'undefined' || !(el instanceof Element)) return false;
    return !!((el.matches && el.matches(FOOTAGE_SELECTOR)) || (el.closest && el.closest(FOOTAGE_SELECTOR)) || (el.dataset && 'footage' in el.dataset));
  }

  /* ---------- GLSL ---------- */
  const VERT = `#version 300 es
layout(location=0) in vec2 aPos; uniform float uFlip; out vec2 vUv;
void main(){ vUv = vec2(aPos.x*0.5+0.5, mix(aPos.y*0.5+0.5, 0.5-aPos.y*0.5, uFlip)); gl_Position = vec4(aPos,0.0,1.0); }`;

  const HEAD = `#version 300 es
precision highp float; precision highp int;
in vec2 vUv; out vec4 oCol;
uniform sampler2D uA; uniform sampler2D uB;
uniform float uU; uniform float uFrame; uniform float uSeed; uniform vec2 uRes; uniform float uAspect; uniform float uAlpha;
uniform vec4 uP0; uniform vec4 uP1; uniform vec4 uP2; uniform vec3 uEdge; uniform float uEdgeMode;
const float PI = 3.14159265358979;
uint pcg(uint v){ uint s = v*747796405u + 2891336453u; uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u; return (w >> 22u) ^ w; }
float h2(vec2 p, float seed){ uvec2 q = uvec2(ivec2(floor(p)) + 32768); uint h = pcg(q.x + pcg(q.y + pcg(uint(abs(seed)) + 40503u))); return float(h) * 2.3283064365386963e-10; }
float vnoise(vec2 p, float s){ vec2 i = floor(p), f = fract(p); vec2 w = f*f*f*(f*(f*6.0-15.0)+10.0);
  float a = h2(i, s), b = h2(i+vec2(1.0,0.0), s), c = h2(i+vec2(0.0,1.0), s), d = h2(i+vec2(1.0,1.0), s);
  return mix(mix(a,b,w.x), mix(c,d,w.x), w.y); }
float fbm(vec2 p, float s){ float v = 0.0, a = 0.5; mat2 R = mat2(0.8,0.6,-0.6,0.8);
  for (int i = 0; i < 4; i++) { v += a*vnoise(p, s + float(i)*17.0); p = R*p*2.03 + vec2(1.7,9.2); a *= 0.5; } return v; }
bool outside(vec2 uv){ return uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0; }
vec4 tapA(vec2 uv){ if (uEdgeMode > 0.5 && outside(uv)) return vec4(uEdge, 1.0); return texture(uA, uv); }
vec4 tapB(vec2 uv){ if (uEdgeMode > 0.5 && outside(uv)) return vec4(uEdge, 1.0); return texture(uB, uv); }
float luma(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }
vec3 screenAdd(vec3 base, vec3 light){ return 1.0 - (1.0 - base) * (1.0 - clamp(light, 0.0, 1.0)); }
float bell(float u){ float s = sin(PI*u); return s*s; }
float sstep(float a, float b, float x){ return smoothstep(a, b, x); }
/* the hidden cut: a hard step at u = 0.5 by default (no frame is ever a 50/50 blend); w > 0 feathers it by ±w of u */
float cutmix(float u, float w){ return w > 1e-4 ? smoothstep(0.5 - w, 0.5 + w, u) : step(0.5, u); }
`;
  const TAIL = `
void main(){ vec4 c = run(vUv); if (uAlpha > 0.5) c.rgb *= c.a; oCol = c; }`;

  /* every effect: fragment body with `vec4 run(vec2 uv)`, defaults, pack(params) → uniform slots */
  const TRANSITIONS = {
    /* RGB channels diverge radially from a centre and converge again; the cut hides under the peak */
    chromaSplit: {
      dur: 0.35,
      defaults: { amount: 0.035, zoom: 0.015, cut: 0, centre: [0.5, 0.5] },
      pack: p => ({ P0: [p.amount, p.zoom, p.cut, 0], P1: [p.centre[0], p.centre[1], 0, 0] }),
      frag: `vec4 run(vec2 uv){
  float u = uU, e = bell(u); vec2 c = uP1.xy;
  float z = 1.0 + uP0.y*e; vec2 p = c + (uv - c)/z;
  vec2 d = (uv - c)*vec2(uAspect, 1.0); vec2 off = d*uP0.x*e; off.x /= uAspect;
  float m = cutmix(u, uP0.z);
  /* red and blue are smeared along the split (5 taps from 0.5x to 1.5x of the offset): lens separation, not three copies */
  vec3 col = vec3(0.0); float ws = 0.0;
  for (int i = -2; i <= 2; i++) { float k = float(i)*0.5, w = 1.0 - 0.35*abs(k);
    vec2 pr = p + off*(1.0 + 0.5*k), pb = p - off*(1.0 + 0.5*k);
    col.r += mix(tapA(pr).r, tapB(pr).r, m)*w; col.b += mix(tapA(pb).b, tapB(pb).b, m)*w; ws += w; }
  col.r /= ws; col.b /= ws; col.g = mix(tapA(p).g, tapB(p).g, m);
  return vec4(col, 1.0); }`
    },
    /* seeded, domain-warped value noise sweeps a soft threshold across the picture; both sides breathe in the window */
    warpDissolve: {
      dur: 0.5,
      defaults: { scale: 2.6, feather: 0.12, warp: 0.6, edge: 0, edgeColor: '#E8C874' },
      pack: p => ({ P0: [p.scale, p.feather, p.warp, p.edge], P1: rgb(p.edgeColor, '#E8C874').concat([0]) }),
      frag: `vec4 run(vec2 uv){
  float u = uU; vec2 q = uv*vec2(uAspect, 1.0)*uP0.x;
  vec2 w = vec2(fbm(q + uSeed, 3.0), fbm(q + vec2(5.2, 1.3) + uSeed, 11.0)) - 0.5;
  float n = fbm(q + w*uP0.z*2.0, uSeed); n = clamp((n - 0.2)/0.6, 0.0, 1.0);
  float f = uP0.y, th = mix(-f, 1.0 + f, u);
  float m = 1.0 - sstep(th - f, th + f, n);
  float e = u*(1.0 - u)*4.0; vec2 dA = w*uP0.z*0.03*e, dB = -w*uP0.z*0.03*e;
  vec3 col = mix(tapA(uv + dA).rgb, tapB(uv + dB).rgb, m);
  float band = 1.0 - sstep(0.0, f*1.5, abs(n - th));
  return vec4(screenAdd(col, uP1.rgb*band*uP0.w*e), 1.0); }`
    },
    /* a warm streak sweeps across the frame; the cut sits under its brightest moment at the frame centre */
    lightLeak: {
      dur: 0.7,
      defaults: { angle: -0.35, width: 0.1, intensity: 0.6, color: '#E8C874', color2: '#E56B5E', cut: 0 },
      pack: p => ({ P0: [p.angle, p.width, p.intensity, 0], P1: rgb(p.color, '#E8C874').concat([0]), P2: rgb(p.color2, '#E56B5E').concat([p.cut]) }),
      frag: `vec4 run(vec2 uv){
  float u = uU; vec2 p = (uv - 0.5)*vec2(uAspect, 1.0);
  vec2 dir = vec2(cos(uP0.x), sin(uP0.x)); float along = dot(p, dir), across = dot(p, vec2(-dir.y, dir.x));
  float d = along - mix(-1.1, 1.1, u), w = max(uP0.y, 0.01); float env = bell(u);
  /* three widths stacked (core, skirt, haze) plus a thin trailing streak: a leak, not a beam */
  float core = exp(-d*d/(w*w)), skirt = 0.6*exp(-d*d/(w*w*6.0)), haze = 0.35*exp(-d*d/(w*w*20.0));
  float d2 = d + 2.2*w; float trail = 0.4*exp(-d2*d2/(w*w*0.5));
  float grainy = 0.7 + 0.6*fbm(vec2(across*2.5, along*0.6) + uSeed, 5.0);
  float leak = (core + skirt + haze + trail)*grainy*uP0.z*env;
  vec3 lc = mix(uP2.rgb, uP1.rgb, clamp(core*1.2 + trail, 0.0, 1.0));
  float m = cutmix(u, uP2.w);
  vec3 base = mix(tapA(uv).rgb, tapB(uv).rgb, m);
  vec3 col = screenAdd(base, lc*leak) + vec3(0.12)*core*env*uP0.z;
  return vec4(clamp(col, 0.0, 1.0), 1.0); }`
    },
    /* a white hit on the cut frame that decays to nothing; optional short rise on A before the cut */
    flashWhite: {
      dur: 0.28,
      defaults: { peak: 0.55, power: 1.6, rise: 0, color: '#FFFFFF' },
      pack: p => ({ P0: [p.peak, p.power, p.rise, 0], P1: rgb(p.color, '#FFFFFF').concat([0]) }),
      frag: `vec4 run(vec2 uv){
  float u = uU, r = uP0.z; float m = step(r, u); float w;
  if (u < r) w = uP0.x*pow(u/max(r, 1e-4), 2.0); else w = uP0.x*pow(clamp(1.0 - (u - r)/max(1.0 - r, 1e-4), 0.0, 1.0), uP0.y);
  vec3 base = mix(tapA(uv).rgb, tapB(uv).rgb, m);
  return vec4(mix(base, uP1.rgb, w), 1.0); }`
    },
    /* superellipse reveal: power 2 is a circle, 4–6 a rounded rectangle; direction +1 grows B, −1 shrinks A */
    iris: {
      dur: 0.6,
      defaults: { power: 2, feather: 0.06, direction: 1, centre: [0.5, 0.5], ease: 'inOut' },
      pack: p => ({ P0: [p.power, p.feather, p.direction, 0], P1: [p.centre[0], p.centre[1], 0, 0] }),
      frag: `vec4 run(vec2 uv){
  float u = uU; vec2 c = uP1.xy; float n = max(uP0.x, 1.0), f = uP0.y;
  vec2 d = (uv - c)*vec2(uAspect, 1.0); float r = pow(pow(abs(d.x), n) + pow(abs(d.y), n), 1.0/n);
  vec2 far = max(c, 1.0 - c)*vec2(uAspect, 1.0); float R = pow(pow(far.x, n) + pow(far.y, n), 1.0/n);
  float m;
  if (uP0.z >= 0.0) { float rad = mix(-f, R + f, u); m = 1.0 - sstep(rad - f, rad + f, r); }
  else { float rad = mix(-f, R + f, 1.0 - u); m = sstep(rad - f, rad + f, r); }
  return vec4(mix(tapA(uv).rgb, tapB(uv).rgb, m), 1.0); }`
    },
    /* vertical slices on a wipe that travels left → right with a sine ripple: in each slice A slides out along the
       wave and B slides in behind it. `scatter` 0 = pure travelling wipe, 1 = every slice on its own sine schedule */
    slitScan: {
      dur: 0.45,
      defaults: { slices: 32, amplitude: 0.22, frequency: 0.9, spread: 0.7, soft: 0.1, scatter: 0.25, fill: 'edge' },
      pack: p => ({ P0: [p.slices, p.amplitude, p.frequency, p.spread], P1: [p.soft, p.scatter, 0, 0] }),
      frag: `vec4 run(vec2 uv){
  float u = uU, N = max(uP0.x, 1.0); float idx = floor(uv.x*N);
  float ph = idx*uP0.z + uSeed*0.01; float s = sin(ph);
  float delay = mix((idx + 0.5)/N, 0.5 + 0.5*sin(ph*1.7 + 1.3), clamp(uP1.y, 0.0, 1.0));
  float p = clamp(u*(1.0 + uP0.w) - delay*uP0.w, 0.0, 1.0);
  float pe = p*p*(3.0 - 2.0*p);
  float m = cutmix(pe, uP1.x);
  float dirn = sign(s) + step(abs(s), 1e-3);
  vec3 a = tapA(vec2(uv.x, uv.y + dirn*(0.6 + 0.4*abs(s))*uP0.y*pe)).rgb;
  vec3 b = tapB(vec2(uv.x, uv.y - dirn*(0.6 + 0.4*abs(s))*uP0.y*(1.0 - pe))).rgb;
  return vec4(mix(a, b, m), 1.0); }`
    },
    /* both pictures travel the same vector: A grows and leaves on the current, B arrives from behind the frame */
    crossWarp: {
      dur: 0.5,
      defaults: { dir: [-1, 0], amount: 0.18, zoom: 0.12, warp: 0.05, soft: 0.22, region: 0.3 },
      pack: p => ({ P0: [p.dir[0], p.dir[1], p.amount, p.zoom], P1: [p.warp, p.soft, p.region, 0] }),
      frag: `vec4 run(vec2 uv){
  float u = uU, ue = u*u*(3.0 - 2.0*u); vec2 dir = uP0.xy;
  vec2 q = uv*vec2(uAspect, 1.0);
  /* a gentle liquid displacement (±warp/2 of the frame at the peak) and a broad, separate field that decides which
     regions hand over first — the picture bends, it never melts */
  vec2 w = (vec2(fbm(q*2.0 + uSeed, 2.0), fbm(q*2.0 + uSeed + 7.0, 9.0)) - 0.5)*uP1.x;
  float region = (fbm(q*0.9 + uSeed + 3.0, 4.0) - 0.5)*2.0*uP1.z;
  float e = ue*(1.0 - ue)*4.0;
  float zA = 1.0 + uP0.w*ue, zB = 1.0 + uP0.w*(1.0 - ue);
  vec2 pA = 0.5 + (uv - 0.5)/zA - dir*uP0.z*ue + w*e;
  vec2 pB = 0.5 + (uv - 0.5)/zB + dir*uP0.z*(1.0 - ue) + w*e;
  float m = cutmix(ue + region*e, uP1.y);
  return vec4(mix(tapA(pA).rgb, tapB(pB).rgb, m), 1.0); }`
    }
  };

  const PASSES = {
    /* plain copy with an optional zoom about a centre (the sanctioned slow push, driven by a MOTION proxy) */
    copy: {
      defaults: { zoom: 1, centre: [0.5, 0.5] },
      pack: p => ({ P0: [p.zoom, 0, 0, 0], P1: [p.centre[0], p.centre[1], 0, 0] }),
      frag: `vec4 run(vec2 uv){ vec2 c = uP1.xy; return vec4(tapA(c + (uv - c)/max(uP0.x, 1e-3)).rgb, 1.0); }`
    },
    vignette: {
      defaults: { amount: 0.12, mid: 0.78, feather: 0.45, roundness: 0.5 },
      pack: p => ({ P0: [p.amount, p.mid, p.feather, p.roundness] }),
      frag: `vec4 run(vec2 uv){
  vec3 c = tapA(uv).rgb; vec2 d = (uv - 0.5)*2.0; float n = mix(8.0, 1.8, clamp(uP0.w, 0.0, 1.0));
  float r = pow(pow(abs(d.x), n) + pow(abs(d.y), n), 1.0/n);
  float dark = 0.75*uP0.x*sstep(uP0.y - uP0.z, uP0.y + uP0.z, r);
  return vec4(c*(1.0 - dark), 1.0); }`
    },
    grain: {
      defaults: { amount: 0.06, size: 1.5, roughness: 0.6, midtones: 0.8, frame: 0 },
      pack: p => ({ P0: [p.amount, p.size, p.roughness, p.midtones], frame: p.frame }),
      frag: `vec4 run(vec2 uv){
  vec3 c = tapA(uv).rgb; vec2 px = gl_FragCoord.xy; float cell = max(1.0, uP0.y);
  float n1 = h2(floor(px/cell), uFrame*7.0 + 1.0), n2 = h2(floor(px/(cell*2.5)), uFrame*13.0 + 2.0);
  float n = mix(n1, n2, 0.35*uP0.z) - 0.5;
  float L = luma(c); float mask = mix(1.0, 1.0 - abs(L*2.0 - 1.0), uP0.w);
  return vec4(clamp(c + n*uP0.x*mask, 0.0, 1.0), 1.0); }`
    },
    chromaticAberration: {
      defaults: { amount: 0.0025, power: 1.5 },
      pack: p => ({ P0: [p.amount, p.power, 0, 0] }),
      frag: `vec4 run(vec2 uv){
  vec2 d = uv - 0.5; float r = length(d*vec2(uAspect, 1.0))/0.9;
  vec2 off = d*uP0.x*pow(clamp(r, 0.0, 1.5), uP0.y)*4.0;
  return vec4(tapA(uv + off).r, tapA(uv).g, tapA(uv - off).b, 1.0); }`
    },
    /* bloom is a composite: bright pass → half-res → 9-tap blur H → V → screen-combine over the source */
    bloom: { defaults: { threshold: 0.72, knee: 0.1, radius: 1.0, amount: 0.55 }, composite: true },
    _bright: {
      defaults: {}, pack: p => ({ P0: [p.threshold, p.knee, 0, 0] }),
      frag: `vec4 run(vec2 uv){ vec3 c = tapA(uv).rgb; float L = luma(c);
  float k = max(uP0.y, 1e-3); float w = sstep(uP0.x - k, uP0.x + k, L); return vec4(c*w, 1.0); }`
    },
    _blur9: {
      defaults: {}, pack: p => ({ P0: [p.dx, p.dy, 0, 0] }),
      frag: `vec4 run(vec2 uv){ vec2 st = uP0.xy/uRes;
  const float W0 = 0.2270270, W1 = 0.1945946, W2 = 0.1216216, W3 = 0.0540541, W4 = 0.0162162;
  vec3 c = tapA(uv).rgb*W0;
  c += (tapA(uv + st).rgb + tapA(uv - st).rgb)*W1; c += (tapA(uv + 2.0*st).rgb + tapA(uv - 2.0*st).rgb)*W2;
  c += (tapA(uv + 3.0*st).rgb + tapA(uv - 3.0*st).rgb)*W3; c += (tapA(uv + 4.0*st).rgb + tapA(uv - 4.0*st).rgb)*W4;
  return vec4(c, 1.0); }`
    },
    _bloomMix: {
      defaults: {}, pack: p => ({ P0: [p.amount, 0, 0, 0] }),
      frag: `vec4 run(vec2 uv){ vec3 base = tapA(uv).rgb, glow = tapB(uv).rgb*uP0.x; return vec4(screenAdd(base, glow), 1.0); }`
    }
  };

  /* ---------- context ---------- */
  function create(canvas, o) {
    o = o || {};
    const dpr = o.dpr || 1, W = Math.round((o.width || 1280) * dpr), H = Math.round((o.height || 720) * dpr);
    canvas.width = W; canvas.height = H;
    if (o.css !== false) { canvas.style.width = (o.width || 1280) + 'px'; canvas.style.height = (o.height || 720) + 'px'; }
    const alpha = !!o.alpha;
    const gl = canvas.getContext('webgl2', { alpha, antialias: false, depth: false, stencil: false, premultipliedAlpha: true,
      preserveDrawingBuffer: true, powerPreference: 'low-power', failIfMajorPerformanceCaveat: false, desynchronized: false });
    if (!gl) throw new Error('shaders.js: WebGL2 is not available (render with --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader for software GL)');
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.disable(gl.BLEND); gl.disable(gl.DEPTH_TEST); gl.disable(gl.SCISSOR_TEST); gl.disable(gl.DITHER);
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    const vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vb);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const ctx = { gl, canvas, W, H, dpr, alpha, vao, programs: {}, fbos: [], half: [], cache: new WeakMap(), cuts: [], shown: null, lost: false,
      edgeColor: rgb(o.edgeColor, '#082A34') };
    canvas.addEventListener('webglcontextlost', e => { e.preventDefault(); ctx.lost = true; });
    canvas.addEventListener('webglcontextrestored', () => { ctx.lost = false; ctx.programs = {}; ctx.fbos = []; ctx.half = []; ctx.cache = new WeakMap(); });
    show(ctx, false);
    return ctx;
  }
  function destroy(ctx) {
    const gl = ctx.gl;
    Object.values(ctx.programs).forEach(p => gl.deleteProgram(p.p));
    ctx.fbos.concat(ctx.half).forEach(f => { gl.deleteFramebuffer(f.fb); gl.deleteTexture(f.tex); });
    ctx.programs = {}; ctx.fbos = []; ctx.half = []; ctx.cuts = [];
  }
  function show(ctx, on) {
    const v = on ? 'visible' : 'hidden';
    if (ctx.shown !== v) { ctx.canvas.style.visibility = v; ctx.shown = v; }
  }

  /* ---------- programs ---------- */
  function compile(gl, type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(s); gl.deleteShader(s);
      throw new Error('shaders.js: GLSL compile failed\n' + log + '\n' + src.split('\n').map((l, i) => (i + 1) + ': ' + l).join('\n'));
    }
    return s;
  }
  function program(ctx, name) {
    if (ctx.programs[name]) return ctx.programs[name];
    const def = TRANSITIONS[name] || PASSES[name];
    if (!def || !def.frag) throw new Error('shaders.js: unknown effect "' + name + '"');
    const gl = ctx.gl, p = gl.createProgram();
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, VERT)); gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, HEAD + def.frag + TAIL));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error('shaders.js: link failed for ' + name + ': ' + gl.getProgramInfoLog(p));
    const u = {}; ['uFlip', 'uA', 'uB', 'uU', 'uFrame', 'uSeed', 'uRes', 'uAspect', 'uAlpha', 'uP0', 'uP1', 'uP2', 'uEdge', 'uEdgeMode'].forEach(n => { u[n] = gl.getUniformLocation(p, n); });
    gl.useProgram(p); gl.uniform1i(u.uA, 0); gl.uniform1i(u.uB, 1);
    return (ctx.programs[name] = { p, u });
  }

  /* ---------- textures ---------- */
  function sourceSize(src) {
    if (src.kind === 'fbo' || src.tex) return [src.w, src.h];
    if (typeof HTMLVideoElement !== 'undefined' && src instanceof HTMLVideoElement) return [src.videoWidth, src.videoHeight];
    if (typeof HTMLImageElement !== 'undefined' && src instanceof HTMLImageElement) return [src.naturalWidth, src.naturalHeight];
    return [src.width, src.height];
  }
  function isStatic(src) { return (typeof HTMLImageElement !== 'undefined' && src instanceof HTMLImageElement) || (typeof ImageBitmap !== 'undefined' && src instanceof ImageBitmap); }
  /* upload or refresh a texture from a drawable source; <img>/ImageBitmap upload once, <canvas>/<video> every call */
  function texture(ctx, source, o) {
    o = o || {};
    if (!source) throw new Error('shaders.js: GL.texture needs a source');
    if (source.kind === 'fbo') return source;                                   // already on the GPU
    if (source.tex && source.w) return source;                                  // a texture object we made
    const gl = ctx.gl; const [w, h] = sourceSize(source);
    if (!(w > 0 && h > 0)) throw new Error('shaders.js: source has no pixels yet (decode the <img> / draw the <canvas> before GL.texture)');
    let rec = ctx.cache.get(source);
    // an <img> is uploaded once per PICTURE, not once per element: the footage lane's <img> changes src every frame of a
    // seq clip and keeps its size, so the cache must re-upload when currentSrc changes or a worker that enters the cut
    // window mid-clip would show the frame it happened to start on
    const src = isStatic(source) && 'currentSrc' in source ? (source.currentSrc || source.src || '') : null;
    const refresh = o.refresh !== undefined ? o.refresh : (!isStatic(source) || (rec && rec.picture !== src));
    if (rec && !refresh && rec.w === w && rec.h === h) return rec;
    if (!rec) {
      const tex = gl.createTexture(); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
      const wrap = o.wrap === 'mirror' ? gl.MIRRORED_REPEAT : gl.CLAMP_TO_EDGE, filt = o.filter === 'nearest' ? gl.NEAREST : gl.LINEAR;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filt); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filt);
      rec = { tex, w: 0, h: 0, kind: 'image', source, footage: isFootage(source), picture: null };
      ctx.cache.set(source, rec);
    } else { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, rec.tex); }
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, !!o.premultiply);
    if (rec.w === w && rec.h === h) gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, source);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    rec.w = w; rec.h = h; rec.picture = src;
    return rec;
  }
  function fboMake(ctx, w, h) {
    const gl = ctx.gl, tex = gl.createTexture(); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    const fb = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error('shaders.js: RGBA8 framebuffer incomplete');
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    const f = { fb, tex, w, h, kind: 'fbo' }; return f;
  }
  /* pick a scratch framebuffer (full or half resolution) that is not one of the inputs */
  function pickFbo(ctx, which, inputs) {
    const pool = which === 'half' ? ctx.half : ctx.fbos;
    const w = which === 'half' ? Math.ceil(ctx.W / 2) : ctx.W, h = which === 'half' ? Math.ceil(ctx.H / 2) : ctx.H;
    while (pool.length < 2) pool.push(fboMake(ctx, w, h));
    for (const f of pool) if (!inputs.some(i => i && i.tex === f.tex)) return f;
    pool.push(fboMake(ctx, w, h)); return pool[pool.length - 1];
  }
  function resolveTarget(ctx, target, inputs) {
    if (!target) return null;
    if (target === 'fbo') return pickFbo(ctx, 'full', inputs);
    if (target === 'half') return pickFbo(ctx, 'half', inputs);
    if (target.kind === 'fbo') return target;
    throw new Error('shaders.js: target must be undefined (canvas), "fbo", "half" or an FBO texture');
  }

  /* ---------- the one draw call ---------- */
  function draw(ctx, name, texA, texB, U, target) {
    if (ctx.lost) throw new Error('shaders.js: WebGL context lost');
    const gl = ctx.gl, pr = program(ctx, name), tgt = resolveTarget(ctx, target, [texA, texB]);
    const w = tgt ? tgt.w : ctx.W, h = tgt ? tgt.h : ctx.H;
    gl.bindFramebuffer(gl.FRAMEBUFFER, tgt ? tgt.fb : null); gl.viewport(0, 0, w, h);
    gl.useProgram(pr.p); gl.bindVertexArray(ctx.vao);
    gl.uniform1f(pr.u.uFlip, tgt ? 0 : 1);
    gl.uniform1f(pr.u.uU, U.u || 0); gl.uniform1f(pr.u.uFrame, U.frame || 0); gl.uniform1f(pr.u.uSeed, U.seed || 0);
    gl.uniform2f(pr.u.uRes, w, h); gl.uniform1f(pr.u.uAspect, w / h); gl.uniform1f(pr.u.uAlpha, ctx.alpha && !tgt ? 1 : 0);
    const P0 = U.P0 || [0, 0, 0, 0], P1 = U.P1 || [0, 0, 0, 0], P2 = U.P2 || [0, 0, 0, 0];
    gl.uniform4f(pr.u.uP0, P0[0] || 0, P0[1] || 0, P0[2] || 0, P0[3] || 0);
    gl.uniform4f(pr.u.uP1, P1[0] || 0, P1[1] || 0, P1[2] || 0, P1[3] || 0);
    gl.uniform4f(pr.u.uP2, P2[0] || 0, P2[1] || 0, P2[2] || 0, P2[3] || 0);
    const ec = U.edge || ctx.edgeColor; gl.uniform3f(pr.u.uEdge, ec[0], ec[1], ec[2]); gl.uniform1f(pr.u.uEdgeMode, U.fill === 'edge' ? 1 : 0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texA.tex);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, (texB || texA).tex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return tgt;
  }
  function packed(def, name, params) {
    const p = Object.assign({}, def.defaults, params || {});
    const U = def.pack ? def.pack(p) : {};
    U.seed = p.seed !== undefined ? p.seed : (hash(name) % 100000);
    U.fill = p.fill; if (p.edgeColor && p.fill === 'edge') U.edge = rgb(p.edgeColor);
    if (p.frame !== undefined) U.frame = p.frame;
    return U;
  }

  /* draw A→B at progress u in [0,1]; returns null (drawn on the canvas) or the FBO texture when params.target is set */
  function transition(ctx, name, texA, texB, u, params) {
    const def = TRANSITIONS[name]; if (!def) throw new Error('shaders.js: unknown transition "' + name + '" (' + Object.keys(TRANSITIONS).join(', ') + ')');
    params = params || {};
    const U = packed(def, name, params); U.u = clamp(u, 0, 1);
    const A = texture(ctx, texA), B = texture(ctx, texB);
    return draw(ctx, name, A, B, U, params.target);
  }
  /* finishing on a recreated layer; refuses the footage lane */
  function pass(ctx, name, tex, params) {
    const def = PASSES[name]; if (!def || name[0] === '_') throw new Error('shaders.js: unknown pass "' + name + '" (' + Object.keys(PASSES).filter(k => k[0] !== '_').join(', ') + ')');
    params = params || {};
    const A = texture(ctx, tex);
    if (A.footage && name !== 'copy') throw new Error('shaders.js: GL.pass("' + name + '") refused: the source is the footage lane. Finishing is for recreated layers only.');
    if (def.composite) return bloom(ctx, A, Object.assign({}, def.defaults, params));
    return draw(ctx, name, A, null, packed(def, name, params), params.target);
  }
  function bloom(ctx, A, p) {
    const bright = draw(ctx, '_bright', A, null, { P0: [p.threshold, p.knee, 0, 0] }, 'half');
    const h1 = draw(ctx, '_blur9', bright, null, { P0: [p.radius, 0, 0, 0] }, 'half');
    const h2 = draw(ctx, '_blur9', h1, null, { P0: [0, p.radius, 0, 0] }, 'half');
    return draw(ctx, '_bloomMix', A, h2, { P0: [p.amount, 0, 0, 0] }, p.target);
  }
  /* run several passes in order: [['vignette', {…}], ['grain', {frame}]] — intermediate results ping-pong through FBOs */
  function chain(ctx, tex, passes, target) {
    let cur = texture(ctx, tex), out = cur;
    for (let i = 0; i < passes.length; i++) {
      const [name, params] = passes[i]; const last = i === passes.length - 1;
      out = pass(ctx, name, cur, Object.assign({}, params || {}, { target: last ? target : 'fbo' }));
      if (!last) cur = out;
    }
    return out;                                                               // null when the last pass painted the canvas
  }

  /* ---------- cut transitions on the clock ---------- */
  /* GL.cutTransition(ctx, {at, dur, name, from:()=>src, to:()=>src, params, ease, passes, split}) → handle(t); a no-op
     outside [at, at+dur). `passes` (array, or a function (t, u) → array so grain can follow the frame index) finishes
     the composite — recreated cards only. Registered on ctx so GL.drive(ctx, t) can run every cut of the scene and
     keep the canvas hidden when none is active. Windows must not overlap.
     `split` = share of the window before the hidden step (every program steps at u = 0.5; the window's progress is
     remapped so that step lands at `split`): 0.5 for card <-> card. With the footage lane on one side the defaults
     change — dur 0.5 s (never more: the rule is enforced here, not only by lint), split FOOTAGE.split on the footage
     side (0.15 when from() is footage, 0.85 when to() is) — so product pixels sit under the effect for two frames. */
  const FOOTAGE = { maxDur: 0.5, split: 0.15 };
  function footageSide(o) {
    let a = null, b = null;
    try { a = o.from(); b = o.to(); } catch (e) { return null; }           // sources not mounted yet: the draw-time check below still applies
    return isFootage(a) ? 'from' : isFootage(b) ? 'to' : null;
  }
  function cutTransition(ctx, o) {
    if (!o || typeof o.from !== 'function' || typeof o.to !== 'function') throw new Error('shaders.js: cutTransition needs from() and to() thunks');
    const def = TRANSITIONS[o.name]; if (!def) throw new Error('shaders.js: unknown transition "' + o.name + '"');
    const side = footageSide(o);
    const at = +o.at, dur = o.dur !== undefined ? +o.dur : (side ? Math.min(def.dur, FOOTAGE.maxDur) : def.dur), ease = easeFn(o.ease);
    if (!(dur > 0)) throw new Error('shaders.js: cutTransition dur must be > 0');
    const overFootage = () => new Error('shaders.js: GL.cutTransition("' + o.name + '") dur ' + dur + ' s passes over the footage lane (max ' + FOOTAGE.maxDur + ' s) — shorten dur or put the ' + o.name + ' between recreated cards');
    if (side && dur > FOOTAGE.maxDur + 1e-9) throw overFootage();
    const split = o.split !== undefined ? +o.split : side === 'from' ? FOOTAGE.split : side === 'to' ? 1 - FOOTAGE.split : 0.5;
    if (!(split > 0 && split < 1)) throw new Error('shaders.js: cutTransition split must lie inside (0, 1)');
    for (const c of ctx.cuts) if (at < c.at + c.dur && c.at < at + dur) throw new Error('shaders.js: cut windows overlap (' + c.effect + ' @' + c.at + ' and ' + o.name + ' @' + at + ')');
    const h = function (t) {
      if (t < at || t >= at + dur) { if (h.active) { h.active = false; if (!o.keepVisible) show(ctx, false); } return { active: false, u: t < at ? 0 : 1 }; }
      const u0 = ease(clamp((t - at) / dur, 0, 1));
      const u = split === 0.5 ? u0 : (u0 < split ? 0.5 * u0 / split : 0.5 + 0.5 * (u0 - split) / (1 - split));   // the hidden step lands at `split`
      const A = texture(ctx, o.from()), B = texture(ctx, o.to());
      if ((A.footage || B.footage) && dur > FOOTAGE.maxDur + 1e-9) throw overFootage();                            // thunks that resolved late
      /* with `passes` the transition lands in an FBO and the finishing chain writes the canvas (recreated cards only) */
      const out = transition(ctx, o.name, A, B, u, Object.assign({}, o.params || {}, o.passes ? { target: 'fbo' } : {}));
      if (o.passes) { const ps = typeof o.passes === 'function' ? o.passes(t, u) : o.passes; chain(ctx, out, ps.map(p => Array.isArray(p) ? p : [p.name, p])); }
      show(ctx, true); h.active = true;
      return { active: true, u };
    };
    h.at = at; h.dur = dur; h.effect = o.name; h.active = false; h.window = [at, at + dur]; h.split = split; h.cutAt = at + split * dur; h.footage = side;
    ctx.cuts.push(h); ctx.cuts.sort((a, b) => a.at - b.at);
    return h;
  }
  /* run every registered cut for this t; returns the active handle or null */
  function drive(ctx, t) {
    let act = null;
    for (const h of ctx.cuts) { const r = h(t); if (r.active) act = h; }
    if (!act) show(ctx, false);
    return act;
  }

  /* ---------- drawable sources for recreated layers ---------- */
  /* a canvas at the stage size (× dpr) with the 2D context pre-scaled; draw(c2d, w, h) paints in stage px */
  function cardCanvas(ctx, o) {
    o = o || {};
    const dpr = o.dpr || (ctx && ctx.dpr) || 1, w = o.width || 1280, h = o.height || 720;
    const cv = (typeof document !== 'undefined') ? document.createElement('canvas') : new OffscreenCanvas(w * dpr, h * dpr);
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const c = cv.getContext('2d', { alpha: false }); c.scale(dpr, dpr);
    c.fillStyle = o.bg || '#082A34'; c.fillRect(0, 0, w, h);
    if (o.draw) o.draw(c, w, h);
    return cv;
  }
  /* the common card: a ground (flat or two-stop vertical gradient), a title, an optional rule and sub line */
  function textCard(ctx, o) {
    o = o || {};
    return cardCanvas(ctx, { width: o.width, height: o.height, dpr: o.dpr, bg: o.bg || '#082A34', draw: (c, w, h) => {
      if (o.bg2) { const g = c.createLinearGradient(0, 0, 0, h); g.addColorStop(0, o.bg || '#082A34'); g.addColorStop(1, o.bg2); c.fillStyle = g; c.fillRect(0, 0, w, h); }
      c.textAlign = 'center'; c.textBaseline = 'middle';
      const cy = o.y === undefined ? h / 2 : o.y;
      if (o.title) { c.fillStyle = o.color || '#E9F3F9'; c.font = o.font || '400 64px Georgia, serif'; c.fillText(o.title, w / 2, cy - (o.sub ? 22 : 0)); }
      if (o.rule !== false && o.title) { c.fillStyle = o.ruleColor || '#E56B5E'; c.fillRect(w / 2 - 45, cy + (o.sub ? 30 : 52), 90, 3); }
      if (o.sub) { c.fillStyle = o.subColor || '#ECDEC3'; c.font = o.subFont || '400 22px Arial, sans-serif'; c.fillText(o.sub, w / 2, cy + 64); }
      if (o.caption) { c.fillStyle = o.captionColor || '#81A9AB'; c.font = o.captionFont || '500 14px Arial, sans-serif'; c.fillText(o.caption.toUpperCase().split('').join(' '), w / 2, h - 60); }
      if (o.draw) o.draw(c, w, h);
    } });
  }
  /* hand back something GL.texture can read. Drawable elements pass through (or are copied to a stage-size
     canvas with {copy:true}); any other DOM element throws: the browser cannot rasterise a subtree synchronously,
     so recreated cards are drawn with GL.cardCanvas / GL.textCard, and footage is handed over as its <img>. */
  function snapshotToCanvas(el, o) {
    o = o || {};
    const drawable = typeof HTMLCanvasElement !== 'undefined' && (el instanceof HTMLCanvasElement || el instanceof HTMLImageElement || el instanceof HTMLVideoElement ||
      (typeof ImageBitmap !== 'undefined' && el instanceof ImageBitmap) || (typeof OffscreenCanvas !== 'undefined' && el instanceof OffscreenCanvas));
    if (!drawable) {
      if (el && el.dataset && el.dataset.glCanvas) { const c = document.getElementById(el.dataset.glCanvas); if (c) return snapshotToCanvas(c, o); }
      throw new Error('shaders.js: GL.snapshotToCanvas cannot rasterise a DOM subtree synchronously. Draw the card with GL.cardCanvas/GL.textCard, point data-gl-canvas at a canvas that mirrors it, or pass the footage <img> directly.');
    }
    if (!o.copy && !o.width) return el;
    const w = o.width || 1280, h = o.height || 720, dpr = o.dpr || 1;
    const cv = document.createElement('canvas'); cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const c = cv.getContext('2d', { alpha: false }); c.scale(dpr, dpr);
    const [sw, sh] = sourceSize(el); const s = o.fit === 'contain' ? Math.min(w / sw, h / sh) : Math.max(w / sw, h / sh);
    c.fillStyle = o.bg || '#082A34'; c.fillRect(0, 0, w, h);
    c.drawImage(el, (w - sw * s) / 2, (h - sh * s) / 2, sw * s, sh * s);
    return cv;
  }

  const DUR = {}; Object.keys(TRANSITIONS).forEach(k => { DUR[k] = TRANSITIONS[k].dur; });
  const DEFAULTS = {}; Object.keys(TRANSITIONS).forEach(k => { DEFAULTS[k] = Object.assign({}, TRANSITIONS[k].defaults); });
  Object.keys(PASSES).filter(k => k[0] !== '_').forEach(k => { DEFAULTS[k] = Object.assign({}, PASSES[k].defaults); });

  root.GL = { create, destroy, texture, transition, pass, chain, cutTransition, drive, show, cardCanvas, textCard, snapshotToCanvas,
    frameIndex, rgb, hash, EASES, DUR, DEFAULTS, FOOTAGE, TRANSITIONS: Object.keys(TRANSITIONS), PASSES: Object.keys(PASSES).filter(k => k[0] !== '_'), isFootage };
})(typeof window !== 'undefined' ? window : globalThis);
