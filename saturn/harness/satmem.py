"""Saturn work RAM, read from the running Beetle Saturn core (or a state).

Beetle Saturn answers retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM = 2)
with one 2 MB block: WorkRAML (0x00200000..0x002FFFFF) then WorkRAMH
(0x06000000..0x060FFFFF). Mednafen keeps both as host-endian uint16, so on
x86 every halfword is byte-swapped against the SH-2's big-endian view -
`read` swaps it back and returns the bytes the CPU sees. The same two
arrays sit in a savestate under the MAIN section as `WorkRAML` and
`WorkRAMH` (`state_ram` finds them by name, no fixed offset).

Evidence (2026-09-12, work/saturn/probe_mem2.py): A.BIN's first 64 bytes,
halfword-swapped, at block offset 0x110000 = WorkRAMH + 0x10000 =
0x06010000 (frame 700); MAIN_L.BIN at 0x0B0000 = WorkRAML + 0xB0000 =
0x002B0000 (a pristine backup, 100% for the whole file) and at WorkRAMH +
0xB0000 = 0x060B0000 (99.8% at the title menu, frame 2600). During the
TrueMotion movies (Konami logo ~1500, the opening ~4000) the 0x060B0000
region is the FMV player's and matches MAIN_L only in its first 0x518
bytes - the master SH-2's PC then sits in A.BIN (0x060107A6, 0x0601AF88).

START (2026-09-12, work/saturn/probe_start.py): the core DOES map RetroPad
START (id 3) - the SMPC pad word in a state reads 0xFFCF idle, 0xFFC7 with
START held, 0xFFCB with A, 0xFFCD with C - but the game ignores it on the
title (the screen stays put, mean 105.5 as with no press; A and C open the
menu, 42.7), and a list menu takes only A/C (confirm) and B (cancel).

Loading: a scene bank (DATA.BIN entry 21 = B000 ... 59 = B260) is split on
load - bytecode (file offset 4 on) at low WRAM 0x002F8000, the string
region at 0x002E8000 (B010's 'JUNKER本部です' at 0x002E801E, the whole
region 0x2E8000..0x2EF81D = file 0x2A16..0xA233). `bank_in_ram` keys on it.

The addresses below are the engine's (MAIN_L.BIN at 0x060B0000); each
carries the probe that found it.
"""
import ctypes as C, os, struct
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")

LOW_BASE, HIGH_BASE, WRAM = 0x00200000, 0x06000000, 0x100000
RETRO_MEMORY_SYSTEM_RAM = 2

