import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import chat_prompt, prompts


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

    def test_an_animal_never_overhears(self):
        nearby = self.NEARBY + [
            {"name": "Bone Mutt", "npc_id": "h:3", "race": "Bone Mutt", "animal": True, "dist": 10},
            {"name": "Gurgler", "npc_id": "h:4", "race": "Fishman", "animal": False, "dist": 10},
        ]
        self.assertEqual([n["npc_id"] for n in chat_prompt.overhearers(nearby, 100, set())], ["h:1", "h:2"])

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

    def test_only_lines_that_the_npc_did_not_overhear_count_as_spoken(self):
        stick, izumi = "h:10", "h:11"
        self.assertEqual(chat_prompt.spoken_with([], [], BEEP), [])
        overheard = [("[Day 3, 14:02] (Overheard) Izumi to Ruka: hey Ruka", izumi, 1), ("(Overheard) (Whispered) Izumi to Kai: psst", izumi, 2)]
        self.assertEqual(chat_prompt.spoken_with(overheard, [], BEEP), [])
        self.assertEqual(chat_prompt.spoken_with([*overheard, ("[Day 3, 14:03] Stick: (Overheard) nothing", stick, 3)], [], BEEP), [stick])

    def test_the_partners_of_the_threads_come_first_then_the_other_speakers_of_the_lines(self):
        entries = [
            ("[Day 4, 08:00] Ruka: Hot today.", "h:13", None),
            ("[Day 4, 08:01] Beep: Beep agrees!", BEEP, None),
            ("[Day 4, 09:00] Izumi: hey", "h:11", 4),
            ("[Day 4, 09:01] Drifter: hey", None, 4),
        ]
        self.assertEqual(chat_prompt.spoken_with(entries, ["h:10", "h:11", "h:10"], BEEP), ["h:10", "h:11", "h:13"])

    def test_the_chat_lines_leave_out_a_row_with_no_thread(self):
        entries = [("[Day 4, 08:00] Ruka: Hot today.", "h:13", None), ("[Day 4, 09:00] Izumi: hey", "h:11", 4)]
        self.assertEqual(chat_prompt.chat_lines(entries), entries[1:])

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

    def test_the_note_names_every_other_speaker(self):
        members = {5: [("h:10", "Stick", "speaker", True), (BEEP, "Beep", "speaker", False), ("h:11", "Izumi", "speaker", True), ("h:13", "Mikse", "overheard", True)]}
        self.assertEqual(chat_prompt.overheard_notes(members, BEEP), {5: "Mikse heard your conversation with Stick and Izumi."})

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


