"""The portraits, pass or fail against the original game: the untouched Japanese image plays a
route and records, for every voice line, the faces it draws on the band (each region's
character by its bitmap's signature, every sprite's x and y); the translation plays the same
route and must show exactly what the subtitle stub's rules make of that:

  * a subtitle up and the line's speaker has a face of the game's on the band (wherever the
    game puts it): that face alone, every sprite of it moved by the same dx so its left edge
    is at FACE_X (32), its y as the game's - one portrait, on the left, the speaker's (Luiz,
    2026-10-16: the Japanese draws portraits anywhere, ours one on the left)
  * a subtitle up and the speaker has no face there: no face on the band (a card, the name)
  * no subtitle up: reported apart (between lines the stub holds the last speaker's face)

Lines are matched by (module, NN, occurrence) - the two runs differ in time (pages, presses),
not in what the script does - and sampled every STEP frames from the line's start. A sample
counts only where the Japanese state is steady (the same for STEADY frames each side): a face
decoding in is not a fault on either side. Every mismatch is a failure, with the frame, the
line, both states.

  python pce/harness/portrait_oracle.py record <out.json> <cue> [--bram NAME] [--route r.json] [--steps a:b] [--japanese]
  python pce/harness/portrait_oracle.py compare <japanese.json> <translation.json> [--report out.txt]
"""
import json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'pce/harness')]

STEP = 4          # frames between samples
SPAN = 900        # frames sampled after a line starts (or until the next line)
STEADY = 8        # the Japanese state the same this many frames before and after a sample
YWIN = 64         # a face's y must be one the game drew it at within this many frames (its own
                  # animation: Metal Gear's face bobs a pixel, slower than STEADY)
DUMP = set(filter(None, os.environ.get("PORTRAIT_DUMP", "").split(",")))
FACE_X = 32       # the speaker's face's left edge beside the subtitle (pcesubs.FACE_X: one column for every face)


def band_faces(pilot):
    """{region: {"char": name or signature, "spr": [(x, y, pattern)...]}} for the face regions
    with sprites on the band (patterns 0x200-0x3FF, y from 0xA0), x/y on the screen."""
    import pcestate as ST, pcesubs as X
    v = ST.sections(pilot.emu.state(), ("VRAM",))["VRAM"]
    sat = [struct.unpack_from("<HHHH", v, 0x2000 + i * 8) for i in range(64)]
    objs = {}
    for y, x, pat, attr in sat:
        p = pat & 0x7FF
        if 0xC0 <= y < 0x400 and p >= 0x200 and 0 < x < 32 + 256:   # (the band from screen y 128,
                                                                       # as the stub's fsprite: a face's top cells sit at 144)
            objs.setdefault((p - 0x200) >> 6, []).append((x - 32, y - 64, p))
    db = X.faces_db()
    owners = {tuple(w): k for k, ws in db.items() for w in ws}
    out = {}
    for reg, spr in objs.items():
        if len(v) < (0x4000 + reg * 0x800 + 0x800) * 2:
            continue                              # (a state with a short VRAM section)
        words = struct.unpack_from("<%dH" % 0x800, v, (0x4000 + reg * 0x800) * 2)
        sig = tuple(words[o] for o in X.SIG_OFFS)
        out[str(reg)] = {"char": owners.get(sig) or "?" + "".join(f"{w:04x}" for w in sig),
                         "spr": sorted(spr)}
    return out


