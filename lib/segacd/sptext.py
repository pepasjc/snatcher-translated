# -*- coding: utf-8 -*-
"""Extract the Sega CD Snatcher script (SP00..SP38.BIN) straight off the
US disc's data track, with its line breaks and colour codes kept.

    python lib/segacd/sptext.py            -> work/segacd/sp_text.json
    python lib/segacd/sptext.py SP06       -> print that file's strings

The community HTML dump (reference/segacd_script/) concatenates the line
breaks away ("enoughmemory"); the files themselves carry them: strings
are 0xFF-terminated, 0xF2 is a line break, 0xFB opens a highlighted span
and 0xF9 closes it, the other 0xF0-0xFE bytes are engine codes (kept as
<xx>). Each file's text region begins where the HTML dump's first offset
says it does (the dump's offsets are file offsets - 'Welcome to Junker'
sits at 0x3B20 of SP06.BIN in both).

Output: {"SP06": [{"off": int, "text": str}, ...], ...}; text uses the
PS1 conventions so the two scripts compare directly: `￥` for the line
break, `＠黄`/`＠白` for the highlight on/off.

Sega CD text is source material - work/ only, never committed.
"""
import glob, json, os, re, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

TRACK1 = os.path.join(ROOT, "discs/iso_segacd_us", "Snatcher (USA) (Track 01).bin")
DUMP = os.path.join(ROOT, "reference/segacd_script")
OUT = os.path.join(WORK, "segacd", "sp_text.json")

BREAK, HI_ON, HI_OFF, END = 0xF2, 0xFB, 0xF9, 0xFF


def iso_files(path=TRACK1):
    """{name: (lba, size)} of the MODE1/2352 track's ISO9660 root."""
    f = open(path, 'rb')

    def sec(n):
        f.seek(n * 2352)
        return f.read(2352)[16:16 + 2048]
    pvd = sec(16)
    assert pvd[1:6] == b'CD001', 'not an ISO9660 track'
    ext, size = struct.unpack('<I', pvd[158:162])[0], struct.unpack('<I', pvd[166:170])[0]
    data = b''.join(sec(ext + i) for i in range((size + 2047) // 2048))
    out, i = {}, 0
    while i < len(data):
        L = data[i]
        if L == 0:
            i = (i // 2048 + 1) * 2048
            continue
        r = data[i:i + L]
        name = r[33:33 + r[32]].decode('latin1').split(';')[0]
        if name not in ('\x00', '\x01'):
            out[name] = (struct.unpack('<I', r[2:6])[0], struct.unpack('<I', r[10:14])[0])
        i += L
    return out


def read_file(name, files=None, path=TRACK1):
    files = files or iso_files(path)
    lba, size = files[name]
    out = bytearray()
    with open(path, 'rb') as f:
        for i in range((size + 2047) // 2048):
            f.seek((lba + i) * 2352)
            out += f.read(2352)[16:16 + 2048]
    return bytes(out[:size])


def text_starts():
    """{'SP06': 0x3ada, ...}: the first offset the HTML dump lists per file."""
    starts = {}
    for p in sorted(glob.glob(os.path.join(DUMP, 'SP*.html'))):
        key = os.path.basename(p)[:4]
        m = re.search(r'(0x[0-9a-f]+):', open(p, encoding='utf-8', errors='replace').read())
        if m:
            starts[key] = int(m.group(1), 16)
    return starts


def decode(b):
    out = []
    for c in b:
        if c == BREAK:
            out.append('￥')
        elif c == HI_ON:
            out.append('＠黄')
        elif c == HI_OFF:
            out.append('＠白')
        elif c >= 0xF0 or c < 0x20:
            out.append(f'<{c:02x}>')
        else:
            out.append(chr(c))
    return ''.join(out)


def strings(name, start, files=None):
    raw = read_file(name + '.BIN', files)
    out, i = [], start
    while i < len(raw):
        j = raw.find(bytes([END]), i)
        if j < 0:
            j = len(raw)
        if j > i:
            out.append({'off': i, 'text': decode(raw[i:j])})
        i = j + 1
    return out


def extract():
    files = iso_files()
    starts = text_starts()
    return {k: strings(k, starts[k], files) for k in sorted(starts)}


def main():
    if len(sys.argv) > 1:
        files = iso_files()
        for s in strings(sys.argv[1], text_starts()[sys.argv[1]], files):
            print(f"{s['off']:#06x}: {s['text']}")
        return
    data = extract()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"{OUT}: {sum(len(v) for v in data.values())} strings in {len(data)} files")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
