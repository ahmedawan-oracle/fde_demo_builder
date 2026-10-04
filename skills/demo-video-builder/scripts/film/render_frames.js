#!/usr/bin/env node
/* render_frames.js — DETERMINISTIC frame-by-frame render of a clock-driven scene (no real-time capture, no dropped frames).
   node render_frames.js scenes/film.html out/seg_film.mp4 92.5 [fps=30] [jpegQuality=96] [workers=3]
   The frame range is split into `workers` contiguous chunks; each chunk runs in its own page: __seek(t0) once, then
   __step(t) per frame → page.screenshot(jpeg) → piped into its own ffmpeg (image2pipe → libx264 crf 17, yuv420p, CFR).
   Chunks are joined losslessly with the concat demuxer. Frame 0 == film clock 0.
   Scene contract: ?render · window.__seek(t) (full reset) · window.__step(t) (sequential, keeps caches). */
const puppeteer = require('puppeteer');
const { spawn, spawnSync } = require('child_process');
const path = require('path'); const fs = require('fs');
function chromePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) return process.env.PUPPETEER_EXECUTABLE_PATH;
  try { const p = puppeteer.executablePath(); if (fs.existsSync(p)) return p; } catch (e) {}
  return ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(fs.existsSync);
}
const argvAll = process.argv.slice(2);
const SHUTTER = (() => { const i = argvAll.indexOf('--shutter'); if (i >= 0) { const v = parseFloat(argvAll[i + 1]); argvAll.splice(i, 2); return isNaN(v) ? 240 : v; } return process.env.RENDER_SHUTTER ? parseFloat(process.env.RENDER_SHUTTER) : 0; })();
const [SCENE, OUT, DUR, FPS_S, Q_S, W_S] = argvAll;
if (!SCENE || !OUT || !DUR) { console.error('usage: node render_frames.js <scene.html[?q]> <out.mp4> <seconds> [fps] [jpegQuality] [workers]'); process.exit(1); }
const FPS = parseInt(FPS_S || '30', 10), Q = parseInt(Q_S || '96', 10), WORKERS = Math.max(1, parseInt(W_S || '3', 10));
const N = Math.round(parseFloat(DUR) * FPS);
const [sp, sq] = SCENE.split('?');
const URL = 'file://' + path.resolve(sp) + '?' + (sq ? sq + '&' : '') + 'render';
const outAbs = path.resolve(OUT); fs.mkdirSync(path.dirname(outAbs), { recursive: true });
const partName = k => outAbs.replace(/\.mp4$/i, `.part${k}.mp4`);

function ffmpegPipe(outFile) {
  return spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-vcodec', 'mjpeg', '-i', '-',
    '-vf', 'scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p', '-color_range', 'tv', '-r', String(FPS), '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-g', '30', outFile],
    { stdio: ['pipe', 'inherit', 'inherit'] });
}
/* motion blur by accumulation (v5.1, --shutter <deg>, default off). Only the frames inside a window where the camera (or the
   picture) was measured to move faster than 3 stage px per frame get k sub-frames spread over the shutter angle
   (240° = two thirds of the frame interval), each a real __seek of the scene, averaged in a canvas page with an ordered
   dither so the mean never rounds the same way twice. k is a pure function of the measured flow — k = min(48, 2·ceil(flow/3)) —
   so two renders accumulate the same sub-frames. Windows come from out/qa/camera_measured.json (gates/motion_diag.py), or
   RENDER_SHUTTER_WINDOWS=<json> [{t0, t1, flow}]. */
