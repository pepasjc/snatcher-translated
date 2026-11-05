"""The harness's backup-RAM library, and one save at a time onto the MiSTer.

    python pce/tools/pce_saves.py list                 # what the harness saved
    python pce/tools/pce_saves.py scenes               # a save per scene module, or why none
    python pce/tools/pce_saves.py pack acts 334 382 574 606   # four saves in one file, slots 1-4
    python pce/tools/pce_saves.py graft mod574 --into 2 --to acts   # one save into a slot of another
    python pce/tools/pce_saves.py remote               # the MiSTer's games and saves
    python pce/tools/pce_saves.py push mod318          # that save onto the MiSTer
    python pce/tools/pce_saves.py pull                 # the MiSTer's save back here
    python pce/tools/pce_saves.py retroarch mod574 --play   # the save into Luiz's RetroArch, and play
    python pce/tools/pce_saves.py retroarch-pull       # RetroArch's save back here

The saves come from `pce/harness/pcemenu.py` (PCESAVE=1 / --bram, or a route's
{"bram": "name"} step): the pilot drives the game's own Save - Use Metal Gear >
Save > slot 1 > Save - and writes the core's 2 KB backup RAM to
work/pce/saves/<name>.sav, with work/pce/saves/index.json holding the module,
the route and the frame. `pce/harness/mint_saves.py` mints one per scene
module from the act routes' savestates (`mod<rec>`), and `scenes` tables them
against MODULES (the label per module) and NO_SAVE (the modules whose menus
never offer Save). The files are gitignored scratch.

One backup RAM holds four Snatcher saves (4 x 416 B + the 16-byte header, in
2,048), so `pack` puts up to four scenes into one file - slots 1-4 in the
game's own Load menu - and `graft` moves one save into a slot of another
file: the entry is copied, renamed SNATCHER0<slot> and its checksum redone
(the 16-bit negated sum of the entry past the checksum word, checked against
the game's own saves; a fresh boot of the harness showed slots 1, 2 and 4 of a
packed file on CASE FILES and loaded slot 4's scene). A packed file pushed to
the MiSTer is every scene in it one CONTINUE away.

Format (checked by bytes, 2026-09-14): the PC Engine's BRAM is 2,048 bytes -
'HUBM', a pointer to the end of the area at +4 ($8800) and to the first free
byte at +6 ($8010 when empty), then the entries, each {size:2, checksum:2, ?:2,
name:10, data}. Snatcher's is 400 bytes and calls itself SNATCHER01..04 (the
slot). The MiSTer's TGFX16 core keeps exactly the same 2,048 bytes in
/media/fat/saves/TGFX16/<image name>.sav (NOT .../TGFX16-CD/), so the file is
copied over as it is - no byte order, no size, no header to convert. The name
is the loaded image's, i.e. the CHD's basename: `remote` looks it up under
/media/usb0/games/TGFX16-CD and /media/fat/games/TGFX16-CD, MISTER_SAVE
overrides it.

The core reads that file when the game is LOADED, and writes it back on its own
schedule: push with the game not running (or reload it afterwards), then pick
the file on the title's CONTINUE > CASE FILES screen (SNATCHER 1-4 = the slots;
there is no Load under Use Metal Gear on the PCE - checked in the harness). Every push copies the MiSTer's current
save to work/pce/saves/mister_backup_<stamp>.sav first.

RetroArch (the install named by RETROARCH in lib/devpaths.py -
never the emudeck one the harness and the Play-*.bat use): Beetle PCE exposes the
same 2,048 bytes as SAVE_RAM and RetroArch keeps it as <saves>/<content name>.srm
(savefile_directory ":/saves", no per-content sorting there), the content name
being the CHD's basename - RETROARCH_GAME, default 'Snatcher CD-ROMantic (Japan)
[dev]' = patched/pce/<that>.chd (chdman builds it from the image). `retroarch
NAME` backs the .srm up to work/pce/saves/retroarch_backup_<stamp>.sav and copies
ours over it; `--play` then starts RetroArch on the CHD with mednafen_pce. It
refuses while retroarch.exe runs: RetroArch writes the .srm back when the content
closes and would undo the copy.
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

SAVES = os.path.join(WORK, "pce", "saves")
HOST = devpaths.get('MISTER_HOST', '')
RSAVES = os.environ.get('MISTER_SAVEDIR', '/media/fat/saves/TGFX16')
GAMEDIRS = ['/media/usb0/games/TGFX16-CD', '/media/fat/games/TGFX16-CD']
DEFAULT_GAME = os.environ.get('MISTER_SAVE', 'Snatcher CD-ROMantic (Japan) [dev]')
SSH_OPTS = ['-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes']
RETROARCH = devpaths.get('RETROARCH', '')
RA_ROOT = os.path.dirname(RETROARCH)
RA_SAVES = os.environ.get('RETROARCH_SAVES', os.path.join(RA_ROOT, 'saves'))
RA_CORE = os.path.join(RA_ROOT, 'cores', 'mednafen_pce_libretro.dll')
RA_GAME = os.environ.get('RETROARCH_GAME', 'Snatcher CD-ROMantic (Japan) [dev]')
RA_CHD = os.path.join(ROOT, 'patched', 'pce', RA_GAME + '.chd')


def run(cmd, **kw):
    print('>', ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
    return subprocess.run(cmd, **kw)


def ssh(script, capture=False):
    cmd = ['ssh', *SSH_OPTS, HOST, script]
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'ssh failed: {r.stderr.strip()}')
        return r.stdout
    return run(cmd)


def index():
    p = os.path.join(SAVES, "index.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def remote_game():
    """The MiSTer's image name for our CHD (the save file is <that>.sav)."""
    if os.environ.get('MISTER_SAVE'):
        return DEFAULT_GAME
    out = ssh('find %s -maxdepth 2 -iname "*.chd" 2>/dev/null; true' % ' '.join(GAMEDIRS), capture=True)
    hits = [os.path.splitext(os.path.basename(l.strip()))[0] for l in out.splitlines() if l.strip()]
    snat = [h for h in hits if 'snatcher' in h.lower()]
    if len(snat) == 1:
        return snat[0]
    if snat:
        dev = [h for h in snat if 'dev' in h.lower()]
        if len(dev) == 1:
            return dev[0]
        print(f'several Snatcher images on the MiSTer: {snat}; using MISTER_SAVE={DEFAULT_GAME}')
    return DEFAULT_GAME


