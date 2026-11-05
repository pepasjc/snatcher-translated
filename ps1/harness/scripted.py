# -*- coding: utf-8 -*-
"""Run a scene from an explicit script of menu paths, and report what it saw.

    python ps1/harness/scripted.py --scene B020 --from-state
    python ps1/harness/scripted.py --scene B020 --slot 4 --frames 60000

The route-following pilot parses a walkthrough written in prose, and that is
where it kept failing: "LOOK or INVESTIGATE any option (x8)" is alternatives,
not a path, so it pressed Look then Investigate in the verb menu and never picked a
target. Guessing the author's grammar is not worth it when the scene is
twenty deterministic menu picks.

So a scene script (ps1/harness/routes/<scene>.json) lists the paths directly, in our
own labels:

    {"path": ["Look", "Little John"]}
    {"path": ["Move", "Forward"], "reps": 2}
    {"path": ["Investigate", "Clothing"], "optional": true}

The runner walks them in order. A path descends one menu at a time; a label
that is not on screen is reported WITH the labels that were, so a wrong guess
is a one-line edit instead of a silent stall. `optional` actions are skipped
after a few tries rather than blocking the run.

Selection is closed-loop on the ENGINE'S cursor (ps1/harness/menustate.py): read
which item is highlighted, press down until it is the one wanted, confirm.
Earlier versions steered by the menu table (which lags), by an assumed start
position (the cursor wraps and is remembered across submenus), and by finding
the label's pixels on screen (short words do not correlate and the box moves
with the layout). Each was a way of guessing what the engine already knows.

It also logs every cue the subtitle payload draws and runs panel_check over
the captures, so a scripted pass doubles as the play-test.
"""
import argparse, ctypes as C, glob, gzip, hashlib, json, os, re, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
import numpy as np
from PIL import Image
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import emurun
from explore import signatures, restore_scene, BANK_RAM
from menuread import read_menu, read_cells, geometry, find, clean
import menustate
BOOT_SHIFT = int(os.environ.get('BOOT_SHIFT', 1050))  # frames the boot card + splash add before the title
from panel_check import scan as panel_scan

MENU_SETTLE = 12     # frames a menu must be live before we act on it
PRESS = 8
ADVANCE = 70
PATIENCE = 3000      # frames to WAIT for an action's label to appear. The
                     # harness used to fire each action once and move on:
                     # `Enter` went before the scream had happened, so it
                     # never took, and every later action then ran against
                     # the wrong screen and burned itself. A person following
                     # a guide waits until the option is actually there.
SYNC_MIN = int(os.environ.get('SYNC_MIN', 30))       # frames of a cue's line heard before it must show
SYNC_LATE = int(os.environ.get('SYNC_LATE', 90))     # frames a card may trail its line's start
FROZEN_FRAMES = int(os.environ.get('FROZEN_FRAMES', 1800))   # our card in WAIT, nothing playing, no menu
HANG_FRAMES = int(os.environ.get('HANG_FRAMES', 3600))       # game frame counter stopped
WATCHDOG = int(os.environ.get('WATCHDOG', 0))   # stop after this many frames without a live menu
MAX_STEPS = 24       # cursor presses before an action is declared stuck
STEP_GAP = 30        # frames between cursor presses (release edge + move)
HOLD_AFTER_CUE = int(os.environ.get('HOLD_AFTER_CUE', 300)) # no presses this long after a subtitle draws
FF_RANGE = [int(x) for x in os.environ['FF_START'].split('-')] if '-' in os.environ.get('FF_START', '') else None
STATE_AT = {int(x) for x in os.environ.get('STATE_AT', '').split(',') if x}
FACEPOKE = [int(x, 0) for x in os.environ.get('FACEPOKE', '').split(',') if x]   # faces POC probe
CLOBBER_AT = {int(x) for x in os.environ.get('CLOBBER_AT', '').split(',') if x}   # width-crop probe
DBGFRAMES = [int(x) for x in os.environ.get('DBGFRAMES', '').split('-') if x]   # per-frame box state
CELTRACE = bool(os.environ.get('CELTRACE'))   # log the nine face cels whenever one changes (#36-#38)
CAPAT = {int(x) for x in os.environ.get('CAPAT', '').split(',') if x}   # CAPAT=f1,f2: PNG captures at those frames
# RAMTOUCH=N,path: every N frames OR the bytes that changed since the last
# sample into a 2 MB mask (uint8, 1 = written at least once) saved to `path`
# at the end - the free-RAM census for the longs-out-of-bank work.
RAMTOUCH = os.environ.get('RAMTOUCH', '')
# STATES_DIR: where this run WRITES bookmarks (route saves, the _auto ones, the
# fight prompt); loads always come from work/states. regress.py --jobs points
# runs that share a bank (b010p, harry) at their own out dir, or two runs
# os.replace() the same B010_harry.state.gz and one of them dies.
STATES_DIR = os.environ.get('STATES_DIR') or os.path.join(WORK, 'states')
if FACEPOKE and len(FACEPOKE) == 2:
    FACEPOKE.append(0x1FF)
# Labels that only ever appear in a location's TOP-LEVEL verb menu. If none of
# them is on screen we are inside a submenu, and backing out is safe; crossing
# out of the top menu just closes it and the game reopens it, forever.
VERBS = {'look', 'check', 'move', 'item', 'use metal gear', 'enter',
         'get in', 'get out', 'hear', 'talk', 'ask', 'smell', 'sniff', 'eat', 'buy'}
# Sweeps never pick these on their own: they leave the location, or open the
# memory-card screen. A route names them explicitly when it wants them.
# Verbs that always open a submenu: a confirm on one of these that just
# reopens the same top menu did not take (swapped buttons, see below).
SUBMENU_VERBS = {'look', 'check', 'ask', 'move', 'item', 'use metal gear'}
AVOID = {'go out', 'get in', 'get out', 'leave', 'exit', 'save', 'videophone',
         'home', 'junker hq', 'ruins'}
from hiram import HIRAM              # the payload blob
LIFE_REF = np.asarray(Image.open(os.path.join(HERE, 'life_ref.png')).convert('RGB'), np.int16)
MAGIC = 0x53554253


def image_stamp(cue):
    """Identity of the disc image a bookmark was taken against."""
    bins = sorted(glob.glob(os.path.join(os.path.dirname(cue) or '.', '*.bin')))
    return [(os.path.basename(b), os.path.getsize(b), int(os.path.getmtime(b))) for b in bins]


def slidelog_stub():
    """The SLIDELOG ring logger for 0x80033848 (see main): k0/k1 only, then
    the displaced `beqz a0, 0x80033A10` and a jump back to 0x80033850."""
    from mipsasm import Asm
    a = Asm(0x801FD800)
    a.lui("$k0", 0x8020)
    a.lw("$k1", -0x3000, "$k0"); a.nop()
    a.andi("$k1", "$k1", 63); a.sll("$k1", "$k1", 4); a.addu("$k1", "$k1", "$k0")
    a.sw("$ra", -0x2FF0, "$k1"); a.sw("$a0", -0x2FEC, "$k1")
    a.sw("$a2", -0x2FE8, "$k1"); a.sw("$a3", -0x2FE4, "$k1")
    a.lw("$k1", -0x3000, "$k0"); a.nop(); a.addiu("$k1", "$k1", 1); a.sw("$k1", -0x3000, "$k0")
    a.bne("$a0", "$zero", "cont"); a.nop()
    a.j(0x80033A10); a.nop()
    a.label("cont"); a.j(0x80033850); a.nop()
    return a.assemble()


