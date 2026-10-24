import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import quests
from core import state, world_events
from store import campaign_db

UC = "defaultEmpireFactionSID"
BANDITS = "200-gamedata.base"
PLAYER = "204-gamedata.base"
OTHER = "1229-gamedata.base"


def faction(faction_id, name, aliases=(), **fields):
    return {"faction_id": faction_id, "name": name, "aliases": list(aliases), "major": False, "fields": fields, "description": ""}


SEED = {
    "template": {"name": "test", "version": "1.0.0", "hash": "abc"},
    "overview": "",
    "factions": [
        faction(UC, "United Cities", enemies=["Dust Bandits", "Anti-Slavers", "Nameless", "United Cities", "Fogmen", "Ninjas", "Northern Nobles"], leader="Emperor Tengu"),
        faction(BANDITS, "Dust Bandits", leader="Dust King"),
        faction("58229-Dialogue.mod", "Anti-Slavers", leader="Tinfist"),
        faction("18007-rebirth.mod", "Black Dragon Ninjas", aliases=["Ninjas"], leader="Dimak and Buzan"),
        faction("10-UC Warring Factions.mod", "Northern Nobles", nobles=["Lord Nagata", "Lady Sanda"]),
        faction(PLAYER, "Nameless"),
    ],
    "history": [],
    "characters": [{"game_id": game_id, "profile": {"Name": name}} for game_id, name in
                   (("tinfist", "Tinfist"), ("dust-king", "Dust King"), ("dimak", "Dimak"), ("buzan", "Buzan"), ("nagata", "Lord Nagata"), ("tengu", "Emperor Tengu"))],
    "entities": [],
}

LEADER = {"npc_id": "u:tengu", "faction": "United Cities", "factionID": UC, "relation": 60}
GUARD = {"npc_id": "h:7", "faction": "United Cities", "factionID": UC, "relation": 0}
SPEAKER = {"npc_id": "h:1", "inventory": []}
BEEP = {"id": "h:1", "template_id": "", "name": "Beep", "faction": "Nameless", "factionID": PLAYER, "player": True}
OUTSIDER = {"id": "h:9", "template_id": "", "name": "Hunter", "faction": "Hounds", "factionID": "48814-Dialogue.mod", "player": False}
TINFIST = {"id": "h:3", "template_id": "tinfist", "name": "Tinfist", "faction": "Anti-Slavers", "factionID": "58229-Dialogue.mod", "player": False}


def bandit(number):
    return {"id": f"h:{1000 + number}", "template_id": "", "name": "Dust Bandit", "faction": "Dust Bandits", "factionID": BANDITS, "player": False}


