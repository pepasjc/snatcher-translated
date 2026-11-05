"""New Game, no presses after the menu: log the INTRO payload's state
(HIRAM magic, shown cue, dialogue task step, window word, the captured
CdlSetfilter and the polled LBA) whenever it changes, screenshot every cue
90 frames after it draws and the screen every 600 frames."""
import ctypes as C, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import emurun
from hiram import HIRAM
emu = emurun.Emu(); emu.load(os.environ.get('IMAGE', 'patched/Snatcher (Japan).cue'))
core = emu.core; core.retro_get_memory_data.restype = C.c_void_p
B = 1050  # the boot card + splash hold ~14 s before the title (scripted.BOOT_SHIFT)
events = {B + 2600: 'press:start', B + 2615: 'release', B + 4400: 'press:circle', B + 4415: 'release'}
frames = int(sys.argv[1]) if len(sys.argv) > 1 else 28500
log = open('work/intro_run.txt', 'w'); last = None; shots = {}
bcd = lambda b: (b >> 4) * 10 + (b & 15)
for f in range(frames):
    act = events.get(f)
    if act:
        emu.held = {emurun.BTN[act[6:]]} if act.startswith('press:') else set()
    emu.run()
    ram = core.retro_get_memory_data(2)
    r = lambda a, n=4: C.string_at(C.c_void_p(ram + (a & 0x1FFFFF)), n)
    magic, shown = struct.unpack('<II', r(HIRAM, 8))
    ctx = struct.unpack('<I', r(0x800ABF64))[0]
    game = ctx == 0x80010000
    fn = struct.unpack('<I', r(ctx + 0x1ED0))[0] if game else 0
    prim = struct.unpack('<I', r(ctx + 0x27F0 + 0x1C))[0] if game else 0
    win = struct.unpack('<I', r(ctx + 0x1ACC))[0] if game else 0
    ff, fc = struct.unpack('<II', r(0x801D0030, 8))
    m_, s_, fr_ = r(ctx + 0x58C, 3) if game else (0, 0, 0)
    lba = (bcd(m_) * 60 + bcd(s_)) * 75 + bcd(fr_) - 150
    st = (magic, shown, fn, prim != 0, ff, fc)
    if st != last:
        log.write(f'{f}: magic={magic:08x} shown={shown:08x} fn={fn:08x} win={win:08x} '
                  f'sprites={prim != 0} filt={ff}/{fc} lba={lba}\n')
        log.flush(); last = st
        if shown != 0xFFFFFFFF and magic == 0x53554253:   # cue 0 too
            shots[f + 90] = shown
    if f in shots:
        emu.image().save(f'work/intro_cue_{f:06d}.png')
    if f % 600 == 0 and f >= 4800:
        emu.image().save(f'work/intro_run_{f:06d}.png')
