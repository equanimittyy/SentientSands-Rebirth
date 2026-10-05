import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import characters
from store import campaign_db

SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "",
    "factions": [],
    "history": [],
    "characters": [],
    "entities": [],
}


class AnimalFlagTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)

    def tearDown(self):
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def test_the_game_flag_makes_an_animal_of_a_race_that_no_list_knows(self):
        profile = characters.get_character_data("Bone Mutt", {"npc_id": "h:1", "race": "Bone Mutt", "animal": True})
        self.assertEqual(campaign_db.get_character("h:1")["Animal"], 1)
        self.assertEqual((profile["Backstory"], profile["SpeechQuirks"]), ("", ""))
        self.assertNotIn(campaign_db.PROVISIONAL, profile)

    def test_a_fishman_is_an_animal_though_the_game_does_not_flag_it(self):
        for npc_id, race in (("h:5", "Fishman"), ("h:6", "Alpha Fishman olive")):
            characters.get_character_data("Gurgler", {"npc_id": npc_id, "race": race, "animal": False})
            self.assertEqual(campaign_db.get_character(npc_id)["Animal"], 1, race)

    def test_an_animal_keeps_the_name_of_its_template(self):
        npc = {"npc_id": "h:7", "name": "Bone Mutt", "template": "Bone Mutt", "race": "Bone Mutt", "animal": True}
        with mock.patch.object(characters, "send_rename") as rename:
            self.assertEqual(characters.npc_name(npc), "Bone Mutt")
        rename.assert_not_called()
        self.assertEqual(campaign_db.get_character("h:7")["Name"], "Bone Mutt")

    def test_a_person_shown_by_its_template_name_gets_a_rolled_name(self):
        npc = {"npc_id": "h:8", "name": "Dust Bandit", "template": "Dust Bandit", "race": "Greenlander", "animal": False}
        with mock.patch.object(characters, "send_rename") as rename:
            self.assertNotEqual(characters.npc_name(npc), "Dust Bandit")
        rename.assert_called_once()

    def test_a_person_stores_the_flag_as_0(self):
        profile = characters.get_character_data("Dust Bandit", {"npc_id": "h:2", "race": "Greenlander", "animal": False})
        self.assertEqual(campaign_db.get_character("h:2")["Animal"], 0)
        self.assertIn(campaign_db.PROVISIONAL, profile)

    def test_a_stored_profile_takes_the_flag_of_the_game(self):
        campaign_db.upsert_profile("h:3", {"Name": "Vert", "Race": "Bone Mutt", "Personality": "Friendly."})
        characters.get_character_data("Vert", {"npc_id": "h:3", "race": "Bone Mutt", "animal": True})
        self.assertEqual(campaign_db.get_character("h:3")["Animal"], 1)

    def test_a_context_without_the_flag_keeps_the_stored_one(self):
        campaign_db.upsert_profile("h:4", {"Name": "Vert", "Race": "Bone Mutt", "Animal": 1, "Personality": "Friendly."})
        characters.get_character_data("Vert", {"npc_id": "h:4", "race": "Bone Mutt"})
        self.assertEqual(campaign_db.get_character("h:4")["Animal"], 1)


if __name__ == "__main__":
    unittest.main()
