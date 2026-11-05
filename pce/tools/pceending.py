"""The ending's credit roll in English (rec 130, the ending's code file).

The roll is a table of 409 line pointers at file 0x051d (u16, $8000-based,
`ff ff` after the last) that the code walks one row at a time: most point
at the blank line (0x0851), the rest at ready-decoded message lines - 14
cells of Shift-JIS, a role wrapped in `fe 02` / `fe 01` (its colour), a
`20` for a half-cell of centring, `ff` at the end. No decoder runs, so the
English is written the way the row renderer reads it: pair codes (two
letters a cell, `pcescript.label_bytes`), centred in the 14 cells, and the
pointers moved to the new lines. The glyph hook composes pairs while the
module window's ALL_EN byte is set, which pcescript gives the ending's
text-less module (670) along with the font.

Lines are rewritten into the region the old ones held (0x0851..0x14c0) and
the file's free tail (0x1580..0x1800). Three lines of JIS level-2 codes
(个仍仄仆仆仆...) are the Konami logo drawn as the roll's own tiles and are
copied as they are (the hook leaves row 0x98 from 0x9F up alone). A name
that needs two rows takes the blank slot after its own. Every English row
opens with `f9 81`: the roll's own prefix selects the 16x16 BIOS font (`f9
80`, 16-px cells), the pair glyphs are drawn for the 12x12 one.

The epilogue over the sunset before the roll is a tile picture (pcecards.py);
the same three lines also sit as dialogue-codec strings after the airport
scene's voiced lines in a text-only sector no file-table record names
(648 and 672, identical) - the game shows neither, so they stay.

  python pce/tools/pceending.py show     # the roll's rows, before and after
  python pce/tools/pceending.py apply    # into patched/pce/snatcher_pce.bin
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import patch_pce as P
import pcescene as S
import pcescript as PS
import pcepair

BLOCK = (130, 3)
BASE = 0x8000                 # the file's load address
TABLE = 0x051D                # the pointer table, `ff ff` terminated
LINES = (0x0851, 0x14C0)      # the old lines
TAIL = (0x1580, 0x1800)       # free bytes at the file's end
BLANK = 0x0851
COLS = 14                     # the Japanese rows: 14 cells of 16 px from x 8
PAD = bytes([0x81, 0x40])     # a fullwidth space
HALF = bytes([0x20])          # half a cell
# `f9 xx` sets the renderer's font: the roll's own prefix says 80 (the 16x16
# BIOS font, 16-px cells), so an English row opens with 81 (12x12, 12-px
# cells - the dialogue's, which the pair glyphs are drawn for). Its cells
# start at x 12 (column 1 of the row = one half cell): 17 of them span
# 12..216, centred 6 px left of the Japanese rows (8..232), which is what
# the file's bytes allow. The roll draws into four VRAM row buffers in
# turn, so a row whose buffer last held a 16-px row (the logos) and no
# blank line since gets 19 cells (12..240) to clear the logo's right edge.
FONT12 = bytes([0xF9, 0x81])
COLS12 = 17
COLS12_WIDE = 19

# Japanese line (padding stripped) -> English; a list is one row per slot,
# the second taking the blank slot that follows; None keeps the bytes
ENGLISH = {
    "出演": "CAST",
    "企画": "PLANNING",
    "原作　脚本": "ORIGINAL STORY & SCRIPT",
    "助監督": "ASSISTANT DIRECTOR",
    "キャラクターデザイン": "CHARACTER DESIGN",
    "メカニックデザイン": "MECHANICAL DESIGN",
    "原画": "ORIGINAL ART",
    "ＣＧ監督": "CG DIRECTOR",
    "グラフィック": "GRAPHICS",
    "音声動画シンクロ": "AUDIO & VIDEO SYNC",
    "シナリオコンパイラ": "SCENARIO COMPILER",
    "コマンドインタプリタ": "COMMAND INTERPRETER",
    "シナリオ構成": "SCENARIO COMPOSITION",
    "演出": "DIRECTION",
    "演出助手": "DIRECTION ASSISTANT",
    "プログラム": "PROGRAM",
    "射撃プログラム": "SHOOTING PROGRAM",
    "サウンドプログラム": "SOUND PROGRAM",
    "ＣＤシステム設計": "CD SYSTEM DESIGN",
    "システムアドバイザー": "SYSTEM ADVISER",
    "音楽": "MUSIC",
    "音響": "SOUND",
    "音声リニア編集": "AUDIO LINEAR EDITING",
    "サウンド監督": "SOUND DIRECTOR",
    "録音": "RECORDING",
    "ミキサー": "MIXER",
    "音声コーディネート": "VOICE COORDINATION",
    "レコーディング協力": "RECORDING COOPERATION",
    "録音演出": "RECORDING DIRECTION",
    "スチール": "STILLS",
    "広報": "PUBLICITY",
    "ポスターイラスト": "POSTER ILLUSTRATION",
    "パッケージ": "PACKAGE",
    "イラストカット": "ILLUSTRATIONS",
    "コミック着色": "COMIC COLOURING",
    "マニュアル": "MANUAL",
    "メイキングビデオ": "MAKING-OF VIDEO",
    "協力": "COOPERATION",
    "プロデュース": "PRODUCER",
    "監督": "DIRECTOR",
    "製作　著作": "PRODUCED BY",
    "屋良有作": "Yusaku Yara",
    "小山茉美": "Mami Koyama",
    "井上喜久子": "Kikuko Inoue",
    "塩沢兼人": "Kaneto Shiozawa",
    "冨永みーな": "Mina Tominaga",
    "槐柳二": "Ryuji Saikachi",
    "井ノ口勲": "Isao Inokuchi",
    "納屋悟郎": "Goro Naya",
    "小島秀夫": "Hideo Kojima",
    "井上慎也": "Shinya Inoue",
    "木下富晴": "Tomiharu Kinoshita",
    "大田良彦": "Yoshihiko Ota",
    "吉岡さとし": "Satoshi Yoshioka",
    "マサール石井": "Masaru Ishii",
    "足立敏哉": "Toshiya Adachi",
    "松花賢和": "Yoshikazu Matsuhana",
    "篠原憲二": "Kenji Shinohara",
    "村岡一樹": "Kazuki Muraoka",
    "橋本和久": "Kazuhisa Hashimoto",
    "古川もとあき": "Motoaki Furukawa",
    "（矩形波倶楽部）": "(Kukeiha Club)",
    "ＩＫＡｃｈａｎ": "IKAchan",
    "プロフェット深見": "Prophet Fukami",
    "ＩＺＵＭＩ": "IZUMI",
    "<f982>アバコクリエイティブスタジオ<f980>": "Avaco Creative Studio",
    "<878a><f982>アバコクリエイティブスタジオ<f980>": "Avaco Creative Studio Co.",
    "阿部幸男": "Yukio Abe",
    "野崎貴美子": "Kimiko Nozaki",
    "<878a>サムスィング": "Something Co.",
    "千崎一義": "Kazuyoshi Senzaki",
    "<f982>（ミュージカルステーション）<f980>": "(Musical Station)",
    "伊東敏夫": "Toshio Ito",
    "<878b>伊東スタジオ": "Ito Studio Ltd.",
    "松田　宏": "Hiroshi Matsuda",
    "永田昭彦": "Akihiko Nagata",
    "早坂妙子": "Taeko Hayasaka",
    "開田祐治": "Yuji Kaida",
    "増田正紀": "Masaki Masuda",
    "山田善朗": "Yoshiro Yamada",
    "福武　茂": "Shigeru Fukutake",
    "坂元信也": "Shinya Sakamoto",
    "岡村憲明": "Noriaki Okamura",
    "立石一博": "Kazuhiro Tateishi",
    "古川敏治": "Toshiharu Furukawa",
    "島　健二": "Kenji Shima",
    "棚橋正顕": "Masaaki Tanahashi",
    "池田孝治": "Koji Ikeda",
    "田村重幸": "Shigeyuki Tamura",
    "山下　章": "Akira Yamashita",
    "コナミ技術研究所": ["Konami Technical", "Research Institute"],
    "コナミ株式会社": "Konami Co., Ltd.",
    "个仍仄仆仆仆": None,            # the Konami logo, three rows of the
    "仂仗仞仭仟价伉": None,          # roll's own tiles under level-2 codes
    "佚估佛佝佗佇佶": None,
}


def pointers(blk):
    """The roll's pointer table as file offsets."""
    out, p = [], TABLE
    while blk[p:p + 2] != bytes([0xFF, 0xFF]):
        out.append((blk[p] | blk[p + 1] << 8) - BASE)
        p += 2
    return out


