"""Headless Snatcher CD-ROMantic (PCE) under Beetle PCE, through lib/emurun.

The PS1 harness's host works for the PC Engine once three libretro details are
answered (all now in lib/emurun.py, found the hard way):
  * GET_CORE_OPTIONS_VERSION / SET_VARIABLES - Beetle PCE crashes inside
    retro_load_game when GET_VARIABLE is refused, so the frontend must take
    each option's first listed value as its default;
  * GET_LOG_INTERFACE - the core calls log_cb unguarded while loading a disc;
  * retro_set_controller_port_device(0, JOYPAD) - without it port 0 is NONE
    and RUN never reaches the system card (the boot sat on "PUSH RUN BUTTON").

Boot timings on this image (NTSC frames from power-on): the system card wants
RUN at ~1000, the title takes I (button "a") at ~4900 for 初めから, ACT 1 opens
at ~29000 and the JUNKER HQ reception's first dialogue is up by ~32000.
Since the boot screens (pcesplash.py, 2026-09-29) the card is up at ~1057,
the splash ends ~1876 and the title shows at ~2640 instead of ~1800; the
title waits for I, so the 4900 press (and everything timed after it) stands.

  python pce/harness/pcerun.py --frames 32000 --shot 500 --state work/pce/stA.mdf
"""
import argparse, ctypes as C, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import emurun as E

CORE = os.environ.get("PCE_CORE") or os.path.join(devpaths.retro_cores(),
                    "mednafen_pce_libretro" + (".dll" if os.name == "nt" else ".so"))   # (PCE_CORE: another core's dll - pce_fast times the video differently)
CUE = os.path.join(WORK, "pce", "snatcher_pce.cue")
BOOT = [(1000, "start"), (1200, None), (4900, "a"), (4930, None)]


def run(frames, cue=CUE, core=CORE, events=BOOT, shot_every=0, outdir=None):
    """Play `frames` frames, pressing `events` [(frame, button|None)]."""
    emu = E.Emu(core=core)
    emu.load(cue)
    press = {f: (set() if b is None else {E.BTN[b]}) for f, b in events}
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    for f in range(frames):
        if f in press:
            emu.held = press[f]
        emu.run()
        if outdir and shot_every and f % shot_every == 0 and emu.frame:
            emu.image().save(os.path.join(outdir, f"f{f:06d}.png"))
    return emu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cue", default=CUE, help="disc to boot (patched copy, ...)")
    ap.add_argument("--frames", type=int, default=32000)
    ap.add_argument("--shot", type=int, default=0, help="capture every N frames")
    ap.add_argument("--out", default=os.path.join(WORK, "pce", "run"))
    ap.add_argument("--state", help="write a savestate here at the end")
    ap.add_argument("--press", action="append", default=[],
                    help="extra FRAME:BUTTON (BUTTON empty = release)")
    a = ap.parse_args()
    events = list(BOOT)
    for p in a.press:
        f, _, b = p.partition(":")
        events.append((int(f), b or None))
    emu = run(a.frames, cue=a.cue, events=sorted(events), shot_every=a.shot,
              outdir=a.out)
    os.makedirs(a.out, exist_ok=True)
    emu.image().save(os.path.join(a.out, "final.png"))
    if a.state:
        open(a.state, "wb").write(emu.state())
        print(f"state: {a.state}")
    print(f"done {a.frames} frames -> {a.out}")


if __name__ == "__main__":
    main()
