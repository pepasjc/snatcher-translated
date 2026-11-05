"""Which portrait belongs to a voice line: the room script's own face ops.

The scene bank's bytecode only plays the voice (`c0 04 e4 00 00 07 xx`); the
band, the columns and the mouth animation are the ROOM script - DATA.BIN chunk
60 + N, loaded raw to 0x002A0000 and run by a second u16-opcode interpreter
(0x060B81B0). Its event table carries one `59 <voice id> <u32 addr>` entry per
voice line (op 0x59 = "if [0x060F2A10] == id, jump"), and the block at that
address sets the faces up (work/saturn/faces/FINDINGS.md, 2026-09-15):

    21 col face buf slot 0 1 2   show column `col`  (x = 24 + 96*col)
    3e / 4b col ...              the same column set-up at x = 0x7000: a HIDDEN
                                 column, there only so its mouth-id list carries
                                 the voice (the animator still runs it)
    36 col voice                 append `voice` to the column's mouth-id list
    22                           open the band

A column is three cels (objects 1+3c/2+3c/3+3c at ctx+0x830 + 76n). Op 0x21's
arguments, measured against the live objects (the Chief's room and the
Mechanic room, subs_run's `faces=` log): the structure buffer is the THIRD
argument (0x060E4C00[buf]) and the VDP1 face slot the fourth
(0x060E4C24[slot]) - the same number in every B010 block; `face` is only the
palette byte 4*face - 24 (a first pass read it as the buffer index and Mika's
dressed column drew nothing at all: work/saturn/faces/step2_reception). The same
character takes a different (slot, buffer) per room, so residency is per room,
not per character.

`harvest(scene)` returns, per voice id, what the script does for that line and
- for a line whose speaker the script hides - the (slot, buffer, palette) of
that speaker's face in the same room, taken from the NEAREST dispatch entry in
the script that shows the same speaker (rooms' lines sit together in the
script; the reception's hidden Mika lines 199/227 are 0x11e from her shown
202, the Mechanic room's hidden Harry lines from his shown 232). The cue file
keeps the result (`face`, `face_src`) - the JSON is the shipped truth and a
wrong guess is a one-line fix there.

    python saturn/subs/roomfaces.py B010        the table, with the cue speakers
"""
import os, sys, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'ps1/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]

import satdata

BASE = 0x2A0000
ROOM_CHUNK0 = 60                  # chunk 60 + scene index (bank 21 + index)
MAX_DIST = 0x2000                 # how far in the script a residency witness may sit

# op -> length in bytes (work/saturn/faces/op_tails.txt: the handlers' returns)
LEN = {0x01: 10, 0x02: 6, 0x03: 6, 0x05: 16, 0x06: 12, 0x07: 4, 0x08: 4, 0x09: 4, 0x0e: 2, 0x0f: 6, 0x11: 8,
       0x13: 4, 0x14: 12, 0x15: 12, 0x16: 8, 0x17: 8, 0x18: 8, 0x10: 2, 0x1b: 30, 0x1c: 8, 0x1e: 8, 0x1f: 2, 0x20: 2,
       0x21: 16, 0x22: 2, 0x24: 2, 0x26: 12, 0x27: 10, 0x29: 2, 0x2b: 10, 0x2d: 8, 0x2e: 8, 0x2f: 4, 0x30: 8,
       0x32: 2, 0x33: 14, 0x34: 2, 0x35: 2, 0x36: 6, 0x37: 4, 0x39: 2, 0x3a: 10, 0x3b: 10, 0x3d: 4, 0x3e: 16,
       0x3f: 4, 0x40: 6, 0x43: 6, 0x44: 4, 0x45: 2, 0x47: 4, 0x48: 2, 0x49: 4, 0x4a: 4, 0x4b: 14, 0x4d: 4,
       0x4f: 6, 0x50: 4, 0x51: 4, 0x57: 6, 0x58: 6, 0x59: 8, 0x5a: 2, 0x5d: 6, 0x5f: 4, 0x60: 2, 0x62: 4,
       0x63: 4, 0x64: 2, 0x68: 2, 0x69: 4, 0x6a: 4}
JUMPS = {0x0d, 0x19, 0x1a, 0x53, 0x54, 0x55, 0x56, 0x67}
COND = {0x59: 8, 0x5b: 10, 0x5c: 10, 0x25: 8, 0x28: 8, 0x38: 8, 0x41: 8, 0x42: 8, 0x0c: 4}
CALL = 0x3c


def u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def room_script(scene_no):
    """The room script of scene `scene_no` (B010 = 1), raw, as loaded at 0x002A0000."""
    ents = satdata.read_table()
    d = open(satdata.DATA, "rb").read()
    return satdata.entry(d, ents, ROOM_CHUNK0 + scene_no)


