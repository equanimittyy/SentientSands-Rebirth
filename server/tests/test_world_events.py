import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import prompts, rumors
from core import deeds, state
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

    def deeds(self):
        return [(deed["deed"], doer["id"], deed["victim"]["id"]) for _, _, deed in reversed(campaign_db.notables()) for doer in deed["doers"]]

    def lines(self):
        return [event["line"] for event in deeds.notable_events()]

    def kill(self, doers, victim, minutes):
        deeds.take([attack(doer, victim, minutes) for doer in doers] + [death(victim, minutes)])


class AttributionTest(WorldEventsTestCase):
    def test_a_death_gives_a_kill_to_each_attacker_of_the_last_3_game_hours(self):
        deeds.take([attack(BEEP, KING, at(1, 10)), attack(IZUMI, KING, at(1, 11)), death(KING, at(1, 13))])
        deeds.take([attack(BEEP, LONGEN, at(1, 14)), death(LONGEN, at(1, 17, 1))])
        self.assertEqual(self.deeds(), [("kill", "h:1", KING["id"]), ("kill", "h:2", KING["id"])])

    def test_a_knocked_out_character_keeps_its_attackers(self):
        deeds.take([attack(BEEP, KING, at(1, 10)), knockout(KING, at(1, 10, 1)), death(KING, at(1, 20))])
        self.assertEqual(self.deeds(), [("kill", "h:1", KING["id"])])

    def test_an_up_that_is_not_carried_ends_the_knockout_and_restarts_the_clock(self):
        first, second = KING, LONGEN
        for victim, dies in ((first, at(1, 14, 30)), (second, at(1, 15, 1))):
            deeds.take([attack(BEEP, victim, at(1, 10)), knockout(victim, at(1, 10, 1)), up(victim, at(1, 12)), death(victim, dies)])
        self.assertEqual(self.deeds(), [("kill", "h:1", first["id"])])

    def test_a_carried_up_keeps_the_captors_of_the_knockout(self):
        deeds.take([attack(BEEP, TINFIST, at(1, 10)), attack(IZUMI, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)),
                    up(TINFIST, at(1, 10, 5), carried=True), imprisonment(TINFIST, at(2, 9))])
        self.assertEqual(self.deeds(), [("capture", "h:1", TINFIST_ID), ("capture", "h:2", TINFIST_ID)])
        self.assertEqual(self.lines(), ["Beep and Izumi of Nameless captured Tinfist."])

    def test_a_character_that_walks_into_a_cell_gives_no_deed(self):
        deeds.take([imprisonment(TINFIST, at(1, 10))])
        self.assertEqual(self.deeds(), [])

    def test_a_load_drops_only_the_events_after_the_loaded_game_time(self):
        deeds.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), attack(IZUMI, KING, at(1, 11))])
        deeds.take([knockout(IZUMI, at(1, 10, 30)), death(KING, at(1, 10, 40)), imprisonment(TINFIST, at(1, 12))])
        self.assertEqual(self.deeds(), [("capture", "h:1", TINFIST_ID)])

    def test_a_carry_across_a_save_and_a_load_keeps_its_captors(self):
        deeds.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), up(TINFIST, at(1, 10, 30), carried=True)])
        deeds.take([knockout(TINFIST, at(1, 10, 20)), up(TINFIST, at(1, 10, 30), carried=True), imprisonment(TINFIST, at(1, 18))])
        self.assertEqual(self.deeds(), [("capture", "h:1", TINFIST_ID)])

    def test_a_capture_counts_once_when_a_load_imprisons_the_prisoner_again(self):
        deeds.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), imprisonment(TINFIST, at(1, 12))])
        deeds.take([imprisonment(TINFIST, at(1, 12, 30)), imprisonment(TINFIST, at(1, 11, 59)), knockout(BEEP, at(1, 12)), imprisonment(TINFIST, at(1, 12))])
        self.assertEqual(self.deeds(), [("capture", "h:1", TINFIST_ID)])
        self.assertEqual(len(self.lines()), 1)

    def test_an_attack_by_another_faction_makes_no_deed(self):
        deeds.take([attack(party("h:9", "Guard", "United Cities"), KING, at(1, 10)), death(KING, at(1, 10))])
        self.assertEqual(self.deeds(), [])