def record(out, cue, bram=None, route=None, steps=None, japanese=False, pre=None, bookmark=None, limit=None,
           checkpoint=None, until=None):
    os.environ["LINELOG"] = "1"
    import pcemenu as M
    if japanese:
        M.JAPANESE = True
    p = M.Pilot(cue=cue)
    if bram:
        import subprocess
        subprocess.run([sys.executable, os.path.join(HERE, "regress_saves.py"), bram, "--frames", "60",
                        "--image", cue], capture_output=True)
        p.restore(os.path.join(WORK, "pce", "regress", bram, "loaded.mdf"))
        pre = pre or []
    else:
        import importlib.util as IU
        sp = IU.spec_from_file_location("ptpce", os.path.join(HERE, "playthrough.py"))
        PT = IU.module_from_spec(sp); sp.loader.exec_module(PT)
        PT.boot(p)
        pre = (pre or []) + [{"maybe": "Go inside"}, {"read": 3000}]
    steps_list = []
    for rf in (route.split(",") if route else []):            # several route files in a row
        if not os.path.isabs(rf) and not os.path.exists(rf):
            rf = os.path.join(HERE, "routes", rf if rf.endswith(".json") else rf + ".json")
        rs = json.load(open(rf, encoding="utf-8"))
        if rs and isinstance(rs[0], dict):
            rs[0] = dict(rs[0], _route_start=True)
        steps_list += rs
    if steps:
        a, b = (int(x) if x else None for x in steps.split(":"))
        steps_list = steps_list[a:b]
    lines, cur, hook = [], [None], [None]
    sv, spk = None, None
    if not japanese:                              # the stub's own state: its page up, rows in,
        import pcesubs as X                       # not held after the voice, not waiting for a face
        sv = X.stub_vars()
    orig = p.watch

    def w():
        orig()
        due = getattr(p, "due", None)               # (frame + 30, NN) from the line's first frame
        if due and (cur[0] is None or cur[0]["f0"] != due[0] - 30):
            cur[0] = {"f0": due[0] - 30, "nn": due[1], "module": None, "samples": []}
            try:
                cur[0]["module"] = p.module()
            except Exception:
                pass
            lines.append(cur[0])
            if hook[0]:
                hook[0](cur[0])
        c = cur[0]
        if c is None or p.frame - c["f0"] > SPAN or (p.frame - c["f0"]) % STEP:
            return
        r = p.ram()
        tag = ""
        if c["nn"] is not None:                   # PORTRAIT_DUMP="334:56:232,...": a state at the
            for d in list(DUMP):                  # first sample at or past each
                m, n, kk = d.split(":")
                if int(m) == c["module"] and int(n, 16) == c["nn"] and p.frame - c["f0"] >= int(kk):
                    DUMP.discard(d); tag = d
        shot_at = int(os.environ.get("PORTRAIT_SHOTS", "0"))   # PORTRAIT_SHOTS=120: every line's screen 120 frames in
        if shot_at and c["nn"] is not None and p.frame - c["f0"] == shot_at:
            os.makedirs(f"{out}_shots", exist_ok=True)
            p.emu.image().save(f"{out}_shots/{c['module']}_{c['nn']:02x}_{c['f0']}.png")
        if tag:
            open(f"{out}_{tag.replace(':', '_')}.mdf", "wb").write(p.emu.state())
            p.emu.image().save(f"{out}_{tag.replace(':', '_')}.png")
        import pcestate as ST, pcesubs as X
        v = ST.sections(p.emu.state(), ("VRAM",))["VRAM"]
        rows = sum(1 for k in range(8) for col in (2, 14, 20)
                   if struct.unpack_from("<H", v, (X.WIN_BAT + k * 64 + col) * 2)[0] & 0xFFF != 0x110)
        lit = rows
        up = None
        if sv:
            sc = ST.sections(p.emu.state(), ("SysCardRAM",))["SysCardRAM"]
            at = lambda a: sc[(0x7B - 0x68) * 0x2000 + a - 0xA000]
            up = int(bool(at(sv["shown"]) and at(sv["rowsin"]) and not at(sv["linger"]) and not at(sv["grace"])))
            code = at(sv["schar"]) & 0x7F                       # the line's speaker as the stub has it
            spk = X.CHARS[code - 1] if 0 < code <= len(X.CHARS) else ""
        c["samples"].append({"k": p.frame - c["f0"], "frame": p.frame, "win": r[0x19BF], "lit": lit, "up": up,
                             "spk": spk if sv else None,
                             "page": (getattr(p, "page", "") or "")[:64] if not japanese else "",
                             "faces": band_faces(p)})
    p.watch = w
    # bookmarks: the last verb menu's state before each wanted line, with the route step there
    want = {tuple(x.split(":")) for x in (bookmark or "").split(",") if x}
    want = {(int(m), int(n, 16)) for m, n in want}
    snap = [None]
    bdir = os.path.join(WORK, "pce", "oracle", "bm")
    os.makedirs(bdir, exist_ok=True)
    def on_line(c):
        key = (c["module"], c["nn"])
        if key in want and snap[0] is not None:
            want.discard(key)
            name = f"{key[0]}_{key[1]:02x}"
            open(os.path.join(bdir, name + ".mdf"), "wb").write(snap[0][0])
            json.dump({"step": snap[0][1], "route": route, "bram": bram, "pre_done": True,
                       "line": [key[0], key[1]]}, open(os.path.join(bdir, name + ".json"), "w"))
            print(f"{p.frame}: bookmark {name} (step {snap[0][1]})", flush=True)
    hook[0] = on_line
    try:
        M.run(p, pre, outdir=out + "_run")
        base = int(steps.split(":")[0] or 0) if steps else 0
        cps, due_cp = [], True                    # checkpoints: a BRAM save at a savable menu after
        for i, st in enumerate(steps_list):       # each route's start and each typed answer
            if checkpoint and due_cp and p.menu() is not None:
                labels = [M.norm(t) for t in p.items()]
                if "use metal gear" in labels or any(l.startswith("save") for l in labels):
                    name = f"cp_{checkpoint}_{base + i}"
                    try:
                        M.game_save(p)
                        M.dump_bram(p, name, route=f"checkpoint {base + i}", saved=True)
                        cps.append(base + i)
                        due_cp = False
                        print(f"{p.frame}: checkpoint {name}", flush=True)
                    except Exception as e:
                        print(f"{p.frame}: checkpoint failed: {e}", flush=True)
            if any(k in st for k in ("type", "dial", "phone")) or st.get("_route_start"):
                due_cp = True
            if want and p.menu() is not None:
                labels = [M.norm(t) for t in p.items()]      # (a menu the game's Save is reached from:
                if "use metal gear" in labels or any(l.startswith("save") for l in labels):   # the bookmark
                    snap[0] = (p.emu.state(), i + (int(steps.split(":")[0] or 0) if steps else 0))      # is a BRAM save)
            M.run(p, [st], outdir=out + "_run")
            if limit and i + 1 >= limit:
                break
            if until and any(c["module"] == until[0] and c["nn"] == until[1] and p.frame - c["f0"] > SPAN
                             for c in lines):
                break                             # (the bookmark's line played through: done)
    finally:
        json.dump({"cue": cue, "japanese": japanese, "lines": lines}, open(out, "w"), indent=0)
        print(f"{out}: {len(lines)} lines", flush=True)


