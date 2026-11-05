"""DEV ONLY: trivial shootouts and START fast-forward, for testing on a MiSTer.

    python saturn/tools/devtest.py check      # dry run: the patch sites, nothing written
    python saturn/tools/devtest.py apply      # writes the [dev-test] image (see below)

NEVER part of a release. The Saturn twin of the PS1's ps1/tools/devfights.py.
The tool never writes the normal build: it reads the built image
`patched/saturn/Snatcher (Japan).cue` (+ its three tracks), patches the
MAIN_L.BIN it finds in track 1 (same size, same sectors, so no directory
record changes; the sectors get fresh EDC/ECC) and writes
`patched/saturn/Snatcher (Japan) [dev-test] (Track 1/2/3).bin` + `.cue`
(tracks 2 and 3 copied verbatim under the new name). It refuses when the
image's MAIN_L.BIN differs from patched/saturn/MAIN_L.BIN (a build half
done) and checks the normal image's files hash the same afterwards.
Run it after a normal Build-Saturn.bat.

What the dev exec changes (every shootout runs in MAIN_L.BIN: the fight
dispatcher 0x060C603C calls one of 15 handlers by the fight id u8
0x060F2C04; each calls the crosshair routine 0x060C62D8 every frame):

1. Any shot hits. The crosshair routine puts the fired cell (0..8, 9 =
   none) into a delay line 0x060FE8D0..D9 and leaves the shot that LANDS
   this frame (fired 8 frames ago) in u32 0x060FE8A4; every handler then
   compares that word with its target (a constant cell, an enemy's cell
   variable, a per-cell state table - fifteen different tests, no shared
   table like the PS1's G). The 16 pool words that hold 0x060C62D8 point at
   SPRAY instead, which calls the routine and, when a shot lands, presents
   the other eight cells to the handler on the next eight frames, one per
   frame (0..8, the landed cell skipped) - whatever the fight's own test
   accepts is hit, as if the player had aimed there. Fight 12 (B230, the
   snatcher holding Mika) kills the hostage on a shot landing in cells
   1/4/5/7 (0x060CA122: ctx+0x75A = 6, state 0x91 = game over): there every
   landing or sprayed cell in that set becomes a miss (9), the player's own
   shot included.
2. No damage. 0x060C69B0 (LIFE -= r4, hit flash, the hits-taken byte
   ctx+0x75A += 1, the hit sound) is the only writer of LIFE (u32
   0x060FE8A0; <= 0 -> state 0x90, death) and of the hits byte; it returns
   at once. Nothing in the fight code waits on either (the PS1's overlays
   froze at 6 hits; the Saturn's handlers only zero ctx+0x75A at fight start
   and the script reads it back as a variable), so no stalemate: enemies
   keep attacking harmlessly however long the player idles. Fight 5 (B130)
   is a race instead: LIFE drains by itself and the fight is won at 0 only
   if a shot landed in time (TIMER_FIGHT: no drain, won when the shot lands).
3. START held = fast-forward, in three script ops (main-thread context; the
   op table at 0x060E4F80.. is {handler, argument count}). Each stub starts
   with a START test and jumps to Konami's handler when it is not held, so a
   run without START executes the original loops (headless: frame-identical
   to the normal image through the B200 reconstruction, 49,410 frames).
   (a) 'Wait for the line' (0x060B8834, word 0x060E4FD0) loops on the frame
   wait while ctx+0x562 says a voice line (1) or a reel (2) plays; the
   interrupt-time sound service 0x060B1654 clears it when the line or the
   stream ends. FFVOICE = that loop; with START held and FF_MIN frames
   waited it calls the engine's own stop 0x060B2544(1) - what the play op
   does before a new sound: sound 0x10, a voice line retired at once, a
   reel stopped and waited out until the service sees its stream gone -
   then waits FF_SETTLE frames, because the subtitle payload slides its
   card out over 16 frames when a line ends and the engine opening its own
   box at once against that slide (+8 vs -8 a frame) hung the script (B230,
   the Act 2 end, found headless). The service itself cannot be hooked: it
   is an SCU interrupt handler registered once at boot, and a sound request
   from an interrupt would race the main thread. (b) 'Wait N frames'
   (0x060B85A0, word 0x060E5040) -> FFWAIT: FF_RATE frames counted per frame
   while START is held. (c) 'Wait until the reel timeline reaches m:s:f'
   (0x060B8AF4, word 0x060E5020: the cinematics' pictures keyed on a reel,
   e.g. the reconstruction's 23,800-frame reel 97) -> FFTIME: the timeline
   u32 ctx+0x6C0 (frames since the reel started, counted by the service)
   gets FF_RATE-1 more per frame while START is held; the reel is then cut
   by (a). START itself is untouched: it still toggles the Blaster in a
   fight and does what it did on the title and the keyboards. Waits on
   room animations (ctx+0x568) and on the Act 2 end card run at normal speed.

The stubs live in the spare invalid-SJIS runs of the glyph table
(satoptmenu.SPARE_RUNS: entries for SJIS second bytes 0xFD..0x13F that no
text can contain; satexec.used_codes() checked, the bytes must be zero) -
the build's own allocations (satlong, satoptmenu) take the first runs.

Headless: point any harness at `patched/saturn/Snatcher (Japan) [dev-test].cue`
- satmem.refresh_chunk_table(image=cue) copies the image's exec patches
(these included) into a resumed bookmark.
"""
import hashlib, os, shutil, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools')]

