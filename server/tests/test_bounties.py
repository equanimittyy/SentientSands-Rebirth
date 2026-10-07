import glob
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core import bounties
from core.paths import WORLD_TEMPLATES_DIR


class FactionTest(unittest.TestCase):
    def test_each_issuer_and_target_is_a_faction_of_the_vanilla_template_by_its_name(self):
        names = {data["game_id"]: data["name"] for data in (json.load(open(path, encoding="utf-8")) for path in glob.glob(os.path.join(WORLD_TEMPLATES_DIR, "kenshi_ssr_vanilla", "factions", "*.json")))}
        self.assertLessEqual(set(bounties.ISSUERS), set(names))
        self.assertEqual({game_id: names.get(game_id) for game_id in bounties.TARGETS}, bounties.TARGETS)


if __name__ == "__main__":
    unittest.main()
