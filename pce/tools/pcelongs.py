"""Long strings out of the module: the PCE's 16-sector cap, lifted for text.

A scene module lives in RAM banks $7E-$81 (16 sectors, sector 17 would land on
the act's voice table at $82), the font at FONT_OFF and the engine's slots at
the top of the fourth bank; with every PS1 bank at full length four modules
(318, 350, 414, 478) run over by 1.8-3.4 KB even with the dictionary. The
free-RAM census (the free-RAM census over 1,311 states, attic/pce/harness/ramfree_pce.py, grouped by the
resident module) found banks $6B and $6C never written for the life of any
module - and took that for free. It is rec 750, loaded with the title and
resident all game: 18 display lists ($6C:1C34) over six picture streams, the
item close-ups (item = the `2b NN` of the module's `1c f8 2c 08 00 14 01 00
2b NN 00 MM 00`): S0 $6B:0000 items 0 1 2 16, S1 $6B:0A13 3-5, S2 $6B:1537 6-8
17, S3 $6B:1CD0 9 10, S4 $6C:06EA 11-13, S5 $6C:0CF4 14 15, FF to $6C:1C00. A
blob over S0 drew the chess piece's decoder through VRAM (#32), one over S4/S5
or the lists stalled Harry's blaster answer. So each blob goes where its OWN
module shows nothing (PLACE): 318 (items 9 10 14) over S0-S2, 350 (every
stream) in the FF fill, 478 (no 14/15 - nor any module after it) over S5.
Every module before Act 2 also carries a RESTORE descriptor that reads 750's
$6B half back from the disc first, so 318's overwrite never outlives 318.

- FETCH ($5341, stage 2 bank 0) maps bank `0x16 + [$3F80] + (ptr >> 13)` at
  MPR6 for a text pointer - the pointer's top three bits pick one of eight
  banks $7E..$85 (pcesubs rides window 4 = $82 for its overflow tables).
  Windows 6 and 7 (pointers 0xC000-0xFFFF) served nothing; the rewrite (40
  bytes in place) sends them to $6B and $6C. [$3F80] is the SCD RAM base,
  $68 in every running state (0 in two boot states before any text), and is
  folded into the constant to fit.
- The shared loader's completion at $54F1 calls the overflow hook for every
  completed group-1 read, including interpreter-driven module changes after
  the recap. Seek requests and other file groups keep their original behavior.
  The scene-start init block is compressed to make room for a bridge that
  maps bank 1 ($69) at MPR3, calls its tail hook, and restores MPR3. The
  hook maps the module's fourth bank, reads the RESTORE descriptor (8 bytes at
  REST, the BIOS's _al.._dh: mode 4, 4 sectors of 750 into $6B; _al 0 =
  none) and the blob's (DESC: _al.._dh for a mode-0 read of the blob's bytes
  to its place at MPR6, then the bank; bank 0 = none), copying each into the
  BIOS arguments with one TII.
- pcescript.build evicts the largest strings of a module that overflows with
  the dictionary into the blob (same codec, same markers; pointers rewritten
  to base(rec) + offset) and writes it as a record in the reserved sectors.
The former scene-start-only hook missed the recap's direct transition to
module 478. Fresh BRAM loads worked, but normal progression read stale text.

  python pce/tools/pcelongs.py apply     # stage 2: FETCH, the hook; after pcesubs, before pceverify
  python pce/tools/pcelongs.py check     # the built image: descriptors, blobs, patches
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import patch_pce as P
from asm6280 import assemble

# rec -> (bank, offset, room): where its blob may lie in rec 750's banks
PLACE = {318: (0x6B, 0x0000, 0x1CD0), 350: (0x6C, 0x1758, 0x04A8), 478: (0x6C, 0x0CF4, 0x0F0C)}
# runs of a place the module's own scenes read (offsets in the bank): the blob carries 750's
# bytes there unchanged and the strings go round them. 478's mechanic room draws Harry and the
# monitor's picture from S5's second half - the blob over it took Harry off the screen for
# whole lines (2026-10-15; never-written is not unused, again). S5's stream ends at 0x11E9:
# from there to 0x1758 lie the frame table every item close-up shares (`frames` = $6C:11E9 in
# all 18 records) and the anim tables. The hole once started at 0x1200 and the blob's strings
# zeroed frames 0-11 - items 0-6 (the chess piece, the Oleen picture, Chin's mugshot...) drew
# garbage or stray sprites in every module after 478 until the next 750 read (#106, #107)
HOLES = {478: [(0x11E9, 0x1758)]}


def holes(rec):
    """[(start, end, 750's bytes)] in blob offsets for module `rec`."""
    if rec not in HOLES:
        return []
    import pcescript as PS
    bank, off, _ = place(rec)
    r750 = PS.read_file(P.Image(P.SRC, 12000), R750, 8)
    at = (bank - 0x6B) * 0x2000
    return [(a - off, b - off, r750[at + a:at + b]) for a, b in HOLES[rec]]
WINDOW = 0xC000               # text pointers from here are longs: window 6 = $6B, window 7 = $6C
R750 = 750                    # the resident record the blobs share, re-read into $6B by RESTORE
RESTORE_BEFORE = 478          # modules below it (Act 1 and the handlers) may follow 318
CLOBBERED = {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17}   # the items whose pictures 318's blob covers (S0-S2)
ITEM_PIC = re.compile(rb'\x1c\xf8\x2c\x08\x00\x14\x01\x00\x2b(.)\x00(.)\x00', re.S)


def needs_restore(rec, module):
    """True when module `rec` can follow 318 and shows a close-up 318's blob covers - only
    those pay the extra 750 read (a long seek on real hardware; the computer room, the save
    handlers and the factory show none - #90)."""
    if rec >= RESTORE_BEFORE or rec == 318:
        return False
    return any(m.group(1)[0] in CLOBBERED for m in ITEM_PIC.finditer(module))
DESC = 0x7FE3                 # module-relative, 9 bytes: _al _ah _bl _bh _cl _ch _dl _dh, bank (0 = none)
REST = 0x7FDB                 # module-relative, 8 bytes: _al.._dh of the 750 read (_al 0 = none)
FETCH = 0x5341
FETCH_OLD = bytes.fromhex("a59218659085906265918591a5914a4a4a4a4a186d803f1869165340a591291f1869c08591b29060")
HOOK_SITE = 0x50E7            # the scene start's JSR $5451, then its 89-byte init block
HOOK_OLD = bytes.fromhex("205154a91585719c0036a9028d003da9038d013d9c023da9028d4035a9108d41359c4235a9028d8035a9088d81359c8235"
                         "a9018d3035a9088d31359c3235a9038da035a9088da1359ca235a9028dc035a9188dc1359cc235a9ff85a0")
BANK1 = 0x69                  # stage 2's second bank, the tail hook's home: mapped at MPR3 by the bridge
LOADER = 0x5451
CD_READ = 0xE009
MARGIN = 32                   # bytes kept free below FONT_OFF after the eviction

FETCH_SOURCE = """
; the text byte fetch, rewritten in place (40 bytes): windows 6/7 -> $6B/$6C
  LDA 0x92
  CLC
  ADC 0x90
  STA 0x90
  CLA
  ADC 0x91
  STA 0x91
  LDA 0x91
  LSR
  LSR
  LSR
  LSR
  LSR
  CMP #0x06
  BCC fwin
  SBC #0x19          ; C set by CMP: 6 -> 0xED, 7 -> 0xEE, borrow clears C
fwin:
  ADC #0x7E          ; 0x68 (SCD RAM base) + 0x16; C clear on both paths -> $7E..$83, $6B, $6C
  TAM #0x40
  LDA 0x91
  AND #0x1F
  ORA #0xC0
  STA 0x91
  LDA (0x90)
  RTS
"""

BRIDGE_SOURCE = """
; bank 0, over the scene start's `JSR $5451` and the init block behind it (92 bytes): the
; module read, the tail hook with bank 1 at MPR3 (the overlay there varies - the opening
; leaves bank 2), then the six inits of the block (two bytes and a zero each) from a table;
; X preserved (the opening's script interpreter waits on a counter indexed by X); the
; remaining inits ($71, $3600, $A0) follow the embedded loader bridge
  JSR {LOADER}
  PHX
  CLX
binit:
  LDA btab,X
  STA 0x00           ; $00/$01: the loader's argument block, consumed by the request
  INX
  LDA btab,X
  STA 0x01
  INX
  LDA btab,X
  STA (0x00)
  INX
  LDA btab,X
  INC 0x00
  STA (0x00)
  INX
  CLA
  INC 0x00
  STA (0x00)
  CPX #24
  BNE binit
  PLX
  BRA bdone
btab:
  .byte 0x00, 0x3D, 0x02, 0x03
  .byte 0x40, 0x35, 0x02, 0x10
  .byte 0x80, 0x35, 0x02, 0x08
  .byte 0x30, 0x35, 0x01, 0x08
  .byte 0xA0, 0x35, 0x03, 0x08
  .byte 0xC0, 0x35, 0x02, 0x18
load_done:
  TMA #0x08
  PHA
  LDA #{BANK1}
  TAM #0x08
  JSR {LHOOK}
  JMP 0x54F4
bdone:
  LDA #0x15
  STA 0x71
  STZ 0x3600
  LDA #0xFF
  STA 0xA0
"""

HOOK_SOURCE = """
; bank 1's tail, reached from the bridge with bank 1 at MPR3: 750's $6B half back, then the
; module's longs (TII keeps A: the bank survives the copy)
lread:
  JSR {CD_READ}
  CMP #0x00
  BNE lread          ; the game's loader retries a failed read too
  RTS
lhook:
  LDA 0x3F2F
  DEC A
  BNE lclear
  LDA 0x3F21
  AND #0x3F
  DEC A
  BNE lclear
  TMA #0x40
  PHA
  LDA #0x81          ; the module's fourth bank at MPR6
  TAM #0x40
  LDA {REST_W}
  BEQ lnorest
  .byte 0x73         ; TII: RESTORE -> _al.._dh
  .word {REST_W}, 0x20F8, 8
  JSR lread
lnorest:
  LDA {BANK_W}
  BEQ ldone
  .byte 0x73         ; TII: DESC -> _al.._dh
  .word {DESC_W}, 0x20F8, 8
  TAM #0x40          ; the blob's bank at MPR6, where its mode-0 address points
  JSR lread
ldone:
  PLA
  TAM #0x40
lclear:
  STZ 0x3F21
  STZ 0x3F2F
  STZ 0x3F22
  RTS
"""


def fetch_patch():
    code, _ = assemble(FETCH_SOURCE, FETCH)
    assert len(code) == len(FETCH_OLD) == 40, len(code)
    return FETCH - P.STAGE2_BASE, FETCH_OLD, code


def hook_org():
    """Immediately after pcesubs' tail code in bank 1."""
    import pcesubs
    used = len(pcesubs.tail()[0])
    return pcesubs.TAIL + used


def hook_code(org=None):
    org = hook_org() if org is None else org
    win = lambda off: 0xC000 + (off & 0x1FFF)          # module offset -> its address at MPR6 ($81)
    src = HOOK_SOURCE.format(CD_READ=CD_READ, REST_W=win(REST), DESC_W=win(DESC), BANK_W=win(DESC + 8))
    code, labels = assemble(src, org)
    return code, labels


def patches():
    """[(stage-2 file offset, old bytes, new bytes)]."""
    import pcesubs
    org = hook_org()
    code, labels = hook_code(org)
    if org + len(code) > pcesubs.TAIL_END:
        raise SystemExit(f"the longs hook is {len(code)} B at {org:#06x}, past bank 1's tail {pcesubs.TAIL_END:#06x}")
    bsrc = BRIDGE_SOURCE.format(LOADER=LOADER, BANK1=BANK1, LHOOK=labels["lhook"])
    bridge, blabels = assemble(bsrc, HOOK_SITE)
    if len(bridge) > len(HOOK_OLD):
        raise SystemExit(f"the bridge is {len(bridge)} B, the block holds {len(HOOK_OLD)}")
    bridge += bytes([0xEA]) * (len(HOOK_OLD) - len(bridge))     # NOPs to the block's end
    out = [fetch_patch()]
    if not os.environ.get("LONGS_NO_BRIDGE"):          # a test: FETCH alone
        out += [(HOOK_SITE - P.STAGE2_BASE, HOOK_OLD, bridge),
                (org - P.STAGE2_BASE, bytes([0xFF]) * len(code), code),
                (0x54F1 - P.STAGE2_BASE, bytes.fromhex('9c213f9c2f3f9c223f60'),
                 bytes([0x4C]) + blabels['load_done'].to_bytes(2, 'little')
                 + bytes.fromhex('68530862c90060'))]
    return out


def place(rec):
    """(bank, offset, room) for module `rec`'s blob."""
    if rec not in PLACE:
        raise SystemExit(f"module {rec} needs a longs blob but has no PLACE in rec 750's banks")
    return PLACE[rec]


def base(rec):
    """The text pointer of the blob's first byte (FETCH: window 6 = $6B, 7 = $6C)."""
    bank, off, _ = place(rec)
    return WINDOW + (bank - 0x6B) * 0x2000 + off


def room(rec):
    return place(rec)[2]


def descriptor(lrec, nbytes, rec):
    """DESC for module `rec`: a mode-0 read of `nbytes` from record `lrec` to its place."""
    if os.environ.get("LONGS_NO_READ"):                # a test: the bridge without its read
        return bytes(9)
    bank, off, _ = place(rec)
    dst = 0xC000 + off                                 # the bank sits at MPR6 for the read
    return bytes([nbytes & 0xFF, nbytes >> 8, dst & 0xFF, dst >> 8,
                  lrec >> 16, (lrec >> 8) & 0xFF, lrec & 0xFF, 0, bank])


def unsign(src_rec):
    """DESC for a NO_RESIDENT module (the ending, 670): three bytes of `src_rec` (its pristine
    record, bytecode - never "SB3") read over the resident stub's signature in rec 110's first
    bank. rec 110 is still in for the ending's first two thirds; with its signature there the
    trampoline ran the resident stub on the ending's table, planned for the module stub (rows
    of 12 cells, no window section of its own): the rows overflowed the resident's 10-cell
    face rows - the cards garbled - and Madnar's throne scenes, with no window, showed none
    (2026-11-06). Without it the trampoline takes the module's own stub, and the walker hook,
    which also needs it, leaves the game's faces alone. A file read puts it back."""
    import pcesubs
    sig = pcesubs.stub()[1]["sig"]                     # at MPR5 ($A000-$BFFF)
    dst = 0xC000 + (sig - 0xA000)                      # the bank at MPR6 for the read
    bank = 0x68 + pcesubs.FACE_BANK
    return bytes([3, 0, dst & 0xFF, dst >> 8, src_rec >> 16, (src_rec >> 8) & 0xFF, src_rec & 0xFF, 0, bank])


def restore():
    """REST: 750's first four sectors ($6B) in mode 4."""
    return bytes([4, 0, 0x6B, 0, R750 >> 16, (R750 >> 8) & 0xFF, R750 & 0xFF, 4])


def parse(d):
    """A DESC's {rec, nbytes, bank, off}, None when the module has no blob."""
    if len(d) < 9 or not d[8]:
        return None
    return dict(rec=d[4] << 16 | d[5] << 8 | d[6], nbytes=d[0] | d[1] << 8,
                bank=d[8], off=(d[2] | d[3] << 8) - 0xC000)


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (P.T2 + P.STAGE2) * P.DATA
    ps = patches()
    for at, old, new in ps:
        got = bytes(img.data[base + at:base + at + len(old)])
        if got == new:
            continue                       # applied already
        assert got == old, f"stage 2 at {at:#x} is not pristine"
        img.write(base + at, new)
    n = img.flush()
    print(f"stage 2: FETCH rewritten (windows 6/7 -> $6B/$6C), shared loader completion hooked, "
          f"{len(ps[2][2])} B of hook at {hook_org():#06x}; {n} sectors written")


def check(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (P.T2 + P.STAGE2) * P.DATA
    for at, old, new in patches():
        got = bytes(img.data[base + at:base + at + len(new)])
        print(f"  stage 2 {P.STAGE2_BASE + at:#06x}: {'patched' if got == new else 'PRISTINE' if got == old else 'OTHER'}")
    placed = json.load(open(os.path.join(WORK, "pce", "build_map.json")))
    for orig, (rec, n) in sorted(placed.items(), key=lambda kv: int(kv[0])):
        off = (P.T2 + rec) * P.DATA
        d = parse(bytes(img.data[off + DESC:off + DESC + 9]))
        r = bytes(img.data[off + REST:off + REST + 8])
        if d:
            print(f"  module {orig} (rec {rec}): longs rec {d['rec']}, {d['nbytes']} B to ${d['bank']:02X}:{d['off']:04x}"
                  f"{', restores 750' if r[0] else ''}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    {"apply": apply, "check": check}[cmd]()
