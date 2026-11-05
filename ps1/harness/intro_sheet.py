"""Contact sheet of the opening's cards from intro_run.py captures.

intro_run.py logs every payload state change to work/intro_run.txt and saves
work/intro_cue_<frame>.png 90 frames after each; per card this picks the
capture 90 frames after its first WAIT that follows a type-on (a card adopted
without a retype, INTRO_news_16b: its first frame) and tiles them, labelled
with the cue id and the card's `y`. Give two run directories (each holding an
intro_run.txt and its captures) to lay them side by side.

    python ps1/harness/intro_sheet.py work/intro_sub/before work/intro_sub/after -o work/intro_sub/before_after.png
"""
import argparse, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
from PIL import Image, ImageDraw

STEP_TYPE, STEP_WAIT = 0x800479D8, 0x80047C30


def cards(run):
    """{cue index: capture path}"""
    per = {}
    for line in open(os.path.join(run, 'intro_run.txt')):
        m = re.match(r'(\d+): magic=53554253 shown=([0-9a-f]{8}) fn=([0-9a-f]{8})', line)
        if not m:
            continue
        f, k, fn = int(m[1]), int(m[2], 16), int(m[3], 16)
        if k == 0xFFFFFFFF:
            continue
        per.setdefault(k, []).append((f, fn))
    out = {}
    for k, ev in per.items():
        pick, typed = ev[0][0], False
        for f, fn in ev:
            if fn == STEP_TYPE:
                typed = True
            elif fn == STEP_WAIT and typed:
                pick = f
                break
        p = os.path.join(run, f'intro_cue_{pick + 90:06d}.png')
        if os.path.exists(p):
            out[k] = p
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('-o', '--out', default=os.path.join(WORK, 'intro_sub', 'sheet.png'))
    args = ap.parse_args()
    cues = [c for c in json.load(open(os.path.join(ROOT, 'ps1/translation/subs_INTRO.json'), encoding='utf-8'))['cues']
            if c.get('enabled', True)]
    runs = [cards(r) for r in args.runs]
    W, H, L = 280, 240, 14
    cols = 2 if len(runs) == 1 else 1
    per_row = cols * len(runs)
    nrows = (len(cues) + cols - 1) // cols
    sheet = Image.new('RGB', (per_row * (W + 4), nrows * (H + L + 4)), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(cues):
        r, cc = divmod(i, cols)
        for j, run in enumerate(runs):
            x = (cc * len(runs) + j) * (W + 4)
            y = r * (H + L + 4)
            d.text((x + 2, y + 1), f"{c['id']}  y {c.get('y', 0)}" + ('' if len(runs) == 1 else f"  [{os.path.basename(args.runs[j])}]"),
                   fill=(255, 255, 0))
            if i in run:
                im = Image.open(run[i]).convert('RGB')
                sheet.paste(im, (x, y + L))
                if 'y' in c:                   # the safe bottom line (gen_intro.LAST_Y)
                    d.line([(x, y + L + 228), (x + im.width - 1, y + L + 228)], fill=(255, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    sheet.save(args.out)
    print(f'{len(cues)} cards, {[len(r) for r in runs]} captured -> {args.out}')


if __name__ == '__main__':
    main()
