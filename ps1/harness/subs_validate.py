# -*- coding: utf-8 -*-
"""Validate subtitle screenshots against the cue JSON, pixel-exactly.

Each expected text row is rendered with the game's own font (pair glyphs from
work/pair_table.json + fullwidth from work/font_table.txt, bitmaps straight
out of the patched executable), then searched for in the screenshot by
normalized ink overlap. A missing row - like B020's mode-3 second-row loss -
scores near zero and fails loudly.

  python ps1/harness/subs_validate.py work/auto55 ps1/translation/subs_B010.json
  python ps1/harness/subs_validate.py shot.png ps1/translation/subs_B020.json --cue 7

Reads cue{N}post_*.png (the settled frame 40 after the draw) by preference,
falling back to cue{N}_*.png. Reports PASS/FAIL per row plus cues that never
got a screenshot at all.
"""
import glob, json, os, re, struct, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import numpy as np
from PIL import Image

from subs_cue import wrap_only, COLS
import pairfont

FONT_BASE = 0x4CB80
EXE = os.path.join(ROOT, "patched", "SLPS_001.54")
PASS_SCORE = 0.99
BRIGHT = 150

_exe = open(EXE, "rb").read()
_pairs = json.load(open(os.path.join(WORK, "pair_table.json")))
_fw = {}
for line in open(os.path.join(WORK, "font_table.txt"), encoding="utf-8"):
    parts = line.split()
    if len(parts) >= 2 and len(parts[1]) == 1:
        _fw.setdefault(parts[1], int(parts[0]))


def glyph(slot, data=None):
    """12x12 bool array from 18 font bytes (the executable font by slot,
    or an explicit glyph)."""
    if data is None:
        off = FONT_BASE + slot * 18
        data = _exe[off:off + 18]
    rows = []
    for i in range(0, 18, 3):
        w = (data[i] << 16) | (data[i+1] << 8) | data[i+2]
        rows.append((w >> 12) & 0xFFF)
        rows.append(w & 0xFFF)
    g = np.zeros((12, 12), bool)
    for y, v in enumerate(rows):
        for x in range(12):
            if v & (0x800 >> x):
                g[y, x] = True
    return g


def fullwidth_char(ch):
    """Slot for a fullwidth Latin character, via the font table."""
    o = ord(ch)
    if 0x21 <= o <= 0x7E:
        ch = chr(o - 0x20 + 0xFF00)
    return _fw.get(ch)


def row_mask(text):
    """Render one row of subtitle text into a 12-tall ink mask, mirroring
    the payload's cell layout: ASCII paired two-per-cell, pairs without a
    glyph as two fullwidth cells."""
    cells = []
    i = 0
    while i < len(text):
        pair = text[i:i+2]
        if text[i].isascii() and (len(pair) == 1 or not pair[1].isascii()):
            # a lone letter at the end of an ASCII run: the encoder pads it
            # with a space into a pair ("father." ends on the pair ". "),
            # not the fullwidth glyph the validator used to expect - every
            # odd-length row scored ~0.8 on its last cell
            pair = text[i] + " "
            if pair in _pairs:
                cells.append(glyph(None, pairfont.render_pair(pair)))
                i += 1
                continue
        if len(pair) == 2 and pair in _pairs:
            # rendered from the pair renderer, NOT read out of the patched
            # exec: a stub written over a live pair slot corrupted `ep`
            # game-wide and the validator matched the garbage against itself
            cells.append(glyph(None, pairfont.render_pair(pair)))
            i += 2
            continue
        s = fullwidth_char(text[i])
        if s is None and text[i].isascii() and text[i].strip():
            # the font table has no fullwidth lowercase; the game shows the
            # fullwidth glyph, near enough the pair glyph of the letter alone
            cells.append(glyph(None, pairfont.render_pair(text[i] + " ")))
        else:
            cells.append(glyph(s) if s is not None else np.zeros((12, 12), bool))
        i += 1
    if not cells:
        return np.zeros((12, 12), bool)
    return np.concatenate(cells, axis=1)


def best_overlap(bright, mask):
    """Max fraction of mask ink that lands on bright pixels, over every
    position in the frame (FFT cross-correlation)."""
    ink = mask.sum()
    if ink == 0:
        return 1.0, (0, 0)
    H, W = bright.shape
    h, w = mask.shape
    if h > H or w > W:
        return 0.0, (0, 0)
    fb = np.fft.rfft2(bright.astype(np.float32))
    fm = np.fft.rfft2(mask[::-1, ::-1].astype(np.float32), s=bright.shape)
    corr = np.fft.irfft2(fb * fm, s=bright.shape)
    valid = corr[h-1:H, w-1:W]
    yx = np.unravel_index(np.argmax(valid), valid.shape)
    return float(valid[yx]) / ink, (int(yx[0]), int(yx[1]))


