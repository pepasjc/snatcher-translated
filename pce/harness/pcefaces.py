"""A census of the faces on the window during voiced lines: which face talks.

Plays a route from a state (pcemenu) and, every frame, reads the sprite
table copy at VRAM 0x1000: sprites whose patterns lie at 0x300-0x3FF (the
face bitmaps at VRAM 0x6000 + region * 0x800) are grouped by that region;
a face's identity is the four words pcesubs.SIG_OFFS name in its bitmap
(the top of the hair, expression-invariant) and its mouth is the sprite
whose pattern changes while the line plays. Per voice line (AD_STAT
rising, the record pointer $5E/$5F naming NN - the stub's own rule), the
region with the most pattern changes is the speaker's. The result, with
the line's speaker from pce/translation/subs_<rec>.json, is what
pcesubs' signature table is built from:

  python pce/harness/pcefaces.py <state.mdf> <route.json> <rec> [out.json]
  python pce/harness/pcefaces.py learn <census.json>...     # merge into faces.json
  python pce/harness/pcefaces.py sheet                      # every face bitmap on the disc, by signature
  python pce/harness/pcefaces.py label <sig> <character>... # file a signature from the sheet

`sheet` decodes every display-list record of every scene block that draws a
face region (VRAM 0x6000-0x7FFF, 0x800 words) and lays the distinct bitmaps
out in work/pce/faces_sheet.png with their signatures (work/pce/faces_sheet.json
maps each to the blocks it appears in): the characters are named by eye
from it, no play needed.

`learn` adds, for every line whose speaker is known and whose talking
region is unambiguous (the most changes, at least MIN_CHANGES and twice
the runner-up's), the region's signature under that speaker, and refuses
a signature already filed under another character.
"""
import ctypes as C, hashlib, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

import pcemenu as M
import pcestate as ST
import pcesubs

FACE_PAT = 0x200             # patterns from here: the face regions (0x4000 + region * 0x800; the portraits at 0x6000 on, the ending's at 0x4000)
MIN_CHANGES = 12             # a talking mouth over a line; blinks stay under this


def faces_of(vram):
    """{region: {'sprites': [(slot, y, x, pat, attr)], 'base': pat, 'sig': [four words]}}"""
    out = {}
    for i in range(64):
        y, x, pat, attr = struct.unpack_from('<HHHH', vram, 0x2000 + i * 8)
        pat &= 0x7FF
        if not (0 < y < 0x400) or not (FACE_PAT <= pat < 0x400) or y < 0xC0:
            continue                # (on the window band: y from 0xC0 raw)
        out.setdefault((pat - FACE_PAT) >> 6, []).append((i, y, x, pat, attr))
    faces = {}
    for region, sprites in out.items():
        base = 0x4000 + region * 0x800
        faces[region] = {"sprites": sprites, "base": base,
                         "sig": [struct.unpack_from('<H', vram, (base + o) * 2)[0] for o in pcesubs.SIG_OFFS]}
    return faces


def line_nn(r):
    """The line the record pointer $5E/$5F names (pcesubs' rule), 0 for an effect."""
    hi, lo = r[0x5F], r[0x5E]
    if not 0x80 <= hi < 0x88:
        return 0
    return ((hi & 7) << 5 | lo >> 3) + 1 & 0xFF


