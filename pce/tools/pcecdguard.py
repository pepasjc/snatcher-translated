"""The CD-DA wait always ends: the script's "wait for the track to stop" knows a drive that
plays past the track's end.

A scene that waits for its CD-DA track queues opcode 0b (stage 2's bank 0, $4CE7, called
from the main loop): it advances once no CD command is pending ($26F5), CD_STAT (A=0)
says the drive is idle and the sub-Q status ($20A0) is no longer 0 (playing). The game
plays a track with CD_PLAY to the start of the next one (`_dh` $82). On the Analogue
Pocket's PCE CD core the play did not stop there: after the Tricycle's flight (318,
track 20, 29.7 s) the music and the animation ran on, the last subtitle page stayed up
and the factory never loaded (Luiz, 2026-10-18, v17 and v18); Beetle stops the drive at
the track's end every time, and the queue moves on the frame `$2638` drops.

So 0b also ends the wait when the drive has run past its track. No CD command or
confirmation pending (`$26F5`, `$263C`, as before); then on when the sub-Q status ($20A0,
refreshed by the CD service every 4 frames while a track plays) is no longer 0 - the
original's test without its CD_STAT call (the status leaves 0 exactly when the drive
stops, pauses or seeks); and when the drive still plays but the sub-Q's track ($20A2,
BCD) is no longer the one requested (`$263B`), it ran into the next track: 0b pauses it
(CD_PAUSE), the status leaves 0, the service drops `$2638` as at a reported end, and the
next pass goes on - the next scene's loader ($5451, which waits for an idle drive and
`$2638` down) finds both. A drive that stops at the end never meets the third test.

It fits in place, the opcode's 22 bytes to the byte: the advance is the `JSR $4DE9 /
RTS` at $4C98, the wait the RTS at $4CE6; no bank switched. (A first cut mapped bank 1
at MPR3 from the main loop to run a longer test from its tail: a vblank landing in that
window ran the handler's short path into bank 1 and the game crashed - pcesubs'
tin/tback are only ever used inside the vblank. A second dropped `$2638` and advanced at
once: the loader that follows then waited on a drive still playing.)

  python pce/tools/pcecdguard.py [apply|check]
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in ('lib', 'lib/asr', 'ps1/tools', 'ps1/subs', 'ps1/harness', 'pce/tools')]

import patch_pce as P
from asm6280 import assemble

OP0B = 0x4CE7                                         # bank 0: the queue's opcode 0b
OLD_OP0B = bytes.fromhex("adf526d010" "62201be0c900d008" "a5a0f004" "20e94d60" "60")
ADVANCE = 0x4C98                                      # JSR $4DE9 / RTS (the queue on by one)
WAIT = 0x4CE6                                         # an RTS
assert ADVANCE == 0x4C98 and WAIT == 0x4CE6

SOURCE = """
op0b:
  LDA 0x26F5             ; a CD command pending
  ORA 0x263C             ; or a play not yet confirmed: wait
  BNE {WAIT}
  LDA 0xA0               ; the sub-Q status no longer 0 (playing): the play is over - on
  BNE {ADVANCE}
  LDA 0xA2               ; the sub-Q's track (BCD)
  CMP 0x263B
  BEQ {WAIT}             ; still the one requested: wait
  JMP 0xE018             ; the drive ran past its end: CD_PAUSE (its RTS is ours) - the
"""                      # status leaves 0, the service drops $2638, and the next pass goes on


def code():
    out, _ = assemble(SOURCE.format(WAIT=WAIT, ADVANCE=ADVANCE), OP0B)
    if len(out) > len(OLD_OP0B):
        raise SystemExit(f"op 0b is {len(out)} B, the opcode holds {len(OLD_OP0B)}")
    return bytes(out) + bytes([0x60]) * (len(OLD_OP0B) - len(out))


def patches():
    """[(stage-2 file offset, old bytes, new bytes)]."""
    return [(OP0B - P.STAGE2_BASE, OLD_OP0B, code())]


def apply(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (P.T2 + P.STAGE2) * P.DATA
    for at, old, new in patches():
        got = bytes(img.data[base + at:base + at + len(old)])
        if got == new:
            continue                       # applied already
        if got != old:
            raise SystemExit(f"stage 2 at {P.STAGE2_BASE + at:#06x} is not as expected ({got.hex()})")
        img.write(base + at, new)
    n = img.flush()
    print(f"CD guard: op 0b ({OP0B:#06x}) ends its wait when the drive runs past its track; {n} sectors written")


def check(out_path=P.OUT):
    img = P.Image(out_path, P.T3 + P.RESERVE)
    base = (P.T2 + P.STAGE2) * P.DATA
    for at, old, new in patches():
        got = bytes(img.data[base + at:base + at + len(new)])
        print(f"  stage 2 {P.STAGE2_BASE + at:#06x}: {'patched' if got == new else 'PRISTINE' if got == old else 'OTHER'}")


if __name__ == "__main__":
    {"apply": apply, "check": check}[sys.argv[1] if len(sys.argv) > 1 else "apply"]()
