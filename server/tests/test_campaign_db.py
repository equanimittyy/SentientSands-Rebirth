import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import campaign_db

BEEP = {
    "ID": "Beep",
    "Name": "Beep",
    "Race": "Hive Worker Drone",
    "Personality": "Cheerful.",
    "Relation": 5,
    "ConversationHistory": ["[Day 1, 08:00] Drifter: Hello", "[Day 2, 09:30] Beep: Beep is happy!"],
}


SEED = {
    "template": {"name": "vanilla_kenshi", "version": "1.0.0", "hash": "abc"},
    "overview": "Kenshi is a world of rust.",
    "factions": [
        {"faction_id": "1083-gamedata.base", "name": "The Holy Nation", "aliases": ["Okranites"], "major": True, "fields": {"leader": "Phoenix"}, "description": "Zealots."},
        {"faction_id": "204-gamedata.base", "name": "Nameless", "aliases": [], "major": False, "fields": {}, "description": "Wanderers."},
    ],
}


class CampaignTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class OpenTest(CampaignTestCase):
    def test_a_new_campaign_gets_an_empty_database(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertEqual(campaign_db.list_npcs(), [])

    def test_a_creation_that_stops_before_the_rename_runs_again(self):
        with mock.patch.object(campaign_db.os, "replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME)))

        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertEqual(campaign_db.list_npcs(), [])
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME + ".tmp")))

    def test_a_new_campaign_copies_the_template(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertEqual(campaign_db.overview(), "Kenshi is a world of rust.")
        self.assertEqual(campaign_db.template_info(), {"name": "vanilla_kenshi", "version": "1.0.0", "hash": "abc"})
        self.assertEqual([(f["name"], f["origin"]) for f in campaign_db.list_factions()], [("Nameless", "template"), ("The Holy Nation", "template")])

    def test_the_seed_is_read_only_for_a_new_database(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        campaign_db.open_campaign(self.folder, mock.Mock(side_effect=AssertionError("seed read again")))
        self.assertEqual(campaign_db.overview(), "Kenshi is a world of rust.")

    def test_an_earlier_schema_version_is_refused_and_closes_the_campaign(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        conn = sqlite3.connect(os.path.join(self.folder, campaign_db.DB_NAME))
        with conn:
            conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        conn.close()
        with self.assertRaises(campaign_db.CampaignUnavailable):
            campaign_db.open_campaign(self.folder, lambda: SEED)
        with self.assertRaisesRegex(campaign_db.CampaignUnavailable, "Start a new campaign"):
            campaign_db.list_npcs()

    def test_a_missing_database_fails_instead_of_being_created(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        os.remove(os.path.join(self.folder, campaign_db.DB_NAME))
        with self.assertRaises(sqlite3.OperationalError):
            campaign_db.get_npc("Beep")
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME)))


class NpcTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)

    def test_upsert_with_one_key_keeps_the_other_keys(self):
        campaign_db.upsert_profile("Beep", BEEP)
        campaign_db.upsert_profile("Beep", {"Relation": 9})
        self.assertEqual(campaign_db.get_npc("Beep"), {**BEEP, "Relation": 9, "ConversationHistory": []})

    def test_concurrent_appends_keep_the_lines_of_both(self):
        campaign_db.upsert_profile("Beep", BEEP)
        threads = [threading.Thread(target=campaign_db.append_dialogue, args=("Beep", [f"line {i}"], BEEP)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(campaign_db.get_npc("Beep")["ConversationHistory"]), [f"line {i}" for i in range(8)])

    def test_concurrent_relation_changes_keep_every_change(self):
        campaign_db.upsert_profile("Beep", BEEP)
        threads = [threading.Thread(target=campaign_db.change_relation, args=("Beep", 1)) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(campaign_db.get_npc("Beep")["Relation"], 25)

    def test_relation_change_clamps_and_skips_a_missing_npc(self):
        campaign_db.upsert_profile("Beep", BEEP)
        self.assertEqual(campaign_db.change_relation("Beep", 200), 100)
        self.assertEqual(campaign_db.change_relation("Beep", -300), -100)
        self.assertIsNone(campaign_db.change_relation("Nobody", 1))

    def test_underscore_keys_are_not_stored(self):
        campaign_db.append_dialogue("Beep", ["a"], {"Name": "Beep", "_transient": True})
        campaign_db.upsert_profile("Beep", {"Relation": 1, "_transient": True})
        self.assertEqual(campaign_db.get_npc("Beep"), {"Name": "Beep", "Relation": 1, "ConversationHistory": ["a"]})

    def test_append_stores_the_profile_only_when_missing(self):
        campaign_db.append_dialogue("Beep", ["a"], {"Name": "Beep"})
        campaign_db.append_dialogue("Beep", ["b"], {"Name": "Other"})
        self.assertEqual(campaign_db.get_npc("Beep"), {"Name": "Beep", "ConversationHistory": ["a", "b"]})

    def test_dialogue_keeps_the_newest_250_lines(self):
        campaign_db.append_dialogue("Beep", [f"line {i}" for i in range(300)], BEEP)
        history = campaign_db.get_npc("Beep")["ConversationHistory"]
        self.assertEqual(history, [f"line {i}" for i in range(50, 300)])

    def test_storage_ids_keep_the_file_name_sanitizing_and_ignore_case(self):
        campaign_db.upsert_profile("Beep!", {"Name": "Beep!"})
        self.assertTrue(campaign_db.npc_exists("beep"))
        self.assertEqual([n["storage_id"] for n in campaign_db.list_npcs()], ["Beep"])

    def test_rename_keeps_the_dialogue_and_the_favorite(self):
        campaign_db.append_dialogue("Beep", ["hello"], BEEP)
        campaign_db.toggle_favorite("Beep")
        self.assertTrue(campaign_db.rename_npc("Beep", "Bop", "Bop"))
        self.assertIsNone(campaign_db.get_npc("Beep"))
        npc = campaign_db.get_npc("Bop")
        self.assertEqual((npc["ID"], npc["Name"], npc["ConversationHistory"]), ("Bop", "Bop", ["hello"]))
        self.assertEqual(campaign_db.list_npcs()[0]["favorite"], True)

    def test_rename_to_a_taken_id_changes_nothing(self):
        campaign_db.upsert_profile("Beep", BEEP)
        campaign_db.upsert_profile("Bop", {"Name": "Bop"})
        self.assertFalse(campaign_db.rename_npc("Beep", "Bop", "Bop"))
        self.assertEqual(campaign_db.get_npc("Beep")["Name"], "Beep")

    def test_toggle_favorite(self):
        campaign_db.upsert_profile("Beep", BEEP)
        self.assertTrue(campaign_db.toggle_favorite("Beep"))
        self.assertFalse(campaign_db.toggle_favorite("Beep"))
        self.assertIsNone(campaign_db.toggle_favorite("Nobody"))


class EventTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)

    @mock.patch.object(campaign_db, "MAX_EVENTS", 5)
    def test_keeps_the_newest_events_and_skips_duplicates(self):
        for i in range(8):
            campaign_db.add_event(f"event {i}")
        campaign_db.add_event("event 7")
        self.assertEqual(campaign_db.recent_events(100), [f"event {i}" for i in range(3, 8)])
        self.assertEqual(campaign_db.recent_events(2), ["event 6", "event 7"])

    def test_cull_deletes_only_later_rows(self):
        campaign_db.append_dialogue("Beep", ["[Day 2, 09:59] early", "[Day 2, 10:01] late", "untimed"], BEEP)
        campaign_db.add_event("[Day 2, 10:00] same minute")
        campaign_db.add_event("[Day 3] next day")
        campaign_db.add_rumor("- [Day 1, 00:00] [RUMOR: old]")
        campaign_db.add_rumor("- [Day 5, 00:00] [RUMOR: new]")

        self.assertEqual(campaign_db.cull_after(2, 10, 0), {"dialogue": 1, "event": 1, "rumor": 1})
        self.assertEqual(campaign_db.get_npc("Beep")["ConversationHistory"], ["[Day 2, 09:59] early", "untimed"])
        self.assertEqual(campaign_db.recent_events(10), ["[Day 2, 10:00] same minute"])
        self.assertEqual([line for _, line in campaign_db.rumors()], ["- [Day 1, 00:00] [RUMOR: old]"])

    def test_rumor_by_id(self):
        campaign_db.add_rumor("- [Day 1, 00:00] [RUMOR: one]")
        (rumor_id, line), = campaign_db.rumors()
        self.assertEqual(campaign_db.rumor(rumor_id), line)
        self.assertIsNone(campaign_db.rumor(rumor_id + 1))

    def test_rumor_edit_moves_its_game_time(self):
        campaign_db.add_rumor("- [Day 1, 00:00] [RUMOR: one]")
        (rumor_id, _), = campaign_db.rumors()
        self.assertTrue(campaign_db.set_rumor(rumor_id, "- [Day 9, 00:00] [RUMOR: two]"))
        self.assertEqual(campaign_db.cull_after(5, 0, 0)["rumor"], 1)
        self.assertFalse(campaign_db.set_rumor(rumor_id, "gone"))

    def test_delete_event_and_rumor(self):
        campaign_db.add_event("[Day 1] one")
        campaign_db.add_rumor("- [Day 1, 00:00] [RUMOR: one]")
        (event_id, _), = campaign_db.events()
        (rumor_id, _), = campaign_db.rumors()
        self.assertTrue(campaign_db.delete_event(event_id))
        self.assertTrue(campaign_db.delete_rumor(rumor_id))
        self.assertFalse(campaign_db.delete_event(event_id))
        self.assertEqual((campaign_db.events(), campaign_db.rumors()), ([], []))


class FactionTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)

    def test_find_by_id_then_by_name_or_alias_ignoring_case(self):
        self.assertEqual(campaign_db.find_faction("1083-gamedata.base")["name"], "The Holy Nation")
        self.assertEqual(campaign_db.find_faction("unknown-id", "the holy nation")["faction_id"], "1083-gamedata.base")
        self.assertEqual(campaign_db.find_faction(None, "OKRANITES")["faction_id"], "1083-gamedata.base")
        self.assertIsNone(campaign_db.find_faction(None, "Holy Nation Outlaws"))

    def test_a_reported_faction_gets_an_empty_row_once(self):
        campaign_db.note_faction("42022-rebirth.mod", "Holy Nation Outlaws")
        campaign_db.note_faction("42022-rebirth.mod", "Renamed")
        faction = campaign_db.find_faction("42022-rebirth.mod")
        self.assertEqual((faction["name"], faction["description"], faction["origin"]), ("Holy Nation Outlaws", "", "campaign"))

    def test_the_player_faction_follows_the_game_name(self):
        campaign_db.note_faction("204-gamedata.base", "Nameless", is_player=True)
        campaign_db.note_faction("204-gamedata.base", "Sand Rats", is_player=True)
        faction = campaign_db.player_faction()
        self.assertEqual((faction["faction_id"], faction["name"], faction["description"]), ("204-gamedata.base", "Sand Rats", "Wanderers."))
        self.assertEqual(campaign_db.list_factions()[0]["name"], "Sand Rats")

    def test_a_new_player_faction_clears_the_old_mark(self):
        campaign_db.note_faction("204-gamedata.base", "Nameless", is_player=True)
        campaign_db.note_faction("9-other.mod", "Other", is_player=True)
        self.assertEqual(campaign_db.player_faction()["faction_id"], "9-other.mod")
        self.assertFalse(campaign_db.find_faction("204-gamedata.base")["is_player"])

    def test_update_keeps_the_other_keys(self):
        faction = campaign_db.find_faction("1083-gamedata.base")
        saved = campaign_db.update_faction("1083-gamedata.base", {"description": "Okran's own.", "major": False}, faction["updated_at"])
        self.assertEqual((saved["description"], saved["major"], saved["fields"], saved["aliases"]), ("Okran's own.", False, {"leader": "Phoenix"}, ["Okranites"]))

    def test_a_stale_update_is_rejected(self):
        faction = campaign_db.find_faction("204-gamedata.base")
        with mock.patch.object(campaign_db, "_now", return_value="2099-01-01T00:00:00.000+00:00"):
            campaign_db.note_faction("204-gamedata.base", "Sand Rats", is_player=True)
        with self.assertRaises(campaign_db.StaleRecord):
            campaign_db.update_faction("204-gamedata.base", {"description": "Mine."}, faction["updated_at"])
        self.assertEqual(campaign_db.player_faction()["description"], "Wanderers.")

    def test_update_of_a_missing_faction(self):
        self.assertIsNone(campaign_db.update_faction("nope", {"description": "x"}, "t"))

    def test_overview_edit(self):
        campaign_db.set_overview("A new world.")
        self.assertEqual(campaign_db.overview(), "A new world.")


if __name__ == "__main__":
    unittest.main()
