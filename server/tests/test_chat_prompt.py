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


class OverhearersTest(unittest.TestCase):
    NEARBY = [
        {"name": "Dust Bandit", "npc_id": "h:1", "dist": 50},
        {"name": "Dust Bandit", "npc_id": "h:2", "dist": 80},
        {"name": "Beep", "npc_id": "u:19576-Dialogue.mod", "dist": 300},
    ]

    def test_two_npcs_of_one_name_both_overhear(self):
        self.assertEqual([n["npc_id"] for n in chat_prompt.overhearers(self.NEARBY, 100, {"h:9"})], ["h:1", "h:2"])

    def test_the_target_does_not_overhear_its_own_chat(self):
        self.assertEqual([n["npc_id"] for n in chat_prompt.overhearers(self.NEARBY, 400, {"h:1"})], ["h:2", "u:19576-Dialogue.mod"])

    def test_nobody_overhears_without_a_radius(self):
        self.assertEqual(chat_prompt.overhearers(self.NEARBY, None, set()), [])

    def test_an_npc_listed_twice_overhears_once(self):
        self.assertEqual(len(chat_prompt.overhearers(self.NEARBY[:1] * 2, 100, set())), 1)


BEEP = "u:19576-Dialogue.mod"


class HistoryTurnsTest(unittest.TestCase):
    def test_the_npc_lines_are_assistant_turns_without_time_or_name(self):
        entries = [
            ("[Day 3, 14:01] (Whispered) Drifter: hi", "h:1"),
            ("[Day 3, 14:01] Beep: Beep friend!", BEEP),
        ]
        self.assertEqual(chat_prompt.history_turns(entries, BEEP), [
            {"role": "user", "content": "[Day 3, 14:01] (Whispered) Drifter: hi"},
            {"role": "assistant", "content": "Beep friend!"},
        ])

    def test_lines_the_npc_heard_are_user_turns_and_merge(self):
        entries = [
            ("[Day 3, 14:01] Beep: Hello.", BEEP),
            ("[Day 3, 14:02] (Overheard) Drifter: hey Ruka", None),
            ("[Day 3, 14:02] Ruka: The sand gets everywhere.", "h:2"),
            ("Beep|1234: an old yell line", BEEP),
        ]
        self.assertEqual(chat_prompt.history_turns(entries, BEEP), [
            {"role": "user", "content": chat_prompt.EARLIER},
            {"role": "assistant", "content": "Hello."},
            {"role": "user", "content": "[Day 3, 14:02] (Overheard) Drifter: hey Ruka\n[Day 3, 14:02] Ruka: The sand gets everywhere."},
            {"role": "assistant", "content": "an old yell line"},
        ])

    def test_a_line_of_another_npc_with_the_same_name_is_a_user_turn(self):
        entries = [("[Day 3, 14:01] Dust Bandit: Hot today.", "h:2"), ("[Day 3, 14:01] Dust Bandit: Always is.", "h:1")]
        self.assertEqual([turn["role"] for turn in chat_prompt.history_turns(entries, "h:1")], ["user", "assistant"])

    def test_a_line_without_a_speaker_is_never_the_npc_line(self):
        self.assertEqual(chat_prompt.history_turns([("Beep: Hello.", None)], None), [{"role": "user", "content": "Beep: Hello."}])

    def test_only_lines_of_the_squad_member_that_the_npc_did_not_overhear_count_as_spoken(self):
        stick, izumi = "h:10", "h:11"
        self.assertFalse(chat_prompt.has_spoken_with([], izumi))
        overheard = [("[Day 3, 14:02] (Overheard) Izumi to Ruka: hey Ruka", izumi, 1), ("(Overheard) (Whispered) Izumi to Kai: psst", izumi, 2)]
        self.assertFalse(chat_prompt.has_spoken_with(overheard, izumi))
        spoke = [*overheard, ("[Day 3, 14:03] Stick: (Overheard) nothing", stick, 3)]
        self.assertTrue(chat_prompt.has_spoken_with(spoke, stick))
        self.assertFalse(chat_prompt.has_spoken_with(spoke, izumi))

    def test_a_squad_member_of_the_same_name_has_not_spoken(self):
        self.assertFalse(chat_prompt.has_spoken_with([("[Day 3, 14:03] Ruka: hi", "h:12", 1)], "h:13"))

    def test_the_companions_are_the_other_speakers_in_the_order_of_their_first_line(self):
        entries = [
            ("[Day 3, 14:01] Stick: hi", "h:10", 1),
            ("[Day 3, 14:01] Beep: Beep friend!", BEEP, 1),
            ("[Day 3, 14:05] (Overheard) Mikse to Ruka: psst", "h:12", 2),
            ("[Day 4, 08:00] Ruka: Hot today.", "h:13", None),
            ("[Day 4, 08:01] Stick: again", "h:10", 3),
            ("[Day 4, 09:00] Izumi: hey", "h:11", 4),
            ("[Day 4, 09:01] Drifter: hey", None, 4),
        ]
        self.assertEqual(chat_prompt.companions(entries, BEEP, "h:11"), ["h:10", "h:13"])

    def test_an_empty_reply_is_never_empty_content(self):
        self.assertEqual(chat_prompt.history_turns([("Drifter: hi", None), ("Beep:", BEEP)], BEEP)[-1], {"role": "assistant", "content": "..."})


