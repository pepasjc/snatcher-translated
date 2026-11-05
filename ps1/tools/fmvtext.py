"""Replace the burned-in Japanese text in the intro FMV with English.

`STR/MX2_S000.STR` is the opening: 5,603 frames, 10 sectors each. Its text is
part of the picture, so translating it means repainting frames and re-encoding
them with jPSXdec (`-replaceframes`).

Removing the Japanese cleanly relies on one property of the sequence: within
a credit the text is *static* while the city keeps moving. So

  run median   = background(blurred by motion) + text      (text survives)
  outside plate= background only                           (text gone)
  text mask    = where those two differ

and each frame is repaired by copying the plate into the masked pixels. The
plate is built from frames on both sides of the run, far enough out that the
credit has changed but close enough that the shot has not.

English is drawn into the same bands the mask reports, centred, in the colour
sampled from the original glyphs, so the layout and palette stay the game's.

`patch_disc.py` rebuilds the image from the original, which puts the Japanese
frames back, so this has to run *after* it - the opposite of every other tool
in the chain, which run before it.

Usage:
  python fmvtext.py frames            # decode the source frames (once)
  python fmvtext.py build [name ...]  # repaint segments -> work/gfx/str/out
  python fmvtext.py xml               # write the jPSXdec replace script
  python fmvtext.py apply             # run jPSXdec against patched/
  python fmvtext.py mirror NAME       # copy the English FMV out of another
                                      # patched image (same build, different
                                      # variant) instead of re-encoding it
"""
import glob, json, os, sys
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
import sysfont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SPEC = os.path.join(ROOT, "ps1/translation", "fmv_credits.json")
WORK = os.path.join(ROOT, "work", "gfx", "str")
SRC = os.path.join(WORK, "fr", "STR")
OUT = os.path.join(WORK, "out")
XML = os.path.join(WORK, "replace.xml")
IDX = os.path.join(WORK, "snatcher.idx")
JAR = os.path.join(ROOT, "lib", "jpsxdec", "jpsxdec_v2.0", "jpsxdec.jar")
# SNATCHER_IMAGE names the image to edit, as in patch_disc.py: the release
# build makes one image per variant (censored / uncensored) and the FMV is
# encoded once and mirrored into the other.
_IMG = os.environ.get("SNATCHER_IMAGE", "Snatcher (Japan)")
DISC = os.path.join(ROOT, "patched", _IMG + ".bin")
# Tamzen 6x12 bold (lib/bdffont.py), the dialogue's face, for segments at
# the default 12 px; a segment with another "size" keeps MS Gothic at that
# size (none does as of 0.9.2).
FONT = "msgothic.ttc"

DECODE_RANGE = (2300, 4700)        # frames worth decoding: caption + credits


def spec():
    d = json.load(open(SPEC, encoding="utf-8"))
    return [s for s in d["segments"] if not s.get("skip")]


def frame_path(n):
    return os.path.join(SRC, f"MX2_S000.STR[0][#{n:04d}].png")   # jPSXdec pads to 4


def decode_frames():
    ensure_index()          # a fresh checkout has none (the movie is the pristine one before apply)
    os.makedirs(os.path.join(WORK, "fr"), exist_ok=True)
    # every frame a segment reads: its run, plus the plate's pad either side
    # (the disclaimer still sits at 2-150, far before the credits)
    spans = sorted((max(0, s["frames"][0] - (0 if s.get("static") else s.get("pad", 60))),
                    s["frames"][1] + (0 if s.get("static") else s.get("pad", 60))) for s in spec())
    ranges = []
    for lo, hi in spans:
        if ranges and lo <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])
    item = find_item()
    for lo, hi in ranges:
        if all(os.path.exists(frame_path(n)) for n in range(lo, hi + 1)):
            continue
        cmd = (f'java -jar "{JAR}" -x "{IDX}" -i {item} -start {lo} -end {hi} '
               f'-vidfmt png -num Header -noaud -dir "{os.path.join(WORK, "fr")}"')
        print(cmd)
        os.system(cmd)


def _stack(nums):
    import numpy as np
    from PIL import Image
    return np.stack([np.array(Image.open(frame_path(n)).convert("RGB"), np.uint8)
                     for n in nums if os.path.exists(frame_path(n))])


def _median(nums):
    import numpy as np
    return np.median(_stack(nums), axis=0).astype(np.uint8)


