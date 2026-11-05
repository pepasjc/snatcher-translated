"""Continuous Saturn stress: late Act 1 or New Game through the ending.

Boot a backup-RAM save once, roam using seeded menu choices, finish Act 1,
then play Act 2 with tours after Oleen and BENSON, finish it and continue
Act 3. Never restore a state, reset, inject a bank, or poke flags.
Stop on damaged font pixels/mappings or a serious harness error. Duration
is emulated play time (60 frames/s), not accelerated host wall time.

  python saturn/harness/satstress.py --act1-minutes 15 --act2-minutes 120
  python saturn/harness/satstress.py --seed 89 --start-save B120_start_manual
  python saturn/harness/satstress.py --whole-game --seed 88
"""
import argparse
import collections
import contextlib
import hashlib
import json
import math
import os
import random
import sys
import time

# Journey helpers import these exceptions. Keep the CLI's classes identical
# to imported classes so scene/deadline interrupts are caught by the runner.
if __name__ == "__main__":
    sys.modules["satstress"] = sys.modules[__name__]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in
               ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]

FPS = 60
TRAVEL = {"move", "go out", "go out front", "go inside", "go back",
          "board tricycle", "exit tricycle", "front", "front desk", "hallway"}
EXCLUDE = {"save", "load", "quit", "quit game", "new game", "don't continue"}
SERIOUS = {"GARBAGE", "BLANK", "FROZEN", "WEDGE", "INVISIBLE"}
SOAK_PHASES = {"oleen_soak", "late_soak"}
TERMINALS = {"B030", "B040"}
TERMINAL_VISIT_FRAMES = 90 * FPS
TERMINAL_EXITS = ("quit training", "stop search", "back to menu", "quit montage", "log off",
                  "don't use gaudi", "hang up", "don't call", "move")
# Resource banks for physical locations. Phone, terminal, map, save and
# recap banks are overlays; loading them does not constitute a new location.
LOCATIONS = {"B010": "HQ", "B080": "HQ", "B020": "Factory ruins",
             "B0B0": "Home", "B0C0": "Gibson's house", "B0D0": "Altamira",
             "B0E0": "Joy Division", "B0F0": "Outer Heaven", "B100": "Outer Heaven",
             "B110": "Ivan's apartment", "B120": "Freddy's apartment", "B130": "Freddy's apartment",
             "B150": "HQ", "B160": "HQ", "B230": "HQ",
             "B190": "Altamira", "B1A0": "Home", "B1B0": "Oleen Hospital",
             "B1C0": "Gibson's house", "B1D0": "Outer Heaven",
             "B1E0": "Queen Hospital", "B1F0": "Cockpit",
            "B200": "Basement", "B210": "Reconstruction", "B220": "Tunnel"}
DESTINATIONS = {"altamira": "Altamira", "gillian's home": "Home", "home": "Home",
                "oleen hospital": "Oleen Hospital", "queen hospital": "Queen Hospital",
                "queens hospital": "Queen Hospital", "gibson's house": "Gibson's house",
                "gibson's home": "Gibson's house",
                "outer heaven": "Outer Heaven", "junker hq": "HQ",
                "oleen hosp.": "Oleen Hospital", "queen hosp.": "Queen Hospital",
                "queen hosp": "Queen Hospital", "gibson hm": "Gibson's house",
                "gibson's": "Gibson's house", "joy division": "Joy Division",
                "ivan's": "Ivan's apartment", "ivan's home": "Ivan's apartment",
                "ivan's apartment": "Ivan's apartment", "freddy's": "Freddy's apartment",
                "freddy's home": "Freddy's apartment", "freddy's apartment": "Freddy's apartment"}


class StageEnd(Exception):
    pass


class StressFailure(Exception):
    pass


class TravelStall(StressFailure):
    pass


def native_control_actions(play, command):
    """Only normal controller operations are accepted by the live queue."""
    if set(command) - {"actions", "continue"}:
        raise ValueError("Native control accepts actions and continue only")
    actions = command.get("actions", [])
    if not isinstance(actions, list) or len(actions) > 100:
        raise ValueError("Native control requires at most 100 actions")
    for action in actions:
        if not isinstance(action, dict) or len(action) != 1:
            raise ValueError("Each native action must have one operation")
        key, value = next(iter(action.items()))
        if key == "press" and value in {"a", "b", "c", "start", "up", "down", "left", "right"}:
            play.press(value)
            play.run(30)
        elif key == "wait" and isinstance(value, int) and 0 < value <= 3600:
            play.run(value)
        elif key == "path" and isinstance(value, list) and 0 < len(value) <= 8 and all(isinstance(x, str) for x in value):
            if not play.do_path(value, patience=1800):
                raise ValueError(f"Native menu path was not available: {value}")
        else:
            raise ValueError(f"Unsupported native action: {key}")
    return command.get("continue") is True


class PlayerProgressWatch:
    """Repeated cards/menus do not establish story progress."""
    def __init__(self, limit=5 * 60 * FPS):
        self.limit = limit
        self.reset(0)

    def reset(self, frame):
        self.seen = set()
        self.last_new = frame

    def observe(self, frame, state, suspended=False):
        if suspended or state not in self.seen:
            self.last_new = frame
            if not suspended:
                self.seen.add(state)
        elif frame - self.last_new >= self.limit:
            raise StressFailure("Player repeated known story states for five emulated minutes; inspect the saved scene/menu")