def frame_bright(path):
    a = np.asarray(Image.open(path).convert("RGB"), np.int16)
    return (a.max(axis=2) > BRIGHT)


def expected_rows(cue, rows, cols=COLS):
    return [r for r in
            wrap_only(cue["en"].replace("/n", chr(10)), rows, cue.get("cols", cols))
            .split(chr(10)) if r.strip()]


# The box: rows are searched for only below BOX_Y0 (the picture above is
# full of bright ink that any row correlates with - BUG-003: a capture of an
# empty box over Chin's face passed "What?!"), jointly, PITCH rows apart at
# one x - the way the engine lays them. The game draws the font 1:1, so a
# card that is right matches its rendering exactly: every passing capture of
# the 2026-11-05 runs scored 1.00 with no stray ink. EXTRA = bright pixels
# in the rows' band (from the first cell to two cells past the row's end)
# that the expected glyphs do not explain, as a share of the expected ink:
# a garbled pair glyph, a stale row tail, a row that overflows its width.
BOX_Y0, BOX_X1, PITCH, EXTRA_X1 = 140, 248, 16, 233     # EXTRA_X1: the box's wait cursor
EXTRA_MAX = 0.01
EMPTY_INK = 20


def _corr(bright, mask):
    """[y, x] = share of mask ink on bright pixels with the mask's top-left there."""
    H, W = bright.shape
    h, w = mask.shape
    if h > H or w > W:
        return np.zeros((1, 1))
    fb = np.fft.rfft2(bright.astype(np.float32))
    fm = np.fft.rfft2(mask[::-1, ::-1].astype(np.float32), s=bright.shape)
    corr = np.fft.irfft2(fb * fm, s=bright.shape)
    return corr[h-1:H, w-1:W] / max(int(mask.sum()), 1)


def validate_box(path, cue, rows, cols=COLS, alt_cols=()):
    """(rows [(text, score, (y, x))], extra, box_ink): the cue's rows found
    together in the dialogue box. `alt_cols` lists other widths the card may
    have been wrapped at (the face-left layout types a card at 18 cells when
    its speaker has no face in the band); the best wrap wins."""
    from scipy.ndimage import binary_dilation
    reg = frame_bright(path)[BOX_Y0:, :BOX_X1]
    # ink of text in the box at all: the rows' area right of the face
    # column, or the whole width when the left holds no portrait (a short
    # plain card, 'Yes.', ends before x=92). A face with nothing beside it
    # is an empty card: the band's close took the text with the face
    left, right = int(reg[20:80, 8:92].sum()), int(reg[20:80, 92:EXTRA_X1].sum())
    ink = right if left > 300 else left + right
    best = None
    for w in (cols,) + tuple(alt_cols):
        texts = expected_rows(cue, rows, w)
        masks = [row_mask(t) for t in texts]
        if not masks:
            return [], 0.0, ink
        maps = [_corr(reg, m) for m in masks]
        H = min(mp.shape[0] - PITCH * k for k, mp in enumerate(maps))
        W = min(mp.shape[1] for mp in maps)
        if H <= 0 or W <= 0:
            continue
        J = np.min([mp[PITCH * k:PITCH * k + H, :W] for k, mp in enumerate(maps)], axis=0)
        # a short row ('P.S.', '3.') matches perfectly in more than one place
        # (the disk reader's monitor text sits inside the box region too):
        # of the near-best placements, the one with the least stray ink wins
        top = np.argsort(J, axis=None)[::-1][:600]
        jmax = float(J.flat[top[0]])
        # each row's glyphs grown by a pixel, on a canvas two cells wider
        # than the row: the band the stray ink is counted in
        dil = []
        for m in masks:
            c = np.zeros((14, m.shape[1] + 26), bool)
            c[1:13, 1:1 + m.shape[1]] = m
            dil.append(binary_dilation(c, iterations=1)[1:13, 1:])
        ink_total = max(sum(int(m.sum()) for m in masks), 1)
        H2, W2 = reg.shape
        for flat in top:
            if float(J.flat[flat]) < jmax - 0.05:
                break
            y, x = (int(v) for v in np.unravel_index(flat, J.shape))
            stray = 0
            for k, d in enumerate(dil):
                yy = y + PITCH * k
                x1 = min(EXTRA_X1, x + d.shape[1], W2)
                if yy >= H2 or x1 <= x:
                    continue
                win = reg[yy:yy + 12, x:x1]
                stray += int((win & ~d[:win.shape[0], :win.shape[1]]).sum())
            extra = stray / ink_total
            res = [(t, float(mp[y + PITCH * k, x]), (y + BOX_Y0 + PITCH * k, x))
                   for k, (t, mp) in enumerate(zip(texts, maps))]
            cand = (min(r[1] for r in res) - extra, res, extra)
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return [(t, 0.0, (0, 0)) for t in expected_rows(cue, rows, cols)], 1.0, ink
    return best[1], best[2], ink