class OverheardNotesTest(unittest.TestCase):
    MEMBERS = {
        1: [("h:10", "Stick", "speaker", True), (BEEP, "Beep", "speaker", False), ("h:11", "Izumi", "overheard", True), ("h:12", "Ruka", "overheard", False), ("h:13", "Mikse", "overheard", True)],
        2: [("h:11", "Izumi", "speaker", True), ("h:14", "Jorge", "speaker", False), (BEEP, "Beep", "overheard", False), ("h:10", "Stick", "overheard", True)],
        3: [("h:10", "Stick", "speaker", True), (BEEP, "Beep", "speaker", False), ("h:12", "Ruka", "overheard", False)],
        4: [("h:10", "Stick", "speaker", True), (BEEP, "Beep", "speaker", False), ("h:15", None, "overheard", True)],
    }

    def test_a_speaker_hears_who_of_the_player_faction_overheard(self):
        self.assertEqual(chat_prompt.overheard_notes(self.MEMBERS, BEEP), {1: "Izumi and Mikse heard your conversation with Stick."})

    def test_the_squad_member_reads_the_note_of_its_own_thread(self):
        self.assertEqual(chat_prompt.overheard_notes(self.MEMBERS, "h:11"), {2: "Stick heard your conversation with Jorge."})

    def test_each_note_follows_the_last_line_of_its_thread(self):
        entries = [
            ("[Day 3, 14:01] Stick: hi", "h:10", 1),
            ("[Day 3, 14:01] Beep: Beep friend!", BEEP, 1),
            ("[Day 3, 14:02] Ruka: Hot today.", "h:12", None),
            ("[Day 3, 14:03] Stick: bye", "h:10", 1),
            ("[Day 3, 14:03] Beep: Bye!", BEEP, 1),
            ("[Day 4, 08:00] Stick: back", "h:10", 3),
        ]
        note = "Izumi and Mikse heard your conversation with Stick."
        self.assertEqual(chat_prompt.with_notes(entries, {1: note}), [
            ("[Day 3, 14:01] Stick: hi", "h:10"),
            ("[Day 3, 14:01] Beep: Beep friend!", BEEP),
            ("[Day 3, 14:02] Ruka: Hot today.", "h:12"),
            ("[Day 3, 14:03] Stick: bye", "h:10"),
            ("[Day 3, 14:03] Beep: Bye!", BEEP),
            (note, None),
            ("[Day 4, 08:00] Stick: back", "h:10"),
        ])
        self.assertEqual(chat_prompt.history_turns(chat_prompt.with_notes(entries[3:5], {1: note}), BEEP)[-1], {"role": "user", "content": note})


class ChatMessagesTest(unittest.TestCase):
    def test_the_tail_comes_last(self):
        turns = chat_prompt.history_turns([("Drifter: hi", None), ("Beep: Hello.", BEEP)], BEEP)
        self.assertEqual(chat_prompt.chat_messages("S", turns, "T")[-1], {"role": "user", "content": "T"})

    def test_a_trailing_user_turn_takes_the_tail(self):
        turns = chat_prompt.history_turns([("Beep: Hello.", BEEP), ("Drifter: bye", None)], BEEP)
        messages = chat_prompt.chat_messages("S", turns, "T")
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "user"])
        self.assertEqual(messages[-1]["content"], "Drifter: bye\n\nT")
        self.assertEqual(turns[-1]["content"], "Drifter: bye")

    def test_the_next_turn_starts_with_this_turn_but_its_tail(self):
        history = [("Drifter: hi", None), ("Beep: Hello.", BEEP)] * 15
        first = chat_prompt.chat_messages("S", chat_prompt.history_turns(chat_prompt.history_window(history, 20), BEEP), "scene 1")
        history += [("Drifter: again", None), ("Beep: Again?", BEEP)]
        second = chat_prompt.chat_messages("S", chat_prompt.history_turns(chat_prompt.history_window(history, 20), BEEP), "scene 2")
        self.assertEqual(second[:len(first) - 1], first[:-1])


if __name__ == "__main__":
    unittest.main()
