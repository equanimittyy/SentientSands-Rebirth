import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import retrieval


def record(kind, name, text, aliases=(), fields=None):
    return {"key": (kind, name), "kind": kind, "name": name, "aliases": list(aliases), "fields": fields or {}, "description": text}


LORE = [
    record("race", "Shek", "A horned race of warriors."),
    record("race", "Skeleton", "Robots of the old world."),
    record("faction", "Shek Kingdom", "The kingdom of the Shek, ruled by Esata the Stone Golem.", fields={"leader": "Esata"}),
    record("faction", "Mercenary Guild", "Sells guards for hire."),
    record("location", "Admag", "The capital of the Shek Kingdom.", fields={"type": "town", "zone": ["Stenn Desert"], "owner": ["Shek Kingdom"]}),
    record("location", "The Hub", "A ruined town of drifters.", fields={"type": "town", "zone": ["Border Zone"]}),
    record("location", "Squin", "Bonedogs roam the gate, and bonedogs sleep on its walls.", fields={"type": "town", "zone": ["Border Zone"]}),
    record("location", "Bast", "A ruined town.", fields={"type": "ruins", "zone": ["Bast"]}),
    record("region", "Bast", "A grassland full of bonedogs.", fields={"animals": ["Bonedogs"]}),
    record("region", "Stenn Desert", "A desert with bonedogs.", fields={"animals": ["Bonedogs"]}),
    record("region", "Border Zone", "A grassland with bonedogs and goats.", fields={"animals": ["Bonedogs", "Goats"]}),
    record("region", "Fog Islands", "A wet coast where mercenaries never go.", fields={"animals": ["Fogmen"]}),
    record("history", "Kral and the Shek Wars", "Kral led the Shek in a war against the Holy Nation."),
    *[record("location", f"Waystation {i}", "A stop where a doctor works.", fields={"type": "outpost"}) for i in range(40)],
]


def names(hits):
    return [(hit["record"]["kind"], hit["record"]["name"]) for hit in hits]


def lore(message, town=None, zone=None):
    return retrieval.find_lore(message, LORE, town, zone)[0]


class LoreRecordsTest(unittest.TestCase):
    def test_each_source_becomes_a_record_with_a_kind_and_a_key(self):
        records = retrieval.lore_records(
            [("races", "shek", {"name": "Shek", "aliases": ["Shek warriors"], "fields": {"type": "humanoid"}, "description": "Horned."})],
            [{"faction_id": "1-gamedata.base", "name": "Shek Kingdom", "aliases": [], "fields": {}, "description": "A kingdom."}],
            [{"title": "The First Empire", "text": "It fell."}],
        )
        self.assertEqual([(r["key"], r["kind"], r["name"], r["description"]) for r in records], [
            (("races", "shek"), "race", "Shek", "Horned."),
            (("factions", "1-gamedata.base"), "faction", "Shek Kingdom", "A kingdom."),
            (("history", 0), "history", "The First Empire", "It fell."),
        ])
        self.assertEqual(records[0]["aliases"], ["Shek warriors"])

    def test_a_record_without_text_stays_for_its_links(self):
        records = retrieval.lore_records([], [{"faction_id": "9-x", "name": "Bugmaster", "aliases": [], "fields": {}, "description": ""}], [{"title": "Empty", "text": " "}])
        self.assertEqual([record["name"] for record in records], ["Bugmaster", "Empty"])

    def test_each_record_keeps_its_knowledge_and_its_children(self):
        [region] = retrieval.lore_records([("regions", "bast", {"name": "Bast", "children": [{"entry": "locations/bast"}], "knowledge": "secret", "known_by": ["Shek"]})], [], [])
        self.assertEqual((region["children"], region["knowledge"], region["known_by"]), (["locations/bast"], "secret", ["Shek"]))