def mint(names):
    """Each bookmark's state (bm/<name>.mdf) saved through the game's own Save into a BRAM save
    work/pce/saves/bm_<name>.sav: a fresh boot of ANY build loads it (a state carries its build's
    stub; a BRAM save only the game's own state)."""
    import pcemenu as M, shutil
    bdir = os.path.join(WORK, "pce", "oracle", "bm")
    for name in names or [f[:-4] for f in os.listdir(bdir) if f.endswith(".mdf")]:
        meta = json.load(open(os.path.join(bdir, name + ".json")))
        p = M.Pilot(cue=meta.get("cue") or os.path.join(ROOT, "patched", "pce_v9", "snatcher_pce.cue"))
        p.restore(os.path.join(bdir, name + ".mdf"))
        M.game_save(p)
        M.dump_bram(p, f"bm_{name}", route=f"bookmark {name}", saved=True)
        print(f"{name}: work/pce/saves/bm_{name}.sav", flush=True)


def key_lines(run):
    seen, out = {}, {}
    for c in run["lines"]:
        if c["nn"] is None:
            continue
        k = (c["module"], c["nn"])
        i = seen.get(k, 0)
        seen[k] = i + 1
        out[(k[0], k[1], i)] = c
    return out


def speaker_of(module, nn):
    """The line's speaker as its subs_<module>.json names it (None: no entry)."""
    import pcesubs as S
    path = os.path.join(ROOT, "pce", "translation", f"subs_{module}.json")
    if not os.path.exists(path):
        return None
    for k, v in json.load(open(path, encoding="utf-8")).items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        try:
            if S.line_key(module, k)[1] == nn:
                return v.get("speaker")
        except Exception:
            continue
    return None


