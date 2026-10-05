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
    "characters": [{"game_id": "tinfist", "profile": {"Name": "Tinfist", "Race": "Skeleton", "Sex": "Other", "Backstory": "Leader of the Anti-Slavers. Once a slave."}}],
    "entities": [{"category": "races", "id": "bonedog", "data": {"name": "Bonedog", "aliases": ["Bonedog (white)"]}}],
}


def party(npc_id, name, faction="Dust Bandits", player=False, race="Greenlander", animal=False, template_id=""):
    return {"id": npc_id, "template_id": template_id, "name": name, "faction": faction, "player": player, "race": race, "animal": animal}


BEEP = party("h:1", "Beep", "Nameless", player=True, race="Hive Worker Drone")
IZUMI = party("h:2", "Izumi", "Nameless", player=True, race="Scorchlander")
TINFIST = party("h:3", "Tinfist", "Anti-Slavers", race="Skeleton", template_id="tinfist")


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


def bandit(number, faction="Dust Bandits", race="Greenlander", animal=False):
    return party(f"h:{1000 + number}", "Dust Bandit", faction, race=race, animal=animal)


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
        with campaign_db._connect() as conn:
            return conn.execute("SELECT kind, doer_id, victim_id FROM deed ORDER BY id").fetchall()

    def lines(self):
        return [event["line"] for event in deeds.notable_events()]

    def kill(self, doers, victim, minutes):
        deeds.take([attack(doer, victim, minutes) for doer in doers] + [death(victim, minutes)])


class AttributionTest(WorldEventsTestCase):
    def test_a_death_gives_a_kill_to_each_attacker_of_the_last_3_game_hours(self):
        first, second = bandit(1), bandit(2)
        deeds.take([attack(BEEP, first, at(1, 10)), attack(IZUMI, first, at(1, 11)), death(first, at(1, 13))])
        deeds.take([attack(BEEP, second, at(1, 14)), death(second, at(1, 17, 1))])
        self.assertEqual(self.deeds(), [("kill", "h:1", first["id"]), ("kill", "h:2", first["id"])])

    def test_a_knocked_out_character_keeps_its_attackers(self):
        victim = bandit(1)
        deeds.take([attack(BEEP, victim, at(1, 10)), knockout(victim, at(1, 10, 1)), death(victim, at(1, 20))])
        self.assertEqual(self.deeds(), [("kill", "h:1", victim["id"])])

    def test_an_up_that_is_not_carried_ends_the_knockout_and_restarts_the_clock(self):
        first, second = bandit(1), bandit(2)
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
        victim = bandit(1)
        deeds.take([attack(BEEP, TINFIST, at(1, 10)), knockout(TINFIST, at(1, 10, 1)), attack(IZUMI, victim, at(1, 11))])
        deeds.take([knockout(IZUMI, at(1, 10, 30)), death(victim, at(1, 10, 40)), imprisonment(TINFIST, at(1, 12))])
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
        victim = bandit(1)
        deeds.take([attack(party("h:9", "Guard", "United Cities"), victim, at(1, 10)), death(victim, at(1, 10))])
        self.assertEqual(self.deeds(), [])


class DeedTest(WorldEventsTestCase):
    def test_no_deed_for_the_capture_of_a_generic_character(self):
        victim = bandit(1)
        deeds.take([attack(BEEP, victim, at(1, 10)), knockout(victim, at(1, 10)), imprisonment(victim, at(1, 11))])
        self.assertEqual(self.deeds(), [])

    def test_no_deed_for_a_victim_in_the_players_faction(self):
        self.kill([BEEP], IZUMI, at(1, 10))
        self.assertEqual(self.deeds(), [])

    def test_a_generic_character_with_a_canon_template_is_the_known_figure(self):
        self.kill([BEEP], TINFIST, at(1, 10))
        self.assertEqual(self.deeds(), [("kill", "h:1", TINFIST_ID)])
        self.assertEqual(self.lines(), ["Beep of Nameless killed Tinfist."])

    def test_a_character_that_the_server_added_is_no_known_figure(self):
        campaign_db.upsert_profile("h:1001", {"Name": "Dust Bandit Josh"})
        self.kill([BEEP], bandit(1), at(1, 10))
        self.assertEqual(self.lines(), [])
        self.assertFalse(campaign_db.known_figure("h:1001"))

    def test_a_line_takes_the_current_name(self):
        self.kill([BEEP, IZUMI], TINFIST, at(1, 10))
        campaign_db.upsert_profile("h:1", {"Name": "Beepy"})
        self.assertEqual(self.lines(), ["Beepy and Izumi of Nameless killed Tinfist."])