def census(state, route, rec, out):
    subs = json.load(open(os.path.join(ROOT, "pce", "translation", f"subs_{rec}.json"), encoding="utf-8"))
    p = M.Pilot()
    p.restore(state)
    steps = json.load(open(route, encoding="utf-8"))
    lines = []          # per voice line: nn, speaker, faces seen, changes per region
    cur = None
    prev_pats = {}
    was_playing = False

    def tick():
        nonlocal cur, prev_pats, was_playing
        st = p.emu.state()
        s = ST.sections(st, ('BaseRAM', 'VRAM'))
        r, v = s['BaseRAM'], s['VRAM']
        playing = r[0x6F2] != 0            # AD_STAT as the service last read it
        if playing and not was_playing:
            nn = line_nn(r)
            if nn:
                cur = {"nn": f"{nn:02x}", "speaker": subs.get(f"{nn:02x}", {}).get("speaker"), "frame": p.frame, "faces": {}}
                lines.append(cur)
        if cur is not None and os.environ.get("PROBE") and (p.frame - cur["frame"]) in (0, 6, 12, 30, 90):
            probe(st, r, cur, p)
        if not playing:
            cur = None
        was_playing = playing
        f = faces_of(v)
        pats = {reg: tuple(sp[3] for sp in sorted(face["sprites"])) for reg, face in f.items()}
        if cur is not None:
            if (p.frame - cur["frame"]) % 45 == 0:
                p.emu.image().save(os.path.join(WORK, "pce", os.environ.get("FACES_DIR", "route_faces"), f'l{cur["nn"]}_{p.frame - cur["frame"]:04d}.png'))
            for reg, face in f.items():
                e = cur["faces"].setdefault(str(reg), {"sig": face["sig"], "changes": 0, "frames": 0,
                                                       "slots": sorted(sp[0] for sp in face["sprites"]), "base": face["base"]})
                e["frames"] += 1
                if reg in prev_pats and prev_pats[reg] != pats[reg]:
                    e["changes"] += 1
        prev_pats = pats

    # drive the route step by step, sampling every frame
    orig_step = p.step

    def step(n=1, held=()):
        for _ in range(n):
            orig_step(1, held)
            tick()
    p.step = step
    M.run(p, steps, every=90, outdir=os.path.join(WORK, "pce", os.environ.get("FACES_DIR", "route_faces")))
    json.dump(lines, open(out, "w"), indent=1)
    for l in lines:
        print(f'{l["nn"]} {str(l["speaker"]):10} {verdict(l) or "-":8} '
              + ' '.join(f'r{reg}:{e["changes"]}c/{e["frames"]}f {" ".join(f"{w:04x}" for w in e["sig"])}' for reg, e in sorted(l["faces"].items())))
    print(out)


def probe(st, r, cur, p):
    """(PROBE=1) the face block's object map and the stub's layout at a line's start."""
    import pcesubs
    fb, fl = pcesubs.face_block()
    code, labels = pcesubs.stub()
    sc = ST.sections(st, ('SysCardRAM',))['SysCardRAM']
    fbase = (0x7B - 0x68) * 0x2000 + pcesubs.FACE_OFF
    sbase = (0x7B - 0x68) * 0x2000 + pcesubs.stub_org() - 0xA000
    fv = lambda k, w=1: sc[fbase + fl[k] - pcesubs.FACE:fbase + fl[k] - pcesubs.FACE + w]
    sv = lambda k: sc[sbase + labels[k] - pcesubs.stub_org()]
    oreg, omv = fv('oreg', 64), fv('omv', 64)
    objs = ' '.join(f"{x:02x}:r{oreg[x]}m{omv[x]}@{r[0x800+x]:02x}{r[0x7c0+x]:02x},{r[0x8c0+x]:02x}{r[0x880+x]:02x}" for x in range(64) if oreg[x] or omv[x])
    live = ' '.join(f"{x:02x}@{r[0x800+x]:02x}{r[0x7c0+x]:02x},{r[0x8c0+x]:02x}{r[0x880+x]:02x}/f{r[0xdc0+x]:02x}/l{r[0xf40+x]:02x}{r[0xf00+x]:02x}b{r[0xf80+x]:02x}/F{r[0x740+x]:02x}{r[0x700+x]:02x}b{r[0xec0+x]:02x}" for x in range(64) if r[0xa40+x] and not oreg[x])
    print(f'  probe {cur["nn"]} +{p.frame - cur["frame"]}: shown={sv("shown")} grace={sv("grace")} mode={sv("mode")} row0={sv("row0")} spill={sv("spill"):02x} sreg={fv("sreg").hex()} present={fv("present",4).hex()} | faces: {objs} | other live: {live}', flush=True)


def verdict(line):
    """The region that talks in a census line, or None when it is not clear."""
    ranked = sorted(line["faces"].items(), key=lambda kv: -kv[1]["changes"])
    if not ranked or ranked[0][1]["changes"] < MIN_CHANGES:
        return None
    if len(ranked) > 1 and ranked[1][1]["changes"] * 2 > ranked[0][1]["changes"]:
        return None
    return ranked[0][0]


