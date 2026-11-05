"""Boot with an Act 1 end save, CONTINUE, and watch the Act 2 recap: scene
index, bank, reel number, stream position, band/box state, blobptr, cells.
regress_saves.py runs it for the Act 1 end save (no verb menu to reach there).

    python saturn/harness/probe_recap.py SAVE_NAME [SLOT] [FRAMES]
"""
import os, sys, json, time, struct
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path[:0] = [os.path.join(ROOT, d) for d in ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]
import satrun, satmem, satpilot, satplay, satsave, satsave_check
NAME, SLOT = sys.argv[1] if len(sys.argv) > 1 else "mister_0916l", int(sys.argv[2]) if len(sys.argv) > 2 else 1
FRAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
out = os.path.join(ROOT, "work", "saturn", "subs_b140", "recap")
os.makedirs(out, exist_ok=True)
logf = open(os.path.join(out, "log.txt"), "w", encoding="utf-8")
def log(m):
    logf.write(m + "\n"); logf.flush(); print(m, flush=True)
image = satsave.PLAY_IMAGE
s = satsave.entry_of(NAME)
bkr = os.path.join(satsave.EMU_SAVES, satsave.image_stem(image) + ".bkr")
os.makedirs(satsave.EMU_SAVES, exist_ok=True)
open(bkr, "wb").write(satsave.read_image(s["path"]))
emu = satrun.SaturnEmu(); emu.load(image)
play = satplay.Play(emu, out, log, image, autosave=False)
assert satsave_check.continue_from_title(play, log)
satsave_check.load_file(play, SLOT, log)
m = play.mem
blobptr = json.load(open(os.path.join(ROOT, "work", "saturn", "build", "subs_layout.json")))["blobptr"]
OBJ0 = satmem.CTX + 0x830
last = None
t0 = time.time()
while play.f < FRAMES:
    play.run(10)
    st = (m.u16(satmem.SCENE_INDEX), play.bank, m.u16(0x060EFE6A), m.u32(0x060EFE64), m.u8(0x060F2A08),
          m.u32(OBJ0 + 12), hex(m.u32(OBJ0 + 24)), hex(m.u32(blobptr)), m.u8(satmem.MENU_LIVE), m.u8(satmem.CTX + 0xB74))
    pos = m.u32(0x060EFF0C)
    if st != last:
        rows = [r for r in satmem.cells(m) if r]
        log(f"{play.f}: scene={st[0]} bank={st[1]} reel={st[2]} loaded={st[3]} band={st[4]} y={st[5]} list={st[6]} blobptr={st[7]} menu={st[8]} wait={st[9]} pos={pos} cells={rows[:3]}")
        emu.image().save(os.path.join(out, f"f{play.f:06d}.png"))
        last = st
    if play.f % 600 == 0:
        emu.image().save(os.path.join(out, f"f{play.f:06d}.png"))
        log(f"{play.f}: pos={pos} cells={[r for r in satmem.cells(m) if r][:3]}")
    if st[9] == 1 and play.f % 120 == 0:      # a card waits: press through
        play.press(satpilot.OK)
log(f"done in {time.time() - t0:.0f}s")
