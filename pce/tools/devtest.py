"""DEV ONLY: trivial shootouts and a fast-forward button, for replaying the PCE
game quickly on real hardware. The PCE twin of the PS1 tree's devfights.py.

    python pce/tools/devtest.py check      # dry run: every patch site, checked against the image
    python pce/tools/devtest.py apply      # writes the dev image (below)
    python pce/tools/devtest.py chd        # patched/pce/<DEV>.chd from it (chdman createcd + verify)
    python pce/tools/devtest.py push       # the CHD to DEVTEST_ROMS and the MiSTer (+ the [dev] save)

NEVER part of a release. The tool never writes the normal build: it copies
patched/pce/snatcher_pce.bin to patched/pce/"Snatcher CD-ROMantic (Japan)
[dev-test].bin" (+ a .cue naming it) and rewrites a few data sectors of the
copy in place (same sectors, same sizes, EDC/ECC regenerated: the file
table, the cue's tracks and the reserve are untouched). It hashes
snatcher_pce.bin and .cue before and after and stops if either changed. Run
it after Build-PCE.bat; it refuses a build whose bytes at the sites differ.

What the dev image changes:

1. Auto-hit (rec 110, the resident file; the fight code runs from its first
   bank at $A000). The shot's state machine ($34C5, handlers at $A8D2) fires
   at the crosshair's cell ($2A15 = $34C8) and in state 3 ($A962) tests that
   cell's object, $34E2+cell = type<<4 | state, state 2-4 hittable. The
   patch scans cells 8..0 instead for an object the game would hit that is
   an ENEMY (an odd type: the kills a fight counts in $34D2; type 2 is the
   don't-shoot kind - the snatcher's arms behind Mika, fight 9's centre
   column, the range's innocents - see the spawn tables at $AC45). Fight 10
   (the snatcher holding Mika) also skips the cells $ACA9 marks as her body
   (1 3 4 5 7: a hit or a miss there costs LIFE in the original). No target:
   a plain miss with no penalty (the miss counter and the difficulty creep at
   $A641 skipped - that code, $A9CC.., holds the fight-10 mask now).
2. No damage. The hit handler ($AD7E) staggers the blaster ($34C4 += $38),
   clears a LIFE segment ($3030 + n) and bumps the damage count $34D5 (dead
   at 6, $ADB0). CPX #6 -> CPX #0 at $AD9E skips segment and count, the
   stagger adds 0, and the range fights' own bump ($AB77) is gone: LIFE
   never drops, and an enemy that keeps attacking cannot end or stall a fight.
3. Fast-forward: hold SELECT outside a shootout (SELECT draws the blaster in
   one; nothing else in the game reads it).
   - Voice (ADPCM): the script's `0a` opcode ($4C21) waits until no request
     is pending and AD_STAT reads stopped. It now maps the text bank (as
     `0d` does) and runs the same test at $6166/$61EE, where SELECT held
     while the line plays = AD_STOP (the call the game makes itself to cut a
     line for the next) and the next opcode. `0a` only runs after `0d` saw
     its line playing, so a line is never cut before the script knew it
     started (that would leave `0d` waiting). The bytes at $6166 and $61EE
     come from folding the ADPCM service's three copies of the
     record-pointer arithmetic into one subroutine at $61A8.
   - CD-DA reels: the script's `1b` opcode ($4C38) waits until the track's
     sub-Q time reaches a mark (the reel's pictures and faces change on
     them), `0b` ($4CE7) until the track has ended. With SELECT held a mark
     passes at once (opcode table -> $4C35), the track playing on (a track
     stopped at a mark, SELECT then let go, would leave the next mark
     waiting for ever); `0b` with SELECT held pauses the track (CD_PAUSE,
     as the game's own scene start does) and goes on - the game builds the
     verb menu after the reel and reads the face band then: a reel still
     playing under the subtitles cost the menu its Look. Room for the `0b`
     entry: opcodes 8, 9 and 0a share one `LDA #2; JMP $43AA` ($4C0F).
   Without SELECT every patched path does what the original did (`0a`
   leaves the text bank at MPR3, as `0d` and the other opcodes that map it).

Not changed: act 3's last battle (don't fire) is still lost by firing.
"""
import hashlib, os, shutil, struct, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import patch_pce as P

