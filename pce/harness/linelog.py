"""Log every dialogue line the PCE engine decodes, with a BaseRAM snapshot.

The decoder expands one line at a time into the BaseRAM buffer at $3600 (a
0xFF ends it); nothing on disc or in SysCardRAM holds the line as SJIS, so
the buffer is the only place the plain text exists. This plays the scene,
pressing I every `--every` frames, and records each new buffer content with
the frame and a copy of BaseRAM (to find the script cursor by diffing).

  python pce/harness/linelog.py --frames 40000 --out work/pce/linelog.json
"""
import argparse, ctypes as C, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import emurun as E
import pcerun as R

LINE = 0x1600          # BaseRAM offset of the line buffer (CPU $3600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cue", default=R.CUE)
    ap.add_argument("--frames", type=int, default=40000)
    ap.add_argument("--start", type=int, default=29000, help="first frame to watch")
    ap.add_argument("--every", type=int, default=150, help="press I every N frames")
    ap.add_argument("--out", default=os.path.join(WORK, "pce", "linelog.json"))
    a = ap.parse_args()
    emu = E.Emu(core=R.CORE)
    emu.load(a.cue)
    c = emu.core
    c.retro_get_memory_data.restype = C.c_void_p
    c.retro_get_memory_size.restype = C.c_size_t
    press = {f: (set() if b is None else {E.BTN[b]}) for f, b in R.BOOT}
    log, last = [], None
    for f in range(a.frames):
        if f in press:
            emu.held = press[f]
        elif f >= a.start:
            k = (f - a.start) % a.every
            if k == 0:
                emu.held = {E.BTN["a"]}
            elif k == 10:
                emu.held = set()
        emu.run()
        if f >= a.start and f % 5 == 0:
            ram = C.string_at(c.retro_get_memory_data(2), c.retro_get_memory_size(2))
            end = ram.find(b"\xff", LINE)
            line = ram[LINE:end] if 0 <= end - LINE <= 200 else b""
            if line and line != last:
                last = line
                log.append({"frame": f, "sjis": line.hex(),
                            "text": line.decode("cp932", errors="replace"),
                            "baseram": ram[:0x2000].hex()})
                print(f, log[-1]["text"], flush=True)
    json.dump(log, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(log)} lines -> {a.out}")


if __name__ == "__main__":
    main()
