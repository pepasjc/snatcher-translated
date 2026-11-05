"""Investigate persistent Saturn font damage from a fresh scene-save boot.

Compare VDP1 font bytes with DATA.BIN chunk 0 every --every frames while
satplay follows a route. Capture the first mismatch and the final state.
This checks pixels that satplay's RAM text decoder cannot validate.

  python saturn/harness/fontwatch.py --save B230_auto --route saturn/harness/routes/B230.json

Boot from backup RAM, rather than restoring a bookmark's older font. Each
run uses its own backup-RAM directory and leaves the scene-save library alone.
"""
import argparse
import contextlib
import hashlib
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in
               ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]


def expected_font(image):
    """Read the exec and font from the same image, including relocated DATA.BIN."""
    import satmem
    import lz3
    exe = satmem.image_exec(image)
    sector, words = struct.unpack_from(">HH", exe, satmem.CHUNK_TABLE - 0x060B0000)
    base = struct.unpack_from(">I", exe, 0x4590)[0] - 0x25C00000
    # ISO9660 root directory: this game's records can span several sectors.
    with open(satmem.image_track1(image), "rb") as track:
        def read_sectors(lba, size):
            out = bytearray()
            for i in range((size + 2047) // 2048):
                track.seek((lba + i) * 2352 + 16)
                out.extend(track.read(2048))
            return bytes(out[:size])
        pvd = read_sectors(16, 2048)
        if pvd[1:6] != b"CD001":
            raise ValueError("Expected a MODE1/2352 ISO9660 track")
        root_lba = struct.unpack_from("<I", pvd, 158)[0]
        root_size = struct.unpack_from("<I", pvd, 166)[0]
        directory = read_sectors(root_lba, root_size)
        pos = 0
        while pos < len(directory):
            length = directory[pos]
            if not length:
                pos = (pos // 2048 + 1) * 2048
                continue
            rec = directory[pos:pos + length]
            if rec[33:33 + rec[32]].split(b";")[0] == b"DATA.BIN":
                data_lba = struct.unpack_from("<I", rec, 2)[0]
                font = lz3.decode(read_sectors(data_lba + sector, words * 2))
                if not 0 <= base < base + len(font) <= 0x80000:
                    raise ValueError("Font outside VDP1 VRAM")
                return base, font
            pos += length
    raise ValueError("DATA.BIN not found in image")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", required=True)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue"))
    ap.add_argument("--route", required=True)
    ap.add_argument("--frames", type=int, default=100000, help="Route frame budget after boot (satplay semantics)")
    ap.add_argument("--every", type=int, default=120)
    ap.add_argument("--out", default=os.path.join(WORK, "saturn", "issues", "88", "fontwatch"))
    a = ap.parse_args()
    if a.every < 1 or a.frames < 1:
        ap.error("--every and --frames must be positive")
    a.out = os.path.abspath(a.out)
    os.makedirs(a.out, exist_ok=True)
    # Set before importing the harness: emurun and satsave read it at import.
    os.environ["EMU_SAVE_DIR"] = os.path.join(a.out, "emu")
    import satrun
    import satplay
    import satmem
    import satsave
    import satsave_check
    import satfont
    satplay.STATES = os.path.join(a.out, "states")
    os.makedirs(satplay.STATES, exist_ok=True)
    side_table = os.path.splitext(a.image)[0] + ".pair_table.json"
    if os.path.exists(side_table):
        satplay.SAT_TABLE = side_table
    base, expected = expected_font(a.image)
    record = satsave.entry_of(a.save)
    slot = a.slot or record.get("slot") or 1
    os.makedirs(satsave.EMU_SAVES, exist_ok=True)
    with open(os.path.join(satsave.EMU_SAVES, satsave.image_stem(a.image) + ".bkr"), "wb") as fh:
        fh.write(satsave.read_image(record["path"]))
    with open(a.route, encoding="utf-8") as fh:
        route = json.load(fh)
    # Route checkpoints must not replace the library's bookmarks or saves.
    route["actions"] = [x for x in route["actions"] if not any(k in x for k in ("save", "bsave", "mcard"))]
    result = dict(image=os.path.abspath(a.image), save=a.save, slot=slot,
                  font_base=hex(base), font_size=len(expected),
                  expected_sha1=hashlib.sha1(expected).hexdigest(), checks=0,
                  first_damage=None)
    with open(os.path.join(a.out, "log.txt"), "w", encoding="utf-8") as logf:
        def log(message):
            logf.write(str(message) + "\n")
            logf.flush()
        with contextlib.redirect_stdout(logf), contextlib.redirect_stderr(logf):
            emu = satrun.SaturnEmu()
            emu.load(a.image)
            play = satplay.Play(emu, a.out, log, a.image, autosave=False)
            started = time.time()
            if not satsave_check.continue_from_title(play, log):
                raise RuntimeError("CONTINUE did not open")
            satsave_check.load_file(play, slot, log)
            for _ in range(120):
                play.run(30)
                if play.bank and play.bank != 21 and play.mem.u8(satmem.MENU_LIVE) == 1 and play.is_top(play.labels_now()):
                    break
            else:
                raise RuntimeError("Scene save did not reach a verb menu")
            result["start_bank"] = satplay.BANK_NAMES.get(play.bank)
            original_run = play.run
            next_check = play.f

            def check(frame):
                nonlocal next_check
                if frame < next_check:
                    return
                next_check = frame + a.every
                state = emu.state()
                actual = satfont.vdp1_vram(state)[base:base + len(expected)]
                result["checks"] += 1
                if actual != expected and result["first_damage"] is None:
                    offsets = [i + base for i, (x, y) in enumerate(zip(actual, expected)) if x != y]
                    result["first_damage"] = dict(frame=frame, bank=satplay.BANK_NAMES.get(play.bank),
                                                  changed_bytes=len(offsets), first=hex(min(offsets)), last=hex(max(offsets)))
                    with open(os.path.join(a.out, "damaged.state"), "wb") as fh:
                        fh.write(state)
                    emu.image().save(os.path.join(a.out, "damaged.png"))
                    log("FONT DAMAGE " + json.dumps(result["first_damage"]))

            def run(n=1, hook=None):
                def each(frame):
                    check(frame)
                    if hook:
                        hook(frame)
                original_run(n, each)

            play.run = run
            check(play.f)
            satplay.run_route(route, play, a.frames, log, None, False)
            next_check = play.f
            check(play.f)
            result["end_frame"] = play.f
            with open(os.path.join(a.out, "final.state"), "wb") as fh:
                fh.write(emu.state())
            emu.image().save(os.path.join(a.out, "final.png"))
            play.finish(started)
            log(json.dumps(result))
    with open(os.path.join(a.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps(result, indent=2))
    return 1 if result["first_damage"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
