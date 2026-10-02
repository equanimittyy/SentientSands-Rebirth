# Proposal: SQLite Campaign Storage

Status: Draft for review

## 1. Summary

The server keeps the NPC profiles, dialogue, event history, and rumors of each campaign in loose JSON and text files. This proposal moves that state into one SQLite database per campaign, `server/campaigns/<name>/campaign.db`, behind a new module, `server/scripts/campaign_db.py`.

The plugin does not change. It reaches campaign data only through the server's HTTP routes (`plugin/ui/CampaignsWindow.cpp`, `plugin/ui/EventsWindow.cpp`), and the routes keep their request and response shapes.

[proposal_data_layers.md](proposal_data_layers.md) adds world templates and their knowledge tables to this database. [proposal_web_app.md](proposal_web_app.md) adds browser editors for it.

## 2. Problems with the file storage

All line references are in `server/scripts/kenshi_llm_server.py`.

| Problem | Cause | Effect |
|---|---|---|
| Lost updates | `/chat` loads each listener's profile, waits up to 55 s for the LLM, appends the history lines, and writes the whole file (`:2679-2734`). `/ambient` also writes the whole file after it appends (`:2004-2024`). Flask runs with `threaded=True`, and no lock covers the read-modify-write. | A change that another request makes to the same NPC during the wait is overwritten. |
| Damaged profiles | `save_character_data` opens the file with mode `"w"`, which empties it before the write (`:1747`). | A crash during a write leaves a partial file. `get_character_data` then reads the profile as missing and generates a new one over it (`:1571-1577`). |
| Slow listing | `/characters` opens and parses every profile file on each request (`:3521-3531`). | The NPC list becomes slower as the campaign grows. |
| Two event stores | The event history is in `event_history.json` and in `logs/global_events.log`. The start-up code merges every log line back into the history (`_load_event_history_from_log`, `:959`). | The merge adds looting events, which `record_event_to_history` keeps out of the history on purpose (`:2800`). |

## 3. Goals and non-goals

### Goals

1. Concurrent requests do not lose dialogue lines or profile changes.
2. A crash during a write does not damage stored data.
3. Each existing campaign migrates on its first load, without data loss.
4. The routes keep their behavior: the same prompts, lists, and history output.

### Non-goals

- Knowledge entities, world templates, and retrieval. These are in the data layers proposal.
- The player profile and the per-campaign prompt overrides. `load_prompt_component` reads any prompt file from the campaign folder first (`:999`), so these stay text files that a player can edit.
- The `logs/` folder. The visual debugger reads `global_events.log` directly (`visual_debugger.py:415`).
- `sentient_sands_registry/`. The server writes it (`populate_initial_registry`, `:1183`) but never reads it.
- Name collisions from the file-name sanitizing, for example `Beep` and `Beep!` share one profile. Storage IDs keep today's sanitizing, so that the migration and the favorites stay valid.

## 4. Layout

```
server/campaigns/<name>/
  campaign.db                      new: NPCs, dialogue, events, rumors
  character_bio.txt                unchanged
  player_faction_description.txt   unchanged
  logs/                            unchanged
  legacy/                          the source files, after the migration
```

The campaign stays a folder, so the campaign list (`:3080`), the prompt overrides, and the logs do not change.

## 5. Schema

```sql
PRAGMA foreign_keys = ON;            -- set on each connection

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL                -- schema_version
);

CREATE TABLE npc (
  id         INTEGER PRIMARY KEY,
  storage_id TEXT NOT NULL UNIQUE,   -- today's sanitized file name
  profile    TEXT NOT NULL,          -- JSON object without ConversationHistory
  favorite   INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL           -- UTC, ISO 8601
);

CREATE TABLE dialogue (
  id        INTEGER PRIMARY KEY,
  npc_id    INTEGER NOT NULL REFERENCES npc(id) ON DELETE CASCADE,
  game_time INTEGER,                 -- minutes from day 0; NULL if the line has no time prefix
  line      TEXT NOT NULL            -- verbatim, time prefix included
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
  line      TEXT NOT NULL            -- verbatim world_events.txt line
);
```

- The profile is one JSON column, because the code treats a profile as a loose dict and backfills missing keys (`:1580-1588`). A column for each key would change every caller for no gain.
- The lines stay verbatim, so the prompts and the history window show the same text. `game_time` lets cull delete rows with one comparison, instead of parsing each line with `is_future_timestamp` (`:647`).
- `npc.id` is an integer key, so a rename changes one column and the dialogue rows stay attached.
- `dialogue` keeps the newest 250 rows for each NPC, the same cap as today (`:1743`, `:2726`).
- `event` keeps the newest 500 rows, the same cap as `EVENT_HISTORY` (`:2808`). An insert skips a line that the table already holds, as today (`:2803`).

## 6. Module

