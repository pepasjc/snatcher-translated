"""Headless Saturn host: run the Saturn Snatcher disc under Beetle Saturn.

The PS1 harness hosts Beetle PSX through ctypes (lib/emurun.py); this is the
same host pointed at the Beetle Saturn libretro core. `SaturnEmu` subclasses
`emurun.Emu` - only the core path, the core options and the pad map differ.
The BIOS (sega_101.bin for a JP disc) is read from the libretro system
directory; the default is the BIOS_DIR the PS1 host uses (lib/devpaths.py), or
SATURN_SYSDIR / --sysdir.

  python saturn/harness/satrun.py [image.cue] --frames 6000 --every 500
  python saturn/harness/satrun.py --frames 6000 --script boot.txt

Script lines: "<frame> <action>", action = press:<btn>[+<btn>], release,
shot, quit. Buttons: a b c x y z l r start up down left right (Saturn names;
mapped to the RetroPad ids Beetle Saturn expects).

Pristine boot timeline (Beetle Saturn 0.9.45.1, ~170 fps, 330x240 XRGB8888;
the English build's two boot screens (saturn/tools/satsplash.py: the PEPA SOFT
HOUSE card ~685, the Snatcher and the disclaimer ~865-1500) push everything
from Konami's logo on by `boot_screens(cue)` = 835 frames - SaturnEmu.load
sets `emu.boot_screens`, satpilot.presses() adds it):
Saturn BIOS logo ~300-600, black, Konami logo ~900-1500, black 1600-2000,
title "PUSH BUTTON" 2100-2800, then the attract movie. A on the title
(START did nothing there) opens NEW GAME / CONTINUE / OPTIONS at ~2600;
C confirms; the red disclaimer is up ~3500 and the opening runs from ~4000.
A savestate is ~4.7 MB and serializes in ~10 ms.
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness')]

import emurun

CORE = os.environ.get("SATURN_CORE") or os.path.join(
    devpaths.retro_cores(), "mednafen_saturn_libretro" + (".dll" if os.name == "nt" else ".so"))
SYSDIR = os.environ.get("SATURN_SYSDIR") or emurun.SYSDIR
DISC = os.path.join(ROOT, "discs", "iso_saturn_jp", "Snatcher (Japan).cue")

# Beetle Saturn's RetroPad map: Saturn A B C = RetroPad B A R, X Y Z = Y X L,
# Saturn L R = L2 R2 (RetroPad ids 12 13).
BTN = {"a": 0, "b": 8, "c": 11, "x": 1, "y": 9, "z": 10, "l": 12, "r": 13,
       "start": 3, "up": 4, "down": 5, "left": 6, "right": 7}


def boot_screens(cue):
    """Frames the image's boot screens add before Konami's logo: satsplash.BOOT_DELAY
    when its IP carries the player, 0 for the pristine disc (or an image built
    without satsplash)."""
    import satsplash
    track1 = None
    for line in open(cue, encoding="utf-8", errors="replace"):
        if line.strip().upper().startswith("FILE"):
            track1 = os.path.join(os.path.dirname(cue), line.split('"')[1]); break
    return satsplash.BOOT_DELAY if track1 and satsplash.hooked(track1) else 0


class SaturnEmu(emurun.Emu):
    def __init__(self, core=CORE, sysdir=SYSDIR):
        if not os.path.exists(core):
            raise SystemExit(f"Saturn core not found: {core}")
        super().__init__(core, sysdir)
        # The PS1 host answers beetle_psx_* options; Beetle Saturn asks for
        # its own. Region from the disc header (a JP disc picks sega_101.bin),
        # no frame skipping so every frame reaches the dump.
        self.options = {
            "beetle_saturn_region": "Auto Detect",
            "beetle_saturn_cd_access_method": "Sync",
            "beetle_saturn_autortc": "enabled",
            "beetle_saturn_horizontal_overscan": "0",
            "beetle_saturn_initial_scanline": "0",
            "beetle_saturn_last_scanline": "239",
        }
        self._asked = set()               # every option key the core queried

    def _env(self, cmd, data):
        if (cmd & 0xFFFF) == emurun.ENV_GET_VARIABLE and data:
            import ctypes as C
            self._asked.add(C.string_at(C.cast(data, C.POINTER(C.c_char_p))[0]).decode())
        return super()._env(cmd, data)

    def load(self, path):
        super().load(path)
        self.boot_screens = boot_screens(path)
        # Beetle Saturn polls no pad until the frontend names the device on
        # the port (RetroArch does it on every load); without it START on
        # the title screen went nowhere.
        self.core.retro_set_controller_port_device(0, 1)   # RETRO_DEVICE_JOYPAD


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=DISC)
    ap.add_argument("--frames", type=int, default=6000)
    ap.add_argument("--every", type=int, default=500)
    ap.add_argument("--out", default=os.path.join(WORK, "saturn", "boot"))
    ap.add_argument("--script", default=None)
    ap.add_argument("--core", default=CORE)
    ap.add_argument("--sysdir", default=SYSDIR)
    ap.add_argument("--state-at", type=int, default=0,
                    help="serialize once at this frame and report size/time")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    events = {}
    if a.script:
        for line in open(a.script):
            line = line.split("#")[0].strip()
            if not line:
                continue
            f, act = line.split(None, 1)
            events.setdefault(int(f), []).append(act.strip())
    emu = SaturnEmu(a.core, a.sysdir)
    emu.load(a.image)
    print(f"loaded {a.image}, pixel format {emu.fmt}", flush=True)
    log = open(os.path.join(a.out, "log.txt"), "w")
    t0 = time.time()
    for f in range(a.frames):
        for act in events.get(f, []):
            if act.startswith("press:"):
                emu.held = {BTN[b] for b in act[6:].split("+")}
            elif act == "release":
                emu.held = set()
            elif act.startswith("shot"):
                emu.image().save(os.path.join(a.out, f"f{f:06d}.png"))
            elif act == "quit":
                break
        emu.run()
        if a.every and f % a.every == 0 and emu.frame:
            import numpy as np
            im = emu.image()
            im.save(os.path.join(a.out, f"f{f:06d}.png"))
            arr = np.asarray(im)
            line = (f"f={f} {im.width}x{im.height} mean={arr.mean():.1f} "
                    f"fps={f / max(time.time() - t0, 1e-9):.0f}")
            print(line, flush=True); log.write(line + "\n")
        if a.state_at and f == a.state_at:
            ts = time.time(); blob = emu.state()
            line = f"state at {f}: {len(blob)} bytes in {time.time() - ts:.2f}s"
            print(line, flush=True); log.write(line + "\n")
    dt = time.time() - t0
    if emu.frame:
        emu.image().save(os.path.join(a.out, "final.png"))
    line = f"done: {a.frames} frames in {dt:.1f}s = {a.frames / dt:.0f} fps; options asked: {sorted(emu._asked)}"
    print(line, flush=True); log.write(line + "\n"); log.close()


if __name__ == "__main__":
    main()