def learn(paths):
    db = pcesubs.faces_db()
    owners = {tuple(sig): name for name, sigs in db.items() for sig in sigs}
    added = 0
    for path in paths:
        for l in json.load(open(path)):
            reg = verdict(l)
            if reg is None or not l["speaker"]:
                continue
            sig = tuple(l["faces"][reg]["sig"])
            if not any(sig):
                continue                # the bitmap was blank when read (text over it): nothing to learn
            owner = owners.get(sig)
            if owner == l["speaker"]:
                continue
            if owner:
                print(f'{path} {l["nn"]}: the talking face is filed under {owner}, the line says {l["speaker"]} - left alone')
                continue
            db.setdefault(l["speaker"], []).append(list(sig))
            owners[sig] = l["speaker"]
            added += 1
            print(f'{path} {l["nn"]}: {l["speaker"]} = {" ".join(f"{w:04x}" for w in sig)}')
    json.dump(db, open(pcesubs.FACES, "w", encoding="utf-8"), indent=1)
    print(f"{added} signature(s) added; {sum(len(v) for v in db.values())} over {len(db)} characters in {pcesubs.FACES}")


def sprite_cell(words, at):
    """A 16x16 sprite cell (64 words at `at`, 16 rows of plane 0, 1, 2, 3) -> (16, 16) indices."""
    import numpy as np
    px = np.zeros((16, 16), dtype=np.uint8)
    for plane in range(4):
        for row in range(16):
            w = words[at + plane * 16 + row]
            for x in range(16):
                if w >> (15 - x) & 1:
                    px[row, x] |= 1 << plane
    return px


