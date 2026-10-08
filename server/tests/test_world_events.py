import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import prompts, rumors
from core import state, world_events
from store import campaign_db

TINFIST_ID = "u:tinfist"
SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "",
    "factions": [{"faction_id": "1-test.mod", "name": "Anti-Slavers", "aliases": [], "major": False, "fields": {"enemies": ["The Holy Nation", "Slave Traders"]}, "description": ""}],
    "history": [],
    "characters": [
        {"game_id": "tinfist", "profile": {"Name": "Tinfist", "Race": "Skeleton", "Sex": "Other", "Backstory": "Leader of the Anti-Slavers. Once a slave."}},
        {"game_id": "dust-king", "profile": {"Name": "Dust King"}},
        {"game_id": "longen", "profile": {"Name": "Longen"}},
    ],
    "entities": [],
}


def party(npc_id, name, faction="Dust Bandits", player=False, template_id=""):
    return {"id": npc_id, "template_id": template_id, "name": name, "faction": faction, "player": player}


BEEP = party("h:1", "Beep", "Nameless", player=True)
IZUMI = party("h:2", "Izumi", "Nameless", player=True)
TINFIST = party("h:3", "Tinfist", "Anti-Slavers", template_id="tinfist")
KING = party("u:dust-king", "Dust King")
LONGEN = party("u:longen", "Longen", "Traders Guild")


def when(minutes):
    return {"day": minutes // 1440, "hour": minutes % 1440 // 60, "minute": minutes % 60}


def at(day, hour=0, minute=0):
    return day * 1440 + hour * 60 + minute


def attack(attacker, target, minutes):
    return {"kind": "attack", "attacker": attacker, "target": target["id"], **when(minutes)}


def knockout(target, minutes):
    return {"kind": "knockout", "id": target["id"], **when(minutes)}


def up(target, minutes, carried=False):
    return {"kind": "up", "id": target["id"], "carried": carried, **when(minutes)}


def death(target, minutes):
    return {"kind": "death", "party": target, **when(minutes)}


def imprisonment(target, minutes):
    return {"kind": "imprisonment", "party": target, **when(minutes)}


def bandit(number):
    return party(f"h:{1000 + number}", "Dust Bandit")


class WorldEventsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)
        campaign_db.note_faction("204-gamedata.base", "Nameless", is_player=True)
        self._campaign = state.ACTIVE_CAMPAIGN
        # A new campaign name gives the attribution a fresh memory
        state.ACTIVE_CAMPAIGN = self.id()

    def tearDown(self):
        state.ACTIVE_CAMPAIGN = self._campaign
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def events(self):
        return [(event["kind"], doer["id"], event["victim"]["id"]) for _, _, event in reversed(campaign_db.events()) for doer in event["doers"]]

    def lines(self):
        return [event["line"] for event in world_events.events()]

    def kill(self, doers, victim, minutes):
        world_events.take([attack(doer, victim, minutes) for doer in doers] + [death(victim, minutes)])


class FightTest(WorldEventsTestCase):
    SQUAD = {BEEP["id"], IZUMI["id"]}

    def test_an_attack_by_a_character_within_3_game_hours_is_a_fight(self):
        world_events.take([attack(BEEP, KING, at(1, 10))])
        self.assertTrue(world_events.fought_recently(self.SQUAD, when(at(1, 13))))
        self.assertFalse(world_events.fought_recently(self.SQUAD, when(at(1, 13, 1))))

    def test_a_knockout_of_a_character_is_a_fight(self):
        world_events.take([knockout(IZUMI, at(1, 10))])
        self.assertTrue(world_events.fought_recently(self.SQUAD, when(at(1, 12))))

    def test_the_fights_of_other_characters_do_not_count(self):
        world_events.take([attack(party("h:9", "Guard", "United Cities"), KING, at(1, 10)), knockout(KING, at(1, 10, 1)), attack(KING, BEEP, at(1, 10, 2))])
        self.assertFalse(world_events.fought_recently(self.SQUAD, when(at(1, 11))))

    def test_a_context_with_no_game_time_has_no_fight(self):
        world_events.take([attack(BEEP, KING, at(1, 10))])
        self.assertFalse(world_events.fought_recently(self.SQUAD, {}))


