"""Saturn cue files from the PS1's: re-time each card onto its Saturn voice line.

The PS1 cue (ps1/translation/subs_<S>.json) keys a card on an XA stream
(file, chan) and an absolute sector window [start, end) inside it. The
Saturn plays the same recording as ACTn.CAT line `idx` (voice_map.json: the
envelope-matched bijection PS1 stream -> Saturn line) and reports its
progress as ADPCM bytes decoded (u32 0x060EA2BC, 11,025 B/s: 22,050 samples/s
at 4 bits). So a card's window becomes a byte window on the line:

    f0 = (start - stream.start) / (stream.end - stream.start)      (master_lines.json)
    b0 = round(f0 * line.size)   b1 = round(f1 * line.size)         (voice table)

and the payload shows the card while b0 <= decoded < b1. The last card of
a line ends at `size` (the decoder stops there).

Stereo-reel cues (the S000 cinematics: `f5`, `fly`..., and EVERY B020
line - the factory sequence is reels) play on the Saturn as SDAIF_nn.AIF
streams (work/saturn/cat/reel_map.json: PS1 S000 index -> `n`). A PS1
(file, chan) names a stream in EITHER XA file, so a cue whose sector
window lies outside the mono stream's span is a reel cue (B020's `f2_0` at
65311 is S000[8], not M000[32]). The stream player keeps the live stream
number at u16 0x060EFE6A, 1 at u32 0x060EFE64 while playing, and the bytes
of the FILE played so far at u32 0x060EFF0C (both counters reset to 0 the
frame after a switch; the newsreel SDAIF_E0, 30 kHz stereo 16-bit, ends at
18,154,366 of 18,154,436 bytes) - measured on the opening, work/saturn/
pack_check/probe_reel2.py. So a reel cue is {reel: n, b0, b1} in file
bytes: 54 (the SSND data offset of every SDAIF) + fraction x frames x 4,
with the frame count and rate from the AIFF's COMM chunk; the blob keys it
on the stream number (sector 0xFFFF).

Text: the card is wrapped twice with the Saturn pair table
(work/saturn/pair_table_sat.json, so a pair without a glyph slot counts its
two fullwidth cells): `rows` for the band layout (the face at the left of the
box, text beside it: 14 cells x 3 rows from column 6) and `rows_plain` for
the plain box (no band up: the nameplate in row 0 in the speaker's colour,
text from row 1, 18 cells x 3 rows; 4 rows from row 0 when the cue has no
speaker). `colour` is the nameplate's colour index (names.json's ＠ colour:
blue 1, red 2, purple 3, green 4, cyan 5, yellow 6, white 7 - the byte the
engine's layout stores per cell). The payload picks the layout at runtime
from the engine's state (satsubs.py).

    python saturn/subs/gen_subs.py B010 [B020 ...]     -> saturn/translation/subs_<S>.json
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]

import satcat
import roomfaces
from satapply import SatPairFont

PS1_SUBS = os.path.join(ROOT, "ps1", "translation")
OUT_DIR = os.path.join(ROOT, "saturn", "translation")
VOICE_MAP = os.path.join(ROOT, "saturn", "translation", "voice_map.json")
MASTER = os.path.join(WORK, "master_lines.json")
SAT_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")
BYTES_PER_S = 11025
COLS, ROWS, COL0 = 14, 3, 6           # the band layout: text beside the face (3 rows: row 3 kept clear)
# PS1 chain cues (chan 254: a VAG line with no CD signature, fired N frames after its
# anchor cue draws) name no stream, but the Saturn plays that recording as an ordinary
# ACT line - which one, per anchor: the PS1 stream the VAG's audio matches in
# voice_map.json. The chain's cards share the line in proportion to their frame windows.
CHAINS = {
    "B010": {"B010_017": "XAS_M000.XA[148]"},     # the Chief's JUNKER ID handover after 'That's the gist of your assignment.' (B010_037/037b)
}
# PS1 banks the Saturn folds into another chunk: none. Chunk 41 = B140 (a 902-byte
# stub) IS its own scene (#53), so is chunk 54 = B210 (3 records: the reconstruction
# loads it and ran 45,000 frames with B200's blob dead - 2026-09-17,
# work/saturn/auto/B200_5) and so is chunk 59 = B260 (2 records: the church's last
# battle, the ending and the airport run under it - the whole ending drew 6 cards with
# its cues in B250's blob, work/saturn/auto/B250_4).
MERGED = {}
# Saturn lines a different bank plays than the PS1 cue file that holds them: line ->
# (the bank whose bytecode plays it, the PS1 cue file). Gillian's "so where's this stand
# supposed to be" after the fortune teller (line 87) closes B0D0's teller scene on the
# Saturn; the PS1's BUG-010 put XAS_M000 file 19 into B0E0's cues, and the band opened
# empty (#97, 2026-10-20).
LINE_HOME = {87: ("B0D0", "B0E0")}
# Reel-only scenes have no voice-id events, so roomfaces finds no witness for anyone:
# the speaker -> [slot, buffer, palette] of their columns, read off the room script's op
# 0x21s and the arrival's captures (B020: three columns, 4/5/6 - see CLAUDE.md)
# REEL_FACES (a per-scene speaker -> [slot, buffer, palette] table for reel-only scenes) is
# gone since 2026-09-16: reel cues carry the character (facechunks.CHARS) and the payload
# names the columns by their slot pixels - the slots differ per room, and the table put
# the ruins' Metal Gear cards on the plain card in every room but the arrival's.
SUBTITLED = [b for b in ["B010", "B020", "B060", "B070", "B080", "B0C0", "B0D0", "B0E0", "B0F0", "B100", "B110", "B120",
                         "B130", "B140", "B150", "B170", "B180", "B190", "B1A0", "B1B0", "B1C0", "B1D0", "B1E0", "B1F0", "B200",
                         "B210", "B220", "B230", "B240", "B250", "B260"]]      # every Saturn scene with cues (the PS1's 30; B140 = chunk 41, B210 = chunk 54 and B260 = chunk 59 are their own scenes)
PLAIN_COLS, PLAIN_ROWS = 18, 3        # the plain box: nameplate row 0, text rows 1-3 (4 rows without a speaker)
NAMES = os.path.join(ROOT, "saturn", "translation", "names.json")
COLOUR_INDEX = {"青": 1, "赤": 2, "紫": 3, "緑": 4, "水": 5, "黄": 6, "白": 7}


# speakers the Saturn's own name table lacks (their name-card came out white): the
# colour is ours to pick - red is nobody's in the ending (Jamie yellow, Gillian green,
# Metal Gear blue, Randam purple) and marks the villain (#68, 2026-09-17)
EXTRA_COLOURS = {"Madnar": 2,
                 # 2026-09-17, "names without colour": Chin's reel and Gibson's tape play
                 # beside Gillian (green), Metal Gear (blue) and Catherine (purple) - cyan
                 # is Harry's, absent from both; the fortune teller takes Mika's purple
                 # (the PS1 gives her Mika's pink). TV, Cook, Thug and Waiter stay the
                 # game's white for bit parts (Clerk, Man, Woman are white in its table).
                 "Chin": 5, "Gibson": 5, "Teller": 3}


# Lines whose speaker the room script HIDES (the column only carries the voice id: B260's
# throne, where Madnar's mouth moves on chunk 125's throne picture in slot 0) while the
# speaker's portrait is resident, with no witness roomfaces can find (#68). Madnar's chunk
# 564 sits in slot 6 / buffer 6, palette 12 (the script's op 0x21 face 9) from line 864 on;
# 859/862 come before it loads (slot 6 = Gillian), 903/911/912 name no column, 998 has
# Randam in slot 6 - those stay nameplate cards. Measured in work/saturn/issues/68.
RESIDENT_FACES = {"B260": {"Madnar": ([6, 6, 12], {868, 869, 893, 949, 951})}}

# Reel narration read in a character's voice: the speakerless cards (no nameplate, the
# narration colour) of that scene's reels carry the character's portrait. The Act 2
# opening's recap (B140, reels 151/152) is the Chief reading the report: the engine shows
# his column through the narration and animates its mouth (objects 7-9; Metal Gear's
# column moves only for his own line), the narration's pitch is the Chief's (~130-150 Hz
# against Metal Gear's ~280). Without it the footage narration drew the face layout beside
# an empty window (the Chief at 216, parked) and the bounty hunter passage kept the
# Chief/Metal Gear faces of its old labels (#101, 2026-10-21; work/saturn/issue101).
NARRATOR_FACES = {"B140": "Chief"}


def name_colours():
    """English speaker name -> the engine's colour byte, from names.json (+ EXTRA_COLOURS)."""
    out = dict(EXTRA_COLOURS)
    for n in json.load(open(NAMES, encoding="utf-8"))["names"]:
        out.setdefault(n["en"], COLOUR_INDEX.get(n["colour"], 7))
    return out


