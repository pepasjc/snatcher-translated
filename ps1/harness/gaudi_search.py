"""Type names into Gaudi's name search (ISZ_B040) headless and capture each
result. The search keyboard is not the menu-cursor keyboard scripted.py
drives (its cursor word never reads live), but the key cell (ctx+0x1D9E,
15-wide grid) and typed length (ctx+0x1D9B) are the same struct.

    python ps1/harness/gaudi_search.py CATHERINE RANDAM HAJILE [--out work/s_gaudi]

Starts from the B040 bookmark (keyboard open). Circle types the highlighted
key, START submits; a result screen closes on Circle. Captures land in --out
as <name>_<frame>.png after each submit and again 240 frames later.
"""
import argparse, ctypes as C, gzip, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import emurun
from explore import restore_scene

ap = argparse.ArgumentParser()
ap.add_argument('names', nargs='+')
ap.add_argument('--out', default=os.path.join(WORK, 's_gaudi'))
ap.add_argument('--state', default='B040')
ap.add_argument('--image', default='patched/Snatcher (Japan).cue')
ap.add_argument('--card', default=devpaths.get('SNATCHER_CARD', ''))
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

emu = emurun.Emu()
emu.load(a.image)
emu.load_card(a.card)
for _ in range(60):
    emu.run()
blob = gzip.decompress(open(os.path.join(WORK, 'states', f'{a.state}.state.gz'), 'rb').read())
restore_scene(emu, 'B040', blob)
core = emu.core
core.retro_get_memory_data.restype = C.c_void_p
ram = core.retro_get_memory_data(2)
CELL, TLEN = 0x11D9E, 0x11D9B


def rd(off):
    return C.string_at(C.c_void_p(ram + off), 1)[0]


f = 0


def frames(n, held=()):
    global f
    emu.held = {emurun.BTN[b] for b in held}
    for _ in range(n):
        emu.run(); f += 1
    emu.held = set()


def tap(btn):
    frames(8, (btn,)); frames(22)


def goto(target):
    for _ in range(40):
        cell = rd(CELL)
        if cell == target:
            return True
        r, c = divmod(cell, 15); tr, tc = divmod(target, 15)
        tap('down' if r < tr else 'up' if r > tr else 'right' if c < tc else 'left')
    return False


def shot(tag):
    p = os.path.join(a.out, f'{tag}_{f:06d}.png')
    emu.image().save(p)
    print(f'{f}: {p}')


MAXLEN = 0x11D9D                          # nonzero while the keyboard is up


def open_keyboard():
    if rd(0x11D7C) in (0xF8, 0xF9, 0xFA) and rd(0x11D7D) & 1:   # Search name / QUIT live
        tap('up'); tap('circle'); frames(90)
        for _ in range(3):                 # Person file. / Enter the name...
            tap('circle'); frames(90)
    assert rd(MAXLEN), 'keyboard did not open'
    while rd(TLEN):                        # backspace the stray first letter
        assert goto(43); tap('circle')


frames(60)
for name in a.names:
    open_keyboard()
    for ch in name.upper():
        t = (ord(ch) - 65) if ch.isalpha() else 30 + int(ch)
        assert goto(t), (name, ch)
        tap('circle')
    print(f'{f}: typed {name!r} (len {rd(TLEN)})')
    shot(name + '_typed')
    tap('start')
    frames(90); shot(name)
    if os.environ.get('TAIL_DUMP'):
        end = 0x8010D000 + os.path.getsize(os.path.join(os.environ.get('SNATCHER_PATCHED') or 'patched', 'ISZ_B040.BIN'))
        print(f'tail {end - 64:08x}:', C.string_at(C.c_void_p(ram + ((end - 64) & 0x1FFFFF)), 96).hex(' '))
    if os.environ.get('TRACE_RING'):
        import struct
        ring = C.string_at(C.c_void_p(ram + 0x1FD000), 0x1010)
        n = struct.unpack_from('<I', ring, 0)[0]
        print(f'ring index {n}')
        for i in range(1, min(n, 255) + 1):
            t0, t1, t2, t3 = struct.unpack_from('<IIII', ring, i * 16)
            print(f'  {i:3d} base={t0:08x} off={t1:04x} key={t2:08x} group={t3:08x}')
        C.memset(C.c_void_p(ram + 0x1FD000), 0, 0x1010)
    frames(240); shot(name + '_b')
    for i in range(12):                   # close the result / correction
        tap('circle'); frames(60)
        if i == 2:
            shot(name + '_c')
        if rd(0x11D7C) in (0xF8, 0xF9, 0xFA) and rd(0x11D7D) & 1:
            break                         # back at Search name / QUIT
    frames(60)
