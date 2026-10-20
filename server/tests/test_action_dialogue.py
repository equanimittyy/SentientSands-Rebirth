import json
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server"))

from chat import action_dialogue as ad
from core import state

GUARD = {"squad_jobs": ["MAN_THE_GATE"]}


def score(*args):
    return sum(bonus for bonus, _ in ad.lean(*args))


class ParseTest(unittest.TestCase):
    def test_the_lines_of_the_entry_table(self):
        self.assertEqual(ad.parse("! Hand me over all your money!"), ("classify", None, "Hand me over all your money!"))
        self.assertEqual(ad.parse("!t Hand me over your cats!"), ("category", "THREATEN", "Hand me over your cats!"))
        self.assertEqual(ad.parse("!b I'd like to trade"), ("category", "BARTER", "I'd like to trade"))
        self.assertEqual(ad.parse("!barter"), ("failure", None, ""))
        self.assertEqual(ad.parse("!end Thanks"), ("end", None, "Thanks"))
        self.assertEqual(ad.parse("!o"), ("failure", None, ""))
        self.assertEqual(ad.parse("!I see the light"), ("failure", None, "see the light"))
        self.assertEqual(ad.parse("!light the way"), ("failure", None, "the way"))
        self.assertEqual(ad.parse("!"), ("failure", None, ""))
        for line in ("!!!", "!?!?!"):
            self.assertEqual(ad.parse(line), (None, None, line))

    def test_a_mark_is_case_insensitive(self):
        self.assertEqual(ad.parse("!B hi")[1], "BARTER")
        self.assertEqual(ad.parse("!E"), ("end", None, ""))

    def test_a_word_ends_at_the_first_character_that_is_not_a_letter(self):
        self.assertEqual(ad.parse("!t, now"), ("category", "THREATEN", ", now"))
        self.assertEqual(ad.parse("!1 thing"), (None, None, "!1 thing"))

    def test_a_mark_without_text_is_a_failure(self):
        for line in ("!   ", "!b", "!x"):
            self.assertEqual(ad.parse(line), ("failure", None, ""))

    def test_a_line_without_a_mark_is_plain_chat(self):
        self.assertEqual(ad.parse("Hello there"), (None, None, "Hello there"))


class BlockTest(unittest.TestCase):
    def test_a_knocked_out_speaker_or_npc_blocks_every_line(self):
        self.assertEqual(ad.knockout_block({}, {"character_state": "unconscious"}, "Bandit", "Beep"), "Beep is unconscious.")
        self.assertEqual(ad.knockout_block({"character_state": "unconscious"}, {}, "Bandit", "Beep"), "Bandit is unconscious.")
        self.assertIsNone(ad.knockout_block({}, {}, "Bandit", "Beep"))

    def test_a_marked_line_to_an_animal_or_a_member_of_the_player_faction_is_plain_chat(self):
        self.assertEqual(ad.mark_chat({"animal": True}, False), "You are an animal and make no deals.")
        self.assertIn("{player}'s faction", ad.mark_chat({}, True))
        self.assertIsNone(ad.mark_chat({}, False))

    def test_only_a_dismissal_of_no_hired_follower_is_blocked(self):
        self.assertEqual(ad.gate_block("DISMISS", {}, {}, "Bandit"), "Bandit is not a hired follower.")
        self.assertIsNone(ad.gate_block("DISMISS", {"temporary_follower": True}, {}, "Bandit"))
        for category in ("THREATEN", "BARTER", "HEAL", "LIBERATE", "RECRUIT", "FOLLOW"):
            self.assertIsNone(ad.gate_block(category, {"character_state": "imprisoned"}, {"character_state": "normal"}, "Bandit"))


