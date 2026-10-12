import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server"))

from chat import offers
from core import state

NPC = {"money": 300, "inventory": [{"name": "Katana", "count": 1}, {"name": "Bread", "count": 2}, {"name": "Bread", "count": 1}]}
SPEAKER = {"money": 1000, "inventory": [{"name": "Dirty Loincloth", "count": 1}]}
GUARD = {**NPC, "squad_jobs": ["MAN_THE_GATE"]}


def check(category, tag, npc=NPC, speaker=SPEAKER):
    return offers.check(category, offers.read(tag), npc, speaker)


class ReadTest(unittest.TestCase):
    def test_the_parts_of_the_offer_tag(self):
        self.assertEqual(offers.read("Fine. [OFFER: JOIN_PARTY; TAKE_CATS: 1,500] [JUDGMENT: 1]"), [("JOIN_PARTY", ""), ("TAKE_CATS", "1,500")])
        self.assertEqual(offers.read("[offer: give item: 2 Bread]"), [("GIVE_ITEM", "2 Bread")])

    def test_a_reply_without_the_tag_has_no_offer(self):
        self.assertIsNone(offers.read("[RECRUIT] Maybe. [JUDGMENT: 0]"))
        self.assertIsNone(offers.read("I won't hire on, and I won't release you either."))

    def test_the_parts_without_their_brackets(self):
        reply = "Take it. GIVE_CATS: 4; GIVE_ITEM: 1 Shovel [JUDGMENT: -3]"
        self.assertEqual(offers.read(reply), [("GIVE_CATS", "4"), ("GIVE_ITEM", "1 Shovel")])
        self.assertEqual(offers.offer_text(reply).strip(), "GIVE_CATS: 4; GIVE_ITEM: 1 Shovel")
        self.assertEqual(offers.read("Fine. OFFER: JOIN_PARTY; TAKE_CATS: 800"), [("JOIN_PARTY", ""), ("TAKE_CATS", "800")])

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

    def test_a_release_costs_a_bribe_on_top_of_the_bounty(self):
        self.assertIsNone(check("LIBERATE", "[OFFER: RELEASE]", npc=GUARD)[0])
        self.assertIsNone(check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 499]", npc=GUARD)[0])
        self.assertEqual(check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 500]", npc=GUARD)[0]["gives"], [("RELEASE", None)])
        wanted = {**SPEAKER, "money": 5000, "bounty": 2000}
        self.assertIsNone(check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 2000]", npc=GUARD, speaker=wanted)[0])
        self.assertIsNotNone(check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 2500]", npc=GUARD, speaker=wanted)[0])