class CountTest(WorldEventsTestCase):
    def kill_many(self, doers, count, start, **victim):
        for number in range(count):
            self.kill(doers, bandit(start + number, **victim), at(1) + start + number)

    def test_a_count_shows_from_25_kills_and_moves_up_only_at_a_new_step(self):
        self.kill_many([BEEP], 24, 0)
        self.assertEqual(self.lines(), [])
        self.kill_many([BEEP], 1, 24)
        self.kill_many([BEEP], 1, 25)
        (event,) = deeds.notable_events()
        self.assertEqual((event["line"], event["time"]), ("Beep has killed 26 members of the Dust Bandits.", "Day 1, 00:24"))
        self.kill_many([BEEP], 74, 26)
        (event,) = deeds.notable_events()
        self.assertEqual((event["line"], event["time"]), ("Beep has killed 100 members of the Dust Bandits.", "Day 1, 01:39"))

    def test_kills_count_by_faction_and_an_animal_by_its_race_entry(self):
        self.kill_many([BEEP], 25, 0, faction="The Holy Nation")
        self.kill_many([BEEP], 12, 100, faction="Wolves", race="Bonedog (white)", animal=True)
        self.kill_many([BEEP], 13, 200, faction="Wolves", race="Bonedog", animal=True)
        self.assertEqual(self.lines(), ["Beep has killed 25 Bonedogs.", "Beep has killed 25 members of The Holy Nation."])

    def test_an_alias_joins_the_earlier_kills_of_a_variant(self):
        self.kill_many([BEEP], 25, 0, faction="Wolves", race="Bonedog (yellow)", animal=True)
        self.assertEqual(self.lines(), ["Beep has killed 25 Bonedog (yellow)s."])
        campaign_db.save_record("entity", ("races", "bonedog"), {"name": "Bonedog", "aliases": ["Bonedog (white)", "Bonedog (yellow)"]},
                                campaign_db.list_records("entity")[0][3])
        self.kill_many([BEEP], 1, 25, faction="Wolves", race="Bonedog", animal=True)
        self.assertEqual(self.lines(), ["Beep has killed 26 Bonedogs."])

    def test_each_attacker_of_a_death_counts_it(self):
        self.kill_many([BEEP, IZUMI], 25, 0)
        self.assertEqual(sorted(self.lines()), ["Beep has killed 25 members of the Dust Bandits.", "Izumi has killed 25 members of the Dust Bandits."])

    def test_a_known_figure_does_not_count(self):
        self.kill_many([BEEP], 24, 0, faction="Anti-Slavers")
        self.kill([BEEP], TINFIST, at(2))
        self.assertEqual(self.lines(), ["Beep of Nameless killed Tinfist."])

    def test_each_squad_member_lists_its_kills_and_known_figures(self):
        self.kill_many([BEEP], 3, 0)
        self.kill_many([BEEP], 2, 100, faction="Wolves", race="Bonedog (white)", animal=True)
        self.kill([BEEP], TINFIST, at(2))
        self.assertEqual(deeds.character_deeds(), {"h:1": {"kills": ["3 members of the Dust Bandits", "2 Bonedogs"], "figures": ["Killed Tinfist"]}})

    def test_a_cull_deletes_the_later_deeds_and_puts_a_count_back_a_step(self):
        self.kill_many([BEEP], 25, 0)
        for number in range(75):
            self.kill([BEEP], bandit(100 + number), at(3) + number)
        self.kill([BEEP], TINFIST, at(3, 5))
        self.assertEqual(campaign_db.cull_after(2, 0, 0), {"dialogue": 0, "deed": 76, "notable": 1, "rumor": 0})
        (event,) = deeds.notable_events()
        self.assertEqual((event["line"], event["time"]), ("Beep has killed 25 members of the Dust Bandits.", "Day 1, 00:24"))
        self.assertEqual(campaign_db.cull_after(1, 0, 10), {"dialogue": 0, "deed": 14, "notable": 1, "rumor": 0})
        self.assertEqual(self.lines(), [])


