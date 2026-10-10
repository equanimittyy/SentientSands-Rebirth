import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server"))

from chat import offers
from core import state

NPC = {"money": 300, "inventory": [{"name": "Katana", "count": 1}, {"name": "Bread", "count": 2}, {"name": "Bread", "count": 1}]}
SPEAKER = {"money": 1000, "inventory": [{"name": "Dirty Loincloth", "count": 1}]}


def check(category, tag, npc=NPC, speaker=SPEAKER, guard=False):
    return offers.check(category, offers.read(tag), npc, speaker, guard)


class ReadTest(unittest.TestCase):
    def test_the_parts_of_the_offer_tag(self):
        self.assertEqual(offers.read("Fine. [OFFER: JOIN_PARTY; TAKE_CATS: 1,500] [JUDGMENT: 1]"), [("JOIN_PARTY", ""), ("TAKE_CATS", "1,500")])
        self.assertEqual(offers.read("[offer: give item: 2 Bread]"), [("GIVE_ITEM", "2 Bread")])

    def test_a_reply_without_the_tag_has_no_offer(self):
        self.assertIsNone(offers.read("[RECRUIT] Maybe. [JUDGMENT: 0]"))

    def test_the_refusal_and_the_attack(self):
        self.assertTrue(offers.refused("No. [REFUSE]"))
        self.assertTrue(offers.attacked("You asked for it! [ attack ]"))
        self.assertFalse(offers.refused("I refuse to pay that."))


class CheckTest(unittest.TestCase):
    def test_a_recruit_with_a_fee(self):
        offer, reason = check("RECRUIT", "[OFFER: JOIN_PARTY; TAKE_CATS: 800]")
        self.assertIsNone(reason)
        self.assertEqual(offer["gives"], [("JOIN_PARTY", None)])
        self.assertEqual(offer["takes"], [("CATS", 800)])

    def test_the_player_pays_only_the_cats_that_it_has(self):
        self.assertIsNone(check("RECRUIT", "[OFFER: JOIN_PARTY; TAKE_CATS: 1001]")[0])

    def test_a_deal_needs_its_part(self):
        self.assertIsNone(check("RECRUIT", "[OFFER: TAKE_CATS: 100]")[0])
        self.assertIsNone(check("HEAL", "[OFFER: JOIN_PARTY]")[0])

    def test_a_part_of_another_category_breaks_the_offer(self):
        self.assertIsNone(check("THREATEN", "[OFFER: GIVE_CATS: 100; TAKE_CATS: 50]")[0])

    def test_a_handover_holds_only_what_the_npc_carries(self):
        offer, _ = check("THREATEN", "[OFFER: GIVE_CATS: 200; GIVE_ITEM: 3 bread]")
        self.assertEqual(offer["gives"], [("CATS", 200), ("ITEM", (3, "Bread"))])
        self.assertIsNone(check("THREATEN", "[OFFER: GIVE_ITEM: 4 Bread]")[0])
        self.assertIsNone(check("THREATEN", "[OFFER: GIVE_CATS: 301]")[0])
        self.assertIsNone(check("THREATEN", "[OFFER: GIVE_ITEM: Wakizashi]")[0])

    def test_the_length_of_a_hire(self):
        self.assertEqual(check("FOLLOW", "[OFFER: HIRE: 2 days]")[0]["gives"], [("HIRE", 48)])
        self.assertEqual(check("FOLLOW", "[OFFER: HIRE: 6 hours]")[0]["gives"], [("HIRE", 6)])
        self.assertIsNone(check("FOLLOW", "[OFFER: HIRE]")[0])

    def test_a_mercenary_charges_its_daily_rate(self):
        merc = {**NPC, "faction": "Mercenary Guild"}
        self.assertIsNone(check("FOLLOW", "[OFFER: HIRE: 1 day; TAKE_CATS: 900]", npc=merc)[0])
        rich = {**SPEAKER, "money": 5000}
        self.assertIsNotNone(check("FOLLOW", "[OFFER: HIRE: 2 days; TAKE_CATS: 4000]", npc=merc, speaker=rich)[0])
        self.assertIsNotNone(check("FOLLOW", "[OFFER: HIRE: 6 hours; TAKE_CATS: 500]", npc=merc)[0])

    def test_a_release_knows_whether_a_guard_releases(self):
        self.assertEqual(check("LIBERATE", "[OFFER: RELEASE]", guard=True)[0]["gives"], [("RELEASE", True)])


