import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from store import world_template

SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "templates")

HOLY_NATION = {"game_id": "1083-gamedata.base", "name": "The Holy Nation", "aliases": ["Okranites"], "major": True, "fields": {"leader": "Phoenix"}, "description": "Zealots."}


class ShippedTemplateTest(unittest.TestCase):
    def test_every_shipped_template_is_valid(self):
        for entry in world_template.listing(SHIPPED, os.devnull):
            template = world_template.load(entry["name"], SHIPPED, os.devnull)
            self.assertEqual(world_template.validate(template), ([], []), entry["name"])

    def test_the_vanilla_seed_holds_the_overview_and_the_factions(self):
        seed = world_template.campaign_seed("kenshi_ssr_vanilla", SHIPPED, os.devnull)
        self.assertIn("KENSHI WORLD LORE", seed["overview"])
        holy_nation = next(f for f in seed["factions"] if f["faction_id"] == "1083-gamedata.base")
        self.assertEqual(holy_nation["name"], "The Holy Nation")
        self.assertEqual(len(seed["template"]["hash"]), 64)

    def test_no_vanilla_character_text_says_that_its_data_is_missing(self):
        characters = world_template.load("kenshi_ssr_vanilla", SHIPPED, os.devnull)["characters"]
        for record_id, character in characters.items():
            for key in ("Personality", "Backstory", "SpeechQuirks"):
                self.assertNotRegex(character["profile"].get(key, ""), re.compile(r"\b(?:is|are) (?:recorded|unknown)\b", re.IGNORECASE), f"{record_id} {key}")


class TemplateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.shipped = os.path.join(self._tmp.name, "world_templates")
        self.user = os.path.join(self._tmp.name, "user", "world_templates")
        self.write("base", "manifest.json", {"format_version": 1, "name": "Base", "description": "Rust and sand.", "version": "1.0.0", "authors": ["SSR"], "credits": ["SentientSands Kayak by Harvicus and Pineaxe."]})
        self.write("base", "overview.txt", "A world of rust.\r\n")
        self.write("base", "factions/holy_nation.json", HOLY_NATION)
        self.write("base", "ADDITIONAL_TERMS.md", "Keep the credit line.")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, template, relative, content, root=None):
        path = os.path.join(root or self.shipped, template, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))

    def problems(self, name="base"):
        return world_template.validate(world_template.load(name, self.shipped, self.user))

    def fields(self, name="base"):
        return [error["field"] for error in self.problems(name)[0]]


