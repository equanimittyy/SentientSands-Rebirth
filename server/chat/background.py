"""The memories, the rumors, and the lore entries that a player's message finds in the active campaign, for the last user
message of a chat and for the test search of the web app, so the test search finds what a chat would find."""

import math

from chat import chat_prompt, knowledge, retrieval, rulers, towns
from chat.prompts import PROMPT_RUMORS, find_named
from core import world_events
from core.settings import load_settings
from store import campaign_db
from store.world_template import DIRECTIONS


def campaign_lore():
    """A character that the server added in play is no record: its rolled backstory is invented."""
    stored = campaign_db.character_knowledge()
    states = rulers.character_states()
    characters = [{"npc_id": npc_id, "profile": profile, "state": states.get(npc_id), **stored[npc_id]} for (npc_id,), profile, origin, _ in campaign_db.list_records("character") if origin != "game"]
    entities = [(category, ext_id, towns.current(data) if category == "locations" else data) for (category, ext_id), data, *_ in campaign_db.list_records("entity")]
    fallen = rulers.fallen()
    return retrieval.lore_records(entities, [rulers.current(faction, fallen) for faction in campaign_db.list_factions()], campaign_db.history(), characters)


def in_system_message(lore, npc_id, profile, faction_id, speaker_race, known, town, zone):
    """The keys of the lore records that the system message of a chat with the NPC holds: its own character record, its
    current and origin faction and its race (describe_npc), the race of the speaker, the player's faction, and the
    current place (scene_values)."""
    factions = [campaign_db.player_faction()]
    for name, game_id in ((profile.get("Faction"), faction_id), (profile.get("OriginFaction"), None)):
        if name and name != "Unknown":
            factions.append(campaign_db.find_faction(game_id, name))
    races = {race["key"] for race in (_race(lore, profile.get("Race")), _race(lore, speaker_race)) if race}
    place = {record["key"] for record in scene_place(lore, known, town, zone)}
    return {("characters", npc_id)} | {("factions", faction["faction_id"]) for faction in factions if faction} | races | place


def scene_place(lore, known, town, zone):
    """The records of the current location and the current region that the NPC knows (known_keys), for the chat scene,
    so that a line about "this town" or "around here" needs no name. A record without text stays out, as in the search."""
    current, regions, _ = retrieval.place(lore, town, zone)
    by_key = {record["key"]: record for record in lore if record["description"].strip()}
    return [by_key[key] for key in [*current, *regions] if key in by_key and key in known]


def identity(lore, npc_id, profile, faction_id):
    """The keys of the records that a known_by can name for the NPC: its own character record, its current faction, its
    origin faction, and its race. A generic NPC can carry the name of a canon character, so only the npc_id counts."""
    keys = {("characters", npc_id)} | {key for key in (_faction_key(faction_id, profile.get("Faction")), _faction_key(None, profile.get("OriginFaction"))) if key}
    race = _race(lore, profile.get("Race"))
    return keys | ({race["key"]} if race else set())


def known_keys(lore, npc_id, profile, faction_id, town, zone):
    """The places of the past chats of the NPC stand for its travels, so nothing tracks an NPC between its chats."""
    visited = {place_of(location, lore) for location in campaign_db.thread_places(npc_id)}
    return knowledge.known(lore, identity(lore, npc_id, profile, faction_id), _faction_key(None, profile.get("OriginFaction")), [(town, zone), *visited])


def travels(lore, profiles):
    """The town or the zone of each place of a past chat of each character, newest first, each once, by npc_id. A place
    inside the home of the character drops out, because known_keys counts it as base, not travel. profiles holds the
    profile of each character by npc_id."""
    stored = {npc_id: [location for location in locations if location] for npc_id, locations in campaign_db.character_places().items() if npc_id in profiles}
    places = {location: place_of(location, lore) for location in {location for locations in stored.values() for location in locations}}
    located = {found: retrieval.place(lore, *found) for found in set(places.values())}
    homes = {name: knowledge.home_of(lore, _faction_key(None, name)) for name in {profiles[npc_id].get("OriginFaction") for npc_id in stored}}
    return {
        npc_id: list(dict.fromkeys(
            town or zone for town, zone in map(places.get, locations) if not knowledge.at_home(homes[profiles[npc_id].get("OriginFaction")], located[town, zone])
        ))
        for npc_id, locations in stored.items()
    }


def _faction_key(game_id, name):
    name = name if name != "Unknown" else None
    faction = campaign_db.find_faction(game_id, name) if game_id or name else None
    return ("factions", faction["faction_id"]) if faction else None


def _race(lore, name):
    return find_named([record for record in lore if record["kind"] == "race"], name) if name else None


def place_of(location, lore):
    """The (town, zone) of a CurrentLocation (scene_text.location_name), whose last part names the town or the zone. A
    building outside the towns reads like a building of a town, so only the locations of the lore tell them apart."""
    building, _, place = location.rpartition(", ")
    if building != "Wilderness" and find_named([record for record in lore if record["kind"] == "location"], place):
        return place, None
    return None, place or None


def directions(message, entries, lore, town, zone, towns):
    """The directions of a turn by name. A neighbour of the NPC's region comes when the message names its direction or
    asks for a direction, and when a found entry names it, or names it as the zone of a location. A named location other
    than the NPC's town takes its direction from towns, by name words. The record of a neighbour gives the directions
    from its own side and only on the turn that names it, and with that alone the model put Okran's Gulf east of the
    Border Zone, not north."""
    _, regions, _ = retrieval.place(lore, town, zone)
    neighbours = {name: side for record in lore if record["key"] in regions for name, side in record["fields"].get("neighbours", {}).items()}
    said = set(retrieval.words(message))
    records = [hit["record"] for hit in entries if "name" in hit]
    named_words = {retrieval.name_words(name) for record in records for name in (record["name"], *record["fields"].get("zone", []))}
    named = {name: side for name, side in neighbours.items() if retrieval.name_words(name) in named_words}
    here = retrieval.name_words(town or "")
    for record in records:
        words = retrieval.name_words(record["name"])
        if record["kind"] == "location" and words != here and words in towns:
            named[record["name"]] = towns[words]
    return {**{name: side for name, side in neighbours.items() if side in said or "direction" in said}, **named}


