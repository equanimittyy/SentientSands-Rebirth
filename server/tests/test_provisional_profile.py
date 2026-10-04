import glob
import json
import os
import re
import sys
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import provisional_profile

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "world_templates", "kenshi_ssr_vanilla")
TRAITS = {trait["id"]: trait for trait in provisional_profile.TRAITS}
TIER_TEXTS = {tier["text"]: (index, trait) for trait in provisional_profile.TRAITS for index, tier in enumerate(trait["tiers"])}
BACKSTORY_TEXTS = [story["text"] for story in provisional_profile.BACKSTORIES]
QUIRKS = provisional_profile.SPEECH_QUIRKS
ALL_TEXTS = [*TIER_TEXTS, *provisional_profile.ANIMAL_PERSONALITIES, *BACKSTORY_TEXTS, *(quirk for quirks in QUIRKS.values() for quirk in quirks)]


def template_names():
    names = set()
    for category in ("factions", "races", "locations", "regions"):
        for path in glob.glob(os.path.join(TEMPLATE, category, "*.json")):
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            names.update([record["name"], *record.get("aliases", [])])
    return names


def rolled_traits(personality):
    """(tier, trait) of each tier text in the personality, in the order of the text."""
    found = sorted((personality.index(text), tier, trait) for text, (tier, trait) in TIER_TEXTS.items() if text in personality)
    return [(tier, trait) for _, tier, trait in found]


class DataTest(unittest.TestCase):
    def test_the_lists_have_their_sizes_and_no_text_repeats(self):
        self.assertEqual(len(provisional_profile.ANIMAL_PERSONALITIES), 20)
        self.assertEqual(len(provisional_profile.BACKSTORIES), 100)
        self.assertEqual({group: len(quirks) for group, quirks in QUIRKS.items()}, {"universal": 50, "human": 25, "shek": 25, "hiver": 25, "skeleton": 25})
        self.assertEqual(len(ALL_TEXTS), len(set(ALL_TEXTS)))

    def test_each_trait_has_three_tiers_and_opposites_that_name_it_back(self):
        self.assertEqual(len(TRAITS), 36)
        for trait in TRAITS.values():
            self.assertEqual(len(trait["tiers"]), 3, trait["id"])
            self.assertTrue(all(tier["name"] and tier["text"] for tier in trait["tiers"]), trait["id"])
            for other in trait["opposites"]:
                self.assertIn(trait["id"], TRAITS[other]["opposites"], trait["id"])

    def test_a_skeleton_neither_eats_nor_lusts(self):
        skeleton = {trait_id for trait_id, trait in TRAITS.items() if "skeleton" in trait["kinds"]}
        self.assertEqual(set(TRAITS) - skeleton, {"lustful", "chaste", "gluttonous", "temperate"})
        self.assertTrue(all(set(trait["kinds"]) <= {"person", "skeleton"} for trait in TRAITS.values()))

    def test_each_backstory_fits_a_person_or_a_skeleton(self):
        self.assertTrue(all(story["kinds"] and set(story["kinds"]) <= {"person", "skeleton"} for story in provisional_profile.BACKSTORIES))

    def test_each_backstory_ends_in_the_past(self):
        present = re.compile(r"\b(?:now|still|anymore|lately|these days|they (?:are|have|do|want|mean|hope|keep|carry|work|live|feel|fear|hate|refuse|know|wonder|intend|owe))\b", re.IGNORECASE)
        self.assertFalse([text for text in BACKSTORY_TEXTS if present.search(text)])

    def test_no_text_names_a_template_entry_or_has_a_gendered_pronoun_or_a_stage_direction(self):
        names = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in sorted(template_names(), key=len, reverse=True)) + r")\b")
        for text in ALL_TEXTS:
            self.assertIsNone(names.search(text), text)
            self.assertNotRegex(text, re.compile(r"\b(?:he|she|him|her|his|hers|himself|herself)\b", re.IGNORECASE))
            self.assertNotRegex(text, r'[*()"]')

    def test_no_text_looks_like_a_stand_in(self):
        # should_save_profile does not store a personality that contains "unknown"
        self.assertFalse([text for text in ALL_TEXTS if "unknown" in text.lower()])


