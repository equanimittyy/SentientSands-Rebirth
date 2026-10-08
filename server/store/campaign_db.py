"""The campaign's characters, dialogue, canon, events, and rumors, in one SQLite file per campaign folder.

Every write runs in one BEGIN IMMEDIATE transaction, and a profile write merges only the keys that the
caller passes. Two requests that change one NPC during an LLM call therefore keep both changes.
"""

import json
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_NAME = "campaign.db"
SCHEMA_VERSION = 16
DIALOGUE_BLOCK = 20
# A memory that this many passes read and did not cite leaves the auto rumor pool, so dull memories do not fill each prompt
RUMOR_PASSES = 6
# The chat count of a provisional profile also marks it as provisional: the template validator, which the campaign editor
# also runs, takes only text and numbers as profile values, so a true/false mark could not be saved from the editor
PROVISIONAL = "Interactions"

SCHEMA = f"""
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE character (
  id         INTEGER PRIMARY KEY,
  npc_id     TEXT NOT NULL UNIQUE,
  profile    TEXT NOT NULL,
  origin     TEXT NOT NULL DEFAULT 'campaign',
  favorite   INTEGER NOT NULL DEFAULT 0,
  knowledge  TEXT NOT NULL DEFAULT '',
  known_by   TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL
);
-- AUTOINCREMENT: the server keeps the ID of the current thread in memory, so the ID of a deleted thread must never name a new one
CREATE TABLE thread (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  game_time    INTEGER,
  location     TEXT,
  memory       TEXT,
  rumor_passes INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE thread_member (
  thread_id         INTEGER NOT NULL REFERENCES thread(id) ON DELETE CASCADE,
  npc_id            TEXT NOT NULL,
  role              TEXT NOT NULL,
  game_time         INTEGER,
  in_player_faction INTEGER NOT NULL,
  PRIMARY KEY (thread_id, npc_id)
);
CREATE TABLE dialogue (
  id           INTEGER PRIMARY KEY,
  character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
  game_time    INTEGER,
  line         TEXT NOT NULL,
  speaker      TEXT,
  thread_id    INTEGER REFERENCES thread(id)
);
CREATE INDEX dialogue_by_character ON dialogue (character_id, id);
CREATE INDEX dialogue_by_thread ON dialogue (thread_id);
CREATE TABLE event (
  id        INTEGER PRIMARY KEY,
  game_time INTEGER,
  data      TEXT NOT NULL
);
CREATE TABLE rumor (
  id          INTEGER PRIMARY KEY,
  event_id    INTEGER NOT NULL UNIQUE REFERENCES event(id) ON DELETE CASCADE,
  game_time   INTEGER,
  text        TEXT NOT NULL,
  instruction TEXT NOT NULL DEFAULT ''
);
CREATE TABLE faction (
  id          INTEGER PRIMARY KEY,
  faction_id  TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  aliases     TEXT NOT NULL DEFAULT '[]',
  major       INTEGER NOT NULL DEFAULT 0,
  fields      TEXT NOT NULL DEFAULT '{{}}',
  description TEXT NOT NULL DEFAULT '',
  is_player   INTEGER NOT NULL DEFAULT 0,
  origin      TEXT NOT NULL DEFAULT 'campaign',
  knowledge   TEXT NOT NULL DEFAULT '',
  known_by    TEXT NOT NULL DEFAULT '[]',
  updated_at  TEXT NOT NULL
);
CREATE TABLE entity (
  id         INTEGER PRIMARY KEY,
  category   TEXT NOT NULL,
  ext_id     TEXT NOT NULL,
  data       TEXT NOT NULL,
  origin     TEXT NOT NULL DEFAULT 'campaign',
  updated_at TEXT NOT NULL,
  UNIQUE (category, ext_id)
);
INSERT INTO meta (key, value) VALUES ('schema_version', '{SCHEMA_VERSION}');
"""

_GAME_TIME = re.compile(r"\[Day (\d+)(?:, (\d+):(\d+))?\]")

_db_path = None
_closed_reason = "No campaign is open."
_open_lock = threading.Lock()
# The web app polls this count, so an open page loads what the game or another tab wrote
writes = 0


class CampaignUnavailable(Exception):
    pass


def open_campaign(folder, seed):
    """seed() gives the template content of a new database. It runs only when the folder has no database."""
    global _db_path, _closed_reason
    with _open_lock:
        path = os.path.join(folder, DB_NAME)
        # Set before the creation, so a failed creation makes writes fail instead of reaching the previous campaign
        _db_path = path
        if not os.path.exists(path):
            create(folder, seed())
            return
        if read_meta(folder).get("schema_version") != str(SCHEMA_VERSION):
            _db_path = None
            _closed_reason = f"The campaign {os.path.basename(folder)} was made by an earlier version of SSR, which this version cannot open. Start a new campaign."
            raise CampaignUnavailable(_closed_reason)


def close_campaign():
    global _db_path, _closed_reason
    with _open_lock:
        _db_path = None
        _closed_reason = "No campaign is selected. On the Campaigns tab, choose one under Current Campaign, or create one under Campaign Manager."