class ValidateTest(TemplateTestCase):
    def test_a_valid_template_has_no_problems(self):
        self.assertEqual(self.problems(), ([], []))

    def test_an_unknown_format_version_is_an_error(self):
        self.write("base", "manifest.json", {"format_version": 2, "name": "Base"})
        self.assertEqual(self.fields(), [["manifest", "format_version"]])

    def test_a_description_that_is_not_text_is_an_error(self):
        self.write("base", "manifest.json", {"format_version": 1, "name": "Base", "description": ["Rust"]})
        self.assertEqual(self.fields(), [["manifest", "description"]])

    def test_a_file_that_does_not_parse_is_an_error(self):
        self.write("base", "factions/broken.json", "{")
        self.assertEqual(self.fields(), [["factions/broken.json"]])

    def test_a_faction_needs_a_name_and_a_game_id(self):
        self.write("base", "factions/empty.json", {})
        self.assertEqual(self.fields(), [["factions", "empty", "name"], ["factions", "empty", "game_id"]])

    def test_two_factions_with_one_game_id_are_an_error(self):
        self.write("base", "factions/copy.json", dict(HOLY_NATION, name="Copy"))
        self.assertEqual(self.fields(), [["factions", "holy_nation", "game_id"]])

    def test_a_character_needs_a_game_id_and_a_name(self):
        self.write("base", "characters/beep.json", {"profile": {"Race": "Hive Worker Drone"}})
        self.assertEqual(self.fields(), [["characters", "beep", "game_id"], ["characters", "beep", "profile", "Name"]])

    def test_an_entity_needs_a_name(self):
        self.write("base", "locations/hub.json", {"fields": {"owner": ["The Holy Nation"]}})
        self.assertEqual(self.fields(), [["locations", "hub", "name"]])

    def test_a_fact_needs_a_category_of_its_kind(self):
        self.write("base", "locations/hub.json", {"name": "The Hub", "fields": {"leader": "Phoenix"}})
        self.assertEqual([error["message"] for error in self.problems()[0]], ["leader is not a fact of a location. Choose one of type, zone, owner."])

    def test_a_fact_needs_the_shape_of_its_category(self):
        self.write("base", "factions/holy_nation.json", dict(HOLY_NATION, fields={"leader": ["Phoenix"], "enemies": "Shek Kingdom"}))
        self.assertEqual([error["message"] for error in self.problems()[0]], ["The fact leader must be text.", "The fact enemies must be a list of text."])

    def test_each_neighbour_needs_a_direction(self):
        for neighbours in (["Stenn Desert"], {"Stenn Desert": ""}, {"Stenn Desert": "up"}):
            self.write("base", "regions/vain.json", {"name": "Vain", "fields": {"neighbours": neighbours}})
            self.assertEqual([error["message"] for error in self.problems()[0]], [
                "The fact neighbours must give each region one of the directions north, northeast, east, southeast, south, southwest, west, northwest.",
            ])

    def test_an_entity_description_must_be_text(self):
        self.write("base", "locations/hub.json", {"name": "The Hub", "description": {"text": "Bars."}})
        self.assertEqual(self.fields(), [["locations", "hub", "description"]])

    def test_a_folder_of_another_category_is_an_error(self):
        self.write("base", "items/sword.json", {"name": "Sword"})
        self.assertEqual(self.fields(), [["items"]])

    def test_an_unknown_tier_is_an_error(self):
        self.write("base", "factions/holy_nation.json", dict(HOLY_NATION, knowledge="public"))
        self.assertEqual(self.fields(), [["factions", "holy_nation", "knowledge"]])

    def test_a_known_by_warns_on_a_record_that_is_not_secret_and_on_a_name_that_names_nothing(self):
        self.write("base", "races/skeleton.json", {"name": "Skeleton"})
        self.write("base", "characters/elder.json", {"game_id": "x", "knowledge": "secret", "profile": {"Name": "Elder"}})
        self.write("base", "history.json", [
            {"title": "Obedience", "text": "The quarry.", "knowledge": "secret", "known_by": ["the Skeletons", "Holy Nation", "okranite", "Elder", "Nobody"]},
            {"title": "Stobe", "text": "A legend.", "known_by": ["Skeleton"]},
        ])
        errors, warnings = self.problems()
        self.assertEqual(errors, [])
        self.assertEqual([(warning["field"], warning["message"]) for warning in warnings], [
            (["history", 0, "known_by"], "Nobody in the Known by of Obedience names no character, faction, or race."),
            (["history", 1, "known_by"], "Stobe is not Secret, so its Known by does nothing."),
        ])

    def test_a_neighbour_that_names_no_region_is_a_warning(self):
        self.write("base", "regions/vain.json", {"name": "Vain", "fields": {"neighbours": {"the Stenn Deserts": "south", "Nowhere": "east"}}})
        self.write("base", "regions/stenn_desert.json", {"name": "Stenn Desert"})
        self.assertEqual([warning["message"] for warning in self.problems()[1]], ["The neighbour Nowhere of Vain names no region."])

    def test_the_two_sides_of_a_neighbour_pair_must_be_opposite(self):
        self.write("base", "regions/vain.json", {"name": "Vain", "fields": {"neighbours": {"Stenn Desert": "south"}}})
        self.write("base", "regions/stenn_desert.json", {"name": "Stenn Desert", "aliases": ["Stenn"], "fields": {"neighbours": {"Vain": "north"}}})
        self.assertEqual(self.problems(), ([], []))
        self.write("base", "regions/stenn_desert.json", {"name": "Stenn Desert", "aliases": ["Stenn"], "fields": {"neighbours": {"the Vain": "northwest"}}})
        self.assertEqual([warning["message"] for warning in self.problems()[1]], [
            "Stenn Desert puts the Vain to the northwest, so the Vain must put Stenn Desert to the southeast, not the south.",
            "Vain puts Stenn Desert to the south, so Stenn Desert must put Vain to the north, not the northwest.",
        ])

    def test_the_knowledge_of_a_character_goes_beside_its_profile(self):
        self.write("base", "characters/beep.json", {"game_id": "x", "knowledge": "global", "profile": {"Name": "Beep"}})
        self.assertEqual(self.problems(), ([], []))
        self.write("base", "characters/beep.json", {"game_id": "x", "profile": {"Name": "Beep", "knowledge": ["global"]}})
        self.assertEqual(self.fields(), [["characters", "beep", "profile"]])

    def test_record_problems_checks_one_record(self):
        self.assertEqual(world_template.record_problems("faction", HOLY_NATION, ["f"]), ([], []))
        self.assertEqual([e["field"] for e in world_template.record_problems("faction", dict(HOLY_NATION, major="yes"), ["f"])[0]], [["f", "major"]])
        self.assertEqual([e["field"] for e in world_template.record_problems("character", {"game_id": "x", "profile": {}}, ["c"])[0]], [["c", "profile", "Name"]])
        self.assertEqual([e["field"] for e in world_template.record_problems("entity", {"name": ""}, ["locations", "hub"])[0]], [["locations", "hub", "name"]])
        self.assertEqual([e["field"] for e in world_template.record_problems("history", [{"title": ""}], ["history"])[0]], [["history", 0]])
        secret = dict(HOLY_NATION, knowledge="secret", known_by=["Nobody"])
        self.assertEqual(world_template.record_problems("faction", secret, ["f"]), ([], []))
        self.assertEqual(len(world_template.record_problems("faction", secret, ["f"], names={"knowers": {("skeleton",)}, "regions": set()})[1]), 1)


