# -*- coding: utf-8 -*-
"""Autopilot: play the game headlessly and bookmark every location it reaches.

  python ps1/harness/explore.py --slot 1 --frames 120000
  python ps1/harness/explore.py --list

Drives Beetle PSX with the same state machine the subtitle harness uses, and
watches which scene bank is loaded at 0x8010D000. Every time that changes to a
bank it has not seen, it names the scene and writes an emulator savestate to
work/states/<scene>.state.gz. The result is a checkpoint per location, built
without a human at the controller.

Scene identity is the sha1 of the bank's first 256 bytes, which is unique
across all 37 banks (checked, no collisions).

**These states survive a rebuild**, unlike a Redux savestate: the bank is
re-injected into RAM after restoring (see restore_scene), so a state captured
against an old build runs the current payload. That is what makes them worth
keeping rather than re-deriving.

A memory card can also be written back with --card-out, but the game only
offers its own save in a few places, so the states are the general mechanism
and the card is the one the player sees.
"""
import argparse, ctypes as C, glob, gzip, hashlib, json, os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import emurun
import raminject

STATES = os.path.join(WORK, 'states')
INDEX = os.path.join(STATES, 'index.json')
BANK_RAM = 0x8010D000
SCRATCH = 0x801FC000
from hiram import HIRAM              # the payload blob
MAGIC = 0x53554253
ADVANCE = 70
MENU_SETTLE = 40
PRESS = 8


def signatures():
    """sha1 of the first 256 bytes -> bank name, for every bank: the patched
    copy where one exists, the pristine one otherwise. A bank with nothing
    to translate (B210, three strings) is never written to patched/, and
    it is exactly the kind the harness must still recognise: the basement's
    face reconstruction ran under it unsubtitled for months (BUG-050)."""
    out = {}
    pristine = os.path.join(ROOT, 'discs', 'extracted_ps1', 'PLN', 'ISZ')
    for p in sorted(glob.glob(os.path.join(pristine, 'ISZ_B*.BIN'))):
        name = os.path.basename(p)[4:-4]     # ISZ_B0C0.BIN -> B0C0
        pp = os.path.join(raminject.PATCHED, os.path.basename(p))
        b = open(pp if os.path.exists(pp) else p, 'rb').read()
        out[hashlib.sha1(b[:256]).hexdigest()] = name
    return out


def save_index(index):
    """Merge into the on-disk index rather than overwriting it.

    Two explorers running at once (Act 2 from one save, Act 3 from another)
    each held their own copy and the second writer erased the first's scenes.
    """
    disk = {}
    if os.path.exists(INDEX):
        try:
            disk = json.load(open(INDEX, encoding='utf-8'))
        except ValueError:
            disk = {}
    for scene, e in index.items():
        d = disk.setdefault(scene, {})
        # This run's tally is authoritative for the scenes it saw. Adding it
        # to disk was wrong: save_index runs every 30 frames with the whole
        # cumulative tally, so counts compounded into the 1e15 range.
        words = dict(d.get('words', {}))
        words.update(e.get('words', {}))
        d.update({k: v for k, v in e.items() if k != 'words'})
        if words:
            d['words'] = words
    json.dump(disk, open(INDEX, 'w', encoding='utf-8'), indent=1)
    return disk