def parse(blk, off):
    """(role?, text with tags, end offset) of the line at `off`."""
    p, role, out = off, False, ""
    while blk[p] != 0xFF:
        b = blk[p]
        if b == 0xFE:
            if blk[p + 1] == 2:
                role = True
            p += 2
        elif b == 0xF9 or b == 0x87:
            out += f"<{b:02x}{blk[p + 1]:02x}>"
            p += 2
        elif b == 0x20:
            p += 1
        else:
            out += blk[p:p + 2].decode("cp932")
            p += 2
    return role, out.strip("　"), p + 1


def line_bytes(en, role, cols=COLS12):
    """A centred row of pair codes in the 12-px font, in the roll's format."""
    cells = len(pcepair.split(en))
    if cells > COLS:
        sys.exit(f"{en!r}: {cells} cells, the row holds {COLS}")
    body = PS.label_bytes(en)
    left = (cols - cells) // 2
    out = HALF if (cols - cells) % 2 else b""
    out += PAD * left + body + PAD * (cols - cells - left)
    if role:
        out = bytes([0xFE, 0x02]) + out + bytes([0xFE, 0x01])
    return FONT12 + out + bytes([0xFF])


def build(blk):
    """(new pointer list, {offset: bytes} of new lines)."""
    ptrs = pointers(blk)
    old = {}
    for off in ptrs:
        if off not in old and off != BLANK:
            old[off] = parse(blk, off)
    new_lines, place = {}, {}        # bytes -> offset
    free = [list(LINES), list(TAIL)]
    free[0][0] = BLANK + len(blk[BLANK:blk.index(0xFF, BLANK) + 1])   # the blank line stays

    def put(data):
        if data in place:
            return place[data]
        for f in free:
            if f[0] + len(data) <= f[1]:
                at = f[0]
                f[0] += len(data)
                new_lines[at] = data
                place[data] = at
                return at
        sys.exit(f"the roll's rows do not fit ({len(data)} B more)")

    out, i = [], 0
    wide = [False] * 4              # buffer (slot % 4) last drawn by a 16-px row
    while i < len(ptrs):
        off = ptrs[i]
        if off == BLANK:
            out.append(BLANK)
            wide[i % 4] = False
            i += 1
            continue
        role, jp, end = old[off]
        if jp not in ENGLISH:
            sys.exit(f"no English for {jp!r} at {off:#x}")
        en = ENGLISH[jp]
        if en is None:
            out.append(put(bytes(blk[off:end])))
            wide[i % 4] = True
            i += 1
            continue
        rows = en if isinstance(en, list) else [en]
        for k, row in enumerate(rows):
            if k:
                assert ptrs[i + k] == BLANK, f"{jp!r}: no blank slot for its row {k + 1}"
            cols = COLS12_WIDE if wide[(i + k) % 4] else COLS12
            wide[(i + k) % 4] = False
            out.append(put(line_bytes(row, role, cols)))
        i += len(rows)
    return out, new_lines


