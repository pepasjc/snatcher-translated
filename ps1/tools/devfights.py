"""DEV ONLY: trivial shootouts, for replaying fights on real hardware.

    python ps1/tools/devfights.py apply      # writes the dev image, see below
    python ps1/tools/devfights.py check      # dry run: show the patch sites
    python ps1/tools/devfights.py stage      # only the exec + work/devfights/patched/

NEVER part of a release. The tool never writes patched/: it copies the
current built image `patched/Snatcher (Japan).bin` to
`patched/Snatcher (Japan) [dev-test].bin` (+ .cue) and rewrites only the
exec's sectors there (same LBA, same size, so no directory record changes).
patched/SLPS_001.54 and every other patched/ file stay as the build left
them; a later Build-Image/patch_disc run never sees the cheat. Run it after
a normal build (the main image must be current: the tool refuses when the
image's exec differs from patched/SLPS_001.54).

What the dev build changes (all in the exec; every fight overlay SXX_B07x
reaches the hit test and the damage handler through the exec routines):

1. Auto-hit. The fire routine (0x80055B74) tests the crosshair cell against
   the per-cell target table G = ctx+0x1E10 (G[cell] == 1 = something
   hittable there, set by the fight overlay), then writes G[0x14] = cell
   and F[0x10] = 1 (F = ctx+0x1DF0) for the overlay's hit test. The patch
   replaces that test (0x80055CB4..0x80055D14, 25 words in place, the fight
   0xC shot sound kept) with a scan: the crosshair cell first, then cells
   8..0; the first G[i] == 1 the mask allows becomes the shot. So any shot,
   wherever the crosshair is, hits what the game itself would accept
   (insector body, snatcher head...). Fight 0xC (B230, the snatcher holding
   the hostage, overlay SXX_B07A) marks the hostage's cells 1/4/5/7 in G too
   and its head in F[4] when it shows; the mask leaves those four out there,
   so a shot while the head is hidden is a plain miss.
2. No damage. The damage handler (0x80054EF4) runs while F[0x13] (set by
   the overlay when the enemy hits you) is non-zero, animates the LIFE bar
   and bumps the damage counter 0x80071E20 (dead at 7). The patch clears
   F[0x13] and skips the handler, so LIFE never drops. The overlays keep
   their own count of attacks that landed in ctx+0x1DEB (ctx+0x195C+0x48F;
   the exec zeroes it at fight start, 0x80053200) and at 6 (= LIFE
   gone) freeze every enemy (G[9..17] = 0x64) and wait for the exec's death
   flag F[0x17], which never comes: a stalemate (MiSTer, B220 maze, the
   insector parked on its attack cell). The handler (run every fight frame,
   s0 = ctx) now zeroes that count each frame, in the load-delay nop.

3. Fast-forward: hold START through a voiced scene or reel and each XA
   stream ends early through the driver's own end-of-stream path, with the
   timeline keyed on it run 16x (see the FF_* notes below). Without START
   the game runs frame-identical to the normal build. START also submits the
   keyboard and opens nothing else in game; at the title it starts New Game.

Play: SELECT draws the blaster, then mash fire.
`work/devfights/patched/` is a copy of patched/ with the dev exec, for the
headless harness: SNATCHER_PATCHED=work/devfights/patched (raminject would
otherwise put the normal exec back into a resumed state).
"""
import os, shutil, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from mipsasm import Asm

PATCHED = os.path.join(ROOT, "patched")
EXEC = os.path.join(PATCHED, "SLPS_001.54")
MAIN = "Snatcher (Japan)"
DEV = "Snatcher (Japan) [dev-test]"
STAGE = os.path.join(WORK, "devfights")
STAGE_PATCHED = os.path.join(STAGE, "patched")
TEXT = 0x80028000


def foff(addr):
    return addr - TEXT + 0x800


BANNER = r"""
##########################################################################
##  DEV-FIGHTS: CHEAT BUILD - shots always hit, no LIFE loss, START=FF. ##
##  Testing only. NEVER release, CHD-for-players or patch from this.    ##
##########################################################################
"""

# fire routine's hit test: original 25 words at 0x80055CB4..0x80055D14
HIT_AT, HIT_END, HIT_OUT = 0x80055CB4, 0x80055D18, 0x80055D2C
HIT_ORIG = bytes.fromhex(
    "e01d238e0c00023403006214000504349ac4000ce8ff05240a80053c4c1da58c0a80043c"
    "501d848c0000a290000000002110820000004390010002340e006214000000000000a290"
    "00000000140082a00a80033c4c1d638c010002344b570108100062a0")
ALL_CELLS = 0x1FF
CORNERS_FIGHT, CORNERS_CELLS = 0xC, 0x14D    # cells 0,2,3,6,8 (hostage: 1,4,5,7)


