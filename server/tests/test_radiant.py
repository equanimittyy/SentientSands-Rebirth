import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import radiant, reply_text

MEMORY = {"game_time": None, "memory": "Stick asked Jorge for work.", "members": [("h:10", "Stick", "speaker", True), ("h:14", "Jorge", "speaker", True)]}


def first(items):
    return items[0]


def last(items):
    return items[-1]


class TopicTest(unittest.TestCase):
    def test_each_kind_with_material_can_be_the_topic(self):
        place = {"town_name": "Squin"}
        self.assertEqual(radiant.topic([MEMORY], place, ["Beep freed the slaves."], first), "A conversation that some of them remember. (Memory of a conversation between Stick and Jorge) Stick asked Jorge for work.")
        self.assertEqual(radiant.topic([MEMORY], place, ["Beep freed the slaves."], last), "A rumour that they heard: Beep freed the slaves.")
        self.assertEqual(radiant.topic([], {"zone_name": "Border Zone"}, [], first), "The place where they are.")

    def test_the_place_holds_the_lore_of_the_town(self):
        location = {"name": "Squin", "aliases": [], "fields": {"type": "town"}, "description": "Squin is a town."}
        self.assertEqual(radiant.topic([], {"town_name": "Squin"}, [], first, location=location), "The place where they are. Its lore follows. They may know only a part of it, and they never recite it.\nSquin (location; type: town): Squin is a town.")

    def test_no_material_gives_no_topic(self):
        self.assertIsNone(radiant.topic([], {}, [], first))


def drinker(serial, squad, jobs=("RELAX_IN_TOWN_PACKAGE",)):
    return {"id": serial, "npc_id": f"h:{serial}", "squad": squad, "squad_jobs": list(jobs)}


def ids(group):
    return [npc["id"] for npc in group]


class Roll:
    def __init__(self, count):
        self.count, self.ranges = count, []

    def randint(self, low, high):
        self.ranges.append((low, high))
        return self.count


class NpcGroupTest(unittest.TestCase):
    def test_only_the_npcs_at_a_bar_count(self):
        guards = [drinker(1, "a", ("STAND_AT_GUARD_NODE_HOMEBUILDING_IN_OUT", "GO_TO_THE_BAR_AND_DRINK")), drinker(2, "a")]
        hired = [{**drinker(3, "b"), "temporary_follower": True}, drinker(4, "b")]
        self.assertEqual(radiant.npc_group(guards + hired, lambda npc_id: True, Roll(5)), [])

    def test_the_npcs_come_from_one_squad(self):
        npcs = [drinker(1, "a"), drinker(2, "b"), drinker(3, "b"), drinker(4, "a")]
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: True, Roll(5))), [1, 4])
        self.assertEqual(radiant.npc_group([drinker(1, "a"), drinker(2, "b")], lambda npc_id: True, Roll(5)), [])

    def test_the_count_is_rolled_from_2_to_5(self):
        npcs = [drinker(serial, "a") for serial in range(1, 8)]
        roll = Roll(3)
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: True, roll)), [1, 2, 3])
        self.assertEqual(roll.ranges, [(2, 5)])
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: True, Roll(5))), [1, 2, 3, 4, 5])

    def test_npcs_with_a_profile_talk_first_and_new_npcs_fill_the_roll(self):
        npcs = [drinker(1, "a"), drinker(2, "a"), drinker(3, "a"), drinker(4, "a")]
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: npc_id == "h:3", Roll(3))), [3, 1, 2])
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: False, Roll(4))), [1, 2, 3, 4])

    def test_the_nearest_squad_with_a_profile_wins_else_the_nearest(self):
        npcs = [drinker(1, "a"), drinker(2, "a"), drinker(3, "b"), drinker(4, "b"), drinker(5, "c"), drinker(6, "c")]
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: npc_id in ("h:5", "h:6"), Roll(2))), [5, 6])
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: npc_id in ("h:4", "h:6"), Roll(2))), [4, 3])
        self.assertEqual(ids(radiant.npc_group(npcs, lambda npc_id: False, Roll(2))), [1, 2])


class NpcTalkTest(unittest.TestCase):
    NPCS = [{"id": 30, "npc_id": "h:30"}, {"id": 31, "npc_id": "h:31"}]

    def test_the_npcs_talk_when_the_roll_is_under_the_chance(self):
        self.assertTrue(radiant.npc_talk(self.NPCS, ["Beep freed the slaves."], 50, lambda: 0.49))
        self.assertFalse(radiant.npc_talk(self.NPCS, ["Beep freed the slaves."], 50, lambda: 0.5))

    def test_a_chance_of_0_never_lets_the_npcs_talk_and_100_always_does(self):
        self.assertFalse(radiant.npc_talk(self.NPCS, ["Beep freed the slaves."], 0, lambda: 0.0))
        self.assertTrue(radiant.npc_talk(self.NPCS, ["Beep freed the slaves."], 100, lambda: 0.999))

    def test_the_npcs_need_a_rumour_and_each_other(self):
        self.assertFalse(radiant.npc_talk(self.NPCS, [], 100, lambda: 0.0))
        self.assertFalse(radiant.npc_talk([], ["Beep freed the slaves."], 100, lambda: 0.0))
        self.assertFalse(radiant.npc_talk(None, ["Beep freed the slaves."], 100, lambda: 0.0))