def unavailable_reason():
    """The reason that no campaign can be read, or None."""
    if _db_path is None:
        return _closed_reason
    if not os.path.exists(_db_path):
        return f"The campaign {os.path.basename(os.path.dirname(_db_path))} has no {DB_NAME} file. On the Campaigns tab, choose or create another campaign."
    return None


def read_meta(folder):
    """The meta rows of the database in folder, or {} if it has none. It opens the file read-only, so any campaign can be read."""
    path = os.path.join(folder, DB_NAME)
    if not os.path.exists(path):
        return {}
    conn = sqlite3.connect(Path(os.path.abspath(path)).as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.DatabaseError:
        return {}
    finally:
        conn.close()


def create(folder, seed):
    """Builds the database in a temporary file and renames it, so a crash before the rename leaves no database."""
    tmp = os.path.join(folder, DB_NAME + ".tmp")
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp, isolation_level=None)
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN")
        template = seed["template"]
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [("overview", seed["overview"]), ("history", json.dumps(seed["history"])), ("template_name", template["name"]), ("template_version", template["version"]), ("template_hash", template["hash"])],
        )
        now = _now()
        conn.executemany(
            "INSERT INTO faction (faction_id, name, aliases, major, fields, description, knowledge, known_by, origin, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'seed', ?)",
            [(f["faction_id"], f["name"], json.dumps(f["aliases"]), int(f["major"]), json.dumps(f["fields"]), f["description"], f.get("knowledge", ""), json.dumps(f.get("known_by", [])), now) for f in seed["factions"]],
        )
        conn.executemany(
            "INSERT INTO character (npc_id, profile, knowledge, known_by, origin, updated_at) VALUES (?, ?, ?, ?, 'seed', ?)",
            [(unique_npc_id(c["game_id"]), json.dumps(c["profile"]), c.get("knowledge", ""), json.dumps(c.get("known_by", [])), now) for c in seed["characters"]],
        )
        conn.executemany(
            "INSERT INTO entity (category, ext_id, data, origin, updated_at) VALUES (?, ?, ?, 'seed', ?)",
            [(e["category"], e["id"], json.dumps(e["data"]), now) for e in seed["entities"]],
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    os.replace(tmp, os.path.join(folder, DB_NAME))
    logging.info(f"CAMPAIGN: Created {DB_NAME} in {folder} from the template {seed['template']['name']}")


def unique_npc_id(game_id):
    return f"u:{game_id}"


def get_character(npc_id):
    with _connect() as conn:
        row = conn.execute("SELECT id, profile FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        if not row:
            return None
        profile = json.loads(row[1])
        profile["ConversationHistory"] = [line for (line,) in conn.execute("SELECT line FROM dialogue WHERE character_id = ? ORDER BY id", (row[0],))]
        return profile


def dialogue(npc_id):
    """The dialogue lines of the character as (line, speaker, thread_id) triples, oldest first."""
    with _connect() as conn:
        return conn.execute(
            "SELECT line, speaker, thread_id FROM dialogue WHERE character_id = (SELECT id FROM character WHERE npc_id = ?) ORDER BY id", (npc_id,)
        ).fetchall()


def character_exists(npc_id):
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM character WHERE npc_id = ?", (npc_id,)).fetchone() is not None


def upsert_profile(npc_id, fields):
    """Ignores ConversationHistory, so a caller can pass a whole profile. A value of None removes the key, because the
    template validator takes only text and numbers as profile values."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        if not row:
            _insert_character(conn, npc_id, {k: v for k, v in fields.items() if v is not None})
            return
        profile = json.loads(row[1])
        profile.update(fields)
        profile = {k: v for k, v in profile.items() if v is not None}
        conn.execute("UPDATE character SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(_stored(profile)), _now(), row[0]))


def rename_character(npc_id, old_name, new_name):
    """Also relabels the lines that the character spoke, so its dialogue shows one name. Only the speaker marks them, because
    another NPC near the player can share the old name."""
    own_line = re.compile(r"^((?:\[Day [^\]]*\]\s*)?)" + re.escape(old_name) + ":")
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        if not row:
            return
        profile = json.loads(row[1])
        profile["Name"] = new_name
        conn.execute("UPDATE character SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(profile), _now(), row[0]))
        lines = conn.execute("SELECT id, line FROM dialogue WHERE character_id = ? AND speaker = ?", (row[0], npc_id)).fetchall()
        conn.executemany(
            "UPDATE dialogue SET line = ? WHERE id = ?",
            [(own_line.sub(lambda match: match.group(1) + new_name + ":", line, count=1), line_id) for line_id, line in lines if own_line.match(line)],
        )


def add_alias(npc_id, alias):
    """Sets the Alias of the stored character unless it has one, which the player may have written. Returns whether it set it."""
    with _connect(write=True) as conn:
        return conn.execute(
            "UPDATE character SET profile = json_set(profile, '$.Alias', ?), updated_at = ? WHERE npc_id = ? AND COALESCE(json_extract(profile, '$.Alias'), '') = ''",
            (alias, _now(), npc_id),
        ).rowcount > 0


def change_relation(npc_id, delta):
    """Returns the new Relation, clamped to -100..100, or None if the character is not stored."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        if not row:
            return None
        profile = json.loads(row[1])
        profile["Relation"] = max(-100, min(100, int(profile.get("Relation", 0)) + delta))
        conn.execute("UPDATE character SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(profile), _now(), row[0]))
        return profile["Relation"]


def count_interaction(npc_id):
    """Returns the new Interactions of a provisional profile, or None if the profile is not provisional or not stored."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        profile = json.loads(row[1]) if row else {}
        if PROVISIONAL not in profile:
            return None
        profile[PROVISIONAL] = int(profile[PROVISIONAL]) + 1
        conn.execute("UPDATE character SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(profile), _now(), row[0]))
        return profile[PROVISIONAL]


def promote_profile(npc_id, bio):
    """Writes the bio over a provisional profile, which stops being provisional. Returns False, with no write, if the profile
    is no longer provisional, for example because the player wrote its text by hand while the LLM wrote the bio."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        profile = json.loads(row[1]) if row else {}
        if PROVISIONAL not in profile:
            return False
        del profile[PROVISIONAL]
        profile.update(bio)
        conn.execute("UPDATE character SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(_stored(profile)), _now(), row[0]))
        return True


def append_dialogue(npc_id, lines, profile, thread_id=None):
    """lines are (line, speaker) pairs, where speaker is the npc_id of the character who spoke, or None. Stores profile first
    only if the character is not stored yet. No line is trimmed: the memory of a thread replaces its lines (set_memory)."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        if row:
            character_id = row[0]
            conn.execute("UPDATE character SET updated_at = ? WHERE id = ?", (_now(), character_id))
        else:
            character_id = _insert_character(conn, npc_id, profile)
        conn.executemany(
            "INSERT INTO dialogue (character_id, game_time, line, speaker, thread_id) VALUES (?, ?, ?, ?, ?)",
            [(character_id, game_time(line), line, speaker, thread_id) for line, speaker in lines],
        )


def join_thread(thread_id, members, joined_at, location=None):
    """Adds members, (npc_id, role, in_player_faction) triples, to the thread, or to a new thread at location when thread_id
    is None or names a deleted thread. A member keeps the game time and the faction of its first join, and an overhearer
    becomes a speaker when it speaks. The thread takes joined_at as the game time of its newest exchange. Returns the
    thread ID."""
    with _connect(write=True) as conn:
        if thread_id is None or not conn.execute("SELECT 1 FROM thread WHERE id = ?", (thread_id,)).fetchone():
            thread_id = conn.execute("INSERT INTO thread (location) VALUES (?)", (location,)).lastrowid
        conn.execute("UPDATE thread SET game_time = COALESCE(?, game_time) WHERE id = ?", (joined_at, thread_id))
        conn.executemany(
            "INSERT INTO thread_member (thread_id, npc_id, role, game_time, in_player_faction) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (thread_id, npc_id) DO UPDATE SET role = excluded.role WHERE excluded.role = 'speaker'",
            [(thread_id, npc_id, role, joined_at, int(in_player_faction)) for npc_id, role, in_player_faction in members],
        )
    return thread_id


def thread_members(thread_ids):
    """The members of each thread as (npc_id, name, role, in_player_faction), in the order that they joined. The name is
    None when the character is gone."""
    thread_ids = list(thread_ids)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT m.thread_id, m.npc_id, json_extract(c.profile, '$.Name'), m.role, m.in_player_faction FROM thread_member m"
            f" LEFT JOIN character c ON c.npc_id = m.npc_id WHERE m.thread_id IN ({', '.join('?' * len(thread_ids))}) ORDER BY m.rowid",
            thread_ids,
        ).fetchall()
    members = {}
    for thread_id, npc_id, name, role, in_player_faction in rows:
        members.setdefault(thread_id, []).append((npc_id, name, role, bool(in_player_faction)))
    return members


def threads():
    """Each thread that has a line or a memory, newest first, as a dict with its members, the game time of its first
    exchange, the place where it started or None, its memory or None, and the lines of one copy (_thread_lines). A thread
    with a memory has no lines."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT t.id, MIN(m.game_time), t.location, t.memory FROM thread t LEFT JOIN thread_member m ON m.thread_id = t.id GROUP BY t.id ORDER BY t.id DESC"
        ).fetchall()
        lines = _thread_lines(conn)
    rows = [row for row in rows if row[0] in lines or row[3] is not None]
    members = thread_members(thread_id for thread_id, *_ in rows)
    return [
        {"id": thread_id, "game_time": first_time, "location": location, "members": members.get(thread_id, []), "memory": memory, "lines": lines.get(thread_id, [])}
        for thread_id, first_time, location, memory in rows
    ]


def pending_threads():
    """Each thread that has a line and no memory, oldest first, as a dict with the game time of its newest exchange and the
    lines of one copy (_thread_lines)."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, game_time FROM thread WHERE memory IS NULL ORDER BY id").fetchall()
        lines = _thread_lines(conn)
    return [{"id": thread_id, "game_time": newest, "lines": lines[thread_id]} for thread_id, newest in rows if thread_id in lines]


def set_memory(thread_id, memory, game_time):
    """Stores the memory of a pending thread and deletes every copy of its lines, which the memory replaces. Returns False,
    with no write, when the thread is gone, has a memory, or no longer has the game_time that the caller read, for example
    because a cull removed its newest lines during the call."""
    with _connect(write=True) as conn:
        if not conn.execute("UPDATE thread SET memory = ? WHERE id = ? AND memory IS NULL AND game_time IS ?", (memory, thread_id, game_time)).rowcount:
            return False
        conn.execute("DELETE FROM dialogue WHERE thread_id = ?", (thread_id,))
        return True


def edit_memory(thread_id, memory):
    """Replaces the text of a memory. Returns False when the thread has no memory."""
    with _connect(write=True) as conn:
        return conn.execute("UPDATE thread SET memory = ? WHERE id = ? AND memory IS NOT NULL", (memory, thread_id)).rowcount > 0


def delete_memory(thread_id):
    """Deletes a thread with a memory, with its members. The memory replaced its lines, so nothing of the conversation stays."""
    with _connect(write=True) as conn:
        return conn.execute("DELETE FROM thread WHERE id = ? AND memory IS NOT NULL", (thread_id,)).rowcount > 0


def memories_of(npc_id, limit=None):
    """The newest limit chat threads with a memory in which the character is a member, or all of them, oldest first, as
    dicts with the game time of the first exchange, the memory, and the members (thread_members)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT t.id, (SELECT MIN(game_time) FROM thread_member WHERE thread_id = t.id), t.memory FROM thread t"
            " WHERE t.memory IS NOT NULL AND EXISTS (SELECT 1 FROM thread_member WHERE thread_id = t.id AND npc_id = ?) ORDER BY t.id DESC LIMIT ?",
            (npc_id, -1 if limit is None else limit),
        ).fetchall()
    return _memories(list(reversed(rows)))


def shared_memories(npc_ids):
    """The threads with a memory in which at least 2 of the characters are members, oldest first, as memories_of gives them."""
    npc_ids = list(npc_ids)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT t.id, (SELECT MIN(game_time) FROM thread_member WHERE thread_id = t.id), t.memory FROM thread t WHERE t.memory IS NOT NULL"
            f" AND (SELECT COUNT(*) FROM thread_member WHERE thread_id = t.id AND npc_id IN ({', '.join('?' * len(npc_ids))})) >= 2 ORDER BY t.id",
            npc_ids,
        ).fetchall()
    return _memories(rows)


def rumor_pool(limit):
    """The newest limit memories in the pool of the auto rumors, oldest first, as memories_of gives them, with the place of
    the thread and the count of the passes that read the memory and did not cite it."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT t.id, (SELECT MIN(game_time) FROM thread_member WHERE thread_id = t.id), t.memory, t.location, t.rumor_passes FROM thread t"
            " WHERE t.memory IS NOT NULL AND t.rumor_passes < ? ORDER BY t.id DESC LIMIT ?",
            (RUMOR_PASSES, limit),
        ).fetchall()
    rows.reverse()
    memories = _memories([row[:3] for row in rows])
    for memory, (_, _, _, location, passes) in zip(memories, rows):
        memory.update(location=location, passes=passes)
    return memories


def count_rumor_pass(thread_ids):
    """Counts a pass of the auto rumors that read the memories of the threads, the newest of the pool. Each of them that is
    still in the pool gets one more pass, and each memory of the pool older than them leaves it, so a cited memory does not
    let an old memory back into the window that the next pass reads."""
    thread_ids = list(thread_ids)
    with _connect(write=True) as conn:
        conn.execute(f"UPDATE thread SET rumor_passes = rumor_passes + 1 WHERE rumor_passes < ? AND id IN ({', '.join('?' * len(thread_ids))})", (RUMOR_PASSES, *thread_ids))
        conn.execute("UPDATE thread SET rumor_passes = ?1 WHERE memory IS NOT NULL AND rumor_passes < ?1 AND id < ?2", (RUMOR_PASSES, min(thread_ids)))


def _memories(rows):
    members = thread_members(thread_id for thread_id, _, _ in rows)
    return [{"id": thread_id, "game_time": first_time, "memory": memory, "members": members.get(thread_id, [])} for thread_id, first_time, memory in rows]


def thread_partners(npc_id):
    """The other speaker of each chat thread in which the character is a speaker, oldest thread first. The members stay after
    a memory replaced the lines of the thread."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT o.npc_id FROM thread_member m JOIN thread_member o ON o.thread_id = m.thread_id AND o.role = 'speaker' AND o.npc_id != m.npc_id"
            " WHERE m.npc_id = ? AND m.role = 'speaker' ORDER BY m.thread_id, o.rowid",
            (npc_id,),
        ).fetchall()
    return [partner for (partner,) in rows]


