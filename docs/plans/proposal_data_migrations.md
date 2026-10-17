# Proposal: Data Migrations

## 1. Summary

SSR is in production, so players keep their data across updates. The release zip leaves out the player's data ([development.md](../info/development.md#release)), so the new server reads each file that an earlier release wrote. Today a change to the format of that data breaks it:

| Data | Path | Version stamp | What an earlier version gets today |
|---|---|---|---|
| Campaign database | `server/data/campaigns/<name>/campaign.db` | `meta.schema_version`, 22 (`server/store/campaign_db.py:18`) | Refused. The player must start a new campaign (`server/store/campaign_db.py:152`). |
| User templates | `server/data/user_templates/<name>/`, and the files of Export | `manifest.format_version`, 1 (`server/store/world_template.py:17`) | Refused (`server/store/world_template.py:92`). |
| LLM configuration | `server/config/llm_config.json` | None | A missing task gets the default route (`server/chat/llm.py:80`). Any other change breaks the file. |
| INI | `SentientSands_Config.ini` in the mod folder | None | A missing key gets its default (`load_settings` in `server/core/settings.py:88`), so a renamed key loses the player's value. |

In this plan, each of the four upgrades data of an earlier version, one version at a time, before the server uses it. The current version of each is the first version that can be upgraded.

The prompt overrides in `server/config/prompts/` are not a part of this plan. `base_hashes.json` already marks an override whose shipped default changed (`server/chat/prompts.py`).

