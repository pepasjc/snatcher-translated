"""Bring a Redux savestate up to the current build so F2 testing runs the
NEW payload instead of the one frozen in the state: current bank, current
payload blob in high RAM, current exec code (see raminject.py).

  python ps1/harness/inject_state.py work/brief_start.sstate0 out.sstate0 [B010]
"""
import gzip, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import raminject

src, dst = sys.argv[1], sys.argv[2]
scene = sys.argv[3] if len(sys.argv) > 3 else 'B010'
raw = bytearray(gzip.decompress(open(src, 'rb').read()))
RAM0 = 0x27                       # decompressed offset of main RAM byte 0


def put(addr, data):
    off = RAM0 + (addr & 0x1FFFFF)
    raw[off:off + len(data)] = data


note = raminject.refresh(put, scene)
open(dst, 'wb').write(gzip.compress(bytes(raw), 6))
print(f"{dst}: {note}")