def restore_scene(emu, scene, blob=None):
    """Restore a bookmarked location, with the CURRENT bank swapped in.

    A savestate carries the bank that was in RAM when it was taken, so it would
    otherwise replay whatever payload that build had. Injecting the freshly
    built bank - and clearing the payload scratch so timers and latches start
    clean - makes a state a location bookmark rather than a build snapshot.
    """
    if blob is None:
        blob = gzip.decompress(open(os.path.join(STATES, f'{scene}.state.gz'),
                                    'rb').read())
    emu.restore(blob)
    c = emu.core
    c.retro_get_memory_data.restype = C.c_void_p
    ram = c.retro_get_memory_data(2)

    def put(addr, data):
        C.memmove(C.c_void_p(ram + (addr & 0x1FFFFF)), data, len(data))
    raminject.refresh(put, scene)
    return len(blob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', type=int, default=120000)
    ap.add_argument('--slot', type=int, help='start from this memory card file')
    ap.add_argument('--image', default='patched/Snatcher (Japan).cue')
    ap.add_argument('--card', default=devpaths.get('SNATCHER_CARD', ''))
    ap.add_argument('--card-out', help='write the card back here at the end')
    ap.add_argument('--out', default=os.path.join(WORK, 'explore'))
    ap.add_argument('--list', action='store_true', help='list bookmarks and exit')
    a = ap.parse_args()

    os.makedirs(STATES, exist_ok=True)
    index = json.load(open(INDEX, encoding='utf-8')) if os.path.exists(INDEX) else {}

    if a.list:
        if not index:
            print('no bookmarks yet')
        for scene, m in sorted(index.items()):
            p = os.path.join(STATES, f'{scene}.state.gz')
            ok = 'ok' if os.path.exists(p) else 'MISSING'
            print(f"{scene}  [{ok}]  frame {m['frame']:6}  {m.get('note', '')}")
        return

    os.makedirs(a.out, exist_ok=True)
    sigs = signatures()

    events = {2600: 'press:start', 2615: 'release'}
    if a.slot:
        events.update({4200: 'press:down', 4215: 'release',
                       4400: 'press:circle', 4415: 'release'})
        # cursor opens on EXIT, so FILE.n is 5-n ups
        t = 5000
        for _ in range(5 - a.slot):
            events[t] = 'press:up'; events[t + 15] = 'release'; t += 60
        t += 60
        events[t] = 'press:circle'; events[t + 15] = 'release'
        first_load = t
    else:
        events.update({2800: 'press:circle', 2815: 'release'})   # NEW GAME
        first_load = 14000                                       # intro is long
    # boot_done is set when a known bank actually appears in RAM. A fixed
    # frame does not work: the MEMORY CARD screen is still animating in and
    # swallows the press, after which the prober backs out to the title.
    boot_done = None

    emu = emurun.Emu()
    emu.load(a.image)
    emu.load_card(a.card)
    core = emu.core
    core.retro_get_memory_data.restype = C.c_void_p
    ram = None

    log = open(os.path.join(a.out, 'log.txt'), 'w', encoding='utf-8')

    def L(m):
        log.write(m + '\n'); log.flush(); print(m, flush=True)

    # every verb in turn - the menu differs per location, so B010's Talk
    # pattern reaches nothing at Gibson's house
    # Luiz: "most of the time to advance the story we need to click on all
    # menu options at least twice, show items, etc." So sweep every slot of
    # the menu, twice per round - a second visit to a verb often yields new
    # dialogue, which is what actually moves a scene on.
    PLAN = []
    for _ in range(200):
        for _pass in range(2):
            for d in range(7):
                PLAN.append((d, 'circle'))

    queue, press_until, last_press = [], 0, 0
    plan_i = menu_frames = 0
    last_sig = None
    sig_since = 0
    cur = None
    found = []

    for f in range(a.frames):
        act = events.get(f)
        if act:
            emu.held = ({emurun.BTN[b] for b in act[6:].split('+')}
                        if act.startswith('press:') else set())
        if queue and f >= queue[0][0]:
            _, btn = queue.pop(0)
            emu.held = {emurun.BTN[btn]}
            press_until, last_press = f + PRESS, f
        elif f == press_until:
            emu.held = set()

        emu.run()
        if ram is None:
            ram = core.retro_get_memory_data(2)

        if f % 30 == 0 and boot_done is None and f > first_load:
            head = C.string_at(C.c_void_p(ram + (BANK_RAM & 0x1FFFFF)), 256)
            if hashlib.sha1(head).hexdigest() in sigs:
                boot_done = f + 300
                L(f'{f}: in game')
            elif not queue and (f - last_press) > 250:
                queue.append((f + 2, 'circle'))      # confirm again

        if f % 30 == 0 and boot_done is not None and f > boot_done:
            head = C.string_at(C.c_void_p(ram + (BANK_RAM & 0x1FFFFF)), 256)
            scene = sigs.get(hashlib.sha1(head).hexdigest())
            if scene and scene != cur:
                cur = scene
                L(f'{f}: in {scene}')
            # Bookmark at the verb menu, not on arrival. Arrival is usually
            # mid-cutscene: B0C0's landed on "Another time." - Gillian
            # declining to enter - where the only available action is the one
            # that leaves the location, so a run restored there just bounced
            # in and out 73 times. The menu bit (0x00200000) marks a state
            # where a pilot can actually choose something.
            here_win = struct.unpack_from(
                '<I', C.string_at(ram, 0x200000),
                (struct.unpack_from('<I', C.string_at(ram, 0x200000),
                                    0x800ABF64 & 0x1FFFFF)[0] + 0x1ACC) & 0x1FFFFF)[0]
            # Record the scene's verb-menu word the first time it is seen.
            # options.mode for a subtitle payload derives from this
            # ((menu_word >> 9) & 0x3F), and guessing it has cost two
            # regressions - so the pilot measures it instead of a human.
            if scene:
                e = index.setdefault(scene, {'frame': f, 'from': 'scan'})
                w = e.setdefault('words', {})
                key = f'0x{here_win & 0xFFFF:04x}'
                w[key] = w.get(key, 0) + 1
                if here_win & 0x00200000 and 'menu_word' not in e:
                    e['menu_word'] = key
                    e['mode'] = ((here_win & 0xFFFF) >> 9) & 0x3F
                    L(f"    menu word {key} -> mode {e['mode']}")
                save_index(index)
            if scene and (here_win & 0x00200000):
                if not os.path.exists(os.path.join(STATES, f'{scene}.state.gz')):
                    blob = gzip.compress(emu.state(), 6)
                    open(os.path.join(STATES, f'{scene}.state.gz'), 'wb').write(blob)
                    index.setdefault(scene, {}).update(
                        {'frame': f, 'bytes': len(blob),
                         'from': f'slot {a.slot}' if a.slot else 'new game'})
                    save_index(index)
                    found.append(scene)
                    L(f'    bookmarked -> work/states/{scene}.state.gz '
                      f'({len(blob) // 1024} KB)')
                if emu.frame:
                    emu.image().save(os.path.join(a.out, f'{scene}_{f:06d}.png'))

        r = C.string_at(ram, 0x200000)
        ctx = struct.unpack_from('<I', r, 0x800ABF64 & 0x1FFFFF)[0]
        if ctx != 0x80010000:
            continue
        win = struct.unpack_from('<I', r, (ctx + 0x1ACC) & 0x1FFFFF)[0]
        low = win & 0xFFFF
        box = not (win & 0x00200000) and low in (0x8701, 0x8901, 0x8300,
                                                 0x8b01, 0x8d01, 0x8900)
        idle = low in (0x8001, 0x8000, 0x0000)
        menu = not (box or idle)
        other = False

        if win != last_sig:
            last_sig, sig_since = win, f
        if boot_done is None or f < boot_done:
            continue

        if menu:
            menu_frames += 1
            if menu_frames == MENU_SETTLE and not queue and plan_i < len(PLAN):
                downs, btn = PLAN[plan_i]; plan_i += 1
                L(f'{f}: menu action #{plan_i - 1}: {downs} downs + {btn}')
                t = f + 5
                for _ in range(4):
                    queue.append((t, 'up')); t += 18
                for _ in range(downs):
                    queue.append((t, 'down')); t += 18
                queue.append((t, btn))
            if menu_frames > MENU_SETTLE and (f - last_press) > 400:
                menu_frames = 0
        else:
            menu_frames = 0
            if box and not queue and (f - sig_since) > 90 and (f - last_press) > ADVANCE:
                queue.append((f + 2, 'circle'))
            if (idle and not queue and (f - sig_since) > 300
                    and (f - last_press) > 300):
                queue.append((f + 2, 'circle'))
            if other and not queue and (f - sig_since) > 120 and (f - last_press) > ADVANCE:
                tries = (f - sig_since) // ADVANCE
                queue.append((f + 2, 'cross' if tries % 4 == 3 else 'circle'))

    if a.card_out:
        emu.save_card(a.card_out)
        L(f'card written to {a.card_out}')
    L(f'end: {len(found)} new bookmark(s) this run: {found}')
    L(f'library now: {sorted(index)}')
    log.close()


if __name__ == '__main__':
    main()
