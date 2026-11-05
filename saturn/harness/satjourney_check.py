"""Bounded native route diagnostics; restored runs are never stress passes."""
import argparse
import gzip
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in
               ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--state", help="Restore a diagnostic state")
    source.add_argument("--save", help="Fresh boot from a scene save to validate new executable code")
    ap.add_argument("--stage", action="append", required=True)
    ap.add_argument("--action-offset", type=int, default=0,
                    help="Start the first restored diagnostic stage at this action index")
    ap.add_argument("--fight-offset", type=int, default=0,
                    help="Skip already completed aims in the first restored stage's fight setup")
    ap.add_argument("--pre-path", action="append", default=[],
                    help="Native controller path before the selected diagnostic actions; separate labels with /")
    ap.add_argument("--frames", type=int, default=60000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue"))
    a = ap.parse_args()
    if a.frames < 1:
        ap.error("--frames must be positive")
    if a.fight_offset < 0 or (a.fight_offset and (not a.state or not a.action_offset)):
        ap.error("--fight-offset requires a restored state and a positive action offset")
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    if os.path.exists(os.path.join(out, "status.json")):
        ap.error("Output already contains a diagnostic")
    os.environ["EMU_SAVE_DIR"] = os.path.join(out, "emu")
    import satrun
    import satplay
    import satjourney
    import satstress
    stages = {s["name"]: s for s in satjourney.opening_stages() + satjourney.stages(whole_game=True)}
    stages["finish_act1"] = dict(name="finish_act1", expected=["B130"],
                                actions=satjourney.route("saturn/harness/routes/B120_finish.json"))
    stages["act1_recap"] = dict(name="act1_recap", expected=["B150"], actions=[dict(recap=True)])
    stages["queen_phone"] = dict(name="queen_phone", actions=[
        dict(scene_menu="Queen Hospital"),
        satjourney.path("Use Metal Gear", "Videophone", strict=True),
        satjourney.path("Call", strict=True), dict(dial="395644"),
        dict(wait_menu=True, patience=6000)])
    stages["queen_phone_handoff"] = dict(name="queen_phone_handoff",
        actions=[dict(x, retry_prefix=False) if "dial" in x else x
                 for x in stages["queen_phone"]["actions"]])
    stages["queen_phone_speed"] = dict(name="queen_phone_speed",
        actions=[dict(x, dial="05") if "dial" in x else x
                 for x in stages["queen_phone"]["actions"]])
    stages["queen_consult"] = dict(name="queen_consult", expected=["B1D0"], actions=[
        satjourney.path("Exit Tricycle", optional=True), dict(scene_menu="Queen Hospital"),
        satjourney.path("Use Metal Gear", "Videophone", strict=True),
        satjourney.path("Call", strict=True), dict(dial="393444"),
        satjourney.path("Show item", "Chart|Medical chart", reps=2, strict=True),
        satjourney.path("Hang up", strict=True), dict(menu_settle=True),
        satjourney.path("Call", strict=True), dict(dial="391009"),
        satjourney.path("Show item", "Chart|Medical chart", reps=2, strict=True),
        satjourney.path("Hang up", strict=True), dict(menu_settle=True),
        satjourney.path("Call", strict=True), dict(dial="395644"),
        dict(sweep=["Look", "Think", "Talk"], rounds=2),
        satjourney.path("Hang up", optional=True), satjourney.path("Don't call", optional=True),
        dict(scene_menu="Queen Hospital"), satjourney.path("Move", "Board Tricycle", strict=True),
        satjourney.path("Outer Heaven", strict=True), satjourney.path("Exit Tricycle", strict=True)])
    satjourney.EndpointGuard.ORIGINS["queen_consult"] = "B1E0"
    satjourney.EndpointGuard.ORIGINS["finish_act1"] = "B120"
    if any(name not in stages or stages[name].get("soak") for name in a.stage):
        ap.error("Select named story stages, not soak phases")
    if not 0 <= a.action_offset < len(stages[a.stage[0]]["actions"]):
        ap.error("--action-offset must select an action in the first stage")
    satplay.STATES = os.path.join(out, "states")
    satplay.PLAY = os.path.join(out, "captures")
    os.makedirs(satplay.STATES, exist_ok=True)
    side = os.path.splitext(a.image)[0] + ".pair_table.json"
    satplay.SAT_TABLE = side if os.path.exists(side) else os.path.join(WORK, "saturn", "pair_table_sat.json")
    result = dict(status="running", validation_only=True, restored_for_validation=bool(a.state),
                  source_state=os.path.abspath(a.state) if a.state else None, source_save=a.save,
                  image=os.path.abspath(a.image), stages=a.stage, action_offset=a.action_offset,
                  pre_paths=a.pre_path, fight_offset=a.fight_offset, completed=[], pid=os.getpid())
    started = time.time()
    with open(os.path.join(out, "log.txt"), "w", encoding="utf-8") as lf:
        def log(value):
            lf.write(str(value) + "\n"); lf.flush()
        if a.save:
            import satsave
            import satsave_check
            record = satsave.entry_of(a.save)
            os.makedirs(satsave.EMU_SAVES, exist_ok=True)
            with open(os.path.join(satsave.EMU_SAVES, satsave.image_stem(a.image) + ".bkr"), "wb") as fh:
                fh.write(satsave.read_image(record["path"]))
        emu = satrun.SaturnEmu(); emu.load(a.image)
        if a.state:
            with open(a.state, "rb") as fh:
                state = fh.read()
            emu.restore(gzip.decompress(state) if a.state.endswith(".gz") else state)
        play = satplay.Play(emu, out, log, a.image, autosave=False)
        watch = satstress.IntegrityWatch(a.image, out, 120, log)
        satstress.guard_gameplay_tracking(play, watch.exe)
        ending = satjourney.EndingObserver()
        player_watch = satstress.PlayerProgressWatch()
        original = play.run
        guard = None
        next_heartbeat = 0
        boot_complete = bool(a.state)

        def status():
            result.update(frame=play.f, bank=satplay.BANK_NAMES.get(play.bank),
                          wall_seconds=round(time.time() - started, 1), font_checks=watch.checks,
                          cards=len(play.cards), menus=len(play.menus),
                          location=satstress.LOCATIONS.get(satplay.BANK_NAMES.get(play.bank)),
                          last_pick=play.last_pick,
                          last_card=play.cards[-1] if play.cards else None,
                          current_menu=play.labels_now())
            temporary = os.path.join(out, "status.tmp")
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
            os.replace(temporary, os.path.join(out, "status.json"))

        def tick(frame):
            nonlocal next_heartbeat
            if not boot_complete:
                if frame >= next_heartbeat:
                    next_heartbeat = frame + 3600
                    status()
                    emu.image().save(os.path.join(out, "latest.png"))
                return
            watch.inspect(play)
            ending.observe(play.cards)
            if frame % 120 == 0:
                movie = play.mem.read(0x060B0600, 32) != watch.exe[0x600:0x620]
                player_watch.observe(frame, satstress.player_state(play), movie or ending.frame is not None)
                result["player_progress_age_minutes"] = round((frame - player_watch.last_new) / satstress.FPS / 60, 3)
            if frame >= next_heartbeat:
                next_heartbeat = frame + 3600
                status()
                emu.image().save(os.path.join(out, "latest.png"))
                if ending.frame is not None:
                    emu.image().save(os.path.join(out, f"ending_heartbeat_{frame:08d}.png"))
                if os.path.exists(os.path.join(out, "stop.request")):
                    raise satstress.StressFailure("Diagnostic stopped for route correction")
            if frame >= a.frames:
                raise satstress.StressFailure("Diagnostic frame limit exceeded")
            if guard and guard.observe(satplay.BANK_NAMES.get(play.bank)):
                raise satstress.GuideDone()
            if any(p["kind"] in satstress.SERIOUS for p in play.problems[-3:]):
                raise satstress.StressFailure("Serious diagnostic rendering/pilot error")

        def run(n=1, hook=None):
            satstress.guarded_run(original, tick, n, hook)
        play.run = run
        def no_restore(*args, **kwargs):
            raise satstress.StressFailure("Route attempted a second restoration")
        emu.restore = no_restore
        try:
            if a.save:
                result["stage"] = "boot"
                if not satsave_check.continue_from_title(play, log):
                    raise RuntimeError("CONTINUE did not open")
                satsave_check.load_file(play, record.get("slot") or 1, log)
                for _ in range(120):
                    play.run(30)
                    if (satplay.BANK_NAMES.get(play.bank) == record.get("bank")
                            and play.mem.u8(satplay.satmem.MENU_LIVE) == 1):
                        break
                else:
                    raise RuntimeError("Scene save did not reach its expected bank and menu")
                boot_complete = True
            play.run(60)
            for labels in a.pre_path:
                action = dict(path=labels.split("/"), strict=True, patience=6000)
                result["current_action"] = action
                status()
                satjourney.run_action(action, play, a.frames, lambda *args, **kw: None, log)
            for stage_index, name in enumerate(a.stage):
                result["stage"] = name; status()
                stage = stages[name]
                player_watch.reset(play.f)
                fights_before = play.fights
                guard = satjourney.EndpointGuard(stage)
                play.fight_state = "body"
                try:
                    offset = a.action_offset if stage_index == 0 else 0
                    # A restored diagnostic starts with a new Play object.
                    # Preserve the stage's controller setup when skipping
                    # already validated native actions.
                    for setup in stage["actions"][:offset]:
                        if "fight" in setup:
                            if stage_index == 0 and a.fight_offset:
                                aims = setup["fight"]
                                if not isinstance(aims, list) or a.fight_offset >= len(aims):
                                    raise ValueError("Fight offset must leave at least one aim")
                                setup = dict(setup, fight=aims[a.fight_offset:])
                            satjourney.run_action(setup, play, a.frames, lambda *args, **kw: None, log)
                    for action_index, action in enumerate(stage["actions"][offset:], offset):
                        result["action_index"] = action_index
                        result["current_action"] = action
                        status()
                        log("ACTION " + json.dumps(action))
                        if action.get("recap"):
                            def recap_started(frame):
                                if satplay.BANK_NAMES.get(play.bank) in {"B140", "B150"}:
                                    raise satstress.GuideDone()
                            while satplay.BANK_NAMES.get(play.bank) != "B150":
                                if satplay.BANK_NAMES.get(play.bank) == "B140":
                                    satstress.advance_transition(play)
                                else:
                                    try:
                                        got = play.wait_menu(patience=300, hook=recap_started)
                                        if (got and satplay.BANK_NAMES.get(play.bank) == "B130"
                                                and got[3] == ["Save", "Don't save"]):
                                            play.pick("Don't save")
                                    except satstress.GuideDone:
                                        pass
                            satjourney.wait_scene_menu(play, "HQ")
                        else:
                            satjourney.run_action(action, play, a.frames, lambda *args, **kwargs: None, log)
                except satstress.GuideDone:
                    pass
                guard = None
                satjourney.verify_stage(play, stage, fights_before)
                if stage.get("finish_game"):
                    while ending.frame is None:
                        satstress.advance_transition(play)
                    while play.f - ending.frame < 10 * 60 * satstress.FPS:
                        play.run(30)
                    result.update(ending_cue=ending.cue_id, ending_frame=ending.frame)
                    emu.image().save(os.path.join(out, "ending_credits.png"))
                result["completed"].append(name)
                with open(os.path.join(out, "phase_" + name + ".state"), "wb") as fh:
                    fh.write(emu.state())
                emu.image().save(os.path.join(out, "phase_" + name + ".png"))
            watch.inspect(play, force=True)
            result["status"] = "passed"
        except Exception as exc:
            result.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        finally:
            if result["status"] == "failed" and watch.previous:
                before = os.path.join(out, "before_failure.state")
                if not os.path.exists(before):
                    with open(before, "wb") as fh:
                        fh.write(watch.previous)
            with open(os.path.join(out, "final.state"), "wb") as fh:
                fh.write(emu.state())
            emu.image().save(os.path.join(out, "final.png"))
            play.finish(started)
            status()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
