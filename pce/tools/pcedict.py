"""A per-module dictionary for the PCE text: frequent cell runs as one code.

The decoder stub (pceengine dentry) treats a row-0x84 code with lo 0x41..0xFF
(the English flag up) as "insert entry k": it saves the string pointer,
decodes the entry - an ordinary nibble stream, byte-aligned, ending like a
string - and comes back. A reference costs 1.5 bytes; every cell it
replaces cost 1.5, so a run of n cells seen m times saves 1.5 (n-1) m less
its 1.5 n + 3 bytes of storage.

Everything is done on CELLS (pcepair.split: letter pairs and singles), never
on characters: a reference then sits on a cell boundary and the letters
around it pair up exactly as they did, so row widths are unchanged and no
lone space turns into a full cell. `items(text)` is the cell/tag list of a
laid-out line; `build(lines)` picks the fragments; `encode(items, frags)`
is the line's code list with references; `entries(frags, at)` the entry
blob and offsets; `table(offs)` the slot table the stub indexes.
"""
import collections, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import pcepair
import pcetext as T

ENTRIES = 190                 # row 0x84, lo 0x41..0xFF without 0x7F
TAG = re.compile(r"(<[^>]*>)")
MIN, MAX = 2, 12              # cells per fragment


def lo_of(k):
    lo = 0x41 + k
    return lo + 1 if lo >= 0x7F else lo


def items(text):
    """[('c', cell) | ('t', tag)] for a laid-out line; a cell is a (a, b)
    pair or a single character."""
    out = []
    for part in TAG.split(text):
        if not part:
            continue
        if part.startswith("<"):
            out.append(("t", part))
        else:
            out += [("c", c) for c in pcepair.split(part)]
    return out


def cell_code(cell):
    if isinstance(cell, tuple):
        return pcepair.pair_code(*cell)
    if ord(cell) < 0x80:
        return tuple(chr(T.FULLWIDTH[ord(cell)]).encode("cp932"))
    return tuple(cell.encode("cp932"))


def build(lines, entries=ENTRIES):
    """Fragments (tuples of cells) worth a slot, best first: greedy, each
    pick measured on the corpus with the earlier picks already applied
    (a chosen run is one opaque cell from then on)."""
    runs = []
    for text in lines:
        run = []
        for kind, v in items(text) + [("t", "")]:
            if kind == "c":
                run.append(v)
            else:
                if run:
                    runs.append(run)
                run = []
    picked = []
    while len(picked) < entries:
        count = collections.Counter()
        for run in runs:
            for n in range(MIN, min(MAX, len(run)) + 1):
                for i in range(len(run) - n + 1):
                    frag = tuple(run[i:i + n])
                    if not any(isinstance(c, tuple) and c[0] == "d" for c in frag):
                        count[frag] += 1
        best, best_save = None, 0
        for frag, m in count.items():
            n = len(frag)
            save = m * 1.5 * (n - 1) - (1.5 * n + 3)
            if save > best_save:
                best, best_save = frag, save
        if best is None:
            break
        k = len(picked)
        picked.append(best)
        n = len(best)
        for run in runs:
            i = 0
            while i <= len(run) - n:
                if tuple(run[i:i + n]) == best:
                    run[i:i + n] = [("d", k)]
                else:
                    i += 1
    return picked


def _contains(a, b):
    """b occurs inside a as a cell run."""
    return any(a[i:i + len(b)] == b for i in range(len(a) - len(b) + 1))


def encode(text, frags, english=True):
    """The line's (hi, lo) codes with dictionary references."""
    order = sorted(range(len(frags)), key=lambda k: -len(frags[k])) if frags else []
    out = [pcepair.MARK] if english else []
    run = []

    def flush():
        i = 0
        while i < len(run):
            for k in order:
                f = frags[k]
                if tuple(run[i:i + len(f)]) == f:
                    out.append((0x84, lo_of(k)))
                    i += len(f)
                    break
            else:
                out.append(cell_code(run[i]))
                i += 1
        run.clear()

    for kind, v in items(text):
        if kind == "c":
            run.append(v)
        else:
            flush()
            out += list(T.tokens(v))          # a tag's code, if it has one
    flush()
    return out


def line_bytes(text, frags, english=True):
    return T.encode_tokens(encode(text, frags, english))


def entries(frags, at):
    """(entry blob, [offsets]) with each entry encoded at `at` onward."""
    blob, offs = bytearray(), []
    for f in frags:
        offs.append(at + len(blob))
        blob += T.encode_tokens([cell_code(c) for c in f])
    return bytes(blob), offs


def table(offs):
    """The slot table the stub indexes by lo - 0x41 (0x7F's slot stays
    empty), as long as the last used slot."""
    slots = [lo_of(k) - 0x41 for k in range(len(offs))]
    out = bytearray((max(slots) + 1) * 2) if slots else b""
    for k, o in enumerate(offs):
        out[2 * slots[k]:2 * slots[k] + 2] = o.to_bytes(2, "little")
    return bytes(out)
