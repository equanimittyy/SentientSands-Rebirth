import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import background
from store import campaign_db

STICK, JORGE, ABEL, IZUMI = "h:10", "h:14", "h:15", "h:11"
NAMELESS, HOLY_NATION, DUST_BANDITS, SHEK_KINGDOM = "204-gamedata.base", "1083-gamedata.base", "17-gamedata.base", "2-gamedata.base"

SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "A world of sand.",
    "factions": [
        {"faction_id": NAMELESS, "name": "Nameless", "aliases": [], "major": False, "fields": {}, "description": "Wanderers without a name."},
        {"faction_id": HOLY_NATION, "name": "The Holy Nation", "aliases": [], "major": True, "fields": {"leader": "Phoenix"}, "description": "Zealots of Okran."},
        {"faction_id": DUST_BANDITS, "name": "Dust Bandits", "aliases": [], "major": False, "fields": {}, "description": "Starving raiders of the desert."},
        {"faction_id": SHEK_KINGDOM, "name": "Shek Kingdom", "aliases": [], "major": True, "fields": {}, "description": "The horned warriors of the Stenn Desert."},
    ],
    "history": [{"title": "Kral and the Shek Wars", "text": "Kral led the Shek in a war against the Holy Nation."}],
    "characters": [],
    "entities": [
        {"category": "races", "id": "shek", "data": {"name": "Shek", "fields": {}, "description": "A horned race."}},
        {"category": "races", "id": "greenlander", "data": {"name": "Greenlander", "fields": {}, "description": "A dark-skinned human race."}},
    ],
}

GUARD = ("{h:10} asked {h:14} for work. {h:14} doubted that {h:10} could fight, but offered 200 cats to guard the door of the bar for the night"
         " and stop anyone who started trouble. {h:10} agreed. {h:14} named the Dust Bandits as the usual trouble, because they drink and leave without paying.")


