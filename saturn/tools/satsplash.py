"""The two boot screens of the English build, drawn before Konami's logo.

The PS1 build shows them from its exec's entry point (ps1/tools/bootcard.py:
the PEPA SOFT HOUSE card, 3 s; ps1/tools/bootsplash.py: a Snatcher walks in
and the disclaimer comes in over it, ~10.7 s). This is the Saturn port of both.

**Where it runs.** The BIOS loads the IP (track 1 sectors 0-15) at
0x06002000 and the first root file, A.BIN, at 0x06010000; the IP's own
start-up code (Sega's SYS_INIT, after the security code and the area block)
ends with `mov.l @(0x06002FD4), r1; jsr @r1` - the one word that hands the
machine to A.BIN (`0x06002F7A`). That literal now points at our player, which
lives in the IP itself: the header's IP size (0xE0) goes from 0x1800 to
0x8000, so the BIOS loads all sixteen system sectors, and the player + its
data sit at BLOCK = 0x06003400 (the IP's own variables end at 0x06003318)
up to 0x0600A000 (27,648 bytes). No file moves, A.BIN and MAIN_L.BIN are
untouched, and no bookmark carries anything of it (satmem's refreshes never
see it). The Sega license screen is the BIOS's and stays; ours come after it.

**What it does** (measured at the jsr on Beetle Saturn + sega_101.bin,
work/saturn/splash/probe_hook.py: the license screen still up, SR = 1,
display on, NBG0 cells; high WRAM 0x06003800..0x06100000 all zero):

  1. saves r8-r14/pr/SR, masks interrupts (the BIOS's handlers stay out),
     turns the display off at a vblank;
  2. copies VDP2 VRAM 0x00000-0x1FFFF and 0x40000-0x5FFFF and the 4 KB of
     CRAM to WRAM 0x06040000.. (BACKUP), then clears both VRAM banks;
  3. unpacks the images (PackBits-style RLE, `rle()`) into WRAM SCRATCH,
     loads the palettes into CRAM, copies the card into NBG0 and writes the
     whole VDP2 register file from REGS_ON (NBG0 = 512x256 8-bpp bitmap at
     VRAM 0, opaque, CRAM 0-255; NBG1 = the same at 0x40000, index 0
     transparent, CRAM 256-511 via CRAOFA; sprites off; colour offset A on
     both layers), display on;
  4. holds the card CARD_FRAMES vblanks, wipes it, then plays the timeline:
     the robot is composed in WRAM from its parts (only when the pose
     changes) and copied into NBG1; it walks by NBG1's scroll registers
     (x, and the one-pixel bob in y); the eyes flicker by rewriting the head's
     own eye colours in CRAM; each text line is copied into NBG0 when it
     appears; the fade is colour offset A going to -255;
  5. display off, VRAM/CRAM put back from BACKUP, the register file put back
     as the jsr left it (REGS_OFF, measured; TVMD with the display bit
     cleared, so A.BIN turns it on when its logo is ready instead of the
     license screen flashing back), BACKUP and SCRATCH zeroed (they were
     zero), SR/regs/pr restored, `jmp 0x06010000` - A.BIN sees what it saw.

Pacing is TVSTAT's VBLANK bit (0x25F80004 bit 3), polled on both edges - only
while the display is on: with TVMD's DISP bit clear the bit reads 1 throughout
(the first build hung in `vwait` right after turning the display off).

The art: the Saturn's Chin scene draws the bodyguards as 120x128 close-up
busts cut in 40x32 tiles (chunk 411), with no separate torso, arms or heads
and no hip plate, so the PS1's figure (CXE_B0D0 parts, as bootsplash.py cuts
them) is used: WORK/saturn/splash/parts/ (a cached copy), else
SATSPLASH_PARTS, else ROOT/work/gfx/all/CXE_B0D0_items/ (rendered from the
PS1 disc by build.py prep ps1). Extracted art is never committed.

    python saturn/tools/satsplash.py preview   # work/saturn/splash/preview.gif + card/snarl/text PNGs
    python saturn/tools/satsplash.py apply     # patched/saturn/IP.BIN (satdisc writes it into sectors 0-15)
    python saturn/tools/satsplash.py off       # removes patched/saturn/IP.BIN (the pristine IP ships)
"""
import os, shutil, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/subs')]
import sysfont

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(WORK, "saturn", "splash")
IP_OUT = os.path.join(ROOT, "patched", "saturn", "IP.BIN")
SRC_T1 = os.path.join(ROOT, "discs", "iso_saturn_jp", "Snatcher (Japan) (Track 1).bin")
PARTS_CACHE = os.path.join(OUT_DIR, "parts")
PARTS_PS1 = os.path.join(ROOT, "work", "gfx", "all", "CXE_B0D0_items")
PART_NAME = "CXE_B0D0_{}_8bpp.png"

W, H = 320, 224                          # NTSC 320x224, TVMD 0x8000
IP_BASE, IP_MAX = 0x06002000, 0x8000
IP_SIZE_OLD = 0x1800
JSR_LITERAL = 0x06002FD4                 # SYS_INIT's `jsr @r1` target (at 0x06002F7A)
A_ENTRY = 0x06010000
BLOCK = 0x06003400                       # above SYS_INIT's variables (0x060032A0..0x06003318)
BLOCK_END = IP_BASE + IP_MAX
BACKUP = 0x06040000                      # 2 x 128 KB VRAM + 4 KB CRAM
SCRATCH = BACKUP + 0x40000 + 0x1000
SCRATCH_END = 0x060B0000                 # MAIN_L.BIN's load address (not loaded yet)
VDP2 = 0x25F80000
VRAM = 0x25E00000
CRAM = 0x25F00000
NBG0_VRAM, NBG1_VRAM = VRAM, VRAM + 0x40000
STRIDE = 512                             # bitmap 512x256, 8 bpp