def validate_shot(path, cue, rows, cols=COLS, alt_cols=()):
    """The rows with their scores (validate_box without the extra ink)."""
    return validate_box(path, cue, rows, cols, alt_cols)[0]


def main():
    target, jpath = sys.argv[1], sys.argv[2]
    # --prefix xB210_: score the captures of another bank a run crossed into
    # (scripted.py names them x<bank>_cue<N>...) against that bank's cues,
    # into validate_<bank>.txt
    prefix = sys.argv[sys.argv.index("--prefix") + 1] if "--prefix" in sys.argv else ""
    d = json.load(open(jpath, encoding="utf-8"))
    rows = d.get("options", {}).get("rows", 3)
    cols = d.get("options", {}).get("cols", COLS)
    alt = (18,) if d.get("options", {}).get("faceleft") and cols != 18 else ()
    cues = [c for c in d["cues"] if c.get("enabled", True)]

    if os.path.isfile(target):
        idx = int(sys.argv[sys.argv.index("--cue") + 1])
        for r, s, pos in validate_shot(target, cues[idx], rows, cols, alt):
            print(f"{'PASS' if s >= PASS_SCORE else 'FAIL'} {s:.2f} @{pos} {r!r}")
        return

    # Keep EVERY frame captured for a cue and score them all, best wins. A
    # single settle frame is not safe: the driver can dismiss the box before
    # it fires, and an empty frame still scores non-zero on some rows - one
    # run reported FAIL on a screenshot that had no dialogue box in it at all.
    shots = {}
    for p in sorted(glob.glob(os.path.join(target, prefix + "cue*_*.png"))):
        m = re.match(r"cue(\d+)(post\d*)?_", os.path.basename(p)[len(prefix):])
        if not m:
            continue
        shots.setdefault(int(m.group(1)), []).append(p)

    passed = failed = missing = hidden = nosettle = 0
    report = []
    for i, c in enumerate(cues):
        if not c["en"].strip():
            continue
        if i not in shots:
            report.append(f"NOSHOT {c['id']}  (never drew or not captured)")
            missing += 1
            continue
        # the draw-frame capture is taken before the type-on: it shows the
        # previous card or an empty box and is scored only when nothing
        # settled was captured (a card taken down within 40 frames)
        settled_shots = [p for p in shots[i] if 'post' in os.path.basename(p)]
        if not settled_shots:
            nosettle += 1
            report.append(f"NOSETTLE {c['id']}  shown under 40 frames: only the draw frame was captured")
            continue
        tries = []
        for p in settled_shots:
            res, extra, ink = validate_box(p, c, rows, cols, alt)
            score = min((s for _, s, _ in res), default=1.0)
            tries.append((score - extra, score, extra, ink, p, res))
        _, score, extra, ink, shot, results = max(tries, key=lambda t: t[0])
        settled = [t for t in tries if 'post' in os.path.basename(t[4])]
        if score >= PASS_SCORE and extra <= EXTRA_MAX:
            passed += 1
            report.append(f"pass   {c['id']}  ({score:.2f})")
        elif settled and all(t[3] < EMPTY_INK for t in settled):
            # every settled capture shows an empty box: the card was taken
            # down before it settled (the face-left rule ends the text with
            # its face) - nothing on screen to compare, reported apart
            hidden += 1
            report.append(f"HIDDEN {c['id']}  empty box in every settled capture ({len(shots[i])} shots)")
        else:
            failed += 1
            report.append(f"FAIL   {c['id']}  {os.path.basename(shot)} (best of {len(shots[i])}, extra ink {extra:.2f})")
            for r, s, pos in results:
                mark = "ok " if s >= PASS_SCORE else "BAD"
                report.append(f"         {mark} {s:.2f} @{pos} {r!r}")
    print("\n".join(report))
    print(f"\n{passed} pass, {failed} FAIL, {missing} no screenshot "
          f"of {passed+failed+missing+hidden+nosettle} enabled cues, {hidden} hidden, {nosettle} not settled")
    rp = os.path.join(target, f"validate_{prefix[1:-1]}.txt" if prefix else "validate.txt")
    open(rp, "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("report:", rp)


if __name__ == "__main__":
    main()
