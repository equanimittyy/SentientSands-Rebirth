"""Finds the lore entries and the memories that a player's message is about, for the last user message of a chat.

It takes the message and the records as plain values and uses the standard library only, so it never touches the
campaign. A search finds words, not meaning, so some hits are wrong: the slots, the score cut, and the cooldown keep a
wrong hit cheap.
"""

import re
import sqlite3

_WORD = re.compile(r"[^\W_]+")
# The split at an apostrophe leaves the "s" of "Admag's" and the "t" of "don't" as words
STOP_WORDS = frozenset("""
    a about above after again against all also am an and any are around as at be because been before being below between
    both but by can could d did do does doing don down during each ever few for from further had has have having he her
    here hers herself him himself his how i if in into is it its itself just ll m ma may me might more most must my myself
    never no nor not now o of off on once only or other our ours ourselves out over own re s same shall she should so some
    such t than that the their theirs them themselves then there these they this those through to too under until up ve
    very was we were what when where which while who whom why will with would y yes you your yours yourself yourselves
""".split())
TEXT_LIMIT = 700
# The name, the aliases, the fields, and the text
WEIGHTS = (10.0, 10.0, 3.0, 1.0)
SCORE_RATIO = 0.6
COMMON_SHARE = 0.1
MEMORY_WORDS = 2
KINDS = {"races": "race", "locations": "location", "regions": "region"}


def lore_records(entities, factions, history):
    """entities are (category, ext_id, data) triples, factions are dicts with a faction_id, and history holds the entries of
    the history. A record has a key that is unique in the campaign, and a record without text is left out."""
    records = [_record((category, ext_id), KINDS[category], data) for category, ext_id, data in entities]
    records += [_record(("factions", faction["faction_id"]), "faction", faction) for faction in factions]
    records += [{"key": ("history", i), "kind": "history", "name": entry["title"], "aliases": [], "fields": {}, "description": entry["text"]} for i, entry in enumerate(history)]
    return [record for record in records if record["description"].strip()]


def _record(key, kind, data):
    return {"key": key, "kind": kind, "name": data.get("name", ""), "aliases": data.get("aliases", []), "fields": data.get("fields", {}), "description": data.get("description") or ""}


def words(text):
    """A word of 4 or more letters loses a final "s", so "skeletons" finds Skeleton."""
    return [word[:-1] if len(word) >= 4 and word.endswith("s") else word for word in _WORD.findall(text.casefold())]


def name_words(name):
    found = words(name)
    return tuple(found[1:] if len(found) > 1 and found[0] == "the" else found)


def name_matches(message, names):
    """names are (name, item) pairs. Returns the pairs whose name the message holds, with the words in order and none
    between them, in the order of their first word in the message. A match inside a longer match is dropped, so "Shek
    Kingdom" finds the faction and not also the race Shek."""
    said = words(message)
    found = [(start, start + len(wanted), name, item) for name, item in names for wanted in [name_words(name)] if wanted for start in _starts(said, wanted)]
    kept = [match for match in found if not any(other[0] <= match[0] and match[1] <= other[1] and other[1] - other[0] > match[1] - match[0] for other in found)]
    return [(name, item) for _, _, name, item in sorted(kept, key=lambda match: match[0])]


def _starts(said, wanted):
    return [start for start in range(len(said) - len(wanted) + 1) if tuple(said[start:start + len(wanted)]) == wanted]


def _names(record):
    return [record["name"], *record["aliases"]]


def _values(fields):
    return [item for value in fields.values() for item in (value if isinstance(value, list) else [value])]


def find_lore(message, records, town=None, zone=None):
    """The records that the message is about: the name matches, then the content hits in the order of place_order.
    Returns (hits, skipped). A hit is {"record", "name"} for a name match and {"record", "words"} for a content hit,
    and skipped holds a (word, reason) pair for each word of the message that did not search."""
    named = {}
    for name, i in name_matches(message, [(name, i) for i, record in enumerate(records) for name in _names(record)]):
        named.setdefault(i, name)
    db = _index(("name", "aliases", "fields", "text"), [(record["name"], " | ".join(record["aliases"]), " | ".join(_values(record["fields"])), record["description"]) for record in records])
    db.execute("CREATE VIRTUAL TABLE row_terms USING fts5vocab(entry, 'row')")
    db.execute("CREATE VIRTUAL TABLE column_terms USING fts5vocab(entry, 'col')")
    # The lore words: chat words are rare in the lore, so BM25 would rank a hit on "doing" or "need" high
    vocabulary = {term for (term,) in db.execute("SELECT term FROM column_terms WHERE col != 'text'")}
    counts = dict(db.execute("SELECT term, doc FROM row_terms"))
    searched, skipped = {}, []
    for word, term in _terms(db, list(dict.fromkeys(_WORD.findall(message.casefold())))):
        if word in STOP_WORDS:
            skipped.append((word, "common"))
        elif term not in vocabulary:
            skipped.append((word, "not lore"))
        elif counts[term] > COMMON_SHARE * len(records):
            skipped.append((word, "frequent"))
        else:
            searched.setdefault(term, word)
    content = [(i, found) for i, found in _ranked(db, list(searched.values()), 1, f"bm25(entry, {', '.join(map(str, WEIGHTS))})") if i not in named]
    hits = [{"record": records[i], "name": name} for i, name in named.items()]
    hits += [{"record": records[i], "words": found} for i, found in place_order(content, records, town, zone)]
    return hits, skipped


