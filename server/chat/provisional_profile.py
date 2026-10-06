"""The provisional profile of an NPC at its first meeting: a personality, a backstory, and a speech quirk, rolled in code.

The LLM writes a bio only later, when the player's chats give it something to build on. The texts live in server/data/defaults, and
each one uses "they", so no text needs a gendered pronoun or a name.
"""

import json
import os
import random

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "defaults")
TRAIT_COUNT = 3
# Most people show a trait mildly, so an extreme trait stands out
TIER_WEIGHTS = (60, 30, 10)
KINDS = ("person", "skeleton", "animal")


def _load(filename):
    with open(os.path.join(CONFIG_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


TRAITS = _load("personality_traits.json")
ANIMAL_PERSONALITIES = _load("animal_personalities.json")
BACKSTORIES = _load("backstories.json")
SPEECH_QUIRKS = _load("speech_quirks.json")
# A skeleton gets its list by kind, because the server knows the skeleton races of the mods
QUIRK_RACES = {"human": ("greenlander", "scorchlander"), "shek": ("shek",), "hiver": ("hive",)}


def speech_quirks(race, kind):
    """The universal quirks plus the list of the race; a race with no list of its own gets the universal ones only."""
    group = "skeleton" if kind == "skeleton" else next(
        (group for group, words in QUIRK_RACES.items() if any(word in race.lower() for word in words)), None)
    return SPEECH_QUIRKS["universal"] + SPEECH_QUIRKS.get(group, [])


def roll(npc_id, kind, race):
    """Personality, Backstory, and SpeechQuirks for a kind of KINDS.

    Seeded by npc_id: a radiant conversation and a chat can meet a new character at the same moment, and both write its profile, so both must
    roll the same one.
    """
    rng = random.Random(npc_id)
    if kind == "animal":
        return {"Personality": rng.choice(ANIMAL_PERSONALITIES), "Backstory": "", "SpeechQuirks": ""}
    candidates = [trait for trait in TRAITS if kind in trait["kinds"]]
    rolled = []
    for _ in range(TRAIT_COUNT):
        trait = rng.choice(candidates)
        candidates = [other for other in candidates if other is not trait and other["id"] not in trait["opposites"]]
        rolled.append((rng.choices(range(len(TIER_WEIGHTS)), TIER_WEIGHTS)[0], trait))
    rolled.sort(key=lambda pair: -pair[0])
    return {
        "Personality": " ".join(trait["tiers"][tier]["text"] for tier, trait in rolled),
        "Backstory": rng.choice([story["text"] for story in BACKSTORIES if kind in story["kinds"]]),
        "SpeechQuirks": rng.choice(speech_quirks(race, kind)),
    }
