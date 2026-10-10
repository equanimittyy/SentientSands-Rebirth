import json
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server"))

from chat import action_dialogue as ad

GUARD = {"squad_jobs": ["MAN_THE_GATE"]}


class ParseTest(unittest.TestCase):
    def test_the_lines_of_the_entry_table(self):
        self.assertEqual(ad.parse("! Hand me over all your money!"), ("classify", None, "Hand me over all your money!"))
        self.assertEqual(ad.parse("!t Hand me over your cats!"), ("category", "THREATEN", "Hand me over your cats!"))
        self.assertEqual(ad.parse("!b I'd like to trade"), ("category", "BARTER", "I'd like to trade"))
        self.assertEqual(ad.parse("!barter"), ("category", "BARTER", ""))
        self.assertEqual(ad.parse("!end Thanks"), ("end", None, "Thanks"))
        self.assertEqual(ad.parse("!o"), ("failure", None, ""))
        self.assertEqual(ad.parse("!I see the light"), ("failure", None, "see the light"))
        self.assertEqual(ad.parse("!light the way"), ("failure", None, "the way"))
        for line in ("!!!", "!?!?!", "!"):
            self.assertEqual(ad.parse(line), (None, None, line))

    def test_a_mark_is_case_insensitive(self):
        self.assertEqual(ad.parse("!B hi")[1], "BARTER")
        self.assertEqual(ad.parse("!E"), ("end", None, ""))

    def test_a_word_ends_at_the_first_character_that_is_not_a_letter(self):
        self.assertEqual(ad.parse("!t, now"), ("category", "THREATEN", ", now"))
        self.assertEqual(ad.parse("!1 thing"), (None, None, "!1 thing"))

    def test_a_space_with_nothing_after_it_is_plain_chat(self):
        self.assertEqual(ad.parse("!   "), (None, None, "!"))

    def test_a_line_without_a_mark_is_plain_chat(self):
        self.assertEqual(ad.parse("Hello there"), (None, None, "Hello there"))


class BlockTest(unittest.TestCase):
    def test_a_knocked_out_speaker_or_npc_blocks_every_line(self):
        self.assertEqual(ad.knockout_block({}, {"character_state": "unconscious"}, "Bandit", "Beep"), "Beep is unconscious.")
        self.assertEqual(ad.knockout_block({"character_state": "unconscious"}, {}, "Bandit", "Beep"), "Bandit is unconscious.")
        self.assertIsNone(ad.knockout_block({}, {}, "Bandit", "Beep"))

    def test_an_animal_or_a_member_of_the_player_faction_blocks_a_marked_line(self):
        self.assertIn("animal", ad.mark_block({"animal": True}, "Goat", False))
        self.assertEqual(ad.mark_block({}, "Hobbs", True), "Hobbs is a member of your faction.")
        self.assertIsNone(ad.mark_block({}, "Bandit", False))


class GateTest(unittest.TestCase):
    def gate(self, category, npc=None, speaker=None):
        return ad.gate_block(category, npc or {}, speaker or {}, "Bandit")

    def test_threaten_needs_a_free_speaker(self):
        self.assertEqual(self.gate("THREATEN", speaker={"character_state": "imprisoned"}), "You can't threaten anyone while imprisoned.")
        self.assertIsNone(self.gate("THREATEN", speaker={"character_state": "enslaved"}))

    def test_barter_has_no_gate(self):
        self.assertIsNone(self.gate("BARTER", {"character_state": "imprisoned"}, {"character_state": "imprisoned"}))

    def test_heal_needs_wounds_a_kit_and_a_free_npc(self):
        kit = {"has_first_aid": True}
        self.assertIsNotNone(self.gate("HEAL", kit, {"health": "Healthy"}))
        self.assertIsNotNone(self.gate("HEAL", {}, {"health": "Injured"}))
        self.assertIsNotNone(self.gate("HEAL", {**kit, "character_state": "imprisoned"}, {"health": "Crippled"}))
        self.assertIsNone(self.gate("HEAL", kit, {"health": "Injured"}))

    def test_a_slight_wound_counts_for_heal(self):
        kit = {"has_first_aid": True}
        slight = {"health": "Healthy", "medical": {"limbs": {"head": 100, "head_max": 100, "left_arm": 90, "left_arm_max": 100}}}
        whole = {"health": "Healthy", "medical": {"limbs": {"head": 100, "head_max": 100, "left_arm": 100, "left_arm_max": 100}}}
        self.assertIsNone(self.gate("HEAL", kit, slight))
        self.assertEqual(self.gate("HEAL", kit, whole), "You have no wounds to treat.")

    def test_liberate_needs_a_captive_speaker_and_a_free_npc(self):
        self.assertIsNotNone(self.gate("LIBERATE", speaker={"character_state": "normal"}))
        self.assertIsNotNone(self.gate("LIBERATE", {"character_state": "imprisoned"}, {"character_state": "imprisoned"}))
        self.assertIsNone(self.gate("LIBERATE", speaker={"character_state": "enslaved"}))

    def test_a_guard_never_frees_a_slave_even_in_a_cage(self):
        caged_slave = {"character_state": "imprisoned", "slave": True}
        self.assertIn("guard", self.gate("LIBERATE", GUARD, caged_slave))
        self.assertIsNone(self.gate("LIBERATE", GUARD, {"character_state": "imprisoned"}))

    def test_recruit_and_follow_need_free_characters_and_no_leader(self):
        for category in ("RECRUIT", "FOLLOW"):
            self.assertIsNotNone(self.gate(category, speaker={"character_state": "enslaved"}))
            self.assertIsNotNone(self.gate(category, {"character_state": "imprisoned"}))
            self.assertIsNotNone(self.gate(category, {"is_leader": True, "faction": "Holy Nation"}))
            self.assertIsNone(self.gate(category))

    def test_dismiss_needs_a_temporary_follower(self):
        self.assertEqual(self.gate("DISMISS"), "Bandit is not a hired follower.")
        self.assertIsNone(self.gate("DISMISS", {"temporary_follower": True}))