# --- the look (PS1 bootcard/bootsplash, fitted to 224 lines) ---------------------
TEXT = [                                 # (font, size, ink, text); fixed, humanizer-checked on the PS1 (bootsplash.py)
    ("impact.ttf", 22, (176, 16, 16), "DISCLAIMER"),
    ("arial.ttf", 12, (0, 0, 0), "This translation was made with the help of AI and"),
    ("arial.ttf", 12, (0, 0, 0), "reviewed by a fan, not a professional translator."),
    ("arial.ttf", 12, (0, 0, 0), "If you'd rather not play an AI-assisted translation,"),
    ("arial.ttf", 12, (0, 0, 0), "stop here. Otherwise, enjoy the game."),
    ("arial.ttf", 12, (0, 0, 0), "Found a problem? Report it at:"),
    ("arialbd.ttf", 11, (16, 64, 160), "github.com/pepasjc/snatcher-translated"),
]
TEXT_POS = [(16, 8), (16, 38), (16, 52), (16, 66), (16, 80), (16, 102), (16, 118)]   # the PS1's (16, 16/46/60/74/88/110/126) 8 lines up
INK_LEVELS = 5
CARD_GREYS = 15                          # card indices 1..15, 0 = white
TEXT_BASE = 16                           # text indices 16..30 in NBG0's palette

HEAD_AT = (17, -30)                      # figure geometry relative to the torso's top-left (bootsplash.py)
L_SHOULDER, R_SHOULDER, SHOULDER_Y = 8, 50, 6
STOP_X, FLOOR_Y = 238, H - 92            # the hip plate ends on the bottom line
START_X = W + 24

# timeline, in frames (59.94 Hz) - the PS1's
CARD_FRAMES = 180                        # bootcard.py HOLD_S 3.0
WALK, SETTLE, EYES_AT, JAW_AT, SNARL, TEXT_GAP, HOLD, FADE = 200, 30, 0, 36, 50, 8, 260, 32
TEXT_AT = 60                             # the lines start coming in 1 s into the walk (bootsplash.py)
EYE_DARK = (48, 40, 40)

COMPS = [(0, 0), (0, 1), (1, 2), (1, 1)]  # (arm pose, head) per composite id

# What the two screens add to the power-on timeline (Konami's logo and the title come
# this many frames later than on the pristine disc): the card + the timeline + the
# set-up and hand-back, measured on Beetle Saturn (work/saturn/splash/probe_align.py:
# 1,214 frames of the logo and the title hash-identical to pristine at offsets 833-840,
# the title's first frame 2122 -> 2955; 953-960 / 955 with the first, 760-frame timeline).
# The harness adds it through satrun.boot_screens.
BOOT_DELAY = 835

# VDP2 register file at the IP's jsr into A.BIN (Beetle Saturn 0.9.45.1 + sega_101.bin,
# RawRegs of a state parked on a `bra .` at the hook - probe_hook.py). Registers not listed
# were 0. Written back at the end with TVMD's display bit cleared.
PRISTINE_VDP2 = {0x000: 0x8000, 0x010: 0x0F44, 0x012: 0xFFFF, 0x014: 0xFFFF, 0x016: 0xFFFF,
                 0x018: 0xFFFF, 0x01A: 0xFFFF, 0x01C: 0xFFFF, 0x01E: 0xFFFF, 0x020: 0x0001,
                 0x030: 0x8000, 0x040: 0x0303, 0x042: 0x0303, 0x078: 0x0001, 0x07C: 0x0001,
                 0x088: 0x0001, 0x08C: 0x0001, 0x0AE: 0x4000, 0x0E0: 0x0020, 0x0F8: 0x0007,
                 0x110: 0x0001, 0x114: 0x0200, 0x116: 0x0200, 0x118: 0x0200}
READ_ONLY = {0x004, 0x006, 0x008, 0x00A, 0x00C}     # TVSTAT, VRSIZE, HCNT, VCNT, reserved

OURS_VDP2 = {
    0x010: 0x44EE, 0x012: 0xEEEE, 0x014: 0x44EE, 0x016: 0xEEEE,   # bank A: NBG0 bitmap reads (256 colours = 2 slots)
    0x018: 0x55EE, 0x01A: 0xEEEE, 0x01C: 0x55EE, 0x01E: 0xEEEE,   # bank B: NBG1
    0x020: 0x0103,                       # BGON: NBG0 + NBG1, NBG0 opaque (index 0 = white)
    0x028: 0x1212,                       # CHCTLA: both bitmaps, 512x256, 256 colours
    0x03C: 0x0020,                       # MPOFN: NBG0 at 0, NBG1 at 0x40000
    0x078: 1, 0x07C: 1, 0x088: 1, 0x08C: 1,                       # zoom 1.0
    0x0E4: 0x0010,                       # CRAOFA: NBG1 colours from 256
    0x0F8: 0x0201,                       # PRINA: NBG0 1, NBG1 2 (sprites/others 0 = hidden)
    0x110: 0x0003,                       # CLOFEN: colour offset on NBG0/NBG1 (offset A, 0 until the fade)
}


