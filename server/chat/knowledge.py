"""Which lore records an NPC can know. Each record has a tier: a Global record reaches every NPC, a Limited record the NPCs
that link to it through the seeded data, and a Secret record the characters, factions, and races of its known_by.

A Limited record is base knowledge when it links to the NPC itself, to the lands of its origin faction, or to a place
inside them, and travel knowledge when it links only to a place away from home: the current place or a place of a past
chat. The prompt can therefore tell the NPC where it learned it.

It takes the records of retrieval.lore_records and the NPC as plain values and uses the standard library only, so it
never touches the campaign. Links go one hop from the own records of the NPC. Only the place takes a second hop, through
the factions that hold it, so a member of the Holy Nation does not reach Tinfist through the enemies of its faction.
"""

from chat.retrieval import name_matches, name_words, place

# A Backstory mixes what the wasteland knows with a private past
DEFAULTS = {"character": "limited"}
HOLDING_FIELDS = ("territory", "bases", "capital")
KNOWER_CATEGORIES = ("characters", "factions", "races")


def tier(record):
    """An empty knowledge reads as the default of the kind, as a missing one does."""
    return record.get("knowledge") or DEFAULTS.get(record["kind"], "global")


def known(records, identity, origin=None, places=()):
    """The records that the NPC can know, as a dict from the key to whether the NPC knows the record only from its travels.
    identity holds the keys of the records that a known_by can name for the NPC: its own character record, its current
    faction, its origin faction, and its race. origin is the key of the origin faction, whose lands are the home of the
    NPC, and places holds the (town, zone) of the current place and of each place of a past chat. A place inside the home
    is base, with its neighbouring regions and holding factions, so what an NPC hears around its home is not travel. An NPC
    whose origin faction holds no land is a drifter, so it knows each place from its travels."""
    identity = set(identity)
    by_words = _by_words(records)
    home = _home(records, by_words, origin)
    located = [place(records, town, zone) for town, zone in set(places)]
    inside = [found for found in located if home & {*found[0], *found[1]}]
    base = identity | home | _own_place(records, by_words, inside)
    travels = _own_place(records, by_words, [found for found in located if found not in inside])
    links = _links(records, by_words)
    result = {}
    for record in records:
        level, key = tier(record), record["key"]
        if level == "global" or level == "limited" and (key in base or links[key] & base) or level == "secret" and knowers(record, by_words) & identity:
            result[key] = False
        elif level == "limited" and (key in travels or links[key] & travels):
            result[key] = True
    return result


def _home(records, by_words, origin):
    """The keys of the land of the origin faction: each location and region that its territory, bases, or capital names,
    each location whose owner names it, and the region of each of these locations. Unlike a place, the home takes no
    neighbouring region and no holding faction, which would spread it over a third of the world."""
    faction = next((record for record in records if record["key"] == origin), None)
    if not faction:
        return set()
    named = {key for field in HOLDING_FIELDS for value in _listed(faction["fields"].get(field)) for key in by_words.get(name_words(value), ())}
    towns = [
        record for record in records if record["kind"] == "location"
        and (record["key"] in named or any(origin in by_words.get(name_words(value), ()) for value in _listed(record["fields"].get("owner"))))
    ]
    regions = {key for town in towns for value in _listed(town["fields"].get("zone")) for key in by_words.get(name_words(value), ()) if key[0] == "regions"}
    return {town["key"] for town in towns} | {key for key in named if key[0] == "regions"} | regions


def _own_place(records, by_words, located):
    """The locations, the regions, and the neighbouring regions of located, which holds what retrieval.place gives for
    each place, and the factions that hold one of them: each faction whose territory, bases, or capital names one of them,
    and each owner of one of the locations."""
    towns, regions = set(), set()
    for current, own_regions, neighbours in located:
        towns.update(current)
        regions.update(own_regions, neighbours)
    found = towns | regions
    holders = {
        record["key"] for record in records if record["kind"] == "faction"
        and any(found & by_words.get(name_words(value), set()) for field in HOLDING_FIELDS for value in _listed(record["fields"].get(field)))
    }
    owners = {key for record in records if record["key"] in towns for value in record["fields"].get("owner", []) for key in by_words.get(name_words(value), ()) if key[0] == "factions"}
    return found | holders | owners


def knowers(record, by_words):
    """The keys of the characters, factions, and races that the known_by of the record names. A name can name several,
    such as Skeleton, which names the race Skeleton and the faction Skeletons."""
    return {key for name in record["known_by"] for key in by_words.get(name_words(name), ()) if key[0] in KNOWER_CATEGORIES}


def _by_words(records):
    """The keys of the records by the name words of each name and alias, as a field value names a record."""
    found = {}
    for record in records:
        for words in filter(None, map(name_words, (record["name"], *record["aliases"]))):
            found.setdefault(words, set()).add(record["key"])
    return found


def _links(records, by_words):
    """The keys that each record links to, in both directions: through a field value, a child, the Faction and the
    OriginFaction of a character, and the text of a history entry. A history entry has no fields, so without its text no
    link could reach a Limited one. The text of another record links nothing, because it finds wrong names, such as the
    character Cat in "Cat-Lon"."""
    links = {record["key"]: set() for record in records}

    def join(key, other):
        if other in links and other != key:
            links[key].add(other)
            links[other].add(key)

    names = [(name, record["key"]) for record in records for name in (record["name"], *record["aliases"])]
    for record in records:
        if record["kind"] == "character":
            # The race is no link, or every canon Greenlander would know the past of every other one
            targets = {key for value in (record["fields"].get("faction"), record["origin_faction"]) if value for key in by_words.get(name_words(value), ()) if key[0] == "factions"}
        else:
            targets = {key for field, value in record["fields"].items() if field != "neighbours" for item in _listed(value) for key in by_words.get(name_words(item), ())}
            targets |= {tuple(child.split("/", 1)) for child in record["children"]}
        if record["kind"] == "history":
            targets |= {key for _, key in name_matches(record["description"], names)}
        for other in targets:
            join(record["key"], other)
    return links


def _listed(value):
    return value if isinstance(value, list) else [value] if value else []
