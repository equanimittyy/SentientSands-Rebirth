import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import npc_names


def roll():
    return "Josh"


def fail():
    raise AssertionError("rolled a name for an NPC that has one")


class NamesTest(unittest.TestCase):
    def test_the_first_name_keeps_the_game_name_as_a_title(self):
        self.assertEqual(npc_names.names({"Name": "Starving Bandit"}, "Starving Bandit", False, roll), ("Starving Bandit Josh", "Josh"))

    def test_a_recruit_gets_no_title(self):
        self.assertEqual(npc_names.names({"Name": "Starving Bandit"}, "Starving Bandit", True, roll), ("Josh", "Josh"))

    def test_a_named_npc_keeps_its_name(self):
        profile = {"Name": "Starving Bandit Josh", "GivenName": "Josh"}
        self.assertEqual(npc_names.names(profile, "Starving Bandit Josh", False, fail), ("Starving Bandit Josh", "Josh"))

    def test_a_name_that_the_game_lost_comes_back(self):
        profile = {"Name": "Starving Bandit Josh", "GivenName": "Josh"}
        self.assertEqual(npc_names.names(profile, "Starving Bandit", False, fail), ("Starving Bandit Josh", "Josh"))


class RecruitNameTest(unittest.TestCase):
    def test_a_recruit_drops_its_title(self):
        self.assertEqual(npc_names.recruit_name({"Name": "Starving Bandit Josh", "GivenName": "Josh"}, "Starving Bandit Josh"), "Josh")

    def test_a_name_that_the_player_gave_in_game_stays(self):
        self.assertIsNone(npc_names.recruit_name({"Name": "Starving Bandit Josh", "GivenName": "Josh"}, "Bob"))

    def test_a_recruit_without_a_title_stays(self):
        self.assertIsNone(npc_names.recruit_name({"Name": "Josh", "GivenName": "Josh"}, "Josh"))

    def test_a_recruit_that_the_player_never_spoke_to_stays(self):
        self.assertIsNone(npc_names.recruit_name({"Name": "Starving Bandit"}, "Starving Bandit"))
        self.assertIsNone(npc_names.recruit_name({}, "Starving Bandit"))


if __name__ == "__main__":
    unittest.main()