[Sections 2 to 8](#2-shared-rules) hold the decided design.

## 2. Shared rules

Each of the four keeps its own `MIGRATIONS` in its own module. `MIGRATIONS` maps a version to the step that upgrades the data from that version to the next one. Each `MIGRATIONS` is empty in the release that adds it, because no format change is pending.

```python
MIGRATIONS = {
    1: _to_2,
}
```

| Data of | Result |
|---|---|
| The current version | The server uses it as today. |
| An earlier version, with a step for each version up to the current one | The server writes a backup, runs the steps in order, writes the current version, and saves the data. |
| An earlier version without those steps | The section of each one says what happens. |
| A later version | The section of each one says what happens. The database and the templates refuse it, so a player who goes back to an earlier release keeps the data for the next update. |

- A change after which the current code cannot use the data of the previous version as it is, such as a renamed key, a new required field, or a changed unit, bumps the version and adds a step in the same commit.
- A step that a release shipped never changes, and a fix is a new step. A player who upgraded with the old step has data that a changed step never reaches.
- A step uses only its own code, never the other functions of its module. Those functions follow the current format, so a later format change breaks an old step that calls them.
- Each upgrade writes one backup, which the next upgrade overwrites. A failed backup stops the upgrade.
- When a step fails, the data keeps its earlier version, and the server logs the traceback.
- Each upgrade writes a log line, for example `CAMPAIGN: Upgraded campaign.db in <folder> from version 22 to 23. The backup is campaign.db.bak.`
- Rejected: one migration module for all four. The four hold different objects (an SQLite connection, a template object, a JSON object, and a `ConfigParser`), so a shared module shares only a loop of two lines.

## 3. Campaign database

`open_campaign` reads `schema_version` with `read_meta` (`server/store/campaign_db.py:174`) and upgrades the database before it opens it. Version 22 is the first version that can be upgraded.

| Database | Result |
|---|---|
| No `campaign.db` | `create` builds it from the seed, as today (`server/store/campaign_db.py:188`). |
| An earlier version without the steps, or no readable version | Refused with today's text: "The campaign X was made by an earlier version of SSR, which this version cannot open. Start a new campaign." |
| A later version | Refused with "The campaign X was made by a later version of SSR. Update SSR to open it." |
| A failed step | Refused with "SSR could not upgrade the campaign X: <error>. The backup is campaign.db.bak." |

- An upgrade runs only when the player opens the campaign. Rejected: an upgrade of each campaign at server start, because it slows the start for campaigns that the player never opens again.
- `open_campaign` sets `_db_path` to `None` before the upgrade and to the path after the commit. A background thread, such as the memory loop, then gets `CampaignUnavailable` and skips its work (`server/chat/memory.py:77`), so no thread writes to a half-upgraded database.
- The upgrade runs under `_open_lock`, as the creation does, so two opens of one campaign cannot upgrade it twice.

### Upgrade

`_upgrade(path, version)` does these steps:

1. It opens a connection with `isolation_level=None`. `foreign_keys` stays OFF, its default, because a table rebuild drops a table that other tables reference.
2. It runs `BEGIN IMMEDIATE`.
3. It calls each step from `version` to `SCHEMA_VERSION - 1` in order, with the connection.
4. It sets `schema_version` to `SCHEMA_VERSION`.
5. It runs `PRAGMA foreign_key_check` and fails when the check gives a row.
6. It runs `COMMIT`.

SQLite rolls back schema changes with the transaction. When a step fails, `_upgrade` runs `ROLLBACK`, so the database keeps its earlier version.

Each step of the database follows these rules too:

- The stored format includes the JSON in the columns, such as `character.profile` and `entity.data`, because a renamed JSON key breaks an old campaign without a change to the SQL.
- A step uses `conn.execute`, never `conn.executescript`. `executescript` commits the open transaction first, so a later failure cannot roll back the earlier statements. `create` can use it (`server/store/campaign_db.py:188`), because it runs before its own `BEGIN`, on a new file.
- `SCHEMA` puts a new column at the end of its table. `ALTER TABLE ... ADD COLUMN` adds a column at the end, so a new campaign and an upgraded campaign then have the same column order, which the test of [section 7](#7-tests) compares.
- A change that `ALTER TABLE` cannot make rebuilds the table with the [12-step procedure of SQLite](https://www.sqlite.org/lang_altertable.html#otheralter): create the new table, copy the rows, drop the old table, rename the new table, and create its indexes again.
- A rebuild of `thread` or `journal` copies the `sqlite_sequence` value of the old table to the new table. The copy of the rows sets the sequence to the largest ID that is left, so a new row then takes the ID of a deleted row, which both tables forbid (`server/store/campaign_db.py:50`, `server/store/campaign_db.py:91`).

### Backup

Before the upgrade, `open_campaign` copies `campaign.db` to `campaign.db.bak` in the campaign folder with the SQLite backup API (`sqlite3.Connection.backup`).

- The database uses the rollback journal ([architecture.md](../info/architecture.md#campaign-storage)). A crash during a write leaves a hot journal, `campaign.db-journal`, and a file copy of `campaign.db` without that journal is a corrupt database. The backup API opens the database, which rolls back the hot journal before the copy.
- To go back to the earlier version, the player replaces `campaign.db` with the backup and installs the earlier release.

## 4. User templates

A step takes and gives the object of `export_template` (`server/store/world_template.py:253`), so one step upgrades both a template folder and an imported file. Version 1 is the first version that can be upgraded.

- At server start, before `init_server_state` (`server/main.py:53`), the server upgrades each user template of an earlier version. Templates are few and small, so the upgrade at start costs little, and no reader of a template meets an earlier version.
- The upgrade of a folder:
  1. It writes the old template as an export file, `<name>.bak.json`, in `server/data/user_templates/`. The template list skips the file, because `_names` lists only folders (`server/store/world_template.py:384`). Import reads the file back, so the player can restore the template from the web app.
  2. It runs the steps and sets `format_version`.
  3. It validates the result with `validate`, so a step that gives an invalid template fails.
  4. It writes the new folder through a staging folder, as `_write_new_template` does (`server/store/world_template.py:308`), and then deletes the old folder and renames the staging folder. A crash between the delete and the rename leaves no template of that name, and Import of the backup restores it.
- `import_template` (`server/store/world_template.py:259`) runs the steps on the object before it validates it, so a file that a player exported from an earlier release imports. An import writes no backup, because the file stays where the player saved it.
- A template of a later version, or of an earlier version that the steps could not upgrade, is refused with today's error (`server/store/world_template.py:92`).
- The shipped templates in `server/data/templates/` never upgrade, because an update replaces them.

## 5. LLM configuration

- The file gets a top-level key, `format_version`. A file without the key is version 1, the format of the current release.
- `llm_config.save` (`server/chat/llm_config.py:211`) sets `format_version` on each save. The save route of the Models page builds the configuration from its four parts only (`server/dashboard/routes.py:474`), so the version of the client would be lost.
- `load_llm_config` (`server/chat/llm.py:66`) runs the steps after `llm_config.load` and before it adds the default routes. A step takes and gives the JSON object.
- The backup is `llm_config.json.bak`. It holds the API keys, so it stays in `server/config/`, which the release zip leaves out.
- A file that does not parse is not upgraded. The server uses the default configuration and does not save over the file, as today (`server/chat/llm.py:74`).
- A file of a later version, or a failed step, gets the same treatment as a file that does not parse.

## 6. INI

- `[Settings]` gets a key, `FormatVersion`. An INI without the key is version 1, the format of the current release.
- `_save_settings_raw` (`server/core/settings.py:39`) writes `FormatVersion` on each write.
- `init_server_state` (`server/store/campaigns.py:29`) runs the steps before its first `load_settings`. A step takes the `ConfigParser` and changes it.
- The backup is `SentientSands_Config.ini.bak`. The release ships no INI (`scripts/package_release.py:42`), so an update never replaces the INI or the backup.
- A failed step leaves the INI as it was. The server then reads it as today, so a renamed key gets its default.
- An INI of a later version is read as it is, without steps. A refusal would make the server run on the defaults, and the next write of `_save_settings_raw` would replace each setting of the player.
- An earlier release then writes its own `FormatVersion`, so after a return to the later release the steps run again on an upgraded INI. A step of the INI therefore must not change an INI that it already upgraded: a rename copies the old key only when the new key is missing, and then deletes the old key. The earlier release writes the old key with its default, so a copy over an existing new key would replace the value of the player. A changed unit gets a new key name instead of a new value under the old name, so the same rule covers it.
- The plugin reads the INI before it starts the server (`LoadPluginConfig` in `plugin/core/Utils.cpp:373`). At the first start after an update, the plugin therefore reads the INI before its upgrade. The server sends the plugin values after its start (`push_settings_to_plugin`, `server/main.py:64`), but a key that the plugin only reads, such as `OpenWebPanelOnStart`, has its default for that one start.

## 7. Tests

| Data | Test file | Checks |
|---|---|---|
| Campaign database | `server/tests/test_campaign_migrations.py` | The upgrade of a database from `SCHEMA_V22`, a frozen copy of the version 22 `SCHEMA` text, with one row in each table, equals a database that `create` builds: the same tables and indexes, and for each table the same `PRAGMA table_info`, `index_list`, and `foreign_key_list`. Each row is still there. A failed step leaves version 22, the rows, and a backup that opens. A later version is refused with "Update SSR". |
| User templates | `server/tests/test_world_template.py` | The upgrade of a frozen version 1 template folder passes `validate`, and `<name>.bak.json` imports. The import of a frozen version 1 export file passes. A failed step leaves the folder as it was. |
| LLM configuration | `server/tests/test_llm_config.py` | The upgrade of a frozen version 1 file passes `validate`. A save from the Models page keeps `format_version`. A later version gets the default configuration, and the file does not change. |
| INI | A new `server/tests/test_settings.py` | The upgrade of a frozen version 1 INI keeps each value of the player under its current key. An INI that an earlier release rewrote after an upgrade keeps the values under the current keys. |

- For each of the four, a test checks that the keys of `MIGRATIONS` equal the range from the first version to the current version, so a version bump without a step fails.
- The frozen samples never change, because each upgrade starts from the first version.
- The comparison of the database does not use the SQL text in `sqlite_master`, because SQLite stores different text for an `ALTER TABLE` than for a `CREATE TABLE`.
- The test of the database fails when `SCHEMA` changes without a step that makes the same change, also while `MIGRATIONS` is empty.
- Each step gets its own test of the data that it changes, such as a renamed profile key.
- The test of an earlier campaign version (`server/tests/test_campaign_db.py:81`) stays, because version 1 has no step.

## 8. Rejected

| Alternative | Reason |
|---|---|
| Alembic | It needs SQLAlchemy, and the server uses `sqlite3`. It adds a package to the embedded runtime in place of a loop of about 30 lines. |
| `PRAGMA user_version` | Version 22 databases already hold `meta.schema_version`, so a switch costs a step and gains nothing. |
| A backup for each upgrade | No dialogue line is trimmed ([architecture.md](../info/architecture.md#campaign-storage)), so each backup of a campaign is as large as the campaign. |