def when(minutes):
    return {"day": minutes // 1440, "hour": minutes % 1440 // 60, "minute": minutes % 60}


def attack(attacker, target, minutes):
    return {"kind": "attack", "attacker": attacker, "target": target["id"], **when(minutes)}


def killed(victim, minutes, attacker=BEEP):
    return [attack(attacker, victim, minutes), {"kind": "death", "party": victim, **when(minutes)}]


def captured(victim, minutes):
    return [attack(BEEP, victim, minutes), {"kind": "imprisonment", "party": victim, **when(minutes)}]


def first(items):
    return items[0]


def last(items):
    return items[-1]


def job(kind="faction", target=BANDITS, count=2, reward=1000, giver="h:7", giver_name="Sergeant Rook", giver_faction=UC):
    return {"giver": giver, "giver_name": giver_name, "giver_faction": giver_faction, "kind": kind, "target": target, "count": count, "reward": reward}


class QuestTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        campaign_db.open_campaign(self._tmp.name, lambda: SEED)
        campaign_db.note_faction(PLAYER, "Nameless", is_player=True)
        for name, value in (("ACTIVE_CAMPAIGN", self.id()), ("UNIQUE_STATES", []), ("LIVE_CONTEXTS", {}), ("PLAYER_CONTEXT", {"factionID": PLAYER})):
            patcher = mock.patch.object(state, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        campaign_db.close_campaign()
        self._tmp.cleanup()

    def take(self, events, now):
        return world_events.take(events, when(now))

    def states(self):
        return [(job["id"], job["state"], job["kills"]) for job in campaign_db.quests(("open", "done", "failed", "paid"))]


class RollTest(QuestTestCase):
    def test_a_leader_at_a_good_relation_gives_a_figure_or_a_faction_job_at_random(self):
        with mock.patch.object(quests.random, "choice", first):
            self.assertEqual(quests.roll(LEADER, "Emperor Tengu", {"leader"}, [])["kind"], "faction")
        with mock.patch.object(quests.random, "choice", last):
            made = quests.roll(LEADER, "Emperor Tengu", {"leader"}, [])
        self.assertEqual((made["kind"], made["giver"], made["giver_name"], made["giver_faction"]), ("figure", "u:tengu", "Emperor Tengu", UC))

    def test_below_the_relation_a_leader_gives_only_a_faction_job(self):
        self.assertIsNone(quests.figure_job({**LEADER, "relation": 59}))
        with mock.patch.object(quests.random, "choice", last):
            self.assertEqual(quests.roll({**LEADER, "relation": 59}, "Emperor Tengu", {"leader"}, [])["kind"], "faction")

    def test_a_guard_gives_a_faction_job_and_an_npc_without_a_role_gives_none(self):
        with mock.patch.object(quests.random, "choice", first), mock.patch.object(quests.random, "randint", return_value=5):
            made = quests.roll(GUARD, "Sergeant Rook", {"guard"}, [])
        self.assertEqual((made["kind"], made["target"], made["target_name"], made["count"], made["reward"]), ("faction", BANDITS, "Dust Bandits", 5, 2500))
        self.assertIsNone(quests.roll(GUARD, "Sergeant Rook", set(), []))

    def test_the_enemies_come_from_the_faction_record_by_name_or_alias(self):
        self.assertEqual([record["name"] for record in quests.enemies(LEADER)], ["Dust Bandits", "Anti-Slavers", "Black Dragon Ninjas", "Northern Nobles"])
        self.assertEqual(quests.enemies({"faction": "Nobody"}), [])

    def figures(self, npc=LEADER):
        offered = []
        with mock.patch.object(quests.random, "choice", lambda items: offered.append(items) or items[0]):
            quests.figure_job(npc)
        return {target["target"]: (target["target_name"], target["reward"], target["about"]) for target in (offered[0] if offered else [])}

    def test_the_targets_are_the_leaders_and_the_nobles_of_the_enemies_that_have_a_canon_record(self):
        self.assertEqual(self.figures(), {
            "u:dust-king": ("Dust King", 20000, "leader of the Dust Bandits"),
            "u:tinfist": ("Tinfist", 20000, "leader of the Anti-Slavers"),
            "u:dimak": ("Dimak", 20000, "leader of the Black Dragon Ninjas"),
            "u:buzan": ("Buzan", 20000, "leader of the Black Dragon Ninjas"),
            "u:nagata": ("Lord Nagata", 10000, "a noble of the Northern Nobles"),
        })

    def test_a_dead_imprisoned_recruited_or_taken_figure_drops_out(self):
        state.UNIQUE_STATES = [{"id": "dust-king", "name": "Dust King", "state": "dead"}, {"id": "dimak", "name": "Dimak", "state": "imprisoned"}]
        state.LIVE_CONTEXTS["u:buzan"] = {"factionID": PLAYER}
        campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:other"), 60)
        self.assertEqual(list(self.figures()), ["u:nagata"])
        campaign_db.add_quest(job("figure", "u:nagata", 1, 10000, giver="u:another", giver_faction=OTHER), 60)
        self.assertIsNone(quests.figure_job(LEADER))

    def test_a_trader_brings_a_material_of_its_class_for_twice_its_value(self):
        goods = [{"name": "Katana", "kind": "weapon"}, {"name": "Bolts", "kind": "ammo"}, {"name": "Bread", "kind": "food"}]
        with mock.patch.object(quests.random, "randint", return_value=5):
            made = quests.roll(GUARD, "Harvag", {"trader"}, goods)
        self.assertEqual((made["kind"], made["target"], made["count"], made["reward"]), ("goods", "Raw Iron", 5, 1500))

    def test_the_class_needs_half_of_the_item_stacks(self):
        food, weapon, armour, drug = ({"name": name, "kind": kind} for name, kind in (("Bread", "food"), ("Katana", "weapon"), ("Rags", "armour"), ("Sake", "drug")))
        self.assertEqual(quests.trader_materials([food, food, weapon]), ("Raw Meat", "Wheatstraw", "Greenfruit", "Cactus", "Riceweed"))
        self.assertEqual(quests.trader_materials([food, weapon]), quests.trader_materials([food]))
        self.assertEqual(quests.trader_materials([food, weapon, armour, drug]), ())
        self.assertIsNone(quests.goods_job([food, weapon, armour, drug]))
        self.assertEqual(quests.trader_materials([]), ())

    def test_the_hi_tech_junk_counts_as_electronics_by_its_name(self):
        junk = [{"name": "CPU Unit", "kind": "goods"}, {"name": "Motor", "kind": "goods"}, {"name": "Rock", "kind": "goods"}]
        self.assertEqual(quests.trader_materials(junk), ("Copper",))
        self.assertEqual(quests.trader_materials(junk[1:] + [{"name": "Stone", "kind": "goods"}]), ())

    def test_a_material_that_the_goods_hold_drops_out(self):
        goods = [{"name": "Katana", "kind": "weapon"}, {"name": "Raw Iron", "kind": "goods"}, {"name": "Bolts", "kind": "ammo"}]
        self.assertIsNone(quests.goods_job(goods))
        armour = [{"name": "Rags", "kind": "armour"}, {"name": "raw iron", "kind": "goods"}]
        with mock.patch.object(quests.random, "choice", first):
            self.assertEqual(quests.goods_job(armour)["target"], "Animal Skin")


class HeldTest(QuestTestCase):
    def test_a_giver_answers_for_its_own_job(self):
        quest_id = campaign_db.add_quest(job("goods", "Raw Iron", 5, 1500, giver="h:20", giver_name="Harvag", giver_faction="1229-gamedata.base"), 60)
        self.assertEqual(quests.held({"npc_id": "h:20"})["id"], quest_id)
        self.assertIsNone(quests.held({"npc_id": "h:21", "factionID": "1229-gamedata.base"}))

    def test_another_guard_or_the_leader_of_the_faction_answers_for_no_faction_job(self):
        quest_id = campaign_db.add_quest(job(giver="h:7"), 60)
        self.assertEqual(quests.held(GUARD)["id"], quest_id)
        self.assertIsNone(quests.held({"npc_id": "h:9", "factionID": UC}))
        self.assertIsNone(quests.held(LEADER))

    def test_a_held_job_stops_a_new_one_of_the_giver(self):
        self.assertIsNotNone(campaign_db.add_quest(job(), 60))
        self.assertIsNone(campaign_db.add_quest(job(target="58229-Dialogue.mod"), 70))

    def test_a_faction_gives_one_job_at_a_time(self):
        quest_id = campaign_db.add_quest(job(giver="h:7"), 60)
        self.assertTrue(quests.faction_held(LEADER))
        self.assertIsNone(quests.roll(LEADER, "Emperor Tengu", {"leader"}, []))
        self.assertIsNone(campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu"), 70))
        self.assertIsNotNone(campaign_db.add_quest(job(giver="h:8", giver_faction=OTHER), 70))
        goods = job("goods", "Raw Iron", 5, 1500, giver_faction="")
        self.assertIsNotNone(campaign_db.add_quest({**goods, "giver": "h:20"}, 70))
        self.assertIsNotNone(campaign_db.add_quest({**goods, "giver": "h:21"}, 70))
        campaign_db.set_quest_state(quest_id, "paid", 80, "open")
        self.assertFalse(quests.faction_held(LEADER))
        self.assertIsNotNone(campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu"), 90))


class CountTest(QuestTestCase):
    def test_each_kill_after_the_accept_counts_until_the_job_is_done(self):
        quest_id = campaign_db.add_quest(job(), 600)
        self.assertEqual(self.take(killed(bandit(1), 599), 605), [])
        self.assertEqual(self.take(killed(bandit(2), 610), 610), ["Job for Sergeant Rook: 1 of 2 members of the Dust Bandits killed."])
        self.assertEqual(self.take(killed(bandit(3), 620), 620), ["Job done: go back to Sergeant Rook for the reward."])
        self.assertEqual(self.take(killed(bandit(4), 630), 630), [])
        self.assertEqual(self.states(), [(quest_id, "done", 2)])

    def test_a_death_with_no_squad_attacker_counts_nothing(self):
        campaign_db.add_quest(job(), 600)
        self.assertEqual(self.take(killed(bandit(1), 610, OUTSIDER), 610), [])
        self.assertEqual(self.take([{"kind": "death", "party": bandit(2), **when(611)}], 611), [])
        self.assertEqual(campaign_db.quests()[0]["kills"], 0)

    def test_a_kill_counts_only_toward_the_oldest_open_job_against_the_faction(self):
        older = campaign_db.add_quest(job(giver="h:7"), 600)
        newer = campaign_db.add_quest(job(giver="h:8", giver_name="Sergeant Kane", giver_faction=OTHER), 601)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 611) + killed(bandit(3), 612), 612)
        self.assertEqual(self.states(), [(newer, "open", 1), (older, "done", 2)])

    def test_a_kill_or_a_capture_of_the_figure_after_the_accept_does_the_job(self):
        killing = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Emperor Tengu"), 600)
        self.assertEqual(self.take(killed(TINFIST, 590), 605), [])
        self.assertEqual(self.states(), [(killing, "open", 0)])
        self.assertEqual(self.take(killed(TINFIST, 610), 610), ["Job done: go back to Emperor Tengu for the reward."])
        capture = campaign_db.add_quest(job("figure", "u:dust-king", 1, 20000, giver="u:esata", giver_name="Esata", giver_faction=OTHER), 620)
        king = {**TINFIST, "id": "h:4", "template_id": "dust-king", "name": "Dust King"}
        self.assertEqual(self.take(captured(king, 630), 630), ["Job done: go back to Esata for the reward."])
        self.assertEqual(self.states(), [(capture, "done", 0), (killing, "done", 0)])

    def test_a_kill_of_a_figure_job_counts_toward_no_faction_job(self):
        campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Emperor Tengu"), 600)
        faction_job = campaign_db.add_quest(job(target="58229-Dialogue.mod", giver_faction=OTHER), 600)
        self.take(killed(TINFIST, 610), 610)
        self.assertEqual(campaign_db.quest(faction_job)["kills"], 0)

    def test_the_figure_job_fails_when_the_game_holds_its_target_or_its_giver_dead_or_imprisoned(self):
        target = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Emperor Tengu"), 600)
        giver = campaign_db.add_quest(job("figure", "u:dust-king", 1, 20000, giver="u:esata", giver_name="Esata", giver_faction=OTHER), 600)
        state.UNIQUE_STATES = [{"id": "tinfist", "name": "Tinfist", "state": "dead"}, {"id": "esata", "name": "Esata", "state": "imprisoned"}]
        self.assertEqual(self.take([], 610), ["Job failed: Esata is imprisoned.", "Job failed: Tinfist is dead."])
        self.assertEqual(self.states(), [(giver, "failed", 0), (target, "failed", 0)])
        self.assertEqual(self.take([], 620), [])

    def test_a_kill_and_a_dead_state_in_one_request_do_the_job(self):
        quest_id = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Emperor Tengu"), 600)
        state.UNIQUE_STATES = [{"id": "tinfist", "name": "Tinfist", "state": "dead"}]
        self.assertEqual(self.take(killed(TINFIST, 610), 610), ["Job done: go back to Emperor Tengu for the reward."])
        self.assertEqual(self.states(), [(quest_id, "done", 0)])

    def test_a_job_of_each_kind_fails_when_the_game_holds_its_giver_dead_even_when_it_is_done(self):
        quest_id = campaign_db.add_quest(job(giver="u:tengu", giver_name="Emperor Tengu"), 600)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 611), 611)
        state.UNIQUE_STATES = [{"id": "tengu", "name": "Emperor Tengu", "state": "dead"}]
        self.assertEqual(self.take([], 620), ["Job failed: Emperor Tengu is dead."])
        self.assertEqual(self.states(), [(quest_id, "failed", 2)])

    def test_the_death_of_the_giver_fails_its_job(self):
        quest_id = campaign_db.add_quest(job(), 600)
        goods = campaign_db.add_quest(job("goods", "Raw Iron", 5, 1500, giver="h:20", giver_name="Harvag", giver_faction=""), 600)
        rook = {"id": "h:7", "template_id": "", "name": "Sergeant Rook", "faction": "United Cities", "factionID": UC, "player": False}
        harvag = {**rook, "id": "h:20", "name": "Harvag", "factionID": ""}
        self.assertEqual(self.take(killed(rook, 610, OUTSIDER) + [{"kind": "death", "party": harvag, **when(611)}], 611),
                         ["Job failed: Sergeant Rook is dead.", "Job failed: Harvag is dead."])
        self.assertEqual(self.states(), [(goods, "failed", 0), (quest_id, "failed", 0)])
        self.take([], 605)
        self.assertEqual(self.states(), [(goods, "open", 0), (quest_id, "open", 0)])


