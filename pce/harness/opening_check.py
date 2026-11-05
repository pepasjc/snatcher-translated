"""The opening's subtitles on screen: a fresh boot through NEW GAME and the opening, every
page of cdda_opening.json read off the screen (screentext.py) at SAMPLES points of its
span and held against the rows pceopening.py built for it: a page garbled in any capture,
or readable in fewer than half (the screen blacked out under it), fails.

The opening's own stub (pceopening.py) draws straight into VRAM with no message buffer,
so the pilot's page log (subtext.py) never sees it; this is its check. A page counts as
shown when its rows are read back whole. Exit 1 on any page not shown or garbled.

    python pce/harness/opening_check.py [--image CUE] [--out DIR]
"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pceopening as O
import screentext

SAMPLES = 6         # captures a page, spread over its span: half must read it whole


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "pce", "snatcher_pce.cue"))
    ap.add_argument("--out", default=os.path.join(WORK, "pce", "regress", "opening"))
    ap.add_argument("--limit", type=int, default=40000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import pcemenu as M
    pages = O.pages(json.load(open(O.CUES, encoding="utf-8")))
    by_track = {}
    for track, s, e, rows in pages:
        by_track.setdefault(int(f"{track:02d}", 16), []).append((s, e, rows))
    p = M.Pilot(cue=a.image)
    p.step(1000)
    p.step(8, ["start"])
    p.step(3000)
    t0, due, results, samples = {}, [], [], {}
    was = 0
    last_track = max(by_track)
    while p.frame < a.limit:
        # I through the title and NEW GAME only (presses in the newsreel would be the player's)
        if not t0 and p.frame % 90 == 0:
            p.step(8, ["a"])
        p.step(1)
        r = p.ram()
        pulse, track = r[0x638], r[0x63B]
        if pulse and not was and track in by_track and track not in t0:
            t0[track] = p.frame
            print(f"{p.frame}: track {track:02x} starts", flush=True)
            for s, e, rows in by_track[track]:
                for k in range(SAMPLES):        # spread over the page's span (its words typed on
                    at = s + (e - s) * (k + 1) // (SAMPLES + 1)      # from its start)
                    due.append((p.frame + at, track, s, e, rows))
            due.sort(key=lambda d: (d[0], d[2]))
        was = pulse
        while due and p.frame >= due[0][0]:
            f, track, s, e, rows = due.pop(0)
            img = p.emu.image()
            verdict, seen = screentext.judge(img, rows)
            key = (track, s)
            if key not in samples:
                samples[key] = dict(track=f"{track:02x}", start=s, end=e, rows=rows, verdicts=[], seen=None)
            samples[key]["verdicts"].append(verdict)
            if verdict == "GARBLED ON SCREEN" or (verdict == "ok" and samples[key]["seen"] is None):
                samples[key]["seen"] = seen
            if verdict != "ok":
                img.save(os.path.join(a.out, f"{track:02x}_{s:05d}_{p.frame}.png"))
            if len(samples[key]["verdicts"]) == SAMPLES:
                v = samples[key]["verdicts"]
                x = samples[key]
                x["verdict"] = ("GARBLED ON SCREEN" if "GARBLED ON SCREEN" in v else "ok" if v.count("ok") * 2 >= SAMPLES
                                else "MOSTLY HIDDEN")
                results.append(x)
                print(f"{p.frame}: opening page t{track:02x} {s}-{e} {x['verdict']} {v.count('ok')}/{SAMPLES} readable {rows} "
                      f"seen {x['seen']}", flush=True)
        if last_track in t0 and not due:
            break
    want = sum(len(v) for v in by_track.values())
    bad = [x for x in results if x["verdict"] != "ok"]
    missing = want - len(results)
    json.dump(results, open(os.path.join(a.out, "opening.json"), "w", encoding="utf-8"), indent=1)
    print(f"opening: {len(results) - len(bad)}/{want} pages read back whole; {len(bad)} wrong, {missing} never due "
          f"(tracks started: {', '.join(f'{t:02x}@{f}' for t, f in t0.items()) or 'none'})")
    sys.exit(1 if bad or missing else 0)


if __name__ == "__main__":
    main()
