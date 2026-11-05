# -*- coding: utf-8 -*-
"""Re-time ts_cache.json segments that carry whole-second timestamps.

Nineteen streams in the cache (every B080 reel among them) have integer
start/end on every segment - not whisper's 20 ms grid, so they came from
some rounded pass - and Luiz heard the result: after the ruins the text
runs ahead of the voices. The segment TEXTS are fine and the scene
generators key on them (segment counts, LINES per segment), so only the
times are replaced:

  1. transcribe the stream again with word timestamps (no VAD);
  2. lay the new words out as one character string with a time per char;
  3. find each old segment's text in that string (difflib, in order, from
     the previous match on) and take the first/last matched char's times.

Segments that cannot be matched keep their old times and are reported.

    python lib/asr/retime_ts.py                 # all integer-timed streams
    python lib/asr/retime_ts.py XAS_S000.XA[56] # one stream
    DRY=1 ...                                # report only, no write
"""
import difflib, json, os, sys
from faster_whisper import WhisperModel
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
CACHE = os.path.join(WORK, 'ts_cache.json')
WORDS = os.path.join(WORK, 'ts_words.json')       # the word passes, kept
WAVS = os.path.join(WORK, 'xa_all', 'SND', 'XAS')
PROMPT = ("スナッチャー、ジャンカー、ギリアン・シード、ミカ・スレイトン、"
          "ハリー・ベンソン、チーフ、ネオ・コウベシティ、紫外線、太陽光線、"
          "チューブライナー、ギブスン、ランダム・ハジル、ナポレオン、"
          "ジェイミー、カトリーナ、イワン、メタルギア、バイオロイド、"
          "工場跡、報告、復唱、任務。")


def integer_timed(segs):
    return len(segs) > 3 and all(float(s['start']).is_integer() and float(s['end']).is_integer() for s in segs)


def word_pass(model, key):
    segs, _ = model.transcribe(os.path.join(WAVS, key + '.wav'), language='ja', beam_size=5,
                               initial_prompt=PROMPT, vad_filter=False, word_timestamps=True)
    words = []
    for s in segs:
        for w in (s.words or []):
            words.append({'start': round(w.start, 2), 'end': round(w.end, 2), 'text': w.word})
    return words


def retime(old, words):
    """New (start, end) per old segment, or None where the text is not found.

    Ordered alignment: each segment is searched from the previous match on,
    inside a window a few times its own length, and a match must cover most
    of the segment and start near the window's head - a loose match once
    jumped a whole reel ahead and every later segment failed."""
    chars, t0, t1 = [], [], []
    for w in words:
        txt = w['text'].replace(' ', '')
        n = max(len(txt), 1)
        for i, ch in enumerate(txt):
            chars.append(ch)
            t0.append(w['start'] + (w['end'] - w['start']) * i / n)
            t1.append(w['start'] + (w['end'] - w['start']) * (i + 1) / n)
    hay = ''.join(chars)
    out, pos = [], 0
    for s in old:
        needle = s['text'].replace(' ', '').lstrip('-')
        if not needle:
            out.append(None); continue
        win = hay[pos:pos + max(4 * len(needle), 40)]
        sm = difflib.SequenceMatcher(None, win, needle, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
        covered = sum(b.size for b in blocks)
        if not blocks or covered < 0.6 * len(needle) or blocks[0].a > 2 * len(needle):
            out.append(None); continue
        a = pos + blocks[0].a
        b = pos + blocks[-1].a + blocks[-1].size - 1
        out.append((round(t0[a], 2), round(t1[b], 2)))
        pos = b + 1
    return out


def main():
    cache = json.load(open(CACHE, encoding='utf-8'))
    words_all = json.load(open(WORDS, encoding='utf-8')) if os.path.exists(WORDS) else {}
    keys = sys.argv[1:] or [k for k, v in cache.items() if integer_timed(v)]
    model = None
    for key in keys:
        if key not in words_all:
            if model is None:
                model = WhisperModel('medium', device='cpu', compute_type='int8')
            print('transcribing', key, flush=True)
            words_all[key] = word_pass(model, key)
            json.dump(words_all, open(WORDS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        old = cache[key]
        new = retime(old, words_all[key])
        # short unmatched segments ("ん?", a name called out) take a
        # proportional share of the gap between their matched neighbours
        got = [i for i, n in enumerate(new) if n is not None]
        mono = all(new[got[k]][1] <= new[got[k + 1]][0] + 0.5 for k in range(len(got) - 1))
        if mono and len(got) >= 0.8 * len(new):
            for k in range(len(got) - 1):
                i0, i1 = got[k], got[k + 1]
                if i1 - i0 > 1:
                    g0, g1 = new[i0][1], new[i1][0]
                    span = sum(old[i]['end'] - old[i]['start'] for i in range(i0 + 1, i1)) or 1
                    t = g0
                    for i in range(i0 + 1, i1):
                        d = (old[i]['end'] - old[i]['start']) / span * (g1 - g0)
                        new[i] = (round(t, 2), round(t + d, 2)); t += d
            if new and new[0] is None:                 # leading: end at the first match
                new[0] = (max(0.0, new[got[0]][0] - (old[0]['end'] - old[0]['start'])), new[got[0]][0])
            if new and new[-1] is None and len(new) > 1 and new[-2] is not None:
                new[-1] = (new[-2][1], new[-2][1] + (old[-1]['end'] - old[-1]['start']))
        ok = all(n is not None for n in new) and all(new[i][1] <= new[i + 1][0] + 0.5 for i in range(len(new) - 1))
        print(f'== {key}: {len(old)} segments, {sum(n is not None for n in new)} re-timed, {"APPLY" if ok else "SKIP (partial or out of order)"}')
        for s, n in zip(old, new):
            tag = f'{n[0]:6.1f}-{n[1]:6.1f}' if n else '   (unmatched)  '
            print(f"   {s['start']:5.1f}-{s['end']:5.1f} -> {tag}  {s['text'][:40]}")
            if n and ok and not os.environ.get('DRY'):
                s['start'], s['end'] = n
    if not os.environ.get('DRY'):
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('wrote', CACHE)


if __name__ == '__main__':
    main()
