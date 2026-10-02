# Proposal: Data Layers: Settings, World Templates, and Campaigns

Status: Draft for review

## 1. Summary

The server mixes player settings, world lore, and play state. For example, the Vanilla Kenshi lore is a shared prompt file that every campaign uses. This proposal puts all server data into four separate classes:

- **App data** ships with the release as defaults, and each update replaces it. A player can override each system prompt. The override survives an update, and a reset restores the shipped default.
- **Settings** belong to the player. Both the gameplay settings and the LLM configuration get a reset to the shipped defaults.
- **World templates** describe a world: entities, a lore timeline, figure profiles, and an overview. The release ships a Vanilla Kenshi template. Players export and import templates to share worlds for modded playthroughs, with custom factions and figures.
- **Campaigns** hold one playthrough. Each campaign starts as a copy of a world template, and then only play changes it.

The proposal builds on the campaign database ([architecture.md](../info/architecture.md#campaign-storage)). The C++ plugin changes only for the speaker picker in the chat window ([section 6.1](#61-player-characters)). [proposal_web_app.md](proposal_web_app.md) adds the browser pages for templates and entities.

Non-goals:

- Changes to the C++ plugin other than the speaker picker.
- Kayak's prompt token system, its economy support, and its HTTP API on port 5001.
- Export to Kayak's folder format. The Kayak converter is one-way.
- Starting rumors and pre-written dialogue in templates.
- Saving a campaign as a template. Play state never leaves its campaign.
- Vector search or embeddings.

## 2. Data classes

| Class | Contents | Location | On update | Default |
|---|---|---|---|---|
| App data | System prompts; UI translations, name pools, default LLM providers and models | Defaults in `server/prompts/` and `server/config/`; prompt overrides in `server/user/prompts/` | Defaults replaced; overrides kept | Shipped files, with a reset for prompts |
| Settings | Gameplay settings; LLM providers, profiles, routes, and API keys | `SentientSands_Config.ini` in the mod root; `server/user/llm_config.json` | Kept | Shipped defaults, with a reset |
| World templates | Entities, lore timeline, figure profiles, overview | `server/world_templates/vanilla_kenshi/`; `server/user/world_templates/<name>/` | Vanilla replaced; user templates kept | Vanilla Kenshi |
| Campaigns | NPC and player character profiles, dialogue, events, rumors, favorites, the player faction description, the copied template knowledge, logs | `server/campaigns/<name>/` | Kept | Created from a template |

The INI stays in the mod root, because the plugin reads it from there at start ([architecture.md](../info/architecture.md#settings)).

Four pieces of data move to their class:

| Data | From | To | Reason |
|---|---|---|---|
| Player bio | `character_bio.txt` in each campaign | The profile of the speaking player character in `npc` | Each squad member has a bio of its own ([section 6.1](#61-player-characters)). |
| Player faction description | `player_faction_description.txt` in each campaign | `meta` in the campaign database | It is play state, and prompts are no longer campaign-specific ([section 6.2](#62-player-faction-description)). |
| World lore | `server/prompts/world_lore.txt` | `overview.txt` of the vanilla template | It describes the world, so a modded template must be able to replace it. |
| Retrieval limits | Kayak's `core_config.txt` | The INI | They tune the server, not the world. |

## 3. World template format

A world template is a folder of JSON and text files. A shared template is the same folder in a zip file.

```
<template>/
  manifest.json          format version, name, version, authors, credits
  overview.txt           lore that goes into every prompt
  history.json           the lore timeline, in order
  entities/
    <category>/<id>.json
  *.md, *.txt            licence and credit files, optional
```

`manifest.json`:

```json
{
  "format_version": 1,
  "name": "Vanilla Kenshi",
  "version": "1.0.0",
  "authors": ["Sentient Sands Rebirth"],
  "credits": ["SentientSands Kayak by Harvicus and Pineaxe."]
}
```

An entity file, `entities/factions/holy_nation.json`:

```json
{
  "name": "Holy Nation",
  "aliases": ["Okran's faithful"],
  "weight": 1,
  "fields": {"leader": "Phoenix", "capital": "Blister Hill"},
  "prose": {"description": "A theocracy that worships Okran..."},
  "children": [{"name": "Phoenix", "weight": 2}],
  "access": []
}
```

A figure file, `entities/figures/<id>.json`, can also hold a `profile`:

```json
{
  "name": "...",
  "fields": {"faction": "..."},
  "profile": {
    "Race": "...", "Sex": "...", "Faction": "...", "Job": "...",
    "Personality": "...", "Backstory": "...", "SpeechQuirks": "..."
  }
}
```

`history.json`:

```json
[
  {"title": "The First Empire", "text": "..."},
  {"title": "The Second Empire", "text": "..."}
]
```

- The entity ID is the file name without `.json`. The category is the folder name. A modded template can add a category.
- The values in `fields` feed link expansion. The values in `prose` are retrieved text and never feed link expansion, the same as Kayak's `$` fields.
- `children` are weighted links to other entities by name. `access` holds the rules that decide which NPCs know the entity. The converter sets its schema when it parses Kayak's `[RULE]` blocks ([section 10](#not-yet-verified)).
- Only a `figures` entity can hold a `profile`. Its keys are the keys of an NPC profile in the campaign database ([architecture.md](../info/architecture.md#campaign-storage)). Chat uses this profile instead of generating one.
- The order of `history.json` is the timeline order. The loader stores each entry as an entity of category `history`, so retrieval finds it like any entity.
- One validator runs on each load, import, and edit. It rejects an unknown `format_version`, a JSON file that does not parse, an entity without `name`, and a `profile` outside `figures`. A child that names no entity is a warning, not an error.

## 4. Templates on disk

| Template | Location | Edits |
|---|---|---|
| Vanilla Kenshi | `server/world_templates/vanilla_kenshi/`, shipped | None. An update replaces it, so the player duplicates it first. |
| User templates | `server/user/world_templates/<name>/` | The web app, or by hand |

The release does not ship `server/user/`, so an update keeps the user templates.

`server/scripts/world_template.py` imports only the standard library. It holds the validator, the loader into a campaign database, and the operations below.

| Operation | Route | Behavior |
|---|---|---|
| List | `GET /api/templates` | The manifest and the entity count of each template |
| Export | `GET /api/templates/<name>/export` | A zip of the template folder |
| Import | `POST /api/templates/import` | A zip upload, with the checks below |
| Duplicate | `POST /api/templates/<name>/duplicate` | A copy as a new user template, with its credits and licence files |
| Delete | `POST /api/templates/<name>/delete` | User templates only. Campaigns made from it keep their copy. |

An imported zip comes from another player, so the import treats it as untrusted:

1. Reject an entry with an absolute path, a `..` part, or a path outside the layout in section 3.
2. Reject a zip with an uncompressed size above 50 MB or more than 10,000 entries.
3. Extract into a temporary folder in `server/user/world_templates/`, run the validator, and then rename the folder to the template name. A failed import leaves nothing behind.
4. Refuse a name that already exists. The player deletes or renames the old template first.

## 5. Data model

The knowledge tables are version 2 of the campaign schema that `campaign_db.py` owns. Illustrative schema:

```sql
CREATE TABLE entity (
  id         INTEGER PRIMARY KEY,
  category   TEXT NOT NULL,      -- factions, figures, locations, items, races, history, ...
  ext_id     TEXT NOT NULL,      -- the entity ID in the template
  name       TEXT NOT NULL,
  weight     REAL NOT NULL DEFAULT 1,
  seq        INTEGER,            -- timeline order of a history entry
  origin     TEXT NOT NULL DEFAULT 'template',  -- template | campaign
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
- The loader inserts the figure profiles into `npc` with `INSERT OR IGNORE`. A profile that the campaign already has, with its dialogue, stays.
- Generated NPCs stay in `npc` and do not become entities. If they did, every generated NPC would enter FTS and link expansion, and retrieval would return generated NPCs in place of lore.
- `npc` does not reference `entity`. When the player talks to a figure, the retriever finds its entity by name or alias.
- `updated_at` lets the web app reject a stale save ([proposal_web_app.md](proposal_web_app.md#3-consistency)).

## 6. Campaign model

- `POST /campaigns/create` takes an optional `template`, and uses Vanilla Kenshi without one. The in-game Campaign Manager sends no template, so the plugin does not change. The web app's Templates page creates a campaign from any template.
- The server loads the template into the new campaign database in one transaction: the entities with their fields, aliases, children, and access rules, the history entries, the links, the FTS index, the figure profiles, and the overview.
- After creation, the campaign does not depend on its template. A template edit, a new template version, or a deleted template does not change the campaign.
- A campaign database of an earlier schema version is not upgraded. `open_campaign` refuses it and logs that the player must start a new campaign.
- The prompt takes the overview from `meta`.
- Gameplay writes only the campaign database, never a template.
- Rejected: reading the template live through `ATTACH` at query time. A template edit would then change the lore of running campaigns, and each FTS query would span two databases.
- Rejected: one database for all campaigns, with a `campaign_id` column. A missing filter would leak data between campaigns.

### 6.1 Player characters

The player picks which squad member speaks in a chat. Today the speaker is always squad slot 1 (`playerCharacters[0]`, `plugin/main.cpp:1475`), and one bio serves the whole campaign.

- The chat window gets a drop-down of the members of the current squad (`PlayerInterface::getCurrentPlatoon`). The talk target is not in the list.
- The drop-down starts on the last speaker if that character is still in the current squad, else on the first member of the current squad. The plugin keeps the last speaker in memory, so a new game session starts on the first member.
- The chat request names the speaker in its `player` field, as today (`plugin/ui/ChatWindow.cpp:377`). It also carries the speaker's context from `GetDetailedContext(speaker, "player")`. The prompt then shows the race, gender, status, and equipment of the speaker, not those of squad slot 1 in `PLAYER_CONTEXT` (`plugin/main.cpp:1247`).
- The bio is the `Personality`, `Backstory`, and `SpeechQuirks` of the speaker's profile in `npc`. A speaker with no profile gets one from the `profile` task, as an NPC does (`get_character_data`). A squad member that the player recruited as an NPC keeps its profile and its dialogue.
- The NPCs page of the web app edits the profile of a player character like any other profile ([proposal_web_app.md](proposal_web_app.md)).
- Ambient banter does not change. It still names squad slot 1 as the player.
- The `character_bio.txt` of an existing campaign is not read and not migrated. The shipped `character_bio.txt` is deleted, and a new campaign no longer gets a copy.

### 6.2 Player faction description

- The description is the `meta` key `player_faction_description` in the campaign database. A new campaign has none, and the prompt then leaves out the faction block, as `build_system_prompt` does today for an empty file.
- The Player profile page edits only this description. `POST /player_profile` keeps its 409 check ([architecture.md](../info/architecture.md#web-app)), because the player can switch the campaign while the page is open.
- The `player_faction_description.txt` of an existing campaign is not read and not migrated. The shipped `player_faction_description.txt` is deleted, and a new campaign no longer gets a copy.

## 7. Vanilla Kenshi template

The vanilla template is a conversion of Kayak's English `KayakDB/Template` (405 entities: 29 factions, 166 items, 122 locations, 7 races, 64 unique NPCs, 17 world lore entries).

- `scripts/convert_kayak.py` is a development tool, not part of the release. It converts a Kayak template folder into a world template folder, and reports each field that it drops.
- The converted template is committed under `server/world_templates/vanilla_kenshi/`. For a newer Kayak release, the converter runs again on a branch, and git merges the result with the local fixes.
- `overview.txt` starts as today's `world_lore.txt`.
- The import source is the official English Kayak release. The inspected copy came from a Russian fork and has Russian `display_name` values.

| Kayak | World template |
|---|---|
| Entity folder name, `display_name` | `name` |
| `aliases`, `weight` | The keys of the same name |
| Other `entity.txt` fields | `fields` |
| Fields with a leading `$` | `prose` |
| Price fields (`average_price`, `base_price_cats`, `price_modifier`) | Dropped, because economy is a non-goal |
| `id`, `persistent_id`, `runtime_id` | The file name comes from `id`. The other two are dropped ([section 10](#not-yet-verified)). |
| `who_knows_me.txt` `[RULE]` blocks | `access` |
| `define_children.txt` `W = <weight> <name>` lines | `children` |
| The unique NPC category | `figures`. The Kayak fields that match profile keys fill `profile`. |
| World lore entries | `history.json`, in Kayak's order |
| `IGN_` files, `ph_` prompt files, runtime files, comments | Skipped |
| `core_config.txt` retrieval limits | The INI defaults |

## 8. Retrieval design

The retriever, `server/scripts/knowledge_retrieve.py`, follows the algorithm of Kayak's `indexer.py` and `retriever.py` on the campaign database:

1. Extract keywords from the player message with Kayak's stop-word approach, limited by `max_keywords`.
2. Layer 0: FTS5 match against the name, the aliases, and the fields.
3. Layers 1 to N: follow the precomputed `link` table, up to `max_layers`.
4. Rank by layer, then entity weight, then FTS rank. Apply `max_matches_per_layer` and `max_files`.
5. Apply the access rules for the speaking NPC.
6. Honor `timeout_ms` as a hard ceiling.

The limits are INI settings with Kayak's defaults: `max_keywords` 3, `max_layers` 1, `max_matches_per_layer` 3, `max_files` 4, and `timeout_ms` 500. The retrieved entities go into the prompt after the overview.

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

Known differences to handle: Kayak uses its own stemming (`stem_key`) and tokenizer, and FTS5's `porter` tokenizer does not match it exactly. `max_matches_per_layer` is a per-source-entity limit and needs a window function or Python-side handling. Priority entities, such as the target NPC, sit on top of the file limit, per Kayak's documented behavior.

## 9. Licence and attribution

- Kayak and SentientSands are GPLv3. Rebirth is also GPLv3, so combining them is compatible.
- Kayak adds an attribution condition under GPLv3 section 7(b) (`Kayak/ADDITIONAL_TERMS.md`). It applies when Kayak material, or a work derived from it, is conveyed to others.
- The vanilla template is derived from Kayak material, so:
  - its `manifest.json` carries the credit line "SentientSands Kayak by Harvicus and Pineaxe."
  - its folder holds a copy of `ADDITIONAL_TERMS.md`
  - a duplicate keeps both, so an exported template that derives from vanilla carries them
  - the README shows the credit line with the official project links (Nexus Mods, Steam Workshop, Kayak source repo, Discord)
- Some lore text paraphrases the Kenshi wiki, and the underlying game content belongs to Lo-Fi Games. The wiki's licence was not checked. This must be reviewed before the vanilla content ships.
- This document is not legal advice.

## 10. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 0. Prep | README credit section; the official English Kayak release | Attribution text in place; source release chosen |
| 1. Player characters | The speaker picker; the player faction description in `meta`; tests | A chat uses the bio and context of the picked speaker; a speaker with no profile gets a generated one; the Player profile page edits the faction description in `meta` |
| 2. Templates and campaigns | `world_template.py`; a vanilla template with only `overview.txt`; campaign creation from a template | New campaigns build the same prompts as today |
| 3. Import and export | The template routes; the Templates page | A template exported from one install imports on another with the same files; each unsafe zip in the tests is rejected |
| 4. Vanilla content | `convert_kayak.py`; the converted template; the licence review | All 405 entities convert; the converter lists each dropped field |
| 5. Retrieval | `knowledge_retrieve.py`; the prompt wiring; the INI limits | Retrieval matches Kayak on a fixed set of queries within documented differences; chat prompts include the retrieved entities |

Import and export come before the vanilla content, so modded templates do not wait for the licence review.

Tests:

- Golden tests: a fixed list of player messages runs through Kayak's own retriever and through the new retriever on the converted template, and the tests compare the returned entity sets and their order.
- Template round trip: a template folder, exported to a zip and imported again, gives the same files.
- Unsafe zips: an entry with `..`, an absolute path, an oversized archive, and invalid JSON are all rejected, and nothing is left on disk.
- Performance check against the 500 ms `timeout_ms` default on the full vanilla template.

### Not yet verified

- The full retrieval logic in Kayak was not traced end to end. Only the file layouts, headers, configuration, and keyword searches were read.
- The grammar of Kayak's `[RULE]` blocks, so the `access` schema is not set yet.
- What Kayak uses `persistent_id` and `runtime_id` for.
- Which Kayak fields of a unique NPC match the keys of an NPC profile.
- The official English template and release were not inspected, only the Russian fork's copy.
- The official `Starswimmer/Kayak` repository contained only a README and a licence when checked, so Kayak's server code was read from the Russian fork's bundle, which can include that author's changes.
- The licence of the Kenshi wiki text that the lore entries paraphrase.
- FTS5 in the embedded Windows Python runtime. The dev container's SQLite has it, but the Windows build was not checked.
- The KenshiLib calls for the current squad and its members (`PlayerInterface::getCurrentPlatoon`, `Character::getPlatoon`). The headers declare them, but no plugin code uses them yet.

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Lore licensing | The vanilla content cannot ship | Phases 1 to 3 do not depend on it; the vanilla template ships with only its overview until the review passes |
| A shared template carries text that steers the LLM | NPCs act against the player's intent, for example through action tags | The same trust as a Kenshi mod; the Templates page shows the authors and credits before an import |
| An unsafe zip | Files written outside the template folder, or a full disk | The import checks in section 4 |
| Attribution lost in a derived template | Licence non-compliance | A duplicate keeps the credits and the licence files; an export includes them |
| A format change | Older templates do not load | `format_version`; the loader reads each earlier version |
| Retrieval drift from Kayak (stemming, ranking) | Different prompt context than upstream | Golden tests, documented differences |

## 12. Open questions

1. Should the name pools (`names.json`, `generic_names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own generic NPC types and names.
2. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
3. Should the release include the Kayak converter, so that players can convert Kayak content packs?

## 13. References

- Original mod: `github.com/harvicusdev-glitch/SentientSands` (GPL-3.0, includes the C++ `src/` folder)
- Kayak source repo listed in the project links: `github.com/Starswimmer/Kayak`
- Kayak on Nexus Mods: `nexusmods.com/kenshi/mods/2067`
- SentientSands on Nexus Mods: `nexusmods.com/kenshi/mods/1872`
- SentientSands on Steam Workshop: item `3675880187`
- Kayak bundle used for inspection: `github.com/Mitt776/SentientSands-RU` (Russian adaptation, GPL-3.0-or-later)
- Required credit line: "SentientSands Kayak by Harvicus and Pineaxe."
