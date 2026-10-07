"""Which lore records an NPC can know. Each record has a tier: a Global record reaches every NPC, a Limited record the NPCs
that link to it through the seeded data, and a Secret record the characters, factions, and races of its known_by.

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


def known(records, identity, town=None, zone=None):
    """The keys of the records that the NPC can know. identity holds the keys of the records that a known_by can name for
    the NPC: its own character record, its current faction, its origin faction, and its race."""
    identity = set(identity)
    by_words = _by_words(records)
    own = identity | _own_place(records, by_words, town, zone)
    links = _links(records, by_words)
    result = set()
    for record in records:
        level = tier(record)
        if (level == "global"
                or level == "limited" and (record["key"] in own or links[record["key"]] & own)
                or level == "secret" and knowers(record, by_words) & identity):
            result.add(record["key"])
    return result


def _own_place(records, by_words, town, zone):
    """The current location, the current region, the neighbouring regions, and the factions that hold one of them: each
    faction whose territory, bases, or capital names one of them, and each owner of the current location."""
    current, regions, neighbours = place(records, town, zone)
    places = {*current, *regions, *neighbours}
    holders = {
        record["key"] for record in records if record["kind"] == "faction"
        and any(places & by_words.get(name_words(value), set()) for field in HOLDING_FIELDS for value in _listed(record["fields"].get(field)))
    }
    owners = {key for record in records if record["key"] in current for value in record["fields"].get("owner", []) for key in by_words.get(name_words(value), ()) if key[0] == "factions"}
    return places | holders | owners


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
