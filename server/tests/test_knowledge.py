import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import knowledge, retrieval

CATEGORIES = {"race": "races", "faction": "factions", "location": "locations", "region": "regions", "history": "history", "character": "characters"}


def record(kind, name, fields=None, knowledge="", known_by=(), children=(), origin_faction="", text="Text."):
    found = {"key": (CATEGORIES[kind], name), "kind": kind, "name": name, "aliases": [], "fields": fields or {}, "description": text,
             "children": list(children), "knowledge": knowledge, "known_by": list(known_by)}
    return {**found, "origin_faction": origin_faction} if kind == "character" else found


def key(kind, name):
    return (CATEGORIES[kind], name)


def knows(records, identity=(), town=None, zone=None):
    return {name for _, name in knowledge.known(records, set(identity), town, zone)}


class TierTest(unittest.TestCase):
    def test_a_character_defaults_to_limited_and_every_other_kind_to_global(self):
        self.assertEqual({kind: knowledge.tier(record(kind, "X")) for kind in CATEGORIES}, {kind: "limited" if kind == "character" else "global" for kind in CATEGORIES})

    def test_an_empty_knowledge_is_the_default(self):
        self.assertEqual(knowledge.tier(record("character", "X", knowledge="")), "limited")
        self.assertEqual(knowledge.tier(record("character", "X", knowledge="global")), "global")

    def test_a_global_record_reaches_every_npc(self):
        self.assertEqual(knows([record("region", "Vain")]), {"Vain"})


class OwnRecordTest(unittest.TestCase):
    def test_each_own_record_of_the_identity_is_known(self):
        records = [record("character", "Beep"), record("faction", "Hivers", knowledge="limited"), record("faction", "Drifters", knowledge="limited"), record("race", "Hiver", knowledge="limited")]
        self.assertEqual(knows(records, [key("character", "Beep"), key("faction", "Hivers"), key("faction", "Drifters"), key("race", "Hiver")]), {"Beep", "Hivers", "Drifters", "Hiver"})
        self.assertEqual(knows(records), set())

    def test_the_current_location_and_the_current_region_are_own_records(self):
        squin, border_zone = record("location", "Squin", {"zone": ["Border Zone"]}, knowledge="limited"), record("region", "Border Zone", knowledge="limited")
        self.assertEqual(knows([squin, border_zone], town="Squin"), {"Squin", "Border Zone"})
        self.assertEqual(knows([border_zone, record("location", "Admag", knowledge="limited")], zone="Border Zone"), {"Border Zone"})


