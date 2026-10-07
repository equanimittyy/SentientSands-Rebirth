import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import retrieval
from core import bounties


def faction(faction_id, name, enemies=(), aliases=(), major=False, territory=()):
    return {"faction_id": faction_id, "name": name, "aliases": list(aliases), "major": major, "fields": {"enemies": list(enemies), "territory": list(territory)}}


def region(name, *neighbours):
    return ("regions", name.lower(), {"name": name, "fields": {"neighbours": {other: "east" for other in neighbours}}})


class EnemyTest(unittest.TestCase):
    def test_an_enemy_in_either_list_counts(self):
        target = faction("1-a", "Dust Bandits", ["Holy Nation"])
        factions = [target, faction("2-a", "The Holy Nation"), faction("3-a", "United Cities", ["Dust Bandits"]), faction("4-a", "Shek Kingdom")]
        self.assertEqual(bounties.enemy_ids(target, factions), ["2-a", "3-a"])

    def test_an_alias_names_the_enemy(self):
        target = faction("1-a", "Dust Bandits", ["The Empire"])
        self.assertEqual(bounties.enemy_ids(target, [target, faction("2-a", "United Cities", aliases=["The Empire"])]), ["2-a"])

    def test_the_own_faction_and_a_faction_without_a_game_id_drop_out(self):
        target = faction("1-a", "Dust Bandits", ["Dust Bandits", "Rebel Farmers"])
        self.assertEqual(bounties.enemy_ids(target, [target, faction(None, "Rebel Farmers")]), [])


class IssuerTest(unittest.TestCase):
    def setUp(self):
        self.target = faction("1-t", "Bandits", ["Far Major", "Near Major", "Near Minor", "Landless Major"])
        self.factions = [
            self.target, faction("2-t", "Far Major", major=True, territory=["Cold"]), faction("3-t", "Near Major", major=True, territory=["Middle"]),
            faction("4-t", "Near Minor", territory=["Home"]), faction("5-t", "Landless Major", major=True),
        ]
        regions = [region("Home", "Middle"), region("Middle", "Cold"), region("Cold")]
        self.lore = retrieval.lore_records(regions, self.factions, [])

    def test_the_major_factions_come_first_and_each_group_nearest_first(self):
        self.assertEqual(bounties.issuer_ids(self.target, self.factions, self.lore, None, "Home", shuffle=lambda ids: None), ["3-t", "2-t", "5-t", "4-t"])

    def test_an_unknown_place_keeps_the_major_factions_first(self):
        self.assertEqual(bounties.issuer_ids(self.target, self.factions, self.lore, None, None, shuffle=lambda ids: None), ["2-t", "3-t", "5-t", "4-t"])


if __name__ == "__main__":
    unittest.main()