import numpy as np
import sh2asm, satdisc

OUT_DIR = os.path.join(ROOT, "patched", "saturn")
MAIN = "Snatcher (Japan)"
DEV = os.environ.get("DEVTEST_NAME") or "Snatcher (Japan) [dev-test]"   # another name while an emulator holds this one
EXEC = os.path.join(OUT_DIR, "MAIN_L.BIN")
PAIR_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")   # the build's; copied beside the cue for satplay
BASE = 0x060B0000
RAW, DATA = 2352, 2048

BANNER = r"""
##########################################################################
##  DEV-TEST: CHEAT BUILD - shots always hit, no LIFE loss, START=FF.   ##
##  Testing only. NEVER release, CHD-for-players or patch from this.    ##
##########################################################################
"""

# --- engine addresses (MAIN_L.BIN at 0x060B0000) -----------------------------
CROSSHAIR = 0x060C62D8          # per-frame crosshair/fire routine of every fight
CROSSHAIR_POOLS = [0x060C72E8, 0x060C73E0, 0x060C81F8, 0x060C8410, 0x060C85EC,
                   0x060C8898, 0x060C901C, 0x060C91E0, 0x060C9528, 0x060C977C,
                   0x060C9990, 0x060C9B80, 0x060C9E20, 0x060CA1DC, 0x060CA7AC,
                   0x060CB02C]  # every literal holding CROSSHAIR (sh2dis xref)
SHOT = 0x060FE8A4               # u32: the cell the shot landing this frame hit, 9 = none
FIGHT_ID = 0x060F2C04           # u8 ctx+0x754: 0..14
HOSTAGE_FIGHT = 12              # B230's second shootout (Mika)
HOSTAGE_CELLS = (1, 4, 5, 7)    # 0x060CA122: a shot there kills her
DAMAGE = 0x060C69B0             # LIFE -= r4, ctx+0x75A += 1, flash, sound 0x504
DAMAGE_ORIG = bytes.fromhex("2fe64f22")             # mov.l r14,@-r15 ; sts.l pr,@-r15
DAMAGE_NEW = bytes.fromhex("000b0009")              # rts ; nop
# Fight 5 (B130) is a race, not a duel: its handler drains LIFE by 1 every
# second frame and, at 0, wins (state 0x80) if a shot landed in cells 1/4/7
# (flag u32 0x060F2284) or dies (0x90). Here the drain is gone and the test
# at 0 reads the flag: the frame the shot lands, the fight is won.
TIMER_FIGHT = [
    (0x060C8FA6, "d21f612271ff2212", "0009000900090009", "fight 5: the LIFE drain (1 per 2 frames) removed"),
    (0x060C8FC4, "d117", "d111", "fight 5: the end test loads the hit flag 0x060F2284, not LIFE"),
    (0x060C8FCA, "895a", "8b5a", "fight 5: ... and goes on while it is 0 (set = state 0x80, won)"),
]
WAITV, WAITV_OP = 0x060B8834, 0x060E4FD0           # script op 'wait while ctx+0x562', its op-table word
STOP = 0x060B2544               # the engine's stop(mode): sound 0x10, voice retired, waits for the CD
WAITN, WAITN_OP = 0x060B85A0, 0x060E5040           # script op 'wait r4 frames', its op-table word
WAITT, WAITT_OP = 0x060B8AF4, 0x060E5020           # script op 'wait until the reel timeline reaches r5:r6:r7'
TIMELINE = 0x060F2B70           # u32 ctx+0x6C0: frames since the reel started (0 = not started)
FRAME_WAIT = 0x060B55A0
PAD_HELD = 0x060F2710           # u16 ctx+0x260: buttons held (START 0x0800)
START = 0x0800
SND_BUSY = 0x060F2A12           # u16 ctx+0x562: 1 a voice line, 2 a reel, 0 none
FF_MIN = 20                     # frames a sound plays before START may end it
FF_RATE = 16                    # 'wait N frames' speed while START is held
FF_SETTLE = 24                  # frames after a cut line before the script goes on (> the
                                # subtitle card's 16-frame slide-out: the engine opening its box
                                # against the payload's closing slide hung the box, B230 Act 2 end)


