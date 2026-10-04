import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import npc_names


def roll():
    return "Josh"


def fail():
    raise AssertionError("rolled a name for an NPC that has one")


class SplitTest(unittest.TestCase):
    def test_a_titled_template_gives_the_job_and_the_name_of_the_game(self):
        self.assertEqual(npc_names.split({"name": "Barman Arleen", "template": "Barman /GENNAME/"}), ("Arleen", "Barman"))
        self.assertEqual(npc_names.split({"name": "Shop Guard Ponzmin", "template": "Shop Guard /UCNAME/"}), ("Ponzmin", "Shop Guard"))

    def test_text_after_the_token_stays_out_of_the_name(self):
        self.assertEqual(npc_names.split({"name": "Fog Heavy Gorl ^^", "template": "Fog Heavy /CANNAME/ ^^"}), ("Gorl", "Fog Heavy"))

    def test_a_token_without_a_title_gives_no_job(self):
        self.assertEqual(npc_names.split({"name": "Nuno", "template": "/GENNAME/"}), ("Nuno", None))
        self.assertEqual(npc_names.split({"name": "Arleen the Blooded", "template": "/GENNAME/ the Blooded"}), ("Arleen", None))

    def test_a_name_that_the_player_gave_stays_whole(self):
        self.assertEqual(npc_names.split({"name": "Bob", "template": "Barman /GENNAME/"}), ("Bob", "Barman"))

    def test_a_template_without_a_token_is_the_job(self):
        self.assertEqual(npc_names.split({"name": "Dust Bandit", "template": "Dust Bandit"}), ("Dust Bandit", "Dust Bandit"))
        self.assertEqual(npc_names.split({"name": "Nuno", "template": "Drifter"}), ("Nuno", "Drifter"))

    def test_a_unique_npc_has_no_job_from_its_template(self):
        self.assertEqual(npc_names.split({"name": "Ruka", "template": "Ruka", "unique": True}), ("Ruka", None))

    def test_a_context_without_a_template_has_no_job(self):
        self.assertEqual(npc_names.split({"name": "Beep"}), ("Beep", None))


class UnnamedTest(unittest.TestCase):
    def test_only_a_generic_npc_with_the_template_name_is_unnamed(self):
        self.assertTrue(npc_names.unnamed({"name": "Dust Bandit", "template": "Dust Bandit"}))
        self.assertFalse(npc_names.unnamed({"name": "Barman Arleen", "template": "Barman /GENNAME/"}))
        self.assertFalse(npc_names.unnamed({"name": "Nuno", "template": "Drifter"}))
        self.assertFalse(npc_names.unnamed({"name": "Ruka", "template": "Ruka", "unique": True}))
        self.assertFalse(npc_names.unnamed({"name": "Beep"}))


class NamesTest(unittest.TestCase):
    def test_the_first_name_shows_the_game_name_as_a_title(self):
        self.assertEqual(npc_names.names({"Name": "Starving Bandit"}, "Starving Bandit", False, roll), ("Josh", "Starving Bandit Josh"))

    def test_a_recruit_gets_no_title(self):
        self.assertEqual(npc_names.names({"Name": "Starving Bandit"}, "Starving Bandit", True, roll), ("Josh", "Josh"))

    def test_a_rolled_name_that_the_game_lost_comes_back_with_its_title(self):
        profile = {"Name": "Josh", "GivenName": "Josh"}
        self.assertEqual(npc_names.names(profile, "Starving Bandit", False, fail), ("Josh", "Starving Bandit Josh"))
        self.assertEqual(npc_names.names(profile, "Starving Bandit", True, fail), ("Josh", "Josh"))

    def test_a_name_that_the_player_gave_comes_back_bare(self):
        self.assertEqual(npc_names.names({"Name": "Bob", "GivenName": None}, "Starving Bandit", False, fail), ("Bob", "Bob"))


class RecruitNameTest(unittest.TestCase):
    def test_a_recruit_drops_its_title(self):
        npc = {"name": "Starving Bandit Josh", "template": "Starving Bandit"}
        self.assertEqual(npc_names.recruit_name(npc, {"Name": "Josh", "GivenName": "Josh"}), "Josh")

    def test_a_name_that_the_player_gave_in_game_stays(self):
        self.assertIsNone(npc_names.recruit_name({"name": "Bob", "template": "Starving Bandit"}, {"Name": "Josh", "GivenName": "Josh"}))

    def test_a_recruit_without_a_title_stays(self):
        self.assertIsNone(npc_names.recruit_name({"name": "Josh", "template": "Starving Bandit"}, {"Name": "Josh", "GivenName": "Josh"}))

    def test_a_name_from_the_game_keeps_its_title(self):
        npc = {"name": "Barman Arleen", "template": "Barman /GENNAME/"}
        self.assertIsNone(npc_names.recruit_name(npc, {"Name": "Arleen"}))

    def test_a_recruit_that_the_player_never_spoke_to_stays(self):
        npc = {"name": "Starving Bandit", "template": "Starving Bandit"}
        self.assertIsNone(npc_names.recruit_name(npc, {"Name": "Starving Bandit"}))
        self.assertIsNone(npc_names.recruit_name(npc, {}))


if __name__ == "__main__":
    unittest.main()
