"""Who is in a VDP1 face slot: the portrait chunks, labelled, and a pixel signature per chunk.

The room script loads a portrait chunk (DATA.BIN, LZ3, one type-3 section of 8-bpp pixels
per face set) into a resource record (op 0F) and copies the section into a VDP1 slot (op
17) and its sprite index into a structure buffer (op 18); a column then shows that slot
(op 21). Which slot holds whom differs per room (Harry sits on slot 5 in B080's Mechanic
room, Mika on 5 at the reception, Catherine on 5 in Gibson's home), and a REEL card names no
voice line the script could be asked about - so the payload names a column by CONTENT: the
16 bytes at SIG_OFF into its slot (CMDSRCA base * 8 + SIG_OFF in VDP1 VRAM) against this
table, which the blob carries per bank ({u16 character, u16 0, 16 bytes} records, 0 ends).
The chunks were labelled by eye from their base sprites (work/saturn/faces/sheets/
faces_montage.png, 2026-09-16); `python saturn/subs/facechunks.py` prints the table and
checks that no two characters share a signature.
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ("lib", "saturn/tools")]

# character ids the cue files carry (`face_char`) and the blob's records use; 0 = none
CHARS = {"Gillian": 1, "Mika": 2, "Chief": 3, "Harry": 4, "Metal Gear": 5, "Catherine": 6,
         "Randam": 7, "Teller": 8, "Madnar": 9, "Ivan": 10, "Napoleon": 11, "Chin": 12, "Jamie": 13,
         "Cook": 14, "Woman": 15}

# portrait chunk -> character: every chunk on the disc whose sprite index has a list of the
# band's face size (72-96 x 56-80), labelled from its base sprite; the room scripts copy
# them into the slots (the scan in work/saturn/faces/faceloads.py misses a few: 546 is
# copied from a record another load overwrote first). Where a chunk loads decides the
# doubtful ones: 569 in B0D0 (Altamira, the Teller), 572 in B0E0 (Joy Division's Cook).
CHUNK_CHAR = {524: "Gillian", 525: "Gillian", 526: "Gillian", 527: "Gillian", 528: "Gillian",
              529: "Gillian", 530: "Gillian", 531: "Gillian", 532: "Gillian", 533: "Gillian",
              534: "Gillian", 535: "Gillian", 536: "Gillian", 537: "Gillian", 538: "Gillian",
              539: "Gillian",
              540: "Mika", 541: "Mika",
              542: "Chief", 543: "Chief",
              544: "Harry", 545: "Harry", 546: "Harry",
              547: "Metal Gear", 548: "Metal Gear", 549: "Metal Gear", 573: "Metal Gear",
              550: "Catherine", 551: "Catherine", 552: "Catherine",
              553: "Randam", 554: "Randam", 555: "Randam", 556: "Randam", 557: "Randam",
              558: "Randam", 559: "Randam",
              560: "Jamie", 561: "Jamie", 562: "Jamie", 563: "Jamie",
              564: "Madnar", 565: "Ivan", 566: "Napoleon", 567: "Napoleon", 568: "Chin", 569: "Teller",
              570: "Woman", 571: "Woman", 572: "Cook"}
# not portraits: 366-368 (an icon), 397/487 (partial close-ups). 566 is Napoleon in his
# wolf mask (Outer Heaven, Act 2: B1D0's band cards; the regression's WRONG-FACE on every
# one of his lines there until it was labelled, 2026-11-06)

SIG_OFF, SIG_LEN = 0x800, 16
CACHE = os.path.join(WORK, "saturn", "build", "face_sigs.json")


def signatures(chunk):
    """{section index: 16 bytes} for every type-3 section of a chunk."""
    import satgfx
    dec = satgfx.load(chunk)
    out = {}
    for i, (t, o, s) in enumerate(satgfx.parse(dec)):
        if t == 3 and s >= SIG_OFF + SIG_LEN:
            out[i] = dec[o + SIG_OFF:o + SIG_OFF + SIG_LEN]
    return out


def sig_table(refresh=False):
    """[(character id, signature bytes)], one per (chunk, type-3 section), cached in
    work/saturn/build/face_sigs.json (the chunks are pristine game data: stable)."""
    if not refresh and os.path.exists(CACHE):
        rows = json.load(open(CACHE))
        # the cache stands while it was made from exactly these labels (a new label rebuilds it)
        if {r["chunk"]: r["name"] for r in rows} == CHUNK_CHAR:
            return [(r["char"], bytes.fromhex(r["sig"])) for r in rows]
    rows = []
    for chunk, name in sorted(CHUNK_CHAR.items()):
        for sec, sig in signatures(chunk).items():
            rows.append({"chunk": chunk, "sec": sec, "char": CHARS[name], "name": name, "sig": sig.hex()})
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(rows, open(CACHE, "w"), indent=1)
    return [(r["char"], bytes.fromhex(r["sig"])) for r in rows]


def check(rows):
    """No signature may name two characters (the same character twice is fine)."""
    by = {}
    for ch, sig in rows:
        by.setdefault(sig, set()).add(ch)
    bad = {sig.hex(): chars for sig, chars in by.items() if len(chars) > 1}
    assert not bad, f"face signatures shared between characters: {bad}"
    zero = [ch for ch, sig in rows if not any(sig)]
    assert not zero, f"blank signatures (SIG_OFF outside the pixels) for characters {zero}"


def pack(rows):
    """The blob's table: {u16 char, u16 0, 16 bytes} per row, a 0 word ends it."""
    import struct
    out = b"".join(struct.pack(">HH", ch, 0) + sig for ch, sig in rows)
    return out + b"\0\0\0\0"


def char_of(sig, rows=None):
    """The character (name) whose chunk carries `sig`, or None."""
    rows = rows or sig_table()
    names = {v: k for k, v in CHARS.items()}
    for ch, s in rows:
        if s == sig:
            return names[ch]
    return None


if __name__ == "__main__":
    rows = sig_table(refresh="--refresh" in sys.argv)
    check(rows)
    names = {v: k for k, v in CHARS.items()}
    for r in json.load(open(CACHE)):
        print(f"chunk {r['chunk']} sec {r['sec']}: {r['name']:10} {r['sig']}")
    print(f"{len(rows)} signatures, {len(pack(rows))} bytes per blob, {len(set(ch for ch, _ in rows))} characters")
