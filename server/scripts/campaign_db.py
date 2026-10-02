"""The campaign's NPC profiles, dialogue, events, and rumors, in one SQLite file per campaign folder.

Every write runs in one BEGIN IMMEDIATE transaction, and a profile write merges only the keys that the
caller passes. Two requests that change one NPC during an LLM call therefore keep both changes.
"""

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_NAME = "campaign.db"
SCHEMA_VERSION = 1
MAX_DIALOGUE = 250
MAX_EVENTS = 500
LEGACY_NAMES = ("characters", "event_history.json", "world_events.txt")

# storage_id is NOCASE because Windows file names, the profile key before this database, ignore case
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


def open_campaign(folder, favorites=()):
    """favorites holds the storage IDs of the INI's old Favorites list, which the migration marks."""
    global _db_path
    with _open_lock:
        path = os.path.join(folder, DB_NAME)
        # Set before the migration, so a failed migration makes writes fail instead of reaching the previous campaign
        _db_path = path
        if not os.path.exists(path):
            _migrate(folder, favorites)


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
            _insert_npc(conn, storage_id, fields, _now())
            return
        profile = json.loads(row[1])
        profile.update(fields)
        profile.pop("ConversationHistory", None)
        conn.execute("UPDATE npc SET profile = ?, updated_at = ? WHERE id = ?", (json.dumps(profile), _now(), row[0]))


def append_dialogue(storage_id, lines, profile):
    """Stores profile first only if the NPC is not stored yet."""
    with _connect(write=True) as conn:
        row = conn.execute("SELECT id FROM npc WHERE storage_id = ?", (_key(storage_id),)).fetchone()
        if row:
            npc_id = row[0]
            conn.execute("UPDATE npc SET updated_at = ? WHERE id = ?", (_now(), npc_id))
        else:
            npc_id = _insert_npc(conn, storage_id, profile, _now())
        _append_lines(conn, npc_id, lines)


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
        _add_event(conn, line)


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
    # mode=rw: a missing file must fail, not become an empty database that the next open takes as migrated
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


def _migrate(folder, favorites):
    tmp = os.path.join(folder, DB_NAME + ".tmp")
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp, isolation_level=None)
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN")
        _import_files(conn, folder)
        conn.executemany("UPDATE npc SET favorite = 1 WHERE storage_id = ?", [(_key(sid),) for sid in favorites])
        counts = [conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("npc", "event", "rumor")]
        conn.execute("COMMIT")
    finally:
        conn.close()
    # A crash before this rename leaves no database, so the next open runs the migration again
    os.replace(tmp, os.path.join(folder, DB_NAME))
    logging.info(f"CAMPAIGN DB: Created {DB_NAME} in {folder} with {counts[0]} NPCs, {counts[1]} events, and {counts[2]} rumors")

    legacy = os.path.join(folder, "legacy")
    for name in LEGACY_NAMES:
        src = os.path.join(folder, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(legacy, name)
        if os.path.exists(dst):
            logging.warning(f"CAMPAIGN DB: {dst} already exists, so {src} stays in place")
            continue
        os.makedirs(legacy, exist_ok=True)
        shutil.move(src, dst)


def _import_files(conn, folder):
    chars = os.path.join(folder, "characters")
    if os.path.isdir(chars):
        for name in sorted(os.listdir(chars)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(chars, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                if not isinstance(profile, dict):
                    raise ValueError("the file does not hold a JSON object")
                npc_id = _insert_npc(conn, name[:-len(".json")], profile, _utc(os.path.getmtime(path)))
            except (ValueError, sqlite3.IntegrityError) as e:
                logging.warning(f"CAMPAIGN DB: Skipped {path}: {e}")
                continue
            _append_lines(conn, npc_id, profile.get("ConversationHistory", []))

    hist = os.path.join(folder, "event_history.json")
    if os.path.exists(hist):
        try:
            with open(hist, "r", encoding="utf-8") as f:
                lines = json.load(f)
            for line in lines:
                _add_event(conn, line)
        except ValueError as e:
            logging.warning(f"CAMPAIGN DB: Skipped {hist}: {e}")

    world = os.path.join(folder, "world_events.txt")
    if os.path.exists(world):
        # replace: a player can edit this file in an editor that saves another encoding
        with open(world, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    conn.execute("INSERT INTO rumor (game_time, line) VALUES (?, ?)", (_game_time(line), line))


def _insert_npc(conn, storage_id, profile, updated_at):
    profile = {k: v for k, v in profile.items() if k != "ConversationHistory"}
    return conn.execute("INSERT INTO npc (storage_id, profile, updated_at) VALUES (?, ?, ?)", (_key(storage_id), json.dumps(profile), updated_at)).lastrowid


def _append_lines(conn, npc_id, lines):
    conn.executemany("INSERT INTO dialogue (npc_id, game_time, line) VALUES (?, ?, ?)", [(npc_id, _game_time(line), line) for line in lines])
    conn.execute(
        "DELETE FROM dialogue WHERE npc_id = ? AND id <= (SELECT id FROM dialogue WHERE npc_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
        (npc_id, npc_id, MAX_DIALOGUE),
    )


def _add_event(conn, line):
    if conn.execute("SELECT 1 FROM event WHERE line = ?", (line,)).fetchone():
        return
    conn.execute("INSERT INTO event (game_time, line) VALUES (?, ?)", (_game_time(line), line))
    conn.execute("DELETE FROM event WHERE id <= (SELECT id FROM event ORDER BY id DESC LIMIT 1 OFFSET ?)", (MAX_EVENTS,))


def _key(storage_id):
    """The sanitizing of the profile file names, kept so that old storage IDs and favorites still match."""
    return "".join(c for c in str(storage_id) if c.isalnum() or c in (" ", "_", "-")).strip()


def _game_time(line):
    """Minutes from day 0 in the line's first [Day N, HH:MM] tag, or None."""
    match = _GAME_TIME.search(line)
    if not match:
        return None
    return int(match.group(1)) * 1440 + int(match.group(2) or 0) * 60 + int(match.group(3) or 0)


def _now():
    return _utc(time.time())


def _utc(seconds):
    # Fixed width, so updated_at sorts as text
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds")
