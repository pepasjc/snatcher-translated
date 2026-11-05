# -*- coding: utf-8 -*-
"""Catch a misplaced or empty dialogue panel in a screenshot.

    python ps1/harness/panel_check.py work/tri_off work/tri_cold      # compare runs
    python ps1/harness/panel_check.py shot.png

The whole of today went into a defect the subtitle validator could not see:
it scores the TEXT rows, so a panel drawn 88 pixels too high - over the scene
picture instead of under it - passes every row it can find and reports clean.
Luiz caught it by eye across four play-tests.

The panel is unmistakable in pixels: a gold frame, ~1550 px of it, spanning
almost the full width. Where it sits is the whole question.

    good  rows 152-227   under the picture
    bad   rows  64-139   riding up over the picture

So: find the gold frame, complain if its top is above TOP_MIN, and complain
if a frame is up with no text ink inside it (the floating empty box that a
blank draw leaves behind).
"""
import glob, os, sys

import numpy as np
from PIL import Image

TOP_MIN = 140          # a panel starting above this is riding up
MIN_GOLD = 400         # fewer gold pixels than this is not a panel
MIN_INK = 40           # text pixels inside the panel
EMPTY_RUN = 3          # consecutive empty frames before it counts.
                       # A box is legitimately empty for a frame or
                       # two while it opens - the verified-good build
                       # shows that in 4 of 434 frames. Riding up needs
                       # no such tolerance: 21 hits in the bad build,
                       # none in either good one.


def gold_mask(a):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (r > 150) & (g > 110) & (b < 110) & (r > b + 60) & (g > b + 40)


FILL_MAX = 32          # median brightness of the box's dark fill, at most
PANEL_H = (64, 80)      # the frame's two edges: 152..223 = 71 rows


def edge_groups(m, w):
    """Rows gold across most of the width, merged into edges (the frame's
    edge is two such rows, y and y+2)."""
    rows = [y for y, c in enumerate(m.sum(axis=1)) if c > w * 0.7]
    groups = []
    for y in rows:
        if groups and y - groups[-1][1] <= 3:
            groups[-1][1] = y
        else:
            groups.append([y, y])
    return groups


def find_panel(img):
    """(top, bottom, left, right) of the dialogue frame, or None.

    Found by its solid horizontal edges - rows that are gold across most of
    the width. A gold bounding box alone is not enough: the ruins' yellow SKY
    is gold-coloured and was reported as a panel riding up to row 20. The sky
    has no full-width row; the frame has four (two per edge).

    The frame is the LOWEST pair of edges PANEL_H apart: B0C0's disk reader
    draws a gold monitor bezel with a full-width top edge at row 21, and
    taking the first edge row as the panel's top reported 50 frames of a
    panel 'riding up' that sat where it should (2026-11-05). A single edge
    low on the screen is a box whose bottom runs off it (the verb menu
    outside Gillian's home, 184..239): its top is real, its bottom is the
    screen's.
    """
    a = np.asarray(img.convert('RGB')).astype(int)
    m = gold_mask(a)
    if m.sum() < MIN_GOLD:
        return None
    h, w = a.shape[0], a.shape[1]
    groups = edge_groups(m, w)
    pairs = [(t[0], b[1]) for i, t in enumerate(groups) for b in groups[i + 1:]
             if PANEL_H[0] <= b[1] - t[0] <= PANEL_H[1]]
    if pairs:
        top, bottom = max(pairs)
    elif len(groups) == 1 and groups[0][1] - groups[0][0] <= 3 and groups[0][0] >= TOP_MIN and h - groups[0][0] >= 30:
        top, bottom = groups[0][0], h - 1
    else:
        return None
    cols = np.nonzero(m[top:bottom + 1].sum(axis=0))[0]
    left, right = int(cols.min()), int(cols.max())
    # the dialogue box is filled dark (median ~24 of 255): gold stripes in a
    # room's own frame art enclose a grey grille (median 40-48) - B120's
    # bathroom and B1A0's shower read as an empty panel that way
    inner = a[top + 6:bottom - 5, left + 6:right - 5]
    if inner.size and np.median(inner.max(axis=2)) > FILL_MAX:
        return None
    return top, bottom, left, right


def ink_inside(img, box):
    """Bright text pixels within the panel interior."""
    a = np.asarray(img.convert('RGB')).astype(int)
    t, b, l, r = box
    # inside the frame's inner border and left of the wait cursor (x 232+)
    inner = a[t + 8:b - 6, l + 8:min(r - 5, 228)]
    if inner.size == 0:
        return 0
    # any colour of text: the JP colours names and terms (the Chief's red
    # "JUNK" read as an empty panel when only white counted)
    bright = (inner.max(axis=2) > 150) & ~gold_mask(inner)
    return int(bright.sum())


def life_bar(img, box):
    """The shootouts' LIFE gauge sits in the same gold frame with no text
    in it: a band of green across the interior."""
    a = np.asarray(img.convert('RGB')).astype(int)
    t, b, l, r = box
    inner = a[t + 6:b - 5, l + 6:r - 5]
    if inner.size == 0:
        return False
    green = (inner[:, :, 1] > 150) & (inner[:, :, 0] < 170) & (inner[:, :, 2] < 120)
    return green.mean() > 0.15


def check(path, top_min=TOP_MIN):
    """[] if the frame looks right, else a list of complaints."""
    img = Image.open(path)
    box = find_panel(img)
    if box is None:
        return []                                   # no panel on screen
    problems = []
    if box[0] < top_min:
        problems.append(f'panel rides up: top row {box[0]} < {top_min}')
    if ink_inside(img, box) < MIN_INK and not life_bar(img, box):
        problems.append('panel is empty: no text inside the frame')
    return problems


def scan(paths):
    """Walk frames in order; report offsets at once, empties only if sustained."""
    out, run, run_from = [], 0, None
    for p in paths:
        problems = check(p)
        offset = [w for w in problems if 'rides up' in w]
        empty = [w for w in problems if 'empty' in w]
        for w in offset:
            out.append((p, w))
        if empty:
            run += 1
            run_from = run_from or p
            if run == EMPTY_RUN:
                out.append((run_from, f'panel empty for {EMPTY_RUN}+ frames'))
        else:
            run, run_from = 0, None
    return out


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    bad = total = 0
    for arg in args:
        shots = ([arg] if os.path.isfile(arg)
                 else sorted(glob.glob(os.path.join(arg, '*.png'))))
        total += len(shots)
        found = scan(shots)
        hits = len(found)
        bad += hits
        for p, why in found:
            print(f'{os.path.basename(arg)}/{os.path.basename(p)}: {why}')
        if not os.path.isfile(arg):
            print(f'{arg}: {hits} problem(s) over {len(shots)} frames')
    print(f'\n{bad} problem(s) in {total} frame(s)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