# ---- engine addresses (MAIN_L.BIN at 0x060B0000) ----------------------------
CTX = 0x060F24B0           # the game context the text layout writes through
TEXT_CELLS = CTX + 0x3FA   # 4 rows x 20 cells of {u16 sjis, u8 colour, pad}
TEXT_ROW = 80              # bytes per row
BLANK_CELL = 0x889E
# The list menu (verbs, Ask topics, Look targets). Found by diffing high WRAM
# across down/down/up/up presses on the reception's verb menu (frame 26628,
# work/saturn/probe_cursor*.py): the only byte going +1 +1 -1 -1 was
# 0x060F28A9, and the cell renderer 0x060B4970 reads it as a u16 at ctx+0x3F8
# to paint the highlight while byte ctx+0x3F7 is set. It reads 0 with a
# dialogue card up or after a confirm, 1 while the menu takes input; the
# index wraps at the count (3 on the first menu, 4 once 話す appeared, 6 on
# the Look submenu) and is REMEMBERED across a submenu (B on the Look list
# returned to the verb menu at index 1). The count is the byte at 0x060FD0C3:
# the only game-area byte reading 3 on the 3-item menu and 4 on the 4-item
# one, then 6 on the Look list; stale while no menu is live.
MENU_LIVE = CTX + 0x3F7
MENU_INDEX = CTX + 0x3F8   # u16
MENU_COUNT = 0x060FD0C3
# item i's label is the 10 cells from MENU_STARTS[i] (renderer table at
# 0x060B4950): items 0-3 fill the left column, 4-7 the right - the PS1's
# list-menu geometry
MENU_STARTS = [0, 20, 40, 60, 10, 30, 50, 70]
# The dialogue card, from snapshots over a card's life (menu -> confirm ->
# type-on -> waiting -> A -> menu; work/saturn/probe_box*.py): ctx+0xB74 is
# 0 while the text types on and 1 from ~10 frames after the last cell lands
# until the press that closes the card (26321-26502 on the first card,
# 26676 on the second); 0 with a menu live. No clean "card up" byte was
# found (ctx+0x11 / 0x060FD573 read 0 / 255 for the first card after the
# opening and 1 / 1 for the next) - a card is up when the cells hold text
# and no menu is live.
BOX_WAIT = CTX + 0xB74
BANK_CODE, BANK_STR = 0x002F8000, 0x002E8000   # the loaded bank's bytecode and string region (bank_in_ram)
# The scene: bank 21 (B000) runs the opening, bank 22 (B010) the reception;
# a loaded bank is split - bytecode (file offset 4 on) at low WRAM
# 0x002F8000, its string region at 0x002E8000 - so the bank in RAM is
# identified by comparing 0x002F8000 with work/saturn/data/NNN_Bxxx.bin[4:].
# The index variable: of the u16s reading 0 through the opening (states
# 8000-24000) and 1 at the reception (0x060EF73E, ctx+0x54A, ctx+0x5D8,
# 0x060FD856), ctx+0x54A is the one that flips 0 -> 1 at frame 25323,
# thirty frames BEFORE the bank in RAM turns from 21 to 22 (25353) and
# holds from then on (work/saturn/probe_scene.py): the scene number given
# to the loader, the PS1's ctx+0x1DB8. 0x060EF73E toggles 0/1 afterwards,
# 0x060FD856 follows the load at 25406, ctx+0x5D8 counts 0, 1, 2 inside
# the scene (a room/step counter). One transition seen so far.
SCENE_INDEX = CTX + 0x54A  # u16, 0 = opening (bank 21), 1 = B010 (bank 22)
SCENE_CANDIDATES = [0x060EF73E, CTX + 0x54A, CTX + 0x5D8, 0x060FD856]


class SatMem:
    """`read(addr, n)` over the live core's RAM pointer."""

    def __init__(self, core):
        core.retro_get_memory_data.restype = C.c_void_p
        core.retro_get_memory_size.restype = C.c_size_t
        self.core = core
        self.ptr = None

    def _base(self):
        if self.ptr is None:
            self.ptr = self.core.retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)
            if not self.ptr or self.core.retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM) != 2 * WRAM:
                raise RuntimeError("core exposes no 2 MB SYSTEM_RAM")
        return self.ptr

    def raw(self, off, n):
        """n bytes at block offset `off`, host order (halfwords swapped)."""
        return C.string_at(C.c_void_p(self._base() + off), n)

    def read(self, addr, n):
        off = block_offset(addr)
        a0, a1 = off & ~1, (off + n + 1) & ~1      # aligned span
        return unswap(self.raw(a0, a1 - a0))[off - a0:off - a0 + n]

    def write(self, addr, data):
        """Write CPU-order bytes into the core's RAM (halfword-swapped in the host
        buffer, so the odd edges are read-modify-written)."""
        off = block_offset(addr)
        n = len(data)
        a0, a1 = off & ~1, (off + n + 1) & ~1
        buf = bytearray(unswap(self.raw(a0, a1 - a0)))
        buf[off - a0:off - a0 + n] = data
        C.memmove(C.c_void_p(self._base() + a0), bytes(unswap(bytes(buf))), a1 - a0)

    def u8(self, addr):
        return self.read(addr, 1)[0]

    def u16(self, addr):
        return struct.unpack('>H', self.read(addr, 2))[0]

    def u32(self, addr):
        return struct.unpack('>I', self.read(addr, 4))[0]

    def low(self):
        """The whole low WRAM, CPU byte order."""
        return unswap(self.raw(0, WRAM))

    def high(self):
        return unswap(self.raw(WRAM, WRAM))

    def dump(self, path, which="high"):
        """Write a WRAM (CPU byte order) to a file; 'high', 'low' or 'both'."""
        with open(path, "wb") as fh:
            if which in ("low", "both"):
                fh.write(self.low())
            if which in ("high", "both"):
                fh.write(self.high())


