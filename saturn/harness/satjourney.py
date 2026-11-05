"""Act 2 stress journey: story prerequisites, two touring windows, finale.

All actions use the live pad/menu/puzzle interfaces. Shared PS1 routes
provide the story order; Saturn routes provide its light, maze and fights.
Every story stage has a required endpoint; optional paths cannot stand in
for reaching it. Native validation is still required for each stage.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in
               ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]


def route(path, start=0):
    import json
    # Slice before removing positional bookmarks so shared route offsets
    # remain stable. Checkpoints never write game saves in a stress session.
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        actions = json.load(fh)["actions"][start:]
    actions = [dict(x) for x in actions if not any(k in x for k in ("save", "bsave", "mcard", "new"))]
    for action in actions:
        if "path" in action:
            action["path"] = [x.replace("Oleen Hospital", "Oleen Hospital|Oleen Hosp.")
                              .replace("Illegal hospital", "Illegal hospital|Illegal hosp.|Black clinic") for x in action["path"]]
            if path.endswith("B1C0.json") and action["path"] == ["Move", "Study|Back to study"]:
                # The backyard exposes this as a root command on Saturn.
                action["path"][0] = "Move|Back to study"
    if path.endswith("B190.json"):
        # Looking around introduces Santa; only a subsequent look/check
        # exposes Napoleon. A single sweep snapshots the earlier menu.
        actions[0]["rounds"] = 2
        actions.insert(1, dict(path=["Look", "Santa"], optional=True, reps=2, patience=600))
        actions.insert(3, dict(path=["Check Santa"], optional=True, reps=2, patience=600))
    if path.endswith("B1E0.json"):
        actions[0]["rounds"] = 2  # the first inspection exposes the door controls
        for action in actions:
            if "sweep" in action:
                action["avoid"] = list(dict.fromkeys(action.get("avoid", []) + ["Board Tricycle"]))
            if action.get("path") == ["Move", "Dr 3|Door 3"]:
                action.update(optional=False, strict=True)
        actions.insert(3, dict(path=["Use Metal Gear", "Turn on light"],
                               optional=False, strict=True, patience=1800))
    if path.endswith("B160.json"):
        for action in actions:
            if "sweep" in action and "Pull the lever" in action["sweep"]:
                # The runaway choices are a flat menu. Its next menu is
                # another set of commands, not children of the last pick.
                action["depth_limit"] = 1
    if path.endswith("B1E0_light.json"):
        lamp_end = next(i for i, a in enumerate(actions) if a.get("light_to") == [82, 66])
        stairs_start = next(i for i, a in enumerate(actions) if "Peek" in a.get("sweep", []))
        actions = actions[:lamp_end] + [dict(queen_stairs=True)] + actions[stairs_start:]
    if path.endswith("B200.json"):
        for action in actions:
            if action.get("sweep") == ["Press switch", "Use switches", "Press button"]:
                # These are aliases for one toggle command, not three
                # independent verbs. Sweeping twice closes the opened doors.
                action["sweep"] = ["Press button|Press switch|Use switches"]
            if action.get("path") in [["Move", "Door 1"], ["Move", "Door 2"], ["Move", "Door 3"]]:
                action.update(optional=False, strict=True)
            if action.get("idle", 0) >= 18000:
                patience = action.pop("idle")
                action.update(wait_menu=True, patience=patience)
        reconstruct = next(i for i, a in enumerate(actions)
                           if a.get("path") == ["Reconstruct|Investigate", "Reconstruct|Remains"])
        actions[reconstruct:reconstruct + 2] = [
            dict(path=["Investigate", "Identity"], strict=True, reps=2, patience=1800),
            dict(path=["Reconstruct"], strict=True, patience=1800)]
    if path.endswith("B240.json"):
        for action in actions:
            if action.get("idle", 0) >= 18000:
                action["ending_wait"] = action.pop("idle")
    if path.endswith("B1E0_call.json"):
        # Leave both hospital rooms and settle the street menu after the call.
        actions = [
            dict(path=["Go out|Exit Tricycle"], optional=True, patience=600),
            dict(path=["Move", "Go out"], optional=True, patience=600),
            dict(path=["Use Metal Gear", "Videophone"], strict=True, patience=1800),
            dict(path=["Call"], strict=True, patience=1800), dict(dial="391009"),
            dict(menu_settle=True),
            dict(path=["Show item", "Chart|Medical chart"], strict=True, reps=2, patience=1800),
            dict(path=["Hang up"], strict=True, patience=1800), dict(menu_settle=True),
            dict(path=["Call"], strict=True, patience=1800), dict(dial="395644"),
            dict(menu_settle=True),
            dict(path=["Don't call"], strict=True, patience=1800),
            dict(scene_menu="Queen Hospital"),
            dict(path=["Move", "Board Tricycle"], strict=True, patience=1800),
            dict(path=["Outer Heaven"], strict=True, patience=1800),
            dict(path=["Exit Tricycle"], strict=True, patience=1800)]
    for action in actions:
        for field in ("sweep", "each"):
            if field in action:
                action[field] = [x.replace("Press switch", "Press switch|Press button|Use switches") for x in action[field]]
    return actions


def path(*labels, optional=False, reps=1, strict=False):
    action = dict(path=list(labels), optional=optional, reps=reps, patience=1800)
    if strict:
        action["strict"] = True
    return action


def opening_stages():
    """Continuous New Game -> late Act 1; no bookmark loads or saves."""
    return [
        dict(name="hq_introduction", expected=["B020"], actions=
             route("saturn/harness/routes/B010.json")[:5] +
             route("saturn/harness/routes/B010_leave.json")),
        dict(name="factory_ruins", expected=["B080"], actions=route("saturn/harness/routes/B020.json")),
        dict(name="act1_hq_and_napoleon", expected=["B060", "B080"], actions=
             route("ps1/harness/routes/B080.json") + [dict(napoleon_password=True),
             dict(sweep=["Talk", "Ask", "Show item"], rounds=2, avoid=["Hang up"]),
             path("Hang up", optional=True), path("Don't call", optional=True)]),
        dict(name="act1_home", expected=["B0B0"], actions=[dict(travel="Home")] +
             route("ps1/harness/routes/B0B0.json")[:8] +
             [path("Hang up", optional=True), path("Don't call", optional=True)]),
        dict(name="act1_gibson", expected=["B0C0"], actions=[dict(travel="Gibson's house")] +
             route("ps1/harness/routes/B0C0.json")),
        dict(name="act1_altamira", expected=["B0D0"], actions=[dict(travel="Altamira")] +
             route("ps1/harness/routes/B0D0_napoleon.json")[:14]),
        dict(name="act1_joy_address", expected=["B0D0"], actions=[
             path("Use Metal Gear", "Videophone"), path("Call"),
             dict(dial="691170"), path("Ask", "Store location"),
             path("Hang up", optional=True), path("Don't call", optional=True)]),
        dict(name="act1_joy_division", expected=["B100"], actions=[dict(travel="Joy Division")] +
             route("saturn/harness/routes/B0E0.json", 7)[:1] +
             route("ps1/harness/routes/B0E0_shop.json")),
        dict(name="act1_outer_heaven", expected=["B100"], actions=[
             path("End questions", optional=True), path("Call", "Dancer"),
             path("Item", "Show", "Photo", "Gibson's photo", reps=2),
             path("Ask", "About Gibson", reps=2),
             path("Ask", "About that man", reps=2)] + [
             path("Ask", "About that man", "His features", feature)
             for feature in ("Face", "Eyes", "Nose", "Mouth", "Hair")
             ] + [path("Ask", "About that man", "His age", optional=True),
             path("Ask", "About that man", "Change subject", optional=True),
             path("End questions", optional=True)]),
        dict(name="act1_montage", expected=["B030", "B080"], actions=[dict(travel="HQ"),
             path("Move", "Computer room", optional=True), path("Use Gaudi", "Use card"),
             path("Create montage"), dict(montage=True)]),
        dict(name="act1_ivan", expected=["B0A0"], min_fights=1, actions=[dict(travel="Ivan's apartment"),
             dict(fight="cell4"), path("Find Ivan"), dict(sweep=["Look"], rounds=2),
             path("Ask", "About Ivan"),
             path("Item", "Show", "Photo", "Montage photo", strict=True), path("Ask", "About Ivan", reps=2),
             path("Move", "Room 301", strict=True)] + route("ps1/harness/routes/B110_census.json")),
        dict(name="act1_freddy_arrival", milestone="opening_completed", expected=["B120"],
             actions=[dict(travel="Freddy's apartment")]),
    ]


class EndingObserver:
    """Require the final enabled ending cue, not just entry into Act 3."""
    def __init__(self):
        import json
        with open(os.path.join(ROOT, "saturn/translation/subs_B260.json"), encoding="utf-8") as fh:
            cues = json.load(fh)["cues"]
        self.cue_id = next(cue["id"] for cue in reversed(cues) if cue.get("enabled"))
        self.frame = None
        self.checked = 0

    def observe(self, cards):
        for card in cards[self.checked:]:
            if card.get("bank") == "B260" and card.get("src") == "cue " + self.cue_id:
                self.frame = card["frame"]
        self.checked = len(cards)


def solve_montage(play):
    """Test the two choices per feature suggested by Gaudi, using live pads.

    Gaudi gives a specific correction only when one feature is wrong.
    General portrait feedback needs the bounded set of hinted combinations.
    A failed match clears the portrait, so enter all five parts every time.
    """
    from satstress import StressFailure
    features = ["Outline", "Eyes", "Nose", "Mouth", "Hair"]
    hints = ["face shape", "eyes", "nose", "mouth", "hairstyle"]
    candidates = [(2, 3), (3, 6), (1, 3), (2, 3), (2, 3)]
    chosen = [values[0] for values in candidates]
    def select(i):
        target = f"{features[i]} {chosen[i]}"
        if not play.do_path([features[i], target], False, 1800):
            raise StressFailure(f"Montage feature {features[i]} could not be selected")
        if getattr(play, "last_pick", None) == target:
            if not hasattr(play, "montage_features"):
                play.montage_features = {}
            play.montage_features[features[i]] = target
    attempted = set()
    for _ in range(32):
        attempted.add(tuple(chosen))
        for i in range(len(features)):
            select(i)
        before = len(play.cards)
        if not play.do_path(["Match"], False, 3000):
            raise StressFailure("Gaudi did not offer the montage match command")
        play.wait_menu(patience=6000)
        reply = " ".join(" ".join(card["rows"]) for card in play.cards[before:]).lower()
        if "two people match" in reply or "finished printing" in reply:
            return
        wrong = next((i for i, hint in enumerate(hints) if f"{hint} be wrong" in reply), None)
        if wrong is not None:
            other = next(value for value in candidates[wrong] if value != chosen[wrong])
            following = list(chosen); following[wrong] = other
        elif "portrait be wrong" in reply:
            following = next((
                [values[((index ^ (index >> 1)) >> i) & 1] for i, values in enumerate(candidates)]
                for index in range(32)
                if tuple(values[((index ^ (index >> 1)) >> i) & 1]
                         for i, values in enumerate(candidates)) not in attempted), None)
        else:
            following = None
        if following is None or tuple(following) in attempted:
            raise StressFailure("Gaudi montage feedback was missing or exhausted its feature choices")
        chosen = following
    raise StressFailure("Montage did not match within its bounded feature search")


def queen_lamp_bounds(play):
    """Measure the lamp's reachable edges through the pad, without RAM writes."""
    from satstress import StressFailure
    corners = []
    for moves in ([['left', 400], ['up', 400]], [['right', 400], ['down', 400]]):
        play.wait_menu(patience=1800)
        play.run(120)
        play.light(moves)
        corners.append(play.light_xy())
    (left, top), (right, bottom) = corners
    if right - left < 32 or bottom - top < 32:
        raise StressFailure(f"Queen Hospital lamp did not move across its bounds: {corners}")
    return left, top, right, bottom


