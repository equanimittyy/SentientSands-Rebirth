# Proposal: SQLite Knowledge Store for SentientSands-Rebirth (Kayak-Compatible)

Status: Draft for review
Target repo: `SentientSands-Rebirth` (fork of `harvicusdev-glitch/SentientSands`)

---

## 1. Summary

SentientSands-Rebirth currently stores NPC data as flat JSON and text files and injects one fixed block of world lore into every prompt. Kayak (the continuation of SentientSands by Pineaxe and Harvicus) adds a text-based knowledge layer with keyword retrieval and link expansion, but it keeps everything in loose files and rebuilds an in-memory index at runtime.

This proposal is to re-create Kayak's knowledge system on top of SQLite:

- Import Kayak's starter data (the `KayakDB/Template`) into a SQLite database.
- Re-implement Kayak's retrieval (keyword match, then layered link expansion) with SQLite FTS5 and recursive queries.
- Store per-campaign state (NPC profiles, dialogue history, stats, world events) in one database file per campaign.
- Integrate the result as an in-process Python module in Rebirth's existing Flask server.

The C++ plugin (`SentientSands.dll`) is not expected to change. All work is on the Python server side.

[proposal_web_app.md](proposal_web_app.md) adds a browser editor for this store.

## 2. Background and findings

These findings come from reading the repositories directly. Items I did not verify are listed in section 11.

### 2.1 Current state of Rebirth

- The fork is currently byte-identical to the original `harvicusdev-glitch/SentientSands` repo (no differences in the Python server or any C++ source).
- Server dependencies are only `flask` and `requests`.
- Storage is flat files:
  - `campaigns/<name>/characters/<id>.json`, one file per NPC
  - `campaigns/<name>/world_events.txt` and `event_history.json`
  - `campaigns/<name>/sentient_sands_registry/`
  - global config as JSON (`providers.json`, `models.json`, `names.json`, `generic_names.json`, `titles.json`, `localization.json`)
- Lore is a single `templates/world_lore.txt` (about 4.5 KB) that goes into every prompt. There is no retrieval.
- The server is one file of roughly 4,300 lines (`kenshi_llm_server.py`).
- The repo has committed `__pycache__` `.pyc` files, which should be removed and git-ignored.

### 2.2 Kayak's design

Kayak stores knowledge as a folder tree (`KayakDB`):

- One folder per entity containing `entity.txt`, `who_knows_me.txt`, `define_children.txt`, and runtime files such as `dialogue.txt`, `stats.txt`, `notes.txt`.
- The template contains 405 entities: 29 factions, 166 items, 122 locations, 7 races, 64 unique NPCs, 17 world lore entries.
- Entity fields use a `key = value` format. A leading `$` on a field name marks prose, which is never used for link expansion.
- Retrieval: Layer 0 matches keywords from the player message against the index. Layers 1 and above open each matched entity and try to match its field values against other entities' names.
- Retrieval is bounded by `max_keywords`, `max_layers`, `max_matches_per_layer`, `max_files` and `timeout_ms`. Defaults in `core_config.txt` are 3, 1, 3, 4 and 500.
- Per-NPC knowledge control uses `who_knows_me.txt` (access rules) and `define_children.txt` (weighted links).
- Campaigns are isolated copies of the template, with their own NPCs, dialogue, logs and prompt files.
- It runs as a separate local server (port 5001) next to the SentientSands server (port 5000).
- Neither Kayak nor SentientSands uses a database engine. A search for `sqlite3`, SQLAlchemy, chromadb, faiss and embedding libraries found nothing.

### 2.3 Why SQLite

- Retrieval over a few hundred entities is a good fit for FTS5 plus a precomputed link table, which removes runtime scanning of field values.
- One `.db` file per campaign makes backup, copying and sharing trivial.
- Integrity (foreign keys, transactions) replaces hand-managed file consistency, for example the reindex requirements Kayak documents for `entity.txt` changes.
- SQLite ships with Python, so there is no new dependency.

## 3. Goals and non-goals

### Goals

1. Lossless import of Kayak's `KayakDB` folder format into SQLite, repeatable when upstream changes.
2. Retrieval behavior that matches Kayak's for the same inputs and limits, verified by tests.
3. Per-campaign databases with isolation equivalent to Kayak's.
4. A clean separation between imported upstream data and local modifications.
5. Export back to the `KayakDB` folder format, so content packs and hand editing still work.
6. Correct attribution to Kayak's authors.

