import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import scene_text


def relation(value):
    return scene_text.relation_text("Drifter", value, met=True)


class ScaleTest(unittest.TestCase):
    def test_the_relation_bands_match_the_game_bar_and_add_steps_at_ten(self):
        expected = {
            -90: "You loathe Drifter.", -89: "You are hostile towards Drifter.",
            -60: "You are hostile towards Drifter.", -59: "You are unfriendly towards Drifter.",
            -25: "You are unfriendly towards Drifter.", -24: "You are mildly hostile towards Drifter.",
            -10: "You are mildly hostile towards Drifter.", -9: "You feel neutral towards Drifter.",
            9: "You feel neutral towards Drifter.", 10: "You are mildly warm towards Drifter.",
            24: "You are mildly warm towards Drifter.", 25: "You are friendly towards Drifter.",
            59: "You are friendly towards Drifter.", 60: "You trust Drifter as an ally.",
            89: "You trust Drifter as an ally.", 90: "You are devoted to Drifter.",
        }
        self.assertEqual({value: relation(value) for value in expected}, expected)

    def test_a_first_meeting_comes_before_the_relation(self):
        self.assertEqual(scene_text.relation_text("Drifter", 0, met=False), "You have never spoken with Drifter before. You feel neutral towards Drifter.")

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
        self.assertEqual(scene_text.blood_text("They", {"blood": 85, "max_blood": 100}), "They seem healthy.")

    def test_combat_money_distance_and_rumor_age_bounds(self):
        self.assertEqual([scene_text.combat_text({"melee_attack": v}) for v in (9, 10, 30, 60, 80)], [step for _, step in scene_text.COMBAT])
        self.assertEqual([scene_text._scale(v, scene_text.MONEY) for v in (49, 50, 1000, 10000)], [step for _, step in scene_text.MONEY])
        self.assertEqual([scene_text._scale(v, scene_text.DISTANCE) for v in (2.4, 2.5, 10, 30)], [step for _, step in scene_text.DISTANCE])
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

    def test_attributes_name_only_the_high_and_low_ones(self):
        self.assertEqual(scene_text.attributes_text({"strength": 60, "toughness": 50, "athletics": 5, "dexterity": 30}), "You are strong and tough, but slow.")
        self.assertEqual(scene_text.attributes_text({"strength": 30}), "")

    def test_limbs(self):
        limbs = {"left_arm": -10, "left_arm_max": 100, "right_leg": 40, "right_leg_max": 100, "head": 100, "head_max": 100}
        self.assertEqual(scene_text.limbs_text(limbs), "Your left arm is crippled and your right leg is hurt.")
        self.assertEqual(scene_text.limbs_text({"left_leg": -100, "left_leg_max": 100}), "Your left leg is gone.")

    def test_rumors_come_newest_first_with_their_age(self):
        lines = ["- [Day 9, 14:10] [RUMOR: Shek raiders were seen near the Bad Teeth.]", "- [Day 11, 19:02] [RUMOR: A caravan never arrived]"]
        self.assertEqual(scene_text.rumors_text(lines, 12), "Rumours:\nYesterday you heard a rumour: A caravan never arrived. A few days ago you heard a rumour: Shek raiders were seen near the Bad Teeth. These are only rumours; bring them up only when they fit the conversation.")
        self.assertTrue(scene_text.rumors_text(lines[:1], None).startswith("Rumours:\nYou heard a rumour:"))
        self.assertEqual(scene_text.rumors_text([], 12), "")

    def test_the_player_seen_by_the_npc(self):
        text = scene_text.player_text("Drifter", True, "Skeleton", "Other", "Sentient machines from ancient times", {"blood": 100, "max_blood": 100, "hunger": 10}, False, "Nameless", "", [])
        self.assertEqual(text, "The person before you:\nThe individual before you is Drifter, a Skeleton. Sentient machines from ancient times. They seem healthy. They are a member of Nameless.")
        self.assertTrue(scene_text.player_text("Drifter", False, "Unknown", "male", "", {}, True, "Unknown", "", []).startswith("The player:\nNearby is Drifter."))

    def test_the_npc_from_its_profile_repeats_neither_faction_nor_job(self):
        profile = {"Relation": -12, "Faction": "The Holy Nation", "Job": "Patrol", "ConversationHistory": ["x"]}
        text = scene_text.npc_text(profile, profile, "Drifter", "Nameless", met=True, major=True, in_player_faction=False, feels_hunger=True)
        self.assertEqual(text, "You:\nYou are mildly hostile towards Drifter. You belong to The Holy Nation, a major world power. You will not leave it for Drifter's squad without an extremely compelling reason, such as Drifter saving your life more than once.")

    def test_the_npc_from_its_live_context(self):
        profile = {"Relation": 30, "Faction": "The Holy Nation", "Job": "Patrol"}
        context = {
            "faction": "The Holy Nation", "job": "Patrol", "relation": -5, "money": 85, "character_state": "imprisoned",
            "medical": {"hunger": 300, "blood": 100, "max_blood": 100}, "stats": {"melee_attack": 40, "melee_defence": 20},
            "memories": {"short_term": [], "long_term": [2, 99]}, "environment": {"indoors": True},
        }
        text = scene_text.npc_text(context, profile, "Drifter", "Nameless", met=True, major=False, in_player_faction=False, feels_hunger=True)
        self.assertEqual(text, "You:\nYou are friendly towards Drifter. You are imprisoned and cannot move freely. Your faction, The Holy Nation, is neutral towards Nameless. You are well fed. You are healthy. You are indoors. You are a seasoned fighter. You have a little money. Drifter once saved your life.")

    def test_a_squad_member_travels_with_the_player(self):
        text = scene_text.npc_text({"faction": "Nameless", "relation": 100}, {"Faction": "Nameless"}, "Drifter", "Nameless", met=True, major=False, in_player_faction=True, feels_hunger=True)
        self.assertIn("You travel in Drifter's squad, and Drifter leads it.", text)
        self.assertNotIn("Your faction", text)

    def test_nearby_people(self):
        people = [
            {"name": "Ruka", "race": "Shek", "gender": "female", "faction": "Shek Kingdom", "health": "Injured", "equipment": "Plank, Shek Armour", "dist": 1.0},
            {"name": "Beep", "race": "Hive Worker Drone", "gender": "male", "faction": "Nameless", "health": "Healthy", "dist": 20},
            {"name": "Ghost", "race": "Unknown", "faction": "Unknown", "dist": 50},
        ]
        self.assertEqual(scene_text.nearby_text(people, "Drifter", "Nameless"), (
            "Around you:\nRuka, a Shek woman of Shek Kingdom, is right beside you. They look injured. They wear or carry Plank, Shek Armour. "
            "Beep, a Hive Worker Drone man, one of Drifter's squad, is nearby. They seem healthy. Ghost is some distance away."
        ))
        self.assertEqual(scene_text.nearby_text([], "Drifter", "Nameless"), "")

    def test_location(self):
        self.assertEqual(scene_text.location_text({"town_name": "Blister Hill"}), "You are in Blister Hill.")
        self.assertEqual(scene_text.location_text({}), "You are somewhere in the wasteland.")


if __name__ == "__main__":
    unittest.main()
