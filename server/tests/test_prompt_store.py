import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import prompt_store


class RenderTest(unittest.TestCase):
    def test_fills_known_placeholders_only(self):
        self.assertEqual(prompt_store.render("Hi {name}, {other} { {", {"name": "Beep"}), "Hi Beep, {other} { {")

    def test_does_not_expand_braces_in_values(self):
        self.assertEqual(prompt_store.render("{a} {b}", {"a": "{b}", "b": "x"}), "{b} x")

    def test_keeps_json_examples(self):
        text = '{\n  "Beep": { "Personality": "..." }\n}'
        self.assertEqual(prompt_store.render(text, {}), text)

    def test_placeholders(self):
        self.assertEqual(prompt_store.placeholders('{name} {race} { "x": 1 }'), {"name", "race"})


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.shipped = os.path.join(self.root.name, "prompts")
        self.user = os.path.join(self.root.name, "user", "prompts")
        os.makedirs(self.shipped)
        self.ship("greeting.txt", "Hello {name} the {race}.\r\n")
        self.ship("notes.md", "Not a prompt.")

    def tearDown(self):
        self.root.cleanup()

    def ship(self, name, text):
        with open(os.path.join(self.shipped, name), "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def save(self, name, text):
        return prompt_store.save(name, text, self.shipped, self.user)

    def entry(self, name):
        return next(e for e in prompt_store.listing(self.shipped, self.user) if e["name"] == name)

    def load(self, name):
        return prompt_store.load(name, self.shipped, self.user)

    def test_lists_only_shipped_prompts(self):
        self.assertEqual([e["name"] for e in prompt_store.listing(self.shipped, self.user)], ["greeting.txt"])

    def test_without_override_loads_default(self):
        self.assertEqual(self.load("greeting.txt"), "Hello {name} the {race}.")
        self.assertEqual(self.entry("greeting.txt"), {
            "name": "greeting.txt", "shipped": "Hello {name} the {race}.", "override": None,
            "default_changed": False, "placeholders": ["name", "race"]})

    def test_override_wins_and_records_its_default(self):
        self.assertEqual(self.save("greeting.txt", "Hey {name}, a {race}."), [])
        self.assertEqual(self.load("greeting.txt"), "Hey {name}, a {race}.")
        self.assertEqual(self.entry("greeting.txt")["override"], "Hey {name}, a {race}.")
        self.assertIs(self.entry("greeting.txt")["default_changed"], False)

    def test_changed_default_marks_override(self):
        self.save("greeting.txt", "Hey {name}, a {race}.")
        self.ship("greeting.txt", "Hello {name}, {race}.")
        self.assertIs(self.entry("greeting.txt")["default_changed"], True)

    def test_hand_made_override_has_unknown_default(self):
        os.makedirs(self.user)
        with open(os.path.join(self.user, "greeting.txt"), "w", encoding="utf-8") as f:
            f.write("By hand {name}.")
        self.assertIsNone(self.entry("greeting.txt")["default_changed"])

    def test_save_equal_to_default_deletes_override(self):
        self.save("greeting.txt", "Hey {name}, a {race}.")
        self.assertEqual(self.save("greeting.txt", "Hello {name} the {race}.\r\n"), [])
        self.assertFalse(os.path.exists(os.path.join(self.user, "greeting.txt")))
        self.assertIsNone(self.entry("greeting.txt")["override"])

    def test_save_after_default_change_clears_the_mark(self):
        self.save("greeting.txt", "Hey {name}, a {race}.")
        self.ship("greeting.txt", "Changed {name} {race}.")
        self.save("greeting.txt", "Hey again {name}, a {race}.")
        self.assertIs(self.entry("greeting.txt")["default_changed"], False)

    def test_empty_save_deletes_override(self):
        self.save("greeting.txt", "Hey {name}, a {race}.")
        self.save("greeting.txt", "  ")
        self.assertEqual(self.load("greeting.txt"), "Hello {name} the {race}.")

    def test_unknown_placeholder_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"\{job\}"):
            self.save("greeting.txt", "Hello {name} the {job}.")
        self.assertFalse(os.path.exists(os.path.join(self.user, "greeting.txt")))

    def test_missing_placeholder_is_a_warning(self):
        warnings = self.save("greeting.txt", "Hello {name}.")
        self.assertEqual(len(warnings), 1)
        self.assertIn("{race}", warnings[0])
        self.assertEqual(self.load("greeting.txt"), "Hello {name}.")

    def test_only_shipped_prompt_names_are_accepted(self):
        for name in ("../greeting.txt", "notes.md", "missing.txt", os.path.join(self.shipped, "greeting.txt")):
            with self.assertRaises(ValueError, msg=name):
                self.save(name, "x")
        self.assertFalse(os.path.exists(self.user))


if __name__ == "__main__":
    unittest.main()