class NameMatchTest(unittest.TestCase):
    def test_case_punctuation_and_the_possessive_do_not_matter(self):
        self.assertEqual(names(lore("ADMAG's gate!")), [("location", "Admag")])

    def test_a_final_s_drops_on_both_sides(self):
        self.assertEqual(names(lore("Skeletons everywhere"))[:1], [("race", "Skeleton")])
        self.assertEqual(names(lore("Is Bast safe?"))[:2], [("location", "Bast"), ("region", "Bast")])

    def test_a_leading_the_drops_from_the_name(self):
        self.assertEqual(names(lore("Is Hub far?")), [("location", "The Hub")])

    def test_the_words_must_be_in_order_with_none_between(self):
        for message in ("Kingdom of the Shek", "the Shek old Kingdom"):
            self.assertNotIn("Shek Kingdom", [hit.get("name") for hit in lore(message)])

    def test_a_longer_match_drops_a_shorter_one_inside_it(self):
        hits = lore("What of the Shek Kingdom?")
        self.assertEqual(names(hits)[0], ("faction", "Shek Kingdom"))
        self.assertNotIn(("race", "Shek"), [name for hit, name in zip(hits, names(hits)) if "name" in hit])

    def test_the_name_matches_follow_the_order_of_the_message(self):
        self.assertEqual(names(lore("From Admag through Squin")), [("location", "Admag"), ("location", "Squin")])

    def test_a_history_entry_matches_by_its_title(self):
        self.assertEqual(names(lore("Tell me of Kral and the Shek Wars."))[0], ("history", "Kral and the Shek Wars"))

    def test_a_name_match_holds_the_name_that_matched(self):
        self.assertEqual(lore("Is Hub far?")[0]["name"], "The Hub")


class ContentSearchTest(unittest.TestCase):
    def test_a_word_of_the_names_or_fields_finds_the_record(self):
        hits = lore("Who is Esata?")
        self.assertEqual(names(hits), [("faction", "Shek Kingdom")])
        self.assertEqual(hits[0]["words"], ["esata"])

    def test_a_word_of_the_texts_only_does_not_search(self):
        hits, skipped = retrieval.find_lore("I need a doctor.", LORE)
        self.assertEqual(hits, [])
        self.assertEqual(skipped, [("i", "common"), ("need", "not lore"), ("a", "common"), ("doctor", "not lore")])

    def test_a_word_in_more_than_a_tenth_of_the_records_does_not_search(self):
        hits, skipped = retrieval.find_lore("Any waystation?", LORE)
        self.assertEqual(hits, [])
        self.assertIn(("waystation", "frequent"), skipped)

    def test_a_plural_meets_its_singular(self):
        self.assertEqual(names(lore("Any work for mercenaries?")), [("faction", "Mercenary Guild")])

    def test_a_hit_below_the_score_cut_is_dropped(self):
        hits = lore("Any work for a mercenary?")
        self.assertEqual(names(hits), [("faction", "Mercenary Guild")])

    def test_a_record_that_both_steps_find_counts_once(self):
        hits = lore("What of the Shek Kingdom?")
        self.assertEqual(sum(hit["record"]["name"] == "Shek Kingdom" for hit in hits), 1)
        self.assertEqual(hits[0]["name"], "Shek Kingdom")


