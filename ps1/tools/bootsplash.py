"""The second boot screen: a Snatcher walks in and the disclaimer appears.

Runs straight after bootcard.py's PEPA SOFT HOUSE card, still before the
game's own entry point, so it is bare metal like that card: no BIOS calls,
no interrupts, the GPU driven through GP0/GP1 by CPU stores.

The art is the endoskeleton from Chin's scene (CXE_B0D0, the 8bpp parts
sheets g1_00/g1_01): torso, two arm poses (hands down / claws up) and three
heads (jaw shut, open, wide). It slides in from the right along the bottom
of a white screen with its eyes dark, stops, the eyes light up, it bares its
jaw at the player, and the text appears line by line; then a fade to black
and the jump into the game.

Everything the player sees is data, built here:

  - an 8bpp texture page (the parts) at VRAM (640,0) with two 256-entry
    CLUTs, the second one with the red eye colours dimmed;
  - a 4bpp page (the text lines, anti-aliased against white) at (768,0);
  - a sprite table, 12 bytes per sprite: E1 texpage word, clut<<16|v<<8|u,
    h<<16|w;
  - the timeline: per frame a header word `count | repeat<<16` and `count`
    entries `id<<24 | y<<16 | x` (x signed 16-bit); id 0xFF is the fade, a
    semi-transparent subtractive rectangle over the screen with x = level.
    A header of 0xFFFFFFFF ends it.

The player stub (`stub`) double-buffers at (0,0)/(0,256): per frame it fills
the back buffer white, draws the entries, waits a frame and flips. The
frame wait counts LINES_PER_FRAME h-blanks on free-running timer 1 (the
mode bootcard's hold uses) and carries the overshoot. Sync mode 1 (reset at
vblank) worked on Beetle, PCSX ReARMed and SwanStation, but on the MiSTer
the wait never held and the splash flashed past in a moment.

    python ps1/tools/bootsplash.py preview    # work/bootsplash_preview.gif (+ _last.png)

bootcard.py builds the tail with `build(org)` and jumps here instead of
the game's entry.
"""
import os, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import sysfont

from mipsasm import Asm

PARTS = os.path.join(WORK, "gfx", "all", "CXE_B0D0_items", "CXE_B0D0_{}_8bpp.png")
W, H = 320, 240
IO = 0x1F80
BUF_Y = (0, 256)                         # the two framebuffers
ROBOT_PAGE = (640, 0)                    # 8bpp: 128 halfwords wide
TEXT_PAGE = (768, 0)                     # 4bpp: 64 halfwords wide
CLUT_ROBOT = (0, 500)                    # 256 entries each, dark eyes on the next row
CLUT_TEXT = (256, 500)
LINES_PER_FRAME = 263                    # h-blanks per NTSC frame
FADE_ID = 0xFF

TEXT = [                                 # (font, size, ink, text); humanizer-checked
    ("impact.ttf", 22, (176, 16, 16), "DISCLAIMER"),
    ("arial.ttf", 12, (0, 0, 0), "This translation was made with the help of AI and"),
    ("arial.ttf", 12, (0, 0, 0), "reviewed by a fan, not a professional translator."),
    ("arial.ttf", 12, (0, 0, 0), "If you'd rather not play an AI-assisted translation,"),
    ("arial.ttf", 12, (0, 0, 0), "stop here. Otherwise, enjoy the game."),
    ("arial.ttf", 12, (0, 0, 0), "Found a problem? Report it at:"),
    ("arialbd.ttf", 11, (16, 64, 160), "github.com/pepasjc/snatcher-translated"),
]
TEXT_POS = [(16, 16), (16, 46), (16, 60), (16, 74), (16, 88), (16, 110), (16, 126)]
TEXT_CHUNK = 192                         # texels per text sprite
INK_LEVELS = 5                           # anti-alias steps per ink in the 4bpp CLUT

# figure geometry, relative to the torso's top-left corner
HEAD_AT = (17, -30)
L_SHOULDER, R_SHOULDER, SHOULDER_Y = 8, 50, 6
STOP_X, FLOOR_Y = 238, 148               # torso top-left when it stops; hip plate ends at 240
START_X = W + 24                         # left arm still off-screen