# the scene modules (class-1 records of the stage-2 file table) and what they
# are, from the PS1 banks their cue files map to and the act routes' states
# (mint_saves.py --list shows which state sits where); a save is mod<rec>
MODULES = {
    158: "Save handler (Act 1)", 174: "Videophone (Act 1)", 190: "Videophone (Act 2)",
    206: "Telephone Game Quiz", 222: "Gaudi's database", 238: "Act 2 recap",
    254: "Gaudi's name search", 270: "Save handler (Act 2)", 286: "Save handler (Act 2, late)",
    302: "Save handler (Act 3)", 318: "JUNKER HQ (Act 1)", 334: "Factory ruins",
    350: "JUNKER HQ (after the factory)", 366: "Gillian's home (Act 1)", 382: "Gibson's house",
    398: "Altamira (Act 1)", 414: "Joy Division", 430: "Outer Heaven (outside)",
    446: "Ivan's apartment", 462: "Freddy's apartment", 478: "JUNKER HQ (Act 2)",
    494: "Altamira (Act 2)", 510: "Oleen Hospital / cockpit", 526: "Gibson's house (Act 2)",
    542: "Queen Hospital (with Randam)", 558: "Outer Heaven (Act 2)", 574: "Gillian's home (Act 2)",
    590: "Basement / morgue", 606: "Tunnel / taxi", 622: "JUNKER HQ (final part)",
    638: "Act 3 start / quiz", 654: "Culture room", 670: "Ending",
}
# modules the game offers no Save in (no Use Metal Gear > Save on any menu there):
# a save cannot be minted, and the scene is reached from its neighbour's
NO_SAVE = {
    158: "the save menu itself", 174: "videophone (from a room)", 190: "videophone (from a room)",
    206: "the quiz screen (from the videophone)", 222: "Gaudi's terminal (from HQ)",
    238: "Act 2 recap (plays on load)", 254: "Gaudi's name search (from HQ)",
    270: "the save menu itself", 286: "the save menu itself", 302: "the save menu itself",
    318: "HQ tour, Metal Gear not yet with Gillian", 638: "the Act 3 quiz (from 622's save)",
    670: "countdown / ending",
}


def modules():
    """The class-1 records of the file table, in disc order."""
    p = os.path.join(WORK, "pce", "filetable.json")
    try:
        return json.load(open(p, encoding="utf-8"))["1"]
    except (OSError, ValueError, KeyError):
        return [{"rec": r} for r in sorted(MODULES)]