class MemoriesTest(unittest.TestCase):
    STICK, IZUMI, MIKSE, JORGE = "h:10", "h:11", "h:12", "h:14"

    def memory(self, members, text="{h:10} asked {h:14} for work.", game_time=3 * 1440 + 14 * 60 + 5):
        return {"id": 1, "game_time": game_time, "memory": text, "members": members}

    def test_a_speaker_reads_who_of_the_player_faction_heard_it(self):
        members = [(self.STICK, "Stick", "speaker", True), (self.JORGE, "Jorge", "speaker", False), (self.IZUMI, "Izumi", "overheard", True), ("h:20", "Guard", "overheard", False)]
        self.assertEqual(chat_prompt.memories_block([self.memory(members)], self.JORGE), "\n".join([
            "Memories of your earlier conversations, oldest first. You know what happened in them. When the talk turns to one, reply truthfully or with a lie. You are not required to uphold the past:",
            "[Day 3, 14:05] You spoke with Stick. Izumi heard it.",
            "Stick asked Jorge for work.",
        ]))

    def test_an_overhearer_reads_both_speakers(self):
        members = [(self.STICK, "Stick", "speaker", True), (self.JORGE, "Jorge", "speaker", False), (self.MIKSE, "Mikse", "overheard", True)]
        self.assertEqual(chat_prompt.memories_block([self.memory(members)], self.MIKSE).splitlines()[1], "[Day 3, 14:05] You overheard Stick and Jorge.")

    def test_no_memory_gives_no_heading(self):
        self.assertEqual(chat_prompt.memories_block([], self.JORGE), "")

    def test_the_names_are_the_current_names(self):
        members = [(self.STICK, "Stickman", "speaker", True), (self.JORGE, None, "speaker", False)]
        self.assertEqual(chat_prompt.memories_block([self.memory(members)], self.STICK).splitlines()[1:], ["[Day 3, 14:05] You spoke with someone.", "Stickman asked someone for work."])

    def test_the_library_line_does_not_speak_to_the_npc(self):
        members = [(self.STICK, "Stick", "speaker", True), (self.JORGE, "Jorge", "speaker", False), (self.MIKSE, "Mikse", "overheard", True)]
        self.assertEqual(chat_prompt.memory_lines([self.memory(members)], self.JORGE), ["[Day 3, 14:05] (Memory of a conversation with Stick, heard by Mikse) Stick asked Jorge for work."])
        self.assertEqual(chat_prompt.memory_lines([self.memory(members, game_time=None)], self.MIKSE), ["(Memory of an overheard conversation of Stick and Jorge) Stick asked Jorge for work."])

    def test_a_shared_memory_names_every_member(self):
        members = [(self.STICK, "Stick", "speaker", True), (self.JORGE, "Jorge", "speaker", True), (self.MIKSE, "Mikse", "overheard", True)]
        self.assertEqual(chat_prompt.shared_memory(self.memory(members)), "[Day 3, 14:05] (Memory of a conversation between Stick and Jorge, heard by Mikse) Stick asked Jorge for work.")

    def test_the_starting_memories_are_the_newest_in_which_the_npc_spoke(self):
        spoke = [(self.STICK, "Stick", "speaker", True), (self.JORGE, "Jorge", "speaker", False)]
        heard = [(self.STICK, "Stick", "speaker", True), (self.IZUMI, "Izumi", "speaker", True), (self.JORGE, "Jorge", "overheard", False)]
        memories = [{**self.memory(spoke), "id": i} for i in range(1, 7)] + [{**self.memory(heard), "id": 7}]
        self.assertEqual([memory["id"] for memory in chat_prompt.starting_memories(memories, self.JORGE)], [2, 3, 4, 5, 6])

    def test_a_header_names_the_others_before_the_lines_of_each_thread(self):
        members = {1: [(self.STICK, "Stick", "speaker", True), (self.JORGE, "Jorge", "speaker", False)], 2: [(self.IZUMI, "Izumi", "speaker", True), (self.JORGE, "Jorge", "speaker", False), (self.STICK, "Stick", "overheard", True)]}
        entries = [("a", self.STICK, 1), ("b", self.JORGE, 1), ("stray", "h:20", None), ("c", self.IZUMI, 2), ("d", self.JORGE, 2), ("e", self.STICK, 1)]
        self.assertEqual(chat_prompt.headed_lines(entries, members, self.JORGE), [
            "(Conversation with Stick)", "a", "b", "stray", "(Conversation with Izumi, heard by Stick)", "c", "d", "(Conversation with Stick)", "e",
        ])


