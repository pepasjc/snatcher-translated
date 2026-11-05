"""Check runtime overflow text against the built disc at stable menu boundaries."""
import os
import sys
from functools import lru_cache
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'work')
sys.path[:0] = [os.path.join(ROOT, p) for p in ('lib', 'pce/tools', 'pce/harness')]
import pcestate as ST
import pcelongs as L
import pcepair
import patch_pce as P


@lru_cache(maxsize=64)
def expected(path, modified, record, sectors):
    with open(path, 'rb') as f:
        out = bytearray()
        for i in range(sectors):
            f.seek((P.T2 + record + i) * P.RAW + P.HDR)
            out.extend(f.read(P.DATA))
    return bytes(out)


def check_state(blob, image=P.OUT):
    sec = ST.sections(blob, ('SysCardRAM', 'CDRAM'))
    module = sec['SysCardRAM'][0x2C000:0x30000] + sec['CDRAM'][:0x4000]
    if pcepair.PairTable.from_module(module) is None:
        return []  # native image, title, or a scene block rather than an English module
    d = L.parse(module[L.DESC:L.DESC+9])
    if not d:
        return []
    if d['bank'] not in (0x6B, 0x6C) or d['off'] + d['nbytes'] > 0x2000:
        return ['Invalid overflow text descriptor']
    record = d['rec']
    want = expected(image, os.stat(image).st_mtime_ns, record, -(-d['nbytes'] // P.DATA))[:d['nbytes']]
    start = (d['bank'] - 0x68) * 0x2000 + d['off']
    got = sec['SysCardRAM'][start:start+len(want)]
    if got != want:
        return [f'Overflow text record {record}: {sum(a != b for a,b in zip(got,want))} bytes differ from disc']
    return []


def check(pilot):
    # The pristine-image harness intentionally uses another disc and has no English banks.
    if os.path.abspath(pilot.cue) != os.path.abspath(os.path.join(ROOT, 'patched', 'pce', 'snatcher_pce.cue')):
        return
    blob = pilot.emu.state()
    errors = check_state(blob)
    if errors:
        os.makedirs(os.path.join(WORK, 'pce', 'text_integrity'), exist_ok=True)
        stem = os.path.join(WORK, 'pce', 'text_integrity', f'{pilot.module()}_{pilot.frame}')
        pilot.emu.image().save(stem + '.png')
        with open(stem + '.mdf', 'wb') as f:
            f.write(blob)
        raise RuntimeError('; '.join(errors) + f'; captured {stem}')