def label(rec):
    try:
        return MODULES.get(int(rec), "")
    except (TypeError, ValueError):
        return ""


def act_of(rec):
    rec = int(rec)
    m = re.search(r'Act (\d)', label(rec))
    return int(m.group(1)) if m else 1 if rec < 478 else 2 if rec < 590 else 3


def cmd_scenes(a):
    """One line per scene module: its save (name, state it came from, date) or why none."""
    ix = index()
    have = 0
    mods = modules()
    for e in mods:
        rec = e["rec"]
        saves = sorted((n, s) for n, s in ix.items()
                       if str(s.get("module")) == str(rec) and s.get("saved") and s.get("used", 0) > 0x10
                       and not n.startswith(("mister_", "retroarch_")))
        lab = label(rec)
        if saves:
            n, s = saves[0]
            have += 1
            more = f" (+{len(saves) - 1})" if len(saves) > 1 else ""
            print(f'{rec:>4}  act {act_of(rec)}  {lab:32} save {n}{more}  slot {s.get("slot", 1)}  '
                  f'{(s.get("date") or "")[:10]}  {s.get("route") or ""}')
        elif rec in NO_SAVE:
            print(f'{rec:>4}  act {act_of(rec)}  {lab:32} -    no Save here: {NO_SAVE[rec]}')
        else:
            print(f'{rec:>4}  act {act_of(rec)}  {lab:32} -    not minted yet (pce/harness/mint_saves.py {rec})')
    print(f'{have} of {len(mods)} modules have a save; pce_saves.py push NAME puts one on the MiSTer, '
          f'pack NAME a b c d up to four in one file')


# --- the backup RAM's entries: {size:2, checksum:2, ?:2, name:10, data} from +0x10 ---

def entries(raw):
    """[(offset, size, name)] of a backup RAM's entries, up to its free pointer."""
    out, p, free = [], 0x10, (raw[6] | raw[7] << 8) - 0x8000
    while p + 16 <= free:
        size = raw[p] | raw[p + 1] << 8
        if size < 16 or p + size > free:
            break
        out.append((p, size, bytes(raw[p + 6:p + 16])))
        p += size
    return out


def checksum(entry):
    return (-sum(entry[4:])) & 0xFFFF


def slot_of(name):
    return int(name[8:10]) if name[:8] == b'SNATCHER' and name[8:10].isdigit() else None


def empty_bram():
    raw = bytearray(2048)
    raw[:4] = b'HUBM'
    raw[4:8] = bytes([0x00, 0x88, 0x10, 0x80])         # area end $8800, first free $8010
    return raw


def graft_into(dst, entry, slot):
    """`entry` (one whole BRAM entry) into `dst` (a bytearray) as SNATCHER0<slot>,
    replacing the slot's entry if there is one, else appended at the free pointer."""
    e = bytearray(entry)
    e[6:16] = b'SNATCHER%02d' % slot
    ck = checksum(e)
    e[2], e[3] = ck & 0xFF, ck >> 8
    free = (dst[6] | dst[7] << 8) - 0x8000
    for off, size, name in entries(dst):
        if slot_of(name) == slot:
            if size != len(e):
                sys.exit(f'slot {slot} in the target holds a {size}-byte entry, ours is {len(e)}')
            dst[off:off + size] = e
            return
    if free + len(e) > len(dst):
        sys.exit(f'no room: {free} B used, {len(e)} B to add, {len(dst)} B in the backup RAM')
    dst[free:free + len(e)] = e
    free += len(e) + 0x8000
    dst[6], dst[7] = free & 0xFF, free >> 8


def resolve(name):
    """A save by name, by module number (mod<rec>), or by the state it was
    minted from (`home2_bath` -> mod574: the index's route reads `state <name>`)."""
    name = str(name)
    if name.isdigit():
        return 'mod' + name
    if not os.path.exists(os.path.join(SAVES, name + '.sav')):
        for k, e in index().items():
            if (e.get('route') or '') == f'state {name}':
                return k
    return name


def read_save(name):
    p, _ = local(resolve(name))
    return p, bytearray(open(p, 'rb').read())


