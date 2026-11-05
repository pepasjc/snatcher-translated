"""Find the TrueType fonts a few build steps render with, on any OS.

    from sysfont import truetype
    f = truetype("arialbd.ttf", 11)        # a PIL ImageFont

Most of the game's English is drawn from the bitmap fonts in lib/fonts (public
domain X11 faces and Tamzen, shipped here). A handful of pictures were set in
Windows fonts, which cannot be redistributed: the boot screens' disclaimer
(Impact, Arial, Arial Bold), the PC Engine title menu (Arial Bold) and credits
(MS Gothic), the Saturn credit roll (Arial, Arial Bold, Times New Roman) and
memo pages (MS Gothic). The build finds them, first match wins, in:

  1. every directory in SNATCHER_FONTS (os.pathsep-separated)
  2. fonts/ at the repository root (ignored by git: drop your copies there)
  3. %WINDIR%\\Fonts (any Windows install)
  4. the usual Linux/macOS font directories, msttcorefonts included

The releases were built with the fonts of Windows 11. Other versions of the
same fonts (msttcorefonts' Arial is the 1998 one) rasterise slightly
differently, so the build still works but its hashes will not match the
release's; copy the five files listed in REQUIRED from a Windows install into
fonts/ to reproduce a release bit for bit.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

REQUIRED = ["arial.ttf", "arialbd.ttf", "impact.ttf", "times.ttf", "msgothic.ttc"]
# other spellings of the same files (msttcorefonts, macOS)
ALIASES = {
    "arial.ttf": ["Arial.ttf"],
    "arialbd.ttf": ["Arial_Bold.ttf", "Arial Bold.ttf"],
    "impact.ttf": ["Impact.ttf"],
    "times.ttf": ["Times_New_Roman.ttf", "Times New Roman.ttf"],
    "msgothic.ttc": ["MS Gothic.ttc", "MSGOTHIC.TTC"],
}
SYSTEM_DIRS = [
    "/usr/share/fonts/truetype/msttcorefonts",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    "/Library/Fonts",
    "/System/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
]


def _dirs():
    out = [d for d in os.environ.get("SNATCHER_FONTS", "").split(os.pathsep) if d]
    out.append(os.path.join(ROOT, "fonts"))
    out.append(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    out += SYSTEM_DIRS
    return out


def find(name):
    """The path of font file `name`, or None."""
    names = [name] + ALIASES.get(name.lower(), [])
    for d in _dirs():
        if not os.path.isdir(d):
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
        # case-insensitive match and one level of subdirectories (Linux font trees)
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        low = {n.lower() for n in names}
        for e in entries:
            p = os.path.join(d, e)
            if e.lower() in low and os.path.isfile(p):
                return p
        for e in entries:
            sub = os.path.join(d, e)
            if os.path.isdir(sub):
                try:
                    for f in os.listdir(sub):
                        if f.lower() in low:
                            return os.path.join(sub, f)
                except OSError:
                    pass
    return None


def path(name):
    p = find(name)
    if p is None:
        sys.exit(f"font {name} not found. Copy it from a Windows install (C:\\Windows\\Fonts) into "
                 f"{os.path.join(ROOT, 'fonts')} or a directory named in SNATCHER_FONTS. "
                 f"The build needs: {', '.join(REQUIRED)}")
    return p


def truetype(name, size, **kw):
    from PIL import ImageFont
    return ImageFont.truetype(path(name), size, **kw)


def report():
    """One line per required font: where it was found, or MISSING."""
    bad = 0
    for n in REQUIRED:
        p = find(n)
        bad += p is None
        print(f"  {n:<14} {p or 'MISSING'}")
    return bad


if __name__ == "__main__":
    sys.exit(1 if report() else 0)
