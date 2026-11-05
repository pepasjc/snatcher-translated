# -*- coding: utf-8 -*-
"""Saturn backup-RAM library: a named save per checkpoint, pushed to the
MiSTer or into Luiz's RetroArch (the PS1's ps1/harness/mcard.py for the Saturn).

  python saturn/harness/satsave.py list
  python saturn/harness/satsave.py scenes                     # a save per bank, or why none
  python saturn/harness/satsave.py show NAME                  # the files inside one image
  python saturn/harness/satsave.py add NAME --bkr FILE        # a 32 KB .bkr / 64 KB .sav/.srm in
  python saturn/harness/satsave.py add NAME --state B020_auto # a bookmark's backup RAM in
  python saturn/harness/satsave.py use NAME                   # -> work/emu/<image>.bkr for a headless boot
  python saturn/harness/satsave.py inject NAME --state S --as S2   # into a bookmark's BackupRAM
  python saturn/harness/satsave.py check NAME                 # boot headless, CONTINUE, is the bank right?
  python saturn/harness/satsave.py remote                     # the MiSTer's Saturn images and saves
  python saturn/harness/satsave.py push NAME                  # onto the MiSTer (its file backed up first)
  python saturn/harness/satsave.py pull [name]                # the MiSTer's save back here
  python saturn/harness/satsave.py ra NAME                    # into Luiz's RetroArch, and run the game

Images live in work/saturn/saves/<name>.bkr with an index.json beside them -
game data, gitignored; only this tool is committed. The harness mints them:
a route step {"bsave": "name"} (satplay.py) saves through the game's own
Use Metal Gear > Save and files the backup RAM here; mint_saves.py does it
per bank from the bookmarks.

FORMATS (2026-09-15, measured, not assumed):

  * The Saturn's internal backup RAM is 32 KiB of 64-byte blocks: block 0 is
    'BackUpRam Format' x 4, a file starts with a header block {0x80, 0 x 3,
    name[11] + 0, comment[10], u32 date (minutes since 1980-01-01, BE),
    u32 size, u16 block list...} - Grandia's GRANDIA_001 at block 2, dated
    0x016B1E39 = 2025-03, blocks 3.. (parse_dir). A file NAME here is that
    32 KiB, plain: Beetle Saturn's own .bkr.
  * Beetle Saturn (mednafen_saturn_libretro.dll, the harness's Jan 2025 build
    and Luiz's Jan 2023 one alike) exposes NO save RAM to the frontend
    (retro_get_memory_size(0) == 0): it loads <savedir>/<content stem>.bkr
    itself at retro_load_game and writes it (+ a 12-byte .smpc) at unload.
    Headless, the save dir is work/emu (lib/emurun.py's ENV_GET_SAVE_DIRECTORY),
    so `use NAME` puts work/emu/<image stem>.bkr there before a boot. A
    Beetle savestate carries the live RAM as MAIN/BackupRAM (32,768 B, plain,
    not halfword-swapped like the WRAMs): satmem.state_ram(blob, "BackupRAM",
    swap=False) reads it from a bookmark, `inject` writes it into one.
  * The MiSTer Saturn core (Saturn_20251003.rbf) keeps
    /media/fat/saves/Saturn/<CHD basename>.sav, 65,536 B: the SH-2 bus view
    of the RAM - every data byte at an odd address behind a 0xFF (Grandia's
    'ff42 ff61 ff63 ff6b' = 'Back'). to_sav/from_sav convert. The name is the
    CHD's: `Snatcher (Japan) [Dev]` (capital D) is the folder Luiz made;
    `remote` lists what is there, MISTER_SAVE overrides.
  * Yabause / YabaSanshiro / Kronos in Luiz's RetroArch expose it through the
    libretro SRAM interface, so RetroArch keeps saves/<content>.srm - the same
    65,536-byte interleaved image (his Grandia .srm from Yabause, 2025-04,
    byte for byte the MiSTer's layout). `ra NAME` writes .bkr (plain) for
    Beetle Saturn or .srm (interleaved) for the others, by the --core stem.
"""
import argparse, glob, gzip, hashlib, json, os, shutil, struct, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib')); import devpaths

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'work')
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools', 'saturn/tools', 'saturn/harness', 'saturn/subs')]
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STORE = os.path.join(WORK, 'saturn', 'saves')
INDEX = os.path.join(STORE, 'index.json')
STATES = os.path.join(WORK, 'saturn', 'states')
EMU_SAVES = os.environ.get('EMU_SAVE_DIR') or os.path.join(ROOT, 'work', 'emu')   # lib/emurun.py's save directory
BKR_SIZE, SAV_SIZE, BLOCK = 32768, 65536, 64
FORMAT_MAGIC = b'BackUpRam Format' * 4

