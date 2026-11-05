# -*- coding: utf-8 -*-
"""Memory-card library: keep a named snapshot per checkpoint and swap them in.

  python ps1/harness/mcard.py scan
  python ps1/harness/mcard.py add act1 --desc "Act 1" --save "1:B020 act 1 end"
  python ps1/harness/mcard.py list
  python ps1/harness/mcard.py find b080
  python ps1/harness/mcard.py scenes                       # a card per bank, or why none
  python ps1/harness/mcard.py use act1
  python ps1/harness/mcard.py graft act1 3 --into 2        # one save between cards
  python ps1/harness/mcard.py remote                       # the MiSTer's PSX images and cards
  python ps1/harness/mcard.py push B0C0_auto               # that card onto the MiSTer
  python ps1/harness/mcard.py pull [name]                  # the MiSTer's card back here
  python ps1/harness/mcard.py ra B0C0_auto                 # that card into RetroArch, and run the game

Snapshots live in work/saves/ with an index.json beside them - game data, so
gitignored like the disc images; only this tool is committed. The headless
harness mints them too: `scripted.py --mcard` (MCSAVE=1) saves through the
game's own Use Metal Gear > Save at the first verb menu of every bank it
passes and adds `<bank>_auto` here; a route's {"mcard": "name"} step saves
where it stands. `push` puts one on the MiSTer for hardware testing.

Card layout, measured from Luiz's card rather than assumed:

  the card is a raw 128 KiB image, 16 frames of 128 B then 15 blocks of 8 KiB.
  Snatcher uses ONE block (directory entry BISLPS-00154SNATCHER, block 1) and
  packs its four in-game saves inside it:

      block + 0x200 + n * 0x780,  n = 0..3

  Each save is stored twice, as two identical 0x3C0 halves, and the four
  together fill the block exactly (0x200 + 4 * 0x780 = 0x2000). The mirror is
  copied along with the save, so a graft needs no checksum fixing.

MiSTer (2026-09-14): the PSX core keeps memory card 1 as
/media/fat/saves/PSX/<image name>.sav - the same raw 131,072 bytes as a
DuckStation .mcd ('MC' signature, Snatcher's block at 0x2000), so a card is
copied over as it is. The name is the loaded CHD's basename (`remote` lists
them; MISTER_SAVE overrides). The core reads the file when the game is
loaded and writes it back on its own schedule: push with the game not
running (or reload it after), and every push backs the MiSTer's current
card up to work/saves/mister_backup_<stamp>.mcd first.

RetroArch (2026-09-15): a RetroArch install named by SNATCHER_RA (lib/devpaths.py;
NOT the shared one the harness drives), Beetle PSX HW, the content being
patched/Snatcher (Japan).cue; with `use_mednafen_memcard0_method = libretro`
card 1 is saves/<content name>.srm - again the raw 128 KiB. `ra NAME` backs
that up to work/saves/ra_backup_<stamp>.mcd, copies ours in and launches
RetroArch on the cue (`--no-run` to only copy; `--core` another core dll
stem). RetroArch writes the .srm back on close, so it must not be running
the game while the copy happens - the tool refuses while retroarch.exe runs.
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BS = chr(92)
LIVE = devpaths.get('SNATCHER_CARD', '')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
STORE = os.path.join(ROOT, 'work', 'saves')
INDEX = os.path.join(STORE, 'index.json')

CARD_SIZE = 131072
BLOCK = 8192                  # Snatcher's block 1
SAVE_BASE, SAVE_SIZE, HALF = 0x200, 0x780, 0x3C0
NSAVES = 4

HOST = devpaths.get('MISTER_HOST', '')
RSAVES = os.environ.get('MISTER_SAVEDIR', '/media/fat/saves/PSX')
GAMEDIRS = ['/media/usb0/Games/PSX', '/media/fat/games/PSX']
DEFAULT_GAME = os.environ.get('MISTER_SAVE', 'Snatcher (Japan) [dev]')
SSH_OPTS = ['-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes']
RA = devpaths.get('SNATCHER_RA', '')
RA_CORE = os.environ.get('SNATCHER_RA_CORE', 'mednafen_psx_hw_libretro')
RA_CONTENT = os.environ.get('SNATCHER_RA_CONTENT', os.path.join(ROOT, 'patched', 'Snatcher (Japan).cue'))


def posix(path):
    return path.replace(BS, '/')


def read_card(path):
    raw = open(path, 'rb').read()
    if len(raw) != CARD_SIZE:
        sys.exit(f'{path}: {len(raw)}B, not a raw {CARD_SIZE}B memory card')
    if raw[:2] != b'MC':
        sys.exit(f'{path}: missing MC signature')
    return bytearray(raw)


def save_span(n):
    at = BLOCK + SAVE_BASE + n * SAVE_SIZE
    return at, at + SAVE_SIZE


def saves_of(raw):
    """[(used, sha1)] for the four in-game saves."""
    out = []
    for n in range(NSAVES):
        a, b = save_span(n)
        s = bytes(raw[a:b])
        out.append((bool(s.strip(b'\0')), hashlib.sha1(s).hexdigest()[:10]))
    return out


def load_index():
    if os.path.exists(INDEX):
        return json.load(open(INDEX, encoding='utf-8'))
    return {'card': LIVE, 'snapshots': {}}


def write_index(ix):
    os.makedirs(STORE, exist_ok=True)
    with open(INDEX, 'w', encoding='utf-8') as fh:
        json.dump(ix, fh, ensure_ascii=False, indent=1)


def snap_path(name):
    return posix(os.path.join(STORE, name + '.mcd'))


def parse_saves(pairs):
    out = {}
    for p in pairs or []:
        if ':' not in p:
            sys.exit(f'--save wants N:text, got {p!r}')
        n, text = p.split(':', 1)
        if not n.strip().isdigit() or not 1 <= int(n) <= NSAVES:
            sys.exit(f'--save slot must be 1..{NSAVES}, got {n!r}')
        out[n.strip()] = text.strip()
    return out


def add_card(name, raw, desc='', labels=None, source='', extra=None):
    """A library entry from card bytes (the harness's way in): the card goes
    to work/saves/<name>.mcd, an existing file is kept as <name>.prev.mcd.
    Returns the index entry."""
    if len(raw) != CARD_SIZE or raw[:2] != b'MC':
        raise ValueError(f'{len(raw)}B, header {raw[:2]!r} - not a raw memory card')
    os.makedirs(STORE, exist_ok=True)
    dst = snap_path(name)
    if os.path.exists(dst):
        os.replace(dst, snap_path(name + '.prev'))
    open(dst, 'wb').write(raw)
    ix = load_index()
    entry = {'path': dst, 'desc': desc, 'taken': time.strftime('%Y-%m-%d %H:%M'),
             'source': source, 'saves': {}}
    entry.update(extra or {})
    for n, (used, sha) in enumerate(saves_of(bytearray(raw)), 1):
        if used:
            entry['saves'][str(n)] = {'sha1': sha, 'label': (labels or {}).get(str(n), '')}
    ix['snapshots'][name] = entry
    write_index(ix)
    return entry


def cmd_scan(a):
    path = a.card or LIVE
    raw = read_card(path)
    print(path)
    ix = load_index()
    known = {}
    for nm, s in ix['snapshots'].items():
        for slot, meta in s['saves'].items():
            known.setdefault(meta['sha1'], []).append(f'{nm}:{slot}')
    for n, (used, sha) in enumerate(saves_of(raw), 1):
        seen = ', '.join(known.get(sha, [])) or ('-' if used else '')
        print(f'  save {n}: {"used  " if used else "EMPTY "} {sha}  {seen}')


def cmd_add(a):
    raw = read_card(a.card or LIVE)
    labels = parse_saves(a.save)
    ix = load_index()
    if a.name in ix['snapshots'] and not a.force:
        sys.exit(f'{a.name} exists - pass --force to overwrite')
    os.makedirs(STORE, exist_ok=True)
    dst = snap_path(a.name)
    shutil.copy2(a.card or LIVE, dst)
    entry = {'path': dst, 'desc': a.desc or '',
             'taken': time.strftime('%Y-%m-%d %H:%M'),
             'source': posix(a.card or LIVE), 'saves': {}}
    for n, (used, sha) in enumerate(saves_of(raw), 1):
        if used:
            entry['saves'][str(n)] = {'sha1': sha,
                                      'label': labels.get(str(n), '')}
    unknown = set(labels) - set(entry['saves'])
    if unknown:
        print(f'  warning: labelled empty slot(s) {sorted(unknown)}')
    ix['snapshots'][a.name] = entry
    write_index(ix)
    print(f'{a.name}: {len(entry["saves"])} save(s) -> {dst}')
    for n, m in sorted(entry['saves'].items()):
        print(f'  save {n}: {m["label"] or "(unlabelled)"}')


def cmd_label(a):
    ix = load_index()
    s = ix['snapshots'].get(a.name) or sys.exit(f'no snapshot {a.name}')
    m = s['saves'].get(str(a.slot)) or sys.exit(
        f'{a.name} has no save in slot {a.slot}')
    m['label'] = a.text
    write_index(ix)
    print(f'{a.name} save {a.slot}: {a.text}')


def cmd_list(a):
    ix = load_index()
    if not ix['snapshots']:
        print('library empty')
        return
    for nm, s in sorted(ix['snapshots'].items()):
        ok = 'ok' if os.path.exists(s['path']) else 'MISSING'
        where = f"  [{s['bank']} {s.get('route') or ''} f{s.get('frame', '?')}]" if s.get('bank') else ''
        print(f'{nm}  [{ok}]  {s["taken"]}  {s["desc"]}{where}')
        for n, m in sorted(s['saves'].items()):
            print(f'    save {n}: {m["label"] or "(unlabelled)"}   {m["sha1"]}')


# banks the game offers no Save in (the menu has no Use Metal Gear / Save):
# a card cannot be minted there, and the scene is reached from its neighbour
NO_SAVE = {
    'B000': 'title screen', 'B010': 'HQ tour, Metal Gear not yet with Gillian',
    'B030': "Gaudi's terminal (from HQ)", 'B040': 'Gaudi name search (from HQ)',
    'B050': 'the save menu itself', 'B060': 'videophone (from a room)',
    'B070': 'videophone (from a room)', 'B090': 'dummy bank', 'B0A0': 'tricycle ride',
    'B130': "Freddy's part 2 (mid-scene)", 'B140': 'Act 2 recap (plays on load of B150)',
    'B170': 'tricycle ride', 'B180': 'phone book', 'B1F0': 'cockpit ride',
    'B210': 'face reconstruction (Restore, mid-basement)', 'B240': 'quiz screen',
    'B260': 'countdown / ending',
}


def scene_labels():
    p = os.path.join(ROOT, 'ps1', 'review', 'scenes.json')
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def cmd_scenes(a):
    """One line per bank: its card (name, bookmark it came from, date) or why none."""
    labels = scene_labels()
    ix = load_index()['snapshots']
    banks = sorted(set(labels) | {'B260'} | {s['bank'] for s in ix.values() if s.get('bank')})
    have = 0
    for b in banks:
        cards = sorted((n, s) for n, s in ix.items() if s.get('bank') == b and s.get('saved'))
        label = labels.get(b, '')
        if cards:
            n, s = cards[0]
            have += 1
            more = f' (+{len(cards) - 1})' if len(cards) > 1 else ''
            print(f'{b}  {label:36} card {n}{more}  slot {s.get("slot", 1)}  {s["taken"]}')
        elif b in NO_SAVE:
            print(f'{b}  {label:36} -    no Save here: {NO_SAVE[b]}')
        else:
            print(f'{b}  {label:36} -    not minted yet (mint_cards.py {b})')
    print(f'{have} of {len(banks)} banks have a card; mcard.py push NAME puts one on the MiSTer')


def cmd_find(a):
    ix = load_index()
    q = a.query.lower()
    hits = 0
    for nm, s in sorted(ix['snapshots'].items()):
        for n, m in sorted(s['saves'].items()):
            if q in m['label'].lower() or q in nm.lower() or q in (s.get('desc') or '').lower():
                print(f'{nm} save {n}: {m["label"] or s.get("desc", "")}')
                hits += 1
    if not hits:
        print(f'nothing matches {a.query!r}')


def backup_live(why):
    if not os.path.exists(LIVE):
        return None
    os.makedirs(STORE, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    b = os.path.join(STORE, f'_backup_{why}_{stamp}.mcd')
    shutil.copy2(LIVE, b)
    return posix(b)


def cmd_use(a):
    ix = load_index()
    s = ix['snapshots'].get(a.name) or sys.exit(f'no snapshot {a.name}')
    if not os.path.exists(s['path']):
        sys.exit(f'snapshot file missing: {s["path"]}')
    b = backup_live('use')
    shutil.copy2(s['path'], LIVE)
    print(f'{a.name} -> {LIVE}')
    if b:
        print(f'  previous card kept at {b}')
    for n, m in sorted(s['saves'].items()):
        print(f'  save {n}: {m["label"] or "(unlabelled)"}')


def cmd_graft(a):
    """Copy one in-game save out of a snapshot into the live card."""
    ix = load_index()
    s = ix['snapshots'].get(a.name) or sys.exit(f'no snapshot {a.name}')
    src = read_card(s['path'])
    dst = read_card(LIVE)
    sa, sb = save_span(a.slot - 1)
    da, db = save_span(a.into - 1)
    blob = src[sa:sb]
    if not bytes(blob).strip(b'\0'):
        sys.exit(f'{a.name} save {a.slot} is empty')
    was_used, was_sha = saves_of(dst)[a.into - 1]
    if was_used and not a.force:
        sys.exit(f'live save {a.into} is in use ({was_sha}) - pass --force')
    b = backup_live('graft')
    dst[da:db] = blob
    open(LIVE, 'wb').write(bytes(dst))
    print(f'{a.name} save {a.slot} -> live save {a.into}')
    print(f'  previous card kept at {b}')
    print('  the save carries its own mirrored copy, so no checksum fixing is'
          ' needed - but confirm it loads in game before relying on it')


# --- the MiSTer -----------------------------------------------------------

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


def remote_game():
    """The MiSTer's image name for our CHD (the card file is <that>.sav)."""
    if os.environ.get('MISTER_SAVE'):
        return DEFAULT_GAME
    out = ssh('find %s -maxdepth 2 -iname "*.chd" 2>/dev/null; true'
              % ' '.join(f'"{d}"' for d in GAMEDIRS), capture=True)
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


def cmd_remote(a):
    print(ssh('echo "== images"; find %s -maxdepth 2 -iname "*snatcher*.chd" 2>/dev/null; '
              'echo "== cards"; ls -la "%s" 2>/dev/null | grep -i snatcher; true'
              % (' '.join(f'"{d}"' for d in GAMEDIRS), RSAVES), capture=True))
    print(f'card in use: {RSAVES}/{remote_game()}.sav')


def backup_remote(game, tag='backup'):
    """The MiSTer's current card, into work/saves/mister_<tag>_<stamp>.mcd."""
    os.makedirs(STORE, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = posix(os.path.join(STORE, f'mister_{tag}_{stamp}.mcd'))
    r = run(['scp', *SSH_OPTS, f'{HOST}:{RSAVES}/{game}.sav', out])
    if r.returncode:
        print(f'(no card on the MiSTer yet for {game!r} - nothing to back up)')
        return None
    print(f'backed up the MiSTer card -> {out}')
    return out


def cmd_push(a):
    ix = load_index()
    s = ix['snapshots'].get(a.name) or sys.exit(f'no snapshot {a.name} (mcard.py list)')
    if not os.path.exists(s['path']):
        sys.exit(f'snapshot file missing: {s["path"]}')
    raw = read_card(s['path'])
    used = [n for n, (u, _) in enumerate(saves_of(raw), 1) if u]
    if not used:
        sys.exit(f'{a.name}: no in-game save on that card')
    game = a.game or remote_game()
    backup_remote(game)
    if run(['ssh', *SSH_OPTS, HOST, f'mkdir -p "{RSAVES}"']).returncode:
        sys.exit('mkdir on the MiSTer failed')
    # scp runs over SFTP (OpenSSH 9+): the remote path is taken literally,
    # so no shell quotes - they became part of the filename
    if run(['scp', *SSH_OPTS, s['path'], f'{HOST}:{RSAVES}/{game}.sav']).returncode:
        sys.exit('scp failed')
    ssh(f'sync; ls -la "{RSAVES}/{game}.sav"')
    slot = s.get('slot') or used[0]
    print(f'pushed {a.name} -> {HOST}:{RSAVES}/{game}.sav')
    for n, m in sorted(s['saves'].items()):
        print(f'  save {n}: {m["label"] or "(unlabelled)"}')
    print('on the MiSTer: load the game (reload it if it was already running), '
          f'then LOAD > FILE.{slot}')


def cmd_pull(a):
    game = a.game or remote_game()
    name = a.name or 'mister_current'
    os.makedirs(STORE, exist_ok=True)
    tmp = posix(os.path.join(STORE, name + '.pull.mcd'))
    if run(['scp', *SSH_OPTS, f'{HOST}:{RSAVES}/{game}.sav', tmp]).returncode:
        sys.exit('scp failed')
    raw = bytes(read_card(tmp))
    os.remove(tmp)
    entry = add_card(name, raw, desc=f'pulled from the MiSTer ({game})',
                     source=f'{HOST}:{RSAVES}/{game}.sav')
    print(f'{entry["path"]}: {len(entry["saves"])} save(s) in use')
    for n, (used, sha) in enumerate(saves_of(bytearray(raw)), 1):
        print(f'  save {n}: {"used  " if used else "EMPTY "} {sha}')


# --- RetroArch ------------------------------------------------------------

def ra_running():
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq retroarch.exe'], capture_output=True, text=True)
    return 'retroarch.exe' in r.stdout.lower()


def cmd_ra(a):
    ix = load_index()
    s = ix['snapshots'].get(a.name) or sys.exit(f'no snapshot {a.name} (mcard.py list)')
    if not os.path.exists(s['path']):
        sys.exit(f'snapshot file missing: {s["path"]}')
    raw = read_card(s['path'])
    used = [n for n, (u, _) in enumerate(saves_of(raw), 1) if u]
    if not used:
        sys.exit(f'{a.name}: no in-game save on that card')
    exe = os.path.join(RA, 'retroarch.exe')
    if not os.path.exists(exe):
        sys.exit(f'{exe} missing (SNATCHER_RA)')
    content = a.content or RA_CONTENT
    if not os.path.exists(content):
        sys.exit(f'{content} missing - build first')
    if ra_running():
        sys.exit('retroarch.exe is running - close it first (it writes the card back on exit)')
    srm = os.path.join(RA, 'saves', os.path.splitext(os.path.basename(content))[0] + '.srm')
    os.makedirs(os.path.dirname(srm), exist_ok=True)
    if os.path.exists(srm):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        b = posix(os.path.join(STORE, f'ra_backup_{stamp}.mcd'))
        shutil.copy2(srm, b)
        print(f'backed up the RetroArch card -> {b}')
    shutil.copy2(s['path'], srm)
    slot = s.get('slot') or used[0]
    print(f'{a.name} -> {srm}')
    for n, m in sorted(s['saves'].items()):
        print(f'  save {n}: {m["label"] or "(unlabelled)"}')
    print(f'in the game: LOAD > FILE.{slot}')
    if a.no_run:
        return
    core = os.path.join(RA, 'cores', (a.core or RA_CORE) + '.dll')
    if not os.path.exists(core):
        sys.exit(f'{core} missing')
    cmd = [exe, '-L', core, content]
    print('>', ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
    subprocess.Popen(cmd, cwd=RA)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('scan'); s.set_defaults(fn=cmd_scan); s.add_argument('--card')
    s = sub.add_parser('add'); s.set_defaults(fn=cmd_add)
    s.add_argument('name'); s.add_argument('--desc'); s.add_argument('--card')
    s.add_argument('--save', action='append', metavar='N:TEXT')
    s.add_argument('--force', action='store_true')
    s = sub.add_parser('label'); s.set_defaults(fn=cmd_label)
    s.add_argument('name'); s.add_argument('slot', type=int); s.add_argument('text')
    s = sub.add_parser('list'); s.set_defaults(fn=cmd_list)
    s = sub.add_parser('find'); s.set_defaults(fn=cmd_find); s.add_argument('query')
    s = sub.add_parser('scenes'); s.set_defaults(fn=cmd_scenes)
    s = sub.add_parser('use'); s.set_defaults(fn=cmd_use); s.add_argument('name')
    s = sub.add_parser('graft'); s.set_defaults(fn=cmd_graft)
    s.add_argument('name'); s.add_argument('slot', type=int)
    s.add_argument('--into', type=int, required=True)
    s.add_argument('--force', action='store_true')
    s = sub.add_parser('remote'); s.set_defaults(fn=cmd_remote)
    s = sub.add_parser('push'); s.set_defaults(fn=cmd_push)
    s.add_argument('name'); s.add_argument('--game', help='the MiSTer image name (default: found over ssh)')
    s = sub.add_parser('pull'); s.set_defaults(fn=cmd_pull)
    s.add_argument('name', nargs='?'); s.add_argument('--game')
    s = sub.add_parser('ra'); s.set_defaults(fn=cmd_ra)
    s.add_argument('name'); s.add_argument('--no-run', action='store_true', help='copy the card, do not launch')
    s.add_argument('--core', help='core dll stem (default mednafen_psx_hw_libretro)')
    s.add_argument('--content', help='the cue to run (default patched/Snatcher (Japan).cue)')

    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
