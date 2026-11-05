"""Encode English text into the game's pair-glyph SJIS bytes.

render_text (0x800367D8) consumes Shift-JIS; the engine converts pair-glyph
codes to SJIS upstream, so subtitle text is stored pre-converted. Pairs that
have no glyph slot fall back to fullwidth Latin (1 code per letter).
"""
import json, os

_pt = None


def _table():
    global _pt
    if _pt is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _pt = json.load(open(os.path.join(root, "work", "pair_table.json")))
    return _pt


def slot_to_sjis(slot):
    n = slot + 845
    ku, ten = n // 94 + 1, n % 94 + 1
    b1 = (ku + 257) // 2 if ku <= 62 else (ku + 385) // 2
    if ku % 2:
        b2 = ten + 63 + (1 if ten >= 64 else 0)
    else:
        b2 = ten + 158
    return bytes((b1, b2))


def fullwidth_sjis(ch):
    o = ord(ch)
    if ch == " ":
        return b"\x81\x40"
    if 0x21 <= o <= 0x7E:
        try:
            return chr(o - 0x20 + 0xFF00).encode("cp932")
        except UnicodeEncodeError:
            pass
    return b"\x81\x40"


LINEBREAK = bytes((0x81, 0x8F))   # the engine line break, as SJIS


def encode(text):
    """A newline in the source becomes the engine line-break code.

    Pairs are taken left to right; an ASCII character left alone at the
    end of a row (before a newline, the end of the text, or a fullwidth
    character) is paired with a SPACE, exactly as pairfont.encode pads an
    odd run for the banks. Until 2026-09-12 it went out as a fullwidth
    letter - one wide, centred glyph - so every subtitle row of odd length
    ended in a detached letter or a wide full stop: 'So Queen Hospital
    an d' / 'the tube liner wer e' (Luiz, B220; 3,286 of 5,312 cue texts
    had one). rebuild_pairs counts pairs the pairfont way, so every such
    'x ' pair has a slot."""
    pt = _table()
    out = bytearray()
    i = 0
    while i < len(text):
        if text[i] == chr(10):
            out += LINEBREAK
            i += 1
            continue
        pair = text[i:i + 2]
        if len(pair) == 2 and pair[1] != chr(10) and pair in pt:
            out += slot_to_sjis(pt[pair][0])
            i += 2
            continue
        alone = ord(text[i]) < 0x80 and (i + 1 == len(text) or text[i + 1] == chr(10) or ord(text[i + 1]) >= 0x80)
        if alone and (text[i] + " ") in pt:
            out += slot_to_sjis(pt[text[i] + " "][0])
            i += 1
            continue
        out += fullwidth_sjis(text[i])
        i += 1
    return bytes(out) + b"\x00\x00"


if __name__ == "__main__":
    import sys
    b = encode(sys.argv[1])
    print(len(b), b.hex())
