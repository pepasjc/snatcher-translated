"""Parse and rebuild ISZ_B040's name-search key table.

Structure, verified byte-by-byte:

    section: [initials word:BE16] [08 param] [fallback word] [09 03 E0 x x]
             then key records until the next section prelude
    key:     [key word] [09] [len:1] [len bytes action]
             action '03 E0 <2 bytes>'        -> show that dossier
             action '06 C0 01 A0 07 <word>'  -> show a correction line

The initials string lists every character that selects the section (typed
first character -> section). The fallback string is the "no such person"
matcher key. The first section is preceded by scene-init bytecode;
TABLE_START points at its initials word.

    python keytable.py            # parse and dump
"""
import json, os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BANK = os.path.join(ROOT, "discs/extracted_ps1", "PLN", "ISZ", "ISZ_B040.BIN")
REF = os.path.join(ROOT, "work", "ref", "ISZ_B040.json")

TABLE_START = 0x1F


def load():
    d = open(BANK, "rb").read()
    sbase = struct.unpack_from(">H", d, 0)[0]
    strings = json.load(open(REF, encoding="utf-8"))["strings"]
    words = {}
    for i, e in enumerate(strings):
        w = (e["off"] - (sbase + 4) + 1) // 2
        words[w] = (i, e["jp"])
    return d, sbase, strings, words


def parse(d, words):
    """Return (sections, end)."""
    pos = TABLE_START
    sections = []
    while pos + 11 <= len(d):
        w = struct.unpack_from(">H", d, pos)[0]
        if w not in words or d[pos + 2] != 0x08:
            break
        start = pos
        head = words[w]
        param = d[pos + 3]
        fb = struct.unpack_from(">H", d, pos + 4)[0]
        if fb not in words:
            break
        if not (d[pos + 6] == 0x09 and d[pos + 7] == 0x03 and d[pos + 8] == 0xE0):
            break
        reply = bytes(d[pos + 9:pos + 11])
        pos += 11
        keys = []
        while pos + 4 <= len(d):
            kw = struct.unpack_from(">H", d, pos)[0]
            if kw not in words or d[pos + 2] != 0x09:
                break
            ln = d[pos + 3]
            action = d[pos + 4:pos + 4 + ln]
            if ln == 0 or ln > 0x20 or len(action) != ln:
                break
            keys.append({"pos": pos, "word": kw, "idx": words[kw][0],
                         "jp": words[kw][1], "len": ln, "action": bytes(action)})
            pos += 4 + ln
        sections.append({"pos": start, "word": w, "idx": head[0], "jp": head[1],
                         "param": param, "fallback": fb, "reply": reply,
                         "keys": keys, "end": pos})
    return sections, pos


if __name__ == "__main__":
    d, sbase, strings, words = load()
    sections, end = parse(d, words)
    total_keys = sum(len(s["keys"]) for s in sections)
    print(f"sbase {sbase:#x}; table {TABLE_START:#x}..{end:#x} "
          f"({end - TABLE_START} bytes), {len(sections)} sections, {total_keys} keys")
    for s in sections:
        corr = sum(1 for k in s["keys"] if k["len"] == 6)
        print(f"  {s['pos']:#06x} '{s['jp']}' idx {s['idx']} param {s['param']:#04x} "
              f"keys {len(s['keys'])} (corrections {corr})")
    print(f"after table: {d[end:end+16].hex(' ')}")


# ---------------------------------------------------------------------------
# English rebuild
# ---------------------------------------------------------------------------

