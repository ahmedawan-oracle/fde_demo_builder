# -*- coding: utf-8 -*-
"""captions_srt.py — sidecar captions (SRT + WebVTT) from the SAME groups the burned-in lane draws.

    node scenes/lib/captions.js scenes/timing_film_data.js scenes/captions.json      # -> out/caption_groups.json
    python tools/captions_srt.py out/caption_groups.json out/<film>.srt [--vtt out/<film>.vtt] [--all]
    python tools/captions_srt.py --selftest

The lane (lib/captions.js) groups WORDS into ≤ 2-line captions with exact in/out windows; this tool only
serialises those groups, so the sidecar can never disagree with the picture. By default dropped groups are
omitted and the embed (big centred) groups are kept as plain cues; --all writes every group regardless of fate.
Cue text = the lane's own line breaks (group.lines). Cues never overlap (gate 13 'captions' orders them) and the
last cue is clamped to the film length (`end` in the groups file = narration + tail).
"""
import json, os, sys


def ts_srt(x):
    x = max(0.0, float(x)); ms = int(round(x * 1000))
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms % 3600000 // 60000, ms % 60000 // 1000, ms % 1000)


def ts_vtt(x):
    return ts_srt(x).replace(',', '.')


def cues(groups_doc, include_all=False):
    """[(start, end, text)] from a caption_groups.json document; monotonic, non-overlapping, clamped."""
    end_film = float(groups_doc.get('end') or groups_doc.get('total') or 1e9)
    out, prev_end = [], 0.0
    for g in groups_doc['groups']:
        if g.get('fate') == 'drop' and not include_all:
            continue
        a, b = float(g['in']), float(g['out'])
        a = max(a, prev_end)
        b = min(b, end_film)
        if b - a < 0.05:
            continue
        text = '\n'.join(g.get('lines') or [g.get('text', '')])
        out.append((round(a, 3), round(b, 3), text))
        prev_end = b
    return out


def write_srt(cs, path):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join('%d\n%s --> %s\n%s\n' % (i + 1, ts_srt(a), ts_srt(b), t) for i, (a, b, t) in enumerate(cs)))


def write_vtt(cs, path):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('WEBVTT\n\n' + '\n'.join('%d\n%s --> %s\n%s\n' % (i + 1, ts_vtt(a), ts_vtt(b), t) for i, (a, b, t) in enumerate(cs)))


def parse_srt(text):
    """[(start, end)] from SRT text — used by the QA gate to assert cues == groups."""
    import re
    ts = re.findall(r'(\d\d):(\d\d):(\d\d)[,.](\d\d\d) --> (\d\d):(\d\d):(\d\d)[,.](\d\d\d)', text)
    return [(int(a) * 3600 + int(b) * 60 + int(c) + int(d) / 1000.0, int(e) * 3600 + int(f) * 60 + int(g) + int(h) / 1000.0)
            for a, b, c, d, e, f, g, h in ts]


def selftest():
    doc = {'total': 10.0, 'end': 11.2, 'groups': [
        {'id': 'cg-0', 'fate': 'rail', 'in': 0.02, 'out': 2.6, 'lines': ['Every Monday, the', 'operations lead asks.']},
        {'id': 'cg-1', 'fate': 'drop', 'in': 2.62, 'out': 4.0, 'lines': ['Acme is fictional.']},
        {'id': 'cg-2', 'fate': 'embed', 'in': 4.02, 'out': 6.0, 'lines': ['ONE ANSWER.']},
        {'id': 'cg-3', 'fate': 'rail', 'in': 5.9, 'out': 20.0, 'lines': ['overlapping and too long']},
    ]}
    cs = cues(doc)
    assert len(cs) == 3, cs
    assert cs[1][2] == 'ONE ANSWER.'
    assert cs[2][0] == 6.0 and cs[2][1] == 11.2, cs[2]                       # clamped to the previous end and the film end
    assert ts_srt(3661.5) == '01:01:01,500' and ts_vtt(0.0415) == '00:00:00.042'
    import tempfile
    d = tempfile.mkdtemp()
    write_srt(cs, os.path.join(d, 't.srt')); write_vtt(cs, os.path.join(d, 't.vtt'))
    back = parse_srt(open(os.path.join(d, 't.srt'), encoding='utf-8').read())
    assert [(round(a, 3), round(b, 3)) for a, b in back] == [(a, b) for a, b, _ in cs], back
    vtt = open(os.path.join(d, 't.vtt'), encoding='utf-8').read()
    assert vtt.startswith('WEBVTT\n\n1\n00:00:00.020 --> 00:00:02.600\nEvery Monday, the\noperations lead asks.'), vtt[:120]
    assert len(cues(doc, include_all=True)) == 4
    print('captions_srt selftest OK: %d cues, srt/vtt round-trip, clamp + drop + --all' % len(cs))


if __name__ == '__main__':
    argv = sys.argv[1:]
    if '--selftest' in argv:
        selftest(); sys.exit(0)
    if len(argv) < 2:
        raise SystemExit(__doc__)
    doc = json.load(open(argv[0], encoding='utf-8'))
    cs = cues(doc, include_all='--all' in argv)
    write_srt(cs, argv[1])
    if '--vtt' in argv:
        write_vtt(cs, argv[argv.index('--vtt') + 1])
    print('captions: %d cues -> %s%s' % (len(cs), argv[1], (' + ' + argv[argv.index('--vtt') + 1]) if '--vtt' in argv else ''))
