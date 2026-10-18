import os
import sys
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "server"))

from chat import action_dialogue, offers
from core import state
from core.settings import SETTINGS_DEFAULTS

NPC = {"money": 300, "inventory": [{"name": "Katana", "count": 1}, {"name": "Bread", "count": 2}, {"name": "Bread", "count": 1}]}
SPEAKER = {"money": 1000, "inventory": [{"name": "Dirty Loincloth", "count": 1}]}
GUARD = {**NPC, "squad_jobs": ["MAN_THE_GATE"]}


# A fixed profit target, because the INI of a dev install and the default can change
def setUpModule():
    patcher = mock.patch.object(offers, "load_settings", lambda: {**SETTINGS_DEFAULTS, "barter_profit_target": 10, "barter_relation_offset": 10})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def check(category, tag, npc=NPC, speaker=SPEAKER):
    return offers.check(category, offers.read(tag, category), npc, speaker)


class ReadTest(unittest.TestCase):
    def test_an_agreement_gets_the_part_of_its_category(self):
        self.assertEqual(offers.read("Fine. [AGREE: 1,500 cats] [JUDGMENT: 1]", "RECRUIT"), [("JOIN_PARTY", ""), ("TAKE_CATS", "1,500 cats")])
        self.assertEqual(offers.read("Sure. [agree: 2 days, 500 cats]", "FOLLOW"), [("HIRE", "2 days"), ("TAKE_CATS", "500 cats")])
        self.assertEqual(offers.read("Hold still. [AGREE]", "HEAL"), [("FIRST_AID", "")])

    def test_a_handover_and_a_trade_name_their_sides(self):
        self.assertEqual(offers.read("Take it. [GIVE: 200 cats, 2 Bread]", "THREATEN"), [("GIVE_CATS", "200 cats"), ("GIVE_ITEM", "2 Bread")])
        self.assertEqual(offers.read("[DEAL: 1 Katana (Ancient, Refitted Blade) for 4,600 cats, 1 Armoured Rags (colored) [alt]]", "BARTER"),
                         [("GIVE_ITEM", "1 Katana (Ancient, Refitted Blade)"), ("TAKE_CATS", "4,600 cats"), ("TAKE_ITEM", "1 Armoured Rags (colored) [alt]")])
        self.assertEqual(offers.read("[DEAL: food for nothing]", "BARTER"), [("GIVE_FOOD", "")])
        self.assertEqual(offers.read("[DEAL: 500 cats]", "BARTER"), [])

    def test_a_reply_without_the_tag_of_its_category_has_no_offer(self):
        self.assertIsNone(offers.read("[RECRUIT] Maybe. [JUDGMENT: 0]", "RECRUIT"))
        self.assertIsNone(offers.read("Fine, take it. [AGREE]", "THREATEN"))
        self.assertIsNone(offers.read("Fine. [AGREE]", None))

    def test_the_tag_leaves_the_spoken_words_whole(self):
        reply = "Here. [DEAL: 1 Armoured Rags (colored) [alt] for 50 cats] [JUDGMENT: 0]"
        self.assertEqual(offers.offer_text(reply, "BARTER"), "[DEAL: 1 Armoured Rags (colored) [alt] for 50 cats]")

    def test_the_refusal_and_the_attack(self):
        self.assertTrue(offers.refused("No. [REFUSE]"))
        self.assertTrue(offers.attacked("You asked for it! [ attack ]"))
        self.assertFalse(offers.refused("I refuse to pay that."))


