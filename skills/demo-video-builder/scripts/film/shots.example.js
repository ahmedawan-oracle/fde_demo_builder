/* shots.example.js — the edit for film.example.html (fictional Acme sample, v5). Loaded after timeline.js.

   Write every framing in the view you think in (the page band, or a crop of the screen) — then
   FOOT.fullscreen() maps it onto the ORIGINAL full product screen. A shot with `establish` opens on the
   whole screen, holds, and pushes into that framing: viewers see where they are before they see detail.
   Every t0 is a spoken word: wt(phase, word). node check_cues.js fails if any cue doesn't resolve.
   Camera rules (references/camera-moves.md): pushes 1.0–2.0 s, dwell ≥ 1 s between moves, never above
   2× the recording's pixels (node scenes/lib/camera.js --curves … prints the pose ladder and the budget).

   v5.1: FILM.holds declares the hold window of each recreated segment (fraction of the segment after which only the
         background may move); a footage shot that ends on a held state carries `hold:` itself; a shot that plays a
         window of a seq clip can take its play{} numbers from tools/cutlist.py (scenes/cutlist_data.js → CUTLIST.<clip>).
   v5 additions in this file
     FILM.dive      the opener reveal's receipt (REVEAL.plan, pure arithmetic, same in node and the browser):
                    the first still dives onto the staged notebook window and the lane takes over on dive.end
     FILM.openEnd   = dive.at — the title card cuts out as the plate appears (seams.json: a match-cut row)
     staged: true   the one footage beat that keeps the window bezel + wallpaper (lib/stage.js); the others
                    open on the whole screen and zoom, as before
     FILM.stage / FILM.marks / FILM.receipt / FILM.hook* / FILM.close*   the copy and geometry the scene draws
   Craft decisions (the sample's review): the question beat stays on the whole screen for the typing and pushes
   only ×1.15 onto the chat column (thread + composer) — a deep push onto a bottom-edge composer left most of the
   frame as dimmed nothing; the notebook push lands the boxed output row in the upper-middle third with blank page
   beside it for the call-out; lower thirds are short, carry no stripe, and sit above the caption lane. */