PDIR = os.path.join(ROOT, "patched", "pce")
MAIN_BIN = os.path.join(PDIR, "snatcher_pce.bin")
MAIN_CUE = os.path.join(PDIR, "snatcher_pce.cue")
DEV = "Snatcher CD-ROMantic (Japan) [dev-test]"
DEV_BIN = os.path.join(PDIR, DEV + ".bin")
DEV_CUE = os.path.join(PDIR, DEV + ".cue")
DEV_CHD = os.path.join(PDIR, DEV + ".chd")
CHDMAN = os.path.join(ROOT, "lib", "chdman", "chdman.exe")
LOCAL_ROMS = devpaths.get("DEVTEST_ROMS", "")
MISTER_HOST = devpaths.get("MISTER_HOST", "")
MISTER_GAMES = os.environ.get("MISTER_GAMES", "/media/usb0/games/TGFX16-CD")
MISTER_SAVES = os.environ.get("MISTER_SAVES", "/media/fat/saves/TGFX16")     # the core keeps CD saves here (pce_saves.py)
DEV_SAVE = "Snatcher CD-ROMantic (Japan) [dev].sav"
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new"]

BANNER = r"""
##########################################################################
##  DEV-TEST: CHEAT BUILD - shots always hit, no LIFE loss, SELECT=FF.  ##
##  Testing only. NEVER release, CHD-for-players or patch from this.    ##
##########################################################################
"""

REC110 = (110, 12)              # the resident file; its first bank is at $A000 while a fight runs
STAGE2_N = 15                   # stage 2: track sector 22, 15 sectors: bank $68 at $4000, the text bank $6A at $6000


def asm(*parts):
    return b"".join(p if isinstance(p, (bytes, bytearray)) else bytes.fromhex(p) for p in parts)


def br(at, target, size=2):
    """The offset byte of a branch `size` bytes long at `at`."""
    d = target - (at + size)
    assert -128 <= d <= 127, (hex(at), hex(target))
    return bytes([d & 0xFF])


def le(v):
    return struct.pack("<H", v)


# ---- 1, 2: the fights (rec 110, address = $A000 + file offset) ----
SCAN, HIT, MASK, MISSED = 0xA962, 0xA978, 0xA9CC, 0xA9BE
LOOP, NEXT = SCAN + 2, SCAN + 0x11


def scan_code():
    code = asm("a2 08",                             # LDX #8
               "bd e2 34",                          # loop: LDA $34E2,X    type<<4 | state
               "29 1f 38 e9 12 c9 03",              # AND #$1F; SEC; SBC #$12; CMP #3  (odd type, state 2-4)
               "b0", br(SCAN + 0x0C, NEXT),         # BCS next
               "4c", le(MASK),                      # JMP mask
               "ca",                                # next: DEX
               "10", br(SCAN + 0x12, LOOP),         # BPL loop
               "80", br(SCAN + 0x14, MISSED))       # BRA $A9BE: no target, a plain miss
    assert len(code) == HIT - SCAN
    return code


def mask_code():
    return asm("ac c0 34 c0 0a",                    # LDY $34C0; CPY #10    Mika's fight?
               "d0", br(MASK + 5, HIT),             # BNE hit
               "bd a9 ac 29 02",                    # LDA $ACA9,X; AND #2   her body's cells
               "d0", br(MASK + 0x0C, NEXT),         # BNE next
               "80", br(MASK + 0x0E, HIT))          # BRA hit


FIGHT = [   # (address, original bytes, new bytes, what)
    (SCAN, "ae152abde234290fc902b0034ccca9c90590034ccca9", scan_code(),
     "shot test: scan cells 8..0 for an enemy the game would hit"),
    (MASK, "acc034c00af017b9b6a5d0032041a6eed434", mask_code(),
     "fight 10: never Mika's cells (was the miss path)"),
    (0xA9EF, "f0ea", b"\xf0" + br(0xA9EF, MISSED),
     "fight 10's hit path: BEQ $A9DB -> $A9BE ($A9DB is mask code now)"),
    (0xAD83, "38", "00", "hit: blaster stagger ADC #$38 -> ADC #0"),
    (0xAD9F, "06", "00", "hit: CPX #6 -> CPX #0 (skip the LIFE segment and the damage count)"),
    (0xAB77, "eed534", "eaeaea", "range fights' attack: INC $34D5 -> NOPs"),
]

# ---- 3: fast-forward (stage 2) ----
RP = 0x61A8         # the record-pointer subroutine (was the effect path's inline copy)
FF0A = 0x61EE       # the `0a` wait's tail (was the play path's inline copy)
RTS_6A = 0x6218     # an RTS in the text bank (the play path's)
OP1B = 0x4C35


