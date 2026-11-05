"""Report which ISZ scene file is resident in a savestate's RAM.

Matches a distinctive slice of every ISZ file against the RAM image, which
identifies the loaded scene without guessing.

Usage: python which_scene.py state.sav [state2.sav ...]
"""
import sys, os, glob, struct
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from find_scene_var import load_ram

ISZ = os.path.join(ROOT, "discs/extracted_ps1", "PLN", "ISZ")

if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(ISZ, "*.BIN")))
    probes = []
    for p in files:
        d = open(p, "rb").read()
        probes.append((os.path.basename(p)[:-4], d[0x40:0x40+96]))
    for state in sys.argv[1:]:
        ram = load_ram(state)
        found = [(n, ram.find(pr)) for n, pr in probes if pr in ram]
        names = ", ".join(f"{n}@{0x80000000+o:#x}" for n, o in found)
        print(f"{os.path.basename(state)}: {names or 'no ISZ matched'}")