class RewindTest(QuestTestCase):
    def test_a_load_undoes_the_jobs_the_kills_and_the_changes_after_its_game_time(self):
        kept = campaign_db.add_quest(job(giver="h:7"), 600)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 620), 620)
        campaign_db.set_quest_state(kept, "paid", 630, "done")
        campaign_db.add_quest(job(giver="h:8", target="58229-Dialogue.mod"), 640)
        self.take([], 615)
        self.assertEqual(self.states(), [(kept, "open", 1)])

    def test_a_paid_job_done_before_the_load_is_done_again(self):
        quest_id = campaign_db.add_quest(job(), 600)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 620), 620)
        campaign_db.set_quest_state(quest_id, "paid", 630, "done")
        self.take([], 625)
        self.assertEqual(self.states(), [(quest_id, "done", 2)])
        self.assertEqual(campaign_db.quest(quest_id)["changed_at"], 620)

    def test_a_figure_job_counts_its_events_again_up_to_the_load(self):
        quest_id = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Emperor Tengu"), 600)
        self.take(killed(TINFIST, 610), 610)
        campaign_db.set_quest_state(quest_id, "paid", 630, "done")
        self.take([], 620)
        self.assertEqual(self.states(), [(quest_id, "done", 0)])
        self.take([], 605)
        self.assertEqual(self.states(), [(quest_id, "open", 0)])

    def test_the_start_of_the_clock_rewinds_nothing(self):
        campaign_db.add_quest(job(), 600)
        world_events.take([], when(0))
        self.assertEqual(len(campaign_db.quests()), 1)

    def test_the_cull_rewinds_the_jobs(self):
        quest_id = campaign_db.add_quest(job(), 600)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 620), 620)
        campaign_db.add_quest(job(giver="h:8", target="58229-Dialogue.mod", giver_faction=OTHER), 640)
        campaign_db.cull_after(0, 10, 15)
        self.assertEqual(self.states(), [(quest_id, "open", 1)])

    def test_a_write_reaches_only_a_job_in_the_expected_state(self):
        quest_id = campaign_db.add_quest(job(), 600)
        self.assertFalse(quests.accept({**campaign_db.quest(quest_id), "state": "done"}, 610))
        self.assertTrue(quests.accept(campaign_db.quest(quest_id), 610))
        self.assertFalse(quests.accept({**job(), "id": quest_id, "state": "open"}, 620))
        self.assertTrue(campaign_db.delete_quest(quest_id))
        self.assertFalse(campaign_db.set_quest_state(quest_id, "paid", 630, "open"))