def pair_font():
    return SatPairFont(json.load(open(SAT_TABLE)))


def cells(pf, text):
    """Cells a text occupies (pairs, fallbacks and fullwidth chars)."""
    return len(pf.encode(text)) // 2


def wrap(pf, text, cols=COLS, rows=ROWS):
    """Greedy word wrap into rows of <= cols cells; raises when it needs more rows."""
    words = text.split()
    out, cur = [], ""
    for w in words:
        cand = (cur + " " + w) if cur else w
        if cells(pf, cand) <= cols:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = w
            if cells(pf, cur) > cols:
                raise ValueError(f"word wider than {cols} cells: {w!r}")
    if cur:
        out.append(cur)
    if len(out) > rows:
        raise ValueError(f"{text!r} needs {len(out)} rows")
    return out


REEL_MAP = os.path.join(WORK, "saturn", "cat", "reel_map.json")
SDAIF_DIR = os.path.join(ROOT, "discs", "extracted_saturn")
SSND_DATA = 54                          # FORM(12) + COMM(8+18) + SSND header (8+8)


def aiff_info(path):
    """(frames, rate, channels, bytes per frame) from an SDAIF's COMM chunk."""
    import struct
    h = open(path, "rb").read(64)
    assert h[:4] == b"FORM" and h[8:16] == b"AIFFCOMM", path
    ch, frames, bits = struct.unpack_from(">hIh", h, 20)
    exp = struct.unpack_from(">H", h, 28)[0]
    mant = struct.unpack_from(">Q", h, 30)[0]
    rate = int(round(mant / 2 ** (16383 + 63 - exp)))
    return frames, rate, ch, ch * bits // 8