class TextTest(unittest.TestCase):
    def test_the_popup_names_the_real_deal(self):
        recruit, _ = check("RECRUIT", "[OFFER: JOIN_PARTY; TAKE_CATS: 1500]", speaker={**SPEAKER, "money": 2000})
        self.assertEqual(offers.popup_text(recruit, "Drifter", "Zaps"), "Drifter offers to join your squad for 1,500 cats.")
        handover, _ = check("THREATEN", "[OFFER: GIVE_CATS: 200; GIVE_ITEM: Katana]")
        self.assertEqual(offers.popup_text(handover, "Bandit", "Zaps"), "Bandit offers 200 cats and a Katana.")
        hire, _ = check("FOLLOW", "[OFFER: HIRE: 2 days; TAKE_CATS: 400]")
        self.assertEqual(offers.popup_text(hire, "Drifter", "Zaps"), "Drifter offers to follow you for 2 days for 400 cats.")
        release, _ = check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 500]", npc=GUARD)
        self.assertEqual(offers.popup_text(release, "Guard", "Zaps"), "Guard offers your release for 500 cats.")
        self.assertEqual(offers.actions(release), ["[ACTION: TAKE_CATS: 500]", "[ACTION: RELEASE_PRISONER]"])
        caged = {**SPEAKER, "captors": "Holy Nation", "captorsID": "17-gamedata.base"}
        breakout, _ = check("LIBERATE", "[OFFER: RELEASE; TAKE_CATS: 500]", npc={"factionID": "204-gamedata.base"}, speaker=caged)
        self.assertEqual(offers.popup_text(breakout, "Drifter", "Zaps"), "Drifter offers to break you out for 500 cats.")
        self.assertEqual(offers.actions(breakout), ["[ACTION: TAKE_CATS: 500]", "[ACTION: BREAKOUT_PLAYER]"])

    def test_the_memory_lines_are_deal_lines(self):
        handover, _ = check("THREATEN", "[OFFER: GIVE_CATS: 200]")
        accepted = offers.accepted_line(handover, "Bandit", "Zaps")
        declined = offers.declined_line(handover, "Bandit", "Zaps")
        self.assertEqual(accepted, "(Zaps accepted: Bandit gives Zaps 200 cats.)")
        self.assertEqual(declined, "(Zaps declined: Bandit offered 200 cats.)")
        for line in (accepted, declined, "(Bandit attacked Zaps.)", "(Doc treated Zaps for free.)", "(Zaps dismissed Hobbs.)"):
            self.assertTrue(offers.DEAL_LINE.search(f"[Day 1, 10:00] {line}"), line)
        self.assertFalse(offers.DEAL_LINE.search("[Day 1, 10:00] Zaps: Fine (for now)."))

    def test_the_join_goes_first_and_the_player_pays_before_the_npc_hands_over(self):
        recruit, _ = check("RECRUIT", "[OFFER: JOIN_PARTY; TAKE_CATS: 800]")
        self.assertEqual(offers.actions(recruit), ["[ACTION: JOIN_PARTY]", "[ACTION: TAKE_CATS: 800]"])
        handover, _ = check("THREATEN", "[OFFER: GIVE_ITEM: 2 Bread]")
        self.assertEqual(offers.actions(handover), ["[ACTION: GIVE_ITEM: Bread: 2]"])

    def test_the_command_holds_what_each_side_must_still_hold(self):
        offer, _ = check("BARTER", "[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 250; TAKE_ITEM: Dirty Loincloth]")
        lines = offers.command(7, offer, "Bandit", "12", "3", "text").split("\n")
        self.assertEqual(lines[:4], ["CMD: OFFER: 7", "12 3", "Bandit", "text"])
        self.assertEqual(lines[4:], ["CHECK: CATS player 250", "CHECK: ITEM player 1 Dirty Loincloth", "CHECK: ITEM npc 1 Katana",
                                     "BOX: player 250 cats", "BOX: player 1 Dirty Loincloth", "BOX: npc 1 Katana"])

    def test_only_an_agreement_in_the_barter_window_sends_the_deal_lines(self):
        offer, _ = check("BARTER", "[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 250]")
        lines = offers.command(7, offer, "Bandit", "12", "3", "text", window=True).split("\n")
        self.assertEqual(lines[-2:], ["DEAL: CATS player 250", "DEAL: ITEM npc 1 Katana"])


SHOP = {"npc_id": "h:1-shop", "day": 4, "money": 5000, "squad_jobs": ["STAND_AT_SHOPKEEPER_NODE"],
        "inventory": [{"name": "Bread", "count": 2, "price": 400}],
        "stock": [{"name": "Katana (Ancient, Refitted Blade)", "count": 1, "price": 3000}, {"name": "First Aid Kit", "count": 1, "price": 102},
                  {"name": "First Aid Kit", "count": 1, "price": 132}]}
BUYER = {"money": 5000, "inventory": [{"name": "Dirty Loincloth", "count": 1, "price": 100}, {"name": "Chain Shirt (High)", "count": 1, "price": 20000}]}


