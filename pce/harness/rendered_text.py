"""Audit active English text buffers; findings require review, not automatic rewriting.

python pce/harness/rendered_text.py STATE.mdf [STATE.mdf ...] --out REPORT.json
Live Pilot runs capture persistent findings under work/pce/text_audit/.
"""
import argparse
import json
import os
import sys
import unicodedata
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'work')
sys.path[:0] = [os.path.join(ROOT, p) for p in ('lib', 'pce/tools', 'pce/harness')]
import pcestate as ST
import pcepair

# Renderer commands and their parameter bytes. Never interpret parameters as glyphs.
COMMANDS = {0xFC: 1, 0xF9: 1, 0xFE: 1, 0xFB: 2, 0xF8: 2}


def inspect_buffer(raw, table):
    if not raw.startswith(b'\xfc'):
        return []
    issues, at = [], 0
    while at < len(raw):
        hi = raw[at]
        if hi == 0xFF:
            return sorted(set(issues))
        if hi in COMMANDS:
            at += COMMANDS[hi] + 1
            continue
        if at + 1 >= len(raw):
            issues.append('Truncated glyph')
            break
        lo = raw[at + 1]
        if pcepair.is_pair(hi, lo):
            slot = pcepair.slot_of_code(hi, lo)
            canonical = 0 <= slot < pcepair.SLOTS and pcepair.code_of_slot(slot) == (hi, lo)
            if not canonical or slot >= len(table.pairs):
                issues.append(f'Invalid English pair {hi:02X}{lo:02X} (slot {slot})')
            elif not all(pcepair.printable(c) for c in table.pairs[slot]):
                issues.append(f'Invalid font glyph in pair slot {slot}')
        else:
            try:
                char = bytes((hi, lo)).decode('cp932')
            except UnicodeDecodeError:
                issues.append(f'Invalid glyph code {hi:02X}{lo:02X}')
            else:
                names = [unicodedata.name(c, '') for c in char]
                if any(any(k in n for k in ('HIRAGANA', 'KATAKANA', 'CJK UNIFIED', 'CJK COMPATIBILITY')) for n in names):
                    issues.append(f'Japanese glyph {hi:02X}{lo:02X}')
        at += 2
    issues.append('No buffer terminator')
    return sorted(set(issues))


def inspect_state(blob):
    sec = ST.sections(blob, ('BaseRAM', 'SysCardRAM', 'CDRAM'))
    mod = sec['SysCardRAM'][0x2C000:0x30000] + sec['CDRAM'][:0x4000]
    if len(mod) != 0x8000 or mod[0x7FFB] != 1:
        return []  # only modules declaring English text; excludes native/title images
    ptr = int.from_bytes(mod[pcepair.PAIRS_PTR:pcepair.PAIRS_PTR+2], 'little')
    if not 2 <= ptr < len(mod):
        return []  # partial module loads are not rendered-text evidence
    count = int.from_bytes(mod[ptr-2:ptr], 'little')
    if not 0 < count <= pcepair.SLOTS or ptr + 2 * count > len(mod):
        return []
    table = pcepair.PairTable.from_module(mod)
    ram = sec['BaseRAM']
    buffers = []
    if ram[0x1478] and ram[0x1600] in (3, 4, 5):
        buffers.append(('dialogue', ram[0x1610:0x1610+96]))
    if ram[0x1A66:0x1A68] == b'\xfc\x00':
        buffers.append(('subtitle', ram[0x1A66:0x1A66+136]))
    out = []
    for kind, raw in buffers:
        errors = inspect_buffer(raw, table)
        if errors:
            out.append(dict(kind=kind, errors=errors, raw=raw.hex(),
                            text_pointer=int.from_bytes(ram[0x1609:0x160B], 'little')))
    return out


class Monitor:
    def __init__(self):
        self.previous = set()
        self.seen = set()
        self.findings = []
        self.directory = None

    def sample(self, pilot):
        if pilot.frame % 30:
            return
        blob = pilot.emu.state()
        findings = inspect_state(blob)
        current = set()
        for item in findings:
            # Two matching samples avoid partial row writes; one report per distinct buffer.
            key = (pilot.module(), item['kind'], item['raw'])
            current.add(key)
            if key not in self.previous or key in self.seen:
                continue
            self.seen.add(key)
            if self.directory is None:
                import tempfile
                parent = os.path.join(WORK, 'pce', 'text_audit')
                os.makedirs(parent, exist_ok=True)
                self.directory = tempfile.mkdtemp(prefix='run_', dir=parent)
            stem = os.path.join(self.directory, f"{str(pilot.module()).replace('?', 'x')}_{pilot.frame}")
            pilot.emu.image().save(stem + '.png')
            Path(stem + '.mdf').write_bytes(blob)
            item.update(module=pilot.module(), frame=pilot.frame, capture=stem)
            self.findings.append(item)
            Path(self.directory, 'findings.json').write_text(json.dumps(self.findings, indent=1), encoding='utf-8')
            print(f"TEXT REVIEW: module {item['module']} frame {pilot.frame}: {item['errors'][:3]}; {stem}", flush=True)
        self.previous = current


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('states', nargs='+')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    rows = [dict(state=f, findings=inspect_state(Path(f).read_bytes())) for f in a.states]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rows, indent=1), encoding='utf-8')
    bad = sum(bool(r['findings']) for r in rows)
    print(f'{len(rows)} states checked; {bad} need text review; {a.out}')
    return bool(bad)


if __name__ == '__main__':
    sys.exit(main())
