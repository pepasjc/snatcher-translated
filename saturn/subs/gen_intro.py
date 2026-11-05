"""The Saturn opening's cue file: the PS1's 24 opening cards, re-timed onto the Saturn reels.

The opening plays two streamed stereo reels (30 kHz 16-bit SDAIFs) with no scene bank of
its own - B000 (chunk 21, ctx+0x54A = 0) is the bank in RAM from the title to B010:

    PS1 XAS_S000.XA[129] (file 2 chan 2)  -> SDAIF_E0.AIF = reel 140   the newsreel narration
    PS1 XAS_S000.XA[162] (file 3 chan 1)  -> SDAIF_E1.AIF = reel 141   the roll + Gillian's profile

(work/saturn/cat/reel_map.json: envelope match 0.999 / 1.000). The English is the PS1's
ps1/translation/subs_INTRO.json verbatim, card for card (INTRO_news_16 / 16b stay two cues:
the PS1 split the card at its baked diagram still; here they carry the same text and the
open card is simply rewritten in place).

Timing: the PS1 cue window (absolute sectors) -> seconds from the stream's first sector
(master_lines.json `dur` over the sector span; the PS1's own windows are sentence spans
from a word-timestamp pass, work/intro_words.json in the PS1 tree) -> Saturn seconds by
reelalign.py's audio fit `saturn_t = a * ps1_t + b` (RMS envelopes cross-correlated: both
reels a = 1, b = 0 - the same recording, corr 0.998 / 1.000, work/saturn/cat/
reel_align.json) -> + LAG_S (the counter leads the speakers by ~10 frames) -> file bytes = 54
(SSND data) + frames x 4 (the COMM chunk). The payload
keys a reel cue on the stream number (u16 0x060EFE6A) and the file bytes played (u32
0x060EFF0C), as for every other reel (gen_subs.py).

Position (`y`, the open box's y = how far below row 0's usual place the rows sit): from
intro_run.py --measure (the pristine opening, no card of ours on screen): the lowest non-black
row of the picture over every frame the card is up (b0 .. the next card or b1 + the linger),
the rows placed MARGIN px under it if they fit above LAST_Y, else as low as they fit
(`over` true = the rows still cross the picture: the full-screen boards). The box frame's
VDP2 fill moves with the box, so the dark band follows the rows.

Layout: no speaker, so the plain box with no nameplate: `rows` rows of `cols` cells from row
`row0` (the blob's `pcols`/`ptext0` words, satsubs.py); the box holds the last card `linger`
frames for the next and object 0 draws at priority `prio` while a card is up. As the PS1's
opening: no frame (`frame` false - the cells without the 8 gold box pieces, the box's VDP2
fill left as a dark translucent band behind the rows) and no slide (`slide` 128 = one frame).

    python saturn/subs/gen_intro.py            -> saturn/translation/subs_INTRO.json
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]

import gen_subs

PS1_INTRO = os.path.join(ROOT, "ps1", "translation", "subs_INTRO.json")
OUT = os.path.join(ROOT, "saturn", "translation", "subs_INTRO.json")
ALIGN = os.path.join(WORK, "saturn", "cat", "reel_align.json")
COLS, ROWS = 20, 3                  # full-width rows, at most three (the PS1's three), from row 0
PICTURE_ROWS = os.path.join(WORK, "saturn", "intro_sub", "picture_rows.json")   # intro_run.py --measure
ROW0_Y, ROW_H = 158, 14             # row 0's cell top at box y 0 (the cell records' y 0x9E), 14-px cells
LAST_Y = 224                        # the last row's cell bottom stays inside 224 lines (the MiSTer's picture)
MARGIN = 3                          # px of black between the picture's lowest row and the text
LINGER_BYTES = 240000               # the box holds a card LINGER frames past b1: 2 s of the 120,000 B/s stream
LINGER = 120                        # frames the open box holds the last card for the next (the narration's
                                    #   pauses run to 1.6 s; the stock 60 closed and re-opened the box in them)
LAG_S = 0.167                       # the stream counter runs ~10 frames AHEAD of the speakers (work/saturn/
                                    #   intro_sub/latency.py: the core's audio output envelope against SDAIF_E0
                                    #   at the counter's position, best lag 10 frames, corr 0.83): a card whose
                                    #   words play at file time t shows when the counter reads t + LAG_S
PRIO = 31                           # object 0's draw priority while a card is up: the boards' own sprites
                                    #   run at 30/31, over the box's 28 (satsubs.py `oprio`)
STREAMS = {(2, 2): "XAS_S000.XA[129]", (3, 1): "XAS_S000.XA[162]"}


def place(cues):
    """Each cue's `y` (and `pic_bottom`, `over`) from the measured picture rows."""
    meas = json.load(open(PICTURE_ROWS))["frames"]
    for i, q in enumerate(cues):
        nxt = next((c["b0"] for c in cues[i + 1:] if c["reel"] == q["reel"]), None)
        end = q["b1"] + LINGER_BYTES if nxt is None else min(nxt, q["b1"] + LINGER_BYTES)
        span = [r for f, reel, pos, r in meas if reel == q["reel"] and q["b0"] <= pos < end]
        assert span, q["id"]
        bottom = max(span)
        n = len(q["rows"])
        y_max = LAST_Y - ROW0_Y - ROW_H * n
        want = max(0, bottom + 1 + MARGIN - ROW0_Y)
        q["pic_bottom"], q["y"], q["over"] = bottom, min(want, y_max), want > y_max