class TextTest(QuestTestCase):
    def test_a_new_job_names_what_the_npc_wants_and_the_fixed_reward(self):
        new = {**job(count=5, reward=2500), "target_name": "Dust Bandits"}
        self.assertEqual(quests.facts(new, SPEAKER, "Beep"), "JOB FACTS:\n- You want Beep's group to kill 5 members of the Dust Bandits.\n- You pay 2,500 cats when it is done.\n"
                         "- The reward is fixed.")
        figure = {**job("figure", "u:tinfist", 1, 20000), "target_name": "Tinfist", "about": "leader of the Anti-Slavers"}
        self.assertEqual(quests.progress(figure, SPEAKER, "Beep"), ["You want Beep's group to kill or capture Tinfist, leader of the Anti-Slavers.", "You pay 20,000 cats when it is done."])
        goods = {**job("goods", "Raw Iron", 5, 1500), "target_name": "Raw Iron"}
        self.assertEqual(quests.progress(goods, SPEAKER, "Beep"), ["You want Beep to bring you 5 Raw Iron.", "You pay 1,500 cats for them."])

    def test_a_held_job_tells_who_gave_it_and_how_far_it_is(self):
        quest_id = campaign_db.add_quest(job(count=5, reward=2500), 600)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 611), 611)
        self.assertEqual(quests.progress(campaign_db.quest(quest_id), SPEAKER, "Beep")[:2],
                         ["You gave Beep's group a job: kill 5 members of the Dust Bandits, for 2,500 cats.", "Beep's group has killed 2 of the 5 so far."])
        self.assertEqual(quests.scene_text(campaign_db.quest(quest_id), SPEAKER, "Beep").split(". ")[0],
                         "You gave Beep's group a job: kill 5 members of the Dust Bandits, for 2,500 cats")
        self.assertEqual(quests.scene_text(None, SPEAKER, "Beep"), "")

    def test_a_goods_job_counts_what_the_speaker_carries(self):
        held = {**job("goods", "Raw Iron", 5, 1500), "id": 1, "state": "open", "target_name": "Raw Iron"}
        def carrying(*counts):
            return {"inventory": [{"name": "Raw Iron", "count": count} for count in counts]}
        self.assertEqual(quests.progress(held, carrying(), "Beep")[1], "Beep carries none of the 5 Raw Iron.")
        self.assertEqual(quests.progress(held, carrying(2, 1), "Beep")[1], "Beep carries only 3 of the 5 Raw Iron.")
        self.assertEqual(quests.progress(held, carrying(3, 2), "Beep")[1], "Beep carries the 5 Raw Iron that you asked for.")
        self.assertFalse(quests.payable(held, carrying(4)))
        self.assertTrue(quests.payable(held, carrying(5)))

    def test_only_a_done_job_is_payable(self):
        quest_id = campaign_db.add_quest(job(), 600)
        self.assertFalse(quests.payable(campaign_db.quest(quest_id), SPEAKER))
        self.take(killed(bandit(1), 610) + killed(bandit(2), 611), 611)
        self.assertTrue(quests.payable(campaign_db.quest(quest_id), SPEAKER))
        self.assertEqual(quests.progress(campaign_db.quest(quest_id), SPEAKER, "Beep")[1], "Beep's group has done the job, so you owe it the 1,000 cats.")

    def test_the_quests_tab_shows_the_giver_the_reward_and_the_progress(self):
        campaign_db.upsert_profile("h:7", {"Name": "Sergeant Rook", "CurrentLocation": "Bar, Heng"})
        quest_id = campaign_db.add_quest(job(count=5, reward=2500), 600)
        self.take(killed(bandit(1), 610) + killed(bandit(2), 611), 611)
        self.assertEqual(quests.entry(campaign_db.quest(quest_id)), {
            "id": str(quest_id), "giver": "Sergeant Rook", "label": "Sergeant Rook: Kill 5 members of the Dust Bandits",
            "details": "Giver: Sergeant Rook of the United Cities, last seen at Bar, Heng.\nReward: 2,500 cats.\nProgress: 2 of 5 killed.",
        })

    def test_the_progress_of_each_kind_and_state(self):
        goods = campaign_db.add_quest(job("goods", "Raw Iron", 5, 1500, giver="h:20", giver_name="Harvag", giver_faction=""), 600)
        figure = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Emperor Tengu"), 600)
        self.assertEqual(quests.details(campaign_db.quest(goods)), "Giver: Harvag.\nReward: 1,500 cats.\nProgress: Bring 5 Raw Iron to Harvag.")
        self.assertEqual(quests.details(campaign_db.quest(figure)).splitlines()[-1], "Progress: Not done yet.")
        self.take(killed(TINFIST, 610), 610)
        self.assertEqual(quests.details(campaign_db.quest(figure)).splitlines()[-1], "Progress: Done. Go back to Emperor Tengu for the reward.")
        self.assertEqual(quests.entry(campaign_db.quest(figure))["label"], "Emperor Tengu: Kill or capture Tinfist")

    def test_the_jobs_take_the_current_names(self):
        quest_id = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_name="Tengu"), 600)
        campaign_db.rename_character("u:tinfist", "Tinfist", "Iron Fist")
        held = campaign_db.quest(quest_id)
        self.assertEqual((held["giver_name"], held["target_name"]), ("Emperor Tengu", "Iron Fist"))


