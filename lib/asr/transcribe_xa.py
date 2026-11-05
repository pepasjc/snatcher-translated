# -*- coding: utf-8 -*-
"""Transcribe extracted XA voice streams. The scenes carry no on-screen
text, so the source dialogue has to come off the audio before it can be
translated.

    python lib/asr/transcribe_xa.py work/xa_all            # flat text
    python lib/asr/transcribe_xa.py work/xa_all --words    # + segment times
    NOVAD=1 python lib/asr/transcribe_xa.py work/xa_all --only XAS_M000.XA[7]

Two outputs, both keyed by stream name (= the WAV basename = the `key` in
the census):

    work/all_transcripts.json   {key: "whole line"}          - for reading
    work/ts_cache.json          {key: [{start, end, text}]}  - what becomes cards

Both are resumable: a stream already present is skipped, and the file is
written after every stream, so a run can be killed at any point.

Two things that are not optional:

* **The vocabulary prompt** (`asr_prompt.txt`). Whisper conditions on it as
  if it preceded the audio. Without it the model loses every proper noun
  and mishears the game's own jargon - 紫外線 came back as 姉妹性.
* **NOVAD=1 before you conclude a stream has no speech.** The voice
  activity filter silently drops quiet dialogue; a whole three-way
  conversation came back as an empty transcript that way and went uncarded.

Output stays under work/ - it is source-script text and is not committed.
"""
import argparse, glob, json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def load(path):
    return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}


def save(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(obj, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('wavdir', help='directory of extracted WAVs (searched recursively)')
    ap.add_argument('--words', action='store_true',
                    help='also write per-segment times (needed to make cues)')
    ap.add_argument('--flat', default='work/all_transcripts.json')
    ap.add_argument('--ts', default='work/ts_cache.json')
    ap.add_argument('--prompt', default=os.path.join(HERE, 'asr_prompt.txt'))
    ap.add_argument('--model', default='medium',
                    help='faster-whisper model; medium is the accuracy/speed knee')
    ap.add_argument('--lang', default='ja')
    ap.add_argument('--only', nargs='*', default=None, help='stream keys to (re)do')
    ap.add_argument('--redo', action='store_true', help='ignore the cache')
    a = ap.parse_args()

    prompt = None
    if os.path.exists(a.prompt):
        prompt = open(a.prompt, encoding='utf-8').read().strip() or None
    if not prompt:
        print('WARNING: no vocabulary prompt - expect mangled proper nouns')

    wavs = sorted(glob.glob(os.path.join(a.wavdir, '**', '*.wav'), recursive=True))
    if a.only:
        want = set(a.only)
        wavs = [w for w in wavs if os.path.splitext(os.path.basename(w))[0] in want]
    if not wavs:
        raise SystemExit(f'no WAVs under {a.wavdir}')

    flat, ts = load(a.flat), load(a.ts)
    vad = not os.environ.get('NOVAD')
    todo = [w for w in wavs
            if a.redo or a.only
            or os.path.splitext(os.path.basename(w))[0] not in (ts if a.words else flat)]
    print(f'{len(wavs)} streams, {len(todo)} to do, model {a.model}, '
          f'vad {"on" if vad else "off"}')
    if not todo:
        return

    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device='cpu', compute_type='int8')

    for i, w in enumerate(todo, 1):
        key = os.path.splitext(os.path.basename(w))[0]
        try:
            segs, _ = model.transcribe(w, language=a.lang, beam_size=5,
                                       initial_prompt=prompt, vad_filter=vad)
            segs = [{'start': round(s.start, 2), 'end': round(s.end, 2),
                     'text': s.text.strip()} for s in segs]
        except Exception as e:                  # a bad WAV must not kill the run
            print(f'  {key}: ERROR {e}')
            continue
        flat[key] = ''.join(s['text'] for s in segs).strip()
        ts[key] = segs
        print(f'  [{i}/{len(todo)}] {key}: {len(segs)} segments  {flat[key][:60]}',
              flush=True)
        if not segs:
            print('    (empty - re-run this stream with NOVAD=1 before believing it)')
        save(flat, a.flat)
        if a.words:
            save(ts, a.ts)
    print(f'wrote {a.flat}' + (f' and {a.ts}' if a.words else ''))


if __name__ == '__main__':
    main()
