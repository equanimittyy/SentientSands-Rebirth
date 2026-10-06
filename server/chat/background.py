"""The memories and the lore entries that a player's message finds in the active campaign, for the last user message of a
chat and for the test search of the web app, so the test search finds what a chat would find."""

from chat import chat_prompt, retrieval
from chat.prompts import find_named
from core.settings import load_settings
from store import campaign_db


def campaign_lore():
    return retrieval.lore_records([(category, ext_id, data) for (category, ext_id), data, *_ in campaign_db.list_records("entity")], campaign_db.list_factions(), campaign_db.history())


def in_system_message(lore, profile, faction_id, speaker_race):
    """The keys of the lore records that the system message of a chat with the NPC holds: its current and origin faction
    (describe_npc), the race of the speaker, and the player's faction (scene_values)."""
    factions = [campaign_db.player_faction()]
    for name, game_id in ((profile.get("Faction"), faction_id), (profile.get("OriginFaction"), None)):
        if name and name != "Unknown":
            factions.append(campaign_db.find_faction(game_id, name))
    race = find_named([record for record in lore if record["kind"] == "race"], speaker_race) if speaker_race else None
    return {("factions", faction["faction_id"]) for faction in factions if faction} | ({race["key"]} if race else set())


def search(message, lore, npc_id=None, profile=None, faction_id=None, speaker_race=None, town=None, zone=None, recent=frozenset()):
    """The memory hits and the lore hits of a turn in prompt order, and the words that did not search the lore, as
    retrieval gives them. Without npc_id, a lore search alone. The search skips what the system message holds."""
    lore_hits, skipped = retrieval.find_lore(message, lore, town, zone)
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
        skip = in_system_message(lore, profile, faction_id, speaker_race)
    settings = load_settings()
    memories, entries = retrieval.chosen(memory_hits, lore_hits, skip, recent, settings["retrieval_slots"], settings["memory_slots"])
    return memories, entries, skipped