class ClassifyTest(unittest.TestCase):
    def test_the_list_leaves_out_each_category_that_the_game_state_rules_out(self):
        self.assertEqual(ad.choices({}, {"character_state": "normal", "health": "Healthy"}, "Bandit"), ["THREATEN", "BARTER", "RECRUIT", "FOLLOW"])

    def test_the_list_is_numbered_and_ends_in_the_escape_hatch(self):
        self.assertEqual(ad.choice_list(["THREATEN", "BARTER"]), "1. A threat or demand\n2. A request to trade items, a gift, or a plea for charity\n3. None of these")

    def test_the_number_maps_back_to_its_category(self):
        listed = ["THREATEN", "BARTER"]
        self.assertEqual(ad.chosen("2", listed), "BARTER")
        self.assertEqual(ad.chosen(" 1.", listed), "THREATEN")

    def test_the_escape_hatch_and_other_output_choose_nothing(self):
        listed = ["THREATEN", "BARTER"]
        for output in ("3", "0", "9", "Barter", "", None):
            self.assertIsNone(ad.chosen(output, listed))


class LeanTest(unittest.TestCase):
    def test_the_relation_scale(self):
        self.assertEqual([ad.relation_bonus(r) for r in (60, 25, 24, -24, -25, -60, None)], [2, 1, 0, 0, -1, -2, 0])

    def test_the_bands(self):
        self.assertEqual(ad.lean_text(2), "You are inclined to agree.")
        self.assertEqual(ad.lean_text(1), "You could go either way.")
        self.assertEqual(ad.lean_text(-1), "You could go either way.")
        self.assertEqual(ad.lean_text(-2), "You are inclined to refuse.")

    def test_a_worse_wound_raises_the_heal_lean(self):
        self.assertEqual(ad.lean("HEAL", {}, {"health": "Crippled"}, 25), 3)
        self.assertEqual(ad.lean("LIBERATE", {}, {"health": "Crippled"}, 0), 1)

    def test_a_guard_or_a_unique_npc_joins_less_readily(self):
        self.assertEqual(ad.lean("RECRUIT", {"unique": True, **GUARD}, {}, 0), -2)
        self.assertEqual(ad.lean("RECRUIT", {"character_state": "escaped-slave"}, {}, 0), 1)

    def test_a_npc_that_is_no_mercenary_is_wary_of_following(self):
        self.assertEqual(ad.lean("FOLLOW", {}, {}, 0), -1)
        self.assertEqual(ad.lean("FOLLOW", {"faction": "Tech Hunters"}, {}, 0), 0)

    def test_a_threat_counts_strength_and_numbers(self):
        strong = {"stats": {"melee_attack": 40, "melee_defence": 40}, "faction": "Nameless", "name": "Zaps", "squad": ["Zaps", "Zip"]}
        npc = {"stats": {"melee_attack": 10, "melee_defence": 10}, "faction": "Dust Bandits", "health": "Injured",
               "nearby": [{"name": "Zip", "faction": "Nameless"}, {"name": "Bandit", "faction": "Dust Bandits"}]}
        self.assertEqual(ad.lean("THREATEN", npc, strong, 0), 3)
        self.assertEqual(ad.lean("THREATEN", {**npc, "is_leader": True}, strong, 0), 2)


class ReplyTest(unittest.TestCase):
    def test_the_ending_tag_ends_the_action_dialogue(self):
        self.assertTrue(ad.ended("[BARTER] Get lost. [END] [JUDGMENT: -1]"))
        self.assertTrue(ad.ended("Fine. [ end ]"))
        self.assertFalse(ad.ended("[BARTER] Fine. [JUDGMENT: 0]"))

    def test_each_end_has_ten_preset_lines(self):
        with open(ad.END_LINES_PATH, encoding="utf-8") as f:
            lines = json.load(f)
        ends = ("end", "barter_accept", "threaten_accept", "threaten_attack", "heal_start", "liberate_accept", "recruit_accept", "follow_accept", "dismiss_end")
        self.assertEqual({end: len(texts) for end, texts in lines.items()}, {end: 10 for end in ends})
        self.assertIn(ad.end_line("end"), lines["end"])


if __name__ == "__main__":
    unittest.main()