_TEXTS = []


def page_speaker(page):
    """The speaker of the subtitle on screen, from its words (subs and CD-DA cue files): a
    voice line's samples go on through the cues and lines after it. None: not ours / unknown."""
    import glob, re
    if not _TEXTS:
        for path in glob.glob(os.path.join(ROOT, "pce", "translation", "subs_*.json")) +                 glob.glob(os.path.join(ROOT, "pce", "translation", "cdda_*.json")):
            d = json.load(open(path, encoding="utf-8"))
            for k, v in (d.items() if isinstance(d, dict) else enumerate(d)):
                if isinstance(v, dict) and v.get("en"):
                    _TEXTS.append((re.sub(r"[^a-z]", "", v["en"].lower()), v.get("speaker") or ""))
    body = re.sub("<[^>]*>|[\x00-\x08]", " ", page.split("<fb")[0])   # (colour codes, row breaks)
    m = re.match(r"^\s*([A-Z][\w .'-]{1,20}):\s+(.*)$", body)
    if m:
        return m.group(1).strip()
    words = re.sub(r"[^a-z]", "", body.lower())
    if len(words) < 6:
        return None
    hits = {sp for en, sp in _TEXTS if words in en}
    return hits.pop() if len(hits) == 1 else None


def by_char(faces):
    """{character: its sprites} - a face drawn from two regions at once (Gillian's shock, #92)
    is one face."""
    out = {}
    for f in faces.values():
        out.setdefault(f["char"], []).extend(f["spr"])
    return out


def state(faces):
    """The faces as compared: each face's character and its sprites' x (the pattern and the y
    left out - a mouth animates through its cells, Metal Gear's face bobs a pixel; the stub
    moves x only, y is checked against the game's own frames apart)."""
    return tuple(sorted((ch, tuple(sorted(x for x, y, p in spr))) for ch, spr in by_char(faces).items()))


def ys(faces):
    return {ch: tuple(sorted(y for x, y, p in spr)) for ch, spr in by_char(faces).items()}


def rel(spr):
    """A face's sprites relative to its own left edge (x, y) - its animation frame."""
    left = min(x for x, y, p in spr)
    return tuple(sorted((x - left, y) for x, y, p in spr))


def expected(jp_faces, shown, speaker):
    """The faces the translation must show given the game's, as a comparable state."""
    if not shown:
        return state(jp_faces)
    spr = by_char(jp_faces).get(speaker)
    if not spr:
        return ()
    dx = FACE_X - min(x for x, y, p in spr)
    return ((speaker, tuple(sorted(x + dx for x, y, p in spr))),)