# timeline, in frames (59.94 Hz)
WALK, SETTLE, EYES_AT, JAW_AT, SNARL, TEXT_GAP, HOLD, FADE = 200, 30, 0, 36, 50, 8, 260, 32
TEXT_AT = 60                             # the lines start coming in 1 s into the walk


# --- assets --------------------------------------------------------------------

def _rgba(im, box):
    x, y, w, h = box
    a = np.asarray(im.crop((x, y, x + w, y + h)).convert("RGB"))
    alpha = np.where(a.sum(2) > 0, 255, 0).astype(np.uint8)   # index 0 = black = transparent
    return np.dstack([a, alpha])


def _trim(a, dx, dy):
    ys, xs = np.nonzero(a[..., 3])
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return a[y0:y1, x0:x1], dx + x0, dy + y0


def _split_arms(a):
    """The sheet packs both arms shoulder to shoulder in a '^'; the apex is the
    column whose ink starts highest. Left of it = the figure's right arm."""
    top = [np.argmax(a[:, c, 3] > 0) if a[:, c, 3].any() else 1 << 30 for c in range(a.shape[1])]
    ax = int(np.argmin(top))
    return a[:, :ax], a[:, ax:]


def parts():
    """name -> (rgba array, dx, dy) relative to the torso's top-left."""
    g0, g1 = Image.open(PARTS.format("g1_00")), Image.open(PARTS.format("g1_01"))
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


def text_lines():
    """[(index array, ink)] - 0 transparent, 1..INK_LEVELS the ink's AA steps."""
    out = []
    for n, (font, size, ink, s) in enumerate(TEXT):
        f = sysfont.truetype(font, size)
        bb = f.getbbox(s)
        im = Image.new("L", (bb[2] - bb[0] + 2, bb[3] - bb[1] + 2), 0)
        ImageDraw.Draw(im).text((1 - bb[0], 1 - bb[1]), s, font=f, fill=255)
        a = np.asarray(im).astype(np.float32) / 255
        q = np.clip(np.rint(a * INK_LEVELS), 0, INK_LEVELS).astype(np.uint8)
        inks = [t[2] for t in TEXT]
        base = 1 + INK_LEVELS * sorted(set(inks), key=inks.index).index(ink)
        out.append(np.where(q > 0, q - 1 + base, 0).astype(np.uint8))
    return out


def text_clut():
    inks = []
    for t in TEXT:
        if t[2] not in inks:
            inks.append(t[2])
    assert 1 + INK_LEVELS * len(inks) <= 16
    clut = [None] + [tuple(int(round(255 + (c - 255) * (k + 1) / INK_LEVELS)) for c in ink)
                     for ink in inks for k in range(INK_LEVELS)]
    return clut + [(255, 255, 255)] * (16 - len(clut))


def _pack(items, width):
    """Shelf-pack [(name, h, w)] into a page `width` texels wide -> {name: (u, v)}, height."""
    at, x, y, shelf = {}, 0, 0, 0
    for name, h, w in sorted(items, key=lambda t: -t[1]):
        if x + w > width:
            x, y, shelf = 0, y + shelf, 0
        at[name] = (x, y)
        x += w + (w & 1)
        shelf = max(shelf, h)
    return at, y + shelf


def _bgr15(c, opaque=True):
    if c is None:
        return 0
    r, g, b = (v >> 3 for v in c)
    v = r | g << 5 | b << 10
    return v if v else 0x8000            # opaque black must not read as transparent


