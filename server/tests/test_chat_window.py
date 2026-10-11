import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import chat_window
from core import state
from store import campaign_db

STICK, IZUMI, RUKA, JORGE = "h:10", "h:11", "h:12", "h:13"
QUIET = 180
SEED = {"template": {"name": "test", "version": "1", "hash": "x"}, "overview": "", "history": [], "factions": [], "characters": [], "entities": []}


class OpenThreadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)
        for npc_id, name in ((STICK, "Stick"), (IZUMI, "Izumi"), (JORGE, "Jorge")):
            campaign_db.upsert_profile(npc_id, {"Name": name})

    def tearDown(self):
        state.CURRENT_THREAD.clear()
        self._tmp.cleanup()

    def chat(self, thread_id, speaker, line, listeners=(), action=None):
        """One exchange of speaker with Jorge, stored as the chat route stores it, which makes it the current thread."""
        members = [(speaker, "speaker", True), (JORGE, "speaker", False), *((npc_id, "overheard", True) for npc_id in listeners)]
        thread_id = campaign_db.join_thread(thread_id, members, campaign_db.game_time("[Day 3, 14:05] "), "The Hub")
        campaign_db.append_dialogue(JORGE, [(f"[Day 3, 14:05] {line}", speaker), ("[Day 3, 14:05] Jorge: Hm.", JORGE)], {}, thread_id)
        for npc_id in listeners:
            campaign_db.append_dialogue(npc_id, [(f"[Day 3, 14:05] (Overheard) {line}", speaker)], {}, thread_id)
        state.CURRENT_THREAD.update(key=(JORGE, "talk"), id=thread_id, replied=time.monotonic(), action=action)
        return thread_id

    def test_an_open_thread_holds_only_its_own_lines_of_the_npc(self):
        old = self.chat(None, STICK, "Stick: Before.")
        state.CURRENT_THREAD.clear()
        thread_id = self.chat(None, STICK, "Stick: Hello.", listeners=[IZUMI])
        self.chat(thread_id, RUKA, "Ruka: And me.")
        self.assertNotEqual(old, thread_id)
        self.assertEqual(chat_window.open_thread(JORGE, QUIET), {
            "title": "Stick, Jorge, and 1 more | The Hub",
            "type": "Chat",
            "lines": "\n".join(["[Day 3, 14:05] Stick: Hello.", "[Day 3, 14:05] Jorge: Hm.", "[Day 3, 14:05] Ruka: And me.", "[Day 3, 14:05] Jorge: Hm."]),
        })

    def test_an_action_dialogue_names_its_category(self):
        self.chat(None, STICK, "Stick: Sell me bread.", action={"category": "BARTER", "speaker": STICK})
        thread = chat_window.open_thread(JORGE, QUIET)
        self.assertEqual((thread["title"], thread["type"]), ("Stick and Jorge | The Hub", "Barter"))

    def test_the_yell_thread_is_open_for_each_of_its_members_only(self):
        self.chat(None, STICK, "(Yelled) Stick: Hey!", listeners=[IZUMI])
        state.CURRENT_THREAD["key"] = (None, "yell")
        self.assertEqual(chat_window.open_thread(JORGE, QUIET)["title"], "Stick and Jorge | The Hub")
        self.assertEqual(chat_window.open_thread(IZUMI, QUIET)["lines"], "[Day 3, 14:05] (Overheard) (Yelled) Stick: Hey!")
        self.assertIsNone(chat_window.open_thread(RUKA, QUIET))

    def test_no_thread_is_open_for_another_npc_after_the_timeout_or_after_an_end(self):
        self.chat(None, STICK, "Stick: Hello.")
        self.assertIsNone(chat_window.open_thread(STICK, QUIET))
        self.assertIsNone(chat_window.open_thread("", QUIET))
        state.CURRENT_THREAD["replied"] = time.monotonic() - QUIET
        self.assertIsNone(chat_window.open_thread(JORGE, QUIET))
        state.CURRENT_THREAD.clear()
        self.assertIsNone(chat_window.open_thread(JORGE, QUIET))


if __name__ == "__main__":
    unittest.main()
