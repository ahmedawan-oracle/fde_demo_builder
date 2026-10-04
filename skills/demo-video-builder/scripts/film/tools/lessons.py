# -*- coding: utf-8 -*-
"""lessons.py — the one lesson each step of the flow was built on, printed at that step.

    python tools/lessons.py <step>          brief | references | look | storyboard | sketch | lock | cutlist | seams | narration |
                                            footage | scene | build | qa | pairs | review | notes | export
    python tools/lessons.py --all | --md    every step (--md: the table SKILL.md carries)
    python tools/lessons.py --selftest

build_film.py prints the lesson of a stage under its header; the flow commands in commands/new-film.md name the step. The
text is ours, from our own builds; a lesson is one sentence of cause, one of consequence, and it changes only when a build
teaches us otherwise. `manual` lists what each step leaves to a person on purpose — the decisions no gate makes.
"""
import json, sys

LESSONS = {
    'brief':      ('A brief that infers an answer has not asked the question.', 'One field per message, the recommended option first with its receipt; stated and inferred as two groups.', 'the message, the audience, what is real'),
    'references': ('A reference logged as what it shows gets copied; logged as how it is cut it gets learned.', 'Shot length, camera, lighting, cut — never logos, taglines or quoted copy; the report turns them into bands the plan is checked against.', 'which five to ten films, and which bands to keep'),
    'look':       ('One look for every shot flattens the film; a look per shot type lets a title spend what a product frame may not.', 'Product as recorded, cards in the house identity, titles allowed their effect, people never glitched; the gate reads CSS and effect calls per type.', 'the skin, the four tones, the per-type forbid lists'),
    'storyboard': ('A beat that has not written its last frame has not decided where it stops moving.', 'start: and end: in one sentence each, end: mandatory on recreated beats; hold: says when only the background may move; the arithmetic must add up to the narration.', 'beat order, the hero prop, the breather, every end: sentence'),
    'sketch':     ('A storyboard read on a phone gets comments; one read in a repo gets approval.', 'sheet --mobile, one column, tap to zoom; every comment at this stage costs a sentence, after a render it costs a render.', 'which cells change'),
    'lock':       ('Building before the lock means rebuilding after it.', 'check --build refuses without ## Locked (--autonomous waives it for a drive-it run) and, once approvals exist, without every END frame approved.', 'the sign-off itself'),
    'cutlist':    ('A footage shot trimmed to its slot loses its end state; one sped to its slot keeps it.', 'The text list (clip, length, start, speed, reverse) opens where the product does something, speeds a long clip up to 1.6x, holds a short one; --check-length fails a list that does not add up.', 'start, speed and direction of every clip'),
    'seams':      ('A cut lands mid-motion on both sides, or it reads as a slide.', 'seams.json before the shots: one current, reserved vectors spent once per act, at most one gl accent per act, never between two product screens; recreated beats move first and then hold.', 'the current, the one reserved vector, the accent'),
    'narration':  ('The narration is the clock; everything else is a function of it.', 'Word times drive every cut, move, caption and sound; a VO regen moves every cut and re-opens every seam — re-run the gates.', 'the words, the pauses, the voices'),
    'footage':    ('Every product frame comes from the recording; a redrawn one is a fabrication.', 'Median stills, stitched pages in the app\'s own chrome, real 30 fps seqs, small soft blurs for privacy, the original full screen before any zoom.', 'what to show, what to blur, where to push'),
    'scene':      ('Every visual is a pure function of t, or two renders differ.', 'No wall clock, no CSS transitions, no unseeded random, no will-change; libraries from node_modules by relative path; devices by moment, gates as footnotes.', 'which device carries each moment'),
    'build':      ('A render that cannot be reproduced cannot be reviewed.', 'Software GL, compositor settle, exact CFR join, the capture-probe fallback when Chrome hangs; every build is a take with its wall time, scene hash and gates.', 'the take to keep'),
    'qa':         ('A broken gate is a failed gate, never a skipped one.', 'qa_film.py runs the picture and sound checks and every gates/*.py module; measure a failing gate before loosening it; CREDIT is last and cannot be disabled.', 'which WARNs to act on'),
    'pairs':      ('A cut is the end frame of one shot meeting the start frame of the next; approve those two stills first.', 'snapshot.py --pairs, the review pack\'s Approve start / Approve end, pair_gate on anchors, words and names.', 'every START and END approval'),
    'review':     ('Reviewers open attachments, not repos.', 'One offline HTML with the frames, the claims, the gates, the honesty flags and a comment box per beat; served locally, same-origin writes only; --lock writes the sign-off.', 'the sign-off, every open comment'),
    'notes':      ('A reviewer proposes; the editor decides and says why.', 'Whole-cut notes snap to the nearest edit boundary and carry accepted / rejected with a reason; rejections are kept and shipped in DELIVERY.md.', 'every accept / reject and its reason'),
    'export':     ('A delivery that hides its decisions invites the same questions twice.', 'Presets from the mastered film only, every output re-checked for the credit; DELIVERY.md carries the reviewer notes and the decisions kept manual.', 'cut points, speeds, the take, the notes, the final length'),
}
ORDER = ['brief', 'references', 'look', 'storyboard', 'sketch', 'lock', 'cutlist', 'seams', 'narration', 'footage', 'scene', 'build', 'qa', 'pairs', 'review', 'notes', 'export']


def lesson(step):
    k = str(step).lower().strip()
    if k not in LESSONS:
        return None
    cause, rule, manual = LESSONS[k]
    return {'step': k, 'lesson': cause, 'rule': rule, 'manual': manual}


def line(step):
    L = lesson(step)
    return ('      lesson · %s — %s' % (L['lesson'], L['rule'])) if L else ''


def table():
    rows = ['| Step | The lesson | The rule it became | Kept manual |', '|---|---|---|---|']
    for k in ORDER:
        c, r, m = LESSONS[k]
        rows.append('| %s | %s | %s | %s |' % (k, c, r, m))
    return '\n'.join(rows)


def selftest():
    ok = all(lesson(k) for k in ORDER) and lesson('nope') is None and line('qa').startswith('      lesson') and table().count('\n') == len(ORDER) + 1
    ok = ok and all(len(LESSONS[k][0].split()) <= 24 for k in ORDER)
    print('lessons selftest %s (%d steps)' % ('PASS' if ok else 'FAIL', len(ORDER)))
    return 0 if ok else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if '--selftest' in a:
        sys.exit(selftest())
    if '--md' in a:
        print(table()); sys.exit(0)
    if '--all' in a or not a:
        for k in ORDER:
            print('%-11s %s' % (k, LESSONS[k][0])); print('            %s' % LESSONS[k][1])
        sys.exit(0)
    L = lesson(a[0])
    if not L:
        print('unknown step %r (%s)' % (a[0], ', '.join(ORDER))); sys.exit(2)
    print(json.dumps(L, indent=1, ensure_ascii=False) if '--json' in a else '%s\n%s\nkept manual: %s' % (L['lesson'], L['rule'], L['manual']))
