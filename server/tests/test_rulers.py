import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import background, prompts, rulers
from core import game, state
from store import campaign_db

HOLY_NATION, NOBLES = "1-gamedata.base", "2-gamedata.base"
SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "A world of sand.",
    "factions": [
        {"faction_id": HOLY_NATION, "name": "The Holy Nation", "aliases": [], "major": True, "fields": {"leader": "Holy Lord Phoenix"}, "description": "Zealots of Okran."},
        {"faction_id": NOBLES, "name": "Western Nobles", "aliases": [], "major": False, "fields": {"nobles": ["Lord Yoshinaga", "Lord Inaba", "Lady Tsugi"]}, "description": "Lords."},
    ],
    "history": [],
    "characters": [{"game_id": "17225-Dialogue.mod", "profile": {"Name": "Holy Lord Phoenix", "Faction": "The Holy Nation", "Backstory": "The Holy Lord."}}],
    "entities": [],
}
PHOENIX_DEAD = {"id": "17225-Dialogue.mod", "name": "Phoenix", "state": "dead"}


class CurrentTest(unittest.TestCase):
    NOBLES = {"name": "Western Nobles", "fields": {"nobles": ["Lord Yoshinaga", "Lord Inaba", "Lady Tsugi"]}}

    def test_each_state_names_the_rulers_in_it(self):
        fallen = {("lord", "yoshinaga"): "dead", ("lady", "tsugi"): "imprisoned", ("lord", "inaba"): "dead"}
        self.assertEqual(rulers.current(self.NOBLES, fallen)["fields"], {"nobles": ["Lord Yoshinaga", "Lord Inaba", "Lady Tsugi"], "dead": ["Lord Yoshinaga", "Lord Inaba"], "imprisoned": ["Lady Tsugi"]})

    def test_a_faction_whose_rulers_live_stays_as_it_is(self):
        self.assertIs(rulers.current(self.NOBLES, {("tinfist",): "imprisoned"}), self.NOBLES)

    def test_a_value_that_names_two_rulers_names_each_in_its_state(self):
        ninjas = {"name": "Black Dragon Ninjas", "fields": {"leader": "Dimak and Buzan"}}
        self.assertEqual(rulers.current(ninjas, {("buzan",): "dead"})["fields"], {"leader": "Dimak and Buzan", "dead": ["Buzan"]})


class FallenTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)

    def tearDown(self):
        state.UNIQUE_STATES = None
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def faction(self, name):
        return next(record for record in background.campaign_lore() if record["name"] == name)

    def test_the_name_of_the_canon_record_matches_a_ruler_that_the_game_names_otherwise(self):
        state.UNIQUE_STATES = [PHOENIX_DEAD]
        self.assertEqual(self.faction("The Holy Nation")["fields"], {"leader": "Holy Lord Phoenix", "dead": ["Holy Lord Phoenix"]})

    def test_an_alias_of_the_canon_record_matches_a_ruler(self):
        campaign_db.upsert_profile("u:17225-Dialogue.mod", {"Alias": "Phoenix, Holy Lord Phoenix LXII"})
        state.UNIQUE_STATES = [PHOENIX_DEAD]
        self.assertEqual(rulers.current({"name": "The Holy Nation", "fields": {"leader": "Holy Lord Phoenix LXII"}}, rulers.fallen())["fields"]["dead"], ["Holy Lord Phoenix LXII"])

    def test_the_game_name_matches_a_ruler_without_a_canon_record(self):
        state.UNIQUE_STATES = [{"id": "4-x.mod", "name": "Lady Tsugi", "state": "imprisoned"}]
        self.assertEqual(self.faction("Western Nobles")["fields"]["imprisoned"], ["Lady Tsugi"])

    def test_the_canon_record_of_a_dead_character_tells_the_state(self):
        state.UNIQUE_STATES = [PHOENIX_DEAD]
        self.assertEqual(self.faction("Holy Lord Phoenix")["fields"], {"faction": "The Holy Nation", "state": "dead"})

    def test_the_faction_of_the_npc_in_the_system_message_tells_the_state(self):
        state.UNIQUE_STATES = [PHOENIX_DEAD]
        self.assertEqual(prompts.describe_faction("The Holy Nation", HOLY_NATION), "The Holy Nation (leader: Holy Lord Phoenix; dead: Holy Lord Phoenix): Zealots of Okran.")


class GameStateTest(unittest.TestCase):
    def tearDown(self):
        state.UNIQUE_STATES = None

    def test_a_unique_character_is_alive_unless_the_game_lists_it(self):
        state.UNIQUE_STATES = [PHOENIX_DEAD]
        self.assertEqual((rulers.game_state("u:17225-Dialogue.mod"), rulers.game_state("u:59030-Dialogue.mod")), ("dead", "alive"))

    def test_the_state_is_unknown_for_a_generic_character_or_without_states(self):
        state.UNIQUE_STATES = []
        self.assertIsNone(rulers.game_state("h:10"))
        state.UNIQUE_STATES = None
        self.assertIsNone(rulers.game_state("u:59030-Dialogue.mod"))


class ReportTest(unittest.TestCase):
    def tearDown(self):
        state.UNIQUE_STATES = None

    def test_a_new_list_is_logged_once(self):
        with self.assertLogs(level="DEBUG") as logs:
            game.take_report(None, [], [], [PHOENIX_DEAD])
            game.take_report(None, [], [], [PHOENIX_DEAD])
        self.assertEqual([record.getMessage() for record in logs.records if record.getMessage().startswith("UNIQUES")], ["UNIQUES: Phoenix (17225-Dialogue.mod): dead"])
        self.assertEqual(state.UNIQUE_STATES, [PHOENIX_DEAD])

    def test_a_report_without_states_leaves_them_unknown(self):
        game.take_report(None, [], [], [PHOENIX_DEAD])
        game.take_report(None, [], [], None)
        self.assertIsNone(state.UNIQUE_STATES)


if __name__ == "__main__":
    unittest.main()
