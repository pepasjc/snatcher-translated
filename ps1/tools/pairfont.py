"""Dual-tile ASCII system for Snatcher PS1.

Each sacrificed kanji glyph slot (12x12, 18B, SLPS_001.54 @ 0x4cb80) is
redrawn as TWO halfwidth Latin letters. English then costs 2 bytes per
2 letters — same density as Japanese, so in-place string patching works.

Pair table persisted in work/pair_table.json (pair -> [slot, code]).
"""
import json, os
from PIL import Image, ImageFont, ImageDraw
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

from textcodec import char_to_code   # lib/, on the path from the header above

FONT_BASE = 0x4cb80
# Glyph data ends at file 0x5c3b4; past that the executable holds an engine
# pointer table, so slot 3529 is the last one that is safe to redraw. Writing
# beyond it hung the game after New Game on every accurate emulator.
MAX_SLOT = 3529
# Slots whose kanji no string in any bank references any more, repurposed as
# code/data by the subtitle loader hook (ps1/subs/subs_cue.py HOOK_CODE and
# HOOK_TAB). Never draw glyphs there.
RESERVED = [(1012, 1026), (1107, 1117), (1260, 1264), (1287, 1294), (1308, 1314), (1329, 1335), (1337, 1340), (1357, 1362), (1550, 1554), (1564, 1570), (2076, 2086), (3004, 3012)]  # 1550-1570: repoint.py, the typed-input field stubs (#35); 2076-2086 subs_cue LONGS_TAB, 3004-3012 LONGS_CODE (the second blob's read)
FREE = os.path.join(ROOT, "work/free_slots.json")
TABLE = os.path.join(ROOT, "work/pair_table.json")

import bdffont   # lib/: Tamzen 6x12 bold (lib/fonts/), since 0.9.2

# Tamzen's letters stand on row 8 of its 12-row cell (descenders 9-10) and
# its row 11 is blank for every character, so the glyph goes down one row:
# letters on row 9, descenders on 10-11, where MS Gothic 12 (the face until
# 0.9.2) had them, so every box, plate and row the game draws the pairs in
# sees the same vertical placement.
PAIR_DY = 1 if bdffont.DIALOGUE.startswith("Tamzen") else 0   # 6x13 (trimmed) is already there

_font = None
def _ref_font():
    global _font
    if _font is None:
        _font = bdffont.load(bdffont.DIALOGUE)
    return _font

def render_pair(pair):
    """Render 2 halfwidth ASCII chars into a 12x12 1bpp bitmap (18 bytes)."""
    f = _ref_font()
    m = f.render(pair)                      # 12 rows x 12 columns
    rows = []
    for y in range(12):
        v = 0
        sy = y - PAIR_DY
        if 0 <= sy < m.shape[0]:
            for x in range(12):
                if m[sy, x]:
                    v |= 0x800 >> x
        rows.append(v)
    out = bytearray()
    for i in range(0, 12, 2):
        w = (rows[i] << 12) | rows[i+1]
        out += bytes([(w >> 16) & 0xFF, (w >> 8) & 0xFF, w & 0xFF])
    return bytes(out)

class PairFont:
    def __init__(self):
        self.table = json.load(open(TABLE)) if os.path.exists(TABLE) else {}
        taken = {c for _, c in self.table.values()}
        # free list may already exclude assigned codes; filter again to be safe
        self.free = [(s, c) for s, c in json.load(open(FREE)) if c not in taken]
        self.next = 0

    def capacity(self):
        return len(self.table) + len(self.free)

    def code_for(self, pair):
        if pair not in self.table:
            if self.next >= len(self.free):
                raise RuntimeError("out of free glyph slots")
            slot, code = self.free[self.next]
            self.table[pair] = [slot, code]
            self.next += 1
        return self.table[pair][1]

    def encode(self, s):
        """English (+ passthrough fullwidth like ￥) -> game bytes."""
        out = bytearray()
        i = 0
        buf = ""
        def flush():
            nonlocal buf
            if len(buf) % 2:
                buf += " "
            for k in range(0, len(buf), 2):
                out.extend(self.encode_pair_or_fallback(buf[k:k+2]))
            buf = ""
        for ch in s:
            if ord(ch) < 0x80:
                buf += ch
            else:
                flush()
                c = char_to_code(ch)
                if c is None:
                    raise ValueError(f"cannot encode {ch!r}")
                out.extend([c >> 8, c & 0xFF])
        flush()
        return bytes(out)

    # ASCII whose U+FF00 form the codec lacks: the hyphen's fullwidth `－` is
    # not in JIS X 0208 (row 1 has `‐` 1-30 and the minus `−` 1-61) and fell
    # back to `？` (Randam's spelled name on the Saturn, 2026-09-16)
    FALLBACK_CHARS = {" ": "　", "-": "‐", "~": "〜"}

    def encode_pair_or_fallback(self, pair):
        """Pair code, or two fullwidth chars if the glyph pool is exhausted
        (costs 4 bytes instead of 2 — only for rare pairs)."""
        # (the path insert and the textcodec import used to sit here, once per
        # PAIR: a scene of the review server grew sys.path by 84,000 entries and
        # every import after it walked the lot - the page went from 4 s to a
        # minute and the phone gave up on it, 2026-09-22)
        try:
            c = self.code_for(pair)
            return bytes([c >> 8, c & 0xFF])
        except RuntimeError:
            out = bytearray()
            for ch in pair:
                fw = self.FALLBACK_CHARS.get(ch) or chr(0xFEE0 + ord(ch))
                c = char_to_code(fw)
                if c is None:                      # no fullwidth form in JIS
                    c = char_to_code("？")
                out.extend([c >> 8, c & 0xFF])
            return bytes(out)

    def write_glyphs(self, exe):
        """Write all table pair glyphs into exec image (bytearray)."""
        for pair, (slot, code) in self.table.items():
            if slot > MAX_SLOT:
                raise SystemExit(f"pair {pair!r} sits at slot {slot}, past the "
                                 f"end of the glyph data (max {MAX_SLOT}) - "
                                 "re-run ps1/tools/rebuild_pairs.py")
            if any(a <= slot <= b for a, b in RESERVED):
                raise SystemExit(f"pair {pair!r} sits at slot {slot}, which "
                                 "holds the subtitle loader hook (subs_cue.py "
                                 "HOOK_CODE/HOOK_TAB) - re-run rebuild_pairs.py "
                                 "with those slots excluded")
            off = FONT_BASE + slot * 18
            exe[off:off+18] = render_pair(pair)

    def save(self):
        json.dump(self.table, open(TABLE, "w"))