def write_save(name, raw, note):
    os.makedirs(SAVES, exist_ok=True)
    out = os.path.join(SAVES, name if name.endswith('.sav') else name + '.sav')
    open(out, 'wb').write(bytes(raw))
    ixp = os.path.join(SAVES, 'index.json')
    ix = index()
    key = os.path.basename(out)[:-4]
    ix[key] = {'file': os.path.basename(out), 'module': note.get('module', 'pack'), 'route': note.get('route'),
               'slot': note.get('slot'), 'slots': note.get('slots'), 'bytes': len(raw),
               'used': (raw[6] | raw[7] << 8) - 0x8000, 'header': bytes(raw[:4]).decode('latin1'),
               'saved': True, 'page': note.get('page', ''),
               'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    with open(ixp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(ix, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    return out


def save_entry(name, slot=None):
    """The one Snatcher entry of a save file (or the one in `slot`)."""
    p, raw = read_save(name)
    ents = [(o, s, n) for o, s, n in entries(raw) if n[:8] == b'SNATCHER']
    if slot is not None:
        ents = [e for e in ents if slot_of(e[2]) == slot]
    if not ents:
        sys.exit(f'{p}: no Snatcher save{" in slot %d" % slot if slot else ""} '
                 f'(entries: {[n.decode("latin1") for _, _, n in entries(raw)]})')
    if len(ents) > 1 and slot is None:
        # a harness dump carries whatever the state's backup RAM held besides
        # its own save: the index says which slot the pilot wrote
        own = index().get(os.path.basename(p)[:-4], {}).get('slot')
        ents = [e for e in ents if slot_of(e[2]) == own] or ents
        if len(ents) > 1:
            sys.exit(f'{p} holds {len(ents)} Snatcher saves - say which with --slot')
    o, s, n = ents[0]
    return raw[o:o + s], slot_of(n)


def slot_note(slots):
    return '; '.join(f'{s["slot"]}: {s["from"]} ({s["label"] or "?"})' for s in slots)


def cmd_pack(a):
    """Up to four saves into one file, slot 1-4 in the order given."""
    if not 1 <= len(a.saves) <= 4:
        sys.exit('pack takes one to four saves')
    ix = index()
    raw = empty_bram()
    slots = []
    for i, n in enumerate(a.saves, 1):
        n = resolve(n)
        entry, _ = save_entry(n)
        graft_into(raw, entry, i)
        e = ix.get(n, {})
        slots.append({'slot': i, 'from': n, 'module': e.get('module'), 'label': label(e.get('module', 0))})
    out = write_save(a.name, raw, {'module': 'pack', 'slots': slots, 'route': 'pack ' + ' '.join(a.saves),
                                   'page': slot_note(slots)})
    print(f'{out}: {len(slots)} save(s), {(raw[6] | raw[7] << 8) - 0x8000} B in use')
    for s in slots:
        print(f'  CASE FILES > SNATCHER {s["slot"]}: {s["from"]} ({s["label"] or "?"})')


def cmd_graft(a):
    """One save's entry into a slot of another file (a new file with --to)."""
    src = resolve(a.name)
    entry, _ = save_entry(src, a.slot)
    target = resolve(a.to) if a.to else src
    if a.to and not os.path.exists(os.path.join(SAVES, target + '.sav')):
        raw = empty_bram()
    else:
        _, raw = read_save(target)
    graft_into(raw, entry, a.into)
    ix = index()
    e = ix.get(target, {})
    slots = [s for s in (e.get('slots') or []) if s.get('slot') != a.into]
    if not e.get('slots') and e.get('module') and e.get('slot') != a.into:
        slots.append({'slot': e.get('slot', 1), 'from': target, 'module': e['module'], 'label': label(e['module'])})
    slots.append({'slot': a.into, 'from': src, 'module': ix.get(src, {}).get('module'),
                  'label': label(ix.get(src, {}).get('module', 0))})
    slots.sort(key=lambda s: s['slot'])
    out = write_save(target, raw,
                     {'module': e.get('module', 'pack'), 'slots': slots, 'route': e.get('route') or f'graft {src}',
                      'page': slot_note(slots)})
    print(f'{out}: slot {a.into} <- {src}; slots now {[s["slot"] for s in slots]}')


# --- RetroArch (Luiz's install): the .srm is the same 2 KB backup RAM ---

def ra_running():
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq retroarch.exe', '/NH'], capture_output=True, text=True)
    return 'retroarch.exe' in r.stdout.lower()


def ra_srm():
    return os.path.join(RA_SAVES, RA_GAME + '.srm')


def slots_of(name):
    e = index().get(name, {})
    return e.get('slots') or [{'slot': e.get('slot', 1), 'from': name, 'label': label(e.get('module', 0))}]


def cmd_retroarch(a):
    if not os.path.exists(RETROARCH):
        sys.exit(f'{RETROARCH} missing (RETROARCH=<path to retroarch.exe>)')
    if ra_running():
        sys.exit('retroarch.exe is running - close it first (it writes the .srm back when the content closes)')
    name = resolve(a.name)
    src, used = local(name)
    os.makedirs(RA_SAVES, exist_ok=True)
    dst = ra_srm()
    if os.path.exists(dst):
        os.makedirs(SAVES, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = os.path.join(SAVES, f'retroarch_backup_{stamp}.sav')
        shutil.copyfile(dst, bak)
        print(f'backed up the RetroArch save -> {bak}')
    shutil.copyfile(src, dst)
    print(f'copied {os.path.basename(src)} ({used} B in use) -> {dst}')
    print('in RetroArch: title > CONTINUE > CASE FILES:')
    for x in slots_of(name):
        print(f'  SNATCHER {x["slot"]}: {x["from"]} ({x["label"] or "?"})')
    if a.play:
        # the CHD must be the current build: RetroArch played a two-builds-old
        # [dev].chd on 2026-09-15 (scenes replaying, menus gone, VRAM garbage)
        img = os.path.join(ROOT, 'patched', 'pce', 'snatcher_pce.bin')
        if not os.path.exists(RA_CHD) or (os.path.exists(img) and os.path.getmtime(RA_CHD) < os.path.getmtime(img)):
            print(f'{os.path.basename(RA_CHD)} is missing or older than the image - rebuilding it')
            from pcerelease import tool
            if os.path.exists(RA_CHD):
                os.remove(RA_CHD)
            cue = os.path.join(ROOT, 'patched', 'pce', 'snatcher_pce.cue')
            r = subprocess.run([tool('chdman'), 'createcd', '-i', cue, '-o', RA_CHD])
            if r.returncode or not os.path.exists(RA_CHD):
                sys.exit('the CHD build failed (chdman createcd)')
        if not os.path.exists(RA_CORE):
            sys.exit(f'{RA_CORE} missing')
        print(f'> "{RETROARCH}" -L "{RA_CORE}" "{RA_CHD}"')
        subprocess.Popen([RETROARCH, '-L', RA_CORE, RA_CHD], cwd=RA_ROOT,
                         creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))


def cmd_retroarch_pull(a):
    src = ra_srm()
    if not os.path.exists(src):
        sys.exit(f'{src} missing')
    os.makedirs(SAVES, exist_ok=True)
    out = os.path.join(SAVES, (a.name or 'retroarch_current') + '.sav')
    shutil.copyfile(src, out)
    raw = open(out, 'rb').read()
    print(f'{out}: {len(raw)} B, header {raw[:4].decode("latin1")!r}, '
          f'{(raw[6] | raw[7] << 8) - 0x8000} B in use')


def cmd_list(a):
    ix = index()
    files = sorted(f for f in os.listdir(SAVES) if f.endswith('.sav')) if os.path.isdir(SAVES) else []
    if not files:
        sys.exit(f'no saves yet in {SAVES} - run the harness with --bram (or PCESAVE=1)')
    print(f'{"name":<18} {"module":>6} {"act":>3} {"slot":>4} {"used":>5} {"frame":>7}  route / page')
    for f in files:
        name = f[:-4]
        e = ix.get(name, {})
        if name.startswith('mister_backup'):
            e = {**e, 'route': 'MiSTer backup'}
        elif name.startswith('retroarch_backup'):
            e = {**e, 'route': 'RetroArch backup'}
        if e.get('slots'):
            e = {**e, 'slot': ','.join(str(x['slot']) for x in e['slots']), 'module': 'pack'}
        print(f'{name:<18} {str(e.get("module", "?")):>6} {str(e.get("act", "-")):>3} '
              f'{str(e.get("slot", "-")):>4} {str(e.get("used", "-")):>5} {str(e.get("frame", "-")):>7}  '
              f'{e.get("route") or "-"} | {(e.get("page") or "")[:40]}')


def cmd_remote(a):
    print(ssh('echo "== images"; find %s -maxdepth 2 -iname "*.chd" 2>/dev/null; '
              'echo "== saves"; ls -la "%s" 2>/dev/null; true' % (' '.join(GAMEDIRS), RSAVES),
              capture=True))
    print(f'save name in use: {remote_game()}.sav')


def local(name):
    p = os.path.join(SAVES, name if name.endswith('.sav') else name + '.sav')
    if not os.path.exists(p):
        sys.exit(f'{p} missing (pce_saves.py list)')
    raw = open(p, 'rb').read()
    if len(raw) != 2048 or raw[:4] != b'HUBM':
        sys.exit(f'{p}: {len(raw)} bytes, header {raw[:4]!r} - not a PCE backup RAM')
    used = (raw[6] | raw[7] << 8) - 0x8000
    if used <= 0x10:
        sys.exit(f'{p}: the backup RAM is empty (no save in it)')
    return p, used


def backup(game, tag='backup'):
    """The MiSTer's current save, into work/pce/saves/mister_<tag>_<stamp>.sav."""
    os.makedirs(SAVES, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out = os.path.join(SAVES, f'mister_{tag}_{stamp}.sav')
    r = run(['scp', *SSH_OPTS, f'{HOST}:{RSAVES}/{game}.sav', out])
    if r.returncode:
        print(f'(no save on the MiSTer yet for {game!r} - nothing to back up)')
        return None
    print(f'backed up the MiSTer save -> {out}')
    return out


def cmd_push(a):
    src, used = local(resolve(a.name))
    game = a.game or remote_game()
    e = index().get(os.path.basename(src)[:-4], {})
    backup(game)
    if run(['ssh', *SSH_OPTS, HOST, f'mkdir -p "{RSAVES}"']).returncode:
        sys.exit('mkdir on the MiSTer failed')
    if run(['scp', *SSH_OPTS, src, f'{HOST}:{RSAVES}/{game}.sav']).returncode:
        sys.exit('scp failed')
    ssh(f'sync; ls -la "{RSAVES}/{game}.sav"')
    print(f'pushed {os.path.basename(src)} ({used} B in use, module {e.get("module", "?")}, '
          f'slot {e.get("slot", "?")}) -> {HOST}:{RSAVES}/{game}.sav')
    print('on the MiSTer: load the game (reload it if it was already running), '
          'then title > CONTINUE > CASE FILES:')
    for x in e.get('slots') or [{'slot': e.get('slot', 1), 'from': os.path.basename(src)[:-4],
                                 'label': label(e.get('module', 0))}]:
        print(f'  SNATCHER {x["slot"]}: {x["from"]} ({x["label"] or "?"})')


def cmd_pull(a):
    game = a.game or remote_game()
    os.makedirs(SAVES, exist_ok=True)
    out = os.path.join(SAVES, (a.name or 'mister_current') + '.sav')
    if run(['scp', *SSH_OPTS, f'{HOST}:{RSAVES}/{game}.sav', out]).returncode:
        sys.exit('scp failed')
    raw = open(out, 'rb').read()
    print(f'{out}: {len(raw)} B, header {raw[:4].decode("latin1")!r}, '
          f'{(raw[6] | raw[7] << 8) - 0x8000} B in use')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list').set_defaults(fn=cmd_list)
    sub.add_parser('scenes').set_defaults(fn=cmd_scenes)
    sub.add_parser('remote').set_defaults(fn=cmd_remote)
    p = sub.add_parser('pack'); p.add_argument('name'); p.add_argument('saves', nargs='+')
    p.set_defaults(fn=cmd_pack)
    p = sub.add_parser('graft'); p.add_argument('name'); p.add_argument('--into', type=int, required=True)
    p.add_argument('--slot', type=int, help='which slot of the source file (if it holds several)')
    p.add_argument('--to', help='the target file (default: the source itself)')
    p.set_defaults(fn=cmd_graft)
    p = sub.add_parser('push'); p.add_argument('name'); p.add_argument('--game')
    p.set_defaults(fn=cmd_push)
    p = sub.add_parser('pull'); p.add_argument('name', nargs='?'); p.add_argument('--game')
    p.set_defaults(fn=cmd_pull)
    p = sub.add_parser('retroarch'); p.add_argument('name')
    p.add_argument('--play', action='store_true', help='start RetroArch on the [dev] CHD afterwards')
    p.set_defaults(fn=cmd_retroarch)
    p = sub.add_parser('retroarch-pull'); p.add_argument('name', nargs='?')
    p.set_defaults(fn=cmd_retroarch_pull)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
