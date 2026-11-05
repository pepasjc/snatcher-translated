"""Translate NSZ_B000.BIN speaker names (dual-tile English).

Two modes:
  full  — natural-length names; relies on engine walking len-prefixed records
          and sector-granularity CD reads (file alone in its sector, 1609B slack).
  fit   — exact original byte length, space-padded (safe fallback).
"""
import sys, os
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from pairfont import PairFont

SRC = os.path.join(ROOT, "discs/extracted_ps1/PLN/NSZ/NSZ_B000.BIN")
OUT = os.path.join(ROOT, "patched/NSZ_B000.BIN")

NAMES = [
    "Metal Gear", "Harry", "Receptionist", "Gillian", "Mika", "Chief",
    "Gaudi", "Napoleon", "Jamie", "Clerk", "Catherine", "Man", "Woman",
    "Passerby", "Announcer", "Barker", "Master", "Pawapuro", "Goemon",
    "Pastel", "Light", "Dracula", "Simon", "Design Man", "Isabella",
    "Freeman", "Ivan", "Lisa", "Rie", "Young Gal", "Fukui II", "Hayasaka",
    "Voice", "Aizawa", "Asato", "Ans. Machine", "Mizutani", "Kiyohara",
    "Kidasu", "Su", "Noguchi", "Adachi", "Yoshitomi", "Object", "Takayuki",
    "Asami", "Naoya", "Yumiko", "Komatsubara", "Kom. Brother", "Matsukawa",
    "Tacchan", "Gaudi  (Y)", "Konami", "Parrot", "Customer", "Petrovich",
    "Randam", "Driver",
]
# "Parrot" is オウム (the JP dump writes ム as メ, `オウメ` - "Oume" until 2026-09-17).
# "Gaudi  (Y)" (ガウディ黄) carries two spaces so " (" and "Y)" stay on pair
# glyphs; with one space "(Y" has no slot and falls back to fullwidth.

def parse(d):
    recs = []
    i = 0
    while i < len(d):
        ln = d[i]
        if ln == 0 or i+1+ln > len(d):
            break
        recs.append(d[i+1:i+1+ln])
        i += 1 + ln
    return recs


def build(pf, mode="full"):
    """Encode the name table with `pf`. Returns (bytes, original length).

    Callers that already hold a PairFont (apply_translation) use this so the
    name table can never be left encoded against a stale pair table.
    """
    d = open(SRC, "rb").read()
    recs = parse(d)
    assert len(recs) == len(NAMES), (len(recs), len(NAMES))
    out = bytearray()
    for jp, en in zip(recs, NAMES):
        eb = pf.encode(en)
        if mode == "fit":
            while len(eb) > len(jp):        # trim to budget
                en = en[:-1]
                eb = pf.encode(en)
            eb = eb + pf.encode(" ") * ((len(jp) - len(eb)) // 2)
        out.append(len(eb))
        out += eb
    if len(out) > 2048:
        raise SystemExit(f"name table too big: {len(out)}")
    return bytes(out), len(d)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    pf = PairFont()
    out, orig = build(pf, mode)
    pf.save()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "wb").write(out)
    # re-write exec glyphs including any new pairs
    exe_path = os.path.join(ROOT, "patched/SLPS_001.54")
    exe = bytearray(open(exe_path, "rb").read())
    pf.write_glyphs(exe)
    open(exe_path, "wb").write(exe)
    print(f"mode={mode}: {len(out)} bytes (orig {orig}), {len(pf.table)} total pair glyphs")