def thread_places(npc_id):
    """The place of each chat thread in which the character is a member, as a speaker or as an overhearer, each once."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.location FROM thread t JOIN thread_member m ON m.thread_id = t.id WHERE m.npc_id = ? AND t.location IS NOT NULL", (npc_id,)
        ).fetchall()
    return [location for (location,) in rows]


def character_places():
    """The place of each chat thread of each character, by npc_id, newest thread first, as thread_places gives them."""
    with _connect() as conn:
        rows = conn.execute("SELECT m.npc_id, t.location FROM thread t JOIN thread_member m ON m.thread_id = t.id WHERE t.location IS NOT NULL ORDER BY t.id DESC").fetchall()
    places = {}
    for npc_id, location in rows:
        places.setdefault(npc_id, []).append(location)
    return places


def names_of(npc_ids):
    """The Name of each stored character among npc_ids."""
    npc_ids = list(npc_ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT npc_id, json_extract(profile, '$.Name') FROM character WHERE npc_id IN ({', '.join('?' * len(npc_ids))})", npc_ids
        ).fetchall()
    return {npc_id: name for npc_id, name in rows if name}


def list_characters():
    """A thread member counts as having dialogue, and a speaker as taking part, because a memory replaces the lines of its thread."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT npc_id, json_extract(profile, '$.Name'), origin, favorite, updated_at,"
            " EXISTS (SELECT 1 FROM dialogue WHERE character_id = character.id) OR EXISTS (SELECT 1 FROM thread_member WHERE npc_id = character.npc_id),"
            " EXISTS (SELECT 1 FROM dialogue WHERE character_id = character.id"
            " AND line NOT LIKE '(Overheard)%' AND line NOT LIKE '[Day %] (Overheard)%')"
            " OR EXISTS (SELECT 1 FROM thread_member WHERE npc_id = character.npc_id AND role = 'speaker') FROM character"
        ).fetchall()
    return [
        {"npc_id": npc_id, "name": name, "origin": origin, "favorite": bool(fav), "updated_at": updated, "has_dialogue": bool(talked),
         "only_overheard": bool(talked) and not took_part}
        for npc_id, name, origin, fav, updated, talked, took_part in rows
    ]