def rp_code():
    code = asm("3a 64 5f",                          # DEC; STZ $5F
               "0a 26 5f 0a 26 5f 0a 26 5f",        # (n - 1) * 8 into $5F:A
               "85 5e 98 04 5f 60",                 # STA $5E; TYA; TSB $5F; RTS   ($5F < 8 here)
               "a0 88", "20", le(RP))               # the effect path's own call: LDY #$88; JSR rp
    assert len(code) == 0x61BF - RP
    return code


def ff0a_code():
    """$61EE..$6207: the `0a` wait's tail, then the play path's call of the subroutine."""
    go = FF0A + 0x0E
    code = asm("20 45 e0",                          # JSR AD_STAT (Z = stopped)
               "f0", br(FF0A + 3, go),              # BEQ go           stopped: on, as the original
               "93 04 28 22",                       # TST #4,$2228     SELECT held?
               "f0", br(FF0A + 9, RTS_6A),          # BEQ rts          no: wait, as the original
               "20 42 e0",                          # JSR AD_STOP
               "4c e9 4d")                          # go: JMP $4DE9    the script's next opcode
    code = code.ljust(0x6200 - FF0A, b"\xea")
    code += asm("20 40 61", "a0 80", "20", le(RP))  # the play path: voice bank in; LDY #$80; JSR rp
    assert len(code) == 0x6208 - FF0A
    return code


OP0A = 0x6166      # the `0a` wait's head in the text bank (was the voice path's inline copy)
M2, OP8, OP9, OP0A68, OP0B = 0x4C0F, 0x4C14, 0x4C1A, 0x4C20, 0x4C26    # the rewritten $4C0F..$4C34


def op0a_head():
    """$6161..$617A: the head of the `0a` wait, then the voice path's call of the subroutine."""
    code = asm("ea" * (OP0A - 0x6161),
               "ad f4 26 0d f3 26 0d f7 26",        # a request pending: wait, as the original
               "d0", br(OP0A + 9, 0x618C),          # BNE an RTS
               "80", br(OP0A + 11, FF0A))           # BRA $61EE
    code += asm("20 40 61", "a0 80", "20", le(RP))  # 6173: voice bank in; LDY #$80; JSR rp
    assert len(code) == 0x617B - 0x6161
    return code


def ops_code():
    """$4C0F..$4C34, opcodes 8, 9 and 0a (each was `LDA #2; JSR $43AA; JSR x; RTS` or the voice
    wait) share the text bank's mapping; opcode 0b gets a new entry."""
    ff = OP0B + 9
    code = asm("a9 02 4c aa 43",                    # m2: LDA #2; JMP $43AA  (the text bank at MPR3)
               "20", le(M2), "4c bc 6f",            # 8:  JSR m2; JMP $6FBC
               "20", le(M2), "4c 52 7e",            # 9:  JSR m2; JMP $7E52
               "20", le(M2), "4c", le(OP0A),        # 0a: JSR m2; JMP $6166
               "93 04 28 22",                       # 0b: TST #4,$2228   SELECT held?
               "d0", br(OP0B + 4, ff),              # BNE ff
               "4c e7 4c",                          # JMP $4CE7: the original wait for the track's end
               "20 18 e0",                          # ff: JSR CD_PAUSE
               "80", br(ff + 3, 0x4C81),            # BRA: JSR $4DE9; RTS (the next opcode)
               "ea")
    assert len(code) == 0x4C35 - M2
    return code


def op1b_code():
    return asm("93 04 28 22",                       # TST #4,$2228     SELECT held?
               "d0", br(OP1B + 4, 0x4C70),          # BNE: JSR $4DDD, the mark passed
               "ad 38 26",                          # LDA $2638        the original from here
               "f0", br(OP1B + 9, 0x4C73))          # BEQ rts; else $4C40 (compare the time)


STAGE2 = [
    (RP, "645f3a0a265f0a265f0a265f186900855ea55f6988855f", rp_code(),
     "ADPCM service: the record pointer as a subroutine + the effect path's call"),
    (0x61A2, "d004", b"\xd0" + br(0x61A2, 0x61BA), "effect path: BNE $61A8 -> $61BA (its LDY/JSR)"),
    (FF0A, "204061645f3a0a265f0a265f0a265f186900855ea55f6980855f", ff0a_code(),
     "the `0a` fast-forward at $61EE + the play path's call of the subroutine"),
    (0x61E7, "f005", b"\xf0" + br(0x61E7, 0x6200), "play path: BEQ $61EE -> $6200"),
    (0x6161, "204061645f3a0a265f0a265f0a265f186900855ea55f6980855f", op0a_head(),
     "the `0a` wait's head at $6166 + the voice path's call of the subroutine"),
    (0x615A, "f005", b"\xf0" + br(0x615A, 0x6173), "voice path: BEQ $6161 -> $6173"),
    (M2, "a90220aa4320bc6f60a90220aa4320527e60adf4260df3260df726d00b2045e0c900d00420e9", ops_code(),
     "opcodes 8, 9, 0a share the text bank's mapping; 0a -> $6166; 0b's entry (SELECT: CD_PAUSE, on)"),
    (OP1B, "4d6060ad3826d0034c734c", op1b_code(), "opcode 1b (CD-DA mark): SELECT passes it"),
    (0x49EB, "0f4c184c214ce74c", le(OP8) + le(OP9) + le(OP0A68) + le(OP0B),
     "opcode table: 8, 9, 0a, 0b -> $4C14, $4C1A, $4C20, $4C26"),
    (0x4A11, "384c", le(OP1B), "opcode table: 1b $4C38 -> $4C35"),
]


