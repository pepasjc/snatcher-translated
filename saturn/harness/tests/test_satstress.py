"""Stress-test invariants: corruption detection and reproducible menu policy."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work")
sys.path[:0] = [os.path.join(ROOT, d) for d in
               ("lib", "saturn/tools", "saturn/harness", "saturn/subs")]

import satstress
import satfont
import satjourney
import satplay
import satlong
import sh2asm
import struct
import json
import subprocess


class GameplayTrackingTests(unittest.TestCase):
    def test_movie_memory_is_not_decoded_and_gameplay_checks_resume(self):
        marker = bytes(range(32))
        current = [marker]
        calls = []
        play = SimpleNamespace(mem=SimpleNamespace(read=lambda addr, n: current[0]),
                               track=lambda: calls.append('gameplay'), tick=123,
                               last_cells=('old',), card_key='old', face_watch='old')
        satstress.guard_gameplay_tracking(play, bytes(0x600) + marker)
        play.track()
        current[0] = b'rec ' + bytes(28)  # native AVI header at the credits transition
        play.track()
        self.assertEqual(['gameplay'], calls)
        self.assertIsNone(play.tick)
        self.assertIsNone(play.last_cells)
        current[0] = marker
        play.track()
        self.assertEqual(['gameplay', 'gameplay'], calls)


class SupervisionTests(unittest.TestCase):
    def test_exited_pilot_is_reported_without_rewriting_native_evidence(self):
        # A real child process exits while its last heartbeat still says running.
        pilot = subprocess.Popen([sys.executable, "-c", "pass"])
        pilot.wait(timeout=10)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "status.json")
            evidence = json.dumps(dict(status="running", pid=pilot.pid, frame=123))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(evidence)
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "saturn", "harness", "satwatch.py"),
                 "--run", directory], capture_output=True, text=True, timeout=10)
            self.assertEqual(1, result.returncode, result.stderr)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(evidence, fh.read())
            with open(os.path.join(directory, "supervision.json"), encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertEqual("process_lost", report["health"])
            self.assertFalse(report["pilot_alive"])
            self.assertEqual(123, report["frame"])


class RetryTests(unittest.TestCase):
    def test_lingering_continue_does_not_change_the_retry_aim_twice(self):
        from unittest.mock import Mock
        play = satplay.Play.__new__(satplay.Play)
        play.f, play.fights, play.deaths = 0, 2, 0
        play.in_death, play.death_counted = False, False
        play.live_since = 0
        play.menu = lambda: (1, 0, 2, ["Continue", "Quit game"])
        play.labels_now = lambda: ["Continue", "Quit game"]
        play.mem = SimpleNamespace(u8=lambda address: 1)
        play.log = lambda message: None
        play.capture = lambda label: "death.png"
        play.problem = Mock()
        play.pick = Mock(return_value=(False, ["Continue", "Quit game"]))

        class StopReplay(Exception):
            pass

        def run(frames=1, hook=None):
            play.f += frames
            play.live_since = play.f - satplay.MENU_SETTLE
            if play.f > 1250:
                raise StopReplay()

        play.run = run
        with self.assertRaises(StopReplay):
            play.wait_menu(patience=2000)
        self.assertGreaterEqual(play.pick.call_count, 2)
        self.assertEqual(1, play.deaths)
        self.assertEqual(1, play.fights)
        self.assertEqual(1, play.problem.call_count)


class HordeAimTests(unittest.TestCase):
    def test_small_head_is_targeted_before_its_larger_body(self):
        import numpy as np
        from PIL import Image
        import satrun
        pixels = np.zeros((240, 330, 3), dtype=np.uint8)
        pixels[150:180, :70] = (255, 200, 0)
        for column in (125, 203):
            pixels[18:142, column:column + 2] = (0, 108, 43)
        for row in (60, 100):
            pixels[row:row + 2, 48:284] = (0, 108, 43)
        pixels[30:36, 240:246] = (128, 128, 128)  # Head: 36 grey pixels.
        pixels[110:130, 240:260] = (160, 160, 160)  # Body: 400 grey pixels.
        play = satplay.Play.__new__(satplay.Play)
        play.f, play.fight_since, play.fights = 100, 0, 1
        play.fight_view, play.fight_state, play.in_fight = None, ["horde"], True
        play.log = lambda message: None
        play.emu = SimpleNamespace(image=lambda: Image.fromarray(pixels), held=set())
        self.assertTrue(play.fight_step())
        self.assertEqual({satrun.BTN["up"], satrun.BTN["right"]}, play.emu.held)


class LongBufferBuildTests(unittest.TestCase):
    def test_runtime_pointer_is_aligned_and_only_recognized_in_matching_helper(self):
        exe = bytearray(0x40000)
        helper = 0x060E806C
        code, labels = sh2asm.asm(satlong.buffer_program(), helper)
        self.assertEqual(0, labels["buffer"] % 4)
        exe[helper - satlong.MAIN_BASE:helper - satlong.MAIN_BASE + len(code)] = code
        start = 0x060E7230
        main, main_labels = sh2asm.asm(satlong.stub_program(helper, labels["buffer"]), start)
        self.assertEqual(0, main_labels["lenvar"] % 4)
        exe[start - satlong.MAIN_BASE:start - satlong.MAIN_BASE + len(main)] = main
        site = next(h[0] for h in satlong.HOOKS if h[2] == "conv")
        struct.pack_into(">I", exe, site - satlong.MAIN_BASE, main_labels["conv"])
        self.assertEqual(labels["buffer"], satlong.buffer_var_from_exec(exe))
        exe[helper - satlong.MAIN_BASE] ^= 1
        self.assertIsNone(satlong.buffer_var_from_exec(exe))


class QueenStairsTests(unittest.TestCase):
    def test_door_target_cannot_satisfy_required_room_entry(self):
        play = SimpleNamespace(wait_menu=lambda **kw: None, run=lambda n: None,
                               is_top=lambda labels: True, labels_now=lambda: ["Move", "Look", "Investigate"],
                               do_path=lambda *args: True, last_pick="Door",
                               emu=SimpleNamespace(frame=0))
        action = dict(path=["Move", "Door 3"], strict=True)
        with self.assertRaises(satstress.StressFailure):
            satjourney.run_action(action, play, 1000, lambda *args, **kw: None, lambda x: None)
        play.last_pick = "Door 3"
        satjourney.run_action(action, play, 1000, lambda *args, **kw: None, lambda x: None)

    def test_stairs_root_is_not_treated_as_a_child_of_peek(self):
        play = SimpleNamespace(top_labels=[], find=satplay.Play.find)
        self.assertTrue(satplay.Play.is_top(play, ["Peek", "Investigate", "Use Metal Gear"]))
        self.assertFalse(satplay.Play.is_top(play, ["Stairs", "Motion detector"]))

    def test_lamp_is_not_moved_after_stairs_already_opened(self):
        play = SimpleNamespace(wait_menu=lambda **kw: (True, 0, 3, ["Peek", "Investigate", "Use Metal Gear"]),
                               find=lambda labels, want: labels.index(want) if want in labels else None)
        satjourney.queen_stairs(play)

    def test_tunnel_root_does_not_sweep_move_as_an_inspection_target(self):
        play = SimpleNamespace(top_labels=[])
        self.assertTrue(satplay.Play.is_top(play, ["Investigate", "Move"]))
        self.assertTrue(satplay.Play.is_top(play, ["Press button", "Investigate", "Move"]))
        self.assertTrue(satplay.Play.is_top(play, ["Turn right", "Turn left", "Back"]))
        self.assertFalse(satplay.Play.is_top(play, ["Wall", "Roof", "Floor", "Button"]))


class PlayerProgressTests(unittest.TestCase):
    def test_replaying_a_fight_does_not_make_the_same_story_state_new(self):
        play = SimpleNamespace(bank=satplay.BANK_OF["B220"],
                               cards=[dict(src="off 28177", rows=["It's freezing."])],
                               labels_now=lambda: ["Investigate", "Move"],
                               mem=SimpleNamespace(read=lambda *args: bytes(14)), fights=1)
        before = satstress.player_state(play)
        play.fights = 10
        self.assertEqual(before, satstress.player_state(play))

    def test_repeated_menu_cycles_fail_even_when_input_keeps_happening(self):
        watch = satstress.PlayerProgressWatch(limit=100)
        watch.observe(0, ("HQ", "Look"))
        watch.observe(1, ("HQ", "Investigate"))
        watch.observe(50, ("HQ", "Look"))
        with self.assertRaises(satstress.StressFailure):
            watch.observe(101, ("HQ", "Investigate"))

    def test_new_scene_and_intentional_no_input_tail_extend_the_watch(self):
        watch = satstress.PlayerProgressWatch(limit=100)
        watch.observe(0, ("HQ", "Look"))
        watch.observe(90, ("Altamira", "Look"))
        watch.observe(180, ("Altamira", "Look"), suspended=True)
        watch.observe(250, ("Altamira", "Look"))
        watch.reset(300)
        watch.observe(301, ("Altamira", "Look"))


class PolicyTests(unittest.TestCase):
    def test_seed_reproduces_choices_and_excludes_session_controls(self):
        labels = ["Look", "Move", "Save", "Quit game", "Load", "Investigate"]
        runs = []
        for _ in range(2):
            policy = satstress.MenuPolicy(88)
            runs.append([policy.choose("B150", 1, labels, True, "act2_roam") for _ in range(100)])
        self.assertEqual(runs[0], runs[1])
        self.assertTrue(set(runs[0]) <= {0, 1, 5})
        self.assertEqual({0, 1, 5}, set(runs[0]))

    def test_finale_is_available_after_act1_roaming(self):
        labels = ["Go to bathroom"]
        policy = satstress.MenuPolicy(88)
        self.assertIsNone(policy.choose("B120", 1, labels, True, "act1_roam"))
        self.assertEqual(0, policy.choose("B120", 1, labels, True, "finish_act1"))

    def test_terminal_escape_uses_exit_items_instead_of_reopening_search(self):
        policy = satstress.MenuPolicy(88)
        for labels, expected in ((["Search name", "Stop search"], 1),
                                 (["Load person file", "Log off"], 1),
                                 (["Move", "Look", "Use Gaudi"], 0)):
            self.assertEqual(expected, policy.choose("B040", 6, labels, False, "act2_roam", escaping=True))
        self.assertIsNone(policy.choose("B030", 6, ["Hair 1", "Hair 2"], False, "act2_roam", escaping=True))


class KeyboardTests(unittest.TestCase):
    def test_panel_counts_come_from_the_live_build(self):
        import satkeys
        memory = {satkeys.LIST_PTR: 0x060E736C, 0x060E736C: 15,
                  satkeys.SEARCH_COUNT: 0xE00F, satkeys.PUZZLE_COUNT: 0xE008}
        mem = SimpleNamespace(u32=lambda addr: memory[addr], u16=lambda addr: memory[addr])
        self.assertTrue(satstress.keyboard_open(mem))
        memory[0x060E736C] = 8
        self.assertTrue(satstress.keyboard_open(mem))
        memory[0x060E736C] = 4
        self.assertFalse(satstress.keyboard_open(mem))

    def test_keyboard_exit_uses_start_and_is_bounded(self):
        presses = []
        play = SimpleNamespace(mem=None, press=presses.append, run=lambda n: None)
        with patch("satstress.keyboard_open", side_effect=[True, False]):
            satstress.leave_keyboard(play)
        self.assertEqual(["start"], presses)
        presses.clear()
        with patch("satstress.keyboard_open", return_value=True):
            with self.assertRaises(satstress.StressFailure):
                satstress.leave_keyboard(play)
        self.assertEqual(["start"] * 3, presses)


class LocationTourTests(unittest.TestCase):
    def test_training_exit_uses_quit_instead_of_ineffective_back(self):
        tour = satstress.LocationTour()
        tour.observe("B150", 0)
        self.assertEqual((True, 1), tour.choose("B150", 7200, ["Keep going", "Quit training"]))

    def test_outside_boarding_waits_for_real_option_exploration(self):
        tour = satstress.LocationTour()
        tour.observe("B190", 100)
        labels = ["Board Tricycle", "Look"]
        policy = satstress.MenuPolicy(88)
        choice = policy.choose("B190", 0, labels, True, "oleen_soak", blocked=tour.blocked_departures(101))
        self.assertEqual(1, choice)
        self.assertEqual(set(), tour.blocked_departures(100 + 3 * 60 * satstress.FPS))

    def test_early_tour_includes_hq_but_late_tour_defers_its_story_trigger(self):
        tour = satstress.LocationTour()
        tour.location = "Home"
        tour.visits.update({"Home": 1, "Altamira": 1})
        labels = ["Altamira", "JUNKER HQ", "Exit Tricycle"]
        self.assertEqual((True, 1), tour.choose("B170", 1, labels))
        tour.pending_arrival = False
        self.assertEqual((True, 0), tour.choose("B170", 1, labels, allow_hq=False))
    def test_hq_overlays_do_not_count_as_physical_locations(self):
        tour = satstress.LocationTour()
        for frame, bank in enumerate(["B150", "B030", "B040", "B070", "B170", "B150", "B160"], 1):
            tour.observe(bank, frame)
        self.assertEqual(0, tour.transitions)
        self.assertEqual(set(), tour.outside)
        self.assertEqual(0, tour.outside_frames)
        tour.observe("B190", 8)
        tour.observe("B170", 9)
        tour.observe("B1A0", 10)
        self.assertEqual(2, tour.transitions)
        self.assertEqual({"Altamira", "Home"}, tour.outside)
        self.assertEqual(2, tour.outside_frames)

    def test_trip_selects_destination_then_exits_tricycle(self):
        tour = satstress.LocationTour()
        tour.observe("B150", 0)
        self.assertEqual((True, 0), tour.choose("B170", 1, ["Altamira", "Exit Tricycle"]))
        self.assertEqual((True, 0), tour.choose("B170", 2, ["Exit Tricycle", "JUNKER HQ"]))
        tour.observe("B190", 3)
        self.assertFalse(tour.pending_arrival)
        self.assertEqual((True, 1), tour.choose("B170", 4, ["JUNKER HQ", "Gillian's home", "Exit Tricycle"]))

    def test_hq_visit_is_bounded_and_failed_travel_fails(self):
        tour = satstress.LocationTour()
        tour.observe("B150", 0)
        self.assertEqual((False, None), tour.choose("B150", 1, ["Look", "Move"]))
        departure = 5 * 60 * satstress.FPS
        self.assertEqual((True, 1), tour.choose("B150", departure, ["Look", "Move"]))
        self.assertEqual((True, 1), tour.choose("B150", departure + 1, ["Chief's room", "Front desk"]))
        with self.assertRaises(satstress.StressFailure):
            tour.observe("B150", departure * 2 + 1)


class NativeControlTests(unittest.TestCase):
    def test_only_native_controller_actions_and_bounded_waits_are_accepted(self):
        calls = []
        play = SimpleNamespace(press=lambda key: calls.append(('press', key)),
                               run=lambda n: calls.append(('run', n)),
                               do_path=lambda path, **kw: calls.append(('path', path)) or True)
        self.assertTrue(satstress.native_control_actions(play, dict(actions=[dict(press='b'), dict(path=['Quit training']), dict(wait=120)], **{'continue': True})))
        self.assertEqual([('press', 'b'), ('run', 30), ('path', ['Quit training']), ('run', 120)], calls)
        for command in [dict(restore='old.state'), dict(actions=[dict(poke=1)]), dict(actions=[dict(wait=3601)])]:
            with self.assertRaises(ValueError):
                satstress.native_control_actions(play, command)


class JourneyTests(unittest.TestCase):
    def test_queen_scan_rejects_a_lamp_that_never_moves(self):
        play = SimpleNamespace(cards=[], wait_menu=lambda **k: None, light_to=lambda *a: False)
        with patch("satjourney.queen_lamp_bounds", return_value=(40, 34, 204, 110)), self.assertRaises(satstress.StressFailure):
            satjourney.queen_evidence(play)

    def test_queen_scan_requires_all_three_live_clues(self):
        points = []
        play = SimpleNamespace(cards=[], wait_menu=lambda **k: None,
                               light_to=lambda x, y: points.append((x, y)) or True)
        def sweep(*args):
            clues = ["St. Basil's Cathedral. Moscow? What's the connection to the Snatchers?", "I'll take the matches.",
                     "I'll keep this piece of the medical record."]
            play.cards.append(dict(rows=[clues[min(len(points), 3) - 1]]))
        play.sweep = sweep
        with patch("satjourney.queen_lamp_bounds", return_value=(40, 34, 204, 110)):
            satjourney.queen_evidence(play)
        self.assertEqual(3, len(points))
        points.clear(); play.cards.clear()
        play.sweep = lambda *args: play.cards.append(dict(rows=["St. Basil's Cathedral", "I'll take the matches."]))
        with patch("satjourney.queen_lamp_bounds", return_value=(40, 34, 204, 110)), self.assertRaises(satstress.StressFailure):
            satjourney.queen_evidence(play)
        self.assertLess(len(points), 150)

    def test_required_complete_path_rejects_a_parent_menu_only(self):
        play = SimpleNamespace(do_path=lambda *a: True, last_pick="Item",
                               find=lambda labels, wanted: 0 if labels == [wanted] else None)
        action = satjourney.path("Item", "Show", "Photo", "Montage photo", strict=True)
        with self.assertRaises(satstress.StressFailure):
            satjourney.run_action(action, play, 100, lambda *a, **k: None, lambda s: None)
        play.last_pick = "Montage photo"
        satjourney.run_action(action, play, 100, lambda *a, **k: None, lambda s: None)

    def test_ivan_bank_alone_does_not_prove_his_shootout(self):
        stage = next(s for s in satjourney.opening_stages() if s["name"] == "act1_ivan")
        play = SimpleNamespace(fights=3)
        with patch("satjourney.verify_endpoint"):
            with self.assertRaises(satstress.StressFailure):
                satjourney.verify_stage(play, stage, fights_before=3)
            play.fights = 4
            satjourney.verify_stage(play, stage, fights_before=3)

    def test_benson_requires_the_native_solution_cue_as_well_as_departure(self):
        stage = next(s for s in satjourney.stages() if s["name"] == "benson")
        play = SimpleNamespace(fights=0, cards=[])
        with patch("satjourney.verify_endpoint"):
            with self.assertRaises(satstress.StressFailure):
                satjourney.verify_stage(play, stage, 0)
            play.cards.append(dict(src="cue B1D0_f9_0"))
            satjourney.verify_stage(play, stage, 0)

    def test_settled_scene_menu_is_observed_without_confirming_a_stale_card(self):
        import satplay
        play = SimpleNamespace(f=0, bank=satplay.BANK_OF["B080"], image="disc",
                               mem=SimpleNamespace(read=lambda *a: bytes(32)),
                               labels_now=lambda: ["Move", "Look", "Investigate"], is_top=lambda labels: True)
        play.wait_menu = lambda **k: None
        def run(n, hook):
            for _ in range(n):
                play.f += 1
                hook(play.f)
        play.run = run
        with patch("satmem.image_exec", return_value=bytes(0x620)), patch("satstress.advance_transition") as advance:
            satjourney.wait_scene_menu(play, "HQ")
        advance.assert_not_called()
        self.assertGreaterEqual(play.f, 120)

    def test_act1_travel_recognizes_the_live_gibsons_home_label(self):
        import satplay
        labels = ["JUNKER HQ", "Gibson's home", "Altamira", "Exit Tricycle"]
        play = SimpleNamespace(f=0, bank=satplay.BANK_OF["B0A0"], mem=None,
                               wait_menu=lambda **k: (True, 0, len(labels), labels))
        picks = []
        def pick(choice):
            picks.append(choice)
            play.bank = satplay.BANK_OF["B0C0"]
            return True, labels
        play.pick = pick
        with patch("satstress.keyboard_open", return_value=False), patch("satjourney.wait_scene_menu") as settled:
            satjourney.travel(play, "Gibson's house", lambda *a, **k: None)
        self.assertEqual([1], picks)
        settled.assert_called_once_with(play, "Gibson's house")

    def test_montage_uses_live_wrong_feature_feedback_until_a_match(self):
        selections = []
        play = SimpleNamespace(cards=[])
        replies = iter(["Could the face shape be wrong?", "Could the eyes be wrong?", "Two people match the composite portrait."])
        def do_path(labels, optional, patience):
            selections.append(labels)
            return True
        def wait_menu(patience):
            play.cards.append(dict(rows=[next(replies)]))
        play.do_path, play.wait_menu = do_path, wait_menu
        satjourney.solve_montage(play)
        self.assertIn(["Outline", "Outline 3"], selections)
        self.assertIn(["Eyes", "Eyes 6"], selections)
        self.assertNotIn(["Nose", "Nose 3"], selections)

    def test_general_montage_feedback_search_is_bounded_and_reenters_cleared_parts(self):
        selections = []
        play = SimpleNamespace(cards=[], do_path=lambda labels, *a: selections.append(labels) or True)
        play.wait_menu = lambda **k: play.cards.append(dict(rows=["Could the portrait be wrong? Try again."]))
        with self.assertRaises(satstress.StressFailure):
            satjourney.solve_montage(play)
        self.assertEqual(32, sum(labels == ["Match"] for labels in selections))
        # A failed match clears every selected part, not just the wrong one.
        self.assertEqual(32 * 5, sum(len(labels) == 2 for labels in selections))

    def test_montage_does_not_accept_missing_feedback(self):
        play = SimpleNamespace(cards=[], do_path=lambda *a: True, wait_menu=lambda **k: None)
        with self.assertRaises(satstress.StressFailure):
            satjourney.solve_montage(play)

    def test_full_game_has_opening_and_complete_act3_without_state_operations(self):
        opening = satjourney.opening_stages()
        self.assertEqual("hq_introduction", opening[0]["name"])
        self.assertEqual("opening_completed", opening[-1]["milestone"])
        for stage in opening:
            self.assertTrue(stage["expected"])
            for action in stage["actions"]:
                self.assertFalse({"save", "bsave", "mcard", "new"} & action.keys())
        final = satjourney.stages(whole_game=True)[-1]
        self.assertEqual("act3_finish", final["name"])
        self.assertTrue(final["finish_game"])

    def test_ending_requires_final_cue_in_ending_bank(self):
        ending = satjourney.EndingObserver()
        cards = [dict(bank="B260", frame=1, src="cue another"),
                 dict(bank="B240", frame=2, src="cue " + ending.cue_id)]
        ending.observe(cards)
        self.assertIsNone(ending.frame)
        cards.append(dict(bank="B260", frame=3, src="cue " + ending.cue_id))
        ending.observe(cards)
        self.assertEqual(3, ending.frame)

    def test_ending_wait_stops_before_sending_input_after_final_cue(self):
        ending = satjourney.EndingObserver()
        play = SimpleNamespace(f=3, cards=[dict(bank="B260", frame=3, src="cue " + ending.cue_id)],
                               emu=SimpleNamespace(frame=0))
        satjourney.run_action(dict(ending_wait=60000), play, 100000,
                              lambda *args, **kw: None, lambda x: None)

    def test_fight_sequences_are_relative_to_the_current_story_stage(self):
        play = SimpleNamespace(fights=4)
        satjourney.run_action(dict(fight=["body", "horde", "hold"]), play, 100,
                              lambda *a, **k: None, lambda s: None)
        self.assertEqual("body", play.fight_state[4])
        self.assertEqual("horde", play.fight_state[5])
        self.assertEqual("hold", play.fight_state[6])

    def test_oleen_exit_stops_the_sweep_but_earlier_tricycle_trips_do_not(self):
        guard = satjourney.EndpointGuard(satjourney.stages()[0])
        self.assertFalse(guard.observe("B150"))
        self.assertFalse(guard.observe("B170"))
        self.assertFalse(guard.observe("B190"))
        self.assertFalse(guard.observe("B1B0"))
        self.assertTrue(guard.observe("B170"))
        self.assertFalse(guard.observe("B170"))
    def test_phone_dial_preserves_area_handoff_and_verifies_suffix(self):
        import satkeys
        import satplay
        play = SimpleNamespace(f=0)
        cursor = [0, 0]
        confirms = []
        entered = bytearray()
        def press(button):
            if button == "a":
                confirms.append((play.f, tuple(cursor)))
                if len(confirms) > 2:
                    digit = next(d for d, cell in satplay.PHONE_CELLS.items() if cell == tuple(cursor))
                    entered.append(0x19 if digit == "0" else 0x0F + int(digit))
            elif button == "left": cursor[0] -= 1
            elif button == "right": cursor[0] += 1
            elif button == "up": cursor[1] -= 1
            elif button == "down": cursor[1] += 1
        play.press = press
        play.run = lambda n: setattr(play, "f", play.f + n)
        play.mem = SimpleNamespace(u8=lambda addr: 1,
                                   read=lambda addr, n: bytes(entered) + bytes(n - len(entered)),
                                   u16=lambda addr: cursor[0 if addr == satkeys.CURSOR else 1])
        play.dec = None
        play.log = lambda text: None
        with patch("satplay.read_cells", return_value=[("What number?", [])]):
            satjourney.dial_phone(play, "395644")
        self.assertEqual([satplay.PHONE_CELLS[d] for d in "395644"], [cell for frame, cell in confirms[1:] if cell != (0, 0)])
        self.assertEqual(bytes.fromhex("1814151313"), bytes(entered))
        self.assertGreaterEqual(confirms[2][0] - confirms[1][0], 324)

    def test_endpoint_wait_observes_the_actual_loaded_bank(self):
        import satplay
        play = SimpleNamespace(f=0, bank=satplay.BANK_OF["B220"])
        def wait_menu(patience, hook):
            play.f += 1
            play.bank = satplay.BANK_OF["B230"]
            hook(play.f)
        play.wait_menu = wait_menu
        satjourney.verify_endpoint(play, ["B230"])
        self.assertEqual(1, play.f)

    def test_story_order_places_tours_before_the_irreversible_finale(self):
        stages = satjourney.stages()
        names = [stage["name"] for stage in stages]
        self.assertLess(names.index("reach_oleen"), names.index("oleen_soak"))
        self.assertLess(names.index("benson"), names.index("late_soak"))
        self.assertLess(names.index("late_soak"), names.index("hq_and_runaway"))
        self.assertLess(names.index("tunnel_and_taxi"), names.index("act2_finale"))
        self.assertEqual("act3_continue", names[-1])
        for stage in stages:
            for action in stage.get("actions", []):
                self.assertFalse({"save", "bsave", "mcard", "new"} & action.keys())
            if not stage.get("soak") and not stage.get("act3"):
                self.assertTrue(stage.get("expected"))

    def test_required_path_failure_stops_the_journey(self):
        play = SimpleNamespace(ensure_top=lambda: None, do_path=lambda *args: False)
        with self.assertRaises(satstress.StressFailure):
            satjourney.run_action({"path": ["Show", "Video memory"]}, play, 100, lambda *a, **k: None, lambda s: None)
        satjourney.run_action({"path": ["Look"], "optional": True}, play, 100, lambda *a, **k: None, lambda s: None)

    def test_untried_external_options_are_reported_separately_from_failed_attempts(self):
        coverage = satstress.OptionCoverage()
        coverage.offer("B150", 1, ["Look", "Move"])
        coverage.offer("B190", 1, ["Look", "Ask", "Save"])
        coverage.record("B190", 1, ["Look", "Ask", "Save"], 0, False)
        self.assertEqual(["Ask"], [item["label"] for item in coverage.missing_outside()])
        failed = next(item for item in coverage.items.values() if item["bank"] == "B190" and item["label"] == "Look")
        self.assertEqual(0, failed["successes"])
        self.assertEqual(1, failed["attempts"])


class FrameGuardTests(unittest.TestCase):
    def test_recap_stub_does_not_count_as_act2_hq(self):
        self.assertFalse(satstress.act2_ready("B140"))
        self.assertTrue(satstress.act2_ready("B150"))

    def test_deadline_interrupts_long_wait_at_the_exact_frame(self):
        frames = []
        def original(n, hook):
            for f in range(1, n + 1):
                frames.append(f)
                hook(f)
        def deadline(frame):
            if frame == 3:
                raise satstress.StageEnd()
        with self.assertRaises(satstress.StageEnd):
            satstress.guarded_run(original, deadline, 100)
        self.assertEqual([1, 2, 3], frames)

    def test_scene_change_interrupts_a_sweep_without_restoring(self):
        frames = []
        def original(n, hook):
            for f in range(1, n + 1):
                frames.append(f)
                hook(f)
        def scene(frame):
            if frame == 2:
                raise satstress.GuideDone()
        with self.assertRaises(satstress.GuideDone):
            satstress.guarded_run(original, scene, 100)
        self.assertEqual([1, 2], frames)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exe = bytearray(0x40000)
        self.exe[0x600:0x620] = b"MAIN" * 8
        self.table = bytearray(2 * satfont.TABLE_N)
        self.vram = bytearray(64)
        self.vram[16:32] = b"test font pixels"
        self.movie = False
        test = self

        class Mem:
            def read(self, addr, size):
                if addr == 0x060B0600:
                    return b"MOVI" * 8 if test.movie else bytes(test.exe[0x600:0x620])
                return bytes(test.table[:size])

        self.play = SimpleNamespace(f=120, mem=Mem(), emu=SimpleNamespace(state=lambda: bytes(self.vram)))
        for target, value in (("fontwatch.expected_font", (16, b"test font pixels")),
                              ("satmem.image_exec", bytes(self.exe))):
            mocker = patch(target, return_value=value)
            mocker.start(); self.addCleanup(mocker.stop)
        mocker = patch("satfont.vdp1_vram", side_effect=lambda state: state)
        mocker.start(); self.addCleanup(mocker.stop)
        self.watch = satstress.IntegrityWatch("test.cue", self.tmp.name, 120, lambda message: None)

    def test_font_damage_captures_previous_good_state(self):
        self.watch.inspect(self.play)
        before = bytes(self.vram)
        self.vram[19] ^= 1
        self.play.f = 240
        with self.assertRaises(satstress.StressFailure):
            self.watch.inspect(self.play)
        self.assertEqual("FONT", self.watch.failure["kind"])
        self.assertEqual(["0x13", "0x13"], self.watch.failure["font_range"])
        with open(os.path.join(self.tmp.name, "before_failure.state"), "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_only_the_recognized_runtime_pointer_can_change_in_the_table(self):
        code = 0x8B10
        offset = 2 * (code - satfont.TABLE_LO)
        with patch("satlong.buffer_var_from_exec", return_value=satfont.TABLE_ADDR + offset):
            watch = satstress.IntegrityWatch("test.cue", self.tmp.name, 120, lambda message: None)
        self.table[offset:offset + 4] = b"\x00\x22\x00\x08"
        watch.inspect(self.play)
        self.table[offset + 4:offset + 6] = b"\xff\xff"
        self.play.f = 240
        with self.assertRaises(satstress.StressFailure):
            watch.inspect(self.play)

    def test_runtime_exec_hole_is_ignored_but_glyph_mapping_is_checked(self):
        start, _ = self.watch.hole
        self.table[start:start + 2] = b"\xff\xff"
        self.watch.inspect(self.play)
        code = 0x8260  # fullwidth A, outside the executable allocation hole
        i = 2 * (code - satfont.TABLE_LO)
        self.table[i:i + 2] = b"\xff\xff"
        self.play.f = 240
        with self.assertRaises(satstress.StressFailure):
            self.watch.inspect(self.play)
        self.assertEqual("GLYPH_TABLE", self.watch.failure["kind"])
        self.assertEqual(["0x8260"], self.watch.failure["glyph_codes"])

    def test_movie_overlay_is_skipped_then_main_is_checked_again(self):
        self.movie = True
        self.watch.inspect(self.play)
        self.assertEqual(0, self.watch.checks)
        self.assertEqual(1, self.watch.skipped)
        self.movie = False
        self.play.f = 240
        self.watch.inspect(self.play)
        self.assertEqual(1, self.watch.checks)


if __name__ == "__main__":
    unittest.main()