def player_state(play):
    import satplay
    card = play.cards[-1] if play.cards else {}
    bank = satplay.BANK_NAMES.get(play.bank)
    return (bank, card.get("src"), tuple(card.get("rows", [])),
            tuple(play.labels_now()), play.mem.read(satplay.PAD_TYPED, 14),
            play.light_xy() if bank == "B1E0" else None,
            tuple(sorted(getattr(play, "montage_features", {}).items())))


class PanelOpen(Exception):
    pass


class GuideDone(Exception):
    pass


def guarded_run(original_run, tick, n=1, hook=None):
    """Check every frame, including inside the pilot's long waits/sweeps."""
    def each(frame):
        tick(frame)
        if hook:
            hook(frame)
    original_run(n, each)


def act2_ready(bank):
    # B140 is the small transition stub/voiced recap. Its old Save menu can
    # remain live in RAM, so it does not prove Act 2's HQ is ready to explore.
    return bank == "B150"


def advance_transition(play):
    """Advance a voiced transition while ignoring stale list-menu flags."""
    import satmem
    import satplay
    play.run(30)
    if play.mem.u8(satmem.BOX_WAIT) == 1 and play.f - play.last_press_f >= satplay.ADVANCE:
        play.press(satplay.OK)
        play.last_press_f = play.f


def settle_tour_arrival(play):
    """Arrival overlays can leave a live tricycle menu in the new bank."""
    import satplay
    bank = satplay.BANK_NAMES.get(play.bank)
    if bank not in LOCATIONS or "Exit Tricycle" not in play.labels_now():
        return
    start = play.f
    while "Exit Tricycle" in play.labels_now():
        if play.f - start >= 18000:
            raise TravelStall("Arrival retained the tricycle menu for five minutes")
        advance_transition(play)
        if play.f - play.last_press_f >= satplay.IDLE_PAGE:
            play.press(satplay.OK)
            play.last_press_f = play.f


def keyboard_open(mem):
    """Read the selected build's panel counts, including puzzle keyboards."""
    import satkeys
    try:
        count = mem.u16(mem.u32(satkeys.LIST_PTR))
        return count in {mem.u16(addr) & 0xff for addr in
                         (satkeys.SEARCH_COUNT, satkeys.PUZZLE_COUNT)}
    except ValueError:
        return False


def leave_keyboard(play):
    # B is backspace. START leaves the name-search keyboard, even with text
    # in its buffer. Bound retries so a different panel cannot loop forever.
    for _ in range(3):
        if not keyboard_open(play.mem):
            return
        play.press("start")
        play.run(120)
    if keyboard_open(play.mem):
        raise StressFailure("Keyboard did not close after three START presses")


class MenuPolicy:
    """Favor less-used choices, periodically travel, occasionally cancel."""
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.visits = collections.Counter()
        self.choices = 0

    def choose(self, bank, room, labels, top, phase, escaping=False, blocked=()):
        if escaping:
            normalized = [label.strip().lower() for label in labels]
            for exit_label in TERMINAL_EXITS:
                if exit_label in normalized:
                    return normalized.index(exit_label)
            travel = [i for i, label in enumerate(normalized) if label in TRAVEL]
            return self.rng.choice(travel) if travel else None
        context = (bank, room, tuple(labels))
        choices = []
        for i, label in enumerate(labels):
            text = label.strip().lower()
            if not text or text in EXCLUDE or text in blocked:
                continue
            # Keep the Act 1 finale and the chief's ceiling fight for their
            # progression phase; all other ordinary options remain available.
            if phase == "act1_roam" and "bathroom" in text:
                continue
            if phase == "act1_roam" and bank == "B120" and text == "knock":
                continue  # keep the initial travel loop outside Lisa's flat
            if phase == "act2_roam" and bank == "B230" and text == "ceiling":
                continue
            key = context + (label,)
            weight = 1 / (1 + self.visits[key]) ** 1.5
            if top and self.choices % 4 == 0 and text in TRAVEL:
                weight *= 8
            choices.append((i, key, weight))
        if not choices:
            return None
        # Back out of optional panels/submenus without restoring any state.
        if not top and self.choices % 11 == 10 and all(self.visits[x[1]] for x in choices):
            self.choices += 1
            return None
        least = min(self.visits[x[1]] for x in choices)
        candidates = [x for x in choices if self.visits[x[1]] == least]
        i, key, _ = self.rng.choices(candidates, weights=[x[2] for x in candidates])[0]
        self.visits[key] += 1
        self.choices += 1
        return i