def add_faces(scene, log=print):
    """Stamp every BAND cue with its speaker's portrait in that room, in place.

    The room script (roomfaces.py), not the bank bytecode, sets the faces up: a
    cue whose line the script shows on a column takes that column's (VDP1 slot,
    structure buffer, palette byte) - `face_src: "own"` - and a cue whose
    speaker the script HIDES takes the nearest line in the script that shows the
    same speaker (`face_src` = that line). The payload uses the second kind (it
    dresses the hidden column); the first is what the harness's speaker gate
    checks the drawn portrait against. Lines the script gives no band get no
    face: their card is the plain box, and a witness from another room would be
    wrong anyway (Mika's reception lines 203/205 would take the Mechanic room's).

    The cue file is the shipped truth, so this EDITS it and leaves everything
    else - unlike convert(), which writes it from the PS1 cues."""
    path = os.path.join(OUT_DIR, f"subs_{scene}.json")
    spec = json.load(open(path, encoding="utf-8"))
    scene_no = int(scene[1:], 16) // 0x10
    spk = {}
    for c in spec["cues"]:
        if "line" in c:
            spk.setdefault(0x700 + c["line"], c.get("speaker", ""))
    h = roomfaces.harvest(scene_no, lambda v: spk.get(v, ""))
    wit, addr = roomfaces.witnesses(scene_no, lambda v: spk.get(v, ""))
    n, hidden, reels = 0, 0, 0
    near = None                          # the last mono line seen: a reel plays in its room
    import facechunks
    for c in spec["cues"]:
        c.pop("face", None)
        c.pop("face_src", None)
        c.pop("face_char", None)
        if "line" in c:
            near = 0x700 + c["line"]
        r = h.get(0x700 + c["line"]) if "line" in c else None
        res = RESIDENT_FACES.get(scene, {}).get(c.get("speaker"))
        if res and c.get("line") in res[1]:
            # overrides an "own" stamp too: 949's is the block's first column, Gillian's slot
            c["face"], c["face_src"] = list(res[0]), "resident"
            n += 1
            hidden += 1
        elif r and r["band"] and r["face"]:
            c["face"], c["face_src"] = r["face"], r["face_src"]
            n += 1
            hidden += r["face_src"] != "own"
        elif "reel" in c and c.get("speaker") in facechunks.CHARS:
            # a reel names no line, and which slot holds the speaker differs per room: the
            # cue carries the CHARACTER and the payload names the shown columns by their
            # slot's pixels (facechunks: the chunk signatures ride in the blob). Until
            # 2026-09-16 a per-scene table / the nearest witness guessed the slot, and the
            # ruins' Metal Gear cards and B080's debrief drew with the wrong or no portrait.
            c["face_char"] = facechunks.CHARS[c["speaker"]]
            n += 1
            reels += 1
        elif "reel" in c and not c.get("speaker") and scene in NARRATOR_FACES:
            c["face_char"] = facechunks.CHARS[NARRATOR_FACES[scene]]     # the narrator's portrait (#101)
            n += 1
            reels += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    log(f"{scene}: {n} of {len(spec['cues'])} cues carry a face ({hidden} for a speaker the script hides, {reels} on reels by character) -> {path}")
    return spec


