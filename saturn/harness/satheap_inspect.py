"""Read a saved native allocator state; never run or mutate an emulator."""
import argparse
import json
import os
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path[:0] = [str(ROOT / d) for d in ('lib', 'saturn/tools', 'saturn/harness')]
import satmem
import satlong


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    state = Path(args.state).read_bytes()
    high = satmem.state_ram(state)
    low = satmem.state_ram(state, 'WorkRAML')
    exe = satmem.image_exec(args.image)

    def word(address):
        address &= 0x1fffffff
        if 0x200000 <= address <= 0x2ffffc:
            return struct.unpack_from('>I', low, address - 0x200000)[0]
        if 0x6000000 <= address <= 0x60ffffc:
            return struct.unpack_from('>I', high, address - 0x6000000)[0]
        raise ValueError(f'Allocator pointer outside RAM: {address:#x}')

    pointer = word(0x060ff088)
    seen, nodes = set(), []
    while pointer not in seen:
        if len(seen) >= 10000:
            raise ValueError('Allocator list did not close within 10,000 nodes')
        seen.add(pointer)
        following, units = word(pointer), word(pointer + 4)
        nodes.append(dict(address=hex(pointer), next=hex(following), units=units,
                          available_bytes=max(0, units * 8 - 8)))
        pointer = following
    pool_var = satlong.buffer_var_from_exec(exe)
    pool_pointer = word(pool_var) if pool_var else None
    scene = struct.unpack_from('>H', high, satmem.SCENE_INDEX - 0x06000000)[0]
    result = dict(state=os.path.abspath(args.state), image=os.path.abspath(args.image),
                  read_only=True, scene_index=scene, bank_candidate_index=scene+21,
                  main_marker_matches=high[0xb0600:0xb0620] == exe[0x600:0x620],
                  long_pool_variable=hex(pool_var) if pool_var else None,
                  long_pool_pointer=hex(pool_pointer) if pool_var else None,
                  allocated_pool_bytes=(word(pool_pointer-4)*8-8) if pool_pointer else None,
                  free_list_closed_at=hex(pointer), free_nodes=nodes,
                  total_available_bytes=sum(n['available_bytes'] for n in nodes),
                  largest_available_bytes=max(n['available_bytes'] for n in nodes))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'free_nodes'}, indent=2))


if __name__ == '__main__':
    main()
