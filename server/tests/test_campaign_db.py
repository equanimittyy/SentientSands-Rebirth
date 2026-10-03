import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import campaign_db

BEEP_ID = "u:19576-Dialogue.mod"
GENERIC_ID = "h:2717040896"

BEEP = {
    "Name": "Beep",
    "Race": "Hive Worker Drone",
    "Personality": "Cheerful.",
    "Relation": 5,
    "ConversationHistory": ["[Day 1, 08:00] Drifter: Hello", "[Day 2, 09:30] Beep: Beep is happy!"],
}


SEED = {
    "template": {"name": "kenshi_ssr_vanilla", "version": "1.0.0", "hash": "abc"},
    "overview": "Kenshi is a world of rust.",
    "factions": [
        {"faction_id": "1083-gamedata.base", "name": "The Holy Nation", "aliases": ["Okranites"], "major": True, "fields": {"leader": "Phoenix"}, "description": "Zealots."},
        {"faction_id": "204-gamedata.base", "name": "Nameless", "aliases": [], "major": False, "fields": {}, "description": "Wanderers."},
    ],
    "history": [{"title": "The First Empire", "text": "It fell."}],
    "characters": [{"game_id": "19576-Dialogue.mod", "profile": {"Name": "Beep", "Race": "Hive Worker Drone"}}],
    "entities": [{"category": "locations", "id": "the_hub", "data": {"name": "The Hub", "fields": {"owner": "Nameless"}}}],
}


class CampaignTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class OpenTest(CampaignTestCase):
    def test_a_new_campaign_holds_only_the_template_characters(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertEqual([(c["npc_id"], c["name"], c["origin"], c["has_dialogue"]) for c in campaign_db.list_characters()], [(BEEP_ID, "Beep", "seed", False)])

    def test_a_creation_that_stops_before_the_rename_runs_again(self):
        with mock.patch.object(campaign_db.os, "replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME)))

        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertEqual(len(campaign_db.list_characters()), 1)
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME + ".tmp")))

    def test_a_new_campaign_copies_the_template(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertEqual(campaign_db.overview(), "Kenshi is a world of rust.")
        self.assertEqual(campaign_db.template_info(), {"name": "kenshi_ssr_vanilla", "version": "1.0.0", "hash": "abc"})
        self.assertEqual([(f["name"], f["origin"]) for f in campaign_db.list_factions()], [("Nameless", "seed"), ("The Holy Nation", "seed")])
        self.assertEqual(campaign_db.history(), [{"title": "The First Empire", "text": "It fell."}])
        self.assertEqual([record[:3] for record in campaign_db.list_records("character")], [((BEEP_ID,), {"Name": "Beep", "Race": "Hive Worker Drone"}, "seed")])
        self.assertEqual([record[:3] for record in campaign_db.list_records("entity")], [(("locations", "the_hub"), {"name": "The Hub", "fields": {"owner": "Nameless"}}, "seed")])

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
            campaign_db.list_characters()

    def test_a_missing_database_fails_instead_of_being_created(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        os.remove(os.path.join(self.folder, campaign_db.DB_NAME))
        with self.assertRaisesRegex(campaign_db.CampaignUnavailable, "has no campaign.db file"):
            campaign_db.get_character(BEEP_ID)
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME)))

    def test_a_closed_campaign_fails_with_the_reason(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        campaign_db.close_campaign()
        with self.assertRaisesRegex(campaign_db.CampaignUnavailable, "No campaign is selected"):
            campaign_db.list_characters()


class CharacterTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)

    def test_upsert_with_one_key_keeps_the_other_keys(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        campaign_db.upsert_profile(GENERIC_ID, {"Relation": 9})
        self.assertEqual(campaign_db.get_character(GENERIC_ID), {**BEEP, "Relation": 9, "ConversationHistory": []})

    def test_concurrent_appends_keep_the_lines_of_both(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        threads = [threading.Thread(target=campaign_db.append_dialogue, args=(GENERIC_ID, [f"line {i}"], BEEP)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(campaign_db.get_character(GENERIC_ID)["ConversationHistory"]), [f"line {i}" for i in range(8)])

    def test_concurrent_relation_changes_keep_every_change(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        threads = [threading.Thread(target=campaign_db.change_relation, args=(GENERIC_ID, 1)) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(campaign_db.get_character(GENERIC_ID)["Relation"], 25)

    def test_relation_change_clamps_and_skips_a_missing_character(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        self.assertEqual(campaign_db.change_relation(GENERIC_ID, 200), 100)
        self.assertEqual(campaign_db.change_relation(GENERIC_ID, -300), -100)
        self.assertIsNone(campaign_db.change_relation("h:1", 1))

    def test_underscore_keys_are_not_stored(self):
        campaign_db.append_dialogue(GENERIC_ID, ["a"], {"Name": "Beep", "_transient": True})
        campaign_db.upsert_profile(GENERIC_ID, {"Relation": 1, "_transient": True})
        self.assertEqual(campaign_db.get_character(GENERIC_ID), {"Name": "Beep", "Relation": 1, "ConversationHistory": ["a"]})

    def test_append_stores_the_profile_only_when_missing(self):
        campaign_db.append_dialogue(GENERIC_ID, ["a"], {"Name": "Beep"})
        campaign_db.append_dialogue(GENERIC_ID, ["b"], {"Name": "Other"})
        self.assertEqual(campaign_db.get_character(GENERIC_ID), {"Name": "Beep", "ConversationHistory": ["a", "b"]})

    def test_a_template_character_keeps_its_canon_profile_in_chat(self):
        campaign_db.append_dialogue(BEEP_ID, ["hello"], {"Name": "Beep", "Personality": "Generated."})
        self.assertEqual(campaign_db.get_character(BEEP_ID), {"Name": "Beep", "Race": "Hive Worker Drone", "ConversationHistory": ["hello"]})
        self.assertEqual([(c["origin"], c["has_dialogue"]) for c in campaign_db.list_characters()], [("seed", True)])

    def test_a_character_met_in_play_has_the_game_origin(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        self.assertEqual({c["npc_id"]: c["origin"] for c in campaign_db.list_characters()}[GENERIC_ID], "game")

    def test_dialogue_keeps_the_newest_250_lines(self):
        campaign_db.append_dialogue(GENERIC_ID, [f"line {i}" for i in range(300)], BEEP)
        history = campaign_db.get_character(GENERIC_ID)["ConversationHistory"]
        self.assertEqual(history, [f"line {i}" for i in range(50, 300)])

    def test_two_npcs_with_one_name_keep_separate_rows(self):
        campaign_db.append_dialogue("h:1", ["to the first"], {"Name": "Bob"})
        campaign_db.append_dialogue("h:2", ["to the second"], {"Name": "Bob"})
        self.assertEqual(campaign_db.get_character("h:1")["ConversationHistory"], ["to the first"])
        self.assertEqual(campaign_db.get_character("h:2")["ConversationHistory"], ["to the second"])

    def test_an_npc_id_is_exact(self):
        campaign_db.upsert_profile("u:5-Mod Name.mod", {"Name": "Ace"})
        self.assertTrue(campaign_db.character_exists("u:5-Mod Name.mod"))
        self.assertFalse(campaign_db.character_exists("U:5-mod name.mod"))

    def test_a_rename_keeps_the_dialogue_and_the_favorite(self):
        campaign_db.append_dialogue(GENERIC_ID, ["hello"], BEEP)
        campaign_db.toggle_favorite(GENERIC_ID)
        campaign_db.upsert_profile(GENERIC_ID, {"Name": "Bop"})
        character = campaign_db.get_character(GENERIC_ID)
        self.assertEqual((character["Name"], character["ConversationHistory"]), ("Bop", ["hello"]))
        self.assertTrue({c["npc_id"]: c["favorite"] for c in campaign_db.list_characters()}[GENERIC_ID])

    def test_toggle_favorite(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        self.assertTrue(campaign_db.toggle_favorite(GENERIC_ID))
        self.assertFalse(campaign_db.toggle_favorite(GENERIC_ID))
        self.assertIsNone(campaign_db.toggle_favorite("h:1"))


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
        campaign_db.append_dialogue(GENERIC_ID, ["[Day 2, 09:59] early", "[Day 2, 10:01] late", "untimed"], BEEP)
        campaign_db.add_event("[Day 2, 10:00] same minute")
        campaign_db.add_event("[Day 3] next day")
        campaign_db.add_rumor("- [Day 1, 00:00] [RUMOR: old]")
        campaign_db.add_rumor("- [Day 5, 00:00] [RUMOR: new]")

        self.assertEqual(campaign_db.cull_after(2, 10, 0), {"dialogue": 1, "event": 1, "rumor": 1})
        self.assertEqual(campaign_db.get_character(GENERIC_ID)["ConversationHistory"], ["[Day 2, 09:59] early", "untimed"])
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
        self.assertEqual((faction["name"], faction["description"], faction["origin"]), ("Holy Nation Outlaws", "", "game"))

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

    def test_add_and_delete(self):
        campaign_db.add_faction("42022-rebirth.mod", {"name": "Outlaws", "aliases": [], "major": False, "fields": {}, "description": "Exiles."})
        self.assertEqual(campaign_db.find_faction("42022-rebirth.mod")["origin"], "campaign")
        with self.assertRaises(campaign_db.DuplicateRecord):
            campaign_db.add_faction("42022-rebirth.mod", {"name": "Again", "aliases": [], "major": False, "fields": {}, "description": ""})
        self.assertTrue(campaign_db.delete_faction("42022-rebirth.mod"))
        self.assertIsNone(campaign_db.find_faction("42022-rebirth.mod"))

    def test_overview_and_history_edit(self):
        campaign_db.set_overview("A new world.")
        campaign_db.set_history([])
        self.assertEqual((campaign_db.overview(), campaign_db.history()), ("A new world.", []))


class RecordTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)

    def test_add_replace_and_delete(self):
        campaign_db.save_record("entity", ("zones", "stenn"), {"name": "Stenn Desert"}, None)
        (key, value, origin, updated_at), = [record for record in campaign_db.list_records("entity") if record[0] == ("zones", "stenn")]
        self.assertEqual(origin, "campaign")
        campaign_db.save_record("entity", key, {"name": "The Stenn"}, updated_at)
        self.assertIn((("zones", "stenn"), {"name": "The Stenn"}), [record[:2] for record in campaign_db.list_records("entity")])
        self.assertTrue(campaign_db.delete_record("entity", key))
        self.assertFalse(campaign_db.delete_record("entity", key))

    def test_a_taken_key_and_a_stale_save_are_refused(self):
        (key, _, _, updated_at), = campaign_db.list_records("character")
        with self.assertRaises(campaign_db.DuplicateRecord):
            campaign_db.save_record("character", key, {"Name": "Copy"}, None)
        with mock.patch.object(campaign_db, "_now", return_value="2099-01-01T00:00:00.000+00:00"):
            campaign_db.save_record("character", key, {"Name": "Beep"}, updated_at)
        with self.assertRaises(campaign_db.StaleRecord):
            campaign_db.save_record("character", key, {"Name": "Old"}, updated_at)
        campaign_db.delete_record("character", key)
        with self.assertRaises(campaign_db.StaleRecord):
            campaign_db.save_record("character", key, {"Name": "Gone"}, "2099-01-01T00:00:00.000+00:00")


if __name__ == "__main__":
    unittest.main()