def character_names():
    with _connect() as conn:
        rows = conn.execute("SELECT json_extract(profile, '$.Name') FROM character").fetchall()
    return {name for (name,) in rows if name}


def toggle_favorite(npc_id):
    """Returns the new state, or None if the character is not stored."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, favorite FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE character SET favorite = ? WHERE id = ?", (int(not row[1]), row[0]))
        return not row[1]


def add_event(kind, doers, victim, game_time):
    """Stores the event of a known figure that the doers, (npc_id, name) pairs, killed or captured. kind is "kill"
    or "capture", and victim holds the npc_id, name, and faction. A doer that already captured the victim gets no second
    capture, because the game imprisons each prisoner again when a save loads. Returns the doers of the event."""
    with _connect(write=True) as conn:
        if kind == "capture":
            captors = {doer["id"] for (event,) in conn.execute(
                "SELECT data FROM event WHERE json_extract(data, '$.kind') = 'capture' AND json_extract(data, '$.victim.id') = ?", (victim["npc_id"],)
            ) for doer in json.loads(event)["doers"]}
            doers = [doer for doer in doers if doer[0] not in captors]
        if doers:
            event = {"kind": kind, "doers": [{"id": npc_id, "name": name} for npc_id, name in doers], "victim": {"id": victim["npc_id"], "name": victim["name"], "faction": victim["faction"]}}
            conn.execute("INSERT INTO event (game_time, data) VALUES (?, ?)", (game_time, json.dumps(event)))
    return doers


def add_custom_event(rumor):
    """Stores a custom event, for an act that the game does not track, with the rumor that the player wrote and no game
    time. Returns its event ID."""
    with _connect(write=True) as conn:
        event_id = conn.execute("INSERT INTO event (data) VALUES (?)", (json.dumps({"kind": "custom"}),)).lastrowid
        conn.execute("INSERT INTO rumor (event_id, text) VALUES (?, ?)", (event_id, rumor))
        return event_id


def add_auto_event(rumor, thread_ids):
    """Stores an auto event, with the rumor that the LLM spun from the memories of the threads, each once. The event takes the
    newest game time of the threads, so the cull deletes it with its memories. The threads leave the pool of the auto rumors.
    Returns its event ID, or None, with no write, when a thread is gone or out of the pool, because a delete or a
    cull changed the pool during the call."""
    thread_ids = list(thread_ids)
    marks = ", ".join("?" * len(thread_ids))
    with _connect(write=True) as conn:
        times = [at for (at,) in conn.execute(f"SELECT game_time FROM thread WHERE memory IS NOT NULL AND rumor_passes < ? AND id IN ({marks})", (RUMOR_PASSES, *thread_ids))]
        if len(times) != len(thread_ids):
            return None
        at = max((at for at in times if at is not None), default=None)
        event_id = conn.execute("INSERT INTO event (game_time, data) VALUES (?, ?)", (at, json.dumps({"kind": "auto", "threads": thread_ids}))).lastrowid
        conn.execute("INSERT INTO rumor (event_id, game_time, text) VALUES (?, ?, ?)", (event_id, at, rumor))
        conn.execute(f"UPDATE thread SET rumor_passes = ? WHERE id IN ({marks})", (RUMOR_PASSES, *thread_ids))
        return event_id


def add_bounty_event(event, game_time):
    """Stores a bounty that the plugin placed, with no rumor yet. Returns its event ID."""
    with _connect(write=True) as conn:
        return conn.execute("INSERT INTO event (game_time, data) VALUES (?, ?)", (game_time, json.dumps({"kind": "bounty", **event}))).lastrowid


def add_bounty_rumor(event_id, notice, rumor):
    """Adds the wanted notice and the rumor of a bounty, unless the bounty is gone or already has a rumor. Returns whether it
    added them."""
    with _connect(write=True) as conn:
        if conn.execute("INSERT OR IGNORE INTO rumor (event_id, game_time, text) SELECT id, game_time, ? FROM event WHERE id = ?", (rumor, event_id)).rowcount == 0:
            return False
        conn.execute("UPDATE event SET data = json_set(data, '$.notice', ?) WHERE id = ?", (notice, event_id))
        return True


def delete_event(event_id):
    """Deletes a custom, an auto, or a bounty event with its rumor. The memories of an auto event stay out of the pool, so the
    next pass does not spin the same rumor again."""
    with _connect(write=True) as conn:
        return conn.execute("DELETE FROM event WHERE id = ? AND json_extract(data, '$.kind') IN ('custom', 'auto', 'bounty')", (event_id,)).rowcount > 0


def events():
    """Every event as (id, game_time, event), newest first. A custom event has no game time and counts as the newest."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, game_time, data FROM event ORDER BY game_time DESC NULLS FIRST, id DESC").fetchall()
    return [(event_id, at, json.loads(event)) for event_id, at, event in rows]


