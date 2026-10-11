import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import reply_text

OWN = {"beep"}
OTHERS = {"drifter", "ruka"}


def spoken(content):
    return reply_text.spoken(content, OWN, OTHERS)


class SpokenTest(unittest.TestCase):
    def test_the_lines_become_one_line(self):
        self.assertEqual(spoken("Beep is happy!\n\nBeep likes you."), "Beep is happy! Beep likes you.")

    def test_tags_and_quotes_go_also_a_tag_that_holds_an_item_name_with_brackets(self):
        self.assertEqual(spoken('"Here." [ACTION: TAKE_ITEM: Bolts [Toothpicks]] [JUDGMENT: 2]'), "Here.")

    def test_a_line_of_another_speaker_ends_the_reply(self):
        self.assertEqual(spoken("Beep agrees.\nRuka: I do not.\nBeep: Then Beep goes alone."), "Beep agrees.")

    def test_the_own_label_goes_also_in_bold(self):
        self.assertEqual(spoken("Beep: Beep agrees."), "Beep agrees.")
        self.assertEqual(spoken("**Beep**: Beep agrees."), "Beep agrees.")

    def test_a_label_of_no_known_name_stays(self):
        self.assertEqual(spoken("Listen: Beep knows a secret."), "Listen: Beep knows a secret.")

    def test_meta_lines_and_dividers_go(self):
        self.assertEqual(spoken("Thinking: be nice.\n===\nBeep waves.\nAs an AI, I cannot."), "Beep waves.")

    def test_a_reply_of_only_tags_has_no_words(self):
        self.assertEqual(spoken("[ACTION: IDLE]"), "")
        self.assertEqual(spoken(""), "")


if __name__ == "__main__":
    unittest.main()