CHUNK_TABLE = 0x060E62F4       # the exec's DATA.BIN chunk table, 639 x {u16 sector, u16 size/2}


def image_track1(cue):
    """The track-1 .bin beside `cue` (its first FILE line)."""
    for line in open(cue, encoding="utf-8", errors="replace"):
        if line.strip().upper().startswith("FILE"):
            return os.path.join(os.path.dirname(cue), line.split('"')[1])
    raise ValueError(f"no FILE line in {cue}")


def image_exec(cue, size=None):
    """MAIN_L.BIN as the track-1 image beside `cue` carries it (MODE1/2352,
    data at 16): found by its first 64 bytes, read sector by sector. The
    exec a run must match is the IMAGE's, not patched/saturn/MAIN_L.BIN -
    a build in progress leaves the two apart (2026-09-15: 4,068 bytes)."""
    track = None
    for line in open(cue, encoding="utf-8", errors="replace"):
        if line.strip().upper().startswith("FILE"):
            track = os.path.join(os.path.dirname(cue), line.split('"')[1]); break
    ref = os.path.join(ROOT, "discs", "extracted_saturn", "MAIN_L.BIN")
    if not os.path.exists(ref):
        ref = os.path.join(ROOT, "patched", "saturn", "MAIN_L.BIN")
    head = open(ref, "rb").read(64)
    size = size or os.path.getsize(ref)
    img = open(track, "rb").read()
    p = img.find(head)
    if p < 0 or p % 2352 != 16:
        raise ValueError(f"MAIN_L.BIN not found in {track}")
    sec = p // 2352
    out = b"".join(img[(sec + i) * 2352 + 16:(sec + i) * 2352 + 16 + 2048] for i in range((size + 2047) // 2048))
    return out[:size]


def refresh_chunk_table(mem, exe_path=None, image=None):
    """Write the current build's chunk table into RAM. A bookmark carries the
    table its build had, and satpack.py (the dense DATA.BIN re-layout) moves
    every chunk: a state restored on a re-laid image would read the wrong
    sectors for everything loaded after the restore. `image` (a cue) takes
    the exec out of the image being played (image_exec); else `exe_path`,
    default patched/saturn/MAIN_L.BIN. Returns True if it changed."""
    if image:
        exe = image_exec(image)
    else:
        exe_path = exe_path or os.path.join(ROOT, "patched", "saturn", "MAIN_L.BIN")
        exe = open(exe_path, "rb").read()
    tab = exe[CHUNK_TABLE - 0x060B0000:CHUNK_TABLE - 0x060B0000 + 4 * 639]
    changed = False
    if mem.read(CHUNK_TABLE, len(tab)) != tab:
        mem.write(CHUNK_TABLE, tab)
        changed = True
    if image:
        changed = refresh_gfs_dir(mem, image) or changed
        changed = refresh_exec_patches(mem, exe) or changed
    return changed


PRISTINE_EXEC = os.path.join(ROOT, "discs", "extracted_saturn", "MAIN_L.BIN")


def refresh_exec_patches(mem, exe):
    """Every byte the build changed in the exec, re-applied to the resumed RAM (the
    PS1's raminject): a bookmark's RAM carries the exec of ITS build - its renderer
    stub, pool words, hole stubs, SJIS table, names - so a payload change (or the
    blob's move to the region's end, 2026-09-16) never reached a resumed run. The
    build's patches are all static (code, the exec hole, tables): the runs of bytes
    where the image's MAIN_L.BIN differs from the pristine one, written back, the
    chunk table included. Runtime state lives in BSS and in data the tools never
    touch - except the keyboard's sprite list, which satkeys copies into the exec
    hole and the game writes while a keyboard is up (the count, the typed cells):
    `runtime_regions` keeps those bytes as the bookmark has them (2026-09-16: a
    refresh on the keys_search bookmark reset the count to the file's 4 and the
    typed name never showed). Returns True if anything was written."""
    if not os.path.exists(PRISTINE_EXEC):
        return False
    pristine = open(PRISTINE_EXEC, "rb").read()
    keep = runtime_regions(exe)
    n = min(len(pristine), len(exe))
    changed = False
    i = 0
    while i < n:
        if pristine[i] == exe[i]:
            i += 1
            continue
        j = i
        while j < n and (pristine[j] != exe[j] or (j + 4 < n and pristine[j:j + 4] != exe[j:j + 4])):
            j += 1
        seg = bytearray(exe[i:j])
        cur = mem.read(0x060B0000 + i, len(seg))
        for lo, hi in keep:                      # exec-file offsets
            a, b = max(lo, i), min(hi, j)
            if a < b:
                seg[a - i:b - i] = cur[a - i:b - i]
        if cur != seg:
            mem.write(0x060B0000 + i, bytes(seg))
            changed = True
        i = j
    if len(exe) > len(pristine):                     # a grown exec (none so far)
        tail = exe[len(pristine):]
        if mem.read(0x060B0000 + len(pristine), len(tail)) != tail:
            mem.write(0x060B0000 + len(pristine), tail)
            changed = True
    return changed


def runtime_regions(exe):
    """[(lo, hi)] exec-file offsets the game writes at runtime inside the build's
    patches: the keyboard sprite list satkeys.py moves into the exec hole (its
    pointer at LIST_PTR; the pristine list sits in the exec's own data, where the
    pristine bytes equal the built ones and no refresh touches them)."""
    import satkeys
    laddr = struct.unpack_from(">I", exe, satkeys.LIST_PTR - 0x060B0000)[0]
    if laddr == satkeys.LIST_ORIG:
        return []
    lo = laddr - 0x060B0000
    return [(lo, lo + 8 + 12 * (satkeys.NPIECES + satkeys.NCELLS))]


GFS_DIR = 0x060F5690            # GFS's directory cache: 24-byte entries {u32 FAD, u32 size, u32 attr, name[12]}
GFS_DIR_N = 227                 # the 226 files + the root, in directory order (A.BIN's FAD 176 first)


def refresh_gfs_dir(mem, image):
    """GFS's directory cache in RAM against the image's root directory. A grown
    DATA.BIN shifts every file after it (satdisc), and a bookmark made on the old
    image keeps the old FADs: the navigator reel loaded, waited for a stream two
    sectors off and the Ask list sat dead (2026-09-16, stall_asklist_showfunds).
    Entries are matched by name; every other RAM copy of a changed FAD (an open
    file's handle) is patched too. Returns True if anything changed."""
    import satdisc
    t1 = open(image_track1(image), "rb")
    recs = {r[2]: (r[3] + 150, r[4]) for r in satdisc.root_records(t1) if not r[5] & 2}
    t1.close()
    changed, moved = False, {}
    for i in range(GFS_DIR_N):
        e = GFS_DIR + 24 * i
        name = mem.read(e + 12, 12).split(b"\x00")[0].decode("ascii", "replace")
        if name not in recs:
            continue
        fad, size = recs[name]
        old_fad, old_size = mem.u32(e), mem.u32(e + 4)
        if (old_fad, old_size) != (fad, size):
            mem.write(e, struct.pack(">II", fad, size))
            moved[old_fad] = fad
            changed = True
    if moved:
        hi = mem.read(0x06000000, 0x100000)
        for off in range(0, len(hi) - 4, 4):
            v = struct.unpack_from(">I", hi, off)[0]
            if v in moved and not (GFS_DIR <= 0x06000000 + off < GFS_DIR + 24 * GFS_DIR_N):
                mem.write(0x06000000 + off, struct.pack(">I", moved[v]))
    return changed


def block_offset(addr):
    """Block offset of a Saturn address; both mirrors (0x002xxxxx / 0x06xxxxxx)."""
    a = addr & 0x0FFFFFFF
    if LOW_BASE <= a < LOW_BASE + WRAM:
        return a - LOW_BASE
    if HIGH_BASE <= a < HIGH_BASE + WRAM:
        return WRAM + a - HIGH_BASE
    raise ValueError(f"not work RAM: {addr:#x}")


def unswap(buf):
    """Halfword-swapped host bytes (even length) -> CPU byte order."""
    b = bytearray(buf)
    b[0::2], b[1::2] = buf[1::2], buf[0::2]
    return bytes(b)


def state_ram(blob, which="WorkRAMH", swap=True):
    """The named MAIN array out of a Mednafen savestate, CPU byte order.

    MDFNSVST: a 32-byte header, then sections of {32-byte name, u32 LE size,
    body}; a body is a list of {u8 namelen, name, u32 LE size, data}.
    WorkRAML/WorkRAMH are halfword-swapped (swap=True unswaps them);
    `BackupRAM` (32,768 B, the internal backup RAM, one byte per byte -
    'BackUpRam Format' reads straight) is stored as the bytes are: pass
    swap=False for it (saturn/harness/satsave.py)."""
    off = 32
    while off + 36 <= len(blob):
        name = blob[off:off + 32].split(b"\0")[0]
        size = struct.unpack_from("<I", blob, off + 32)[0]
        if name == b"MAIN":
            p, end = off + 36, off + 36 + size
            while p < end:
                nl = blob[p]; nm = blob[p + 1:p + 1 + nl]
                vs = struct.unpack_from("<I", blob, p + 1 + nl)[0]
                p += 1 + nl + 4
                if nm == which.encode():
                    return unswap(blob[p:p + vs]) if swap else blob[p:p + vs]
                p += vs
        off += 36 + size
    raise ValueError(f"{which} not in state")


def cells(mem, rows=4, cols=20, strip=True):
    """The text cell array as rows of SJIS-decoded strings (blank = space)."""
    out = []
    for r in range(rows):
        row = mem.read(TEXT_CELLS + r * TEXT_ROW, cols * 4)
        s = ""
        for c in range(cols):
            code = struct.unpack_from(">H", row, c * 4)[0]
            if code in (0, BLANK_CELL):
                s += " "
            else:
                try:
                    s += code.to_bytes(2, "big").decode("cp932")
                except UnicodeDecodeError:
                    s += "?"
        out.append(s.rstrip() if strip else s)
    return out


def menu_labels(mem):
    """The eight possible list-menu labels out of the cell array (items
    0-3 left column, 4-7 right); trailing blanks stripped, '' when empty."""
    rows = cells(mem, 4, 20, strip=False)
    return [rows[s // 20][s % 20:s % 20 + 10].strip() for s in MENU_STARTS]


_BANKS = {}


def bank_in_ram(mem):
    """Which DATA.BIN entry (21 = B000 ... 59 = B260) is loaded, by its
    bytecode at BANK_CODE, or None."""
    import glob
    if not _BANKS:
        for p in glob.glob(os.path.join(WORK, "saturn", "data", "0*_B*.bin")):
            _BANKS[int(os.path.basename(p)[:3])] = open(p, "rb").read()[4:68]
    head = mem.read(BANK_CODE, 64)
    return next((n for n, h in _BANKS.items() if h == head), None)