def queen_stairs(play):
    """Stop manipulating the lamp as soon as the native stairs menu appears."""
    from satstress import StressFailure
    for point in [(82, 66), (84, 66), (82, 68), (84, 68), (80, 66), (82, 64), (86, 66)]:
        got = play.wait_menu(patience=8000)
        if got and any(play.find(got[3], label) is not None for label in ("Peek", "Stairs", "Go downstairs")):
            return
        if not play.light_to(*point):
            raise StressFailure(f"Queen Hospital lamp could not reach {point}")
        play.do_path(["Look"], patience=1800)
        play.do_path(["Investigate"], patience=1800)
        got = play.wait_menu(patience=8000)
        if got and play.find(got[3], "Peek") is not None:
            return
    raise StressFailure("Queen Hospital vase did not expose the hidden stairs")


def queen_evidence(play):
    """Collect the matches, cathedral photo, and medical record through the pad."""
    from satstress import StressFailure
    left, top, right, bottom = queen_lamp_bounds(play)
    points = [(max(left, min(right, x)), max(top, min(bottom, y)))
              for x, y in [(144, 32), (168, 80), (144, 56), (144, 64), (192, 40),
                           (192, 56), (80, 40), (80, 32), (192, 48)]] + [
        (x, y) for y in range(top, bottom + 1, 16) for x in range(left, right + 1, 16)]
    seen = set()
    points = [(x, y, True) for x, y in points]
    for point_index, (x, y, coarse) in enumerate(points):
        if (x, y) in seen:
            continue
        seen.add((x, y))
        play.wait_menu(patience=1800)
        if not play.light_to(x, y):
            raise StressFailure(f"Queen Hospital lamp could not reach {(x, y)}")
        before = len(play.cards)
        play.sweep(["Look", "Investigate"], 2, ["Go out", "Turn on light", "Save"])
        feedback = " ".join(" ".join(card["rows"]) for card in play.cards[before:]).lower()
        # Saturn requires the complete object inside the beam. Refine near
        # native partial hits immediately, without recursively expanding them.
        if coarse and ("isn't fully inside" in feedback or "off target" in feedback):
            points[point_index + 1:point_index + 1] = [
                (max(left, min(right, x + dx)), max(top, min(bottom, y + dy)), False)
                for dx, dy in [(0, -8), (0, 8), (-8, 0), (8, 0),
                               (-8, -8), (8, -8), (-8, 8), (8, 8),
                               (0, -4), (0, 4), (-4, 0), (4, 0)]]
        # The room's initial menu census may already have collected a clue.
        # Keep native evidence from this visit instead of requiring it twice.
        text = " ".join(" ".join(card["rows"]) for card in play.cards
                        if card.get("bank", "B1E0") == "B1E0").lower()
        if ("take the matches" in text and "basil" in text and "cathedral" in text
                and ("moscow? what's the connection" in text or "stored this photograph" in text)
                and "keep this piece of the medical record" in text):
            return
    raise StressFailure("Queen Hospital scan did not obtain matches, cathedral photo, and medical record")