class TurnsTest(unittest.TestCase):
    def test_each_line_speaks_to_the_last_speaker_and_nobody_speaks_twice_in_a_row(self):
        for seed in range(200):
            order = radiant.turns(["10", "14", "20", "31"], 12, random.Random(seed))
            self.assertIsNone(order[0][1])
            for (before, _), (speaker, addressee) in zip(order, order[1:]):
                self.assertEqual(addressee, before)
                self.assertNotEqual(speaker, before)

    def test_the_one_addressed_answers_or_a_third_character_cuts_in(self):
        orders = [radiant.turns(["10", "14", "20", "31"], 12, random.Random(seed)) for seed in range(200)]
        answers = [order[index][0] == order[index - 1][1] for order in orders for index in range(2, len(order))]
        self.assertTrue(0.4 < sum(answers) / len(answers) < 0.6)

    def test_two_characters_take_turns(self):
        order = radiant.turns(["10", "14"], 5, random.Random(1))
        self.assertEqual([speaker for speaker, _ in order][1:], [order[1][0], order[0][0]] * 2)

    def test_the_length_counts_the_lines_of_the_plan(self):
        for seed in range(20):
            length, order = radiant.plan(["10", "14"], random.Random(seed))
            self.assertEqual(int(length.split()[0]), len(order))
            self.assertTrue(2 <= len(order) <= 12)


NAMES = {"10": "Stick", "14": "Jorge"}


class TurnTest(unittest.TestCase):
    ORDER = [("10", None), ("14", "10"), ("10", "14")]

    def test_the_first_line_opens_the_talk_and_speaks_to_everyone(self):
        self.assertEqual(radiant.turn(0, self.ORDER, NAMES), "Line 1 of 3, which opens the talk. Stick|10 speaks to everyone.")

    def test_a_middle_line_names_its_speaker_by_its_label_and_its_addressee_by_its_name(self):
        self.assertEqual(radiant.turn(1, self.ORDER, NAMES), "Line 2 of 3. Jorge|14 speaks to Stick.")

    def test_the_last_line_closes_the_talk(self):
        self.assertEqual(radiant.turn(2, self.ORDER, NAMES), "Line 3 of 3, the last, which closes the talk. Stick|10 speaks to Jorge.")


class TalkTest(unittest.TestCase):
    def test_the_talk_so_far_grows_only_at_its_end(self):
        before = radiant.talk([("10", "Hot today.")], NAMES)
        after = radiant.talk([("10", "Hot today."), ("14", "Too hot.")], NAMES)
        self.assertEqual(after, "Stick|10: Hot today.\nJorge|14: Too hot.")
        self.assertTrue(after.startswith(before))

    def test_a_talk_without_lines_says_so(self):
        self.assertEqual(radiant.talk([], NAMES), "Nobody has spoken yet.")


class AcquaintanceTest(unittest.TestCase):
    def test_each_pair_gets_the_count_of_its_earlier_talks(self):
        names = {"h:10": "Stick", "h:14": "Jorge", "h:20": "Ruka"}
        partners = {"h:10": ["h:14", "h:20", "h:14"], "h:14": ["h:10", "h:10"], "h:20": ["h:10"]}
        self.assertEqual(radiant.acquaintance(names, partners), "- Stick and Jorge have talked a little.\n- Stick and Ruka have talked a little.\n- Jorge and Ruka have never talked.")

    def test_more_talks_give_a_closer_bond(self):
        names = {"h:10": "Stick", "h:14": "Jorge", "h:20": "Ruka"}
        partners = {"h:10": ["h:14"] * 3 + ["h:20"] * 10, "h:14": [], "h:20": []}
        self.assertEqual(radiant.acquaintance(names, partners), "- Stick and Jorge know each other.\n- Stick and Ruka know each other well.\n- Jorge and Ruka have never talked.")


class VoicesTest(unittest.TestCase):
    NAMES = {"10": "Stick", "14": "Jorge", "20": "Stick"}

    def test_the_speaker_owns_its_name_and_its_label(self):
        own, _ = radiant.voices(self.NAMES, "14")
        self.assertEqual(own, {"jorge", "jorge|14"})

    def test_the_others_are_named_by_their_names_and_labels_but_never_by_the_own_name(self):
        _, others = radiant.voices(self.NAMES, "10")
        self.assertEqual(others, {"jorge", "jorge|14", "stick|20"})

    def test_the_reply_keeps_only_the_words_of_the_speaker(self):
        reply = "**Jorge|14**: Too hot.\nStick|10: Then drink.\nJorge|14: I will."
        self.assertEqual(reply_text.spoken(reply, *radiant.voices(self.NAMES, "14")), "Too hot.")


if __name__ == "__main__":
    unittest.main()
