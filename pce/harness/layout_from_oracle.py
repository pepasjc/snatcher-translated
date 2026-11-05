"""Each voiced line's layout from the original game (portrait_oracle.py recordings of the
untouched Japanese image): a line whose speaker's face the game draws on the band while the
line plays is "face" (the stub waits for that face and shows it on the left), any other line
"plain" (a card with the name, no portrait). The game is the source of truth; a line no
recording reached gets no field (pcesubs takes "face": the stub then waits for a face and
falls back to the card only if none comes - a missing field never hides a portrait).

Faces the game draws that faces.json does not know are listed by the speaker whose lines they
come up in - a speaker with one unknown face through all its lines is that face's owner
(`--learn` adds it to faces.json).

  python pce/harness/layout_from_oracle.py <jp.json> [<jp.json> ...] [--write] [--learn]
"""
import collections, glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

TDIR = os.path.join(ROOT, "pce", "translation")


def subs_index():
    """{(module, nn): [(path, key, spec)...]} over the subs files - a module that plays one NN
    in two acts ("cc.4" Gillian, "cc.5" Madnar in the ending) has an entry for each."""
    import pcesubs as S
    out = {}
    for p in glob.glob(os.path.join(TDIR, "subs_*.json")):
        rec = int(os.path.basename(p)[5:-5])
        for k, v in json.load(open(p, encoding="utf-8")).items():
            if k.startswith("_") or not isinstance(v, dict) or not v.get("en"):
                continue
            try:
                out.setdefault((rec, S.line_key(rec, k)[1]), []).append((p, k, v))
            except Exception:
                continue
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    idx = subs_index()
    seen = {}                                   # (path, key) -> (face seen?, first k)
    unknown = collections.defaultdict(collections.Counter)
    lines_of = collections.Counter()
    for path in args:
        for c in json.load(open(path))["lines"]:
            entries = idx.get((c["module"], c["nn"]))
            if not entries:
                continue
            chars_at = [(s["k"], {f["char"] for f in s["faces"].values()}) for s in c["samples"]]
            for p, k, v in entries:
                speaker = v.get("speaker")
                lines_of[speaker] += 1
                first = next((kk for kk, chars in chars_at if speaker in chars), None)
                for kk, chars in chars_at:
                    for ch in chars:
                        if ch.startswith("?"):
                            unknown[speaker][ch] += 1
                if first is None and len(entries) > 1:
                    continue                    # (which act played is not known: no verdict)
                was = seen.get((p, k))
                if was is None or (first is not None and not was[0]):
                    seen[(p, k)] = (first is not None, first)
    n_face = sum(1 for f, _ in seen.values() if f)
    total = sum(len(v) for v in idx.values())
    print(f"{len(seen)} lines recorded: {n_face} face, {len(seen) - n_face} plain; "
          f"{total - len(seen)} lines no recording decided (left to the stub's wait)")
    late = sorted(k for f, k in seen.values() if f)
    if late:
        print(f"the speaker's face first seen at +{late[0]}..+{late[-1]} frames "
              f"(median +{late[len(late) // 2]})")
    for sp, c in sorted(unknown.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  unknown faces during {sp}'s lines ({lines_of[sp]} lines): {c.most_common(3)}")
    if "--write" in sys.argv:
        by_file = collections.defaultdict(dict)
        for entries in idx.values():
            for p, k, v in entries:
                by_file[p][k] = ("face" if seen[(p, k)][0] else "plain") if (p, k) in seen else None
        changed = 0
        for p, keys in by_file.items():
            raw = open(p, encoding="utf-8", newline="").read()
            nl = "\r\n" if "\r\n" in raw else "\n"
            data = json.loads(raw)
            for k, want in keys.items():
                v = data[k]
                if want is None:
                    if "layout" in v:
                        del v["layout"]
                        changed += 1
                elif v.get("layout") != want:
                    v["layout"] = want
                    changed += 1
            open(p, "w", encoding="utf-8", newline="").write(
                json.dumps(data, ensure_ascii=False, indent=1).replace("\n", nl) + (nl if raw.endswith(nl) else ""))
        print(f"{changed} layout fields written")


if __name__ == "__main__":
    main()
