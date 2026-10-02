# Proposal: Stable NPC IDs

Status: Draft for review

## 1. Summary

The campaign database keys each NPC by its name ([architecture.md](../info/architecture.md#campaign-storage)). Two NPCs with one name therefore share one profile and one dialogue history, a rename moves the row to a new key, and a world template can bind a figure profile to a game character only by name. This proposal keys each NPC by an ID that the game gives the character. The name stays only for display and for the LLM.

Non-goals:

- An upgrade of a campaign that is keyed by name. The rule of [proposal_data_layers.md](proposal_data_layers.md#7-campaign-model) applies: a campaign database of an earlier schema version is not upgraded.
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
| Every other character, the player's squad included | `h:<handle>` | `npc->getHandle().toString()` |

- A unique NPC has the same ID in every save and every campaign. A figure profile of a world template therefore binds to the game character by ID, not by name ([section 7](#7-world-templates)).
- Many generic NPCs share one template, so a generic NPC has no template ID of its own. Its handle is unique in a save.
- The plugin builds the ID, because only the plugin sees the game objects. The server treats the ID as an opaque string.

## 4. Data model

- `npc.storage_id` becomes `npc.npc_id`. It holds the ID of section 3 unchanged, with no sanitizing, and it does not ignore case.
- The name is only the `Name` key of the profile, so two NPCs with one name keep two rows.
- A rename changes only `Name`. `campaign_db.rename_npc` goes away.
- The change raises the schema version.

## 5. Plugin and server

- Each NPC object that the plugin sends carries `npc_id` in place of `storage_id`, and it keeps `name`. This covers the context, the chat request, the ambient request, and the nearby lists.
- The Dialogue Library (`plugin/ui/LibraryWindow.cpp`) lists the NPCs by `npc_id`, and it sends the `npc_id` in `/history`, `/favorite`, and `/regenerate_profile`.
- `LIVE_CONTEXTS` is keyed by `npc_id`.
- The speaker picker ([proposal_data_layers.md](proposal_data_layers.md#71-player-characters)) sends the `npc_id` of the speaker, and the server reads the bio of the speaker by that ID.
- The `Name|serial` text that the server sends back to the plugin does not change, because the plugin finds a live character by its serial.

## 6. Names in LLM output

The LLM names each speaker by name, for example `Beep: Hello`. The server maps a name to an `npc_id` only among the NPCs of the same request. The name assignment for generic NPCs therefore stays, because it keeps the names of one conversation apart. It is no longer part of the storage key.

## 7. World templates

- A figure file of a world template gets the key `game_id`, which holds the `stringID` of the character's template.
- The loader inserts the figure profile into `npc` under `u:<game_id>`, so the profile binds to the game character even when the player renames it.
- A figure without `game_id` has no profile in `npc`. Its entity is still found by name and alias, as in [proposal_data_layers.md](proposal_data_layers.md#6-data-model).

## 8. Acceptance criteria

- Two NPCs with one name keep separate profiles and dialogue.
- A rename keeps the row, the dialogue, and the favorite.
- A unique NPC has the same ID after a save and a load, and in a new campaign.
- A generic NPC has the same ID after a save and a load.
- A recruited NPC keeps its profile and its dialogue in the player's squad.

## 9. Not yet verified

Each chat message writes one `ID_PROBE` line for the target NPC to `SentientSands_SDK.log` (`LogNpcIdentity` in `plugin/game/Context.cpp`). The line holds the name, the handle text, the serial, the instance ID, the template `stringID` and name, and the faction. Compare the lines of one NPC before and after a save and a load, a recruit, a change of the mod list, and a reload of its town.

- Whether `hand::toString()` gives the same text after a save and a load. Kenshi stores handles in its save files.
- Whether the instance ID gives the same text after a save and a load. If it does, it can replace the handle as the ID of a generic NPC.
- Which game data field marks the template of a unique character, and whether `npc->data` is that template.
- Whether a recruited NPC keeps its handle when it joins the player's faction.
- Whether a template `stringID` stays the same when the player changes the mod list.
- Whether a generic NPC that the game unloads and loads again, for example a town guard, keeps its handle.
- Whether Kayak's `persistent_id` and `runtime_id` ([proposal_data_layers.md](proposal_data_layers.md#not-yet-verified)) are the template `stringID` and the handle. If they are, the Kayak converter can fill `game_id`.
