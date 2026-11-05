# -*- coding: utf-8 -*-
"""The engine's own menu cursor, read from RAM.

Every screen-based way of knowing where the cursor is failed in the end: the
highlight bar is not drawn in every layout, short labels do not correlate
reliably (Move 0.66, and in the wrong column), and the menu box moves with the
scene's vertical split so a cached row goes stale. The engine of course knows,
and it keeps it in one word at ctx+0x1D7C (found by pressing `down` and
diffing RAM for a period-N byte - attic/cursor_probe.py, then traced with
attic/cursor_trace.py):

    byte 0   0xF8 while a menu is live and taking input
             0x04 for the frames between a confirm and the next menu
             0x00 when nothing is selectable (dialogue box, idle, cutscene)
    byte 1   count << 4 | index << 1 | live      (0x53 = 5 items, cursor on 1)
    byte 2   a per-press animation counter, 0 when settled

Two properties matter for driving: the label table at 0x800AE670 is rebuilt
one frame BEFORE the live flag sets, so whenever `live` is true the labels
are the ones under the cursor; and the cursor is remembered across a
submenu, so it is NOT on item 0 when the verb menu comes back.
"""
import ctypes as C

CTX = 0x80010000
ADDR = CTX + 0x1D7C


def read(ram):
    """(live, index, count) from a libretro RAM pointer.

    0xF9 in byte 0 is the same widget inside the videophone layout: the
    Call/No call menu reads 0xF9 0x21. The keypad itself reads 0xF9 0xA1
    (count 10) and is NOT a menu - see `keypad()`.
    """
    b = C.string_at(C.c_void_p(ram + (ADDR & 0x1FFFFF)), 4)
    count = b[1] >> 4
    live = b[0] in (0xF8, 0xF9) and bool(b[1] & 1)
    if live and b[0] == 0xF9 and dialling(ram):
        live = False
    return live, (b[1] >> 1) & 7, count


def dialling(ram):
    """True while the keypad is up: the label table then holds the
    dial-table matcher strings (数３９５６４４ ...) - all of them before the
    first digit, the surviving candidates after - rather than menu text.
    ctx+0x1D7C is no use here: it reads 0xF9 0xA1 on the fresh pad and
    0x01 0x40 once digits are in."""
    from menuread import read_menu
    b = C.string_at(C.c_void_p(ram + (ADDR & 0x1FFFFF)), 2)
    # byte 0 reads 0xF9 on the fresh pad, 0x01 once digits are in, and 0x05
    # after the number is placed - the 数 labels linger past that, so bit 2
    # is what says the pad is gone
    if b[0] & 0x04:
        return False
    labels = read_menu(ram)
    return bool(labels) and any('数' in x for x in labels)


def keypad(ram):
    """The videophone keypad's highlighted key, 1-12, or 0 when the pad is
    not taking input.

    ctx+0x1DAE is the key under the cursor (0-based) while the pad polls
    input and 0xFF otherwise; 1-9 are the digits, 10 '*', 11 '0', 12 '#',
    three per row, wrapping both ways. '#' places the call (it opens the
    Call/No call menu). Found with attic/fight_ram.py --mode pad.
    """
    k = C.string_at(C.c_void_p(ram + ((CTX + 0x1DAE) & 0x1FFFFF)), 1)[0]
    if not dialling(ram):
        return 0                            # the key byte is stale after a call
    return k + 1 if k < 12 else 13          # 13: pad up, key unknown