class BackgroundBlockTest(unittest.TestCase):
    STICK, JORGE, ABEL = "h:10", "h:14", "h:15"
    ADMAG = {"kind": "location", "name": "Admag", "aliases": [], "fields": {"type": "town", "zone": ["Stenn Desert"]}, "description": "The Shek capital."}
    MEMORY = {"id": 1, "game_time": 3 * 1440 + 14 * 60 + 5, "memory": "{h:10} asked {h:14} for work.", "members": [(STICK, "Stick", "speaker", True), (JORGE, "Jorge", "speaker", False), (ABEL, "Paladin Abel", "overheard", False)]}
    RUMOR = {"id": 1, "event_id": 1, "game_time": 1440 + 9 * 60, "text": "A caravan never arrived.", "instruction": None}

    def test_nothing_found_gives_no_block(self):
        self.assertEqual(chat_prompt.background_block([], [], [], self.ABEL, "Izumi"), "")

    def test_an_entry_gives_its_name_kind_fields_and_text(self):
        self.assertEqual(chat_prompt.background_block([], [], [self.ADMAG], self.ABEL, "Izumi"), "\n".join([
            "(Background, not said aloud. Lore that Izumi's words may touch on:",
            "- Admag (location; type: town; zone: Stenn Desert): The Shek capital.",
            "This lore may have nothing to do with what Izumi means, and you may know less than it says. Use it only where it fits your reply, and never recite it or turn the talk towards it.)",
        ]))

    def test_a_memory_gives_its_header_from_the_view_of_the_npc(self):
        self.assertEqual(chat_prompt.background_block([self.MEMORY], [], [], self.ABEL, "Izumi"), "\n".join([
            "(Background, not said aloud. Memories that Izumi's words may touch on:",
            "[Day 3, 14:05] You overheard Stick and Jorge.",
            "Stick asked Jorge for work.",
            "These memories may have nothing to do with what Izumi means. Use them only where they fit your reply, and never recite them or turn the talk towards them.)",
        ]))

    def test_the_memories_come_before_the_lore(self):
        lines = chat_prompt.background_block([self.MEMORY], [], [self.ADMAG], self.ABEL, "Izumi").splitlines()
        self.assertEqual([lines[0], lines[3]], ["(Background, not said aloud. Memories that Izumi's words may touch on:", "Lore that Izumi's words may touch on:"])
        self.assertTrue(lines[-1].startswith("These memories and this lore may have nothing to do with what Izumi means, and you may know less than the lore says."))

    def test_a_rumor_gives_its_age(self):
        self.assertEqual(chat_prompt.background_block([], [self.RUMOR], [], self.ABEL, "Izumi", today=5), "\n".join([
            "(Background, not said aloud. Rumours that Izumi's words may touch on:",
            "- A few days ago you heard a rumour: A caravan never arrived.",
            "These rumours may have nothing to do with what Izumi means. Use them only where they fit your reply, and never recite them or turn the talk towards them.)",
        ]))

    def test_the_rumors_come_between_the_memories_and_the_lore(self):
        lines = chat_prompt.background_block([self.MEMORY], [self.RUMOR], [self.ADMAG], self.ABEL, "Izumi").splitlines()
        self.assertEqual([lines[3], lines[5]], ["Rumours that Izumi's words may touch on:", "Lore that Izumi's words may touch on:"])
        self.assertTrue(lines[-1].startswith("These memories, these rumours, and this lore may have nothing to do with what Izumi means, and you may know less than the lore says."))

    def test_the_lore_from_travels_follows_under_its_own_heading(self):
        vain = {"kind": "region", "name": "Vain", "aliases": [], "fields": {}, "description": "Cliffs."}
        self.assertEqual(chat_prompt.background_block([], [], [self.ADMAG], self.ABEL, "Izumi", [vain]).splitlines()[:4], [
            "(Background, not said aloud. Lore that Izumi's words may touch on:",
            "- Admag (location; type: town; zone: Stenn Desert): The Shek capital.",
            "You learned the following in your travels:",
            "- Vain (region): Cliffs.",
        ])
        self.assertEqual(chat_prompt.background_block([], [], [], self.ABEL, "Izumi", [vain]).splitlines()[0], "(Background, not said aloud. You learned the following in your travels:")

    def test_a_long_text_is_cut_and_the_fields_stay(self):
        entry = {**self.ADMAG, "description": "Walls. " * 200}
        line = chat_prompt.background_block([], [], [entry], self.ABEL, "Izumi").splitlines()[1]
        self.assertTrue(line.startswith("- Admag (location; type: town; zone: Stenn Desert): Walls."))
        self.assertLessEqual(len(line), len("- Admag (location; type: town; zone: Stenn Desert): ") + 700)


class NameMarksTest(unittest.TestCase):
    MEMBERS = [("h:1", "Dust Bandit"), ("h:2", "Dust Bandit Josh"), ("h:3", "Jorge")]

    def test_only_whole_names_are_marked_the_longest_first(self):
        text = "Dust Bandit Josh owed Jorge 30 cats. Jorgeson saw a Dust Bandit."
        self.assertEqual(chat_prompt.mark_names(text, self.MEMBERS), "{h:2} owed {h:3} 30 cats. Jorgeson saw a {h:1}.")

    def test_a_name_that_two_members_share_stays_as_text(self):
        self.assertEqual(chat_prompt.mark_names("Dust Bandit threatened Jorge.", [*self.MEMBERS, ("h:4", "Dust Bandit")]), "Dust Bandit threatened {h:3}.")

    def test_a_rename_reaches_the_text(self):
        marked = chat_prompt.mark_names("Jorge's bar.", self.MEMBERS)
        self.assertEqual(chat_prompt.named(marked, {"h:3": "Old Jorge"}), "Old Jorge's bar.")


class ChatMessagesTest(unittest.TestCase):
    def test_the_tail_comes_last(self):
        turns = chat_prompt.history_turns([("Drifter: hi", None), ("Beep: Hello.", BEEP)], BEEP)
        self.assertEqual(chat_prompt.chat_messages("S", turns, "T")[-1], {"role": "user", "content": "T"})

    def test_a_history_with_no_lines_gives_no_turns(self):
        self.assertEqual(chat_prompt.chat_messages("S", chat_prompt.history_turns([], BEEP), "T"), [{"role": "system", "content": "S"}, {"role": "user", "content": "T"}])

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


class DescribeRecordTest(unittest.TestCase):
    def test_a_neighbour_reads_with_its_direction(self):
        vain = {"name": "Vain", "fields": {"hazards": ["acid rain"], "neighbours": {"Stenn Desert": "south", "Okran's Gulf": "east"}}, "description": "Hive lands."}
        self.assertEqual(prompts.describe_record(vain, "region"), "Vain (region; hazards: acid rain; neighbours: Stenn Desert to the south, Okran's Gulf to the east): Hive lands.")


if __name__ == "__main__":
    unittest.main()
