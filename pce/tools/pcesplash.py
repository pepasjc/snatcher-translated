"""Two boot screens before the game proper: the PEPA SOFT HOUSE card and the
Snatcher splash with the disclaimer - the PS1's bootcard.py + bootsplash.py,
redrawn for the PC Engine.

  1. The card (CARD frames, 3 s): white, "PEPA SOFT HOUSE" in Impact between
     two black bars, a small grey "ENGLISH TRANSLATION  v<pce/VERSION>  ·  2026"
     under it - ps1/tools/splash.py card(), re-laid for 256 pixels.
  2. The splash (640 frames, 10.7 s; ps1/tools/bootsplash.py's timeline frame for frame):
     the endoskeleton from Chin's scene (the PS1's CXE_B0D0 parts - torso, two
     arm poses, three heads) slides in along the bottom with its eyes dark and
     a one-pixel bob per step, stops at the bottom right, the eyes flicker on,
     it opens its jaw with its claws up, shuts it, the disclaimer appears line
     by line, holds, and everything fades to black.

Mechanism. The IPL (track sector 1) loads stage 1 at $3000; stage 1 checks
the System Card, maps MPR2-6 = $68-$6C and CD_READs stage 2 (sector 22) into
$68 at $30A8. `apply` puts `JSR LOADER; NOP` over the `LDA #0 / TAM #$80`
just before that read ($30A4) and a loader into stage 1's own zero tail
($3300, sector 2). The loader CD_READs the blob (the player + its data, BLOB
sectors at a fixed place in the reserved sectors past the modules, clear of
the 150-sector gap before the audio tracks) into Super CD-ROM RAM $70-$74,
maps it at $4000-$DFFF and calls it; on return it zeroes $70-$7F (blank in
the pristine boot at that point), puts MPR2-7 back and stage 1 carries on
with its own read of stage 2. Nothing of the game is touched.

The player owns the machine: PHP/SEI (no BIOS vsync handler runs), saves
the whole VRAM into $78-$7F (TAI from the VDC data port) and the VCE palette,
then sets its own VDC state - display off during the uploads, MWR 0x10 (a
64x32 map: the card in columns 32-63, the disclaimer in 0-31, switched by
BXR), SAT DMA every vblank from a double-buffered VRAM SAT (0x0800/0x0900).
It paces on the VDC status VD bit (CR bit 3 set, the CPU's I flag set, so
the IRQ is never taken; reading status acknowledges it). Per frame: wait
vblank, apply the pending palette set / BAT patch / BXR / CR (all VCE writes
inside vblank), then write the figure's SAT for the next frame. The fade is
eight palette sets (every channel minus L, the PS1's subtractive fade in
3-bit). At the end: display off, VRAM back, MWR/BXR/BYR/DCR/DVSSR/CR as the
BIOS left them at the hook (measured on a probe image that stopped there: CR
0xC8, MWR 0, BXR/BYR 0, DCR 0, DVSSR 0x0700), the palette black but for
entry 511 (the BIOS's own would bring its JUST A MOMENT screen back while
stage 2 loads), PLP, RTS. The dot clock and the display timing (256 x 240,
the BIOS's) are never written. The PCE title is up ~840 frames later than
before (~2640 instead of ~1800) and waits for I, so no harness press moved.

The art: the PS1's parts sheets (the PCE copy of the endoskeleton was not
found in the time allowed; see the journal), read from SPLASH_ART or
ROOT/work/gfx/all/CXE_B0D0_items (the PS1 build renders it) and cached in work/pce/splash/
(never committed). Quantised to the 9-bit VCE colours, merged to 15 colours
(one sprite palette; a second with the eyes dark), cut into 16x16 sprites.
Text: Arial/Impact anti-aliased over white in 4 ink steps, one BG palette
for the disclaimer (black, red, blue ramps), one for the card (black, grey).

  python pce/tools/pcesplash.py preview   # work/pce/splash_preview.gif + splash_{card,walk75,walk120,snarl,text}.png
  python pce/tools/pcesplash.py apply     # patched/pce: the blob, the loader, the hook
"""
import os, shutil, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import sysfont

import asm6280
import patch_pce as P

W, H = 256, 240
VERSION = open(os.path.join(ROOT, "pce", "VERSION")).read().strip()
ART = os.environ.get("SPLASH_ART") or os.path.join(ROOT, "work", "gfx", "all", "CXE_B0D0_items")
CACHE = os.path.join(WORK, "pce", "splash")
PART_FILE = "CXE_B0D0_{}_8bpp.png"

# --- the card (ps1/tools/splash.py card(), centred on 256) ---
TITLE = "PEPA SOFT HOUSE"
SUB = f"ENGLISH TRANSLATION  v{VERSION}  ·  2026"
FONT = ("impact.ttf", 26)
SUBFONT = ("arialbd.ttf", 10)            # the PS1's 11 would run 230 px
CARD = 180                               # frames (bootcard.py HOLD_S = 3.0)

# --- the disclaimer (bootsplash.py's words and inks; sizes for 256 wide) ---
TEXT = [                                 # (font, size, ink, text) - the PS1's reviewed lines and breaks
    ("impact.ttf", 22, (176, 16, 16), "DISCLAIMER"),
    ("arial.ttf", 10, (0, 0, 0), "This translation was made with the help of AI and"),
    ("arial.ttf", 10, (0, 0, 0), "reviewed by a fan, not a professional translator."),
    ("arial.ttf", 10, (0, 0, 0), "If you'd rather not play an AI-assisted translation,"),
    ("arial.ttf", 10, (0, 0, 0), "stop here. Otherwise, enjoy the game."),
    ("arial.ttf", 10, (0, 0, 0), "Found a problem? Report it at:"),
    ("arialbd.ttf", 10, (16, 64, 160), "github.com/pepasjc/snatcher-translated"),
]
# Arial 10 keeps the PS1's four breaks (the widest line is 246 px; at 11 two
# lines run past 248 and any re-break needs a fifth line, which pushes the URL
# into the robot's rows). Every line ends above the figure's head (y 118).
TEXT_X = 5
TEXT_Y = [11, 38, 51, 64, 77, 90, 103]         # tile-aligned for 16 sectors; the URL ends 4 px above the head
INK_LEVELS = 4                           # anti-alias steps per ink

