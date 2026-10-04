import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import npc_names


class NameOfTest(unittest.TestCase):
    def test_a_titled_template_gives_the_name_of_the_game(self):
        self.assertEqual(npc_names.name_of({"name": "Barman Arleen", "template": "Barman /GENNAME/"}), "Arleen")
        self.assertEqual(npc_names.name_of({"name": "Shop Guard Ponzmin", "template": "Shop Guard /UCNAME/"}), "Ponzmin")

    def test_text_after_the_token_stays_out_of_the_name(self):
        self.assertEqual(npc_names.name_of({"name": "Fog Heavy Gorl ^^", "template": "Fog Heavy /CANNAME/ ^^"}), "Gorl")
        self.assertEqual(npc_names.name_of({"name": "Arleen the Blooded", "template": "/GENNAME/ the Blooded"}), "Arleen")

    def test_a_name_that_the_player_gave_stays_whole(self):
        self.assertEqual(npc_names.name_of({"name": "Bob", "template": "Barman /GENNAME/"}), "Bob")

    def test_a_template_without_a_token_gives_the_whole_game_name(self):
        self.assertEqual(npc_names.name_of({"name": "Dust Bandit", "template": "Dust Bandit"}), "Dust Bandit")
        self.assertEqual(npc_names.name_of({"name": "Nuno", "template": "Drifter"}), "Nuno")

    def test_a_unique_npc_keeps_its_whole_game_name(self):
        self.assertEqual(npc_names.name_of({"name": "Ruka", "template": "Ruka", "unique": True}), "Ruka")
        self.assertEqual(npc_names.name_of({"name": "Beep"}), "Beep")


class UnnamedTest(unittest.TestCase):
    def test_only_a_generic_npc_with_the_template_name_is_unnamed(self):
        self.assertTrue(npc_names.unnamed({"name": "Dust Bandit", "template": "Dust Bandit"}))
        self.assertFalse(npc_names.unnamed({"name": "Barman Arleen", "template": "Barman /GENNAME/"}))
        self.assertFalse(npc_names.unnamed({"name": "Nuno", "template": "Drifter"}))
        self.assertFalse(npc_names.unnamed({"name": "Ruka", "template": "Ruka", "unique": True}))
        self.assertFalse(npc_names.unnamed({"name": "Beep"}))


if __name__ == "__main__":
    unittest.main()
