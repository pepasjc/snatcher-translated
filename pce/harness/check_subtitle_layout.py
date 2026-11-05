"""Audit subtitle wording, page capacity, and minimum card count in all layouts."""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, "pce", "tools"), os.path.join(ROOT, "lib")]

import pcesubs as S


def audit_merges(baseline):
    def runs(cues):
        result = []
        for cue in cues:
            if (not result or cue["track"] != result[-1][-1]["track"]
                    or cue.get("speaker") != result[-1][-1].get("speaker")
                    or not -0.02 <= cue["start"] - result[-1][-1]["end"] <= 0.08):
                result.append([])
            result[-1].append(cue)
        return result

    def ids(cues):
        return [source for cue in cues for source in [cue["ps1"]] + cue.get("ps1_more", [])]

    merged = rebalanced = 0
    for path in sorted(Path(ROOT, "pce", "translation").glob("cdda_*.json")):
        if not path.stem.split("_")[1].isdigit():
            continue
        relative = path.relative_to(ROOT).as_posix()
        original = json.loads(subprocess.check_output(["git", "show", f"{baseline}:{relative}"], cwd=ROOT))
        current = json.loads(path.read_text(encoding="utf-8"))
        before, after = runs(original), runs(current)
        assert len(before) == len(after), (relative, "speaker/track/gap boundary")
        for group, updated in zip(before, after):
            assert ids(group) == ids(updated), (relative, "source order")
            assert " ".join(c["en"] for c in group) == " ".join(c["en"] for c in updated), (relative, "wording")
            assert group[0]["start"] == updated[0]["start"] and group[-1]["end"] == updated[-1]["end"], (relative, "timing span")
            assert all(c["track"] == group[0]["track"] and c.get("speaker") == group[0].get("speaker") for c in updated), (relative, "speaker/track")
            assert all(c["start"] < c["end"] for c in updated), (relative, "duration")
            old_boundaries = {c["start"] for c in group}
            rebalanced += sum(c["start"] not in old_boundaries for c in updated)
        merged += len(original) - len(current)
    print(f"PASS: {merged} CD cue boundaries merged, {rebalanced} rebalanced; all wording, source order, speakers, tracks and timing spans preserved against {baseline}.")


def greedy_count(items, width, rows):
    if not items:
        return 0
    pages, row, used = 1, 1, 0
    for text, colour in items:
        size = S.cost(text, colour)
        if used + size > width:
            row, used = row + 1, 0
        if row > rows:
            pages, row = pages + 1, 1
        used += size
    return pages


def audit():
    count = 0
    for path in sorted(Path(ROOT, "pce", "translation").glob("*.json")):
        if not path.stem.startswith(("subs_", "cdda_")):
            continue
        if not path.stem.split("_")[1].isdigit():
            continue
        rec = int(path.stem.split("_")[1])
        content = json.loads(path.read_text(encoding="utf-8"))
        entries = content.items() if isinstance(content, dict) else enumerate(content)
        for key, spec in entries:
            if str(key).startswith("_"):
                continue
            en, speaker = spec["en"], spec.get("speaker")
            four = rec not in S.NO_RESIDENT
            # the voice lines pack the words between two breaks into one chunk (pcesubs
            # balanced_chunks), the CD-DA cards keep one chunk a word (word_balanced_chunks)
            plan = S.balanced_chunks if path.stem.startswith("subs_") else S.word_balanced_chunks
            planned = plan(en, four, speaker=speaker)
            words = [w for w in planned if w[0] is not None]
            assert " ".join(t for t, _ in words).split() == en.replace("￥", " ").split(), (path, key, "wording")
            if not path.stem.startswith("subs_"):
                count += 1
                continue
            for face, rows in [(True, 2), (False, 2)] + ([(True, 4), (False, 3)] if four else []):
                width = S.WIDTH_FACE if face else S.WIDTH_PLAIN
                items = ([S.name_chunk(speaker), ("", S.TEXT_COLOUR)] if speaker and not face else []) + words
                cards = S.pages(speaker, en, face, rows, four)
                assert all(1 <= len(card) <= rows for card in cards), (path, key, "rows")
                assert len(cards) <= greedy_count(S.chunks(en) if not speaker or face else
                                                  [S.name_chunk(speaker)] + S.chunks(en), width, rows) + 1, (path, key, face, rows, "extra cards")
                actual = "".join(line for card in cards for line in card)
                expected = "".join(text for text, _ in items)
                assert actual.split() == expected.split(), (path, key, face, rows, "lost text")
                count += 1
    example = "All right, Gillian. I'll open the door to HQ. I'll show you around inside."
    assert len(S.pages("Mika", example, True, 4)) == 1
    fallback = S.pages("Mika", example, True, 2)
    assert not fallback[0][-1].rstrip().endswith(" to")
    print(f"PASS: {count} subtitle layouts preserve every word and use the minimum card count.")
    print("Reception 1f, four rows:")
    print("\n".join(S.pages("Mika", example, True, 4)[0]))


if __name__ == "__main__":
    audit()
    if len(sys.argv) > 1:
        audit_merges(sys.argv[1])