class CheckTest(unittest.TestCase):
    def test_a_recruit_with_a_fee(self):
        offer, reason = check("RECRUIT", "[AGREE: 800 cats]")
        self.assertIsNone(reason)
        self.assertEqual(offer["gives"], [("JOIN_PARTY", None)])
        self.assertEqual(offer["takes"], [("CATS", 800)])

    def test_the_player_pays_only_the_cats_that_it_has(self):
        self.assertIsNone(check("RECRUIT", "[AGREE: 1001 cats]")[0])

    def test_a_part_of_another_category_breaks_the_offer(self):
        self.assertIsNone(check("THREATEN", "[GIVE: food]")[0])

    def test_a_handover_holds_only_what_the_npc_carries(self):
        offer, _ = check("THREATEN", "[GIVE: 200 cats, 3 bread]")
        self.assertEqual(offer["gives"], [("CATS", 200), ("ITEM", (3, "Bread"))])
        self.assertIsNone(check("THREATEN", "[GIVE: 4 Bread]")[0])
        self.assertIsNone(check("THREATEN", "[GIVE: 301 cats]")[0])
        self.assertIsNone(check("THREATEN", "[GIVE: Wakizashi]")[0])

    def test_the_length_of_a_hire(self):
        self.assertEqual(check("FOLLOW", "[AGREE: 2 days]")[0]["gives"], [("HIRE", 48)])
        self.assertEqual(check("FOLLOW", "[AGREE: 6 hours]")[0]["gives"], [("HIRE", 6)])
        self.assertIsNone(check("FOLLOW", "[AGREE]")[0])

    def test_a_mercenary_charges_its_daily_rate(self):
        merc = {**NPC, "faction": "Mercenary Guild"}
        self.assertIsNone(check("FOLLOW", "[AGREE: 1 day, 900 cats]", npc=merc)[0])
        rich = {**SPEAKER, "money": 5000}
        self.assertIsNotNone(check("FOLLOW", "[AGREE: 2 days, 4000 cats]", npc=merc, speaker=rich)[0])
        self.assertIsNotNone(check("FOLLOW", "[AGREE: 6 hours, 500 cats]", npc=merc)[0])
        self.assertIsNone(check("FOLLOW", "[AGREE: 1 day, 0 cats]", npc=merc)[0])

    def test_a_part_of_0_cats_is_no_cats(self):
        hire, _ = check("FOLLOW", "[AGREE: 1 day, 0 cats]")
        self.assertEqual((hire["gives"], hire["takes"]), ([("HIRE", 24)], []))
        self.assertIsNone(check("BARTER", "[DEAL: nothing for 0 cats]")[0])

    def test_a_release_costs_a_bribe_on_top_of_the_bounty(self):
        self.assertIsNone(check("LIBERATE", "[AGREE]", npc=GUARD)[0])
        self.assertIsNone(check("LIBERATE", "[AGREE: 499 cats]", npc=GUARD)[0])
        self.assertEqual(check("LIBERATE", "[AGREE: 500 cats]", npc=GUARD)[0]["gives"], [("RELEASE", None)])
        wanted = {**SPEAKER, "money": 5000, "bounty": 2000}
        self.assertIsNone(check("LIBERATE", "[AGREE: 2000 cats]", npc=GUARD, speaker=wanted)[0])
        self.assertIsNotNone(check("LIBERATE", "[AGREE: 2500 cats]", npc=GUARD, speaker=wanted)[0])