def srlv(rd, rt, rs):
    from mipsasm import REG
    return REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11 | 0x06


def hit_code():
    """$s1 = ctx in the fire routine (0x80055B98 move s1,a0)."""
    a = Asm(HIT_AT)
    a.lw("$t3", 0x1DE0, "$s1")                            # fight id
    a.ori("$t2", "$zero", CORNERS_FIGHT)
    a.bne("$t3", "$t2", "scan")
    a.ori("$t3", "$zero", ALL_CELLS)                      # mask: every cell
    a.ori("$a0", "$zero", 0x500)                          # the original
    a.jal(0x80031268)                                     # fight-0xC shot
    a.addiu("$a1", "$zero", -0x18)                        # sound, kept
    a.ori("$t3", "$zero", CORNERS_CELLS)                  # never the hostage
    a.label("scan")
    a.lbu("$v0", 0x1DF0, "$s1")                           # crosshair cell first
    a.ori("$t1", "$zero", 1)
    a.ori("$t2", "$zero", 9)
    a.label("loop")
    a.addu("$t0", "$s1", "$v0")
    a.lbu("$v1", 0x1E10, "$t0")                           # G[cell]
    a.word(srlv("$t4", "$t3", "$v0"))                     # mask >> cell
    a.bne("$v1", "$t1", "next")
    a.andi("$t4", "$t4", 1)
    a.bne("$t4", "$zero", "hit")
    a.nop()
    a.label("next")
    a.beq("$t2", "$zero", "out")
    a.addiu("$t2", "$t2", -1)
    a.b("loop")
    a.addu("$v0", "$t2", "$zero")                         # then cells 8..0
    a.label("hit")
    a.sb("$v0", 0x1E24, "$s1")                            # G[0x14] = shot cell
    a.b("out")
    a.sb("$t1", 0x1E00, "$s1")                            # F[0x10] = hit
    a.label("out")                                        # = HIT_END (assert)
    return a


# Fast-forward (hold START through voiced scenes and reels).
#
# The script, the voice band (faces, mouths) and the cinematics keep their
# timeline on ctx+0x1B20, the frames the XA status read "playing" (0x800490B4
# adds 1 per frame, zeroed at each stream start); the wait task 0x8004AAE0
# and the band's tables (0x80049144, 0x80049574) step as it passes each
# entry, and the script waits for the stream to end before the next one.
#   1. While START is held the count runs FF_RATE times faster (a jal in the
#      load-delay nop at 0x80049100; its delay slot is the original +1).
#   2. The driver's per-frame end check (0x8002E504) reads the position
#      through a stub that answers "at the end" once START is held, the
#      stream has played FF_MIN sectors, the drive is inside it, and the
#      count has passed 4/5 of its length in sectors (a mono line's frames;
#      a stereo reel's timeline is done by then). The normal end-of-stream
#      path then fades and stops it. A stream with no count kept (the
#      count task ctx+0x202C is not on step 0x800490B4: plain dialogue, the
#      B220 escape lines) ends as soon as it has played FF_MIN sectors. The stop path's resume point
#      (0x8002F3D8) reads the same stub, so a chained stream starts where the
#      ended one would have finished. Ending a stream sets the count to
#      PLAYED, so whatever is left of its timeline passes.
# Found on B200/B210: ending a stream at once (no fast count) left the morgue
# band waiting for ever, and jumping a reel's whole picture timeline in one
# frame left the next stream's seek hanging (the Chief's reel, B210).
FF_CALL, FF_STUB, FF_POS = 0x8002E504, 0x80054F20, 0x80031968
FF_CALL2 = 0x8002F3D8
COUNT_CALL, COUNT_STUB = 0x80049100, 0x80055000
FF_START_LBA, FF_END_LBA = 0x800AB654, 0x800AB658
COUNT_TASK, COUNT_STEP = 0x202C, 0x800490B4    # ctx task that keeps the count
START = 0x0800
FF_RATE = 16                        # playback-count speed while START is held
FF_MIN = 60                         # sectors played before START may end it
PLAYED = 0x00100000
DEAD_END = 0x80055444               # end of the dead damage-handler body


def _start_held(a, reg, skip):
    a.lui(reg, 0x800B); a.lw(reg, -0x409C, reg)          # ctx
    a.nop()
    a.lhu(reg, 0x3C, reg)                                 # held buttons
    a.nop()
    a.andi(reg, reg, START)
    a.beq(reg, "$zero", skip)


def count_stub():
    a = Asm(COUNT_STUB)
    _start_held(a, "$t0", "ret")
    a.nop()
    a.addiu("$v0", "$v0", FF_RATE - 1)
    a.label("ret")
    a.jr("$ra")
    a.nop()
    return a.assemble()