### Non-goals (for the first release)

- Re-implementing Kayak's prompt token system (`token_resolver.py`) and economy support.
- Vector search or embeddings.
- Changes to the C++ plugin.
- Compatibility with Kayak's HTTP API on port 5001 (see open questions).

## 4. Licence and attribution

- Kayak and SentientSands are GPLv3. Rebirth is also GPLv3, so combining them is compatible.
- Kayak adds an attribution condition under GPLv3 section 7(b) (`Kayak/ADDITIONAL_TERMS.md`). It applies when Kayak material, or a work derived from it, is conveyed to others. It does not apply to private use or to implementations that do not copy or derive from Kayak material.
- Importing Kayak's template data is copying, so for any distribution this project must:
  - preserve `ADDITIONAL_TERMS.md`
  - display "SentientSands Kayak by Harvicus and Pineaxe." in the README or credits
  - list the official project links (Nexus Mods, Steam Workshop, Kayak source repo, Discord) next to it
- Some lore text paraphrases the Kenshi wiki, and the underlying game content belongs to Lo-Fi Games. The wiki's licence was not checked. This must be reviewed before distribution.
- This document is not legal advice.

## 5. Architecture

```
Kenshi (C++ plugin, unchanged)
        |
        v
Flask server (Rebirth, port 5000)
        |
        |  in-process calls
        v
sentient_db/  (new Python package)
  - schema.py        schema creation and migrations
  - importer.py      KayakDB folders -> SQLite (lossless)
  - patches.py       local overrides applied after import
  - retriever.py     FTS5 + recursive link expansion
  - access.py        who_knows_me rule evaluation
  - exporter.py      SQLite -> KayakDB folders
  - campaigns.py     create/switch/copy campaign databases

data/
  template.db        imported upstream data plus local patches
  campaigns/<name>.db   one file per campaign
```

Running in-process avoids a second server and the extra port that Kayak uses.

## 6. Data model

Illustrative schema. Final column names will follow the importer's needs.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL            -- schema_version, source_version, import_hash
);

CREATE TABLE entity (
  id            INTEGER PRIMARY KEY,
  category      TEXT NOT NULL,   -- factions, items, locations, races, unique_npcs, ...
  subpath       TEXT,            -- e.g. locations/cities
  name          TEXT NOT NULL,   -- Kayak folder name
  ext_id        TEXT,            -- "Id" header
  persistent_id TEXT,            -- stable across saves
  runtime_id    TEXT,            -- session scoped
  weight        REAL NOT NULL DEFAULT 1,
  origin        TEXT NOT NULL DEFAULT 'template',  -- template | patch | campaign
  UNIQUE (category, name)
);

CREATE TABLE field (
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  key        TEXT NOT NULL,      -- stored without the leading $
  seq        INTEGER NOT NULL DEFAULT 0,
  value      TEXT NOT NULL,
  is_prose   INTEGER NOT NULL DEFAULT 0,   -- 1 if the source key started with $
  expandable INTEGER NOT NULL DEFAULT 1,   -- 0 for non_expand_fields
  PRIMARY KEY (entity_id, key, seq)
);

CREATE TABLE alias (
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  alias      TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  PRIMARY KEY (entity_id, alias_norm)
);

-- Precomputed at import: field value matches another entity's name or alias.
CREATE TABLE link (
  src_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  dst_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  via_key TEXT NOT NULL,
  PRIMARY KEY (src_id, dst_id, via_key)
);

CREATE TABLE knows (             -- who_knows_me.txt
  entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  rule_raw  TEXT NOT NULL        -- raw [RULE] block, parsed by access.py
);

CREATE TABLE child (             -- define_children.txt
  parent_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  child_name TEXT NOT NULL,
  child_id   INTEGER REFERENCES entity(id) ON DELETE SET NULL,
  weight     REAL NOT NULL
);