class TextTest(unittest.TestCase):
    def test_the_popup_names_the_real_deal(self):
        recruit, _ = check("RECRUIT", "[AGREE: 1500 cats]", speaker={**SPEAKER, "money": 2000})
        self.assertEqual(offers.popup_text(recruit, "Drifter", "Zaps"), "Drifter offers to join your squad for 1,500 cats.")
        handover, _ = check("THREATEN", "[GIVE: 200 cats, Katana]")
        self.assertEqual(offers.popup_text(handover, "Bandit", "Zaps"), "Bandit offers 200 cats and a Katana.")
        hire, _ = check("FOLLOW", "[AGREE: 2 days, 400 cats]")
        self.assertEqual(offers.popup_text(hire, "Drifter", "Zaps"), "Drifter offers to follow you for 2 days for 400 cats.")
        release, _ = check("LIBERATE", "[AGREE: 500 cats]", npc=GUARD)
        self.assertEqual(offers.popup_text(release, "Guard", "Zaps"), "Guard offers your release for 500 cats.")
        self.assertEqual(offers.actions(release), ["[ACTION: TAKE_CATS: 500]", "[ACTION: RELEASE_PRISONER]"])

    def test_a_hire_keeps_its_terms_for_the_renewal(self):
        hire, _ = check("FOLLOW", "[AGREE: 2 days, 400 cats]")
        self.assertEqual(offers.hire_terms(hire), (48, 400))
        free, _ = check("FOLLOW", "[AGREE: 6 hours]")
        self.assertEqual(offers.hire_terms(free), (6, 0))
        recruit, _ = check("RECRUIT", "[AGREE: 800 cats]")
        self.assertIsNone(offers.hire_terms(recruit))
        self.assertEqual(offers.renewal_text("Drifter", 48, 4000), "Drifter offers to renew following you for 2 days for 4,000 cats.")
        self.assertEqual(offers.renewal_text("Drifter", 6, 0), "Drifter offers to renew following you for 6 hours.")

    def test_the_memory_lines_are_deal_lines(self):
        handover, _ = check("THREATEN", "[GIVE: 200 cats]")
        accepted = offers.accepted_line(handover, "Bandit", "Zaps")
        declined = offers.declined_line(handover, "Bandit", "Zaps")
        self.assertEqual(accepted, "(Zaps accepted: Bandit gives Zaps 200 cats.)")
        self.assertEqual(declined, "(Zaps declined: Bandit offered 200 cats.)")
        for line in (accepted, declined, "(Bandit attacked Zaps.)", "(Doc treated Zaps for free.)", "(Zaps dismissed Hobbs.)"):
            self.assertTrue(offers.DEAL_LINE.search(f"[Day 1, 10:00] {line}"), line)
        self.assertFalse(offers.DEAL_LINE.search("[Day 1, 10:00] Zaps: Fine (for now)."))

    def test_a_fellow_captive_says_a_captive_line_at_the_accept(self):
        shackled = {"character_state": "enslaved", "captor": "17-gamedata.base"}
        recruit, _ = check("RECRUIT", "[AGREE]")
        self.assertEqual(offers.accept_end(recruit, shackled, shackled), "recruit_captive_accept")
        self.assertEqual(offers.accept_end(recruit, {**shackled, "captor": "5-gamedata.base"}, shackled), "recruit_accept")
        self.assertEqual(offers.accept_end(recruit, NPC, SPEAKER), "recruit_accept")
        handover, _ = check("THREATEN", "[GIVE: 2 Bread]")
        self.assertEqual(offers.accept_end(handover, shackled, shackled), "threaten_accept")

    def test_the_join_carries_its_fee_and_the_player_pays_before_the_npc_hands_over(self):
        recruit, _ = check("RECRUIT", "[AGREE: 800 cats]")
        self.assertEqual(offers.actions(recruit), ["[ACTION: JOIN_PARTY: 800]"])
        free, _ = check("RECRUIT", "[AGREE]")
        self.assertEqual(offers.actions(free), ["[ACTION: JOIN_PARTY: 0]"])
        handover, _ = check("THREATEN", "[GIVE: 2 Bread]")
        self.assertEqual(offers.actions(handover), ["[ACTION: GIVE_ITEM: Bread: 2]"])

    def test_the_command_holds_what_each_side_must_still_hold(self):
        offer, _ = check("BARTER", "[DEAL: Katana for 250 cats, Dirty Loincloth]")
        lines = offers.command(7, offer, "Bandit", "12", "3", "text").split("\n")
        self.assertEqual(lines[:4], ["CMD: OFFER: 7", "12 3", "Bandit", "text"])
        self.assertEqual(lines[4:], ["CHECK: CATS player 250", "CHECK: ITEM player 1 Dirty Loincloth", "CHECK: ITEM npc 1 Katana",
                                     "CHECK: ROOM player 1 Dirty Loincloth", "RESTOCK: inventory", "BOX: player 250 cats", "BOX: player 1 Dirty Loincloth", "BOX: npc 1 Katana"])

    def test_only_an_agreement_in_the_barter_window_sends_the_deal_lines(self):
        offer, _ = check("BARTER", "[DEAL: Katana for 250 cats]")
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
        return offers.check("BARTER", offers.read(tag, "BARTER"), npc, speaker)

    def test_a_shopkeeper_sells_the_stock_of_its_shop(self):
        offer, reason = self.barter("[DEAL: Katana for 3000 cats]")
        self.assertIsNone(reason)
        self.assertEqual(offer["gives"], [("ITEM", (1, "Katana (Ancient, Refitted Blade)"))])

    def test_a_trader_in_a_shop_keeps_what_it_carries(self):
        self.assertIsNone(self.barter("[DEAL: 1 Bread for 1000 cats]")[0])
        sale, _ = self.barter("[DEAL: Katana for 3000 cats]")
        self.assertEqual(offers.actions(sale), ["[ACTION: TAKE_CATS: 3000]", "[ACTION: SELL_ITEM: Katana (Ancient, Refitted Blade): 1]"])
        away = {key: value for key, value in SHOP.items() if key != "stock"}
        self.assertEqual(offers.actions(self.barter("[DEAL: 1 Bread for 1000 cats]", npc=away)[0])[1], "[ACTION: GIVE_ITEM: Bread: 1]")

    def test_a_trader_in_a_shop_buys_into_the_stock_and_another_npc_must_carry_what_it_buys(self):
        shop, _ = self.barter("[DEAL: 50 cats for Dirty Loincloth]")
        self.assertEqual(offers.actions(shop), ["[ACTION: BUY_ITEM: Dirty Loincloth: 1]", "[ACTION: GIVE_CATS: 50]"])
        self.assertNotIn("CHECK: ROOM player 1 Dirty Loincloth", offers.checks(shop))
        away = {key: value for key, value in SHOP.items() if key != "stock"}
        carried, _ = self.barter("[DEAL: 50 cats for Dirty Loincloth]", npc=away)
        self.assertEqual(offers.actions(carried)[0], "[ACTION: TAKE_ITEM: Dirty Loincloth: 1]")
        self.assertIn("CHECK: ROOM player 1 Dirty Loincloth", offers.checks(carried))

    def test_another_npc_hands_over_only_what_it_carries(self):
        self.assertIsNone(self.barter("[DEAL: Katana for 3000 cats]", npc={**SHOP, "squad_jobs": []})[0])

    def test_a_barman_whose_job_reads_trading_sells_the_stock(self):
        barman = {**SHOP, "squad_jobs": [], "is_trader": True}
        self.assertIsNotNone(self.barter("[DEAL: Katana for 3000 cats]", npc=barman)[0])

    def test_a_trade_at_a_loss_holds_because_the_worth_only_guides_the_model(self):
        self.assertIsNotNone(self.barter("[DEAL: Katana for 10 cats]")[0])
        self.assertIsNotNone(self.barter("[DEAL: Katana for Dirty Loincloth]")[0])

    def test_the_relation_sets_the_profit_that_the_npc_wants(self):
        self.assertEqual([offers.profit_share(SHOP, relation) for relation in (-60, -59, -25, -24, 24, 25, 59, 60)], [0.3, 0.2, 0.2, 0.1, 0.1, 0, 0, 0])

    def test_an_npc_that_is_not_a_trader_wants_more_profit(self):
        self.assertEqual([offers.profit_share(NPC, relation) for relation in (-60, 0, 60)], [0.4, 0.2, 0])

    def test_the_profit_target_setting_moves_each_relation_band_down_to_zero(self):
        with mock.patch.object(offers, "load_settings", lambda: {**SETTINGS_DEFAULTS, "barter_profit_target": 25, "barter_relation_offset": 10}):
            self.assertEqual([offers.profit_share(SHOP, relation) for relation in (-60, 0, 25, 60)], [0.45, 0.25, 0.05, 0])

    def test_the_relation_offset_setting_sizes_each_step(self):
        with mock.patch.object(offers, "load_settings", lambda: SETTINGS_DEFAULTS):
            self.assertEqual([offers.profit_share(SHOP, relation) for relation in (-60, -25, 0, 25, 60)], [5.0, 4.5, 4.0, 3.0, 2.5])
            self.assertEqual(offers.profit_share(NPC, 0), 4.5)

    def test_the_stock_sets_the_price_at_its_highest(self):
        self.assertEqual(offers.price_of("First Aid Kit", offers.goods(SHOP, "BARTER")), 132)

    def test_a_name_without_its_grade_needs_one_grade_held(self):
        two = {**BUYER, "inventory": BUYER["inventory"] + [{"name": "Chain Shirt (Standard)", "count": 1, "price": 10000}]}
        self.assertEqual(offers.held(BUYER["inventory"], "chain shirt"), ("Chain Shirt (High)", 1))
        self.assertEqual(offers.held(two["inventory"], "Chain Shirt"), (None, 0))

    def test_charity_costs_the_npc_nothing_but_has_tight_limits(self):
        poor = {**SHOP, "money": 0, "stock": [], "inventory": []}
        cats, _ = self.barter("[DEAL: 50 cats for nothing]", npc=poor)
        self.assertTrue(cats["charity"])
        self.assertEqual(offers.actions(cats), ["[ACTION: ADD_CATS: 50]"])
        self.assertEqual(offers.checks(cats), [])
        food, _ = self.barter("[DEAL: food for nothing]", npc=poor)
        self.assertEqual(offers.actions(food), ["[ACTION: SPAWN_ITEM: Dried Gristle Flaps]"])
        self.assertIn("only for charity", self.barter("[DEAL: food for 10 cats]")[1])
        self.assertIsNone(self.barter("[DEAL: 1 Dried Meat for nothing]", npc=poor)[0])
        self.assertEqual(self.barter("[DEAL: 500 cats for nothing]", npc=poor)[0]["gives"], [("CATS", 50)])
        self.assertIsNone(self.barter("[DEAL: 1 Katana for nothing]")[0])

    def test_a_second_charity_in_a_day_is_no_hard_limit(self):
        state.CHARITY_DAYS[SHOP["npc_id"]] = SHOP["day"]
        self.assertTrue(self.barter("[DEAL: 10 cats for nothing]", npc={**SHOP, "money": 0})[0]["charity"])

    def test_a_gift_raises_the_relation_by_its_worth(self):
        self.assertEqual(self.barter("[DEAL: nothing for 1499 cats]")[0]["gift"], 2)
        self.assertEqual(self.barter("[DEAL: nothing for 499 cats]")[0]["gift"], 0)
        self.assertEqual(self.barter("[DEAL: nothing for Chain Shirt]")[0]["gift"], 10)
        self.assertEqual(offers.popup_text(self.barter("[DEAL: nothing for 500 cats]")[0], "Shopkeeper", "Zaps"), "Shopkeeper accepts your gift of 500 cats.")

    def test_the_prompt_lists_the_goods_and_the_prices_of_the_items_named(self):
        self.assertEqual(offers.stocktake(SHOP), "YOUR GOODS: 1 Katana (Ancient, Refitted Blade), 2 First Aid Kit.")
        guide = offers.price_guide("How much for the katana? I could sell my chain shirt.", SHOP, BUYER, "Zaps")
        self.assertEqual(guide, ["You have 1 Katana (Ancient, Refitted Blade): you sell each for at least 3,000 cats.",
                                 "Zaps has 1 Chain Shirt (High): you pay at most 18,181 cats each."])

    def test_the_npc_takes_its_profit_only_from_what_it_buys(self):
        hated = offers.price_guide("How much for the katana? I could sell my chain shirt.", SHOP, BUYER, "Zaps", relation=-60)
        self.assertEqual(hated, ["You have 1 Katana (Ancient, Refitted Blade): you sell each for at least 3,000 cats.",
                                 "Zaps has 1 Chain Shirt (High): you pay at most 15,384 cats each."])
        self.assertEqual(offers.price_guide("My chain shirt?", {**SHOP, "squad_jobs": []}, BUYER, "Zaps"), ["Zaps has 1 Chain Shirt (High): you pay at most 16,666 cats each."])

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

    def test_the_named_items_of_both_sides_are_what_a_follow_up_carries(self):
        said = "How much for the katana? I could sell my chain shirt."
        self.assertEqual(offers.named_items(said, SHOP, BUYER), ["Katana (Ancient, Refitted Blade)", "Chain Shirt (High)"])
        self.assertEqual(offers.named_items("How many cats, you say?\nFor a good price. Not cheap.", SHOP, BUYER), [])
        carried = "How many cats?\n" + "\n".join(offers.named_items(said, SHOP, BUYER))
        self.assertEqual(offers.price_guide(carried, SHOP, BUYER, "Zaps"), offers.price_guide(said, SHOP, BUYER, "Zaps"))

    def test_a_kind_word_prices_at_most_ten_items_of_each_side(self):
        store = {**SHOP, "inventory": [], "stock": [{"name": f"Food {n}", "count": 1, "price": 10, "kind": "food"} for n in range(15)]}
        self.assertEqual(len(offers.price_guide("Any food?", store, BUYER, "Zaps")), offers.PRICE_LINES)


