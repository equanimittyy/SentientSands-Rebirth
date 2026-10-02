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


class CampaignTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


class OpenTest(CampaignTestCase):
    def test_a_new_campaign_gets_an_empty_database(self):
        campaign_db.open_campaign(self.folder)
        self.assertEqual(campaign_db.list_npcs(), [])

    def test_a_creation_that_stops_before_the_rename_runs_again(self):
        with mock.patch.object(campaign_db.os, "replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                campaign_db.open_campaign(self.folder)
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME)))

        campaign_db.open_campaign(self.folder)
        self.assertEqual(campaign_db.list_npcs(), [])
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME + ".tmp")))

    def test_a_missing_database_fails_instead_of_being_created(self):
        campaign_db.open_campaign(self.folder)
        os.remove(os.path.join(self.folder, campaign_db.DB_NAME))
        with self.assertRaises(sqlite3.OperationalError):
            campaign_db.get_npc("Beep")
        self.assertFalse(os.path.exists(os.path.join(self.folder, campaign_db.DB_NAME)))


class NpcTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder)

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
        campaign_db.open_campaign(self.folder)

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


if __name__ == "__main__":
    unittest.main()
