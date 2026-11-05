# -*- coding: utf-8 -*-
"""The Sega CD voice library: extract every clip off the US disc and
transcribe it (English, faster-whisper on the GPU).

    python lib/segacd/pcmvoice.py            -> work/segacd/pcm_asr.json
    python lib/segacd/pcmvoice.py --wav      -> also work/segacd/pcm/NNNN.wav
    python lib/segacd/pcmvoice.py --only 120 240

PCMLD_01.BIN is one 84 MB blob of 8-bit sign-magnitude PCM at 16 kHz
(the Ricoh RF5C164's format: bit 7 the sign, bits 0-6 the magnitude);
PCMLT_01.BIN indexes it: an 8-byte header, then 8-byte records
{type u16, param u16, start u16, length u16} with start and length in
2048-byte sectors of the blob - 2,195 records, 1,270 with a length.
Record 0's first 32 bytes are a header, not samples.

Output: {"120": {"start", "len", "secs", "text", "segments": [{start,
end, text}]}, ...} keyed by record index. Resumable: a record already in
the file is skipped, the file is written every 50 records.

Sega CD audio and its transcript are source material - work/ only.
"""
import argparse, glob, json, os, site, struct, sys, wave
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import numpy as np
import sptext

OUT = os.path.join(WORK, "segacd", "pcm_asr.json")
WAVDIR = os.path.join(WORK, "segacd", "pcm")
RATE = 16000


def cuda_dlls():
    """The pip CUDA runtime (nvidia-cublas-cu12, nvidia-cudnn-cu12) ships its
    DLLs under site-packages/nvidia/*/bin; ctranslate2 finds them on PATH."""
    for sp in site.getsitepackages():
        for d in glob.glob(os.path.join(sp, 'nvidia', '*', 'bin')):
            os.add_dll_directory(d)
            os.environ['PATH'] = d + os.pathsep + os.environ['PATH']


def records(files=None):
    files = files or sptext.iso_files()
    lt = sptext.read_file('PCMLT_01.BIN', files)
    return [struct.unpack('>HHHH', lt[i:i + 8]) for i in range(8, len(lt) - 7, 8)]


def decode(raw):
    a = np.frombuffer(raw, dtype=np.uint8).astype(np.int16)
    return (np.where(a & 0x80, a & 0x7F, -(a & 0x7F)) * 256).astype(np.int16)


class Library:
    def __init__(self):
        self.files = sptext.iso_files()
        self.recs = records(self.files)
        self.lba = self.files['PCMLD_01.BIN'][0]
        self.f = open(sptext.TRACK1, 'rb')

    def raw(self, idx):
        _, _, st, ln = self.recs[idx]
        out = bytearray()
        for i in range(ln):
            self.f.seek((self.lba + st + i) * 2352)
            out += self.f.read(2352)[16:16 + 2048]
        return bytes(out[32:] if idx == 0 else out)

    def samples(self, idx):
        return decode(self.raw(idx))

    def wav(self, idx, path):
        s = self.samples(idx)
        w = wave.open(path, 'wb')
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(s.tobytes()); w.close()
        return len(s) / RATE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', nargs='*', type=int)
    ap.add_argument('--wav', action='store_true', help='keep the WAVs')
    ap.add_argument('--model', default='medium.en')
    ap.add_argument('--redo', action='store_true')
    a = ap.parse_args()
    cuda_dlls()
    from faster_whisper import WhisperModel
    lib = Library()
    os.makedirs(WAVDIR, exist_ok=True)
    done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) and not a.redo else {}
    todo = a.only if a.only else [i for i, r in enumerate(lib.recs) if r[3]]
    todo = [i for i in todo if str(i) not in done]
    print(f"{len(todo)} records to transcribe")
    model = WhisperModel(a.model, device='cuda', compute_type='float16')
    for n, idx in enumerate(todo):
        path = os.path.join(WAVDIR, f'{idx:04d}.wav')
        secs = lib.wav(idx, path)
        segs, _ = model.transcribe(path, language='en', beam_size=5, vad_filter=False)
        segs = [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip()} for s in segs]
        _, _, st, ln = lib.recs[idx]
        done[str(idx)] = {'start': st, 'len': ln, 'secs': round(secs, 2),
                          'text': ' '.join(s['text'] for s in segs), 'segments': segs}
        if not a.wav:
            os.remove(path)
        print(f"{idx:4d} {secs:5.1f}s  {done[str(idx)]['text'][:90]}")
        if n % 50 == 49:
            json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"{OUT}: {len(done)} records")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