class AttributionTest(WorldEventsTestCase):
    def test_a_death_gives_a_kill_to_each_attacker_of_the_last_3_game_hours(self):
        world_events.take([attack(BEEP, KING, at(1, 10)), attack(IZUMI, KING, at(1, 11)), death(KING, at(1, 13))])
        world_events.take([attack(BEEP, LONGEN, at(1, 14)), death(LONGEN, at(1, 17, 1))])
        self.assertEqual(self.events(), [("kill", "h:1", KING["id"]), ("kill", "h:2", KING["id"])])

    def test_a_knocked_out_character_keeps_its_attackers(self):
        world_events.take([attack(BEEP, KING, at(1, 10)), knockout(KING, at(1, 10, 1)), death(KING, at(1, 20))])
        self.assertEqual(self.events(), [("kill", "h:1", KING["id"])])

    def test_an_up_that_is_not_carried_ends_the_knockout_and_restarts_the_clock(self):
        first, second = KING, LONGEN
        for victim, dies in ((first, at(1, 14, 30)), (second, at(1, 15, 1))):
            world_events.take([attack(BEEP, victim, at(1, 10)), knockout(victim, at(1, 10, 1)), up(victim, at(1, 12)), death(victim, dies)])
        self.assertEqual(self.events(), [("kill", "h:1", first["id"])])

    def test_a_carried_up_keeps_the_captors_of_the_knockout(self):
        world_events.take([attack(BEEP, TINFIST, at(1, 10)), attack(IZUMI, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)),
                    up(TINFIST, at(1, 10, 5), carried=True), imprisonment(TINFIST, at(2, 9))])
        self.assertEqual(self.events(), [("capture", "h:1", TINFIST_ID), ("capture", "h:2", TINFIST_ID)])
        self.assertEqual(self.lines(), ["Beep and Izumi of Nameless captured Tinfist."])

    def test_a_character_that_walks_into_a_cell_gives_no_event(self):
        world_events.take([imprisonment(TINFIST, at(1, 10))])
        self.assertEqual(self.events(), [])

    def test_a_load_drops_only_the_events_after_the_loaded_game_time(self):
        world_events.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), attack(IZUMI, KING, at(1, 11))])
        world_events.take([knockout(IZUMI, at(1, 10, 30)), death(KING, at(1, 10, 40)), imprisonment(TINFIST, at(1, 12))])
        self.assertEqual(self.events(), [("capture", "h:1", TINFIST_ID)])

    def test_a_carry_across_a_save_and_a_load_keeps_its_captors(self):
        world_events.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), up(TINFIST, at(1, 10, 30), carried=True)])
        world_events.take([knockout(TINFIST, at(1, 10, 20)), up(TINFIST, at(1, 10, 30), carried=True), imprisonment(TINFIST, at(1, 18))])
        self.assertEqual(self.events(), [("capture", "h:1", TINFIST_ID)])

    def test_a_capture_counts_once_when_a_load_imprisons_the_prisoner_again(self):
        world_events.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), imprisonment(TINFIST, at(1, 12))])
        world_events.take([imprisonment(TINFIST, at(1, 12, 30)), imprisonment(TINFIST, at(1, 11, 59)), knockout(BEEP, at(1, 12)), imprisonment(TINFIST, at(1, 12))])
        self.assertEqual(self.events(), [("capture", "h:1", TINFIST_ID)])
        self.assertEqual(len(self.lines()), 1)

    def test_an_attack_by_another_faction_makes_no_event(self):
        world_events.take([attack(party("h:9", "Guard", "United Cities"), KING, at(1, 10)), death(KING, at(1, 10))])
        self.assertEqual(self.events(), [])