def stages(whole_game=False):
    return [
        dict(name="reach_oleen", milestone="oleen_complete", expected=["B170"], actions=[
            path("Move", "Mechanic room"),
            dict(sweep=["Look", "Investigate", "Ask", "Talk"], rounds=2, avoid=["Go out"]),
            path("Use Metal Gear", "Videophone"), path("Call", optional=True),
            dict(dial="395644"), dict(napoleon_password=True),
            path("Hang up", optional=True), path("Don't call", optional=True),
            dict(travel="Altamira"),
        ] + route("ps1/harness/routes/B190.json") + [
            dict(travel="Oleen Hospital"),
        ] + route("ps1/harness/routes/B1B0.json", 3)),
        dict(name="oleen_soak", soak="oleen"),
        dict(name="jamie_and_gibson", expected=["B1C0"], actions=[
            dict(travel="Home"), path("Move", "Go inside", optional=True),
            path("Use Metal Gear", "Videophone"), path("Call", optional=True),
            dict(dial="393444"), path("Hang up", optional=True), path("Call", optional=True),
            dict(dial="391009"), dict(sweep=["Ask", "Talk"], rounds=2),
            path("Hang up", optional=True), path("Don't call", optional=True),
            dict(travel="Gibson's house"),
        ]),
        dict(name="gibson_search", expected=["B170", "B150"], actions=route("ps1/harness/routes/B1C0.json", 3) + [
             path("Move", "Living room", strict=True),
             path("Call", "Catherine"), path("Call", "Alice"),
             path("Move", "Study", strict=True), dict(wait_menu=True, patience=12000)]),
        dict(name="catherine_and_queen", expected=["B1E0"], actions=[
            dict(travel="HQ"), path("Move", "Chief's room", strict=True),
            path("Find Catherine", reps=3),
            dict(sweep=["Find Catherine", "Look", "Investigate"], rounds=3),
            dict(travel="Altamira"), path("Find Catherine", reps=3),
            dict(sweep=["Find Catherine", "Look", "Investigate"], rounds=3),
            dict(travel="Home"),
        ] + route("ps1/harness/routes/B1A0.json", 11) + [
            path("Ask", "Hospital list", reps=2),
            path("Investigate", "Hospital list", strict=True),
            path("Check the list|Search list"), dict(type="QUEEN"),
        ] + route("ps1/harness/routes/B1A0_post.json")),
        dict(name="first_queen_and_outer_heaven", expected=["B1D0"], actions=[
             dict(sweep=["Look", "Investigate"], rounds=2),
             path("Look", "Door", strict=True), path("Investigate", "Door", strict=True),
             path("Move", "Go inside", strict=True)] +
             route("ps1/harness/routes/B1E0.json") + [dict(queen_evidence=True)] +
             route("ps1/harness/routes/B1E0_call.json")),
        dict(name="benson", milestone="late_travel_reached", expected=["B170"],
             required_cue="cue B1D0_f9_0",
             actions=route("ps1/harness/routes/B1D0.json", 4)),
        dict(name="late_soak", soak="late"),
        dict(name="hq_and_runaway", expected=["B1E0"], actions=[dict(travel="HQ")] +
             route("ps1/harness/routes/B160.json", 2)),
        dict(name="queen_basement", expected=["B200"], actions=
             route("saturn/harness/routes/B1E0_randam.json") + route("saturn/harness/routes/B1E0_light.json")),
        dict(name="basement", expected=["B220"], actions=route("saturn/harness/routes/B200.json")),
        dict(name="tunnel_and_taxi", expected=["B230"], actions=route("saturn/harness/routes/B220.json")),
        dict(name="act2_finale", milestone="act2_completed", expected=["B240", "B250"],
             actions=route("saturn/harness/routes/B230.json")),
        dict(name="act3_finish" if whole_game else "act3_continue", act3=True,
             finish_game=whole_game, actions=route("saturn/harness/routes/B240.json")),
    ]