class PlaceOrderTest(unittest.TestCase):
    def test_without_a_place_the_hits_keep_their_score_order(self):
        self.assertEqual(set(names(lore("Any bonedogs around?"))), {("location", "Squin"), ("region", "Bast"), ("region", "Stenn Desert"), ("region", "Border Zone")})

    def test_the_current_location_then_its_region_then_the_others(self):
        self.assertEqual(names(lore("Any bonedogs around?", town="Squin", zone="Border Zone"))[:2], [("location", "Squin"), ("region", "Border Zone")])

    def test_the_locations_of_the_current_region_follow_it(self):
        self.assertEqual(names(lore("Any bonedogs around?", zone="Border Zone"))[:2], [("region", "Border Zone"), ("location", "Squin")])

    def test_without_a_zone_the_region_comes_from_the_current_location(self):
        self.assertEqual(names(lore("Any bonedogs around?", town="Squin"))[:2], [("location", "Squin"), ("region", "Border Zone")])
        self.assertEqual(names(lore("Any bonedogs around?", town="Bast"))[0], ("region", "Bast"))

    def test_a_current_place_that_is_not_a_hit_adds_no_entry(self):
        self.assertNotIn(("location", "The Hub"), names(lore("Any bonedogs around?", town="The Hub")))
        self.assertEqual(lore("Nice weather.", town="Squin", zone="Border Zone"), [])

    def test_the_neighbouring_regions_follow_the_locations_of_the_current_region(self):
        found = names(retrieval.find_lore("Any bonedogs around?", NEIGHBOURS, zone="Border Zone")[0])
        self.assertEqual(found[:3], [("region", "Border Zone"), ("location", "Squin"), ("region", "Stenn Desert")])

    def test_a_neighbour_is_no_content_hit(self):
        self.assertEqual(names(retrieval.find_lore("Is the Fog Islands dangerous?", NEIGHBOURS)[0]), [("region", "Fog Islands")])


def with_neighbours(entry):
    neighbours = {"Stenn Desert": ["Fog Islands"], "Border Zone": ["Stenn Desert"]}.get(entry["name"]) if entry["kind"] == "region" else None
    return {**entry, "fields": {**entry["fields"], "neighbours": neighbours}} if neighbours else entry


NEIGHBOURS = [with_neighbours(entry) for entry in LORE]


def memory(key, text, *members):
    return {"key": ("memory", key), "text": text, "names": list(members)}


GUARD = memory(1, "Stick asked Jorge for work. Jorge offered 200 cats to guard the door of the bar for the night and stop anyone who started trouble. Jorge named the Dust Bandits as the usual trouble.", "Stick", "Jorge")
SAND = memory(2, "Paladin Abel told Beep that the sand gets everywhere and the wind never stops.", "Beep")
DRINK = memory(3, "Beep asked Stick for a drink at night, and Stick said the bar had trouble enough.", "Beep", "Stick")
MEMORIES = [GUARD, SAND, DRINK]


def memories(message, lore_names=()):
    return retrieval.find_memories(message, MEMORIES, "Paladin Abel", list(lore_names))


class MemorySearchTest(unittest.TestCase):
    def test_a_member_name_finds_the_memory(self):
        hits = memories("Have you seen Jorge?")
        self.assertEqual([hit["record"] for hit in hits], [GUARD])
        self.assertEqual(hits[0]["name"], "Jorge")

    def test_a_lore_name_in_the_text_finds_the_memory(self):
        hits = memories("Are the Dust Bandits around?", ["Dust Bandits", "Dust Bandit Gang"])
        self.assertEqual([hit["record"] for hit in hits], [GUARD])
        self.assertEqual(hits[0]["name"], "Dust Bandits")

    def test_two_shared_words_find_the_memory(self):
        hits = memories("Who keeps the trouble out of here at night?")
        self.assertEqual([hit["record"] for hit in hits][-1], GUARD)
        self.assertEqual(hits[-1]["words"], ["trouble", "night"])

    def test_one_shared_word_does_not(self):
        self.assertEqual(memories("Do you need a guard?"), [])

    def test_a_word_of_the_npc_name_does_not_search(self):
        self.assertEqual(memories("Abel, is the sand bad?"), [])

    def test_the_newest_memory_comes_first(self):
        self.assertEqual([hit["record"] for hit in memories("Did you see Stick?")], [DRINK, GUARD])

    def test_a_memory_that_both_steps_find_counts_once(self):
        hits = memories("Did Stick find trouble at night?")
        self.assertEqual([hit["record"] for hit in hits], [DRINK, GUARD])
        self.assertTrue(all("name" in hit for hit in hits))

    def test_a_hit_below_the_score_cut_is_dropped(self):
        strong = memory(1, "Trouble at night. Trouble at night again.")
        weak = memory(2, "The caravan came at noon with salt, rice, and wheat. A guard told of old trouble in the hills, of rain, of dust, and of a long walk under a cold night sky past the ruins of the south.")
        hits = retrieval.find_memories("Any trouble tonight or last night?", [strong, weak], "Abel", [])
        self.assertEqual([hit["record"] for hit in hits], [strong])