class EventTest(WorldEventsTestCase):
    def test_no_event_for_a_generic_character(self):
        self.kill([BEEP], bandit(1), at(1, 10))
        world_events.take([attack(BEEP, bandit(2), at(1, 10)), knockout(bandit(2), at(1, 10)), imprisonment(bandit(2), at(1, 11))])
        self.assertEqual(self.events(), [])

    def test_no_event_for_a_victim_in_the_players_faction(self):
        self.kill([BEEP], IZUMI, at(1, 10))
        self.assertEqual(self.events(), [])

    def test_a_generic_character_with_a_canon_template_is_the_known_figure(self):
        self.kill([BEEP], TINFIST, at(1, 10))
        self.assertEqual(self.events(), [("kill", "h:1", TINFIST_ID)])
        self.assertEqual(self.lines(), ["Beep of Nameless killed Tinfist."])

    def test_a_unique_character_outside_the_canon_is_a_known_figure(self):
        self.kill([BEEP], party("u:9-other.mod", "Mod Boss"), at(1, 10))
        self.assertEqual(self.lines(), ["Beep of Nameless killed Mod Boss."])

    def test_a_generic_character_with_a_profile_is_no_known_figure(self):
        campaign_db.upsert_profile("h:1001", {"Name": "Dust Bandit Josh"})
        self.kill([BEEP], bandit(1), at(1, 10))
        self.assertEqual(self.lines(), [])

    def test_a_line_takes_the_current_name(self):
        self.kill([BEEP, IZUMI], TINFIST, at(1, 10))
        campaign_db.upsert_profile("h:1", {"Name": "Beepy"})
        self.assertEqual(self.lines(), ["Beepy and Izumi of Nameless killed Tinfist."])

    def test_a_new_captor_gets_a_capture_of_a_known_figure_that_another_captured(self):
        world_events.take([attack(BEEP, TINFIST, at(1, 10)), imprisonment(TINFIST, at(1, 11))])
        world_events.take([attack(BEEP, TINFIST, at(1, 12)), attack(IZUMI, TINFIST, at(1, 12)), imprisonment(TINFIST, at(1, 13))])
        self.assertEqual(self.events(), [("capture", "h:1", TINFIST_ID), ("capture", "h:2", TINFIST_ID)])
        self.assertEqual(self.lines(), ["Izumi of Nameless captured Tinfist.", "Beep of Nameless captured Tinfist."])

    def test_each_squad_member_lists_its_known_figures(self):
        self.kill([BEEP], TINFIST, at(1))
        world_events.take([attack(BEEP, KING, at(2)), attack(IZUMI, KING, at(2)), imprisonment(KING, at(2, 1))])
        self.assertEqual(world_events.character_events(), {"h:1": ["Killed Tinfist", "Captured Dust King"], "h:2": ["Captured Dust King"]})

    def test_a_cull_deletes_the_later_events_and_their_rumors(self):
        self.kill([BEEP], KING, at(1))
        self.kill([BEEP], TINFIST, at(3))
        campaign_db.save_rumor(None, world_events.events()[0]["id"], "Beep killed Tinfist.")
        self.assertEqual(campaign_db.cull_after(2, 0, 0), {"dialogue": 0, "rumor": 1, "event": 1})
        self.assertEqual(self.lines(), ["Beep of Nameless killed Dust King."])
        self.assertEqual(campaign_db.rumors(), [])


class CustomEventTest(WorldEventsTestCase):
    def test_a_custom_event_shows_as_custom_and_lists_for_no_squad_member(self):
        self.kill([BEEP], TINFIST, at(1))
        campaign_db.add_custom_event("They say Beep freed the slaves of Rebirth.")
        self.assertEqual([(event["time"], event["line"], event["rumor"] is not None) for event in world_events.events()],
                         [("-", "Written by you", True), ("Day 1, 00:00", "Beep of Nameless killed Tinfist.", False)])
        self.assertEqual(world_events.character_events(), {"h:1": ["Killed Tinfist"]})

    def test_the_facts_of_a_custom_event_leave_the_event_to_the_rumor_so_far(self):
        event_id = campaign_db.add_custom_event("They say Beep freed the slaves of Rebirth.")
        self.assertEqual(rumors.facts(*campaign_db.event(event_id)), "The player's faction: Nameless.\nThe event: The one that the rumor so far tells.")


