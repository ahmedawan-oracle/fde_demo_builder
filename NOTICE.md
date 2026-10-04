# Notices

fde_demo_builder is released under the MIT License (see LICENSE). The code, the measured rules, the shaders,
the synthesized sounds, the skins and the documentation in this repository are original work by Ahmed Awan
and the contributors to this repository.

## Third-party libraries

The plugin uses the libraries below, each under its own licence. None of their source is vendored here: the
scaffold installs the JavaScript packages into a project's `node_modules`, Python packages come from pip, and
ffmpeg is an external binary on PATH. Check the LICENSE file shipped with the installed version before
redistributing a build.

| Library | Used for | Licence |
|---|---|---|
| gsap | timelines mounted on the film clock (`lib/motion.js` and every lib built on it) | GSAP standard licence (no charge; keep its notice) |
| three | 3D titles (`lib/title3d.js`) | MIT |
| d3-delaunay | Voronoi shard geometry for the 3D titles | ISC |
| puppeteer | headless Chrome for the deterministic frame render, studio taps and gates | Apache License 2.0 |
| puppeteer-screen-recorder (optional, v1/v2 bookends only) | real-time capture of the animated opener/outro in `scripts/render_bookend.js` / `render_scene.js`; the v3+ film render does not use it | MIT |
| numpy | audio analysis, cursor tracking, idle detection, brand kit colour maths, gates | BSD-3-Clause |
| scipy | filters for the synthesized SFX and bus chains, the account-badge detector, cursor tracking | BSD-3-Clause |
| Pillow | frames, contact sheets, style sheets, review-pack thumbnails, the mandatory credit stamp | MIT-CMU (HPND) |
| scikit-learn (optional) | cross-check engine for the brand kit's colour clustering (`BRAND_KIT_ENGINE=sklearn`) | BSD-3-Clause |
| winocr (optional, Windows) | OCR engine for the leak gate (the OS text recogniser) | MIT |
| rapidocr-onnxruntime + onnxruntime + opencv-python-headless (optional) | OCR engine for the leak gate on other platforms | Apache License 2.0 / MIT / Apache License 2.0 |
| edge-tts | narration synthesis, invoked as a separate process (`python -m edge_tts`); optional at render time | GPL-3.0 |
| faster-whisper (optional) | word-timestamp alignment for the v1/v2 bookends | MIT |
| ffmpeg / ffprobe | encode, mix, loudness measurement, libass burn-in (external binary, not bundled) | LGPL-2.1+ / GPL-2.0+ depending on the build |

Fonts, music beds and product recordings that go into a film are the project's own assets; their rights are
recorded per asset in that project's media ledger (`tools/ledger.py`), never in this file. Fonts named by the
skins are faces that ship with the operating system and are never copied into this repository.