class Assets:
    def __init__(self):
        P = parts()
        colours = []
        for a, _, _ in P.values():
            for c in map(tuple, a[a[..., 3] > 0][:, :3]):
                if c not in colours:
                    colours.append(c)
        assert len(colours) <= 255, len(colours)
        self.robot_clut = [None] + colours + [(0, 0, 0)] * (255 - len(colours))
        self.robot_clut_dark = [c if c is None or not _is_eye(c) else (48, 40, 40)
                                for c in self.robot_clut]
        index = {c: i for i, c in enumerate(self.robot_clut) if c is not None}
        at, h = _pack([(n, a.shape[0], a.shape[1]) for n, (a, _, _) in P.items()], 256)
        assert h <= 256, h
        self.robot_page = np.zeros((h, 256), np.uint8)
        self.sprites = {}                # name -> (page, u, v, w, h, clut, dx, dy)
        for n, (a, dx, dy) in P.items():
            u, v = at[n]
            idx = np.zeros(a.shape[:2], np.uint8)
            m = a[..., 3] > 0
            idx[m] = [index[tuple(c)] for c in a[m][:, :3]]
            self.robot_page[v:v + a.shape[0], u:u + a.shape[1]] = idx
            self.sprites[n] = ("robot", u, v, a.shape[1], a.shape[0], 0, dx, dy)
            if n.startswith("head"):
                self.sprites[n + "_dark"] = ("robot", u, v, a.shape[1], a.shape[0], 1, dx, dy)
        self.text_clut = text_clut()
        chunks = {}                      # a page is 256 texels wide: cut longer lines
        for i, a in enumerate(text_lines()):
            for k in range(0, a.shape[1], TEXT_CHUNK):
                chunks[f"text{i}.{k // TEXT_CHUNK}"] = (a[:, k:k + TEXT_CHUNK], k)
        at, h = _pack([(n, a.shape[0], a.shape[1]) for n, (a, _) in chunks.items()], 256)
        assert h <= 256, h
        self.text_page = np.zeros((h, 256), np.uint8)
        for n, (a, dx) in chunks.items():
            u, v = at[n]
            self.text_page[v:v + a.shape[0], u:u + a.shape[1]] = a
            self.sprites[n] = ("text", u, v, a.shape[1], a.shape[0], 0, dx, 0)
        self.ids = {n: i for i, n in enumerate(self.sprites)}
        assert len(self.ids) < FADE_ID

    # VRAM images, as halfword arrays (h, w)
    def robot_vram(self):
        p = self.robot_page
        return (p[:, 0::2].astype(np.uint16) | p[:, 1::2].astype(np.uint16) << 8)

    def text_vram(self):
        p = self.text_page
        return (p[:, 0::4].astype(np.uint16) | p[:, 1::4].astype(np.uint16) << 4
                | p[:, 2::4].astype(np.uint16) << 8 | p[:, 3::4].astype(np.uint16) << 12)

    def uploads(self):
        """[(x, y, halfword array)] in VRAM."""
        clut = lambda c: np.array([[_bgr15(x) for x in c]], np.uint16)
        return [(*ROBOT_PAGE, self.robot_vram()), (*TEXT_PAGE, self.text_vram()),
                (CLUT_ROBOT[0], CLUT_ROBOT[1], clut(self.robot_clut)),
                (CLUT_ROBOT[0], CLUT_ROBOT[1] + 1, clut(self.robot_clut_dark)),
                (*CLUT_TEXT, clut(self.text_clut))]

    def sprite_table(self):
        out = bytearray()
        for n, (page, u, v, w, h, alt, _, _) in self.sprites.items():
            if page == "robot":
                tp = ROBOT_PAGE[0] // 64 | 1 << 7            # 8bpp
                cx, cy = CLUT_ROBOT[0], CLUT_ROBOT[1] + alt
            else:
                tp = TEXT_PAGE[0] // 64                       # 4bpp
                cx, cy = CLUT_TEXT
            clut = cy << 6 | cx >> 4
            out += struct.pack("<III", 0xE1000000 | 1 << 10 | tp, clut << 16 | v << 8 | u, h << 16 | w)
        return bytes(out)


# --- the timeline ----------------------------------------------------------------

def _ease_out(t):
    return 1 - (1 - t) ** 3