def rumors():
    """Every rumor as a dict, oldest first by game time. The rumor of a custom event has no game time and counts as the newest."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, event_id, game_time, text, instruction FROM rumor ORDER BY game_time NULLS LAST, id").fetchall()
    return [{"id": rumor_id, "event_id": event_id, "game_time": at, "text": text, "instruction": instruction}
            for rumor_id, event_id, at, text, instruction in rows]


def event(event_id):
    """The event as (game_time, event), or None."""
    with _connect() as conn:
        row = conn.execute("SELECT game_time, data FROM event WHERE id = ?", (event_id,)).fetchone()
    return (row[0], json.loads(row[1])) if row else None


def save_rumor(rumor_id, event_id, text, instruction=None):
    """Saves the text of the rumor, or of the rumor of the event when rumor_id is None, and adds that rumor with the
    game time of its event when it has none. instruction None keeps the stored one. Returns False when the rumor or
    the event is gone."""
    with _connect(write=True) as conn:
        if rumor_id is None:
            row = conn.execute("SELECT id FROM rumor WHERE event_id = ?", (event_id,)).fetchone()
            if row is None:
                event = conn.execute("SELECT game_time FROM event WHERE id = ?", (event_id,)).fetchone()
                if event is None:
                    return False
                rumor_id = conn.execute("INSERT INTO rumor (event_id, game_time, text) VALUES (?, ?, '')", (event_id, event[0])).lastrowid
            else:
                rumor_id = row[0]
        return conn.execute("UPDATE rumor SET text = ?, instruction = COALESCE(?, instruction) WHERE id = ?", (text, instruction, rumor_id)).rowcount > 0


def add_rumor(event_id, text):
    """Adds the rumor of the event with its game time, unless the event is gone or already has a rumor, which the
    player may have saved while the LLM wrote this one. Returns whether it added the rumor."""
    with _connect(write=True) as conn:
        return conn.execute("INSERT OR IGNORE INTO rumor (event_id, game_time, text) SELECT id, game_time, ? FROM event WHERE id = ?", (text, event_id)).rowcount > 0


def cull_after(day, hour, minute):
    """Deletes the dialogue, events, rumors, thread members, and memories dated after the given game time. Returns
    the count per table of the dialogue, the events, and the rumors."""
    now = day * 1440 + hour * 60 + minute
    with _connect(write=True) as conn:
        touched = {thread_id for (thread_id,) in conn.execute("SELECT id FROM thread WHERE game_time > ?", (now,))}
        culled = {table: conn.execute(f"DELETE FROM {table} WHERE game_time > ?", (now,)).rowcount for table in ("dialogue", "rumor", "event")}
        conn.execute("DELETE FROM thread_member WHERE game_time > ?", (now,))
        # The memory told of culled exchanges, and it replaced every line, so nothing from before the cut is left to keep
        conn.execute("DELETE FROM thread WHERE memory IS NOT NULL AND game_time > ?", (now,))
        conn.execute("UPDATE thread SET game_time = (SELECT MAX(game_time) FROM dialogue WHERE thread_id = thread.id) WHERE game_time > ?", (now,))
        _drop_unused_threads(conn, touched)
        return culled


def delete_rumor(rumor_id):
    with _connect(write=True) as conn:
        return conn.execute("DELETE FROM rumor WHERE id = ?", (rumor_id,)).rowcount > 0


def overview():
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'overview'").fetchone()
    return row[0] if row else ""


def set_overview(text):
    with _connect(write=True) as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('overview', ?)", (text,))


def history():
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'history'").fetchone()
    return json.loads(row[0]) if row else []


def set_history(entries):
    with _connect(write=True) as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('history', ?)", (json.dumps(entries),))


def template_info():
    """The name, version, and content hash of the template that the campaign came from."""
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM meta WHERE key LIKE 'template_%'").fetchall()
    return {key[len("template_"):]: value for key, value in rows}


class StaleRecord(Exception):
    pass


class DuplicateRecord(Exception):
    pass


FACTION_KEYS = ("name", "aliases", "major", "fields", "description", "knowledge", "known_by")
_FACTION_COLUMNS = "faction_id, name, aliases, major, fields, description, knowledge, known_by, is_player, origin, updated_at"


def list_factions():
    """The player's faction first, then by name."""
    with _connect() as conn:
        rows = conn.execute(f"SELECT {_FACTION_COLUMNS} FROM faction ORDER BY is_player DESC, name COLLATE NOCASE").fetchall()
    return [_faction(row) for row in rows]


