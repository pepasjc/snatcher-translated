"""Headless libretro driver: run a PS1 image under Beetle PSX and dump frames.

RetroArch's GUI cannot be scripted reliably (injected keys never reach it), so
the core is hosted directly. This gives a cycle-accurate emulator that can be
driven from a test script — the only way to reproduce a bug that DuckStation
does not have without asking a human to press buttons.

  python emurun.py <image.cue> --frames 3600 --script boot.txt --out work/emu

Script lines: "<frame> <action>", action = press:<btn>, shot, quit.
Buttons: cross circle triangle square start select up down left right
"""
import ctypes as C, os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import devpaths

# the cores folder and the BIOS folder come from lib/devpaths.py (RETRO_CORES, BIOS_DIR)
CORE = os.path.join(devpaths.retro_cores(), "mednafen_psx_libretro" + (".dll" if os.name == "nt" else ".so"))
SYSDIR = devpaths.get("BIOS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bios"))

BTN = {"b": 0, "cross": 0, "y": 1, "square": 1, "select": 2, "start": 3,
       "up": 4, "down": 5, "left": 6, "right": 7, "a": 8, "circle": 8,
       "x": 9, "triangle": 9, "l": 10, "r": 11}

ENV_GET_CAN_DUPE = 3
ENV_SET_PIXEL_FORMAT = 10
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_GET_VARIABLE = 15
ENV_GET_VARIABLE_UPDATE = 17
ENV_GET_LOG_INTERFACE = 27
ENV_GET_SAVE_DIRECTORY = 31
ENV_SET_VARIABLES = 16
ENV_GET_CORE_OPTIONS_VERSION = 52

RETRO_ENV = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
RETRO_VIDEO = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
RETRO_AUDIO = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
RETRO_AUDIO_B = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
RETRO_POLL = C.CFUNCTYPE(None)
RETRO_INPUT = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)
RETRO_LOG = C.CFUNCTYPE(None, C.c_int, C.c_char_p)


class GameInfo(C.Structure):
    _fields_ = [("path", C.c_char_p), ("data", C.c_void_p),
                ("size", C.c_size_t), ("meta", C.c_char_p)]


