"""Read-only supervision of stress pilots, including unexpected process loss.

Keep native status.json intact. Write supervision.json alongside it so a
stale running heartbeat cannot be mistaken for a live player.
"""
import argparse
import ctypes
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in
               ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]


def process_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.WaitForSingleObject.restype = ctypes.c_ulong
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if not handle:
            if ctypes.get_last_error() == 5:
                raise OSError("Cannot inspect pilot process: access denied")
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def observation(status, alive, age, stale_seconds):
    active = status.get("status") in {"running", "awaiting_native_control"}
    health = ("process_lost" if active and not alive else
              "heartbeat_stale" if active and age > stale_seconds else
              "awaiting_native_control" if active and status.get("status") == "awaiting_native_control" else
              "running" if active else "finished")
    card = status.get("last_card") or {}
    return dict(health=health, pilot_alive=alive, pilot_status=status.get("status"),
                pid=status.get("pid"), heartbeat_age_seconds=round(age, 1),
                phase=status.get("phase") or status.get("stage"),
                frame=status.get("frame"), bank=status.get("bank"),
                location=status.get("location"), current_action=status.get("current_action"),
                last_pick=status.get("last_pick"), current_menu=status.get("current_menu"),
                dialogue=card.get("rows"), dialogue_screenshot=card.get("shot"),
                font_checks=status.get("font_checks"),
                player_progress_age_minutes=status.get("player_progress_age_minutes"),
                location_changes=status.get("location_changes"),
                outside_minutes=status.get("outside_minutes"),
                restores=status.get("restores"),
                restored_for_validation=status.get("restored_for_validation", False),
                failure=status.get("failure") or status.get("reason"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--poll", type=float, default=30)
    parser.add_argument("--stale-seconds", type=float, default=180)
    args = parser.parse_args()
    if args.poll <= 0 or args.stale_seconds <= 0:
        parser.error("Polling and stale thresholds must be positive")
    pending = {os.path.abspath(p) for p in args.run}
    failed = False
    while pending:
        for directory in sorted(pending.copy()):
            path = os.path.join(directory, "status.json")
            try:
                with open(path, encoding="utf-8-sig") as fh:
                    status = json.load(fh)
                age = time.time() - os.path.getmtime(path)
                result = observation(status, process_alive(status.get("pid")),
                                     age, args.stale_seconds)
            except (OSError, ValueError) as exc:
                # Atomic status replacement can briefly make a read unavailable.
                print(f"{directory}: status unavailable: {exc}", flush=True)
                continue
            result["observed_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            screenshots = [os.path.join(directory, name) for name in os.listdir(directory)
                           if name.endswith(".png")]
            result["latest_screenshot"] = max(screenshots, key=os.path.getmtime) if screenshots else None
            temporary = os.path.join(directory, "supervision.tmp")
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
            os.replace(temporary, os.path.join(directory, "supervision.json"))
            with open(os.path.join(directory, "supervision.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(result) + "\n")
            print(json.dumps(dict(run=directory, **result)), flush=True)
            if result["health"] in {"process_lost", "finished"}:
                pending.remove(directory)
                failed |= result["health"] == "process_lost" or status["status"] in {"failed", "error", "interrupted"}
        if pending:
            time.sleep(args.poll)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