def timeline(A):
    """[(entries, fade)] one per frame; entries = [(sprite name, x, y)]."""
    frames = []

    def figure(x, y, pose=0, head="head0_dark"):
        out = []
        for n in (f"armL{pose}", f"armR{pose}", "torso", head):
            dx, dy = A.sprites[n][6:8]
            out.append((n, x + dx, y + dy))
        return out

    robot = []
    for f in range(WALK):
        x = round(START_X + (STOP_X - START_X) * _ease_out(f / (WALK - 1)))
        step = (f // 12) % 2 if f < WALK - 24 else 0      # a one-pixel bob per step
        robot.append(figure(x, FLOOR_Y + step))
    still = lambda **kw: figure(STOP_X, FLOOR_Y, **kw)
    robot += [still()] * SETTLE
    for lit in (1, 0, 0, 1, 1, 0, 1):                    # the eyes flicker on
        robot += [still(head="head0" if lit else "head0_dark")] * 3
    robot += [still(head="head0")] * (JAW_AT - 21)
    robot += [still(head="head1")] * 4
    robot += [still(pose=1, head="head2")] * SNARL
    robot += [still(pose=1, head="head1")] * 4
    robot += [still(head="head0")] * (20 + HOLD)
    # the text comes in over the walk, one line every TEXT_GAP frames
    lines = [[(n, x + A.sprites[n][6], y) for n in A.sprites if n.startswith(f"text{i}.")]
             for i, (x, y) in enumerate(TEXT_POS)]
    shown_at = lambda f: [e for i, l in enumerate(lines) if f >= TEXT_AT + i * TEXT_GAP for e in l]
    for f, fig in enumerate(robot):
        frames.append((fig + shown_at(f), 0))
    for f in range(1, FADE + 1):
        frames.append((still(head="head0") + shown_at(len(robot)), min(255, round(255 * f / FADE))))
    frames += [([], 255)] * 4
    return frames


def encode(A, frames):
    out, prev, rep = bytearray(), None, 0

    def flush():
        if prev is None:
            return
        ents, fade = prev
        words = [(A.ids[n] << 24 | (y & 0xFF) << 16 | (x & 0xFFFF)) for n, x, y in ents]
        if fade:
            words.append(FADE_ID << 24 | fade)
        out.extend(struct.pack("<I", len(words) | rep << 16))
        out.extend(struct.pack(f"<{len(words)}I", *words))

    for fr in frames:
        if fr == prev and rep < 0xFFFF:
            rep += 1
        else:
            flush()
            prev, rep = fr, 1
    flush()
    return bytes(out + struct.pack("<I", 0xFFFFFFFF))


# --- the Python model (what the stub draws) -------------------------------------

def render(A, entries, fade):
    im = np.full((H, W, 3), 255, np.float32)
    rgb = lambda c: (255, 255, 255) if c is None else c
    for n, x, y in entries:
        page, u, v, w, h, alt, _, _ = A.sprites[n]
        src = (A.robot_page if page == "robot" else A.text_page)[v:v + h, u:u + w]
        clut = (A.robot_clut_dark if alt else A.robot_clut) if page == "robot" else A.text_clut
        # through the 15-bit CLUT, as the GPU sees it
        pal = np.array([[(_bgr15(c) >> s & 31) << 3 for s in (0, 5, 10)] for c in clut], np.float32)
        for yy in range(h):
            sy = y + yy
            if not 0 <= sy < H:
                continue
            for xx in range(w):
                sx, i = x + xx, src[yy, xx]
                if i and 0 <= sx < W:
                    im[sy, sx] = pal[i]
    if fade:
        im = np.maximum(im // 8 - (fade >> 3), 0) * 8           # 5-bit B-F
    return Image.fromarray(im.astype(np.uint8))


def preview():
    A = Assets()
    frames = timeline(A)
    shots, last = [], None
    for i in range(0, len(frames), 2):
        shots.append(render(A, *frames[i]))
    shots[0].save(os.path.join(WORK, "bootsplash_preview.gif"), save_all=True,
                  append_images=shots[1:], duration=33, loop=0)
    render(A, *frames[len(frames) - FADE - 10]).resize((640, 480), Image.NEAREST).save(
        os.path.join(WORK, "bootsplash_last.png"))
    data = encode(A, frames)
    print(f"{len(frames)} frames ({len(frames) / 59.94:.1f} s), timeline {len(data)} B, "
          f"robot page {A.robot_page.shape}, text page {A.text_page.shape}, "
          f"{len(A.sprites)} sprites; work/bootsplash_preview.gif, work/bootsplash_last.png")


# --- the player stub --------------------------------------------------------------

def _gp0_ready(a, lab):
    a.label(lab)                         # GPUSTAT bit 26: ready for a command word
    a.lw("$t9", 0x1814, "$t0")
    a.nop()
    a.srl("$t9", "$t9", 26)
    a.andi("$t9", "$t9", 1)
    a.beq("$t9", "$zero", lab)
    a.nop()


def _li(a, reg, v):
    a.lui(reg, v >> 16 & 0xFFFF)
    a.ori(reg, reg, v & 0xFFFF)


def stub(org, orig_pc, uploads_at, n_uploads, sprites_at, timeline_at):
    a = Asm(org)
    a.lui("$t0", IO)
    # uploads: {xy, wh, src, nwords} each, CPU -> VRAM like bootcard's card
    _li(a, "$a0", uploads_at)
    a.ori("$a1", "$zero", n_uploads)
    a.label("up")
    a.label("up_ready")                  # GPUSTAT bit 28: ready for a DMA block
    a.lw("$t9", 0x1814, "$t0")
    a.nop()
    a.srl("$t9", "$t9", 28)
    a.andi("$t9", "$t9", 1)
    a.beq("$t9", "$zero", "up_ready")
    a.nop()
    a.lui("$t1", 0xA000)
    a.sw("$t1", 0x1810, "$t0")
    a.lw("$t1", 0, "$a0")
    a.nop()
    a.sw("$t1", 0x1810, "$t0")
    a.lw("$t1", 4, "$a0")
    a.nop()
    a.sw("$t1", 0x1810, "$t0")
    a.lw("$t2", 8, "$a0")
    a.lw("$t3", 12, "$a0")
    a.nop()
    a.label("up_word")
    a.lw("$t1", 0, "$t2")
    a.addiu("$t2", "$t2", 4)
    a.sw("$t1", 0x1810, "$t0")
    a.addiu("$t3", "$t3", -1)
    a.bne("$t3", "$zero", "up_word")
    a.nop()
    a.addiu("$a1", "$a1", -1)
    a.bne("$a1", "$zero", "up")
    a.addiu("$a0", "$a0", 16)
    # timer 1: h-blanks, free-running (no sync mode: see the docstring)
    a.ori("$t1", "$zero", 0x0100)
    a.sw("$t1", 0x1114, "$t0")
    _li(a, "$a0", timeline_at)
    _li(a, "$a2", sprites_at)
    a.ori("$a1", "$zero", 1)             # draw into buffer 1 first; the card stays up in 0
    a.label("frame")
    a.lw("$v0", 0, "$a0")
    a.addiu("$t1", "$zero", -1)
    a.beq("$v0", "$t1", "done")
    a.addiu("$a0", "$a0", 4)
    a.srl("$a3", "$v0", 16)              # repeat
    a.andi("$v1", "$v0", 0xFFFF)         # entries
    a.label("rep")
    a.sll("$t4", "$a1", 8)               # buffer y
    _gp0_ready(a, "r_e3")
    a.sll("$t1", "$t4", 10)
    a.lui("$t2", 0xE300)
    a.or_("$t1", "$t1", "$t2")
    a.sw("$t1", 0x1810, "$t0")           # draw area top-left
    a.addiu("$t1", "$t4", H - 1)
    a.sll("$t1", "$t1", 10)
    a.ori("$t1", "$t1", W - 1)
    a.lui("$t2", 0xE400)
    a.or_("$t1", "$t1", "$t2")
    a.sw("$t1", 0x1810, "$t0")           # bottom-right
    a.sll("$t1", "$t4", 11)
    a.lui("$t2", 0xE500)
    a.or_("$t1", "$t1", "$t2")
    a.sw("$t1", 0x1810, "$t0")           # offset
    _gp0_ready(a, "r_fill")
    _li(a, "$t1", 0x02FFFFFF)
    a.sw("$t1", 0x1810, "$t0")
    a.sll("$t1", "$t4", 16)
    a.sw("$t1", 0x1810, "$t0")
    _li(a, "$t1", H << 16 | W)
    a.sw("$t1", 0x1810, "$t0")
    a.or_("$t5", "$a0", "$zero")         # entry cursor
    a.or_("$t6", "$v1", "$zero")
    a.label("ent")
    a.beq("$t6", "$zero", "ents_done")
    a.nop()
    a.lw("$t7", 0, "$t5")
    a.addiu("$t5", "$t5", 4)
    a.addiu("$t6", "$t6", -1)
    a.srl("$t8", "$t7", 24)              # id
    a.ori("$t1", "$zero", FADE_ID)
    a.beq("$t8", "$t1", "fade")
    a.sll("$t1", "$t8", 3)               # id * 12
    a.sll("$t2", "$t8", 2)
    a.addu("$t1", "$t1", "$t2")
    a.addu("$t1", "$t1", "$a2")
    _gp0_ready(a, "r_tp")
    a.lw("$t2", 0, "$t1")
    a.nop()
    a.sw("$t2", 0x1810, "$t0")           # E1 texpage
    _gp0_ready(a, "r_spr")
    a.lui("$t2", 0x6500)                 # textured rectangle, raw texture
    a.sw("$t2", 0x1810, "$t0")
    a.lui("$t2", 0x00FF)
    a.ori("$t2", "$t2", 0xFFFF)
    a.and_("$t2", "$t7", "$t2")          # y<<16 | x
    a.sw("$t2", 0x1810, "$t0")
    a.lw("$t2", 4, "$t1")
    a.nop()
    a.sw("$t2", 0x1810, "$t0")           # clut, v, u
    a.lw("$t2", 8, "$t1")
    a.nop()
    a.sw("$t2", 0x1810, "$t0")           # h, w
    a.b("ent")
    a.nop()
    a.label("fade")                      # subtract x from every channel
    _gp0_ready(a, "r_ftp")
    _li(a, "$t2", 0xE1000000 | 1 << 10 | 2 << 5)
    a.sw("$t2", 0x1810, "$t0")
    _gp0_ready(a, "r_frect")
    a.andi("$t2", "$t7", 0xFF)
    a.sll("$t1", "$t2", 8)
    a.or_("$t2", "$t2", "$t1")
    a.sll("$t1", "$t1", 8)
    a.or_("$t2", "$t2", "$t1")
    a.lui("$t1", 0x6200)                 # monochrome rectangle, semi-transparent
    a.or_("$t2", "$t2", "$t1")
    a.sw("$t2", 0x1810, "$t0")
    a.sw("$zero", 0x1810, "$t0")
    _li(a, "$t2", H << 16 | W)
    a.sw("$t2", 0x1810, "$t0")
    a.b("ent")
    a.nop()
    a.label("ents_done")
    # one frame = LINES_PER_FRAME h-blanks on the free-running counter; the
    # overshoot is carried into the next frame so the pace does not drift
    a.label("vb")
    a.lhu("$t3", 0x1110, "$t0")
    a.nop()
    a.sltiu("$t1", "$t3", LINES_PER_FRAME)
    a.bne("$t1", "$zero", "vb")
    a.nop()
    a.addiu("$t3", "$t3", -LINES_PER_FRAME)
    a.sw("$t3", 0x1110, "$t0")
    a.sll("$t1", "$t4", 10)              # GP1 05: display start (0, buffer y)
    a.lui("$t2", 0x0500)
    a.or_("$t1", "$t1", "$t2")
    a.sw("$t1", 0x1814, "$t0")
    a.xori("$a1", "$a1", 1)
    a.addiu("$a3", "$a3", -1)
    a.bne("$a3", "$zero", "rep")
    a.nop()
    a.sll("$t1", "$v1", 2)
    a.b("frame")
    a.addu("$a0", "$a0", "$t1")
    a.label("done")
    a.ori("$t1", "$zero", 0x0100)        # timer 1 as bootcard leaves it
    a.sw("$t1", 0x1114, "$t0")
    a.j(orig_pc)
    a.nop()
    return a


def build(org, orig_pc):
    """The tail block at `org`: stub, uploads table, sprite table, timeline,
    pixel data. Returns bytes (word aligned)."""
    A = Assets()
    data = encode(A, timeline(A))
    sprites = A.sprite_table()
    ups = A.uploads()
    size = stub(org, orig_pc, 0, len(ups), 0, 0).size()
    tab_at = org + size
    spr_at = tab_at + 16 * len(ups)
    tl_at = spr_at + len(sprites)
    pix_at = tl_at + len(data)
    table, pix = bytearray(), bytearray()
    for x, y, hw in ups:
        h, w = hw.shape
        assert w % 2 == 0 or h % 2 == 0, (x, y, w, h)
        raw = hw.astype("<u2").tobytes()
        raw += b"\0" * (-len(raw) % 4)
        table += struct.pack("<IIII", y << 16 | x, h << 16 | w, pix_at + len(pix), len(raw) // 4)
        pix += raw
    code = stub(org, orig_pc, tab_at, len(ups), spr_at, tl_at).assemble()
    out = code + table + sprites + data + pix
    return out + b"\0" * (-len(out) % 4)


if __name__ == "__main__":
    {"preview": preview}[sys.argv[1]]()