def face_image(words):
    """A portrait from its bitmap, laid out as the Chief's objects draw it: four 32x32 quadrant
    sprites (cells 0-15: TL, BL, TR, BR, each TL/TR/BL/BR inside), the eyes' first frame (cells
    16-17, a 32x16 at 8,16) and the mouth's (cells 22-23, a 32x16 at 16,32) -> (64, 64)."""
    import numpy as np
    img = np.zeros((64, 64), dtype=np.uint8)
    for c in range(16):
        q, k = c // 4, c % 4
        x = [(0, 0), (0, 32), (32, 0), (32, 32)][q][0] + (k % 2) * 16
        y = [(0, 0), (0, 32), (32, 0), (32, 32)][q][1] + (k // 2) * 16
        img[y:y + 16, x:x + 16] = sprite_cell(words, c * 64)
    for c, (x, y) in ((16, (8, 16)), (17, (24, 16)), (22, (16, 32)), (23, (32, 32))):
        if (c + 1) * 64 <= len(words):
            img[y:y + 16, x:x + 16] = sprite_cell(words, c * 64)
    return img


def sheet():
    """Every distinct face bitmap on the disc, rendered with its signature."""
    import numpy as np
    from PIL import Image, ImageDraw
    import pcescene as S
    import pcecodec as C
    import tilescan as T
    faces = {}          # sig -> {"px": image, "where": [block...]}
    # a record may point into another file loaded beside the block (the act's portraits):
    # every file's bank range, so the stream can be fetched from wherever that bank is
    ft = S.TABLES
    files = []
    for g in ("0", "1", "2", "3"):
        for e in ft[g]:
            if g == "2":
                files.append((e["bank"], (e["n"] * 2048 + C.BANK - 1) // C.BANK, e["rec"], e["n"]))
    blocks = {}

    def load(rec, n):
        if rec not in blocks:
            blocks[rec] = S.block(rec, n)
        return blocks[rec]

    def records(blk, bank0, nbanks):
        """Every 6-byte record run in the block, any bank (find_lists wants the block's own)."""
        n = len(blk)
        i = 0
        while i < n - 6:
            j, recs = i, []
            while j + 6 <= n:
                b, t, vl, vh, pl, ph = blk[j:j + 6]
                if b == 0xFF:
                    break
                ptr = pl | ph << 8
                if not (3 <= b < 0x20 and 0x8000 <= ptr < 0xE000 and t < 0x20):
                    recs = None
                    break
                recs.append((b, t, vl | vh << 8, ptr))
                j += 6
            if recs and len(recs) >= 1 and j + 6 <= n:
                for r in recs:
                    yield r
                i = j + 1
            else:
                i += 1

    seen = set()
    for bi in range(len(ft["2"])):
        r = ft["2"][bi]
        blk = load(r["rec"], r["n"])
        nb = (len(blk) + C.BANK - 1) // C.BANK
        for b, t, va, ptr in records(blk, r["bank"], nb):
            if not (0x4000 <= va < 0x8000) or (b, t, va, ptr) in seen:
                continue
            seen.add((b, t, va, ptr))
            # the record's bank, less the block's own load bank, is a page of the block that
            # holds the list (the Chief's face: list in rec 1138's first bank, data in its third);
            # failing that, whatever file the table puts at that bank
            cands = [(blk, r["rec"], b - r["bank"])] + [(load(frec, fn), frec, b - fbank) for fbank, fnb, frec, fn in files if fbank <= b < fbank + fnb]
            hit = None
            for src, frec, page in cands:
                o = page * C.BANK + (ptr - 0x8000)
                if page < 0 or o + 8 > len(src):
                    continue
                sp, flags, rowlen = C.image_stream(src, o, t)
                try:
                    data, end, clean = C.decode(src, sp, limit=0x1400)
                except Exception:
                    continue
                if clean and 0x800 <= len(data) <= 0x1000:
                    hit = (src, frec, o)
                    break
            if not hit:
                continue
            src, frec, o = hit
            vram = S.build_vram(src, [(b, t, va, ptr, o)])
            base = (va - 0x4000) >> 11 << 11 | 0x4000
            words = struct.unpack_from("<%dH" % 0x800, vram, base * 2)
            region = (va - 0x4000) >> 11
            sig = tuple(words[o2] for o2 in pcesubs.SIG_OFFS)
            if not any(sig):
                continue
            e = faces.setdefault(sig, {"where": [], "px": None})
            e["where"].append(f"b{bi}r{region}<{frec}")
            if e["px"] is None:
                e["px"] = face_image(words)
    db = pcesubs.faces_db()
    owners = {tuple(v2): name for name, sigs in db.items() for v2 in sigs}
    keys = sorted(faces, key=lambda sg: (owners.get(sg, "~"), sg))
    COLS, W, H = 8, 128 + 8, 128 + 36
    rows = (len(keys) + COLS - 1) // COLS
    im = Image.new("L", (COLS * W, rows * H), 20)
    d = ImageDraw.Draw(im)
    meta = {}
    for i, sg in enumerate(keys):
        x, y = (i % COLS) * W, (i // COLS) * H
        im.paste(Image.fromarray(faces[sg]["px"] * 17, "L").resize((128, 128), Image.NEAREST), (x, y + 14))
        name = owners.get(sg, "?")
        d.text((x + 1, y + 1), f"{i} {name[:9]}", fill=255)
        d.text((x + 1, y + 142), " ".join(f"{w:04x}" for w in sg[:2]), fill=200)
        d.text((x + 1, y + 152), " ".join(f"{w:04x}" for w in sg[2:]), fill=200)
        meta[i] = {"sig": list(sg), "where": faces[sg]["where"], "name": owners.get(sg)}
    out = os.path.join(WORK, "pce", "faces_sheet.png")
    im.save(out)
    json.dump(meta, open(os.path.join(WORK, "pce", "faces_sheet.json"), "w"), indent=1)
    print(f"{len(keys)} distinct face bitmaps ({sum(1 for k in keys if k in owners)} named) -> {out}")


def label(args):
    """label <index> <character> ...: file the sheet's face #index under the character."""
    meta = json.load(open(os.path.join(WORK, "pce", "faces_sheet.json")))
    db = pcesubs.faces_db()
    owners = {tuple(v2): name for name, sigs in db.items() for v2 in sigs}
    for idx, name in zip(args[::2], args[1::2]):
        sig = tuple(meta[idx]["sig"])
        if name not in pcesubs.CHARS:
            raise SystemExit(f"{name!r} is not in pcesubs.CHARS")
        if owners.get(sig) == name:
            continue
        if owners.get(sig):
            db[owners[sig]] = [v2 for v2 in db[owners[sig]] if tuple(v2) != sig]
        db.setdefault(name, []).append(list(sig))
        owners[sig] = name
        print(f"#{idx} -> {name}")
    json.dump(db, open(pcesubs.FACES, "w", encoding="utf-8"), indent=1)


def main():
    if sys.argv[1] == "learn":
        learn(sys.argv[2:])
        return
    if sys.argv[1] == "sheet":
        sheet()
        return
    if sys.argv[1] == "label":
        label(sys.argv[2:])
        return
    state, route, rec = sys.argv[1], sys.argv[2], int(sys.argv[3])
    out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(WORK, "pce", f"faces_{rec}.json")
    census(state, route, rec, out)


if __name__ == "__main__":
    main()
