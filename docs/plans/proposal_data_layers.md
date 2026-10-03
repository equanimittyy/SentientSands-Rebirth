# Proposal: Data Layers: Settings, World Templates, and Campaigns

Status: Draft for review

## 1. Summary

The server mixes player settings, world lore, and play state. For example, the Vanilla Kenshi lore is a shared prompt file that every campaign uses. This proposal puts all server data into four separate classes:

- **App data** ships with the release as defaults, and each update replaces it. A player can override each system prompt. The override survives an update, and a reset restores the shipped default.
- **Settings** belong to the player. Both the gameplay settings and the LLM configuration get a reset to the shipped defaults.
- **World templates** describe a world: canon factions, canon characters, world lore entities, a lore timeline, and an overview. The release ships the SSR Vanilla template. Players export and import templates to share worlds for modded playthroughs, with custom factions and characters.
- **Campaigns** hold one playthrough in three stores: characters, factions, and world lore. Each campaign starts as a copy of a world template, and then only play and the player's edits change it.

The proposal builds on the campaign database ([architecture.md](../info/architecture.md#campaign-storage)). The C++ plugin changes only for the speaker picker in the chat window ([section 6.1](#61-player-characters)) and for the game IDs of [proposal_npc_ids.md](proposal_npc_ids.md). [proposal_web_app.md](proposal_web_app.md) adds the browser pages for templates, factions, characters, and entities.

Non-goals:

- Changes to the C++ plugin other than the speaker picker and the game IDs.
- Any use of Kayak's code, data, or folder format. SSR writes its own vanilla content ([section 7](#7-ssr-vanilla-template)).
- Starting rumors and pre-written dialogue in templates.
- Saving a campaign as a template. Play state never leaves its campaign.
- Vector search or embeddings.

## 2. Data classes

| Class | Contents | Location | On update | Default |
|---|---|---|---|---|
| App data | System prompts; UI translations, name pools, default LLM providers and models | Defaults in `server/prompts/` and `server/config/`; prompt overrides in `server/user/prompts/` | Defaults replaced; overrides kept | Shipped files, with a reset for prompts |
| Settings | Gameplay settings; LLM providers, profiles, routes, and API keys | `SentientSands_Config.ini` in the mod root; `server/user/llm_config.json` | Kept | Shipped defaults, with a reset |
| World templates | Canon factions, canon characters, world lore entities, lore timeline, overview | `server/world_templates/vanilla_kenshi/`; `server/user/world_templates/<name>/` | Vanilla replaced; user templates kept | SSR Vanilla |
| Campaigns | The character store (NPCs and player characters, with dialogue and favorites), the faction store (the player's faction included), the copied world lore, events, rumors, logs | `server/campaigns/<name>/` | Kept | Created from a template |

The INI stays in the mod root, because the plugin reads it from there at start ([architecture.md](../info/architecture.md#settings)).

Four pieces of data move to their class:

| Data | From | To | Reason |
|---|---|---|---|
| Player bio | `character_bio.txt` in each campaign | The profile of the speaking player character in the character store | Each squad member has a bio of its own ([section 6.1](#61-player-characters)). |
| Player faction description | `player_faction_description.txt` in each campaign | The player's faction in the faction store | The player's faction is a faction like any other ([section 6.2](#62-factions)). |
| Faction lore | `FACTION_METADATA` and `MAJOR_FACTIONS` in `kenshi_llm_server.py` | `factions/` of the vanilla template | A modded world must be able to replace it, and a campaign must be able to edit its copy. |
| World lore | `server/prompts/world_lore.txt` | `overview.txt` of the vanilla template | It describes the world, so a modded template must be able to replace it. |

## 3. World template format

A world template is a folder of JSON and text files. A shared template is one JSON file that holds the folder ([architecture.md](../info/architecture.md#world-templates)).

```
<template>/
  manifest.json          format version, name, version, authors, credits
  overview.txt           lore that goes into every prompt
  history.json           the lore timeline, in order
  factions/<id>.json     canon factions, copied into the faction store
  characters/<id>.json   canon characters, copied into the character store
  races/<id>.json        world lore: the races
  locations/<id>.json    world lore: cities, settlements, outposts, ruins
  regions/<id>.json      world lore: the regions of the map
  *.md, *.txt            licence and credit files, optional
```

`manifest.json`:

```json
{
  "format_version": 1,
  "name": "SSR Vanilla",
  "description": "Supports vanilla Kenshi, with compatibility for Universal Wasteland Expansion.",
  "version": "1.0.0",
  "authors": ["Sentient Sands Rebirth"],
  "credits": []
}
```

A faction file, `factions/holy_nation.json`:

```json
{
  "game_id": "<the faction's string ID in the game data>",
  "name": "Holy Nation",
  "aliases": ["Okran's faithful"],
  "major": true,
  "fields": {"leader": "Phoenix", "capital": "Blister Hill"},
  "description": "A theocracy that worships Okran..."
}
```

A character file, `characters/beep.json`:

```json
{
  "game_id": "<the string ID of the character's template in the game data>",
  "profile": {
    "Name": "Beep", "Race": "...", "Sex": "...", "Faction": "...", "Job": "...",
    "Personality": "...", "Backstory": "...", "SpeechQuirks": "..."
  }
}
```

A world lore entity file, `locations/blister_hill.json`:

```json
{
  "name": "Blister Hill",
  "aliases": [],
  "weight": 1,
  "fields": {"owner": "Holy Nation"},
  "prose": {"description": "The capital of the Holy Nation..."},
  "children": [{"name": "...", "weight": 2}],
  "access": []
}
```

`history.json`:

```json
[
  {"title": "The First Empire", "text": "..."},
  {"title": "The Second Empire", "text": "..."}
]
```

- A faction and a canon character bind to the game by `game_id`, not by name, so a rename in the game does not break the link ([proposal_npc_ids.md](proposal_npc_ids.md#7-world-templates)). `major` marks a major world power, whose members resist recruitment.
- The keys of a character's `profile` are the keys of a profile in the character store ([architecture.md](../info/architecture.md#campaign-storage)). Chat uses the canon profile instead of generating one.
- The entity ID is the file name without `.json`. The category is the folder name: `races`, `locations`, or `regions`. A template cannot add a category, so another folder is an error.
- The values in `fields` feed link expansion. The values in `prose` are retrieved text and never feed link expansion.
- `children` are weighted links to other entities by name. `access` holds the rules that decide which NPCs know the entity. Phase 5 sets its schema, with the retriever that applies it ([section 10](#10-phases-and-verification)).
- The order of `history.json` is the timeline order. The loader stores each entry as an entity of category `history`, so retrieval finds it like any entity.
- One validator runs on each load, import, and edit. It rejects an unknown `format_version`, a JSON file that does not parse, a faction or an entity without `name`, a faction or a character without `game_id`, and a character without a `Name` in its profile. A child that names no entity is a warning, not an error.

## 4. Templates on disk

Built. [architecture.md](../info/architecture.md#world-templates) describes the template folders, the routes, and the import and export of a template as one JSON file. A campaign is a folder, so a player shares or backs up a campaign by copying its folder.

## 5. Data model

Version 2 of the campaign schema that `campaign_db.py` owns has three separate stores: characters, factions, and world lore. Illustrative schema:

```sql
-- The character store: NPCs and player characters have one shape.
CREATE TABLE character (
  id         INTEGER PRIMARY KEY,
  npc_id     TEXT NOT NULL UNIQUE,  -- the game ID of proposal_npc_ids.md
  profile    TEXT NOT NULL,         -- JSON: Name, Race, Sex, Faction, Job, Personality, ...
  origin     TEXT NOT NULL DEFAULT 'campaign',  -- seed | campaign
  favorite   INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

-- The faction store: the seeded factions, the player's faction, and factions met in play.
CREATE TABLE faction (
  id          INTEGER PRIMARY KEY,
  faction_id  TEXT NOT NULL UNIQUE,  -- the faction's string ID in the game data
  name        TEXT NOT NULL,
  aliases     TEXT NOT NULL DEFAULT '[]',  -- JSON list
  major       INTEGER NOT NULL DEFAULT 0,
  fields      TEXT NOT NULL DEFAULT '{}',  -- JSON object, for example the leader
  description TEXT NOT NULL DEFAULT '',
  is_player   INTEGER NOT NULL DEFAULT 0,
  origin      TEXT NOT NULL DEFAULT 'campaign',  -- seed | campaign
  updated_at  TEXT NOT NULL
);

-- The world lore: retrieval searches only these tables.
CREATE TABLE entity (
  id         INTEGER PRIMARY KEY,
  category   TEXT NOT NULL,      -- races, locations, regions, history
  ext_id     TEXT NOT NULL,      -- the entity ID in the template
  name       TEXT NOT NULL,
  weight     REAL NOT NULL DEFAULT 1,
  seq        INTEGER,            -- timeline order of a history entry
  origin     TEXT NOT NULL DEFAULT 'seed',  -- seed | campaign
  updated_at TEXT NOT NULL,
  UNIQUE (category, ext_id)
);

CREATE TABLE field (
  entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  key       TEXT NOT NULL,
  seq       INTEGER NOT NULL DEFAULT 0,  -- a list value gives one row per item
  value     TEXT NOT NULL,
  is_prose  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (entity_id, key, seq)
);

CREATE TABLE alias (
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  alias      TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  PRIMARY KEY (entity_id, alias_norm)
);

-- Precomputed at load: a field value matches another entity's name or alias.
CREATE TABLE link (
  src_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  dst_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  via_key TEXT NOT NULL,
  PRIMARY KEY (src_id, dst_id, via_key)
);

CREATE TABLE child (
  parent_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  child_name TEXT NOT NULL,
  child_id   INTEGER REFERENCES entity(id) ON DELETE SET NULL,
  weight     REAL NOT NULL
);

CREATE TABLE access_rule (
  entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  rule      TEXT NOT NULL        -- one JSON object from the entity's access list
);

CREATE VIRTUAL TABLE entity_fts USING fts5(
  name, aliases, body,
  tokenize = 'porter unicode61'
);                               -- rowid = entity.id
```

- `meta` holds the overview and the name, version, and content hash of the template that the campaign came from.
- The dialogue rows reference `character`, as they reference `npc` today.
- Characters and factions are not world lore entities. Retrieval searches only the lore, so the many generated NPCs cannot crowd lore out of a prompt.
- Rejected: one table for characters, factions, and lore, with a flag that keeps generated characters out of retrieval. The three stores have different keys and different editors, and only the lore needs links, children, and access rules.
- `updated_at` lets the web app reject a stale save ([proposal_web_app.md](proposal_web_app.md#3-consistency)).

## 6. Campaign model

- The Campaigns tab of the web app creates a campaign from any template, and from SSR Vanilla by default.
- The server loads the template into the new campaign database in one transaction: the canon factions into the faction store, the canon characters into the character store under `u:<game_id>`, the lore entities with their fields, aliases, children, and access rules, the history entries, the links, the FTS index, and the overview.
- After creation, the campaign does not depend on its template. A template edit, a new template version, or a deleted template does not change the campaign.
- A campaign database of an earlier schema version is not upgraded. `open_campaign` refuses it and logs that the player must start a new campaign.
- The prompt takes the overview from `meta`.
- Gameplay writes only the campaign database, never a template.
- Rejected: reading the template live through `ATTACH` at query time. A template edit would then change the lore of running campaigns, and each FTS query would span two databases.
- Rejected: one database for all campaigns, with a `campaign_id` column. A missing filter would leak data between campaigns.

### 6.1 Player characters

The player picks which squad member speaks in a chat. Today the speaker is always squad slot 1 (`playerCharacters[0]`, `plugin/main.cpp:1475`), and one bio serves the whole campaign.

- The chat window gets a drop-down of the members of the current squad (`PlayerInterface::getCurrentPlatoon`, [kenshi_internals.md](../info/kenshi_internals.md#squads)). The talk target is not in the list.
- The drop-down starts on the last speaker if that character is still in the current squad, else on the first member of the current squad. The plugin keeps the last speaker in memory, so a new game session starts on the first member.
- The chat request names the speaker in its `player` field, as today (`plugin/ui/ChatWindow.cpp:377`). It also carries the speaker's context from `GetDetailedContext(speaker, "player")`. The prompt then shows the race, gender, status, and equipment of the speaker, not those of squad slot 1 in `PLAYER_CONTEXT` (`plugin/main.cpp:1247`).
- The bio is the `Personality`, `Backstory`, and `SpeechQuirks` of the speaker's profile in the character store. A speaker with no profile gets one from the `profile` task, as an NPC does (`get_character_data`). A squad member that the player recruited as an NPC keeps its profile and its dialogue.
- The Characters page of the web app edits the profile of a player character like any other profile ([proposal_web_app.md](proposal_web_app.md)).
- Ambient banter does not change. It still names squad slot 1 as the player.
- The shipped `character_bio.txt` is deleted, and a new campaign no longer gets a copy.

### 6.2 Factions

Built. Each campaign holds its own copy of the factions, and the player edits that copy on the Campaign Canon subtab of the web app's Editor tab. [architecture.md](../info/architecture.md#factions) describes the faction store.

## 7. SSR Vanilla template

SSR writes the vanilla template itself. Today the template holds the overview, 17 history entries, 80 factions, 211 characters, 7 races, 69 regions, and 164 locations.

- The facts come from the game: its data files, which the Forgotten Construction Set (FCS) opens, and play. The Kenshi wiki can help to find a fact, but no text comes from the wiki or from Kayak ([section 9](#9-licence)).
- The template of Kayak v0.5.0 ([section 13](#13-references)) is only a checklist of the records that a vanilla world needs. Phase 4 covers at least the counts in the table.
- Each faction and each canon character has its game ID. The faction IDs come from the `FACTION_PROBE` line ([kenshi_internals.md](../info/kenshi_internals.md#factions)), and the character ID is the string ID of the character's template in the game data ([proposal_npc_ids.md](proposal_npc_ids.md#3-id-format)).
- A region is a named zone of the game data (record type 95), such as Border Zone or Shem. Record type 28 is a ground texture set and type 99 is a soil type, so neither is a region. Six zones have no wiki page, no towns, and almost no data, so the template leaves them out: Akakus, Central, Desert, Empire, Rim Sands, and The Desert.
- A location is a town of the game data (record type 13) that the wiki places in a zone. The game data does not say which zone holds a town, so the zone comes from the wiki's town infobox, joined to the game data on the string ID. A camp that a zone places at random (a nest) is not a location.
- The `factions` and `animals` fields of a region hold only the squads that are in the zone at the start of a game. A squad that needs a world state other than "a character is alive", such as the death of a leader, is left out, because a new campaign does not know which states have changed. The descriptions also describe the start of a game.

| Records | Location in the template | Kayak v0.5.0 count |
|---|---|---|
| Factions | `factions/` | 23 |
| Unique NPCs | `characters/` | 64 |
| Locations: cities, settlements, outposts, ruins | `locations/` | 122, with the regions |
| Regions | `regions/` | In the locations count |
| Races | `races/` | 7 |
| World lore: eras, wars, and beliefs | `history.json` | 17 |

## 8. Retrieval design

The retriever, `server/scripts/knowledge_retrieve.py`, searches the world lore of the campaign database. The embedded Windows runtime ships SQLite 3.49.1, which has FTS5 ([development.md](../info/development.md#probes) has the check for a later runtime).

1. Extract keywords from the player message: drop the stop words, and keep at most `max_keywords`.
2. Layer 0: FTS5 match against the name, the aliases, and the fields.
3. Layers 1 to N: follow the precomputed `link` table, up to `max_layers`.
4. Rank by layer, then entity weight, then FTS rank. Apply `max_matches_per_layer` and `max_files`.
5. Apply the access rules for the speaking NPC.
6. Honor `timeout_ms` as a hard ceiling.

The limits are INI settings with these defaults: `max_keywords` 3, `max_layers` 1, `max_matches_per_layer` 3, `max_files` 4, and `timeout_ms` 500. The retrieved entities go into the prompt after the overview.

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

`max_matches_per_layer` limits the matches that each source entity adds, so it needs a window function or Python-side handling.

## 9. Licence

- Rebirth is GPLv3, as is the original SentientSands that it derives from.
- The vanilla template copies no text from Kayak or the Kenshi wiki ([section 7](#7-ssr-vanilla-template)). Kayak's attribution condition under GPLv3 section 7(b) (`Kayak/ADDITIONAL_TERMS.md`) applies only to Kayak material and works derived from it, so the template carries no Kayak credit or terms file. The wiki's licence also does not apply, because no wiki text is copied.
- The names, places, and story of Kenshi belong to Lo-Fi Games, as for any Kenshi mod.
- This document is not legal advice.

## 10. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Templates and factions | Built ([architecture.md](../info/architecture.md#world-templates)). A new campaign copies every template record, and it keeps the characters, races, locations, and regions as JSON rows until phases 2 and 5 give them their stores ([architecture.md](../info/architecture.md#campaign-canon)). | |
| 2. Characters | The character store keyed by game ID ([proposal_npc_ids.md](proposal_npc_ids.md)); canon characters from the template; the speaker picker; the Characters page; tests | The acceptance criteria of the NPC ID proposal; a canon character file gives that NPC its canon profile in a new campaign; a chat uses the bio and context of the picked speaker; a speaker with no profile gets a generated one |
| 3. Import and export | Built ([architecture.md](../info/architecture.md#world-templates)). | |
| 4. Vanilla content | The factions, characters, races, locations, regions, and world lore of the vanilla template ([section 7](#7-ssr-vanilla-template)) | The template covers at least the counts in section 7, and the validator accepts it; each faction and each canon character has its game ID; no record copies text from Kayak or the wiki |
| 5. Retrieval | `knowledge_retrieve.py`; the prompt wiring; the INI limits | For each player message in a fixed list, retrieval returns the expected entities in the expected order; chat prompts include the retrieved entities |

Phase 4 needs no other phase. The tests of phase 5 run on the vanilla content of phase 4.

Tests:

- Retrieval tests: a fixed list of player messages, each with its expected entities in order, runs on the vanilla template.
- Performance check against the 500 ms `timeout_ms` default on the full vanilla template.

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A vanilla record copies text from Kayak or the wiki | Their licence terms then apply to the template | Each record is written from the facts of the game, never from the text of Kayak or the wiki |
| A shared template carries text that steers the LLM | NPCs act against the player's intent, for example through action tags | The same trust as a Kenshi mod; the Templates page shows the authors and credits before an import |
| Attribution lost in a derived template | Licence non-compliance | A duplicate keeps the credits and the licence files; an export keeps the credits of the manifest |
| A format change | Older templates do not load | `format_version`; the loader reads each earlier version |

## 12. Open questions

1. Should the name pools (`names.json`, `generic_names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own generic NPC types and names.
2. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
3. Should retrieval also search the faction and character stores, so that a question about the Holy Nation or Beep brings their records into the prompt? Should a lore field, such as the owner of a town, link to a faction?

## 13. References

- Original mod: `github.com/harvicusdev-glitch/SentientSands` (GPL-3.0, includes the C++ `src/` folder)
- SentientSands on Nexus Mods: `nexusmods.com/kenshi/mods/1872`
- SentientSands on Steam Workshop: item `3675880187`
- Kayak, the checklist of [section 7](#7-ssr-vanilla-template): `github.com/Starswimmer/Kayak`, release `V0.41_betatest` (version 0.5.0)