CREATE TABLE dialogue (          -- replaces dialogue.txt
  id        INTEGER PRIMARY KEY,
  npc_id    INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  ts        TEXT NOT NULL,
  speaker   TEXT NOT NULL,
  line      TEXT NOT NULL,
  archived  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE stats (             -- replaces stats.txt
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  key        TEXT NOT NULL,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (entity_id, key)
);

CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- core_config.txt

CREATE TABLE patch (             -- local overrides, see section 7
  id         INTEGER PRIMARY KEY,
  op         TEXT NOT NULL,      -- set_field | add_entity | remove_entity | ...
  target     TEXT NOT NULL,
  payload    TEXT NOT NULL,      -- JSON
  applied_at TEXT
);

CREATE VIRTUAL TABLE entity_fts USING fts5(
  name, aliases, body,
  tokenize = 'porter unicode61'
);                               -- rowid = entity.id
```

Later phases add a `prompt_part` table for the mandatory prompt files (Chat, Biography, Loremaster, Speak) and tables for economy data.

## 7. Import design

The import is split in two so upstream updates and local edits do not collide.

### 7.1 Step 1: lossless import

The importer reads Kayak files without altering their content and writes them to SQLite. It must preserve Kayak's conventions, because the retriever depends on them:

| Convention | Handling |
|---|---|
| `$` prefix on a field name | `is_prose = 1`, never used for expansion |
| `non_expand_fields` in `core_config.txt` (id, persistent_id, runtime_id, weight, display_name, aliases, average_price, base_price_cats, price_modifier) | `expandable = 0` |
| `IGN_` prefixed files and folders | skipped |
| `ph_` placeholder prompt files | skipped |
| `[RULE]` blocks in `who_knows_me.txt` | stored raw, parsed by a real parser |
| `W = <weight> <name>` lines in `define_children.txt` | parsed into `child` |
| Comment prefixes `#`, `;`, `//` | ignored |
| `persistent_id` / `runtime_id` | stored in their own columns |

The import records a hash of the source tree in `meta`, so it is deterministic and re-runnable.

Source selection matters. The template I inspected came from a Russian fork and contains Russian `display_name` values. The import source should be the official English Kayak release.

### 7.2 Step 2: local patch layer

Translations, lore fixes, new entities and removals go in the `patch` table (or a patch file in JSON) and are applied after import. This lets the importer be re-run against a newer Kayak release without losing local changes. Conflicts (a patch targeting a field that upstream removed) are reported instead of silently dropped.

## 8. Retrieval design

The retriever replaces Kayak's `indexer.py` and `retriever.py` logic:

1. Extract keywords from the player message using Kayak's stop-word approach, limited by `max_keywords`.
2. Layer 0: FTS5 match against name, aliases and non-prose fields.
3. Layers 1 to N: follow the precomputed `link` table, up to `max_layers`.
4. Rank by layer, then entity weight, then FTS rank. Apply `max_matches_per_layer` and `max_files`.
5. Apply access rules from `knows` for the speaking NPC.
6. Honor `timeout_ms` as a hard ceiling.

Illustrative query for steps 2 and 3:

```sql
WITH RECURSIVE hit(entity_id, layer) AS (
  SELECT rowid, 0
  FROM entity_fts
  WHERE entity_fts MATCH :query
  ORDER BY bm25(entity_fts)
  LIMIT :layer0_limit
  UNION
  SELECT l.dst_id, h.layer + 1
  FROM hit h
  JOIN link l ON l.src_id = h.entity_id
  WHERE h.layer < :max_layers
)
SELECT e.*, MIN(h.layer) AS layer
FROM hit h
JOIN entity e ON e.id = h.entity_id
GROUP BY e.id
ORDER BY layer, e.weight DESC
LIMIT :max_files;
```

Known differences to handle: Kayak uses its own stemming (`stem_key`) and tokenizer, and FTS5's `porter` tokenizer will not match it exactly. `max_matches_per_layer` is a per-source-entity limit and needs a window function or Python-side handling. Priority entities such as the target NPC sit on top of the file limit, per Kayak's documented behavior.

## 9. Campaign model

- `template.db` holds upstream data plus patches.
- Creating a campaign copies `template.db` to `campaigns/<name>.db`.
- Runtime data (generated NPCs, dialogue, stats, rumors, world events) lives only in the campaign database. Template data is never modified by gameplay.
- Switching campaigns closes one connection and opens another. No index reload is needed because FTS tables are part of the database.
- A one-time migration reads Rebirth's per-character JSON files, `world_events.txt` and `event_history.json` into the new tables.
- Alternative considered: a single database with a `campaign_id` column. Rejected for now because a missing filter would leak data between campaigns, and per-file databases are easier to back up and share.

## 10. Phases

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 0. Prep | Remove `__pycache__` from the repo, add `.gitignore`, add README credit section, obtain the official English Kayak release | Repo clean, attribution text in place |
| 1. Core store | `schema.py`, `importer.py`, `retriever.py`, `exporter.py`, test suite | Import of all 405 entities succeeds; export then re-import round-trips; retrieval results match Kayak on a fixed set of queries within documented differences |
| 2. Rebirth integration | Replace flat JSON character and event storage with the database; campaign create, switch and migrate commands | Existing campaigns migrate without data loss; chat prompts include retrieved entities; in-game F8 hub campaign switching works |
| 3. Prompt layer | Port prompt files and the token system (`<target_npc_context>` and others) | Prompts match Kayak's output for the same inputs |
| 4. Economy and extras | Price modifiers, trader inventory injection, dialogue archiving limits | Behavior matches Kayak's documented formulas |

Phases 3 and 4 are the largest. In Kayak, `token_resolver.py` is about 1,850 lines, `prompt_builder.py` about 700, and the SentientSands bridge about 1,900, compared with roughly 600 and 430 lines for the indexer and retriever.

## 11. Verification plan

- Golden tests: a fixed list of player messages run through Kayak's own retriever (from the bundled Python code) and through the new retriever, comparing returned entity sets and order.
- Round-trip test: `KayakDB` folder, to SQLite, back to folder, with a diff of normalized content.
- Migration test: a real Rebirth campaign folder migrated and then compared field by field.
- Performance check against the 500 ms `timeout_ms` default on a campaign with thousands of generated NPCs.

### Not yet verified

- The full retrieval logic in Kayak was not traced end to end. Only file layouts, headers, configuration and keyword searches were read.
- The official English template and release were not inspected, only the Russian fork's copy.
- The C++ plugin was not compiled or run. The assumption that it needs no changes depends on the server API it calls staying the same.
- The official `Starswimmer/Kayak` repository contained only a README and licence when checked, so Kayak's current server code was read from the Russian fork's bundle, which may include that author's modifications.
- The licence of the Kenshi wiki text paraphrased in lore entries.

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Retrieval drift from Kayak (stemming, ranking) | Different prompt context than upstream | Golden tests, documented differences |
| Upstream format changes (Kayak v0.4 already broke older campaigns) | Importer breaks on new releases | Version field in `meta`, importer tests per Kayak version |
| Lore licensing | Cannot distribute some data | Review wiki and game content terms before release; keep data import optional |
| Large single-file server (4,300 lines) | Hard to integrate cleanly | Keep `sentient_db` self-contained, change the server only at storage call sites |
| Missed Kayak semantics (access rules, child weights) | Silent behavior differences | Real parsers, not line splitting; dedicated tests |
| Attribution omitted | Licence non-compliance | Phase 0 deliverable, checked in release checklist |

## 13. Open questions

1. Which source is the baseline: the official English Kayak release, or another version?
2. Should the project keep Kayak's HTTP API (port 5001) for compatibility with external tools, or run only in-process?
3. Should the exporter target the exact Kayak folder format so Kayak-compatible content packs keep working?
4. Is distributing the imported lore planned, or will users run the importer against their own Kayak copy? The second option reduces licensing exposure.
5. Where should local modifications live: the `patch` table, versioned JSON files, or both?

## 14. References

- Original mod: `github.com/harvicusdev-glitch/SentientSands` (GPL-3.0, includes the C++ `src/` folder)
- Kayak source repo listed in project links: `github.com/Starswimmer/Kayak`
- Kayak on Nexus Mods: `nexusmods.com/kenshi/mods/2067`
- SentientSands on Nexus Mods: `nexusmods.com/kenshi/mods/1872`
- SentientSands on Steam Workshop: item `3675880187`
- Kayak bundle used for inspection: `github.com/Mitt776/SentientSands-RU` (Russian adaptation, GPL-3.0-or-later)
- Required credit line: "SentientSands Kayak by Harvicus and Pineaxe."
