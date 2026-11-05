"""Bring a captured RAM image up to the current build.

A savestate (Beetle bookmark, Redux .sstate, RetroArch .state) freezes the
scene bank, the subtitle payload and the exec code of the build it was taken
against. Every tool that resumes one must swap in:

  * the current bank at 0x8010D000 (and clear the payload scratch);
  * the current payload blob at HIRAM, with the magic word set the way the
    loader hook's `done` callback leaves it - a bookmark taken mid-scene
    never saw that load;
  * the exec's code and read-only tables - the trampoline, the loader hook
    and its per-scene table, the scene table - but NEVER its globals.

`put(addr, data)` writes `data` at RAM address `addr`; each host supplies
its own (ctypes memmove into the core, or slicing a decompressed state).
"""
import os, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

# SNATCHER_PATCHED points the injection at another build's files (a baseline
# extracted from an older image, say) so a bookmark can be replayed against it.
PATCHED = os.environ.get('SNATCHER_PATCHED') or os.path.join(ROOT, 'patched')
BANK_RAM = 0x8010D000
# the memory-card bank ISZ_B050 (the save screen's messages) is loaded once
# at boot and stays resident past the scene bank slot; a bookmark carries
# its build's copy, and a pair rebuild since then drew its text as garbage
# (the Save probe of 2026-09-14: 'Do not remove the memory card' unreadable)
SYS_BANK, SYS_BANK_RAM = 'B050', 0x80118000
SCRATCH = 0x801FC000
from hiram import HIRAM, LONGS       # the payload blob, the longs blob
MAGIC = 0x53554253                 # 'SUBS'
EXEC_RAM, EXEC_HDR = 0x80028000, 0x800
# pure code / read-only data of the exec: text, the scene table, the font and
# table block (the loader hook lives in dead glyph slots), the dead-region
# stubs. 0x8009E2B0 onward is engine-written and must stay the state's own.
# repoint.py's regions are read-only too: the keylen clamp (0x8009E204),
# the remap stub + table part 2 (0x8009E330, 0x200) and table part 1
# (0x8009F628, 0x3F8). A bookmark taken before a bank's longs changed kept
# the old table, and a stale entry pointed Squad room at the offset that now
# held Mechanic room (v0.6). The graphics/overlay file tables (exec file
# 0x4b4e4 on, 12-byte {lba, size, pad} records, up to the font) are read-only
# too - bookmarks differ from the exec there only in the records our tools
# rewrite - and without them a bookmark loads a relocated file from its old
# slot (CXF_B080 moved past the image end: the old composite came back).
CODE_RANGES = ((0x80028000, 0x80070000), (0x80071E8C, 0x80071E8C + 39 * 12),
               (0x80072CE4, 0x80074380),
               (0x80074380, 0x80083BB4), (0x8009E204, 0x8009E2B0),
               (0x8009E330, 0x8009E530), (0x8009F628, 0x8009FA20))


NAME_TAB, NAME_N = 0x800AC1D4, 59


def name_table(nsz):
    """The SJIS name table the game builds from NSZ_B000 at boot: each
    length-prefixed record decoded and re-encoded as SJIS in a 32-byte
    entry. Matches a fresh boot's table byte for byte, the one quirk
    included: the game's conversion writes trail byte 0x7F where SJIS has
    0x80 (the font index reserves 0x80 the same way)."""
    import textcodec
    out, o = bytearray(), 0
    for _ in range(NAME_N):
        if o >= len(nsz):
            break
        n = nsz[o]
        rec = nsz[o + 1:o + 1 + n]
        o += 1 + n
        try:
            sj = bytearray(textcodec.decode_stream(rec).encode('cp932'))
        except (UnicodeEncodeError, ValueError):
            return None                      # unknown bytes: leave the state's own table
        for k in range(0, len(sj) - 1, 2):
            if sj[k] >= 0x81 and sj[k + 1] == 0x80:
                sj[k + 1] = 0x7F
        if len(sj) > 31:
            return None
        out += bytes(sj) + bytes(32 - len(sj))
    return bytes(out) if len(out) == 32 * NAME_N else None


def refresh(put, scene):
    """Apply the current build to a RAM image through put(addr, bytes)."""
    notes = []
    if scene:
        bank_path = os.path.join(PATCHED, f'ISZ_{scene}.BIN')
        if os.path.exists(bank_path):
            bank = open(bank_path, 'rb').read()
            put(BANK_RAM, bank)
            put(SCRATCH, b'\x00' * 0x100)
            notes.append(f'{scene} bank ({len(bank)}B) injected, scratch cleared')
        sys_path = os.path.join(PATCHED, f'ISZ_{SYS_BANK}.BIN')
        if scene != SYS_BANK and os.path.exists(sys_path):
            put(SYS_BANK_RAM, open(sys_path, 'rb').read())
            notes.append(f'{SYS_BANK} refreshed at {SYS_BANK_RAM:#x}')
        sub_path = os.path.join(PATCHED, f'SUBS_{scene}.BIN')
        if os.environ.get('NOSUBS'):
            # NOSUBS=1: the payload stays dead in the resumed state (magic
            # and scratch cleared, the exec hooks inert) - the game runs as
            # the pristine one does from here, for telling its own quirks
            # from ours (the garbage face on Randam's Kremlin lines, #4)
            put(HIRAM, bytes(4))
            put(SCRATCH, bytes(0x800))
            notes.append('NOSUBS: payload magic and scratch cleared')
        elif os.path.exists(sub_path):
            blob = bytearray(open(sub_path, 'rb').read())
            struct.pack_into('<I', blob, 0, MAGIC)
            put(HIRAM, bytes(blob))
            notes.append(f'payload ({len(blob)}B) at {HIRAM:#x}')
        else:
            put(HIRAM, b'\x00' * 4)
            notes.append('no payload for this scene: magic cleared')
        longs_path = os.path.join(PATCHED, f'LONGS_{scene}.BIN')
        if os.path.exists(longs_path):
            lb = open(longs_path, 'rb').read()
            put(LONGS, lb)
            notes.append(f'longs blob ({len(lb)}B) at {LONGS:#x}')
    exe = os.path.join(PATCHED, 'SLPS_001.54')
    if os.path.exists(exe):
        img = open(exe, 'rb').read()
        for lo, hi in CODE_RANGES:
            fo = lo - EXEC_RAM + EXEC_HDR
            put(lo, img[fo:fo + (hi - lo)])
        notes.append('exec code refreshed')
    # the speaker name table: the game converts NSZ_B000's records to SJIS
    # 32-byte entries at NAME_TAB once, at boot, so a bookmark carries its
    # build's pair codes and drew 'iotaomGeha' for 'Chief' after a pair
    # rebuild (B150_auto, 2026-11-06)
    nsz = os.path.join(PATCHED, 'NSZ_B000.BIN')
    if os.path.exists(nsz):
        tab = name_table(open(nsz, 'rb').read())
        if tab:
            put(NAME_TAB, tab)
            notes.append(f'name table ({len(tab) // 32} names) at {NAME_TAB:#x}')
    # the word-wrap stub the boot stub copies into high RAM: the hook in
    # render_text jumps there unconditionally (ps1/tools/wordwrap.py)
    import wordwrap
    put(wordwrap.RESIDENT, wordwrap.resident())
    notes.append(f'wordwrap resident at {wordwrap.RESIDENT:#x}')
    return '; '.join(notes)