def compare(jp_path, en_path, report=None):
    jp, en = key_lines(json.load(open(jp_path))), key_lines(json.load(open(en_path)))
    fails, checked, lines_checked = [], 0, 0
    for key, ec in sorted(en.items(), key=lambda kv: kv[1]["f0"]):
        jc = jp.get(key)
        if jc is None:
            continue
        lines_checked += 1
        js = {s["k"]: s for s in jc["samples"]}
        for s in ec["samples"]:
            k = s["k"]
            around = [js.get(k + d) for d in range(-STEADY, STEADY + 1, STEP)]
            if any(a is None for a in around) or len({state(a["faces"]) for a in around}) != 1:
                continue
            shown = (s["up"] == 1) if s.get("up") is not None else                 (s["win"] == 0x56 and bool(s["page"].strip()) and s.get("lit", 99) > 0)   # (rows mapped in
                                          # the window's BAT: a line waiting for its face blanks them, the old page stays in the buffer)
            if not shown:
                continue                  # (between lines: reported by the timeline, not judged)
            speaker = s.get("spk")
            if speaker is None:                       # (an older recording: the speaker from the words)
                speaker = page_speaker(s["page"])
                if speaker is None:
                    continue
            if speaker == "":
                speaker = None                        # (no speaker: a card, no face expected)
            got = by_char(s["faces"])
            jfaces = by_char(js[k]["faces"])
            checked += 1
            if speaker in jfaces:
                # exactly one face, the speaker's, its left edge at FACE_X, and its cells laid out
                # as one of the game's own frames of that face nearby (a mouth moves with the voice)
                frames = {rel(by_char(js[k + d]["faces"])[speaker]) for d in range(-YWIN, YWIN + 1, STEP)
                          if k + d in js and speaker in by_char(js[k + d]["faces"])}
                ok = (set(got) == {speaker} and min(x for x, y, p in got[speaker]) == FACE_X
                      and rel(got[speaker]) in frames)
                want = (speaker, f"left {FACE_X}", f"{len(frames)} frames of the game's")
            else:
                ok = not got                      # a card: no face on the band
                want = ()
            if not ok:
                fails.append((key, k, s["frame"], speaker, shown, want,
                              {ch: rel(sp) and (min(x for x, y, p in sp), rel(sp)) for ch, sp in got.items()}))
    lines = [f"{lines_checked} lines matched, {checked} samples checked, {len(fails)} failures"]
    for (mod, nn, i), k, frame, speaker, shown, want, got in fails:
        lines.append(f"FAIL module {mod} line {nn:02x}#{i} +{k} (frame {frame}) speaker {speaker} "
                     f"{'subtitle up' if shown else 'no subtitle'}\n  want {want}\n  got  {got}")
    text = "\n".join(lines)
    if report:
        open(report, "w", encoding="utf-8").write(text + "\n")
    print(text if len(fails) < 40 else "\n".join(lines[:41]) + f"\n... {len(fails) - 40} more")
    return not fails


def rules(paths, report=None):
    """Luiz's rule (2026-10-18), no reference needed: a voiced line's text on screen always has its
    speaker's name on top of the card or a portrait on the left - words alone mean the portrait
    went missing (or a card's later page lost its name)."""
    import re
    out, total, bad = [], 0, 0
    for path in paths:
        for c in json.load(open(path))["lines"]:
            for s in c["samples"]:
                page = s.get("page") or ""
                if s.get("up") != 1 or not page.split("<fb")[0].strip():
                    continue
                total += 1
                named = bool(re.match(r"^\s*.[A-Z][\w .'-]{1,20}:", page))   # (the name's colour code, then "Name:")
                left = any(min(x for x, y, p in f["spr"]) == FACE_X for f in s["faces"].values())
                if not named and not left:
                    bad += 1
                    out.append(f"WORDS ALONE module {c['module']} line {c['nn'] if c['nn'] is None else format(c['nn'], '02x')} "
                               f"+{s['k']} (frame {s['frame']}) {page.split('<fb')[0].strip()[:40]!r} faces "
                               f"{ {f['char']: min(x for x, y, p in f['spr']) for f in s['faces'].values()} }")
    head = f"{total} samples with words up, {bad} with neither the speaker's name nor a portrait"
    if report:
        open(report, "w", encoding="utf-8").write("\n".join([head] + out) + "\n")
    print(head)
    return not bad


def main():
    a = sys.argv[1:]
    def opt(name, default=None):
        return a[a.index(name) + 1] if name in a else default
    if a[0] == "record":
        record(a[1], a[2], bram=opt("--bram"), route=opt("--route"), steps=opt("--steps"),
               japanese="--japanese" in a, pre=json.loads(opt("--pre", "null")),
               bookmark=opt("--bookmark"), limit=int(opt("--limit", "0")) or None,
               checkpoint=opt("--checkpoint"),
               until=(lambda u: u and (int(u.split(":")[0]), int(u.split(":")[1], 16)))(opt("--until-line")))
    elif a[0] == "rules":
        sys.exit(0 if rules([x for x in a[1:] if not x.startswith("--") and x != opt("--report")], opt("--report")) else 1)
    elif a[0] == "mint":
        mint(a[1:])
    elif a[0] == "compare":
        sys.exit(0 if compare(a[1], a[2], opt("--report")) else 1)


if __name__ == "__main__":
    main()