# --- the figure (bootsplash.py's geometry, relative to the torso's top-left) ---
HEAD_AT = (17, -30)
L_SHOULDER, R_SHOULDER, SHOULDER_Y = 8, 50, 6
STOP_X, FLOOR_Y = W - 82, 148            # the PS1's 238 on 320: the claws end at the right edge
START_X = W + 24
WALK, SETTLE, EYES_AT, JAW_AT, SNARL, TEXT_GAP, HOLD, FADE = 200, 30, 0, 36, 50, 8, 260, 32
TEXT_AT = 60                             # the lines start coming in 1 s into the walk
DARK_EYE = (48, 40, 40)

# --- VRAM (word addresses) and the machine ---
BAT_W, BAT_H = 64, 32                    # MWR 0x10
SAT_BUF = (0x0800, 0x0900)
TILE_BASE = 0x1000
MWR_SPLASH = 0x10
HOOK = {"CR": 0x00C8, "MWR": 0x0000, "BXR": 0, "BYR": 0, "DCR": 0, "DVSSR": 0x0700}   # at $30A4, measured
BLOB_BANK = 0x70                         # $70-$74 at $4000-$DFFF
SAVE_BANK = 0x78                         # VRAM snapshot $78-$7F
ORG = 0x4000
BLOB_MAX = 5 * 0x2000
MAGIC = b"PEPASPLASH"
PAL_BLANK = 511                          # VCE entries the BIOS blanks after the hook

# --- stage 1 ---
STAGE1_SECTOR = 2                        # track-relative; loaded at $3000 by the IPL
HOOK_AT = 0x30A4                         # LDA #$00 / TAM #$80, right before stage 2's read
HOOK_ORIG = bytes([0xA9, 0x00, 0x53, 0x80])
LOADER = 0x3300                          # stage 1's zero tail $32A0-$37FF
LOADER_END = 0x3800
POSTGAP = 150                            # blank sectors kept at the end of track 2


# ============================================================================
# assets
# ============================================================================

def _art(name):
    src = os.path.join(ART, PART_FILE.format(name))
    cached = os.path.join(CACHE, PART_FILE.format(name))
    if os.path.exists(src):
        os.makedirs(CACHE, exist_ok=True)
        if not os.path.exists(cached) or open(src, "rb").read() != open(cached, "rb").read():
            shutil.copyfile(src, cached)
    if not os.path.exists(cached):
        raise SystemExit(f"no endoskeleton art: {src} (set SPLASH_ART to the CXE_B0D0_items directory)")
    return Image.open(cached)


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
    """bootsplash.parts(): name -> (rgba, dx, dy) relative to the torso's top-left."""
    g0, g1 = _art("g1_00"), _art("g1_01")
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


def q9(c):
    """RGB -> (r, g, b) in 0..7."""
    return tuple(int(round(v * 7 / 255)) for v in c)


def q9_art(c):
    """q9 for the art: a near-grey stays grey (the sheet's darks carry a slight green
    that 3-bit rounding turns into (0, 1, 0), a plain green)."""
    if max(c) - min(c) <= 16:
        v = int(round(sum(c) / 3 * 7 / 255))
        return (v, v, v)
    return q9(c)


def rgb9(t):
    return tuple(int(round(v * 255 / 7)) for v in t)


def vce(t):
    r, g, b = t
    return g << 6 | r << 3 | b


def _merge_to(colours, counts, eyes, n):
    """Merge the rarest colour into its nearest same-kind neighbour until <= n."""
    cols = list(colours)
    mapping = {c: c for c in cols}
    while len(cols) > n:
        rare = min(cols, key=lambda c: counts[c])
        kind = rare in eyes
        pool = [c for c in cols if c != rare and (c in eyes) == kind] or [c for c in cols if c != rare]
        near = min(pool, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, rare)))
        for k, v in mapping.items():
            if v == rare:
                mapping[k] = near
        counts[near] += counts[rare]
        cols.remove(rare)
    return cols, mapping


class Robot:
    """Sprite patterns (16x16, 15 colours + transparent) and the figure's configurations."""

    def __init__(self):
        P_ = parts()
        counts, eyes = {}, set()
        for a, _, _ in P_.values():
            for c in map(tuple, a[a[..., 3] > 0][:, :3]):
                q = q9_art(c)
                counts[q] = counts.get(q, 0) + 1
                if _is_eye(c):
                    eyes.add(q)
        cols, mapping = _merge_to(sorted(counts, key=lambda c: -counts[c]), dict(counts), eyes, 15)
        self.colours = cols                              # palette entries 1..15
        idx = {c: i + 1 for i, c in enumerate(cols)}
        self.pal_lit = [(7, 7, 7)] + cols + [(7, 7, 7)] * (15 - len(cols))
        dark = q9(DARK_EYE)
        self.pal_dark = [c if c not in eyes else dark for c in self.pal_lit]
        self.pal_dark[0] = self.pal_lit[0]
        self.parts = {}                                   # name -> (index array, dx, dy)
        for n, (a, dx, dy) in P_.items():
            m = a[..., 3] > 0
            ia = np.zeros(a.shape[:2], np.uint8)
            for y, x in zip(*np.nonzero(m)):
                ia[y, x] = idx[mapping[q9_art(tuple(a[y, x, :3]))]]
            self.parts[n] = (ia, dx, dy)
        self.patterns = []                                # 16x16 index arrays
        self._pat = {}
        self.cells = {}                                   # part -> [(dy, dx, pattern#)]
        for n, (ia, dx, dy) in self.parts.items():
            h, w = ia.shape
            out = []
            for cy in range(0, h, 16):
                for cx in range(0, w, 16):
                    cell = np.zeros((16, 16), np.uint8)
                    blk = ia[cy:cy + 16, cx:cx + 16]
                    cell[:blk.shape[0], :blk.shape[1]] = blk
                    if not cell.any():
                        continue
                    key = cell.tobytes()
                    if key not in self._pat:
                        self._pat[key] = len(self.patterns)
                        self.patterns.append(cell)
                    out.append((dy + cy, dx + cx, self._pat[key]))
            self.cells[n] = out

    def config(self, pose, head, lit):
        """[(dy, dx, pattern#, palette)] front to back: head, torso, arms."""
        out = []
        for n, pal in ((head, 0 if lit else 1), ("torso", 0), (f"armL{pose}", 0), (f"armR{pose}", 0)):
            out += [(dy, dx, p, pal) for dy, dx, p in self.cells[n]]
        return out

    def box(self, cfg, x, y):
        xs, ys = [], []
        for dy, dx, p, _ in cfg:
            pat = self.patterns[p]
            yy, xx = np.nonzero(pat)
            xs += [x + dx + xx.min(), x + dx + xx.max()]
            ys += [y + dy + yy.min(), y + dy + yy.max()]
        return min(xs), min(ys), max(xs), max(ys)