MODULE = 670                  # the ending's module: its pair table draws the roll


def apply(out_path=P.OUT):
    blk = bytes(S.block(*BLOCK))
    pcepair.load_registry()           # the slots pcescript gave the roll in 670's table
    with pcepair.using(pcepair.table_for(MODULE)):
        ptrs, lines = build(blk)
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (S.T2 + BLOCK[0]) * P.DATA
    assert bytes(img.data[base + TABLE:base + TABLE + 2 * len(ptrs)]) == blk[TABLE:TABLE + 2 * len(ptrs)], "the table is not pristine"
    # the blank line stays where it is; everything else is rewritten
    img.write(base + LINES[0], bytes(LINES[1] - LINES[0]))
    img.write(base + BLANK, blk[BLANK:blk.index(0xFF, BLANK) + 1])
    for at, data in lines.items():
        img.write(base + at, data)
    img.write(base + TABLE, b"".join((p + BASE).to_bytes(2, "little") for p in ptrs))
    used = sum(len(d) for d in lines.values())
    print(f"rec 130: {len(lines)} rows, {used} B of {LINES[1] - LINES[0] + TAIL[1] - TAIL[0]}; {img.flush()} sectors written")


def show():
    blk = bytes(S.block(*BLOCK))
    pcepair.load_registry(frozen=False)
    with pcepair.using(pcepair.table_for(MODULE)):
        ptrs, lines = build(blk)
    for off in ptrs:
        if off == BLANK:
            print()
            continue
        data = lines.get(off, blk[off:off + 40])
        print(f"{off:#06x} {data.hex(' ')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    show() if cmd == "show" else apply()
