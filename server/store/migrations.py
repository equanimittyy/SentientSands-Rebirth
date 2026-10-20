"""Brings the campaign database of an earlier release up to the current schema.

Each schema that a release shipped has one step to the next schema, and a campaign runs every step from its own schema
up, in one transaction. The SQL of a step stays as its release needed it, because a later schema change gets a step of
its own. A copy of the database comes first, so a player who goes back to the old release keeps the campaign.
"""

import logging
import os
import sqlite3
from typing import Callable, NamedTuple

from core.version import MOD_VERSION


class Step(NamedTuple):
    newest_release: int
    run: Callable


def _from_22(conn):
    conn.execute("CREATE TABLE captive (npc_id TEXT PRIMARY KEY, game_time INTEGER NOT NULL)")
    # SSR 1 and 2 seeded a leader name that neither the game nor his character record uses, so his death never reached
    # the faction.
    conn.execute("UPDATE faction SET fields = json_set(fields, '$.leader', 'Holy Lord Phoenix') "
                 "WHERE faction_id = '1083-gamedata.base' AND json_extract(fields, '$.leader') = 'Holy Lord Phoenix LXII'")


STEPS = {
    22: Step(newest_release=2, run=_from_22),
}


def backup_name(schema):
    return f"campaign_ssr{STEPS[schema].newest_release}_backup.db"


def migrate(path, schema):
    """Copies the database, then runs the steps from schema up. A failed step leaves the transaction open, so the close
    rolls back the whole migration and the database keeps its schema."""
    backup = os.path.join(os.path.dirname(path), backup_name(schema))
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        copy = sqlite3.connect(backup)
        try:
            conn.backup(copy)
        finally:
            copy.close()
        conn.execute("BEGIN")
        reached = schema
        while reached in STEPS:
            STEPS[reached].run(conn)
            reached += 1
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(reached),))
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('ssr_version', ?)", (str(MOD_VERSION),))
        conn.execute("COMMIT")
    finally:
        conn.close()
    logging.info(f"CAMPAIGN: Copied {path} to {os.path.basename(backup)}, then migrated it from schema {schema} to {reached}.")