HOST = devpaths.get('MISTER_HOST', '')
RSAVES = os.environ.get('MISTER_SAT_SAVEDIR', '/media/fat/saves/Saturn')
GAMEDIRS = ['/media/usb0/Games/Saturn', '/media/fat/games/Saturn']
DEFAULT_GAME = os.environ.get('MISTER_SAT_SAVE', 'Snatcher (Japan) [Dev]')
SSH_OPTS = ['-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes']
RA = devpaths.get('SNATCHER_RA', '')
RA_CORE = os.environ.get('SNATCHER_SAT_RA_CORE', 'mednafen_saturn_libretro')
RA_CONTENT = os.environ.get('SNATCHER_SAT_RA_CONTENT', os.path.join(ROOT, 'patched', 'saturn', 'Snatcher (Japan).cue'))
PLAY_IMAGE = os.path.join(ROOT, 'patched', 'saturn', 'Snatcher (Japan).cue')
BS = chr(92)


def posix(path):
    return path.replace(BS, '/')


# ---- formats -------------------------------------------------------------------

def to_sav(bkr):
    """32 KiB plain -> the 64 KiB bus image (0xFF, byte)."""
    out = bytearray(b'\xff' * SAV_SIZE)
    out[1::2] = bkr
    return bytes(out)


def from_sav(sav):
    """The 64 KiB bus image -> 32 KiB plain (the even bytes must all be 0xFF)."""
    if any(b != 0xFF for b in sav[0::2]):
        raise ValueError('not an interleaved backup RAM image (even bytes are not all 0xFF)')
    return bytes(sav[1::2])


def read_image(path):
    """A .bkr (32 KiB) or a .sav/.srm (64 KiB) -> 32 KiB plain."""
    raw = open(path, 'rb').read()
    if len(raw) == BKR_SIZE:
        b = raw
    elif len(raw) == SAV_SIZE:
        b = from_sav(raw)
    else:
        sys.exit(f'{path}: {len(raw)} B - not a 32 KiB .bkr nor a 64 KiB .sav/.srm')
    if b[:16] != FORMAT_MAGIC[:16]:
        sys.exit(f'{path}: no BackUpRam Format header ({b[:16]!r})')
    return b


def bup_date(minutes):
    t = minutes * 60 + 315532800                # 1980-01-01 UTC
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.gmtime(t))
    except (OverflowError, ValueError, OSError):
        return f'{minutes:#x}'


