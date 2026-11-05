"""Rebuild the letter-pair glyph table.

Only JIS level 1 (ku 16-47) follows the font's linear slot layout
(slot = (ku-1)*94 + (ten-1) - 845). Level 2 rows (ku 48+) do NOT: glyphs
written there are never read back, so any pair assigned to such a slot
renders blank in game. This rebuilds the pool level-1 only and assigns
slots by how often each pair actually occurs in the translated text, so
the scarce slots go to common pairs and the rare tail falls back to
fullwidth (wider, 2 bytes more, but readable).

Usage: python rebuild_pairs.py [--fresh]

Since 2026-09-12 the pool is every level-1 slot the game NO LONGER draws:
only the strings that stay Japanese (no `en`, or `lock`), the colour codes
and other non-ASCII inside English lines, and the name table hold their
glyphs; until then every kanji of the ORIGINAL script counted as used and
the pool was 1,375 slots for ~1,600 pairs - 241 fell back to fullwidth,
and the two fullwidth letters inside a word ("hand ke rchief",
"cros sr oad", "gro wt h") were the gaps Luiz kept seeing. The pool is
~2,900 now, so every pair the text uses has a slot. The assignment is
also INCREMENTAL: a pair already in work/pair_table.json keeps its slot
(bookmarks carry rendered text in RAM - the live menu labels, the SJIS
name table - and a reshuffled table turns it to garbage), new pairs take
free slots, and only `--fresh` ranks everything from scratch.
"""
import os, sys, json, glob, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]
from textcodec import char_to_code
from translate_names import NAMES
from pairfont import RESERVED
from consolidate import wrap

TR = os.path.join(ROOT, "ps1/translation")
REF = os.path.join(ROOT, "work", "ref")
NSZ = os.path.join(ROOT, "discs/extracted_ps1", "PLN", "NSZ", "NSZ_B000.BIN")
FREE = os.path.join(ROOT, "work", "free_slots.json")
TABLE = os.path.join(ROOT, "work", "pair_table.json")

NAME_WEIGHT = 10 ** 6           # speaker-name pairs outrank every text pair

# The engine parses these after '＠' (colour) and at a line's end (Ｃ);
# their codes are level-1 kanji, so they must never become pair glyphs.
CONTROL = "赤白黄緑青水紫桃Ｃ"


def game_used_codes(residual=True):
    """Codes the built game still draws or parses through the font.

    residual=True: the Japanese of strings that stay Japanese (no `en`,
    or `lock`) plus every non-ASCII character inside an English line or
    long (colour codes, ▽, ★, ￥...). residual=False is the old rule -
    every character of the original script."""
    used = {c for c in (char_to_code(ch) for ch in CONTROL) if c}
    for p in glob.glob(os.path.join(REF, "ISZ_*.json")):
        ref = json.load(open(p, encoding="utf-8"))
        tpath = os.path.join(TR, os.path.basename(p))
        tr = json.load(open(tpath, encoding="utf-8")) if os.path.exists(tpath) else {"strings": []}
        ens = {e["off"]: e for e in tr["strings"]}
        for r in ref["strings"]:
            e = ens.get(r["off"], {})
            if not residual or not e.get("en") or e.get("lock"):
                for ch in r["jp"]:
                    c = char_to_code(ch)
                    if c:
                        used.add(c)
            for text in (e.get("en", ""), e.get("long", "")):
                for ch in text:
                    if ord(ch) >= 0x80:
                        c = char_to_code(ch)
                        if c:
                            used.add(c)
    n = open(NSZ, "rb").read()
    for i in range(len(n) - 1):
        used.add((n[i] << 8) | n[i+1])
    return used

# The glyph data in the executable ends at file 0x5c3b4 = FONT_BASE + 18*3530;
# what follows is an engine table of RAM pointers. Slots 3530..3572 are inside
# it, so writing pair glyphs there corrupts live data. That shipped: the game
# hung on a black screen after New Game on mednafen, no$psx and MiSTer, while
# DuckStation limped on, which made it look like a disc-layout bug.
MAX_SLOT = 3529


def level1_pool(used):
    pool = []
    for ku in range(16, 48):                      # level 1 only
        for ten in range(1, 95):
            pair = (ku + 1) // 2
            high = 0x80 - pair
            pos = (0 if ku % 2 == 1 else 94) + (ten - 1)
            low = 0xC0 - pos
            if low <= 0x80:
                low -= 1
            if low < 0:
                continue
            code = (high << 8) | low
            if code in used:
                continue
            slot = (ku - 1) * 94 + (ten - 1) - 845
            if slot > MAX_SLOT:
                continue
            # the dead slots that hold exec-side code (subs_cue's hooks
            # and stubs, pairfont.RESERVED) - kanji the original script
            # used, so the old pool never reached them; the residual pool
            # does, and a pair there is overwritten by the stub
            if any(a <= slot <= b for a, b in RESERVED):
                continue
            pool.append((slot, code))
    return pool

def count_into(counts, en, weight=1):
    """Count pairs exactly the way pairfont.encode chunks them."""
    buf = ""
    for ch in en:
        if ord(ch) < 0x80:
            buf += ch
        else:
            if buf:
                if len(buf) % 2:
                    buf += " "
                for k in range(0, len(buf), 2):
                    counts[buf[k:k+2]] += weight
                buf = ""
    if buf:
        if len(buf) % 2:
            buf += " "
        for k in range(0, len(buf), 2):
            counts[buf[k:k+2]] += weight