class EndpointGuard:
    """Stop a sweep when its story exit loads the next resource bank."""
    ORIGINS = {"hq_introduction": "B010", "factory_ruins": "B020", "act1_ivan": "B110",
               "reach_oleen": "B1B0", "gibson_search": "B1C0",
               "catherine_and_queen": "B1A0", "first_queen_and_outer_heaven": "B1E0",
               "benson": "B1D0",
               "hq_and_runaway": "B1F0", "queen_basement": "B1E0",
               "basement": "B200", "tunnel_and_taxi": "B220", "act2_finale": "B230"}

    def __init__(self, stage):
        self.origin = self.ORIGINS.get(stage["name"])
        self.expected = stage.get("expected", [])
        self.armed = False

    def observe(self, bank):
        if self.origin is None:
            return False
        if bank == self.origin:
            self.armed = True
        if self.armed and bank in self.expected:
            self.armed = False
            return True
        return False


def type_text(play, text):
    import satplay
    import satkeys
    from satstress import keyboard_open, StressFailure, PanelOpen
    waiting_since = play.f
    def panel(frame):
        if keyboard_open(play.mem):
            raise PanelOpen()
        if play.f - waiting_since >= 6000:
            raise StressFailure(f"Keyboard did not open for {text!r}")
    while play.f - waiting_since < 6000:
        if keyboard_open(play.mem):
            break
        try:
            play.wait_menu(patience=600, hook=panel)
            play.run(30, panel)
        except PanelOpen:
            break
    else:
        raise StressFailure(f"Keyboard did not open for {text!r}")
    # Clear an existing answer through the real backspace input.
    for _ in range(14):
        if play.mem.u8(satkeys.TYPED) == 0:
            break
        play.press("b"); play.run(24)
    grid = satkeys.grid_cells()
    for char in text.upper():
        if char not in grid:
            raise StressFailure(f"Unsupported keyboard character {char!r}")
        row, col = grid[char]
        for _ in range(40):
            r, c = play.mem.u16(satkeys.CURSOR + 2), play.mem.u16(satkeys.CURSOR)
            if (r, c) == (row, col):
                break
            play.press("down" if r < row else "up" if r > row else "right" if c < col else "left")
            play.run(24)
        else:
            raise StressFailure(f"Keyboard cursor cannot reach {char!r}")
        play.press("a"); play.run(24)
    actual = play.mem.read(satkeys.TYPED, 14).split(b"\0", 1)[0]
    expected = bytes(satkeys.code_of(char) for char in text.upper())
    if actual != expected:
        raise StressFailure(f"Keyboard input differs for {text!r}: {actual.hex()}")
    play.press("start"); play.run(120)


