import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import background, knowledge, prompts, towns
from core import game, state
from store import campaign_db

UNITED_CITIES, REAVERS = "1-gamedata.base", "2-gamedata.base"
BRINK = {"name": "Brink", "fields": {"type": "town", "zone": ["Stormgap Coast"], "owner": ["United Cities"]}, "description": "Brink is a United Cities town."}
RUIN = {"name": "Free Settlement", "fields": {"type": "ruins", "owner": ["United Cities"]}, "description": "An empty town."}

SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "A world of sand.",
    "factions": [
        {"faction_id": UNITED_CITIES, "name": "United Cities", "aliases": [], "major": True, "fields": {}, "description": "The Empire."},
        {"faction_id": REAVERS, "name": "Reavers", "aliases": [], "major": False, "fields": {}, "description": "Raiders of the coast."},
    ],
    "history": [],
    "characters": [],
    "entities": [
        {"category": "regions", "id": "stormgap_coast", "data": {"name": "Stormgap Coast", "fields": {}, "description": "A stormy coast."}},
        {"category": "locations", "id": "brink", "data": BRINK},
    ],
}


def faction(name):
    return {"name": name, "aliases": []}


class ChangedTest(unittest.TestCase):
    def test_a_new_owner_holds_the_town(self):
        found = towns.changed(BRINK, "town", faction("Reavers"))
        self.assertEqual(found["fields"], {"type": "town", "zone": ["Stormgap Coast"], "owner": ["Reavers"]})
        self.assertEqual(found["change"], "Brink is now a town held by Reavers. It was a town of United Cities before.")
        self.assertEqual(found["description"], "Brink is now a town held by Reavers. It was a town of United Cities before. Brink is a United Cities town.")

    def test_a_town_that_falls_to_ruins_keeps_its_owner_as_the_former_owner(self):
        found = towns.changed(BRINK, "ruins", faction("Reavers"))
        self.assertEqual(found["fields"]["owner"], ["United Cities"])
        self.assertEqual(found["change"], "Brink is now ruins. It was a town of United Cities before.")

    def test_a_new_owner_of_a_ruin_changes_nothing(self):
        self.assertIs(towns.changed(RUIN, "ruins", faction("Reavers")), RUIN)

    def test_a_ruin_that_becomes_a_town_names_no_former_owner(self):
        self.assertEqual(towns.changed(RUIN, "town", faction("Anti-Slavers"))["change"], "Free Settlement is now a town held by Anti-Slavers. It was ruins before.")

    def test_the_same_owner_and_type_change_nothing(self):
        self.assertIs(towns.changed(BRINK, "town", faction("The United Cities")), BRINK)

    def test_a_town_without_an_owner_loses_its_owner(self):
        found = towns.changed(BRINK, "outpost", None)
        self.assertNotIn("owner", found["fields"])
        self.assertEqual(found["change"], "Brink is now an outpost. It was a town of United Cities before.")


class CurrentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)

    def tearDown(self):
        state.CHANGED_TOWNS = []
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def brink(self):
        return next(record for record in background.campaign_lore() if record["name"] == "Brink")

    def test_the_owner_takes_the_name_of_its_faction_record(self):
        state.CHANGED_TOWNS = [{"name": "Brink", "owner": "Reaver Raiders", "owner_id": REAVERS, "type": 2}]
        self.assertEqual(self.brink()["fields"]["owner"], ["Reavers"])
        self.assertEqual(prompts.find_location("Brink")["change"], "Brink is now a town held by Reavers. It was a town of United Cities before.")

    def test_a_town_that_no_report_names_stays_as_the_template_has_it(self):
        state.CHANGED_TOWNS = [{"name": "Squin", "owner": "Reavers", "owner_id": REAVERS, "type": 2}]
        self.assertEqual(self.brink()["fields"]["owner"], ["United Cities"])

    def test_a_town_that_its_faction_took_is_home(self):
        reavers = ("factions", REAVERS)
        self.assertNotIn(self.brink()["key"], knowledge.known(background.campaign_lore(), {reavers}, reavers))
        state.CHANGED_TOWNS = [{"name": "Brink", "owner": "Reavers", "owner_id": REAVERS, "type": 2}]
        self.assertFalse(knowledge.known(background.campaign_lore(), {reavers}, reavers)[self.brink()["key"]])


class OutpostTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)

    def tearDown(self):
        state.SEEN_OUTPOSTS = None
        state.SEEN_FACTIONS.clear()
        state.PLAYER_CONTEXT = {}
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def report(self, *towns, listed=True):
        player = {"faction": "Nameless", "factionID": "204-gamedata.base"}
        game.take_report(player, [], [], [], [{"key": key, "name": name, "zone": zone} for key, name, zone in towns] if listed else None)

    def outposts(self):
        return {ext_id: data for (category, ext_id), data, *_ in campaign_db.list_records("entity") if category == "locations" and ext_id.startswith("t:")}

    def describe(self, ext_id, text):
        key, data, _, updated_at = next(record for record in campaign_db.list_records("entity") if record[0] == ("locations", ext_id))
        campaign_db.save_record("entity", key, {**data, "description": text}, updated_at)

    def test_a_listed_town_of_the_player_gets_an_empty_location_record(self):
        self.report(("t:1", "Your Outpost", "Border Zone"))
        self.assertEqual(self.outposts(), {"t:1": {"name": "Your Outpost", "aliases": [], "fields": {"type": "outpost", "zone": ["Border Zone"], "owner": ["Nameless"]}, "description": ""}})

    def test_two_outposts_of_one_name_in_one_zone_keep_two_records(self):
        self.report(("t:1", "Your Outpost", "Border Zone"), ("t:2", "Your Outpost", "Border Zone"))
        self.describe("t:2", "The second one.")
        self.assertEqual(list(self.outposts()), ["t:1", "t:2"])
        self.assertEqual(prompts.find_location("Your Outpost", "t:2")["description"], "The second one.")

    def test_a_rename_in_game_keeps_the_description(self):
        self.report(("t:1", "Your Outpost", "Border Zone"))
        self.describe("t:1", "Walls of scrap.")
        self.report(("t:1", "Sandhold", "Border Zone"))
        self.assertEqual((self.outposts()["t:1"]["name"], self.outposts()["t:1"]["description"]), ("Sandhold", "Walls of scrap."))

    def test_an_outpost_that_the_game_no_longer_lists_loses_its_record(self):
        self.report(("t:1", "Your Outpost", "Border Zone"), ("t:2", "Your Outpost", "Border Zone"))
        self.report(("t:2", "Your Outpost", "Border Zone"))
        self.assertEqual(list(self.outposts()), ["t:2"])
        self.assertIn("brink", [ext_id for (category, ext_id), *_ in campaign_db.list_records("entity") if category == "locations"])

    def test_a_plugin_without_the_list_keeps_every_record(self):
        self.report(("t:1", "Your Outpost", "Border Zone"))
        self.report(listed=False)
        self.assertEqual(list(self.outposts()), ["t:1"])


class ReportTest(unittest.TestCase):
    def tearDown(self):
        state.CHANGED_TOWNS = []

    def test_a_new_list_is_logged_once(self):
        towns = [{"name": "Brink", "owner": "Reavers", "owner_id": REAVERS, "type": 2}]
        with self.assertLogs(level="DEBUG") as logs:
            game.take_report(None, [], towns, [])
            game.take_report(None, [], towns, [])
        self.assertEqual([record.getMessage() for record in logs.records if record.getMessage().startswith("TOWNS")], [f"TOWNS: Brink: owner Reavers ({REAVERS}), type 2"])


if __name__ == "__main__":
    unittest.main()
