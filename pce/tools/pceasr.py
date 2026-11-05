"""Whisper over the PCE's voice lines: work/pce/asr_cache.json.

Every line a module plays (pcevoice.module_voices) is decoded to WAV and
transcribed once (faster-whisper `medium`, Japanese, the game-vocabulary
prompt of lib/asr/asr_prompt.txt; a record whose rate byte is not 0x0E
is an effect or a jingle and is skipped). The cache maps "act_NN" to
{text, segments [{start, end, text}], secs, rate}; pcematch.py reads it.

  python pce/tools/pceasr.py <rec> [<rec>...]     # the modules' lines
  python pce/tools/pceasr.py all                  # every module with voice lines
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcevoice as V

CACHE = os.path.join(WORK, "pce", "asr_cache.json")
PROMPT = open(os.path.join(ROOT, "lib", "asr", "asr_prompt.txt"), encoding="utf-8").read().strip()
SPEECH_RATE = 0x0E           # 16 kHz: the voice lines; the effects and jingles run at other rates


def load():
    return json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}


def save(cache):
    tmp = CACHE + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE)


def modules():
    ft = json.load(open(os.path.join(WORK, "pce", "filetable.json")))
    return [(e["rec"], e["n"]) for e in ft["1"]]


def model():
    """faster-whisper medium on the GPU when its runtime is installed (`pip install
    nvidia-cublas-cu12 nvidia-cudnn-cu12`: 2 s a line against 40 on the CPU), else the CPU."""
    from faster_whisper import WhisperModel
    try:
        import nvidia.cublas, nvidia.cudnn
        import site
        for d in (os.path.join(site.getsitepackages()[-1], "nvidia", "cublas", "bin"),
                  os.path.join(site.getsitepackages()[-1], "nvidia", "cudnn", "bin")):
            if os.path.isdir(d):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        return WhisperModel("medium", device="cuda", compute_type="float16")
    except Exception as e:
        print(f"(no GPU whisper: {e!r}; the CPU it is)", flush=True)
        return WhisperModel("medium", device="cpu", compute_type="int8")


def transcribe(recs):
    cache = load()
    whisper = None
    todo = []
    for rec, n in modules():
        if rec not in recs:
            continue
        for act, nn in V.module_voices(rec, n):
            key = f"{act}_{nn:02x}"
            if key in cache:
                continue
            r = V.record(act, nn)
            if r["rate"] != SPEECH_RATE:
                cache[key] = {"text": "", "segments": [], "secs": 0, "rate": r["rate"], "effect": True}
                continue
            todo.append((rec, act, nn, key))
    save(cache)
    print(f"{len(todo)} lines to transcribe", flush=True)
    for i, (rec, act, nn, key) in enumerate(todo):
        if whisper is None:
            whisper = model()
        path, r, secs = V.wav(act, nn)
        segs, info = whisper.transcribe(path, language="ja", beam_size=5, initial_prompt=PROMPT, vad_filter=False)
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
        cache[key] = {"text": " ".join(s["text"] for s in segs), "segments": segs, "secs": round(secs, 2), "rate": r["rate"]}
        print(f"[{i + 1}/{len(todo)}] {rec} {key} {secs:.1f}s {cache[key]['text'][:60]}", flush=True)
        if i % 10 == 9:
            save(cache)
    save(cache)


def main():
    if sys.argv[1] == "all":
        recs = {rec for rec, n in modules()}
    else:
        recs = {int(a) for a in sys.argv[1:]}
    transcribe(recs)


if __name__ == "__main__":
    main()
