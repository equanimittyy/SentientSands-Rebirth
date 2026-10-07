import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from store import campaign_db

BEEP_ID = "u:19576-Dialogue.mod"
GENERIC_ID = "h:2717040896"

def spoken(speaker, *lines):
    return [(line, speaker) for line in lines]


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

    def test_unavailable_reason(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        self.assertIsNone(campaign_db.unavailable_reason())
        os.remove(os.path.join(self.folder, campaign_db.DB_NAME))
        self.assertRegex(campaign_db.unavailable_reason(), "has no campaign.db file")
        campaign_db.close_campaign()
        self.assertRegex(campaign_db.unavailable_reason(), "No campaign is selected")

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

    def test_a_rename_relabels_only_the_lines_of_the_character(self):
        lines = [
            *spoken("h:1", "[Day 1, 08:00] Drifter: Hello Zabuza"),
            *spoken(GENERIC_ID, "[Day 1, 08:00] Zabuza: Zabuza: a fine name.", "Zabuza: No time."),
            *spoken("h:7", "[Day 2] Zabuza: I am another Zabuza."),
        ]
        campaign_db.append_dialogue(GENERIC_ID, lines, {"Name": "Zabuza"})
        campaign_db.rename_character(GENERIC_ID, "Zabuza", "Poopyhead")
        self.assertEqual(campaign_db.get_character(GENERIC_ID), {
            "Name": "Poopyhead",
            "ConversationHistory": ["[Day 1, 08:00] Drifter: Hello Zabuza", "[Day 1, 08:00] Poopyhead: Zabuza: a fine name.", "Poopyhead: No time.", "[Day 2] Zabuza: I am another Zabuza."],
        })

    def test_the_dialogue_keeps_the_speaker_of_each_line(self):
        campaign_db.append_dialogue(GENERIC_ID, [("Drifter: hi", None), ("Zabuza: Hm.", GENERIC_ID)], {"Name": "Zabuza"})
        self.assertEqual(campaign_db.dialogue(GENERIC_ID), [("Drifter: hi", None, None), ("Zabuza: Hm.", GENERIC_ID, None)])
        self.assertEqual(campaign_db.dialogue("h:1"), [])

    def test_the_names_hold_the_name_of_each_character(self):
        campaign_db.upsert_profile(GENERIC_ID, {"Name": "Dust Bandit"})
        campaign_db.rename_character(GENERIC_ID, "Dust Bandit", "Josh")
        self.assertEqual(campaign_db.character_names(), {"Beep", "Josh"})

    def test_a_value_of_none_removes_the_key(self):
        campaign_db.upsert_profile(GENERIC_ID, {"Name": "Zabuza", "CurrentJob": "Guarding a building"})
        campaign_db.upsert_profile(GENERIC_ID, {"CurrentJob": None})
        self.assertNotIn("CurrentJob", campaign_db.get_character(GENERIC_ID))

    def test_concurrent_appends_keep_the_lines_of_both(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        threads = [threading.Thread(target=campaign_db.append_dialogue, args=(GENERIC_ID, spoken(None, f"line {i}"), BEEP)) for i in range(8)]
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

    def test_only_a_provisional_profile_counts_interactions(self):
        campaign_db.upsert_profile(GENERIC_ID, {"Name": "Dust Bandit", campaign_db.PROVISIONAL: 0})
        self.assertEqual([campaign_db.count_interaction(GENERIC_ID) for _ in range(2)], [1, 2])
        self.assertIsNone(campaign_db.count_interaction(BEEP_ID))
        self.assertIsNone(campaign_db.count_interaction("h:1"))

    def test_a_bio_ends_the_provisional_profile_and_never_overwrites_a_full_one(self):
        campaign_db.upsert_profile(GENERIC_ID, {"Name": "Dust Bandit", "Personality": "Rolled.", campaign_db.PROVISIONAL: 4})
        self.assertTrue(campaign_db.promote_profile(GENERIC_ID, {"Personality": "Written."}))
        self.assertEqual(campaign_db.get_character(GENERIC_ID), {"Name": "Dust Bandit", "Personality": "Written.", "ConversationHistory": []})
        self.assertFalse(campaign_db.promote_profile(GENERIC_ID, {"Personality": "Again."}))
        self.assertEqual(campaign_db.get_character(GENERIC_ID)["Personality"], "Written.")
        self.assertFalse(campaign_db.promote_profile("h:1", {"Personality": "Written."}))

    def test_append_stores_the_profile_only_when_missing(self):
        campaign_db.append_dialogue(GENERIC_ID, spoken(None, "a"), {"Name": "Beep"})
        campaign_db.append_dialogue(GENERIC_ID, spoken(None, "b"), {"Name": "Other"})
        self.assertEqual(campaign_db.get_character(GENERIC_ID), {"Name": "Beep", "ConversationHistory": ["a", "b"]})

    def test_a_template_character_keeps_its_canon_profile_in_chat(self):
        campaign_db.append_dialogue(BEEP_ID, spoken(None, "hello"), {"Name": "Beep", "Personality": "Generated."})
        self.assertEqual(campaign_db.get_character(BEEP_ID), {"Name": "Beep", "Race": "Hive Worker Drone", "ConversationHistory": ["hello"]})
        self.assertEqual([(c["origin"], c["has_dialogue"]) for c in campaign_db.list_characters()], [("seed", True)])

    def test_only_a_character_whose_every_line_is_overheard_counts_as_only_overheard(self):
        campaign_db.append_dialogue(GENERIC_ID, spoken(None, "[Day 1, 08:00] (Overheard) Drifter: Hello", "(Overheard) Beep: Hi"), BEEP)
        campaign_db.append_dialogue("h:1", spoken(None, "[Day 1, 08:00] (Overheard) Drifter: Hello", "[Day 1, 08:01] Beep: Hi"), BEEP)
        only_overheard = {c["npc_id"]: c["only_overheard"] for c in campaign_db.list_characters()}
        self.assertEqual(only_overheard, {BEEP_ID: False, GENERIC_ID: True, "h:1": False})

    def test_a_character_met_in_play_has_the_game_origin(self):
        campaign_db.upsert_profile(GENERIC_ID, BEEP)
        self.assertEqual({c["npc_id"]: c["origin"] for c in campaign_db.list_characters()}[GENERIC_ID], "game")

    def test_no_line_is_trimmed(self):
        campaign_db.append_dialogue(GENERIC_ID, spoken(None, *(f"line {i}" for i in range(300))), BEEP)
        self.assertEqual(len(campaign_db.get_character(GENERIC_ID)["ConversationHistory"]), 300)

    def test_two_npcs_with_one_name_keep_separate_rows(self):
        campaign_db.append_dialogue("h:1", spoken(None, "to the first"), {"Name": "Bob"})
        campaign_db.append_dialogue("h:2", spoken(None, "to the second"), {"Name": "Bob"})
        self.assertEqual(campaign_db.get_character("h:1")["ConversationHistory"], ["to the first"])
        self.assertEqual(campaign_db.get_character("h:2")["ConversationHistory"], ["to the second"])

    def test_an_npc_id_is_exact(self):
        campaign_db.upsert_profile("u:5-Mod Name.mod", {"Name": "Ace"})
        self.assertTrue(campaign_db.character_exists("u:5-Mod Name.mod"))
        self.assertFalse(campaign_db.character_exists("U:5-mod name.mod"))

    def test_a_rename_keeps_the_dialogue_and_the_favorite(self):
        campaign_db.append_dialogue(GENERIC_ID, spoken(None, "hello"), BEEP)
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


class ThreadTest(CampaignTestCase):
    STICK, IZUMI, RUKA = "h:10", "h:11", "h:12"

    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)
        for npc_id, name in ((self.STICK, "Stick"), (self.IZUMI, "Izumi"), (self.RUKA, "Ruka"), (GENERIC_ID, "Jorge")):
            campaign_db.upsert_profile(npc_id, {"Name": name})

    def exchange(self, thread_id, when, listeners=(), speaker=None, location=None):
        """A chat of Stick, or of speaker, with Jorge, stored as the chat route stores it."""
        speaker = speaker or self.STICK
        members = [(speaker, "speaker", True), (GENERIC_ID, "speaker", False), *((npc_id, "overheard", True) for npc_id in listeners)]
        thread_id = campaign_db.join_thread(thread_id, members, campaign_db.game_time(when), location)
        lines = [(f"{when} Stick: hi", speaker), (f"{when} Jorge: Hm.", GENERIC_ID)]
        for npc_id in (speaker, GENERIC_ID):
            campaign_db.append_dialogue(npc_id, lines, {}, thread_id)
        for npc_id in listeners:
            campaign_db.append_dialogue(npc_id, [(f"{when} (Overheard) {line.split('] ', 1)[1]}", who) for line, who in lines], {}, thread_id)
        return thread_id

    def test_each_copy_stores_the_thread_and_the_members_keep_their_first_join(self):
        thread_id = self.exchange(None, "[Day 3, 14:05]", listeners=[self.IZUMI])
        self.assertEqual(self.exchange(thread_id, "[Day 3, 14:06]", listeners=[self.IZUMI, self.RUKA]), thread_id)
        self.assertEqual({row[2] for row in campaign_db.dialogue(self.IZUMI)}, {thread_id})
        self.assertEqual(campaign_db.thread_members([thread_id]), {thread_id: [
            (self.STICK, "Stick", "speaker", True), (GENERIC_ID, "Jorge", "speaker", False), (self.IZUMI, "Izumi", "overheard", True), (self.RUKA, "Ruka", "overheard", True),
        ]})

    def test_a_deleted_thread_is_never_joined_again(self):
        thread_id = self.exchange(None, "[Day 3, 14:05]")
        campaign_db.cull_after(3, 0, 0)
        self.assertNotEqual(self.exchange(thread_id, "[Day 2, 10:00]"), thread_id)

    def test_a_cull_deletes_the_later_members_and_the_threads_with_no_row_left(self):
        early = self.exchange(None, "[Day 3, 14:05]")
        self.exchange(early, "[Day 3, 16:00]", listeners=[self.IZUMI])
        late = self.exchange(None, "[Day 4, 09:00]")
        campaign_db.cull_after(3, 15, 0)
        self.assertEqual(campaign_db.thread_members([early, late]), {early: [(self.STICK, "Stick", "speaker", True), (GENERIC_ID, "Jorge", "speaker", False)]})

    def test_a_deleted_character_takes_the_threads_that_only_it_held(self):
        thread_id = campaign_db.join_thread(None, [(GENERIC_ID, "speaker", False)], None)
        campaign_db.append_dialogue(GENERIC_ID, [("Jorge: Hm.", GENERIC_ID)], {}, thread_id)
        campaign_db.delete_record("character", (GENERIC_ID,))
        self.assertEqual(campaign_db.thread_members([thread_id]), {})

    def test_the_threads_show_the_copy_of_a_speaker_newest_first(self):
        first = self.exchange(None, "[Day 3, 14:05]", listeners=[self.IZUMI])
        self.exchange(first, "[Day 3, 14:06]", listeners=[self.IZUMI])
        second = self.exchange(None, "[Day 4, 09:00]", speaker=self.RUKA)
        threads = campaign_db.threads()
        self.assertEqual([thread["id"] for thread in threads], [second, first])
        self.assertEqual(threads[1]["lines"], ["[Day 3, 14:05] Stick: hi", "[Day 3, 14:05] Jorge: Hm.", "[Day 3, 14:06] Stick: hi", "[Day 3, 14:06] Jorge: Hm."])
        self.assertEqual(campaign_db.game_time_text(threads[1]["game_time"]), "Day 3, 14:05")
        self.assertEqual([member[1:3] for member in threads[1]["members"]], [("Stick", "speaker"), ("Jorge", "speaker"), ("Izumi", "overheard")])

    def test_a_thread_keeps_the_place_where_it_started(self):
        thread_id = self.exchange(None, "[Day 3, 14:05]", location="Bar, The Hub")
        self.exchange(thread_id, "[Day 3, 14:06]", location="The Hub")
        self.exchange(None, "[Day 4, 09:00]")
        self.assertEqual([thread["location"] for thread in campaign_db.threads()], [None, "Bar, The Hub"])

    def test_the_places_of_a_member_count_each_place_once(self):
        self.exchange(None, "[Day 3, 14:05]", listeners=[self.IZUMI], location="Bar, The Hub")
        self.exchange(None, "[Day 4, 09:00]", location="Bar, The Hub")
        self.exchange(None, "[Day 5, 09:00]", location="Wilderness, Vain")
        self.exchange(None, "[Day 6, 09:00]")
        self.assertEqual(sorted(campaign_db.thread_places(self.STICK)), ["Bar, The Hub", "Wilderness, Vain"])
        self.assertEqual(campaign_db.thread_places(self.IZUMI), ["Bar, The Hub"])
        self.assertEqual(campaign_db.thread_places(self.RUKA), [])

    def test_the_places_of_each_character_come_newest_thread_first(self):
        self.exchange(None, "[Day 3, 14:05]", listeners=[self.IZUMI], location="Bar, The Hub")
        self.exchange(None, "[Day 4, 09:00]", location="Wilderness, Vain")
        self.exchange(None, "[Day 5, 09:00]")
        places = campaign_db.character_places()
        self.assertEqual((places[self.STICK], places[self.IZUMI]), (["Wilderness, Vain", "Bar, The Hub"], ["Bar, The Hub"]))
        self.assertNotIn(self.RUKA, places)

    def test_a_thread_without_a_speaker_copy_shows_the_copy_of_an_overhearer(self):
        thread_id = self.exchange(None, "[Day 3, 14:05]", listeners=[self.IZUMI])
        for npc_id in (self.STICK, GENERIC_ID):
            campaign_db.delete_record("character", (npc_id,))
        self.assertEqual(campaign_db.threads()[0]["lines"], ["[Day 3, 14:05] (Overheard) Stick: hi", "[Day 3, 14:05] (Overheard) Jorge: Hm."])
        self.assertEqual([member[:2] for member in campaign_db.thread_members([thread_id])[thread_id]], [(self.STICK, None), (GENERIC_ID, None), (self.IZUMI, "Izumi")])

    def test_names_of(self):
        self.assertEqual(campaign_db.names_of([self.STICK, "h:99"]), {self.STICK: "Stick"})

    def test_the_pending_threads_are_the_threads_without_a_memory_oldest_first(self):
        first = self.exchange(None, "[Day 3, 14:05]", listeners=[self.IZUMI])
        self.exchange(first, "[Day 3, 14:06]", listeners=[self.IZUMI])
        second = self.exchange(None, "[Day 4, 09:00]")
        third = self.exchange(None, "[Day 5, 09:00]")
        self.assertTrue(campaign_db.set_memory(second, "Stick greeted Jorge.", campaign_db.game_time("[Day 4, 09:00]")))
        pending = campaign_db.pending_threads()
        self.assertEqual([(thread["id"], thread["game_time"]) for thread in pending], [(first, campaign_db.game_time("[Day 3, 14:06]")), (third, campaign_db.game_time("[Day 5, 09:00]"))])
        self.assertEqual(pending[0]["lines"], ["[Day 3, 14:05] Stick: hi", "[Day 3, 14:05] Jorge: Hm.", "[Day 3, 14:06] Stick: hi", "[Day 3, 14:06] Jorge: Hm."])

    def test_a_memory_is_stored_once_and_only_for_the_game_time_that_was_read(self):
        thread_id = self.exchange(None, "[Day 3, 14:05]")
        self.assertFalse(campaign_db.set_memory(thread_id, "Stale.", campaign_db.game_time("[Day 3, 14:00]")))
        self.assertTrue(campaign_db.set_memory(thread_id, "Stick greeted Jorge.", campaign_db.game_time("[Day 3, 14:05]")))
        self.assertFalse(campaign_db.set_memory(thread_id, "Again.", campaign_db.game_time("[Day 3, 14:05]")))
        self.assertEqual(campaign_db.threads()[0]["memory"], "Stick greeted Jorge.")

    def test_a_memory_replaces_every_copy_of_the_lines_of_its_thread(self):
        thread_id = self.exchange(None, "[Day 1, 08:00]", listeners=[self.IZUMI])
        other = self.exchange(None, "[Day 2, 08:00]")
        campaign_db.append_dialogue(self.IZUMI, [("[Day 1, 09:00] Izumi: Hot today.", self.IZUMI)], {})
        campaign_db.set_memory(thread_id, "Stick greeted Jorge.", campaign_db.game_time("[Day 1, 08:00]"))
        self.assertEqual([row[0] for row in campaign_db.dialogue(self.IZUMI)], ["[Day 1, 09:00] Izumi: Hot today."])
        self.assertEqual({row[2] for row in campaign_db.dialogue(GENERIC_ID)}, {other})
        thread = next(thread for thread in campaign_db.threads() if thread["id"] == thread_id)
        self.assertEqual((thread["memory"], thread["lines"]), ("Stick greeted Jorge.", []))
        self.assertEqual(campaign_db.game_time_text(thread["game_time"]), "Day 1, 08:00")
        self.assertEqual([member[1] for member in thread["members"]], ["Stick", "Jorge", "Izumi"])
        self.assertEqual([pending["id"] for pending in campaign_db.pending_threads()], [other])

    def test_a_cull_deletes_the_threads_whose_memory_is_after_the_cut_and_the_later_lines_of_a_pending_thread(self):
        kept = self.exchange(None, "[Day 2, 10:00]")
        remembered = self.exchange(None, "[Day 3, 14:00]")
        self.exchange(remembered, "[Day 3, 16:00]")
        pending = self.exchange(None, "[Day 3, 14:05]")
        self.exchange(pending, "[Day 3, 16:05]")
        for thread_id, when in ((kept, "[Day 2, 10:00]"), (remembered, "[Day 3, 16:00]")):
            campaign_db.set_memory(thread_id, f"Memory of {thread_id}.", campaign_db.game_time(when))
        campaign_db.cull_after(3, 15, 0)
        self.assertEqual({thread["id"]: thread["memory"] for thread in campaign_db.threads()}, {kept: f"Memory of {kept}.", pending: None})
        self.assertEqual(campaign_db.thread_members([remembered]), {})
        [left] = campaign_db.pending_threads()
        self.assertEqual((left["id"], left["game_time"], left["lines"]), (pending, campaign_db.game_time("[Day 3, 14:05]"), ["[Day 3, 14:05] Stick: hi", "[Day 3, 14:05] Jorge: Hm."]))

    def test_only_a_memory_can_be_edited_or_deleted(self):
        remembered = self.exchange(None, "[Day 1, 08:00]", listeners=[self.IZUMI])
        pending = self.exchange(None, "[Day 2, 08:00]")
        campaign_db.set_memory(remembered, "Stick greeted Jorge.", campaign_db.game_time("[Day 1, 08:00]"))
        self.assertTrue(campaign_db.edit_memory(remembered, "Stick paid Jorge."))
        self.assertFalse(campaign_db.edit_memory(pending, "No."))
        self.assertFalse(campaign_db.delete_memory(pending))
        self.assertEqual({thread["id"]: thread["memory"] for thread in campaign_db.threads()}, {remembered: "Stick paid Jorge.", pending: None})
        self.assertTrue(campaign_db.delete_memory(remembered))
        self.assertEqual([thread["id"] for thread in campaign_db.threads()], [pending])
        self.assertEqual((campaign_db.thread_members([remembered]), campaign_db.thread_partners(self.STICK)), ({}, [GENERIC_ID]))

    def test_the_memories_of_a_member_are_the_newest_oldest_first(self):
        threads = [self.exchange(None, f"[Day {day}, 08:00]", listeners=[self.IZUMI] if day == 2 else []) for day in (1, 2, 3, 4)]
        for day, thread_id in enumerate(threads[:3], start=1):
            campaign_db.set_memory(thread_id, f"Day {day}.", campaign_db.game_time(f"[Day {day}, 08:00]"))
        self.assertEqual([memory["memory"] for memory in campaign_db.memories_of(GENERIC_ID)], ["Day 1.", "Day 2.", "Day 3."])
        self.assertEqual([memory["memory"] for memory in campaign_db.memories_of(GENERIC_ID, 2)], ["Day 2.", "Day 3."])
        [heard] = campaign_db.memories_of(self.IZUMI)
        self.assertEqual((campaign_db.game_time_text(heard["game_time"]), [member[2] for member in heard["members"]]), ("Day 2, 08:00", ["speaker", "speaker", "overheard"]))

    def test_a_shared_memory_has_at_least_two_of_the_characters_as_members(self):
        threads = [self.exchange(None, "[Day 1, 08:00]", listeners=[self.IZUMI]), self.exchange(None, "[Day 2, 08:00]"), self.exchange(None, "[Day 3, 08:00]", speaker=self.RUKA)]
        for day, thread_id in enumerate(threads, start=1):
            campaign_db.set_memory(thread_id, f"Day {day}.", campaign_db.game_time(f"[Day {day}, 08:00]"))
        self.exchange(None, "[Day 4, 08:00]", listeners=[self.IZUMI])
        self.assertEqual([memory["memory"] for memory in campaign_db.shared_memories([self.STICK, self.IZUMI, self.RUKA])], ["Day 1."])
        self.assertEqual([memory["memory"] for memory in campaign_db.shared_memories([self.STICK, GENERIC_ID])], ["Day 1.", "Day 2."])

    def test_the_partners_of_a_speaker_stay_after_the_memory(self):
        first = self.exchange(None, "[Day 1, 08:00]", listeners=[self.IZUMI])
        self.exchange(None, "[Day 2, 08:00]", speaker=self.RUKA)
        campaign_db.set_memory(first, "Stick greeted Jorge.", campaign_db.game_time("[Day 1, 08:00]"))
        self.assertEqual(campaign_db.thread_partners(GENERIC_ID), [self.STICK, self.RUKA])
        self.assertEqual(campaign_db.thread_partners(self.IZUMI), [])

    def test_the_library_counts_the_members_of_a_thread_with_a_memory(self):
        thread_id = self.exchange(None, "[Day 1, 08:00]", listeners=[self.IZUMI])
        campaign_db.set_memory(thread_id, "Stick greeted Jorge.", campaign_db.game_time("[Day 1, 08:00]"))
        listed = {c["npc_id"]: (c["has_dialogue"], c["only_overheard"]) for c in campaign_db.list_characters() if c["origin"] == "game"}
        self.assertEqual(listed, {self.STICK: (True, False), GENERIC_ID: (True, False), self.IZUMI: (True, True), self.RUKA: (False, False)})


TINFIST = {"npc_id": "u:tinfist", "name": "Tinfist", "faction": "Anti-Slavers"}


class CullAndRumorTest(CampaignTestCase):
    def setUp(self):
        super().setUp()
        campaign_db.open_campaign(self.folder, lambda: SEED)

    def figure(self, at):
        campaign_db.add_deed("kill", [(BEEP_ID, "Beep")], TINFIST, at)
        return next(notable_id for notable_id, time, _ in campaign_db.notables() if time == at)

    def test_cull_deletes_only_later_rows(self):
        campaign_db.append_dialogue(GENERIC_ID, spoken(None, "[Day 2, 09:59] early", "[Day 2, 10:01] late", "untimed"), BEEP)
        kept, culled = self.figure(2 * 1440 + 600), self.figure(3 * 1440)
        campaign_db.save_rumor(None, kept, "old")
        campaign_db.save_rumor(None, culled, "new")

        self.assertEqual(campaign_db.cull_after(2, 10, 0), {"dialogue": 1, "rumor": 1, "notable": 1})
        self.assertEqual(campaign_db.get_character(GENERIC_ID)["ConversationHistory"], ["[Day 2, 09:59] early", "untimed"])
        self.assertEqual([at for _, at, _ in campaign_db.notables()], [2 * 1440 + 600])
        self.assertEqual([rumor["text"] for rumor in campaign_db.rumors()], ["old"])

    def test_a_notable_event_has_one_rumor_with_its_game_time(self):
        notable_id = self.figure(1440)
        self.assertTrue(campaign_db.save_rumor(None, notable_id, "one", "Tell it grimly."))
        self.assertTrue(campaign_db.save_rumor(None, notable_id, "two"))
        (rumor,) = campaign_db.rumors()
        self.assertEqual((rumor["notable_id"], rumor["game_time"], rumor["text"], rumor["instruction"]), (notable_id, 1440, "two", "Tell it grimly."))
        self.assertFalse(campaign_db.save_rumor(None, notable_id + 1, "none"))
        self.assertFalse(campaign_db.save_rumor(rumor["id"] + 1, None, "none"))

    def test_an_added_rumor_never_replaces_a_rumor(self):
        notable_id = self.figure(1440)
        self.assertTrue(campaign_db.add_rumor(notable_id, "auto"))
        self.assertFalse(campaign_db.add_rumor(notable_id, "again"))
        self.assertFalse(campaign_db.add_rumor(notable_id + 1, "gone"))
        self.assertEqual([(rumor["notable_id"], rumor["game_time"], rumor["text"], rumor["instruction"]) for rumor in campaign_db.rumors()], [(notable_id, 1440, "auto", "")])

    def test_a_custom_deed_holds_the_rumor_of_the_player_and_only_a_custom_deed_can_be_deleted(self):
        kill = self.figure(1440)
        custom = campaign_db.add_custom_deed("They say Beep freed the slaves of Rebirth.")
        self.assertEqual(campaign_db.notable(custom), (None, {"deed": "custom"}))
        self.assertEqual([(rumor["notable_id"], rumor["game_time"], rumor["text"]) for rumor in campaign_db.rumors()], [(custom, None, "They say Beep freed the slaves of Rebirth.")])
        self.assertFalse(campaign_db.delete_custom_deed(kill))
        self.assertTrue(campaign_db.delete_custom_deed(custom))
        self.assertEqual([notable_id for notable_id, _, _ in campaign_db.notables()], [kill])
        self.assertEqual(campaign_db.rumors(), [])

    def test_a_custom_deed_and_its_rumor_count_as_the_newest_and_the_cull_keeps_them(self):
        custom = campaign_db.add_custom_deed("They say Beep freed the slaves.")
        later = self.figure(3 * 1440)
        earlier = self.figure(1440)
        for notable_id in (later, earlier):
            campaign_db.save_rumor(None, notable_id, str(notable_id))
        self.assertEqual([notable_id for notable_id, _, _ in campaign_db.notables()], [custom, later, earlier])
        self.assertEqual([rumor["notable_id"] for rumor in campaign_db.rumors()], [earlier, later, custom])
        self.assertEqual(campaign_db.cull_after(2, 0, 0), {"dialogue": 0, "rumor": 1, "notable": 1})
        self.assertEqual([notable_id for notable_id, _, _ in campaign_db.notables()], [custom, earlier])
        self.assertEqual([rumor["game_time"] for rumor in campaign_db.rumors()], [1440, None])

    def test_delete_rumor(self):
        campaign_db.save_rumor(None, self.figure(1440), "one")
        (rumor,) = campaign_db.rumors()
        self.assertTrue(campaign_db.delete_rumor(rumor["id"]))
        self.assertFalse(campaign_db.delete_rumor(rumor["id"]))
        self.assertEqual(campaign_db.rumors(), [])


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

    def test_the_knowledge_of_a_faction_keeps_its_values(self):
        self.assertEqual({key: campaign_db.find_faction("204-gamedata.base")[key] for key in ("knowledge", "known_by")}, {"knowledge": "", "known_by": []})
        faction = campaign_db.find_faction("1083-gamedata.base")
        campaign_db.update_faction("1083-gamedata.base", {"knowledge": "secret", "known_by": ["Nameless"]}, faction["updated_at"])
        self.assertEqual({key: campaign_db.find_faction("1083-gamedata.base")[key] for key in ("knowledge", "known_by")}, {"knowledge": "secret", "known_by": ["Nameless"]})

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

    def test_the_knowledge_of_a_character_keeps_its_values_beside_the_profile(self):
        self.assertEqual(campaign_db.character_knowledge(), {BEEP_ID: {"knowledge": "", "known_by": []}})
        (key, _, _, updated_at), = campaign_db.list_records("character")
        campaign_db.save_record("character", key, {"Name": "Beep"}, updated_at, {"knowledge": "secret", "known_by": ["Hivers"]})
        campaign_db.save_record("character", ("u:new",), {"Name": "New"}, None, {"knowledge": "global", "known_by": []})
        self.assertEqual(campaign_db.character_knowledge(), {BEEP_ID: {"knowledge": "secret", "known_by": ["Hivers"]}, "u:new": {"knowledge": "global", "known_by": []}})
        self.assertEqual(campaign_db.get_character(BEEP_ID), {"Name": "Beep", "ConversationHistory": []})

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


class WriteCountTest(CampaignTestCase):
    def test_only_a_committed_write_counts(self):
        campaign_db.open_campaign(self.folder, lambda: SEED)
        before = campaign_db.writes
        campaign_db.list_records("character")
        self.assertEqual(campaign_db.writes, before)
        campaign_db.note_faction("1-test.mod", "Hub Burners")
        self.assertEqual(campaign_db.writes, before + 1)
        with self.assertRaises(campaign_db.StaleRecord):
            campaign_db.save_record("character", (BEEP_ID,), {"Name": "Old"}, "2000-01-01T00:00:00.000+00:00")
        self.assertEqual(campaign_db.writes, before + 1)


if __name__ == "__main__":
    unittest.main()