def town_directions(named_towns):
    """The direction of each town of the plugin's named_towns from the NPC, by the name words of the town."""
    return {retrieval.name_words(town["name"]): DIRECTIONS[round(math.degrees(math.atan2(town["dx"], -town["dz"])) / 45) % 8] for town in named_towns}


def unknown_towns(named_towns, lore, known):
    """The towns of the plugin's named_towns whose location the NPC cannot know (known_keys). Without a line that says so,
    the model made up a way to them. A town without a location record is not one, because nothing tells whether the NPC
    knows it."""
    locations = [record for record in lore if record["kind"] == "location"]
    hidden = {retrieval.name_words(record["name"]) for record in locations} - {retrieval.name_words(record["name"]) for record in locations if record["key"] in known}
    return [town["name"] for town in named_towns if retrieval.name_words(town["name"]) in hidden]


def names_record(message, lore):
    """Whether the message names a lore record, whether the NPC can know it or not. A search drops the records that the
    NPC cannot know, so without this a line that names only such a town carries the town before it, and "Where is it?"
    gets the direction of that town."""
    return bool(retrieval.name_matches(message, [(name, record["key"]) for record in lore for name in (record["name"], *record["aliases"])]))


def rumor_records(npc_id):
    """The rumors that the chat scene leaves out, because it holds the newest. Each NPC hears each rumor, as in the scene.
    The NPC drops out of the names, because the player names it to address it."""
    told = campaign_db.rumors()[:-PROMPT_RUMORS]
    events = {event_id: event for event_id, _, event in campaign_db.events()}
    characters = {rumor["id"]: world_events.characters(events[rumor["event_id"]]) for rumor in told}
    names = campaign_db.names_of({member_id for found in characters.values() for member_id, _ in found})
    return [
        {"key": ("rumor", rumor["id"]), "text": rumor["text"], "names": [names.get(member_id, name) for member_id, name in characters[rumor["id"]] if member_id != npc_id], "rumor": rumor}
        for rumor in told
    ]


def search(message, lore, npc_id=None, profile=None, faction_id=None, speaker_race=None, town=None, zone=None, recent=frozenset(), carried=None):
    """The memory hits, the rumor hits, and the lore hits of a turn in prompt order, and the words that did not search the
    lore, as retrieval gives them. Without npc_id, a lore search alone of every record, so a template author can test
    each one. With it, the search skips what the system message holds, and the records that the NPC cannot know drop
    out before the index, so they set neither the best score of the score cut nor the common share. A lore hit holds
    travels, which is true when the NPC knows the record only from its travels. carried holds the hits of the last turn
    that its line found by name (named), which come first when this message names nothing: the hits of a turn stay out
    of the history, so "What does she rule?" would lose what "Who is Esata?" found."""
    searched = [record for record in lore if record["description"].strip()]
    keys = {}
    if npc_id is not None:
        keys = known_keys(lore, npc_id, profile, faction_id, town, zone)
        searched = [record for record in searched if record["key"] in keys]
    lore_hits, skipped = retrieval.find_lore(message, searched, town, zone)
    lore_hits = [{**hit, "travels": keys.get(hit["record"]["key"], False)} for hit in lore_hits]
    memory_hits, rumor_hits, skip = [], [], set()
    if npc_id is not None:
        stored = campaign_db.memories_of(npc_id)
        starting = {memory["id"] for memory in chat_prompt.starting_memories(stored, npc_id)}
        records = [
            # The NPC is a member of each of its memories, so its own name would find them all
            {"key": ("memory", memory["id"]), "text": chat_prompt.memory_text(memory), "names": [name for member_id, name, _, _ in memory["members"] if member_id != npc_id and name], "memory": memory}
            for memory in stored if memory["id"] not in starting
        ]
        # A lore name counts even when the system message holds its entry, because it does not hold the memory
        lore_names = [name for hit in lore_hits if "name" in hit for name in (hit["record"]["name"], *hit["record"]["aliases"])]
        memory_hits = retrieval.find_texts(message, records, profile.get("Name", ""), lore_names)
        rumor_hits = retrieval.find_texts(message, rumor_records(npc_id), profile.get("Name", ""), lore_names)
        skip = in_system_message(lore, npc_id, profile, faction_id, speaker_race, keys, town, zone)
    if carried and not any("name" in hit for hits in (memory_hits, rumor_hits, lore_hits) for hit in hits):
        memory_hits, rumor_hits, lore_hits = (_carried_first(old, new) for old, new in zip(carried, (memory_hits, rumor_hits, lore_hits)))
    settings = load_settings()
    memories, rumors, entries = retrieval.chosen(memory_hits, rumor_hits, lore_hits, skip, recent, settings["retrieval_slots"], settings["memory_slots"])
    return memories, rumors, entries, skipped


def _carried_first(carried, hits):
    keys = {hit["record"]["key"] for hit in carried}
    return [{**hit, "carried": True} for hit in carried] + [hit for hit in hits if hit["record"]["key"] not in keys]


def named(*found):
    """The hits of each list of search that the line of the turn found by name, so the next turn carries only one turn."""
    return tuple([hit for hit in hits if "name" in hit and not hit.get("carried")] for hits in found)