# --- text -------------------------------------------------------------------

def _alpha_text(s, font, size):
    f = sysfont.truetype(font, size)
    bb = f.getbbox(s)
    im = Image.new("L", (bb[2] - bb[0] + 2, bb[3] - bb[1] + 2), 0)
    ImageDraw.Draw(im).text((1 - bb[0], 1 - bb[1]), s, font=f, fill=255)
    return np.asarray(im)


def _levels(a):
    return np.clip(np.rint(a.astype(np.float32) / 255 * INK_LEVELS), 0, INK_LEVELS).astype(np.uint8)


def _ramp(ink):
    return [q9(tuple(255 + (c - 255) * (k + 1) / INK_LEVELS for c in ink)) for k in range(INK_LEVELS)]


def disclaimer_palette():
    inks = []
    for t in TEXT:
        if t[2] not in inks:
            inks.append(t[2])
    pal = [(7, 7, 7)] + [c for ink in inks for c in _ramp(ink)]
    assert len(pal) <= 16
    return pal + [(7, 7, 7)] * (16 - len(pal)), inks


def disclaimer_lines():
    """[(levels array, x, y, palette base)]"""
    _, inks = disclaimer_palette()
    out = []
    for (font, size, ink, s), y in zip(TEXT, TEXT_Y):
        a = _levels(_alpha_text(s, font, size))
        out.append((a, TEXT_X, y, 1 + INK_LEVELS * inks.index(ink)))
    return out


def disclaimer_screen(k):
    """The disclaimer with its first k lines: 256x240 palette indices (BG palette 0)."""
    im = np.zeros((H, W), np.uint8)
    for a, x, y, base in disclaimer_lines()[:k]:
        h, w = a.shape
        assert x + w <= W and y + h <= H, (x, w, y, h)
        region = im[y:y + h, x:x + w]
        region[a > 0] = (a[a > 0] - 1 + base)
    return im


CARD_INKS = [(0, 0, 0), (90, 90, 90)]


def card_palette():
    pal = [(7, 7, 7)] + _ramp(CARD_INKS[0]) + _ramp(CARD_INKS[1])
    return pal + [(7, 7, 7)] * (16 - len(pal))


