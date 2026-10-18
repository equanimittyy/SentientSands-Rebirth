import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import routes


class LinePacingTest(unittest.TestCase):
    def setUp(self):
        self.sleeps, self.sent = [], []
        for target, name, value in ((routes, "load_settings", mock.Mock(return_value={"dialogue_speed_seconds": 5})), (routes.time, "sleep", self.sleeps.append), (routes, "send_to_pipe", self.sent.append)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, routes, "_last_line", routes._last_line)
        self.addCleanup(setattr, routes, "_last_think", routes._last_think)
        routes._last_line = routes._last_think = 0.0

    def test_a_reply_waits_the_dialogue_delay_after_the_line_of_the_player(self):
        routes.say(["Erkom: Got anything to trade?"], player=True)
        routes.say(["Tiras|20: What you need."])
        self.assertEqual(self.sent, ["PLAYER_SAY: Erkom: Got anything to trade?", "NPC_SAY: Tiras|20: What you need."])
        self.assertGreater(self.sleeps[-1], 4.9)

    def test_the_line_of_the_player_waits_the_dialogue_delay_after_a_line_of_an_npc(self):
        routes.say(["Tiras|20: What you need."])
        routes.say(["Erkom: Some water."], player=True)
        self.assertEqual(self.sent[-1], "PLAYER_SAY: Erkom: Some water.")
        self.assertGreater(self.sleeps[-1], 4.9)

    def test_a_line_long_after_every_line_does_not_wait(self):
        routes.say(["Erkom: Hello."], player=True)
        self.assertEqual(self.sleeps, [0.0])

    def test_the_thinking_of_an_npc_shows_at_once_while_the_line_of_the_player_is_up(self):
        routes.say(["Erkom: Got anything to trade?"], player=True)
        routes.think("Tiras|20")
        self.assertEqual(self.sent[-1], "NPC_THINK: Tiras|20: ...")
        self.assertEqual(self.sleeps, [0.0])

    def test_a_quick_line_after_its_thinking_waits_until_the_line_before_it_has_gone(self):
        routes.say(["Erkom: Got anything to trade?"], player=True)
        routes.think("Tiras|20")
        routes.say(["Tiras|20: What you need."])
        self.assertEqual(self.sent[-1], "NPC_SAY: Tiras|20: What you need.")
        self.assertGreater(self.sleeps[-1], 4.9)

    def test_a_line_shows_at_least_the_least_thinking_time_after_its_thinking(self):
        routes.think("Tiras|20")
        routes.say(["Tiras|20: What you need."])
        self.assertEqual(self.sent, ["NPC_THINK: Tiras|20: ...", "NPC_SAY: Tiras|20: What you need."])
        self.assertGreater(self.sleeps[-1], routes.THINK_MIN - 0.05)


class RadiantPacingTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.remembered = mock.Mock()
        for target, name, value in ((routes, "load_settings", mock.Mock(return_value={"dialogue_speed_seconds": 5})), (routes.time, "sleep", lambda seconds: None),
                                    (routes, "send_to_pipe", self.sent.append), (routes, "remember_radiant", self.remembered)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(setattr, routes, "_last_line", routes._last_line)
        self.addCleanup(setattr, routes, "_last_think", routes._last_think)
        routes._last_line = routes._last_think = 0.0
        self.conversation = {"names": {"1": "Tiras", "2": "Erkom"}, "order": [("1", "2"), ("2", "1")], "campaign": routes.state.ACTIVE_CAMPAIGN}

    def play(self, write_line):
        routes._STAGE.acquire()
        with mock.patch.object(routes, "write_line", write_line):
            player = threading.Thread(target=routes.play_radiant, args=(self.conversation,))
            player.start()
            player.join(5)
        self.assertFalse(player.is_alive())

    def test_each_line_shows_after_the_thinking_of_its_speaker(self):
        self.play(lambda conversation, spoken, index: ["Dust again.", "Always dust."][index])
        self.assertEqual(self.sent, ["NPC_THINK: Tiras|1: ...", "NPC_SAY: Tiras|1: Dust again.", "NPC_THINK: Erkom|2: ...", "NPC_SAY: Erkom|2: Always dust."])
        self.remembered.assert_called_once_with(self.conversation, [("1", "Dust again."), ("2", "Always dust.")])

    def test_the_next_call_does_not_wait_for_the_line_before_it_to_show(self):
        second_call = threading.Event()
        waited = []
        def send(message):
            if message == "NPC_SAY: Tiras|1: Dust again.":
                waited.append(second_call.wait(2))
            self.sent.append(message)
        def write_line(conversation, spoken, index):
            if index == 1:
                self.assertEqual(spoken, [("1", "Dust again.")])
                second_call.set()
            return ["Dust again.", "Always dust."][index]
        with mock.patch.object(routes, "send_to_pipe", send):
            self.play(write_line)
        self.assertEqual(waited, [True])

    def test_a_call_without_a_line_ends_the_thinking_of_its_speaker(self):
        self.play(lambda conversation, spoken, index: ["Dust again.", ""][index])
        self.assertEqual(self.sent[-2:], ["NPC_THINK: Erkom|2: ...", "NPC_SAY: Erkom|2: "])
        self.remembered.assert_called_once_with(self.conversation, [("1", "Dust again.")])

    def test_a_call_that_fails_ends_the_talk_without_holding_the_stage(self):
        def write_line(conversation, spoken, index):
            raise RuntimeError("no provider")
        self.play(write_line)
        self.assertEqual(self.sent, ["NPC_THINK: Tiras|1: ...", "NPC_SAY: Tiras|1: "])
        self.assertTrue(routes._STAGE.acquire(blocking=False))
        routes._STAGE.release()


if __name__ == "__main__":
    unittest.main()
