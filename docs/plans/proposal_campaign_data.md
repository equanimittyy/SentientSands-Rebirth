# Proposal: Campaign Data: Lore Retrieval, Faction Check, and Campaign Dialogue

Status: Draft for review

## 1. Summary

The campaign database, the world templates, the character store keyed by game IDs, the speaker picker, and the web editors are built ([architecture.md](../info/architecture.md#campaign-storage)). This proposal holds the work that is left:

| Part | What it adds |
|---|---|
| Lore retrieval ([section 2](#2-lore-data-model), [section 3](#3-retrieval)) | The chat prompt gets the world lore entries that the player's message names. Today no prompt reads the history, the locations, or the regions. |
| Faction check ([section 4](#4-faction-of-an-npc)) | The prompt follows an NPC that changes faction in game. |
| Campaign Dialogue ([section 5](#5-campaign-dialogue)) | The Editor of the web app shows the dialogue history and the favorite of each character. |

Non-goals:

- Vector search or embeddings.
- Raw SQL editing or a generic table editor in the web app.

## 2. Lore data model

Today an `entity` row holds the whole template record of a race, a location, or a region as JSON, and the history is one `meta` row ([architecture.md](../info/architecture.md#campaign-canon)). Retrieval needs the lore split into rows that SQLite can search and join. Illustrative schema:

```sql
CREATE TABLE entity (
  id          INTEGER PRIMARY KEY,
  category    TEXT NOT NULL,      -- races, locations, regions, history
  ext_id      TEXT NOT NULL,      -- the entity ID in the template
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  seq         INTEGER,            -- timeline order of a history entry
  origin      TEXT NOT NULL DEFAULT 'seed',
  updated_at  TEXT NOT NULL,
  UNIQUE (category, ext_id)
);

CREATE TABLE field (
  entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  key       TEXT NOT NULL,
  seq       INTEGER NOT NULL DEFAULT 0,  -- a list value gives one row per item
  value     TEXT NOT NULL,
  PRIMARY KEY (entity_id, key, seq)
);

CREATE TABLE alias (
  entity_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  alias      TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  PRIMARY KEY (entity_id, alias_norm)
);

-- Precomputed: a field value matches another entity's name or alias.
CREATE TABLE link (
  src_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  dst_id  INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  via_key TEXT NOT NULL,
  PRIMARY KEY (src_id, dst_id, via_key)
);

CREATE TABLE child (
  parent_id   INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  child_entry TEXT NOT NULL,  -- <category>/<entity ID>
  child_id    INTEGER REFERENCES entity(id) ON DELETE SET NULL,
  weight      REAL NOT NULL
);

CREATE VIRTUAL TABLE entity_fts USING fts5(
  name, aliases, body,
  tokenize = 'porter unicode61'
);                               -- rowid = entity.id
```

- The loader stores each entry of `history.json` as an entity of category `history`, in timeline order by `seq`, so retrieval finds it like any entity.
- The values in `fields` feed link expansion. The `description` is retrieved text and never feeds link expansion.
- Characters and factions are not world lore entities. Retrieval searches only the lore, so the many generated NPCs cannot crowd lore out of a prompt.
- Rejected: one table for characters, factions, and lore, with a flag that keeps generated characters out of retrieval. The three stores have different keys and different editors, and only the lore needs links and children.
- The `link` table and the `entity_fts` index derive from the fields and the aliases, so only `campaign_db` keeps them in step. The web app writes lore only through `campaign_db`, never through SQL in a route.
- The change raises the schema version, so `open_campaign` refuses each existing campaign ([architecture.md](../info/architecture.md#campaign-storage)).

## 3. Retrieval

The retriever, `server/scripts/knowledge_retrieve.py`, searches the world lore of the campaign database. The embedded Windows runtime ships SQLite 3.49.1, which has FTS5 ([development.md](../info/development.md#probes) has the check for a later runtime).

1. Extract keywords from the player message: drop the stop words, and keep at most `max_keywords`.
2. Layer 0: FTS5 match against the name, the aliases, and the fields.
3. Layers 1 to N: follow the precomputed `link` table, up to `max_layers`.
4. Rank by layer, then FTS rank. Apply `max_matches_per_layer` and `max_files`.
5. Keep only the entities that the speaking NPC knows, by its knowledge bank ([section 7](#7-open-questions)).
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
ORDER BY layer
LIMIT :max_files;
```

`max_matches_per_layer` limits the matches that each source entity adds, so it needs a window function or Python-side handling.

## 4. Faction of an NPC

The profile `Faction` is the faction that SSR tells the LLM. Today the server writes the faction that the game reports into it only while it is `Unknown` (`get_character_data`). An NPC that changes faction in game, for example a recruit, therefore keeps its old faction in the prompts.

- The server checks the faction of an NPC only when a chat or ambient banter uses the NPC. It compares the profile `Faction` with the faction in the context of that request, and it writes the profile only when the two are different.
- The server does not check on each context post. The plugin posts the context of the selected character every 1.5 s (`plugin/main.cpp:1246`), so a check there would run all the time, also for an NPC that no prompt uses.

## 5. Campaign Dialogue

A Campaign Dialogue subtab of the Editor shows the dialogue of the active campaign, as the Dialogue Library does in game. Both views stay, so the player can read the dialogue in the game or in the browser. Campaign Canon already edits the profile of each character.

- The subtab lists the same characters as the Dialogue Library ([architecture.md](../info/architecture.md#characters)), NPCs and player characters alike. The player searches the list by name.
- The subtab shows the dialogue history of the selected character and sets its favorite.

## 6. Phases and verification

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 1. Retrieval | The lore data model; `knowledge_retrieve.py`; the prompt wiring; the INI limits; tests | For each player message in a fixed list, retrieval on SSR Vanilla returns the expected entities in the expected order; chat prompts include the retrieved entities; an entity edit on Campaign Canon appears in the next prompt that retrieves it; a search finds a renamed entity; a query on the full SSR Vanilla template stays under the 500 ms `timeout_ms` default |
| 2. Faction check | The check of [section 4](#4-faction-of-an-npc); tests | A recruit's next chat prompt names its new faction; a context post alone writes no profile |
| 3. Campaign Dialogue | The subtab of [section 5](#5-campaign-dialogue) | The subtab lists the same characters and shows the same history as the Dialogue Library; a favorite set in one shows in the other |

The phases do not depend on each other.

## 7. Open questions

1. Should the name pools (`names.json`, `generic_names.json`) be customizable? The options are a player override, as for the system prompts, or a part of each world template, so that a modded template can add its own generic NPC types and names.
2. Should an existing campaign be able to take a newer version of its template, and how does that merge with `origin = 'campaign'` changes?
3. Should retrieval also search the faction and character stores, so that a question about the Holy Nation or Beep brings their records into the prompt? Should a lore field, such as the owner of a town, link to a faction?
4. What does the knowledge bank of a character hold, and how does a character get it?
5. Should the player's edit of an NPC's `Faction` on Campaign Canon survive the faction check of [section 4](#4-faction-of-an-npc)? The check replaces the edit the next time that a chat uses the NPC.
