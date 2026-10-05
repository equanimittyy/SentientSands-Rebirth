import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from chat import scene_text


def relation(value):
    return scene_text.relation_text("Drifter", "Nameless", value, met=True)


class ScaleTest(unittest.TestCase):
    def test_the_relation_bands_match_the_game_bar_and_add_steps_at_ten(self):
        group = "Nameless, the group Drifter travels with"
        expected = {
            -90: f"You loathe {group}.", -89: f"You feel hostile towards {group}.",
            -60: f"You feel hostile towards {group}.", -59: f"You feel unfriendly towards {group}.",
            -25: f"You feel unfriendly towards {group}.", -24: f"You feel mildly hostile towards {group}.",
            -10: f"You feel mildly hostile towards {group}.", -9: f"You feel neutral towards {group}.",
            9: f"You feel neutral towards {group}.", 10: f"You feel mildly warm towards {group}.",
            24: f"You feel mildly warm towards {group}.", 25: f"You feel friendly towards {group}.",
            59: f"You feel friendly towards {group}.", 60: f"You trust {group}.",
            89: f"You trust {group}.", 90: f"You feel devoted to {group}.",
        }
        self.assertEqual({value: relation(value) for value in expected}, expected)

    def test_a_first_meeting_and_the_companions_come_before_the_relation(self):
        self.assertEqual(scene_text.relation_text("Izumi", "Nameless", 30, met=False, companions=["Stick"]),
                         "You have never spoken with Izumi before. Earlier you spoke with Stick, who travels with Izumi. You feel friendly towards Nameless, the group Izumi travels with.")
        self.assertEqual(scene_text.relation_text("Izumi", "Nameless", 0, met=True, companions=["Stick", "Mikse"]),
                         "Earlier you spoke with Stick and Mikse, who travel with Izumi. You feel neutral towards Nameless, the group Izumi travels with.")

    def test_the_overheard_note_names_the_listeners_and_the_other_speaker(self):
        self.assertEqual(scene_text.overheard_note(["Stick", "Mikse", "Ruka"], "Izumi"), "Stick, Mikse, and Ruka heard your conversation with Izumi.")
        self.assertEqual(scene_text.overheard_note(["Stick"], None), "Stick heard your conversation.")

    def test_the_memory_header_names_the_other_speakers_and_the_listeners(self):
        self.assertEqual(scene_text.memory_header(["Stick"], ["Izumi", "Mikse"], False), "You spoke with Stick. Izumi and Mikse heard it.")
        self.assertEqual(scene_text.memory_header(["Stick"], [], False), "You spoke with Stick.")
        self.assertEqual(scene_text.memory_header(["Stick", "Jorge"], [], True), "You overheard Stick and Jorge.")

    def test_the_library_labels_do_not_speak_to_the_npc(self):
        self.assertEqual(scene_text.conversation_label(["Stick"], ["Izumi"], False), "Conversation with Stick, heard by Izumi")
        self.assertEqual(scene_text.memory_label(["Stick", "Jorge"], [], True), "Memory of an overheard conversation of Stick and Jorge")

    def test_the_faction_stance_bands(self):
        stances = {value: scene_text._scale(value, scene_text.FACTION_STANCE) for value in (-30, -29, -10, -9, 9, 10, 49, 50)}
        self.assertEqual(stances, {-30: "hostile", -29: "unfriendly", -10: "unfriendly", -9: "neutral", 9: "neutral", 10: "friendly", 49: "friendly", 50: "allied"})

    def test_hunger_reads_as_you_or_they(self):
        self.assertEqual([scene_text.hunger_text("They", level) for level in (79, 80, 199, 200, 249, 250)], [
            "They look starving.", "They look very hungry.", "They look very hungry.",
            "They look hungry.", "They look hungry.", "They look well fed.",
        ])
        self.assertEqual(scene_text.hunger_text("You", 10), "You are starving.")

    def test_blood_comes_before_the_share_left(self):
        self.assertEqual(scene_text.blood_text("They", {"blood": 100, "max_blood": 100, "blood_rate": 0.5}), "They are bleeding.")
        self.assertEqual(scene_text.blood_text("You", {"blood": 40, "max_blood": 100}), "You are weak from blood loss.")
        self.assertEqual(scene_text.blood_text("They", {"blood": 80, "max_blood": 100}), "They look wounded.")
        self.assertEqual(scene_text.blood_text("They", {"blood": 85, "max_blood": 100}), "")

    def test_health_reads_healthy_only_without_a_wound(self):
        self.assertEqual(scene_text.health_text("They", {"blood": 85, "max_blood": 100}), "They seem healthy.")
        self.assertEqual(scene_text.health_text("You", {"blood": 100, "max_blood": 100}), "You are healthy.")
        crippled = {"blood": 100, "max_blood": 100, "limbs": {"left_leg": -10, "left_leg_max": 100}}
        self.assertEqual(scene_text.health_text("They", crippled), "Their left leg is crippled.")
        self.assertEqual(scene_text.health_text("You", {**crippled, "blood": 80}), "You are wounded. Your left leg is crippled.")

    def test_combat_money_and_rumor_age_bounds(self):
        self.assertEqual([scene_text.combat_text({"melee_attack": v}) for v in (9, 10, 30, 60, 80)], [step for _, step in scene_text.COMBAT])
        self.assertEqual([scene_text._scale(v, scene_text.MONEY) for v in (49, 50, 1000, 10000)], [step for _, step in scene_text.MONEY])
        self.assertEqual([scene_text._scale(v, scene_text.RUMOR_AGE) for v in (0, 1, 2, 7)], [step for _, step in scene_text.RUMOR_AGE])


