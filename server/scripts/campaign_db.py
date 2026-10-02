"""The campaign's NPC profiles, dialogue, events, and rumors, in one SQLite file per campaign folder.

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
SCHEMA_VERSION = 1
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
INSERT INTO meta (key, value) VALUES ('schema_version', '{SCHEMA_VERSION}');
"""

_GAME_TIME = re.compile(r"\[Day (\d+)(?:, (\d+):(\d+))?\]")

_db_path = None
_open_lock = threading.Lock()


def open_campaign(folder):
    global _db_path
    with _open_lock:
        path = os.path.join(folder, DB_NAME)
        # Set before the creation, so a failed creation makes writes fail instead of reaching the previous campaign
        _db_path = path
        if not os.path.exists(path):
            _create(folder)


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


@contextmanager
def _connect(write=False):
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


def _create(folder):
    tmp = os.path.join(folder, DB_NAME + ".tmp")
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp, isolation_level=None)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    # A crash before this rename leaves no database, so the next open creates it again
    os.replace(tmp, os.path.join(folder, DB_NAME))
    logging.info(f"CAMPAIGN: Created {DB_NAME} in {folder}")


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
