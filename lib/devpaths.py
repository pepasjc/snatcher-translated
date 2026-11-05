"""Machine-specific paths and hosts for the dev tools (harness, save helpers).

    import devpaths
    card = devpaths.get("SNATCHER_CARD")              # None when not configured
    host = devpaths.need("MISTER_HOST", "pushing a save to the MiSTer")

A value comes from the environment first, then from local_paths.json at the
repository root (git-ignored: copy local_paths.example.json and fill in what
you use). Nothing here is needed to build the patches.

Keys: MISTER_HOST (user@address of a MiSTer, for the push/pull helpers),
SNATCHER_CARD (a DuckStation memory card the harness reads), SNATCHER_RA
(a RetroArch install folder), RETROARCH (its retroarch.exe), BIOS_DIR (the
PlayStation / Saturn BIOS folder the headless emulator host passes to the
cores), RETRO_CORES (the folder holding the libretro cores).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FILE = os.path.join(ROOT, "local_paths.json")
_conf = None


def _load():
    global _conf
    if _conf is None:
        _conf = json.load(open(FILE, encoding="utf-8")) if os.path.exists(FILE) else {}
    return _conf


def get(key, default=None):
    v = os.environ.get(key)
    if v:
        return v
    return _load().get(key) or default


def need(key, what):
    v = get(key)
    if not v:
        sys.exit(f"{what} needs {key}: set it in the environment or in {FILE}")
    return v


def retro_cores():
    """The libretro cores folder: RETRO_CORES, else the EmuDeck / RetroArch default."""
    d = get("RETRO_CORES")
    if d:
        return d
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "emudeck", "Emulators", "RetroArch", "cores") if appdata \
        else os.path.expanduser("~/.config/retroarch/cores")