class SentenceTest(unittest.TestCase):
    def test_a_person_names_the_sex_only_as_man_or_woman(self):
        self.assertEqual(scene_text.person("Shek", "female"), "a Shek woman")
        self.assertEqual(scene_text.person("Greenlander", "Male"), "a Greenlander man")
        self.assertEqual(scene_text.person("Skeleton", "Other"), "a Skeleton")
        self.assertEqual(scene_text.person("Unknown", "male"), "")

    def test_equipment_splits_into_worn_and_carried(self):
        items = [
            {"name": "Samurai Armour", "equipped": True, "slot": "body"},
            {"name": "Leather Boots", "equipped": True, "slot": "boots"},
            {"name": "Katana", "equipped": True, "slot": "weapon"},
            {"name": "Iron Club", "equipped": True, "slot": "weapon"},
            {"name": "Repair Kit", "equipped": False, "slot": "none"},
        ]
        self.assertEqual(scene_text.equipment_text("They", items), "They wear Samurai Armour and Leather Boots, and carry a Katana and an Iron Club.")
        self.assertEqual(scene_text.equipment_text("You", items[2:3]), "You carry a Katana.")
        self.assertEqual(scene_text.equipment_text("You", items[4:]), "")

    def test_strength_compares_the_player_with_the_npc(self):
        self.assertEqual([scene_text.strength_text("Stick", {"melee_attack": 50, "melee_defence": 20}, {"melee_defence": v}) for v in (19, 20, 40, 60, 80)], [step.format(name="Stick") for _, step in scene_text.STRENGTH_GAP])
        self.assertEqual(scene_text.strength_text("Stick", {"melee_attack": 50}, {"strength": 90}), "")

    def test_limbs(self):
        limbs = {"left_arm": -10, "left_arm_max": 100, "right_leg": 40, "right_leg_max": 100, "head": 100, "head_max": 100}
        self.assertEqual(scene_text.limbs_text(limbs), "Your left arm is crippled and your right leg is hurt.")
        self.assertEqual(scene_text.limbs_text({"left_leg": -100, "left_leg_max": 100}), "Your left leg is gone.")
        self.assertEqual([scene_text.limbs_text({"head": hp, "head_max": 100}) for hp in (69, 70)], ["Your head is hurt.", ""])

    def test_rumors_come_newest_first_with_their_age(self):
        lines = [(9 * 1440 + 850, "Shek raiders were seen near the Bad Teeth."), (11 * 1440 + 1142, "A caravan never arrived")]
        self.assertEqual(scene_text.rumors_text(lines, 12), "Rumours:\nYesterday you heard a rumour: A caravan never arrived. A few days ago you heard a rumour: Shek raiders were seen near the Bad Teeth. These are only rumours; bring them up only when they fit the conversation.")
        self.assertTrue(scene_text.rumors_text(lines[:1], None).startswith("Rumours:\nYou heard a rumour:"))
        self.assertTrue(scene_text.rumors_text([*lines, (None, "Beep freed the slaves of Rebirth.")], 12).startswith("Rumours:\nYou heard a rumour: Beep freed the slaves of Rebirth. Yesterday"))
        self.assertEqual(scene_text.rumors_text([], 12), "")

    def test_the_player_seen_by_the_npc(self):
        text = scene_text.player_text("Drifter", True, "Skeleton", "Other", "Sentient machines from ancient times", {"blood": 100, "max_blood": 100, "hunger": 10}, False, "Nameless", "", [])
        self.assertEqual(text, "The person before you:\nThe individual before you is Drifter, a Skeleton. Sentient machines from ancient times. They seem healthy. They are a member of Nameless.")
        self.assertTrue(scene_text.player_text("Drifter", False, "Unknown", "male", "", {}, True, "Unknown", "", []).startswith("The player:\nNearby is Drifter."))
        self.assertTrue(scene_text.player_text("Drifter", True, "Unknown", "male", "", {}, True, "Unknown", "", [], "Bar").endswith("They are inside Bar."))

    def test_the_player_shows_its_state_and_wounds_as_an_npc_does(self):
        medical = {"blood": 100, "max_blood": 100, "is_unconscious": True, "limbs": {"right_arm": -100, "right_arm_max": 100}}
        text = scene_text.player_text("Drifter", True, "Unknown", "male", "", medical, False, "Unknown", "", [], state="imprisoned")
        self.assertEqual(text, "The person before you:\nThe individual before you is Drifter. They are imprisoned and cannot move freely. Their right arm is gone. They are unconscious.")
        self.assertEqual(scene_text.state_text("They", "escaped-slave"), "They escaped slavery, and they are hunted.")

    def test_the_npc_from_its_profile_repeats_neither_faction_nor_current_job(self):
        profile = {"Relation": -12, "Faction": "The Holy Nation", "CurrentJob": "Patrolling the town", "ConversationHistory": ["x"]}
        text = scene_text.npc_text(profile, profile, "Drifter", "Nameless", met=True, major=True, in_player_faction=False, feels_hunger=True)
        self.assertEqual(text, "You:\nYou feel mildly hostile towards Nameless, the group Drifter travels with. You belong to The Holy Nation, a major world power. You will not leave it for Drifter's squad without an extremely compelling reason, such as Drifter saving your life more than once.")

    def test_the_npc_from_its_live_context(self):
        profile = {"Relation": 30, "Faction": "The Holy Nation", "CurrentJob": "Guarding the town"}
        context = {
            "faction": "The Holy Nation", "job": "Patrol", "relation": -5, "money": 85, "character_state": "imprisoned",
            "medical": {"hunger": 300, "blood": 100, "max_blood": 100}, "stats": {"melee_attack": 40, "melee_defence": 20},
            "memories": {"short_term": [], "long_term": [2, 99]}, "environment": {"indoors": True},
        }
        text = scene_text.npc_text(context, profile, "Drifter", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True)
        self.assertEqual(text, "You:\nYou feel friendly towards Nameless, the group Drifter travels with. You are imprisoned and cannot move freely. Your current task: Patrol. Your faction, The Holy Nation, is neutral towards Nameless. You are well fed. You are healthy. You are indoors. You are a seasoned fighter. You have a little money. Drifter once saved your life.")

    def test_an_npc_that_changed_faction_hears_the_old_and_the_new_one(self):
        context = {"faction": "Band of Bones"}
        text = scene_text.npc_text(context, {"Faction": "Shek Kingdom"}, "Drifter", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True, faction_description="A violent band of Shek bandits")
        self.assertIn("You belonged to Shek Kingdom, but now you belong to Band of Bones. A violent band of Shek bandits.", text)
        text = scene_text.npc_text(context, {}, "Drifter", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True)
        self.assertIn("You now belong to Band of Bones.", text)

    def test_only_a_trader_owns_the_shop_that_it_is_in(self):
        bar = {"in_shop": True, "building_name": "Bar", "environment": {"indoors": True}}
        customer = scene_text.npc_text(bar, {}, "Stick", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True)
        self.assertIn("You are inside Bar.", customer)
        self.assertNotIn("trader", customer)
        owner = scene_text.npc_text({**bar, "is_trader": True}, {}, "Stick", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True)
        self.assertIn("You are a trader.", owner)
        self.assertIn("You are in your shop, Bar.", owner)
        self.assertEqual(scene_text.building_text({"building_name": "Unknown", "environment": {"indoors": True}}, False), "You are indoors.")
        self.assertEqual(scene_text.building_text({"building_name": "Unknown", "environment": {"indoors": False}}, True), "")

    def test_the_location_names_the_building_and_the_town_or_the_zone(self):
        def location(building="Unknown", **environment):
            return scene_text.location_name({"building_name": building, "environment": environment})
        self.assertEqual(location("Bar", town_name="The Hub", zone_name="Border Zone"), "Bar, The Hub")
        self.assertEqual(location(town_name="The Hub", zone_name="Border Zone"), "The Hub")
        self.assertEqual(location("Shack", zone_name="Vain"), "Shack, Vain")
        self.assertEqual(location(zone_name="Vain"), "Wilderness, Vain")
        self.assertEqual(location(), "Wilderness")

    def test_the_strength_of_the_player_follows_the_fight_skill_of_the_npc(self):
        text = scene_text.npc_text({"stats": {"strength": 60, "toughness": 50, "melee_attack": 40}, "environment": {"indoors": True}}, {}, "Stick", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True, player_stats={"strength": 90, "melee_attack": 5})
        self.assertIn("You are indoors. You are a seasoned fighter. Stick looks much weaker than you.", text)

    def test_the_npc_names_the_companions_that_it_spoke_with(self):
        text = scene_text.npc_text({}, {"Relation": 0}, "Izumi", "Nameless", met=False, major=False, in_player_faction=False, feels_hunger=True, companions=["Stick"])
        self.assertTrue(text.startswith("You:\nYou have never spoken with Izumi before. Earlier you spoke with Stick, who travels with Izumi. You feel neutral towards Nameless, the group Izumi travels with."))

    def test_a_squad_member_travels_with_the_player(self):
        text = scene_text.npc_text({"faction": "Nameless", "relation": 100}, {"Faction": "Nameless"}, "Drifter", "Nameless", met=True, major=False, in_player_faction=True, feels_hunger=True)
        self.assertIn("You travel in Drifter's squad, and Drifter leads it.", text)
        self.assertNotIn("Your faction", text)

    def test_location(self):
        self.assertEqual(scene_text.location_text({"town_name": "Blister Hill"}), "You are in Blister Hill.")
        self.assertEqual(scene_text.location_text({}), "You are somewhere in the wasteland.")
        self.assertEqual(scene_text.location_text({"town_name": "Squin", "in_town": True, "weather": 1}), "You are in Squin. You are inside the town walls. A dust storm blows.")
        self.assertEqual(scene_text.location_text({"in_town": False, "weather": 0}), "You are somewhere in the wasteland.")


if __name__ == "__main__":
    unittest.main()