# Romanization of every key. Character names follow the Sega CD localization
# (GILLIANSEED, MIKASLAYTON, RANDAMHAJILE, CATHERINE, JAMIE); staff names are
# Hepburn. Spelling-variant keys map to variant spellings so each stays a
# distinct typeable entry. Vulgar joke keys stay romaji, which preserves the
# easter egg without printing English profanity. idx 185 is the quit command.
ENGLISH = {
    4: "ALICE", 5: "ALICEGIBSON", 6: "AIZAWA",
    7: "AIZAWAMASAYUKI", 8: "ASATA", 10: "ASATAHIROYUKI",
    11: "ASADA", 12: "ASADAHIROYUKI", 13: "ASAMI",
    14: "ASAMIJUN", 15: "ARAKIKAZUNORI", 17: "ARAKI",
    18: "ARAKIKAZUKI", 19: "ANDO", 20: "ANDOTAKAYUKI",
    21: "ADACHI", 23: "ISABELLAVELVET", 24: "ISABELLA",
    25: "IVANRODRIGUEZ", 26: "IVAN", 27: "OLDMAN",
    28: "INOGUCHI", 29: "INOGUCHIISAO", 30: "INOUE",
    31: "INOUEKIKUKO", 32: "IWASAKI", 33: "IWASAKIKAZUHIRO",
    34: "OMEKO", 35: "OMANKO", 36: "OCONNOR",
    38: "CATHERINEGIBSON", 39: "CATHERINE", 40: "CATHERINEGIBSEN",
    41: "CHIEF", 42: "KOYAMA", 43: "KOYAMAMAMI",
    44: "KIYOHARA", 45: "KIYOHARAYOHEI", 46: "GOD",
    47: "GODADACHI", 48: "KOJIMA", 49: "KOJIMAHIDEO",
    50: "KOMATSUBARA", 51: "KOMATSUBARARIEKO", 52: "KIDA",
    53: "KIDASUN", 54: "KINTAMA", 55: "KYANTAMA",
    56: "KONAMI", 57: "CUNNINGHAM", 59: "GILLIANSEED",
    60: "GILLIAN", 61: "GIBSON", 62: "GILMORE",
    63: "GLAZER", 64: "GAUDI", 67: "SERGIO",
    68: "SHIOZAWA", 69: "SHIOZAWAKANETO", 70: "SAIKACHI",
    71: "SAIKACHIRYUJI", 72: "SLAYTON", 73: "SOTOYAMA",
    75: "SOTOYAMAMAKOTO", 76: "SOTOYAMASHIN", 78: "SHIRAISHIMASAYA",
    79: "SHIRAISHI", 80: "SCHULTZ", 81: "SCHULTZDECKER",
    82: "SHINOBU", 83: "SHO", 84: "SHODECKARD",
    85: "SEED", 87: "JEAN", 88: "JEANJACK",
    89: "JACK", 90: "JEANJACKGIBSON", 91: "JEANJACKGIBSEN",
    92: "JAMIESEED", 93: "JAMIE", 94: "SERGIOGLAZER",
    95: "JOHNSON", 97: "CHINSHUHO", 98: "CHIN",
    99: "TOMINAGA", 100: "TOMINAGAMINA", 101: "TATCHAN",
    102: "TAKAHASHI", 103: "TAKAHASHIYUMIKO", 104: "TOYAMASHIN",
    106: "TOYAMA", 107: "TOYAMAMAKOTO", 108: "CHINPOKO",
    109: "CHINCHIN", 110: "CHINKO", 111: "TAMAKIN",
    112: "TAMATAMA", 113: "CHINPO", 115: "DAVID",
    116: "DAVIDJOHNSON", 117: "DECKARD", 119: "NAPOLEON",
    120: "NAPOLEONBONAPARTE", 121: "NAYA", 122: "NAYAGORO",
    123: "NOGUCHI", 124: "NOGUCHIHIROE", 125: "NIELSEN",
    127: "HARRYBENSON", 128: "HARRY", 129: "FREDDYNIELSEN",
    130: "FREDDINIELSEN", 131: "FREDDY", 132: "FREDDI",
    133: "HATSUMI", 134: "HATSUMINAOYA", 135: "HAYASAKA",
    136: "HAYASAKATAEKO", 137: "HAGGY", 138: "HASHIMOTOKAZUHISA",
    139: "HASHIMOTO", 140: "HAJILE", 142: "BENSONCUNNINGHAM",
    143: "BENSON", 144: "BIG", 145: "BOBO",
    146: "VELVET", 147: "BRIAN", 148: "BRIANOCONNOR",
    151: "MIKASLAYTON", 152: "MIKA", 153: "METALGEAR",
    154: "METAL", 155: "MIZUTANI", 156: "MIZUTANIATSUSHI",
    157: "MIZUKAMI", 158: "MIZUKAMIGENTARO", 159: "MIZUGAMIGENTARO",
    161: "MINAKAMIGENTARO", 163: "MIZUGAMI", 164: "MINAKAMI",
    165: "MATSUKAWA", 166: "MATSUKAWANORITADA", 167: "MADOKA",
    168: "MISTERBIG", 170: "LITTLEJOHN", 171: "LITTLE",
    172: "LISANIELSEN", 173: "LISA", 174: "RIKA",
    175: "RANDAMHAJILE", 176: "RANDAM", 177: "LEWIS",
    178: "LEWISGILMORE", 179: "RODRIGUEZ", 181: "YARA",
    182: "YARAYUSAKU", 183: "YOSHITOMI", 184: "YOSHITOMIKENSUKE",
    185: "QUIT",
}

