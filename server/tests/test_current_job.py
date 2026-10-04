import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server", "scripts"))

import current_job


def job(ctx, in_player_faction=False):
    return current_job.current_job(ctx, in_player_faction, "Nameless")


class CurrentJobTest(unittest.TestCase):
    def test_a_squad_job_gives_its_phrase(self):
        self.assertEqual(job({"squad_jobs": ["PICKUP_INTRUDERS_BUILDING", "STAND_AT_GUARD_NODE_HOMEBUILDING_IN_OUT"]}), "Guarding a building")
        self.assertEqual(job({"squad_jobs": ["RELAX_IN_TOWN_PACKAGE", "SHOPPING"]}), "Hanging out at a bar")

    def test_the_first_entry_of_the_table_wins(self):
        self.assertEqual(job({"squad_jobs": ["MAN_A_TURRET_ON_BUILDING", "STAND_AT_GUARD_NODE_HOMEBUILDING_IN_OUT"]}), "Guarding a building")
        self.assertEqual(job({"squad_jobs": ["PATROL_TOWN", "RELAX_IN_TOWN_PACKAGE"]}), "Hanging out at a bar")

    def test_a_shopkeeper_runs_a_shop_and_another_trader_trades(self):
        self.assertEqual(job({"is_trader": True, "squad_jobs": ["STAND_AT_SHOPKEEPER_NODE"]}), "Running a shop")
        self.assertEqual(job({"is_trader": True, "squad_jobs": ["PATROL_TOWN", "RELAX_IN_TOWN_PACKAGE"]}), "Trading")

    def test_a_member_of_the_player_faction_is_a_member(self):
        self.assertEqual(job({"squad_jobs": ["PATROL_TOWN"]}, in_player_faction=True), "Member of Nameless")

    def test_a_hired_npc_is_a_temporary_follower_even_in_the_player_faction(self):
        self.assertEqual(job({"temporary_follower": True, "squad_jobs": []}), "Temporary follower of Nameless")
        self.assertEqual(job({"temporary_follower": True, "squad_jobs": []}, in_player_faction=True), "Temporary follower of Nameless")

    def test_no_known_squad_job_gives_no_current_job(self):
        self.assertIsNone(job({"squad_jobs": []}))
        self.assertIsNone(job({"squad_jobs": ["JOB_MEDIC", "SELF_PRESERVATION"]}))

    def test_the_plugin_sends_each_task_of_the_table(self):
        source = open(os.path.join(ROOT, "plugin", "game", "Context.cpp"), encoding="utf-8").read()
        self.assertEqual(set(re.findall(r"ROLE_TASK\((\w+)\),", source)), current_job.TASKS)


if __name__ == "__main__":
    unittest.main()
