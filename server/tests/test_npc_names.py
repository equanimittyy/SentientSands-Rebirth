import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import npc_names


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

    def test_the_title_of_a_template_without_a_token_stays_out_of_the_name(self):
        self.assertEqual(npc_names.split({"name": "Dust Bandit Josh", "template": "Dust Bandit"}), ("Josh", "Dust Bandit"))
        self.assertEqual(npc_names.split({"name": "Drifter Nuno", "template": "Drifter"}), ("Nuno", "Drifter"))

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


class ShownTest(unittest.TestCase):
    def test_a_generic_npc_shows_its_job_as_a_title(self):
        self.assertEqual(npc_names.shown("h:1", {"Name": "Nuno", "Job": "Drifter"}, False), "Drifter Nuno")

    def test_a_member_of_the_player_faction_shows_no_title(self):
        self.assertEqual(npc_names.shown("h:1", {"Name": "Nuno", "Job": "Drifter"}, True), "Nuno")

    def test_a_canon_character_shows_no_title(self):
        self.assertEqual(npc_names.shown("u:Yamdu", {"Name": "Yamdu", "Job": "Writer and field researcher"}, False), "Yamdu")

    def test_an_npc_without_a_job_shows_no_title(self):
        for job in (None, "", "None", "Unknown"):
            self.assertEqual(npc_names.shown("h:1", {"Name": "Nuno", "Job": job}, False), "Nuno")
        self.assertEqual(npc_names.shown("h:1", {"Name": "Nuno"}, False), "Nuno")


class JobTextTest(unittest.TestCase):
    def test_a_job_shows_as_it_is(self):
        self.assertEqual(npc_names.job_text({"Job": "Shop Guard"}), "Shop Guard")

    def test_a_recruit_has_a_former_job(self):
        self.assertEqual(npc_names.job_text({"Job": "None", "FormerJob": "Shop Guard"}), "Former Shop Guard")

    def test_no_job_shows_as_none(self):
        self.assertEqual(npc_names.job_text({"Job": "Unknown"}), "None")
        self.assertEqual(npc_names.job_text({}), "None")


if __name__ == "__main__":
    unittest.main()
