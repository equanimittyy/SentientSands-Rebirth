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
        self.assertEqual(radiant.topic([], {"biome": "Border Zone"}, [], first), "The place where they are.")

    def test_no_material_gives_no_topic(self):
        self.assertIsNone(radiant.topic([], {}, [], first))


class LinesTest(unittest.TestCase):
    def test_only_the_lines_of_participants_stay(self):
        content = "Stick|10: Hot today.\nNarrator: The wind howls.\nJorge|99: Who am I?\nThe end.\nJorge|14: \"Too hot.\""
        self.assertEqual(radiant.lines(content, {"10": {}, "14": {}}), [("10", "Hot today."), ("14", "Too hot.")])

    def test_bracketed_text_goes_and_an_empty_line_with_it(self):
        content = "Stick|10: [ACTION: IDLE] Fine. [JUDGMENT: 2]\nJorge|14: [ACTION: IDLE]"
        self.assertEqual(radiant.lines(content, {"10": {}, "14": {}}), [("10", "Fine.")])


if __name__ == "__main__":
    unittest.main()
