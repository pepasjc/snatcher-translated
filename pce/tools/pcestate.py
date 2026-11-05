"""Read a Beetle PCE (mednafen) savestate: the machine's memories by name.

The libretro core's serialize blob is mednafen's own MDFNSVST container. After
the 32-byte header every variable is `{namelen byte, name, u32 size, data}`,
so the interesting memories are simply named:

  BaseRAM     0x2000   the HuC6280's work RAM  (CPU $2000-$3FFF)
  VRAM        0x10000  VDC video RAM, 16-bit words, planar 8x8 tiles
  CDRAM       0x10000  CD-ROM^2 RAM
  SysCardRAM  0x30000  Super System Card's 192 KB - Snatcher's scripts live here
  ADPCM.RAM   0x10000
  SaveRAM     0x800    the BRAM save file

Usage:
  python pce/tools/pcestate.py <state.mdf> [name ...]     # dump to work/pce/
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

WANTED = ("BaseRAM", "VRAM", "CDRAM", "SysCardRAM", "ADPCM.RAM", "SaveRAM")


_AT = {}          # (state length, name) -> (offset of the name's length byte, data start, size)


def sections(blob, wanted=WANTED):
    """{name: bytes} for every wanted variable found in the state. The layout of one core's
    states does not move, so a variable found once is read straight from its place after
    (its name checked there) - the scan took 3 ms a call, and the harness reads every frame."""
    out = {}
    for name in wanted:
        at = _AT.get((len(blob), name))
        if at is not None:
            o, start, size = at
            if blob[o] == len(name) and blob[o + 1:o + 1 + len(name)] == name.encode():
                out[name] = blob[start:start + size]
    if len(out) == len(wanted):
        return out
    out = {}
    for m in re.finditer(rb'[\x03-\x10]([A-Za-z][A-Za-z0-9_.]{2,15})', blob):
        o = m.start()
        nl = blob[o]
        name = blob[o + 1:o + 1 + nl]
        if len(name) != nl:
            continue
        try:
            name = name.decode()
        except UnicodeDecodeError:
            continue
        if name not in wanted or name in out:
            continue
        size = int.from_bytes(blob[o + 1 + nl:o + 5 + nl], "little")
        if o + 5 + nl + size <= len(blob):
            out[name] = blob[o + 5 + nl:o + 5 + nl + size]
            _AT[(len(blob), name)] = (o, o + 5 + nl, size)
    return out


def inject(blob, name, offset, data):
    """The state with `data` written into variable `name` at `offset` (same size; the
    container has no checksum). A savestate carries the image's files as loaded - the
    resident rec 110 and rec 54 - so a rebuilt one is tested on an old state this way."""
    for m in re.finditer(rb'[-]([A-Za-z][A-Za-z0-9_.]{2,15})', blob):
        o = m.start()
        nl = blob[o]
        if blob[o + 1:o + 1 + nl] != name.encode():
            continue
        size = int.from_bytes(blob[o + 1 + nl:o + 5 + nl], "little")
        start = o + 5 + nl
        assert offset + len(data) <= size, (offset, len(data), size)
        return blob[:start + offset] + bytes(data) + blob[start + offset + len(data):]
    raise KeyError(name)


def main():
    blob = open(sys.argv[1], "rb").read()
    names = sys.argv[2:] or list(WANTED)
    outdir = os.path.join(WORK, "pce")
    os.makedirs(outdir, exist_ok=True)
    for name, data in sections(blob, tuple(names)).items():
        path = os.path.join(outdir, name.replace(".", "_").lower() + ".bin")
        open(path, "wb").write(data)
        print(f"{name:12} {len(data):#8x} -> {path}")


if __name__ == "__main__":
    main()
