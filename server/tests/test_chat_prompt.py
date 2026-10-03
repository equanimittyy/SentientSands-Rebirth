import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import chat_prompt


class HistoryWindowTest(unittest.TestCase):
    def test_keeps_its_first_line_until_it_holds_two_blocks(self):
        lines = [f"line {i}" for i in range(100)]
        firsts = {chat_prompt.history_window(lines[:n], 20)[0] for n in range(40, 60)}
        self.assertEqual(firsts, {"line 20"})
        self.assertEqual(chat_prompt.history_window(lines[:60], 20)[0], "line 40")

    def test_a_short_history_is_whole(self):
        self.assertEqual(chat_prompt.history_window(["a", "b"], 20), ["a", "b"])

    def test_a_trim_of_one_block_keeps_the_first_line(self):
        lines = [f"line {i}" for i in range(250)]
        self.assertEqual(chat_prompt.history_window(lines, 20)[0], chat_prompt.history_window(lines[20:], 20)[0])


class HistoryTurnsTest(unittest.TestCase):
    def test_the_npc_lines_are_assistant_turns_without_time_or_name(self):
        lines = [
            "[Day 3, 14:01] Drifter [ACTION: WHISPERS TO Beep]: hi",
            "[Day 3, 14:01] Beep: Beep friend! [ACTION: JUDGMENT: 2]",
        ]
        self.assertEqual(chat_prompt.history_turns(lines, "Beep"), [
            {"role": "user", "content": "[Day 3, 14:01] Drifter [ACTION: WHISPERS TO Beep]: hi"},
            {"role": "assistant", "content": "Beep friend! [ACTION: JUDGMENT: 2]"},
        ])

    def test_lines_the_npc_heard_are_user_turns_and_merge(self):
        lines = [
            "[Day 3, 14:01] Beep: Hello.",
            "[Day 3, 14:02] (Overheard) Drifter: hey Ruka",
            "[Day 3, 14:02] Ruka: The sand gets everywhere.",
            "Beep|1234: an old yell line",
        ]
        self.assertEqual(chat_prompt.history_turns(lines, "beep"), [
            {"role": "user", "content": chat_prompt.EARLIER},
            {"role": "assistant", "content": "Hello."},
            {"role": "user", "content": "[Day 3, 14:02] (Overheard) Drifter: hey Ruka\n[Day 3, 14:02] Ruka: The sand gets everywhere."},
            {"role": "assistant", "content": "an old yell line"},
        ])

    def test_an_empty_reply_is_never_empty_content(self):
        self.assertEqual(chat_prompt.history_turns(["Drifter: hi", "Beep:"], "Beep")[-1], {"role": "assistant", "content": "..."})


class ChatMessagesTest(unittest.TestCase):
    def test_the_tail_comes_last(self):
        turns = chat_prompt.history_turns(["Drifter: hi", "Beep: Hello."], "Beep")
        self.assertEqual(chat_prompt.chat_messages("S", turns, "T")[-1], {"role": "user", "content": "T"})

    def test_a_trailing_user_turn_takes_the_tail(self):
        turns = chat_prompt.history_turns(["Beep: Hello.", "Drifter: bye"], "Beep")
        messages = chat_prompt.chat_messages("S", turns, "T")
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[-1]["content"], "Drifter: bye\n\nT")
        self.assertEqual(turns[-1]["content"], "Drifter: bye")

    def test_the_next_turn_starts_with_this_turn_but_its_tail(self):
        history = ["Drifter: hi", "Beep: Hello."] * 15
        first = chat_prompt.chat_messages("S", chat_prompt.history_turns(chat_prompt.history_window(history, 20), "Beep"), "scene 1")
        history += ["Drifter: again", "Beep: Again?"]
        second = chat_prompt.chat_messages("S", chat_prompt.history_turns(chat_prompt.history_window(history, 20), "Beep"), "scene 2")
        self.assertEqual(second[:len(first) - 1], first[:-1])


if __name__ == "__main__":
    unittest.main()