function shutterWindows() {
  if (!SHUTTER) return [];
  const wins = [];
  const envp = process.env.RENDER_SHUTTER_WINDOWS;
  try {
    if (envp && fs.existsSync(envp)) { for (const w of JSON.parse(fs.readFileSync(envp, 'utf8'))) wins.push({ t0: +w.t0, t1: +w.t1, flow: +w.flow }); return wins; }
    const mp = path.join(path.dirname(path.dirname(outAbs)), 'out', 'qa', 'camera_measured.json');
    if (!fs.existsSync(mp)) return wins;
    const M = JSON.parse(fs.readFileSync(mp, 'utf8')); const scale = 1280 / ((M.res && M.res[0]) || 320); const dt = 1 / (M.fps || 10);
    for (const sh of (M.shots || [])) for (const r of (sh.intervals || [])) {
      if (r.skip) continue;
      const flow = Math.hypot(r.dx || 0, r.dy || 0) * scale / (dt * FPS);       // stage px per output frame
      if (flow > 3) wins.push({ t0: r.t, t1: r.t + dt, flow });
    }
  } catch (e) { console.error('shutter windows unreadable: ' + e.message); }
  return wins;
}
const SHUTTER_WINS = shutterWindows();
const kFor = t => { let f = 0; for (const w of SHUTTER_WINS) if (t >= w.t0 - 1e-6 && t < w.t1 + 1e-6) f = Math.max(f, w.flow); return f > 3 ? Math.min(48, 2 * Math.ceil(f / 3)) : 1; };
let shutterFrames = 0;
async function accumulate(p, t, k) {
  // k sub-frames across the shutter angle (each a real __seek), averaged by ffmpeg's tmix in integer arithmetic — the same
  // inputs give the same mean, so the blurred frame is as deterministic as a plain one
  const span = (SHUTTER / 360) / FPS;
  const pngs = [];
  for (let j = 0; j < k; j++) {
    await p.evaluate(t => (window.__step || window.__seek)(t), t + span * j / k);
    await p.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    pngs.push(await p.screenshot({ type: 'png', clip: { x: 0, y: 0, width: 1280, height: 720 } }));
  }
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-f', 'image2pipe', '-vcodec', 'png', '-i', '-',
    '-vf', `tmix=frames=${k},select=eq(n\\,${k - 1})`, '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '2', '-'],
    { input: Buffer.concat(pngs), maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0 || !r.stdout || !r.stdout.length) throw new Error('shutter accumulate failed: ' + String(r.stderr || ''));
  return r.stdout;
}
async function renderChunk(browser, k, i0, i1, errs) {
  const p = await browser.newPage();
  p.on('pageerror', e => errs.push(`PAGEERROR[${k}] ` + e.message));
  await p.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1.5 });
  p.setDefaultNavigationTimeout(240000);
  await p.goto(URL, { waitUntil: 'load', timeout: 240000 });
  // glyph metrics must be final before frame 0: fonts.ready alone is not enough for @font-face src:local() faces,
  // whose first paint was measured to settle up to ~1 s later on a loaded machine. Load every declared face
  // explicitly, then seek and screenshot until two consecutive captures of frame i0 are byte-identical.
  await p.evaluate(async () => { await document.fonts.ready; const faces = []; document.fonts.forEach(f => faces.push(f)); await Promise.all(faces.map(f => f.load().catch(() => null))); });
  await new Promise(r => setTimeout(r, 300));
  await p.evaluate(t => { document.body.classList.remove('pre'); return window.__seek(t); }, i0 / FPS);
  for (let tries = 0, prev = null; tries < 8; tries++) {
    // the same two animation frames the per-frame path waits before its capture: with the compositor-sync flags a screenshot
    // asked for on an idle page can wait for a frame that is never scheduled (captureScreenshot timed out) — the rAF pair
    // schedules and commits one (v5.1)
    await p.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    const shot = await p.screenshot({ type: 'png', clip: { x: 0, y: 0, width: 1280, height: 720 } });
    const sig = require('crypto').createHash('md5').update(shot).digest('hex');
    if (sig === prev) break;
    prev = sig; await new Promise(r => setTimeout(r, 250));
    await p.evaluate(t => window.__seek(t), i0 / FPS);
    if (tries === 7) errs.push(`WARN[${k}] first frame did not settle after 8 captures (late font or image paint)`);
  }
  const ff = ffmpegPipe(partName(k));
  const write = buf => new Promise(res => { if (!ff.stdin.write(buf)) ff.stdin.once('drain', res); else res(); });
  const t0 = Date.now();
  for (let i = i0; i < i1; i++) {
    const t = i / FPS;
    if (i > i0) await p.evaluate(t => (window.__step || window.__seek)(t), t);   // awaits a returned decode Promise
    // two animation frames between the step and the capture: the step's DOM writes must be committed and ACTIVATED by the
    // compositor before the screenshot asks for a frame, or the capture can still show the previous frame's tiles (measured
    // on the Acme sample under load: a receipt pill lingering one frame past its exit, scrolled-page glyph edges, 98/1099
    // frames differing between two 3-worker renders; 0 with this wait). Costs ~2 x 16 ms per frame.
    await p.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    const ks = kFor(t);
    let buf;
    if (ks > 1) {
      buf = await accumulate(p, t, ks); shutterFrames++;
      await p.evaluate(t => (window.__step || window.__seek)(t), t);               // leave the scene on the frame's own time for the next step
    } else {
      buf = await p.screenshot({ type: 'jpeg', quality: Q, clip: { x: 0, y: 0, width: 1280, height: 720 } });
    }
    await write(buf);
    if ((i - i0) % 300 === 0) console.log(`[w${k}] frame ${i}/${N}  t=${t.toFixed(2)}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end();
  await new Promise((res, rej) => ff.on('close', c => c === 0 ? res() : rej(new Error('ffmpeg exit ' + c))));
  await p.close();
  return i1 - i0;
}
(async () => {
  const t0 = Date.now(); const errs = [];
  /* GL: software by default. A CPU rasteriser (SwiftShader behind ANGLE) gives WebGL2 for lib/shaders.js and lib/title3d.js
     with pixels that do not depend on the laptop's GPU or driver, and with the GPU process off a 1280×720 DOM screenshot
     measured 80 ms vs 157 ms on the Intel D3D11 path. RENDER_GL=hardware restores the machine's own GPU (faster for heavy
     three.js scenes, frames then differ between machines). */
  const GL_MODE = process.env.RENDER_GL === 'hardware' ? 'hardware' : 'software';
  const glArgs = GL_MODE === 'hardware' ? [] : ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--disable-gpu'];
  /* compositor sync: a layer whose scale changes every frame (a staged lane inside the camera, a PiP arriving) can be
     screenshotted while its tiles are still being re-rastered at the new scale, so two renders differ by a few glyph-edge
     pixels. These flags make every compositor stage finish before a frame is drawn and turn off deferred image raster.
     Measured on the staged-lane scene: 47/54 frames differed between two renders without them, 0/54 with them, same wall
     time (42 s vs 37 s). On by default; RENDER_COMPOSITOR_SYNC=0 disables them. */
  const syncArgs = process.env.RENDER_COMPOSITOR_SYNC === '0' ? [] : ['--run-all-compositor-stages-before-draw', '--disable-checker-imaging', '--disable-threaded-animation', '--disable-image-animation-resync'];
  // protocolTimeout: the first software-GL frame of a scene with a 3D title can take minutes on a loaded laptop; the default
  // 180 s turned a slow first capture into a dead render (v5.1)
  const launch = sync => puppeteer.launch({ headless: 'new', executablePath: chromePath(), protocolTimeout: 900000,
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1.5', '--window-size=1280,760', '--font-render-hinting=none', '--disable-lcd-text',
           '--force-color-profile=srgb', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--allow-file-access-from-files']
           .concat(glArgs, sync) }).catch(e => {
    if (/3221225595|0xC0000409|STATUS_STACK_BUFFER_OVERRUN/.test(String(e && e.message))) console.error('Chrome crashed at launch (0xC0000409): set PUPPETEER_EXECUTABLE_PATH to the system Chrome');
    throw e; });
  let b = await launch(syncArgs), compositorSync = syncArgs.length ? 'on' : 'off';
  /* capture probe (v5.1): on some Chrome builds the compositor-sync flags make Page.captureScreenshot wait forever for a frame
     that is never drawn (measured: a one-frame probe hung past 150 s with the flags, 2.3 s without, same scene, same machine).
     A render that can never capture is worse than one that may differ by a glyph edge, so a plain page is screenshotted once
     with a 30 s race; a hang kills that Chrome and relaunches without the flags. The receipt says which path was used. */
  if (syncArgs.length) {
    const probe = async () => { const p = await b.newPage(); await p.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1.5 });
      await p.goto('data:text/html,<body style="margin:0;background:%23082A34"><div style="width:200px;height:100px;background:%23fff"></div></body>');
      await p.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
      await p.screenshot({ type: 'png', clip: { x: 0, y: 0, width: 64, height: 64 } }); await p.close(); return true; };
    const ok = await Promise.race([probe().catch(() => false), new Promise(r => setTimeout(() => r(false), 30000))]);
    if (!ok) {
      console.error('WARN compositor-sync flags hang Page.captureScreenshot on this Chrome — relaunching without them (RENDER_COMPOSITOR_SYNC=0 behaviour); the determinism canary should be read with this in mind');
      try { b.process() && b.process().kill('SIGKILL'); } catch (e) {}
      b = await launch([]); compositorSync = 'off (fallback: capture hung with the sync flags)';
    }
  }
  const chromeVersion = await b.version();
  // the GL renderer string goes into the render receipt so the gl canary can prove two renders used the same rasteriser
  const glRenderer = await (async () => { const p = await b.newPage(); const r = await p.evaluate(() => { const g = document.createElement('canvas').getContext('webgl2'); if (!g) return 'no webgl2';
    const d = g.getExtension('WEBGL_debug_renderer_info'); return d ? g.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'webgl2'; }).catch(() => 'probe failed'); await p.close(); return r; })();
  const bounds = []; for (let k = 0; k < WORKERS; k++) bounds.push([Math.round(k * N / WORKERS), Math.round((k + 1) * N / WORKERS)]);
  const counts = await Promise.all(bounds.map(([i0, i1], k) => renderChunk(b, k, i0, i1, errs)));
  await b.close();
  const list = path.join(path.dirname(outAbs), 'concat_parts.txt');
  // each part's `duration` is stated exactly (frames / FPS): the concat demuxer otherwise offsets the next part by the
  // mp4 header's millisecond-rounded duration (100 frames -> 3.333 s, 5 ticks short), so every chunk boundary slid the
  // remaining timestamps 0.33 ms early and the joined file was no longer exactly CFR (avg_frame_rate 30.0019)
  fs.writeFileSync(list, bounds.map(([i0, i1], k) => `file '${partName(k).replace(/\\/g, '/').replace(/'/g, "'\\''")}'\nduration ${((i1 - i0) / FPS).toFixed(6)}`).join('\n') + '\n');
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', outAbs], { stdio: 'inherit' });
  if (r.status !== 0) { console.error('concat failed'); process.exit(3); }
  bounds.forEach((_, k) => { try { fs.unlinkSync(partName(k)); } catch (e) {} }); try { fs.unlinkSync(list); } catch (e) {}
  const nb = spawnSync('ffprobe', ['-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', outAbs], { encoding: 'utf8' }).stdout.trim();
  console.log(JSON.stringify({ out: OUT, frames: N, rendered: counts.reduce((a, c) => a + c, 0), probed: nb, fps: FPS, seconds: N / FPS, workers: WORKERS, chrome: chromeVersion, gl: GL_MODE, gl_renderer: glRenderer, compositor_sync: compositorSync, shutter: SHUTTER ? { deg: SHUTTER, windows: SHUTTER_WINS.length, frames_accumulated: shutterFrames } : null, errors: errs, wall_s: Math.round((Date.now() - t0) / 1000) }));
  if (errs.length) { console.error(errs.join('\n')); process.exit(2); }
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