class TextTest(unittest.TestCase):
    def test_the_popup_names_the_real_deal(self):
        recruit, _ = check("RECRUIT", "[OFFER: JOIN_PARTY; TAKE_CATS: 1500]", speaker={**SPEAKER, "money": 2000})
        self.assertEqual(offers.popup_text(recruit, "Drifter", "Zaps"), "Drifter offers to join your squad for 1,500 cats.")
        handover, _ = check("THREATEN", "[OFFER: GIVE_CATS: 200; GIVE_ITEM: Katana]")
        self.assertEqual(offers.popup_text(handover, "Bandit", "Zaps"), "Bandit offers 200 cats and a Katana.")
        hire, _ = check("FOLLOW", "[OFFER: HIRE: 2 days; TAKE_CATS: 400]")
        self.assertEqual(offers.popup_text(hire, "Drifter", "Zaps"), "Drifter offers to follow you for 2 days for 400 cats.")
        release, _ = check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 500]", guard=True)
        self.assertEqual(offers.popup_text(release, "Guard", "Zaps"), "Guard offers your release for 500 cats.")
        breakout, _ = check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 500]")
        self.assertEqual(offers.popup_text(breakout, "Drifter", "Zaps"), "Drifter offers to break you out for 500 cats.")

    def test_the_memory_lines_are_deal_lines(self):
        handover, _ = check("THREATEN", "[OFFER: GIVE_CATS: 200]")
        accepted = offers.accepted_line(handover, "Bandit", "Zaps")
        declined = offers.declined_line(handover, "Bandit", "Zaps")
        self.assertEqual(accepted, "(Zaps accepted: Bandit gives Zaps 200 cats.)")
        self.assertEqual(declined, "(Zaps declined: Bandit offered 200 cats.)")
        for line in (accepted, declined, "(Bandit attacked Zaps.)", "(Doc treated Zaps for free.)", "(Zaps dismissed Hobbs.)"):
            self.assertTrue(offers.DEAL_LINE.search(f"[Day 1, 10:00] {line}"), line)
        self.assertFalse(offers.DEAL_LINE.search("[Day 1, 10:00] Zaps: Fine (for now)."))

    def test_the_player_pays_before_the_npc_hands_over(self):
        recruit, _ = check("RECRUIT", "[OFFER: JOIN_PARTY; TAKE_CATS: 800]")
        self.assertEqual(offers.actions(recruit), ["[ACTION: TAKE_CATS: 800]", "[ACTION: JOIN_PARTY]"])
        handover, _ = check("THREATEN", "[OFFER: GIVE_ITEM: 2 Bread]")
        self.assertEqual(offers.actions(handover), ["[ACTION: GIVE_ITEM: Bread: 2]"])

    def test_the_command_holds_what_each_side_must_still_hold(self):
        offer, _ = check("BARTER", "[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 250; TAKE_ITEM: Dirty Loincloth]")
        lines = offers.command(7, offer, "Bandit", "12", "3", "text").split("\n")
        self.assertEqual(lines[:4], ["CMD: OFFER: 7", "12 3", "Bandit", "text"])
        self.assertEqual(lines[4:], ["CHECK: CATS player 250", "CHECK: ITEM player 1 Dirty Loincloth", "CHECK: ITEM npc 1 Katana"])


class HoldTest(unittest.TestCase):
    def tearDown(self):
        state.PENDING_OFFER = None

    def test_only_the_held_offer_can_be_taken_and_only_once(self):
        offer_id = offers.hold({"category": "RECRUIT"}, npc="Drifter")
        self.assertIsNone(offers.take(offer_id + 1))
        self.assertEqual(offers.take(str(offer_id))["npc"], "Drifter")
        self.assertIsNone(offers.take(offer_id))


class FactsTest(unittest.TestCase):
    def test_the_turn_message_holds_the_cats_and_the_lean(self):
        text = offers.facts("RECRUIT", NPC, SPEAKER, "Zaps", 2)
        self.assertIn("Zaps's squad has 1,000 cats.", text)
        self.assertIn("YOUR THOUGHT: You are inclined to agree.", text)

    def test_a_threat_lists_what_the_npc_carries(self):
        self.assertIn("You carry: 1 Katana, 2 Bread, 1 Bread.", offers.facts("THREATEN", NPC, SPEAKER, "Zaps", 0))

    def test_a_mercenary_names_its_rate(self):
        self.assertIn("at least 2,500 cats for each day", offers.facts("FOLLOW", {**NPC, "faction": "Black Dog"}, SPEAKER, "Zaps", 0))


if __name__ == "__main__":
    unittest.main()