def ff_stub():
    a = Asm(FF_STUB)
    a.addiu("$sp", "$sp", -0x18)
    a.sw("$ra", 0x10, "$sp")
    a.jal(FF_POS)                                         # v0 = drive position
    a.nop()
    a.lw("$ra", 0x10, "$sp")
    a.addiu("$sp", "$sp", 0x18)
    _start_held(a, "$v1", "ret")
    a.lui("$v1", (FF_START_LBA + 0x8000) >> 16)
    a.lw("$t1", (FF_START_LBA & 0xFFFF) - 0x10000, "$v1")  # start
    a.lw("$v1", (FF_END_LBA & 0xFFFF) - 0x10000, "$v1")    # end
    a.subu("$t0", "$v0", "$t1")                           # sectors played
    a.word(0x29080000 | FF_MIN)                           # slti t0,t0,FF_MIN
    a.bne("$t0", "$zero", "ret")
    a.sltu("$t0", "$v0", "$v1")                           # drive inside THIS stream
    a.beq("$t0", "$zero", "ret")                          # (not still on the last one)
    a.subu("$t3", "$v1", "$t1")                           # length in sectors
    a.lui("$t2", 0x800B); a.lw("$t2", -0x409C, "$t2")    # ctx
    a.sll("$t3", "$t3", 2)                                # 4 x length
    a.lw("$t4", 0x1B20, "$t2")                            # playback count
    a.lw("$t5", COUNT_TASK + 0x10, "$t2")                 # its task's step
    a.lui("$t6", COUNT_STEP >> 16)
    a.ori("$t6", "$t6", COUNT_STEP & 0xFFFF)
    a.bne("$t5", "$t6", "end")                            # no count kept: end now
    a.sll("$t0", "$t4", 2)
    a.addu("$t0", "$t0", "$t4")                           # 5 x count
    a.sltu("$t0", "$t0", "$t3")
    a.bne("$t0", "$zero", "ret")
    a.label("end")
    a.lui("$t4", PLAYED >> 16)
    a.sw("$t4", 0x1B20, "$t2")                            # what is left passes
    a.addu("$v0", "$v1", "$zero")                         # "at the end"
    a.label("ret")
    a.jr("$ra")
    a.nop()
    return a.assemble()


def patches():
    """[(ram, original bytes, new bytes, what)]"""
    a = hit_code()
    code = a.assemble()
    assert a.labels()["out"] == HIT_END, hex(a.labels()["out"])
    # 'out' lands on HIT_END; re-target the two branches there to HIT_OUT
    # (the routine's epilogue) - HIT_END is the other path's own code.
    words = list(struct.unpack(f"<{len(code)//4}I", code))
    for i, w in enumerate(words):
        if w >> 26 == 4:                                  # beq
            pc = HIT_AT + 4 * i
            tgt = pc + 4 + (((w & 0xFFFF) ^ 0x8000) - 0x8000) * 4
            if tgt == HIT_END:
                words[i] = (w & 0xFFFF0000) | (((HIT_OUT - pc - 4) >> 2) & 0xFFFF)
    code = struct.pack(f"<{len(words)}I", *words)
    assert len(code) == HIT_END - HIT_AT == len(HIT_ORIG)
    stub, cstub = ff_stub(), count_stub()
    jal = lambda t: struct.pack("<I", 0x0C000000 | (t >> 2) & 0x03FFFFFF)
    ex = open(EXEC, "rb").read()
    dead = lambda at, n: ex[foff(at):foff(at) + n]
    assert FF_STUB + len(stub) <= COUNT_STUB and COUNT_STUB + len(cstub) <= DEAD_END
    return [
        (FF_STUB, dead(FF_STUB, len(stub)), stub, "fast-forward: end-check stub (dead damage-handler body)"),
        (COUNT_STUB, dead(COUNT_STUB, len(cstub)), cstub, "fast-forward: playback-count stub"),
        (COUNT_CALL, bytes(4), jal(COUNT_STUB), "playback count (0x800490B4): nop -> jal count stub"),
        (FF_CALL, jal(FF_POS), jal(FF_STUB), "XA end check: position via the START stub"),
        (FF_CALL2, jal(FF_POS), jal(FF_STUB), "XA stop: the saved resume position via the START stub"),
        (HIT_AT, HIT_ORIG, code, "fire: any shot hits a cell the game marks hittable"),
        (0x80054F10, bytes.fromhex("13004290"), bytes.fromhex("130040a0"),
         "damage: lbu v0,0x13(v0) -> sb zero,0x13(v0) (clear the hit flag)"),
        (0x80054F14, bytes.fromhex("00000000"), bytes.fromhex("eb1d00a2"),
         "damage: nop -> sb zero,0x1DEB(s0) (the overlays' attack count; at 6 they freeze)"),
        (0x80054F18, bytes.fromhex("4b014010"), bytes.fromhex("4b010010"),
         "damage: beqz v0,0x80055448 -> b 0x80055448 (skip LIFE loss)"),
    ]