class BarterTest(unittest.TestCase):
    def tearDown(self):
        state.CHARITY_DAYS.clear()

    def barter(self, tag, npc=SHOP, speaker=BUYER):
        return offers.check("BARTER", offers.read(tag), npc, speaker)

    def test_a_shopkeeper_sells_the_stock_of_its_shop(self):
        offer, reason = self.barter("[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 3000]")
        self.assertIsNone(reason)
        self.assertEqual(offer["gives"], [("ITEM", (1, "Katana (Ancient, Refitted Blade)"))])

    def test_a_trader_in_a_shop_keeps_what_it_carries(self):
        self.assertIsNone(self.barter("[OFFER: GIVE_ITEM: 1 Bread; TAKE_CATS: 1000]")[0])
        sale, _ = self.barter("[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 3000]")
        self.assertEqual(offers.actions(sale), ["[ACTION: TAKE_CATS: 3000]", "[ACTION: SELL_ITEM: Katana (Ancient, Refitted Blade): 1]"])
        away = {key: value for key, value in SHOP.items() if key != "stock"}
        self.assertEqual(offers.actions(self.barter("[OFFER: GIVE_ITEM: 1 Bread; TAKE_CATS: 1000]", npc=away)[0])[1], "[ACTION: GIVE_ITEM: Bread: 1]")

    def test_another_npc_hands_over_only_what_it_carries(self):
        self.assertIsNone(self.barter("[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 3000]", npc={**SHOP, "squad_jobs": []})[0])

    def test_a_barman_whose_job_reads_trading_sells_the_stock(self):
        barman = {**SHOP, "squad_jobs": [], "is_trader": True}
        self.assertIsNotNone(self.barter("[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 3000]", npc=barman)[0])

    def test_a_trade_at_a_loss_holds_because_the_worth_only_guides_the_model(self):
        self.assertIsNotNone(self.barter("[OFFER: GIVE_ITEM: Katana; TAKE_CATS: 10]")[0])
        self.assertIsNotNone(self.barter("[OFFER: GIVE_ITEM: Katana; TAKE_ITEM: Dirty Loincloth]")[0])

    def test_the_relation_sets_the_loss_that_the_npc_usually_takes(self):
        self.assertEqual([offers.loss_share(relation) for relation in (-25, -24, 24, 25, 59, 60)], [0.0, 0.05, 0.05, 0.15, 0.15, 0.3])

    def test_the_stock_sets_the_price_at_its_highest(self):
        self.assertEqual(offers.price_of("First Aid Kit", offers.goods(SHOP, "BARTER")), 132)

    def test_a_name_without_its_grade_needs_one_grade_held(self):
        two = {**BUYER, "inventory": BUYER["inventory"] + [{"name": "Chain Shirt (Standard)", "count": 1, "price": 10000}]}
        self.assertEqual(offers.held(BUYER["inventory"], "chain shirt"), ("Chain Shirt (High)", 1))
        self.assertEqual(offers.held(two["inventory"], "Chain Shirt"), (None, 0))

    def test_charity_costs_the_npc_nothing_but_has_tight_limits(self):
        poor = {**SHOP, "money": 0, "stock": [], "inventory": []}
        cats, _ = self.barter("[OFFER: GIVE_CATS: 50]", npc=poor)
        self.assertTrue(cats["charity"])
        self.assertEqual(offers.actions(cats), ["[ACTION: ADD_CATS: 50]"])
        self.assertEqual(offers.checks(cats), [])
        food, _ = self.barter("[OFFER: GIVE_FOOD]", npc=poor)
        self.assertEqual(offers.actions(food), ["[ACTION: SPAWN_ITEM: Dried Gristle Flaps]"])
        self.assertIn("only for charity", self.barter("[OFFER: GIVE_FOOD; TAKE_CATS: 10]")[1])
        self.assertIsNone(self.barter("[OFFER: GIVE_ITEM: 1 Dried Meat]", npc=poor)[0])
        self.assertEqual(self.barter("[OFFER: GIVE_CATS: 500]", npc=poor)[0]["gives"], [("CATS", 50)])
        self.assertIsNone(self.barter("[OFFER: GIVE_ITEM: 1 Katana]")[0])

    def test_a_second_charity_in_a_day_is_no_hard_limit(self):
        state.CHARITY_DAYS[SHOP["npc_id"]] = SHOP["day"]
        self.assertTrue(self.barter("[OFFER: GIVE_CATS: 10]", npc={**SHOP, "money": 0})[0]["charity"])

    def test_a_gift_raises_the_relation_by_its_worth(self):
        self.assertEqual(self.barter("[OFFER: TAKE_CATS: 1499]")[0]["gift"], 2)
        self.assertEqual(self.barter("[OFFER: TAKE_CATS: 499]")[0]["gift"], 0)
        self.assertEqual(self.barter("[OFFER: TAKE_ITEM: Chain Shirt]")[0]["gift"], 10)
        self.assertEqual(offers.popup_text(self.barter("[OFFER: TAKE_CATS: 500]")[0], "Shopkeeper", "Zaps"), "Shopkeeper accepts your gift of 500 cats.")

    def test_the_prompt_lists_the_goods_and_the_prices_of_the_items_named(self):
        self.assertEqual(offers.stocktake(SHOP), "YOUR GOODS: 1 Katana (Ancient, Refitted Blade), 2 First Aid Kit.")
        guide = offers.price_guide("How much for the katana? I could sell my chain shirt.", SHOP, BUYER, "Zaps")
        self.assertEqual(guide, ["You have 1 Katana (Ancient, Refitted Blade): you sell each for at least 3,000 cats.",
                                 "Zaps has 1 Chain Shirt (High): you pay at most 16,000 cats each."])

    def test_a_word_of_the_name_or_a_kind_word_asks_for_an_item(self):
        bar = {**SHOP, "inventory": [], "stock": [{"name": "Water", "count": 3, "price": 10, "kind": "food"},
                                                  {"name": "Water Jug", "count": 14, "price": 120, "kind": "goods"},
                                                  {"name": "Sake", "count": 2, "price": 200, "kind": "drug"},
                                                  {"name": "Bread", "count": 5, "price": 50, "kind": "food"}]}
        self.assertEqual(offers.asked(bar["stock"], "Got any water?"), ["Water", "Water Jug"])
        self.assertEqual(offers.asked(bar["stock"], "Anything to drink?"), ["Sake"])
        self.assertEqual(offers.asked(bar["stock"], "I need food"), ["Water", "Bread"])
        self.assertEqual(offers.asked(bar["stock"], "Can I pay in cats, right now?"), [])
        self.assertEqual(offers.price_guide("Got any water?", bar, BUYER, "Zaps")[1], "You have 14 Water Jug: you sell each for at least 120 cats.")

    def test_a_kind_word_prices_at_most_ten_items_of_each_side(self):
        store = {**SHOP, "inventory": [], "stock": [{"name": f"Food {n}", "count": 1, "price": 10, "kind": "food"} for n in range(15)]}
        self.assertEqual(len(offers.price_guide("Any food?", store, BUYER, "Zaps")), offers.PRICE_LINES)


