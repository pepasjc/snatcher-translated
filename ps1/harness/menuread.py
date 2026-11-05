# -*- coding: utf-8 -*-
"""Read the live menu labels out of RAM, so the pilot can aim by name.

The engine copies the text of the current menu's items into a table of
64-byte entries at 0x800AE670, with the entry count at 0x800ABF60 (that is
the same table CLAUDE.md describes as holding "copied glyph-code text of the
live menu strings, not pointers"). Decoding it turns the pilot from something
that presses cursor positions blindly into something that can be told
"choose TALK" - which is what following a walkthrough needs.

    labels = read_menu(ram)      # ['Exit Tricycle', 'Ruins', 'Home']

Text is pair-glyph encoded exactly like the script, so it decodes with
work/pair_table.json plus lib/textcodec for anything fullwidth.
"""
import json, os, sys
import ctypes as C
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import textcodec

MENU_TABLE = 0x800AE670
MENU_COUNT = 0x800ABF60
ENTRY = 64

_pairs = json.load(open(os.path.join(WORK, 'pair_table.json'), encoding='utf-8'))
BY_CODE = {v[1]: k for k, v in _pairs.items()}


def decode(b):
    """Glyph codes -> text, stopping at the terminator."""
    out = []
    for i in range(0, len(b) - 1, 2):
        code = (b[i] << 8) | b[i + 1]
        if b[i] == 0:
            # the string ends at its first 0x00 byte: a label copied over a
            # longer one keeps the old bytes after it ('Look' read 'Lookr lo'
            # in B230's booth menu, 2026-11-07)
            break
        if code in BY_CODE:
            out.append(BY_CODE[code])
        else:
            ch = textcodec.code_to_char(code)
            out.append(ch if ch else '')
    return ''.join(out).strip()


def read_menu(ram, limit=16):
    """[label, ...] for the menu currently on screen, or [] if there is none."""
    count = int.from_bytes(C.string_at(C.c_void_p(ram + (MENU_COUNT & 0x1FFFFF)),
                                       4), 'little')
    if not 0 < count <= limit:
        return []
    base = ram + (MENU_TABLE & 0x1FFFFF)
    return [decode(C.string_at(C.c_void_p(base + i * ENTRY), ENTRY))
            for i in range(count)]


def read_cells(ram, limit=16):
    """[cells, ...] per live label: the glyph codes before the terminator.
    One code = one cell on the list grid (a pair glyph or a fullwidth
    character alike), so this is what the renderer will place."""
    count = int.from_bytes(C.string_at(C.c_void_p(ram + (MENU_COUNT & 0x1FFFFF)),
                                       4), 'little')
    if not 0 < count <= limit:
        return []
    base = ram + (MENU_TABLE & 0x1FFFFF)
    out = []
    for i in range(count):
        b = C.string_at(C.c_void_p(base + i * ENTRY), ENTRY)
        n = 0
        for j in range(0, len(b) - 1, 2):
            if b[j] == 0:                  # the terminator byte (see decode)
                break
            n += 1
        out.append(n)
    return out


def geometry(labels, cells):
    """Labels that overflow the list grid: [(idx, label, cells, limit)].

    The list menu (0x8004D90C) fills a buffer of four 18-cell rows laid
    back to back: item i goes to row i % 4 at cell 0 (i < 4) or cell 10
    (i >= 4), and render_text cuts at 18 with no wrap. A right-column
    label past 8 cells runs into the next row's first cells (over the left
    label there, or past the buffer's end on row 3); a left label past 10
    runs under its right neighbour, past 18 into the next row."""
    bad = []
    n = len(labels)
    for i, (lab, w) in enumerate(zip(labels, cells)):
        if i >= 4:
            limit = 8
        elif i + 4 < n:
            limit = 10
        else:
            limit = 18
        if w > limit:
            bad.append((i, lab, w, limit))
    return bad


def find(labels, want):
    """Index of the first label matching `want`, else None.

    Guides write commands in capitals (TALK, ASK ABOUT MIKA) while the game
    prints them mixed case, so matching is case-insensitive and accepts a
    prefix - "ASK ABOUT JUNKERS" should find an "Ask" item.
    """
    w = want.strip().lower()
    for i, lab in enumerate(labels):
        if lab.lower() == w:
            return i
    for i, lab in enumerate(labels):
        low = lab.lower()
        if low and (w.startswith(low) or low.startswith(w)):
            return i
    for i, lab in enumerate(labels):
        if lab and lab.lower() in w:
            return i
    return None

_strings = {}


def known_strings(scene):
    """Every English string in a bank, for cleaning up menu labels.

    The engine does not clear a menu entry before writing a shorter label into
    it, so the tail of the previous one survives: "Item" written over
    "Use Metal Gear" reads back as "Itemtal Gear", and "Look" over
    "Look HQ" keeps the " HQ". The bank's own translated strings settle it -
    the real label is the longest prefix that is actually a string in this
    scene.
    """
    if scene not in _strings:
        p = os.path.join(ROOT, 'ps1/translation', f'ISZ_{scene}.json')
        out = set()
        if os.path.exists(p):
            doc = json.load(open(p, encoding='utf-8'))
            for row in (doc['strings'] if isinstance(doc, dict) else doc):
                for k in ('en', 'long'):
                    v = (row.get(k) or '').strip()
                    if v:
                        out.add(v)
        _strings[scene] = out
    return _strings[scene]


def clean(label, scene):
    known = known_strings(scene)
    if not known or label in known:
        return label
    best = ''
    for n in range(len(label), 0, -1):
        if label[:n] in known:
            best = label[:n]
            break
    return best or label

# The guide's command words are the Sega CD's; our menu labels are our own
# translation, so they disagree more often than not. "MOVE and ADVANCE" is
# `Forward` in our text, and the pilot sat in the ruins corridor unable to
# walk down it. Keys are guide words, values are label words to try.
SYNONYMS = {
    'ADVANCE': ('Forward', 'Move'),
    'MOVE': ('Move', 'Forward'),
    'INVESTIGATE': ('Investigate', 'Look'),
    'EXAMINE': ('Investigate', 'Look'),
    'SEARCH': ('Investigate',),
    'POSSESSIONS': ('Item',),
    'INVENTORY': ('Item',),
    # NOT 'Back': in a Forward/Back menu that is retreat, and the pilot
    # spent a run stepping forward then immediately back out again.
    'EXIT': ('Go out', 'Leave'),
    'LEAVE': ('Go out',),
    'BACK': ('Back', 'Go out'),
    'ENTER': ('Go inside', 'Enter', 'Board Tricycle'),
    'CALL': ('Videophone',),
    'PHONE': ('Videophone',),
    'LISTEN': ('Listen', 'Hear'),
    'ANSWER': ('Answer',),
    'QUESTION': ('Ask',),
    'TURBOCYCLE': ('Board Tricycle', 'Go inside'),
}


def find_any(labels, want):
    """Index of a label matching `want`, trying the guide-word synonyms too."""
    i = find(labels, want)
    if i is not None:
        return i
    for alt in SYNONYMS.get(want.strip().upper(), ()):
        i = find(labels, alt)
        if i is not None:
            return i
    return None