# 15 contiguous letter-range sections, replacing the 15 kana sections.
SECTIONS = ["A", "BC", "DEF", "G", "H", "I", "J", "K", "L", "M", "NO",
            "PQR", "S", "TUV", "WXYZ"]


def fullwidth(t):
    return "".join(chr(0xFF00 + ord(c) - 0x20) if 33 <= ord(c) <= 126 else c
                   for c in t)


def build(out_bank):
    """Rebuild the key table with English keys packed into the low region.

    A consumer in the candidate-list path keeps only 13 bits of a key word,
    so every key string must sit at word <= 0x1FFF (byte offset <= 0x3FFE from
    the string base). Space comes from the dead katakana key strings plus
    dialogue strings evicted to the end of the bank; evicted strings keep
    working through the display remap table (work/keytable_remaps.json, merged
    by repoint.py)."""
    from textcodec import encode_string
    d0, sbase, strings, words = load()
    sections, end = parse(d0, words)
    assert end - TABLE_START == 1334, end
    base = sbase + 4
    WORD_MAX = 0x1FFF

    d = bytearray(open(out_bank, "rb").read())

    key_idx = set()
    for s in sections:
        key_idx.add(s["idx"])
        for k in s["keys"]:
            key_idx.add(k["idx"])

    new_strings = []                     # (kind, id, encoded-with-terminator)
    for idx in sorted(set(keytable_all_key_idx(sections))):
        assert idx in ENGLISH, f"missing romanization for idx {idx}"
        new_strings.append(("key", idx,
                            encode_string(fullwidth(ENGLISH[idx])) + bytes(1)))
    # headers are allocated during emit via place_string; reserve room for
    # roughly 15 headers incl. the catch-all tail of leftover characters
    need = sum(len(b) for _, _, b in new_strings) + 160

    tr = json.load(open(os.path.join(ROOT, "ps1/translation", "ISZ_B040.json"),
                        encoding="utf-8"))["strings"]

    # free spans: the dead katakana keys and section headers. A key that also
    # carries translated display text (dual-purpose string) is evicted to the
    # tail first so its dialogue references keep working through the remap.
    spans = []
    moved = {}
    remaps = []
    def evict(i):
        e = strings[i]
        raw_end = d.index(0, e["off"])
        content = bytes(d[e["off"]:raw_end + 1])
        d.append(0)
        new_off = len(d)
        d.extend(content)
        # key the remap on the offset the engine will ASK for: the bytecode
        # holds a word (base + 2w), and the resolver (0x8003EDE4) steps back
        # one byte only when the byte before is non-zero - an odd-placed
        # string, once its first two bytes are zeroed below, is requested
        # at old + 1 (GitHub #99: Gibson's file page came up empty)
        req = base + 2 * ((e["off"] - base + 1) // 2)
        remaps.append([req - base, new_off - base])
        moved[i] = new_off
        # never reuse the exact old offset: the display remap matches it and
        # would redirect the new occupant to the evicted string's new home
        d[e["off"]] = 0
        d[e["off"] + 1] = 0
        spans.append([e["off"] + 2, e["off"] + e["budget"]])
    for i in sorted(key_idx):
        if tr[i].get("en") and not tr[i].get("lock"):
            evict(i)
        else:
            e = strings[i]
            spans.append([e["off"], e["off"] + e["budget"]])
    pool = sum(b - a for a, b in spans)
    limit = base + WORD_MAX * 2
    cands = sorted(((e["budget"], i) for i, (e, te) in
                    enumerate(zip(strings, tr))
                    if te.get("en") and not te.get("lock") and i not in key_idx
                    and e["off"] + e["budget"] < limit and e["budget"] >= 20),
                   reverse=True)
    ci = 0
    while pool < need + 96:
        budget, i = cands[ci]; ci += 1
        evict(i)
        pool += strings[i]["budget"]

    # pack the new strings into the spans: coalesce, then first-fit decreasing
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and merged[-1][1] == a:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    spans = merged
    placed = {}
    for kind, ident, enc in sorted(new_strings, key=lambda t: -len(t[2])):
        for sp in spans:
            if sp[1] - sp[0] >= len(enc):
                off = sp[0]
                d[off:off + len(enc)] = enc
                sp[0] += len(enc)
                w = (off - base + 1) // 2
                assert 0 < w <= WORD_MAX, (kind, ident, hex(w))
                placed[(kind, ident)] = w
                break
        else:
            raise SystemExit(f"no span fits {kind} {ident} ({len(enc)}B)")
    def place_string(text):
        enc = encode_string(fullwidth(text)) + bytes(1)
        for sp in spans:
            if sp[1] - sp[0] >= len(enc):
                off = sp[0]
                d[off:off + len(enc)] = enc
                sp[0] += len(enc)
                w = (off - base + 1) // 2
                assert 0 < w <= WORD_MAX, (text, hex(w))
                return w
        raise SystemExit(f"no span fits header {text!r} ({len(enc)}B)")

    # ------------------------------------------------------------------
    # words-only rewrite: the table's byte layout is left completely intact
    # (sections, record order, actions, corrections, the quit record) because
    # the engine addresses parts of it by fixed position and match results by
    # record index. Only two kinds of BE16 word values change in place:
    #   - each key record's word -> the packed English string for that key
    #   - each section header word -> a string of the Latin initials routed
    #     to that section (one section per letter; a couple of strays like
    #     CHIEF or GOD live in a section not matching their initial and are
    #     reached by browsing that section's candidate list)
    # ------------------------------------------------------------------
    HEADERS = ["A", "IOU", "KC", "G", "S", "J", "TC", "D", "N", "HF", "BV",
               "EPWXZ0123456789!?", "M", "LR", "YQ"]
    # letters must not repeat across headers except deliberately: the engine
    # takes the first section whose header contains the typed first letter
    claimed = {}
    for i, h in enumerate(HEADERS):
        for c in h:
            claimed.setdefault(c, i)
    assert len(HEADERS) == len(sections)

    for i, (spec, header) in enumerate(zip(sections, HEADERS)):
        hw = place_string(header)
        struct.pack_into(">H", d, spec["pos"], hw)
        for k in spec["keys"]:
            struct.pack_into(">H", d, k["pos"], placed[("key", k["idx"])])
    for a, b in spans:                   # zero what packing left over
        for kk in range(a, b):
            d[kk] = 0
    open(out_bank, "wb").write(d)

    json.dump({"sbase": sbase, "entries": remaps,
               "moved": {str(i): off for i, off in moved.items()}},
              open(os.path.join(ROOT, "work", "keytable_remaps.json"), "w"))
    counts = ", ".join(f"{h}:{len(s['keys'])}" for h, s in zip(HEADERS, sections))
    print(f"key table words swapped in place ({counts})")
    print(f"{len(remaps)} dialogue strings evicted to the bank tail; "
          f"bank {len(d)} bytes")
    return len(d)


def keytable_all_key_idx(sections):
    for s in sections:
        for k in s["keys"]:
            yield k["idx"]


SCENE_TABLE = 0x4A68C          # {LBA, size, pad} x 39; B040 = index 4


def apply():
    """Rebuild patched/ISZ_B040.BIN, relocate the grown bank to appended
    sectors, and update the scene table. patch_disc.py reads
    work/relocations.json; repoint.py merges work/keytable_remaps.json."""
    bank = os.path.join(ROOT, "patched", "ISZ_B040.BIN")
    exe_path = os.path.join(ROOT, "patched", "SLPS_001.54")
    size = build(bank)

    src = json.load(open(os.path.join(ROOT, "work", "lba_map.json")))
    img = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
    total_sectors = os.path.getsize(img) // 2352
    new_lba = total_sectors

    exe = bytearray(open(exe_path, "rb").read())
    rec = SCENE_TABLE + 4 * 12
    old_lba, old_size, pad = struct.unpack_from("<III", exe, rec)
    assert old_lba == src["ISZ_B040.BIN"][0], "scene table drifted"
    struct.pack_into("<II", exe, rec, new_lba, size)
    open(exe_path, "wb").write(exe)

    json.dump({"ISZ_B040.BIN": new_lba},
              open(os.path.join(ROOT, "work", "relocations.json"), "w"))
    print(f"ISZ_B040 relocated: LBA {old_lba} -> {new_lba}, "
          f"size {old_size} -> {size}")


if __name__ == "__main__" and "apply" in sys.argv:
    apply()
