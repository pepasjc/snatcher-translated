"""Timestamped transcription for the long S-reels (B080 work).

  python lib/asr/transcribe_ts.py out.json wav1 wav2 ...

Writes {stream_name: [{start, end, text}, ...]} with segment times in seconds.
"""
import json, os, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from faster_whisper import WhisperModel

outp = sys.argv[1]
wavs = sys.argv[2:]

PROMPT = ("スナッチャー、ジャンカー、ギリアン・シード、ミカ・スレイトン、"
          "ハリー・ベンソン、チーフ、ネオ・コウベシティ、紫外線、太陽光線、"
          "チューブライナー、ギブスン、ランダム・ハジル、ナポレオン、"
          "ジェイミー、カトリーナ、イワン、メタルギア、バイオロイド、"
          "工場跡、報告、復唱、任務。")

done = {}
if os.path.exists(outp):
    done = json.load(open(outp, encoding='utf-8'))

model = WhisperModel("medium", device="cpu", compute_type="int8")
for w in wavs:
    key = os.path.splitext(os.path.basename(w))[0]
    if key in done:
        print('skip', key)
        continue
    # VAD off when NOVAD is set: the voice-activity filter silently drops
    # quiet dialogue, which is how a whole Harry/Metal/Gillian conversation
    # came back as an empty transcript and never got carded.
    segs, info = model.transcribe(w, language='ja', beam_size=5,
                                  initial_prompt=PROMPT,
                                  vad_filter=not os.environ.get('NOVAD'))
    out = []
    for s in segs:
        out.append({'start': round(s.start, 2), 'end': round(s.end, 2),
                    'text': s.text.strip()})
        print(f"  {key} {s.start:7.1f}-{s.end:7.1f} {s.text.strip()}",
              flush=True)
    done[key] = out
    json.dump(done, open(outp, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('done', key, len(out), 'segments', flush=True)
print('wrote', outp)
