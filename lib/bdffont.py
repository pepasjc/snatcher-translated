"""Bitmap fonts from BDF files, drawn as numpy masks.

The English text drawn into the game's graphics - the pair glyphs, the
memo pages, the disclaimer, the credit roll, the intro FMV captions and
the opening's JUNKER HQ caption - uses Tamzen (lib/fonts/, licence in
lib/fonts/LICENSE-Tamzen.txt): a bitmap face, so every pixel is the
designer's and nothing depends on a TrueType rasteriser or on the fonts a
Windows install happens to carry.

    f = bdffont.load("Tamzen6x12b")      # cached per name
    m = f.render("Hello")                 # bool (ascent+descent) x (6*len)
    m = f.render("Hello", proportional=True, gap=1, space=3)

Rows of a mask run from the top of the font's cell (FONT_ASCENT rows above
the baseline, FONT_DESCENT below), so `f.ascent` is the baseline row.
"""
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")

# The faces in use.
DIALOGUE = "6x13"             # pair glyphs, pages, disclaimer, FMV, caption line 1:
                              # X11 misc-fixed 6x13 (public domain), 0.9.2 - caps 9 px where
                              # Tamzen 6x12's were 7 ("too small"); the bold 6x13B looked worse
CAPTION = "Tamzen8x16b"       # the opening's JUNKER HQ
ROLL = "6x13"                 # the credit roll (6x13B bold overflowed its atlas; regular fits)

# Rows cut off the top of a face so it fits the game's 12-row cells: 6x13's
# row 0 is blank for every printable character, and without it the letters
# stand on row 9 with descenders on 10-11, where MS Gothic 12 had them.
TRIM_TOP = {"6x13B": 1, "6x13": 1}


class BDF:
    def __init__(self, path, trim_top=0):
        self.glyphs, cur, bits = {}, None, None
        self.ascent = self.descent = None
        for line in open(path, encoding="latin-1"):
            p = line.split()
            if not p:
                continue
            if p[0] == "FONT_ASCENT":
                self.ascent = int(p[1])
            elif p[0] == "FONT_DESCENT":
                self.descent = int(p[1])
            elif p[0] == "ENCODING":
                cur = {"enc": int(p[1])}
            elif p[0] == "BBX" and cur is not None:
                cur["bbx"] = list(map(int, p[1:5]))
            elif p[0] == "DWIDTH" and cur is not None:
                cur["dw"] = int(p[1])
            elif p[0] == "BITMAP":
                bits = []
            elif p[0] == "ENDCHAR":
                cur["bits"] = bits
                self.glyphs[cur["enc"]] = cur
                cur = bits = None
            elif bits is not None:
                bits.append((int(p[0], 16), len(p[0]) * 4))
        self.ascent -= trim_top
        self.height = self.ascent + self.descent
        self.advance = self.glyphs[ord("M")]["dw"]
        self._cache = {}

    def glyph(self, ch):
        """One character as a bool array, height x advance (a copy)."""
        if ch not in self._cache:
            g = self.glyphs.get(ord(ch))
            if g is None:
                raise ValueError(f"{ch!r} is not in the font")
            w, h, xo, yo = g["bbx"]
            a = np.zeros((self.height, g["dw"]), bool)
            top = self.ascent - (h + yo)
            for y, (row, nbits) in enumerate(g["bits"]):
                for x in range(w):
                    if row >> (nbits - 1 - x) & 1:
                        X, Y = xo + x, top + y
                        if 0 <= X < a.shape[1] and 0 <= Y < a.shape[0]:
                            a[Y, X] = True
            self._cache[ch] = a
        return self._cache[ch].copy()

    def render(self, text, proportional=False, gap=1, space=3, spacing=0):
        """A run of text as a bool mask, `height` rows.

        Monospace: every character takes the font's advance plus `spacing`.
        Proportional: each glyph is cropped to its ink columns and followed by
        `gap` blank columns; a space is `space` columns. Trailing blank
        columns are kept (the caller crops if it wants to)."""
        cols = []
        for ch in text:
            g = self.glyph(ch)
            if proportional:
                xs = np.nonzero(g.any(0))[0]
                if ch == " " or not len(xs):
                    cols.append(np.zeros((self.height, space), bool))
                    continue
                g = g[:, xs.min():xs.max() + 1]
                cols.append(g)
                cols.append(np.zeros((self.height, gap), bool))
            else:
                cols.append(g)
                if spacing:
                    cols.append(np.zeros((self.height, spacing), bool))
        if not cols:
            return np.zeros((self.height, 0), bool)
        return np.hstack(cols)

    def width(self, text, **kw):
        return self.render(text, **kw).shape[1]


_loaded = {}


def load(name=DIALOGUE):
    if name not in _loaded:
        _loaded[name] = BDF(os.path.join(FONT_DIR, name + ".bdf"), TRIM_TOP.get(name, 0))
    return _loaded[name]


def crop(mask):
    """Drop blank columns at both ends."""
    xs = np.nonzero(mask.any(0))[0]
    return mask[:, xs.min():xs.max() + 1] if len(xs) else mask[:, :0]
