"""A translation splash card at the end of the Konami logo movie.

`STR/MX0_S000.STR` (jPSXdec item 1943) is the boot movie: 168 frames at
15 fps, 320x240 - the Konami emblem animates in (1-94), sits static on
white (95-153) and fades to black (154-166) before the title. The static
tail is longer than it needs to be, so the logo keeps 1.6 s of it and the
rest becomes our card: a short cross-fade from the emblem (119-124), the
card (125-153), and the original's fade-to-black curve applied to the card
(154-166) so the cut to the title feels the same.

Frames are re-encoded with jPSXdec `-replaceframes` against the patched
image, like fmvtext.py, so this runs AFTER patch_disc.py (which puts the
original movie back).

    python ps1/tools/splash.py preview     # work/splash_preview.png
    python ps1/tools/splash.py apply       # frames -> XML -> jPSXdec on patched/
"""
import glob, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import sysfont

WORK = os.path.join(ROOT, "work", "gfx", "str")
IDX = os.path.join(WORK, "snatcher.idx")
JAR = os.path.join(ROOT, "lib", "jpsxdec", "jpsxdec_v2.0", "jpsxdec.jar")
OUT = os.path.join(WORK, "splash")
XML = os.path.join(WORK, "splash.xml")
ITEM = "1943"                          # STR/MX0_S000.STR[0]
LOGO_FRAMES = os.path.join(WORK, "mx0")   # decoded originals (for the cross-fade)

TITLE = "PEPA SOFT HOUSE"
VERSION = open(os.path.join(ROOT, "VERSION")).read().strip()   # one place: the BAT reads it too
SUB = f"ENGLISH TRANSLATION  v{VERSION}  ·  2026"
FONT = ("impact.ttf", 26)
SUBFONT = ("arialbd.ttf", 11)
W, H = 320, 240
CROSS = range(119, 125)                # emblem -> card
HOLD = range(125, 154)                 # the card
FADE = range(154, 165)                 # to black, the movie's own curve; 165-166 are
                                       # already (near) black in the original and one of
                                       # them jPSXdec cannot re-encode ("Can't decode a
                                       # frame we just encoded")
LAST_LOGO = 118                        # last untouched emblem frame


def card():
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = sysfont.truetype(*FONT)
    bb = d.textbbox((0, 0), TITLE, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    cx, cy = W // 2, H // 2 - 6
    bar_w = tw + 24
    d.rectangle([cx - bar_w // 2, cy - th // 2 - 14, cx + bar_w // 2, cy - th // 2 - 10], fill=(0, 0, 0))
    d.rectangle([cx - bar_w // 2, cy + th // 2 + 10, cx + bar_w // 2, cy + th // 2 + 14], fill=(0, 0, 0))
    d.text((cx - tw // 2 - bb[0], cy - th // 2 - bb[1]), TITLE, font=f, fill=(0, 0, 0))
    fs = sysfont.truetype(*SUBFONT)
    sb = d.textbbox((0, 0), SUB, font=fs)
    d.text((cx - (sb[2] - sb[0]) // 2 - sb[0], cy + th // 2 + 22 - sb[1]), SUB, font=fs, fill=(90, 90, 90))
    return im


def logo_frames():
    fs = sorted(glob.glob(os.path.join(LOGO_FRAMES, "**", "*.png"), recursive=True))
    if len(fs) < 166:
        os.makedirs(LOGO_FRAMES, exist_ok=True)
        os.system(f'java -jar "{JAR}" -x "{IDX}" -i {ITEM} -start 1 -end 168 -vf png -quality high '
                  f'-dir "{LOGO_FRAMES}" > nul')
        fs = sorted(glob.glob(os.path.join(LOGO_FRAMES, "**", "*.png"), recursive=True))
    return {i + 1: p for i, p in enumerate(fs)}


def build():
    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(os.path.join(OUT, "*.png")):
        os.remove(old)
    src = logo_frames()
    base = np.asarray(card()).astype(np.float32)
    logo = np.asarray(Image.open(src[LAST_LOGO]).convert("RGB")).astype(np.float32)
    # the movie's own fade: brightness of each original fade frame relative
    # to the last static one
    ref = np.asarray(Image.open(src[153]).convert("L")).astype(np.float32).mean()
    for n in CROSS:
        t = (n - CROSS.start + 1) / (len(CROSS) + 1)
        Image.fromarray((logo * (1 - t) + base * t).astype(np.uint8)).save(os.path.join(OUT, f"{n:05d}.png"))
    for n in HOLD:
        Image.fromarray(base.astype(np.uint8)).save(os.path.join(OUT, f"{n:05d}.png"))
    for n in FADE:
        k = np.asarray(Image.open(src[n]).convert("L")).astype(np.float32).mean() / ref
        Image.fromarray((base * k).astype(np.uint8)).save(os.path.join(OUT, f"{n:05d}.png"))
    print(f"{OUT}: {len(CROSS) + len(HOLD) + len(FADE)} frames")


def write_xml():
    frames = sorted(int(os.path.basename(p)[:-4]) for p in glob.glob(os.path.join(OUT, "*.png")))
    with open(XML, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n<str-replace version="0.3">\n')
        for n in frames:
            f.write(f'    <replace frame="{n}" size-limit="original non-zero">'
                    f'{os.path.join(OUT, f"{n:05d}.png")}</replace>\n')
        f.write("</str-replace>\n")


def preview():
    card().resize((640, 480), Image.NEAREST).save(os.path.join(ROOT, "work", "splash_preview.png"))
    print("work/splash_preview.png")


def apply():
    import fmvtext
    fmvtext.ensure_index()
    build()
    write_xml()
    cmd = f'java -jar "{JAR}" -x "{IDX}" -i {ITEM} -replaceframes "{XML}"'
    print(cmd)
    os.system(cmd)


if __name__ == "__main__":
    {"preview": preview, "build": build, "apply": apply}[sys.argv[1] if len(sys.argv) > 1 else "preview"]()