class RumorTest(WorldEventsTestCase):
    def event(self):
        return campaign_db.event(world_events.events()[0]["id"])

    def test_the_facts_of_a_known_figure_tell_who_it_is_and_who_fears_the_news(self):
        self.kill([BEEP, IZUMI], TINFIST, at(40, 3, 10))
        campaign_db.upsert_profile("h:1", {"Name": "Beep", "Race": "Hive Worker Drone", "Sex": "Male", "Backstory": "Worked in a mine. Then fled."})
        self.assertEqual(rumors.facts(*self.event()),
                         "The player's faction: Nameless.\nThe event: Beep and Izumi of Nameless killed Tinfist of the Anti-Slavers.\nTime: Day 40, 03:10.\n"
                         "Who they are:\n- Tinfist (Skeleton, no sex): Leader of the Anti-Slavers.\n- Beep (male Hive Worker Drone): Worked in a mine.\nThe factions:\n- Anti-Slavers. Enemies: The Holy Nation, Slave Traders.")

    def test_the_prompt_holds_the_instruction_the_facts_and_the_rumor_so_far(self):
        self.kill([BEEP], TINFIST, at(1))
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(prompts, "USER_PROMPTS_DIR", empty), mock.patch.object(rumors, "load_settings", return_value={"language": "English"}):
            text = rumors.prompt(*self.event(), "Beep is the Stickman of the Dust.", "Beep killed Tinfist.")
        self.assertIn("PLAYER INSTRUCTIONS: Beep is the Stickman of the Dust.", text)
        self.assertIn("The event: Beep of Nameless killed Tinfist of the Anti-Slavers.", text)
        self.assertIn("RUMOR SO FAR:\nBeep killed Tinfist.", text)
        self.assertEqual(campaign_db.rumors(), [])

    def test_the_text_loses_quotes_bullets_and_line_breaks(self):
        self.assertEqual(rumors.clean('- "They say Beep\nkilled Tinfist."'), "They say Beep killed Tinfist.")


