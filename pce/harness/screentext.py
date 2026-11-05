"""Read the subtitle text back off the SCREEN and hold it against the page it should show.

The buffer check (subtext.py) proves the stub laid the right codes out; what the player
sees also depends on the tiles the renderer wrote, the BAT that maps them and the faces
that share their regions - a page can be right in RAM and garbled on screen. Every
letter is a 6x12 glyph of the module font (pcepair.modfont, X11 6x13 trimmed), so the
screen can be read exactly: find the first row's origin by correlating its expected
ink with the lit pixels of the band, then match every 6-pixel cell of every row
against the font. A row may be shorter on screen than expected (the words type on, a
line cut short) but every lit cell must be the expected letter, and a row may only be
cut where the rows after it are still blank.

    python pce/harness/screentext.py IMG.png "row one|row two"     # judge one capture
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'pce/tools', 'pce/harness')]
import numpy as np
import pcepair

PITCH = 16                      # the renderer's rows, 16 lines apart
BAND = (136, 236)               # the text window's lines on the screen
_G = {}


def glyphs():
    if not _G:
        font = pcepair.modfont()
        for i, ch in enumerate(pcepair.GLYPHS):
            g = np.zeros((12, 6), bool)
            for r in range(12):
                v = font[i * 12 + r]
                for x in range(6):
                    g[r, x] = bool(v & (0x20 >> x))
            _G[ch] = g
    return _G


def lit(img):
    a = np.asarray(img.convert("RGB")).astype(int)
    return a.max(2) >= 140


def render(text):
    g = glyphs()
    out = np.zeros((12, 6 * len(text)), bool)
    for i, ch in enumerate(text):
        out[:, 6 * i:6 * i + 6] = g.get(ch, g["?"])
    return out


def ocr_cell(cell):
    """The letter a 12x6 cell shows: ' ' blank, the best glyph within 4 pixels, else '?'."""
    if not cell.any():
        return " "
    best, bd = "?", 99
    for ch, g in glyphs().items():
        d = int((g != cell).sum())
        if d < bd:
            best, bd = ch, d
    return best if bd <= 4 else "?"


def locate(mask, text, band=BAND):
    """(x0, y0, score) of the row `text` in the band: the window whose lit pixels best cover
    the row's ink (the first 8 letters - the ones typed on first)."""
    lead = len(text) - len(text.lstrip())
    head = text.lstrip()[:8].rstrip()
    if not head:
        return None
    k = render(head).astype(np.int32)
    h, w = k.shape
    y0, y1 = band
    sub = mask[y0:y1].astype(np.int32)
    if sub.shape[1] < w:
        return None
    from numpy.lib.stride_tricks import sliding_window_view
    win = sliding_window_view(sub, (h, w))                  # (Y, X, h, w)
    hits = np.einsum("yxhw,hw->yx", win, k)
    extra = win.sum((2, 3)) - hits
    score = hits - 2 * extra
    yy, xx = np.unravel_index(int(score.argmax()), score.shape)
    ink = int(k.sum())
    return xx - 6 * lead, y0 + yy, (int(hits[yy, xx]) - int(extra[yy, xx])) / max(1, ink)


def read_row(mask, x, y, cells):
    s = ""
    for i in range(cells):
        if y + 12 > mask.shape[0] or x + 6 * i + 6 > mask.shape[1] or x + 6 * i < 0:
            break
        s += ocr_cell(mask[y:y + 12, x + 6 * i:x + 6 * i + 6])
    return s.rstrip()


def judge(img, rows):
    """(verdict, seen rows): 'ok', 'GARBLED ON SCREEN' (a lit cell that is not the expected
    letter, or text after a row that stopped short), 'NOT ON SCREEN' (the first row not
    found), or 'unjudged' (nothing to read). Each row is found on its own line (the opening
    centres every row), else at the first row's column."""
    rows = [r.rstrip() for r in rows]
    first = next((i for i, r in enumerate(rows) if r.strip()), None)
    if first is None:
        return "unjudged", []
    mask = lit(img)
    at = locate(mask, rows[first])
    if at is None:
        return "unjudged", []
    x0, y0, score = at
    y0 -= PITCH * first
    if score < 0.5:
        return "NOT ON SCREEN", []
    seen, short = [], False
    for r, want in enumerate(rows):
        y = y0 + PITCH * r
        x = x0
        if want.strip() and r != first:
            got = locate(mask, want, (max(0, y - 1), min(mask.shape[0], y + 13)))
            if got is not None and got[2] >= 0.5:
                x = got[0]
        line = read_row(mask, x, y, max(len(want), 1) + 2)
        seen.append(line)
        if short and line.strip():
            return "GARBLED ON SCREEN", seen
        for i, ch in enumerate(line):
            want_ch = want[i] if i < len(want) else " "
            if ch != want_ch:
                if ch == " " and not line[i:].strip():      # typed on this far
                    break
                return "GARBLED ON SCREEN", seen
        if len(line) < len(want):
            short = True
    return "ok", seen


def main():
    from PIL import Image
    img = Image.open(sys.argv[1])
    print(judge(img, sys.argv[2].split("|")))


if __name__ == "__main__":
    main()