class DeedTest(WorldEventsTestCase):
    def test_no_deed_for_a_generic_character(self):
        self.kill([BEEP], bandit(1), at(1, 10))
        deeds.take([attack(BEEP, bandit(2), at(1, 10)), knockout(bandit(2), at(1, 10)), imprisonment(bandit(2), at(1, 11))])
        self.assertEqual(self.deeds(), [])

    def test_no_deed_for_a_victim_in_the_players_faction(self):
        self.kill([BEEP], IZUMI, at(1, 10))
        self.assertEqual(self.deeds(), [])

    def test_a_generic_character_with_a_canon_template_is_the_known_figure(self):
        self.kill([BEEP], TINFIST, at(1, 10))
        self.assertEqual(self.deeds(), [("kill", "h:1", TINFIST_ID)])
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
        deeds.take([attack(BEEP, TINFIST, at(1, 10)), imprisonment(TINFIST, at(1, 11))])
        deeds.take([attack(BEEP, TINFIST, at(1, 12)), attack(IZUMI, TINFIST, at(1, 12)), imprisonment(TINFIST, at(1, 13))])
        self.assertEqual(self.deeds(), [("capture", "h:1", TINFIST_ID), ("capture", "h:2", TINFIST_ID)])
        self.assertEqual(self.lines(), ["Izumi of Nameless captured Tinfist.", "Beep of Nameless captured Tinfist."])

    def test_each_squad_member_lists_its_known_figures(self):
        self.kill([BEEP], TINFIST, at(1))
        deeds.take([attack(BEEP, KING, at(2)), attack(IZUMI, KING, at(2)), imprisonment(KING, at(2, 1))])
        self.assertEqual(deeds.character_deeds(), {"h:1": ["Killed Tinfist", "Captured Dust King"], "h:2": ["Captured Dust King"]})

    def test_a_cull_deletes_the_later_deeds_and_their_rumors(self):
        self.kill([BEEP], KING, at(1))
        self.kill([BEEP], TINFIST, at(3))
        campaign_db.save_rumor(None, deeds.notable_events()[0]["id"], "Beep killed Tinfist.")
        self.assertEqual(campaign_db.cull_after(2, 0, 0), {"dialogue": 0, "rumor": 1, "notable": 1})
        self.assertEqual(self.lines(), ["Beep of Nameless killed Dust King."])
        self.assertEqual(campaign_db.rumors(), [])


class CustomDeedTest(WorldEventsTestCase):
    def test_a_custom_deed_shows_its_text_and_lists_for_no_squad_member(self):
        self.kill([BEEP], TINFIST, at(1))
        campaign_db.add_custom_deed("Beep freed the slaves of Rebirth.")
        self.assertEqual([(event["time"], event["line"]) for event in deeds.notable_events()],
                         [("-", "Beep freed the slaves of Rebirth."), ("Day 1, 00:00", "Beep of Nameless killed Tinfist.")])
        self.assertEqual(deeds.character_deeds(), {"h:1": ["Killed Tinfist"]})

    def test_the_facts_of_a_custom_deed_are_its_text_with_no_time(self):
        notable_id = campaign_db.add_custom_deed("Beep freed the slaves of Rebirth.")
        self.assertEqual(rumors.facts(*campaign_db.notable(notable_id)), "The player's faction: Nameless.\nThe deed: Beep freed the slaves of Rebirth.")


class RumorTest(WorldEventsTestCase):
    def notable(self):
        return campaign_db.notable(deeds.notable_events()[0]["id"])

    def test_the_facts_of_a_known_figure_tell_who_it_is_and_who_fears_the_news(self):
        self.kill([BEEP, IZUMI], TINFIST, at(40, 3, 10))
        campaign_db.upsert_profile("h:1", {"Name": "Beep", "Race": "Hive Worker Drone", "Sex": "Male", "Backstory": "Worked in a mine. Then fled."})
        self.assertEqual(rumors.facts(*self.notable()),
                         "The player's faction: Nameless.\nThe deed: Beep and Izumi of Nameless killed Tinfist of the Anti-Slavers.\nTime: Day 40, 03:10.\n"
                         "Who they are:\n- Tinfist (Skeleton, no sex): Leader of the Anti-Slavers.\n- Beep (male Hive Worker Drone): Worked in a mine.\nThe factions:\n- Anti-Slavers. Enemies: The Holy Nation, Slave Traders.")

    def test_the_prompt_holds_the_instruction_the_facts_and_the_rumor_so_far(self):
        self.kill([BEEP], TINFIST, at(1))
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(prompts, "USER_PROMPTS_DIR", empty), mock.patch.object(rumors, "load_settings", return_value={"language": "English"}):
            text = rumors.prompt(*self.notable(), "Beep is the Stickman of the Dust.", "Beep killed Tinfist.")
        self.assertIn("PLAYER INSTRUCTIONS: Beep is the Stickman of the Dust.", text)
        self.assertIn("The deed: Beep of Nameless killed Tinfist of the Anti-Slavers.", text)
        self.assertIn("RUMOR SO FAR:\nBeep killed Tinfist.", text)
        self.assertEqual(campaign_db.rumors(), [])

    def test_the_text_loses_quotes_bullets_and_line_breaks(self):
        self.assertEqual(rumors.clean('- "They say Beep\nkilled Tinfist."'), "They say Beep killed Tinfist.")


class LineTest(unittest.TestCase):
    def test_names_join_with_and(self):
        self.assertEqual(deeds.name_list(["Beep"]), "Beep")
        self.assertEqual(deeds.name_list(["Beep", "Izumi"]), "Beep and Izumi")
        self.assertEqual(deeds.name_list(["Beep", "Izumi", "Hamut"]), "Beep, Izumi, and Hamut")


if __name__ == "__main__":
    unittest.main()