class PlainChatTest(unittest.TestCase):
    def chat(self, category, npc=None, speaker=None):
        return ad.plain_chat(category, npc or {}, speaker or {})

    def test_barter_never_goes_to_plain_chat(self):
        self.assertIsNone(self.chat("BARTER", {"character_state": "imprisoned"}, {"character_state": "imprisoned", "slave": True}))

    def test_a_threat_from_a_cage_is_not_taken_seriously(self):
        self.assertEqual(self.chat("THREATEN", speaker={"character_state": "imprisoned"}), "{player} is locked in a cage, so you do not take the threat seriously.")
        self.assertIsNone(self.chat("THREATEN", speaker={"character_state": "normal"}))

    def test_heal_needs_wounds_a_kit_and_a_free_npc(self):
        kit = {"has_first_aid": True}
        flesh = {"needs_first_aid": True}
        self.assertEqual(self.chat("HEAL", kit, {"health": "Injured"}), "{player} has no wounds to treat.")
        self.assertEqual(self.chat("HEAL", {}, flesh), "You have no first aid kit.")
        self.assertIsNotNone(self.chat("HEAL", {**kit, "character_state": "imprisoned"}, flesh))
        self.assertIsNone(self.chat("HEAL", kit, flesh))

    def test_heal_needs_a_kit_for_one_of_the_wounds(self):
        repair = {"has_repair_kit": True}
        both = {"needs_first_aid": True, "needs_repair": True}
        self.assertEqual(self.chat("HEAL", {"has_first_aid": True}, {"needs_repair": True}), "You have no repair kit.")
        self.assertEqual(self.chat("HEAL", {}, both), "You have no first aid kit or repair kit.")
        self.assertIsNone(self.chat("HEAL", repair, {"needs_repair": True}))
        self.assertIsNone(self.chat("HEAL", repair, both))
        self.assertEqual(ad.kits({"has_first_aid": True, **repair}, both), ["first aid kit", "repair kit"])

    def test_only_a_free_guard_releases_a_prisoner_who_is_no_slave(self):
        prisoner = {"character_state": "imprisoned"}
        self.assertIsNone(self.chat("LIBERATE", GUARD, prisoner))
        self.assertEqual(self.chat("LIBERATE", GUARD, {"character_state": "normal"}), "{player} is free already.")
        self.assertEqual(self.chat("LIBERATE", {}, prisoner), "You are not a guard, so you cannot release {player}.")
        self.assertIsNotNone(self.chat("LIBERATE", {**GUARD, "character_state": "imprisoned"}, prisoner))
        for slave in ({**prisoner, "slave": True}, {"character_state": "enslaved", "slave": True}):
            self.assertEqual(self.chat("LIBERATE", GUARD, slave), "{player} is a slave, and no one releases a slave.")

    def test_a_jailer_at_a_bounty_desk_is_a_guard(self):
        desk = {"squad_jobs": ["STAND_AT_SHOPKEEPER_NODE", "STAY_IN_HOME", "FIND_CAGE_AND_PUT_DEADGUY_IN"]}
        self.assertTrue(ad.is_guard(desk))
        self.assertFalse(ad.is_guard({"squad_jobs": ["STAND_AT_SHOPKEEPER_NODE"]}))

    def test_recruit_and_follow_need_free_characters_and_no_leader(self):
        self.assertEqual(self.chat("RECRUIT", speaker={"character_state": "enslaved"}), "{player} is enslaved, so you cannot join {player}.")
        self.assertEqual(self.chat("FOLLOW", {"character_state": "imprisoned"}), "You are imprisoned, so you cannot follow {player}.")
        for category in ("RECRUIT", "FOLLOW"):
            self.assertEqual(self.chat(category, {"is_leader": True, "faction": "Holy Nation"}), "You lead Holy Nation and will not leave it.")
            self.assertEqual(self.chat(category, {"squad_jobs": ["SIT_ON_THRONE"], "faction": "Holy Nation"}), "You lead Holy Nation and will not leave it.")
            self.assertIsNone(self.chat(category))

    def test_a_captive_of_the_same_faction_can_join_or_follow(self):
        caged = {"character_state": "imprisoned", "captor": "17-gamedata.base"}
        shackled = {"character_state": "enslaved", "captor": "17-gamedata.base"}
        for category in ("RECRUIT", "FOLLOW"):
            self.assertIsNone(self.chat(category, caged, shackled))
            self.assertEqual(self.chat(category, {**caged, "is_leader": True, "faction": "Slave Traders"}, shackled),
                             "You lead Slave Traders and will not leave it.")
        self.assertEqual(self.chat("RECRUIT", {**caged, "captor": "5-gamedata.base"}, shackled), "{player} is enslaved, so you cannot join {player}.")
        self.assertEqual(self.chat("RECRUIT", {"character_state": "enslaved", "captor": ""}, {"character_state": "enslaved", "captor": ""}),
                         "{player} is enslaved, so you cannot join {player}.")

    def test_a_captive_of_the_speaker_faction_can_join_or_follow(self):
        speaker = {"character_state": "normal", "factionID": "204-gamedata.base"}
        for npc in ({"character_state": "enslaved", "slave": True, "captor": "204-gamedata.base"},
                    {"character_state": "imprisoned", "captor": "204-gamedata.base"}):
            for category in ("RECRUIT", "FOLLOW"):
                self.assertIsNone(self.chat(category, npc, speaker))
        self.assertEqual(self.chat("RECRUIT", {"character_state": "enslaved", "slave": True, "captor": "17-gamedata.base"}, speaker),
                         "You are enslaved, so you cannot join {player}.")
        self.assertEqual(self.chat("RECRUIT", {"character_state": "enslaved", "slave": True, "captor": ""}, {"character_state": "normal", "factionID": ""}),
                         "You are enslaved, so you cannot join {player}.")

    def test_a_fellow_captive_joins_instead_of_following(self):
        shackled = {"character_state": "enslaved", "captor": "17-gamedata.base"}
        self.assertEqual(ad.runs_as("FOLLOW", shackled, shackled), "RECRUIT")
        self.assertEqual(ad.runs_as("FOLLOW", {**shackled, "captor": "5-gamedata.base"}, shackled), "FOLLOW")
        self.assertEqual(ad.runs_as("FOLLOW", {**shackled, "captor": "204-gamedata.base"}, {"factionID": "204-gamedata.base"}), "RECRUIT")
        self.assertEqual(ad.runs_as("FOLLOW", {}, {}), "FOLLOW")
        self.assertEqual(ad.runs_as("BARTER", shackled, shackled), "BARTER")
        self.assertIsNone(ad.runs_as(None, shackled, shackled))


