"""The campaign's characters, dialogue, canon, deeds, notable events, and rumors, in one SQLite file per campaign folder.

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
SCHEMA_VERSION = 9
DIALOGUE_BLOCK = 20
# A few kills are part of any trip through the wasteland, so the scale starts at 25
COUNT_STEPS = (25, 100, 250, 500)
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
  updated_at TEXT NOT NULL
);
-- AUTOINCREMENT: the server keeps the ID of the current thread in memory, so the ID of a deleted thread must never name a new one
CREATE TABLE thread (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  game_time INTEGER,
  memory    TEXT
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
CREATE TABLE deed (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,
  doer_id     TEXT NOT NULL,
  doer_name   TEXT NOT NULL,
  victim_id   TEXT NOT NULL,
  victim_name TEXT NOT NULL,
  faction     TEXT NOT NULL,
  race        TEXT NOT NULL,
  animal      INTEGER NOT NULL,
  figure      INTEGER NOT NULL,
  game_time   INTEGER NOT NULL
);
CREATE INDEX deed_by_doer ON deed (doer_id, kind);
CREATE TABLE notable (
  id        INTEGER PRIMARY KEY,
  kind      TEXT NOT NULL,
  game_time INTEGER NOT NULL,
  deed      TEXT NOT NULL
);
-- SET NULL: a count that an alias joins into another count goes, and the rumor that the player wrote must stay
CREATE TABLE rumor (
  id          INTEGER PRIMARY KEY,
  notable_id  INTEGER UNIQUE REFERENCES notable(id) ON DELETE SET NULL,
  game_time   INTEGER NOT NULL,
  text        TEXT NOT NULL,
  instruction TEXT NOT NULL DEFAULT '',
  step        INTEGER
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
            "INSERT INTO faction (faction_id, name, aliases, major, fields, description, origin, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'seed', ?)",
            [(f["faction_id"], f["name"], json.dumps(f["aliases"]), int(f["major"]), json.dumps(f["fields"]), f["description"], now) for f in seed["factions"]],
        )
        conn.executemany(
            "INSERT INTO character (npc_id, profile, origin, updated_at) VALUES (?, ?, 'seed', ?)",
            [(unique_npc_id(c["game_id"]), json.dumps(c["profile"]), now) for c in seed["characters"]],
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
    only if the character is not stored yet. A banter line has no thread. No line is trimmed: the memory of a chat thread
    replaces its lines (set_memory), and banter lines stay."""
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


def join_thread(thread_id, members, joined_at):
    """Adds members, (npc_id, role, in_player_faction) triples, to the thread, or to a new thread when thread_id is None or
    names a deleted thread. A member keeps the game time and the faction of its first join, and the thread takes joined_at
    as the game time of its newest exchange. Returns the thread ID."""
    with _connect(write=True) as conn:
        if thread_id is None or not conn.execute("SELECT 1 FROM thread WHERE id = ?", (thread_id,)).fetchone():
            thread_id = conn.execute("INSERT INTO thread DEFAULT VALUES").lastrowid
        conn.execute("UPDATE thread SET game_time = COALESCE(?, game_time) WHERE id = ?", (joined_at, thread_id))
        conn.executemany(
            "INSERT OR IGNORE INTO thread_member (thread_id, npc_id, role, game_time, in_player_faction) VALUES (?, ?, ?, ?, ?)",
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
    """Each chat thread that has a line or a memory, newest first, as a dict with its members, the game time of its first
    exchange, its memory or None, and the lines of one copy (_thread_lines). A thread with a memory has no lines."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT t.id, MIN(m.game_time), t.memory FROM thread t LEFT JOIN thread_member m ON m.thread_id = t.id GROUP BY t.id ORDER BY t.id DESC"
        ).fetchall()
        lines = _thread_lines(conn)
    rows = [row for row in rows if row[0] in lines or row[2] is not None]
    members = thread_members(thread_id for thread_id, _, _ in rows)
    return [
        {"id": thread_id, "game_time": first_time, "members": members.get(thread_id, []), "memory": memory, "lines": lines.get(thread_id, [])}
        for thread_id, first_time, memory in rows
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
    members = thread_members(thread_id for thread_id, _, _ in rows)
    return [{"id": thread_id, "game_time": first_time, "memory": memory, "members": members.get(thread_id, [])} for thread_id, first_time, memory in reversed(rows)]


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


def known_figure(npc_id):
    """A character of the canon, which the template or the player added. A character that the server added in play is none,
    because each NPC that the player talks to gets a profile."""
    with _connect() as conn:
        row = conn.execute("SELECT origin FROM character WHERE npc_id = ?", (npc_id,)).fetchone()
    return bool(row) and row[0] in ("seed", "campaign")


def add_deeds(kind, doers, victim, figure, game_time):
    """Stores a deed, "kill" or "capture", for each doer, an (npc_id, name) pair. victim holds the npc_id, name, faction,
    race, and animal flag. A doer that already captured the victim gets no second capture, because the game imprisons each
    prisoner again when a save loads. Adds the notable event of a known figure, and updates the counts of the doers. Returns
    the doers that got a deed."""
    with _connect(write=True) as conn:
        if kind == "capture":
            doers = [doer for doer in doers if not conn.execute(
                "SELECT 1 FROM deed WHERE kind = 'capture' AND doer_id = ? AND victim_id = ?", (doer[0], victim["npc_id"])).fetchone()]
        conn.executemany(
            "INSERT INTO deed (kind, doer_id, doer_name, victim_id, victim_name, faction, race, animal, figure, game_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(kind, npc_id, name, victim["npc_id"], victim["name"], victim["faction"], victim["race"], int(victim["animal"]), int(figure), game_time) for npc_id, name in doers],
        )
        if doers and figure:
            deed = {"deed": kind, "doers": [{"id": npc_id, "name": name} for npc_id, name in doers], "victim": {"id": victim["npc_id"], "name": victim["name"], "faction": victim["faction"]}}
            conn.execute("INSERT INTO notable (kind, game_time, deed) VALUES ('figure', ?, ?)", (game_time, json.dumps(deed)))
        elif doers and kind == "kill":
            _refresh_counts(conn, [npc_id for npc_id, _ in doers])
    return doers


def deed_summary():
    """For each doer: its kills of characters that are not known figures, as (target, value, count) with target "faction" or
    "race", most first; and the known figures that it killed or captured, as (kind, npc_id, name), oldest first."""
    summary = {}
    with _connect() as conn:
        races = _race_entries(conn)
        rows = conn.execute("SELECT doer_id, kind, victim_id, victim_name, faction, race, animal, figure FROM deed ORDER BY game_time, id").fetchall()
    for doer, kind, victim_id, victim_name, faction, race, animal, figure in rows:
        entry = summary.setdefault(doer, {"kills": {}, "figures": []})
        if figure:
            entry["figures"].append((kind, victim_id, victim_name))
        else:
            key = ("race", races.get(race.lower(), race)) if animal else ("faction", faction)
            entry["kills"][key] = entry["kills"].get(key, 0) + 1
    return {doer: {"kills": sorted(((target, value, count) for (target, value), count in entry["kills"].items()), key=lambda kill: -kill[2]), "figures": entry["figures"]}
            for doer, entry in summary.items()}


def notables():
    """Every notable event as (id, kind, game_time, deed), newest first. A count has the game time of the kill that reached
    its step."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, kind, game_time, deed FROM notable ORDER BY game_time DESC, id DESC").fetchall()
    return [(notable_id, kind, at, json.loads(deed)) for notable_id, kind, at, deed in rows]


