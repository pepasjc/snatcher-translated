"""Inspect the preserved #88 tunnel failure offline; never mutate the core."""
from pathlib import Path
import sys, struct, json, hashlib, argparse
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORK = ROOT / 'work'
sys.path[:0] = [str(ROOT / d) for d in ('lib','saturn/tools','saturn/harness','saturn/subs','ps1/tools','ps1/subs')]
import satmem, satfont, fontwatch, lz3, satexec, satlong
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--image', required=True)
ap.add_argument('--state', required=True)
ap.add_argument('--out', required=True)
args = ap.parse_args()
image = str(Path(args.image).resolve())
state_path = Path(args.state).resolve()
state = state_path.read_bytes()
high = satmem.state_ram(state)
low = satmem.state_ram(state, 'WorkRAML')
exe = satmem.image_exec(image)
base, expected = fontwatch.expected_font(image)
font = satfont.vdp1_vram(state)[base:base+len(expected)]
off = satfont.TABLE_ADDR - 0x06000000
table = high[off:off + 2 * satfont.TABLE_N]
expected_table = exe[satfont.TABLE_ADDR-0x060B0000:satfont.TABLE_ADDR-0x060B0000 + len(table)]
lo, hi = satexec.sjis_range()
buffer_var = satlong.buffer_var_from_exec(exe)
changes = [hex(satfont.TABLE_LO+i//2) for i in range(0,len(table),2)
           if not lo <= satfont.TABLE_LO+i//2 < hi
           and not (buffer_var is not None and buffer_var <= satfont.TABLE_ADDR+i < buffer_var+4)
           and table[i:i+2] != expected_table[i:i+2]]
with open(satmem.image_track1(image), 'rb') as fh:
    def sectors(lba, size):
        out = bytearray()
        for i in range((size+2047)//2048):
            fh.seek((lba+i)*2352+16); out.extend(fh.read(2048))
        return bytes(out[:size])
    pvd = sectors(16,2048)
    directory = sectors(struct.unpack_from('<I',pvd,158)[0],struct.unpack_from('<I',pvd,166)[0])
    p = 0
    while p < len(directory):
        n = directory[p]
        if not n:
            p = (p//2048+1)*2048; continue
        rec = directory[p:p+n]
        if rec[33:33+rec[32]].split(b';')[0] == b'DATA.BIN':
            data_lba = struct.unpack_from('<I',rec,2)[0]; break
        p += n
    sec, words = struct.unpack_from('>HH',exe,satmem.CHUNK_TABLE-0x060B0000+4*55)
    bank = sectors(data_lba+sec,words*2)
text_base, region_size = struct.unpack_from('>HH', bank)
strings = bank[text_base+4:text_base+4+region_size]
pool_address = (struct.unpack_from('>I', high, buffer_var-0x06000000)[0]
                if buffer_var is not None else satlong.LONGS_BASE)
pool_tail = bank[text_base+4+region_size+4:]
pool_differences = []
pool_size = 0
if len(pool_tail) >= 8 and pool_tail[:4] == b'LNGS':
    pool_size = struct.unpack_from('>I', pool_tail, 4)[0]
    pool_off = (pool_address & 0x1fffffff) - 0x00200000
    if pool_address and 0 <= pool_off <= len(low)-pool_size:
        pool_differences = [i for i,(a,b) in enumerate(zip(pool_tail[8:8+pool_size], low[pool_off:pool_off+pool_size])) if a != b]
differences = [i for i,(a,b) in enumerate(zip(strings,low[0xE8000:])) if a != b]
cell_off = satmem.TEXT_CELLS - 0x06000000
cells = [[hex(struct.unpack_from('>H',high,cell_off+r*80+c*4)[0]) for c in range(20)] for r in range(4)]
result = dict(state=str(state_path), font_sha1=hashlib.sha1(font).hexdigest(),
              expected_font_sha1=hashlib.sha1(expected).hexdigest(), font_matches=font==expected,
              glyph_table_changes=changes, main_marker_matches=high[0xB0600:0xB0620]==exe[0x600:0x620],
              bank_size=len(bank), text_base=text_base, string_bytes=len(strings),
              string_changed_bytes=len(differences), first_string_changes= differences[:30],
              long_buffer_address=hex(pool_address), long_pool_bytes=pool_size,
              long_pool_changed_bytes=len(pool_differences), first_long_pool_changes=pool_differences[:30], cells=cells)
out = Path(args.out).resolve()
out.mkdir(parents=True,exist_ok=True)
(out/'inspection.json').write_text(json.dumps(result,indent=2))
(out/'B220_image.bin').write_bytes(bank)
(out/'low_ram.bin').write_bytes(low)
(out/'high_ram.bin').write_bytes(high)
print(json.dumps({k:v for k,v in result.items() if k!='cells'},indent=2))
