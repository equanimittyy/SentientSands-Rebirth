import os
import sys
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
        routes._last_line = 0.0

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


if __name__ == "__main__":
    unittest.main()
