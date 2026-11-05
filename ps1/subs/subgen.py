# -*- coding: utf-8 -*-
"""Scene subtitle generator library: the B010 method for every scene.

A scene generator (work/gen_BXXX.py) is a LINES table - (xa, chan, file):
(id, speaker, [segment texts]) - and nothing else. This module supplies the
rest:

  streams(scene)        every XA stream the scene's cue file already cards,
                        resolved to its XA file (M000/S000) by sector range,
                        plus any (xa, chan, file) the generator adds
  ensure_ts(streams)    timestamped ASR for each (faster-whisper medium,
                        cached in work/ts_cache.json; segment times in s)
  show(scene)           print every segment with its time, for writing LINES
  build(scene, LINES)   write ps1/translation/subs_BXXX.json (+ the Japanese
                        sidecar in work/subs_ref), one card per segment,
                        pieces timed in proportion to their length, every
                        card asserted to fit the scene's rows x cols

Sector timing: each stream converts with its own rate, span / wav duration.
The master `dur` is 2x too long for every stream, mono included.

Repository policy: generators hold English only. Japanese lives in the ASR
cache and the sidecar, both under work/ (ignored).
"""
import contextlib, json, os, sys, wave
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MASTER = os.path.join(WORK, 'master_lines.json')
TRANSCRIPTS = os.path.join(WORK, 'all_transcripts.json')
TS_CACHE = os.path.join(WORK, 'ts_cache.json')
WAVS = os.path.join(WORK, 'xa_all', 'SND', 'XAS')
XA_NAME = {'M': 'XAS_M000.XA', 'S': 'XAS_S000.XA'}

_master = None


def master():
    global _master
    if _master is None:
        _master = json.load(open(MASTER, encoding='utf-8'))
        # xa_census.py's master_lines carries the jPSXdec stream name as
        # `key` (= the WAV basename) and no transcript; the hand-built one
        # it replaced (lost 2026-09-12) had `ja` and was joined to the
        # transcripts by text. Keep that join for a file that still has it.
        if _master and 'key' not in _master[0]:
            t = json.load(open(TRANSCRIPTS, encoding='utf-8'))
            inv = {}
            for k, v in t.items():
                inv.setdefault(v, []).append(k)
            for it in _master:
                ks = [k for k in inv.get(it.get('ja', ''), []) if k.startswith(XA_NAME[it['xa']])]
                it['key'] = ks[0] if ks else None
    return _master


def find(xa, ch, file):
    for it in master():
        if it['xa'] == xa and it['ch'] == ch and it['file'] == file:
            return it
    raise KeyError((xa, ch, file))


def resolve(ch, file, start):
    """Which XA file a cue's (chan, file, start sector) belongs to."""
    hits = [it for it in master() if it['ch'] == ch and it['file'] == file
            and it['start'] <= start < it['end'] + 1]
    if len(hits) == 1:
        return hits[0]
    hits = [it for it in master() if it['ch'] == ch and it['file'] == file]
    if len(hits) == 1:
        return hits[0]
    raise KeyError(f'ambiguous stream chan {ch} file {file} at {start}: {[(h["xa"], h["start"]) for h in hits]}')


def wav_dur(key):
    with contextlib.closing(wave.open(os.path.join(WAVS, key + '.wav'))) as w:
        return w.getnframes() / w.getframerate()


def streams(scene, extra=()):
    """[(xa, ch, file, master entry)] for a scene: what its cue file cards
    (chan 254/255 chain and marker cues excluded) plus `extra`."""
    p = os.path.join(ROOT, 'ps1/translation', f'subs_{scene}.json')
    seen, out = set(), []
    if os.path.exists(p):
        for c in json.load(open(p, encoding='utf-8'))['cues']:
            if c['chan'] >= 254:
                continue
            it = resolve(c['chan'], c['file'], c['start'])
            k = (it['xa'], it['ch'], it['file'])
            if k not in seen:
                seen.add(k)
                out.append(k)
    for k in extra:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return [(xa, ch, f, find(xa, ch, f)) for xa, ch, f in out]


