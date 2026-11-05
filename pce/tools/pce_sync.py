"""Carry the PS1 cue files' later corrections into the PCE lines that were drafted from them.

Every PCE line (pce/translation/subs_<rec>.json) keeps the ids of the PS1
cards it was matched to (`ps1`, from pcematch). When the PS1 files move on
(a speaker relabelled, a translation fixed, cards re-cut by consolidate.py
under new ids), this compares, per PCE line, the English those cards
carried at a base commit with what the same span of the stream carries
now (the old cards' file/chan/sectors against the current cards, so
re-cut ids still resolve), and:

  - applies the new text and speaker where the PCE line still equals the
    old PS1 text (nothing was hand-edited on the PCE side);
  - reports the rest (the PCE line was edited AND the PS1 changed) for a
    hand decision.

The CD-DA cue files (pce/translation/cdda_<rec>.json, drafted by pcecdda.py
from the PS1 reels' cards) follow the same rule by their `ps1` id: a card
whose en and speaker still equal the PS1 card's at the base takes the PS1
card's current en and speaker (the dash pass, a speaker swap by ear).

  python pce/tools/pce_sync.py <base commit> [--write]   # e.g. pre-main-sync
"""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import glob


def ps1_files(commit=None):
    """{bank: cue list} from the working tree, or from a commit."""
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "ps1", "translation", "subs_*.json"))):
        bank = os.path.basename(path)[5:-5]
        if commit:
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            try:
                text = subprocess.check_output(["git", "show", f"{commit}:{rel}"], cwd=ROOT)
            except subprocess.CalledProcessError:
                continue
            out[bank] = json.loads(text.decode("utf-8"))["cues"]
        else:
            out[bank] = json.load(open(path, encoding="utf-8"))["cues"]
    return out


def history(ids, before):
    """{id: (card, its file's cues)} for PS1 ids already retired at <before>: each id as the newest
    commit before it last carried it (the cue files under ps1/translation/ and,
    before the 2026-09-10 reorg, translation/). A PCE line matched to a card
    that a consolidate.py re-cut retired BEFORE the base would otherwise never
    follow the PS1 again (229 lines at the 2026-09-28 sync)."""
    want, out = set(ids), {}
    revs = subprocess.check_output(["git", "log", "--format=%H", before, "--",
                                    "ps1/translation/subs_*.json", "translation/subs_*.json"],
                                   cwd=ROOT, text=True).split()
    for rev in revs:
        if not want:
            break
        names = subprocess.check_output(["git", "show", "--format=", "--name-only", rev],
                                        cwd=ROOT, text=True).split()
        for rel in names:
            if not os.path.basename(rel).startswith("subs_") or not rel.endswith(".json"):
                continue
            try:                             # the file as this commit left it (newest first)
                cues = json.loads(subprocess.check_output(["git", "show", f"{rev}:{rel}"], cwd=ROOT,
                                                          stderr=subprocess.DEVNULL).decode("utf-8"))["cues"]
            except (subprocess.CalledProcessError, ValueError, KeyError, TypeError):
                continue
            for c in cues:
                if c.get("id") in want:
                    out[c["id"]] = (c, cues)
                    want.discard(c["id"])
    return out