def card_screen():
    """splash.card() on 256 x 240, as ink layers -> palette indices (BG palette 1)."""
    title = Image.new("L", (W, H), 0)
    sub = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(title)
    f = sysfont.truetype(*FONT)
    bb = d.textbbox((0, 0), TITLE, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    cx, cy = W // 2, H // 2 - 6
    bar_w = tw + 24
    d.rectangle([cx - bar_w // 2, cy - th // 2 - 14, cx + bar_w // 2, cy - th // 2 - 10], fill=255)
    d.rectangle([cx - bar_w // 2, cy + th // 2 + 10, cx + bar_w // 2, cy + th // 2 + 14], fill=255)
    d.text((cx - tw // 2 - bb[0], cy - th // 2 - bb[1]), TITLE, font=f, fill=255)
    ds = ImageDraw.Draw(sub)
    fs = sysfont.truetype(*SUBFONT)
    sb = ds.textbbox((0, 0), SUB, font=fs)
    assert sb[2] - sb[0] <= W - 16, sb
    ds.text((cx - (sb[2] - sb[0]) // 2 - sb[0], cy + th // 2 + 22 - sb[1]), SUB, font=fs, fill=255)
    im = np.zeros((H, W), np.uint8)
    for layer, base in ((title, 1), (sub, 1 + INK_LEVELS)):
        a = _levels(np.asarray(layer))
        im[a > 0] = a[a > 0] - 1 + base
    return im


# ============================================================================
# VRAM images
# ============================================================================

def tile_words(t):
    """8x8 indices -> 16 VRAM words (planes 0/1 in words 0-7, 2/3 in 8-15)."""
    out = []
    for plane_pair in (0, 2):
        for r in range(8):
            lo = hi = 0
            for c in range(8):
                v = int(t[r, c])
                lo = lo << 1 | (v >> plane_pair & 1)
                hi = hi << 1 | (v >> (plane_pair + 1) & 1)
            out.append(lo | hi << 8)
    return out


def sprite_words(p):
    """16x16 indices -> 64 VRAM words (plane n = words 16n..16n+15, MSB leftmost)."""
    out = []
    for plane in range(4):
        for r in range(16):
            w = 0
            for c in range(16):
                w = w << 1 | (int(p[r, c]) >> plane & 1)
            out.append(w)
    return out


class Screens:
    """The tile set, the BAT images per stage and the patches between them."""

    def __init__(self):
        self.tiles, self._t = [], {}
        self.blank = self.tile(np.zeros((8, 8), np.uint8))
        card = self.bat_of(card_screen(), 1)
        self.stages = [self.bat_of(disclaimer_screen(k), 0) for k in range(len(TEXT) + 1)]
        bat = np.full((BAT_H, BAT_W), self.word(self.blank, 0), np.uint16)
        bat[:H // 8, 32:64] = card
        bat[:H // 8, 0:32] = self.stages[0]
        self.initial = bat
        self.patches = []                                # stage k-1 -> k: [(vram, [words])]
        for k in range(1, len(self.stages)):
            runs = []
            a, b = self.stages[k - 1], self.stages[k]
            for r in range(a.shape[0]):
                diff = np.nonzero(a[r] != b[r])[0]
                if len(diff):
                    c0, c1 = diff.min(), diff.max() + 1
                    runs.append((r * BAT_W + c0, [int(v) for v in b[r, c0:c1]]))
            self.patches.append(runs)

    def tile(self, t):
        key = t.tobytes()
        if key not in self._t:
            self._t[key] = len(self.tiles)
            self.tiles.append(t.copy())
        return self._t[key]

    def word(self, i, pal):
        return pal << 12 | (TILE_BASE // 16 + i)

    def bat_of(self, im, pal):
        out = np.zeros((H // 8, W // 8), np.uint16)
        for r in range(H // 8):
            for c in range(W // 8):
                out[r, c] = self.word(self.tile(im[r * 8:r * 8 + 8, c * 8:c * 8 + 8]), pal)
        return out


# ============================================================================
# the timeline
# ============================================================================

def _ease_out(t):
    return 1 - (1 - t) ** 3


def frames():
    """bootsplash.timeline() for the PCE: per frame (screen, figure, fade level)
    - screen 'card' or the disclaimer stage 0..7 (lines shown), figure (pose, head,
    lit, x, y) or None, fade 0..7 (every channel minus the level). The lines come
    in from TEXT_AT, one every TEXT_GAP frames, while the robot walks."""
    def fig(x, y, pose=0, head="head0", lit=False):
        return (pose, head, lit, x, y)

    robot = []
    for f in range(WALK):
        x = round(START_X + (STOP_X - START_X) * _ease_out(f / (WALK - 1)))
        step = (f // 12) % 2 if f < WALK - 24 else 0
        robot.append(fig(x, FLOOR_Y + step))
    still = lambda **kw: fig(STOP_X, FLOOR_Y, **kw)
    robot += [still()] * SETTLE
    for lit in (1, 0, 0, 1, 1, 0, 1):
        robot += [still(lit=bool(lit))] * 3
    robot += [still(lit=True)] * (JAW_AT - 21)
    robot += [still(head="head1", lit=True)] * 4
    robot += [still(pose=1, head="head2", lit=True)] * SNARL
    robot += [still(pose=1, head="head1", lit=True)] * 4
    robot += [still(lit=True)] * (20 + HOLD)
    shown = lambda f: min(len(TEXT), max(0, (f - TEXT_AT) // TEXT_GAP + 1))
    out = [("card", None, 0)] * CARD
    out += [(shown(f), r, 0) for f, r in enumerate(robot)]
    k = shown(len(robot))
    for f in range(1, FADE + 1):
        out.append((k, still(lit=True), int(round(7 * f / FADE))))
    out += [(k, None, 7)] * 4
    return out


def palettes(robot):
    """8 fade levels x [BG 0, BG 1, sprite 0, sprite 1] x 16 colours (r, g, b 0..7)."""
    dis, _ = disclaimer_palette()
    base = [dis, card_palette(), robot.pal_lit, robot.pal_dark]
    return [[[tuple(max(0, v - L) for v in c) for c in pal] for pal in base] for L in range(8)]


# ============================================================================
# the blob: player code + data
# ============================================================================

# timeline ops
OP_END, OP_FIG, OP_BAT, OP_PAL, OP_SHOW, OP_BXR, OP_CR = range(7)


def encode(frs, cfg_ids):
    """frames -> timeline bytes."""
    out = bytearray()
    cur = {"screen": None, "fig": "?", "fade": None}
    stage = 0
    run = 0

    def flush():
        nonlocal run
        while run:
            n = min(run, 0xFFFF)
            out.extend(struct.pack("<BH", OP_SHOW, n))
            run -= n

    first = True
    for screen, figure, fade in frs:
        ops = bytearray()
        if screen != cur["screen"]:
            if screen == "card":
                ops += struct.pack("<BH", OP_BXR, 256)
            else:
                if cur["screen"] in (None, "card"):
                    ops += struct.pack("<BH", OP_BXR, 0)
                while stage < screen:
                    ops += bytes([OP_BAT, stage])        # patch stage -> stage + 1
                    stage += 1
            cur["screen"] = screen
        if figure != cur["fig"]:
            if figure is None:
                ops += bytes([OP_FIG, 0xFF, 0, 0, 0, 0])
            else:
                pose, head, lit, x, y = figure
                ops += struct.pack("<BBhh", OP_FIG, cfg_ids[(pose, head, lit)], x + 32, y + 64)
            cur["fig"] = figure
        if fade != cur["fade"]:
            ops += bytes([OP_PAL, fade])
            cur["fade"] = fade
        if first:
            ops += bytes([OP_CR, 0xC8])
            first = False
        if ops:
            flush()
            out += ops
        run += 1
    flush()
    out.append(OP_END)
    return bytes(out)


def _st(r, v):
    return [f".byte 0x03, {r}", f".byte 0x13, {v & 0xFF}", f".byte 0x23, {v >> 8 & 0xFF}"]


def _blk(op, src, dst, n):
    return [f".byte {op}, {src & 0xFF}, {src >> 8}, {dst & 0xFF}, {dst >> 8}, {n & 0xFF}, {n >> 8 & 0xFF}"]


TIA, TAI = 0xE3, 0xF3


def player(env):
    """The player at $4000. `env` gives the data labels (a second pass resolves them)."""
    L = [
        "JMP start",
        ".byte " + ", ".join(str(b) for b in MAGIC),
        # zero page ($2000-$201F; stage 2 clears it)
        "tl = 0x00", "ptr = 0x02", "fx = 0x04", "fy = 0x06", "cfg = 0x08", "cnt = 0x09",
        "ppal = 0x0B", "pbat = 0x0C", "pbxr = 0x0D", "bxr = 0x0E", "pcr = 0x10", "satb = 0x11",
        "left = 0x12", "n = 0x13", "tmp = 0x14",
        "start:",
        "PHP", "SEI", ".byte 0xD4",                       # CSH
        # --- the BIOS's VRAM into $78-$7F, its palette into palbuf
        *_st(1, 0), ".byte 0x03, 2",
        f"LDA #{SAVE_BANK}", "STA tmp",
        "snap: LDA tmp", "TAM #0x08",
        *_blk(TAI, 0x0002, 0x6000, 0x2000),
        "INC tmp", "LDA tmp", f"CMP #{SAVE_BANK + 8}", "BNE snap",
        "STZ a:0x0402", "STZ a:0x0403",
        *_blk(TAI, 0x0404, env.get("palbuf", 0), 1024),
        f"LDA #{BLOB_BANK + 1}", "TAM #0x08",
        # --- our VDC state, display off while we upload
        "JSR vwait",
        *_st(5, 0x0008), *_st(9, MWR_SPLASH), *_st(7, 256), *_st(8, 0), *_st(0x0F, 0x0010),
        # uploads: {src, vram, len}
        f"LDA #{env.get('uploads', 0) & 0xFF}", "STA ptr", f"LDA #{env.get('uploads', 0) >> 8}", "STA ptr+1",
        "up: CLY",
        "LDA (ptr),Y", "STA tsrc", "INY", "LDA (ptr),Y", "STA tsrc+1", "INY",
        "LDA (ptr),Y", "STA tmp", "INY", "LDA (ptr),Y", "STA tmp+1", "INY",
        "LDA (ptr),Y", "STA tlen", "INY", "LDA (ptr),Y", "STA tlen+1",
        "ORA tlen", "BEQ up_done",
        "JSR mawr", "JSR tia_vdc",
        "CLC", "LDA ptr", "ADC #6", "STA ptr", "BCC up", "INC ptr+1", "BRA up",
        "up_done:",
        # clear both SAT buffers (the first frames show no figure)
        f"LDA #{SAT_BUF[0] >> 8}", "STA satb",
        "LDA #0xFF", "STA cfg", "JSR sat", "JSR sat",
        "LDA #0xFF", "STA ppal", "STA pbat", "STZ pbxr", "STZ pcr",
        f"LDA #{env.get('timeline', 0) & 0xFF}", "STA tl", f"LDA #{env.get('timeline', 0) >> 8}", "STA tl+1",
        # --- the timeline
        "op: JSR getb",
        f"CMP #{OP_FIG}", "BNE op2",
        "JSR getb", "STA cfg", "JSR getb", "STA fx", "JSR getb", "STA fx+1",
        "JSR getb", "STA fy", "JSR getb", "STA fy+1", "BRA op",
        f"op2: CMP #{OP_BAT}", "BNE op3", "JSR getb", "STA pbat", "BRA op",
        f"op3: CMP #{OP_PAL}", "BNE op4", "JSR getb", "STA ppal", "BRA op",
        f"op4: CMP #{OP_BXR}", "BNE op5", "JSR getb", "STA bxr", "JSR getb", "STA bxr+1", "LDA #1", "STA pbxr", "BRA op",
        f"op5: CMP #{OP_CR}", "BNE op6", "JSR getb", "STA pcr", "BRA op",
        f"op6: CMP #{OP_SHOW}", "BNE done",
        "JSR getb", "STA cnt", "JSR getb", "STA cnt+1",
        "frame: JSR vwait",
        "JSR apply",
        "JSR sat",
        "LDA cnt", "BNE fr1", "DEC cnt+1", "fr1: DEC cnt",
        "LDA cnt", "ORA cnt+1", "BNE frame",
        "JMP op",
        # --- the end: everything back as the BIOS left it
        "done: JSR vwait",
        *_st(5, 0x0008), *_st(0x0F, HOOK["DCR"]),
        *_st(0, 0), ".byte 0x03, 2",
        f"LDA #{SAVE_BANK}", "STA tmp",
        "rest: LDA tmp", "TAM #0x08",
        *_blk(TIA, 0x6000, 0x0002, 0x2000),
        "INC tmp", "LDA tmp", f"CMP #{SAVE_BANK + 8}", "BNE rest",
        f"LDA #{BLOB_BANK + 1}", "TAM #0x08",
        # the palette back with entries 0-510 blank (511 kept): the BIOS's own would
        # bring its JUST A MOMENT screen back for the ~40 frames stage 2 takes to load,
        # after our fade. The game sets every colour it draws with: at the title the
        # palette, SAT and VRAM equal a pristine boot's (see the journal)
        *_blk(TAI, env.get("zero2", 0), env.get("palbuf", 0), 2 * PAL_BLANK),
        "JSR vwait",
        "STZ a:0x0402", "STZ a:0x0403",
        *_blk(TIA, env.get("palbuf", 0), 0x0404, 1024),
        *_st(9, HOOK["MWR"]), *_st(7, HOOK["BXR"]), *_st(8, HOOK["BYR"]),
        *_st(0x13, HOOK["DVSSR"]), *_st(5, HOOK["CR"]),
        "LDA a:0x0000",                                   # drop a pending VD
        "PLP", "RTS",
        # --- subroutines
        "getb: LDA (tl)", "INC tl", "BNE gb1", "INC tl+1", "gb1: RTS",
        "vwait: LDA a:0x0000", "AND #0x20", "BEQ vwait", "RTS",
        "mawr: .byte 0x03, 0", "LDA tmp", "STA a:0x0002", "LDA tmp+1", "STA a:0x0003", ".byte 0x03, 2", "RTS",
        "tia_vdc: .byte 0xE3", "tsrc: .word 0", ".word 0x0002", "tlen: .word 0", "RTS",
        "tia_vce: .byte 0xE3", "vsrc: .word 0", ".word 0x0404", ".word 64", "RTS",
        # pending palette / BAT patch / BXR / CR, inside vblank
        "apply: LDA ppal", "CMP #0xFF", "BEQ ap2",
        "TAX", f"LDA pal_lo,X", "STA vsrc", "LDA pal_hi,X", "STA vsrc+1",
        "STZ a:0x0402", "STZ a:0x0403", "JSR tia_vce",
        "CLC", "LDA vsrc", "ADC #64", "STA vsrc", "BCC ap1", "INC vsrc+1",
        "ap1: STZ a:0x0402", "LDA #1", "STA a:0x0403", "JSR tia_vce",
        "LDA #0xFF", "STA ppal",
        "ap2: LDA pbat", "CMP #0xFF", "BEQ ap4",
        "TAX", "LDA bat_lo,X", "STA ptr", "LDA bat_hi,X", "STA ptr+1",
        # runs: {vram, len bytes, words}; vram 0xFFFF ends
        "ap3: CLY", "LDA (ptr),Y", "STA tmp", "INY", "LDA (ptr),Y", "STA tmp+1",
        "CMP #0xFF", "BEQ ap3e",
        "INY", "LDA (ptr),Y", "STA tlen", "INY", "LDA (ptr),Y", "STA tlen+1",
        "CLC", "LDA ptr", "ADC #4", "STA ptr", "STA tsrc", "LDA ptr+1", "ADC #0", "STA ptr+1", "STA tsrc+1",
        "JSR mawr", "JSR tia_vdc",
        "CLC", "LDA ptr", "ADC tlen", "STA ptr", "LDA ptr+1", "ADC tlen+1", "STA ptr+1",
        "BRA ap3",
        "ap3e: LDA #0xFF", "STA pbat",
        "ap4: LDA pbxr", "BEQ ap5",
        ".byte 0x03, 7", "LDA bxr", "STA a:0x0002", "LDA bxr+1", "STA a:0x0003", "STZ pbxr",
        "ap5: LDA pcr", "BEQ ap6",
        ".byte 0x03, 5", "LDA pcr", "STA a:0x0002", "STZ a:0x0003", "STZ pcr",
        "ap6: RTS",
        # the figure's SAT into the other buffer, then DVSSR -> it (DMA'd at the next vblank)
        f"sat: LDA satb", f"EOR #{(SAT_BUF[0] ^ SAT_BUF[1]) >> 8}", "STA satb",
        "STZ tmp", "STA tmp+1", "JSR mawr",
        "LDA #64", "STA left",
        "LDA cfg", "CMP #0xFF", "BEQ fill",
        "TAX", "LDA cfg_lo,X", "STA ptr", "LDA cfg_hi,X", "STA ptr+1",
        "LDA (ptr)", "STA n",
        "INC ptr", "BNE ent", "INC ptr+1",
        "ent: CLY",
        "LDA (ptr),Y", "CLC", "ADC fy", "STA a:0x0002", "INY", "LDA (ptr),Y", "ADC fy+1", "STA a:0x0003", "INY",
        "LDA (ptr),Y", "CLC", "ADC fx", "STA a:0x0002", "INY", "LDA (ptr),Y", "ADC fx+1", "STA a:0x0003", "INY",
        "LDA (ptr),Y", "STA a:0x0002", "INY", "LDA (ptr),Y", "STA a:0x0003", "INY",
        "LDA (ptr),Y", "STA a:0x0002", "INY", "LDA (ptr),Y", "STA a:0x0003",
        "CLC", "LDA ptr", "ADC #8", "STA ptr", "BCC ent1", "INC ptr+1",
        "ent1: DEC left", "DEC n", "BNE ent",
        "fill: LDA left", "BEQ satd",
        "fill1: LDX #4", "fill2: STZ a:0x0002", "STZ a:0x0003", "DEX", "BNE fill2",   # the VDC steps on the high byte
        "DEC left", "BNE fill1",
        "satd: .byte 0x03, 0x13", "STZ a:0x0002", "LDA satb", "STA a:0x0003",
        "RTS",
    ]
    return L


class Blob:
    def __init__(self):
        self.robot = Robot()
        self.screens = Screens()
        self.frames = frames()
        keys = []
        for _, fig, _ in self.frames:
            if fig and fig[:3] not in keys:
                keys.append(fig[:3])
        self.cfg_keys = keys
        self.cfg_ids = {k: i for i, k in enumerate(keys)}
        self.configs = [self.robot.config(*k) for k in keys]
        self.pals = palettes(self.robot)
        self.timeline = encode(self.frames, self.cfg_ids)
        nt = len(self.screens.tiles)
        self.spr_base = (TILE_BASE + 16 * nt + 63) & ~63
        assert self.spr_base + 64 * len(self.robot.patterns) <= 0x10000 // 2
        self._check()
        self.build()

    def _check(self):
        """Sprites per line <= 16 cells, SAT <= 64, the URL clear of the figure."""
        for k, cfg in zip(self.cfg_keys, self.configs):
            assert len(cfg) <= 64, (k, len(cfg))
            for y in range(-64, H + 64):
                cells = sum(1 for dy, _, _, _ in cfg if dy <= y < dy + 16)
                assert cells <= 16, (k, y, cells)
        # every shown line clear of the figure in every frame (4 px)
        boxes = [(x, y, x + a.shape[1] - 1, y + a.shape[0] - 1) for a, x, y, _ in disclaimer_lines()]
        gap = 1 << 30
        for screen, figure, _ in self.frames:
            if screen == "card" or figure is None:
                continue
            fx0, fy0, fx1, fy1 = self.robot.box(self.robot.config(*figure[:3]), figure[3], figure[4])
            for i, (x0, y0, x1, y1) in enumerate(boxes[:screen]):
                clear = x1 + 4 < fx0 or y1 + 4 < fy0
                assert clear, f"line {i} ({x0},{y0})-({x1},{y1}) runs into the figure {figure} ({fx0},{fy0})-({fx1},{fy1})"
                if x1 >= fx0:
                    gap = min(gap, fy0 - y1 - 1)
        self.url_gap = gap

    def vram_uploads(self):
        """[(vram word address, [words])]"""
        tiles = [w for t in self.screens.tiles for w in tile_words(t)]
        sprites = [w for p in self.robot.patterns for w in sprite_words(p)]
        bat = [int(v) for v in self.screens.initial.flatten()]
        return [(0, bat), (TILE_BASE, tiles), (self.spr_base, sprites)]

    def data(self, base):
        """Data section at `base` -> (bytes, labels)."""
        out, lab = bytearray(), {}

        def put(name, b):
            lab[name] = base + len(out)
            out.extend(b)

        put("palbuf", bytes(1024))
        put("zero2", bytes(2))
        put("timeline", self.timeline)
        # palette sets: level L = 64 words (BG 0, BG 1, sprite 0, sprite 1)
        los, his = [], []
        for L, pals in enumerate(self.pals):
            words = [vce(c) for pal in pals for c in pal]
            put(f"pal{L}", struct.pack(f"<{len(words)}H", *words))
        lab["pal_lo"] = base + len(out); out.extend(bytes(lab[f"pal{L}"] & 0xFF for L in range(8)))
        lab["pal_hi"] = base + len(out); out.extend(bytes(lab[f"pal{L}"] >> 8 for L in range(8)))
        # figure configurations: count, then {dy+, dx+, pattern word, attr word} (y/x added to fy/fx)
        for i, cfg in enumerate(self.configs):
            b = bytearray([len(cfg)])
            for dy, dx, p, pal in cfg:
                b += struct.pack("<hhHH", dy, dx, (self.spr_base + 64 * p) >> 5, 0x80 | pal)
            put(f"cfg{i}", b)
        n = max(1, len(self.configs))
        lab["cfg_lo"] = base + len(out); out.extend(bytes(lab.get(f"cfg{i}", 0) & 0xFF for i in range(n)))
        lab["cfg_hi"] = base + len(out); out.extend(bytes(lab.get(f"cfg{i}", 0) >> 8 for i in range(n)))
        # BAT patches
        for k, runs in enumerate(self.screens.patches):
            b = bytearray()
            for addr, words in runs:
                b += struct.pack("<HH", addr, 2 * len(words)) + struct.pack(f"<{len(words)}H", *words)
            b += b"\xff\xff"
            put(f"bat{k}", b)
        m = len(self.screens.patches)
        lab["bat_lo"] = base + len(out); out.extend(bytes(lab[f"bat{k}"] & 0xFF for k in range(m)))
        lab["bat_hi"] = base + len(out); out.extend(bytes(lab[f"bat{k}"] >> 8 for k in range(m)))
        # uploads: the list, then the words (split below 8 KB a TIA)
        ups = self.vram_uploads()
        chunks = []
        for vaddr, words in ups:
            for i in range(0, len(words), 0x1000):
                chunks.append((vaddr + i, words[i:i + 0x1000]))
        lab["uploads"] = base + len(out)
        list_at = len(out)
        out.extend(bytes(6 * len(chunks) + 6))
        for j, (vaddr, words) in enumerate(chunks):
            src = base + len(out)
            out.extend(struct.pack(f"<{len(words)}H", *words))
            out[list_at + 6 * j:list_at + 6 * j + 6] = struct.pack("<HHH", src, vaddr, 2 * len(words))
        return bytes(out), lab

    def build(self):
        names = ["palbuf", "zero2", "timeline", "uploads", "pal_lo", "pal_hi", "cfg_lo", "cfg_hi", "bat_lo", "bat_hi"]
        env = {k: 0x8000 for k in names}
        for _ in range(4):                                # data labels move with the code size
            code, _ = asm6280.assemble(chr(10).join(player(env)), ORG, env)
            data, lab = self.data(ORG + len(code))
            if all(env[k] == lab[k] for k in names):
                break
            env = {k: lab[k] for k in names}
        else:
            raise SystemExit("the splash's data labels did not settle")
        self.code, self.labels = code, lab
        self.blob = code + data
        if len(self.blob) > BLOB_MAX:
            raise SystemExit(f"the splash blob is {len(self.blob)} B, over {BLOB_MAX} ($70-$74)")
        self.sectors = (len(self.blob) + P.DATA - 1) // P.DATA


def loader(rec, sectors):
    """Stage 1's side at LOADER: read the blob into $70-$74, run it, zero $70-$7F,
    put MPR2-7 back; replaces (and ends with) the hooked LDA #0 / TAM #$80."""
    def text(zero2):
        return chr(10).join([
            "TMA #0x04", "STA sv", "TMA #0x08", "STA sv+1", "TMA #0x10", "STA sv+2", "TMA #0x20", "STA sv+3",
            "TMA #0x40", "STA sv+4",
            f"rd: LDA #{rec >> 16 & 0xFF}", "STA 0xFC",            # _cl _ch _dl = the sector
            f"LDA #{rec >> 8 & 0xFF}", "STA 0xFD",
            f"LDA #{rec & 0xFF}", "STA 0xFE",
            "LDA #2", "STA 0xFF",                                  # _dh: through MPR2
            f"LDA #{BLOB_BANK}", "STA 0xFA", "STZ 0xFB",           # _bl: the first bank
            f"LDA #{sectors}", "STA 0xF8", "STZ 0xF9",             # _al: sectors
            "JSR 0xE009",                                           # CD_READ
            "BNE rd",
            f"LDA #{BLOB_BANK}", "TAM #0x04", "INC A", "TAM #0x08", "INC A", "TAM #0x10", "INC A", "TAM #0x20",
            "INC A", "TAM #0x40",
            f"JSR {ORG}",
            f"LDA #{BLOB_BANK}", "STA bk",
            "z: LDA bk", "TAM #0x08",
            *_blk(TAI, zero2, 0x6000, 0x2000),
            "INC bk", "LDA bk", f"CMP #{SAVE_BANK + 8}", "BNE z",
            "LDA sv", "TAM #0x04", "LDA sv+1", "TAM #0x08", "LDA sv+2", "TAM #0x10", "LDA sv+3", "TAM #0x20",
            "LDA sv+4", "TAM #0x40",
            "LDA #0", "TAM #0x80",
            "RTS",
            "sv: .res 5", "bk: .res 1", "zero2: .word 0",
        ])
    _, lab = asm6280.assemble(text(0), LOADER)
    code, lab2 = asm6280.assemble(text(lab["zero2"]), LOADER)
    assert lab2["zero2"] == lab["zero2"] and LOADER + len(code) <= LOADER_END
    return code


# ============================================================================
# the model: what the VDC shows, from the blob's own data
# ============================================================================

class Model:
    def __init__(self, B):
        self.B = B
        self.vram = np.zeros(0x8000, np.uint16)
        for vaddr, words in B.vram_uploads():
            self.vram[vaddr:vaddr + len(words)] = words
        self.bxr = 256
        self.pal = None
        self.sat_live = []        # the SAT the VDC shows (DMA'd at vblank)
        self.sat_next = []

    def play(self):
        """Yield one RGB frame per displayed frame, interpreting the timeline bytes."""
        B, t, i = self.B, self.B.timeline, 0
        cfg, fx, fy = 0xFF, 0, 0
        pend = {}
        while True:
            op = t[i]; i += 1
            if op == OP_END:
                return
            if op == OP_FIG:
                cfg, fx, fy = t[i], struct.unpack_from("<h", t, i + 1)[0], struct.unpack_from("<h", t, i + 3)[0]; i += 5
            elif op == OP_BAT:
                pend["bat"] = t[i]; i += 1
            elif op == OP_PAL:
                pend["pal"] = t[i]; i += 1
            elif op == OP_BXR:
                pend["bxr"] = struct.unpack_from("<H", t, i)[0]; i += 2
            elif op == OP_CR:
                i += 1
            elif op == OP_SHOW:
                n = struct.unpack_from("<H", t, i)[0]; i += 2
                for _ in range(n):
                    # vblank: the DMA of last frame's SAT, then the pending writes
                    self.sat_live = self.sat_next
                    if "pal" in pend:
                        self.pal = B.pals[pend.pop("pal")]
                    if "bat" in pend:
                        for addr, words in B.screens.patches[pend.pop("bat")]:
                            self.vram[addr:addr + len(words)] = words
                    if "bxr" in pend:
                        self.bxr = pend.pop("bxr")
                    self.sat_next = [] if cfg == 0xFF else [(fy + dy - 64, fx + dx - 32, p, pal) for dy, dx, p, pal in B.configs[cfg]]
                    yield self.render()

    def render(self):
        B = self.B
        rgb = lambda c: rgb9(c)
        im = np.zeros((H, W, 3), np.uint8)
        tiles = {}
        for r in range(H // 8):
            for c in range(W // 8):
                col = (c + self.bxr // 8) % BAT_W
                w = int(self.vram[r * BAT_W + col])
                pal, ti = w >> 12, w & 0xFFF
                t = B.screens.tiles[ti - TILE_BASE // 16]
                cols = np.array([rgb(self.pal[pal][v] if v else self.pal[0][0]) for v in range(16)], np.uint8)
                im[r * 8:r * 8 + 8, c * 8:c * 8 + 8] = cols[t]
        for y, x, p, pal in reversed(self.sat_live):       # entry 0 in front
            pat = B.robot.patterns[p]
            cols = np.array([rgb(self.pal[2 + pal][v]) for v in range(16)], np.uint8)
            for yy in range(16):
                sy = y + yy
                if not 0 <= sy < H:
                    continue
                for xx in range(16):
                    sx, v = x + xx, pat[yy, xx]
                    if v and 0 <= sx < W:
                        im[sy, sx] = cols[v]
        return Image.fromarray(im)


# ============================================================================

def preview():
    B = Blob()
    shots, marks = [], {}
    n_card = CARD
    snarl_at = CARD + WALK + SETTLE + 21 + (JAW_AT - 21) + 4 + SNARL // 2
    text_at = len(B.frames) - FADE - 4 - 10
    out = os.path.join(WORK, "pce")
    for f, im in enumerate(Model(B).play()):
        if f % 2 == 0:
            shots.append(im)
        if f == n_card // 2:
            im.save(os.path.join(out, "splash_card.png"))
        if f == snarl_at:
            im.save(os.path.join(out, "splash_snarl.png"))
        if f == text_at:
            im.save(os.path.join(out, "splash_text.png"))
        if f in (CARD + 75, CARD + 120):
            im.save(os.path.join(out, f"splash_walk{f - CARD}.png"))
    shots[0].save(os.path.join(out, "splash_preview.gif"), save_all=True, append_images=shots[1:], duration=33, loop=0)
    print(f"{len(B.frames)} frames ({len(B.frames) / 59.94:.1f} s: card {CARD}, splash {len(B.frames) - CARD}); "
          f"blob {len(B.blob)} B = {B.sectors} sectors (code {len(B.code)} B, timeline {len(B.timeline)} B); "
          f"{len(B.screens.tiles)} tiles, {len(B.robot.patterns)} sprite patterns at {B.spr_base:#06x}, "
          f"{len(B.configs)} figure configs ({max(len(c) for c in B.configs)} sprites max), "
          f"robot colours {len(B.robot.colours)}; URL {B.url_gap} px above the figure\n"
          f"  work/pce/splash_preview.gif, splash_card.png, splash_snarl.png, splash_text.png")
    return B


def blob_rec(sectors):
    return (P.T3 - P.T2) + P.RESERVE - POSTGAP - sectors


def apply(out_path=P.OUT):
    B = Blob()
    img = P.Image(out_path, P.T3 + P.RESERVE)
    rec = blob_rec(B.sectors)
    at = (P.T2 + rec) * P.DATA
    old = bytes(img.data[at:at + B.sectors * P.DATA])
    if any(old) and old[3:3 + len(MAGIC)] != MAGIC:
        raise SystemExit(f"rec {rec} x{B.sectors} is not blank: something else was placed there")
    # nothing of ours past or before the blob either (a longer blob earlier: blank it)
    s1 = (P.T2 + STAGE1_SECTOR) * P.DATA
    hook = bytes(img.data[s1 + HOOK_AT - 0x3000:s1 + HOOK_AT - 0x3000 + 4])
    jsr = bytes([0x20, LOADER & 0xFF, LOADER >> 8, 0xEA])
    if hook not in (HOOK_ORIG, jsr):
        raise SystemExit(f"stage 1 at ${HOOK_AT:04x} holds {hook.hex()}, not the pristine LDA #0 / TAM #$80")
    ld = loader(rec, B.sectors)
    tail = bytes(img.data[s1 + LOADER - 0x3000:s1 + LOADER_END - 0x3000])
    if hook == HOOK_ORIG and any(tail):
        raise SystemExit(f"stage 1's tail ${LOADER:04x}-${LOADER_END:04x} is not blank")
    img.write(at, B.blob + bytes(B.sectors * P.DATA - len(B.blob)))
    img.write(s1 + LOADER - 0x3000, ld + bytes(LOADER_END - LOADER - len(ld)))
    img.write(s1 + HOOK_AT - 0x3000, jsr)
    n = img.flush()
    print(f"splash: blob {len(B.blob)} B at rec {rec} x{B.sectors} (-> ${BLOB_BANK:02x}), loader {len(ld)} B at "
          f"${LOADER:04x}, hook at ${HOOK_AT:04x}; {len(B.frames)} frames ({len(B.frames) / 59.94:.1f} s); "
          f"{n} sectors written")


if __name__ == "__main__":
    {"preview": preview, "apply": apply}[sys.argv[1]]()