@mock.patch.object(background, "load_settings", lambda: {"retrieval_slots": 3, "memory_slots": 3})
class SearchTest(unittest.TestCase):
    ABEL_PROFILE = {"Name": "Paladin Abel", "Faction": "The Holy Nation", "OriginFaction": "The Holy Nation"}
    JORGE_PROFILE = {"Name": "Jorge", "Faction": "Nameless"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)
        campaign_db.note_faction(NAMELESS, "Nameless", is_player=True)
        for npc_id, name in ((STICK, "Stick"), (JORGE, "Jorge"), (ABEL, "Paladin Abel"), (IZUMI, "Izumi")):
            campaign_db.upsert_profile(npc_id, {"Name": name})
        self.guard = self.remember([(STICK, "speaker", True), (JORGE, "speaker", False), (ABEL, "overheard", False)], GUARD, "[Day 3, 14:05]")

    def tearDown(self):
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def remember(self, members, text, when):
        thread_id = campaign_db.join_thread(None, members, campaign_db.game_time(when))
        for npc_id, _, _ in members:
            campaign_db.append_dialogue(npc_id, [(f"{when} line", npc_id)], {}, thread_id)
        campaign_db.set_memory(thread_id, text, campaign_db.game_time(when))
        return thread_id

    def search(self, message, npc_id=ABEL, profile=None, speaker_race="Greenlander"):
        profile = profile or (self.ABEL_PROFILE if npc_id == ABEL else self.JORGE_PROFILE)
        memories, _, entries, _ = background.search(message, background.campaign_lore(), npc_id, profile, None, speaker_race)
        return [hit["record"]["memory"]["id"] for hit in memories], [hit["record"]["name"] for hit in entries]

    def rumors(self, message, npc_id=ABEL):
        return [hit["record"]["text"] for hit in background.search(message, background.campaign_lore(), npc_id, self.ABEL_PROFILE, None, "Greenlander")[1]]

    def add_newest_rumors(self):
        for text in ("A caravan never arrived.", "The well of Stack ran dry.", "Hounds howl near the Hub."):
            campaign_db.add_custom_event(text)

    def test_an_overhearer_finds_the_memory_by_two_shared_words(self):
        self.assertEqual(self.search("Who keeps the trouble out of here at night?"), ([self.guard], []))

    def test_a_lore_name_finds_the_memory_and_its_entry(self):
        self.assertEqual(self.search("Are the Dust Bandits around?"), ([self.guard], ["Dust Bandits"]))

    def test_a_member_name_finds_the_memory(self):
        self.assertEqual(self.search("Have you seen Stick?"), ([self.guard], []))

    def test_one_shared_word_finds_no_memory(self):
        self.assertEqual(self.search("Do you need a guard?")[0], [])

    def test_a_chat_line_finds_nothing(self):
        self.assertEqual(self.search("How are you doing today?"), ([], []))

    def test_the_memory_that_the_system_message_holds_is_not_found(self):
        self.assertEqual(self.search("Did Stick ever find work?", npc_id=JORGE), ([], []))

    def test_a_renamed_member_is_found_by_the_new_name(self):
        campaign_db.upsert_profile(STICK, {"Name": "Stickman"})
        self.assertEqual(self.search("Have you seen Stickman?"), ([self.guard], []))
        self.assertEqual(self.search("Have you seen Stick?"), ([], []))

    def test_an_npc_that_spoke_in_many_threads_finds_the_older_ones(self):
        older = self.remember([(IZUMI, "speaker", True), (JORGE, "speaker", False)], "{h:11} sold {h:14} a crate of rum.", "[Day 1, 08:00]")
        for day in range(4, 9):
            self.remember([(STICK, "speaker", True), (JORGE, "speaker", False)], f"{{h:10}} paid {{h:14}} on day {day}.", f"[Day {day}, 08:00]")
        self.assertEqual(self.search("Have you seen Izumi?", npc_id=JORGE)[0], [older])

    def test_the_lore_of_the_system_message_is_skipped(self):
        self.assertEqual(self.search("The Holy Nation, the Nameless, and the Greenlander walk into a bar.")[1], [])
        self.assertEqual(self.search("The Holy Nation, the Nameless, and the Shek walk into a bar.")[1], ["Shek"])
        self.assertEqual(self.search("The Holy Nation, the Nameless, and the Shek walk into a bar.", profile=dict(self.ABEL_PROFILE, Race="Shek"))[1], [])

    def test_a_lore_search_alone_skips_nothing(self):
        memories, rumors, entries, skipped = background.search("I hate the Holy Nation.", background.campaign_lore())
        self.assertEqual((memories, rumors, [hit["record"]["name"] for hit in entries]), ([], [], ["The Holy Nation"]))
        self.assertIn(("hate", "not lore"), skipped)

    def test_a_character_of_its_event_finds_an_older_rumor(self):
        campaign_db.add_event("kill", [(STICK, "Stick")], {"npc_id": "u:grig", "name": "Grig", "faction": "Dust Bandits"}, campaign_db.game_time("[Day 2, 10:00]"))
        campaign_db.save_rumor(None, campaign_db.events()[0][0], "A wanderer cut down the bandit Grig.")
        self.assertEqual(self.rumors("Is Grig really dead?"), [])
        self.add_newest_rumors()
        self.assertEqual(self.rumors("Is Grig really dead?"), ["A wanderer cut down the bandit Grig."])
        self.assertEqual(self.rumors("Did you hear what Stick did?"), ["A wanderer cut down the bandit Grig."])

    def test_two_shared_words_find_an_older_rumor(self):
        campaign_db.add_custom_event("Slavers burned a farm east of Stack.")
        self.add_newest_rumors()
        self.assertEqual(self.rumors("Who burned that farm?"), ["Slavers burned a farm east of Stack."])
        self.assertEqual(self.rumors("Any farm work?"), [])

    def test_the_npc_does_not_find_a_rumor_by_its_own_name(self):
        campaign_db.add_event("capture", [(STICK, "Stick")], {"npc_id": ABEL, "name": "Paladin Abel", "faction": "The Holy Nation"}, campaign_db.game_time("[Day 2, 10:00]"))
        campaign_db.save_rumor(None, campaign_db.events()[0][0], "Wanderers took a paladin in chains.")
        self.add_newest_rumors()
        self.assertEqual(self.rumors("Paladin Abel, how are you?"), [])
        self.assertEqual(self.rumors("Paladin Abel, how are you?", npc_id=JORGE), ["Wanderers took a paladin in chains."])


KNOWLEDGE_SEED = dict(
    SEED,
    factions=[dict(faction, fields={"territory": ["Vain"]}) if faction["faction_id"] == SHEK_KINGDOM else faction for faction in SEED["factions"]],
    history=[{"title": "Kenshi is a Moon", "text": "The world is a moon.", "knowledge": "secret", "known_by": ["Paladin Abel"]}],
    characters=[{"game_id": "abel", "profile": {"Name": "Paladin Abel", "Faction": "The Holy Nation", "Backstory": "A paladin of Okran."}}],
    entities=SEED["entities"] + [
        {"category": "regions", "id": "bonedog_plains", "data": {"name": "Bonedog Plains", "aliases": ["Bonedog Den"], "fields": {"animals": ["Bonedogs"]}, "description": "Bonedogs.", "knowledge": "limited"}},
        {"category": "regions", "id": "vain", "data": {"name": "Vain", "fields": {"animals": ["Bonedogs", "Goats", "Beak Things", "Garru", "Leviathans", "Spiders", "Gorillos", "Crabs", "Landbats", "Raptors"]}, "description": "Cliffs.", "knowledge": "global"}},
        {"category": "regions", "id": "barren", "data": {"name": "The Barren"}},
        {"category": "locations", "id": "fang_hollow", "data": {"name": "Fang Hollow", "fields": {"zone": ["Vain"]}, "description": "A cave.", "knowledge": "limited"}},
    ] + [{"category": "locations", "id": f"waystation_{i}", "data": {"name": f"Waystation {i}", "description": "A stop.", "knowledge": "global"}} for i in range(20)],
)


