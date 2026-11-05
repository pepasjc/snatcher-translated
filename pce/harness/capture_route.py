"""Capture periodic rendered frames and transition states on a fresh BRAM boot."""
import argparse
import json
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
WORK = os.path.join(ROOT, 'work')
sys.path[:0] = [os.path.join(ROOT, p) for p in ('lib', 'pce/tools', 'pce/harness')]
import pcemenu as M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--save', required=True)
    ap.add_argument('--route', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--interval', type=int, default=120)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    p = M.Pilot()
    p.emu.load_card(a.save)
    p.step(1000); p.press('start'); p.step(3900)
    p.press('a'); p.step(600); p.press('a')
    M.wait_menu(p, 90, limit=16000)
    print('Loaded', p.module(), p.items(), flush=True)
    rows, last = [], None
    step = p.step
    def capture_step(n=1, held=()):
        nonlocal last
        while n:
            count = min(n, a.interval - p.frame % a.interval)
            step(count, held); n -= count
            if p.frame % a.interval:
                continue
            ram = p.ram()
            rec, track = p.module(), ram[0x63b] if ram[0x638] else 0
            stem = f'{p.frame:07d}_{rec}_{track:02x}'
            p.emu.image().save(os.path.join(a.out, stem + '.png'))
            if (rec, track) != last:
                with open(os.path.join(a.out, stem + '.mdf'), 'wb') as f:
                    f.write(p.emu.state())
                last = rec, track
                print(p.frame, rec, f'track {track:02x}', flush=True)
            rows.append(dict(frame=p.frame, module=rec, track=track, image=stem+'.png'))
    p.step = capture_step
    try:
        M.run(p, json.load(open(a.route, encoding='utf-8')), every=90, outdir=a.out)
    finally:
        with open(os.path.join(a.out, 'frames.json'), 'w') as f:
            json.dump(rows, f, indent=1)
        with open(os.path.join(a.out, 'end.mdf'), 'wb') as f:
            f.write(p.emu.state())


if __name__ == '__main__':
    main()