def place_order(content, records, town, zone):
    """content holds (index, words) pairs in the order of their score. The current location comes first, then the current
    region, then the locations of that region, then the others, each group in the order of its score. The region of the
    NPC is the likeliest meaning of a message that finds many regions with near-equal scores, such as "Any bonedogs around?"."""
    def called(record, name):
        return bool(name) and name.casefold() in {other.casefold() for other in _names(record)}

    current = [record for record in records if record["kind"] == "location" and called(record, town)]
    zones = [zone] if zone else [name for record in current for name in record["fields"].get("zone", [])]
    regions = [record for record in records if record["kind"] == "region" and any(called(record, name) for name in zones)]
    region_names = {name.casefold() for record in regions for name in _names(record)}

    def group(record):
        if record in current:
            return 0
        if record in regions:
            return 1
        if record["kind"] == "location" and region_names & {name.casefold() for name in record["fields"].get("zone", [])}:
            return 2
        return 3

    return sorted(content, key=lambda hit: group(records[hit[0]]))


def find_memories(message, memories, npc_name, lore_names):
    """memories are dicts with a "text" and the "names" of their members except the NPC, oldest first. lore_names are the
    names of the lore records that the message names. Returns the hits newest first, in the form of find_lore."""
    named = {}
    for name, i in name_matches(message, [(name, i) for i, memory in enumerate(memories) for name in memory["names"]]):
        named.setdefault(i, name)
    for i, memory in enumerate(memories):
        text = words(memory["text"])
        told = [name for name in lore_names if _starts(text, name_words(name))]
        if told:
            named.setdefault(i, told[0])
    db = _index(("text",), [(memory["text"],) for memory in memories])
    # Every memory of the NPC holds its name, so a word of the name would find them all
    own = set(_WORD.findall(npc_name.casefold()))
    searched = {}
    for word, term in _terms(db, list(dict.fromkeys(_WORD.findall(message.casefold())))):
        if term and word not in STOP_WORDS and word not in own:
            searched.setdefault(term, word)
    found = dict(_ranked(db, list(searched.values()), MEMORY_WORDS, "bm25(entry)"))
    return [{"record": memories[i], "name": named[i]} if i in named else {"record": memories[i], "words": found[i]} for i in sorted({*named, *found}, reverse=True)]


def _index(columns, rows):
    db = sqlite3.connect(":memory:")
    db.execute(f"CREATE VIRTUAL TABLE entry USING fts5({', '.join(columns)}, tokenize='porter unicode61')")
    db.executemany(f"INSERT INTO entry (rowid, {', '.join(columns)}) VALUES ({', '.join('?' * (len(columns) + 1))})", [(i, *row) for i, row in enumerate(rows)])
    return db


def _terms(db, said):
    """Each word with its term under the tokenizer of the index, so "mercenaries" meets "Mercenary"."""
    db.execute("CREATE VIRTUAL TABLE said USING fts5(word, tokenize='porter unicode61')")
    db.execute("CREATE VIRTUAL TABLE said_terms USING fts5vocab(said, 'instance')")
    db.executemany("INSERT INTO said (rowid, word) VALUES (?, ?)", enumerate(said))
    terms = dict(db.execute("SELECT doc, term FROM said_terms"))
    return [(word, terms.get(i)) for i, word in enumerate(said)]


def _ranked(db, searched, minimum, score):
    """The (rowid, words) of each row that holds at least minimum of the searched words, best first, without the rows
    below SCORE_RATIO of the best score."""
    if not searched:
        return []
    holders = {word: {rowid for (rowid,) in db.execute("SELECT rowid FROM entry WHERE entry MATCH ?", (_quoted(word),))} for word in searched}
    rows = []
    for rowid, rank in db.execute(f"SELECT rowid, {score} FROM entry WHERE entry MATCH ? ORDER BY 2", (" OR ".join(map(_quoted, searched)),)):
        found = [word for word in searched if rowid in holders[word]]
        if len(found) >= minimum:
            rows.append((rowid, rank, found))
    # BM25 gives negative scores, the best lowest
    return [(rowid, found) for rowid, rank, found in rows if rank <= rows[0][1] * SCORE_RATIO]


def _quoted(word):
    return f'"{word}"'


def chosen(memory_hits, lore_hits, skip, recent, slots, memory_slots):
    """The memories and the lore entries of a turn. A content hit whose key is in recent was a hit of a recent turn: its
    shared words would bring it back on each turn, and a model tends to talk about the text that it gets. A name match
    always passes, because the player asked about it. The lore records whose key is in skip are already in the system
    message."""
    def passes(hit):
        return "name" in hit or hit["record"]["key"] not in recent

    memories = [hit for hit in memory_hits if passes(hit)][:min(memory_slots, slots)]
    entries = [hit for hit in lore_hits if hit["record"]["key"] not in skip and passes(hit)][:slots - len(memories)]
    return memories, entries


def clipped(text):
    """The text up to its last sentence end before TEXT_LIMIT characters, or its first TEXT_LIMIT characters."""
    if len(text) <= TEXT_LIMIT:
        return text
    head = text[:TEXT_LIMIT]
    ends = [match.end() for match in re.finditer(r"[.!?](?=\s|$)", head)]
    return head[:ends[-1]] if ends else head


def held(turns, cooldown):
    """The keys of the hits of the last cooldown turns, where turns holds the set of the keys of each turn, oldest first."""
    return set().union(*turns[-cooldown:]) if cooldown > 0 else set()


def next_turns(turns, keys, cooldown):
    return [*turns, set(keys)][-cooldown:] if cooldown > 0 else []