def patch_exec(data):
    data = bytearray(data)
    for ram, old, new, what in patches():
        o = foff(ram)
        cur = bytes(data[o:o + len(old)])
        if cur == new:
            print(f"  {ram:08x} already patched ({what})")
            continue
        if cur != old:
            sys.exit(f"{ram:08x}: unexpected bytes {cur.hex()} - not the exec this tool knows")
        data[o:o + len(old)] = new
        print(f"  {ram:08x} {old[:8].hex()}.. -> {new[:8].hex()}.. {what}")
    return bytes(data)


def exec_lba():
    import json
    rel = json.load(open(os.path.join(WORK, "relocations.json")))
    if "SLPS_001.54" in rel:
        return rel["SLPS_001.54"]
    return json.load(open(os.path.join(WORK, "lba_map.json")))["SLPS_001.54"][0]


def read_image_file(path, lba, size):
    out = bytearray()
    with open(path, "rb") as f:
        for s in range((size + 2047) // 2048):
            f.seek((lba + s) * 2352 + 24)
            out += f.read(2048)
    return bytes(out[:size])


def stage(dev_exec):
    """work/devfights/patched/ = patched/'s files with the dev exec."""
    os.makedirs(STAGE_PATCHED, exist_ok=True)
    for name in os.listdir(PATCHED):
        src = os.path.join(PATCHED, name)
        if name.upper().endswith(".BIN") and os.path.isfile(src) and "(Japan)" not in name:
            shutil.copyfile(src, os.path.join(STAGE_PATCHED, name))
    open(os.path.join(STAGE_PATCHED, "SLPS_001.54"), "wb").write(dev_exec)
    open(os.path.join(STAGE, "SLPS_001.54"), "wb").write(dev_exec)
    print(f"staged {STAGE_PATCHED} (SNATCHER_PATCHED for the harness)")


def apply(write_image=True):
    print(BANNER)
    from patch_disc import fix_sector
    base = open(EXEC, "rb").read()
    lba = exec_lba()
    main_bin = os.path.join(PATCHED, MAIN + ".bin")
    if write_image and read_image_file(main_bin, lba, len(base)) != base:
        sys.exit("the main image's exec differs from patched/SLPS_001.54 - "
                 "run the normal build first; nothing written")
    dev = patch_exec(base)
    assert len(dev) == len(base)
    stage(dev)
    if not write_image:
        return
    out_bin = os.path.join(PATCHED, DEV + ".bin")
    if os.path.exists(out_bin):
        try:
            open(out_bin, "r+b").close()
        except PermissionError:
            sys.exit(f"{out_bin} is open in an emulator - close it; nothing written")
    print(f"copying {main_bin} -> {out_bin} ...")
    tmp = out_bin + ".tmp"
    shutil.copyfile(main_bin, tmp)
    with open(tmp, "r+b") as f:
        for s in range((len(dev) + 2047) // 2048):
            f.seek((lba + s) * 2352)
            sec = bytearray(f.read(2352))
            assert sec[1:11] == bytes([0xFF] * 10), f"sector {lba + s} has no sync"
            chunk = dev[s * 2048:(s + 1) * 2048]
            sec[24:24 + len(chunk)] = chunk
            f.seek((lba + s) * 2352)
            f.write(fix_sector(sec))
    try:
        os.replace(tmp, out_bin)
    except PermissionError:
        os.remove(tmp)
        sys.exit(f"{out_bin} is held open (an emulator or a harness run) - "
                 "close it and rerun; nothing written")
    cue = open(os.path.join(PATCHED, MAIN + ".cue"), encoding="utf-8").read()
    open(os.path.join(PATCHED, DEV + ".cue"), "w", encoding="utf-8").write(
        cue.replace(MAIN + ".bin", DEV + ".bin"))
    if read_image_file(out_bin, lba, len(dev)) != dev:
        sys.exit("read-back of the dev exec failed")
    print(f"wrote {out_bin} (+ .cue); exec at LBA {lba}, {len(dev)} bytes")
    print(BANNER)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "apply":
        apply()
    elif cmd == "stage":
        print(BANNER)
        stage(patch_exec(open(EXEC, "rb").read()))
    elif cmd == "check":
        for ram, old, new, what in patches():
            print(f"{ram:08x} {len(new) // 4:2d} words  {what}")
            print(f"   old {old.hex()}\n   new {new.hex()}")
        patch_exec(open(EXEC, "rb").read())
    else:
        sys.exit(__doc__)