class Emu:
    def __init__(self, core=CORE, sysdir=SYSDIR):
        self.core = C.CDLL(core)
        self.fmt = 0
        self.frame = None            # (bytes, w, h, pitch)
        self.held = set()
        self.always = set()          # buttons held on top of .held (FF_START)
        self._sys = C.c_char_p(sysdir.encode())
        # Core options. Unanswered, Beetle runs with NO second memory card,
        # which every RetroArch install has - and the v0.6 boot movie hung
        # the BIOS card poll only with two cards (BUG-033), invisible here
        # for four releases. Default to a player's setup; RETRO_OPTIONS
        # points at a RetroArch .opt file to replay someone's exact config.
        self.options = {"beetle_psx_enable_memcard1": "enabled"}
        self._optbuf = {}
        opt = os.environ.get("RETRO_OPTIONS")
        if opt:
            for line in open(opt, encoding="utf-8-sig"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    self.options[k.strip()] = v.strip().strip('"')
        # EMU_SAVE_DIR: the core's save directory (Beetle Saturn keeps its backup
        # RAM there as <image>.bkr, read at load and written at unload) - one
        # per run when several emulators boot the same image at once
        self._save = C.c_char_p(os.path.abspath(os.environ.get("EMU_SAVE_DIR") or "work/emu").encode())
        self._log = RETRO_LOG(self._logmsg)
        self.audio_level = 0               # mean |sample| of the last batch
        self.audio_probe = bool(os.environ.get("AUDIOLOG"))
        self.audio_sink = None             # a bytearray: every batch's samples appended (s16 stereo)

        def batch(d, n):
            if self.audio_sink is not None and n:
                self.audio_sink += C.string_at(C.c_void_p(d), n * 4)
            if self.audio_probe and n:
                buf = C.string_at(C.c_void_p(d), n * 4)
                import array
                a = array.array('h', buf)
                self.audio_level = sum(abs(v) for v in a) // len(a)
            return n
        self._cbs = [RETRO_ENV(self._env), RETRO_VIDEO(self._video),
                     RETRO_AUDIO(lambda l, r: None),
                     RETRO_AUDIO_B(batch),
                     RETRO_POLL(lambda: None), RETRO_INPUT(self._input)]
        c = self.core
        c.retro_set_environment(self._cbs[0])
        c.retro_set_video_refresh(self._cbs[1])
        c.retro_set_audio_sample(self._cbs[2])
        c.retro_set_audio_sample_batch(self._cbs[3])
        c.retro_set_input_poll(self._cbs[4])
        c.retro_set_input_state(self._cbs[5])
        c.retro_init()

    def _logmsg(self, level, fmt):
        # Beetle cores call log_cb unguarded when a disc fails to load; without
        # an interface the pointer is NULL and the process dies inside the core
        try:
            sys.stderr.write("[core] " + fmt.decode(errors="replace"))
        except Exception:
            pass

    def _env(self, cmd, data):
        cmd &= 0xFFFF                      # strip EXPERIMENTAL/PRIVATE bits
        if cmd == ENV_GET_SYSTEM_DIRECTORY:
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(self._sys, C.c_void_p)
            return True
        if cmd == ENV_GET_SAVE_DIRECTORY:
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(self._save, C.c_void_p)
            return True
        if cmd == ENV_SET_PIXEL_FORMAT:
            self.fmt = C.cast(data, C.POINTER(C.c_int))[0]
            return True
        if cmd == ENV_GET_CAN_DUPE:
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        if cmd == ENV_GET_LOG_INTERFACE:
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(self._log, C.c_void_p)
            return True
        if cmd == ENV_GET_CORE_OPTIONS_VERSION:
            # answer 0 so a core takes the old SET_VARIABLES path below
            C.cast(data, C.POINTER(C.c_uint))[0] = 0
            return True
        if cmd == ENV_SET_VARIABLES:
            # {key, "desc; a|b|c"} array, NULL key ends it. Beetle PCE crashes
            # when GET_VARIABLE is refused, so take each option's first value
            # as its default and let self.options override.
            arr = C.cast(data, C.POINTER(C.c_char_p * 2))
            i = 0
            while True:
                ent = arr[i]
                if not ent[0]:
                    break
                key = ent[0].decode()
                val = (ent[1] or b"").decode()
                if key not in self.options:
                    self.options[key] = val.split(";")[-1].strip().split("|")[0]
                i += 1
            return True
        if cmd == ENV_GET_VARIABLE_UPDATE:
            C.cast(data, C.POINTER(C.c_bool))[0] = False
            return True
        if cmd == ENV_GET_VARIABLE and self.options:
            # {key, value}: answer from RETRO_OPTIONS (a RetroArch .opt file),
            # so a boot can be replayed with a player's exact core settings
            var = C.cast(data, C.POINTER(C.c_char_p * 2))[0]
            key = C.string_at(C.cast(data, C.POINTER(C.c_char_p))[0]).decode()
            val = self.options.get(key)
            if val is None:
                return False
            self._optbuf[key] = C.c_char_p(val.encode())
            C.cast(data, C.POINTER(C.c_void_p))[1] = C.cast(self._optbuf[key], C.c_void_p)
            return True
        return False

    def _video(self, data, w, h, pitch):
        if not data:
            return
        buf = C.string_at(data, pitch * h)
        self.frame = (buf, w, h, pitch)

    def _input(self, port, device, index, ident):
        if port == 0 and device == 1 and (ident in self.held or ident in self.always):
            return 1
        return 0

    def load(self, path):
        gi = GameInfo(os.path.abspath(path).encode(), None, 0, None)
        if not self.core.retro_load_game(C.byref(gi)):
            raise SystemExit("retro_load_game failed")
        # Beetle PCE leaves port 0 as DEVICE_NONE until the frontend says
        # otherwise, and then ignores every button: RUN never reached the
        # system card headless.
        self.core.retro_set_controller_port_device(0, 1)

    def load_card(self, path):
        """Put a memory card into the core.

        With the libretro save format the card is exposed as SAVE_RAM and the
        FRONTEND owns the file - a .srm dropped in the save directory is simply
        ignored, which is why headless runs always booted to NO FILE.
        """
        c = self.core
        c.retro_get_memory_data.restype = C.c_void_p
        c.retro_get_memory_size.restype = C.c_size_t
        n = c.retro_get_memory_size(0)
        raw = open(path, "rb").read()
        if len(raw) != n:
            sys.exit(f"{path}: {len(raw)}B, core wants {n}B")
        C.memmove(C.c_void_p(c.retro_get_memory_data(0)), raw, n)

    def save_card(self, path):
        """Write the card back out, so a headless run can mint checkpoints."""
        c = self.core
        c.retro_get_memory_data.restype = C.c_void_p
        c.retro_get_memory_size.restype = C.c_size_t
        n = c.retro_get_memory_size(0)
        open(path, "wb").write(C.string_at(c.retro_get_memory_data(0), n))

    def state(self):
        """Serialize the whole machine, so a run can bookmark where it is."""
        c = self.core
        c.retro_serialize_size.restype = C.c_size_t
        n = c.retro_serialize_size()
        buf = C.create_string_buffer(n)
        if not c.retro_serialize(buf, C.c_size_t(n)):
            raise RuntimeError("retro_serialize failed")
        return buf.raw

    def restore(self, blob):
        c = self.core
        if not c.retro_unserialize(blob, C.c_size_t(len(blob))):
            raise RuntimeError("retro_unserialize failed")

    def run(self):
        self.core.retro_run()

    def image(self):
        from PIL import Image
        import numpy as np
        buf, w, h, pitch = self.frame
        if self.fmt == 1:                       # XRGB8888
            a = np.frombuffer(buf, np.uint8).reshape(h, pitch // 4, 4)[:, :w, :3]
            return Image.fromarray(a[:, :, ::-1])
        a = np.frombuffer(buf, np.uint16).reshape(h, pitch // 2)[:, :w]
        if self.fmt == 2:                       # RGB565
            r = ((a >> 11) & 31) << 3; g = ((a >> 5) & 63) << 2; b = (a & 31) << 3
        else:                                   # 0RGB1555
            r = ((a >> 10) & 31) << 3; g = ((a >> 5) & 31) << 3; b = (a & 31) << 3
        return Image.fromarray(np.dstack([r, g, b]).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--frames", type=int, default=3600)
    ap.add_argument("--script", default=None)
    ap.add_argument("--out", default="work/emu")
    ap.add_argument("--every", type=int, default=0)
    ap.add_argument("--core", default=CORE)
    ap.add_argument("--card", help="memory card to insert (raw 128K)")
    ap.add_argument("--card-out", help="write the card back here at the end")
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
    emu = Emu(a.core)
    emu.load(a.image)
    if a.card:
        emu.load_card(a.card)
        print(f"card in: {a.card}")
    print(f"loaded {a.image}, pixel format {emu.fmt}")
    for f in range(a.frames):
        for act in events.get(f, []):
            if act.startswith("press:"):
                emu.held = {BTN[b] for b in act[6:].split("+")}
            elif act == "release":
                emu.held = set()
            elif act.startswith("shot"):
                emu.image().save(os.path.join(a.out, f"f{f:06d}.png"))
                print(f"  shot at {f}")
            elif act == "quit":
                break
        emu.run()
        if a.every and f % a.every == 0 and emu.frame:
            emu.image().save(os.path.join(a.out, f"f{f:06d}.png"))
    if emu.frame:
        emu.image().save(os.path.join(a.out, "final.png"))
    if a.card_out:
        emu.save_card(a.card_out)
        print(f"card out: {a.card_out}")
    print("done")


if __name__ == "__main__":
    main()