class StoreTest(QuestTestCase):
    def test_the_list_holds_the_open_and_the_done_jobs_newest_first_by_the_accept(self):
        older = campaign_db.add_quest(job(giver="h:7"), 600)
        newer = campaign_db.add_quest(job(giver="h:8", giver_faction=OTHER), 700)
        failed = campaign_db.add_quest(job("figure", "u:tinfist", 1, 20000, giver="u:tengu", giver_faction=""), 650)
        campaign_db.set_quest_state(failed, "failed", 710, "open")
        paid = campaign_db.add_quest(job(giver="h:9", giver_faction=""), 660)
        campaign_db.set_quest_state(paid, "paid", 710, "open")
        campaign_db.set_quest_state(older, "done", 720, "open")
        self.assertEqual([(job["id"], job["state"]) for job in campaign_db.quests()], [(newer, "open"), (older, "done")])

    def test_abandon_deletes_the_job_with_its_kills_so_the_giver_can_give_a_new_job(self):
        quest_id = campaign_db.add_quest(job(), 600)
        self.take(killed(bandit(1), 610), 610)
        self.assertTrue(campaign_db.delete_quest(quest_id))
        self.assertFalse(campaign_db.delete_quest(quest_id))
        new = campaign_db.add_quest(job(), 620)
        self.assertNotEqual(new, quest_id)
        self.assertEqual(campaign_db.quest(new)["kills"], 0)

    def test_a_rekey_moves_the_job_of_the_giver(self):
        quest_id = campaign_db.add_quest(job(giver="h:7"), 600)
        self.assertTrue(campaign_db.rekey("h:7", "h:70", 610))
        self.assertEqual(campaign_db.quest(quest_id)["giver"], "h:70")


if __name__ == "__main__":
    unittest.main()