class RumorTest(WorldEventsTestCase):
    def notable(self, kind):
        return next(campaign_db.notable(event["id"]) for event in deeds.notable_events() if event["kind"] == kind)

    def test_the_facts_of_a_count_tell_its_step_not_its_number(self):
        for number in range(30):
            self.kill([BEEP], bandit(number), at(1) + number)
        campaign_db.upsert_profile("h:1", {"Name": "Beep", "Race": "Hive Worker Drone", "Sex": "Male", "Backstory": "Worked in a mine. Then fled."})
        self.assertEqual(rumors.facts(*self.notable("count")),
                         "The player's faction: Nameless.\nThe deed: Beep of Nameless has killed dozens of members of the Dust Bandits.\nTime: Day 1, 00:24.\n"
                         "Who they are:\n- Beep (male Hive Worker Drone): Worked in a mine.")

    def test_the_facts_of_a_known_figure_tell_who_it_is_and_who_fears_the_news(self):
        self.kill([BEEP, IZUMI], TINFIST, at(40, 3, 10))
        self.assertEqual(rumors.facts(*self.notable("figure")),
                         "The player's faction: Nameless.\nThe deed: Beep and Izumi of Nameless killed Tinfist of the Anti-Slavers.\nTime: Day 40, 03:10.\n"
                         "Who they are:\n- Tinfist (Skeleton, no sex): Leader of the Anti-Slavers.\nThe factions:\n- Anti-Slavers. Enemies: The Holy Nation, Slave Traders.")

    def test_the_prompt_holds_the_instruction_the_facts_and_the_rumor_so_far(self):
        self.kill([BEEP], TINFIST, at(1))
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(prompts, "USER_PROMPTS_DIR", empty), mock.patch.object(rumors, "load_settings", return_value={"language": "English"}):
            text = rumors.prompt(*self.notable("figure"), "Beep is the Stickman of the Dust.", "Beep killed Tinfist.")
        self.assertIn("PLAYER INSTRUCTIONS: Beep is the Stickman of the Dust.", text)
        self.assertIn("The deed: Beep of Nameless killed Tinfist of the Anti-Slavers.", text)
        self.assertIn("RUMOR SO FAR:\nBeep killed Tinfist.", text)
        self.assertEqual(campaign_db.rumors(), [])

    def test_a_count_that_reaches_a_new_step_after_its_rumor_shows_as_grown(self):
        for number in range(25):
            self.kill([BEEP], bandit(number), at(1) + number)
        campaign_db.save_rumor(None, deeds.notable_events()[0]["id"], "Beep kills bandits.")
        for number in range(75):
            self.kill([BEEP], bandit(100 + number), at(2) + number)
        (event,) = deeds.notable_events()
        self.assertEqual((event["rumor"] is not None, event["grown"]), (True, "more than a hundred"))
        campaign_db.save_rumor(event["rumor"], None, "Beep kills more bandits.")
        self.assertIsNone(deeds.notable_events()[0]["grown"])

    def test_the_text_loses_quotes_bullets_and_line_breaks(self):
        self.assertEqual(rumors.clean('- "They say Beep\nkilled Tinfist."'), "They say Beep killed Tinfist.")


class LineTest(unittest.TestCase):
    def test_a_faction_is_named_by_its_members(self):
        self.assertEqual(deeds.members_of("Dust Bandits"), "members of the Dust Bandits")
        self.assertEqual(deeds.members_of("The Holy Nation"), "members of The Holy Nation")

    def test_an_animal_race_is_plural(self):
        self.assertEqual(deeds.plural("Beak Thing"), "Beak Things")
        self.assertEqual(deeds.plural("Blood Spiders"), "Blood Spiders")

    def test_names_join_with_and(self):
        self.assertEqual(deeds.name_list(["Beep"]), "Beep")
        self.assertEqual(deeds.name_list(["Beep", "Izumi"]), "Beep and Izumi")
        self.assertEqual(deeds.name_list(["Beep", "Izumi", "Hamut"]), "Beep, Izumi, and Hamut")


if __name__ == "__main__":
    unittest.main()