def hit(key, name=None):
    return {"record": {"key": key}, "name": name} if name else {"record": {"key": key}, "words": ["word"]}


class ChosenTest(unittest.TestCase):
    MEMORY_HITS = [hit("m3"), hit("m2"), hit("m1")]
    LORE_HITS = [hit("l1", "Admag"), hit("l2"), hit("l3")]

    def keys(self, chosen):
        return [[hit["record"]["key"] for hit in hits] for hits in chosen]

    def test_the_lore_fills_the_slots_that_the_memories_leave(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS[:1], self.LORE_HITS, set(), set(), 3, 3)), [["m3"], ["l1", "l2"]])

    def test_the_memory_slots_cap_the_memories(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS, self.LORE_HITS, set(), set(), 3, 1)), [["m3"], ["l1", "l2"]])

    def test_as_many_memories_as_slots_leave_no_lore(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS, self.LORE_HITS, set(), set(), 3, 3)), [["m3", "m2", "m1"], []])

    def test_zero_slots_turn_the_search_off(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS, self.LORE_HITS, set(), set(), 0, 3)), [[], []])

    def test_zero_memory_slots_give_every_slot_to_the_lore(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS, self.LORE_HITS, set(), set(), 3, 0)), [[], ["l1", "l2", "l3"]])

    def test_memory_slots_above_the_slots_count_as_the_slots(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS, self.LORE_HITS, set(), set(), 2, 5)), [["m3", "m2"], []])

    def test_a_record_that_the_system_message_holds_is_skipped(self):
        self.assertEqual(self.keys(retrieval.chosen([], self.LORE_HITS, {"l1"}, set(), 3, 3)), [[], ["l2", "l3"]])

    def test_a_recent_content_hit_leaves_its_slot_to_the_next(self):
        self.assertEqual(self.keys(retrieval.chosen(self.MEMORY_HITS[:2], self.LORE_HITS, set(), {"m3", "l2"}, 3, 3)), [["m2"], ["l1", "l3"]])

    def test_a_recent_name_match_passes(self):
        self.assertEqual(self.keys(retrieval.chosen([], self.LORE_HITS, set(), {"l1"}, 1, 3)), [[], ["l1"]])


class CooldownTest(unittest.TestCase):
    def test_the_hits_of_the_last_n_turns_are_held(self):
        turns = []
        for keys in ({"a"}, {"b"}, {"c"}):
            turns = retrieval.next_turns(turns, keys, 2)
        self.assertEqual(retrieval.held(turns, 2), {"b", "c"})

    def test_a_hit_older_than_n_turns_is_not_held(self):
        turns = retrieval.next_turns(retrieval.next_turns([], {"a"}, 1), set(), 1)
        self.assertEqual(retrieval.held(turns, 1), set())

    def test_a_cooldown_of_zero_holds_nothing(self):
        self.assertEqual(retrieval.next_turns([{"a"}], {"b"}, 0), [])
        self.assertEqual(retrieval.held([{"a"}], 0), set())

    def test_a_lower_cooldown_reads_only_the_newest_turns(self):
        self.assertEqual(retrieval.held([{"a"}, {"b"}], 1), {"b"})


class ClippedTest(unittest.TestCase):
    def test_a_short_text_stays_whole(self):
        self.assertEqual(retrieval.clipped("A town. With walls."), "A town. With walls.")

    def test_a_long_text_ends_at_its_last_sentence_end_before_the_limit(self):
        text = "A" * 600 + ". " + "B" * 200 + "."
        self.assertEqual(retrieval.clipped(text), "A" * 600 + ".")

    def test_a_long_text_without_a_sentence_end_ends_at_the_limit(self):
        self.assertEqual(retrieval.clipped("A" * 900), "A" * retrieval.TEXT_LIMIT)


if __name__ == "__main__":
    unittest.main()
