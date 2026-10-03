"""The campaign's NPC profiles, dialogue, canon, events, and rumors, in one SQLite file per campaign folder.

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
SCHEMA_VERSION = 3
MAX_DIALOGUE = 250
MAX_EVENTS = 500

SCHEMA = f"""
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE npc (
  id         INTEGER PRIMARY KEY,
  storage_id TEXT NOT NULL COLLATE NOCASE UNIQUE,
  profile    TEXT NOT NULL,
  favorite   INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE dialogue (
  id        INTEGER PRIMARY KEY,
  npc_id    INTEGER NOT NULL REFERENCES npc(id) ON DELETE CASCADE,
  game_time INTEGER,
  line      TEXT NOT NULL
);
CREATE INDEX dialogue_by_npc ON dialogue (npc_id, id);
CREATE TABLE event (
  id        INTEGER PRIMARY KEY,
  game_time INTEGER,
  line      TEXT NOT NULL
);
CREATE TABLE rumor (
  id        INTEGER PRIMARY KEY,
  game_time INTEGER,
  line      TEXT NOT NULL
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
CREATE TABLE character (
  id         INTEGER PRIMARY KEY,
  game_id    TEXT NOT NULL UNIQUE,
  profile    TEXT NOT NULL,
  origin     TEXT NOT NULL DEFAULT 'campaign',
  updated_at TEXT NOT NULL
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
            "INSERT INTO faction (faction_id, name, aliases, major, fields, description, origin, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'template', ?)",
            [(f["faction_id"], f["name"], json.dumps(f["aliases"]), int(f["major"]), json.dumps(f["fields"]), f["description"], now) for f in seed["factions"]],
        )
        conn.executemany(
            "INSERT INTO character (game_id, profile, origin, updated_at) VALUES (?, ?, 'template', ?)",
            [(c["game_id"], json.dumps(c["profile"]), now) for c in seed["characters"]],
        )
        conn.executemany(
            "INSERT INTO entity (category, ext_id, data, origin, updated_at) VALUES (?, ?, ?, 'template', ?)",
            [(e["category"], e["id"], json.dumps(e["data"]), now) for e in seed["entities"]],
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    os.replace(tmp, os.path.join(folder, DB_NAME))
    logging.info(f"CAMPAIGN: Created {DB_NAME} in {folder} from the template {seed['template']['name']}")


def get_npc(storage_id):
    with _connect() as conn:
        row = conn.execute("SELECT id, profile FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone()
        if not row:
            return None
        profile = json.loads(row[1])
        profile["ConversationHistory"] = [line for (line,) in conn.execute("SELECT line FROM dialogue WHERE npc_id = ? ORDER BY id", (row[0],))]
        return profile


def npc_exists(storage_id):
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone() is not None


def upsert_profile(storage_id, fields):
    """Ignores ConversationHistory, so a caller can pass a whole profile."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone()
        if not row:
            _insert_npc(conn, storage_id, fields)
            return
        profile = json.loads(row[1])
        profile.update(fields)
        conn.execute("UPDATE npc SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(_stored(profile)), _now(), row[0]))


def change_relation(storage_id, delta):
    """Returns the new Relation, clamped to -100..100, or None if the NPC is not stored."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, profile FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone()
        if not row:
            return None
        profile = json.loads(row[1])
        profile["Relation"] = max(-100, min(100, int(profile.get("Relation", 0)) + delta))
        conn.execute("UPDATE npc SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(profile), _now(), row[0]))
        return profile["Relation"]


def append_dialogue(storage_id, lines, profile):
    """Stores profile first only if the NPC is not stored yet."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone()
        if row:
            npc_id = row[0]
            conn.execute("UPDATE npc SET updated_at = ? WHERE id = ?", (_now(), npc_id))
        else:
            npc_id = _insert_npc(conn, storage_id, profile)
        conn.executemany("INSERT INTO dialogue (npc_id, game_time, line) VALUES (?, ?, ?)", [(npc_id, _game_time(line), line) for line in lines])
        conn.execute(
            "DELETE FROM dialogue WHERE npc_id = ? AND id <= (SELECT id FROM dialogue WHERE npc_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (npc_id, npc_id, MAX_DIALOGUE),
        )


def rename_npc(old_id, new_id, name):
    """Returns False, and changes nothing, if old_id is not stored or new_id is already taken."""
    with _connect(write=True) as conn:
        if conn.execute("SELECT 1 FROM npc WHERE storage_id = ?", (_key(new_id),)).fetchone():
            return False
        row = conn.execute("SELECT id, profile FROM npc WHERE storage_id = ?", (_key(old_id),)).fetchone()
        if not row:
            return False
        profile = json.loads(row[1])
        profile["ID"] = new_id
        profile["Name"] = name
        conn.execute("UPDATE npc SET storage_id = ?, profile = ?, updated_at = ? WHERE id = ?", (_key(new_id), json.dumps(profile), _now(), row[0]))
        return True


def list_npcs():
    with _connect() as conn:
        rows = conn.execute("SELECT storage_id, COALESCE(json_extract(profile, '$.Name'), storage_id), favorite, updated_at FROM npc").fetchall()
    return [{"storage_id": sid, "name": name, "favorite": bool(fav), "updated_at": updated} for sid, name, fav, updated in rows]


def toggle_favorite(storage_id):
    """Returns the new state, or None if the NPC is not stored."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id, favorite FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE npc SET favorite = ? WHERE id = ?", (int(not row[1]), row[0]))
        return not row[1]


def add_event(line):
    with _connect(write=True) as conn:
        if conn.execute("SELECT 1 FROM event WHERE line = ?", (line,)).fetchone():
            return
        conn.execute("INSERT INTO event (game_time, line) VALUES (?, ?)", (_game_time(line), line))
        conn.execute("DELETE FROM event WHERE id <= (SELECT id FROM event ORDER BY id DESC LIMIT 1 OFFSET ?)", (MAX_EVENTS,))


def recent_events(n):
    """The newest n events, oldest first."""
    with _connect() as conn:
        rows = conn.execute("SELECT line FROM (SELECT id, line FROM event ORDER BY id DESC LIMIT ?) ORDER BY id", (n,)).fetchall()
    return [line for (line,) in rows]


def add_rumor(line):
    with _connect(write=True) as conn:
        conn.execute("INSERT INTO rumor (game_time, line) VALUES (?, ?)", (_game_time(line), line))


def rumors():
    """Every rumor as (id, line), oldest first."""
    with _connect() as conn:
        return conn.execute("SELECT id, line FROM rumor ORDER BY id").fetchall()


def rumor(rumor_id):
    with _connect() as conn:
        row = conn.execute("SELECT line FROM rumor WHERE id = ?", (rumor_id,)).fetchone()
    return row[0] if row else None


def cull_after(day, hour, minute):
    """Deletes the dialogue, events, and rumors dated after the given game time. Returns the count per table."""
    now = day * 1440 + hour * 60 + minute
    with _connect(write=True) as conn:
        return {table: conn.execute(f"DELETE FROM {table} WHERE game_time > ?", (now,)).rowcount for table in ("dialogue", "event", "rumor")}


def events():
    """Every event as (id, line), oldest first."""
    with _connect() as conn:
        return conn.execute("SELECT id, line FROM event ORDER BY id").fetchall()


def delete_event(event_id):
    with _connect(write=True) as conn:
        return conn.execute("DELETE FROM event WHERE id = ?", (event_id,)).rowcount > 0


def set_rumor(rumor_id, line):
    with _connect(write=True) as conn:
        return conn.execute("UPDATE rumor SET line = ?, game_time = ? WHERE id = ?", (line, _game_time(line), rumor_id)).rowcount > 0


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
_RECORDS = {"character": ("character", ("game_id",), "profile"), "entity": ("entity", ("category", "ext_id"), "data")}


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
        return conn.execute(f"DELETE FROM {table} WHERE {' AND '.join(f'{name} = ?' for name in keys)}", key).rowcount > 0


@contextmanager
def _connect(write=False):
    if _db_path is None:
        raise CampaignUnavailable(_closed_reason)
    # mode=rw: a missing file must fail, not become an empty database that the next open takes as created
    conn = sqlite3.connect(Path(os.path.abspath(_db_path)).as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _insert_npc(conn, storage_id, profile):
    return conn.execute("INSERT INTO npc (storage_id, profile, updated_at) VALUES (?, ?, ?)", (_key(storage_id), json.dumps(_stored(profile)), _now())).lastrowid


def _stored(profile):
    # A stored "_transient" would block /rename and make /ambient regenerate the profile on every call
    return {k: v for k, v in profile.items() if k != "ConversationHistory" and not k.startswith("_")}


def _key(storage_id):
    return "".join(c for c in str(storage_id) if c.isalnum() or c in (" ", "_", "-")).strip()


def _game_time(line):
    """Minutes from day 0 in the line's first [Day N, HH:MM] tag, or None."""
    match = _GAME_TIME.search(line)
    if not match:
        return None
    return int(match.group(1)) * 1440 + int(match.group(2) or 0) * 60 + int(match.group(3) or 0)


def _now():
    # Fixed width, so updated_at sorts as text
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
