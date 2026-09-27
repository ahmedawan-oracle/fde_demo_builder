/* timeline.js — the narration is the clock. Builds TX from the timing that gen_vo_multivoice.py emits:
     TX.P[phase]            phase start (s);  TX.P[phase + '_end']
     TX.wt(phase, word, n)  the moment the n-th occurrence of `word` is spoken in `phase` (falls back to the
                            phase start — check_cues.js fails the build if any cue falls back)
   Browser: reads window.PHASES / window.WORDS (scenes/timing_<name>.js).
   Node:    TL.load('scenes/timing_<name>_data.js'). */
(function (root) {
  'use strict';
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  function build(PH, WD) {
    const P = {}; PH.phases.forEach(p => { P[p.name] = p.start; P[p.name + '_end'] = p.start + p.dur; });
    function wt(phase, word, n) {
      const list = WD[phase] || [], want = norm(word); let k = 0;
      for (const x of list) if (norm(x.w) === want && ++k === (n || 1)) return P[phase] + x.t;
      return P[phase];
    }
    return { PHASES: PH, WORDS: WD, P: P, wt: wt, total: PH.total, norm: norm };
  }
  const TL = { build: build, load: f => { const d = require(require('path').resolve(f)); return build(d.PHASES, d.WORDS); } };
  if (typeof module !== 'undefined' && module.exports) module.exports = TL;          // node (build / QA tools)
  if (typeof window !== 'undefined') { root.TL = TL; if (window.PHASES) root.TX = build(window.PHASES, window.WORDS); }
})(typeof window !== 'undefined' ? window : globalThis);