def ensure_ts(keys):
    """Timestamped transcription for every key not yet cached."""
    cache = json.load(open(TS_CACHE, encoding='utf-8')) if os.path.exists(TS_CACHE) else {}
    todo = [k for k in keys if k and k not in cache]
    if todo:
        from faster_whisper import WhisperModel
        PROMPT = ("スナッチャー、ジャンカー、ギリアン・シード、ミカ・スレイトン、"
                  "ハリー・ベンソン、チーフ、ネオ・コウベシティ、紫外線、太陽光線、"
                  "チューブライナー、ギブスン、ランダム・ハジル、ナポレオン、"
                  "ジェイミー、カトリーナ、イワン、メタルギア、バイオロイド、"
                  "工場跡、報告、復唱、任務。")
        model = WhisperModel('medium', device='cpu', compute_type='int8')
        for k in todo:
            segs, _ = model.transcribe(os.path.join(WAVS, k + '.wav'), language='ja',
                                       initial_prompt=PROMPT, beam_size=5,
                                       vad_filter=False)
            cache[k] = [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip()}
                        for s in segs]
            print(f'  transcribed {k}: {len(cache[k])} segments', flush=True)
            json.dump(cache, open(TS_CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return cache


def show(scene, extra=()):
    """Print every stream's segments - the input for writing LINES."""
    st = streams(scene, extra)
    ts = ensure_ts([it['key'] for _, _, _, it in st])
    for xa, ch, f, it in st:
        d = wav_dur(it['key']) if it['key'] else 0
        print(f"('{xa}', {ch}, {f})  {it['start']}-{it['end']}  wav {d:5.1f}s")
        for g in ts.get(it['key'], []):
            print(f"    {g['start']:6.2f}-{g['end']:6.2f}  {g['text']}")


def fits(text, rows, cols):
    from subs_cue import wrap_only
    try:
        wrap_only(text, rows, cols)
        return True
    except SystemExit:
        return False


def build(scene, lines, options=None, last=(), fixed=None, cols_of=None, chains=(), reels=(), disabled=()):
    """Write the scene's cue file from LINES.

    lines:   [((xa, ch, file), id, speaker, [seg texts])]; a seg text may be
             a list of pieces (timed by length), or '' to merge the segment's
             time into the previous piece. Segment counts are asserted.
    last:    ids whose LINE ends a conversation (its final card clears the box
             when the stream stops)
    fixed:   {id: (start, end)} sector overrides for hand-timed cards
    cols_of: {id: cols} narrower wrap for a card (portrait layouts)
    disabled: ids kept in the file but not shown (a sneeze is not a line)
    chains:  [(id, anchor_id, delay, wend, speaker, text)] frame-timed cards
             on a VAG line
    reels:   [(key, id_prefix, [(speaker, text)], {last seg indexes})] - a
             stereo reel whose segments alternate speakers; one card (or
             pieces) per ASR segment, ids prefix_NN
    """
    sys.argv = [sys.argv[0], 'on', 'x', '--scene', scene]
    from subs_cue import wrap_only
    options = dict(options or {})
    rows = options.get('rows', 3)
    cols = options.get('cols', 18)
    fixed = fixed or {}
    cols_of = cols_of or {}
    merge = options.pop('merge', True)

    def pieces_of(text, cid):
        """A segment's pieces - or the whole segment as one card when it fits
        the box. The pieces were cut for 11-cell rows; at 18 cells a whole
        ASR segment usually fits, and one card per segment reads better and
        times better than three. `merge: False` keeps every piece."""
        pieces = text if isinstance(text, list) else [text]
        if merge and len(pieces) > 1:
            joined = ' '.join(p.strip() for p in pieces)
            if fits(joined, rows, cols_of.get(cid, cols)):
                return [joined]
        return pieces
    ts = ensure_ts([find(*k)['key'] for k, *_ in lines] + [find(*r[0])['key'] for r in reels])
    cues, ref, misfits = [], {}, []
    sidecar = os.path.join(WORK, 'subs_ref', f'{scene}.json')
    if os.path.exists(sidecar):
        ref = json.load(open(sidecar, encoding='utf-8'))

    def emit(cid, speaker, key, start, end, text, ja):
        c = cols_of.get(cid, cols)
        try:
            wrap_only(text, rows, c)
        except SystemExit:
            misfits.append(f'{cid}: does not fit {rows} rows x {c}: {text!r}')
        cue = {'id': cid, 'file': key[2], 'chan': key[1], 'start': start, 'end': end,
               'dur': round((end - start) / 150, 1), 'speaker': speaker, 'en': text,
               'enabled': cid not in disabled}
        if cid in cols_of:
            cue['cols'] = cols_of[cid]
        cues.append(cue)
        ref[cid] = ja

    for key, cid, speaker, texts in lines:
        it = find(*key)
        segs = ts[it['key']]
        assert len(segs) == len(texts), f'{cid}: {len(segs)} ASR segments, {len(texts)} texts'
        span = it['end'] - it['start']
        dur = wav_dur(it['key'])
        sec = lambda t: it['start'] + int(round(t * span / dur))
        # merge '' texts into the previous segment's time
        groups = []
        for seg, text in zip(segs, texts):
            if text == '' and groups:
                groups[-1][0]['end'] = seg['end']
                groups[-1][2] += seg['text']
                continue
            groups.append([dict(seg), text, seg['text']])
        n = 0
        for gi, (seg, text, ja) in enumerate(groups):
            pieces = pieces_of(text, cid)
            t0, t1 = seg['start'], seg['end']
            if gi == len(groups) - 1:
                t1 = dur
            total = sum(len(p) for p in pieces)
            acc = 0
            for pi, piece in enumerate(pieces):
                sub = cid if n == 0 else cid + chr(ord('a') + n)
                if sub in fixed:
                    st, en = fixed[sub]
                else:
                    st = it['start'] if n == 0 else sec(t0 + (t1 - t0) * acc / total)
                    acc += len(piece)
                    en = it['end'] if (gi == len(groups) - 1 and pi == len(pieces) - 1) \
                        else sec(t0 + (t1 - t0) * acc / total)
                emit(sub, speaker, key, st, en, piece, ja if pi == 0 else '')
                n += 1
        if cid in last:                      # a base id marks the line's LAST card
            cues[-1]['last'] = True
    for key, prefix, segs_text, last_segs in reels:
        it = find(*key)
        segs = ts[it['key']]
        assert len(segs) == len(segs_text), f'{prefix}: {len(segs)} ASR segments, {len(segs_text)} texts'
        span = it['end'] - it['start']
        dur = wav_dur(it['key'])
        sec = lambda t: it['start'] + int(round(t * span / dur))
        for si, (seg, (speaker, text)) in enumerate(zip(segs, segs_text)):
            pieces = pieces_of(text, f'{prefix}_{si:02d}')
            t0 = seg['start']
            t1 = segs[si + 1]['start'] if si + 1 < len(segs) else dur
            total = sum(len(p) for p in pieces)
            acc = 0
            for pi, piece in enumerate(pieces):
                sub = f'{prefix}_{si:02d}' + ('' if pi == 0 else chr(ord('a') + pi))
                # the first card opens with the stream unless the reel has a
                # real lead-in (B080's arrival: 4 s of music before Metal speaks)
                st = it['start'] if si == 0 and pi == 0 and t0 < 1.5 else sec(t0 + (t1 - t0) * acc / total)
                acc += len(piece)
                en = it['end'] if (si == len(segs) - 1 and pi == len(pieces) - 1)                     else sec(t0 + (t1 - t0) * acc / total)
                emit(sub, speaker, key, st, en, piece, seg['text'] if pi == 0 else '')
            if si in last_segs:
                cues[-1]['last'] = True
    for cid, anchor, delay, wend, speaker, text in chains:
        try:
            wrap_only(text, rows, cols)
        except SystemExit:
            raise SystemExit(f'{cid}: does not fit: {text!r}')
        cues.append({'id': cid, 'file': 0, 'chan': 254, 'start': delay, 'end': wend,
                     'dur': round((wend - delay) / 60, 1), 'speaker': speaker, 'en': text,
                     'enabled': True, 'anchor': anchor, **({'last': True} if cid in last else {})})
    if misfits:
        raise SystemExit(chr(10).join(misfits))
    out = {'scene': scene}
    if options:
        out['options'] = options
    out['cues'] = cues
    p = os.path.join(ROOT, 'ps1/translation', f'subs_{scene}.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(sidecar), exist_ok=True)
    json.dump(ref, open(sidecar, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{scene}: {len(cues)} cues written')
    for c in cues:
        print(f"  {c['id']:12s} {c['chan']}/{c['file']:<3} {c['start']}-{c['end']} {c['speaker']:8s} {c['en']}")
    return cues