def dial_phone(play, digits, retry_prefix=False):
    """Saturn selects the number's first digit, then types its remaining digits.

    The first digit dispatches to a second numeric-input screen. Waiting
    for that handoff is essential: sending the entire number at once loses
    digits during the transition or inserts them into the wrong screen.
    """
    import satkeys
    import satplay
    import satmem
    from satstress import StressFailure
    start = play.f
    while play.f - start < 3000:
        text = "".join(row for row, _ in satplay.read_cells(play.mem, play.dec))
        if "What number" in text and play.mem.u8(satmem.BOX_WAIT) == 1:
            break
        play.run(1)
    else:
        raise StressFailure("Videophone number prompt did not settle")
    play.press("a"); play.run(120)
    def tap_digit(digit):
        col, row = satplay.PHONE_CELLS[digit]
        for _ in range(40):
            c, r = play.mem.u16(satkeys.CURSOR), play.mem.u16(satkeys.CURSOR + 2)
            if (c, r) == (col, row):
                break
            play.press("down" if r < row else "up" if r > row else "right" if c < col else "left")
            play.run(12)
        else:
            raise StressFailure("Videophone cursor did not reach requested digit")
        play.press("a"); play.run(24)
    expected = b""
    for index, digit in enumerate(digits):
        expected += bytes([0x0F + int(digit)])
        for attempt in range(3):
            tap_digit(digit)
            if index == 0 and attempt == 0:
                play.run(300)
            entered = play.mem.read(satplay.PAD_TYPED, 14).split(b"\0")[0]
            play.log(f"{play.f}: phone digit {digit}: buffer {entered.hex()}")
            if index == 0 and attempt == 0 and not retry_prefix and not entered:
                expected = b""
                break
            if entered == expected:
                break
            if entered != expected[:-1]:
                raise StressFailure(f"Videophone entered {entered.hex()}, expected {expected.hex()}")
            play.run(120)
        else:
            raise StressFailure(f"Videophone did not accept digit {index + 1}")
    # The first digit selects the area; the second pad stores its suffix.
    # Let the automatic match/ringing complete without START cancelling it.
    play.run(600)