`server/scripts/campaign_db.py` imports only the standard library, so its tests run in the dev container ([development.md](../info/development.md#tests)).

| Function | Replaces |
|---|---|
| `open_campaign(folder)` | `load_campaign_config` (`:454`). It runs the migration if the folder has no `campaign.db`. |
| `get_npc(storage_id)` | The reads of `characters/<id>.json`. It returns the same dict, with `ConversationHistory` built from `dialogue`. |
| `npc_exists(storage_id)` | The `os.path.exists` checks in `/chat` (`:2246`, `:2304`) and `/regenerate_profile` (`:3317`). |
| `upsert_profile(storage_id, fields)` | `save_character_data`. It inserts the profile, or merges `fields` into the stored profile. It never writes dialogue. |
| `append_dialogue(storage_id, lines, profile)` | Appending to `ConversationHistory` and saving the whole file. It inserts `profile` first if the NPC is not stored yet. |
| `rename_npc(old_id, new_id, name)` | The file move in `/rename` (`:1826-1844`). |
| `list_npcs()` | The directory scans in `/characters` and `get_used_names` (`:575`). |
| `set_favorite(storage_id, on)` | The `Favorites` list in the INI (`/favorite`, `:3576`). |
| `add_event(line)`, `recent_events(n)` | `EVENT_HISTORY`, `event_history.json`, and the start-up log merge. |
| `add_rumor(line)`, `rumors()`, `rumor(id)` | The reads and appends of `world_events.txt`. |
| `cull_after(game_time)` | The three loops in `/campaigns/cull` (`:3250-3292`). |

Each write runs in one `BEGIN IMMEDIATE` transaction. Two merges into the same profile therefore run one after the other, and a merge does not read a value that another write is about to change.

A caller that changes some keys passes only those keys to `upsert_profile`. For example, `/regenerate_profile` passes `Personality`, `Backstory`, and `SpeechQuirks`. A profile write then cannot undo a change to other keys that a different request made during an LLM call.

## 7. Connections

- Each operation opens a short connection, sets `foreign_keys` and a 5 s busy timeout, and closes the connection. Thread-local connections were rejected, because each campaign switch would have to reset them. Opening an SQLite file costs little compared with one LLM call.
- The database uses the default rollback journal, not WAL. Writes are small and infrequent, so WAL's reads during a write give no gain. Without WAL, the campaign has no `-wal` and `-shm` files, and a player can copy the campaign folder while the server is idle.
- `switch_campaign` changes only the active folder path. No connection stays open across a switch.

## 8. Migration

`open_campaign` migrates a campaign folder that has no `campaign.db`:

1. Build the database in `campaign.db.tmp`.
2. Import each `characters/*.json` file. The profile without `ConversationHistory` goes into `npc`, and each history line goes into `dialogue`. The storage ID is the file name without `.json`. An NPC whose storage ID is in the INI's `Favorites` list gets `favorite = 1`.
3. Import `event_history.json` into `event`. Import each line of `world_events.txt` that is not blank and not a `#` comment into `rumor`.
4. Commit, then rename `campaign.db.tmp` to `campaign.db`. A crash before the rename leaves no database, so the next start runs the migration again.
5. Move `characters/`, `event_history.json`, and `world_events.txt` into `legacy/`. The server does not read them again, and a player can recover them by hand.

- The migration logs and skips a file that does not parse, and moves it into `legacy/` with the others. Today the server treats such a file as missing and generates a new profile over it.
- `game_time` comes from the `[Day N, HH:MM]` prefix, with the pattern of `is_future_timestamp`.
- The migration runs after `migrate_to_campaigns` (`:397`), which moves the files of pre-campaign installs into `campaigns/Default/`.
- The server stops writing `Favorites` to the INI. The old value stays in the file, so a campaign that migrates later still finds its favorites.
- `ensure_campaign_seeded` (`:376`) stops creating `characters/` and `world_events.txt`, because a new campaign starts with an empty `campaign.db`.

## 9. Route contracts

- `/events` returns an `id` for each rumor. The plugin sends it back to `/events/content` as `day` and does not read it (`plugin/ui/EventsWindow.cpp:104-114`). Today the id is a line number in `world_events.txt`. After the change, it is `rumor.id`.
- `/characters` with sort `latest` orders by `npc.updated_at` instead of the file modification time.
- `/history` still shows at most 250 lines.
- `/favorite` sets `npc.favorite`, and `/characters` returns the favorites of the active campaign. Today one favorites list is shared by all campaigns.
- The prompt keeps the same rumor and event blocks (`:1088-1110`, `:2845-2858`). The filters that today run over file lines run over the rows.

## 10. Tests

`server/tests/test_campaign_db.py` uses only the standard library:

- The migration of a fixture campaign folder stores the same profiles, dialogue, events, and rumors as the source files, and moves the source files into `legacy/`.
- A migration that stops before the rename runs again on the next open.
- Two threads append to one NPC at the same time, and the database stores the lines of both.
- `upsert_profile` with one key keeps the other keys.
- `dialogue` keeps the newest 250 lines for each NPC, and `event` keeps the newest 500.
- `rename_npc` keeps the dialogue and the favorite mark.
- Each storage ID in the INI's `Favorites` list becomes `favorite = 1` in each campaign that holds it.
- `cull_after` deletes only later rows, from all three tables.

The same change updates the "Server state" table and the `server/scripts/` row in [architecture.md](../info/architecture.md#server-state).

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A player cannot edit an NPC profile in a text editor | A common fix for a bad profile is no longer available | The NPCs page of the web app; the files in `legacy/` stay readable |
| A defect in the migration | Lost dialogue or profiles | Build in a temporary file; keep the source files in `legacy/`; test on a copy of a real campaign |
| A request that is in progress during a campaign switch | A write goes to the new campaign | No change from today, where `CHARACTERS_DIR` changes during the request in the same way |

## 12. Open questions

1. Before the web app's NPCs page exists, does a player need another way to edit a profile by hand, for example an export to JSON and an import back?