def count_sjis(counts, text, weight=1):
    """Count pairs the way sjis_enc.encode takes them (see there)."""
    i = 0
    while i < len(text):
        if text[i] == chr(10):
            i += 1
            continue
        pair = text[i:i + 2]
        if len(pair) == 2 and pair[1] != chr(10) and ord(pair[0]) < 0x80 and ord(pair[1]) < 0x80:
            counts[pair] += weight
            i += 2
            continue
        if ord(text[i]) < 0x80:
            counts[text[i] + " "] += weight
        i += 1


def pair_demand():
    counts = collections.Counter()
    for p in glob.glob(os.path.join(TR, "*.json")):
        spec = json.load(open(p, encoding="utf-8"))
        # Subtitles and longs draw through the same pairs, so their demand
        # counts too - but only bank text has a byte budget, where a pair
        # falling back costs 2 bytes, so it outweighs them (a rebuild that
        # weighed them equally pushed '(K' out and Konami Omni Building no
        # longer fit).
        if "cues" in spec:
            # Subtitles go through sjis_enc.encode on the text subs_cue
            # wraps at the bank's cols AND at 18 (the plain card): pairs
            # left to right, a letter left alone at a row's end paired
            # with a space. Count exactly those pairs - the unwrapped text
            # never shows which letter ends a row ('A ' in '...type / A,
            # RH negative' had no slot and drew a wide A).
            opts = spec.get("options", {})
            rows, cols = opts.get("rows", 3), min(opts.get("cols", 18), 18)
            for c in spec["cues"]:
                if c.get("en") and c.get("enabled", True):
                    text = c["en"].replace("/n", chr(10))
                    # wrapped as it will be once every pair has a glyph
                    # (consolidate.wrap): subs_cue.wrap_only measures with
                    # THIS table, so a row needing a pair not yet assigned
                    # would come out different - or not fit at all
                    for w in {min(c.get("cols", cols), 18), 18}:
                        count_sjis(counts, chr(10).join(wrap(text, w)), weight=1)
            continue
        if "strings" not in spec:      # disclaimer/gfx_pages/fmv_credits
            continue
        for e in spec["strings"]:
            if e.get("en"):
                count_into(counts, e["en"], weight=4)
            if e.get("long"):          # replaces its en on screen
                count_into(counts, e["long"], weight=2)
    # Speaker names print above nearly every line of dialogue, and a name that
    # loses its glyph is garbled on screen rather than merely wide. Weight them
    # far above any text pair so they always keep real slots.
    for name in NAMES:
        count_into(counts, name, weight=NAME_WEIGHT)
    return counts

def budget_fallbacks(table):
    """Pairs with no slot inside strings that overrun their budget by that."""
    out = set()
    for p in glob.glob(os.path.join(TR, "ISZ_*.json")):
        for e in json.load(open(p, encoding="utf-8"))["strings"]:
            en = e.get("en")
            if not en or e.get("lock"):
                continue
            size, missing, buf = 1, [], ""
            def flush():
                nonlocal size, buf
                if len(buf) % 2:
                    buf += " "
                for k in range(0, len(buf), 2):
                    pr = buf[k:k + 2]
                    if pr in table:
                        size += 2
                    else:
                        size += 4
                        missing.append(pr)
                buf = ""
            for ch in en:
                if ord(ch) < 0x80:
                    buf += ch
                else:
                    flush()
                    size += 2
            flush()
            if size > e["budget"] and missing and size - 2 * len(missing) <= e["budget"]:
                out.update(missing)
    return out


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    used = game_used_codes()
    pool = level1_pool(used)
    demand = pair_demand()
    name_pairs = {p for p, c in demand.items() if c >= NAME_WEIGHT}
    text_uses = sum(c % NAME_WEIGHT for c in demand.values())
    print(f"level-1 slots free: {len(pool)}")
    print(f"distinct pairs wanted: {len(demand)} "
          f"({len(name_pairs)} from speaker names, {text_uses} text uses)")

    old = {} if fresh or not os.path.exists(TABLE) else json.load(open(TABLE))
    pool_slots = {slot for slot, _ in pool}
    kept = {p: v for p, v in old.items() if v[0] in pool_slots}
    if len(kept) < len(old):
        print(f"{len(old) - len(kept)} pairs of the old table sat on slots the game now draws - reassigned")
    free = [(slot, code) for slot, code in pool if slot not in {v[0] for v in kept.values()}]
    print(f"keeping {len(kept)} pairs on their slots, {len(free)} slots free for new ones")

    # New pairs by demand into the free slots, then keep every budgeted
    # string in budget: a string that only fits with a rare pair on a slot
    # (`92` in "1992: Vesta program") gets that pair promoted over the
    # least-used newcomers, and the assignment is repeated until nothing
    # is over. With the residual pool every wanted pair fits and the
    # promotion never fires.
    for round_ in range(20):
        table = dict(kept)
        new = [(pair, c) for pair, c in demand.most_common() if pair not in kept]
        for i, (pair, _) in enumerate(new):
            if i >= len(free):
                break
            slot, code = free[i]
            table[pair] = [slot, code]
        promote = budget_fallbacks(table)
        if not promote:
            break
        print(f"round {round_}: promoting {sorted(promote)} to keep strings in budget")
        for pair in promote:
            demand[pair] += NAME_WEIGHT // 2
    json.dump(table, open(TABLE, "w"))
    spare = [[s, c] for s, c in pool if s not in {v[0] for v in table.values()}]
    json.dump(spare, open(FREE, "w"))

    assert name_pairs <= set(table), sorted(name_pairs - set(table))
    missing = [p for p in demand if p not in table]
    fallback_uses = sum(demand[p] for p in missing)
    print(f"assigned {len(table)} pairs, {len(spare)} slots spare")
    print(f"{len(missing)} wanted pairs fall back to fullwidth "
          f"({fallback_uses} uses, {fallback_uses*100//max(1,text_uses)}% of text)")