def find_faction(faction_id=None, name=None):
    """By the game ID first, then by name or alias, ignoring case."""
    with _connect() as conn:
        row = None
        if faction_id:
            row = conn.execute(f"SELECT {_FACTION_COLUMNS} FROM faction WHERE faction_id = ?", (faction_id,)).fetchone()
        if row is None and name:
            row = conn.execute(
                f"SELECT {_FACTION_COLUMNS} FROM faction WHERE name = ?1 COLLATE NOCASE"
                " OR EXISTS (SELECT 1 FROM json_each(faction.aliases) WHERE value = ?1 COLLATE NOCASE)"
                " ORDER BY is_player DESC, id LIMIT 1",
                (name,),
            ).fetchone()
    return _faction(row) if row else None


def player_faction():
    with _connect() as conn:
        row = conn.execute(f"SELECT {_FACTION_COLUMNS} FROM faction WHERE is_player = 1").fetchone()
    return _faction(row) if row else None


def note_faction(faction_id, name, is_player=False):
    """Adds a faction that the game reports and the store lacks, with an empty description.

    The player's faction takes the name that the game gives, because the player can rename it in game.
    """
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, name, is_player FROM faction WHERE faction_id = ?", (faction_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO faction (faction_id, name, is_player, origin, updated_at) VALUES (?, ?, ?, 'game', ?)", (faction_id, name, int(is_player), _now()))
        elif is_player and (row[1] != name or not row[2]):
            conn.execute("UPDATE faction SET name = ?, is_player = 1, updated_at = ? WHERE id = ?", (name, _now(), row[0]))
        if is_player:
            conn.execute("UPDATE faction SET is_player = 0, updated_at = ? WHERE is_player = 1 AND faction_id != ?", (_now(), faction_id))