def stage2_offset(addr):
    """Stage 2's file offset of a CPU address: $4000-$5FFF bank $68, $6000-$7FFF the text bank $6A."""
    assert 0x4000 <= addr < 0x8000
    return addr - 0x4000 if addr < 0x6000 else 0x4000 + addr - 0x6000


# ---- the image ----
def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def read_track(f, rec, n):
    out = bytearray()
    for i in range(n):
        f.seek((P.T2 + rec + i) * P.RAW)
        s = f.read(P.RAW)
        assert s[1:11] == b"\xff" * 10 and s[15] == 1, f"sector {P.T2 + rec + i} is not MODE1"
        out += s[P.HDR:P.HDR + P.DATA]
    return bytes(out)


def rec110_at(f):
    """rec 110's sector as the build's stage-2 file table has it."""
    st2 = read_track(f, P.STAGE2, STAGE2_N)
    rec, n = REC110
    key = bytes([rec >> 16, rec & 0xFF, (rec >> 8) & 0xFF])
    hits = [i for i in range(len(st2) - 8) if st2[i:i + 3] == key and st2[i + 3] == 4
            and st2[i + 6] == n and st2[i + 7] == 0]
    if len(hits) != 1:
        sys.exit(f"rec 110: {len(hits)} file-table records")
    r = st2[hits[0]:hits[0] + 3]
    return r[0] << 16 | r[2] << 8 | r[1]


def plan(f):
    """[(track-relative rec, offset in it, bytes now, new, address, what)], refused when a site
    holds neither the original nor the patched bytes."""
    out = []
    for rec, n, off_of, patches in ((rec110_at(f), REC110[1], lambda a: a - 0xA000, FIGHT),
                                    (P.STAGE2, STAGE2_N, stage2_offset, STAGE2)):
        data = read_track(f, rec, n)
        for addr, old, new, what in patches:
            old, new = bytes.fromhex(old), new if isinstance(new, bytes) else bytes.fromhex(new)
            assert len(old) >= len(new), hex(addr)
            off = off_of(addr)
            cur = data[off:off + len(new)]
            if cur != old[:len(new)] and cur != new:
                sys.exit(f"${addr:04x}: unexpected bytes {cur.hex()} (want {old[:len(new)].hex()}) - "
                         "not the build this tool knows; nothing written")
            out.append((rec, off, cur, new, addr, what))
    return out


def write_sectors(path, patches):
    raw = {}
    with open(path, "r+b") as f:
        for rec, off, cur, new, addr, what in patches:
            for i, b in enumerate(new):
                sec, pos = divmod((P.T2 + rec) * P.DATA + off + i, P.DATA)
                if sec not in raw:
                    f.seek(sec * P.RAW)
                    raw[sec] = bytearray(f.read(P.RAW))
                raw[sec][P.HDR + pos] = b
        for sec, s in sorted(raw.items()):
            f.seek(sec * P.RAW)
            f.write(P.fix_sector(s))
    return len(raw)


def held(path):
    if not os.path.exists(path):
        return False
    try:
        open(path, "r+b").close()
        return False
    except PermissionError:
        return True


def check():
    with open(MAIN_BIN, "rb") as f:
        for rec, off, cur, new, addr, what in plan(f):
            print(f"${addr:04x} rec {rec} +{off:#06x} {len(new):2d} B{'  (already patched)' if cur == new else ''}  {what}")
            print(f"     old {cur.hex()}\n     new {new.hex()}")


