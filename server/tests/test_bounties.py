import glob
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core import bounties
from core.paths import WORLD_TEMPLATES_DIR

HOLY_NATION, UNITED_CITIES, SHEK_KINGDOM = bounties.ISSUERS


def faction(faction_id, name, enemies=(), aliases=()):
    return {"faction_id": faction_id, "name": name, "aliases": list(aliases), "fields": {"enemies": list(enemies)}}


class IssuerTest(unittest.TestCase):
    def test_an_issuer_in_either_list_counts(self):
        target = faction("200-a", "Dust Bandits", ["Holy Nation"])
        factions = [target, faction(HOLY_NATION, "The Holy Nation"), faction(UNITED_CITIES, "United Cities", ["Dust Bandits"]), faction(SHEK_KINGDOM, "Shek Kingdom")]
        self.assertEqual(bounties.issuer_ids(target, factions), [HOLY_NATION, UNITED_CITIES])

    def test_an_alias_names_the_issuer(self):
        target = faction("200-a", "Rebel Farmers", ["The Empire"])
        self.assertEqual(bounties.issuer_ids(target, [target, faction(UNITED_CITIES, "United Cities", aliases=["The Empire"])]), [UNITED_CITIES])

    def test_an_enemy_that_is_no_issuer_and_the_own_faction_drop_out(self):
        target = faction(HOLY_NATION, "The Holy Nation", ["The Holy Nation", "Flotsam Ninjas"])
        self.assertEqual(bounties.issuer_ids(target, [target, faction("300-a", "Flotsam Ninjas")]), [])

    def test_each_issuer_is_a_faction_of_the_vanilla_template(self):
        ids = {json.load(open(path, encoding="utf-8"))["game_id"] for path in glob.glob(os.path.join(WORLD_TEMPLATES_DIR, "kenshi_ssr_vanilla", "factions", "*.json"))}
        self.assertLessEqual(set(bounties.ISSUERS), ids)


if __name__ == "__main__":
    unittest.main()