def rumors():
    """Every rumor as a dict, oldest first by game time. step is the step of its count when the player saved it."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, notable_id, game_time, text, instruction, step FROM rumor ORDER BY game_time, id").fetchall()
    return [{"id": rumor_id, "notable_id": notable_id, "game_time": at, "text": text, "instruction": instruction, "step": step}
            for rumor_id, notable_id, at, text, instruction, step in rows]


def notable(notable_id):
    """The notable event as (kind, game_time, deed), or None."""
    with _connect() as conn:
        row = conn.execute("SELECT kind, game_time, deed FROM notable WHERE id = ?", (notable_id,)).fetchone()
    return (row[0], row[1], json.loads(row[2])) if row else None


def save_rumor(rumor_id, notable_id, text, instruction=None):
    """Saves the text of the rumor, or of the rumor of the notable event when rumor_id is None, and adds that rumor when it
    has none. A rumor takes the game time and the step of its notable event, so a rumor that grew with its count is news
    again. instruction None keeps the stored one. Returns False when the rumor or the notable event is gone."""
    with _connect(write=True) as conn:
        if rumor_id is None:
            row = conn.execute("SELECT id FROM rumor WHERE notable_id = ?", (notable_id,)).fetchone()
            if row is None:
                if not conn.execute("SELECT 1 FROM notable WHERE id = ?", (notable_id,)).fetchone():
                    return False
                rumor_id = conn.execute("INSERT INTO rumor (notable_id, game_time, text) VALUES (?, 0, '')", (notable_id,)).lastrowid
            else:
                rumor_id = row[0]
        row = conn.execute("SELECT r.game_time, r.step, n.game_time, n.deed FROM rumor r LEFT JOIN notable n ON n.id = r.notable_id WHERE r.id = ?", (rumor_id,)).fetchone()
        if row is None:
            return False
        at, step, notable_time, deed = row
        if deed is not None:
            at, step = notable_time, json.loads(deed).get("step")
        conn.execute("UPDATE rumor SET text = ?, instruction = COALESCE(?, instruction), game_time = ?, step = ? WHERE id = ?", (text, instruction, at, step, rumor_id))
        return True


def cull_after(day, hour, minute):
    """Deletes the dialogue, deeds, notable events, rumors, thread members, and memories dated after the given game time,
    and puts each count back to the step of the kills that remain. Returns the count per table of the dialogue, the deeds,
    the notable events, and the rumors."""
    now = day * 1440 + hour * 60 + minute
    with _connect(write=True) as conn:
        touched = {thread_id for (thread_id,) in conn.execute("SELECT id FROM thread WHERE game_time > ?", (now,))}
        culled = {table: conn.execute(f"DELETE FROM {table} WHERE game_time > ?", (now,)).rowcount for table in ("dialogue", "deed", "rumor")}
        notables_before = conn.execute("SELECT COUNT(*) FROM notable").fetchone()[0]
        conn.execute("DELETE FROM notable WHERE kind = 'figure' AND game_time > ?", (now,))
        _refresh_counts(conn, [doer for (doer,) in conn.execute("SELECT DISTINCT json_extract(deed, '$.doer') FROM notable WHERE kind = 'count'")])
        culled["notable"] = notables_before - conn.execute("SELECT COUNT(*) FROM notable").fetchone()[0]
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


FACTION_KEYS = ("name", "aliases", "major", "fields", "description")
_FACTION_COLUMNS = "faction_id, name, aliases, major, fields, description, is_player, origin, updated_at"


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
            "INSERT INTO faction (faction_id, name, aliases, major, fields, description, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (faction_id, values["name"], json.dumps(values["aliases"]), int(values["major"]), json.dumps(values["fields"]), values["description"], _now()),
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
        for key in ("aliases", "fields"):
            if key in values:
                values[key] = json.dumps(values[key])
        if "major" in values:
            values["major"] = int(values["major"])
        values["updated_at"] = _now()
        conn.execute(f"UPDATE faction SET {', '.join(f'{key} = ?' for key in values)} WHERE faction_id = ?", (*values.values(), faction_id))
        saved = conn.execute(f"SELECT {_FACTION_COLUMNS} FROM faction WHERE faction_id = ?", (faction_id,)).fetchone()
    return _faction(saved)


def _faction(row):
    faction_id, name, aliases, major, fields, description, is_player, origin, updated_at = row
    return {
        "faction_id": faction_id,
        "name": name,
        "aliases": json.loads(aliases),
        "major": bool(major),
        "fields": json.loads(fields),
        "description": description,
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


def save_record(kind, key, value, updated_at):
    """Adds the record when updated_at is None, else replaces its value.

    Raises DuplicateRecord if a new record's key is taken, and StaleRecord if the record changed after the caller read
    updated_at or is gone.
    """
    table, keys, column = _RECORDS[kind]
    match = " AND ".join(f"{name} = ?" for name in keys)
    with _connect(write=True) as conn:
        row = conn.execute(f"SELECT updated_at FROM {table} WHERE {match}", key).fetchone()
        if updated_at is None:
            if row:
                raise DuplicateRecord(key)
            conn.execute(f"INSERT INTO {table} ({', '.join(keys)}, {column}, updated_at) VALUES ({', '.join('?' * (len(keys) + 2))})", (*key, json.dumps(value), _now()))
        elif row is None or row[0] != updated_at:
            raise StaleRecord(key)
        else:
            conn.execute(f"UPDATE {table} SET {column} = ?, updated_at = ? WHERE {match}", (json.dumps(value), _now(), *key))


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


def _refresh_counts(conn, doer_ids):
    """Makes the count rows of each doer match its kills. An animal counts by its race entry, so an alias that the player
    adds also joins the earlier kills of the variants. A row takes the game time of the kill that reached its step, so it
    moves to the top of the Deeds list only at a new step."""
    races = _race_entries(conn)
    for doer in doer_ids:
        kills, name = {}, ""
        for name, faction, race, animal, at in conn.execute(
            "SELECT doer_name, faction, race, animal, game_time FROM deed WHERE kind = 'kill' AND figure = 0 AND doer_id = ? ORDER BY game_time, id", (doer,)
        ):
            kills.setdefault(("race", races.get(race.lower(), race)) if animal else ("faction", faction), []).append(at)
        counts = {}
        for (target, value), times in kills.items():
            step = sum(len(times) >= bound for bound in COUNT_STEPS)
            if step:
                counts[(target, value)] = ({"doer": doer, "doer_name": name, target: value, "count": len(times), "step": step}, times[COUNT_STEPS[step - 1] - 1])
        for row_id, deed in conn.execute("SELECT id, deed FROM notable WHERE kind = 'count' AND json_extract(deed, '$.doer') = ?", (doer,)).fetchall():
            deed = json.loads(deed)
            key = ("race", deed["race"]) if "race" in deed else ("faction", deed["faction"])
            if key in counts:
                deed, reached = counts.pop(key)
                conn.execute("UPDATE notable SET deed = ?, game_time = ? WHERE id = ?", (json.dumps(deed), reached, row_id))
            else:
                conn.execute("DELETE FROM notable WHERE id = ?", (row_id,))
        conn.executemany("INSERT INTO notable (kind, game_time, deed) VALUES ('count', ?, ?)", [(reached, json.dumps(deed)) for deed, reached in counts.values()])


def _race_entries(conn):
    """The name of the race entry for each race name and alias in lower case, as the prompts match a race (find_race)."""
    entries = {}
    for (data,) in conn.execute("SELECT data FROM entity WHERE category = 'races' ORDER BY id"):
        entry = json.loads(data)
        for name in [entry.get("name", ""), *entry.get("aliases", [])]:
            entries.setdefault(name.lower(), entry.get("name", ""))
    return entries


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