def napoleon_password(play):
    from satstress import StressFailure, PanelOpen, keyboard_open
    got = play.wait_menu(patience=3000)
    if not got or "Answer" not in got[3]:
        raise StressFailure("Napoleon did not offer the password answer")
    prompt = " ".join(" ".join(card["rows"]) for card in play.cards[-12:]).lower()
    if "revolution is" in prompt:
        answer = "OVER"
    elif "hundred days" in prompt:
        answer = "REIGN"
    else:
        raise StressFailure("Napoleon's password question was not recognized")
    def panel(frame):
        if keyboard_open(play.mem):
            raise PanelOpen()
    try:
        play.pick("Answer", hook=panel)
    except PanelOpen:
        pass
    type_text(play, answer)


def verify_stage(play, stage, fights_before):
    from satstress import StressFailure
    if stage.get("expected"):
        verify_endpoint(play, stage["expected"])
    if play.fights - fights_before < stage.get("min_fights", 0):
        raise StressFailure(f"Story stage {stage['name']} did not complete its required shootout")
    if stage.get("required_cue") and not any(
            card.get("src") == stage["required_cue"] for card in play.cards):
        raise StressFailure(f"Story stage {stage['name']} did not produce {stage['required_cue']}")


def verify_endpoint(play, expected):
    import satplay
    from satstress import StressFailure, GuideDone
    start = play.f
    def arrived(frame):
        if satplay.BANK_NAMES.get(play.bank) in expected:
            raise GuideDone()
        if frame - start >= 12000:
            raise StressFailure(f"Story did not reach {expected}; still in {satplay.BANK_NAMES.get(play.bank)}")
    try:
        while satplay.BANK_NAMES.get(play.bank) not in expected:
            play.wait_menu(patience=1500, hook=arrived)
            play.run(30, arrived)
    except GuideDone:
        pass