class LocationTour:
    """Leave HQ and rotate through unlocked physical locations by pad input."""
    def __init__(self):
        self.location = None
        self.since = 0
        self.departing_since = None
        self.pending_arrival = False
        self.visits = collections.Counter()
        self.transitions = 0
        self.outside = set()
        self.outside_frames = 0

    def observe(self, bank, frame):
        location = LOCATIONS.get(bank)
        if location and location != self.location:
            if self.location:
                self.transitions += 1
            self.location, self.since = location, frame
            self.departing_since = None
            self.pending_arrival = False
            self.visits[location] += 1
            if location != "HQ":
                self.outside.add(location)
        # Only time in an actual external resource bank counts, not its
        # phone book, terminal, transit map or other temporary overlay.
        if location and location != "HQ":
            self.outside_frames += 1
        if self.departing_since is not None and frame - self.departing_since > 5 * 60 * FPS:
            raise TravelStall("Travel failed to load another physical location within five minutes")

    def blocked_departures(self, frame):
        limit = (2 if self.location == "HQ" else 3) * 60 * FPS
        if self.location and frame - self.since < limit:
            return {"board tricycle", "go out", "go out front"}
        return set()

    def choose(self, bank, frame, labels, allow_hq=True):
        normalized = [label.strip().lower() for label in labels]
        if bank == "B170":
            if self.pending_arrival and "exit tricycle" in normalized:
                return True, normalized.index("exit tricycle")
            candidates = [(i, DESTINATIONS[label]) for i, label in enumerate(normalized)
                          if label in DESTINATIONS and DESTINATIONS[label] != self.location
                          and (allow_hq or DESTINATIONS[label] != "HQ")]
            if candidates:
                # Visit every unlocked destination before repeating it.
                i, _ = min(candidates, key=lambda x: (self.visits[x[1]], x[1] == "HQ", x[0]))
                self.pending_arrival = True
                return True, i
            return True, normalized.index("exit tricycle") if "exit tricycle" in normalized else None
        limit = (2 if self.location == "HQ" else 3) * 60 * FPS
        if self.departing_since is None and frame - self.since < limit:
            return False, None
        if self.departing_since is None:
            self.departing_since = frame
        for label in TERMINAL_EXITS[:-1] + ("board tricycle", "go out", "go out front",
                                           "front desk", "front", "move", "go back"):
            if label in normalized:
                return True, normalized.index(label)
        return True, None  # B backs out of an unrelated submenu


class OptionCoverage:
    def __init__(self):
        self.items = {}

    def offer(self, bank, room, labels):
        for label in labels:
            if not label.strip() or label.strip().lower() in EXCLUDE:
                continue
            key = (bank, room, tuple(labels), label)
            self.items.setdefault(key, dict(bank=bank, room=room, menu=labels,
                                           label=label, attempts=0, successes=0))

    def record(self, bank, room, labels, choice, ok, attempt=True):
        key = (bank, room, tuple(labels), labels[choice])
        if key in self.items:
            self.items[key]["attempts"] += int(attempt)
            self.items[key]["successes"] += int(ok)

    def missing_outside(self):
        return [item for item in self.items.values()
                if LOCATIONS.get(item["bank"]) not in {None, "HQ"} and not item["attempts"]]


def guard_gameplay_tracking(play, exe):
    """Dialogue RAM belongs to MAIN_L only while its executable is resident."""
    original = play.track
    marker = exe[0x600:0x620]

    def track():
        if play.mem.read(0x060B0600, 32) != marker:
            # Movies replace this memory with media data. Reset settling state
            # so returning gameplay cannot inherit a movie's stale observations.
            play.tick = None
            play.last_cells = None
            play.card_key = None
            play.face_watch = None
            return
        original()

    play.track = track


class IntegrityWatch:
    def __init__(self, image, out, every, log):
        import fontwatch
        import satmem
        import satfont
        import satexec
        import satlong
        self.base, self.font = fontwatch.expected_font(image)
        self.exe = satmem.image_exec(image)
        self.table_off = satfont.TABLE_ADDR - 0x060B0000
        self.table = self.exe[self.table_off:self.table_off + 2 * satfont.TABLE_N]
        lo, hi = satexec.sjis_range()
        self.hole = (2 * (lo - satfont.TABLE_LO), 2 * (hi - satfont.TABLE_LO))
        buffer_var = satlong.buffer_var_from_exec(self.exe)
        self.runtime_table_ranges = ([] if buffer_var is None else
                                     [(buffer_var - satfont.TABLE_ADDR, buffer_var - satfont.TABLE_ADDR + 4)])
        self.out, self.every, self.log = out, every, log
        self.next_frame = 0
        self.checks = self.skipped = 0
        self.previous = None
        self.failure = None

    def inspect(self, play, force=False):
        import satfont
        import satmem
        if not force and play.f < self.next_frame:
            return
        self.next_frame = play.f + self.every
        # The movie player temporarily occupies MAIN_L's RAM. Never compare
        # its bytes with MAIN_L's table or call that a glyph-table failure.
        if play.mem.read(0x060B0600, 32) != self.exe[0x600:0x620]:
            self.skipped += 1
            return
        state = play.emu.state()
        actual = satfont.vdp1_vram(state)[self.base:self.base + len(self.font)]
        table = play.mem.read(satfont.TABLE_ADDR, len(self.table))
        a, b = self.hole
        self.checks += 1
        differences = [i + self.base for i, (x, y) in enumerate(zip(actual, self.font)) if x != y]
        table_changes = [satfont.TABLE_LO + i // 2 for i in range(0, len(table), 2)
                         if not a <= i < b
                         and not any(lo <= i < hi for lo, hi in self.runtime_table_ranges)
                         and table[i:i + 2] != self.table[i:i + 2]]
        if differences or table_changes:
            self.failure = dict(frame=play.f, kind="FONT" if differences else "GLYPH_TABLE",
                                font_changed_bytes=len(differences),
                                font_range=[hex(min(differences)), hex(max(differences))] if differences else [],
                                glyph_codes=[hex(x) for x in table_changes])
            if self.previous:
                with open(os.path.join(self.out, "before_failure.state"), "wb") as fh:
                    fh.write(self.previous)
            raise StressFailure(json.dumps(self.failure))
        self.previous = state