def spray_program():
    """SPRAY: called in place of CROSSHAIR (no arguments, returns nothing)."""
    mask = [1 if c in HOSTAGE_CELLS else 0 for c in range(9)] + [0]
    return [
        ("sts.l", "pr", "@-r15"),
        ("mov.l", f"=0x{CROSSHAIR:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("mov.l", f"=0x{SHOT:08x}", "r1"),
        ("mov.l", "@r1", "r2"),                 # r2 = the landed cell, 9 = none
        ("mov.l", "=state", "r3"),              # state+0 = cells left to spray, +1 = the landed cell
        ("mov", "#8", "r0"),
        ("cmp/hi", "r0", "r2"),                 # r2 > 8: nothing landed
        ("bt", "spray"),
        ("mov.b", "@r3", "r0"),                 # a shot landed: a spray already running goes on
        ("tst", "r0", "r0"),
        ("bf", "mask"),
        ("mov", "#9", "r0"),                    # else spray the 9 cells next
        ("mov.b", "r0", "@r3"),
        ("mov", "r3", "r4"),
        ("add", "#1", "r4"),
        ("bra", "mask"),
        ("mov.b", "r2", "@r4"),
        ("label", "spray"),
        ("mov.b", "@r3", "r0"),
        ("extu.b", "r0", "r0"),
        ("tst", "r0", "r0"),
        ("bt", "out"),                          # nothing to spray
        ("add", "#-1", "r0"),
        ("mov.b", "r0", "@r3"),
        ("mov", "#8", "r2"),
        ("sub", "r0", "r2"),                    # r2 = 8 - left = 0, 1, .. 8
        ("mov.b", "@(1,r3)", "r0"),
        ("extu.b", "r0", "r0"),
        ("cmp/eq", "r0", "r2"),
        ("bt", "out"),                          # the cell the shot already tried
        ("label", "mask"),
        ("mov.l", f"=0x{FIGHT_ID:08x}", "r4"),
        ("mov.b", "@r4", "r0"),
        ("extu.b", "r0", "r0"),
        ("cmp/eq", f"#{HOSTAGE_FIGHT}", "r0"),
        ("bf", "write"),
        ("mov.l", "=masktab", "r4"),
        ("add", "r2", "r4"),
        ("mov.b", "@r4", "r0"),
        ("tst", "r0", "r0"),
        ("bt", "write"),
        ("mov", "#9", "r2"),                    # the hostage's cell: a miss
        ("label", "write"),
        ("mov.l", "r2", "@r1"),
        ("label", "out"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("nop",),
        ("pool",),
        ("label", "state"),
        (".long", 0),
        ("label", "masktab"),
        *[(".word", mask[i] << 8 | mask[i + 1]) for i in range(0, 10, 2)],
    ]


def _start_held(reg, skip):
    """T := START held; branch to `skip` when it is not (clobbers r0 and reg)."""
    return [
        ("mov.l", f"=0x{PAD_HELD:08x}", reg),
        ("mov.w", "@" + reg, "r0"),
        ("mov", "#8", reg),
        ("shll8", reg),                          # 0x0800
        ("tst", reg, "r0"),
        ("bt", skip),
    ]


def _guard(orig):
    """Entry of an op stub: START not held -> jump to the original handler
    (arguments untouched), so a run without START executes Konami's loop."""
    return [
        ("mov.l", f"=0x{PAD_HELD:08x}", "r1"),
        ("mov.w", "@r1", "r0"),
        ("mov", "#8", "r1"),
        ("shll8", "r1"),
        ("tst", "r1", "r0"),
        ("bf", "ff"),
        ("mov.l", f"=0x{orig:08x}", "r0"),
        ("jmp", "@r0"),
        ("nop",),
        ("label", "ff"),
    ]


def ffvoice_program():
    """FFVOICE: the script op 'wait for the line' (WAITV) with START: while
    ctx+0x562 says a voice line or reel plays, wait a frame; with START held
    and FF_MIN frames waited, run the engine's own stop (STOP(1), as the play
    op does before a new sound) and go on waiting until the sound is gone."""
    return [
        *_guard(WAITV),
        ("mov.l", "r8", "@-r15"),
        ("sts.l", "pr", "@-r15"),
        ("mov", "#0", "r8"),
        ("label", "loop"),
        ("mov.l", f"=0x{SND_BUSY:08x}", "r1"),
        ("mov.w", "@r1", "r0"),
        ("tst", "r0", "r0"),
        ("bt", "done"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("add", "#1", "r8"),
        *_start_held("r1", "loop"),
        ("mov", f"#{FF_MIN}", "r1"),
        ("cmp/hs", "r1", "r8"),
        ("bf", "loop"),
        ("mov.l", f"=0x{STOP:08x}", "r0"),
        ("jsr", "@r0"),
        ("mov", "#1", "r4"),
        ("mov", f"#{FF_SETTLE}", "r8"),          # then let the subtitle payload slide its card out
        ("label", "settle"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("dt", "r8"),
        ("bf", "settle"),
        ("bra", "loop"),
        ("nop",),
        ("label", "done"),
        ("lds.l", "@r15+", "pr"),
        ("rts",),
        ("mov.l", "@r15+", "r8"),
    ]


def fftime_program():
    """FFTIME(r5 min, r6 s, r7 frames): WAITT - wait until the reel timeline
    u32 ctx+0x6C0 (frames since the reel started, counted by the interrupt
    service while non-zero) reaches r5*3600 + r6*60 + r7 - with START held
    adding FF_RATE-1 more per frame (once the reel has started it)."""
    raw = lambda w: (".word", w)
    return [
        *_guard(WAITT),
        ("mov.l", "r8", "@-r15"),
        ("mov.l", "r9", "@-r15"),
        ("sts.l", "pr", "@-r15"),
        ("mov.l", "=3600", "r1"),
        raw(0x0517),                             # mul.l r1,r5
        raw(0x081A),                             # sts macl,r8
        ("mov", "#60", "r1"),
        raw(0x0617),                             # mul.l r1,r6
        raw(0x011A),                             # sts macl,r1
        ("add", "r1", "r8"),
        ("add", "r7", "r8"),                     # r8 = the target frame
        ("mov.l", f"=0x{TIMELINE:08x}", "r9"),
        ("label", "loop"),
        ("mov.l", "@r9", "r0"),
        ("cmp/hs", "r8", "r0"),
        ("bt", "done"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        *_start_held("r1", "loop"),
        ("mov.l", "@r9", "r0"),
        ("tst", "r0", "r0"),
        ("bt", "loop"),                          # the reel has not started its count
        ("add", f"#{FF_RATE - 1}", "r0"),
        ("bra", "loop"),
        ("mov.l", "r0", "@r9"),
        ("label", "done"),
        ("lds.l", "@r15+", "pr"),
        ("mov.l", "@r15+", "r9"),
        ("rts",),
        ("mov.l", "@r15+", "r8"),
    ]


def ffwait_program():
    """FFWAIT(r4 = frames): WAITN with START held counting FF_RATE per frame."""
    return [
        *_guard(WAITN),
        ("mov.l", "r8", "@-r15"),
        ("mov.l", "r9", "@-r15"),
        ("sts.l", "pr", "@-r15"),
        ("mov", "r4", "r9"),
        ("mov", "#0", "r8"),
        ("label", "loop"),
        ("cmp/hs", "r9", "r8"),
        ("bt", "done"),
        ("mov.l", f"=0x{FRAME_WAIT:08x}", "r0"),
        ("jsr", "@r0"),
        ("nop",),
        ("add", "#1", "r8"),
        *_start_held("r1", "loop"),
        ("bra", "loop"),
        ("add", f"#{FF_RATE - 1}", "r8"),
        ("label", "done"),
        ("lds.l", "@r15+", "pr"),
        ("mov.l", "@r15+", "r9"),
        ("rts",),
        ("mov.l", "@r15+", "r8"),
    ]


def spare_runs(exe, sizes):
    """Addresses for blocks of `sizes` bytes in the spare invalid-SJIS runs of
    the glyph table, one block per run, skipping runs the build used."""
    import satexec, satoptmenu
    used = satexec.used_codes()
    out = []
    want = list(sizes)
    for lo, hi in satoptmenu.SPARE_RUNS:
        if not want:
            break
        start = (lo + 3) & ~3
        end = start + want[0]
        if end > hi:
            continue
        first = satexec.TABLE_LO + (start - satexec.TABLE_ADDR) // 2
        last = satexec.TABLE_LO + (end - 1 - satexec.TABLE_ADDR) // 2
        if any(first <= c <= last for c in used) or any(exe[start - BASE:end - BASE]):
            continue
        assert all(((c & 0xFF) >= 0xFD or (c & 0xFF) < 0x40) for c in range(first, last + 1)), hex(first)
        out.append(start)
        want.pop(0)
    if want:
        sys.exit(f"devtest: no spare run left for {want}")
    return out


def build(exe):
    """[(addr, old bytes, new bytes, what)] for `exe` (the built MAIN_L.BIN)."""
    o = lambda a: a - BASE
    out = []
    progs = [("SPRAY", spray_program()), ("FFVOICE", ffvoice_program()),
             ("FFTIME", fftime_program()), ("FFWAIT", ffwait_program())]
    sizes = [len(sh2asm.asm(p, 0x060E846C)[0]) for _, p in progs]
    addrs = spare_runs(exe, sizes)
    at = {}
    for (name, prog), addr in zip(progs, addrs):
        code, _ = sh2asm.asm(prog, addr)
        at[name] = addr
        out.append((addr, exe[o(addr):o(addr) + len(code)], code, f"{name} stub ({len(code)} B, spare glyph-table run)"))
    lw = lambda v: struct.pack(">I", v)
    for p in CROSSHAIR_POOLS:
        out.append((p, lw(CROSSHAIR), lw(at["SPRAY"]), "fight handler: crosshair routine -> SPRAY"))
    out.append((DAMAGE, DAMAGE_ORIG, DAMAGE_NEW, "damage 0x060C69B0: returns at once (no LIFE loss)"))
    for addr, old, new, what in TIMER_FIGHT:
        out.append((addr, bytes.fromhex(old), bytes.fromhex(new), what))
    out.append((WAITV_OP, lw(WAITV), lw(at["FFVOICE"]), "script op 'wait for the line' -> FFVOICE"))
    out.append((WAITN_OP, lw(WAITN), lw(at["FFWAIT"]), "script op 'wait N frames' -> FFWAIT"))
    out.append((WAITT_OP, lw(WAITT), lw(at["FFTIME"]), "script op 'wait for reel time m:s:f' -> FFTIME"))
    return out


def patch_exec(exe):
    exe = bytearray(exe)
    for addr, old, new, what in build(bytes(exe)):
        cur = bytes(exe[addr - BASE:addr - BASE + len(old)])
        if cur != old:
            sys.exit(f"devtest: {addr:#010x} holds {cur.hex()}, expected {old.hex()} - not the exec this tool knows")
        exe[addr - BASE:addr - BASE + len(new)] = new
        print(f"  {addr:#010x} {old[:8].hex():>16} -> {new[:8].hex():<16} {what}")
    return bytes(exe)


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def cue_files(cue):
    return [line.split('"')[1] for line in open(cue, encoding="utf-8") if line.strip().upper().startswith("FILE")]


def check():
    exe = open(EXEC, "rb").read()
    for addr, old, new, what in build(exe):
        print(f"{addr:#010x} {len(new):3d} B  {what}")
        if len(new) > 8:
            print(sh2asm.check(new, addr))
        else:
            print(f"   old {old.hex()}  new {new.hex()}")


def apply():
    print(BANNER)
    main_cue = os.path.join(OUT_DIR, MAIN + ".cue")
    dev_cue = os.path.join(OUT_DIR, DEV + ".cue")
    files = cue_files(main_cue)
    assert len(files) == 3 and files[0] == f"{MAIN} (Track 1).bin", files
    t1 = os.path.join(OUT_DIR, files[0])
    before = {f: sha1_file(os.path.join(OUT_DIR, f)) for f in files + [MAIN + ".cue", "MAIN_L.BIN"]}
    with open(t1, "rb") as f:
        rec = next(r for r in satdisc.root_records(f) if r[2] == "MAIN_L.BIN")
    lba, size = rec[3], rec[4]
    n = (size + DATA - 1) // DATA
    with open(t1, "rb") as f:
        f.seek(lba * RAW)
        raw = f.read(n * RAW)
    img_exe = b"".join(raw[i * RAW + 16:i * RAW + 16 + DATA] for i in range(n))[:size]
    exe = open(EXEC, "rb").read()
    if img_exe != exe:
        sys.exit("devtest: the image's MAIN_L.BIN differs from patched/saturn/MAIN_L.BIN - "
                 "finish the normal build first; nothing written")
    dev = patch_exec(exe)
    assert len(dev) == len(exe)
    outs = [f.replace(MAIN, DEV, 1) for f in files]
    for o_ in outs + [DEV + ".cue"]:
        p = os.path.join(OUT_DIR, o_)
        if os.path.exists(p):
            try:
                open(p, "r+b").close()
            except PermissionError:
                sys.exit(f"devtest: {p} is held open (an emulator?) - close it; nothing written")
    # track 1: the main one with MAIN_L.BIN's sectors rebuilt
    tmp = os.path.join(OUT_DIR, outs[0] + ".tmp")
    print(f"copying track 1 -> {outs[0]} ...")
    shutil.copyfile(t1, tmp)
    secs = np.frombuffer(raw, dtype=np.uint8).reshape(n, RAW).copy()
    body = bytearray(b"".join(raw[i * RAW + 16:i * RAW + 16 + DATA] for i in range(n)))
    body[:size] = dev
    hdr = satdisc.headers(list(range(lba, lba + n)))
    assert (secs[:, :16] == hdr).all(), "MAIN_L.BIN's sectors carry unexpected headers"
    secs[:, 16:2064] = np.frombuffer(bytes(body), dtype=np.uint8).reshape(n, DATA)
    satdisc.fix_sectors(secs)
    with open(tmp, "r+b") as f:
        f.seek(lba * RAW)
        f.write(secs.tobytes())
    os.replace(tmp, os.path.join(OUT_DIR, outs[0]))
    for src, dst in zip(files[1:], outs[1:]):
        print(f"copying {src} -> {dst} ...")
        shutil.copyfile(os.path.join(OUT_DIR, src), os.path.join(OUT_DIR, dst))
    cue = open(main_cue, encoding="utf-8", newline="").read()
    for src, dst in zip(files, outs):
        cue = cue.replace(f'"{src}"', f'"{dst}"')
    open(dev_cue, "w", encoding="utf-8", newline="").write(cue)
    if os.path.exists(PAIR_TABLE):
        shutil.copyfile(PAIR_TABLE, os.path.join(OUT_DIR, DEV + ".pair_table.json"))
    # read back
    with open(os.path.join(OUT_DIR, outs[0]), "rb") as f:
        f.seek(lba * RAW)
        back = f.read(n * RAW)
    got = b"".join(back[i * RAW + 16:i * RAW + 16 + DATA] for i in range(n))[:size]
    if got != dev:
        sys.exit("devtest: read-back of the dev exec failed")
    after = {f: sha1_file(os.path.join(OUT_DIR, f)) for f in before}
    for f in before:
        if before[f] != after[f]:
            sys.exit(f"devtest: {f} CHANGED - investigate")
        print(f"  unchanged {before[f]}  {f}")
    print(f"wrote {dev_cue} (+ 3 tracks); MAIN_L.BIN at LBA {lba}, {size} bytes")
    for o_ in outs:
        print(f"  {sha1_file(os.path.join(OUT_DIR, o_))}  {o_}")
    print(BANNER)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "apply":
        apply()
    elif cmd == "check":
        check()
    else:
        sys.exit(__doc__)