class RollTest(unittest.TestCase):
    def test_a_person_rolls_three_traits_with_no_opposites_the_highest_tier_first(self):
        for n in range(300):
            traits = rolled_traits(provisional_profile.roll(f"h:{n}", "person", "Greenlander")["Personality"])
            self.assertEqual(len(traits), 3)
            ids = [trait["id"] for _, trait in traits]
            self.assertEqual(len(set(ids)), 3)
            self.assertFalse([trait_id for _, trait in traits for trait_id in trait["opposites"] if trait_id in ids])
            self.assertEqual([tier for tier, _ in traits], sorted((tier for tier, _ in traits), reverse=True))

    def test_a_skeleton_rolls_only_skeleton_traits(self):
        for n in range(300):
            traits = rolled_traits(provisional_profile.roll(f"h:{n}", "skeleton", "Skeleton")["Personality"])
            self.assertTrue(all("skeleton" in trait["kinds"] for _, trait in traits))

    def test_a_person_gets_a_backstory_and_a_speech_quirk(self):
        profile = provisional_profile.roll("h:1", "person", "Greenlander")
        self.assertIn(profile["Backstory"], BACKSTORY_TEXTS)
        self.assertIn(profile["SpeechQuirks"], QUIRKS["universal"] + QUIRKS["human"])

    def test_a_race_rolls_the_universal_quirks_and_its_own(self):
        races = {"Greenlander": ("person", "human"), "Scorchlander": ("person", "human"), "Shek": ("person", "shek"),
                 "Hive Soldier Drone": ("person", "hiver"), "Northern Hive Prince": ("person", "hiver"), "Skeleton": ("skeleton", "skeleton"),
                 "Soldierbot": ("skeleton", "skeleton")}
        for race, (kind, group) in races.items():
            rolled = {provisional_profile.roll(f"h:{n}", kind, race)["SpeechQuirks"] for n in range(300)}
            self.assertLessEqual(rolled, set(QUIRKS["universal"] + QUIRKS[group]), race)
            self.assertTrue(rolled & set(QUIRKS[group]), race)

    def test_a_race_with_no_list_rolls_only_universal_quirks(self):
        rolled = {provisional_profile.roll(f"h:{n}", "person", "Fishman")["SpeechQuirks"] for n in range(300)}
        self.assertLessEqual(rolled, set(QUIRKS["universal"]))

    def test_a_person_and_a_skeleton_roll_only_backstories_of_their_kind(self):
        for kind in ("person", "skeleton"):
            stories = {story["text"] for story in provisional_profile.BACKSTORIES if kind in story["kinds"]}
            for n in range(300):
                self.assertIn(provisional_profile.roll(f"h:{n}", kind, kind.title())["Backstory"], stories, kind)

    def test_an_animal_gets_one_personality_and_nothing_else(self):
        profile = provisional_profile.roll("h:1", "animal", "Bonedog")
        self.assertIn(profile["Personality"], provisional_profile.ANIMAL_PERSONALITIES)
        self.assertEqual((profile["Backstory"], profile["SpeechQuirks"]), ("", ""))

    def test_one_npc_id_always_rolls_one_profile(self):
        self.assertEqual(provisional_profile.roll("h:42", "person", "Shek"), provisional_profile.roll("h:42", "person", "Shek"))
        self.assertGreater(len({provisional_profile.roll(f"h:{n}", "person", "Shek")["Personality"] for n in range(50)}), 45)

    def test_the_tiers_follow_their_weights(self):
        tiers = Counter(tier for n in range(2000) for tier, _ in rolled_traits(provisional_profile.roll(f"h:{n}", "person", "Shek")["Personality"]))
        shares = [tiers[tier] / sum(tiers.values()) for tier in range(3)]
        for share, weight in zip(shares, provisional_profile.TIER_WEIGHTS):
            self.assertAlmostEqual(share, weight / 100, delta=0.03)


if __name__ == "__main__":
    unittest.main()
