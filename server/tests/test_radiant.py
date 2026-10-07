import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import radiant

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


class LinesTest(unittest.TestCase):
    def test_the_lines_of_participants_stay(self):
        content = "Stick|10: Hot today.\n\nJorge|14: \"Too hot.\""
        self.assertEqual(radiant.lines(content, {"10": {}, "14": {}}), [("10", "Hot today."), ("14", "Too hot.")])

    def test_one_line_of_no_participant_silences_the_reply(self):
        for stray in ("Narrator: The wind howls.", "Jorge|99: Who am I?", "The end.", "**Jorge|14**: Too hot."):
            self.assertEqual(radiant.lines(f"Stick|10: Hot today.\n{stray}", {"10": {}, "14": {}}), [], stray)

    def test_bracketed_text_goes_and_an_empty_line_with_it(self):
        content = "Stick|10: [ACTION: IDLE] Fine. [JUDGMENT: 2]\nJorge|14: [ACTION: IDLE]"
        self.assertEqual(radiant.lines(content, {"10": {}, "14": {}}), [("10", "Fine.")])


if __name__ == "__main__":
    unittest.main()