def _plate(nums, pct=20):
    """Background estimate: a low percentile, which drops the bright glyphs.

    A median plate fails here because the credits come every ~100 frames at
    the same screen rows, so a window wide enough to span the gaps also spans
    the neighbouring credit and keeps its text.
    """
    import numpy as np
    return np.percentile(_stack(nums), pct, axis=0).astype(np.uint8)


# The credits use four layouts, all on a 32px pitch. Measured off the run
# medians rather than inferred: every generic detector (difference against a
# plate, blob shape, top-hat, temporal variance) keys on the dense cityscape
# instead of the dimmer text.
ROWS = {
    1: [(120, 138)],
    2: [(88, 106), (120, 138)],
    3: [(88, 106), (120, 138), (152, 170)],
    4: [(56, 74), (88, 106), (136, 154), (168, 186)],
}
COLS = (34, 290)   # wide enough for the longest Japanese line; a narrower
                   # window left the last glyph of 小松原里枝子 on screen


def analyse(seg):
    """(run median, mask, bands, frames) for one credit.

    Frames: the run is located by "bright and holding still" against a median
    plate straddling it, which gets the start and end right even though the
    same test cannot find the rows.

    Mask: inside the declared rows only, the glyphs are simply the brightest
    pixels of the run median - the median having already dissolved the moving
    lights and beams.
    """
    import numpy as np
    from scipy import ndimage
    a, b = seg["frames"]
    bands_decl = [tuple(r) for r in seg["rows"]] if seg.get("rows") else None
    if seg.get("static"):
        # Text that never blinks - the disclaimer still - defeats the "bright
        # and holding still against a plate" test, because the plate holds the
        # text too. Take the declared frames as the run.
        frames = [n for n in range(a, b + 1) if os.path.exists(frame_path(n))]
        run = np.median(_stack(frames).astype(np.float32), axis=0)
        bands = bands_decl or ROWS[len(seg["lines"])]
        x0, x1 = COLS
        mask = np.zeros(run.shape[:2], bool)
        for (y0, y1) in bands:
            band = run[y0:y1, x0:x1].mean(2)
            cut = np.percentile(band, seg.get("ink_pct", 60))
            m = band > max(cut, band.mean() + 6)
            mask[y0:y1, x0:x1] = ndimage.binary_dilation(
                m, np.ones((3, 3), bool), iterations=seg.get("grow", 2))
        return run, mask, bands, frames

    pad = seg.get("pad", 60)
    window = [n for n in range(a - pad, b + pad + 1) if os.path.exists(frame_path(n))]
    st = _stack(window).astype(np.int16)
    plate = np.percentile(st, 50, axis=0)
    grey = st.mean(3)
    pg = plate.mean(2)
    lift = (grey - grey.mean(axis=(1, 2), keepdims=True)) - (pg - pg.mean())
    hold = seg.get("hold", 5)
    steady = np.stack([lift[i:i + hold].min(0) for i in range(len(st) - hold + 1)])
    idx = {n: i for i, n in enumerate(window)}

    bands = [tuple(r) for r in seg["rows"]] if seg.get("rows") else ROWS[len(seg["lines"])]
    x0, x1 = COLS
    inner = [n for n in range(a, b + 1) if n in idx and idx[n] < len(steady)]
    area = np.array([sum(int((steady[idx[n]][y0:y1, x0:x1] > 20).sum())
                         for y0, y1 in bands) for n in inner])
    if not len(area) or area.max() < 30:
        return None, None, bands, []
    live = [n for n, v in zip(inner, area) if v > area.max() * 0.3]
    frames = list(range(min(live), max(live) + hold))

    run = np.median(_stack(live).astype(np.float32), axis=0)
    mask = np.zeros(run.shape[:2], bool)
    for (y0, y1) in bands:
        band = run[y0:y1, x0:x1].mean(2)
        cut = np.percentile(band, seg.get("ink_pct", 76))
        m = band > max(cut, band.mean() + 6)
        mask[y0:y1, x0:x1] = ndimage.binary_dilation(
            m, np.ones((3, 3), bool), iterations=seg.get("grow", 2))
    return run, mask, bands, frames


