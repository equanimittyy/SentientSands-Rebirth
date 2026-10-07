import glob
import json
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import rumors
from core import bounties, deeds, state
from core.paths import WORLD_TEMPLATES_DIR
from store import campaign_db

DUST_BANDITS = "200-gamedata.base"
SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "",
    "factions": [{"faction_id": DUST_BANDITS, "name": "Dust Bandits", "aliases": [], "major": False, "fields": {"enemies": ["United Cities"]}, "description": ""}],
    "history": [],
    "characters": [],
    "entities": [],
}
BEEP = {"id": "h:100", "template_id": "", "name": "Beep", "faction": "Nameless", "player": True}


def candidate(serial, faction_id=DUST_BANDITS, faction="Dust Bandits"):
    return {"npc_id": f"h:{serial}", "name": "Dust Bandit", "faction": faction, "faction_id": faction_id, "place": "Stack"}


def when(minutes):
    return {"day": minutes // 1440, "hour": minutes % 1440 // 60, "minute": minutes % 60}


class FactionTest(unittest.TestCase):
    def test_each_issuer_and_target_is_a_faction_of_the_vanilla_template_by_its_name(self):
        names = {}
        for path in glob.glob(os.path.join(WORLD_TEMPLATES_DIR, "kenshi_ssr_vanilla", "factions", "*.json")):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            names[data["game_id"]] = data["name"]
        for factions in (bounties.ISSUERS, bounties.TARGETS):
            self.assertEqual({game_id: names.get(game_id) for game_id in factions}, factions)


class ReasonTest(unittest.TestCase):
    def test_each_reason_names_a_crime_of_the_game_and_has_a_text_of_its_own(self):
        self.assertLessEqual({reason["crime"] for reason in bounties.REASONS}, set(bounties.CRIMES))
        self.assertEqual(len({reason["text"] for reason in bounties.REASONS}), len(bounties.REASONS))


class RollTest(unittest.TestCase):
    def test_only_a_member_of_a_target_faction_without_an_open_bounty_is_the_target(self):
        candidates = [candidate(1, "1083-gamedata.base", "The Holy Nation"), candidate(2), candidate(3)]
        for seed in range(20):
            self.assertEqual(bounties.roll(candidates, {"h:2"}, rng=random.Random(seed))["target"]["npc_id"], "h:3")
        self.assertIsNone(bounties.roll(candidates[:2], {"h:2"}))
        self.assertIsNone(bounties.roll([], set()))

    def test_the_reason_gives_the_crime_and_the_amount_is_in_the_range_in_steps_of_100(self):
        for seed in range(50):
            bounty = bounties.roll([candidate(1)], set(), rng=random.Random(seed))
            self.assertIn({"crime": bounty["crime"], "text": bounty["reason"]}, bounties.REASONS)
            self.assertTrue(2000 <= bounty["amount"] <= 15000 and bounty["amount"] % 100 == 0)
        self.assertEqual(bounties.roll([candidate(1)], set(), 4300)["amount"], 4300)

    def test_each_combat_skill_gets_a_bonus_within_2_levels_of_the_level_of_the_amount(self):
        for amount, level in ((2000, 4), (6000, 12), (10000, 20), (15000, 20)):
            for seed in range(20):
                bonuses = bounties.skill_bonuses(amount, random.Random(seed))
                self.assertEqual(set(bonuses), set(bounties.COMBAT_STATS))
                self.assertTrue(all(level - 2 <= bonus <= level + 2 for bonus in bonuses.values()))
        self.assertTrue(all(bonus >= 0 for bonus in bounties.skill_bonuses(500, random.Random(1)).values()))

    def test_a_scan_is_due_after_the_timer_while_fewer_bounties_are_open_than_the_setting_allows(self):
        self.assertTrue(bounties.due(7200, 120, 2, 3))
        self.assertFalse(bounties.due(7199, 120, 2, 3))
        self.assertFalse(bounties.due(7200, 120, 3, 3))
        self.assertFalse(bounties.due(7200, 120, 0, 0))


@mock.patch.object(deeds, "send_to_pipe")
@mock.patch.object(bounties, "send_to_pipe")
class BountyDeedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)
        campaign_db.note_faction("204-gamedata.base", "Nameless", is_player=True)
        self._campaign, self._player = state.ACTIVE_CAMPAIGN, state.PLAYER_CONTEXT
        state.ACTIVE_CAMPAIGN, state.PLAYER_CONTEXT = self.id(), when(100)

    def tearDown(self):
        state.ACTIVE_CAMPAIGN, state.PLAYER_CONTEXT = self._campaign, self._player
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def place(self, serial, squad="0-5-6-7-8", persistent=False, expires=100000, amount=3200):
        bounty = bounties.roll([candidate(serial)], set(), amount, random.Random(serial))
        bounties.send(bounty)
        taken = bounties.take_pending(f"h:{serial}")
        return bounties.store(taken, f"Arleen {serial}", {"context": {"npc_id": f"h:{serial}", **when(90)}, "squad": squad, "persistent": persistent, "expires": expires})

    def statuses(self):
        return [(event["line"], event["status"]) for event in deeds.notable_events() if event["kind"] == "bounty"]

    def kill(self, serial, minutes):
        victim = {"id": f"h:{serial}", "template_id": "", "name": "Arleen", "faction": "Dust Bandits", "player": False}
        deeds.take([{"kind": "attack", "attacker": BEEP, "target": victim["id"], **when(minutes)}, {"kind": "death", "party": victim, **when(minutes)}])

    def test_place_bounty_carries_the_serial_the_crime_the_amount_the_issuers_and_the_bonuses(self, place_pipe, end_pipe):
        bounty = bounties.roll([candidate(77)], set(), 3200, random.Random(1))
        bounties.send(bounty)
        serial, crime, amount, issuers, bonuses = place_pipe.call_args[0][0].removeprefix("PLACE_BOUNTY: ").split("|")
        self.assertEqual((serial, bounties.CRIMES[int(crime) - 1], amount, issuers.split(",")), ("77", bounty["crime"], "3200", list(bounties.ISSUERS)))
        self.assertEqual(dict(map(int, pair.split(":")) for pair in bonuses.split(",")), bounty["bonuses"])

    def test_the_result_of_a_placement_counts_once_and_not_after_a_campaign_switch(self, place_pipe, end_pipe):
        bounties.send(bounties.roll([candidate(1)], set()))
        self.assertIsNone(bounties.take_pending("h:2"))
        self.assertIsNone(bounties.take_pending("h:1"))
        bounties.send(bounties.roll([candidate(1)], set()))
        state.ACTIVE_CAMPAIGN = "Other"
        self.assertIsNone(bounties.take_pending("h:1"))

    def test_a_bounty_has_no_deed_line_and_is_open_until_it_expires(self, place_pipe, end_pipe):
        notable_id = self.place(1, expires=200)
        deed = campaign_db.notable(notable_id)
        self.assertEqual(deed[0], 90)
        self.assertEqual({key: deed[1][key] for key in ("target", "amount", "place", "squad", "persistent")},
                         {"target": {"id": "h:1", "name": "Arleen 1", "faction": "Dust Bandits"}, "amount": 3200, "place": "Stack", "squad": "0-5-6-7-8", "persistent": False})
        self.assertEqual(self.statuses(), [("Unknown", "Open")])
        state.PLAYER_CONTEXT = when(201)
        self.assertEqual(self.statuses(), [("Unknown", "Expired")])
        self.assertEqual(deeds.open_bounties(), [])

    def test_the_target_of_an_open_bounty_is_a_known_figure_and_its_kill_ends_the_bounty(self, place_pipe, end_pipe):
        self.place(1)
        self.kill(1, 150)
        self.assertEqual(self.statuses(), [("Unknown", "Killed")])
        self.assertEqual([event["kind"] for event in deeds.notable_events()], ["kill", "bounty"])
        end_pipe.assert_called_once_with("END_BOUNTY: 0-5-6-7-8|1")
        self.assertEqual(deeds.character_deeds(), {"h:100": ["Killed Arleen"]})

    def test_a_cull_of_the_kill_opens_the_bounty_again(self, place_pipe, end_pipe):
        self.place(1)
        self.kill(1, 150)
        campaign_db.cull_after(0, 2, 0)
        self.assertEqual(self.statuses(), [("Unknown", "Open")])

    def test_a_squad_that_another_open_bounty_holds_stays_and_keeps_the_flag_of_the_first_bounty(self, place_pipe, end_pipe):
        self.place(1, persistent=False)
        second = self.place(2, persistent=True)
        self.assertFalse(campaign_db.notable(second)[1]["persistent"])
        self.kill(1, 150)
        end_pipe.assert_not_called()
        self.kill(2, 160)
        end_pipe.assert_called_once_with("END_BOUNTY: 0-5-6-7-8|1")

    def test_a_squad_that_the_game_kept_keeps_its_flag(self, place_pipe, end_pipe):
        self.place(1, persistent=True)
        self.kill(1, 150)
        end_pipe.assert_called_once_with("END_BOUNTY: 0-5-6-7-8|0")

    def test_a_bounty_deed_can_be_deleted(self, place_pipe, end_pipe):
        self.assertTrue(campaign_db.delete_custom_deed(self.place(1)))
        self.assertEqual(deeds.notable_events(), [])

    def test_an_expired_bounty_ends_once(self, place_pipe, end_pipe):
        self.place(1, squad="a", expires=200)
        self.place(2, squad="b")
        state.PLAYER_CONTEXT = when(201)
        deeds.end_expired_bounties()
        deeds.end_expired_bounties()
        end_pipe.assert_called_once_with("END_BOUNTY: a|1")
        self.assertEqual(len(deeds.open_bounties()), 1)

    def test_the_rumor_takes_the_issuers_the_reason_the_profile_and_the_place(self, place_pipe, end_pipe):
        notable_id = self.place(1)
        campaign_db.upsert_profile("h:1", {"Name": "Arleen", "Race": "Greenlander", "Sex": "Female", "Personality": "Cold.", "Backstory": "Raised by raiders."})
        deed = campaign_db.notable(notable_id)[1]
        self.assertEqual(rumors.bounty_facts(*campaign_db.notable(notable_id)),
                         f"The bounty: The Holy Nation, the United Cities, and the Shek Kingdom each pay 3,200 cats for the wanted character.\n"
                         f"The crime ({rumors.CRIME_WORDS.get(deed['crime'], deed['crime'].lower())}): {deed['reason']}\n"
                         "The wanted character: Arleen (female Greenlander) of the Dust Bandits.\nPersonality: Cold.\nBackstory: Raised by raiders.\n"
                         "Last seen: Stack.\nTime: Day 0, 01:30.\nThe factions:\n- Dust Bandits. Enemies: United Cities.")

    def test_a_reply_needs_a_notice_a_rumor_and_a_short_alias(self, place_pipe, end_pipe):
        reply = {"notice": "WANTED: Arleen.", "rumor": '"They say Arleen is wanted."', "alias": "the Ore Butcher"}
        self.assertEqual(rumors.bounty_reply(reply), ("WANTED: Arleen.", "They say Arleen is wanted.", "the Ore Butcher"))
        for changes in ({"notice": ""}, {"rumor": ""}, {"alias": ""}, {"alias": None}, {"alias": "the one who killed the miners for ore"}):
            self.assertIsNone(rumors.bounty_reply({**reply, **changes}))
        self.assertIsNone(rumors.bounty_reply(None))

    def test_the_notice_is_the_line_of_the_bounty_and_comes_with_its_rumor(self, place_pipe, end_pipe):
        notable_id = self.place(1)
        self.assertTrue(campaign_db.add_bounty_rumor(notable_id, "WANTED: Arleen.", "They say Arleen is wanted."))
        self.assertFalse(campaign_db.add_bounty_rumor(notable_id, "WANTED again.", "Again."))
        self.assertEqual(self.statuses(), [("WANTED: Arleen.", "Open")])
        self.assertEqual([rumor["text"] for rumor in campaign_db.rumors()], ["They say Arleen is wanted."])

    def test_an_alias_never_overwrites_one_that_the_profile_holds(self, place_pipe, end_pipe):
        campaign_db.upsert_profile("h:1", {"Name": "Arleen"})
        self.assertTrue(campaign_db.add_alias("h:1", "the Ore Butcher"))
        self.assertFalse(campaign_db.add_alias("h:1", "Red-Hand"))
        self.assertFalse(campaign_db.add_alias("h:9", "Red-Hand"))
        self.assertEqual(campaign_db.get_character("h:1")["Alias"], "the Ore Butcher")


if __name__ == "__main__":
    unittest.main()