class ClassifyTest(unittest.TestCase):
    def test_the_list_leaves_out_only_a_blocked_category(self):
        self.assertEqual(ad.choices({}, {"character_state": "normal", "health": "Healthy"}, "Bandit"), ["THREATEN", "BARTER", "HEAL", "LIBERATE", "RECRUIT", "FOLLOW"])

    def test_the_list_is_numbered_and_ends_in_the_escape_hatch(self):
        self.assertEqual(ad.choice_list(["THREATEN", "BARTER", "HEAL"]), "1. A threat or demand\n2. A request to buy, sell, or swap items, a gift, or a plea for charity\n"
                         "3. A request to treat wounds or repair robotic parts, paid or free\n4. None of these")

    def test_the_number_maps_back_to_its_category(self):
        listed = ["THREATEN", "BARTER", "HEAL"]
        self.assertEqual(ad.chosen("2", listed), "BARTER")
        self.assertEqual(ad.chosen(" 1.", listed), "THREATEN")
        self.assertEqual(ad.chosen("3", listed), "HEAL")

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
        self.assertEqual(score("HEAL", {}, {"health": "Crippled"}, 25), 3)
        self.assertEqual(score("LIBERATE", {}, {"health": "Crippled"}, 0), 1)

    def test_a_charity_counts_for_its_game_day_but_not_in_the_lean_of_a_trade(self):
        npc = {"npc_id": "h:1-beggar", "day": 4}
        self.assertFalse(ad.gave_charity_today(npc))
        state.CHARITY_DAYS[npc["npc_id"]] = 4
        self.addCleanup(state.CHARITY_DAYS.clear)
        self.assertTrue(ad.gave_charity_today(npc))
        self.assertFalse(ad.gave_charity_today({**npc, "day": 5}))
        self.assertEqual(ad.lean("BARTER", npc, {}, 0), [])

    def test_a_guard_a_trader_or_a_unique_npc_joins_less_readily(self):
        self.assertEqual(score("RECRUIT", {"unique": True, **GUARD}, {}, 0), -3)
        self.assertEqual(score("FOLLOW", {"is_trader": True}, {}, 0), -3)
        self.assertEqual(score("RECRUIT", {"character_state": "escaped-slave"}, {}, 0), 1)

    def test_a_fellow_captive_joins_more_readily(self):
        shackled = {"character_state": "enslaved", "captor": "17-gamedata.base"}
        self.assertEqual(ad.lean("RECRUIT", shackled, shackled, 0, (), "whisper"), [(2, "{player} is a fellow captive, and like most captives, you want to escape.")])
        self.assertEqual(score("RECRUIT", {**shackled, "captor": "5-gamedata.base"}, shackled, 0), 0)

    def test_a_captive_of_the_speaker_faction_leans_by_fight_and_days_held(self):
        captor = {"factionID": "204-gamedata.base"}
        caged = {"character_state": "imprisoned", "captor": "204-gamedata.base"}
        self.assertEqual(ad.lean("RECRUIT", caged, captor, 0, days_held=0), [(1, "{player}'s faction holds you captive, and joining the squad sets you free."),
                                                                            (-2, "{player}'s faction took you captive today, and your anger is fresh.")])
        self.assertEqual(ad.lean_text(score("RECRUIT", caged, captor, -60, (), "talk", 0)), ad.REFUSED_LEAN)
        weak = {**caged, "stats": {"melee_attack": 10, "melee_defence": 10}}
        strong = {**captor, "stats": {"melee_attack": 40, "melee_defence": 20}}
        self.assertEqual(score("RECRUIT", weak, strong, -60, (), "talk", 14), 3)
        self.assertEqual(score("RECRUIT", caged, captor, 0), 1)
        self.assertEqual(score("RECRUIT", caged, {"factionID": "17-gamedata.base"}, 0, (), "talk", 14), 0)

    def test_the_fight_bonus_takes_the_strength_step_of_the_chat_prompt(self):
        speaker = {"stats": {"melee_attack": 50, "melee_defence": 10}}
        gaps = (30, 29, 10, 9, -10, -11, -30, -31)
        self.assertEqual([ad.fight_bonus({"stats": {"melee_defence": 50 - gap}}, speaker) for gap in gaps], [2, 1, 1, 0, 0, -1, -1, -2])
        self.assertEqual(ad.fight_bonus({}, speaker), 0)

    def test_the_days_held_steps_of_a_captive(self):
        self.assertEqual([ad.captivity_pair(days)[0] for days in (0, 1, 2, 3, 4, 5, 8, 9, 13, 14, 40)], [-2, -2, -2, -1, -1, 0, 0, 1, 1, 2, 2])
        self.assertEqual(ad.captivity_pair(1)[1], "{player}'s faction took you captive 1 day ago, and your anger is fresh.")
        self.assertEqual(ad.captivity_pair(2)[1], "{player}'s faction took you captive 2 days ago, and your anger is fresh.")
        self.assertEqual(ad.captivity_pair(3)[1], "{player}'s faction took you captive only 3 days ago, and you still defy your captors.")

    def test_a_fellow_captive_that_hears_no_whisper_fears_the_captors(self):
        shackled = {"character_state": "enslaved", "captor": "17-gamedata.base"}
        for mode in ("talk", "yell"):
            self.assertIn((-6, "{player} says it out loud, where your captors can hear, so you refuse and deny any plan to escape."),
                          ad.lean("RECRUIT", shackled, shackled, 0, (), mode))
            self.assertEqual(score("RECRUIT", shackled, shackled, 0, (), mode), -4)
            self.assertEqual(ad.lean_text(score("RECRUIT", shackled, shackled, 100, (), mode)), ad.REFUSED_LEAN)
        self.assertEqual(score("RECRUIT", {}, {}, 0, (), "talk"), 0)

    def test_a_npc_that_is_no_mercenary_is_wary_of_following(self):
        self.assertEqual(score("FOLLOW", {}, {}, 0), -1)
        self.assertEqual(score("FOLLOW", {"faction": "Tech Hunters"}, {}, 0), 0)
        self.assertEqual(ad.thought(ad.lean("FOLLOW", {}, {}, 0), "Zaps"), "You could go either way.\n- Reasons to refuse: You have no reason to follow Zaps.")

    def test_a_threat_counts_strength_and_numbers(self):
        strong = {"stats": {"melee_attack": 40, "melee_defence": 40}, "faction": "Nameless", "name": "Zaps", "squad": ["Zaps", "Zip"]}
        npc = {"stats": {"melee_attack": 10, "melee_defence": 10}, "faction": "Dust Bandits", "health": "Injured",
               "nearby": [{"name": "Zip", "faction": "Nameless"}, {"name": "Bandit", "faction": "Dust Bandits"}]}
        self.assertEqual(score("THREATEN", npc, strong, 0), 4)
        self.assertEqual(score("THREATEN", {**npc, "stats": {"melee_attack": 25}}, strong, 0), 3)
        self.assertEqual(score("THREATEN", {**npc, "stats": {"melee_attack": 35}}, strong, 0), 2)
        self.assertEqual(score("THREATEN", {**npc, "is_leader": True}, strong, 0), 3)

    def test_the_thought_gives_the_band_and_its_reasons(self):
        lean = ad.lean("RECRUIT", {"character_state": "escaped-slave", **GUARD}, {}, -30)
        self.assertEqual(ad.thought(lean, "Zaps"), "You are inclined to refuse.\n- Reasons to agree: You escaped slavery.\n"
                         "- Reasons to refuse: You dislike Zaps's group. You are a guard.")
        self.assertEqual(ad.thought([], "Zaps"), "You could go either way.")


class ReplyTest(unittest.TestCase):
    def test_the_ending_tag_ends_the_action_dialogue(self):
        self.assertTrue(ad.ended("[BARTER] Get lost. [END] [JUDGMENT: -1]"))
        self.assertTrue(ad.ended("Fine. [ end ]"))
        self.assertFalse(ad.ended("[BARTER] Fine. [JUDGMENT: 0]"))

    def test_each_end_has_ten_preset_lines(self):
        with open(ad.END_LINES_PATH, encoding="utf-8") as f:
            lines = json.load(f)
        ends = ("end", "barter_accept", "threaten_accept", "threaten_attack", "heal_start", "liberate_accept", "recruit_accept", "recruit_captive_accept", "follow_accept",
                "dismiss_end")
        self.assertEqual({end: len(texts) for end, texts in lines.items()}, {end: 10 for end in ends})
        self.assertIn(ad.end_line("end"), lines["end"])


if __name__ == "__main__":
    unittest.main()