SQUAD = [{"key": "3", "inventory": BUYER["inventory"]}, {"key": "8", "inventory": [{"name": "Bread", "count": 4, "price": 50}]}]
TABLE = {"take_cats": 2950, "give_cats": 0, "take": [{"holder": "8", "name": "Bread", "count": 2}], "give": [{"name": "Katana (Ancient, Refitted Blade)", "count": 1}]}


class BarterWindowTest(unittest.TestCase):
    def test_the_agreement_tag(self):
        self.assertTrue(offers.agreed("Fine, it's yours. [ agree ]"))
        self.assertFalse(offers.agreed("I agree that it's hot."))

    def test_an_item_of_any_squad_mate_leaves_its_holder(self):
        offer, _ = offers.check("BARTER", offers.table_parts(TABLE), SHOP, BUYER, SQUAD)
        self.assertEqual(offer["takes"], [("CATS", 2950), ("ITEM", (2, "Bread", "8"))])
        self.assertEqual(offers.voiced(offer, "Shopkeeper|12>3"), ["Shopkeeper|12>3: [ACTION: TAKE_CATS: 2950]", "Shopkeeper|12>8: [ACTION: TAKE_ITEM: Bread: 2]",
                                                                   "Shopkeeper|12>3: [ACTION: SELL_ITEM: Katana (Ancient, Refitted Blade): 1]"])
        self.assertIn("CHECK: ITEM 8 2 Bread", offers.checks(offer))
        self.assertIn("DEAL: ITEM 8 2 Bread", offers.deal_lines(offer))

    def test_the_table_names_the_holder_of_each_item(self):
        wrong = {**TABLE, "take": [{"holder": "3", "name": "Bread", "count": 2}]}
        self.assertIn("does not hold", offers.check("BARTER", offers.table_parts(wrong), SHOP, BUYER, SQUAD)[1])

    def test_the_deal_lines_hold_charity(self):
        poor = {**SHOP, "money": 0, "stock": [], "inventory": []}
        charity, _ = offers.check("BARTER", offers.table_parts({"give_cats": 500}), poor, BUYER, SQUAD)
        self.assertEqual(offers.deal_lines(charity), ["DEAL: CATS npc 50"])

    def test_the_turn_message_weighs_the_deal_on_the_table(self):
        offer, _, lines = offers.on_table(TABLE, SHOP, BUYER, SQUAD, "Zaps")
        self.assertIsNotNone(offer)
        self.assertEqual(lines, ["On the table, Zaps gives 2,950 cats and 2 Bread, and you give a Katana (Ancient, Refitted Blade).",
                                 "It keeps your price: you get a worth of 3,030 cats for a worth of 3,000."])

    def test_the_table_weighs_a_loss_against_the_loss_that_the_npc_usually_takes(self):
        offer, _, lines = offers.on_table({**TABLE, "take_cats": 2800}, SHOP, BUYER, SQUAD, "Zaps")
        self.assertIsNotNone(offer)
        self.assertEqual(lines[1], "It is below your price, inside the loss that you usually take: you get a worth of 2,880 cats for a worth of 3,000.")
        offer, _, lines = offers.on_table({**TABLE, "take_cats": 2800}, SHOP, BUYER, SQUAD, "Zaps", relation=-25)
        self.assertIsNotNone(offer)
        self.assertEqual(lines[1], "It is below your price by more than the loss that you usually take: you get a worth of 2,880 cats for a worth of 3,000.")
        self.assertIn("- It is below your price", offers.facts("BARTER", SHOP, BUYER, "Zaps", [], table=lines))

    def test_a_table_that_breaks_a_hard_limit_cannot_be_agreed(self):
        offer, reason, lines = offers.on_table({**TABLE, "take": [{"holder": "3", "name": "Bread", "count": 2}]}, SHOP, BUYER, SQUAD, "Zaps")
        self.assertIsNone(offer)
        self.assertIn("does not hold", reason)
        self.assertEqual(lines[1], "You cannot agree to it as it is.")

    def test_a_gift_charity_and_an_empty_table(self):
        self.assertEqual(offers.on_table({"take_cats": 600}, SHOP, BUYER, SQUAD, "Zaps")[2][1], "It is a gift to you.")
        self.assertEqual(offers.on_table({"give_cats": 50}, SHOP, BUYER, SQUAD, "Zaps")[2][1], "It is a plea for charity.")
        self.assertEqual(offers.on_table({}, SHOP, BUYER, SQUAD, "Zaps"), (None, "the table is empty", ["Nothing is on the table yet."]))


