# -*- coding: utf-8 -*-
"""Stamp the built images' hashes into ps1/RELEASE_NOTES.md.

Make-Patch.bat refuses to finish while ps1/RELEASE_NOTES.md names the wrong
patch files or the wrong result hashes (release_readme.check_notes), because
0.6 once shipped telling players to run the 0.5.2 command. The filename half
of that check is worth keeping manual - it is the half that catches a
forgotten version bump - but the hashes change on every rebuild and copying
four lines by hand four times in a day is how a wrong one gets in.

    python lib/stamp_notes.py            # from patched/, per variant
    python lib/stamp_notes.py --check    # exit 1 if the notes are stale

The notes carry one fenced block per variant, each headed by the .bin name
the patch produces; this rewrites the Size/CRC32/MD5/SHA1 lines inside those
blocks and leaves everything else alone.
"""
import argparse
import os
import re
import sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from release_readme import hashes

NOTES = os.path.join(ROOT, 'ps1', 'RELEASE_NOTES.md')
# the .bin a patch produces -> the image it is built from
VARIANTS = [('', 'Snatcher (Japan) [censored].bin'),
            (' (Uncensored)', 'Snatcher (Japan).bin')]


def version():
    return open(os.path.join(ROOT, 'ps1', 'VERSION'), encoding='utf-8').read().strip()


def block(h):
    return (f"Size   {h['Size']}\nCRC32  {h['CRC32']}\n"
            f"MD5    {h['MD5']}\nSHA1   {h['SHA1']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='report staleness instead of fixing it')
    a = ap.parse_args()
    ver = version()
    text = open(NOTES, encoding='utf-8').read()
    stale = []
    for suffix, image in VARIANTS:
        path = os.path.join(ROOT, 'patched', image)
        if not os.path.exists(path):
            sys.exit(f'missing image: {path} - run Make-Release.bat first')
        name = f'Snatcher (Japan) [T-En by pepa v{ver}]{suffix}.bin'
        # the fenced block headed by this .bin name
        pat = re.compile(r'(```\n' + re.escape(name) + r'\n)(.*?)(\n```)', re.S)
        m = pat.search(text)
        if not m:
            sys.exit(f'RELEASE_NOTES.md has no hash block for "{name}"')
        want = block(hashes(path))
        if m.group(2).strip() != want:
            stale.append(name)
            text = text[:m.start(2)] + want + text[m.end(2):]
    if a.check:
        for n in stale:
            print(f'stale: {n}')
        return 1 if stale else 0
    if stale:
        open(NOTES, 'w', encoding='utf-8', newline='\n').write(text)
        for n in stale:
            print(f'stamped {n}')
    else:
        print('RELEASE_NOTES.md already matches the built images')
    return 0


if __name__ == '__main__':
    sys.exit(main())
