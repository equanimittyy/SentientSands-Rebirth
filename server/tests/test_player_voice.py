import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import player_voice

PROFILE = {"Race": "Shek", "Personality": "Blunt and proud.", "Backstory": "A deserter.", "SpeechQuirks": "Short, hard words."}


class BubbleTest(unittest.TestCase):
    def test_matches_the_bubble_of_the_plugin(self):
        cases = {
            "Hello there": "Hello there",
            "/stock": "",
            "!b Two waters": "Two waters",
            "! Hand it over": "Hand it over",
            "!end": "",
            "!!!": "!!!",
            "!?": "!?",
            "!": "!",
        }
        for message, bubble in cases.items():
            self.assertEqual(player_voice.bubble(message), bubble, message)


class RewriteTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        patcher = mock.patch.object(player_voice, "language_instruction", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)

    def rewrite(self, line, reply, profile=PROFILE, last_line=""):
        with mock.patch.object(player_voice, "call_llm", return_value=reply) as call:
            result = player_voice.rewrite(line, "Beep", profile, "Ruka", "whisper", last_line, until=99)
        return result, call

    def test_returns_the_cleaned_rewrite(self):
        self.assertEqual(self.rewrite("Can you help me?", '"Need a hand. You in?"')[0], "Need a hand. You in?")
        self.assertEqual(self.rewrite("Can you help me?", "Beep: Need a hand.")[0], "Need a hand.")

    def test_prompt_holds_the_speaker_the_listener_and_the_line(self):
        _, call = self.rewrite("Can you help me?", "Need a hand.", last_line="Ruka: What do you want?")
        task, messages, until = call.call_args.args
        self.assertEqual((task, until), ("rephrase", 99))
        prompt = messages[0]["content"]
        for part in ("Blunt and proud.", "Short, hard words.", "Shek", "Beep whispers it to Ruka.", "LAST LINE OF THE TALK: Ruka: What do you want?", "LINE: Can you help me?"):
            self.assertIn(part, prompt)

    def test_prompt_without_a_last_line_has_no_label(self):
        _, call = self.rewrite("Hello", "Hey.")
        self.assertNotIn("LAST LINE", call.call_args.args[1][0]["content"])

    def test_lines_without_words_and_animals_get_no_call(self):
        for line, profile in (("*nods*", PROFILE), ("*waves* *smiles*", PROFILE), ("Hello", dict(PROFILE, Animal=True))):
            result, call = self.rewrite(line, "Changed", profile)
            self.assertEqual(result, line)
            call.assert_not_called()

    def test_no_reply_keeps_the_raw_line(self):
        self.assertEqual(self.rewrite("Hello", None)[0], "Hello")
        self.assertEqual(self.rewrite("Hello", "[JUDGMENT: 0]")[0], "Hello")

    def test_a_lost_number_keeps_the_raw_line(self):
        self.assertEqual(self.rewrite("I'll give you 200 cats", "Some cats for it.")[0], "I'll give you 200 cats")
        self.assertEqual(self.rewrite("2 days for 500 cats", "Two days, 500 cats.")[0], "2 days for 500 cats")

    def test_thousands_separators_match(self):
        self.assertEqual(self.rewrite("I pay 2,000 cats", "2000 cats. Take it.")[0], "2000 cats. Take it.")
        self.assertEqual(self.rewrite("I pay 2000 cats", "2,000 cats, no more.")[0], "2,000 cats, no more.")


if __name__ == "__main__":
    unittest.main()