class LinkTest(unittest.TestCase):
    def test_a_field_links_in_both_directions(self):
        records = [record("faction", "Anti-Slavers", {"leader": "Tinfist"}, knowledge="limited"), record("character", "Tinfist")]
        self.assertEqual(knows(records, [key("faction", "Anti-Slavers")]), {"Anti-Slavers", "Tinfist"})
        self.assertEqual(knows(records, [key("character", "Tinfist")]), {"Anti-Slavers", "Tinfist"})

    def test_a_child_links_to_its_entry(self):
        records = [record("region", "Bast", knowledge="limited", children=["locations/Bast Ruins"]), record("location", "Bast Ruins", knowledge="limited")]
        self.assertEqual(knows(records, [key("location", "Bast Ruins")]), {"Bast", "Bast Ruins"})

    def test_the_faction_and_the_origin_faction_of_a_character_link(self):
        records = [record("faction", "Anti-Slavers"), record("faction", "Holy Nation"), record("character", "Bo", {"faction": "Anti-Slavers"}, origin_faction="Holy Nation")]
        self.assertIn("Bo", knows(records, [key("faction", "Anti-Slavers")]))
        self.assertIn("Bo", knows(records, [key("faction", "Holy Nation")]))

    def test_the_text_of_a_history_entry_links_and_the_text_of_another_record_does_not(self):
        records = [record("race", "Shek"), record("history", "Kral", knowledge="limited", text="Kral led the Shek."), record("region", "Stenn Desert", knowledge="limited", text="Home of the Shek.")]
        self.assertEqual(knows(records, [key("race", "Shek")]), {"Shek", "Kral"})

    def test_the_race_of_a_character_is_no_link(self):
        records = [record("race", "Greenlander"), record("character", "Ruka", {"race": "Greenlander"})]
        self.assertEqual(knows(records, [key("race", "Greenlander")]), {"Greenlander"})

    def test_the_faction_of_a_character_links_only_to_a_faction(self):
        records = [record("race", "Skeleton"), record("faction", "Skeletons"), record("character", "Quin", {"faction": "Skeletons"})]
        self.assertNotIn("Quin", knows(records, [key("race", "Skeleton")]))

    def test_no_second_hop(self):
        records = [record("faction", "Holy Nation", {"enemies": ["Anti-Slavers"]}), record("faction", "Anti-Slavers", {"leader": "Tinfist"}), record("character", "Tinfist")]
        self.assertNotIn("Tinfist", knows(records, [key("faction", "Holy Nation")]))

    def test_a_field_value_that_names_no_record_links_nothing(self):
        records = [record("faction", "Skeleton Bandits", {"leader": "Cat-Lon"}, knowledge="limited"), record("character", "Cat")]
        self.assertEqual(knows(records, [key("character", "Cat")]), {"Cat"})

    def test_a_field_value_matches_a_name_without_case_a_leading_the_and_a_final_s(self):
        for value in ("great desert", "Great Deserts", "The Great Desert"):
            records = [record("faction", "United Cities", {"territory": [value]}), record("region", "The Great Desert", knowledge="limited")]
            self.assertIn("The Great Desert", knows(records, [key("faction", "United Cities")]), value)


class PlaceTest(unittest.TestCase):
    WORLD = [
        record("region", "Border Zone", {"neighbours": ["Stenn Desert"]}, knowledge="limited"),
        record("region", "Stenn Desert", {"factions": ["Hungry Bandits"]}, knowledge="limited"),
        record("region", "Vain", {"neighbours": ["Stenn Desert"]}, knowledge="limited"),
        record("location", "The Hub", {"zone": ["Border Zone"], "owner": ["Holy Nation Outlaws"]}, knowledge="limited"),
        record("location", "Admag", {"zone": ["Stenn Desert"]}, knowledge="limited"),
        record("faction", "Holy Nation Outlaws", knowledge="limited"),
        record("faction", "Dust Bandits", {"territory": ["Border Zone"], "leader": "Dust King"}, knowledge="limited"),
        record("faction", "Shek Kingdom", {"capital": "Admag", "territory": ["Stenn Desert"]}, knowledge="limited"),
        record("faction", "Mercenary Guild", {"bases": ["Vain"]}, knowledge="limited"),
        record("faction", "Hungry Bandits", knowledge="limited"),
        record("character", "Dust King", {"faction": "Dust Bandits"}),
        record("character", "Hungry Chief", {"faction": "Hungry Bandits"}),
    ]

    def test_a_holding_faction_through_territory_bases_capital_and_owner_with_its_characters(self):
        self.assertEqual(knows(self.WORLD, town="The Hub"), {"The Hub", "Border Zone", "Stenn Desert", "Admag", "Holy Nation Outlaws", "Dust Bandits", "Dust King", "Shek Kingdom", "Hungry Bandits"})
        self.assertEqual(knows(self.WORLD, town="Admag"), {"Admag", "Stenn Desert", "Border Zone", "Vain", "The Hub", "Shek Kingdom", "Mercenary Guild", "Dust Bandits", "Dust King", "Hungry Bandits"})

    def test_a_faction_of_a_region_holds_nothing_so_its_characters_stay_unknown(self):
        found = knows(self.WORLD, zone="Stenn Desert")
        self.assertIn("Hungry Bandits", found)
        self.assertNotIn("Hungry Chief", found)

    def test_a_neighbouring_region_that_either_region_names(self):
        self.assertIn("Stenn Desert", knows(self.WORLD, zone="Border Zone"))
        self.assertIn("Border Zone", knows(self.WORLD, zone="Stenn Desert"))

    def test_a_town_and_a_holding_faction_of_a_neighbouring_region(self):
        self.assertTrue({"Admag", "Shek Kingdom"} <= knows(self.WORLD, zone="Border Zone"))

    def test_no_region_two_steps_away(self):
        self.assertNotIn("Vain", knows(self.WORLD, zone="Border Zone"))

    def test_no_link_through_neighbours(self):
        self.assertEqual(knows(self.WORLD, [key("region", "Stenn Desert")]), {"Stenn Desert", "Admag", "Shek Kingdom", "Hungry Bandits"})