def add_faction(faction_id, values):
    """Raises DuplicateRecord if the campaign already holds faction_id."""
    with _connect(write=True) as conn:
        if conn.execute("SELECT 1 FROM faction WHERE faction_id = ?", (faction_id,)).fetchone():
            raise DuplicateRecord(faction_id)
        conn.execute(
            "INSERT INTO faction (faction_id, name, aliases, major, fields, description, knowledge, known_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (faction_id, values["name"], json.dumps(values["aliases"]), int(values["major"]), json.dumps(values["fields"]), values["description"], values.get("knowledge", ""), json.dumps(values.get("known_by", [])), _now()),
        )


def delete_faction(faction_id):
    with _connect(write=True) as conn:
        return conn.execute("DELETE FROM faction WHERE faction_id = ?", (faction_id,)).rowcount > 0


def update_faction(faction_id, changes, updated_at):
    """Returns the saved faction, or None if it is not stored.

    Raises StaleRecord if the row changed after the caller read updated_at, for example when the game renamed the
    player's faction during an edit.
    """
    with _connect(write=True) as conn:
        row = conn.execute("SELECT updated_at FROM faction WHERE faction_id = ?", (faction_id,)).fetchone()
        if row is None:
            return None
        if row[0] != updated_at:
            raise StaleRecord(faction_id)
        values = {key: changes[key] for key in FACTION_KEYS if key in changes}
        for key in ("aliases", "fields", "known_by"):
            if key in values:
                values[key] = json.dumps(values[key])
        if "major" in values:
            values["major"] = int(values["major"])
        values["updated_at"] = _now()
        conn.execute(f"UPDATE faction SET {', '.join(f'{key} = ?' for key in values)} WHERE faction_id = ?", (*values.values(), faction_id))
        saved = conn.execute(f"SELECT {_FACTION_COLUMNS} FROM faction WHERE faction_id = ?", (faction_id,)).fetchone()
    return _faction(saved)


def _faction(row):
    faction_id, name, aliases, major, fields, description, knowledge, known_by, is_player, origin, updated_at = row
    return {
        "faction_id": faction_id,
        "name": name,
        "aliases": json.loads(aliases),
        "major": bool(major),
        "fields": json.loads(fields),
        "description": description,
        "knowledge": knowledge,
        "known_by": json.loads(known_by),
        "is_player": bool(is_player),
        "origin": origin,
        "updated_at": updated_at,
    }


# kind: (table, key columns, JSON column)
_RECORDS = {"character": ("character", ("npc_id",), "profile"), "entity": ("entity", ("category", "ext_id"), "data")}


def list_records(kind):
    """Each record of the kind as (key, value, origin, updated_at), where key is a tuple of the key columns."""
    table, keys, column = _RECORDS[kind]
    with _connect() as conn:
        rows = conn.execute(f"SELECT {', '.join(keys)}, {column}, origin, updated_at FROM {table} ORDER BY id").fetchall()
    return [(row[:len(keys)], json.loads(row[len(keys)]), *row[len(keys) + 1:]) for row in rows]