def main():
    src = json.load(open(PS1_INTRO, encoding="utf-8"))
    ml = {m["key"]: m for m in json.load(open(gen_subs.MASTER, encoding="utf-8"))}
    reels = {r["ps1"]: r for r in json.load(open(gen_subs.REEL_MAP))}
    aligned = json.load(open(ALIGN))
    pf = gen_subs.pair_font()
    cues, align = [], {}
    for c in src["cues"]:
        if not c.get("enabled", True):
            continue
        key = STREAMS[(c["file"], c["chan"])]
        st, r = ml[key], reels[key]
        al = aligned[key]                        # reelalign.py must have run on reels 140/141
        align[r["sdaif"]] = {"ps1": key, "a": al["a"], "b": al["b"], "corr": al["corr"]}
        frames, rate, ch, bpf = gen_subs.aiff_info(os.path.join(gen_subs.SDAIF_DIR, r["sdaif"]))
        span = st["end"] - st["start"]
        t0 = al["a"] * (c["start"] - st["start"]) / span * st["dur"] + al["b"]
        t1 = al["a"] * (c["end"] - st["start"]) / span * st["dur"] + al["b"]
        fr0, fr1 = (min(frames, max(0, int((t + LAG_S) * rate))) for t in (t0, t1))
        assert fr0 < fr1, c["id"]
        cues.append({
            "id": c["id"], "reel": r["n"], "sdaif": r["sdaif"], "rate": rate, "frames": frames,
            "t0": round(t0, 2), "t1": round(t1, 2),
            "b0": gen_subs.SSND_DATA + fr0 * bpf, "b1": gen_subs.SSND_DATA + fr1 * bpf,
            "size": gen_subs.SSND_DATA + frames * bpf,
            "speaker": "", "colour": 7, "en": c["en"], "rows": gen_subs.wrap(pf, c["en"], COLS, ROWS),
            "enabled": True,
        })
    place(cues)
    out = {"scene": "INTRO", "options": {"layout": "plain", "cols": COLS, "rows": ROWS, "row0": 0, "cue_y": True,
                                         "linger": LINGER, "prio": PRIO, "lag_s": LAG_S,
                                         "frame": False, "slide": 128,
                                         "bank": "B000", "chunk": 21, "scene_var": 0,
                                         "timing": "PS1 sector window -> seconds (master_lines dur) -> reelalign fit -> SSND bytes",
                                         "align": align},
           "cues": cues}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"INTRO: {len(cues)} cues -> {OUT}")
    for q in cues:
        print(f"  {q['id']:17} reel {q['reel']} {q['t0']:7.2f}-{q['t1']:7.2f}s  picture to {q['pic_bottom']:3} "
              f"y {q['y']:2} rows {ROW0_Y + q['y']}..{ROW0_Y + q['y'] + ROW_H * len(q['rows'])}{'  OVER' if q['over'] else ''}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