class BoxTest(unittest.TestCase):
    def test_cats_come_first_then_the_biggest_count_then_the_name(self):
        offer = {"category": "BARTER", "takes": [], "gives": [("ITEM", (1, "katana")), ("ITEM", (3, "Water")), ("CATS", 200), ("ITEM", (3, "Bread")), ("ITEM", (1, "Hat"))]}
        self.assertEqual(offers.boxes(offer), ["BOX: npc 200 cats", "BOX: npc 3 Bread", "BOX: npc 3 Water", "BOX: npc 1 Hat", "BOX: npc 1 katana"])


class HoldTest(unittest.TestCase):
    def tearDown(self):
        state.PENDING_OFFER = None

    def test_only_the_held_offer_can_be_taken_and_only_once(self):
        offer_id = offers.hold({"category": "RECRUIT"}, npc="Drifter")
        self.assertIsNone(offers.take(offer_id + 1))
        self.assertEqual(offers.take(str(offer_id))["npc"], "Drifter")
        self.assertIsNone(offers.take(offer_id))


class FactsTest(unittest.TestCase):
    def test_the_turn_message_holds_the_lean_but_not_the_cats_of_the_squad(self):
        text = offers.facts("RECRUIT", NPC, SPEAKER, "Zaps", [(2, "You like {player}'s group a lot.")])
        self.assertNotIn("1,000", text)
        self.assertIn("YOUR THOUGHT: You are inclined to agree.\n- Reasons to agree: You like Zaps's group a lot.", text)

    def test_a_threat_lists_what_the_npc_carries(self):
        self.assertIn("You carry: 1 Katana, 2 Bread, 1 Bread.", offers.facts("THREATEN", NPC, SPEAKER, "Zaps", []))

    def test_a_trade_names_the_cap_of_charity(self):
        self.assertIn("- As charity, you give at most 50 cats.", offers.facts("BARTER", NPC, SPEAKER, "Zaps", []))

    def test_a_trade_names_the_loss_that_the_npc_usually_takes(self):
        self.assertIn("- As a rule, you take a loss of at most 15% of what you give in a trade, but your character decides.",
                      offers.facts("BARTER", NPC, SPEAKER, "Zaps", [], relation=30))
        self.assertIn("- As a rule, you take no loss in a trade, but your character decides.", offers.facts("BARTER", NPC, SPEAKER, "Zaps", [], relation=-30))

    def test_a_second_plea_in_a_day_leans_to_refuse_but_a_trade_does_not(self):
        npc = {**NPC, "npc_id": "h:1-beggar", "day": 4}
        liked = [(1, "You like {player}'s group.")]
        self.assertNotIn("begs for charity", offers.facts("BARTER", npc, SPEAKER, "Zaps", liked))
        state.CHARITY_DAYS[npc["npc_id"]] = 4
        self.addCleanup(state.CHARITY_DAYS.clear)
        text = offers.facts("BARTER", npc, SPEAKER, "Zaps", liked)
        self.assertIn("YOUR THOUGHT: You could go either way.\n- Reasons to agree: You like Zaps's group.\n"
                      "- If Zaps begs for charity: You could go either way. You already gave charity today.", text)
        text = offers.facts("BARTER", npc, SPEAKER, "Zaps", [])
        self.assertIn("- If Zaps begs for charity: You are inclined to refuse. You already gave charity today.", text)

    def test_a_guard_names_its_bribe(self):
        self.assertIn("- You release Zaps only for a bribe of at least 500 cats.", offers.facts("LIBERATE", GUARD, SPEAKER, "Zaps", []))
        text = offers.facts("LIBERATE", GUARD, {**SPEAKER, "bounty": 2000}, "Zaps", [])
        self.assertIn("- You release Zaps only for a bribe of at least 2,500 cats: the bounty of 2,000 cats on Zaps, and 500 more.", text)
        caged = {**SPEAKER, "bounty": 2000, "captors": "Holy Nation", "captorsID": "17-gamedata.base"}
        self.assertIn("- You break Zaps out of a cage of Holy Nation only for a fee of at least 2,500 cats: the bounty of 2,000 cats on Zaps, and 500 more.",
                      offers.facts("LIBERATE", {"factionID": "204-gamedata.base"}, caged, "Zaps", []))

    def test_a_treatment_names_the_repair_only_for_robotic_parts(self):
        self.assertNotIn("DEAL FACTS", offers.facts("HEAL", {"has_first_aid": True}, {"needs_first_aid": True}, "Zaps", []))
        robot = {"needs_first_aid": True, "needs_repair": True}
        self.assertIn("- Zaps has damaged robotic parts, and you repair them with your repair kit.",
                      offers.facts("HEAL", {"has_repair_kit": True}, robot, "Zaps", []))
        self.assertIn("- Zaps has damaged robotic parts, but you have no repair kit, so you treat only the flesh wounds.",
                      offers.facts("HEAL", {"has_first_aid": True}, robot, "Zaps", []))

    def test_a_mercenary_names_its_rate(self):
        self.assertIn("at least 2,500 cats for each day", offers.facts("FOLLOW", {**NPC, "faction": "Black Dog"}, SPEAKER, "Zaps", []))


if __name__ == "__main__":
    unittest.main()