def decode_block(d, off, maxops=60):
    out = []
    for _ in range(maxops):
        if off + 2 > len(d):
            break
        op = u16(d, off)
        if op in JUMPS:
            break
        if op == CALL:
            tgt = (u16(d, off + 4) << 16 | u16(d, off + 6)) - BASE
            out += [x for x in decode_block(d, tgt, maxops) if x[1] != 0x29]
            off += 8
            continue
        if op == 0x29:
            break
        n = COND.get(op) or LEN.get(op)
        if not n:
            break
        out.append((off, op, [u16(d, off + 2 + 2 * i) for i in range((n - 2) // 2)]))
        off += n
    return out


def dispatch(d):
    """[(voice id, target offset, entry offset)] for every `59 <voice> <addr>`."""
    return [(u16(d, o + 2), u16(d, o + 6), o) for o in range(0, len(d) - 8, 2)
            if u16(d, o) == 0x59 and 0x700 <= u16(d, o + 2) < 0xB00 and u16(d, o + 4) == 0x002A]


def face_of(args):
    """Op 0x21/0x3E arguments -> {slot, bufi, pal, face, col}.

    Measured against the live cels (the harness's speaker gate compares every
    shown card's portrait with this): args[2] is the structure-buffer index
    (0x060E4C00[buf]) and args[3] the VDP1 slot (0x060E4C24[slot]) - the two are
    the same number in every B010 block - and `face` is the palette byte
    4*face - 24, not an identity (Gillian is face 7 in the Chief's room and 8 in
    the Mechanic room)."""
    col, face, buf, slot = args[0], args[1], args[2], args[3]
    return dict(col=col, face=face, slot=slot, bufi=buf, pal=4 * face - 24)


def entries(scene_no):
    """Per voice id: {voice, addr, shown, hidden, ids, band} in script order (first wins)."""
    d = room_script(scene_no)
    out, seen = [], set()
    for voice, tgt, o in dispatch(d):
        if (voice, tgt) in seen:
            continue
        seen.add((voice, tgt))
        shown, hidden, ids, band = [], [], [], False
        for _off, op, args in decode_block(d, tgt):
            if op == 0x21:
                shown.append(face_of(args))
            elif op in (0x3e, 0x4b):
                hidden.append(args[0] if op == 0x3e else args[0])
            elif op == 0x36:
                ids.append((args[0], args[1]))
            elif op == 0x22:
                band = True
        out.append(dict(voice=voice, addr=o, shown=shown, hidden=hidden, ids=ids, band=band))
    return out


def harvest(scene_no, speaker_of):
    """{voice id: {face: [slot, bufi, pal], face_src, band, shown}} for a scene.

    `speaker_of(voice)` gives the cue file's speaker name (the script names no
    one). A line whose own op 0x21 shows a column carries that column's face
    ("own"); a line with no shown column takes the nearest same-speaker witness
    in the script (its voice id goes in `face_src`), within MAX_DIST bytes."""
    ents = entries(scene_no)
    witness = {}          # speaker -> [(addr, face dict)]
    for e in ents:
        spk = speaker_of(e["voice"])
        if spk and e["shown"]:
            witness.setdefault(spk, []).append((e["addr"], e["shown"][0]))
    out = {}
    for e in ents:
        spk = speaker_of(e["voice"])
        rec = dict(band=e["band"], shown=bool(e["shown"]), speaker=spk, face=None, face_src=None, dist=None)
        if e["shown"]:
            f = e["shown"][0]
            rec.update(face=[f["slot"], f["bufi"], f["pal"]], face_src="own")
        elif spk and witness.get(spk):
            addr, f = min(witness[spk], key=lambda w: abs(w[0] - e["addr"]))
            if abs(addr - e["addr"]) <= MAX_DIST:
                src = next(x["voice"] for x in ents if x["addr"] == addr)
                rec.update(face=[f["slot"], f["bufi"], f["pal"]], face_src=src - 0x700, dist=abs(addr - e["addr"]))
        out[e["voice"]] = rec
    return out


def witnesses(scene_no, speaker_of):
    """({speaker: [(script addr, face dict)]} over the lines whose op 0x21 shows a
    column, {voice id: script addr}) - for a REEL cue, which names no line: its
    speaker's witness nearest the neighbouring mono line's entry."""
    ents = entries(scene_no)
    wit, addr = {}, {}
    for e in ents:
        addr[e["voice"]] = e["addr"]
        spk = speaker_of(e["voice"])
        if spk and e["shown"]:
            wit.setdefault(spk, []).append((e["addr"], e["shown"][0]))
    return wit, addr


def main(argv):
    import json
    scene = argv[0] if argv else "B010"
    no = int(scene[1:], 16) // 0x10
    spec = json.load(open(os.path.join(ROOT, "saturn", "translation", f"subs_{scene}.json"), encoding="utf-8"))
    spk = {}
    for c in spec["cues"]:
        if "line" in c:
            spk.setdefault(0x700 + c["line"], c.get("speaker", ""))
    h = harvest(no, lambda v: spk.get(v, ""))
    for voice in sorted(h):
        r = h[voice]
        print(f"voice {voice:#06x} ({voice - 0x700:3d}) {r['speaker'] or '?':11s} band={int(r['band'])} "
              f"shown={int(r['shown'])} face={r['face']} src={r['face_src']}"
              + (f" (+{r['dist']:#x})" if r["dist"] else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