class SaveTest(TemplateTestCase):
    def setUp(self):
        super().setUp()
        world_template.duplicate("base", "Mine", self.shipped, self.user)

    def test_the_listing_gives_the_title_and_the_counts_of_each_template(self):
        self.write("base", "regions/okran.json", {"name": "Okran's Pride"})
        self.assertEqual(world_template.listing(self.shipped, self.user), [
            {"name": "base", "builtin": True, "title": "Base", "description": "Rust and sand.", "counts": {"factions": 1, "characters": 0, "entities": 1}},
            {"name": "Mine", "builtin": False, "title": "Mine", "description": "Rust and sand.", "counts": {"factions": 1, "characters": 0, "entities": 0}},
        ])

    def test_a_shipped_template_is_read_only(self):
        with self.assertRaisesRegex(world_template.TemplateError, "Duplicate it"):
            world_template.save_record("base", "overview", None, "Changed.", self.shipped, self.user)

    def test_duplicate_keeps_every_file_and_takes_the_new_name(self):
        template = world_template.load("Mine", self.shipped, self.user)
        self.assertFalse(template["builtin"])
        self.assertEqual(template["manifest"]["name"], "Mine")
        self.assertEqual(template["manifest"]["credits"], ["SentientSands Kayak by Harvicus and Pineaxe."])
        self.assertTrue(os.path.exists(os.path.join(self.user, "Mine", "ADDITIONAL_TERMS.md")))
        self.assertEqual(os.listdir(self.user), ["Mine"])

    def test_duplicate_refuses_a_taken_or_unsafe_name(self):
        for name in ("mine", "base", "../escape", ""):
            with self.assertRaises(world_template.TemplateError, msg=name):
                world_template.duplicate("base", name, self.shipped, self.user)

    def test_duplicate_and_import_refuse_the_title_of_another_template(self):
        self.write("other", "manifest.json", {"format_version": 1, "name": "Rust World"})
        with self.assertRaisesRegex(world_template.TemplateError, "already exists"):
            world_template.duplicate("base", "rust world", self.shipped, self.user)
        with self.assertRaisesRegex(world_template.TemplateError, "already exists"):
            world_template.import_template(world_template.export_template("base", self.shipped, self.user), "Rust World", self.shipped, self.user)

    def test_a_new_record_takes_its_id_from_its_name(self):
        faction = dict(HOLY_NATION, game_id="42022-rebirth.mod", name="Holy Nation Outlaws")
        record_id, _ = world_template.save_record("Mine", "faction", None, faction, self.shipped, self.user)
        self.assertEqual(record_id, "holy_nation_outlaws")
        record_id, _ = world_template.save_record("Mine", "faction", None, dict(faction, game_id="other"), self.shipped, self.user)
        self.assertEqual(record_id, "holy_nation_outlaws_2")
        self.assertEqual(len(world_template.load("Mine", self.shipped, self.user)["factions"]), 3)

    def test_an_invalid_record_is_not_written(self):
        with self.assertRaises(world_template.TemplateError) as raised:
            world_template.save_record("Mine", "faction", "holy_nation", dict(HOLY_NATION, name=""), self.shipped, self.user)
        self.assertEqual(raised.exception.errors[0]["field"], ["factions", "holy_nation", "name"])
        self.assertEqual(world_template.load("Mine", self.shipped, self.user)["factions"]["holy_nation"]["name"], "The Holy Nation")

    def test_an_entity_goes_into_its_category_folder(self):
        world_template.save_record("Mine", "entity", None, {"name": "Stenn Desert"}, self.shipped, self.user, category="regions")
        self.assertTrue(os.path.exists(os.path.join(self.user, "Mine", "regions", "stenn_desert.json")))

    def test_unsafe_ids_and_categories_are_refused(self):
        with self.assertRaises(world_template.TemplateError):
            world_template.save_record("Mine", "faction", "../x", HOLY_NATION, self.shipped, self.user)
        with self.assertRaises(world_template.TemplateError):
            world_template.save_record("Mine", "entity", None, {"name": "X"}, self.shipped, self.user, category="../x")
        with self.assertRaisesRegex(world_template.TemplateError, "items is not a category"):
            world_template.save_record("Mine", "entity", None, {"name": "X"}, self.shipped, self.user, category="items")

    def test_delete_record_and_template(self):
        world_template.delete_record("Mine", "faction", "holy_nation", self.shipped, self.user)
        self.assertEqual(world_template.load("Mine", self.shipped, self.user)["factions"], {})
        world_template.delete("Mine", self.shipped, self.user)
        self.assertEqual([t["name"] for t in world_template.listing(self.shipped, self.user)], ["base"])
        with self.assertRaises(world_template.TemplateError):
            world_template.delete("base", self.shipped, self.user)

    def test_the_seed_copies_every_kind_of_record(self):
        world_template.save_record("Mine", "history", None, [{"title": "Then", "text": "It was."}], self.shipped, self.user)
        world_template.save_record("Mine", "character", None, {"game_id": "19576-Dialogue.mod", "profile": {"Name": "Beep"}, "note": "dropped"}, self.shipped, self.user)
        world_template.save_record("Mine", "entity", None, {"name": "Stenn Desert"}, self.shipped, self.user, category="regions")
        seed = world_template.campaign_seed("Mine", self.shipped, self.user)
        self.assertEqual(seed["history"], [{"title": "Then", "text": "It was."}])
        self.assertEqual(seed["characters"], [{"game_id": "19576-Dialogue.mod", "profile": {"Name": "Beep"}}])
        world_template.save_record("Mine", "character", "beep", {"game_id": "19576-Dialogue.mod", "profile": {"Name": "Beep"}, "knowledge": "secret", "known_by": ["Beep"]}, self.shipped, self.user)
        seed = world_template.campaign_seed("Mine", self.shipped, self.user)
        self.assertEqual(seed["characters"], [{"game_id": "19576-Dialogue.mod", "profile": {"Name": "Beep"}, "knowledge": "secret", "known_by": ["Beep"]}])
        self.assertEqual(seed["entities"], [{"category": "regions", "id": "stenn_desert", "data": {"name": "Stenn Desert"}}])

    def test_a_template_with_an_error_gives_no_campaign_seed(self):
        self.write("Mine", "factions/broken.json", "{", root=self.user)
        with self.assertRaises(world_template.TemplateError):
            world_template.campaign_seed("Mine", self.shipped, self.user)


