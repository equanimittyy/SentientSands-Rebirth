"""The bounties that SSR puts on NPCs through the bounty system of the game."""

import math
import random

from chat import knowledge, retrieval
from chat.retrieval import name_words

# The order of CrimeEnum in KenshiLib after CRIME_NONE, so the plugin takes CRIMES[i] as the enum value i + 1
CRIMES = (
    "ENSLAVING", "LOCKPICKING", "STEALING", "MURDER", "ASSAULT", "ASSAULT_VIP", "SLAVE_FREEING", "SMUGGLING",
    "TERRORISM", "LOOTING", "TRESPASSING", "ESCAPE_PRISON", "FENCING", "FARM_EATING", "KIDNAPPING", "UNIFORM_THEFT",
)


def enemy_ids(target, factions):
    """The game IDs of the factions that the campaign sets against target, the faction of the target: each faction in its
    enemies, and each faction that lists it in theirs. The names match by name words, so "Holy Nation" names The Holy
    Nation."""
    def names(faction):
        return {name_words(name) for name in (faction["name"], *faction["aliases"])}

    def enemies(faction):
        return {name_words(name) for name in faction["fields"].get("enemies", [])}

    own = names(target)
    return [
        faction["faction_id"] for faction in factions
        if faction["faction_id"] and faction["faction_id"] != target["faction_id"] and (names(faction) & enemies(target) or own & enemies(faction))
    ]


def issuer_ids(target, factions, lore, town, zone, shuffle=random.shuffle):
    """The enemy_ids of target, the likeliest issuer first: the major factions, then the others, each group nearest first to
    the place of the target. A faction without land comes last in its group, and a tie goes at random. lore holds the
    records of retrieval.lore_records."""
    ids = enemy_ids(target, factions)
    shuffle(ids)
    major = {faction["faction_id"] for faction in factions if faction["major"]}
    steps = region_steps(lore, town, zone)

    def distance(faction_id):
        land = knowledge.home_of(lore, ("factions", faction_id))
        return min((steps[key] for key in land if key in steps), default=math.inf)

    return sorted(ids, key=lambda faction_id: (faction_id not in major, distance(faction_id)))


def region_steps(lore, town, zone):
    """The number of steps through the neighbours from the region of the place to each region that it reaches."""
    _, start, _ = retrieval.place(lore, town, zone)
    regions = [record for record in lore if record["kind"] == "region"]
    names = {record["key"]: {name_words(name) for name in (record["name"], *record["aliases"])} for record in regions}
    named = {record["key"]: {name_words(name) for name in record["fields"].get("neighbours", [])} for record in regions}
    steps = {key: 0 for key in start}
    frontier = list(start)
    while frontier:
        reached = [
            other for other in names if other not in steps
            and any(names[other] & named[key] or names[key] & named[other] for key in frontier)
        ]
        steps.update((key, steps[frontier[0]] + 1) for key in reached)
        frontier = reached
    return steps
