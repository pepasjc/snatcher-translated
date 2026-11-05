"""Boot the built PCE image fresh and press through to the reception's verb
menu: the only test of a build (a savestate carries every module already
in RAM, so a state made on one build proves nothing about another).

  python pce/harness/pceboot.py [out_prefix] [events]      (PCE_CUE=<cue> boots another image)

Writes <out>_35700.mdf/.png (the verb menu, ~35,700 frames in) and
<out>_end.mdf/.png; default out = work/pce/final. `events` is
'frame:button,...' (button empty = release, 'shot' = capture, 'state' =
savestate); the default is MENU below - RUN at 1000, a press at 4900 past
the title, then a press every 90 frames from 32000 through the opening's
cards (each press is 8 frames), a shot and a state at 35700.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

import emurun as E
import pcerun as R

CUE = os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue")
MENU = "4900:a,4930:," + ",".join(f"{f}:a,{f + 8}:" for f in range(32000, 35600, 90)) + ",35700:shot,35700:state"


def run(out, events=MENU, cue=CUE, bram=None):
    emu = E.Emu(core=R.CORE)
    emu.load(cue)
    if bram:
        emu.load_card(bram)
    held = {1000: 'start', 1200: ''}
    shots, states = set(), set()
    for e in events.split(','):
        f, _, b = e.partition(':')
        if b == 'shot':
            shots.add(int(f))
        elif b == 'state':
            states.add(int(f))
        else:
            held[int(f)] = b
    last = max(list(held) + list(shots) + list(states))
    for f in range(last + 1):
        if f in held:
            emu.held = {E.BTN[held[f]]} if held[f] else set()
        emu.run()
        if f in shots:
            emu.image().save(f'{out}_{f}.png')
        if f in states:
            open(f'{out}_{f}.mdf', 'wb').write(emu.state())
    emu.image().save(f'{out}_end.png')
    open(f'{out}_end.mdf', 'wb').write(emu.state())
    return f'{out}_{max(states)}.mdf' if states else f'{out}_end.mdf'


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, "pce", "final")
    events = sys.argv[2] if len(sys.argv) > 2 else MENU
    print(run(out, events, cue=os.environ.get("PCE_CUE", CUE)))      # PCE_CUE: another image (a test one)