class SecretTest(unittest.TestCase):
    def secret(self, *known_by):
        return [
            record("history", "Obedience", knowledge="secret", known_by=known_by),
            record("character", "Elder", {"faction": "Skeleton Bandits"}), record("faction", "Skeleton Bandits"), record("faction", "Skeletons", {"leader": "Elder"}),
            record("race", "Skeleton"), record("region", "Obedience Region", {"neighbours": []}),
        ]

    def test_secret_by_the_npc_its_current_faction_its_origin_faction_and_its_race(self):
        for identity, known_by in (([key("character", "Elder")], "Elder"), ([key("faction", "Skeleton Bandits")], "Skeleton Bandits"), ([key("race", "Skeleton")], "Skeleton")):
            self.assertIn("Obedience", knows(self.secret(known_by), identity), known_by)
            self.assertNotIn("Obedience", knows(self.secret(known_by), [key("faction", "Skeletons" if known_by != "Skeleton" else "Skeleton Bandits")]), known_by)

    def test_a_name_that_names_both_a_race_and_a_faction_names_each(self):
        records = self.secret("Skeleton")
        self.assertIn("Obedience", knows(records, [key("race", "Skeleton")]))
        self.assertIn("Obedience", knows(records, [key("faction", "Skeletons")]))

    def test_no_secret_through_a_link_or_a_holding_faction(self):
        records = [
            record("history", "The Chaos Age", knowledge="secret", known_by=["Skeletons"], text="The Skeletons and Black Desert City."),
            record("faction", "Skeletons", {"territory": ["Black Desert"]}), record("region", "Black Desert"), record("location", "Black Desert City", {"zone": ["Black Desert"]}),
        ]
        self.assertEqual(knows(records, zone="Black Desert"), {"Skeletons", "Black Desert", "Black Desert City"})
        self.assertNotIn("The Chaos Age", knows(records, [key("location", "Black Desert City")]))

    def test_an_empty_known_by_reaches_no_npc(self):
        records = [record("history", "Kenshi is a Moon", knowledge="secret"), record("faction", "Skeletons")]
        self.assertEqual(knows(records, [key("faction", "Skeletons")]), {"Skeletons"})


class CharacterRecordTest(unittest.TestCase):
    def test_a_character_record_holds_its_race_faction_and_backstory_without_unknown(self):
        profile = {"Name": "Tinfist", "Race": "Skeleton", "Faction": "Anti-Slavers", "OriginFaction": "Unknown", "Backstory": "Leader of the Anti-Slavers.", "Personality": "Stern."}
        [found] = retrieval.lore_records([], [], [], [{"npc_id": "u:1", "profile": profile, "knowledge": "global", "known_by": []}])
        self.assertEqual((found["key"], found["kind"], found["name"], found["fields"], found["description"], found["origin_faction"], knowledge.tier(found)),
                         (("characters", "u:1"), "character", "Tinfist", {"race": "Skeleton", "faction": "Anti-Slavers"}, "Leader of the Anti-Slavers.", "", "global"))


if __name__ == "__main__":
    unittest.main()
