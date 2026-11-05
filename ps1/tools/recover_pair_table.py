# -*- coding: utf-8 -*-
"""Recover work/pair_table.json from a built image.

    python ps1/tools/recover_pair_table.py [--image IMG] [--xdelta X] [out.json]

Every pair glyph the build writes into the exec's font is render_pair(p)
for an ASCII pair p, so a built image gives the table back: read every
slot of the level-1 pool (the slots rebuild_pairs assigns - the current
work/pair_table.json names them), match its 18 bytes against the render
of every printable pair, and the slot's pair is the one that matches.
Used once, 2026-09-12: the junction deletion took work/pair_table.json,
a rebuild put 663 of 1,375 pairs on other slots (the cue texts had
changed since the last rebuild), every bookmark's on-screen text turned
to garbage against the new font, and the 0.8.1 release image (pristine +
its xdelta) still carried the table every translation was fitted
against. Two things the glyphs alone cannot tell: game punctuation below
slot 200 renders exactly like ', ', ' (', ') ', '" '... (hence the pool
restriction), and the blank pair '  ' is the pool's one all-zero slot.
Writes work/pair_table.recovered.json; copy it over work/pair_table.json
after fit_report passes on every bank.
"""
import argparse, json, os, struct, subprocess, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import pairfont

PRISTINE = os.path.join(ROOT, 'discs', 'iso_ps1_jp', 'Snatcher (Japan).bin')


def code_of(slot):
    """The text code of a font slot (textcodec's layout in reverse)."""
    n = slot + 845
    ku, ten = n // 94 + 1, n % 94 + 1
    high = 0x80 - (ku + 1) // 2
    pos = (0 if ku % 2 else 94) + (ten - 1)
    low = 0xC0 - pos
    if low <= 0x80:
        low -= 1
    return (high << 8) | low


def read_exec(img):
    f = open(img, 'rb')

    def rsec(lba):
        f.seek(lba * 2352 + 24)
        return f.read(2048)

    def listdir(lba, ln):
        data = b''.join(rsec(lba + i) for i in range((ln + 2047) // 2048))
        i = 0
        while i < len(data):
            l = data[i]
            if l == 0:
                i = (i // 2048 + 1) * 2048
                continue
            e_lba, e_sz = struct.unpack('<I', data[i+2:i+6])[0], struct.unpack('<I', data[i+10:i+14])[0]
            nm = data[i+33:i+33+data[i+32]].decode('latin1').split(';')[0]
            if nm not in ('\x00', '\x01'):
                yield nm, e_lba, e_sz
            i += l

    pvd = rsec(16)
    rec = pvd[156:156+34]
    root_lba, root_len = struct.unpack('<I', rec[2:6])[0], struct.unpack('<I', rec[10:14])[0]
    for nm, lba, sz in listdir(root_lba, root_len):
        if nm.startswith('SLPS_001.54'):
            exe = b''.join(rsec(lba + i) for i in range((sz + 2047) // 2048))[:sz]
            assert exe[:8] == b'PS-X EXE', exe[:8]
            print(f'exec at LBA {lba}, {sz} bytes')
            return exe
    raise SystemExit('no SLPS_001.54 in the image')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', nargs='?', default=os.path.join(WORK, 'pair_table.recovered.json'))
    ap.add_argument('--image', help='a built image (default: the 0.8.1 release rebuilt from its xdelta into work/)')
    ap.add_argument('--xdelta', default=os.path.join(ROOT, 'release', 'Snatcher (Japan) [T-En by pepa v0.8.1].xdelta'))
    a = ap.parse_args()
    img = a.image or os.path.join(WORK, 'release_image_for_pairs.bin')
    if not a.image and not os.path.exists(img):
        subprocess.run([os.path.join(ROOT, 'lib', 'xdelta', 'xdelta3.exe'), '-d', '-f', '-s', PRISTINE, a.xdelta, img], check=True)
    exe = read_exec(img)

    want = {}
    chars = [chr(c) for c in range(0x20, 0x7F)]
    for x in chars:
        for y in chars:
            want.setdefault(pairfont.render_pair(x + y), []).append(x + y)
    cur = json.load(open(pairfont.TABLE))
    pool = sorted({v[0] for v in cur.values()})
    print(f'{len(want)} distinct pair bitmaps, pool of {len(pool)} slots from the current table')

    table, amb = {}, []
    for slot in pool:
        g = exe[pairfont.FONT_BASE + 18 * slot: pairfont.FONT_BASE + 18 * slot + 18]
        if g == bytes(18):
            continue
        ps = want.get(g)
        if not ps:
            print(f'slot {slot}: glyph matches no pair ({g.hex()})')
        elif len(ps) == 1:
            table[ps[0]] = slot
        else:
            amb.append((slot, ps))
    for slot, ps in amb:                       # pairs that render alike ('Il'/'ll'): either owner draws the same
        free = [p for p in ps if p not in table]
        if not free:
            print(f'slot {slot}: every candidate of {ps} already placed')
            continue
        pick = next((p for p in free if cur.get(p, [None])[0] == slot), free[0])
        table[pick] = slot
        print(f'slot {slot}: {ps} -> {pick}')
    zero = [s for s in pool if s not in table.values()]
    if '  ' not in table and zero:
        table['  '] = zero[0]
        print(f"'  ' -> the blank slot {zero[0]}")
    out = {p: [s, code_of(s)] for p, s in table.items()}
    json.dump(out, open(a.out, 'w'))
    same = sum(1 for p in out if p in cur and cur[p][0] == out[p][0])
    print(f'wrote {a.out}: {len(out)} pairs; {same} on the same slot as the current table, {len(out) - same} differ')


if __name__ == '__main__':
    main()