def wait_scene_menu(play, destination):
    import satplay
    import satmem
    from satstress import LOCATIONS, StressFailure, GuideDone, advance_transition
    expected_main = satmem.image_exec(play.image)[0x600:0x620]
    start = play.f
    last_key, stable_since = None, play.f
    def ready_menu():
        bank = satplay.BANK_NAMES.get(play.bank)
        labels = play.labels_now()
        return (LOCATIONS.get(bank) == destination and play.is_top(labels)
                and play.mem.read(0x060B0600, 32) == expected_main)
    def settled(frame):
        nonlocal last_key, stable_since
        if frame - start >= 18000:
            raise StressFailure(f"{destination!r} did not present a settled scene menu")
        if frame % 30:
            return
        bank = satplay.BANK_NAMES.get(play.bank)
        labels = play.labels_now()
        ready = ready_menu()
        key = (bank, tuple(labels)) if ready else None
        if key != last_key:
            last_key, stable_since = key, frame
        if ready and frame - stable_since >= 120:
            raise GuideDone()
    try:
        while True:
            play.wait_menu(patience=300, hook=settled)
            if ready_menu():
                # A stale card-wait byte must not turn the settling period
                # into an unintended choice on the newly loaded root menu.
                play.run(30, settled)
            else:
                labels = play.labels_now()
                if labels and not play.is_top(labels):
                    play.press("b"); play.run(30, settled)
                else:
                    advance_transition(play)
            settled(play.f)
    except GuideDone:
        pass


