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
const [SCENE, OUT, DUR, FPS_S, Q_S, W_S] = process.argv.slice(2);
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
async function renderChunk(browser, k, i0, i1, errs) {
  const p = await browser.newPage();
  p.on('pageerror', e => errs.push(`PAGEERROR[${k}] ` + e.message));
  await p.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1.5 });
  p.setDefaultNavigationTimeout(240000);
  await p.goto(URL, { waitUntil: 'load', timeout: 240000 });
  await new Promise(r => setTimeout(r, 1200));
  await p.evaluate(t => { document.body.classList.remove('pre'); return window.__seek(t); }, i0 / FPS);
  const ff = ffmpegPipe(partName(k));
  const write = buf => new Promise(res => { if (!ff.stdin.write(buf)) ff.stdin.once('drain', res); else res(); });
  const t0 = Date.now();
  for (let i = i0; i < i1; i++) {
    const t = i / FPS;
    if (i > i0) await p.evaluate(t => (window.__step || window.__seek)(t), t);   // awaits a returned decode Promise
    const buf = await p.screenshot({ type: 'jpeg', quality: Q, clip: { x: 0, y: 0, width: 1280, height: 720 } });
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
  const b = await puppeteer.launch({ headless: 'new', executablePath: chromePath(),
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1.5', '--window-size=1280,760', '--font-render-hinting=none', '--disable-lcd-text'] });
  const bounds = []; for (let k = 0; k < WORKERS; k++) bounds.push([Math.round(k * N / WORKERS), Math.round((k + 1) * N / WORKERS)]);
  const counts = await Promise.all(bounds.map(([i0, i1], k) => renderChunk(b, k, i0, i1, errs)));
  await b.close();
  const list = path.join(path.dirname(outAbs), 'concat_parts.txt');
  fs.writeFileSync(list, bounds.map((_, k) => `file '${partName(k).replace(/\\/g, '/').replace(/'/g, "'\\''")}'`).join('\n') + '\n');
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', outAbs], { stdio: 'inherit' });
  if (r.status !== 0) { console.error('concat failed'); process.exit(3); }
  bounds.forEach((_, k) => { try { fs.unlinkSync(partName(k)); } catch (e) {} }); try { fs.unlinkSync(list); } catch (e) {}
  const nb = spawnSync('ffprobe', ['-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', outAbs], { encoding: 'utf8' }).stdout.trim();
  console.log(JSON.stringify({ out: OUT, frames: N, rendered: counts.reduce((a, c) => a + c, 0), probed: nb, fps: FPS, seconds: N / FPS, workers: WORKERS, errors: errs, wall_s: Math.round((Date.now() - t0) / 1000) }));
  if (errs.length) { console.error(errs.join('\n')); process.exit(2); }
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