def apply():
    print(BANNER)
    for p in (MAIN_BIN, MAIN_CUE):
        if not os.path.exists(p):
            sys.exit(f"{p} missing - run pce/build/Build-PCE.bat first")
    if held(DEV_BIN):
        sys.exit(f"{DEV_BIN} is open (an emulator or a harness run) - close it; nothing written")
    before = {p: sha1(p) for p in (MAIN_BIN, MAIN_CUE)}
    with open(MAIN_BIN, "rb") as f:
        patches = plan(f)
    if any(cur == new for rec, off, cur, new, addr, what in patches):
        sys.exit("the normal image already carries the cheat - rebuild it with Build-PCE.bat")
    for rec, off, cur, new, addr, what in patches:
        print(f"  ${addr:04x} {cur[:6].hex()}.. -> {new[:6].hex()}..  {what}")
    print(f"copying {MAIN_BIN} -> {DEV_BIN} ...", flush=True)
    tmp = DEV_BIN + ".tmp"
    shutil.copyfile(MAIN_BIN, tmp)
    n = write_sectors(tmp, patches)
    os.replace(tmp, DEV_BIN)
    cue = open(MAIN_CUE, encoding="utf-8", newline="").read()
    if cue.count('"snatcher_pce.bin"') != 1:
        sys.exit("the cue does not name snatcher_pce.bin exactly once")
    open(DEV_CUE, "w", encoding="utf-8", newline="").write(cue.replace('"snatcher_pce.bin"', f'"{DEV}.bin"'))
    with open(DEV_BIN, "rb") as f:
        if any(cur != new for rec, off, cur, new, addr, what in plan(f)):
            sys.exit("read-back of the dev image failed")
    after = {p: sha1(p) for p in (MAIN_BIN, MAIN_CUE)}
    if after != before:
        sys.exit("the normal image CHANGED - this must never happen")
    print(f"{n} sectors rewritten (EDC/ECC regenerated); the normal image is byte-identical:")
    for p, h in after.items():
        print(f"  {h}  {os.path.relpath(p, ROOT)}")
    print(f"  {sha1(DEV_BIN)}  {os.path.relpath(DEV_BIN, ROOT)}")
    print(BANNER)


def run(cmd):
    print(">", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    return subprocess.run(cmd)


def chd():
    if not os.path.exists(DEV_CUE):
        sys.exit("no dev image - run apply first")
    if os.path.exists(DEV_CHD):
        os.remove(DEV_CHD)
    if run([CHDMAN, "createcd", "-i", DEV_CUE, "-o", DEV_CHD]).returncode:
        sys.exit("chdman createcd failed")
    if run([CHDMAN, "verify", "-i", DEV_CHD]).returncode:
        sys.exit("chdman verify failed")
    print(f"{sha1(DEV_CHD)}  {os.path.relpath(DEV_CHD, ROOT)}")


def push():
    """The CHD into LOCAL_ROMS and onto the MiSTer in a [dev-test] folder beside the [dev]
    one (push_mister.py's layout); the [dev] image's save, if the MiSTer has one and no
    [dev-test] save exists yet, copied to the [dev-test] name."""
    if not os.path.exists(DEV_CHD):
        sys.exit("no CHD - run chd first")
    if LOCAL_ROMS:
        if not os.path.isdir(LOCAL_ROMS):
            sys.exit(f"{LOCAL_ROMS} is not there")
        shutil.copyfile(DEV_CHD, os.path.join(LOCAL_ROMS, DEV + ".chd"))
        print(f"copied to {LOCAL_ROMS}/{DEV}.chd")
    rdir = f"{MISTER_GAMES}/{DEV}"
    if run(["ssh", *SSH_OPTS, MISTER_HOST, f'mkdir -p "{rdir}"']).returncode:
        sys.exit("mkdir on the MiSTer failed")
    # scp runs over SFTP (OpenSSH 9+): the remote path is literal, no shell quotes
    if run(["scp", *SSH_OPTS, DEV_CHD, f"{MISTER_HOST}:{rdir}/{DEV}.chd"]).returncode:
        sys.exit("scp failed")
    # the [dev] save, whatever case the card's file system kept ("[Dev]" on Luiz's), unless
    # the [dev-test] image has a save of its own already
    dst = f"{MISTER_SAVES}/{DEV}.sav"
    run(["ssh", *SSH_OPTS, MISTER_HOST,
         f'if [ ! -f "{dst}" ]; then for f in "{MISTER_SAVES}"/*; do '
         f'case "$(basename "$f" | tr A-Z a-z)" in "{DEV_SAVE.lower()}") cp "$f" "{dst}" && echo "copied $f";; esac; done; fi; '
         f'ls -la "{rdir}"; ls -la "{MISTER_SAVES}" | grep -i snatcher; sync'])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"check": check, "apply": apply, "chd": chd, "push": push}.get(cmd, lambda: sys.exit(__doc__))()