def hooked(track1):
    """True if a track-1 image's IP hands A.BIN's jsr to the player."""
    with open(track1, "rb") as f:
        f.seek(2352 * ((JSR_LITERAL - IP_BASE) // 2048) + 16 + (JSR_LITERAL - IP_BASE) % 2048)
        return struct.unpack(">I", f.read(4))[0] == BLOCK


def version():
    """The Saturn patch's version: saturn/VERSION (ps1/VERSION is the PS1 patch's)."""
    return open(os.path.join(ROOT, "saturn", "VERSION")).read().strip()


# --- assets ---------------------------------------------------------------------------

def parts_dir():
    for d in (PARTS_CACHE, os.environ.get("SATSPLASH_PARTS"), PARTS_PS1):
        if d and all(os.path.exists(os.path.join(d, PART_NAME.format(g))) for g in ("g1_00", "g1_01")):
            if d != PARTS_CACHE:
                os.makedirs(PARTS_CACHE, exist_ok=True)
                for g in ("g1_00", "g1_01"):
                    shutil.copyfile(os.path.join(d, PART_NAME.format(g)), os.path.join(PARTS_CACHE, PART_NAME.format(g)))
            return PARTS_CACHE
    sys.exit("satsplash: the Snatcher parts (CXE_B0D0_g1_00/01_8bpp.png) not found - set SATSPLASH_PARTS "
             f"or put them in {PARTS_CACHE}")


def _rgba(im, box):
    x, y, w, h = box
    a = np.asarray(im.crop((x, y, x + w, y + h)).convert("RGB"))
    alpha = np.where(a.sum(2) > 0, 255, 0).astype(np.uint8)
    return np.dstack([a, alpha])


def _trim(a, dx, dy):
    ys, xs = np.nonzero(a[..., 3])
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return a[y0:y1, x0:x1], dx + x0, dy + y0


def _split_arms(a):
    top = [np.argmax(a[:, c, 3] > 0) if a[:, c, 3].any() else 1 << 30 for c in range(a.shape[1])]
    ax = int(np.argmin(top))
    return a[:, :ax], a[:, ax:]


def parts():
    """name -> (rgba, dx, dy) relative to the torso's top-left: bootsplash.parts()'s cut."""
    d = parts_dir()
    g0 = Image.open(os.path.join(d, PART_NAME.format("g1_00")))
    g1 = Image.open(os.path.join(d, PART_NAME.format("g1_01")))
    out = {"torso": _trim(_rgba(g0, (0, 4, 58, 92)), 0, 0)}
    for pose, (im, box) in enumerate(((g0, (57, 3, 63, 82)), (g1, (2, 5, 61, 51)))):
        left, right = _split_arms(_rgba(im, box))
        out[f"armL{pose}"] = _trim(left, L_SHOULDER - left.shape[1], SHOULDER_Y)
        out[f"armR{pose}"] = _trim(right, R_SHOULDER, SHOULDER_Y)
    for i in range(3):
        out[f"head{i}"] = _trim(_rgba(g1, (24 * i, 56, 24, 46)), *HEAD_AT)
    return out


def _is_eye(c):
    r, g, b = c
    return r > 120 and r > g + 60 and r > b + 60


def _q15(c):
    return tuple((v >> 3) << 3 for v in c)


def _rgb555(c):
    r, g, b = (v >> 3 for v in c)
    return r | g << 5 | b << 10


def card_image():
    """splash.card() (the PS1's PEPA SOFT HOUSE card, 320x240) cut to 224 lines,
    as indices: 0 white, 1..15 darker greys."""
    import splash
    im = splash.card().convert("L").crop((0, 8, W, 8 + H))
    a = np.asarray(im).astype(np.float32)
    return np.clip(np.rint((255 - a) / 255 * CARD_GREYS), 0, CARD_GREYS).astype(np.uint8)


def card_palette():
    return [(255, 255, 255)] + [(round(255 - 255 * k / CARD_GREYS),) * 3 for k in range(1, CARD_GREYS + 1)]


def text_inks():
    inks = []
    for t in TEXT:
        if t[2] not in inks:
            inks.append(t[2])
    assert INK_LEVELS * len(inks) <= 15
    return inks


def text_palette():
    """NBG0 colours TEXT_BASE.. : per ink INK_LEVELS anti-alias steps against white."""
    return [tuple(int(round(255 + (c - 255) * (k + 1) / INK_LEVELS)) for c in ink)
            for ink in text_inks() for k in range(INK_LEVELS)]


def text_lines():
    """[index array] per line: 0 = white, TEXT_BASE.. the ink's steps (bootsplash.text_lines)."""
    inks = text_inks()
    out = []
    for font, size, ink, s in TEXT:
        f = sysfont.truetype(font, size)
        bb = f.getbbox(s)
        im = Image.new("L", (bb[2] - bb[0] + 2, bb[3] - bb[1] + 2), 0)
        ImageDraw.Draw(im).text((1 - bb[0], 1 - bb[1]), s, font=f, fill=255)
        a = np.asarray(im).astype(np.float32) / 255
        q = np.clip(np.rint(a * INK_LEVELS), 0, INK_LEVELS).astype(np.uint8)
        base = TEXT_BASE + INK_LEVELS * inks.index(ink)
        out.append(np.where(q > 0, q - 1 + base, 0).astype(np.uint8))
    return out


def _even(a):
    """Pad an index array's width to even (word copies into VRAM)."""
    if a.shape[1] % 2:
        a = np.pad(a, ((0, 0), (0, 1)))
    return a


def rle(data):
    """PackBits-style: c < 128 -> c+1 literal bytes; c >= 128 -> the next byte (c - 126) times."""
    data = bytes(data)
    out, i, n = bytearray(), 0, len(data)
    lit = bytearray()

    def flush():
        while lit:
            k = min(128, len(lit))
            out.append(k - 1)
            out.extend(lit[:k])
            del lit[:k]
    while i < n:
        j = i
        while j < n and data[j] == data[i] and j - i < 129:
            j += 1
        if j - i >= 3:
            flush()
            out.append(j - i + 126)
            out.append(data[i])
            i = j
        else:
            lit.extend(data[i:j])
            i = j
    flush()
    return bytes(out)


def nibbles(a, base):
    """Index array -> two pixels per byte, high nibble first: v - base, 0 kept (all < 16)."""
    v = np.where(a > 0, a.astype(int) - base, 0).ravel()
    assert v.size % 2 == 0 and v.max() < 16 and (v[a.ravel() > 0] > 0).all()
    return (v[0::2] << 4 | v[1::2]).astype(np.uint8).tobytes()


def unnibble(b, base):
    """The player's `expand`: each nibble v -> v + base, 0 -> 0."""
    out = bytearray()
    for x in b:
        for v in (x >> 4, x & 15):
            out.append(v + base if v else 0)
    return bytes(out)


def unrle(src, n):
    out, i = bytearray(), 0
    while len(out) < n:
        c = src[i]; i += 1
        if c < 128:
            out += src[i:i + c + 1]; i += c + 1
        else:
            out += bytes([src[i]]) * (c - 126); i += 1
    assert len(out) == n
    return bytes(out)


class Assets:
    def __init__(self):
        P = parts()
        # robot palette: index 0 transparent; the heads' eye colours get their own
        # indices so the flicker dims the eyes and nothing else
        colours, eyes = [], []
        for n, (a, _, _) in P.items():
            for c in map(tuple, a[a[..., 3] > 0][:, :3]):
                c = _q15(c)
                key = ("eye", c) if n.startswith("head") and _is_eye(c) else ("col", c)
                if key[0] == "eye":
                    if key not in eyes:
                        eyes.append(key)
                elif key not in colours:
                    colours.append(key)
        keys = colours + eyes
        assert len(keys) <= 255, len(keys)
        self.robot_index = {k: i + 1 for i, k in enumerate(keys)}
        self.robot_pal = [(0, 0, 0)] + [k[1] for k in keys]
        self.eye_idx = [self.robot_index[k] for k in eyes]
        self.parts = {}                 # name -> (index array, dx, dy)
        for n, (a, dx, dy) in P.items():
            idx = np.zeros(a.shape[:2], np.uint8)
            m = a[..., 3] > 0
            for yy, xx in zip(*np.nonzero(m)):
                c = _q15(tuple(a[yy, xx, :3]))
                key = ("eye", c) if n.startswith("head") and _is_eye(c) else ("col", c)
                idx[yy, xx] = self.robot_index[key]
            self.parts[n] = (idx, dx, dy)
        # the composite box: the union of every pose's parts
        boxes = [(dx, dy, dx + a.shape[1], dy + a.shape[0]) for a, dx, dy in self.parts.values()]
        self.ox, self.oy = min(b[0] for b in boxes), min(b[1] for b in boxes)
        self.cw = max(b[2] for b in boxes) - self.ox
        self.cw += self.cw & 1
        self.ch = max(b[3] for b in boxes) - self.oy
        self.card = card_image()
        self.texts = [_even(t) for t in text_lines()]

    def comp_parts(self, cid):
        pose, head = COMPS[cid]
        return [f"armL{pose}", f"armR{pose}", "torso", f"head{head}"]

    def composite(self, cid):
        out = np.zeros((self.ch, self.cw), np.uint8)
        for n in self.comp_parts(cid):
            a, dx, dy = self.parts[n]
            x, y = dx - self.ox, dy - self.oy
            reg = out[y:y + a.shape[0], x:x + a.shape[1]]
            reg[a > 0] = a[a > 0]
        return out

    def card_rect(self):
        ys, xs = np.nonzero(self.card)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min() & ~1, xs.max() + 1
        x1 += (x1 - x0) & 1
        return x0, y0, self.card[y0:y1, x0:x1]


# --- the timeline -----------------------------------------------------------------------

def _ease_out(t):
    return 1 - (1 - t) ** 3


def timeline():
    """[(comp, eyes_lit, x, y, texts, fade)] per frame after the card; x, y = the
    torso's top-left on screen (bootsplash.timeline, same frame counts): the robot's
    sequence, with the text lines coming in over it from TEXT_AT, one every TEXT_GAP."""
    robot = []
    for f in range(WALK):
        x = round(START_X + (STOP_X - START_X) * _ease_out(f / (WALK - 1)))
        step = (f // 12) % 2 if f < WALK - 24 else 0
        robot.append((0, 0, x, FLOOR_Y + step))
    still = lambda comp=0, eyes=1: (comp, eyes, STOP_X, FLOOR_Y)
    robot += [still(eyes=0)] * SETTLE
    for lit in (1, 0, 0, 1, 1, 0, 1):
        robot += [still(eyes=lit)] * 3
    robot += [still()] * (JAW_AT - 21)
    robot += [still(1)] * 4
    robot += [still(2)] * SNARL
    robot += [still(3)] * 4
    robot += [still()] * (20 + HOLD)
    shown = lambda f: sum(1 for i in range(len(TEXT)) if f >= TEXT_AT + i * TEXT_GAP)
    fr = [r + (shown(f), 0) for f, r in enumerate(robot)]
    for f in range(1, FADE + 1):
        fr.append(still() + (len(TEXT), min(255, round(255 * f / FADE))))
    fr += [still() + (len(TEXT), 255)] * 4
    return fr


def segments(A, frames):
    """Run-length the frames: [(rep, comp, eyes, sx, sy, texts, fade)] with sx, sy =
    the composite's top-left on screen."""
    out = []
    for comp, eyes, x, y, texts, fade in frames:
        rec = (comp, eyes, x + A.ox, y + A.oy, texts, fade)
        if out and out[-1][1:] == rec and out[-1][0] < 0xFFFF:
            out[-1] = (out[-1][0] + 1,) + rec
        else:
            out.append((1,) + rec)
    return out


# --- the Python model (what the player draws) ---------------------------------------------

def render(A, comp, eyes, sx, sy, texts, fade, card=False):
    pal0 = card_palette() + text_palette()
    pal0 = [_q15(c) for c in pal0]
    nbg0 = np.zeros((H, W), np.uint8)
    if card:
        x0, y0, img = A.card_rect()
        nbg0[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    for i in range(texts):
        (x, y), t = TEXT_POS[i], A.texts[i]
        nbg0[y:y + t.shape[0], x:x + t.shape[1]] = t
    lut0 = np.array(pal0 + [(0, 0, 0)] * (256 - len(pal0)), np.int32)
    im = lut0[nbg0]
    if not card:
        pal1 = [_q15(c) for c in A.robot_pal]
        if not eyes:
            for i in A.eye_idx:
                pal1[i] = _q15(EYE_DARK)
        lut1 = np.array(pal1 + [(0, 0, 0)] * (256 - len(pal1)), np.int32)
        c = A.composite(comp)
        for yy in range(A.ch):
            y = sy + yy
            if not 0 <= y < H:
                continue
            row = c[yy]
            for xx in np.nonzero(row)[0]:
                x = sx + xx
                if 0 <= x < W:
                    im[y, x] = lut1[row[xx]]
    if fade:
        im = np.maximum(im - (fade >> 3 << 3), 0)
    return Image.fromarray(im.astype(np.uint8))


def check_layout(A):
    """The URL (and every text line) clear of the robot at its stop, every pose."""
    for cid in range(len(COMPS)):
        c = A.composite(cid)
        sx, sy = STOP_X + A.ox, FLOOR_Y + A.oy
        for i, ((x, y), t) in enumerate(zip(TEXT_POS, A.texts)):
            ys, xs = np.nonzero(c)
            hit = ((xs + sx >= x - 4) & (xs + sx < x + t.shape[1] + 4) &
                   (ys + sy >= y - 4) & (ys + sy < y + t.shape[0] + 4))
            assert not hit.any(), f"text line {i} touches the robot (pose {cid})"
    assert FLOOR_Y + A.parts["torso"][2] + A.parts["torso"][0].shape[0] == H     # the hip plate on the bottom line


# --- the player (SH-2) ------------------------------------------------------------------

PLAYER = r"""
entry:
    mov.l   r8, @-r15
    mov.l   r9, @-r15
    mov.l   r10, @-r15
    mov.l   r11, @-r15
    mov.l   r12, @-r15
    mov.l   r13, @-r15
    mov.l   r14, @-r15
    sts.l   pr, @-r15
    .word   0x0002              ; stc sr, r0
    mov.l   r0, @-r15
    or      #0xF0, r0
    .word   0x400E              ; ldc r0, sr: interrupts masked
    mov.l   =0x25F80000, r12
    bsr     vwait
    nop
    mov     #0, r0
    mov.w   r0, @r12            ; TVMD: display off
; the VDP2 memory we use, saved
    mov.l   =0x25E00000, r4
    mov.l   =BACKUP, r5
    mov.l   =0x20000, r6
    bsr     copy
    nop
    mov.l   =0x25E40000, r4
    mov.l   =BACKUP + 0x20000, r5
    mov.l   =0x20000, r6
    bsr     copy
    nop
    mov.l   =0x25F00000, r4
    mov.l   =BACKUP + 0x40000, r5
    mov.l   =0x1000, r6
    bsr     copy
    nop
    mov.l   =0x25E00000, r4
    mov.l   =0x20000, r6
    bsr     zero
    nop
    mov.l   =0x25E40000, r4
    mov.l   =0x20000, r6
    bsr     zero
    nop
; the images into SCRATCH
    mov.l   =UNPACK, r8
unp:                            ; {src, dst, pixels, mode}: mode 0 = bytes, 0x100|base = nibbles
    mov.l   @r8+, r4
    tst     r4, r4
    bt      unp_done
    mov.l   @r8+, r5
    mov.l   @r8+, r6
    mov.l   @r8+, r7
    tst     r7, r7
    bt      unp_bytes
    mov.l   r5, @-r15
    mov.l   r6, @-r15
    mov.l   r7, @-r15
    mov.l   =NIBTMP, r5
    bsr     unrle
    shlr    r6
    mov.l   @r15+, r7
    mov.l   @r15+, r6
    mov.l   @r15+, r5
    mov.l   =NIBTMP, r4
    bsr     expand
    extu.b  r7, r7
    bra     unp
    nop
unp_bytes:
    bsr     unrle
    nop
    bra     unp
    nop
unp_done:
    mov.l   =CRAM_TAB, r4
    bsr     cramload
    nop
    mov.l   =EYES_DARK, r4
    bsr     cramload
    nop
    mov.l   =CARD_RECT, r4
    mov.l   =0x25E00000, r5
    bsr     rcopy
    nop
    mov.l   =REGS_ON, r4            ; no vwait: with the display off TVSTAT's VBLANK reads 1 throughout
    bsr     regs
    nop
; the card
    mov.l   =CARD_FRAMES, r13
card:
    bsr     vwait
    nop
    dt      r13
    bf      card
    mov.l   =CARD_WIPE, r4
    mov.l   =0x25E00000, r5
    bsr     rcopy
    nop
; the timeline
    mov.l   =TIMELINE, r8
    mov     #-1, r9             ; composite in NBG1
    mov     #0, r10             ; eyes lit? (dark loaded)
    mov     #0, r11             ; text lines shown
tl:
    mov.w   @r8, r0
    extu.w  r0, r13
    tst     r13, r13
    bt      tl_end
    mov.b   @(6, r8), r0
    extu.b  r0, r0
    cmp/eq  r9, r0
    bt      tl_same
    mov     r0, r9
    bsr     compose
    nop
    mov     #1, r14
    bra     tl_wait
    nop
tl_same:
    mov     #0, r14
tl_wait:
    bsr     vwait
    nop
    mov.w   @(2, r8), r0        ; composite x on screen -> SCXIN1 = -x
    neg     r0, r0
    mov.l   =0x1FF, r1
    and     r1, r0
    mov.l   =0x25F80080, r1
    mov.w   r0, @r1
    mov.w   @(4, r8), r0        ; y -> SCYIN1 = -y
    neg     r0, r0
    and     #0xFF, r0
    mov.l   =0x25F80084, r1
    mov.w   r0, @r1
    mov.w   @(10, r8), r0       ; fade -> COAR/G/B = -fade
    neg     r0, r0
    mov.l   =0x1FF, r1
    and     r1, r0
    mov.l   =0x25F80114, r1
    mov.w   r0, @r1
    mov.w   r0, @(2, r1)
    mov.w   r0, @(4, r1)
    mov.b   @(7, r8), r0        ; eyes
    extu.b  r0, r0
    cmp/eq  r10, r0
    bt      tl_text
    mov     r0, r10
    mov.l   =EYES_DARK, r4
    tst     r0, r0
    bt      tl_eyes
    mov.l   =EYES_LIT, r4
tl_eyes:
    bsr     cramload
    nop
tl_text:
    mov.b   @(8, r8), r0
    extu.b  r0, r0
    cmp/hs  r0, r11
    bt      tl_comp
    mov     r11, r4             ; TEXT_RECTS + 12 * r11
    shll2   r4
    mov     r4, r1
    shll    r4
    add     r1, r4
    mov.l   =TEXT_RECTS, r1
    add     r1, r4
    mov.l   =0x25E00000, r5
    bsr     rcopy
    nop
    add     #1, r11
    bra     tl_text
    nop
tl_comp:
    tst     r14, r14
    bt      tl_rep
    mov.l   =COMP_RECT, r4
    mov.l   =0x25E40000, r5
    bsr     rcopy
    nop
tl_rep:
    dt      r13
    bt      tl_next
    bsr     vwait
    nop
    bra     tl_rep
    nop
tl_next:
    add     #12, r8
    bra     tl
    nop
tl_end:
; hand the machine back as the jsr left it
    bsr     vwait
    nop
    mov     #0, r0
    mov.w   r0, @r12            ; display off
    mov.l   =BACKUP, r4
    mov.l   =0x25E00000, r5
    mov.l   =0x20000, r6
    bsr     copy
    nop
    mov.l   =BACKUP + 0x20000, r4
    mov.l   =0x25E40000, r5
    mov.l   =0x20000, r6
    bsr     copy
    nop
    mov.l   =BACKUP + 0x40000, r4
    mov.l   =0x25F00000, r5
    mov.l   =0x1000, r6
    bsr     copy
    nop
    mov.l   =REGS_OFF, r4
    bsr     regs
    nop
    mov.l   =BACKUP, r4
    mov.l   =SCRATCH_END - BACKUP, r6
    bsr     zero
    nop
    mov.l   @r15+, r0
    .word   0x400E              ; ldc r0, sr
    lds.l   @r15+, pr
    mov.l   @r15+, r14
    mov.l   @r15+, r13
    mov.l   @r15+, r12
    mov.l   @r15+, r11
    mov.l   @r15+, r10
    mov.l   @r15+, r9
    mov.l   =A_ENTRY, r1
    jmp     @r1
    mov.l   @r15+, r8
.pool

; --- leaf routines (r0-r7) ---
vwait:                          ; to the start of the next vertical blank
    mov.l   =0x25F80004, r1
vw1:
    mov.w   @r1, r0
    tst     #8, r0
    bf      vw1
vw2:
    mov.w   @r1, r0
    tst     #8, r0
    bt      vw2
    rts
    nop

copy:                           ; r4 src, r5 dst, r6 bytes (longs)
    mov.l   @r4+, r0
    mov.l   r0, @r5
    add     #4, r5
    add     #-4, r6
    cmp/pl  r6
    bt      copy
    rts
    nop

zero:                           ; r4 dst, r6 bytes (longs)
    mov     #0, r0
zero1:
    mov.l   r0, @r4
    add     #4, r4
    add     #-4, r6
    cmp/pl  r6
    bt      zero1
    rts
    nop

regs:                           ; r4 -> {u16 offset, u16 value}*, 0xFFFF ends
    mov.l   =0x25F80000, r3
    mov     #-1, r2
rg1:
    mov.w   @r4+, r1
    cmp/eq  r2, r1
    bt      rg2
    mov.w   @r4+, r0
    add     r3, r1
    bra     rg1
    mov.w   r0, @r1
rg2:
    rts
    nop

cramload:                       ; r4 -> {u16 index, u16 count, count x u16}*, 0xFFFF ends
    mov     #-1, r2
cl1:
    mov.w   @r4+, r1
    cmp/eq  r2, r1
    bt      cl3
    mov.w   @r4+, r6
    extu.w  r6, r6
    extu.w  r1, r1
    shll    r1
    mov.l   =0x25F00000, r3
    add     r3, r1
cl2:
    mov.w   @r4+, r0
    mov.w   r0, @r1
    add     #2, r1
    dt      r6
    bf      cl2
    bra     cl1
    nop
cl3:
    rts
    nop

unrle:                          ; r4 src, r5 dst, r6 output bytes
    mov.b   @r4+, r0
    extu.b  r0, r0
    tst     #0x80, r0
    bf      ur_run
    add     #1, r0
ur_lit:
    mov.b   @r4+, r1
    mov.b   r1, @r5
    add     #1, r5
    add     #-1, r6
    dt      r0
    bf      ur_lit
    bra     ur_next
    nop
ur_run:
    add     #-126, r0
    mov.b   @r4+, r1
ur_rep:
    mov.b   r1, @r5
    add     #1, r5
    add     #-1, r6
    dt      r0
    bf      ur_rep
ur_next:
    cmp/pl  r6
    bt      unrle
    rts
    nop

expand:                         ; r4 nibbles, r5 dst, r6 pixels (even), r7 base: v -> v + base, 0 -> 0
    mov.b   @r4+, r0
    extu.b  r0, r0
    mov     r0, r1
    shlr2   r1
    shlr2   r1
    tst     r1, r1
    bt      ex1
    add     r7, r1
ex1:
    mov.b   r1, @r5
    add     #1, r5
    and     #15, r0
    tst     r0, r0
    bt      ex2
    add     r7, r0
ex2:
    mov.b   r0, @r5
    add     #1, r5
    add     #-2, r6
    cmp/pl  r6
    bt      expand
    rts
    nop

rcopy:                          ; r4 -> {u32 src, u16 x, u16 y, u16 w, u16 h}, r5 bitmap base (stride 512); words
    mov.l   @r4, r1
    mov.w   @(4, r4), r0
    extu.w  r0, r2
    mov.w   @(6, r4), r0
    extu.w  r0, r3
    mov.w   @(8, r4), r0
    extu.w  r0, r6
    mov.w   @(10, r4), r0
    extu.w  r0, r7
    shll8   r3
    shll    r3
    add     r3, r5
    add     r2, r5
rc1:
    mov     r5, r2
    mov     r6, r3
rc2:
    mov.w   @r1+, r0
    mov.w   r0, @r2
    add     #2, r2
    add     #-2, r3
    cmp/pl  r3
    bt      rc2
    mov     #2, r0
    shll8   r0
    add     r0, r5
    dt      r7
    bf      rc1
    rts
    nop

compose:                        ; r9 = composite id: COMPBUF cleared, its four parts blitted
    mov.l   =COMPBUF, r4
    mov.l   =COMP_BYTES, r6
    mov     #0, r0
cp0:
    mov.l   r0, @r4
    add     #4, r4
    add     #-4, r6
    cmp/pl  r6
    bt      cp0
    mov     r9, r4              ; COMP_TAB + 48 * r9
    shll2   r4
    shll2   r4
    mov     r4, r1
    shll    r4
    add     r1, r4
    mov.l   =COMP_TAB, r1
    add     r1, r4
    mov     #4, r7
cp1:                            ; part {u32 src, u32 dst offset, u16 w, u16 h}, index 0 transparent
    mov.l   @r4, r1
    mov.l   @(4, r4), r2
    mov.l   =COMPBUF, r0
    add     r0, r2
    mov.w   @(8, r4), r0
    extu.w  r0, r6
    mov.w   @(10, r4), r0
    extu.w  r0, r3
cp2:
    mov     r2, r5
    mov     r6, r0
cp3:
    mov.b   @r1+, r10
    tst     r10, r10
    bt      cp4
    mov.b   r10, @r5
cp4:
    add     #1, r5
    dt      r0
    bf      cp3
    mov.l   =COMP_W, r5
    add     r5, r2
    dt      r3
    bf      cp2
    add     #12, r4
    dt      r7
    bf      cp1
    rts
    nop
.pool
"""
# compose borrows r10 as its pixel register: saved and put back around it
PLAYER = PLAYER.replace("""compose:                        ; r9 = composite id: COMPBUF cleared, its four parts blitted
    mov.l   =COMPBUF, r4""", """compose:                        ; r9 = composite id: COMPBUF cleared, its four parts blitted
    mov.l   r10, @-r15
    mov.l   =COMPBUF, r4""").replace("""    add     #12, r4
    dt      r7
    bf      cp1
    rts
    nop""", """    add     #12, r4
    dt      r7
    bf      cp1
    rts
    mov.l   @r15+, r10""")


def build():
    """The IP image (32 KB) with the player at BLOCK. Returns (ip bytes, info)."""
    import sh2s
    A = Assets()
    check_layout(A)
    frames = timeline()
    segs = segments(A, frames)
    # SCRATCH layout: images unpacked, the composite buffer, a zero area for the card wipe
    scratch = SCRATCH
    unpack = []                          # (rle bytes, dst, n pixels, mode)
    nibtmp = 0

    def place(arr, base=None):
        """base None: 8-bpp bytes; else two pixels per byte (value - base, 0 stays 0),
        unpacked through NIBTMP and expanded (`nibbles`)."""
        nonlocal scratch, nibtmp
        raw = np.ascontiguousarray(arr).tobytes()
        at = scratch
        scratch += (len(raw) + 3) & ~3
        if base is None:
            unpack.append((rle(raw), at, len(raw), 0))
        else:
            nb = nibbles(arr, base)
            assert unnibble(nb, base) == raw
            nibtmp = max(nibtmp, len(nb))
            unpack.append((rle(nb), at, len(raw), 0x100 | base))
        return at
    cx, cy, cimg = A.card_rect()
    card_at = place(cimg, 0)
    text_at = [place(t, TEXT_BASE - 1) for t in A.texts]
    part_at = {n: place(a) for n, (a, dx, dy) in A.parts.items()}
    compbuf = scratch
    comp_bytes = (A.cw * A.ch + 3) & ~3
    scratch += comp_bytes
    zero_at = scratch
    scratch += (cimg.size + 3) & ~3
    nib_at = scratch
    scratch += (nibtmp + 3) & ~3
    assert scratch <= SCRATCH_END, hex(scratch)
    for data, dst, n, mode in unpack:     # the decoder's model, stream by stream
        out = unrle(data, n if not mode else n // 2)
        assert len(out) == (n if not mode else n // 2)

    def rect(ptr, x, y, a):
        return struct.pack(">IHHHH", ptr, x, y, a.shape[1], a.shape[0])
    card_rect = rect(card_at, cx, cy, cimg)
    card_wipe = rect(zero_at, cx, cy, cimg)
    text_rects = b"".join(rect(p, x, y, t) for p, (x, y), t in zip(text_at, TEXT_POS, A.texts))
    comp_rect = struct.pack(">IHHHH", compbuf, 0, 0, A.cw, A.ch)
    comp_tab = b""
    for cid in range(len(COMPS)):
        for n in A.comp_parts(cid):
            a, dx, dy = A.parts[n]
            off = (dy - A.oy) * A.cw + (dx - A.ox)
            comp_tab += struct.pack(">IIHH", part_at[n], off, a.shape[1], a.shape[0])
    pal0 = [_rgb555(c) for c in card_palette() + text_palette()]
    pal1 = [_rgb555(c) for c in A.robot_pal]
    cram_tab = struct.pack(">HH", 0, len(pal0)) + struct.pack(f">{len(pal0)}H", *pal0)
    cram_tab += struct.pack(">HH", 256, len(pal1)) + struct.pack(f">{len(pal1)}H", *pal1)
    cram_tab += b"\xff\xff"

    def eyes(colour_of):
        out = b""
        for i in A.eye_idx:
            out += struct.pack(">HHH", 256 + i, 1, colour_of(i))
        return out + b"\xff\xff"
    eyes_lit = eyes(lambda i: pal1[i])
    eyes_dark = eyes(lambda i: _rgb555(EYE_DARK))
    regs_on = {o: 0 for o in range(0, 0x120, 2) if o not in READ_ONLY}
    regs_on.update(OURS_VDP2)
    regs_on[0x000] = 0x8000              # TVMD last: display on once everything is set
    regs_off = {o: PRISTINE_VDP2.get(o, 0) for o in range(0, 0x120, 2) if o not in READ_ONLY}
    regs_off[0x000] = PRISTINE_VDP2[0x000] & 0x7FFF

    def regtab(d):
        order = [o for o in d if o != 0] + [0]
        return b"".join(struct.pack(">HH", o, d[o]) for o in order) + b"\xff\xff"
    tl = b""
    for rep, comp, eye, sx, sy, texts, fade in segs:
        tl += struct.pack(">HhhBBBBH", rep, sx, sy, comp, eye, texts, 0, fade)
    tl += b"\0" * 12
    # data after the code; two passes settle the labels
    tables = [("REGS_ON", regtab(regs_on)), ("REGS_OFF", regtab(regs_off)), ("CRAM_TAB", cram_tab),
              ("EYES_LIT", eyes_lit), ("EYES_DARK", eyes_dark), ("CARD_RECT", card_rect),
              ("CARD_WIPE", card_wipe), ("TEXT_RECTS", text_rects), ("COMP_RECT", comp_rect),
              ("COMP_TAB", comp_tab), ("TIMELINE", tl)]
    consts = dict(BACKUP=BACKUP, SCRATCH_END=SCRATCH_END, A_ENTRY=A_ENTRY, CARD_FRAMES=CARD_FRAMES,
                  COMPBUF=compbuf, NIBTMP=nib_at, COMP_BYTES=comp_bytes, COMP_W=A.cw)
    labels = {name: BLOCK for name, _ in tables + [("UNPACK", 0)]}    # placeholders for the first pass
    for _ in range(3):
        asm = sh2s.Asm(BLOCK)
        asm.consts = dict(consts, **labels)
        code = asm.assemble(PLAYER)
        at = BLOCK + len(code)
        blob, labels = bytearray(code), {}
        for name, data in tables:
            at += -at & 3
            blob += b"\0" * (at - BLOCK - len(blob))
            labels[name] = at
            blob += data
            at += len(data)
        at += -at & 3
        blob += b"\0" * (at - BLOCK - len(blob))
        unp = b""
        stream_at = at + 16 * len(unpack) + 4
        streams = b""
        for data, dst, n, mode in unpack:
            unp += struct.pack(">IIII", stream_at + len(streams), dst, n, mode)
            streams += data
        labels["UNPACK"] = at
        blob += unp + b"\0" * 4 + streams
    assert asm.labels["entry"] == BLOCK
    end = BLOCK + len(blob)
    assert end <= BLOCK_END, f"the player needs {end - BLOCK} bytes, the IP has {BLOCK_END - BLOCK}"
    ip = bytearray(pristine_ip())
    assert ip[:16] == b"SEGA SEGASATURN " and struct.unpack_from(">I", ip, 0xE0)[0] == IP_SIZE_OLD
    assert struct.unpack_from(">I", ip, JSR_LITERAL - IP_BASE)[0] == A_ENTRY
    assert not any(ip[BLOCK - IP_BASE:]), "the IP's tail is not empty"
    struct.pack_into(">I", ip, 0xE0, IP_MAX)
    struct.pack_into(">I", ip, JSR_LITERAL - IP_BASE, BLOCK)
    ip[BLOCK - IP_BASE:end - IP_BASE] = blob
    info = dict(code=len(code), block=len(blob), free=BLOCK_END - end, frames=len(frames), segs=len(segs),
                scratch=scratch - SCRATCH, rle=sum(len(u[0]) for u in unpack),
                raw=sum(u[2] for u in unpack), comp=(A.cw, A.ch), card=(cx, cy) + cimg.shape[::-1])
    return bytes(ip), info


def pristine_ip():
    with open(SRC_T1, "rb") as f:
        raw = f.read(16 * 2352)
    return b"".join(raw[i * 2352 + 16:i * 2352 + 16 + 2048] for i in range(16))


# --- commands ---------------------------------------------------------------------------

def apply():
    ip, info = build()
    os.makedirs(os.path.dirname(IP_OUT), exist_ok=True)
    open(IP_OUT, "wb").write(ip)
    total = CARD_FRAMES + info["frames"]
    print(f"{IP_OUT}: player {info['code']} B code, block {info['block']} B at {BLOCK:#x} "
          f"({info['free']} B free below {BLOCK_END:#x}); images {info['raw']} B -> {info['rle']} B RLE; "
          f"scratch {info['scratch']} B; {info['segs']} segments; card {CARD_FRAMES} + splash {info['frames']} "
          f"= {total} frames ({total / 59.94:.1f} s); jsr literal {JSR_LITERAL:#x} -> {BLOCK:#x}, IP size {IP_MAX:#x}; "
          f"text v{version()}")


def off():
    if os.path.exists(IP_OUT):
        os.remove(IP_OUT)
        print(f"removed {IP_OUT}: the pristine IP ships")


def preview():
    os.makedirs(OUT_DIR, exist_ok=True)
    A = Assets()
    check_layout(A)
    frames = timeline()
    card = render(A, 0, 0, 0, 0, 0, 0, card=True)
    card.resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(OUT_DIR, "preview_card.png"))
    segs = segments(A, frames)
    shots = [card] * (CARD_FRAMES // 30)
    per = []
    for rep, comp, eyes, sx, sy, texts, fade in segs:
        per += [(comp, eyes, sx, sy, texts, fade)] * rep
    for i in range(0, len(per), 2):
        shots.append(render(A, *per[i]))
    shots[0].save(os.path.join(OUT_DIR, "preview.gif"), save_all=True, append_images=shots[1:],
                  duration=33, loop=0)
    snarl = WALK + SETTLE + 21 + (JAW_AT - 21) + 4 + SNARL // 2
    render(A, *per[snarl]).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(OUT_DIR, "preview_snarl.png"))
    render(A, *per[len(per) - FADE - 10]).resize((W * 2, H * 2), Image.NEAREST).save(
        os.path.join(OUT_DIR, "preview_text.png"))
    ip, info = build()
    print(f"{len(frames)} frames after the {CARD_FRAMES}-frame card ({(len(frames) + CARD_FRAMES) / 59.94:.1f} s), "
          f"{info}; {OUT_DIR}/preview.gif, preview_card.png, preview_snarl.png, preview_text.png")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    {"preview": preview, "apply": apply, "off": off}[cmd]()