def nametrace_stub():
    """The NAMETRACE ring logger on the type-0 handler's nameplate strcmp
    (`jal 0x80058634` at 0x800475EC, s0 = the queued object): k0/k1 only,
    stores {name_ptr, mode} per line, then jumps on to strcmp (ra is the
    hook site's). Count word at 0x801FD400, 64 entries of 8 B from
    0x801FD410; the stub sits at 0x801FDC00."""
    from mipsasm import Asm
    a = Asm(0x801FDC00)
    a.lui("$k0", 0x8020)
    a.lw("$k1", -0x2C00, "$k0"); a.nop()
    a.andi("$k1", "$k1", 63); a.sll("$k1", "$k1", 3); a.addu("$k1", "$k1", "$k0")
    a.sw("$a0", -0x2BF0, "$k1")
    a.lw("$k0", 0xC, "$s0"); a.nop()
    a.sw("$k0", -0x2BEC, "$k1")
    a.lui("$k0", 0x8020)
    a.lw("$k1", -0x2C00, "$k0"); a.nop(); a.addiu("$k1", "$k1", 1); a.sw("$k1", -0x2C00, "$k0")
    a.j(0x80058634); a.nop()
    return a.assemble()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scene', required=True)
    ap.add_argument('--slot', type=int)
    ap.add_argument('--new', action='store_true', help='boot a New Game instead of a card save')
    ap.add_argument('--from-state', action='store_true')
    ap.add_argument('--state', help='resume from work/states/<name>.state.gz (implies --from-state)')
    ap.add_argument('--state-file', help='resume from this .state.gz exactly as saved: no bank, '
                    'payload or exec refresh (chained runs on one image; the dev-test exec survives)')
    ap.add_argument('--start', type=int, default=0, help='skip the first N route actions')
    ap.add_argument('--end', type=int, help='stop the route before this action (a segment of a long route)')
    ap.add_argument('--frames', type=int, default=60000)
    ap.add_argument('--out')
    ap.add_argument('--image', default='patched/Snatcher (Japan).cue')
    ap.add_argument('--card', default=devpaths.get('SNATCHER_CARD', ''))
    ap.add_argument('--shot-every', type=int, default=180)
    ap.add_argument('--route', help='route json (default ps1/harness/routes/<scene>.json)')
    ap.add_argument('--stop-after', type=int, help='stop this many frames after the last action')
    ap.add_argument('--trace', action='store_true', help='log every press and menu transition')
    ap.add_argument('--mcard', action='store_true',
                    help='save through the game at the first verb menu of every bank (= MCSAVE=1)')
    a = ap.parse_args()
    if a.state or a.state_file:
        a.from_state = True
    if not (a.slot or a.from_state or a.new):
        sys.exit('need --slot, --new or --from-state')

    out = a.out or os.path.join(WORK, f's_{a.scene.lower()}')
    os.makedirs(out, exist_ok=True)
    os.makedirs(STATES_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(out, '*.png')):   # panel_check reads them all
        os.remove(old)
    route = a.route or os.path.join(HERE, 'routes', f'{a.scene}.json')
    script = json.load(open(route, encoding='utf-8'))
    actions = script['actions']
    if a.end is not None:
        actions = actions[:a.end]
    for _i, _x in enumerate(actions):
        _x['_i'] = _i                   # route index, kept through sweep expansion (checkpoints)

    log = open(os.path.join(out, 'log.txt'), 'w', encoding='utf-8')

    def L(m):
        log.write(m + '\n'); log.flush(); print(m, flush=True)

    L(f"{a.scene}: {len(actions)} scripted actions")

    events = {}
    first_load = 0
    # The v0.7 boot card (ps1/tools/bootcard.py) holds the screen ~3 s and the
    # Snatcher splash (bootsplash.py) ~11 s before the Konami movie, so every
    # fixed-frame press below runs BOOT_SHIFT later.
    B = BOOT_SHIFT
    if a.slot:
        events = {B + 2600: 'press:start', B + 2615: 'release',
                  B + 4200: 'press:down', B + 4215: 'release',
                  B + 4400: 'press:circle', B + 4415: 'release'}
        t = B + 5000
        for _ in range(5 - a.slot):
            events[t] = 'press:up'; events[t + 15] = 'release'; t += 60
        t += 60
        events[t] = 'press:circle'; events[t + 15] = 'release'
        first_load = t
    if a.new:
        # title -> NEW GAME (the first item) -> disclaimer and intro; the
        # generic boot presser then taps circle until a scene bank loads
        events = {B + 2600: 'press:start', B + 2615: 'release',
                  B + 4400: 'press:circle', B + 4415: 'release'}
        first_load = B + 4400

    # cue ids for the log (the index alone shifts whenever a cue file is
    # re-cut; coverage.py keys on ids)
    ids_of = {}
    def cue_id(scene, idx):
        if scene not in ids_of:
            p = os.path.join(ROOT, 'ps1', 'translation', f'subs_{scene}.json')
            try:
                ids_of[scene] = [c['id'] for c in json.load(open(p, encoding='utf-8'))['cues']
                                 if c.get('enabled', True)]     # the blob's indices skip muted cues
            except OSError:
                ids_of[scene] = []
        ids = ids_of[scene]
        return ids[idx] if 0 <= idx < len(ids) else ('blank' if idx == len(ids) else '?')

    # The speaker gate (always on). For every card of this scene's cue file
    # the run draws, two per-frame tallies while the card is up:
    #   eng  - the character the ENGINE animates (menu word bits 20-22 = the
    #          band column whose mouth moves, through the room's face list
    #          to its CXN file and the cast table): the script names the
    #          speaker of every voice line this way, independent of our data
    #   face - the character OUR layout put at FACE_X (the column whose base
    #          cel sits at x=24 and is visible)
    # Compared with the cue's `speaker` at the card's end: `DATA?` when the
    # engine names someone else although the data speaker has a face in the
    # room (a mislabelled cue - the morgue's ten, #23's basement reports),
    # `FACE!` when our layout shows the wrong face (a payload bug),
    # `unverifiable` when the speaker has no face here (the script then
    # animates a listener - Metal in most rooms) or the engine named nobody.
    cues_cache = {}
    def cues_of(bank):
        if bank not in cues_cache:
            try:
                cues_cache[bank] = [c for c in json.load(open(os.path.join(ROOT, 'ps1', 'translation', f'subs_{bank}.json'), encoding='utf-8'))['cues']
                                     if c.get('enabled', True)]
            except OSError:
                cues_cache[bank] = []
        return cues_cache[bank]
    import subs_cue as SC
    char_name = {v: k for k, v in SC.SPEAKER_CHAR.items()}
    def cxn_char(file_idx):
        i = file_idx - SC.CXN_FIRST
        if 0 <= i < len(SC.CXN_CHARS):
            ch = int(SC.CXN_CHARS[i], 18)
            return char_name.get(ch, f'char{SC.CXN_CHARS[i]}')
        return None
    spk_tally = {}
    spk_verdicts = []
    spk_paused = None
    import collections
    def spk_sample(bank, idx):
        t = spk_tally.get((bank, idx))
        if t is None:
            t = spk_tally[(bank, idx)] = {'frames': 0, 'band': 0, 'eng': collections.Counter(),
                                          'face': collections.Counter(), 'room': set()}
        t['frames'] += 1
        mw = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF4) & 0x1FFFFF)), 4))[0]
        band, col = (mw >> 26) & 1, (mw >> 20) & 7
        lst = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1814) & 0x1FFFFF)), 4))[0]
        chars = []
        for c in range(3):
            sid = struct.unpack_from('<b', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF8 + c) & 0x1FFFFF)), 1))[0]
            fi = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((lst + 4 * sid) & 0x1FFFFF)), 4))[0] if sid >= 0 and 0x80000000 <= lst < 0x80200000 else -1
            chars.append(cxn_char(fi))
        # a column counts only while its cels are on the screen: a closed
        # band parks them at y=276 or 396 with the band bit still set (the
        # basement's full-screen scream; Chin's own column stays parked
        # through his reel while his picture fills the screen and only
        # Gillian's face is up), and neither the engine's naming nor our
        # x=24 means anything there - nor is such a speaker 'in the room'
        cels = []
        for c in range(3):
            cel = ctx + 0x4934 + 0x5C * (3 * c)
            x, y = struct.unpack_from('<HHH', C.string_at(C.c_void_p(ram + ((cel + 0x4E) & 0x1FFFFF)), 6))[0::2]
            # visible = any of the column's three cels shown (bits 9 and 8
            # of +0x58): Metal Gear's base cel is hidden by design, his
            # eyes cel is the animated head (#37) - same rule as face_find
            fl = 0
            for k in range(3):
                fk = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((cel + 0x5C * k + 0x58) & 0x1FFFFF)), 4))[0]
                if (fk & 0x300) == 0x300: fl = 0x300
            cels.append((x, y, fl))
        t['room'] |= {c for c, cel in zip(chars, cels) if c and cel[1] < 240}
        if band:
            # ... and on the screen sideways too: the payload parks the
            # columns it does not use at x=400, and with every column
            # there (Madnar's full-screen close-ups in B260, a plain card
            # with his nameplate) no band is showing at all
            if any(cel[1] < 240 and cel[0] < 320 for cel in cels):
                # the band bit stays set while the band is CLOSED (its cels
                # parked at y=396): only an open band, cels on screen,
                # counts towards FACE! - Madnar's full-screen close-ups in
                # B260 and Gillian's 'Harry was our son' (B240) drew plain
                # cards with the nameplate, rightly, and were flagged
                t['band'] += 1
            if col < 3 and chars[col] and cels[col][1] < 240:
                t['eng'][chars[col]] += 1
        for c in range(3):
            x, y, fl = cels[c]
            if x == SC.FACE_X and y < 240 and fl & 0x200 and chars[c]:
                t['face'][chars[c]] += 1
    def spk_close(bank, idx, f):
        t = spk_tally.pop((bank, idx), None)
        cues = cues_of(bank)
        if t is None or not (0 <= idx < len(cues)):
            return
        c = cues[idx]
        data = c.get('speaker') or '-'
        eng = t['eng'].most_common()
        face = t['face'].most_common()
        n_eng = sum(t['eng'].values())
        if not eng or n_eng < max(30, t['frames'] // 5):
            verdict = 'unverifiable'            # the engine named nobody, or only for a few frames
                                                # (a band closing under the card: c7f56's 3 frames)
        elif data not in t['room']:
            verdict = 'unverifiable'            # no face for the speaker here: a listener animates
        elif eng[0][0] != data and eng[0][1] >= 0.6 * n_eng:
            # "by_ear": Luiz heard the line and named the speaker against
            # the engine's animation (c7f46: the script animates Gillian's
            # mouth, the voice is Randam's) - a human verdict outranks the
            # engine's, so the card counts as checked, not flagged
            # `by_text`: the speaker was settled from the Japanese wording
            # (Metal Gear's polite register) against an engine that
            # animates the listener - counted like `by_ear`
            verdict = 'ear' if (c.get('by_ear') or c.get('by_text')) else 'DATA?'
        else:
            verdict = 'ok'
        if data in t['room'] and t['band'] >= t['frames'] // 2 and (not face or face[0][0] != data):
            verdict = 'FACE!' if verdict != 'DATA?' else 'DATA?/FACE!'
        spk_verdicts.append((verdict, c['id'], data, eng, face))
        L(f'{f}: speaker {c["id"]} data={data} engine={",".join(f"{k}:{v}" for k, v in eng) or "-"} '
          f'face={",".join(f"{k}:{v}" for k, v in face) or "-"} room={sorted(t["room"])} verdict={verdict}')
    # AUTOSAVE (default on): a bookmark of every bank the run passes through,
    # taken at the first live verb menu after the bank loads, against the
    # image of this run - work/states/<bank>_auto. Mid-scene bank switches
    # count too (Restore in the basement loads B210). The previous one is
    # kept as <bank>_auto.prev.
    autosave = os.environ.get('AUTOSAVE', '1') != '0'
    auto_pending = None
    auto_done = set()

    emu = emurun.Emu()
    emu.load(a.image)
    emu.load_card(a.card)
    if os.environ.get('FF_START') and not FF_RANGE:
        emu.always = {emurun.BTN['start']}   # dev-test fast-forward: START held throughout
    # FF_START=smart: START held except while the keyboard or the videophone
    # pad is up (START submits the one and places the call on the other) and
    # during the game's own Save
    ff_smart = os.environ.get('FF_START') == 'smart'
    rec = None
    if os.environ.get('PLAYLOG'):
        try:
            import playlog          # the MiSTer whole-game recorder (maintainer's tree only)
        except ImportError:
            sys.exit('PLAYLOG needs ps1/harness/playlog.py, which is not part of this tree')
        rec = playlog.Recorder(emu, os.environ['PLAYLOG'], dict(
            image=a.image, route=route, start=a.start, state_file=a.state_file,
            state=a.state, new=a.new, scene=a.scene, ff=os.environ.get('FF_START', '')))
    sigs = signatures()
    state_ok = 'circle'
    if a.from_state:
        for _ in range(60):
            emu.run()
        blob = None
        if a.state_file:
            blob = gzip.decompress(open(a.state_file, 'rb').read())
            meta = a.state_file[:-9] + '.json'
            meta = json.load(open(meta)) if os.path.exists(meta) else {}
            state_ok = meta.get('ok', 'circle') if isinstance(meta, dict) else 'circle'
        elif a.state:
            sp = os.path.join(WORK, 'states', f'{a.state}.state.gz')
            blob = gzip.decompress(open(sp, 'rb').read())
            # A savestate carries the CD state, so it is tied to the image it
            # was taken against: after a patch_disc rebuild that moves
            # sectors, the NEXT scene load reads the wrong bank and the game
            # hangs on black (a B020 bookmark from the morning did exactly
            # that after the evening rebuild - the ruins played fine, HQ
            # never loaded). Inside the bookmark's own scene it is safe.
            stamp = os.path.join(WORK, 'states', f'{a.state}.json')
            meta = json.load(open(stamp)) if os.path.exists(stamp) else None
            if isinstance(meta, dict):        # newer stamps carry the button config too
                state_ok = meta.get('ok', 'circle')
                meta = meta.get('image')
            else:
                state_ok = 'circle'
            if meta != image_stamp(a.image):
                print(f'WARNING: bookmark {a.state} was not taken against the current image; '
                      f'fine within {a.scene}, but the next scene load may hang', flush=True)
        # A bookmark may belong to the scene BEFORE the one under test (the
        # B1E0 stairway leading down into B200): inject the bank the state
        # actually holds, or the target bank lands over the wrong bytecode.
        if a.state_file:
            emu.restore(blob)
            if os.path.exists(a.state_file[:-9] + '.card'):
                emu.load_card(a.state_file[:-9] + '.card')
        else:
            held = a.state[:4] if a.state and re.match(r'B[0-9A-F]{3}', a.state) else a.scene
            restore_scene(emu, held, blob)
    core = emu.core
    core.retro_get_memory_data.restype = C.c_void_p
    ram = None
    boot_done = 0 if a.from_state else None

    queue, press_until, last_press = [], 0, 0
    live_since = None
    last_win, win_since = None, 0
    last_win_full = None
    ai, depth, action_since = a.start, 0, 0
    steps, sub_misses = 0, 0
    confirmed = None
    top_labels = []
    reps_done = 0
    last_shown, last_bank, pending = None, None, []
    drawn_of = {}                # bank -> cue indices drawn (the run's scene and any it crosses into)
    misses, shots = [], 0
    done_at = None
    last_scene = None
    in_fight, select_at, fight_no, fight_t0 = False, -9999, 0, 0
    fight_phase, corner_cell = 0, None
    cue_at = -9999
    pad_seen, dial_i = -9999, 0
    last_fctr = None
    # The game's key config can swap confirm and cancel (Luiz's late-Act-1
    # card has it that way: circle backed out of every menu and cross opened
    # them). Detected by a confirm that just reopens the same top menu twice.
    menu_words = {}      # window word while the TOP verb menu is live, per scene
    geom_seen = set()    # label tuples checked against the list grid (menuread.geometry)
    geom_bad = []        # (frame, scene, idx, label, cells, limit): a label that overflows its column
    OK, BACK = 'circle', 'cross'
    if a.from_state and (a.state or a.state_file) and state_ok != 'circle':
        OK, BACK = state_ok, 'circle'
        L(f'buttons from bookmark: confirm={OK} cancel={BACK}')
    if os.environ.get('PILOT_OK') in ('circle', 'cross'):
        # PILOT_OK=cross: the key config of the card behind a bookmark with
        # no sidecar (Luiz's Act 2+ cards swap confirm and cancel; the
        # pilot's cancel-to-refresh then confirms its way out of the room)
        OK = os.environ['PILOT_OK']
        BACK = 'cross' if OK == 'circle' else 'circle'
        L(f'buttons from PILOT_OK: confirm={OK} cancel={BACK}')
    bounces, pre_labels, confirmed_at = 0, None, 0
    # The sync gate (always on). Every frame the voice stream is moving
    # (the payload's PARKED count under PARK_FRAMES), the polled position
    # and the captured Setfilter {file, chan} name the cues the payload's
    # matcher would take - the same rule it runs. A cue heard that way for
    # SYNC_MIN frames that never showed is UNSHOWN (a dropped subtitle: the
    # player heard the line with no card), one that showed more than
    # SYNC_LATE frames after its line began is LATE (out of sync with the
    # voice). FROZEN: our card held in WAIT with no stream moving and no
    # menu for FROZEN_FRAMES (the Saturn v1.0 softlock's signature); HANG:
    # the game's frame counter (ctx+0x18) stopped.
    sync_idx = {}            # bank -> {(file, chan): [cue index]}
    sync_heard = {}          # (bank, idx) -> [[first, last, frames]] episodes
    sync_shown = collections.defaultdict(list)   # (bank, idx) -> frames it was shown
    frozen_since, frozen_logged = None, False
    frozen_hits = []
    hang_ctr, hang_since = None, 0
    def sync_cues(bank):
        if bank not in sync_idx:
            d = {}
            for i, c in enumerate(cues_of(bank)):
                if c.get('chan', 0) != 254 and 'start' in c:
                    d.setdefault((c['file'], c['chan']), []).append(i)
            sync_idx[bank] = d
        return sync_idx[bank]

    def boxstate():
        """The dialogue box's frame and fill sprites (ctx+0x27B0/0x27F0):
        visible bit and the y of vertex 0 of their prims. The frame is not
        positioned per layout - it parks at y=272, off the bottom of the
        screen, and the type-0 open/close steps slide it 120 px up and back
        - so a drift here is a slide that ran without its partner."""
        out = []
        for obj in (ctx + 0x27B0, ctx + 0x27F0):
            flags = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((obj + 0x3C) & 0x1FFFFF)), 4))[0]
            prim = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((obj + 0x1C) & 0x1FFFFF)), 4))[0]
            y = struct.unpack_from('<h', C.string_at(C.c_void_p(ram + ((prim + 0x5A) & 0x1FFFFF)), 2))[0] if 0x80000000 <= prim < 0x80200000 else -1
            out.append(f"{'v' if flags & 0x01000000 else 'h'}{y}")
        fn = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1ED0) & 0x1FFFFF)), 4))[0]
        # the nine portrait-slot tasks at ctx+0x4934 (0x5C each): x, y and
        # the visible bit (+0x58 bit 28); the band's faces live here
        slots = []
        for i in range(9):
            t = ctx + 0x4934 + 0x5C * i
            x, y = struct.unpack_from('<H', C.string_at(C.c_void_p(ram + ((t + 0x4E) & 0x1FFFFF)), 2))[0], struct.unpack_from('<H', C.string_at(C.c_void_p(ram + ((t + 0x52) & 0x1FFFFF)), 2))[0]
            fl = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((t + 0x58) & 0x1FFFFF)), 4))[0]
            fn_i = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((t + 0x10) & 0x1FFFFF)), 4))[0]
            if fn_i or fl & 0x10000100:      # a step, or prims built (bit 8)
                pv = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((t + 0x14) & 0x1FFFFF)), 4))[0]
                pb = C.string_at(C.c_void_p(ram + (pv & 0x1FFFFF)), 4).hex() if 0x80000000 <= pv < 0x80200000 else '-'
                slots.append(f'{i}:{x},{y},{fl:08x},{fn_i:08x},p{pb}')
        out[0] += ' faces=' + (','.join(slots) if slots else '-')
        # the menu word: bit 26 = band open, bits 20-22 = the speaking column
        mw = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF4) & 0x1FFFFF)), 4))[0]
        out[0] += f' band={(mw >> 26) & 1} spk={(mw >> 20) & 7}'
        if os.environ.get('BOXDUMP'):
            for obj in (ctx + 0x27B0, ctx + 0x27F0):
                prim = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((obj + 0x1C) & 0x1FFFFF)), 4))[0]
                out.append(C.string_at(C.c_void_p(ram + (obj & 0x1FFFFF)), 0x40).hex())
                out.append(C.string_at(C.c_void_p(ram + (prim & 0x1FFFFF)), 0x80).hex() if 0x80000000 <= prim < 0x80200000 else '-')
        extra = (' objs %s %s prims %s %s' % (out[2], out[4], out[3], out[5])) if len(out) > 2 else ''
        if os.environ.get('ROWDUMP'):
            # the six row sprites at ctx+0x2570 (0x40 each): visible bit and
            # the prim's vertex/uv block (+0x58..+0x78)
            rows = []
            for i in range(6):
                obj = ctx + 0x22B0 + 0x2C0 + 0x40 * i
                flags = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((obj + 0x3C) & 0x1FFFFF)), 4))[0]
                prim = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((obj + 0x1C) & 0x1FFFFF)), 4))[0]
                vb = C.string_at(C.c_void_p(ram + ((prim + 0x68) & 0x1FFFFF)), 0x14).hex() if 0x80000000 <= prim < 0x80200000 else '-'
                rows.append(f"{'v' if flags & 0x01000000 else 'h'}:{vb}")
            extra += ' rows ' + ' '.join(rows)
        ph, fk = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC078), 4))[0], struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC08C), 4))[0]
        dbg = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC094), 4))[0]
        widths = C.string_at(C.c_void_p(ram + ((ctx + 0x1AD0) & 0x1FFFFF)), 6).hex()
        return f'frame={out[0]} fill={out[1]} fn={fn:08x} phase={ph} fake={fk} dbg={dbg:08x} w={widths}' + extra

    def press(seq, f):
        t = f + 2
        for btn in seq:
            queue.append((t, btn)); t += 18

    # --- the game's own Save, and the memory card out (--mcard / MCSAVE=1 /
    # a route's {"mcard": name}) - the card library is ps1/harness/mcard.py,
    # and `mcard.py push` puts one on the MiSTer. The flow, probed on
    # 2026-09-14 (work/probe_save2.py): Use Metal Gear > Save (some rooms put
    # Save in the verb menu itself) > 'Saving your progress so far.' > 'Do not
    # remove the memory card while saving.' > the four-slot list (menu cursor
    # 0xF9, count 4, labels 'Save 1'..'Save 4') > 'This file holds data from a
    # previous session. Overwrite it?' > Save / Don't save > 'Do not remove...'
    # > the card is WRITTEN > 'Save complete. Resuming the case.' > the verb
    # menu. ~2,000 frames. The verdict is the card's bytes changing, not the
    # menus. Runs the emulator synchronously (the main loop's frame count
    # stands still meanwhile; no cue plays during a save).
    MCSAVE_SLOT = int(os.environ.get('MCSAVE_SLOT', '1'))
    MCSAVE_TRIES = int(os.environ.get('MCSAVE_TRIES', '3'))
    mcsave = a.mcard or os.environ.get('MCSAVE', '') not in ('', '0')
    mc_tries, mc_done, mc_written = {}, set(), []

    def card_bytes():
        core.retro_get_memory_size.restype = C.c_size_t
        return C.string_at(C.c_void_p(core.retro_get_memory_data(0)), core.retro_get_memory_size(0))

    def game_save(f, slot=None, scene=None):
        """Save the game from a live verb menu and come back to it. True when
        the card changed."""
        nonlocal last_press
        slot = slot or MCSAVE_SLOT
        scene = scene or last_scene or a.scene
        before = card_bytes()
        keep_always, emu.always = emu.always, set()
        n = 0

        def step(k):
            nonlocal n
            for _ in range(k):
                emu.run(); n += 1

        def tap(btn, after=STEP_GAP):
            emu.held = {emurun.BTN[btn]}; step(PRESS); emu.held = set(); step(after)

        def menu():
            live, idx, count = menustate.read(ram)
            labels = [clean(x, scene) for x in read_menu(ram)] if live else []
            return live, idx, count, labels

        def is_verbs(labels):
            return sum(x.lower() in VERBS for x in labels) >= 3 or (bool(labels) and labels == top_labels)

        def choose(i):
            # steer the cursor to item i, confirm, and wait for the list to go
            # (a confirm that lands while the list is still opening is eaten:
            # pressed again every 30 frames)
            for _ in range(2 * MAX_STEPS):
                live, idx, count, labels = menu()
                if not live:
                    return False
                if idx == i:
                    break
                tap('down' if idx < i else 'up')
            was = (count, labels)
            for _ in range(8):
                tap(OK, 0)
                for _ in range(30):               # per frame: the next list can be
                    step(1)                       # live again within the gap
                    live, idx, count, labels = menu()
                    if not live or (count, labels) != was:
                        return True
            return False

        phase, idle, labels, live_at = 'top', 0, [], None
        while n < 7000:
            live, idx, count, labels = menu()
            if not live:
                live_at = None
                step(30); idle += 30              # a box: press through it, spaced like ADVANCE
                if idle >= ADVANCE:
                    tap(OK, 0); idle = 0
                continue
            idle = 0
            if live_at is None:
                live_at = n
            if n - live_at < 2 * MENU_SETTLE:    # the label table lags the cursor
                step(1)
                continue
            low = [x.lower() for x in labels]
            if phase == 'top':
                if 'use metal gear' in low:
                    choose(low.index('use metal gear')); phase = 'sub'
                elif 'save' in low:
                    choose(low.index('save')); phase = 'slots'
                else:
                    L(f'{f}: mcard: no Save in {labels}')
                    return False
            elif phase == 'sub':
                if 'save' in low:
                    choose(low.index('save')); phase = 'slots'
                else:
                    L(f'{f}: mcard: no Save under Use Metal Gear here ({labels})')
                    tap(BACK); step(60)
                    return False
            elif phase == 'slots':
                if count == 4 and low and all(x.startswith('save') for x in low):
                    L(f'{f}: mcard: slot {slot} of {labels}')
                    choose(slot - 1); phase = 'confirm'
                elif is_verbs(labels):
                    L(f'{f}: mcard: back at the verb menu without a slot list ({labels})')
                    break
                else:
                    L(f'{f}: mcard: unexpected list {labels}, backing out')
                    tap(BACK); step(60)
            elif phase == 'confirm':
                if count == 2 and low and low[0] == 'save':
                    choose(0); phase = 'done'
                elif is_verbs(labels):
                    break
                else:
                    L(f'{f}: mcard: unexpected list {labels}, backing out')
                    tap(BACK); step(60)
            else:
                if is_verbs(labels):
                    break
                tap(BACK); step(60)
            step(30)
        ok = card_bytes() != before
        emu.always = keep_always
        last_press = f
        L(f'{f}: mcard: save {"written" if ok else "NOT written"} after {n} frames, menu {labels}')
        return ok

    def dump_card(f, name, saved, slot=None, scene=None):
        import mcard
        slot = slot or MCSAVE_SLOT
        scene = scene or last_scene or a.scene
        where = f'{scene} {os.path.basename(route)} f{f}'
        entry = mcard.add_card(name, card_bytes(), desc=f'harness: {where}',
                               labels={str(slot): where} if saved else None, source=out,
                               extra={'bank': scene, 'route': os.path.basename(route), 'frame': f,
                                      'slot': slot, 'saved': saved, 'ok': OK})
        mc_written.append((name, scene, saved))
        L(f'{f}: mcard {entry["path"]} ({len(entry["saves"])} save(s) in use, slot {slot}, saved={saved})')
        return entry

    def skip(f, why, want, labels):
        nonlocal ai, depth, reps_done, steps, action_since, confirmed, sub_misses
        misses.append((ai, want, list(labels)))
        L(f'{f}: {why} action {ai} {actions[ai]["path"]} - {want!r} in {labels}'
          + ('  (optional)' if actions[ai].get('optional') else ''))
        ai, depth, reps_done, steps, sub_misses = ai + 1, 0, 0, 0, 0
        action_since, confirmed = f, None

    for f in range(a.frames):
        act = events.get(f)
        if act:
            emu.held = ({emurun.BTN[b] for b in act[6:].split('+')}
                        if act.startswith('press:') else set())
        if queue and f >= queue[0][0]:
            _, btn = queue.pop(0)
            emu.held = {emurun.BTN[btn]}
            press_until, last_press = f + PRESS, f
            if a.trace and ram is not None:
                L(f'{f}: press {btn}  ms={C.string_at(C.c_void_p(ram + 0x11D7C), 4).hex()} '
                  f'win={last_win:04x}' if last_win is not None else f'{f}: press {btn}')
        elif f == press_until:
            emu.held = set()

        if ff_smart and ram is not None:
            _m = C.string_at(C.c_void_p(ram + 0x11D7C), 2)
            _hold = not (_m[0] in (0xF8, 0xF9) and _m[1] == 0x01) and not (
                _m[0] in (0xF9, 0x01, 0x05) and menustate.dialling(ram))
            emu.always = {emurun.BTN['start']} if _hold else set()
        emu.run()
        if ram is None:
            ram = core.retro_get_memory_data(2)
        if RAMTOUCH and ram is not None:
            _n = int(RAMTOUCH.split(',')[0])
            if f % _n == 0:
                _cur = np.frombuffer(C.string_at(C.c_void_p(ram), 0x200000), dtype=np.uint8).copy()
                if getattr(main, '_rt_prev', None) is None:
                    main._rt_mask = np.zeros(0x200000, dtype=np.uint8)
                else:
                    main._rt_mask |= (_cur != main._rt_prev)
                main._rt_prev = _cur
        if os.environ.get('FACEWATCH') and ram is not None:
            # rows in the face layout (row 0 template x = 92) with no visible cel at x=24
            _pr = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1258C), 4))[0]
            _rx = struct.unpack_from('<h', C.string_at(C.c_void_p(ram + ((_pr + 0x30) & 0x1FFFFF)), 2))[0] if 0x80000000 <= _pr < 0x80200000 else -1
            _vis = False
            for _i in range(9):
                _t = 0x14934 + 0x5C * _i
                _x = struct.unpack_from('<H', C.string_at(C.c_void_p(ram + _t + 0x4E), 2))[0]
                _fl = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + _t + 0x58), 4))[0]
                if _x == 24 and (_fl & 0x300) == 0x300: _vis = True
            _lay = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 200), 4))[0]
            _ph2 = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 120), 4))[0]
            _sh2 = struct.unpack_from('<i', C.string_at(C.c_void_p(ram + 0x1F0004), 4))[0]
            _key = (_lay, _sh2)
            if _ph2 and getattr(main, '_laykey', None) is not None and main._laykey[1] == _sh2 and main._laykey[0] != _lay:
                L(f'{f}: LAYOUT {main._laykey[0]} -> {_lay} under card {_sh2}')
            main._laykey = _key if _ph2 else None
            _bad = (_rx == 92 and not _vis)
            if _bad != getattr(main, '_facebad', False):
                main._facebad = _bad
                L(f'{f}: FACEWATCH {"text without face" if _bad else "ok"} rowx={_rx}')
        if DBGFRAMES and DBGFRAMES[0] <= f <= DBGFRAMES[1] and ram is not None:
            _fn = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x11ED0), 4))[0]
            _ph = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 120), 4))[0]
            _w = C.string_at(C.c_void_p(ram + 0x11AD0), 3).hex()
            _sh = struct.unpack_from('<i', C.string_at(C.c_void_p(ram + 0x1F0004), 4))[0]
            _loc = C.string_at(C.c_void_p(ram + 0x1058C), 8)
            _bcd = lambda b: (b >> 4) * 10 + (b & 15)
            _lba = (_bcd(_loc[0]) * 60 + _bcd(_loc[1])) * 75 + _bcd(_loc[2]) - 150
            _flt = struct.unpack_from('<II', C.string_at(C.c_void_p(ram + 0x1FC000 + 48), 8))
            _cand = struct.unpack_from('<II', C.string_at(C.c_void_p(ram + 0x1FC000 + 8), 8))
            _objs = []; _n = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x11954), 4))[0]
            while 0x80000000 <= _n < 0x80200000 and len(_objs) < 8:
                _objs.append(struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((_n + 4) & 0x1FFFFF)), 4))[0])
                _n = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + (_n & 0x1FFFFF)), 4))[0]
            _tr = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 224), 4))[0]
            _pk = struct.unpack_from('<II', C.string_at(C.c_void_p(ram + 0x1FC000 + 128), 8))[0]; _ll = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 36), 4))[0]
            _mg = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + (HIRAM & 0x1FFFFF)), 4))[0]
            _si = struct.unpack_from('<i', C.string_at(C.c_void_p(ram + 0x11DB8), 4))[0]; _q = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1057C), 4))[0]
            L(f'{f}: DBG sceneidx={_si} cdq={_q:08x} magic={_mg:08x} trace={_tr} parked={_pk} lastlba={_ll} objs={_objs} step={_fn:08x} phase={_ph} w={_w} shown={_sh} lba={_lba} file/chan={_loc[4]}/{_loc[5]} filter={_flt} cand/count={_cand} fillflags={struct.unpack_from("<I", C.string_at(C.c_void_p(ram + 0x127F0 + 0x3C), 4))[0]:08x} frameflags={struct.unpack_from("<I", C.string_at(C.c_void_p(ram + 0x127B0 + 0x3C), 4))[0]:08x} win={struct.unpack_from("<I", C.string_at(C.c_void_p(ram + 0x11ACC), 4))[0]:08x}')
        if CLOBBER_AT and f in CLOBBER_AT and ram is not None:
            # probe: the band open's label render (BUG-013) as it lands on
            # DuckStation - every row width a letter, mid type-on
            C.memmove(C.c_void_p(ram + 0x11AD0), bytes([1, 1, 1]), 3)
            L(f'{f}: CLOBBER widths -> 1,1,1')
        if FACEPOKE and ram is not None:
            # faces POC probe: FACEPOKE=x,y[,slotmask] rewrites every live
            # portrait slot's +0x4E/+0x52 each frame (cel renderer 0x80035DBC
            # reads them per frame, so a write should move the face)
            ctx0 = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + (0x800ABF64 & 0x1FFFFF)), 4))[0]
            if ctx0 == 0x80010000:
                for i in range(9):
                    if not (FACEPOKE[2] >> i) & 1:
                        continue
                    t = ctx0 + 0x4934 + 0x5C * i
                    if True:                # every slot: a column is 3 cels (base, eyes, mouth)
                        C.memmove(C.c_void_p(ram + ((t + 0x4E) & 0x1FFFFF)), struct.pack('<H', FACEPOKE[0]), 2)
                        C.memmove(C.c_void_p(ram + ((t + 0x52) & 0x1FFFFF)), struct.pack('<H', FACEPOKE[1]), 2)

        if f % 30 == 0 and f > first_load:
            head = C.string_at(C.c_void_p(ram + (BANK_RAM & 0x1FFFFF)), 256)
            here = sigs.get(hashlib.sha1(head).hexdigest())
            if here and here != last_scene:
                L(f'{f}: scene {here}')
                last_scene = here
                if rec:
                    rec.scene = here
                    rec.note('scene', bank=here)
                if autosave and here not in auto_done:
                    auto_pending = (here, f)
            if boot_done is None:
                if here:
                    boot_done = f + 240
                    L(f'{f}: in game')
                elif not queue and (f - last_press) > 250:
                    queue.append((f + 2, 'circle'))
        if boot_done is None or f < boot_done:
            continue

        ctx = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + (0x800ABF64 & 0x1FFFFF)), 4))[0]
        if ctx != 0x80010000:
            continue
        win = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1ACC) & 0x1FFFFF)), 4))[0]
        low = win & 0xFFFF
        if os.environ.get('SLIDELOG'):
            # ring logger on the slider 0x80033848: every call's ra/obj/dy/mask,
            # 64 entries of 16 B at 0x801FD010 behind a count word at 0x801FD000;
            # the stub (slidelog_stub(), k0/k1 only) sits at 0x801FD800
            # and the slider's first two words become `j stub; nop`.
            if not hasattr(main, '_slidelog'):
                main._slidelog = True
                stub = slidelog_stub()
                C.memmove(C.c_void_p(ram + 0x1FD800), stub, len(stub))
                C.memmove(C.c_void_p(ram + 0x1FD000), bytes(1024), 1024)
                C.memmove(C.c_void_p(ram + 0x33848), struct.pack('<II', 0x08000000 | (0x801FD800 >> 2) & 0x3FFFFFF, 0), 8)
                main._slide_seen = 0
            idxw = struct.unpack('<I', C.string_at(C.c_void_p(ram + 0x1FD000), 4))[0] & 63
            while main._slide_seen != idxw:
                e = struct.unpack('<IIII', C.string_at(C.c_void_p(ram + 0x1FD010 + 16 * main._slide_seen), 16))
                main._slide_seen = (main._slide_seen + 1) & 63
                L(f'{f}: SLIDE ra={e[0]:08x} obj={e[1]:08x} dy={e[2] & 0xffff:04x} mask={e[3]:x}')
        if os.environ.get('NAMETRACE'):
            # every dialogue line the engine's type-0 handler renders a
            # nameplate for: the speaker (index into the 32-byte SJIS name
            # table at 0x800AC1D4) and the mode word (nameplate colour =
            # 0x800711BC[mode]; the game's own speaker -> colour map)
            if not hasattr(main, '_nametrace'):
                main._nametrace = True
                stub = nametrace_stub()
                C.memmove(C.c_void_p(ram + 0x1FDC00), stub, len(stub))
                C.memmove(C.c_void_p(ram + 0x1FD400), bytes(0x210), 0x210)
                C.memmove(C.c_void_p(ram + 0x475EC), struct.pack('<I', 0x0C000000 | (0x801FDC00 >> 2) & 0x3FFFFFF), 4)
                main._name_seen = 0
                main._ctab = C.string_at(C.c_void_p(ram + 0x711BC), 64)
            idxw = struct.unpack('<I', C.string_at(C.c_void_p(ram + 0x1FD400), 4))[0] & 63
            while main._name_seen != idxw:
                e = struct.unpack('<II', C.string_at(C.c_void_p(ram + 0x1FD410 + 8 * main._name_seen), 8))
                main._name_seen = (main._name_seen + 1) & 63
                _ni = (e[0] - 0x800AC1D4) // 32 if 0x800AC1D4 <= e[0] < 0x800AC1D4 + 32 * 64 else -1
                _mode = e[1] & 0x3F
                L(f'{f}: NAME idx={_ni} ptr={e[0]:08x} mode={_mode} colour={main._ctab[_mode]}')
        if emu.audio_probe:
            if not hasattr(main, '_alog'):
                main._alog = open(os.path.join(out, 'audio.txt'), 'w')
            main._alog.write('%d %d\n' % (f, emu.audio_level))
        if os.environ.get('SCENEIDX') and ram is not None:
            _si2 = struct.unpack_from('<i', C.string_at(C.c_void_p(ram + 0x11DB8), 4))[0]
            if _si2 != getattr(main, '_si', None):
                main._si = _si2; L(f'{f}: SCENEIDX {_si2}')
        if os.environ.get('SPKTRACE'):
            mw = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF4) & 0x1FFFFF)), 4))[0]
            bstep = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x2048 + 0x10) & 0x1FFFFF)), 4))[0]
            sv = ((mw >> 20) & 7, (mw >> 26) & 1, bstep)
            if sv != getattr(main, '_spk', None):
                main._spk = sv
                cols = [struct.unpack_from('<b', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF8 + c) & 0x1FFFFF)), 1))[0] for c in range(3)]
                # the room's face list: slot id -> class-4 file index (CXN_* = 396..447)
                lst = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1814) & 0x1FFFFF)), 4))[0]
                files = [struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((lst + 4 * i) & 0x1FFFFF)), 4))[0] if i >= 0 and 0x80000000 <= lst < 0x80200000 else -1 for i in cols]
                L(f'{f}: SPK col={sv[0]} band={sv[1]} step={sv[2]:08x} faces={cols} files={files}')
        if low != last_win:
            last_win, win_since = low, f
        if a.trace and win != last_win_full:
            wf = struct.unpack_from('<IIIIIII', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF4) & 0x1FFFFF)), 28))
            L(f'{f}: win {win:08x}  1AF4={wf[0]:08x} 1AFC={wf[2]:08x} 1B04={wf[4]:08x} 1B0C={wf[6]:08x}')
        last_win_full = win
        live, idx, count = menustate.read(ram)
        if WATCHDOG and not in_fight and live_since is None and f - getattr(main, '_last_live', f) > WATCHDOG:
            L(f'{f}: WATCHDOG: no menu for {WATCHDOG} frames - stopping (a softlock?)')
            emu.image().save(os.path.join(out, f'watchdog_{f:06d}.png'))
            break
        if live:
            main._last_live = f
            if live_since is None:
                live_since = f
            if auto_pending and f - auto_pending[1] >= 30 and f - live_since >= MENU_SETTLE:
                bank = auto_pending[0]
                path = os.path.join(STATES_DIR, f'{bank}_auto.state.gz')
                if os.path.exists(path):
                    os.replace(path, path[:-9] + '.prev.state.gz')
                open(path, 'wb').write(gzip.compress(emu.state()))
                json.dump({'image': image_stamp(a.image), 'ok': OK, 'run': out, 'frame': f},
                          open(path[:-9] + '.json', 'w'))
                L(f'{f}: auto-bookmark {bank}_auto at {read_menu(ram)}')
                auto_done.add(bank); auto_pending = None
                if a.trace:
                    L(f'{f}: menu live idx={idx} n={count} {read_menu(ram)}')
        else:
            if live_since is not None and a.trace:
                L(f'{f}: menu gone')
            live_since = None

        # every XA stream the driver selects leaves its CdlSetfilter {file,
        # chan} in the payload scratch - the honest list of what a scene
        # plays, and the way a mis-carded conversation is found
        fchg = struct.unpack('<III', C.string_at(C.c_void_p(ram + 0x1FC030), 12))
        if fchg[:2] != last_fctr:              # the stub writes {file, chan}; the counter word is never bumped
            m, sec, fr = C.string_at(C.c_void_p(ram + 0x1058C), 3)
            bcd = lambda b: (b >> 4) * 10 + (b & 15)
            lba = (bcd(m) * 60 + bcd(sec)) * 75 + bcd(fr) - 150
            L(f'{f}: stream file={fchg[0]} chan={fchg[1]} lba={lba}')
            last_fctr = fchg[:2]
        bp = HIRAM                              # the payload blob, once loaded
        if struct.unpack_from(
                '<I', C.string_at(C.c_void_p(ram + (bp & 0x1FFFFF)), 4))[0] == MAGIC:
            shown = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((bp + 4) & 0x1FFFFF)), 4))[0]
            # the bank whose blob this is: the run's scene until the bank in
            # RAM changes (a run crosses into the next scene, or Restore
            # loads B210 in the basement); every bank's cards are scored
            # against ITS cue file - until 2026-09-12 another bank's cards
            # were logged 'not scored' and the reconstruction's 202 went
            # unchecked in every run that reached it
            bank = last_scene or a.scene
            if shown != last_shown and last_shown not in (None, 0xFFFFFFFF) and (last_bank, last_shown) in spk_tally:
                if shown == 0xFFFFFFFF:
                    # the minimum hold may draw this card again, plain, in a
                    # few frames (subs_cue HOLDREQ): judge both as one card
                    spk_paused = (last_bank, last_shown)
                else:
                    spk_close(last_bank, last_shown, f)
            if shown != 0xFFFFFFFF and spk_paused is not None:
                if spk_paused != (bank, shown) and spk_paused in spk_tally:
                    spk_close(*spk_paused, f)
                spk_paused = None
            if shown != 0xFFFFFFFF:
                spk_sample(bank, shown)
            if shown != last_shown:
                if shown == 0xFFFFFFFF and last_shown not in (None, 0xFFFFFFFF):
                    L(f'{f}: cue cleared  win={win:08x}')
                if shown not in (None, 0xFFFFFFFF):
                    drawn_of.setdefault(bank, []).append(shown)
                    of = f' of {bank}' if bank != a.scene else ''
                    L(f'{f}: cue {shown}{of} ({cue_id(bank, shown)})  win={win:08x}  {boxstate()}')
                    if a.trace:
                        wf = struct.unpack_from('<IIIIIII', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF4) & 0x1FFFFF)), 28))
                        L(f'{f}:   window 1AF4={wf[0]:08x} 1AF8={wf[1]:08x} 1AFC={wf[2]:08x} 1B00={wf[3]:08x} 1B04={wf[4]:08x} 1B08={wf[5]:08x} 1B0C={wf[6]:08x}')
                    cue_at = f
                    # captures of another bank's cards carry an `x<bank>_`
                    # prefix: subs_validate scores `cue*` against the run's
                    # scene and each prefix against that bank
                    pre = f'x{bank}_' if bank != a.scene else ''
                    emu.image().save(os.path.join(out, f'{pre}cue{shown}_{f:06d}.png'))
                    # settled shots for subs_validate: the box is still typing
                    # on at the draw frame and for a while after (+150 is safe)
                    pending += [(f + 24, shown, 0, pre), (f + 40, shown, 0, pre), (f + 60, shown, 1, pre), (f + 120, shown, 2, pre), (f + 200, shown, 3, pre)]
                    # keep the queue in frame order: a card queued within 200
                    # frames of the previous one (or of a clear) sat behind that
                    # entry's +200 and lost its settled shots (B0E0_114, #39)
                    pending.sort(key=lambda e: e[0])
                last_shown, last_bank = shown, bank
            if shown not in (None, 0xFFFFFFFF):
                sync_shown[(bank, shown)].append(f)
            parked = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 128), 4))[0]
            if parked < 45:
                m3 = C.string_at(C.c_void_p(ram + 0x1058C), 3)
                _bcd = lambda b: (b >> 4) * 10 + (b & 15)
                plba = (_bcd(m3[0]) * 60 + _bcd(m3[1])) * 75 + _bcd(m3[2]) - 150
                _cl = cues_of(bank)
                for ci in sync_cues(bank).get(tuple(fchg[:2]), ()):
                    if _cl[ci]['start'] <= plba < _cl[ci]['end']:
                        eps = sync_heard.setdefault((bank, ci), [])
                        if eps and f - eps[-1][1] <= 120:
                            eps[-1][1] = f; eps[-1][2] += 1
                        else:
                            eps.append([f, f, 1])
            phase = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x1FC000 + 120), 4))[0]
            if phase == 2 and parked >= 45 and not live:
                if frozen_since is None:
                    frozen_since = f
                elif f - frozen_since >= FROZEN_FRAMES and not frozen_logged:
                    frozen_logged = True
                    frozen_hits.append((frozen_since, bank, shown))
                    L(f'{f}: FROZEN card {cue_id(bank, shown) if shown != 0xFFFFFFFF else "?"} of {bank} held in WAIT '
                      f'since {frozen_since} with no stream and no menu')
                    emu.image().save(os.path.join(out, f'frozen_{f:06d}.png'))
            else:
                frozen_since, frozen_logged = None, False
        _fc = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + 0x10018), 4))[0]
        if _fc != hang_ctr:
            hang_ctr, hang_since = _fc, f
        elif f - hang_since == HANG_FRAMES:
            # an in-game movie may hold the counter for a while: logged
            # here, the run stopped only when it stays stopped 5x as long
            L(f'{f}: HANG: the game frame counter stopped at {_fc} {HANG_FRAMES} frames ago')
            emu.image().save(os.path.join(out, f'hang_{f:06d}.png'))
        elif f - hang_since >= 5 * HANG_FRAMES:
            L(f'{f}: HANG for {5 * HANG_FRAMES} frames - stopping')
            break
        while pending and pending[0][0] <= f:
            at, which, k, pre = pending.pop(0)
            if last_shown == which:
                emu.image().save(os.path.join(out, f'{pre}cue{which}post{k}_{f:06d}.png'))

        if a.shot_every and f % a.shot_every == 0 and emu.frame and shots < int(os.environ.get('SHOT_CAP', 900)) and f >= int(os.environ.get('SHOT_FROM', 0)):
            emu.image().save(os.path.join(out, f'p_{f:06d}.png'))
            shots += 1
        if CELTRACE and ram is not None:
            # the nine portrait cels (ctx+0x4934, 0x5C each): x, y, the flags'
            # visible/built bits and column, the step and the private frame
            _cels = []
            for _i in range(9):
                _t = ctx + 0x4934 + 0x5C * _i
                _x, _y = struct.unpack_from('<HH', C.string_at(C.c_void_p(ram + ((_t + 0x4E) & 0x1FFFFF)), 6)[0:2] + C.string_at(C.c_void_p(ram + ((_t + 0x52) & 0x1FFFFF)), 2))
                _fl = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((_t + 0x58) & 0x1FFFFF)), 4))[0]
                _fn = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((_t + 0x10) & 0x1FFFFF)), 4))[0]
                _pv = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((_t + 0x14) & 0x1FFFFF)), 4))[0]
                _pb = C.string_at(C.c_void_p(ram + (_pv & 0x1FFFFF)), 4).hex() if 0x80000000 <= _pv < 0x80200000 else '-'
                _cels.append(f'{_i}:{_x},{_y},{_fl:08x},{_fn:08x},p{_pb}')
            _mw = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1AF4) & 0x1FFFFF)), 4))[0]
            _bs = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x2048 + 0x10) & 0x1FFFFF)), 4))[0]
            _key = (tuple(_cels), (_mw >> 20) & 7, (_mw >> 26) & 1, _bs)
            if _key != getattr(main, '_celkey', None):
                main._celkey = _key
                L(f'{f}: CEL band={_key[2]} spk={_key[1]} bstep={_bs:08x} ' + ' '.join(_cels))
            if os.environ.get('POKEX_AT') and f == int(os.environ['POKEX_AT']):
                # one-shot probe: x of column 0's three cels := 30, to see whether the engine restores x later
                for _i in range(3):
                    C.memmove(C.c_void_p(ram + ((ctx + 0x4934 + 0x5C * _i + 0x4E) & 0x1FFFFF)), struct.pack('<H', 30), 2)
                L(f'{f}: POKEX 30')
        if f in CAPAT:
            emu.image().save(os.path.join(out, f'c_{f:06d}.png'))
        if FF_RANGE:                            # FF_START=lo-hi: START held only in [lo, hi)
            emu.always = {emurun.BTN['start']} if FF_RANGE[0] <= f < FF_RANGE[1] else set()
        if f in STATE_AT:                       # STATE_AT=f1,f2: raw states for forensics (VRAM, RAM)
            open(os.path.join(out, f'state_{f:06d}.gz'), 'wb').write(gzip.compress(emu.state()))

        if ai >= len(actions):
            if done_at is None:
                done_at = f
                L(f'{f}: script complete')
            if a.stop_after and f - done_at > a.stop_after:
                break
            continue
        if queue:
            continue

        if 'section' in actions[ai]:
            # {"section": "..."}: a heading in a long route (the whole-game
            # chain), logged and noted in the play log
            L(f'{f}: === {actions[ai]["section"]}')
            if rec:
                rec.note('section', text=actions[ai]['section'], action=ai)
            ai, action_since = ai + 1, f
            continue
        if 'press' in actions[ai]:
            # {"press": "circle"} - one button, for screens that wait on the
            # pad without a menu or a box (the videophone's incoming call).
            press([actions[ai]['press']], f)
            L(f'{f}: press {actions[ai]["press"]}')
            ai, action_since = ai + 1, f
            continue
        if 'idle' in actions[ai]:
            # Touch nothing for N frames. The harness otherwise advances any
            # box within a few hundred frames, which is exactly what hides a
            # subtitle box left floating after a conversation: the player
            # sees it until they press something, the pilot never does. Logs
            # the dialogue task's step function (ctx+0x1EC0+0x10, the type-0
            # handler's state machine) whenever it changes.
            action = actions[ai]
            if f >= press_until:                # a {"press"} queued just
                emu.held = set()                # before the idle still has
                press_until = -1                # to be held its PRESS frames
            fn = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1ED0) & 0x1FFFFF)), 4))[0]
            if action.get('_since') is None:
                action['_since'] = f
                action['_fn'] = None
                L(f'{f}: idle for {action["idle"]} frames')
            bs = boxstate()
            if fn != action['_fn'] or bs != action.get('_bs'):
                L(f'{f}: idle: dialogue task fn={fn:08x} win={win:08x} {bs}')
                action['_fn'], action['_bs'] = fn, bs
            if a.shot_every and f % 20 == 0:
                emu.image().save(os.path.join(out, f'i_{f:06d}.png'))
            if f - action['_since'] >= action['idle']:
                emu.image().save(os.path.join(out, f'idle_end_{f:06d}.png'))
                L(f'{f}: idle over: dialogue task fn={fn:08x} win={win:08x}')
                ai, action_since = ai + 1, f
            continue

        pad = menustate.keypad(ram)
        if pad:
            pad_seen = f
        if a.trace:
            # transient engine objects (ctx+0x1954 list): type and args
            node = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((ctx + 0x1954) & 0x1FFFFF)), 4))[0]
            n = 0
            while 0x80000000 <= node < 0x80200000 and n < 8:
                t, a0, a1, a2 = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + ((node + 4) & 0x1FFFFF)), 4))[0], *struct.unpack_from('<III', C.string_at(C.c_void_p(ram + ((node + 8) & 0x1FFFFF)), 12))
                L(f'{f}: obj type={t} args={a0:08x} {a1:08x} {a2:08x}  {boxstate()}')
                if t == 0 and 0x80000000 <= a2 < 0x80200000:      # the SJIS text, as the engine converted it
                    _tx = C.string_at(C.c_void_p(ram + (a2 & 0x1FFFFF)))[:96]
                    L(f'{f}:   text sjis={_tx.hex()}')
                node = struct.unpack_from('<I', C.string_at(C.c_void_p(ram + (node & 0x1FFFFF)), 4))[0]; n += 1
        if a.trace and f % 60 == 0:
            L(f'{f}: trace pad={pad} live={live} idx={idx} n={count} win={win:08x} ai={ai} depth={depth} conf={confirmed} q={len(queue)} {boxstate()}')
        msb = C.string_at(C.c_void_p(ram + 0x11D7C), 2)
        if msb[0] in (0xF8, 0xF9) and (msb[1] == 0x01 or (
                msb[0] == 0xF9 and C.string_at(C.c_void_p(ram + 0x11DAE), 1)[0] == 0xFF   # not the keypad (stale fullwidth matcher labels)
                and any(any('Ａ' <= ch <= 'ｚ' for ch in x) for x in read_menu(ram)))):
            # (the videophone's password keyboard reads F9 with the matcher
            # targets - fullwidth Latin - as its label table)
            # The typing keyboard (the hospital name, Napoleon's password,
            # the BENSON cipher): the menu cursor reads live with count 0.
            # ctx+0x1D9E is the key cell on a 15-wide grid - A-O, P-Z, 0-9 -
            # 43 is backspace, ctx+0x1D9B the typed length (work/kbd_probe*).
            # Confirm types the highlighted key; START submits.
            action = actions[ai]
            if 'type' not in action:
                if confirmed is not None:
                    # the pick that opened the keyboard is done; no menu
                    # will come back to say so
                    ai, depth, confirmed, action_since = ai + 1, 0, None, f
                continue                       # never type blindly
            if f - last_press < STEP_GAP:
                continue
            cell = C.string_at(C.c_void_p(ram + 0x11D9E), 1)[0]
            tlen = C.string_at(C.c_void_p(ram + 0x11D9B), 1)[0]
            want = action['type'].upper()
            pos = action.get('_typed', 0)
            if pos == 0 and tlen and not action.get('_cleared'):
                target = 43                    # backspace the stray letters
            elif pos >= len(want) and tlen < len(want) and not action.get('_submitted'):
                # a key press the keyboard did not take (pressed too soon after
                # the previous one): type on from what the field really holds
                L(f'{f}: keyboard holds {tlen} of {len(want)} letters - typing on')
                action['_typed'] = pos = tlen
                continue
            elif pos >= len(want):
                if f - last_press < 60:
                    continue
                if not action.get('_submitted'):
                    press([action.get('then', 'start')], f)
                    action['_submitted'] = True
                    L(f'{f}: typed {want!r}, submitting')
                    continue
                if f - last_press > 200:
                    L(f'{f}: typed {want!r} - done')
                    ai, action_since = ai + 1, f
                continue
            else:
                ch = want[pos]
                target = (ord(ch) - 65) if ch.isalpha() else (30 + int(ch)) if ch.isdigit() else 45
            r, c = divmod(cell, 15); tr, tc = divmod(target, 15)
            if (r, c) == (tr, tc):
                press([OK], f)
                if target == 43:
                    if tlen <= 1:
                        action['_cleared'] = True
                else:
                    action['_typed'] = pos + 1
                    L(f'{f}: key {want[pos]!r} (cell {target})')
            else:
                press(['down' if r < tr else 'up' if r > tr else 'right' if c < tc else 'left'], f)
            continue
        if pad == 13 and 'dial' not in actions[ai]:
            # key byte unknown: the keypad graphic is up behind a dialogue
            # (the Act 2 Jamie call opens on a Snatcher) - not a pad we could
            # type into, so advance the box like anywhere else
            pad = 0
        if pad and (not live or 'dial' in actions[ai]):
            # (Catherine's age pad keeps the menu cursor live alongside the
            # keypad - its label table is the 数 matcher list)
            # The videophone keypad (menustate.keypad). A blind circle here
            # dials a digit - the old box-advance typed 0000000000 - so
            # nothing is pressed on it except by a `dial` action. The key
            # reads 0 for a while after a confirm; a nudge refreshes it.
            action = actions[ai] if ai < len(actions) else {}
            if 'dial' not in action and confirmed is not None and depth + 1 >= len(action.get('path', [])):
                # the path that opened the phone is done - no menu will come
                # back to say so while the pad is up
                ai, depth, confirmed, action_since = ai + 1, 0, None, f
                action = actions[ai] if ai < len(actions) else {}
            if 'dial' in action and f - last_press >= STEP_GAP:
                if dial_i >= len(action['dial']):
                    # the videophone auto-dials at six digits; a numeric
                    # answer (Catherine's "father's age") wants START or OK
                    if action.get('then') and not action.get('_then_done'):
                        press([action['then']], f)
                        action['_then_done'] = True
                        L(f'{f}: dial then {action["then"]}')
                        continue
                    if not action.get('then') and not action.get('_hash'):
                        # the phone usually dials itself at six digits, but a
                        # second call in one session sat on the pad (lab
                        # 39-1009 after Jamie); a number the dial table
                        # does not know needs START
                        if f - last_press <= 150:
                            continue
                        # '#' is just another character; START places the call
                        press(['start'], f)
                        action['_hash'] = True
                        L(f'{f}: pad idle after the number - pressing START')
                        continue
                    L(f'{f}: dialled {action["dial"]}')
                    ai, dial_i, action_since = ai + 1, 0, f
                    continue
                ch = action['dial'][dial_i]
                want = {'*': 10, '0': 11, '#': 12}.get(ch) or int(ch)
                if pad == 13:
                    press(['right'], f)         # unknown position: nudge
                    continue
                cr, cc = divmod(pad - 1, 3)
                tr, tc = divmod(want - 1, 3)
                if (cr, cc) == (tr, tc):
                    press([OK], f)
                    L(f'{f}: dial {ch!r} (key {want})')
                    dial_i += 1
                elif cr != tr:
                    press(['down' if (tr - cr) % 4 <= 2 else 'up'], f)
                else:
                    press(['right' if (tc - cc) % 3 == 1 else 'left'], f)
            continue
        if not live:
            fight = C.string_at(C.c_void_p(ram + 0x11DF0), 8)
            # ctx+0x1E14 is 1 only while a fight is running with the blaster
            # drawn (work/fight_sig.py); the crosshair bytes go stale after a
            # win and even survive into the next bank, and steering by them
            # alone had the harness holding fire through the whole Act 2
            # debrief, dismissing every subtitle it was there to film.
            # A fight is on while the LIFE bar is on screen (ps1/harness/life_ref.png,
            # the label at (28,163)-(60,175)), checked every 10 frames. The
            # RAM signals all lied: the crosshair bytes go stale after a win
            # and survive into the next bank (the harness held fire through
            # the whole Act 2 debrief and dismissed every subtitle), and
            # ctx+0x1E05/0x1E14 flip mid-fight.
            if f % 10 == 0:
                shot = np.asarray(emu.image().convert('RGB'), np.int16)
                crop = shot[163:175, 28:60]
                fight_phase = 1 if np.abs(crop - LIFE_REF).mean() < 25 else 0
                if fight_phase and script.get('fight') == 'corners':
                    # the Act 2 finale: the snatcher holds Mika and shows
                    # its head in one corner cell at a time; anything else
                    # hits her. Count non-black, non-grid pixels per corner
                    # against the chains' baseline (work/fight_watch2.py)
                    corner_cell = None
                    for cell, (x0, y0, x1, y1), base in ((0, (40, 10, 106, 56), 156), (2, (173, 10, 240, 56), 60),
                                                        (6, (40, 103, 106, 150), 0), (8, (173, 103, 240, 150), 0)):
                        c = shot[y0:y1, x0:x1]
                        n = int(((c.max(axis=2) > 40) & ~((c[:, :, 1] > c[:, :, 0]) & (c[:, :, 1] > c[:, :, 2]))).sum())
                        if n > base + 250:
                            corner_cell = cell
            if fight_phase:
                # Shootout. ctx+0x1DF0 = {crosshair cell, x, y, drawn}, and
                # ctx+0x1DF5 is the enemy's cell (row*3+col). The fight runs
                # from the "SELECT to draw" prompt onwards - enemies move
                # while the blaster is holstered - so draw first. The
                # crosshair moves only while a direction is HELD, so hold
                # the direction(s) for the enemy's cell and pulse fire.
                # Found with attic/fight_ram.py; blind cell-cycling lost in
                # 250 frames, this wins.
                if not in_fight:
                    L(f'{f}: shootout')
                    in_fight, fight_t0 = True, f
                    if rec:
                        rec.set_mode('fight')
                    # bookmark the prompt, so the fight can be probed by hand
                    fp = os.path.join(STATES_DIR, f'{a.scene}_fight.state.gz')
                    open(fp, 'wb').write(gzip.compress(emu.state()))
                    json.dump({'image': image_stamp(a.image), 'ok': OK}, open(fp[:-9] + '.json', 'w'))
                if a.trace and f % 10 == 0:
                    L(f'{f}: fight {C.string_at(C.c_void_p(ram + 0x11DF0), 16).hex()}')
                blind = script.get('fight') == 'blind' or os.environ.get('BLIND_FIGHT')
                if blind and f % 60 == 0:
                    L(f'{f}: blind F={C.string_at(C.c_void_p(ram + 0x11DF0), 0x18).hex()} '
                      f'G={C.string_at(C.c_void_p(ram + 0x11E10), 0x18).hex()} '
                      f'life={struct.unpack("<I", C.string_at(C.c_void_p(ram + 0x71E20), 4))[0]}')
                if blind and f - fight_t0 < int(os.environ.get('BLIND_DELAY', 0)):
                    emu.held = set()           # the idle player: let them come
                    continue
                if fight[3] != 1:
                    if (f - last_press) > 40:
                        press(['select'], f)
                    continue
                r, c = divmod(fight[5] % 9, 3)
                aim = script.get('fight', 'body')
                if isinstance(aim, list):
                    # one aim per shootout, in order (B200's snatcher takes
                    # the head first and the abdomen in its second fight);
                    # the last entry covers any further fight
                    aim = aim[min(fight_no, len(aim) - 1)]
                if aim == 'blind' or os.environ.get('BLIND_FIGHT'):
                    # no aiming at all, just pulse fire: the dev-test
                    # image (ps1/tools/devfights.py) must win like this
                    emu.held = {emurun.BTN[OK]} if (f // 3) % 2 == 0 else set()
                    press_until = -1
                    continue
                if aim == 'head':
                    # Snatchers only take headshots, and the head is not
                    # where ctx+0x1DF5 says: in Lisa's fight that byte stays
                    # 0 and ctx+0x1DF4 is her state - 1/2/3 standing (head in
                    # the centre cell), 0 hit/rising (head top-middle).
                    # Found with work/b120_fight.py; wins at near-full life.
                    r, c = (0 if fight[4] == 0 else 1), 1
                elif aim == 'top-middle':  # the Act 1 finale: fire straight up
                    r, c = 0, 1
                elif aim.startswith('cell'):   # a fixed cell read off the picture
                    r, c = divmod(int(aim[4:]), 3)
                elif aim == 'corners':
                    if corner_cell is None:
                        emu.held = set()       # hold fire: only Mika is in view
                        press_until = -1
                        continue
                    r, c = divmod(corner_cell, 3)
                # The crosshair sits in the centre cell and moves to a cell
                # only while that cell's direction(s) are HELD - so the
                # centre is reached by holding nothing, not by steering.
                dirs = set()
                if r == 0: dirs.add('up')
                if r == 2: dirs.add('down')
                if c == 0: dirs.add('left')
                if c == 2: dirs.add('right')
                on_target = fight[0] == r * 3 + c
                fire = on_target and (f // 3) % 2 == 0
                emu.held = {emurun.BTN[b] for b in dirs} | ({emurun.BTN[OK]} if fire else set())
                press_until = -1               # held across frames, not a tap
                continue
            if in_fight:
                L(f'{f}: shootout over')
                in_fight, fight_no = False, fight_no + 1
                if rec:
                    rec.set_mode(None)
                emu.held = set()
            # Nothing selectable: a dialogue box wants advancing, an idle
            # screen wants a nudge. Wait for the window word to hold still
            # first - the high byte cycles during type-on, so the low 16 are
            # what is timed.
            if f - cue_at < HOLD_AFTER_CUE:
                # A subtitle is up. It advances with the voice, and a circle
                # here dismisses it before the settled capture - the captures
                # then show an empty frame and the validator fails every row.
                continue
            if (f - win_since) > 80 and (f - last_press) > ADVANCE:
                # A box that circle does not advance is the "SELECT to draw
                # the Blaster" prompt at the start of a shootout.
                if (f - win_since) > 700 and (f - select_at) > 700:
                    press(['select'], f)
                    select_at = f
                else:
                    press([OK], f)
            continue
        if f - live_since < MENU_SETTLE:
            continue

        labels = [clean(x, last_scene or a.scene) for x in read_menu(ram)]
        # every distinct list once against the renderer's 4 x 2 grid: a
        # right-column label past 8 cells paints over the next row
        if labels and tuple(labels) not in geom_seen:
            geom_seen.add(tuple(labels))
            for i, lab, w, lim in geometry(labels, read_cells(ram)):
                geom_bad.append((f, last_scene or a.scene, i, lab, w, lim))
                L(f'{f}: GEOMETRY! {last_scene or a.scene} item {i} {lab!r} is {w} cells, column allows {lim}: {labels}')
        # Item opens [Look, Check] - two verbs - so "any verb present" called
        # it the top menu, the sweep never descended into it, and a run sat
        # in it for 3,000 frames waiting for Move. Real verb menus carry
        # four or more.
        nverbs = sum(x.lower() in VERBS for x in labels)
        is_top = nverbs >= 3 or (labels == top_labels and bool(labels))
        if mcsave and is_top and confirmed is None and f - live_since > 30:
            # the memory card per bank (beside the bookmark): the first verb
            # menu that offers Use Metal Gear or Save, MCSAVE_TRIES goes
            bank = last_scene or a.scene
            lab = [x.lower() for x in labels]
            if bank not in mc_done and mc_tries.get(bank, 0) < MCSAVE_TRIES and (
                    'use metal gear' in lab or 'save' in lab):
                mc_tries[bank] = mc_tries.get(bank, 0) + 1
                L(f'{f}: mcard: {bank}, save attempt {mc_tries[bank]} at {labels}')
                if game_save(f, scene=bank):
                    mc_done.add(bank)
                    dump_card(f, f'{bank}_auto', True, scene=bank)
                elif mc_tries[bank] >= MCSAVE_TRIES:
                    L(f'{f}: mcard: {bank} never saved, given up')
                continue
        if is_top and f - live_since > 30:
            # the scene's verb-menu window word: what subs_cue needs as
            # options.menu_word (mode = bits 9-14) before a bank can carry a
            # payload. Counted per scene, reported at the end.
            k = (last_scene or a.scene, low)
            if k not in menu_words:
                L(f'{f}: menu word {low:#06x} (mode {(low >> 9) & 0x3F}) at {labels}')
            menu_words[k] = menu_words.get(k, 0) + 1
        action = actions[ai]
        if 'mcard' in action:
            # {"mcard": "name", "slot": n}: the game's own save from here,
            # the card into the library (mcard.py push NAME for the MiSTer).
            # Only from a verb menu that reads as one: a resumed bookmark's
            # label table is stale until a press redraws it
            # "any": true takes any live menu offering Use Metal Gear (B1E0
            # Door 3: Go out/Look/Investigate/Use Metal Gear is two VERBS)
            if not is_top and not (action.get('any') and 'use metal gear' in [x.lower() for x in labels]):
                if (f - action_since) > action.get('patience', PATIENCE):
                    L(f'{f}: mcard {action["mcard"]!r}: no verb menu here ({labels}), skipped')
                    ai, action_since = ai + 1, f
                elif (f - last_press) > ADVANCE:
                    L(f'{f}: mcard: not a verb menu ({labels}), cancel')
                    press([BACK], f)
                continue
            ok = game_save(f, slot=action.get('slot'))
            if ok:
                dump_card(f, action['mcard'], ok, slot=action.get('slot'))
            else:
                mc_written.append((action['mcard'], last_scene or a.scene, False))
            ai, action_since = ai + 1, f
            continue
        if 'checkpoint' in action:
            # {"checkpoint": name, "slot": n}: the game's own Save into card
            # slot n (the MiSTer replay resumes from these), then a raw state
            # + the card beside it in STATES_DIR (--state-file resumes there)
            if not is_top:
                if (f - action_since) > action.get('patience', PATIENCE):
                    L(f'{f}: checkpoint {action["checkpoint"]!r}: no verb menu ({labels}), skipped')
                    ai, action_since = ai + 1, f
                elif (f - last_press) > ADVANCE:
                    press([BACK], f)
                continue
            slot = action.get('slot', 1)
            if rec:
                rec.note('save_begin', name=action['checkpoint'], slot=slot)
            ok = game_save(f, slot=slot)
            if not ok:
                L(f'{f}: CHECKPOINT FAILED: {action["checkpoint"]} - no Save from {labels}; stopping')
                break
            path = os.path.join(STATES_DIR, f'{action["checkpoint"]}.state.gz')
            open(path, 'wb').write(gzip.compress(emu.state()))
            emu.save_card(path[:-9] + '.card')
            nxt = action.get('_i', ai) + 1
            json.dump({'image': image_stamp(a.image), 'ok': OK, 'scene': last_scene or a.scene,
                       'action': nxt, 'route': route, 'saved': ok, 'slot': slot},
                      open(path[:-9] + '.json', 'w'))
            if rec:
                rec.note('checkpoint', name=action['checkpoint'], slot=slot, saved=ok, action=nxt,
                         state=path)
            L(f'{f}: checkpoint {action["checkpoint"]} slot {slot} saved={ok} '
              f'(resume: --state-file {path} --start {nxt})')
            ai, action_since = ai + 1, f
            continue
        if 'save' in action:
            # bookmark at a live menu, so a later run can resume here with
            # --state NAME instead of replaying the whole scene
            path = os.path.join(STATES_DIR, f'{action["save"]}.state.gz')
            if os.path.exists(path):
                # a route save over an existing bookmark keeps the old one as
                # NAME.prev: a run that never reached its spot once replaced
                # B010_harry with the room list (2026-09-11)
                os.replace(path, path[:-9] + '.prev.state.gz')
            open(path, 'wb').write(gzip.compress(emu.state()))
            json.dump({'image': image_stamp(a.image), 'ok': OK}, open(path[:-9] + '.json', 'w'))
            L(f'{f}: saved state {action["save"]} at {labels}')
            ai, action_since = ai + 1, f
            continue
        if 'fight' in action:
            # change where the pilot aims from here on: B200's snatcher takes
            # the head first and the abdomen in its second fight, and the aim
            # is otherwise route-wide
            script['fight'] = action['fight']
            L(f'{f}: aim {action["fight"]}')
            ai, action_since = ai + 1, f
            continue
        if 'cancel' in action:
            # back out of a persistent submenu (the duct's direction list
            # stays open after a move, hiding Look/Check)
            press([BACK], f)
            L(f'{f}: cancel at {labels}')
            ai, action_since = ai + 1, f
            continue
        if 'type' in action:
            # a menu is live again: the keyboard took the answer (or a box
            # dismissed it) - move on
            if action.get('_submitted'):
                L(f'{f}: typed {action["type"]!r} - done')
            else:
                L(f'{f}: keyboard gone before {action["type"]!r} was typed')
            ai, action_since = ai + 1, f
            continue
        if 'dial' in action:
            # a menu opened while dialling: '#' brings up Call/No call, so
            # the number is done; anything else, wait it out
            if dial_i >= len(action['dial']):
                L(f'{f}: dialled {action["dial"]}')
                ai, dial_i, action_since = ai + 1, 0, f
            continue
        if rec and any(k in action for k in ('light_at', 'light_to', 'light')):
            rec.set_mode('light')
        if 'light_at' in action:
            # Metal's light steered on its RAM position (ctx+0x658A x,
            # ctx+0x658E y; ~1 unit per held frame): B1E0 Door 3's drawer
            # answers at (120, 60), the matches at (144, 84) (#65)
            tx, ty = action['light_at']
            x, y = struct.unpack('<hh', C.string_at(C.c_void_p(ram + 0x1658A), 2)
                                 + C.string_at(C.c_void_p(ram + 0x1658E), 2))
            if x == tx and y == ty:
                emu.held = set()
                L(f'{f}: light at ({x},{y})')
                ai, action_since, last_press = ai + 1, f, f
                continue
            d = ('right' if tx > x else 'left') if x != tx else ('down' if ty > y else 'up')
            emu.held = {emurun.BTN[BACK], emurun.BTN[d]}
            press_until = -1
            if f - action_since > 1500:
                L(f'{f}: light stuck at ({x},{y}), wanted ({tx},{ty})')
                emu.held = set(); ai, action_since = ai + 1, f
            continue
        if 'light_to' in action:
            # move Metal's light to a screen position (x, y in the 200x140
            # picture): measure the lit blob every 10 frames, hold cancel +
            # the direction that closes the larger gap, stop within 4 px
            tx, ty = action['light_to']
            if f % 10 == 0:
                a2 = np.asarray(emu.image().convert('RGB'), np.int16)[10:150, 40:240].max(axis=2)
                ys, xs = np.nonzero(a2 > 40)
                if len(xs):
                    x, y = int(xs.mean()), int(ys.mean())
                    dx, dy = tx - x, ty - y
                    if abs(dx) <= 4 and abs(dy) <= 4:
                        emu.held = set()
                        L(f'{f}: light at ({x},{y})')
                        ai, action_since, last_press = ai + 1, f, f
                        continue
                    d = ('right' if dx > 0 else 'left') if abs(dx) >= abs(dy) else ('down' if dy > 0 else 'up')
                    emu.held = {emurun.BTN[BACK], emurun.BTN[d]}
                    press_until = -1
                    if f - action_since > 3000:
                        L(f'{f}: light stuck at ({x},{y}), wanted ({tx},{ty})')
                        emu.held = set(); ai, action_since = ai + 1, f
            continue
        if 'light' in action:
            # Queen Hospital's dark room: Metal's light moves while the
            # CANCEL button is held with a direction (the menu stays up).
            # {"light": [["right", 60], ["down", 30]]} holds each in turn.
            moves = action['light']
            k = action.get('_step', 0)
            if k >= len(moves):
                emu.held = set()
                L(f'{f}: light moved {moves}')
                ai, action_since = ai + 1, f
                continue
            d, n = moves[k]
            emu.held = {emurun.BTN[BACK], emurun.BTN[d]}
            press_until = -1
            action['_held'] = action.get('_held', 0) + 1
            if action['_held'] >= n:
                emu.held = set(); press_until = f + 1
                action['_step'], action['_held'] = k + 1, 0
                last_press = f
            continue
        if rec and rec.mode == 'light':
            rec.set_mode(None)
        if 'sweep' in action:
            # Luiz's method, made mechanical: open each verb and pick every
            # item it offers, `rounds` times over. Items that appear as the
            # scene progresses (Memory after Check/Little John) are caught by
            # the later rounds. Each verb starts as a bare pick; every submenu
            # it opens is read live and one pick per LABEL queued behind it
            # (`seen` is per round). Labels, not indices: menus shrink as
            # items are taken (Wear vanished after the first look and `#2`
            # stopped meaning Hand), and an index sibling then misses.
            exp = []
            for _ in range(action.get('rounds', 1)):
                seen = {}
                exp += [{'path': [verb], 'optional': True, 'pick': True,
                         'patience': 400, 'seen': seen,
                         'each': action.get('each'), 'each_rounds': action.get('each_rounds', 1),
                         'avoid': action.get('avoid', ())}
                        for verb in action['sweep']]
            L(f'{f}: sweep {action["sweep"]} x{action.get("rounds", 1)}')
            actions[ai:ai + 1] = exp
            action = actions[ai]
        path = action['path']
        # A confirm is only believed once the menu has gone away. The press
        # is ignored if it lands while the menu is still opening (14 frames
        # after `live` was not enough; 98 was), so a confirm that leaves the
        # same menu live is simply pressed again.
        if confirmed is not None:
            if live_since > confirmed:         # menu closed and reopened: it took
                depth += 1
                confirmed, steps = None, 0
                if depth == 1 and is_top and labels == pre_labels and (
                        live_since - confirmed_at < 30 or (len(path) > 1 and live_since - confirmed_at < 120)):
                    # the same menu straight back within a few frames: the
                    # press was read as CANCEL. A real pick that just prints
                    # a line keeps the menu away for 60+ frames.
                    bounces += 1
                    if bounces >= 2:
                        OK, BACK = BACK, OK
                        bounces = 0
                        L(f'{f}: confirm bounced twice on {labels} - swapping buttons: confirm={OK} cancel={BACK}')
                    depth = 0
                    continue
                if depth < len(path) and is_top:
                    # The verb had no submenu of its own (Hear, Enter): the
                    # top menu is back.
                    L(f'{f}: {path[0]!r} needed no submenu; {path[1:]} not applicable')
                    depth = len(path)
            elif f - confirmed > 60:
                press([OK], f)
                confirmed = f
                continue
            else:
                continue
        if action.get('pick') and depth > 0 and not is_top:
            # inside a submenu on a sweep: queue every label not yet picked
            # this round under this prefix
            known = action['seen'].setdefault(tuple(path[:depth]), set())
            avoid = AVOID | {x.lower() for x in action.get('avoid', ())}
            new = [x for x in labels if x and x not in known and x.lower() not in avoid]
            if new:
                known.update(new)
                actions[ai + 1:ai + 1] = [dict(action, path=path[:depth] + [x]) for x in new]
                L(f'{f}: {path[:depth]} offers {labels} -> +{len(new)} picks')
            if depth >= len(path):
                # this pick ended on a menu rather than a line: the siblings
                # just queued cover it - back out and move on
                press([BACK], f)
                ai, depth, steps, reps_done = ai + 1, 0, 0, 0
                action_since = f
                continue
        if depth >= len(path):                 # path complete
            depth, steps, sub_misses = 0, 0, 0
            reps_done += 1
            if reps_done >= action.get('reps', 1):
                if action.get('each') and len(path) > 1:
                    # a room was entered: sweep it before the next room
                    actions.insert(ai + 1, {'sweep': action['each'], 'rounds': action.get('each_rounds', 1),
                                            'avoid': action.get('avoid', ())})
                ai, reps_done = ai + 1, 0
                action_since = f
            continue
        want = path[depth]
        ti = None
        for alt in want.split('|'):            # "Go out|Forward": first offered wins
            ti = find(labels, alt)
            if ti is not None:
                break
        if ti is None and depth + 1 < len(path) and not is_top:
            # Some menus persist: Enter at the HQ desk leaves the room list
            # up and cross does not close it, so the next pick's 'Enter' is
            # never offered while its room already is. Skip the step we are
            # evidently past.
            nxt = [find(labels, alt) for alt in path[depth + 1].split('|')]
            if any(x is not None for x in nxt):
                depth += 1
                continue
        if ti is None or ti >= max(count, 1):
            if depth > 0:
                # LOG what the submenu actually held - this branch used to
                # back out silently, so a run could press Look thirteen times
                # and the log never said which options Look had opened.
                L(f'{f}: submenu miss - wanted {want!r}, {path} offered {labels}')
                press([BACK], f)
                depth, steps = 0, 0
                sub_misses += 1
                if sub_misses >= 2 or action.get('pick'):   # will not change by itself
                    skip(f, 'MISS', want, labels)
                continue
            if (f - action_since) < action.get('patience', PATIENCE):  # not offered yet
                # Crossing out of the TOP menu closes it and the game reopens
                # it, forever. Only back out when nothing here is a verb -
                # i.e. we are stranded in a submenu.
                if not is_top and (f - last_press) > ADVANCE:
                    press([BACK], f)
                continue
            skip(f, 'MISS', want, labels)
            continue
        if ti == idx and f - live_since < action.get('delay', 0):
            continue                           # {"delay": N}: let the menu sit N frames first
        if ti == idx:
            L(f'{f}: action {ai} {path} step {depth}: {want!r} = item {ti} of {labels} -> confirm')
            press([OK], f)
            confirmed = confirmed_at = f
            pre_labels = list(labels)
            if depth == 0:
                top_labels = list(labels)
            continue
        # The cursor wraps and moves through every item, right column
        # included, so `down` alone reaches anything. Space the presses: a
        # down every 6 frames left the button effectively held and the
        # cursor never moved (24 presses, STUCK on item 0).
        if f - last_press < STEP_GAP:
            continue
        press(['down'], f)
        steps += 1
        if steps > MAX_STEPS:
            skip(f, 'STUCK', want, labels)

    problems = panel_scan(sorted(glob.glob(os.path.join(out, 'p_*.png'))))
    if os.environ.get('PANEL_EMPTY_OK'):
        # the duct maze (B220): the game's own direction box sits empty
        # between moves with no card of ours anywhere near - only a panel
        # riding up counts there
        problems = [(p, why) for p, why in problems if 'empty' not in why]
    L(f'panel check: {len(problems)} problem(s) over {shots} captures')
    for p, why in problems[:10]:
        L(f'  {os.path.basename(p)}: {why}')
    for (sc, w), n in sorted(menu_words.items(), key=lambda kv: -kv[1]):
        L(f'menu word {sc}: {w:#06x} ({n} frames live, mode {(w >> 9) & 0x3F})')
    L(f'geometry: {len(geom_bad)} problem(s) over {len(geom_seen)} distinct lists')
    for fr, sc, i, lab, w, lim in geom_bad:
        L(f'  GEOMETRY! {sc} item {i} {lab!r} {w} > {lim} cells (frame {fr})')
    drawn = drawn_of.get(a.scene, [])
    if mc_written:
        L('memory cards: ' + ', '.join(f'{n} ({s}{"" if ok else ", NOT saved"})' for n, s, ok in mc_written))
    L(f'end: {ai}/{len(actions)} actions, {len(set(drawn))} distinct cues, '
      f'{len(misses)} miss(es); cues {sorted(set(drawn))}'
      + ''.join(f'; {b}: {len(set(d))} cues' for b, d in sorted(drawn_of.items()) if b != a.scene))
    for i, want, labs in misses:
        L(f'  action {i}: wanted {want!r}, saw {labs}')
    for key in list(spk_tally):
        spk_close(*key, f)
    vc = collections.Counter(v for v, *_ in spk_verdicts)
    L(f'speakers: {len(spk_verdicts)} cards, ok {vc["ok"] + vc["ear"]}, unverifiable {vc["unverifiable"]}, '
      f'DATA? {vc["DATA?"] + vc["DATA?/FACE!"]}, FACE! {vc["FACE!"] + vc["DATA?/FACE!"]}')
    for v, cid, data, eng, face in spk_verdicts:
        if v not in ('ok', 'ear', 'unverifiable'):
            L(f'  {v} {cid}: data={data} engine={",".join(f"{k}:{n}" for k, n in eng) or "-"} face={",".join(f"{k}:{n}" for k, n in face) or "-"}')
    # the sync gate's verdicts
    unshown, late = [], []
    for (bank, ci), eps in sorted(sync_heard.items()):
        cl = cues_of(bank)
        if not (0 <= ci < len(cl)):
            continue
        for first, last, n in eps:
            if n < SYNC_MIN:
                continue
            sh = [x for x in sync_shown.get((bank, ci), ()) if first - 240 <= x <= last + 240]
            if not sh:
                unshown.append((bank, cl[ci]['id'], first, n))
            elif sh[0] - first > SYNC_LATE:
                late.append((bank, cl[ci]['id'], first, sh[0] - first))
    L(f'sync: {sum(1 for e in sync_heard.values() for x in e if x[2] >= SYNC_MIN)} lines heard, '
      f'UNSHOWN {len(unshown)}, LATE {len(late)}, FROZEN {len(frozen_hits)}')
    for bank, cid, first, n in unshown:
        L(f'  UNSHOWN {bank} {cid}: heard {n} frames from {first}, no card')
    for bank, cid, first, d in late:
        L(f'  LATE {bank} {cid}: card {d} frames after its line began at {first}')
    for since, bank, sh in frozen_hits:
        L(f'  FROZEN {bank} {cue_id(bank, sh) if sh != 0xFFFFFFFF else "?"}: since {since}')
    import subprocess
    for bank, drawn in sorted(drawn_of.items()):
        subs = os.path.join(ROOT, 'ps1/translation', f'subs_{bank}.json')
        if not drawn or not os.path.exists(subs):
            continue
        cmd = [sys.executable, os.path.join(HERE, 'subs_validate.py'), out, subs]
        if bank != a.scene:
            cmd += ['--prefix', f'x{bank}_']
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        summary = [l for l in r.stdout.splitlines() if ' pass, ' in l]
        L((f'{bank}: ' if bank != a.scene else '') + (summary[-1] if summary else r.stderr[-500:]))
    if rec:
        rec.close()
    if RAMTOUCH and getattr(main, '_rt_mask', None) is not None:
        _path = RAMTOUCH.split(',', 1)[1] if ',' in RAMTOUCH else os.path.join(out, 'ramtouch.npy')
        np.save(_path, main._rt_mask)
        L(f'ramtouch: {int(main._rt_mask.sum())} of 2 MB bytes changed across samples -> {_path}')
    log.close()


if __name__ == '__main__':
    main()