def read_route(path):
    with open(path, encoding="utf-8") as fh:
        route = json.load(fh)
    return [x for x in route["actions"] if not any(k in x for k in ("save", "bsave", "mcard", "new"))]


def validate_minutes(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("minutes must be finite and nonnegative")
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--whole-game", action="store_true", help="Boot New Game, play all acts and capture the ending/credits for review")
    ap.add_argument("--live-control", action="store_true", help="Keep the native process at travel stalls and accept controller-only control.json commands")
    ap.add_argument("--start-save", default="B120_start_manual")
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--image", default=os.path.join(ROOT, "patched", "saturn", "Snatcher (Japan).cue"))
    ap.add_argument("--seed", type=int, default=88)
    ap.add_argument("--act1-minutes", type=validate_minutes, default=15)
    ap.add_argument("--finish-minutes", type=validate_minutes, default=45, help="Maximum time to reach Act 2")
    ap.add_argument("--act2-minutes", type=validate_minutes, default=120)
    ap.add_argument("--late-minutes", type=validate_minutes, default=30, help="Additional tour after BENSON, before the runaway")
    ap.add_argument("--act3-minutes", type=validate_minutes, default=15)
    ap.add_argument("--progress-minutes", type=validate_minutes, default=90, help="Hard deadline for each story stage, including the full Act 3 route")
    ap.add_argument("--every", type=int, default=120, help="Font/table check interval in frames")
    ap.add_argument("--min-transitions", type=int, default=10, help="Act 2 physical location changes")
    ap.add_argument("--min-options", type=int, default=40, help="Distinct options outside HQ")
    ap.add_argument("--min-locations", type=int, default=2, help="Distinct Act 2 locations outside HQ")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.every < 1 or min(a.finish_minutes, a.progress_minutes) <= 0 or min(a.min_transitions, a.min_options, a.min_locations) < 0 or not 0 <= a.slot <= 4:
        ap.error("invalid interval, finish time, or coverage threshold")
    out = os.path.abspath(a.out or os.path.join(WORK, "saturn", "stress", time.strftime("%Y%m%d_%H%M%S") + f"_s{a.seed}"))
    os.makedirs(out, exist_ok=True)
    if os.path.exists(os.path.join(out, "events.jsonl")):
        ap.error("--out already contains a stress run; choose a new directory")
    os.environ["EMU_SAVE_DIR"] = os.path.join(out, "emu")
    import satrun
    import satplay
    import satmem
    import satsave
    import satsave_check
    satplay.STATES = os.path.join(out, "states")
    satplay.PLAY = os.path.join(out, "captures")
    os.makedirs(satplay.STATES, exist_ok=True)
    table_path = os.path.splitext(a.image)[0] + ".pair_table.json"
    if os.path.exists(table_path):
        satplay.SAT_TABLE = table_path
    else:
        # The main build's work table, not the archived play image's table.
        satplay.SAT_TABLE = os.path.join(WORK, "saturn", "pair_table_sat.json")
    record = None if a.whole_game else satsave.entry_of(a.start_save)
    slot = None if a.whole_game else a.slot or record.get("slot") or 1
    os.makedirs(satsave.EMU_SAVES, exist_ok=True)
    source_save = None
    if record:
        source_save = satsave.read_image(record["path"])
        source_slot = next((x for x in satsave.parse_dir(source_save)
                            if x["name"] == f"SNATCHER_{slot:02d}"), None)
        if not source_slot:
            ap.error(f"starting save has no SNATCHER_{slot:02d} file")
        if source_slot.get("comment", "").replace(" ", "").upper() in {"ACT2", "ACT3"}:
            ap.error("starting save is from Act 2/3; choose a late Act 1 save")
        with open(os.path.join(satsave.EMU_SAVES, satsave.image_stem(a.image) + ".bkr"), "wb") as fh:
            fh.write(source_save)
    result = dict(status="running", seed=a.seed, save=None if a.whole_game else a.start_save, slot=slot,
                  whole_game=a.whole_game, opening_completed=False, ending_reached=False,
                  credits_review_required=a.whole_game,
                  image=os.path.abspath(a.image), core=satrun.CORE,
                  approximate_fps=FPS, requested_minutes=dict(act1=a.act1_minutes, oleen_soak=a.act2_minutes,
                  late_soak=a.late_minutes, act3=a.act3_minutes),
                  phase="boot", resets=0, restores=0, transitions=0, banks=[], phases=[],
                  act2_transitions=0, actions=0, distinct_options=0, distinct_act2_options=0, act2_reached=False,
                  act2_recap_seen=False, act3_reached=False, oleen_complete=False,
                  late_travel_reached=False, act2_completed=False)
    policy = MenuPolicy(a.seed)
    tour = LocationTour()
    coverage = OptionCoverage()
    history = collections.deque(maxlen=256)
    options = set()
    act2_options = set()
    outside_options = set()
    seen_bank = None
    phase_deadline = None
    watchdog_frame = 0
    new_coverage_frame = 0
    boot_complete = False
    controlling = False
    exploring_menu = False
    guided_bank = None
    journey_guard = None
    terminal_entered = None
    failed_choices = 0
    phase_start = 0
    logf = open(os.path.join(out, "log.txt"), "w", encoding="utf-8")
    eventf = open(os.path.join(out, "events.jsonl"), "w", encoding="utf-8")
    started = time.time()

    def log(message):
        logf.write(str(message) + "\n"); logf.flush()

    def event(kind, **data):
        if kind == "journey_action":
            result["current_action"] = data.get("action")
            result["journey_actions"] = result.get("journey_actions", 0) + 1
        item = dict(frame=play.f, phase=result["phase"], event=kind, **data)
        history.append(item)
        eventf.write(json.dumps(item, ensure_ascii=False) + "\n"); eventf.flush()

    def write_status():
        result.update(frame=play.f, wall_seconds=round(time.time() - started, 1),
                      pid=os.getpid(), bank=satplay.BANK_NAMES.get(play.bank),
                      cards=len(play.cards), menus=len(play.menus),
                      current_menu=play.labels_now(),
                      location=LOCATIONS.get(satplay.BANK_NAMES.get(play.bank)),
                      last_pick=play.last_pick,
                      last_card=play.cards[-1] if play.cards else None,
                      emulated_minutes=round(play.f / FPS / 60, 3),
                      phase_elapsed_minutes=round((play.f - phase_start) / FPS / 60, 3),
                      font_checks=watch.checks, movie_checks_skipped=watch.skipped,
                      distinct_options=len(options), distinct_act2_options=len(act2_options),
                      location_changes=tour.transitions, outside_locations=sorted(tour.outside),
                      outside_minutes=round(tour.outside_frames / FPS / 60, 3),
                      distinct_outside_options=len(outside_options),
                      untried_outside_options=len(coverage.missing_outside()),
                      pilot_problems=len(play.problems))
        temporary = os.path.join(out, "status.tmp")
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        os.replace(temporary, os.path.join(out, "status.json"))

    with contextlib.redirect_stdout(logf), contextlib.redirect_stderr(logf):
        watch = IntegrityWatch(a.image, out, a.every, log)
        result["main_sha1"] = hashlib.sha1(watch.exe).hexdigest()
        result["font_sha1"] = hashlib.sha1(watch.font).hexdigest()
        with open(satrun.CORE, "rb") as fh:
            result["core_sha1"] = hashlib.sha1(fh.read()).hexdigest()
        emu = satrun.SaturnEmu(); emu.load(a.image)
        play = satplay.Play(emu, out, log, a.image, autosave=False)
        guard_gameplay_tracking(play, watch.exe)
        import satjourney
        ending = satjourney.EndingObserver() if a.whole_game else None
        player_watch = PlayerProgressWatch()
        original_run = play.run

        def no_restore(*args, **kwargs):
            result["restores"] += 1
            raise StressFailure("Pilot attempted a savestate restore; continuous-session history would be lost")

        emu.restore = no_restore

        def coverage_satisfied():
            return (tour.transitions >= a.min_transitions and len(outside_options) >= a.min_options
                    and len(tour.outside) >= a.min_locations
                    and tour.outside_frames >= round((a.act2_minutes + a.late_minutes) * 60 * FPS) // 2
                    and not coverage.missing_outside())

        def tick(frame):
            nonlocal seen_bank, watchdog_frame, new_coverage_frame, terminal_entered
            if boot_complete:
                watch.inspect(play)
                if ending:
                    ending.observe(play.cards)
                if frame % 120 == 0:
                    movie = play.mem.read(0x060B0600, 32) != watch.exe[0x600:0x620]
                    suspended = (movie or result["phase"] in SOAK_PHASES
                                 or result["phase"] == "act1_roam"
                                 or (ending is not None and ending.frame is not None))
                    player_watch.observe(frame, player_state(play), suspended)
                    result["player_progress_age_minutes"] = round((frame - player_watch.last_new) / FPS / 60, 3)
                if result["phase"] in SOAK_PHASES:
                    previous_location = tour.location
                    tour.observe(satplay.BANK_NAMES.get(play.bank), frame)
                    if tour.location != previous_location:
                        event("location", location=tour.location)
            if exploring_menu and keyboard_open(play.mem):
                raise PanelOpen()
            bank = satplay.BANK_NAMES.get(play.bank)
            if bank and bank != seen_bank:
                if bank in TERMINALS and terminal_entered is None:
                    terminal_entered = frame
                elif bank not in TERMINALS:
                    terminal_entered = None
                if seen_bank and boot_complete:
                    result["transitions"] += 1
                    new_coverage_frame = frame
                    if result["phase"] in SOAK_PHASES:
                        result["act2_transitions"] += 1
                seen_bank = bank
                if bank not in result["banks"]:
                    result["banks"].append(bank)
                    new_coverage_frame = frame
                if bank == "B140":
                    result["act2_recap_seen"] = True
                if act2_ready(bank):
                    result["act2_reached"] = True
                if bank in {"B240", "B250", "B260"}:
                    result["act3_reached"] = True
                    if result["phase"] in SOAK_PHASES:
                        raise StressFailure("Act 3 reached before the requested Act 2 soak finished")
                if isinstance(play.fight_state, list):
                    pass  # explicit stage aim sequences span resource-bank changes
                elif bank == "B120":
                    play.fight_state = "head"
                elif bank == "B230":
                    play.fight_state = "corners"
                else:
                    play.fight_state = "body"
                event("bank", bank=bank)
            if guided_bank and bank and bank != guided_bank:
                raise GuideDone()
            if journey_guard and journey_guard.observe(bank):
                event("journey_endpoint", bank=bank)
                raise GuideDone()
            if boot_complete and any(x["kind"] in SERIOUS for x in play.problems[-3:]):
                raise StressFailure("Serious pilot text/rendering error; see problems.txt")
            if frame >= watchdog_frame:
                watchdog_frame = frame + 3600
                write_status()
                emu.image().save(os.path.join(out, f"heartbeat_{frame:08d}.png"))
                if os.path.exists(os.path.join(out, "stop.request")):
                    raise StressFailure("Stress run stopped for player/route inspection")
            if not controlling and phase_deadline is not None and frame >= phase_deadline:
                raise StageEnd()

        def run(n=1, hook=None):
            guarded_run(original_run, tick, n, hook)

        play.run = run

        def start_phase(name, frames):
            nonlocal phase_deadline, phase_start
            result["phase"] = name
            phase_start = play.f
            player_watch.reset(play.f)
            phase_deadline = play.f + frames
            bank = satplay.BANK_NAMES.get(play.bank)
            play.fight_state = "head" if bank == "B120" else "corners" if bank == "B230" else "body"
            event("phase_start", deadline=phase_deadline)
            write_status()

        def end_phase():
            result["phases"].append(dict(name=result["phase"], frames=play.f - phase_start,
                                         minutes=round((play.f - phase_start) / FPS / 60, 3)))
            event("phase_end")
            with open(os.path.join(out, f"phase_{result['phase']}.state"), "wb") as fh:
                fh.write(emu.state())
            emu.image().save(os.path.join(out, f"phase_{result['phase']}.png"))

        def explore_step():
            nonlocal new_coverage_frame, failed_choices
            settle_tour_arrival(play)
            if satplay.BANK_NAMES.get(play.bank) == "B140":
                advance_transition(play)
                return
            # wait_menu advances dialogue and fights closed-loop. The hard
            # per-frame deadline still applies when its patience resets.
            got = play.wait_menu(patience=3000)
            if got is None:
                play.press("b"); play.run(30)
                event("cancel_no_menu")
                return
            labels = got[3]
            bank = satplay.BANK_NAMES.get(play.bank)
            if bank == "B150" and labels == ["Save", "Don't save"]:
                advance_transition(play)
                return
            room = play.mem.u16(satmem.CTX + 0x5D8)
            if result["phase"] in SOAK_PHASES:
                coverage.offer(bank, room, labels)
            escaping = (failed_choices >= 3 or
                        (terminal_entered is not None and play.f - terminal_entered >= TERMINAL_VISIT_FRAMES))
            touring, tour_choice = tour.choose(bank, play.f, labels, allow_hq=result["phase"] != "late_soak") if result["phase"] in SOAK_PHASES else (False, None)
            blocked = tour.blocked_departures(play.f) if result["phase"] in SOAK_PHASES else ()
            choice = tour_choice if touring else policy.choose(bank, room, labels, play.is_top(labels), result["phase"], escaping, blocked)
            if choice is None:
                event("cancel", bank=bank, labels=labels)
                play.press("b"); play.run(30)
            else:
                key = (bank, room, tuple(labels), labels[choice])
                event("choice", bank=bank, room=room, labels=labels, choice=choice, touring=touring)
                if result["phase"] in SOAK_PHASES:
                    coverage.record(bank, room, labels, choice, False)
                ok, _ = play.pick(choice)
                if result["phase"] in SOAK_PHASES:
                    coverage.record(bank, room, labels, choice, ok, attempt=False)
                failed_choices = 0 if ok else failed_choices + 1
                result["actions"] += 1
                if ok and key not in options:
                    options.add(key); new_coverage_frame = play.f
                if ok and result["phase"] in SOAK_PHASES:
                    act2_options.add(key)
                    if LOCATIONS.get(bank) not in {None, "HQ"}:
                        outside_options.add(key)
                event("choice_result", ok=ok)
            if play.f - new_coverage_frame > 15 * 60 * FPS:
                raise StressFailure("No scene change or new option in 15 emulated minutes; insufficient roaming")

        def live_control(reason):
            nonlocal controlling, failed_choices, exploring_menu
            controlling = True
            exploring_menu = False
            tour.departing_since = None
            play.emu.held = set()
            play.held_until = -1
            result["status"] = "awaiting_native_control"
            result["control_reason"] = reason
            event("native_control_start", reason=reason)
            emu.image().save(os.path.join(out, f"control_{play.f:08d}.png"))
            write_status()
            path = os.path.join(out, "control.json")
            try:
                while True:
                    if os.path.exists(os.path.join(out, "stop.request")):
                        raise StressFailure("Stress run stopped during native control")
                    if os.path.exists(path):
                        try:
                            with open(path, encoding="utf-8") as fh:
                                command = json.load(fh)
                            os.replace(path, os.path.join(out, f"control_command_{time.time_ns()}.json"))
                            event("native_control_command", command=command)
                            resume = native_control_actions(play, command)
                            emu.image().save(os.path.join(out, f"control_result_{play.f:08d}.png"))
                            result.pop("control_error", None)
                            write_status()
                            if resume:
                                result["status"] = "running"
                                result.pop("control_reason", None)
                                failed_choices = 0
                                event("native_control_end")
                                write_status()
                                return
                        except (ValueError, OSError) as exc:
                            result["control_error"] = str(exc)
                            event("native_control_error", reason=str(exc))
                            write_status()
                    time.sleep(1)
                    write_status()
            finally:
                controlling = False

        def explore():
            nonlocal exploring_menu, failed_choices
            try:
                if a.live_control and os.path.exists(os.path.join(out, "control.json")):
                    live_control("Native controller command requested")
                exploring_menu = True
                explore_step()
            except TravelStall as exc:
                if not a.live_control:
                    raise
                live_control(str(exc))
            except PanelOpen:
                exploring_menu = False
                event("keyboard_exit", button="start")
                leave_keyboard(play)
                failed_choices = 3  # leave the search menu next, rather than reopening it
            finally:
                exploring_menu = False

        def guided(actions, bank_lock=None):
            nonlocal new_coverage_frame, guided_bank
            guided_bank = bank_lock
            try:
                for action in actions:
                    if result["act2_reached"] or (bank_lock and satplay.BANK_NAMES.get(play.bank) != bank_lock):
                        break
                    event("guided_action", action=action)
                    satplay.run_action(action, play, phase_deadline, log)
                    new_coverage_frame = play.f
            except GuideDone:
                new_coverage_frame = play.f
                event("guide_bank_changed", bank=satplay.BANK_NAMES.get(play.bank))
            finally:
                guided_bank = None

        try:
            if a.whole_game:
                start_phase("new_game", round(a.progress_minutes * 60 * FPS))
                try:
                    satplay.run_action({"new": True}, play, phase_deadline, log)
                    satjourney.verify_endpoint(play, ["B010"])
                except StageEnd:
                    raise StressFailure("New Game did not reach the opening scene within its budget")
                boot_complete = True
                watch.inspect(play, force=True)
                end_phase()
                for stage in satjourney.opening_stages():
                    fights_before = play.fights
                    journey_guard = satjourney.EndpointGuard(stage)
                    start_phase(stage["name"], round(a.progress_minutes * 60 * FPS))
                    try:
                        for action in stage["actions"]:
                            satjourney.run_action(action, play, phase_deadline, event, log)
                        satjourney.verify_stage(play, stage, fights_before)
                    except GuideDone:
                        satjourney.verify_stage(play, stage, fights_before)
                    except StageEnd:
                        raise StressFailure(f"Story stage {stage['name']} exhausted its progression budget")
                    journey_guard = None
                    if stage.get("milestone"):
                        result[stage["milestone"]] = True
                        event("milestone", name=stage["milestone"])
                    end_phase()
            else:
                if not satsave_check.continue_from_title(play, log):
                    raise StressFailure("CONTINUE did not open")
                satsave_check.load_file(play, slot, log)
            # A recap save may start on voice/cards; do not require a live
            # verb menu before observing it. The default save is late Act 1.
            for _ in range(150):
                play.run(30)
                if play.bank and play.bank != 21:
                    break
            else:
                raise StressFailure("Scene save did not load")
            wanted = (record.get("slot_banks") or {}).get(str(slot), record.get("bank")) if record else "B120"
            if wanted and satplay.BANK_NAMES.get(play.bank) != wanted:
                raise StressFailure(f"Save loaded {satplay.BANK_NAMES.get(play.bank)}, expected {wanted}")
            if result["act2_reached"] or play.bank > satplay.BANK_OF["B140"]:
                raise StressFailure("Starting save must be in Act 1")
            boot_complete = True
            watch.inspect(play, force=True)
            start_phase("act1_roam", round(a.act1_minutes * 60 * FPS))
            try:
                while not result["act2_reached"] and play.f < phase_deadline:
                    explore()
            except StageEnd:
                pass
            end_phase()
            start_phase("finish_act1", round(a.finish_minutes * 60 * FPS))
            try:
                while not result["act2_reached"]:
                    if play.bank == satplay.BANK_OF["B120"]:
                        guided(read_route(os.path.join(HERE, "routes", "B120_finish.json")), bank_lock="B120")
                    elif play.bank == satplay.BANK_OF["B080"]:
                        guided([{"path": ["Move", "Front|Front desk"], "optional": True, "patience": 600},
                                {"path": ["Move", "Board Tricycle"], "optional": True, "patience": 600},
                                {"path": ["Board Tricycle"], "optional": True, "patience": 600},
                                {"path": ["Freddy|Freddy's"], "optional": True, "patience": 600},
                                {"path": ["Exit Tricycle"], "optional": True, "patience": 600}])
                    elif play.bank == satplay.BANK_OF["B0A0"]:
                        guided([{"path": ["Freddy|Freddy's"], "optional": True, "patience": 600},
                                {"path": ["Exit Tricycle"], "optional": True, "patience": 600}])
                    else:
                        explore()
                    if not result["act2_reached"]:
                        explore()
                import satjourney
                satjourney.wait_scene_menu(play, "HQ")
            except StageEnd:
                raise StressFailure("Act 1 progression budget expired before reaching Act 2")
            end_phase()
            for stage in satjourney.stages(whole_game=a.whole_game):
                fights_before = play.fights
                journey_guard = satjourney.EndpointGuard(stage)
                minutes = (a.act2_minutes if stage.get("soak") == "oleen" else
                           a.late_minutes if stage.get("soak") == "late" else
                           a.act3_minutes if stage.get("act3") and not a.whole_game else a.progress_minutes)
                # Keep the latest free travel point until real outside coverage
                # is established, with a finite additional exploration budget.
                extra_minutes = 120 if stage.get("soak") == "late" else 0
                start_phase(stage["name"], round((minutes + extra_minutes) * 60 * FPS))
                minimum_end = phase_start + round(minutes * 60 * FPS)
                # Stage transitions do not reset the core or load any save.
                new_coverage_frame = play.f
                tour.departing_since = None
                tour.since = play.f
                try:
                    if stage.get("soak"):
                        extended = False
                        while play.f < minimum_end or (stage.get("soak") == "late" and not coverage_satisfied()):
                            if play.f >= minimum_end and not extended:
                                event("coverage_extension", maximum_extra_minutes=extra_minutes,
                                      outside_minutes=tour.outside_frames / FPS / 60,
                                      untried_outside_options=len(coverage.missing_outside()))
                                extended = True
                            explore()
                    else:
                        for action in stage["actions"]:
                            if play.f >= phase_deadline:
                                raise StageEnd()
                            satjourney.run_action(action, play, phase_deadline, event, log)
                            new_coverage_frame = play.f
                        if stage.get("finish_game"):
                            while ending.frame is None:
                                advance_transition(play)
                            # Final dialogue is evidence of story completion; retain a
                            # natural ten-minute tail and screenshots to inspect credits.
                            while play.f - ending.frame < 10 * 60 * FPS:
                                play.run(30)
                            result["ending_reached"] = True
                            result["ending_cue"] = ending.cue_id
                            result["ending_frame"] = ending.frame
                            emu.image().save(os.path.join(out, "ending_credits.png"))
                        elif stage.get("act3"):
                            while play.f < phase_deadline:
                                advance_transition(play)
                except GuideDone:
                    pass  # a story exit interrupts the old scene's sweep immediately
                except StageEnd:
                    if stage.get("finish_game") or (not stage.get("soak") and not stage.get("act3")):
                        raise StressFailure(f"Story stage {stage['name']} exhausted its progression budget")
                satjourney.verify_stage(play, stage, fights_before)
                journey_guard = None
                if stage.get("milestone"):
                    result[stage["milestone"]] = True
                    event("milestone", name=stage["milestone"])
                end_phase()
            phase_deadline = None
            watch.inspect(play, force=True)
            if (not coverage_satisfied()
                    or not all(result[x] for x in ("oleen_complete", "late_travel_reached", "act2_completed", "act3_reached"))):
                result["status"] = "insufficient_coverage"
            else:
                if a.whole_game and not (result["opening_completed"] and result["ending_reached"]):
                    raise StressFailure("Full-game run did not establish both opening and ending milestones")
                result["status"] = "ending_review_required" if a.whole_game else "passed"
        except KeyboardInterrupt:
            result["status"] = "interrupted"
        except (StressFailure, satplay.Wedged) as exc:
            result["status"] = "failed"
            result["failure"] = watch.failure or dict(frame=play.f, reason=str(exc) or type(exc).__name__)
        except Exception as exc:
            result["status"] = "error"
            result["failure"] = dict(frame=play.f, reason=f"{type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
        finally:
            phase_deadline = None
            state_name = "final.state" if result["status"] in {"passed", "ending_review_required"} else "failure.state"
            if result["status"] == "failed" and watch.previous and not os.path.exists(os.path.join(out, "before_failure.state")):
                with open(os.path.join(out, "before_failure.state"), "wb") as fh:
                    fh.write(watch.previous)
            with open(os.path.join(out, state_name), "wb") as fh:
                fh.write(emu.state())
            emu.image().save(os.path.join(out, "final.png"))
            with open(os.path.join(out, "last_actions.json"), "w", encoding="utf-8") as fh:
                json.dump(list(history), fh, indent=1, ensure_ascii=False)
            with open(os.path.join(out, "menu_coverage.json"), "w", encoding="utf-8") as fh:
                json.dump(list(coverage.items.values()), fh, indent=1, ensure_ascii=False)
            result["source_save_unchanged"] = satsave.read_image(record["path"]) == source_save if record else None
            play.finish(started)
            write_status()
            log(json.dumps(result))
    logf.close(); eventf.close()
    print(json.dumps(result, indent=2))
    print("Artifacts: " + out)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