class AutoRumorTest(WorldEventsTestCase):
    def memory(self, day, text="{u:longen} sold water."):
        thread_id = campaign_db.join_thread(None, [("u:longen", "speaker", False)], at(day), "Bar, Squin")
        campaign_db.append_dialogue("u:longen", [(f"[Day {day}, 00:00] Longen: Water.", "u:longen")], {}, thread_id)
        campaign_db.set_memory(thread_id, text, at(day))
        return thread_id

    def pool(self):
        return [(memory["id"], memory["passes"]) for memory in campaign_db.rumor_pool(rumors.AUTO_POOL)]

    def test_a_pass_waits_for_a_new_memory_and_for_the_memories_and_the_rumors_of_the_events(self):
        self.assertIsNone(rumors.auto_pool())
        first = self.memory(1)
        self.assertEqual([memory["id"] for memory in rumors.auto_pool()], [first])
        pending = campaign_db.join_thread(None, [("u:longen", "speaker", False)], at(2))
        campaign_db.append_dialogue("u:longen", [("[Day 2, 00:00] Longen: More water.", "u:longen")], {}, pending)
        self.assertIsNone(rumors.auto_pool())
        campaign_db.set_memory(pending, "Longen sold more water.", at(2))
        self.kill([BEEP], TINFIST, at(3))
        self.assertIsNone(rumors.auto_pool())
        campaign_db.save_rumor(None, world_events.events()[0]["id"], "Beep killed Tinfist.")
        self.assertEqual([memory["id"] for memory in rumors.auto_pool()], [first, pending])
        campaign_db.count_rumor_pass([first, pending])
        self.assertIsNone(rumors.auto_pool())

    def test_the_prompt_labels_each_memory_with_its_time_its_place_and_the_current_names(self):
        self.memory(1)
        campaign_db.upsert_profile("u:longen", {"Name": "Lord Longen"})
        campaign_db.add_custom_event("They say Beep freed the slaves of Rebirth.")
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(prompts, "USER_PROMPTS_DIR", empty), mock.patch.object(rumors, "load_settings", return_value={"language": "English"}):
            text = rumors.auto_prompt(campaign_db.rumor_pool(rumors.AUTO_POOL))
        self.assertIn("The player's faction: Nameless.", text)
        self.assertIn("MEMORIES:\n[1] (Day 1, 00:00; Bar, Squin) Lord Longen sold water.", text)
        self.assertIn("RUMORS ALREADY TOLD:\n- They say Beep freed the slaves of Rebirth.", text)

    def test_a_reply_cites_the_memories_by_their_labels(self):
        memories = [{"id": 12}, {"id": 15}, {"id": 19}]
        self.assertEqual(rumors.auto_reply({"rumor": '"Word is that Longen sells water."', "memories": [3, "1", "[3]", 7]}, memories), ("Word is that Longen sells water.", [19, 12]))
        self.assertEqual(rumors.auto_reply({"rumor": "", "memories": [1]}, memories), ("", []))
        self.assertEqual(rumors.auto_reply({"rumor": None}, memories), ("", []))
        self.assertIsNone(rumors.auto_reply({"rumor": "Word is that Longen sells water.", "memories": [7]}, memories))
        self.assertIsNone(rumors.auto_reply({"memories": [1]}, memories))
        self.assertIsNone(rumors.auto_reply(None, memories))

    def test_a_rumor_takes_its_memories_out_of_the_pool_and_the_others_count_the_pass(self):
        _, read, cited = self.memory(1), self.memory(2), self.memory(3)
        pool = campaign_db.rumor_pool(2)
        rumors.keep_auto_rumor({"rumor": "Word in Squin is that Longen sells water.", "memories": [2]}, pool, state.ACTIVE_CAMPAIGN)
        self.assertEqual([(event["kind"], event["time"], event["line"], event["rumor"] is not None) for event in world_events.events()], [("auto", "Day 3, 00:00", "From 1 conversation", True)])
        self.assertEqual(self.pool(), [(read, 1)])

    def test_an_empty_rumor_counts_each_memory_that_the_pass_read(self):
        first = self.memory(1)
        rumors.keep_auto_rumor({"rumor": "", "memories": []}, campaign_db.rumor_pool(rumors.AUTO_POOL), state.ACTIVE_CAMPAIGN)
        self.assertEqual((campaign_db.events(), self.pool()), ([], [(first, 1)]))

    def test_a_reply_that_is_not_valid_or_a_campaign_switch_changes_nothing(self):
        first = self.memory(1)
        pool = campaign_db.rumor_pool(rumors.AUTO_POOL)
        with self.assertLogs(level="WARNING"):
            rumors.keep_auto_rumor({"rumor": "Word is that Longen sells water.", "memories": []}, pool, state.ACTIVE_CAMPAIGN)
        rumors.keep_auto_rumor({"rumor": "Word is that Longen sells water.", "memories": [1]}, pool, "another campaign")
        self.assertEqual((campaign_db.events(), self.pool()), ([], [(first, 0)]))

    def test_an_auto_event_lists_for_no_squad_member_and_its_rumor_is_its_event(self):
        self.kill([BEEP], TINFIST, at(1))
        event_id = campaign_db.add_auto_event("Word in Squin is that Longen sells water.", [self.memory(2), self.memory(3)])
        self.assertEqual(world_events.events()[0]["line"], "From 2 conversations")
        self.assertEqual(world_events.character_events(), {"h:1": ["Killed Tinfist"]})
        self.assertEqual(rumors.facts(*campaign_db.event(event_id)), "The player's faction: Nameless.\nThe event: The one that the rumor so far tells.\nTime: Day 3, 00:00.")


class LineTest(unittest.TestCase):
    def test_names_join_with_and(self):
        self.assertEqual(world_events.name_list(["Beep"]), "Beep")
        self.assertEqual(world_events.name_list(["Beep", "Izumi"]), "Beep and Izumi")
        self.assertEqual(world_events.name_list(["Beep", "Izumi", "Hamut"]), "Beep, Izumi, and Hamut")


if __name__ == "__main__":
    unittest.main()
