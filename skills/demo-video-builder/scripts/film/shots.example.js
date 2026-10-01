/* shots.example.js — the edit for film.example.html (fictional Acme sample). Loaded after timeline.js.

   Write every framing in the view you think in (the page band, or a crop of the screen) — then
   FOOT.fullscreen() maps it onto the ORIGINAL full product screen. A shot with `establish` opens on the
   whole screen, holds, and pushes into that framing: viewers see where they are before they see detail.
   Every t0 is a spoken word: wt(phase, word). node check_cues.js fails if any cue doesn't resolve.
   Camera rules (references/camera-moves.md): pushes 1.0–2.0 s, dwell ≥ 1 s between moves, never above
   2× the recording's pixels (node scenes/lib/camera.js --curves … prints the pose ladder and the budget). */
(function (root) {
  const T = root.TX, P = T.P, wt = T.wt, R = root.FOOT.REVEAL;

  root.FILM = {
    openEnd: P.nb,                          // recreated title card until the notebook
    close: P.close,                         // recreated closing card from here
    title: 'Monday, answered.',
    subtitle: 'From an analyst’s notebook to a question anyone can ask',
    caption: 'Fictional company · synthetic data',
    closeLines: ['One notebook.', 'One question.', 'One answer the whole team can trust.'],
    acts: [ { label: 'THE ANALYST', text: 'Build it where the data is.', t0: P.nb, phase: 'nb' },
            { label: 'THE OPERATIONS LEAD', text: 'Ask it where the work is.', t0: P.ask, phase: 'ask' } ]
  };

  // the typed question: line box + word ends measured with `extract_clips.py --word-ends`
  const RVQ = { lines: [[522, 982, 991, 1012]], sync: 'ask', tailPxs: 260, bg: '#ffffff',
    ends: [572, 632, 691, 730, 791, 854, 902, 935, 988] };
  const SEND = Math.max(R.end(RVQ, T) + 0.2, P.answer + 0.1);

  // the views the edit below is written in: [x, y, width] of the source rect (1920x1080 recording)
  const VIEW = { nb: [480, 150, 1400], q: [420, 700, 1320], send: [420, 700, 1320] };

  root.SHOTS = root.FOOT.fullscreen([
    { t0: P.nb, t1: P.ask, clip: 'nb', y0: 0, s0: 1.0, c0: [640, 360], establish: { hold: 0.9, dur: 1.2 },
      scroll: [ { t0: wt('nb', 'filters') - 0.3, dur: 1.1, y: 760 },
                { t0: wt('nb', 'counts') - 0.3, dur: 1.1, y: 1520 } ],
      moves: [ { t0: wt('nb', 'counts') + 0.6, dur: 1.0, s: 1.15, c: [520, 300], ease: 'io' } ] },   // 1.15 / 0.729 = 1.58× upsample, under the 1.6 warn

    { t0: P.ask, t1: SEND, clip: 'q', reveal: RVQ, s0: 1.0, c0: [640, 420], establish: { hold: 0.5, dur: 1.0 } },
    // the comma: 0.45 s between the last typed word and the send, so the result reads as caused
    { t0: SEND, t1: T.P.close, clip: 'send', play: { at: SEND + 0.45 }, s0: 1.0, c0: [640, 420], seam: true,
      moves: [ { t0: SEND + 0.5, dur: 0.8, s: 1.0, c: [640, 360], ease: 'io', abs: true },        // back to the whole screen, then ≥ 1 s dwell
               { t0: wt('answer', 'governed') - 0.4, dur: 1.2, s: 1.6, c: [940, 225], ease: 'io', abs: true } ] }   // onto the sent message
  ], VIEW);

  // highlights in DOC px (pages) or source px (stills), keyed to a spoken word
  root.HL = {
    nb: [ { id: 'late', kind: 'box', r: [16, 1612, 520, 30], cue: ['nb', 'counts'], dt: 1.0 } ]   // Part 3 output
  };
})(typeof window !== 'undefined' ? window : globalThis);