def repaint(seg, run, mask, bands, frames):
    """Inpaint the Japanese away frame by frame, then draw the English."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    import bdffont
    size = seg.get("size", 12)
    font = sysfont.truetype(FONT, size) if size != 12 else None
    tam = bdffont.load(bdffont.DIALOGUE)
    os.makedirs(OUT, exist_ok=True)
    m8 = mask.astype(np.uint8)
    x0, x1 = COLS
    colours = []
    for (y0, y1) in bands:
        px = run[y0:y1, x0:x1][mask[y0:y1, x0:x1]]
        colours.append(np.percentile(px, 80, axis=0) if len(px) else np.array([200, 200, 255]))
    written = []
    for n in frames:
        p = frame_path(n)
        if not os.path.exists(p):
            continue
        src = np.array(Image.open(p).convert("RGB"), np.uint8)
        if seg.get("flat"):
            # Flat backdrop (the red disclaimer): take the surrounding colour
            # straight, which is exact where inpainting leaves faint smudges.
            fixed_rgb = src.copy()
            for (y0, y1) in bands:
                strip = src[y0:y1]
                sm = mask[y0:y1]
                if sm.any() and (~sm).any():
                    fixed_rgb[y0:y1][sm] = np.median(strip[~sm], axis=0).astype(np.uint8)
            im = Image.fromarray(fixed_rgb)
            fixed = cv2.cvtColor(fixed_rgb, cv2.COLOR_RGB2BGR)
        else:
            # Repair from the same frame: the camera drifts through the
            # sequence, so pixels borrowed from other frames never line up.
            fixed = cv2.inpaint(cv2.cvtColor(src, cv2.COLOR_RGB2BGR), m8, 3,
                                cv2.INPAINT_TELEA)
            im = Image.fromarray(cv2.cvtColor(fixed, cv2.COLOR_BGR2RGB))
        dr = ImageDraw.Draw(im)
        lift = float((src[mask].astype(int).mean() - fixed[:, :, ::-1][mask].astype(int).mean()))
        base = float((run[mask].mean() - np.array(im)[mask].mean())) or 1.0
        fade = min(1.0, max(0.15, lift / base)) if base > 1 else 1.0
        for (y0, y1), text, col in zip(bands, seg["lines"], colours):
            if not text:
                continue
            ink = tuple(int(c * fade) for c in col)
            if font is not None:
                w = dr.textlength(text, font=font)
                dr.text(((im.width - w) // 2, y0 + 1), text, fill=ink, font=font)
                continue
            # Top row y0+3: the letters stand where MS Gothic 12 drawn at
            # y0+1 had them.
            m = tam.render(text)
            x = (im.width - m.shape[1]) // 2
            for yy, xx in zip(*np.nonzero(m)):
                if 0 <= y0 + 3 + yy < im.height and 0 <= x + xx < im.width:
                    im.putpixel((int(x + xx), int(y0 + 3 + yy)), ink)
        dst = os.path.join(OUT, f"{n:05d}.png")
        im.save(dst)
        written.append(n)
    return written


def build(names=None):
    done = {}
    for seg in spec():
        if names and seg["name"] not in names:
            continue
        run, mask, bands, frames = analyse(seg)
        if not frames:
            print(f"  SKIP {seg['name']}: no run found in {seg['frames']}")
            continue
        print(f"{seg['name']}: {frames[0]}-{frames[-1]} ({len(frames)}f), "
              f"mask {int(mask.sum())}px, {len(bands)} row(s)")
        done[seg["name"]] = repaint(seg, run, mask, bands, frames)
    total = sum(len(v) for v in done.values())
    print(f"wrote {total} frame(s) to {OUT}")


def write_xml():
    frames = sorted(int(os.path.basename(p)[:-4]) for p in glob.glob(os.path.join(OUT, "*.png")))
    with open(XML, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n<str-replace version="0.3">\n')
        for n in frames:
            # No format attribute: that one is only for pre-encoded `bs`/`mdec`
            # streams, and naming it for an image makes jPSXdec reject the file.
            #
            # size-limit is essential. jPSXdec only ensures a re-encoded frame
            # fits its sector allocation (~23KB over 10 sectors), but the game
            # sizes its own frame buffer from the largest frame on the disc -
            # 16,128 bytes here. Without the cap 851 frames came back bigger,
            # up to 18,072, and the game hung at New Game on mednafen and
            # no$psx while DuckStation limped on.
            f.write(f'    <replace frame="{n}" size-limit="original non-zero">'
                    f'{os.path.join(OUT, f"{n:05d}.png")}</replace>\n')
        f.write("</str-replace>\n")
    print(f"{XML}: {len(frames)} frame(s)")


def find_item(want="STR/MX2_S000.STR[0]"):
    """The index number jPSXdec gave MX2_S000.STR's video, read from the index.

    Item numbers are NOT stable across images: they are assigned in the order
    jPSXdec detects items, and a build whose appended area holds different
    data detects a different number of them. A freshly built v0.8 image put
    the video at 1951 and the XA audio at 1952, so the hard-coded 1952 made
    jPSXdec answer "Disc item is not a standard STR video" and replace
    nothing - a silently Japanese intro movie.
    """
    for line in open(IDX, encoding="utf-8", errors="replace"):
        if f"|ID:{want}|" in line and "|Type:Video|" in line:
            return line.split("|", 1)[0].split(":")[1]
    sys.exit(f"{want} not found in {IDX} - delete the index and rerun")


def fmv_is_english():
    """True when the image's MX2_S000.STR differs from the pristine disc's."""
    lba, size = json.load(open(os.path.join(ROOT, "work", "lba_map.json")))["MX2_S000.STR"]
    off, span = lba * 2352, ((size + 2047) // 2048) * 2352
    src = os.path.join(ROOT, "discs/iso_ps1_jp", "Snatcher (Japan).bin")
    with open(src, "rb") as fa, open(DISC, "rb") as fb:
        fa.seek(off); fb.seek(off)
        left = span
        while left:
            n = min(1 << 22, left)
            if fa.read(n) != fb.read(n):
                return True
            left -= n
    return False


def ensure_index():
    """jPSXdec needs an index of the disc; rebuild it if absent or stale.

    The index records the sector count and jPSXdec refuses one that does not
    match the image ("Serialized sector count 243945 does not match actual
    244165") - which happens whenever repoint/subs_cue relocate another bank
    past the image end. The image size is stamped beside the index.
    """
    stamp = IDX + ".size"
    # The image path belongs in the stamp too: the variant images have the
    # same sector count, so a size alone would hand one image's index to the
    # other and jPSXdec would happily write frames into the wrong file.
    size = f"{DISC}|{os.path.getsize(DISC)}"
    if os.path.exists(IDX) and os.path.exists(stamp) and open(stamp).read() == size:
        return
    os.makedirs(os.path.dirname(IDX), exist_ok=True)
    if os.path.exists(IDX):
        os.remove(IDX)
    os.system(f'java -jar "{JAR}" -f "{DISC}" -x "{IDX}"')
    open(stamp, "w").write(size)


def apply():
    ensure_index()
    write_xml()
    item = find_item()
    cmd = (f'java -jar "{JAR}" -x "{IDX}" -i {item} -replaceframes "{XML}"')
    print(cmd)
    os.system(cmd)
    # jPSXdec exits 0 even when it replaced nothing ("Disc item is not a
    # standard STR video"), so the image itself is the check.
    if not fmv_is_english():
        sys.exit("fmvtext: MX2_S000.STR still matches the pristine disc - "
                 "nothing was replaced")
    print(f"MX2_S000.STR replaced (item {item})")


def mirror(src_name):
    """Copy MX2_S000.STR's sectors from another patched image into DISC.

    jPSXdec's replace touches nothing but that one file's sectors, so a
    variant image built from the same run is byte-identical outside it -
    copying the extent is the same result as a second encode of 1,829
    frames, in seconds instead of minutes.
    """
    src = os.path.join(ROOT, "patched", src_name + ".bin")
    lba, size = json.load(open(os.path.join(ROOT, "work", "lba_map.json")))["MX2_S000.STR"]
    nsec = (size + 2047) // 2048
    off, span = lba * 2352, nsec * 2352
    for path in (src, DISC):
        if not os.path.exists(path):
            sys.exit(f"missing image: {path}")
        if os.path.getsize(path) < off + span:
            sys.exit(f"image too short for MX2_S000.STR: {path}")
    with open(src, "rb") as fs, open(DISC, "r+b") as fd:
        fs.seek(off)
        fd.seek(off)
        left, same = span, True
        while left:
            chunk = fs.read(min(1 << 22, left))
            here = fd.tell()
            if same and fd.read(len(chunk)) != chunk:
                same = False
            fd.seek(here)
            fd.write(chunk)
            left -= len(chunk)
    print(f"mirrored MX2_S000.STR ({nsec} sectors) from {src_name}"
          + (" (already identical)" if same else ""))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "frames":
        decode_frames()
    elif cmd == "build":
        build(sys.argv[2:] or None)
    elif cmd == "xml":
        write_xml()
    elif cmd == "apply":
        apply()
    elif cmd == "mirror":
        mirror(sys.argv[2])
    else:
        sys.exit(__doc__)