(function (root) {
  const T = root.TX, P = T.P, wt = T.wt, R = root.FOOT.REVEAL;
  const RV = root.REVEAL || (typeof require === 'function' ? require('./lib/reveals.js') : null);

  // the opener: a heroDive of the notebook's first still lands on "notebook"; the lane starts on the frame it ends
  const DIVE = RV.plan({ kind: 'heroDive', land: wt('nb', 'notebook') });
  /* the opener reveal rides into out/timeline.json so reveal_gate measures its hand-over (a planned reveal with no ledger row
     would let the three reveal gates pass without looking) */
  const STAGE_OPTS = { wallpaper: 'mesh', padding: 64, bezel: 'window', title: 'Acme Console' };
  if (typeof global !== 'undefined') {
    // target = the staged footage rect in stage px (lib/stage.js geometry of the same options the scene mounts with), so
    // reveal_gate can render the clip's own still into it and compare with the hand-over frame
    const SG = root.STAGE || (typeof require === 'function' ? require('./lib/stage.js') : null);
    const fr = SG ? SG.geometry(STAGE_OPTS).footage : { x: 0, y: 0, w: 1280, h: 720 };
    global.__ledgers = global.__ledgers || {};
    global.__ledgers.reveals = [Object.assign({ id: 'open', kind: 'heroDive', clip: 'nb' }, DIVE, { target: [+fr.x.toFixed(2), +fr.y.toFixed(2), +fr.w.toFixed(2), +fr.h.toFixed(2)] })];
  }

  // the typed question: line box + word ends measured with `extract_clips.py --word-ends`
  const RVQ = { lines: [[522, 982, 991, 1012]], sync: 'ask', tailPxs: 260, bg: '#ffffff',
    ends: [572, 632, 691, 730, 791, 854, 902, 935, 988] };
  // the send lands on the word "send"; the typed line is complete 1.4 s earlier, so the air reads as a breath
  const SEND = Math.max(R.end(RVQ, T) + 0.2, P.answer + 0.1);
  // the real send frames (clip 'send', 52 frames from 15.05 s) run until the answer card has settled; the still takes over
  const ANSWER_AT = SEND + 0.45 + 1.75;

  root.FILM = {
    dive: DIVE,
    openEnd: DIVE.at,                       // recreated title card until the plate appears
    close: P.close,                         // recreated closing card from here
    send: SEND,
    title: 'Monday, answered.',
    heroWord: 'answered',
    subtitle: 'From an analyst’s notebook to a question anyone can ask',
    caption: 'Fictional company · synthetic data',
    hookKicker: 'Every Monday',
    hookQuestion: 'Which regions missed the on-time target last week?',   // the old way: a colleague, a day later
    hookReply: 'On it. I will have it by tomorrow.',
    hookLabel: 'recreated · fictional',
    closeKicker: 'One notebook · One question',
    closeTitle: 'One answer the whole team can trust.',
    closeSub: 'Monday, answered.',
    receipt: ['grounded in the notebook', 'same governed data', 'traceable'],
    kpiLabel: 'regions over target',
    kpiSub: 'Part 3 · synthetic data',
    kpiRect: { x: 820, y: 236, w: 340, h: 136 },   // stage px: the call-out sits on blank page beside the boxed output row, never on code or prose
    stage: STAGE_OPTS,
    // move first, then hold (gates/hold_gate.py): the recreated segments' hold windows. The close card is complete by the
    // end of the narration and holds through the tail while the credit lands; the hook and the title waive theirs in the
    // storyboard (every element lands on its spoken word up to the cut). Footage shots declare `hold:` per shot instead.
    holds: [ { id: 'close', t0: P.close, t1: T.total + 3.6, hold: 0.55, bg: 1.0 } ],
    // footage-space rects (source px of the 1920x1080 recording) the hand-drawn layer points at
    marks: { composer: { x: 500, y: 960, w: 1360, h: 80 }, send: { x: 1738, y: 972, w: 104, h: 56 },
             figure: { x: 548, y: 460, w: 36, h: 47 } },            // == claims.json figures[0].rect
    // lower thirds (OVL.lowerThird): bottom in 1080 px — above the caption lane, so the lane never lifts onto product text;
    // the question beat's is a 2 s hand-off (one voice owns the hero line, the typed question is its own caption)
    acts: [ { label: 'THE ANALYST', text: 'Build it where the data is.', t0: DIVE.end, phase: 'nb', bottom: 260 },   // 260: clear of the caption lane (200 collided with the first notebook caption for 0.5 s)
            { label: 'THE OPERATIONS LEAD', text: 'Ask it where the work is.', t0: P.ask, dur: 2.0, phase: 'ask', bottom: 260 } ]
  };

  // the views the edit below is written in: [x, y, width] of the source rect (1920x1080 recording)
  const VIEW = { nb: [480, 150, 1400], q: [0, 0, 1920], send: [0, 0, 1920], answer: [0, 0, 1920] };

  root.SHOTS = root.FOOT.fullscreen([
    // the notebook keeps its window (staged): a gentle push into the page, two real scrolls, then onto the Part 3 output
    { t0: DIVE.end, t1: P.ask, clip: 'nb', seam: true, staged: true, y0: 0, s0: 0.875, c0: [640, 360], establish: { hold: 0.9, dur: 1.2 },
      scroll: [ { t0: wt('nb', 'filters') - 0.3, dur: 1.1, y: 760 },
                { t0: wt('nb', 'counts') - 0.3, dur: 1.1, y: 1380 } ],
      // lands as "Three" is spoken: the boxed output row in the upper-middle third, blank page to its right for the call-out
      moves: [ { t0: wt('nb', 'region') - 0.2, dur: 1.0, s: 1.15, c: [600, 330], ease: 'io' } ] },

    // the question beat: the whole screen for the typing, then a ×1.15 push onto the chat column (thread above, composer below)
    { t0: P.ask, t1: SEND, clip: 'q', reveal: RVQ, s0: 1.0, c0: [640, 360],
      moves: [ { t0: P.ask + 0.5, dur: 1.0, s: 1.15, c: [720, 400], ease: 'out' } ] },
    // the comma: 0.45 s between the last typed word and the send, so the result reads as caused (same pose as the typing ends on)
    { t0: SEND, t1: ANSWER_AT, clip: 'send', play: { at: SEND + 0.45 }, s0: 1.15, c0: [720, 400], seam: true,
      moves: [ { t0: SEND + 0.5, dur: 0.8, s: 1.0, c: [640, 360], ease: 'io', abs: true } ] },      // back to the whole screen, then hold
    // the answer card, held on the whole screen: the hand-drawn circle lands on its figure, the light leak takes it to the close
    // the shot's own contract (gates/spec_gate.py): words that may never show on its frames, the figure it must trace, the study it borrows from
    { t0: ANSWER_AT, t1: P.close, clip: 'answer', s0: 1.0, c0: [640, 360], seam: true,
      spec: { forbidden: ['TODO', 'lorem', 'placeholder'], claims: ['regions_over_target'], references: [] } }
  ], VIEW);

  // highlights in DOC px (pages) or source px (stills), keyed to a spoken word
  root.HL = {
    nb: [ { id: 'late', kind: 'box', r: [16, 1612, 520, 30], cue: ['nb', 'Three'], dt: 0 } ]   // Part 3 output row
  };
})(typeof window !== 'undefined' ? window : globalThis);