def convert(scene, log=print):
    src = json.load(open(os.path.join(PS1_SUBS, f"subs_{scene}.json"), encoding="utf-8"))
    for extra in MERGED.get(scene, []):          # the folded PS1 banks' cues after the host's
        src["cues"] += json.load(open(os.path.join(PS1_SUBS, f"subs_{extra}.json"), encoding="utf-8"))["cues"]
    vm = {(v["file"], v["chan"]): v for v in json.load(open(VOICE_MAP))}
    for line, (home, ps1) in LINE_HOME.items():  # lines this bank plays from another bank's cue file
        if home == scene:
            src["cues"] += [c for c in json.load(open(os.path.join(PS1_SUBS, f"subs_{ps1}.json"), encoding="utf-8"))["cues"]
                            if vm.get((c["file"], c["chan"]), {}).get("idx") == line]
    ml = {m["key"]: m for m in json.load(open(MASTER, encoding="utf-8"))}
    reels = {r["ps1"]: r for r in json.load(open(REEL_MAP))}
    s_streams = [m for m in ml.values() if m["xa"] == "S"]
    align_path = os.path.join(WORK, "saturn", "cat", "reel_align.json")
    aligned = json.load(open(align_path)) if os.path.exists(align_path) else {}
    table = satcat.table()
    pf = pair_font()
    colours = name_colours()
    cues, skipped = [], []
    unknown = set()
    chains = {}
    for b in [scene] + MERGED.get(scene, []):
        chains.update(CHAINS.get(b, {}))
    groups = {}                                  # anchor -> its chain cues, for the frame -> byte split
    for c in src["cues"]:
        if c.get("enabled", True) and c.get("chan", 0) == 254 and c.get("anchor") in chains:
            groups.setdefault(c["anchor"], []).append(c)
    by_ps1 = {v["ps1"]: v for v in vm.values()}
    for c in src["cues"]:
        if not c.get("enabled", True):
            continue
        v = vm.get((c["file"], c["chan"]))
        if c.get("chan", 0) == 254:
            if c.get("anchor") not in chains:
                skipped.append(c["id"])      # a chain cue (VAG on the PS1) with no Saturn line named
                continue
            g = groups[c["anchor"]]
            g0, g1 = min(x["start"] for x in g), max(x["end"] for x in g)
            v = by_ps1[chains[c["anchor"]]]
            rec = table[v["idx"]]
            f0, f1 = (c["start"] - g0) / (g1 - g0), (c["end"] - g0) / (g1 - g0)
            speaker = c.get("speaker", "")
            if speaker and speaker not in colours:
                unknown.add(speaker)
            cues.append({
                "id": c["id"], "line": v["idx"], "act": rec["act"], "sector": rec["sector"],
                "offset": rec["offset"], "size": rec["size"],
                "b0": int(round(f0 * rec["size"])), "b1": int(round(f1 * rec["size"])),
                "speaker": speaker, "colour": colours.get(speaker, 7), "en": c["en"], "rows": wrap(pf, c["en"]),
                "rows_plain": wrap(pf, c["en"], PLAIN_COLS, PLAIN_ROWS if speaker else PLAIN_ROWS + 1),
                "enabled": True, "chain": c["anchor"],
            })
            continue
        s = ml[v["ps1"]] if v else None
        if s is not None and s["start"] <= c["start"] < s["end"] and LINE_HOME.get(v["idx"], (scene,))[0] != scene:
            skipped.append(c["id"])                  # another bank plays this line (LINE_HOME)
            continue
        if s is None or not (s["start"] <= c["start"] < s["end"]):
            # no mono line, or the same (file, chan) in the OTHER XA file: an S000 reel
            st = next((m for m in s_streams if m["file"] == c["file"] and m["ch"] == c["chan"] and m["start"] <= c["start"] < m["end"]), None)   # the file number is shared by interleaved channels
            r = reels.get(st["key"]) if st else None
            if r is None:
                skipped.append(c["id"])
                continue
            frames, rate, ch, bpf = aiff_info(os.path.join(SDAIF_DIR, r["sdaif"]))
            # the PS1 window in SECONDS from the stream's first sector (the census `dur` is the
            # stream's real length), mapped onto the Saturn file by the audio alignment
            # (reelalign.py: saturn_t = a * ps1_t + b; 1, 0 = the same cut). A proportion of the
            # sector span - the rule until 2026-09-16 - squeezed the HQ arrival's 71.3-s PS1
            # stream onto its 65.0-s Saturn cut (the PS1 runs 6 s longer at the END): every
            # card 9 % early, 3 s by the office (Luiz: "the text starts too quickly")
            span = st["end"] - st["start"]
            al = aligned.get(st["key"], {})
            a_, b_ = al.get("a", 1.0), al.get("b", 0.0)
            t0 = a_ * (c["start"] - st["start"]) / span * st["dur"] + b_
            t1 = a_ * (c["end"] - st["start"]) / span * st["dur"] + b_
            fr0 = min(frames, max(0, int(t0 * rate)))
            fr1 = min(frames, max(0, int(t1 * rate)))
            if fr1 <= fr0:
                skipped.append(c["id"])                  # past the Saturn cut's end
                continue
            speaker = c.get("speaker", "")
            if speaker and speaker not in colours:
                unknown.add(speaker)
            cues.append({
                "id": c["id"], "reel": r["n"], "sdaif": r["sdaif"], "rate": rate, "frames": frames,
                "b0": SSND_DATA + fr0 * bpf, "b1": SSND_DATA + fr1 * bpf,
                "size": SSND_DATA + frames * bpf,
                "speaker": speaker, "colour": colours.get(speaker, 7), "en": c["en"], "rows": wrap(pf, c["en"]),
                "rows_plain": wrap(pf, c["en"], PLAIN_COLS, PLAIN_ROWS if speaker else PLAIN_ROWS + 1),
                "enabled": True,
            })
            continue
        span = s["end"] - s["start"]
        rec = table[v["idx"]]
        f0 = max(0.0, (c["start"] - s["start"]) / span)
        f1 = min(1.0, (c["end"] - s["start"]) / span)
        speaker = c.get("speaker", "")
        if speaker and speaker not in colours:
            unknown.add(speaker)
        cues.append({
            "id": c["id"], "line": v["idx"], "act": rec["act"], "sector": rec["sector"],
            "offset": rec["offset"], "size": rec["size"],
            "b0": int(round(f0 * rec["size"])), "b1": int(round(f1 * rec["size"])),
            "speaker": speaker, "colour": colours.get(speaker, 7), "en": c["en"], "rows": wrap(pf, c["en"]),
            "rows_plain": wrap(pf, c["en"], PLAIN_COLS, PLAIN_ROWS if speaker else PLAIN_ROWS + 1),
            "enabled": True,
        })
    # the last card of each mono line runs to the end of the line (the decoder stops there;
    # a reel's counter stays at the end when it is over, so a reel card ends where the PS1's did)
    last = {}
    for i, q in enumerate(cues):
        if "line" in q:
            last[q["line"]] = i
    for i in last.values():
        cues[i]["b1"] = cues[i]["size"]
    for i, q in enumerate(cues):
        assert q["b0"] < q["b1"] <= q["size"], q["id"]
    nreel = sum(1 for q in cues if "reel" in q)
    out = {"scene": scene, "options": {"layout": "band", "cols": COLS, "rows": ROWS, "col0": COL0,
                                       "plain_cols": PLAIN_COLS, "plain_rows": PLAIN_ROWS,
                                       "bytes_per_s": BYTES_PER_S},
           "cues": cues}
    path = os.path.join(OUT_DIR, f"subs_{scene}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log(f"{scene}: {len(cues)} cues ({len(cues) - nreel} on {len(last)} mono lines, {nreel} on reels) -> {path}; "
        f"skipped {len(skipped)} (no line or reel): {' '.join(skipped)}"
        + (f"; speakers not in names.json (white nameplate): {sorted(unknown)}" if unknown else ""))
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        args = SUBTITLED
    for sc in args or ["B010"]:
        if "--faces" in sys.argv:
            add_faces(sc)               # only the portrait fields, the rest of the file untouched
        else:
            convert(sc)
            add_faces(sc)