SQUAD = [{"key": "3", "inventory": BUYER["inventory"]}, {"key": "8", "inventory": [{"name": "Bread", "count": 4, "price": 50}]}]
TABLE = {"take_cats": 2950, "give_cats": 0, "take": [{"holder": "8", "name": "Bread", "count": 2}], "give": [{"name": "Katana (Ancient, Refitted Blade)", "count": 1}]}
PURCHASE = {"give_cats": 95, "take": [{"holder": "3", "name": "Dirty Loincloth", "count": 1}]}


class BarterWindowTest(unittest.TestCase):
    def test_the_agreement_tag(self):
        self.assertTrue(offers.agreed("Fine, it's yours. [ agree ]"))
        self.assertFalse(offers.agreed("I agree that it's hot."))

    def test_an_item_of_any_squad_mate_leaves_its_holder(self):
        offer, _ = offers.check("BARTER", offers.table_parts(TABLE), SHOP, BUYER, SQUAD)
        self.assertEqual(offer["takes"], [("CATS", 2950), ("ITEM", (2, "Bread", "8"))])
        self.assertEqual(offers.voiced(offer, "Shopkeeper|12>3"), ["Shopkeeper|12>3: [ACTION: TAKE_CATS: 2950]", "Shopkeeper|12>8: [ACTION: BUY_ITEM: Bread: 2]",
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
        offer, _, lines, lean = offers.on_table({**TABLE, "take_cats": 2910}, SHOP, BUYER, SQUAD, "Zaps")
        self.assertIsNotNone(offer)
        self.assertEqual(lines, ["On the table, Zaps gives 2,910 cats and 2 Bread, and they want a Katana (Ancient, Refitted Blade) from you."])
        self.assertEqual(lean, [(2, "The deal on the table is a fair profit: it meets your desired profit.")])

    def test_the_gap_prices_each_side_as_the_price_guide_does(self):
        self.assertEqual(offers.price_guide("Katana, Bread", SHOP, {"inventory": offers.pooled(SQUAD)}, "Zaps"),
                         ["You have 1 Katana (Ancient, Refitted Blade): you sell each for at least 3,000 cats.", "Zaps has 4 Bread: you pay at most 45 cats each."])
        self.assertEqual(offers.on_table({**TABLE, "take_cats": 2908}, SHOP, BUYER, SQUAD, "Zaps")[3], [(-1, "The deal on the table is a suboptimal profit: it misses your desired profit by about 2 cats.")])

    def test_a_profit_below_the_one_that_the_npc_wants_leans_it_to_refuse(self):
        offer, _, _, lean = offers.on_table(PURCHASE, SHOP, BUYER, SQUAD, "Zaps")
        self.assertIsNotNone(offer)
        self.assertEqual(lean, [(-1, "The deal on the table is a suboptimal profit: it misses your desired profit by about 5 cats.")])
        self.assertEqual(offers.on_table(PURCHASE, SHOP, BUYER, SQUAD, "Zaps", relation=30)[3], [(2, "The deal on the table is a fair profit: it beats your desired profit by about 5 cats.")])

    def test_a_bigger_profit_on_the_table_leans_harder_to_agree(self):
        self.assertEqual(offers.on_table({**TABLE, "take_cats": 2900}, SHOP, BUYER, SQUAD, "Zaps", relation=30)[3], [(2, "The deal on the table is a fair profit: it meets your desired profit.")])
        self.assertEqual(offers.on_table({**TABLE, "take_cats": 3670}, SHOP, BUYER, SQUAD, "Zaps")[3], [(3, "The deal on the table is a good profit: it beats your desired profit by about 760 cats.")])
        self.assertEqual(offers.on_table({**TABLE, "take_cats": 4420}, SHOP, BUYER, SQUAD, "Zaps")[3], [(4, "The deal on the table is a big profit: it beats your desired profit by about 1,510 cats.")])
        self.assertEqual(offers.on_table({"take_cats": 600}, SHOP, BUYER, SQUAD, "Zaps")[3], [(4, "The deal on the table is a big profit: it beats your desired profit by about 600 cats.")])

    def test_a_big_profit_outweighs_hate_but_a_small_one_does_not(self):
        hated = action_dialogue.lean("BARTER", SHOP, BUYER, -60)
        small = offers.on_table(PURCHASE, SHOP, BUYER, SQUAD, "Zaps", relation=-60)[3]
        big = offers.on_table({**TABLE, "take_cats": 4420}, SHOP, BUYER, SQUAD, "Zaps", relation=-60)[3]
        self.assertIn("YOUR THOUGHT: You are inclined to refuse.", offers.facts("BARTER", SHOP, BUYER, "Zaps", hated + small, relation=-60))
        self.assertIn("YOUR THOUGHT: You are inclined to agree.", offers.facts("BARTER", SHOP, BUYER, "Zaps", hated + big, relation=-60))

    def test_a_deal_below_the_price_of_the_npc_leans_it_to_refuse_at_any_relation(self):
        for relation, missed in ((60, 100), (None, 110), (-25, 117)):
            offer, _, lines, lean = offers.on_table({**TABLE, "take_cats": 2800}, SHOP, BUYER, SQUAD, "Zaps", relation=relation)
            self.assertIsNotNone(offer)
            self.assertEqual(lean, [(-2, f"The deal on the table is a loss: it misses your desired profit by about {missed} cats.")])
        self.assertIn("- On the table, Zaps gives 2,800 cats", offers.facts("BARTER", SHOP, BUYER, "Zaps", [], table=lines))

    def test_a_table_that_breaks_a_hard_limit_cannot_be_agreed(self):
        offer, reason, lines, lean = offers.on_table({**TABLE, "take": [{"holder": "3", "name": "Bread", "count": 2}]}, SHOP, BUYER, SQUAD, "Zaps")
        self.assertIsNone(offer)
        self.assertIn("does not hold", reason)
        self.assertEqual(lines[1], "You cannot agree to it as it is, because Zaps does not have 2 Bread.")
        self.assertEqual(lean, [])

    def test_the_turn_message_names_the_broken_limit_of_the_table(self):
        soup = {"take_cats": 600, "give": [{"name": "Meat and Barley Rice Soup", "count": 1}]}
        broken = [(soup, "someone else bought your 1 Meat and Barley Rice Soup"), ({**TABLE, "give_cats": 9000}, "you have fewer than 9000 cats"),
                  ({**TABLE, "take_cats": 6000}, "Zaps has fewer than 6000 cats"), ({"give": TABLE["give"]}, "you give charity only as cats")]
        for deal, why in broken:
            with self.subTest(why=why):
                self.assertEqual(offers.on_table(deal, SHOP, BUYER, SQUAD, "Zaps")[2][1], f"You cannot agree to it as it is, because {why}.")

    def test_only_a_trade_names_where_accept_restocks(self):
        offer = offers.on_table(TABLE, SHOP, BUYER, SQUAD, "Zaps")[0]
        self.assertIn("RESTOCK: stock", offers.command(7, offer, "Shopkeeper", "12", "3", "text").split("\n"))
        handover, _ = check("THREATEN", "[GIVE: 2 Bread]")
        charity = offers.on_table({"give_cats": 50}, SHOP, BUYER, SQUAD, "Zaps")[0]
        for offer in (handover, charity):
            self.assertNotIn("RESTOCK", offers.command(7, offer, "Bandit", "12", "3", "text"))

    def test_an_item_that_the_npc_lost_from_the_table_stays_its_own(self):
        soup = {"take_cats": 800, "give": [{"name": "Meat and Barley Rice Soup", "count": 1}]}
        lost = [{"name": "Meat and Barley Rice Soup", "count": 1, "price": 721}]
        store = offers.with_lost(SHOP, lost)
        offer, _, _, lean = offers.on_table(soup, store, BUYER, SQUAD, "Zaps")
        self.assertEqual(offer["gives"], [("ITEM", (1, "Meat and Barley Rice Soup"))])
        self.assertEqual(lean, [(2, "The deal on the table is a fair profit: it beats your desired profit by about 79 cats.")])
        self.assertIn("1 Meat and Barley Rice Soup", offers.stocktake(store))
        self.assertEqual(offers.with_lost({**SHOP, "squad_jobs": []}, lost)["inventory"][-1], lost[0])
        self.assertIs(offers.with_lost(SHOP, []), SHOP)

    def test_a_gift_charity_and_an_empty_table(self):
        self.assertEqual(offers.on_table({"take_cats": 600}, SHOP, BUYER, SQUAD, "Zaps")[2][1], "It is a gift to you.")
        self.assertEqual(offers.on_table({"give_cats": 50}, SHOP, BUYER, SQUAD, "Zaps")[2:], (["On the table, Zaps gives nothing, and they want 50 cats from you.", "It is a plea for charity."], []))
        self.assertEqual(offers.on_table({}, SHOP, BUYER, SQUAD, "Zaps"), (None, "the table is empty", ["Nothing is on the table yet."], []))


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

    def test_a_trade_gives_the_profit_that_the_npc_wants_only_as_prices(self):
        text = offers.facts("BARTER", SHOP, BUYER, "Zaps", [], said="chain shirt", relation=-30)
        self.assertIn("- Zaps has 1 Chain Shirt (High): you pay at most 16,666 cats each.", text)
        self.assertNotIn("%", text)

    def test_a_trade_names_the_pull_of_a_profit(self):
        self.assertIn("- A trade that gets you more than you give is a profit: the bigger the profit, the more gladly you take it.",
                      offers.facts("BARTER", NPC, SPEAKER, "Zaps", []))

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

    def test_a_treatment_names_the_repair_only_for_robotic_parts(self):
        self.assertNotIn("DEAL FACTS", offers.facts("HEAL", {"has_first_aid": True}, {"needs_first_aid": True}, "Zaps", []))
        robot = {"needs_first_aid": True, "needs_repair": True}
        self.assertIn("- Zaps has damaged robotic parts, and you repair them with your repair kit.",
                      offers.facts("HEAL", {"has_repair_kit": True}, robot, "Zaps", []))
        self.assertIn("- Zaps has damaged robotic parts, but you have no repair kit, so you treat only the flesh wounds.",
                      offers.facts("HEAL", {"has_first_aid": True}, robot, "Zaps", []))

    def test_a_mercenary_names_its_rate(self):
        self.assertIn("at least 2,500 cats for each day", offers.facts("FOLLOW", {**NPC, "faction": "Black Dog"}, SPEAKER, "Zaps", []))
        self.assertNotIn("DEAL FACTS", offers.facts("FOLLOW", NPC, SPEAKER, "Zaps", []))


if __name__ == "__main__":
    unittest.main()
