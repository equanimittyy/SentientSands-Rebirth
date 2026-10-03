# Proposal: Stable NPC IDs

Status: Draft for review

## 1. Summary

The campaign database keys each NPC by its name ([architecture.md](../info/architecture.md#campaign-storage)). Two NPCs with one name therefore share one profile and one dialogue history, a rename moves the row to a new key, and a world template can bind a canon character to a game character only by name. This proposal keys each NPC by an ID that the game gives the character. The name stays only for display and for the LLM.

Non-goals:

- An upgrade of a campaign that is keyed by name. The rule of [proposal_data_layers.md](proposal_data_layers.md#6-campaign-model) applies: a campaign database of an earlier schema version is not upgraded.
- Matching a new character to the profile of an earlier one. A character that the game creates again, for example a guard that replaces a dead guard, is a new NPC.

## 2. Current state

| Part | Today |
|---|---|
| Plugin | `GetStorageIDFor` (`plugin/game/Context.cpp:170`) returns the name as `storage_id`. The context also carries `id`, which is the instance ID (`getInstanceID()->uid`), or `hand_<serial>` when the instance ID is empty (`Context.cpp:354-359`). |
| Server | `get_character_data` strips a `\|serial` suffix from the name and keys the profile by the name (`kenshi_llm_server.py:1359-1380`). |
| Database | `storage_id` holds the name with only its letters, digits, spaces, `_`, and `-` (`campaign_db._key`), and it ignores case. |
| Rename | `/rename` moves the row to the new name (`campaign_db.rename_npc`). |
| Name assignment | `/get_batch_identities` gives each generic NPC a unique name, so that the name can work as the key. |

## 3. ID format

| Character | ID | Source |
|---|---|---|
| A unique NPC, for example Beep | `u:<stringID>` | `npc->data->stringID`, the ID of the character's template in the game data |
| Every other character, the player's squad included | `h:<serial>` | `npc->getHandle().serial` |

- A unique NPC has the same ID in every save and every campaign. A canon character of a world template therefore binds to the game character by ID, not by name ([section 7](#7-world-templates)).
- Many generic NPCs share one template, so a generic NPC has no template ID of its own. The `serial` of its handle identifies it, because only the `serial` survives a save and a load, a town reload, and a recruit ([kenshi_internals.md](../info/kenshi_internals.md#character-identity)).
- The rest of the handle cannot be in the ID, because it names the squad of the NPC and its place in that squad, so a recruit changes it.
- The instance ID (`getInstanceID()->uid`) and the layout instance ID (`getLayoutInstanceID`) are empty for unique and generic NPCs, so neither can be the ID.
- `Character::isUnique` separates the two rows.
- The plugin builds the ID, because only the plugin sees the game objects. The server treats the ID as an opaque string.

## 4. Data model

- The `npc` table becomes the character store, `character`, keyed by `npc_id` ([proposal_data_layers.md](proposal_data_layers.md#5-data-model)). `npc_id` holds the ID of section 3 unchanged, with no sanitizing, and it does not ignore case. A player character is a row like any NPC.
- The name is only the `Name` key of the profile, so two NPCs with one name keep two rows.
- A rename changes only `Name`. `campaign_db.rename_npc` goes away.
- The change raises the schema version.

## 5. Plugin and server

- Each NPC object that the plugin sends carries `npc_id` in place of `storage_id`, and it keeps `name`. This covers the context, the chat request, the ambient request, and the nearby lists.
- The Dialogue Library (`plugin/ui/LibraryWindow.cpp`) lists the NPCs by `npc_id`, and it sends the `npc_id` in `/history`, `/favorite`, and `/regenerate_profile`.
- `LIVE_CONTEXTS` is keyed by `npc_id`.
- The speaker picker ([proposal_data_layers.md](proposal_data_layers.md#61-player-characters)) sends the `npc_id` of the speaker, and the server reads the bio of the speaker by that ID.
- The `Name|serial` text that the server sends back to the plugin does not change, because the plugin finds a live character by its serial.

## 6. Names in LLM output

The LLM names each speaker by name, for example `Beep: Hello`. The server maps a name to an `npc_id` only among the NPCs of the same request. The name assignment for generic NPCs therefore stays, because it keeps the names of one conversation apart. It is no longer part of the storage key.

## 7. World templates

- A canon character file of a world template, `characters/<id>.json`, holds `game_id`: the `stringID` of the character's template.
- The loader copies the canon profile into the character store under `u:<game_id>`, so the profile binds to the game character even when the player renames it.
- The validator rejects a character file without `game_id`, because its profile could not bind to a game character. Lore about a person whom the game does not have belongs in the world lore entities ([proposal_data_layers.md](proposal_data_layers.md#3-world-template-format)).

## 8. Acceptance criteria

- Two NPCs with one name keep separate profiles and dialogue.
- A rename keeps the row, the dialogue, and the favorite.
- A unique NPC has the same ID after a save and a load, and in a new campaign.
- A generic NPC has the same ID after a save and a load.
- A recruited NPC keeps its profile and its dialogue in the player's squad.