def travel(play, destination, event):
    import satplay
    from satstress import LOCATIONS, DESTINATIONS, TERMINAL_EXITS, StressFailure, keyboard_open, leave_keyboard
    start = play.f
    arriving = False
    while play.f - start < 5 * 60 * 60:
        bank = satplay.BANK_NAMES.get(play.bank)
        if LOCATIONS.get(bank) == destination:
            # Bank loading precedes the arrival cards and the actual scene
            # menu. The old tricycle labels must not be treated as arrival.
            wait_scene_menu(play, destination)
            return
        if keyboard_open(play.mem):
            leave_keyboard(play)
        got = play.wait_menu(patience=1500)
        if not got:
            play.press("b"); play.run(30); continue
        bank = satplay.BANK_NAMES.get(play.bank)
        if LOCATIONS.get(bank) == destination:
            # wait_menu can complete the arrival; do not choose Move in the
            # destination scene before noticing that travel has succeeded.
            wait_scene_menu(play, destination)
            return
        labels = got[3]
        normalized = [x.strip().lower() for x in labels]
        choice = None
        if bank in {"B0A0", "B170"}:
            if arriving and "exit tricycle" in normalized:
                choice = normalized.index("exit tricycle")
            else:
                choice = next((i for i, label in enumerate(normalized) if DESTINATIONS.get(label) == destination), None)
                if choice is not None:
                    arriving = True
                elif "exit tricycle" in normalized:
                    raise StressFailure(f"Required destination {destination!r} is not unlocked: {labels}")
        else:
            for label in TERMINAL_EXITS[:-1] + ("back to study", "living room", "board tricycle", "go out", "go out front", "front desk", "front", "move", "go back"):
                if label in normalized:
                    choice = normalized.index(label); break
        event("journey_travel", destination=destination, bank=bank, labels=labels, choice=choice)
        if choice is None:
            play.press("b"); play.run(30)
        else:
            ok, _ = play.pick(choice)
            if not ok and bank in {"B0A0", "B170"}:
                arriving = False
    raise StressFailure(f"Could not reach {destination!r} within five minutes")


def run_action(action, play, deadline, event, log):
    import satplay
    from satstress import StressFailure
    event("journey_action", action=action)
    if "type" in action:
        type_text(play, action["type"])
    elif "ending_wait" in action:
        ending = EndingObserver()

        class FinalCueSeen(Exception):
            pass

        def stop_at_final_cue(frame):
            ending.observe(play.cards)
            if ending.frame is not None:
                raise FinalCueSeen()

        try:
            stop_at_final_cue(play.f)
            play.wait_menu(patience=action["ending_wait"], hook=stop_at_final_cue)
        except FinalCueSeen:
            pass  # The caller now runs the ending tail without any input.
    elif "fight" in action:
        aims = action["fight"]
        # Play indexes aim lists by the session's total shootouts. Routes
        # describe fights relative to this stage, including in a fresh game.
        play.fight_state = [aims[0]] * play.fights + aims if isinstance(aims, list) else aims
    elif action.get("montage"):
        solve_montage(play)
    elif action.get("queen_evidence"):
        queen_evidence(play)
    elif action.get("queen_stairs"):
        queen_stairs(play)
    elif "scene_menu" in action:
        wait_scene_menu(play, action["scene_menu"])
    elif action.get("menu_settle"):
        play.wait_menu(patience=6000)
        play.run(120)
    elif "light_to" in action:
        if not play.light_to(*action["light_to"]):
            raise StressFailure(f"Queen Hospital lamp could not reach {action['light_to']}")
    elif "travel" in action:
        travel(play, action["travel"], event)
    elif "dial" in action:
        if action.get("then") == "start":
            play.dial(str(action["dial"]))  # Catherine's question pad, not the videophone.
        else:
            dial_phone(play, str(action["dial"]), action.get("retry_prefix", False))
    elif action.get("napoleon_password"):
        napoleon_password(play)
    elif "path" in action:
        for _ in range(action.get("reps", 1)):
            if action.get("strict") and action["path"][0] == "Move":
                for _ in range(8):
                    play.wait_menu(patience=1800)
                    play.run(120)
                    if play.is_top(play.labels_now()):
                        break
                    play.press("b")
                    play.run(120)
                else:
                    raise StressFailure("Required movement could not leave the current submenu")
            ok = play.do_path(action["path"], action.get("optional", False), action.get("patience", 1800))
            if ok and action.get("strict"):
                ok = play.last_pick.strip().lower() in {
                    label.strip().lower() for label in action["path"][-1].split("|")}
            if not ok:
                if not action.get("optional"):
                    raise StressFailure(f"Required story path failed: {action['path']}")
                break
    elif "sweep" in action and "depth_limit" in action:
        play.sweep(action["sweep"], action.get("rounds", 1), action.get("avoid", ()),
                   action.get("each"), action.get("each_rounds", 1),
                   depth_limit=action["depth_limit"])
    else:
        satplay.run_action(action, play, deadline, log)
