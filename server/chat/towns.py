"""The towns that the world states of the game changed, such as Brink after the Reavers take it. The game swaps the data of
such a town for an override with another owner or type, and each request of the plugin lists these towns
(state.CHANGED_TOWNS). The location records describe the start of a game, so the server lays the changes over them for
the lore, the knowledge, and the scene. Each NPC that knows a town knows its change, because the plugin sees only that a
change holds, not when or where its news went."""

from chat.retrieval import name_words
from core import state
from store import campaign_db

# TownType in deps/KenshiLib/Include/kenshi/Town.h, in the words of the location types
TYPES = {0: "camp", 1: "outpost", 2: "town", 3: "village", 4: "ruins", 5: "slave camp", 6: "military", 7: "prison", 9: "point of interest"}


def current(location):
    """The location record as the game has it now. A record that no changed town names stays as it is."""
    names = {name_words(name) for name in (location.get("name", ""), *location.get("aliases", []))}
    change = next((change for change in state.CHANGED_TOWNS if name_words(change.get("name") or "") in names), None)
    if not change:
        return location
    owner = change.get("owner")
    faction = (campaign_db.find_faction(change.get("owner_id"), owner) or {"name": owner, "aliases": []}) if owner else None
    return changed(location, TYPES.get(change.get("type")), faction)


def changed(location, kind, owner):
    """The location record with the type kind, or its own type when kind is None, and the owner, a faction with a name and
    aliases, or None. The change sentence leads the description and is the record's change. A ruin is no one's land
    (knowledge._ruins), so a town that falls to ruins keeps its owner as the former owner, and a new owner of a ruin
    changes nothing."""
    fields = location.get("fields", {})
    old_kind, old_owners = fields.get("type"), fields.get("owner", [])
    kind = kind or old_kind
    names = {name_words(name) for name in (owner["name"], *owner["aliases"])} if owner else set()
    same_owner = any(name_words(value) in names for value in old_owners) if owner else not old_owners
    if kind == "ruins" and old_kind == "ruins" or kind == old_kind and same_owner:
        return location
    of = " of " + " and ".join(old_owners) if old_owners and old_kind != "ruins" else ""
    fields = {**fields, "type": kind}
    now = _a(kind)
    if kind != "ruins" and owner:
        fields["owner"] = [owner["name"]]
        now += " held by " + owner["name"]
    elif kind != "ruins":
        fields.pop("owner", None)
    change = f"{location['name']} is now {now}. It was {_a(old_kind)}{of} before."
    return {**location, "fields": fields, "description": f"{change} {location.get('description') or ''}".strip(), "change": change}


def _a(kind):
    if kind is None:
        return "a place"
    if kind == "ruins":
        return kind
    if kind == "military":
        return "a military base"
    return f"{'an' if kind[0] in 'aeiou' else 'a'} {kind}"