@mock.patch.object(background, "load_settings", lambda: {"retrieval_slots": 3, "memory_slots": 3})
class KnowledgeTest(unittest.TestCase):
    ABEL, HOLY = "u:abel", {"Name": "Paladin Abel", "Faction": "The Holy Nation"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: KNOWLEDGE_SEED)

    def tearDown(self):
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def search(self, message, npc_id=None, profile=None):
        return [hit["record"]["name"] for hit in background.search(message, background.campaign_lore(), npc_id, profile or self.HOLY)[2]]

    def travels(self, message, npc_id, profile=None):
        return [(hit["record"]["name"], hit["travels"]) for hit in background.search(message, background.campaign_lore(), npc_id, profile or self.HOLY)[2]]

    def test_a_record_that_the_npc_cannot_know_cuts_no_hit_that_it_can_know(self):
        self.assertEqual(self.search("Any bonedogs?"), ["Bonedog Plains"])
        self.assertEqual(self.search("Any bonedogs?", "h:1"), ["Vain"])

    def test_the_npc_finds_a_limited_character_of_its_faction_but_not_its_own_record(self):
        self.assertEqual(self.search("Who is Paladin Abel?", "h:1"), ["Paladin Abel"])
        self.assertEqual(self.search("Who is Paladin Abel?", self.ABEL), [])

    def test_a_secret_reaches_the_character_in_its_known_by_but_not_a_generic_npc_with_its_name(self):
        self.assertEqual(self.search("Is Kenshi a Moon?", self.ABEL), ["Kenshi is a Moon"])
        self.assertEqual(self.search("Is Kenshi a Moon?", "h:1"), [])

    def test_a_lore_search_alone_searches_every_record(self):
        self.assertEqual(self.search("Is Kenshi a Moon?"), ["Kenshi is a Moon"])

    def test_a_character_that_the_server_added_in_play_is_no_record(self):
        campaign_db.upsert_profile("h:10", {"Name": "Stick", "Backstory": "A drifter."})
        self.assertEqual([record["key"] for record in background.campaign_lore() if record["kind"] == "character"], [("characters", self.ABEL)])

    def test_a_record_without_text_is_no_hit(self):
        self.assertEqual(self.search("Where is the Barren?"), [])

    def test_the_lands_of_the_origin_faction_are_base_knowledge(self):
        self.assertEqual(self.travels("Where is Fang Hollow?", "h:2", {"Name": "Kang", "Faction": "Nameless", "OriginFaction": "Shek Kingdom"}), [("Fang Hollow", False)])
        self.assertEqual(self.travels("Where is Fang Hollow?", "h:1"), [])

    def test_the_place_of_a_past_chat_is_travel_knowledge(self):
        campaign_db.join_thread(None, [("h:1", "overheard", False)], None, "Wilderness, Vain")
        self.assertEqual(self.travels("Where is Fang Hollow?", "h:1"), [("Fang Hollow", True)])

    def test_the_travels_are_the_places_of_past_chats_away_from_home_newest_first(self):
        for location in ("Bar, Fang Hollow", "Wilderness, Vain", "Shack, The Barren", "Wilderness, The Barren", ""):
            campaign_db.join_thread(None, [("h:1", "overheard", False), ("h:2", "overheard", False)], None, location)
        profiles = {"h:1": {"Name": "Stick"}, "h:2": {"Name": "Kang", "OriginFaction": "Shek Kingdom"}}
        self.assertEqual(background.travels(background.campaign_lore(), profiles), {"h:1": ["The Barren", "Vain", "Fang Hollow"], "h:2": ["The Barren"]})


class PlaceTest(unittest.TestCase):
    LORE = [{"kind": "location", "name": name, "aliases": []} for name in ("The Hub", "Bast")] + [{"kind": "region", "name": "Vain", "aliases": []}]

    def test_a_town_of_the_lore_is_the_town(self):
        self.assertEqual(background.place_of("Bar, The Hub", self.LORE), ("The Hub", None))
        self.assertEqual(background.place_of("The Hub", self.LORE), ("The Hub", None))

    def test_any_other_place_is_the_zone(self):
        self.assertEqual(background.place_of("Shack, Vain", self.LORE), (None, "Vain"))
        self.assertEqual(background.place_of("Wilderness, Bast", self.LORE), (None, "Bast"))

    def test_no_location_gives_no_place(self):
        self.assertEqual(background.place_of("", self.LORE), (None, None))


if __name__ == "__main__":
    unittest.main()