class ExchangeTest(TemplateTestCase):
    def test_an_export_imports_as_the_same_template_under_the_new_name(self):
        exported = world_template.export_template("base", self.shipped, self.user)
        self.assertEqual(list(exported), ["manifest", "overview", "history", "factions", "characters", "races", "locations", "regions"])
        self.assertEqual(world_template.import_template(exported, "Shared", self.shipped, self.user), "Shared")
        self.assertEqual(world_template.export_template("Shared", self.shipped, self.user), dict(exported, manifest=dict(exported["manifest"], name="Shared")))

    def test_an_import_takes_the_knowledge_keys(self):
        exported = world_template.export_template("base", self.shipped, self.user)
        exported["factions"]["holy_nation"].update(knowledge="secret", known_by=["Okranites"])
        exported.update(history=[{"title": "Then", "text": "It was.", "knowledge": "limited"}], regions={"vain": {"name": "Vain", "knowledge": "limited"}},
                        characters={"beep": {"game_id": "x", "knowledge": "global", "profile": {"Name": "Beep"}}})
        world_template.import_template(exported, "Shared", self.shipped, self.user)
        self.assertEqual(world_template.export_template("Shared", self.shipped, self.user), dict(exported, manifest=dict(exported["manifest"], name="Shared")))

    def test_the_vanilla_template_survives_a_round_trip(self):
        exported = world_template.export_template("kenshi_ssr_vanilla", SHIPPED, self.user)
        world_template.import_template(json.loads(json.dumps(exported)), "Vanilla copy", SHIPPED, self.user)
        imported = world_template.export_template("Vanilla copy", SHIPPED, self.user)
        self.assertEqual(imported, dict(exported, manifest=dict(exported["manifest"], name="Vanilla copy")))
        self.assertEqual(world_template.validate(world_template.load("Vanilla copy", SHIPPED, self.user)), ([], []))

    def test_an_unsafe_or_invalid_file_leaves_nothing_on_disk(self):
        exported = world_template.export_template("base", self.shipped, self.user)
        cases = {
            "not an object": ([exported], "Shared"),
            "an unknown part": (dict(exported, items={}), "Shared"),
            "an ID with a path": (dict(exported, factions={"../escape": HOLY_NATION}), "Shared"),
            "records that are not an object": (dict(exported, races=[{"name": "Shek"}]), "Shared"),
            "an invalid record": (dict(exported, characters={"beep": {"profile": {"Name": "Beep"}}}), "Shared"),
            "a version that is not text": (dict(exported, manifest=dict(exported["manifest"], version=2)), "Shared"),
            "an unknown key in the manifest": (dict(exported, manifest=dict(exported["manifest"], licence="GPL")), "Shared"),
            "an unknown key in a history entry": (dict(exported, history=[{"title": "Then", "text": "It was.", "year": 1}]), "Shared"),
            "an unknown key in a record": (dict(exported, factions={"holy_nation": dict(HOLY_NATION, descripton="Zealots.")}), "Shared"),
            "IDs that differ only in case": (dict(exported, characters={"beep": {"game_id": "1", "profile": {"Name": "Beep"}}, "Beep": {"game_id": "2", "profile": {"Name": "Beep"}}}), "Shared"),
            "a taken name": (exported, "BASE"),
            "an unsafe name": (exported, "../escape"),
        }
        for case, (data, name) in cases.items():
            with self.assertRaises(world_template.TemplateError, msg=case):
                world_template.import_template(data, name, self.shipped, self.user)
            self.assertEqual(os.listdir(self.user) if os.path.isdir(self.user) else [], [], case)

    def test_each_problem_names_its_place_in_the_file(self):
        exported = world_template.export_template("base", self.shipped, self.user)

        def messages(data):
            with self.assertRaises(world_template.TemplateError) as raised:
                world_template.import_template(data, "Shared", self.shipped, self.user)
            return [error["message"] for error in raised.exception.errors]

        self.assertEqual(messages({"campaign": "Default"}), ["This file is not an SSR world template. Choose a file that the Export button saved."])
        self.assertEqual(messages(dict(exported, factions={"holy_nation": dict(HOLY_NATION, descripton="Zealots.")})), ["The Holy Nation (faction): SSR does not use descripton. Check the spelling, or remove it."])
        self.assertEqual(messages(dict(exported, characters={"beep": {"profile": {"Name": "Beep"}}})), ["Beep (character): Give the character its game ID."])
        self.assertEqual(messages(dict(exported, history=[{"title": "Then", "text": "It was.", "year": 1}])), ["History entry 1: SSR does not use year. Check the spelling, or remove it."])


if __name__ == "__main__":
    unittest.main()