def parse_dir(b):
    """The files in a 32 KiB image: [{name, comment, date, size, blocks, block}]."""
    out = []
    for blk in range(1, BKR_SIZE // BLOCK):
        h = b[blk * BLOCK:(blk + 1) * BLOCK]
        if h[0] != 0x80 or h[1:4] != b'\0\0\0':
            continue
        name = h[4:15].split(b'\0')[0]
        if not name or any(c < 0x20 or c > 0x7E for c in name):
            continue
        comment = h[16:26].split(b'\0')[0].decode('ascii', 'replace')
        date, size = struct.unpack_from('>II', h, 26)
        blocks = []
        p = 34
        while p + 2 <= BLOCK:
            n = struct.unpack_from('>H', h, p)[0]
            if n == 0:
                break
            blocks.append(n); p += 2
        out.append({'name': name.decode('ascii'), 'comment': comment, 'date': bup_date(date),
                    'size': size, 'blocks': len(blocks), 'block': blk})
    return out


def file_data(b, f):
    """A file's bytes. Every block starts with a 4-byte flag word (0x80000000
    on the header block, 0 on data blocks); the header's block list runs to
    the end of its block and CONTINUES at the start of the data blocks up
    to a 0 entry, and the file's `size` bytes follow (Snatcher's ACT 1 file:
    15 numbers in the header, 30 more in the first data block, 4,064 B)."""
    h = b[f['block'] * BLOCK:(f['block'] + 1) * BLOCK]
    blocks = [struct.unpack_from('>H', h, 34 + 2 * i)[0] for i in range(f['blocks'])]
    raw = b''.join(b[n * BLOCK + 4:(n + 1) * BLOCK] for n in blocks)
    p = 0
    if len(blocks) == (BLOCK - 34) // 2:               # the header's list was full
        more = []
        while p + 2 <= len(raw):
            n = struct.unpack_from('>H', raw, p)[0]; p += 2
            if n == 0:
                break
            more.append(n)
        raw = b''.join(b[n * BLOCK + 4:(n + 1) * BLOCK] for n in blocks + more)
    return raw[p:p + f['size']]


def file_header(b, f):
    """The raw 64-byte header block of a file (name, language byte, comment, date, size)."""
    return b[f['block'] * BLOCK:(f['block'] + 1) * BLOCK]


def pack_files(sources):
    """One 32 KiB backup RAM holding up to four files: `sources` = [(raw 32 KiB image,
    file dict from parse_dir, new name)]. The layout is what the BIOS's BUP library
    writes (read back by parse_dir/file_data): block 0 the format magic, then per
    file a header block {0x80, 0 x 3, name[11], language, comment[10], u32 date, u32
    size, u16 block list...} and its data blocks {u32 0, 60 B}; the block list
    fills the header's 15 slots and continues at the start of the data stream up to
    a 0 word, the file's bytes follow. Blocks are handed out from 1 upward, one
    file after the other (Snatcher's ACT 1 file: 4,064 B = 70 blocks + the header).
    Written for the MiSTer/RetroArch scene save, 2026-09-16: the game's four slots
    hold four SCENES, one file each - `satsave.py pack B080_auto B0B0_auto ...`."""
    if not 1 <= len(sources) <= 4:
        raise ValueError('pack wants 1-4 files')
    out = bytearray(BKR_SIZE)
    out[:BLOCK] = sources[0][0][:BLOCK]                   # the format block as the BIOS wrote it
    nxt = 2                                               # the BIOS never scans block 1 (a file there is invisible)
    head_slots = (BLOCK - 34) // 2                        # 15 block numbers fit the header
    for raw, f, name in sources:
        data = file_data(raw, f)
        hdr = bytearray(file_header(raw, f))
        n = 1
        while True:                                       # data blocks: the list's tail + the bytes
            cont = 2 * (n - head_slots) + 2 if n >= head_slots else 0
            need = -(-(cont + len(data)) // (BLOCK - 4))
            if need == n:
                break
            n = need
        hblk = nxt; blocks = list(range(nxt + 1, nxt + 1 + n)); nxt += 1 + n
        if nxt > BKR_SIZE // BLOCK:
            raise ValueError('the four files do not fit 32 KiB')
        hdr[4:15] = name.encode('ascii').ljust(11, b'\0')
        hdr[34:] = b'\0' * (BLOCK - 34)
        for i, bn in enumerate(blocks[:head_slots]):
            struct.pack_into('>H', hdr, 34 + 2 * i, bn)
        stream = b''
        if n >= head_slots:
            stream = b''.join(struct.pack('>H', bn) for bn in blocks[head_slots:]) + b'\0\0'
        stream += data
        stream = stream.ljust(n * (BLOCK - 4), b'\0')
        out[hblk * BLOCK:(hblk + 1) * BLOCK] = hdr
        for i, bn in enumerate(blocks):
            out[bn * BLOCK:(bn + 1) * BLOCK] = b'\0\0\0\0' + stream[i * (BLOCK - 4):(i + 1) * (BLOCK - 4)]
    packed = bytes(out)
    got = parse_dir(packed)                               # the round trip must give the files back
    assert [g['name'] for g in got] == [nm for _, _, nm in sources], got
    for g, (raw, f, _) in zip(got, sources):
        assert file_data(packed, g) == file_data(raw, f), g['name']
    return packed


def files_sha(b):
    """One hash per file's content, so two images can be compared by file."""
    return {f['name']: hashlib.sha1(file_data(b, f)).hexdigest()[:10] for f in parse_dir(b)}


# ---- the library ----------------------------------------------------------------

def load_index():
    if os.path.exists(INDEX):
        return json.load(open(INDEX, encoding='utf-8'))
    return {'snapshots': {}}


def write_index(ix):
    os.makedirs(STORE, exist_ok=True)
    with open(INDEX, 'w', encoding='utf-8') as fh:
        json.dump(ix, fh, ensure_ascii=False, indent=1)


def snap_path(name):
    return posix(os.path.join(STORE, name + '.bkr'))


def add(name, raw, desc='', source='', extra=None):
    """A library entry from 32 KiB of backup RAM (the harness's way in); an
    existing file is kept as <name>.prev.bkr. Returns the entry."""
    if len(raw) != BKR_SIZE or raw[:16] != FORMAT_MAGIC[:16]:
        raise ValueError(f'{len(raw)} B, header {raw[:16]!r} - not a formatted 32 KiB backup RAM')
    os.makedirs(STORE, exist_ok=True)
    dst = snap_path(name)
    if os.path.exists(dst):
        os.replace(dst, snap_path(name + '.prev'))
    open(dst, 'wb').write(raw)
    ix = load_index()
    entry = {'path': dst, 'desc': desc, 'taken': time.strftime('%Y-%m-%d %H:%M'),
             'source': source, 'files': parse_dir(raw), 'sha': files_sha(raw)}
    entry.update(extra or {})
    ix['snapshots'][name] = entry
    write_index(ix)
    return entry


def entry_of(name):
    ix = load_index()
    s = ix['snapshots'].get(name) or sys.exit(f'no save {name!r} (satsave.py list)')
    if not os.path.exists(s['path']):
        sys.exit(f'save file missing: {s["path"]}')
    return s


def describe(s, indent='    '):
    for f in s.get('files', []):
        print(f'{indent}{f["name"]:12} {f["comment"]:10}  {f["date"]}  {f["size"]} B in {f["blocks"]} blocks')
    if not s.get('files'):
        print(f'{indent}(no file - formatted, empty)')


def cmd_add(a):
    if a.state:
        p = os.path.join(STATES, a.state + '.state.gz')
        import satmem
        raw = satmem.state_ram(gzip.decompress(open(p, 'rb').read()), 'BackupRAM', swap=False)
        src = posix(p)
    elif a.bkr:
        raw = read_image(a.bkr); src = posix(a.bkr)
    else:
        sys.exit('add wants --bkr FILE or --state NAME')
    ix = load_index()
    if a.name in ix['snapshots'] and not a.force:
        sys.exit(f'{a.name} exists - pass --force to overwrite')
    extra = {}
    if a.bank:
        extra['bank'] = a.bank.upper()
    e = add(a.name, raw, desc=a.desc or '', source=src, extra=extra)
    print(f'{a.name}: {len(e["files"])} file(s) -> {e["path"]}')
    describe(e)


def cmd_pack(a):
    """Up to four library saves into one image, slot k = the k-th name (its file
    renamed SNATCHER_0k), added as a new entry with `slots` = {k: source name}."""
    sources = []
    for k, nm in enumerate(a.names, 1):
        s = entry_of(nm)
        raw = read_image(s['path'])
        fs = parse_dir(raw)
        if not fs:
            sys.exit(f'{nm}: no file in that backup RAM')
        sources.append((raw, fs[0], f'SNATCHER_{k:02d}'))
    packed = pack_files(sources)
    ix = load_index()
    if a.as_name in ix['snapshots'] and not a.force:
        sys.exit(f'{a.as_name} exists - pass --force to overwrite')
    slots = {str(k): nm for k, nm in enumerate(a.names, 1)}
    banks = {str(k): ix['snapshots'][nm].get('bank') for k, nm in enumerate(a.names, 1)}
    e = add(a.as_name, packed, desc='pack: ' + ' '.join(a.names), source='pack',
            extra={'slots': slots, 'slot_banks': banks, 'bank': banks.get('1')})
    print(f'{a.as_name}: {len(e["files"])} file(s) -> {e["path"]}')
    describe(e)
    print('check each slot: ' + '; '.join(f'satsave_check.py {a.as_name} --slot {k}' for k in slots))


def cmd_list(a):
    ix = load_index()
    if not ix['snapshots']:
        print('library empty'); return
    for nm, s in sorted(ix['snapshots'].items()):
        ok = 'ok' if os.path.exists(s['path']) else 'MISSING'
        where = f"  [{s['bank']} f{s.get('frame', '?')} saved={s.get('saved')}]" if s.get('bank') else ''
        print(f'{nm}  [{ok}]  {s["taken"]}  {s["desc"]}{where}')
        describe(s)


def cmd_show(a):
    s = entry_of(a.name)
    b = read_image(s['path'])
    print(s['path'])
    describe({'files': parse_dir(b)}, '  ')
    print('  sha per file:', files_sha(b))


# banks the game offers no Save in (no Use Metal Gear on the verb menu) - the
# PS1's list, the same script: reach the scene from its neighbour's save
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
    labels = scene_labels()
    ix = load_index()['snapshots']
    banks = sorted(set(labels) | {'B%03X' % (i * 0x10) for i in range(39)} | {s['bank'] for s in ix.values() if s.get('bank')})
    have = 0
    for b in banks:
        saves = sorted((n, s) for n, s in ix.items() if s.get('bank') == b and s.get('saved'))
        label = labels.get(b, '')
        if saves:
            n, s = saves[0]; have += 1
            more = f' (+{len(saves) - 1})' if len(saves) > 1 else ''
            print(f'{b}  {label:36} save {n}{more}  {s["taken"]}')
        elif b in NO_SAVE:
            print(f'{b}  {label:36} -    no Save here: {NO_SAVE[b]}')
        else:
            print(f'{b}  {label:36} -    not minted yet (mint_saves.py {b})')
    print(f'{have} of {len(banks)} banks have a save; satsave.py push NAME puts one on the MiSTer')


# ---- headless -------------------------------------------------------------------

def image_stem(cue):
    return os.path.splitext(os.path.basename(cue))[0]


def cmd_use(a):
    """The save into work/emu/<image stem>.bkr: Beetle Saturn reads it at
    retro_load_game, so the next headless boot of that image has it."""
    s = entry_of(a.name)
    os.makedirs(EMU_SAVES, exist_ok=True)
    dst = os.path.join(EMU_SAVES, image_stem(a.image) + '.bkr')
    shutil.copy2(s['path'], dst)
    print(f'{a.name} -> {dst} (read by the next headless boot of {a.image})')


def inject_state(blob, raw):
    """A savestate blob with its MAIN/BackupRAM replaced (same size, in place)."""
    off = 32
    while off + 36 <= len(blob):
        name = blob[off:off + 32].split(b'\0')[0]
        size = struct.unpack_from('<I', blob, off + 32)[0]
        if name == b'MAIN':
            p, end = off + 36, off + 36 + size
            while p < end:
                nl = blob[p]; nm = blob[p + 1:p + 1 + nl]
                vs = struct.unpack_from('<I', blob, p + 1 + nl)[0]
                p += 1 + nl + 4
                if nm == b'BackupRAM':
                    if vs != len(raw):
                        raise ValueError(f'state BackupRAM is {vs} B')
                    return blob[:p] + raw + blob[p + vs:]
                p += vs
        off += 36 + size
    raise ValueError('no MAIN/BackupRAM in the state')


def cmd_inject(a):
    s = entry_of(a.name)
    raw = read_image(s['path'])
    src = os.path.join(STATES, a.state + '.state.gz')
    dst = os.path.join(STATES, (a.as_name or a.state) + '.state.gz')
    blob = inject_state(gzip.decompress(open(src, 'rb').read()), raw)
    if os.path.exists(dst) and dst != src:
        os.replace(dst, dst[:-9] + '.prev.state.gz')
    open(dst, 'wb').write(gzip.compress(blob))
    side = src[:-9] + '.json'
    if os.path.exists(side) and dst != src:
        shutil.copy2(side, dst[:-9] + '.json')
    print(f'{a.name} -> {dst} (BackupRAM replaced)')


def cmd_check(a):
    """Boot the image headless with the save in place, take CONTINUE on the
    title and report which bank loads (satsave_check.py does the driving)."""
    s = entry_of(a.name)
    cmd = [sys.executable, os.path.join(HERE, 'satsave_check.py'), a.name, '--image', a.image,
           '--frames', str(a.frames)]
    if a.out:
        cmd += ['--out', a.out]
    r = subprocess.run(cmd, cwd=ROOT)
    sys.exit(r.returncode)


# ---- the MiSTer -------------------------------------------------------------------

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
    """The MiSTer's image name for our CHD (the save file is <that>.sav)."""
    if os.environ.get('MISTER_SAT_SAVE'):
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
        print(f'several Snatcher images on the MiSTer: {snat}; using MISTER_SAT_SAVE={DEFAULT_GAME}')
    return DEFAULT_GAME


def cmd_remote(a):
    print(ssh('echo "== images"; find %s -maxdepth 2 -iname "*snatcher*.chd" 2>/dev/null; '
              'echo "== saves"; ls -la "%s" 2>/dev/null; true'
              % (' '.join(f'"{d}"' for d in GAMEDIRS), RSAVES), capture=True))
    print(f'save in use: {RSAVES}/{remote_game()}.sav')


def backup_remote(game, tag='backup'):
    os.makedirs(STORE, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = posix(os.path.join(STORE, f'mister_{tag}_{stamp}.sav'))
    r = run(['scp', *SSH_OPTS, f'{HOST}:{RSAVES}/{game}.sav', out])
    if r.returncode:
        print(f'(no save on the MiSTer yet for {game!r} - nothing to back up)')
        return None
    print(f'backed up the MiSTer save -> {out}')
    return out


def cmd_push(a):
    s = entry_of(a.name)
    raw = read_image(s['path'])
    if not parse_dir(raw):
        sys.exit(f'{a.name}: no file in that backup RAM')
    game = a.game or remote_game()
    tmp = posix(os.path.join(STORE, a.name + '.push.sav'))
    if a.dry_run:
        print(f'dry run: would back up {HOST}:{RSAVES}/{game}.sav and copy {a.name} over it as the 64 KiB image')
        return
    open(tmp, 'wb').write(to_sav(raw))
    backup_remote(game)
    if run(['ssh', *SSH_OPTS, HOST, f'mkdir -p "{RSAVES}"']).returncode:
        sys.exit('mkdir on the MiSTer failed')
    # scp runs over SFTP (OpenSSH 9+): the remote path is taken literally, no shell quotes
    if run(['scp', *SSH_OPTS, tmp, f'{HOST}:{RSAVES}/{game}.sav']).returncode:
        sys.exit('scp failed')
    os.remove(tmp)
    ssh(f'sync; ls -la "{RSAVES}/{game}.sav"')
    print(f'pushed {a.name} -> {HOST}:{RSAVES}/{game}.sav')
    describe(s, '  ')
    print('on the MiSTer: load the game (reload it if it was already running), then CONTINUE on the title')


def cmd_pull(a):
    game = a.game or remote_game()
    name = a.name or 'mister_current'
    os.makedirs(STORE, exist_ok=True)
    tmp = posix(os.path.join(STORE, name + '.pull.sav'))
    if run(['scp', *SSH_OPTS, f'{HOST}:{RSAVES}/{game}.sav', tmp]).returncode:
        sys.exit('scp failed')
    raw = read_image(tmp)
    os.remove(tmp)
    e = add(name, raw, desc=f'pulled from the MiSTer ({game})', source=f'{HOST}:{RSAVES}/{game}.sav')
    print(f'{e["path"]}: {len(e["files"])} file(s)')
    describe(e)


# ---- RetroArch ----------------------------------------------------------------------

def ra_running():
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq retroarch.exe'], capture_output=True, text=True)
    return 'retroarch.exe' in r.stdout.lower()


def cmd_ra(a):
    s = entry_of(a.name)
    raw = read_image(s['path'])
    if not parse_dir(raw):
        sys.exit(f'{a.name}: no file in that backup RAM')
    exe = os.path.join(RA, 'retroarch.exe')
    if not os.path.exists(exe):
        sys.exit(f'{exe} missing (SNATCHER_RA)')
    core_stem = a.core or RA_CORE
    core = os.path.join(RA, 'cores', core_stem + '.dll')
    if not os.path.exists(core):
        sys.exit(f'{core} missing - no such Saturn core in {RA}')
    content = a.content or RA_CONTENT
    if not os.path.exists(content):
        sys.exit(f'{content} missing - build first')
    if ra_running():
        sys.exit('retroarch.exe is running - close it first (it writes the save back on exit)')
    stem = os.path.splitext(os.path.basename(content))[0]
    beetle = 'mednafen' in core_stem or 'beetle' in core_stem
    dst = os.path.join(RA, 'saves', stem + ('.bkr' if beetle else '.srm'))
    data = raw if beetle else to_sav(raw)
    if a.dry_run:
        print(f'dry run: would back up {dst} (exists: {os.path.exists(dst)}) and write {len(data)} B there, '
              f'then run {exe} -L {core} "{content}"')
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        b = posix(os.path.join(STORE, f'ra_backup_{stamp}{os.path.splitext(dst)[1]}'))
        shutil.copy2(dst, b)
        print(f'backed up the RetroArch save -> {b}')
    open(dst, 'wb').write(data)
    print(f'{a.name} -> {dst} ({"plain 32 KiB, Beetle Saturn" if beetle else "interleaved 64 KiB, SRAM interface"})')
    describe(s, '  ')
    print('in the game: CONTINUE on the title')
    if a.no_run:
        return
    cmd = [exe, '-L', core, content]
    print('>', ' '.join(f'"{c}"' if ' ' in c else c for c in cmd))
    subprocess.Popen(cmd, cwd=RA)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('add'); s.set_defaults(fn=cmd_add)
    s.add_argument('name'); s.add_argument('--bkr', help='a .bkr (32 KiB) or .sav/.srm (64 KiB)')
    s.add_argument('--state', help='a bookmark in work/saturn/states')
    s.add_argument('--desc'); s.add_argument('--bank'); s.add_argument('--force', action='store_true')
    s = sub.add_parser('list'); s.set_defaults(fn=cmd_list)
    s = sub.add_parser('show'); s.set_defaults(fn=cmd_show); s.add_argument('name')
    s = sub.add_parser('scenes'); s.set_defaults(fn=cmd_scenes)
    s = sub.add_parser('pack'); s.set_defaults(fn=cmd_pack); s.add_argument('names', nargs='+')
    s.add_argument('--as', dest='as_name', default='scenes'); s.add_argument('--force', action='store_true')
    s = sub.add_parser('use'); s.set_defaults(fn=cmd_use); s.add_argument('name')
    s.add_argument('--image', default=PLAY_IMAGE)
    s = sub.add_parser('inject'); s.set_defaults(fn=cmd_inject); s.add_argument('name')
    s.add_argument('--state', required=True); s.add_argument('--as', dest='as_name')
    s = sub.add_parser('check'); s.set_defaults(fn=cmd_check); s.add_argument('name')
    s.add_argument('--image', default=PLAY_IMAGE); s.add_argument('--frames', type=int, default=40000)
    s.add_argument('--out')
    s = sub.add_parser('remote'); s.set_defaults(fn=cmd_remote)
    s = sub.add_parser('push'); s.set_defaults(fn=cmd_push); s.add_argument('name')
    s.add_argument('--game', help='the MiSTer image name (default: found over ssh)')
    s.add_argument('--dry-run', action='store_true')
    s = sub.add_parser('pull'); s.set_defaults(fn=cmd_pull); s.add_argument('name', nargs='?'); s.add_argument('--game')
    s = sub.add_parser('ra'); s.set_defaults(fn=cmd_ra); s.add_argument('name')
    s.add_argument('--no-run', action='store_true'); s.add_argument('--core', help='core dll stem (default mednafen_saturn_libretro)')
    s.add_argument('--content', help='the cue/chd to run (default patched/saturn/Snatcher (Japan).cue)')
    s.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
