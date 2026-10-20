"""The leaders and the nobles that the game holds dead or imprisoned, such as Tinfist in a cage of the Holy Nation. The game
keeps the state of each unique NPC that it spawned, and each request of the plugin lists those that are not alive
(state.UNIQUE_STATES). The faction records describe the start of a game, so the server lays the states over them for
the lore. Each NPC that knows a faction knows the state of its rulers, because the plugin sees only that a state holds,
not when or where its news went."""

from chat.retrieval import name_words
from core import state
from store import campaign_db

RULER_FIELDS = ("leader", "nobles")


def character_states():
    """The state of each unique NPC that is not alive, by the npc_id that its canon record would have."""
    return {f"u:{unique['id']}": unique["state"] for unique in state.UNIQUE_STATES or []}


def fallen():
    """The state of each unique NPC that is not alive, by the name words of its game name and of the Name of its canon
    record, because a template author or a player can name the character otherwise than the game does."""
    if not state.UNIQUE_STATES:
        return {}
    names = campaign_db.names_of(character_states())
    found = {}
    for unique in state.UNIQUE_STATES:
        for name in (unique["name"], names.get(f"u:{unique['id']}")):
            if name:
                found[name_words(name)] = unique["state"]
    return found


def current(faction, fallen):
    """The faction record with a field for each state, such as dead, that names the leader and the nobles in that state as
    the record names them. The leader and the nobles stay, so the links of the record hold. A value can name two rulers,
    such as "Dimak and Buzan", so a value that matches no one is split at "and"."""
    fields = faction.get("fields", {})
    held = {}
    for field in RULER_FIELDS:
        value = fields.get(field)
        for name in value if isinstance(value, list) else [value] if value else []:
            for ruler in [name] if name_words(name) in fallen else name.split(" and "):
                if name_words(ruler) in fallen:
                    held.setdefault(fallen[name_words(ruler)], []).append(ruler)
    return {**faction, "fields": {**fields, **held}} if held else faction