def save_record(kind, key, value, updated_at, knowledge=None):
    """Adds the record when updated_at is None, else replaces its value. knowledge holds the knowledge and known_by of a
    character, which its row keeps beside the profile, because the validator takes only text and numbers as profile values.

    Raises DuplicateRecord if a new record's key is taken, and StaleRecord if the record changed after the caller read
    updated_at or is gone.
    """
    table, keys, column = _RECORDS[kind]
    match = " AND ".join(f"{name} = ?" for name in keys)
    columns = {column: json.dumps(value), **({"knowledge": knowledge["knowledge"], "known_by": json.dumps(knowledge["known_by"])} if knowledge else {}), "updated_at": _now()}
    with _connect(write=True) as conn:
        row = conn.execute(f"SELECT updated_at FROM {table} WHERE {match}", key).fetchone()
        if updated_at is None:
            if row:
                raise DuplicateRecord(key)
            conn.execute(f"INSERT INTO {table} ({', '.join([*keys, *columns])}) VALUES ({', '.join('?' * (len(keys) + len(columns)))})", (*key, *columns.values()))
        elif row is None or row[0] != updated_at:
            raise StaleRecord(key)
        else:
            conn.execute(f"UPDATE {table} SET {', '.join(f'{name} = ?' for name in columns)} WHERE {match}", (*columns.values(), *key))


def character_knowledge():
    """The knowledge and known_by of each character, by npc_id. An empty knowledge means the default of a character."""
    with _connect() as conn:
        rows = conn.execute("SELECT npc_id, knowledge, known_by FROM character").fetchall()
    return {npc_id: {"knowledge": knowledge, "known_by": json.loads(known_by)} for npc_id, knowledge, known_by in rows}


def delete_record(kind, key):
    table, keys, _ = _RECORDS[kind]
    with _connect(write=True) as conn:
        touched = _threads_of(conn, "character_id = (SELECT id FROM character WHERE npc_id = ?)", key) if kind == "character" else set()
        deleted = conn.execute(f"DELETE FROM {table} WHERE {' AND '.join(f'{name} = ?' for name in keys)}", key).rowcount > 0
        _drop_unused_threads(conn, touched)
        return deleted


@contextmanager
def _connect(write=False):
    global writes
    reason = unavailable_reason()
    if reason:
        raise CampaignUnavailable(reason)
    # mode=rw: a missing file must fail, not become an empty database that the next open takes as created
    conn = sqlite3.connect(Path(os.path.abspath(_db_path)).as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.execute("COMMIT")
        # After the commit, so a page that sees the new count also reads the new data
        if write:
            writes += 1
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _insert_character(conn, npc_id, profile):
    return conn.execute("INSERT INTO character (npc_id, profile, origin, updated_at) VALUES (?, ?, 'game', ?)", (npc_id, json.dumps(_stored(profile)), _now())).lastrowid


def _threads_of(conn, where, args):
    """The threads of the dialogue rows that match where."""
    return {thread_id for (thread_id,) in conn.execute(f"SELECT DISTINCT thread_id FROM dialogue WHERE thread_id IS NOT NULL AND {where}", args)}


def _drop_unused_threads(conn, thread_ids):
    """Deletes each of the threads that has no memory and that no dialogue row uses any more, with its members."""
    conn.executemany(
        "DELETE FROM thread WHERE id = ?1 AND memory IS NULL AND NOT EXISTS (SELECT 1 FROM dialogue WHERE thread_id = ?1)", [(thread_id,) for thread_id in thread_ids]
    )


def _thread_lines(conn):
    """The lines of one copy of each thread that has a line: the copy of a speaker, because its lines have no (Overheard)
    tag, or of an overhearer when the delete of the speakers left no other copy."""
    copies = conn.execute(
        "SELECT d.thread_id, d.character_id, COUNT(*),"
        " EXISTS (SELECT 1 FROM thread_member m WHERE m.thread_id = d.thread_id AND m.npc_id = c.npc_id AND m.role = 'speaker')"
        " FROM dialogue d JOIN character c ON c.id = d.character_id WHERE d.thread_id IS NOT NULL GROUP BY d.thread_id, d.character_id"
    ).fetchall()
    best = {}
    for thread_id, character_id, count, is_speaker in copies:
        if thread_id not in best or (is_speaker, count) > best[thread_id][0]:
            best[thread_id] = ((is_speaker, count), character_id)
    return {
        thread_id: [line for (line,) in conn.execute("SELECT line FROM dialogue WHERE thread_id = ? AND character_id = ? ORDER BY id", (thread_id, character_id))]
        for thread_id, (_, character_id) in best.items()
    }


def _stored(profile):
    return {k: v for k, v in profile.items() if k != "ConversationHistory"}


def game_time(line):
    """Minutes from day 0 in the line's first [Day N, HH:MM] tag, or None."""
    match = _GAME_TIME.search(line)
    if not match:
        return None
    return int(match.group(1)) * 1440 + int(match.group(2) or 0) * 60 + int(match.group(3) or 0)


def game_time_text(minutes):
    """The "Day N, HH:MM" text of the minutes that game_time gives."""
    return f"Day {minutes // 1440}, {minutes % 1440 // 60:02d}:{minutes % 60:02d}"


def _now():
    # Fixed width, so updated_at sorts as text
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