def bare(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def extend(olds, en, pools):
    """The run of consecutive PS1 cards (one stream, in stream order) around the
    line's cards whose joined text IS the PCE line: pcematch kept only the first
    card's id where one ADPCM line covers several cards. None if no pool has one."""
    want = bare(en)
    ids = {c["id"] for c in olds}
    k = (olds[0]["file"], olds[0]["chan"])
    for cues in pools:
        s = sorted((c for c in cues if (c.get("file"), c.get("chan")) == k and "start" in c
                    and c.get("enabled", True)), key=lambda c: c["start"])
        at = [n for n, c in enumerate(s) if c.get("id") in ids]
        if not at:
            continue
        for i in range(at[0], max(-1, at[0] - 4), -1):
            for j in range(at[-1], min(len(s), at[-1] + 8)):
                got = bare(" ".join(c["en"] for c in s[i:j + 1]))
                if got == want:
                    return s[i:j + 1]
                if len(got) > len(want):
                    break
    return None


def one_bank(news, olds):
    """The same take carded under two banks (Joy Division's greeting under B060 and
    B0E0, the drunk's wake-up under B100 and B110) is one line: when cards of two banks
    overlap in the span, keep the bank the line's own cards came from (else the one
    covering the most). The full review translated such twins differently, so the
    text test alone no longer folds them."""
    banks = {}
    for c in news:
        banks.setdefault(c["id"].split("_")[0], []).append(c)
    if len(banks) < 2:
        return news
    order = [c["id"].split("_")[0] for c in olds]
    keep = max(banks, key=lambda b: (order.count(b), sum(c["end"] - c["start"] for c in banks[b])))
    kept = banks[keep]
    out = list(kept)
    for b, cs in banks.items():                  # a bank's cards outside the kept ones' time stay
        if b != keep:
            out += [c for c in cs if all(min(c["end"], k["end"]) <= max(c["start"], k["start"]) for k in kept)]
    return out


def clean(en):
    return " ".join(en.replace("￥", " ").split())


# a PS1 speaker name the PCE's pcesubs.CHARS spells otherwise
SPEAKER = {"Metal": "Metal Gear"}


def joined(cues):
    en = " ".join(clean(c["en"]) for c in cues if c.get("enabled", True))
    speakers = [SPEAKER.get(c["speaker"], c["speaker"]) for c in cues if c.get("speaker")]
    speaker = max(set(speakers), key=speakers.count) if speakers else None
    return en, speaker


def main():
    base = sys.argv[1]
    write = "--write" in sys.argv
    old = ps1_files(base)
    new = ps1_files()
    old_by_id = {c["id"]: (bank, c) for bank, cues in old.items() for c in cues}
    pools = list(old.values())          # cue lists a PCE line's run of cards is looked for in
    gone = set()
    for path in glob.glob(os.path.join(ROOT, "pce", "translation", "subs_*.json")):
        for key, line in json.load(open(path, encoding="utf-8")).items():
            if not key.startswith("_") and line.get("ps1") and not any(i in old_by_id for i in line["ps1"]):
                gone.update(line["ps1"])
    if gone:
        found = history(gone, base)
        print(f"{len(gone)} ids retired before the base, {len(found)} found in the history")
        for i, (c, cues) in found.items():
            if all(k in c for k in ("file", "chan", "start", "end", "en")):
                old_by_id[i] = (None, c)
                pools.append(cues)
    new_by_fc = {}
    for bank, cues in new.items():
        for c in cues:
            k = (c["file"], c["chan"])
            # the same take carded under two banks (the videophone's): once
            if any(o["start"] == c["start"] and clean(o["en"]) == clean(c["en"]) for o in new_by_fc.get(k, [])):
                continue
            new_by_fc.setdefault(k, []).append(c)
    applied, review, missing, same, extended = 0, [], 0, 0, 0
    for path in sorted(glob.glob(os.path.join(ROOT, "pce", "translation", "subs_*.json"))):
        rec = os.path.basename(path)[5:-5]
        data = json.load(open(path, encoding="utf-8"))
        changed = False
        for key, line in data.items():
            if key.startswith("_") or not line.get("ps1"):
                continue
            olds = [old_by_id[i][1] for i in line["ps1"] if i in old_by_id]
            if not olds:
                missing += 1
                continue
            old_en, old_speaker = joined(olds)
            if bare(line["en"]) != bare(old_en):
                run = extend(olds, line["en"], pools)
                if run:
                    olds = run
                    old_en, old_speaker = joined(olds)
                    extended += 1
            # the same span of the same stream in the current files
            spans = {}
            for c in olds:
                k = (c["file"], c["chan"])
                a, b = spans.get(k, (c["start"], c["end"]))
                spans[k] = (min(a, c["start"]), max(b, c["end"]))
            news = []
            for k, (a, b) in spans.items():
                # a card counts when at least half of it (or of the span) lies inside the span:
                # re-cut boundaries shift by a few sectors
                for c in new_by_fc.get(k, []):
                    ov = min(b, c["end"]) - max(a, c["start"])
                    if ov > 0 and ov * 2 >= min(c["end"] - c["start"], b - a):
                        news.append(c)
            news = one_bank(news, olds)
            news.sort(key=lambda c: c["start"])
            if not news:
                missing += 1
                continue
            new_en, new_speaker = joined(news)
            if new_en == old_en and new_speaker == old_speaker:
                same += 1
                continue
            # a re-cut that merged the old span into a much longer card (the PS1 joining
            # 'Metal!' to the line after it) is not this PCE line's text: a hand decision
            span_old = sum(b - a for a, b in spans.values())
            span_new = max(c["end"] for c in news) - min(c["start"] for c in news)
            # the PCE's own dash pass rewrote punctuation only: still the PS1's words
            edited = bare(line["en"]) != bare(old_en) or span_new > span_old * 1.5 + 20
            if edited:
                review.append((rec, key, line["en"], old_en, new_en, line.get("speaker"), new_speaker))
                continue
            print(f"{rec} {key}: {old_speaker}: {old_en[:50]!r}\n      -> {new_speaker}: {new_en[:50]!r}")
            if write:
                line["en"] = new_en
                if new_speaker:
                    line["speaker"] = new_speaker
                line["ps1"] = [c["id"] for c in news]
                changed = True
            applied += 1
        if changed:
            raw = open(path, encoding="utf-8", newline="").read()
            nl = "\r\n" if "\r\n" in raw else "\n"
            text = json.dumps(data, ensure_ascii=False, indent=1).replace("\n", nl) + nl
            open(path, "w", encoding="utf-8", newline="").write(text)
    print(f"\n{applied} lines take the PS1's new text{' (written)' if write else ''}, {same} unchanged, {missing} with no card found"
          f" ({extended} matched to a longer run of cards than their ids)")
    if review:
        print(f"{len(review)} lines edited on the PCE side while the PS1 changed too - by hand:")
        for rec, key, en, old_en, new_en, sp, nsp in review:
            print(f"  {rec} {key} ({sp} -> {nsp}):\n    pce: {en[:70]!r}\n    was: {old_en[:70]!r}\n    now: {new_en[:70]!r}")


def cdda(base, write):
    """cdda_<rec>.json cards brought up to their PS1 card (by id)."""
    old = {c["id"]: c for cues in ps1_files(base).values() for c in cues}
    new = {c["id"]: c for cues in ps1_files().values() for c in cues}
    applied, review = 0, []
    for path in sorted(glob.glob(os.path.join(ROOT, "pce", "translation", "cdda_*.json"))):
        rec = os.path.basename(path)[5:-5]
        cards = json.load(open(path, encoding="utf-8"))
        changed = False
        for card in cards:
            o, n = old.get(card.get("ps1")), new.get(card.get("ps1"))
            if not o or not n or (n["en"], n["speaker"]) == (o["en"], o["speaker"]):
                continue
            if (card["en"], card["speaker"]) == (n["en"], n["speaker"]):
                continue                                        # already there
            if (card["en"], card["speaker"]) != (o["en"], o["speaker"]):
                review.append((rec, card, o, n))
                continue
            print(f"{rec} t{card['track']} {card['start']:.2f} {card['ps1']}: {o['speaker']}: {o['en'][:50]!r}\n      -> {n['speaker']}: {n['en'][:50]!r}")
            if write:
                card["en"], card["speaker"] = n["en"], SPEAKER.get(n["speaker"], n["speaker"])
                changed = True
            applied += 1
        if changed:
            json.dump(cards, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\ncdda: {applied} cards take the PS1's new text{' (written)' if write else ''}")
    if write:
        recut(new)
    for rec, card, o, n in review:
        print(f"  {rec} {card['ps1']} edited on the PCE side while the PS1 changed too - by hand:\n    pce: {card['speaker']}: {card['en'][:70]!r}\n    was: {o['speaker']}: {o['en'][:70]!r}\n    now: {n['speaker']}: {n['en'][:70]!r}")


def recut(new):
    """The PS1 re-cut a reel (cards merged or split under new ids): per track, the PS1
    cards of the same reel in stream order; a PS1 card the PCE has no card for is
    appended to the previous PCE card's text, and a PCE card whose id is retired is
    merged into its predecessor (span extended, text carried) - so every track reads as
    the PS1 reel does now. Timings stay the PCE's (the warp of its own audio)."""
    import re
    bare = lambda s: re.sub(r"[^a-z0-9']+", " ", s.lower()).strip()
    for path in sorted(glob.glob(os.path.join(ROOT, "pce", "translation", "cdda_*.json"))):
        cards = json.load(open(path, encoding="utf-8"))
        out, changed = [], False
        for c in cards:                                   # retired ids first
            if c.get("ps1") and c["ps1"] not in new and out and out[-1]["track"] == c["track"]:
                out[-1]["end"] = max(out[-1]["end"], c["end"]); changed = True
                print(f"  {os.path.basename(path)} {c['ps1']} merged into {out[-1]['ps1']}")
                continue
            out.append(c)
        by_track = {}
        for c in out:
            by_track.setdefault(c["track"], []).append(c)
        for t, cs in by_track.items():
            ids = {c.get("ps1"): c for c in cs if c.get("ps1")}
            pref = {i.rsplit("_", 1)[0] for i in ids}
            ps1 = sorted((c for c in new.values() if c["id"].rsplit("_", 1)[0] in pref), key=lambda c: (c["file"], c["chan"], c["start"]))
            prev, pending = None, []
            for c in ps1:
                if c["id"] in ids:
                    card, text = ids[c["id"]], c["en"]
                    if pending:
                        text, pending = " ".join(pending + [text]), []
                    if card["en"] != text:
                        card["en"] = text; changed = True
                    prev = card
                elif prev is not None:
                    if bare(c["en"]) not in bare(prev["en"]):
                        prev["en"] = (prev["en"] + " " + c["en"]).strip(); changed = True
                else:
                    pending.append(c["en"])
            if bare(" ".join(c["en"] for c in cs)) != bare(" ".join(c["en"] for c in ps1)):
                print(f"  {os.path.basename(path)} track {t}: does not read as the PS1 reel - by hand")
        if changed:
            json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
    cdda(sys.argv[1], "--write" in sys.argv)
