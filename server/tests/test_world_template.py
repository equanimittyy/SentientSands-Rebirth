import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import world_template

SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "world_templates")

HOLY_NATION = {"game_id": "1083-gamedata.base", "name": "The Holy Nation", "aliases": ["Okranites"], "major": True, "fields": {"leader": "Phoenix"}, "description": "Zealots."}


class ShippedTemplateTest(unittest.TestCase):
    def test_every_shipped_template_is_valid(self):
        for entry in world_template.listing(SHIPPED, os.devnull):
            template = world_template.load(entry["name"], SHIPPED, os.devnull)
            self.assertEqual(world_template.validate(template), ([], []), entry["name"])

    def test_the_vanilla_seed_holds_the_overview_and_the_factions(self):
        seed = world_template.campaign_seed("vanilla_kenshi", SHIPPED, os.devnull)
        self.assertIn("KENSHI WORLD LORE", seed["overview"])
        holy_nation = next(f for f in seed["factions"] if f["faction_id"] == "1083-gamedata.base")
        self.assertEqual(holy_nation["name"], "The Holy Nation")
        self.assertEqual(len(seed["template"]["hash"]), 64)


class TemplateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.shipped = os.path.join(self._tmp.name, "world_templates")
        self.user = os.path.join(self._tmp.name, "user", "world_templates")
        self.write("base", "manifest.json", {"format_version": 1, "name": "Base", "version": "1.0.0", "authors": ["SSR"], "credits": ["SentientSands Kayak by Harvicus and Pineaxe."]})
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
        self.write("base", "locations/hub.json", {"fields": {"owner": "The Holy Nation"}})
        self.assertEqual(self.fields(), [["locations", "hub", "name"]])

    def test_a_folder_of_another_category_is_an_error(self):
        self.write("base", "items/sword.json", {"name": "Sword"})
        self.assertEqual(self.fields(), [["items"]])

    def test_a_child_that_names_no_entity_is_a_warning(self):
        self.write("base", "locations/hub.json", {"name": "The Hub", "aliases": ["Hub"], "children": [{"name": "Bar", "weight": 2}]})
        self.write("base", "locations/bar.json", {"name": "The Bar", "children": [{"name": "hub"}]})
        errors, warnings = self.problems()
        self.assertEqual(errors, [])
        self.assertEqual([warning["field"] for warning in warnings], [["locations", "hub", "children"]])

    def test_record_problems_checks_one_record(self):
        self.assertEqual(world_template.record_problems("faction", HOLY_NATION, ["f"]), ([], []))
        self.assertEqual([e["field"] for e in world_template.record_problems("faction", dict(HOLY_NATION, major="yes"), ["f"])[0]], [["f", "major"]])
        self.assertEqual([e["field"] for e in world_template.record_problems("character", {"game_id": "x", "profile": {}}, ["c"])[0]], [["c", "profile", "Name"]])
        hub = {"name": "The Hub", "children": [{"name": "Bar"}]}
        self.assertEqual(len(world_template.record_problems("entity", hub, ["e"])[1]), 1)
        self.assertEqual(world_template.record_problems("entity", hub, ["e"], world_template.entity_names([{"name": "x", "aliases": ["bar"]}])), ([], []))
        self.assertEqual([e["field"] for e in world_template.record_problems("history", [{"title": ""}], ["history"])[0]], [["history", 0]])


class SaveTest(TemplateTestCase):
    def setUp(self):
        super().setUp()
        world_template.duplicate("base", "Mine", self.shipped, self.user)

    def test_the_listing_gives_the_title_and_the_counts_of_each_template(self):
        self.write("base", "regions/okran.json", {"name": "Okran's Pride"})
        self.assertEqual(world_template.listing(self.shipped, self.user), [
            {"name": "base", "builtin": True, "title": "Base", "counts": {"factions": 1, "characters": 0, "entities": 1}},
            {"name": "Mine", "builtin": False, "title": "Mine", "counts": {"factions": 1, "characters": 0, "entities": 0}},
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

    def test_duplicate_refuses_a_taken_or_unsafe_name(self):
        for name in ("mine", "base", "../escape", ""):
            with self.assertRaises(world_template.TemplateError, msg=name):
                world_template.duplicate("base", name, self.shipped, self.user)

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
        self.assertEqual(seed["entities"], [{"category": "regions", "id": "stenn_desert", "data": {"name": "Stenn Desert"}}])

    def test_a_template_with_an_error_gives_no_campaign_seed(self):
        self.write("Mine", "factions/broken.json", "{", root=self.user)
        with self.assertRaises(world_template.TemplateError):
            world_template.campaign_seed("Mine", self.shipped, self.user)


if __name__ == "__main__":
    unittest.main()
