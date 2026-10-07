"""The memories and the lore entries that a player's message finds in the active campaign, for the last user message of a
chat and for the test search of the web app, so the test search finds what a chat would find."""

from chat import chat_prompt, knowledge, retrieval
from chat.prompts import find_named
from core.settings import load_settings
from store import campaign_db


def campaign_lore():
    """A character that the server added in play is no record: its rolled backstory is invented."""
    stored = campaign_db.character_knowledge()
    characters = [{"npc_id": npc_id, "profile": profile, **stored[npc_id]} for (npc_id,), profile, origin, _ in campaign_db.list_records("character") if origin != "game"]
    return retrieval.lore_records([(category, ext_id, data) for (category, ext_id), data, *_ in campaign_db.list_records("entity")], campaign_db.list_factions(), campaign_db.history(), characters)


def in_system_message(lore, npc_id, profile, faction_id, speaker_race):
    """The keys of the lore records that the system message of a chat with the NPC holds: its own character record, its
    current and origin faction (describe_npc), the race of the speaker, and the player's faction (scene_values)."""
    factions = [campaign_db.player_faction()]
    for name, game_id in ((profile.get("Faction"), faction_id), (profile.get("OriginFaction"), None)):
        if name and name != "Unknown":
            factions.append(campaign_db.find_faction(game_id, name))
    race = _race(lore, speaker_race)
    return {("characters", npc_id)} | {("factions", faction["faction_id"]) for faction in factions if faction} | ({race["key"]} if race else set())


def identity(lore, npc_id, profile, faction_id):
    """The keys of the records that a known_by can name for the NPC: its own character record, its current faction, its
    origin faction, and its race. A generic NPC can carry the name of a canon character, so only the npc_id counts."""
    keys = {("characters", npc_id)}
    for game_id, name in ((faction_id, profile.get("Faction")), (None, profile.get("OriginFaction"))):
        name = name if name != "Unknown" else None
        faction = campaign_db.find_faction(game_id, name) if game_id or name else None
        if faction:
            keys.add(("factions", faction["faction_id"]))
    race = _race(lore, profile.get("Race"))
    return keys | ({race["key"]} if race else set())


def known_keys(lore, npc_id, profile, faction_id, town, zone):
    return knowledge.known(lore, identity(lore, npc_id, profile, faction_id), town, zone)


def _race(lore, name):
    return find_named([record for record in lore if record["kind"] == "race"], name) if name else None


def place_of(location, lore):
    """The (town, zone) of a CurrentLocation (scene_text.location_name), whose last part names the town or the zone. A
    building outside the towns reads like a building of a town, so only the locations of the lore tell them apart."""
    building, _, place = location.rpartition(", ")
    if building != "Wilderness" and find_named([record for record in lore if record["kind"] == "location"], place):
        return place, None
    return None, place or None


def search(message, lore, npc_id=None, profile=None, faction_id=None, speaker_race=None, town=None, zone=None, recent=frozenset()):
    """The memory hits and the lore hits of a turn in prompt order, and the words that did not search the lore, as
    retrieval gives them. Without npc_id, a lore search alone of every record, so a template author can test each one.
    With it, the search skips what the system message holds, and the records that the NPC cannot know drop out before
    the index, so they set neither the best score of the score cut nor the common share."""
    searched = [record for record in lore if record["description"].strip()]
    if npc_id is not None:
        keys = known_keys(lore, npc_id, profile, faction_id, town, zone)
        searched = [record for record in searched if record["key"] in keys]
    lore_hits, skipped = retrieval.find_lore(message, searched, town, zone)
    memory_hits, skip = [], set()
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
        memory_hits = retrieval.find_memories(message, records, profile.get("Name", ""), lore_names)
        skip = in_system_message(lore, npc_id, profile, faction_id, speaker_race)
    settings = load_settings()
    memories, entries = retrieval.chosen(memory_hits, lore_hits, skip, recent, settings["retrieval_slots"], settings["memory_slots"])
    return memories, entries, skipped
